#!/usr/bin/env python3
"""Phase 12b seed: Indexes page i18n — hero, table headers, chips, disclaimer."""
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
    ("index_title", "index", {
        "en": "Global Market Indexes", "zh": "全球市场指数", "zh-TW": "全球市場指數",
        "ja": "グローバル市場指数", "ko": "글로벌 시장 지수", "vi": "Chỉ số Thị trường Toàn cầu",
        "th": "ดัชนีตลาดโลก", "ms": "Indeks Pasaran Global"}),
    ("index_desc", "index", {
        "en": "16 major indexes across 4 regions \u2014 daily OHLCV with RSI, MACD, SMA cross analysis",
        "zh": "4个区域16个主要指数 \u2014 每日OHLCV及RSI、MACD、SMA交叉分析",
        "zh-TW": "4個區域16個主要指數 \u2014 每日OHLCV及RSI、MACD、SMA交叉分析",
        "ja": "4地域16主要指数 \u2014 RSI\u3001MACD\u3001SMAクロス分析付き日次OHLCV",
        "ko": "4개 지역 16개 주요 지수 \u2014 RSI, MACD, SMA 크로스 분석 포함 일일 OHLCV",
        "vi": "16 ch\u1ec9 s\u1ed1 ch\u00ednh t\u1ea1i 4 khu v\u1ef1c \u2014 OHLCV h\u00e0ng ng\u00e0y v\u1edbi ph\u00e2n t\u00edch RSI, MACD, SMA",
        "th": "16 \u0e14\u0e31\u0e0a\u0e19\u0e35\u0e2b\u0e25\u0e31\u0e01\u0e43\u0e19 4 \u0e20\u0e39\u0e21\u0e34\u0e20\u0e32\u0e04 \u2014 OHLCV \u0e23\u0e32\u0e22\u0e27\u0e31\u0e19\u0e1e\u0e23\u0e49\u0e2d\u0e21 RSI, MACD, SMA",
        "ms": "16 indeks utama merentasi 4 rantau \u2014 OHLCV harian dengan analisis RSI, MACD, SMA"}),
    ("index_up", "index", {
        "en": "up", "zh": "\u4e0a\u6da8", "zh-TW": "\u4e0a\u6f32",
        "ja": "\u4e0a\u6607", "ko": "\uc0c1\uc2b9", "vi": "t\u0103ng",
        "th": "\u0e02\u0e36\u0e49\u0e19", "ms": "naik"}),
    ("index_down", "index", {
        "en": "down", "zh": "\u4e0b\u8dcc", "zh-TW": "\u4e0b\u8dcc",
        "ja": "\u4e0b\u843d", "ko": "\ud558\ub77d", "vi": "gi\u1ea3m",
        "th": "\u0e25\u0e07", "ms": "turun"}),
    ("index_th_index", "index", {
        "en": "Index", "zh": "\u6307\u6570", "zh-TW": "\u6307\u6578",
        "ja": "\u6307\u6570", "ko": "\uc9c0\uc218", "vi": "Ch\u1ec9 s\u1ed1",
        "th": "\u0e14\u0e31\u0e0a\u0e19\u0e35", "ms": "Indeks"}),
    ("index_th_level", "index", {
        "en": "Level", "zh": "\u70b9\u4f4d", "zh-TW": "\u9ede\u4f4d",
        "ja": "\u6c34\u6e96", "ko": "\uc218\uc900", "vi": "M\u1ee9c",
        "th": "\u0e23\u0e30\u0e14\u0e31\u0e1a", "ms": "Paras"}),
    ("index_th_trend", "index", {
        "en": "Trend", "zh": "\u8d8b\u52bf", "zh-TW": "\u8da8\u52e2",
        "ja": "\u30c8\u30ec\u30f3\u30c9", "ko": "\ud2b8\ub80c\ub4dc", "vi": "Xu h\u01b0\u1edbng",
        "th": "\u0e41\u0e19\u0e27\u0e42\u0e19\u0e49\u0e21", "ms": "Aliran"}),
    ("index_th_52w", "index", {
        "en": "vs 52w High", "zh": "\u8ddd52\u5468\u9ad8", "zh-TW": "\u8ddd52\u9031\u9ad8",
        "ja": "52\u9031\u9ad8\u5024\u6bd4", "ko": "52\uc8fc \uace0\uc810 \ub300\ube44", "vi": "so \u0111\u1ec9nh 52T",
        "th": "\u0e40\u0e17\u0e35\u0e22\u0e1a 52w \u0e2a\u0e39\u0e07\u0e2a\u0e38\u0e14", "ms": "vs Tinggi 52m"}),
    ("index_disclaimer", "index", {
        "en": "Data as of market close. RSI, MACD, and trend indicators computed from daily OHLCV.",
        "zh": "\u6570\u636e\u622a\u81f3\u6536\u76d8\u3002RSI\u3001MACD\u548c\u8d8b\u52bf\u6307\u6807\u57fa\u4e8e\u6bcf\u65e5OHLCV\u8ba1\u7b97\u3002",
        "zh-TW": "\u6578\u64da\u622a\u81f3\u6536\u76e4\u3002RSI\u3001MACD\u548c\u8da8\u52e2\u6307\u6a19\u57fa\u65bc\u6bcf\u65e5OHLCV\u8a08\u7b97\u3002",
        "ja": "\u5f15\u3051\u5f8c\u306e\u30c7\u30fc\u30bf\u3002RSI\u3001MACD\u3001\u30c8\u30ec\u30f3\u30c9\u6307\u6a19\u306f\u65e5\u6b21OHLCV\u304b\u3089\u7b97\u51fa\u3002",
        "ko": "\uc7a5 \ub9c8\uac10 \uae30\uc900 \ub370\uc774\ud130. RSI, MACD, \ud2b8\ub80c\ub4dc \uc9c0\ud45c\ub294 \uc77c\uc77c OHLCV\uc5d0\uc11c \uacc4\uc0b0.",
        "vi": "D\u1eef li\u1ec7u t\u00ednh \u0111\u1ebfn l\u00fac \u0111\u00f3ng c\u1eeda. RSI, MACD v\u00e0 ch\u1ec9 b\u00e1o xu h\u01b0\u1edbng \u0111\u01b0\u1ee3c t\u00ednh t\u1eeb OHLCV h\u00e0ng ng\u00e0y.",
        "th": "\u0e02\u0e49\u0e2d\u0e21\u0e39\u0e25 \u0e13 \u0e15\u0e25\u0e32\u0e14\u0e1b\u0e34\u0e14 RSI, MACD \u0e41\u0e25\u0e30\u0e15\u0e31\u0e27\u0e0a\u0e35\u0e49\u0e41\u0e19\u0e27\u0e42\u0e19\u0e49\u0e21\u0e04\u0e33\u0e19\u0e27\u0e13\u0e08\u0e32\u0e01 OHLCV \u0e23\u0e32\u0e22\u0e27\u0e31\u0e19",
        "ms": "Data setakat pasaran tutup. RSI, MACD dan penunjuk aliran dikira daripada OHLCV harian."}),
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
