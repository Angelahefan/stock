-- fct_ai_guardrail_decision — per-turn governance audit evidence.
--
-- Target DB: datapai_auth_db (framework_db, port 5433) — co-located with
-- datapai.dim_ai_control so auditors can join decisions→controls without
-- cross-DB hops.
--
-- Grain: one row per gate invocation (one per chat turn).
-- Retention: indefinite. Write-once, never update.
-- Hash pattern: user_prompt_sha256 + user_prompt_length so we can prove
-- "this exact prompt was evaluated" without storing PII plaintext.

CREATE TABLE IF NOT EXISTS datapai.fct_ai_guardrail_decision (
    decision_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ts                    timestamptz NOT NULL DEFAULT now(),
    session_id            text,
    user_id               text,
    domain                text NOT NULL,                 -- stock / healthcare / platform
    ticker                text,                          -- optional domain-specific context
    exchange              text,

    -- prompt evidence (PII-safe)
    user_prompt_sha256    text NOT NULL,
    user_prompt_length    integer NOT NULL,
    user_prompt_preview   text,                          -- first 200 chars, NULL if classifier flagged PII

    -- gate decision
    verdict               text NOT NULL,                 -- allow / allow_with_conditions / block / escalate
    blocked               boolean NOT NULL,
    risk_tier             text NOT NULL,                 -- low / medium / high / critical
    classification        text NOT NULL,                 -- info_request / tool_call / data_write / advice / external_fetch / multi_agent
    conditions            jsonb NOT NULL DEFAULT '[]',

    -- cited controls (denormalised snapshot — joins to dim_ai_control via
    -- control_nk, but also carried inline so audit evidence survives even
    -- if the catalog is re-seeded)
    cited_control_nks     jsonb NOT NULL DEFAULT '[]',
    cited_frameworks      jsonb NOT NULL DEFAULT '[]',
    cited_count           integer NOT NULL DEFAULT 0,

    reason                text,
    gate_latency_ms       integer,
    gate_model_hint       text,                          -- e.g. openai / bedrock / gemini

    -- full raw decision for forensic replay
    raw_gate_json         jsonb
);

CREATE INDEX IF NOT EXISTS idx_guardrail_decision_ts
    ON datapai.fct_ai_guardrail_decision (ts DESC);
CREATE INDEX IF NOT EXISTS idx_guardrail_decision_session
    ON datapai.fct_ai_guardrail_decision (session_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_guardrail_decision_user
    ON datapai.fct_ai_guardrail_decision (user_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_guardrail_decision_blocked
    ON datapai.fct_ai_guardrail_decision (blocked, ts DESC)
    WHERE blocked = true;
CREATE INDEX IF NOT EXISTS idx_guardrail_decision_verdict
    ON datapai.fct_ai_guardrail_decision (verdict, ts DESC);
-- GIN index for "show me every decision citing APRA_AI_2025.CPS230.*"
CREATE INDEX IF NOT EXISTS idx_guardrail_decision_cited_nks_gin
    ON datapai.fct_ai_guardrail_decision USING gin (cited_control_nks jsonb_path_ops);

COMMENT ON TABLE datapai.fct_ai_guardrail_decision IS
    'Per-turn AI governance gate decision. Write-once audit evidence. '
    'Join cited_control_nks[*] ↔ datapai.dim_ai_control.control_nk for '
    'point-in-time policy reconstruction (dim is SCD2).';

-- Verification
-- SELECT count(*), count(*) FILTER (WHERE blocked) AS blocks,
--        min(ts), max(ts)
-- FROM datapai.fct_ai_guardrail_decision;
