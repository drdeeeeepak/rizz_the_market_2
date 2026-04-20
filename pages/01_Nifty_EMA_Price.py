# pages/01_Nifty_EMA_Price.py — Page 01: EMA Entry Engine v6
# Cluster Regime · Moat Count · Momentum Score · EMA Lens Distance
# Three independent components — no double counting
import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P01 · EMA Entry Engine", layout="wide")
st_autorefresh(interval=60_000, key="p01")
st.title("Page 01 — EMA Entry Engine")
st.caption("Cluster Regime · ATR Danger Zones · Moat Count · Momentum Score · EMA Lens Distance")

sig = st.session_state.get("signals", {})
if not sig:
    st.info("⬅️ Open **Home** page first — it loads all signals."); st.stop()

atr14     = sig.get("atr14", 200)
spot_est  = sig.get("final_put_short", 0) + sig.get("final_put_dist", 0)
regime    = sig.get("cr_regime", "INSIDE_BULL")
base_mult = sig.get("cr_base_mult", 2.0)

# ── Kill banners ──────────────────────────────────────────────────────────
if sig.get("cr_hard_skip"):
    st.error("🔴 HARD SKIP — INSIDE_BEAR + 0 put moats + Strong Down. All three aligned against put leg. Do not enter.")
if sig.get("flat_block"):
    st.error("🔴 EMA 3/8 FLAT 5+ DAYS — Coiled spring. Stand aside.")
if sig.get("p1_hard_exit"):
    st.error("🔴 CANARY P1 HARD EXIT — Put Safety <50% and EMA3 < EMA8. Review put leg.")

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
    "RECOVERING":     "Spot cleared above fast cluster on a bounce but fast cluster is entirely below slow cluster. Transitional — slow cluster is significant overhead resistance.",
    "INSIDE_BEAR":    "Fast cluster crossed below slow cluster AND spot is between the two clusters. Structure deteriorating — both legs uncertain.",
    "BEAR_COMPRESSED":"Spot below fast cluster AND fast cluster overlapping with slow cluster.",
    "STRONG_BEAR":    "Spot below fast cluster AND fast cluster below slow cluster. Full bearish stack. CE has all EMAs as overhead resistance.",
}

r_col = REGIME_COLOURS.get(regime, "default")
ui.alert_box(regime, REGIME_DESC_LONG.get(regime, ""), level={
    "green":"success","blue":"info","amber":"warning","red":"danger","default":"info"
}.get(r_col,"info"))

c1, c2, c3, c4 = st.columns(4)
with c1: ui.metric_card("CLUSTER REGIME", regime, color=r_col)
with c2: ui.metric_card("BASE ATR MULT", f"{base_mult}×", sub=f"= {int(round(base_mult*atr14/50)*50):,} pts at ATR {atr14:.0f}")
with c3: ui.metric_card("IC SHAPE", sig.get("cr_ic_shape","1:1"), sub="Size guidance")
with c4: ui.metric_card("SIZE GUIDANCE", f"{sig.get('cr_size',0.75):.0%}",
                          color="green" if sig.get("cr_size",0.75) >= 1.0 else "amber")

# EMA level table
st.markdown("")
ema_vals = sig.get("cr_ema_vals", {})
if ema_vals:
    spot_disp = spot_est if spot_est > 0 else 0
    cols = st.columns(7)
    labels = ["EMA8","EMA16","EMA30","EMA60","EMA120","EMA200","Spot"]
    values = [ema_vals.get(8,0), ema_vals.get(16,0), ema_vals.get(30,0),
              ema_vals.get(60,0), ema_vals.get(120,0), ema_vals.get(200,0), spot_disp]
    for i, (lbl, val) in enumerate(zip(labels, values)):
        is_fast = i < 3
        is_spot = i == 6
        colour  = "blue" if is_spot else "green" if is_fast else "default"
        with cols[i]:
            ui.metric_card(lbl, f"{val:,.0f}",
                           sub="Fast" if is_fast else "Slow" if not is_spot else "Current",
                           color=colour)

st.divider()

# ══════════════════════════════════════════════════════════════════════════
# COMPONENT 2 — Moat Count
# ══════════════════════════════════════════════════════════════════════════
ui.section_header("Component 2 — Moat Count",
                  "EMAs between spot and your strike = walls the market must break through · Creates all PE/CE asymmetry")

ui.simple_technical(
    "Each moat is one EMA wall between spot and your short strike. More moats = more protection = you can afford to be tighter. The moat count creates the asymmetry between put and call distances — the cluster regime base is symmetric; moats make it directional.",
    f"Moat set: EMA8, 16, 30, 60, 120, 200\nClustering rule: moats within {50} pts count as ONE\nDegraded rule: EMA8 put-side with negative slope = 0.5 moat (weakening before spot arrives)\nZone: within 3× ATR14 ({int(3*atr14):,} pts) of spot"
)
st.markdown("")

put_moats  = sig.get("cr_put_moats",  2)
call_moats = sig.get("cr_call_moats", 2)
put_label  = sig.get("cr_put_moat_label",  "adequate")
call_label = sig.get("cr_call_moat_label", "adequate")
put_mult   = sig.get("cr_put_moat_mult",   0.25)
call_mult  = sig.get("cr_call_moat_mult",  0.25)

MOAT_COLOUR = {"fortress":"green","strong":"green","adequate":"amber","thin":"red","exposed":"red"}

col1, col2 = st.columns(2)
with col1:
    ui.metric_card("PUT-SIDE MOATS", f"{put_moats:.1f}",
                   sub=f"{put_label.capitalize()} — {'+' if put_mult>=0 else ''}{put_mult:+.2f}× ATR adjustment ({int(round(put_mult*atr14/50)*50):+,} pts)",
                   color=MOAT_COLOUR.get(put_label,"default"))
    detail_p = sig.get("cr_put_moat_detail", [])
    if detail_p:
        st.caption("Moats (EMA → level): " + " | ".join(f"{label}: {val:,.0f}" for label, val in detail_p))

with col2:
    ui.metric_card("CALL-SIDE MOATS", f"{call_moats:.1f}",
                   sub=f"{call_label.capitalize()} — {'+' if call_mult>=0 else ''}{call_mult:+.2f}× ATR adjustment ({int(round(call_mult*atr14/50)*50):+,} pts)",
                   color=MOAT_COLOUR.get(call_label,"default"))
    detail_c = sig.get("cr_call_moat_detail", [])
    if detail_c:
        st.caption("Moats (EMA → level): " + " | ".join(f"{label}: {val:,.0f}" for label, val in detail_c))

# ATR danger zones
weekly_z  = sig.get("cr_weekly_zone",  atr14*2)
biwkly_z  = sig.get("cr_biweekly_zone",atr14*3)
put_dngr  = sig.get("cr_put_danger_emas",  [])
call_dngr = sig.get("cr_call_danger_emas", [])

if put_dngr or call_dngr:
    st.markdown("")
    if put_dngr:
        st.warning(f"⚠️ Put-side EMAs inside weekly zone (±{weekly_z:.0f} pts — WILL be tested): "
                   + ", ".join(f"EMA{p}" for p in put_dngr))
    if call_dngr:
        st.warning(f"⚠️ Call-side EMAs inside weekly zone (±{weekly_z:.0f} pts — WILL be tested): "
                   + ", ".join(f"EMA{p}" for p in call_dngr))

st.divider()

# ══════════════════════════════════════════════════════════════════════════
# COMPONENT 3 — Momentum Score
# ══════════════════════════════════════════════════════════════════════════
ui.section_header("Component 3 — Momentum Score",
                  "Speed and direction of the current move · Adjusts the threatened leg only")

mom_state = sig.get("cr_mom_state",  "FLAT")
mom_score = sig.get("cr_mom_score",  0.0)
mom_pe_m  = sig.get("cr_mom_pe_mult",0.0)
mom_ce_m  = sig.get("cr_mom_ce_mult",0.0)

MOM_COLOUR = {
    "STRONG_UP":"red","MODERATE_UP":"amber","FLAT":"green",
    "MODERATE_DOWN":"amber","STRONG_DOWN":"red","TRANSITIONING":"amber"
}
MOM_DESC = {
    "STRONG_UP":    "Market moving toward CE fast. CE is the threatened leg.",
    "MODERATE_UP":  "Upward drift. CE side under mild pressure.",
    "FLAT":         "No conviction either way. Moats reliable as-is.",
    "MODERATE_DOWN":"Downward drift. PE side under mild pressure.",
    "STRONG_DOWN":  "Market moving toward PE fast. PE is the threatened leg.",
    "TRANSITIONING":"EMA3 and EMA8 disagree. Uncertainty — both sides get +0.25×.",
}

c1,c2,c3,c4 = st.columns(4)
with c1: ui.metric_card("MOMENTUM STATE", mom_state,
                          sub=MOM_DESC.get(mom_state,""),
                          color=MOM_COLOUR.get(mom_state,"default"))
with c2: ui.metric_card("COMBINED SCORE", f"{mom_score:+.1f}%", sub="% of ATR per day")
with c3: ui.metric_card("EMA3 SLOPE", f"{sig.get('cr_mom_ema3_slope',0):+.1f} pts/day", sub="Fast (60% weight)")
with c4: ui.metric_card("EMA8 SLOPE", f"{sig.get('cr_mom_ema8_slope',0):+.1f} pts/day", sub="Smooth (40% weight)")

# Which leg gets the momentum adjustment
st.markdown("")
col1, col2 = st.columns(2)
with col1:
    pe_mom_pts = int(round(mom_pe_m * atr14 / 50) * 50)
    ui.metric_card("PE MOMENTUM ADJ", f"{mom_pe_m:+.2f}× ATR",
                   sub=f"= {pe_mom_pts:+,} pts {'← threatened' if mom_pe_m > 0 else '← safe leg, no addition'}",
                   color="red" if mom_pe_m > 0 else "green")
with col2:
    ce_mom_pts = int(round(mom_ce_m * atr14 / 50) * 50)
    ui.metric_card("CE MOMENTUM ADJ", f"{mom_ce_m:+.2f}× ATR",
                   sub=f"= {ce_mom_pts:+,} pts {'← threatened' if mom_ce_m > 0 else '← safe leg, no addition'}",
                   color="red" if mom_ce_m > 0 else "green")

st.divider()

# ══════════════════════════════════════════════════════════════════════════
# EMA LENS DISTANCE — Final output of this page
# ══════════════════════════════════════════════════════════════════════════
ui.section_header("EMA Lens Distance — This Page's Output",
                  "Base + Moat + Momentum = EMA lens recommendation · Other lenses produce their own · Home page shows all")

pe_total_m = sig.get("cr_pe_total_mult", base_mult)
ce_total_m = sig.get("cr_ce_total_mult", base_mult)
pe_dist    = sig.get("cr_pe_dist_pts",   int(round(pe_total_m * atr14 / 50) * 50))
ce_dist    = sig.get("cr_ce_dist_pts",   int(round(ce_total_m * atr14 / 50) * 50))

# Breakdown rows
def pct_otm(dist, spot):
    return f"{dist/spot*100:.1f}% OTM" if spot > 0 else ""

col1, col2 = st.columns(2)
with col1:
    st.markdown("**PE (Put) Distance — Breakdown**")
    rows_pe = [
        ("1. Regime base",      f"{base_mult}×",    f"{int(round(base_mult*atr14/50)*50):,} pts"),
        ("2. Moat adjustment",  f"{put_mult:+.2f}×", f"{int(round(put_mult*atr14/50)*50):+,} pts  ({put_label})"),
        ("3. Momentum adj",     f"{mom_pe_m:+.2f}×", f"{int(round(mom_pe_m*atr14/50)*50):+,} pts"),
        ("━━ EMA LENS TOTAL",   f"{pe_total_m:.2f}×",f"{pe_dist:,} pts  ({pct_otm(pe_dist, spot_est)})"),
    ]
    for label, mult, pts in rows_pe:
        is_total = "TOTAL" in label
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;font-size:{'13' if is_total else '11'}px;"
            f"font-weight:{'700' if is_total else '400'};color:{'#dc2626' if is_total else '#334155'};"
            f"padding:{'6' if is_total else '3'}px 0;border-{'top' if is_total else 'bottom'}:"
            f"{'2px solid #e2e8f0' if not is_total else '2px solid #dc2626'};'>"
            f"<span>{label}</span><span>{mult} = {pts}</span></div>",
            unsafe_allow_html=True)
    ui.metric_card("PE LENS DISTANCE", f"{pe_dist:,} pts",
                   sub=f"PE short suggestion: ~{int(spot_est - pe_dist):,}" if spot_est > 0 else "",
                   color="green")

with col2:
    st.markdown("**CE (Call) Distance — Breakdown**")
    rows_ce = [
        ("1. Regime base",      f"{base_mult}×",    f"{int(round(base_mult*atr14/50)*50):,} pts"),
        ("2. Moat adjustment",  f"{call_mult:+.2f}×",f"{int(round(call_mult*atr14/50)*50):+,} pts  ({call_label})"),
        ("3. Momentum adj",     f"{mom_ce_m:+.2f}×", f"{int(round(mom_ce_m*atr14/50)*50):+,} pts"),
        ("━━ EMA LENS TOTAL",   f"{ce_total_m:.2f}×",f"{ce_dist:,} pts  ({pct_otm(ce_dist, spot_est)})"),
    ]
    for label, mult, pts in rows_ce:
        is_total = "TOTAL" in label
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;font-size:{'13' if is_total else '11'}px;"
            f"font-weight:{'700' if is_total else '400'};color:{'#dc2626' if is_total else '#334155'};"
            f"padding:{'6' if is_total else '3'}px 0;border-{'top' if is_total else 'bottom'}:"
            f"{'2px solid #e2e8f0' if not is_total else '2px solid #dc2626'};'>"
            f"<span>{label}</span><span>{mult} = {pts}</span></div>",
            unsafe_allow_html=True)
    ui.metric_card("CE LENS DISTANCE", f"{ce_dist:,} pts",
                   sub=f"CE short suggestion: ~{int(spot_est + ce_dist):,}" if spot_est > 0 else "",
                   color="green")

st.caption("This is the EMA lens output only. RSI, Bollinger, VIX, and Market Profile each produce their own independent distance. The Home page shows all lenses side by side. Suggested final strike = most conservative across all lenses.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════
# CANARY — Hold Monitor (from Page 02 context)
# ══════════════════════════════════════════════════════════════════════════
ui.section_header("Canary Signal — Regime Deterioration Early Warning")

canary    = sig.get("canary_level",    0)
can_dir   = sig.get("canary_direction","NONE")
CANARY_LEVEL = {4:"danger",3:"danger",2:"warning",1:"warning",0:"success"}
CANARY_MSG   = {
    4: "FULL CANARY — EMA16 crossed EMA30. Regime has shifted. Consider defensive roll.",
    3: "CANARY DAY 3 — EMA8 crossed EMA16. Structural weakness. Tighten monitoring.",
    2: "CANARY DAY 2 — EMA8 within 30pts of EMA16. Regime weakening.",
    1: "CANARY DAY 1 — EMA3 crossed EMA8. Watch for reversal — no action yet.",
    0: "Canary clear — no deterioration signals.",
}
ui.alert_box(f"Canary Day {canary} ({can_dir})", CANARY_MSG.get(canary,""),
             level=CANARY_LEVEL.get(canary,"info"))
