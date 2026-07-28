import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pytz
import numpy as np

from data.live_fetcher import get_nifty_1h_phase, get_nifty_spot
from analytics.hourly_rsi_pivot import analyze_hourly_rsi


# Backtest functions inlined
def run_backtest(df, rsi_period, lookback):
    """Run backtest on strategy."""
    df = df.copy()
    df, signals = analyze_hourly_rsi(df, rsi_period, lookback)
    
    if not signals:
        return pd.DataFrame(), {}
    
    results = []
    for i, sig in enumerate(signals):
        sig_idx = sig['index']
        sig_type = sig['signal']
        sig_price = df['close'].iloc[sig_idx]
        sig_rsi = sig['rsi_at_signal']
        pivot = sig['pivot_level']
        
        # Find exit
        exit_idx = len(df) - 1
        for j in range(i + 1, len(signals)):
            if signals[j]['index'] > sig_idx:
                if (sig_type == 'BUY' and signals[j]['signal'] == 'SELL') or \
                   (sig_type == 'SELL' and signals[j]['signal'] == 'BUY'):
                    exit_idx = signals[j]['index']
                    break
        
        exit_price = df['close'].iloc[exit_idx]
        pnl_pts = (exit_price - sig_price) if sig_type == 'BUY' else (sig_price - exit_price)
        pnl_pct = (pnl_pts / sig_price * 100) if sig_price != 0 else 0
        
        results.append({
            'signal_type': sig_type,
            'signal_time': df.index[sig_idx],
            'signal_price': sig_price,
            'signal_rsi': sig_rsi,
            'pivot_level': pivot,
            'exit_time': df.index[exit_idx],
            'exit_price': exit_price,
            'pnl_pts': pnl_pts,
            'pnl_pct': pnl_pct,
            'bars_held': exit_idx - sig_idx
        })
    
    result_df = pd.DataFrame(results)
    
    # Stats
    stats = {
        'total_trades': len(result_df),
        'winning_trades': (result_df['pnl_pct'] > 0).sum(),
        'losing_trades': (result_df['pnl_pct'] < 0).sum(),
        'total_pnl_pct': result_df['pnl_pct'].sum(),
        'avg_pnl_pct': result_df['pnl_pct'].mean(),
        'max_win_pct': result_df['pnl_pct'].max(),
        'max_loss_pct': result_df['pnl_pct'].min(),
        'win_rate': (result_df['pnl_pct'] > 0).sum() / len(result_df) * 100 if len(result_df) > 0 else 0
    }
    
    return result_df, stats


# Page 04 Pattern: Live Indicator Best Practice (CLAUDE.md Rule 7)
# 1. Fetch max history for accurate RSI (365 days)
# 2. Display only recent window (7 days chart)
# 3. Preserve debug output (diagnostics) for troubleshooting
# This prevents cached-stale-data issues and catches Kite mismatches fast.

st.set_page_config(page_title="Hourly RSI Breakout", layout="wide")
st.title("🎯 Hourly RSI Breakout — HL/LH Pivot Signals")

# Sidebar controls
st.sidebar.header("Settings")
rsi_period = st.sidebar.slider("RSI Period", 7, 21, 14)
lookback = st.sidebar.slider("Lookback for pivot detection", 2, 5, 3)

# Fetch maximum available data for accurate RSI calculation
@st.cache_data(ttl=300, show_spinner="Fetching hourly data...")
def load_hourly_data():
    df = get_nifty_1h_phase(days=365)
    if df.empty:
        st.error("Failed to fetch hourly data")
        return None
    return df

df_hourly = load_hourly_data()

if df_hourly is None or df_hourly.empty:
    st.warning("No data available")
    st.stop()

if not isinstance(df_hourly.index, pd.DatetimeIndex):
    df_hourly.index = pd.to_datetime(df_hourly.index)

df_analysis, signals = analyze_hourly_rsi(df_hourly, rsi_period=rsi_period, lookback=lookback)
spot = get_nifty_spot()

# Chart: 7 days RSI (calculated from all available data, displayed for last 7 days)
seven_days_ago = df_analysis.index[-1] - timedelta(days=7)
df_chart = df_analysis[df_analysis.index >= seven_days_ago]

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=df_chart.index,
    y=df_chart['rsi'],
    mode='lines',
    name='RSI',
    line=dict(color='#0ea5e9', width=2)
))

fig.add_hline(y=70, line_dash="dash", line_color="rgba(255,0,0,0.3)", annotation_text="Overbought (70)")
fig.add_hline(y=30, line_dash="dash", line_color="rgba(0,255,0,0.3)", annotation_text="Oversold (30)")
fig.add_hline(y=50, line_dash="dot", line_color="rgba(200,200,200,0.3)")

# HL pivots (7 days)
hl_pivots = df_chart[df_chart['pivot_type'] == 'HL']
if not hl_pivots.empty:
    fig.add_trace(go.Scatter(
        x=hl_pivots.index,
        y=hl_pivots['pivot_value'],
        mode='markers',
        name='HL (Higher Low)',
        marker=dict(size=10, color='#10b981', symbol='circle')
    ))

# LH pivots (7 days)
lh_pivots = df_chart[df_chart['pivot_type'] == 'LH']
if not lh_pivots.empty:
    fig.add_trace(go.Scatter(
        x=lh_pivots.index,
        y=lh_pivots['pivot_value'],
        mode='markers',
        name='LH (Lower High)',
        marker=dict(size=10, color='#ef4444', symbol='diamond')
    ))

# Signals (7 days)
if signals:
    buy_sig = [s for s in signals if s['signal'] == 'BUY' and df_analysis.index[s['index']] >= seven_days_ago]
    sell_sig = [s for s in signals if s['signal'] == 'SELL' and df_analysis.index[s['index']] >= seven_days_ago]

    if buy_sig:
        buy_times = [df_analysis.index[s['index']] for s in buy_sig]
        buy_rsis = [s['rsi_at_signal'] for s in buy_sig]
        fig.add_trace(go.Scatter(
            x=buy_times, y=buy_rsis, mode='markers+text', name='BUY',
            marker=dict(size=14, color='#00ff00', symbol='triangle-up'),
            text=['BUY']*len(buy_times), textposition='top center'
        ))

    if sell_sig:
        sell_times = [df_analysis.index[s['index']] for s in sell_sig]
        sell_rsis = [s['rsi_at_signal'] for s in sell_sig]
        fig.add_trace(go.Scatter(
            x=sell_times, y=sell_rsis, mode='markers+text', name='SELL',
            marker=dict(size=14, color='#ff0000', symbol='triangle-down'),
            text=['SELL']*len(sell_times), textposition='bottom center'
        ))

fig.update_layout(
    title=f"Hourly RSI (7 Days) — Nifty: {spot:.2f}",
    xaxis_title="Time",
    yaxis_title="RSI",
    height=600,
    template='plotly_dark',
    hovermode='x unified',
    yaxis=dict(range=[0, 100])
)

st.plotly_chart(fig, use_container_width=True)

# Signals table (last 5 signals)
st.subheader("📊 Breakout Signals (Last 5)")
if signals:
    sig_df = pd.DataFrame(signals)
    sig_df['Time'] = sig_df['index'].apply(lambda i: df_analysis.index[i] if i < len(df_analysis) else None)
    sig_df = sig_df[['Time', 'signal', 'pivot_level', 'rsi_at_signal']].rename(columns={
        'signal': 'Signal', 'pivot_level': 'Pivot', 'rsi_at_signal': 'RSI'
    })
    sig_df = sig_df.iloc[::-1].reset_index(drop=True)  # Reverse to show latest first
    sig_df = sig_df.head(5)  # Show only last 5 signals

    # Color only the Signal column
    def style_signal_column(val):
        if val == 'BUY':
            return 'background-color: #10b981; color: white; font-weight: bold'
        elif val == 'SELL':
            return 'background-color: #ef4444; color: white; font-weight: bold'
        return ''

    styled_df = sig_df.style.applymap(style_signal_column, subset=['Signal'])
    st.dataframe(styled_df, use_container_width=True)
else:
    st.info("No signals yet")

# Pivot status
st.subheader("📍 Current Pivots")
col1, col2, col3 = st.columns(3)
last_hl = df_analysis[df_analysis['pivot_type'] == 'HL'].tail(1)
if not last_hl.empty:
    col1.metric("HL", f"{last_hl['pivot_value'].values[0]:.2f}")
else:
    col1.metric("HL", "—")

last_lh = df_analysis[df_analysis['pivot_type'] == 'LH'].tail(1)
if not last_lh.empty:
    col2.metric("LH", f"{last_lh['pivot_value'].values[0]:.2f}")
else:
    col2.metric("LH", "—")

current_rsi = df_analysis['rsi'].dropna().iloc[-1] if not df_analysis['rsi'].dropna().empty else None
if current_rsi:
    col3.metric("Current RSI", f"{current_rsi:.2f}")
else:
    col3.metric("Current RSI", "—")

# Backtest section
st.divider()
st.subheader("🧪 Backtest")
st.info(f"Real data: {len(df_analysis)} hourly candles from Kite API")

if st.button("▶ Run Backtest", use_container_width=True):
    with st.spinner(f"Backtesting {len(df_analysis)} candles..."):
        backtest_df, stats = run_backtest(df_analysis, rsi_period, lookback)
    
    if not backtest_df.empty:
        st.success(f"✅ {stats['total_trades']} trades | {stats['win_rate']:.1f}% win rate | {stats['total_pnl_pct']:.2f}% P&L")
        
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Trades", stats['total_trades'])
        col2.metric("Wins", stats['winning_trades'])
        col3.metric("Losses", stats['losing_trades'])
        col4.metric("Avg P&L", f"{stats['avg_pnl_pct']:.2f}%")
        col5.metric("Total P&L", f"{stats['total_pnl_pct']:.2f}%")
        
        # Results table
        st.subheader("Trade Results (Latest First)")
        display_df = backtest_df.copy()
        display_df['signal_time'] = display_df['signal_time'].dt.strftime('%Y-%m-%d %H:%M')
        display_df['exit_time'] = display_df['exit_time'].dt.strftime('%Y-%m-%d %H:%M')
        display_df = display_df[[
            'signal_type', 'signal_time', 'signal_price', 'signal_rsi',
            'exit_time', 'exit_price', 'pnl_pts', 'pnl_pct', 'bars_held'
        ]].rename(columns={
            'signal_type': 'Type', 'signal_time': 'Entry', 'signal_price': 'Entry$',
            'signal_rsi': 'RSI@Entry', 'exit_time': 'Exit', 'exit_price': 'Exit$',
            'pnl_pts': 'P&L(pts)', 'pnl_pct': 'P&L(%)', 'bars_held': 'Hrs'
        })

        # Reverse to show latest first
        display_df = display_df.iloc[::-1].reset_index(drop=True)

        # Add color styling
        def style_backtest(row):
            if row['Type'] == 'BUY':
                return ['background-color: #10b981; color: white'] * len(row)
            else:
                return ['background-color: #ef4444; color: white'] * len(row)

        styled_backtest = display_df.style.apply(style_backtest, axis=1)
        st.dataframe(styled_backtest, use_container_width=True)
        
        # CSV download
        csv = backtest_df.to_csv(index=False)
        st.download_button(
            "📥 Download CSV", csv,
            f"backtest_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "text/csv", use_container_width=True
        )
        
        # P&L chart
        st.subheader("P&L Chart")
        chart_df = backtest_df.copy()
        chart_df['cumulative'] = chart_df['pnl_pct'].cumsum()
        chart_df['trade'] = range(1, len(chart_df) + 1)
        
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            x=chart_df['trade'], y=chart_df['pnl_pct'],
            name='Per-Trade P&L',
            marker=dict(color=['#10b981' if x > 0 else '#ef4444' for x in chart_df['pnl_pct']]),
            opacity=0.6
        ))
        fig2.add_trace(go.Scatter(
            x=chart_df['trade'], y=chart_df['cumulative'],
            name='Cumulative', mode='lines+markers',
            line=dict(color='#0ea5e9', width=3)
        ))
        fig2.update_layout(
            title="P&L Analysis", xaxis_title="Trade #", yaxis_title="P&L (%)",
            height=400, template='plotly_dark', barmode='overlay'
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.warning("No trades in backtest period")
