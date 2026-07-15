# pages/28_Swing_RSI_Fade_Backtest.py
# Swing setup: Nifty tends to run one-sided for ~3-6 trading days, then reverse
# for a similar stretch. This page tests fading intraday RSI overbought/oversold
# extremes (30-minute and hourly) as the entry trigger for that turn — short on
# RSI overbought, long on RSI oversold — and compares the two timeframes head to
# head so the "which one's best" question in the setup gets an actual answer
# from history instead of a guess.

import importlib

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

import data.live_fetcher as _lf
from analytics import rsi_fade_backtest as rfb

try:
    importlib.reload(_lf)
    importlib.reload(rfb)
except Exception:
    pass

st.set_page_config(page_title="P28 · Swing RSI Fade Backtest", layout="wide")
st.title("Page 28 — Swing RSI Fade Backtest")
st.caption("Fade hourly / 30-minute RSI overbought & oversold extremes as a swing entry "
          "for the 3-6 day one-sided-move-then-reverse pattern.")

with st.expander("⚠️ What this tests (and its limits) — read once", expanded=False):
    st.markdown(
        "- **Fade = contrarian.** RSI overbought → go SHORT; RSI oversold → go LONG. One "
        "position at a time — a new signal while a trade is open is skipped, same as a real "
        "swing trader who can only carry one position on this setup.\n"
        "- **Entry mode — Touch vs Zone-exit.** *Touch* enters the instant RSI first crosses "
        "into the OB/OS zone. *Zone-exit* waits for RSI to cross back OUT of the zone before "
        "entering — more conservative, because during a genuine 3-6 day one-sided run RSI can "
        "sit pinned at an extreme for a day or more before actually turning; Touch risks eating "
        "that continuation before the real reversal starts.\n"
        "- **Exit = first of:** stop % hit, target % hit, RSI crossing back through the 50 "
        "midline (optional), or a time-stop after N candles held. If a single candle's range "
        "hits both stop and target, the stop is assumed to have won (conservative — OHLC alone "
        "can't tell you the intrabar order).\n"
        "- **Entries fill at the signal candle's close** — no slippage/spread modeled.\n"
        "- **Sample size matters.** A few hundred days of 30m/60m history only contains a "
        "couple dozen genuine OB/OS extremes per threshold — check `n_trades` before trusting "
        "any row's win-rate or expectancy.\n"
        "- History pulled live from Kite (`data/live_fetcher.py`) — needs a valid login via "
        "Home page.")

# ══════════════════════════════════════════════════════════════════════════════
# Live RSI Dashboard (60m + 30m for spread entry/management)
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("📊 Live RSI Dashboard — Spread Entry/Roll Signals")
st.caption("Real-time 60-minute & 30-minute RSI for Bull Put / Bear Call entry and position management")

@st.cache_data(ttl=120, show_spinner=False)
def _fetch_live_60m(days=6):
    try:
        return _lf.get_nifty_1h_phase(days=days)
    except Exception:
        return None

@st.cache_data(ttl=120, show_spinner=False)
def _fetch_live_30m(days=6):
    try:
        return _lf.get_nifty_30m(days=days)
    except Exception:
        return None

with st.spinner("Fetching live RSI data…"):
    df_live_60m = _fetch_live_60m(6)
    df_live_30m = _fetch_live_30m(6)

if (df_live_60m is None or df_live_60m.empty) and (df_live_30m is None or df_live_30m.empty):
    st.warning("Could not fetch live RSI data. Log in via Home page.")
else:
    # Calculate RSI for live data
    if df_live_60m is not None and not df_live_60m.empty:
        df_live_60m_rsi = rfb.compute_rsi(df_live_60m, 14)
        rsi_60m_current = df_live_60m_rsi["rsi"].iloc[-1] if len(df_live_60m_rsi) > 0 else None
        rsi_60m_prev = df_live_60m_rsi["rsi"].iloc[-2] if len(df_live_60m_rsi) > 1 else rsi_60m_current
        price_60m = df_live_60m_rsi["close"].iloc[-1] if len(df_live_60m_rsi) > 0 else None
    else:
        rsi_60m_current = rsi_60m_prev = price_60m = None

    if df_live_30m is not None and not df_live_30m.empty:
        df_live_30m_rsi = rfb.compute_rsi(df_live_30m, 14)
        rsi_30m_current = df_live_30m_rsi["rsi"].iloc[-1] if len(df_live_30m_rsi) > 0 else None
        rsi_30m_prev = df_live_30m_rsi["rsi"].iloc[-2] if len(df_live_30m_rsi) > 1 else rsi_30m_current
        price_30m = df_live_30m_rsi["close"].iloc[-1] if len(df_live_30m_rsi) > 0 else None
    else:
        rsi_30m_current = rsi_30m_prev = price_30m = None

    # Determine zones and trends
    def _rsi_zone(rsi_val):
        if rsi_val < 25:
            return "🟢", "OVERSOLD"
        elif rsi_val < 30:
            return "🟡", "CAUTION"
        elif rsi_val > 75:
            return "🟢", "OVERBOUGHT"
        elif rsi_val > 70:
            return "🟡", "CAUTION"
        else:
            return "⚫", "NEUTRAL"

    def _trend_arrow(prev, curr):
        if curr > prev + 2:
            return "↗ Rising"
        elif curr < prev - 2:
            return "↘ Falling"
        else:
            return "→ Flat"

    # Display RSI cards
    rsi_col1, rsi_col2 = st.columns(2)

    with rsi_col1:
        if rsi_60m_current is not None:
            zone_60m, zone_label_60m = _rsi_zone(rsi_60m_current)
            trend_60m = _trend_arrow(rsi_60m_prev, rsi_60m_current)
            st.metric(
                f"{zone_60m} 60-MINUTE RSI",
                f"{rsi_60m_current:.1f}",
                delta=f"{rsi_60m_current - rsi_60m_prev:.1f} — {trend_60m}",
                delta_color="off"
            )
            st.caption(f"Zone: {zone_label_60m} | Spot: {price_60m:.0f}")
        else:
            st.warning("60m data unavailable")

    with rsi_col2:
        if rsi_30m_current is not None:
            zone_30m, zone_label_30m = _rsi_zone(rsi_30m_current)
            trend_30m = _trend_arrow(rsi_30m_prev, rsi_30m_current)
            st.metric(
                f"{zone_30m} 30-MINUTE RSI",
                f"{rsi_30m_current:.1f}",
                delta=f"{rsi_30m_current - rsi_30m_prev:.1f} — {trend_30m}",
                delta_color="off"
            )
            st.caption(f"Zone: {zone_label_30m} | Spot: {price_30m:.0f}")
        else:
            st.warning("30m data unavailable")

    # Signal generation
    if rsi_60m_current is not None and rsi_30m_current is not None:
        signal_col1, signal_col2 = st.columns(2)

        # Bull Put signal
        with signal_col1:
            if rsi_60m_current < 25 and rsi_30m_current < 25:
                st.success("✅ **BULL PUT READY** (Extreme oversold)")
                st.caption(f"60m RSI {rsi_60m_current:.1f} < 25 & 30m RSI {rsi_30m_current:.1f} < 25 — Strong entry signal")
                if st.button("Enter Bull Put Spread", key="bull_put_entry"):
                    st.info("Note: Manually enter position in broker. Strike recommendation: Sell 1-1.5% below spot.")
            elif rsi_60m_current < 30 and rsi_30m_current < 30:
                st.warning("⚠️ **BULL PUT MODERATE** (Oversold, not extreme)")
                st.caption(f"60m RSI {rsi_60m_current:.1f} & 30m RSI {rsi_30m_current:.1f} — Moderate signal, wait for confirmation")
            elif rsi_60m_current < 22 and rsi_30m_current > rsi_30m_prev:
                st.info("🔴 **ROLL DOWN** (Extreme oversold, bounce starting)")
                st.caption(f"60m RSI {rsi_60m_current:.1f} < 22 & 30m RSI rising — Safe to roll your short put down")
                if st.button("Confirm Roll Down", key="roll_down_confirm"):
                    st.success("Prepare to roll: Buy back put, sell lower strike for credit.")
            else:
                st.info("⭕ No Bull Put signal right now")

        # Bear Call signal
        with signal_col2:
            if rsi_60m_current > 75 and rsi_30m_current > 75:
                st.success("✅ **BEAR CALL READY** (Extreme overbought)")
                st.caption(f"60m RSI {rsi_60m_current:.1f} > 75 & 30m RSI {rsi_30m_current:.1f} > 75 — Strong entry signal")
                if st.button("Enter Bear Call Spread", key="bear_call_entry"):
                    st.info("Note: Manually enter position in broker. Strike recommendation: Sell 1-1.5% above spot.")
            elif rsi_60m_current > 70 and rsi_30m_current > 70:
                st.warning("⚠️ **BEAR CALL MODERATE** (Overbought, not extreme)")
                st.caption(f"60m RSI {rsi_60m_current:.1f} & 30m RSI {rsi_30m_current:.1f} — Moderate signal, wait for confirmation")
            elif rsi_60m_current > 78 and rsi_30m_current < rsi_30m_prev:
                st.info("🔴 **ROLL UP** (Extreme overbought, correction starting)")
                st.caption(f"60m RSI {rsi_60m_current:.1f} > 78 & 30m RSI falling — Safe to roll your short call up")
                if st.button("Confirm Roll Up", key="roll_up_confirm"):
                    st.success("Prepare to roll: Buy back call, sell higher strike for credit.")
            else:
                st.info("⭕ No Bear Call signal right now")

    # Historical RSI table (last 5 trading days)
    st.divider()
    st.subheader("📋 Historical RSI Status (Last 5 Trading Days)")
    st.caption("7 × 60m candles + 13 × 30m candles per day | Signals show when Bull Put/Bear Call/Roll conditions were met")

    @st.cache_data(ttl=600, show_spinner=False)
    def _fetch_hist_60m():
        try:
            return _lf.get_nifty_1h_phase(days=6)
        except Exception:
            return None

    @st.cache_data(ttl=600, show_spinner=False)
    def _fetch_hist_30m():
        try:
            return _lf.get_nifty_30m(days=6)
        except Exception:
            return None

    df_hist_60m = _fetch_hist_60m()
    df_hist_30m = _fetch_hist_30m()

    if df_hist_60m is not None and not df_hist_60m.empty:
        df_hist_60m = rfb.compute_rsi(df_hist_60m, 14)
    if df_hist_30m is not None and not df_hist_30m.empty:
        df_hist_30m = rfb.compute_rsi(df_hist_30m, 14)

    if (df_hist_60m is not None and not df_hist_60m.empty) or (df_hist_30m is not None and not df_hist_30m.empty):
        def _rsi_css(val):
            """Color RSI cells based on trading zones: Red=SHORT (OB), Blue=LONG (OS), Green=Neutral"""
            try:
                rsi = float(val)
                if rsi >= 75:
                    return "background-color:#be123c;color:#ffffff;font-weight:800;"  # Dark red - extreme OB (SHORT)
                elif rsi >= 70:
                    return "background-color:#ef4444;color:#ffffff;font-weight:700;"  # Red - overbought
                elif rsi <= 22:
                    return "background-color:#0d47a1;color:#ffffff;font-weight:800;"  # Dark blue - extreme OS (LONG)
                elif rsi <= 30:
                    return "background-color:#1e40af;color:#ffffff;font-weight:700;"  # Blue - oversold
                else:
                    return "background-color:#10b981;color:#ffffff;font-weight:600;"  # Green - neutral
            except:
                return ""

        def _div_css(val):
            """Color divergence cells: Green=Bullish (LONG), Red=Bearish (SHORT)"""
            s = str(val)
            if "Bull" in s:
                return "background-color:#10b981;color:#ffffff;font-weight:800;"  # Green - bullish div
            elif "Bear" in s:
                return "background-color:#ef4444;color:#ffffff;font-weight:800;"  # Red - bearish div
            return ""

        def _signal_css(val):
            """Color signal column: Green for LONG, Red for SHORT"""
            s = str(val)
            if "LONG" in s:
                return "background-color:#d1fae5;color:#065f46;font-weight:800;"  # Light green
            elif "SHORT" in s:
                return "background-color:#fee2e2;color:#7f1d1d;font-weight:800;"  # Light red
            return ""

        def _detect_divergence(df, lookback=20, min_gap=2.0):
            """Detect bullish/bearish divergence: price extreme not confirmed by RSI"""
            if df is None or df.empty or 'rsi' not in df.columns:
                return pd.Series("", index=df.index if df is not None and not df.empty else pd.Index([]))

            d = df.copy()
            rsi = d['rsi'].fillna(0)
            low = d['low'].fillna(0)
            high = d['high'].fillna(0)

            prior_low_price = d['low'].shift(1).rolling(lookback).min()
            prior_low_rsi = rsi.shift(1).rolling(lookback).min()
            prior_high_price = d['high'].shift(1).rolling(lookback).max()
            prior_high_rsi = rsi.shift(1).rolling(lookback).max()

            bullish_div = (d['low'] <= prior_low_price) & (rsi > prior_low_rsi + min_gap)
            bearish_div = (d['high'] >= prior_high_price) & (rsi < prior_high_rsi - min_gap)

            div_signal = pd.Series("", index=d.index, dtype=str)
            div_signal[bullish_div] = "▲ Bull"
            div_signal[bearish_div] = "▼ Bear"
            return div_signal

        def _build_hist_table(df_60m, df_30m):
            """Build flat historical RSI table: 30m rows with 60m data in cols 2-4"""
            if df_60m is None or df_60m.empty:
                df_60m = pd.DataFrame()
            if df_30m is None or df_30m.empty:
                df_30m = pd.DataFrame()

            rows = []

            # Normalize index to datetime
            if not df_60m.empty and not isinstance(df_60m.index, pd.DatetimeIndex):
                df_60m.index = pd.to_datetime(df_60m.index)
            if not df_30m.empty and not isinstance(df_30m.index, pd.DatetimeIndex):
                df_30m.index = pd.to_datetime(df_30m.index)

            # Add divergence detection
            div_60m = _detect_divergence(df_60m) if not df_60m.empty else pd.Series()
            div_30m = _detect_divergence(df_30m) if not df_30m.empty else pd.Series()

            # Get last 5 trading days
            if not df_30m.empty:
                dates_30m = df_30m.index.date
                unique_dates = sorted(set(dates_30m), reverse=True)[:5]
            elif not df_60m.empty:
                dates_60m = df_60m.index.date
                unique_dates = sorted(set(dates_60m), reverse=True)[:5]
            else:
                return pd.DataFrame()

            for date in sorted(unique_dates, reverse=True):
                rows.append({
                    'Time': f"📅 {date.strftime('%A, %B %d, %Y')}",
                    '60m_RSI': '', '60m_Div': '', '60m_Trend': '',
                    '30m_RSI': '', '30m_Div': '', '30m_Trend': '', 'Signal': ''
                })

                # Iterate through all 30m candles for this date
                if not df_30m.empty:
                    day_30m = df_30m[df_30m.index.date == date]
                    day_60m = df_60m[df_60m.index.date == date] if not df_60m.empty else pd.DataFrame()
                    day_div_30m = div_30m[div_30m.index.date == date] if not div_30m.empty else pd.Series()
                    day_div_60m = div_60m[div_60m.index.date == date] if not div_60m.empty else pd.Series()

                    shown_60m_hours = set()  # Track which hours we've already shown 60m data for

                    # Iterate through 30m candles in REVERSE order (newest first)
                    day_30m_reversed = day_30m.iloc[::-1]
                    for idx_in_reversed, (idx_30m, row_30m) in enumerate(day_30m_reversed.iterrows()):
                        rsi_30m = row_30m['rsi']
                        if pd.isna(rsi_30m):
                            continue

                        zone_dot_30m, zone_label_30m = _rsi_zone(rsi_30m)
                        # Get previous candle (which is next in reversed iteration)
                        prev_rsi_30m = day_30m_reversed['rsi'].iloc[idx_in_reversed+1] if idx_in_reversed+1 < len(day_30m_reversed) else rsi_30m
                        trend_30m = _trend_arrow(prev_rsi_30m, rsi_30m)
                        div_30m_str = day_div_30m.get(idx_30m, "") if not day_div_30m.empty else ""

                        # Find corresponding 60m candle (same hour as 30m candle)
                        hour_30m = idx_30m.hour
                        minute_30m = idx_30m.minute

                        rsi_60m_val = ""
                        div_60m_str = ""
                        trend_60m_str = ""

                        # Only show 60m data on the first 30m candle of each hour
                        if hour_30m not in shown_60m_hours and not day_60m.empty:
                            # Get 60m candle that covers this 30m time
                            covering_60m = day_60m[
                                ((day_60m.index.hour == hour_30m) & (day_60m.index.minute <= minute_30m)) |
                                ((day_60m.index.hour == hour_30m + 1) & (day_60m.index.minute > minute_30m))
                            ]
                            if len(covering_60m) > 0:
                                idx_60m = covering_60m.index[-1]
                                rsi_60m = covering_60m['rsi'].iloc[-1]
                                if not pd.isna(rsi_60m):
                                    zone_dot_60m, zone_label_60m = _rsi_zone(rsi_60m)
                                    idx_60m_prev = day_60m.index.get_indexer([idx_60m], method='backfill')
                                    prev_rsi_60m = day_60m['rsi'].iloc[idx_60m_prev[0]-1] if idx_60m_prev[0] > 0 else rsi_60m
                                    trend_60m_str = _trend_arrow(prev_rsi_60m, rsi_60m)
                                    rsi_60m_val = f"{rsi_60m:.1f}"
                                    div_60m_str = day_div_60m.get(idx_60m, "") if not day_div_60m.empty else ""
                                    shown_60m_hours.add(hour_30m)

                        # Determine 30m signal with entry direction
                        signal = ""
                        time_str = idx_30m.strftime('%H:%M')
                        if rsi_30m < 25 and i > 0 and day_30m['rsi'].iloc[i-1] > 30:
                            signal = f"🟢 LONG {time_str}"
                        elif rsi_30m > 75 and i > 0 and day_30m['rsi'].iloc[i-1] < 70:
                            signal = f"🔴 SHORT {time_str}"
                        elif rsi_30m < 22 and i > 0 and day_30m['rsi'].iloc[i-1] > 25:
                            signal = f"↓ ROLL DOWN {time_str}"
                        elif rsi_30m > 78 and i > 0 and day_30m['rsi'].iloc[i-1] < 75:
                            signal = f"↑ ROLL UP {time_str}"

                        rows.append({
                            'Time': time_str,
                            '60m_RSI': rsi_60m_val,
                            '60m_Div': div_60m_str,
                            '60m_Trend': trend_60m_str,
                            '30m_RSI': f"{rsi_30m:.1f}",
                            '30m_Div': div_30m_str,
                            '30m_Trend': trend_30m,
                            'Signal': signal
                        })

            return pd.DataFrame(rows)

        hist_table = _build_hist_table(df_hist_60m, df_hist_30m)

        if not hist_table.empty:
            # Apply pandas Styler for cell coloring
            def _style_rsi_table(df):
                """Apply trading-signal colors to RSI and Divergence columns"""
                styler = df.style

                # Color RSI cells (trading zones) using row-wise apply to avoid format conflict
                def _rsi_row(row):
                    styles = [''] * len(row)
                    for i, col in enumerate(row.index):
                        if col in ['60m_RSI', '30m_RSI']:
                            styles[i] = _rsi_css(row[col])
                        else:
                            styles[i] = ''
                    return styles

                styler = styler.apply(_rsi_row, axis=1)

                # Color divergence cells (bullish/bearish signals)
                def _div_row(row):
                    styles = [''] * len(row)
                    for i, col in enumerate(row.index):
                        if col in ['60m_Div', '30m_Div']:
                            styles[i] = _div_css(row[col])
                        else:
                            styles[i] = ''
                    return styles

                styler = styler.apply(_div_row, axis=1)

                # Color signal column (LONG/SHORT)
                def _signal_row(row):
                    styles = [''] * len(row)
                    for i, col in enumerate(row.index):
                        if col == 'Signal':
                            styles[i] = _signal_css(row[col])
                        else:
                            styles[i] = ''
                    return styles

                styler = styler.apply(_signal_row, axis=1)

                return styler

            styled_table = _style_rsi_table(hist_table)
            st.dataframe(styled_table, use_container_width=True, height=600)

            # Download button
            csv_data = hist_table.to_csv(index=False)
            st.download_button(
                "⬇ Download Historical RSI as CSV",
                csv_data.encode('utf-8'),
                file_name="nifty_rsi_historical_5days.csv",
                mime="text/csv",
                key="hist_rsi_download"
            )
        else:
            st.warning("Not enough historical data to display table.")
    else:
        st.info("Historical RSI data loading… (requires 5+ days of data)")

    # Mini RSI trend charts
    st.divider()
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        if df_live_60m_rsi is not None and len(df_live_60m_rsi) > 1:
            st.subheader("60m RSI Trend (last 4 hours)")
            fig_60m = go.Figure()
            fig_60m.add_trace(go.Scatter(
                x=list(range(len(df_live_60m_rsi))),
                y=df_live_60m_rsi["rsi"],
                mode="lines+markers",
                line=dict(color="#3b82f6", width=2),
                name="RSI(14)"
            ))
            fig_60m.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="Overbought 70")
            fig_60m.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="Oversold 30")
            fig_60m.add_hline(y=75, line_dash="dot", line_color="darkred", annotation_text="Extreme 75")
            fig_60m.add_hline(y=25, line_dash="dot", line_color="darkgreen", annotation_text="Extreme 25")
            fig_60m.update_layout(height=250, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Candle #", yaxis_title="RSI")
            st.plotly_chart(fig_60m, use_container_width=True, key="chart_60m_rsi")

    with chart_col2:
        if df_live_30m_rsi is not None and len(df_live_30m_rsi) > 1:
            st.subheader("30m RSI Trend (last 2 hours)")
            fig_30m = go.Figure()
            fig_30m.add_trace(go.Scatter(
                x=list(range(len(df_live_30m_rsi))),
                y=df_live_30m_rsi["rsi"],
                mode="lines+markers",
                line=dict(color="#f59e0b", width=2),
                name="RSI(14)"
            ))
            fig_30m.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="Overbought 70")
            fig_30m.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="Oversold 30")
            fig_30m.add_hline(y=75, line_dash="dot", line_color="darkred", annotation_text="Extreme 75")
            fig_30m.add_hline(y=25, line_dash="dot", line_color="darkgreen", annotation_text="Extreme 25")
            fig_30m.update_layout(height=250, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Candle #", yaxis_title="RSI")
            st.plotly_chart(fig_30m, use_container_width=True, key="chart_30m_rsi")

# ══════════════════════════════════════════════════════════════════════════════
# Inputs
# ══════════════════════════════════════════════════════════════════════════════
c1, c2 = st.columns(2)
with c1:
    days_30m = st.slider("30m lookback (calendar days, Kite caps 30-minute history ~200d)",
                         30, 200, 150, step=10, key="p28_days30")
with c2:
    days_60m = st.slider("60m lookback (calendar days, Kite caps 60-minute history ~400d)",
                         60, 380, 300, step=20, key="p28_days60")

c3, c4, c5 = st.columns(3)
with c3:
    rsi_period = st.number_input("RSI period", 5, 30, 14, 1, key="p28_rsi_period")
with c4:
    entry_mode_label = st.radio("Entry mode", ["Zone-exit (conservative)", "Touch (immediate)"],
                                key="p28_entry_mode")
    entry_mode = "zone_exit" if entry_mode_label.startswith("Zone-exit") else "touch"
with c5:
    midline_exit = st.checkbox("Exit on RSI midline (50) cross-back", value=True, key="p28_midline")

st.markdown("**Detailed backtest — main config**")
d1, d2, d3, d4 = st.columns(4)
with d1:
    ob = st.number_input("Overbought threshold", 55.0, 90.0, 70.0, 1.0, key="p28_ob")
with d2:
    os_ = st.number_input("Oversold threshold", 10.0, 45.0, 30.0, 1.0, key="p28_os")
with d3:
    stop_pct = st.number_input("Stop %", 0.2, 10.0, 1.5, 0.1, key="p28_stop")
with d4:
    target_pct = st.number_input("Target %", 0.2, 10.0, 2.5, 0.1, key="p28_target")

e1, e2 = st.columns(2)
with e1:
    max_bars_30m = st.number_input("30m time-stop (candles held, 12/day)", 4, 240, 60, 4,
                                   key="p28_maxbars30")
with e2:
    max_bars_60m = st.number_input("60m time-stop (candles held, 6/day)", 2, 120, 30, 2,
                                   key="p28_maxbars60")

compare_configs = st.checkbox("📊 Run side-by-side with alternative config (0.75% stop, 1.5% target)",
                              value=False, key="p28_compare_alt")
if compare_configs:
    st.markdown("**Alternative config (for comparison)**")
    alt_c1, alt_c2 = st.columns(2)
    with alt_c1:
        alt_stop_pct = st.number_input("Alt: Stop %", 0.2, 10.0, 0.75, 0.1, key="p28_alt_stop")
    with alt_c2:
        alt_target_pct = st.number_input("Alt: Target %", 0.2, 10.0, 1.5, 0.1, key="p28_alt_target")
else:
    alt_stop_pct = None
    alt_target_pct = None

st.caption(f"30m time-stop ≈ {max_bars_30m/12:.1f} trading days · "
          f"60m time-stop ≈ {max_bars_60m/6:.1f} trading days — keep these in the 3-6 day "
          "range the setup is built around, not much longer.")

st.markdown("**Trend filter — require RSI divergence**")
st.caption(
    "The failure mode seen in a live run (March 2026): every LONG fade kept getting stopped "
    "because price kept making fresh lows WITH RSI also making fresh lows in lockstep — a "
    "genuine sustained decline, not a stalling move. Turning this on only fades once price "
    "makes a new N-candle extreme that RSI does NOT confirm (classic bullish/bearish "
    "divergence) — much closer to 'the move is stalling' than 'RSI crossed 70/30,' trend or "
    "no trend.")
f1, f2, f3 = st.columns(3)
with f1:
    require_divergence = st.checkbox("Require divergence to enter", value=False, key="p28_div")
with f2:
    div_lookback = st.number_input("Divergence lookback (candles)", 5, 60, 20, 1,
                                   key="p28_div_lookback", disabled=not require_divergence)
with f3:
    div_min_gap = st.number_input("Min RSI gap (points)", 0.0, 15.0, 2.0, 0.5,
                                  key="p28_div_gap", disabled=not require_divergence)
st.caption("⚠️ Tested live: this blocked the March pile-on entirely, but it also blocked most "
          "of the best month (Feb 2026) — fast V-shaped reversals don't leave RSI time to "
          "diverge either. Try loosening the gap/lookback, or use the cooldown filter below "
          "instead — it's a less blunt fix for the same problem.")

st.markdown("**Trend filter — option 3: cooldown between same-direction re-entries**")
st.caption(
    "A less blunt alternative to divergence: instead of judging each signal on momentum "
    "confirmation, this just takes the FIRST fade of a stretch and refuses to re-enter the "
    "SAME direction again until cooldown_bars has passed — no repeat re-triggers piling on "
    "while a trend grinds on. The cooldown clears immediately the moment a trade fires in the "
    "OPPOSITE direction (a real reversal already showed up, so the restriction no longer "
    "applies). Unlike divergence, this doesn't touch the FIRST trade of any stretch — including "
    "fast V-reversals — so it should cost less of the good trades.")
g1, g2, g3 = st.columns(3)
with g1:
    require_cooldown = st.checkbox("Require cooldown between same-direction re-entries",
                                   value=False, key="p28_cooldown")
with g2:
    cooldown_bars_30m = st.number_input("30m cooldown (candles, 12/day)", 4, 240, 48, 4,
                                        key="p28_cooldown30", disabled=not require_cooldown)
with g3:
    cooldown_bars_60m = st.number_input("60m cooldown (candles, 6/day)", 2, 120, 24, 2,
                                        key="p28_cooldown60", disabled=not require_cooldown)

run = st.button("▶ Run backtest", type="primary", key="p28_run")
if run:
    st.session_state.p28_ran = True
    st.session_state.p28_inputs = dict(
        days_30m=days_30m, days_60m=days_60m, rsi_period=int(rsi_period),
        entry_mode=entry_mode, midline_exit=midline_exit, ob=float(ob), os_=float(os_),
        stop_pct=float(stop_pct), target_pct=float(target_pct),
        max_bars_30m=int(max_bars_30m), max_bars_60m=int(max_bars_60m),
        require_divergence=require_divergence, div_lookback=int(div_lookback),
        div_min_gap=float(div_min_gap),
        require_cooldown=require_cooldown, cooldown_bars_30m=int(cooldown_bars_30m),
        cooldown_bars_60m=int(cooldown_bars_60m),
        compare_configs=compare_configs,
        alt_stop_pct=float(alt_stop_pct) if alt_stop_pct is not None else None,
        alt_target_pct=float(alt_target_pct) if alt_target_pct is not None else None,
    )

if not st.session_state.get("p28_ran"):
    st.info("Set your parameters and click Run. Pulls 30m + 60m Nifty history from Kite and "
           "walks every RSI OB/OS extreme forward (a few seconds).")
    st.stop()

_in = st.session_state.p28_inputs

@st.cache_data(ttl=1800, show_spinner=False)
def _load_30m(days):
    return _lf.get_nifty_30m(days=days)


@st.cache_data(ttl=1800, show_spinner=False)
def _load_60m(days):
    return _lf.get_nifty_1h_phase(days=days)


with st.spinner("Fetching 30m + 60m history…"):
    df_30m = _load_30m(_in["days_30m"])
    df_60m = _load_60m(_in["days_60m"])

if (df_30m is None or df_30m.empty) and (df_60m is None or df_60m.empty):
    st.error("Could not load either 30m or 60m Nifty history. Log in via Home → Kite, then retry.")
    st.stop()

if df_30m is None or df_30m.empty:
    st.warning(
        "30m history came back empty — 60m loaded fine below, but the 30m half of every "
        "section on this page will be blank. `get_nifty_30m()` swallows its own errors and "
        "returns empty on failure (never crashes), and this page caches THAT result for 30 "
        "minutes — so a transient failure (or an older cached empty result from before a fix "
        "was deployed) can look like a permanent one. Click below to force a fresh fetch.")
    if st.button("🔄 Clear cached 30m/60m fetch & retry", key="p28_clear_cache"):
        _load_30m.clear()
        _load_60m.clear()
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# Detailed backtest — main + optional alternative config
# ══════════════════════════════════════════════════════════════════════════════

with st.expander("📊 Detailed Backtest Results (collapse when not needed)", expanded=False):
    st.divider()
    st.subheader(f"Detailed backtest — RSI({_in['rsi_period']}), OB {_in['ob']:.0f} / OS {_in['os_']:.0f}, "
                f"{'Zone-exit' if _in['entry_mode']=='zone_exit' else 'Touch'} entry")

    def _run_config(config_name, ob, os_, stop, target, max_bars_30m, max_bars_60m, cooldown_30m, cooldown_60m):
        """Run backtest for a single config across both timeframes; returns dict of results."""
        results = {}
        for label, df, max_bars, cooldown_bars in [
            ("30-minute", df_30m, max_bars_30m, cooldown_30m),
            ("60-minute (hourly)", df_60m, max_bars_60m, cooldown_60m),
        ]:
            if df is None or df.empty:
                results[label] = (None, None, None)
                continue
            trades = rfb.simulate_fade_trades(
                df, rsi_period=_in["rsi_period"], ob=ob, os_=os_,
                entry_mode=_in["entry_mode"], max_bars=max_bars, stop_pct=stop,
                target_pct=target, midline_exit=_in["midline_exit"],
                require_divergence=_in.get("require_divergence", False),
                div_lookback=_in.get("div_lookback", 20), div_min_gap=_in.get("div_min_gap", 2.0),
                require_cooldown=_in.get("require_cooldown", False), cooldown_bars=cooldown_bars)
            stats = rfb.trade_stats(trades)
            results[label] = (trades, stats, None if trades.empty else rfb.equity_curve(trades))
        return results

    # Run main config
    main_results = _run_config(
        "Main", _in["ob"], _in["os_"], _in["stop_pct"], _in["target_pct"],
        _in["max_bars_30m"], _in["max_bars_60m"],
        _in.get("cooldown_bars_30m", 48), _in.get("cooldown_bars_60m", 24))

    # Run alt config if enabled
    alt_results = None
    if _in.get("compare_configs"):
        alt_results = _run_config(
            "Alternative", _in["ob"], _in["os_"], _in["alt_stop_pct"], _in["alt_target_pct"],
            _in["max_bars_30m"], _in["max_bars_60m"],
            _in.get("cooldown_bars_30m", 48), _in.get("cooldown_bars_60m", 24))

    # Display results
    configs_to_show = [
        ("Main", _in["stop_pct"], _in["target_pct"], main_results),
    ]
    if alt_results:
        configs_to_show.append(("Alternative (0.75% / 1.5%)", _in["alt_stop_pct"], _in["alt_target_pct"], alt_results))

    for config_label, stop, target, results in configs_to_show:
        st.markdown(f"### {config_label} — {stop:.2f}% stop / {target:.2f}% target")
        detail_cols = st.columns(2)

        for col, label in zip(detail_cols, ["30-minute", "60-minute (hourly)"]):
            with col:
                st.markdown(f"**{label}**")
                trades, stats, eq = results[label]

                if trades is None or trades.empty:
                    st.caption("No data or no trades triggered.")
                    continue

                # Show summary metrics
                m1, m2, m3 = st.columns(3)
                m1.metric("Trades", stats["n_trades"])
                m2.metric("Win rate", f"{stats['win_rate']:.1f}%" if pd.notna(stats["win_rate"]) else "—")
                m3.metric("Expectancy", f"{stats['expectancy_pts']:.1f} pts" if pd.notna(stats["expectancy_pts"]) else "—")
                m4, m5, m6 = st.columns(3)
                pf = stats["profit_factor"]
                m4.metric("Profit factor", f"{pf:.2f}" if pd.notna(pf) and pf not in (float("inf"),) else ("∞" if pf == float("inf") else "—"))
                m5.metric("Total P&L", f"{stats['total_pnl_pts']:.1f} pts")
                m6.metric("Max drawdown", f"{stats['max_drawdown_pts']:.1f} pts")

                # Equity curve
                if eq is not None and not eq.empty:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=list(range(len(eq))), y=eq["cum_pnl_pts"],
                                             mode="lines", line=dict(color="#2563eb", width=2),
                                             name="Cumulative P&L (pts)"))
                    fig.update_layout(height=200, margin=dict(l=10, r=10, t=10, b=10),
                                      yaxis_title="pts", xaxis_title="trade #")
                    st.plotly_chart(fig, use_container_width=True, key=f"p28_eq_{config_label}_{label}")

                # Trade log in collapsible expander
                with st.expander(f"📋 Trade log ({len(trades)} trades)", expanded=False):
                    st.dataframe(trades, use_container_width=True, hide_index=True, height=320)
                    st.download_button(f"⬇ Download {label} trade log CSV",
                                       trades.to_csv(index=False).encode("utf-8"),
                                       file_name=f"rsi_fade_trades_{label.split()[0]}.csv", mime="text/csv",
                                       key=f"p28_dl_{config_label}_{label}")

    # ══════════════════════════════════════════════════════════════════════════════
    # Threshold scan + timeframe comparison — the "which one's best" answer
    # ══════════════════════════════════════════════════════════════════════════════
    st.divider()
    st.subheader("Threshold scan — 30m vs hourly, across OB/OS pairs")
    st.caption("Runs OB/OS pairs 65/35, 70/30, 75/25, 80/20 on both timeframes with the same entry "
              "mode / exit rule / stop / target above, sorted by expectancy (pts per trade).")

    dfs = {"30-minute": df_30m, "60-minute (hourly)": df_60m}
    max_bars_map = {"30-minute": _in["max_bars_30m"], "60-minute (hourly)": _in["max_bars_60m"]}
    cooldown_bars_map = {"30-minute": _in.get("cooldown_bars_30m", 48),
                         "60-minute (hourly)": _in.get("cooldown_bars_60m", 24)}

    scan = rfb.compare_timeframes(dfs, rsi_period=_in["rsi_period"], entry_mode=_in["entry_mode"],
                                  max_bars_map=max_bars_map, stop_pct=_in["stop_pct"],
                                  target_pct=_in["target_pct"], midline_exit=_in["midline_exit"],
                                  require_divergence=_in.get("require_divergence", False),
                                  div_lookback=_in.get("div_lookback", 20),
                                  div_min_gap=_in.get("div_min_gap", 2.0),
                                  require_cooldown=_in.get("require_cooldown", False),
                                  cooldown_bars_map=cooldown_bars_map)

    if scan.empty:
        st.caption("Not enough data loaded to run the scan.")
    else:
        # Show top result by default
        top = scan[scan["n_trades"] >= 10]
        if not top.empty:
            best = top.iloc[0]
            st.success(f"**Top pick** (n_trades ≥ 10): {best['timeframe']}, OB {best['ob']:.0f} / OS {best['os']:.0f} — "
                      f"{best['expectancy_pts']:.1f} pts/trade, {best['win_rate']:.1f}% win rate, "
                      f"{int(best['n_trades'])} trades, max DD {best['max_drawdown_pts']:.1f} pts")
        else:
            st.warning("No timeframe/threshold combo cleared 10 trades in this lookback — extend the "
                      "lookback sliders above before trusting results.")

        # Full scan results in expander
        with st.expander("📊 View full threshold scan table", expanded=False):
            st.dataframe(scan, use_container_width=True, hide_index=True)
            st.download_button("⬇ Download full scan CSV", scan.to_csv(index=False).encode("utf-8"),
                               file_name="rsi_fade_threshold_scan.csv", mime="text/csv", key="p28_dl_scan")
