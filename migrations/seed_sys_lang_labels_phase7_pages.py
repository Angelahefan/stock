#!/usr/bin/env python3
"""Phase 7 seed: US/ASX page labels — section headers, table headers, card labels."""
import psycopg2, psycopg2.extras, os

conn = psycopg2.connect(host=os.environ.get("PGHOST","localhost"), port=int(os.environ.get("PGPORT","5432")),
    dbname="postgres", user=os.environ.get("PGUSER","postgres"), password=os.environ.get("PGPASSWORD","postgres"))

# fmt: off
LABELS = [
    ("section_us_market", "common", {
        "en": "US Markets", "zh": "美国市场", "zh-TW": "美國市場", "ja": "米国市場", "ko": "미국 시장", "vi": "Thị trường Mỹ", "th": "ตลาดสหรัฐ", "ms": "Pasaran AS",
    }),
    ("section_asx_market", "common", {
        "en": "Australian Securities Exchange", "zh": "澳大利亚证券交易所", "zh-TW": "澳洲證券交易所", "ja": "オーストラリア証券取引所", "ko": "호주증권거래소", "vi": "Sở GDCK Úc", "th": "ตลาดหลักทรัพย์ออสเตรเลีย", "ms": "Bursa Sekuriti Australia",
    }),
    ("change_detected", "common", {
        "en": "change detected", "zh": "检测到变化", "zh-TW": "檢測到變化", "ja": "変更検出", "ko": "변경 감지됨", "vi": "phát hiện thay đổi", "th": "ตรวจพบการเปลี่ยนแปลง", "ms": "perubahan dikesan",
    }),
    ("nav_asx_short", "common", {
        "en": "Australia", "zh": "澳洲", "zh-TW": "澳洲", "ja": "オーストラリア", "ko": "호주", "vi": "Úc", "th": "ออสเตรเลีย", "ms": "Australia",
    }),
    ("scan_label", "common", {
        "en": "Scan", "zh": "扫描", "zh-TW": "掃描", "ja": "スキャン", "ko": "스캔", "vi": "Quét", "th": "สแกน", "ms": "Imbasan",
    }),
]
# fmt: on

rows = []
for key, cat, trans in LABELS:
    for lang, text in trans.items():
        rows.append((key, lang, text, cat))

print(f"Seeding {len(rows)} label rows ({len(LABELS)} keys × 8 languages)...")
with conn.cursor() as cur:
    psycopg2.extras.execute_values(cur,
        """INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES %s
           ON CONFLICT (label_key, lang) DO UPDATE SET text = EXCLUDED.text, category = EXCLUDED.category, updated_at = NOW()""",
        rows, template="(%s, %s, %s, %s)")
    conn.commit()
    print(f"Upserted {cur.rowcount} rows.")
    cur.execute("SELECT COUNT(*) FROM datapai.sys_lang_labels")
    print(f"Total labels in DB: {cur.fetchone()[0]}")
conn.close()
print("Done.")
