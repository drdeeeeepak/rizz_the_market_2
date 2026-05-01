# Home.py — premiumdecay v8 (27 Apr 2026)
# SuperTrend MTF integrated: fetches 15m/30m/5m, passes to compute_all_signals.
# Home score rescaled to 100 across 8 lenses (Option B).
# ST cascade flip shown as kill switch banner.

import streamlit as st
import datetime, pytz, json
import pandas as pd
from pathlib import Path

st.set_page_config(page_title="premiumdecay · Home", layout="wide", page_icon="📊")

def _ist():
    return datetime.datetime.now(pytz.timezone("Asia/Kolkata"))

def _mode():
    n = _ist(); wd = n.weekday(); t = n.hour * 60 + n.minute
    if wd >= 5:                  return "PLANNING"
    if 555 <= t < 9*60+15:       return "PRE_MARKET"
    if 9*60+15 <= t <= 15*60+30: return "LIVE"
    if 15*60+30 < t <= 18*60:    return "TRANSITION"
    return "PLANNING"

MODE = _mode()
_ML = {
    "LIVE":       ("🟢", "LIVE",                      "#16a34a"),
    "TRANSITION": ("🟡", "TRANSITION · EOD computing", "#d97706"),
    "PRE_MARKET": ("🌅", "PRE-MARKET · Gap check",    "#7c3aed"),
    "PLANNING":   ("🌙", "PLANNING MODE",              "#2563eb"),
}
icon, mode_txt, mode_col = _ML.get(MODE, ("⚪","—","#94a3b8"))

st.markdown(
    f"<div style='display:flex;align-items:center;gap:12px;margin-bottom:4px;'>"
    f"<h1 style='margin:0;color:#0f2140;font-size:28px;'>premiumdecay</h1>"
    f"<span style='background:{mode_col};color:white;padding:3px 10px;border-radius:12px;"
    f"font-size:12px;font-weight:600;'>{icon} {mode_txt}</span></div>",
    unsafe_allow_html=True)
st.caption("Asymmetric Iron Condor · Nifty 50 · Biweekly Tuesday · 5% OTM · 7-day hold · EOD only")

# ── Data load ─────────────────────────────────────────────────────────────────
from data.live_fetcher import (
    get_nifty_spot, get_nifty_daily, get_top10_daily,
    get_india_vix, get_vix_history, get_dual_expiry_chains,
    get_near_far_expiries, get_nifty_1h_phase,
    get_nifty_15m, get_nifty_30m, get_nifty_5m,
)
from analytics.compute_signals import compute_all_signals, load_saved_signals
import ui.components as ui

with st.spinner("Computing all signals…"):
    spot      = get_nifty_spot()
    nifty_df  = get_nifty_daily()
    stock_dfs = get_top10_daily()
    vix_live  = get_india_vix()
    vix_hist  = get_vix_history()
    chains    = get_dual_expiry_chains(spot if spot > 0 else 23000)

    # 1H — used by Dow Theory phase engine + ST proxy resampling (2H/4H)
    # Fetched regardless of mode — historical OHLCV available any time from Kite
    nifty_1h = pd.DataFrame()
    try:
        nifty_1h = get_nifty_1h_phase()
    except Exception as _e:
        st.warning(f"1H data unavailable: {_e}")

    # SuperTrend intraday TFs — only fetch during live session
    nifty_30m = pd.DataFrame()
    nifty_15m = pd.DataFrame()
    nifty_5m  = pd.DataFrame()
    if MODE == "LIVE":
        try:
            nifty_30m = get_nifty_30m()
        except Exception as _e:
            st.warning(f"30m data unavailable: {_e}")
        try:
            nifty_15m = get_nifty_15m()
        except Exception as _e:
            st.warning(f"15m data unavailable: {_e}")
        try:
            nifty_5m  = get_nifty_5m()
        except Exception as _e:
            pass   # 5m display-only, silent fail

data_ok = not nifty_df.empty and "close" in nifty_df.columns and len(nifty_df) > 5
if data_ok and spot == 0:
    spot = float(nifty_df["close"].iloc[-1])

if not data_ok:
    saved = load_saved_signals()
    if saved:
        st.info("⚠️ Live data unavailable. Showing last EOD computation.")
        sig = saved
    else:
        st.warning("⚠️ No data. Check Kite token in sidebar.")
        sig = {}
else:
    sig = compute_all_signals(
        nifty_df, stock_dfs, vix_live, vix_hist, chains, spot,
        nifty_1h  = nifty_1h,
        nifty_30m = nifty_30m,
        nifty_15m = nifty_15m,
        nifty_5m  = nifty_5m,
    )
    sig["_saved_at"] = datetime.datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%-d %b %-I:%M %p IST")

st.session_state["signals"] = sig
st.session_state["nifty_1h"] = nifty_1h   # used by Dow Theory page for candlestick chart

from page_utils import show_page_header
show_page_header(spot, sig.get("_saved_at", "—"))

# ── Top metrics row ───────────────────────────────────────────────────────────
near_exp, far_exp = get_near_far_expiries()
near_dte = chains.get("near_dte", 0)
far_dte  = chains.get("far_dte",  7)
atr14    = sig.get("atr14", 200)

cols = st.columns(8)
with cols[0]: ui.metric_card("NIFTY SPOT", f"{spot:,.0f}", color="blue")
with cols[1]: ui.metric_card("INDIA VIX",  f"{vix_live:.1f}", color="red" if vix_live>20 else "amber" if vix_live>16 else "green")
with cols[2]: ui.metric_card("ATR14",      f"{atr14:.0f} pts")
with cols[3]: ui.metric_card("NEAR DTE",   f"{near_dte}d", sub=str(near_exp), color="red" if near_dte<=2 else "default")
with cols[4]: ui.metric_card("FAR DTE",    f"{far_dte}d",  sub=str(far_exp),  color="green")
with cols[5]: ui.metric_card("NET SKEW",   f"{sig.get('net_skew',0):+.0f}", sub="CE-PE safety", color="green" if sig.get("net_skew",0)>0 else "amber")
with cols[6]: ui.metric_card("REGIME",     sig.get("cr_regime", sig.get("p2_regime","—")), sub="EMA cluster")
with cols[7]: ui.metric_card("SIZE MULT",  f"{sig.get('size_multiplier',1.0):.0%}", sub="VIX-based", color="green" if sig.get("size_multiplier",1.0)>=1.0 else "red")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# NIFTY HEALTH MONITOR
# ══════════════════════════════════════════════════════════════════════════════
_structure    = sig.get("dow_structure",       "MIXED")
_phase        = sig.get("dow_phase",           "MX")
_narrative    = sig.get("dow_narrative",       "—")
_score        = sig.get("dow_phase_score",     "WAIT")
_score_label  = sig.get("dow_dow_phase_score_label", "Nifty Health Monitor")
_ce_health    = sig.get("dow_ce_health",       "STRONG")
_pe_health    = sig.get("dow_pe_health",       "STRONG")
_ce_pts       = sig.get("dow_ce_health_pts",   0.0)
_pe_pts       = sig.get("dow_pe_health_pts",   0.0)
_call_breach  = sig.get("dow_call_breach",     0.0)
_put_breach   = sig.get("dow_put_breach",      0.0)
_call_prox    = sig.get("dow_call_prox_warn",  False)
_put_prox     = sig.get("dow_put_prox_warn",   False)
_retrace_pct  = sig.get("dow_retrace_pct",     0.0)
_sessions     = sig.get("dow_sessions_in_phase", 0.0)

_STRUCT_COL = {
    "UPTREND": "#16a34a", "DOWNTREND": "#dc2626",
    "MIXED_EXPANDING": "#d97706", "MIXED_CONTRACTING": "#d97706",
    "CONSOLIDATING": "#64748b",
}
_SCORE_COL = {
    "PRIME": "#16a34a", "GOOD": "#2563eb",
    "WAIT": "#d97706", "AVOID": "#ea580c", "NO_TRADE": "#dc2626",
}
_HEALTH_COL = {
    "STRONG": "#16a34a", "MODERATE": "#2563eb",
    "WATCH": "#d97706", "ALERT": "#ea580c", "BREACH": "#dc2626",
}

struct_col = _STRUCT_COL.get(_structure, "#64748b")
score_col  = _SCORE_COL.get(_score,     "#d97706")

st.markdown("### 🏥 Nifty Health Monitor")

st.markdown(
    f"<div style='background:#f0f9ff;border-left:4px solid {struct_col};"
    f"padding:12px 16px;border-radius:6px;margin-bottom:8px;"
    f"font-size:15px;color:#0f1724;font-weight:500;'>"
    f"{_narrative}"
    f"</div>",
    unsafe_allow_html=True
)

c1, c2, c3, c4 = st.columns(4)
with c1:
    ui.metric_card(
        _score_label, _score,
        sub=f"Tuesday=Entry · Other=Health",
        color=("green" if _score=="PRIME" else "blue" if _score=="GOOD" else
               "amber" if _score=="WAIT" else "red")
    )
with c2:
    ui.metric_card("Structure", _structure,
                   color=("green" if _structure=="UPTREND" else
                          "red" if _structure=="DOWNTREND" else "amber"))
with c3:
    ui.metric_card(
        "CE Health", f"{_ce_health} · {_ce_pts:,.0f}pts",
        color=("green" if _ce_health=="STRONG" else "blue" if _ce_health=="MODERATE" else
               "amber" if _ce_health=="WATCH" else "red")
    )
with c4:
    ui.metric_card(
        "PE Health", f"{_pe_health} · {_pe_pts:,.0f}pts",
        color=("green" if _pe_health=="STRONG" else "blue" if _pe_health=="MODERATE" else
               "amber" if _pe_health=="WATCH" else "red")
    )

if _call_prox:
    st.warning(f"⚠️ DOW: Spot approaching call breach level {_call_breach:,.0f} — CE leg proximity alert.")
if _put_prox:
    st.warning(f"⚠️ DOW: Spot approaching put breach level {_put_breach:,.0f} — PE leg proximity alert.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# B — MASTER SCORE
# ══════════════════════════════════════════════════════════════════════════════
master      = sig.get("master_score", 0)
verdict     = sig.get("master_verdict", "—")
master_col  = sig.get("master_colour",  "#94a3b8")
lens_scores = sig.get("_lens_scores", {})
kills       = sig.get("kill_switches", {})

if kills.get("RSI_DUAL_EXHAUSTION") or kills.get("K3"):
    st.error("🔴 RSI_DUAL_EXHAUSTION — Both timeframes exhausted. Flatten 1:1, +300 pts both sides.")
if kills.get("RSI_REGIME_FLIP") or kills.get("K1"):
    st.error("🔴 RSI_REGIME_FLIP — Weekly RSI flipped zones. Check buffer vs 2×ATR.")

c1, c2 = st.columns([1, 3])
with c1:
    st.markdown(
        f"<div style='background:{master_col};border-radius:12px;padding:20px;text-align:center;'>"
        f"<div style='color:white;font-size:42px;font-weight:800;line-height:1;'>{master}</div>"
        f"<div style='color:white;font-size:11px;font-weight:600;margin-top:4px;'>MASTER SCORE</div>"
        f"<div style='color:white;font-size:13px;font-weight:700;margin-top:8px;'>{verdict}</div>"
        f"</div>", unsafe_allow_html=True)
with c2:
    if lens_scores:
        sc = st.columns(len(lens_scores))
        for col, (name, pts) in zip(sc, lens_scores.items()):
            with col: ui.metric_card(name, str(pts), sub="pts")
    with st.expander("Full signal summary", expanded=False):
        rows = [
            ("DOW Structure",  _structure,                                            "Phase engine"),
            ("DOW Phase",      _phase,                                                "Current phase"),
            ("DOW Score",      _score,                                                _score_label),
            ("ST Shape",       sig.get("st_ic_shape","—"),                            "SuperTrend MTF"),
            ("ST PUT Band",    sig.get("st_put_stack",{}).get("band","—"),            "ST moat quality"),
            ("ST CALL Band",   sig.get("st_call_stack",{}).get("band","—"),           "ST moat quality"),
            ("Canary",         f"Day {sig.get('canary_level',0)} ({sig.get('canary_direction','—')})", "EMA"),
            ("MTF Alignment",  sig.get("mtf_alignment","—"),                          "RSI weekly×daily"),
            ("W Regime",       sig.get("weekly_regime","—"),                          "Weekly RSI"),
            ("D Zone",         sig.get("daily_zone","—"),                             "Daily RSI"),
            ("BB Regime",      sig.get("bb_regime","—"),                              "Bollinger"),
            ("VIX State",      sig.get("vix_state","—"),                              "VIX"),
            ("IVP",            f"{sig.get('ivp_1yr',50):.0f}% — {sig.get('ivp_zone','—')}", "IV pctile"),
            ("VRP",            f"{sig.get('vrp',0):+.1f}%",                           "IV-HV20"),
            ("MP Nesting",     sig.get("mp_nesting","—"),                             "Mkt Profile"),
            ("Behaviour",      sig.get("mp_behaviour","—"),                           "R/I"),
            ("Breadth",        f"{sig.get('breadth_score',50):.0f}% — {sig.get('breadth_label','—')}", "Stocks"),
            ("GEX",            f"{sig.get('gex_total',0):+,.0f}",                    "OI chain"),
            ("PCR",            f"{sig.get('pcr',1.0):.2f}",                          "Put/Call"),
        ]
        for label, value, note in rows:
            st.markdown(
                f"<div style='display:flex;gap:8px;margin-bottom:3px;font-size:11px;'>"
                f"<span style='width:110px;color:#334155;font-weight:600;flex-shrink:0;'>{label}</span>"
                f"<span style='flex:1;color:#0f1724;font-weight:600;'>{value}</span>"
                f"<span style='color:#94a3b8;'>{note}</span>"
                f"</div>", unsafe_allow_html=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# C — FINAL STRIKE SUGGESTION
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("🎯 Final Strike Suggestion")
st.caption("MAX across all lenses per side · All lenses independent · Score max = 100 (8 lenses)")

from config import WING_DISTANCE
fd_put  = sig.get("final_put_dist",  1200)
fd_call = sig.get("final_call_dist", 1200)
fpe     = sig.get("final_put_short",  int(spot - fd_put))
fce     = sig.get("final_call_short", int(spot + fd_call))
fpew    = sig.get("final_put_wing",   fpe  - WING_DISTANCE)
fcew    = sig.get("final_call_wing",  fce  + WING_DISTANCE)
sug_pe  = sig.get("suggested_pe_lens", "—")
sug_ce  = sig.get("suggested_ce_lens", "—")

# %OTM for final strikes
pe_pct  = fd_put  / spot * 100 if spot > 0 else 0.0
ce_pct  = fd_call / spot * 100 if spot > 0 else 0.0

c1,c2,c3,c4 = st.columns(4)
with c1: ui.metric_card("PE SHORT", f"{fpe:,}", sub=f"−{fd_put:,} pts · {pe_pct:.1f}% OTM · {sug_pe}", color="green")
with c2: ui.metric_card("PE WING",  f"{fpew:,}", sub=f"−{WING_DISTANCE:,} pts beyond short")
with c3: ui.metric_card("CE SHORT", f"{fce:,}", sub=f"+{fd_call:,} pts · {ce_pct:.1f}% OTM · {sug_ce}", color="red")
with c4: ui.metric_card("CE WING",  f"{fcew:,}", sub=f"+{WING_DISTANCE:,} pts beyond short")

# Canary pill — computed from src1 (gap) + src2 (momentum), both directions
_mscore = sig.get("cr_mom_score", 0.0)
_e3_h   = sig.get("ema3", sig.get("cr_ema_vals", {}).get(3, 0))
_e8_h   = sig.get("ema8", sig.get("cr_ema_vals", {}).get(8, 0))
_atr_h  = sig.get("cr_atr14", sig.get("atr14", 200)) or 200
_gap_pct_h  = abs(_e3_h - _e8_h) / _atr_h * 100 if _e3_h and _e8_h else 0
_can_dir_h  = "BULL" if _e3_h > _e8_h else "BEAR"
_gap_day_h  = 0 if _gap_pct_h > 55 else 1 if _gap_pct_h > 35 else 2 if _gap_pct_h > 15 else 3 if _gap_pct_h > 2 else 4

# src2 pe/ce from momentum score (same logic as Page 02)
def _s2h(s):
    if -5 <= s <= 5:  return 0, 0
    elif s > 0:       return (0,4) if s>32 else (1,3) if s>20 else (2,2) if s>11 else (3,1)
    else:
        a = abs(s);   return (4,0) if a>32 else (3,1) if a>20 else (2,2) if a>11 else (1,3)
_s2_pe_h, _s2_ce_h = _s2h(_mscore)

# src1 effective per direction
_s1_pe_h = _gap_day_h if _can_dir_h == "BEAR" else 0
_s1_ce_h = _gap_day_h if _can_dir_h == "BULL" else 0

_can_pe_h = max(_s1_pe_h, _s2_pe_h)
_can_ce_h = max(_s1_ce_h, _s2_ce_h)
_can_lvl  = max(_can_pe_h, _can_ce_h)
_can_side = "CE" if _can_ce_h >= _can_pe_h else "PE"

# Color = direction (BEAR=red, BULL=green), brightness = canary level
_dir_base = "#dc2626" if _can_dir_h == "BEAR" else "#16a34a"
_PE_G = {0:"#14532d",1:"#15803d",2:"#16a34a",3:"#4ade80",4:"#86efac"}
_CE_R = {0:"#7f1d1d",1:"#991b1b",2:"#dc2626",3:"#f87171",4:"#fca5a5"}
_lbl  = {0:"SINGING",1:"Day 1",2:"Day 2",3:"Day 3",4:"Day 4"}
_both_h = (_can_pe_h == 0 and _can_ce_h == 0)
_pe_bg = "#d97706" if _both_h else _PE_G.get(_can_pe_h,"#94a3b8")
_ce_bg = "#d97706" if _both_h else _CE_R.get(_can_ce_h,"#94a3b8")
_pe_tx = "#1e293b" if (not _both_h and _can_pe_h >= 3) else "white"
_ce_tx = "#1e293b" if (not _both_h and _can_ce_h >= 3) else "white"
st.markdown(
    f"<div style='display:flex;gap:6px;margin-bottom:8px;'>"
    f"<div style='flex:1;background:{_pe_bg};border-radius:8px;padding:8px 14px;'>"
    f"<div style='color:{_pe_tx};font-size:9px;font-weight:700;opacity:0.85;'>PE · PUT SIDE · Src1+Src2</div>"
    f"<div style='color:{_pe_tx};font-size:13px;font-weight:900;'>{_lbl.get(_can_pe_h,'—')} · {_can_dir_h}</div>"
    f"</div>"
    f"<div style='flex:1;background:{_ce_bg};border-radius:8px;padding:8px 14px;text-align:right;'>"
    f"<div style='color:{_ce_tx};font-size:9px;font-weight:700;opacity:0.85;'>CE · CALL SIDE · Src1+Src2</div>"
    f"<div style='color:{_ce_tx};font-size:13px;font-weight:900;'>{_lbl.get(_can_ce_h,'—')} · Gap {_gap_pct_h:.0f}%</div>"
    f"</div>"
    f"</div>", unsafe_allow_html=True)

# Skew bar with gap Rule 1 override
if _gap_day_h >= 3:
    _skew_h = "EXIT heavy side"; _skew_c = "#dc2626"; _forced_h = f" · Gap Day {_gap_day_h} — structure broken"
elif _gap_day_h == 2:
    _skew_h = "1:1 Forced"; _skew_c = "#ea580c"; _forced_h = f" · Gap Day 2 ({_gap_pct_h:.0f}% ATR) override"
elif abs(_mscore) > 20:
    _skew_h = "2:1 PE heavy" if _mscore > 0 else "1:2 CE heavy"
    _skew_c = "#16a34a" if _mscore > 0 else "#dc2626"; _forced_h = ""
else:
    _skew_h = "1:1 Balanced"; _skew_c = "#d97706"; _forced_h = ""
st.markdown(
    f"<div style='padding:8px 14px;border-radius:6px;background:{_skew_c}18;border-left:3px solid {_skew_c};margin-bottom:8px;'>"
    f"<span style='font-size:11px;font-weight:700;color:{_skew_c};'>IC SHAPE · {_skew_h}</span>"
    f"<span style='font-size:10px;color:#64748b;'> · Score {_mscore:+.1f}% ATR/day{_forced_h}</span>"
    f"</div>", unsafe_allow_html=True)

with st.expander("📊 All Lens Distances", expanded=True):
    lens_table = sig.get("lens_table", {})
    if lens_table:
        import pandas as _pd
        rows = []
        for ln, dists in lens_table.items():
            pev = dists["pe"]; cev = dists["ce"]
            # ⚠️ floor flag for ST row
            pe_warn = " ⚠️" if ln == "SuperTrend MTF" and sig.get("st_pe_floor_applied") else ""
            ce_warn = " ⚠️" if ln == "SuperTrend MTF" and sig.get("st_ce_floor_applied") else ""
            rows.append({
                "Lens":      ln,
                "PE Dist":   f"{'⭐ ' if ln==sug_pe else ''}{pev:,} pts{pe_warn}",
                "PE %OTM":   f"{pev/spot*100:.1f}%" if spot>0 else "—",
                "PE Strike": f"~{int(spot-pev):,}" if spot>0 else "—",
                "CE Dist":   f"{'⭐ ' if ln==sug_ce else ''}{cev:,} pts{ce_warn}",
                "CE %OTM":   f"{cev/spot*100:.1f}%" if spot>0 else "—",
                "CE Strike": f"~{int(spot+cev):,}" if spot>0 else "—",
            })
        # Expiry Drift row — Tuesday (expiry) close: PE sold 4% below, CE sold 3.5% above
        try:
            import datetime as _dt_ed, numpy as _np_ed
            from data.live_fetcher import get_nifty_daily as _gnd_ed
            _daily_ed = _gnd_ed()
            if not _daily_ed.empty:
                _today_ed = _dt_ed.date.today()
                _days_since_tue_ed = (_today_ed.weekday() - 1) % 7
                _last_tue_ed = _today_ed - _dt_ed.timedelta(days=_days_since_tue_ed)
                _trading_ed = set(_daily_ed.index.date)
                _anchor_ed = None
                for _off in range(7):
                    _cand = _last_tue_ed - _dt_ed.timedelta(days=_off)
                    if _cand in _trading_ed:
                        _anchor_ed = _cand; break
                if _anchor_ed:
                    _exp_close = float(_daily_ed[_daily_ed.index.date <= _anchor_ed]["close"].iloc[-1])
                    _pe_sold = int(round(_exp_close * 0.96  / 50) * 50)
                    _ce_sold = int(round(_exp_close * 1.035 / 50) * 50)
                    _pe_d = int(spot - _pe_sold) if spot > 0 else 0
                    _ce_d = int(_ce_sold - spot) if spot > 0 else 0
                    if _pe_d > 0 and _ce_d > 0:
                        rows.append({
                            "Lens":      f"Expiry Drift ({str(_anchor_ed)})",
                            "PE Dist":   f"{_pe_d:,} pts",
                            "PE %OTM":   f"{_pe_d/spot*100:.1f}%" if spot>0 else "—",
                            "PE Strike": f"{_pe_sold:,}",
                            "CE Dist":   f"{_ce_d:,} pts",
                            "CE %OTM":   f"{_ce_d/spot*100:.1f}%" if spot>0 else "—",
                            "CE Strike": f"{_ce_sold:,}",
                        })
        except Exception:
            pass
        df_l = _pd.DataFrame(rows)
        def hl(row):
            s = [""] * len(row)
            if "⭐" in str(row["PE Dist"]): s[1]=s[2]=s[3]="background-color:#dcfce7;font-weight:700"
            if "⭐" in str(row["CE Dist"]): s[4]=s[5]=s[6]="background-color:#fee2e2;font-weight:700"
            if "Expiry Drift" in str(row["Lens"]): s[0]=s[1]=s[2]=s[3]=s[4]=s[5]=s[6]="background-color:#fef9c3;"
            return s
        st.dataframe(df_l.style.apply(hl, axis=1), use_container_width=True, hide_index=True)
        st.caption("⭐ = most conservative. Green = PE driver. Red = CE driver. ⚠️ = ST floor applied. 🟡 Expiry Drift = sold strikes (PE −4%, CE +3.5% from expiry close).")

st.divider()
st.caption("Each lens speaks independently. Suggested = most conservative. Lot size = 65. Score max = 100 across 8 lenses.")

with st.sidebar:
    st.markdown("---")
    st.markdown("**Session**")
    if st.button("🚪 Logout / Clear Token", use_container_width=True):
        for key in list(st.session_state.keys()): del st.session_state[key]
        import os
        for tp in [".kite_token","data/.kite_token", Path(__file__).parent/"data"/".kite_token"]:
            try:
                if os.path.exists(str(tp)): os.remove(str(tp))
            except Exception: pass
        st.cache_data.clear()
        st.success("Logged out. Refresh to re-authenticate.")
        st.rerun()
    st.caption("Clears token and session.")

    with st.expander("🔍 Dow Debug", expanded=False):
        for k in ["dow_structure","dow_phase","dow_phase_score","dow_retrace_pct",
                  "dow_sessions_in_phase","dow_ph_last","dow_pl_last",
                  "dow_ce_health","dow_pe_health","dow_atr14_1h","dow_candles_used"]:
            st.markdown(f"**{k}:** {sig.get(k,'—')}")

    with st.expander("🔍 ST Debug", expanded=False):
        for k in ["st_ic_shape","st_home_score","st_flip_tfs",
                  "st_lens_pe_dist","st_lens_ce_dist",
                  "st_lens_pe_pct","st_lens_ce_pct",
                  "st_pe_floor_applied","st_ce_floor_applied"]:
            st.markdown(f"**{k}:** {sig.get(k,'—')}")
        put_stack = sig.get("st_put_stack", {})
        call_stack = sig.get("st_call_stack", {})
        if put_stack:
            st.markdown(f"**PUT normalised:** {put_stack.get('normalised','—')} — {put_stack.get('band','—')}")
        if call_stack:
            st.markdown(f"**CALL normalised:** {call_stack.get('normalised','—')} — {call_stack.get('band','—')}")
