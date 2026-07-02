# pages/22_Backtest_Optimizer.py
# Premium-seller optimizer. Runs the Conviction engine over ~2y of daily Nifty history and
# answers: (1) how far does Nifty travel in a week → how close can I sell; (2) which
# conviction-column readings precede a breach of my sold strikes → book-loss / roll / hold.
#
# You just: log in (Home → Kite) so the token is fresh, then click "Run backtest".

import pandas as pd
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
st.caption("Empirical cutoffs for your Nifty option-selling: how close you can sell, and which "
           "conviction readings warn of a strike breach before next Tuesday.")

with st.expander("⚠️ What this is (and its limits) — read once"):
    st.markdown(
        "- Runs the **anchored (positional) engine** over ~2 years of **daily** Nifty history, "
        "cycle-by-cycle, then measures the **forward 1-week / 2-week move** after every row.\n"
        "- **Fidelity caveats (first-cut):** uses the continuous **index** with synthetic equal "
        "volume, so VWAP is unweighted and the CVD/volume pillar is a price-action proxy; "
        "expected-move (Stretch) is a realized-vol estimate (no VIX history); **breadth is off**. "
        "So trust the **price/momentum/structure** columns (State, Final, Bull−Bear, RSI, ΔVWAP, "
        "Stretch, the 4 scores) more than any volume/breadth read here.\n"
        "- These are **base-rate cutoffs to stack the odds**, not guarantees. Always keep your stop.")

c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1])
with c1:
    lookback = st.slider("Lookback (calendar days)", 365, 1460, 730, step=30)
with c2:
    call_pct = st.number_input("Sold CALL distance %", 1.0, 8.0, 3.5, 0.25)
with c3:
    put_pct = st.number_input("Sold PUT distance %", 1.0, 8.0, 4.0, 0.25)
with c4:
    nbins = st.select_slider("Buckets per column", options=[3, 4, 5, 6], value=5)

run = st.button("▶ Run backtest", type="primary")


@st.cache_data(ttl=3600, show_spinner=False)
def _load_daily(days: int) -> pd.DataFrame:
    return _lf.get_nifty_intraday(interval="day", days=days)


@st.cache_data(ttl=3600, show_spinner=False)
def _run(days, cp, pp, nb):
    daily = _load_daily(days)
    if daily is None or daily.empty:
        return None
    return bt.run_backtest(daily, horizons=(5, 10), call_pct=cp, put_pct=pp, nbins=nb)


if not run:
    st.info("Set your strike distances and click **Run backtest**. First run pulls ~2y of daily "
            "candles and computes the engine over every cycle (~10–20s).")
    st.stop()

with st.spinner("Fetching history and running the engine over every cycle…"):
    res = _run(lookback, float(call_pct), float(put_pct), int(nbins))

if res is None:
    st.error("Could not load daily Nifty history from Kite. Log in via Home → Kite, then retry.")
    st.stop()

st.success(f"Analysed **{res['n_rows']}** daily rows · {res['span']}")

# ── 1. Weekly move distribution — how close can you sell? ──────────────────────
st.subheader("1 · How far does Nifty travel? (sell-closer sizing)")
st.caption("Percentiles of the forward **max-up** and **max-down** move from each day. "
           "Sell beyond the percentile that matches your target win-rate (e.g. the p90 column "
           "≈ a strike breached ~10% of the time).")
st.dataframe(res["distribution"], use_container_width=True, hide_index=True)
_d = res["distribution"]
if not _d.empty:
    _r5 = _d[_d["horizon"] == "5d"].iloc[0]
    st.caption(f"↳ 1-week read: your **+{call_pct:.2f}% call** was breached "
               f"**{_r5['call_breach%']}%** of weeks · **−{put_pct:.2f}% put** "
               f"**{_r5['put_breach%']}%**. For a ~90% hold, sell near **+{_r5['up_p90']}% / "
               f"−{_r5['dn_p90']}%**; ~95% → **+{_r5['up_p95']}% / −{_r5['dn_p95']}%**.")

st.divider()

# ── 2. Column cutoff scan — which readings warn of a breach ────────────────────
st.subheader("2 · Column cutoffs — which readings precede a breach (book-loss / roll / hold)")
st.caption("For each column, rows are bucketed low→high. **call_breach%** = how often the "
           "+call strike was hit in the next week from that bucket; **put_breach%** likewise. "
           "**pct_up5** = share of weeks that closed up. High call_breach → your sold-CALL is "
           "threatened (defend / roll up); high put_breach → sold-PUT threatened.")

cuts = res["cutoffs"]
# State first, then the numeric columns in a sensible order.
order = ["State", "Final", "Bull−Bear", "Conf%", "Downtr", "Topping", "Uptrend",
         "Reversal", "RSI", "ΔVWAP", "Stretch"]
for col in order:
    if col not in cuts:
        continue
    st.markdown(f"**{col}**")
    st.dataframe(cuts[col].reset_index(), use_container_width=True, hide_index=True)

# ── Raw data download for your own slicing ────────────────────────────────────
with st.expander("⬇ Download the raw per-day table (conviction columns + forward outcomes)"):
    _merged = res["conv"].join(res["outcomes"], how="inner")
    st.download_button("Download CSV", _merged.to_csv().encode("utf-8"),
                       file_name="conviction_backtest.csv", mime="text/csv")
    st.dataframe(_merged.tail(30), use_container_width=True)
