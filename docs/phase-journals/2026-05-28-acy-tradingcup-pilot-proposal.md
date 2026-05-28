# ACY × DATAP.AI — TradingCup AI Trade Council Pilot

**Date:** 2026-05-28
**Status:** Proposal — awaiting Jimmy (ACY CEO) return from SG (~2 weeks)
**Owner:** Donny
**Origin:** Jimmy WeChat 2026-05-27 — "看看能做些什么" across finlogix.com, acy.com, ACY Securities iOS App, tradingcup.com

---

## TL;DR

Ship a 6-week paid pilot on **tradingcup.com** (ACY's fake-money trading competition) that puts our **multi-persona AI debate engine** (Bull / Bear / Risk / PM synthesis) on every trade idea, in the competitor's native language. Fake money = no AFSL personal-advice exposure during pilot. Natural upgrade path to live ACY accounts in Phase 2 (paid SaaS, AFSL-governed via our `dim_ai_control` engine).

**Differentiation vs. every other fintech AI bot:** structured adversarial agents arguing both sides of a trade, with a PM synthesis verdict + invalidation level. Not a chatbot.

**Ask of ACY:** $5k/mo pilot (matches our [CI buildout pricing](./2026-05-07-ci-buildout-plan.md)) + leaderboard integration + post-pilot case study rights.

---

## Product: "AI Trade Council"

One-tap **"Ask the Council"** button on every TradingCup trade ticket:

| Agent | Output |
|---|---|
| **Bull** | Strongest case FOR the trade — catalysts, technicals, flow |
| **Bear** | Strongest case AGAINST — invalidation, contrarian read |
| **Risk** | Position sizing vs. existing book, correlation, stop placement |
| **PM** | Synthesis verdict: ENTER / REDUCE / SKIP + confidence % + invalidation level |

All in trader's native language (8 already live in stock.datap.ai).

**Council Scorecard** at competition end: per-trader P&L delta between trades that followed Council vs. ignored it. Publishable, shareable, virality-friendly.

---

## Why TradingCup first

1. **No AFSL personal-advice risk** — fake money + "educational AI research" framing. Still governance-logged via `dim_ai_control` so audit trail exists when we go live.
2. **Built-in distribution** — competitors will screenshot Council outputs ("Bear agent called this dump 2hrs early") into ACY's existing trader community. Free marketing.
3. **Measurable** — "Council-followers averaged X% better P&L" = a number Jimmy can put in ACY marketing.
4. **Natural Phase 2** — live accounts, Council outputs pass through AFSL pre-screen before display. That's the paid SaaS hook (~$15-30k/mo).

---

## Technical integration plan

### What we already have (stock-be)
- Synthesis pipeline: `agents.synthesis` (bull/bear/risk/PM personas, ROUNDS=1, per-persona max_tokens — last week's perf work)
- `load_synthesis_universe()` — engagement-aligned ticker source (commit 076ae2a)
- Partial-JSON guard + direction/signals sanity check (commit 5199161)
- 8-language prompts (from CI buildout / stock.datap.ai)
- LLM client via `DATAPAI_PLATFORM_DIR` env (platform-be is shared dep)
- Governance logging via `dim_ai_control` (platform-be)

### What ACY needs to expose
| Surface | Mechanism | Notes |
|---|---|---|
| Trade events | Webhook `POST /datapai/trade-intent` with `{user_id, symbol, side, qty, lang}` | Fires when user opens trade ticket |
| User language preference | Field on webhook OR `GET /user/{id}/profile` | Default `en` if absent |
| Leaderboard write-back | `POST /datapai/scorecard` with `{user_id, competition_id, council_followed, pnl_delta}` | End-of-competition write |
| FX/CFD instrument metadata | Static doc dump OK — list of TradingCup tradeable symbols | We adapt our equity-tuned personas to FX/CFD |

### What we build (6 weeks)
- **Week 1-2:** TradingCup symbol universe loader (FX/CFD adapter for `load_synthesis_universe`); persona prompt tuning for FX/CFD (different vs. equities — no earnings catalysts, more macro/rate flow)
- **Week 3:** ACY webhook receiver + Council API endpoint (`POST /council/v1/synthesize`); response <8s p50 (existing synthesis is ~6s after the ROUNDS=1 fix)
- **Week 4:** Native-language rendering pipeline reuse; embed widget (iframe OR JSON-for-native-render — Jimmy picks)
- **Week 5:** Scorecard aggregation job (Airflow DAG, per project rule no crontab); leaderboard write-back
- **Week 6:** Pilot launch with one TradingCup cohort; daily metrics review

### Stack decisions (locked)
- Hosting: DATAP.AI EC2 (platform.datap.ai), customer-VPC-ready architecture for Phase 2
- Scheduling: Airflow only (no crontab)
- LLM: gemini-2.5-flash for personas (NOT flash-lite — silent empty responses on function calls)
- Governance: every Council output logged to `dim_ai_control` + `fct_ai_*` tables — same engine we'll sell to commercial SaaS partners

---

## Phase 2 upgrade path (post-pilot, live ACY accounts)

- Council pre-screen via AFSL governance gate (`dim_ai_control` rules: no specific price targets without disclaimer, no guaranteed-return language, mandatory risk warning per jurisdiction)
- Per-jurisdiction routing (AU = AFSL, SG = MAS, etc.) — slots cleanly into existing `dim_ai_control` design
- Pricing tier $15-30k/mo per ACY entity

---

## What's on us before Jimmy lands

- [ ] One-pager PDF (this doc, condensed to 1 page) — forward-able to Jimmy on WhatsApp
- [ ] Quick recon on finlogix.com, acy.com, ACY Securities iOS app, tradingcup.com — confirm assumptions about embed surfaces
- [ ] Validate FX/CFD synthesis quality with 5-10 symbols on staging before the meeting
- [ ] Draft pilot SOW (6 weeks, $5k/mo, deliverables, success metrics, case-study rights)

## What we explicitly defer

- finlogix replacement — too big for first conversation, revisit if pilot lands
- acy.com web platform integration — Phase 2
- iOS app integration — Phase 2 (requires native SDK work)
- Live-money governance gate — Phase 2

---

## Related

- [CI buildout plan (2026-05-07)](./2026-05-07-ci-buildout-plan.md) — ACY was already on the 5-demo target list
- [Government vertical plan (2026-04-23)](~/git/datapai-platform-be/docs/phase-journals/2026-04-23-government-vertical-plan.md) — same `dim_ai_control` engine pattern
- [Salesforce/SAP/BMC deploy model](~/.claude/projects/-Users-linlin-git-datapai-stock-be/memory/project_salesforce_mcp_deploy_model.md) — customer-VPC-first applies to ACY Phase 2 too
- Synthesis perf commits (this branch): 076ae2a, 5199161, e4064b4, da30dad, 7032152
