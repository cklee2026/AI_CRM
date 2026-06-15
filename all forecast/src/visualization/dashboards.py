import sys
from pathlib import Path

# Streamlit runs this file directly, so add the project root to the path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
from src.database import list_foods, list_locations, get_prices, add_price, delete_food
from src.visualization.charts import (
    create_price_trend_chart,
    create_regional_comparison_chart,
    create_price_heatmap,
    create_kpi_cards_data
)

st.set_page_config(page_title="Food Price Tracker", layout="wide")

# Auto-update data on startup (if last update was > 1 day ago)
@st.cache_resource
def auto_update_on_startup():
    import json
    from pathlib import Path

    last_update_file = Path("./data/.last_update")
    now = datetime.now()
    should_update = True

    # Check if we updated in the last 24 hours
    if last_update_file.exists():
        try:
            with open(last_update_file, 'r') as f:
                last_update = datetime.fromisoformat(json.load(f)["timestamp"])
                if (now - last_update).total_seconds() < 86400:  # 24 hours
                    should_update = False
        except:
            pass

    if should_update:
        try:
            st.info("📡 Auto-updating price data... (this runs once per day)")
            from src.scrapers.pricecatcher import run as run_pricecatcher
            result = run_pricecatcher(months_back=1)

            # Save last update time
            last_update_file.parent.mkdir(parents=True, exist_ok=True)
            with open(last_update_file, 'w') as f:
                json.dump({"timestamp": now.isoformat()}, f)

            st.success(f"✅ {result['message']}")
        except Exception as e:
            st.warning(f"⚠️ Auto-update failed: {str(e)[:100]}. Check your internet connection.")

auto_update_on_startup()

st.title("Food Price Tracker")
st.markdown("Track food prices across International / Malaysia / Sabah / Lahad Datu")

page = st.sidebar.radio("Navigate", [
    "使用指南",
    "Overview",
    "Trend Analysis",
    "Price Analysis",
    "Forecast",
    "Regional Comparison",
    "Price Chain",
    "Report Builder",
    "Seasonal & Anomalies",
    "Price Alerts",
    "Heatmap",
    "Track New Item",
    "Add Price",
    "Data",
    "AI Settings",
])

@st.cache_data(ttl=300)
def load_foods():
    return [f['name'] for f in list_foods()]

@st.cache_data(ttl=300)
def load_locations():
    return [l['name'] for l in list_locations()]

@st.cache_data(ttl=300)
def foods_with_data():
    """Food names that actually have prices, most data first."""
    from src.database import get_connection
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT f.name, COUNT(*) AS n
            FROM prices p JOIN foods f ON p.food_id = f.id
            GROUP BY 1 ORDER BY n DESC
        """).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()

foods = load_foods()
locations = load_locations()

# ============ 使用指南 ============
if page == "使用指南":
    st.header("🎓 Food Price Tracker — User Guide / 使用指南")

    tab_zh, tab_en = st.tabs(["中文 Chinese", "English"])

    with tab_zh:
        st.markdown("""
## 系统概述

这是一个**食品价格监测和预测工具**，能追踪马来西亚各地食品价格，帮助你：
- 📊 看价格趋势（过去）
- 🔮 预测未来价格（未来）
- 📍 比较不同地区的价格差异
- 🚨 发现异常的价格峰值
- 📈 分析产品的季节性规律

数据来源：**KPDN（马来西亚国内贸易部）官方价格数据** + 你手工添加的本地市场价

---

## 快速开始（3 步）

### 1️⃣ 查看现有数据
→ 点击 **Overview** 看仪表盘首页，显示最新价格和热力图

### 2️⃣ 追踪新产品（可选）
→ 点击 **Track New Item**，搜索想要的产品（用马来语搜，如 BAWANG、IKAN、DAGING），系统自动拉回一年数据

### 3️⃣ 添加本地市场价（可选）
→ 点击 **Add Price**，手工输入你在巴刹或超市看到的价格。这样可以补充官方数据没有的信息

---

## 导航功能详解

### 📊 **数据查看与分析**

| 功能 | 用途 | 怎么用 |
|------|------|--------|
| **Overview** | 仪表盘首页 | 看最新4个产品的价格 + 热力图全景。可自定义显示哪些产品 |
| **Trend Analysis** | 趋势分析 | 选一个产品和地点，看价格在一段时间内怎么变化。显示涨跌幅度 |
| **Price Analysis** | 正式价格分析 | 统计分析价格变化的原因。可测试国际价是否驱动本地价 |
| **Regional Comparison** | 地区对比 | 同一产品在国际/沙巴/Lahad Datu 的价格对比。看地区差异 |
| **Price Chain** | 价格链对比 | 同一产品的国际价→批发价→零售价叠在一起看，理解供应链加价 |
| **Heatmap** | 热力图 | 看所有产品×地点的价格热力图。颜色越深价格越高 |

### 🔮 **预测与规律**

| 功能 | 用途 | 怎么用 |
|------|------|--------|
| **Forecast** | 价格预测 | 用历史数据预测未来价格。显示趋势+季节性+95% 信心区间。可预测周或月 |
| **Seasonal & Anomalies** | 季节性与异常 | 分析通常哪些月份贵/便宜，检测异常峰值（突然大涨/大跌） |
| **Price Alerts** | 价格警报 | 设定阈值（如 10%），自动找出超过这个幅度的价格变动 |

### 🛠️ **数据管理**

| 功能 | 用途 | 怎么用 |
|------|------|--------|
| **Report Builder** | 自定义报表 | 自由组合选食品、地点、时间、图表类型，生成你想要的报表 |
| **Track New Item** | 追踪新产品 | 从 KPDN 官方目录搜索新产品（几千个），系统自动拉数据 + 后续自动更新 |
| **Add Price** | 手动添加价格 | 输入你在本地市场看到的价格。用来补充官方数据 |
| **Data** | 数据表 | 看所有价格的原始表格，可筛选和导出 |

### ⚙️ **系统设置**

| 功能 | 用途 |
|------|------|
| **AI Settings** | 配置 API 密钥启用 AI 分析（可选）。会在 Forecast 页生成市场分析文字 |

---

## 常见任务

### 🎯 任务 1：我想知道 bawang merah 的价格趋势

1. 点击 **Trend Analysis**
2. 选择 Food = "Bawang Kecil Merah Rose Import (India)"
3. 选择 Location = "Lahad Datu"
4. 看图表，向下滚动看周/月变化表

### 🎯 任务 2：预测下个月鸡肉价格

1. 点击 **Forecast**
2. 选择 Food = "Chicken (Whole)"
3. 选择 Location = "Lahad Datu"
4. 调整 "Forecast by" = "month"，"Periods ahead" = 1
5. 看预测价格和置信区间

### 🎯 任务 3：找出异常价格变化

1. 点击 **Price Alerts**
2. 调整 "Alert threshold" 到你想要的百分比（如 10%）
3. 看列表，红色向上=涨价警告，绿色向下=降价

### 🎯 任务 4：添加我在巴刹看到的价格

1. 点击 **Add Price**
2. 填写：
   - Food = 产品名（如"Bawang Kecil Merah Rose"）
   - Price = 你看到的价格（如 5.90）
   - Date = 日期（今天）
   - Location = Lahad Datu
   - Price type = "retail"（零售价）
3. 点击"Record Price"提交

### 🎯 任务 5：追踪一个新产品

1. 点击 **Track New Item**
2. 在搜索框输入产品的马来语名字，如：
   - BAWANG（洋葱）
   - IKAN（鱼）
   - DAGING（肉）
   - SAYUR（蔬菜）
   - BUAH（水果）
3. 看搜索结果，点想要的产品旁的"Track this"
4. 系统自动拉回一年的历史数据，后续自动更新

---

## 💡 Tips

- **数据更新频率**：KPDN 数据每周更新一次（通常周一）
- **历史数据范围**：通常有 1-2 年的历史数据
- **地区级别**：
  - Malaysia = 全国平均（最多商家）
  - Sabah = 沙巴州平均
  - Lahad Datu = Lahad Datu 区（最详细的本地数据）
- **价格差异**：同一产品在超市和巴刹价格可能差很大，KPDN 只监控注册商家
- **手工添加价格**：用"Add Price"补充你的本地市场价，这样数据更完整

---

## 📞 遇到问题？

- **没有数据**：先点 "Track New Item" 添加你想追踪的产品
- **数据很少**：产品太冷门了，KPDN 可能不监控。用 "Add Price" 手工补充
- **价格和巴刹不符**：KPDN 只监控注册商家（超市、连锁店），不包括巴刹湿市场。价格差异是正常的
        """)

    with tab_en:
        st.markdown("""
## System Overview

A **food price monitoring and forecasting tool** that tracks food prices across Malaysia to help you:
- 📊 View price trends (past)
- 🔮 Predict future prices (future)
- 📍 Compare prices across different regions
- 🚨 Detect unusual price spikes
- 📈 Analyze seasonal patterns

Data source: **KPDN (Ministry of Domestic Trade, Malaysia) official price data** + your manually added local market prices

---

## Quick Start (3 Steps)

### 1️⃣ View Existing Data
→ Click **Overview** to see the dashboard with latest prices and heatmap

### 2️⃣ Track New Products (Optional)
→ Click **Track New Item**, search for products (use Malay keywords like BAWANG, IKAN, DAGING). System automatically pulls back one year of data

### 3️⃣ Add Local Market Prices (Optional)
→ Click **Add Price**, manually enter prices you saw at markets or stores. This supplements official data

---

## Navigation Features

### 📊 **Data View & Analysis**

| Feature | Purpose | How to Use |
|---------|---------|-----------|
| **Overview** | Dashboard | View latest 4 products + heatmap overview. Customize which products to display |
| **Trend Analysis** | Trend analysis | Select a product & location to see price changes over time. Shows price changes (%) |
| **Price Analysis** | Statistical analysis | Analyze reasons for price changes. Test if international prices drive local prices |
| **Regional Comparison** | Regional comparison | Compare same product across international/Sabah/Lahad Datu. See regional differences |
| **Price Chain** | Price chain | Stack international → wholesale → retail prices to understand supply chain markups |
| **Heatmap** | Heatmap visualization | See price heatmap for all products × locations. Darker color = higher price |

### 🔮 **Forecasting & Patterns**

| Feature | Purpose | How to Use |
|---------|---------|-----------|
| **Forecast** | Price forecasting | Predict future prices using historical data. Shows trend + seasonality + 95% confidence band. Forecast by week or month |
| **Seasonal & Anomalies** | Seasonal & anomaly detection | Analyze which months are typically expensive/cheap. Detect unusual spikes |
| **Price Alerts** | Price alerts | Set threshold (e.g., 10%). System auto-detects price changes exceeding threshold |

### 🛠️ **Data Management**

| Feature | Purpose | How to Use |
|---------|---------|-----------|
| **Report Builder** | Custom reports | Freely combine foods, locations, time periods, and chart types to build your report |
| **Track New Item** | Track new products | Search KPDN official catalog (thousands of items). System auto-pulls data + future updates |
| **Add Price** | Manual data entry | Enter prices you saw locally. Supplements official data |
| **Data** | Raw data table | View all price data in table format. Filter, sort, and export |

### ⚙️ **System Settings**

| Feature | Purpose |
|---------|---------|
| **AI Settings** | Configure API key to enable AI analysis (optional). Generates market analysis on Forecast page |

---

## Common Tasks

### 🎯 Task 1: I want to know bawang merah price trend

1. Click **Trend Analysis**
2. Select Food = "Bawang Kecil Merah Rose Import (India)"
3. Select Location = "Lahad Datu"
4. View chart, scroll down to see weekly/monthly changes

### 🎯 Task 2: Forecast next month's chicken price

1. Click **Forecast**
2. Select Food = "Chicken (Whole)"
3. Select Location = "Lahad Datu"
4. Set "Forecast by" = "month", "Periods ahead" = 1
5. View forecast price and confidence interval

### 🎯 Task 3: Find unusual price changes

1. Click **Price Alerts**
2. Adjust "Alert threshold" to your desired percentage (e.g., 10%)
3. View list: red up arrow = price increase warning, green down arrow = price decrease

### 🎯 Task 4: Add a price I saw at the market

1. Click **Add Price**
2. Fill in:
   - Food = Product name (e.g., "Bawang Kecil Merah Rose")
   - Price = Your observed price (e.g., 5.90)
   - Date = Date (today)
   - Location = Lahad Datu
   - Price type = "retail"
3. Click "Record Price" to submit

### 🎯 Task 5: Track a new product

1. Click **Track New Item**
2. Enter product's Malay name in search box:
   - BAWANG (onion)
   - IKAN (fish)
   - DAGING (meat)
   - SAYUR (vegetables)
   - BUAH (fruit)
3. View search results, click "Track this" next to desired product
4. System auto-pulls one year of history, updates automatically thereafter

---

## 💡 Tips

- **Data update frequency**: KPDN data updates weekly (usually Mondays)
- **Historical data range**: Typically 1-2 years of history
- **Regional levels**:
  - Malaysia = National average (most shops)
  - Sabah = Sabah state average
  - Lahad Datu = Lahad Datu district (most detailed local data)
- **Price differences**: Same product can vary greatly between supermarkets and wet markets. KPDN only monitors registered shops
- **Manual price entry**: Use "Add Price" to supplement with local market prices for more complete data

---

## 📞 Troubleshooting

- **No data available**: First click "Track New Item" to add products you want to track
- **Too little data**: Product may be too niche for KPDN monitoring. Use "Add Price" to supplement
- **Price doesn't match wet market**: KPDN only monitors registered shops (supermarkets, chains), not wet markets. Price differences are normal
        """)


# ============ OVERVIEW ============
if page == "Overview":
    st.header("Overview Dashboard")

    all_kpis = create_kpi_cards_data(max_cards=50)
    all_kpi_labels = [f"{k['food']} @ {k['location']}" for k in all_kpis]

    default_kpi_labels = all_kpi_labels[:4]
    saved_kpi = st.session_state.get("overview_kpi_selection", default_kpi_labels)
    valid_saved_kpi = [x for x in saved_kpi if x in all_kpi_labels]

    with st.expander("Customize KPI cards", expanded=False):
        selected_kpi_labels = st.multiselect(
            "Select up to 4 items to show as KPI cards",
            options=all_kpi_labels,
            default=valid_saved_kpi,
            max_selections=4,
            key="overview_kpi_ms",
        )
        st.session_state["overview_kpi_selection"] = selected_kpi_labels

    display_kpis = [k for k in all_kpis if f"{k['food']} @ {k['location']}" in selected_kpi_labels]
    if not display_kpis:
        display_kpis = all_kpis[:4]

    if display_kpis:
        cols = st.columns(len(display_kpis))
        for i, kpi in enumerate(display_kpis):
            with cols[i]:
                st.metric(
                    label=f"{kpi['food']} @ {kpi['location']}",
                    value=f"{kpi['current_price']:.2f}",
                    delta=f"{kpi['change_pct']:.1f}%",
                    delta_color="inverse",
                )

    st.subheader("Price Heatmap: Food x Location")
    st.caption("Note: International prices are in USD; Malaysian locations in MYR.")

    foods_with_data_list = foods_with_data() or foods

    # Default heatmap to same foods as KPI selection, else fall back to top 8
    kpi_foods = list(dict.fromkeys([k['food'] for k in display_kpis]))
    default_heatmap = st.session_state.get("overview_heatmap_selection",
                      kpi_foods if kpi_foods else foods_with_data_list[:8])
    valid_default_heatmap = [x for x in default_heatmap if x in foods_with_data_list]
    if not valid_default_heatmap:
        valid_default_heatmap = kpi_foods if kpi_foods else foods_with_data_list[:8]

    with st.expander("Customize heatmap foods / 自定义热力图产品", expanded=False):
        selected_heatmap_foods = st.multiselect(
            "Select foods to show in heatmap (defaults to your KPI selection above)",
            options=foods_with_data_list,
            default=valid_default_heatmap,
            key="overview_heatmap_ms",
        )
        st.session_state["overview_heatmap_selection"] = selected_heatmap_foods

    heatmap_foods = selected_heatmap_foods if selected_heatmap_foods else \
                    (kpi_foods if kpi_foods else foods_with_data_list[:8])
    heatmap = create_price_heatmap(heatmap_foods, locations)
    if heatmap:
        st.plotly_chart(heatmap, width="stretch")
    else:
        st.info("No data available yet. Run the scrapers or add price entries first.")

# ============ TREND ANALYSIS ============
elif page == "Trend Analysis":
    st.header("Price Trend Analysis")

    col1, col2, col3 = st.columns(3)
    with col1:
        selected_food = st.selectbox("Select Food", foods)
    with col2:
        selected_location = st.selectbox("Select Location", ["All Locations"] + locations)
    with col3:
        selected_ptype = st.selectbox(
            "Price type", ["All", "retail", "wholesale", "international",
                           "import_unit", "controlled"], key="trend_ptype")

    location_param = None if selected_location == "All Locations" else selected_location
    ptype_param = None if selected_ptype == "All" else selected_ptype
    fig = create_price_trend_chart(selected_food, location_param, price_type=ptype_param)
    if fig:
        st.plotly_chart(fig, width="stretch")
    else:
        st.warning("No data available for this selection.")

    if location_param:
        prices = get_prices(selected_food, location_param, price_type=ptype_param)
        if prices:
            df = pd.DataFrame(prices)
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Latest Price", f"{df['price'].iloc[0]:.2f}")
            with col2:
                st.metric("Average", f"{df['price'].mean():.2f}")
            with col3:
                st.metric("Min", f"{df['price'].min():.2f}")
            with col4:
                st.metric("Max", f"{df['price'].max():.2f}")

        # Period summary table with up/down direction and reasons
        from src.analytics.trends import get_period_summary
        period = st.radio("Aggregate by", ["week", "month", "year"], horizontal=True)
        summary = get_period_summary(selected_food, location_param, period,
                                     price_type=ptype_param)
        if not summary.empty:
            display = summary.copy()
            display["period_start"] = display["period_start"].astype(str).str[:10]
            display = display.rename(columns={
                "period_start": "Period", "avg_price": "Avg", "min_price": "Min",
                "max_price": "Max", "change_pct": "Change %", "direction": "Trend",
                "notes": "Reasons", "price_count": "Samples"})
            st.dataframe(display, width="stretch", hide_index=True)

# ============ PRICE ANALYSIS ============
elif page == "Price Analysis":
    st.header("Price Analysis 正式价格分析")
    st.caption("纯统计、离线、不连网、不用 AI——从你的数据推导价格上下的依据。"
               "可分析国际价或马来西亚任一层；选一个国际商品可测它是否带动本地价。")

    ca, cb, cc = st.columns(3)
    with ca:
        pa_food = st.selectbox("Food 物品", foods, key="pa_food")
    with cb:
        pa_loc = st.selectbox("Location 地点", locations, key="pa_loc")
    with cc:
        pa_ptype = st.selectbox("Price type 价格层", ["All", "retail", "wholesale",
                                "international", "import_unit", "controlled"],
                                key="pa_ptype")

    pa_intl = st.selectbox(
        "（可选）测试国际驱动因素 — 选一个国际商品 / Optional international driver",
        ["（不测试 none）"] + foods, key="pa_intl")
    lang = st.radio("语言 Language", ["中文", "English"], horizontal=True, key="pa_lang")

    pa_ptype_param = None if pa_ptype == "All" else pa_ptype
    intl_param = None if pa_intl.startswith("（不测试") else pa_intl

    if st.button("分析 Analyze", type="primary"):
        from src.analytics.price_analysis import analyze_price
        rep = analyze_price(pa_food, pa_loc, price_type=pa_ptype_param,
                            intl_food=intl_param)
        if not rep["ok"]:
            st.warning("此选择没有数据 / No data for this selection.")
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("最新价 Latest", f"{rep['latest']:.2f}", help=rep["latest_date"])
            m2.metric("1个月 1m", f"{(rep['change'].get('1m') or 0):+.1f}%")
            m3.metric("3个月 3m", f"{(rep['change'].get('3m') or 0):+.1f}%")
            m4.metric("1年 1y", f"{(rep['change'].get('1y') or 0):+.1f}%")

            st.subheader("分析依据 Findings")
            conf_badge = {"high": "🟢", "medium": "🟡", "low": "⚪"}
            key = "zh" if lang == "中文" else "en"
            for fd in rep["findings"]:
                st.markdown(f"{fd['icon']} {conf_badge.get(fd['confidence'],'')} "
                            f"{fd[key]}")
            st.caption("🟢 高置信 / 🟡 中等 / ⚪ 仅供参考。全部由本地数据统计得出，"
                       "可复现、无需联网。")

            if intl_param and (not rep["intl_driver"] or
                               rep["intl_driver"]["correlation"] is None):
                st.info("国际驱动相关性无法计算：所选国际商品与本地价的时间段不重叠"
                        "（World Bank 数据目前停在 2024-12，需更新数据源）。")

            st.divider()
            st.subheader("🌐 真实世界驱动因素 Real-world drivers（联网，不用 AI）")
            st.caption("从公开数据拉柴油价、汇率、来源国/本地降雨、节庆日历，"
                       "和你的价格做去趋势相关性。进口物品自动看来源国天气。")
            if st.button("拉取并分析驱动因素 Fetch & analyze drivers"):
                from src.analytics.drivers import driver_findings
                from src.analytics.price_analysis import _series
                with st.spinner("正在从 data.gov.my / frankfurter / open-meteo 拉数据…"):
                    local = _series(pa_food, pa_loc, pa_ptype_param)
                    dres = driver_findings(local, pa_food)
                tag = ("进口（来源国：%s）" % dres["origin"] if dres["imported"]
                       else "本地产")
                st.caption(f"物品判定：**{tag}**")
                for fd in dres["findings"]:
                    st.markdown(f"{fd['icon']} {conf_badge.get(fd['confidence'],'')} "
                                f"{fd[key]}")

# ============ FORECAST ============
elif page == "Forecast":
    st.header("Price Forecast")
    st.caption("Predict future prices from historical data "
               "(linear trend + monthly seasonality, 95% confidence band).")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        selected_food = st.selectbox("Food", foods_with_data() or foods)
    with col2:
        loc_default = locations.index("Lahad Datu") if "Lahad Datu" in locations else 0
        selected_location = st.selectbox("Location", locations, index=loc_default)
    with col3:
        fc_period = st.selectbox("Forecast by", ["week", "month"])
    with col4:
        max_p = 12 if fc_period == "week" else 6
        fc_periods = st.slider("Periods ahead", 1, max_p, min(4, max_p))

    from src.analytics.forecast import forecast_prices
    try:
        result = forecast_prices(selected_food, selected_location, fc_periods, fc_period)
        hist = result["history"]
        fc = result["forecast"]
        meta = result["meta"]

        fig = go.Figure()
        # Confidence band
        fig.add_trace(go.Scatter(
            x=pd.concat([fc["date"], fc["date"][::-1]]),
            y=pd.concat([fc["hi"], fc["lo"][::-1]]),
            fill="toself", fillcolor="rgba(255,127,14,0.18)",
            line=dict(width=0), hoverinfo="skip",
            name="95% range", showlegend=True))
        # History
        fig.add_trace(go.Scatter(
            x=hist["date"], y=hist["price"], mode="lines+markers",
            name="History", line=dict(color="#1f77b4", width=2),
            marker=dict(size=5)))
        # Forecast (connect last actual to first forecast)
        fc_x = pd.concat([hist["date"].tail(1), fc["date"]])
        fc_y = pd.concat([hist["price"].tail(1), fc["forecast"]])
        fig.add_trace(go.Scatter(
            x=fc_x, y=fc_y, mode="lines+markers",
            name="Forecast", line=dict(color="#ff7f0e", width=2, dash="dash"),
            marker=dict(size=7, symbol="diamond")))

        fig.update_layout(
            title=f"{selected_food} @ {selected_location} - next {fc_periods} {fc_period}(s)",
            template="plotly_white", height=520,
            xaxis_title="Date", yaxis_title="Price", hovermode="x unified")
        st.plotly_chart(fig, width="stretch")

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.metric("Last actual", f"{hist['price'].iloc[-1]:.2f}")
        with col_b:
            delta = fc["forecast"].iloc[-1] - hist["price"].iloc[-1]
            st.metric(f"Forecast in {fc_periods} {fc_period}(s)",
                      f"{fc['forecast'].iloc[-1]:.2f}", delta=f"{delta:+.2f}",
                      delta_color="inverse")
        with col_c:
            st.metric("Model", meta["method"].replace(" + ", " +\n"))

        display = fc.copy()
        display["date"] = display["date"].astype(str).str[:10]
        display = display.rename(columns={
            "date": f"{fc_period.title()} starting", "forecast": "Forecast",
            "lo": "Low (95%)", "hi": "High (95%)"})
        st.dataframe(display, width="stretch", hide_index=True)

        # --- Why this forecast: evidence-based remarks ---
        st.subheader("Why this forecast / 预测依据")
        lang = st.radio("Language", ["中文", "English"], horizontal=True,
                        label_visibility="collapsed")
        lang_key = "zh" if lang == "中文" else "en"
        for remark in result["explanations"]:
            st.markdown(f"{remark['icon']} {remark[lang_key]}")

        st.caption("Forecasts are statistical estimates from past data - "
                   "collect more history for better accuracy. "
                   "预测为统计估计，数据越多越准确。")

        # --- Optional AI analysis (bring-your-own-key, see AI Settings) ---
        from src.ai_analysis import load_settings as load_ai, \
            generate_forecast_analysis, AIError
        ai = load_ai()
        st.divider()
        if ai.get("disabled_reason"):
            st.error("AI analysis was automatically turned off: "
                     f"{ai['disabled_reason']}")
        elif ai["enabled"]:
            if st.button("Generate AI market analysis / 生成 AI 市场分析",
                         type="secondary"):
                with st.spinner(f"Asking {ai['model']}..."):
                    try:
                        analysis = generate_forecast_analysis(
                            selected_food, selected_location, result,
                            lang=lang_key)
                        st.markdown(analysis)
                        st.caption(f"Generated by {ai['provider']} / {ai['model']} - "
                                   "AI text may contain general-knowledge claims; "
                                   "verify before business decisions.")
                    except AIError as e:
                        if e.kind == "budget":
                            st.error(f"{e}\n\nAI 余额/token 已用完 - AI 功能已自动关闭。"
                                     "充值后请到 AI Settings 重新开启。")
                        else:
                            st.error(str(e))
        else:
            st.caption("Want AI-written market analysis here? Add your API key "
                       "in the **AI Settings** page. 想要 AI 市场分析？"
                       "到 AI Settings 页面填入你的 API key。")
    except ValueError as e:
        st.info(str(e))

# ============ REGIONAL COMPARISON ============
elif page == "Regional Comparison":
    st.header("Regional Price Comparison")

    selected_food = st.selectbox("Select Food to Compare", foods)
    st.caption("International prices are in USD - compare Malaysian locations with each other.")

    fig = create_regional_comparison_chart(selected_food, locations)
    if fig:
        st.plotly_chart(fig, width="stretch")
    else:
        st.warning("No data available for this food.")

    st.subheader("Detailed Comparison")
    comparison_data = []
    for location in locations:
        prices = get_prices(selected_food, location)
        if prices:
            latest = prices[0]
            comparison_data.append({
                'Location': location,
                'Latest Price': f"{latest['price']:.2f}",
                'Currency': latest['currency'],
                'Date': latest['date'],
                'Source': latest['source'] or '-',
            })
    if comparison_data:
        st.dataframe(pd.DataFrame(comparison_data), width="stretch", hide_index=True)

# ============ PRICE CHAIN ============
elif page == "Price Chain":
    st.header("Price Chain Comparison 价格链对比")
    st.caption("把不同价格层叠在一起看：国际价(USD) → 沙巴批发价(MYR) → 零售价(MYR)。"
               "批发与零售同为 MYR、可直接比加价；国际价是 USD，画在右侧副轴只作趋势参考。")

    @st.cache_data(ttl=300)
    def layer_pairs(ptype):
        """[(label, food, location)] available for a given price_type."""
        from src.database import get_connection
        conn = get_connection()
        try:
            rows = conn.execute("""
                SELECT DISTINCT f.name, l.name
                FROM prices p
                JOIN foods f ON p.food_id = f.id
                JOIN locations l ON p.location_id = l.id
                WHERE p.price_type = ?
                ORDER BY f.name, l.name
            """, [ptype]).fetchall()
            return [(f"{f}  @ {l}", f, l) for f, l in rows]
        finally:
            conn.close()

    def pick_layer(col, title, ptype):
        with col:
            st.markdown(f"**{title}**")
            pairs = layer_pairs(ptype)
            if not pairs:
                st.caption("（暂无此层数据）")
                return None
            labels = ["— none —"] + [p[0] for p in pairs]
            choice = st.selectbox(title, labels, key=f"chain_{ptype}",
                                  label_visibility="collapsed")
            if choice == "— none —":
                return None
            label, food, loc = next(p for p in pairs if p[0] == choice)
            return {"ptype": ptype, "food": food, "loc": loc, "label": label}

    c1, c2, c3 = st.columns(3)
    intl = pick_layer(c1, "🌍 国际价 International (USD)", "international")
    whol = pick_layer(c2, "🚚 批发价 Wholesale (MYR)", "wholesale")
    retl = pick_layer(c3, "🏪 零售价 Retail (MYR)", "retail")

    selected = [s for s in (whol, retl, intl) if s]
    if not selected:
        st.info("从上面每一层各选一个物品来对比。批发价来自 FAMA(沙巴)，"
                "零售价来自 KPDN PriceCatcher，国际价来自 World Bank。")
    else:
        fig = go.Figure()
        myr_color = {"wholesale": "#1f77b4", "retail": "#d62728"}
        latest = {}
        for s in (whol, retl):
            if not s:
                continue
            rows = get_prices(s["food"], s["loc"], price_type=s["ptype"])
            if not rows:
                continue
            df = pd.DataFrame(rows).sort_values("date")
            fig.add_trace(go.Scatter(
                x=df["date"], y=df["price"], mode="lines+markers",
                name=f"{s['ptype']} · {s['food'][:24]}",
                line=dict(color=myr_color[s["ptype"]])))
            latest[s["ptype"]] = df.iloc[-1]
        if intl:
            rows = get_prices(intl["food"], intl["loc"], price_type="international")
            if rows:
                df = pd.DataFrame(rows).sort_values("date")
                fig.add_trace(go.Scatter(
                    x=df["date"], y=df["price"], mode="lines+markers",
                    name=f"international · {intl['food'][:24]} (USD)",
                    line=dict(color="#2ca02c", dash="dot"), yaxis="y2"))
                latest["international"] = df.iloc[-1]

        fig.update_layout(
            height=480,
            yaxis=dict(title="MYR (批发/零售)"),
            yaxis2=dict(title="USD (国际)", overlaying="y", side="right",
                        showgrid=False),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(t=60))
        st.plotly_chart(fig, width="stretch")

        # Markup summary: retail vs wholesale (both MYR, comparable)
        if "wholesale" in latest and "retail" in latest:
            w = float(latest["wholesale"]["price"])
            r = float(latest["retail"]["price"])
            markup = (r - w) / w * 100 if w else 0
            m1, m2, m3 = st.columns(3)
            m1.metric("最新批发价 Wholesale", f"RM {w:.2f}",
                      help=str(latest["wholesale"]["date"]))
            m2.metric("最新零售价 Retail", f"RM {r:.2f}",
                      help=str(latest["retail"]["date"]))
            m3.metric("零售 vs 批发加价 Markup", f"{markup:+.1f}%",
                      delta_color="off")
            st.caption("⚠️ 批发与零售可能是不同来源的相近物品(FAMA vs PriceCatcher "
                       "命名不同)，加价仅供参考；选名称最接近的两项最准。")
        elif "wholesale" in latest or "retail" in latest:
            st.caption("再选另一个 MYR 层(批发或零售)即可显示加价对比。")

# ============ REPORT BUILDER ============
elif page == "Report Builder":
    st.header("Report Builder")
    st.caption("Pick any locations (state/district), foods, period and chart type "
               "to build your own visual report.")

    import plotly.express as px

    CHART_TYPES = ["Line", "Area", "Bar", "Pie", "Box", "Scatter", "Histogram"]

    col1, col2, col3 = st.columns(3)
    with col1:
        defaults = foods_with_data()[:3] or foods[:3]
        sel_foods = st.multiselect("Foods", foods, default=defaults)
    with col2:
        default_locs = [l for l in ["Malaysia", "Sabah", "Lahad Datu"] if l in locations]
        sel_locs = st.multiselect("Locations (state / district)", locations,
                                  default=default_locs or locations[:2])
    with col3:
        chart_type = st.selectbox("Chart type", CHART_TYPES)

    col4, col5, col6 = st.columns(3)
    with col4:
        period = st.selectbox("Aggregate by", ["raw data", "week", "month", "year"], index=1)
    with col5:
        rb_ptype = st.selectbox("Price type", ["All", "retail", "wholesale",
                                "international", "import_unit", "controlled"],
                                key="rb_ptype")
    with col6:
        days_back = st.slider("History (days back)", 30, 730, 400)

    rb_ptype_param = None if rb_ptype == "All" else rb_ptype

    # ---- Build the dataset ----
    rows = []
    for f in sel_foods:
        for loc in sel_locs:
            for p in get_prices(f, loc, price_type=rb_ptype_param):
                rows.append(p | {"food": f, "location": loc})

    if not rows:
        st.info("No data for this selection - pick other foods/locations.")
    else:
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        cutoff = pd.Timestamp(datetime.now().date() - timedelta(days=days_back))
        df = df[df["date"] >= cutoff]
        df["series"] = df["food"] + " @ " + df["location"]

        if period != "raw data" and chart_type not in ("Pie", "Histogram"):
            freq = {"week": "W-MON", "month": "MS", "year": "YS"}[period]
            df = (df.groupby(["series", "food", "location",
                              pd.Grouper(key="date", freq=freq)])["price"]
                    .mean().reset_index())

        if df.empty:
            st.info("No data in this date range - increase 'History (days back)'.")
        else:
            fig = None
            if chart_type == "Line":
                fig = px.line(df.sort_values("date"), x="date", y="price",
                              color="series", markers=True,
                              labels={"price": "Price", "date": "Date"})
            elif chart_type == "Area":
                fig = px.area(df.sort_values("date"), x="date", y="price",
                              color="series",
                              labels={"price": "Price", "date": "Date"})
            elif chart_type == "Bar":
                latest = (df.sort_values("date").groupby("series").tail(1))
                fig = px.bar(latest, x="food", y="price", color="location",
                             barmode="group", text_auto=".2f",
                             labels={"price": "Latest price"})
            elif chart_type == "Pie":
                pie_loc = sel_locs[0]
                latest = (df[df["location"] == pie_loc]
                          .sort_values("date").groupby("food").tail(1))
                if latest.empty:
                    st.info(f"No data at {pie_loc} for a pie chart.")
                else:
                    st.caption(f"Basket cost share at **{pie_loc}** "
                               "(latest price of each selected food)")
                    fig = px.pie(latest, names="food", values="price", hole=0.35)
                    fig.update_traces(texttemplate="%{label}<br>%{value:.2f} (%{percent})")
            elif chart_type == "Box":
                fig = px.box(df, x="series", y="price", color="location",
                             labels={"price": "Price distribution"})
            elif chart_type == "Scatter":
                fig = px.scatter(df.sort_values("date"), x="date", y="price",
                                 color="series", labels={"price": "Price"})
            elif chart_type == "Histogram":
                fig = px.histogram(df, x="price", color="series", barmode="overlay",
                                   labels={"price": "Price"})

            if fig is not None:
                fig.update_layout(template="plotly_white", height=520,
                                  legend_title_text="")
                st.plotly_chart(fig, width="stretch")

                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.download_button(
                        "Download chart (HTML, interactive)",
                        data=fig.to_html(include_plotlyjs="cdn"),
                        file_name="price_report.html", mime="text/html")
                with col_d2:
                    st.download_button(
                        "Download data (CSV)",
                        data=df.to_csv(index=False),
                        file_name="price_report_data.csv", mime="text/csv")

# ============ SEASONAL & ANOMALIES ============
elif page == "Seasonal & Anomalies":
    st.header("Seasonal Patterns & Anomaly Detection")

    col1, col2 = st.columns(2)
    with col1:
        selected_food = st.selectbox("Select Food", foods)
    with col2:
        selected_location = st.selectbox("Select Location", locations)

    from src.analytics.seasonal import seasonal_index, detect_anomalies

    idx = seasonal_index(selected_food, selected_location)
    if idx.empty:
        st.info("Not enough data for seasonal analysis (needs several months of history).")
    else:
        st.subheader("Seasonal Index by Month")
        st.caption("Index > 1.0 = typically expensive month, < 1.0 = typically cheap")
        colors = ["#d62728" if v > 1.02 else ("#2ca02c" if v < 0.98 else "#7f7f7f")
                  for v in idx["index"]]
        fig = go.Figure(go.Bar(
            x=idx["month_name"], y=idx["index"],
            marker_color=colors,
            text=idx["index"].apply(lambda v: f"{v:.2f}"),
            textposition="outside",
            hovertemplate="%{x}: index %{y:.3f}<extra></extra>",
        ))
        fig.add_hline(y=1.0, line_dash="dash", line_color="gray")
        fig.update_layout(template="plotly_white", height=400,
                          yaxis_title="Seasonal Index", xaxis_title="Month")
        st.plotly_chart(fig, width="stretch")

    st.subheader("Anomalies (unusual spikes/drops)")
    z = st.slider("Sensitivity (z-score threshold)", 1.5, 4.0, 2.0, 0.5)
    anomalies = detect_anomalies(selected_food, selected_location, z_threshold=z)
    if anomalies.empty:
        st.success("No anomalies detected at this sensitivity.")
    else:
        display = anomalies.copy()
        display["date"] = display["date"].astype(str).str[:10]
        st.dataframe(display, width="stretch", hide_index=True)

# ============ PRICE ALERTS ============
elif page == "Price Alerts":
    st.header("Price Spike Alerts")

    from src.alerts import detect_spikes

    threshold = st.slider("Alert threshold (%)", 1, 30, 10)
    spikes = detect_spikes(threshold)

    if not spikes:
        st.success(f"No price moves larger than {threshold}% detected.")
    else:
        st.warning(f"{len(spikes)} price spike(s) detected:")
        df = pd.DataFrame(spikes)[
            ["direction", "food", "location", "prev_price", "cur_price",
             "change_pct", "prev_date", "cur_date", "currency"]
        ].rename(columns={
            "direction": "Dir", "food": "Food", "location": "Location",
            "prev_price": "Previous", "cur_price": "Current",
            "change_pct": "Change %", "prev_date": "Prev Date",
            "cur_date": "Date", "currency": "Currency"})
        st.dataframe(df, width="stretch", hide_index=True)

    # Alert history
    log_path = Path("./data/alerts_log.csv")
    if log_path.exists():
        st.subheader("Alert History")
        history = pd.read_csv(log_path)
        st.dataframe(history.tail(50).iloc[::-1], width="stretch", hide_index=True)

# ============ HEATMAP ============
elif page == "Heatmap":
    st.header("Price Heatmap")

    col1, col2 = st.columns(2)
    with col1:
        selected_foods = st.multiselect("Select Foods", foods, default=foods[:5])
    with col2:
        selected_locations = st.multiselect("Select Locations", locations, default=locations)

    if selected_foods and selected_locations:
        fig = create_price_heatmap(selected_foods, selected_locations)
        if fig:
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No data for selected items.")

# ============ TRACK NEW ITEM ============
elif page == "Track New Item":
    st.header("Track a New Item")
    st.caption("Search the official KPDN catalog (thousands of items). When you "
               "track one, it is added to the database with a year of history "
               "backfilled, and weekly updates include it automatically.")
    st.info("Tip: search in Malay - BERAS (rice), IKAN (fish), DAGING (beef), "
            "SUSU (milk), SAYUR (vegetables), BUAH (fruit), ROTI (bread)")

    from src.scrapers.pricecatcher import search_catalog, track_item

    col_s1, col_s2 = st.columns([4, 1])
    with col_s1:
        keyword = st.text_input("Search the catalog",
                                placeholder="e.g. IKAN, DAGING, MILO...")
    with col_s2:
        st.write("")
        st.write("")
        refresh = st.button("Refresh catalog",
                            help="Re-download the official item list now "
                                 "(it also auto-refreshes weekly)")

    if refresh:
        try:
            with st.spinner("Re-downloading the official catalog..."):
                search_catalog("a", limit=1, force_refresh=True)
            st.success("Catalog refreshed from data.gov.my.")
        except Exception as e:
            st.error(f"Refresh failed: {e}")

    if keyword and len(keyword) >= 2:
        try:
            results = search_catalog(keyword, limit=30)
        except Exception as e:
            results = []
            st.error(f"Catalog search failed: {e}")

        if not results:
            st.warning(f"No items matching '{keyword}'.")
        else:
            df = pd.DataFrame(results)
            st.dataframe(df.rename(columns={
                "item_code": "Code", "item": "Item", "unit": "Unit",
                "group": "Group", "category": "Category"}),
                width="stretch", hide_index=True)

            options = {f"[{r['item_code']}] {r['item']} ({r['unit']})": r
                       for r in results}
            choice = st.selectbox("Pick an item to track", list(options.keys()))
            chosen = options[choice]

            col1, col2 = st.columns(2)
            with col1:
                custom_name = st.text_input("Food name in your tracker",
                                            value=chosen["item"].title())
            with col2:
                category = st.selectbox("Category", ["proteins", "grains", "oils",
                                                     "vegetables", "dairy", "fruits", "other"])

            if st.button("Track this item (adds to DB + backfills history)",
                         type="primary"):
                with st.spinner("Creating food and backfilling history..."):
                    try:
                        result = track_item(chosen["item_code"], custom_name,
                                            category, backfill=True)
                        st.success(
                            f"Now tracking '{result['item']}' as **{result['food']}** "
                            f"(per {result['unit']}). Backfilled "
                            f"{result['imported']} weekly prices.")
                        st.cache_data.clear()
                    except Exception as e:
                        st.error(f"Could not track item: {e}")

# ============ ADD PRICE ============
elif page == "Add Price":
    st.header("Add a Price Entry")
    st.caption("Record a price you saw at a local market, store, or online.")

    _PT_LABELS = {
        "retail": "零售价 Retail (shelf price)",
        "wholesale": "批发价 Wholesale (market borong)",
        "international": "国际价 International benchmark",
        "import_unit": "入口单价 Import unit value",
        "controlled": "统制价 Government ceiling",
    }
    with st.form("add_price_form"):
        col1, col2 = st.columns(2)
        with col1:
            food = st.selectbox("Food", foods)
            price = st.number_input("Price (MYR)", min_value=0.0, step=0.05, format="%.2f")
            collected = st.date_input("Date", value=date.today())
        with col2:
            location = st.selectbox("Location", locations)
            price_type = st.selectbox(
                "Price type 价格类型", list(_PT_LABELS.keys()),
                format_func=lambda k: _PT_LABELS[k],
                help="同一物品同一天可以分开存零售价和批发价等不同层次")
            source = st.text_input("Source (market/store name)", "")
            notes = st.text_input("Notes (reason for price change?)", "")

        submitted = st.form_submit_button("Save Price")
        if submitted:
            if price <= 0:
                st.error("Please enter a price greater than zero.")
            else:
                try:
                    add_price(food, location, price, collected,
                              source or None, notes or None,
                              price_type=price_type)
                    st.success(f"Saved: {food} @ {location} = MYR {price:.2f} "
                               f"({collected}, {price_type})")
                except Exception as e:
                    st.error(f"Could not save: {e}")

# ============ DATA ============
elif page == "Data":
    st.header("Price Data")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        selected_food = st.selectbox("Filter by Food", ["All"] + foods)
    with col2:
        selected_location = st.selectbox("Filter by Location", ["All"] + locations)
    with col3:
        selected_ptype = st.selectbox(
            "Price type", ["All", "retail", "wholesale", "international",
                           "import_unit", "controlled"])
    with col4:
        days_back = st.slider("Days Back", 1, 730, 365)

    food_param = None if selected_food == "All" else selected_food
    location_param = None if selected_location == "All" else selected_location
    ptype_param = None if selected_ptype == "All" else selected_ptype

    prices = get_prices(food_param, location_param, price_type=ptype_param)
    if prices:
        df = pd.DataFrame(prices)
        df['date'] = pd.to_datetime(df['date'])
        cutoff_date = datetime.now().date() - timedelta(days=days_back)
        df = df[df['date'].dt.date >= cutoff_date].sort_values('date', ascending=False)

        st.caption(f"{len(df)} price records")
        st.dataframe(
            df[['food', 'location', 'price_type', 'price', 'currency',
                'date', 'source', 'notes']],
            width="stretch", hide_index=True
        )

        csv = df.to_csv(index=False)
        st.download_button(
            label="Download CSV",
            data=csv,
            file_name="prices_export.csv",
            mime="text/csv"
        )
    else:
        st.info("No data found.")

    # ---- Manage / delete foods so dropdowns only show what you need ----
    st.divider()
    st.subheader("🗑️ 管理产品 / Manage items")
    st.caption("删除你不需要的产品，之后所有下拉框和搜索就不会再出现它们。"
               "删除会一并清掉该产品的价格记录，并停止自动更新。"
               "Delete items you don't need - they vanish from every dropdown, "
               "their prices are removed, and they won't be re-imported.")

    from src.database import get_connection as _gc
    _c = _gc()
    try:
        _rows = _c.execute("""
            SELECT f.name, COUNT(p.id) AS n
            FROM foods f LEFT JOIN prices p ON p.food_id = f.id
            GROUP BY f.name ORDER BY n DESC, f.name
        """).fetchall()
    finally:
        _c.close()
    food_label = {f"{name}  ({n} 笔价格 / records)": name for name, n in _rows}

    to_delete = st.multiselect(
        "选择要删除的产品 / Select items to delete",
        options=list(food_label.keys()), key="delete_food_ms")

    if to_delete:
        confirm = st.checkbox(
            f"我确认要永久删除这 {len(to_delete)} 个产品及其价格 / "
            f"Confirm permanent delete of {len(to_delete)} item(s)",
            key="delete_food_confirm")
        if st.button("删除 / Delete", type="primary", disabled=not confirm):
            removed = []
            for label in to_delete:
                try:
                    res = delete_food(food_label[label])
                    removed.append(f"{res['food']} ({res['prices_removed']} 笔)")
                except Exception as e:
                    st.error(f"删除 {food_label[label]} 失败: {e}")
            if removed:
                st.success("已删除 / Deleted: " + "; ".join(removed))
                st.cache_data.clear()  # refresh dropdown lists
                st.rerun()

# ============ AI SETTINGS ============
elif page == "AI Settings":
    st.header("AI Analysis Settings")
    st.caption("Bring your own API key to enable AI-written market analysis on "
               "the Forecast page. Off by default - the tracker works fully "
               "without it.")

    from src.ai_analysis import (load_settings, save_settings, test_connection,
                                 PROVIDERS)

    ai = load_settings()

    # Notification: auto-disabled because tokens ran out
    if ai.get("disabled_reason"):
        st.error(f"AI analysis was AUTOMATICALLY TURNED OFF "
                 f"({ai.get('disabled_at', '')}):\n\n{ai['disabled_reason']}")
        if st.button("I have topped up - clear this notice"):
            ai["disabled_reason"] = None
            ai["disabled_at"] = None
            save_settings(ai)
            st.rerun()

    enabled = st.toggle("Enable AI analysis", value=ai["enabled"])

    col1, col2 = st.columns(2)
    with col1:
        provider_names = list(PROVIDERS.keys())
        provider = st.selectbox(
            "Provider", provider_names,
            index=provider_names.index(ai["provider"])
            if ai["provider"] in provider_names else 0)
        preset = PROVIDERS[provider]
        base_default = ai["base_url"] if ai["provider"] == provider else preset["base_url"]
        base_url = st.text_input("API base URL", value=base_default,
                                 disabled=(provider == "DeepSeek"))
        if provider == "DeepSeek":
            base_url = preset["base_url"]
    with col2:
        model_default = ai["model"] if ai["provider"] == provider else preset["default_model"]
        model = st.text_input(
            "Model name (free text - any model your account supports)",
            value=model_default,
            placeholder="e.g. deepseek-v4-flash, deepseek-v4-pro")
        api_key = st.text_input("API key", value=ai["api_key"], type="password",
                                placeholder="sk-...")

    st.caption("Security: on Windows the key is encrypted with DPAPI (bound to "
               "your Windows account) - the settings file never contains the "
               "plaintext key, and it cannot be decrypted on another computer. "
               "密钥经 Windows DPAPI 加密保存，绑定你的 Windows 账户；"
               "搬去其他电脑后需重新输入一次。")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Save settings", type="primary"):
            ai.update({"enabled": enabled, "provider": provider,
                       "base_url": base_url, "model": model, "api_key": api_key})
            if enabled:
                ai["disabled_reason"] = None
                ai["disabled_at"] = None
            save_settings(ai)
            st.success("Settings saved." +
                       (" AI analysis is ON - see the Forecast page."
                        if enabled else " AI analysis is OFF."))
    with col_b:
        if st.button("Test connection"):
            probe = dict(ai)
            probe.update({"provider": provider, "base_url": base_url,
                          "model": model, "api_key": api_key})
            with st.spinner("Calling the API..."):
                ok, msg = test_connection(probe)
            if ok:
                st.success(msg)
            else:
                st.error(msg)

    st.divider()
    st.subheader("Usage")
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        st.metric("Total tokens used (this tracker)",
                  f"{ai.get('total_tokens_used', 0):,}")
    with col_u2:
        st.metric("Last used", ai.get("last_used") or "never")
    st.caption("Token counts come from the provider's API responses. "
               "When the provider reports your balance/quota is exhausted, "
               "AI analysis turns off automatically and a notice appears here "
               "and on the Forecast page.")

# ============ FOOTER ============
st.sidebar.markdown("---")
st.sidebar.markdown("**Food Price Tracker v2.0**")
st.sidebar.markdown("DuckDB + Streamlit | Data: KPDN PriceCatcher, World Bank")
st.sidebar.markdown("---")
st.sidebar.markdown(
    "<div style='font-size:11px; color:gray; text-align:center;'>"
    "© 2026 BIG LOBSTER TEAM 🦞<br>ALL RIGHTS RESERVED"
    "</div>",
    unsafe_allow_html=True
)
