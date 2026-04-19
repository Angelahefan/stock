# Phase 2.0 — AI Governance Product Execution Plan (SAP + BMC / Control-M channel)

> **Status:** v0.3 (2026-04-19) — strategic plan for coming weeks. Living document, reviewed weekly.
> **Authorization:** User directive 2026-04-19 — "prepare a details execute plan… build the AI governance that SAP and Control-M needed on top of my platform." Follow-up directive same day: "skip partner DD questions, chicken-or-egg, if there's real value we just implement it, speed does matter." Plan revised v0.1 → v0.2 accordingly — see §15 Changelog.
> **Phase numbering:** Phase 1.x was internal fixes + virtual-customer hardening. Phase 2.x is productisation — shipping AI governance as a sellable plugin/add-on via BMC + SAP partner channel.
> **Canonical home (future):** `datapai-platform-be/docs/strategy/` — platform-be is the product being sold. Drafting here in `datapai-stock-be` because that's where the AI audit foundation lives; mirror to platform-be when cross-repo alignment checkpoint completes (Week 2).
> **Related docs:**
> - `docs/architecture/ai-audit-trail.md` — foundation pattern (Phase 1.13, live)
> - `docs/architecture/fdw-gotchas.md` — data-plane constraint to preserve
> - `docs/phase-journals/2026-04-12-phase-1.13-chat-audit-design.md` — precedent for cold-tier S3 Parquet
> - `~/.claude/projects/.../memory/project_datapai_portfolio_gtm.md` — portfolio + GTM strategic memory

---

## 0.5 Starting line — what's already shipped (2026-04-19 inventory, v0.3)

**The original v0.1/v0.2 plan significantly understated the existing codebase.** Before re-planning, the actual starting line is:

> **All existing modules are EARLY STAGE — a lot of rework expected** (user clarifications 2026-04-19: "draft, not prod readiness" + "haven't test it yet, early stage, a lot of work to re-do"). The design exists in code form; the *implementation may not work end-to-end*. Treat the inventory below as **prior art / reference implementation + vocabulary + decisions**, not as shipping code. Any Week-1 deliverable that "extends existing X" may actually require reworking X first — timelines below are aspirational compression relative to from-scratch, not guarantees. Each weekly retrospective will adjust based on rework actuals.

### Already live in `datapai-platform-be`

| Module | What it does | Where |
|---|---|---|
| **AI Guardrail Framework v1.4** | Policy catalog compiler (reads dbt `meta.datapai.*`), warehouse-native compiler (reads guardrail mart), runtime validators (SQL, retrieval, summary, tool-action), governed-action 13-step lifecycle, context filter | `guardrail/policy_compiler.py`, `warehouse_compiler.py`, `metadata_schema.py`, `validators.py`, `governed_action.py`, `context_filter.py` |
| **Trace ledger** | Append-only agent trace events; Snowflake (prod) + SQLite (dev) backends; PII/PHI redaction; replay for audit | `traceability/ledger.py`, `backends/snowflake_backend.py`, `redaction.py`, `replay.py` |
| **Metadata schema** | Dataclasses for `AiAccessLevel`, `SensitivityLevel`, `AnswerMode`, `ExportPolicy`, `RetrievalPolicy`, `SummarizationPolicy`, `ExplanationPolicy`, model + column policy objects | `guardrail/metadata_schema.py` |
| **Control-M integration pack** | Job templates (debate, archive, agent-audit, policy reload), shell wrappers, standardised exit codes, auto-captured Control-M context in audit trail, 15-min install guide | `integrations/control_m/` |
| **Multi-LLM router + cost guard** | Claude/OpenAI/Gemini/Ollama + per-model budgets | `agents/llm_client.py`, `agents/cost_guard.py` |
| **Ship-with boundary doc** | Explicit rule: platform-be does not compete with BMC or SAP products; integrates alongside them | `docs/ship-with.md` |

### Already live in `dbt-demo`

| Layer | What exists |
|---|---|
| **Demo domains** | `full-jaffle-shop` (B2C/PII/finance), `chinook` (media/HR), `stock` (stub) |
| **`ai_mart` models** | `dim_ai_governed_assets`, `dim_ai_governed_fields`, `fct_ai_asset_quality`, `fct_ai_asset_runtime_eligibility`, `fct_ai_policy_catalog_versions` |
| **Seeds** | `ai_governed_assets_seed`, `ai_governed_fields_seed` |
| **Adapters configured** | Snowflake (`datapai_snowflake` profile), Postgres (`jaffle_shop` profile), Redshift (`datapai.ci_fal` profile) |
| **Integrations** | `elementary-data` + `dbt-labs/audit_helper` — quality signals feed the mart |
| **BI** | Lightdash connected |

### What this means for Phase 2.x

- **Dim/fact + SCD2 + dbt + Snowflake is not "to build" — it exists.** Our contribution is *extending the schema* with external compliance frameworks + AI-system-level register + immutable-bronze layer.
- **Control-M integration is not "to build" — it exists.** Our contribution in P2.2 is BMC HelixGPT + BMC Discovery connectors on top, not Control-M itself.
- **Snowflake + Lightdash are not "to set up" — they exist and are referenced from platform-be.** Our contribution is the governance dashboard content, not the infrastructure.
- **Trace ledger already captures LLM agent activity with Snowflake persistence.** Our contribution is (a) an **OTel GenAI adapter** so non-platform LLM sources can feed it, and (b) an **S3 Object Lock COMPLIANCE bronze layer** so the authoritative audit record is truly immutable (Snowflake is mutable).

**Net effect: Phase 2.1 MVP shortens from 4 weeks to ~2 weeks.** The original 12-week plan compresses to ~8 weeks realistic.

---

## 0. Executive summary

Build a **multi-jurisdiction AI governance product** on top of `datapai-platform-be`, using `datapai-stock-be` as the virtual customer. Ship it as a **plugin/add-on** into existing customer infrastructure (cloud, VPC, warehouse, scheduler) — **zero data migration, value-in-day-one**. Distribute via a concrete **BMC golden partner** relationship with strong **SAP** access. Coverage: Australia 6 Practices (Oct 2025), NIST AI RMF 1.0 + Gen AI Profile, UK 5 Principles, ISO/IEC 42001:2023, FINRA 24-09 (financial services), Colorado AI Act, FCA guidance. Same data model powers three buyer-persona wedges: **AI Governance** (Compliance / CAIO), **LLM FinOps** (CFO), **Shadow AI / LLM DLP** (CISO). Phase 2.0 runs ~12 weeks to a working product + first-customer POC.

---

## 1. Strategic context and positioning

### 1.1 The bet

DATAP.AI's platform-be becomes a **compliance-native, warehouse-agnostic, channel-delivered AI governance add-on**. Customers do not migrate data. They install a dbt package + a small OLTP register + OTel ingest + dashboard templates on their own infrastructure. The product emits **auditor-grade evidence** (compliance PDFs, cryptographic lineage, WORM-locked raw telemetry) for AU/US/UK regulators simultaneously.

### 1.2 Channel-first distribution

- Primary channel: **BMC golden partner** (personal relationship) with co-sell reach into SAP accounts.
- Secondary adjacent channels (deprioritised for Phase 2.0): ServiceNow Store, Salesforce AppExchange, AWS Marketplace for procurement.
- **Snowflake Marketplace / Databricks Marketplace deprioritised** — no seller relationships. Adapters stay live so a walk-in deal can be served, but no listing investment.

### 1.3 Virtual customer strategy

`datapai-stock-be` is customer #0. Every governance primitive must prove itself against real stock-agent traffic (existing OpenLIT telemetry, chat_messages, roles + governance-audit) *before* being packaged for external sale. `datapai-healthcare-be` is customer #1 internally, activating once finance vertical is stable.

### 1.4 Target customer profile

BMC and SAP accounts overlap almost perfectly with AI governance buyers:

| Attribute | Profile |
|---|---|
| Size | Global 2000, regulated |
| Verticals | Banking, insurance, pharma, manufacturing, utilities, telco, government |
| Geography | AU, US, UK, EU, DACH, Japan |
| Existing infra | Mix of on-prem + AWS/Azure; SAP S/4HANA or BTP; BMC Helix or Control-M for orchestration |
| Current AI governance maturity | Low — most have pilot-stage AI without formal control frameworks |
| Budget owner | Chief AI Officer, CRO, CISO, CCO — varies by org |
| Forcing function | AU Oct 2025 guidance, Colorado AI Act (Feb 2026), EU AI Act (2025-27), FINRA 24-09, FCA, ISO 42001 certification requirements |

---

## 2. Product definition

### 2.1 One data model, three wedges

| Wedge | Persona | Entry pitch | Primary artefact |
|---|---|---|---|
| **AI Governance** | Chief AI Officer / CRO / Compliance | "Auto-generated quarterly compliance evidence for AU 6 + NIST + FINRA, from your actual AI telemetry" | Compliance PDF, control evidence dashboard |
| **LLM FinOps** | CFO / Head of Platform | "Per-team, per-product, per-user LLM cost attribution and right-sizing recommendations" | Cost dashboard, anomaly alerts |
| **Shadow AI / LLM DLP** | CISO | "Discover every AI system in your org, detect PII-in-prompts and data exfiltration paths" | System inventory report, DLP incident log |

Same warehouse schema, ~80% shared models. Different dashboards, different sales motions, different buyers.

### 2.2 Packaging

- **`datapai_ai_governance` dbt package** — the analytical layer; customer's own warehouse
- **`platform-be governance service`** — OLTP register for AI systems, accountable parties, risk assessments, incidents, human-oversight events; Postgres schema with version-controlled migrations (Alembic)
- **OTel GenAI collector bundle** — Helm chart for Kubernetes; Docker Compose for on-prem; SAP BTP Kyma manifest; BMC Helix integration module
- **Control-M job bundle** — declarative job definitions for batch ingest, for customers on BMC Control-M instead of Airflow
- **Dashboard pack** — Streamlit (self-host, MIT), plus PowerBI / Looker / SAP Analytics Cloud templates
- **Evidence generator** — Python service that renders compliance-framework PDFs from the warehouse (ISO 42001, AU 6, NIST AI RMF, Colorado, FINRA)

### 2.3 Form factor constraints (non-negotiable)

Derived from strategic memory `project_datapai_portfolio_gtm.md` — *"would this run cleanly in a stranger's SAP BTP tenant or BMC Helix environment tomorrow?"* is the gating question for every design decision.

- No customer data leaves customer's warehouse
- No customer warehouse migration required
- No customer network-topology change required
- dbt package adapter-aware (Snowflake, Databricks, BigQuery, SAP Datasphere, Postgres at minimum)
- OLTP service deployable to SAP BTP Kyma, customer Postgres, or a DATAP.AI-hosted SaaS tenant
- Identity pluggable: SAP IAS/IPS, BMC Helix SSO, OAuth2/OIDC generic, platform-be native

---

## 3. Technical architecture overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CUSTOMER ENVIRONMENT                                │
│                                                                              │
│  ┌──────────────────────────────┐                                           │
│  │  LLM runtimes                 │                                           │
│  │  • OpenAI / Anthropic APIs    │                                           │
│  │  • SAP AI Core + Joule        │                                           │
│  │  • BMC HelixGPT               │                                           │
│  │  • Self-hosted (vLLM etc.)    │                                           │
│  └──────────┬────────────────────┘                                           │
│             │ OTel GenAI semantic conventions                                │
│             ▼                                                                 │
│  ┌────────────────────────────────────────────────────────────┐             │
│  │  OTel Collector (DATAP.AI bundle)                           │             │
│  │  • OpenLIT / Langfuse / native OTel input                   │             │
│  │  • Redaction + PII detection filter                         │             │
│  │  • Dual-write: S3 WORM bronze + CDC to OLTP register        │             │
│  └──────────┬────────────────────────────────┬────────────────┘             │
│             │                                 │                              │
│             ▼ append-only writes              ▼                              │
│  ┌──────────────────────────────┐   ┌────────────────────────────┐         │
│  │  S3 BRONZE (immutable)        │   │  Governance OLTP register  │         │
│  │  Object Lock = COMPLIANCE     │   │  Postgres on:              │         │
│  │  Separate AWS account         │   │  • SAP BTP Kyma, OR         │         │
│  │  Append-only IAM              │   │  • Customer Postgres, OR    │         │
│  │  Parquet, OTel JSON spans     │   │  • DATAP.AI SaaS tenant     │         │
│  │  SHA-256 manifest sidecar     │   │                             │         │
│  │  Retention: 7y (configurable) │   │  Tables: ai_system,         │         │
│  └──────────┬────────────────────┘   │  accountable_person,        │         │
│             │                          │  risk_assessment, incident, │         │
│             │ dbt reads                │  human_oversight_event,     │         │
│             ▼                          │  policy_version...          │         │
│  ┌────────────────────────────────────┴────────────────────────┐            │
│  │  WAREHOUSE — Iceberg (silver/gold) on customer's own warehouse            │
│  │  Adapters: Snowflake / Databricks / BigQuery /                           │
│  │            SAP Datasphere / Postgres                                     │
│  │                                                                          │
│  │  Managed by dbt package `datapai_ai_governance`:                         │
│  │    dims (SCD2): dim_ai_system, dim_accountable_person,                   │
│  │                 dim_control, dim_policy_version, dim_jurisdiction,        │
│  │                 dim_framework, dim_model_provider, dim_dataset           │
│  │    facts: fact_ai_inference, fact_ai_debate_session,                     │
│  │           fact_ai_test_run, fact_ai_risk_assessment,                     │
│  │           fact_human_oversight_event, fact_ai_incident,                  │
│  │           fact_disclosure_event                                          │
│  │    bridges: bridge_control_framework, bridge_system_jurisdiction         │
│  │    seed files: ISO 42001 Annex A, NIST AI RMF, AU 6, UK 5,               │
│  │                Colorado AI Act, FINRA 24-09, FCA                         │
│  │    tests: governance assertions (point-in-time FK, required controls,    │
│  │           SLA compliance, SCD2 integrity)                                │
│  │    docs: auto-generated lineage graph (= Practice 4 artefact)            │
│  └─────────────────┬────────────────────────────────────────────┘           │
│                    │                                                         │
│                    ▼                                                         │
│  ┌────────────────────────────────────────────────────────────┐             │
│  │  Dashboard pack + Evidence generator                         │             │
│  │  • Governance dashboard (Streamlit / PowerBI / SAC template) │             │
│  │  • FinOps dashboard                                          │             │
│  │  • Shadow AI dashboard                                       │             │
│  │  • Quarterly evidence PDF generator                          │             │
│  └────────────────────────────────────────────────────────────┘             │
│                                                                              │
│  Orchestration options (customer choice):                                    │
│  • Airflow (default DATAP.AI, stock.datap.ai)                                │
│  • Control-M (BMC shops)                                                     │
│  • SAP BTP Job Scheduling Service (SAP shops)                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Key architectural decisions (locked)

| Decision | Locked outcome | Rationale |
|---|---|---|
| Analytical warehouse form | **Dim/fact with SCD2 + dbt package** | Kimball is right for SCD2 governance history; precedent in LangSmith, MLflow, dbt_artifacts |
| Immutability | **S3 Object Lock COMPLIANCE mode** on bronze, separate AWS account, append-only IAM | Iceberg alone is logically-but-not-physically immutable; auditors require WORM bytes |
| Query layer | **Iceberg** on mutable bucket, rebuildable from bronze | Open table format, time-travel, not warehouse-locked |
| Source of truth | **OLTP register in platform-be Postgres**, CDC to warehouse | Warehouse is analytical; registration/approval workflow stays OLTP |
| Instrumentation | **OTel GenAI semantic conventions** | Open standard; inherits OpenLIT, Langfuse, SAP AI Core, BMC HelixGPT, future tools |
| Control model | **ISO/IEC 42001 Annex A as internal canonical**, N:N bridge to AU/US/UK/sector frameworks | Multi-jurisdiction without schema churn; add EU AI Act = seed-data change |
| Primary channel | **BMC + SAP partner channel** | Concrete human relationship; regulated-industry overlap; gap in partner portfolios |
| First paid SKU | **Financial-services vertical pack** | Leverages stock.datap.ai domain credibility; highest willingness-to-pay |
| Virtual customer | **stock.datap.ai**; health.datap.ai second | Existing audit-trail foundation; finance is hardest regulated vertical |

### 3.2 Key architectural decisions (open)

| Open decision | Options | Decision trigger |
|---|---|---|
| CDC tooling | Debezium self-host / Fivetran / Airbyte | Partner DD: which does partner's customers already run? |
| Iceberg catalog | Snowflake-managed / AWS Glue / Apache Polaris | First paid customer's existing catalog |
| SaaS OLTP vs customer-hosted OLTP | Both, with customer choice | Sales feedback from first 3 POCs |
| Open-source-led vs closed SaaS | Hybrid: OSS dbt package + paid vertical packs + paid hosted service | Confirm with partner before Phase 2.2 |
| Compliance attestation roadmap | SOC 2 Type 1 → Type 2 → ISO 27001 → ISO 42001 self-certify | Partner tells us which their customers require |

---

## 4. Compliance framework coverage

All frameworks land as rows in `dim_control` + `bridge_control_framework`. Adding a new jurisdiction = `dbt seed` change, not code change.

| Framework | Jurisdiction | Version | Seed file |
|---|---|---|---|
| ISO/IEC 42001:2023 Annex A | International | 2023 | `seeds/frameworks/iso_42001_2023.csv` |
| NIST AI RMF 1.0 + Gen AI Profile | US | 2023, 2024-07 | `seeds/frameworks/nist_ai_rmf_10.csv`, `seeds/frameworks/nist_ai_600_1.csv` |
| Australia Guidance for AI Adoption — 6 Essential Practices | AU | 2025-10 | `seeds/frameworks/au_6_practices_2025.csv` |
| Australia Voluntary AI Safety Standard (legacy 10 guardrails) | AU | 2024-09 | `seeds/frameworks/au_vaiss_2024.csv` (for backwards compat) |
| UK AI White Paper 5 Principles + AISI | UK | 2023-2024 | `seeds/frameworks/uk_5_principles.csv` |
| Colorado AI Act (SB24-205) | US-CO | Effective 2026-02 | `seeds/frameworks/colorado_ai_act.csv` |
| FINRA Regulatory Notice 24-09 | US financial services | 2024 | `seeds/frameworks/finra_24_09.csv` |
| FCA DP5/22 + AI Update | UK financial services | 2022-2024 | `seeds/frameworks/fca_ai.csv` |
| SEC AI supervisory guidance | US securities | 2024-2025 | `seeds/frameworks/sec_ai.csv` |
| EU AI Act (prospective) | EU | 2025-2027 phased | `seeds/frameworks/eu_ai_act.csv` — stub for P2.3 |

`bridge_control_framework` handles the N:N. Every `dim_control` row answers one question from one framework; a single real-world control (e.g. "Responsible Party is identified for each AI system") maps to AU Practice 1 + NIST GOVERN-3 + ISO 42001 A.3.2 + FINRA 24-09 supervisory identifier simultaneously.

---

## 5. Phased roadmap — 12 weeks

Four-week phases, checkpoint at end of each. Phase 2.1 is the MVP for partner conversations; Phase 2.2 is the first integration; Phase 2.3 is a POC at a named customer.

### Phase 2.1 — Extend what exists, ship the first compliance PDF (Weeks 1–2)

**Scope change 2026-04-19 (v0.3):** original 4-week MVP reduced to ~2 weeks after inventorying existing `ai_mart` + guardrail framework + trace ledger + Control-M integration. The product already runs; we extend it with external compliance mappings, immutable bronze, OTel GenAI adapter, and evidence-generation.

**Goal:** real compliance PDF (AU 6 + FINRA) auto-generated from live stock.datap.ai trace data, using extended `ai_mart` + new immutable bronze + evidence generator.

**Exit criteria:**
- `dbt-demo/seeds/ai_mart/frameworks/` populated with ISO 42001, NIST AI RMF, AU 6, UK 5, Colorado AI Act, FINRA 24-09, FCA (7 seed files + citation manifest)
- `ai_mart` extended with `dim_framework`, `dim_jurisdiction`, `dim_control`, `bridge_control_framework`, `bridge_asset_framework`, `dim_ai_system`, `dim_accountable_person`, `fact_ai_risk_assessment`, `fact_ai_incident`, `fact_human_oversight_event`
- S3 Object Lock COMPLIANCE bucket provisioned; trace ledger writes dual-sink (Snowflake + S3 bronze)
- OTel GenAI adapter accepts OpenLIT / OTel-standard spans into the trace ledger
- Evidence generator renders AU 6 + FINRA PDF from live stock.datap.ai data
- Lightdash dashboards: Governance view first, FinOps + Shadow AI skeletons
- Customer install pack v0.1 — consolidates ship-with.md + Control-M README + dbt-demo setup + framework seed + Object Lock bronze into a single installable bundle

### Phase 2.2 — SAP integration + BMC connectors (Weeks 3–6)

**Scope change 2026-04-19 (v0.3):** shifted earlier (Weeks 3–6 instead of 5–8) because Phase 2.1 shortened. Control-M integration pack already exists; P2.2 adds *on top* of it: BMC HelixGPT + BMC Discovery connectors, SAP AI Core telemetry, SAP Datasphere adapter, SAP BTP Kyma deployment.

**TODO (scheduled for Week 3, ahead of BMC connectors) — TinyFish backend scan endpoint**

> Replaces the client-side `runMockScan()` stub in [`datapai-healthcare-fe/app/governance/scan/page.tsx`](../../../datapai-healthcare-fe/app/governance/scan/page.tsx) with a real server call. This is the first backend piece that activates the framework auto-refresh feature end-to-end — everything else in Workstream K depends on it.

- **Endpoints (live in `datapai-platform-be`):**
  - `POST /api/governance/scan/{framework_code}` → creates a run record, kicks off async scan, returns `{ run_id, started_at }`. Body optional `{ simulate_drift?: bool }` for dev.
  - `GET /api/governance/scan/{run_id}` → returns `{ status, stage, result?, error? }`. Polled by FE every 1-2s while `status == "running"`.
  - `POST /api/governance/scan/{run_id}/approve` → opens PR in `dbt-demo` with the diff applied to `seeds/ai_mart/frameworks/ai_controls_seed.csv`.
  - `POST /api/governance/scan/{run_id}/reject` → logs rejection to trace ledger; no seed change.

- **Inside the scan:**
  1. Look up framework row in `ai_controls_seed` (`source_url`, last known hash in `sys_common_config` key `ai_governance.framework_hash.<framework_code>`).
  2. Call TinyFish `/api/run`-equivalent (lift the generic kernel from `datapai-stock-fe/lib/scan-pipeline` into platform-be).
  3. Compute content SHA-256. Short-circuit if unchanged (update hash, return zero-diff result).
  4. If changed: invoke AI extractor with the framework-specific prompt at `dbt-demo/seeds/ai_mart/frameworks/extractors/<framework_code>.md` (only `AU_6_2025.md` exists today).
  5. Diff extracted rows vs current seed rows for this `framework_code`.
  6. Persist run record + diff to trace ledger + bronze S3 (Object Lock path `s3://datapai-ai-audit/ai_governance/seed_candidates/...`).
  7. Return `ScanResult` matching the FE TypeScript shape in `page.tsx` (`runId`, `completedAt`, `sourceSha256`, `rowsExtracted`, `rowsMatchingSeed`, `rowsWithChanges`, `changes[]`, `structuralFlags[]`).

- **Acceptance criteria:**
  - FE `runMockScan()` swapped for real `fetch()` with identical response shape — no FE refactor needed
  - `AU_6_2025` scan run end-to-end against the live industry.gov.au URL produces the golden-path zero-diff result (matches the test case in `extractors/AU_6_2025.md` §4)
  - Manually induced content change (local HTML fixture) produces a correct diff with before/after values populated
  - Approve path opens a real PR in `dbt-demo`; reviewer verdict recorded to trace ledger; hash updated in `sys_common_config`
  - Reject path records verdict to trace ledger; hash NOT updated (next scan re-detects)
  - No auto-merge under any code path

- **Out of scope for this task (deferred):**
  - Other 6 framework extractor prompts (clone from `AU_6_2025.md`)
  - Airflow weekly DAG (user-triggered scan only at first; scheduled scan is Phase 2.2 Week 4+)
  - stock-fe cross-app link
  - i18n for FE strings

---

**Weeks 3–4 — BMC connectors on top of existing Control-M pack**
- BMC HelixGPT / AIOps OTel connector — feeds HelixGPT LLM activity into existing trace ledger + new OTel adapter
- BMC Discovery connector — populates `dim_ai_system` from the customer's existing CMDB (auto-inventory of AI systems)
- BMC Helix SSO integration — platform-be auth layer accepts BMC Helix as an OIDC provider
- Smoke-test deploy against DATAP.AI-hosted BMC trial (or partner-sponsored env)

**Weeks 5–6 — SAP track**
- SAP AI Core + Joule OTel connector — feeds SAP-native LLM activity into trace ledger
- SAP Datasphere adapter added to `dbt-demo/profiles.yml` — `ai_mart` materialises into Datasphere as alternative to Snowflake
- SAP IAS / IPS SSO integration
- SAP BTP Kyma Helm manifest — platform-be OLTP state (policy catalog + governance register) deployable to SAP BTP
- Smoke-test deploy in SAP BTP trial subaccount
- Partner-certification paperwork submitted: SAP Store + BMC Helix Platform programs (in parallel where partner sponsorship allows)

**Exit criteria for Phase 2.2:**
- BMC HelixGPT + Discovery connectors working end-to-end
- SAP AI Core connector working end-to-end
- `ai_mart` materialises in Datasphere
- SAP BTP Kyma deployment runs the governance register
- Compliance evidence PDF generated from reference SAP data AND from reference BMC data — proving runtime-agnosticism
- SAP Store + BMC partner-cert paperwork in flight

### Phase 2.3 — Named-customer POC + security readiness (Weeks 9–12)

**Goal:** first real customer POC running, security review passed, SOC 2 Type 1 prep underway.

**Exit criteria:**
- Customer POC live in customer environment, generating real evidence PDFs
- Security questionnaire answered (SIG / CAIQ format)
- SOC 2 Type 1 audit scoped and started
- Customer signs paid conversion paperwork OR gives documented expansion path
- Second vertical internal activation: healthcare.datap.ai governance stack running
- Lessons-learned doc feeds Phase 3.0 plan

---

## 6. Workstream catalog

Ten parallel workstreams, owned independently. Phase 2.1 activates workstreams A–F + G. Phase 2.2 adds H (channel integration). Phase 2.3 adds I + J.

### A. Platform-be governance OLTP

- Schema migrations for `ai_system`, `accountable_person`, `responsible_party_assignment`, `risk_assessment`, `control_evidence`, `incident`, `human_oversight_event`, `disclosure_event`, `policy_version`, `supplier`, `dataset_registration`
- FastAPI CRUD endpoints with role-gated access (leverages existing `role_key` from 3c956c7)
- Alembic migration scaffolding (if not already — confirm)
- Event outbox table for CDC
- Integration with existing `governance-audit` primitive (e470a78)

### B. dbt package `datapai_ai_governance`

- Package skeleton with `dbt_project.yml`, sources, staging/intermediate/mart layers
- Adapter support: Postgres (dev), Snowflake, Databricks, BigQuery, SAP Datasphere
- Seed files for all compliance frameworks in §4
- Macros for SCD2 helpers, framework bridging, point-in-time joins
- dbt tests as governance assertions (list in §7)
- `dbt docs generate` output published as first-class artefact

### C. OTel GenAI collector bundle

- Base OTel collector config + pipelines
- OpenLIT input (stock.datap.ai native)
- Generic OTel GenAI input (any compliant source)
- SAP AI Core input connector (stub → activate P2.2)
- BMC HelixGPT input connector (stub → activate P2.2)
- Redaction/PII filter (configurable)
- Dual-sink: S3 bronze + Postgres outbox

### D. Bronze S3 WORM layer

- Terraform module for Object Lock Compliance bucket
- Separate AWS account scaffolding (may defer to P2.2)
- IAM append-only role definitions
- SHA-256 manifest sidecar tooling
- Retention policy: 7y default (configurable)
- CloudTrail + S3 Access Logs, also Object-Locked

### E. Silver/Gold Iceberg layer

- Iceberg catalog choice (deferred open decision)
- dbt materialisations targeting Iceberg
- Snowflake-managed Iceberg first (fast path)
- SAP Datasphere Iceberg target (P2.2)

### F. Dashboard pack

- Streamlit primary (Phase 2.1)
- Governance dashboard views: system inventory, control coverage, risk heatmap, incident timeline, evidence readiness scorecard
- FinOps dashboard views: cost by model/team/product, anomaly detection, projection
- Shadow AI dashboard views: discovered-system log, PII-in-prompt alerts, unapproved model usage
- Template exports: PowerBI pbit, Looker LookML snippets, SAP Analytics Cloud content (P2.2)

### G. Evidence generator + partner enablement

- Jinja2 PDF templates per framework (AU 6, FINRA, NIST, Colorado)
- Python renderer service with read-only warehouse access
- Partner 1-pager (1 page, no jargon)
- Partner 15-slide deck (problem, product, evidence, ROI, ask)
- Demo script (15-min)
- ROI calculator (Google Sheets + PDF export)
- FAQ (top 20 objections)

### H. Channel integration (SAP or BMC — decided end of Week 2)

See Phase 2.2 exit criteria for the two branches.

### I. Security + compliance readiness

- SIG / CAIQ questionnaire template filled
- Penetration test scoping
- SOC 2 Type 1 auditor selection (Vanta, Drata, Secureframe, or direct)
- Data classification + encryption-at-rest/in-transit documentation
- Subprocessor list

### K. TinyFish-powered framework auto-refresh (must-have product feature)

**Added 2026-04-19 per user directive: "a must have feature."**

Product differentiator: most AI governance tools ship static control libraries that drift stale as frameworks update. DATAP.AI auto-detects framework updates from canonical sources (industry.gov.au, nist.gov, iso.org, gov.uk, leg.colorado.gov, finra.org, fca.org.uk, eur-lex.europa.eu) and proposes diffs for human review — compliance team always sees the latest regulator content without manual tracking.

Reuses the existing TinyFish integration already wired into `datapai-stock-be` (per prior `/api/run` IR universe work). Applies AI web extraction to the regulatory domain.

**Flow:**

```
Weekly Airflow DAG (framework_seed_refresh_dag.py)
  │
  └── For each row in ai_controls_seed (DISTINCT framework_code):
        1. TinyFish run → fetch canonical source_url (HTML + PDF as needed)
        2. SHA-256 of fetched content → compare vs last-known hash in sys_common_config
        3. If hash unchanged → skip (fast path; most weeks)
        4. If hash changed:
             a. AI extraction (Gemini/Claude with framework-specific prompt) parses
                fetched content into the same 18-column schema as the seed
             b. Diff candidate rows vs current ai_controls_seed rows for
                this framework_code
             c. Write candidate rows + diff summary to:
                s3://datapai-ai-audit/ai_governance/seed_candidates/YYYY-MM-DD/<framework>/
             d. Open PR in dbt-demo with the candidate diff on a branch
                `governance/auto-refresh/<framework>-<date>`
             e. Notify #ai-governance channel (Slack/Teams via platform-be)
        5. Human reviews diff → merge if accepted; dbt seed refresh picks up on next run
        6. Update last-known hash in sys_common_config
            key: `ai_governance.framework_hash.<framework_code>` → hash + retrieved_date
```

**Invariants (non-negotiable):**

- **Never auto-merge.** Regulator-facing data lands only after human review. Reason: an incorrect extraction that auto-merges pollutes the compliance evidence.
- **Never mutate published rows.** If a framework publishes a new version, create a new `framework_code` (e.g. `AU_6_2027`) + new rows with new `effective_from`. Existing rows remain for historical audit queries.
- **Preserve the citation trail.** Every auto-refresh diff includes the SHA-256 of the source content, the retrieval timestamp, and the TinyFish run_id, so the evidence PDF can always point back to "on YYYY-MM-DD at HH:MM UTC, source X was SHA-256 Y, and that matched control row Z."
- **PR-first workflow.** Diffs never bypass git. This is both a review gate and an immutable change log.

**Component ownership:**
- Airflow DAG — `datapai-platform-be/dags/framework_seed_refresh_dag.py` (new, Phase 2.2)
- TinyFish extraction configs — `datapai-platform-be/governance/framework_extractors/` (new)
- Per-framework extraction prompts — `datapai-platform-be/governance/framework_extractors/prompts/<framework_code>.md`
- PR automation — `datapai-platform-be/governance/seed_diff_pr.py` (new)
- Slack/Teams notify — via existing platform-be notification service
- Hash state — `sys_common_config` (existing pattern, user's DB-driven-defaults rule)

**Sales-deck value prop (draft):**
> "DATAP.AI AI Governance is self-maintaining. Framework updates from AU, US, UK, EU regulators are auto-detected within 7 days of publication and surfaced as reviewable diffs. No more stale compliance mappings. No more 'we thought we were compliant with v1.0 but the regulator moved to v2.0 six months ago.'"

**Competitive read:** static control libraries are what every competitor ships. Credo AI, Holistic AI, Fiddler, IBM watsonx.governance — all manually refresh quarterly at best. Auto-refresh is a compounding moat because the number of frameworks is growing fast (EU AI Act phases 2025-27, more US states adopting sector AI laws, APAC region following AU's lead). Every new framework we add to auto-refresh widens the gap vs competitors who are still cutting PRs by hand.

### J. Documentation

- Architecture decision records (ADRs) — one per locked decision in §3.1
- Runbook for platform-be operators
- Customer install guide (this doubles as partner enablement)
- API reference (generated from FastAPI schemas)
- CHANGELOG entries in both platform-be and datapai-stock-be

---

## 7. Week-by-week deliverables (Phase 2.1 detail)

### Week 1 — Compliance framework seeds + immutable bronze + evidence skeleton

Build on existing `ai_mart` + trace ledger; do not duplicate. All work is draft-quality extension of draft-quality code — no prod-readiness claimed.

| Day | Workstream | Deliverable |
|---|---|---|
| D1 | J | ADR-001: extend existing `ai_mart` with external-framework bridge (no new warehouse). ADR-002: S3 Object Lock COMPLIANCE bronze chosen for immutability layer *under* trace ledger. ADR-003: OTel GenAI adapter feeds existing trace ledger (no new ledger). |
| D1 | B | `dbt-demo/seeds/ai_mart/frameworks/` folder + citation manifest + first seed: ISO 42001 Annex A (~38 controls) |
| D2 | B | Seed files: AU 6 Essential Practices (Oct 2025), NIST AI RMF 1.0, NIST AI 600-1 Gen AI Profile |
| D2 | B | Seed files: UK 5 Principles, Colorado AI Act, FINRA 24-09, FCA DP5/22 |
| D3 | B | `ai_mart` schema extension: `dim_framework`, `dim_jurisdiction`, `dim_control`, `bridge_control_framework` — dbt models + `schema.yml` tests |
| D3 | B | `ai_mart` schema extension: `dim_ai_system`, `dim_accountable_person`, `bridge_asset_framework` — extends existing `dim_ai_governed_assets` to cover AI-system-level (not just dbt-asset-level) governance |
| D4 | B | `fact_ai_risk_assessment`, `fact_ai_incident`, `fact_human_oversight_event` — staging + mart models; populated from trace ledger where available, null-seeded where not |
| D4 | D | S3 Object Lock COMPLIANCE bucket provisioned (Terraform) in existing DATAP.AI AWS account (approved §1 earlier). SHA-256 manifest sidecar tooling drafted. |
| D5 | C+D | Trace ledger dual-sink: existing `SnowflakeBackend` augmented with S3 bronze append-writer. Every trace event lands in both. |
| D5 | G | Evidence generator scaffold: Jinja2 templates for AU 6 + FINRA, Python renderer reading from extended `ai_mart` |

### Week 2 — OTel adapter, first real compliance PDF, dashboard extension

| Day | Workstream | Deliverable |
|---|---|---|
| D6 | C | OTel GenAI adapter — converts OTel-standard GenAI spans (OpenLIT input format) into trace ledger schema. Wire stock.datap.ai's existing OpenLIT output through it. |
| D6 | F | Lightdash governance dashboard — extends existing Lightdash connection with new `ai_mart` framework-coverage views |
| D7 | B | dbt tests as governance assertions (§8) on extended `ai_mart` — point-in-time FK, SCD2 integrity, required-control-coverage, framework-mandatory checks |
| D7 | G | **First real AU 6 + FINRA compliance PDF generated from live stock.datap.ai trace data** |
| D8 | A | `dim_ai_system` seeded with live stock.datap.ai AI systems (finance agents). Human-oversight events capture wired into stock-be chat flow. |
| D8 | F | Lightdash FinOps view (per-model/team/user spend from trace ledger + cost_guard data) |
| D9 | F | Lightdash Shadow AI view (inventory from `dim_ai_system` + unclassified systems detected via trace-ledger cross-ref) |
| D9 | G | Customer install pack v0.1 — consolidates ship-with.md + Control-M README + dbt-demo setup + framework seeds + Object Lock bronze + OTel adapter into a single install bundle |
| D10 | J | Phase 2.1 retrospective + Phase 2.2 kickoff plan (Weeks 3–6) |

### Weeks 3–6 (Phase 2.2) and Weeks 7–8 (Phase 2.3)

Outlined in §5. Detailed week-by-week deliverables will be added during the Week 2 retrospective based on Phase 2.1 actuals. Phase 2.3 compresses to Weeks 7–8: customer POC + SOC 2 Type 1 kickoff + draft-code hardening workstream activated.

---

## 8. Governance assertions (the dbt tests that matter)

These are not data-quality tests; they are **governance assertions** auditors will care about. Each one failing is a governance violation.

1. Every `fact_ai_inference` row joins to a `dim_ai_system` row **active at event_timestamp** (point-in-time SCD2 join).
2. Every `dim_ai_system` currently active has a non-null `accountable_person_sk` resolving to a currently active `dim_accountable_person`.
3. Every `dim_ai_system` currently active has a `fact_ai_risk_assessment` within the last `risk_review_interval_days` (configurable per jurisdiction).
4. No `fact_ai_inference` originates from a system whose `dim_ai_system.approval_status != 'approved'` at event_timestamp.
5. Every `fact_ai_incident` has a linked `fact_human_oversight_event` within the incident-response SLA.
6. Every `dim_ai_system` in a jurisdiction has at least one `bridge_control_framework` row mapping it to every mandatory framework for that jurisdiction.
7. No `fact_disclosure_event` is missing for systems that require end-user disclosure (AU Practice 4, Colorado AI Act §6-1-1705).
8. Every `fact_ai_test_run` for a high-risk system is within the mandated pre-deployment test window.
9. SCD2 integrity: every dim has exactly one `current = true` row per natural key; no overlapping validity periods.
10. Bronze `raw_sha256` in every gold fact row resolves to an actually existing S3 Object Lock-ed object.

---

## 9. Partner due-diligence — *intentionally descoped*

**Decision 2026-04-19 (v0.2):** explicitly do **not** gate Phase 2.x execution on partner due-diligence. Rationale (user directive): chicken-or-egg — no partner commits to vaporware, we don't build for aspirational channels. Asking partners to validate an unbuilt product wastes weeks for signals we cannot trust until something is demoable. **Build first. Demonstrate real value. Let the channel respond to evidence, not promises.**

Original DD questions retained below for later use — as conversation prompts *after* the Phase 2.1 partner demo, not before.

<details>
<summary>Archived: 7 partner-validation questions (use post-demo, not pre-build)</summary>

1. Which of your current BMC / SAP accounts would buy AI governance in the next 6 months? Please name 5.
2. Is this a resale motion or a co-sell-with-vendor motion?
3. What's the typical deal size and sales cycle for products you resell?
4. Do you have an SAP BTP practice or is it S/4HANA resale only?
5. BMC side — is your practice BMC Helix (cloud/SaaS) or TrueSight (on-prem)?
6. What AI-governance or AI-observability products have you tried to sell before? What worked, what didn't?
7. Would you co-invest in a POC with a named account in Phase 2.3 (Weeks 9–12)?

</details>

---

## 10. Risks and mitigations

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| **Partner cannot actually sell** — channel is aspirational, not real | Phase 2.3 POC lands late or not at all; revenue path delayed | Medium | Accepted risk per user directive 2026-04-19 (velocity > validation). Mitigated by ensuring the product stands alone: even without the friend-partner channel, it's listable on SAP Store / BMC Platform program and sellable direct. |
| **Both-tracks-parallel (SAP + Control-M) over-scopes Phase 2.2** | P2.2 slips; neither ships polished | High | Narrow-before-broad sequencing: Weeks 5-6 = Control-M job bundle (small surface), Weeks 7-8 = SAP BTP + Datasphere (larger). Ship Control-M polished even if SAP slips into P2.3. |
| **Scope creep into all three wedges at once** | Ship mediocre at three instead of great at one | High | Phase 2.1 covers governance dashboard only; FinOps + Shadow AI are visible placeholder Streamlit pages, not fully productised until P3 |
| **Stock.datap.ai regressions from instrumentation load** | Virtual-customer workload degrades | Low | OTel collector sidecar only; no in-process hooks; feature-flag the dual-write |
| **Multi-warehouse dbt adapter bugs** | Snowflake ships, SAP Datasphere broken at demo | Medium | Phase 2.1 targets Postgres + Snowflake only; SAP Datasphere defers to P2.2 where it matters |
| **Compliance framework interpretation disputes** | Evidence PDF gets rejected by first auditor | Medium | Seed files carry explicit source citation (URL + version + retrieved date); evidence PDF includes interpretation notes |
| **SAP / BMC certification timelines (3-9 months)** | Product ready but cannot list on marketplace | Medium | Kick off certification paperwork in Week 1 via partner sponsorship; treat as parallel track, not blocking |
| **Team bandwidth** (founder-CTO + small team, also running stock-be) | Phase slips | High | Phase 2.1 is deliberately scoped to stock-be-only target; no new vertical in P2.1 |
| **Customer requires on-prem air-gapped deploy** | DATAP.AI SaaS OLTP option doesn't fit | Medium | OLTP service designed stateless-where-possible + containerised; deploy into customer VPC from day 1 as default |
| **S3 Object Lock migration burden if we start in wrong AWS account** | Bronze history cannot be moved without breaking immutability chain | Low | Provision correct account from Week 1; if deferred, document the migration-impossibility clearly |
| **Regulatory landscape changes mid-build** (new AU mandatory guardrails, EU AI Act phase shift) | Seed files become incorrect | Low | Versioned seeds per framework with `effective_from_date`; add new version rather than mutate |

---

## 11. Success criteria

### Phase 2.1 (Week 4)

- [ ] End-to-end stack running against live stock.datap.ai AI traffic
- [ ] AU 6 + FINRA compliance PDF auto-generated from real data, reviewed by at least one external compliance advisor
- [ ] Partner demo delivered (or firmly scheduled)
- [ ] Phase 2.2 both-tracks skeleton committed (Control-M bundle stub + SAP BTP manifest stub)
- [ ] All §8 governance assertions implemented as dbt tests and passing

### Phase 2.2 (Week 8)

- [ ] First-channel-target (SAP BTP or BMC Helix) deployment manifest validated in a reference environment
- [ ] Partner-certification paperwork in flight
- [ ] Second compliance PDF template (NIST or Colorado) generated
- [ ] Security questionnaire + SIG / CAIQ draft complete

### Phase 2.3 (Week 12)

- [ ] POC live in one customer environment, generating weekly evidence
- [ ] Signed POC-to-paid conversion paperwork, OR documented path-to-conversion with timeline
- [ ] Healthcare vertical internal activation (health.datap.ai governance stack running)
- [ ] Phase 3.0 plan drafted, lessons-learned incorporated

---

## 12. Review cadence

- **Weekly**: Friday 30-min review against that week's deliverable table; update this doc inline with status, slippage, re-scoping
- **End of each phase**: retrospective + next-phase plan enhancement, committed to git
- **End of Phase 2.3**: full strategy refresh; this doc archived as-of date, successor doc opens Phase 3.0

---

## 13. Appendix A — Artefacts to be produced (reviewable checklist)

Code / config:
- [ ] `datapai-platform-be/migrations/` — governance OLTP schema
- [ ] `datapai_ai_governance/` — new dbt package (repo TBD)
- [ ] `datapai-infra/otel-collector-genai/` — collector bundle
- [ ] `datapai-infra/terraform/s3-bronze-worm/` — Object Lock module
- [ ] `datapai-infra/helm/platform-be-governance/` — OLTP register Helm chart
- [ ] `datapai-infra/controlm/` — Control-M job bundle (Phase 2.2, branch B)
- [ ] `datapai-infra/sap-btp/` — SAP BTP manifest (Phase 2.2, branch A)
- [ ] `datapai-streamlit/governance/` — dashboard pack

Docs (most produced in this repo or mirrored):
- [ ] `docs/architecture/ai-governance-warehouse.md` — detailed schema + decisions
- [ ] `docs/architecture/bronze-worm-immutability.md` — S3 Object Lock pattern
- [ ] `docs/architecture/otel-genai-ingest.md` — collector pattern
- [ ] `docs/strategy/<YYYY-MM-DD>-phase-2.1-retrospective.md` (end Week 4)
- [ ] `docs/strategy/<YYYY-MM-DD>-phase-2.2-retrospective.md` (end Week 8)
- [ ] `docs/strategy/<YYYY-MM-DD>-phase-2.3-retrospective.md` (end Week 12)
- [ ] `docs/operator-runbook.md` — new AI governance section
- [ ] ADRs: ADR-001 through ADR-00N in `docs/adr/`

Partner enablement (likely in `datapai-homepage` or a new `datapai-partners` repo):
- [ ] 1-pager PDF
- [ ] 15-slide deck
- [ ] Demo script
- [ ] ROI calculator
- [ ] FAQ / objection handler

Compliance framework seed files (per §4):
- [ ] 10 CSV seed files + 10 citation files (source URL, version, retrieval date)

---

## 14. Appendix B — Standing rules this plan inherits

From `~/.claude/CLAUDE.md` (global) and project memory:

- **Document every major change in git before moving on** — each phase retrospective is non-negotiable
- **DB-driven defaults** — no hardcoded plan/limit/enum; all compliance-framework data is seed-driven
- **Airflow only — no crontab** — unless the customer runs Control-M, in which case Control-M is the *customer's* choice for ingest; DATAP.AI-side orchestration stays Airflow
- **Never modify `.env.dev` or secrets without backup**
- **Never `rsync --delete` to EC2** — deploy scripts additive-only
- **Always check git status after changes** before committing
- **Autonomous execution authorised** for local changes and commits under an approved plan; still confirm for `git push`, prod deploys, destructive shared-state ops
- **AI Governance — No Black Box** (Phase 1.13 standing rule) — every AI conversation persisted hot+cold; now extended as the product thesis itself

---

---

## 15. Changelog

- **v0.3 — 2026-04-19 (same day)** — Ground-truth correction after inventorying existing `datapai-platform-be` + `dbt-demo` + `integrations/control_m`. New §0.5 "Starting line" documents what's already in-tree (Guardrail v1.4, trace ledger, Control-M pack, `ai_mart` dim/fact layer, Snowflake + Lightdash connected). Further clarified by user: existing code is *early stage, not tested, a lot of rework expected* — treat as prior art, not foundation. Phase 2.1 scope refocused from "build MVP" to "extend existing `ai_mart` with external compliance frameworks + S3 Object Lock bronze + OTel GenAI adapter + evidence generator." Phase 2.1 compressed from 4 weeks to 2 weeks (aspirational; rework may expand). Phase 2.2 shifted to Weeks 3–6. Phase 2.3 compresses to Weeks 7–8. Week 1–2 deliverables in §7 rewritten to reflect new scope. ADRs renumbered to reference existing modules. Customer install pack v0.1 listed as P2.1 W2 deliverable.
- **v0.2 — 2026-04-19** — User directive: skip partner DD, build first. Phase 2.2 restructured from SAP-or-BMC branch decision into both-tracks-parallel. Partner-DD questionnaire descoped in §9.
- **v0.1 — 2026-04-19** — Initial plan.

---

*Phase 2.0 plan v0.3 — 2026-04-19. Next review: 2026-04-24 (Friday Week 1 checkpoint).*
