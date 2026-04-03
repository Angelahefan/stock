#!/usr/bin/env python3
"""Phase 12c seed: Pricing feature notes + tier-specific feature variants."""
import psycopg2, psycopg2.extras, os

conn = psycopg2.connect(
    host=os.environ.get("PGHOST", "localhost"),
    port=int(os.environ.get("PGPORT", "5432")),
    dbname="postgres",
    user=os.environ.get("PGUSER", "postgres"),
    password=os.environ.get("PGPASSWORD", "postgres"),
)

# fmt: off
LABELS = [
    # ── Feature notes ───────────────────────────────────────────────────────
    ("pf_note_commitment", "pricing", {
        "en": "commitment \u00b7 hedging \u00b7 risk", "zh": "\u627f\u8bfa \u00b7 \u5bf9\u51b2 \u00b7 \u98ce\u9669",
        "zh-TW": "\u627f\u8afe \u00b7 \u5c0d\u6c96 \u00b7 \u98a8\u96aa", "ja": "\u30b3\u30df\u30c3\u30c8\u30e1\u30f3\u30c8 \u00b7 \u30d8\u30c3\u30b8 \u00b7 \u30ea\u30b9\u30af",
        "ko": "\uc57d\uc815 \u00b7 \ud5e4\uc9c0 \u00b7 \ub9ac\uc2a4\ud06c", "vi": "cam k\u1ebft \u00b7 ph\u00f2ng h\u1ed9 \u00b7 r\u1ee7i ro",
        "th": "\u0e04\u0e27\u0e32\u0e21\u0e21\u0e38\u0e48\u0e07\u0e21\u0e31\u0e48\u0e19 \u00b7 \u0e1b\u0e49\u0e2d\u0e07\u0e04\u0e27\u0e32\u0e21\u0e40\u0e2a\u0e35\u0e48\u0e22\u0e07 \u00b7 \u0e04\u0e27\u0e32\u0e21\u0e40\u0e2a\u0e35\u0e48\u0e22\u0e07",
        "ms": "komitmen \u00b7 lindung nilai \u00b7 risiko"}),
    ("pf_note_every_trading", "pricing", {
        "en": "every trading day", "zh": "\u6bcf\u4e2a\u4ea4\u6613\u65e5", "zh-TW": "\u6bcf\u500b\u4ea4\u6613\u65e5",
        "ja": "\u6bce\u55b6\u696d\u65e5", "ko": "\u6bcf \uac70\ub798\uc77c", "vi": "m\u1ed7i ng\u00e0y giao d\u1ecbch",
        "th": "\u0e17\u0e38\u0e01\u0e27\u0e31\u0e19\u0e17\u0e33\u0e01\u0e32\u0e23", "ms": "setiap hari dagangan"}),
    ("pf_note_ir_live", "pricing", {
        "en": "IR context + live price", "zh": "IR\u4e0a\u4e0b\u6587 + \u5b9e\u65f6\u4ef7\u683c",
        "zh-TW": "IR\u4e0a\u4e0b\u6587 + \u5373\u6642\u50f9\u683c", "ja": "IR\u30b3\u30f3\u30c6\u30ad\u30b9\u30c8 + \u30ea\u30a2\u30eb\u30bf\u30a4\u30e0\u4fa1\u683c",
        "ko": "IR \ucee8\ud14d\uc2a4\ud2b8 + \uc2e4\uc2dc\uac04 \uac00\uaca9", "vi": "ng\u1eef c\u1ea3nh IR + gi\u00e1 tr\u1ef1c ti\u1ebfp",
        "th": "\u0e1a\u0e23\u0e34\u0e1a\u0e17 IR + \u0e23\u0e32\u0e04\u0e32\u0e2a\u0e14", "ms": "konteks IR + harga langsung"}),
    ("pf_note_instant", "pricing", {
        "en": "instant repeat loads", "zh": "\u5373\u65f6\u91cd\u590d\u52a0\u8f7d", "zh-TW": "\u5373\u6642\u91cd\u8907\u8f09\u5165",
        "ja": "\u5373\u5ea7\u306e\u518d\u8aad\u307f\u8fbc\u307f", "ko": "\uc989\uc2dc \ubc18\ubcf5 \ub85c\ub4dc",
        "vi": "t\u1ea3i l\u1ea1i t\u1ee9c th\u00ec", "th": "\u0e42\u0e2b\u0e25\u0e14\u0e0b\u0e49\u0e33\u0e17\u0e31\u0e19\u0e17\u0e35",
        "ms": "muat semula segera"}),
    ("pf_note_configurable", "pricing", {
        "en": "configurable schedule", "zh": "\u53ef\u914d\u7f6e\u65f6\u95f4\u8868", "zh-TW": "\u53ef\u914d\u7f6e\u6642\u9593\u8868",
        "ja": "\u8a2d\u5b9a\u53ef\u80fd\u306a\u30b9\u30b1\u30b8\u30e5\u30fc\u30eb", "ko": "\uc124\uc815 \uac00\ub2a5\ud55c \uc77c\uc815",
        "vi": "l\u1ecbch c\u00f3 th\u1ec3 t\u00f9y ch\u1ec9nh", "th": "\u0e15\u0e32\u0e23\u0e32\u0e07\u0e17\u0e35\u0e48\u0e01\u0e33\u0e2b\u0e19\u0e14\u0e40\u0e2d\u0e07\u0e44\u0e14\u0e49",
        "ms": "jadual boleh disesuaikan"}),
    ("pf_note_6agents", "pricing", {
        "en": "all 6 agents", "zh": "\u51686\u4e2a\u4ee3\u7406", "zh-TW": "\u51686\u500b\u4ee3\u7406",
        "ja": "\u51686\u30a8\u30fc\u30b8\u30a7\u30f3\u30c8", "ko": "\u51686\uac1c \uc5d0\uc774\uc804\ud2b8",
        "vi": "t\u1ea5t c\u1ea3 6 agent", "th": "\u0e17\u0e31\u0e49\u0e07 6 \u0e40\u0e2d\u0e40\u0e08\u0e19\u0e15\u0e4c",
        "ms": "semua 6 agen"}),
    ("pf_note_realtime", "pricing", {
        "en": "real-time push", "zh": "\u5b9e\u65f6\u63a8\u9001", "zh-TW": "\u5373\u6642\u63a8\u9001",
        "ja": "\u30ea\u30a2\u30eb\u30bf\u30a4\u30e0\u30d7\u30c3\u30b7\u30e5", "ko": "\uc2e4\uc2dc\uac04 \ud478\uc2dc",
        "vi": "\u0111\u1ea9y th\u1eddi gian th\u1ef1c", "th": "\u0e1e\u0e38\u0e0a\u0e41\u0e1a\u0e1a\u0e40\u0e23\u0e35\u0e22\u0e25\u0e44\u0e17\u0e21\u0e4c",
        "ms": "tolak masa nyata"}),
    ("pf_note_addl_seats", "pricing", {
        "en": "additional seats available", "zh": "\u53ef\u589e\u52a0\u5e2d\u4f4d", "zh-TW": "\u53ef\u589e\u52a0\u5e2d\u4f4d",
        "ja": "\u8ffd\u52a0\u30b7\u30fc\u30c8\u53ef\u80fd", "ko": "\ucd94\uac00 \uc2dc\ud2b8 \uac00\ub2a5",
        "vi": "c\u00f3 th\u1ec3 th\u00eam ch\u1ed7 ng\u1ed3i", "th": "\u0e40\u0e1e\u0e34\u0e48\u0e21\u0e17\u0e35\u0e48\u0e19\u0e31\u0e48\u0e07\u0e44\u0e14\u0e49",
        "ms": "tempat tambahan tersedia"}),
    ("pf_note_addl_request", "pricing", {
        "en": "additional seats on request", "zh": "\u53ef\u7533\u8bf7\u589e\u52a0\u5e2d\u4f4d", "zh-TW": "\u53ef\u7533\u8acb\u589e\u52a0\u5e2d\u4f4d",
        "ja": "\u8ffd\u52a0\u30b7\u30fc\u30c8\u306f\u304a\u554f\u3044\u5408\u308f\u305b", "ko": "\ucd94\uac00 \uc2dc\ud2b8 \uc694\uccad \uac00\ub2a5",
        "vi": "th\u00eam ch\u1ed7 ng\u1ed3i theo y\u00eau c\u1ea7u", "th": "\u0e40\u0e1e\u0e34\u0e48\u0e21\u0e17\u0e35\u0e48\u0e19\u0e31\u0e48\u0e07\u0e15\u0e32\u0e21\u0e04\u0e33\u0e02\u0e2d",
        "ms": "tempat tambahan atas permintaan"}),
    ("pf_note_sla", "pricing", {
        "en": "guaranteed response SLA", "zh": "\u4fdd\u8bc1\u54cd\u5e94SLA", "zh-TW": "\u4fdd\u8b49\u56de\u61c9SLA",
        "ja": "\u5fdc\u7b54SLA\u4fdd\u8a3c", "ko": "\ubcf4\uc7a5\ub41c \uc751\ub2f5 SLA",
        "vi": "SLA ph\u1ea3n h\u1ed3i \u0111\u01b0\u1ee3c \u0111\u1ea3m b\u1ea3o", "th": "SLA \u0e15\u0e2d\u0e1a\u0e2a\u0e19\u0e2d\u0e07\u0e23\u0e31\u0e1a\u0e1b\u0e23\u0e30\u0e01\u0e31\u0e19",
        "ms": "SLA respons dijamin"}),
    ("pf_note_on_request", "pricing", {
        "en": "on request", "zh": "\u5e94\u8981\u6c42\u63d0\u4f9b", "zh-TW": "\u61c9\u8981\u6c42\u63d0\u4f9b",
        "ja": "\u30ea\u30af\u30a8\u30b9\u30c8\u6642", "ko": "\uc694\uccad \uc2dc",
        "vi": "theo y\u00eau c\u1ea7u", "th": "\u0e15\u0e32\u0e21\u0e04\u0e33\u0e02\u0e2d",
        "ms": "atas permintaan"}),
    ("pf_note_sector_score", "pricing", {
        "en": "sector \u00b7 score threshold", "zh": "\u677f\u5757 \u00b7 \u5206\u6570\u9608\u503c",
        "zh-TW": "\u677f\u584a \u00b7 \u5206\u6578\u95be\u503c", "ja": "\u30bb\u30af\u30bf\u30fc \u00b7 \u30b9\u30b3\u30a2\u95be\u5024",
        "ko": "\uc139\ud130 \u00b7 \uc810\uc218 \uc784\uacc4\uac12", "vi": "ng\u00e0nh \u00b7 ng\u01b0\u1ee1ng \u0111i\u1ec3m",
        "th": "\u0e01\u0e25\u0e38\u0e48\u0e21 \u00b7 \u0e40\u0e01\u0e13\u0e11\u0e4c\u0e04\u0e30\u0e41\u0e19\u0e19",
        "ms": "sektor \u00b7 ambang skor"}),
    ("pf_note_annual_contract", "pricing", {
        "en": "annual contract available", "zh": "\u53ef\u7b7e\u5e74\u5ea6\u5408\u540c", "zh-TW": "\u53ef\u7c3d\u5e74\u5ea6\u5408\u540c",
        "ja": "\u5e74\u9593\u5951\u7d04\u53ef\u80fd", "ko": "\uc5f0\uac04 \uacc4\uc57d \uac00\ub2a5",
        "vi": "c\u00f3 h\u1ee3p \u0111\u1ed3ng h\u00e0ng n\u0103m", "th": "\u0e21\u0e35\u0e2a\u0e31\u0e0d\u0e0d\u0e32\u0e23\u0e32\u0e22\u0e1b\u0e35",
        "ms": "kontrak tahunan tersedia"}),
    ("pf_note_competitors", "pricing", {
        "en": "watch competitors too", "zh": "\u4e5f\u53ef\u76d1\u63a7\u7ade\u4e89\u5bf9\u624b", "zh-TW": "\u4e5f\u53ef\u76e3\u63a7\u7af6\u722d\u5c0d\u624b",
        "ja": "\u7af6\u5408\u4ed6\u793e\u3082\u76e3\u8996\u53ef\u80fd", "ko": "\uacbd\uc7c1\uc0ac\ub3c4 \ubaa8\ub2c8\ud130\ub9c1",
        "vi": "theo d\u00f5i c\u1ea3 \u0111\u1ed1i th\u1ee7", "th": "\u0e15\u0e34\u0e14\u0e15\u0e32\u0e21\u0e04\u0e39\u0e48\u0e41\u0e02\u0e48\u0e07\u0e14\u0e49\u0e27\u0e22",
        "ms": "pantau pesaing juga"}),

    # ── Scan history variants ───────────────────────────────────────────────
    ("pf_scan_history_30d", "pricing", {
        "en": "30-day scan history", "zh": "30\u5929\u626b\u63cf\u5386\u53f2", "zh-TW": "30\u5929\u6383\u63cf\u6b77\u53f2",
        "ja": "30\u65e5\u9593\u30b9\u30ad\u30e3\u30f3\u5c65\u6b74", "ko": "30\uc77c \uc2a4\uce94 \uae30\ub85d",
        "vi": "L\u1ecbch s\u1eed qu\u00e9t 30 ng\u00e0y", "th": "\u0e1b\u0e23\u0e30\u0e27\u0e31\u0e15\u0e34\u0e01\u0e32\u0e23\u0e2a\u0e41\u0e01\u0e19 30 \u0e27\u0e31\u0e19",
        "ms": "Sejarah imbasan 30 hari"}),
    ("pf_scan_history_1y", "pricing", {
        "en": "1-year scan history", "zh": "1\u5e74\u626b\u63cf\u5386\u53f2", "zh-TW": "1\u5e74\u6383\u63cf\u6b77\u53f2",
        "ja": "1\u5e74\u9593\u30b9\u30ad\u30e3\u30f3\u5c65\u6b74", "ko": "1\ub144 \uc2a4\uce94 \uae30\ub85d",
        "vi": "L\u1ecbch s\u1eed qu\u00e9t 1 n\u0103m", "th": "\u0e1b\u0e23\u0e30\u0e27\u0e31\u0e15\u0e34\u0e01\u0e32\u0e23\u0e2a\u0e41\u0e01\u0e19 1 \u0e1b\u0e35",
        "ms": "Sejarah imbasan 1 tahun"}),
]
# fmt: on

rows = []
for key, cat, trans in LABELS:
    for lang, text in trans.items():
        rows.append((key, lang, text, cat))

print(f"Seeding {len(rows)} rows ({len(LABELS)} keys \u00d7 8 langs)...")
with conn.cursor() as cur:
    psycopg2.extras.execute_values(
        cur,
        """INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES %s
           ON CONFLICT (label_key, lang)
           DO UPDATE SET text = EXCLUDED.text, category = EXCLUDED.category, updated_at = NOW()""",
        rows, template="(%s, %s, %s, %s)")
    conn.commit()
    print(f"Upserted {cur.rowcount} rows.")
    cur.execute("SELECT COUNT(*) FROM datapai.sys_lang_labels")
    print(f"Total labels in DB: {cur.fetchone()[0]}")
conn.close()
print("Done.")
