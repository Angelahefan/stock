"""
Seed stock_market_closed_dates for 2026-2030 across all 13 markets.
Uses a combination of fixed holidays + calculated holidays (Easter, lunar new year).

Run: python3 migrations/seed_market_closed_dates.py
"""
import os
import psycopg2
from datetime import date

# fmt: off
# Fixed holidays per market (month, day, name)
FIXED_HOLIDAYS = {
    "US": [
        (1, 1, "New Year's Day"), (1, 20, "MLK Day"), (2, 17, "Presidents' Day"),
        (5, 26, "Memorial Day"), (6, 19, "Juneteenth"), (7, 4, "Independence Day"),
        (9, 1, "Labor Day"), (11, 27, "Thanksgiving"), (12, 25, "Christmas"),
    ],
    "ASX": [
        (1, 1, "New Year's Day"), (1, 26, "Australia Day"), (4, 25, "ANZAC Day"),
        (6, 9, "Queen's Birthday"), (12, 25, "Christmas"), (12, 26, "Boxing Day"),
    ],
    "TSE": [
        (1, 1, "New Year"), (1, 2, "New Year Bank"), (1, 3, "New Year Bank"),
        (2, 11, "National Foundation Day"), (2, 23, "Emperor's Birthday"),
        (3, 20, "Vernal Equinox"), (4, 29, "Showa Day"), (5, 3, "Constitution Day"),
        (5, 4, "Greenery Day"), (5, 5, "Children's Day"),
        (7, 21, "Marine Day"), (8, 11, "Mountain Day"),
        (9, 15, "Respect for Aged"), (9, 23, "Autumnal Equinox"),
        (10, 13, "Sports Day"), (11, 3, "Culture Day"), (11, 23, "Labour Thanksgiving"),
    ],
    "HKEX": [
        (1, 1, "New Year"), (5, 1, "Labour Day"), (7, 1, "HKSAR Day"),
        (10, 1, "National Day"), (12, 25, "Christmas"), (12, 26, "Boxing Day"),
    ],
    "SSE": [
        (1, 1, "New Year"), (5, 1, "Labour Day"), (10, 1, "National Day"),
        (10, 2, "National Day"), (10, 3, "National Day"),
    ],
    "SZSE": [
        (1, 1, "New Year"), (5, 1, "Labour Day"), (10, 1, "National Day"),
        (10, 2, "National Day"), (10, 3, "National Day"),
    ],
    "LSE": [
        (1, 1, "New Year"), (5, 5, "Early May Bank"), (5, 26, "Spring Bank"),
        (8, 25, "Summer Bank"), (12, 25, "Christmas"), (12, 26, "Boxing Day"),
    ],
    "SGX": [
        (1, 1, "New Year"), (5, 1, "Labour Day"), (8, 9, "National Day"),
        (12, 25, "Christmas"),
    ],
    "SET": [
        (1, 1, "New Year"), (4, 13, "Songkran"), (4, 14, "Songkran"),
        (4, 15, "Songkran"), (5, 1, "Labour Day"), (12, 5, "King's Birthday"),
        (12, 10, "Constitution Day"), (12, 31, "New Year's Eve"),
    ],
    "KLSE": [
        (1, 1, "New Year"), (2, 1, "Federal Territory Day"), (5, 1, "Labour Day"),
        (6, 3, "Yang di-Pertuan Agong"), (8, 31, "Merdeka Day"),
        (9, 16, "Malaysia Day"), (12, 25, "Christmas"),
    ],
    "IDX": [
        (1, 1, "New Year"), (5, 1, "Labour Day"), (6, 1, "Pancasila Day"),
        (8, 17, "Independence Day"), (12, 25, "Christmas"),
    ],
    "HOSE": [
        (1, 1, "New Year"), (4, 30, "Reunification Day"), (5, 1, "Labour Day"),
        (9, 2, "National Day"),
    ],
    "TWSE": [
        (1, 1, "New Year"), (2, 28, "Peace Memorial Day"),
        (4, 4, "Children's Day"), (5, 1, "Labour Day"),
        (10, 10, "National Day"),
    ],
}

# Easter dates 2026-2030 (manually calculated)
EASTER_DATES = {
    2026: date(2026, 4, 5),
    2027: date(2027, 3, 28),
    2028: date(2028, 4, 16),
    2029: date(2029, 4, 1),
    2030: date(2030, 4, 21),
}

# Lunar New Year dates 2026-2030
LUNAR_NEW_YEAR = {
    2026: date(2026, 2, 17),
    2027: date(2027, 2, 6),
    2028: date(2028, 1, 26),
    2029: date(2029, 2, 13),
    2030: date(2030, 2, 3),
}
# fmt: on


def generate_all_dates():
    """Generate (market, date, reason) tuples for 2026-2030."""
    rows = []
    for year in range(2026, 2031):
        # Fixed holidays
        for market, holidays in FIXED_HOLIDAYS.items():
            for m, d, name in holidays:
                try:
                    rows.append((market, date(year, m, d), name))
                except ValueError:
                    pass  # Feb 29 in non-leap years etc.

        # Easter-based holidays (Good Friday, Easter Monday)
        easter = EASTER_DATES.get(year)
        if easter:
            from datetime import timedelta
            good_friday = easter - timedelta(days=2)
            easter_monday = easter + timedelta(days=1)
            for market in ["US", "ASX", "LSE", "HKEX", "SGX"]:
                rows.append((market, good_friday, "Good Friday"))
                rows.append((market, easter_monday, "Easter Monday"))
            # Easter Saturday for ASX
            rows.append(("ASX", easter - timedelta(days=1), "Easter Saturday"))

        # Lunar New Year (China, HK, Vietnam, Taiwan, Singapore, Malaysia)
        lny = LUNAR_NEW_YEAR.get(year)
        if lny:
            from datetime import timedelta
            for market in ["SSE", "SZSE", "HKEX", "HOSE", "TWSE", "SGX", "KLSE"]:
                for offset in range(-1, 3):
                    d = lny + timedelta(days=offset)
                    rows.append((market, d, f"Lunar New Year Day {offset+2}"))

    return rows


def main():
    host = os.getenv("DATAPAI_PG_HOST", "localhost")
    port = int(os.getenv("DATAPAI_PG_PORT", "5434"))
    db = os.getenv("DATAPAI_PG_DB", "postgres")
    user = os.getenv("DATAPAI_PG_USER", "postgres")
    pw = os.getenv("DATAPAI_PG_PASSWORD", "postgres")

    conn = psycopg2.connect(host=host, port=port, dbname=db, user=user, password=pw)
    conn.autocommit = True
    cur = conn.cursor()

    # Create table
    with open(os.path.join(os.path.dirname(__file__), "create_market_closed_dates.sql")) as f:
        cur.execute(f.read())
    print("Table created")

    # Seed
    rows = generate_all_dates()
    from psycopg2.extras import execute_values
    execute_values(
        cur,
        """INSERT INTO datapai.stock_market_closed_dates (market_code, closed_date, reason)
           VALUES %s ON CONFLICT DO NOTHING""",
        rows,
    )
    print(f"Seeded {len(rows)} closed dates across {len(FIXED_HOLIDAYS)} markets (2026-2030)")

    # Verify
    cur.execute("SELECT market_code, COUNT(*) FROM datapai.stock_market_closed_dates GROUP BY market_code ORDER BY market_code")
    for mkt, cnt in cur.fetchall():
        print(f"  {mkt}: {cnt} dates")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
