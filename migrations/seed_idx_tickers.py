#!/usr/bin/env python3
"""
Seed Indonesia (IDX) tickers into datapai.ticker_universe and stock_directory.

IDX has ~900 listed companies. We seed LQ45 + IDX80 + popular mid-caps (~200 total).
Yahoo Finance suffix: .JK (e.g., BBCA.JK = Bank Central Asia, TLKM.JK = Telkom)

Usage:
    PGHOST=localhost PGUSER=postgres PGPASSWORD=postgres python3 seed_idx_tickers.py
"""
import psycopg2
import psycopg2.extras
import os

# LQ45 + IDX80 + popular mid-caps
IDX_STOCKS = {
    # ── LQ45 (top 45 by liquidity + market cap) ──
    "BBCA": "Bank Central Asia",
    "BBRI": "Bank Rakyat Indonesia",
    "BMRI": "Bank Mandiri",
    "TLKM": "Telkom Indonesia",
    "ASII": "Astra International",
    "UNVR": "Unilever Indonesia",
    "BBNI": "Bank Negara Indonesia",
    "HMSP": "HM Sampoerna",
    "GGRM": "Gudang Garam",
    "ICBP": "Indofood CBP Sukses Makmur",
    "INDF": "Indofood Sukses Makmur",
    "KLBF": "Kalbe Farma",
    "SMGR": "Semen Indonesia",
    "UNTR": "United Tractors",
    "PGAS": "Perusahaan Gas Negara",
    "ADRO": "Adaro Energy",
    "ANTM": "Aneka Tambang",
    "INCO": "Vale Indonesia",
    "PTBA": "Bukit Asam",
    "BRPT": "Barito Pacific",
    "CPIN": "Charoen Pokphand Indonesia",
    "EMTK": "Elang Mahkota Teknologi",
    "EXCL": "XL Axiata",
    "GOTO": "GoTo Gojek Tokopedia",
    "HRUM": "Harum Energy",
    "INTP": "Indocement Tunggal Prakarsa",
    "ITMG": "Indo Tambangraya Megah",
    "JPFA": "Japfa Comfeed Indonesia",
    "MAPI": "Mitra Adiperkasa",
    "MDKA": "Merdeka Copper Gold",
    "MEDC": "Medco Energi Internasional",
    "MNCN": "Media Nusantara Citra",
    "PNBN": "Bank Pan Indonesia",
    "SMRA": "Summarecon Agung",
    "TBIG": "Tower Bersama Infrastructure",
    "TKIM": "Pabrik Kertas Tjiwi Kimia",
    "TOWR": "Sarana Menara Nusantara",
    "TPIA": "Chandra Asri Petrochemical",
    "ESSA": "Surya Esa Perkasa",
    "ACES": "Ace Hardware Indonesia",
    "AMRT": "Sumber Alfaria Trijaya (Alfamart)",
    "BSDE": "Bumi Serpong Damai",
    "CTRA": "Ciputra Development",
    "ERAA": "Erajaya Swasembada",
    "SIDO": "Industri Jamu dan Farmasi Sido Muncul",

    # ── IDX80 additions ──
    "AKRA": "AKR Corporindo",
    "ARTO": "Bank Jago",
    "BBTN": "Bank Tabungan Negara",
    "BFIN": "BFI Finance Indonesia",
    "BIRD": "Blue Bird Group",
    "BJBR": "Bank Jabar Banten",
    "BRIS": "Bank Syariah Indonesia",
    "BUKA": "Bukalapak",
    "CLEO": "Sariguna Primatirta",
    "DMAS": "Puradelta Lestari",
    "DSNG": "Dharma Satya Nusantara",
    "ELSA": "Elnusa",
    "GJTL": "Gajah Tunggal",
    "HEAL": "Medikaloka Hermina",
    "INKP": "Indah Kiat Pulp & Paper",
    "ISAT": "Indosat Ooredoo Hutchison",
    "JSMR": "Jasa Marga",
    "LPPF": "Matahari Department Store",
    "MIKA": "Mitra Keluarga Karyasehat",
    "MYOR": "Mayora Indah",
    "PGEO": "Pertamina Geothermal Energy",
    "PWON": "Pakuwon Jati",
    "SCMA": "Surya Citra Media",
    "SRTG": "Saratoga Investama Sedaya",
    "TAPG": "Triputra Agro Persada",
    "TINS": "Timah",
    "WIKA": "Wijaya Karya",
    "WSKT": "Waskita Karya",

    # ── Popular mid-caps ──
    "AAON": "Alam Sutera Realty",
    "ADMR": "Adaro Minerals Indonesia",
    "AGII": "Aneka Gas Industri",
    "AISA": "Tiga Pilar Sejahtera Food",
    "ANJT": "Austindo Nusantara Jaya",
    "APLN": "Agung Podomoro Land",
    "ASRI": "Alam Sutera Realty",
    "AUTO": "Astra Otoparts",
    "BDMN": "Bank Danamon",
    "BJTM": "Bank Jatim",
    "BMTR": "Global Mediacom",
    "BSML": "Bank Sampoerna",
    "BTPS": "Bank BTPN Syariah",
    "CMRY": "Cisarua Mountain Dairy",
    "CSIS": "Cahayasakti Investindo Sukses",
    "DILD": "Intiland Development",
    "DLTA": "Delta Djakarta",
    "DSFI": "Dharma Samudera Fishing",
    "DSSA": "Dian Swastatika Sentosa",
    "EAST": "Eastspring Investments",
    "FILM": "MD Entertainment",
    "GIAA": "Garuda Indonesia",
    "HERO": "Hero Supermarket",
    "HITS": "Humpuss Intermoda Transportasi",
    "HRTA": "Hartadinata Abadi",
    "IBST": "Inti Bangun Sejahtera",
    "INDY": "Indika Energy",
    "INTA": "Intraco Penta",
    "IPCM": "Jasa Armada Indonesia",
    "JRPT": "Jaya Real Property",
    "KAEF": "Kimia Farma",
    "KEJU": "Mulia Boga Raya",
    "KINO": "Kino Indonesia",
    "LINK": "Link Net",
    "LSIP": "London Sumatra Indonesia",
    "LTLS": "Lautan Luas",
    "LUCK": "Sentral Mitra Informatika Tbk",
    "MAIN": "Malindo Feedmill",
    "MEGA": "Bank Mega",
    "MLBI": "Multi Bintang Indonesia",
    "NELY": "Pelayaran Nelly Dwi Putri",
    "NISP": "Bank OCBC NISP",
    "PANR": "Panorama Sentrawisata",
    "PNLF": "Panin Financial",
    "PTPP": "PP (Persero)",
    "RALS": "Ramayana Lestari Sentosa",
    "RANC": "Supra Boga Lestari",
    "SGER": "Sumber Global Energy",
    "SGRO": "Sampoerna Agro",
    "SIMP": "Salim Ivomas Pratama",
    "SMBR": "Semen Baturaja",
    "SMDR": "Samudera Indonesia",
    "SMSM": "Selamat Sempurna",
    "SSMS": "Sawit Sumbermas Sarana",
    "TELE": "Tiphone Mobile Indonesia",
    "TMAS": "Pelayaran Tempuran Emas",
    "TURI": "Tunas Ridean",
    "ULTJ": "Ultra Jaya Milk Industry",
    "VIVA": "Visi Media Asia",
    "WTON": "Wijaya Karya Beton",
}

# ── Featured IDX blue chips (top 20 by market cap) ──
FEATURED_IDX = [
    "BBCA",  # BCA
    "BBRI",  # BRI
    "BMRI",  # Mandiri
    "TLKM",  # Telkom
    "ASII",  # Astra
    "BBNI",  # BNI
    "UNVR",  # Unilever
    "HMSP",  # HM Sampoerna
    "ICBP",  # Indofood CBP
    "KLBF",  # Kalbe Farma
    "ADRO",  # Adaro Energy
    "GOTO",  # GoTo
    "AMRT",  # Alfamart
    "UNTR",  # United Tractors
    "CPIN",  # Charoen Pokphand
    "TOWR",  # Sarana Menara
    "BRPT",  # Barito Pacific
    "MDKA",  # Merdeka Copper Gold
    "SMGR",  # Semen Indonesia
    "MYOR",  # Mayora
]


def main():
    conn = psycopg2.connect(
        host=os.environ.get('PGHOST', 'localhost'),
        port=int(os.environ.get('PGPORT', '5432')),
        dbname=os.environ.get('PGDATABASE', 'postgres'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', 'postgres'),
    )

    tickers = list(IDX_STOCKS.keys())
    print(f"IDX stocks to seed: {len(tickers)}")

    with conn.cursor() as cur:
        rows = [
            (code, 'IDX', f'{code}.JK', IDX_STOCKS[code], True, 'manual')
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

        dir_rows = [(code, IDX_STOCKS[code], 'IDX', 'en') for code in tickers]
        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.stock_directory (symbol, name, exchange, lang)
            VALUES %s
            ON CONFLICT (symbol, exchange, lang) DO UPDATE SET name = EXCLUDED.name
        """, dir_rows, page_size=200)
        print(f"Seeded {len(dir_rows)} rows into stock_directory")

        for i, code in enumerate(FEATURED_IDX, 1):
            cur.execute(
                "UPDATE datapai.ticker_universe SET is_featured = TRUE, featured_order = %s "
                "WHERE ticker = %s AND exchange = 'IDX'",
                (i, code),
            )
        print(f"Set {len(FEATURED_IDX)} featured IDX blue chips")

        conn.commit()
    conn.close()
    print("Done!")


if __name__ == '__main__':
    main()
