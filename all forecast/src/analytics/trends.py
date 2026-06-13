"""Price trend analysis: up/down direction, % change, and reasons.

Aggregation periods: week, month, year - matching the requirement to
view data "小至每个星期，月份或年份" (down to every week, month or year).
"""
import pandas as pd
from src.database import get_connection

PERIOD_TRUNC = {"week": "week", "month": "month", "year": "year"}


def get_period_summary(food_name: str, location_name: str, period: str = "month",
                       price_type: str = None) -> pd.DataFrame:
    """Aggregate prices by period with avg/min/max and % change vs previous period.

    Returns DataFrame: period_start, avg_price, min_price, max_price,
    price_count, change_pct, direction, notes (reasons recorded for that period).
    price_type optionally restricts to one layer (None = all).
    """
    if period not in PERIOD_TRUNC:
        raise ValueError(f"period must be one of {list(PERIOD_TRUNC)}")

    ptype_clause = "AND p.price_type = ?" if price_type else ""
    params = [food_name, location_name]
    if price_type:
        params.append(price_type)

    conn = get_connection()
    try:
        df = conn.execute(f"""
            SELECT
                DATETRUNC('{PERIOD_TRUNC[period]}', p.collected_date) AS period_start,
                AVG(p.price) AS avg_price,
                MIN(p.price) AS min_price,
                MAX(p.price) AS max_price,
                COUNT(*) AS price_count,
                STRING_AGG(DISTINCT p.notes, '; ') FILTER (WHERE p.notes IS NOT NULL) AS notes
            FROM prices p
            JOIN foods f ON p.food_id = f.id
            JOIN locations l ON p.location_id = l.id
            WHERE f.name = ? AND l.name = ? {ptype_clause}
            GROUP BY 1
            ORDER BY 1
        """, params).df()
    finally:
        conn.close()

    if df.empty:
        return df

    df["change_pct"] = (df["avg_price"].pct_change() * 100).round(2)
    df["direction"] = df["change_pct"].apply(
        lambda x: "UP" if pd.notna(x) and x > 0.5
        else ("DOWN" if pd.notna(x) and x < -0.5 else "STABLE")
    )
    return df


def get_trend_report(food_name: str, location_name: str) -> dict:
    """Full trend report: latest price, change over week/month/year, volatility."""
    conn = get_connection()
    try:
        df = conn.execute("""
            SELECT p.collected_date, p.price, p.notes
            FROM prices p
            JOIN foods f ON p.food_id = f.id
            JOIN locations l ON p.location_id = l.id
            WHERE f.name = ? AND l.name = ?
            ORDER BY p.collected_date
        """, [food_name, location_name]).df()
    finally:
        conn.close()

    if df.empty:
        return None

    df["collected_date"] = pd.to_datetime(df["collected_date"])
    df = df.set_index("collected_date")
    latest_date = df.index.max()
    latest_price = float(df["price"].iloc[-1])

    def change_since(days: int):
        cutoff = latest_date - pd.Timedelta(days=days)
        past = df[df.index <= cutoff]
        if past.empty:
            return None
        past_price = float(past["price"].iloc[-1])
        if past_price == 0:
            return None
        return round((latest_price - past_price) / past_price * 100, 2)

    volatility = round(float(df["price"].std() / df["price"].mean() * 100), 2) \
        if len(df) > 1 and df["price"].mean() else None

    # Recent annotated reasons for price moves
    reasons = df[df["notes"].notna()].tail(5)
    reason_list = [
        {"date": idx.date().isoformat(), "price": float(row["price"]), "note": row["notes"]}
        for idx, row in reasons.iterrows()
    ]

    return {
        "food": food_name,
        "location": location_name,
        "latest_date": latest_date.date().isoformat(),
        "latest_price": latest_price,
        "change_1w_pct": change_since(7),
        "change_1m_pct": change_since(30),
        "change_1y_pct": change_since(365),
        "volatility_pct": volatility,
        "data_points": len(df),
        "recent_reasons": reason_list,
    }


def get_regional_markup(food_name: str) -> pd.DataFrame:
    """Latest price per location with % markup vs the international baseline.

    Note: international prices are in USD; markup % is only meaningful
    between same-currency locations, so we group by currency.
    """
    conn = get_connection()
    try:
        df = conn.execute("""
            WITH latest AS (
                SELECT p.location_id, p.price, p.currency, p.collected_date,
                       ROW_NUMBER() OVER (PARTITION BY p.location_id
                                          ORDER BY p.collected_date DESC) AS rn
                FROM prices p
                JOIN foods f ON p.food_id = f.id
                WHERE f.name = ?
            )
            SELECT l.name AS location, l.level, latest.price, latest.currency,
                   latest.collected_date AS as_of
            FROM latest
            JOIN locations l ON latest.location_id = l.id
            WHERE latest.rn = 1
            ORDER BY l.level
        """, [food_name]).df()
    finally:
        conn.close()

    if df.empty:
        return df

    # Markup vs the highest-level (most national) location in same currency
    for currency in df["currency"].unique():
        sub = df[df["currency"] == currency]
        if len(sub) > 1:
            baseline = sub.iloc[0]["price"]
            if baseline:
                df.loc[df["currency"] == currency, "markup_pct"] = (
                    (df.loc[df["currency"] == currency, "price"] - baseline)
                    / baseline * 100
                ).round(2)

    return df
