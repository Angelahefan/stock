#!/usr/bin/env python3
"""
Phase 3 seed: i18n labels for remaining hardcoded English strings.
- Grid/List toggle
- Last scan section
- Footer disclaimer
- US homepage hero
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
    # ── Grid / List toggle ──
    ("view_grid", "common", {
        "en": "Grid", "zh": "网格", "zh-TW": "網格", "ja": "グリッド", "ko": "그리드", "vi": "Lưới", "th": "ตาราง", "ms": "Grid",
    }),
    ("view_list", "common", {
        "en": "List", "zh": "列表", "zh-TW": "列表", "ja": "リスト", "ko": "리스트", "vi": "Danh sách", "th": "รายการ", "ms": "Senarai",
    }),

    # ── Last scan section ──
    ("last_scan_label", "scan", {
        "en": "Last scan:", "zh": "上次扫描:", "zh-TW": "上次掃描:", "ja": "最終スキャン:", "ko": "마지막 스캔:", "vi": "Quét gần nhất:", "th": "สแกนล่าสุด:", "ms": "Imbasan terakhir:",
    }),
    ("tickers_with_data", "scan", {
        "en": "tickers with data", "zh": "只有数据的股票", "zh-TW": "有數據的股票", "ja": "銘柄にデータあり", "ko": "데이터 보유 종목", "vi": "mã có dữ liệu", "th": "หุ้นที่มีข้อมูล", "ms": "saham dengan data",
    }),

    # ── Footer disclaimer ──
    ("disclaimer_title", "footer", {
        "en": "Important Disclaimer",
        "zh": "重要免责声明",
        "zh-TW": "重要免責聲明",
        "ja": "重要な免責事項",
        "ko": "중요 면책 조항",
        "vi": "Tuyên bố miễn trừ trách nhiệm",
        "th": "ข้อสงวนสิทธิ์ที่สำคัญ",
        "ms": "Penafian Penting",
    }),
    ("disclaimer_body", "footer", {
        "en": "All data, signals, scores, and AI-generated content on DataP.ai are for educational and informational purposes only and do NOT constitute financial advice, investment recommendations, or solicitation to buy or sell securities. Technical indicators are computed from historical price data and backtested against past performance — past performance does not guarantee future results. Always conduct your own research and consult a qualified financial advisor before making investment decisions. DataP.ai and its operators are not responsible for any trading losses.",
        "zh": "DataP.ai上的所有数据、信号、评分和AI生成内容仅供教育和信息目的，不构成财务建议、投资推荐或买卖证券的招揽。技术指标根据历史价格数据计算并基于过去表现回测——过去的表现不保证未来结果。在做出投资决策之前，请务必进行自己的研究并咨询合格的财务顾问。DataP.ai及其运营者不对任何交易损失负责。",
        "zh-TW": "DataP.ai上的所有數據、信號、評分和AI生成內容僅供教育和資訊目的，不構成財務建議、投資推薦或買賣證券的招攬。技術指標根據歷史價格數據計算並基於過去表現回測——過去的表現不保證未來結果。在做出投資決策之前，請務必進行自己的研究並諮詢合格的財務顧問。DataP.ai及其營運者不對任何交易損失負責。",
        "ja": "DataP.aiのすべてのデータ、シグナル、スコア、AI生成コンテンツは教育・情報提供のみを目的としており、投資助言、投資推奨、証券の売買勧誘を構成するものではありません。テクニカル指標は過去の価格データから算出され、過去のパフォーマンスに基づいてバックテストされています。過去のパフォーマンスは将来の結果を保証するものではありません。投資判断を行う前に、必ずご自身で調査を行い、適格な財務アドバイザーに相談してください。DataP.aiおよびその運営者は、いかなる取引損失についても責任を負いません。",
        "ko": "DataP.ai의 모든 데이터, 시그널, 점수 및 AI 생성 콘텐츠는 교육 및 정보 제공 목적으로만 제공되며, 재무 조언, 투자 추천 또는 증권 매매 권유를 구성하지 않습니다. 기술적 지표는 과거 가격 데이터에서 계산되며, 과거 성과는 미래 결과를 보장하지 않습니다. 투자 결정을 내리기 전에 반드시 스스로 조사하고 자격을 갖춘 재무 고문과 상담하십시오. DataP.ai 및 운영자는 어떠한 거래 손실에 대해서도 책임지지 않습니다.",
        "vi": "Tất cả dữ liệu, tín hiệu, điểm số và nội dung do AI tạo trên DataP.ai chỉ nhằm mục đích giáo dục và cung cấp thông tin, KHÔNG cấu thành tư vấn tài chính, khuyến nghị đầu tư hoặc chào mời mua bán chứng khoán. Các chỉ báo kỹ thuật được tính từ dữ liệu giá lịch sử và kiểm tra ngược dựa trên hiệu suất quá khứ — hiệu suất quá khứ không đảm bảo kết quả tương lai. Luôn tự nghiên cứu và tham khảo ý kiến cố vấn tài chính có trình độ trước khi đưa ra quyết định đầu tư. DataP.ai và các nhà điều hành không chịu trách nhiệm về bất kỳ tổn thất giao dịch nào.",
        "th": "ข้อมูล สัญญาณ คะแนน และเนื้อหาที่สร้างโดย AI ทั้งหมดบน DataP.ai มีวัตถุประสงค์เพื่อการศึกษาและให้ข้อมูลเท่านั้น ไม่ถือเป็นคำแนะนำทางการเงิน คำแนะนำการลงทุน หรือการชักชวนให้ซื้อหรือขายหลักทรัพย์ ตัวชี้วัดทางเทคนิคคำนวณจากข้อมูลราคาในอดีตและทดสอบย้อนหลัง — ผลการดำเนินงานในอดีตไม่รับประกันผลลัพธ์ในอนาคต โปรดทำการวิจัยด้วยตนเองและปรึกษาที่ปรึกษาทางการเงินที่มีคุณสมบัติก่อนตัดสินใจลงทุน DataP.ai และผู้ดำเนินการไม่รับผิดชอบต่อการสูญเสียจากการซื้อขายใดๆ",
        "ms": "Semua data, isyarat, skor dan kandungan yang dijana AI di DataP.ai adalah untuk tujuan pendidikan dan maklumat sahaja dan TIDAK merupakan nasihat kewangan, cadangan pelaburan atau ajakan untuk membeli atau menjual sekuriti. Penunjuk teknikal dikira daripada data harga sejarah dan diuji balik berdasarkan prestasi lepas — prestasi lepas tidak menjamin keputusan masa depan. Sentiasa lakukan penyelidikan sendiri dan berunding dengan penasihat kewangan bertauliah sebelum membuat keputusan pelaburan. DataP.ai dan pengendalinya tidak bertanggungjawab atas sebarang kerugian dagangan.",
    }),

    # ── US homepage hero (hardcoded English) ──
    ("hero_spot_shifts", "hero", {
        "en": "Spot language shifts on company websites before they move stock prices",
        "zh": "在股价变动前发现公司网站的语言变化",
        "zh-TW": "在股價變動前發現公司網站的語言變化",
        "ja": "株価変動前に企業サイトの言葉の変化を検出",
        "ko": "주가 변동 전 기업 웹사이트의 언어 변화를 포착",
        "vi": "Phát hiện thay đổi ngôn ngữ trên website công ty trước khi giá cổ phiếu biến động",
        "th": "ตรวจจับการเปลี่ยนแปลงภาษาบนเว็บไซต์บริษัทก่อนราคาหุ้นจะเคลื่อนไหว",
        "ms": "Kesan perubahan bahasa di laman web syarikat sebelum harga saham bergerak",
    }),
    ("hero_covered_label", "hero", {
        "en": "covered · powered by", "zh": "覆盖 · 技术支持", "zh-TW": "覆蓋 · 技術支持", "ja": "カバー · 提供", "ko": "커버 · 제공", "vi": "được theo dõi · cung cấp bởi", "th": "ครอบคลุม · ขับเคลื่อนโดย", "ms": "diliputi · dikuasakan oleh",
    }),
    ("hero_realBrowser_agents", "hero", {
        "en": "real-browser technology & AI agents", "zh": "真实浏览器技术和AI代理", "zh-TW": "真實瀏覽器技術和AI代理", "ja": "リアルブラウザ技術とAIエージェント", "ko": "실제 브라우저 기술 & AI 에이전트", "vi": "công nghệ trình duyệt thực & AI agent", "th": "เทคโนโลยีเบราว์เซอร์จริงและ AI agent", "ms": "teknologi pelayar sebenar & ejen AI",
    }),
    ("hero_view_n_alerts", "hero", {
        "en": "View", "zh": "查看", "zh-TW": "查看", "ja": "表示", "ko": "보기", "vi": "Xem", "th": "ดู", "ms": "Lihat",
    }),
    ("hero_alerts_suffix", "hero", {
        "en": "Alerts", "zh": "个预警", "zh-TW": "個預警", "ja": "件のアラート", "ko": "개 알림", "vi": "Cảnh báo", "th": "การแจ้งเตือน", "ms": "Amaran",
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
