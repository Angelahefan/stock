-- 012_ticker_universe_featured.sql
-- Add featured stock support to ticker_universe
-- Featured stocks appear first on market grid pages

BEGIN;

ALTER TABLE datapai.ticker_universe ADD COLUMN IF NOT EXISTS is_featured BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE datapai.ticker_universe ADD COLUMN IF NOT EXISTS featured_order INT NOT NULL DEFAULT 9999;
CREATE INDEX IF NOT EXISTS idx_ticker_universe_featured ON datapai.ticker_universe (exchange, is_featured, featured_order) WHERE is_active = TRUE;

-- ── US Blue Chips (20) ──
UPDATE datapai.ticker_universe SET is_featured=TRUE, featured_order=n.ord
FROM (VALUES
  ('NVDA',1),('AAPL',2),('MSFT',3),('GOOGL',4),('AMZN',5),('META',6),('TSLA',7),('AMD',8),('ACMR',9),('SMCI',10),
  ('INTC',11),('CRM',12),('PLTR',13),('SNOW',14),('PRTS',15),('ZS',16),('CRWD',17),('NET',18),('DDOG',19),('PANW',20)
) AS n(tk, ord)
WHERE ticker=n.tk AND exchange='US';

-- ── ASX Blue Chips (18) ──
UPDATE datapai.ticker_universe SET is_featured=TRUE, featured_order=n.ord
FROM (VALUES
  ('BHP',1),('CBA',2),('CSL',3),('NAB',4),('ANZ',5),('WBC',6),('WES',7),('MQG',8),('TLS',9),
  ('WOW',10),('RIO',11),('FMG',12),('TWE',13),('GMG',14),('STO',15),('ORG',16),('WDS',17),('QAN',18)
) AS n(tk, ord)
WHERE ticker=n.tk AND exchange='ASX';

-- ── HOSE Blue Chips (20) ──
UPDATE datapai.ticker_universe SET is_featured=TRUE, featured_order=n.ord
FROM (VALUES
  ('VIC',1),('VCB',2),('VHM',3),('VNM',4),('HPG',5),('FPT',6),('MWG',7),('MSN',8),('TCB',9),('MBB',10),
  ('ACB',11),('STB',12),('SSI',13),('VPB',14),('GAS',15),('PLX',16),('SAB',17),('BVH',18),('REE',19),('PNJ',20)
) AS n(tk, ord)
WHERE ticker=n.tk AND exchange='HOSE';

COMMIT;
