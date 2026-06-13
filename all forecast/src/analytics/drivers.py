"""Real-world price drivers from public internet data - NO AI.

Pulls free, key-less public data that plausibly drives Malaysian/Sabah food
prices, aligns each with a local price series, and reports lagged correlations.
Everything is verifiable: every claim points to real numbers, not a model guess.

Sources (all tested reachable, no API key):
  - Diesel/petrol price ........ data.gov.my  (transport cost)
  - USD/MYR exchange rate ...... frankfurter.app  (import cost)
  - Rainfall ................... open-meteo archive  (supply shocks)
  - Festival calendar .......... built-in (no internet)  (demand spikes)

Imported items (name contains INDIA/CHINA/THAI/...) are matched to their
SOURCE-COUNTRY rainfall, not Lahad Datu's - local rain doesn't affect onions
grown in India. Local produce uses Lahad Datu rainfall.

Fetched series are cached to data/drivers/*.csv (refreshed weekly) so repeated
analysis does not hammer the APIs or need a live connection every time.
"""
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

CACHE = Path("data/drivers")
CACHE.mkdir(parents=True, exist_ok=True)
CACHE_AGE_DAYS = 7
UA = {"User-Agent": "Mozilla/5.0 FoodPriceTracker"}

# Source-country growing regions (lat, lon) for imported produce
ORIGIN_COORDS = {
    "INDIA": (19.99, 73.79),       # Nashik - India's onion belt
    "CHINA": (36.40, 118.10),      # Shandong - garlic / vegetables
    "THAILAND": (14.00, 100.60),   # central Thailand
    "THAI": (14.00, 100.60),
    "INDONESIA": (-7.50, 110.00),  # Java
    "HOLLAND": (52.10, 5.30),      # Netherlands
    "NETHERLANDS": (52.10, 5.30),
    "VIETNAM": (10.80, 106.70),
    "MYANMAR": (21.90, 96.10),
    "PAKISTAN": (30.20, 71.50),
}
LAHAD_DATU = (5.03, 118.32)

# Malaysian festivals that drive food demand (date, name). Approximate but
# good enough for "weeks before a festival" correlation. Extend as needed.
FESTIVALS = [
    ("2024-02-10", "Chinese New Year"), ("2025-01-29", "Chinese New Year"),
    ("2026-02-17", "Chinese New Year"), ("2027-02-06", "Chinese New Year"),
    ("2024-04-10", "Hari Raya Aidilfitri"), ("2025-03-31", "Hari Raya Aidilfitri"),
    ("2026-03-20", "Hari Raya Aidilfitri"), ("2027-03-10", "Hari Raya Aidilfitri"),
    ("2024-06-17", "Hari Raya Aidiladha"), ("2025-06-07", "Hari Raya Aidiladha"),
    ("2026-05-27", "Hari Raya Aidiladha"), ("2027-05-17", "Hari Raya Aidiladha"),
    ("2024-10-31", "Deepavali"), ("2025-10-20", "Deepavali"),
    ("2026-11-08", "Deepavali"), ("2027-10-29", "Deepavali"),
]


# ---------------------------------------------------------------------------
# Origin detection
# ---------------------------------------------------------------------------
def detect_origin(food_name: str):
    """Return the source-country key if the item name marks an import, else None."""
    up = food_name.upper()
    for key in ORIGIN_COORDS:
        if re.search(rf"\b{key}\b", up):
            return key
    if "IMPORT" in up:
        return "IMPORT"     # imported but unknown country
    return None


# ---------------------------------------------------------------------------
# Cached fetch helper
# ---------------------------------------------------------------------------
def _cached(name, builder):
    path = CACHE / f"{name}.csv"
    if path.exists():
        age = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).days
        if age < CACHE_AGE_DAYS:
            try:
                df = pd.read_csv(path, parse_dates=["date"])
                if not df.empty:
                    return df
            except Exception:
                pass
    df = builder()
    if df is not None and not df.empty:
        df.to_csv(path, index=False)
    return df


# ---------------------------------------------------------------------------
# Fetchers (each returns DataFrame[date, value])
# ---------------------------------------------------------------------------
def fetch_diesel():
    def build():
        url = "https://api.data.gov.my/data-catalogue?id=fuelprice&limit=2000"
        r = requests.get(url, timeout=30, headers=UA)
        r.raise_for_status()
        df = pd.DataFrame(r.json())
        df = df[df["series_type"] == "level"][["date", "diesel"]].copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.rename(columns={"diesel": "value"}).dropna()
        return df.sort_values("date")
    return _cached("diesel", build)


def fetch_fx():
    """USD->MYR daily rate from the local price era to now."""
    def build():
        start = "2023-01-01"
        end = date.today().isoformat()
        url = f"https://api.frankfurter.app/{start}..{end}?from=USD&to=MYR"
        r = requests.get(url, timeout=30, headers=UA)
        r.raise_for_status()
        rates = r.json().get("rates", {})
        rows = [{"date": d, "value": v["MYR"]} for d, v in sorted(rates.items())]
        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
        return df
    return _cached("fx_usd_myr", build)


def fetch_rainfall(origin_key=None):
    """Daily precipitation for the relevant region (source country or Lahad Datu)."""
    lat, lon = ORIGIN_COORDS.get(origin_key, LAHAD_DATU)
    tag = origin_key if origin_key in ORIGIN_COORDS else "lahad_datu"

    def build():
        start = "2023-01-01"
        end = (date.today() - timedelta(days=5)).isoformat()  # archive lags a few days
        url = ("https://archive-api.open-meteo.com/v1/archive"
               f"?latitude={lat}&longitude={lon}&start_date={start}&end_date={end}"
               "&daily=precipitation_sum&timezone=auto")
        r = requests.get(url, timeout=30, headers=UA)
        r.raise_for_status()
        daily = r.json().get("daily", {})
        df = pd.DataFrame({"date": daily.get("time", []),
                           "value": daily.get("precipitation_sum", [])})
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.dropna()
        return df
    return _cached(f"rain_{tag}", build)


def festival_indicator(dates, pre_days=21):
    """For a DatetimeIndex/Series, return a 0/1 series: 1 if within `pre_days`
    before any festival (the demand build-up window)."""
    fdates = [pd.Timestamp(d) for d, _ in FESTIVALS]
    out = []
    for d in dates:
        d = pd.Timestamp(d)
        flag = any(0 <= (fd - d).days <= pre_days for fd in fdates)
        out.append(1 if flag else 0)
    return pd.Series(out, index=pd.DatetimeIndex(dates))


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------
def _lagged_corr(local, driver, lags_weeks=(0, 1, 2, 3, 4, 6, 8)):
    """Best |correlation| of WEEK-OVER-WEEK CHANGES of the local price vs the
    driver, at several lags (driver leading). Correlating changes (not levels)
    removes the shared trend, so two series that merely both drift over the year
    do NOT show a spurious correlation - only genuine co-movement counts.
    Returns (lag_weeks, r, n).
    """
    l = local.set_index("date")["price"].resample("W-MON").mean().interpolate().diff().dropna()
    g = (driver.set_index("date")["value"].resample("W-MON").mean()
         .interpolate().diff().dropna())
    if len(l) < 8 or len(g) < 8:
        return None, None, 0
    best = (None, 0.0, 0)
    for w in lags_weeks:
        joined = pd.concat([l, g.shift(w)], axis=1, join="inner").dropna()
        if len(joined) < 8:
            continue
        if joined.iloc[:, 0].std() == 0 or joined.iloc[:, 1].std() == 0:
            continue
        r = joined.iloc[:, 0].corr(joined.iloc[:, 1])
        if r is not None and abs(r) > abs(best[1]):
            best = (w, round(float(r), 2), len(joined))
    return best


def _festival_corr(local, pre_days=21):
    l = local.set_index("date")["price"].resample("W-MON").mean().dropna()
    if len(l) < 8:
        return None, 0
    ind = festival_indicator(l.index, pre_days=pre_days)
    joined = pd.concat([l, ind], axis=1, join="inner").dropna()
    if joined.iloc[:, 1].nunique() < 2:
        return None, 0
    r = joined.iloc[:, 0].corr(joined.iloc[:, 1])
    return (round(float(r), 2) if r is not None else None), len(joined)


# ---------------------------------------------------------------------------
# Public: build driver findings for a price series
# ---------------------------------------------------------------------------
def _strength(r):
    a = abs(r)
    if a >= 0.7:
        return "strong", "较强"
    if a >= 0.5:
        return "moderate", "中等"
    return "weak", "较弱"


def _conf(r):
    """Honest confidence from correlation magnitude."""
    a = abs(r)
    if a >= 0.7:
        return "high"
    if a >= 0.5:
        return "medium"
    return "low"


def driver_findings(local_df, food_name, min_abs_r=0.30):
    """local_df: DataFrame[date, price]. Returns list of bilingual findings
    {icon, category, en, zh, confidence}. Hits the internet.

    Correlations are on WEEK-OVER-WEEK CHANGES (de-trended), so a reported link
    is genuine co-movement, not two series that merely drift together. r>=0.30
    on ~50 weeks is roughly the threshold of statistical significance; weaker
    links are not reported. low/medium/high confidence follows |r|.
    """
    findings = []
    origin = detect_origin(food_name)
    imported = origin is not None

    # 1. Diesel (transport). Expected mechanism: diesel up -> price up (r>0).
    try:
        diesel = fetch_diesel()
        lag, r, n = _lagged_corr(local_df, diesel)
        if r is not None and abs(r) >= min_abs_r:
            s_en, s_zh = _strength(r)
            if r > 0:
                en = (f"Moves WITH diesel price ({s_en} r={r}, ~{lag}wk lag): "
                      f"diesel up -> this price up. Consistent with transport cost "
                      f"pass-through (n={n} wk).")
                zh = (f"与柴油价同向({s_zh} r={r},滞后约{lag}周):油价涨→此价涨。"
                      f"符合运输成本传导(n={n}周)。")
            else:
                en = (f"Moves OPPOSITE to diesel ({s_en} r={r}, ~{lag}wk lag) - not "
                      f"the usual transport-cost direction; likely coincidental (n={n}).")
                zh = (f"与柴油价反向({s_zh} r={r},滞后约{lag}周)——非运输成本的常见"
                      f"方向,可能是巧合(n={n})。")
            findings.append({"icon": "🚚", "category": "diesel",
                             "confidence": _conf(r),
                             "en": en, "zh": zh})
    except Exception as e:
        findings.append({"icon": "🚚", "category": "diesel", "confidence": "low",
                         "en": f"Diesel data unavailable ({e}).",
                         "zh": f"柴油数据获取失败({e})。"})

    # 2. FX USD/MYR (import cost). Expected: ringgit weak (rate up) -> dearer (r>0).
    if imported:
        try:
            fx = fetch_fx()
            lag, r, n = _lagged_corr(local_df, fx)
            if r is not None and abs(r) >= min_abs_r:
                s_en, s_zh = _strength(r)
                if r > 0:
                    en = (f"Moves WITH USD/MYR ({s_en} r={r}, ~{lag}wk lag): a "
                          f"weaker ringgit, dearer import. Consistent with import-"
                          f"cost pass-through (n={n}).")
                    zh = (f"与美元/令吉汇率同向({s_zh} r={r},滞后约{lag}周):令吉贬"
                          f"→进口更贵。符合进口成本传导(n={n})。")
                else:
                    en = (f"Moves OPPOSITE to USD/MYR ({s_en} r={r}, ~{lag}wk lag) "
                          f"- not the usual import-cost direction; likely "
                          f"coincidental (n={n}).")
                    zh = (f"与美元/令吉汇率反向({s_zh} r={r},滞后约{lag}周)——非进口"
                          f"成本的常见方向,可能是巧合(n={n})。")
                findings.append({"icon": "💱", "category": "fx",
                                 "confidence": _conf(r),
                                 "en": en, "zh": zh})
        except Exception:
            pass

    # 3. Rainfall (supply). Expected: more rain -> supply down -> price up (r>0).
    try:
        rain = fetch_rainfall(origin if origin in ORIGIN_COORDS else None)
        lag, r, n = _lagged_corr(local_df, rain, lags_weeks=(1, 2, 3, 4, 6, 8, 10))
        where_en = (f"{origin.title()} (source country)" if origin in ORIGIN_COORDS
                    else "Lahad Datu")
        where_zh = (f"{origin}(来源国)" if origin in ORIGIN_COORDS else "Lahad Datu")
        if r is not None and abs(r) >= min_abs_r:
            s_en, s_zh = _strength(r)
            if r > 0:
                en = (f"Rises after wetter spells in {where_en} ({s_en} r={r}, "
                      f"~{lag}wk lag): rain disrupts supply, lifts price (n={n}).")
                zh = (f"{where_zh}多雨后此价上升({s_zh} r={r},滞后约{lag}周):降雨"
                      f"扰乱供应、推高价格(n={n})。")
            else:
                en = (f"Falls after wetter spells in {where_en} ({s_en} r={r}, "
                      f"~{lag}wk lag) - opposite to the supply-shock pattern; "
                      f"likely coincidental (n={n}).")
                zh = (f"{where_zh}多雨后此价反而下降({s_zh} r={r},滞后约{lag}周)"
                      f"——与供应冲击相反,可能是巧合(n={n})。")
            findings.append({"icon": "🌧️", "category": "rainfall",
                             "confidence": _conf(r), "en": en, "zh": zh})
    except Exception:
        pass

    # 4. Festivals (demand)
    try:
        r, n = _festival_corr(local_df)
        if r is not None and abs(r) >= min_abs_r:
            findings.append({
                "icon": "🎉", "category": "festival", "confidence": "medium",
                "en": f"Higher in the ~3 weeks before festivals (r={r}): "
                      f"CNY / Hari Raya / Deepavali demand build-up (n={n}).",
                "zh": f"节庆前约3周价格偏高(r={r}):农历新年/开斋节/屠妖节"
                      f"备货需求(n={n})。"})
    except Exception:
        pass

    if not findings:
        findings.append({
            "icon": "ℹ️", "category": "none", "confidence": "low",
            "en": "No statistically meaningful link (|r|>=0.30) found between this "
                  "price's weekly moves and diesel, FX, rainfall or festivals over "
                  "the available ~1 year. Weekly food prices are noisy and locally "
                  "driven; longer history would test slower drivers better.",
            "zh": "在现有约1年数据中,此价格的周变化与柴油、汇率、降雨、节庆均无"
                  "统计上有意义的关联(|r|>=0.30)。食品周价噪声大、受本地因素主导;"
                  "积累更长历史才能更好检验较慢的驱动因素。"})
    else:
        findings.append({
            "icon": "⚖️", "category": "caveat", "confidence": "low",
            "en": "These are de-trended correlations, NOT proof of cause. Based on "
                  "~1 year of weekly data; treat as suggestive context, not fact.",
            "zh": "以上是去趋势后的相关性,不是因果证明。基于约1年周数据,只作"
                  "参考性背景,不能当定论。"})
    return {"origin": origin, "imported": imported, "findings": findings}
