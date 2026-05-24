# 2026-05-24 — Debate-log FDW NOT-NULL bypass (split read/write foreign tables)

## TL;DR

`datapai.sys_agent_debate_log` is a postgres_fdw foreign table on consumer
DBs (stock 5434, health 5435, trade 5436) pointing at the base table on
`datapai_auth_db`/`datapai_framework_db`. Even though Python omitted `id`
from INSERT column lists, postgres_fdw rewrote the remote SQL to include
EVERY foreign-table column and passed `NULL` for `id` — tripping the base
table's `NOT NULL`. Result: **every multi-agent debate run silently dropped
its log row for ~7 weeks**, starving the Reflector loop of training data
and preventing compound learning toward the 70% win-rate target.

Fix: split into two foreign tables backed by the same remote relation:

| Foreign table | Cols | Use |
|---|---|---|
| `datapai.sys_agent_debate_log` | 22 (no id, no created_at) | INSERT — postgres_fdw stops sending NULL for the auto cols, remote defaults `nextval(...)` and `now()` fire |
| `datapai.sys_agent_debate_log_full` | 24 (incl. id + created_at) | SELECT id-back / Reflector UPDATE WHERE id=… |

Applied DDL on all 3 consumer DBs. Base table + 256 existing rows untouched.

## Verified live

```
=== row count before ===
256
=== synthesis with 540s timeout ===
exit code: 0
... 2026-05-24 06:13:32 [INFO] stock_synthesis — [1/1] BHP  HOLD  conf=60%  conviction=MEDIUM ...
... 2026-05-24 06:13:32 [INFO] stock_synthesis — === Stock Synthesis DONE | ASX | processed=1 errors=0 | 434s ===
=== row count after ===
257
=== newest debate row ===
 id  | ticker | direction | confidence |          created_at
-----+--------+-----------+------------+-------------------------------
 260 | BHP    | HOLD      |        0.6 | 2026-05-24 06:13:31.994642+00
```

(The previous "real" row was 256 / WDS / 2026-04-03 — confirming 51 days of zero debate logging.)

## Files changed

| File | Change |
|---|---|
| `migrations/044_fdw_drop_id_from_debate_log.sql` | **NEW** — DROP+CREATE both foreign tables on stock/health/trade DBs. Verification + rollback included. |
| `agents/stock_synthesis/memory.py` | `log_debate` — drop `RETURNING id`, do follow-up `SELECT id FROM …_full WHERE ticker=… ORDER BY id DESC LIMIT 1`. `update_debate_actuals` — point UPDATE at `…_full`. |
| `agents/stock_synthesis/reflector.py` | Two SELECT statements point at `…_full` (both need id column). |

## Design alternatives considered

1. **Custom column option to skip on INSERT** — postgres_fdw doesn't support this. Rejected.
2. **dblink-wrapped INSERT** — works but needs extension on consumer DBs + DSN duplication. Heavier. Rejected.
3. **`SECURITY DEFINER` function on remote** — needs DDL on `datapai_auth_db` + per-vertical perms. Rejected.
4. **Move base table local to stock_db** — loses cross-vertical visibility (health/trade also log debates here). Rejected.
5. **Split into two foreign tables (chosen)** — both wrap the same base; write side hides auto columns, read side exposes them. No extensions, no DSN duplication, no remote DDL.

## Gotchas

### G1. postgres_fdw column behaviour
> If you specify a column in a foreign table's definition, postgres_fdw will include it in the remote INSERT statement (with NULL if Python omits it from the local INSERT column list).

There is no per-column "skip on insert" option. The *only* way to make postgres_fdw stop sending a column is to drop it from the foreign-table definition.

### G2. RETURNING does work via FDW — but only for exposed columns
Initial attempt: keep `RETURNING id`. Failed because the write-side table no longer has `id`. Solution: do the readback against the `_full` foreign table.

### G3. Composite-match id readback has a race window
The fallback `SELECT id FROM …_full WHERE (ticker, exchange, debate_date, debate_type) = … ORDER BY id DESC LIMIT 1` is reliable in practice because:
- `debate_date` is date-grained (1/day)
- `debate_type` is constant ('synthesis')
- Two `(ticker, exchange)` synthesis runs would have to land in the same DB transaction microsecond to race

Acceptable risk. If a true race ever surfaces, add a `client_uuid` column.

## What still doesn't work yet (observed during verification)

1. **AG2 takes ~7 min per ticker** (434s for BHP). A 50-ticker nightly batch ≈ 6 hours. Tight. Consider trimming `MAX_DEBATE_ROUNDS` from 2 to 1.
2. **`bull_arguments` / `bear_arguments` arrays empty in the inserted row** — the loop
   ```python
   for msg in groupchat.messages:
       if msg.get("role") == "assistant" and msg.get("name"): …
   ```
   in `synthesis_pipeline.py` doesn't capture Gemini-shaped messages (likely no `role: assistant` field). Without these arrays, Reflector can't learn from agent positions. Separate fix needed before Reflector loop is useful.
3. **Service startup warnings** (non-fatal): `DependencyConflict: langchain 0.1.5 < 0.1.20`, `Failed to instrument autogen: ConversableAgent has no attribute 'run'`. App starts fine.

## Related pointers

- Predecessor: `docs/phase-journals/2026-05-24-ag2-gemini-revival.md` (Gemini wired into AG2 — unblocked the debate; this journal unblocks the *logging* of those debates).
- Memory: `~/.claude/projects/-Users-linlin-git-datapai-stock-be/memory/reference_no_local_dev_env.md` (EC2-only DBs).
