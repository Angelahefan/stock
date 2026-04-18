#!/usr/bin/env python3
"""Quick backfill of stock_fundamentals for demo stocks only. Throttled to avoid Yahoo rate limits."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yfinance as yf
from scripts.lib.db_helpers import get_conn
from scripts.lib.log_setup import setup_logging

logger = setup_logging("backfill_demo_fundamentals")


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT d.ticker, d.exchange, COALESCE(tu.yf_symbol, d.ticker) as yf_symbol
                FROM datapai.market_demo_stocks d
                LEFT JOIN datapai.ticker_universe tu ON tu.ticker = d.ticker AND tu.exchange = d.exchange
                LEFT JOIN datapai.stock_fundamentals sf ON sf.ticker = d.ticker AND sf.exchange = d.exchange
                WHERE sf.ticker IS NULL
                ORDER BY d.exchange
            """)
            missing = cur.fetchall()

    logger.info("Missing fundamentals for %d demo stocks", len(missing))

    for ticker, exchange, yf_sym in missing:
        try:
            t = yf.Ticker(yf_sym)
            info = t.info or {}
            if not info.get("marketCap"):
                logger.warning("  SKIP %s (%s) — no data", ticker, yf_sym)
                continue

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO datapai.stock_fundamentals
                          (ticker, exchange, sector, industry, currency, market_cap, pe_ttm, pe_forward,
                           pb_ratio, ps_ratio, beta, dividend_yield, dividend_rate,
                           fifty_two_week_high, fifty_two_week_low, shares_outstanding, float_shares,
                           profit_margin, operating_margin, return_on_equity, return_on_assets,
                           revenue_ttm, net_income_ttm, earnings_growth, revenue_growth,
                           total_cash, total_debt, debt_to_equity, current_ratio, updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT (ticker, exchange) DO UPDATE SET
                          sector=EXCLUDED.sector, industry=EXCLUDED.industry, market_cap=EXCLUDED.market_cap,
                          pe_ttm=EXCLUDED.pe_ttm, pe_forward=EXCLUDED.pe_forward, pb_ratio=EXCLUDED.pb_ratio,
                          beta=EXCLUDED.beta, dividend_yield=EXCLUDED.dividend_yield,
                          fifty_two_week_high=EXCLUDED.fifty_two_week_high, fifty_two_week_low=EXCLUDED.fifty_two_week_low,
                          profit_margin=EXCLUDED.profit_margin, return_on_equity=EXCLUDED.return_on_equity,
                          revenue_growth=EXCLUDED.revenue_growth, earnings_growth=EXCLUDED.earnings_growth,
                          updated_at=NOW()
                    """, (
                        ticker, exchange,
                        info.get("sector"), info.get("industry"), info.get("currency"),
                        info.get("marketCap"), info.get("trailingPE"), info.get("forwardPE"),
                        info.get("priceToBook"), info.get("priceToSalesTrailing12Months"),
                        info.get("beta"), info.get("dividendYield"), info.get("dividendRate"),
                        info.get("fiftyTwoWeekHigh"), info.get("fiftyTwoWeekLow"),
                        info.get("sharesOutstanding"), info.get("floatShares"),
                        info.get("profitMargins"), info.get("operatingMargins"),
                        info.get("returnOnEquity"), info.get("returnOnAssets"),
                        info.get("totalRevenue"), info.get("netIncomeToCommon"),
                        info.get("earningsGrowth"), info.get("revenueGrowth"),
                        info.get("totalCash"), info.get("totalDebt"),
                        info.get("debtToEquity"), info.get("currentRatio"),
                    ))

            sector = info.get("sector", "?")
            mcap = info.get("marketCap", 0)
            logger.info("  OK %s (%s) — %s, mcap=%s", ticker, exchange, sector, mcap)
        except Exception as e:
            logger.warning("  ERR %s: %s", ticker, e)
        time.sleep(2)

    logger.info("Done!")


if __name__ == "__main__":
    main()
