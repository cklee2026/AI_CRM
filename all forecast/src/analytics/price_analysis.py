"""Formal, offline price analysis - NO AI, NO internet required.

Everything here is rule-based statistics computed from the prices already in
the local DuckDB. It is deterministic, reproducible and free. It explains the
price behaviour (what is happening and the data-supported drivers); it does
NOT invent external real-world causes it cannot see.

What it reports for a (food, location[, price_type]) series:
  - direction & magnitude of the move (linear trend, % change over 1/3/6/12 mo)
  - volatility (coefficient of variation) with a plain-language band
  - seasonal position (which months are typically dear/cheap, where we are now)
  - momentum (recent vs the longer trend - accelerating / easing / reversing)
  - range position (is the latest price near its high or low)
  - anomaly flag on the latest point (z-score vs the recent window)
  - OPTIONAL driver test: lagged correlation against an international series
    (e.g. World Bank) - the closest data-driven "why" without external info
  - any human-recorded reasons (price notes)

Each finding carries a category and a confidence so the report is honest
about what the data can and cannot support.
"""
from datetime import date
import numpy as np
import pandas as pd

from src.database import get_connection
from src.analytics.seasonal import seasonal_index


def _series(food, location, price_type=None):
    clause = "AND p.price_type = ?" if price_type else ""
    params = [food, location] + ([price_type] if price_type else [])
    conn = get_connection()
    try:
        df = conn.execute(f"""
            SELECT p.collected_date AS date, p.price, p.notes
            FROM prices p
            JOIN foods f ON p.food_id = f.id
            JOIN locations l ON p.location_id = l.id
            WHERE f.name = ? AND l.name = ? {clause}
            ORDER BY p.collected_date
        """, params).df()
    finally:
        conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df["price"] = df["price"].astype(float)
    return df


def _pct_change_since(df, days):
    """% change from the price ~`days` before the latest, to the latest."""
    latest_date = df["date"].iloc[-1]
    cutoff = latest_date - pd.Timedelta(days=days)
    past = df[df["date"] <= cutoff]
    if past.empty:
        return None
    base = past["price"].iloc[-1]
    if not base:
        return None
    return round((df["price"].iloc[-1] - base) / base * 100, 1)


def _linear_trend(df):
    """Least-squares slope over time. Returns (pct_per_month, r2)."""
    if len(df) < 3:
        return None, None
    t = (df["date"] - df["date"].iloc[0]).dt.days.to_numpy(dtype=float)
    y = df["price"].to_numpy(dtype=float)
    if t.max() == 0:
        return None, None
    slope, intercept = np.polyfit(t, y, 1)
    pred = slope * t + intercept
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    mean_price = y.mean()
    pct_per_month = (slope * 30 / mean_price * 100) if mean_price else None
    return (round(pct_per_month, 2) if pct_per_month is not None else None,
            round(r2, 2))


def _lagged_correlation(local_df, intl_df, lags_weeks=(0, 2, 4, 8, 12)):
    """Best correlation of local price vs an international series at several
    lags (international leading). Returns (best_lag_weeks, best_r) or (None, None).
    """
    if local_df.empty or intl_df.empty:
        return None, None
    # monthly means make the two series comparable despite different cadences
    l = (local_df.set_index("date")["price"].resample("MS").mean().dropna())
    g = (intl_df.set_index("date")["price"].resample("MS").mean().dropna())
    if len(l) < 4 or len(g) < 4:
        return None, None
    best = (None, 0.0)
    for w in lags_weeks:
        shifted = g.shift(periods=int(round(w / 4.345)))  # weeks -> months
        joined = pd.concat([l, shifted], axis=1, join="inner").dropna()
        if len(joined) < 4:
            continue
        r = joined.iloc[:, 0].corr(joined.iloc[:, 1])
        if r is not None and abs(r) > abs(best[1]):
            best = (w, round(float(r), 2))
    return best if best[0] is not None else (None, None)


def _vol_band(cv):
    if cv is None:
        return None, None, None
    if cv < 0.04:
        return "stable", "波动小", "📊"
    if cv < 0.10:
        return "moderately volatile", "中度波动", "📊"
    return "highly volatile", "波动大", "⚠️"


def analyze_price(food, location, price_type=None, intl_food=None,
                  intl_location="International"):
    """Return a structured, offline analysis report.

    intl_food: optional international commodity name to test as a price driver
    (lagged correlation). None skips the driver test.
    """
    df = _series(food, location, price_type)
    if df.empty:
        return {"ok": False, "reason": "no data for this selection",
                "findings": []}

    latest = float(df["price"].iloc[-1])
    latest_date = df["date"].iloc[-1].date()
    lo, hi, mean = float(df["price"].min()), float(df["price"].max()), float(df["price"].mean())
    cv = float(df["price"].std() / mean) if mean and len(df) > 1 else None

    chg = {w: _pct_change_since(df, d) for w, d in
           (("1m", 30), ("3m", 91), ("6m", 182), ("1y", 365))}
    slope_pm, r2 = _linear_trend(df)
    range_pos = round((latest - lo) / (hi - lo) * 100) if hi > lo else None

    # momentum: last 3 vs prior 3 observations
    momentum = None
    if len(df) >= 6:
        recent = df["price"].iloc[-3:].mean()
        prior = df["price"].iloc[-6:-3].mean()
        if prior:
            momentum = round((recent - prior) / prior * 100, 1)

    # seasonal position
    seas = seasonal_index(food, location) if price_type is None else seasonal_index(food, location)
    cur_month = latest_date.month
    cur_season = None
    peak = trough = None
    if not seas.empty:
        row = seas[seas["month"] == cur_month]
        if not row.empty:
            cur_season = {"index": float(row["index"].iloc[0]),
                          "reading": row["reading"].iloc[0]}
        peak = seas.loc[seas["index"].idxmax()]
        trough = seas.loc[seas["index"].idxmin()]

    # anomaly on the latest point (z vs last up-to-8 window)
    z_latest = None
    if len(df) >= 6:
        window = df["price"].iloc[-9:-1]
        if len(window) >= 4 and window.std():
            z_latest = round((latest - window.mean()) / window.std(), 2)

    # optional international driver test
    intl_lag, intl_r = (None, None)
    if intl_food:
        intl_df = _series(intl_food, intl_location, price_type=None)
        intl_lag, intl_r = _lagged_correlation(df, intl_df)

    # recorded human reasons (notes that are not auto "weekly/monthly avg")
    notes = [n for n in df["notes"].dropna().unique()
             if not str(n).lower().startswith(("weekly avg", "monthly avg"))]

    report = {
        "ok": True, "food": food, "location": location,
        "price_type": price_type or "all",
        "latest": latest, "latest_date": str(latest_date),
        "min": round(lo, 4), "max": round(hi, 4), "mean": round(mean, 4),
        "cv": round(cv, 3) if cv is not None else None,
        "change": chg, "trend_pct_per_month": slope_pm, "trend_r2": r2,
        "range_position_pct": range_pos, "momentum_pct": momentum,
        "season_now": cur_season,
        "season_peak": (peak["month_name"] if peak is not None else None),
        "season_trough": (trough["month_name"] if trough is not None else None),
        "latest_z": z_latest,
        "intl_driver": ({"commodity": intl_food, "lag_weeks": intl_lag,
                         "correlation": intl_r} if intl_food else None),
        "recorded_reasons": notes,
        "data_points": int(len(df)),
        "history_days": int((df["date"].iloc[-1] - df["date"].iloc[0]).days),
    }
    report["findings"] = _build_findings(report)
    return report


def _build_findings(r):
    """Turn the numbers into ranked bilingual findings. Each:
    {icon, category, en, zh, confidence: high|medium|low}."""
    f = []

    # 1. Basis
    f.append({"icon": "🧾", "category": "basis", "confidence": "high",
              "en": f"Based on {r['data_points']} price points over "
                    f"{r['history_days']} days ({r['price_type']}).",
              "zh": f"基于 {r['history_days']} 天内 {r['data_points']} 个价格点"
                    f"（{r['price_type']}）。"})

    # 2. Trend direction + magnitude
    slope = r["trend_pct_per_month"]
    if slope is not None:
        conf = "high" if (r["trend_r2"] or 0) >= 0.5 else "medium" if (r["trend_r2"] or 0) >= 0.2 else "low"
        if slope > 0.5:
            d_en, d_zh, icon = "rising", "上升", "📈"
        elif slope < -0.5:
            d_en, d_zh, icon = "falling", "下降", "📉"
        else:
            d_en, d_zh, icon = "broadly flat", "大致持平", "➡️"
        f.append({"icon": icon, "category": "trend", "confidence": conf,
                  "en": f"Underlying trend is {d_en}: about {slope:+.1f}%/month "
                        f"(fit R²={r['trend_r2']}).",
                  "zh": f"基本趋势{d_zh}：约 {slope:+.1f}%/月"
                        f"（拟合度 R²={r['trend_r2']}）。"})

    # 3. Concrete changes
    parts_en, parts_zh = [], []
    for w, lab_zh in (("1m", "1个月"), ("3m", "3个月"), ("1y", "1年")):
        v = r["change"].get(w)
        if v is not None:
            parts_en.append(f"{w} {v:+.1f}%")
            parts_zh.append(f"{lab_zh} {v:+.1f}%")
    if parts_en:
        f.append({"icon": "🔢", "category": "change", "confidence": "high",
                  "en": "Actual change: " + ", ".join(parts_en) + ".",
                  "zh": "实际变化：" + "、".join(parts_zh) + "。"})

    # 4. Momentum vs trend (acceleration / reversal)
    m = r["momentum_pct"]
    if m is not None and slope is not None:
        if (m > 1 and slope < -0.5) or (m < -1 and slope > 0.5):
            f.append({"icon": "🔄", "category": "momentum", "confidence": "medium",
                      "en": f"Recent momentum ({m:+.1f}%) contradicts the longer "
                            "trend - a possible turning point.",
                      "zh": f"近期动能（{m:+.1f}%）与长期趋势相反——可能出现转折。"})
        elif abs(m) > 2:
            word_en = "accelerating" if (m > 0) == (slope > 0) else "easing"
            word_zh = "加速" if (m > 0) == (slope > 0) else "放缓"
            f.append({"icon": "🔄", "category": "momentum", "confidence": "medium",
                      "en": f"Move is {word_en}: last 3 vs prior 3 = {m:+.1f}%.",
                      "zh": f"走势{word_zh}：最近3期 vs 前3期 = {m:+.1f}%。"})

    # 5. Volatility
    band_en, band_zh, vicon = _vol_band(r["cv"])
    if band_en:
        f.append({"icon": vicon, "category": "volatility", "confidence": "high",
                  "en": f"Price is {band_en} (CV={r['cv']*100:.1f}%).",
                  "zh": f"价格{band_zh}（变异系数 CV={r['cv']*100:.1f}%）。"})

    # 6. Range position
    rp = r["range_position_pct"]
    if rp is not None:
        if rp >= 80:
            f.append({"icon": "🔺", "category": "range", "confidence": "high",
                      "en": f"Latest {r['latest']:.2f} sits near the TOP of its "
                            f"range ({rp}% of {r['min']:.2f}-{r['max']:.2f}).",
                      "zh": f"最新价 {r['latest']:.2f} 处于历史区间高位"
                            f"（{rp}%，区间 {r['min']:.2f}–{r['max']:.2f}）。"})
        elif rp <= 20:
            f.append({"icon": "🔻", "category": "range", "confidence": "high",
                      "en": f"Latest {r['latest']:.2f} sits near the BOTTOM of its "
                            f"range ({rp}% of {r['min']:.2f}-{r['max']:.2f}).",
                      "zh": f"最新价 {r['latest']:.2f} 处于历史区间低位"
                            f"（{rp}%，区间 {r['min']:.2f}–{r['max']:.2f}）。"})

    # 7. Seasonal position
    s = r["season_now"]
    if s and r["season_peak"]:
        if s["reading"] != "normal":
            tag_en = "typically expensive" if s["reading"] == "expensive" else "typically cheap"
            tag_zh = "通常偏贵" if s["reading"] == "expensive" else "通常偏便宜"
            f.append({"icon": "📅", "category": "seasonal", "confidence": "medium",
                      "en": f"Seasonally this month is {tag_en} "
                            f"(index {s['index']:.2f}); peak ~{r['season_peak']}, "
                            f"cheapest ~{r['season_trough']}.",
                      "zh": f"季节上本月{tag_zh}（指数 {s['index']:.2f}）；"
                            f"通常最贵在 {r['season_peak']}，最便宜在 {r['season_trough']}。"})

    # 8. Anomaly on latest
    z = r["latest_z"]
    if z is not None and abs(z) >= 2:
        f.append({"icon": "🚨", "category": "anomaly", "confidence": "high",
                  "en": f"Latest price is unusual vs its recent window "
                        f"(z={z:+.1f}) - a notable {'jump' if z>0 else 'drop'}.",
                  "zh": f"最新价相对近期异常（z={z:+.1f}）——明显"
                        f"{'跳升' if z>0 else '下跌'}。"})

    # 9. International driver (lagged correlation)
    idr = r["intl_driver"]
    if idr and idr["correlation"] is not None and abs(idr["correlation"]) >= 0.5:
        strength_en = "strong" if abs(idr["correlation"]) >= 0.7 else "moderate"
        strength_zh = "较强" if abs(idr["correlation"]) >= 0.7 else "中等"
        lagtxt_en = (f"with ~{idr['lag_weeks']} week lag"
                     if idr["lag_weeks"] else "with no lag")
        lagtxt_zh = (f"滞后约 {idr['lag_weeks']} 周"
                     if idr["lag_weeks"] else "无滞后")
        f.append({"icon": "🌍", "category": "driver", "confidence": "medium",
                  "en": f"Likely driver: tracks international {idr['commodity']} "
                        f"({strength_en} correlation r={idr['correlation']}, "
                        f"{lagtxt_en}). Correlation, not proof.",
                  "zh": f"可能驱动因素：与国际 {idr['commodity']} 同向"
                        f"（{strength_zh}相关 r={idr['correlation']}，{lagtxt_zh}）。"
                        f"这是相关性，非因果证明。"})

    # 10. Recorded human reasons
    if r["recorded_reasons"]:
        joined = "; ".join(str(x) for x in r["recorded_reasons"][:3])
        f.append({"icon": "📝", "category": "recorded", "confidence": "high",
                  "en": f"Recorded notes: {joined}.",
                  "zh": f"已记录的备注：{joined}。"})

    return f
