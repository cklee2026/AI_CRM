# Food Price Tracker - Implementation Status

**Current version: v2.0 — Phases 1-4 complete** (2026-06-10)

See [README.md](README.md) for full usage documentation.

## What's done

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | DuckDB schema, CLI, dashboard framework | ✅ |
| 2 | World Bank scraper, CSV import, trend analytics, scheduler | ✅ |
| 3 | KPDN PriceCatcher scraper (Malaysia/Sabah/Lahad Datu), spike alerts, seasonal/anomaly detection | ✅ |
| 4 | Dashboard v2 (8 pages incl. alerts, seasonal, in-UI price entry), custom foods/locations, email alerts, Windows .bat launchers | ✅ |

## Data in the database (all real, no demo data)

| Location | Source | Records | Coverage |
|----------|--------|---------|----------|
| International | World Bank Pink Sheet | 56 | monthly, 14 months |
| Malaysia | KPDN PriceCatcher | 366 | weekly, Jun 2025 - Jun 2026 |
| Sabah | KPDN PriceCatcher | 279 | weekly, Jun 2025 - Jun 2026 |
| Lahad Datu | KPDN PriceCatcher | 227 | weekly, Jun 2025 - Jun 2026 |

## Daily use

1. Double-click **`update_data.bat`** to fetch the latest prices + check alerts
2. Double-click **`start_dashboard.bat`** to browse charts
3. Record local market prices in the dashboard's **Add Price** page

## Known limitations

- PriceCatcher geographic levels are fixed to Malaysia/Sabah/Lahad Datu
  (user-added locations like Tawau accept manual entries only)
- World Bank "Chicken" commodity column name mismatch: 4/5 international items import
- Some Lahad Datu item gaps (premises don't stock every tracked brand)

## Remaining ideas (Phase 5)

- Extend PriceCatcher scraper to user-added districts
- PDF report export
- Docker packaging
