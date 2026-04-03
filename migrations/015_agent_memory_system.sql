-- Migration 015: Agent Memory System
-- Date: 2026-03-25
-- Purpose: DB-driven agent memory for BM25 retrieval, debate logging, and curated best results
-- Inspired by TradingAgents (TauricResearch) BM25 memory + reflection pattern
-- Key principle: Postgres is truth, BM25 is runtime cache

-- 1. Raw agent memory — situation→recommendation pairs
-- Backing store for BM25 index. Each agent role has its own memory corpus.
CREATE TABLE IF NOT EXISTS datapai.sys_agent_memory (
    id              SERIAL PRIMARY KEY,
    agent_role      VARCHAR(30) NOT NULL,
    -- 'bull', 'bear', 'risk_manager', 'portfolio_manager', 'exit_agent', 'signal_classifier'
    ticker          VARCHAR(20),          -- NULL for general lessons
    exchange        VARCHAR(10),          -- NULL for general lessons
    situation_text  TEXT NOT NULL,         -- market context description
    recommendation  TEXT NOT NULL,         -- what agent decided / should have decided
    outcome         VARCHAR(20) DEFAULT 'PENDING',
    -- 'CORRECT', 'WRONG', 'PARTIAL', 'PENDING'
    outcome_detail  TEXT,                 -- e.g. "held 30 more days, +12% recovery"
    confidence      DOUBLE PRECISION,     -- 0.0-1.0 how confident the memory is
    source          VARCHAR(30) NOT NULL DEFAULT 'reflection',
    -- 'reflection' (post-trade), 'backtest' (learning_agent), 'manual' (human), 'debate' (from synthesis)
    tags            TEXT[] DEFAULT '{}',  -- ['regime:BULL', 'quality:A', 'sector:TECH']
    is_active       BOOLEAN DEFAULT TRUE, -- soft-delete stale memories
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_memory_role ON datapai.sys_agent_memory(agent_role);
CREATE INDEX IF NOT EXISTS idx_agent_memory_ticker ON datapai.sys_agent_memory(ticker, exchange);
CREATE INDEX IF NOT EXISTS idx_agent_memory_source ON datapai.sys_agent_memory(source);
CREATE INDEX IF NOT EXISTS idx_agent_memory_outcome ON datapai.sys_agent_memory(outcome);
CREATE INDEX IF NOT EXISTS idx_agent_memory_tags ON datapai.sys_agent_memory USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_agent_memory_active ON datapai.sys_agent_memory(is_active, agent_role);

COMMENT ON TABLE datapai.sys_agent_memory IS 'Raw agent memory: situation→recommendation pairs for BM25 retrieval';


-- 2. Curated best-learned results — validated, high-value lessons
-- Promoted from sys_agent_memory when a pattern has enough evidence and high success rate.
CREATE TABLE IF NOT EXISTS datapai.sys_agent_results (
    id              SERIAL PRIMARY KEY,
    result_key      VARCHAR(100) NOT NULL UNIQUE,
    -- e.g. 'bull/regime:BULL/signal:TONE_SOFTENING', 'exit/regime:BEAR/quality:D'
    agent_role      VARCHAR(30) NOT NULL,
    category        VARCHAR(30) NOT NULL,
    -- 'debate_lesson', 'exit_rule', 'signal_weight', 'regime_insight', 'sector_pattern'
    title           VARCHAR(200) NOT NULL,
    lesson_text     TEXT NOT NULL,
    evidence_count  INTEGER DEFAULT 1,
    -- how many raw memories support this lesson
    success_rate    DOUBLE PRECISION,
    -- when this lesson was applied, what % of outcomes were correct
    applicable_when JSONB DEFAULT '{}',
    -- conditions: {"regime": ["BULL_MOMENTUM"], "quality": ["A","B"], "signal_type": ["TONE_SOFTENING"]}
    priority        INTEGER DEFAULT 50,
    -- 1-100, higher = more important. Top lessons injected first into prompts.
    is_active       BOOLEAN DEFAULT TRUE,
    last_validated  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_results_role ON datapai.sys_agent_results(agent_role);
CREATE INDEX IF NOT EXISTS idx_agent_results_category ON datapai.sys_agent_results(category);
CREATE INDEX IF NOT EXISTS idx_agent_results_priority ON datapai.sys_agent_results(priority DESC);
CREATE INDEX IF NOT EXISTS idx_agent_results_applicable ON datapai.sys_agent_results USING GIN(applicable_when);

COMMENT ON TABLE datapai.sys_agent_results IS 'Curated best-learned results — validated high-value lessons promoted from raw memory';


-- 3. Full debate transcript log — every synthesis debate stored for review and reflection
CREATE TABLE IF NOT EXISTS datapai.sys_agent_debate_log (
    id              SERIAL PRIMARY KEY,
    ticker          VARCHAR(20) NOT NULL,
    exchange        VARCHAR(10) NOT NULL,
    debate_date     DATE NOT NULL,
    debate_type     VARCHAR(20) NOT NULL DEFAULT 'synthesis',
    -- 'synthesis', 'exit_review', 'risk_assessment'

    -- Input signals that fed the debate
    input_signals   JSONB NOT NULL,

    -- Debate transcript
    bull_arguments  TEXT[],
    bear_arguments  TEXT[],
    risk_arguments  TEXT[],
    pm_arguments    TEXT[],

    -- Outcome
    direction       VARCHAR(20) NOT NULL,
    confidence      DOUBLE PRECISION,
    thesis          TEXT,
    recommendation  TEXT,

    -- Debate metadata
    regime          VARCHAR(30),
    quality_tier    VARCHAR(5),
    conflict_level  DOUBLE PRECISION,
    agent_scores    JSONB DEFAULT '{}',

    -- Post-hoc evaluation (filled by reflection, NULL until evaluated)
    actual_return_7d   DOUBLE PRECISION,
    actual_return_30d  DOUBLE PRECISION,
    actual_return_90d  DOUBLE PRECISION,
    was_correct        BOOLEAN,

    -- Lessons extracted (filled by reflection)
    lessons_extracted  TEXT[],

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_debate_log_ticker ON datapai.sys_agent_debate_log(ticker, exchange);
CREATE INDEX IF NOT EXISTS idx_debate_log_date ON datapai.sys_agent_debate_log(debate_date DESC);
CREATE INDEX IF NOT EXISTS idx_debate_log_direction ON datapai.sys_agent_debate_log(direction);
CREATE INDEX IF NOT EXISTS idx_debate_log_pending ON datapai.sys_agent_debate_log(was_correct) WHERE was_correct IS NULL;

COMMENT ON TABLE datapai.sys_agent_debate_log IS 'Full debate transcripts with post-hoc actual returns for reflection';
