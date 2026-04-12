"""
scripts/lib/twenty_client.py
─────────────────────────────────────────────────────────────────────────────
Thin GraphQL client for Twenty CRM v1.21+ — used by the stock CRM sync DAG
and (future) the AI chatbot tool-call layer.

Twenty exposes two GraphQL endpoints:
  - /metadata : schema/object/field management + system queries
  - /graphql  : workspace data (records in stockClient, person, company, etc.)

This client wraps both with a single API-key bearer token (generated via the
Twenty UI Settings → APIs & Webhooks, or programmatically via createApiKey +
generateApiKeyToken as we did in Phase 1.4.6b).

Auth:
  Authorization: Bearer $TWENTY_STOCK_API_KEY

Design goals:
  1. Tiny dependency surface — only httpx (already in the platform requirements)
  2. Same logging + retry style as db_helpers.py
  3. Idempotent upsert by arbitrary dedup field (not just id)
  4. Batch-aware — Twenty supports array create mutations natively
  5. Enum normalisation helper — Twenty SELECT values must be UPPER_SNAKE_CASE,
     but Postgres check constraints are lowercase; the sync script can call
     this once per field value instead of sprinkling .upper() everywhere

Usage:
    from scripts.lib.twenty_client import TwentyClient, upper_enum
    client = TwentyClient.from_env()                  # reads env vars
    client.ping()                                     # smoke test

    existing = client.find_one("stockClient", filter={"email": {"eq": "donny@datap.ai"}},
                               fields=["id", "email", "subscriptionPlan"])
    if existing:
        client.update_record("stockClient", existing["id"], {"deviceCount": 2})
    else:
        client.create_record("stockClient", {
            "email": "donny@datap.ai",
            "signupSource": upper_enum("web"),        # -> "WEB"
            "subscriptionPlan": upper_enum("individual"),
        })

    # Bulk upsert (used by the sync DAG)
    result = client.bulk_upsert(
        "stockClient",
        rows=[
            {"email": "a@x.com", "deviceCount": 1},
            {"email": "b@x.com", "deviceCount": 3},
        ],
        dedup_field="email",
    )
    # result = {"created": N, "updated": M, "failed": K}
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Iterable

import httpx


logger = logging.getLogger(__name__)


# ── Enum helper ──────────────────────────────────────────────────────────────
def upper_enum(value: str | None) -> str | None:
    """
    Normalise a string to UPPER_SNAKE_CASE for Twenty SELECT / MULTI_SELECT
    values. Twenty rejects anything else with `INVALID_FIELD_INPUT`.

    Examples:
      'web'          -> 'WEB'
      'mobile_ios'   -> 'MOBILE_IOS'
      'individual'   -> 'INDIVIDUAL'
      'MarketIntel'  -> 'MARKET_INTEL'
      'Strong Sell'  -> 'STRONG_SELL'
    """
    if value is None:
        return None
    s = str(value)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)  # CamelCase boundary
    s = re.sub(r"[^A-Za-z0-9]+", "_", s)           # spaces, punctuation
    return s.upper().strip("_")


# ── Exceptions ───────────────────────────────────────────────────────────────
class TwentyError(RuntimeError):
    """Raised when a GraphQL response contains errors we cannot recover from."""


class TwentyAuthError(TwentyError):
    """Raised on 401/403 — API key invalid or missing permissions."""


class TwentyBadInputError(TwentyError):
    """Raised on GraphQL BAD_USER_INPUT / VALIDATION_FAILED / METADATA_VALIDATION_FAILED
    — these are permanent per-row failures and are NEVER retried."""


# ── Client ───────────────────────────────────────────────────────────────────
class TwentyClient:
    """
    Thin GraphQL client for Twenty CRM.

    Prefer TwentyClient.from_env() unless you need explicit config (tests, etc.).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_backoff_sec: float = 1.0,
    ):
        if not api_key:
            raise TwentyAuthError("api_key is empty")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_sec = retry_backoff_sec
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    @classmethod
    def from_env(cls) -> "TwentyClient":
        base = os.environ.get("TWENTY_STOCK_URL", "https://crm-stock.datap.ai")
        key = os.environ.get("TWENTY_STOCK_API_KEY", "")
        return cls(base, key)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TwentyClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── Low-level GraphQL ────────────────────────────────────────────────────
    def _post(self, path: str, query: str, variables: dict | None = None) -> dict:
        """POST a GraphQL query/mutation to /graphql or /metadata."""
        url = f"{self.base_url}{path}"
        payload = {"query": query, "variables": variables or {}}

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self._client.post(url, json=payload)
                if r.status_code in (401, 403):
                    raise TwentyAuthError(f"{r.status_code} from {path}: {r.text[:200]}")
                if r.status_code >= 500:
                    raise TwentyError(f"{r.status_code} from {path}: {r.text[:200]}")
                data = r.json()
                if "errors" in data:
                    # Classify the error so we don't retry permanent 4xx-class failures.
                    codes = {
                        (err.get("extensions") or {}).get("code")
                        for err in data["errors"]
                    }
                    msg = f"GraphQL errors from {path}: {data['errors']}"
                    if codes & {
                        "BAD_USER_INPUT",
                        "VALIDATION_FAILED",
                        "METADATA_VALIDATION_FAILED",
                        "FORBIDDEN",
                        "UNAUTHENTICATED",
                    }:
                        raise TwentyBadInputError(msg)
                    raise TwentyError(msg)
                return data["data"]
            except (httpx.HTTPError, TwentyError) as e:
                last_err = e
                if isinstance(e, (TwentyAuthError, TwentyBadInputError)):
                    # Permanent errors — bail immediately
                    raise
                if attempt < self.max_retries:
                    sleep_for = self.retry_backoff_sec * (2 ** (attempt - 1))
                    logger.warning(
                        "twenty %s attempt %d/%d failed: %s — retrying in %.1fs",
                        path, attempt, self.max_retries, e, sleep_for,
                    )
                    time.sleep(sleep_for)
                    continue
                logger.error("twenty %s failed after %d attempts: %s", path, self.max_retries, e)
        assert last_err is not None
        raise last_err

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        """POST to /graphql (workspace-scoped record queries)."""
        return self._post("/graphql", query, variables)

    def metadata(self, query: str, variables: dict | None = None) -> dict:
        """POST to /metadata (object/field/role queries + mutations)."""
        return self._post("/metadata", query, variables)

    # ── Smoke test ───────────────────────────────────────────────────────────
    def ping(self) -> bool:
        """Return True if the API key is valid and the workspace responds."""
        try:
            self.metadata("query { objects(paging: { first: 1 }) { edges { node { id } } } }")
            return True
        except TwentyError as e:
            logger.error("twenty ping failed: %s", e)
            return False

    # ── Record queries (/graphql) ────────────────────────────────────────────
    def find_one(
        self,
        object_name_plural: str,
        *,
        filter: dict[str, Any] | None = None,
        fields: Iterable[str] = ("id",),
    ) -> dict | None:
        """
        Return a single record matching `filter`, or None.

        `object_name_plural` is the GraphQL query field name — e.g. "stockClients"
        for the stockClient object, "people" for the built-in Person object.

        `filter` uses Twenty's filter shape, e.g. {"email": {"eq": "donny@datap.ai"}}.

        `fields` is the GraphQL selection set for `node { ... }`.
        """
        fields_selection = " ".join(fields)
        query = f"""
        query FindOne($filter: {_filter_type(object_name_plural)}) {{
          {object_name_plural}(filter: $filter, first: 1) {{
            edges {{ node {{ {fields_selection} }} }}
          }}
        }}
        """
        data = self.graphql(query, {"filter": filter or {}})
        edges = data.get(object_name_plural, {}).get("edges", [])
        return edges[0]["node"] if edges else None

    def find_many(
        self,
        object_name_plural: str,
        *,
        filter: dict[str, Any] | None = None,
        fields: Iterable[str] = ("id",),
        first: int = 100,
    ) -> list[dict]:
        """Return up to `first` records matching `filter`. Does NOT paginate."""
        fields_selection = " ".join(fields)
        query = f"""
        query FindMany($filter: {_filter_type(object_name_plural)}, $first: Int) {{
          {object_name_plural}(filter: $filter, first: $first) {{
            edges {{ node {{ {fields_selection} }} }}
            totalCount
          }}
        }}
        """
        data = self.graphql(query, {"filter": filter or {}, "first": first})
        return [e["node"] for e in data.get(object_name_plural, {}).get("edges", [])]

    def create_record(
        self,
        object_name_singular: str,
        data: dict[str, Any],
        *,
        return_fields: Iterable[str] = ("id",),
    ) -> dict:
        """Create a single record. Returns the fields in `return_fields`."""
        mutation_name = f"create{_capitalize_first(object_name_singular)}"
        input_type = f"{_capitalize_first(object_name_singular)}CreateInput!"
        fields_selection = " ".join(return_fields)
        query = f"""
        mutation Create($data: {input_type}) {{
          {mutation_name}(data: $data) {{ {fields_selection} }}
        }}
        """
        result = self.graphql(query, {"data": data})
        return result[mutation_name]

    def update_record(
        self,
        object_name_singular: str,
        record_id: str,
        data: dict[str, Any],
        *,
        return_fields: Iterable[str] = ("id",),
    ) -> dict:
        """Update a single record by id."""
        mutation_name = f"update{_capitalize_first(object_name_singular)}"
        input_type = f"{_capitalize_first(object_name_singular)}UpdateInput!"
        fields_selection = " ".join(return_fields)
        query = f"""
        mutation Update($id: UUID!, $data: {input_type}) {{
          {mutation_name}(id: $id, data: $data) {{ {fields_selection} }}
        }}
        """
        result = self.graphql(query, {"id": record_id, "data": data})
        return result[mutation_name]

    def delete_record(self, object_name_singular: str, record_id: str) -> dict:
        """Soft-delete a single record by id."""
        mutation_name = f"delete{_capitalize_first(object_name_singular)}"
        query = f"""
        mutation Delete($id: UUID!) {{
          {mutation_name}(id: $id) {{ id }}
        }}
        """
        result = self.graphql(query, {"id": record_id})
        return result[mutation_name]

    # ── Upsert primitive (used heavily by sync DAGs) ─────────────────────────
    def upsert_by_field(
        self,
        object_name_singular: str,
        object_name_plural: str,
        dedup_field: str,
        row: dict[str, Any],
        *,
        known_fields: Iterable[str] = ("id",),
    ) -> tuple[str, dict]:
        """
        Find-or-create a record by a unique field (e.g. email).

        Returns a tuple:
          ("created", {...record}) if the record was created
          ("updated", {...record}) if it existed and was updated
        """
        dedup_value = row.get(dedup_field)
        if dedup_value is None:
            raise ValueError(f"row missing dedup field {dedup_field}: {row}")

        existing = self.find_one(
            object_name_plural,
            filter={dedup_field: {"eq": dedup_value}},
            fields=known_fields,
        )
        if existing:
            # Strip the dedup field from the update payload — Twenty won't allow
            # updating a unique key to its current value in some versions, and
            # it's unnecessary anyway.
            update_payload = {k: v for k, v in row.items() if k != dedup_field}
            if not update_payload:
                return "updated", existing
            result = self.update_record(
                object_name_singular, existing["id"], update_payload, return_fields=known_fields,
            )
            return "updated", result
        else:
            result = self.create_record(object_name_singular, row, return_fields=known_fields)
            return "created", result

    def bulk_upsert(
        self,
        object_name_singular: str,
        object_name_plural: str,
        rows: list[dict[str, Any]],
        dedup_field: str,
        *,
        known_fields: Iterable[str] = ("id",),
    ) -> dict[str, int]:
        """
        Upsert many rows by a unique field. Logs per-row failures and
        continues — does NOT abort on a single bad row.

        Returns: {"created": N, "updated": M, "failed": K}
        """
        created = updated = failed = 0
        for row in rows:
            try:
                kind, _ = self.upsert_by_field(
                    object_name_singular,
                    object_name_plural,
                    dedup_field,
                    row,
                    known_fields=known_fields,
                )
                if kind == "created":
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                failed += 1
                logger.error(
                    "upsert failed for %s %s=%s: %s",
                    object_name_singular, dedup_field, row.get(dedup_field), e,
                )
        return {"created": created, "updated": updated, "failed": failed}


# ── Internal helpers ─────────────────────────────────────────────────────────
def _capitalize_first(s: str) -> str:
    """stockClient -> StockClient."""
    return s[:1].upper() + s[1:]


def _filter_type(object_name_plural: str) -> str:
    """
    Twenty's auto-generated filter input type name follows the pattern
    `{PascalCaseSingular}FilterInput`. For plural 'stockClients' the type is
    'StockClientFilterInput'. This helper assumes a simple -s plural.
    """
    singular = object_name_plural[:-1] if object_name_plural.endswith("s") else object_name_plural
    return f"{_capitalize_first(singular)}FilterInput"
