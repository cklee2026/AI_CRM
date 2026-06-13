"""Bulk CSV import for historical price data.

Expected CSV columns: food, location, price, date
Optional columns: currency, source, notes, price_type

price_type is one of retail / wholesale / international / import_unit /
controlled (default retail). It lets several price layers coexist for the
same food/location/date - e.g. import FAMA wholesale prices alongside the
PriceCatcher retail prices already in the database.

Example CSV:
    food,location,price,date,currency,source,notes,price_type
    Rice (Long Grain),Lahad Datu,3.40,2025-06-15,MYR,Local Market,,retail
    Rice (Long Grain),Sabah,2.90,2025-06-15,MYR,FAMA,,wholesale
"""
import csv
from datetime import datetime
from pathlib import Path
from src.database import get_connection, get_food_id, get_location_id


def import_csv(filepath: str, skip_duplicates: bool = True) -> dict:
    """Import prices from a CSV file. Returns summary counts."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {filepath}")

    conn = get_connection()
    imported, skipped, errors = 0, 0, []

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            required = {"food", "location", "price", "date"}
            missing = required - set(name.strip().lower() for name in reader.fieldnames or [])
            if missing:
                raise ValueError(f"CSV missing required columns: {missing}. "
                                 f"Required: food, location, price, date")

            # Normalize header names
            for row_num, raw_row in enumerate(reader, start=2):
                row = {k.strip().lower(): (v.strip() if v else None) for k, v in raw_row.items()}
                try:
                    food_id = get_food_id(row["food"], conn)
                    location_id = get_location_id(row["location"], conn)

                    if food_id is None:
                        errors.append(f"Row {row_num}: unknown food '{row['food']}'")
                        continue
                    if location_id is None:
                        errors.append(f"Row {row_num}: unknown location '{row['location']}'")
                        continue

                    price = float(row["price"])
                    collected_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
                    currency = row.get("currency") or "MYR"
                    source = row.get("source")
                    notes = row.get("notes")
                    price_type = (row.get("price_type") or "retail").lower()

                    # Check for duplicate (same food/location/date/price_type)
                    existing = conn.execute(
                        "SELECT id FROM prices WHERE food_id=? AND location_id=? "
                        "AND collected_date=? AND price_type=?",
                        [food_id, location_id, collected_date, price_type]
                    ).fetchall()
                    if existing:
                        if skip_duplicates:
                            skipped += 1
                            continue
                        else:
                            conn.execute(
                                "UPDATE prices SET price=?, currency=?, source=?, notes=? WHERE id=?",
                                [price, currency, source, notes, existing[0][0]]
                            )
                            imported += 1
                            continue

                    next_id = conn.execute(
                        "SELECT COALESCE(MAX(id), 0) + 1 FROM prices"
                    ).fetchall()[0][0]

                    conn.execute("""
                        INSERT INTO prices (id, food_id, location_id, price, currency,
                                            collected_date, price_type, source, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, [next_id, food_id, location_id, price, currency,
                          collected_date, price_type, source, notes])
                    imported += 1

                except (ValueError, KeyError) as e:
                    errors.append(f"Row {row_num}: {e}")

        conn.commit()
    finally:
        conn.close()

    return {"imported": imported, "skipped": skipped, "errors": errors}


def create_template_csv(filepath: str = "import_template.csv"):
    """Create a template CSV file users can fill in."""
    with open(filepath, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["food", "location", "price", "date", "currency", "source", "notes", "price_type"])
        writer.writerow(["Rice (Long Grain)", "Lahad Datu", "3.40", "2025-06-15", "MYR", "Local Market", "", "retail"])
        writer.writerow(["Rice (Long Grain)", "Sabah", "2.90", "2025-06-15", "MYR", "FAMA", "wholesale example", "wholesale"])
    print(f"[OK] Template created: {filepath}")
