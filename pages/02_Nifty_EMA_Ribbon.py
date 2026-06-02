# pages/02_Nifty_EMA_Ribbon.py — v2.2 (Trading Sessions & Math UI Update)
# EMA Hold Monitor — Full redesign per locked rules Section 3 + 4.2
#
# LOCKED CHANGES:
#   - Auto-compute fallback — no forced Home redirect
#   - Five sections: Canary Dashboard, Source Breakdown, Moat Status, Momentum, Hold/Act Table
#   - PE canary and CE canary shown independently throughout
#   - Page header colour driven by combined canary level
#   - Three-source canary display (sources computed in ema.py / canary_level from signals)
#   - New Hold/Act table (moats × canary Day, per side independently)
#   - VIX-Adjusted DTB, Cycle-Filtering (Wed-Tue), Live Data Priority
#   - Relative True Range (RTR) replaces Nifty Spot Volume for institutional threat
#   - Explicit math calculations displayed in UI elements

import streamlit as st
import pandas as pd
import numpy as np
from streamlit_autorefresh import st_autorefresh
import ui.components as ui
from pathlib import Path
import json

st.set_page_config(page_title="P02 · EMA Hold Monitor", layout="wide")
st_autorefresh(interval=180_000, key="p02")
st.title("Page 02 — EMA Hold Monitor")
st.caption("Canary Dashboard · EMA Moat Stack · Strike-Path Corridors · Momentum · Hold/Act Table")

from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

# Save EOD entry values BEFORE live override — locks adjusted strikes and entry regime
_entry_put_moats  = sig.get("cr_put_moats",  2)
_entry_call_moats = sig.get("cr_call_moats", 2)
_entry_regime     = sig.get("cr_regime", "INSIDE_BULL")

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

# Source 1 — EMA3/EMA8 gap (LIVE)
e3  = sig.get("ema3",  ema_vals.get(3,  0))
e8  = sig.get("ema8",  ema_vals.get(8,  0))
e16 = sig.get("ema16", ema_vals.get(16, 0))
e30 = sig.get("ema30", ema_vals.get(30, 0))
gap_pts = abs(e3 - e8) if e3 and e8 else 0
gap_pct = gap_pts / atr14 * 100 if atr14 > 0 else 0

can_dir_live = "BULL" if (e3 and e8 and e3 > e8) else "BEAR" if (e3 and e8 and e3 < e8) else can_dir

if   gap_pct > 55: _src1_threatened = 4
elif gap_pct > 35: _src1_threatened = 3
elif gap_pct > 15: _src1_threatened = 2
elif gap_pct >  5: _src1_threatened = 1
else:              _src1_threatened = 0

src1    = _src1_threatened
src1_pe = _src1_threatened if can_dir_live == "BEAR" else 0
src1_ce = _src1_threatened if can_dir_live == "BULL" else 0

# Source 2 — Momentum % of ATR/day
def _src2_levels(score):
    if -5.0 <= score <= 5.0:  return 0, 0
    elif score > 0:
        if   score > 32: return 0, 4
        elif score > 20: return 0, 3
        elif score > 11: return 0, 2
        else:            return 0, 1
    else:
        s = abs(score)
        if   s > 32: return 4, 0
        elif s > 20: return 3, 0
        elif s > 11: return 2, 0
        else:        return 1, 0

src2_pe, src2_ce = _src2_levels(mom_score)

if src2_pe == 0 and src2_ce == 0:
    src2_pe_col = src2_ce_col = "#d97706"
else:
    src2_pe_col = src2_ce_col = None

skew_forced = False
if abs(mom_score) > 20:
    if mom_score > 0:
        skew_label = "2:1 PE heavy"; skew_note = "market rising — sell more puts, CE exposure light"; skew_col = "#16a34a"
    else:
        skew_label = "1:2 CE heavy"; skew_note = "market falling — sell more calls, PE exposure light"; skew_col = "#dc2626"
else:
    skew_label = "1:1 Balanced"; skew_note = "no directional edge · balanced condor"; skew_col = "#d97706"

_thr_side = "CE" if can_dir_live == "BULL" else "PE"
if src1 >= 4:
    skew_label = f"EXIT {_thr_side}"; skew_note = f"Gap D4 ({gap_pct:.0f}% ATR) — strong trend, exit {_thr_side} immediately"; skew_col = "#dc2626"; skew_forced = True
elif src1 == 3:
    skew_label = f"REDUCE {_thr_side}"; skew_note = f"Gap D3 ({gap_pct:.0f}% ATR) — solid trend, cut {_thr_side} exposure"; skew_col = "#ea580c"; skew_forced = True
elif src1 == 2:
    skew_label = "1:1 Forced"; skew_note = f"Gap D2 ({gap_pct:.0f}% ATR) — moderate trend, flatten skew"; skew_col = "#d97706"; skew_forced = True

# Source 3 — Anchor from rolled_positions.json (set by EOD job each Tuesday)
import datetime as _dt, numpy as _np
tue_close = tue_atr = 0.0
tue_anchor_available = False
tue_anchor_date = ""
from data.rolled_positions import load_rolled, rolled_strikes as _rs_fn
_rolled = load_rolled()
_anchor_val = _rolled.get("anchor")
if _anchor_val and float(_anchor_val) > 0:
    tue_close            = float(_anchor_val)
    tue_anchor_date      = str(_rolled.get("anchor_date", ""))
    tue_anchor_available = True
    # ATR from daily data for DTB calculation
    try:
        from data.live_fetcher import get_nifty_daily
        _daily_atr = get_nifty_daily()
        if not _daily_atr.empty and len(_daily_atr) >= 15:
            _hh = _daily_atr["high"].values[-15:]
            _ll = _daily_atr["low"].values[-15:]
            _cc = _daily_atr["close"].values[-15:]
            _tr = [max(_hh[i]-_ll[i], abs(_hh[i]-_cc[i-1]), abs(_ll[i]-_cc[i-1]))
                   for i in range(1, len(_hh))]
            tue_atr = float(_np.mean(_tr[-14:])) if len(_tr) >= 14 else float(_np.mean(_tr)) if _tr else 200.0
    except Exception:
        tue_atr = atr14

# ── DTE & Threat Multiplier (Trading Session Upgraded) ───────────────────────
try:
    from data.live_fetcher import get_dte as _get_dte, next_tuesday as _next_tue
    dte = _get_dte(_next_tue(_dt.date.today()))
except Exception:
    dte = 7

threat_mult = rel_range = daily_ret_pct = 0.0
ce_threat_mult = pe_threat_mult = 0.0
_yday_ce_thr = _yday_pe_thr = 0.0
_today_move_pts = _yday_move_pts = 0.0
_prev_close_live = 0.0

try:
    from data.live_fetcher import get_nifty_daily_live as _gdl
    _dlive = _gdl()
    if not _dlive.empty and len(_dlive) >= 3:
        # Calculate True Range for the RTR Proxy
        _dlive["prev_close"] = _dlive["close"].shift(1)
        _dlive["tr1"] = _dlive["high"] - _dlive["low"]
        _dlive["tr2"] = (_dlive["high"] - _dlive["prev_close"]).abs()
        _dlive["tr3"] = (_dlive["low"] - _dlive["prev_close"]).abs()
        _dlive["true_range"] = _dlive[["tr1", "tr2", "tr3"]].max(axis=1)
        _atr14_live = float(_dlive["true_range"].rolling(14).mean().iloc[-1])

        # ALWAYS treat the last available data row as "Latest Session" and previous as "Yday"
        _today_row, _yday_row, _d2ago_row = _dlive.iloc[-1], _dlive.iloc[-2], _dlive.iloc[-3]
            
        _prev_close_live = float(_yday_row["close"])
        _d2ago_close     = float(_d2ago_row["close"])
        
        # Latest Session metrics
        _today_tr = max(float(_today_row["high"]) - float(_today_row["low"]),
                        abs(float(_today_row["high"]) - _prev_close_live),
                        abs(float(_today_row["low"]) - _prev_close_live))
        
        rel_range       = _today_tr / _atr14_live if _atr14_live > 0 else 1.0
        _today_move_pts = (spot if spot > 0 else float(_today_row["close"])) - _prev_close_live
        daily_ret_pct   = _today_move_pts / _prev_close_live * 100 if _prev_close_live > 0 else 0.0
        threat_mult     = abs(daily_ret_pct) * rel_range
            
        # Previous Session metrics
        _yday_move_pts = _prev_close_live - _d2ago_close
        _yday_ret_pct  = _yday_move_pts / _d2ago_close * 100 if _d2ago_close > 0 else 0.0
        
        _yday_tr = float(_yday_row["true_range"]) if pd.notna(_yday_row["true_range"]) else max(
            float(_yday_row["high"]) - float(_yday_row["low"]), 
            abs(float(_yday_row["high"]) - _d2ago_close), 
            abs(float(_yday_row["low"]) - _d2ago_close))
            
        _yday_rel_range = _yday_tr / _atr14_live if _atr14_live > 0 else 1.0
        _yday_ce_thr    = max(_yday_ret_pct,  0.0) * _yday_rel_range
        _yday_pe_thr    = max(-_yday_ret_pct, 0.0) * _yday_rel_range
except Exception:
    pass

if threat_mult == 0.0:
    daily_ret_pct = float(sig.get("daily_ret_pct", 0.0))
    rel_range     = float(sig.get("rel_vol",       1.0)) # Backwards compat fallback
    threat_mult   = float(sig.get("threat_mult",   0.0))

ce_threat_mult = max(daily_ret_pct,  0.0) * rel_range
pe_threat_mult = max(-daily_ret_pct, 0.0) * rel_range

spot_now = spot
_spot_is_fallback = False
if spot_now == 0:
    try:
        _fb = get_nifty_daily()
        if _fb is not None and not _fb.empty:
            spot_now = float(_fb["close"].iloc[-1])
            _spot_is_fallback = True
    except Exception:
        pass
src3_pe = src3_ce = 0
pe_sold = ce_sold = 0
drift_pct = 0.0

# ── Rolled positions (already loaded above as _rolled) ───────────────────────
# Strikes come directly from rolled_positions.json — set by EOD job only
_rp_ce = _rolled.get("ce_strike")
_rp_pe = _rolled.get("pe_strike")
_rp_history = _rolled.get("history", [])
# is_rolled: True if there was a mid-cycle roll (history has >1 entry)
_is_rolled = len(_rp_history) > 1

def _moat_pull(m):
    if m >= 4: return 100
    if m >= 3: return 75
    if m >= 2: return 50
    return 0

if tue_anchor_available and tue_close > 0 and spot_now > 0:
    # Strikes from rolled_positions.json; fall back to formula if not set yet
    ce_sold   = int(_rp_ce) if _rp_ce else int(round(tue_close * 1.035 / 50) * 50)
    pe_sold   = int(_rp_pe) if _rp_pe else int(round(tue_close * 0.960 / 50) * 50)
    drift_pct = (spot_now - tue_close) / tue_close * 100
    if   drift_pct >= 3.0: src3_ce = 4
    elif drift_pct >= 2.5: src3_ce = 3
    elif drift_pct >= 2.0: src3_ce = 2
    elif drift_pct >= 1.5: src3_ce = 1
    if   drift_pct <= -3.5: src3_pe = 4
    elif drift_pct <= -3.0: src3_pe = 3
    elif drift_pct <= -2.5: src3_pe = 2
    elif drift_pct <= -2.0: src3_pe = 1

# ── Dynamic Roll Matrix pre-compute ─────────────────────────────────────────
_DEF_THR, _OFF_THR = 2.5, 1.8

if tue_anchor_available and tue_close > 0 and spot_now > 0:
    ce_def_trig_spot = int(round(tue_close * (1 + _DEF_THR / 100) / 50) * 50)
    pe_def_trig_spot = int(round(tue_close * (1 - _DEF_THR / 100) / 50) * 50)
    pe_off_trig_spot = int(round(tue_close * (1 + _OFF_THR / 100) / 50) * 50)
    ce_off_trig_spot = int(round(tue_close * (1 - _OFF_THR / 100) / 50) * 50)

    ce_adverse = max((spot_now - tue_close) / tue_close * 100, 0.0)
    pe_adverse = max((tue_close - spot_now) / tue_close * 100, 0.0)
    pe_favor   = max((spot_now - tue_close) / tue_close * 100, 0.0)
    ce_favor   = max((tue_close - spot_now) / tue_close * 100, 0.0)

    # Book state — pure price, closing basis (displayed intraday as live proxy)
    ce_book_loss   = ce_adverse >= _DEF_THR
    pe_book_loss   = pe_adverse >= _DEF_THR
    ce_book_profit = ce_favor   >= _OFF_THR
    pe_book_profit = pe_favor   >= _OFF_THR

    ce_off_pct, pe_off_pct = 3.5, 4.0
else:
    ce_adverse = pe_adverse = pe_favor = ce_favor = 0.0
    ce_book_loss = pe_book_loss = ce_book_profit = pe_book_profit = False
    ce_def_trig_spot = pe_def_trig_spot = pe_off_trig_spot = ce_off_trig_spot = 0
    ce_off_pct, pe_off_pct = 3.5, 4.0

pe_canary = max(src1_pe, src2_pe, src3_pe)
ce_canary = max(src1_ce, src2_ce, src3_ce)
overall_canary = max(pe_canary, ce_canary, canary)

# ── India VIX ────────────────────────────────────────────────────────────────
vix_current = vix_chg_pct = 0.0
vix_available = vix_rising = False
_vix_is_fallback = False
try:
    from data.live_fetcher import get_india_vix_detail as _get_vix
    vix_current, vix_chg_pct = _get_vix()
    vix_available = vix_current > 0
    vix_rising = vix_chg_pct > 5.0
except Exception:
    pass
if not vix_available:
    _fb_vix = sig.get("vix", 0.0) or 0.0
    if _fb_vix > 0:
        vix_current = _fb_vix
        vix_chg_pct = 0.0
        vix_available = True
        vix_rising = False
        _vix_is_fallback = True

# book states already computed in roll matrix pre-compute above

PE_GREEN = {0:"#14532d", 1:"#15803d", 2:"#16a34a", 3:"#bbf7d0", 4:"#dcfce7"}
CE_RED   = {0:"#b91c1c", 1:"#dc2626", 2:"#ef4444", 3:"#fca5a5", 4:"#fee2e2"}
def _txt(lvl): return "#1e293b" if lvl >= 3 else "white"
BOTH_AMBER = "#d97706"

def _driver(s1, s2, s3):
    if s1 >= s2 and s1 >= s3 and s1 > 0:
        return "Source 1 (EMA Gap)"
    return "Source 2" if s2 >= s3 else "Source 3"

pe_driver = _driver(src1_pe, src2_pe, src3_pe)
ce_driver = _driver(src1_ce, src2_ce, src3_ce)

CANARY_LABEL  = {0: "SINGING", 1: "Canary Day 1", 2: "Canary Day 2",
                 3: "Canary Day 3", 4: "Canary Day 4"}
CANARY_ACTION = {0: "HOLD", 1: "WATCH", 2: "WATCH", 3: "PREPARE", 4: "ACT"}
CANARY_ICON   = {0: "✅", 1: "🟡", 2: "⚠️", 3: "🔴", 4: "🔴"}
CANARY_HEADER_COLOUR = {0: "#d97706", 1: "#d97706", 2: "#d97706", 3: "#ea580c", 4: "#dc2626"}
overall_action = CANARY_ACTION.get(overall_canary, "WATCH")
overall_label  = CANARY_LABEL.get(overall_canary, "Canary Day 4")

_both_singing = (pe_canary == 0 and ce_canary == 0)
_LIGHT_COLS = {"#bbf7d0", "#dcfce7", "#fca5a5", "#fecaca", "#fee2e2"}

def _action_from_table(moats: float, canary_day: int) -> tuple:
    if moats >= 3:
        if canary_day <= 2: return "✅ HOLD",     "success"
        if canary_day == 3: return "👁 WATCH",    "info"
        return                       "⚠️ PREPARE", "warning"
    elif moats >= 2:
        if canary_day <= 1: return "✅ HOLD",     "success"
        if canary_day == 2: return "👁 WATCH",    "info"
        if canary_day == 3: return "⚠️ PREPARE",  "warning"
        return                       "🔴 ACT",     "danger"
    elif moats >= 1:
        if canary_day <= 1: return "👁 WATCH",    "info"
        if canary_day == 2: return "⚠️ PREPARE",  "warning"
        return                       "🔴 ACT",     "danger"
    else:
        if canary_day <= 1: return "⚠️ PREPARE",  "warning"
        return                       "🔴 ACT",     "danger"

action_pe, level_pe = _action_from_table(put_moats,  pe_canary)
action_ce, level_ce = _action_from_table(call_moats, ce_canary)

_severity = {"success": 0, "info": 1, "warning": 2, "danger": 3}
_lvl_col  = {"success":"#16a34a","info":"#0369a1","warning":"#d97706","danger":"#dc2626"}
if _severity.get(level_pe, 0) >= _severity.get(level_ce, 0):
    page_action, page_level, page_driver = action_pe, level_pe, "PE"
else:
    page_action, page_level, page_driver = action_ce, level_ce, "CE"

threatened = ("PE" if "DOWN" in mom_state else
              "CE" if "UP"   in mom_state else
              "Both" if mom_state == "TRANSITIONING" else "Neither")

def _chip(lvl, palette):
    bg = BOTH_AMBER if _both_singing else palette.get(lvl, "#94a3b8")
    tc = "#1e293b" if bg in _LIGHT_COLS else "white"
    return (f"<span style='background:{bg};color:{tc};border-radius:3px;"
            f"padding:2px 6px;font-size:14px;font-weight:700;line-height:1.4;'>D{lvl}</span>")

def _roll_state(bl, bp):
    if bl: return "🔴 BOOK LOSS",   "#b91c1c"
    if bp: return "🟢 BOOK PROFIT", "#0f766e"
    return         "✅ HOLD",        "#1e3a5f"

pe_rs_txt, pe_rs_col = _roll_state(pe_book_loss, pe_book_profit)
ce_rs_txt, ce_rs_col = _roll_state(ce_book_loss, ce_book_profit)

# ══════════════════════════════════════════════════════════════════════════════
# ROLL MATRIX — Defensive Book Loss · Offensive Book Profit
# ══════════════════════════════════════════════════════════════════════════════
show_page_header(spot, signals_ts)

ui.section_header("Roll Matrix",
                  "EOD price-based · Unified anchor · Book Loss ≥2.5% · Book Profit ≥1.8%")

with st.expander("Roll Matrix — Reference", expanded=False):
    st.markdown("""
**Anchor** — Tuesday's EOD close, set by the EOD job at 3:35 PM. Both CE and PE always share the same anchor.

**Entry strikes** (from anchor):
- CE sold at anchor + 3.5% (nearest 50pt)
- PE sold at anchor − 4.0% (nearest 50pt)

---

**BOOK LOSS — drift ≥ 2.5% adverse (EOD closing basis)**

| Direction | Trigger |
|---|---|
| CE LOSS | EOD close ≥ anchor + 2.5% (market moved up) |
| PE LOSS | EOD close ≤ anchor − 2.5% (market moved down) |

Action: New anchor = that day's EOD close. Both CE and PE strikes recalculated.

---

**BOOK PROFIT — drift ≥ 1.8% favorable (EOD closing basis)**

| Direction | Trigger |
|---|---|
| PE PROFIT | EOD close ≥ anchor + 1.8% (PE premium dead, CE still fine) |
| CE PROFIT | EOD close ≤ anchor − 1.8% (CE premium dead, PE still fine) |

Action: Same as loss — new anchor = EOD close, both strikes reset.

---

**Priority:** LOSS events take priority over PROFIT (2.5% adverse implies 1.8% favorable on the other side, but the loss is what drives the roll).

**Cycle:** Starts at Tuesday EOD. History cleared every Tuesday when new anchor is set.
""")

# Define basic DTB strings for the top metrics card (Showing Background Math)
_vix_floor = vix_current if (vix_current and vix_current > 0) else 15.0
_expected_daily_move_pts = (spot_now * (_vix_floor / 100)) / 16

if tue_anchor_available and ce_def_trig_spot > 0 and pe_def_trig_spot > 0:
    _ce_gap_pts = max(0, ce_def_trig_spot - spot_now)
    _pe_gap_pts = max(0, spot_now - pe_def_trig_spot)
    
    _ce_pace = max(_today_move_pts, _expected_daily_move_pts)
    _pe_pace = max(abs(_today_move_pts), _expected_daily_move_pts)
    
    _ce_days_s  = f"{_ce_gap_pts / _ce_pace:.1f}d"
    _pe_days_s  = f"{_pe_gap_pts / _pe_pace:.1f}d"
    _dtb_val    = f"CE {_ce_days_s} · PE {_pe_days_s}"
    
    if _yday_move_pts != 0 and _prev_close_live > 0:
        _yd_cl       = _prev_close_live
        _yd_ce_gap   = max(0, ce_def_trig_spot - _yd_cl)
        _yd_pe_gap   = max(0, _yd_cl - pe_def_trig_spot)
        
        _yd_ce_pace  = max(_yday_move_pts, _expected_daily_move_pts)
        _yd_pe_pace  = max(abs(_yday_move_pts), _expected_daily_move_pts)
        
        _yd_ce_s     = f"{_yd_ce_gap / _yd_ce_pace:.1f}d"
        _yd_pe_s     = f"{_yd_pe_gap / _yd_pe_pace:.1f}d"
        _dtb_sub     = f"Yday CE: {_yd_ce_s} ({_yd_ce_gap:.0f}pt÷{_yd_ce_pace:.0f}pt) · PE: {_yd_pe_s} ({_yd_pe_gap:.0f}pt÷{_yd_pe_pace:.0f}pt)"
    else:
        _dtb_sub = "gap_pts ÷ pace_pts"
    
    # Update Threat Subtitle to show the explicit math
    _thr_sub = f"CE: {max(daily_ret_pct, 0):.2f}% × {rel_range:.2f} RTR · PE: {max(-daily_ret_pct, 0):.2f}% × {rel_range:.2f} RTR"
else:
    _dtb_val = "—"; _dtb_sub = "anchor needed"; _thr_sub = "anchor needed"

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1: ui.metric_card("DTE", f"{dte}",
                         sub="Wed/Thu — std IC" if dte >= 5 else "Fri/Mon/Tue — tight IC")
with c2: ui.metric_card("THREAT MULT", f"CE {ce_threat_mult:.2f} · PE {pe_threat_mult:.2f}",
                         sub=_thr_sub,
                         color="red" if (ce_threat_mult > 1.15 or pe_threat_mult > 1.15) else "green")
with c3: ui.metric_card("ANCHOR CLOSE",
                         f"{tue_close:,.0f}" if tue_anchor_available else "N/A",
                         sub=f"Anchor: {tue_anchor_date}" if tue_anchor_available else "No anchor")
with c4: ui.metric_card("DRIFT FROM ANCHOR",
                         f"{drift_pct:+.2f}%" if tue_anchor_available else "—",
                         sub=f"Spot {spot_now:,.0f}" + (" · prev close" if _spot_is_fallback else ""),
                         color="red" if abs(drift_pct) >= 2.0 else "default")
with c5:
    if vix_available:
        if _vix_is_fallback:
            _vix_interp = "prev close · live N/A"
        else:
            _mkt_up = daily_ret_pct > 0.1
            _mkt_dn = daily_ret_pct < -0.1
            if vix_rising and _mkt_up:
                _vix_interp = "⚠️ VIX↑+mkt↑ → mean revert risk"
            elif vix_rising and _mkt_dn:
                _vix_interp = "🔴 VIX↑+mkt↓ → fall may continue"
            elif not vix_rising and _mkt_up:
                _vix_interp = "✅ VIX↓+mkt↑ → move confirmed"
            elif not vix_rising and _mkt_dn:
                _vix_interp = "⚠️ VIX↓+mkt↓ → complacency"
            else:
                _vix_interp = f"Chg {vix_chg_pct:+.1f}% · stable"
        _vix_color = "red" if vix_current > 20 else "default"
        ui.metric_card("INDIA VIX", f"{vix_current:.2f}",
                        sub=_vix_interp, color=_vix_color)
    else:
        ui.metric_card("INDIA VIX", "N/A", sub="Feed unavailable")
with c6: ui.metric_card("DAYS TO BREACH", _dtb_val,
                         sub=_dtb_sub,
                         color="default")

# ── Threat & DTB daily history table — RTR + VIX-Adjusted (Math UI) ───────────
with st.expander("Threat & DTB — Daily History (VIX & RTR Proxy)", expanded=False):
    try:
        from data.live_fetcher import get_nifty_daily_live as _gdl
        _dlive = _gdl() 
    except Exception:
        _dlive = pd.DataFrame()

    if tue_anchor_available and ce_def_trig_spot > 0 and pe_def_trig_spot > 0 and not _dlive.empty:
        # 1. Vectorized Computation for performance and reliability
        _th = _dlive.copy()
        _th["ret_pct"] = _th["close"].pct_change() * 100
        
        # RTR Proxy logic to prevent Spot Volume NaN errors
        _th["prev_close"] = _th["close"].shift(1)
        _th["tr1"] = _th["high"] - _th["low"]
        _th["tr2"] = (_th["high"] - _th["prev_close"]).abs()
        _th["tr3"] = (_th["low"] - _th["prev_close"]).abs()
        _th["true_range"] = _th[["tr1", "tr2", "tr3"]].max(axis=1)
        
        _atr14_hist = _th["true_range"].rolling(14).mean()
        _th["rel_range"] = np.where(_atr14_hist > 0, _th["true_range"] / _atr14_hist, 1.0)
        
        # 2. VIX-Adjusted Expected Move (Rule of 16)
        _vix_floor = vix_current if (vix_current and vix_current > 0) else 15.0
        _expected_daily_move_pts = (spot_now * (_vix_floor / 100)) / 16
        
        # 3. Compute Threat and Gaps against Active (possibly rolled) Strikes
        _th["ce_thr"] = _th["ret_pct"].clip(lower=0) * _th["rel_range"]
        _th["pe_thr"] = (-_th["ret_pct"]).clip(lower=0) * _th["rel_range"]
        
        _th["ce_gap"] = (ce_def_trig_spot - _th["close"]).clip(lower=0)
        _th["pe_gap"] = (_th["close"] - pe_def_trig_spot).clip(lower=0)
        
        # 4. Filter for Current Expiry Cycle (Wednesday to Tuesday)
        import datetime as _dt
        _now_ist_t = _dt.datetime.now(pytz.timezone("Asia/Kolkata"))
        _today_d   = _now_ist_t.date()
        
        _days_since_wed = (_today_d.weekday() - 2) % 7
        _current_wed    = _today_d - _dt.timedelta(days=_days_since_wed)
        
        _cycle_mask = _th.index.date >= _current_wed
        _th_cycle   = _th[_cycle_mask].copy()
        
        _display_rows = []
        
        # We process ALL rows up to the second-to-last as historical
        _hist_end = len(_th_cycle) - 1
        if _hist_end > 0:
            _th_hist = _th_cycle.iloc[:_hist_end]
            for _idx, _r in _th_hist.iterrows():
                _move = max(abs(_r["close"] - _r["open"]), _expected_daily_move_pts)
                _display_rows.append({
                    "Date":      _idx.strftime("%d %b"),
                    "Ret %":     f"{_r['ret_pct']:+.2f}%",
                    "Rel Rng":   f"{_r['rel_range']:.2f}×",
                    "CE Threat": f"{float(_r['ce_thr']):.2f}  ({max(float(_r['ret_pct']), 0):.2f}% × {_r['rel_range']:.2f})",
                    "PE Threat": f"{float(_r['pe_thr']):.2f}  ({max(float(-_r['ret_pct']), 0):.2f}% × {_r['rel_range']:.2f})",
                    "CE DTB":    f"{_r['ce_gap'] / _move:.1f}d  ({_r['ce_gap']:.0f}pt ÷ {_move:.0f}pt)",
                    "PE DTB":    f"{_r['pe_gap'] / _move:.1f}d  ({_r['pe_gap']:.0f}pt ÷ {_move:.0f}pt)",
                })

        # 5. Latest Session Row with Background Math
        if len(_th_cycle) > 0:
            _ce_pace = max(_today_move_pts, _expected_daily_move_pts)
            _pe_pace = max(abs(_today_move_pts), _expected_daily_move_pts)
            
            _last_dt = _th_cycle.index[-1].date() if hasattr(_th_cycle.index[-1], 'date') else _th_cycle.index[-1].to_pydatetime().date()
            _is_actual_today = (_last_dt == _now_ist_t.date())
            _row_label = "LIVE ▶" if _is_actual_today else f"{_last_dt.strftime('%d %b')} (Latest)"
            
            _display_rows.append({
                "Date":      _row_label,
                "Ret %":     f"{daily_ret_pct:+.2f}%",
                "Rel Rng":   f"{rel_range:.2f}×",
                "CE Threat": f"{ce_threat_mult:.2f}  ({max(daily_ret_pct, 0):.2f}% × {rel_range:.2f})",
                "PE Threat": f"{pe_threat_mult:.2f}  ({max(-daily_ret_pct, 0):.2f}% × {rel_range:.2f})",
                "CE DTB":    f"{_ce_gap_pts / _ce_pace:.1f}d  ({_ce_gap_pts:.0f}pt ÷ {_ce_pace:.0f}pt)",
                "PE DTB":    f"{_pe_gap_pts / _pe_pace:.1f}d  ({_pe_gap_pts:.0f}pt ÷ {_pe_pace:.0f}pt)",
            })
        
        _tbl = pd.DataFrame(list(reversed(_display_rows)))

        # 6. Heatmap Styling (Extracts the number securely from the background math string)
        def _style_urgent(row):
            styles = [""] * len(row)
            try:
                for i, col in [(5, "CE DTB"), (6, "PE DTB")]:
                    if float(str(row[col]).split("d")[0]) < 2.0: 
                        styles[i] = "background-color:#7f1d1d;color:white;font-weight:700"
                if float(str(row["CE Threat"]).split()[0]) > 1.15: styles[3] = "color:#ef4444;font-weight:700"
                if float(str(row["PE Threat"]).split()[0]) > 1.15: styles[4] = "color:#ef4444;font-weight:700"
            except: pass
            return styles

        if not _tbl.empty:
            st.dataframe(_tbl.style.apply(_style_urgent, axis=1), hide_index=True, use_container_width=True)
            st.caption(f"Cycle Start: {_current_wed.strftime('%d %b')} | Active Trigger: CE {ce_def_trig_spot:,} · PE {pe_def_trig_spot:,}")
        else:
            st.info(f"Cycle starting {_current_wed.strftime('%d %b')} has no trading data yet.")
    else:
        st.info("RTR & VIX history requires an active Expiry Anchor.")


if not tue_anchor_available:
    import datetime as _dtnow, pytz as _pynow
    _ist_now2 = _dtnow.datetime.now(_pynow.timezone("Asia/Kolkata"))
    _pre_mkt  = _ist_now2.hour * 60 + _ist_now2.minute < 9 * 60 + 15
    if _pre_mkt:
        st.info("⏳ Pre-market: Kite historical data not available yet. "
                "Open **Home** page once after 9:15 AM — anchor will persist for all future sessions.")
    else:
        st.warning("⚠️ Expiry anchor unavailable. Click ↻ refresh to reload data.")
else:
    # ── Entry / rolled strike card ────────────────────────────────────────────
    _card_title = "ENTRY STRIKES" + (" · ROLLED" if _is_rolled else "")
    _last_roll  = _rp_history[-1] if _rp_history else {}
    _roll_note  = (f"🔄 {_last_roll.get('event','?')} on {_last_roll.get('date','?')} · "
                   f"anchor {_last_roll.get('old_anchor',0):,.0f} → {_last_roll.get('new_anchor',0):,.0f}"
                   if _is_rolled else "")

    st.markdown(
        f"<div style='background:#0f172a;border-radius:10px;padding:12px 16px;"
        f"border:1px solid #1e293b;margin-bottom:10px;'>"
        f"<div style='font-size:13px;font-weight:700;color:#94a3b8;"
        f"letter-spacing:1.5px;margin-bottom:8px;'>{_card_title}</div>"
        + (f"<div style='font-size:12px;color:#fbbf24;margin-bottom:8px;'>{_roll_note}</div>"
           if _roll_note else "")
        + f"<div style='display:flex;gap:16px;flex-wrap:wrap;'>"
        f"<div>"
        f"<span style='font-size:14px;color:#94a3b8;'>PE SOLD </span>"
        f"<span style='font-size:20px;font-weight:900;color:{'#fbbf24' if _is_rolled else '#16a34a'};'>"
        f"{pe_sold:,}</span>"
        f"<div style='font-size:13px;color:#94a3b8;margin-top:2px;'>"
        f"anchor {tue_close:,.0f} − 4.0%</div></div>"
        f"<div>"
        f"<span style='font-size:14px;color:#94a3b8;'>CE SOLD </span>"
        f"<span style='font-size:20px;font-weight:900;color:{'#fbbf24' if _is_rolled else '#dc2626'};'>"
        f"{ce_sold:,}</span>"
        f"<div style='font-size:13px;color:#94a3b8;margin-top:2px;'>"
        f"anchor {tue_close:,.0f} + 3.5%</div></div>"
        f"</div></div>",
        unsafe_allow_html=True)

    # ── Cycle history card ────────────────────────────────────────────────────
    if _rp_history:
        _EV_LABEL = {
            "EXPIRY_ANCHOR": ("📅 EXPIRY ANCHOR", "#1e3a5f"),
            "CE_LOSS":       ("🔴 CE BOOK LOSS",  "#7f1d1d"),
            "PE_LOSS":       ("🔴 PE BOOK LOSS",  "#7f1d1d"),
            "CE_PROFIT":     ("🟢 CE BOOK PROFIT","#0f766e"),
            "PE_PROFIT":     ("🟢 PE BOOK PROFIT","#0f766e"),
        }
        _hist_rows = ""
        for _he in reversed(_rp_history):
            _el, _ec = _EV_LABEL.get(_he.get("event",""), ("?", "#334155"))
            _old_a   = _he.get("old_anchor")
            _anc_str = (f"{_old_a:,.0f} → {_he.get('new_anchor',0):,.0f}"
                        if _old_a else f"{_he.get('new_anchor',0):,.0f} (new cycle)")
            _hist_rows += (
                f"<div style='display:flex;gap:10px;align-items:center;padding:7px 10px;"
                f"border-radius:6px;background:{_ec}22;margin:3px 0;border-left:3px solid {_ec};'>"
                f"<span style='font-size:13px;font-weight:700;color:#e2e8f0;min-width:90px;'>"
                f"{_he.get('date','?')}</span>"
                f"<span style='font-size:13px;font-weight:700;color:{_ec};min-width:150px;'>{_el}</span>"
                f"<span style='font-size:13px;color:#94a3b8;'>Anchor {_anc_str}</span>"
                f"<span style='font-size:13px;color:#64748b;margin-left:auto;'>"
                f"CE {_he.get('new_ce',0):,} · PE {_he.get('new_pe',0):,}</span>"
                f"</div>"
            )
        st.markdown(
            f"<div style='background:#0f172a;border-radius:10px;padding:12px 16px;"
            f"border:1px solid #1e293b;margin-bottom:10px;'>"
            f"<div style='font-size:12px;font-weight:700;color:#94a3b8;"
            f"letter-spacing:1.5px;margin-bottom:8px;'>CYCLE HISTORY · {tue_anchor_date}</div>"
            + _hist_rows + "</div>",
            unsafe_allow_html=True)
    def _side_card(side_tag, palette, book_loss, book_profit, adverse, favor,
                   def_trig_spot, off_trig_spot, is_ce):
        if book_loss:
            bg     = palette[0]
            state  = "🔴 BOOK LOSS"
            action = f"EOD close crossed {_DEF_THR}% adverse · Roll BOTH strikes from new anchor"
        elif book_profit:
            bg     = "#0f766e"
            state  = "🟢 BOOK PROFIT"
            action = f"EOD close crossed {_OFF_THR}% favorable · Roll BOTH strikes from new anchor"
        else:
            bg     = palette[4] if adverse < 0.5 and favor < 0.5 else palette[3]
            state  = "✅ HOLD"
            action = (f"Loss trig {def_trig_spot:,} ({_DEF_THR - adverse:.2f}% away) · "
                      f"Profit trig {off_trig_spot:,} ({_OFF_THR - favor:.2f}% away)")

        txt_col  = "#1e293b" if bg in _LIGHT_COLS else "white"
        adv_str  = f"{adverse:.2f}% {'above' if is_ce else 'below'} anchor"
        fav_str  = f"{favor:.2f}%  {'below' if is_ce else 'above'} anchor"
        vix_line = ""
        if vix_available and vix_rising:
            if is_ce:
                vix_line = (f"<div style='margin-top:6px;padding:4px 8px;border-radius:4px;"
                            f"background:rgba(0,0,0,0.25);color:#fef08a;font-size:13px;font-weight:700;'>"
                            f"⚠️ VIX RISING {vix_chg_pct:+.1f}% — up moves may revert</div>")
            else:
                vix_line = (f"<div style='margin-top:6px;padding:4px 8px;border-radius:4px;"
                            f"background:rgba(0,0,0,0.25);color:#bfdbfe;font-size:13px;font-weight:700;'>"
                            f"🔵 VIX RISING {vix_chg_pct:+.1f}% — fear-driven move</div>")
        st.markdown(
            f"<div style='background:{bg};border-radius:10px;padding:14px 16px;margin-bottom:8px;'>"
            f"<div style='color:{txt_col};font-size:13px;font-weight:700;opacity:0.8;letter-spacing:1px;'>"
            f"{side_tag}</div>"
            f"<div style='color:{txt_col};font-size:20px;font-weight:900;margin:4px 0 6px;'>{state}</div>"
            f"<div style='color:{txt_col};font-size:12px;opacity:0.9;margin-bottom:8px;'>{action}</div>"
            f"<div style='background:rgba(0,0,0,0.18);border-radius:6px;padding:8px 10px;"
            f"font-size:13px;color:{txt_col};'>"
            f"Adverse {adv_str} · Favorable {fav_str}"
            f"</div>" + vix_line + f"</div>",
            unsafe_allow_html=True)

    col_ce, col_pe = st.columns(2)
    with col_ce:
        _side_card("CE · CALL SIDE", CE_RED,
                   ce_book_loss, ce_book_profit, ce_adverse, ce_favor,
                   ce_def_trig_spot, ce_off_trig_spot, is_ce=True)
    with col_pe:
        _side_card("PE · PUT SIDE", PE_GREEN,
                   pe_book_loss, pe_book_profit, pe_adverse, pe_favor,
                   pe_def_trig_spot, pe_off_trig_spot, is_ce=False)

    # ── Strike-Path Corridor ──────────────────────────────────────────────────
    if ema_vals and spot_now > 0 and tue_anchor_available:
        _all_emas = [(p, float(v)) for p, v in ema_vals.items() if v and float(v) > 0]
        _anc      = float(tue_close)
        _pct_anc  = lambda v: (float(v) - _anc) / _anc * 100 if _anc > 0 else 0

        _ce_items = [("ANCHOR", _anc, "neutral"), ("CMP", float(spot_now), "cmp")]
        if ce_def_trig_spot > 0:
            _ce_items.append(("BOOK LOSS",   float(ce_def_trig_spot), "book_loss"))
        if ce_off_trig_spot > 0:
            _ce_items.append(("BOOK PROFIT", float(ce_off_trig_spot), "book_profit"))
        if ce_sold > 0:
            for p, v in _all_emas:
                if spot_now < v < ce_sold:
                    _ce_items.append((f"🧱 EMA{p}", v, "above"))
            _ce_moat_count = sum(1 for _, v, k in _ce_items if k == "above")
            _ce_note = f"{_ce_moat_count} moat{'s' if _ce_moat_count!=1 else ''}" if _ce_moat_count else "PATH CLEAR ⚠️"
            _ce_items.append((f"CE SOLD {ce_sold:,}", float(ce_sold), "sold_ce"))
        else:
            _ce_moat_count, _ce_note = 0, ""

        _pe_items = [("ANCHOR", _anc, "neutral"), ("CMP", float(spot_now), "cmp")]
        if pe_def_trig_spot > 0:
            _pe_items.append(("BOOK LOSS",   float(pe_def_trig_spot), "book_loss"))
        if pe_off_trig_spot > 0:
            _pe_items.append(("BOOK PROFIT", float(pe_off_trig_spot), "book_profit"))
        if pe_sold > 0:
            for p, v in _all_emas:
                if pe_sold < v < spot_now:
                    _pe_items.append((f"🧱 EMA{p}", v, "below"))
            _pe_moat_count = sum(1 for _, v, k in _pe_items if k == "below")
            _pe_note = f"{_pe_moat_count} moat{'s' if _pe_moat_count!=1 else ''}" if _pe_moat_count else "PATH CLEAR ⚠️"
            _pe_items.append((f"PE SOLD {pe_sold:,}", float(pe_sold), "sold_pe"))
        else:
            _pe_moat_count, _pe_note = 0, ""

        _KIND_BG = {
            "neutral":     ("#334155", "white"),
            "cmp":         ("#3b82f6", "white"),
            "above":       ("#fbcfe8", "#831843"),
            "below":       ("#bbf7d0", "#14532d"),
            "sold_ce":     ("#1e293b", "white"),
            "sold_pe":     ("#1e293b", "white"),
            "book_loss":   ("#7f1d1d", "white"),
            "book_profit": ("#0f766e", "white"),
        }

        def _render_vc(title, items):
            items_desc = sorted(items, key=lambda x: x[1], reverse=True)
            html = (f"<div style='background:#0f172a;border-radius:10px;padding:16px;"
                    f"border:1px solid #1e293b;'>")
            html += (f"<div style='font-size:15px;font-weight:700;color:#94a3b8;"
                     f"margin-bottom:16px;letter-spacing:1px;'>{title}</div>")
            for lbl, val, kind in items_desc:
                bg, txt = _KIND_BG.get(kind, ("#334155", "white"))
                is_spot = kind == "cmp"
                border = "border:2px solid #60a5fa;" if is_spot else "border:1px solid rgba(255,255,255,0.1);"
                margin = "margin:12px 0;" if is_spot else "margin:4px 0;"
                pct = _pct_anc(val)
                pct_str = f"{pct:+.2f}% anchor" if kind != "cmp" else "—"
                html += (f"<div style='background:{bg};color:{txt};padding:10px 14px;"
                         f"border-radius:6px;{border}{margin}display:flex;"
                         f"justify-content:space-between;align-items:center;'>")
                html += f"<span style='font-weight:700;font-size:14px;'>{lbl}</span>"
                html += f"<div style='text-align:right;'>"
                html += f"<div style='font-weight:900;font-size:16px;'>{val:,.0f}</div>"
                html += f"<div style='font-size:11px;opacity:0.8;'>{pct_str}</div>"
                html += "</div></div>"
            html += "</div>"
            return html

        _corr_col1, _corr_col2 = st.columns(2)
        with _corr_col1:
            st.markdown(_render_vc("📈 CE STRIKE-PATH CORRIDOR (Overhead)", _ce_items), unsafe_allow_html=True)
        with _corr_col2:
            st.markdown(_render_vc("📉 PE STRIKE-PATH CORRIDOR (Downside)", _pe_items), unsafe_allow_html=True)

    _off_rule = f"{'Wed/Thu' if dte >= 5 else 'Fri/Mon/Tue'} · CE +{ce_off_pct}% / PE −{pe_off_pct}% from spot"
    st.caption(
        f"Anchor {tue_close:,.0f} · Spot {spot_now:,.0f} · Drift {drift_pct:+.2f}% · "
        f"Threat CE {ce_threat_mult:.2f} · PE {pe_threat_mult:.2f} · VIX {vix_current:.2f} · {_off_rule}"
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# CANARY SOURCES — diagnostic layer
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Canary Sources",
                  "Diagnostic — see exactly which source is driving the signal and why")

_vc_lvl  = max(pe_canary, ce_canary)
_vc_col  = CANARY_HEADER_COLOUR.get(_vc_lvl, "#94a3b8")

_pe_lbl = f"PE · D{pe_canary}" if pe_canary > 0 else "PE · Clear"
_ce_lbl = f"CE · D{ce_canary}" if ce_canary > 0 else "CE · Clear"
_pe_col = CANARY_HEADER_COLOUR.get(pe_canary, "#16a34a") if pe_canary > 0 else "#16a34a"
_ce_col = CANARY_HEADER_COLOUR.get(ce_canary, "#16a34a") if ce_canary > 0 else "#16a34a"
_act    = CANARY_ACTION.get(_vc_lvl, "WATCH")

if _vc_lvl == 0:
    _detail_line = f"EMA Gap D{src1} · Momentum {mom_score:+.1f}% · Drift {drift_pct:+.2f}% — all quiet"
    _detail_col  = "#16a34a"
else:
    _vc_drv = ce_driver if ce_canary >= pe_canary else pe_driver
    _detail_line = (f"{_vc_drv} · {skew_label}"
                    + (f" · {gap_pct:.0f}% ATR gap" if "Source 1" in _vc_drv else
                       f" · score {mom_score:+.1f}% ATR" if "Source 2" in _vc_drv else
                       f" · drift {drift_pct:+.2f}%"))
    _detail_col  = _vc_col

_ic_entry_map = {
    "STRONG_BULL":     "1:2 CE further",
    "BULL_COMPRESSED": "1:2 CE further",
    "INSIDE_BULL":     "1:1 Symmetric",
    "RECOVERING":      "1:1 Symmetric",
    "INSIDE_BEAR":     "1:1 Symmetric",
    "BEAR_COMPRESSED": "2:1 PE further",
    "STRONG_BEAR":     "2:1 PE further",
}
_ic_entry      = _ic_entry_map.get(_entry_regime, "1:1 Symmetric")
_ic_now        = skew_label
_ic_changed    = _ic_entry != _ic_now
_ic_entry_col  = "#475569"
_ic_now_col    = "#dc2626" if skew_forced else "#16a34a" if not _ic_changed else "#d97706"

st.markdown(
    f"<div style='border-left:4px solid {_vc_col};padding:10px 16px;border-radius:0 6px 6px 0;"
    f"background:{_vc_col}18;margin-bottom:10px;'>"
    f"<div style='font-size:12px;font-weight:700;color:{_vc_col};margin-bottom:6px;'>VERDICT</div>"
    f"<div style='display:flex;gap:16px;align-items:center;margin-bottom:6px;'>"
    f"<span style='font-size:15px;font-weight:800;color:{_pe_col};'>{_pe_lbl}</span>"
    f"<span style='font-size:13px;color:#94a3b8;'>·</span>"
    f"<span style='font-size:15px;font-weight:800;color:{_ce_col};'>{_ce_lbl}</span>"
    f"<span style='font-size:13px;color:#94a3b8;'>→</span>"
    f"<span style='font-size:15px;font-weight:900;color:{_vc_col};'>{_act}</span>"
    f"</div>"
    f"<div style='font-size:13px;color:{_detail_col};margin-bottom:6px;'>{_detail_line}</div>"
    f"<div style='font-size:13px;'>"
    f"<span style='color:{_ic_entry_col};'>IC Shape · Entry: {_ic_entry} ({_entry_regime})</span>"
    f"<span style='color:#94a3b8;'> → </span>"
    f"<span style='color:{_ic_now_col};font-weight:700;'>Now: {_ic_now}</span>"
    f"</div>"
    f"</div>", unsafe_allow_html=True)

with st.expander("IC Shape — Reference Rules", expanded=False):
    st.markdown("""
| Entry Regime | IC Shape at Entry | Why |
|---|---|---|
| STRONG_BULL | 1:2 CE further out | Bull trend — CE side has more buffer needed |
| BULL_COMPRESSED | 1:2 CE further out | Compressed but bullish — protect CE side |
| INSIDE_BULL | 1:1 Symmetric | Inside range, mild bull — balanced |
| RECOVERING | 1:1 Symmetric | Trend unclear — stay symmetric |
| INSIDE_BEAR | 1:1 Symmetric | Inside range, mild bear — balanced |
| BEAR_COMPRESSED | 2:1 PE further out | Compressed but bearish — protect PE side |
| STRONG_BEAR | 2:1 PE further out | Bear trend — PE side has more buffer needed |

**Now (live skew):**
| Signal | Shape Override |
|---|---|
| S1 Gap ≥ D4 | EXIT threatened side |
| S1 Gap = D3 | REDUCE threatened side |
| S1 Gap = D2 | 1:1 Forced (flatten skew) |
| S1 BULL, S2 BULL | 2:1 PE heavy (sell more puts) |
| S1 BEAR, S2 BEAR | 1:2 CE heavy (sell more calls) |
| No directional signal | 1:1 Balanced |

*Entry shape is locked from the regime at entry. Live shape is driven by S1+S2 momentum.*
""")

src_data = [
    {
        "source": "Source 1 — EMA3/EMA8 Gap (Live)",
        "what":   (f"Gap: {gap_pts:.0f} pts ({gap_pct:.1f}% ATR) · "
                   f"EMA3 {'>' if can_dir_live=='BULL' else '<'} EMA8 · "
                   f"{'CE side threatened · PE D0' if can_dir_live=='BULL' else 'PE side threatened · CE D0'}"),
        "pe_lvl": src1_pe, "ce_lvl": src1_ce,
        "detail": (f"EMA3: {e3:,.0f}  |  EMA8: {e8:,.0f}\n"
                   f"Gap: {gap_pts:.0f} pts = {gap_pct:.1f}% of ATR14 ({atr14:.0f})\n"
                   f"Direction: EMA3 {'>' if can_dir_live=='BULL' else '<'} EMA8 "
                   f"→ {'CE threatened · PE always D0' if can_dir_live=='BULL' else 'PE threatened · CE always D0'}\n"
                   f"Threatened side:  >55%=D4  ·  35–55%=D3  ·  15–35%=D2  ·  5–15%=D1  ·  ≤5%=D0\n"
                   f"Safe side: always D0"),
    },
    {
        "source":     "Source 2 — Momentum Score (% of ATR/day)",
        "what":       f"Score: {mom_score:+.1f}% of ATR/day · IC Shape: {skew_label}",
        "pe_lvl":     src2_pe, "ce_lvl": src2_ce,
        "pe_col":     src2_pe_col, "ce_col": src2_ce_col,
        "detail":     (f"EMA3 slope: {ema3_slope:+.1f} pts/day  (60% weight)\n"
                       f"EMA8 slope: {ema8_slope:+.1f} pts/day  (40% weight)\n"
                       f"Combined score: {mom_score:+.1f}% of ATR/day\n"
                       f"Bullish → CE only:  >+32%=D4  ·  +20–32%=D3  ·  +11–20%=D2  ·  +5–11%=D1  (PE always D0)\n"
                       f"Flat zone: ±5% = both Day 0\n"
                       f"Bearish → PE only:  <-32%=D4  ·  -20–32%=D3  ·  -11–20%=D2  ·  -5–11%=D1  (CE always D0)"),
        "skew_label": skew_label, "skew_note": skew_note, "skew_col": skew_col,
    },
    {
        "source": "Source 3 — Spot Drift from Expiry Close",
        "what":   (f"Drift: {drift_pct:+.2f}% from expiry close · PE sold {pe_sold:,} · CE sold {ce_sold:,}"
                   if tue_anchor_available else "Expiry anchor not yet available"),
        "pe_lvl": src3_pe, "ce_lvl": src3_ce,
        "detail": ((f"Expiry close: {tue_close:,.0f}  ({tue_anchor_date})\n"
                    f"PE sold at −4.0% → {pe_sold:,}  |  CE sold at +3.5% → {ce_sold:,}\n"
                    f"Drift from expiry: {drift_pct:+.2f}%\n"
                    f"PE triggers:  −2.0% = D1  ·  −2.5% = D2  ·  −3.0% = D3  ·  −3.5% = D4\n"
                    f"CE triggers:  +1.5% = D1  ·  +2.0% = D2  ·  +2.5% = D3  ·  +3.0% = D4")
                   if tue_anchor_available else "No expiry anchor available."),
    },
]

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
        f"<div style='color:{txt};font-size:12px;font-weight:700;opacity:0.85;'>{label}</div>"
        f"<div style='color:{txt};font-size:15px;font-weight:900;margin:2px 0;'>{icon} {lbl}</div>"
        f"</div>", unsafe_allow_html=True)

for s in src_data:
    with st.expander(
            f"{s['source']} — "
            f"PE: {CANARY_LABEL.get(s['pe_lvl'],'—')} | CE: {CANARY_LABEL.get(s['ce_lvl'],'—')}",
            expanded=False):
        st.markdown(f"<small style='color:#334155;'>{s['what']}</small>", unsafe_allow_html=True)
        st.markdown(f"<pre style='font-size:13px;color:#334155;margin-bottom:8px;'>{s['detail']}</pre>",
                    unsafe_allow_html=True)
        if "Source 3" in s["source"] and tue_anchor_available:
            st.caption(f"Anchor: {tue_anchor_date} · close {tue_close:,.0f} · "
                       f"PE sold {pe_sold:,} · CE sold {ce_sold:,}")
        _src_card("PE · PUT SIDE",  s["pe_lvl"], PE_GREEN, s.get("pe_col"))
        _src_card("CE · CALL SIDE", s["ce_lvl"], CE_RED,   s.get("ce_col"))
        if "skew_label" in s:
            sc = s["skew_col"]
            st.markdown(
                f"<div style='margin-top:4px;padding:8px 14px;border-radius:6px;"
                f"background:{sc}18;border-left:3px solid {sc};'>"
                f"<span style='font-size:14px;font-weight:700;color:{sc};'>"
                f"IC SHAPE · {s['skew_label']}</span>"
                f"<span style='font-size:13px;color:#334155;'> — {s['skew_note']}</span>"
                f"</div>", unsafe_allow_html=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# REFERENCES — collapsed by default
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("Hold / Act Table — Moats × Canary Day", expanded=False):
    ref_rows = [
        ["3–4 moats", "Day 0–2", "HOLD",    "Structure intact — comfortable"],
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
    st.dataframe(pd.DataFrame(ref_rows, columns=["Moats", "Canary Day", "Action", "Note"]),
                 width="stretch", hide_index=True)
    st.caption("Applied per side independently. More severe of PE/CE = page recommendation.")

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

# ── Live Cluster State ────────────────────────────────────────────────────────
if e3 and e8 and e16 and e30 and spot > 0:
    _fast_lo, _fast_hi = min(e3, e8),   max(e3, e8)
    _slow_lo, _slow_hi = min(e16, e30), max(e16, e30)
    _fast_above_slow   = _fast_lo > _slow_hi
    _fast_below_slow   = _fast_hi < _slow_lo

    if _fast_above_slow:
        _gap = _fast_lo - _slow_hi
    elif _fast_below_slow:
        _gap = _slow_lo - _fast_hi
    else:
        _gap = -(max(_fast_lo, _slow_lo) - min(_fast_hi, _slow_hi))

    _gap_lbl = ("WIDE"      if _gap > 150 else
                "NARROW"    if _gap > 30  else
                "TIGHT"     if _gap >= 0  else
                "ENTANGLED")
    _gap_col = ("#16a34a" if _gap > 150 else
                "#d97706" if _gap > 30  else
                "#ea580c" if _gap >= 0  else
                "#dc2626")

    _spot_v      = float(spot)
    _gap_cmp_pct = (_gap / _spot_v * 100) if _spot_v > 0 else 0
    _gap_atr_pct = (_gap / atr14   * 100) if atr14   > 0 else 0
    _gap_pct_str = f"{_gap_cmp_pct:.2f}% CMP · {_gap_atr_pct:.0f}% ATR"

    _fast_slope  = (ema3_slope + ema8_slope) / 2
    _slope_arrow = "▲" if _fast_slope > 5 else "▼" if _fast_slope < -5 else "→"
    _slope_col   = "#16a34a" if _fast_slope > 5 else "#dc2626" if _fast_slope < -5 else "#94a3b8"
    _slope_lbl   = f"{_slope_arrow} {abs(_fast_slope):.0f} pts/day"

    _converging  = ((_fast_above_slow and _fast_slope < 0) or
                    (_fast_below_slow and _fast_slope > 0) or
                    (not _fast_above_slow and not _fast_below_slow))
    if _converging and abs(_fast_slope) > 1 and _gap > 0:
        _days_to_cross = int(_gap / abs(_fast_slope))
        _cross_note    = f"~{_days_to_cross}d to touch"
        _cross_col     = "#dc2626" if _days_to_cross <= 2 else "#ea580c" if _days_to_cross <= 5 else "#d97706"
    else:
        _cross_note = "Diverging" if not _converging and _gap > 0 else ""
        _cross_col  = "#16a34a"

    if _spot_v > _fast_hi:
        _spot_pos = f"Above fast (+{_spot_v - _fast_hi:.0f} pts)"
    elif _spot_v >= _fast_lo:
        _spot_pos = "Inside fast cluster"
    elif _spot_v > _slow_hi:
        _spot_pos = "Between clusters"
    elif _spot_v >= _slow_lo:
        _spot_pos = "Inside slow cluster"
    else:
        _spot_pos = f"Below slow (−{_slow_lo - _spot_v:.0f} pts)"

    _regime_changed = (_entry_regime != regime)
    _entry_reg_col  = {"STRONG_BULL":"#16a34a","BULL_COMPRESSED":"#15803d","INSIDE_BULL":"#0369a1",
                       "RECOVERING":"#d97706","INSIDE_BEAR":"#ea580c","BEAR_COMPRESSED":"#dc2626",
                       "STRONG_BEAR":"#b91c1c"}.get(_entry_regime, "#64748b")
    _reg_ic   = {"STRONG_BULL":"1:2","BULL_COMPRESSED":"1:2","INSIDE_BULL":"1:1",
                 "RECOVERING":"1:1","INSIDE_BEAR":"1:1","BEAR_COMPRESSED":"2:1",
                 "STRONG_BEAR":"2:1"}.get(regime, "1:1")
    _reg_sz   = {"STRONG_BULL":"100%","BULL_COMPRESSED":"75%","INSIDE_BULL":"75%",
                 "RECOVERING":"75%","INSIDE_BEAR":"50%","BEAR_COMPRESSED":"75%",
                 "STRONG_BEAR":"63%"}.get(regime, "75%")
    _reg_col2 = {"STRONG_BULL":"#16a34a","BULL_COMPRESSED":"#15803d","INSIDE_BULL":"#0369a1",
                 "RECOVERING":"#d97706","INSIDE_BEAR":"#ea580c","BEAR_COMPRESSED":"#dc2626",
                 "STRONG_BEAR":"#b91c1c"}.get(regime, "#64748b")

    st.markdown(
        f"<div style='background:#0f172a;border-radius:10px;padding:14px 16px;"
        f"border:1px solid #1e293b;margin-top:10px;'>"
        f"<div style='font-size:13px;font-weight:700;color:#94a3b8;"
        f"letter-spacing:1.5px;margin-bottom:10px;'>LIVE CLUSTER STATE</div>"
        f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;'>"
        f"<div style='background:#1e293b;border-radius:6px;padding:8px 10px;'>"
        f"<div style='font-size:13px;color:#94a3b8;margin-bottom:3px;'>SHORT-TERM MOMENTUM · EMA3 – EMA8</div>"
        f"<div style='font-size:13px;font-weight:700;color:#e2e8f0;'>{_fast_lo:,.0f} – {_fast_hi:,.0f}</div>"
        f"<div style='font-size:13px;color:{_slope_col};margin-top:2px;'>"
        f"Slope {_slope_lbl} · width {_fast_hi-_fast_lo:.0f} pts</div></div>"
        f"<div style='background:#1e293b;border-radius:6px;padding:8px 10px;'>"
        f"<div style='font-size:13px;color:#94a3b8;margin-bottom:3px;'>INTERMEDIATE TREND · EMA16 – EMA30</div>"
        f"<div style='font-size:13px;font-weight:700;color:#e2e8f0;'>{_slow_lo:,.0f} – {_slow_hi:,.0f}</div>"
        f"<div style='font-size:13px;color:#94a3b8;margin-top:2px;'>"
        f"Spot: {_spot_pos} · width {_slow_hi-_slow_lo:.0f} pts</div></div>"
        f"</div>"
        f"<div style='background:#1e293b;border-radius:6px;padding:8px 12px;margin-bottom:8px;'>"
        f"<div style='display:flex;align-items:center;gap:12px;flex-wrap:wrap;'>"
        f"<div>"
        f"<span style='font-size:14px;color:#94a3b8;'>Gap </span>"
        f"<span style='font-size:22px;font-weight:900;color:{_gap_col};'>{_gap:+.0f} pts</span>"
        f"<span style='font-size:12px;font-weight:700;color:{_gap_col};margin-left:6px;'>{_gap_lbl}</span>"
        f"<span style='font-size:13px;color:#94a3b8;margin-left:8px;'>{_gap_pct_str}</span>"
        f"</div>"
        + (f"<div style='font-size:14px;font-weight:700;color:{_cross_col};'>{_cross_note}</div>"
           if _cross_note else "")
        + f"</div></div>"
        f"<div style='display:flex;gap:6px;flex-wrap:wrap;align-items:center;'>"
        + (f"<div style='background:{_entry_reg_col}33;border:1px solid {_entry_reg_col}66;"
           f"border-radius:5px;padding:4px 10px;'>"
           f"<span style='color:{_entry_reg_col};font-size:14px;font-weight:700;'>"
           f"ENTRY: {_entry_regime}</span></div>"
           f"<span style='color:#94a3b8;font-size:14px;'>→</span>"
           if _regime_changed else "")
        + f"<div style='background:{_reg_col2};border-radius:5px;padding:4px 10px;'>"
        f"<span style='color:white;font-size:12px;font-weight:700;'>"
        + ("NOW: " if _regime_changed else "") + f"{regime}</span></div>"
        + (f"<div style='background:#7c2d12;border-radius:5px;padding:4px 10px;'>"
           f"<span style='color:#fca5a5;font-size:14px;font-weight:700;'>"
           f"⚠️ REGIME CHANGED</span></div>" if _regime_changed else "")
        + f"<div style='background:#1e293b;border-radius:5px;padding:4px 10px;'>"
        f"<span style='color:#e2e8f0;font-size:12px;font-weight:700;'>"
        + f"{_reg_ic.split(':')[0]}CE : {_reg_ic.split(':')[1]}PE"
        + f"</span></div>"
        f"<div style='background:#1e293b;border-radius:5px;padding:4px 10px;'>"
        f"<span style='color:#e2e8f0;font-size:12px;font-weight:700;'>Size {_reg_sz}</span></div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True)

    with st.expander("Live Cluster State — Reference", expanded=False):
        st.markdown(
            "**Clusters**\n\n"
            "- **SHORT-TERM MOMENTUM (EMA3 – EMA8):** The fast cluster. "
            "EMA3 is the most reactive; EMA8 smooths it. "
            "When EMA3 > EMA8, short-term momentum is bullish. "
            "The slope (pts/day) shows how fast the cluster is moving.\n"
            "- **INTERMEDIATE TREND (EMA16 – EMA30):** The slow cluster. "
            "Represents the weekly/fortnightly trend. "
            "When the fast cluster is above it, the trend is bullish. "
            "When fast is below it, the trend is bearish.\n\n"
            "---\n\n"
            "**Gap labels** — distance in points between the two clusters:\n\n"
            "| Label | Gap | Meaning |\n"
            "|-------|-----|----------|\n"
            "| WIDE | > 150 pts | Clusters well separated — trend firmly established |\n"
            "| NARROW | 30–150 pts | Gap closing — convergence underway, watch for cross |\n"
            "| TIGHT | 0–30 pts | Nearly overlapping — inflection zone, cross imminent |\n"
            "| ENTANGLED | negative | Clusters overlapping — no clear trend |\n\n"
            "---\n\n"
            "**Cross proximity** — based on fast cluster slope direction:\n\n"
            "- **Diverging** — fast slope moving *away* from slow cluster. "
            "Gap is widening. Trend strengthening in its current direction.\n"
            "- **~Xd to touch** — fast slope moving *toward* slow cluster at current pace. "
            "Days until clusters touch. ≤ 2d = red (imminent) · ≤ 5d = orange (near) · > 5d = amber (watch).\n\n"
            "Converging triggers when: fast above slow and slope falling, "
            "OR fast below slow and slope rising, OR clusters already entangled."
        )
