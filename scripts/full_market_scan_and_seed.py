#!/usr/bin/env python3
"""
Full market scan & seed — discovers ALL valid tickers for an exchange via yfinance,
then seeds into ticker_universe + stock_directory + backfills 5yr OHLCV.

Usage:
    # Single exchange
    python3 scripts/full_market_scan_and_seed.py --exchange HKEX

    # All 5 new markets sequentially
    python3 scripts/full_market_scan_and_seed.py --all

    # Scan only (no backfill)
    python3 scripts/full_market_scan_and_seed.py --exchange SET --scan-only

Exchange scan strategies:
    HKEX: numeric codes 0001-9999 → .HK (Main Board + GEM)
    KLSE: numeric codes 0001-9999 → .KL
    IDX:  alphabetic codes from known list + web scrape → .JK
    SET:  alphabetic codes from known list + web scrape → .BK
    HOSE: alphabetic codes already seeded (691), skip
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("full_market_scan")

BATCH_SIZE = 500  # yfinance batch download size
SLEEP_BETWEEN = 1.0  # seconds between batches


def get_conn():
    return psycopg2.connect(
        host=os.environ.get('PGHOST', 'localhost'),
        port=int(os.environ.get('PGPORT', '5432')),
        dbname=os.environ.get('PGDATABASE', 'postgres'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', 'postgres'),
    )


def scan_numeric_exchange(suffix: str, start: int = 1, end: int = 10000) -> dict:
    """Scan numeric code range (HKEX, KLSE) — returns {yf_symbol: last_close}."""
    codes = [f"{i:04d}{suffix}" for i in range(start, end)]
    log.info("Scanning %d codes for %s (%04d-%04d)", len(codes), suffix, start, end - 1)
    return _batch_scan(codes)


def scan_alphabetic_exchange(suffix: str, known_tickers: list) -> dict:
    """Scan known alphabetic tickers (SET, IDX) — returns {yf_symbol: last_close}."""
    codes = [f"{t}{suffix}" for t in known_tickers]
    log.info("Scanning %d known tickers for %s", len(codes), suffix)
    return _batch_scan(codes)


def _batch_scan(codes: list) -> dict:
    """Batch download to find valid tickers. Returns {symbol: close_price}."""
    valid = {}
    for start in range(0, len(codes), BATCH_SIZE):
        batch = codes[start:start + BATCH_SIZE]
        try:
            data = yf.download(
                " ".join(batch), period="5d", group_by="ticker",
                progress=False, threads=True, auto_adjust=True,
            )
            if data is not None and not data.empty:
                if isinstance(data.columns, pd.MultiIndex):
                    avail = set(data.columns.get_level_values(0))
                    for sym in batch:
                        try:
                            if sym in avail:
                                close = data[sym]["Close"].dropna()
                                if len(close) > 0 and float(close.iloc[-1]) > 0:
                                    valid[sym] = round(float(close.iloc[-1]), 4)
                        except Exception:
                            pass
                elif len(batch) == 1:
                    close = data["Close"].dropna()
                    if len(close) > 0 and float(close.iloc[-1]) > 0:
                        valid[batch[0]] = round(float(close.iloc[-1]), 4)
        except Exception as e:
            log.warning("Batch error at %d: %s", start, str(e)[:100])

        done = min(start + BATCH_SIZE, len(codes))
        if done % 1000 < BATCH_SIZE or done == len(codes):
            log.info("  %d/%d scanned, %d valid", done, len(codes), len(valid))
        time.sleep(SLEEP_BETWEEN)

    return valid


def get_company_names_batch(symbols: list) -> dict:
    """Get company names for a batch of symbols via yfinance. Returns {symbol: name}."""
    names = {}
    for i, sym in enumerate(symbols):
        try:
            tk = yf.Ticker(sym)
            info = tk.info or {}
            name = info.get("longName") or info.get("shortName") or ""
            if name:
                names[sym] = name[:200]
        except Exception:
            pass
        if (i + 1) % 100 == 0:
            log.info("  Names: %d/%d fetched", i + 1, len(symbols))
            time.sleep(1)
    return names


def seed_to_db(exchange: str, suffix: str, valid_tickers: dict, names: dict):
    """Delete old data and seed fresh tickers + stock_directory."""
    conn = get_conn()
    ticker_code = lambda sym: sym.replace(suffix, "")

    with conn.cursor() as cur:
        # Delete old data for this exchange
        cur.execute("DELETE FROM datapai.stock_directory WHERE exchange = %s", (exchange,))
        old_dir = cur.rowcount
        cur.execute("DELETE FROM datapai.ticker_universe WHERE exchange = %s", (exchange,))
        old_uni = cur.rowcount
        log.info("Deleted old data: %d from ticker_universe, %d from stock_directory", old_uni, old_dir)

        # Seed ticker_universe
        rows = [
            (ticker_code(sym), exchange, sym, names.get(sym, ticker_code(sym)), True, 'yfinance_full_scan')
            for sym in valid_tickers
        ]
        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.ticker_universe (ticker, exchange, yf_symbol, company_name, is_active, source)
            VALUES %s
            ON CONFLICT (ticker, exchange) DO UPDATE SET
                yf_symbol = EXCLUDED.yf_symbol, company_name = EXCLUDED.company_name,
                is_active = TRUE, source = EXCLUDED.source, updated_at = NOW()
        """, rows, page_size=500)
        log.info("Seeded %d tickers into ticker_universe", len(rows))

        # Seed stock_directory (en + 7 fallback languages)
        langs = ['en', 'zh', 'zh-TW', 'ja', 'ko', 'vi', 'th', 'ms']
        dir_rows = []
        for sym in valid_tickers:
            code = ticker_code(sym)
            name = names.get(sym, code)
            for lang in langs:
                dir_rows.append((code, name, exchange, lang))
        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.stock_directory (symbol, name, exchange, lang)
            VALUES %s
            ON CONFLICT (symbol, exchange, lang) DO UPDATE SET name = EXCLUDED.name
        """, dir_rows, page_size=1000)
        log.info("Seeded %d rows into stock_directory (%d tickers x %d langs)", len(dir_rows), len(valid_tickers), len(langs))

        conn.commit()
    conn.close()


def set_featured(exchange: str, featured_tickers: list):
    """Mark top N tickers as featured."""
    conn = get_conn()
    with conn.cursor() as cur:
        # Reset all featured for this exchange
        cur.execute("UPDATE datapai.ticker_universe SET is_featured = FALSE, featured_order = 0 WHERE exchange = %s", (exchange,))
        for i, ticker in enumerate(featured_tickers, 1):
            cur.execute(
                "UPDATE datapai.ticker_universe SET is_featured = TRUE, featured_order = %s WHERE ticker = %s AND exchange = %s",
                (i, ticker, exchange),
            )
        conn.commit()
    conn.close()
    log.info("Set %d featured tickers for %s", len(featured_tickers), exchange)


def backfill_ohlcv(exchange: str, suffix: str, valid_tickers: dict, years: int = 5):
    """Backfill historical OHLCV for all valid tickers."""
    from scripts.lib.db_helpers import df_to_daily_rows, upsert_daily_rows

    symbols = list(valid_tickers.keys())
    log.info("Backfilling %d tickers for %s (%d years)", len(symbols), exchange, years)

    total_rows = 0
    for start in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[start:start + BATCH_SIZE]
        try:
            data = yf.download(
                " ".join(batch), period=f"{years}y", group_by="ticker",
                progress=False, threads=True, auto_adjust=True,
            )
            if data is None or data.empty:
                continue

            rows = []
            if isinstance(data.columns, pd.MultiIndex):
                avail = set(data.columns.get_level_values(0))
                for sym in batch:
                    if sym in avail:
                        df = data[sym]
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.get_level_values(-1)
                        r = df_to_daily_rows(df, sym, exchange, "yahoo")
                        rows.extend(r)
            elif len(batch) == 1:
                r = df_to_daily_rows(data, batch[0], exchange, "yahoo")
                rows.extend(r)

            if rows:
                upsert_daily_rows(rows, f"{exchange} batch {start // BATCH_SIZE + 1}")
                total_rows += len(rows)

        except Exception as e:
            log.warning("Backfill batch error at %d: %s", start, str(e)[:100])

        done = min(start + BATCH_SIZE, len(symbols))
        log.info("  Backfill: %d/%d tickers, %d rows so far", done, len(symbols), total_rows)
        time.sleep(SLEEP_BETWEEN)

    log.info("Backfill complete: %d total rows for %s", total_rows, exchange)


# ── Known ticker lists for alphabetic exchanges ──────────────────────────────

# These are scraped/curated lists of ALL known tickers on each exchange.
# For exchanges with alphabetic codes, we can't brute-force scan like numeric ones.

def get_set_all_tickers():
    """All ~800 SET tickers (Thailand). Source: SET website + stockanalysis."""
    # SET50 + SET100 + rest of Main Board
    # This is a comprehensive list — will be validated by yfinance scan
    from scripts.migrations.seed_set_tickers import SET_STOCKS
    base = list(SET_STOCKS.keys())
    # Add more common SET tickers not in our curated list
    extra = [
        "2S", "7UP", "A", "AAV", "ABPIF", "ABM", "ACC", "ACE", "ACG", "ADB",
        "ADVANC", "AEC", "AEONTS", "AFC", "AGE", "AH", "AHOLD", "AI", "AIRA",
        "AIT", "AJ", "AKP", "AKR", "ALL", "ALLA", "ALT", "ALTO", "ALUCON",
        "AMA", "AMATA", "AMIN", "AMORPH", "ANAN", "AOT", "AP", "APCO", "APCS",
        "APP", "AQUA", "ARIP", "AS", "ASAP", "ASEFA", "ASK", "ASN", "ASP",
        "ASW", "ATP", "AU", "AUCT", "AWC", "AYUD", "B", "BA", "BAFS", "BAM",
        "BANPU", "BAY", "BBL", "BC", "BCH", "BCP", "BCPG", "BDMS", "BEAUTY",
        "BEC", "BEM", "BEYOND", "BGC", "BGRIM", "BGT", "BH", "BIG", "BIZ",
        "BJC", "BJCHI", "BKD", "BKI", "BLA", "BOL", "BPP", "BR", "BROOK",
        "BRR", "BSBM", "BTC", "BTGN", "BTW", "BTS", "BTNC", "BUI", "BWG",
        "CAZ", "CBG", "CCET", "CCP", "CENTEL", "CGD", "CGH", "CHARAN", "CHG",
        "CHO", "CHOW", "CI", "CIMBT", "CK", "CKP", "CM", "CMAN", "CMC",
        "CMO", "CMR", "CNS", "CNT", "COL", "COM7", "COMAN", "CONN", "COSCO",
        "CPALL", "CPAXT", "CPF", "CPI", "CPL", "CPN", "CRANE", "CRC", "CRD",
        "CSC", "CSP", "CSS", "CSR", "CWT", "D", "DCON", "DDD", "DELTA",
        "DEMCO", "DIF", "DIMET", "DOD", "DPAINT", "DRT", "DTAC", "DTC",
        "DUSIT", "EA", "EARTH", "EASTW", "ECF", "ECL", "EE", "EFORL", "EGCO",
        "EKH", "EASON", "EMC", "EP", "EPG", "ERA", "ERW", "ESTAR", "ETC",
        "EVER", "F", "FANCY", "FE", "FIRE", "FLASH", "FMT", "FN", "FNS",
        "FORTH", "FPT", "FPI", "FSMART", "FSS", "FVC", "GBX", "GC", "GEL",
        "GFPT", "GGC", "GIFT", "GJS", "GL", "GLAND", "GLOBAL", "GLOW",
        "GOLD", "GPSC", "GRAMMY", "GREEN", "GULF", "GUNKUL", "GYT", "HANA",
        "HARN", "HFT", "HMPRO", "HPT", "HTC", "HUMAN", "HYDRO", "ICC",
        "ICN", "ICHI", "ILINK", "ILUMIN", "IMH", "INET", "INGRS", "INOX",
        "INSURE", "INTUCH", "IRC", "IRPC", "IT", "IVL", "J", "JAS", "JASIF",
        "JAY", "JCK", "JCKH", "JKN", "JMART", "JMT", "JSTEEL", "JTS", "JUBILE",
        "JWD", "K", "KAMART", "KBANK", "KBS", "KCE", "KDH", "KGI", "KKP",
        "KSL", "KTB", "KTC", "KWC", "KYE", "L", "LANNA", "LALIN", "LH",
        "LHFG", "LIT", "LIVE", "LOXLEY", "LPN", "LPH", "LST", "LTX",
        "M", "MALEE", "MAJOR", "MAKRO", "MATCH", "MATI", "MAX", "MC",
        "MCOT", "MDX", "MEGA", "META", "MFEC", "MICRO", "MILL", "MINT",
        "MJD", "MK", "ML", "MM", "MODERN", "MONO", "MOONG", "MPIC", "MTC",
        "MTI", "MVP", "NBC", "NCH", "NEP", "NET", "NER", "NEW", "NOBLE",
        "NOK", "NSI", "NTV", "NVD", "NUSA", "NWR", "NYT", "OCC", "OGC",
        "OHTL", "OKJ", "ONEE", "ORI", "OSP", "OTO", "PAE", "PAF", "PAP",
        "PATO", "PB", "PCSGH", "PDG", "PE", "PF", "PG", "PICO", "PLANB",
        "PLAT", "PM", "PMTA", "POLAR", "PORT", "POST", "PPAL", "PPM", "PPS",
        "PRANDA", "PREB", "PRIN", "PRINC", "PRM", "PSH", "PSL", "PTG", "PTL",
        "PTT", "PTTEP", "PTTGC", "PYLON", "Q", "QH", "QLT", "QTC", "RAM",
        "RATCH", "RBF", "RCL", "ROBINS", "RPC", "RS", "S", "S11", "SABINA",
        "SABUY", "SAMART", "SAMCO", "SAMTEL", "SAK", "SAPPE", "SAT", "SAWAD",
        "SC", "SCAN", "SCB", "SCC", "SCCC", "SCG", "SCGP", "SCI", "SE-ED",
        "SEAFCO", "SFP", "SGF", "SGP", "SHANG", "SINGER", "SIRI", "SIS",
        "SITHAI", "SKR", "SLP", "SMART", "SMD", "SMIT", "SMPC", "SMT", "SNC",
        "SNP", "SOLAR", "SORKON", "SPA", "SPACK", "SPALI", "SPCG", "SPRC",
        "SQ", "SR", "SRICHA", "SSF", "SSP", "SSTRT", "STA", "STEC", "STGT",
        "STI", "SUC", "SUN", "SUPER", "SUSCO", "SUTHA", "SVH", "SWC", "SYMC",
        "SYNEX", "SYNTEC", "T", "TACC", "TAE", "TASCO", "TCAP", "TCC", "TCJ",
        "TEAM", "TFG", "TFI", "TGCI", "TH", "THAI", "THANA", "THANI",
        "THANULUX", "THCOM", "THIP", "THREL", "TIDLOR", "TIW", "TISCO",
        "TK", "TKN", "TKS", "TKT", "TMB", "TMD", "TMILL", "TMT", "TNDT",
        "TNR", "TNP", "TOA", "TOG", "TOP", "TOPP", "TPBI", "TPIPL", "TPIPP",
        "TQM", "TQR", "TR", "TRC", "TRITN", "TRT", "TRU", "TRUE", "TSC",
        "TSE", "TSR", "TTA", "TTB", "TTCL", "TTW", "TU", "TVO", "TWP",
        "TWZ", "TYONG", "U", "UAC", "UBE", "UBIS", "UP", "UPF", "UMS",
        "UOBKH", "UPA", "UPOIC", "UREKA", "UTF", "UV", "VGI", "VIBHA",
        "VIH", "VNT", "VPO", "VRANDA", "W", "WACOAL", "WAVE", "WFX",
        "WG", "WHA", "WHAUP", "WICE", "WINNER", "WINMED", "WORK", "WP",
        "WPH", "XO", "ZEN", "ZIGA",
    ]
    return list(set(base + extra))


def get_idx_all_tickers():
    """All ~900 IDX tickers (Indonesia). Source: IDX website + stockanalysis."""
    from scripts.migrations.seed_idx_tickers import IDX_STOCKS
    base = list(IDX_STOCKS.keys())
    extra = [
        "AADI", "ABBA", "ABDA", "ABMM", "ACST", "ADES", "ADHI", "ADMF", "ADRO",
        "AEGS", "AGII", "AGRO", "AGRS", "AHAP", "AISA", "AKKU", "AKPI", "AKRA",
        "AKSI", "ALDO", "ALKA", "ALMI", "ALTO", "AMAG", "AMAN", "AMAR", "AMFG",
        "AMIN", "AMRT", "ANDI", "ANJT", "ANTM", "APEX", "APIC", "APII", "APLI",
        "APLN", "ARCI", "AREA", "ARGO", "ARII", "ARMY", "ARNA", "ARTA", "ARTI",
        "ARTO", "ASGR", "ASII", "ASJT", "ASMI", "ASPI", "ASRI", "ASSA", "ATAP",
        "AUTO", "AVIA", "AYAM", "BABP", "BACA", "BAJA", "BALI", "BALL", "BAPA",
        "BATA", "BBCA", "BBHI", "BBKP", "BBLD", "BBMD", "BBNI", "BBRI", "BBRM",
        "BBSS", "BBTN", "BBYB", "BCAP", "BCIC", "BCIP", "BDMN", "BEKS", "BELL",
        "BESS", "BEST", "BFIN", "BGTG", "BHAT", "BHIT", "BIKA", "BIMA", "BINA",
        "BIRD", "BISI", "BJBR", "BJTM", "BKDP", "BKSL", "BLTA", "BLTZ", "BMRI",
        "BMTR", "BNBA", "BNBR", "BNGA", "BNII", "BNLI", "BOLT", "BRAM", "BRIS",
        "BRMS", "BRNA", "BRPT", "BSDE", "BSML", "BSSR", "BTEK", "BTON", "BTPN",
        "BTPS", "BUDI", "BUKA", "BUKK", "BULL", "BUMI", "BUVA", "BWPT", "BYAN",
        "CAKK", "CAMP", "CANI", "CARE", "CASA", "CASH", "CASS", "CEKA", "CENT",
        "CFIN", "CINT", "CITA", "CLPI", "CLEO", "CMNT", "CMPP", "CMRY", "CNKO",
        "CNTX", "COCO", "COWL", "CPIN", "CPRI", "CSAP", "CSIS", "CTBN", "CTRA",
        "CUAN", "DADA", "DART", "DAYA", "DEAL", "DEPO", "DEWA", "DFAM", "DGIK",
        "DGNS", "DILD", "DIVA", "DKFT", "DLTA", "DMAS", "DMMX", "DNAR", "DNET",
        "DOID", "DPNS", "DSFI", "DSNG", "DSSA", "DUCK", "DUTI", "DWGL", "EAST",
        "ECII", "EDGE", "EKAD", "ELSA", "ELTY", "EMDE", "EMTK", "ENAK", "ENRG",
        "EPMT", "ERAA", "ERTX", "ESIP", "ESSA", "ESTI", "ETAL", "EXCL", "FACE",
        "FAPA", "FAST", "FILM", "FIRE", "FISH", "FITT", "FLMC", "FMII", "FOOD",
        "FORU", "FPNI", "FREN", "FUJI", "GAMA", "GDST", "GDYR", "GEMA", "GEMS",
        "GGRM", "GGRP", "GHON", "GIAA", "GJTL", "GLOB", "GLVA", "GOLD", "GOTO",
        "GPRA", "GRIA", "GRPH", "GSMF", "GTBO", "GWSA", "GZCO", "HADE", "HAIS",
        "HBAT", "HDTX", "HEAL", "HERO", "HGII", "HGML", "HILL", "HITS", "HMSP",
        "HOKI", "HOME", "HOTL", "HRME", "HRTA", "HRUM", "IATA", "IBST", "ICBP",
        "ICON", "IDEA", "IDPR", "IFII", "IFSH", "IGAR", "IMAS", "IMJS", "INAF",
        "INAI", "INCI", "INCO", "INDF", "INDO", "INDR", "INDS", "INDX", "INDY",
        "INKP", "INOV", "INPC", "INPP", "INPS", "INTA", "INTD", "INTP", "IPAC",
        "IPCM", "IPOL", "IPPE", "IPTV", "IRRA", "ISAT", "ISSP", "ITIC", "ITMA",
        "ITMG", "JAWA", "JAYA", "JGLE", "JIHD", "JKON", "JKSW", "JMAS", "JPFA",
        "JRPT", "JSKY", "JSMR", "JTPE", "KAEF", "KARW", "KBAG", "KBLI", "KBLM",
        "KBLV", "KDSI", "KEEN", "KEJU", "KIAS", "KICI", "KIJA", "KINO", "KIOS",
        "KLBF", "KMDS", "KMTR", "KOIN", "KONI", "KOPI", "KOTA", "KPAL", "KPAS",
        "KPIG", "KRAS", "KREN", "LINK", "LION", "LMPI", "LMSH", "LPCK", "LPGI",
        "LPIN", "LPKR", "LPPF", "LPPS", "LSIP", "LTLS", "LUCK", "MABA", "MAHA",
        "MAIN", "MAMI", "MANG", "MAPI", "MARK", "MASA", "MAYA", "MBAP", "MBSS",
        "MBTO", "MCOL", "MDKA", "MDKI", "MDLN", "MEDC", "MEGA", "MERK", "META",
        "MFIN", "MFMI", "MGNA", "MICE", "MIDI", "MIKA", "MINA", "MLBI", "MLIA",
        "MLPL", "MLPT", "MMLP", "MNCN", "MOLI", "MPIX", "MPPA", "MPRO", "MRAT",
        "MSIN", "MSKY", "MTDL", "MTLA", "MTPS", "MTSM", "MTWI", "MYOH", "MYOR",
        "NAGA", "NCKL", "NELY", "NICK", "NIKL", "NIRO", "NISP", "NOBU", "NRCA",
        "NUSA", "OASA", "OBMD", "OCAP", "OILS", "OKAS", "OMED", "OMRE", "OPMS",
        "PADI", "PALM", "PANR", "PANS", "PBID", "PBRX", "PCAR", "PDES", "PEGE",
        "PEHA", "PGAS", "PGEO", "PGLI", "PGUN", "PICO", "PJAA", "PKPK", "PLAN",
        "PLIN", "PMJS", "PNBN", "PNLF", "PNSE", "POLL", "POLU", "POOL", "PORT",
        "POSA", "PPRE", "PPRO", "PRAS", "PRAY", "PRDA", "PRIM", "PSAB", "PSDN",
        "PSGO", "PSKT", "PSSI", "PTBA", "PTDU", "PTIS", "PTPP", "PTPS", "PTRO",
        "PTSN", "PUDP", "PURA", "PURE", "PURI", "PWON", "PYFA", "RAJA", "RALS",
        "RANC", "RBMS", "RDTX", "REAL", "RELI", "RICY", "RIGS", "RIMO", "RISE",
        "RMBA", "RMKE", "ROCK", "RODA", "RONY", "ROTI", "RUIS", "RUNS", "SAFE",
        "SAGE", "SAII", "SAME", "SAMF", "SAPX", "SATU", "SBAT", "SBMA", "SCBD",
        "SCCO", "SCMA", "SCNP", "SDMU", "SDPC", "SDRA", "SEMA", "SGER", "SGRO",
        "SHID", "SHIP", "SICO", "SIDO", "SILO", "SIMA", "SIMP", "SIPD", "SKBM",
        "SKLT", "SKRN", "SLAD", "SLIS", "SMAR", "SMBR", "SMCB", "SMDR", "SMDM",
        "SMGR", "SMKL", "SMMA", "SMMT", "SMRA", "SMRU", "SMSM", "SNLK", "SOCI",
        "SOFA", "SOHO", "SOSS", "SOUL", "SPAL", "SPMA", "SPTO", "SQMI", "SRAJ",
        "SRIL", "SRSN", "SRTG", "SSMS", "SSTM", "STAR", "STTP", "SUGI", "SULI",
        "SURE", "SWAT", "TAPG", "TARA", "TAXI", "TAYS", "TBIG", "TBLA", "TBMS",
        "TCID", "TELE", "TGKA", "TGRA", "TINS", "TIRA", "TKIM", "TLKM", "TMAS",
        "TMPO", "TNCA", "TOBA", "TOPS", "TOTL", "TOWR", "TOYS", "TPIA", "TPMA",
        "TRIM", "TRIS", "TRJA", "TRST", "TRUE", "TRUK", "TRUS", "TSPC", "TURI",
        "UANG", "UCID", "UFOE", "ULTJ", "UNIC", "UNIT", "UNSP", "UNTR", "UNVR",
        "URBN", "VICI", "VINS", "VIVA", "VKTR", "VRNA", "WAPO", "WEGE", "WEHA",
        "WGSH", "WICO", "WIKA", "WINE", "WINS", "WMPP", "WMUU", "WOOD", "WOWS",
        "WSBP", "WSKT", "WTON", "YELO", "ZBRA", "ZINC", "ZONE",
    ]
    return list(set(base + extra))


# ── Featured tickers per exchange ──
FEATURED = {
    "HKEX": ["9988", "0700", "1299", "0005", "0941", "3690", "1211", "1810", "0939", "1398",
             "2318", "9618", "0388", "0883", "1024", "9888", "0175", "2020", "9999", "0027"],
    "SET": ["DELTA", "PTT", "ADVANC", "AOT", "GULF", "CPALL", "PTTEP", "SCB", "BDMS", "TRUE",
            "KBANK", "SCC", "BBL", "CPN", "MINT", "OR", "KTB", "IVL", "BH", "HMPRO"],
    "KLSE": ["1155", "1295", "1023", "5347", "5225", "5183", "6033", "5681", "4731", "5285",
             "5819", "3816", "6012", "6947", "2488", "4707", "5296", "5246", "5014", "5186"],
    "IDX": ["BBCA", "BBRI", "BMRI", "TLKM", "ASII", "BBNI", "UNVR", "HMSP", "ICBP", "KLBF",
            "ADRO", "GOTO", "AMRT", "UNTR", "CPIN", "TOWR", "BRPT", "MDKA", "SMGR", "MYOR"],
    "HOSE": [],  # already has featured set
}


def process_exchange(exchange: str, scan_only: bool = False, years: int = 5):
    """Full pipeline for one exchange: scan → seed → featured → backfill."""
    EXCHANGE_CONFIG = {
        "HKEX": {"suffix": ".HK", "type": "numeric", "range": (1, 10000)},
        "KLSE": {"suffix": ".KL", "type": "numeric", "range": (1, 10000)},
        "SET":  {"suffix": ".BK", "type": "alpha", "loader": get_set_all_tickers},
        "IDX":  {"suffix": ".JK", "type": "alpha", "loader": get_idx_all_tickers},
    }

    if exchange not in EXCHANGE_CONFIG:
        log.error("Unknown exchange: %s", exchange)
        return

    cfg = EXCHANGE_CONFIG[exchange]
    suffix = cfg["suffix"]

    log.info("=" * 60)
    log.info("  EXCHANGE: %s (suffix: %s)", exchange, suffix)
    log.info("=" * 60)

    # Step 1: Scan
    if cfg["type"] == "numeric":
        start, end = cfg["range"]
        valid = scan_numeric_exchange(suffix, start, end)
    else:
        tickers = cfg["loader"]()
        valid = scan_alphabetic_exchange(suffix, tickers)

    log.info("Found %d valid tickers for %s", len(valid), exchange)

    if not valid:
        log.error("No valid tickers found — skipping")
        return

    # Step 2: Get company names (slow but one-time)
    log.info("Fetching company names for %d tickers...", len(valid))
    names = get_company_names_batch(list(valid.keys()))
    log.info("Got names for %d/%d tickers", len(names), len(valid))

    # Step 3: Seed to DB
    seed_to_db(exchange, suffix, valid, names)

    # Step 4: Set featured
    if FEATURED.get(exchange):
        set_featured(exchange, FEATURED[exchange])

    if scan_only:
        log.info("Scan-only mode — skipping backfill")
        return

    # Step 5: Backfill OHLCV
    backfill_ohlcv(exchange, suffix, valid, years)

    log.info("=" * 60)
    log.info("  %s COMPLETE: %d tickers, names + %dyr OHLCV", exchange, len(valid), years)
    log.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Full market scan, seed, and backfill")
    parser.add_argument("--exchange", help="Single exchange: HKEX, SET, KLSE, IDX")
    parser.add_argument("--all", action="store_true", help="Process all 4 new markets")
    parser.add_argument("--scan-only", action="store_true", help="Scan + seed only, skip backfill")
    parser.add_argument("--years", type=int, default=5, help="Years of history (default: 5)")
    args = parser.parse_args()

    if args.all:
        for ex in ["HKEX", "SET", "KLSE", "IDX"]:
            process_exchange(ex, scan_only=args.scan_only, years=args.years)
    elif args.exchange:
        process_exchange(args.exchange.upper(), scan_only=args.scan_only, years=args.years)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
