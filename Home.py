# Home.py — premiumdecay v6 (22 April 2026)
# Position Manager · Multi-Lens Integrated Assessment · Final Strike Suggestion
#
# LOCKED CHANGES vs v5:
#   - _mode(): Tuesday EOD = PRIMARY_ENTRY, Wednesday = SECONDARY_ENTRY
#   - Master score collapsible explanation section added
#   - _lens_scores now shows correct labels (EMA structure, Options Chain, Dow Theory)
#   - sig["vix"] key now available for correct VIX display

import streamlit as st
import datetime, pytz, json
import pandas as pd
from pathlib import Path

st.set_page_config(page_title="premiumdecay · Home", layout="wide", page_icon="📊")

# ── Mode detection — LOCKED entry day logic ───────────────────────────────────
def _ist():
    return datetime.datetime.now(pytz.timezone("Asia/Kolkata"))

def _mode():
    n  = _ist()
    wd = n.weekday()   # Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
    t  = n.hour * 60 + n.minute

    if wd >= 5:
        return "PLANNING"

    # LOCKED: Tuesday 14:30–15:30 IST = PRIMARY IC entry window
    if wd == 1 and 14*60+30 <= t <= 15*60+30:
        return "ENTRY_PRIMARY"

    # LOCKED: Wednesday market hours = SECONDARY entry (not prohibited)
    if wd == 2 and 9*60+15 <= t <= 15*60+30:
        return "ENTRY_SECONDARY"

    if t < 9*60+15:
        return "PRE_MARKET"
    if 9*60+15 <= t <= 15*60+30:
        return "LIVE"
    if 15*60+30 < t <= 18*60:
        return "TRANSITION"
    return "PLANNING"

MODE = _mode()
_ML = {
    "LIVE":            ("🟢", "LIVE",                          "#16a34a"),
    "TRANSITION":      ("🟡", "TRANSITION · EOD computing",    "#d97706"),
    "PRE_MARKET":      ("🌅", "PRE-MARKET · Gap check",        "#7c3aed"),
    "PLANNING":        ("🌙", "PLANNING MODE",                  "#2563eb"),
    "ENTRY_PRIMARY":   ("🎯", "TUESDAY EOD — PRIMARY ENTRY",   "#dc2626"),
    "ENTRY_SECONDARY": ("🎯", "WEDNESDAY — SECONDARY ENTRY",   "#d97706"),
}
icon, mode_txt, mode_col = _ML.get(MODE, ("⚪", "—", "#94a3b8"))

st.markdown(
    f"<div style='display:flex;align-items:center;gap:12px;margin-bottom:4px;'>"
    f"<h1 style='margin:0;color:#0f2140;font-size:28px;'>premiumdecay</h1>"
    f"<span style='background:{mode_col};color:white;padding:3px 10px;border-radius:12px;"
    f"font-size:12px;font-weight:600;'>{icon} {mode_txt}</span></div>",
    unsafe_allow_html=True)
st.caption("Asymmetric Iron Condor · Nifty 50 · Biweekly Tuesday · 5% OTM · 7-day hold · EOD only")

# Entry mode banners
if MODE == "ENTRY_PRIMARY":
    st.success("🎯 **TUESDAY EOD — PRIMARY ENTRY WINDOW** · This is the ideal IC entry time. Near expiry closing. Far expiry beginning.")
elif MODE == "ENTRY_SECONDARY":
    st.info("🎯 **WEDNESDAY — SECONDARY ENTRY** · Valid entry if Tuesday was missed. Not prohibited.")

# ── Data load ─────────────────────────────────────────────────────────────────
from data.live_fetcher import (
    get_nifty_spot, get_nifty_daily, get_top10_daily,
    get_india_vix, get_vix_history, get_dual_expiry_chains, get_near_far_expiries,
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
    sig = compute_all_signals(nifty_df, stock_dfs, vix_live, vix_hist, chains, spot)

st.session_state["signals"] = sig

# ── Top metrics row ───────────────────────────────────────────────────────────
near_exp, far_exp = get_near_far_expiries()
near_dte = chains.get("near_dte", 0)
far_dte  = chains.get("far_dte",  7)
atr14    = sig.get("atr14", 200)

cols = st.columns(8)
with cols[0]: ui.metric_card("NIFTY SPOT",  f"{spot:,.0f}",              color="blue")
with cols[1]: ui.metric_card("INDIA VIX",   f"{sig.get('vix', vix_live):.1f}",
                               color="red" if vix_live > 20 else "amber" if vix_live > 16 else "green")
with cols[2]: ui.metric_card("ATR14",       f"{atr14:.0f} pts")
with cols[3]: ui.metric_card("NEAR DTE",    f"{near_dte}d",              sub=str(near_exp), color="red" if near_dte <= 2 else "default")
with cols[4]: ui.metric_card("FAR DTE",     f"{far_dte}d",               sub=str(far_exp),  color="green")
with cols[5]: ui.metric_card("NET SKEW",    f"{sig.get('net_skew',0):+.0f}", sub="CE-PE safety", color="green" if sig.get("net_skew",0) > 0 else "amber")
with cols[6]: ui.metric_card("REGIME",      sig.get("cr_regime", sig.get("p2_regime","—")), sub="EMA cluster")
with cols[7]: ui.metric_card("SIZE MULT",   f"{sig.get('size_multiplier',1.0):.0%}", sub="VIX-based", color="green" if sig.get("size_multiplier",1.0) >= 1.0 else "red")

# Dow breach alerts
if sig.get("put_breach_active"):
    st.error(f"🔴 PUT BREACH ACTIVE — Spot closed below put breach level {sig.get('put_breach_level',0):,.0f}. Structural support broken.")
if sig.get("call_breach_active"):
    st.error(f"🔴 CALL BREACH ACTIVE — Spot closed above call breach level {sig.get('call_breach_level',0):,.0f}. Structural resistance broken.")
if sig.get("pe_proximity_warning"):
    st.warning(f"⚠️ PE PROXIMITY — Spot within 1/3 ATR of recent pivot low {sig.get('recent_pivot_low',0):,.0f}. Structural support being tested.")
if sig.get("ce_proximity_warning"):
    st.warning(f"⚠️ CE PROXIMITY — Spot within 1/3 ATR of recent pivot high {sig.get('recent_pivot_high',0):,.0f}. Structural resistance being tested.")
if sig.get("pivot_staleness_flag"):
    st.info(f"ℹ️ PIVOT STALENESS — No recent pivot confirmed in {sig.get('bars_since_pivot',0)} trading days. Structural reference unreliable.")

# Staleness check
if data_ok and not nifty_df.empty:
    try:
        last_ts = nifty_df.index[-1]
        age_hrs = (datetime.datetime.now(pytz.utc) -
                   (last_ts.tz_localize("Asia/Kolkata").tz_convert("UTC")
                    if last_ts.tzinfo is None else last_ts.tz_convert("UTC"))
                   ).total_seconds() / 3600
        if age_hrs > 26:
            st.warning(f"⚠️ Data is {age_hrs:.0f}h old — EOD job may have failed.")
    except Exception:
        pass

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
        ce_exp   = st.text_input( "CE Expiry",        value=str(far_exp))
    with fc3:
        pe_short = st.number_input("PE Short strike", value=0, step=50, min_value=0)
        pe_wing  = st.number_input("PE Long wing",    value=0, step=50, min_value=0)
        pe_lots  = st.number_input("PE lots",         value=1, step=1,  min_value=0)
        pe_exp   = st.text_input( "PE Expiry",        value=str(far_exp))
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

# Kill switch banners
kills = sig.get("kill_switches", {})
if kills.get("RSI_DUAL_EXHAUSTION") or kills.get("K3"):
    st.error("🔴 RSI_DUAL_EXHAUSTION — Both timeframes exhausted. Flatten 1:1, +300 pts both sides.")
if kills.get("RSI_REGIME_FLIP") or kills.get("K1"):
    st.error("🔴 RSI_REGIME_FLIP — Weekly RSI flipped zones. Check buffer vs 2×ATR.")
if sig.get("BANKING_DAILY_COLLAPSE") or sig.get("sd6_collapse"):
    st.error("🔴 BANKING_DAILY_COLLAPSE — 3 of 4 banks daily RSI <40. No new entry.")
if sig.get("cr_hard_skip"):
    st.error("🔴 HARD SKIP — INSIDE_BEAR + 0 put moats + Strong Down. Do not enter.")
if sig.get("is_danger"):
    st.error("🔴 VIX DANGER — Active spike territory. Max distance both sides, 50% size.")
if sig.get("mp_initiative_both"):
    st.error("🔴 INITIATIVE + INITIATIVE — Market Profile double confirmation. Strong defensive roll trigger.")

col_m, col_scores, col_detail = st.columns([1, 1, 2])

with col_m:
    st.markdown(
        f"<div style='background:{master_col};border-radius:12px;padding:24px;text-align:center;'>"
        f"<p style='color:white;font-size:12px;margin:0;font-weight:700;letter-spacing:1px;'>MASTER SCORE</p>"
        f"<p style='color:white;font-size:56px;font-weight:900;margin:6px 0;line-height:1;'>{master}</p>"
        f"<p style='color:rgba(255,255,255,0.75);font-size:12px;margin:0;'>/ 100</p>"
        f"</div>",
        unsafe_allow_html=True)
    st.markdown(
        f"<div style='background:{master_col}20;border:1.5px solid {master_col};border-radius:8px;"
        f"padding:10px;margin-top:8px;text-align:center;'>"
        f"<b style='color:{master_col};font-size:13px;'>{verdict}</b></div>",
        unsafe_allow_html=True)

with col_scores:
    st.markdown("**Per-Lens Scores**")
    # Max points per lens for bar calculation
    LENS_MAX = {
        "EMA structure": 5, "RSI (P5-8)": 20, "Bollinger": 15,
        "Options Chain": 25, "VIX / IV": 10, "Mkt Profile": 20, "Dow Theory": 5
    }
    for lens, sc in lens_scores.items():
        max_pts = LENS_MAX.get(lens, 20)
        bar_w  = int(sc / max_pts * 100) if max_pts > 0 else 0
        bar_c  = "#16a34a" if sc >= max_pts * 0.75 else "#d97706" if sc >= max_pts * 0.4 else "#dc2626"
        st.markdown(
            f"<div style='margin-bottom:6px;'>"
            f"<div style='display:flex;justify-content:space-between;font-size:11px;margin-bottom:2px;'>"
            f"<span style='color:#334155;font-weight:600;'>{lens}</span>"
            f"<span style='color:{bar_c};font-weight:700;'>{sc}/{max_pts}</span></div>"
            f"<div style='background:#e2e8f0;border-radius:4px;height:6px;'>"
            f"<div style='background:{bar_c};width:{bar_w}%;height:6px;border-radius:4px;'></div>"
            f"</div></div>",
            unsafe_allow_html=True)

with col_detail:
    st.markdown("**Signal Summary — All Lenses**")
    summary_rows = [
        ("EMA Regime",     sig.get("cr_regime", sig.get("p2_regime","—")),              "Cluster + Stack"),
        ("Canary",         f"Day {sig.get('canary_level',0)} ({sig.get('canary_direction','—')})", "EMA deterioration"),
        ("MTF Alignment",  sig.get("mtf_alignment", sig.get("alignment","—")),           "RSI weekly × daily"),
        ("W Regime",       sig.get("weekly_regime","—"),                                  "Weekly RSI"),
        ("D Zone",         sig.get("daily_zone","—"),                                     "Daily RSI"),
        ("BB Regime",      sig.get("bb_regime","—"),                                      "Bollinger"),
        ("VIX State",      sig.get("vix_state","—"),                                      "VIX environment"),
        ("IVP",            f"{sig.get('ivp_1yr',50):.0f}% — {sig.get('ivp_zone','—')}",  "IV percentile"),
        ("VRP",            f"{sig.get('vrp',0):+.1f}%",                                  "IV minus HV20"),
        ("MP Nesting",     sig.get("mp_nesting","—"),                                     "Market Profile"),
        ("Behaviour",      sig.get("mp_behaviour","—"),                                   "Responsive/Initiative"),
        ("Breadth",        f"{sig.get('breadth_score',50):.0f}% — {sig.get('breadth_label','—')}", "Stock moat breadth"),
        ("GEX",            f"{sig.get('gex_total',0):+,.0f}",                            "Options chain"),
        ("PCR",            f"{sig.get('pcr',1.0):.2f}",                                   "Put/Call ratio"),
        ("Dow Structure",  sig.get("dow_structure","—"),                                  "Dow Theory"),
    ]
    for label, value, note in summary_rows:
        st.markdown(
            f"<div style='display:flex;gap:8px;margin-bottom:3px;font-size:11px;'>"
            f"<span style='width:110px;color:#334155;font-weight:600;flex-shrink:0;'>{label}</span>"
            f"<span style='flex:1;color:#0f1724;font-weight:600;'>{value}</span>"
            f"<span style='color:#94a3b8;'>{note}</span>"
            f"</div>", unsafe_allow_html=True)

# LOCKED: Master score explanation — collapsible, collapsed by default
with st.expander("ℹ️ How is the Master Score calculated?", expanded=False):
    st.markdown("""
**Master Score — 100 points total**

Six independent analytical lenses each score the current market conditions from their own perspective.
They never interfere with each other. The total is your trade-readiness score.
""")
    score_rows = [
        ["Options Chain (Page 10)", "25 pts", "OI structure, PCR balance, GEX environment, wall integrity"],
        ["RSI (Pages 05+06)",       "20 pts", "Weekly regime + daily zone alignment for IC entry quality"],
        ["Market Profile (Page 12)","20 pts", "Nesting, VA width, POC proximity, biweekly tinge"],
        ["Bollinger (Page 09)",     "15 pts", "Band position, walk modifier, squeeze state"],
        ["VIX / IV (Page 11)",      "10 pts", "VIX state, IVP zone, VRP sign"],
        ["Dow Theory (Page 00)",    "5 pts",  "Structural clarity — UPTREND/DOWNTREND scores highest, MIXED lowest"],
        ["EMA structural quality",  "5 pts",  "Regime + moat combination quality"],
        ["TOTAL",                   "100 pts",""],
    ]
    df_score = pd.DataFrame(score_rows, columns=["Engine", "Max Points", "What It Scores"])
    st.dataframe(df_score, use_container_width=True, hide_index=True)
    st.markdown("""
**Score Bands**

| Score | Verdict | Position Size |
|-------|---------|---------------|
| 0–34 | Stand Aside | 0% |
| 35–54 | Marginal — reduce size | 50% |
| 55–74 | Enter with caution | 75% |
| 75–100 | Enter — high confidence | 100% |

**Breadth multiplier applied AFTER score:**
8–10 stocks above EMA60 = 1.0× · 6–7 = 0.85× · 4–5 = 0.65× · 0–3 = 0.40×

**Any kill switch = absolute veto regardless of score.** Kill switches override the master score entirely.
""")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# C — FINAL STRIKE SUGGESTION + DISTANCE TRANSPARENCY
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("🎯 Final Strike Suggestion")
st.caption("Binding = MAX of all lens distances per side · All modifiers independent · Suggested is most conservative")

from config import WING_DISTANCE
fd_put  = sig.get("final_put_dist",  1200)
fd_call = sig.get("final_call_dist", 1200)
fpe     = sig.get("final_put_short",  int(spot - fd_put))
fce     = sig.get("final_call_short", int(spot + fd_call))
fpew    = sig.get("final_put_wing",   fpe  - WING_DISTANCE)
fcew    = sig.get("final_call_wing",  fce  + WING_DISTANCE)
sug_pe_lens = sig.get("suggested_pe_lens", "—")
sug_ce_lens = sig.get("suggested_ce_lens", "—")

c1,c2,c3,c4 = st.columns(4)
with c1:
    ui.metric_card("PE SHORT", f"{fpe:,}",
                   sub=f"−{fd_put:,} pts · Driven by: {sug_pe_lens}", color="green")
with c2:
    ui.metric_card("PE WING",  f"{fpew:,}", sub=f"−{WING_DISTANCE:,} pts beyond short")
with c3:
    ui.metric_card("CE SHORT", f"{fce:,}",
                   sub=f"+{fd_call:,} pts · Driven by: {sug_ce_lens}", color="red")
with c4:
    ui.metric_card("CE WING",  f"{fcew:,}", sub=f"+{WING_DISTANCE:,} pts beyond short")

with st.expander("📊 All Lens Distances — each lens speaks independently", expanded=True):
    lens_table = sig.get("lens_table", {})
    if lens_table:
        st.markdown("Each lens has independently assessed the safe distance. **You decide which to use.** The suggested strike is the most conservative (furthest from spot) across all lenses.")
        st.markdown("")
        rows = []
        for lens_name, dists in lens_table.items():
            pe_v = dists["pe"]; ce_v = dists["ce"]
            pe_pct = f"{pe_v/spot*100:.1f}%" if spot > 0 else "—"
            ce_pct = f"{ce_v/spot*100:.1f}%" if spot > 0 else "—"
            is_pe_max = lens_name == sug_pe_lens
            is_ce_max = lens_name == sug_ce_lens
            rows.append({
                "Lens":      lens_name,
                "PE Dist":   f"{'⭐ ' if is_pe_max else ''}{pe_v:,} pts",
                "PE % OTM":  pe_pct,
                "PE Strike": f"~{int(spot - pe_v):,}" if spot > 0 else "—",
                "CE Dist":   f"{'⭐ ' if is_ce_max else ''}{ce_v:,} pts",
                "CE % OTM":  ce_pct,
                "CE Strike": f"~{int(spot + ce_v):,}" if spot > 0 else "—",
            })
        df_lens = pd.DataFrame(rows)
        def hl_max(row):
            styles = [""] * len(row)
            if "⭐" in str(row["PE Dist"]): styles[1] = styles[2] = styles[3] = "background-color:#dcfce7;font-weight:700"
            if "⭐" in str(row["CE Dist"]): styles[4] = styles[5] = styles[6] = "background-color:#fee2e2;font-weight:700"
            return styles
        st.dataframe(df_lens.style.apply(hl_max, axis=1),
                     use_container_width=True, hide_index=True)
        st.caption("⭐ = most conservative (suggested). Green = PE driver. Red = CE driver.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# D — POSITION ANALYSIS (when strikes entered)
# ══════════════════════════════════════════════════════════════════════════════
if has_pos:
    st.subheader("📍 Open Position Analysis")

    ce_s = pos["ce_short"]; pe_s = pos["pe_short"]
    ce_dist_live = ce_s - spot if ce_s > 0 else 0
    pe_dist_live = spot - pe_s if pe_s > 0 else 0

    c1,c2,c3,c4 = st.columns(4)
    with c1: ui.metric_card("CE BUFFER", f"{ce_dist_live:,.0f} pts",
                              sub=f"Spot to CE short ({ce_s:,})",
                              color="green" if ce_dist_live > 2*atr14 else "amber" if ce_dist_live > atr14 else "red")
    with c2: ui.metric_card("PE BUFFER", f"{pe_dist_live:,.0f} pts",
                              sub=f"PE short ({pe_s:,}) to spot",
                              color="green" if pe_dist_live > 2*atr14 else "amber" if pe_dist_live > atr14 else "red")
    with c3: ui.metric_card("CE vs 2×ATR", f"{ce_dist_live - 2*atr14:+,.0f} pts",
                              sub=f"2×ATR = {2*atr14:.0f} pts",
                              color="green" if ce_dist_live > 2*atr14 else "red")
    with c4: ui.metric_card("PE vs 2×ATR", f"{pe_dist_live - 2*atr14:+,.0f} pts",
                              sub=f"2×ATR = {2*atr14:.0f} pts",
                              color="green" if pe_dist_live > 2*atr14 else "red")

    mtm    = pos.get("mtm_pnl", 0)
    credit = pos.get("entry_credit", 0)
    if credit > 0:
        pnl_pct = mtm / credit * 100 if credit else 0
        st.info(f"Entry credit: {credit:.1f} pts · Current MtM: {mtm:+.1f} pts ({pnl_pct:+.0f}% of credit)")

    if ce_dist_live < 2 * atr14:
        if kills.get("RSI_ZONE_SKIP") or kills.get("K2"):
            st.error(f"🔴 RSI_ZONE_SKIP + CE buffer < 2×ATR ({ce_dist_live:.0f} pts). EXIT CE leg.")
        if kills.get("RSI_REGIME_FLIP") or kills.get("K1"):
            st.error(f"🔴 RSI_REGIME_FLIP + CE buffer < 2×ATR. EXIT CE leg.")
    if pe_dist_live < 2 * atr14:
        if kills.get("RSI_ZONE_SKIP") or kills.get("K2"):
            st.error(f"🔴 RSI_ZONE_SKIP + PE buffer < 2×ATR ({pe_dist_live:.0f} pts). EXIT PE leg.")

st.divider()
st.caption("Each lens speaks independently. Suggested strike = most conservative across all lenses. Lot size = 65.")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("---")
    st.markdown("**Session**")
    if st.button("🚪 Logout / Clear Token", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        import os
        token_paths = [
            ".kite_token", "data/.kite_token",
            Path(__file__).parent / "data" / ".kite_token",
        ]
        for tp in token_paths:
            try:
                if os.path.exists(str(tp)):
                    os.remove(str(tp))
            except Exception:
                pass
        st.cache_data.clear()
        st.success("Logged out. Refresh the page to re-authenticate.")
        st.rerun()
    st.caption("Clears token and session. Refresh to re-login via Kite.")
