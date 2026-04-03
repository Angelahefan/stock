#!/usr/bin/env python3
"""Phase 6 seed: FA (Fundamental Analysis) markdown labels — all section headers and commentary."""
import psycopg2, psycopg2.extras, os

conn = psycopg2.connect(host=os.environ.get("PGHOST","localhost"), port=int(os.environ.get("PGPORT","5432")),
    dbname="postgres", user=os.environ.get("PGUSER","postgres"), password=os.environ.get("PGPASSWORD","postgres"))

# fmt: off
LABELS = [
    # Score bands
    ("fa_insufficient_data", "fa", {"en":"insufficient data","zh":"数据不足","zh-TW":"數據不足","ja":"データ不足","ko":"데이터 부족","vi":"Thiếu dữ liệu","th":"ข้อมูลไม่เพียงพอ","ms":"Data tidak mencukupi"}),
    ("fa_excellent", "fa", {"en":"excellent","zh":"优秀","zh-TW":"優秀","ja":"優秀","ko":"우수","vi":"Xuất sắc","th":"ยอดเยี่ยม","ms":"Cemerlang"}),
    ("fa_strong", "fa", {"en":"strong","zh":"强","zh-TW":"強","ja":"強い","ko":"강함","vi":"Mạnh","th":"แข็งแกร่ง","ms":"Kukuh"}),
    ("fa_moderate", "fa", {"en":"moderate","zh":"中等","zh-TW":"中等","ja":"普通","ko":"보통","vi":"Trung bình","th":"ปานกลาง","ms":"Sederhana"}),
    ("fa_weak", "fa", {"en":"weak","zh":"弱","zh-TW":"弱","ja":"弱い","ko":"약함","vi":"Yếu","th":"อ่อนแอ","ms":"Lemah"}),
    ("fa_very_favourable", "fa", {"en":"very favourable","zh":"非常有利","zh-TW":"非常有利","ja":"非常に良好","ko":"매우 유리","vi":"Rất thuận lợi","th":"เอื้ออำนวยมาก","ms":"Sangat menguntungkan"}),
    ("fa_favourable", "fa", {"en":"favourable","zh":"有利","zh-TW":"有利","ja":"良好","ko":"유리","vi":"Thuận lợi","th":"เอื้ออำนวย","ms":"Menguntungkan"}),
    ("fa_neutral", "fa", {"en":"neutral","zh":"中性","zh-TW":"中性","ja":"中立","ko":"중립","vi":"Trung lập","th":"เป็นกลาง","ms":"Neutral"}),
    ("fa_unfavourable", "fa", {"en":"unfavourable","zh":"不利","zh-TW":"不利","ja":"不利","ko":"불리","vi":"Bất lợi","th":"ไม่เอื้ออำนวย","ms":"Tidak menguntungkan"}),
    ("fa_very_unfavourable", "fa", {"en":"very unfavourable","zh":"非常不利","zh-TW":"非常不利","ja":"非常に不利","ko":"매우 불리","vi":"Rất bất lợi","th":"ไม่เอื้ออำนวยมาก","ms":"Sangat tidak menguntungkan"}),

    # Signal actions
    ("fa_action_strong_buy", "fa", {"en":"Strong case to accumulate / buy","zh":"强烈建议增持/买入","zh-TW":"強烈建議增持/買入","ja":"積極的な買い推奨","ko":"강력 매수/적립 신호","vi":"Khuyến nghị mạnh mua vào","th":"แนะนำสะสม/ซื้อ","ms":"Cadangan kuat untuk membeli"}),
    ("fa_action_buy", "fa", {"en":"Lean toward buying or holding long","zh":"倾向买入或持有","zh-TW":"傾向買入或持有","ja":"買いまたは長期保有寄り","ko":"매수 또는 보유 성향","vi":"Nghiêng về mua hoặc nắm giữ","th":"แนวโน้มซื้อหรือถือ","ms":"Cenderung membeli atau memegang"}),
    ("fa_action_neutral", "fa", {"en":"Hold — wait for clearer catalysts","zh":"持有——等待更明确的催化剂","zh-TW":"持有——等待更明確的催化劑","ja":"保有——より明確な材料待ち","ko":"보유 — 명확한 촉매 대기","vi":"Giữ — chờ tín hiệu rõ ràng hơn","th":"ถือ — รอตัวกระตุ้นที่ชัดเจนกว่า","ms":"Pegang — tunggu pemangkin yang lebih jelas"}),
    ("fa_action_sell", "fa", {"en":"Consider trimming or reducing exposure","zh":"考虑减持或降低敞口","zh-TW":"考慮減持或降低部位","ja":"ポジション縮小を検討","ko":"비중 축소 또는 노출 줄이기 고려","vi":"Cân nhắc giảm vị thế","th":"พิจารณาลดสัดส่วน","ms":"Pertimbangkan mengurangkan pendedahan"}),
    ("fa_action_strong_sell", "fa", {"en":"Strong case to exit the position","zh":"强烈建议退出头寸","zh-TW":"強烈建議退出部位","ja":"ポジション清算を強く推奨","ko":"포지션 청산 강력 권고","vi":"Khuyến nghị mạnh thoát vị thế","th":"แนะนำอย่างยิ่งให้ออกจากตำแหน่ง","ms":"Cadangan kuat untuk keluar"}),
    ("fa_action_insufficient", "fa", {"en":"Insufficient data to form a view","zh":"数据不足以形成观点","zh-TW":"數據不足以形成觀點","ja":"見解形成に不十分なデータ","ko":"견해를 형성하기에 데이터 부족","vi":"Không đủ dữ liệu để đánh giá","th":"ข้อมูลไม่เพียงพอที่จะสรุป","ms":"Data tidak mencukupi untuk membentuk pandangan"}),

    # Header labels
    ("fa_ai_verdict", "fa", {"en":"AI verdict","zh":"AI判断","zh-TW":"AI判斷","ja":"AI判定","ko":"AI 판정","vi":"Nhận định AI","th":"คำตัดสิน AI","ms":"Keputusan AI"}),
    ("fa_composite_score", "fa", {"en":"Composite score","zh":"综合评分","zh-TW":"綜合評分","ja":"総合スコア","ko":"종합 점수","vi":"Điểm tổng hợp","th":"คะแนนรวม","ms":"Skor komposit"}),
    ("fa_bearish", "fa", {"en":"bearish","zh":"看跌","zh-TW":"看跌","ja":"弱気","ko":"약세","vi":"giảm","th":"ขาลง","ms":"menurun"}),
    ("fa_bullish", "fa", {"en":"bullish","zh":"看涨","zh-TW":"看漲","ja":"強気","ko":"강세","vi":"tăng","th":"ขาขึ้น","ms":"menaik"}),
    ("fa_recommended_action", "fa", {"en":"Recommended action","zh":"建议操作","zh-TW":"建議操作","ja":"推奨アクション","ko":"권장 액션","vi":"Hành động khuyến nghị","th":"การดำเนินการที่แนะนำ","ms":"Tindakan yang disyorkan"}),
    ("fa_company_fundamentals", "fa", {"en":"Company Fundamentals","zh":"公司基本面","zh-TW":"公司基本面","ja":"企業ファンダメンタルズ","ko":"기업 기본 분석","vi":"Cơ bản công ty","th":"ปัจจัยพื้นฐานของบริษัท","ms":"Asas syarikat"}),
    ("fa_market_cap", "fa", {"en":"Market cap","zh":"市值","zh-TW":"市值","ja":"時価総額","ko":"시가총액","vi":"Vốn hóa","th":"มูลค่าตลาด","ms":"Permodalan pasaran"}),
    ("fa_enterprise_value", "fa", {"en":"Enterprise value","zh":"企业价值","zh-TW":"企業價值","ja":"企業価値","ko":"기업가치","vi":"Giá trị doanh nghiệp","th":"มูลค่าองค์กร","ms":"Nilai perusahaan"}),
    ("fa_valuation", "fa", {"en":"Valuation","zh":"估值","zh-TW":"估值","ja":"バリュエーション","ko":"밸류에이션","vi":"Định giá","th":"การประเมินมูลค่า","ms":"Penilaian"}),
    ("fa_score", "fa", {"en":"score","zh":"评分","zh-TW":"評分","ja":"スコア","ko":"점수","vi":"điểm","th":"คะแนน","ms":"skor"}),
    ("fa_this_sector", "fa", {"en":"this sector","zh":"该行业","zh-TW":"該行業","ja":"このセクター","ko":"이 섹터","vi":"ngành này","th":"ภาคนี้","ms":"sektor ini"}),
    ("fa_strong_yield", "fa", {"en":"strong shareholder yield","zh":"强劲股东回报","zh-TW":"強勁股東回報","ja":"高い株主利回り","ko":"높은 주주 수익률","vi":"lợi suất cổ đông cao","th":"ผลตอบแทนผู้ถือหุ้นสูง","ms":"hasil pemegang saham yang kukuh"}),
    ("fa_decent_yield", "fa", {"en":"decent cash return","zh":"不错的现金回报","zh-TW":"不錯的現金回報","ja":"まずまずのキャッシュリターン","ko":"적절한 현금 수익","vi":"lợi nhuận tiền mặt khá","th":"ผลตอบแทนเงินสดที่ดี","ms":"pulangan tunai yang baik"}),
    ("fa_low_yield", "fa", {"en":"low cash yield","zh":"低现金收益","zh-TW":"低現金收益","ja":"低キャッシュ利回り","ko":"낮은 현금 수익률","vi":"lợi suất tiền mặt thấp","th":"ผลตอบแทนเงินสดต่ำ","ms":"hasil tunai rendah"}),
    ("fa_profitability", "fa", {"en":"Profitability & Management Efficiency","zh":"盈利能力与管理效率","zh-TW":"盈利能力與管理效率","ja":"収益性と経営効率","ko":"수익성 및 경영 효율","vi":"Khả năng sinh lời & Hiệu quả quản lý","th":"ความสามารถในการทำกำไรและประสิทธิภาพการจัดการ","ms":"Keuntungan & kecekapan pengurusan"}),
    ("fa_quality_score", "fa", {"en":"quality score","zh":"质量评分","zh-TW":"質量評分","ja":"品質スコア","ko":"품질 점수","vi":"điểm chất lượng","th":"คะแนนคุณภาพ","ms":"skor kualiti"}),
    ("fa_gross_margin", "fa", {"en":"Gross margin","zh":"毛利率","zh-TW":"毛利率","ja":"粗利率","ko":"매출총이익률","vi":"Biên lợi nhuận gộp","th":"อัตรากำไรขั้นต้น","ms":"Margin kasar"}),
    ("fa_operating_margin", "fa", {"en":"Operating margin","zh":"营业利润率","zh-TW":"營業利潤率","ja":"営業利益率","ko":"영업이익률","vi":"Biên lợi nhuận hoạt động","th":"อัตรากำไรจากการดำเนินงาน","ms":"Margin operasi"}),
    ("fa_net_margin", "fa", {"en":"Net margin","zh":"净利润率","zh-TW":"淨利潤率","ja":"純利益率","ko":"순이익률","vi":"Biên lợi nhuận ròng","th":"อัตรากำไรสุทธิ","ms":"Margin bersih"}),
    ("fa_capital_returns", "fa", {"en":"Capital returns","zh":"资本回报","zh-TW":"資本回報","ja":"資本利益率","ko":"자본 수익","vi":"Lợi nhuận vốn","th":"ผลตอบแทนจากเงินทุน","ms":"Pulangan modal"}),
    ("fa_leverage", "fa", {"en":"Leverage & liquidity","zh":"杠杆与流动性","zh-TW":"槓桿與流動性","ja":"レバレッジと流動性","ko":"레버리지 및 유동성","vi":"Đòn bẩy & thanh khoản","th":"เลเวอเรจและสภาพคล่อง","ms":"Leveraj & kecairan"}),
    ("fa_current_ratio", "fa", {"en":"Current ratio","zh":"流动比率","zh-TW":"流動比率","ja":"流動比率","ko":"유동비율","vi":"Tỷ lệ thanh toán hiện hành","th":"อัตราส่วนสภาพคล่อง","ms":"Nisbah semasa"}),
    ("fa_interest_coverage", "fa", {"en":"Interest coverage","zh":"利息覆盖率","zh-TW":"利息覆蓋率","ja":"インタレストカバレッジ","ko":"이자보상배율","vi":"Hệ số thanh toán lãi","th":"อัตราส่วนความสามารถในการจ่ายดอกเบี้ย","ms":"Liputan faedah"}),
    ("fa_cash", "fa", {"en":"Cash","zh":"现金","zh-TW":"現金","ja":"現金","ko":"현금","vi":"Tiền mặt","th":"เงินสด","ms":"Tunai"}),
    ("fa_debt", "fa", {"en":"Debt","zh":"负债","zh-TW":"負債","ja":"負債","ko":"부채","vi":"Nợ","th":"หนี้","ms":"Hutang"}),
    ("fa_net_cash", "fa", {"en":"Net cash position","zh":"净现金头寸","zh-TW":"淨現金部位","ja":"ネットキャッシュ","ko":"순 현금 포지션","vi":"Vị thế tiền mặt ròng","th":"ฐานะเงินสดสุทธิ","ms":"Kedudukan tunai bersih"}),
    ("fa_balance_sheet", "fa", {"en":"Balance sheet","zh":"资产负债表","zh-TW":"資產負債表","ja":"バランスシート","ko":"대차대조표","vi":"Bảng cân đối","th":"งบดุล","ms":"Kunci kira-kira"}),
    ("fa_growth_cashflow", "fa", {"en":"Growth & Cash Flow","zh":"增长与现金流","zh-TW":"增長與現金流","ja":"成長とキャッシュフロー","ko":"성장 및 현금흐름","vi":"Tăng trưởng & Dòng tiền","th":"การเติบโตและกระแสเงินสด","ms":"Pertumbuhan & aliran tunai"}),
    ("fa_revenue_growth", "fa", {"en":"Revenue growth","zh":"收入增长","zh-TW":"收入增長","ja":"売上成長","ko":"매출 성장","vi":"Tăng trưởng doanh thu","th":"การเติบโตของรายได้","ms":"Pertumbuhan hasil"}),
    ("fa_earnings_growth", "fa", {"en":"Earnings growth","zh":"盈利增长","zh-TW":"盈利增長","ja":"利益成長","ko":"이익 성장","vi":"Tăng trưởng lợi nhuận","th":"การเติบโตของกำไร","ms":"Pertumbuhan pendapatan"}),
    ("fa_per_share", "fa", {"en":"per share","zh":"每股","zh-TW":"每股","ja":"1株あたり","ko":"주당","vi":"mỗi cổ phiếu","th":"ต่อหุ้น","ms":"setiap saham"}),
    ("fa_op_cf_margin", "fa", {"en":"op. CF margin","zh":"经营现金流利润率","zh-TW":"經營現金流利潤率","ja":"営業CF利益率","ko":"영업CF마진","vi":"Biên CF hoạt động","th":"อัตรากำไร CF จากการดำเนินงาน","ms":"Margin CF operasi"}),
    ("fa_free_cash_flow", "fa", {"en":"Free cash flow","zh":"自由现金流","zh-TW":"自由現金流","ja":"フリーキャッシュフロー","ko":"잉여현금흐름","vi":"Dòng tiền tự do","th":"กระแสเงินสดอิสระ","ms":"Aliran tunai bebas"}),
    ("fa_dividend", "fa", {"en":"Dividend","zh":"股息","zh-TW":"股息","ja":"配当","ko":"배당","vi":"Cổ tức","th":"เงินปันผล","ms":"Dividen"}),
    ("fa_payout_ratio", "fa", {"en":"Payout ratio","zh":"派息率","zh-TW":"派息率","ja":"配当性向","ko":"배당성향","vi":"Tỷ lệ chi trả","th":"อัตราการจ่ายเงินปันผล","ms":"Nisbah pembayaran"}),
    ("fa_high_volatility", "fa", {"en":"high volatility vs market","zh":"相对市场高波动","zh-TW":"相對市場高波動","ja":"市場比高ボラ","ko":"시장 대비 높은 변동성","vi":"biến động cao so với thị trường","th":"ความผันผวนสูงเมื่อเทียบกับตลาด","ms":"turun naik tinggi berbanding pasaran"}),
    ("fa_moderate_volatility", "fa", {"en":"moderately higher volatility","zh":"中等偏高波动","zh-TW":"中等偏高波動","ja":"やや高いボラ","ko":"약간 높은 변동성","vi":"biến động cao vừa phải","th":"ความผันผวนสูงปานกลาง","ms":"turun naik sederhana tinggi"}),
    ("fa_low_beta", "fa", {"en":"low-beta defensive","zh":"低贝塔防御型","zh-TW":"低貝塔防禦型","ja":"低ベータ・ディフェンシブ","ko":"저베타 방어적","vi":"phòng thủ beta thấp","th":"เบต้าต่ำเชิงรับ","ms":"beta rendah defensif"}),
    ("fa_market_volatility", "fa", {"en":"close to market volatility","zh":"接近市场波动","zh-TW":"接近市場波動","ja":"市場並みのボラ","ko":"시장 수준 변동성","vi":"gần với biến động thị trường","th":"ใกล้เคียงกับความผันผวนของตลาด","ms":"dekat turun naik pasaran"}),
    ("fa_next_earnings", "fa", {"en":"Next earnings date","zh":"下次财报日","zh-TW":"下次財報日","ja":"次回決算日","ko":"다음 실적 발표일","vi":"Ngày công bố kết quả tiếp theo","th":"วันประกาศผลประกอบการถัดไป","ms":"Tarikh pendapatan seterusnya"}),
    ("fa_macro_geo", "fa", {"en":"Macro & Geopolitical Environment","zh":"宏观与地缘政治环境","zh-TW":"宏觀與地緣政治環境","ja":"マクロ・地政学的環境","ko":"거시경제 및 지정학적 환경","vi":"Môi trường vĩ mô & Địa chính trị","th":"สภาพแวดล้อมมหภาคและภูมิรัฐศาสตร์","ms":"Persekitaran makro & geopolitik"}),
    ("fa_macro_score", "fa", {"en":"macro score","zh":"宏观评分","zh-TW":"宏觀評分","ja":"マクロスコア","ko":"매크로 점수","vi":"điểm vĩ mô","th":"คะแนนมหภาค","ms":"skor makro"}),
    ("fa_key_macro", "fa", {"en":"Key macro factors for this sector","zh":"该行业关键宏观因素","zh-TW":"該行業關鍵宏觀因素","ja":"このセクターの主要マクロ要因","ko":"이 섹터의 주요 매크로 요인","vi":"Yếu tố vĩ mô chính cho ngành này","th":"ปัจจัยมหภาคสำคัญสำหรับภาคนี้","ms":"Faktor makro utama untuk sektor ini"}),
    ("fa_geo_flags", "fa", {"en":"Geopolitical flags to monitor","zh":"需关注的地缘政治风险","zh-TW":"需關注的地緣政治風險","ja":"注視すべき地政学リスク","ko":"모니터링할 지정학적 리스크","vi":"Rủi ro địa chính trị cần theo dõi","th":"ธงภูมิรัฐศาสตร์ที่ต้องติดตาม","ms":"Bendera geopolitik untuk dipantau"}),
    ("fa_ai_disruption", "fa", {"en":"AI & tech disruption risk","zh":"AI与技术颠覆风险","zh-TW":"AI與技術顛覆風險","ja":"AI・テクノロジー破壊リスク","ko":"AI 및 기술 혁신 리스크","vi":"Rủi ro đột phá AI & công nghệ","th":"ความเสี่ยงจากการเปลี่ยนแปลงของ AI และเทคโนโลยี","ms":"Risiko gangguan AI & teknologi"}),
    ("fa_disruption_high", "fa", {"en":"sector faces material disruption from AI/automation","zh":"行业面临AI/自动化的重大颠覆","zh-TW":"行業面臨AI/自動化的重大顛覆","ja":"AI/自動化による重大な破壊リスク","ko":"AI/자동화로 인한 중대한 혼란 직면","vi":"ngành đối mặt với sự gián đoạn lớn từ AI","th":"ภาคเผชิญการเปลี่ยนแปลงครั้งใหญ่จาก AI","ms":"sektor menghadapi gangguan material daripada AI"}),
    ("fa_disruption_medium", "fa", {"en":"some disruption risk; companies adapting to AI are better positioned","zh":"存在一定颠覆风险；适应AI的公司处于更有利位置","zh-TW":"存在一定顛覆風險；適應AI的公司處於更有利位置","ja":"一定の破壊リスクあり；AI適応企業は優位","ko":"일부 혼란 리스크; AI 적응 기업이 유리","vi":"Một số rủi ro; công ty thích ứng AI có vị thế tốt hơn","th":"มีความเสี่ยงบ้าง; บริษัทที่ปรับตัวกับ AI มีตำแหน่งที่ดีกว่า","ms":"Risiko gangguan sederhana; syarikat yang menyesuaikan diri lebih baik"}),
    ("fa_disruption_low", "fa", {"en":"sector is relatively insulated from near-term AI disruption","zh":"行业相对不受近期AI颠覆影响","zh-TW":"行業相對不受近期AI顛覆影響","ja":"セクターは短期的なAI破壊から比較的隔離","ko":"섹터는 단기 AI 혼란으로부터 상대적으로 안전","vi":"Ngành tương đối không bị ảnh hưởng bởi AI ngắn hạn","th":"ภาคค่อนข้างได้รับการป้องกันจากการเปลี่ยนแปลง AI ในระยะสั้น","ms":"Sektor agak terlindung daripada gangguan AI jangka pendek"}),
    ("fa_analyst_sentiment", "fa", {"en":"Market & Analyst Sentiment","zh":"市场与分析师情绪","zh-TW":"市場與分析師情緒","ja":"市場＆アナリストセンチメント","ko":"시장 및 애널리스트 센티먼트","vi":"Tâm lý thị trường & Nhà phân tích","th":"ความเชื่อมั่นของตลาดและนักวิเคราะห์","ms":"Sentimen pasaran & penganalisis"}),
    ("fa_consensus", "fa", {"en":"Wall St. consensus","zh":"华尔街共识","zh-TW":"華爾街共識","ja":"ウォール街コンセンサス","ko":"월스트리트 컨센서스","vi":"Đồng thuận Wall St.","th":"ฉันทามติของ Wall St.","ms":"Konsensus Wall St."}),
    ("fa_price_target", "fa", {"en":"Price target","zh":"目标价","zh-TW":"目標價","ja":"目標株価","ko":"목표가","vi":"Giá mục tiêu","th":"เป้าหมายราคา","ms":"Sasaran harga"}),
    ("fa_implied_upside", "fa", {"en":"Implied upside","zh":"隐含上涨空间","zh-TW":"隱含上漲空間","ja":"推定上昇余地","ko":"예상 상승 여력","vi":"Tiềm năng tăng giá","th":"ส่วนต่างขาขึ้นที่คาดหวัง","ms":"Potensi kenaikan"}),
    ("fa_ai_summary", "fa", {"en":"AI Investment Summary","zh":"AI投资摘要","zh-TW":"AI投資摘要","ja":"AI投資サマリー","ko":"AI 투자 요약","vi":"Tóm tắt đầu tư AI","th":"สรุปการลงทุน AI","ms":"Ringkasan pelaburan AI"}),
    ("fa_why_buy", "fa", {"en":"Why BUY / What's working","zh":"为什么买入/优势","zh-TW":"為什麼買入/優勢","ja":"買いの理由/強み","ko":"매수 이유/강점","vi":"Lý do MUA / Điểm mạnh","th":"ทำไมต้องซื้อ / อะไรที่ดี","ms":"Mengapa BELI / Apa yang berkesan"}),
    ("fa_key_risks", "fa", {"en":"Key risks / What could go wrong","zh":"主要风险/潜在问题","zh-TW":"主要風險/潛在問題","ja":"主要リスク/懸念事項","ko":"주요 리스크/잠재적 문제","vi":"Rủi ro chính / Điều gì có thể sai","th":"ความเสี่ยงหลัก / อะไรอาจผิดพลาด","ms":"Risiko utama / Apa yang boleh salah"}),
    ("fa_data_source", "fa", {"en":"Fundamental data: yfinance + Gemini grounding","zh":"基本面数据：yfinance + Gemini实时","zh-TW":"基本面數據：yfinance + Gemini即時","ja":"ファンダメンタルデータ：yfinance + Gemini","ko":"펀더멘탈 데이터: yfinance + Gemini","vi":"Dữ liệu cơ bản: yfinance + Gemini","th":"ข้อมูลพื้นฐาน: yfinance + Gemini","ms":"Data asas: yfinance + Gemini"}),
    ("fa_computed", "fa", {"en":"Computed","zh":"计算于","zh-TW":"計算於","ja":"算出日","ko":"산출일","vi":"Tính toán ngày","th":"คำนวณเมื่อ","ms":"Dikira pada"}),
    ("fa_not_advice", "fa", {"en":"Not financial advice","zh":"非投资建议","zh-TW":"非投資建議","ja":"投資助言ではありません","ko":"투자 조언이 아닙니다","vi":"Không phải tư vấn tài chính","th":"ไม่ใช่คำแนะนำทางการเงิน","ms":"Bukan nasihat kewangan"}),
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
