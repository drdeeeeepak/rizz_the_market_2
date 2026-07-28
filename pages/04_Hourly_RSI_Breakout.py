import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pytz

from data.live_fetcher import get_nifty_1h_phase, get_nifty_spot
from analytics.hourly_rsi_pivot import analyze_hourly_rsi


st.set_page_config(page_title="Hourly RSI Breakout", layout="wide")
st.title("🎯 Hourly RSI Breakout — HL/LH Pivot Signals")

# ─── Sidebar controls ─────────────────────────────────────────────────────────
st.sidebar.header("Settings")
days_to_fetch = st.sidebar.slider("Days of hourly data", 5, 30, 14)
rsi_period = st.sidebar.slider("RSI Period", 7, 21, 14)
lookback = st.sidebar.slider("Lookback for pivot detection", 2, 5, 3)

# ─── Fetch data ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner="Fetching hourly data...")
def load_hourly_data(days):
    df = get_nifty_1h_phase(days=days)
    if df.empty:
        st.error("Failed to fetch hourly data")
        return None
    return df


df_hourly = load_hourly_data(days_to_fetch)

if df_hourly is None or df_hourly.empty:
    st.warning("No data available")
    st.stop()

# Ensure datetime index
if not isinstance(df_hourly.index, pd.DatetimeIndex):
    df_hourly.index = pd.to_datetime(df_hourly.index)

# ─── Analyze RSI and pivots ───────────────────────────────────────────────────
df_analysis, signals = analyze_hourly_rsi(df_hourly, rsi_period=rsi_period, lookback=lookback)

# Get current spot
spot = get_nifty_spot()

# ─── Build chart ──────────────────────────────────────────────────────────────
fig = go.Figure()

# Add RSI line
fig.add_trace(go.Scatter(
    x=df_analysis.index,
    y=df_analysis['rsi'],
    mode='lines',
    name='RSI',
    line=dict(color='#0ea5e9', width=2),
    hovertemplate='<b>%{x|%Y-%m-%d %H:%M}</b><br>RSI: %{y:.2f}<extra></extra>'
))

# Add overbought (70) and oversold (30) zones
fig.add_hline(y=70, line_dash="dash", line_color="rgba(255, 0, 0, 0.3)", annotation_text="Overbought (70)")
fig.add_hline(y=30, line_dash="dash", line_color="rgba(0, 255, 0, 0.3)", annotation_text="Oversold (30)")

# Add 50 midline
fig.add_hline(y=50, line_dash="dot", line_color="rgba(200, 200, 200, 0.3)")

# Mark HL (Higher Low) pivots
hl_pivots = df_analysis[df_analysis['pivot_type'] == 'HL']
if not hl_pivots.empty:
    fig.add_trace(go.Scatter(
        x=hl_pivots.index,
        y=hl_pivots['pivot_value'],
        mode='markers',
        name='Higher Low (HL)',
        marker=dict(size=10, color='#10b981', symbol='circle', line=dict(color='#059669', width=2)),
        hovertemplate='<b>HL</b><br>%{x|%Y-%m-%d %H:%M}<br>RSI: %{y:.2f}<extra></extra>'
    ))

# Mark LH (Lower High) pivots
lh_pivots = df_analysis[df_analysis['pivot_type'] == 'LH']
if not lh_pivots.empty:
    fig.add_trace(go.Scatter(
        x=lh_pivots.index,
        y=lh_pivots['pivot_value'],
        mode='markers',
        name='Lower High (LH)',
        marker=dict(size=10, color='#ef4444', symbol='diamond', line=dict(color='#dc2626', width=2)),
        hovertemplate='<b>LH</b><br>%{x|%Y-%m-%d %H:%M}<br>RSI: %{y:.2f}<extra></extra>'
    ))

# Mark breakout signals
if signals:
    buy_signals = [s for s in signals if s['signal'] == 'BUY']
    sell_signals = [s for s in signals if s['signal'] == 'SELL']

    if buy_signals:
        buy_times = [df_analysis.index[s['index']] for s in buy_signals if s['index'] < len(df_analysis)]
        buy_rsis = [s['rsi_at_signal'] for s in buy_signals]
        fig.add_trace(go.Scatter(
            x=buy_times,
            y=buy_rsis,
            mode='markers+text',
            name='BUY Signal',
            marker=dict(size=14, color='#00ff00', symbol='triangle-up', line=dict(color='#00aa00', width=2)),
            text=['BUY'] * len(buy_times),
            textposition='top center',
            hovertemplate='<b>BUY</b><br>%{x|%Y-%m-%d %H:%M}<br>RSI: %{y:.2f}<extra></extra>'
        ))

    if sell_signals:
        sell_times = [df_analysis.index[s['index']] for s in sell_signals if s['index'] < len(df_analysis)]
        sell_rsis = [s['rsi_at_signal'] for s in sell_signals]
        fig.add_trace(go.Scatter(
            x=sell_times,
            y=sell_rsis,
            mode='markers+text',
            name='SELL Signal',
            marker=dict(size=14, color='#ff0000', symbol='triangle-down', line=dict(color='#aa0000', width=2)),
            text=['SELL'] * len(sell_times),
            textposition='bottom center',
            hovertemplate='<b>SELL</b><br>%{x|%Y-%m-%d %H:%M}<br>RSI: %{y:.2f}<extra></extra>'
        ))

# Layout
fig.update_layout(
    title=f"Hourly RSI Pivots — Nifty Spot: {spot:.2f}",
    xaxis_title="Time (UTC)",
    yaxis_title="RSI",
    hovermode='x unified',
    height=600,
    template='plotly_dark',
    xaxis=dict(rangeslider=dict(visible=False)),
    yaxis=dict(range=[0, 100])
)

st.plotly_chart(fig, use_container_width=True)

# ─── Display signals table ─────────────────────────────────────────────────────
st.subheader("📊 Breakout Signals")

if signals:
    signals_df = pd.DataFrame(signals)
    # Convert index to datetime
    signals_df['Time'] = signals_df['index'].apply(lambda i: df_analysis.index[i] if i < len(df_analysis) else None)
    signals_df = signals_df[['Time', 'signal', 'pivot_level', 'rsi_at_signal']].rename(columns={
        'signal': 'Signal',
        'pivot_level': 'Pivot Level',
        'rsi_at_signal': 'RSI at Signal'
    })

    # Color signals
    signal_colors = []
    for sig in signals_df['Signal']:
        if sig == 'BUY':
            signal_colors.append('background-color: #10b981')
        else:
            signal_colors.append('background-color: #ef4444')

    st.dataframe(
        signals_df.style.apply(lambda row: [signal_colors[row.name] if 'Signal' == col else '' for col in signals_df.columns], axis=1),
        use_container_width=True
    )
else:
    st.info("No breakout signals yet")

# ─── Display pivot summary ────────────────────────────────────────────────────
st.subheader("📍 Current Pivot Status")

col1, col2, col3 = st.columns(3)

# Get last HL
last_hl = df_analysis[df_analysis['pivot_type'] == 'HL'].tail(1)
if not last_hl.empty:
    hl_value = last_hl['pivot_value'].values[0]
    hl_time = last_hl.index[0]
    col1.metric("📈 Last Higher Low (HL)", f"{hl_value:.2f}", help=f"Set at {hl_time}")
else:
    col1.metric("📈 Last Higher Low (HL)", "—")

# Get last LH
last_lh = df_analysis[df_analysis['pivot_type'] == 'LH'].tail(1)
if not last_lh.empty:
    lh_value = last_lh['pivot_value'].values[0]
    lh_time = last_lh.index[0]
    col2.metric("📉 Last Lower High (LH)", f"{lh_value:.2f}", help=f"Set at {lh_time}")
else:
    col2.metric("📉 Last Lower High (LH)", "—")

# Current RSI
current_rsi = df_analysis['rsi'].dropna().iloc[-1] if not df_analysis['rsi'].dropna().empty else None
if current_rsi:
    col3.metric("🎯 Current RSI", f"{current_rsi:.2f}")
else:
    col3.metric("🎯 Current RSI", "—")

# ─── Display recent hourly data ────────────────────────────────────────────────
st.subheader("📋 Recent Hourly Candles")

recent_df = df_analysis[['open', 'high', 'low', 'close', 'volume', 'rsi', 'pivot_type']].tail(20).copy()
recent_df.index.name = 'Time'
recent_df = recent_df.rename(columns={'pivot_type': 'Pivot'})

st.dataframe(recent_df, use_container_width=True)
