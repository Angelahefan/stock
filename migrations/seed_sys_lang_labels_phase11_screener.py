#!/usr/bin/env python3
"""Phase 11 seed: Screener page i18n labels — page title, tab labels, filter labels,
table headers, signal chips, quality tiers, disclaimer, empty states.

~70 keys × 8 languages = ~560 rows.
"""
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
    # ── Page-level ──────────────────────────────────────────────────────────
    ("screener_title", "screener", {
        "en": "Stock Screener", "zh": "股票筛选器", "zh-TW": "股票篩選器",
        "ja": "株式スクリーナー", "ko": "주식 스크리너", "vi": "Bộ lọc cổ phiếu",
        "th": "ตัวกรองหุ้น", "ms": "Penapis Saham"}),
    ("screener_tab_technical", "screener", {
        "en": "Technical", "zh": "技术分析", "zh-TW": "技術分析",
        "ja": "テクニカル", "ko": "기술적 분석", "vi": "Kỹ thuật",
        "th": "เทคนิค", "ms": "Teknikal"}),
    ("screener_tab_fundamental", "screener", {
        "en": "Fundamental", "zh": "基本面", "zh-TW": "基本面",
        "ja": "ファンダメンタル", "ko": "기본적 분석", "vi": "Cơ bản",
        "th": "ปัจจัยพื้นฐาน", "ms": "Fundamental"}),

    # ── Shared filter labels ────────────────────────────────────────────────
    ("screener_filter_exchange", "screener", {
        "en": "Exchange", "zh": "交易所", "zh-TW": "交易所",
        "ja": "取引所", "ko": "거래소", "vi": "Sàn giao dịch",
        "th": "ตลาดหลักทรัพย์", "ms": "Bursa"}),
    ("screener_filter_any", "screener", {
        "en": "Any", "zh": "全部", "zh-TW": "全部",
        "ja": "すべて", "ko": "전체", "vi": "Tất cả",
        "th": "ทั้งหมด", "ms": "Semua"}),
    ("screener_btn_scanning", "screener", {
        "en": "Scanning…", "zh": "扫描中…", "zh-TW": "掃描中…",
        "ja": "スキャン中…", "ko": "스캔 중…", "vi": "Đang quét…",
        "th": "กำลังสแกน…", "ms": "Mengimbas…"}),
    ("screener_btn_screen", "screener", {
        "en": "Screen", "zh": "筛选", "zh-TW": "篩選",
        "ja": "スクリーニング", "ko": "스크리닝", "vi": "Lọc",
        "th": "คัดกรอง", "ms": "Tapis"}),
    ("screener_filter_min", "screener", {
        "en": "Min", "zh": "最小", "zh-TW": "最小",
        "ja": "最小", "ko": "최소", "vi": "Tối thiểu",
        "th": "ต่ำสุด", "ms": "Min"}),
    ("screener_filter_max", "screener", {
        "en": "Max", "zh": "最大", "zh-TW": "最大",
        "ja": "最大", "ko": "최대", "vi": "Tối đa",
        "th": "สูงสุด", "ms": "Maks"}),
    ("screener_filter_show", "screener", {
        "en": "Show", "zh": "显示", "zh-TW": "顯示",
        "ja": "表示", "ko": "표시", "vi": "Hiển thị",
        "th": "แสดง", "ms": "Papar"}),

    # ── Technical filter labels ─────────────────────────────────────────────
    ("screener_filter_price", "screener", {
        "en": "Price ($)", "zh": "价格 ($)", "zh-TW": "價格 ($)",
        "ja": "価格 ($)", "ko": "가격 ($)", "vi": "Giá ($)",
        "th": "ราคา ($)", "ms": "Harga ($)"}),
    ("screener_filter_rsi", "screener", {
        "en": "RSI (14)", "zh": "RSI (14)", "zh-TW": "RSI (14)",
        "ja": "RSI (14)", "ko": "RSI (14)", "vi": "RSI (14)",
        "th": "RSI (14)", "ms": "RSI (14)"}),
    ("screener_filter_macd", "screener", {
        "en": "MACD", "zh": "MACD", "zh-TW": "MACD",
        "ja": "MACD", "ko": "MACD", "vi": "MACD",
        "th": "MACD", "ms": "MACD"}),
    ("screener_filter_kdj", "screener", {
        "en": "KDJ", "zh": "KDJ", "zh-TW": "KDJ",
        "ja": "KDJ", "ko": "KDJ", "vi": "KDJ",
        "th": "KDJ", "ms": "KDJ"}),
    ("screener_filter_ma_cross", "screener", {
        "en": "MA Cross", "zh": "均线交叉", "zh-TW": "均線交叉",
        "ja": "MA クロス", "ko": "MA 크로스", "vi": "Giao cắt MA",
        "th": "MA Cross", "ms": "MA Cross"}),
    ("screener_filter_golden", "screener", {
        "en": "Golden", "zh": "金叉", "zh-TW": "金叉",
        "ja": "ゴールデン", "ko": "골든", "vi": "Golden",
        "th": "Golden", "ms": "Golden"}),
    ("screener_filter_death", "screener", {
        "en": "Death", "zh": "死叉", "zh-TW": "死叉",
        "ja": "デッド", "ko": "데드", "vi": "Death",
        "th": "Death", "ms": "Death"}),
    ("screener_filter_vol_ratio", "screener", {
        "en": "Vol ratio ≥", "zh": "成交量比 ≥", "zh-TW": "成交量比 ≥",
        "ja": "出来高比 ≥", "ko": "거래량 비율 ≥", "vi": "Tỷ lệ KL ≥",
        "th": "อัตราส่วนปริมาณ ≥", "ms": "Nisbah vol ≥"}),
    ("screener_filter_52w", "screener", {
        "en": "52w", "zh": "52周", "zh-TW": "52週",
        "ja": "52週", "ko": "52주", "vi": "52 tuần",
        "th": "52 สัปดาห์", "ms": "52 minggu"}),
    ("screener_filter_near_high", "screener", {
        "en": "Near High", "zh": "接近高点", "zh-TW": "接近高點",
        "ja": "高値付近", "ko": "고점 근처", "vi": "Gần đỉnh",
        "th": "ใกล้จุดสูงสุด", "ms": "Dekat Tinggi"}),
    ("screener_filter_near_low", "screener", {
        "en": "Near Low", "zh": "接近低点", "zh-TW": "接近低點",
        "ja": "安値付近", "ko": "저점 근처", "vi": "Gần đáy",
        "th": "ใกล้จุดต่ำสุด", "ms": "Dekat Rendah"}),

    # ── Filter dropdown values ──────────────────────────────────────────────
    ("screener_bullish", "screener", {
        "en": "Bullish", "zh": "看涨", "zh-TW": "看漲",
        "ja": "強気", "ko": "강세", "vi": "Tăng giá",
        "th": "ขาขึ้น", "ms": "Bullish"}),
    ("screener_bearish", "screener", {
        "en": "Bearish", "zh": "看跌", "zh-TW": "看跌",
        "ja": "弱気", "ko": "약세", "vi": "Giảm giá",
        "th": "ขาลง", "ms": "Bearish"}),
    ("screener_overbought", "screener", {
        "en": "Overbought", "zh": "超买", "zh-TW": "超買",
        "ja": "買われすぎ", "ko": "과매수", "vi": "Quá mua",
        "th": "ซื้อมากเกินไป", "ms": "Terlebih beli"}),
    ("screener_oversold", "screener", {
        "en": "Oversold", "zh": "超卖", "zh-TW": "超賣",
        "ja": "売られすぎ", "ko": "과매도", "vi": "Quá bán",
        "th": "ขายมากเกินไป", "ms": "Terlebih jual"}),
    ("screener_neutral", "screener", {
        "en": "Neutral", "zh": "中性", "zh-TW": "中性",
        "ja": "中立", "ko": "중립", "vi": "Trung lập",
        "th": "เป็นกลาง", "ms": "Neutral"}),

    # ── Results area text ───────────────────────────────────────────────────
    ("screener_scanning", "screener", {
        "en": "Scanning stocks…", "zh": "扫描股票中…", "zh-TW": "掃描股票中…",
        "ja": "株式をスキャン中…", "ko": "주식 스캔 중…", "vi": "Đang quét cổ phiếu…",
        "th": "กำลังสแกนหุ้น…", "ms": "Mengimbas saham…"}),
    ("screener_of", "screener", {
        "en": "of", "zh": "共", "zh-TW": "共",
        "ja": "/", "ko": "/", "vi": "trong",
        "th": "จาก", "ms": "daripada"}),
    ("screener_stocks", "screener", {
        "en": "stocks", "zh": "只股票", "zh-TW": "檔股票",
        "ja": "銘柄", "ko": "종목", "vi": "cổ phiếu",
        "th": "หุ้น", "ms": "saham"}),
    ("screener_filtered", "screener", {
        "en": "(filtered)", "zh": "(已筛选)", "zh-TW": "(已篩選)",
        "ja": "(フィルタ済)", "ko": "(필터됨)", "vi": "(đã lọc)",
        "th": "(กรองแล้ว)", "ms": "(ditapis)"}),
    ("screener_updated", "screener", {
        "en": "Updated", "zh": "更新于", "zh-TW": "更新於",
        "ja": "更新", "ko": "업데이트", "vi": "Cập nhật",
        "th": "อัปเดต", "ms": "Dikemas kini"}),
    ("screener_sort_tip", "screener", {
        "en": "Click column headers to sort", "zh": "点击列标题排序", "zh-TW": "點擊列標題排序",
        "ja": "列ヘッダーをクリックして並べ替え", "ko": "열 헤더를 클릭하여 정렬", "vi": "Nhấn tiêu đề cột để sắp xếp",
        "th": "คลิกหัวคอลัมน์เพื่อเรียงลำดับ", "ms": "Klik kepala lajur untuk isih"}),
    ("screener_no_match", "screener", {
        "en": "No stocks match your filters", "zh": "没有符合条件的股票", "zh-TW": "沒有符合條件的股票",
        "ja": "条件に一致する銘柄がありません", "ko": "필터에 맞는 종목이 없습니다", "vi": "Không có cổ phiếu phù hợp",
        "th": "ไม่มีหุ้นตรงตามเงื่อนไข", "ms": "Tiada saham sepadan dengan penapis"}),
    ("screener_no_match_hint", "screener", {
        "en": "Try relaxing the filters or switching exchange.", "zh": "尝试放宽筛选条件或更换交易所。", "zh-TW": "嘗試放寬篩選條件或更換交易所。",
        "ja": "フィルターを緩めるか、取引所を変更してみてください。", "ko": "필터를 완화하거나 거래소를 변경해 보세요.", "vi": "Thử nới lỏng bộ lọc hoặc đổi sàn giao dịch.",
        "th": "ลองปรับเงื่อนไขหรือเปลี่ยนตลาด", "ms": "Cuba longgarkan penapis atau tukar bursa."}),

    # ── Table headers (technical) ───────────────────────────────────────────
    ("screener_th_ticker", "screener", {
        "en": "Ticker", "zh": "代码", "zh-TW": "代碼",
        "ja": "銘柄", "ko": "종목", "vi": "Mã CK",
        "th": "สัญลักษณ์", "ms": "Simbol"}),
    ("screener_th_price", "screener", {
        "en": "Price", "zh": "价格", "zh-TW": "價格",
        "ja": "価格", "ko": "가격", "vi": "Giá",
        "th": "ราคา", "ms": "Harga"}),
    ("screener_th_days", "screener", {
        "en": "Days", "zh": "日", "zh-TW": "日",
        "ja": "日", "ko": "일", "vi": "Ngày",
        "th": "วัน", "ms": "Hari"}),
    ("screener_th_weeks", "screener", {
        "en": "Weeks", "zh": "周", "zh-TW": "週",
        "ja": "週", "ko": "주", "vi": "Tuần",
        "th": "สัปดาห์", "ms": "Minggu"}),
    ("screener_th_months", "screener", {
        "en": "Months", "zh": "月", "zh-TW": "月",
        "ja": "月", "ko": "월", "vi": "Tháng",
        "th": "เดือน", "ms": "Bulan"}),
    ("screener_th_quarter", "screener", {
        "en": "Quarter", "zh": "季", "zh-TW": "季",
        "ja": "四半期", "ko": "분기", "vi": "Quý",
        "th": "ไตรมาส", "ms": "Suku"}),
    ("screener_th_score", "screener", {
        "en": "Score", "zh": "评分", "zh-TW": "評分",
        "ja": "スコア", "ko": "점수", "vi": "Điểm",
        "th": "คะแนน", "ms": "Skor"}),
    ("screener_th_qual", "screener", {
        "en": "Qual", "zh": "质量", "zh-TW": "品質",
        "ja": "質", "ko": "품질", "vi": "Chất lượng",
        "th": "คุณภาพ", "ms": "Kualiti"}),
    ("screener_th_alert", "screener", {
        "en": "Alert", "zh": "警报", "zh-TW": "警報",
        "ja": "アラート", "ko": "알림", "vi": "Cảnh báo",
        "th": "แจ้งเตือน", "ms": "Amaran"}),
    ("screener_th_sector", "screener", {
        "en": "Sector", "zh": "板块", "zh-TW": "板塊",
        "ja": "セクター", "ko": "섹터", "vi": "Ngành",
        "th": "กลุ่มอุตสาหกรรม", "ms": "Sektor"}),
    ("screener_th_52w_high", "screener", {
        "en": "52w High", "zh": "52周高", "zh-TW": "52週高",
        "ja": "52週高値", "ko": "52주 고점", "vi": "Đỉnh 52T",
        "th": "สูงสุด 52w", "ms": "Tinggi 52m"}),
    ("screener_th_vol_ratio", "screener", {
        "en": "Vol Ratio", "zh": "量比", "zh-TW": "量比",
        "ja": "出来高比", "ko": "거래량 비율", "vi": "Tỷ lệ KL",
        "th": "อัตราส่วนปริมาณ", "ms": "Nisbah Vol"}),
    ("screener_th_volume", "screener", {
        "en": "Volume", "zh": "成交量", "zh-TW": "成交量",
        "ja": "出来高", "ko": "거래량", "vi": "Khối lượng",
        "th": "ปริมาณ", "ms": "Volum"}),
    ("screener_th_volatility", "screener", {
        "en": "Volatility", "zh": "波动率", "zh-TW": "波動率",
        "ja": "ボラティリティ", "ko": "변동성", "vi": "Biến động",
        "th": "ความผันผวน", "ms": "Volatiliti"}),
    ("screener_th_rsi_signal", "screener", {
        "en": "RSI Signal", "zh": "RSI信号", "zh-TW": "RSI信號",
        "ja": "RSIシグナル", "ko": "RSI 시그널", "vi": "RSI Tín hiệu",
        "th": "สัญญาณ RSI", "ms": "Isyarat RSI"}),
    ("screener_th_obv", "screener", {
        "en": "OBV", "zh": "OBV", "zh-TW": "OBV",
        "ja": "OBV", "ko": "OBV", "vi": "OBV",
        "th": "OBV", "ms": "OBV"}),

    # ── Signal chip labels (BUY/SELL/HOLD) ──────────────────────────────────
    ("signal_buy", "enum", {
        "en": "BUY", "zh": "买入", "zh-TW": "買入",
        "ja": "買い", "ko": "매수", "vi": "MUA",
        "th": "ซื้อ", "ms": "BELI"}),
    ("signal_sell", "enum", {
        "en": "SELL", "zh": "卖出", "zh-TW": "賣出",
        "ja": "売り", "ko": "매도", "vi": "BÁN",
        "th": "ขาย", "ms": "JUAL"}),
    ("signal_hold", "enum", {
        "en": "HOLD", "zh": "持有", "zh-TW": "持有",
        "ja": "保有", "ko": "보유", "vi": "GIỮ",
        "th": "ถือ", "ms": "PEGANG"}),
    ("signal_strong_buy", "enum", {
        "en": "STRONG BUY", "zh": "强烈买入", "zh-TW": "強烈買入",
        "ja": "強い買い", "ko": "강력 매수", "vi": "MUA MẠNH",
        "th": "ซื้อแนะนำ", "ms": "BELI KUAT"}),
    ("signal_strong_sell", "enum", {
        "en": "STRONG SELL", "zh": "强烈卖出", "zh-TW": "強烈賣出",
        "ja": "強い売り", "ko": "강력 매도", "vi": "BÁN MẠNH",
        "th": "ขายแนะนำ", "ms": "JUAL KUAT"}),

    # ── Trend / TA chip labels ──────────────────────────────────────────────
    ("signal_bullish_chip", "enum", {
        "en": "BULLISH", "zh": "看涨", "zh-TW": "看漲",
        "ja": "強気", "ko": "강세", "vi": "TĂNG",
        "th": "ขาขึ้น", "ms": "BULLISH"}),
    ("signal_bearish_chip", "enum", {
        "en": "BEARISH", "zh": "看跌", "zh-TW": "看跌",
        "ja": "弱気", "ko": "약세", "vi": "GIẢM",
        "th": "ขาลง", "ms": "BEARISH"}),
    ("signal_flat_chip", "enum", {
        "en": "FLAT", "zh": "持平", "zh-TW": "持平",
        "ja": "横ばい", "ko": "보합", "vi": "ĐI NGANG",
        "th": "ทรงตัว", "ms": "MENDATAR"}),
    ("signal_overbought_chip", "enum", {
        "en": "OVERBOUGHT", "zh": "超买", "zh-TW": "超買",
        "ja": "買われすぎ", "ko": "과매수", "vi": "QUÁ MUA",
        "th": "ซื้อมากเกินไป", "ms": "TERLEBIH BELI"}),
    ("signal_oversold_chip", "enum", {
        "en": "OVERSOLD", "zh": "超卖", "zh-TW": "超賣",
        "ja": "売られすぎ", "ko": "과매도", "vi": "QUÁ BÁN",
        "th": "ขายมากเกินไป", "ms": "TERLEBIH JUAL"}),
    ("signal_neutral_chip", "enum", {
        "en": "NEUTRAL", "zh": "中性", "zh-TW": "中性",
        "ja": "中立", "ko": "중립", "vi": "TRUNG LẬP",
        "th": "เป็นกลาง", "ms": "NEUTRAL"}),
    ("signal_up_chip", "enum", {
        "en": "UP", "zh": "上涨", "zh-TW": "上漲",
        "ja": "上昇", "ko": "상승", "vi": "TĂNG",
        "th": "ขึ้น", "ms": "NAIK"}),
    ("signal_down_chip", "enum", {
        "en": "DOWN", "zh": "下跌", "zh-TW": "下跌",
        "ja": "下落", "ko": "하락", "vi": "GIẢM",
        "th": "ลง", "ms": "TURUN"}),

    # ── SMA cross chips ─────────────────────────────────────────────────────
    ("sma_bull", "screener", {
        "en": "▲ Bull", "zh": "▲ 多", "zh-TW": "▲ 多",
        "ja": "▲ 強気", "ko": "▲ 강세", "vi": "▲ Tăng",
        "th": "▲ ขึ้น", "ms": "▲ Bull"}),
    ("sma_bear", "screener", {
        "en": "▼ Bear", "zh": "▼ 空", "zh-TW": "▼ 空",
        "ja": "▼ 弱気", "ko": "▼ 약세", "vi": "▼ Giảm",
        "th": "▼ ลง", "ms": "▼ Bear"}),

    # ── Quality tier labels ─────────────────────────────────────────────────
    ("quality_excellent", "screener", {
        "en": "Excellent", "zh": "优秀", "zh-TW": "優秀",
        "ja": "優良", "ko": "우수", "vi": "Xuất sắc",
        "th": "ยอดเยี่ยม", "ms": "Cemerlang"}),
    ("quality_good", "screener", {
        "en": "Good", "zh": "良好", "zh-TW": "良好",
        "ja": "良い", "ko": "양호", "vi": "Tốt",
        "th": "ดี", "ms": "Baik"}),
    ("quality_fair", "screener", {
        "en": "Fair", "zh": "一般", "zh-TW": "一般",
        "ja": "普通", "ko": "보통", "vi": "Trung bình",
        "th": "พอใช้", "ms": "Sederhana"}),
    ("quality_poor", "screener", {
        "en": "Poor", "zh": "较差", "zh-TW": "較差",
        "ja": "不良", "ko": "불량", "vi": "Kém",
        "th": "ต่ำ", "ms": "Lemah"}),

    # ── Fundamental tab labels ──────────────────────────────────────────────
    ("screener_fund_ai_signal", "screener", {
        "en": "AI Signal", "zh": "AI信号", "zh-TW": "AI信號",
        "ja": "AIシグナル", "ko": "AI 시그널", "vi": "Tín hiệu AI",
        "th": "สัญญาณ AI", "ms": "Isyarat AI"}),
    ("screener_fund_sector", "screener", {
        "en": "Sector", "zh": "板块", "zh-TW": "板塊",
        "ja": "セクター", "ko": "섹터", "vi": "Ngành",
        "th": "กลุ่มอุตสาหกรรม", "ms": "Sektor"}),
    ("screener_fund_min_score", "screener", {
        "en": "Min Score", "zh": "最低评分", "zh-TW": "最低評分",
        "ja": "最低スコア", "ko": "최소 점수", "vi": "Điểm tối thiểu",
        "th": "คะแนนขั้นต่ำ", "ms": "Skor Minimum"}),
    ("screener_fund_all", "screener", {
        "en": "All", "zh": "全部", "zh-TW": "全部",
        "ja": "すべて", "ko": "전체", "vi": "Tất cả",
        "th": "ทั้งหมด", "ms": "Semua"}),
    ("screener_fund_all_sectors", "screener", {
        "en": "All sectors", "zh": "所有板块", "zh-TW": "所有板塊",
        "ja": "全セクター", "ko": "전체 섹터", "vi": "Tất cả ngành",
        "th": "ทุกกลุ่มอุตสาหกรรม", "ms": "Semua sektor"}),

    # ── Fundamental table headers ───────────────────────────────────────────
    ("screener_th_company", "screener", {
        "en": "Company", "zh": "公司", "zh-TW": "公司",
        "ja": "企業", "ko": "회사", "vi": "Công ty",
        "th": "บริษัท", "ms": "Syarikat"}),
    ("screener_th_signal", "screener", {
        "en": "Signal", "zh": "信号", "zh-TW": "信號",
        "ja": "シグナル", "ko": "시그널", "vi": "Tín hiệu",
        "th": "สัญญาณ", "ms": "Isyarat"}),
    ("screener_th_val", "screener", {
        "en": "Val", "zh": "估值", "zh-TW": "估值",
        "ja": "バリュエーション", "ko": "밸류에이션", "vi": "Định giá",
        "th": "มูลค่า", "ms": "Nilai"}),
    ("screener_th_growth", "screener", {
        "en": "Growth", "zh": "增长", "zh-TW": "增長",
        "ja": "成長", "ko": "성장", "vi": "Tăng trưởng",
        "th": "การเติบโต", "ms": "Pertumbuhan"}),
    ("screener_th_macro", "screener", {
        "en": "Macro", "zh": "宏观", "zh-TW": "宏觀",
        "ja": "マクロ", "ko": "매크로", "vi": "Vĩ mô",
        "th": "มหภาค", "ms": "Makro"}),
    ("screener_th_analyst", "screener", {
        "en": "Analyst", "zh": "分析师", "zh-TW": "分析師",
        "ja": "アナリスト", "ko": "애널리스트", "vi": "Phân tích",
        "th": "นักวิเคราะห์", "ms": "Penganalisis"}),
    ("screener_th_upside", "screener", {
        "en": "Upside", "zh": "上涨空间", "zh-TW": "上漲空間",
        "ja": "上昇余地", "ko": "상승 여력", "vi": "Tiềm năng tăng",
        "th": "โอกาสขึ้น", "ms": "Potensi Naik"}),

    # ── Backtest section ────────────────────────────────────────────────────
    ("screener_backtest_title", "screener", {
        "en": "Signal Backtest Results & Methodology", "zh": "信号回测结果与方法论", "zh-TW": "信號回測結果與方法論",
        "ja": "シグナルバックテスト結果と手法", "ko": "시그널 백테스트 결과 및 방법론", "vi": "Kết quả backtest tín hiệu & Phương pháp",
        "th": "ผลการทดสอบย้อนหลังสัญญาณ & วิธีการ", "ms": "Keputusan Backtest Isyarat & Metodologi"}),

    # ── Disclaimer ──────────────────────────────────────────────────────────
    ("screener_disclaimer", "screener", {
        "en": "Technical indicators pre-computed nightly from price data. Not financial advice.",
        "zh": "技术指标基于价格数据每日预计算。本内容不构成投资建议。",
        "zh-TW": "技術指標基於價格數據每日預計算。本內容不構成投資建議。",
        "ja": "テクニカル指標は価格データから毎晩事前計算されます。投資助言ではありません。",
        "ko": "기술 지표는 매일 밤 가격 데이터에서 사전 계산됩니다. 투자 조언이 아닙니다.",
        "vi": "Các chỉ báo kỹ thuật được tính toán hàng đêm từ dữ liệu giá. Không phải lời khuyên đầu tư.",
        "th": "ตัวชี้วัดทางเทคนิคคำนวณล่วงหน้าทุกคืนจากข้อมูลราคา ไม่ใช่คำแนะนำการลงทุน",
        "ms": "Penunjuk teknikal dikira setiap malam daripada data harga. Bukan nasihat kewangan."}),

    # ── No-results (fundamental tab) ────────────────────────────────────────
    ("screener_fund_no_match", "screener", {
        "en": "No stocks match filters. Try relaxing criteria.",
        "zh": "没有符合条件的股票。尝试放宽条件。",
        "zh-TW": "沒有符合條件的股票。嘗試放寬條件。",
        "ja": "条件に一致する銘柄がありません。条件を緩めてください。",
        "ko": "필터에 맞는 종목이 없습니다. 조건을 완화해 보세요.",
        "vi": "Không có cổ phiếu phù hợp. Thử nới lỏng điều kiện.",
        "th": "ไม่มีหุ้นตรงตามเงื่อนไข ลองปรับเกณฑ์ใหม่",
        "ms": "Tiada saham sepadan. Cuba longgarkan kriteria."}),
]
# fmt: on

rows = []
for key, cat, trans in LABELS:
    for lang, text in trans.items():
        rows.append((key, lang, text, cat))

print(f"Seeding {len(rows)} rows ({len(LABELS)} keys × 8 langs)...")
with conn.cursor() as cur:
    psycopg2.extras.execute_values(
        cur,
        """INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES %s
           ON CONFLICT (label_key, lang)
           DO UPDATE SET text = EXCLUDED.text, category = EXCLUDED.category, updated_at = NOW()""",
        rows,
        template="(%s, %s, %s, %s)",
    )
    conn.commit()
    print(f"Upserted {cur.rowcount} rows.")
    cur.execute("SELECT COUNT(*) FROM datapai.sys_lang_labels")
    print(f"Total labels in DB: {cur.fetchone()[0]}")
conn.close()
print("Done.")
