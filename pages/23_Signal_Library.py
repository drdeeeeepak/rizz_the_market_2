# pages/23_Signal_Library.py
# Signal Library — runs the GENERIC signal backtest harness (analytics/signal_lab.py)
# over every adapter in analytics/signal_adapters.py and ranks them: which page's
# signal actually carries a forward edge on Nifty, and which don't.
#
# You just: log in (Home → Kite) so the token is fresh, then click "Run Signal Library".

import pandas as pd
import streamlit as st

import importlib
import data.live_fetcher as _lf
from analytics import backtest as bt
from analytics import signal_lab as sl
from analytics import signal_adapters as sa
import ui.conviction_table as uict

try:
    importlib.reload(_lf)
    importlib.reload(bt)
    importlib.reload(sl)
    importlib.reload(sa)
    importlib.reload(uict)
except Exception:
    pass

st.set_page_config(page_title="P23 · Signal Library", layout="wide")
st.title("Page 23 — Signal Library")
st.caption("Ranks EVERY page's core signal on the SAME forward-outcome framework as the "
           "Conviction backtest (page 22) — one leaderboard to decide which pages to keep, "
           "change, or cut.")

with st.expander("⚠️ What this is (and its limits) — read once"):
    st.markdown(
        "- **Signal contract:** each adapter emits one directional score per trading day "
        "(+ = bullish, − = bearish, 0 = no opinion), reusing the real page's own engine "
        "functions — not a reimplementation. See `analytics/signal_adapters.py` docstrings "
        "for the exact sign convention each page was coded with.\n"
        "- **Cadence:** all adapters are read at DAILY granularity, even ones whose live page "
        "runs intraday (Dow Theory, EMA Slope Phases use the last confirmed 1H bar of the "
        "day) — this keeps every signal comparable on the same forward-outcome table.\n"
        "- **Bollinger %B is coded mean-reversion** (fade), matching the OVERBOUGHT-FADE edge "
        "already found for %B/RSI on the Conviction table. **RSI Weekly is coded "
        "continuation**, matching page 05's designed use — a negative Spearman there would "
        "say the fade pattern holds weekly too; the harness doesn't assume either way.\n"
        "- **Futures OI Buildup** needs continuous-futures OI history (`get_nifty_fut_continuous`) "
        "— option-chain GEX/gamma-flip has NO history at all (only the forward gamma_history "
        "log) and isn't back-testable here.\n"
        "- **Daily breadth** (advance/decline, % of Nifty-50 above their own PREVIOUS CLOSE) is "
        "a COUSIN of the live Conviction table's Brd% (% above session VWAP, intraday) — it "
        "tests whether breadth adds edge at the daily/weekly horizon, not a re-test of that "
        "exact column. Uses today's Nifty-50 membership applied historically (survivorship).\n"
        "- These are **base-rate edges to decide what to build on**, not guarantees.")


# ── cached loaders ──────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _load_daily(days):
    return _lf.get_nifty_daily(days=days)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_h1(days):
    return _lf.get_nifty_1h_phase(days=days)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_fut_continuous(days):
    return _lf.get_nifty_fut_continuous(days=days)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_nifty50_daily(days):
    return _lf.get_nifty50_daily(days=days)


def _frozen(df: pd.DataFrame, height=360, reset=True):
    d = df.reset_index() if reset else df
    st.markdown(uict.candle_table_frozen_html(d, height=height), unsafe_allow_html=True)


# ── controls ─────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1])
with c1:
    lookback = st.slider("Daily lookback (calendar days)", 365, 1460, 730, step=30)
with c2:
    call_pct = st.number_input("Sold CALL distance %", 1.0, 8.0, 3.5, 0.25)
with c3:
    put_pct = st.number_input("Sold PUT distance %", 1.0, 8.0, 4.0, 0.25)
with c4:
    nbins = st.select_slider("Buckets/column", options=[3, 4, 5, 6], value=5)

h1_days = st.slider("1H lookback for Dow Theory / EMA Slope Phases (trading days, "
                    "capped by Kite's 60-min history limit)", 60, 380, 260, step=20)

all_labels = list(sa.ADAPTERS.keys())
selected = st.multiselect("Signals to run", all_labels, default=all_labels)

if not st.button("▶ Run Signal Library", type="primary"):
    st.info("Pick your lookback and signals, then click Run. First run pulls ~2y of daily "
            "candles + ~1y of 1H candles and scores every selected adapter (~15-30s).")
    st.stop()

with st.spinner("Fetching history and scoring every signal…"):
    daily = _load_daily(lookback)
    needs = {n for lbl in selected for n in sa.ADAPTERS[lbl]["needs"]}
    h1 = _load_h1(h1_days) if "h1" in needs else pd.DataFrame()
    fut_daily = _load_fut_continuous(lookback) if "fut_daily" in needs else pd.DataFrame()

if daily is None or daily.empty:
    st.error("Could not load daily Nifty history. Log in via Home → Kite, then retry.")
    st.stop()

data_map = {"daily": daily, "h1": h1, "fut_daily": fut_daily}
results, skipped = [], []
for label in selected:
    meta = sa.ADAPTERS[label]
    kwargs = {}
    missing = False
    for n in meta["needs"]:
        frame = data_map.get(n)
        if frame is None or frame.empty:
            missing = True
        kwargs[{"daily": "daily", "h1": "df_1h", "fut_daily": "fut_daily"}[n]] = frame
    if missing:
        skipped.append(label)
        continue
    try:
        sig = meta["fn"](**kwargs)
        res = sl.evaluate_signal(daily, sig, name=label, horizons=(5, 10),
                                 call_pct=float(call_pct), put_pct=float(put_pct), nbins=int(nbins))
        results.append(res)
    except Exception as e:
        skipped.append(f"{label} (error: {e})")

st.success(f"Analysed **{len(daily)}** daily rows · scored **{len(results)}/{len(selected)}** signals")
if skipped:
    st.caption(f"Skipped (missing data or error): {', '.join(skipped)}")

# ── 1. Leaderboard ─────────────────────────────────────────────────────────
st.subheader("1 · Leaderboard — ranked by |expectancy| at the 5-day horizon")
st.caption("**hit_rate%** = share of active days the signal called the forward direction "
          "correctly · **expectancy%** = avg forward move in the called direction · "
          "**spearman** = rank correlation between the raw score and the forward return "
          "(works even when hit_rate/expectancy are muted by a near-zero score).")
ranked = sl.rank_signals(results)
if ranked.empty:
    st.warning("No signals scored — check the skip list above.")
    st.stop()
_frozen(ranked, height=min(60 + 40 * len(ranked), 420), reset=False)

st.download_button("⬇ Download leaderboard CSV", ranked.to_csv(index=False).encode("utf-8"),
                   file_name="signal_library_leaderboard.csv", mime="text/csv")

# ── 2. Per-signal detail ────────────────────────────────────────────────────
st.divider()
st.subheader("2 · Per-signal detail — bucket scan + weekly move distribution")
by_name = {r["name"]: r for r in results}
pick = st.selectbox("Signal", ranked["signal"].tolist())
r = by_name[pick]
cA, cB = st.columns(2)
with cA:
    st.markdown(f"**{pick} — scorecard**")
    st.json({k: r[k] for k in ("n", "n_active", "hit_rate", "expectancy", "spearman", "span")})
with cB:
    st.markdown("**Weekly move distribution (this Nifty history, all days)**")
    st.dataframe(r["distribution"], use_container_width=True, hide_index=True)

st.markdown(f"**{pick} — bucket scan** (quantile-binned raw score → forward edge)")
if r["bucket"].empty:
    st.caption("Not enough active rows to bucket.")
else:
    _frozen(r["bucket"], height=280)

with st.expander("⬇ Download this signal's raw per-day table"):
    st.download_button("Download CSV", r["detail"].to_csv().encode("utf-8"),
                       file_name=f"signal_{pick.replace(' ', '_')}.csv", mime="text/csv",
                       key=f"dl_{pick}")
    st.dataframe(r["detail"].tail(30), use_container_width=True)

# ── 3. Walk-forward: RSI overbought-fade rule ───────────────────────────────
st.divider()
st.subheader("3 · Walk-forward check — the overbought-fade RSI rule")
st.caption("Out-of-sample check for the rule found on page 22: SHORT/sell-CALLs when "
          "Conviction-table RSI ≥ 62 AND Bull−Bear ≥ 45. Split by year — does the edge "
          "survive outside the one regime it was found in?")
split_by = st.radio("Split", ["year", "half"], horizontal=True, key="wf_split")
rf = sl.rsi_fade_walk_forward(daily, horizons=(5, 10), by=split_by)
st.markdown("**Overall (whole sample)**")
st.json(rf["overall"])
st.markdown("**By split**")
if rf["by_split"].empty:
    st.caption("Not enough conviction-table rows to split (need RSI/Bull−Bear columns — "
              "check the daily fetch above.)")
else:
    _frozen(rf["by_split"], height=min(60 + 40 * len(rf["by_split"]), 320))

# ── 4. Advanced: real-volume + breadth-on Conviction re-run ────────────────
st.divider()
st.subheader("4 · Advanced — real-volume + breadth-on Conviction re-run")
st.caption("Re-runs the page-22 Conviction backtest on CONTINUOUS FUTURES (real volume → "
          "real CVD) with daily advance/decline BREADTH wired in, instead of the muted "
          "synthetic-volume/breadth-off first cut. Heavy: pulls ~50 stocks' daily history "
          "(chunked, ~20-30s) — separate button so it's opt-in.")
if st.button("▶ Run real-volume + breadth-on re-run"):
    with st.spinner("Fetching continuous futures + 50-constituent daily history…"):
        fut2 = _load_fut_continuous(lookback)
        stock_daily = _load_nifty50_daily(lookback)
    if fut2 is None or fut2.empty:
        st.error("Could not load continuous futures history. Log in via Home → Kite, then retry.")
    else:
        breadth = bt.daily_advance_breadth(stock_daily) if stock_daily else None
        real = bt.run_backtest_real(fut2, breadth=breadth, horizons=(5, 10),
                                    call_pct=float(call_pct), put_pct=float(put_pct), nbins=int(nbins))
        st.success(f"Analysed **{real['n_rows']}** daily rows on real futures · {real['span']} · "
                  f"breadth from **{len(stock_daily)}** constituents")
        st.dataframe(real["distribution"], use_container_width=True, hide_index=True)
        for col in ["State", "Final", "Bull−Bear", "Conf%", "RSI", "ΔVWAP", "Stretch", "Brd%"]:
            if col in real["cutoffs"]:
                st.markdown(f"**{col}**")
                st.dataframe(real["cutoffs"][col].reset_index(), use_container_width=True, hide_index=True)
