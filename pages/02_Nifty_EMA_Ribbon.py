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

# Source 1 — EMA3/EMA8 gap (LIVE) · thresholds: 55/35/15/5 % of ATR
# Direction computed live from actual EMA values, not stale EOD can_dir
# EMA3 > EMA8 → BULL → only CE threatened (PE always D0)
# EMA3 < EMA8 → BEAR → only PE threatened (CE always D0)
e3  = sig.get("ema3",  ema_vals.get(3,  0))
e8  = sig.get("ema8",  ema_vals.get(8,  0))
e16 = sig.get("ema16", ema_vals.get(16, 0))
e30 = sig.get("ema30", ema_vals.get(30, 0))
gap_pts = abs(e3 - e8) if e3 and e8 else 0
gap_pct = gap_pts / atr14 * 100 if atr14 > 0 else 0

# Live direction from EMA values
can_dir_live = "BULL" if (e3 and e8 and e3 > e8) else "BEAR" if (e3 and e8 and e3 < e8) else can_dir

# Source 1 threatened-side scale (reversed):
# Wide gap = strong trend = MORE danger for the threatened leg.
# Safe side always D0. Gap closing toward cross = momentum dying = D0 on threatened side too.
if   gap_pct > 55: _src1_threatened = 4   # Strong established trend — maximum threat
elif gap_pct > 35: _src1_threatened = 3   # Solid trend
elif gap_pct > 15: _src1_threatened = 2   # Moderate — flatten skew
elif gap_pct >  5: _src1_threatened = 1   # Weakening — threat reducing
else:              _src1_threatened = 0   # Cross imminent/done — momentum dying, D0

src1    = _src1_threatened                            # scalar used by skew-override logic
src1_pe = _src1_threatened if can_dir_live == "BEAR" else 0
src1_ce = _src1_threatened if can_dir_live == "BULL" else 0

# Source 2 — Momentum % of ATR/day · PE + CE = 4, except flat zone = 0 + 0
def _src2_levels(score):
    if -5.0 <= score <= 5.0:  return 0, 0          # flat: both D0
    elif score > 0:                                  # bullish — CE threatened only, PE always D0
        if   score > 32: return 0, 4
        elif score > 20: return 0, 3
        elif score > 11: return 0, 2
        else:            return 0, 1                # 5–11%
    else:                                            # bearish — PE threatened only, CE always D0
        s = abs(score)
        if   s > 32: return 4, 0
        elif s > 20: return 3, 0
        elif s > 11: return 2, 0
        else:        return 1, 0                    # 5–11%

src2_pe, src2_ce = _src2_levels(mom_score)

# Color overrides for Source 2 cards
# With directional logic, PE and CE are never both non-zero simultaneously.
if src2_pe == 0 and src2_ce == 0:                  # flat or safe side: amber both
    src2_pe_col = src2_ce_col = "#d97706"
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

# Rule 1: strong trend (D3/D4 = wide gap) overrides skew
_thr_side = "CE" if can_dir_live == "BULL" else "PE"
if src1 >= 4:
    skew_label = f"EXIT {_thr_side}"; skew_note = f"Gap D4 ({gap_pct:.0f}% ATR) — strong trend, exit {_thr_side} immediately"; skew_col = "#dc2626"; skew_forced = True
elif src1 == 3:
    skew_label = f"REDUCE {_thr_side}"; skew_note = f"Gap D3 ({gap_pct:.0f}% ATR) — solid trend, cut {_thr_side} exposure"; skew_col = "#ea580c"; skew_forced = True
elif src1 == 2:
    skew_label = "1:1 Forced"; skew_note = f"Gap D2 ({gap_pct:.0f}% ATR) — moderate trend, flatten skew"; skew_col = "#d97706"; skew_forced = True

# Source 3 — Expiry anchor with phase-aware logic
# Phases on expiry day (Tuesday):
#   before 3:15 PM  → use PRIOR expiry's close (monitoring open position)
#   3:15 – 3:30 PM  → use live spot as provisional anchor (position sizing)
#   after  3:30 PM  → use today's expiry close (new week starts)
import datetime as _dt, numpy as _np
tue_close = tue_atr = 0.0
tue_anchor_available = False
tue_anchor_date = ""
anchor_mode = "NORMAL"  # NORMAL | PRE_EXPIRY | PROVISIONAL | POST_EXPIRY
try:
    from data.live_fetcher import get_nifty_daily, get_nifty_daily_live
    _now_ist        = _dt.datetime.now(pytz.timezone("Asia/Kolkata"))
    _today          = _now_ist.date()
    _cur_mins       = _now_ist.hour * 60 + _now_ist.minute
    _PROV_START     = 15 * 60 + 15   # 3:15 PM IST
    _PROV_END       = 15 * 60 + 30   # 3:30 PM IST
    _days_since_tue = (_today.weekday() - 1) % 7
    _last_tue       = _today - _dt.timedelta(days=_days_since_tue)

    # After 3:30 PM on expiry day, use live-TTL fetch (60s) so we always get
    # the actual EOD candle from Kite, not a stale intraday price from the 24h cache.
    _is_tue         = (_last_tue == _today)
    _use_live_daily = _is_tue and (_cur_mins >= _PROV_END)
    _daily = get_nifty_daily_live() if _use_live_daily else get_nifty_daily()

    if not _daily.empty:
        _trading_dates  = set(_daily.index.date)
        _is_expiry_day  = _is_tue and (_today in _trading_dates)

        def _find_anchor(target_tue):
            for _off in range(7):
                _c = target_tue - _dt.timedelta(days=_off)
                if _c in _trading_dates:
                    return _c
            return None

        def _load_anchor(date):
            _h2 = _daily[_daily.index.date <= date].tail(15)
            _cl = float(_h2["close"].iloc[-1])
            _hh, _ll, _cc = _h2["high"].values, _h2["low"].values, _h2["close"].values
            _tr = [max(_hh[i]-_ll[i], abs(_hh[i]-_cc[i-1]), abs(_ll[i]-_cc[i-1]))
                   for i in range(1, len(_h2))]
            _atr = float(_np.mean(_tr[-14:])) if len(_tr) >= 14 else float(_np.mean(_tr)) if _tr else 200.0
            return _cl, _atr

        if _is_expiry_day and _cur_mins < _PROV_START:
            # Before 3:15 on expiry day — use previous expiry close
            anchor_mode = "PRE_EXPIRY"
            _prev_tue = _last_tue - _dt.timedelta(days=7)
            _ad = _find_anchor(_prev_tue)
            if _ad:
                tue_close, tue_atr = _load_anchor(_ad)
                tue_anchor_date = str(_ad) + " (prior expiry)"
                tue_anchor_available = True

        elif _is_expiry_day and _PROV_START <= _cur_mins < _PROV_END:
            # 3:15–3:30 PM provisional window — use live spot as anchor
            anchor_mode = "PROVISIONAL"
            tue_close = float(spot_now) if spot_now > 0 else 0.0
            tue_anchor_date = f"PROVISIONAL {_now_ist.strftime('%H:%M')} IST"
            tue_anchor_available = tue_close > 0
            _hist_atr = _daily.tail(15)
            _hh, _ll, _cc = _hist_atr["high"].values, _hist_atr["low"].values, _hist_atr["close"].values
            _tr = [max(_hh[i]-_ll[i], abs(_hh[i]-_cc[i-1]), abs(_ll[i]-_cc[i-1]))
                   for i in range(1, len(_hist_atr))]
            tue_atr = float(_np.mean(_tr[-14:])) if len(_tr) >= 14 else float(_np.mean(_tr)) if _tr else 200.0

        else:
            # Normal: after 3:30 on expiry day OR any non-expiry day.
            # POST_EXPIRY uses get_nifty_daily_live() (60s TTL) so the
            # anchor is always the actual Tuesday EOD candle from Kite.
            # Holiday Tuesday: _find_anchor walks back to last trading day.
            anchor_mode = "POST_EXPIRY" if _is_expiry_day else "NORMAL"
            _ad = _find_anchor(_last_tue)
            if _ad:
                tue_close, tue_atr = _load_anchor(_ad)
                tue_anchor_date = str(_ad)
                tue_anchor_available = True
except Exception:
    pass

# Anchor fallback 1: tuesday_anchors.json written by EOD job
if not tue_anchor_available:
    try:
        from analytics.constituent_ema import _load_anchors as _la
        _anch = _la().get("NIFTY", {})
        if _anch.get("close") and _anch.get("date"):
            tue_close          = float(_anch["close"])
            tue_atr            = float(_anch.get("atr", atr14))
            tue_anchor_date    = str(_anch["date"]) + " (cached)"
            tue_anchor_available = True
            anchor_mode        = "NORMAL"
    except Exception:
        pass

# Anchor fallback 2: signals.json / session_state (stored by compute_all_signals every run)
if not tue_anchor_available:
    _fb_tc = float(sig.get("tue_close", 0))
    _fb_td = sig.get("tue_date", "")
    if _fb_tc > 0 and _fb_td:
        tue_close          = _fb_tc
        tue_atr            = float(sig.get("tue_atr", atr14))
        tue_anchor_date    = _fb_td + " (signals)"
        tue_anchor_available = True
        anchor_mode        = "NORMAL"

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
# Threat fallback: use values stored in signals.json from EOD job
if threat_mult == 0.0:
    daily_ret_pct = float(sig.get("daily_ret_pct", 0.0))
    rel_vol       = float(sig.get("rel_vol",       1.0))
    threat_mult   = float(sig.get("threat_mult",   0.0))

spot_now = spot
# Fallback: if Kite returns 0 pre-market, use last EOD close from daily data
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

# ── Rolled positions ──────────────────────────────────────────────────────────
from data.rolled_positions import (
    load_rolled, maybe_update_anchors as _mua, rolled_strike as _rs,
)
import datetime as _dtrp, pytz as _pyrp
_rolled = load_rolled()
_ist_rp = _dtrp.datetime.now(_pyrp.timezone("Asia/Kolkata"))
if _ist_rp.hour * 60 + _ist_rp.minute >= 15 * 60 + 15:
    # ce_canary/pe_canary computed later; _mua falls back to sig.canary_direction
    _rolled = _mua(spot_now, float(tue_close or 0), sig, _rolled)
_ce_rolled   = _rolled.get("CE", {})
_pe_rolled   = _rolled.get("PE", {})
ce_is_rolled = bool(_ce_rolled.get("active"))
pe_is_rolled = bool(_pe_rolled.get("active"))
# Source 3: expiry close = Tuesday close (or last trading day before Tuesday if holiday)
# PE sold 4% below expiry close, CE sold 3.5% above expiry close (rounded to nearest 50-pt strike)
# Canary triggers based on % drift from expiry close toward the sold strike
def _moat_pull(m):
    if m >= 4: return 100
    if m >= 3: return 75
    if m >= 2: return 50
    return 0

if tue_anchor_available and tue_close > 0 and spot_now > 0:
    _pe_pull  = _moat_pull(_entry_put_moats)
    _ce_pull  = _moat_pull(_entry_call_moats)
    pe_sold   = int(round((tue_close * 0.96  + _pe_pull) / 50) * 50)
    ce_sold   = int(round((tue_close * 1.035 - _ce_pull) / 50) * 50)
    # Override with rolled strike when active
    if ce_is_rolled and _ce_rolled.get("strike"):
        ce_sold = int(_ce_rolled["strike"])
    if pe_is_rolled and _pe_rolled.get("strike"):
        pe_sold = int(_pe_rolled["strike"])
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
    # Per-side effective anchors (rolled if active, else Tuesday close)
    _ce_anc = float(_ce_rolled["anchor"]) if ce_is_rolled else float(tue_close)
    _pe_anc = float(_pe_rolled["anchor"]) if pe_is_rolled else float(tue_close)

    # Exact spot prices where triggers fire (nearest 50pt)
    ce_def_trig_spot = int(round(_ce_anc * (1 + _DEF_THR / 100) / 50) * 50)
    pe_def_trig_spot = int(round(_pe_anc * (1 - _DEF_THR / 100) / 50) * 50)
    pe_off_trig_spot = int(round(_pe_anc * (1 + _OFF_THR / 100) / 50) * 50)
    ce_off_trig_spot = int(round(_ce_anc * (1 - _OFF_THR / 100) / 50) * 50)

    ce_adverse = max((spot_now - _ce_anc) / _ce_anc * 100, 0.0)
    pe_adverse = max((_pe_anc - spot_now) / _pe_anc * 100, 0.0)
    pe_favor   = max((spot_now - _pe_anc) / _pe_anc * 100, 0.0)
    ce_favor   = max((_ce_anc - spot_now) / _ce_anc * 100, 0.0)

    ce_def_fired = ce_adverse >= _DEF_THR and threat_mult > 1.15
    pe_def_fired = pe_adverse >= _DEF_THR and threat_mult > 1.15
    ce_def_near  = not ce_def_fired and ce_adverse >= _DEF_THR * 0.75
    pe_def_near  = not pe_def_fired and pe_adverse >= _DEF_THR * 0.75
    ce_off_fired = ce_favor >= _OFF_THR
    pe_off_fired = pe_favor >= _OFF_THR

    # Defensive: roll OUT 3.5% (CE) / 4% (PE) from CMP
    ce_def_roll_to = int(round(spot_now * 1.035 / 50) * 50)
    pe_def_roll_to = int(round(spot_now * 0.960 / 50) * 50)

    # Offensive: roll IN 3.5% (CE) / 4% (PE) from CMP — unified with defensive
    ce_off_pct, pe_off_pct = 3.5, 4.0
    ce_off_roll_to = int(round(spot_now * (1 + ce_off_pct / 100) / 50) * 50)
    pe_off_roll_to = int(round(spot_now * (1 - pe_off_pct / 100) / 50) * 50)
else:
    _ce_anc = _pe_anc = 0.0
    ce_adverse = pe_adverse = pe_favor = ce_favor = 0.0
    ce_def_fired = pe_def_fired = ce_def_near = pe_def_near = False
    ce_off_fired = pe_off_fired = False
    ce_def_trig_spot = pe_def_trig_spot = pe_off_trig_spot = ce_off_trig_spot = 0
    ce_def_roll_to = pe_def_roll_to = ce_off_roll_to = pe_off_roll_to = 0
    ce_off_pct, pe_off_pct = 3.5, 4.0

# Overall PE and CE canary (max across sources)
# src1_pe/src1_ce already encode direction — no need for can_dir check here
pe_canary = max(src1_pe, src2_pe, src3_pe)
ce_canary = max(src1_ce, src2_ce, src3_ce)
overall_canary = max(pe_canary, ce_canary, canary)  # include legacy for safety

# Re-run anchor update now that per-side canary counts are known
if _ist_rp.hour * 60 + _ist_rp.minute >= 15 * 60 + 15:
    _rolled = _mua(spot_now, float(tue_close or 0), sig, _rolled,
                   ce_canary=ce_canary, pe_canary=pe_canary)
    _ce_rolled   = _rolled.get("CE", {})
    _pe_rolled   = _rolled.get("PE", {})
    ce_is_rolled = bool(_ce_rolled.get("active"))
    pe_is_rolled = bool(_pe_rolled.get("active"))

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
def _driver(s1, s2, s3):
    if s1 >= s2 and s1 >= s3 and s1 > 0:
        return "Source 1 (EMA Gap)"
    return "Source 2" if s2 >= s3 else "Source 3"

pe_driver = _driver(src1_pe, src2_pe, src3_pe)
ce_driver = _driver(src1_ce, src2_ce, src3_ce)

# ── Page header colour ───────────────────────────────────────────────────────
CANARY_LABEL  = {0: "SINGING", 1: "Canary Day 1", 2: "Canary Day 2",
                 3: "Canary Day 3", 4: "Canary Day 4"}
CANARY_ACTION = {0: "HOLD", 1: "WATCH", 2: "WATCH", 3: "PREPARE", 4: "ACT"}
CANARY_ICON   = {0: "✅", 1: "🟡", 2: "⚠️", 3: "🔴", 4: "🔴"}
CANARY_HEADER_COLOUR = {0: "#d97706", 1: "#d97706", 2: "#d97706", 3: "#ea580c", 4: "#dc2626"}
overall_action = CANARY_ACTION.get(overall_canary, "WATCH")
overall_label  = CANARY_LABEL.get(overall_canary, "Canary Day 4")

_both_singing = (pe_canary == 0 and ce_canary == 0)

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
            f"padding:2px 6px;font-size:14px;font-weight:700;line-height:1.4;'>D{lvl}</span>")

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
# ROLL MATRIX — Defensive Book Loss · Offensive Book Profit
# ══════════════════════════════════════════════════════════════════════════════
show_page_header(spot, signals_ts)

# ── Expiry-day phase banners ─────────────────────────────────────────────────
if anchor_mode == "PROVISIONAL":
    _prov_ce = int(round(spot_now * 1.035 / 50) * 50)
    _prov_pe = int(round(spot_now * 0.960 / 50) * 50)
    st.markdown(
        f"<div style='background:#6d28d9;border-radius:8px;padding:14px 20px;"
        f"margin-bottom:12px;border:2px solid #a78bfa;'>"
        f"<div style='color:white;font-size:14px;font-weight:700;opacity:0.85;'>"
        f"🟣 EXPIRY CLOSING WINDOW · 3:15–3:30 PM IST</div>"
        f"<div style='color:white;font-size:20px;font-weight:900;margin:4px 0;'>"
        f"PROVISIONAL STRIKES — NEXT WEEK</div>"
        f"<div style='color:white;font-size:14px;'>"
        f"Anchor = CMP {spot_now:,.0f} · "
        f"Sell CE → <b>{_prov_ce:,}</b> (+3.5%) · "
        f"Sell PE → <b>{_prov_pe:,}</b> (−4.0%)</div>"
        f"<div style='color:rgba(255,255,255,0.65);font-size:14px;margin-top:4px;'>"
        f"Anchor locks to today's EOD close after 3:30 PM</div>"
        f"</div>", unsafe_allow_html=True)
elif anchor_mode == "PRE_EXPIRY":
    st.markdown(
        f"<div style='background:#1e3a5f;border-radius:8px;padding:10px 16px;"
        f"margin-bottom:10px;border:1px solid #3b82f6;'>"
        f"<div style='color:#bfdbfe;font-size:12px;'>"
        f"📅 <b>Expiry day</b> — monitoring open position against prior anchor "
        f"<b>{tue_anchor_date}</b> ({tue_close:,.0f}). "
        f"Provisional new-week strikes appear at <b>3:15 PM IST</b>.</div>"
        f"</div>", unsafe_allow_html=True)

ui.section_header("Roll Matrix",
                  "Four-filter defensive gate · Offensive theta harvest · Exact roll-to strikes")

with st.expander("Roll Matrix — Reference", expanded=False):
    st.markdown(
        "**BOOK LOSS (Defensive Roll)**\n\n"
        "All 6 filters must pass simultaneously:\n\n"
        "1. **Drift ≥ 2.5%** adverse from anchor close\n"
        "2. **Threat Multiplier > 1.15** — move is institutionally backed\n"
        "3. **Canary ≥ Day 2** on the threatened side\n"
        "4. **Momentum agrees** — mom_score > 0 for CE threat · mom_score < 0 for PE threat\n"
        "5. **Days to Breach ≤ 1.5d** — spot is close enough to the trigger that pace matters; "
        "a large days-to-breach means the move is slow and may stall\n"
        "6. **VIX regime confirms** — VIX↑ + mkt↓ confirms PE loss (fear-driven); "
        "VIX↑ + mkt↑ warns CE may revert (use as caution, not confirmation)\n\n"
        "Action: Buy back losing leg · Roll OUT 3.5% (CE) / 4% (PE) from CMP (nearest 50pt)\n\n"
        "---\n\n"
        "**PREPARE TO BOOK LOSS:** Drift ≥ 2.25% (90%) regardless of filters, "
        "OR drift ≥ 2.0% (80%) + 3 of 4 core filters pass.\n\n"
        "---\n\n"
        "**BOOK PROFIT (Offensive Roll):** Favorable drift ≥ 1.8%\n\n"
        "Action: Buy back dead leg · Roll IN 3.5% (CE) / 4% (PE) from CMP (nearest 50pt)\n\n"
        "**PREPARE TO BOOK PROFIT:** Favorable drift ≥ 1.35% (75% of 1.8%)\n\n"
        "---\n\n"
        "**Threat Multiplier** = |daily return %| × (today volume ÷ 14-day avg)\n\n"
        "> 1.15 = institutional backing confirmed. Below 1.15 = possible noise.\n\n"
        "---\n\n"
        "**Days to Breach**\n\n"
        "How many trading days at the current pace before spot reaches the defensive trigger.\n\n"
        "Formula: gap% ÷ daily pace%   where daily pace = (ATR14 ÷ spot × 100) × Threat Multiplier\n\n"
        "- CE X.Xd = X.X days before spot reaches the CE defense trigger (2.5% above anchor)\n"
        "- PE X.Xd = X.X days before spot reaches the PE defense trigger (2.5% below anchor)\n"
        "- Lower number = more urgency. Shows '—' when anchor or threat data is unavailable.\n\n"
        "---\n\n"
        "**India VIX — 4 contextual regimes**\n\n"
        "VIX measures implied volatility. Its direction relative to price direction reveals market intent:\n\n"
        "| VIX | Market | Signal | Implication |\n"
        "|-----|--------|--------|-------------|\n"
        "| ↑ Rising | ↑ Up | ⚠️ Mean revert risk | Unusual combo — institutions hedging into a rally. "
        "Up move may not sustain. **CE caution.** |\n"
        "| ↑ Rising | ↓ Down | 🔴 Fall may continue | Fear-driven sell-off. VIX rising confirms bearish "
        "momentum. **PE position under pressure — extra confirmation to act.** |\n"
        "| ↓ Stable/falling | ↑ Up | ✅ Move confirmed | Normal bull regime. Complacency is healthy here. "
        "**CE safe to hold.** |\n"
        "| ↓ Stable/falling | ↓ Down | ⚠️ Complacency | Market falling but fear not rising — possible "
        "bounce setup or slow bleed. **Watch for reversal before acting on PE.** |"
    )

# Metrics bar
_daily_pace_pct = (atr14 / spot_now * 100 * threat_mult) if (spot_now > 0 and threat_mult > 0) else 0
if tue_anchor_available and _daily_pace_pct > 0:
    _ce_gap = max(0, (ce_def_trig_spot - spot_now) / spot_now * 100) if ce_def_trig_spot > 0 else 0
    _pe_gap = max(0, (spot_now - pe_def_trig_spot) / spot_now * 100) if pe_def_trig_spot > 0 else 0
    _ce_days = _ce_gap / _daily_pace_pct
    _pe_days = _pe_gap / _daily_pace_pct
    _dtb_val = f"CE {_ce_days:.1f}d · PE {_pe_days:.1f}d"
    _dtb_sub = "gap ÷ ATR×threat pace"
    _thr_sub = f"Ret {daily_ret_pct:+.1f}% · RelVol {rel_vol:.2f}"
else:
    _dtb_val = "—"
    _dtb_sub = "anchor needed"
    _thr_sub = f"Ret {daily_ret_pct:+.1f}% · RelVol {rel_vol:.2f}"

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1: ui.metric_card("DTE", f"{dte}",
                         sub="Wed/Thu — std IC" if dte >= 5 else "Fri/Mon/Tue — tight IC")
with c2: ui.metric_card("THREAT MULT", f"{threat_mult:.2f}",
                         sub=_thr_sub,
                         color="red" if threat_mult > 1.15 else "green")
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
    _pe_pull = _moat_pull(_entry_put_moats)
    _ce_pull = _moat_pull(_entry_call_moats)
    _pe_base = int(round(tue_close * 0.96  / 50) * 50)
    _ce_base = int(round(tue_close * 1.035 / 50) * 50)
    _pe_moat_warn = put_moats < _entry_put_moats and not pe_is_rolled
    _ce_moat_warn = call_moats < _entry_call_moats and not ce_is_rolled

    # Strike note: original formula or rolled context
    if pe_is_rolled:
        _pe_strike_note = (f"🔄 ROLLED {_pe_rolled.get('roll_type','?')} · "
                           f"anchor {_pe_rolled.get('anchor',0):,.0f} · "
                           f"date {_pe_rolled.get('anchor_date','?')}")
    else:
        _pe_strike_note = (f"−4% base {_pe_base:,}"
                           + (f" + {_pe_pull}pt moat pull ({_entry_put_moats} moats at entry)"
                              if _pe_pull else " · 0 moats at entry"))
    if ce_is_rolled:
        _ce_strike_note = (f"🔄 ROLLED {_ce_rolled.get('roll_type','?')} · "
                           f"anchor {_ce_rolled.get('anchor',0):,.0f} · "
                           f"date {_ce_rolled.get('anchor_date','?')}")
    else:
        _ce_strike_note = (f"+3.5% base {_ce_base:,}"
                           + (f" − {_ce_pull}pt moat pull ({_entry_call_moats} moats at entry)"
                              if _ce_pull else " · 0 moats at entry"))

    _card_title = "ENTRY STRIKES"
    if ce_is_rolled or pe_is_rolled:
        _rolled_sides = " + ".join(
            (["CE"] if ce_is_rolled else []) + (["PE"] if pe_is_rolled else []))
        _card_title = f"ENTRY STRIKES · {_rolled_sides} ROLLED"

    st.markdown(
        f"<div style='background:#0f172a;border-radius:10px;padding:12px 16px;"
        f"border:1px solid #1e293b;margin-bottom:10px;'>"
        f"<div style='font-size:13px;font-weight:700;color:#94a3b8;"
        f"letter-spacing:1.5px;margin-bottom:8px;'>{_card_title}</div>"
        f"<div style='display:flex;gap:16px;flex-wrap:wrap;'>"
        # PE strike
        f"<div>"
        f"<span style='font-size:14px;color:#94a3b8;'>PE SOLD </span>"
        f"<span style='font-size:20px;font-weight:900;"
        f"color:{'#fbbf24' if pe_is_rolled else '#16a34a'};'>{pe_sold:,}</span>"
        f"<div style='font-size:13px;color:#94a3b8;margin-top:2px;'>{_pe_strike_note}</div>"
        + (f"<div style='font-size:14px;font-weight:700;color:#f59e0b;margin-top:3px;'>"
           f"⚠️ PE moats {_entry_put_moats}→{put_moats} · Support thinning · Strike locked</div>"
           if _pe_moat_warn else "")
        + f"</div>"
        # CE strike
        f"<div>"
        f"<span style='font-size:14px;color:#94a3b8;'>CE SOLD </span>"
        f"<span style='font-size:20px;font-weight:900;"
        f"color:{'#fbbf24' if ce_is_rolled else '#dc2626'};'>{ce_sold:,}</span>"
        f"<div style='font-size:13px;color:#94a3b8;margin-top:2px;'>{_ce_strike_note}</div>"
        + (f"<div style='font-size:14px;font-weight:700;color:#f59e0b;margin-top:3px;'>"
           f"⚠️ CE moats {_entry_call_moats}→{call_moats} · Resistance weakening · Strike locked</div>"
           if _ce_moat_warn else "")
        + f"</div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True)
    def _frow(label, passed, value_str):
        icon = "✅" if passed else "❌"
        col  = "#14532d" if passed else "#7f1d1d"
        return (
            f"<div style='display:flex;align-items:center;gap:6px;margin:3px 0;'>"
            f"<span style='font-size:13px;'>{icon}</span>"
            f"<span style='font-size:15px;color:#000000;flex:1;'>{label}</span>"
            f"<span style='font-size:16px;font-weight:700;color:{col};'>{value_str}</span>"
            f"</div>"
        )

    def _side_card(side_tag, palette,
                   book_loss, prep_loss, book_profit, prep_profit,
                   adverse, favor,
                   def_roll_to, off_roll_to, def_trig_spot, off_trig_spot,
                   f1, f2, f3, f4, fp, canary_val, is_ce,
                   rolled_info=None):
        _roll_pct = "3.5%" if is_ce else "4%"
        if book_loss:
            bg    = palette[0]
            state = "🔴 BOOK LOSS — ROLL OUT"
            action = f"Buy back losing leg · Roll OUT {_roll_pct} from CMP → {def_roll_to:,}"
        elif prep_loss:
            bg    = "#ea580c"
            state = "⚠️ PREPARE TO BOOK LOSS"
            action = f"Approaching threshold · {_DEF_THR - adverse:.2f}% to trigger · Spot {def_trig_spot:,}"
        elif book_profit:
            bg    = "#0f766e"
            state = "🟢 BOOK PROFIT — ROLL IN"
            action = f"Buy back dead leg · Roll IN {_roll_pct} from CMP → {off_roll_to:,}"
        elif prep_profit:
            bg    = "#0369a1"
            state = "🔵 PREPARE TO BOOK PROFIT"
            action = f"Favorable drift building · {_OFF_THR - favor:.2f}% to trigger · Spot {off_trig_spot:,}"
        else:
            bg    = palette[4] if adverse < 0.5 and favor < 0.5 else palette[3]
            state = "✅ HOLD"
            action = (f"Def gap {_DEF_THR - adverse:.2f}% · Off gap {_OFF_THR - favor:.2f}% · "
                      f"Def trig {def_trig_spot:,} · Off trig {off_trig_spot:,}")

        txt_col = "#1e293b" if bg in _LIGHT_COLS else "white"

        rolled_banner = ""
        if rolled_info and rolled_info.get("active"):
            rolled_banner = (
                f"<div style='background:rgba(0,0,0,0.30);border-radius:6px;"
                f"padding:5px 10px;margin-bottom:8px;"
                f"font-size:11px;font-weight:700;color:#fbbf24;'>"
                f"🔄 ROLLED {rolled_info.get('roll_type','?')} · "
                f"anchor {float(rolled_info.get('anchor') or 0):,.0f} · "
                f"date {rolled_info.get('anchor_date','?')}"
                f"</div>"
            )

        vix_line = ""
        if vix_available and vix_rising:
            if is_ce:
                vix_line = (f"<div style='margin-top:4px;padding:4px 8px;border-radius:4px;"
                            f"background:rgba(0,0,0,0.25);color:#fef08a;"
                            f"font-size:14px;font-weight:700;'>"
                            f"⚠️ VIX RISING {vix_chg_pct:+.1f}% — CAUTION: up moves may revert</div>")
            else:
                vix_line = (f"<div style='margin-top:4px;padding:4px 8px;border-radius:4px;"
                            f"background:rgba(0,0,0,0.25);color:#bfdbfe;"
                            f"font-size:14px;font-weight:700;'>"
                            f"🔵 VIX RISING {vix_chg_pct:+.1f}% — EXTRA CONFIRMATION: fear-driven</div>")

        scorecard = (
            _frow("Drift ≥ 2.5% adverse",  f1, f"{adverse:.2f}%")
            + _frow("Threat Mult > 1.15",   f2, f"{threat_mult:.2f}")
            + _frow(f"Canary ≥ Day 2 ({canary_val}/4)", f3, f"Day {canary_val}")
            + _frow(f"Mom {'> 0 bullish' if is_ce else '< 0 bearish'}", f4, f"{mom_score:+.1f}%ATR")
        )
        st.markdown(
            f"<div style='background:{bg};border-radius:10px;padding:14px 16px;margin-bottom:8px;'>"
            f"<div style='color:{txt_col};font-size:14px;font-weight:700;"
            f"opacity:0.8;letter-spacing:1px;'>{side_tag}</div>"
            f"<div style='color:{txt_col};font-size:18px;font-weight:900;margin:3px 0 6px;'>{state}</div>"
            + rolled_banner
            + f"<div style='color:{txt_col};font-size:12px;font-weight:700;"
            f"opacity:0.9;margin-bottom:8px;'>{action}</div>"
            f"<div style='background:rgba(0,0,0,0.20);border-radius:6px;padding:8px 10px;'>"
            f"<div style='color:#e2e8f0;font-size:13px;font-weight:700;"
            f"margin-bottom:4px;letter-spacing:1px;'>FILTER SCORECARD — {fp}/4 PASS</div>"
            + scorecard + f"</div>" + vix_line + f"</div>",
            unsafe_allow_html=True)

    col_ce, col_pe = st.columns(2)
    with col_ce:
        _side_card("CE · CALL SIDE", CE_RED,
                   ce_book_loss, ce_prepare_loss, ce_book_profit, ce_prepare_profit,
                   ce_adverse, ce_favor,
                   ce_def_roll_to, ce_off_roll_to, ce_def_trig_spot, ce_off_trig_spot,
                   ce_f1, ce_f2, ce_f3, ce_f4, ce_fp, ce_canary, is_ce=True,
                   rolled_info=_ce_rolled)
    with col_pe:
        _side_card("PE · PUT SIDE", PE_GREEN,
                   pe_book_loss, pe_prepare_loss, pe_book_profit, pe_prepare_profit,
                   pe_adverse, pe_favor,
                   pe_def_roll_to, pe_off_roll_to, pe_def_trig_spot, pe_off_trig_spot,
                   pe_f1, pe_f2, pe_f3, pe_f4, pe_fp, pe_canary, is_ce=False,
                   rolled_info=_pe_rolled)

    # ── Strike-Path Corridor ──────────────────────────────────────────────────
    if ema_vals and spot_now > 0 and tue_anchor_available:
        _all_emas   = [(p, float(v)) for p, v in ema_vals.items() if v and float(v) > 0]
        _anc        = float(tue_close)
        _pct_anc    = lambda v: (float(v) - _anc) / _anc * 100 if _anc > 0 else 0

        # Pre-compute trigger levels
        _ce_prep_trig = int(round(_anc * (1 + _DEF_THR * 0.90 / 100) / 50) * 50)  # +2.25%
        _pe_prep_trig = int(round(_anc * (1 - _DEF_THR * 0.90 / 100) / 50) * 50)  # -2.25%
        _ce_prep_prof = int(round(_anc * (1 - _OFF_THR * 0.75 / 100) / 50) * 50)  # -1.35%
        _pe_prep_prof = int(round(_anc * (1 + _OFF_THR * 0.75 / 100) / 50) * 50)  # +1.35%

        def _sub(kind, val, extra=""):
            pct = _pct_anc(val)
            base = {
                "neutral":      "anchor",
                "cmp":          "current price",
                "above":        "moat EMA",
                "below":        "moat EMA",
                "sold_ce":      f"CE sold · {extra}" if extra else "CE sold",
                "sold_pe":      f"PE sold · {extra}" if extra else "PE sold",
                "book_loss":    "📕 BOOK LOSS",
                "prep_loss":    "⚠️ PREPARE LOSS",
                "book_profit":  "📗 BOOK PROFIT",
                "prep_profit":  "🔵 PREP PROFIT",
            }.get(kind, kind)
            return f"{pct:+.2f}% · {base}"

        def _col(kind):
            return {"neutral":"anchor","cmp":"blue",
                    "above":"red","sold_ce":"sold_ce",
                    "below":"green","sold_pe":"sold_pe",
                    "book_loss":"loss","prep_loss":"loss",
                    "book_profit":"profit","prep_profit":"profit"}.get(kind,"default")

        # ── CE strip ─────────────────────────────────────────────────────────
        _ce_items = [("ANCHOR", _anc, "neutral"), ("CMP", float(spot_now), "cmp")]
        # Loss triggers (above anchor, between CMP and CE_SOLD)
        if ce_def_trig_spot > 0:
            _ce_items.append(("PREP LOSS",  float(_ce_prep_trig),   "prep_loss"))
            _ce_items.append(("BOOK LOSS",  float(ce_def_trig_spot), "book_loss"))
        # Profit trigger (below anchor — market moved down, favorable for CE)
        if ce_off_trig_spot > 0:
            _ce_items.append(("PREP PROFIT", float(_ce_prep_prof),   "prep_profit"))
            _ce_items.append(("BOOK PROFIT", float(ce_off_trig_spot), "book_profit"))
        # EMA moats in corridor
        if ce_sold > 0:
            for p, v in _all_emas:
                if spot_now < v < ce_sold:
                    _ce_items.append((f"EMA{p}", v, "above"))
            _ce_moat_count = sum(1 for _, v, k in _ce_items if k == "above")
            _ce_note = f"{_ce_moat_count} moat{'s' if _ce_moat_count!=1 else ''}" if _ce_moat_count else "PATH CLEAR ⚠️"
            _ce_items.append((f"CE {ce_sold:,}", float(ce_sold), "sold_ce"))
        else:
            _ce_moat_count, _ce_note = 0, ""
        _ce_items.sort(key=lambda x: x[1])

        st.markdown("<div style='font-size:13px;color:#475569;margin-bottom:3px;'>📈 CE Corridor — all levels sorted by price · % from anchor on each</div>", unsafe_allow_html=True)
        _ce_cols = st.columns(max(len(_ce_items), 1))
        for i, (lbl, val, kind) in enumerate(_ce_items):
            _extra = _ce_note if kind == "sold_ce" else ""
            _stxt  = _sub(kind, val, _extra)
            with _ce_cols[i]:
                if kind == "book_loss":
                    st.error(f"🔴 **{lbl}**\n\n**{val:,.0f}**\n\n{_stxt}")
                elif kind == "prep_loss":
                    st.warning(f"🟠 **{lbl}**\n\n**{val:,.0f}**\n\n{_stxt}")
                elif kind == "book_profit":
                    st.success(f"🟢 **{lbl}**\n\n**{val:,.0f}**\n\n{_stxt}")
                elif kind == "prep_profit":
                    st.success(f"🔵 **{lbl}**\n\n**{val:,.0f}**\n\n{_stxt}")
                else:
                    ui.metric_card(lbl, f"{val:,.0f}", sub=_stxt, color=_col(kind))

        # ── PE strip ─────────────────────────────────────────────────────────
        _pe_items = [("ANCHOR", _anc, "neutral"), ("CMP", float(spot_now), "cmp")]
        # Loss triggers (below anchor, between PE_SOLD and CMP)
        if pe_def_trig_spot > 0:
            _pe_items.append(("PREP LOSS",  float(_pe_prep_trig),   "prep_loss"))
            _pe_items.append(("BOOK LOSS",  float(pe_def_trig_spot), "book_loss"))
        # Profit trigger (above anchor — market moved up, favorable for PE)
        if pe_off_trig_spot > 0:
            _pe_items.append(("PREP PROFIT", float(_pe_prep_prof),   "prep_profit"))
            _pe_items.append(("BOOK PROFIT", float(pe_off_trig_spot), "book_profit"))
        # EMA moats in corridor
        if pe_sold > 0:
            for p, v in _all_emas:
                if pe_sold < v < spot_now:
                    _pe_items.append((f"EMA{p}", v, "below"))
            _pe_moat_count = sum(1 for _, v, k in _pe_items if k == "below")
            _pe_note = f"{_pe_moat_count} moat{'s' if _pe_moat_count!=1 else ''}" if _pe_moat_count else "PATH CLEAR ⚠️"
            _pe_items.append((f"PE {pe_sold:,}", float(pe_sold), "sold_pe"))
        else:
            _pe_moat_count, _pe_note = 0, ""
        _pe_items.sort(key=lambda x: x[1])

        st.markdown("<div style='font-size:13px;color:#475569;margin:8px 0 3px;'>📉 PE Corridor — all levels sorted by price · % from anchor on each</div>", unsafe_allow_html=True)
        _pe_cols = st.columns(max(len(_pe_items), 1))
        for i, (lbl, val, kind) in enumerate(_pe_items):
            _extra_pe = _pe_note if kind == "sold_pe" else ""
            _stxt_pe  = _sub(kind, val, _extra_pe)
            with _pe_cols[i]:
                if kind == "book_loss":
                    st.error(f"🔴 **{lbl}**\n\n**{val:,.0f}**\n\n{_stxt_pe}")
                elif kind == "prep_loss":
                    st.warning(f"🟠 **{lbl}**\n\n**{val:,.0f}**\n\n{_stxt_pe}")
                elif kind == "book_profit":
                    st.success(f"🟢 **{lbl}**\n\n**{val:,.0f}**\n\n{_stxt_pe}")
                elif kind == "prep_profit":
                    st.success(f"🔵 **{lbl}**\n\n**{val:,.0f}**\n\n{_stxt_pe}")
                else:
                    ui.metric_card(lbl, f"{val:,.0f}", sub=_stxt_pe, color=_col(kind))

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
_vc_col  = CANARY_HEADER_COLOUR.get(_vc_lvl, "#94a3b8")

# Line 1: PE status · CE status → action
_pe_lbl = f"PE · D{pe_canary}" if pe_canary > 0 else "PE · Clear"
_ce_lbl = f"CE · D{ce_canary}" if ce_canary > 0 else "CE · Clear"
_pe_col = CANARY_HEADER_COLOUR.get(pe_canary, "#16a34a") if pe_canary > 0 else "#16a34a"
_ce_col = CANARY_HEADER_COLOUR.get(ce_canary, "#16a34a") if ce_canary > 0 else "#16a34a"
_act    = CANARY_ACTION.get(_vc_lvl, "WATCH")

# Line 2: dominant driver detail
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

# IC Shape — entry (locked) vs now (live)
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
# e3/e8/e16/e30 already computed at lines above from sig + ema_vals fallback
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

    _gap_lbl = ("BREATHING"   if _gap > 150 else
                "COMPRESSING" if _gap > 30  else
                "TOUCHING"    if _gap >= 0  else
                "ENTANGLED")
    _gap_col = ("#16a34a" if _gap > 150 else
                "#d97706" if _gap > 30  else
                "#ea580c" if _gap >= 0  else
                "#dc2626")

    # Gap as % CMP (headline — intuitive) and % ATR (VIX-normalised)
    _spot_v      = float(spot)
    _gap_cmp_pct = (_gap / _spot_v * 100) if _spot_v > 0 else 0
    _gap_atr_pct = (_gap / atr14   * 100) if atr14   > 0 else 0
    _gap_pct_str = f"{_gap_cmp_pct:.2f}% CMP · {_gap_atr_pct:.0f}% ATR"

    # Fast cluster slope
    _fast_slope  = (ema3_slope + ema8_slope) / 2
    _slope_arrow = "▲" if _fast_slope > 5 else "▼" if _fast_slope < -5 else "→"
    _slope_col   = "#16a34a" if _fast_slope > 5 else "#dc2626" if _fast_slope < -5 else "#94a3b8"
    _slope_lbl   = f"{_slope_arrow} {abs(_fast_slope):.0f} pts/day"

    # Cross proximity
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

    # Spot position with distance
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

    # Entry regime vs current
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
        # Cluster bands
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
        # Gap row
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
        # Regime row
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
        f"<span style='color:#e2e8f0;font-size:12px;font-weight:700;'>Shape {_reg_ic}</span></div>"
        f"<div style='background:#1e293b;border-radius:5px;padding:4px 10px;'>"
        f"<span style='color:#e2e8f0;font-size:12px;font-weight:700;'>Size {_reg_sz}</span></div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True)
