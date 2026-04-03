"""
agents/fundamental/fetcher.py
==============================
Fetches and normalises fundamental data for a stock ticker using yfinance.

Public API
----------
fetch_fundamentals(ticker, exchange) -> dict
    Returns a flat dict of fundamental fields + historical financials.
    Never raises — returns partial data with errors list on failure.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# yfinance ticker suffix by exchange
_EXCHANGE_SUFFIX: dict[str, str] = {
    "US":  "",
    "ASX": ".AX",
}


def _safe(info: dict, key: str, default=None):
    """Return info[key] if it's a real value (not None/nan/0 for ratios)."""
    v = info.get(key)
    if v is None:
        return default
    # yfinance sometimes returns 'Infinity' or very large sentinel values
    try:
        fv = float(v)
        if fv != fv:   # NaN check
            return default
        return v
    except (TypeError, ValueError):
        return default


def _pct(info: dict, key: str) -> Optional[float]:
    """Return a yfinance ratio field as a proper decimal (already in 0–1 form)."""
    v = _safe(info, key)
    if v is None:
        return None
    return float(v)


def _billions(info: dict, key: str) -> Optional[int]:
    """Return large integer field (market cap, cash, etc.) as int."""
    v = _safe(info, key)
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _parse_history(ticker_obj) -> List[dict]:
    """
    Extract annual and quarterly financials from yfinance ticker object.
    Returns list of period dicts for fundamental_history table.
    """
    periods: list[dict] = []

    def _extract(df, period_type: str):
        if df is None or df.empty:
            return
        for col in df.columns:
            # col is a Timestamp
            try:
                period_end = col.date() if hasattr(col, "date") else date.fromisoformat(str(col)[:10])
            except Exception:
                continue

            def _get(row_label: str) -> Optional[int]:
                try:
                    v = df.loc[row_label, col]
                    if v is None or (hasattr(v, "__float__") and float(v) != float(v)):
                        return None
                    return int(float(v))
                except (KeyError, TypeError, ValueError):
                    return None

            def _get_float(row_label: str) -> Optional[float]:
                try:
                    v = df.loc[row_label, col]
                    if v is None or (hasattr(v, "__float__") and float(v) != float(v)):
                        return None
                    return float(v)
                except (KeyError, TypeError, ValueError):
                    return None

            # Try multiple label variants for cross-version yfinance compat
            revenue      = _get("Total Revenue") or _get("Revenue")
            gross_profit = _get("Gross Profit")
            op_income    = _get("Operating Income") or _get("EBIT")
            net_income   = _get("Net Income")
            ebitda       = _get("EBITDA") or _get("Normalized EBITDA")
            eps          = _get_float("Diluted EPS") or _get_float("Basic EPS")
            fcf          = _get("Free Cash Flow")
            op_cf        = _get("Operating Cash Flow")
            capex        = _get("Capital Expenditure")
            total_assets = _get("Total Assets")
            total_debt   = _get("Total Debt") or _get("Long Term Debt")
            equity       = _get("Stockholders Equity") or _get("Total Equity Gross Minority Interest")
            cash         = _get("Cash And Cash Equivalents") or _get("Cash Cash Equivalents And Short Term Investments")

            periods.append({
                "period_end":            period_end,
                "period_type":           period_type,
                "revenue":               revenue,
                "gross_profit":          gross_profit,
                "operating_income":      op_income,
                "net_income":            net_income,
                "ebitda":                ebitda,
                "eps":                   eps,
                "free_cash_flow":        fcf,
                "operating_cash_flow":   op_cf,
                "capex":                 capex,
                "total_assets":          total_assets,
                "total_debt":            total_debt,
                "shareholders_equity":   equity,
                "cash_and_equivalents":  cash,
            })

    try:
        _extract(ticker_obj.income_stmt, "annual")
    except Exception as exc:
        log.debug("annual income_stmt error: %s", exc)
    try:
        _extract(ticker_obj.quarterly_income_stmt, "quarterly")
    except Exception as exc:
        log.debug("quarterly income_stmt error: %s", exc)

    # Compute YoY growth within each period_type
    for pt in ("annual", "quarterly"):
        subset = sorted([p for p in periods if p["period_type"] == pt],
                        key=lambda x: x["period_end"])
        for i, p in enumerate(subset):
            prev = subset[i - 1] if i > 0 else None
            p["revenue_yoy"] = _yoy(p.get("revenue"), prev.get("revenue") if prev else None)
            p["earnings_yoy"] = _yoy(p.get("net_income"), prev.get("net_income") if prev else None)
            p["fcf_yoy"] = _yoy(p.get("free_cash_flow"), prev.get("free_cash_flow") if prev else None)

    return periods


def _yoy(current: Optional[int], prior: Optional[int]) -> Optional[float]:
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior)


def fetch_fundamentals(ticker: str, exchange: str) -> dict:
    """
    Fetch fundamental data for ticker/exchange from yfinance.

    Returns dict with keys:
      - All snapshot fields (flat)
      - 'history': list of period dicts for fundamental_history
      - 'errors': list of error strings encountered
      - 'warnings': list of non-fatal issues
    """
    import yfinance as yf

    errors: list[str] = []
    warnings: list[str] = []

    suffix = _EXCHANGE_SUFFIX.get(exchange.upper(), "")
    yf_symbol = f"{ticker.upper()}{suffix}"

    result: dict[str, Any] = {
        "ticker": ticker.upper(),
        "exchange": exchange.upper(),
        "source": "yfinance",
        "computed_at": datetime.utcnow(),
        "history": [],
        "errors": errors,
        "warnings": warnings,
    }

    try:
        yf_ticker = yf.Ticker(yf_symbol)
        info = yf_ticker.info or {}
    except Exception as exc:
        errors.append(f"yfinance fetch failed: {exc}")
        return result

    if not info or info.get("trailingPE") is None and info.get("regularMarketPrice") is None:
        warnings.append(f"yfinance returned sparse data for {yf_symbol} — ticker may be delisted or incorrect")

    # ── Identity ──────────────────────────────────────────────────────────────
    result["company_name"]   = info.get("longName") or info.get("shortName")
    result["sector"]         = info.get("sector")
    result["industry"]       = info.get("industry") or info.get("industryDisp")
    result["currency"]       = info.get("currency")

    # ── Size ──────────────────────────────────────────────────────────────────
    result["market_cap"]         = _billions(info, "marketCap")
    result["enterprise_value"]   = _billions(info, "enterpriseValue")

    # ── Valuation ─────────────────────────────────────────────────────────────
    result["pe_ratio"]    = _safe(info, "trailingPE")
    result["forward_pe"]  = _safe(info, "forwardPE")
    result["peg_ratio"]   = _safe(info, "pegRatio") or _safe(info, "trailingPegRatio")
    result["pb_ratio"]    = _safe(info, "priceToBook")
    result["ps_ratio"]    = _safe(info, "priceToSalesTrailing12Months")
    result["ev_ebitda"]   = _safe(info, "enterpriseToEbitda")
    result["ev_revenue"]  = _safe(info, "enterpriseToRevenue")

    # ── Profitability ─────────────────────────────────────────────────────────
    result["gross_margin"]     = _pct(info, "grossMargins")
    result["operating_margin"] = _pct(info, "operatingMargins")
    result["net_margin"]       = _pct(info, "profitMargins")
    result["roe"]              = _pct(info, "returnOnEquity")
    result["roa"]              = _pct(info, "returnOnAssets")
    # ROIC not directly in yfinance — approximate as net_income / (total_debt + equity)
    result["roic"]             = None   # computed in quality_agent if needed

    # ── Growth ────────────────────────────────────────────────────────────────
    result["revenue_yoy"]       = _pct(info, "revenueGrowth")
    result["earnings_yoy"]      = _pct(info, "earningsGrowth")
    result["revenue_growth_5yr"] = None   # yfinance doesn't expose 5yr directly
    result["eps_growth_5yr"]    = None

    # ── Financial Health ──────────────────────────────────────────────────────
    result["current_ratio"]    = _safe(info, "currentRatio")
    result["quick_ratio"]      = _safe(info, "quickRatio")
    result["debt_to_equity"]   = _safe(info, "debtToEquity")
    # Interest coverage = EBIT / interest expense — not directly in info, skip
    result["interest_coverage"] = None
    result["total_cash"]       = _billions(info, "totalCash")
    result["total_debt"]       = _billions(info, "totalDebt")
    tc = result["total_cash"] or 0
    td = result["total_debt"] or 0
    result["net_cash"]         = tc - td if (tc or td) else None

    # ── Cash Flow ─────────────────────────────────────────────────────────────
    result["free_cash_flow"]     = _billions(info, "freeCashflow")
    result["fcf_per_share"]      = _safe(info, "freeCashflow") and (
        float(info.get("freeCashflow", 0)) / float(info.get("sharesOutstanding", 1) or 1)
        if info.get("sharesOutstanding") else None
    )
    # FCF yield = FCF / market cap
    if result["free_cash_flow"] and result["market_cap"] and result["market_cap"] > 0:
        result["fcf_yield"] = result["free_cash_flow"] / result["market_cap"]
    else:
        result["fcf_yield"] = None
    result["operating_cf_margin"] = _safe(info, "operatingCashflow") and (
        float(info.get("operatingCashflow", 0)) / float(info.get("totalRevenue", 1) or 1)
        if info.get("totalRevenue") else None
    )

    # ── Dividend ──────────────────────────────────────────────────────────────
    result["dividend_yield"]  = _pct(info, "dividendYield") or _pct(info, "trailingAnnualDividendYield")
    result["payout_ratio"]    = _pct(info, "payoutRatio")

    # ── Market / Risk ─────────────────────────────────────────────────────────
    result["beta"]        = _safe(info, "beta")
    result["short_ratio"] = _safe(info, "shortRatio")
    erd = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
    if erd:
        try:
            result["next_earnings_date"] = datetime.utcfromtimestamp(erd).date()
        except Exception:
            result["next_earnings_date"] = None
    else:
        result["next_earnings_date"] = None

    # ── Historical financials ─────────────────────────────────────────────────
    try:
        result["history"] = _parse_history(yf_ticker)
    except Exception as exc:
        warnings.append(f"Could not parse historical financials: {exc}")
        result["history"] = []

    return result
