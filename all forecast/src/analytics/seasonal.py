"""Seasonal pattern and anomaly detection.

Seasonal index: average price per calendar month divided by the overall
average - shows which months are typically expensive (>1.0) or cheap (<1.0).

Anomalies: prices more than N standard deviations away from the rolling
average (z-score), flagging unusual spikes or drops worth investigating.
"""
import pandas as pd
from src.database import get_connection


def _price_series(food_name: str, location_name: str) -> pd.DataFrame:
    conn = get_connection()
    try:
        df = conn.execute("""
            SELECT p.collected_date AS date, p.price, p.notes
            FROM prices p
            JOIN foods f ON p.food_id = f.id
            JOIN locations l ON p.location_id = l.id
            WHERE f.name = ? AND l.name = ?
            ORDER BY p.collected_date
        """, [food_name, location_name]).df()
    finally:
        conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def seasonal_index(food_name: str, location_name: str) -> pd.DataFrame:
    """Seasonal index per calendar month (needs ideally 12+ months of data).

    Returns DataFrame: month (1-12), month_name, avg_price, index, reading
    where index > 1.0 means that month is typically more expensive.
    """
    df = _price_series(food_name, location_name)
    if df.empty:
        return pd.DataFrame()

    overall_avg = df["price"].mean()
    if not overall_avg:
        return pd.DataFrame()

    monthly = (df.assign(month=df["date"].dt.month)
                 .groupby("month")["price"]
                 .agg(avg_price="mean", samples="count")
                 .reset_index())
    monthly["index"] = (monthly["avg_price"] / overall_avg).round(3)
    monthly["month_name"] = monthly["month"].apply(
        lambda m: ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1])
    monthly["reading"] = monthly["index"].apply(
        lambda i: "expensive" if i > 1.02 else ("cheap" if i < 0.98 else "normal"))
    return monthly[["month", "month_name", "avg_price", "index", "reading", "samples"]]


def detect_anomalies(food_name: str, location_name: str,
                     z_threshold: float = 2.0, window: int = 8) -> pd.DataFrame:
    """Flag prices whose z-score vs the rolling window exceeds the threshold.

    Returns DataFrame: date, price, rolling_avg, z_score, direction, notes.
    """
    df = _price_series(food_name, location_name)
    if len(df) < window + 1:
        return pd.DataFrame()

    df = df.set_index("date")
    rolling_mean = df["price"].rolling(window, min_periods=window).mean().shift(1)
    rolling_std = df["price"].rolling(window, min_periods=window).std().shift(1)

    df["rolling_avg"] = rolling_mean
    df["z_score"] = (df["price"] - rolling_mean) / rolling_std
    anomalies = df[df["z_score"].abs() >= z_threshold].copy()

    if anomalies.empty:
        return pd.DataFrame()

    anomalies["direction"] = anomalies["z_score"].apply(
        lambda z: "SPIKE" if z > 0 else "DROP")
    anomalies = anomalies.reset_index()
    anomalies["z_score"] = anomalies["z_score"].round(2)
    anomalies["rolling_avg"] = anomalies["rolling_avg"].round(4)
    return anomalies[["date", "price", "rolling_avg", "z_score", "direction", "notes"]]
