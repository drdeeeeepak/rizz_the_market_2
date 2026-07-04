# pages/23_Signal_Library.py
# Signal Library — runs the GENERIC signal backtest harness (analytics/signal_lab.py)
# over every adapter in analytics/signal_adapters.py and ranks them: which page's
# signal actually carries a forward edge on Nifty, and which don't.
#
# You just: log in (Home → Kite) so the token is fresh, then click "Run Signal Library".

import numpy as np
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
        "- **Continuous-futures roll gaps:** Kite's `continuous=True` stitches contracts "
        "WITHOUT back-adjustment, so every monthly rollover prints a real price jump (basis, "
        "not a market move). All 7 price-based adapters above run on the INDEX (gap-free), "
        "not futures, so they're unaffected. The OI-Buildup adapter and the section-4 real-"
        "volume rerun below both guard against it (see their own captions).\n"
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


def _build_combined_csv(ranked, results, rf, dow_scan, real_bundle=None, roll_rule=None) -> str:
    """Bundle every table this page can produce into ONE text/csv file, each
    block prefixed with a '## N. TITLE' header — a single thing to hand back
    for review instead of juggling one download per section."""
    parts = ["## 1. LEADERBOARD\n" + ranked.to_csv(index=False)]

    # Wide daily table: one row per day, one column per signal, plus the forward-outcome
    # columns once (identical across signals — all scored against the same price series).
    sig_cols, outcome_df = {}, None
    for r in results:
        det = r["detail"]
        sig_cols[r["name"]] = det["signal"]
        if outcome_df is None:
            outcome_df = det.drop(columns=["signal"])
    if sig_cols:
        wide = pd.DataFrame(sig_cols)
        if outcome_df is not None:
            wide = wide.join(outcome_df, how="outer")
        parts.append("## 2. DAILY SIGNALS + FORWARD OUTCOMES (all signals, one row per day)\n"
                     + wide.to_csv())

    bucket_rows = []
    for r in results:
        b = r["bucket"]
        if b.empty:
            continue
        b = b.reset_index()
        b.insert(0, "signal", r["name"])
        bucket_rows.append(b)
    if bucket_rows:
        parts.append("## 3. BUCKET SCANS (per signal)\n"
                     + pd.concat(bucket_rows, ignore_index=True).to_csv(index=False))

    if rf and not rf.get("by_split", pd.DataFrame()).empty:
        parts.append("## 4. RSI OVERBOUGHT-FADE WALK-FORWARD (by split)\n"
                     + rf["by_split"].to_csv(index=False))

    if dow_scan is not None and not dow_scan.empty:
        parts.append("## 5. DOW THEORY RETRACE-% BUCKET SCAN\n" + dow_scan.to_csv(index=False))

    if real_bundle is not None:
        real = real_bundle["real"]
        parts.append("## 6. REAL-VOLUME + BREADTH-ON — WEEKLY MOVE DISTRIBUTION\n"
                     + real["distribution"].to_csv(index=False))
        for col, cdf in real["cutoffs"].items():
            parts.append(f"## 6b. REAL-VOLUME + BREADTH-ON — CUTOFF: {col}\n"
                         + cdf.reset_index().to_csv())

    if roll_rule is not None:
        if not roll_rule["near"].empty:
            parts.append("## 7. ROLL-RULE SCAN — NEAR EXPIRY GRID\n"
                         + roll_rule["near"].to_csv(index=False))
        if not roll_rule["far"].empty:
            parts.append("## 7b. ROLL-RULE SCAN — BIWEEKLY (NEXT EXPIRY) GRID\n"
                         + roll_rule["far"].to_csv(index=False))
        best = pd.DataFrame([roll_rule["best_near"], roll_rule["best_far"]],
                            index=["best_near", "best_far"])
        parts.append("## 7c. ROLL-RULE SCAN — BEST (X%, Y%)\n" + best.to_csv())

    return "\n\n".join(parts)


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

# Gate on a session_state flag rather than the button's own return value: st.button()
# is only True on the ONE rerun triggered by that exact click — clicking ANY other
# widget further down the page (the §2 selectbox, §3 radio, §4 re-run button) triggers
# its own rerun where this button is False again, so a raw `if not st.button(...):
# st.stop()` gate would wipe the whole page on every one of those clicks before the
# script ever reached them. Stash the controls too, so later reruns keep using the
# last-run settings instead of needing a fresh click every time.
if st.button("▶ Run Signal Library", type="primary"):
    st.session_state.p23_ran = True
    st.session_state.p23_inputs = dict(lookback=lookback, h1_days=h1_days, selected=selected,
                                       call_pct=call_pct, put_pct=put_pct, nbins=nbins)

if not st.session_state.get("p23_ran"):
    st.info("Pick your lookback and signals, then click Run. First run pulls ~2y of daily "
            "candles + ~1y of 1H candles and scores every selected adapter (~15-30s).")
    st.stop()

_in = st.session_state.p23_inputs
lookback, h1_days, selected = _in["lookback"], _in["h1_days"], _in["selected"]
call_pct, put_pct, nbins = _in["call_pct"], _in["put_pct"], _in["nbins"]

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
st.caption("Re-runs the page-22 Conviction backtest with REAL volume (from continuous futures, "
          "merged onto the gap-free INDEX price — see caveat below) and daily advance/decline "
          "BREADTH wired in, instead of the muted synthetic-volume/breadth-off first cut. "
          "Heavy: pulls ~50 stocks' daily history (chunked, ~20-30s) — separate button so it's "
          "opt-in.")
st.caption("Price stays on the INDEX, not continuous futures directly: Kite's "
          "`continuous=True` stitches contracts WITHOUT back-adjustment, so every monthly "
          "rollover prints a real price jump (cost-of-carry basis, not a market move) that "
          "would corrupt RSI/VWAP/Stretch and the forward-outcome labels. Futures contributes "
          "real VOLUME only here.")
# Same session_state pattern as the top gate: store the result (or error) on click,
# then render it unconditionally below — otherwise it would only exist inside this
# `if st.button(...):` block and vanish the instant you touch the §2 selectbox or §3
# radio (each of those triggers a rerun where THIS button is False again).
if st.button("▶ Run real-volume + breadth-on re-run"):
    with st.spinner("Fetching continuous futures + 50-constituent daily history…"):
        fut2 = _load_fut_continuous(lookback)
        stock_daily = _load_nifty50_daily(lookback)
    if fut2 is None or fut2.empty:
        st.session_state.p23_real_error = "Could not load continuous futures history. Log in via Home → Kite, then retry."
        st.session_state.pop("p23_real_result", None)
    else:
        breadth = bt.daily_advance_breadth(stock_daily) if stock_daily else None
        real = bt.run_backtest_real(daily, fut2, breadth=breadth, horizons=(5, 10),
                                    call_pct=float(call_pct), put_pct=float(put_pct), nbins=int(nbins))
        st.session_state.p23_real_result = {"real": real, "n_constituents": len(stock_daily)}
        st.session_state.pop("p23_real_error", None)

if st.session_state.get("p23_real_error"):
    st.error(st.session_state.p23_real_error)

if "p23_real_result" in st.session_state:
    real = st.session_state.p23_real_result["real"]
    n_constituents = st.session_state.p23_real_result["n_constituents"]
    st.success(f"Analysed **{real['n_rows']}** daily rows on real futures · {real['span']} · "
              f"breadth from **{n_constituents}** constituents")
    st.dataframe(real["distribution"], use_container_width=True, hide_index=True)
    for col in ["State", "Final", "Bull−Bear", "Conf%", "RSI", "ΔVWAP", "Stretch", "Brd%"]:
        if col in real["cutoffs"]:
            st.markdown(f"**{col}**")
            st.dataframe(real["cutoffs"][col].reset_index(), use_container_width=True, hide_index=True)

# ── 5. Dow Theory — which retrace-% is actually the best entry? ────────────
st.divider()
st.subheader("5 · Dow Theory — which retrace% is actually the best entry?")
st.caption("Buckets every UPTREND day (assume you always buy) and every DOWNTREND day (assume "
          "you always short) by how deep the retrace was at entry — checks empirically whether "
          "the 60%+ 'PRIME' zone actually beats the 30-60% 'GOOD' zone, or is just a wider stop "
          "wearing a better label. **sequence=RISING** = bouncing AWAY from the last pivot low "
          "(the UT-1/DT-1 question) · **sequence=FALLING** = pulling back FROM the last pivot "
          "high (in an UPTREND, the 90-101% FALLING row is the UT-3 floor-retest; in a DOWNTREND "
          "it's the leg after a fresh low).")
h1_dow = h1 if (h1 is not None and not h1.empty) else _load_h1(h1_days)
dow_scan = sl.dow_retrace_bucket_scan(daily, h1_dow, horizons=(5, 10))
if dow_scan.empty:
    st.caption("Not enough 1H history/pivots to bucket — try a longer 1H lookback above.")
else:
    _frozen(dow_scan, height=min(60 + 30 * len(dow_scan), 460))
    st.download_button("⬇ Download Dow retrace scan CSV", dow_scan.to_csv(index=False).encode("utf-8"),
                       file_name="dow_retrace_bucket_scan.csv", mime="text/csv")

# ── 6. Roll-rule optimizer ───────────────────────────────────────────────────
st.divider()
st.subheader("6 · Roll-rule optimizer — find the best X%/Y% roll rule")
st.caption("Your rule: sell CALL/PUT at a fixed % from the Tuesday anchor. Every time drift from "
          "anchor reaches a NEW multiple of X%, roll the OTHER (now-safer) leg inward by Y% of "
          "its OWN current strike — repeatable, as many times as drift keeps extending. Checks "
          "whether that rolled leg avoids a CLOSE-based breach (not intraday wicks) through both "
          "the near (this Tuesday) and biweekly (next Tuesday too, since positions run two "
          "cycles) expiry windows.")
st.caption("No real option premium/IV data in a spot-only backtest — 'best' is picked by "
          "survival rate; avg_rolls is a rough stand-in for 'more premium captured', not a real "
          "number. breach_on_rolled_leg% / breach_on_original_leg% split WHY a cycle failed: the "
          "rule itself getting caught by a reversal, vs. the untouched original leg finally "
          "giving way (a risk this rule was never trying to solve).")

rc1, rc2 = st.columns(2)
with rc1:
    roll_call_pct = st.number_input("Sold CALL % from anchor", 1.0, 8.0, 3.0, 0.25, key="roll_call_pct")
with rc2:
    roll_put_pct = st.number_input("Sold PUT % from anchor", 1.0, 8.0, 3.5, 0.25, key="roll_put_pct")
rc3, rc4 = st.columns(2)
with rc3:
    x_range = st.slider("X% grid range (drift trigger)", 0.25, 4.0, (0.5, 2.5), 0.25, key="roll_x_range")
    x_step = st.select_slider("X% step", options=[0.25, 0.5, 1.0], value=0.5, key="roll_x_step")
with rc4:
    y_range = st.slider("Y% grid range (roll-in size)", 0.1, 3.0, (0.25, 1.5), 0.15, key="roll_y_range")
    y_step = st.select_slider("Y% step", options=[0.1, 0.25, 0.5], value=0.25, key="roll_y_step")

x_grid = tuple(np.round(np.arange(x_range[0], x_range[1] + 1e-9, x_step), 3))
y_grid = tuple(np.round(np.arange(y_range[0], y_range[1] + 1e-9, y_step), 3))
st.caption(f"Grid: X ∈ {list(x_grid)} · Y ∈ {list(y_grid)} → {len(x_grid) * len(y_grid)} combinations "
          f"× {len(daily)} daily rows.")

if st.button("▶ Run roll-rule scan"):
    with st.spinner(f"Simulating {len(x_grid) * len(y_grid)} (X, Y) combinations across every weekly cycle…"):
        rr = sl.roll_rule_scan(daily, x_grid=x_grid, y_grid=y_grid,
                               call_pct=float(roll_call_pct), put_pct=float(roll_put_pct))
    st.session_state.p23_roll_rule = rr

if "p23_roll_rule" in st.session_state:
    rr = st.session_state.p23_roll_rule
    st.success(f"Simulated **{rr['n_cycles']}** weekly cycles · CALL {rr['call_pct']}% / "
              f"PUT {rr['put_pct']}% from anchor")

    _rr_keys = ("x%", "y%", "n", "survival_rate%", "avg_rolls",
               "breach_on_rolled_leg%", "breach_on_original_leg%")
    cA, cB = st.columns(2)
    with cA:
        st.markdown("**Best — near expiry (this week)**")
        if rr["best_near"]:
            st.json({k: rr["best_near"][k] for k in _rr_keys})
    with cB:
        st.markdown("**Best — biweekly (through next expiry too)**")
        if rr["best_far"]:
            st.json({k: rr["best_far"][k] for k in _rr_keys})

    st.markdown("**Full grid — near expiry**")
    if rr["near"].empty:
        st.caption("Not enough Tuesday-anchored cycles in this history.")
    else:
        _frozen(rr["near"], height=min(60 + 28 * len(rr["near"]), 460), reset=False)
        st.download_button("⬇ Download near-expiry grid CSV", rr["near"].to_csv(index=False).encode("utf-8"),
                           file_name="roll_rule_near.csv", mime="text/csv", key="dl_roll_near")

    st.markdown("**Full grid — biweekly (through next expiry)**")
    if rr["far"].empty:
        st.caption("Not enough Tuesday-anchored cycles in this history.")
    else:
        _frozen(rr["far"], height=min(60 + 28 * len(rr["far"]), 460), reset=False)
        st.download_button("⬇ Download biweekly grid CSV", rr["far"].to_csv(index=False).encode("utf-8"),
                           file_name="roll_rule_far.csv", mime="text/csv", key="dl_roll_far")

# ── 7. Download everything as one CSV ───────────────────────────────────────
st.divider()
st.subheader("7 · Download everything as one CSV")
st.caption("Bundles every table above — leaderboard, all signals' daily values + forward "
          "outcomes, all bucket scans, the RSI walk-forward, the Dow retrace scan, and the "
          "real-volume rerun / roll-rule scan if you ran them — into ONE file with "
          "'## N. TITLE' section headers. Easiest single thing to hand back for review.")
combined = _build_combined_csv(ranked, results, rf, dow_scan, st.session_state.get("p23_real_result"),
                               st.session_state.get("p23_roll_rule"))
st.download_button("⬇ Download everything (combined CSV)", combined.encode("utf-8"),
                   file_name="signal_library_full_export.csv", mime="text/csv", type="primary")
