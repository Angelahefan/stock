#!/usr/bin/env python3
"""
scripts/stock_crm_client_sync.py
─────────────────────────────────────────────────────────────────────────────
Nightly sync of stock users → Twenty CRM `stockClient` objects.

Reads from Postgres (datapai schema, tables: users, watchlist, sessions,
user_scan_log, and optionally user_devices once Phase 1.10.2 ships) and
upserts one row per user into Twenty via the GraphQL API.

Only the `stockClient` object is synced in this phase. `stockPortfolio` and
`stockSignal` are deferred because their source tables (usr_holdings /
usr_portfolio_snapshots) are currently empty — they'll get their own sync
scripts when data lands there.

Env vars (all from /home/ec2-user/.env.dev):
  DATAPAI_PG_HOST / DATAPAI_PG_PORT / DATAPAI_PG_DB / DATAPAI_PG_USER / DATAPAI_PG_PASSWORD
  TWENTY_STOCK_URL
  TWENTY_STOCK_API_KEY

Usage:
  python3 scripts/stock_crm_client_sync.py [--dry-run] [--limit N]

Exit code:
  0 if all rows upserted successfully
  1 if any row failed (Airflow DAG treats this as a task failure)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

# Make lib/ importable when running as a script
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from lib.twenty_client import TwentyClient, upper_enum  # noqa: E402


# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  [%(name)s]  %(message)s",
)
log = logging.getLogger("stock_crm_client_sync")


# ── Runtime enum loading ─────────────────────────────────────────────────────
#
# Design note (2026-04-11): all enums that filter outbound values to Twenty
# are loaded from Twenty's own field metadata at sync startup. This means:
#
#   - If you add a new plan option in Twenty (or via bootstrap_twenty_objects.py),
#     this script picks it up automatically on the next run.
#   - If you rename a plan, remove a plan, or add a new market (preferredMarkets
#     MULTI_SELECT), this script picks it up automatically.
#   - No hardcoded {"WATCH", "INDIVIDUAL", ...} set anywhere in this file.
#   - Twenty IS the source of truth for its own enums — this script just
#     queries Twenty and filters accordingly.
#
# For normalization rules (e.g. NASDAQ → US exchange mapping), we DO still
# need a small config table, because those are TRANSLATION rules between the
# source domain (stock_db.watchlist.exchange) and Twenty's enum — not a
# Twenty concept. That lives in datapai.sys_common_config config_type='exchange_aliases'.
TWENTY_ENUM_SOURCE_FIELDS = [
    # (object_name_singular, field_name)
    ("stockClient", "subscriptionPlan"),
    ("stockClient", "signupSource"),
    ("stockClient", "preferredMarkets"),
    ("stockClient", "riskProfile"),
]


# ── Postgres helpers ─────────────────────────────────────────────────────────
def get_pg_conn():
    return psycopg2.connect(
        host=os.getenv("DATAPAI_PG_HOST", "localhost"),
        port=int(os.getenv("DATAPAI_PG_PORT", "5434")),
        dbname=os.getenv("DATAPAI_PG_DB", "postgres"),
        user=os.getenv("DATAPAI_PG_USER", "postgres"),
        password=os.getenv("DATAPAI_PG_PASSWORD", "postgres"),
        connect_timeout=30,
    )


def table_exists(conn, schema: str, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
            """,
            (schema, table),
        )
        return cur.fetchone() is not None


def column_exists(conn, schema: str, table: str, column: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
            """,
            (schema, table, column),
        )
        return cur.fetchone() is not None


# ── Runtime enum loader ──────────────────────────────────────────────────────
def load_twenty_enums(client: TwentyClient) -> dict[str, dict]:
    """
    Query Twenty's /metadata GraphQL for the current option values of every
    SELECT / MULTI_SELECT field we care about. Returns:

        {
          "subscriptionPlan": {"values": {"WATCH", "INDIVIDUAL", ...}, "default": "WATCH"},
          "signupSource":     {"values": {"WEB", "MOBILE_IOS", ...},    "default": "UNKNOWN"},
          "preferredMarkets": {"values": {"US", "ASX", ...},            "default": None},
          "riskProfile":      {"values": {"CONSERVATIVE", ...},         "default": "MODERATE"},
        }

    The default is the option with position=0 (or None for MULTI_SELECT).
    The field's own `defaultValue` is preferred when set (comes as "'WATCH'"
    with surrounding single quotes — we strip them).

    Implementation note (2026-04-11): Twenty's outer `objects(paging: ...)`
    query truncates nested `fields` to a small subset (observed: ~6 of 22
    fields for stockClient). To get ALL fields reliably, we must query
    per-object using `object(id: ...)` which honors the inner paging hint.
    This matches how bootstrap_twenty_objects.py fetches field lists.

    If Twenty is unreachable, returns an empty dict. transform_row() treats
    that as "accept everything" — i.e. it passes through values unchanged and
    lets Twenty reject them at write time. This means a transient Twenty
    outage doesn't silently corrupt data with wrong filtering.
    """
    # Step 1: list all objects to resolve nameSingular → id
    try:
        r = client.metadata("""
            query {
              objects(paging: { first: 200 }) {
                edges { node { id nameSingular } }
              }
            }
        """)
    except Exception as e:
        log.warning("load_twenty_enums: object list query failed: %s — enum filters disabled", e)
        return {}

    name_to_id: dict[str, str] = {}
    for e in r.get("objects", {}).get("edges", []):
        n = e["node"]
        name_to_id[n["nameSingular"]] = n["id"]

    # Step 2: per-object query for the full field list (only for objects we need)
    wanted_objects = {obj_name for obj_name, _ in TWENTY_ENUM_SOURCE_FIELDS}
    fields_by_object: dict[str, dict] = {}  # object_name → {field_name: field_dict}

    for obj_name in wanted_objects:
        obj_id = name_to_id.get(obj_name)
        if not obj_id:
            log.warning("load_twenty_enums: object %s not found in Twenty", obj_name)
            continue
        try:
            r = client.metadata(
                """
                query Fields($objectId: UUID!) {
                  object(id: $objectId) {
                    id
                    nameSingular
                    fields(paging: { first: 200 }) {
                      edges {
                        node {
                          id name type options defaultValue
                        }
                      }
                    }
                  }
                }
                """,
                {"objectId": obj_id},
            )
        except Exception as e:
            log.warning("load_twenty_enums: fields query for %s failed: %s", obj_name, e)
            continue
        fields = {
            fe["node"]["name"]: fe["node"]
            for fe in r.get("object", {}).get("fields", {}).get("edges", [])
        }
        fields_by_object[obj_name] = fields

    # Step 3: extract the target (object, field) pairs
    out: dict[str, dict] = {}
    for object_name, field_name in TWENTY_ENUM_SOURCE_FIELDS:
        fields = fields_by_object.get(object_name, {})
        field = fields.get(field_name)
        if not field:
            log.warning(
                "load_twenty_enums: field %s.%s not found (object has fields: %s)",
                object_name, field_name, sorted(fields.keys()),
            )
            continue
        options = field.get("options") or []
        if not options:
            # Not a SELECT / MULTI_SELECT — skip
            continue
        values = {opt["value"] for opt in options if opt.get("value")}

        # Default: prefer field.defaultValue (stripped of quotes), else position 0
        default: str | None = None
        default_raw = field.get("defaultValue")
        if default_raw and isinstance(default_raw, str):
            default = default_raw.strip("'\"") or None
        if default is None and field.get("type") == "SELECT":
            # Fall back to position 0
            ordered = sorted(options, key=lambda o: o.get("position") or 0)
            if ordered:
                default = ordered[0].get("value")
        out[field_name] = {"values": values, "default": default}

    log.info("Loaded Twenty enums from live field metadata:")
    for fname, info in out.items():
        vals = sorted(info["values"])
        log.info("  %s: default=%r, values=%s", fname, info["default"], vals)
    return out


def load_exchange_aliases(conn) -> dict[str, str]:
    """
    Load source→Twenty exchange-name normalization map from sys_common_config
    (config_type='exchange_aliases'). Falls back to a minimal hardcoded map if
    the config table is empty or unreachable.

    Example rows in sys_common_config:
        config_type='exchange_aliases', config_key='NASDAQ', config_value='US'
        config_type='exchange_aliases', config_key='NYSE',   config_value='US'
        config_type='exchange_aliases', config_key='AMEX',   config_value='US'
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT config_key, config_value
                FROM datapai.sys_common_config
                WHERE config_type = 'exchange_aliases'
                  AND (effective_from IS NULL OR effective_from <= CURRENT_DATE)
                  AND (effective_to   IS NULL OR effective_to   >  CURRENT_DATE)
                """
            )
            rows = cur.fetchall()
        aliases = {k.upper(): v.upper() for k, v in rows} if rows else {}
        if aliases:
            log.info("Loaded exchange aliases from sys_common_config: %s", aliases)
            return aliases
    except Exception as e:
        log.warning("load_exchange_aliases: query failed: %s — using hardcoded fallback", e)

    # Fallback — only used if config table is empty on first run.
    fallback = {"NASDAQ": "US", "NYSE": "US", "AMEX": "US"}
    log.info("Using hardcoded fallback exchange aliases: %s", fallback)
    return fallback


# ── Extraction ───────────────────────────────────────────────────────────────
def fetch_users(conn, *, has_signup_source: bool, has_user_devices: bool) -> list[dict]:
    """
    Build one row per user with all the fields the sync needs, using two
    LEFT JOINs (preferredMarkets and monthlyQueryCount) and one subquery per
    user (lastLoginAt). Conditionally includes signup_source and user_devices
    if their columns/tables exist.
    """
    signup_source_expr = "u.signup_source" if has_signup_source else "'UNKNOWN' AS signup_source"
    device_count_expr = (
        "COALESCE(ud.device_count, 0) AS device_count"
        if has_user_devices
        else "0 AS device_count"
    )

    device_count_join = (
        """
        LEFT JOIN (
            SELECT user_id, COUNT(*)::int AS device_count
            FROM datapai.user_devices
            WHERE disabled_at IS NULL
            GROUP BY user_id
        ) ud ON ud.user_id = u.id
        """
        if has_user_devices
        else ""
    )

    sql = f"""
        SELECT
            u.id AS user_id,
            u.email,
            u.plan,
            u.plan_status,
            u.created_at AS user_created_at_text,
            {signup_source_expr if has_signup_source else "'unknown' AS signup_source"},
            COALESCE(wm.exchanges, '{{}}'::text[]) AS watchlist_exchanges,
            COALESCE(sm.monthly_scans, 0) AS monthly_scans,
            ll.last_login_at,
            {device_count_expr}
        FROM datapai.users u
        LEFT JOIN (
            SELECT user_id, array_agg(DISTINCT exchange ORDER BY exchange) AS exchanges
            FROM datapai.watchlist
            WHERE exchange IS NOT NULL
            GROUP BY user_id
        ) wm ON wm.user_id = u.id
        LEFT JOIN (
            SELECT user_id, COUNT(*)::int AS monthly_scans
            FROM datapai.user_scan_log
            WHERE scanned_at > NOW() - INTERVAL '30 days'
            GROUP BY user_id
        ) sm ON sm.user_id = u.id
        LEFT JOIN (
            SELECT user_id, MAX(created_at::timestamptz) AS last_login_at
            FROM datapai.sessions
            GROUP BY user_id
        ) ll ON ll.user_id = u.id
        {device_count_join}
        ORDER BY u.created_at
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


# ── Transform ────────────────────────────────────────────────────────────────
def transform_row(
    row: dict,
    *,
    twenty_enums: dict[str, dict],
    exchange_aliases: dict[str, str],
) -> dict:
    """Postgres row → Twenty stockClient mutation payload.

    Both `twenty_enums` and `exchange_aliases` are DB-driven (the former from
    Twenty field metadata, the latter from sys_common_config). No hardcoded
    plan/market/signup_source sets in this function.
    """
    # ── preferredMarkets: alias + filter against Twenty's current enum ──
    markets_enum = (twenty_enums.get("preferredMarkets") or {}).get("values") or set()
    markets: list[str] = []
    for ex in row["watchlist_exchanges"] or []:
        if not ex:
            continue
        ex_upper = ex.upper()
        ex_upper = exchange_aliases.get(ex_upper, ex_upper)
        if markets_enum and ex_upper not in markets_enum:
            # Twenty doesn't know this exchange yet — skip silently.
            # (Log at DEBUG, not WARNING, to avoid spam if watchlist has new exchanges.)
            log.debug("dropping unknown exchange %s for %s", ex_upper, row["email"])
            continue
        if ex_upper not in markets:
            markets.append(ex_upper)

    # ── subscriptionPlan: normalize + filter against Twenty's current enum ──
    plan_info = twenty_enums.get("subscriptionPlan") or {}
    plan_values = plan_info.get("values") or set()
    plan_default = plan_info.get("default")

    plan_raw = row.get("plan")
    plan = upper_enum(plan_raw) if plan_raw else plan_default
    if plan_values and plan not in plan_values:
        log.warning(
            "user %s has plan %r (normalized %r) not in Twenty enum %s; defaulting to %r",
            row["email"], plan_raw, plan, sorted(plan_values), plan_default,
        )
        plan = plan_default

    # ── signupSource: normalize + filter against Twenty's current enum ──
    signup_info = twenty_enums.get("signupSource") or {}
    signup_values = signup_info.get("values") or set()
    signup_default = signup_info.get("default")

    signup_raw = row.get("signup_source") or signup_default or "UNKNOWN"
    signup = upper_enum(signup_raw)
    if signup_values and signup not in signup_values:
        signup = signup_default

    payload: dict[str, Any] = {
        "email": row["email"],
        "subscriptionPlan": plan,
        "signupSource": signup,
        "preferredMarkets": markets,
        "deviceCount": int(row.get("device_count") or 0),
        "monthlyQueryCount": int(row.get("monthly_scans") or 0),
    }

    # lastLoginAt — only set if we have a value. Twenty wants strict
    # `YYYY-MM-DDTHH:mm:ssZ` (no microseconds, `Z` not `+00:00`), so we format
    # the datetime explicitly rather than relying on .isoformat().
    last_login = row.get("last_login_at")
    if last_login is not None:
        if isinstance(last_login, datetime):
            if last_login.tzinfo is None:
                last_login = last_login.replace(tzinfo=timezone.utc)
            else:
                last_login = last_login.astimezone(timezone.utc)
            payload["lastLoginAt"] = last_login.strftime("%Y-%m-%dT%H:%M:%SZ")

    return payload


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="Sync stock users to Twenty CRM stockClient")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without writing to Twenty")
    parser.add_argument("--limit", type=int, default=0, help="Only sync the first N users (0 = all)")
    args = parser.parse_args()

    # Twenty connectivity
    try:
        twenty = TwentyClient.from_env()
    except Exception as e:
        log.error("TwentyClient init failed: %s", e)
        return 1
    if not args.dry_run and not twenty.ping():
        log.error("Twenty ping failed — aborting")
        return 1

    # Load DB-driven enum values from Twenty's live field metadata.
    # No hardcoded plan/market/signup-source sets anywhere below.
    twenty_enums = load_twenty_enums(twenty)

    # Postgres source
    try:
        conn = get_pg_conn()
    except Exception as e:
        log.error("Postgres connect failed: %s", e)
        return 1

    try:
        # Load DB-driven exchange-name aliases (NASDAQ->US etc.) from sys_common_config
        exchange_aliases = load_exchange_aliases(conn)

        has_signup_source = column_exists(conn, "datapai", "users", "signup_source")
        has_user_devices = table_exists(conn, "datapai", "user_devices")
        log.info(
            "source schema probes: users.signup_source=%s, user_devices=%s",
            has_signup_source, has_user_devices,
        )

        users = fetch_users(
            conn,
            has_signup_source=has_signup_source,
            has_user_devices=has_user_devices,
        )
        log.info("fetched %d users from datapai.users", len(users))

        if args.limit > 0:
            users = users[: args.limit]
            log.info("limiting to first %d users", args.limit)

        payloads = [
            transform_row(
                u,
                twenty_enums=twenty_enums,
                exchange_aliases=exchange_aliases,
            )
            for u in users
        ]
    finally:
        conn.close()

    if args.dry_run:
        log.info("── dry run — %d payloads ──", len(payloads))
        for p in payloads:
            log.info("  %s", p)
        return 0

    # Upsert loop
    start = time.time()
    known_fields = [
        "id", "email", "subscriptionPlan", "signupSource", "preferredMarkets",
        "deviceCount", "monthlyQueryCount", "lastLoginAt",
    ]
    result = twenty.bulk_upsert(
        object_name_singular="stockClient",
        object_name_plural="stockClients",
        rows=payloads,
        dedup_field="email",
        known_fields=known_fields,
    )
    elapsed = time.time() - start

    log.info(
        "── summary: created=%d updated=%d failed=%d in %.1fs ──",
        result["created"], result["updated"], result["failed"], elapsed,
    )
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    # Load .env.dev so the script is runnable standalone (outside Airflow)
    for p in [Path("/home/ec2-user/.env.dev"), Path.home() / ".env.dev"]:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break
    sys.exit(main())
