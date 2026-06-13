"""Automated scheduled data collection using APScheduler.

Run with:  python main.py schedule
Keeps running in the terminal; press Ctrl+C to stop.

Schedules (enable/disable in config.yaml):
- KPDN PriceCatcher (Malaysia/Sabah/Lahad Datu): weekly, Tuesdays 08:00
- World Bank Pink Sheet (International): weekly, Mondays 08:00
- Price spike alert check: runs after each scrape
"""
import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger


def _check_alerts():
    from src.alerts import run as run_alerts
    try:
        spikes = run_alerts()
        if spikes:
            print(f"[SCHEDULED] {len(spikes)} price spike(s) detected - see data/alerts_log.csv")
    except Exception as e:
        print(f"[SCHEDULED][ERROR] Alert check failed: {e}")


def scrape_world_bank():
    from src.scrapers import world_bank
    try:
        result = world_bank.run()
        print(f"[SCHEDULED] {result['message']}")
        _check_alerts()
    except Exception as e:
        print(f"[SCHEDULED][ERROR] World Bank scrape failed: {e}")


def scrape_pricecatcher():
    from src.scrapers import pricecatcher
    try:
        result = pricecatcher.run(months_back=1)
        print(f"[SCHEDULED] {result['message']}")
        _check_alerts()
    except Exception as e:
        print(f"[SCHEDULED][ERROR] PriceCatcher scrape failed: {e}")


def start():
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    scheduler = BlockingScheduler()
    scrapers_cfg = config.get("scrapers", {})

    if scrapers_cfg.get("world_bank", {}).get("enabled", False):
        scheduler.add_job(
            scrape_world_bank,
            CronTrigger(day_of_week="mon", hour=8, minute=0),
            id="world_bank_weekly",
            name="World Bank Pink Sheet (weekly)",
        )
        print("Scheduled: World Bank Pink Sheet - every Monday 08:00")

    if scrapers_cfg.get("pricecatcher", {}).get("enabled", False):
        scheduler.add_job(
            scrape_pricecatcher,
            CronTrigger(day_of_week="tue", hour=8, minute=0),
            id="pricecatcher_weekly",
            name="KPDN PriceCatcher (weekly)",
        )
        print("Scheduled: KPDN PriceCatcher - every Tuesday 08:00")

    print("Scheduler running. Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("Scheduler stopped.")


if __name__ == "__main__":
    start()
