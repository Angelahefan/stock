#!/usr/bin/env python3
"""Seed i18n labels for China A-Shares pages (8 languages)."""
import psycopg2, psycopg2.extras, os

conn = psycopg2.connect(host=os.environ.get("PGHOST","localhost"), port=int(os.environ.get("PGPORT","5432")),
    dbname="postgres", user=os.environ.get("PGUSER","postgres"), password=os.environ.get("PGPASSWORD","postgres"))

# fmt: off
LABELS = [
    ("nav_china", "common", {
        "en": "A-Shares", "zh": "A股", "zh-TW": "A股", "ja": "A株", "ko": "A주", "vi": "A-Shares", "th": "หุ้น A", "ms": "A-Shares",
    }),
    ("hero_title_china", "china", {
        "en": "China A-Shares", "zh": "中国A股", "zh-TW": "中國A股", "ja": "中国A株", "ko": "중국 A주", "vi": "Cổ phiếu A Trung Quốc", "th": "หุ้น A จีน", "ms": "Saham A China",
    }),
    ("section_china_market", "china", {
        "en": "Shanghai + Shenzhen Stock Exchanges",
        "zh": "上海证券交易所 + 深圳证券交易所",
        "zh-TW": "上海證券交易所 + 深圳證券交易所",
        "ja": "上海・深圳証券取引所",
        "ko": "상하이 + 선전 증권거래소",
        "vi": "Sở GDCK Thượng Hải + Thâm Quyến",
        "th": "ตลาดหลักทรัพย์เซี่ยงไฮ้ + เสินเจิ้น",
        "ms": "Bursa Saham Shanghai + Shenzhen",
    }),
    ("section_sse_stocks", "china", {
        "en": "Shanghai (SSE)", "zh": "上海 (SSE)", "zh-TW": "上海 (SSE)", "ja": "上海 (SSE)", "ko": "상하이 (SSE)", "vi": "Thượng Hải (SSE)", "th": "เซี่ยงไฮ้ (SSE)", "ms": "Shanghai (SSE)",
    }),
    ("section_sse_label", "china", {
        "en": "Shanghai Stock Exchange", "zh": "上海证券交易所", "zh-TW": "上海證券交易所", "ja": "上海証券取引所", "ko": "상하이증권거래소", "vi": "Sở GDCK Thượng Hải", "th": "ตลาดหลักทรัพย์เซี่ยงไฮ้", "ms": "Bursa Saham Shanghai",
    }),
    ("section_szse_stocks", "china", {
        "en": "Shenzhen (SZSE)", "zh": "深圳 (SZSE)", "zh-TW": "深圳 (SZSE)", "ja": "深圳 (SZSE)", "ko": "선전 (SZSE)", "vi": "Thâm Quyến (SZSE)", "th": "เสินเจิ้น (SZSE)", "ms": "Shenzhen (SZSE)",
    }),
    ("section_szse_label", "china", {
        "en": "Shenzhen Stock Exchange", "zh": "深圳证券交易所", "zh-TW": "深圳證券交易所", "ja": "深圳証券取引所", "ko": "선전증권거래소", "vi": "Sở GDCK Thâm Quyến", "th": "ตลาดหลักทรัพย์เสินเจิ้น", "ms": "Bursa Saham Shenzhen",
    }),
]
# fmt: on

rows = []
for key, cat, trans in LABELS:
    for lang, text in trans.items():
        rows.append((key, lang, text, cat))

print(f"Seeding {len(rows)} label rows ({len(LABELS)} keys x 8 languages)...")
with conn.cursor() as cur:
    psycopg2.extras.execute_values(cur,
        """INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES %s
           ON CONFLICT (label_key, lang) DO UPDATE SET text = EXCLUDED.text, category = EXCLUDED.category, updated_at = NOW()""",
        rows, template="(%s, %s, %s, %s)")
    conn.commit()
    print(f"Upserted {cur.rowcount} rows.")
conn.close()
print("Done.")
