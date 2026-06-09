# 2026-06-09 — Debate-Failed Fallback Fix + Today-Only Performance Filter

> **TL;DR.** Gemini AI Studio prepayment credits depleted ~Jun 4. Every API
> call returned `429 RESOURCE_EXHAUSTED`. AG2 swallowed empty responses → the
> `_run_debate` fallback fired silently → the M1 momentum gate promoted broken
> `HOLD 0.30 LOW` rows to `BUY 0.55 MEDIUM`. **115 fake BUY/HOLD calls landed
> in `stock_synthesis` Jun 4-8** with placeholder thesis text
> *"Insufficient signal clarity for a directional call."* — none of which
> reflected any actual AI debate.
>
> This journal documents the fix: the fallback now emits `WATCH` (not `HOLD`),
> the M1 gate is blocked on failed debates, and 115 historical rows were
> retroactively relabeled. Also: `/performance` got "Today only" filter +
> date-DESC sort so the user can spot future regressions at a glance.

---

## Symptom

User noticed BUY signals on FLNC + TEAM for Jun 4, 5, 8 whose thesis was
*"Insufficient signal clarity for a directional call."* and key_risk was
*"Conflicting signals with no clear resolution"* — clearly contradictory
to the BUY direction.

```
ticker | direction | conf | conviction | thesis
-------+-----------+------+------------+------------------------------------------------
FLNC   | BUY       | 0.55 | MEDIUM     | Insufficient signal clarity for a directional call.
TEAM   | BUY       | 0.55 | MEDIUM     | Insufficient signal clarity for a directional call.
... (115 such rows across 42 US tickers × 3 days)
```

## Root-cause investigation

Read `task_id=synth_TEAM/attempt=1.log` for the
`scheduled__2026-06-05T22:00:00+00:00` Airflow run. Every LLM call returned:

```
GeminiHTTPModelClient.chat() failed: 429 Client Error: Too Many Requests
"Your prepayment credits are depleted. Please go to AI Studio
 at https://ai.studio/projects to manage your project and billing."
```

AG2's GroupChat termination logic doesn't distinguish "5 rounds completed
successfully" from "5 rounds all returned empty due to API error" — both
hit `TERMINATING RUN: Maximum rounds (5) reached`. The PM never produced
parseable JSON → `recommendation` was `None` → the else-branch fallback at
`synthesis_pipeline.py:452` fired:

```python
else:
    # Default to HOLD if debate produced no result
    direction = SignalDirection.HOLD
    confidence = 0.3
    conviction = "LOW"
    thesis = "Insufficient signal clarity for a directional call."
    ...
```

Then the **M1 momentum-exception gate** (added 2026-05-29, task #48) at
`synthesis_pipeline.py:538` saw `HOLD + confidence < 0.5 + signals not
aligned + recent_return_7d > 5% + TA bullish` → promoted to **BUY 0.55
MEDIUM**. M1 had no awareness that the HOLD was a fallback, not a real
debate result.

### Why none of our safeguards caught it

| Layer | What it should have done | Why it didn't |
|---|---|---|
| Health monitor (task #36-37) | Daily check for fallback-signature rows | `synthesis_health_runs.status` column missing — schema mismatch silently errored |
| Smoke test (task #39) | Run AAPL synthesis daily + assert non-fallback | DAG didn't include this step pre-deploy |
| Logger.error on fallback (task #38) | Promote INFO → ERROR with exception repr | Was logging the LLM 429 at INFO inside `GeminiHTTPModelClient` — never bubbled up to ERROR at the synthesis layer |
| M1 protection | Avoid promoting low-quality HOLDs | M1 didn't check whether the HOLD came from a real debate |

The health-monitor schema mismatch is the most galling — we built the
exact tool to catch this regression and it failed to run.

## Fixes applied

### 1. `agents/stock_synthesis/synthesis_pipeline.py` — fallback now emits WATCH

**Diff:**

```diff
     else:
-        # Default to HOLD if debate produced no result
-        direction = SignalDirection.HOLD
+        # Debate produced no result (LLM 429 / parse error / total failure).
+        # Emit WATCH (not HOLD) — "we don't have conviction yet" is the
+        # truthful state, and WATCH won't be promoted by the M1 momentum gate.
+        logger.error("[%s/%s] DEBATE FAILED — emitting WATCH (was: silent HOLD fallback)", ticker, exchange)
+        direction = SignalDirection.WATCH
         confidence = 0.3
         conviction = "LOW"
-        thesis = "Insufficient signal clarity for a directional call."
+        thesis = "AI debate unavailable — no recommendation can be made."
         what_bulls_say = ""
         what_bears_say = ""
-        key_risk = "Conflicting signals with no clear resolution"
+        key_risk = "Engine fallback fired; treat as deferred until next refresh."
+        gate_decisions["debate_failed"] = {"fired": True, "reason": "LLM returned no parseable recommendation"}
```

### 2. M1 momentum gate — must not fire on failed debates

```diff
-if direction == SignalDirection.HOLD and confidence < 0.50 and not signals_aligned:
+if direction == SignalDirection.HOLD and confidence < 0.50 and not signals_aligned and not gate_decisions.get("debate_failed", {}).get("fired"):
```

Since the new fallback emits `WATCH` (not `HOLD`), this check is doubly
defensive — but the `debate_failed` short-circuit makes the intent
explicit and survives any future re-tuning of the fallback direction.

### 3. Database — retroactive relabel of 115 broken-fallback rows

```sql
WITH targets AS (
  SELECT ticker, exchange, computed_at
  FROM datapai.stock_synthesis
  WHERE thesis = 'Insufficient signal clarity for a directional call.'
    AND computed_at >= '2026-06-04'
)
UPDATE datapai.stock_synthesis ss
SET direction = 'WATCH',
    confidence = 0.30,
    conviction = 'LOW',
    thesis = 'AI debate unavailable — no recommendation can be made (Gemini API credits depleted Jun 4-8).',
    key_risk = 'Engine fallback fired; treat as deferred until next refresh.',
    gate_decisions = COALESCE(ss.gate_decisions, '{}'::jsonb)
        || jsonb_build_object('debate_failed',
             jsonb_build_object('fired', true,
                                'reason', 'Gemini 429 — credits depleted',
                                'retroactive_relabel', true)),
    relabeled_at = NOW(),
    relabeled_from_dir = ss.direction
FROM targets t
WHERE ss.ticker = t.ticker
  AND ss.exchange = t.exchange
  AND ss.computed_at = t.computed_at;
-- UPDATE 115
```

### 4. `app/performance/page.tsx` (FE) — "Today only" filter + date-DESC sort

Two enhancements to make future regressions visible at a glance:

- **"Today only" toggle button** alongside the existing "All Directions"
  dropdown. Click toggles green/white. Filters synth rows to current local
  date only (compares `r.computed_at` → `toLocaleDateString()` against
  `new Date().toLocaleDateString()`).
- **Rows sorted by `computed_at` DESC** — newest debates always at top so
  the latest run is immediately visible regardless of which filter is
  active.

## Verification

- ✅ Gemini API ping returns 200 after user topped up billing
- ✅ Manual run `bash scripts/run_stock_synthesis.sh --exchange US --tickers TEAM`
  completed in 165s and produced **real** debate output:
  ```
  TEAM | WATCH | 0.40 | LOW |
  "Despite bullish technicals and analyst optimism, the persistent
   negative ROE and low quality score…"
  ```
- ✅ Jun 5 + Jun 8 historical rows now show the correct "AI debate
  unavailable" thesis with `relabeled_from_dir` populated
- ✅ Manually-triggered `stock_synthesis_us` DAG run is `running` — full
  universe refresh in progress, ~30 min ETA

## Still outstanding

| # | Item | Owner |
|---|---|---|
| 1 | Health monitor schema mismatch (`synthesis_health_runs.status` column missing) | Engineering — next session |
| 2 | Failover LLM provider (DeepSeek/OpenAI) so a single-vendor billing lapse can't take engine offline again | Design — pending decision |
| 3 | `datapai.sys_agent_results` table missing — non-fatal warning during synthesis (lesson lookup gracefully degrades to empty) | Low priority |
| 4 | Smoke test should be wired into the daily DAG as a pre-flight assertion (don't proceed if 1 sample fails) | Engineering |
| 5 | Re-evaluate M1 momentum exception — it added complexity that compounded this bug. M2 (AVOID demotion) was the only one validated this session. | Design |

## Files touched

- `agents/stock_synthesis/synthesis_pipeline.py` — fallback emits WATCH; M1 short-circuits on failed debates
- `datapai-stock-fe/app/performance/page.tsx` — Today filter + date-DESC sort
- DB: `datapai.stock_synthesis` — 115 rows retroactively relabeled

## Backups created (on EC2)

- `agents/stock_synthesis/synthesis_pipeline.py.bak-20260609-074003`
- `docker-compose.yml.bak-*` (earlier today, from cost-reduction session)

## Pointers

- Phase journal style: matches the 2026-04-11 reference quality bar per
  `~/.claude/CLAUDE.md` standing requirement
- Related history: 2026-04-11 phase-1.10-to-4b.md (original AG2 revival),
  2026-05-28 WATCH/AVOID expansion, 2026-05-29 M1/M2/M3 momentum patches
