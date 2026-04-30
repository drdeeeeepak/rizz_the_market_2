# pages/01_Nifty_EMA_Price.py — v7 (22 April 2026)
# EMA Entry Engine
# Cluster Regime · Moat Count · Momentum Score · EMA Lens Distance
#
# LOCKED CHANGES:
#   - Canary section REMOVED entirely (belongs on Page 02 only)
#   - Auto-compute fallback — no forced Home redirect
#   - Moat and momentum display updated to show FIXED POINTS (not ATR multiples)
#   - Page ends cleanly after EMA Lens Distance output

import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P01 · EMA Entry Engine", layout="wide")
st_autorefresh(interval=60_000, key="p01")
st.title("Page 01 — EMA Entry Engine")
st.caption("Cluster Regime · ATR Danger Zones · Moat Count · Momentum Score · EMA Lens Distance")

from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)
if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

import datetime, pytz
def _is_live():
    n = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
    t = n.hour * 60 + n.minute
    return n.weekday() < 5 and 9*60+15 <= t <= 15*60+30

if _is_live():
    try:
        from data.live_fetcher import get_nifty_daily_live
        from analytics.ema import EMAEngine
        _df = get_nifty_daily_live()
        if not _df.empty:
            sig = {**sig, **EMAEngine().signals(_df)}
            signals_ts = "LIVE"
    except Exception as _e:
        st.caption(f"Live EMA unavailable: {_e}")

atr14     = sig.get("atr14", 200)
spot_est  = spot
regime    = sig.get("cr_regime", "INSIDE_BULL")
base_mult = sig.get("cr_base_mult", 1.5)
base_pts  = sig.get("cr_base_pts",  int(round(base_mult * atr14 / 50) * 50))

# ── Kill banners ──────────────────────────────────────────────────────────
if sig.get("cr_hard_skip"):
    st.error("🔴 HARD SKIP — INSIDE_BEAR + 0 put moats + Strong Down. All three aligned against put leg. Do not enter.")
if sig.get("flat_block"):
    st.error("🔴 EMA 3/8 FLAT 5+ DAYS — Coiled spring. Stand aside.")
if sig.get("p1_hard_exit"):
    st.error("🔴 EMA HARD EXIT — Put Safety <50% and EMA3 < EMA8. Review put leg.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════
# COMPONENT 1 — Cluster Regime
# ══════════════════════════════════════════════════════════════════════════
ui.section_header("Component 1 — Cluster Regime",
                  "Where is spot relative to fast (8,16,30) and slow (60,120,200) EMA clusters?")

REGIME_COLOURS = {
    "STRONG_BULL":    "green",  "BULL_COMPRESSED":  "green",
    "INSIDE_BULL":    "blue",   "RECOVERING":       "amber",
    "INSIDE_BEAR":    "amber",  "BEAR_COMPRESSED":  "red",
    "STRONG_BEAR":    "red",
}
REGIME_DESC_LONG = {
    "STRONG_BULL":    "Spot above fast cluster AND fast above slow cluster. Full bullish stack.",
    "BULL_COMPRESSED":"Spot above fast cluster AND fast cluster penetrating slow cluster.",
    "INSIDE_BULL":    "Fast cluster above slow cluster AND spot has pulled back inside fast cluster.",
    "RECOVERING":     "Spot cleared above fast cluster on a bounce but fast cluster is entirely below slow cluster. Slow cluster is significant overhead resistance.",
    "INSIDE_BEAR":    "Fast cluster crossed below slow cluster AND spot is between the two clusters. Structure deteriorating.",
    "BEAR_COMPRESSED":"Spot below fast cluster AND fast cluster penetrating slow cluster from below.",
    "STRONG_BEAR":    "Spot below fast cluster AND fast cluster below slow cluster. Full bearish stack.",
}
REGIME_IC = {
    "STRONG_BULL":    ("1:2 — CE further",  "Full size",   "Strong PE floor. CE needs room."),
    "BULL_COMPRESSED":("1:2 — CE further",  "75% size",    "Fast cluster compressing. CE caution."),
    "INSIDE_BULL":    ("1:1 — Symmetric",   "75% size",    "Pullback in uptrend. Both sides equal."),
    "RECOVERING":     ("1:1 — Symmetric",   "75% size",    "Bounced above fast — slow cluster overhead."),
    "INSIDE_BEAR":    ("1:1 — Symmetric",   "50% size",    "Deteriorating. Both legs uncertain."),
    "BEAR_COMPRESSED":("2:1 — PE further",  "75% size",    "Downside pressure. PE needs room."),
    "STRONG_BEAR":    ("2:1 — PE further",  "62.5% size",  "Full bear stack. PE fully exposed."),
}

ic_shape, ic_size, ic_note = REGIME_IC.get(regime, ("1:1","Full size","—"))
regime_col = REGIME_COLOURS.get(regime, "default")

c1,c2,c3,c4,c5 = st.columns(5)
with c1: ui.metric_card("REGIME",    regime,   color=regime_col)
with c2: ui.metric_card("BASE MULT", f"{base_mult}×", sub=f"= {base_pts:,} pts")
with c3: ui.metric_card("IC SHAPE",  ic_shape, sub=ic_note)
with c4: ui.metric_card("SIZE GUIDE",ic_size)
with c5: ui.metric_card("ATR14",     f"{atr14:.0f} pts", sub="Daily ATR14")

ui.simple_technical(
    REGIME_DESC_LONG.get(regime, "—"),
    f"Fast cluster: EMA8, EMA16, EMA30\n"
    f"Slow cluster: EMA60, EMA120, EMA200\n"
    f"Base = {base_mult}× ATR14 = {base_pts:,} pts\n"
    f"Same base both PE and CE — moat count creates asymmetry"
)

ema_v = sig.get("cr_ema_vals", {})
if ema_v:
    st.markdown("**EMA Levels**")
    cols_e = st.columns(6)
    for i, p in enumerate([8, 16, 30, 60, 120, 200]):
        v = ema_v.get(p, 0)
        diff = round(float(spot_est - v), 0) if spot_est > 0 and v > 0 else 0
        side = "below" if diff > 0 else "above"
        with cols_e[i]:
            ui.metric_card(f"EMA{p}", f"{v:,.0f}",
                           sub=f"{abs(diff):,.0f} pts {side} spot" if diff != 0 else "at spot",
                           color="green" if v < spot_est else "red" if v > spot_est else "default")

st.divider()

# ══════════════════════════════════════════════════════════════════════════
# COMPONENT 2 — Moat Count
# ══════════════════════════════════════════════════════════════════════════
ui.section_header("Component 2 — Moat Count",
                  "EMA walls between spot and short strikes · Fixed point adjustment per moat label")

put_moats  = sig.get("cr_put_moats",      2.0)
call_moats = sig.get("cr_call_moats",     2.0)
put_label  = sig.get("cr_put_moat_label", "adequate")
call_label = sig.get("cr_call_moat_label","adequate")
put_pts    = sig.get("cr_put_moat_pts",   100)
call_pts   = sig.get("cr_call_moat_pts",  100)

MOAT_COLOUR = {
    "fortress": "green", "strong": "green",
    "adequate": "amber", "thin": "red", "exposed": "red"
}

col1, col2 = st.columns(2)
with col1:
    ui.metric_card("PUT MOATS (PE side)", f"{put_moats:.1f}",
                   sub=f"{put_label.capitalize()} → {put_pts:+,} pts",
                   color=MOAT_COLOUR.get(put_label, "default"))
    detail_p = sig.get("cr_put_moat_detail", [])
    if detail_p:
        for lbl, val in detail_p:
            st.caption(f"  {lbl}: {val:,.0f}")

with col2:
    ui.metric_card("CALL MOATS (CE side)", f"{call_moats:.1f}",
                   sub=f"{call_label.capitalize()} → {call_pts:+,} pts",
                   color=MOAT_COLOUR.get(call_label, "default"))
    detail_c = sig.get("cr_call_moat_detail", [])
    if detail_c:
        for lbl, val in detail_c:
            st.caption(f"  {lbl}: {val:,.0f}")

import pandas as pd
moat_ref = pd.DataFrame([
    ["5–6", "Fortress", "−100 pts", "Rare. Multi-wall cluster. Very strong protection."],
    ["3–4", "Strong",   "+0 pts",   "Standard protection. Base distance stands."],
    ["2",   "Adequate", "+100 pts", "Decent but one session can consume a moat."],
    ["1",   "Thin",     "+200 pts", "Only one wall. Genuine exposure."],
    ["0",   "Exposed",  "+350 pts", "No EMA protection at all on this side."],
], columns=["Moat Count", "Label", "Adjustment", "Reasoning"])
with st.expander("Moat adjustment reference", expanded=False):
    st.dataframe(moat_ref, use_container_width=True, hide_index=True)
    st.caption("Clustering rule: moats within 50 pts of each other = ONE moat. "
               "Degraded rule: EMA8 put-side moat with negative slope = 0.5 moat.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════
# COMPONENT 3 — Momentum Score
# ══════════════════════════════════════════════════════════════════════════
ui.section_header("Component 3 — Momentum Score",
                  "Speed and direction of current price trend · Threatened leg only · Fixed points")

mom_state  = sig.get("cr_mom_state",    "FLAT")
mom_score  = sig.get("cr_mom_score",    0.0)
mom_pe_pts = sig.get("cr_mom_pe_pts",   0)
mom_ce_pts = sig.get("cr_mom_ce_pts",   0)

MOM_COLOUR = {
    "STRONG_UP":    "red",   "MODERATE_UP":    "amber",
    "FLAT":         "green", "MODERATE_DOWN":  "amber",
    "STRONG_DOWN":  "red",   "TRANSITIONING":  "amber",
}
MOM_DESC = {
    "STRONG_UP":    "Market moving toward CE fast. CE is the threatened leg.",
    "MODERATE_UP":  "Upward drift. CE side under mild pressure.",
    "FLAT":         "No conviction either way. Moats reliable as-is.",
    "MODERATE_DOWN":"Downward drift. PE side under mild pressure.",
    "STRONG_DOWN":  "Market moving toward PE fast. PE is the threatened leg.",
    "TRANSITIONING":"EMA3 and EMA8 disagree. Uncertainty — both sides get +75 pts.",
}

c1,c2,c3,c4 = st.columns(4)
with c1: ui.metric_card("MOMENTUM STATE", mom_state,
                          sub=MOM_DESC.get(mom_state, ""),
                          color=MOM_COLOUR.get(mom_state, "default"))
with c2: ui.metric_card("COMBINED SCORE", f"{mom_score:+.1f}%", sub="% of ATR per day")
with c3: ui.metric_card("EMA3 SLOPE", f"{sig.get('cr_mom_ema3_slope',0):+.1f} pts/day", sub="Fast (60% weight)")
with c4: ui.metric_card("EMA8 SLOPE", f"{sig.get('cr_mom_ema8_slope',0):+.1f} pts/day", sub="Smooth (40% weight)")

st.markdown("")
col1, col2 = st.columns(2)
with col1:
    ui.metric_card("PE MOMENTUM ADJ", f"{mom_pe_pts:+,} pts",
                   sub="← threatened" if mom_pe_pts > 0 else "← safe leg, +0",
                   color="red" if mom_pe_pts > 0 else "green")
with col2:
    ui.metric_card("CE MOMENTUM ADJ", f"{mom_ce_pts:+,} pts",
                   sub="← threatened" if mom_ce_pts > 0 else "← safe leg, +0",
                   color="red" if mom_ce_pts > 0 else "green")

st.divider()

# ══════════════════════════════════════════════════════════════════════════
# SECTION 4 — EMA Lens Distance Total
# ══════════════════════════════════════════════════════════════════════════
ui.section_header("EMA Lens Distance — This Page's Output",
                  "Base pts + Moat pts + Momentum pts = EMA lens · Capped at 3.0× ATR14 · Other lenses produce their own")

pe_dist = sig.get("cr_pe_dist_pts", int(round(base_mult * atr14 / 50) * 50))
ce_dist = sig.get("cr_ce_dist_pts", int(round(base_mult * atr14 / 50) * 50))
cap_applied_pe = sig.get("cr_cap_applied_pe", False)
cap_applied_ce = sig.get("cr_cap_applied_ce", False)

def pct_otm(dist, spot):
    return f"{dist/spot*100:.1f}% OTM" if spot > 0 else ""

col1, col2 = st.columns(2)
with col1:
    st.markdown("**PE (Put) Distance — Breakdown**")
    rows_pe = [
        ("1. Regime base",    f"{base_mult}× ATR", f"{base_pts:,} pts"),
        ("2. Moat adj",       f"{put_label.capitalize()}", f"{put_pts:+,} pts"),
        ("3. Momentum adj",   f"{mom_state}", f"{mom_pe_pts:+,} pts"),
        ("━━ EMA LENS TOTAL", f"{'⚠️ Cap applied' if cap_applied_pe else ''}", f"{pe_dist:,} pts  ({pct_otm(pe_dist, spot_est)})"),
    ]
    for label, detail, pts in rows_pe:
        is_total = "TOTAL" in label
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;font-size:{'13' if is_total else '11'}px;"
            f"font-weight:{'700' if is_total else '400'};color:{'#dc2626' if is_total else '#334155'};"
            f"padding:{'6' if is_total else '3'}px 0;border-bottom:1px solid #e2e8f0;'>"
            f"<span>{label} <span style='color:#94a3b8;font-size:10px;'>{detail}</span></span>"
            f"<span>{pts}</span></div>",
            unsafe_allow_html=True)
    ui.metric_card("PE LENS DISTANCE", f"{pe_dist:,} pts",
                   sub=f"PE short ~{int(spot_est - pe_dist):,}" if spot_est > 0 else "",
                   color="green")

with col2:
    st.markdown("**CE (Call) Distance — Breakdown**")
    rows_ce = [
        ("1. Regime base",    f"{base_mult}× ATR", f"{base_pts:,} pts"),
        ("2. Moat adj",       f"{call_label.capitalize()}", f"{call_pts:+,} pts"),
        ("3. Momentum adj",   f"{mom_state}", f"{mom_ce_pts:+,} pts"),
        ("━━ EMA LENS TOTAL", f"{'⚠️ Cap applied' if cap_applied_ce else ''}", f"{ce_dist:,} pts  ({pct_otm(ce_dist, spot_est)})"),
    ]
    for label, detail, pts in rows_ce:
        is_total = "TOTAL" in label
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;font-size:{'13' if is_total else '11'}px;"
            f"font-weight:{'700' if is_total else '400'};color:{'#dc2626' if is_total else '#334155'};"
            f"padding:{'6' if is_total else '3'}px 0;border-bottom:1px solid #e2e8f0;'>"
            f"<span>{label} <span style='color:#94a3b8;font-size:10px;'>{detail}</span></span>"
            f"<span>{pts}</span></div>",
            unsafe_allow_html=True)
    ui.metric_card("CE LENS DISTANCE", f"{ce_dist:,} pts",
                   sub=f"CE short ~{int(spot_est + ce_dist):,}" if spot_est > 0 else "",
                   color="green")

st.caption(
    "This is the EMA lens output only. RSI, Bollinger, VIX, and Market Profile each produce "
    "their own independent distance. The Home page shows all lenses side by side. "
    "Suggested final strike = most conservative across all lenses. "
    "Hard cap: 3.0× ATR14 per side — EMA lens never exceeds this."
)

# PAGE ENDS HERE — canary section removed (belongs on Page 02 only)
