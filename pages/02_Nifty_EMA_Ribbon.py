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

# Source 1 — EMA3/EMA8 gap · thresholds: 55/35/15 % of ATR
# Direction: BULL = CE threatened · BEAR = PE threatened
if   gap_pct > 55: src1 = 0   # Singing — structure wide, safe
elif gap_pct > 35: src1 = 1   # Stable trend
elif gap_pct > 15: src1 = 2   # Compressing — flatten skew to 1:1
elif gap_pct >  2: src1 = 3   # Cross imminent — exit heavy side
else:              src1 = 4   # Cross — close all

# Source 2 — Momentum % of ATR/day · PE + CE = 4, except flat zone = 0 + 0
def _src2_levels(score):
    if -5.0 <= score <= 5.0:  return 0, 0          # flat: both singing (amber)
    elif score > 0:                                  # bullish
        if   score > 32: return 0, 4
        elif score > 20: return 1, 3
        elif score > 11: return 2, 2
        else:            return 3, 1                # 5–11%
    else:                                            # bearish
        s = abs(score)
        if   s > 32: return 4, 0
        elif s > 20: return 3, 1
        elif s > 11: return 2, 2
        else:        return 1, 3                    # 5–11%

src2_pe, src2_ce = _src2_levels(mom_score)

# Color overrides for Source 2 cards
if src2_pe == 0 and src2_ce == 0:                  # flat: amber both
    src2_pe_col = src2_ce_col = "#d97706"
elif src2_pe == 2 and src2_ce == 2 and mom_score > 0:  # bullish 2/2: PE light green, CE real red
    src2_pe_col = "#bbf7d0"; src2_ce_col = "#dc2626"
elif src2_pe == 2 and src2_ce == 2 and mom_score < 0:  # bearish 2/2: PE real green, CE light red
    src2_pe_col = "#16a34a"; src2_ce_col = "#fecaca"
else:
    src2_pe_col = src2_ce_col = None               # use standard LEVEL_COLOUR

# Skew from momentum (bullish = PE heavy, bearish = CE heavy — sell more on the SAFE side)
skew_forced = False
if abs(mom_score) > 20:
    if mom_score > 0:
        skew_label = "2:1 PE heavy"; skew_note = "market rising — sell more puts, CE exposure light"; skew_col = "#16a34a"
    else:
        skew_label = "1:2 CE heavy"; skew_note = "market falling — sell more calls, PE exposure light"; skew_col = "#dc2626"
else:
    skew_label = "1:1 Balanced"; skew_note = "no directional edge · balanced condor"; skew_col = "#d97706"

# Rule 1: Gap overrides skew at Day 2+
if src1 >= 3:
    skew_label = "EXIT heavy side"; skew_note = f"Gap Day {src1} ({gap_pct:.0f}% ATR) — structure broken"; skew_col = "#dc2626"; skew_forced = True
elif src1 == 2:
    skew_label = "1:1 Forced"; skew_note = f"Gap Day 2 ({gap_pct:.0f}% ATR) — overrides momentum skew"; skew_col = "#ea580c"; skew_forced = True

# Source 3 — Tuesday anchor: auto-computed from cached daily data
# Uses last Tuesday, or last trading day before it if Tuesday was a holiday
import datetime as _dt, numpy as _np
tue_close = tue_atr = 0.0
tue_anchor_available = False
tue_anchor_date = ""
try:
    from data.live_fetcher import get_nifty_daily
    _daily = get_nifty_daily()
    if not _daily.empty:
        _today = _dt.date.today()
        _days_since_tue = (_today.weekday() - 1) % 7
        _last_tue = _today - _dt.timedelta(days=_days_since_tue)
        _trading_dates = set(_daily.index.date)
        _anchor_date = None
        for _offset in range(7):
            _candidate = _last_tue - _dt.timedelta(days=_offset)
            if _candidate in _trading_dates:
                _anchor_date = _candidate
                break
        if _anchor_date:
            _hist = _daily[_daily.index.date <= _anchor_date].tail(15)
            tue_close = float(_hist["close"].iloc[-1])
            _h, _l, _c = _hist["high"].values, _hist["low"].values, _hist["close"].values
            _tr = [max(_h[i]-_l[i], abs(_h[i]-_c[i-1]), abs(_l[i]-_c[i-1]))
                   for i in range(1, len(_hist))]
            tue_atr = float(_np.mean(_tr[-14:])) if len(_tr) >= 14 else float(_np.mean(_tr))
            tue_anchor_date = str(_anchor_date)
            tue_anchor_available = True
except Exception:
    pass

spot_now = spot
src3_pe = src3_ce = 0
pe_sold = ce_sold = 0
drift_pct = 0.0
# Source 3: expiry close = Tuesday close (or last trading day before Tuesday if holiday)
# PE sold 4% below expiry close, CE sold 3.5% above expiry close (rounded to nearest 50-pt strike)
# Canary triggers based on % drift from expiry close toward the sold strike
if tue_anchor_available and tue_close > 0 and spot_now > 0:
    pe_sold   = int(round(tue_close * 0.96  / 50) * 50)
    ce_sold   = int(round(tue_close * 1.035 / 50) * 50)
    drift_pct = (spot_now - tue_close) / tue_close * 100
    # CE side: sold at +3.5% → canary thresholds at +1.5%, +2.0%, +2.5%, +3.0%
    if   drift_pct >= 3.0: src3_ce = 4
    elif drift_pct >= 2.5: src3_ce = 3
    elif drift_pct >= 2.0: src3_ce = 2
    elif drift_pct >= 1.5: src3_ce = 1
    # PE side: sold at -4.0% → canary thresholds at -2.0%, -2.5%, -3.0%, -3.5%
    if   drift_pct <= -3.5: src3_pe = 4
    elif drift_pct <= -3.0: src3_pe = 3
    elif drift_pct <= -2.5: src3_pe = 2
    elif drift_pct <= -2.0: src3_pe = 1

# Overall PE and CE canary (max across sources)
pe_canary = max(src1 if can_dir == "BEAR" else 0, src2_pe, src3_pe)
ce_canary = max(src1 if can_dir == "BULL" else 0, src2_ce, src3_ce)
overall_canary = max(pe_canary, ce_canary, canary)  # include legacy for safety

# ── Canary colour palettes ──────────────────────────────────────────────────
# PE = green gradient: Day 0 deepest (safest), Day 4 lightest (most exposed)
PE_GREEN = {0:"#14532d", 1:"#15803d", 2:"#16a34a", 3:"#bbf7d0", 4:"#dcfce7"}
# CE = red gradient: Day 0 deepest (safest), Day 4 lightest (most exposed)
CE_RED   = {0:"#7f1d1d", 1:"#991b1b", 2:"#dc2626", 3:"#fecaca", 4:"#fee2e2"}
# Text: white on deep shades, dark on light shades
def _txt(lvl): return "#1e293b" if lvl >= 3 else "white"
# Both singing → amber
BOTH_AMBER = "#d97706"

# ── Driver attribution (needed by header) ────────────────────────────────────
src1_pe_eff = src1 if can_dir == "BEAR" else 0
src1_ce_eff = src1 if can_dir == "BULL" else 0
pe_driver = "Source 1" if src1_pe_eff >= src2_pe and src1_pe_eff >= src3_pe else \
            "Source 2" if src2_pe >= src3_pe else "Source 3"
ce_driver = "Source 1" if src1_ce_eff >= src2_ce and src1_ce_eff >= src3_ce else \
            "Source 2" if src2_ce >= src3_ce else "Source 3"

# ── Page header colour ───────────────────────────────────────────────────────
CANARY_LABEL  = {0: "SINGING", 1: "Canary Day 1", 2: "Canary Day 2",
                 3: "Canary Day 3", 4: "Canary Day 4"}
CANARY_ACTION = {0: "HOLD", 1: "WATCH", 2: "WATCH", 3: "PREPARE", 4: "ACT"}
CANARY_ICON   = {0: "✅", 1: "🟡", 2: "⚠️", 3: "🔴", 4: "🔴"}
CANARY_HEADER_COLOUR = {0: "#d97706", 1: "#d97706", 2: "#d97706", 3: "#ea580c", 4: "#dc2626"}
overall_action = CANARY_ACTION.get(overall_canary, "WATCH")
overall_label  = CANARY_LABEL.get(overall_canary, "Canary Day 4")

_both_singing = (pe_canary == 0 and ce_canary == 0)
_pe_hdr = BOTH_AMBER if _both_singing else PE_GREEN.get(pe_canary, "#94a3b8")
_ce_hdr = BOTH_AMBER if _both_singing else CE_RED.get(ce_canary, "#94a3b8")
_pe_txt = "white" if _both_singing else _txt(pe_canary)
_ce_txt = "white" if _both_singing else _txt(ce_canary)
_act_col = {0:"#d97706",1:"#d97706",2:"#d97706",3:"#ea580c",4:"#dc2626"}.get(overall_canary,"#94a3b8")
if _both_singing: _act_col = "#d97706"

st.markdown(
    f"<div style='display:flex;border-radius:8px;overflow:hidden;margin-bottom:12px;gap:2px;'>"
    # PE side
    f"<div style='background:{_pe_hdr};flex:1;padding:10px 16px;'>"
    f"<div style='color:{_pe_txt};font-size:9px;font-weight:700;opacity:0.9;'>PE · PUT SIDE</div>"
    f"<div style='color:{_pe_txt};font-size:15px;font-weight:900;'>{CANARY_ICON.get(pe_canary,'')} {CANARY_LABEL.get(pe_canary,'—')}</div>"
    f"<div style='color:{_pe_txt};font-size:9px;opacity:0.8;'>{pe_driver}</div>"
    f"</div>"
    # Centre action
    f"<div style='background:{_act_col};padding:10px 14px;display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:90px;'>"
    f"<div style='color:white;font-size:8px;font-weight:700;letter-spacing:1px;text-align:center;'>EMA HOLD MONITOR</div>"
    f"<div style='color:white;font-size:18px;font-weight:900;'>{overall_action}</div>"
    f"<div style='color:rgba(255,255,255,0.75);font-size:8px;font-family:monospace;'>{regime}</div>"
    f"</div>"
    # CE side
    f"<div style='background:{_ce_hdr};flex:1;padding:10px 16px;text-align:right;'>"
    f"<div style='color:{_ce_txt};font-size:9px;font-weight:700;opacity:0.9;'>CE · CALL SIDE</div>"
    f"<div style='color:{_ce_txt};font-size:15px;font-weight:900;'>{CANARY_ICON.get(ce_canary,'')} {CANARY_LABEL.get(ce_canary,'—')}</div>"
    f"<div style='color:{_ce_txt};font-size:9px;opacity:0.8;'>{ce_driver}</div>"
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
                 width="stretch", hide_index=True)

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
    st.dataframe(_can_ref, width="stretch", hide_index=True)
    st.markdown("**Three sources that vote:**")
    _src_ref = pd.DataFrame([
        ["Source 1", "EMA Proximity",           "EMA3 vs EMA8 gap shrinking. Fires BEFORE the crossover — gives you advance notice."],
        ["Source 2", "Momentum Acceleration",   "3-day rolling deceleration of EMA slopes. Detects when the move toward your strike is picking up speed."],
        ["Source 3", "Spot Drift from Expiry Close", "% drift of spot from Tuesday (expiry) close. PE sold 4% below, CE sold 3.5% above. Canary fires 2% before the sold strike."],
    ], columns=["Source", "Name", "What it detects"])
    st.dataframe(_src_ref, width="stretch", hide_index=True)

def canary_card(side, level, driving_src, is_pe=True):
    palette = PE_GREEN if is_pe else CE_RED
    bg  = BOTH_AMBER if _both_singing else palette.get(level, "#94a3b8")
    txt = "white" if (_both_singing or level < 3) else "#1e293b"
    icon  = CANARY_ICON.get(level, "⚪")
    label = CANARY_LABEL.get(level, "—")
    action_map = {0:"Hold — structure intact", 1:"Watch — EOD check",
                  2:"Monitor moats actively", 3:"Prepare roll plan now", 4:"Act now — roll or exit"}
    st.markdown(
        f"<div style='background:{bg};border-radius:8px;padding:12px 16px;'>"
        f"<div style='color:{txt};font-size:9px;font-weight:700;opacity:0.85;'>{side}</div>"
        f"<div style='color:{txt};font-size:16px;font-weight:900;margin:2px 0;'>{icon} {label}</div>"
        f"<div style='color:{txt};font-size:10px;opacity:0.85;'>Driver: {driving_src}</div>"
        f"<div style='color:{txt};font-size:10px;opacity:0.75;'>{action_map.get(level,'—')}</div>"
        f"</div>", unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1: canary_card("PE · PUT SIDE", pe_canary, pe_driver, is_pe=True)
with col2: canary_card("CE · CALL SIDE", ce_canary, ce_driver, is_pe=False)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Three Source Breakdown
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Three Source Breakdown",
                  "Diagnostic layer — see exactly which source is driving the canary and why")

# ── Verdict block: synthesises the interplay of all three sources ─────────────
_vc_lvl  = max(pe_canary, ce_canary)
_vc_side = "CE" if ce_canary >= pe_canary else "PE"
_vc_drv  = ce_driver if ce_canary >= pe_canary else pe_driver
_vc_col  = CANARY_HEADER_COLOUR.get(_vc_lvl, "#94a3b8")

if _vc_lvl == 0:
    _verdict_main = "All three sources are clear. EMA structure intact, no drift pressure. Hold with confidence."
else:
    _verdict_main = (f"{_vc_drv} is driving {_vc_side} to {CANARY_LABEL.get(_vc_lvl)} — "
                     f"{CANARY_ACTION.get(_vc_lvl,'WATCH')} on the {_vc_side} side.")

if src1 >= 3:
    _rule1_text = f"Rule 1 — Gap Day {src1} ({gap_pct:.0f}% ATR): exit the heavy side immediately. Skew irrelevant."
    _rule1_col  = "#dc2626"
elif src1 == 2:
    _rule1_text = f"Rule 1 — Gap Day 2 ({gap_pct:.0f}% ATR): skew overridden — flatten to 1:1 regardless of momentum."
    _rule1_col  = "#ea580c"
else:
    _rule1_text = f"Rule 1 — Gap Day {src1} ({gap_pct:.0f}% ATR, {can_dir}): {skew_label} skew stands."
    _rule1_col  = "#16a34a"

if _vc_lvl > 0:
    _rule2_text = f"Rule 2 — Harshest signal wins: {_vc_drv} overrides all other sources at {CANARY_LABEL.get(_vc_lvl)}."
    _rule2_col  = _vc_col
else:
    _rule2_text = "Rule 2 — No source firing. Max() across all sources = Singing."
    _rule2_col  = "#16a34a"

st.markdown(
    f"<div style='border-left:4px solid {_vc_col};padding:10px 16px;border-radius:0 6px 6px 0;"
    f"background:{_vc_col}10;margin-bottom:10px;'>"
    f"<div style='font-size:12px;font-weight:700;color:{_vc_col};margin-bottom:4px;'>VERDICT</div>"
    f"<div style='font-size:12px;color:#1e293b;margin-bottom:6px;'>{_verdict_main}</div>"
    f"<div style='font-size:11px;color:{_rule1_col};margin-bottom:2px;'>{_rule1_text}</div>"
    f"<div style='font-size:11px;color:{_rule2_col};'>{_rule2_text}</div>"
    f"</div>", unsafe_allow_html=True)

src_data = [
    {
        "source":  "Source 1 — EMA Proximity",
        "what":    f"EMA3/EMA8 gap: {gap_pts:.0f} pts ({gap_pct:.2f}% ATR) · Direction: {can_dir}",
        "pe_lvl":  src1_pe_eff,
        "ce_lvl":  src1_ce_eff,
        "detail":  f"EMA3={e3:,.0f} · EMA8={e8:,.0f} · Gap={gap_pts:.0f} pts ({gap_pct:.2f}% ATR)\n"
                   f"Thresholds: >55%=Singing · 35-55%=Day1 · 15-35%=Day2 · <15%=Day3 · <2%=Day4(Cross)\n"
                   f"Rule 1: Gap Day 2+ overrides momentum skew",
    },
    {
        "source":      "Source 2 — Momentum Score (% of ATR/day)",
        "what":        f"Score: {mom_score:+.1f}% of ATR/day · IC Shape: {skew_label}",
        "pe_lvl":      src2_pe,
        "ce_lvl":      src2_ce,
        "pe_col":      src2_pe_col,
        "ce_col":      src2_ce_col,
        "detail":      f"EMA3 slope: {ema3_slope:+.1f} pts/day (60% weight)\n"
                       f"EMA8 slope: {ema8_slope:+.1f} pts/day (40% weight)\n"
                       f"Combined score: {mom_score:+.1f}% ATR/day\n"
                       f"Thresholds: >32%(D0/D4) 20-32%(D1/D3) 11-20%(D2/D2) 5-11%(D3/D1) flat±5%=0/0",
        "skew_label":  skew_label,
        "skew_note":   skew_note,
        "skew_col":    skew_col,
    },
    {
        "source":  "Source 3 — Spot Drift from Expiry Close",
        "what":    (f"Drift: {drift_pct:+.2f}% from expiry close · PE sold {pe_sold:,} · CE sold {ce_sold:,}"
                    if tue_anchor_available else
                    "Expiry anchor not yet available"),
        "pe_lvl":  src3_pe,
        "ce_lvl":  src3_ce,
        "detail":  (f"Expiry close: {tue_close:,.0f} ({tue_anchor_date})\n"
                    f"PE sold at −4.0% → {pe_sold:,}  |  CE sold at +3.5% → {ce_sold:,}\n"
                    f"Drift from expiry: {drift_pct:+.2f}%\n"
                    f"PE triggers: −2%(D1) −2.5%(D2) −3%(D3) −3.5%(D4)\n"
                    f"CE triggers: +1.5%(D1) +2%(D2) +2.5%(D3) +3%(D4)")
                   if tue_anchor_available else "No expiry anchor available.",
    },
]

LEVEL_COLOUR = {0: "#16a34a", 1: "#d97706", 2: "#d97706", 3: "#ea580c", 4: "#dc2626"}

for s in src_data:
    with st.expander(f"{s['source']} — PE: {CANARY_LABEL.get(s['pe_lvl'],'—')} | CE: {CANARY_LABEL.get(s['ce_lvl'],'—')}", expanded=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            st.markdown(f"<small style='color:#334155;'>{s['what']}</small>", unsafe_allow_html=True)
            st.markdown(f"<pre style='font-size:10px;color:#5a6b8a;'>{s['detail']}</pre>", unsafe_allow_html=True)
            if "Source 3" in s["source"] and tue_anchor_available:
                st.caption(f"Expiry anchor: {tue_anchor_date} · close {tue_close:,.0f} · PE sold {pe_sold:,} · CE sold {ce_sold:,}")
        with c2:
            col = s.get("pe_col") or PE_GREEN.get(s["pe_lvl"], "#94a3b8")
            st.markdown(
                f"<div style='border:2px solid {col};border-radius:6px;padding:10px;text-align:center;'>"
                f"<div style='font-size:9px;color:{col};font-weight:700;'>PE LEVEL</div>"
                f"<div style='font-size:18px;font-weight:900;color:{col};'>{CANARY_ICON.get(s['pe_lvl'],'')} {CANARY_LABEL.get(s['pe_lvl'],'—')}</div>"
                f"</div>", unsafe_allow_html=True)
        with c3:
            col = s.get("ce_col") or CE_RED.get(s["ce_lvl"], "#94a3b8")
            st.markdown(
                f"<div style='border:2px solid {col};border-radius:6px;padding:10px;text-align:center;'>"
                f"<div style='font-size:9px;color:{col};font-weight:700;'>CE LEVEL</div>"
                f"<div style='font-size:18px;font-weight:900;color:{col};'>{CANARY_ICON.get(s['ce_lvl'],'')} {CANARY_LABEL.get(s['ce_lvl'],'—')}</div>"
                f"</div>", unsafe_allow_html=True)
        if "skew_label" in s:
            sc = s["skew_col"]
            st.markdown(
                f"<div style='margin-top:8px;padding:8px 14px;border-radius:6px;"
                f"background:{sc}18;border-left:3px solid {sc};'>"
                f"<span style='font-size:11px;font-weight:700;color:{sc};'>IC SHAPE · {s['skew_label']}</span>"
                f"<span style='font-size:10px;color:#334155;'> — {s['skew_note']}</span>"
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
    st.dataframe(df_ref, width="stretch", hide_index=True)
    st.caption("Applied per side independently. CE and PE each get their own action. More severe = page recommendation.")
