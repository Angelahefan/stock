#!/usr/bin/env python3
"""
Seed stock_directory with 8 language variants for all stocks.

Strategy:
1. Copy all existing 'en' rows to 7 other languages (proper nouns stay English)
2. Override the top 58 UNIVERSE_ALL stocks with curated CJK/vi translations
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

LANGS = ["zh", "zh-TW", "ja", "ko", "vi", "th", "ms"]

# ── Step 1: Bulk duplicate en → 7 other langs ────────────────────────────────
print("Step 1: Duplicating en rows to 7 other languages...")
with conn.cursor() as cur:
    for lang in LANGS:
        cur.execute("""
            INSERT INTO datapai.stock_directory (symbol, name, exchange, sector, lang)
            SELECT symbol, name, exchange, sector, %s
            FROM datapai.stock_directory
            WHERE lang = 'en'
            ON CONFLICT (symbol, exchange, lang) DO NOTHING
        """, (lang,))
        print(f"  {lang}: {cur.rowcount} rows inserted")
    conn.commit()

# ── Step 2: Curated translations for top stocks ──────────────────────────────
# Format: (symbol, exchange, {lang: name})
# fmt: off
CURATED = [
    # ── US Stocks (20) ──
    ("ACMR", "US", {"zh": "ACM研究", "zh-TW": "ACM研究", "ja": "ACMリサーチ", "ko": "ACM리서치", "vi": "ACM Research", "th": "ACM Research", "ms": "ACM Research"}),
    ("NVDA", "US", {"zh": "英伟达", "zh-TW": "輝達", "ja": "エヌビディア", "ko": "엔비디아", "vi": "Nvidia", "th": "Nvidia", "ms": "Nvidia"}),
    ("AAPL", "US", {"zh": "苹果公司", "zh-TW": "蘋果公司", "ja": "アップル", "ko": "애플", "vi": "Apple", "th": "แอปเปิล", "ms": "Apple"}),
    ("MSFT", "US", {"zh": "微软", "zh-TW": "微軟", "ja": "マイクロソフト", "ko": "마이크로소프트", "vi": "Microsoft", "th": "ไมโครซอฟท์", "ms": "Microsoft"}),
    ("GOOGL", "US", {"zh": "谷歌", "zh-TW": "谷歌", "ja": "グーグル (アルファベット)", "ko": "알파벳 (구글)", "vi": "Alphabet (Google)", "th": "อัลฟาเบท (กูเกิล)", "ms": "Alphabet (Google)"}),
    ("AMZN", "US", {"zh": "亚马逊", "zh-TW": "亞馬遜", "ja": "アマゾン", "ko": "아마존", "vi": "Amazon", "th": "อเมซอน", "ms": "Amazon"}),
    ("META", "US", {"zh": "Meta平台", "zh-TW": "Meta平台", "ja": "メタ・プラットフォームズ", "ko": "메타 플랫폼즈", "vi": "Meta Platforms", "th": "เมต้า แพลตฟอร์มส์", "ms": "Meta Platforms"}),
    ("TSLA", "US", {"zh": "特斯拉", "zh-TW": "特斯拉", "ja": "テスラ", "ko": "테슬라", "vi": "Tesla", "th": "เทสลา", "ms": "Tesla"}),
    ("AMD", "US", {"zh": "超威半导体", "zh-TW": "超微半導體", "ja": "AMD", "ko": "AMD", "vi": "AMD", "th": "AMD", "ms": "AMD"}),
    ("SMCI", "US", {"zh": "超微电脑", "zh-TW": "超微電腦", "ja": "スーパーマイクロ", "ko": "슈퍼마이크로", "vi": "Super Micro Computer", "th": "ซูเปอร์ไมโคร", "ms": "Super Micro Computer"}),
    ("INTC", "US", {"zh": "英特尔", "zh-TW": "英特爾", "ja": "インテル", "ko": "인텔", "vi": "Intel", "th": "อินเทล", "ms": "Intel"}),
    ("CRM", "US", {"zh": "赛富时", "zh-TW": "賽富時", "ja": "セールスフォース", "ko": "세일즈포스", "vi": "Salesforce", "th": "เซลส์ฟอร์ซ", "ms": "Salesforce"}),
    ("PLTR", "US", {"zh": "帕兰提尔", "zh-TW": "帕蘭提爾", "ja": "パランティア", "ko": "팔란티어", "vi": "Palantir", "th": "พาแลนเทียร์", "ms": "Palantir"}),
    ("SNOW", "US", {"zh": "雪花公司", "zh-TW": "雪花公司", "ja": "スノーフレーク", "ko": "스노우플레이크", "vi": "Snowflake", "th": "สโนว์เฟลก", "ms": "Snowflake"}),
    ("PRTS", "US", {"zh": "CarParts.com", "zh-TW": "CarParts.com", "ja": "CarParts.com", "ko": "CarParts.com", "vi": "CarParts.com", "th": "CarParts.com", "ms": "CarParts.com"}),
    ("ZS", "US", {"zh": "Zscaler网络安全", "zh-TW": "Zscaler網路安全", "ja": "Zスケーラー", "ko": "지스케일러", "vi": "Zscaler", "th": "Zscaler", "ms": "Zscaler"}),
    ("CRWD", "US", {"zh": "众击控股", "zh-TW": "眾擊控股", "ja": "クラウドストライク", "ko": "크라우드스트라이크", "vi": "CrowdStrike", "th": "คราวด์สไตรค์", "ms": "CrowdStrike"}),
    ("NET", "US", {"zh": "Cloudflare网络", "zh-TW": "Cloudflare網路", "ja": "クラウドフレア", "ko": "클라우드플레어", "vi": "Cloudflare", "th": "คลาวด์แฟลร์", "ms": "Cloudflare"}),
    ("DDOG", "US", {"zh": "Datadog监控", "zh-TW": "Datadog監控", "ja": "データドッグ", "ko": "데이터독", "vi": "Datadog", "th": "Datadog", "ms": "Datadog"}),
    ("PANW", "US", {"zh": "帕洛阿尔托网络", "zh-TW": "帕洛阿爾托網路", "ja": "パロアルトネットワークス", "ko": "팔로알토 네트웍스", "vi": "Palo Alto Networks", "th": "พาโล อัลโต เน็ตเวิร์กส์", "ms": "Palo Alto Networks"}),

    # ── ASX Stocks (18) ──
    ("BHP", "ASX", {"zh": "必和必拓集团", "zh-TW": "必和必拓集團", "ja": "BHPグループ", "ko": "BHP그룹", "vi": "Tập đoàn BHP", "th": "บีเอชพี กรุ๊ป", "ms": "Kumpulan BHP"}),
    ("CBA", "ASX", {"zh": "澳洲联邦银行", "zh-TW": "澳洲聯邦銀行", "ja": "コモンウェルス銀行", "ko": "커먼웰스은행", "vi": "Ngân hàng Commonwealth", "th": "ธนาคารคอมมอนเวลธ์", "ms": "Bank Komanwel"}),
    ("CSL", "ASX", {"zh": "CSL生物制药", "zh-TW": "CSL生物製藥", "ja": "CSLリミテッド", "ko": "CSL리미티드", "vi": "CSL Limited", "th": "CSL ลิมิเต็ด", "ms": "CSL Limited"}),
    ("NAB", "ASX", {"zh": "澳洲国民银行", "zh-TW": "澳洲國民銀行", "ja": "ナショナルオーストラリア銀行", "ko": "호주국민은행", "vi": "Ngân hàng Quốc gia Úc", "th": "ธนาคารแห่งชาติออสเตรเลีย", "ms": "Bank Negara Australia"}),
    ("ANZ", "ASX", {"zh": "澳新银行集团", "zh-TW": "澳新銀行集團", "ja": "ANZ銀行グループ", "ko": "ANZ은행그룹", "vi": "Tập đoàn Ngân hàng ANZ", "th": "กลุ่มธนาคาร ANZ", "ms": "Kumpulan Perbankan ANZ"}),
    ("WBC", "ASX", {"zh": "西太平洋银行", "zh-TW": "西太平洋銀行", "ja": "ウエストパック銀行", "ko": "웨스트팩은행", "vi": "Ngân hàng Westpac", "th": "ธนาคารเวสต์แพค", "ms": "Westpac Banking"}),
    ("WES", "ASX", {"zh": "韦斯农集团", "zh-TW": "韋斯農集團", "ja": "ウェスファーマーズ", "ko": "웨스파머스", "vi": "Wesfarmers", "th": "เวสฟาร์เมอร์ส", "ms": "Wesfarmers"}),
    ("MQG", "ASX", {"zh": "麦格理集团", "zh-TW": "麥格理集團", "ja": "マッコーリーグループ", "ko": "맥쿼리그룹", "vi": "Tập đoàn Macquarie", "th": "แมคควอรี กรุ๊ป", "ms": "Kumpulan Macquarie"}),
    ("TLS", "ASX", {"zh": "澳洲电信", "zh-TW": "澳洲電信", "ja": "テルストラ", "ko": "텔스트라", "vi": "Telstra", "th": "เทลสตรา", "ms": "Telstra"}),
    ("WOW", "ASX", {"zh": "沃尔沃斯集团", "zh-TW": "沃爾沃斯集團", "ja": "ウールワース・グループ", "ko": "울워스그룹", "vi": "Tập đoàn Woolworths", "th": "วูลเวิร์ธส กรุ๊ป", "ms": "Kumpulan Woolworths"}),
    ("RIO", "ASX", {"zh": "力拓集团", "zh-TW": "力拓集團", "ja": "リオ・ティント", "ko": "리오틴토", "vi": "Rio Tinto", "th": "ริโอ ทินโต", "ms": "Rio Tinto"}),
    ("FMG", "ASX", {"zh": "福蒂斯丘金属", "zh-TW": "福蒂斯丘金屬", "ja": "フォーテスキューメタルズ", "ko": "포테스큐메탈즈", "vi": "Fortescue Metals", "th": "ฟอร์เทสคิว เมทัลส์", "ms": "Fortescue Metals"}),
    ("TWE", "ASX", {"zh": "富邑葡萄酒", "zh-TW": "富邑葡萄酒", "ja": "トレジャリーワインエステーツ", "ko": "트레저리와인에스테이츠", "vi": "Treasury Wine Estates", "th": "เทรเชอรี ไวน์ เอสเทตส์", "ms": "Treasury Wine Estates"}),
    ("GMG", "ASX", {"zh": "嘉民集团", "zh-TW": "嘉民集團", "ja": "グッドマングループ", "ko": "굿맨그룹", "vi": "Tập đoàn Goodman", "th": "กูดแมน กรุ๊ป", "ms": "Kumpulan Goodman"}),
    ("STO", "ASX", {"zh": "桑托斯能源", "zh-TW": "桑托斯能源", "ja": "サントス", "ko": "산토스", "vi": "Santos", "th": "ซานโตส", "ms": "Santos"}),
    ("ORG", "ASX", {"zh": "澳源能源", "zh-TW": "澳源能源", "ja": "オリジンエナジー", "ko": "오리진에너지", "vi": "Origin Energy", "th": "ออริจิน เอเนอร์จี", "ms": "Origin Energy"}),
    ("WDS", "ASX", {"zh": "伍德赛德能源", "zh-TW": "伍德賽德能源", "ja": "ウッドサイドエナジー", "ko": "우드사이드에너지", "vi": "Woodside Energy", "th": "วูดไซด์ เอเนอร์จี", "ms": "Woodside Energy"}),
    ("QAN", "ASX", {"zh": "澳洲航空", "zh-TW": "澳洲航空", "ja": "カンタス航空", "ko": "콴타스항공", "vi": "Qantas Airways", "th": "สายการบินควอนตัส", "ms": "Qantas Airways"}),

    # ── VN Stocks (20 blue chips) ──
    ("VIC", "HOSE", {"zh": "Vingroup集团", "zh-TW": "Vingroup集團", "ja": "ビングループ", "ko": "빈그룹", "vi": "Tập đoàn Vingroup", "th": "วินกรุ๊ป", "ms": "Kumpulan Vingroup"}),
    ("VCB", "HOSE", {"zh": "越南外贸银行", "zh-TW": "越南外貿銀行", "ja": "ベトコムバンク", "ko": "비엣콤뱅크", "vi": "Ngân hàng TMCP Ngoại thương Việt Nam", "th": "เวียดคอมแบงก์", "ms": "Vietcombank"}),
    ("VHM", "HOSE", {"zh": "Vinhomes地产", "zh-TW": "Vinhomes地產", "ja": "ビンホームズ", "ko": "빈홈즈", "vi": "CTCP Vinhomes", "th": "วินโฮมส์", "ms": "Vinhomes"}),
    ("VNM", "HOSE", {"zh": "越南乳业", "zh-TW": "越南乳業", "ja": "ビナミルク", "ko": "비나밀크", "vi": "CTCP Sữa Việt Nam (Vinamilk)", "th": "วินามิลค์", "ms": "Vinamilk"}),
    ("HPG", "HOSE", {"zh": "和发集团", "zh-TW": "和發集團", "ja": "ホアファットグループ", "ko": "호아팟그룹", "vi": "CTCP Tập đoàn Hòa Phát", "th": "ฮัวฟัต กรุ๊ป", "ms": "Kumpulan Hoa Phat"}),
    ("FPT", "HOSE", {"zh": "FPT信息技术", "zh-TW": "FPT資訊科技", "ja": "FPTコーポレーション", "ko": "FPT코퍼레이션", "vi": "CTCP FPT", "th": "เอฟพีที คอร์ปอเรชั่น", "ms": "FPT Corporation"}),
    ("MWG", "HOSE", {"zh": "移动世界集团", "zh-TW": "移動世界集團", "ja": "モバイルワールドグループ", "ko": "모바일월드그룹", "vi": "CTCP Đầu tư Thế giới Di động", "th": "โมบาย เวิลด์ กรุ๊ป", "ms": "Mobile World Group"}),
    ("MSN", "HOSE", {"zh": "马山集团", "zh-TW": "馬山集團", "ja": "マサングループ", "ko": "마산그룹", "vi": "CTCP Tập đoàn Masan", "th": "มาซาน กรุ๊ป", "ms": "Kumpulan Masan"}),
    ("TCB", "HOSE", {"zh": "越南科技商业银行", "zh-TW": "越南科技商業銀行", "ja": "テクコムバンク", "ko": "테크콤뱅크", "vi": "Ngân hàng TMCP Kỹ thương Việt Nam", "th": "เทคคอมแบงก์", "ms": "Techcombank"}),
    ("MBB", "HOSE", {"zh": "越南军队银行", "zh-TW": "越南軍隊銀行", "ja": "MBバンク", "ko": "MB뱅크", "vi": "Ngân hàng TMCP Quân đội", "th": "เอ็มบี แบงก์", "ms": "MB Bank"}),
    ("ACB", "HOSE", {"zh": "亚洲商业银行", "zh-TW": "亞洲商業銀行", "ja": "アジア商業銀行", "ko": "아시아상업은행", "vi": "Ngân hàng TMCP Á Châu", "th": "ธนาคารพาณิชย์เอเชีย", "ms": "Asia Commercial Bank"}),
    ("STB", "HOSE", {"zh": "西贡商业银行", "zh-TW": "西貢商業銀行", "ja": "サコムバンク", "ko": "사콤뱅크", "vi": "Ngân hàng TMCP Sài Gòn Thương Tín", "th": "ซาคอมแบงก์", "ms": "Sacombank"}),
    ("SSI", "HOSE", {"zh": "SSI证券", "zh-TW": "SSI證券", "ja": "SSI証券", "ko": "SSI증권", "vi": "CTCP Chứng khoán SSI", "th": "SSI ซิเคียวริตี้ส์", "ms": "SSI Securities"}),
    ("VPB", "HOSE", {"zh": "越南繁荣银行", "zh-TW": "越南繁榮銀行", "ja": "VPバンク", "ko": "VP뱅크", "vi": "Ngân hàng TMCP Việt Nam Thịnh Vượng", "th": "วีพี แบงก์", "ms": "VP Bank"}),
    ("GAS", "HOSE", {"zh": "越南石油天然气", "zh-TW": "越南石油天然氣", "ja": "ペトロベトナムガス", "ko": "페트로베트남가스", "vi": "Tổng Công ty Khí Việt Nam", "th": "ปิโตรเวียดนาม แก๊ส", "ms": "PetroVietnam Gas"}),
    ("PLX", "HOSE", {"zh": "越南石油总公司", "zh-TW": "越南石油總公司", "ja": "ペトロリメックス", "ko": "페트롤리멕스", "vi": "Tập đoàn Xăng dầu Việt Nam", "th": "ปิโตรลิเม็กซ์", "ms": "Petrolimex"}),
    ("SAB", "HOSE", {"zh": "西贡啤酒", "zh-TW": "西貢啤酒", "ja": "サベコ", "ko": "사베코", "vi": "Tổng CTCP Bia - Rượu - NGK Sài Gòn", "th": "ซาเบโก", "ms": "Sabeco"}),
    ("BVH", "HOSE", {"zh": "宝越控股", "zh-TW": "寶越控股", "ja": "バオベトホールディングス", "ko": "바오비엣홀딩스", "vi": "Tập đoàn Bảo Việt", "th": "เบาเวียด โฮลดิ้งส์", "ms": "Bao Viet Holdings"}),
    ("REE", "HOSE", {"zh": "REE机电集团", "zh-TW": "REE機電集團", "ja": "REEコーポレーション", "ko": "REE코퍼레이션", "vi": "CTCP Cơ Điện Lạnh", "th": "อาร์อีอี คอร์ปอเรชั่น", "ms": "REE Corporation"}),
    ("PNJ", "HOSE", {"zh": "富润珠宝", "zh-TW": "富潤珠寶", "ja": "フーニュアンジュエリー", "ko": "푸뉴안주얼리", "vi": "CTCP Vàng bạc Đá quý Phú Nhuận", "th": "ฟู เญือน จิวเวลรี่", "ms": "Phu Nhuan Jewelry"}),
]
# fmt: on

print(f"\nStep 2: Updating {len(CURATED)} curated stock names (7 langs each)...")
rows = []
for symbol, exchange, translations in CURATED:
    for lang, name in translations.items():
        rows.append((symbol, name, exchange, lang))

with conn.cursor() as cur:
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO datapai.stock_directory (symbol, name, exchange, lang)
        VALUES %s
        ON CONFLICT (symbol, exchange, lang)
        DO UPDATE SET name = EXCLUDED.name
        """,
        rows,
        template="(%s, %s, %s, %s)",
    )
    conn.commit()
    print(f"  Upserted {cur.rowcount} curated rows.")

# ── Summary ──
with conn.cursor() as cur:
    cur.execute("SELECT lang, COUNT(*) FROM datapai.stock_directory GROUP BY lang ORDER BY lang")
    print("\nFinal stock_directory counts by lang:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")
    cur.execute("SELECT COUNT(*) FROM datapai.stock_directory")
    print(f"\nTotal rows: {cur.fetchone()[0]}")

conn.close()
print("Done.")
