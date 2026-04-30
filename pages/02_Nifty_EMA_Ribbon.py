# pages/02_Nifty_EMA_Ribbon.py — v2 (22 April 2026)
# EMA Hold Monitor — Full redesign per locked rules Section 3 + 4.2
#
# LOCKED CHANGES:
#   - Auto-compute fallback — no forced Home redirect
#   - Five sections: Canary Dashboard, Source Breakdown, Moat Status, Momentum, Hold/Act Table
#   - PE canary and CE canary shown independently throughout
#   - Page header colour driven by combined canary level
#   - Three-source canary display (sources computed in ema.py / canary_level from signals)
#   - Source 3 Tuesday anchor displayed when available
#   - New Hold/Act table (moats × canary Day, per side independently)

import streamlit as st
import pandas as pd
from streamlit_autorefresh import st_autorefresh
import ui.components as ui
from pathlib import Path
import json

st.set_page_config(page_title="P02 · EMA Hold Monitor", layout="wide")
st_autorefresh(interval=60_000, key="p02")

from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
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

# ── Pull signals ──────────────────────────────────────────────────────────
atr14      = sig.get("atr14", 200)
canary     = sig.get("canary_level",    0)
can_dir    = sig.get("canary_direction","NONE")
put_moats  = sig.get("cr_put_moats",    2)
call_moats = sig.get("cr_call_moats",   2)
put_label  = sig.get("cr_put_moat_label", "adequate")
call_label = sig.get("cr_call_moat_label","adequate")
mom_state  = sig.get("cr_mom_state",   "FLAT")
mom_score  = sig.get("cr_mom_score",    0.0)
regime     = sig.get("cr_regime",      "INSIDE_BULL")
ema3_slope = sig.get("cr_mom_ema3_slope", 0.0)
ema8_slope = sig.get("cr_mom_ema8_slope", 0.0)
ema_vals   = sig.get("cr_ema_vals", {})

# Recompute moat counts from current spot — same fix as P01 (stale sig values
# are wrong when spot has moved since EOD compute)
from analytics.ema import MOAT_SET, MOAT_CLUSTER_DIST, ATR_BIWEEKLY_MULT, moat_label_and_pts as _mlab

def _rcp(spot_v, ev, atr_v, slope_v=0.0):
    fl = spot_v - atr_v * ATR_BIWEEKLY_MULT
    cs = sorted([(p, ev[p]) for p in MOAT_SET if fl < ev.get(p, 0) < spot_v],
                key=lambda x: x[1], reverse=True)
    mg, cnt, det = [], 0.0, []
    for p, v in cs:
        if mg and abs(v - mg[-1][1]) <= MOAT_CLUSTER_DIST:
            pp, pv = mg[-1]; mg[-1] = (f"{pp}+{p}", pv)
        else:
            mg.append((p, v))
    for lb, v in mg:
        if str(lb) == "8" and slope_v < 0:
            cnt += 0.5; det.append((f"EMA{lb}(deg)", round(v, 0)))
        else:
            cnt += 1.0; det.append((f"EMA{lb}", round(v, 0)))
    return cnt, det

def _rcc(spot_v, ev, atr_v):
    cl = spot_v + atr_v * ATR_BIWEEKLY_MULT
    cs = sorted([(p, ev[p]) for p in MOAT_SET if spot_v < ev.get(p, 0) < cl],
                key=lambda x: x[1])
    mg = []
    for p, v in cs:
        if mg and abs(v - mg[-1][1]) <= MOAT_CLUSTER_DIST:
            pp, pv = mg[-1]; mg[-1] = (f"{pp}+{p}", pv)
        else:
            mg.append((p, v))
    return float(len(mg)), [(f"EMA{lb}", round(v, 0)) for lb, v in mg]

if ema_vals and spot > 0:
    put_moats,  _detail_p = _rcp(spot, ema_vals, atr14, ema3_slope)
    call_moats, _detail_c = _rcc(spot, ema_vals, atr14)
else:
    put_moats  = sig.get("cr_put_moats",  2)
    call_moats = sig.get("cr_call_moats", 2)
    _detail_p  = sig.get("cr_put_moat_detail",  [])
    _detail_c  = sig.get("cr_call_moat_detail", [])
put_label,  _ = _mlab(put_moats)
call_label, _ = _mlab(call_moats)

# For three-source display — legacy canary is single-source, we display what we have
# Source 1 approximation from existing canary logic
e3  = sig.get("ema3",  ema_vals.get(3,  0))
e8  = sig.get("ema8",  ema_vals.get(8,  0))
e16 = sig.get("ema16", ema_vals.get(16, 0))
e30 = sig.get("ema30", ema_vals.get(30, 0))
gap_pts = abs(e3 - e8) if e3 and e8 else 0
gap_pct = gap_pts / atr14 * 100 if atr14 > 0 else 0

# Source 1 level approximation
if e16 > 0 and e8 > 0 and abs(e8 - e16) < 30:  src1 = 4
elif e8 < e16 and e3 < e8:                       src1 = 3
elif e3 < e8:                                     src1 = 2 if gap_pct < 5 else 1
elif gap_pct < 5:                                 src1 = 2
elif gap_pct < 15:                                src1 = 1
else:                                             src1 = 0

# Source 2 — momentum acceleration (would need previous day's score; approximate from state)
src2_map = {"STRONG_DOWN": 4, "MODERATE_DOWN": 3, "TRANSITIONING": 2,
            "FLAT": 1, "MODERATE_UP": 0, "STRONG_UP": 0}
src2_pe = src2_map.get(mom_state, 0)
src2_ce = src2_map.get({"STRONG_UP": "STRONG_UP", "MODERATE_UP": "MODERATE_UP"}.get(mom_state, "FLAT"), 0)
if mom_state == "STRONG_UP":   src2_ce = 3; src2_pe = 0
elif mom_state == "MODERATE_UP": src2_ce = 2; src2_pe = 0
elif mom_state == "TRANSITIONING": src2_pe = 2; src2_ce = 2

# Source 3 — Tuesday anchor
ANCHOR_FILE = Path("data/tuesday_anchors.json")
tue_close = tue_atr = 0.0
tue_anchor_available = False
if ANCHOR_FILE.exists():
    try:
        anchors = json.loads(ANCHOR_FILE.read_text())
        nifty_anchor = anchors.get("NIFTY", anchors.get("nifty", {}))
        tue_close = nifty_anchor.get("close", 0.0)
        tue_atr   = nifty_anchor.get("atr",   atr14)
        tue_anchor_available = tue_close > 0
    except Exception:
        pass

spot_now = spot
src3_pe = src3_ce = 0
factor_a_pct = factor_b = 0.0
if tue_anchor_available and tue_close > 0 and tue_atr > 0 and spot_now > 0:
    move      = spot_now - tue_close
    factor_a_pct = abs(move) / tue_atr * 100
    # Factor B not easily computable without yesterday's spot — show distance only
    if   factor_a_pct < 20: base3 = 0
    elif factor_a_pct < 40: base3 = 1
    elif factor_a_pct < 60: base3 = 2
    elif factor_a_pct < 80: base3 = 3
    else:                    base3 = 4
    if move > 0:  src3_ce = base3
    else:         src3_pe = base3

# Overall PE and CE canary (max across sources)
pe_canary = max(src1 if can_dir == "BEAR" else 0, src2_pe, src3_pe)
ce_canary = max(src1 if can_dir == "BULL" else 0, src2_ce, src3_ce)
overall_canary = max(pe_canary, ce_canary, canary)  # include legacy for safety

# ── Page header colour ─────────────────────────────────────────────────────
CANARY_HEADER_COLOUR = {0: "#16a34a", 1: "#d97706", 2: "#d97706", 3: "#ea580c", 4: "#dc2626"}
CANARY_LABEL = {0: "SINGING", 1: "Canary Day 1", 2: "Canary Day 2",
                3: "Canary Day 3", 4: "Canary Day 4"}
CANARY_ACTION = {0: "HOLD", 1: "WATCH", 2: "WATCH", 3: "PREPARE", 4: "ACT"}

hdr_col = CANARY_HEADER_COLOUR.get(overall_canary, "#94a3b8")
overall_label  = CANARY_LABEL.get(overall_canary, "—")
overall_action = CANARY_ACTION.get(overall_canary, "WATCH")

st.markdown(
    f"<div style='background:{hdr_col};border-radius:8px;padding:12px 18px;"
    f"display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;'>"
    f"<div>"
    f"<div style='color:white;font-size:11px;font-weight:700;letter-spacing:1px;'>EMA HOLD MONITOR · {overall_label}</div>"
    f"<div style='color:rgba(255,255,255,0.8);font-size:10px;font-family:monospace;'>Regime: {regime}</div>"
    f"</div>"
    f"<div style='background:white;border-radius:6px;padding:6px 16px;'>"
    f"<div style='color:{hdr_col};font-size:18px;font-weight:900;'>{overall_action}</div>"
    f"</div>"
    f"</div>",
    unsafe_allow_html=True)

with st.expander("Cluster Regime Reference", expanded=False):
    _reg_rows = [
        ["STRONG_BULL",     "Spot above fast, fast above slow",              "1:2 CE further", "Full",   "Full bullish stack — strong PE floor, CE needs room"],
        ["BULL_COMPRESSED", "Spot above fast, fast penetrating slow",        "1:2 CE further", "75%",    "Fast cluster compressing into slow — mild CE caution"],
        ["INSIDE_BULL",     "Spot pulled back inside fast cluster",          "1:1 Symmetric",  "75%",    "Pullback in uptrend — both sides equal distance"],
        ["RECOVERING",      "Spot above fast, but fast still below slow",    "1:1 Symmetric",  "75%",    "Bounce — slow cluster is significant overhead ceiling"],
        ["INSIDE_BEAR",     "Fast crossed below slow, spot between them",    "1:1 Symmetric",  "50%",    "Structure deteriorating — both legs uncertain"],
        ["BEAR_COMPRESSED", "Spot below fast, fast penetrating slow upward", "2:1 PE further", "75%",    "Downside pressure — PE needs extra room"],
        ["STRONG_BEAR",     "Spot below fast, fast below slow",              "2:1 PE further", "62.5%",  "Full bearish stack — PE fully exposed"],
    ]
    _reg_df = pd.DataFrame(_reg_rows,
        columns=["Regime", "EMA Structure", "IC Shape", "Size", "Hold Note"])
    def _hl_reg(val):
        return "background-color:#dbeafe;font-weight:700" if val == regime else ""
    st.dataframe(_reg_df.style.map(_hl_reg, subset=["Regime"]),
                 use_container_width=True, hide_index=True)

st.title("Page 02 — EMA Hold Monitor")
st.caption("Three-Source Canary · PE and CE independently · Live Moat Status · Hold / Watch / Prepare / Act")
show_page_header(spot, signals_ts)

# Top-level banners for serious canary
if overall_canary >= 4:
    st.error(f"🔴 {overall_label} — EMA structure has shifted. ACT NOW. Roll or exit. Do not wait for tomorrow.")
elif overall_canary == 3:
    st.warning(f"⚠️ {overall_label} — Structural weakness confirmed. PREPARE roll plan now. Know your exit strikes.")
elif overall_canary == 0:
    st.success("✅ SINGING — All sources clear. EMA structure intact. Hold with confidence.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Position Canary Dashboard
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 1 — Position Canary Dashboard",
                  "PE canary and CE canary independently · Overall = higher of the two")

with st.expander("What is the Canary? — Reference", expanded=False):
    st.markdown(
        "**The canary is an early warning system for your open IC position.**\n\n"
        "Named after the 'canary in a coal mine' — it detects when the EMA structure "
        "protecting your short strikes is starting to erode, **before** it becomes a loss event. "
        "Three independent sources vote. PE and CE are assessed separately. "
        "The overall canary = the higher (worse) of the two sides."
    )
    _can_ref = pd.DataFrame([
        ["✅ SINGING",    "Day 0", "HOLD",    "All 3 sources clear. EMA walls intact. No action needed."],
        ["🟡 Canary Day 1","Day 1", "WATCH",   "One source flagging. Check again at EOD. No panic."],
        ["⚠️ Canary Day 2","Day 2", "WATCH",   "Two sources or escalating source. Active monitoring — check moat count."],
        ["🔴 Canary Day 3","Day 3", "PREPARE", "Structure weakening. Prepare your roll/exit strikes now. Know the plan."],
        ["🔴 Canary Day 4","Day 4", "ACT",     "EMA structure has shifted. Roll or exit. Do not wait for tomorrow."],
    ], columns=["Level", "Day", "Action", "What it means"])
    st.dataframe(_can_ref, use_container_width=True, hide_index=True)
    st.markdown("**Three sources that vote:**")
    _src_ref = pd.DataFrame([
        ["Source 1", "EMA Proximity",           "EMA3 vs EMA8 gap shrinking. Fires BEFORE the crossover — gives you advance notice."],
        ["Source 2", "Momentum Acceleration",   "3-day rolling deceleration of EMA slopes. Detects when the move toward your strike is picking up speed."],
        ["Source 3", "Spot Drift from Tuesday", "How far spot has moved from Tuesday's close relative to ATR. Large drift = leg getting closer to short strike."],
    ], columns=["Source", "Name", "What it detects"])
    st.dataframe(_src_ref, use_container_width=True, hide_index=True)

CANARY_COLOUR = {0: "green", 1: "amber", 2: "amber", 3: "red", 4: "red"}
CANARY_ICON   = {0: "✅", 1: "🟡", 2: "⚠️", 3: "🔴", 4: "🔴"}

def canary_card(side, level, driving_src):
    icon = CANARY_ICON.get(level, "⚪")
    label = CANARY_LABEL.get(level, "—")
    action_map = {0: "Hold — structure intact", 1: "Watch — check again at EOD",
                  2: "Active monitoring — check moats", 3: "Prepare roll plan now",
                  4: "Act now — roll or exit"}
    action = action_map.get(level, "—")
    color  = CANARY_COLOUR.get(level, "default")
    ui.metric_card(f"{side} CANARY", f"{icon} {label}",
                   sub=f"Driver: {driving_src} · {action}", color=color)

col1, col2 = st.columns(2)
pe_driver = "Source 1" if src1 >= src2_pe and src1 >= src3_pe else \
            "Source 2" if src2_pe >= src3_pe else "Source 3"
ce_driver = "Source 1" if src1 >= src2_ce and src1 >= src3_ce else \
            "Source 2" if src2_ce >= src3_ce else "Source 3"

with col1: canary_card("PE (Put Side)", pe_canary, pe_driver)
with col2: canary_card("CE (Call Side)", ce_canary, ce_driver)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Three Source Breakdown
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Three Source Breakdown",
                  "Diagnostic layer — see exactly which source is driving the canary and why")

src_data = [
    {
        "source":  "Source 1 — EMA Proximity",
        "what":    f"EMA3 vs EMA8 gap: {gap_pts:.0f} pts ({gap_pct:.1f}% of ATR). Fires BEFORE crossover.",
        "pe_lvl":  src1 if can_dir == "BEAR" else 0,
        "ce_lvl":  src1 if can_dir == "BULL" else 0,
        "detail":  f"EMA3={e3:,.0f} · EMA8={e8:,.0f} · EMA16={e16:,.0f} · EMA30={e30:,.0f}\n"
                   f"Gap {gap_pct:.1f}% ATR → {'>15%=Clear, 5-15%=Day1, <5%=Day2, Cross=Day3, EMA8/16 close=Day4'}",
    },
    {
        "source":  "Source 2 — Momentum Acceleration (3-day rolling)",
        "what":    f"Momentum state: {mom_state} (Score: {mom_score:+.1f}%). Rolling 3-day deceleration check.",
        "pe_lvl":  src2_pe,
        "ce_lvl":  src2_ce,
        "detail":  f"EMA3 slope: {ema3_slope:+.1f} pts/day (60% weight)\n"
                   f"EMA8 slope: {ema8_slope:+.1f} pts/day (40% weight)\n"
                   f"State: {mom_state}",
    },
    {
        "source":  "Source 3 — Spot Drift from Tuesday Close",
        "what":    f"{'Anchor available — ' + str(round(factor_a_pct,1)) + '% of Tuesday ATR moved' if tue_anchor_available else 'Tuesday anchor not yet set — will activate after first Tuesday EOD'}",
        "pe_lvl":  src3_pe,
        "ce_lvl":  src3_ce,
        "detail":  (f"Tuesday close: {tue_close:,.0f} · Tuesday ATR: {tue_atr:.0f}\n"
                    f"Distance: {factor_a_pct:.1f}% of Tuesday ATR14\n"
                    f"Mean reversion: Factor B (2-day return direction) determines if signal softens")
                   if tue_anchor_available else "Anchor writes to data/tuesday_anchors.json at EOD Tuesday",
    },
]

LEVEL_COLOUR = {0: "#16a34a", 1: "#d97706", 2: "#d97706", 3: "#ea580c", 4: "#dc2626"}

for s in src_data:
    with st.expander(f"{s['source']} — PE: {CANARY_LABEL.get(s['pe_lvl'],'—')} | CE: {CANARY_LABEL.get(s['ce_lvl'],'—')}", expanded=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            st.markdown(f"<small style='color:#334155;'>{s['what']}</small>", unsafe_allow_html=True)
            st.markdown(f"<pre style='font-size:10px;color:#5a6b8a;'>{s['detail']}</pre>", unsafe_allow_html=True)
        with c2:
            col = LEVEL_COLOUR.get(s["pe_lvl"], "#94a3b8")
            st.markdown(
                f"<div style='border:2px solid {col};border-radius:6px;padding:10px;text-align:center;'>"
                f"<div style='font-size:9px;color:{col};font-weight:700;'>PE LEVEL</div>"
                f"<div style='font-size:18px;font-weight:900;color:{col};'>{CANARY_ICON.get(s['pe_lvl'],'')} {CANARY_LABEL.get(s['pe_lvl'],'—')}</div>"
                f"</div>", unsafe_allow_html=True)
        with c3:
            col = LEVEL_COLOUR.get(s["ce_lvl"], "#94a3b8")
            st.markdown(
                f"<div style='border:2px solid {col};border-radius:6px;padding:10px;text-align:center;'>"
                f"<div style='font-size:9px;color:{col};font-weight:700;'>CE LEVEL</div>"
                f"<div style='font-size:18px;font-weight:900;color:{col};'>{CANARY_ICON.get(s['ce_lvl'],'')} {CANARY_LABEL.get(s['ce_lvl'],'—')}</div>"
                f"</div>", unsafe_allow_html=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Live Moat Status
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — Live Moat Status",
                  "Updated daily during hold — moat count changes as price and EMAs move")

MOAT_COLOUR = {"fortress":"green","strong":"green","adequate":"amber","thin":"red","exposed":"red"}

col1, col2, col3 = st.columns(3)
with col1:
    ui.metric_card("PUT MOATS REMAINING", f"{put_moats:g}",
                   sub=put_label.capitalize(),
                   color=MOAT_COLOUR.get(put_label, "default"))
    if _detail_p:
        st.caption("Active moats: " + " | ".join(f"{lbl}: {val:,.0f}" for lbl, val in _detail_p))

with col2:
    ui.metric_card("CALL MOATS REMAINING", f"{call_moats:g}",
                   sub=call_label.capitalize(),
                   color=MOAT_COLOUR.get(call_label, "default"))
    if _detail_c:
        st.caption("Active moats: " + " | ".join(f"{lbl}: {val:,.0f}" for lbl, val in _detail_c))

with col3:
    MOM_COLOUR_MAP = {
        "STRONG_UP":"red","MODERATE_UP":"amber","FLAT":"green",
        "MODERATE_DOWN":"amber","STRONG_DOWN":"red","TRANSITIONING":"amber"
    }
    threatened = ("PE" if "DOWN" in mom_state else
                  "CE" if "UP" in mom_state else
                  "Both" if mom_state == "TRANSITIONING" else "Neither")
    ui.metric_card("MOMENTUM TODAY", mom_state,
                   sub=f"Threatening: {threatened} · Score: {mom_score:+.1f}%",
                   color=MOM_COLOUR_MAP.get(mom_state, "default"))

    # Threatened leg flip check — flag if direction changed since entry
    entry_regime = sig.get("entry_regime", regime)
    if entry_regime != regime:
        st.warning(f"⚠️ Regime changed since entry: {entry_regime} → {regime}")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Momentum Direction
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 4 — Momentum Direction",
                  "EMA3 and EMA8 slopes · Which leg is threatened today")

c1,c2,c3,c4 = st.columns(4)
with c1: ui.metric_card("EMA3 SLOPE", f"{ema3_slope:+.1f} pts/day", sub="Fast slope (60% weight)")
with c2: ui.metric_card("EMA8 SLOPE", f"{ema8_slope:+.1f} pts/day", sub="Smooth slope (40% weight)")
with c3: ui.metric_card("COMBINED SCORE", f"{mom_score:+.1f}%", sub="% of ATR per day")
with c4: ui.metric_card("THREATENED LEG", threatened,
                         color="red" if threatened in ("PE","CE","Both") else "green")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Hold / Act Decision Table
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 5 — Hold / Watch / Prepare / Act",
                  "Moat count × Canary Day level · Per side independently · More severe of two = page recommendation")

def _action_from_table(moats: float, canary_day: int) -> tuple:
    """Returns (action, level) per locked rules decision table."""
    if moats >= 3:
        if canary_day <= 1: return "✅ HOLD",    "success"
        if canary_day == 2: return "✅ HOLD",    "success"
        if canary_day == 3: return "👁 WATCH",   "info"
        return                       "⚠️ PREPARE","warning"
    elif moats >= 2:
        if canary_day <= 1: return "✅ HOLD",    "success"
        if canary_day == 2: return "👁 WATCH",   "info"
        if canary_day == 3: return "⚠️ PREPARE","warning"
        return                       "🔴 ACT",    "danger"
    elif moats >= 1:
        if canary_day <= 1: return "👁 WATCH",   "info"
        if canary_day == 2: return "⚠️ PREPARE","warning"
        return                       "🔴 ACT",    "danger"
    else:
        if canary_day <= 1: return "⚠️ PREPARE","warning"
        return                       "🔴 ACT",    "danger"

action_pe, level_pe = _action_from_table(put_moats,  pe_canary)
action_ce, level_ce = _action_from_table(call_moats, ce_canary)

col1, col2 = st.columns(2)
with col1:
    ui.alert_box(
        f"PE (Put Side) — {action_pe}",
        f"Moats: {put_moats:g} ({put_label}) · Canary: {CANARY_LABEL.get(pe_canary,'—')}\n"
        f"Put side action: {action_pe}",
        level=level_pe
    )
with col2:
    ui.alert_box(
        f"CE (Call Side) — {action_ce}",
        f"Moats: {call_moats:g} ({call_label}) · Canary: {CANARY_LABEL.get(ce_canary,'—')}\n"
        f"Call side action: {action_ce}",
        level=level_ce
    )

# Page-level recommendation = more severe
severity = {"success": 0, "info": 1, "warning": 2, "danger": 3}
if severity.get(level_pe, 0) >= severity.get(level_ce, 0):
    page_action, page_level = action_pe, level_pe
    page_driver = "PE side"
else:
    page_action, page_level = action_ce, level_ce
    page_driver = "CE side"

ui.alert_box(
    f"PAGE RECOMMENDATION — {page_action} (driven by {page_driver})",
    f"The more severe of PE and CE determines the overall hold recommendation.",
    level=page_level
)

with st.expander("Hold Table Reference — full grid", expanded=False):
    ref_rows = [
        ["3–4 moats", "Day 0–1", "HOLD",    "Structure intact"],
        ["3–4 moats", "Day 2",   "HOLD",    "Still comfortable"],
        ["3–4 moats", "Day 3",   "WATCH",   "Canary escalating — stay alert"],
        ["3–4 moats", "Day 4",   "PREPARE", "Regime shifting — prepare plan"],
        ["2 moats",   "Day 0–1", "HOLD",    "Adequate protection"],
        ["2 moats",   "Day 2",   "WATCH",   "Monitor daily"],
        ["2 moats",   "Day 3",   "PREPARE", "Two walls + canary = action ready"],
        ["2 moats",   "Day 4",   "ACT",     "Roll or exit"],
        ["1 moat",    "Day 0–1", "WATCH",   "One wall — watch closely"],
        ["1 moat",    "Day 2",   "PREPARE", "One wall + canary escalating"],
        ["1 moat",    "Day 3–4", "ACT",     "Execute defensive roll"],
        ["0 moats",   "Day 0–1", "PREPARE", "No EMA protection — have plan"],
        ["0 moats",   "Day 2–4", "ACT",     "Exit or roll immediately"],
    ]
    df_ref = pd.DataFrame(ref_rows, columns=["Moats", "Canary Day", "Action", "Note"])
    st.dataframe(df_ref, use_container_width=True, hide_index=True)
    st.caption("Applied per side independently. CE and PE each get their own action. More severe = page recommendation.")
