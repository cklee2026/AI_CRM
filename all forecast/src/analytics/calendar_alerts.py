"""Malaysian festival & seasonal price-alert remarks.

Warns the shop owner about the CALENDAR dates that reliably move Malaysian food
prices, in BOTH directions:
  - 暴涨 / spike : demand build-up before festivals (Chinese New Year, the
    Ramadan fasting month -> Hari Raya Aidilfitri, Hari Raya Aidiladha,
    Deepavali) -> stock up early.
  - 暴跌 / crash : the post-festival normalisation and the item's historically
    cheap months -> consider waiting.

Two kinds of knowledge, kept clearly separate:
  - Festival demand patterns = GENERAL Malaysian knowledge (labelled 一般规律).
  - Per-item high/low months   = DATA from the user's own price history, via
    seasonal_index().

Reuses (no duplication):
  - FESTIVALS               from analytics.drivers
  - seasonal_index()        from analytics.seasonal
  - commodity_for()         from analytics.news (food -> commodity keyword)
"""
from datetime import date, datetime

from src.analytics.drivers import FESTIVALS
from src.analytics.seasonal import seasonal_index
from src.analytics.news import commodity_for

MONTH_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_ZH = ["1月", "2月", "3月", "4月", "5月", "6月",
            "7月", "8月", "9月", "10月", "11月", "12月"]

# General Malaysian demand knowledge per festival. `affected` holds commodity
# keywords as returned by news.commodity_for(); `lead_weeks` is how early demand
# (and price) typically starts building. NOT data - clearly labelled as a
# general pattern when shown.
FESTIVAL_EFFECTS = {
    "Chinese New Year": {
        "lead_weeks": 4,
        "affected": ["chicken", "fish", "vegetable", "palm oil", "sugar"],
        "en": ("poultry, seafood, vegetables, cooking oil and sugar demand "
               "surges in the weeks before CNY"),
        "zh": "年前几周鸡肉、海鲜、蔬菜、食用油、糖需求大增",
    },
    # Aidilfitri: the Ramadan fasting month (~30 days before) is the real
    # demand window, so the lead is long.
    "Hari Raya Aidilfitri": {
        "lead_weeks": 5,
        "affected": ["chicken", "beef", "fish", "vegetable", "sugar",
                     "wheat flour", "palm oil"],
        "en": ("the Ramadan fasting month drives chicken, beef, fish, "
               "vegetables, sugar, flour and cooking oil demand up; it peaks "
               "just before Hari Raya"),
        "zh": ("斋戒月（开斋节前约一个月）鸡肉、牛肉、鱼、蔬菜、糖、面粉、"
               "食用油需求上升，临近开斋节达到高峰"),
    },
    "Hari Raya Aidiladha": {
        "lead_weeks": 2,
        "affected": ["beef"],
        "en": ("mainly beef/cattle (korban) demand rises; impact on general "
               "groceries is usually modest"),
        "zh": "主要是牛肉/牛只（宰牲）需求上升，对一般杂货影响通常较小",
    },
    "Deepavali": {
        "lead_weeks": 2,
        "affected": ["palm oil", "sugar", "wheat flour", "vegetable"],
        "en": ("cooking oil, sugar, flour and vegetables demand rises ~2 weeks "
               "before Deepavali"),
        "zh": "屠妖节前约2周食用油、糖、面粉、蔬菜需求上升",
    },
}


def _parse_festivals():
    """[(date, name)] sorted by date."""
    out = []
    for d, name in FESTIVALS:
        try:
            out.append((datetime.strptime(d, "%Y-%m-%d").date(), name))
        except ValueError:
            continue
    return sorted(out)


def _is_relevant(food_name, affected):
    """True if the food maps to one of a festival's affected commodities."""
    if not food_name:
        return False
    commodity = commodity_for(food_name).lower()
    return any(a in commodity or commodity in a for a in affected)


def festival_calendar_alerts(today=None, horizon_days=200, food_name=None):
    """Upcoming/active/just-passed festival demand remarks.

    Returns list of {icon, en, zh, severity}. `severity` is 'high' when the
    festival's demand clearly affects `food_name`, else 'info'. General
    Malaysian knowledge - every remark is labelled as a general pattern.

    `horizon_days` is wide (~6.5 months) so the next festival is always shown;
    festivals up to 21 days past are still flagged for the post-festival dip.
    """
    if today is None:
        today = date.today()
    alerts = []
    for fdate, name in _parse_festivals():
        days_to = (fdate - today).days
        if days_to < -21 or days_to > horizon_days:
            continue
        eff = FESTIVAL_EFFECTS.get(name, {})
        lead_days = int(eff.get("lead_weeks", 3)) * 7
        relevant = _is_relevant(food_name, eff.get("affected", []))
        sev = "high" if relevant else "info"
        item_en = (f" In particular {commodity_for(food_name)} is affected."
                   if relevant else "")
        item_zh = (f" 其中「{food_name}」会受影响。" if relevant else "")
        gen_en = eff.get("en", "festival demand can lift prices")
        gen_zh = eff.get("zh", "节庆需求可能推高价格")

        if 0 <= days_to <= lead_days:
            # Demand window already open -> spike risk now
            alerts.append({
                "icon": "⚠️", "severity": sev,
                "en": (f"DEMAND WINDOW OPEN: {name} is in {days_to} day(s). "
                       f"General pattern - {gen_en}.{item_en} Consider stocking "
                       f"up early before prices rise."),
                "zh": (f"涨价窗口已开启：距离{_zh_name(name)}还有 {days_to} 天。"
                       f"一般规律——{gen_zh}。{item_zh}建议趁涨价前提前备货。"),
            })
        elif days_to > lead_days:
            # Still ahead, not yet in the build-up window
            wk = eff.get("lead_weeks", 3)
            alerts.append({
                "icon": "📅", "severity": sev,
                "en": (f"UPCOMING: {name} in {days_to} days. General pattern - "
                       f"{gen_en}; prices usually start climbing ~{wk} week(s) "
                       f"before.{item_en}"),
                "zh": (f"即将到来：距离{_zh_name(name)}还有 {days_to} 天。一般规律"
                       f"——{gen_zh}；通常节前约 {wk} 周开始涨价。{item_zh}"),
            })
        else:
            # Just passed -> demand normalises, possible dip (crash direction)
            alerts.append({
                "icon": "📉", "severity": "info",
                "en": (f"JUST PASSED: {name} was {-days_to} day(s) ago. General "
                       f"pattern - demand normalises afterwards, so some items "
                       f"(vegetables, seafood) may DIP from festival highs."),
                "zh": (f"刚过去：{_zh_name(name)}在 {-days_to} 天前。一般规律——"
                       f"节后需求回落，部分商品（蔬菜、海鲜）价格可能从节庆高位回跌。"),
            })
    return alerts


def _zh_name(name):
    return {
        "Chinese New Year": "农历新年",
        "Hari Raya Aidilfitri": "开斋节",
        "Hari Raya Aidiladha": "哈芝节",
        "Deepavali": "屠妖节",
    }.get(name, name)


def seasonal_extreme_alerts(food_name, location):
    """Data-driven high/low-month remarks from the item's own price history.

    Returns [] when there isn't enough history (seasonal_index empty / sparse).
    Both directions: 📈 most-expensive month, 📉 cheapest month.
    """
    idx = seasonal_index(food_name, location)
    if idx.empty or len(idx) < 6:
        return []

    alerts = []
    hi = idx.loc[idx["index"].idxmax()]
    lo = idx.loc[idx["index"].idxmin()]
    hi_dev = (float(hi["index"]) - 1) * 100
    lo_dev = (1 - float(lo["index"])) * 100
    cur_month = date.today().month

    if hi_dev >= 2:
        m = int(hi["month"])
        cur = "（就是本月！）" if m == cur_month else ""
        cur_en = " (this is the current month!)" if m == cur_month else ""
        alerts.append({
            "icon": "📈", "severity": "high" if m == cur_month else "info",
            "en": (f"From YOUR data: {food_name} is historically most expensive "
                   f"in {MONTH_EN[m-1]} (~{hi_dev:.0f}% above the yearly average, "
                   f"index {hi['index']:.2f}){cur_en}."),
            "zh": (f"根据你的数据：{food_name} 历史上 {MONTH_ZH[m-1]} 最贵"
                   f"（高于全年均价约 {hi_dev:.0f}%，季节指数 {hi['index']:.2f}）{cur}。"),
        })
    if lo_dev >= 2:
        m = int(lo["month"])
        cur = "（就是本月！）" if m == cur_month else ""
        cur_en = " (this is the current month!)" if m == cur_month else ""
        alerts.append({
            "icon": "📉", "severity": "high" if m == cur_month else "info",
            "en": (f"From YOUR data: {food_name} is historically cheapest in "
                   f"{MONTH_EN[m-1]} (~{lo_dev:.0f}% below the yearly average, "
                   f"index {lo['index']:.2f}){cur_en} - a good time to buy."),
            "zh": (f"根据你的数据：{food_name} 历史上 {MONTH_ZH[m-1]} 最便宜"
                   f"（低于全年均价约 {lo_dev:.0f}%，季节指数 {lo['index']:.2f}）{cur}"
                   f"，适合趁低买入。"),
        })
    return alerts


def price_calendar_alerts(food_name, location, today=None):
    """Combined festival (food-aware) + seasonal (data) remarks for the
    item-specific pages (Forecast, Seasonal & Anomalies)."""
    return (festival_calendar_alerts(today=today, food_name=food_name)
            + seasonal_extreme_alerts(food_name, location))
