# pages/24_Reversal_Backtest.py
# Standalone — kept separate from pages 22/23 with its own run button(s).
#
# Question: after a FALL (>=1% in a day, even purely intraday, OR >=1.5% over
# two closes), how big does the bounce off the low need to be before Nifty
# reliably keeps going up — vs. rolling back over into a fresh lower low?
#
# Two modes, each with its own button:
#   • Daily   — long history (years), catches an intraday-only fall via that
#               day's own LOW (even if the close recovers).
#   • Intraday — short history (Kite-limited), reference = running high SINCE
#               THAT SESSION'S OPEN, so it catches a same-day drop-and-bounce
#               a daily bar can mask entirely.

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
st.caption("After a fall of >=1% in a day (even intraday) or >=1.5% over two closes, what's "
           "the smallest bounce off the low that reliably means Nifty keeps going up, rather "
           "than rolling over into a fresh lower low?")

with st.expander("⚠️ What this is (and its limits) — read once"):
    st.markdown(
        "- **Fall trigger:** a day/candle is flagged if EITHER (a) prior close → this bar's "
        "LOW drops >= your 1-day %  — using the LOW, not the close, so a purely intraday dip "
        "that recovers by the close still counts — OR (b) close two bars ago → this bar's "
        "close drops >= your 2-day %.\n"
        "- **Episode:** consecutive/near-consecutive flagged bars are merged into one episode, "
        "anchored on the LOWEST low in the run.\n"
        "- **Reversal tracking:** walking forward bar-by-bar from the anchor low, a NEW lower "
        "low resets the anchor (the fall isn't over). Once the running high since the "
        "(current) anchor first climbs your threshold% above it, that's the **trigger bar**.\n"
        "- **Scored per threshold:** forward return + hit-rate (share that closed higher) at "
        "each horizon from the trigger bar, and **failure_rate%** — how often price closed "
        "back below the anchor low again before the longest horizon (a whipsaw reversal).\n"
        "- **Recommended threshold** = the SMALLEST reversal% whose hit-rate clears your "
        "target, with enough triggered episodes to trust it. This is a base-rate cutoff from "
        "history, not a guarantee — always keep your stop.\n"
        "- **Daily engine:** years of index daily OHLC, reference = prior close(s). "
        "**Intraday engine:** Kite-limited lookback (weeks, not years) on 15-min candles, "
        "reference = the running high since that SESSION's open — the only way to catch a "
        "same-day drop-and-recover a daily bar would hide.")


# ── cached loaders ──────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _load_daily(days):
    return _lf.get_nifty_daily(days=days)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_intraday(interval, days):
    return _lf.get_nifty_intraday(interval=interval, days=days)


def _render(df, height=360):
    st.dataframe(df, use_container_width=True, hide_index=True, height=height)


def _run_engine(df, find_fn, scan_fn, find_kwargs, scan_kwargs, thresholds, horizons):
    episodes = find_fn(df, **find_kwargs)
    if episodes.empty:
        return episodes, {"scan": pd.DataFrame(), "detail": pd.DataFrame()}
    res = scan_fn(df, episodes, thresholds=thresholds, forward_horizons=horizons, **scan_kwargs)
    return episodes, res


def _summary_block(scan, horizons, unit_label, min_hit, min_n):
    cols = st.columns(len(horizons))
    for col, h in zip(cols, horizons):
        best = rb.pick_min_reliable_threshold(scan, horizon=h, min_hit_rate=min_hit, min_n=min_n)
        with col:
            if best is None:
                st.metric(f"Min reversal @ {h}{unit_label}", "—")
                st.caption(f"No threshold cleared {min_hit:.0f}% hit-rate with >= {min_n} episodes.")
            else:
                hit_col = f"hit_rate_{h}b%" if f"hit_rate_{h}b%" in best else f"hit_rate_{h}d%"
                st.metric(f"Min reversal @ {h}{unit_label}", f"{best['threshold%']:.2f}%",
                          help=f"hit-rate {best[hit_col]:.1f}% on {int(best['n_triggered'])} "
                               f"triggered episodes")


# ══════════════════════════════════════════════════════════════════════════════
# MODE 1 — Daily engine
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("1 · Daily engine — long history")
c1, c2, c3 = st.columns(3)
with c1:
    d_lookback = st.slider("Lookback (calendar days)", 365, 1460, 730, step=30, key="p24_d_lb")
with c2:
    d_fall1 = st.number_input("Fall trigger — 1 day (%, uses that day's low)", 0.3, 5.0, 1.0, 0.1,
                              key="p24_d_fall1")
with c3:
    d_fall2 = st.number_input("Fall trigger — 2 days (%, close to close)", 0.5, 8.0, 1.5, 0.1,
                              key="p24_d_fall2")

c4, c5, c6 = st.columns(3)
with c4:
    d_thr_lo, d_thr_hi = st.slider("Reversal-threshold scan range (%)", 0.1, 5.0, (0.25, 3.0), 0.05,
                                   key="p24_d_thr")
with c5:
    d_thr_step = st.select_slider("Scan step (%)", options=[0.1, 0.25, 0.5], value=0.25, key="p24_d_step")
with c6:
    d_min_hit = st.number_input("Target hit-rate % (for the recommended threshold)", 50.0, 90.0, 60.0, 1.0,
                                key="p24_d_hit")

d_horizons = st.multiselect("Forward horizons (trading days)", [1, 2, 3, 5, 10, 15, 20],
                            default=[3, 5, 10], key="p24_d_hor")

if st.button("▶ Run daily reversal backtest", type="primary", key="p24_run_daily"):
    st.session_state.p24_daily_ran = True
    st.session_state.p24_daily_inputs = dict(
        lookback=d_lookback, fall1=d_fall1, fall2=d_fall2,
        thr_lo=d_thr_lo, thr_hi=d_thr_hi, thr_step=d_thr_step,
        min_hit=d_min_hit, horizons=tuple(sorted(d_horizons)) or (3, 5, 10))

if not st.session_state.get("p24_daily_ran"):
    st.info("Set your fall triggers and click Run. Pulls ~2y of daily candles and walks "
            "forward from every fall episode's low (a few seconds).")
else:
    _in = st.session_state.p24_daily_inputs
    thresholds = tuple(round(x, 2) for x in np.arange(_in["thr_lo"], _in["thr_hi"] + 1e-9, _in["thr_step"]))
    with st.spinner("Fetching daily history and scanning reversal thresholds…"):
        daily = _load_daily(_in["lookback"])
        if daily is None or daily.empty:
            episodes, res = pd.DataFrame(), {"scan": pd.DataFrame(), "detail": pd.DataFrame()}
        else:
            episodes, res = _run_engine(
                daily, rb.find_fall_episodes_daily, rb.reversal_threshold_scan_daily,
                dict(fall_1d_pct=_in["fall1"], fall_2d_pct=_in["fall2"]),
                {}, thresholds, _in["horizons"])

    if daily is None or daily.empty:
        st.error("Could not load daily Nifty history. Log in via Home → Kite, then retry.")
    elif episodes.empty:
        st.warning("No fall episodes found at these triggers over this lookback — loosen the "
                   "% triggers or extend the lookback.")
    else:
        st.success(f"Found **{len(episodes)}** fall episodes over **{len(daily)}** daily rows "
                  f"({daily.index.min().date()} → {daily.index.max().date()}).")

        st.markdown("**Recommended minimum reversal — smallest threshold clearing your target hit-rate**")
        _summary_block(res["scan"], _in["horizons"], "d", _in["min_hit"], min_n=10)

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
                               file_name="reversal_scan_daily.csv", mime="text/csv", key="p24_dl_d_scan")

        with st.expander("Fall episodes found"):
            _render(episodes, height=min(60 + 28 * len(episodes), 420))

        with st.expander("⬇ Per-episode trigger detail (every threshold that fired)"):
            if res["detail"].empty:
                st.caption("Nothing triggered in this scan range.")
            else:
                _render(res["detail"], height=360)
                st.download_button("Download CSV", res["detail"].to_csv(index=False).encode("utf-8"),
                                   file_name="reversal_detail_daily.csv", mime="text/csv",
                                   key="p24_dl_d_detail")

# ══════════════════════════════════════════════════════════════════════════════
# MODE 2 — Intraday engine
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("2 · Intraday engine — same-day drop & bounce")
st.caption("Reference peak is the running HIGH since that session's own open, so this catches "
          "a fall-and-reversal entirely within one day — the daily engine above only sees it "
          "if it also shows up as a bar-low vs. the prior close. Lookback is capped by Kite's "
          "intraday history limit (weeks, not years) — sample sizes will be much smaller.")

i1, i2, i3 = st.columns(3)
with i1:
    i_interval = st.selectbox("Candle", ["5minute", "15minute"], index=1, key="p24_i_int")
with i2:
    i_lookback = st.slider("Lookback (calendar days)", 10, 180, 60, step=5, key="p24_i_lb")
with i3:
    i_fall = st.number_input("Fall trigger — intraday (%, off the session's running high)",
                             0.3, 5.0, 1.0, 0.1, key="p24_i_fall")

i4, i5, i6 = st.columns(3)
with i4:
    i_thr_lo, i_thr_hi = st.slider("Reversal-threshold scan range (%)", 0.1, 5.0, (0.25, 2.5), 0.05,
                                   key="p24_i_thr")
with i5:
    i_thr_step = st.select_slider("Scan step (%)", options=[0.1, 0.25, 0.5], value=0.25, key="p24_i_step")
with i6:
    i_min_hit = st.number_input("Target hit-rate % (for the recommended threshold)", 50.0, 90.0, 60.0, 1.0,
                                key="p24_i_hit")

_bars_help = {"5minute": (12, "≈1h"), "15minute": (4, "≈1h")}
bars_per_hr, _ = _bars_help[i_interval]
i_horizons_hr = st.multiselect("Forward horizons (hours ahead, in candles)", [1, 2, 4, 6.5],
                               default=[1, 2, 6.5], key="p24_i_hor")

if st.button("▶ Run intraday reversal backtest", type="primary", key="p24_run_intra"):
    st.session_state.p24_intra_ran = True
    horizons_bars = tuple(sorted(set(max(1, round(h * bars_per_hr)) for h in (i_horizons_hr or [1, 2, 6.5]))))
    st.session_state.p24_intra_inputs = dict(
        interval=i_interval, lookback=i_lookback, fall=i_fall,
        thr_lo=i_thr_lo, thr_hi=i_thr_hi, thr_step=i_thr_step,
        min_hit=i_min_hit, horizons=horizons_bars)

if not st.session_state.get("p24_intra_ran"):
    st.info("Pick a candle size and click Run. Pulls Kite's available intraday index history "
            "(no real volume on the index, price-only) and walks forward from every intraday "
            "fall's low.")
else:
    _in = st.session_state.p24_intra_inputs
    thresholds = tuple(round(x, 2) for x in np.arange(_in["thr_lo"], _in["thr_hi"] + 1e-9, _in["thr_step"]))
    with st.spinner("Fetching intraday history and scanning reversal thresholds…"):
        intraday = _load_intraday(_in["interval"], _in["lookback"])
        if intraday is None or intraday.empty:
            episodes, res = pd.DataFrame(), {"scan": pd.DataFrame(), "detail": pd.DataFrame()}
        else:
            episodes, res = _run_engine(
                intraday, rb.find_fall_episodes_intraday, rb.reversal_threshold_scan_intraday,
                dict(fall_pct=_in["fall"]), {}, thresholds, _in["horizons"])

    if intraday is None or intraday.empty:
        st.error("Could not load intraday Nifty history. Log in via Home → Kite, then retry.")
    elif episodes.empty:
        st.warning("No intraday fall episodes found at this trigger over this lookback — "
                   "loosen the % trigger or extend the lookback.")
    else:
        st.success(f"Found **{len(episodes)}** intraday fall episodes over **{len(intraday)}** "
                  f"{i_interval} candles ({intraday.index.min()} → {intraday.index.max()}).")

        st.markdown("**Recommended minimum reversal — smallest threshold clearing your target hit-rate**")
        _summary_block(res["scan"], _in["horizons"], " bars", _in["min_hit"], min_n=10)

        st.divider()
        st.markdown("**Full threshold scan**")
        if res["scan"].empty:
            st.caption("No threshold in the scan range ever triggered — widen the range.")
        else:
            _render(res["scan"])
            st.download_button("⬇ Download threshold scan CSV",
                               res["scan"].to_csv(index=False).encode("utf-8"),
                               file_name="reversal_scan_intraday.csv", mime="text/csv",
                               key="p24_dl_i_scan")

        with st.expander("Intraday fall episodes found"):
            _render(episodes, height=min(60 + 28 * len(episodes), 420))

        with st.expander("⬇ Per-episode trigger detail (every threshold that fired)"):
            if res["detail"].empty:
                st.caption("Nothing triggered in this scan range.")
            else:
                _render(res["detail"], height=360)
                st.download_button("Download CSV", res["detail"].to_csv(index=False).encode("utf-8"),
                                   file_name="reversal_detail_intraday.csv", mime="text/csv",
                                   key="p24_dl_i_detail")
