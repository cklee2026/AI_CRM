import duckdb
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple

def get_connection():
    """Get a DuckDB connection."""
    db_path = Path("./data/prices.duckdb")
    if not db_path.exists():
        raise FileNotFoundError("Database not initialized. Run 'python -m src.database.schema' first.")
    return duckdb.connect(str(db_path))

def get_food_id(food_name: str, conn=None) -> Optional[int]:
    """Get food ID by name."""
    should_close = False
    if conn is None:
        conn = get_connection()
        should_close = True

    try:
        result = conn.execute(
            "SELECT id FROM foods WHERE name = ?",
            [food_name]
        ).fetchall()
        return result[0][0] if result else None
    finally:
        if should_close:
            conn.close()

def get_location_id(location_name: str, conn=None) -> Optional[int]:
    """Get location ID by name."""
    should_close = False
    if conn is None:
        conn = get_connection()
        should_close = True

    try:
        result = conn.execute(
            "SELECT id FROM locations WHERE name = ?",
            [location_name]
        ).fetchall()
        return result[0][0] if result else None
    finally:
        if should_close:
            conn.close()

def add_price(food_name: str, location_name: str, price: float,
              collected_date: date = None, source: str = None,
              notes: str = None, currency: str = "MYR",
              price_type: str = "retail"):
    """Add a price entry to the database.

    price_type is one of retail / wholesale / international / import_unit /
    controlled (see schema.PRICE_TYPES). Several layers can coexist for the
    same food/location/date.
    """
    conn = get_connection()
    try:
        if collected_date is None:
            collected_date = date.today()

        food_id = get_food_id(food_name, conn)
        location_id = get_location_id(location_name, conn)

        if food_id is None:
            raise ValueError(f"Food '{food_name}' not found. Available foods: {[f['name'] for f in list_foods()]}")
        if location_id is None:
            raise ValueError(f"Location '{location_name}' not found. Available locations: {[l['name'] for l in list_locations()]}")

        # Get next ID
        result = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM prices").fetchall()
        next_id = result[0][0]

        conn.execute("""
            INSERT INTO prices (id, food_id, location_id, price, currency, collected_date, price_type, source, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [next_id, food_id, location_id, price, currency, collected_date, price_type, source, notes])

        conn.commit()
        print(f"[OK] Added: {food_name} at {location_name} = {price} {currency} "
              f"({collected_date}, {price_type})")
    finally:
        conn.close()

def add_food(name: str, category: str, unit: str) -> int:
    """Add a user-defined food item. Returns the new food id."""
    conn = get_connection()
    try:
        if get_food_id(name, conn) is not None:
            raise ValueError(f"Food '{name}' already exists.")
        next_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM foods").fetchall()[0][0]
        conn.execute(
            "INSERT INTO foods (id, name, category, unit, is_custom) VALUES (?, ?, ?, ?, true)",
            [next_id, name, category, unit]
        )
        conn.commit()
        print(f"[OK] Added food: {name} ({category}, per {unit})")
        return next_id
    finally:
        conn.close()

def delete_food(name: str) -> dict:
    """Delete a food and everything tied to it.

    Removes its prices and any PriceCatcher tracking mapping first (FK order),
    so it disappears from every dropdown AND won't be re-imported on the next
    scrape. Returns a summary of what was removed.
    """
    conn = get_connection()
    try:
        food_id = get_food_id(name, conn)
        if food_id is None:
            raise ValueError(f"Food '{name}' not found.")

        n_prices = conn.execute(
            "SELECT COUNT(*) FROM prices WHERE food_id = ?", [food_id]
        ).fetchall()[0][0]

        # Child rows first (prices references foods via FK).
        conn.execute("DELETE FROM prices WHERE food_id = ?", [food_id])
        # Stop future auto-import of this item (table may not exist on old DBs).
        try:
            conn.execute("DELETE FROM tracked_items WHERE food_id = ?", [food_id])
        except Exception:
            pass
        conn.execute("DELETE FROM foods WHERE id = ?", [food_id])
        conn.commit()
        print(f"[OK] Deleted food '{name}' ({n_prices} prices removed)")
        return {"food": name, "prices_removed": n_prices}
    finally:
        conn.close()

def add_location(name: str, level: int, parent_name: str = None) -> int:
    """Add a user-defined location. Returns the new location id."""
    conn = get_connection()
    try:
        if get_location_id(name, conn) is not None:
            raise ValueError(f"Location '{name}' already exists.")
        parent_id = None
        if parent_name:
            parent_id = get_location_id(parent_name, conn)
            if parent_id is None:
                raise ValueError(f"Parent location '{parent_name}' not found.")
        next_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM locations").fetchall()[0][0]
        conn.execute(
            "INSERT INTO locations (id, name, level, parent_id, country_code) VALUES (?, ?, ?, ?, 'MY')",
            [next_id, name, level, parent_id]
        )
        conn.commit()
        print(f"[OK] Added location: {name} (level {level})")
        return next_id
    finally:
        conn.close()

def list_foods() -> List[Dict]:
    """List all available foods."""
    conn = get_connection()
    try:
        result = conn.execute(
            "SELECT id, name, category, unit FROM foods ORDER BY category, name"
        ).fetchall()
        return [
            {"id": r[0], "name": r[1], "category": r[2], "unit": r[3]}
            for r in result
        ]
    finally:
        conn.close()

def list_locations() -> List[Dict]:
    """List all locations with hierarchy."""
    conn = get_connection()
    try:
        result = conn.execute("""
            SELECT id, name, level, parent_id FROM locations ORDER BY level, name
        """).fetchall()
        return [
            {"id": r[0], "name": r[1], "level": r[2], "parent_id": r[3]}
            for r in result
        ]
    finally:
        conn.close()

def get_prices(food_name: str = None, location_name: str = None,
               start_date: date = None, end_date: date = None,
               price_type: str = None) -> List[Dict]:
    """Get prices with optional filtering.

    price_type filters to a single layer (retail / wholesale / international /
    import_unit / controlled). None returns all layers.
    """
    conn = get_connection()
    try:
        query = """
            SELECT f.name, l.name, p.price, p.currency, p.collected_date,
                   p.source, p.notes, p.price_type
            FROM prices p
            JOIN foods f ON p.food_id = f.id
            JOIN locations l ON p.location_id = l.id
            WHERE 1=1
        """
        params = []

        if food_name:
            query += " AND f.name = ?"
            params.append(food_name)
        if location_name:
            query += " AND l.name = ?"
            params.append(location_name)
        if price_type:
            query += " AND p.price_type = ?"
            params.append(price_type)
        if start_date:
            query += " AND p.collected_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND p.collected_date <= ?"
            params.append(end_date)

        query += " ORDER BY p.collected_date DESC, f.name"

        result = conn.execute(query, params).fetchall()
        return [
            {
                "food": r[0],
                "location": r[1],
                "price": float(r[2]),
                "currency": r[3],
                "date": r[4],
                "source": r[5],
                "notes": r[6],
                "price_type": r[7]
            }
            for r in result
        ]
    finally:
        conn.close()

def get_price_statistics(food_name: str, location_name: str) -> Dict:
    """Get price statistics for a food in a location."""
    conn = get_connection()
    try:
        food_id = get_food_id(food_name, conn)
        location_id = get_location_id(location_name, conn)

        if not food_id or not location_id:
            return None

        result = conn.execute("""
            SELECT
                COUNT(*) as count,
                AVG(price) as avg_price,
                MIN(price) as min_price,
                MAX(price) as max_price,
                MIN(collected_date) as first_date,
                MAX(collected_date) as last_date
            FROM prices
            WHERE food_id = ? AND location_id = ?
        """, [food_id, location_id]).fetchall()

        if not result:
            return None

        r = result[0]
        return {
            "food": food_name,
            "location": location_name,
            "count": r[0],
            "avg_price": float(r[1]) if r[1] else None,
            "min_price": float(r[2]) if r[2] else None,
            "max_price": float(r[3]) if r[3] else None,
            "first_date": r[4],
            "last_date": r[5]
        }
    finally:
        conn.close()

def export_to_csv(filename: str = "prices_export.csv",
                  food_name: str = None,
                  location_name: str = None):
    """Export prices to CSV."""
    conn = get_connection()
    try:
        query = """
            SELECT f.name as food, l.name as location,
                   p.price, p.currency, p.collected_date,
                   p.source, p.notes
            FROM prices p
            JOIN foods f ON p.food_id = f.id
            JOIN locations l ON p.location_id = l.id
            WHERE 1=1
        """
        params = []

        if food_name:
            query += " AND f.name = ?"
            params.append(food_name)
        if location_name:
            query += " AND l.name = ?"
            params.append(location_name)

        query += " ORDER BY p.collected_date DESC"

        result = conn.execute(query, params).df()
        result.to_csv(filename, index=False)
        print(f"[OK] Exported to {filename}")
    finally:
        conn.close()
