# pages/25_Roll_Management_Backtest.py
# Roll & Position Management — every backtest that answers "when should I roll
# an EXISTING Iron Condor leg, and by how much" in one place. Moved out of
# pages 22/23 (which were carrying entry-timing / signal-ranking work
# alongside these) to keep those pages fast and give roll-management its own
# rule book, mirroring page 24's pattern for entry-timing.
#
# You just: log in (Home → Kite) so the token is fresh, then click each
# section's own Run button — every section is independent and only needs
# Nifty daily candles.

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

import importlib
import data.live_fetcher as _lf
from analytics import backtest as bt
from analytics import signal_lab as sl
import ui.conviction_table as uict

try:
    importlib.reload(_lf)
    importlib.reload(bt)
    importlib.reload(sl)
    importlib.reload(uict)
except Exception:
    pass

st.set_page_config(page_title="P25 · Roll Management", layout="wide")
st.title("Page 25 — Roll & Position Management")
st.caption("Every backtest for managing an EXISTING Iron Condor: when to roll the profit leg in, "
           "when to roll/shift the loss leg out, and what anchor-drift threshold actually marks "
           "the turn. Split off pages 22/23 to keep those fast — see page 24 instead for a "
           "DIFFERENT question (is a FRESH short safe to place right now).")

with st.expander("⚠️ What this is (and its limits) — read once"):
    st.markdown(
        "- **Roll threshold** (section 1) replays the LIVE anchor/roll rule "
        "(`data/rolled_positions.py`) — a pure anchor-drift PATTERN test, with **no knowledge of "
        "your actual sold-strike distance**.\n"
        "- **Anchor close-distribution / strike-shift ladders / roll-rule optimizer** (sections "
        "2, 5, 6, 7) all take your REAL call_pct/put_pct as inputs — these are the strike-aware "
        "tools, and the ones that answer strike-breach questions directly.\n"
        "- **Anchor-drift scans** (sections 3, 4) test whether price mean-reverts or continues "
        "past a given drift%, the empirical basis for picking a trigger in the first place.\n"
        "- No historical option premium/IV data exists anywhere in this app (Kite only gives a "
        "LIVE chain snapshot, not historical option prices) — every table here is scored on "
        "**survival** (did the strike hold), never P&L. `avg_rolls` is the closest proxy for "
        "premium captured, not a real number.\n"
        "- These are base-rate cutoffs to stack the odds, not guarantees. Keep your existing "
        "stop/roll discipline regardless.")

_rulebook_path = Path(__file__).resolve().parent.parent / "docs" / "PAGE_25_RULE_BOOK.md"
with st.expander("📜 Roll-management rule book (read this first)"):
    if _rulebook_path.exists():
        st.markdown(_rulebook_path.read_text())
    else:
        st.caption("Not written yet — run the sections below first.")


@st.cache_data(ttl=3600, show_spinner=False)
def _load_daily(days):
    return _lf.get_nifty_daily(days=days)


def _frozen(df: pd.DataFrame, height=360, reset=True):
    d = df.reset_index() if reset else df
    st.markdown(uict.candle_table_frozen_html(d, height=height), unsafe_allow_html=True)


lookback = st.slider("Daily lookback (calendar days) — shared by every section below",
                     365, 1460, 730, step=30, key="p25_lookback")

# ══════════════════════════════════════════════════════════════════════════════
# 1 · Roll threshold — pure anchor-drift pattern (moved from page 22)
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("1 · Roll threshold — when to roll (pure anchor-drift pattern)")
st.caption("Replays the live anchor/roll logic (`data/rolled_positions.py`) over every historical "
           "Tue→Tue cycle at candidate profit/loss triggers, and scores each: which trigger keeps "
           "a cycle **one-sided** (only the threatened leg gets re-sold, the other stays put) most "
           "often, vs. triggers that **whipsaw both legs** in the same cycle or let a **hard loss** "
           "reset through. Today's live triggers are **1.8% profit / 2.5% loss**. This has **no "
           "knowledge of your actual sold-strike distance** — for that, use the Roll-rule "
           "optimizer (section 7 below) instead.")

rc1, rc2, rc3 = st.columns([1.2, 1.2, 0.8])
with rc1:
    pt_lo, pt_hi = st.slider("Profit-trigger scan range (%)", 0.5, 4.0, (1.0, 3.0), 0.25, key="p25_pt_range")
with rc2:
    lt_lo, lt_hi = st.slider("Loss-trigger scan range (%)", 1.5, 5.0, (2.0, 4.0), 0.25, key="p25_lt_range")
with rc3:
    rt_step = st.select_slider("Scan step (%)", options=[0.1, 0.25, 0.5], value=0.25, key="p25_rt_step")

if st.button("▶ Run roll-threshold scan", key="p25_rt_run"):
    st.session_state.p25_rt_ran = True
    st.session_state.p25_rt_inputs = dict(pt_lo=pt_lo, pt_hi=pt_hi, lt_lo=lt_lo, lt_hi=lt_hi, step=rt_step)

if st.session_state.get("p25_rt_ran"):
    _in = st.session_state.p25_rt_inputs
    profit_thrs = tuple(round(x, 2) for x in np.arange(_in["pt_lo"], _in["pt_hi"] + 1e-9, _in["step"]))
    loss_thrs = tuple(round(x, 2) for x in np.arange(_in["lt_lo"], _in["lt_hi"] + 1e-9, _in["step"]))
    with st.spinner("Fetching daily history and scanning roll triggers…"):
        _d = _load_daily(lookback)
        rt_scan = bt.roll_threshold_scan(_d, profit_thrs=profit_thrs, loss_thrs=loss_thrs) \
            if _d is not None and not _d.empty else pd.DataFrame()

    if rt_scan.empty:
        st.error("Could not load daily Nifty history, or no valid (profit_thr, loss_thr) combos "
                 "(loss_thr must be > profit_thr). Log in via Home → Kite, then retry.")
    else:
        rt_best = bt.best_roll_threshold(rt_scan)
        st.success(f"Scanned **{len(rt_scan)}** trigger combos over **{rt_best['n_cycles']}** "
                  f"historical weekly cycles.")
        st.markdown(f"**Roll profit at ±{rt_best['profit_thr']}%** / **roll loss at ±{rt_best['loss_thr']}%** "
                   f"from anchor — left the opposite leg untouched in **{rt_best['clean_pct']}%** of cycles, "
                   f"with a hard-loss reset in only **{rt_best['loss_pct']}%** (score {rt_best['score']}).")
        st.caption("`clean_pct` = only the threatened leg was re-sold, the other side undisturbed all "
                  "cycle. `loss_pct` = a hard adverse breach forced both legs to reset. `score` = "
                  "clean_pct − 2×loss_pct (a loss reset is weighted worse than a clean one-sided roll).")
        st.dataframe(rt_scan, use_container_width=True, hide_index=True)
        with st.expander("⬇ Download the full scan"):
            st.download_button("Download CSV", rt_scan.to_csv(index=False).encode("utf-8"),
                               file_name="roll_threshold_scan.csv", mime="text/csv", key="p25_dl_rt")
else:
    st.info("Pick scan ranges and click Run.")

# ══════════════════════════════════════════════════════════════════════════════
# 2 · Anchor close-distribution scan (moved from page 23)
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("2 · Anchor close-distribution — % of weeks/biweeks closing in each 0.5% band")
st.caption("For every Tuesday-anchored cycle, buckets the FINAL close-to-close drift from anchor "
          "(next Tuesday for 1-week, the Tuesday after that for 2-week/biweekly) into fixed 0.5% "
          "bands, split by direction (up-close vs down-close), with anything beyond 5% grouped "
          "into one '5%+' catch-all. pct_of_all_cycles% is out of ALL cycles for that window — "
          "the up-row and down-row percentages sum to 100% together. The direct histogram behind "
          "picking a strike distance.")

if st.button("▶ Run anchor close-distribution scan", key="p25_dist_run"):
    with st.spinner("Fetching daily history…"):
        st.session_state.p25_dist_result = sl.anchor_close_distribution_scan(_load_daily(lookback))

if "p25_dist_result" in st.session_state:
    dist = st.session_state.p25_dist_result
    dc1, dc2 = st.columns(2)
    for _key, _label, _col in (("1_week", "1-week (Tuesday → next Tuesday)", dc1),
                               ("2_week", "2-week / biweekly (Tuesday → Tuesday after next)", dc2)):
        ddf = dist[_key]
        with _col:
            st.markdown(f"**{_label}**")
            if ddf.empty:
                st.caption("Not enough Tuesday-anchored cycles in this history.")
            else:
                _frozen(ddf, height=min(60 + 24 * len(ddf), 460), reset=False)
                st.download_button(f"⬇ Download {_label} distribution CSV",
                                   ddf.to_csv(index=False).encode("utf-8"),
                                   file_name=f"anchor_close_distribution_{_key}.csv",
                                   mime="text/csv", key=f"p25_dl_dist_{_key}")

# ══════════════════════════════════════════════════════════════════════════════
# 3 · Anchor-drift — does Nifty mean-revert or continue? (moved from page 23 §6)
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("3 · Anchor-drift — does Nifty mean-revert or continue?")
st.caption("Buckets every day inside a weekly cycle by its CURRENT |drift| from the Tuesday "
          "anchor, then checks where price ends up by THAT SAME cycle's close (next Tuesday): "
          "did drift extend further the same way (**continuation**) or shrink/flip back toward "
          "anchor (**mean-reversion**)? Tests claims like 'reverts below 2%, continues above 2%' "
          "against real numbers instead of a hunch. avg_extension_pts > 0 → continuation on "
          "average in that bucket; < 0 → reversion.")
drift_bins_str = st.text_input("Drift bucket edges (%, comma-separated)", "0,1,2,3,5,100",
                               key="p25_drift_bins")
try:
    drift_bins = tuple(float(x.strip()) for x in drift_bins_str.split(","))
except ValueError:
    drift_bins = (0, 1, 2, 3, 5, 100)
    st.caption("Couldn't parse bucket edges — using default 0,1,2,3,5,100.")

if st.button("▶ Run anchor-drift reversion scan", key="p25_adr_run"):
    with st.spinner("Fetching daily history…"):
        st.session_state.p25_adr_result = sl.anchor_drift_reversion_scan(
            _load_daily(lookback), drift_bins=drift_bins)

if "p25_adr_result" in st.session_state:
    adr = st.session_state.p25_adr_result
    if adr.empty:
        st.caption("Not enough Tuesday-anchored cycles in this history.")
    else:
        _frozen(adr, height=min(60 + 30 * len(adr), 360), reset=False)
        st.download_button("⬇ Download anchor-drift scan CSV", adr.to_csv(index=False).encode("utf-8"),
                           file_name="anchor_drift_reversion_scan.csv", mime="text/csv", key="p25_dl_adr")

# ══════════════════════════════════════════════════════════════════════════════
# 4 · Anchor-drift — optimum threshold (moved from page 23 §6b)
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("4 · Anchor-drift — optimum threshold (best breakpoint)")
st.caption("Instead of fixed buckets, scans every candidate drift% threshold X and scores the "
          "'reverts below X% / continues above X%' rule of thumb directly: "
          "**reversion_rate_below%** = among days already under X% drift, how often price gave "
          "ground back by that cycle's close; **continuation_rate_above%** = among days at/over "
          "X%, how often it kept extending; **accuracy%** is the n-weighted blend of the two — "
          "the single X% with the highest accuracy% is the cleanest breakpoint this history "
          "supports. Run for BOTH the 1-week cycle and the 2-week/biweekly cycle, since positions "
          "are held both.")

if st.button("▶ Run anchor-drift optimum-threshold scan", key="p25_opt_run"):
    with st.spinner("Fetching daily history…"):
        st.session_state.p25_opt_result = sl.anchor_drift_optimum_threshold_scan(_load_daily(lookback))

if "p25_opt_result" in st.session_state:
    opt = st.session_state.p25_opt_result
    oc1, oc2 = st.columns(2)
    for _key, _label, _col in (("1_week", "Best — 1-week", oc1),
                               ("2_week", "Best — 2-week (biweekly)", oc2)):
        bundle = opt[_key]
        with _col:
            st.markdown(f"**{_label}**")
            if bundle["best"] is None:
                st.caption("Not enough Tuesday-anchored cycles / observations per side in this history.")
            else:
                st.json({k: bundle["best"][k] for k in
                        ("threshold%", "n_below", "reversion_rate_below%",
                         "n_above", "continuation_rate_above%", "accuracy%")})

    for _key, _label in (("1_week", "1-week"), ("2_week", "2-week / biweekly")):
        scan_df = opt[_key]["scan"]
        if scan_df.empty:
            continue
        st.markdown(f"**Full threshold scan — {_label}**")
        _frozen(scan_df, height=min(60 + 24 * len(scan_df), 420), reset=False)
        st.download_button(f"⬇ Download {_label} threshold scan CSV",
                           scan_df.to_csv(index=False).encode("utf-8"),
                           file_name=f"anchor_drift_optimum_threshold_{_key}.csv", mime="text/csv",
                           key=f"p25_dl_opt_{_key}")

# ══════════════════════════════════════════════════════════════════════════════
# 5 · Strike-shift ladder backtest (moved from page 23)
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("5 · Strike-shift ladder backtest — fixed asymmetric roll schedule")
st.caption("Your rule: keep CALL/PUT at their starting OTM %; whichever leg sits on the OPPOSITE "
          "side of the move is the 'safe' leg, and it shifts INWARD by a FIXED Nifty-point amount "
          "(absolute, not a % of anchor — so it lands on real strike spacing regardless of index "
          "level) each time |drift| from anchor reaches the next trigger — CALL shifts down on a "
          "fall, PUT shifts up on a rise. Each direction's ladder is independent (a reversal "
          "doesn't reset it), and once all steps are used the leg stays put for the rest of the "
          "cycle. Runs against BOTH the near (this Tuesday) and biweekly (next Tuesday) windows, "
          "each alongside a no-shift baseline on the identical cycles for direct comparison.")

lc1, lc2 = st.columns(2)
with lc1:
    ladder_call_pct = st.number_input("Sold CALL % from anchor", 1.0, 8.0, 3.0, 0.25, key="p25_ladder_call_pct")
with lc2:
    ladder_put_pct = st.number_input("Sold PUT % from anchor", 1.0, 8.0, 3.5, 0.25, key="p25_ladder_put_pct")
lc3, lc4 = st.columns(2)
with lc3:
    ladder_triggers_str = st.text_input("Triggers — cumulative |drift| % from anchor (comma-separated)",
                                        "1.0,2.0,2.5", key="p25_ladder_triggers")
with lc4:
    ladder_shift_pts_str = st.text_input("Shifts — FIXED Nifty points the safe leg moves at each trigger",
                                         "50,50,200", key="p25_ladder_shift_pts")
try:
    ladder_triggers = tuple(float(x.strip()) for x in ladder_triggers_str.split(","))
    ladder_shift_pts = tuple(float(x.strip()) for x in ladder_shift_pts_str.split(","))
    ladder_valid = len(ladder_triggers) == len(ladder_shift_pts)
except ValueError:
    ladder_triggers, ladder_shift_pts, ladder_valid = (), (), False
if not ladder_valid:
    st.caption("Triggers and shift points must both parse and have the same number of steps — "
              "using default 1.0,2.0,2.5 / 50,50,200.")
    ladder_triggers, ladder_shift_pts = sl.LADDER_TRIGGERS_DEFAULT, sl.LADDER_SHIFT_PTS_DEFAULT

if st.button("▶ Run strike-shift ladder backtest", key="p25_ladder_run"):
    with st.spinner("Fetching daily history and simulating every cycle…"):
        st.session_state.p25_ladder_result = sl.strike_shift_ladder_scan(
            _load_daily(lookback), call_pct=float(ladder_call_pct), put_pct=float(ladder_put_pct),
            triggers=ladder_triggers, shift_pts=ladder_shift_pts)

if "p25_ladder_result" in st.session_state:
    lr = st.session_state.p25_ladder_result
    st.success(f"Simulated **{lr['n_cycles']}** weekly cycles · CALL {lr['call_pct']}% / "
              f"PUT {lr['put_pct']}% · triggers {lr['triggers']} · shift_pts {lr['shift_pts']}")

    ld1, ld2 = st.columns(2)
    _ladder_keys = ("n", "survival_rate%", "baseline_survival_rate%", "avg_steps_used",
                   "breach_on_shifted_leg%", "breach_on_original_leg%")
    for _key, _label, _col in (("near", "Near expiry (this week)", ld1),
                               ("far", "Biweekly (through next expiry)", ld2)):
        bundle = lr[_key]
        with _col:
            st.markdown(f"**{_label}**")
            st.json({k: bundle["agg"][k] for k in _ladder_keys})

    st.markdown("**Per-cycle detail — near expiry**")
    if lr["near"]["detail"].empty:
        st.caption("Not enough Tuesday-anchored cycles in this history.")
    else:
        _frozen(lr["near"]["detail"], height=min(60 + 28 * len(lr["near"]["detail"]), 460), reset=False)
        st.download_button("⬇ Download near-expiry detail CSV",
                           lr["near"]["detail"].to_csv(index=False).encode("utf-8"),
                           file_name="strike_shift_ladder_near.csv", mime="text/csv", key="p25_dl_ladder_near")

    st.markdown("**Per-cycle detail — biweekly**")
    if lr["far"]["detail"].empty:
        st.caption("Not enough Tuesday-anchored cycles in this history.")
    else:
        _frozen(lr["far"]["detail"], height=min(60 + 28 * len(lr["far"]["detail"]), 460), reset=False)
        st.download_button("⬇ Download biweekly detail CSV",
                           lr["far"]["detail"].to_csv(index=False).encode("utf-8"),
                           file_name="strike_shift_ladder_far.csv", mime="text/csv", key="p25_dl_ladder_far")

# ══════════════════════════════════════════════════════════════════════════════
# 6 · Strike-shift ladder v2 — 4th escalation on actual breach (moved from page 23)
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("6 · Strike-shift ladder — 4th (final) adjustment on actual breach")
st.caption("Adds ONE more escalation on top of the 3-step drift ladder above (section 5 — uses "
          "the SAME triggers/shift_pts entered there): if the ORIGINAL sold strike (CALL 3% / "
          "PUT 3.5%, editable below) is actually breached on an EOD close, the OTHER (still-"
          "safe/profit) leg shifts one more FIXED 300 points, then the run keeps going to check "
          "whether that leg is ALSO breached before cycle-end (a 'double breach'). survival_rate% "
          "here means the same as above (any breach at all) and can't change from this step — it "
          "only fires AFTER the first breach. What it DOES answer: among cycles that breach, does "
          "the extra 300-pt shift make a second, opposite-side breach MORE or LESS likely, vs. "
          "the identical price path with no 4th shift at all.")

vc1, vc2 = st.columns(2)
with vc1:
    v2_call_pct = st.number_input("Sold CALL % from anchor", 1.0, 8.0, 3.0, 0.25, key="p25_v2_call_pct")
with vc2:
    v2_put_pct = st.number_input("Sold PUT % from anchor", 1.0, 8.0, 3.5, 0.25, key="p25_v2_put_pct")
v2_breach_shift_pts = st.number_input("Extra points the profit leg shifts once the sold strike breaches",
                                      50.0, 1000.0, 300.0, 25.0, key="p25_v2_breach_shift_pts")

if st.button("▶ Run 4th-adjustment (breach-triggered) backtest", key="p25_ladder_v2_run"):
    with st.spinner("Fetching daily history and simulating every cycle…"):
        st.session_state.p25_ladder_v2_result = sl.strike_shift_ladder_v2_scan(
            _load_daily(lookback), call_pct=float(v2_call_pct), put_pct=float(v2_put_pct),
            triggers=ladder_triggers, shift_pts=ladder_shift_pts,
            breach_shift_pts=float(v2_breach_shift_pts))

if "p25_ladder_v2_result" in st.session_state:
    v2r = st.session_state.p25_ladder_v2_result
    st.success(f"Simulated **{v2r['n_cycles']}** weekly cycles · CALL {v2r['call_pct']}% / "
              f"PUT {v2r['put_pct']}% · triggers {v2r['triggers']} · shift_pts {v2r['shift_pts']} · "
              f"breach shift {v2r['breach_shift_pts']}pts")

    v2d1, v2d2 = st.columns(2)
    _v2_keys = ("n", "survival_rate%", "n_breached", "double_breach_rate%",
               "double_breach_rate_without_step4%", "avg_steps_used")
    for _key, _label, _col in (("near", "Near expiry (this week)", v2d1),
                               ("far", "Biweekly (through next expiry)", v2d2)):
        bundle = v2r[_key]
        with _col:
            st.markdown(f"**{_label}**")
            st.json({k: bundle["agg"][k] for k in _v2_keys})

    st.markdown("**Per-cycle detail — near expiry**")
    if v2r["near"]["detail"].empty:
        st.caption("Not enough Tuesday-anchored cycles in this history.")
    else:
        _frozen(v2r["near"]["detail"], height=min(60 + 28 * len(v2r["near"]["detail"]), 460), reset=False)
        st.download_button("⬇ Download near-expiry detail CSV",
                           v2r["near"]["detail"].to_csv(index=False).encode("utf-8"),
                           file_name="strike_shift_ladder_v2_near.csv", mime="text/csv",
                           key="p25_dl_ladder_v2_near")

    st.markdown("**Per-cycle detail — biweekly**")
    if v2r["far"]["detail"].empty:
        st.caption("Not enough Tuesday-anchored cycles in this history.")
    else:
        _frozen(v2r["far"]["detail"], height=min(60 + 28 * len(v2r["far"]["detail"]), 460), reset=False)
        st.download_button("⬇ Download biweekly detail CSV",
                           v2r["far"]["detail"].to_csv(index=False).encode("utf-8"),
                           file_name="strike_shift_ladder_v2_far.csv", mime="text/csv",
                           key="p25_dl_ladder_v2_far")

# ══════════════════════════════════════════════════════════════════════════════
# 7 · Roll-rule optimizer (moved from page 23 §7)
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("7 · Roll-rule optimizer — find the best X%/Y% roll rule")
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

rrc1, rrc2 = st.columns(2)
with rrc1:
    roll_call_pct = st.number_input("Sold CALL % from anchor", 1.0, 8.0, 3.0, 0.25, key="p25_roll_call_pct")
with rrc2:
    roll_put_pct = st.number_input("Sold PUT % from anchor", 1.0, 8.0, 3.5, 0.25, key="p25_roll_put_pct")
rrc3, rrc4 = st.columns(2)
with rrc3:
    x_range = st.slider("X% grid range (drift trigger)", 0.25, 4.0, (0.5, 2.5), 0.25, key="p25_roll_x_range")
    x_step = st.select_slider("X% step", options=[0.25, 0.5, 1.0], value=0.5, key="p25_roll_x_step")
with rrc4:
    y_range = st.slider("Y% grid range (roll-in size)", 0.1, 3.0, (0.25, 1.5), 0.15, key="p25_roll_y_range")
    y_step = st.select_slider("Y% step", options=[0.1, 0.25, 0.5], value=0.25, key="p25_roll_y_step")

x_grid = tuple(np.round(np.arange(x_range[0], x_range[1] + 1e-9, x_step), 3))
y_grid = tuple(np.round(np.arange(y_range[0], y_range[1] + 1e-9, y_step), 3))
st.caption(f"Grid: X ∈ {list(x_grid)} · Y ∈ {list(y_grid)} → {len(x_grid) * len(y_grid)} combinations.")

if st.button("▶ Run roll-rule scan", key="p25_rr_run"):
    with st.spinner(f"Simulating {len(x_grid) * len(y_grid)} (X, Y) combinations across every weekly cycle…"):
        rr = sl.roll_rule_scan(_load_daily(lookback), x_grid=x_grid, y_grid=y_grid,
                               call_pct=float(roll_call_pct), put_pct=float(roll_put_pct))
    st.session_state.p25_roll_rule = rr

if "p25_roll_rule" in st.session_state:
    rr = st.session_state.p25_roll_rule
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
                           file_name="roll_rule_near.csv", mime="text/csv", key="p25_dl_roll_near")

    st.markdown("**Full grid — biweekly (through next expiry)**")
    if rr["far"].empty:
        st.caption("Not enough Tuesday-anchored cycles in this history.")
    else:
        _frozen(rr["far"], height=min(60 + 28 * len(rr["far"]), 460), reset=False)
        st.download_button("⬇ Download biweekly grid CSV", rr["far"].to_csv(index=False).encode("utf-8"),
                           file_name="roll_rule_far.csv", mime="text/csv", key="p25_dl_roll_far")

# ══════════════════════════════════════════════════════════════════════════════
# 8 · Download everything as one CSV
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("8 · Download everything as one CSV")
st.caption("Bundles every table above that you've run — into ONE file with '## N. TITLE' section "
          "headers. Easiest single thing to hand back for review.")


def _build_combined_csv() -> str:
    parts = []
    if "p25_rt_ran" in st.session_state:
        pass  # roll-threshold scan already has its own download; raw df not stashed in session_state
    dist = st.session_state.get("p25_dist_result")
    if dist is not None:
        for key, label in (("1_week", "1-WEEK"), ("2_week", "2-WEEK (BIWEEKLY)")):
            if not dist[key].empty:
                parts.append(f"## ANCHOR CLOSE-DISTRIBUTION — {label}\n" + dist[key].to_csv(index=False))
    adr = st.session_state.get("p25_adr_result")
    if adr is not None and not adr.empty:
        parts.append("## ANCHOR-DRIFT CONTINUATION-VS-REVERSION SCAN\n" + adr.to_csv(index=False))
    opt = st.session_state.get("p25_opt_result")
    if opt is not None:
        for key, label in (("1_week", "1-WEEK"), ("2_week", "2-WEEK (BIWEEKLY)")):
            bundle = opt.get(key) or {}
            scan_df = bundle.get("scan")
            if scan_df is not None and not scan_df.empty:
                parts.append(f"## ANCHOR-DRIFT OPTIMUM THRESHOLD SCAN — {label}\n"
                             + scan_df.to_csv(index=False))
    rr = st.session_state.get("p25_roll_rule")
    if rr is not None:
        if not rr["near"].empty:
            parts.append("## ROLL-RULE SCAN — NEAR EXPIRY GRID\n" + rr["near"].to_csv(index=False))
        if not rr["far"].empty:
            parts.append("## ROLL-RULE SCAN — BIWEEKLY GRID\n" + rr["far"].to_csv(index=False))
    return "\n\n".join(parts) if parts else "No sections run yet."


st.download_button("⬇ Download everything (combined CSV)", _build_combined_csv().encode("utf-8"),
                   file_name="roll_management_full_export.csv", mime="text/csv", type="primary")
