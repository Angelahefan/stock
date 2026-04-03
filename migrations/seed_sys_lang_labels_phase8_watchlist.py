#!/usr/bin/env python3
"""Phase 8 seed: Watchlist, Index, Screener page labels."""
import psycopg2, psycopg2.extras, os

conn = psycopg2.connect(host=os.environ.get("PGHOST","localhost"), port=int(os.environ.get("PGPORT","5432")),
    dbname="postgres", user=os.environ.get("PGUSER","postgres"), password=os.environ.get("PGPASSWORD","postgres"))

# fmt: off
LABELS = [
    ("watchlist_title", "watchlist", {
        "en": "My Watchlist", "zh": "我的关注列表", "zh-TW": "我的關注清單", "ja": "マイウォッチリスト", "ko": "내 관심목록", "vi": "Danh sách theo dõi", "th": "รายการติดตาม", "ms": "Senarai pantau saya",
    }),
    ("watchlist_view_alerts", "watchlist", {
        "en": "View My Alerts", "zh": "查看我的预警", "zh-TW": "查看我的預警", "ja": "マイアラートを表示", "ko": "내 알림 보기", "vi": "Xem cảnh báo của tôi", "th": "ดูการแจ้งเตือนของฉัน", "ms": "Lihat amaran saya",
    }),
    ("watchlist_empty", "watchlist", {
        "en": "Your watchlist is empty", "zh": "您的关注列表为空", "zh-TW": "您的關注清單為空", "ja": "ウォッチリストは空です", "ko": "관심목록이 비어 있습니다", "vi": "Danh sách theo dõi trống", "th": "รายการติดตามว่างเปล่า", "ms": "Senarai pantau anda kosong",
    }),
    ("watchlist_empty_desc", "watchlist", {
        "en": "Search for a ticker above, visit any stock page, and click ⭐ Add to Watchlist to start monitoring it.",
        "zh": "在上方搜索股票代码，访问任意股票页面，点击⭐添加到关注列表开始监控。",
        "zh-TW": "在上方搜尋股票代碼，訪問任意股票頁面，點擊⭐加入關注清單開始監控。",
        "ja": "上のティッカーを検索し、任意の銘柄ページを訪問して⭐ウォッチリストに追加をクリックして監視を開始。",
        "ko": "위에서 티커를 검색하고, 주식 페이지를 방문하여 ⭐관심목록에 추가를 클릭하세요.",
        "vi": "Tìm mã cổ phiếu ở trên, truy cập trang cổ phiếu bất kỳ, nhấn ⭐Thêm vào danh sách theo dõi.",
        "th": "ค้นหาหุ้นด้านบน เข้าหน้าหุ้นใดก็ได้ แล้วกด⭐เพิ่มในรายการติดตาม",
        "ms": "Cari saham di atas, lawati halaman saham, dan klik ⭐Tambah ke senarai pantau.",
    }),
    # Index page region labels
    ("region_us", "index", {
        "en": "United States", "zh": "美国", "zh-TW": "美國", "ja": "米国", "ko": "미국", "vi": "Hoa Kỳ", "th": "สหรัฐอเมริกา", "ms": "Amerika Syarikat",
    }),
    ("region_asx", "index", {
        "en": "Australia", "zh": "澳大利亚", "zh-TW": "澳洲", "ja": "オーストラリア", "ko": "호주", "vi": "Úc", "th": "ออสเตรเลีย", "ms": "Australia",
    }),
    ("region_asia", "index", {
        "en": "Asia Pacific", "zh": "亚太地区", "zh-TW": "亞太地區", "ja": "アジア太平洋", "ko": "아시아 태평양", "vi": "Châu Á - Thái Bình Dương", "th": "เอเชียแปซิฟิก", "ms": "Asia Pasifik",
    }),
    ("region_eu", "index", {
        "en": "Europe", "zh": "欧洲", "zh-TW": "歐洲", "ja": "欧州", "ko": "유럽", "vi": "Châu Âu", "th": "ยุโรป", "ms": "Eropah",
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
