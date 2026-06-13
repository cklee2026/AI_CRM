"""Price forecasting for future weeks/months.

Method (transparent and dependency-free):
1. Resample history to a regular weekly/monthly series (gaps interpolated).
2. Estimate a monthly seasonal index when there is enough history (10+ months).
3. Fit a linear trend on the recent deseasonalized series (last ~52 weeks).
4. Forecast = trend x seasonal index, with a 95% band from residual spread.

This is intentionally a simple statistical model - good for short horizons
(a few weeks/months). The more history collected, the better it gets.
"""
import numpy as np
import pandas as pd
from src.database import get_connection

FREQ_MAP = {"week": "W-MON", "month": "MS"}
MIN_POINTS = {"week": 8, "month": 5}


def _history(food_name: str, location_name: str) -> pd.DataFrame:
    conn = get_connection()
    try:
        df = conn.execute("""
            SELECT p.collected_date AS date, AVG(p.price) AS price
            FROM prices p
            JOIN foods f ON p.food_id = f.id
            JOIN locations l ON p.location_id = l.id
            WHERE f.name = ? AND l.name = ?
            GROUP BY 1 ORDER BY 1
        """, [food_name, location_name]).df()
    finally:
        conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def _recorded_reasons(food_name: str, location_name: str, limit: int = 3) -> list:
    """User-recorded reasons for price moves (excludes auto-generated notes)."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT p.collected_date, p.notes, p.price
            FROM prices p
            JOIN foods f ON p.food_id = f.id
            JOIN locations l ON p.location_id = l.id
            WHERE f.name = ? AND l.name = ?
              AND p.notes IS NOT NULL
              AND p.notes NOT LIKE 'weekly avg%'
              AND p.notes NOT LIKE 'monthly avg%'
            ORDER BY p.collected_date DESC
            LIMIT ?
        """, [food_name, location_name, limit]).fetchall()
    finally:
        conn.close()
    return [{"date": str(r[0]), "note": r[1], "price": float(r[2])} for r in rows]


MONTH_NAMES_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_NAMES_ZH = ["1月", "2月", "3月", "4月", "5月", "6月",
                  "7月", "8月", "9月", "10月", "11月", "12月"]


def _build_explanations(food_name, location_name, series, freq, window,
                        slope, residual_std, seasonal, use_seasonal,
                        future_dates) -> list:
    """Human-readable remarks explaining WHY the forecast looks the way it does.

    Each remark: {"icon", "en", "zh"} - evidence-based, citing actual numbers.
    """
    remarks = []
    unit = "week" if freq == "week" else "month"
    unit_zh = "周" if freq == "week" else "个月"
    mean_price = float(series.mean())

    # 1. Data basis
    first, last = series.index.min(), series.index.max()
    remarks.append({
        "icon": "📊",
        "en": (f"Based on {len(series)} {unit}s of price data "
               f"({first:%Y-%m-%d} to {last:%Y-%m-%d}), average price "
               f"{mean_price:.2f}. More history = more reliable forecasts."),
        "zh": (f"基于 {len(series)} {unit_zh}的价格数据"
               f"（{first:%Y-%m-%d} 至 {last:%Y-%m-%d}），平均价 "
               f"{mean_price:.2f}。历史数据越多，预测越可靠。"),
    })

    # 2. Trend
    trend_pct = (slope / mean_price * 100) if mean_price else 0.0
    if abs(trend_pct) < 0.05:
        remarks.append({
            "icon": "➡️",
            "en": (f"Prices have been essentially FLAT over the last {window} "
                   f"{unit}s ({trend_pct:+.2f}% per {unit}), so the forecast "
                   "stays close to the current level."),
            "zh": (f"过去 {window} {unit_zh}价格基本持平"
                   f"（每{unit_zh} {trend_pct:+.2f}%），因此预测维持在当前水平附近。"),
        })
    else:
        direction_en = "RISING" if trend_pct > 0 else "FALLING"
        direction_zh = "上涨" if trend_pct > 0 else "下跌"
        remarks.append({
            "icon": "📈" if trend_pct > 0 else "📉",
            "en": (f"The underlying trend is {direction_en}: on average "
                   f"{trend_pct:+.2f}% per {unit} over the last {window} {unit}s. "
                   "The forecast extends this trend forward."),
            "zh": (f"基础趋势为{direction_zh}：过去 {window} {unit_zh}平均"
                   f"每{unit_zh} {trend_pct:+.2f}%。预测将此趋势向前延伸。"),
        })

    # 3. Recent momentum vs longer trend
    if len(series) >= 8:
        recent4 = float(series.iloc[-4:].mean())
        prev4 = float(series.iloc[-8:-4].mean())
        if prev4 > 0:
            mom_pct = (recent4 - prev4) / prev4 * 100
            agrees = (mom_pct >= 0) == (trend_pct >= 0) or abs(mom_pct) < 1
            if abs(mom_pct) >= 1:
                mom_dir_en = "up" if mom_pct > 0 else "down"
                mom_dir_zh = "上升" if mom_pct > 0 else "下降"
                consistency_en = ("consistent with the longer trend, which "
                                  "strengthens confidence in the forecast."
                                  if agrees else
                                  "OPPOSITE to the longer trend - treat the "
                                  "forecast with extra caution until more data arrives.")
                consistency_zh = ("与长期趋势一致，增强了预测的可信度。"
                                  if agrees else
                                  "与长期趋势相反 — 请谨慎看待预测，等待更多新数据。")
                remarks.append({
                    "icon": "🔍",
                    "en": (f"Recent momentum: the last 4 {unit}s averaged {recent4:.2f} "
                           f"vs {prev4:.2f} in the 4 before ({mom_pct:+.1f}%, {mom_dir_en}). "
                           f"This is {consistency_en}"),
                    "zh": (f"近期动量：最近 4 {unit_zh}均价 {recent4:.2f}，"
                           f"之前 4 {unit_zh}为 {prev4:.2f}（{mom_pct:+.1f}%，{mom_dir_zh}）。"
                           f"{consistency_zh}"),
                })

    # 4. Seasonality
    if use_seasonal:
        future_months = sorted({d.month for d in future_dates})
        # Pick the forecast month with the biggest seasonal deviation
        dev_month = max(future_months, key=lambda m: abs(seasonal[m] - 1))
        dev = (seasonal[dev_month] - 1) * 100
        if abs(dev) >= 2:
            hl_en = "ABOVE" if dev > 0 else "BELOW"
            hl_zh = "高于" if dev > 0 else "低于"
            remarks.append({
                "icon": "📅",
                "en": (f"Seasonal pattern applied: historically, "
                       f"{MONTH_NAMES_EN[dev_month-1]} prices run {abs(dev):.1f}% "
                       f"{hl_en} the yearly average (seasonal index "
                       f"{seasonal[dev_month]:.2f}). The forecast adjusts for this."),
                "zh": (f"已套用季节性规律：历史上 {MONTH_NAMES_ZH[dev_month-1]} 价格"
                       f"通常{hl_zh}全年平均 {abs(dev):.1f}%（季节指数 "
                       f"{seasonal[dev_month]:.2f}）。预测已据此调整。"),
            })
        else:
            remarks.append({
                "icon": "📅",
                "en": ("Seasonal pattern applied, but the forecast months are "
                       "historically close to the yearly average - little "
                       "seasonal adjustment needed."),
                "zh": "已分析季节性规律，但预测月份历史上接近全年平均价 — 季节调整很小。",
            })
    else:
        remarks.append({
            "icon": "📅",
            "en": ("Less than ~10 months of history, so seasonal patterns are "
                   "NOT applied yet. After a full year of data, the model will "
                   "learn which months are expensive/cheap."),
            "zh": ("历史数据不足约 10 个月，暂未套用季节性规律。"
                   "收集满一年数据后，模型会学习哪些月份贵、哪些月份便宜。"),
        })

    # 5. Volatility / confidence band width
    cv = (residual_std / mean_price * 100) if mean_price else 0.0
    if cv < 2:
        stab_en, stab_zh = "very STABLE", "非常稳定"
        conf_en = "the forecast range is narrow and dependable"
        conf_zh = "预测区间窄且可靠"
    elif cv < 5:
        stab_en, stab_zh = "moderately variable", "波动适中"
        conf_en = "the forecast range reflects normal market variation"
        conf_zh = "预测区间反映正常的市场波动"
    else:
        stab_en, stab_zh = "VOLATILE", "波动较大"
        conf_en = ("the wide 95% range is honest about this - use the range, "
                   "not the single number")
        conf_zh = "较宽的 95% 区间如实反映这一点 — 请参考区间而非单一数字"
    remarks.append({
        "icon": "📏",
        "en": (f"This item's price is {stab_en} (typical deviation "
               f"±{residual_std:.2f}, {cv:.1f}% of the average) - {conf_en}."),
        "zh": (f"该物品价格{stab_zh}（典型偏差 ±{residual_std:.2f}，"
               f"约为均价的 {cv:.1f}%）— {conf_zh}。"),
    })

    # 6. Latest price unusual?
    if len(series) > 9:
        tail = series.iloc[-9:-1]
        tail_std = float(tail.std(ddof=1))
        if tail_std > 0:
            z_last = (float(series.iloc[-1]) - float(tail.mean())) / tail_std
            if abs(z_last) >= 2:
                d_en = "high" if z_last > 0 else "low"
                d_zh = "偏高" if z_last > 0 else "偏低"
                remarks.append({
                    "icon": "⚠️",
                    "en": (f"CAUTION: the most recent price ({series.iloc[-1]:.2f}) "
                           f"is unusually {d_en} vs the recent average "
                           f"({tail.mean():.2f}). If this is a temporary shock, "
                           "the forecast may shift once new data arrives."),
                    "zh": (f"注意：最新价格（{series.iloc[-1]:.2f}）相比近期平均"
                           f"（{tail.mean():.2f}）异常{d_zh}。如果这只是短暂冲击，"
                           "新数据进来后预测可能会修正。"),
                })

    # 7. User-recorded reasons
    reasons = _recorded_reasons(food_name, location_name)
    if reasons:
        listed = "; ".join(f"{r['date'][:10]}: {r['note']}" for r in reasons)
        remarks.append({
            "icon": "📝",
            "en": (f"Recorded market reasons that may still matter: {listed}. "
                   "The model sees only prices - factor these in yourself."),
            "zh": (f"已记录的市场原因（可能仍有影响）：{listed}。"
                   "模型只看价格数字 — 这些因素请自行判断。"),
        })

    return remarks


def forecast_prices(food_name: str, location_name: str,
                    periods: int = 4, freq: str = "week") -> dict:
    """Forecast the next `periods` weeks or months.

    Returns dict with:
      history: DataFrame(date, price) - regularized series used for fitting
      forecast: DataFrame(date, forecast, lo, hi)
      meta: dict(method, points_used, seasonal, residual_std)
    Raises ValueError when there is not enough history.
    """
    if freq not in FREQ_MAP:
        raise ValueError("freq must be 'week' or 'month'")

    raw = _history(food_name, location_name)
    if raw.empty:
        raise ValueError(f"No price history for {food_name} @ {location_name}.")

    series = (raw.set_index("date")["price"]
                 .resample(FREQ_MAP[freq]).mean()
                 .interpolate(limit_direction="both"))
    if len(series) < MIN_POINTS[freq]:
        raise ValueError(
            f"Not enough history: {len(series)} {freq}s of data, "
            f"need at least {MIN_POINTS[freq]}. Collect more data first.")

    # --- Seasonal index (monthly), only with 10+ distinct months of data ---
    months_covered = series.index.month.nunique()
    span_days = (series.index.max() - series.index.min()).days
    use_seasonal = months_covered >= 10 and span_days >= 300

    if use_seasonal:
        month_avg = series.groupby(series.index.month).mean()
        overall = series.mean()
        seasonal = (month_avg / overall).reindex(range(1, 13)).fillna(1.0)
    else:
        seasonal = pd.Series(1.0, index=range(1, 13))

    deseason = series / series.index.month.map(seasonal).values

    # --- Linear trend on the recent window ---
    window = min(len(deseason), 52 if freq == "week" else 24)
    recent = deseason.iloc[-window:]
    t = np.arange(len(recent), dtype=float)
    slope, intercept = np.polyfit(t, recent.values, 1)

    fitted = slope * t + intercept
    residual_std = float(np.std(recent.values - fitted, ddof=1)) if len(recent) > 2 else 0.0

    # --- Project forward ---
    offset = pd.tseries.frequencies.to_offset(FREQ_MAP[freq])
    future_dates = pd.date_range(series.index[-1] + offset, periods=periods, freq=FREQ_MAP[freq])
    t_future = np.arange(len(recent), len(recent) + periods, dtype=float)
    base = slope * t_future + intercept
    season_factors = np.array([seasonal[d.month] for d in future_dates])

    point = np.maximum(base * season_factors, 0.01)
    band = 1.96 * residual_std * season_factors
    lo = np.maximum(point - band, 0.01)
    hi = point + band

    forecast_df = pd.DataFrame({
        "date": future_dates,
        "forecast": np.round(point, 4),
        "lo": np.round(lo, 4),
        "hi": np.round(hi, 4),
    })

    history_df = series.reset_index()
    history_df.columns = ["date", "price"]

    explanations = _build_explanations(
        food_name, location_name, series, freq, window,
        slope, residual_std, seasonal, use_seasonal, future_dates)

    return {
        "history": history_df,
        "forecast": forecast_df,
        "explanations": explanations,
        "meta": {
            "method": "linear trend" + (" + monthly seasonality" if use_seasonal else ""),
            "points_used": int(window),
            "seasonal": bool(use_seasonal),
            "residual_std": round(residual_std, 4),
            "trend_per_period": round(float(slope), 5),
        },
    }
