#!/usr/bin/env python3
"""Phase 12 seed: Pricing page i18n — hero, tiers, features, comparison, FAQ, CTAs."""
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
    # ── Hero ────────────────────────────────────────────────────────────────
    ("pricing_hero_label", "pricing", {
        "en": "Pricing", "zh": "价格", "zh-TW": "價格",
        "ja": "料金プラン", "ko": "요금제", "vi": "Bảng giá",
        "th": "ราคา", "ms": "Harga"}),
    ("pricing_hero_title", "pricing", {
        "en": "Know what changed before the market does",
        "zh": "比市场更早知道发生了什么变化",
        "zh-TW": "比市場更早知道發生了什麼變化",
        "ja": "市場より先に変化を察知する",
        "ko": "시장보다 먼저 변화를 파악하세요",
        "vi": "Biết điều gì thay đổi trước khi thị trường biết",
        "th": "รู้ก่อนตลาดว่ามีอะไรเปลี่ยนแปลง",
        "ms": "Ketahui perubahan sebelum pasaran bertindak"}),
    ("pricing_hero_desc", "pricing", {
        "en": "AI agents scan 9,000+ company websites daily, detect language shifts in forward guidance and risk disclosures, and surface actionable signals — before they move stock prices.",
        "zh": "AI代理每天扫描9,000+家公司网站，检测前瞻性指引和风险披露中的语言变化，在股价波动之前发现可操作的信号。",
        "zh-TW": "AI代理每天掃描9,000+家公司網站，偵測前瞻性指引和風險披露中的語言變化，在股價波動之前發現可操作的信號。",
        "ja": "AIエージェントが毎日9,000+の企業ウェブサイトをスキャンし、業績予想やリスク開示の言語変化を検出。株価が動く前にシグナルを発見。",
        "ko": "AI 에이전트가 매일 9,000+개 기업 웹사이트를 스캔하여 실적 전망 및 리스크 공시의 언어 변화를 감지하고, 주가가 움직이기 전에 시그널을 포착합니다.",
        "vi": "Các AI agent quét hơn 9.000 trang web công ty mỗi ngày, phát hiện thay đổi ngôn ngữ trong hướng dẫn triển vọng và công bố rủi ro — trước khi chúng ảnh hưởng đến giá cổ phiếu.",
        "th": "เอเจนต์ AI สแกนเว็บไซต์บริษัทกว่า 9,000 แห่งทุกวัน ตรวจจับการเปลี่ยนแปลงภาษาในแนวโน้มและการเปิดเผยความเสี่ยง — ก่อนที่ราคาหุ้นจะเคลื่อนไหว",
        "ms": "Agen AI mengimbas 9,000+ laman web syarikat setiap hari, mengesan perubahan bahasa dalam panduan hadapan dan pendedahan risiko — sebelum ia menggerakkan harga saham."}),
    ("pricing_hero_note", "pricing", {
        "en": "Prices in AUD · No lock-in · Cancel any time",
        "zh": "价格以澳元计 · 无锁定期 · 随时取消",
        "zh-TW": "價格以澳幣計 · 無鎖定期 · 隨時取消",
        "ja": "豪ドル表示 · 契約期間なし · いつでも解約可能",
        "ko": "호주 달러 기준 · 약정 없음 · 언제든 해지 가능",
        "vi": "Giá tính bằng AUD · Không ràng buộc · Hủy bất cứ lúc nào",
        "th": "ราคาเป็น AUD · ไม่ผูกมัด · ยกเลิกได้ทุกเมื่อ",
        "ms": "Harga dalam AUD · Tiada kontrak · Batal bila-bila masa"}),

    # ── Price UI ────────────────────────────────────────────────────────────
    ("pricing_free", "pricing", {
        "en": "Free", "zh": "免费", "zh-TW": "免費",
        "ja": "無料", "ko": "무료", "vi": "Miễn phí",
        "th": "ฟรี", "ms": "Percuma"}),
    ("pricing_per_mo", "pricing", {
        "en": "/mo", "zh": "/月", "zh-TW": "/月",
        "ja": "/月", "ko": "/월", "vi": "/tháng",
        "th": "/เดือน", "ms": "/bln"}),
    ("pricing_or", "pricing", {
        "en": "or", "zh": "或", "zh-TW": "或",
        "ja": "または", "ko": "또는", "vi": "hoặc",
        "th": "หรือ", "ms": "atau"}),
    ("pricing_per_yr", "pricing", {
        "en": "/yr", "zh": "/年", "zh-TW": "/年",
        "ja": "/年", "ko": "/년", "vi": "/năm",
        "th": "/ปี", "ms": "/thn"}),
    ("pricing_save", "pricing", {
        "en": "save", "zh": "节省", "zh-TW": "節省",
        "ja": "割引", "ko": "절약", "vi": "tiết kiệm",
        "th": "ประหยัด", "ms": "jimat"}),

    # ── Tier names ──────────────────────────────────────────────────────────
    ("pricing_tier_watch", "pricing", {
        "en": "Signal Watch", "zh": "信号监控", "zh-TW": "信號監控",
        "ja": "シグナルウォッチ", "ko": "시그널 워치", "vi": "Theo dõi Tín hiệu",
        "th": "Signal Watch", "ms": "Signal Watch"}),
    ("pricing_tier_individual", "pricing", {
        "en": "Individual", "zh": "个人版", "zh-TW": "個人版",
        "ja": "個人プラン", "ko": "개인", "vi": "Cá nhân",
        "th": "บุคคล", "ms": "Individu"}),
    ("pricing_tier_professional", "pricing", {
        "en": "Professional", "zh": "专业版", "zh-TW": "專業版",
        "ja": "プロフェッショナル", "ko": "프로페셔널", "vi": "Chuyên nghiệp",
        "th": "มืออาชีพ", "ms": "Profesional"}),
    ("pricing_tier_business", "pricing", {
        "en": "Business", "zh": "企业版", "zh-TW": "企業版",
        "ja": "ビジネス", "ko": "비즈니스", "vi": "Doanh nghiệp",
        "th": "ธุรกิจ", "ms": "Perniagaan"}),

    # ── Tier taglines ───────────────────────────────────────────────────────
    ("pricing_tag_watch", "pricing", {
        "en": "Get started. No card needed.",
        "zh": "立即开始。无需信用卡。",
        "zh-TW": "立即開始。無需信用卡。",
        "ja": "すぐに始められます。カード不要。",
        "ko": "지금 시작하세요. 카드 필요 없음.",
        "vi": "Bắt đầu ngay. Không cần thẻ.",
        "th": "เริ่มต้นเลย ไม่ต้องใช้บัตร",
        "ms": "Mula sekarang. Tanpa kad."}),
    ("pricing_tag_individual", "pricing", {
        "en": "For the serious self-directed investor.",
        "zh": "适合认真的自主投资者。",
        "zh-TW": "適合認真的自主投資者。",
        "ja": "本格的な個人投資家向け。",
        "ko": "진지한 자기주도형 투자자를 위해.",
        "vi": "Dành cho nhà đầu tư tự chủ nghiêm túc.",
        "th": "สำหรับนักลงทุนที่จริงจัง",
        "ms": "Untuk pelabur aktif yang serius."}),
    ("pricing_tag_professional", "pricing", {
        "en": "For active traders, advisors & small teams.",
        "zh": "适合活跃交易者、顾问及小团队。",
        "zh-TW": "適合活躍交易者、顧問及小團隊。",
        "ja": "アクティブトレーダー、アドバイザー、小規模チーム向け。",
        "ko": "활발한 트레이더, 어드바이저 및 소규모 팀을 위해.",
        "vi": "Dành cho trader tích cực, cố vấn & nhóm nhỏ.",
        "th": "สำหรับเทรดเดอร์ ที่ปรึกษา และทีมขนาดเล็ก",
        "ms": "Untuk pedagang aktif, penasihat & pasukan kecil."}),
    ("pricing_tag_business", "pricing", {
        "en": "For funds, desks and research teams.",
        "zh": "适合基金、交易台和研究团队。",
        "zh-TW": "適合基金、交易台和研究團隊。",
        "ja": "ファンド、デスク、リサーチチーム向け。",
        "ko": "펀드, 트레이딩 데스크 및 리서치 팀을 위해.",
        "vi": "Dành cho quỹ, bàn giao dịch và nhóm nghiên cứu.",
        "th": "สำหรับกองทุน โต๊ะเทรด และทีมวิจัย",
        "ms": "Untuk dana, meja dagangan dan pasukan penyelidikan."}),

    # ── Badges ──────────────────────────────────────────────────────────────
    ("pricing_badge_popular", "pricing", {
        "en": "Most popular", "zh": "最受欢迎", "zh-TW": "最受歡迎",
        "ja": "人気No.1", "ko": "가장 인기", "vi": "Phổ biến nhất",
        "th": "ยอดนิยม", "ms": "Paling popular"}),
    ("pricing_badge_institutional", "pricing", {
        "en": "Institutional", "zh": "机构级", "zh-TW": "機構級",
        "ja": "機関投資家向け", "ko": "기관용", "vi": "Tổ chức",
        "th": "สถาบัน", "ms": "Institusi"}),

    # ── CTA buttons ─────────────────────────────────────────────────────────
    ("pricing_cta_free", "pricing", {
        "en": "Start free", "zh": "免费开始", "zh-TW": "免費開始",
        "ja": "無料で始める", "ko": "무료 시작", "vi": "Bắt đầu miễn phí",
        "th": "เริ่มต้นฟรี", "ms": "Mula percuma"}),
    ("pricing_cta_trial", "pricing", {
        "en": "Start 14-day free trial", "zh": "开始14天免费试用", "zh-TW": "開始14天免費試用",
        "ja": "14日間無料トライアル", "ko": "14일 무료 체험 시작", "vi": "Dùng thử 14 ngày miễn phí",
        "th": "ทดลองใช้ฟรี 14 วัน", "ms": "Percubaan percuma 14 hari"}),
    ("pricing_cta_contact", "pricing", {
        "en": "Contact us", "zh": "联系我们", "zh-TW": "聯繫我們",
        "ja": "お問い合わせ", "ko": "문의하기", "vi": "Liên hệ",
        "th": "ติดต่อเรา", "ms": "Hubungi kami"}),

    # ── Feature list (watch tier) ───────────────────────────────────────────
    ("pf_stocks_monitored", "pricing", {
        "en": "stocks monitored", "zh": "只股票监控", "zh-TW": "檔股票監控",
        "ja": "銘柄監視", "ko": "종목 모니터링", "vi": "cổ phiếu theo dõi",
        "th": "หุ้นที่ติดตาม", "ms": "saham dipantau"}),
    ("pf_weekly_scan", "pricing", {
        "en": "Weekly IR page scan", "zh": "每周IR页面扫描", "zh-TW": "每週IR頁面掃描",
        "ja": "週次IRページスキャン", "ko": "주간 IR 페이지 스캔", "vi": "Quét trang IR hàng tuần",
        "th": "สแกนหน้า IR รายสัปดาห์", "ms": "Imbasan halaman IR mingguan"}),
    ("pf_lang_shift_alerts", "pricing", {
        "en": "Language shift alerts", "zh": "语言变化警报", "zh-TW": "語言變化警報",
        "ja": "言語変化アラート", "ko": "언어 변화 알림", "vi": "Cảnh báo thay đổi ngôn ngữ",
        "th": "แจ้งเตือนการเปลี่ยนแปลงภาษา", "ms": "Amaran perubahan bahasa"}),
    ("pf_scan_history", "pricing", {
        "en": "scan history", "zh": "扫描历史", "zh-TW": "掃描歷史",
        "ja": "スキャン履歴", "ko": "스캔 기록", "vi": "lịch sử quét",
        "th": "ประวัติการสแกน", "ms": "sejarah imbasan"}),
    ("pf_confidence_scores", "pricing", {
        "en": "Confidence scores", "zh": "置信度评分", "zh-TW": "置信度評分",
        "ja": "信頼度スコア", "ko": "신뢰도 점수", "vi": "Điểm tin cậy",
        "th": "คะแนนความเชื่อมั่น", "ms": "Skor keyakinan"}),
    ("pf_watchlist", "pricing", {
        "en": "Watchlist", "zh": "关注列表", "zh-TW": "關注列表",
        "ja": "ウォッチリスト", "ko": "관심 목록", "vi": "Danh sách theo dõi",
        "th": "รายการติดตาม", "ms": "Senarai pantau"}),
    ("pf_daily_scan", "pricing", {
        "en": "Daily scan", "zh": "每日扫描", "zh-TW": "每日掃描",
        "ja": "日次スキャン", "ko": "일일 스캔", "vi": "Quét hàng ngày",
        "th": "สแกนรายวัน", "ms": "Imbasan harian"}),
    ("pf_ai_technical", "pricing", {
        "en": "AI Technical Signal", "zh": "AI技术信号", "zh-TW": "AI技術信號",
        "ja": "AIテクニカルシグナル", "ko": "AI 기술적 시그널", "vi": "Tín hiệu Kỹ thuật AI",
        "th": "สัญญาณเทคนิค AI", "ms": "Isyarat Teknikal AI"}),
    ("pf_chart_vision", "pricing", {
        "en": "Chart Vision (Gemini)", "zh": "图表视觉 (Gemini)", "zh-TW": "圖表視覺 (Gemini)",
        "ja": "チャートビジョン (Gemini)", "ko": "차트 비전 (Gemini)", "vi": "Phân tích Biểu đồ (Gemini)",
        "th": "Chart Vision (Gemini)", "ms": "Chart Vision (Gemini)"}),
    ("pf_asx_trading", "pricing", {
        "en": "ASX Trading Signal", "zh": "ASX交易信号", "zh-TW": "ASX交易信號",
        "ja": "ASXトレーディングシグナル", "ko": "ASX 트레이딩 시그널", "vi": "Tín hiệu Giao dịch ASX",
        "th": "สัญญาณเทรด ASX", "ms": "Isyarat Dagangan ASX"}),
    ("pf_api_access", "pricing", {
        "en": "API access", "zh": "API访问", "zh-TW": "API存取",
        "ja": "APIアクセス", "ko": "API 액세스", "vi": "Truy cập API",
        "th": "เข้าถึง API", "ms": "Akses API"}),

    # ── Individual tier features ────────────────────────────────────────────
    ("pf_daily_ir_scan", "pricing", {
        "en": "Daily IR page scan", "zh": "每日IR页面扫描", "zh-TW": "每日IR頁面掃描",
        "ja": "日次IRページスキャン", "ko": "일일 IR 페이지 스캔", "vi": "Quét trang IR hàng ngày",
        "th": "สแกนหน้า IR รายวัน", "ms": "Imbasan halaman IR harian"}),
    ("pf_full_pipeline", "pricing", {
        "en": "full signal pipeline", "zh": "完整信号管道", "zh-TW": "完整信號管道",
        "ja": "フルシグナルパイプライン", "ko": "전체 시그널 파이프라인", "vi": "quy trình tín hiệu đầy đủ",
        "th": "ท่อสัญญาณเต็มรูปแบบ", "ms": "saluran isyarat penuh"}),
    ("pf_conf_relevance", "pricing", {
        "en": "Confidence + relevance scores", "zh": "置信度+相关性评分", "zh-TW": "置信度+相關性評分",
        "ja": "信頼度＋関連性スコア", "ko": "신뢰도 + 관련성 점수", "vi": "Điểm tin cậy + liên quan",
        "th": "คะแนนความเชื่อมั่น + ความเกี่ยวข้อง", "ms": "Skor keyakinan + relevansi"}),
    ("pf_watchlist_email", "pricing", {
        "en": "Watchlist + email alerts", "zh": "关注列表+邮件提醒", "zh-TW": "關注列表+郵件提醒",
        "ja": "ウォッチリスト＋メールアラート", "ko": "관심 목록 + 이메일 알림", "vi": "Danh sách theo dõi + email cảnh báo",
        "th": "รายการติดตาม + แจ้งเตือนอีเมล", "ms": "Senarai pantau + amaran emel"}),
    ("pf_signal_cache", "pricing", {
        "en": "6-hour signal cache", "zh": "6小时信号缓存", "zh-TW": "6小時信號快取",
        "ja": "6時間シグナルキャッシュ", "ko": "6시간 시그널 캐시", "vi": "Bộ nhớ đệm tín hiệu 6 giờ",
        "th": "แคชสัญญาณ 6 ชั่วโมง", "ms": "Cache isyarat 6 jam"}),

    # ── Professional tier features ──────────────────────────────────────────
    ("pf_multi_scans", "pricing", {
        "en": "Multiple daily scans", "zh": "每日多次扫描", "zh-TW": "每日多次掃描",
        "ja": "1日複数回スキャン", "ko": "하루 다회 스캔", "vi": "Quét nhiều lần mỗi ngày",
        "th": "สแกนหลายครั้งต่อวัน", "ms": "Imbasan harian berganda"}),
    ("pf_full_ai_pipeline", "pricing", {
        "en": "Full AI signal pipeline", "zh": "完整AI信号管道", "zh-TW": "完整AI信號管道",
        "ja": "フルAIシグナルパイプライン", "ko": "전체 AI 시그널 파이프라인", "vi": "Quy trình tín hiệu AI đầy đủ",
        "th": "ท่อสัญญาณ AI เต็มรูปแบบ", "ms": "Saluran isyarat AI penuh"}),
    ("pf_unlimited_history", "pricing", {
        "en": "Unlimited scan history", "zh": "无限扫描历史", "zh-TW": "無限掃描歷史",
        "ja": "無制限スキャン履歴", "ko": "무제한 스캔 기록", "vi": "Lịch sử quét không giới hạn",
        "th": "ประวัติการสแกนไม่จำกัด", "ms": "Sejarah imbasan tanpa had"}),
    ("pf_all_individual", "pricing", {
        "en": "All Individual AI features", "zh": "所有个人版AI功能", "zh-TW": "所有個人版AI功能",
        "ja": "個人プラン全AI機能", "ko": "모든 개인 AI 기능", "vi": "Tất cả tính năng AI Cá nhân",
        "th": "ฟีเจอร์ AI ทั้งหมดของบุคคล", "ms": "Semua ciri AI Individu"}),
    ("pf_priority_processing", "pricing", {
        "en": "Priority signal processing", "zh": "优先信号处理", "zh-TW": "優先信號處理",
        "ja": "優先シグナル処理", "ko": "우선 시그널 처리", "vi": "Xử lý tín hiệu ưu tiên",
        "th": "ประมวลผลสัญญาณลำดับแรก", "ms": "Pemprosesan isyarat keutamaan"}),
    ("pf_rest_api", "pricing", {
        "en": "REST API access", "zh": "REST API访问", "zh-TW": "REST API存取",
        "ja": "REST APIアクセス", "ko": "REST API 액세스", "vi": "Truy cập REST API",
        "th": "เข้าถึง REST API", "ms": "Akses REST API"}),
    ("pf_webhooks", "pricing", {
        "en": "Webhook alerts", "zh": "Webhook警报", "zh-TW": "Webhook警報",
        "ja": "Webhookアラート", "ko": "Webhook 알림", "vi": "Cảnh báo Webhook",
        "th": "แจ้งเตือน Webhook", "ms": "Amaran Webhook"}),
    ("pf_data_export", "pricing", {
        "en": "Historical data export", "zh": "历史数据导出", "zh-TW": "歷史數據匯出",
        "ja": "過去データエクスポート", "ko": "히스토리컬 데이터 내보내기", "vi": "Xuất dữ liệu lịch sử",
        "th": "ส่งออกข้อมูลย้อนหลัง", "ms": "Eksport data sejarah"}),
    ("pf_team_seats", "pricing", {
        "en": "team seats", "zh": "团队席位", "zh-TW": "團隊席位",
        "ja": "チームシート", "ko": "팀 시트", "vi": "chỗ ngồi nhóm",
        "th": "ที่นั่งทีม", "ms": "tempat pasukan"}),
    ("pf_white_label", "pricing", {
        "en": "White-label option", "zh": "白标方案", "zh-TW": "白標方案",
        "ja": "ホワイトラベルオプション", "ko": "화이트 라벨 옵션", "vi": "Tùy chọn nhãn trắng",
        "th": "ตัวเลือก White-label", "ms": "Pilihan White-label"}),

    # ── Business tier features ──────────────────────────────────────────────
    ("pf_unlimited_stocks", "pricing", {
        "en": "Unlimited stocks", "zh": "无限股票", "zh-TW": "無限股票",
        "ja": "無制限の銘柄", "ko": "무제한 종목", "vi": "Cổ phiếu không giới hạn",
        "th": "หุ้นไม่จำกัด", "ms": "Saham tanpa had"}),
    ("pf_unlimited_scans", "pricing", {
        "en": "Unlimited scans", "zh": "无限扫描", "zh-TW": "無限掃描",
        "ja": "無制限スキャン", "ko": "무제한 스캔", "vi": "Quét không giới hạn",
        "th": "สแกนไม่จำกัด", "ms": "Imbasan tanpa had"}),
    ("pf_all_professional", "pricing", {
        "en": "All Professional features", "zh": "所有专业版功能", "zh-TW": "所有專業版功能",
        "ja": "プロフェッショナル全機能", "ko": "모든 프로페셔널 기능", "vi": "Tất cả tính năng Chuyên nghiệp",
        "th": "ฟีเจอร์ทั้งหมดของมืออาชีพ", "ms": "Semua ciri Profesional"}),
    ("pf_custom_alerts", "pricing", {
        "en": "Custom alert rules", "zh": "自定义警报规则", "zh-TW": "自定義警報規則",
        "ja": "カスタムアラートルール", "ko": "사용자 정의 알림 규칙", "vi": "Quy tắc cảnh báo tùy chỉnh",
        "th": "กฎการแจ้งเตือนที่กำหนดเอง", "ms": "Peraturan amaran tersuai"}),
    ("pf_dedicated_support", "pricing", {
        "en": "Dedicated support", "zh": "专属支持", "zh-TW": "專屬支持",
        "ja": "専任サポート", "ko": "전담 지원", "vi": "Hỗ trợ chuyên biệt",
        "th": "การสนับสนุนเฉพาะ", "ms": "Sokongan khusus"}),
    ("pf_custom_integrations", "pricing", {
        "en": "Custom integrations", "zh": "自定义集成", "zh-TW": "自定義整合",
        "ja": "カスタム統合", "ko": "사용자 정의 통합", "vi": "Tích hợp tùy chỉnh",
        "th": "การรวมระบบที่กำหนดเอง", "ms": "Integrasi tersuai"}),
    ("pf_invoiced_billing", "pricing", {
        "en": "Invoiced billing", "zh": "发票结算", "zh-TW": "發票結算",
        "ja": "請求書払い", "ko": "인보이스 결제", "vi": "Thanh toán hóa đơn",
        "th": "การเรียกเก็บเงินใบแจ้งหนี้", "ms": "Bil invois"}),
    ("pf_ir_monitoring_own", "pricing", {
        "en": "IR monitoring for your own listings", "zh": "监控您自己上市公司的IR页面", "zh-TW": "監控您自己上市公司的IR頁面",
        "ja": "自社上場のIR監視", "ko": "자사 상장 IR 모니터링", "vi": "Giám sát IR cho công ty niêm yết của bạn",
        "th": "ติดตาม IR สำหรับบริษัทจดทะเบียนของคุณ", "ms": "Pemantauan IR untuk penyenaraian anda sendiri"}),

    # ── Section headings ────────────────────────────────────────────────────
    ("pricing_what_buying", "pricing", {
        "en": "What you're actually buying", "zh": "您实际获得的是什么", "zh-TW": "您實際獲得的是什麼",
        "ja": "あなたが実際に手に入れるもの", "ko": "실제로 무엇을 얻는가", "vi": "Bạn thực sự nhận được gì",
        "th": "สิ่งที่คุณได้รับจริงๆ", "ms": "Apa yang anda sebenarnya dapat"}),
    ("pricing_how_compare", "pricing", {
        "en": "How we compare", "zh": "我们的优势对比", "zh-TW": "我們的優勢對比",
        "ja": "他社との比較", "ko": "경쟁사 비교", "vi": "So sánh với đối thủ",
        "th": "เราเปรียบเทียบอย่างไร", "ms": "Bagaimana kami berbanding"}),
    ("pricing_unique_label", "pricing", {
        "en": "Unique to TinyFish × DataP.ai", "zh": "TinyFish × DataP.ai 独有", "zh-TW": "TinyFish × DataP.ai 獨有",
        "ja": "TinyFish × DataP.ai 独自の機能", "ko": "TinyFish × DataP.ai 만의 기능", "vi": "Chỉ có tại TinyFish × DataP.ai",
        "th": "เฉพาะ TinyFish × DataP.ai", "ms": "Unik di TinyFish × DataP.ai"}),
    ("pricing_unique_desc", "pricing", {
        "en": "— features no other retail platform offers.",
        "zh": "——其他零售平台都没有的功能。",
        "zh-TW": "——其他零售平台都沒有的功能。",
        "ja": "— 他のリテールプラットフォームにない機能。",
        "ko": "— 다른 리테일 플랫폼에는 없는 기능.",
        "vi": "— tính năng không nền tảng bán lẻ nào khác có.",
        "th": "— ฟีเจอร์ที่แพลตฟอร์มรายย่อยอื่นไม่มี",
        "ms": "— ciri yang tiada platform runcit lain tawarkan."}),
    ("pricing_feature_col", "pricing", {
        "en": "Feature", "zh": "功能", "zh-TW": "功能",
        "ja": "機能", "ko": "기능", "vi": "Tính năng",
        "th": "ฟีเจอร์", "ms": "Ciri"}),
    ("pricing_faq_title", "pricing", {
        "en": "Frequently asked questions", "zh": "常见问题", "zh-TW": "常見問題",
        "ja": "よくある質問", "ko": "자주 묻는 질문", "vi": "Câu hỏi thường gặp",
        "th": "คำถามที่พบบ่อย", "ms": "Soalan lazim"}),

    # ── Bottom CTA ──────────────────────────────────────────────────────────
    ("pricing_bottom_title", "pricing", {
        "en": "Ready to see what changed — before the market does?",
        "zh": "准备好在市场反应之前发现变化了吗？",
        "zh-TW": "準備好在市場反應之前發現變化了嗎？",
        "ja": "市場が動く前に変化を捉える準備はできましたか？",
        "ko": "시장이 반응하기 전에 변화를 포착할 준비가 되셨나요?",
        "vi": "Sẵn sàng phát hiện thay đổi trước thị trường?",
        "th": "พร้อมที่จะรู้ก่อนตลาดหรือยัง?",
        "ms": "Bersedia melihat perubahan sebelum pasaran?"}),
    ("pricing_bottom_desc", "pricing", {
        "en": "Start free. No credit card required. Upgrade when you need more stocks or daily scans.",
        "zh": "免费开始。无需信用卡。需要更多股票或每日扫描时再升级。",
        "zh-TW": "免費開始。無需信用卡。需要更多股票或每日掃描時再升級。",
        "ja": "無料で開始。クレジットカード不要。より多くの銘柄や日次スキャンが必要になったら、アップグレード。",
        "ko": "무료로 시작. 카드 불필요. 더 많은 종목이나 일일 스캔이 필요할 때 업그레이드.",
        "vi": "Bắt đầu miễn phí. Không cần thẻ tín dụng. Nâng cấp khi cần thêm cổ phiếu hoặc quét hàng ngày.",
        "th": "เริ่มต้นฟรี ไม่ต้องใช้บัตรเครดิต อัปเกรดเมื่อต้องการหุ้นเพิ่มหรือสแกนรายวัน",
        "ms": "Mula percuma. Tanpa kad kredit. Naik taraf apabila perlu lebih banyak saham atau imbasan harian."}),
    ("pricing_cta_try_individual", "pricing", {
        "en": "Try Individual free for 14 days", "zh": "免费试用个人版14天", "zh-TW": "免費試用個人版14天",
        "ja": "個人プランを14日間無料体験", "ko": "개인 플랜 14일 무료 체험", "vi": "Dùng thử Cá nhân miễn phí 14 ngày",
        "th": "ทดลองใช้บุคคลฟรี 14 วัน", "ms": "Cuba Individu percuma 14 hari"}),
    ("pricing_cta_enterprise", "pricing", {
        "en": "Business / Enterprise enquiry →", "zh": "企业/机构咨询 →", "zh-TW": "企業/機構諮詢 →",
        "ja": "ビジネス/エンタープライズお問い合わせ →", "ko": "비즈니스/엔터프라이즈 문의 →", "vi": "Liên hệ Doanh nghiệp →",
        "th": "สอบถามแพ็กเกจธุรกิจ →", "ms": "Pertanyaan Perniagaan / Perusahaan →"}),

    # ── FAQ questions ───────────────────────────────────────────────────────
    ("pricing_faq_q1", "pricing", {
        "en": 'What does "language shift" mean?',
        "zh": "\u4ec0\u4e48\u662f\u201c\u8bed\u8a00\u53d8\u5316\u201d\uff1f",
        "zh-TW": "\u4ec0\u9ebc\u662f\u300c\u8a9e\u8a00\u8b8a\u5316\u300d\uff1f",
        "ja": "\u300c\u8a00\u8a9e\u5909\u5316\u300d\u3068\u306f\uff1f",
        "ko": '"\uc5b8\uc5b4 \ubcc0\ud654"\ub780 \ubb34\uc5c7\uc778\uac00\uc694?',
        "vi": '"Thay \u0111\u1ed5i ng\u00f4n ng\u1eef" c\u00f3 ngh\u0129a l\u00e0 g\u00ec?',
        "th": '"การเปลี่ยนแปลงภาษา" หมายถึงอะไร?',
        "ms": 'Apakah maksud "perubahan bahasa"?'}),
    ("pricing_faq_a1", "pricing", {
        "en": "Companies quietly change the wording on their investor relations pages before announcements — removing forward guidance, adding risk disclaimers, softening commitment language. These shifts often precede material price moves by days or weeks.",
        "zh": "公司在公告前会悄悄修改投资者关系页面的措辞——删除前瞻性指引、添加风险免责声明、软化承诺语言。这些变化往往在股价大幅波动前数天或数周出现。",
        "zh-TW": "公司在公告前會悄悄修改投資者關係頁面的措辭——刪除前瞻性指引、添加風險免責聲明、軟化承諾語言。這些變化往往在股價大幅波動前數天或數週出現。",
        "ja": "企業は発表前にIRページの表現を密かに変更します — 業績予想の削除、リスク免責の追加、コミットメント表現の軟化。これらの変化は、重要な株価変動の数日〜数週間前に起こることが多いです。",
        "ko": "기업들은 공시 전에 투자자 관계 페이지의 표현을 조용히 변경합니다 — 실적 전망 삭제, 위험 면책 조항 추가, 약속 표현 완화. 이러한 변화는 주가 변동보다 수일~수주 앞서 나타나는 경우가 많습니다.",
        "vi": "Các công ty thầm lặng thay đổi cách diễn đạt trên trang quan hệ nhà đầu tư trước khi công bố — xóa hướng dẫn triển vọng, thêm tuyên bố miễn trừ rủi ro, làm mềm ngôn ngữ cam kết. Những thay đổi này thường xuất hiện trước biến động giá từ vài ngày đến vài tuần.",
        "th": "บริษัทจะเปลี่ยนถ้อยคำบนหน้าเว็บนักลงทุนสัมพันธ์อย่างเงียบๆ ก่อนการประกาศ — ลบแนวโน้ม เพิ่มข้อจำกัดความเสี่ยง ทำให้ภาษามีความมุ่งมั่นน้อยลง การเปลี่ยนแปลงเหล่านี้มักเกิดก่อนราคาเคลื่อนไหวสำคัญหลายวันหรือหลายสัปดาห์",
        "ms": "Syarikat diam-diam menukar perkataan pada halaman hubungan pelabur mereka sebelum pengumuman — mengeluarkan panduan hadapan, menambah penafian risiko, melembutkan bahasa komitmen. Perubahan ini sering mendahului pergerakan harga material beberapa hari atau minggu."}),
    ("pricing_faq_q2", "pricing", {
        "en": "Which stocks are covered?", "zh": "覆盖哪些股票？", "zh-TW": "涵蓋哪些股票？",
        "ja": "どの銘柄が対象ですか？", "ko": "어떤 종목을 커버하나요?", "vi": "Những cổ phiếu nào được bao phủ?",
        "th": "ครอบคลุมหุ้นอะไรบ้าง?", "ms": "Saham mana yang diliputi?"}),
    ("pricing_faq_a2", "pricing", {
        "en": "9,000+ US-listed stocks (NYSE, NASDAQ, AMEX) and 2,000+ ASX-listed companies.",
        "zh": "9,000+只美国上市股票（NYSE、NASDAQ、AMEX）和2,000+家ASX上市公司。",
        "zh-TW": "9,000+檔美國上市股票（NYSE、NASDAQ、AMEX）和2,000+家ASX上市公司。",
        "ja": "9,000+の米国上場株（NYSE、NASDAQ、AMEX）と2,000+のASX上場企業。",
        "ko": "9,000+개의 미국 상장 주식(NYSE, NASDAQ, AMEX)과 2,000+개의 ASX 상장 기업.",
        "vi": "Hơn 9.000 cổ phiếu niêm yết tại Mỹ (NYSE, NASDAQ, AMEX) và hơn 2.000 công ty niêm yết ASX.",
        "th": "หุ้นสหรัฐกว่า 9,000 ตัว (NYSE, NASDAQ, AMEX) และบริษัทจดทะเบียน ASX กว่า 2,000 แห่ง",
        "ms": "9,000+ saham tersenarai AS (NYSE, NASDAQ, AMEX) dan 2,000+ syarikat tersenarai ASX."}),
    ("pricing_faq_q3", "pricing", {
        "en": "Is this financial advice?", "zh": "这是投资建议吗？", "zh-TW": "這是投資建議嗎？",
        "ja": "これは投資助言ですか？", "ko": "이것은 투자 조언인가요?", "vi": "Đây có phải lời khuyên tài chính không?",
        "th": "นี่เป็นคำแนะนำทางการเงินหรือไม่?", "ms": "Adakah ini nasihat kewangan?"}),
    ("pricing_faq_a3", "pricing", {
        "en": "No. All signals are AI-generated and for informational purposes only. They do not constitute financial advice. Always do your own research before making investment decisions.",
        "zh": "不是。所有信号均由AI生成，仅供参考。它们不构成投资建议。在做出投资决策前，请始终进行自己的研究。",
        "zh-TW": "不是。所有信號均由AI生成，僅供參考。它們不構成投資建議。在做出投資決策前，請始終進行自己的研究。",
        "ja": "いいえ。全てのシグナルはAI生成であり、情報提供のみを目的としています。投資助言ではありません。投資判断は必ずご自身で調査の上行ってください。",
        "ko": "아니요. 모든 시그널은 AI가 생성한 것이며 정보 제공만을 목적으로 합니다. 투자 조언이 아닙니다. 투자 결정 전 반드시 자체 조사를 수행하세요.",
        "vi": "Không. Tất cả tín hiệu được AI tạo ra và chỉ mang tính tham khảo. Không phải lời khuyên đầu tư. Luôn tự nghiên cứu trước khi ra quyết định đầu tư.",
        "th": "ไม่ สัญญาณทั้งหมดสร้างโดย AI เพื่อวัตถุประสงค์ในการให้ข้อมูลเท่านั้น ไม่ถือเป็นคำแนะนำทางการเงิน กรุณาศึกษาด้วยตัวเองก่อนตัดสินใจลงทุน",
        "ms": "Tidak. Semua isyarat dijana oleh AI dan untuk tujuan maklumat sahaja. Ia bukan nasihat kewangan. Sentiasa buat kajian sendiri sebelum membuat keputusan pelaburan."}),
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
        rows, template="(%s, %s, %s, %s)")
    conn.commit()
    print(f"Upserted {cur.rowcount} rows.")
    cur.execute("SELECT COUNT(*) FROM datapai.sys_lang_labels")
    print(f"Total labels in DB: {cur.fetchone()[0]}")
conn.close()
print("Done.")
