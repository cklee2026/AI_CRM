# Food Price Tracker 🍎

An automated system to track food prices across geographic regions (International → Malaysia → Sabah → Lahad Datu) with historical data analysis and interactive visualizations.

## Features

- ✅ **Manual & Automated Data Collection**: Add prices via CLI or scheduled scrapers
- ✅ **Portable Database**: DuckDB database lives in the `data/` folder - copy and go
- ✅ **Multi-level Geographic Tracking**: International → Malaysia → Sabah → Lahad Datu
- ✅ **Interactive Dashboard**: Streamlit-based visualizations
- ✅ **Price Analysis**: Trends, regional comparisons, volatility analysis
- ✅ **Multiple Chart Types**: Line charts, bar charts, heatmaps
- ✅ **CSV Export**: Download price data anytime

## Quick Start (Windows - easiest)

Double-click these files:
- **`update_data.bat`** - fetch latest Malaysian + international prices and check alerts
- **`start_dashboard.bat`** - open the dashboard in your browser

## Quick Start (command line)

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Initialize Database

```bash
python main.py init
```

This creates the DuckDB database and loads default food items and locations.

### 3. Add Price Data

**Manual entry:**
```bash
python main.py add
# Or with all options:
python main.py add --food "Rice (Long Grain)" --location "Lahad Datu" --price 3.50 --date 2026-06-10 --source "Local Market" --notes "Supply good"
```

**Bulk import from CSV:**
- Prepare a CSV file with columns: `food`, `location`, `price`, `currency`, `date`, `source`, `notes`
- (Feature coming in Phase 2)

### 4. View Prices

**List prices:**
```bash
python main.py list-prices
# Filter by food: python main.py list-prices --food "Rice (Long Grain)"
# Filter by location: python main.py list-prices --location "Lahad Datu"
# Filter by date range: python main.py list-prices --start-date 2026-05-01 --end-date 2026-06-10
```

**View statistics:**
```bash
python main.py stats --food "Rice (Long Grain)" --location "Lahad Datu"
```

### 5. Launch Dashboard

```bash
python main.py dashboard
```

Opens an interactive Streamlit dashboard at `http://localhost:8501`

### 6. Available Foods & Locations

```bash
python main.py foods       # List all foods
python main.py locations   # List all locations
```

### 7. Export Data

```bash
python main.py export --output prices.csv
# Filter: python main.py export --food "Rice (Long Grain)" --location "Lahad Datu"
```

## Project Structure

```
food-price-tracker/
├── data/                    # DuckDB database (portable)
│   └── prices.duckdb
├── src/
│   ├── database/           # Database connection & schema
│   │   ├── db.py          # Query functions
│   │   ├── schema.py      # Database initialization
│   │   └── __init__.py
│   ├── visualization/      # Dashboard & charts
│   │   ├── dashboards.py  # Streamlit dashboard
│   │   ├── charts.py      # Plotly chart generation
│   │   └── __init__.py
│   ├── cli.py             # Command-line interface
│   └── __init__.py
├── config.yaml            # Food items & locations config
├── main.py               # Entry point
├── requirements.txt
└── README.md
```

## Database Schema

### foods
- `id`: Unique identifier
- `name`: Food name (e.g., "Rice (Long Grain)")
- `category`: Category (grains, oils, proteins, vegetables, dairy)
- `unit`: Unit of measurement (kg, liter, dozen)
- `is_custom`: Whether user-defined

### locations
- `id`: Unique identifier
- `name`: Location name
- `level`: Geographic hierarchy (0=International, 1=National, 2=State, 3=City)
- `parent_id`: Parent location reference
- `country_code`: ISO country code (MY for Malaysia)

### prices
- `id`: Unique identifier
- `food_id`: Reference to foods
- `location_id`: Reference to locations
- `price`: Price amount
- `currency`: Currency code (MYR, USD, etc.)
- `collected_date`: Date price was recorded
- `source`: Data source (market name, website, etc.)
- `notes`: Additional notes (reason for price change, etc.)

## Dashboard Pages

### Overview
- KPI cards showing latest prices and week-over-week changes
- Price heatmap (Food × Location matrix)

### Trend Analysis
- Time-series line chart for selected food
- Price statistics (latest, average, min, max)
- Week/month/year aggregation table with UP/DOWN trends and reasons

### Regional Comparison
- Bar chart comparing prices across regions
- Detailed comparison table

### Report Builder
- Build your own visual report: pick any foods, any locations
  (national / state / district), date range and aggregation period
- 7 chart types: Line, Area, Bar, Pie (basket cost share), Box
  (price distribution), Scatter, Histogram
- Download the chart as interactive HTML or the data as CSV

### Seasonal & Anomalies
- Seasonal index chart: which months are typically expensive/cheap
- Z-score anomaly detection with adjustable sensitivity

### Price Alerts
- Live spike detection with adjustable threshold
- Full alert history from data/alerts_log.csv

### Heatmap
- Interactive heatmap, pick any foods x locations

### Add Price
- Form to record prices you see at local markets - no command line needed

### Data
- Full data table with filtering and CSV download

## Custom Foods & Locations

```bash
python main.py add-food --name "Bananas (Berangan)" --category fruits --unit kg
python main.py add-location --name "Tawau" --level 3 --parent "Sabah"
```

## Portability

The entire system is designed to be portable:

1. **Database**: `data/prices.duckdb` is a single file
2. **Configuration**: `config.yaml` contains food and location definitions
3. **Folder structure**: Self-contained in the project directory

**To move to another computer:**
```bash
# Copy the entire project folder
cp -r food-price-tracker /path/to/new/location

# Install dependencies on new machine
pip install -r requirements.txt

# Use immediately - no setup needed!
python main.py list-prices
python main.py dashboard
```

## Configuration

Edit `config.yaml` to:
- Add new food items
- Add new locations
- Configure scraper schedules
- Change dashboard theme

## Command Reference

| Command | Description |
|---------|-------------|
| `init` | Initialize database |
| `add` | Add a price entry |
| `list-prices` | View prices with filters |
| `stats` | Get price statistics |
| `analyze` | Trend analysis: up/down %, by week/month/year, with reasons |
| `forecast` | Predict future prices by week or month |
| `seasonal` | Seasonal patterns + anomaly detection |
| `alerts` | Detect price spikes, log and notify |
| `search-items` | Search the official KPDN item catalog |
| `track-item` | Track a catalog item: auto-create food + backfill history |
| `scrape` | Fetch international prices from World Bank Pink Sheet |
| `scrape-malaysia` | Fetch Malaysia/Sabah/Lahad Datu prices from KPDN PriceCatcher |
| `import-csv` | Bulk import historical prices from CSV |
| `template` | Generate a CSV template for bulk import |
| `schedule` | Start automated weekly scraping (runs until Ctrl+C) |
| `foods` | List available foods |
| `locations` | List available locations |
| `export` | Export prices to CSV |
| `dashboard` | Launch Streamlit dashboard |

## Data Collection Workflows

### Malaysian official prices (KPDN PriceCatcher) - recommended
```bash
python main.py scrape-malaysia --months 13   # backfill 1 year of weekly prices
```
Pulls official government price data from data.gov.my for **Malaysia,
Sabah, and Lahad Datu** (weekly averages across local premises - Lahad Datu
has 31 monitored premises). Covers 8 of the 10 tracked foods.

### Automated international prices (World Bank)
```bash
python main.py scrape --months 14    # fetch ~14 months of history
python main.py schedule              # keep running for weekly auto-updates
```

### Price spike alerts
```bash
python main.py alerts                # uses threshold from config.yaml (10%)
python main.py alerts --threshold 5  # custom threshold
```
Alerts print to console and append to `data/alerts_log.csv`. To get
Telegram notifications, set `alerts.telegram` in `config.yaml`.

### Seasonal patterns & anomaly detection
```bash
python main.py seasonal --food "Tomatoes" --location "Lahad Datu"
```
Shows which calendar months are typically expensive/cheap, plus
z-score-based anomaly detection for unusual spikes or drops.

### Track any item from the official catalog
```bash
python main.py search-items "IKAN"           # search (Malay keywords work best)
python main.py track-item --code 1476 --name "Fish (Ikan Kembung)" --category proteins
```
Tracking an item auto-creates the food in the database, backfills a year
of weekly history from cached data, and includes it in all future
scheduled scrapes. Also available in the dashboard ("Track New Item" page).

### Price forecasting
```bash
python main.py forecast --food "Tomatoes" --location "Lahad Datu" --periods 4 --period week
python main.py forecast --food "Tomatoes" --location "Lahad Datu" --periods 3 --period month
```
Predicts future prices using linear trend + monthly seasonality with a
95% confidence range. Also available as a dashboard page with charts.

Every forecast comes with **evidence-based remarks** explaining WHY
(bilingual English / 中文): data basis, trend direction with actual %,
recent momentum vs the longer trend, seasonal adjustment for the target
months, volatility assessment, unusual-latest-price warnings, and any
recorded market reasons. Use `--lang zh` for Chinese remarks in the CLI.

### Optional AI market analysis (bring your own key)
Open the dashboard **AI Settings** page, choose a provider (DeepSeek
preset, or any OpenAI-compatible endpoint), type the model name
(free text - e.g. `deepseek-chat`), paste your API key, Test, Save,
and toggle ON. The Forecast page then gets a "Generate AI market
analysis" button that writes a plain-language report from the real
statistics.

Current DeepSeek models (per api-docs.deepseek.com): `deepseek-v4-flash`
(default) and `deepseek-v4-pro`; the old `deepseek-chat`/`deepseek-reasoner`
are deprecated 2026-07-24 and are migrated automatically.

Budget protection: when the provider reports your balance/token quota
is exhausted (DeepSeek error 402 余额不足), AI analysis **turns off
automatically** and a notice appears on the Settings and Forecast pages
until you top up and re-enable it. Token usage is tracked on the
Settings page.

Key security: on Windows the API key is encrypted with **DPAPI**, bound
to your Windows user account - `data/ai_settings.json` never contains
the plaintext key, and the encrypted blob cannot be decrypted on another
computer or by another user. After moving the folder to a new PC,
re-enter the key once in AI Settings.

### Bulk historical import (local prices)
```bash
python main.py template              # creates import_template.csv
# fill in your historical prices, then:
python main.py import-csv my_prices.csv
```

### Trend analysis
```bash
python main.py analyze --food "Rice (Long Grain)" --location "Lahad Datu" --period month
# period can be: week, month, year
```

## Roadmap (Phase 4+)

- [x] KPDN PriceCatcher scraper (Malaysia/Sabah/Lahad Datu) - DONE
- [x] Price spike alerts (console/CSV/Telegram) - DONE
- [x] Anomaly detection & seasonal patterns - DONE
- [ ] User-defined food items & locations via UI
- [ ] Email alerts
- [ ] Docker containerization

## Troubleshooting

**"Database not initialized"**
```bash
python main.py init
```

**"Food not found"**
Check available foods: `python main.py foods`

**"Location not found"**
Check available locations: `python main.py locations`

**Dashboard won't start**
```bash
pip install --upgrade streamlit plotly
python main.py dashboard
```

## License

MIT

## Support

For issues or questions, refer to the plan file at `.claude/plans/lahad-datu-1-chart-sunny-nest.md`
