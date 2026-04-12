# AI Audit Trail — Architecture Pattern

**Status:** Live (Phase 1.13, 2026-04-12)
**Applies to:** Every AI surface at DATAP.AI across every vertical (stock, health, trade, future verticals)
**Standing rule:** AI Governance — No Black Box. Every AI conversation must be persisted, searchable, and auditable **forever**.

---

## The rule in one sentence

> Every user message to and every response from every AI surface at DATAP.AI lands in two places: a hot tier in Postgres for active UI and LLM context recall, and a cold tier on S3 as Parquet for audit, back-tracking, and compliance.

Failing to persist an AI conversation is a **governance violation**, not a recoverable error.

---

## Two-tier architecture

```
  User / Client
       │
       │ POST /agent/<vertical>-chat
       ▼
  ┌─────────────────────────────────────┐
  │  Backend FastAPI endpoint            │
  │  (datapai-stock-be, healthcare-be)   │
  └──────────┬───────────────────────────┘
             │
             │  direct psycopg2 connection      ┌──── HOT TIER ─────────────────┐
             ├──────────────────────────────────▶  framework_db (port 5433)    │
             │  (NOT the stock_db FDW alias)     │  datapai.chat_sessions       │
             │                                    │  datapai.chat_messages       │
             │                                    │  datapai.sys_user_context    │
             │                                    │  datapai.user_preferences    │
             │                                    │  Retention: 90 days          │
             │                                    └──────────────────────────────┘
             │                                                   │
             │                                                   │  Weekly DAG
             │                                                   │  (Sunday 02:00 UTC)
             │                                                   ▼
             │                                    ┌──── COLD TIER ────────────────┐
             │                                    │  S3: codepais3 bucket          │
             │                                    │  datapai-archive/<vertical>/   │
             │                                    │    chat_history/year=YYYY/     │
             │                                    │      month=MM/day=DD/          │
             │                                    │        part-*.parquet          │
             │                                    │  Retention: forever            │
             │                                    └────────────────────────────────┘
             │
             │  secondary audit (fire-and-forget, non-fatal)
             └──────────────────────────────────▶  Twenty CRM (stockClient note)
```

---

## Rules for anyone building a new AI surface

### 1. Use a direct framework_db connection for writes

postgres_fdw silently bypasses remote-side `DEFAULT` clauses when you INSERT through a foreign-table alias. Writes to `chat_sessions`, `chat_messages`, `sys_user_context`, `user_preferences`, `user_devices`, `notification_log`, and any other user-facing table on framework_db MUST route through a direct psycopg2 connection.

**Pattern:** see `agents/stock_chat/fw_db.py` — a module with a lazy `_get_fw_conn()`, an auto-reconnecting `_fw_cursor()` context manager, and `fw_execute` / `fw_execute_returning` / `fw_query` helpers. The healthcare vertical should own a parallel `healthcare-be/agents/health_chat/fw_db.py` using the same pattern.

**Anti-pattern:** importing `execute` from a stock_db FDW pool and using it to write to a foreign-table alias. This WILL silently lose data once the schema gains any `DEFAULT` clause.

### 2. Loud ERROR on persist failure — never "non-fatal warning"

Old pattern (banned):
```python
try:
    save_message(session_id, "user", req.message)
except Exception as e:
    logger.warning("persist failed (non-fatal): %s", e)
```

New pattern (required):
```python
try:
    save_message(session_id, "user", req.message)
except Exception as e:
    logger.error(
        "GOVERNANCE: chat persist FAILED for session=%s user_id=%s ticker=%s: %s",
        session_id, user_id_str, ticker, e,
    )
```

The user still gets their AI response (graceful degradation), but the failure is loud in monitoring / journalctl. The `GOVERNANCE:` prefix is searchable.

### 3. DB-driven config, not hardcoded

Retention windows, bucket names, prefixes, and kill switches live in `datapai.sys_common_config` under `config_type='<vertical>_chat_archive'`. Changing any value is a SQL update — zero code.

See `framework_db/migrations/043_phase_1_13_chat_archive_config.sql` for the row structure and `operator-runbook.md` for the change procedure.

### 4. Hot tier is ephemeral cache; cold tier is canonical

Treat Postgres as a 90-day rolling cache. The canonical record lives on S3 forever. That means:
- **Don't** feel bad about DELETEing old rows from Postgres — the Parquet files are authoritative.
- **Do** make sure the archival script verifies every Parquet file is readable + row-count-matches BEFORE it deletes from Postgres. Current `archive_chat_history_to_s3.py` does this via `_verify_parquet()`.
- **Do** log every archival run to `datapai.sys_archive_log` with `status`, `rows_archived`, `s3_objects_written`, `started_at`, `ended_at`, so operators can audit the audit trail.

### 5. Partition by day, not by session

S3 paths use Hive-style `year=YYYY/month=MM/day=DD/` partitioning keyed off `chat_messages.created_at AT TIME ZONE 'UTC'`. Athena / DuckDB / Trino can all prune on these partitions natively. One Parquet file per day per run — small random UUID run_id in the filename prevents collisions across runs.

### 6. Context sources column is a promise to future us

`chat_messages.context_sources` is a JSONB column currently written as `[]`. Future work: populate it with the names of each system-prompt block that was injected (`user_profile`, `twenty_crm`, `rag_tinyfish`, etc.) so audit reviewers can reproduce what the LLM actually saw when it generated a response. This is the difference between "we stored the conversation" and "we can explain the conversation" — the second one is what governance actually asks for.

---

## Tables touched by the audit trail (framework_db.datapai schema)

| Table | Purpose | Foreign-table alias on stock_db? |
|---|---|---|
| `chat_sessions` | One row per (user, ticker) chat thread | Yes — `datapai_stock_db.datapai.chat_sessions` |
| `chat_messages` | Every user message + AI response | Yes |
| `sys_user_context` | Extracted facts about the user (holdings, goals) | Yes |
| `user_preferences` | Risk tolerance, investment horizon, etc. | Yes |
| `sys_archive_log` | Run-audit for the weekly archival DAG | No — server-side only |
| `sys_common_config` | Config source of truth for archive tunables | Yes (read-only through FDW) |

Any future table added for AI audit purposes — a `chat_context_sources` detail table, a `llm_tool_calls` log, etc. — MUST follow the same rules.

---

## Reference files

### Stock vertical (live)
- **Write path module**: `agents/stock_chat/fw_db.py`
- **Chat persistence**: `agents/stock_chat/history.py` (save_message, get_or_create_session, save_user_preference)
- **User context**: `agents/stock_chat/user_context.py` (upsert_user_context)
- **Endpoint**: `agents/stock_chat/endpoint.py` (non-streaming `/agent/stock-chat`, streaming `/agent/stock-chat/stream`)
- **Archival script**: `scripts/archive_chat_history_to_s3.py`
- **Shell wrapper**: `scripts/run_archive_chat_history_to_s3.sh`
- **Airflow DAG**: `scripts/dags/chat_history_archival.py`
- **Migration**: `migrations/043_phase_1_13_chat_archive_config.sql`

### Health vertical (future, Phase 2+)
- **Write path module**: `healthcare-be/agents/health_chat/fw_db.py` (to be created — mirror the stock pattern)
- **Archival**: `datapai-healthcare-be/scripts/archive_health_chat_history_to_s3.py` (to be created)
- **Airflow DAG**: `datapai-airflow/dags/health_chat_history_archival.py` (to be created — reads `archive_prefix_health` config)

### Operator reference
- **Runbook**: `docs/operator-runbook.md` — "how to change retention", "how to disable archival", "how to query sys_archive_log"
- **FDW gotchas**: `docs/architecture/fdw-gotchas.md` — the pattern this phase fixes

---

## Why this matters — the one-paragraph rationale

DATAP.AI targets regulated verticals (healthcare, equities, pharma). Every prospective customer in those verticals asks some version of "what did your AI tell my users, and can I prove it?" The Four Intelligences positioning — specifically **CI (Customer Intelligence)** and **DI (Data Intelligence)** — is only defensible if the answer is "every conversation is on S3, partitioned by day, queryable via Athena, and the archival is a GitHub-auditable Airflow DAG." This architecture pattern is what makes that answer true. No black boxes.
