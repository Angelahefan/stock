-- ============================================================================
-- 027_create_notification_tables.sql
-- Notification preferences + log for Telegram alerts & email digests
-- ============================================================================

-- ── User notification preferences ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS datapai.usr_notification_prefs (
    id              SERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES datapai.users(id) ON DELETE CASCADE,
    channel         TEXT NOT NULL CHECK (channel IN ('telegram', 'email')),
    enabled         BOOLEAN DEFAULT FALSE,          -- disabled by default
    telegram_chat_id TEXT,                          -- set when user links via /start
    alert_signal    BOOLEAN DEFAULT TRUE,           -- BUY/SELL flip alerts
    alert_price     BOOLEAN DEFAULT TRUE,           -- price threshold alerts
    digest_weekly   BOOLEAN DEFAULT TRUE,           -- weekly email digest
    max_daily       INTEGER DEFAULT 3,              -- max alerts per day per channel
    lang            TEXT DEFAULT 'en',              -- preferred language for notifications
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT usr_notification_prefs_unique UNIQUE (user_id, channel)
);

CREATE INDEX IF NOT EXISTS idx_usr_notif_prefs_user    ON datapai.usr_notification_prefs (user_id);
CREATE INDEX IF NOT EXISTS idx_usr_notif_prefs_channel ON datapai.usr_notification_prefs (channel);
CREATE INDEX IF NOT EXISTS idx_usr_notif_prefs_tg_chat ON datapai.usr_notification_prefs (telegram_chat_id)
    WHERE telegram_chat_id IS NOT NULL;

-- ── Notification log ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS datapai.notification_log (
    id           SERIAL PRIMARY KEY,
    user_id      TEXT NOT NULL,
    channel      TEXT NOT NULL,
    ticker       TEXT,
    exchange     TEXT,
    message_type TEXT NOT NULL,                     -- signal_alert, price_alert, weekly_digest
    status       TEXT DEFAULT 'sent',               -- sent, failed, throttled
    error_detail TEXT,
    sent_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notif_log_user    ON datapai.notification_log (user_id);
CREATE INDEX IF NOT EXISTS idx_notif_log_sent    ON datapai.notification_log (sent_at);
CREATE INDEX IF NOT EXISTS idx_notif_log_channel ON datapai.notification_log (channel, sent_at);

-- ── Telegram link tokens (for /start flow) ────────────────────────────────
CREATE TABLE IF NOT EXISTS datapai.telegram_link_tokens (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES datapai.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    used_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tg_link_token_user ON datapai.telegram_link_tokens (user_id);

-- ── Seed i18n labels for notifications (8 languages) ─────────────────────
INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES
    -- Signal alert message
    ('notif.signal_alert_title',    'en',    '📊 Signal Alert',                  'notification'),
    ('notif.signal_alert_title',    'zh',    '📊 信号提醒',                       'notification'),
    ('notif.signal_alert_title',    'zh-TW', '📊 訊號提醒',                       'notification'),
    ('notif.signal_alert_title',    'ja',    '📊 シグナルアラート',                 'notification'),
    ('notif.signal_alert_title',    'ko',    '📊 신호 알림',                       'notification'),
    ('notif.signal_alert_title',    'vi',    '📊 Cảnh báo tín hiệu',            'notification'),
    ('notif.signal_alert_title',    'th',    '📊 แจ้งเตือนสัญญาณ',                'notification'),
    ('notif.signal_alert_title',    'ms',    '📊 Amaran Isyarat',               'notification'),

    -- Signal changed from X to Y
    ('notif.signal_changed',        'en',    'Signal changed from {old} to {new}',               'notification'),
    ('notif.signal_changed',        'zh',    '信号从 {old} 变为 {new}',                            'notification'),
    ('notif.signal_changed',        'zh-TW', '訊號從 {old} 變為 {new}',                            'notification'),
    ('notif.signal_changed',        'ja',    'シグナルが {old} から {new} に変更',                    'notification'),
    ('notif.signal_changed',        'ko',    '신호가 {old}에서 {new}로 변경',                        'notification'),
    ('notif.signal_changed',        'vi',    'Tín hiệu thay đổi từ {old} sang {new}',            'notification'),
    ('notif.signal_changed',        'th',    'สัญญาณเปลี่ยนจาก {old} เป็น {new}',                   'notification'),
    ('notif.signal_changed',        'ms',    'Isyarat berubah dari {old} ke {new}',              'notification'),

    -- Confidence label
    ('notif.confidence',            'en',    'Confidence',            'notification'),
    ('notif.confidence',            'zh',    '置信度',                 'notification'),
    ('notif.confidence',            'zh-TW', '信心度',                 'notification'),
    ('notif.confidence',            'ja',    '信頼度',                 'notification'),
    ('notif.confidence',            'ko',    '신뢰도',                 'notification'),
    ('notif.confidence',            'vi',    'Độ tin cậy',           'notification'),
    ('notif.confidence',            'th',    'ความมั่นใจ',             'notification'),
    ('notif.confidence',            'ms',    'Keyakinan',            'notification'),

    -- Weekly digest subject
    ('notif.weekly_digest_subject', 'en',    'DataPAI Weekly Portfolio Digest',                   'notification'),
    ('notif.weekly_digest_subject', 'zh',    'DataPAI 每周投资组合摘要',                              'notification'),
    ('notif.weekly_digest_subject', 'zh-TW', 'DataPAI 每週投資組合摘要',                              'notification'),
    ('notif.weekly_digest_subject', 'ja',    'DataPAI 週間ポートフォリオダイジェスト',                    'notification'),
    ('notif.weekly_digest_subject', 'ko',    'DataPAI 주간 포트폴리오 요약',                           'notification'),
    ('notif.weekly_digest_subject', 'vi',    'DataPAI Tổng hợp danh mục đầu tư hàng tuần',      'notification'),
    ('notif.weekly_digest_subject', 'th',    'DataPAI สรุปพอร์ตโฟลิโอประจำสัปดาห์',                   'notification'),
    ('notif.weekly_digest_subject', 'ms',    'DataPAI Ringkasan Portfolio Mingguan',              'notification'),

    -- Unsubscribe link text
    ('notif.unsubscribe',           'en',    'Unsubscribe',          'notification'),
    ('notif.unsubscribe',           'zh',    '退订',                  'notification'),
    ('notif.unsubscribe',           'zh-TW', '退訂',                  'notification'),
    ('notif.unsubscribe',           'ja',    '配信停止',               'notification'),
    ('notif.unsubscribe',           'ko',    '구독 취소',              'notification'),
    ('notif.unsubscribe',           'vi',    'Hủy đăng ký',         'notification'),
    ('notif.unsubscribe',           'th',    'ยกเลิกการสมัคร',         'notification'),
    ('notif.unsubscribe',           'ms',    'Nyahlanggan',          'notification'),

    -- Bot linked successfully
    ('notif.bot_linked',            'en',    'Account linked successfully! You will receive alerts for your watchlist.',   'notification'),
    ('notif.bot_linked',            'zh',    '账号链接成功！您将收到关注列表的提醒。',                                          'notification'),
    ('notif.bot_linked',            'zh-TW', '帳號連結成功！您將收到關注清單的提醒。',                                          'notification'),
    ('notif.bot_linked',            'ja',    'アカウント連携完了！ウォッチリストのアラートを受信します。',                           'notification'),
    ('notif.bot_linked',            'ko',    '계정 연동 완료! 관심 목록 알림을 받게 됩니다.',                                   'notification'),
    ('notif.bot_linked',            'vi',    'Liên kết tài khoản thành công! Bạn sẽ nhận cảnh báo cho danh sách theo dõi.', 'notification'),
    ('notif.bot_linked',            'th',    'เชื่อมต่อบัญชีสำเร็จ! คุณจะได้รับการแจ้งเตือนสำหรับรายการเฝ้าดู',                 'notification'),
    ('notif.bot_linked',            'ms',    'Akaun berjaya dipautkan! Anda akan menerima amaran untuk senarai pantau.',  'notification'),

    -- Bot unlinked
    ('notif.bot_unlinked',          'en',    'Account unlinked. You will no longer receive alerts.',              'notification'),
    ('notif.bot_unlinked',          'zh',    '账号已断开链接。您将不再收到提醒。',                                    'notification'),
    ('notif.bot_unlinked',          'zh-TW', '帳號已解除連結。您將不再收到提醒。',                                    'notification'),
    ('notif.bot_unlinked',          'ja',    'アカウント連携を解除しました。アラートは届かなくなります。',                  'notification'),
    ('notif.bot_unlinked',          'ko',    '계정 연동이 해제되었습니다. 더 이상 알림을 받지 않습니다.',                 'notification'),
    ('notif.bot_unlinked',          'vi',    'Đã hủy liên kết tài khoản. Bạn sẽ không nhận cảnh báo nữa.',     'notification'),
    ('notif.bot_unlinked',          'th',    'ยกเลิกการเชื่อมต่อบัญชีแล้ว จะไม่ได้รับการแจ้งเตือนอีกต่อไป',        'notification'),
    ('notif.bot_unlinked',          'ms',    'Akaun telah dinyahpaut. Anda tidak lagi akan menerima amaran.',   'notification'),

    -- Weekly digest: stock row headers
    ('notif.digest_stock',          'en',    'Stock',                'notification'),
    ('notif.digest_stock',          'zh',    '股票',                  'notification'),
    ('notif.digest_stock',          'zh-TW', '股票',                  'notification'),
    ('notif.digest_stock',          'ja',    '銘柄',                  'notification'),
    ('notif.digest_stock',          'ko',    '종목',                  'notification'),
    ('notif.digest_stock',          'vi',    'Cổ phiếu',            'notification'),
    ('notif.digest_stock',          'th',    'หุ้น',                  'notification'),
    ('notif.digest_stock',          'ms',    'Saham',                'notification'),

    ('notif.digest_price',          'en',    'Price',                'notification'),
    ('notif.digest_price',          'zh',    '价格',                  'notification'),
    ('notif.digest_price',          'zh-TW', '價格',                  'notification'),
    ('notif.digest_price',          'ja',    '株価',                  'notification'),
    ('notif.digest_price',          'ko',    '가격',                  'notification'),
    ('notif.digest_price',          'vi',    'Giá',                  'notification'),
    ('notif.digest_price',          'th',    'ราคา',                  'notification'),
    ('notif.digest_price',          'ms',    'Harga',                'notification'),

    ('notif.digest_change',         'en',    'Weekly Change',        'notification'),
    ('notif.digest_change',         'zh',    '周涨跌',                'notification'),
    ('notif.digest_change',         'zh-TW', '週漲跌',                'notification'),
    ('notif.digest_change',         'ja',    '週間騰落',              'notification'),
    ('notif.digest_change',         'ko',    '주간 변동',             'notification'),
    ('notif.digest_change',         'vi',    'Thay đổi tuần',       'notification'),
    ('notif.digest_change',         'th',    'เปลี่ยนแปลงรายสัปดาห์',  'notification'),
    ('notif.digest_change',         'ms',    'Perubahan Mingguan',   'notification'),

    ('notif.digest_signal',         'en',    'AI Signal',            'notification'),
    ('notif.digest_signal',         'zh',    'AI 信号',               'notification'),
    ('notif.digest_signal',         'zh-TW', 'AI 訊號',               'notification'),
    ('notif.digest_signal',         'ja',    'AIシグナル',             'notification'),
    ('notif.digest_signal',         'ko',    'AI 신호',               'notification'),
    ('notif.digest_signal',         'vi',    'Tín hiệu AI',         'notification'),
    ('notif.digest_signal',         'th',    'สัญญาณ AI',             'notification'),
    ('notif.digest_signal',         'ms',    'Isyarat AI',           'notification')

ON CONFLICT (label_key, lang) DO UPDATE SET
    text = EXCLUDED.text,
    category = EXCLUDED.category,
    updated_at = NOW();
