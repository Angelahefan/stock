# Phase 4C — Real-device push notification smoke test plan

> **Status**: ready to execute. Requires a physical iPhone or Android device + a mobile dev build.
>
> **Prerequisites completed** (by 2026-04-11 session, documented in [`2026-04-11-phase-1.10-to-4b.md`](2026-04-11-phase-1.10-to-4b.md)):
> - Backend `/api/auth/device/register` endpoint is live and tested
> - `datapai.user_devices` table exists with FDW alias on stock_db
> - `send_alerts.py` has the push loop wired + `_send_expo_push` function verified end-to-end with a fake token
> - Mobile app `lib/notifications.ts` has `registerDeviceWithBackend()` wired and called from `lib/api.ts` `auth.login`/`auth.register` on success
> - Mobile app `app/_layout.tsx` has notification tap deep-link handler for `signal_alert` payloads
> - `expo-notifications`, `expo-device`, `expo-secure-store` already installed

## Goal

Prove that a real Expo push token from a real device:
1. Gets registered in `datapai.user_devices` via `POST /api/auth/device/register` on first launch after login
2. Receives a real Expo Push notification when `send_alerts.py` detects a signal change
3. Routes to the ticker detail page when the user taps the notification

## Prerequisites you need to have

- **Apple Developer account** ($99/year) if testing on iOS — needed to install a dev build on a physical iPhone
- **OR a physical Android device** — simpler, no developer account needed
- **EAS CLI** or **Xcode / Android Studio** for building
  - Easiest path: `npm install -g eas-cli` then `eas login`
  - Xcode path: requires Xcode + a provisioning profile + physical device paired via USB
- **Your personal iPhone or Android phone** with the ability to grant notification permission
- A working login (`donny@datap.ai` + password — already in your head)

## Step-by-step

### 1. Start a dev build

Pick one of these two paths:

**Path A — EAS dev build (recommended, cloud-builds the app, no local Xcode needed)**

```bash
cd /Users/linlin/git/datapai-mobile
eas build --profile development --platform ios --local   # or --platform android
# (remove --local to build in Expo's cloud — slower but no Xcode needed)
```

Then scan the QR code / download the `.ipa` or `.apk` onto your phone and install it. For iOS, you may need to trust the developer profile in Settings → General → Device Management.

**Path B — `npx expo run:ios` or `run:android` (faster if you have Xcode / Android Studio set up)**

```bash
cd /Users/linlin/git/datapai-mobile
npx expo run:ios   # launches Xcode build, installs on a connected iPhone
# or
npx expo run:android   # launches Android Studio build
```

Either path gives you a **development build** of the app (not Expo Go) — important because push notifications don't work reliably in Expo Go for managed workflow projects.

### 2. Launch the app, grant notification permission

1. Open the newly-installed DATAP.AI app on your phone
2. Log in as `donny@datap.ai` with your existing password
3. **Watch for the iOS/Android permission prompt**: "DATAP.AI Would Like to Send You Notifications" → tap **Allow**
4. The app should continue to the tabs screen normally

### 3. Verify the device was registered on the backend

```bash
ssh ec2 'docker exec datapai_framework_db psql -U postgres -d datapai_auth_db -c "
  SELECT id, user_id, platform, substring(expo_push_token, 1, 40) AS token_prefix,
         device_name, device_model, os_version, app_version,
         last_seen_at, created_at
  FROM datapai.user_devices
  WHERE disabled_at IS NULL
  ORDER BY last_seen_at DESC
  LIMIT 5
"'
```

**Expected result**: one new row with:
- `user_id` = `9974f810-2256-4f65-82d0-6639c3fd6124` (donny's legacy stock.users.id — the linking works via auth.users.uuid for new users, but donny is legacy)
- `platform` = `ios` or `android`
- `token_prefix` starts with `ExponentPushToken[` followed by a real token string (40+ chars)
- `device_name` is your iPhone's name or "iPhone device" / "Android device"
- `last_seen_at` is within the last few seconds

**If the row is missing**:
- Check the mobile app logs via `npx expo start` terminal for any error messages
- Check `auth.audit_log` for `register_failed` / `device_register_failed` events
- Verify `authFetch<T>()` in `lib/api.ts` is hitting the right URL (`AUTH_BASE = "https://auth.datap.ai"`)
- Check the iOS device's Settings → Notifications → DATAP.AI → confirm "Allow Notifications" is ON
- Try to re-trigger by force-quitting the app and reopening

### 4. Send a real push notification

Use the existing smoke test pattern but with your REAL token. SSH to EC2:

```bash
ssh ec2

# Get donny's real token from the DB
export REAL_TOKEN=$(docker exec datapai_framework_db psql -U postgres -d datapai_auth_db -tAc "
  SELECT expo_push_token FROM datapai.user_devices
  WHERE user_id = '9974f810-2256-4f65-82d0-6639c3fd6124'
    AND disabled_at IS NULL
    AND expo_push_token IS NOT NULL
  ORDER BY last_seen_at DESC LIMIT 1
")
echo "token: $REAL_TOKEN"

# Send a direct test via Expo Push Service (bypasses send_alerts.py — proves the token works)
curl -sS -X POST https://exp.host/--/api/v2/push/send \
  -H "Content-Type: application/json" \
  -d "[{
    \"to\": \"$REAL_TOKEN\",
    \"title\": \"🧪 Phase 4C test\",
    \"body\": \"If you can see this on your lock screen, push notifications work!\",
    \"data\": {
      \"type\": \"signal_alert\",
      \"ticker\": \"BHP.AX\",
      \"exchange\": \"ASX\"
    },
    \"sound\": \"default\",
    \"priority\": \"high\",
    \"channelId\": \"signal-alerts\"
  }]" | python3 -m json.tool
```

**Expected**:
- Response: `{"data": [{"status": "ok", "id": "..."}]}` (a ticket with `status=ok`)
- **Your phone lock screen shows the notification within 1-5 seconds**
- Title: "🧪 Phase 4C test"
- Body: "If you can see this..."

**If the response is `status=error`**:
- `"DeviceNotRegistered"` — the token is stale / wrong. Go back to step 2 and re-register.
- `"MessageTooBig"` — shouldn't happen with a simple message, but reduce the payload size.
- `"InvalidCredentials"` — Expo's free anonymous tokens should work without credentials. If you see this, your `projectId` in `app.json` → `extra.eas.projectId` is wrong.
- `"MessageRateExceeded"` — Expo rate-limited you. Wait 5 minutes and retry.

### 5. Verify tap deep-link works

Tap the notification that just arrived on your phone.

**Expected**:
- iOS/Android wakes the DATAP.AI app
- The app navigates to `/ticker/BHP.AX?exchange=ASX`
- The ticker detail screen loads

**If the app opens but doesn't deep-link**:
- Check the log for `[layout] notification tap deep-link failed` from `app/_layout.tsx`
- Verify the `data` field of the notification payload has `type: 'signal_alert'` AND `ticker: 'BHP.AX'` AND `exchange: 'ASX'`
- Ensure the app was actually quit (not just backgrounded) — `addNotificationResponseReceivedListener` fires for cold starts too, but sometimes the listener hasn't mounted yet

### 6. Trigger a REAL signal change via the alert pipeline

This is the end-to-end test that proves the whole pipeline (signal detection → `send_alerts.py` → Expo → device) works.

Easiest way: use the existing smoke test script pattern but substitute the real token for the fake one. The smoke test is at `/tmp/phase4a_push_smoke_test.py` on EC2 — edit the `FAKE_TOKEN` constant to be your real ExponentPushToken, then run:

```bash
ssh ec2
# Edit /tmp/phase4a_push_smoke_test.py — change FAKE_TOKEN to your real token
# Then:
python3 /tmp/phase4a_push_smoke_test.py 2>&1
```

**Expected**:
- Script picks a ticker from donny's watchlist, fabricates a "previous signal" row, runs `send_alerts.py`
- `send_alerts.py` detects the change, calls `_send_expo_push` with your real token
- Expo responds with `status=ok`
- **Phone lock screen shows a REAL signal alert** with the ticker + direction flip in the body
- Tap → deep-links to the ticker detail screen

**Cleanup happens automatically** — the smoke test deletes the synthetic device row + notification_log rows after the run.

### 7. (Optional) Wait for a real live signal change

Instead of fabricating via the smoke test, you can wait for the actual `send_alerts.py` Airflow DAG to fire a real signal change during market hours. The schedule is every 30 min. When the signal pipeline detects a real BUY→SELL or similar flip on a ticker in donny's watchlist, the push should arrive on your phone within 30 min.

This is the true end-to-end validation. Worth doing at least once to confirm the scheduled pipeline works without any manual synthesis.

## Success criteria

All 5 must pass:
- [ ] `datapai.user_devices` has a real `ExponentPushToken[...]` row for donny within 10 seconds of app launch
- [ ] Direct `curl https://exp.host/--/api/v2/push/send` returns `status=ok`
- [ ] Phone lock screen shows the test notification
- [ ] Tapping the notification deep-links to the ticker detail page
- [ ] Running the `phase4a_push_smoke_test.py` with the real token (or waiting for a real signal change) delivers a "signal_alert" notification via `send_alerts.py`

Once all 5 pass, Phase 4C is complete and the entire Phase 4 (mobile push notification infrastructure) is green.

## Troubleshooting — common issues

### "Push notifications only work on physical devices"

The mobile code refuses to register on a simulator / emulator via `Device.isDevice` check. This is intentional — Expo Push tokens don't work on simulators. Use a real device.

### The app doesn't show the permission prompt

- iOS: already granted OR permanently denied. Check Settings → DATAP.AI → Notifications → toggle on.
- Android 13+: the permission is requested at runtime; if denied once, you may need to toggle it in Settings → Apps → DATAP.AI → Notifications.

### Notification arrives but tap doesn't deep-link

Check the payload shape. The `data` field must be an object (not a string) with at least `type`, `ticker`, `exchange` keys. If sent via the direct curl above with a string body, JSON parse it first.

### `send_alerts.py` logs "0 sent, 0 eligible users" for push

The push user query joins `datapai.user_devices` to `datapai.users`. If donny's row in `user_devices` has `disabled_at` set, or `expo_push_token` is null/empty, he won't be in the eligible user list. Check:
```sql
SELECT * FROM datapai.user_devices WHERE user_id = '9974f810-2256-4f65-82d0-6639c3fd6124';
```

### "Sound does not play" on iOS

iOS has a "focus" mode that silences non-critical notifications. Also, the app's notification settings need "Sounds" enabled under Settings → DATAP.AI → Notifications.

### Expo returns `"DeviceNotRegistered"` unexpectedly

This happens when:
- The device token is stale (e.g. the user uninstalled and reinstalled the app)
- You copied the token incorrectly (missing brackets, truncated)
- The OS rotated the token (rare on iOS, more common on Android Battery Saver)

Fix: force a fresh registration by force-quitting the app and relaunching. `send_alerts.py::_disable_invalid_push_token` will automatically soft-delete the bad token.

## What happens after Phase 4C passes

- Mark the Phase 4 todo as complete in the session journal
- Move on to Phase 2 (ERPNext for healthcare CRM) when the first real B2B health lead comes in
- Or revisit any of the parked items (Phase 1.11 MFA, legacy user ID migration, stock-be JWT verification gap)
