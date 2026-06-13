import duckdb
import os
import shutil
from pathlib import Path

# Recognised price layers (see prices.price_type column comment)
PRICE_TYPES = {
    "retail": "Retail (shelf price)",
    "wholesale": "Wholesale (market borong)",
    "international": "International benchmark",
    "import_unit": "Import unit value",
    "controlled": "Government ceiling price",
}

def get_database_path():
    """Get or create the data directory and return the database path."""
    data_dir = Path("./data")
    data_dir.mkdir(exist_ok=True)
    return str(data_dir / "prices.duckdb")

def initialize_database():
    """Create DuckDB database with schema if it doesn't exist."""
    db_path = get_database_path()
    conn = duckdb.connect(db_path)

    # Create sequence for prices table first
    conn.execute("CREATE SEQUENCE IF NOT EXISTS prices_seq START 1")

    # Create foods table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS foods (
            id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL UNIQUE,
            category VARCHAR NOT NULL,
            unit VARCHAR NOT NULL,
            is_custom BOOLEAN DEFAULT false,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create locations table with geographic hierarchy
    conn.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL UNIQUE,
            level INTEGER NOT NULL,
            parent_id INTEGER,
            country_code VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parent_id) REFERENCES locations(id)
        )
    """)

    # Create prices table.
    # price_type lets several price layers coexist for the same food/location/date:
    #   retail        - shelf price consumers pay (KPDN PriceCatcher)
    #   wholesale     - market wholesale price (FAMA, by state incl. Sabah)
    #   international  - global commodity benchmark (World Bank Pink Sheet, USD)
    #   import_unit    - average customs import unit value (DOSM external trade)
    #   controlled     - government festive ceiling price (KPDN Harga Kawalan)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY,
            food_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            price DECIMAL(10, 4) NOT NULL,
            currency VARCHAR DEFAULT 'MYR',
            collected_date DATE NOT NULL,
            price_type VARCHAR DEFAULT 'retail',
            source VARCHAR,
            notes VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (food_id) REFERENCES foods(id),
            FOREIGN KEY (location_id) REFERENCES locations(id),
            UNIQUE (food_id, location_id, collected_date, price_type)
        )
    """)

    # User-tracked PriceCatcher items (beyond the config.yaml presets).
    # Stored in the DB so the mapping travels with the portable folder.
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

    # Create price_analysis view for quick aggregations
    conn.execute("""
        CREATE VIEW IF NOT EXISTS price_analysis AS
        SELECT
            f.id as food_id,
            f.name as food_name,
            l.id as location_id,
            l.name as location_name,
            p.price_type as price_type,
            DATETRUNC('week', p.collected_date) as week_start,
            DATETRUNC('month', p.collected_date) as month_start,
            DATETRUNC('year', p.collected_date) as year_start,
            AVG(p.price) as avg_price,
            MIN(p.price) as min_price,
            MAX(p.price) as max_price,
            COUNT(*) as price_count
        FROM prices p
        JOIN foods f ON p.food_id = f.id
        JOIN locations l ON p.location_id = l.id
        GROUP BY f.id, f.name, l.id, l.name, p.price_type,
                 DATETRUNC('week', p.collected_date),
                 DATETRUNC('month', p.collected_date),
                 DATETRUNC('year', p.collected_date)
    """)

    # Create index for faster queries
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_food_location ON prices(food_id, location_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(collected_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_location_date ON prices(location_id, collected_date)")

    conn.close()

    # Apply migrations for databases created before a schema change
    migrate_database()

    print(f"[OK] Database initialized at {db_path}")


def migrate_database():
    """Idempotent migrations for older databases. Safe to call any time.

    Currently: adds the `price_type` column (and the wider UNIQUE key) to the
    prices table, backfilling existing rows. World Bank rows become
    'international'; everything else 'retail'. A one-time backup of the DB
    file is written before the table is rebuilt.
    """
    db_path = get_database_path()
    if not Path(db_path).exists():
        return

    conn = duckdb.connect(db_path)
    try:
        cols = [c[0] for c in conn.execute("DESCRIBE prices").fetchall()]
        if "price_type" in cols:
            return  # already migrated

        print("[..] Migrating prices table: adding price_type ...")
        # Safety backup before touching the table
        backup = db_path + ".bak-before-pricetype"
        if not Path(backup).exists():
            conn.close()
            shutil.copy2(db_path, backup)
            conn = duckdb.connect(db_path)
            print(f"[OK] Backup written: {backup}")

        # The view and indexes depend on prices; drop them before the rename
        # (DuckDB blocks ALTER/RENAME while dependents exist).
        conn.execute("DROP VIEW IF EXISTS price_analysis")
        conn.execute("DROP INDEX IF EXISTS idx_prices_food_location")
        conn.execute("DROP INDEX IF EXISTS idx_prices_date")
        conn.execute("DROP INDEX IF EXISTS idx_prices_location_date")
        conn.execute("DROP INDEX IF EXISTS idx_prices_type")
        conn.execute("ALTER TABLE prices RENAME TO prices_old")
        conn.execute("""
            CREATE TABLE prices (
                id INTEGER PRIMARY KEY,
                food_id INTEGER NOT NULL,
                location_id INTEGER NOT NULL,
                price DECIMAL(10, 4) NOT NULL,
                currency VARCHAR DEFAULT 'MYR',
                collected_date DATE NOT NULL,
                price_type VARCHAR DEFAULT 'retail',
                source VARCHAR,
                notes VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (food_id) REFERENCES foods(id),
                FOREIGN KEY (location_id) REFERENCES locations(id),
                UNIQUE (food_id, location_id, collected_date, price_type)
            )
        """)
        conn.execute("""
            INSERT INTO prices
                (id, food_id, location_id, price, currency, collected_date,
                 price_type, source, notes, created_at)
            SELECT id, food_id, location_id, price, currency, collected_date,
                   CASE WHEN source = 'World Bank Pink Sheet'
                        THEN 'international' ELSE 'retail' END,
                   source, notes, created_at
            FROM prices_old
        """)
        conn.execute("DROP TABLE prices_old")

        # Recreate dependent indexes + view
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_food_location ON prices(food_id, location_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(collected_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_location_date ON prices(location_id, collected_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_type ON prices(price_type)")
        conn.execute("""
            CREATE VIEW IF NOT EXISTS price_analysis AS
            SELECT
                f.id as food_id, f.name as food_name,
                l.id as location_id, l.name as location_name,
                p.price_type as price_type,
                DATETRUNC('week', p.collected_date) as week_start,
                DATETRUNC('month', p.collected_date) as month_start,
                DATETRUNC('year', p.collected_date) as year_start,
                AVG(p.price) as avg_price, MIN(p.price) as min_price,
                MAX(p.price) as max_price, COUNT(*) as price_count
            FROM prices p
            JOIN foods f ON p.food_id = f.id
            JOIN locations l ON p.location_id = l.id
            GROUP BY f.id, f.name, l.id, l.name, p.price_type,
                     DATETRUNC('week', p.collected_date),
                     DATETRUNC('month', p.collected_date),
                     DATETRUNC('year', p.collected_date)
        """)
        n = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        print(f"[OK] Migration complete: {n} prices now carry price_type.")
    finally:
        conn.close()


def load_default_data():
    """Load default foods and locations from config."""
    import yaml

    db_path = get_database_path()
    conn = duckdb.connect(db_path)

    # Load config
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Load foods
    foods = config.get("default_foods", [])
    for food in foods:
        try:
            conn.execute("""
                INSERT INTO foods (id, name, category, unit, is_custom)
                VALUES (?, ?, ?, ?, ?)
            """, [food['id'], food['name'], food['category'], food['unit'], food.get('is_custom', False)])
        except Exception as e:
            # Skip if already exists
            pass

    # Load locations
    locations = config.get("locations", [])
    for loc in locations:
        try:
            conn.execute("""
                INSERT INTO locations (id, name, level, parent_id, country_code)
                VALUES (?, ?, ?, ?, ?)
            """, [loc['id'], loc['name'], loc['level'], loc.get('parent_id'), loc.get('country_code')])
        except Exception as e:
            # Skip if already exists
            pass

    conn.commit()
    conn.close()
    print("[OK] Default data loaded")

if __name__ == "__main__":
    initialize_database()
    migrate_database()
    load_default_data()
