# Operator Runbook — DB-driven business changes

> **Purpose**: When you need to change business behavior (limits, plans, channels, mappings), **do not edit code**. The system is DB-driven by design. This runbook lists every business action and the exact SQL to run.
>
> **Audience**: Donny, future teammates, on-call engineers. Keep this short and scannable.
>
> **Principle**: Any change in this runbook is done by updating a row in `datapai.sys_common_config` or a similar config table. The next scheduled run of the affected service picks it up automatically. **No code deploy, no service restart, no pager.**

---

## Connect to the config DB first

```bash
ssh ec2  # i.e. ssh -i ~/.ssh/Linux-CodeCambat.pem ec2-user@platform.datap.ai
docker exec -it datapai_framework_db psql -U postgres -d datapai_auth_db
```

All business config tables live in `datapai_framework_db` on port 5433, schema `datapai`. Connect via `docker exec -it datapai_framework_db psql -U postgres -d datapai_auth_db`.

**Safety: check the rows before you UPDATE.** Every config update below includes a `SELECT` first.

---

## Push notifications — change daily limit per plan

**Who this affects**: Mobile app users receiving signal alerts via Expo Push.
**When it takes effect**: Next `send_alerts.py` run (every 30 min during market hours).
**Cost impact**: None — Expo push is free at every volume.

### See current limits

```sql
SELECT config_key, config_value, description
FROM datapai.sys_common_config
WHERE config_type = 'push_limits'
ORDER BY config_key;
```

### Change one plan's limit

```sql
UPDATE datapai.sys_common_config
SET config_value = '10', updated_at = NOW()
WHERE config_type = 'push_limits'
  AND config_key  = 'watch_daily_limit';   -- or individual_daily_limit, etc.
```

Valid keys: `watch_daily_limit`, `individual_daily_limit`, `professional_daily_limit`, `business_daily_limit`, `default_daily_limit` (fallback for unknown plans).

### Add a new plan's limit

If you just added a new plan to `sys_pricing_tiers` (e.g. `enterprise_plus`):

```sql
INSERT INTO datapai.sys_common_config (config_type, config_key, config_value, description, created_by)
VALUES ('push_limits', 'enterprise_plus_daily_limit', '200', 'Enterprise+ plan', 'donny');
```

---

## Telegram notifications — per-user max_daily + opt-in

**Who this affects**: Users with Telegram chat_id linked.
**Where the config lives**: `datapai.usr_notification_prefs` (one row per user per channel, NOT in sys_common_config — because Telegram is opt-in and per-user).
**When it takes effect**: Next `send_alerts.py` run.

### See a user's Telegram prefs

```sql
SELECT user_id, channel, enabled, telegram_chat_id, alert_signal, max_daily, lang
FROM datapai.usr_notification_prefs
WHERE channel = 'telegram';
```

### Change a user's daily Telegram limit

```sql
UPDATE datapai.usr_notification_prefs
SET max_daily = 3, updated_at = NOW()
WHERE user_id = '9974f810-2256-4f65-82d0-6639c3fd6124'   -- donny's stock.users.id
  AND channel  = 'telegram';
```

### Temporarily disable a user's Telegram alerts (without removing the chat_id)

```sql
UPDATE datapai.usr_notification_prefs
SET enabled = FALSE
WHERE user_id = '9974f810-...' AND channel = 'telegram';
```

### Re-enable

```sql
UPDATE datapai.usr_notification_prefs
SET enabled = TRUE
WHERE user_id = '9974f810-...' AND channel = 'telegram';
```

---

## Add or rename a subscription plan

**Affects**: Twenty CRM `stockClient.subscriptionPlan` field, `sys_pricing_tiers`, push limits config, chat limits config (existing).
**Two-step process**:

### Step 1: add the plan to `sys_pricing_tiers`

```sql
-- One row per region (en, vi, th, ms, zh) — repeat for each region
INSERT INTO datapai.sys_pricing_tiers
  (tier_id, region, currency, currency_symbol, monthly_price, annual_price, trial_days, is_active)
VALUES
  ('enterprise_plus', 'en', 'AUD', '$', 2999.00, 29990.00, 30, TRUE),
  ('enterprise_plus', 'vi', 'VND', '₫', 59990000.00, 599000000.00, 30, TRUE),
  -- ... other regions
;
```

### Step 2: add the plan option to Twenty

Two options — pick one:

**Option A (recommended): via the Twenty web UI at `https://crm-stock.datap.ai`**
1. Log in as `donny@datap.ai`
2. Go to **Settings → Data model → Stock Clients → subscriptionPlan**
3. Click **Add option** → Label = `Enterprise Plus`, Value = `ENTERPRISE_PLUS` (**MUST be UPPER_SNAKE_CASE**), pick a color, Save.
4. Done. Next `stock_crm_client_sync` run automatically picks it up — no code changes.

**Option B: via the metadata API (for scripted environments)**
See `/tmp/fix_twenty_plan_enum.py` on EC2 as a reference for the `updateOneField` mutation pattern. Not usually needed for occasional manual plan additions.

### Step 3 (optional but recommended): add the plan's push daily limit

```sql
INSERT INTO datapai.sys_common_config (config_type, config_key, config_value, description, created_by)
VALUES ('push_limits', 'enterprise_plus_daily_limit', '200', 'Enterprise Plus daily push cap', 'donny');
```

Without this, the plan falls back to `default_daily_limit` (5/day) — the conservative safety net.

### Verify

```sql
-- sys_pricing_tiers
SELECT tier_id, region, monthly_price FROM datapai.sys_pricing_tiers WHERE tier_id = 'enterprise_plus';

-- push_limits
SELECT * FROM datapai.sys_common_config WHERE config_type = 'push_limits' AND config_key LIKE '%enterprise_plus%';

-- Twenty option (via dry-run of sync script)
ssh ec2 /home/ec2-user/git/datapai-stock-be/scripts/run_stock_crm_client_sync.sh --dry-run 2>&1 | grep subscriptionPlan
```

---

## Add or remove a stock exchange

**Affects**: Twenty CRM `stockClient.preferredMarkets` MULTI_SELECT options, exchange aliases in `sys_common_config`.

### Step 1: add the option in Twenty

Twenty UI → **Settings → Data model → Stock Clients → preferredMarkets** → Add option → Label = `Singapore Exchange`, Value = `SGX` (uppercase), Save.

### Step 2: add normalization aliases if your source data uses different names

For example, if `datapai.watchlist.exchange` ever contains `'SGX_MAIN'` or `'SES'` (the old Stock Exchange of Singapore name), add aliases:

```sql
INSERT INTO datapai.sys_common_config (config_type, config_key, config_value, description, created_by)
VALUES
  ('exchange_aliases', 'SGX_MAIN', 'SGX', 'Legacy SGX_MAIN → SGX', 'donny'),
  ('exchange_aliases', 'SES',      'SGX', 'Old Stock Exchange of Singapore → SGX', 'donny');
```

### Step 3: verify

```bash
ssh ec2 /home/ec2-user/git/datapai-stock-be/scripts/run_stock_crm_client_sync.sh --dry-run 2>&1 | grep preferredMarkets
```

### Current exchange aliases

```sql
SELECT config_key, config_value, description FROM datapai.sys_common_config WHERE config_type = 'exchange_aliases';
```

Today: `NASDAQ → US`, `NYSE → US`, `AMEX → US`. These ensure any `watchlist.exchange = 'NASDAQ'` row gets counted under Twenty's `US` enum.

---

## Chat / LLM limits (existing pre-Phase 4 config, included for completeness)

**Affects**: AI copilot message budget per user per day/month.
**Where**: `datapai.sys_common_config`, `config_type='chat_limits'`.
**When it takes effect**: Next chat request (the backend reads this on every call).

### See current chat limits

```sql
SELECT config_key, config_value, description
FROM datapai.sys_common_config
WHERE config_type = 'chat_limits'
ORDER BY config_key;
```

### Change a plan's daily message cap

```sql
UPDATE datapai.sys_common_config
SET config_value = '1000', updated_at = NOW()
WHERE config_type = 'chat_limits'
  AND config_key  = 'individual_daily_limit';   -- or pro_daily_limit, business_daily_limit, etc.
```

---

## Feature flags (existing)

```sql
-- List all flags
SELECT config_key, config_value, description FROM datapai.sys_common_config WHERE config_type = 'feature_flags';

-- Toggle one off
UPDATE datapai.sys_common_config
SET config_value = 'false'
WHERE config_type = 'feature_flags' AND config_key = 'google_search_grounding';
```

---

## LLM model selection (existing)

```sql
-- See which model each role is using
SELECT config_key, config_value, description FROM datapai.sys_common_config WHERE config_type = 'llm_config';

-- Switch the copilot to a different model
UPDATE datapai.sys_common_config
SET config_value = 'gemini-2.5-pro'
WHERE config_type = 'llm_config' AND config_key = 'copilot_model';
```

---

## Emergency: disable a channel entirely

### Disable push notifications for all users

```sql
-- Fast way: lower all push daily limits to 0 → nothing sends
UPDATE datapai.sys_common_config
SET config_value = '0', updated_at = NOW()
WHERE config_type = 'push_limits' AND config_key LIKE '%_daily_limit';
```

To re-enable: `SET config_value = '5'` etc. or restore from backup.

### Disable Telegram for all users

```sql
UPDATE datapai.usr_notification_prefs
SET enabled = FALSE, updated_at = NOW()
WHERE channel = 'telegram';
```

### Completely kill `send_alerts.py` (nuclear option)

Via Airflow:
```bash
ssh ec2 docker exec dbt_airflow-airflow-scheduler-1 airflow dags pause datapai_alerts
```

Re-enable: `airflow dags unpause datapai_alerts`.

---

## Rollback last config change

All `sys_common_config` rows have `created_at` + `updated_at` columns, but there's no history table. **Write down what you're changing before you change it**, or take a snapshot:

```sql
-- Snapshot all push_limits before a change
CREATE TEMP TABLE push_limits_backup AS
SELECT * FROM datapai.sys_common_config WHERE config_type = 'push_limits';

-- Make your change
UPDATE datapai.sys_common_config SET config_value = '0' WHERE config_type = 'push_limits' AND config_key = 'watch_daily_limit';

-- Verify it went wrong
-- ...

-- Restore from snapshot
UPDATE datapai.sys_common_config c
SET config_value = b.config_value, updated_at = NOW()
FROM push_limits_backup b
WHERE c.config_type = b.config_type AND c.config_key = b.config_key;
```

---

## What is **NOT** in this runbook (i.e. needs code changes)

These decisions are still in code because they're either protocol constants or require logic:

- **JWT secret rotation** → env var `.env.dev` → restart `auth-be.service`
- **Adding a new notification channel** (e.g. Discord, WhatsApp) → code change in `send_alerts.py` + new send function + optional CHECK constraint on `usr_notification_prefs.channel`
- **New Twenty custom object** (e.g. `stockAlert` entity type) → code change in `bootstrap_twenty_objects.py` + re-run
- **Password policy** (min length, required character classes) → `PASSWORD_PATTERN` regex in `auth-be/agents/auth/endpoint.py`
- **Session expiry duration** → `JWT_EXPIRY_DAYS` env var or the default in `endpoint.py`
- **Rate limit thresholds on auth endpoints** → env vars `RATE_LIMIT_MAX_ATTEMPTS`, `RATE_LIMIT_WINDOW_MINUTES`

These are things where the business case for DB-driven is weak (changes rarely, or requires logic that's hard to express as data).

---

## Known drift risks to watch

| If you change... | ...then also check |
|---|---|
| `sys_pricing_tiers` (add/rename plan) | Twenty `subscriptionPlan` SELECT options, `sys_common_config` `push_limits` and `chat_limits` config rows |
| Twenty field options via UI | Next `stock_crm_client_sync` run — auto-picked up, no action needed |
| `datapai.user_devices` schema | The FDW foreign-table alias on `stock_db` (run the ALTER FOREIGN TABLE migration) |
| Add a new stock exchange | Twenty `preferredMarkets` MULTI_SELECT options, `sys_common_config` `exchange_aliases` if source names differ |

---

## Verification after any change

```bash
# 1. Dry-run the sync — shows exactly what the script would write to Twenty
ssh ec2 /home/ec2-user/git/datapai-stock-be/scripts/run_stock_crm_client_sync.sh --dry-run 2>&1 | head -30

# 2. Real sync
ssh ec2 /home/ec2-user/git/datapai-stock-be/scripts/run_stock_crm_client_sync.sh 2>&1 | tail -5

# 3. Manually trigger the alert pipeline to test push / telegram
ssh ec2 'cd /home/ec2-user/git/datapai-stock-be && set -a && source /home/ec2-user/.env.dev && set +a && python3 scripts/send_alerts.py 2>&1 | tail -10'
```

If you see `summary: created=N updated=M failed=K` with `failed=0`, you're good.

---

## Related

- **Main session journal**: `docs/phase-journals/2026-04-11-phase-1.10-to-4b.md`
- **FDW gotchas** (if you're adding new config tables that cross the framework_db ↔ stock_db FDW boundary): `docs/architecture/fdw-gotchas.md`
- **Design principle** (why DB-driven is the default): see `feedback_db_driven_default.md` in Claude memory
