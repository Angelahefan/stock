#!/usr/bin/env python3
"""
Phase 2 seed: Add translation keys used by datapai-tinyfish (Next.js)
that were missing from the initial Phase 1 seed.

These keys come directly from lib/translations.ts in datapai-tinyfish.
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
    # ── Language toggle / meta ──
    ("lang_toggle", "common", {
        "en": "中文", "zh": "EN", "zh-TW": "EN", "ja": "EN", "ko": "EN", "vi": "EN", "th": "EN", "ms": "EN",
    }),
    ("lang_label", "common", {
        "en": "English", "zh": "中文", "zh-TW": "繁體中文", "ja": "日本語", "ko": "한국어", "vi": "Tiếng Việt", "th": "ภาษาไทย", "ms": "Bahasa Melayu",
    }),

    # ── Navigation (missing from Phase 1) ──
    ("nav_poweredBy", "nav", {
        "en": "Powered by", "zh": "技术支持", "zh-TW": "技術支持", "ja": "提供", "ko": "제공", "vi": "Cung cấp bởi", "th": "ขับเคลื่อนโดย", "ms": "Dikuasakan oleh",
    }),

    # ── Footer (camelCase variants matching TS) ──
    ("footer_poweredBy", "footer", {
        "en": "powered by", "zh": "由", "zh-TW": "由", "ja": "提供", "ko": "제공", "vi": "được cung cấp bởi", "th": "ขับเคลื่อนโดย", "ms": "dikuasakan oleh",
    }),
    ("footer_and", "footer", {
        "en": "&", "zh": "和", "zh-TW": "和", "ja": "&", "ko": "&", "vi": "&", "th": "&", "ms": "&",
    }),
    ("footer_realBrowser", "footer", {
        "en": "real-browser technology", "zh": "真实浏览器技术", "zh-TW": "真實瀏覽器技術", "ja": "リアルブラウザ技術", "ko": "실제 브라우저 기술", "vi": "công nghệ trình duyệt thực", "th": "เทคโนโลยีเบราว์เซอร์จริง", "ms": "teknologi pelayar sebenar",
    }),
    ("footer_aiFramework", "footer", {
        "en": "AI agent framework", "zh": "AI代理框架", "zh-TW": "AI代理框架", "ja": "AIエージェントフレームワーク", "ko": "AI 에이전트 프레임워크", "vi": "khung AI agent", "th": "เฟรมเวิร์ก AI agent", "ms": "rangka kerja ejen AI",
    }),
    ("footer_websiteIntel", "footer", {
        "en": "Website Change Intelligence", "zh": "网站变动情报", "zh-TW": "網站變動情報", "ja": "ウェブサイト変更インテリジェンス", "ko": "웹사이트 변경 인텔리전스", "vi": "Phân tích thay đổi website", "th": "ข้อมูลการเปลี่ยนแปลงเว็บไซต์", "ms": "Perisikan Perubahan Laman Web",
    }),

    # ── AI analysis landing (/intel) ──
    ("intel_badge", "intel", {
        "en": "⚡ AI analysis", "zh": "⚡ AI分析", "zh-TW": "⚡ AI分析", "ja": "⚡ AI分析", "ko": "⚡ AI분석", "vi": "⚡ Phân tích AI", "th": "⚡ AI วิเคราะห์", "ms": "⚡ Analisis AI",
    }),
    ("intel_hero_title", "intel", {
        "en": "Real-time AI signals for any stock", "zh": "任意股票的实时AI信号", "zh-TW": "任意股票的即時AI訊號", "ja": "あらゆる銘柄のリアルタイムAIシグナル", "ko": "모든 종목의 실시간 AI 신호", "vi": "Tín hiệu AI thời gian thực cho mọi cổ phiếu", "th": "สัญญาณ AI แบบเรียลไทม์สำหรับทุกหุ้น", "ms": "Isyarat AI masa nyata untuk mana-mana saham",
    }),
    ("intel_hero_desc", "intel", {
        "en": "Multi-timeframe technical analysis · Gemini Vision chart patterns · ASX Trading Signal combining IR language shifts with live price data.",
        "zh": "多时间框架技术分析 · Gemini Vision图表形态识别 · ASX交易信号——结合IR语言变化与实时价格数据。",
        "zh-TW": "多時間框架技術分析 · Gemini Vision圖表形態識別 · ASX交易訊號——結合IR語言變化與即時價格數據。",
        "ja": "マルチタイムフレームテクニカル分析 · Gemini Visionチャートパターン · ASXトレーディングシグナル。",
        "ko": "다중 시간프레임 기술적 분석 · Gemini Vision 차트 패턴 · ASX 트레이딩 시그널。",
        "vi": "Phân tích kỹ thuật đa khung thời gian · Nhận dạng mẫu biểu đồ Gemini Vision · Tín hiệu giao dịch ASX.",
        "th": "วิเคราะห์เทคนิคหลายกรอบเวลา · รูปแบบกราฟ Gemini Vision · สัญญาณการซื้อขาย ASX",
        "ms": "Analisis teknikal pelbagai jangka masa · Corak carta Gemini Vision · Isyarat dagangan ASX.",
    }),
    ("intel_search", "intel", {
        "en": "Search stock → AI analysis…", "zh": "搜索股票 → AI分析…", "zh-TW": "搜尋股票 → AI分析…", "ja": "銘柄検索 → AI分析…", "ko": "종목 검색 → AI 분석…", "vi": "Tìm cổ phiếu → Phân tích AI…", "th": "ค้นหาหุ้น → วิเคราะห์ AI…", "ms": "Cari saham → Analisis AI…",
    }),
    ("intel_withSignal", "intel", {
        "en": "⚡ Stocks with recent AI signal", "zh": "⚡ 近期有AI信号的股票", "zh-TW": "⚡ 近期有AI訊號的股票", "ja": "⚡ 最近のAIシグナルがある銘柄", "ko": "⚡ 최근 AI 신호가 있는 종목", "vi": "⚡ Cổ phiếu có tín hiệu AI gần đây", "th": "⚡ หุ้นที่มีสัญญาณ AI ล่าสุด", "ms": "⚡ Saham dengan isyarat AI terkini",
    }),
    ("intel_period", "intel", {
        "en": "(last 24 hours)", "zh": "（最近24小时）", "zh-TW": "（最近24小時）", "ja": "（過去24時間）", "ko": "（최근 24시간）", "vi": "(24 giờ qua)", "th": "(24 ชั่วโมงที่ผ่านมา)", "ms": "(24 jam lepas)",
    }),
    ("intel_allStocks", "intel", {
        "en": "All monitored stocks", "zh": "所有监控股票", "zh-TW": "所有監控股票", "ja": "全モニタリング銘柄", "ko": "전체 모니터링 종목", "vi": "Tất cả cổ phiếu theo dõi", "th": "หุ้นทั้งหมดที่ติดตาม", "ms": "Semua saham yang dipantau",
    }),
    ("intel_clickGenerate", "intel", {
        "en": "Monitored universe — click to generate AI signal", "zh": "监控范围 — 点击生成AI信号", "zh-TW": "監控範圍 — 點擊生成AI訊號", "ja": "モニタリング対象 — クリックでAIシグナル生成", "ko": "모니터링 대상 — 클릭하여 AI 신호 생성", "vi": "Danh mục theo dõi — nhấp để tạo tín hiệu AI", "th": "กลุ่มที่ติดตาม — คลิกเพื่อสร้างสัญญาณ AI", "ms": "Semesta pantauan — klik untuk jana isyarat AI",
    }),
    ("intel_noSignal", "intel", {
        "en": "no signal yet", "zh": "暂无信号", "zh-TW": "暫無訊號", "ja": "シグナルなし", "ko": "신호 없음", "vi": "chưa có tín hiệu", "th": "ยังไม่มีสัญญาณ", "ms": "belum ada isyarat",
    }),
    ("intel_whatIs", "intel", {
        "en": "What is AI analysis?", "zh": "什么是AI分析？", "zh-TW": "什麼是AI分析？", "ja": "AI分析とは？", "ko": "AI 분석이란?", "vi": "Phân tích AI là gì?", "th": "AI วิเคราะห์คืออะไร?", "ms": "Apakah analisis AI?",
    }),
    ("intel_ta_heading", "intel", {
        "en": "📈 Technical Analysis (TA)", "zh": "📈 技术分析(TA)", "zh-TW": "📈 技術分析(TA)", "ja": "📈 テクニカル分析(TA)", "ko": "📈 기술적 분석(TA)", "vi": "📈 Phân tích kỹ thuật (TA)", "th": "📈 วิเคราะห์เทคนิค (TA)", "ms": "📈 Analisis Teknikal (TA)",
    }),
    ("intel_ta_desc", "intel", {
        "en": "Multi-timeframe OHLCV data (5m / 30m / 1h / 1d) → RSI, MACD, Bollinger, EMA → Gemini primary analysis → GPT‑5.1 compliance review → structured BUY/HOLD/SELL signal.",
        "zh": "多时间框架OHLCV数据（5分/30分/1小时/1天）→ RSI、MACD、布林带、EMA → Gemini主分析 → GPT‑5.1合规审核 → 结构化买入/持有/卖出信号。",
        "zh-TW": "多時間框架OHLCV數據（5分/30分/1小時/1天）→ RSI、MACD、布林帶、EMA → Gemini主分析 → GPT‑5.1合規審核 → 結構化買入/持有/賣出訊號。",
        "ja": "マルチタイムフレームOHLCVデータ → RSI、MACD、ボリンジャー、EMA → Gemini分析 → GPT‑5.1コンプライアンス → BUY/HOLD/SELLシグナル。",
        "ko": "다중 시간프레임 OHLCV 데이터 → RSI, MACD, 볼린저, EMA → Gemini 분석 → GPT‑5.1 검토 → BUY/HOLD/SELL 시그널。",
        "vi": "Dữ liệu OHLCV đa khung thời gian → RSI, MACD, Bollinger, EMA → Gemini phân tích → GPT‑5.1 đánh giá → tín hiệu MUA/GIỮ/BÁN.",
        "th": "ข้อมูล OHLCV หลายกรอบเวลา → RSI, MACD, Bollinger, EMA → Gemini วิเคราะห์ → GPT‑5.1 ตรวจสอบ → สัญญาณ ซื้อ/ถือ/ขาย",
        "ms": "Data OHLCV pelbagai jangka masa → RSI, MACD, Bollinger, EMA → Gemini analisis → GPT‑5.1 semakan → isyarat BELI/PEGANG/JUAL.",
    }),
    ("intel_chart_heading", "intel", {
        "en": "📊 Chart Analysis (CA)", "zh": "📊 图表分析(CA)", "zh-TW": "📊 圖表分析(CA)", "ja": "📊 チャート分析(CA)", "ko": "📊 차트 분석(CA)", "vi": "📊 Phân tích biểu đồ (CA)", "th": "📊 วิเคราะห์กราฟ (CA)", "ms": "📊 Analisis Carta (CA)",
    }),
    ("intel_chart_desc", "intel", {
        "en": "Renders a 3-panel dark chart (Price+BBands / RSI / MACD) and sends it to Gemini Vision for real-time pattern recognition — head-and-shoulders, breakouts, divergences.",
        "zh": "生成三栏图表（价格+布林带 / RSI / MACD），发送给Gemini Vision进行实时形态识别——头肩顶、突破、背离等。",
        "zh-TW": "生成三欄圖表（價格+布林帶 / RSI / MACD），發送給Gemini Vision進行即時形態識別——頭肩頂、突破、背離等。",
        "ja": "3パネルチャート（価格+BB / RSI / MACD）をGemini Visionに送信し、パターン認識を実行。",
        "ko": "3패널 차트（가격+BB / RSI / MACD）를 Gemini Vision으로 전송하여 패턴 인식 실행。",
        "vi": "Tạo biểu đồ 3 bảng gửi đến Gemini Vision nhận dạng mẫu hình — vai đầu vai, phá vỡ, phân kỳ.",
        "th": "สร้างกราฟ 3 แผง ส่งไปยัง Gemini Vision เพื่อจดจำรูปแบบ — หัวและไหล่ การทะลุ การแยกตัว",
        "ms": "Menjana carta 3 panel dan menghantarnya ke Gemini Vision untuk pengecaman corak masa nyata.",
    }),
    ("intel_asx_heading", "intel", {
        "en": "🎯 ASX Trading Signal", "zh": "🎯 ASX交易信号", "zh-TW": "🎯 ASX交易訊號", "ja": "🎯 ASXトレーディングシグナル", "ko": "🎯 ASX 트레이딩 시그널", "vi": "🎯 Tín hiệu giao dịch ASX", "th": "🎯 สัญญาณการซื้อขาย ASX", "ms": "🎯 Isyarat Dagangan ASX",
    }),
    ("intel_asx_desc", "intel", {
        "en": "Unique to DataP.ai: combines TinyFish IR page language intelligence with live multi-timeframe ASX price data → STRONG BUY to STRONG SELL with entry, target and stop-loss per timeframe.",
        "zh": "DataP.ai独家：结合TinyFish IR页面语言智能与实时多时间框架ASX价格数据 → 强烈买入至强烈卖出，附各时间框架入场价、目标价及止损位。",
        "zh-TW": "DataP.ai獨家：結合TinyFish IR頁面語言智能與即時多時間框架ASX價格數據 → 強烈買入至強烈賣出。",
        "ja": "DataP.ai独自：TinyFish IR言語インテリジェンス＋リアルタイムASX価格データ → STRONG BUYからSTRONG SELLまで。",
        "ko": "DataP.ai 독점: TinyFish IR 언어 인텔리전스 + 실시간 ASX 가격 데이터 → STRONG BUY ~ STRONG SELL.",
        "vi": "Độc quyền DataP.ai: kết hợp phân tích ngôn ngữ IR TinyFish với dữ liệu giá ASX đa khung thời gian → MUA MẠNH đến BÁN MẠNH.",
        "th": "เฉพาะ DataP.ai: ผสมผสาน TinyFish IR + ข้อมูลราคา ASX หลายกรอบเวลา → ซื้อแรง ถึง ขายแรง",
        "ms": "Eksklusif DataP.ai: gabungan TinyFish IR + data harga ASX pelbagai jangka masa → BELI KUAT ke JUAL KUAT.",
    }),

    # ── Per-stock intel page (/ticker/[sym]/intel) ──
    ("stock_breadcrumb", "stock", {
        "en": "AI analysis", "zh": "AI分析", "zh-TW": "AI分析", "ja": "AI分析", "ko": "AI분석", "vi": "Phân tích AI", "th": "AI วิเคราะห์", "ms": "Analisis AI",
    }),
    ("stock_pipeline_tf", "stock", {
        "en": "🌊 TinyFish IR scan", "zh": "🌊 TinyFish IR扫描", "zh-TW": "🌊 TinyFish IR掃描", "ja": "🌊 TinyFish IRスキャン", "ko": "🌊 TinyFish IR 스캔", "vi": "🌊 TinyFish IR quét", "th": "🌊 TinyFish IR สแกน", "ms": "🌊 TinyFish IR imbasan",
    }),
    ("stock_pipeline_yf", "stock", {
        "en": "Yahoo Finance OHLCV", "zh": "Yahoo财经OHLCV", "zh-TW": "Yahoo財經OHLCV", "ja": "Yahoo Finance OHLCV", "ko": "Yahoo Finance OHLCV", "vi": "Yahoo Finance OHLCV", "th": "Yahoo Finance OHLCV", "ms": "Yahoo Finance OHLCV",
    }),
    ("stock_pipeline_ai", "stock", {
        "en": "Gemini + GPT‑5.1", "zh": "Gemini + GPT‑5.1", "zh-TW": "Gemini + GPT‑5.1", "ja": "Gemini + GPT‑5.1", "ko": "Gemini + GPT‑5.1", "vi": "Gemini + GPT‑5.1", "th": "Gemini + GPT‑5.1", "ms": "Gemini + GPT‑5.1",
    }),
    ("stock_pipeline_sig", "stock", {
        "en": "Actionable Signal", "zh": "可操作信号", "zh-TW": "可操作訊號", "ja": "アクショナブルシグナル", "ko": "실행 가능 시그널", "vi": "Tín hiệu hành động", "th": "สัญญาณที่ดำเนินการได้", "ms": "Isyarat Boleh Tindak",
    }),
    ("stock_cta_ir", "stock", {
        "en": "← IR Signal page", "zh": "← IR信号页", "zh-TW": "← IR訊號頁", "ja": "← IRシグナルページ", "ko": "← IR 시그널 페이지", "vi": "← Trang tín hiệu IR", "th": "← หน้าสัญญาณ IR", "ms": "← Halaman isyarat IR",
    }),
    ("stock_cta_report", "stock", {
        "en": "📋 Full Report", "zh": "📋 完整报告", "zh-TW": "📋 完整報告", "ja": "📋 フルレポート", "ko": "📋 전체 보고서", "vi": "📋 Báo cáo đầy đủ", "th": "📋 รายงานเต็ม", "ms": "📋 Laporan Penuh",
    }),
    ("stock_other", "stock", {
        "en": "Other stocks in the monitored universe", "zh": "监控范围内的其他股票", "zh-TW": "監控範圍內的其他股票", "ja": "モニタリング対象の他の銘柄", "ko": "모니터링 대상의 다른 종목", "vi": "Các cổ phiếu khác trong danh mục theo dõi", "th": "หุ้นอื่นๆ ในกลุ่มที่ติดตาม", "ms": "Saham lain dalam semesta pantauan",
    }),

    # ── TechAnalyticsPanel ──
    ("panel_heading", "panel", {
        "en": "⚡ AI analysis", "zh": "⚡ AI分析", "zh-TW": "⚡ AI分析", "ja": "⚡ AI分析", "ko": "⚡ AI분석", "vi": "⚡ Phân tích AI", "th": "⚡ AI วิเคราะห์", "ms": "⚡ Analisis AI",
    }),
    ("panel_tf", "panel", {
        "en": "🌊 TinyFish IR scan", "zh": "🌊 TinyFish IR扫描", "zh-TW": "🌊 TinyFish IR掃描", "ja": "🌊 TinyFish IRスキャン", "ko": "🌊 TinyFish IR 스캔", "vi": "🌊 TinyFish IR quét", "th": "🌊 TinyFish IR สแกน", "ms": "🌊 TinyFish IR imbasan",
    }),
    ("panel_yf", "panel", {
        "en": "Yahoo Finance OHLCV", "zh": "Yahoo财经OHLCV", "zh-TW": "Yahoo財經OHLCV", "ja": "Yahoo Finance OHLCV", "ko": "Yahoo Finance OHLCV", "vi": "Yahoo Finance OHLCV", "th": "Yahoo Finance OHLCV", "ms": "Yahoo Finance OHLCV",
    }),
    ("panel_ai", "panel", {
        "en": "Gemini + GPT‑5.1", "zh": "Gemini + GPT‑5.1", "zh-TW": "Gemini + GPT‑5.1", "ja": "Gemini + GPT‑5.1", "ko": "Gemini + GPT‑5.1", "vi": "Gemini + GPT‑5.1", "th": "Gemini + GPT‑5.1", "ms": "Gemini + GPT‑5.1",
    }),
    ("panel_sig", "panel", {
        "en": "Actionable Signal", "zh": "可操作信号", "zh-TW": "可操作訊號", "ja": "アクショナブルシグナル", "ko": "실행 가능 시그널", "vi": "Tín hiệu hành động", "th": "สัญญาณที่ดำเนินการได้", "ms": "Isyarat Boleh Tindak",
    }),
    ("panel_btn_ta", "panel", {
        "en": "📈 Technical Analysis (TA)", "zh": "📈 技术分析(TA)", "zh-TW": "📈 技術分析(TA)", "ja": "📈 テクニカル分析(TA)", "ko": "📈 기술적 분석(TA)", "vi": "📈 Phân tích kỹ thuật (TA)", "th": "📈 วิเคราะห์เทคนิค (TA)", "ms": "📈 Analisis Teknikal (TA)",
    }),
    ("panel_btn_ta_done", "panel", {
        "en": "📈 TA ✓", "zh": "📈 TA ✓", "zh-TW": "📈 TA ✓", "ja": "📈 TA ✓", "ko": "📈 TA ✓", "vi": "📈 TA ✓", "th": "📈 TA ✓", "ms": "📈 TA ✓",
    }),
    ("panel_btn_ta_loading", "panel", {
        "en": "Generating…", "zh": "生成中…", "zh-TW": "生成中…", "ja": "生成中…", "ko": "생성 중…", "vi": "Đang tạo…", "th": "กำลังสร้าง…", "ms": "Menjana…",
    }),
    ("panel_btn_chart", "panel", {
        "en": "📊 Chart Analysis (CA)", "zh": "📊 图表分析(CA)", "zh-TW": "📊 圖表分析(CA)", "ja": "📊 チャート分析(CA)", "ko": "📊 차트 분석(CA)", "vi": "📊 Phân tích biểu đồ (CA)", "th": "📊 วิเคราะห์กราฟ (CA)", "ms": "📊 Analisis Carta (CA)",
    }),
    ("panel_btn_chart_done", "panel", {
        "en": "📊 CA ✓", "zh": "📊 CA ✓", "zh-TW": "📊 CA ✓", "ja": "📊 CA ✓", "ko": "📊 CA ✓", "vi": "📊 CA ✓", "th": "📊 CA ✓", "ms": "📊 CA ✓",
    }),
    ("panel_btn_chart_loading", "panel", {
        "en": "Rendering…", "zh": "渲染中…", "zh-TW": "渲染中…", "ja": "レンダリング中…", "ko": "렌더링 중…", "vi": "Đang vẽ…", "th": "กำลังเรนเดอร์…", "ms": "Merender…",
    }),
    ("panel_btn_asx", "panel", {
        "en": "🎯 ASX Trading Signal", "zh": "🎯 ASX交易信号", "zh-TW": "🎯 ASX交易訊號", "ja": "🎯 ASXトレーディングシグナル", "ko": "🎯 ASX 트레이딩 시그널", "vi": "🎯 Tín hiệu giao dịch ASX", "th": "🎯 สัญญาณการซื้อขาย ASX", "ms": "🎯 Isyarat Dagangan ASX",
    }),
    ("panel_btn_asx_done", "panel", {
        "en": "🎯 ASX Signal ✓", "zh": "🎯 ASX信号 ✓", "zh-TW": "🎯 ASX訊號 ✓", "ja": "🎯 ASXシグナル ✓", "ko": "🎯 ASX 시그널 ✓", "vi": "🎯 ASX tín hiệu ✓", "th": "🎯 ASX สัญญาณ ✓", "ms": "🎯 ASX Isyarat ✓",
    }),
    ("panel_btn_asx_loading", "panel", {
        "en": "Analysing…", "zh": "分析中…", "zh-TW": "分析中…", "ja": "分析中…", "ko": "분석 중…", "vi": "Đang phân tích…", "th": "กำลังวิเคราะห์…", "ms": "Menganalisis…",
    }),
    ("panel_ta_time", "panel", {
        "en": "Typically 20–45 seconds", "zh": "通常需要20-45秒", "zh-TW": "通常需要20-45秒", "ja": "通常20〜45秒", "ko": "보통 20-45초", "vi": "Thường 20–45 giây", "th": "โดยปกติ 20–45 วินาที", "ms": "Biasanya 20–45 saat",
    }),
    ("panel_chart_time", "panel", {
        "en": "Typically 15–30 seconds", "zh": "通常需要15-30秒", "zh-TW": "通常需要15-30秒", "ja": "通常15〜30秒", "ko": "보통 15-30초", "vi": "Thường 15–30 giây", "th": "โดยปกติ 15–30 วินาที", "ms": "Biasanya 15–30 saat",
    }),
    ("panel_asx_time", "panel", {
        "en": "Typically 30–60 seconds", "zh": "通常需要30-60秒", "zh-TW": "通常需要30-60秒", "ja": "通常30〜60秒", "ko": "보통 30-60초", "vi": "Thường 30–60 giây", "th": "โดยปกติ 30–60 วินาที", "ms": "Biasanya 30–60 saat",
    }),
    ("panel_tf_context", "panel", {
        "en": "chars from TinyFish IR scan", "zh": "字符来自TinyFish IR扫描", "zh-TW": "字符來自TinyFish IR掃描", "ja": "文字（TinyFish IRスキャン）", "ko": "문자（TinyFish IR 스캔）", "vi": "ký tự từ TinyFish IR", "th": "อักขระจาก TinyFish IR", "ms": "aksara dari TinyFish IR",
    }),
    ("panel_ta_title", "panel", {
        "en": "📈 Technical Analysis (TA)", "zh": "📈 技术分析(TA)", "zh-TW": "📈 技術分析(TA)", "ja": "📈 テクニカル分析(TA)", "ko": "📈 기술적 분석(TA)", "vi": "📈 Phân tích kỹ thuật (TA)", "th": "📈 วิเคราะห์เทคนิค (TA)", "ms": "📈 Analisis Teknikal (TA)",
    }),
    ("panel_asx_title", "panel", {
        "en": "🎯 ASX Trading Signal", "zh": "🎯 ASX交易信号", "zh-TW": "🎯 ASX交易訊號", "ja": "🎯 ASXトレーディングシグナル", "ko": "🎯 ASX 트레이딩 시그널", "vi": "🎯 Tín hiệu giao dịch ASX", "th": "🎯 สัญญาณการซื้อขาย ASX", "ms": "🎯 Isyarat Dagangan ASX",
    }),
    ("panel_asx_notice", "panel", {
        "en": "⚠ Signal based on latest IR page content + live ASX price data. Google Search grounding enabled.",
        "zh": "⚠ 信号基于最新IR页面内容 + 实时ASX价格数据。已启用Google搜索增强。",
        "zh-TW": "⚠ 訊號基於最新IR頁面內容 + 即時ASX價格數據。已啟用Google搜尋增強。",
        "ja": "⚠ 最新IRページ + リアルタイムASX価格データに基づくシグナル。Google検索グラウンディング有効。",
        "ko": "⚠ 최신 IR 페이지 + 실시간 ASX 가격 데이터 기반 시그널. Google 검색 그라운딩 활성화.",
        "vi": "⚠ Tín hiệu dựa trên nội dung IR mới nhất + dữ liệu giá ASX. Đã bật Google Search.",
        "th": "⚠ สัญญาณจากเนื้อหา IR ล่าสุด + ข้อมูลราคา ASX Google Search grounding เปิดใช้งาน",
        "ms": "⚠ Isyarat berdasarkan kandungan IR terkini + data harga ASX. Google Search grounding diaktifkan.",
    }),
    ("panel_collapse", "panel", {
        "en": "▲ collapse", "zh": "▲ 收起", "zh-TW": "▲ 收起", "ja": "▲ 折りたたむ", "ko": "▲ 접기", "vi": "▲ thu gọn", "th": "▲ ย่อ", "ms": "▲ tutup",
    }),
    ("panel_expand", "panel", {
        "en": "▼ expand", "zh": "▼ 展开", "zh-TW": "▼ 展開", "ja": "▼ 展開", "ko": "▼ 펼치기", "vi": "▼ mở rộng", "th": "▼ ขยาย", "ms": "▼ buka",
    }),
    ("panel_not_advice", "panel", {
        "en": "NOT financial advice", "zh": "非投资建议", "zh-TW": "非投資建議", "ja": "投資助言ではありません", "ko": "투자 조언이 아닙니다", "vi": "Không phải tư vấn đầu tư", "th": "ไม่ใช่คำแนะนำการลงทุน", "ms": "BUKAN nasihat kewangan",
    }),
    ("panel_modal_title", "panel", {
        "en": "📊 Chart Analysis (CA)", "zh": "📊 图表分析(CA)", "zh-TW": "📊 圖表分析(CA)", "ja": "📊 チャート分析(CA)", "ko": "📊 차트 분석(CA)", "vi": "📊 Phân tích biểu đồ (CA)", "th": "📊 วิเคราะห์กราฟ (CA)", "ms": "📊 Analisis Carta (CA)",
    }),
    ("panel_modal_close", "panel", {
        "en": "Close", "zh": "关闭", "zh-TW": "關閉", "ja": "閉じる", "ko": "닫기", "vi": "Đóng", "th": "ปิด", "ms": "Tutup",
    }),
]
# fmt: on

# ── Insert ──
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

    # Verify
    cur.execute("SELECT COUNT(*) FROM datapai.sys_lang_labels")
    total = cur.fetchone()[0]
    print(f"\nTotal labels in DB: {total}")

    cur.execute("SELECT lang, COUNT(*) FROM datapai.sys_lang_labels GROUP BY lang ORDER BY lang")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")

conn.close()
print("\nDone.")
