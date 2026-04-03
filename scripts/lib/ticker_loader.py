"""
scripts/lib/ticker_loader.py
─────────────────────────────────────────────────────────────────────────────
Fetch and cache the US + ASX ticker universes.

US  : NASDAQ + NYSE screener API (free, no auth)
ASX : Multiple sources tried in order; hardcoded top-600 fallback

Results are cached in scripts/cache/ to avoid repeated network calls.
Pass use_cache=False to force a fresh download.

Usage:
    from scripts.lib.ticker_loader import load_us_tickers, load_asx_tickers

    us_tickers  = load_us_tickers()    # → list["AAPL", "MSFT", ...]
    asx_tickers = load_asx_tickers()   # → list["BHP.AX", "CBA.AX", ...]

    # Load from a custom file (one ticker per line, or CSV first column):
    asx_tickers = load_tickers_from_file("/path/to/asx_tickers.txt")
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests
import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_DIR  = Path(__file__).parent.parent / "cache"
_CACHE_DIR.mkdir(exist_ok=True)

_US_CACHE   = _CACHE_DIR / "us_tickers.json"
_ASX_CACHE  = _CACHE_DIR / "asx_tickers.json"
_VN_CACHE   = _CACHE_DIR / "vietnam_tickers.json"

# Cache TTL: 7 days (ticker lists don't change daily)
_CACHE_TTL_SECS = 7 * 24 * 3600

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "application/json, text/csv, */*",
}


# ─────────────────────────────────────────────────────────────────────────────
# US Tickers — NASDAQ + NYSE screener
# ─────────────────────────────────────────────────────────────────────────────

_NASDAQ_SCREENER_URL = (
    "https://api.nasdaq.com/api/screener/stocks"
    "?tableonly=true&limit=10000&offset=0&exchange=nasdaq"
)
_NYSE_SCREENER_URL = (
    "https://api.nasdaq.com/api/screener/stocks"
    "?tableonly=true&limit=10000&offset=0&exchange=nyse"
)
_AMEX_SCREENER_URL = (
    "https://api.nasdaq.com/api/screener/stocks"
    "?tableonly=true&limit=5000&offset=0&exchange=amex"
)


def _fetch_nasdaq_screener(url: str) -> list[str]:
    """Fetch tickers from a NASDAQ screener URL. Returns list of ticker strings."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("data", {}).get("table", {}).get("rows", [])
        tickers = []
        for r in rows:
            sym = (r.get("symbol") or "").strip().upper()
            # Skip ETFs (/$), blank, very long symbols, or those with slashes
            if sym and len(sym) <= 5 and "/" not in sym and "$" not in sym:
                tickers.append(sym)
        return tickers
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return []


def load_us_tickers(use_cache: bool = True) -> list[str]:
    """
    Return deduplicated list of US stock tickers (NASDAQ + NYSE + AMEX).
    Cached for 7 days. Use use_cache=False to force refresh.
    """
    if use_cache and _US_CACHE.exists():
        age = time.time() - _US_CACHE.stat().st_mtime
        if age < _CACHE_TTL_SECS:
            tickers = json.loads(_US_CACHE.read_text())
            logger.info("US tickers from cache: %d tickers (age %.1fh)", len(tickers), age / 3600)
            return tickers

    logger.info("Fetching US ticker list from NASDAQ screener API...")
    nasdaq = _fetch_nasdaq_screener(_NASDAQ_SCREENER_URL)
    time.sleep(1)
    nyse   = _fetch_nasdaq_screener(_NYSE_SCREENER_URL)
    time.sleep(1)
    amex   = _fetch_nasdaq_screener(_AMEX_SCREENER_URL)

    # Deduplicate, sort
    all_tickers = sorted(set(nasdaq + nyse + amex))
    logger.info("US tickers fetched: %d total (NASDAQ=%d, NYSE=%d, AMEX=%d)",
                len(all_tickers), len(nasdaq), len(nyse), len(amex))

    _US_CACHE.write_text(json.dumps(all_tickers))
    return all_tickers


# ─────────────────────────────────────────────────────────────────────────────
# ASX Tickers — multiple free sources tried in order
#
# ASX removed their public CSV in early 2026. Sources tried:
#   1. stockanalysis.com  — comprehensive scrape, no auth
#   2. marketindex.com.au — another third-party list
#   3. Hardcoded ~600 top-cap tickers — permanent fallback
#
# For the full ~2200-stock universe: download from ASX website when logged in
# and pass the file via load_tickers_from_file("asx_all.csv").
# ─────────────────────────────────────────────────────────────────────────────

_STOCKANALYSIS_ASX = "https://stockanalysis.com/list/australian-stock-exchange/"


def _fetch_stockanalysis_asx() -> list[str]:
    """
    Scrape ASX ticker list from stockanalysis.com.
    Returns list of 'CODE.AX' strings or [] on failure.
    The page has a table with Symbol column.
    """
    try:
        resp = requests.get(_STOCKANALYSIS_ASX, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        # pandas can parse HTML tables directly
        tables = pd.read_html(io.StringIO(resp.text))
        if not tables:
            return []
        df = tables[0]  # first table contains the stock list
        # Try common column names
        sym_col = None
        for col in df.columns:
            if str(col).lower() in ("symbol", "ticker", "code"):
                sym_col = col
                break
        if sym_col is None:
            sym_col = df.columns[0]
        tickers = []
        for val in df[sym_col].dropna():
            code = str(val).strip().upper()
            if code and len(code) <= 5 and code.isalpha():
                tickers.append(f"{code}.AX")
        logger.info("stockanalysis.com: fetched %d ASX tickers", len(tickers))
        return tickers
    except Exception as e:
        logger.warning("stockanalysis.com ASX fetch failed: %s", e)
        return []


def load_asx_tickers(use_cache: bool = True) -> list[str]:
    """
    Return list of ASX stock tickers in yfinance format (e.g. 'BHP.AX').
    Cached for 7 days.

    Override for full universe:
        from scripts.lib.ticker_loader import load_tickers_from_file
        tickers = load_tickers_from_file("~/asx_all.csv", suffix=".AX")
    """
    if use_cache and _ASX_CACHE.exists():
        age = time.time() - _ASX_CACHE.stat().st_mtime
        if age < _CACHE_TTL_SECS:
            tickers = json.loads(_ASX_CACHE.read_text())
            logger.info("ASX tickers from cache: %d tickers (age %.1fh)", len(tickers), age / 3600)
            return tickers

    logger.info("Fetching ASX ticker list...")

    # Source 1: stockanalysis.com (best free public source)
    tickers = _fetch_stockanalysis_asx()

    # Source 2: fallback hardcoded top-600 tickers
    if not tickers:
        logger.warning("All live ASX sources failed — using hardcoded top-600 fallback")
        tickers = _asx_fallback_tickers()

    tickers = sorted(set(tickers))
    logger.info("ASX tickers loaded: %d", len(tickers))
    _ASX_CACHE.write_text(json.dumps(tickers))
    return tickers


# ─────────────────────────────────────────────────────────────────────────────
# Custom ticker file loader
# ─────────────────────────────────────────────────────────────────────────────

def load_tickers_from_file(path: str, suffix: str = "") -> list[str]:
    """
    Load tickers from a plain text or CSV file.

    Accepts:
      - One ticker per line:  BHP\\nCBA\\n...
      - CSV with ticker in first column:  BHP,Company Name,...
      - Tickers may or may not already have the suffix

    Parameters
    ----------
    path   : file path (absolute or relative to cwd)
    suffix : append this suffix if not already present (e.g. '.AX' for ASX)

    Returns list of ticker strings.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Ticker file not found: {p}")

    tickers = []
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # First CSV column
            code = line.split(",")[0].strip().upper()
            if not code:
                continue
            # Append suffix if needed
            if suffix and not code.endswith(suffix.upper()):
                code = f"{code}{suffix}"
            tickers.append(code)

    tickers = sorted(set(tickers))
    logger.info("Loaded %d tickers from %s", len(tickers), p)
    return tickers


def load_vietnam_tickers(use_cache: bool = True) -> list[str]:
    """Load Vietnam (HOSE + HNX) tickers from DB, with .VN suffix for yfinance."""
    if use_cache and _VN_CACHE.exists():
        age = time.time() - _VN_CACHE.stat().st_mtime
        if age < _CACHE_TTL_SECS:
            with open(_VN_CACHE) as f:
                cached = json.load(f)
            logger.info("Vietnam tickers from cache: %d (age %.1fh)", len(cached), age / 3600)
            return cached

    # Primary source: DB ticker_universe
    tickers = []
    try:
        from scripts.lib.db_helpers import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT yf_symbol FROM datapai.ticker_universe "
                    "WHERE exchange = 'HOSE' AND is_active = TRUE ORDER BY ticker"
                )
                tickers = [r[0] for r in cur.fetchall()]
        logger.info("Vietnam tickers from DB: %d", len(tickers))
    except Exception as e:
        logger.warning("Failed to load Vietnam tickers from DB: %s", e)

    if not tickers:
        logger.warning("No Vietnam tickers found — using empty list")
        return []

    # Cache for next time
    _VN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(_VN_CACHE, "w") as f:
        json.dump(tickers, f)

    return tickers


def load_monitored_tickers(exchange: str | None = None) -> list[str]:
    """
    Return monitored universe tickers from env var or DB.

    Sources (merged, deduplicated):
      1. MONITORED_TICKERS env var (if set)
      2. datapai.fundamental_lite — all stocks with fundamental data
      3. datapai.ta_signals — recent signal tickers (legacy)

    This ensures ALL stocks with fundamental data get TA indicators computed,
    enabling proper multi-agent consensus (FA + TA + Macro).
    """
    env_val = os.getenv("MONITORED_TICKERS", "")
    if env_val.strip():
        tickers = [t.strip().upper() for t in env_val.split(",") if t.strip()]
        logger.info("Monitored tickers from env: %d", len(tickers))
        return tickers

    tickers_set: set[str] = set()

    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from agents.stock_chat.db import query as db_query

        # Source 1: fundamental_lite — all FA-screened stocks (primary source)
        sql_fund = "SELECT DISTINCT ticker FROM datapai.fundamental_lite"
        params_fund: list = []
        if exchange:
            sql_fund += " WHERE exchange = %s"
            params_fund.append(exchange)
        rows = db_query(sql_fund, params_fund or None)
        fund_tickers = {r["ticker"] for r in rows}
        tickers_set.update(fund_tickers)
        logger.info("Monitored tickers from fundamental_lite: %d", len(fund_tickers))

        # Source 2: ta_signals — recent signals (supplements fundamental_lite)
        sql_sig = (
            "SELECT DISTINCT ticker FROM datapai.ta_signals "
            "WHERE generated_at::timestamptz > NOW() - INTERVAL '14 days'"
        )
        params_sig: list = []
        if exchange:
            sql_sig += " AND exchange = %s"
            params_sig.append(exchange)
        sql_sig += " LIMIT 500"
        rows = db_query(sql_sig, params_sig or None)
        sig_tickers = {r["ticker"] for r in rows}
        tickers_set.update(sig_tickers)
        if sig_tickers - fund_tickers:
            logger.info("Additional tickers from ta_signals: %d", len(sig_tickers - fund_tickers))

    except Exception as e:
        logger.warning("Could not load monitored tickers from DB: %s — using empty list", e)

    tickers = sorted(tickers_set)

    # prices table stores tickers with exchange suffix but fundamental_lite doesn't
    from core.config.exchange_registry import registry
    suffix = registry.get_suffix(exchange)
    if suffix:
        tickers = [t if t.endswith(suffix) else f"{t}{suffix}" for t in tickers]

    logger.info("Total monitored tickers for %s: %d", exchange or "ALL", len(tickers))
    return tickers


def _asx_fallback_tickers() -> list[str]:
    """Top ~600 ASX tickers by market cap (hardcoded fallback when all live sources fail)."""
    top_asx = [
        # ── Top 50 (ASX 50 index) ────────────────────────────────────────────
        "BHP", "CBA", "CSL", "NAB", "WBC", "ANZ", "WES", "MQG", "RIO",
        "TLS", "FMG", "WDS", "TCL", "STO", "ALL", "REA", "GMG", "COL",
        "WOW", "QBE", "IAG", "BXB", "SHL", "MIN", "JHX", "ASX", "TWE",
        "NST", "ORI", "GPT", "CHC", "SCG", "MGR", "CPU", "DXS", "EBO",
        "EVN", "FLT", "IGO", "ILU", "IPL", "JBH", "LYC", "MPL", "NHF",
        "ORG", "PPT", "RHC", "RMD", "S32", "SEK", "SGM", "SGP", "SUN",
        "TAH", "TPG", "XRO", "AZJ", "BOQ",
        # ── ASX 100 ──────────────────────────────────────────────────────────
        "AGL", "ALD", "ALQ", "ALU", "AMC", "ANN", "APA", "APE", "ARB",
        "AST", "BAP", "BKW", "BLD", "BSL", "CAR", "CCP", "CGF", "CIA",
        "CLW", "CMW", "CNI", "CQE", "CTD", "CWY", "DOW", "EQT", "GNC",
        "GOR", "GWA", "HVN", "IVC", "JHG", "KGN", "LNW", "MGX", "MMS",
        "MTO", "MYR", "NUF", "NXT", "ORA", "PDL", "PNI", "PRG", "PRY",
        "QAN", "REH", "RRL", "SAR", "SKI", "SOL", "SPK", "SSR", "SVW",
        "VEA", "WPR", "AIA",
        # ── ASX 200 ──────────────────────────────────────────────────────────
        "360", "ABB", "ABY", "ACL", "ACQ", "ADA", "ADD", "ADH", "ADI",
        "AEF", "AEL", "AEV", "AFG", "AFI", "AGE", "AGH", "AGI", "AGY",
        "AHY", "AIM", "AIZ", "AKE", "ALC", "ALI", "ALP", "ALX", "AMI",
        "AMP", "AMT", "ANA", "ANL", "AOF", "APA", "APD", "APM", "AQZ",
        "ARF", "ARI", "ARX", "ASB", "ASD", "ASG", "ATM", "ATR", "AUB",
        "AUI", "AUQ", "AVH", "AVJ", "AWC", "AWF", "AX1", "AZS", "BAL",
        "BBN", "BCI", "BCK", "BGA", "BGP", "BIN", "BKG", "BKI", "BKT",
        "BLX", "BMN", "BNO", "BPT", "BRL", "BRN", "BSX", "BTH", "BWP",
        "BXB", "CAB", "CAJ", "CAN", "CAT", "CBL", "CCX", "CDX", "CEH",
        "CEN", "CIP", "CKF", "CLH", "CLQ", "CLS", "CMM", "CMP", "CNB",
        "CNQ", "COE", "COH", "CQR", "CRN", "CSF", "CTI", "CTN", "CUV",
        "CVN", "CWP", "CXL", "CXO", "CY5",
        # ── ASX 300 extension ─────────────────────────────────────────────────
        "DBI", "DCG", "DCN", "DDR", "DEG", "DEL", "DHG", "DMP", "DOC",
        "DRO", "DSH", "DTC", "DTL", "DUB", "DUR", "DXC", "DYL", "EAR",
        "EBR", "ECF", "ECX", "EDV", "EFT", "EGL", "EHE", "ELD", "ELO",
        "EML", "EMR", "EMV", "EMX", "ENR", "ENV", "EOL", "EPD", "EPW",
        "ERA", "ERM", "ERX", "ESS", "EVO", "EWC", "EXL", "EXP", "EXR",
        "FAR", "FCT", "FDV", "FGG", "FGX", "FHS", "FID", "FIG", "FIN",
        "FLC", "FLN", "FMG", "FNP", "FOR", "FPH", "FRI", "FSA", "FUN",
        "FWD", "GBT", "GDG", "GEM", "GFF", "GFY", "GGG", "GGL", "GID",
        "GIL", "GLA", "GLB", "GLD", "GLL", "GLN", "GLY", "GMA", "GMV",
        "GNX", "GOW", "GPM", "GRL", "GRR", "GS1", "GSS", "GUD",
        # ── Mid/small cap ────────────────────────────────────────────────────
        "HAV", "HCW", "HDN", "HLS", "HMC", "HNR", "HOT", "HPI", "HRL",
        "HUB", "HUM", "HVT", "IAP", "ICQ", "IDX", "IEL", "IFM", "IMD",
        "INA", "ING", "INP", "INR", "INT", "IOU", "IPD", "IPG", "IRI",
        "IRX", "ISU", "ITD", "ITL", "IVX", "IXR", "JAN", "JDO", "JHC",
        "JIN", "JMS", "JNO", "JRV", "KAR", "KBL", "KCN", "KGL", "KII",
        "KMD", "KMT", "KNB", "KPG", "KSL", "LBL", "LBT", "LCM", "LEP",
        "LFG", "LGI", "LIN", "LIT", "LME", "LNK", "LOM", "LOV", "LPD",
        "LPI", "LRS", "LSF", "LTR", "LVT", "MAH", "MBH", "MBK", "MCR",
        "MDC", "MDR", "MDX", "MEI", "MFD", "MGH", "MHC", "MLD", "MLX",
        "MMI", "MND", "MNF", "MNW", "MOE", "MQA", "MRR", "MSB", "MTR",
        "MTS", "MVF", "MVP", "MWY", "MYQ",
        # ── Resources / Mining ───────────────────────────────────────────────
        "NCZ", "NDO", "NEA", "NEC", "NEU", "NIC", "NML", "NMS", "NNL",
        "NOX", "NRZ", "NTC", "NTD", "NTI", "NWS", "NXD", "NXM", "OBM",
        "OCL", "OEL", "OFX", "OGC", "OKR", "OLL", "OML", "ONT", "OPY",
        "OPZ", "ORC", "OSH", "OTW", "OZL", "PAB", "PAC", "PAR", "PBH",
        "PBP", "PEK", "PEN", "PGH", "PGL", "PHI", "PLL", "PLY", "PME",
        "PNR", "POI", "PPC", "PPG", "PPH", "PPM", "PRO", "PRU", "PSQ",
        "PTB", "PTM", "PUA", "PVS", "PWH", "PXA", "PYC",
        # ── Financials / Property ─────────────────────────────────────────────
        "QAN", "QAU", "QHL", "QIP", "QMS", "QRI", "QUB", "RAP", "RBL",
        "RCE", "RCR", "RDC", "RDY", "REG", "RFG", "RGI", "RHL", "RHT",
        "RIC", "RIO", "RKN", "RMC", "RMS", "RND", "ROG", "ROO", "RPL",
        "RRS", "RSG", "RTR", "RUL", "RVS", "RWC", "RXH", "SBM", "SCP",
        "SDG", "SDF", "SDI", "SDV", "SEH", "SEK", "SEN", "SFR", "SGF",
        "SHJ", "SHL", "SIL", "SIM", "SIS", "SIV", "SIX", "SLR", "SLX",
        "SML", "SMR", "SNL", "SOI", "SPL", "SRG", "SRV", "SSL", "STA",
        "STB", "STX", "SUL", "SWM", "SXE", "SXL", "SYR",
        # ── Tech / Healthcare ─────────────────────────────────────────────────
        "TBN", "TCG", "TCI", "TDO", "TER", "TFC", "TGA", "TGP", "TGS",
        "THL", "TIE", "TIG", "TIX", "TKL", "TLC", "TLX", "TML", "TNE",
        "TOE", "TPC", "TPM", "TRS", "TSI", "TSL", "TTM", "TUA", "TUL",
        "TUN", "TUR", "TVN", "TWD", "TXN", "UBI", "UCM", "UMG", "UNI",
        "UWL", "VAH", "VCX", "VEG", "VGL", "VHT", "VIV", "VLW", "VMY",
        "VNT", "VOC", "VPR", "VRX", "VSC", "VTI", "VUK", "VVR", "VYS",
        "WAA", "WAF", "WAM", "WAR", "WAT", "WBT", "WCB", "WEB", "WFD",
        "WGX", "WHC", "WLD", "WLL", "WLS", "WNR", "WOR", "WPL", "WRK",
        "WSA", "WTC", "WWG", "WZR", "XF1", "XPD", "XRF", "YAL", "Z1P",
        "ZGL", "ZIP", "ZNO", "ZPT", "ZQT",
    ]
    return [f"{t}.AX" for t in top_asx]
