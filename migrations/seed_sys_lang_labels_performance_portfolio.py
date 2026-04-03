#!/usr/bin/env python3
"""Seed i18n labels for Signal Performance + Portfolio pages (8 languages)."""
import psycopg2, psycopg2.extras, os

conn = psycopg2.connect(host=os.environ.get("PGHOST","localhost"), port=int(os.environ.get("PGPORT","5432")),
    dbname="postgres", user=os.environ.get("PGUSER","postgres"), password=os.environ.get("PGPASSWORD","postgres"))

# fmt: off
LABELS = [
    # ── Nav ──
    ("nav_performance", "common", {
        "en": "Performance", "zh": "信号绩效", "zh-TW": "信號績效", "ja": "パフォーマンス", "ko": "성과", "vi": "Hiệu suất", "th": "ผลงาน", "ms": "Prestasi",
    }),
    ("nav_portfolio", "common", {
        "en": "Portfolio", "zh": "投资组合", "zh-TW": "投資組合", "ja": "ポートフォリオ", "ko": "포트폴리오", "vi": "Danh mục", "th": "พอร์ตโฟลิโอ", "ms": "Portfolio",
    }),

    # ── Performance page ──
    ("perf_title", "performance", {
        "en": "Signal Performance", "zh": "信号绩效", "zh-TW": "信號績效", "ja": "シグナルパフォーマンス", "ko": "시그널 성과", "vi": "Hiệu suất tín hiệu", "th": "ผลงานสัญญาณ", "ms": "Prestasi Isyarat",
    }),
    ("perf_subtitle", "performance", {
        "en": "Track accuracy and returns of AI-generated trading signals across all markets",
        "zh": "追踪所有市场AI交易信号的准确率和回报",
        "zh-TW": "追蹤所有市場AI交易信號的準確率和回報",
        "ja": "全市場のAIトレーディングシグナルの精度とリターンを追跡",
        "ko": "모든 시장의 AI 트레이딩 시그널 정확도와 수익률 추적",
        "vi": "Theo dõi độ chính xác và lợi nhuận của tín hiệu giao dịch AI trên tất cả thị trường",
        "th": "ติดตามความแม่นยำและผลตอบแทนของสัญญาณการซื้อขาย AI ในทุกตลาด",
        "ms": "Jejak ketepatan dan pulangan isyarat dagangan AI merentas semua pasaran",
    }),
    ("perf_win_rate", "performance", {
        "en": "Win Rate", "zh": "胜率", "zh-TW": "勝率", "ja": "勝率", "ko": "승률", "vi": "Tỷ lệ thắng", "th": "อัตราชนะ", "ms": "Kadar Kemenangan",
    }),
    ("perf_total_signals", "performance", {
        "en": "Total Signals", "zh": "信号总数", "zh-TW": "信號總數", "ja": "シグナル総数", "ko": "총 시그널", "vi": "Tổng tín hiệu", "th": "สัญญาณทั้งหมด", "ms": "Jumlah Isyarat",
    }),
    ("perf_avg_return_30d", "performance", {
        "en": "Avg Return (30d)", "zh": "30日平均回报", "zh-TW": "30日平均回報", "ja": "平均リターン(30日)", "ko": "평균 수익률 (30일)", "vi": "Lợi nhuận TB (30 ngày)", "th": "ผลตอบแทนเฉลี่ย (30 วัน)", "ms": "Pulangan Purata (30h)",
    }),
    ("perf_avg_alpha", "performance", {
        "en": "Avg Alpha vs S&P 500", "zh": "相对标普500超额收益", "zh-TW": "相對標普500超額收益", "ja": "S&P500比アルファ", "ko": "S&P500 대비 알파", "vi": "Alpha TB so với S&P 500", "th": "Alpha เทียบ S&P 500", "ms": "Alpha Purata vs S&P 500",
    }),
    ("perf_by_direction", "performance", {
        "en": "Performance by Signal Direction", "zh": "按信号方向的绩效", "zh-TW": "按信號方向的績效", "ja": "シグナル方向別パフォーマンス", "ko": "시그널 방향별 성과", "vi": "Hiệu suất theo hướng tín hiệu", "th": "ผลงานตามทิศทางสัญญาณ", "ms": "Prestasi Mengikut Arah Isyarat",
    }),
    ("perf_by_exchange", "performance", {
        "en": "Performance by Market", "zh": "按市场的绩效", "zh-TW": "按市場的績效", "ja": "市場別パフォーマンス", "ko": "시장별 성과", "vi": "Hiệu suất theo thị trường", "th": "ผลงานตามตลาด", "ms": "Prestasi Mengikut Pasaran",
    }),
    ("perf_recent_signals", "performance", {
        "en": "Recent Signals", "zh": "最新信号", "zh-TW": "最新信號", "ja": "最新シグナル", "ko": "최근 시그널", "vi": "Tín hiệu gần đây", "th": "สัญญาณล่าสุด", "ms": "Isyarat Terkini",
    }),
    ("perf_direction", "performance", {
        "en": "Direction", "zh": "方向", "zh-TW": "方向", "ja": "方向", "ko": "방향", "vi": "Hướng", "th": "ทิศทาง", "ms": "Arah",
    }),
    ("perf_count", "performance", {
        "en": "Signals", "zh": "信号数", "zh-TW": "信號數", "ja": "シグナル数", "ko": "시그널 수", "vi": "Tín hiệu", "th": "สัญญาณ", "ms": "Isyarat",
    }),
    ("perf_market", "performance", {
        "en": "Market", "zh": "市场", "zh-TW": "市場", "ja": "市場", "ko": "시장", "vi": "Thị trường", "th": "ตลาด", "ms": "Pasaran",
    }),
    ("perf_ticker", "performance", {
        "en": "Ticker", "zh": "代码", "zh-TW": "代碼", "ja": "銘柄", "ko": "종목코드", "vi": "Mã CK", "th": "หุ้น", "ms": "Kod",
    }),
    ("perf_date", "performance", {
        "en": "Date", "zh": "日期", "zh-TW": "日期", "ja": "日付", "ko": "날짜", "vi": "Ngày", "th": "วันที่", "ms": "Tarikh",
    }),
    ("perf_price", "performance", {
        "en": "Price", "zh": "价格", "zh-TW": "價格", "ja": "価格", "ko": "가격", "vi": "Giá", "th": "ราคา", "ms": "Harga",
    }),
    ("perf_alpha_short", "performance", {
        "en": "Alpha", "zh": "超额收益", "zh-TW": "超額收益", "ja": "アルファ", "ko": "알파", "vi": "Alpha", "th": "Alpha", "ms": "Alpha",
    }),
    ("perf_outcome", "performance", {
        "en": "Result", "zh": "结果", "zh-TW": "結果", "ja": "結果", "ko": "결과", "vi": "Kết quả", "th": "ผลลัพธ์", "ms": "Keputusan",
    }),
    ("perf_all", "performance", {
        "en": "All Directions", "zh": "所有方向", "zh-TW": "所有方向", "ja": "全方向", "ko": "전체 방향", "vi": "Tất cả hướng", "th": "ทุกทิศทาง", "ms": "Semua Arah",
    }),

    # ── Portfolio page ──
    ("port_title", "portfolio", {
        "en": "My Portfolio", "zh": "我的投资组合", "zh-TW": "我的投資組合", "ja": "マイポートフォリオ", "ko": "내 포트폴리오", "vi": "Danh mục của tôi", "th": "พอร์ตของฉัน", "ms": "Portfolio Saya",
    }),
    ("port_subtitle", "portfolio", {
        "en": "Track holdings, P&L, and performance vs benchmark",
        "zh": "追踪持仓、盈亏和基准对比",
        "zh-TW": "追蹤持倉、盈虧和基準對比",
        "ja": "保有、損益、ベンチマーク比較を追跡",
        "ko": "보유 종목, 손익, 벤치마크 대비 성과 추적",
        "vi": "Theo dõi danh mục, lãi lỗ và so sánh với benchmark",
        "th": "ติดตามการถือครอง กำไร/ขาดทุน และเปรียบเทียบ benchmark",
        "ms": "Jejak pegangan, untung rugi, dan prestasi vs penanda aras",
    }),
    ("port_login_required", "portfolio", {
        "en": "Please log in to view your portfolio", "zh": "请登录查看投资组合", "zh-TW": "請登入查看投資組合", "ja": "ポートフォリオを表示するにはログインしてください", "ko": "포트폴리오를 보려면 로그인하세요", "vi": "Vui lòng đăng nhập để xem danh mục", "th": "กรุณาเข้าสู่ระบบเพื่อดูพอร์ตโฟลิโอ", "ms": "Sila log masuk untuk melihat portfolio",
    }),
    ("port_total_value", "portfolio", {
        "en": "Total Value", "zh": "总市值", "zh-TW": "總市值", "ja": "総額", "ko": "총 가치", "vi": "Tổng giá trị", "th": "มูลค่ารวม", "ms": "Jumlah Nilai",
    }),
    ("port_total_cost", "portfolio", {
        "en": "Total Cost", "zh": "总成本", "zh-TW": "總成本", "ja": "総コスト", "ko": "총 비용", "vi": "Tổng chi phí", "th": "ต้นทุนรวม", "ms": "Jumlah Kos",
    }),
    ("port_total_pnl", "portfolio", {
        "en": "Total P&L", "zh": "总盈亏", "zh-TW": "總盈虧", "ja": "総損益", "ko": "총 손익", "vi": "Tổng lãi/lỗ", "th": "กำไร/ขาดทุนรวม", "ms": "Jumlah U/R",
    }),
    ("port_return", "portfolio", {
        "en": "Return", "zh": "收益率", "zh-TW": "收益率", "ja": "リターン", "ko": "수익률", "vi": "Lợi nhuận", "th": "ผลตอบแทน", "ms": "Pulangan",
    }),
    ("port_positions", "portfolio", {
        "en": "Positions", "zh": "持仓数", "zh-TW": "持倉數", "ja": "ポジション", "ko": "포지션", "vi": "Vị thế", "th": "ตำแหน่ง", "ms": "Posisi",
    }),
    ("port_allocation", "portfolio", {
        "en": "Allocation", "zh": "配置", "zh-TW": "配置", "ja": "配分", "ko": "배분", "vi": "Phân bổ", "th": "การจัดสรร", "ms": "Peruntukan",
    }),
    ("port_holdings", "portfolio", {
        "en": "Holdings", "zh": "持仓", "zh-TW": "持倉", "ja": "保有銘柄", "ko": "보유 종목", "vi": "Danh mục nắm giữ", "th": "การถือครอง", "ms": "Pegangan",
    }),
    ("port_add", "portfolio", {
        "en": "+ Add Holding", "zh": "+ 添加持仓", "zh-TW": "+ 添加持倉", "ja": "+ 銘柄追加", "ko": "+ 종목 추가", "vi": "+ Thêm", "th": "+ เพิ่มหุ้น", "ms": "+ Tambah",
    }),
    ("port_cancel", "portfolio", {
        "en": "Cancel", "zh": "取消", "zh-TW": "取消", "ja": "キャンセル", "ko": "취소", "vi": "Hủy", "th": "ยกเลิก", "ms": "Batal",
    }),
    ("port_save", "portfolio", {
        "en": "Save", "zh": "保存", "zh-TW": "儲存", "ja": "保存", "ko": "저장", "vi": "Lưu", "th": "บันทึก", "ms": "Simpan",
    }),
    ("port_ticker", "portfolio", {
        "en": "Ticker", "zh": "代码", "zh-TW": "代碼", "ja": "銘柄", "ko": "종목코드", "vi": "Mã CK", "th": "หุ้น", "ms": "Kod",
    }),
    ("port_exchange", "portfolio", {
        "en": "Market", "zh": "市场", "zh-TW": "市場", "ja": "市場", "ko": "시장", "vi": "Sàn", "th": "ตลาด", "ms": "Pasaran",
    }),
    ("port_shares", "portfolio", {
        "en": "Shares", "zh": "股数", "zh-TW": "股數", "ja": "株数", "ko": "주수", "vi": "Số CP", "th": "จำนวนหุ้น", "ms": "Saham",
    }),
    ("port_avg_cost", "portfolio", {
        "en": "Avg Cost", "zh": "平均成本", "zh-TW": "平均成本", "ja": "平均コスト", "ko": "평균 단가", "vi": "Giá TB", "th": "ต้นทุนเฉลี่ย", "ms": "Kos Purata",
    }),
    ("port_current", "portfolio", {
        "en": "Current", "zh": "现价", "zh-TW": "現價", "ja": "現在値", "ko": "현재가", "vi": "Giá hiện tại", "th": "ราคาปัจจุบัน", "ms": "Semasa",
    }),
    ("port_pnl", "portfolio", {
        "en": "P&L", "zh": "盈亏", "zh-TW": "盈虧", "ja": "損益", "ko": "손익", "vi": "Lãi/Lỗ", "th": "กำไร/ขาดทุน", "ms": "U/R",
    }),
    ("port_pnl_pct", "portfolio", {
        "en": "P&L %", "zh": "盈亏%", "zh-TW": "盈虧%", "ja": "損益%", "ko": "손익%", "vi": "Lãi/Lỗ %", "th": "กำไร/ขาดทุน %", "ms": "U/R %",
    }),
    ("port_value", "portfolio", {
        "en": "Value", "zh": "市值", "zh-TW": "市值", "ja": "評価額", "ko": "가치", "vi": "Giá trị", "th": "มูลค่า", "ms": "Nilai",
    }),
    ("port_remove", "portfolio", {
        "en": "Remove", "zh": "删除", "zh-TW": "刪除", "ja": "削除", "ko": "삭제", "vi": "Xóa", "th": "ลบ", "ms": "Buang",
    }),
    ("port_empty", "portfolio", {
        "en": "No holdings yet. Click '+ Add Holding' to get started.",
        "zh": "暂无持仓。点击'+添加持仓'开始。",
        "zh-TW": "暫無持倉。點擊'+添加持倉'開始。",
        "ja": "まだ保有銘柄がありません。'+ 銘柄追加'で始めましょう。",
        "ko": "아직 보유 종목이 없습니다. '+ 종목 추가'를 클릭하세요.",
        "vi": "Chưa có danh mục. Nhấn '+ Thêm' để bắt đầu.",
        "th": "ยังไม่มีหุ้น กด '+ เพิ่มหุ้น' เพื่อเริ่มต้น",
        "ms": "Tiada pegangan lagi. Klik '+ Tambah' untuk mula.",
    }),
    ("port_history", "portfolio", {
        "en": "Portfolio History", "zh": "投资组合历史", "zh-TW": "投資組合歷史", "ja": "ポートフォリオ履歴", "ko": "포트폴리오 이력", "vi": "Lịch sử danh mục", "th": "ประวัติพอร์ต", "ms": "Sejarah Portfolio",
    }),
    ("port_date", "portfolio", {
        "en": "Date", "zh": "日期", "zh-TW": "日期", "ja": "日付", "ko": "날짜", "vi": "Ngày", "th": "วันที่", "ms": "Tarikh",
    }),
    ("port_daily_pnl", "portfolio", {
        "en": "Daily P&L", "zh": "当日盈亏", "zh-TW": "當日盈虧", "ja": "日次損益", "ko": "일간 손익", "vi": "Lãi/Lỗ ngày", "th": "กำไร/ขาดทุนรายวัน", "ms": "U/R Harian",
    }),
    ("port_benchmark", "portfolio", {
        "en": "S&P 500", "zh": "标普500", "zh-TW": "標普500", "ja": "S&P500", "ko": "S&P 500", "vi": "S&P 500", "th": "S&P 500", "ms": "S&P 500",
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
