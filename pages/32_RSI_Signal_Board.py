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

from data.live_fetcher import get_nifty_1h_phase, get_nifty_spot
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

with st.expander("2. Pure Divergence — findings", expanded=True):
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
