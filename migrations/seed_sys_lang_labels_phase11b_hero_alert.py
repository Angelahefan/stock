#!/usr/bin/env python3
"""Phase 11b seed: Hero alert line + Copilot chatbot i18n labels."""
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
    ("hero_wordscore_cautious", "ticker", {
        "en": "⚠ Word-score alert: page shifted toward more cautious language.",
        "zh": "⚠ 措辞评分警报：页面措辞变得更加谨慎。",
        "zh-TW": "⚠ 措辭評分警報：頁面措辭變得更加謹慎。",
        "ja": "⚠ ワードスコア警告：ページの表現がより慎重な言い回しに変化。",
        "ko": "⚠ 워드스코어 경고: 페이지 표현이 더 신중한 어조로 변경됨.",
        "vi": "⚠ Cảnh báo chỉ số ngôn từ: trang đã chuyển sang ngôn ngữ thận trọng hơn.",
        "th": "⚠ แจ้งเตือนคะแนนถ้อยคำ: หน้าเปลี่ยนไปใช้ภาษาที่ระมัดระวังมากขึ้น",
        "ms": "⚠ Amaran skor kata: halaman beralih ke bahasa yang lebih berhati-hati."}),
    ("hero_wordscore_confident", "ticker", {
        "en": "✓ Word-score: language has become more confident and committed.",
        "zh": "✓ 措辞评分：语言变得更加自信和坚定。",
        "zh-TW": "✓ 措辭評分：語言變得更加自信和堅定。",
        "ja": "✓ ワードスコア：表現がより自信に満ちた積極的な内容に変化。",
        "ko": "✓ 워드스코어: 표현이 더 자신감 있고 확고한 어조로 변경됨.",
        "vi": "✓ Chỉ số ngôn từ: ngôn ngữ đã trở nên tự tin và cam kết hơn.",
        "th": "✓ คะแนนถ้อยคำ: ภาษามีความมั่นใจและมุ่งมั่นมากขึ้น",
        "ms": "✓ Skor kata: bahasa menjadi lebih yakin dan komited."}),
    ("hero_wordscore_moderate", "ticker", {
        "en": "~ Moderate wording change detected on this page.",
        "zh": "~ 检测到该页面措辞有适度变化。",
        "zh-TW": "~ 偵測到該頁面措辭有適度變化。",
        "ja": "~ このページで中程度の表現変更を検出。",
        "ko": "~ 이 페이지에서 적당한 표현 변경이 감지됨.",
        "vi": "~ Phát hiện thay đổi ngôn từ vừa phải trên trang này.",
        "th": "~ ตรวจพบการเปลี่ยนแปลงถ้อยคำระดับปานกลางในหน้านี้",
        "ms": "~ Perubahan perkataan sederhana dikesan pada halaman ini."}),
    ("hero_ag2_signal", "ticker", {
        "en": "AG2 signal", "zh": "AG2 信号", "zh-TW": "AG2 信號",
        "ja": "AG2シグナル", "ko": "AG2 시그널", "vi": "Tín hiệu AG2",
        "th": "สัญญาณ AG2", "ms": "Isyarat AG2"}),
    ("hero_no_ag2_signal", "ticker", {
        "en": "No AG2 financial signal", "zh": "无AG2金融信号", "zh-TW": "無AG2金融信號",
        "ja": "AG2金融シグナルなし", "ko": "AG2 금융 시그널 없음", "vi": "Không có tín hiệu tài chính AG2",
        "th": "ไม่มีสัญญาณการเงิน AG2", "ms": "Tiada isyarat kewangan AG2"}),
    ("hero_conf", "ticker", {
        "en": "conf", "zh": "置信度", "zh-TW": "置信度",
        "ja": "信頼度", "ko": "신뢰도", "vi": "độ tin cậy",
        "th": "ความเชื่อมั่น", "ms": "keyakinan"}),
    ("hero_quality_flags", "ticker", {
        "en": "⚠ quality flags", "zh": "⚠ 质量标记", "zh-TW": "⚠ 品質標記",
        "ja": "⚠ 品質フラグ", "ko": "⚠ 품질 플래그", "vi": "⚠ cờ chất lượng",
        "th": "⚠ ธงคุณภาพ", "ms": "⚠ penanda kualiti"}),

    # ── Copilot context header ────────────────────────────────────────────
    ("copilot_viewing", "copilot", {
        "en": "Viewing", "zh": "正在查看", "zh-TW": "正在查看",
        "ja": "表示中", "ko": "조회 중", "vi": "Đang xem",
        "th": "กำลังดู", "ms": "Melihat"}),
    ("copilot_on", "copilot", {
        "en": "on", "zh": "在", "zh-TW": "在",
        "ja": "の", "ko": "에서", "vi": "trên",
        "th": "บน", "ms": "di"}),

    # ── Copilot chatbot strings ─────────────────────────────────────────────
    ("copilot_intro", "copilot", {
        "en": "I'm your AI research co-pilot. I know what you're looking at on this page.",
        "zh": "我是您的AI研究助手。我了解您正在查看的页面内容。",
        "zh-TW": "我是您的AI研究助手。我了解您正在查看的頁面內容。",
        "ja": "私はあなたのAIリサーチ・コパイロットです。このページの内容を把握しています。",
        "ko": "저는 AI 리서치 코파일럿입니다. 이 페이지의 내용을 파악하고 있습니다.",
        "vi": "Tôi là trợ lý nghiên cứu AI của bạn. Tôi hiểu nội dung trang bạn đang xem.",
        "th": "ฉันเป็นผู้ช่วยวิจัย AI ของคุณ ฉันรู้ว่าคุณกำลังดูอะไรอยู่ในหน้านี้",
        "ms": "Saya pembantu penyelidikan AI anda. Saya tahu apa yang anda lihat di halaman ini."}),
    ("copilot_try_asking", "copilot", {
        "en": "Try asking", "zh": "试试问", "zh-TW": "試試問",
        "ja": "聞いてみよう", "ko": "질문해 보세요", "vi": "Thử hỏi",
        "th": "ลองถาม", "ms": "Cuba tanya"}),
    ("copilot_placeholder", "copilot", {
        "en": "Ask anything… (Enter to send)",
        "zh": "问任何问题… (Enter发送)",
        "zh-TW": "問任何問題… (Enter 送出)",
        "ja": "何でも聞いてください…（Enterで送信）",
        "ko": "무엇이든 물어보세요… (Enter로 전송)",
        "vi": "Hỏi bất kỳ điều gì… (Enter để gửi)",
        "th": "ถามอะไรก็ได้… (Enter เพื่อส่ง)",
        "ms": "Tanya apa sahaja… (Enter untuk hantar)"}),
    ("copilot_disclaimer", "copilot", {
        "en": "For research only — not financial advice",
        "zh": "仅供参考，不构成投资建议",
        "zh-TW": "僅供參考，不構成投資建議",
        "ja": "調査目的のみ — 投資助言ではありません",
        "ko": "연구 목적만 — 투자 조언이 아닙니다",
        "vi": "Chỉ để nghiên cứu — không phải lời khuyên đầu tư",
        "th": "เพื่อการศึกษาเท่านั้น — ไม่ใช่คำแนะนำการลงทุน",
        "ms": "Untuk penyelidikan sahaja — bukan nasihat kewangan"}),

    # ── Copilot suggested questions ─────────────────────────────────────────
    # US homepage
    ("copilot_q_us_1", "copilot", {
        "en": "Which US stocks have the most significant website changes today?",
        "zh": "今天哪些美股有最重大的网站变更？",
        "zh-TW": "今天哪些美股有最重大的網站變更？",
        "ja": "今日、最も重要なウェブサイト変更があった米国株はどれですか？",
        "ko": "오늘 가장 중요한 웹사이트 변경이 있는 미국 주식은?",
        "vi": "Cổ phiếu Mỹ nào có thay đổi website đáng kể nhất hôm nay?",
        "th": "หุ้นสหรัฐฯ ตัวไหนมีการเปลี่ยนแปลงเว็บไซต์สำคัญที่สุดวันนี้?",
        "ms": "Saham AS mana yang mempunyai perubahan laman web paling ketara hari ini?"}),
    ("copilot_q_us_2", "copilot", {
        "en": "Give me a quick overview of the current market sentiment",
        "zh": "给我一个当前市场情绪的快速概览",
        "zh-TW": "給我一個當前市場情緒的快速概覽",
        "ja": "現在の市場センチメントを簡単に教えてください",
        "ko": "현재 시장 심리를 간략히 설명해 주세요",
        "vi": "Cho tôi cái nhìn tổng quan nhanh về tâm lý thị trường hiện tại",
        "th": "ให้ภาพรวมเร็วๆ เกี่ยวกับอารมณ์ตลาดปัจจุบัน",
        "ms": "Berikan gambaran ringkas sentimen pasaran semasa"}),
    ("copilot_q_us_3", "copilot", {
        "en": "Which stocks in the monitored universe have the best technicals?",
        "zh": "在监控范围内哪些股票技术面最好？",
        "zh-TW": "在監控範圍內哪些股票技術面最好？",
        "ja": "監視対象の中でテクニカルが最も良い銘柄はどれですか？",
        "ko": "모니터링 대상 중 기술적 분석이 가장 좋은 종목은?",
        "vi": "Cổ phiếu nào trong danh sách theo dõi có kỹ thuật tốt nhất?",
        "th": "หุ้นตัวไหนในจักรวาลที่ติดตามมีเทคนิคดีที่สุด?",
        "ms": "Saham mana dalam universi pemantauan mempunyai teknikal terbaik?"}),
    # Ticker detail
    ("copilot_q_ticker_1", "copilot", {
        "en": "What are the key risks for this stock right now?",
        "zh": "这只股票目前的主要风险是什么？",
        "zh-TW": "這檔股票目前的主要風險是什麼？",
        "ja": "この銘柄の現在の主要リスクは何ですか？",
        "ko": "이 종목의 현재 주요 리스크는 무엇인가요?",
        "vi": "Rủi ro chính của cổ phiếu này hiện tại là gì?",
        "th": "ความเสี่ยงหลักของหุ้นตัวนี้ตอนนี้คืออะไร?",
        "ms": "Apakah risiko utama saham ini sekarang?"}),
    ("copilot_q_ticker_2", "copilot", {
        "en": "Summarise the latest IR page changes detected",
        "zh": "总结检测到的最新IR页面变更",
        "zh-TW": "總結偵測到的最新IR頁面變更",
        "ja": "検出された最新のIRページ変更を要約してください",
        "ko": "감지된 최신 IR 페이지 변경 사항을 요약해 주세요",
        "vi": "Tóm tắt các thay đổi trang IR mới nhất được phát hiện",
        "th": "สรุปการเปลี่ยนแปลงหน้า IR ล่าสุดที่ตรวจพบ",
        "ms": "Ringkaskan perubahan halaman IR terbaru yang dikesan"}),
    ("copilot_q_ticker_3", "copilot", {
        "en": "What do the technicals say about entry points?",
        "zh": "技术面对入场点位有什么建议？",
        "zh-TW": "技術面對入場點位有什麼建議？",
        "ja": "テクニカルはエントリーポイントについて何を示していますか？",
        "ko": "기술적 분석에서 진입 시점은 어떻게 보나요?",
        "vi": "Phân tích kỹ thuật cho thấy điểm vào lệnh như thế nào?",
        "th": "เทคนิคบอกอะไรเกี่ยวกับจุดเข้าซื้อ?",
        "ms": "Apa kata teknikal tentang titik masuk?"}),
    # Ticker intel
    ("copilot_q_intel_1", "copilot", {
        "en": "Compare the TA and FA signals — are they aligned?",
        "zh": "比较技术分析和基本面信号——它们一致吗？",
        "zh-TW": "比較技術分析和基本面信號——它們一致嗎？",
        "ja": "TAとFAシグナルを比較 — 一致していますか？",
        "ko": "TA와 FA 시그널을 비교해 주세요 — 일치하나요?",
        "vi": "So sánh tín hiệu TA và FA — chúng có nhất quán không?",
        "th": "เปรียบเทียบสัญญาณ TA และ FA — สอดคล้องกันไหม?",
        "ms": "Bandingkan isyarat TA dan FA — adakah ia selari?"}),
    ("copilot_q_intel_2", "copilot", {
        "en": "What's the AI's overall view on this stock?",
        "zh": "AI对这只股票的整体看法是什么？",
        "zh-TW": "AI對這檔股票的整體看法是什麼？",
        "ja": "この銘柄に対するAIの総合的な見解は？",
        "ko": "이 종목에 대한 AI의 전체적인 견해는?",
        "vi": "Quan điểm tổng thể của AI về cổ phiếu này là gì?",
        "th": "AI มีมุมมองรวมต่อหุ้นตัวนี้อย่างไร?",
        "ms": "Apakah pandangan keseluruhan AI tentang saham ini?"}),
    ("copilot_q_intel_3", "copilot", {
        "en": "Run me through the key chart patterns",
        "zh": "给我讲解关键的图表形态",
        "zh-TW": "給我講解關鍵的圖表形態",
        "ja": "主要なチャートパターンを説明してください",
        "ko": "주요 차트 패턴을 설명해 주세요",
        "vi": "Phân tích các mô hình biểu đồ chính cho tôi",
        "th": "อธิบายรูปแบบกราฟสำคัญให้ฟัง",
        "ms": "Terangkan corak carta utama"}),
    # Watchlist
    ("copilot_q_watch_1", "copilot", {
        "en": "Summarise my watchlist — which stocks need attention?",
        "zh": "总结我的关注列表——哪些股票需要注意？",
        "zh-TW": "總結我的關注列表——哪些股票需要注意？",
        "ja": "ウォッチリストを要約 — 注目すべき銘柄はどれですか？",
        "ko": "관심 목록을 요약해 주세요 — 주의가 필요한 종목은?",
        "vi": "Tóm tắt danh sách theo dõi — cổ phiếu nào cần chú ý?",
        "th": "สรุปรายการติดตาม — หุ้นตัวไหนต้องเฝ้าดู?",
        "ms": "Ringkaskan senarai pantau — saham mana perlu perhatian?"}),
    ("copilot_q_watch_2", "copilot", {
        "en": "Any breaking news or critical alerts for my stocks?",
        "zh": "我的股票有什么突发新闻或重要警报？",
        "zh-TW": "我的股票有什麼突發新聞或重要警報？",
        "ja": "保有銘柄に速報ニュースや重要アラートはありますか？",
        "ko": "내 종목에 속보나 중요 알림이 있나요?",
        "vi": "Có tin tức nóng hổi hoặc cảnh báo quan trọng nào cho cổ phiếu của tôi?",
        "th": "มีข่าวด่วนหรือการแจ้งเตือนสำคัญสำหรับหุ้นของฉันไหม?",
        "ms": "Ada berita terkini atau amaran penting untuk saham saya?"}),
    # Screener
    ("copilot_q_screener_1", "copilot", {
        "en": "Which stocks have the strongest buy setup right now?",
        "zh": "现在哪些股票有最强的买入信号？",
        "zh-TW": "現在哪些股票有最強的買入信號？",
        "ja": "今、最も強い買いセットアップの銘柄はどれですか？",
        "ko": "지금 가장 강한 매수 설정인 종목은?",
        "vi": "Cổ phiếu nào có tín hiệu mua mạnh nhất hiện tại?",
        "th": "หุ้นตัวไหนมีสัญญาณซื้อแข็งแกร่งที่สุดตอนนี้?",
        "ms": "Saham mana yang mempunyai setup beli paling kuat sekarang?"}),
    ("copilot_q_screener_2", "copilot", {
        "en": "Show me oversold stocks with high volume — potential bounce plays",
        "zh": "显示超卖且成交量大的股票——可能反弹的标的",
        "zh-TW": "顯示超賣且成交量大的股票——可能反彈的標的",
        "ja": "出来高の多い売られすぎ銘柄を表示 — リバウンド候補",
        "ko": "거래량이 많은 과매도 종목 보여주세요 — 반등 가능성",
        "vi": "Cho xem cổ phiếu quá bán với khối lượng cao — khả năng bật lại",
        "th": "แสดงหุ้นที่ถูกขายมากเกินไปพร้อมปริมาณสูง — โอกาสเด้ง",
        "ms": "Tunjukkan saham terlebih jual dengan volum tinggi — potensi lantunan"}),
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
