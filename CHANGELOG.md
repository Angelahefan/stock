# datapai-stock-be — CHANGELOG

## 2026-04-11 — Phase 1.10 → Phase 4B (dual-write, Twenty CRM, push notifications, DB-driven refactor)

**Detailed journal**: [docs/phase-journals/2026-04-11-phase-1.10-to-4b.md](docs/phase-journals/2026-04-11-phase-1.10-to-4b.md)

### Added

- **`scripts/send_alerts.py`** — Expo push notification channel alongside the existing Telegram loop. New functions: `_get_push_users_and_devices`, `_send_expo_push`, `_disable_invalid_push_token`, `_load_push_daily_limits`. DB-driven daily budget per user plan via `sys_common_config.push_limits`. Graceful FDW-bypass for writes via new `_get_framework_conn` helper (direct connection to framework_db).
- **`scripts/stock_crm_client_sync.py`** — full DB-driven refactor. `load_twenty_enums(client)` queries Twenty's own field metadata per-object at runtime (subscriptionPlan, signupSource, preferredMarkets, riskProfile). `load_exchange_aliases(conn)` reads `sys_common_config` with `config_type='exchange_aliases'`. No hardcoded business data remains in the script.
- **`scripts/run_stock_crm_client_sync.sh`** — shell wrapper for Airflow DAG integration.
- **`scripts/lib/twenty_client.py`** — `httpx`-based GraphQL client with `find_one`, `find_many`, `create_record`, `update_record`, `upsert_by_field`, `bulk_upsert`, `upper_enum()` helper, `TwentyBadInputError` for permanent-failure short-circuit.
- **`docs/phase-journals/2026-04-11-phase-1.10-to-4b.md`** — comprehensive session journal (600+ lines) covering 8 phases.
- **`docs/operator-runbook.md`** — "zero code changes required" reference for business-config edits (push limits, plans, exchanges, channels, feature flags).
- **`docs/architecture/fdw-gotchas.md`** — permanent reference for the 4 postgres_fdw + schema grant gotchas discovered this session.
- **`migrations/040_phase_1_10_dual_write.sql`** — `datapai.users.signup_source` column + `datapai.user_devices` table + FDW alias refresh + schema grants for `auth_service` role.
- **`migrations/041_phase_4b_push_limits_config.sql`** — 5 `push_limits` config rows (watch=5, individual=20, professional=50, business=100, default=5).
- **`migrations/042_phase_4b_exchange_aliases_config.sql`** — 3 `exchange_aliases` config rows (NASDAQ/NYSE/AMEX → US).

### Fixed

- **Pre-existing `_log_notification` FDW gotcha** in `scripts/send_alerts.py`. The original code used `INSERT INTO datapai.notification_log (user_id, channel, ...) VALUES (...)` which looked correct for a normal table but was broken because `notification_log` is a postgres_fdw foreign-table alias on stock_db. `postgres_fdw` always sends the full column list with NULL for unspecified columns, bypassing the remote-side `DEFAULT gen_random_uuid()` / `nextval()` / `NOW()` clauses. The bug was dormant until the first user linked a notification channel (which happened during this session's Phase 4A Telegram work). Fix: route writes through a direct framework_db connection via the new `_get_framework_conn()` helper.
- **Twenty `stockClient.subscriptionPlan` enum drift** — options were set to `[WATCH, INDIVIDUAL, TEAM, ENTERPRISE]` but the real plans in `datapai.sys_pricing_tiers.tier_id` are `[watch, individual, professional, business]`. Live metadata update via `/metadata` GraphQL `updateOneField` mutation: removed TEAM/ENTERPRISE, added PROFESSIONAL/BUSINESS, kept WATCH/INDIVIDUAL with their original UUIDs so existing records (donny's INDIVIDUAL value) are untouched.

### Changed

- **Telegram bot now live**: `@datapai_stock_bot`, token in `.env.dev` under `TELEGRAM_BOT_TOKEN` + `TELEGRAM_BOT_USERNAME`. Donny's chat_id `8678243225` linked in `datapai.usr_notification_prefs`. Test message delivered end-to-end.
- **Python compat**: `from __future__ import annotations` added to `send_alerts.py` so the modern `list[dict]` type hints work on the Python 3.8 EC2 host (Airflow runs 3.11 inside the container but host CLI runs 3.8).

### Config rows added to `datapai.sys_common_config`

| config_type | config_key | config_value |
|---|---|---|
| push_limits | watch_daily_limit | 5 |
| push_limits | individual_daily_limit | 20 |
| push_limits | professional_daily_limit | 50 |
| push_limits | business_daily_limit | 100 |
| push_limits | default_daily_limit | 5 |
| exchange_aliases | NASDAQ | US |
| exchange_aliases | NYSE | US |
| exchange_aliases | AMEX | US |

### Dependencies

No new Python dependencies added. Uses stdlib `urllib.request` for Expo Push API, `psycopg2` (existing), `httpx` (existing in `twenty_client.py`).
