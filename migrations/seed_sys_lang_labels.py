#!/usr/bin/env python3
"""Seed datapai.sys_lang_labels with all UI translations for 8 languages."""
import psycopg2
import psycopg2.extras
import os

conn = psycopg2.connect(
    host=os.environ.get('PGHOST', 'localhost'),
    port=int(os.environ.get('PGPORT', '5432')),
    dbname='postgres',
    user=os.environ.get('PGUSER', 'postgres'),
    password=os.environ.get('PGPASSWORD', 'postgres'),
)

# All translations: (label_key, category, {lang: text})
LABELS = [
    # ── Navigation ──
    ("nav_usStocks", "nav", {"en": "🇺🇸 US Stocks", "zh": "🇺🇸 美股", "zh-TW": "🇺🇸 美股", "ja": "🇺🇸 米国株", "ko": "🇺🇸 미국주식", "vi": "🇺🇸 Cổ phiếu Mỹ", "th": "🇺🇸 หุ้นสหรัฐ", "ms": "🇺🇸 Saham AS"}),
    ("nav_asx", "nav", {"en": "🇦🇺 Australian Stocks", "zh": "🇦🇺 澳股", "zh-TW": "🇦🇺 澳股", "ja": "🇦🇺 豪州株", "ko": "🇦🇺 호주주식", "vi": "🇦🇺 Cổ phiếu Úc", "th": "🇦🇺 หุ้นออสเตรเลีย", "ms": "🇦🇺 Saham Australia"}),
    ("nav_vietnam", "nav", {"en": "🇻🇳 Vietnamese Stocks", "zh": "🇻🇳 越南股", "zh-TW": "🇻🇳 越南股", "ja": "🇻🇳 ベトナム株", "ko": "🇻🇳 베트남주식", "vi": "🇻🇳 Cổ phiếu Việt Nam", "th": "🇻🇳 หุ้นเวียดนาม", "ms": "🇻🇳 Saham Vietnam"}),
    ("nav_alerts", "nav", {"en": "Alerts", "zh": "预警", "zh-TW": "預警", "ja": "アラート", "ko": "알림", "vi": "Cảnh báo", "th": "แจ้งเตือน", "ms": "Amaran"}),
    ("nav_watchlist", "nav", {"en": "Watchlist", "zh": "自选股", "zh-TW": "自選股", "ja": "ウォッチリスト", "ko": "관심종목", "vi": "Danh mục", "th": "รายการจับตา", "ms": "Senarai Pantau"}),
    ("nav_aiAnalysis", "nav", {"en": "AI Analysis", "zh": "AI分析", "zh-TW": "AI分析", "ja": "AI分析", "ko": "AI분석", "vi": "Phân tích AI", "th": "AI วิเคราะห์", "ms": "Analisis AI"}),
    ("nav_pricing", "nav", {"en": "Pricing", "zh": "定价", "zh-TW": "定價", "ja": "料金", "ko": "가격", "vi": "Bảng giá", "th": "ราคา", "ms": "Harga"}),
    ("nav_login", "nav", {"en": "Log in", "zh": "登录", "zh-TW": "登入", "ja": "ログイン", "ko": "로그인", "vi": "Đăng nhập", "th": "เข้าสู่ระบบ", "ms": "Log Masuk"}),
    ("nav_indexes", "nav", {"en": "Indexes", "zh": "指数", "zh-TW": "指數", "ja": "指数", "ko": "지수", "vi": "Chỉ số", "th": "ดัชนี", "ms": "Indeks"}),
    ("nav_screener", "nav", {"en": "Screener", "zh": "筛选器", "zh-TW": "篩選器", "ja": "スクリーナー", "ko": "스크리너", "vi": "Bộ lọc", "th": "ตัวกรอง", "ms": "Penyaring"}),

    # ── Hero sections ──
    ("hero_title_us", "hero", {"en": "US Stocks · Website Change Intelligence", "zh": "美股 · 网站变动情报", "zh-TW": "美股 · 網站變動情報", "ja": "米国株 · ウェブサイト変更インテリジェンス", "ko": "미국 주식 · 웹사이트 변경 인텔리전스", "vi": "Cổ phiếu Mỹ · Phân tích thay đổi website", "th": "หุ้นสหรัฐ · ข่าวกรองการเปลี่ยนแปลงเว็บไซต์", "ms": "Saham AS · Perisikan Perubahan Laman Web"}),
    ("hero_title_asx", "hero", {"en": "Australian Stocks · Company Intelligence", "zh": "澳股 · 公司情报", "zh-TW": "澳股 · 公司情報", "ja": "豪州株 · 企業インテリジェンス", "ko": "호주 주식 · 기업 인텔리전스", "vi": "Cổ phiếu Úc · Phân tích doanh nghiệp", "th": "หุ้นออสเตรเลีย · ข่าวกรองบริษัท", "ms": "Saham Australia · Perisikan Syarikat"}),
    ("hero_title_vn", "hero", {"en": "Vietnamese Stocks · Market Intelligence", "zh": "越南股 · 市场情报", "zh-TW": "越南股 · 市場情報", "ja": "ベトナム株 · 市場インテリジェンス", "ko": "베트남 주식 · 시장 인텔리전스", "vi": "Cổ phiếu Việt Nam · Phân tích thị trường", "th": "หุ้นเวียดนาม · ข่าวกรองตลาด", "ms": "Saham Vietnam · Perisikan Pasaran"}),
    ("hero_desc", "hero", {"en": "Spot language shifts on company websites before they move stock prices", "zh": "在股价变动前发现公司网站的语言变化", "zh-TW": "在股價變動前發現公司網站的語言變化", "ja": "株価変動前に企業サイトの言葉の変化を検出", "ko": "주가 변동 전 기업 웹사이트의 언어 변화를 포착", "vi": "Phát hiện thay đổi ngôn ngữ trên website công ty trước khi giá cổ phiếu biến động", "th": "ตรวจจับการเปลี่ยนแปลงภาษาบนเว็บไซต์บริษัทก่อนราคาหุ้นจะเคลื่อนไหว", "ms": "Kesan perubahan bahasa di laman web syarikat sebelum harga saham bergerak"}),
    ("hero_stocks_covered", "hero", {"en": "stocks covered", "zh": "只股票覆盖", "zh-TW": "隻股票覆蓋", "ja": "銘柄カバー", "ko": "종목 커버", "vi": "cổ phiếu được theo dõi", "th": "หุ้นที่ครอบคลุม", "ms": "saham diliputi"}),
    ("hero_powered_by", "hero", {"en": "powered by", "zh": "技术驱动", "zh-TW": "技術驅動", "ja": "提供元", "ko": "제공", "vi": "được hỗ trợ bởi", "th": "ขับเคลื่อนโดย", "ms": "dikuasakan oleh"}),
    ("hero_view_alerts", "hero", {"en": "View Alerts", "zh": "查看预警", "zh-TW": "查看預警", "ja": "アラートを見る", "ko": "알림 보기", "vi": "Xem cảnh báo", "th": "ดูการแจ้งเตือน", "ms": "Lihat Amaran"}),

    # ── Monitored Universe ──
    ("section_monitored", "section", {"en": "Monitored Universe", "zh": "监控范围", "zh-TW": "監控範圍", "ja": "モニタリング対象", "ko": "모니터링 대상", "vi": "Danh mục theo dõi", "th": "กลุ่มหุ้นที่ติดตาม", "ms": "Semesta Pantauan"}),
    ("section_us_market", "section", {"en": "US Markets", "zh": "美国市场", "zh-TW": "美國市場", "ja": "米国市場", "ko": "미국 시장", "vi": "Thị trường Mỹ", "th": "ตลาดสหรัฐ", "ms": "Pasaran AS"}),
    ("section_asx_market", "section", {"en": "Australian Securities Exchange", "zh": "澳大利亚证券交易所", "zh-TW": "澳大利亞證券交易所", "ja": "オーストラリア証券取引所", "ko": "호주 증권 거래소", "vi": "Sàn chứng khoán Úc", "th": "ตลาดหลักทรัพย์ออสเตรเลีย", "ms": "Bursa Sekuriti Australia"}),
    ("section_vn_market", "section", {"en": "Ho Chi Minh & Hanoi Stock Exchange", "zh": "胡志明与河内证券交易所", "zh-TW": "胡志明與河內證券交易所", "ja": "ホーチミン＆ハノイ証券取引所", "ko": "호치민 & 하노이 증권거래소", "vi": "Sở GDCK TP.HCM & Hà Nội", "th": "ตลาดหลักทรัพย์โฮจิมินห์และฮานอย", "ms": "Bursa Saham Ho Chi Minh & Hanoi"}),
    ("section_top_stocks", "section", {"en": "Top Stocks", "zh": "热门股票", "zh-TW": "熱門股票", "ja": "注目銘柄", "ko": "인기 종목", "vi": "Cổ phiếu nổi bật", "th": "หุ้นยอดนิยม", "ms": "Saham Teratas"}),

    # ── How It Works ──
    ("how_it_works", "howItWorks", {"en": "How It Works", "zh": "工作原理", "zh-TW": "工作原理", "ja": "仕組み", "ko": "작동 방식", "vi": "Cách hoạt động", "th": "วิธีการทำงาน", "ms": "Cara Ia Berfungsi"}),
    ("step1_label", "howItWorks", {"en": "Fetches", "zh": "抓取", "zh-TW": "抓取", "ja": "取得", "ko": "수집", "vi": "Thu thập", "th": "ดึงข้อมูล", "ms": "Mengambil"}),
    ("step1_desc", "howItWorks", {"en": "Real browser rendering of JavaScript-heavy investor pages — no scraping shortcuts", "zh": "使用真实浏览器渲染JS重型投资者页面——无抓取捷径", "zh-TW": "使用真實瀏覽器渲染JS頁面——無抓取捷徑", "ja": "JS投資家ページの実ブラウザレンダリング——スクレイピング不使用", "ko": "JS 투자자 페이지의 실제 브라우저 렌더링", "vi": "Duyệt thực tế trang nhà đầu tư JS — không dùng phím tắt", "th": "เรนเดอร์เบราว์เซอร์จริงของหน้าเว็บนักลงทุน — ไม่ใช้ทางลัด", "ms": "Pelayar sebenar untuk halaman pelabur JS — tanpa pintasan"}),
    ("step2_label", "howItWorks", {"en": "Cleans", "zh": "清洗", "zh-TW": "清洗", "ja": "クリーニング", "ko": "정제", "vi": "Làm sạch", "th": "ทำความสะอาด", "ms": "Membersih"}),
    ("step2_desc", "howItWorks", {"en": "Removes nav/footer noise, hashes content, stores versioned snapshots in Postgres", "zh": "去除导航/页脚噪音，哈希内容，在Postgres中存储版本快照", "zh-TW": "去除導航/頁腳雜訊，雜湊內容，在Postgres中存儲版本快照", "ja": "ナビ/フッターノイズを除去、ハッシュ化、Postgresにバージョン管理", "ko": "nav/footer 노이즈 제거, 콘텐츠 해시, Postgres에 버전 스냅샷 저장", "vi": "Loại bỏ nhiễu nav/footer, hash nội dung, lưu trữ phiên bản trong Postgres", "th": "ลบส่วนที่ไม่จำเป็น แฮชเนื้อหา เก็บสแนปช็อตเวอร์ชันใน Postgres", "ms": "Buang bunyi bising nav/footer, hash kandungan, simpan syot kilat versi dalam Postgres"}),
    ("step3_label", "howItWorks", {"en": "Diff & Score", "zh": "差异与评分", "zh-TW": "差異與評分", "ja": "差分＆スコアリング", "ko": "차이 분석 & 점수", "vi": "So sánh & Chấm điểm", "th": "เปรียบเทียบและให้คะแนน", "ms": "Beza & Skor"}),
    ("step3_desc", "howItWorks", {"en": "Text diff detects wording shifts. Word-list scores measure commitment/hedging/risk", "zh": "文本差异检测措辞变化。词表评分衡量承诺/对冲/风险", "zh-TW": "文本差異檢測措辭變化。詞表評分衡量承諾/對沖/風險", "ja": "テキスト差分で言葉の変化を検出。ワードリストスコアで確約/ヘッジ/リスクを測定", "ko": "텍스트 차이로 표현 변화 감지. 단어 목록 점수로 확약/헤지/리스크 측정", "vi": "So sánh văn bản phát hiện thay đổi từ ngữ. Điểm danh sách từ đo lường cam kết/phòng hộ/rủi ro", "th": "ตรวจจับการเปลี่ยนแปลงคำพูดด้วยการเปรียบเทียบข้อความ", "ms": "Perbezaan teks mengesan perubahan perkataan. Skor senarai perkataan mengukur komitmen/lindung nilai/risiko"}),
    ("step4_label", "howItWorks", {"en": "AI Signal", "zh": "AI信号", "zh-TW": "AI信號", "ja": "AIシグナル", "ko": "AI 신호", "vi": "Tín hiệu AI", "th": "สัญญาณ AI", "ms": "Isyarat AI"}),
    ("step4_desc", "howItWorks", {"en": "AI summary with direct quotes, confidence score, and price chart context", "zh": "AI摘要，含直接引用、置信度评分和价格图表上下文", "zh-TW": "AI摘要，含直接引用、置信度評分和價格圖表上下文", "ja": "AI要約（直接引用・信頼度スコア・チャートコンテキスト）", "ko": "AI 요약, 직접 인용, 신뢰도 점수 및 가격 차트 컨텍스트", "vi": "Tóm tắt AI với trích dẫn trực tiếp, điểm tin cậy và biểu đồ giá", "th": "สรุป AI พร้อมคำพูดอ้างอิง คะแนนความเชื่อมั่น และบริบทกราฟราคา", "ms": "Ringkasan AI dengan petikan langsung, skor keyakinan dan konteks carta harga"}),

    # ── Trust Layer ──
    ("trust_title", "trust", {"en": "Trust Layer — every alert is fully reproducible", "zh": "信任层——每个预警均可完全复现", "zh-TW": "信任層——每個預警均可完全複現", "ja": "信頼レイヤー — すべてのアラートは完全に再現可能", "ko": "신뢰 계층 — 모든 알림은 완전히 재현 가능", "vi": "Lớp tin cậy — mọi cảnh báo đều có thể tái tạo", "th": "ชั้นความเชื่อถือ — ทุกการแจ้งเตือนสามารถทำซ้ำได้", "ms": "Lapisan Kepercayaan — setiap amaran boleh dihasilkan semula"}),
    ("trust_source", "trust", {"en": "Source & Audit", "zh": "来源与审计", "zh-TW": "來源與審計", "ja": "ソース＆監査", "ko": "소스 & 감사", "vi": "Nguồn & Kiểm toán", "th": "แหล่งที่มาและการตรวจสอบ", "ms": "Sumber & Audit"}),
    ("trust_source_desc", "trust", {"en": "Source URL · Snapshot hash · TinyFish run ID · Scan timestamp", "zh": "来源URL · 快照哈希 · TinyFish运行ID · 扫描时间戳", "zh-TW": "來源URL · 快照雜湊 · TinyFish運行ID · 掃描時間戳", "ja": "ソースURL・スナップショットハッシュ・実行ID・スキャンタイムスタンプ", "ko": "소스 URL · 스냅샷 해시 · 실행 ID · 스캔 타임스탬프", "vi": "URL nguồn · Mã hash · ID chạy TinyFish · Thời gian quét", "th": "URL ต้นทาง · แฮชสแนปช็อต · ID การรัน · เวลาสแกน", "ms": "URL sumber · Hash syot kilat · ID larian · Cap masa imbasan"}),
    ("trust_evidence", "trust", {"en": "Evidence", "zh": "证据", "zh-TW": "證據", "ja": "証拠", "ko": "증거", "vi": "Bằng chứng", "th": "หลักฐาน", "ms": "Bukti"}),
    ("trust_evidence_desc", "trust", {"en": "Before/after text · Diff snippet · Direct quotes from changed lines", "zh": "变更前后文本 · 差异片段 · 变更行直接引用", "zh-TW": "變更前後文本 · 差異片段 · 變更行直接引用", "ja": "変更前後テキスト・差分スニペット・変更行の直接引用", "ko": "변경 전후 텍스트 · 차이 스니펫 · 변경된 행의 직접 인용", "vi": "Văn bản trước/sau · Đoạn khác biệt · Trích dẫn trực tiếp từ dòng thay đổi", "th": "ข้อความก่อน/หลัง · สรุปความแตกต่าง · อ้างอิงจากบรรทัดที่เปลี่ยน", "ms": "Teks sebelum/selepas · Petikan perbezaan · Petikan langsung dari baris berubah"}),
    ("trust_ai", "trust", {"en": "AI Layer", "zh": "AI层", "zh-TW": "AI層", "ja": "AIレイヤー", "ko": "AI 계층", "vi": "Lớp AI", "th": "ชั้น AI", "ms": "Lapisan AI"}),
    ("trust_ai_desc", "trust", {"en": "Paid LLM summary · Signal classification · Confidence score", "zh": "付费LLM摘要 · 信号分类 · 置信度评分", "zh-TW": "付費LLM摘要 · 信號分類 · 置信度評分", "ja": "有料LLM要約・シグナル分類・信頼度スコア", "ko": "유료 LLM 요약 · 신호 분류 · 신뢰도 점수", "vi": "Tóm tắt LLM · Phân loại tín hiệu · Điểm tin cậy", "th": "สรุป LLM · การจำแนกสัญญาณ · คะแนนความเชื่อมั่น", "ms": "Ringkasan LLM · Klasifikasi isyarat · Skor keyakinan"}),

    # ── Stock card / table headers ──
    ("price", "stock", {"en": "Price", "zh": "价格", "zh-TW": "價格", "ja": "価格", "ko": "가격", "vi": "Giá", "th": "ราคา", "ms": "Harga"}),
    ("change_pct_label", "stock", {"en": "Change %", "zh": "涨跌幅", "zh-TW": "漲跌幅", "ja": "変動率", "ko": "등락률", "vi": "% Thay đổi", "th": "% เปลี่ยนแปลง", "ms": "% Perubahan"}),
    ("date_label", "stock", {"en": "Date", "zh": "日期", "zh-TW": "日期", "ja": "日付", "ko": "날짜", "vi": "Ngày", "th": "วันที่", "ms": "Tarikh"}),
    ("ticker_label", "stock", {"en": "Ticker", "zh": "代码", "zh-TW": "代碼", "ja": "ティッカー", "ko": "티커", "vi": "Mã CK", "th": "รหัสหุ้น", "ms": "Ticker"}),
    ("name_label", "stock", {"en": "Name", "zh": "名称", "zh-TW": "名稱", "ja": "名称", "ko": "이름", "vi": "Tên", "th": "ชื่อ", "ms": "Nama"}),
    ("volume_label", "stock", {"en": "Volume", "zh": "成交量", "zh-TW": "成交量", "ja": "出来高", "ko": "거래량", "vi": "Khối lượng", "th": "ปริมาณ", "ms": "Jumlah dagangan"}),
    ("market_cap_label", "stock", {"en": "Market Cap", "zh": "市值", "zh-TW": "市值", "ja": "時価総額", "ko": "시가총액", "vi": "Vốn hóa", "th": "มูลค่าตลาด", "ms": "Permodalan pasaran"}),
    ("no_price_data", "stock", {"en": "No price data", "zh": "暂无价格", "zh-TW": "暫無價格", "ja": "価格データなし", "ko": "가격 데이터 없음", "vi": "Chưa có giá", "th": "ไม่มีข้อมูลราคา", "ms": "Tiada data harga"}),
    ("baseline_saved", "stock", {"en": "Baseline saved", "zh": "基线已保存", "zh-TW": "基線已保存", "ja": "ベースライン保存済み", "ko": "기준선 저장됨", "vi": "Đã lưu cơ sở", "th": "บันทึกข้อมูลฐานแล้ว", "ms": "Garis asas disimpan"}),
    ("significant_change", "stock", {"en": "Significant change", "zh": "重大变化", "zh-TW": "重大變化", "ja": "重大な変化", "ko": "중요한 변화", "vi": "Thay đổi đáng kể", "th": "การเปลี่ยนแปลงสำคัญ", "ms": "Perubahan ketara"}),
    ("not_yet_scanned", "stock", {"en": "Not yet scanned", "zh": "尚未扫描", "zh-TW": "尚未掃描", "ja": "未スキャン", "ko": "아직 스캔되지 않음", "vi": "Chưa quét", "th": "ยังไม่ได้สแกน", "ms": "Belum diimbas"}),
    ("change_detected", "stock", {"en": "change detected", "zh": "检测到变化", "zh-TW": "檢測到變化", "ja": "変化を検出", "ko": "변경 감지", "vi": "phát hiện thay đổi", "th": "ตรวจพบการเปลี่ยนแปลง", "ms": "perubahan dikesan"}),
    ("confidence_label", "stock", {"en": "conf", "zh": "置信度", "zh-TW": "置信度", "ja": "確度", "ko": "신뢰도", "vi": "độ tin cậy", "th": "ความเชื่อมั่น", "ms": "keyakinan"}),

    # ── Last scan summary ──
    ("last_scan", "scan", {"en": "Last scan", "zh": "最近扫描", "zh-TW": "最近掃描", "ja": "最終スキャン", "ko": "마지막 스캔", "vi": "Quét gần nhất", "th": "สแกนล่าสุด", "ms": "Imbasan terakhir"}),
    ("scanned", "scan", {"en": "scanned", "zh": "已扫描", "zh-TW": "已掃描", "ja": "スキャン済み", "ko": "스캔됨", "vi": "đã quét", "th": "สแกนแล้ว", "ms": "diimbas"}),
    ("changed", "scan", {"en": "changed", "zh": "有变化", "zh-TW": "有變化", "ja": "変更あり", "ko": "변경됨", "vi": "thay đổi", "th": "เปลี่ยนแปลง", "ms": "berubah"}),
    ("failed", "scan", {"en": "failed", "zh": "失败", "zh-TW": "失敗", "ja": "失敗", "ko": "실패", "vi": "thất bại", "th": "ล้มเหลว", "ms": "gagal"}),
    ("view_run_detail", "scan", {"en": "View run detail", "zh": "查看运行详情", "zh-TW": "查看運行詳情", "ja": "実行詳細を見る", "ko": "실행 상세 보기", "vi": "Xem chi tiết", "th": "ดูรายละเอียดการรัน", "ms": "Lihat butiran larian"}),
    ("view_all_alerts", "scan", {"en": "View all alerts", "zh": "查看全部预警", "zh-TW": "查看全部預警", "ja": "すべてのアラートを見る", "ko": "모든 알림 보기", "vi": "Xem tất cả cảnh báo", "th": "ดูการแจ้งเตือนทั้งหมด", "ms": "Lihat semua amaran"}),

    # ── Index page ──
    ("indexes_title", "index", {"en": "Global Market Indexes", "zh": "全球市场指数", "zh-TW": "全球市場指數", "ja": "グローバル市場指数", "ko": "글로벌 시장 지수", "vi": "Chỉ số thị trường toàn cầu", "th": "ดัชนีตลาดโลก", "ms": "Indeks Pasaran Global"}),
    ("indexes_desc", "index", {"en": "Real-time global market overview — updated every 20 minutes during trading hours", "zh": "实时全球市场概览——交易时段每20分钟更新", "zh-TW": "即時全球市場概覽——交易時段每20分鐘更新", "ja": "リアルタイム グローバル市場概要 — 取引時間中20分毎に更新", "ko": "실시간 글로벌 시장 개요 — 거래 시간 중 20분마다 업데이트", "vi": "Tổng quan thị trường toàn cầu — cập nhật mỗi 20 phút trong giờ giao dịch", "th": "ภาพรวมตลาดโลกแบบเรียลไทม์ — อัปเดตทุก 20 นาทีในช่วงเวลาซื้อขาย", "ms": "Gambaran keseluruhan pasaran global masa nyata — dikemas kini setiap 20 minit semasa waktu dagangan"}),

    # ── Screener page ──
    ("screener_title", "screener", {"en": "Stock Screener", "zh": "股票筛选器", "zh-TW": "股票篩選器", "ja": "株式スクリーナー", "ko": "주식 스크리너", "vi": "Bộ lọc cổ phiếu", "th": "ตัวกรองหุ้น", "ms": "Penyaring Saham"}),
    ("screener_desc", "screener", {"en": "Filter and sort stocks by technical indicators, price changes, and volume", "zh": "按技术指标、价格变化和成交量筛选和排序股票", "zh-TW": "按技術指標、價格變化和成交量篩選和排序股票", "ja": "テクニカル指標、価格変動、出来高で銘柄をフィルター＆ソート", "ko": "기술 지표, 가격 변동, 거래량으로 종목 필터링 및 정렬", "vi": "Lọc và sắp xếp cổ phiếu theo chỉ báo kỹ thuật, biến động giá và khối lượng", "th": "กรองและจัดเรียงหุ้นตามตัวชี้วัดทางเทคนิค การเปลี่ยนแปลงราคา และปริมาณ", "ms": "Tapis dan susun saham mengikut penunjuk teknikal, perubahan harga dan jumlah dagangan"}),

    # ── Watchlist page ──
    ("watchlist_title", "watchlist", {"en": "My Watchlist", "zh": "我的自选股", "zh-TW": "我的自選股", "ja": "マイウォッチリスト", "ko": "내 관심종목", "vi": "Danh mục của tôi", "th": "รายการจับตาของฉัน", "ms": "Senarai Pantau Saya"}),
    ("watchlist_empty", "watchlist", {"en": "Your watchlist is empty. Add stocks from any market page.", "zh": "您的自选股为空。从任意市场页面添加股票。", "zh-TW": "您的自選股為空。從任意市場頁面添加股票。", "ja": "ウォッチリストは空です。市場ページから銘柄を追加してください。", "ko": "관심종목이 비어있습니다. 시장 페이지에서 종목을 추가하세요.", "vi": "Danh mục trống. Thêm cổ phiếu từ trang thị trường bất kỳ.", "th": "รายการจับตาว่างเปล่า เพิ่มหุ้นจากหน้าตลาดใดก็ได้", "ms": "Senarai pantau kosong. Tambah saham dari mana-mana halaman pasaran."}),
    ("add_to_watchlist", "watchlist", {"en": "Add to watchlist", "zh": "加入自选", "zh-TW": "加入自選", "ja": "ウォッチリストに追加", "ko": "관심종목 추가", "vi": "Thêm vào danh mục", "th": "เพิ่มในรายการจับตา", "ms": "Tambah ke senarai pantau"}),
    ("remove_from_watchlist", "watchlist", {"en": "Remove", "zh": "移除", "zh-TW": "移除", "ja": "削除", "ko": "제거", "vi": "Xóa", "th": "ลบ", "ms": "Buang"}),

    # ── Common UI ──
    ("search_placeholder", "common", {"en": "Search stock by name or ticker...", "zh": "按名称或代码搜索股票...", "zh-TW": "按名稱或代碼搜索股票...", "ja": "銘柄名またはティッカーで検索...", "ko": "종목명 또는 티커로 검색...", "vi": "Tìm cổ phiếu theo tên hoặc mã...", "th": "ค้นหาหุ้นตามชื่อหรือรหัส...", "ms": "Cari saham mengikut nama atau ticker..."}),
    ("loading", "common", {"en": "Loading...", "zh": "加载中...", "zh-TW": "載入中...", "ja": "読み込み中...", "ko": "로딩 중...", "vi": "Đang tải...", "th": "กำลังโหลด...", "ms": "Memuatkan..."}),
    ("error_label", "common", {"en": "Error", "zh": "错误", "zh-TW": "錯誤", "ja": "エラー", "ko": "오류", "vi": "Lỗi", "th": "ข้อผิดพลาด", "ms": "Ralat"}),
    ("refresh", "common", {"en": "Refresh", "zh": "刷新", "zh-TW": "重新整理", "ja": "更新", "ko": "새로고침", "vi": "Làm mới", "th": "รีเฟรช", "ms": "Muat semula"}),
    ("close", "common", {"en": "Close", "zh": "关闭", "zh-TW": "關閉", "ja": "閉じる", "ko": "닫기", "vi": "Đóng", "th": "ปิด", "ms": "Tutup"}),
    ("collapse", "common", {"en": "collapse", "zh": "收起", "zh-TW": "收起", "ja": "折りたたむ", "ko": "접기", "vi": "thu gọn", "th": "ย่อ", "ms": "tutup"}),
    ("expand", "common", {"en": "expand", "zh": "展开", "zh-TW": "展開", "ja": "展開", "ko": "펼치기", "vi": "mở rộng", "th": "ขยาย", "ms": "buka"}),
    ("not_financial_advice", "common", {"en": "NOT financial advice", "zh": "非投资建议", "zh-TW": "非投資建議", "ja": "投資助言ではありません", "ko": "투자 조언이 아닙니다", "vi": "Không phải tư vấn đầu tư", "th": "ไม่ใช่คำแนะนำการลงทุน", "ms": "BUKAN nasihat kewangan"}),

    # ── Footer ──
    ("footer_project", "footer", {"en": "A DataP.ai project", "zh": "DataP.ai 项目", "zh-TW": "DataP.ai 專案", "ja": "DataP.aiプロジェクト", "ko": "DataP.ai 프로젝트", "vi": "Dự án DataP.ai", "th": "โปรเจค DataP.ai", "ms": "Projek DataP.ai"}),
    ("footer_powered_by", "footer", {"en": "powered by", "zh": "由", "zh-TW": "由", "ja": "提供", "ko": "제공", "vi": "được cung cấp bởi", "th": "ขับเคลื่อนโดย", "ms": "dikuasakan oleh"}),
    ("footer_real_browser", "footer", {"en": "real-browser technology", "zh": "真实浏览器技术", "zh-TW": "真實瀏覽器技術", "ja": "リアルブラウザ技術", "ko": "리얼 브라우저 기술", "vi": "công nghệ trình duyệt thực", "th": "เทคโนโลยีเบราว์เซอร์จริง", "ms": "teknologi pelayar sebenar"}),
    ("footer_ai_framework", "footer", {"en": "AI agent framework", "zh": "AI代理框架", "zh-TW": "AI代理框架", "ja": "AIエージェントフレームワーク", "ko": "AI 에이전트 프레임워크", "vi": "khung AI agent", "th": "เฟรมเวิร์ก AI agent", "ms": "rangka kerja ejen AI"}),
    ("footer_website_intel", "footer", {"en": "Website Change Intelligence", "zh": "网站变动情报", "zh-TW": "網站變動情報", "ja": "ウェブサイト変更インテリジェンス", "ko": "웹사이트 변경 인텔리전스", "vi": "Phân tích thay đổi website", "th": "ข้อมูลการเปลี่ยนแปลงเว็บไซต์", "ms": "Perisikan Perubahan Laman Web"}),

    # ── Auth ──
    ("register", "auth", {"en": "Register", "zh": "注册", "zh-TW": "註冊", "ja": "登録", "ko": "가입", "vi": "Đăng ký", "th": "สมัคร", "ms": "Daftar"}),
    ("logout", "auth", {"en": "Log out", "zh": "退出", "zh-TW": "登出", "ja": "ログアウト", "ko": "로그아웃", "vi": "Đăng xuất", "th": "ออกจากระบบ", "ms": "Log Keluar"}),
    ("profile", "auth", {"en": "Profile", "zh": "个人资料", "zh-TW": "個人資料", "ja": "プロフィール", "ko": "프로필", "vi": "Hồ sơ", "th": "โปรไฟล์", "ms": "Profil"}),
]

# Flatten and insert
rows = []
for label_key, category, texts in LABELS:
    for lang, text in texts.items():
        rows.append((label_key, lang, text, category))

with conn.cursor() as cur:
    psycopg2.extras.execute_values(cur, """
        INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category)
        VALUES %s
        ON CONFLICT (label_key, lang) DO UPDATE SET
            text = EXCLUDED.text,
            category = EXCLUDED.category,
            updated_at = NOW()
    """, rows, page_size=200)
    conn.commit()

print(f"Seeded {len(rows)} translation rows ({len(LABELS)} keys × {len(set(r[1] for r in rows))} languages)")

# Verify
with conn.cursor() as cur:
    cur.execute("SELECT lang, COUNT(*) FROM datapai.sys_lang_labels GROUP BY lang ORDER BY lang")
    for r in cur.fetchall():
        print(f"  {r[0]:>5}: {r[1]} labels")

conn.close()
