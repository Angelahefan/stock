-- ─────────────────────────────────────────────────────────────────────────────
-- 2026-04-18_stock_agent_roles.sql
-- Seed stock-domain agent roles into datapai.sys_agent_roles (platform table).
--
-- Depends on platform migration 2026-04-18_sys_agent_roles.sql which creates
-- the sys_agent_roles table + generic roles.
--
-- Each role has a role_key of form 'stock.<name>'. Apps reference roles by
-- the (domain, role_key) composite — the `id` is an internal FK.
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO datapai.sys_agent_roles (role_key, domain, display_name, role_description, tags)
VALUES
    ('stock.technical',      'stock', 'Technical Analyst',      'Scores based on technical indicators (RSI/MACD/BB/etc.)', '{"debate","ta"}'),
    ('stock.fundamental',    'stock', 'Fundamental Analyst',    'Scores based on valuation / quality / growth',            '{"debate","fa"}'),
    ('stock.sentiment',      'stock', 'Sentiment Analyst',      'Scores based on news + market sentiment',                 '{"debate","sentiment"}'),
    ('stock.macro',          'stock', 'Macro / Regime Analyst', 'Scores based on regime + macro signals',                  '{"debate","macro"}'),
    ('stock.bull',           'stock', 'Bull-side Advocate',     'Argues the bullish case in debate',                       '{"debate","advocate"}'),
    ('stock.bear',           'stock', 'Bear-side Advocate',     'Argues the bearish case in debate',                       '{"debate","advocate"}'),
    ('stock.risk_agent',     'stock', 'Risk Agent',             'Entry risk + position sizing assessment',                 '{"risk"}'),
    ('stock.exit_agent',     'stock', 'Exit Agent',             'Stop-loss / take-profit thresholds',                      '{"exit"}'),
    ('stock.synthesis',      'stock', 'Investment Committee',   'Final debate consensus + thesis writer',                  '{"synthesis","debate"}'),
    ('stock.reflector',      'stock', 'Stock Reflector',        'Reflects on closed trades, writes lessons',               '{"reflection","learning"}')
ON CONFLICT (domain, role_key) DO NOTHING;

-- ── Backfill existing sys_agent_memory rows with agent_role_id ────────────────
-- Match by existing agent_role string -> 'stock.<agent_role>' role_key.
UPDATE datapai.sys_agent_memory m
SET agent_role_id = r.id
FROM datapai.sys_agent_roles r
WHERE r.domain = 'stock'
  AND r.role_key = 'stock.' || m.agent_role
  AND m.agent_role_id IS NULL;

-- Verify:
--   SELECT role_key, display_name FROM datapai.sys_agent_roles WHERE domain = 'stock' ORDER BY role_key;
--   SELECT m.agent_role, r.role_key FROM datapai.sys_agent_memory m
--     LEFT JOIN datapai.sys_agent_roles r ON r.id = m.agent_role_id LIMIT 5;
