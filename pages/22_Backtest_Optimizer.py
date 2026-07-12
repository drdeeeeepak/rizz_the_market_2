# pages/22_Backtest_Optimizer.py
# Premium-seller optimizer, two modes:
#   • Positional (daily) — condor management + "how close can I sell" (index, ~2y).
#   • Intraday timing    — one-sided selling entry/side/exit (futures, real volume, ~months).
#
# Roll-management backtests (Roll threshold, roll-rule optimizer, strike-shift
# ladders, anchor-drift scans) live on page 25 now — moved there to keep this
# page's run-time down and give roll-management its own dedicated page.
#
# You just: log in (Home → Kite) so the token is fresh, then click "Run backtest".

import streamlit as st

import importlib
import data.live_fetcher as _lf
from analytics import intraday_conviction as ic
from analytics import backtest as bt
try:
    importlib.reload(_lf)
    importlib.reload(ic)
    importlib.reload(bt)
except Exception:
    pass

st.set_page_config(page_title="P22 · Backtest / Optimizer", layout="wide")
st.title("Page 22 — Backtest / Optimizer (premium seller)")
st.caption("Empirical cutoffs for your Nifty option-selling: how close you can sell, which "
           "conviction readings warn of a strike breach, and when to time one-sided trades.")

with st.expander("⚠️ What this is (and its limits) — read once"):
    st.markdown(
        "- **Positional (daily):** anchored engine over ~2y of **index** daily (synthetic volume → "
        "CVD is a price proxy, breadth off, realized-vol expected-move). Measures the forward "
        "**1-week / 2-week** move after every row → sell-closer sizing + strike-breach cutoffs.\n"
        "- **Intraday timing:** session engine over ~months of **futures** intraday (**real volume** → "
        "CVD works). Measures the forward move over the next **N candles** → directional edge (which "
        "side to sell) and how fast it decays (exit).\n"
        "- **Roll/position-management backtests** (Roll threshold, roll-rule optimizer, strike-shift "
        "ladders, anchor-drift scans) moved to **page 25**.\n"
        "- These are **base-rate cutoffs to stack the odds**, not guarantees. Always keep your stop.")


# ── cached loaders / runners ──────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _load_daily(days):
    return _lf.get_nifty_intraday(interval="day", days=days)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_intraday(interval, days):
    return _lf.get_nifty_fut_intraday(interval=interval, days=days)


@st.cache_data(ttl=3600, show_spinner=False)
def _run_daily(days, cp, pp, nb):
    d = _load_daily(days)
    if d is None or d.empty:
        return None
    return bt.run_backtest(d, horizons=(5, 10), call_pct=cp, put_pct=pp, nbins=nb)


@st.cache_data(ttl=3600, show_spinner=False)
def _run_intraday(interval, days, horizons, nb):
    d = _load_intraday(interval, days)
    if d is None or d.empty:
        return None
    return bt.run_intraday_backtest(d, horizons=tuple(horizons), anchored=False, nbins=nb)


def _render_cuts(cuts, order):
    for col in order:
        if col not in cuts:
            continue
        st.markdown(f"**{col}**")
        st.dataframe(cuts[col].reset_index(), use_container_width=True, hide_index=True)


mode = st.radio("Mode", ["Positional (daily) — condor / sell-closer",
                         "Intraday timing (one-sided entry / exit)"], horizontal=True)

# ══════════════════════════════════════════════════════════════════════════════
# MODE 1 — Positional (daily)
# ══════════════════════════════════════════════════════════════════════════════
if mode.startswith("Positional"):
    c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1])
    with c1:
        lookback = st.slider("Lookback (calendar days)", 365, 1460, 730, step=30)
    with c2:
        call_pct = st.number_input("Sold CALL distance %", 1.0, 8.0, 3.5, 0.25)
    with c3:
        put_pct = st.number_input("Sold PUT distance %", 1.0, 8.0, 4.0, 0.25)
    with c4:
        nbins = st.select_slider("Buckets/column", options=[3, 4, 5, 6], value=5)

    # Gate on session_state rather than the button's own return value: st.button() is
    # only True on the ONE rerun triggered by that exact click — clicking the
    # download button inside the expander below triggers its own rerun where this
    # button is False again, and a raw `if not st.button(...): st.stop()` gate would
    # wipe the whole mode's results before the script ever got there.
    if st.button("▶ Run positional backtest", type="primary"):
        st.session_state.p22_pos_ran = True
        st.session_state.p22_pos_inputs = dict(lookback=lookback, call_pct=call_pct,
                                               put_pct=put_pct, nbins=nbins)

    if not st.session_state.get("p22_pos_ran"):
        st.info("Set your strike distances and click Run. First run pulls ~2y of daily candles "
                "and computes the engine over every cycle (~10–20s).")
        st.stop()

    _in = st.session_state.p22_pos_inputs
    lookback, call_pct, put_pct, nbins = _in["lookback"], _in["call_pct"], _in["put_pct"], _in["nbins"]

    with st.spinner("Fetching daily history and running the engine over every cycle…"):
        res = _run_daily(lookback, float(call_pct), float(put_pct), int(nbins))
    if res is None:
        st.error("Could not load daily Nifty history. Log in via Home → Kite, then retry.")
        st.stop()
    st.success(f"Analysed **{res['n_rows']}** daily rows · {res['span']}")

    st.subheader("1 · How far does Nifty travel? (sell-closer sizing)")
    st.caption("Percentiles of the forward **max-up** / **max-down** move from each day. Sell beyond "
               "the percentile matching your target win-rate (p90 ≈ breached ~10% of the time).")
    st.dataframe(res["distribution"], use_container_width=True, hide_index=True)
    _d = res["distribution"]
    if not _d.empty:
        _r5 = _d[_d["horizon"] == "5d"].iloc[0]
        st.caption(f"↳ 1-week: your **+{call_pct:.2f}% call** was breached **{_r5['call_breach%']}%** "
                   f"of weeks · **−{put_pct:.2f}% put** **{_r5['put_breach%']}%**. For ~90% hold sell near "
                   f"**+{_r5['up_p90']}% / −{_r5['dn_p90']}%**; ~95% → **+{_r5['up_p95']}% / −{_r5['dn_p95']}%**.")

    st.divider()
    st.subheader("2 · Column cutoffs — which readings precede a breach (book-loss / roll / hold)")
    st.caption("Rows bucketed low→high. **call_breach%** = how often the +call strike was hit next "
               "week from that bucket (sold-CALL threatened → defend/roll up); **put_breach%** likewise.")
    _render_cuts(res["cutoffs"],
                 ["State", "Final", "Bull−Bear", "Conf%", "Downtr", "Topping", "Uptrend",
                  "Reversal", "RSI", "ΔVWAP", "Stretch"])

    with st.expander("⬇ Download the raw per-day table (columns + forward outcomes)"):
        _m = res["conv"].join(res["outcomes"], how="inner")
        st.download_button("Download CSV", _m.to_csv().encode("utf-8"),
                           file_name="conviction_positional.csv", mime="text/csv")
        st.dataframe(_m.tail(30), use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# MODE 2 — Intraday timing
# ══════════════════════════════════════════════════════════════════════════════
elif mode.startswith("Intraday"):
    _CPS = {"15 min": ("15minute", 25), "1 hour": ("60minute", 7)}
    c1, c2, c3 = st.columns([1, 1.4, 1])
    with c1:
        tf_label = st.selectbox("Candle", list(_CPS.keys()), index=1)
    with c2:
        lookback = st.slider("Lookback (calendar days)", 30, 200, 120, step=10)
    with c3:
        nbins = st.select_slider("Buckets/column", options=[3, 4, 5, 6], value=5)
    interval, cps = _CPS[tf_label]
    horizons = (cps, 2 * cps, 4 * cps)   # ≈ 1, 2, 4 sessions ahead

    st.caption(f"Forward move measured at **{horizons[0]}/{horizons[1]}/{horizons[2]} candles** "
               f"(≈ 1 / 2 / 4 sessions on {tf_label}).")

    # Same session_state gating as Mode 1 above (see comment there) — the download
    # button inside the expander below would otherwise wipe these results on click.
    if st.button("▶ Run intraday backtest", type="primary"):
        st.session_state.p22_intra_ran = True
        st.session_state.p22_intra_inputs = dict(interval=interval, lookback=lookback,
                                                  horizons=horizons, nbins=nbins)

    if not st.session_state.get("p22_intra_ran"):
        st.info("Pick a candle size and click Run. Pulls a few months of intraday futures (real "
                "volume) and scores the forward move after every reading.")
        st.stop()

    _in = st.session_state.p22_intra_inputs
    interval, lookback = _in["interval"], _in["lookback"]
    horizons, nbins = _in["horizons"], _in["nbins"]

    with st.spinner("Fetching intraday futures and running the engine…"):
        res = _run_intraday(interval, lookback, horizons, int(nbins))
    if res is None:
        st.error("Could not load intraday futures history. Log in via Home → Kite, then retry.")
        st.stop()
    st.success(f"Analysed **{res['n_rows']}** {tf_label} candles · {res['span']}")

    st.subheader("1 · Directional edge by State (which side to sell + when to exit)")
    st.caption("Per State: average forward return and up-rate at 1 / 2 / 4 sessions. Positive & "
               "high up% → bullish → **sell PUTs**; negative → bearish → **sell CALLs**. Watch the "
               "edge **decay** across horizons — that's your exit window.")
    st.dataframe(res["state_edge"], use_container_width=True, hide_index=True)

    st.divider()
    st.subheader(f"2 · Column cutoffs — forward edge over the next {horizons[0]} candles")
    st.caption("Rows bucketed low→high. **pct_up** = share that closed up · **avg_ret** = mean forward "
               "return · **avg_maxup / avg_maxdn** = the favourable/adverse excursion to size stops.")
    _render_cuts(res["cutoffs"],
                 ["State", "Final", "Bull−Bear", "Conf%", "Uptrend", "Downtr", "Topping",
                  "Reversal", "RSI", "ΔVWAP", "Stretch"])

    with st.expander("⬇ Download the raw per-candle table (columns + forward outcomes)"):
        _m = res["conv"].join(res["outcomes"], how="inner")
        st.download_button("Download CSV", _m.to_csv().encode("utf-8"),
                           file_name="conviction_intraday.csv", mime="text/csv")
        st.dataframe(_m.tail(30), use_container_width=True)
