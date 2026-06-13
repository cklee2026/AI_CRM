import sys
import click
from datetime import datetime, date

# Windows consoles may use a legacy codepage that cannot encode Chinese
# characters; replace unencodable characters instead of crashing.
try:
    sys.stdout.reconfigure(errors='replace')
except Exception:
    pass
from pathlib import Path
from tabulate import tabulate
from src.database.schema import initialize_database, load_default_data
from src.database import (
    add_price, list_foods, list_locations, get_prices,
    get_price_statistics, export_to_csv
)

@click.group()
def cli():
    """Food Price Tracker - Track food prices across regions."""
    pass

@cli.command()
def init():
    """Initialize the database with schema and default data."""
    click.echo("Initializing database...")
    initialize_database()
    load_default_data()
    click.echo("Database ready to use!")

@cli.command()
@click.option('--food', prompt='Food name', help='Name of the food item')
@click.option('--location', prompt='Location name', help='Name of the location')
@click.option('--price', prompt='Price', type=float, help='Price in MYR')
@click.option('--date', type=click.DateTime(formats=['%Y-%m-%d']),
              default=None, help='Date (YYYY-MM-DD, default: today)')
@click.option('--source', default=None, help='Data source (market name, website, etc.)')
@click.option('--notes', default=None, help='Additional notes (reason for price change, etc.)')
def add(food, location, price, date, source, notes):
    """Add a price entry."""
    try:
        collected_date = date.date() if date else None
        add_price(food, location, price, collected_date, source, notes)
    except ValueError as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

@cli.command()
@click.option('--food', default=None, help='Filter by food name')
@click.option('--location', default=None, help='Filter by location')
@click.option('--start-date', type=click.DateTime(formats=['%Y-%m-%d']),
              default=None, help='Start date (YYYY-MM-DD)')
@click.option('--end-date', type=click.DateTime(formats=['%Y-%m-%d']),
              default=None, help='End date (YYYY-MM-DD)')
@click.option('--limit', type=int, default=50, help='Limit results')
def list_prices(food, location, start_date, end_date, limit):
    """List prices with optional filters."""
    try:
        start = start_date.date() if start_date else None
        end = end_date.date() if end_date else None

        prices = get_prices(food, location, start, end)
        prices = prices[:limit]

        if not prices:
            click.echo("No prices found.")
            return

        table_data = [
            [p['food'], p['location'], f"{p['price']:.2f}", p['currency'],
             p['date'], p['source'] or '-', p['notes'] or '-']
            for p in prices
        ]

        headers = ['Food', 'Location', 'Price', 'Currency', 'Date', 'Source', 'Notes']
        click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))
    except Exception as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

@cli.command()
@click.option('--food', prompt='Food name', help='Name of the food item')
@click.option('--location', prompt='Location name', help='Name of the location')
def stats(food, location):
    """Get price statistics for a food in a location."""
    try:
        stats = get_price_statistics(food, location)
        if not stats:
            click.echo("No data found for this combination.")
            return

        click.echo(f"\nPrice Statistics: {stats['food']} @ {stats['location']}")
        click.echo(f"   Count: {stats['count']} entries")
        click.echo(f"   Average: MYR {stats['avg_price']:.2f}" if stats['avg_price'] else "   Average: N/A")
        click.echo(f"   Range: MYR {stats['min_price']:.2f} - {stats['max_price']:.2f}"
                   if stats['min_price'] else "   Range: N/A")
        click.echo(f"   First: {stats['first_date']}")
        click.echo(f"   Last: {stats['last_date']}\n")
    except ValueError as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

@cli.command()
def foods():
    """List all available foods."""
    try:
        food_list = list_foods()
        if not food_list:
            click.echo("No foods found.")
            return

        table_data = [[f['id'], f['name'], f['category'], f['unit']] for f in food_list]
        headers = ['ID', 'Name', 'Category', 'Unit']
        click.echo("\nAvailable Foods:")
        click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))
    except Exception as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

@cli.command()
def locations():
    """List all locations."""
    try:
        loc_list = list_locations()
        if not loc_list:
            click.echo("No locations found.")
            return

        table_data = [[l['id'], l['name'], f"Level {l['level']}", l['parent_id'] or '-']
                      for l in loc_list]
        headers = ['ID', 'Name', 'Level', 'Parent']
        click.echo("\nAvailable Locations:")
        click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))
    except Exception as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

@cli.command()
@click.option('--output', default='prices_export.csv', help='Output filename')
@click.option('--food', default=None, help='Filter by food name')
@click.option('--location', default=None, help='Filter by location')
def export(output, food, location):
    """Export prices to CSV."""
    try:
        export_to_csv(output, food, location)
    except Exception as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

@cli.command()
def dashboard():
    """Launch the Streamlit dashboard."""
    import subprocess
    import sys
    click.echo("Launching dashboard...")
    subprocess.run([sys.executable, '-m', 'streamlit', 'run', 'src/visualization/dashboards.py'])

@cli.command(name='import-csv')
@click.argument('filepath')
@click.option('--update', is_flag=True, help='Update existing entries instead of skipping duplicates')
def import_csv_cmd(filepath, update):
    """Bulk import prices from a CSV file (columns: food, location, price, date)."""
    from src.importer import import_csv
    try:
        result = import_csv(filepath, skip_duplicates=not update)
        click.echo(f"[OK] Imported: {result['imported']}, skipped: {result['skipped']}")
        for err in result['errors'][:20]:
            click.echo(click.style(f"  {err}", fg='yellow'))
        if len(result['errors']) > 20:
            click.echo(f"  ... and {len(result['errors']) - 20} more errors")
    except Exception as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

@cli.command()
@click.option('--output', default='import_template.csv', help='Template filename')
def template(output):
    """Create a CSV template for bulk import."""
    from src.importer import create_template_csv
    create_template_csv(output)

@cli.command()
@click.option('--months', default=14, help='How many months of history to fetch')
def scrape(months):
    """Run the World Bank scraper to fetch international commodity prices."""
    from src.scrapers import world_bank
    try:
        result = world_bank.run(months_back=months)
        click.echo(f"[OK] {result['message']}")
    except Exception as e:
        click.echo(click.style(f"[ERROR] Scrape failed: {e}", fg='red'))

@cli.command(name='analyze-price')
@click.option('--food', prompt='Food name', help='Name of the food item')
@click.option('--location', prompt='Location name', help='Name of the location')
@click.option('--price-type', 'price_type', default=None,
              type=click.Choice(['retail', 'wholesale', 'international',
                                  'import_unit', 'controlled']),
              help='Restrict to one price layer (default: all)')
@click.option('--intl', default=None,
              help='International commodity to test as a driver (lagged correlation)')
@click.option('--lang', type=click.Choice(['zh', 'en']), default='zh')
def analyze_price_cmd(food, location, price_type, intl, lang):
    """Formal OFFLINE price analysis (no AI, no internet) - explains why a
    price is moving using statistics computed from your local data."""
    from src.analytics.price_analysis import analyze_price
    try:
        rep = analyze_price(food, location, price_type=price_type, intl_food=intl)
        if not rep['ok']:
            click.echo("No data for this selection.")
            return
        click.echo(f"\nPrice Analysis: {rep['food']} @ {rep['location']} "
                   f"[{rep['price_type']}]")
        click.echo(f"  Latest {rep['latest']:.2f} ({rep['latest_date']}) | "
                   f"range {rep['min']:.2f}-{rep['max']:.2f}\n")
        badge = {'high': '[H]', 'medium': '[M]', 'low': '[.]'}
        for fd in rep['findings']:
            click.echo(f"  {badge.get(fd['confidence'],'')} {fd[lang]}")
        if intl and (not rep['intl_driver'] or
                     rep['intl_driver']['correlation'] is None):
            click.echo("\n  (International driver not computable: no overlapping "
                       "dates with the chosen international series.)")
    except Exception as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

@cli.command()
@click.option('--food', prompt='Food name', help='Name of the food item')
@click.option('--location', prompt='Location name', help='Name of the location')
@click.option('--period', type=click.Choice(['week', 'month', 'year']), default='month',
              help='Aggregation period')
def analyze(food, location, period):
    """Analyze price trends: up/down direction, % change, and recorded reasons."""
    from src.analytics.trends import get_trend_report, get_period_summary
    try:
        report = get_trend_report(food, location)
        if not report:
            click.echo("No data found for this combination.")
            return

        click.echo(f"\nTrend Report: {report['food']} @ {report['location']}")
        click.echo(f"   Latest: MYR {report['latest_price']:.2f} ({report['latest_date']})")
        for label, key in [("1 week", "change_1w_pct"), ("1 month", "change_1m_pct"),
                           ("1 year", "change_1y_pct")]:
            val = report[key]
            if val is None:
                click.echo(f"   Change {label}: not enough history")
            else:
                arrow = "UP" if val > 0 else ("DOWN" if val < 0 else "FLAT")
                click.echo(f"   Change {label}: {val:+.2f}% [{arrow}]")
        if report['volatility_pct'] is not None:
            click.echo(f"   Volatility: {report['volatility_pct']:.2f}%")
        click.echo(f"   Data points: {report['data_points']}")

        if report['recent_reasons']:
            click.echo("\n   Recorded reasons for price moves:")
            for r in report['recent_reasons']:
                click.echo(f"   - {r['date']}: {r['note']} (price {r['price']:.2f})")

        summary = get_period_summary(food, location, period)
        if not summary.empty:
            click.echo(f"\nBy {period}:")
            table_data = [
                [str(row['period_start'])[:10], f"{row['avg_price']:.2f}",
                 f"{row['min_price']:.2f}", f"{row['max_price']:.2f}",
                 f"{row['change_pct']:+.1f}%" if pd_notna(row['change_pct']) else '-',
                 row['direction'] if pd_notna(row['change_pct']) else '-',
                 (row['notes'] or '-') if 'notes' in row else '-']
                for _, row in summary.iterrows()
            ]
            headers = ['Period', 'Avg', 'Min', 'Max', 'Change', 'Trend', 'Reasons']
            click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))
    except Exception as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

def pd_notna(value):
    import pandas as pd
    return pd.notna(value)

@cli.command()
def schedule():
    """Start the automated scraper scheduler (runs until Ctrl+C)."""
    from src.scheduler import start
    start()

@cli.command(name='scrape-malaysia')
@click.option('--months', default=2, help='How many monthly files to fetch')
def scrape_malaysia(months):
    """Fetch Malaysia/Sabah/Lahad Datu prices from KPDN PriceCatcher (data.gov.my)."""
    from src.scrapers import pricecatcher
    try:
        result = pricecatcher.run(months_back=months)
        click.echo(f"[OK] {result['message']}")
    except Exception as e:
        click.echo(click.style(f"[ERROR] PriceCatcher scrape failed: {e}", fg='red'))

@cli.command(name='scrape-fama')
@click.option('--level', default='Borong',
              type=click.Choice(['Borong', 'Runcit', 'Ladang']),
              help='Price level: Borong=wholesale, Runcit=retail, Ladang=farm')
@click.option('--state', default='SABAH', help='State (NEGERI), e.g. SABAH')
@click.option('--location', default=None,
              help='DB location to store under (defaults to the state name)')
@click.option('--show', is_flag=True, help='Just print rows, do not save')
def scrape_fama(level, state, location, show):
    """Scrape FAMA wholesale/retail prices via the official Power BI dashboard.

    Needs playwright + chromium (pip install playwright; python -m playwright
    install chromium). Drives a headless browser, so it is slower than the
    other scrapers - run it on its own, not in the fast update path.
    """
    from src.scrapers.fama_pbi import scrape_fama as run_fama, save_to_db
    try:
        click.echo(f"[..] Scraping FAMA {level} / {state} (launching browser)...")
        res = run_fama(level=level, state=state)
        click.echo(f"[OK] {len(res['rows'])} commodities, "
                   f"updated {res['date']}, type={res['price_type']}")
        if show:
            table = [[r['commodity'], f"{r['price']:.2f}", r['grade'], r['unit']]
                     for r in res['rows']]
            click.echo(tabulate(table, headers=['Komoditi', 'RM', 'Gred', 'Unit'],
                                tablefmt='grid'))
            return
        summary = save_to_db(res, location=location)
        click.echo(f"[OK] saved to '{summary['location']}' as "
                   f"{summary['price_type']}: {summary['inserted']} inserted, "
                   f"{summary['skipped']} already present, "
                   f"{summary['created_foods']} new foods.")
    except Exception as e:
        click.echo(click.style(f"[ERROR] FAMA scrape failed: {e}", fg='red'))

@cli.command()
@click.option('--threshold', type=float, default=None,
              help='Alert threshold in % (default from config.yaml)')
def alerts(threshold):
    """Check for price spikes and log/send alerts."""
    from src.alerts import run as run_alerts
    try:
        spikes = run_alerts(threshold)
        if not spikes:
            click.echo("No price spikes detected.")
            return
        table_data = [
            [s['direction'], s['food'], s['location'],
             f"{s['prev_price']:.2f}", f"{s['cur_price']:.2f}",
             f"{s['change_pct']:+.1f}%", s['cur_date']]
            for s in spikes
        ]
        headers = ['Dir', 'Food', 'Location', 'Prev', 'Now', 'Change', 'Date']
        click.echo(f"\n{len(spikes)} price spike(s) detected:")
        click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))
        click.echo("Alerts logged to data/alerts_log.csv")
    except Exception as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

@cli.command()
@click.option('--food', prompt='Food name', help='Name of the food item')
@click.option('--location', prompt='Location name', help='Name of the location')
def seasonal(food, location):
    """Show seasonal price patterns and detect anomalies."""
    from src.analytics.seasonal import seasonal_index, detect_anomalies
    try:
        idx = seasonal_index(food, location)
        if idx.empty:
            click.echo("Not enough data for seasonal analysis.")
        else:
            click.echo(f"\nSeasonal pattern: {food} @ {location}")
            table_data = [
                [row['month_name'], f"{row['avg_price']:.2f}",
                 f"{row['index']:.3f}", row['reading'], row['samples']]
                for _, row in idx.iterrows()
            ]
            headers = ['Month', 'Avg Price', 'Index', 'Reading', 'Samples']
            click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))
            click.echo("Index > 1.0 = typically expensive month; < 1.0 = typically cheap")

        anomalies = detect_anomalies(food, location)
        if anomalies.empty:
            click.echo("\nNo anomalies detected (or not enough data points).")
        else:
            click.echo(f"\n{len(anomalies)} anomalous price(s) detected:")
            table_data = [
                [str(row['date'])[:10], f"{row['price']:.2f}",
                 f"{row['rolling_avg']:.2f}", f"{row['z_score']:+.2f}",
                 row['direction'], row['notes'] or '-']
                for _, row in anomalies.iterrows()
            ]
            headers = ['Date', 'Price', 'Rolling Avg', 'Z-score', 'Type', 'Notes']
            click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))
    except Exception as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

@cli.command(name='add-food')
@click.option('--name', prompt='Food name', help='Name of the new food item')
@click.option('--category', prompt='Category',
              type=click.Choice(['grains', 'oils', 'proteins', 'vegetables', 'dairy', 'fruits', 'other']),
              help='Food category')
@click.option('--unit', prompt='Unit (kg/liter/dozen/piece)', help='Unit of measurement')
def add_food_cmd(name, category, unit):
    """Add a custom food item to track."""
    from src.database import add_food
    try:
        add_food(name, category, unit)
    except ValueError as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

@cli.command(name='add-location')
@click.option('--name', prompt='Location name', help='Name of the new location')
@click.option('--level', prompt='Level (0=Intl, 1=National, 2=State, 3=City/District)',
              type=int, help='Geographic level')
@click.option('--parent', default=None, help='Parent location name (e.g. Sabah)')
def add_location_cmd(name, level, parent):
    """Add a custom location to track."""
    from src.database import add_location
    try:
        add_location(name, level, parent)
    except ValueError as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

@cli.command(name='search-items')
@click.argument('keyword')
@click.option('--limit', default=25, help='Max results')
def search_items(keyword, limit):
    """Search the official KPDN item catalog (thousands of items)."""
    from src.scrapers.pricecatcher import search_catalog
    try:
        results = search_catalog(keyword, limit)
        if not results:
            click.echo(f"No items matching '{keyword}'. Try a Malay keyword "
                       "(e.g. BERAS=rice, IKAN=fish, SUSU=milk, DAGING=beef).")
            return
        table_data = [[r['item_code'], r['item'], r['unit'], r['group'] or '-']
                      for r in results]
        headers = ['Code', 'Item', 'Unit', 'Group']
        click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))
        click.echo("\nTrack one with:  python main.py track-item --code <Code>")
    except Exception as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

@cli.command(name='track-item')
@click.option('--code', type=int, prompt='Item code', help='PriceCatcher item code (from search-items)')
@click.option('--name', default=None, help='Custom food name (default: catalog name)')
@click.option('--category', default='other', help='Food category')
@click.option('--no-backfill', is_flag=True, help='Skip importing history now')
def track_item_cmd(code, name, category, no_backfill):
    """Track a catalog item: auto-create the food in the DB and backfill history."""
    from src.scrapers.pricecatcher import track_item
    try:
        result = track_item(code, name, category, backfill=not no_backfill)
        click.echo(f"[OK] Tracking '{result['item']}' as food '{result['food']}' "
                   f"(per {result['unit']}, factor {result['factor']})")
        if result['food_created']:
            click.echo("     Food was created in the database.")
        if not no_backfill:
            click.echo(f"     Backfilled {result['imported']} weekly prices "
                       f"({result['skipped']} already existed).")
        click.echo("     Weekly scheduled scrapes will now include this item automatically.")
    except Exception as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

@cli.command()
@click.option('--food', prompt='Food name', help='Name of the food item')
@click.option('--location', prompt='Location name', help='Name of the location')
@click.option('--periods', default=4, help='How many periods ahead')
@click.option('--period', type=click.Choice(['week', 'month']), default='week',
              help='Forecast by week or month')
@click.option('--lang', type=click.Choice(['en', 'zh']), default='en',
              help='Language for the explanation remarks')
def forecast(food, location, periods, period, lang):
    """Forecast future prices from historical data, with reasoning."""
    from src.analytics.forecast import forecast_prices
    try:
        result = forecast_prices(food, location, periods, period)
        meta = result['meta']
        last = result['history'].iloc[-1]

        click.echo(f"\nForecast: {food} @ {location}")
        click.echo(f"   Method: {meta['method']} ({meta['points_used']} {period}s of history)")
        click.echo(f"   Last actual: {last['price']:.2f} ({str(last['date'])[:10]})\n")

        table_data = [
            [str(row['date'])[:10], f"{row['forecast']:.2f}",
             f"{row['lo']:.2f} - {row['hi']:.2f}"]
            for _, row in result['forecast'].iterrows()
        ]
        headers = [f'{period.title()} starting', 'Forecast', '95% range']
        click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))

        click.echo("\nWhy this forecast:" if lang == 'en' else "\n预测依据:")
        for remark in result['explanations']:
            click.echo(f"  * {remark[lang]}")
    except ValueError as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))
    except Exception as e:
        click.echo(click.style(f"[ERROR] {e}", fg='red'))

if __name__ == '__main__':
    cli()
