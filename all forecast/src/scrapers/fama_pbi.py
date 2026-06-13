"""FAMA wholesale/retail price scraper via the official Power BI dashboard.

FAMA's "PANDUAN HARGA HARIAN" daily price guide is published as a Power BI
report (the old sdvi2.fama.gov.my ASP system is offline). The data API is
locked behind Power BI's handshake (direct HTTP returns 403), so we drive a
real headless browser, which performs the legitimate handshake, set the
price level (Ladang/Borong/Runcit) and the NEGERI (state) slicer, then read
the rendered commodity table.

Levels:
    Ladang  -> farm gate price   (price_type 'wholesale' is NOT this)
    Borong  -> wholesale price    -> price_type 'wholesale'
    Runcit  -> retail price       -> price_type 'retail'

Requires: playwright + chromium
    pip install playwright
    python -m playwright install chromium

This is heavier than a normal HTTP scrape (launches a browser) so it runs as
its own CLI command (`scrape-fama`), not inside the fast update path.
"""
import re
from datetime import date, datetime

# The published report (FAMA Harga Pasaran Terkini embed)
REPORT_URL = ("https://app.powerbi.com/view?r=eyJrIjoiYjQxZGNjZDctZDlmNy00ZjU2"
              "LTgwZmUtMTI3Njk2NDkzZjUzIiwidCI6ImJhNzljNzM5LWZkYmEtNGM1My1hNTFi"
              "LWIwYTYxNGJhZTg3ZiIsImMiOjEwfQ%3D%3D")

# Horizontal centre (px) of each price-level tile at viewport width 1600.
# The tiles are image-buttons (no DOM text) so we click by position.
LEVEL_TILES = {"Ladang": (343, 350), "Borong": (787, 350), "Runcit": (1231, 350)}

LEVEL_PRICE_TYPE = {"Borong": "wholesale", "Runcit": "retail", "Ladang": "wholesale"}


class FamaScrapeError(Exception):
    pass


def _settle(page, ms=5000):
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


def _select_state(page, state):
    """Open the NEGERI slicer and pick `state` (scrolls the virtualised list)."""
    page.locator("[role=combobox][aria-label='negeri']").click()
    page.wait_for_timeout(2500)
    popup = page.locator(".slicer-dropdown-popup.focused .slicer-dropdown-content").first
    box = popup.bounding_box()
    if not box:
        raise FamaScrapeError("NEGERI dropdown did not open")
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    opt = page.locator(".slicerItemContainer", has_text=state)
    for _ in range(20):
        if opt.count() > 0:
            break
        page.mouse.wheel(0, 180)
        page.wait_for_timeout(400)
    if opt.count() == 0:
        raise FamaScrapeError(f"state '{state}' not found in NEGERI dropdown")
    opt.first.click()
    page.mouse.click(250, 250)   # click empty area to close the dropdown
    page.wait_for_timeout(5000)


def _read_table(page):
    """Parse the rendered commodity table into rows."""
    txt = page.inner_text("body").replace("\xa0", " ")
    rows = []
    for chunk in txt.split("Select Row")[1:]:
        lines = [l.strip() for l in chunk.splitlines() if l.strip()]
        if len(lines) >= 4 and re.match(r"^\d+(\.\d+)?$", lines[1]):
            rows.append({"commodity": lines[0], "price": float(lines[1]),
                         "grade": lines[2], "unit": lines[3]})
    return rows


def _read_update_date(page):
    """Extract 'Tarikh Kemaskini' (last-updated date) -> date object.

    The report prints the date as D/M/YYYY immediately before the
    'Tarikh Kemaskini' label; anchor on that so we don't pick a stray date.
    """
    txt = page.inner_text("body")
    # date that appears just before the "Tarikh Kemaskini" label
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})\s*\n?\s*Tarikh\s*Kemaskini",
                  txt, re.I)
    if not m:
        # fallback: last date anywhere on the page
        allm = re.findall(r"(\d{1,2})/(\d{1,2})/(\d{4})", txt)
        m = None
        if allm:
            d, mth, y = allm[-1]
            try:
                return date(int(y), int(mth), int(d))
            except ValueError:
                return date.today()
        return date.today()
    d, mth, y = m.group(1), m.group(2), m.group(3)
    try:
        return date(int(y), int(mth), int(d))
    except ValueError:
        return date.today()


def scrape_fama(level="Borong", state="SABAH", headless=True, timeout_ms=60000):
    """Scrape one (level, state) view of the FAMA price dashboard.

    Returns {"level", "state", "price_type", "date", "rows": [...]}.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise FamaScrapeError(
            "Playwright not installed. Run:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium")

    if level not in LEVEL_TILES:
        raise FamaScrapeError(f"level must be one of {list(LEVEL_TILES)}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_context(
                viewport={"width": 1600, "height": 1000}).new_page()
            page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(12000)   # let visuals render

            tx, ty = LEVEL_TILES[level]
            page.mouse.click(tx, ty)
            _settle(page, 6000)

            if state and state.upper() != "ALL":
                _select_state(page, state.upper())

            rows = _read_table(page)
            upd = _read_update_date(page)
        finally:
            browser.close()

    if not rows:
        raise FamaScrapeError(
            "No rows read - the report layout may have changed, or this "
            "(level, state) combination has no data.")

    return {"level": level, "state": state,
            "price_type": LEVEL_PRICE_TYPE[level],
            "date": upd, "rows": rows}


# ---------------------------------------------------------------------------
# Persist to the price database
# ---------------------------------------------------------------------------
def _food_name(commodity: str, grade: str) -> str:
    """Build a tidy food name; keep the grade only when it distinguishes rows
    (e.g. TELUR AYAM grades A/B/C). F.A.Q is the generic grade - drop it."""
    name = commodity.title().replace(" / ", " / ")
    if grade and grade.upper() not in ("F.A.Q", "FAQ", ""):
        name = f"{name} (Gred {grade})"
    return name


def save_to_db(result: dict, location: str = None) -> dict:
    """Insert scraped rows into the DB. Auto-creates foods (is_custom).
    Returns counts. Deduped by the prices UNIQUE key.
    """
    from src.database import get_connection, get_food_id, get_location_id

    loc = location or result["state"].title()   # 'SABAH' -> 'Sabah'
    ptype = result["price_type"]
    d = result["date"]

    conn = get_connection()
    created_foods, inserted, skipped = 0, 0, 0
    try:
        location_id = get_location_id(loc, conn)
        if location_id is None:
            raise FamaScrapeError(
                f"location '{loc}' not in DB - add it first "
                f"(add-location), or pass a known location.")

        for r in result["rows"]:
            fname = _food_name(r["commodity"], r["grade"])
            food_id = get_food_id(fname, conn)
            if food_id is None:
                nid = conn.execute(
                    "SELECT COALESCE(MAX(id),0)+1 FROM foods").fetchone()[0]
                unit = "dozen" if r["unit"].lower() == "biji" else r["unit"].lower()
                conn.execute(
                    "INSERT INTO foods (id, name, category, unit, is_custom) "
                    "VALUES (?, ?, 'fama', ?, true)", [nid, fname, unit])
                food_id = nid
                created_foods += 1

            dup = conn.execute(
                "SELECT 1 FROM prices WHERE food_id=? AND location_id=? "
                "AND collected_date=? AND price_type=?",
                [food_id, location_id, d, ptype]).fetchone()
            if dup:
                skipped += 1
                continue
            pid = conn.execute(
                "SELECT COALESCE(MAX(id),0)+1 FROM prices").fetchone()[0]
            conn.execute(
                "INSERT INTO prices (id, food_id, location_id, price, currency, "
                "collected_date, price_type, source, notes) "
                "VALUES (?, ?, ?, ?, 'MYR', ?, ?, 'FAMA', ?)",
                [pid, food_id, location_id, r["price"], d, ptype,
                 f"{result['level']} {result['state']}"])
            inserted += 1
        conn.commit()
    finally:
        conn.close()

    return {"created_foods": created_foods, "inserted": inserted,
            "skipped": skipped, "location": loc, "price_type": ptype,
            "date": str(d), "total_rows": len(result["rows"])}
