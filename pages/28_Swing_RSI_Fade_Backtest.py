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

with st.expander("⚠️ What this tests (and its limits) — read once", expanded=True):
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

st.markdown("**Detailed single-config backtest** — pick one OB/OS pair + exit rule to see the "
           "actual trade log and equity curve, per timeframe.")
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

st.caption(f"30m time-stop ≈ {max_bars_30m/12:.1f} trading days · "
          f"60m time-stop ≈ {max_bars_60m/6:.1f} trading days — keep these in the 3-6 day "
          "range the setup is built around, not much longer.")

run = st.button("▶ Run backtest", type="primary", key="p28_run")
if run:
    st.session_state.p28_ran = True
    st.session_state.p28_inputs = dict(
        days_30m=days_30m, days_60m=days_60m, rsi_period=int(rsi_period),
        entry_mode=entry_mode, midline_exit=midline_exit, ob=float(ob), os_=float(os_),
        stop_pct=float(stop_pct), target_pct=float(target_pct),
        max_bars_30m=int(max_bars_30m), max_bars_60m=int(max_bars_60m),
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

# ══════════════════════════════════════════════════════════════════════════════
# Detailed single-config backtest — per timeframe
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader(f"Detailed backtest — RSI({_in['rsi_period']}), OB {_in['ob']:.0f} / OS {_in['os_']:.0f}, "
            f"{'Zone-exit' if _in['entry_mode']=='zone_exit' else 'Touch'} entry")

tf_configs = [
    ("30-minute", df_30m, _in["max_bars_30m"]),
    ("60-minute (hourly)", df_60m, _in["max_bars_60m"]),
]

detail_cols = st.columns(2)
for col, (label, df, max_bars) in zip(detail_cols, tf_configs):
    with col:
        st.markdown(f"**{label}**")
        if df is None or df.empty:
            st.caption("No data loaded for this timeframe.")
            continue
        trades = rfb.simulate_fade_trades(
            df, rsi_period=_in["rsi_period"], ob=_in["ob"], os_=_in["os_"],
            entry_mode=_in["entry_mode"], max_bars=max_bars, stop_pct=_in["stop_pct"],
            target_pct=_in["target_pct"], midline_exit=_in["midline_exit"])
        stats = rfb.trade_stats(trades)

        m1, m2, m3 = st.columns(3)
        m1.metric("Trades", stats["n_trades"])
        m2.metric("Win rate", f"{stats['win_rate']:.1f}%" if pd.notna(stats["win_rate"]) else "—")
        m3.metric("Expectancy", f"{stats['expectancy_pts']:.1f} pts" if pd.notna(stats["expectancy_pts"]) else "—")
        m4, m5, m6 = st.columns(3)
        pf = stats["profit_factor"]
        m4.metric("Profit factor", f"{pf:.2f}" if pd.notna(pf) and pf not in (float("inf"),) else ("∞" if pf == float("inf") else "—"))
        m5.metric("Total P&L", f"{stats['total_pnl_pts']:.1f} pts")
        m6.metric("Max drawdown", f"{stats['max_drawdown_pts']:.1f} pts")

        if trades.empty:
            st.caption("No trades triggered at this threshold/lookback — widen the OB/OS gap "
                      "or extend the lookback.")
            continue

        eq = rfb.equity_curve(trades)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=list(range(len(eq))), y=eq["cum_pnl_pts"],
                                 mode="lines", line=dict(color="#2563eb", width=2),
                                 name="Cumulative P&L (pts)"))
        fig.update_layout(height=220, margin=dict(l=10, r=10, t=10, b=10),
                          yaxis_title="pts", xaxis_title="trade #")
        st.plotly_chart(fig, use_container_width=True, key=f"p28_eq_{label}")

        with st.expander(f"Trade log — {label} ({len(trades)} trades)"):
            st.dataframe(trades, use_container_width=True, hide_index=True, height=320)
            st.download_button(f"⬇ Download {label} trade log CSV",
                               trades.to_csv(index=False).encode("utf-8"),
                               file_name=f"rsi_fade_trades_{label.split()[0]}.csv", mime="text/csv",
                               key=f"p28_dl_{label}")

# ══════════════════════════════════════════════════════════════════════════════
# Threshold scan + timeframe comparison — the "which one's best" answer
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("Threshold scan — 30m vs hourly, across OB/OS pairs")
st.caption("Runs OB/OS pairs 65/35, 70/30, 75/25, 80/20 on both timeframes with the same entry "
          "mode / exit rule / stop / target above, sorted by expectancy (pts per trade). This is "
          "the table that actually answers 'which timeframe is best' — a higher expectancy with "
          "a sane `n_trades` count beats a flashier win-rate on a handful of trades.")

dfs = {"30-minute": df_30m, "60-minute (hourly)": df_60m}
max_bars_map = {"30-minute": _in["max_bars_30m"], "60-minute (hourly)": _in["max_bars_60m"]}

scan = rfb.compare_timeframes(dfs, rsi_period=_in["rsi_period"], entry_mode=_in["entry_mode"],
                              max_bars_map=max_bars_map, stop_pct=_in["stop_pct"],
                              target_pct=_in["target_pct"], midline_exit=_in["midline_exit"])

if scan.empty:
    st.caption("Not enough data loaded to run the scan.")
else:
    st.dataframe(scan, use_container_width=True, hide_index=True)
    st.download_button("⬇ Download threshold scan CSV", scan.to_csv(index=False).encode("utf-8"),
                       file_name="rsi_fade_threshold_scan.csv", mime="text/csv", key="p28_dl_scan")

    top = scan[scan["n_trades"] >= 10]
    if not top.empty:
        best = top.iloc[0]
        st.success(f"Best expectancy with n_trades ≥ 10: **{best['timeframe']}**, "
                  f"OB {best['ob']:.0f} / OS {best['os']:.0f} — {best['expectancy_pts']:.1f} pts/trade, "
                  f"{best['win_rate']:.1f}% win rate, {int(best['n_trades'])} trades, "
                  f"max drawdown {best['max_drawdown_pts']:.1f} pts.")
    else:
        st.warning("No timeframe/threshold combo cleared 10 trades in this lookback — extend the "
                  "lookback sliders above before trusting any row.")
