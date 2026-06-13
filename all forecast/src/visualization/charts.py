import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
from src.database import get_prices, list_foods, list_locations

def create_price_trend_chart(food_name, location_name=None, days=90, price_type=None):
    """Create a line chart showing price trends over time.

    price_type optionally restricts to one layer (retail/wholesale/
    international/import_unit/controlled); None shows all.
    """
    prices = get_prices(food_name, location_name, price_type=price_type)

    if not prices:
        return None

    df = pd.DataFrame(prices)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')

    fig = go.Figure()

    if location_name:
        # Single location
        fig.add_trace(go.Scatter(
            x=df['date'],
            y=df['price'],
            mode='lines+markers',
            name=food_name,
            line=dict(color='#1f77b4', width=2),
            marker=dict(size=6),
            hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Price: MYR %{y:.2f}<extra></extra>'
        ))
    else:
        # Multiple locations
        for location in df['location'].unique():
            location_data = df[df['location'] == location].sort_values('date')
            fig.add_trace(go.Scatter(
                x=location_data['date'],
                y=location_data['price'],
                mode='lines+markers',
                name=location,
                hovertemplate='<b>%{x|%Y-%m-%d}</b><br>%{fullData.name}: MYR %{y:.2f}<extra></extra>'
            ))

    fig.update_layout(
        title=f"Price Trend: {food_name}" + (f" @ {location_name}" if location_name else " (All Locations)"),
        xaxis_title="Date",
        yaxis_title="Price (MYR)",
        hovermode='x unified',
        template='plotly_white',
        height=500
    )

    return fig

def create_regional_comparison_chart(food_name, locations=None):
    """Create a bar chart comparing prices across regions."""
    if locations is None:
        locations = [l['name'] for l in list_locations()]

    prices_data = []
    for loc in locations:
        prices = get_prices(food_name, loc)
        if prices:
            latest_price = prices[0]['price']  # Latest price
            prices_data.append({
                'location': loc,
                'price': latest_price,
                'currency': prices[0]['currency']
            })

    if not prices_data:
        return None

    df = pd.DataFrame(prices_data)
    df = df.sort_values('price', ascending=False)

    fig = go.Figure(data=[
        go.Bar(
            x=df['location'],
            y=df['price'],
            marker=dict(
                color=df['price'],
                colorscale='RdYlGn_r',
                showscale=True,
                colorbar=dict(title='Price (MYR)')
            ),
            text=df['price'].apply(lambda x: f'MYR {x:.2f}'),
            textposition='auto',
            hovertemplate='<b>%{x}</b><br>Price: MYR %{y:.2f}<extra></extra>'
        )
    ])

    fig.update_layout(
        title=f"Regional Price Comparison: {food_name}",
        xaxis_title="Location",
        yaxis_title="Price (MYR)",
        template='plotly_white',
        height=400,
        showlegend=False
    )

    return fig

def create_price_heatmap(foods=None, locations=None):
    """Create a heatmap showing food prices by location."""
    if foods is None:
        foods = [f['name'] for f in list_foods()]
    if locations is None:
        locations = [l['name'] for l in list_locations()]

    # Build matrix
    data_matrix = []
    for food in foods:
        row = []
        for location in locations:
            prices = get_prices(food, location)
            if prices:
                row.append(prices[0]['price'])  # Latest price
            else:
                row.append(None)
        data_matrix.append(row)

    fig = go.Figure(data=go.Heatmap(
        z=data_matrix,
        x=locations,
        y=foods,
        colorscale='YlOrRd',
        hovertemplate='Food: %{y}<br>Location: %{x}<br>Price: MYR %{z:.2f}<extra></extra>'
    ))

    fig.update_layout(
        title="Price Heatmap: Food × Location",
        xaxis_title="Location",
        yaxis_title="Food Item",
        template='plotly_white',
        height=600
    )

    return fig

def create_multi_food_comparison(food_names, location_name, days=90):
    """Create a line chart comparing multiple foods in one location."""
    all_prices = []
    for food in food_names:
        prices = get_prices(food, location_name)
        if prices:
            for p in prices:
                p['food'] = food
            all_prices.extend(prices)

    if not all_prices:
        return None

    df = pd.DataFrame(all_prices)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')

    fig = go.Figure()

    for food in food_names:
        food_data = df[df['food'] == food].sort_values('date')
        if not food_data.empty:
            fig.add_trace(go.Scatter(
                x=food_data['date'],
                y=food_data['price'],
                mode='lines+markers',
                name=food,
                hovertemplate='<b>%{x|%Y-%m-%d}</b><br>%{fullData.name}: MYR %{y:.2f}<extra></extra>'
            ))

    fig.update_layout(
        title=f"Food Comparison @ {location_name}",
        xaxis_title="Date",
        yaxis_title="Price (MYR)",
        hovermode='x unified',
        template='plotly_white',
        height=500
    )

    return fig

def create_kpi_cards_data(max_cards: int = 6):
    """Generate data for KPI cards: most local locations first (Lahad Datu),
    only food x location pairs that actually have 2+ prices."""
    from src.database import get_connection

    conn = get_connection()
    try:
        rows = conn.execute("""
            WITH ranked AS (
                SELECT f.name AS food, l.name AS location, l.level,
                       p.price, p.collected_date,
                       ROW_NUMBER() OVER (PARTITION BY p.food_id, p.location_id
                                          ORDER BY p.collected_date DESC) AS rn
                FROM prices p
                JOIN foods f ON p.food_id = f.id
                JOIN locations l ON p.location_id = l.id
            )
            SELECT cur.food, cur.location,
                   cur.price AS latest, prev.price AS previous
            FROM ranked cur
            JOIN ranked prev
              ON cur.food = prev.food AND cur.location = prev.location
             AND cur.rn = 1 AND prev.rn = 2
            WHERE prev.price > 0
            ORDER BY cur.level DESC, cur.food
            LIMIT ?
        """, [max_cards]).fetchall()
    finally:
        conn.close()

    kpis = []
    for food, location, latest, previous in rows:
        change_pct = (float(latest) - float(previous)) / float(previous) * 100
        kpis.append({
            'food': food,
            'location': location,
            'current_price': float(latest),
            'change_pct': round(change_pct, 2),
            'trend': 'up' if change_pct > 0 else ('down' if change_pct < 0 else 'flat'),
        })
    return kpis
