#!/usr/bin/env python3
"""
compute_portfolio_snapshots.py
─────────────────────────────────────────────────────────────────────────────
Daily job: for each user with holdings, compute current portfolio value,
daily P&L, total P&L, and benchmark comparison (S&P 500).

Store daily snapshots for equity curve charting.

Usage:
    python scripts/compute_portfolio_snapshots.py
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date

import psycopg2
from psycopg2.extras import execute_values, RealDictCursor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from lib.log_setup import setup_logging

logger = setup_logging("compute_portfolio_snapshots")

BENCHMARK_TICKER = "^GSPC"


def get_conn():
    from scripts.lib.db_helpers import get_conn as _get_conn
    return _get_conn()


def fetch_users_with_holdings(conn) -> list[str]:
    """Get distinct user_ids that have holdings."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT user_id FROM datapai.usr_holdings")
        return [r[0] for r in cur.fetchall()]


def fetch_user_holdings(conn, user_id: str) -> list[dict]:
    """Get all holdings for a user."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT ticker, exchange, shares, avg_cost FROM datapai.usr_holdings WHERE user_id = %s",
            [user_id],
        )
        return [dict(r) for r in cur.fetchall()]


def get_latest_price(conn, ticker: str, exchange: str) -> float | None:
    """Get the most recent close price for a ticker."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT close FROM datapai.prices
               WHERE ticker = %s AND exchange = %s AND close IS NOT NULL
               ORDER BY trade_date DESC LIMIT 1""",
            [ticker, exchange],
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_previous_portfolio_value(conn, user_id: str) -> float | None:
    """Get the most recent portfolio snapshot value (for daily P&L)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT total_value FROM datapai.usr_portfolio_snapshots
               WHERE user_id = %s
               ORDER BY snapshot_date DESC LIMIT 1""",
            [user_id],
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_benchmark_return_since(conn, since_date: date) -> float | None:
    """Compute S&P 500 return since a given date."""
    with conn.cursor() as cur:
        # Get price at start
        cur.execute(
            """SELECT close FROM datapai.prices
               WHERE ticker = %s AND close IS NOT NULL AND trade_date >= %s
               ORDER BY trade_date LIMIT 1""",
            [BENCHMARK_TICKER, str(since_date)],
        )
        row = cur.fetchone()
        if not row:
            return None
        start_price = row[0]

        # Get latest price
        cur.execute(
            """SELECT close FROM datapai.prices
               WHERE ticker = %s AND close IS NOT NULL
               ORDER BY trade_date DESC LIMIT 1""",
            [BENCHMARK_TICKER],
        )
        row = cur.fetchone()
        if not row or start_price == 0:
            return None
        end_price = row[0]

        return (end_price - start_price) / start_price * 100.0


def main():
    conn = get_conn()
    today = date.today()

    try:
        users = fetch_users_with_holdings(conn)
        logger.info("Found %d users with holdings", len(users))

        snapshots = []
        for user_id in users:
            holdings = fetch_user_holdings(conn, user_id)
            if not holdings:
                continue

            total_value = 0.0
            total_cost = 0.0
            earliest_add = today

            for h in holdings:
                current_price = get_latest_price(conn, h["ticker"], h["exchange"])
                if current_price is not None:
                    total_value += float(h["shares"]) * current_price
                else:
                    # Fallback: use avg_cost
                    total_value += float(h["shares"]) * float(h["avg_cost"])
                total_cost += float(h["shares"]) * float(h["avg_cost"])

            total_pnl = total_value - total_cost
            total_pnl_pct = (total_pnl / total_cost * 100.0) if total_cost > 0 else 0.0

            prev_value = get_previous_portfolio_value(conn, user_id)
            daily_pnl = (total_value - prev_value) if prev_value is not None else 0.0

            # Benchmark return since earliest holding date
            # (simplified: use 90 days ago as proxy)
            from datetime import timedelta
            benchmark_start = today - timedelta(days=90)
            benchmark_return = get_benchmark_return_since(conn, benchmark_start) or 0.0

            snapshots.append((
                user_id, today, total_value, total_cost,
                daily_pnl, total_pnl, round(total_pnl_pct, 2),
                round(benchmark_return, 2),
            ))

        if snapshots:
            sql = """
                INSERT INTO datapai.usr_portfolio_snapshots
                    (user_id, snapshot_date, total_value, total_cost,
                     daily_pnl, total_pnl, total_pnl_pct, benchmark_return)
                VALUES %s
                ON CONFLICT (user_id, snapshot_date) DO UPDATE SET
                    total_value    = EXCLUDED.total_value,
                    total_cost     = EXCLUDED.total_cost,
                    daily_pnl      = EXCLUDED.daily_pnl,
                    total_pnl      = EXCLUDED.total_pnl,
                    total_pnl_pct  = EXCLUDED.total_pnl_pct,
                    benchmark_return = EXCLUDED.benchmark_return,
                    created_at     = NOW()
            """
            with conn.cursor() as cur:
                execute_values(cur, sql, snapshots)
            conn.commit()
            logger.info("Upserted %d portfolio snapshots", len(snapshots))
        else:
            logger.info("No portfolio snapshots to compute")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
