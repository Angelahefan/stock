#!/usr/bin/env python3
"""
Batch-translate all stock names in stock_directory from English to 7 languages.
Uses Gemini API to translate company names properly.

Processes in batches of 50 names per API call for efficiency.
Updates stock_directory rows in-place (lang != 'en').

Usage:
  GOOGLE_API_KEY=xxx PGHOST=localhost PGPORT=5432 PGUSER=postgres PGPASSWORD=postgres \
    python3 translate_stock_names.py [--exchange US] [--batch-size 50] [--dry-run]
"""
from __future__ import annotations
import psycopg2
import json
import os
import sys
import time
import argparse
import requests
from typing import Dict, List

# ── Config ──
GEMINI_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

LANGS = {
    "zh":    "Simplified Chinese",
    "zh-TW": "Traditional Chinese",
    "ja":    "Japanese",
    "ko":    "Korean",
    "vi":    "Vietnamese",
    "th":    "Thai",
    "ms":    "Malay",
}

def call_gemini(prompt: str) -> str:
    """Call Gemini API and return text response."""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 8192,
        },
    }
    resp = requests.post(GEMINI_URL, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def translate_batch(names: list[str], target_lang: str, target_lang_name: str) -> dict[str, str]:
    """
    Translate a batch of company names to target language.
    Returns {english_name: translated_name} dict.
    """
    names_json = json.dumps(names, ensure_ascii=False)
    prompt = f"""Translate these stock company names to {target_lang_name}.

Rules:
- If the company has an official well-known name in {target_lang_name}, use it (e.g. Apple → 苹果公司, Samsung → 三星)
- For less well-known companies, you MUST transliterate the name into {target_lang_name} script. NEVER leave it in English.
  Examples for Chinese: "Astra International" → "阿斯特拉国际", "Indorama Ventures" → "英多拉马风投", "Kasikornbank" → "开泰银行"
  Examples for Japanese: "Astra International" → "アストラ・インターナショナル", "Gamuda" → "ガムダ"
  Examples for Thai: "Bank Central Asia" → "ธนาคารกลางเอเชีย"
- Keep well-known abbreviations as-is ONLY if they are universally recognized (HSBC, IBM, BMW). Otherwise transliterate.
- EVERY name must be translated or transliterated. Do NOT return the English name unchanged.
- For Vietnamese/Thai/Indonesian/Malaysian companies, use their official local name if known.

Input (JSON array of English names):
{names_json}

Output ONLY a JSON object mapping each English name to its {target_lang_name} translation.
No markdown, no explanation, just the JSON object.
Example: {{"Apple Inc.": "苹果公司", "BHP Group": "必和必拓集团", "Astra International": "阿斯特拉国际"}}"""

    try:
        raw = call_gemini(prompt)
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        result = json.loads(raw)
        if isinstance(result, dict):
            return result
    except Exception as e:
        print(f"    ⚠ Gemini error: {e}")
    return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", help="Filter by exchange (US, ASX, HOSE)")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lang", help="Only translate to this language (e.g. zh)")
    args = parser.parse_args()

    if not GEMINI_API_KEY:
        print("ERROR: GOOGLE_API_KEY not set")
        sys.exit(1)

    conn = psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname="postgres",
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", "postgres"),
    )

    # Load all English names
    with conn.cursor() as cur:
        where = "WHERE lang='en'"
        params = []
        if args.exchange:
            where += " AND exchange=%s"
            params.append(args.exchange)
        cur.execute(f"SELECT symbol, name, exchange FROM datapai.stock_directory {where} ORDER BY exchange, symbol", params)
        rows = cur.fetchall()

    print(f"Found {len(rows)} English stock names to translate")

    target_langs = {args.lang: LANGS[args.lang]} if args.lang else LANGS
    total_updated = 0

    for lang_code, lang_name in target_langs.items():
        print(f"\n{'='*60}")
        print(f"Translating to {lang_name} ({lang_code})")
        print(f"{'='*60}")

        # Process in batches
        for i in range(0, len(rows), args.batch_size):
            batch = rows[i:i + args.batch_size]
            names = [r[1] for r in batch]
            symbols = [(r[0], r[2]) for r in batch]  # (symbol, exchange)

            print(f"  Batch {i//args.batch_size + 1}/{(len(rows) + args.batch_size - 1)//args.batch_size}: {len(batch)} names...")

            translations = translate_batch(names, lang_code, lang_name)

            if not translations:
                print(f"    ⚠ No translations returned, skipping batch")
                continue

            # Update DB
            if not args.dry_run:
                with conn.cursor() as cur:
                    updated = 0
                    for (sym, exchange), en_name in zip(symbols, names):
                        translated = translations.get(en_name)
                        if translated:
                            cur.execute(
                                """INSERT INTO datapai.stock_directory (symbol, name, exchange, lang)
                                   VALUES (%s, %s, %s, %s)
                                   ON CONFLICT (symbol, exchange, lang)
                                   DO UPDATE SET name = EXCLUDED.name""",
                                (sym, translated, exchange, lang_code),
                            )
                            updated += cur.rowcount
                    conn.commit()
                    total_updated += updated
                    print(f"    ✓ Upserted {updated}/{len(batch)} names")
            else:
                # Show sample translations
                for en_name in list(translations.keys())[:3]:
                    print(f"    {en_name} → {translations[en_name]}")
                print(f"    ... ({len(translations)} total)")

            # Rate limiting: 0.5s between batches
            time.sleep(0.5)

    print(f"\n{'='*60}")
    print(f"Done. Total rows updated: {total_updated}")
    conn.close()


if __name__ == "__main__":
    main()
