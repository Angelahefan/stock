# ═══════════════════════════════════════════════════════════════════════════════
# stock_chat/rag_retriever.py  —  LanceDB retrieval for TinyFish scan history
#
# Uses the EXISTING LanceDB S3 infrastructure (s3://codepais3/lancedb_data/)
# Adds a NEW collection: 'tinyfish_scans' — does NOT touch existing collections
# (documents, pdfs, images, asx_announcements).
#
# Also uses datapai.ticker_context_cache (postgres) as a fast pre-computed
# context layer for the most recent scan data — avoids LanceDB cold starts.
# ═══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_LANCEDB_URI = os.getenv("LANCEDB_URI", "s3://codepais3/lancedb_data/")
_TOP_K       = int(os.getenv("SC_RAG_TOP_K", "4"))


def _get_db():
    """Connect to LanceDB (lazy import to avoid startup cost)."""
    try:
        import lancedb
        return lancedb.connect(_LANCEDB_URI)
    except Exception as e:
        logger.warning("LanceDB connect failed: %s", e)
        return None


def retrieve_scan_context(ticker: str, query: str, top_k: int = _TOP_K) -> list[dict]:
    """
    Search the tinyfish_scans LanceDB collection for relevant scan history.
    Returns list of {text, score, metadata} dicts.
    Falls back to empty list if LanceDB is unavailable.
    """
    db = _get_db()
    if db is None:
        return []

    try:
        table_names = db.table_names()
    except Exception as e:
        logger.warning("LanceDB table_names failed: %s", e)
        return []

    if "tinyfish_scans" not in table_names:
        logger.info("tinyfish_scans collection not yet indexed — no RAG context")
        return []

    try:
        from embeddings.embed import embed_texts  # existing embedding module
        q_vec = embed_texts([f"{ticker} {query}"])[0]
        tbl   = db.open_table("tinyfish_scans")
        rows  = (
            tbl.search(q_vec)
               .where(f"ticker = '{ticker.upper()}'")
               .limit(top_k)
               .to_list()
        )
        return [
            {
                "text":     r.get("text", ""),
                "score":    r.get("_distance", 0),
                "metadata": {k: v for k, v in r.items() if k not in ("text", "_distance", "vector")},
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("LanceDB search failed for %s: %s", ticker, e)
        return []


def ingest_scan_snapshot(
    ticker: str,
    exchange: str,
    scan_text: str,
    scan_date: str,
    signal_summary: Optional[str] = None,
    change_type: Optional[str] = None,
) -> bool:
    """
    Index a TinyFish scan snapshot into the tinyfish_scans LanceDB collection.
    Called by the scan pipeline after each successful IR page fetch.
    Returns True on success, False on failure (non-fatal).
    """
    db = _get_db()
    if db is None:
        return False

    try:
        from embeddings.embed import embed_texts
        combined_text = f"[{ticker} {exchange} {scan_date}]\n{scan_text}"
        if signal_summary:
            combined_text += f"\n\nSignal summary: {signal_summary}"
        vec = embed_texts([combined_text])[0]

        record = {
            "ticker":         ticker.upper(),
            "exchange":       exchange.upper(),
            "scan_date":      scan_date,
            "change_type":    change_type or "UNKNOWN",
            "text":           combined_text,
            "vector":         vec,
        }

        table_names = db.table_names()
        if "tinyfish_scans" not in table_names:
            import pyarrow as pa
            schema = pa.schema([
                pa.field("ticker",      pa.string()),
                pa.field("exchange",    pa.string()),
                pa.field("scan_date",   pa.string()),
                pa.field("change_type", pa.string()),
                pa.field("text",        pa.string()),
                pa.field("vector",      pa.list_(pa.float32(), len(vec))),
            ])
            db.create_table("tinyfish_scans", data=[record], schema=schema)
            logger.info("Created tinyfish_scans LanceDB collection")
        else:
            tbl = db.open_table("tinyfish_scans")
            tbl.add([record])

        return True
    except Exception as e:
        logger.warning("LanceDB ingest failed for %s: %s", ticker, e)
        return False


def get_postgres_context(ticker: str) -> str:
    """
    Fast path: return IR scan context from datapai.ticker_context_cache.
    Excludes ta_signal entries (those are fetched separately via get_ta_signal_context).
    Populated by the TinyFish scan pipeline.
    """
    try:
        from .db import query
        rows = query(
            """
            SELECT content FROM datapai.ticker_context_cache
            WHERE ticker = %s
              AND context_type <> 'ta_signal'
              AND (expires_at IS NULL OR expires_at > now())
            ORDER BY created_at DESC LIMIT 3
            """,
            (ticker.upper(),),
        )
        return "\n\n".join(r["content"] for r in rows) if rows else ""
    except Exception as e:
        logger.warning("ticker_context_cache read failed for %s: %s", ticker, e)
        return ""


def get_ta_signal_context(ticker: str) -> str:
    """
    Fetch the latest TA signal context for injection into the chat system prompt.

    Priority:
      1. datapai.ticker_context_cache (context_type='ta_signal', 8h TTL)
         → Written by Python TA endpoint; contains explicit "Today's Open/High/Low/Close" labels.
      2. datapai.ta_signals (no expiry check — always falls back here)
         → Written by Next.js after calling the Python TA endpoint; structured fields.
         → Reconstructed with explicit OHLC labels so the LLM can cite them directly.

    This dual-fallback means the chatbot always has TA data if the user has ever
    generated a signal for this ticker — even if the 8h ticker_context_cache has expired
    but the 48h ta_signals entry (used by the intel page) is still valid.
    """
    t = ticker.upper()

    # ── Priority 1: ticker_context_cache (fresh, explicit OHLC labels) ────────
    try:
        from .db import query
        rows = query(
            """
            SELECT content FROM datapai.ticker_context_cache
            WHERE ticker = %s
              AND context_type = 'ta_signal'
              AND (expires_at IS NULL OR expires_at > now())
            ORDER BY created_at DESC LIMIT 1
            """,
            (t,),
        )
        if rows and rows[0]["content"]:
            return rows[0]["content"]
    except Exception as e:
        logger.warning("ticker_context_cache read failed for %s: %s", t, e)

    # ── Priority 2: ta_signals table (written by Next.js, no expiry check) ────
    # indicators_json contains the full per-timeframe OHLCV data including
    # open/high/low for the daily (1d) bar — parse it to reconstruct explicit labels.
    try:
        import json as _json
        from .db import query as q2
        rows2 = q2(
            """
            SELECT ticker, exchange, signal_md, current_price, change_pct,
                   rsi, rsi_label, trend, macd_label, bb_label,
                   indicators_json, generated_at
            FROM datapai.ta_signals
            WHERE ticker = %s
            ORDER BY generated_at DESC LIMIT 1
            """,
            (t,),
        )
        if rows2:
            r = rows2[0]
            lines = [f"[TA Signal — {r['ticker']} | {r.get('exchange', 'US')}]"]
            if r.get("generated_at"):
                lines.append(f"Generated: {str(r['generated_at'])[:16]}")

            # Extract daily OHLC from indicators_json (stored by Next.js)
            daily = {}
            try:
                if r.get("indicators_json"):
                    inds = _json.loads(r["indicators_json"])
                    daily = inds.get("1d") or inds.get("daily") or {}
            except Exception:
                pass

            # Prefer daily OHLC from indicators_json; fall back to top-level columns
            open_p      = daily.get("open")
            high_p      = daily.get("high")
            low_p       = daily.get("low")
            close_p     = daily.get("current_price") or r.get("current_price")
            prev_close  = daily.get("prev_close")
            chg_pct     = daily.get("change_pct") or r.get("change_pct")

            if open_p  is not None: lines.append(f"Today's Open:  {open_p:.4f}")
            if high_p  is not None: lines.append(f"Today's High:  {high_p:.4f}")
            if low_p   is not None: lines.append(f"Today's Low:   {low_p:.4f}")
            if close_p is not None:
                close_line = f"Today's Close: {close_p:.4f}"
                if chg_pct is not None:
                    close_line += f"  ({chg_pct:+.2f}% vs prev close)"
                lines.append(close_line)
            if prev_close is not None: lines.append(f"Prev Close:    {prev_close:.4f}")

            if r.get("rsi")      is not None: lines.append(f"RSI(14):  {r['rsi']:.1f} ({r.get('rsi_label', '')})")
            if r.get("trend"):                lines.append(f"Trend:    {r['trend']}")
            if r.get("macd_label"):           lines.append(f"MACD:     {r['macd_label']}")
            if r.get("bb_label"):             lines.append(f"Bollinger:{r['bb_label']}")
            if r.get("signal_md"):
                lines.append("")
                lines.append(r["signal_md"][:1500])

            logger.info("ta_signal: fell back to ta_signals+indicators_json for %s (OHLC: O=%s H=%s L=%s C=%s)",
                        t, open_p, high_p, low_p, close_p)
            return "\n".join(lines)
    except Exception as e:
        logger.warning("ta_signals fallback read failed for %s: %s", t, e)

    return ""


def get_fundamental_context(ticker: str, exchange: str) -> str:
    """
    Read the latest fundamental snapshot from datapai.fundamental_snapshot
    and return a concise, labelled text block for injection into the chat
    system prompt.

    Returns an empty string if no snapshot exists or on any DB error.
    TTL: fundamental_snapshot is recomputed nightly — always fresh enough.
    """
    try:
        from scripts.lib.db_helpers import get_conn
        sql = """
            SELECT
                company_name, sector, industry, currency,
                market_cap, pe_ratio, forward_pe, peg_ratio, pb_ratio,
                ps_ratio, ev_ebitda, ev_revenue,
                gross_margin, operating_margin, net_margin,
                roe, roa, roic,
                revenue_yoy, earnings_yoy, revenue_growth_5yr,
                current_ratio, debt_to_equity, interest_coverage,
                free_cash_flow, fcf_yield,
                dividend_yield,
                beta, next_earnings_date,
                valuation_score, quality_score, growth_score, macro_score,
                fundamental_score, fundamental_signal,
                analyst_consensus, analyst_target_price, analyst_upside_pct,
                macro_summary, macro_factors, geopolitical_flags,
                tech_disruption_risk,
                fundamental_summary, key_strengths, key_risks,
                computed_at
            FROM datapai.fundamental_snapshot
            WHERE ticker = %s AND exchange = %s
            LIMIT 1
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (ticker.upper(), exchange.upper()))
                row = cur.fetchone()
                if not row:
                    return ""
                cols = [d[0] for d in cur.description]
                d = dict(zip(cols, row))

        def _fmt(v, pct=False, mult=1e-9, unit="B"):
            if v is None:
                return "N/A"
            if pct:
                return f"{float(v)*100:.1f}%"
            if unit:
                return f"{float(v)/mult:.2f}{unit}"
            return f"{float(v):.2f}"

        def _score(v):
            return f"{float(v):.3f}" if v is not None else "N/A"

        signal = d.get("fundamental_signal") or "N/A"
        f_score = _score(d.get("fundamental_score"))
        val_s = _score(d.get("valuation_score"))
        qual_s = _score(d.get("quality_score"))
        grow_s = _score(d.get("growth_score"))
        macro_s = _score(d.get("macro_score"))

        lines = [f"[Fundamental Analysis — {ticker.upper()} | {exchange.upper()} | computed: {str(d.get('computed_at',''))[:10]}]"]

        # Signal headline
        lines.append(f"Signal: {signal}  |  Composite score: {f_score}")
        lines.append(f"Scores → Valuation: {val_s}  Quality: {qual_s}  Growth: {grow_s}  Macro: {macro_s}")

        # Company
        if d.get("company_name"):
            lines.append(f"Company: {d['company_name']}  |  Sector: {d.get('sector','N/A')}  |  Industry: {d.get('industry','N/A')}")

        # Market size
        mc = d.get("market_cap")
        if mc:
            lines.append(f"Market cap: {_fmt(mc)}  |  Beta: {d['beta']:.2f}" if d.get("beta") else f"Market cap: {_fmt(mc)}")

        # Valuation multiples
        val_parts = []
        if d.get("pe_ratio"):   val_parts.append(f"P/E: {float(d['pe_ratio']):.1f}")
        if d.get("forward_pe"): val_parts.append(f"Fwd P/E: {float(d['forward_pe']):.1f}")
        if d.get("pb_ratio"):   val_parts.append(f"P/B: {float(d['pb_ratio']):.1f}")
        if d.get("ev_ebitda"):  val_parts.append(f"EV/EBITDA: {float(d['ev_ebitda']):.1f}")
        if d.get("fcf_yield"):  val_parts.append(f"FCF yield: {float(d['fcf_yield'])*100:.1f}%")
        if val_parts:
            lines.append("Valuation: " + "  |  ".join(val_parts))

        # Quality / margins
        qual_parts = []
        if d.get("gross_margin"):     qual_parts.append(f"Gross margin: {_fmt(d['gross_margin'], pct=True, unit='')}")
        if d.get("net_margin"):       qual_parts.append(f"Net margin: {_fmt(d['net_margin'], pct=True, unit='')}")
        if d.get("roe"):              qual_parts.append(f"ROE: {_fmt(d['roe'], pct=True, unit='')}")
        if d.get("debt_to_equity") is not None:
            qual_parts.append(f"D/E: {float(d['debt_to_equity']):.2f}")
        if qual_parts:
            lines.append("Quality: " + "  |  ".join(qual_parts))

        # Growth
        grow_parts = []
        if d.get("revenue_yoy"):     grow_parts.append(f"Rev YoY: {_fmt(d['revenue_yoy'], pct=True, unit='')}")
        if d.get("earnings_yoy"):    grow_parts.append(f"EPS YoY: {_fmt(d['earnings_yoy'], pct=True, unit='')}")
        if d.get("revenue_growth_5yr"): grow_parts.append(f"5yr Rev CAGR: {_fmt(d['revenue_growth_5yr'], pct=True, unit='')}")
        if grow_parts:
            lines.append("Growth: " + "  |  ".join(grow_parts))

        # Analyst
        if d.get("analyst_consensus"):
            analyst_line = f"Analyst: {d['analyst_consensus']}"
            if d.get("analyst_target_price"):
                analyst_line += f"  |  Target: {float(d['analyst_target_price']):.2f} {d.get('currency','')}"
            if d.get("analyst_upside_pct"):
                analyst_line += f"  |  Upside: {float(d['analyst_upside_pct']):.1f}%"
            lines.append(analyst_line)

        # Next earnings
        if d.get("next_earnings_date"):
            lines.append(f"Next earnings: {str(d['next_earnings_date'])[:10]}")

        # Tech disruption risk
        if d.get("tech_disruption_risk") and d["tech_disruption_risk"] != "UNKNOWN":
            lines.append(f"Tech disruption risk: {d['tech_disruption_risk']}")

        # Macro summary
        if d.get("macro_summary"):
            lines.append(f"Macro: {d['macro_summary'][:300]}")

        # Geopolitical flags
        geo = d.get("geopolitical_flags")
        if geo:
            geo_list = geo if isinstance(geo, list) else []
            if geo_list:
                lines.append(f"Geopolitical: {'; '.join(geo_list[:3])}")

        # LLM narrative
        if d.get("fundamental_summary"):
            lines.append(f"Summary: {d['fundamental_summary'][:400]}")

        # Key strengths / risks
        strengths = d.get("key_strengths") or []
        risks = d.get("key_risks") or []
        if strengths:
            lines.append(f"Key strengths: {'; '.join(strengths[:3])}")
        if risks:
            lines.append(f"Key risks: {'; '.join(risks[:3])}")

        return "\n".join(lines)

    except Exception as e:
        logger.warning("get_fundamental_context failed for %s/%s: %s", ticker, exchange, e)
        return ""


def upsert_ticker_context(
    ticker: str,
    context_type: str,
    content: str,
    metadata: dict | None = None,
    ttl_hours: int = 24,
) -> None:
    """Store or refresh a ticker context cache entry (called by scan pipeline)."""
    try:
        import json
        from .db import execute
        execute(
            """
            INSERT INTO datapai.ticker_context_cache
                (ticker, context_type, content, metadata, expires_at)
            VALUES (%s, %s, %s, %s, now() + %s * interval '1 hour')
            ON CONFLICT (ticker, context_type) DO UPDATE SET
                content    = EXCLUDED.content,
                metadata   = EXCLUDED.metadata,
                created_at = now(),
                expires_at = now() + %s * interval '1 hour'
            """,
            (ticker.upper(), context_type, content, json.dumps(metadata or {}), ttl_hours, ttl_hours),
        )
    except Exception as e:
        logger.warning("upsert_ticker_context failed for %s: %s", ticker, e)
