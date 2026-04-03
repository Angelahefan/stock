#!/usr/bin/env python3
"""
Seed Hong Kong (HKEX) tickers into datapai.ticker_universe and stock_directory.

HKEX Main Board: ~2,500 listed companies. We seed the top ~500 most liquid
(Hang Seng Index + Hang Seng Composite + popular mid-caps).

Yahoo Finance format: 0700.HK (Tencent), 0005.HK (HSBC), 9988.HK (Alibaba)
Note: HK tickers are zero-padded to 4 digits in Yahoo Finance.

Usage:
    PGHOST=localhost PGUSER=postgres PGPASSWORD=postgres python3 seed_hkex_tickers.py
"""
import psycopg2
import psycopg2.extras
import os

# ── Hang Seng Index constituents (82) + Hang Seng Composite (500+) ──
# Top ~500 most liquid HKEX stocks by market cap
# Format: "TICKER:NAME" — ticker is the raw HK stock code (no padding)
HKEX_STOCKS = {
    # ── Hang Seng Index (HSI) Blue Chips ──
    "0001": "CK Hutchison",
    "0002": "CLP Holdings",
    "0003": "HK & China Gas",
    "0005": "HSBC Holdings",
    "0006": "Power Assets Holdings",
    "0011": "Hang Seng Bank",
    "0012": "Henderson Land",
    "0016": "Sun Hung Kai Properties",
    "0017": "New World Development",
    "0019": "Swire Pacific A",
    "0023": "Bank of East Asia",
    "0027": "Galaxy Entertainment",
    "0066": "MTR Corporation",
    "0101": "Hang Lung Properties",
    "0175": "Geely Automobile",
    "0241": "Alibaba Health",
    "0267": "CITIC",
    "0288": "WH Group",
    "0291": "China Resources Beer",
    "0316": "Orient Overseas",
    "0322": "Tingyi",
    "0386": "China Petroleum & Chemical (Sinopec)",
    "0388": "Hong Kong Exchanges & Clearing",
    "0669": "Techtronic Industries",
    "0688": "China Overseas Land",
    "0700": "Tencent Holdings",
    "0762": "China Unicom",
    "0823": "Link REIT",
    "0857": "PetroChina",
    "0868": "Xinyi Glass",
    "0881": "Zhongsheng Group",
    "0883": "CNOOC",
    "0939": "China Construction Bank",
    "0941": "China Mobile",
    "0960": "Longfor Group",
    "0968": "Xinyi Solar",
    "0981": "SMIC",
    "1038": "CK Infrastructure",
    "1044": "Hengan International",
    "1088": "China Shenhua Energy",
    "1093": "CSPC Pharmaceutical",
    "1109": "China Resources Land",
    "1113": "CK Asset Holdings",
    "1177": "Sino Biopharmaceutical",
    "1209": "China Resources Mixc",
    "1211": "BYD Company",
    "1299": "AIA Group",
    "1378": "China Hongqiao",
    "1398": "ICBC",
    "1810": "Xiaomi Corp",
    "1876": "Budweiser APAC",
    "1928": "Sands China",
    "1997": "Wharf REIC",
    "2007": "Country Garden",
    "2018": "AAC Technologies",
    "2020": "ANTA Sports",
    "2269": "WuXi Biologics",
    "2313": "Shenzhou International",
    "2318": "Ping An Insurance",
    "2319": "China Mengniu Dairy",
    "2331": "Li Ning",
    "2382": "Sunny Optical",
    "2388": "BOC Hong Kong",
    "2628": "China Life Insurance",
    "2688": "ENN Energy",
    "2899": "Zijin Mining",
    "3328": "Bank of Communications",
    "3690": "Meituan",
    "3968": "China Merchants Bank",
    "3988": "Bank of China",
    "6098": "Country Garden Services",
    "6862": "Haidilao",
    "9618": "JD.com",
    "9888": "Baidu",
    "9961": "Trip.com",
    "9988": "Alibaba Group",
    "9999": "NetEase",
    # ── Large Caps (HSC Large Cap Index) ──
    "0020": "SenseTime Group",
    "0034": "Kowloon Development",
    "0083": "Sino Land",
    "0135": "Kunlun Energy",
    "0144": "China Merchants Port",
    "0151": "Want Want China",
    "0168": "Tsingtao Brewery",
    "0169": "China Resources Power",
    "0178": "Sa Sa International",
    "0189": "Dongyue Group",
    "0220": "Uni-President China",
    "0268": "Kingdee International",
    "0270": "Guangdong Investment",
    "0285": "BYD Electronic",
    "0293": "Cathay Pacific",
    "0303": "VTech Holdings",
    "0330": "Esprit Holdings",
    "0347": "Angang Steel",
    "0358": "Jiangxi Copper",
    "0371": "Beijing Enterprises Water",
    "0384": "China Gas Holdings",
    "0390": "China Railway Group",
    "0392": "Beijing Enterprises",
    "0489": "Dongfeng Motor",
    "0522": "ASM Pacific Technology",
    "0551": "Yue Yuen Industrial",
    "0570": "China Traditional Chinese Medicine",
    "0576": "Zhejiang Expressway",
    "0586": "China Conch Venture",
    "0590": "Luk Fook Holdings",
    "0604": "Shenzhen Investment",
    "0656": "Fosun International",
    "0659": "NWS Holdings",
    "0667": "China East Education",
    "0683": "Kerry Properties",
    "0694": "Beijing Capital International Airport",
    "0696": "TravelSky Technology",
    "0728": "China Telecom",
    "0753": "Air China",
    "0763": "ZTE Corporation",
    "0772": "China Literature",
    "0780": "Tongcheng Travel",
    "0799": "IGG",
    "0813": "Shimao Group",
    "0836": "China Resources Power",
    "0853": "MicroPort Scientific",
    "0856": "VNET Group",
    "0867": "China Medical System",
    "0873": "World Chinese Media",
    "0880": "SJM Holdings",
    "0884": "CIFI Holdings",
    "0902": "Huaneng Power International",
    "0909": "Ming Yuan Cloud",
    "0914": "Anhui Conch Cement",
    "0916": "China Longyuan Power",
    "0921": "Hisense Home Appliances",
    "0966": "China Taiping Insurance",
    "0992": "Lenovo Group",
    "0998": "China CITIC Bank",
    "1024": "Kuaishou Technology",
    "1066": "Weigao Group",
    "1072": "Dongfang Electric",
    "1099": "Sinopharm Group",
    "1128": "Wynn Macau",
    "1171": "Yanzhou Coal Mining (Yankuang Energy)",
    "1176": "Zhuzhou CRRC Times Electric",
    "1193": "China Resources Gas",
    "1208": "MMG",
    "1268": "China Meidong Auto",
    "1288": "Agricultural Bank of China",
    "1313": "China Resources Cement",
    "1316": "NextEer International",
    "1336": "New China Life Insurance",
    "1339": "PICC Group",
    "1347": "Hua Hong Semiconductor",
    "1359": "China Cinda Asset Management",
    "1361": "361 Degrees",
    "1368": "Xtep International",
    "1382": "Pacific Textiles",
    "1385": "Shanghai Fosun Pharmaceutical",
    "1415": "Cowell e Holdings",
    "1416": "Bosideng International",
    "1448": "Fuyao Glass",
    "1458": "Zhou Hei Ya International",
    "1478": "Q Technology",
    "1508": "China Reinsurance",
    "1513": "Livzon Pharmaceutical",
    "1516": "Sunac China",
    "1528": "Maanshan Iron & Steel",
    "1530": "3SBio",
    "1548": "Genscript Biotech",
    "1579": "颐海国际 (Yihai International)",
    "1618": "Metallurgical Corporation of China",
    "1658": "Postal Savings Bank of China",
    "1666": "Tong Ren Tang Technologies",
    "1668": "China South Publishing & Media",
    "1680": "Macau Legend",
    "1686": "Sunevision Holdings",
    "1728": "Zhengzhou Yutong Bus",
    "1772": "GangFeng Lithium",
    "1776": "GF Securities",
    "1787": "Shandong Gold Mining",
    "1797": "China East Education",
    "1799": "Xinhua Education",
    "1801": "Innovent Biologics",
    "1811": "CGN Power",
    "1816": "CGN New Energy",
    "1818": "China Zhaoshang Zhengtong Auto Services",
    "1833": "Ping An Healthcare and Technology",
    "1839": "CIMC Vehicles",
    "1858": "Chunfeng Auto",
    "1868": "Nanyue Holdings",
    "1877": "Shanghai Junshi Biosciences",
    "1898": "China Coal Energy",
    "1919": "COSCO Shipping Holdings",
    "1929": "Chow Tai Fook Jewellery",
    "1951": "JinXin Fertility",
    "1958": "BAIC Motor",
    "1963": "Bank of Chongqing",
    "1972": "Swire Properties",
    "1999": "Man Wah Holdings",
    "2002": "Sunway Communication",
    "2013": "Weimob",
    "2015": "Li Auto",
    "2018": "AAC Technologies",
    "2038": "FIT Hon Teng",
    "2057": "ZTO Express",
    "2060": "AoXing Pharmaceutical",
    "2096": "Sinocare",
    "2098": "Zall Smart Commerce",
    "2128": "China Lesso Group",
    "2158": "Yidu Tech",
    "2196": "Fosun Tourism",
    "2202": "China Vanke",
    "2208": "Goldwind Science & Technology",
    "2238": "GAC Group",
    "2269": "WuXi Biologics",
    "2282": "MGM China",
    "2285": "Daqo New Energy",
    "2318": "Ping An Insurance",
    "2328": "PICC P&C",
    "2333": "Great Wall Motor",
    "2338": "Weichai Power",
    "2343": "Pacific Basin Shipping",
    "2345": "Shanghai Pharmaceuticals",
    "2357": "AviChina Industry & Technology",
    "2359": "WuXi AppTec",
    "2378": "Prudential plc",
    "2380": "China Power International",
    "2386": "Sinopec Engineering",
    "2399": "China Youzan",
    "2500": "Venus Medtech",
    "2518": "Autohome",
    "2600": "Chalco (Aluminum Corp of China)",
    "2601": "CPIC (China Pacific Insurance)",
    "2607": "Shanghai Pharmaceuticals",
    "2611": "Guotai Junan International",
    "2616": "Shandong Gold",
    "2618": "JD Logistics",
    "2628": "China Life Insurance",
    "2666": "Giant Biogene",
    "2669": "China Overseas Property",
    "2678": "Texhong Textile",
    "2689": "ND Paper",
    "2696": "Bilibili",
    "2768": "Jiayuan International",
    "2777": "Guangzhou R&F Properties",
    "2799": "China Huarong Asset Management",
    "2800": "Tracker Fund of Hong Kong",
    "2828": "Hang Seng China Enterprises ETF",
    "2883": "China Oilfield Services",
    "2899": "Zijin Mining",
    "2999": "FingerTango",
    "3301": "Ronshine China",
    "3311": "China State Construction International",
    "3320": "China Resources Pharmaceutical",
    "3323": "China National Building Material",
    "3331": "Vinda International",
    "3360": "Far East Horizon",
    "3368": "Parkson Retail",
    "3377": "Sino-Ocean Group",
    "3380": "Logan Group",
    "3383": "Agile Group",
    "3396": "Legend Holdings",
    "3606": "Fuyao Glass Industry Group",
    "3613": "Beijing Tong Ren Tang Chinese Medicine",
    "3618": "Chongqing Rural Commercial Bank",
    "3636": "China Resources Medical",
    "3668": "Yangtze Optical Fibre and Cable",
    "3669": "Yongda Auto",
    "3690": "Meituan",
    "3698": "Huishang Bank",
    "3738": "Haidilao International",
    "3759": "SinoHydro Equipment",
    "3800": "GCL Technology",
    "3808": "China Galaxy Securities",
    "3883": "China Aoyuan Group",
    "3888": "Kingsoft",
    "3899": "CIMC Enric",
    "3900": "Greentown China",
    "3908": "China International Capital Corp (CICC)",
    "3958": "Orient Securities",
    "3968": "China Merchants Bank",
    "3969": "China Yuchai International",
    "3983": "China BlueChemical",
    "3993": "China Molybdenum",
    "6030": "CITIC Securities",
    "6049": "Polaris Media",
    "6060": "ZhongAn Online P&C Insurance",
    "6066": "CSC Financial",
    "6078": "Hygeia Healthcare",
    "6098": "Country Garden Services",
    "6100": "Tongdao Liepin Group",
    "6110": "TopSports International",
    "6127": "Yeahka",
    "6160": "BeiGene",
    "6185": "CanSino Biologics",
    "6186": "China Feihe",
    "6196": "Bioceres Crop Solutions",
    "6618": "JD Health International",
    "6690": "Haier Smart Home",
    "6699": "Angelalign Technology",
    "6818": "China Everbright Bank",
    "6823": "HKT Trust and HKT Limited",
    "6826": "Shanghai Electric",
    "6837": "Haitong Securities",
    "6855": "Asia Cement (China)",
    "6862": "Haidilao International",
    "6865": "Flat Glass Group",
    "6869": "Yangtze Memory Technologies",
    "6881": "China Galaxy Securities",
    "6886": "HTSC (Huatai Securities)",
    "6969": "Smoore International",
    "6993": "Blue Moon Group",
    "7226": "Bank of Shanghai (via Stock Connect)",
    "8083": "China YuRun Food",
    "9626": "Bilibili (Class Z)",
    "9633": "Nongfu Spring",
    "9666": "Jinke Smart Services",
    "9668": "ZhenFund",
    "9698": "GreenTown Management",
    "9868": "XPeng",
    "9888": "Baidu",
    "9901": "NIO",
    "9911": "New Oriental Education",
    "9923": "Yeahka Ltd",
    "9926": "Akeso",
    "9961": "Trip.com Group",
    "9966": "Alphamab Oncology",
    "9969": "Pop Mart International",
    "9979": "GreenTech",
    "9987": "Yum China",
    "9988": "Alibaba Group",
    "9989": "Hutchmed (China)",
    "9990": "LinkDoc Technology",
    "9992": "Popsockets",
    "9995": "RemeGen",
    "9996": "Sato Group",
    "9997": "Kangji Medical",
    "9999": "NetEase",
}

# ── Featured HK blue chips (top 20 by market cap) ──
FEATURED_HK = [
    "9988",  # Alibaba
    "0700",  # Tencent
    "1299",  # AIA
    "0005",  # HSBC
    "0941",  # China Mobile
    "3690",  # Meituan
    "1211",  # BYD
    "1810",  # Xiaomi
    "0939",  # CCB
    "1398",  # ICBC
    "2318",  # Ping An
    "9618",  # JD.com
    "0388",  # HKEX
    "0883",  # CNOOC
    "1024",  # Kuaishou
    "9888",  # Baidu
    "0175",  # Geely
    "2020",  # ANTA Sports
    "9999",  # NetEase
    "0027",  # Galaxy Entertainment
]


def main():
    conn = psycopg2.connect(
        host=os.environ.get('PGHOST', 'localhost'),
        port=int(os.environ.get('PGPORT', '5432')),
        dbname=os.environ.get('PGDATABASE', 'postgres'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', 'postgres'),
    )

    tickers = list(HKEX_STOCKS.keys())
    print(f"HKEX stocks to seed: {len(tickers)}")

    with conn.cursor() as cur:
        # 1. Seed ticker_universe
        rows = [
            (code, 'HKEX', f'{code.lstrip("0") or "0"}.HK' if len(code) <= 4 else f'{code}.HK',
             HKEX_STOCKS[code], True, 'manual')
            for code in tickers
        ]
        # Yahoo Finance uses zero-padded 4-digit codes: 0700.HK, 0005.HK, 9988.HK
        # But for shorter codes, Yahoo strips leading zeros for some: 5.HK = HSBC
        # Safest: use the full 4-digit code with .HK
        rows = [
            (code, 'HKEX', f'{code}.HK', HKEX_STOCKS[code], True, 'manual')
            for code in tickers
        ]
        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.ticker_universe (ticker, exchange, yf_symbol, company_name, is_active, source)
            VALUES %s
            ON CONFLICT (ticker, exchange) DO UPDATE SET
                yf_symbol = EXCLUDED.yf_symbol,
                company_name = EXCLUDED.company_name,
                is_active = EXCLUDED.is_active,
                updated_at = NOW()
        """, rows, page_size=200)
        print(f"Seeded {len(rows)} tickers into ticker_universe")

        # 2. Seed stock_directory (English names — PK is symbol, exchange, lang)
        dir_rows = [(code, HKEX_STOCKS[code], 'HKEX', 'en') for code in tickers]
        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.stock_directory (symbol, name, exchange, lang)
            VALUES %s
            ON CONFLICT (symbol, exchange, lang) DO UPDATE SET
                name = EXCLUDED.name
        """, dir_rows, page_size=200)
        print(f"Seeded {len(dir_rows)} rows into stock_directory")

        # 3. Set featured stocks
        for i, code in enumerate(FEATURED_HK, 1):
            cur.execute(
                "UPDATE datapai.ticker_universe SET is_featured = TRUE, featured_order = %s "
                "WHERE ticker = %s AND exchange = 'HKEX'",
                (i, code),
            )
        print(f"Set {len(FEATURED_HK)} featured HK blue chips")

        conn.commit()
    conn.close()
    print("Done!")


if __name__ == '__main__':
    main()
