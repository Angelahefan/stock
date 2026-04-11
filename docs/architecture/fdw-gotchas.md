# Postgres FDW gotchas — `stock_db` ↔ `framework_db`

> **Who this is for**: engineers writing scripts that read or write to user-facing tables (`datapai.users`, `datapai.user_devices`, `datapai.notification_log`, `datapai.watchlist`, `datapai.sessions`, etc.) from the stock-be codebase.
>
> **TL;DR**: These tables are **foreign-table aliases** on `stock_db`, not real tables. The real tables live in `framework_db`. Reads are fine (transparent). Writes have three subtle traps documented here.

---

## The layout

```
┌──────────────────────────────────────────────────────┐
│  datapai_framework_db (port 5433)                    │
│  db: datapai_auth_db                                 │
│                                                      │
│  schema: auth  — SSO layer                           │
│    auth.users, auth.sessions, auth.audit_log, ...    │
│                                                      │
│  schema: datapai  — REAL user-facing tables          │
│    datapai.users                 ← REAL              │
│    datapai.user_devices          ← REAL              │
│    datapai.notification_log      ← REAL              │
│    datapai.watchlist             ← REAL              │
│    datapai.sessions              ← REAL              │
│    datapai.user_scan_log         ← REAL              │
│    datapai.sys_common_config     ← REAL              │
│    datapai.sys_pricing_tiers     ← REAL              │
│    ... (28 user-facing tables)                       │
└──────────────────────────────────────────────────────┘
                           ▲
                           │ postgres_fdw (server: framework_db)
                           │ user_mapping: postgres / auth_root_2026
                           │
┌──────────────────────────────────────────────────────┐
│  datapai_stock_db (port 5434)                        │
│  db: postgres                                        │
│                                                      │
│  schema: datapai                                     │
│    datapai.users                 ← FOREIGN ALIAS     │
│    datapai.user_devices          ← FOREIGN ALIAS     │
│    datapai.notification_log      ← FOREIGN ALIAS     │
│    datapai.watchlist             ← FOREIGN ALIAS     │
│    ... (28 foreign aliases)                          │
│                                                      │
│    datapai.prices_*              ← REAL              │
│    datapai.ohlcv_intraday_*      ← REAL              │
│    datapai.stock_synthesis       ← REAL              │
│    datapai.screener_metrics      ← REAL              │
│    datapai.usr_notification_prefs ← REAL (exception) │
│    ... (66 real stock-market tables)                 │
└──────────────────────────────────────────────────────┘
```

**The one exception**: `datapai.usr_notification_prefs` is a **real local table on `stock_db`**, not a foreign-table alias. It holds per-user channel opt-ins (Telegram, email). Historical reasons.

---

## How to tell if a table is real or foreign

```sql
SELECT c.relname,
       c.relkind,
       CASE c.relkind
         WHEN 'r' THEN 'real table'
         WHEN 'f' THEN 'FOREIGN TABLE'
         WHEN 'v' THEN 'view'
         WHEN 'm' THEN 'materialized view'
         WHEN 'p' THEN 'partitioned table'
         ELSE c.relkind::text
       END AS kind
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'datapai'
  AND c.relname = 'your_table_name';
```

`relkind = 'f'` → foreign table, read the gotchas below before writing to it.
`relkind = 'r'` → real local table, normal SQL applies.

---

## Gotcha 1: INSERT bypasses remote-side DEFAULT clauses

### What happens

When you run this against a foreign table on `stock_db`:

```sql
INSERT INTO datapai.notification_log (user_id, channel, ticker, exchange, message_type, status)
VALUES ('9974f810-...', 'telegram', 'BHP.AX', 'ASX', 'signal_alert:BUY', 'sent');
```

You expect `id` (bigint sequence) and `sent_at` (TIMESTAMPTZ DEFAULT NOW()) to be set by the remote table's DEFAULT clauses. Instead you get:

```
ERROR: null value in column "id" of relation "notification_log" violates not-null constraint
CONTEXT: remote SQL command: INSERT INTO datapai.notification_log
         (id, user_id, channel, ticker, exchange, message_type, status, error_detail, sent_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
```

### Why

`postgres_fdw` expands your INSERT column list to **every column in the foreign-table definition** (all 9 columns of `notification_log`), passes NULL for the ones you didn't specify (`id`, `error_detail`, `sent_at`), and parameterizes everything as `$1..$N`. The remote side sees an explicit `NULL` in `id`, so the `DEFAULT nextval(...)` clause never fires, and the `NOT NULL` constraint rejects the row.

### Why `DEFAULT` keyword doesn't work either

You might think:

```sql
INSERT INTO datapai.notification_log
  (id, user_id, channel, ticker, exchange, message_type, status, error_detail, sent_at)
VALUES (DEFAULT, %s, %s, %s, %s, %s, %s, NULL, DEFAULT)
```

would forward the `DEFAULT` keyword to the remote. It doesn't. `postgres_fdw` parameterizes every value, so `DEFAULT` becomes `$1 = null` just like above.

### The fix — open a direct framework_db connection for writes

Connect to the REAL framework_db (`datapai_auth_db` on port 5433) and write there. The DEFAULT clauses fire normally on the real table.

```python
import psycopg2, os

def _get_framework_conn():
    """Lazy direct connection to framework_db (datapai_auth_db on port 5433).
    Reuses a single connection for the duration of the process."""
    global _framework_conn
    if _framework_conn is None or _framework_conn.closed:
        _framework_conn = psycopg2.connect(
            host=os.getenv("AUTH_DB_HOST", "localhost"),
            port=int(os.getenv("AUTH_DB_PORT", "5433")),
            dbname=os.getenv("AUTH_DB_NAME", "datapai_auth_db"),
            user=os.getenv("AUTH_DB_USER", "auth_service"),
            password=os.getenv("AUTH_DB_PASSWORD", ""),
        )
        _framework_conn.autocommit = True
    return _framework_conn


def log_notification(user_id, channel, ticker, exchange, message_type, status, error_detail=None):
    fw = _get_framework_conn()
    with fw.cursor() as cur:
        cur.execute(
            "INSERT INTO datapai.notification_log "
            "(user_id, channel, ticker, exchange, message_type, status, error_detail) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, channel, ticker, exchange, message_type, status, error_detail),
        )
```

**Rule**: reads are fine over the FDW (transparent, pushed-down). Writes should go directly to framework_db.

Live example: `scripts/send_alerts.py::_log_notification` and `_disable_invalid_push_token`.

### Why reads are fine

SELECT queries over the FDW are transparent — `postgres_fdw` sends the actual SELECT to the remote and returns the results. No default-value issue because SELECTs don't care about column DEFAULTs.

---

## Gotcha 2: Outer `objects(paging)` query in Twenty truncates nested `fields`

**Not strictly an FDW gotcha — this is a Twenty metadata API quirk — but it's in the same "read nesting traps" category and worth documenting alongside.**

### What happens

```graphql
query {
  objects(paging: { first: 200 }) {
    edges {
      node {
        fields(paging: { first: 200 }) {
          edges { node { name type options } }
        }
      }
    }
  }
}
```

You'd expect this to return all ~22 fields per object. Instead you get ~6 fields per object, in no particular order. The inner `fields(paging)` hint is ignored when nested inside the outer `objects(paging)`.

### The fix — query per-object

```graphql
query Fields($objectId: UUID!) {
  object(id: $objectId) {
    fields(paging: { first: 200 }) {
      edges { node { name type options defaultValue } }
    }
  }
}
```

Two calls needed (first to list objects + get their ids, then per-object field query), but you get ALL fields reliably.

Live example: `scripts/stock_crm_client_sync.py::load_twenty_enums`.

---

## Gotcha 3: ALTER TABLE on a foreign table only changes LOCAL metadata

### What happens

You want to add a column to `datapai.users`. You SSH into the EC2 box, connect to the stock DB, and run:

```sql
ALTER TABLE datapai.users ADD COLUMN signup_source TEXT;
```

It returns `ALTER TABLE` success. But then:

```sql
SELECT signup_source FROM datapai.users LIMIT 1;
-- ERROR: column "signup_source" does not exist
-- CONTEXT: remote SQL command: SELECT signup_source FROM datapai.users LIMIT 1
```

### Why

`ALTER TABLE` on a foreign table in `postgres_fdw` only updates the LOCAL foreign-table definition — i.e. what `stock_db` thinks the remote looks like. It does NOT propagate to the remote. The next SELECT tries to push `signup_source` to the remote, which doesn't have that column, and errors out.

### The fix — always apply schema migrations on framework_db first

```sql
-- Step 1: apply the real migration on framework_db
-- (connect to datapai_framework_db via docker exec)
ALTER TABLE datapai.users ADD COLUMN signup_source TEXT NOT NULL DEFAULT 'unknown';

-- Step 2: refresh the FDW foreign-table alias on stock_db to include the new column
ALTER FOREIGN TABLE datapai.users ADD COLUMN signup_source TEXT;
```

**Rule**: schema migrations ALWAYS go to `framework_db` first, then mirror to the FDW alias on `stock_db`. NEVER run `ALTER TABLE` (without FOREIGN) on the stock-db side expecting it to propagate — it does NOT.

### Adding a whole new foreign table

If you created a new real table on framework_db (e.g. `datapai.user_devices`), add a matching foreign-table alias on stock_db:

```sql
CREATE FOREIGN TABLE IF NOT EXISTS datapai.user_devices (
    id              UUID,
    user_id         TEXT,
    platform        TEXT,
    expo_push_token TEXT,
    device_name     TEXT,
    device_model    TEXT,
    os_version      TEXT,
    app_version     TEXT,
    last_seen_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ,
    disabled_at     TIMESTAMPTZ
)
SERVER framework_db
OPTIONS (schema_name 'datapai', table_name 'user_devices');
```

**Note** that the column types on the foreign table don't need `DEFAULT` clauses (those live on the remote). The `NOT NULL` constraints also don't need to be on the foreign side — the remote enforces them.

---

## Gotcha 4: Schema-level `GRANT USAGE` must come before table-level grants

Not strictly an FDW issue, but it bit us during Phase 1.10 setup and is worth capturing.

### What happens

You grant table-level permissions to a role:

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON datapai.users TO auth_service;
```

Then auth-be tries to INSERT and fails:

```
ERROR: permission denied for schema datapai
```

### Why

Postgres requires two levels of permission to write to a table in a non-owned schema:
1. `USAGE` on the schema itself — to even "enter" it
2. `SELECT/INSERT/UPDATE/DELETE` on the tables — for the actual operation

Without `USAGE`, the table grants are dead letters. And the error mentions the SCHEMA, not the table, which is confusing.

### The fix — full incantation

```sql
GRANT USAGE ON SCHEMA datapai TO auth_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA datapai TO auth_service;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA datapai TO auth_service;
ALTER DEFAULT PRIVILEGES IN SCHEMA datapai
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO auth_service;
```

The `ALTER DEFAULT PRIVILEGES` line is critical: it ensures any FUTURE tables created in the schema automatically get the grants. Without it, every new table needs a manual `GRANT` and someone will forget.

---

## Quick reference: when to use which connection

| Operation | Connection |
|---|---|
| **Read from any user-facing table** (`users`, `watchlist`, `notification_log`, etc.) | `stock_db` (port 5434) — transparent via FDW, use for joins with real stock tables like `stock_synthesis` |
| **Write to a user-facing table** (INSERT/UPDATE/DELETE) | `framework_db` (port 5433) — direct, avoids the DEFAULT-value gotcha |
| **Read/write stock-market tables** (prices, ohlcv, screener_metrics) | `stock_db` — these are real local tables |
| **Read/write `usr_notification_prefs`** | `stock_db` — exception, real local table |
| **Schema migration** | `framework_db` FIRST, then mirror to FDW alias on `stock_db` |
| **Twenty custom metadata queries** | Twenty `/metadata` GraphQL endpoint, NEVER postgres directly |

---

## Why this architecture exists

Historical: `framework_db` was introduced as a shared SSO/identity layer across multiple verticals (stock, trade, homepage, etc.). Rather than forcing each vertical app to learn about framework_db's connection details, the foreign-table aliases let each vertical's local DB "see" the identity tables as if they were local. Reads are cheap (FDW pushdown is good), and writes were expected to be rare (identity changes happen at register time, not in sync scripts).

The write-path gotchas were discovered in 2026-04-11 during Phase 4A when we started writing `notification_log` rows from the alert pipeline. The original `send_alerts.py` had been in production but had never actually hit the INSERT path because no user had a linked channel until Phase 4A.

---

## Related

- `docs/phase-journals/2026-04-11-phase-1.10-to-4b.md` — the session where these gotchas were discovered and fixed
- `docs/operator-runbook.md` — business-config changes (uses direct framework_db writes via SQL, which sidestep these gotchas entirely)
- `scripts/send_alerts.py::_get_framework_conn` — reference implementation of the direct-write pattern
- `scripts/stock_crm_client_sync.py::load_twenty_enums` — reference implementation of the per-object query pattern (Gotcha 2)
