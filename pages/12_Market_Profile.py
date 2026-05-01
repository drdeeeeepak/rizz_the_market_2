# pages/12_Market_Profile.py — Page 12: Market Profile Engine
# Volume Profile · Nesting · Responsive/Initiative · Day Type · Wed-Tue Cycle · Biweekly Tinge
import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import ui.components as ui

st.set_page_config(page_title="P12 · Market Profile", layout="wide")
st_autorefresh(interval=60_000, key="p12")
st.title("Page 12 — Market Profile Engine")
st.caption("Volume Profile · Nesting · Responsive/Initiative · Day Type · Wed–Tue Cycle · Biweekly Tinge")

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
        from data.live_fetcher import get_nifty_daily_live, get_nifty_spot as _gs
        from analytics.market_profile import MarketProfileEngine
        _df   = get_nifty_daily_live()
        _spot = _gs() or spot
        if not _df.empty and _spot > 0:
            _mp = MarketProfileEngine().signals(
                _df, _spot,
                near_dte=sig.get("near_dte", 7),
                far_dte=sig.get("far_dte",   14),
                net_skew=sig.get("net_skew",  0.0),
                atr14=sig.get("atr14",        200.0),
            )
            sig["mp_nesting"]         = _mp["nesting_state"]
            sig["mp_behaviour"]       = _mp.get("price_behaviour", "NEUTRAL")
            sig["weekly_vah"]         = _mp["weekly_vah"]
            sig["weekly_poc"]         = _mp["weekly_poc"]
            sig["weekly_val"]         = _mp["weekly_val"]
            sig["mp_responsive"]      = _mp["responsive"]
            sig["mp_ce_anchor"]       = _mp["ce_strike_anchor"]
            sig["mp_pe_anchor"]       = _mp["pe_strike_anchor"]
            sig["mp_kills"]           = _mp.get("mp_kills", _mp.get("kill_switches", {}))
            sig["mp_day_type"]        = _mp.get("day_type",     "NORMAL")
            sig["mp_cycle_day"]       = _mp.get("cycle_day",    "")
            sig["mp_cycle_action"]    = _mp.get("cycle_action", "")
            sig["mp_va_ratio"]        = _mp.get("va_ratio",    1.0)
            sig["mp_buffer_pts"]      = _mp.get("buffer_pts",  150)
            sig["mp_dte_factor"]      = _mp.get("dte_factor",  1.0)
            sig["mp_ce_biwkly_dist"]  = _mp.get("ce_biwkly_dist", 400)
            sig["mp_pe_biwkly_dist"]  = _mp.get("pe_biwkly_dist", 400)
            signals_ts = "LIVE"
    except Exception as _e:
        st.caption(f"Live Market Profile unavailable: {_e}")

nesting    = sig.get("mp_nesting",    "BALANCED")
behaviour  = sig.get("mp_behaviour",  "NEUTRAL")
day_type   = sig.get("mp_day_type",   "NORMAL")
cycle_day  = sig.get("mp_cycle_day",  "")
cycle_act  = sig.get("mp_cycle_action","")
wvah       = sig.get("weekly_vah",    0)
wval       = sig.get("weekly_val",    0)
wpoc       = sig.get("weekly_poc",    0)
dvah       = sig.get("daily_vah",     0)
dval       = sig.get("daily_val",     0)
va_ratio   = sig.get("mp_va_ratio",   1.0)
buffer_pts = sig.get("mp_buffer_pts", 150)
dte_factor = sig.get("mp_dte_factor", 1.0)
ce_dist    = sig.get("mp_ce_biwkly_dist", 400)
pe_dist    = sig.get("mp_pe_biwkly_dist", 400)
ce_anchor  = sig.get("mp_ce_anchor",  0)
pe_anchor  = sig.get("mp_pe_anchor",  0)
poc_mig    = sig.get("mp_poc_migration", {})
both_init  = sig.get("mp_initiative_both", False)
spot       = sig.get("final_put_short", 0) + sig.get("final_put_dist", 0)
atr14      = sig.get("atr14", 200)

# ── Critical banners ──────────────────────────────────────────────────────────
if both_init:
    st.error("🔴 INITIATIVE + INITIATIVE — Nesting INITIATIVE and price behaviour INITIATIVE simultaneously. "
             "Strong defensive roll trigger. Check moat count immediately.")
if nesting == "INITIATIVE_UPPER":
    st.warning("⚠️ INITIATIVE_UPPER — Daily VA fully above weekly VAH. CE leg under sustained pressure. "
               "Check CE moat count from Page 02.")
elif nesting == "INITIATIVE_LOWER":
    st.warning("⚠️ INITIATIVE_LOWER — Daily VA fully below weekly VAL. PE leg under sustained pressure. "
               "Check PE moat count from Page 02.")
if day_type == "TREND_DAY":
    st.warning("⚠️ TREND DAY developing — Do NOT make defensive roll decisions intraday. "
               "Wait for EOD close to assess where daily VA formed.")

# Cycle day banner
if cycle_day:
    CYCLE_COLOURS = {
        "Wednesday": "warning", "Thursday": "success", "Friday": "info",
        "Monday": "warning", "Tuesday": "danger", "Weekend": "info"
    }
    ui.alert_box(f"{cycle_day} — Cycle Guide", cycle_act,
                 level=CYCLE_COLOURS.get(cycle_day, "info"))

st.divider()

# ── Headline metrics ──────────────────────────────────────────────────────────
NEST_COLOURS = {
    "BALANCED": "green", "TESTING_UPPER": "amber", "TESTING_LOWER": "amber",
    "INITIATIVE_UPPER": "red", "INITIATIVE_LOWER": "red",
}
BEH_COLOURS = {"RESPONSIVE": "green", "INITIATIVE": "red", "NEUTRAL": "default"}

c1,c2,c3,c4,c5,c6 = st.columns(6)
with c1: ui.metric_card("NESTING", nesting, color=NEST_COLOURS.get(nesting,"default"))
with c2: ui.metric_card("PRICE BEHAVIOUR", behaviour, color=BEH_COLOURS.get(behaviour,"default"))
with c3: ui.metric_card("DAY TYPE", day_type, color="red" if day_type=="TREND_DAY" else "default")
with c4: ui.metric_card("WEEKLY VAH", f"{wvah:,.0f}", sub="CE must be above")
with c5: ui.metric_card("WEEKLY VAL", f"{wval:,.0f}", sub="PE must be below")
with c6: ui.metric_card("WEEKLY POC", f"{wpoc:,.0f}", sub="Max pain magnet")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Volume Profile Visual
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 1 — Volume Profile Key Levels",
                  "Wednesday–Tuesday weekly cycle · 70% Value Area")

col1, col2 = st.columns([1, 2])
with col1:
    st.markdown("**Weekly Value Area**")
    rows = [
        ("VAH (CE anchor)", f"{wvah:,.0f}", "CE short must be above this"),
        ("POC",             f"{wpoc:,.0f}", "Market's centre of gravity"),
        ("VAL (PE anchor)", f"{wval:,.0f}", "PE short must be below this"),
        ("VA Width",        f"{wvah-wval:,.0f} pts", f"VA Ratio: {va_ratio:.2f}×ATR"),
        ("ATR-Buffer",      f"{buffer_pts:,} pts",   f"{sig.get('mp_buf_mult',0.75):.2f}×ATR beyond VA"),
    ]
    for label, val, note in rows:
        ui.metric_card(label, val, sub=note)
        st.markdown("")

with col2:
    if wvah > 0 and wval > 0 and spot > 0:
        # Simple level chart
        fig = go.Figure()
        levels = [
            (wvah + buffer_pts, "CE Biweekly Anchor", "#dc2626", "dash"),
            (wvah,              "Weekly VAH",          "#f97316", "solid"),
            (wpoc,              "Weekly POC",           "#2563eb", "solid"),
            (wval,              "Weekly VAL",           "#16a34a", "solid"),
            (wval - buffer_pts, "PE Biweekly Anchor",  "#15803d", "dash"),
            (spot,              "Current Spot",         "#7c3aed", "solid"),
        ]
        for level, name, colour, dash in levels:
            fig.add_hline(y=level, line_color=colour, line_dash=dash,
                          annotation_text=f"{name}: {level:,.0f}",
                          annotation_position="right")
        # VA shading
        fig.add_hrect(y0=wval, y1=wvah, fillcolor="#dcfce7", opacity=0.3,
                      annotation_text="70% Value Area")
        fig.update_layout(height=300, margin=dict(l=0,r=120,t=20,b=0),
                          yaxis_title="Nifty Level",
                          plot_bgcolor="#f8f9fb", paper_bgcolor="#f8f9fb")
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("VA levels not yet computed — run Home page first.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Biweekly Tinge
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Biweekly Tinge: DTE Expansion + Net Skew",
                  "Nearest expiry anchors → expanded for 7-day hold")

ui.simple_technical(
    "Your IC is not on the nearest expiry. The nearest expiry gives us the sharpest, most live picture of gravitational forces. We then scale it outward for your biweekly hold using time (DTE ratio) and direction (Net Skew). Two boundaries displayed — the more conservative wins.",
    f"DTE Factor = √(far_DTE / near_DTE) = {dte_factor:.3f}\n"
    f"CE biweekly = (VAH + buffer) × DTE factor = {ce_dist:,} pts from spot\n"
    f"PE biweekly = (VAL − buffer) × DTE factor = {pe_dist:,} pts from spot\n"
    f"Net Skew ±30 threshold: ±{round(0.25*atr14/50)*50:,} pts tinge"
)
st.markdown("")

near_dte = sig.get("near_dte", 7)
far_dte  = sig.get("far_dte", 14)

c1,c2,c3,c4,c5 = st.columns(5)
with c1: ui.metric_card("NEAR DTE", f"{near_dte}d", sub="Nearest expiry")
with c2: ui.metric_card("FAR DTE", f"{far_dte}d",   sub="Your biweekly")
with c3: ui.metric_card("DTE FACTOR", f"{dte_factor:.3f}×", sub="√(far/near)")
with c4: ui.metric_card("CE BIWEEKLY DIST", f"{ce_dist:,} pts",
                          sub=f"Anchor: {ce_anchor:,.0f}", color="red")
with c5: ui.metric_card("PE BIWEEKLY DIST", f"{pe_dist:,} pts",
                          sub=f"Anchor: {pe_anchor:,.0f}", color="green")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Nesting and Behaviour
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — Nesting and Price Behaviour",
                  "Nesting: where is daily VA vs weekly VA · Behaviour: how is price acting at boundaries")

NESTING_DESC = {
    "BALANCED":         ("Daily VA fully inside weekly VA. Maximum IC confidence. Natural gravitational containment working.", "success"),
    "TESTING_UPPER":    ("Daily VA overlapping weekly VAH. CE side mild pressure. Monitor for transition to INITIATIVE.", "warning"),
    "TESTING_LOWER":    ("Daily VA overlapping weekly VAL. PE side mild pressure. Monitor for transition to INITIATIVE.", "warning"),
    "INITIATIVE_UPPER": ("Daily VA fully above weekly VAH. Market left weekly value on upside. CE leg under sustained pressure.", "danger"),
    "INITIATIVE_LOWER": ("Daily VA fully below weekly VAL. Market below weekly accepted range. PE leg under sustained pressure.", "danger"),
}
BEHAVIOUR_DESC = {
    "RESPONSIVE": ("Price tested outside VA and returned inside. VA walls are genuine boundaries. Hold with confidence.", "success"),
    "INITIATIVE": ("Price moved outside VA and continued away. Boundary not rejected — it was conquered. Warning.", "danger"),
    "NEUTRAL":    ("Price inside VA. Normal rotation around POC. Standard IC conditions.", "info"),
}

col1, col2 = st.columns(2)
with col1:
    desc, level = NESTING_DESC.get(nesting, ("", "info"))
    ui.alert_box(f"Nesting: {nesting}", desc, level=level)
with col2:
    desc_b, level_b = BEHAVIOUR_DESC.get(behaviour, ("", "info"))
    ui.alert_box(f"Behaviour: {behaviour}", desc_b, level=level_b)

# Nesting reference table
with st.expander("Nesting + Moat Count Combined Action Table", expanded=False):
    rows_n = [
        ["BALANCED",          "Any",        "Hold — both MP and structure supportive"],
        ["TESTING",           "3+ moats",   "Watch — two lenses mild pressure, structure intact"],
        ["TESTING",           "1-2 moats",  "Elevated alert — MP and structure both showing pressure"],
        ["INITIATIVE_UPPER",  "2+ CE moats","Prepare defensive roll — initiative confirmed"],
        ["INITIATIVE_UPPER",  "0-1 CE moats","Execute defensive roll — MP and EMA both broken on CE"],
        ["INITIATIVE_LOWER",  "2+ PE moats","Prepare defensive roll — initiative confirmed"],
        ["INITIATIVE_LOWER",  "0-1 PE moats","Execute defensive roll — MP and EMA both broken on PE"],
        ["Any",               "0 moats + INITIATIVE","EXIT — all protection consumed"],
    ]
    df_n = pd.DataFrame(rows_n, columns=["Nesting","Moat Status","Combined Action"])
    def hl_nesting(val):
        if nesting in str(val): return "background-color:#dbeafe;font-weight:700"
        return ""
    st.dataframe(df_n.style.map(hl_nesting, subset=["Nesting"]), width="stretch", hide_index=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Day Type
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 4 — Day Type Classification",
                  "Based on Initial Balance and session structure")

DAY_TYPE_DESC = {
    "NORMAL":             ("Balanced two-sided activity. IC-friendly. No special action.", "info"),
    "TREND_DAY":          ("Narrow IB, strong directional close. Most dangerous for IC. Wait for EOD — no intraday rolls.", "danger"),
    "DOUBLE_DISTRIBUTION":("Two distinct VAs in one session. Range shift signal. Watch which distribution holds into close.", "warning"),
    "P_SHAPE":            ("Strong early rally then rotates lower. CE pressure reducing. Fading the rally — hold with confidence.", "info"),
    "b_SHAPE":            ("Strong early drop then rotates higher. PE pressure reducing. Fading the drop — hold with confidence.", "info"),
    "NEUTRAL_EXTREME":    ("Large range, closes near middle. Failed breakout. VA walls just proved their strength.", "success"),
}
dt_desc, dt_level = DAY_TYPE_DESC.get(day_type, ("Normal session", "info"))
ui.alert_box(f"Day Type: {day_type}", dt_desc, level=dt_level)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — POC Migration
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 5 — POC Migration During Hold",
                  "Has the market's centre of gravity shifted since entry?")

poc_dist   = poc_mig.get("distance", 0)
poc_label  = poc_mig.get("label",  "STABLE")
poc_action = poc_mig.get("action", "No action")

POC_COLOURS = {"STABLE": "green", "MILD_UPWARD": "amber", "MILD_DOWNWARD": "amber",
               "STRONG_UPWARD": "red", "STRONG_DOWNWARD": "red"}

c1, c2, c3 = st.columns(3)
with c1: ui.metric_card("POC MIGRATION", f"{poc_dist:,.0f} pts",
                          sub=poc_label, color=POC_COLOURS.get(poc_label,"default"))
with c2: ui.metric_card("WEEKLY POC", f"{wpoc:,.0f}", sub="Weekly centre of gravity")
with c3: ui.metric_card("ACTION", poc_action[:40], sub="Based on migration distance")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Wed–Tue Cycle Guide
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 6 — Wednesday to Tuesday Cycle Guide",
                  "DTE-specific actions for each day of your IC's life")

CYCLE_DATA = [
    ("Wednesday", "-7 DTE", "OBSERVE ONLY",  "Never enter. Use last completed cycle VA as reference only. Re-validate all engines Thursday morning."),
    ("Thursday",  "-6 DTE", "PRIME ENTRY ★", "Primary entry day. Enter before 11 AM. BALANCED nesting + RESPONSIVE = full confidence. Dual boundary MAX wins."),
    ("Friday",    "-5 DTE", "FOLLOW BIAS",   "No new entries. Follow Thursday's directional bias. Friday EOD important — weekend gap risk."),
    ("Monday",    "-2 DTE", "GAP CHECK",     "Re-run all engines at 9:15 AM. Gap inside VA = hold. Gap outside + INITIATIVE = assess immediately before 11 AM."),
    ("Tuesday",   "EXPIRY", "CLOSE / ROLL",  "No new positions. Close profitable legs by 12 PM. If either strike within 200 pts at 12 PM — exit entire position."),
]
for day, dte, action, desc in CYCLE_DATA:
    is_today = day == cycle_day
    level = "success" if is_today and "PRIME" in action else "warning" if is_today else "info"
    prefix = "📍 TODAY — " if is_today else ""
    ui.alert_box(f"{prefix}{day} ({dte}) — {action}", desc, level=level if is_today else "info")
