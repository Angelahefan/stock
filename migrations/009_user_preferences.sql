-- ═══════════════════════════════════════════════════════════════════════════
-- 009_user_preferences.sql — Extracted user preferences from chat history
-- ═══════════════════════════════════════════════════════════════════════════
-- Stores key facts the user has told the copilot so it remembers across sessions.
-- Updated automatically after each chat turn by extracting preferences from user messages.

CREATE TABLE IF NOT EXISTS datapai.user_preferences (
    user_id        TEXT        NOT NULL,
    pref_key       TEXT        NOT NULL,   -- e.g. 'risk_tolerance', 'favourite_stock', 'investment_horizon'
    pref_value     TEXT        NOT NULL,   -- e.g. 'aggressive', 'NVDA', '2+ years'
    source_message TEXT,                   -- the user message this was extracted from
    confidence     REAL        DEFAULT 1.0,
    created_at     TIMESTAMPTZ DEFAULT now(),
    updated_at     TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT user_preferences_pkey PRIMARY KEY (user_id, pref_key)
);

CREATE INDEX IF NOT EXISTS idx_user_prefs_user ON datapai.user_preferences (user_id);

-- Known preference keys:
-- risk_tolerance: conservative / moderate / aggressive / speculative
-- investment_horizon: short / medium / long
-- favourite_stocks: comma-separated tickers
-- sectors_interested: comma-separated sectors
-- sectors_avoid: comma-separated sectors
-- trading_style: day_trader / swing / position / buy_and_hold
-- portfolio_focus: growth / value / income / balanced
-- budget_range: e.g. "10k-50k AUD"
-- country: AU / US / etc
-- language: en / zh
-- custom notes: free text
