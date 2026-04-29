# pages/10b_OI_Scoring.py — Page 10B: OI Intelligence Monitor
# Expiry Zones · OI Velocity + OIDI · Strike Intelligence · Wall + GEX · Cross-Expiry 2:30 PM
import streamlit as st
import pandas as pd
import pytz
import datetime
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P10B · OI Monitor", layout="wide")
st_autorefresh(interval=60_000, key="p10b")
st.title("Page 10B — OI Intelligence Monitor")
st.caption("Expiry Zones · OI Velocity · Strike Intelligence · Wall + GEX · Cross-Expiry Synthesis 2:30 PM+")

from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)
if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

from data.live_fetcher import get_nifty_spot, get_dual_expiry_chains
from analytics.oi_scoring import OIScoringEngine
from analytics.options_chain import OptionsChainEngine

spot = get_nifty_spot()
if spot == 0:
    from data.live_fetcher import get_nifty_daily
    df_t = get_nifty_daily()
    spot = float(df_t["close"].iloc[-1]) if not df_t.empty else 23000.0

chains   = get_dual_expiry_chains(spot)
near_exp = chains["near_expiry"]; far_exp  = chains["far_expiry"]
near_dte = chains["near_dte"];   far_dte  = chains["far_dte"]
atr14    = sig.get("atr14", 200.0)

eng    = OIScoringEngine()
oc_eng = OptionsChainEngine()

near_sc = eng.score_chain_near(chains["near"].copy(), near_dte) if not chains["near"].empty else pd.DataFrame()
far_sc  = eng.score_chain_far(chains["far"].copy(),  far_dte)  if not chains["far"].empty  else pd.DataFrame()
far_sig = oc_eng.signals(chains["far"],  spot, far_dte,  atr14=atr14) if not chains["far"].empty  else {}
near_sig= oc_eng.signals(chains["near"], spot, near_dte, atr14=atr14) if not chains["near"].empty else {}

near_mult = eng.get_dte_multiplier(near_dte)
far_mult  = eng.get_dte_multiplier(far_dte)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Expiry Zone and GEX Environment
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 1 — Expiry Zone and GEX Environment",
                  "How risky is each expiry's gamma environment · Are dealers pinning or amplifying")

col1, col2 = st.columns(2)
with col1:
    zone_n = eng.dte_zone(near_dte)
    c_n    = "red" if zone_n == "GAMMA_DANGER" else "amber" if zone_n == "WARNING" else "blue"
    ui.alert_box(f"Near {near_exp} · {near_dte} DTE — Intelligence Layer",
                 f"Zone: {zone_n} · Panic multiplier: {near_mult}×\n"
                 f"Scoring method: FLOW (% OI change)\n"
                 f"{'⚠️ GAMMA DANGER — Intraday spikes amplified. Do NOT panic-roll. Wait for EOD.' if near_dte <= 2 else 'Monitor OI flow signals intraday.'}",
                 level=c_n if c_n in ("red","amber") else "info")
with col2:
    zone_f = eng.dte_zone(far_dte)
    c_f    = "success" if far_dte > 5 else "warning" if far_dte > 2 else "danger"
    ui.alert_box(f"Far {far_exp} · {far_dte} DTE — YOUR TRADE ←",
                 f"Zone: {zone_f} · Panic multiplier: {far_mult}×\n"
                 f"Scoring method: STRUCTURAL (absolute OI levels)\n"
                 f"{'⚠️ GAMMA DANGER — EXIT only if buffer < 2×ATR. No leg-shift.' if far_dte <= 2 else 'Far OI changes slowly — structural score shows committed positions.'}",
                 level=c_f)

# GEX summary
far_gex   = far_sig.get("gex", {})
near_gex  = near_sig.get("gex", {})
call_wall = far_sig.get("call_wall", 0)
put_wall  = far_sig.get("put_wall", 0)
flip_lvl  = far_gex.get("flip_level", 0)
total_gex = far_gex.get("total_gex", 0)

c1,c2,c3,c4 = st.columns(4)
with c1: ui.metric_card("GEX (FAR)",  f"{total_gex:+,.0f}",
                          sub="+ Pinning | − Amplifying",
                          color="green" if total_gex > 0 else "red")
with c2: ui.metric_card("GEX FLIP",  f"{flip_lvl:,}" if flip_lvl else "—",
                          sub="Dealers flip here")
with c3: ui.metric_card("CALL WALL", f"{call_wall:,}" if call_wall else "—",
                          sub="CE must be above", color="red")
with c4: ui.metric_card("PUT WALL",  f"{put_wall:,}" if put_wall else "—",
                          sub="PE must be below", color="green")

if flip_lvl and call_wall:
    if abs(flip_lvl - call_wall) <= 50:
        ui.alert_box("DOUBLE BARRIER", f"GEX flip ({flip_lvl:,}) = Call wall ({call_wall:,}). Dealers and OI both defending same ceiling. Extremely strong CE protection.", level="success")
    elif flip_lvl < call_wall:
        ui.alert_box("GAP DANGER", f"GEX flip ({flip_lvl:,}) is below call wall ({call_wall:,}). Amplification zone between them — price can run to {flip_lvl:,} before wall holds.", level="warning")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — OI Velocity and OIDI
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — OI Velocity and Flow",
                  "Which side is growing faster · OIDI = speed × directional conviction")

ui.simple_technical(
    "A wall that looks big but is being removed is fragile. A wall that looks modest but is receiving aggressive fresh writing is getting stronger. Velocity catches this — it reads the LIVE FLOW of positioning, not just the snapshot size.",
    "Absolute Momentum = Total Put OI Chg − Total Call OI Chg\nVelocity = % Put OI Chg − % Call OI Chg\nOIDI = Velocity × Strike PCR\nHigher OIDI = stronger directional flow with conviction"
)
st.markdown("")

def _velocity_metrics(chain_df: pd.DataFrame, label: str):
    if chain_df.empty:
        st.info(f"{label}: no data")
        return
    total_pe_chg = float(chain_df["pe_oi_change"].sum()) if "pe_oi_change" in chain_df.columns else 0
    total_ce_chg = float(chain_df["ce_oi_change"].sum()) if "ce_oi_change" in chain_df.columns else 0
    abs_mom = total_pe_chg - total_ce_chg
    total_pe = float(chain_df["pe_oi"].sum()); total_ce = float(chain_df["ce_oi"].sum())
    pct_pe = (total_pe_chg / total_pe * 100) if total_pe > 0 else 0
    pct_ce = (total_ce_chg / total_ce * 100) if total_ce > 0 else 0
    velocity = pct_pe - pct_ce
    c1,c2,c3 = st.columns(3)
    with c1: ui.metric_card(f"{label} ABS MOMENTUM", f"{abs_mom:+,.0f}",
                              sub="+ = floor building faster",
                              color="green" if abs_mom > 0 else "red")
    with c2: ui.metric_card(f"{label} VELOCITY", f"{velocity:+.2f}%",
                              sub="% put growth minus % call growth",
                              color="green" if velocity > 0 else "red")
    with c3:
        direction = ("Floor building" if abs_mom > 500_000 else
                     "Ceiling building" if abs_mom < -500_000 else "Balanced")
        ui.metric_card(f"{label} DIRECTION", direction)

st.markdown("**Near Expiry — Flow Scoring**")
_velocity_metrics(chains["near"], "NEAR")
st.markdown("**Far Expiry — Structural Scoring**")
_velocity_metrics(chains["far"], "FAR")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Strike Intelligence (Far Expiry)
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — Strike Intelligence (Far Expiry — YOUR TRADE)",
                  "Active flags · Strike velocity labels · Wall writeups")

# Active flags
def _detect_flags(chain_df: pd.DataFrame, spot: float) -> list:
    if chain_df.empty or "ce_oi_change" not in chain_df.columns:
        return []
    flags = []
    atm = round(spot / 50) * 50
    otm_ce = chain_df[chain_df.index > atm].head(5)
    otm_pe = chain_df[chain_df.index < atm].tail(5)

    # HARD CEILING: call OI change > 2x put OI change at 3+ consecutive OTM CE strikes
    if len(otm_ce) >= 3:
        count = sum(1 for s in otm_ce.index
                    if chain_df.loc[s,"ce_oi_change"] > 2 * abs(chain_df.loc[s,"pe_oi_change"]))
        if count >= 3:
            wall_s = int(otm_ce["ce_oi"].idxmax()) if "ce_oi" in otm_ce.columns else 0
            flags.append(f"HARD CEILING at {wall_s:,} — aggressive resistance building at {count} strikes")

    # HARD FLOOR
    if len(otm_pe) >= 3:
        count = sum(1 for s in otm_pe.index
                    if chain_df.loc[s,"pe_oi_change"] > 2 * abs(chain_df.loc[s,"ce_oi_change"]))
        if count >= 3:
            floor_s = int(otm_pe["pe_oi"].idxmax()) if "pe_oi" in otm_pe.columns else 0
            flags.append(f"HARD FLOOR at {floor_s:,} — aggressive support building at {count} strikes")

    return flags

flags = _detect_flags(chains["far"], spot)
if flags:
    for f in flags:
        ui.alert_box("Active Flag", f, level="warning")

# Strike table with velocity labels (far expiry structural scoring)
if not far_sc.empty:
    ce_s = st.session_state.get("ce_short", 0)
    pe_s = st.session_state.get("pe_short", 0)

    display_cols = [c for c in ["pe_oi","pe_base","pe_wall","pe_velocity_label",
                                  "ce_oi","ce_base","ce_wall","ce_velocity_label",
                                  "net_score","position_action"] if c in far_sc.columns]

    def style_net(val):
        try:
            v = float(val)
            if v >= 3:  return "background-color:#16a34a;color:white;font-weight:700"
            if v >= 1:  return "background-color:#dcfce7;color:#14532d"
            if v == 0:  return "background-color:#f1f5f9;color:#5a6b8a"
            if v >= -2: return "background-color:#fee2e2;color:#7f1d1d"
            return "background-color:#dc2626;color:white;font-weight:700"
        except: return ""

    def style_velocity(val):
        if "BUILDING" in str(val): return "color:#16a34a;font-weight:700"
        if "CRUMBLING" in str(val): return "color:#dc2626;font-weight:700"
        return "color:#5a6b8a"

    def hl_strikes(row):
        if ce_s and row.name == ce_s: return ["background-color:#fee2e2"]*len(row)
        if pe_s and row.name == pe_s: return ["background-color:#dcfce7"]*len(row)
        return [""]*len(row)

    styled = far_sc[display_cols].style.map(style_net, subset=["net_score"] if "net_score" in display_cols else [])
    if "pe_velocity_label" in display_cols:
        styled = styled.map(style_velocity, subset=["pe_velocity_label","ce_velocity_label"])
    if ce_s or pe_s:
        styled = styled.apply(hl_strikes, axis=1)
    st.dataframe(styled, use_container_width=True, height=380)

    # Quick wall summary
    if "pe_oi" in far_sc.columns:
        c1,c2,c3,c4 = st.columns(4)
        top_pe = far_sc["pe_oi"].idxmax(); top_ce = far_sc["ce_oi"].idxmax()
        atm = round(spot/50)*50
        with c1: ui.metric_card("PUT WALL (Structural)", f"{top_pe:,}",
                                  sub=f"PE OI: {far_sc.loc[top_pe,'pe_oi']:,.0f}", color="green")
        with c2: ui.metric_card("CALL WALL (Structural)", f"{top_ce:,}",
                                  sub=f"CE OI: {far_sc.loc[top_ce,'ce_oi']:,.0f}", color="red")
        with c3:
            if atm in far_sc.index:
                ui.metric_card("ATM NET SCORE", f"{far_sc.loc[atm,'net_score']:.0f}" if "net_score" in far_sc.columns else "—",
                                sub="Structural at ATM",
                                color="green" if far_sc.loc[atm].get("net_score",0) > 0 else "red")
        with c4: ui.metric_card("FAR CHAIN ROWS", str(len(far_sc)), sub="Strikes loaded", color="blue")
else:
    st.warning("Far chain not available.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Dual Fortress + Complete Wall Analysis
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 4 — Dual Fortress and Wall Analysis",
                  "Wall integrity · Verdict · Near + far convergence at your strikes")

ce_s = st.session_state.get("ce_short", 0)
pe_s = st.session_state.get("pe_short", 0)
if ce_s and pe_s and not near_sc.empty and not far_sc.empty:
    conv = eng.convergence_check(near_sc, far_sc, int(ce_s), int(pe_s))
    c1,c2,c3,c4 = st.columns(4)
    with c1: ui.metric_card("PE NEAR WALL", f"{conv['pe_near_wall']}/10",
                              sub="Flow-based", color="green" if conv['pe_near_wall'] >= 7 else "amber")
    with c2: ui.metric_card("PE FAR WALL",  f"{conv['pe_far_wall']}/10",
                              sub="Structural", color="green" if conv['pe_far_wall'] >= 7 else "amber")
    with c3: ui.metric_card("CE NEAR WALL", f"{conv['ce_near_wall']}/10",
                              sub="Flow-based", color="green" if conv['ce_near_wall'] >= 7 else "amber")
    with c4: ui.metric_card("CE FAR WALL",  f"{conv['ce_far_wall']}/10",
                              sub="Structural", color="green" if conv['ce_far_wall'] >= 7 else "amber")
    if conv["pe_dual_fortress"]: st.success("✅ PE DUAL FORTRESS — Both near flow ≥7 and far structural ≥7. Max PE confidence. -100 pts leg-shift distance.")
    if conv["ce_dual_fortress"]: st.success("✅ CE DUAL FORTRESS — Both near flow ≥7 and far structural ≥7. Max CE confidence.")
    if not conv["pe_dual_fortress"] and not conv["ce_dual_fortress"]:
        st.info("Dual fortress not confirmed at current IC strikes.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Cross-Expiry Synthesis (activates 2:30 PM)
# ══════════════════════════════════════════════════════════════════════════════
ist = pytz.timezone("Asia/Kolkata")
now_ist = datetime.datetime.now(ist)
past_230 = now_ist.hour > 14 or (now_ist.hour == 14 and now_ist.minute >= 30)

ui.section_header("Section 5 — Cross-Expiry Synthesis",
                  f"{'🟢 ACTIVE — EOD positioning visible' if past_230 else '⏳ Activates at 2:30 PM IST — OI settling into final positions'}")

if past_230:
    if not chains["near"].empty and not chains["far"].empty:
        near_df = chains["near"]; far_df = chains["far"]

        # Velocity comparison
        def _chain_velocity(df):
            if "pe_pct_change" not in df.columns: return 0, 0
            return float(df["pe_pct_change"].mean()), float(df["ce_pct_change"].mean())

        n_pe_vel, n_ce_vel = _chain_velocity(near_df)
        f_pe_vel, f_ce_vel = _chain_velocity(far_df)

        near_active = abs(n_pe_vel) + abs(n_ce_vel) > abs(f_pe_vel) + abs(f_ce_vel)

        c1, c2 = st.columns(2)
        with c1:
            ui.alert_box("Velocity Comparison",
                         f"Near expiry activity: {'HIGH' if near_active else 'low'}\n"
                         f"Far expiry activity: {'HIGH' if not near_active else 'low'}\n"
                         f"{'Market focused on resolving this week — your far expiry is quiet and stable.' if near_active else 'Active positioning already building in YOUR trade expiry — watch direction carefully.'}",
                         level="info")

        # PCR comparison
        near_pcr = near_sig.get("pcr", 1.0)
        far_pcr  = far_sig.get("pcr", 1.0)
        pcr_diff = abs(near_pcr - far_pcr)
        convergence = pcr_diff < 0.2

        with c2:
            ui.alert_box("PCR Convergence",
                         f"Near PCR: {near_pcr:.2f} | Far PCR: {far_pcr:.2f}\n"
                         f"Difference: {pcr_diff:.2f}\n"
                         f"{'CONVERGENT — consistent conviction across expiries → IC range reliable' if convergence else 'DIVERGENT — different views near vs far → high uncertainty → widen both sides'}",
                         level="success" if convergence else "warning")

        # Intent analysis
        st.markdown("**Intent Analysis — What are near and far telling each other?**")
        patterns = []
        if "ce_pct_change" in near_df.columns:
            near_ce_unwinding = float(near_df.loc[near_df.index > round(spot/50)*50+100, "ce_pct_change"].mean() if not near_df.loc[near_df.index > round(spot/50)*50+100].empty else 0)
            if near_ce_unwinding < -5:
                patterns.append(("Call Unwinding in Near", "Resistance being removed — path opening upward. CE threat for far IC increasing.", "warning"))
        if "pe_pct_change" in far_df.columns:
            far_pe_writing = float(far_df.loc[far_df.index < round(spot/50)*50-100, "pe_pct_change"].mean() if not far_df.loc[far_df.index < round(spot/50)*50-100].empty else 0)
            if far_pe_writing > 5:
                patterns.append(("Put Writing in Far", "New put sellers in YOUR expiry — floor structurally strengthening. PE side safer.", "success"))

        if patterns:
            for name, msg, level in patterns:
                ui.alert_box(name, msg, level=level)
        else:
            st.info("No significant cross-expiry patterns detected at current OI levels.")
else:
    st.info("Cross-expiry synthesis will appear here at 2:30 PM IST. OI settles into final positions in the last hour — this section reads real positioning, not intraday noise.")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Your IC Strikes")
    ce_in = st.number_input("CE Short Strike", value=int(st.session_state.get("ce_short",0)), step=50)
    pe_in = st.number_input("PE Short Strike", value=int(st.session_state.get("pe_short",0)), step=50)
    if st.button("Set strikes", use_container_width=True):
        st.session_state["ce_short"] = ce_in
        st.session_state["pe_short"] = pe_in
        st.rerun()
    st.divider()
    st.caption(f"Spot: {spot:,.0f}")
    st.caption(f"Near: {near_exp} ({near_dte} DTE)")
    st.caption(f"Far:  {far_exp} ({far_dte} DTE)")
    st.caption(f"ATR14: {atr14:.0f} pts")
