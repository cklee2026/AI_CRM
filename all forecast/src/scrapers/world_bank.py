"""World Bank Commodity Price Data (the "Pink Sheet") scraper.

Downloads the official monthly commodity price Excel file and imports
international prices for foods we track. This gives real historical
data going back decades - perfect for the 1-year backlog requirement.

Source: https://www.worldbank.org/en/research/commodity-markets
"""
import requests
import pandas as pd
from datetime import date, datetime
from pathlib import Path
from src.database import get_connection, get_food_id, get_location_id

PINK_SHEET_URL = (
    "https://thedocs.worldbank.org/en/doc/"
    "5d903e848db1d1b83e0ec8f744e55570-0350012021/related/"
    "CMO-Historical-Data-Monthly.xlsx"
)

# Map World Bank commodity column names -> (our food name, unit conversion to per-kg/litre)
# World Bank prices in $/mt are divided by 1000 to get $/kg.
COMMODITY_MAP = {
    "Rice, Thai 5%": ("Rice (Long Grain)", 0.001),      # $/mt -> $/kg
    "Palm oil": ("Cooking Oil (Palm)", 0.001),           # $/mt -> $/kg (~liter)
    "Sugar, world": ("Sugar", 1.0),                      # already $/kg
    "Wheat, US HRW": ("Flour (Wheat)", 0.001),           # $/mt -> $/kg
    "Chicken": ("Chicken (Whole)", 1.0),                 # $/kg
}


def download_pink_sheet(cache_dir: str = "./data/downloads") -> Path:
    """Download the World Bank monthly commodity Excel file."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    filepath = cache / "CMO-Historical-Data-Monthly.xlsx"

    print(f"Downloading World Bank Pink Sheet...")
    resp = requests.get(PINK_SHEET_URL, timeout=60, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) food-price-tracker/1.0"
    })
    resp.raise_for_status()
    filepath.write_bytes(resp.content)
    print(f"[OK] Downloaded to {filepath} ({len(resp.content) // 1024} KB)")
    return filepath


def parse_pink_sheet(filepath: Path, months_back: int = 14) -> list:
    """Parse the Monthly Prices sheet and return rows for our tracked foods.

    The sheet layout: row 4 = commodity names, row 5 = units, data starts ~row 7.
    Date index format: 2025M01 (year + M + month).
    """
    df = pd.read_excel(filepath, sheet_name="Monthly Prices", header=4, index_col=0)
    # Drop the units row (first row after header) and empty rows
    df = df.iloc[1:]
    df = df.dropna(how="all")

    records = []
    for col in df.columns:
        col_clean = str(col).strip()
        if col_clean not in COMMODITY_MAP:
            continue
        food_name, factor = COMMODITY_MAP[col_clean]

        series = df[col].dropna().tail(months_back)
        for idx, value in series.items():
            # Index like "2025M01"
            idx_str = str(idx).strip()
            if "M" not in idx_str:
                continue
            try:
                year, month = idx_str.split("M")
                collected = date(int(year), int(month), 1)
                price = round(float(value) * factor, 4)
            except (ValueError, TypeError):
                continue

            records.append({
                "food": food_name,
                "price": price,
                "date": collected,
            })

    return records


def run(months_back: int = 14) -> dict:
    """Download, parse and store international prices. Returns summary."""
    filepath = download_pink_sheet()
    records = parse_pink_sheet(filepath, months_back)

    if not records:
        return {"imported": 0, "skipped": 0,
                "message": "No matching commodities found - the sheet layout may have changed."}

    conn = get_connection()
    imported, skipped = 0, 0
    try:
        location_id = get_location_id("International", conn)
        for rec in records:
            food_id = get_food_id(rec["food"], conn)
            if food_id is None:
                continue

            existing = conn.execute(
                "SELECT id FROM prices WHERE food_id=? AND location_id=? AND collected_date=?",
                [food_id, location_id, rec["date"]]
            ).fetchall()
            if existing:
                skipped += 1
                continue

            next_id = conn.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM prices"
            ).fetchall()[0][0]
            conn.execute("""
                INSERT INTO prices (id, food_id, location_id, price, currency,
                                    collected_date, source, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [next_id, food_id, location_id, rec["price"], "USD",
                  rec["date"], "World Bank Pink Sheet", "monthly avg, per kg"])
            imported += 1

        conn.commit()
    finally:
        conn.close()

    return {"imported": imported, "skipped": skipped,
            "message": f"World Bank: {imported} new prices, {skipped} already existed."}


if __name__ == "__main__":
    result = run()
    print(result["message"])
