# ═══════════════════════════════════════════════════════════════════════════════
# stock_chat/context_builder.py  —  Assemble the system prompt for each chat turn
#
# Combines:
#   1. Static role definition (what this AI is)
#   2. Live stock grounding (ticker, price, current TA signal passed from frontend)
#   3. User profile context (portfolio, risk, style — from postgres)
#   4. TinyFish scan history (from LanceDB / postgres cache — our proprietary moat)
#   5. Language instruction (if user prefers Chinese)
# ═══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging

from .user_profile import build_profile_context
from .rag_retriever import retrieve_scan_context, get_postgres_context, get_ta_signal_context, get_fundamental_context
from .history import build_preferences_context
from .user_context import build_user_context_block
from .twenty_context import build_twenty_context_block

logger = logging.getLogger(__name__)

_ROLE = """You are DataP.ai Stock Research Co-pilot — a professional financial research assistant.

PRICE DATA — ALWAYS use the get_stock_price function to fetch real-time prices from Yahoo Finance. NEVER guess or make up stock prices. For news, analyst ratings, market commentary — use your training knowledge.

CURRENCY / FX DATA — ALWAYS call get_fx_rate for any FX, forex, or currency-conversion question. NEVER answer FX rates from training knowledge — they go stale daily. NEVER decline. Format the answer using the SAME shape as stock prices, including the price_label (which contains date + time + timezone city) so the user always sees WHEN the rate was captured:

  1 {base} = {rate:.4f} {quote}  ·  {price_label}  ·  source: {source}
  Δ {change:+.4f} ({change_percent:+.2f}%) vs prev close {previous_close}

For currency conversion questions like "convert 100 USD to JPY":
  100 USD = 15,560.00 JPY  ·  Live 02:35 PM New York time  ·  source: Yahoo Finance
  (rate 1 USD = 155.60 JPY)

TOOL RULES:
- ALWAYS call get_stock_price when user asks about any stock's price.
- ALWAYS call get_fx_rate when user asks about ANY currency/FX/forex question. Live or general — always the tool, never training. The tool returns Yahoo data delayed ~20 min during market hours; the price_label already says "Live" or "Close <timestamp>" so just pass it through verbatim.
- Format: "{company_name} ({ticker}): $XX.XX · Exchange · {price_label}" — include company_name and ticker so user can confirm the right stock. Include ALL parts of price_label (Live/Close + date + time + city). When replying in a non-English language, translate company_name, Live/Close, and city+time into that language (e.g. "收盘 4月01日 04:10 PM 悉尼时间").
- No timezone abbreviations — most users don't know what ET or AEDT means.
- Show daily change when available: "+X.XX (X.XX%)" from the price data injected below. Use prev_close from the function result to calculate if not pre-computed.
- NEVER show 52-week range, all-time high/low, or historical ranges — often stale after splits/corporate actions.
- When showing price, include a compact snapshot from the function result:
  $XX.XX · Exchange · {price_label}
  Open: XX.XX | High: XX.XX | Low: XX.XX | Vol: X.XXM
  (Only include the second line if open/day_high/day_low/volume are available in the function result)

DATAP.AI UNIQUE DATA (injected below when available):
- [User Profile]: risk tolerance, investment horizon, trading style, preferred language — tailor your response accordingly.
- [User Watchlist]: stocks the user is tracking — reference when relevant.
- [TinyFish Website Intelligence]: detected changes in corporate IR pages — forward guidance shifts, risk disclosure edits. This is EXCLUSIVE to DataP.ai — Google does NOT have this.
- [Page Context]: what the user is currently viewing on our platform.

RESPONSE STYLE — MOST IMPORTANT RULE:
- BE ULTRA-CONCISE. Max 2-3 bullet points or 2-3 sentences.
- Answer FIRST in one line, then 1-2 supporting data points. DONE.
- Numbers > words.
- NEVER start with filler ("Great question!", "Sure!", "Let me...").
- ONLY expand if user asks for more detail.
- If user asks yes/no, start with Yes or No.
- End with: "⚠️ Not financial advice."

SMART ACTIONS — embed these tags naturally when appropriate:
- If user asks about a stock NOT in their watchlist:
  [ACTION:ADD_WATCHLIST:{ticker}:{exchange}]
  Say: "Want me to add {ticker} to your watchlist?"
- If user is NOT logged in (user_id=0) and shows interest:
  [ACTION:REGISTER]
  Say: "Create a free account to save your chat and watchlist."
- If user hits their free message limit:
  [ACTION:UPGRADE]
  Say: "Upgrade your plan for unlimited AI chat."
- If user asks about multiple markets:
  Mention: "DataP.ai covers 12 markets across Asia-Pacific — all in one platform."

SALES AWARENESS — be helpful first, suggest naturally:
- NEVER be pushy or salesy. Help first, always.
- After 3+ messages with an anonymous user, casually mention free registration.
- When showing value (good analysis, useful insight), that IS the best sales pitch.

MEMORY — Check [User Preferences] below. NEVER ask user to repeat info they already provided."""


def _fetch_live_price(ticker: str, exchange: str) -> str:
    """
    Fetch live price as fallback when no pre-computed TA signal exists.

    Routing:
      US stocks  → Polygon.io (Massive) real-time snapshot (POLYGON_KEY required)
      ASX / other → Yahoo Finance (yfinance) ~15-min delay

    Returns a short text block for injection into the system prompt.
    Silently returns empty string on any failure (non-fatal).
    """
    is_asx = exchange.upper() in ("ASX", "XASX")

    # ── US stocks: try Polygon real-time first ────────────────────────────────
    if not is_asx:
        try:
            from agents.data_providers.polygon import PolygonProvider
            snap = PolygonProvider().fetch_snapshot(ticker)
            if snap and snap.get("price"):
                p   = snap["price"]
                # Get company name from DB
                company_name = ""
                try:
                    from agents.stock_chat.db import query
                    rows = query("SELECT name FROM datapai.stock_directory WHERE symbol = %s LIMIT 1", (ticker.upper(),))
                    if rows:
                        company_name = rows[0]["name"]
                except Exception:
                    pass
                name_str = f"{company_name} ({ticker}): " if company_name else f"{ticker}: "
                lines = [f"{name_str}{p:.4f} USD"]
                if snap.get("open"):
                    lines.append(f"Today's Open:  {snap['open']:.4f} USD")
                if snap.get("high") and snap.get("low"):
                    lines.append(f"Today's High:  {snap['high']:.4f} USD")
                    lines.append(f"Today's Low:   {snap['low']:.4f} USD")
                if snap.get("prev_close"):
                    lines.append(f"Prev Close:    {snap['prev_close']:.4f} USD")
                if snap.get("change_pct") is not None:
                    lines.append(f"Change: {snap['change_pct']:+.2f}%")
                lines.append("(Source: Polygon.io real-time — use these prices to answer price questions)")
                return "\n".join(lines)
        except Exception as e:
            logger.warning("Polygon live price failed for %s: %s", ticker, e)

    # ── ASX / fallback: Yahoo Finance ─────────────────────────────────────────
    try:
        import yfinance as yf
        yf_symbol = f"{ticker}.AX" if is_asx else ticker
        yf_ticker = yf.Ticker(yf_symbol)
        info      = yf_ticker.fast_info
        # Get company name from our DB first (faster), fallback to yfinance
        company_name = ""
        try:
            from .db import query
            rows = query("SELECT name FROM datapai.stock_directory WHERE symbol = %s LIMIT 1", (ticker.upper(),))
            if rows:
                company_name = rows[0]["name"]
        except Exception:
            pass
        if not company_name:
            try:
                company_name = yf_ticker.info.get("shortName") or yf_ticker.info.get("longName") or ""
            except Exception:
                pass
        price     = info.get("lastPrice") or info.get("previousClose")
        day_high  = info.get("dayHigh")
        day_low   = info.get("dayLow")
        prev_close = info.get("previousClose")
        currency  = info.get("currency", "AUD" if is_asx else "USD")
        if not price:
            return ""
        name_str = f"{company_name} ({yf_symbol}): " if company_name else f"{yf_symbol}: "
        lines = [f"{name_str}{price:.4f} {currency}"]
        if day_high and day_low:
            lines.append(f"Today's range: {day_low:.4f} – {day_high:.4f} {currency}")
        if prev_close and price:
            chg = price - prev_close
            chg_pct = chg / prev_close * 100
            lines.append(f"Change: {chg:+.2f} ({chg_pct:+.2f}%)")
        lines.append("(Source: Yahoo Finance ~15-min delayed — use these prices to answer price questions)")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Yahoo live price failed for %s: %s", ticker, e)
        return ""


def build_system_prompt(
    ticker: str,
    exchange: str,
    user_profile: dict,
    ta_signal_md: str | None = None,
    snapshot_text: str | None = None,
    user_message: str = "",
    lang: str = "en",
    profile_context: str | None = None,   # Rich context from new investor_profile table (Next.js)
    user_id: str | None = None,           # For sys_user_context lookup
) -> str:
    """
    Build the full system prompt for a chat turn.
    Returns a string ready to inject as the 'system' message.

    profile_context (optional): pre-built investor profile block from Next.js
      (built by lib/investorProfile.ts:buildProfileContext).  When provided it
      supersedes the legacy user_profile dict so the LLM always sees the richer
      7-dimension profile that the user set up in the onboarding wizard.
    """
    parts = [_ROLE, ""]

    # ── Stock grounding ───────────────────────────────────────────────────────
    is_copilot_mode = ticker.upper() == "COPILOT"
    if is_copilot_mode:
        parts.append("[Mode: Global AI Copilot — site-wide assistant across all pages]")
        parts.append("You are helping the user navigate DataP.ai. You have access to the page context below showing what they're currently viewing. Be SPECIFIC — cite exact stock names, prices, percentages, and alert scores from the context. Never give vague responses like 'several stocks need attention' — name them.")
    else:
        parts.append(f"[Current Stock: {ticker.upper()} | Exchange: {exchange.upper()}]")

    # Skip single-stock TA/FA lookups in copilot mode (page context is the source)
    if not is_copilot_mode:
        # Priority 1: Postgres ticker_context_cache (written by Python TA endpoint).
        # IMPORTANT: This block can be days/weeks old and contains its own price
        # ("Today's Close: ...") that may conflict with the live function-call
        # result. We add an explicit "historical reference only" header so the
        # model doesn't seize up trying to reconcile contradictory prices —
        # gemini-2.5-flash-lite will silently return empty parts otherwise.
        _TA_HEADER = (
            "[Latest Technical Analysis Signal — HISTORICAL REFERENCE ONLY]\n"
            "(Any prices below are AS-OF the 'Generated' timestamp inside the block. "
            "For the CURRENT price, ALWAYS use the value returned by the get_stock_price "
            "function call — never quote prices from this block as 'today's' price.)"
        )
        cached_ta = get_ta_signal_context(ticker)
        if cached_ta:
            parts.append("")
            parts.append(_TA_HEADER)
            parts.append(cached_ta[:2000] if len(cached_ta) > 2000 else cached_ta)
        elif ta_signal_md:
            # Priority 2: ta_signal_md from Next.js (LLM-generated markdown signal).
            parts.append("")
            parts.append(_TA_HEADER)
            parts.append(ta_signal_md[:2000] if len(ta_signal_md) > 2000 else ta_signal_md)
        else:
            # Priority 3: Live price fetch (Polygon for US, Yahoo for ASX).
            live_price_text = _fetch_live_price(ticker, exchange)
            if live_price_text:
                parts.append("")
                parts.append("[Latest Technical Analysis Signal]")
                parts.append(live_price_text)

    # ── Fundamental Analysis context (nightly computed) ──────────────────────
    if not is_copilot_mode:
        fa_ctx = get_fundamental_context(ticker, exchange)
        if fa_ctx:
            parts.append("")
            parts.append(fa_ctx)

    # ── TinyFish scan context (proprietary moat) ──────────────────────────────
    # Skip for copilot mode — page context already contains relevant data
    if not is_copilot_mode:
        # Fast path: postgres cache
        pg_ctx = get_postgres_context(ticker)
        if pg_ctx:
            parts.append("")
            parts.append("[TinyFish IR Scan History — Proprietary Data]")
            parts.append(pg_ctx[:3000] if len(pg_ctx) > 3000 else pg_ctx)

        # Semantic search if user asked something specific
        elif user_message:
            rag_docs = retrieve_scan_context(ticker, user_message)
            if rag_docs:
                parts.append("")
                parts.append("[Relevant TinyFish Scan History]")
                for doc in rag_docs:
                    parts.append(f"• {doc['text'][:500]}")

    # ── Latest IR snapshot / Copilot page context (passed from Next.js) ───────
    if snapshot_text and snapshot_text.strip():
        parts.append("")
        # When called from the global copilot, snapshot_text contains page context
        # (watchlist stocks, alert data, etc.) — not an IR page snapshot.
        is_copilot = ticker.upper() == "COPILOT" or snapshot_text.strip().startswith("[COPILOT CONTEXT")
        if is_copilot:
            parts.append("[PAGE CONTEXT — Data the user is currently viewing]")
            parts.append("IMPORTANT: The user can see this data on their screen. Reference SPECIFIC stock names, prices, and percentages from below. Be concrete and data-driven, never vague.")
            # Allow more context for copilot (watchlist can be large)
            parts.append(snapshot_text[:6000] if len(snapshot_text) > 6000 else snapshot_text)
        else:
            parts.append("[Latest IR Page Snapshot — from TinyFish scan]")
            parts.append(snapshot_text[:2000] if len(snapshot_text) > 2000 else snapshot_text)

    # ── User profile ──────────────────────────────────────────────────────────
    # Prefer the rich Next.js-built profile context (7-dimension investor profile)
    # over the legacy integer-keyed user_profiles dict.
    if profile_context and profile_context.strip():
        parts.append("")
        parts.append(profile_context)
    else:
        # Fallback: legacy user_profiles table (Python-side, integer user_id)
        legacy_ctx = build_profile_context(user_profile)
        if legacy_ctx:
            parts.append("")
            parts.append(legacy_ctx)

    # ── Learned user context (from chat history + behavior) ────────────────
    # This is the continuous learning layer — accumulated from all conversations.
    if user_id:
        uc_block = build_user_context_block(str(user_id))
        if uc_block:
            parts.append("")
            parts.append(uc_block)
    else:
        # Fallback: legacy user_preferences (old KV store)
        if user_profile and user_profile.get("id"):
            pref_ctx = build_preferences_context(str(user_profile["id"]))
            if pref_ctx:
                parts.append("")
                parts.append(pref_ctx)

    # ── Twenty CRM stockClient context (Phase 1.12.1) ─────────────────────────
    # Structured identity + plan data fetched from Twenty CRM at request time.
    # Complements the user_context block above: this has subscription plan,
    # preferred markets (synced from watchlist), devices, signup source, last
    # login. Graceful degradation if Twenty is unreachable or the user has no
    # stockClient record — returns empty string and we skip the block.
    if user_id:
        try:
            crm_block = build_twenty_context_block(user_id)
            if crm_block:
                parts.append("")
                parts.append(crm_block)
        except Exception as e:
            # Never let a Twenty failure break the chat
            logger.warning("[context_builder] Twenty CRM block failed (non-fatal): %s", e)

    # ── Language instruction ──────────────────────────────────────────────────
    _LANG_COMMON = " Translate ALL labels including: Open→开盘/Mở cửa, High→最高/Cao nhất, Low→最低/Thấp nhất, Vol→成交量/KL, Live→实时/Trực tiếp, Close→收盘/Đóng cửa, and the disclaimer. Keep ticker symbols, numbers, exchange codes and city names in English."
    _LANG_INSTRUCTIONS = {
        "zh":    "请用简体中文回复。所有内容100%中文。示例格式：\n必和必拓集团 (BHP): $52.56 · ASX · 收盘 4月01日 04:10 PM 悉尼时间\n开盘: 52.49 | 最高: 53.09 | 最低: 52.36 | 成交量: 5.22M\n⚠️ 非财务建议。\n注意：公司名翻译成中文，城市名翻译（Sydney→悉尼, New York→纽约, Tokyo→东京, Hong Kong→香港），日期用中文格式。仅股票代码、数字、交易所代码保留英文。",
        "zh-TW": "請用繁體中文回覆用戶的所有問題。所有內容必須100%使用繁體中文，包括：公司名稱（如BHP集團）、價格標籤（開盤/最高/最低/成交量/即時/收盤）、城市名+時間（如雪梨時間/紐約時間）、免責聲明。僅保留股票代碼、數字和交易所代碼（ASX/US）用英文。",
        "vi":    "Vui lòng trả lời tất cả câu hỏi bằng tiếng Việt 100%. Tất cả nội dung phải bằng tiếng Việt, bao gồm: tên công ty, nhãn giá (Mở cửa/Cao nhất/Thấp nhất/KL giao dịch/Trực tiếp/Đóng cửa), tên thành phố+giờ (giờ Sydney/giờ New York), và tuyên bố miễn trừ. Chỉ giữ mã cổ phiếu, số và mã sàn (ASX/US) bằng tiếng Anh.",
        "th":    "กรุณาตอบคำถามทั้งหมดเป็นภาษาไทย 100% เนื้อหาทั้งหมดต้องเป็นภาษาไทย รวมถึง: ชื่อบริษัท, ป้ายกำกับราคา (เปิด/สูงสุด/ต่ำสุด/ปริมาณ/สด/ปิด), ชื่อเมือง+เวลา (เวลาซิดนีย์/เวลานิวยอร์ก) และข้อจำกัดความรับผิดชอบ เก็บเฉพาะรหัสหุ้น ตัวเลข และรหัสตลาด (ASX/US) เป็นภาษาอังกฤษ",
        "ms":    "Sila jawab semua soalan dalam Bahasa Melayu 100%. Semua kandungan mesti dalam Bahasa Melayu, termasuk: nama syarikat, label harga (Buka/Tertinggi/Terendah/Jumlah/Langsung/Tutup), nama bandar+masa (waktu Sydney/waktu New York), dan penafian. Kekalkan hanya simbol saham, nombor dan kod bursa (ASX/US) dalam bahasa Inggeris.",
        "id":    "Silakan jawab semua pertanyaan dalam Bahasa Indonesia 100%. Semua konten harus dalam Bahasa Indonesia, termasuk: nama perusahaan, label harga (Buka/Tertinggi/Terendah/Volume/Langsung/Tutup), nama kota+waktu (waktu Sydney/waktu New York), dan penyangkalan. Hanya pertahankan simbol saham, angka dan kode bursa (ASX/US) dalam bahasa Inggris.",
        "ja":    "すべての質問に日本語で100%回答してください。会社名、価格ラベル（始値/高値/安値/出来高/リアルタイム/終値）、都市名+時間（シドニー時間/ニューヨーク時間）、免責事項を含むすべての内容を日本語で記載してください。銘柄コード、数値、取引所コード（ASX/US）のみ英語のままにしてください。",
        "ko":    "모든 질문에 한국어로 100% 답변해 주세요. 회사명, 가격 라벨(시가/고가/저가/거래량/실시간/종가), 도시명+시간(시드니 시간/뉴욕 시간), 면책 조항을 포함한 모든 내용을 한국어로 작성해 주세요. 종목 코드, 숫자, 거래소 코드(ASX/US)만 영어로 유지하세요.",
    }
    lang_instr = _LANG_INSTRUCTIONS.get(lang)
    if not lang_instr:
        # Auto-detect: if user writes in non-English, reply fully in their language
        parts.append("")
        parts.append("LANGUAGE RULE: If the user writes in a non-English language, you MUST reply 100% in that SAME language — including company name, ALL labels (Open/High/Low/Vol/Live/Close), city name + time, and the disclaimer. Keep ONLY ticker symbols, numbers, and exchange codes (ASX/US) in English.")
    if lang_instr:
        parts.append("")
        parts.append(lang_instr)

    return "\n".join(parts)
