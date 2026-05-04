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
st_autorefresh(interval=180_000, key="p02")

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
_DEF_THR, _OFF_THR = 2.5, 1.8    # defensive: 2.5% adverse (all 4 filters) · offensive: 1.8% favorable

if tue_anchor_available and tue_close > 0 and spot_now > 0:
    # Exact spot prices where triggers fire (nearest 50pt)
    ce_def_trig_spot = int(round(tue_close * (1 + _DEF_THR / 100) / 50) * 50)
    pe_def_trig_spot = int(round(tue_close * (1 - _DEF_THR / 100) / 50) * 50)
    pe_off_trig_spot = int(round(tue_close * (1 + _OFF_THR / 100) / 50) * 50)
    ce_off_trig_spot = int(round(tue_close * (1 - _OFF_THR / 100) / 50) * 50)

    ce_adverse = max(drift_pct,  0.0)
    pe_adverse = max(-drift_pct, 0.0)
    pe_favor   = max(drift_pct,  0.0)
    ce_favor   = max(-drift_pct, 0.0)

    ce_def_fired = ce_adverse >= _DEF_THR and threat_mult > 1.15
    pe_def_fired = pe_adverse >= _DEF_THR and threat_mult > 1.15
    ce_def_near  = not ce_def_fired and ce_adverse >= _DEF_THR * 0.75
    pe_def_near  = not pe_def_fired and pe_adverse >= _DEF_THR * 0.75
    ce_off_fired = ce_favor >= _OFF_THR
    pe_off_fired = pe_favor >= _OFF_THR

    # Defensive: roll OUT to 5% from anchor close
    ce_def_roll_to = int(round(tue_close * 1.05 / 50) * 50)
    pe_def_roll_to = int(round(tue_close * 0.95 / 50) * 50)

    # Offensive: roll IN from current spot
    # Wed/Thu (DTE>=5): standard IC distances — 3.5% CE, 4.0% PE from CMP
    # Fri/Mon/Tue (DTE<=4): tighter — 2.5% CE, 3.0% PE from CMP
    if dte >= 5:
        ce_off_pct, pe_off_pct = 3.5, 4.0
    else:
        ce_off_pct, pe_off_pct = 2.5, 3.0
    ce_off_roll_to = int(round(spot_now * (1 + ce_off_pct / 100) / 50) * 50)  # new CE above spot
    pe_off_roll_to = int(round(spot_now * (1 - pe_off_pct / 100) / 50) * 50)  # new PE below spot
else:
    ce_adverse = pe_adverse = pe_favor = ce_favor = 0.0
    ce_def_fired = pe_def_fired = ce_def_near = pe_def_near = False
    ce_off_fired = pe_off_fired = False
    ce_def_trig_spot = pe_def_trig_spot = pe_off_trig_spot = ce_off_trig_spot = 0
    ce_def_roll_to = pe_def_roll_to = ce_off_roll_to = pe_off_roll_to = 0
    ce_off_pct, pe_off_pct = (3.5, 4.0) if dte >= 5 else (2.5, 3.0)

# Overall PE and CE canary (max across sources)
pe_canary = max(src1 if can_dir == "BEAR" else 0, src2_pe, src3_pe)
ce_canary = max(src1 if can_dir == "BULL" else 0, src2_ce, src3_ce)
overall_canary = max(pe_canary, ce_canary, canary)  # include legacy for safety

# ── India VIX ────────────────────────────────────────────────────────────────
vix_current = vix_chg_pct = 0.0
vix_available = vix_rising = False
try:
    from data.live_fetcher import get_india_vix_detail as _get_vix
    vix_current, vix_chg_pct = _get_vix()
    vix_available = vix_current > 0
    vix_rising = vix_chg_pct > 5.0
except Exception:
    pass

# ── Multi-filter roll states ─────────────────────────────────────────────────
# Four required gates per side. VIX is advisory only (not a gate).
# BOOK LOSS: all 4 pass. PREPARE TO BOOK LOSS: 90% drift OR (80% drift + 3/4 filters).
# BOOK PROFIT: favorable ≥ 1.8%. PREPARE TO BOOK PROFIT: favorable ≥ 1.35%.
if tue_anchor_available and tue_close > 0 and spot_now > 0:
    # CE side filters (spot rallied above CE strike)
    ce_f1 = ce_adverse >= _DEF_THR           # 2.5% adverse drift
    ce_f2 = threat_mult > 1.15              # institutional backing
    ce_f3 = ce_canary >= 2                  # canary Day 2+
    ce_f4 = mom_score > 0                   # bullish momentum (hurts CE)
    ce_fp = int(ce_f1) + int(ce_f2) + int(ce_f3) + int(ce_f4)
    # PE side filters (spot fell below PE strike)
    pe_f1 = pe_adverse >= _DEF_THR
    pe_f2 = threat_mult > 1.15
    pe_f3 = pe_canary >= 2
    pe_f4 = mom_score < 0                   # bearish momentum (hurts PE)
    pe_fp = int(pe_f1) + int(pe_f2) + int(pe_f3) + int(pe_f4)
    # BOOK LOSS: all 4 gates
    ce_book_loss    = ce_f1 and ce_f2 and ce_f3 and ce_f4
    pe_book_loss    = pe_f1 and pe_f2 and pe_f3 and pe_f4
    # PREPARE TO BOOK LOSS: 90% pure drift OR (80% drift + ≥3 filters pass)
    ce_prepare_loss = (not ce_book_loss) and (
        ce_adverse >= _DEF_THR * 0.90 or (ce_adverse >= _DEF_THR * 0.80 and ce_fp >= 3))
    pe_prepare_loss = (not pe_book_loss) and (
        pe_adverse >= _DEF_THR * 0.90 or (pe_adverse >= _DEF_THR * 0.80 and pe_fp >= 3))
    # BOOK PROFIT: favorable ≥ 1.8%
    ce_book_profit    = ce_favor >= _OFF_THR
    pe_book_profit    = pe_favor >= _OFF_THR
    # PREPARE TO BOOK PROFIT: 75% of 1.8% = 1.35%
    ce_prepare_profit = (not ce_book_profit) and ce_favor >= _OFF_THR * 0.75
    pe_prepare_profit = (not pe_book_profit) and pe_favor >= _OFF_THR * 0.75
else:
    ce_f1=ce_f2=ce_f3=ce_f4=pe_f1=pe_f2=pe_f3=pe_f4=False
    ce_fp=pe_fp=0
    ce_book_loss=ce_prepare_loss=ce_book_profit=ce_prepare_profit=False
    pe_book_loss=pe_prepare_loss=pe_book_profit=pe_prepare_profit=False

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
pe_driver = "Source 2" if src2_pe >= src3_pe else "Source 3"
ce_driver = "Source 2" if src2_ce >= src3_ce else "Source 3"

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
    f"<div style='color:{_pe_txt};font-size:11px;font-weight:700;opacity:0.9;'>PE · PUT SIDE</div>"
    f"<div style='color:{_pe_txt};font-size:17px;font-weight:900;'>{CANARY_ICON.get(pe_canary,'')} {CANARY_LABEL.get(pe_canary,'—')}</div>"
    f"<div style='color:{_pe_txt};font-size:11px;opacity:0.8;'>{pe_driver}</div>"
    f"</div>"
    # Centre action
    f"<div style='background:{_act_col};padding:10px 14px;display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:90px;'>"
    f"<div style='color:white;font-size:10px;font-weight:700;letter-spacing:1px;text-align:center;'>EMA HOLD MONITOR</div>"
    f"<div style='color:white;font-size:20px;font-weight:900;'>{overall_action}</div>"
    f"<div style='color:rgba(255,255,255,0.75);font-size:10px;font-family:monospace;'>{regime}</div>"
    f"</div>"
    # CE side
    f"<div style='background:{_ce_hdr};flex:1;padding:10px 16px;text-align:right;'>"
    f"<div style='color:{_ce_txt};font-size:11px;font-weight:700;opacity:0.9;'>CE · CALL SIDE</div>"
    f"<div style='color:{_ce_txt};font-size:17px;font-weight:900;'>{CANARY_ICON.get(ce_canary,'')} {CANARY_LABEL.get(ce_canary,'—')}</div>"
    f"<div style='color:{_ce_txt};font-size:11px;opacity:0.8;'>{ce_driver}</div>"
    f"</div>"
    f"</div>",
    unsafe_allow_html=True)

# ── Top-of-page Roll Alert Banner ────────────────────────────────────────────
_any_book_loss   = ce_book_loss   or pe_book_loss
_any_book_profit = ce_book_profit or pe_book_profit
_any_prep_loss   = ce_prepare_loss   or pe_prepare_loss
_any_prep_profit = ce_prepare_profit or pe_prepare_profit

if _any_book_loss:
    _loss_sides = " + ".join(filter(None, ["CE" if ce_book_loss else "", "PE" if pe_book_loss else ""]))
    _loss_roll  = " + ".join(filter(None, [
        f"CE → {ce_def_roll_to:,}" if ce_book_loss else "",
        f"PE → {pe_def_roll_to:,}" if pe_book_loss else ""]))
    st.markdown(
        f"<div style='background:#b91c1c;border-radius:8px;padding:14px 20px;margin-bottom:12px;"
        f"border:2px solid #ef4444;'>"
        f"<div style='color:white;font-size:11px;font-weight:700;opacity:0.85;'>🔴 ROLL MATRIX ALERT</div>"
        f"<div style='color:white;font-size:18px;font-weight:900;margin:4px 0;'>BOOK LOSS — {_loss_sides} LEG</div>"
        f"<div style='color:white;font-size:12px;'>All 4 filters confirmed · Buy back losing leg · "
        f"Roll OUT to 5% from anchor · {_loss_roll}</div>"
        f"</div>", unsafe_allow_html=True)
elif _any_prep_loss:
    _prep_sides = " + ".join(filter(None, ["CE" if ce_prepare_loss else "", "PE" if pe_prepare_loss else ""]))
    st.markdown(
        f"<div style='background:#ea580c;border-radius:8px;padding:14px 20px;margin-bottom:12px;"
        f"border:2px solid #f97316;'>"
        f"<div style='color:white;font-size:11px;font-weight:700;opacity:0.85;'>⚠️ ROLL MATRIX ALERT</div>"
        f"<div style='color:white;font-size:18px;font-weight:900;margin:4px 0;'>PREPARE TO BOOK LOSS — {_prep_sides} LEG</div>"
        f"<div style='color:white;font-size:12px;'>Approaching defensive threshold · Review Section 6 now</div>"
        f"</div>", unsafe_allow_html=True)

if _any_book_profit:
    _prof_sides = " + ".join(filter(None, ["CE" if ce_book_profit else "", "PE" if pe_book_profit else ""]))
    _prof_roll  = " + ".join(filter(None, [
        f"CE → {ce_off_roll_to:,}" if ce_book_profit else "",
        f"PE → {pe_off_roll_to:,}" if pe_book_profit else ""]))
    st.markdown(
        f"<div style='background:#0f766e;border-radius:8px;padding:14px 20px;margin-bottom:12px;"
        f"border:2px solid #14b8a6;'>"
        f"<div style='color:white;font-size:11px;font-weight:700;opacity:0.85;'>🟢 ROLL MATRIX ALERT</div>"
        f"<div style='color:white;font-size:18px;font-weight:900;margin:4px 0;'>BOOK PROFIT — {_prof_sides} LEG</div>"
        f"<div style='color:white;font-size:12px;'>Favorable drift ≥ 1.8% · Dead leg cheap · "
        f"Roll IN closer · {_prof_roll}</div>"
        f"</div>", unsafe_allow_html=True)
elif _any_prep_profit:
    _pp_sides = " + ".join(filter(None, ["CE" if ce_prepare_profit else "", "PE" if pe_prepare_profit else ""]))
    st.markdown(
        f"<div style='background:#0369a1;border-radius:8px;padding:14px 20px;margin-bottom:12px;"
        f"border:2px solid #38bdf8;'>"
        f"<div style='color:white;font-size:11px;font-weight:700;opacity:0.85;'>🔵 ROLL MATRIX ALERT</div>"
        f"<div style='color:white;font-size:18px;font-weight:900;margin:4px 0;'>PREPARE TO BOOK PROFIT — {_pp_sides} LEG</div>"
        f"<div style='color:white;font-size:12px;'>Favorable drift ≥ 1.35% · Review Section 6 · Prepare roll-in strikes</div>"
        f"</div>", unsafe_allow_html=True)

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

# Colours that need dark text — defined here so all UI sections can use it
_LIGHT_COLS = {"#bbf7d0", "#dcfce7", "#fca5a5", "#fecaca", "#fee2e2"}

# ── Hold/Act lookup (moat count × canary day) ────────────────────────────────
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

# Inline source chip: small coloured badge showing canary day per source
def _chip(lvl, palette):
    bg = BOTH_AMBER if _both_singing else palette.get(lvl, "#94a3b8")
    tc = "#1e293b" if bg in _LIGHT_COLS else "white"
    return (f"<span style='background:{bg};color:{tc};border-radius:3px;"
            f"padding:2px 6px;font-size:11px;font-weight:700;line-height:1.4;'>D{lvl}</span>")

# Roll state label + colour per side
def _roll_state(bl, pl, bp, pp):
    if bl: return "🔴 BOOK LOSS",    "#b91c1c"
    if pl: return "⚠️ PREPARE LOSS", "#ea580c"
    if bp: return "🟢 BOOK PROFIT",  "#0f766e"
    if pp: return "🔵 PREP PROFIT",  "#0369a1"
    return         "✅ HOLD",         "#1e3a5f"

pe_rs_txt, pe_rs_col = _roll_state(pe_book_loss, pe_prepare_loss, pe_book_profit, pe_prepare_profit)
ce_rs_txt, ce_rs_col = _roll_state(ce_book_loss, ce_prepare_loss, ce_book_profit, ce_prepare_profit)

# ══════════════════════════════════════════════════════════════════════════════
# COMMAND CENTRE
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Command Centre",
                  "Position snapshot — Roll state · Canary · Moats · Source chips · Drift · Filter status")

def _side_panel(tag, palette, is_pe,
                rs_txt, rs_col, hold_act, ha_lvl,
                canary_lvl, driver,
                moats, moat_lbl, moat_detail,
                s2, s3,
                adverse, favor,
                f1, f2, f3, f4):
    ha_col  = _lvl_col.get(ha_lvl, "#64748b")
    mc      = "#15803d" if moats >= 2 else "#d97706" if moats >= 1 else "#dc2626"
    dc      = "#dc2626" if adverse >= 2.0 else "#ea580c" if adverse >= 1.0 else "#64748b"
    fc      = "#0f766e" if favor  >= 1.8  else "#16a34a" if favor  >= 1.0 else "#64748b"

    bg_can  = BOTH_AMBER if _both_singing else (PE_GREEN if is_pe else CE_RED).get(canary_lvl, "#94a3b8")
    tc_can  = "#1e293b" if bg_can in _LIGHT_COLS else "white"

    moat_sub = (" · ".join(f"{lb}: {v:,.0f}" for lb, v in moat_detail[:2])
                if moat_detail else "—")

    dots = "".join(
        f"<span style='display:inline-block;width:8px;height:8px;border-radius:50%;"
        f"background:{'#16a34a' if ok else '#dc2626'};margin-right:2px;vertical-align:middle;'></span>"
        f"<span style='font-size:10px;color:#94a3b8;margin-right:6px;'>{lbl}</span>"
        for ok, lbl in [(f2, "Thr"), (f3, "Can"), (f4, "Mom"), (f1, "Dft")]
    )

    vix_line = ""
    if vix_available and vix_rising:
        if is_pe:
            vix_line = ("<div style='margin-top:6px;font-size:11px;font-weight:700;color:#bfdbfe;'>"
                        "🔵 VIX rising — fear confirms PE pressure</div>")
        else:
            vix_line = ("<div style='margin-top:6px;font-size:11px;font-weight:700;color:#fef08a;'>"
                        "⚠️ VIX rising — up move may revert, hold CE</div>")

    s2c = _chip(s2, palette)
    s3c = _chip(s3, palette)

    st.markdown(
        f"<div style='background:#0f172a;border-radius:10px;padding:14px 16px;"
        f"border:1px solid #1e293b;'>"
        # Tag
        f"<div style='font-size:10px;font-weight:700;color:#475569;"
        f"letter-spacing:1.5px;margin-bottom:8px;'>{tag}</div>"
        # Roll state badge
        f"<div style='background:{rs_col};border-radius:6px;padding:5px 10px;margin-bottom:10px;'>"
        f"<span style='color:white;font-size:15px;font-weight:900;"
        f"letter-spacing:0.3px;'>{rs_txt}</span></div>"
        # Canary
        f"<div style='display:flex;align-items:center;gap:6px;margin-bottom:7px;'>"
        f"<span style='background:{bg_can};color:{tc_can};border-radius:5px;"
        f"padding:3px 8px;font-size:12px;font-weight:700;'>"
        f"{CANARY_ICON.get(canary_lvl,'')} {CANARY_LABEL.get(canary_lvl,'—')}</span>"
        f"<span style='font-size:10px;color:#475569;'>{driver}</span></div>"
        # Source chips (S2 + S3 only)
        f"<div style='display:flex;align-items:center;gap:3px;margin-bottom:7px;'>"
        f"<span style='font-size:10px;color:#475569;margin-right:2px;'>SRC</span>"
        f"<span style='font-size:10px;color:#64748b;'>S2</span>&nbsp;{s2c}&nbsp;"
        f"<span style='font-size:10px;color:#64748b;margin-left:4px;'>S3</span>&nbsp;{s3c}</div>"
        # Moats
        f"<div style='margin-bottom:7px;'>"
        f"<span style='font-size:11px;color:#94a3b8;'>Moats </span>"
        f"<span style='font-size:16px;font-weight:700;color:{mc};'>{moats:g}</span>"
        f"<span style='font-size:11px;color:#64748b;'> · {moat_lbl}</span>"
        f"<div style='font-size:10px;color:#475569;margin-top:1px;'>{moat_sub}</div></div>"
        # Adverse / Favor
        f"<div style='display:flex;gap:14px;margin-bottom:7px;'>"
        f"<div><span style='font-size:10px;color:#94a3b8;'>ADVERSE </span>"
        f"<span style='font-size:15px;font-weight:700;color:{dc};'>{adverse:.2f}%</span></div>"
        f"<div><span style='font-size:10px;color:#94a3b8;'>FAVOR </span>"
        f"<span style='font-size:15px;font-weight:700;color:{fc};'>{favor:.2f}%</span></div></div>"
        # Hold/Act
        f"<div style='margin-bottom:8px;'>"
        f"<span style='font-size:11px;color:#94a3b8;'>Hold/Act: </span>"
        f"<span style='font-size:13px;font-weight:700;color:{ha_col};'>{hold_act}</span></div>"
        # Filter dots
        f"<div style='display:flex;align-items:center;flex-wrap:wrap;'>{dots}</div>"
        + vix_line
        + f"</div>", unsafe_allow_html=True)

_oa_col    = _lvl_col.get(page_level, "#64748b")
_reg_col   = {"STRONG_BULL":"#16a34a","BULL_COMPRESSED":"#15803d","INSIDE_BULL":"#15803d",
              "RECOVERING":"#d97706","INSIDE_BEAR":"#ea580c","BEAR_COMPRESSED":"#dc2626",
              "STRONG_BEAR":"#b91c1c"}.get(regime, "#64748b")
_thr_col2  = "#dc2626" if threat_mult > 1.5 else "#ea580c" if threat_mult > 1.15 else "#16a34a"
_vix_col2  = "#dc2626" if vix_rising else ("#16a34a" if vix_available else "#64748b")
_vix_disp  = f"{vix_current:.1f}" if vix_available else "N/A"
_drift_col3 = "#dc2626" if abs(drift_pct) >= 2.0 else "#ea580c" if abs(drift_pct) >= 1.0 else "#16a34a"
_drift_disp = f"{drift_pct:+.2f}%" if tue_anchor_available else "—"
_thr_disp  = "⚠️" if threat_mult > 1.15 else ""

col_pe, col_ctr, col_ce = st.columns([5, 4, 5])

with col_pe:
    _side_panel(
        "PE · PUT SIDE", PE_GREEN, True,
        pe_rs_txt, pe_rs_col, action_pe, level_pe,
        pe_canary, pe_driver,
        put_moats, put_label, _detail_p,
        src2_pe, src3_pe,
        pe_adverse, pe_favor,
        pe_f1, pe_f2, pe_f3, pe_f4)

with col_ctr:
    st.markdown(
        f"<div style='background:#0f172a;border-radius:10px;padding:14px 16px;"
        f"border:1px solid #1e293b;text-align:center;'>"
        f"<div style='font-size:10px;font-weight:700;color:#475569;"
        f"letter-spacing:1.5px;margin-bottom:10px;'>OVERALL VERDICT</div>"
        # Overall action
        f"<div style='background:{_oa_col};border-radius:8px;padding:8px 12px;margin-bottom:10px;'>"
        f"<div style='color:white;font-size:17px;font-weight:900;'>{page_action}</div>"
        f"<div style='color:rgba(255,255,255,0.65);font-size:11px;'>{page_driver} side drives</div></div>"
        # Regime
        f"<div style='border:1px solid {_reg_col}55;border-radius:6px;"
        f"padding:5px 8px;margin-bottom:6px;'>"
        f"<div style='font-size:12px;font-weight:700;color:{_reg_col};'>{regime}</div>"
        f"<div style='font-size:10px;color:#64748b;'>EMA Regime</div></div>"
        # IC shape
        f"<div style='border:1px solid {skew_col}55;border-radius:6px;"
        f"padding:5px 8px;margin-bottom:10px;'>"
        f"<div style='font-size:12px;font-weight:700;color:{skew_col};'>{skew_label}</div>"
        f"<div style='font-size:10px;color:#64748b;'>IC Shape</div></div>"
        # 2×2 key metrics grid
        f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:4px;'>"
        f"<div style='background:#1e293b;border-radius:5px;padding:5px 6px;'>"
        f"<div style='font-size:10px;color:#64748b;'>DTE</div>"
        f"<div style='font-size:16px;font-weight:700;color:#e2e8f0;'>{dte}</div></div>"
        f"<div style='background:#1e293b;border-radius:5px;padding:5px 6px;'>"
        f"<div style='font-size:10px;color:#64748b;'>THREAT {_thr_disp}</div>"
        f"<div style='font-size:16px;font-weight:700;color:{_thr_col2};'>{threat_mult:.2f}</div></div>"
        f"<div style='background:#1e293b;border-radius:5px;padding:5px 6px;'>"
        f"<div style='font-size:10px;color:#64748b;'>INDIA VIX</div>"
        f"<div style='font-size:16px;font-weight:700;color:{_vix_col2};'>{_vix_disp}</div></div>"
        f"<div style='background:#1e293b;border-radius:5px;padding:5px 6px;'>"
        f"<div style='font-size:10px;color:#64748b;'>DRIFT</div>"
        f"<div style='font-size:16px;font-weight:700;color:{_drift_col3};'>{_drift_disp}</div></div>"
        f"</div>"
        f"</div>", unsafe_allow_html=True)

with col_ce:
    _side_panel(
        "CE · CALL SIDE", CE_RED, False,
        ce_rs_txt, ce_rs_col, action_ce, level_ce,
        ce_canary, ce_driver,
        call_moats, call_label, _detail_c,
        src2_ce, src3_ce,
        ce_adverse, ce_favor,
        ce_f1, ce_f2, ce_f3, ce_f4)

# Regime change warning (was in Section 3)
_entry_regime = sig.get("entry_regime", regime)
if _entry_regime != regime:
    st.warning(f"⚠️ Regime changed since entry: {_entry_regime} → {regime}")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# ROLL MATRIX — Defensive Book Loss · Offensive Book Profit
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Roll Matrix",
                  "Four-filter defensive gate · Offensive theta harvest · Exact roll-to strikes")

with st.expander("Roll Matrix — Reference", expanded=False):
    st.markdown(
        "**BOOK LOSS (Defensive Roll)**\n\n"
        "All 4 filters must pass simultaneously:\n\n"
        "1. **Drift ≥ 2.5%** adverse from anchor close\n"
        "2. **Threat Multiplier > 1.15** — move is institutionally backed\n"
        "3. **Canary ≥ Day 2** on the threatened side\n"
        "4. **Momentum agrees** — mom_score > 0 for CE threat · mom_score < 0 for PE threat\n\n"
        "Action: Buy back losing leg · Roll OUT to 5% from anchor close (nearest 50pt)\n\n"
        "**VIX asymmetry:** Rising VIX with an up move suggests mean reversion → ⚠️ CAUTION on CE. "
        "Rising VIX with a down move is fear-driven → 🔵 EXTRA CONFIRMATION on PE.\n\n"
        "---\n\n"
        "**PREPARE TO BOOK LOSS:** Drift ≥ 2.25% (90%) regardless of filters, "
        "OR drift ≥ 2.0% (80%) + 3 of 4 filters pass.\n\n"
        "---\n\n"
        "**BOOK PROFIT (Offensive Roll):** Favorable drift ≥ 1.8%\n\n"
        "| When | CE roll-in | PE roll-in |\n"
        "|------|-----------|----------|\n"
        "| DTE ≥ 5 (Wed/Thu) | +3.5% from CMP | −4.0% from CMP |\n"
        "| DTE ≤ 4 (Fri/Mon/Tue) | +2.5% from CMP | −3.0% from CMP |\n\n"
        "**PREPARE TO BOOK PROFIT:** Favorable drift ≥ 1.35% (75% of 1.8%)\n\n"
        "---\n\n"
        "**Threat Multiplier** = |daily return %| × (today volume ÷ 14-day avg)\n\n"
        "> 1.15 = institutional backing confirmed. Below 1.15 = possible noise."
    )

# Metrics bar
c1, c2, c3, c4, c5 = st.columns(5)
with c1: ui.metric_card("DTE", f"{dte}",
                         sub="Wed/Thu — std IC" if dte >= 5 else "Fri/Mon/Tue — tight IC")
with c2: ui.metric_card("THREAT MULT", f"{threat_mult:.2f}",
                         sub=f"Ret {daily_ret_pct:+.1f}% · RelVol {rel_vol:.2f}",
                         color="red" if threat_mult > 1.15 else "green")
with c3: ui.metric_card("ANCHOR CLOSE",
                         f"{tue_close:,.0f}" if tue_anchor_available else "N/A",
                         sub=f"Anchor: {tue_anchor_date}" if tue_anchor_available else "No anchor")
with c4: ui.metric_card("DRIFT FROM ANCHOR",
                         f"{drift_pct:+.2f}%" if tue_anchor_available else "—",
                         sub=f"Spot {spot_now:,.0f}",
                         color="red" if abs(drift_pct) >= 2.0 else "default")
with c5:
    if vix_available:
        ui.metric_card("INDIA VIX", f"{vix_current:.2f}",
                        sub=f"Chg {vix_chg_pct:+.1f}% · {'⚠️ RISING' if vix_rising else 'stable'}",
                        color="red" if vix_rising else "default")
    else:
        ui.metric_card("INDIA VIX", "N/A", sub="Feed unavailable")

if not tue_anchor_available:
    st.info("Expiry anchor not available — load data to activate roll matrix.")
else:
    def _frow(label, passed, value_str):
        icon = "✅" if passed else "❌"
        col  = "#16a34a" if passed else "#dc2626"
        return (
            f"<div style='display:flex;align-items:center;gap:6px;margin:3px 0;'>"
            f"<span style='font-size:13px;'>{icon}</span>"
            f"<span style='font-size:12px;color:#e2e8f0;flex:1;'>{label}</span>"
            f"<span style='font-size:12px;font-weight:700;color:{col};'>{value_str}</span>"
            f"</div>"
        )

    def _side_card(side_tag, palette,
                   book_loss, prep_loss, book_profit, prep_profit,
                   adverse, favor,
                   def_roll_to, off_roll_to, def_trig_spot, off_trig_spot,
                   f1, f2, f3, f4, fp, canary_val, is_ce):
        if book_loss:
            bg    = palette[0]
            state = "🔴 BOOK LOSS — ROLL OUT"
            action = f"Buy back losing leg · Roll OUT to 5% from anchor → {def_roll_to:,}"
        elif prep_loss:
            bg    = "#ea580c"
            state = "⚠️ PREPARE TO BOOK LOSS"
            action = f"Approaching threshold · {_DEF_THR - adverse:.2f}% to trigger · Spot {def_trig_spot:,}"
        elif book_profit:
            bg    = "#0f766e"
            state = "🟢 BOOK PROFIT — ROLL IN"
            _pct  = ce_off_pct if is_ce else pe_off_pct
            action = f"Buy back dead leg · Roll IN {_pct}% from spot → {off_roll_to:,}"
        elif prep_profit:
            bg    = "#0369a1"
            state = "🔵 PREPARE TO BOOK PROFIT"
            action = f"Favorable drift building · {_OFF_THR - favor:.2f}% to trigger · Spot {off_trig_spot:,}"
        else:
            bg    = palette[4] if adverse < 0.5 and favor < 0.5 else palette[3]
            state = "✅ HOLD"
            action = (f"Def gap {_DEF_THR - adverse:.2f}% · Off gap {_OFF_THR - favor:.2f}% · "
                      f"Def trig {def_trig_spot:,} · Off trig {off_trig_spot:,}")

        txt_col  = "#1e293b" if bg in _LIGHT_COLS else "white"
        vix_line = ""
        if vix_available and vix_rising:
            if is_ce:
                vix_line = (f"<div style='margin-top:4px;padding:4px 8px;border-radius:4px;"
                            f"background:rgba(0,0,0,0.25);color:#fef08a;"
                            f"font-size:11px;font-weight:700;'>"
                            f"⚠️ VIX RISING {vix_chg_pct:+.1f}% — CAUTION: up moves may revert</div>")
            else:
                vix_line = (f"<div style='margin-top:4px;padding:4px 8px;border-radius:4px;"
                            f"background:rgba(0,0,0,0.25);color:#bfdbfe;"
                            f"font-size:11px;font-weight:700;'>"
                            f"🔵 VIX RISING {vix_chg_pct:+.1f}% — EXTRA CONFIRMATION: fear-driven</div>")

        scorecard = (
            _frow("Drift ≥ 2.5% adverse",  f1, f"{adverse:.2f}%")
            + _frow("Threat Mult > 1.15",   f2, f"{threat_mult:.2f}")
            + _frow(f"Canary ≥ Day 2 ({canary_val}/4)", f3, f"Day {canary_val}")
            + _frow(f"Mom {'> 0 bullish' if is_ce else '< 0 bearish'}", f4, f"{mom_score:+.1f}%ATR")
        )
        st.markdown(
            f"<div style='background:{bg};border-radius:10px;padding:14px 16px;margin-bottom:8px;'>"
            f"<div style='color:{txt_col};font-size:11px;font-weight:700;"
            f"opacity:0.8;letter-spacing:1px;'>{side_tag}</div>"
            f"<div style='color:{txt_col};font-size:18px;font-weight:900;margin:3px 0 6px;'>{state}</div>"
            f"<div style='color:{txt_col};font-size:12px;font-style:italic;"
            f"opacity:0.9;margin-bottom:8px;'>{action}</div>"
            f"<div style='background:rgba(0,0,0,0.20);border-radius:6px;padding:8px 10px;'>"
            f"<div style='color:#94a3b8;font-size:10px;font-weight:700;"
            f"margin-bottom:4px;letter-spacing:1px;'>FILTER SCORECARD — {fp}/4 PASS</div>"
            + scorecard + f"</div>" + vix_line + f"</div>",
            unsafe_allow_html=True)

    col_ce, col_pe = st.columns(2)
    with col_ce:
        _side_card("CE · CALL SIDE", CE_RED,
                   ce_book_loss, ce_prepare_loss, ce_book_profit, ce_prepare_profit,
                   ce_adverse, ce_favor,
                   ce_def_roll_to, ce_off_roll_to, ce_def_trig_spot, ce_off_trig_spot,
                   ce_f1, ce_f2, ce_f3, ce_f4, ce_fp, ce_canary, is_ce=True)
    with col_pe:
        _side_card("PE · PUT SIDE", PE_GREEN,
                   pe_book_loss, pe_prepare_loss, pe_book_profit, pe_prepare_profit,
                   pe_adverse, pe_favor,
                   pe_def_roll_to, pe_off_roll_to, pe_def_trig_spot, pe_off_trig_spot,
                   pe_f1, pe_f2, pe_f3, pe_f4, pe_fp, pe_canary, is_ce=False)

    # ── Strike-Path Corridor ──────────────────────────────────────────────────
    if ema_vals and spot_now > 0:
        _all_emas = [(p, float(v)) for p, v in ema_vals.items() if v and float(v) > 0]

        # CE corridor: EMAs strictly between spot and ce_sold (spot < ema < ce_sold)
        if ce_sold > 0:
            _ce_moats = sorted(
                [(p, v) for p, v in _all_emas if spot_now < v < ce_sold],
                key=lambda x: x[1]
            )
        else:
            _ce_moats = []

        # PE corridor: EMAs strictly between pe_sold and spot (pe_sold < ema < spot)
        if pe_sold > 0:
            _pe_moats = sorted(
                [(p, v) for p, v in _all_emas if pe_sold < v < spot_now],
                key=lambda x: x[1], reverse=True
            )
        else:
            _pe_moats = []

        # CE strip: [ANCHOR→] [CMP] [EMA moats ascending] [CE_SOLD]
        # PE strip: [PE_SOLD] [EMA moats descending] [CMP] [←ANCHOR]
        _ce_anchor_val = tue_close if tue_anchor_available else None
        _pe_anchor_val = tue_close if tue_anchor_available else None

        st.markdown(
            "<div style='font-size:11px;font-weight:700;color:#475569;"
            "letter-spacing:1px;margin:12px 0 6px;'>STRIKE-PATH CORRIDOR</div>",
            unsafe_allow_html=True)

        # CE strip
        _ce_items = []
        if _ce_anchor_val:
            _ce_items.append(("ANCHOR", _ce_anchor_val, "neutral"))
        _ce_items.append(("CMP", spot_now, "cmp"))
        for p, v in _ce_moats:
            _ce_items.append((f"EMA{p}", v, "above"))
        if ce_sold > 0:
            _ce_items.append((f"CE {ce_sold:,}", float(ce_sold), "sold_ce"))

        _pe_items = []
        if pe_sold > 0:
            _pe_items.append((f"PE {pe_sold:,}", float(pe_sold), "sold_pe"))
        for p, v in _pe_moats:
            _pe_items.append((f"EMA{p}", v, "below"))
        _pe_items.append(("CMP", spot_now, "cmp"))
        if _pe_anchor_val:
            _pe_items.append(("ANCHOR", _pe_anchor_val, "neutral"))

        _COLOR_MAP = {
            "neutral": ("#dbeafe", "#1e3a5f"),
            "cmp":     ("#bfdbfe", "#1e3a5f"),
            "above":   ("#fee2e2", "#7f1d1d"),
            "below":   ("#dcfce7", "#14532d"),
            "sold_ce": ("#b91c1c", "white"),
            "sold_pe": ("#15803d", "white"),
        }

        st.markdown("<div style='font-size:10px;color:#64748b;margin-bottom:3px;'>📈 CE Corridor (left→right, price ascending)</div>", unsafe_allow_html=True)
        _ce_cols = st.columns(max(len(_ce_items), 1))
        for i, (lbl, val, kind) in enumerate(_ce_items):
            bg, tc = _COLOR_MAP[kind]
            _moat_count = len(_ce_moats)
            _path_note = f"{_moat_count} moat{'s' if _moat_count != 1 else ''}" if kind == "sold_ce" else ""
            if kind == "sold_ce" and _moat_count == 0:
                _path_note = "PATH CLEAR ⚠️"
            with _ce_cols[i]:
                ui.metric_card(lbl, f"{val:,.0f}",
                               sub=_path_note if _path_note else ("sold strike" if kind == "sold_ce" else
                                   "current price" if kind == "cmp" else
                                   "anchor" if kind == "neutral" else "moat EMA"),
                               color=("red" if kind in ("above", "sold_ce") else
                                      "blue" if kind == "cmp" else
                                      "green" if kind in ("below", "sold_pe") else "default"))

        st.markdown("<div style='font-size:10px;color:#64748b;margin:6px 0 3px;'>📉 PE Corridor (left→right, price descending — danger on left)</div>", unsafe_allow_html=True)
        _pe_cols = st.columns(max(len(_pe_items), 1))
        for i, (lbl, val, kind) in enumerate(_pe_items):
            bg, tc = _COLOR_MAP[kind]
            _moat_count_pe = len(_pe_moats)
            _path_note_pe = f"{_moat_count_pe} moat{'s' if _moat_count_pe != 1 else ''}" if kind == "sold_pe" else ""
            if kind == "sold_pe" and _moat_count_pe == 0:
                _path_note_pe = "PATH CLEAR ⚠️"
            with _pe_cols[i]:
                ui.metric_card(lbl, f"{val:,.0f}",
                               sub=_path_note_pe if _path_note_pe else ("sold strike" if kind == "sold_pe" else
                                   "current price" if kind == "cmp" else
                                   "anchor" if kind == "neutral" else "moat EMA"),
                               color=("green" if kind in ("below", "sold_pe") else
                                      "blue" if kind == "cmp" else
                                      "red" if kind in ("above", "sold_ce") else "default"))

    _off_rule = f"{'Wed/Thu' if dte >= 5 else 'Fri/Mon/Tue'} · CE +{ce_off_pct}% / PE −{pe_off_pct}% from spot"
    st.caption(
        f"Anchor {tue_close:,.0f} · Spot {spot_now:,.0f} · Drift {drift_pct:+.2f}% · "
        f"Threat {threat_mult:.2f} · VIX {vix_current:.2f} · {_off_rule}"
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# CANARY SOURCES — diagnostic layer
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Canary Sources",
                  "Diagnostic — see exactly which source is driving the signal and why")

# Verdict block
_vc_lvl  = max(pe_canary, ce_canary)
_vc_side = "CE" if ce_canary >= pe_canary else "PE"
_vc_drv  = ce_driver if ce_canary >= pe_canary else pe_driver
_vc_col  = CANARY_HEADER_COLOUR.get(_vc_lvl, "#94a3b8")

if _vc_lvl == 0:
    _verdict_main = "All three sources are clear. EMA structure intact, no drift pressure. Hold with confidence."
else:
    _verdict_main = (f"{_vc_drv} is driving {_vc_side} to {CANARY_LABEL.get(_vc_lvl)} — "
                     f"{CANARY_ACTION.get(_vc_lvl,'WATCH')} on the {_vc_side} side.")

_rule1_col  = "#dc2626" if src1 >= 3 else "#ea580c" if src1 == 2 else "#16a34a"
_rule1_text = (f"Rule 1 — Gap Day {src1} ({gap_pct:.0f}% ATR): exit heavy side immediately." if src1 >= 3 else
               f"Rule 1 — Gap Day 2 ({gap_pct:.0f}% ATR): skew overridden → flatten 1:1." if src1 == 2 else
               f"Rule 1 — Gap Day {src1} ({gap_pct:.0f}% ATR, {can_dir}): {skew_label} skew stands.")
_rule2_col  = _vc_col if _vc_lvl > 0 else "#16a34a"
_rule2_text = (f"Rule 2 — Harshest signal wins: {_vc_drv} at {CANARY_LABEL.get(_vc_lvl)}." if _vc_lvl > 0 else
               "Rule 2 — No source firing. Max() across all sources = Singing.")

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
        "source":     "Source 2 — Momentum Score (% of ATR/day)",
        "what":       f"Score: {mom_score:+.1f}% of ATR/day · IC Shape: {skew_label}",
        "pe_lvl":     src2_pe, "ce_lvl": src2_ce,
        "pe_col":     src2_pe_col, "ce_col": src2_ce_col,
        "detail":     (f"EMA3 slope: {ema3_slope:+.1f} pts/day  (60% weight)\n"
                       f"EMA8 slope: {ema8_slope:+.1f} pts/day  (40% weight)\n"
                       f"Combined score: {mom_score:+.1f}% of ATR/day\n"
                       f"Bullish (PE/CE):  >32% = D0/D4  ·  20–32% = D1/D3"
                       f"  ·  11–20% = D2/D2  ·  5–11% = D3/D1\n"
                       f"Flat zone: ±5% = both Day 0 (amber)  ·  Bearish: mirror"),
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
        f"<div style='color:{txt};font-size:9px;font-weight:700;opacity:0.85;'>{label}</div>"
        f"<div style='color:{txt};font-size:15px;font-weight:900;margin:2px 0;'>{icon} {lbl}</div>"
        f"</div>", unsafe_allow_html=True)

for s in src_data:
    with st.expander(
            f"{s['source']} — "
            f"PE: {CANARY_LABEL.get(s['pe_lvl'],'—')} | CE: {CANARY_LABEL.get(s['ce_lvl'],'—')}",
            expanded=False):
        st.markdown(f"<small style='color:#334155;'>{s['what']}</small>", unsafe_allow_html=True)
        st.markdown(f"<pre style='font-size:10px;color:#5a6b8a;margin-bottom:8px;'>{s['detail']}</pre>",
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
                f"<span style='font-size:11px;font-weight:700;color:{sc};'>"
                f"IC SHAPE · {s['skew_label']}</span>"
                f"<span style='font-size:10px;color:#334155;'> — {s['skew_note']}</span>"
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
