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
        "- **Reversal tracking:** walking forward day-by-day from the anchor low, a NEW lower "
        "low resets the anchor (the fall isn't over). Once the running high since the "
        "(current) anchor first climbs your threshold% above it, that's the **trigger day**.\n"
        "- **Scored per threshold:** forward return + hit-rate (share that closed higher) at "
        "each horizon from the trigger day, and **failure_rate%** — how often price closed "
        "back below the anchor low again before the longest horizon (a whipsaw reversal).\n"
        "- **Recommended threshold** = the SMALLEST reversal% whose hit-rate clears your "
        "target, with enough triggered episodes to trust it. This is a base-rate cutoff from "
        "history, not a guarantee — always keep your stop.\n"
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

if st.button("▶ Run reversal backtest", type="primary", key="p24_run"):
    st.session_state.p24_ran = True
    st.session_state.p24_inputs = dict(
        lookback=lookback, fall1=fall1, fall2=fall2,
        thr_lo=thr_lo, thr_hi=thr_hi, thr_step=thr_step,
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
        episodes = rb.find_fall_episodes_daily(daily, fall_1d_pct=_in["fall1"], fall_2d_pct=_in["fall2"])
        res = rb.reversal_threshold_scan_daily(daily, episodes, thresholds=thresholds,
                                               forward_horizons=_in["horizons"]) \
            if not episodes.empty else {"scan": pd.DataFrame(), "detail": pd.DataFrame()}

if daily is None or daily.empty:
    st.error("Could not load daily Nifty history. Log in via Home → Kite, then retry.")
    st.stop()
if episodes.empty:
    st.warning("No fall episodes found at these triggers over this lookback — loosen the "
              "% triggers or extend the lookback.")
    st.stop()

st.success(f"Found **{len(episodes)}** fall episodes over **{len(daily)}** daily rows "
          f"({daily.index.min().date()} → {daily.index.max().date()}).")

st.markdown("**Recommended minimum reversal — smallest threshold clearing your target hit-rate**")
_summary_block(res["scan"], _in["horizons"], _in["min_hit"], min_n=10)

st.divider()
st.markdown("**Full threshold scan**")
st.caption("hit_rate = share of triggered episodes closing higher N days later · "
          "avg_fwd_ret = mean forward return · failure_rate = % that closed back "
          "below the anchor low again before the longest horizon.")
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
