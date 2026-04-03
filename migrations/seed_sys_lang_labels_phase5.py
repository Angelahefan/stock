#!/usr/bin/env python3
"""
Phase 5 seed: remaining hardcoded English strings.
- WatchlistButton labels
- TickerScanButton labels
- Agent flow + ticker page misc
- TechAnalyticsPanel loading spinner
"""
import psycopg2
import psycopg2.extras
import os

conn = psycopg2.connect(
    host=os.environ.get("PGHOST", "localhost"),
    port=int(os.environ.get("PGPORT", "5432")),
    dbname="postgres",
    user=os.environ.get("PGUSER", "postgres"),
    password=os.environ.get("PGPASSWORD", "postgres"),
)

# fmt: off
LABELS = [
    # ── Watchlist buttons ──
    ("btn_login_watch", "common", {
        "en": "Log in to Watch", "zh": "登录后关注", "zh-TW": "登入後關注", "ja": "ログインしてウォッチ", "ko": "로그인하여 관심등록", "vi": "Đăng nhập để theo dõi", "th": "เข้าสู่ระบบเพื่อติดตาม", "ms": "Log masuk untuk pantau",
    }),
    ("btn_watch", "common", {
        "en": "Watch", "zh": "关注", "zh-TW": "關注", "ja": "ウォッチ", "ko": "관심등록", "vi": "Theo dõi", "th": "ติดตาม", "ms": "Pantau",
    }),
    ("btn_watching", "common", {
        "en": "Watching", "zh": "已关注", "zh-TW": "已關注", "ja": "ウォッチ中", "ko": "관심종목", "vi": "Đang theo dõi", "th": "กำลังติดตาม", "ms": "Memantau",
    }),
    ("btn_add_watchlist", "common", {
        "en": "Add to Watchlist", "zh": "添加到关注列表", "zh-TW": "加入關注清單", "ja": "ウォッチリストに追加", "ko": "관심목록에 추가", "vi": "Thêm vào danh sách theo dõi", "th": "เพิ่มในรายการติดตาม", "ms": "Tambah ke senarai pantau",
    }),

    # ── Scan buttons ──
    ("btn_rescan", "common", {
        "en": "Re-scan", "zh": "重新扫描", "zh-TW": "重新掃描", "ja": "再スキャン", "ko": "재스캔", "vi": "Quét lại", "th": "สแกนอีกครั้ง", "ms": "Imbas semula",
    }),
    ("btn_scan_stock", "common", {
        "en": "Scan This Stock", "zh": "扫描此股票", "zh-TW": "掃描此股票", "ja": "この銘柄をスキャン", "ko": "이 종목 스캔", "vi": "Quét cổ phiếu này", "th": "สแกนหุ้นนี้", "ms": "Imbas saham ini",
    }),

    # ── Agent flow misc ──
    ("ticker_scans_stored", "ticker", {
        "en": "scans stored permanently in database",
        "zh": "次扫描永久存储在数据库中",
        "zh-TW": "次掃描永久存儲在資料庫中",
        "ja": "回のスキャンをデータベースに永久保存",
        "ko": "회 스캔이 데이터베이스에 영구 저장됨",
        "vi": "lần quét được lưu vĩnh viễn trong cơ sở dữ liệu",
        "th": "การสแกนถูกจัดเก็บถาวรในฐานข้อมูล",
        "ms": "imbasan disimpan secara kekal dalam pangkalan data",
    }),
    ("ticker_signal_from", "ticker", {
        "en": "Showing AI signal from",
        "zh": "显示AI信号来自",
        "zh-TW": "顯示AI信號來自",
        "ja": "AIシグナル表示元：",
        "ko": "AI 시그널 출처：",
        "vi": "Hiển thị tín hiệu AI từ",
        "th": "แสดงสัญญาณ AI จาก",
        "ms": "Menunjukkan isyarat AI dari",
    }),
    ("ticker_no_signal", "ticker", {
        "en": "No new financial signal in latest scan",
        "zh": "最新扫描中无新金融信号",
        "zh-TW": "最新掃描中無新金融信號",
        "ja": "最新スキャンで新たな金融シグナルなし",
        "ko": "최신 스캔에서 새로운 금융 시그널 없음",
        "vi": "Không có tín hiệu tài chính mới trong lần quét gần nhất",
        "th": "ไม่มีสัญญาณทางการเงินใหม่ในการสแกนล่าสุด",
        "ms": "Tiada isyarat kewangan baharu dalam imbasan terkini",
    }),
    ("ticker_powered_tagline", "ticker", {
        "en": "Web execution by TinyFish · Financial intelligence by DataP.ai",
        "zh": "网页执行由TinyFish提供 · 金融情报由DataP.ai提供",
        "zh-TW": "網頁執行由TinyFish提供 · 金融情報由DataP.ai提供",
        "ja": "Web実行：TinyFish · 金融インテリジェンス：DataP.ai",
        "ko": "웹 실행: TinyFish · 금융 인텔리전스: DataP.ai",
        "vi": "Thực thi web bởi TinyFish · Phân tích tài chính bởi DataP.ai",
        "th": "ดำเนินการเว็บโดย TinyFish · ข่าวกรองการเงินโดย DataP.ai",
        "ms": "Pelaksanaan web oleh TinyFish · Perisikan kewangan oleh DataP.ai",
    }),

    # ── TechAnalyticsPanel loading spinner ──
    ("panel_loading_ohlcv", "panel", {
        "en": "Fetching live OHLCV data → computing indicators → generating Gemini signal…",
        "zh": "获取实时OHLCV数据 → 计算指标 → 生成Gemini信号…",
        "zh-TW": "獲取即時OHLCV數據 → 計算指標 → 生成Gemini信號…",
        "ja": "リアルタイムOHLCVデータ取得中 → 指標計算 → Geminiシグナル生成中…",
        "ko": "실시간 OHLCV 데이터 수집 → 지표 계산 → Gemini 시그널 생성 중…",
        "vi": "Đang lấy dữ liệu OHLCV → tính toán chỉ báo → tạo tín hiệu Gemini…",
        "th": "กำลังดึงข้อมูล OHLCV → คำนวณตัวชี้วัด → สร้างสัญญาณ Gemini…",
        "ms": "Mengambil data OHLCV langsung → mengira penunjuk → menjana isyarat Gemini…",
    }),
]
# fmt: on

rows = []
for label_key, category, translations in LABELS:
    for lang, text in translations.items():
        rows.append((label_key, lang, text, category))

print(f"Seeding {len(rows)} label rows ({len(LABELS)} keys × 8 languages)...")

with conn.cursor() as cur:
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category)
        VALUES %s
        ON CONFLICT (label_key, lang)
        DO UPDATE SET text = EXCLUDED.text, category = EXCLUDED.category, updated_at = NOW()
        """,
        rows,
        template="(%s, %s, %s, %s)",
    )
    conn.commit()
    print(f"Upserted {cur.rowcount} rows.")
    cur.execute("SELECT COUNT(*) FROM datapai.sys_lang_labels")
    print(f"Total labels in DB: {cur.fetchone()[0]}")

conn.close()
print("Done.")
