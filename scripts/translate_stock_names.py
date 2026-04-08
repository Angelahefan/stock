"""
Translate Chinese stock names to English using Gemini.
Processes in batches of 100 for efficiency.
Then updates stock_directory for all 7 non-zh languages.

Usage: source ~/.env.dev && python3 scripts/translate_stock_names.py
"""
import os
import json
import time
import requests
import psycopg2
from psycopg2.extras import execute_values

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
MODEL = "gemini-2.5-flash"
PG_HOST = os.getenv("DATAPAI_PG_HOST", "localhost")
PG_PORT = int(os.getenv("DATAPAI_PG_PORT", "5434"))
PG_DB = os.getenv("DATAPAI_PG_DB", "postgres")
PG_USER = os.getenv("DATAPAI_PG_USER", "postgres")
PG_PASS = os.getenv("DATAPAI_PG_PASSWORD", "postgres")


def get_conn():
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASS)


def translate_batch(names):
    """Send batch of (symbol, chinese_name) to Gemini, get English translations."""
    prompt = (
        "Translate these Chinese company names to English. "
        "Return ONLY a JSON object mapping symbol to English name. "
        "Use the official English company name if well-known, otherwise translate literally. "
        "Keep it concise (no 'Co., Ltd.' unless official).\n\n"
        "Examples:\n"
        "- 浦发银行 → SPD Bank\n"
        "- 隆基绿能 → LONGi Green Energy\n"
        "- 贵州茅台 → Kweichow Moutai\n"
        "- 中国平安 → Ping An Insurance\n"
        "- 台积电 → TSMC\n\n"
        "Input:\n"
    )
    for sym, name in names:
        prompt += f"{sym}|{name}\n"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GOOGLE_API_KEY}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192},
    }
    r = requests.post(url, json=body, timeout=120)
    if r.status_code != 200:
        print(f"API error: {r.status_code} {r.text[:200]}")
        return {}

    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"JSON parse error: {text[:300]}")
        return {}


def main():
    conn = get_conn()
    cur = conn.cursor()

    # Get all Chinese stock names
    cur.execute("""
        SELECT symbol, name, exchange FROM datapai.stock_directory
        WHERE exchange IN ('SSE', 'SZSE', 'TWSE') AND lang = 'zh'
        ORDER BY exchange, symbol
    """)
    rows = cur.fetchall()
    print(f"Total: {len(rows)} tickers to translate")

    # Translate in batches
    en_names = {}
    batch_size = 100
    for i in range(0, len(rows), batch_size):
        batch = [(r[0], r[1]) for r in rows[i:i + batch_size]]
        batch_num = i // batch_size + 1
        total_batches = (len(rows) - 1) // batch_size + 1
        print(f"Batch {batch_num}/{total_batches} ({len(batch)} tickers)...", end=" ", flush=True)
        translated = translate_batch(batch)
        en_names.update(translated)
        print(f"got {len(translated)} translations")
        time.sleep(2)  # rate limit

    print(f"\nTotal translated: {len(en_names)} / {len(rows)}")

    # Save results incrementally
    with open("/tmp/en_names.json", "w") as f:
        json.dump(en_names, f, ensure_ascii=False, indent=2)
    print(f"Saved /tmp/en_names.json ({len(en_names)} entries)")

    if not en_names:
        print("No translations — exiting")
        conn.close()
        return

    # Update stock_directory: set English name for all non-zh languages
    NON_ZH_LANGS = ["en", "ja", "ko", "ms", "th", "vi"]
    conn2 = get_conn()
    conn2.autocommit = True
    cur2 = conn2.cursor()
    updated = 0
    for sym, en_name in en_names.items():
        for lang in NON_ZH_LANGS:
            cur2.execute(
                "UPDATE datapai.stock_directory SET name = %s WHERE symbol = %s AND lang = %s",
                (en_name, sym, lang),
            )
            updated += cur2.rowcount
    print(f"Updated {updated} rows")
    cur2.close()
    conn2.close()

    # Verify
    cur2.execute("""
        SELECT lang, name FROM datapai.stock_directory
        WHERE symbol = '601012' ORDER BY lang
    """)
    print("\nVerification (601012):")
    for lang, name in cur2.fetchall():
        print(f"  {lang}: {name}")

    cur.close()
    cur2.close()
    conn.close()


if __name__ == "__main__":
    main()
