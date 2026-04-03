-- 028_early_supporter_badge.sql
-- Add Early Supporter badge system to datapai.users
-- First 1,000 users get badge='early_supporter' with badge_number = signup order

BEGIN;

-- 1. Add badge columns
ALTER TABLE datapai.users
  ADD COLUMN IF NOT EXISTS badge TEXT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS badge_number INT DEFAULT NULL;

-- 2. Assign badge to ALL existing users (ordered by signup)
WITH numbered AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY created_at ASC) AS rn
  FROM datapai.users
)
UPDATE datapai.users u
SET badge = 'early_supporter',
    badge_number = n.rn
FROM numbered n
WHERE u.id = n.id
  AND n.rn <= 1000;

COMMIT;
