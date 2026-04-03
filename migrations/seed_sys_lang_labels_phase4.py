#!/usr/bin/env python3
"""
Phase 4 seed: i18n labels for ticker detail page, analysis buttons,
and remaining hardcoded English.
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
    # ── Analyse button ──
    ("analyse_btn", "common", {
        "en": "Analyse", "zh": "分析", "zh-TW": "分析", "ja": "分析", "ko": "분석", "vi": "Phân tích", "th": "วิเคราะห์", "ms": "Analisis",
    }),

    # ── Back navigation ──
    ("back_to_home", "nav", {
        "en": "Back to Home", "zh": "返回首页", "zh-TW": "返回首頁", "ja": "ホームに戻る", "ko": "홈으로 돌아가기", "vi": "Về trang chủ", "th": "กลับหน้าหลัก", "ms": "Kembali ke laman utama",
    }),
    ("back_to_indexes", "nav", {
        "en": "Back to Indexes", "zh": "返回指数", "zh-TW": "返回指數", "ja": "指数に戻る", "ko": "지수로 돌아가기", "vi": "Quay lại chỉ số", "th": "กลับไปดัชนี", "ms": "Kembali ke indeks",
    }),

    # ── Ticker hero ──
    ("ticker_all_alerts", "ticker", {
        "en": "All Alerts", "zh": "所有预警", "zh-TW": "所有預警", "ja": "全アラート", "ko": "전체 알림", "vi": "Tất cả cảnh báo", "th": "การแจ้งเตือนทั้งหมด", "ms": "Semua amaran",
    }),
    ("ticker_ir_report", "ticker", {
        "en": "IR Signal Report", "zh": "IR信号报告", "zh-TW": "IR信號報告", "ja": "IRシグナルレポート", "ko": "IR 시그널 리포트", "vi": "Báo cáo tín hiệu IR", "th": "รายงานสัญญาณ IR", "ms": "Laporan isyarat IR",
    }),

    # ── Analysis buttons ──
    ("ticker_ta_btn", "ticker", {
        "en": "Technical Analysis (TA)", "zh": "技术分析 (TA)", "zh-TW": "技術分析 (TA)", "ja": "テクニカル分析 (TA)", "ko": "기술적 분석 (TA)", "vi": "Phân tích kỹ thuật (TA)", "th": "วิเคราะห์เทคนิค (TA)", "ms": "Analisis teknikal (TA)",
    }),
    ("ticker_fa_btn", "ticker", {
        "en": "Fundamental Analysis (FA)", "zh": "基本面分析 (FA)", "zh-TW": "基本面分析 (FA)", "ja": "ファンダメンタル分析 (FA)", "ko": "기본적 분석 (FA)", "vi": "Phân tích cơ bản (FA)", "th": "วิเคราะห์ปัจจัยพื้นฐาน (FA)", "ms": "Analisis asas (FA)",
    }),
    ("ticker_ma_btn", "ticker", {
        "en": "Market Analysis (MA)", "zh": "市场分析 (MA)", "zh-TW": "市場分析 (MA)", "ja": "市場分析 (MA)", "ko": "시장 분석 (MA)", "vi": "Phân tích thị trường (MA)", "th": "วิเคราะห์ตลาด (MA)", "ms": "Analisis pasaran (MA)",
    }),
    ("ticker_ca_btn", "ticker", {
        "en": "Chart Analysis (CA)", "zh": "图表分析 (CA)", "zh-TW": "圖表分析 (CA)", "ja": "チャート分析 (CA)", "ko": "차트 분석 (CA)", "vi": "Phân tích biểu đồ (CA)", "th": "วิเคราะห์กราฟ (CA)", "ms": "Analisis carta (CA)",
    }),

    # ── Section headers ──
    ("ticker_signal_detection", "ticker", {
        "en": "Signal Detection", "zh": "信号检测", "zh-TW": "信號檢測", "ja": "シグナル検出", "ko": "시그널 감지", "vi": "Phát hiện tín hiệu", "th": "การตรวจจับสัญญาณ", "ms": "Pengesanan isyarat",
    }),
    ("ticker_language_shift", "ticker", {
        "en": "Language Shift Scores", "zh": "语言转变评分", "zh-TW": "語言轉變評分", "ja": "言語変化スコア", "ko": "언어 변화 점수", "vi": "Điểm thay đổi ngôn ngữ", "th": "คะแนนการเปลี่ยนแปลงภาษา", "ms": "Skor perubahan bahasa",
    }),
    ("ticker_language_shift_desc", "ticker", {
        "en": "New vs. previous scan · per 1,000 words on cleaned text",
        "zh": "新旧扫描对比 · 每1,000个词（清理后文本）",
        "zh-TW": "新舊掃描對比 · 每1,000個詞（清理後文本）",
        "ja": "新旧スキャン比較 · クリーンテキスト1,000語あたり",
        "ko": "신규 vs 이전 스캔 · 정제 텍스트 1,000단어 기준",
        "vi": "So sánh quét mới vs cũ · trên 1.000 từ văn bản đã xử lý",
        "th": "สแกนใหม่ vs เก่า · ต่อ 1,000 คำในข้อความที่ทำความสะอาด",
        "ms": "Imbasan baru vs sebelumnya · per 1,000 perkataan teks bersih",
    }),
    ("ticker_cross_validation", "ticker", {
        "en": "Cross-Validation", "zh": "交叉验证", "zh-TW": "交叉驗證", "ja": "クロスバリデーション", "ko": "교차 검증", "vi": "Xác minh chéo", "th": "การตรวจสอบข้าม", "ms": "Pengesahan silang",
    }),
    ("ticker_cross_validation_desc", "ticker", {
        "en": "Signal verified against filings · press releases · public sources",
        "zh": "信号通过文件、新闻稿、公开来源验证",
        "zh-TW": "信號通過文件、新聞稿、公開來源驗證",
        "ja": "シグナルを提出書類・プレスリリース・公開情報で検証",
        "ko": "공시·보도자료·공개 자료를 통한 시그널 검증",
        "vi": "Tín hiệu xác minh qua hồ sơ · thông cáo báo chí · nguồn công khai",
        "th": "สัญญาณตรวจสอบกับเอกสาร · ข่าวประชาสัมพันธ์ · แหล่งข้อมูลสาธารณะ",
        "ms": "Isyarat disahkan terhadap pemfailan · siaran akhbar · sumber awam",
    }),
    ("ticker_investigation", "ticker", {
        "en": "Investigation", "zh": "调查", "zh-TW": "調查", "ja": "調査", "ko": "조사", "vi": "Điều tra", "th": "การสอบสวน", "ms": "Penyiasatan",
    }),
    ("ticker_investigation_desc", "ticker", {
        "en": "Probes press releases · exchange filings · IR pages for corroborating evidence",
        "zh": "探查新闻稿、交易所文件、IR页面以获取佐证",
        "zh-TW": "探查新聞稿、交易所文件、IR頁面以獲取佐證",
        "ja": "プレスリリース・取引所提出書類・IRページで裏付け証拠を調査",
        "ko": "보도자료·거래소 공시·IR 페이지에서 뒷받침 증거 조사",
        "vi": "Kiểm tra thông cáo báo chí · hồ sơ sàn giao dịch · trang IR để tìm bằng chứng",
        "th": "ตรวจสอบข่าวประชาสัมพันธ์ · เอกสารตลาด · หน้า IR เพื่อหาหลักฐาน",
        "ms": "Menyelidik siaran akhbar · pemfailan bursa · halaman IR untuk bukti menyokong",
    }),
    ("ticker_price_context", "ticker", {
        "en": "Price Context", "zh": "价格背景", "zh-TW": "價格背景", "ja": "価格コンテキスト", "ko": "가격 맥락", "vi": "Bối cảnh giá", "th": "บริบทราคา", "ms": "Konteks harga",
    }),
    ("ticker_price_context_desc", "ticker", {
        "en": "30-day chart · orange markers = scan dates",
        "zh": "30天图表 · 橙色标记 = 扫描日期",
        "zh-TW": "30天圖表 · 橙色標記 = 掃描日期",
        "ja": "30日チャート · オレンジマーカー = スキャン日",
        "ko": "30일 차트 · 주황 마커 = 스캔 날짜",
        "vi": "Biểu đồ 30 ngày · điểm cam = ngày quét",
        "th": "กราฟ 30 วัน · เครื่องหมายสีส้ม = วันที่สแกน",
        "ms": "Carta 30 hari · penanda oren = tarikh imbasan",
    }),
    ("ticker_change_history", "ticker", {
        "en": "Change History", "zh": "变更历史", "zh-TW": "變更歷史", "ja": "変更履歴", "ko": "변경 이력", "vi": "Lịch sử thay đổi", "th": "ประวัติการเปลี่ยนแปลง", "ms": "Sejarah perubahan",
    }),

    # ── Signal card labels ──
    ("ticker_signal_type", "ticker", {
        "en": "Signal Type", "zh": "信号类型", "zh-TW": "信號類型", "ja": "シグナルタイプ", "ko": "시그널 유형", "vi": "Loại tín hiệu", "th": "ประเภทสัญญาณ", "ms": "Jenis isyarat",
    }),
    ("ticker_severity", "ticker", {
        "en": "Severity", "zh": "严重程度", "zh-TW": "嚴重程度", "ja": "深刻度", "ko": "심각도", "vi": "Mức độ nghiêm trọng", "th": "ความรุนแรง", "ms": "Keterukan",
    }),
    ("ticker_confidence", "ticker", {
        "en": "Confidence", "zh": "置信度", "zh-TW": "置信度", "ja": "信頼度", "ko": "신뢰도", "vi": "Độ tin cậy", "th": "ความมั่นใจ", "ms": "Keyakinan",
    }),
    ("ticker_relevance_score", "ticker", {
        "en": "Relevance Score", "zh": "相关性评分", "zh-TW": "相關性評分", "ja": "関連性スコア", "ko": "관련성 점수", "vi": "Điểm liên quan", "th": "คะแนนความเกี่ยวข้อง", "ms": "Skor kaitan",
    }),
    ("ticker_financial_relevance", "ticker", {
        "en": "Financial Relevance", "zh": "财务相关性", "zh-TW": "財務相關性", "ja": "財務関連性", "ko": "재무 관련성", "vi": "Liên quan tài chính", "th": "ความเกี่ยวข้องทางการเงิน", "ms": "Kaitan kewangan",
    }),

    # ── Language shift score labels ──
    ("ticker_commitment", "ticker", {
        "en": "Commitment", "zh": "承诺", "zh-TW": "承諾", "ja": "コミットメント", "ko": "약속", "vi": "Cam kết", "th": "ความมุ่งมั่น", "ms": "Komitmen",
    }),
    ("ticker_hedging", "ticker", {
        "en": "Hedging", "zh": "对冲", "zh-TW": "對沖", "ja": "ヘッジ", "ko": "헤징", "vi": "Phòng vệ", "th": "การป้องกันความเสี่ยง", "ms": "Lindung nilai",
    }),
    ("ticker_risk_words", "ticker", {
        "en": "Risk Words", "zh": "风险词", "zh-TW": "風險詞", "ja": "リスクワード", "ko": "리스크 용어", "vi": "Từ rủi ro", "th": "คำเสี่ยง", "ms": "Perkataan risiko",
    }),
    ("ticker_overall_score", "ticker", {
        "en": "Overall Score", "zh": "综合评分", "zh-TW": "綜合評分", "ja": "総合スコア", "ko": "종합 점수", "vi": "Điểm tổng hợp", "th": "คะแนนรวม", "ms": "Skor keseluruhan",
    }),

    # ── Agent flow pipeline labels ──
    ("ticker_flow_diff", "ticker", {
        "en": "Diff Engine", "zh": "差异引擎", "zh-TW": "差異引擎", "ja": "差分エンジン", "ko": "차이 엔진", "vi": "Công cụ so sánh", "th": "เครื่องมือเปรียบเทียบ", "ms": "Enjin perbezaan",
    }),
    ("ticker_flow_quality", "ticker", {
        "en": "Signal Quality Filter", "zh": "信号质量过滤", "zh-TW": "信號質量過濾", "ja": "シグナル品質フィルター", "ko": "시그널 품질 필터", "vi": "Bộ lọc chất lượng tín hiệu", "th": "ตัวกรองคุณภาพสัญญาณ", "ms": "Penapis kualiti isyarat",
    }),
    ("ticker_flow_signal", "ticker", {
        "en": "Financial Signal Agent", "zh": "金融信号代理", "zh-TW": "金融信號代理", "ja": "金融シグナルエージェント", "ko": "금융 시그널 에이전트", "vi": "Đại lý tín hiệu tài chính", "th": "เอเจนต์สัญญาณการเงิน", "ms": "Ejen isyarat kewangan",
    }),
    ("ticker_flow_investigation", "ticker", {
        "en": "Investigation Agent", "zh": "调查代理", "zh-TW": "調查代理", "ja": "調査エージェント", "ko": "조사 에이전트", "vi": "Đại lý điều tra", "th": "เอเจนต์สอบสวน", "ms": "Ejen penyiasatan",
    }),
    ("ticker_flow_validation", "ticker", {
        "en": "Cross-Validation Agent", "zh": "交叉验证代理", "zh-TW": "交叉驗證代理", "ja": "クロスバリデーションエージェント", "ko": "교차 검증 에이전트", "vi": "Đại lý xác minh chéo", "th": "เอเจนต์ตรวจสอบข้าม", "ms": "Ejen pengesahan silang",
    }),
    ("ticker_flow_explanation", "ticker", {
        "en": "AI Explanation", "zh": "AI解释", "zh-TW": "AI解釋", "ja": "AI解説", "ko": "AI 설명", "vi": "Giải thích AI", "th": "คำอธิบาย AI", "ms": "Penjelasan AI",
    }),

    # ── Price context stats ──
    ("ticker_last_close", "ticker", {
        "en": "Last close", "zh": "上次收盘", "zh-TW": "上次收盤", "ja": "前回終値", "ko": "최종 종가", "vi": "Đóng cửa gần nhất", "th": "ปิดล่าสุด", "ms": "Penutupan terakhir",
    }),
    ("ticker_1d_change", "ticker", {
        "en": "1d change", "zh": "1日变动", "zh-TW": "1日變動", "ja": "1日変動", "ko": "1일 변동", "vi": "Thay đổi 1 ngày", "th": "เปลี่ยนแปลง 1 วัน", "ms": "Perubahan 1 hari",
    }),
    ("ticker_5d_range", "ticker", {
        "en": "5d range", "zh": "5日范围", "zh-TW": "5日範圍", "ja": "5日レンジ", "ko": "5일 범위", "vi": "Phạm vi 5 ngày", "th": "ช่วง 5 วัน", "ms": "Julat 5 hari",
    }),

    # ── Index page ──
    ("ticker_price_chart", "ticker", {
        "en": "90-Day Price Chart", "zh": "90天价格图", "zh-TW": "90天價格圖", "ja": "90日価格チャート", "ko": "90일 가격 차트", "vi": "Biểu đồ giá 90 ngày", "th": "กราฟราคา 90 วัน", "ms": "Carta harga 90 hari",
    }),
    ("ticker_technical_analysis", "ticker", {
        "en": "Technical Analysis", "zh": "技术分析", "zh-TW": "技術分析", "ja": "テクニカル分析", "ko": "기술적 분석", "vi": "Phân tích kỹ thuật", "th": "การวิเคราะห์เทคนิค", "ms": "Analisis teknikal",
    }),

    # ── No data state ──
    ("ticker_no_data", "ticker", {
        "en": "No scan data yet", "zh": "暂无扫描数据", "zh-TW": "暫無掃描數據", "ja": "スキャンデータなし", "ko": "스캔 데이터 없음", "vi": "Chưa có dữ liệu quét", "th": "ยังไม่มีข้อมูลสแกน", "ms": "Belum ada data imbasan",
    }),
    ("ticker_no_data_desc", "ticker", {
        "en": "Run a scan from the home page to populate signals for",
        "zh": "从首页运行扫描以获取信号 —",
        "zh-TW": "從首頁運行掃描以獲取信號 —",
        "ja": "ホームページからスキャンを実行してシグナルを取得 —",
        "ko": "홈 페이지에서 스캔을 실행하여 시그널 수집 —",
        "vi": "Chạy quét từ trang chủ để lấy tín hiệu cho",
        "th": "รันสแกนจากหน้าหลักเพื่อรวบรวมสัญญาณสำหรับ",
        "ms": "Jalankan imbasan dari laman utama untuk mendapatkan isyarat bagi",
    }),

    # ── Hero labels for US/ASX pages ──
    ("hero_title_us", "hero", {
        "en": "US Stocks · Website Change Intelligence",
        "zh": "美股 · 网站变化情报",
        "zh-TW": "美股 · 網站變化情報",
        "ja": "米国株 · ウェブサイト変更インテリジェンス",
        "ko": "미국 주식 · 웹사이트 변화 인텔리전스",
        "vi": "Cổ phiếu Mỹ · Phân tích thay đổi website",
        "th": "หุ้นสหรัฐ · ข่าวกรองการเปลี่ยนแปลงเว็บไซต์",
        "ms": "Saham AS · Perisikan perubahan laman web",
    }),
    ("hero_title_asx", "hero", {
        "en": "ASX Company Intelligence",
        "zh": "澳交所公司情报",
        "zh-TW": "澳交所公司情報",
        "ja": "ASX企業インテリジェンス",
        "ko": "ASX 기업 인텔리전스",
        "vi": "Phân tích công ty ASX",
        "th": "ข่าวกรองบริษัท ASX",
        "ms": "Perisikan syarikat ASX",
    }),
    ("hero_view_alerts", "hero", {
        "en": "View All Alerts", "zh": "查看所有预警", "zh-TW": "查看所有預警", "ja": "全アラートを表示", "ko": "전체 알림 보기", "vi": "Xem tất cả cảnh báo", "th": "ดูการแจ้งเตือนทั้งหมด", "ms": "Lihat semua amaran",
    }),

    # ── Footer ──
    ("footer_tagline", "footer", {
        "en": "Website Change Intelligence", "zh": "网站变化情报", "zh-TW": "網站變化情報", "ja": "ウェブサイト変更インテリジェンス", "ko": "웹사이트 변화 인텔리전스", "vi": "Phân tích thay đổi website", "th": "ข่าวกรองการเปลี่ยนแปลงเว็บไซต์", "ms": "Perisikan perubahan laman web",
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
