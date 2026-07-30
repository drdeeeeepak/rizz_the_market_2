# pages/32_RSI_Signal_Board.py
# One hourly-RSI signal board replacing pages 04 (Hourly RSI Breakout), 28 (RSI
# Swing Fade) and 31 (RSI Divergence Backtest) — those pages' interactive
# backtest tooling stays available in git history; this page keeps only the
# live signal (last 5, per system) and the backtested know-how already gathered
# from each, as a static writeup rather than re-runnable controls.

import importlib

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from data.live_fetcher import get_nifty_1h_phase, get_nifty_spot, get_nifty_30m, get_nifty_15m
from analytics import rsi_fade_backtest as rfb
from analytics.hourly_rsi_pivot import analyze_hourly_rsi

try:
    importlib.reload(rfb)
except Exception:
    pass

st.set_page_config(page_title="P32 · RSI Signal Board", layout="wide")

st.title("RSI Signal Board — Hourly")
st.caption(
    "Three independent hourly-RSI signal systems on one page: RSI Fade (75/25 zone "
    "cross), Pure Divergence, and HL/LH Pivot Breakout. Each shows its last 5 live "
    "signals, a chart, and the backtested findings gathered on it so far."
)

DAYS = 365
RSI_PERIOD = 14


@st.cache_data(ttl=300, show_spinner="Fetching hourly data…")
def _load_hourly():
    df = get_nifty_1h_phase(days=DAYS)
    return df if df is not None and not df.empty else None


df_hourly = _load_hourly()

if df_hourly is None:
    st.error("Could not fetch hourly Nifty history. Log in via Home page, then retry.")
    st.stop()

if not isinstance(df_hourly.index, pd.DatetimeIndex):
    df_hourly.index = pd.to_datetime(df_hourly.index)

try:
    spot = get_nifty_spot()
except Exception:
    spot = None

st.caption(
    f"{len(df_hourly)} hourly candles · {df_hourly.index[0]:%d %b %Y} → "
    f"{df_hourly.index[-1]:%d %b %Y}" + (f" · Spot {spot:.0f}" if spot else "")
)


@st.cache_data(ttl=300, show_spinner=False)
def _load_30m(days=60):
    df = get_nifty_30m(days=days)
    return df if df is not None and not df.empty else None


@st.cache_data(ttl=300, show_spinner=False)
def _load_15m(days=40):
    df = get_nifty_15m(days=days)
    return df if df is not None and not df.empty else None


df_30m_raw = _load_30m()
df_15m_raw = _load_15m()
df_30m_hist = rfb.compute_rsi(df_30m_raw, RSI_PERIOD) if df_30m_raw is not None else None
df_15m_hist = rfb.compute_rsi(df_15m_raw, RSI_PERIOD) if df_15m_raw is not None else None


def _rsi_chart(df_rsi, title, marker_times, marker_rsi, marker_labels, marker_colors, days_shown=10):
    cutoff = df_rsi.index[-1] - pd.Timedelta(days=days_shown)
    chart_df = df_rsi[df_rsi.index >= cutoff]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=chart_df.index, y=chart_df["rsi"], mode="lines",
        line=dict(color="#0ea5e9", width=2), name="RSI(14)"
    ))
    fig.add_hline(y=70, line_dash="dash", line_color="rgba(239,68,68,0.5)")
    fig.add_hline(y=30, line_dash="dash", line_color="rgba(16,185,129,0.5)")
    fig.add_hline(y=50, line_dash="dot", line_color="rgba(150,150,150,0.4)")
    if marker_times:
        fig.add_trace(go.Scatter(
            x=marker_times, y=marker_rsi, mode="markers+text", name="Signal",
            marker=dict(size=12, color=marker_colors,
                       symbol=["triangle-up" if c == "#10b981" else "triangle-down" for c in marker_colors]),
            text=marker_labels, textposition="top center"
        ))
    fig.update_layout(title=title, height=320, template="plotly_dark",
                      yaxis=dict(range=[0, 100], title="RSI"), xaxis_title="",
                      margin=dict(l=10, r=10, t=40, b=10))
    return fig


def _last5_table(rows):
    if not rows:
        st.info("No signals in the lookback window.")
        return
    df = pd.DataFrame(rows)

    def _style(row):
        color = "#10b981" if row["Side"] in ("LONG", "BUY", "Bullish") else "#ef4444"
        return [f"background-color:{color};color:white;font-weight:700;" if col == "Side" else ""
                for col in row.index]

    st.dataframe(df.style.apply(_style, axis=1), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# 1. RSI FADE — 75/25 zone cross (contrarian)
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.header("1. RSI Fade — 75/25 Zone Cross")
st.caption("Contrarian: RSI crossing INTO overbought (≥75) → SHORT. RSI crossing INTO oversold (≤25) → LONG.")

df_fade = rfb.compute_rsi(df_hourly, RSI_PERIOD)
prev_rsi = df_fade["rsi"].shift(1)
fade_short = (prev_rsi < 75) & (df_fade["rsi"] >= 75)
fade_long = (prev_rsi > 25) & (df_fade["rsi"] <= 25)
fade_sig = df_fade[fade_short.fillna(False) | fade_long.fillna(False)].copy()
fade_sig["side"] = ["SHORT" if fade_short.loc[i] else "LONG" for i in fade_sig.index]

fade_last5 = fade_sig.tail(5).iloc[::-1]
fade_rows = [
    {"Time": ts.strftime("%d %b %H:%M"), "Side": r["side"], "RSI": f"{r['rsi']:.1f}", "Price": f"{r['close']:.0f}"}
    for ts, r in fade_last5.iterrows()
]

col_a, col_b = st.columns([1, 1])
with col_a:
    st.subheader("Last 5 signals")
    _last5_table(fade_rows)
with col_b:
    fig = _rsi_chart(
        df_fade, "RSI Fade — last 10 days",
        fade_last5.index.tolist(), fade_last5["rsi"].tolist(),
        fade_last5["side"].tolist(),
        ["#ef4444" if s == "SHORT" else "#10b981" for s in fade_last5["side"]],
    )
    st.plotly_chart(fig, use_container_width=True, key="chart_fade")


# ══════════════════════════════════════════════════════════════════════════════
# 2. PURE DIVERGENCE — divergence is the only entry rule
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.header("2. Pure Divergence")
st.caption(
    "Price makes a fresh 20-bar extreme that RSI does NOT confirm. Bullish divergence "
    "→ LONG. Bearish divergence → SHORT. No RSI zone gate."
)

df_div = rfb.detect_divergence_signals(df_hourly, RSI_PERIOD, div_lookback=20, div_min_gap=2.0)
div_sig = df_div[df_div["bullish"] | df_div["bearish"]].copy()
div_sig["side"] = ["Bullish" if b else "Bearish" for b in div_sig["bullish"]]

div_last5 = div_sig.tail(5).iloc[::-1]
div_rows = [
    {"Time": ts.strftime("%d %b %H:%M"), "Side": r["side"], "RSI": f"{r['rsi']:.1f}", "Price": f"{r['close']:.0f}"}
    for ts, r in div_last5.iterrows()
]

col_a, col_b = st.columns([1, 1])
with col_a:
    st.subheader("Last 5 signals")
    _last5_table(div_rows)
with col_b:
    fig = _rsi_chart(
        df_div, "Pure Divergence — last 10 days",
        div_last5.index.tolist(), div_last5["rsi"].tolist(),
        div_last5["side"].tolist(),
        ["#10b981" if s == "Bullish" else "#ef4444" for s in div_last5["side"]],
    )
    st.plotly_chart(fig, use_container_width=True, key="chart_div")


# ══════════════════════════════════════════════════════════════════════════════
# 3. HL/LH PIVOT BREAKOUT
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.header("3. HL/LH Pivot Breakout")
st.caption("RSI breaks above the last Lower High (LH) → BUY. RSI breaks below the last Higher Low (HL) → SELL.")

df_piv, piv_signals = analyze_hourly_rsi(df_hourly, rsi_period=RSI_PERIOD, lookback=3)
piv_last5 = piv_signals[-5:][::-1] if piv_signals else []
piv_rows = [
    {
        "Time": df_piv.index[s["index"]].strftime("%d %b %H:%M"),
        "Side": s["signal"],
        "RSI": f"{s['rsi_at_signal']:.1f}",
        "Pivot": f"{s['pivot_level']:.1f}",
    }
    for s in piv_last5
]

col_a, col_b = st.columns([1, 1])
with col_a:
    st.subheader("Last 5 signals")
    _last5_table(piv_rows)
with col_b:
    marker_times = [df_piv.index[s["index"]] for s in piv_last5]
    marker_rsi = [s["rsi_at_signal"] for s in piv_last5]
    marker_side = [s["signal"] for s in piv_last5]
    fig = _rsi_chart(
        df_piv, "Pivot Breakout — last 10 days",
        marker_times, marker_rsi, marker_side,
        ["#10b981" if s == "BUY" else "#ef4444" for s in marker_side],
    )
    st.plotly_chart(fig, use_container_width=True, key="chart_pivot")


# ── RSI Trend mini-charts (last 5 trading days) ────────────────────────────────
st.divider()
mini_col1, mini_col2 = st.columns(2)

with mini_col1:
    st.subheader("60m RSI Trend (last 5 trading days)")
    chart_data_60m = df_fade.tail(40).reset_index(drop=True)
    fig_60m = go.Figure()
    fig_60m.add_trace(go.Scatter(
        x=list(range(len(chart_data_60m))), y=chart_data_60m["rsi"],
        mode="lines+markers", line=dict(color="#3b82f6", width=2), name="RSI(14)"
    ))
    last_40 = df_fade.tail(40)
    current_date = None
    for i, (idx, row) in enumerate(last_40.iterrows()):
        row_date = idx.date()
        if current_date is None:
            current_date = row_date
        elif row_date != current_date:
            fig_60m.add_vline(x=i, line_dash="solid", line_color="lightgrey", opacity=0.5,
                             annotation_text=row_date.strftime("%b %d"), annotation_position="top")
            current_date = row_date
    fig_60m.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="Overbought 70")
    fig_60m.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="Oversold 30")
    fig_60m.add_hline(y=75, line_dash="dot", line_color="darkred", annotation_text="Extreme 75")
    fig_60m.add_hline(y=25, line_dash="dot", line_color="darkgreen", annotation_text="Extreme 25")
    fig_60m.update_layout(height=250, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Candle #", yaxis_title="RSI")
    st.plotly_chart(fig_60m, use_container_width=True, key="chart_60m_trend")

with mini_col2:
    if df_30m_hist is not None and len(df_30m_hist) > 1:
        st.subheader("30m RSI Trend (last 5 trading days)")
        chart_data_30m = df_30m_hist.tail(80).reset_index(drop=True)
        fig_30m = go.Figure()
        fig_30m.add_trace(go.Scatter(
            x=list(range(len(chart_data_30m))), y=chart_data_30m["rsi"],
            mode="lines+markers", line=dict(color="#f59e0b", width=2), name="RSI(14)"
        ))
        last_80 = df_30m_hist.tail(80)
        current_date = None
        for i, (idx, row) in enumerate(last_80.iterrows()):
            row_date = idx.date()
            if current_date is None:
                current_date = row_date
            elif row_date != current_date:
                fig_30m.add_vline(x=i, line_dash="solid", line_color="lightgrey", opacity=0.5,
                                 annotation_text=row_date.strftime("%b %d"), annotation_position="top")
                current_date = row_date
        fig_30m.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="Overbought 70")
        fig_30m.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="Oversold 30")
        fig_30m.add_hline(y=75, line_dash="dot", line_color="darkred", annotation_text="Extreme 75")
        fig_30m.add_hline(y=25, line_dash="dot", line_color="darkgreen", annotation_text="Extreme 25")
        fig_30m.update_layout(height=250, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Candle #", yaxis_title="RSI")
        st.plotly_chart(fig_30m, use_container_width=True, key="chart_30m_trend")
    else:
        st.warning("30m data unavailable")

# ── Historical RSI Status table (finalized styling — see CLAUDE.md) ────────────
st.divider()
st.subheader("Historical RSI Status (Last 5 Trading Days)")
st.caption("60m/30m/15m RSI with Divergence")


def _rsi_css(val, trend=0):
    """
    RSI styling.
    Background by zone: RED ≥70 (overbought), GREEN ≤30 (oversold), GRAY neutral.
    Text by trend vs previous candle: RED if lower (trend=-1), GREEN if higher
    (trend=+1), dark slate if flat/first candle (trend=0).
    """
    try:
        rsi = float(val)
        if rsi >= 70:
            bg_color = "#fca5a5"
        elif rsi <= 30:
            bg_color = "#86efac"
        else:
            bg_color = "#e2e8f0"
        if trend < 0:
            text_color, text_weight = "#dc2626", "800"
        elif trend > 0:
            text_color, text_weight = "#15803d", "800"
        else:
            text_color, text_weight = "#334155", "600"
        return f"background-color:{bg_color};color:{text_color};font-weight:{text_weight};"
    except Exception:
        return ""


def _div_css(val):
    """Color divergence cells: Green=Bullish (LONG), Red=Bearish (SHORT)"""
    s = str(val)
    if "Bull" in s:
        return "background-color:#10b981;color:#ffffff;font-weight:800;"
    elif "Bear" in s:
        return "background-color:#ef4444;color:#ffffff;font-weight:800;"
    return ""


def _signal_css(val):
    """Color signal column: Green for LONG, Red for SHORT"""
    s = str(val)
    if "LONG" in s:
        return "background-color:#d1fae5;color:#065f46;font-weight:800;"
    elif "SHORT" in s:
        return "background-color:#fee2e2;color:#7f1d1d;font-weight:800;"
    return ""


def _detect_divergence(df, lookback=20, min_gap=2.0):
    """Detect bullish/bearish divergence: price extreme not confirmed by RSI"""
    if df is None or df.empty or 'rsi' not in df.columns:
        return pd.Series("", index=df.index if df is not None and not df.empty else pd.Index([]))
    d = df.copy()
    rsi = d['rsi'].fillna(0)
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


def _build_hist_table(df_60m, df_30m, df_15m):
    """Build historical RSI table with combined RSI+Div columns for 60m, 30m, 15m"""
    if df_60m is None or df_60m.empty:
        df_60m = pd.DataFrame()
    if df_30m is None or df_30m.empty:
        df_30m = pd.DataFrame()
    if df_15m is None or df_15m.empty:
        df_15m = pd.DataFrame()

    rows = []
    for df in [df_60m, df_30m, df_15m]:
        if not df.empty and not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

    div_60m = _detect_divergence(df_60m) if not df_60m.empty else pd.Series()
    div_30m = _detect_divergence(df_30m) if not df_30m.empty else pd.Series()
    div_15m = _detect_divergence(df_15m) if not df_15m.empty else pd.Series()

    if not df_30m.empty:
        unique_dates = sorted(set(df_30m.index.date), reverse=True)[:5]
    elif not df_60m.empty:
        unique_dates = sorted(set(df_60m.index.date), reverse=True)[:5]
    else:
        return pd.DataFrame()

    for date in sorted(unique_dates, reverse=True):
        rows.append({'Time': f"📅 {date.strftime('%A, %B %d, %Y')}",
                     '60m': '', '30m': '', '15m': '', 'Signal': ''})

        if not df_15m.empty:
            day_15m = df_15m[df_15m.index.date == date]
            day_30m = df_30m[df_30m.index.date == date] if not df_30m.empty else pd.DataFrame()
            day_60m = df_60m[df_60m.index.date == date] if not df_60m.empty else pd.DataFrame()
            day_div_15m = div_15m[div_15m.index.date == date] if not div_15m.empty else pd.Series()
            day_div_30m = div_30m[div_30m.index.date == date] if not div_30m.empty else pd.Series()
            day_div_60m = div_60m[div_60m.index.date == date] if not div_60m.empty else pd.Series()

            shown_60m_hours = set()
            shown_30m_times = set()

            day_15m_reversed = day_15m.iloc[::-1]
            for idx_in_reversed, (idx_15m, row_15m) in enumerate(day_15m_reversed.iterrows()):
                rsi_15m = row_15m['rsi']
                if pd.isna(rsi_15m):
                    continue

                time_str = idx_15m.strftime('%H:%M')
                div_15m_str = day_div_15m.get(idx_15m, "") if not day_div_15m.empty else ""
                col_15m = f"{rsi_15m:.1f}" + (f" {div_15m_str}" if div_15m_str else "")

                hour_15m = idx_15m.hour
                minute_15m = idx_15m.minute
                target_30m_minute = 15 if minute_15m < 30 else 45
                time_key_30m = f"{hour_15m}:{target_30m_minute:02d}"
                col_30m = ""
                if time_key_30m not in shown_30m_times and not day_30m.empty:
                    shown_30m_times.add(time_key_30m)
                    for idx_30m, row_30m in day_30m.iterrows():
                        if idx_30m.hour == hour_15m and idx_30m.minute == target_30m_minute:
                            try:
                                rsi_30m = row_30m['rsi'] if 'rsi' in row_30m.index else None
                            except (KeyError, AttributeError):
                                rsi_30m = None
                            if rsi_30m is not None and not pd.isna(rsi_30m):
                                div_30m_str = day_div_30m.get(idx_30m, "") if not day_div_30m.empty else ""
                                col_30m = f"{rsi_30m:.1f}" + (f" {div_30m_str}" if div_30m_str else "")
                            break

                col_60m = ""
                if hour_15m not in shown_60m_hours and not day_60m.empty:
                    shown_60m_hours.add(hour_15m)
                    for idx_60m, row_60m in day_60m.iterrows():
                        if idx_60m.hour == hour_15m:
                            rsi_60m = row_60m.get('rsi') if isinstance(row_60m, dict) else row_60m['rsi']
                            if not pd.isna(rsi_60m):
                                div_60m_str = day_div_60m.get(idx_60m, "") if not day_div_60m.empty else ""
                                col_60m = f"{rsi_60m:.1f}" + (f" {div_60m_str}" if div_60m_str else "")
                            break

                signal = ""
                if minute_15m % 30 == 0 and not day_30m.empty:
                    matching_30m = day_30m[(day_30m.index.hour == hour_15m) & (day_30m.index.minute == minute_15m)]
                    if len(matching_30m) > 0:
                        rsi_30m_sig = matching_30m['rsi'].iloc[-1]
                        if not pd.isna(rsi_30m_sig):
                            prev_30m_idx = day_30m.index.get_loc(matching_30m.index[-1])
                            prev_rsi_30m = day_30m['rsi'].iloc[prev_30m_idx - 1] if prev_30m_idx > 0 else rsi_30m_sig
                            if rsi_30m_sig < 25 and prev_rsi_30m > 30:
                                signal = f"🟢 LONG {time_str}"
                            elif rsi_30m_sig > 75 and prev_rsi_30m < 70:
                                signal = f"🔴 SHORT {time_str}"
                            elif rsi_30m_sig < 22 and prev_rsi_30m > 25:
                                signal = f"↓ ROLL DOWN {time_str}"
                            elif rsi_30m_sig > 78 and prev_rsi_30m < 75:
                                signal = f"↑ ROLL UP {time_str}"

                rows.append({'Time': time_str, '60m': col_60m, '30m': col_30m, '15m': col_15m, 'Signal': signal})

    return pd.DataFrame(rows)


hist_table = _build_hist_table(df_fade, df_30m_hist, df_15m_hist)

if not hist_table.empty:
    def _style_rsi_table(df):
        styler = df.style

        def _prev_rsi_below(row_loc, col):
            import re
            for j in range(row_loc + 1, len(df)):
                v = df.iloc[j][col]
                if v:
                    m = re.search(r'(\d+\.?\d*)', str(v))
                    if m:
                        try:
                            return float(m.group(1))
                        except ValueError:
                            continue
            return None

        def _rsi_trend(row_loc, col, curr_val):
            try:
                curr = float(curr_val)
            except (TypeError, ValueError):
                return 0
            prev = _prev_rsi_below(row_loc, col)
            if prev is None:
                return 0
            if curr < prev:
                return -1
            if curr > prev:
                return 1
            return 0

        def _combined_rsi_div_row(row):
            import re
            styles = [''] * len(row)
            row_loc = df.index.get_loc(row.name)
            for i, col in enumerate(row.index):
                if col in ('60m', '30m', '15m'):
                    cell_val = row[col]
                    if cell_val:
                        # Divergence marker takes priority over the RSI-zone background —
                        # a cell can carry both (e.g. "35.4 ▲ Bull"), and the whole point
                        # of the marker is to stand out regardless of which zone RSI is in.
                        if "Bull" in str(cell_val) or "Bear" in str(cell_val):
                            styles[i] = _div_css(cell_val)
                        else:
                            m = re.search(r'(\d+\.?\d*)', str(cell_val))
                            if m:
                                trend = _rsi_trend(row_loc, col, m.group(1))
                                styles[i] = _rsi_css(m.group(1), trend)
                    else:
                        styles[i] = ''
                else:
                    styles[i] = ''
            return styles

        def _signal_row(row):
            styles = [''] * len(row)
            for i, col in enumerate(row.index):
                styles[i] = _signal_css(row[col]) if col == 'Signal' else ''
            return styles

        styler = styler.apply(_combined_rsi_div_row, axis=1)
        styler = styler.apply(_signal_row, axis=1)
        return styler

    styled_table = _style_rsi_table(hist_table)
    st.dataframe(styled_table, use_container_width=True, height=600, hide_index=True)
    st.download_button(
        "⬇ Download Historical RSI as CSV", hist_table.to_csv(index=False).encode('utf-8'),
        file_name="nifty_rsi_historical_5days.csv", mime="text/csv", key="hist_rsi_download",
    )
else:
    st.warning("Not enough historical data to display table.")


# ══════════════════════════════════════════════════════════════════════════════
# FINDINGS — what backtesting on each system found (static reference, not re-run)
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.header("Findings — what the backtests on each system found")
st.caption(
    "These are the results already gathered from the (now retired) dedicated pages for "
    "each system. Kept as static reference rather than re-runnable controls; the "
    "interactive backtest tooling that produced them still exists in git history."
)

with st.expander("1. RSI Fade 75/25 — findings", expanded=False):
    st.markdown("""
No single fixed calibration was finalized for the plain 75/25 fade — unlike the other
two systems below, its backtest tooling stayed fully interactive (adjustable OB/OS
threshold pairs, stop/target, entry mode, divergence filter, cooldown filter, threshold
scan across 65/35 → 80/20 on both 30m and hourly) and was never run to a single
recommended settled number.

**One real finding from a live run (March 2026):** plain OB/OS fades kept getting
stopped out during a genuine multi-day one-sided decline — price and RSI were both
making fresh lows in lockstep (a real trend, not a stalling move), so the fade kept
re-triggering into the same losing side. Two mitigations were tested against that
failure mode:
- **Require divergence to enter** — blocked the March pile-on entirely, but also
  blocked most of the best month (Feb 2026); fast V-shaped reversals don't leave RSI
  time to diverge either.
- **Cooldown between same-direction re-entries** — a less blunt fix: take the first
  fade of a stretch, refuse to re-enter the same direction until a cooldown window
  passes (clears immediately on a reversal). Doesn't touch the first trade of any
  stretch, so should cost less of the good trades — this was the more promising
  direction but wasn't taken to a final number either.

If you want a fixed recommended threshold/stop for this system the way the other two
have, that requires actually running the threshold scan to a conclusion — the tool to
do it (`analytics/rsi_fade_backtest.py: simulate_fade_trades` /
`threshold_scan` / `compare_timeframes`) is unchanged and still callable.
""")

with st.expander("2. Pure Divergence — findings", expanded=False):
    st.markdown("""
Divergence alone as the entry (no RSI zone gate), holding until the opposite
divergence fires (no midline exit, no time stop) — tested with and without a fixed
points stop, re-simulated per stop value (not estimated by clipping a finished trade
log, which distorts results because it can't create the extra re-entries a real stop
produces).

**No stop (baseline):**
| Timeframe | Trades | Win rate | Expectancy | Profit factor | Total P&L | Max DD |
|---|---|---|---|---|---|---|
| 60m (hourly) | 28 | 64.3% | +40.7 pts/trade | 1.25 | +1,138 pts | −2,254 pts |
| 30m | 25 | 60.0% | −48.6 pts/trade | 0.77 | −1,214 pts | −2,456 pts |

**With the optimum stop (from a full stop-loss re-simulation, not a clipped estimate):**
| Timeframe | Optimum stop | Trades | Win rate | Expectancy | Profit factor | Total P&L | Max DD |
|---|---|---|---|---|---|---|---|
| **60m (hourly)** | **100 pts** | 65 | 33.8% | **+71.3 pts/trade** | 2.08 | +4,632 pts | −671 pts |
| 30m | 150 pts | 54 | 37.0% | +39.3 pts/trade | 1.42 | +2,121 pts | −1,567 pts |

On hourly, a 100-pt stop more than quadruples total P&L vs no stop and cuts max
drawdown by ~70% — despite a lower win rate, because losses are capped small (exactly
the stop) while winners are left to run (avg win ≈ 406 pts at that stop). The
**100–250 pt band is the stable region** on hourly (all outperform no-stop); very
tight stops (50 pts) look good on a naive read but push win rate down to ~19–20% and
sit at the edge of what was tested — treat that edge as curve-fit risk, not a real
optimum. 300 pts is a genuine dip in the data, not a typo — don't use it.

⚠️ These numbers came from one ~1-year hourly sample (~6 months for 30m, Kite's
retention limit on that timeframe) — a real edge, but not a large one statistically.
""")

with st.expander("3. HL/LH Pivot Breakout — findings", expanded=False):
    st.markdown("""
**Last calibration: 28 Jul 2026 · 90 trades · 365 days of hourly candles, Nifty-50.**

**Recommended configuration:**
- **Entry filter — OS 40 / OB 55** (15-point RSI spread, narrower than the default
  30/70): 66.7% win rate, 24 trades, 2.30:1 reward:risk, +19.29% total P&L, profit
  factor 4.60x, expectancy +0.804%/trade.
- **Confirmation — none** (immediate entry on the OS/OB filter; it already screens out
  most false breakouts). Add a 2-candle wait only if too many trades fire.
- **Stop loss — 75 points** (practical): 4.79:1 R:R, +51.09% P&L. A 25-point stop is
  more aggressive (13.32:1 R:R, +59.26% P&L) but risks getting whipsawed on hourly
  noise.

| Stop loss | R:R | Win rate | Total P&L | Expectancy |
|---|---|---|---|---|
| 25 pts | 13.32:1 | 51.1% | +59.26% | +0.658%/trade |
| 50 pts | 6.87:1 | 51.1% | +54.96% | +0.611%/trade |
| **75 pts** | **4.79:1** | **51.1%** | **+51.09%** | **+0.568%/trade** |
| 100 pts | 3.71:1 | 51.1% | +47.39% | +0.527%/trade |
| 150 pts | 2.68:1 | 51.1% | +41.09% | +0.457%/trade |

**Retest triggers** (from the original calibration notes — worth rechecking
periodically even with the live tooling retired): after every 100 new live trades;
if live win rate drops below 55% (vs 66.7% backtest); if avg win/loss ratio drops
below 1.5:1; on a VIX spike (+30% vs 14-day avg); or if it's been 90+ days since the
last calibration.
""")
