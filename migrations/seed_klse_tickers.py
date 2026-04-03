#!/usr/bin/env python3
"""
Seed Malaysia (KLSE / Bursa Malaysia) tickers into datapai.ticker_universe and stock_directory.

Bursa Malaysia has ~900 listed companies. We seed FBMKLCI30 + FBM100 + popular mid-caps (~200 total).
Yahoo Finance suffix: .KL (e.g., 1155.KL = Maybank, 1295.KL = Public Bank)

Note: Malaysian stocks use numeric codes on Yahoo Finance (e.g., 1155.KL),
but are commonly known by short names (MAYBANK, PBBANK, TENAGA).

Usage:
    PGHOST=localhost PGUSER=postgres PGPASSWORD=postgres python3 seed_klse_tickers.py
"""
import psycopg2
import psycopg2.extras
import os

# FBMKLCI 30 + FBM100 + popular mid-caps
# Format: "TICKER": "Company Name" — ticker is the Yahoo symbol code (without .KL)
KLSE_STOCKS = {
    # ── FBMKLCI 30 (top 30 blue chips) ──
    "1155": "Malayan Banking (Maybank)",
    "1295": "Public Bank",
    "5347": "Tenaga Nasional",
    "6888": "Axiata Group",
    "1015": "AMMB Holdings",
    "1023": "CIMB Group Holdings",
    "3182": "Genting",
    "4715": "Genting Malaysia",
    "5183": "Petronas Chemicals Group",
    "5225": "IHH Healthcare",
    "5681": "Petronas Dagangan",
    "4863": "Telekom Malaysia",
    "6012": "Maxis",
    "4197": "Sime Darby",
    "4677": "YTL Corporation",
    "5168": "Hartalega Holdings",
    "7277": "Dialog Group",
    "5285": "SD Guthrie (Sime Darby Plantation)",
    "2445": "Kuala Lumpur Kepong",
    "1082": "Hong Leong Financial Group",
    "1066": "RHB Bank",
    "5819": "Hong Leong Bank",
    "4065": "PPB Group",
    "3816": "MISC",
    "6947": "Digi.Com (now CelcomDigi)",
    "4588": "UMW Holdings",
    "5296": "QL Resources",
    "6033": "Petronas Gas",
    "1961": "IOI Corporation",
    "5235": "KLCCP Stapled Group",

    # ── FBM100 additions (next 70) ──
    "2488": "Gamuda",
    "1562": "Berjaya Corporation",
    "3034": "Hap Seng Consolidated",
    "5014": "Malaysia Airports Holdings",
    "6888": "Axiata Group",
    "4707": "Nestlé Malaysia",
    "3026": "Dutch Lady Milk Industries",
    "4065": "PPB Group",
    "7113": "Top Glove Corporation",
    "7153": "Kossan Rubber Industries",
    "5878": "Supermax Corporation",
    "7084": "TA Enterprise",
    "3336": "Sunway",
    "5053": "OSK Holdings",
    "6432": "Eco World Development",
    "8583": "Eco World International",
    "5020": "UEM Sunrise",
    "5148": "SP Setia",
    "4898": "Sapura Energy",
    "5246": "Westports Holdings",
    "5239": "AEON Credit Service",
    "5099": "AirAsia Group (Capital A)",
    "6742": "YTL Power International",
    "6645": "Sunway REIT",
    "5186": "Inari Amertron",
    "0023": "LBS Bina Group",
    "6009": "DRB-HICOM",
    "5279": "Serba Dinamik",
    "7106": "Scientex",
    "7668": "Carlsberg Brewery Malaysia",
    "3255": "Heineken Malaysia",
    "4162": "British American Tobacco (M)",
    "5200": "UMS Holdings",
    "5024": "Malaysian Resources Corporation (MRCB)",
    "5185": "SCGM",
    "5095": "Sime Darby Property",
    "4731": "Press Metal Aluminium Holdings",
    "6963": "Sunway Construction Group",
    "4863": "Telekom Malaysia",
    "2267": "IOI Properties Group",
    "7164": "Vitrox Corporation",
    "0166": "Padini Holdings",
    "5398": "Mah Sing Group",
    "1724": "Parkson Holdings",
    "4324": "Duopharma Biotech",
    "5218": "Sapura Industrial",
    "8869": "Velesto Energy",
    "5235": "KLCCP Stapled Group",
    "3336": "Sunway",
    "1171": "Bursa Malaysia",
    "5202": "MSM Malaysia Holdings",

    # ── Popular mid-caps ──
    "2828": "Southern Acids (M)",
    "3867": "Dayang Enterprise Holdings",
    "5071": "Rubberex Corporation",
    "5075": "Cahya Mata Sarawak",
    "5141": "Matrix Concepts Holdings",
    "5162": "Revenue Group",
    "5175": "UWC",
    "5196": "JHM Consolidation",
    "5205": "Malaysia Steel Works",
    "5211": "Sunway Berhad",
    "5218": "Hong Seng Consolidated",
    "5220": "SLP Resources",
    "5243": "PMB Technology",
    "5258": "SKP Resources",
    "5264": "Cape EMS",
    "5305": "Frontken Corporation",
    "5318": "Mi Technovation",
    "6556": "ATA IMS",
    "6888": "Axiata Group",
    "7033": "CTOS Digital",
    "7052": "Poh Kong Holdings",
    "7064": "Aeon Co (M)",
    "7090": "Datasonic Group",
    "7100": "Oldtown White Coffee",
    "7113": "Top Glove Corporation",
    "7129": "Greatech Technology",
    "7148": "Pentamaster Corporation",
    "7153": "Kossan Rubber Industries",
    "7155": "Aurelius Technologies",
    "7161": "MPI (Malaysian Pacific Industries)",
    "7164": "Vitrox Corporation",
    "7168": "Globetronics Technology",
    "7172": "D&O Green Technologies",
    "7191": "Unisem (M)",
    "7204": "KESM Industries",
    "7216": "Kelington Group",
    "7229": "Elsoft Research",
    "7237": "Power Root",
    "7293": "Farm Fresh",
    "7668": "Carlsberg Brewery Malaysia",
    "8524": "Taliworks Corporation",
    "8575": "YFG",
    "8664": "SP Setia",
    "0078": "Fraser & Neave Holdings",
    "0138": "MyEG Services",
    "0145": "Leong Hup International",
    "0158": "Muda Holdings",
    "0166": "Padini Holdings",
    "0176": "Chin Hin Group",
    "0223": "Icon Offshore",
    "0247": "Bermaz Auto",
    "2445": "Kuala Lumpur Kepong",
    "2828": "Southern Acids",
    "3034": "Hap Seng Consolidated",
    "3182": "Genting",
    "3336": "Sunway",
    "3476": "QES Group",
    "3867": "Dayang Enterprise",
    "4065": "PPB Group",
    "4162": "BAT Malaysia",
    "4197": "Sime Darby",
    "4324": "Duopharma Biotech",
    "4588": "UMW Holdings",
    "4677": "YTL Corporation",
    "4707": "Nestlé Malaysia",
    "4715": "Genting Malaysia",
    "4731": "Press Metal Aluminium",
    "4863": "Telekom Malaysia",
    "4898": "Sapura Energy",
    "5014": "MAHB (Malaysia Airports)",
    "5020": "UEM Sunrise",
    "5024": "MRCB",
    "5053": "OSK Holdings",
    "5075": "Cahya Mata Sarawak",
    "5095": "Sime Darby Property",
    "5099": "Capital A (AirAsia)",
    "5141": "Matrix Concepts",
    "5148": "SP Setia",
    "5168": "Hartalega Holdings",
    "5183": "Petronas Chemicals",
    "5186": "Inari Amertron",
    "5225": "IHH Healthcare",
    "5239": "AEON Credit",
    "5246": "Westports Holdings",
    "5285": "SD Guthrie",
    "5296": "QL Resources",
    "5347": "Tenaga Nasional",
    "5398": "Mah Sing Group",
    "5681": "Petronas Dagangan",
    "5819": "Hong Leong Bank",
    "5878": "Supermax Corporation",
    "6009": "DRB-HICOM",
    "6012": "Maxis",
    "6033": "Petronas Gas",
    "6432": "Eco World Development",
    "6556": "ATA IMS",
    "6645": "Sunway REIT",
    "6742": "YTL Power",
    "6947": "CelcomDigi",
    "6963": "Sunway Construction",
    "7106": "Scientex",
    "7277": "Dialog Group",
}

# ── Featured FBMKLCI blue chips (top 20 by market cap) ──
FEATURED_KLSE = [
    "1155",  # Maybank
    "1295",  # Public Bank
    "1023",  # CIMB
    "5347",  # Tenaga Nasional
    "5225",  # IHH Healthcare
    "5183",  # Petronas Chemicals
    "6033",  # Petronas Gas
    "5681",  # Petronas Dagangan
    "4731",  # Press Metal
    "5285",  # SD Guthrie
    "5819",  # Hong Leong Bank
    "3816",  # MISC
    "6012",  # Maxis
    "6947",  # CelcomDigi
    "2488",  # Gamuda
    "4707",  # Nestlé Malaysia
    "5296",  # QL Resources
    "5246",  # Westports
    "5014",  # MAHB
    "5186",  # Inari Amertron
]


def main():
    conn = psycopg2.connect(
        host=os.environ.get('PGHOST', 'localhost'),
        port=int(os.environ.get('PGPORT', '5432')),
        dbname=os.environ.get('PGDATABASE', 'postgres'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', 'postgres'),
    )

    tickers = list(KLSE_STOCKS.keys())
    print(f"KLSE stocks to seed: {len(tickers)}")

    with conn.cursor() as cur:
        rows = [
            (code, 'KLSE', f'{code}.KL', KLSE_STOCKS[code], True, 'manual')
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

        dir_rows = [(code, KLSE_STOCKS[code], 'KLSE', 'en') for code in tickers]
        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.stock_directory (symbol, name, exchange, lang)
            VALUES %s
            ON CONFLICT (symbol, exchange, lang) DO UPDATE SET name = EXCLUDED.name
        """, dir_rows, page_size=200)
        print(f"Seeded {len(dir_rows)} rows into stock_directory")

        for i, code in enumerate(FEATURED_KLSE, 1):
            cur.execute(
                "UPDATE datapai.ticker_universe SET is_featured = TRUE, featured_order = %s "
                "WHERE ticker = %s AND exchange = 'KLSE'",
                (i, code),
            )
        print(f"Set {len(FEATURED_KLSE)} featured KLSE blue chips")

        conn.commit()
    conn.close()
    print("Done!")


if __name__ == '__main__':
    main()
