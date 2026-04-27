# Home.py — premiumdecay v7 (27 Apr 2026)
# Added: Nifty Health Monitor bar, single get_nifty_1h_phase() fetch.

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

    # Single 1H fetch — used by Dow Theory phase engine every day
    nifty_1h = pd.DataFrame()
    if MODE != "PLANNING":
        try:
            nifty_1h = get_nifty_1h_phase()
        except Exception as _e:
            st.warning(f"1H phase data unavailable: {_e}")

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
        nifty_1h=nifty_1h,
    )

st.session_state["signals"] = sig

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

if data_ok and not nifty_df.empty:
    try:
        last_ts = nifty_df.index[-1]
        age_hrs = (datetime.datetime.now(pytz.utc) -
                   (last_ts.tz_localize("Asia/Kolkata").tz_convert("UTC")
                    if last_ts.tzinfo is None else last_ts.tz_convert("UTC"))
                   ).total_seconds() / 3600
        if age_hrs > 26:
            st.warning(f"⚠️ Data is {age_hrs:.0f}h old — EOD job may have failed.")
    except Exception: pass

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

# Narrative — the single most important sentence
st.markdown(
    f"<div style='background:#f0f9ff;border-left:4px solid {struct_col};"
    f"padding:12px 16px;border-radius:6px;margin-bottom:8px;"
    f"font-size:15px;color:#0f1724;font-weight:500;'>"
    f"{_narrative}"
    f"</div>",
    unsafe_allow_html=True
)

# Four metric cards
c1, c2, c3, c4 = st.columns(4)
with c1:
    ui.metric_card(
        _score_label, _score,
        sub=f"Tuesday=Entry · Other=Health",
        color=("green" if _score=="PRIME" else "blue" if _score=="GOOD"
               else "amber" if _score=="WAIT" else "red")
    )
with c2:
    ui.metric_card(
        "RETRACE DEPTH", f"{_retrace_pct:.0f}%",
        sub=f"{_sessions:.0f} session{'s' if _sessions!=1 else ''} in phase"
    )
with c3:
    ui.metric_card(
        "CE HEALTH", _ce_health,
        sub=f"{_ce_pts:,.0f} pts from LH/HH",
        color=("green" if _ce_health=="STRONG" else "blue" if _ce_health=="MODERATE"
               else "amber" if _ce_health=="WATCH" else "red")
    )
with c4:
    ui.metric_card(
        "PE HEALTH", _pe_health,
        sub=f"{_pe_pts:,.0f} pts from LL/HL",
        color=("green" if _pe_health=="STRONG" else "blue" if _pe_health=="MODERATE"
               else "amber" if _pe_health=="WATCH" else "red")
    )

# Proximity warnings
if _call_prox:
    st.error(f"⚠️ CALL PROXIMITY — Approaching call breach {_call_breach:,.0f}. Check Page 00.")
if _put_prox:
    st.error(f"⚠️ PUT PROXIMITY — Approaching put breach {_put_breach:,.0f}. Check Page 00.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# A — POSITION INPUT
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("📋 Position Input")
st.caption("Enter your open IC legs here. Home page only — never on Pages 1-12.")

with st.form("pos_form", clear_on_submit=False):
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        struct       = st.selectbox("Structure", ["Standard IC","Single Spread","IC with Calendar","Ratio","Diagonal","Custom"])
        entry_credit = st.number_input("Entry credit (pts)", value=0.0, step=0.5, min_value=0.0)
        mtm_pnl      = st.number_input("Current MtM P&L (pts, +ve=profit)", value=0.0, step=0.5)
    with fc2:
        ce_short = st.number_input("CE Short strike", value=0, step=50, min_value=0)
        ce_wing  = st.number_input("CE Long wing",    value=0, step=50, min_value=0)
        ce_lots  = st.number_input("CE lots",         value=1, step=1,  min_value=0)
        ce_exp   = st.text_input("CE Expiry",         value=str(far_exp))
    with fc3:
        pe_short = st.number_input("PE Short strike", value=0, step=50, min_value=0)
        pe_wing  = st.number_input("PE Long wing",    value=0, step=50, min_value=0)
        pe_lots  = st.number_input("PE lots",         value=1, step=1,  min_value=0)
        pe_exp   = st.text_input("PE Expiry",         value=str(far_exp))
    submitted = st.form_submit_button("🔍 Analyse Position", use_container_width=True)

if submitted:
    st.session_state.update({
        "ce_short": int(ce_short), "ce_wing": int(ce_wing),
        "pe_short": int(pe_short), "pe_wing": int(pe_wing),
        "ce_lots":  int(ce_lots),  "pe_lots": int(pe_lots),
        "ce_exp": ce_exp, "pe_exp": pe_exp,
        "entry_credit": float(entry_credit), "mtm_pnl": float(mtm_pnl),
        "structure": struct,
    })

pos     = {k: st.session_state.get(k, 0) for k in
           ["ce_short","ce_wing","pe_short","pe_wing","ce_lots","pe_lots","entry_credit","mtm_pnl"]}
has_pos = pos["ce_short"] > 0 or pos["pe_short"] > 0

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# B — MULTI-LENS INTEGRATED ASSESSMENT
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("🔬 Multi-Lens Integrated Assessment")

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
st.caption("MAX across all lenses per side · All lenses independent")

from config import WING_DISTANCE
fd_put  = sig.get("final_put_dist",  1200)
fd_call = sig.get("final_call_dist", 1200)
fpe     = sig.get("final_put_short",  int(spot - fd_put))
fce     = sig.get("final_call_short", int(spot + fd_call))
fpew    = sig.get("final_put_wing",   fpe  - WING_DISTANCE)
fcew    = sig.get("final_call_wing",  fce  + WING_DISTANCE)
sug_pe  = sig.get("suggested_pe_lens", "—")
sug_ce  = sig.get("suggested_ce_lens", "—")

c1,c2,c3,c4 = st.columns(4)
with c1: ui.metric_card("PE SHORT", f"{fpe:,}", sub=f"−{fd_put:,} pts · {sug_pe}", color="green")
with c2: ui.metric_card("PE WING",  f"{fpew:,}", sub=f"−{WING_DISTANCE:,} pts beyond short")
with c3: ui.metric_card("CE SHORT", f"{fce:,}", sub=f"+{fd_call:,} pts · {sug_ce}", color="red")
with c4: ui.metric_card("CE WING",  f"{fcew:,}", sub=f"+{WING_DISTANCE:,} pts beyond short")

with st.expander("📊 All Lens Distances", expanded=True):
    lens_table = sig.get("lens_table", {})
    if lens_table:
        import pandas as _pd
        rows = []
        for ln, dists in lens_table.items():
            pev = dists["pe"]; cev = dists["ce"]
            rows.append({
                "Lens":      ln,
                "PE Dist":   f"{'⭐ ' if ln==sug_pe else ''}{pev:,} pts",
                "PE %OTM":   f"{pev/spot*100:.1f}%" if spot>0 else "—",
                "PE Strike": f"~{int(spot-pev):,}" if spot>0 else "—",
                "CE Dist":   f"{'⭐ ' if ln==sug_ce else ''}{cev:,} pts",
                "CE %OTM":   f"{cev/spot*100:.1f}%" if spot>0 else "—",
                "CE Strike": f"~{int(spot+cev):,}" if spot>0 else "—",
            })
        df_l = _pd.DataFrame(rows)
        def hl(row):
            s = [""] * len(row)
            if "⭐" in str(row["PE Dist"]): s[1]=s[2]=s[3]="background-color:#dcfce7;font-weight:700"
            if "⭐" in str(row["CE Dist"]): s[4]=s[5]=s[6]="background-color:#fee2e2;font-weight:700"
            return s
        st.dataframe(df_l.style.apply(hl, axis=1), use_container_width=True, hide_index=True)
        st.caption("⭐ = most conservative. Green = PE driver. Red = CE driver.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# D — POSITION ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
if has_pos:
    st.subheader("📍 Open Position Analysis")
    ce_s = pos["ce_short"]; pe_s = pos["pe_short"]
    ce_buf = ce_s - spot if ce_s > 0 else 0
    pe_buf = spot - pe_s if pe_s > 0 else 0

    c1,c2,c3,c4 = st.columns(4)
    with c1: ui.metric_card("CE BUFFER", f"{ce_buf:,.0f} pts", sub=f"to CE {ce_s:,}",
                              color="green" if ce_buf>2*atr14 else "amber" if ce_buf>atr14 else "red")
    with c2: ui.metric_card("PE BUFFER", f"{pe_buf:,.0f} pts", sub=f"from PE {pe_s:,}",
                              color="green" if pe_buf>2*atr14 else "amber" if pe_buf>atr14 else "red")
    with c3: ui.metric_card("CE vs 2×ATR", f"{ce_buf-2*atr14:+,.0f} pts", sub=f"2×ATR={2*atr14:.0f}",
                              color="green" if ce_buf>2*atr14 else "red")
    with c4: ui.metric_card("PE vs 2×ATR", f"{pe_buf-2*atr14:+,.0f} pts", sub=f"2×ATR={2*atr14:.0f}",
                              color="green" if pe_buf>2*atr14 else "red")

    if _call_breach > 0 and ce_s > 0:
        gap = ce_s - _call_breach
        if gap < 0:   st.error(f"⚠️ DOW: Call breach {_call_breach:,.0f} exceeded. CE {ce_s:,} at risk.")
        elif gap<200: st.warning(f"⚠️ CE short {ce_s:,} is {gap:,.0f} pts above call breach {_call_breach:,.0f}.")
    if _put_breach > 0 and pe_s > 0:
        gap = _put_breach - pe_s
        if gap < 0:   st.error(f"⚠️ DOW: Put breach {_put_breach:,.0f} exceeded. PE {pe_s:,} at risk.")
        elif gap<200: st.warning(f"⚠️ PE short {pe_s:,} is {gap:,.0f} pts below put breach {_put_breach:,.0f}.")

    mtm = pos.get("mtm_pnl", 0); credit = pos.get("entry_credit", 0)
    if credit > 0:
        st.info(f"Entry credit: {credit:.1f} pts · MtM: {mtm:+.1f} pts ({mtm/credit*100:+.0f}% of credit)")

    if ce_buf < 2*atr14:
        if kills.get("RSI_ZONE_SKIP") or kills.get("K2"):
            st.error(f"🔴 RSI_ZONE_SKIP + CE buffer < 2×ATR. EXIT CE leg.")
        if kills.get("RSI_REGIME_FLIP") or kills.get("K1"):
            st.error(f"🔴 RSI_REGIME_FLIP + CE buffer < 2×ATR. EXIT CE leg.")
    if pe_buf < 2*atr14:
        if kills.get("RSI_ZONE_SKIP") or kills.get("K2"):
            st.error(f"🔴 RSI_ZONE_SKIP + PE buffer < 2×ATR. EXIT PE leg.")

st.divider()
st.caption("Each lens speaks independently. Suggested = most conservative. Lot size = 65.")

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
