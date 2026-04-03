#!/usr/bin/env python3
"""
Seed Thailand (SET) tickers into datapai.ticker_universe and stock_directory.

SET has ~800 listed companies. We seed SET50 + SET100 + popular mid-caps (~200 total).
Yahoo Finance suffix: .BK (e.g., PTT.BK, AOT.BK)

Usage:
    PGHOST=localhost PGUSER=postgres PGPASSWORD=postgres python3 seed_set_tickers.py
"""
import psycopg2
import psycopg2.extras
import os

# SET50 blue chips + SET100 + popular mid-caps
# Source: SET website, Wikipedia SET50/SET100 constituents, Yahoo Finance
SET_STOCKS = {
    # ── SET50 Index (top 50 by market cap + liquidity) ──
    "ADVANC": "Advanced Info Service",
    "AOT": "Airports of Thailand",
    "AWC": "Asset World Corp",
    "BBL": "Bangkok Bank",
    "BDMS": "Bangkok Dusit Medical Services",
    "BEM": "Bangkok Expressway and Metro",
    "BGRIM": "B.Grimm Power",
    "BH": "Bumrungrad Hospital",
    "BTS": "BTS Group Holdings",
    "CBG": "Carabao Group",
    "CENTEL": "Central Plaza Hotel",
    "COM7": "Com7",
    "CPALL": "CP ALL",
    "CPAXT": "CP Axtra",
    "CPF": "Charoen Pokphand Foods",
    "CPN": "Central Pattana",
    "CRC": "Central Retail Corporation",
    "DELTA": "Delta Electronics Thailand",
    "EA": "Energy Absolute",
    "EGCO": "Electricity Generating",
    "GLOBAL": "Siam Global House",
    "GPSC": "Global Power Synergy",
    "GULF": "Gulf Energy Development",
    "HMPRO": "Home Product Center",
    "INTUCH": "Intouch Holdings",
    "IVL": "Indorama Ventures",
    "KBANK": "Kasikornbank",
    "KTB": "Krung Thai Bank",
    "KTC": "Krungthai Card",
    "LH": "Land and Houses",
    "MINT": "Minor International",
    "MTC": "Muangthai Capital",
    "OR": "PTT Oil and Retail Business",
    "OSP": "Osotspa",
    "PTT": "PTT Public Company",
    "PTTEP": "PTT Exploration and Production",
    "PTTGC": "PTT Global Chemical",
    "RATCH": "Ratchaburi Electricity Generating",
    "SAWAD": "Srisawad Corporation",
    "SCB": "SCB X (Siam Commercial Bank)",
    "SCC": "Siam Cement Group",
    "SCGP": "SCG Packaging",
    "TIDLOR": "Ngern Tid Lor",
    "TISCO": "TISCO Financial Group",
    "TOP": "Thai Oil",
    "TRUE": "True Corporation",
    "TTB": "TMBThanachart Bank",
    "TU": "Thai Union Group",
    "WHA": "WHA Corporation",
    "MAKRO": "Siam Makro",

    # ── SET100 additions (next 50 by market cap) ──
    "AEONTS": "AEON Thana Sinsap Thailand",
    "AMATA": "Amata Corporation",
    "AP": "AP Thailand",
    "BANPU": "Banpu Public Company",
    "BAM": "Bangkok Commercial Asset Management",
    "BCH": "Bangkok Chain Hospital",
    "BCP": "Bangchak Corporation",
    "BPP": "Banpu Power",
    "BTSGIF": "BTS Rail Mass Transit Growth Infrastructure Fund",
    "CHG": "Chularat Hospital",
    "CK": "CH Karnchang",
    "CKP": "CK Power",
    "COTTO": "SCG Ceramics",
    "DOHOME": "DoHome",
    "DTAC": "dtac (now merged with True)",
    "ERW": "Erawan Group",
    "GFPT": "GFPT Public Company",
    "GGC": "GGC (Global Green Chemicals)",
    "GUNKUL": "Gunkul Engineering",
    "IRPC": "IRPC Public Company",
    "JAS": "Jasmine International",
    "JASIF": "Jasmine Broadband Internet Infrastructure Fund",
    "JMART": "Jay Mart Group Holdings",
    "JMT": "JMT Network Services",
    "KLINIQ": "Kliniq Skincare",
    "KKP": "Kiatnakin Phatra Bank",
    "KSL": "Khon Kaen Sugar Industry",
    "MC": "MC Group",
    "MEGA": "Mega Lifesciences",
    "MONO": "Mono Group",
    "NER": "Northeast Rubber",
    "ORI": "Origin Property",
    "PLANB": "Plan B Media",
    "PRM": "Prima Marine",
    "PSH": "Pruksa Holding",
    "PSL": "Precious Shipping",
    "PTG": "PTG Energy",
    "QH": "Quality Houses",
    "RBF": "R&B Food Supply",
    "RS": "RS Group",
    "SABINA": "Sabina",
    "SAPPE": "Sappe Public Company",
    "SC": "SC Asset Corporation",
    "SINGER": "Singer Thailand",
    "SPALI": "Supalai",
    "SPRC": "Star Petroleum Refining",
    "STA": "Sri Trang Agro-Industry",
    "STGT": "Sri Trang Gloves Thailand",
    "SUPER": "Super Energy Corporation",
    "SYNEX": "Synnex Thailand",
    "TCAP": "Thanachart Capital",
    "THANI": "Ratchathani Leasing",
    "TPIPP": "TPI Polene Power",
    "VGI": "VGI Group",
    "WHAUP": "WHAUP Utilities and Power",

    # ── Popular mid-caps ──
    "AAV": "AirAsia Group (Thailand)",
    "ACC": "Asia Capital Group",
    "AGE": "Asia Green Energy",
    "AH": "Aapico Hitech",
    "AIMCG": "AIM Commercial Growth REIT",
    "ALLA": "Alla Public Company",
    "ANAN": "Ananda Development",
    "ASW": "Asia Wealth Securities",
    "AU": "AF-Au Group",
    "BA": "Bangkok Airways",
    "BAFS": "Bangkok Aviation Fuel Services",
    "BAY": "Bank of Ayudhya (Krungsri)",
    "BC": "Buriram Sugar",
    "BCT": "Bangkok Cold Storage",
    "BEAUTY": "Beauty Community",
    "BIG": "Big Camera Corporation",
    "BJC": "Berli Jucker",
    "BOL": "Business Online",
    "BRR": "Bangkok Ranch",
    "CFRESH": "Seafresh Industry",
    "CHO": "Cho Thavee",
    "CI": "Charn Issara Development",
    "CNT": "Christiani & Nielsen Thai",
    "COLOR": "Colorpack",
    "CSS": "CSS Group",
    "DDD": "Do Day Dream",
    "DEMCO": "DEMCO",
    "DIF": "Digital Telecommunications Infrastructure Fund",
    "DRT": "Diamond Roofing Tiles",
    "ECF": "East Coast Furnitech",
    "EE": "Eastern Energy & Economy",
    "EP": "Eastern Printing",
    "EPG": "Eastern Polymer Group",
    "FE": "Far East DDB",
    "FN": "FN Factory Outlet",
    "FORTH": "Forth Corporation",
    "FPT": "Frasers Property Thailand",
    "GBX": "Globlex Holdings",
    "GEL": "General Engineering",
    "GLAND": "Grand Land and Property",
    "GOLD": "Golden Land Property",
    "GRAMMY": "GMM Grammy",
    "GREEN": "Green Resources",
    "GYT": "Goodyear Thailand",
    "HANA": "Hana Microelectronics",
    "ICC": "ICC International",
    "III": "Triple I Logistics",
    "ILINK": "Interlink Communication",
    "JCK": "JCK International",
    "JCKH": "JCK Hospitality",
    "JWD": "JWD InfoLogistics",
    "K": "K Line Shipping",
    "KAMART": "Kamart Group Holdings",
    "KCE": "KCE Electronics",
    "KGI": "KGI Securities Thailand",
    "KIAT": "Kiatnakin Securities",
    "KWC": "K.W.C. Holdings",
    "LANNA": "Lanna Resources",
    "LEO": "Leone Litho",
    "LIT": "Lighting & Equipment",
    "LPN": "LPN Development",
    "LST": "L.S. Industry",
    "MAJOR": "Major Cineplex Group",
    "MALEE": "Malee Group",
    "MFEC": "MFEC (Mission For Everyone Computer)",
    "MILL": "Millennium Group",
    "MOSHI": "Moshi Moshi Retail",
    "MPG": "MPG Corporation",
    "M-CHAI": "Mahachai Hospital",
    "NRF": "NR Instant Produce",
    "NSI": "Nam Seng Insurance",
    "NVD": "Navanakorn",
    "OCC": "O.C.C. Public Company",
    "PAP": "Pacific Pipe",
    "PE": "Premier Enterprise",
    "PG": "Phatra Insurance",
    "PRANDA": "Pranda Jewelry",
    "PRIME": "Prime Road Power",
    "PRINC": "Principal Capital",
    "PR9": "PR9 Corporation",
    "QLT": "Quality Construction Products",
    "RAM": "Ramkhamhaeng Hospital",
    "RCL": "Regional Container Lines",
    "ROBINS": "Robinson Department Store",
    "SABUY": "Sabuy Technology",
    "SAK": "Sakthi Sugars",
    "SAMART": "Samart Corporation",
    "SAMTEL": "Samart Telcoms",
    "SAT": "Somboon Advance Technology",
    "SE-ED": "SE-Education",
    "SF": "SF Corporation",
    "SIAM": "Siam Steel International",
    "SKR": "Sikarin Hospital",
    "SNC": "SNC Former",
    "SNP": "S & P Syndicate",
    "SPCG": "SPCG Public Company",
    "SSP": "SSP Group (Thailand)",
    "STEC": "Sino-Thai Engineering & Construction",
    "SUC": "Surapon Foods",
    "SUSCO": "Susco Public Company",
    "SYNTEC": "Syntec Construction",
    "TACC": "Thai Agri Foods",
    "TAE": "Thai Agro Energy",
    "TAKUNI": "Takuni Group",
    "TASCO": "Tipco Asphalt",
    "TFG": "Thai Film Industries",
    "THAI": "Thai Airways International",
    "THCOM": "Thaicom",
    "TMILL": "T.M.I. Machinery",
    "TMT": "Thai Metal Trade",
    "TNR": "Tongkah Harbour",
    "TOA": "TOA Paint Thailand",
    "TQM": "TQM Corporation",
    "TRC": "TRC Construction",
    "TRU": "Thai Rung Union Car",
    "TSC": "Thai Steel Cable",
    "TSE": "Thai Solar Energy",
    "TTA": "Thoresen Thai Agencies",
    "TTCL": "TTCL",
    "TVO": "Thai Vegetable Oil",
    "TWZ": "TWZ Corporation",
    "UAC": "UAC Global",
    "UOBKH": "UOB Kay Hian Securities Thailand",
    "VIBHA": "Vibhavadi Medical Center",
    "VIH": "Vinythai Holdings",
    "WAVE": "Wave Entertainment",
    "WICE": "WICE Logistics",
    "WORK": "Workpoint Entertainment",
    "WP": "WP Energy",
}

# ── Featured SET50 blue chips (top 20 by weight/market cap) ──
FEATURED_SET = [
    "DELTA",   # Delta Electronics — largest by weight (~15%)
    "PTT",     # PTT
    "ADVANC",  # AIS
    "AOT",     # Airports of Thailand
    "GULF",    # Gulf Energy
    "CPALL",   # CP ALL
    "PTTEP",   # PTT E&P
    "SCB",     # SCB X
    "BDMS",    # Bangkok Dusit Medical
    "TRUE",    # True Corp
    "KBANK",   # Kasikornbank
    "SCC",     # Siam Cement
    "BBL",     # Bangkok Bank
    "CPN",     # Central Pattana
    "MINT",    # Minor International
    "OR",      # PTT Oil & Retail
    "KTB",     # Krung Thai Bank
    "IVL",     # Indorama Ventures
    "BH",      # Bumrungrad Hospital
    "HMPRO",   # Home Product Center
]


def main():
    conn = psycopg2.connect(
        host=os.environ.get('PGHOST', 'localhost'),
        port=int(os.environ.get('PGPORT', '5432')),
        dbname=os.environ.get('PGDATABASE', 'postgres'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', 'postgres'),
    )

    tickers = list(SET_STOCKS.keys())
    print(f"SET stocks to seed: {len(tickers)}")

    with conn.cursor() as cur:
        # 1. Seed ticker_universe
        rows = [
            (code, 'SET', f'{code}.BK', SET_STOCKS[code], True, 'manual')
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
        dir_rows = [(code, SET_STOCKS[code], 'SET', 'en') for code in tickers]
        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.stock_directory (symbol, name, exchange, lang)
            VALUES %s
            ON CONFLICT (symbol, exchange, lang) DO UPDATE SET name = EXCLUDED.name
        """, dir_rows, page_size=200)
        print(f"Seeded {len(dir_rows)} rows into stock_directory")

        # 3. Set featured stocks
        for i, code in enumerate(FEATURED_SET, 1):
            cur.execute(
                "UPDATE datapai.ticker_universe SET is_featured = TRUE, featured_order = %s "
                "WHERE ticker = %s AND exchange = 'SET'",
                (i, code),
            )
        print(f"Set {len(FEATURED_SET)} featured SET blue chips")

        conn.commit()
    conn.close()
    print("Done!")


if __name__ == '__main__':
    main()
