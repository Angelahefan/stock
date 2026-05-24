# 2026-05-24 — AG2 Multi-Agent Debate revived on Gemini (Option A)

## TL;DR

For ~2 months the stock-synthesis pipeline silently logged
`AG2/autogen not installed — falling back to single-LLM synthesis` on every
call, and the fallback was itself broken (always returned HOLD / 0.3 / LOW).
Real cause: AG2 0.5.3's `api_type: "google"` requires
`google-generativeai >= 0.3` (needs `google.ai.generativelanguage.Content`),
but EC2 is pinned to Python 3.8.20, which caps that SDK at `0.1.0rc1` —
missing the `Content` symbol. AG2 fell through to the OpenAI default client,
which then threw too.

Fixed by writing a **custom AG2 `ModelClient`** that wraps the already-proven
`GoogleChatClient` (pure-HTTP, no SDK — the same path our chat bot uses
daily) and registering it on every `ConversableAgent`. No Python upgrade,
no AG2 swap, no dropping of multi-agent debate.

Also fixed two related bugs uncovered along the way:
1. `PORTFOLIO_MANAGER_PROMPT` contained literal `{ }` JSON braces that
   crashed `prompt.format(past_lessons=…)` with `KeyError('\n    "direction"')`.
2. `event_classifier.py` imported `GeminiChatClient` — that class was renamed
   to `GoogleChatClient` months ago, so every news classification ImportError'd
   and news input vanished from synthesis.

Live evidence (post-deploy, BHP/ASX):
- `Detected custom model client in config: GeminiHTTPModelClient` × 3 → AG2
  registered the wrapper on all 4 agents.
- Portfolio Manager produced clean JSON citing real data (BoA downgrade, China
  credit impulse, ROE 24.7%, PE 17.66) — first real AG2 GroupChat output
  since the bug was introduced.
- Bull Analyst then closed with consensus acknowledgement.
- Final recommendation: **HOLD · 65% · MEDIUM** (vs. the 2-month hardcoded
  "HOLD / 0.3 / LOW" default).

## Why this matters

- 2-month "win-rate 25.6%" on `/performance` was measuring a broken engine,
  not a bad model. Real signals now accumulate.
- Quality + Regime gates (added in the same change) only fire on `BUY`/
  `STRONG_BUY`; previously they never had anything to demote because the
  fallback always emitted `HOLD`.
- Unblocks Reflector loop work (next phase) — the multi-agent debate logs
  are the input to the Reflector that learns from win/loss outcomes.

## Files changed

| File | Change |
|---|---|
| `agents/stock_synthesis/gemini_ag2_client.py` | **NEW** — `GeminiHTTPModelClient` implementing AG2's `ModelClient` protocol + `build_llm_config()` helper. Wraps `GoogleChatClient`. |
| `agents/stock_synthesis/synthesis_pipeline.py` | Switched Google branch of `llm_config` to use `model_client_cls: GeminiHTTPModelClient`; call `agent.register_model_client(...)` on each of bull/bear/risk_mgr/portfolio_mgr/manager. Added post-debate **Quality + Regime gates** and `_get_quality_for_gate()` helper. |
| `agents/stock_synthesis/agent_prompts.py` | Escaped `{` `}` → `{{` `}}` in `PORTFOLIO_MANAGER_PROMPT`'s JSON example so `str.format()` doesn't KeyError. |
| `agents/news_agent/event_classifier.py` | Renamed `GeminiChatClient` → `GoogleChatClient` (the import was the only place in the codebase still using the old name). |

## Design decisions + alternatives considered

User explicitly demanded we **keep AG2** and **keep Gemini as default**. The
real candidates were:

| Option | Effort | Risk | Choice |
|---|---|---|---|
| **A. Custom AG2 client wrapping existing `GoogleChatClient` (HTTP)** | ~1h | Low — purely additive | ✅ **Picked** |
| B. Migrate stock-be to Python 3.12 (already installed at `/usr/local/bin/python3.12`) so AG2's native `api_type: google` works | ~1 day | Medium — touches every dep | Deferred |
| C. Swap AG2 for LangGraph | ~3-5 days | High | Rejected — rewrites memory + reflector |
| D. Swap AG2 for Microsoft AutoGen 0.4 | ~3-5 days | High | Rejected — same as C |
| E. Swap AG2 for CrewAI | ~2-3 days | Medium | Rejected — weaker memory primitives |
| F. Drop multi-agent entirely, do manual 4-persona via RouterChatClient | ~30min | Low | **Explicitly vetoed by user** ("can't drop ag2") |

A wins because:
1. Reuses the Gemini HTTP path that's been working in chat / screenshot /
   fundamental / SEC filing / ASX trading signal agents every day.
2. AG2's `register_model_client` is the documented hook for exactly this case.
3. Zero blast radius on the 9 other systemd services on EC2.
4. Fully reversible — drop the wrapper later when we move to Python 3.12.

## Gotchas discovered

### G1. AG2's "AG2/autogen not installed" log message is a lie
The exception was actually `ImportError: cannot import name 'Content' from 'google.ai.generativelanguage'`, raised inside AG2's `_register_default_client` for the Google API path. The `ImportError` we were catching was about Gemini SDK shape, not AG2 itself. Misleading log = 2 months of "we thought AG2 wasn't installed."

### G2. EC2 has Python 3.12 but no python3.9/3.10/3.11
- `/usr/bin/python3.8` (current default for all services)
- `/usr/local/bin/python3.12` (available, unused by stock-be)
- No 3.9/3.10/3.11 at all. Future migration jumps straight from 3.8 → 3.12.

### G3. `agents/llm_client.py` doesn't exist in stock-be
Stock-be imports `from agents.llm_client import …` but the file lives in
`platform-be`. The `datapai-agent.service` unit sets
`Environment="DATAPAI_PLATFORM_DIR=/home/ec2-user/git/datapai-platform-be"`
and `app.py` adds it to `sys.path` at startup. **This is why running
anything locally on the Mac without that env var resolves to "no such
module."** Documented in
`~/.claude/projects/-Users-linlin-git-datapai-stock-be/memory/reference_no_local_dev_env.md`.

### G4. `PORTFOLIO_MANAGER_PROMPT` literal JSON braces
The prompt was authored as if it were a Python f-string showing the LLM what
to emit. But `agent_prompts.py` passes it through `str.format(past_lessons=…)`,
so Python treats `{ "direction": "BUY", … }` as a placeholder and raises
`KeyError('\n    "direction": "BUY",\n    "confidence": 0.65,\n    "conviction": "MEDIUM",\n    "thesis": "...",\n    "what_bulls_say": "...",\n    "what_bears_say": "...",\n    "key_risk": "..."')`. The truncated form `'\n    "direction"'` was what we saw in the log. Fix: double the braces.

### G5. `sys_agent_debate_log` FDW NOT-NULL on `id` (pre-existing, NOT fixed here)
Reflector loop still can't log debates. postgres_fdw passes NULL for `id`
even when Python omits the column. Needs dblink bypass, or DROP the foreign
table and ALTER its base table to use a DEFAULT. Tracked separately.

## Verification evidence

```text
[autogen.oai.client] INFO - Detected custom model client in config: GeminiHTTPModelClient, model client can not be used until register_model_client is called.
[autogen.oai.client] INFO - Detected custom model client in config: GeminiHTTPModelClient, model client can not be used until register_model_client is called.
[autogen.oai.client] INFO - Detected custom model client in config: GeminiHTTPModelClient, model client can not be used until register_model_client is called.

Portfolio_Manager (to chat_manager):
```json
{
    "direction": "HOLD",
    "confidence": 0.65,
    "conviction": "MEDIUM",
    "thesis": "While BHP exhibits strong historical fundamentals and profitability, the recent Bank of America downgrade, citing valuation concerns and a negative China credit impulse, introduces significant forward-looking macroeconomic headwinds. These risks, coupled with a cautious broader analyst consensus, suggest limited near-term upside and warrant a neutral stance despite the company's underlying quality.",
    "what_bulls_say": "BHP boasts exceptional profitability (ROE 24.7%, 19.0% net margin)…",
    "what_bears_say": "Bank of America downgraded BHP to Neutral due to valuation concerns (PE 17.66) and a critical 'negative China credit impulse'…",
    "key_risk": "The primary risk is the 'negative China credit impulse.'…"
}
```

Service restart clean:
```
● datapai-agent.service - DataPAI Agent API (FastAPI) — stock backend
   Active: active (running) since Sun 2026-05-24 05:37:12 UTC
   Memory: 407.1M
   ├─31978 /usr/bin/python3 -m uvicorn app:app --host 0.0.0.0 --port 8005 --workers 2
```

## What's still pending

1. **`sys_agent_debate_log` FDW NOT-NULL fix** — needed for Reflector loop.
   Approach: drop the foreign table, ALTER local table to DEFAULT `gen_random_uuid()`
   for `id`, re-import foreign table. ~30 min on EC2.
2. **Quality + Regime gate verification** — gates only fire on BUY/STRONG_BUY;
   need a BUY signal to confirm the demotion path. Will manifest in the next
   batch run via `scripts/run_stock_synthesis.py --exchange ALL`.
3. **Python 3.12 migration (Option B)** — separate maintenance window, would
   let us drop `gemini_ag2_client.py` and use AG2's native `api_type: google`.
4. **News classifier verification** — `event_classifier.py` rename means news
   should now classify into MaterialEvent rows. Confirm next run produces
   non-empty NEWS signals in `sys_agent_debate_log`.

## Related pointers

- Memory: `~/.claude/projects/-Users-linlin-git-datapai-stock-be/memory/reference_no_local_dev_env.md` (added today — EC2 is the only runtime, SSH first for any "does this run" question)
- Memory: `~/.claude/projects/-Users-linlin-git-datapai-stock-be/memory/feedback_no_gemini_lite_fn_calls.md` (never use gemini-2.5-flash-lite for multi-turn)
- Previous synthesis bug fix: commit `f987930` (made `_extract_json` robust)
