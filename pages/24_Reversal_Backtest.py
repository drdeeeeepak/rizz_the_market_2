# pages/24_Reversal_Backtest.py
# Standalone — kept separate from pages 22/23 with its own run button.
#
# Two modes (radio button, mirrors page 22's style):
#   Fall — put-seller safety: after a FALL (>=0.1% in a day, using that
#     day's LOW so a purely intraday dip vs. yesterday's close still
#     counts, OR >=0.75% over two closes), how big does the bounce off the
#     low need to be before Nifty reliably keeps going up — vs. rolling
#     back over into a fresh lower low?
#   Rise — call-seller safety: the mirror question for a rise/pullback,
#     with the important caveat that markets in an uptrend persistently
#     make new highs as normal behavior — so don't expect this to flatten
#     to 0% the way the Fall side does. It measures the actual curve.

from pathlib import Path

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

with st.expander("📜 Final Rule Book — put & call selling (read this first)"):
    _rulebook_path = Path(__file__).resolve().parent.parent / "docs" / "PAGE_24_RULE_BOOK.md"
    try:
        st.markdown(_rulebook_path.read_text())
    except Exception:
        st.caption("Rule book file not found — see docs/PAGE_24_RULE_BOOK.md in the repo.")

mode = st.radio("Mode", ["Fall — put-seller safety", "Rise — call-seller safety",
                         "Pinpoint — dual-confirmation long/short",
                         "Same-day scan — no merge, no anchor"], horizontal=True,
                key="p24_mode")
is_fall = mode.startswith("Fall")
is_pinpoint = mode.startswith("Pinpoint")
is_sameday = mode.startswith("Same-day")

if is_sameday:
    st.caption("The naive version of the low/high-side signal: does TODAY's close sit X% above "
              "TODAY's own low (or X% below TODAY's own high), with NO episode-merging and NO "
              "running anchor across multiple days? For each X% threshold, checks whether TODAY's "
              "own low/high gets touched again within the next 3/5/10 trading days. This directly "
              "answers 'if my 3:25pm price is X% above today's low, is today's low safe' — the "
              "question of whether a bigger same-day threshold alone (no multi-day tracking) is "
              "enough, contrasted with the Pinpoint mode above which tracks a running anchor.")

    with st.expander("⚠️ What this is (and its limits) — read once"):
        st.markdown(
            "- **No episode-merging, no anchor-walk.** Every day is scored purely against its own "
            "low/high — unlike Fall/Rise/Pinpoint above, a multi-day decline's anchor never "
            "shifts to an earlier, more extreme day.\n"
            "- **Watch the `n` column.** Sample size collapses fast as the threshold rises (few "
            "days ever see a huge same-day round-trip) — a threshold with n<10 is not a reliable "
            "read, even if its touch-rate looks great.\n"
            "- **This is the version already known to test weak at the smallest threshold "
            "(0.25%)** — this scan exists to check honestly whether a BIGGER threshold actually "
            "fixes that, or whether the structural gap (no running anchor) persists regardless of "
            "the number chosen.")

    lookback = st.slider("Lookback (calendar days)", 365, 1460, 730, step=30, key="p24sd_lb")
    c1, c2, c3 = st.columns(3)
    with c1:
        thr_min = st.number_input("Threshold min %", 0.05, 3.0, 0.1, 0.05, key="p24sd_thr_min")
    with c2:
        thr_max = st.number_input("Threshold max %", 0.1, 5.0, 3.0, 0.05, key="p24sd_thr_max")
    with c3:
        thr_step = st.number_input("Threshold step %", 0.05, 1.0, 0.1, 0.05, key="p24sd_thr_step")
    horizons_str = st.text_input("Forward horizons (trading days, comma-separated)", "3,5,10",
                                 key="p24sd_horizons")
    try:
        horizons = tuple(int(x.strip()) for x in horizons_str.split(","))
    except ValueError:
        horizons = (3, 5, 10)
        st.caption("Couldn't parse horizons — using default 3,5,10.")

    @st.cache_data(ttl=3600, show_spinner=False)
    def _p24sd_load_daily(days):
        return _lf.get_nifty_daily(days=days)

    if st.button("▶ Run same-day scan", type="primary", key="p24sd_run"):
        thresholds = tuple(round(x, 2) for x in np.arange(thr_min, thr_max + thr_step / 2, thr_step))
        st.session_state.p24sd_ran = True
        st.session_state.p24sd_inputs = dict(lookback=lookback, horizons=horizons,
                                             thresholds=thresholds)

    if not st.session_state.get("p24sd_ran"):
        st.info("Pick your settings and click Run. Only needs daily candles.")
        st.stop()

    _in = st.session_state.p24sd_inputs
    with st.spinner("Fetching daily history and scanning thresholds…"):
        daily = _p24sd_load_daily(_in["lookback"])

    if daily is None or daily.empty:
        st.error("Could not load daily Nifty history. Log in via Home → Kite, then retry.")
        st.stop()

    bounce_scan = rb.same_day_bounce_scan(daily, bounce_pcts=_in["thresholds"],
                                         forward_horizons=_in["horizons"])
    pullback_scan = rb.same_day_pullback_scan(daily, pullback_pcts=_in["thresholds"],
                                              forward_horizons=_in["horizons"])

    st.subheader("Low side — today's close X% above today's own low")
    st.dataframe(bounce_scan, use_container_width=True, hide_index=True)

    st.subheader("High side — today's close X% below today's own high")
    st.dataframe(pullback_scan, use_container_width=True, hide_index=True)

    with st.expander("⬇ Download both scans"):
        st.download_button("Download low-side CSV", bounce_scan.to_csv(index=False).encode("utf-8"),
                           file_name="same_day_bounce_scan.csv", mime="text/csv", key="p24sd_dl_low")
        st.download_button("Download high-side CSV", pullback_scan.to_csv(index=False).encode("utf-8"),
                           file_name="same_day_pullback_scan.csv", mime="text/csv", key="p24sd_dl_high")

    st.stop()

if is_pinpoint:
    st.caption("On days where BOTH the fall+bounce (PUT) AND rise+pullback (CALL) confirmations "
               "fire — which, at the validated 0% trigger, turns out to be the MAJORITY of days, "
               "not a rare edge case — which side actually breaches more? PUT-safety and "
               "CALL-safety were validated as two SEPARATE claims, so a day confirming both isn't "
               "automatically a directional conflict — it might just mean both sides are safe "
               "(an Iron Condor day). This measures which is actually true instead of assuming.")

    with st.expander("⚠️ What this is (and its limits) — read once"):
        st.markdown(
            "- Uses the SAME validated definitions as the Fall/Rise modes above — fall/rise "
            "trigger and bounce/pullback confirmation, same formulas, defaulting to the confirmed "
            "0% trigger / 0.25% confirmation from the rule book.\n"
            "- Classifies EVERY day into one of 4 buckets: **PUT_ONLY** (only the low bounced "
            "enough — lean long/sell put), **CALL_ONLY** (only the high pulled back enough — lean "
            "short/sell call), **BOTH** (both confirmed the same day — the case this section "
            "exists to resolve), **NEITHER** (no signal, stay out).\n"
            "- Touch rates are INTRADAY (uses the low/high columns, not just the close) — the same "
            "stricter, conservative 'deciding metric' already established over hit_rate in the "
            "Fall/Rise modes.\n"
            "- This is NOT episode-merged like the Fall/Rise modes above — every day is scored on "
            "its own. At the validated 0% trigger that's the correct granularity anyway (the "
            "trigger stopped filtering anything once it hit 0%).")

    lookback = st.slider("Lookback (calendar days)", 365, 1460, 730, step=30, key="p24p_lb")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        bounce_pct = st.number_input("Bounce confirmation % (off the low)", 0.0, 3.0, 0.25, 0.05,
                                     key="p24p_bounce")
    with c2:
        pullback_pct = st.number_input("Pullback confirmation % (off the high)", 0.0, 3.0, 0.25, 0.05,
                                       key="p24p_pullback")
    with c3:
        fall_trigger = st.number_input("Fall trigger % (0 = validated floor)", 0.0, 3.0, 0.0, 0.05,
                                       key="p24p_fall_trig")
    with c4:
        rise_trigger = st.number_input("Rise trigger % (0 = validated floor)", 0.0, 3.0, 0.0, 0.05,
                                       key="p24p_rise_trig")
    horizons_str = st.text_input("Forward horizons (trading days, comma-separated)", "3,5,10",
                                 key="p24p_horizons")
    try:
        horizons = tuple(int(x.strip()) for x in horizons_str.split(","))
    except ValueError:
        horizons = (3, 5, 10)
        st.caption("Couldn't parse horizons — using default 3,5,10.")

    @st.cache_data(ttl=3600, show_spinner=False)
    def _p24p_load_daily(days):
        return _lf.get_nifty_daily(days=days)

    if st.button("▶ Run dual-confirmation scan", type="primary", key="p24p_run"):
        st.session_state.p24p_ran = True
        st.session_state.p24p_inputs = dict(lookback=lookback, bounce_pct=bounce_pct,
                                            pullback_pct=pullback_pct, fall_trigger=fall_trigger,
                                            rise_trigger=rise_trigger, horizons=horizons)

    if not st.session_state.get("p24p_ran"):
        st.info("Pick your settings and click Run. Only needs daily candles.")
        st.stop()

    _in = st.session_state.p24p_inputs
    with st.spinner("Fetching daily history and classifying every day…"):
        daily = _p24p_load_daily(_in["lookback"])

    if daily is None or daily.empty:
        st.error("Could not load daily Nifty history. Log in via Home → Kite, then retry.")
        st.stop()

    scan = rb.dual_confirmation_scan(daily, bounce_pct=_in["bounce_pct"],
                                     pullback_pct=_in["pullback_pct"],
                                     fall_trigger_pct=_in["fall_trigger"],
                                     rise_trigger_pct=_in["rise_trigger"],
                                     forward_horizons=_in["horizons"])

    if scan.empty:
        st.error("Not enough daily history for this lookback.")
        st.stop()

    st.success(f"Classified **{int(scan['n'].sum())}** days into 4 buckets.")
    st.subheader("Bucket counts and forward touch rates")
    st.caption("**BOTH** is the row that answers the actual question: compare its "
              "touch_low_rate vs touch_high_rate at each horizon. Close together and both low → "
              "both sides genuinely safe, sell an Iron Condor on these days. One clearly higher → "
              "that's the side more likely to breach, lean the OTHER way instead.")
    st.dataframe(scan, use_container_width=True, hide_index=True)

    both_row = scan[scan["bucket"] == "BOTH"]
    if not both_row.empty:
        h0 = _in["horizons"][0]
        tl = both_row.iloc[0].get(f"touch_low_rate_{h0}d%")
        th = both_row.iloc[0].get(f"touch_high_rate_{h0}d%")
        if pd.notna(tl) and pd.notna(th):
            gap = abs(tl - th)
            if gap <= 5:
                st.info(f"At {h0}d: touch_low_rate {tl}% vs touch_high_rate {th}% on BOTH-confirmed "
                       f"days — close together, no real asymmetry. These look like genuine "
                       f"both-sides-safe days, not a directional pick.")
            elif tl > th:
                st.warning(f"At {h0}d: touch_low_rate {tl}% > touch_high_rate {th}% on BOTH-confirmed "
                          f"days — the PUT side breaches more often here. Lean toward the CALL side "
                          f"(sell call / short-biased) on these days, not both equally.")
            else:
                st.warning(f"At {h0}d: touch_high_rate {th}% > touch_low_rate {tl}% on BOTH-confirmed "
                          f"days — the CALL side breaches more often here. Lean toward the PUT side "
                          f"(sell put / long-biased) on these days, not both equally.")

    with st.expander("⬇ Download the full scan"):
        st.download_button("Download CSV", scan.to_csv(index=False).encode("utf-8"),
                           file_name="dual_confirmation_scan.csv", mime="text/csv",
                           key="p24p_dl_scan")

    st.stop()

if is_fall:
    st.caption("After a fall of >=0.1% in a day (even intraday, vs. yesterday's close) or "
               ">=0.75% over two closes, what's the smallest bounce off the low that reliably "
               "means Nifty keeps going up, rather than rolling over into a fresh lower low?")
else:
    st.caption("After a rise of >=0.1% in a day (even intraday, vs. yesterday's close) or "
               ">=0.75% over two closes, how much of a pullback off the high actually means "
               "anything for a call seller — mirrors the fall/put analysis, flipped.")

with st.expander("⚠️ What this is (and its limits) — read once"):
    if is_fall:
        st.markdown(
            "- **Fall trigger:** a day is flagged if EITHER (a) prior close → today's LOW drops "
            ">= your 1-day % — using the LOW, not the close, so a purely intraday dip that "
            "recovers by the close still counts — OR (b) close two days ago → today's close "
            "drops >= your 2-day %.\n"
            "- **Episode:** consecutive/near-consecutive flagged days are merged into one episode, "
            "anchored on the LOWEST low in the run.\n"
            "- **Green-candle confirmation (optional, off by default):** drops any episode unless "
            "the low day itself closes green (close > open) OR the very next trading day does — "
            "a visible sign buyers stepped in at/right after the low. Off by default because the "
            "EOD-bounce trigger itself already turned out to be confirmation enough on its own.\n"
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
            "- **Fall-size scan (section 3)** is a different question: instead of varying the "
            "bounce, it varies the FALL SIZE itself and checks the low with NO bounce wait at all "
            "— 'how big a fall, on its own, needs to be before its low holds.'\n"
            "- **Fall × bounce lookup (section 4)** combines both dimensions: for every fall size "
            "in range, the smallest bounce that kept the low untouched — since the fall size is "
            "given by the market and the bounce is the thing you actually wait for.\n"
            "- All of these are base-rate cutoffs from history, not guarantees — always keep your "
            "stop, and treat 0% observed touch-rate as 'not seen yet in this sample', not 'can't "
            "happen' (small samples can easily hide a rare tail event).\n"
            "- Runs on years of index daily OHLC, reference = prior close(s).")
    else:
        st.markdown(
            "- **This is the mirror of the Fall mode** — same mechanics, flipped: anchor on the "
            "HIGHEST high instead of the lowest low, track a PULLBACK down instead of a bounce "
            "up, and **touch_high_rate** (not touch_low_rate) is the bad outcome — for a CALL "
            "seller, not a put seller.\n"
            "- **Expect very different numbers than the Fall side, on purpose.** A confirmed low "
            "tends to hold because a fall is usually event-driven and resolves. A high in an "
            "uptrend doesn't behave the same way — markets with positive drift are SUPPOSED to "
            "keep making new highs, so don't expect touch_high_rate to flatten near 0% the way "
            "touch_low_rate did. This suite measures that curve honestly; it doesn't force a "
            "match to the put side.\n"
            "- **Rise trigger:** prior close → today's HIGH climbs >= your 1-day %, OR close two "
            "days ago → today's close climbs >= your 2-day %.\n"
            "- **Pullback tracking:** walking forward from the anchor high, a NEW higher high "
            "resets the anchor upward (the rise isn't over). The trigger fires the first day the "
            "running LOW since the anchor drops your pullback% below it.\n"
            "- **hit_rate here means closed LOWER** (continuation of the pullback, i.e. a real "
            "top) — the opposite sign convention from the Fall side's 'closed higher'.\n"
            "- Section 3 (rise-size, zero pullback) is where the asymmetry shows up most clearly "
            "— touch_high_rate climbing with rise size, not flattening near zero.\n"
            "- Same caveats as the Fall side: base-rate cutoffs from history, not guarantees.")


# ── cached loaders ──────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _load_daily(days):
    return _lf.get_nifty_daily(days=days)


def _render(df, height=360):
    st.dataframe(df, use_container_width=True, hide_index=True, height=height)


def _summary_block(scan, horizons, min_hit, min_n, picker, col_key, label):
    cols = st.columns(len(horizons))
    for col, h in zip(cols, horizons):
        best = picker(scan, horizon=h, min_hit_rate=min_hit, min_n=min_n)
        with col:
            if best is None:
                st.metric(f"{label} @ {h}d", "—")
                st.caption(f"No threshold cleared {min_hit:.0f}% hit-rate with >= {min_n} episodes.")
            else:
                st.metric(f"{label} @ {h}d", f"{best[col_key]:.2f}%",
                          help=f"hit-rate {best[f'hit_rate_{h}d%']:.1f}% on "
                               f"{int(best['n_triggered'])} triggered episodes")


def _safety_block(scan, horizons, max_touch, min_n, picker, rate_prefix, col_key, label):
    cols = st.columns(len(horizons))
    for col, h in zip(cols, horizons):
        best = picker(scan, horizon=h, max_touch_rate=max_touch, min_n=min_n)
        with col:
            if best is None:
                st.metric(f"{label} @ {h}d", "—")
                st.caption(f"No threshold kept the touch-rate at/below {max_touch:.0f}% "
                          f"with >= {min_n} episodes.")
            else:
                st.metric(f"{label} @ {h}d", f"{best[col_key]:.2f}%",
                          help=f"{rate_prefix} {best[f'{rate_prefix}_{h}d%']:.1f}% on "
                               f"{int(best['n_triggered'])} triggered episodes")


def _size_block(scan, horizons, max_touch, min_n, picker, size_key, rate_prefix, label):
    cols = st.columns(len(horizons))
    for col, h in zip(cols, horizons):
        best = picker(scan, horizon=h, max_touch_rate=max_touch, min_n=min_n)
        with col:
            if best is None:
                st.metric(f"{label} @ {h}d", "—")
                st.caption(f"No cutoff kept the touch-rate at/below {max_touch:.0f}% "
                          f"with >= {min_n} episodes.")
            else:
                st.metric(f"{label} @ {h}d", f"{best[size_key]:.2f}%",
                          help=f"{rate_prefix} {best[f'{rate_prefix}_{h}d%']:.1f}% on "
                               f"{int(best['n_episodes'])} episodes at this size")


if is_fall:
    c1, c2, c3 = st.columns(3)
    with c1:
        lookback = st.slider("Lookback (calendar days)", 365, 1460, 730, step=30, key="p24_lb")
    with c2:
        fall1 = st.number_input("Fall trigger — 1 day (%, uses that day's low)", 0.0, 5.0, 0.1, 0.05,
                                key="p24_fall1")
    with c3:
        fall2 = st.number_input("Fall trigger — 2 days (%, close to close)", 0.3, 8.0, 0.75, 0.1,
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
        "trading day does", value=False, key="p24_green",
        help="Drops any fall episode where neither the low day nor the day right after it "
             "closed above its own open. Off by default — the EOD-bounce trigger already turned "
             "out to be confirmation enough on its own.")

    st.markdown("**Fall-size scan (section 3 below)** — separate from the bounce-threshold scan "
               "above: varies the SIZE OF THE FALL itself and checks the low with NO bounce wait "
               "required at all.")
    fc1, fc2 = st.columns(2)
    with fc1:
        fall_lo, fall_hi = st.slider("Fall-size scan range (%)", 0.0, 6.0, (0.25, 3.0), 0.05,
                                     key="p24_fall_range")
    with fc2:
        fall_step = st.select_slider("Fall-size scan step (%)", options=[0.1, 0.25, 0.5], value=0.25,
                                     key="p24_fall_step")

    if st.button("▶ Run reversal backtest", type="primary", key="p24_run"):
        st.session_state.p24_ran = True
        st.session_state.p24_inputs = dict(
            lookback=lookback, fall1=fall1, fall2=fall2, require_green=require_green,
            thr_lo=thr_lo, thr_hi=thr_hi, thr_step=thr_step, max_touch=max_touch,
            fall_lo=fall_lo, fall_hi=fall_hi, fall_step=fall_step,
            min_hit=min_hit, horizons=tuple(sorted(horizons)) or (3, 5, 10))

    if not st.session_state.get("p24_ran"):
        st.info("Set your fall triggers and click Run. Pulls ~2y of daily candles and walks "
                "forward from every fall episode's low (a few seconds).")
        st.stop()

    _in = st.session_state.p24_inputs
    thresholds = tuple(round(x, 2) for x in np.arange(_in["thr_lo"], _in["thr_hi"] + 1e-9, _in["thr_step"]))
    fall_pcts = tuple(round(x, 2) for x in np.arange(_in["fall_lo"], _in["fall_hi"] + 1e-9, _in["fall_step"]))
    with st.spinner("Fetching daily history and scanning reversal thresholds…"):
        daily = _load_daily(_in["lookback"])
        if daily is None or daily.empty:
            episodes, res, fall_scan, grid = pd.DataFrame(), {"scan": pd.DataFrame(), "detail": pd.DataFrame()}, \
                pd.DataFrame(), pd.DataFrame()
        else:
            episodes = rb.find_fall_episodes_daily(daily, fall_1d_pct=_in["fall1"], fall_2d_pct=_in["fall2"],
                                                   require_green_confirmation=_in["require_green"])
            res = rb.reversal_threshold_scan_daily(daily, episodes, thresholds=thresholds,
                                                   forward_horizons=_in["horizons"]) \
                if not episodes.empty else {"scan": pd.DataFrame(), "detail": pd.DataFrame()}
            fall_scan = rb.fall_size_safety_scan(daily, fall_pcts=fall_pcts, forward_horizons=_in["horizons"],
                                                 require_green_confirmation=_in["require_green"])
            grid = rb.fall_bounce_grid_scan(daily, fall_pcts=fall_pcts, bounce_pcts=thresholds,
                                            forward_horizons=_in["horizons"],
                                            require_green_confirmation=_in["require_green"])

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
    _summary_block(res["scan"], _in["horizons"], _in["min_hit"], 10,
                   rb.pick_min_reliable_threshold, "threshold%", "Min reversal")

    st.divider()
    st.markdown("**2 · Put-seller safety — smallest bounce after which the low was never intraday-touched again**")
    st.caption("'Will a put strike parked below the low stay safe' — checks the day's LOW, not the "
              "close, so it also catches a wick through the low that recovers by end of day. This "
              "is the number that answers 'after a fall, how much bounce before I can relax "
              "about my sold put for the next N days.'")
    _safety_block(res["scan"], _in["horizons"], _in["max_touch"], 10,
                 rb.pick_min_safe_threshold, "touch_low_rate", "threshold%", "Min safe bounce")

    st.divider()
    st.markdown("**3 · Minimum fall size for a 'certain' low — no bounce required at all**")
    st.caption("A different question from section 2: instead of varying the BOUNCE size, this "
              "varies the FALL size itself, and checks the low with NO bounce/confirmation wait — "
              "straight from the low day forward. Answers: 'how big does the fall itself need to "
              "be before its own low reliably holds, before any bounce even happens?' Always uses "
              "the pure 1-day fall trigger only (2-day path muted) so the fall-size axis isn't "
              "confounded with a different trigger shape.")
    if fall_scan.empty:
        st.caption("No fall-size cutoff in the scan range found any episodes — widen the range.")
    else:
        _size_block(fall_scan, _in["horizons"], _in["max_touch"], 10,
                   rb.pick_min_certain_fall, "fall_pct", "touch_low_rate", "Min certain fall")
        with st.expander("Full fall-size scan"):
            _render(fall_scan)
            st.download_button("⬇ Download fall-size scan CSV",
                               fall_scan.to_csv(index=False).encode("utf-8"),
                               file_name="fall_size_safety_scan.csv", mime="text/csv",
                               key="p24_dl_fallscan")

    st.divider()
    st.markdown("**4 · Fall × bounce lookup — the minimum bounce needed, for the fall size you're "
               "actually seeing**")
    st.caption("Sections 2 and 3 each hold one side fixed (a fixed fall for section 2, zero bounce "
              "for section 3). This combines both: for EVERY fall size in your scan range, the "
              "smallest bounce that kept the low untouched — a live lookup, not a single number. "
              "Fall size isn't something you choose (the market gives it to you); the bounce you "
              "wait for is. Pick today's fall size below, read off the bounce needed.")
    if grid.empty:
        st.caption("No (fall%, bounce%) combination in range found any episodes — widen either range.")
    else:
        lookup_h = st.selectbox("Horizon for this lookup (trading days)", _in["horizons"],
                               index=len(_in["horizons"]) - 1, key="p24_lookup_h")
        lookup = rb.min_bounce_by_fall_size(grid, horizon=lookup_h, max_touch_rate=_in["max_touch"], min_n=10)
        if lookup.empty:
            st.caption("Not enough episodes per fall-size bucket to build this table — widen the "
                      "fall-size range or lower the min-sample bar.")
        else:
            _render(lookup, height=min(60 + 28 * len(lookup), 420))
            st.caption("`min_bounce_pct` = NaN means no bounce in your scanned range kept that fall "
                      "size's low untouched at this horizon with enough sample — widen the "
                      "reversal-threshold scan range above.")
        with st.expander("Full fall × bounce grid (every combination, every horizon)"):
            _render(grid, height=360)
            st.download_button("⬇ Download fall × bounce grid CSV",
                               grid.to_csv(index=False).encode("utf-8"),
                               file_name="fall_bounce_grid.csv", mime="text/csv",
                               key="p24_dl_grid")

    st.divider()
    st.markdown("**5 · Full bounce-threshold scan (detail behind sections 1 & 2)**")
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

else:
    c1, c2, c3 = st.columns(3)
    with c1:
        lookback = st.slider("Lookback (calendar days)", 365, 1460, 730, step=30, key="p24r_lb")
    with c2:
        rise1 = st.number_input("Rise trigger — 1 day (%, uses that day's high)", 0.0, 5.0, 0.1, 0.05,
                                key="p24r_rise1")
    with c3:
        rise2 = st.number_input("Rise trigger — 2 days (%, close to close)", 0.3, 8.0, 0.75, 0.1,
                                key="p24r_rise2")

    c4, c5, c6 = st.columns(3)
    with c4:
        thr_lo, thr_hi = st.slider("Pullback-threshold scan range (%)", 0.1, 5.0, (0.25, 3.0), 0.05,
                                   key="p24r_thr")
    with c5:
        thr_step = st.select_slider("Scan step (%)", options=[0.1, 0.25, 0.5], value=0.25, key="p24r_step")
    with c6:
        min_hit = st.number_input("Target hit-rate % (for the recommended threshold)", 50.0, 90.0, 60.0, 1.0,
                                  key="p24r_hit")

    horizons = st.multiselect("Forward horizons (trading days)", [1, 2, 3, 5, 10, 15, 20],
                              default=[3, 5, 10], key="p24r_hor")

    max_touch = st.number_input(
        "Max acceptable intraday touch-rate % — for the call-seller safety threshold below "
        "(0 = never touched the high again in this sample — expect this bar to be much harder "
        "to clear than on the Fall side)", 0.0, 90.0, 0.0, 1.0, key="p24r_touch")

    require_red = st.checkbox(
        "Require a red-candle confirmation — high day itself closes red, or the next "
        "trading day does", value=False, key="p24r_red",
        help="Drops any rise episode where neither the high day nor the day right after it "
             "closed below its own open. Off by default, matching the Fall side's simplified rule.")

    st.markdown("**Rise-size scan (section 3 below)** — separate from the pullback-threshold scan "
               "above: varies the SIZE OF THE RISE itself and checks the high with NO pullback "
               "wait required at all. This is where the shakeout asymmetry shows up most clearly.")
    fc1, fc2 = st.columns(2)
    with fc1:
        rise_lo, rise_hi = st.slider("Rise-size scan range (%)", 0.0, 6.0, (0.25, 3.0), 0.05,
                                     key="p24r_rise_range")
    with fc2:
        rise_step = st.select_slider("Rise-size scan step (%)", options=[0.1, 0.25, 0.5], value=0.25,
                                     key="p24r_rise_step")

    if st.button("▶ Run reversal backtest", type="primary", key="p24r_run"):
        st.session_state.p24r_ran = True
        st.session_state.p24r_inputs = dict(
            lookback=lookback, rise1=rise1, rise2=rise2, require_red=require_red,
            thr_lo=thr_lo, thr_hi=thr_hi, thr_step=thr_step, max_touch=max_touch,
            rise_lo=rise_lo, rise_hi=rise_hi, rise_step=rise_step,
            min_hit=min_hit, horizons=tuple(sorted(horizons)) or (3, 5, 10))

    if not st.session_state.get("p24r_ran"):
        st.info("Set your rise triggers and click Run. Pulls ~2y of daily candles and walks "
                "forward from every rise episode's high (a few seconds).")
        st.stop()

    _in = st.session_state.p24r_inputs
    thresholds = tuple(round(x, 2) for x in np.arange(_in["thr_lo"], _in["thr_hi"] + 1e-9, _in["thr_step"]))
    rise_pcts = tuple(round(x, 2) for x in np.arange(_in["rise_lo"], _in["rise_hi"] + 1e-9, _in["rise_step"]))
    with st.spinner("Fetching daily history and scanning pullback thresholds…"):
        daily = _load_daily(_in["lookback"])
        if daily is None or daily.empty:
            episodes, res, rise_scan, grid = pd.DataFrame(), {"scan": pd.DataFrame(), "detail": pd.DataFrame()}, \
                pd.DataFrame(), pd.DataFrame()
        else:
            episodes = rb.find_rise_episodes_daily(daily, rise_1d_pct=_in["rise1"], rise_2d_pct=_in["rise2"],
                                                    require_red_confirmation=_in["require_red"])
            res = rb.pullback_threshold_scan_daily(daily, episodes, thresholds=thresholds,
                                                   forward_horizons=_in["horizons"]) \
                if not episodes.empty else {"scan": pd.DataFrame(), "detail": pd.DataFrame()}
            rise_scan = rb.rise_size_certainty_scan(daily, rise_pcts=rise_pcts, forward_horizons=_in["horizons"],
                                                    require_red_confirmation=_in["require_red"])
            grid = rb.rise_pullback_grid_scan(daily, rise_pcts=rise_pcts, pullback_pcts=thresholds,
                                              forward_horizons=_in["horizons"],
                                              require_red_confirmation=_in["require_red"])

    if daily is None or daily.empty:
        st.error("Could not load daily Nifty history. Log in via Home → Kite, then retry.")
        st.stop()
    if episodes.empty:
        st.warning("No rise episodes found at these triggers over this lookback — loosen the "
                  "% triggers, extend the lookback, or turn off the red-candle confirmation.")
        st.stop()

    st.success(f"Found **{len(episodes)}** rise episodes over **{len(daily)}** daily rows "
              f"({daily.index.min().date()} → {daily.index.max().date()}).")

    st.markdown("**1 · Recommended minimum pullback — smallest threshold clearing your target hit-rate**")
    st.caption("'Will Nifty keep falling' — the continuation-down read that confirms a real top, "
              "not a shakeout that resumes.")
    _summary_block(res["scan"], _in["horizons"], _in["min_hit"], 10,
                   rb.pick_min_reliable_pullback, "threshold%", "Min pullback")

    st.divider()
    st.markdown("**2 · Call-seller safety — smallest pullback after which the high was never "
               "intraday-touched again**")
    st.caption("'Will a call strike parked above the high stay safe' — checks the day's HIGH, not "
              "the close, so it also catches a wick through the high that recovers by end of day. "
              "**Expect this to need a bigger pullback than the put side needed bounce, and to "
              "clear a much lower max-touch bar** — uptrends persistently make new highs, so a "
              "0% touch-rate target may not be reachable here at all; that's the finding, not a "
              "bug.")
    _safety_block(res["scan"], _in["horizons"], _in["max_touch"], 10,
                 rb.pick_min_safe_pullback, "touch_high_rate", "threshold%", "Min safe pullback")

    st.divider()
    st.markdown("**3 · Minimum rise size for a 'certain' high — no pullback required at all**")
    st.caption("A different question from section 2: instead of varying the PULLBACK size, this "
              "varies the RISE size itself, and checks the high with NO pullback wait — straight "
              "from the high day forward. This is where the shakeout asymmetry is clearest: "
              "expect touch_high_rate to CLIMB as rise size grows, not flatten near zero the way "
              "the fall side's touch_low_rate did — bigger rallies invite bigger, later new highs, "
              "they don't confirm the top is in.")
    if rise_scan.empty:
        st.caption("No rise-size cutoff in the scan range found any episodes — widen the range.")
    else:
        _size_block(rise_scan, _in["horizons"], _in["max_touch"], 10,
                   rb.pick_min_certain_rise, "rise_pct", "touch_high_rate", "Min certain rise")
        with st.expander("Full rise-size scan"):
            _render(rise_scan)
            st.download_button("⬇ Download rise-size scan CSV",
                               rise_scan.to_csv(index=False).encode("utf-8"),
                               file_name="rise_size_certainty_scan.csv", mime="text/csv",
                               key="p24r_dl_risescan")

    st.divider()
    st.markdown("**4 · Rise × pullback lookup — the minimum pullback needed, for the rise size "
               "you're actually seeing**")
    st.caption("Sections 2 and 3 each hold one side fixed (a fixed rise for section 2, zero "
              "pullback for section 3). This combines both: for EVERY rise size in your scan "
              "range, the smallest pullback that kept the high untouched — a live lookup, not a "
              "single number. Expect more NaN cells here than on the Fall side's equivalent table "
              "— that's the asymmetry showing up directly, not a computation issue.")
    if grid.empty:
        st.caption("No (rise%, pullback%) combination in range found any episodes — widen either range.")
    else:
        lookup_h = st.selectbox("Horizon for this lookup (trading days)", _in["horizons"],
                               index=len(_in["horizons"]) - 1, key="p24r_lookup_h")
        lookup = rb.min_pullback_by_rise_size(grid, horizon=lookup_h, max_touch_rate=_in["max_touch"], min_n=10)
        if lookup.empty:
            st.caption("Not enough episodes per rise-size bucket to build this table — widen the "
                      "rise-size range or lower the min-sample bar.")
        else:
            _render(lookup, height=min(60 + 28 * len(lookup), 420))
            st.caption("`min_pullback_pct` = NaN means no pullback in your scanned range kept that "
                      "rise size's high untouched at this horizon with enough sample — widen the "
                      "pullback-threshold scan range above, or raise your max-touch tolerance.")
        with st.expander("Full rise × pullback grid (every combination, every horizon)"):
            _render(grid, height=360)
            st.download_button("⬇ Download rise × pullback grid CSV",
                               grid.to_csv(index=False).encode("utf-8"),
                               file_name="rise_pullback_grid.csv", mime="text/csv",
                               key="p24r_dl_grid")

    st.divider()
    st.markdown("**5 · Full pullback-threshold scan (detail behind sections 1 & 2)**")
    st.caption("hit_rate_Xd = share of triggered episodes closing LOWER X days later (continuation "
              "of the pullback) · avg_fwd_ret_Xd = mean forward return · close_fail_rate_Xd = % "
              "where the CLOSE rose back above the anchor high within X days of the trigger · "
              "touch_high_rate_Xd = % where the day's HIGH (intraday) touched/exceeded the anchor "
              "high within X days — the one relevant to a sold call strike parked above the high.")
    if res["scan"].empty:
        st.caption("No threshold in the scan range ever triggered — widen the range.")
    else:
        _render(res["scan"])
        st.download_button("⬇ Download threshold scan CSV",
                           res["scan"].to_csv(index=False).encode("utf-8"),
                           file_name="pullback_scan_daily.csv", mime="text/csv", key="p24r_dl_scan")

    with st.expander("Rise episodes found"):
        _render(episodes, height=min(60 + 28 * len(episodes), 420))

    with st.expander("⬇ Per-episode trigger detail (every threshold that fired)"):
        if res["detail"].empty:
            st.caption("Nothing triggered in this scan range.")
        else:
            _render(res["detail"], height=360)
            st.download_button("Download CSV", res["detail"].to_csv(index=False).encode("utf-8"),
                               file_name="pullback_detail_daily.csv", mime="text/csv",
                               key="p24r_dl_detail")
