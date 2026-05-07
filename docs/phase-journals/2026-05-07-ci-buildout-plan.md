# Customer Intelligence (CI) — End-to-End Build Plan

> **Mission**: Ship a multilingual AI chatbot + CRM signal layer for AU fintech, leveraging the existing chat / governance / catalog stack. Goal = 2 paying pilots within 30 days, 5 logos within 60 days, $30–80k cash collected.
>
> **Date**: 2026-05-07 · **Origin session**: see `~/.claude/projects/-Users-linlin-git-datapai-stock-be/` · **Owner**: Donny Zhao

---

## 1. Why CI > pure AI Governance for our stage

Pure "AI Governance" lands flat on prospects who don't yet use AI. Most AU fintechs (CoinSpot, Independent Reserve, mid-tier brokers) **don't have customer-facing AI today**, but **do have visible chat pain** (no chatbot or rule-based dumb chatbot). CI inverts the wedge:

| Lever | "AI Governance" pitch | **"CI / CRM+AI" pitch** |
|---|---|---|
| Pain visibility | Hidden (need compliance interview) | **Visible from homepage** |
| Demo time | Days | **90 seconds** |
| Deploy time | Weeks (vendor risk review) | **Hours** (JS embed) |
| Buyer | Compliance / CRO | **Head of Growth / CEO** |
| Budget bucket | Compliance (slow) | **Marketing / customer success (fast)** |
| ROI metric | Audit defensibility (abstract) | **24/7 coverage, 50%+ deflection, 3× lead capture** |

Compliance becomes the **moat** (procurement decider), not the **headline** (buyer hook).

---

## 2. Differentiation triangle — must hit all three

1. **Deep multilingual** — CN (Simp + Trad), JP, KR, VI, TH, ID, MS — *tone-correct, not Google Translate*
2. **AFSL / AUSTRAC / ASIC RG274 governance baked in** — citations under the hood, write-once audit row per turn
3. **CRM-aware tiering** — first-time visitor vs $50k VIP get different treatments; suspicious AML pattern blocks + alerts

No competitor (Intercom, Drift, Zendesk Answer Bot, Ada, Yellow.AI, Forethought) hits all three. Most hit zero for AU FS context.

---

## 3. Existing assets to leverage (DO NOT REBUILD)

### Backend (datapai-stock-be / datapai-platform-be)
| Asset | Path | Purpose |
|---|---|---|
| Streaming chat endpoint | `agents/stock_chat/endpoint.py` :: `stock_chat_stream()` | SSE chat with Gemini function calling — **clone for `/agent/ci-chat/stream`** |
| AI governance gateway | `agents/stock_chat/guardrail_bridge.py` :: `run_gate_sync()` | Pre-call gate, citations, write-once audit. Reusable as-is. |
| Catalog loader | `guardrail_bridge.py` :: `_load_catalog_summary()` | DB-driven framework summary, 5-min cache |
| Multi-LLM router | `datapai-platform-be/agents/llm_client.py` :: `RouterChatClient` | OpenAI / Bedrock / Google / Fireworks / Ollama with optional dual review |
| Function-tool pattern | `endpoint.py` :: `get_stock_price` + `get_fx_rate` | Template for tenant-specific tools |
| AG2 multi-agent debate | `agents/stock_synthesis/synthesis_pipeline.py` | Premium-tier "multi-agent reviewer" feature later |

### Database
| Table | Host | Purpose |
|---|---|---|
| `datapai.dim_ai_control_finance` | `datapai_framework_db:5433/datapai_auth_db` | Policy catalog (258 controls / 20 frameworks incl. AFSL + AUSTRAC) |
| `datapai.fct_ai_guardrail_decision` | same | Write-once governance audit |
| `datapai.chat_messages` | `datapai_stock_db:5434` | Existing chat audit (reuse table shape) |
| `auth.users` | `datapai_framework_db` | User auth (reuse for tenant admin login) |

### Frontend (datapai-stock-fe)
| Asset | Path | Purpose |
|---|---|---|
| Chat client implementation | scattered across `app/components/` | SSE chunk parsing pattern — clone for widget |
| i18n labels system | `lib/i18n.ts` + `/api/i18n/labels` | Reuse for widget + dashboard UI |

### Infrastructure
| Service | Port | Reuse |
|---|---|---|
| `datapai-agent.service` (FastAPI) | 8005 | Add `/agent/ci-chat/*` routes here at first |
| `stock-fe.service` (Next.js) | 3085 | Host MVP dashboard at `/ci-admin` until split repo |
| EC2 deploy: `bash sync.sh` + `sudo systemctl restart` | — | Same pattern |

---

## 4. Architecture (target state)

```
┌──────────────────────┐
│  Customer's website  │
│  <script src="...    │   1. JS embed (1-line install)
│   ci.datap.ai/embed/ │
│   v1/widget.js">     │
└──────────┬───────────┘
           │ HTTPS SSE
           ▼
┌──────────────────────┐
│  ci.datap.ai         │   2. Widget loads, calls /agent/ci-chat/stream
│  (Next.js + edge)    │      with tenant_id (from script src)
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  datapai-ci-be       │   3. FastAPI: chat stream + tools + governance
│  (port 8006 EC2)     │      → run_gate_sync (AFSL/AUSTRAC catalog)
│                      │      → Gemini 2.5 Flash with tenant tools
│                      │      → tenant doc retrieval (pgvector)
│                      │      → CRM webhook on lead capture
└──┬────────────────┬──┘
   │                │
   ▼                ▼
┌─────────┐   ┌──────────────┐
│ datapai_│   │ Customer's   │
│ ci_db   │   │ CRM (Sales-  │
│ (5437)  │   │ force /      │
│ tenants │   │ HubSpot /    │
│ docs    │   │ Twenty /     │
│ chats   │   │ Pipedrive)   │
│ leads   │   └──────────────┘
└─────────┘

         ┌──────────────────────┐
         │ app.ci.datap.ai      │   4. Tenant admin dashboard
         │ (Next.js, port 3086) │      - Embed code
         │                      │      - Doc upload + crawl
         │                      │      - Chat logs + audit
         │                      │      - Customer Intelligence
         │                      │      - AFSL evidence packs
         └──────────────────────┘
```

### Naming convention
- Repo: `datapai-ci-be` (Python FastAPI), `datapai-ci-fe` (Next.js)
- Service: `datapai-ci-agent.service` (port 8006), `ci-fe.service` (port 3086)
- Domain: `ci.datap.ai` (widget host) + `app.ci.datap.ai` (dashboard)
- DB: `datapai_ci_db` on port 5437 (or new instance)
- API path: `/agent/ci-chat/stream`, `/embed/v1/widget.js`, `/api/tenant/...`

### Data isolation
- Tenant data in `datapai_ci_db` — **strict tenant_id row-level isolation** (RLS or app-layer enforcement)
- Governance catalog **stays in `datapai_framework_db`** (shared across products)
- Customer VPC deployment option for Tier-3 enterprise customers (Year 2)

---

## 5. Phased build plan

### Phase 0 — Decisions to make on Day 1 (≤2 hours)

- [ ] Confirm new repo vs sub-folder of stock-be → **recommend new repo `datapai-ci-be`**
- [ ] Confirm DB: new instance vs share stock_db → **recommend new instance `datapai_ci_db:5437`**
- [ ] Confirm domain DNS for `ci.datap.ai` (widget) + `app.ci.datap.ai` (dashboard)
- [ ] Confirm widget look-and-feel (open-source base?): **recommend Chatwoot widget OSS as scaffold**, customise
- [ ] Confirm initial CRM target: **recommend HubSpot first** (free tier, easy OAuth) → Twenty (open-source) → Salesforce → Pipedrive

---

### Phase 1 — MVP backend (Days 2–6)

**Goal: end-to-end chat working from a fake customer's website to LLM with governance + tenant context.**

#### 1.1 New repo + bootstrap (4 hrs)
- [ ] `datapai-ci-be/` repo initialised, FastAPI scaffold, requirements.txt
- [ ] Reuse `RouterChatClient` from `datapai-platform-be/agents/llm_client.py` via `PYTHONPATH` (same pattern as stock-be)
- [ ] systemd unit on EC2: port 8006
- [ ] CORS whitelist (will be tightened in Phase 5)

#### 1.2 Tenant schema + admin endpoints (8 hrs)
- [ ] DB: `ci_tenant` table — `id, slug, display_name, languages_enabled[], system_prompt_extra, afsl_number, brand_color, logo_url, status, created_at`
- [ ] DB: `ci_tenant_apikey` table (tenant scoped widget keys)
- [ ] DB: `ci_tenant_crm` table (encrypted CRM credentials)
- [ ] CRUD endpoints `/api/tenant/...` (admin auth required)
- [ ] Seed 1 fixture tenant: `slug=demo-fintech`, with brand colour, sample system prompt

#### 1.3 Tenant doc ingestion (12 hrs)
- [ ] DB: `ci_tenant_doc` (id, tenant_id, source_type [url|upload], source_url, title, content, embedding `vector(1536)`, created_at) — pgvector
- [ ] URL crawler: given a homepage URL, crawl docs (sitemap.xml + 1-hop pages, max 50 URLs, robots.txt respected)
- [ ] Embedder: OpenAI text-embedding-3-small or local fallback
- [ ] `/api/tenant/{slug}/docs/crawl` (kick off async ingest)
- [ ] `/api/tenant/{slug}/docs/upload` (file upload PDF/MD/TXT → chunk → embed)

#### 1.4 Chat stream endpoint (16 hrs) — clone of stock-chat with tenant awareness
- [ ] `/agent/ci-chat/stream` (SSE) accepting `{tenant_slug, session_id, message, lang}`
- [ ] Reuse `run_gate_sync()` from guardrail_bridge → pass tenant metadata `{domain: tenant_slug, afsl_number, classification_hint}`
- [ ] Reuse Gemini streaming pattern from `stock_chat/endpoint.py` (the function-call loop, the `thought` filter, `gemini-2.5-flash` model — DO NOT use `*-lite`, see `feedback_no_gemini_lite_fn_calls.md`)
- [ ] System prompt builder: `_ROLE_BASE` + tenant brand block + tenant docs context (top-K retrieval) + governance constraint if blocked
- [ ] Function tools (start with 1): `capture_lead(name, email, phone, intent, locale)` — writes to tenant CRM + `ci_lead` table
- [ ] Language detection + force-reply-in-language rule (proven on stock-chat, port verbatim)

#### 1.5 Governance footer in widget (4 hrs)
- [ ] Reuse `footer_markdown(gate_result, blocked=...)` from guardrail_bridge — **same pattern, same SSE event**
- [ ] Widget renders the structured `governance` event as a discrete badge (collapsed by default, expandable)

#### 1.6 Lead capture pipeline (8 hrs)
- [ ] On tool-call `capture_lead`: insert `ci_lead` row + emit webhook to tenant CRM via `ci_tenant_crm` config
- [ ] HubSpot connector first (OAuth + Contacts API)
- [ ] Twenty connector second (REST API, simpler)
- [ ] Salesforce + Pipedrive in Phase 4

**Phase 1 acceptance**: curl-test the SSE endpoint with `tenant_slug=demo-fintech` in CN/EN/JP, see appropriate replies + governance footer + a captured lead row in DB.

---

### Phase 2 — Embeddable widget (Days 7–9)

**Goal: a JS snippet a customer pastes into their site that opens our chat in their branding.**

#### 2.1 Widget repo + bundler (4 hrs)
- [ ] `datapai-ci-fe/embed/` — Vite or esbuild bundling to single `widget.js` (target IE11+ not needed; modern only)
- [ ] Hosted at `https://ci.datap.ai/embed/v1/widget.js`

#### 2.2 Widget behaviour (12 hrs)
- [ ] Floating bubble (bottom-right by default), brand colour from tenant config
- [ ] Click → opens chat panel (or full screen on mobile)
- [ ] SSE consumer for `/agent/ci-chat/stream`
- [ ] Markdown rendering, links open in new tab
- [ ] Streaming chunk rendering (incremental text)
- [ ] Governance event: discrete badge "✅ Governed by APRA / ASIC / AFSL / AUSTRAC" — clickable for detail
- [ ] Language picker (defaults to browser `navigator.language`)
- [ ] Persistent session_id in localStorage

#### 2.3 1-line install snippet
```html
<script async
  src="https://ci.datap.ai/embed/v1/widget.js"
  data-tenant="demo-fintech"
  data-lang="auto"
></script>
```

#### 2.4 Demo page
- [ ] `https://ci.datap.ai/demo` — fake "Independent Reserve sandbox" with the widget embedded — **what we send to prospects in cold outreach**

**Phase 2 acceptance**: Embed the widget on a static HTML test page, chat works, governance footer shows, language switching works, lead is captured to a test HubSpot.

---

### Phase 3 — Tenant admin dashboard MVP (Days 10–14)

**Goal: a customer can self-serve sign up, paste their docs URL, and copy their embed snippet.**

#### 3.1 Auth + tenant onboarding (8 hrs)
- [ ] Reuse `auth.users` from framework_db
- [ ] Sign-up flow: name, email, company → creates tenant record + admin user
- [ ] Tenant dashboard URL `app.ci.datap.ai/{tenant_slug}`

#### 3.2 Onboarding wizard (8 hrs)
- [ ] Step 1: enter homepage URL → crawler runs in background
- [ ] Step 2: confirm pages to include (checkbox list of crawled URLs)
- [ ] Step 3: select languages, brand colour, AFSL number (optional), CRM choice
- [ ] Step 4: copy embed snippet

#### 3.3 Live chat-log view (4 hrs)
- [ ] Chat history table — searchable, filterable by lang/intent/governance verdict
- [ ] Click row → see full transcript + governance citations + linked lead

#### 3.4 Customer Intelligence panel (8 hrs)
- [ ] Daily summary widget: top intents, top languages, conversion funnel, churn signals
- [ ] Powered by a nightly CRON over `ci_lead` + `chat_messages` tables (reuse Airflow on EC2)

**Phase 3 acceptance**: New prospect can sign up, paste URL, copy embed, see chats in dashboard within 1 hour from zero.

---

### Phase 4 — CRM connectors (Days 15–18)

- [ ] Salesforce OAuth + Lead/Contact create
- [ ] Pipedrive OAuth + Person/Deal create
- [ ] Twenty OSS REST integration (for OSS-aligned prospects)
- [ ] CRM webhook event: every chat session end → push summary to CRM as Note/Activity
- [ ] CRM tier-aware tiering: lookup existing customer → adjust system prompt (VIP / standard / new)

---

### Phase 5 — Demo polish + first cold outreach (Days 19–21)

- [ ] **Tenant fixture for "Independent Reserve sandbox"** — full crawl of their public site, demo widget on `ci.datap.ai/demo/independent-reserve` (sandbox label clear)
- [ ] Same for **TMGM, ACY, Stake, CoinSpot** — 5 sandbox demos pre-built
- [ ] Side-by-side video: their current chat vs ours, in CN
- [ ] Cold-outreach email template + Loom recording
- [ ] Pricing page on `ci.datap.ai/pricing`

**Phase 5 acceptance**: 5 sandbox demos live, cold-email queue ready to send.

---

### Phase 6 — Pilot deployment (Days 22–30)

**Goal: 1–2 paying pilot customers signed at $5–10k/month × 3 months minimum.**

- [ ] Convert sandbox demo → real tenant for first paying customer
- [ ] Production CRM connection
- [ ] SLA: 99.9% uptime, 24-hour support response
- [ ] Pilot SOW template (3-month, $5k/month, success metrics)

---

## 6. First-customer cold outreach plan

### Targets ranked by closability

| # | Target | Why fast | First contact |
|---|---|---|---|
| 1 | **CoinSpot** | AUSTRAC heat, biggest AU consumer brand, no chat visible | CEO Russell Wilson |
| 2 | **Independent Reserve** | AUSTRAC heat, multilingual customers | CEO Adrian Przelozny |
| 3 | **Swyftx** | Recovering brand, needs compliance signal | CEO Jason Titman |
| 4 | **TMGM** | Public AI product = ASIC headline risk | Head of Compliance / Marketing |
| 5 | **ACY Securities** | Mandarin retail = our differentiator | CRO via LinkedIn |
| 6 | **Stake** | Consumer brand, Asian market push | Head of Customer / Growth |
| 7 | **Sharesies AU** | Multilingual NZ-AU pressure | Head of Customer |
| 8 | **Spaceship** | Consumer brand, board-mandated AI | CEO |

### Pitch (1 line)
> *"Here's your chat → here's mine, in Mandarin, on your products. Three days to deploy, $5k/month pilot, every reply is AFSL/AUSTRAC-defensible by construction."*

---

## 7. Pricing model

| Plan | Monthly | Setup | Target buyer |
|---|---|---|---|
| Pilot | $5,000 / 3 mo min | $5,000 | First-customer logos |
| Growth | $2,500 | $5,000 | Robos / mid-tier brokers |
| Pro | $7,500 | $10,000 | CFD/FX brokers, crypto exchanges |
| Enterprise | $20,000+ | custom | Banks, large AFSL holders |

Setup fee covers brand/content training + CRM wiring + AFSL evidence pack templates.

---

## 8. Risk register

| Risk | Mitigation |
|---|---|
| **Asian-language quality criticised by native speaker** | Hire CN/JP/KR fluent QA contractor for $2k 2-day audit before first pilot ships. |
| **"We already have Intercom"** objection | Counter: "Intercom doesn't know AFSL. ASIC asks for chat audit, you're exposed." Demo the citation. |
| **CRM connector reliability** | Start with HubSpot only (richest free tier). Add Salesforce only when first paying customer needs it. |
| **gemini-2.5-flash-lite trap** | DO NOT USE. See `feedback_no_gemini_lite_fn_calls.md`. Use `gemini-2.5-flash`. |
| **`--delete` rsync wipes EC2 hot-fix** | sync.sh has no `--delete`. See `feedback_ec2_is_source_of_truth.md`. |
| **Multitenancy bugs leak data across tenants** | RLS or app-layer enforcement on every query. End-to-end pen test before first paying customer. |
| **Compliance citation goes wrong** | Reuse `run_gate_sync` verbatim — already battle-tested in stock-chat with AFSL + AUSTRAC catalog. |

---

## 9. What the new session needs to know on Day 1

### Key environment / connection details
- EC2: `ssh -i ~/.ssh/Linux-CodeCambat.pem ec2-user@platform.datap.ai`
- DB ports: framework_db=5433, stock_db=5434 (see `reference_ec2_ssh.md`)
- LLM env: `GOOGLE_MODEL=gemini-2.5-flash` (NOT lite), `GOOGLE_API_KEY` in `~/.env.dev`
- Catalog: `datapai_framework_db.datapai_auth_db.datapai.dim_ai_control_finance` — 258 controls / 20 frameworks live, AFSL + AUSTRAC included
- Backend: `datapai-agent.service` on port 8005 (FastAPI), reuse `RouterChatClient` from platform-be

### Critical patterns (DO NOT DEVIATE)
1. **Service split**: keep ci-be on its own port (8006), separate systemd unit, separate sync.sh
2. **Fail-open governance**: every call to `run_gate_sync` wraps in try/except, never block availability
3. **`thought` part filter**: gemini-2.5-flash returns chain-of-thought parts — `if part.get("thought"): continue`
4. **`function response` envelope**: `{"functionResponse": {"name": fn_name, "response": {"name": fn_name, "content": fn_result}}}` — verified working with gemini-2.5-flash
5. **Footer**: `footer_markdown(gate, blocked=False)` for allow path — reuse, don't reinvent
6. **AFSL evidence pack** = SQL over `fct_ai_guardrail_decision` joined to `dim_ai_control_finance` — already wired
7. **Multi-language**: prompt rule = "reply 100% in user's language including labels and disclaimer"

### Files to read first (in order)
1. `datapai-stock-be/agents/stock_chat/endpoint.py` — the chat streaming pattern to clone
2. `datapai-stock-be/agents/stock_chat/guardrail_bridge.py` — governance gateway (reuse as-is)
3. `datapai-stock-be/agents/stock_chat/context_builder.py` — system prompt structure
4. `datapai-platform-be/agents/llm_client.py` — RouterChatClient
5. `datapai-platform-be/agents/ai_governance_guardrail/policy_loader.py` — domain → table routing
6. This document.

### Key memory pointers
- `feedback_no_gemini_lite_fn_calls.md` — model trap to avoid
- `feedback_ec2_is_source_of_truth.md` — sync hygiene
- `feedback_airflow_only.md` — internal scheduling rule
- `feedback_db_driven_default.md` — no hardcoded plan/limit lists
- `feedback_document_major_changes.md` — write a phase journal at every milestone
- `project_tinyfish_cost_fix.md` — Next.js EC2 build steps if FE deploy hits zombie ports

---

## 10. Day-by-day sprint board (30 days)

| Day | Phase | Deliverable |
|---|---|---|
| 1 | 0 | Architecture decisions confirmed; new repo created; DB instance provisioned |
| 2–3 | 1.1–1.2 | FastAPI bootstrap; tenant schema; CRUD endpoints |
| 4 | 1.3 | Doc ingestion (URL crawl + pgvector) |
| 5–6 | 1.4–1.6 | Chat stream endpoint + governance integration + HubSpot lead capture |
| 7–8 | 2.1–2.2 | Widget bundler + bubble + chat panel + SSE consumer |
| 9 | 2.3–2.4 | Embed snippet + demo page |
| 10–11 | 3.1–3.2 | Auth + tenant onboarding wizard |
| 12 | 3.3 | Chat-log view |
| 13–14 | 3.4 | Customer Intelligence panel + nightly aggregator |
| 15–16 | 4 | Salesforce + Pipedrive + Twenty connectors |
| 17 | 4 | CRM webhook events + tier-aware system prompts |
| 18 | 4 | Pen test + multi-tenant isolation audit |
| 19–20 | 5 | 5 sandbox demos pre-built (CoinSpot, Indep Reserve, Swyftx, TMGM, ACY) |
| 21 | 5 | Cold outreach kit (email template + Loom + pricing page) |
| 22 | 6 | First cold outreach batch sent |
| 23–25 | 6 | Discovery calls + first pilot SOW signed |
| 26–28 | 6 | First pilot deployment in production |
| 29 | 6 | Phase journal at `~/git/datapai-ci-be/docs/phase-journals/2026-06-XX-pilot-1.md` |
| 30 | 6 | First $5k invoice issued; cycle repeats with prospect 2 |

**End of D30 target**: 1 paying pilot live, 1 in onboarding, 5 logos in pipeline, 1 phase journal committed.

---

## 11. Out of scope for first 30 days (Year 2 backlog)

- AG2 multi-agent reviewer (premium tier)
- Voice (Twilio) channel
- WhatsApp / Telegram channel
- Customer VPC deployment (enterprise tier)
- IRAP / SOC 2 / ISO 27001 cert (start now in parallel)
- Marketplace listings (Snowflake Native App, AWS Marketplace, Salesforce AppExchange)
- Multi-region (US, SG)
- White-label option for Big-4 channel partners

---

## 12. Success criteria (D30 review)

| Metric | Target |
|---|---|
| Phases 0–5 shipped end-to-end | ✅ |
| 5 sandbox demos live | ✅ |
| Cold outreach sent to 20 prospects | ✅ |
| Discovery calls held | ≥5 |
| Paid pilots signed | ≥1 |
| Cash collected | ≥$5,000 |
| Logos on website | ≥3 (incl. sandbox-permission logos) |
| Phase journal written + committed | ✅ |

If we miss "paid pilot signed", we don't have product-market fit on the wedge — pivot to next-strongest cohort (e.g. AU robo-advisors instead of crypto exchanges).

---

## 13. Hand-off to new session

Open the new Claude session in `~/git/datapai-ci-be` (after creating the repo). First message:

> "Read `~/git/datapai-stock-be/docs/phase-journals/2026-05-07-ci-buildout-plan.md`. Confirm the architecture decisions in §4. Then start Phase 1.1 — bootstrap the FastAPI repo and import RouterChatClient. Follow the patterns from datapai-stock-be/agents/stock_chat/endpoint.py."

Everything the new session needs is in this doc + the linked memory files + the existing stock-be code.

---

**Author**: Claude (anthropic) · **Reviewed by**: Donny Zhao · **Status**: Approved for execution · **Next phase journal**: `2026-05-XX-ci-phase-1-mvp.md`
