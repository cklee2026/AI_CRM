"""KPDN PriceCatcher scraper - official Malaysian government price data.

Source: https://data.gov.my (Ministry of Domestic Trade / KPDN)
Monthly parquet files with item-level prices per premise, covering every
district in Malaysia - including Lahad Datu (31 premises) and Sabah (325).

For each tracked food we compute WEEKLY average prices at three levels:
  - Malaysia   (all premises nationwide)
  - Sabah      (premises where state = Sabah)
  - Lahad Datu (premises where district = Lahad Datu)
"""
import requests
import yaml
import duckdb as _duckdb
from datetime import date
from pathlib import Path
from src.database import get_connection, get_food_id, get_location_id

CACHE_DIR = Path("./data/downloads")

GEO_FILTERS = {
    "Malaysia": "1=1",
    "Sabah": "upper(pr.state) = 'SABAH'",
    "Lahad Datu": "upper(pr.district) = 'LAHAD DATU'",
}


def _load_config() -> dict:
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["scrapers"]["pricecatcher"]


def _ensure_tracked_items_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tracked_items (
            food_id INTEGER NOT NULL,
            item_code BIGINT NOT NULL,
            factor DOUBLE DEFAULT 1.0,
            source VARCHAR DEFAULT 'pricecatcher',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (food_id, item_code)
        )
    """)


def get_item_mappings() -> dict:
    """All food -> PriceCatcher item mappings: config.yaml presets
    plus user-tracked items stored in the database."""
    mappings = {}
    for food_name, spec in _load_config().get("items", {}).items():
        mappings[food_name] = {"item_code": int(spec["item_code"]),
                               "factor": float(spec.get("factor", 1.0))}

    conn = get_connection()
    try:
        _ensure_tracked_items_table(conn)
        rows = conn.execute("""
            SELECT f.name, t.item_code, t.factor
            FROM tracked_items t JOIN foods f ON t.food_id = f.id
        """).fetchall()
        for name, code, factor in rows:
            mappings[name] = {"item_code": int(code), "factor": float(factor)}
    finally:
        conn.close()
    return mappings


CATALOG_MAX_AGE_DAYS = 7


def _catalog_file(force_refresh: bool = False) -> Path:
    """Ensure the item catalog is downloaded and reasonably fresh.

    Re-downloads automatically when older than CATALOG_MAX_AGE_DAYS so
    newly added KPDN items become searchable. On download failure the
    existing cached copy is kept.
    """
    import time
    cfg = _load_config()
    path = CACHE_DIR / "lookup_item.parquet"

    stale = (path.exists() and
             (time.time() - path.stat().st_mtime) > CATALOG_MAX_AGE_DAYS * 86400)
    if path.exists() and not stale and not force_refresh:
        return path

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        print("Downloading item catalog...")
        if _download(f"{cfg['base_url'].rstrip('/')}/lookup_item.parquet", tmp):
            tmp.replace(path)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        if not path.exists():
            raise
        print(f"[WARN] Catalog refresh failed ({e}) - using cached copy.")
    return path


def search_catalog(keyword: str, limit: int = 25,
                   force_refresh: bool = False) -> list:
    """Search the official PriceCatcher item catalog by keyword.

    Multi-word searches match items containing ALL the words in any order
    (e.g. 'bawang merah' finds 'BAWANG KECIL MERAH IMPORT (THAILAND)').
    Returns list of dicts: item_code, item, unit, item_group, item_category.
    """
    path = _catalog_file(force_refresh)
    words = [w for w in keyword.strip().split() if w]
    if not words:
        return []
    conditions = " AND ".join("item ILIKE ?" for _ in words)
    params = [str(path)] + [f"%{w}%" for w in words] + [limit]

    con = _duckdb.connect()
    try:
        rows = con.execute(f"""
            SELECT item_code, item, unit, item_group, item_category
            FROM read_parquet(?)
            WHERE {conditions}
            ORDER BY item
            LIMIT ?
        """, params).fetchall()
    finally:
        con.close()
    return [{"item_code": int(r[0]), "item": r[1], "unit": r[2],
             "group": r[3], "category": r[4]} for r in rows]


def _derive_factor_unit(unit_str: str) -> tuple:
    """Derive a unit-normalization factor from the catalog unit string.

    '10 kg' -> (0.1, 'kg'); '5 kg' -> (0.2, 'kg'); '1 liter' -> (1.0, 'liter');
    anything else (e.g. '550 g', '10 biji') is kept as-is with factor 1.0.
    """
    import re
    s = (unit_str or "").lower().replace(" ", "")
    m = re.match(r"^(\d+(?:\.\d+)?)(kg|liter|litre|l)$", s)
    if m:
        qty = float(m.group(1))
        unit = "liter" if m.group(2) in ("liter", "litre", "l") else "kg"
        if qty > 0:
            return (round(1.0 / qty, 6), unit)
    return (1.0, unit_str or "unit")


def track_item(item_code: int, food_name: str = None,
               category: str = "other", backfill: bool = True) -> dict:
    """Start tracking a PriceCatcher item: create the food in the DB if
    missing, register the mapping, and backfill history from cached files.

    The mapping lives in the tracked_items table, so weekly scheduled
    scrapes automatically include it from now on."""
    # Find the item in the catalog
    path = _catalog_file()
    con = _duckdb.connect()
    try:
        row = con.execute(
            "SELECT item, unit, item_group FROM read_parquet(?) WHERE item_code = ?",
            [str(path), item_code]).fetchall()
    finally:
        con.close()
    if not row:
        raise ValueError(f"Item code {item_code} not found in the PriceCatcher catalog.")

    catalog_name, catalog_unit, catalog_group = row[0]
    factor, unit = _derive_factor_unit(catalog_unit)
    if food_name is None:
        food_name = catalog_name.title()

    conn = get_connection()
    try:
        _ensure_tracked_items_table(conn)

        food_id = get_food_id(food_name, conn)
        created = False
        if food_id is None:
            food_id = conn.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM foods").fetchall()[0][0]
            conn.execute(
                "INSERT INTO foods (id, name, category, unit, is_custom) VALUES (?, ?, ?, ?, true)",
                [food_id, food_name, category or (catalog_group or "other").lower(), unit])
            created = True

        existing = conn.execute(
            "SELECT 1 FROM tracked_items WHERE food_id=? AND item_code=?",
            [food_id, item_code]).fetchall()
        if not existing:
            conn.execute(
                "INSERT INTO tracked_items (food_id, item_code, factor) VALUES (?, ?, ?)",
                [food_id, item_code, factor])
        conn.commit()
    finally:
        conn.close()

    result = {"food": food_name, "item_code": item_code, "item": catalog_name,
              "unit": unit, "factor": factor, "food_created": created,
              "imported": 0, "skipped": 0}

    if backfill:
        files = sorted(CACHE_DIR.glob("pricecatcher_*.parquet"))
        if not files:
            files = fetch_files(months_back=2)
        if files:
            records = aggregate_weekly(files, items={
                food_name: {"item_code": item_code, "factor": factor}})
            stored = store(records)
            result.update(stored)

    return result


def _download(url: str, dest: Path) -> bool:
    """Download a file; returns False on 404 (month not published yet)."""
    resp = requests.get(url, timeout=120, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) food-price-tracker/1.0"
    })
    if resp.status_code == 404:
        return False
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return True


def _month_list(months_back: int) -> list:
    """List of (year, month) tuples from current month going back."""
    today = date.today()
    out = []
    y, m = today.year, today.month
    for _ in range(months_back):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def fetch_files(months_back: int = 2) -> list:
    """Download lookup tables + monthly price files. Returns local file paths."""
    cfg = _load_config()
    base = cfg["base_url"].rstrip("/")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    premise_file = CACHE_DIR / "lookup_premise.parquet"
    if not premise_file.exists():
        print("Downloading premise lookup...")
        _download(f"{base}/lookup_premise.parquet", premise_file)

    # KPDN keeps appending new days to the CURRENT month's file (and may add
    # late readings to the PREVIOUS month), so those two must always be
    # re-downloaded even when a cached copy exists. Older months never change.
    today = date.today()
    fresh_months = {(today.year, today.month)}
    py, pm = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    fresh_months.add((py, pm))

    monthly_files, missed = [], 0
    for y, m in _month_list(months_back + 2):  # extra slack for unpublished months
        if len(monthly_files) >= months_back:
            break
        fname = f"pricecatcher_{y:04d}-{m:02d}.parquet"
        local = CACHE_DIR / fname
        must_refresh = (y, m) in fresh_months
        if local.exists() and not must_refresh:
            monthly_files.append(local)
            continue
        action = "Refreshing" if local.exists() else "Downloading"
        print(f"{action} {fname}...")
        # Download to a temp file first so a failed refresh keeps the old copy.
        tmp = local.with_suffix(".tmp")
        ok = False
        try:
            ok = _download(f"{base}/{fname}", tmp)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            print(f"  [WARN] {fname} download failed ({e})")
        if ok:
            tmp.replace(local)
            monthly_files.append(local)
            print(f"[OK] {fname} ({local.stat().st_size // 1024} KB)")
        else:
            tmp.unlink(missing_ok=True)
            if local.exists():
                # Refresh failed but we still have the older cached copy - use it.
                monthly_files.append(local)
                print(f"  using cached {fname}")
            else:
                missed += 1
                print(f"  {fname} not published yet, trying earlier month")
                if missed > 3:
                    break

    return monthly_files


def aggregate_weekly(monthly_files: list, items: dict = None) -> list:
    """Compute weekly average price per item per geography from parquet files.

    items: {food_name: {item_code, factor}} - defaults to all mappings
    (config.yaml presets + user-tracked items from the DB).
    Returns list of dicts: food, location, week_start, avg_price, samples.
    """
    if items is None:
        items = get_item_mappings()
    premise_file = str(CACHE_DIR / "lookup_premise.parquet")
    file_list = ", ".join(f"'{f}'" for f in monthly_files)

    con = _duckdb.connect()  # in-memory, separate from the main DB
    records = []

    for food_name, spec in items.items():
        item_code = int(spec["item_code"])
        factor = float(spec.get("factor", 1.0))

        for location, geo_filter in GEO_FILTERS.items():
            rows = con.execute(f"""
                SELECT
                    DATE_TRUNC('week', p.date) AS week_start,
                    AVG(p.price) AS avg_price,
                    COUNT(*) AS samples
                FROM read_parquet([{file_list}]) p
                JOIN read_parquet('{premise_file}') pr
                  ON CAST(p.premise_code AS BIGINT) = CAST(pr.premise_code AS BIGINT)
                WHERE p.item_code = ? AND p.price > 0 AND {geo_filter}
                GROUP BY 1
                ORDER BY 1
            """, [item_code]).fetchall()

            for week_start, avg_price, samples in rows:
                records.append({
                    "food": food_name,
                    "location": location,
                    "week_start": week_start if isinstance(week_start, date)
                                  else week_start.date(),
                    "price": round(float(avg_price) * factor, 4),
                    "samples": int(samples),
                })

    con.close()
    return records


def store(records: list) -> dict:
    """Upsert weekly averages into the main prices table.

    A week's average grows as KPDN appends more days to the current month's
    file, so an existing row for the same food/location/week is UPDATED when
    the recomputed price changed (e.g. the current week mid-update). Rows that
    are unchanged are skipped; brand-new weeks are inserted.
    """
    conn = get_connection()
    imported, updated, skipped = 0, 0, 0
    try:
        for rec in records:
            food_id = get_food_id(rec["food"], conn)
            location_id = get_location_id(rec["location"], conn)
            if food_id is None or location_id is None:
                continue

            notes = f"weekly avg of {rec['samples']} readings"
            existing = conn.execute(
                """SELECT id, price FROM prices
                   WHERE food_id=? AND location_id=? AND collected_date=?
                     AND price_type='retail'""",
                [food_id, location_id, rec["week_start"]]
            ).fetchall()
            if existing:
                row_id, old_price = existing[0]
                if round(float(old_price), 4) == round(float(rec["price"]), 4):
                    skipped += 1
                    continue
                conn.execute(
                    "UPDATE prices SET price=?, notes=? WHERE id=?",
                    [rec["price"], notes, row_id])
                updated += 1
                continue

            next_id = conn.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM prices"
            ).fetchall()[0][0]
            conn.execute("""
                INSERT INTO prices (id, food_id, location_id, price, currency,
                                    collected_date, source, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [next_id, food_id, location_id, rec["price"], "MYR",
                  rec["week_start"], "KPDN PriceCatcher", notes])
            imported += 1
        conn.commit()
    finally:
        conn.close()

    return {"imported": imported, "updated": updated, "skipped": skipped}


def premise_price_extremes(food_name: str, location: str = "Lahad Datu",
                           lookback_days: int = 7) -> dict:
    """Find the cheapest and dearest individual shop (premise) for a food.

    Reads the cached PriceCatcher parquet files directly (premise-level data
    that the weekly-average pipeline discards) and returns, for the most
    recent ~week of readings in the given geography, which shop charged the
    lowest price and which the highest. Useful as a "where to buy" reference.

    Returns a dict like:
      {"food": ..., "location": ..., "as_of": "2026-06-10",
       "low":  {"premise": ..., "type": ..., "price": 3.02},
       "high": {"premise": ..., "type": ..., "price": 9.43},
       "shops": 18}
    or {"available": False, "reason": ...} when nothing can be computed.
    """
    geo_filter = GEO_FILTERS.get(location)
    if geo_filter is None:
        return {"available": False, "reason": f"Unknown location '{location}'."}

    mappings = get_item_mappings()
    spec = mappings.get(food_name)
    if not spec:
        return {"available": False,
                "reason": f"No PriceCatcher item mapped for '{food_name}'."}
    item_code = int(spec["item_code"])
    factor = float(spec.get("factor", 1.0))

    premise_file = CACHE_DIR / "lookup_premise.parquet"
    files = sorted(CACHE_DIR.glob("pricecatcher_*.parquet"))[-2:]  # 2 newest months
    if not files or not premise_file.exists():
        return {"available": False, "reason": "No cached price files yet."}

    file_list = ", ".join(f"'{f}'" for f in files)
    pf = str(premise_file)
    con = _duckdb.connect()
    try:
        rows = con.execute(f"""
            WITH readings AS (
                SELECT pr.premise AS premise, pr.premise_type AS premise_type,
                       pc.price AS price, pc.date AS date
                FROM read_parquet([{file_list}]) pc
                JOIN read_parquet('{pf}') pr
                  ON CAST(pc.premise_code AS BIGINT) = CAST(pr.premise_code AS BIGINT)
                WHERE pc.item_code = ? AND pc.price > 0 AND {geo_filter}
            ),
            recent AS (
                SELECT * FROM readings
                WHERE date >= (SELECT MAX(date) FROM readings) - ?
            )
            SELECT premise, premise_type, AVG(price) AS avg_price,
                   (SELECT MAX(date) FROM recent) AS as_of
            FROM recent
            GROUP BY premise, premise_type
            ORDER BY avg_price
        """, [item_code, lookback_days]).fetchall()
    finally:
        con.close()

    if not rows:
        return {"available": False,
                "reason": "No recent premise-level readings for this item."}

    low, high = rows[0], rows[-1]
    as_of = low[3]
    return {
        "available": True,
        "food": food_name,
        "location": location,
        "as_of": as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of),
        "shops": len(rows),
        "low": {"premise": low[0], "type": low[1],
                "price": round(float(low[2]) * factor, 2)},
        "high": {"premise": high[0], "type": high[1],
                 "price": round(float(high[2]) * factor, 2)},
    }


def run(months_back: int = 2) -> dict:
    """Full pipeline: download, aggregate weekly, store."""
    files = fetch_files(months_back)
    if not files:
        return {"imported": 0, "skipped": 0,
                "message": "No PriceCatcher monthly files could be downloaded."}

    records = aggregate_weekly(files)
    result = store(records)
    result["message"] = (
        f"PriceCatcher: {result['imported']} new + {result.get('updated', 0)} "
        f"refreshed weekly prices ({result['skipped']} unchanged) "
        f"from {len(files)} monthly file(s)."
    )
    return result


if __name__ == "__main__":
    print(run()["message"])
