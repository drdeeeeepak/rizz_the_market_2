# pages/24_Reversal_Backtest.py
# Standalone — kept separate from pages 22/23 with its own run button.
#
# Question: after a FALL (>=1% in a day, using that day's LOW so a purely
# intraday dip vs. yesterday's close still counts, OR >=1.5% over two
# closes), how big does the bounce off the low need to be before Nifty
# reliably keeps going up — vs. rolling back over into a fresh lower low?

import numpy as np
import pandas as pd
import streamlit as st

import importlib
import data.live_fetcher as _lf
from analytics import reversal_backtest as rb
try:
    importlib.reload(_lf)
    importlib.reload(rb)
except Exception:
    pass

st.set_page_config(page_title="P24 · Market Reversal Backtest", layout="wide")
st.title("Page 24 — Market Reversal Backtest")
st.caption("After a fall of >=1% in a day (even intraday, vs. yesterday's close) or >=1.5% "
           "over two closes, what's the smallest bounce off the low that reliably means Nifty "
           "keeps going up, rather than rolling over into a fresh lower low?")

with st.expander("⚠️ What this is (and its limits) — read once"):
    st.markdown(
        "- **Fall trigger:** a day is flagged if EITHER (a) prior close → today's LOW drops "
        ">= your 1-day % — using the LOW, not the close, so a purely intraday dip that "
        "recovers by the close still counts — OR (b) close two days ago → today's close "
        "drops >= your 2-day %.\n"
        "- **Episode:** consecutive/near-consecutive flagged days are merged into one episode, "
        "anchored on the LOWEST low in the run.\n"
        "- **Green-candle confirmation (optional, on by default):** drops any episode unless "
        "the low day itself closes green (close > open) OR the very next trading day does — "
        "a visible sign buyers stepped in at/right after the low, not just a quiet low that "
        "could still break.\n"
        "- **Reversal tracking:** walking forward day-by-day from the anchor low, a NEW lower "
        "low resets the anchor (the fall isn't over). Once the running high since the "
        "(current) anchor first climbs your threshold% above it, that's the **trigger day**.\n"
        "- **Scored per threshold, PER horizon (1d/2d/3d/5d...):** forward return + hit-rate "
        "(share that closed higher), and two different 'broke again' checks from the trigger "
        "day — **close_fail_rate%** (closing price fell back below the anchor low) and "
        "**touch_low_rate%** (the day's intraday LOW touched/breached the anchor low, even if "
        "it closed back above it). touch_low is the one that matters for an option SELLER: a "
        "strike parked below the low can get threatened intraday on a day that still closes "
        "back above it.\n"
        "- **Recommended (continuation) threshold** = the SMALLEST reversal% whose hit-rate "
        "clears your target — 'will it keep going up'.\n"
        "- **Recommended (safety) threshold** = the SMALLEST reversal% whose touch_low_rate at "
        "your horizon is at/below your tolerance — 'will a strike below the low stay "
        "untouched' — see section 2 below.\n"
        "- Both are base-rate cutoffs from history, not guarantees — always keep your stop, "
        "and treat 0% observed touch-rate as 'not seen yet in this sample', not 'can't happen' "
        "(small samples can easily hide a rare tail event).\n"
        "- Runs on years of index daily OHLC, reference = prior close(s).")


# ── cached loaders ──────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _load_daily(days):
    return _lf.get_nifty_daily(days=days)


def _render(df, height=360):
    st.dataframe(df, use_container_width=True, hide_index=True, height=height)


def _summary_block(scan, horizons, min_hit, min_n):
    cols = st.columns(len(horizons))
    for col, h in zip(cols, horizons):
        best = rb.pick_min_reliable_threshold(scan, horizon=h, min_hit_rate=min_hit, min_n=min_n)
        with col:
            if best is None:
                st.metric(f"Min reversal @ {h}d", "—")
                st.caption(f"No threshold cleared {min_hit:.0f}% hit-rate with >= {min_n} episodes.")
            else:
                st.metric(f"Min reversal @ {h}d", f"{best['threshold%']:.2f}%",
                          help=f"hit-rate {best[f'hit_rate_{h}d%']:.1f}% on "
                               f"{int(best['n_triggered'])} triggered episodes")


def _safety_block(scan, horizons, max_touch, min_n):
    cols = st.columns(len(horizons))
    for col, h in zip(cols, horizons):
        best = rb.pick_min_safe_threshold(scan, horizon=h, max_touch_rate=max_touch, min_n=min_n)
        with col:
            if best is None:
                st.metric(f"Min safe bounce @ {h}d", "—")
                st.caption(f"No threshold kept the touch-rate at/below {max_touch:.0f}% "
                          f"with >= {min_n} episodes.")
            else:
                st.metric(f"Min safe bounce @ {h}d", f"{best['threshold%']:.2f}%",
                          help=f"touch_low_rate {best[f'touch_low_rate_{h}d%']:.1f}% on "
                               f"{int(best['n_triggered'])} triggered episodes")


c1, c2, c3 = st.columns(3)
with c1:
    lookback = st.slider("Lookback (calendar days)", 365, 1460, 730, step=30, key="p24_lb")
with c2:
    fall1 = st.number_input("Fall trigger — 1 day (%, uses that day's low)", 0.3, 5.0, 1.0, 0.1,
                            key="p24_fall1")
with c3:
    fall2 = st.number_input("Fall trigger — 2 days (%, close to close)", 0.5, 8.0, 1.5, 0.1,
                            key="p24_fall2")

c4, c5, c6 = st.columns(3)
with c4:
    thr_lo, thr_hi = st.slider("Reversal-threshold scan range (%)", 0.1, 5.0, (0.25, 3.0), 0.05,
                               key="p24_thr")
with c5:
    thr_step = st.select_slider("Scan step (%)", options=[0.1, 0.25, 0.5], value=0.25, key="p24_step")
with c6:
    min_hit = st.number_input("Target hit-rate % (for the recommended threshold)", 50.0, 90.0, 60.0, 1.0,
                              key="p24_hit")

horizons = st.multiselect("Forward horizons (trading days)", [1, 2, 3, 5, 10, 15, 20],
                          default=[3, 5, 10], key="p24_hor")

max_touch = st.number_input(
    "Max acceptable intraday touch-rate % — for the put-seller safety threshold below "
    "(0 = never touched the low again in this sample)", 0.0, 50.0, 0.0, 1.0, key="p24_touch")

require_green = st.checkbox(
    "Require a green-candle confirmation — low day itself closes green, or the next "
    "trading day does", value=True, key="p24_green",
    help="Drops any fall episode where neither the low day nor the day right after it "
         "closed above its own open — i.e. no visible sign buyers stepped in at the low.")

if st.button("▶ Run reversal backtest", type="primary", key="p24_run"):
    st.session_state.p24_ran = True
    st.session_state.p24_inputs = dict(
        lookback=lookback, fall1=fall1, fall2=fall2, require_green=require_green,
        thr_lo=thr_lo, thr_hi=thr_hi, thr_step=thr_step, max_touch=max_touch,
        min_hit=min_hit, horizons=tuple(sorted(horizons)) or (3, 5, 10))

if not st.session_state.get("p24_ran"):
    st.info("Set your fall triggers and click Run. Pulls ~2y of daily candles and walks "
            "forward from every fall episode's low (a few seconds).")
    st.stop()

_in = st.session_state.p24_inputs
thresholds = tuple(round(x, 2) for x in np.arange(_in["thr_lo"], _in["thr_hi"] + 1e-9, _in["thr_step"]))
with st.spinner("Fetching daily history and scanning reversal thresholds…"):
    daily = _load_daily(_in["lookback"])
    if daily is None or daily.empty:
        episodes, res = pd.DataFrame(), {"scan": pd.DataFrame(), "detail": pd.DataFrame()}
    else:
        episodes = rb.find_fall_episodes_daily(daily, fall_1d_pct=_in["fall1"], fall_2d_pct=_in["fall2"],
                                               require_green_confirmation=_in["require_green"])
        res = rb.reversal_threshold_scan_daily(daily, episodes, thresholds=thresholds,
                                               forward_horizons=_in["horizons"]) \
            if not episodes.empty else {"scan": pd.DataFrame(), "detail": pd.DataFrame()}

if daily is None or daily.empty:
    st.error("Could not load daily Nifty history. Log in via Home → Kite, then retry.")
    st.stop()
if episodes.empty:
    st.warning("No fall episodes found at these triggers over this lookback — loosen the "
              "% triggers, extend the lookback, or turn off the green-candle confirmation.")
    st.stop()

st.success(f"Found **{len(episodes)}** fall episodes over **{len(daily)}** daily rows "
          f"({daily.index.min().date()} → {daily.index.max().date()}).")

st.markdown("**1 · Recommended minimum reversal — smallest threshold clearing your target hit-rate**")
st.caption("'Will Nifty keep going up' — for a long/continuation read.")
_summary_block(res["scan"], _in["horizons"], _in["min_hit"], min_n=10)

st.divider()
st.markdown("**2 · Put-seller safety — smallest bounce after which the low was never intraday-touched again**")
st.caption("'Will a put strike parked below the low stay safe' — checks the day's LOW, not the "
          "close, so it also catches a wick through the low that recovers by end of day. This "
          "is the number that answers 'after a 1%+ fall, how much bounce before I can relax "
          "about my sold put for the next N days.'")
_safety_block(res["scan"], _in["horizons"], _in["max_touch"], min_n=10)

st.divider()
st.markdown("**Full threshold scan**")
st.caption("hit_rate_Xd = share of triggered episodes closing higher X days later · "
          "avg_fwd_ret_Xd = mean forward return · close_fail_rate_Xd = % where the CLOSE fell "
          "back below the anchor low within X days of the trigger · touch_low_rate_Xd = % "
          "where the day's LOW (intraday) touched/breached the anchor low within X days — the "
          "one relevant to a sold put strike parked below the low.")
if res["scan"].empty:
    st.caption("No threshold in the scan range ever triggered — widen the range.")
else:
    _render(res["scan"])
    st.download_button("⬇ Download threshold scan CSV",
                       res["scan"].to_csv(index=False).encode("utf-8"),
                       file_name="reversal_scan_daily.csv", mime="text/csv", key="p24_dl_scan")

with st.expander("Fall episodes found"):
    _render(episodes, height=min(60 + 28 * len(episodes), 420))

with st.expander("⬇ Per-episode trigger detail (every threshold that fired)"):
    if res["detail"].empty:
        st.caption("Nothing triggered in this scan range.")
    else:
        _render(res["detail"], height=360)
        st.download_button("Download CSV", res["detail"].to_csv(index=False).encode("utf-8"),
                           file_name="reversal_detail_daily.csv", mime="text/csv",
                           key="p24_dl_detail")
