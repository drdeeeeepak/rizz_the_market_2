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
#   - VIX-Adjusted DTB, Cycle-Filtering (Wed-Tue), and Live Data Priority included.
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
# Source 3 — Expiry anchor with phase-aware logic
import datetime as _dt, numpy as _np
tue_close = tue_atr = 0.0
tue_anchor_available = False
tue_anchor_date = ""
anchor_mode = "NORMAL"
try:
    from data.live_fetcher import get_nifty_daily, get_nifty_daily_live
    _now_ist        = _dt.datetime.now(pytz.timezone("Asia/Kolkata"))
    _today          = _now_ist.date()
    _cur_mins       = _now_ist.hour * 60 + _now_ist.minute
    _PROV_START     = 15 * 60 + 15
    _PROV_END       = 15 * 60 + 30
    _days_since_tue = (_today.weekday() - 1) % 7
    _last_tue       = _today - _dt.timedelta(days=_days_since_tue)
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
            anchor_mode = "PRE_EXPIRY"
            _prev_tue = _last_tue - _dt.timedelta(days=7)
            _ad = _find_anchor(_prev_tue)
            if _ad:
                tue_close, tue_atr = _load_anchor(_ad)
                tue_anchor_date = str(_ad) + " (prior expiry)"
                tue_anchor_available = True
        elif _is_expiry_day and _PROV_START <= _cur_mins < _PROV_END:
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
            anchor_mode = "POST_EXPIRY" if _is_expiry_day else "NORMAL"
            _ad = _find_anchor(_last_tue)
            if _ad:
                tue_close, tue_atr = _load_anchor(_ad)
                tue_anchor_date = str(_ad)
                tue_anchor_available = True
except Exception:
    pass
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
ce_threat_mult = pe_threat_mult = 0.0
_yday_ce_thr = _yday_pe_thr = 0.0
_today_move_pts = _yday_move_pts = 0.0
_prev_close_live = 0.0
try:
    from data.live_fetcher import get_nifty_daily_live as _gdl
    _dlive = _gdl()
    if not _dlive.empty and len(_dlive) >= 3:
        vol_sma14     = float(_dlive["volume"].rolling(14).mean().iloc[-1])
        _now_ist_t    = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
        _lc_date      = _dlive.index[-1].date() if hasattr(_dlive.index[-1], 'date') else _dlive.index[-1].to_pydatetime().date()
        _has_today    = (_lc_date == _now_ist_t.date())
        if _has_today:
            _today_row, _yday_row, _d2ago_row = _dlive.iloc[-1], _dlive.iloc[-2], _dlive.iloc[-3]
        else:
            _today_row, _yday_row, _d2ago_row = None, _dlive.iloc[-1], _dlive.iloc[-2]
        _prev_close_live = float(_yday_row["close"])
        _d2ago_close     = float(_d2ago_row["close"])
        if _has_today and _today_row is not None:
            _mkt_open     = _now_ist_t.replace(hour=9, minute=15, second=0, microsecond=0)
            _elapsed_min  = max(1, int((_now_ist_t - _mkt_open).total_seconds() / 60))
            _elapsed_frac = min(_elapsed_min / 375.0, 1.0)
            rel_vol         = (float(_today_row["volume"]) / _elapsed_frac) / vol_sma14 if vol_sma14 > 0 else 1.0
            _today_move_pts = (spot if spot > 0 else float(_today_row["close"])) - _prev_close_live
            daily_ret_pct   = _today_move_pts / _prev_close_live * 100 if _prev_close_live > 0 else 0.0
            threat_mult     = abs(daily_ret_pct) * rel_vol
        _yday_move_pts = _prev_close_live - _d2ago_close
        _yday_ret_pct  = _yday_move_pts / _d2ago_close * 100 if _d2ago_close > 0 else 0.0
        _yday_rel_vol  = float(_yday_row["volume"]) / vol_sma14 if vol_sma14 > 0 else 1.0
        _yday_ce_thr   = max(_yday_ret_pct,  0.0) * _yday_rel_vol
        _yday_pe_thr   = max(-_yday_ret_pct, 0.0) * _yday_rel_vol
except Exception:
    pass
if threat_mult == 0.0:
    daily_ret_pct = float(sig.get("daily_ret_pct", 0.0))
    rel_vol       = float(sig.get("rel_vol",       1.0))
    threat_mult   = float(sig.get("threat_mult",   0.0))
ce_threat_mult = max(daily_ret_pct,  0.0) * rel_vol
pe_threat_mult = max(-daily_ret_pct, 0.0) * rel_vol
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
# ── Rolled positions ──────────────────────────────────────────────────────────
from data.rolled_positions import (
    load_rolled, maybe_update_anchors as _mua, rolled_strike as _rs,
)
import datetime as _dtrp, pytz as _pyrp
_rolled = load_rolled()
_ist_rp = _dtrp.datetime.now(_pyrp.timezone("Asia/Kolkata"))
if _ist_rp.hour * 60 + _ist_rp.minute >= 15 * 60 + 15:
    _rolled = _mua(spot_now, float(tue_close or 0), sig, _rolled)
_ce_rolled   = _rolled.get("CE", {})
_pe_rolled   = _rolled.get("PE", {})
ce_is_rolled = bool(_ce_rolled.get("active"))
pe_is_rolled = bool(_pe_rolled.get("active"))
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
    if ce_is_rolled and _ce_rolled.get("strike"):
        ce_sold = int(_ce_rolled["strike"])
    if pe_is_rolled and _pe_rolled.get("strike"):
        pe_sold = int(_pe_rolled["strike"])
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
    _ce_anc = float(_ce_rolled["anchor"]) if ce_is_rolled else float(tue_close)
    _pe_anc = float(_pe_rolled["anchor"]) if pe_is_rolled else float(tue_close)
    ce_def_trig_spot = int(round(_ce_anc * (1 + _DEF_THR / 100) / 50) * 50)
    pe_def_trig_spot = int(round(_pe_anc * (1 - _DEF_THR / 100) / 50) * 50)
    pe_off_trig_spot = int(round(_pe_anc * (1 + _OFF_THR / 100) / 50) * 50)
    ce_off_trig_spot = int(round(_ce_anc * (1 - _OFF_THR / 100) / 50) * 50)
    ce_adverse = max((spot_now - _ce_anc) / _ce_anc * 100, 0.0)
    pe_adverse = max((_pe_anc - spot_now) / _pe_anc * 100, 0.0)
    pe_favor   = max((spot_now - _pe_anc) / _pe_anc * 100, 0.0)
    ce_favor   = max((_ce_anc - spot_now) / _ce_anc * 100, 0.0)
    ce_def_fired = ce_adverse >= _DEF_THR and ce_threat_mult > 1.15
    pe_def_fired = pe_adverse >= _DEF_THR and pe_threat_mult > 1.15
    ce_def_near  = not ce_def_fired and ce_adverse >= _DEF_THR * 0.75
    pe_def_near  = not pe_def_fired and pe_adverse >= _DEF_THR * 0.75
    ce_off_fired = ce_favor >= _OFF_THR
    pe_off_fired = pe_favor >= _OFF_THR
    ce_def_roll_to = int(round(spot_now * 1.035 / 50) * 50)
    pe_def_roll_to = int(round(spot_now * 0.960 / 50) * 50)
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
pe_canary = max(src1_pe, src2_pe, src3_pe)
ce_canary = max(src1_ce, src2_ce, src3_ce)
overall_canary = max(pe_canary, ce_canary, canary)
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
if tue_anchor_available and tue_close > 0 and spot_now > 0:
    ce_f1 = ce_adverse >= _DEF_THR
    ce_f2 = ce_threat_mult > 1.15
    ce_f3 = ce_canary >= 2
    ce_f4 = mom_score > 0
    ce_fp = int(ce_f1) + int(ce_f2) + int(ce_f3) + int(ce_f4)
    pe_f1 = pe_adverse >= _DEF_THR
    pe_f2 = pe_threat_mult > 1.15
    pe_f3 = pe_canary >= 2
    pe_f4 = mom_score < 0
    pe_fp = int(pe_f1) + int(pe_f2) + int(pe_f3) + int(pe_f4)
    ce_book_loss    = ce_f1 and ce_f2 and ce_f3 and ce_f4
    pe_book_loss    = pe_f1 and pe_f2 and pe_f3 and pe_f4
    ce_prepare_loss = (not ce_book_loss) and (
        ce_adverse >= _DEF_THR * 0.90 or (ce_adverse >= _DEF_THR * 0.80 and ce_fp >= 3))
    pe_prepare_loss = (not pe_book_loss) and (
        pe_adverse >= _DEF_THR * 0.90 or (pe_adverse >= _DEF_THR * 0.80 and pe_fp >= 3))
    ce_book_profit    = ce_favor >= _OFF_THR
    pe_book_profit    = pe_favor >= _OFF_THR
    ce_prepare_profit = (not ce_book_profit) and ce_favor >= _OFF_THR * 0.75
    pe_prepare_profit = (not pe_book_profit) and pe_favor >= _OFF_THR * 0.75
else:
    ce_f1=ce_f2=ce_f3=ce_f4=pe_f1=pe_f2=pe_f3=pe_f4=False
    ce_fp=pe_fp=0
    ce_book_loss=ce_prepare_loss=ce_book_profit=ce_prepare_profit=False
    pe_book_loss=pe_prepare_loss=pe_book_profit=pe_prepare_profit=False
PE_GREEN = {0:"#14532d", 1:"#15803d", 2:"#16a34a", 3:"#bbf7d0", 4:"#dcfce7"}
CE_RED   = {0:"#b91c1c", 1:"#dc2626", 2:"#ef4444", 3:"#fca5a5", 4:"#fee2e2"}
def _txt(lvl): return "#1e293b" if lvl >= 3 else "white"
BOTH_AMBER = "#d97706"
def _driver(s1, s2, s3):
    if s1 >= s2 and s1 >= s3 and s1 > 0:
        return "Source 1 (EMA Gap)"
    return "Source 2" if s2 >= s3 else "Source 3"
pe_driver = _driver(src1_pe, src2_pe, src3_pe)
ce_driver = _driver(src1_ce, src2_ce, src3_c
