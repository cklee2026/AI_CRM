"""Price spike alerts.

Compares the two most recent prices for every food x location pair and
flags moves larger than the configured threshold. Alerts go to:
  - console (always)
  - data/alerts_log.csv (always, for history)
  - Telegram (optional - set bot_token/chat_id in config.yaml)
"""
import csv
import yaml
import requests
from datetime import datetime
from pathlib import Path
from src.database import get_connection


def _load_alert_config() -> dict:
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("alerts", {})


def detect_spikes(threshold_pct: float = None) -> list:
    """Find food x location pairs whose latest price moved > threshold %."""
    cfg = _load_alert_config()
    if threshold_pct is None:
        threshold_pct = float(cfg.get("threshold_pct", 10))

    conn = get_connection()
    try:
        rows = conn.execute("""
            WITH ranked AS (
                SELECT f.name AS food, l.name AS location,
                       p.price, p.currency, p.collected_date, p.notes,
                       ROW_NUMBER() OVER (PARTITION BY p.food_id, p.location_id
                                          ORDER BY p.collected_date DESC) AS rn
                FROM prices p
                JOIN foods f ON p.food_id = f.id
                JOIN locations l ON p.location_id = l.id
            )
            SELECT cur.food, cur.location,
                   prev.price AS prev_price, cur.price AS cur_price,
                   prev.collected_date AS prev_date, cur.collected_date AS cur_date,
                   cur.currency, cur.notes
            FROM ranked cur
            JOIN ranked prev
              ON cur.food = prev.food AND cur.location = prev.location
             AND cur.rn = 1 AND prev.rn = 2
            WHERE prev.price > 0
        """).fetchall()
    finally:
        conn.close()

    spikes = []
    for food, location, prev_price, cur_price, prev_date, cur_date, currency, notes in rows:
        change_pct = (float(cur_price) - float(prev_price)) / float(prev_price) * 100
        if abs(change_pct) >= threshold_pct:
            spikes.append({
                "food": food,
                "location": location,
                "prev_price": float(prev_price),
                "cur_price": float(cur_price),
                "prev_date": str(prev_date),
                "cur_date": str(cur_date),
                "change_pct": round(change_pct, 2),
                "currency": currency,
                "direction": "UP" if change_pct > 0 else "DOWN",
                "notes": notes,
            })

    spikes.sort(key=lambda s: -abs(s["change_pct"]))
    return spikes


def log_alerts(spikes: list, log_file: str = None):
    """Append alerts to the CSV history log."""
    cfg = _load_alert_config()
    path = Path(log_file or cfg.get("log_file", "./data/alerts_log.csv"))
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()

    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["alerted_at", "food", "location", "prev_price",
                             "cur_price", "change_pct", "direction",
                             "prev_date", "cur_date", "currency"])
        now = datetime.now().isoformat(timespec="seconds")
        for s in spikes:
            writer.writerow([now, s["food"], s["location"], s["prev_price"],
                             s["cur_price"], s["change_pct"], s["direction"],
                             s["prev_date"], s["cur_date"], s["currency"]])


def send_telegram(spikes: list) -> bool:
    """Send alerts to Telegram if configured. Returns True if sent."""
    cfg = _load_alert_config().get("telegram", {})
    if not cfg.get("enabled") or not cfg.get("bot_token") or not cfg.get("chat_id"):
        return False

    lines = ["Food price alerts:"]
    for s in spikes[:15]:
        lines.append(
            f"{s['direction']} {s['food']} @ {s['location']}: "
            f"{s['prev_price']:.2f} -> {s['cur_price']:.2f} {s['currency']} "
            f"({s['change_pct']:+.1f}%)"
        )
    resp = requests.post(
        f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
        json={"chat_id": cfg["chat_id"], "text": "\n".join(lines)},
        timeout=30,
    )
    return resp.ok


def _format_lines(spikes: list) -> list:
    lines = []
    for s in spikes[:15]:
        lines.append(
            f"{s['direction']} {s['food']} @ {s['location']}: "
            f"{s['prev_price']:.2f} -> {s['cur_price']:.2f} {s['currency']} "
            f"({s['change_pct']:+.1f}%)"
        )
    return lines


def send_email(spikes: list) -> bool:
    """Send alerts by email if SMTP is configured. Returns True if sent."""
    cfg = _load_alert_config().get("email", {})
    if not cfg.get("enabled") or not cfg.get("smtp_host") or not cfg.get("to"):
        return False

    import smtplib
    from email.mime.text import MIMEText

    body = "Food price alerts:\n\n" + "\n".join(_format_lines(spikes))
    msg = MIMEText(body)
    msg["Subject"] = f"[Food Price Tracker] {len(spikes)} price spike(s) detected"
    msg["From"] = cfg.get("from", cfg.get("username", "food-price-tracker"))
    msg["To"] = cfg["to"]

    with smtplib.SMTP(cfg["smtp_host"], int(cfg.get("smtp_port", 587))) as server:
        if cfg.get("use_tls", True):
            server.starttls()
        if cfg.get("username"):
            server.login(cfg["username"], cfg.get("password", ""))
        server.send_message(msg)
    return True


def run(threshold_pct: float = None) -> list:
    """Detect, log, and dispatch alerts. Returns the spike list."""
    spikes = detect_spikes(threshold_pct)
    if spikes:
        log_alerts(spikes)
        try:
            send_telegram(spikes)
        except Exception as e:
            print(f"[WARN] Telegram alert failed: {e}")
        try:
            send_email(spikes)
        except Exception as e:
            print(f"[WARN] Email alert failed: {e}")
    return spikes
