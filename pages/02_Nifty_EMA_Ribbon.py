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
    src2_pe_col = "#bbf7d0"; src2_ce_col = "#dc2626"   # CE_RED[1]
elif src2_pe == 2 and src2_ce == 2 and mom_score < 0:  # bearish 2/2: PE real green, CE light red
    src2_pe_col = "#16a34a"; src2_ce_col = "#fca5a5"   # CE_RED[3]
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

# ── DTE & Threat Multiplier ──────────────────────────────────────────────────
try:
    from data.live_fetcher import get_dte as _get_dte, next_tuesday as _next_tue
    dte = _get_dte(_next_tue(_dt.date.today()))
except Exception:
    dte = 7

threat_mult = rel_vol = daily_ret_pct = vol_sma14 = 0.0
try:
    if not _daily.empty and len(_daily) >= 15:
        vol_sma14     = float(_daily["volume"].rolling(14).mean().iloc[-1])
        _td_vol       = float(_daily["volume"].iloc[-1])
        _td_close     = float(_daily["close"].iloc[-1])
        _prev_close   = float(_daily["close"].iloc[-2])
        daily_ret_pct = (_td_close - _prev_close) / _prev_close * 100 if _prev_close > 0 else 0.0
        rel_vol       = _td_vol / vol_sma14 if vol_sma14 > 0 else 1.0
        threat_mult   = abs(daily_ret_pct) * rel_vol
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

# ── Dynamic Roll Matrix pre-compute ─────────────────────────────────────────
_DEF_HI, _DEF_LO, _OFF_THR = 2.8, 2.0, 2.5          # defensive hi/lo, offensive threshold
def_threshold    = _DEF_LO if dte <= 3 else _DEF_HI   # DTE<=3 = gamma risk, no threat needed
def_needs_threat = dte > 3

if tue_anchor_available and tue_close > 0 and spot_now > 0:
    # Exact spot prices where triggers fire (nearest 50pt)
    ce_def_trig_spot = int(round(tue_close * (1 + def_threshold / 100) / 50) * 50)
    pe_def_trig_spot = int(round(tue_close * (1 - def_threshold / 100) / 50) * 50)
    pe_off_trig_spot = int(round(tue_close * (1 + _OFF_THR / 100) / 50) * 50)  # PE dead when UP
    ce_off_trig_spot = int(round(tue_close * (1 - _OFF_THR / 100) / 50) * 50)  # CE dead when DOWN

    ce_adverse = max(drift_pct,  0.0)   # CE threatened: spot went UP from anchor
    pe_adverse = max(-drift_pct, 0.0)   # PE threatened: spot went DOWN from anchor
    pe_favor   = max(drift_pct,  0.0)   # PE dead: spot UP, PE is safe, harvest theta
    ce_favor   = max(-drift_pct, 0.0)   # CE dead: spot DOWN, CE is safe, harvest theta

    ce_def_fired = ce_adverse >= def_threshold and (not def_needs_threat or threat_mult > 1.15)
    pe_def_fired = pe_adverse >= def_threshold and (not def_needs_threat or threat_mult > 1.15)
    ce_def_near  = not ce_def_fired and ce_adverse >= def_threshold * 0.75
    pe_def_near  = not pe_def_fired and pe_adverse >= def_threshold * 0.75
    ce_off_fired = ce_favor >= _OFF_THR
    pe_off_fired = pe_favor >= _OFF_THR

    # Defensive: roll OUT to 5% from anchor close
    ce_def_roll_to = int(round(tue_close * 1.05 / 50) * 50)
    pe_def_roll_to = int(round(tue_close * 0.95 / 50) * 50)

    # Offensive: roll IN from current spot, DTE-scaled distance
    off_in_pct     = 2.5 if dte >= 4 else 2.0 if dte == 3 else 1.5
    ce_off_roll_to = int(round(spot_now * (1 + off_in_pct / 100) / 50) * 50)  # new CE above spot
    pe_off_roll_to = int(round(spot_now * (1 - off_in_pct / 100) / 50) * 50)  # new PE below spot
else:
    ce_adverse = pe_adverse = pe_favor = ce_favor = 0.0
    ce_def_fired = pe_def_fired = ce_def_near = pe_def_near = False
    ce_off_fired = pe_off_fired = False
    ce_def_trig_spot = pe_def_trig_spot = pe_off_trig_spot = ce_off_trig_spot = 0
    ce_def_roll_to = pe_def_roll_to = ce_off_roll_to = pe_off_roll_to = 0
    off_in_pct = 2.5

# Overall PE and CE canary (max across sources)
pe_canary = max(src1 if can_dir == "BEAR" else 0, src2_pe, src3_pe)
ce_canary = max(src1 if can_dir == "BULL" else 0, src2_ce, src3_ce)
overall_canary = max(pe_canary, ce_canary, canary)  # include legacy for safety

# ── Canary colour palettes ──────────────────────────────────────────────────
# PE = green gradient: Day 0 deepest (safest), Day 4 lightest (most exposed)
PE_GREEN = {0:"#14532d", 1:"#15803d", 2:"#16a34a", 3:"#bbf7d0", 4:"#dcfce7"}
# CE = red gradient: Day 0 deepest (safest), Day 4 lightest (most exposed)
CE_RED   = {0:"#b91c1c", 1:"#dc2626", 2:"#ef4444", 3:"#fca5a5", 4:"#fee2e2"}
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
        "detail":  f"EMA3: {e3:,.0f}  ·  EMA8: {e8:,.0f}\n"
                   f"Gap: {gap_pts:.0f} pts  ({gap_pct:.2f}% of ATR)\n"
                   f"Thresholds: >55% = Singing  ·  35–55% = Day 1  ·  15–35% = Day 2  ·  <15% = Day 3  ·  <2% = Day 4\n"
                   f"Rule 1: Gap Day 2+ overrides momentum skew regardless of score",
    },
    {
        "source":      "Source 2 — Momentum Score (% of ATR/day)",
        "what":        f"Score: {mom_score:+.1f}% of ATR/day · IC Shape: {skew_label}",
        "pe_lvl":      src2_pe,
        "ce_lvl":      src2_ce,
        "pe_col":      src2_pe_col,
        "ce_col":      src2_ce_col,
        "detail":      f"EMA3 slope: {ema3_slope:+.1f} pts/day  (60% weight)\n"
                       f"EMA8 slope: {ema8_slope:+.1f} pts/day  (40% weight)\n"
                       f"Combined score: {mom_score:+.1f}% of ATR/day\n"
                       f"Bullish thresholds (PE/CE):  >32% = D0/D4  ·  20–32% = D1/D3  ·  11–20% = D2/D2  ·  5–11% = D3/D1\n"
                       f"Flat zone: ±5% = both Day 0 (amber)  ·  Bearish: mirror of above",
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
        "detail":  (f"Expiry close: {tue_close:,.0f}  ({tue_anchor_date})\n"
                    f"PE sold at −4.0% → {pe_sold:,}  |  CE sold at +3.5% → {ce_sold:,}\n"
                    f"Drift from expiry: {drift_pct:+.2f}%\n"
                    f"PE triggers:  −2.0% = D1  ·  −2.5% = D2  ·  −3.0% = D3  ·  −3.5% = D4\n"
                    f"CE triggers:  +1.5% = D1  ·  +2.0% = D2  ·  +2.5% = D3  ·  +3.0% = D4")
                   if tue_anchor_available else "No expiry anchor available.",
    },
]

# colours that need dark text (light backgrounds)
_LIGHT_COLS = {"#bbf7d0", "#dcfce7", "#fca5a5", "#fecaca", "#fee2e2"}

def _src_card(label, lvl, palette, bg_override=None):
    bg = bg_override if bg_override else (BOTH_AMBER if _both_singing else palette.get(lvl, "#94a3b8"))
    if _both_singing or bg_override == "#d97706":
        txt = "white"
    elif bg_override and bg_override in _LIGHT_COLS:
        txt = "#1e293b"
    else:
        txt = _txt(lvl)
    icon = CANARY_ICON.get(lvl, "⚪")
    lbl  = CANARY_LABEL.get(lvl, "—")
    st.markdown(
        f"<div style='background:{bg};border-radius:8px;padding:10px 16px;margin-bottom:6px;'>"
        f"<div style='color:{txt};font-size:9px;font-weight:700;opacity:0.85;'>{label}</div>"
        f"<div style='color:{txt};font-size:15px;font-weight:900;margin:2px 0;'>{icon} {lbl}</div>"
        f"</div>", unsafe_allow_html=True)

for s in src_data:
    with st.expander(f"{s['source']} — PE: {CANARY_LABEL.get(s['pe_lvl'],'—')} | CE: {CANARY_LABEL.get(s['ce_lvl'],'—')}", expanded=True):
        st.markdown(f"<small style='color:#334155;'>{s['what']}</small>", unsafe_allow_html=True)
        st.markdown(f"<pre style='font-size:10px;color:#5a6b8a;margin-bottom:8px;'>{s['detail']}</pre>", unsafe_allow_html=True)
        if "Source 3" in s["source"] and tue_anchor_available:
            st.caption(f"Expiry anchor: {tue_anchor_date} · close {tue_close:,.0f} · PE sold {pe_sold:,} · CE sold {ce_sold:,}")
        _src_card("PE · PUT SIDE",  s["pe_lvl"], PE_GREEN, s.get("pe_col"))
        _src_card("CE · CALL SIDE", s["ce_lvl"], CE_RED,   s.get("ce_col"))
        if "skew_label" in s:
            sc = s["skew_col"]
            st.markdown(
                f"<div style='margin-top:4px;padding:8px 14px;border-radius:6px;"
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

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Dynamic Roll Matrix
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 6 — Dynamic Roll Matrix",
                  "Threat-scaled defensive stop-loss & offensive theta-harvest triggers · Exact roll-to strikes")

with st.expander("What is the Roll Matrix? — Reference", expanded=False):
    st.markdown(
        "**The Roll Matrix tells you exactly when and how to act on a threatened or dead leg.**\n\n"
        "It runs two independent checks — one for defence, one for offence — on both the CE and PE sides.\n\n"
        "---\n\n"
        "**Defensive Roll — Stop Loss**\n\n"
        "Triggered when spot drifts adversely from the expiry anchor close.\n\n"
        "| DTE | Trigger | Threat check? | Action |\n"
        "|-----|---------|---------------|--------|\n"
        "| ≥ 4 (Wed/Thu) | 2.8% adverse drift | Yes — Threat > 1.15 | Buy back losing leg · Roll OUT to 5% from anchor |\n"
        "| ≤ 3 (Fri/Mon) | 2.0% adverse drift | No — gamma is the risk | Buy back losing leg · Roll OUT to 5% from anchor |\n\n"
        "On Wed/Thu you wait for the Threat Multiplier to confirm the move is institutional before rolling — "
        "a 2.8% drift on thin volume often reverses. On Fri/Mon, gamma risk is too high to wait; act at 2.0% regardless.\n\n"
        "---\n\n"
        "**Offensive Roll — Theta Harvest**\n\n"
        "Triggered when spot moves *favourably* by 2.5% — the opposing leg loses nearly all delta and becomes cheap to buy back.\n\n"
        "| DTE | Roll IN to (from current spot) |\n"
        "|-----|--------------------------------|\n"
        "| ≥ 4 (Wed/Thu) | 2.5% from spot |\n"
        "| 3 (Fri) | 2.0% from spot |\n"
        "| ≤ 2 (Mon/Tue) | 1.5% from spot |\n\n"
        "The closer to expiry, the tighter you sell the new strike — you need less distance because the remaining theta "
        "collapses faster.\n\n"
        "---\n\n"
        "**Threat Multiplier** = |daily return %| × relative volume (today / 14-day avg)\n\n"
        "A value > 1.15 means the move is backed by above-average institutional activity. "
        "Below 1.15 the move may be noise. Only relevant for the DTE ≥ 4 defensive trigger.\n\n"
        "Note: volume data uses yesterday's completed candle until a live volume feed is wired in."
    )

# ── Metrics row ──────────────────────────────────────────────────────────────
_dte_label = {0:"Tue · Expiry",1:"Tue · Expiry",2:"Wed",3:"Thu",4:"Fri",5:"Mon",6:"Tue · Entry"}.get(
    (7 - dte) % 7 if dte > 0 else 0, f"DTE {dte}")
_thr_col = "#dc2626" if threat_mult > 1.5 else "#ea580c" if threat_mult > 1.15 else "#16a34a"
_drift_col = "#dc2626" if abs(drift_pct) >= 2.0 else "#ea580c" if abs(drift_pct) >= 1.0 else "#16a34a"

c1, c2, c3, c4 = st.columns(4)
with c1: ui.metric_card("DTE",            f"{dte}",              sub=f"Thresh: {'2.0%' if dte<=3 else '2.8%+Threat'}")
with c2: ui.metric_card("THREAT MULT",    f"{threat_mult:.2f}",  sub=f"Ret {daily_ret_pct:+.1f}% · RelVol {rel_vol:.2f}",
                         color="red" if threat_mult > 1.15 else "green")
with c3: ui.metric_card("ANCHOR CLOSE",   f"{tue_close:,.0f}" if tue_anchor_available else "N/A",
                         sub=f"Expiry: {tue_anchor_date}" if tue_anchor_available else "No anchor")
with c4: ui.metric_card("DRIFT FROM ANCHOR", f"{drift_pct:+.2f}%" if tue_anchor_available else "—",
                         sub=f"Spot {spot_now:,.0f}", color="red" if abs(drift_pct) >= 2.0 else "default")

st.markdown("**Defensive Roll — Stop Loss**")
st.caption(f"DTE {dte}: threshold {'2.0% (gamma — no threat check)' if dte<=3 else f'2.8% + Threat > 1.15 (current: {threat_mult:.2f})'}")

def _def_card(side_label, adverse, fired, near, trig_spot, roll_to, palette):
    if fired:
        bg, txt_col = palette[0], "white"
        status = "STOP-LOSS TRIGGERED"
        body   = (f"Adverse drift {adverse:.2f}% ≥ {def_threshold:.1f}% threshold"
                  + ("" if not def_needs_threat else f" · Threat {threat_mult:.2f} > 1.15"))
        action = f"BUY BACK losing leg · Roll OUT to {roll_to:,} (5% from anchor)"
    elif near:
        bg, txt_col = "#ea580c", "white"
        status = "APPROACHING"
        gap = def_threshold - adverse
        body   = f"Drift {adverse:.2f}% · Gap to trigger: {gap:.2f}% · Trigger spot: {trig_spot:,}"
        action = f"Monitor closely · Trigger at {trig_spot:,} → Roll to {roll_to:,}"
    else:
        bg  = palette[0]
        txt_col = "white"
        status = "CLEAR"
        gap = def_threshold - adverse
        body   = f"Adverse drift {adverse:.2f}% · Gap to trigger: {gap:.2f}%"
        action = f"Trigger spot: {trig_spot:,} · Roll OUT to: {roll_to:,}"
        bg = palette[4] if adverse < 0.5 else palette[3] if adverse < 1.0 else palette[2]
        txt_col = "#1e293b" if bg in _LIGHT_COLS else "white"
    st.markdown(
        f"<div style='background:{bg};border-radius:8px;padding:12px 16px;margin-bottom:6px;'>"
        f"<div style='color:{txt_col};font-size:9px;font-weight:700;opacity:0.85;'>{side_label}</div>"
        f"<div style='color:{txt_col};font-size:14px;font-weight:900;margin:2px 0;'>{status}</div>"
        f"<div style='color:{txt_col};font-size:10px;opacity:0.9;margin-bottom:2px;'>{body}</div>"
        f"<div style='color:{txt_col};font-size:10px;font-style:italic;opacity:0.8;'>{action}</div>"
        f"</div>", unsafe_allow_html=True)

if tue_anchor_available:
    _def_card("CE · CALL SIDE — Defensive",
              ce_adverse, ce_def_fired, ce_def_near, ce_def_trig_spot, ce_def_roll_to, CE_RED)
    _def_card("PE · PUT SIDE — Defensive",
              pe_adverse, pe_def_fired, pe_def_near, pe_def_trig_spot, pe_def_roll_to, PE_GREEN)
else:
    st.info("Expiry anchor not available — load data to activate roll matrix.")

st.markdown("**Offensive Roll — Theta Harvest**")
st.caption(f"Trigger: 2.5% favorable drift · Roll IN to {off_in_pct:.1f}% from spot (DTE {dte} rule)")

def _off_card(side_label, favor, fired, trig_spot, roll_to, palette):
    gap = _OFF_THR - favor
    if fired:
        bg      = "#0f766e"   # teal — profit action
        txt_col = "white"
        status  = "ROLL-IN READY"
        body    = f"Favorable drift {favor:.2f}% ≥ 2.5% threshold · Dead leg has minimal delta"
        action  = f"BUY BACK dead leg · Roll IN to {off_in_pct:.1f}% from spot → {roll_to:,}"
    else:
        bg      = palette[4] if favor < 0.5 else palette[3] if favor < 1.5 else palette[2]
        txt_col = "#1e293b" if bg in _LIGHT_COLS else "white"
        status  = "CLEAR"
        body    = f"Favorable drift {favor:.2f}% · Need {gap:.2f}% more to trigger · Trigger spot: {trig_spot:,}"
        action  = f"If triggered: Roll IN to {off_in_pct:.1f}% from spot → {roll_to:,}"
    st.markdown(
        f"<div style='background:{bg};border-radius:8px;padding:12px 16px;margin-bottom:6px;'>"
        f"<div style='color:{txt_col};font-size:9px;font-weight:700;opacity:0.85;'>{side_label}</div>"
        f"<div style='color:{txt_col};font-size:14px;font-weight:900;margin:2px 0;'>{status}</div>"
        f"<div style='color:{txt_col};font-size:10px;opacity:0.9;margin-bottom:2px;'>{body}</div>"
        f"<div style='color:{txt_col};font-size:10px;font-style:italic;opacity:0.8;'>{action}</div>"
        f"</div>", unsafe_allow_html=True)

if tue_anchor_available:
    _off_card("CE · CALL SIDE — Offensive (CE dead when spot falls)",
              ce_favor, ce_off_fired, ce_off_trig_spot, ce_off_roll_to, CE_RED)
    _off_card("PE · PUT SIDE — Offensive (PE dead when spot rises)",
              pe_favor, pe_off_fired, pe_off_trig_spot, pe_off_roll_to, PE_GREEN)
