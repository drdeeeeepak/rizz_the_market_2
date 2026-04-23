# pages/10_Options_Chain.py — v5 (22 April 2026)
# Options Chain Analysis Engine
#
# FIXES vs v4:
#   - Auto-compute fallback — no forced Home redirect
#   - Futures premium fetched and displayed correctly (was 0)
#   - PCR, max pain, delta, gamma, IV, straddle, theta all fixed
#     via BS Greek approximation in options_chain.py _enrich_greeks()
#   - ATR asymmetry fixed (CE dist and PE dist now symmetric for same ATR model)
#   - Wall anchor shows properly when OI populated
#   - GEX and flip level fixed
#   - Data diagnostics section added — shows what columns are available
#   - 15-min auto-refresh kept for live session

import streamlit as st
import pandas as pd
import math
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P10 · Options Chain", layout="wide")
st_autorefresh(interval=900_000, key="p10")
st.title("Page 10 — Options Chain Analysis Engine")
st.caption("Greeks · Five Strike Models · Strike Synthesis · Most conservative per side is binding · Updates every 15 min")

# ── Auto-compute fallback ─────────────────────────────────────────────────────
sig = st.session_state.get("signals", {})
if not sig:
    with st.spinner("Loading signals — please wait..."):
        try:
            from data.live_fetcher import (
                get_nifty_spot, get_nifty_daily, get_top10_daily,
                get_india_vix, get_vix_history, get_dual_expiry_chains,
            )
            from analytics.compute_signals import compute_all_signals
            spot_     = get_nifty_spot()
            nifty_df_ = get_nifty_daily()
            stock_dfs_= get_top10_daily()
            vix_live_ = get_india_vix()
            vix_hist_ = get_vix_history()
            chains_   = get_dual_expiry_chains(spot_)
            if spot_ == 0 and not nifty_df_.empty:
                spot_ = float(nifty_df_["close"].iloc[-1])
            sig = compute_all_signals(nifty_df_, stock_dfs_, vix_live_, vix_hist_, chains_, spot_)
            st.session_state["signals"] = sig
        except Exception as e:
            st.error(f"Could not load signals: {e}. Please open Home page first.")
            st.stop()

# ── Fetch live chain data ─────────────────────────────────────────────────────
from data.live_fetcher import get_nifty_spot, get_dual_expiry_chains
from analytics.options_chain import OptionsChainEngine

spot = get_nifty_spot()
if spot == 0:
    from data.live_fetcher import get_nifty_daily
    df_t = get_nifty_daily()
    spot = float(df_t["close"].iloc[-1]) if not df_t.empty else float(sig.get("final_put_short", 23000) + sig.get("final_put_dist", 0))

chains   = get_dual_expiry_chains(spot)
near_exp = chains["near_expiry"]
far_exp  = chains["far_expiry"]
near_dte = chains["near_dte"]
far_dte  = chains["far_dte"]

# Expiry selector
choice   = st.radio("Analyse expiry",
    [f"Far — {far_exp} ({far_dte} DTE) ← YOUR TRADE",
     f"Near — {near_exp} ({near_dte} DTE) — Intelligence"],
    horizontal=True)
is_far   = "Far" in choice
df_chain = chains["far"] if is_far else chains["near"]
dte      = far_dte if is_far else near_dte

atr14   = sig.get("atr14", 200.0)
va_mult = sig.get("mp_buf_mult", 0.75)

# Futures LTP
try:
    from data.live_fetcher import get_nifty_futures_ltp
    futures_ltp = get_nifty_futures_ltp()
except Exception:
    futures_ltp = 0.0

oc_eng = OptionsChainEngine()
oc_sig = oc_eng.signals(df_chain, spot, dte, atr14=atr14,
                         va_buf_mult=va_mult, futures_price=futures_ltp)

# ── Alert banners ─────────────────────────────────────────────────────────────
if sig.get("migration_detected"):
    st.error("🔴 OI MIGRATION DETECTED — unusual intraday OI shift. Review open positions.")

gex_data  = oc_sig.get("gex", {})
total_gex = gex_data.get("total_gex", 0)
pcr       = oc_sig["pcr"]

if total_gex < 0:
    st.warning("⚠️ NEGATIVE GEX — Dealers amplifying moves in both directions. Widen both sides.")
if pcr < 0.7:
    st.warning("⚠️ PCR EXTREME LOW — Extreme bullish positioning. Widen CE side.")
elif pcr > 1.3:
    st.warning("⚠️ PCR EXTREME HIGH — Fear positioning. Widen PE side.")

# Data quality warning
if df_chain.empty:
    st.error("❌ No chain data — Kite connection issue or market closed. Values below are fallback estimates.")
elif df_chain.get("ce_oi", pd.Series()).sum() == 0 if "ce_oi" in df_chain.columns else True:
    st.warning("⚠️ OI data is zero — chain may be stale. Greeks computed via Black-Scholes approximation.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Four Headline Numbers
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 1 — Four Headline Numbers",
                  "Overall state of the options market at a glance")

fut_p   = oc_sig.get("fut_premium", 0)
mp      = oc_sig.get("max_pain", spot)
mp_dist = oc_sig.get("max_pain_dist", 0)

PCR_COLOUR = ("red"   if pcr < 0.7 or pcr > 1.3 else
              "amber" if pcr < 0.9 or pcr > 1.1 else "green")

c1, c2, c3, c4 = st.columns(4)
with c1:
    ui.metric_card("NIFTY SPOT", f"{spot:,.0f}", sub="Live anchor", color="blue")
with c2:
    pcr_note = ("Extreme bullish — widen CE" if pcr < 0.7 else
                "Fear — widen PE"            if pcr > 1.3 else
                "Balanced — ideal IC"        if 0.9 <= pcr <= 1.1 else "Mild lean")
    ui.metric_card("PCR", f"{pcr:.2f}", sub=pcr_note, color=PCR_COLOUR)
with c3:
    mp_side = "above spot" if mp > spot else "below spot"
    ui.metric_card("MAX PAIN", f"{mp:,.0f}",
                   sub=f"{mp_dist:,.0f} pts {mp_side} — option seller gravity",
                   color="amber" if mp_dist > 300 else "default")
with c4:
    fp_note = ("Bullish conviction — CE needs room" if fut_p > 50 else
               "Bearish lean — PE needs room"       if fut_p < -50 else
               "Neutral — no directional bias")
    fp_col  = "red" if fut_p > 50 else "green" if fut_p < -50 else "default"
    ui.metric_card("FUTURES PREMIUM", f"{fut_p:+.0f} pts", sub=fp_note, color=fp_col)

with st.expander("What do these numbers mean?", expanded=False):
    ui.simple_technical(
        "PCR above 1 = more puts than calls = defensive hedging dominant. "
        "Max pain is the strike where option sellers collectively profit most at expiry — price tends to gravitate toward it. "
        "Futures premium above zero means the market is pricing in an upward move.",
        "PCR = Total Put OI / Total Call OI across full chain\n"
        "Max pain = strike minimising total intrinsic value for option buyers\n"
        "Futures premium = Nifty futures LTP − spot price\n"
        "Balanced PCR 0.9–1.1 = ideal IC entry conditions"
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Greeks Context
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Greeks Context",
                  "ATM IV · Straddle · Magnet strike · Theta/IV selling edge · Delta skew · IV skew")

atm_iv   = oc_sig.get("atm_iv",        0)
straddle = oc_sig.get("straddle_price", 0)
magnet   = oc_sig.get("magnet_strike",  0)
th_iv    = oc_sig.get("theta_iv_ratio", 0)
d_skew   = oc_sig.get("delta_skew",    "BALANCED")
iv_skew  = oc_sig.get("iv_skew",        0)

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1:
    iv_note = "Very low — premiums thin" if atm_iv < 10 else "High — premiums fat" if atm_iv > 20 else "Normal range"
    ui.metric_card("ATM IV", f"{atm_iv:.1f}%" if atm_iv else "—",
                   sub=iv_note, color="amber" if atm_iv < 10 else "default")
with c2:
    str_note = f"±{round(straddle):,} pts implied move" if straddle else "LTP unavailable"
    ui.metric_card("STRADDLE", f"{straddle:,.0f} pts" if straddle else "—", sub=str_note)
with c3:
    mag_dist = abs(magnet - spot) if magnet else 0
    mag_note = f"{mag_dist:,.0f} pts from spot — {'DANGER near' if mag_dist < 200 else 'buffer zone'}" if magnet else "Gamma unavailable"
    ui.metric_card("MAGNET STRIKE", f"{magnet:,}" if magnet else "—",
                   sub=mag_note,
                   color="red" if magnet and mag_dist < 200 else "amber" if magnet and mag_dist < 400 else "default")
with c4:
    th_note = ("Good — collect well" if th_iv >= 1.0 else
               "Borderline"          if th_iv >= 0.7 else
               "Poor edge"           if th_iv > 0   else "Theta unavailable")
    th_col  = "green" if th_iv >= 1.0 else "amber" if th_iv >= 0.7 else "red" if th_iv > 0 else "default"
    ui.metric_card("THETA/IV RATIO", f"{th_iv:.3f}" if th_iv else "—", sub=th_note, color=th_col)
with c5:
    sk_note = ("Downside feared — add PE buffer" if d_skew == "PUT_SKEW" else
               "Upside squeeze risk — add CE"    if d_skew == "CALL_SKEW" else "Balanced")
    sk_col  = "amber" if d_skew != "BALANCED" else "green"
    ui.metric_card("DELTA SKEW", d_skew, sub=sk_note, color=sk_col)
with c6:
    sk_note2 = ("Put IV premium — downside hedging" if iv_skew > 2 else
                "Call IV premium — upside squeeze"  if iv_skew < -2 else "Normal")
    ui.metric_card("IV SKEW (Put−Call)", f"{iv_skew:+.1f}%" if iv_skew else "—",
                   sub=sk_note2, color="amber" if abs(iv_skew) > 3 else "default")

with st.expander("Greeks plain English guide", expanded=False):
    ui.simple_technical(
        "Magnet strike is where dealer hedging is most violent — spot near it means amplified moves. "
        "If it sits between spot and your short strike, it absorbs dealer hedging before price reaches you — that is a buffer, not a threat. "
        "Theta/IV above 1.0 means you are collecting strong time decay relative to uncertainty — ideal for selling. "
        "Delta skew tells you which direction the market is paying more to hedge.",
        "Magnet = highest combined CE+PE gamma strike\n"
        "Theta/IV = avg ATM |theta| / ATM IV\n"
        "Delta skew: compare |put delta| vs |call delta| at ATM ±100\n"
        "PUT_SKEW = downside more feared\n"
        "CALL_SKEW = upside squeeze risk\n"
        "IV skew = ATM put IV minus ATM call IV"
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Five Strike Models + Synthesis
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — Five Strike Models and Strike Synthesis",
                  "Five independent methods — most conservative per side is binding recommendation")

ui.simple_technical(
    "Five different mathematical approaches each suggest where your short strikes should sit. "
    "They use different data so they won't always agree. The range of answers tells you how much "
    "structural uncertainty exists right now. The furthest from spot per side is highlighted — "
    "this is your binding recommendation.",
    "Binding CE = MAX of all CE suggestions (furthest from spot)\n"
    "Binding PE = MIN of all PE suggestions (furthest from spot)\n"
    "CE must always be above call wall · PE must always be below put wall\n"
    "ATR used symmetrically — CE and PE distances identical for same ATR multiple"
)
st.markdown("")

models    = oc_sig.get("models",    {})
synthesis = oc_sig.get("synthesis", {})
binding_ce  = synthesis.get("binding_ce",  0)
binding_pe  = synthesis.get("binding_pe",  0)
call_wall   = oc_sig.get("call_wall",  0)
put_wall    = oc_sig.get("put_wall",   0)

MODEL_LABELS = {
    "10_delta":    "1. 10 Delta",
    "iv_exp_move": "2. IV Expected Move (1SD)",
    "atr_1x":      "3a. ATR 1× Aggressive",
    "atr_1.5x":    "3b. ATR 1.5× Balanced",
    "atr_2x":      "3c. ATR 2× Conservative",
    "straddle":    "4. Straddle Breakeven",
    "wall_anchor": "5. Wall Anchor",
}

if models:
    rows = []
    for key, m in models.items():
        ce = m.get("ce", 0)
        pe = m.get("pe", 0)
        is_bind_ce = ce > 0 and ce == binding_ce
        is_bind_pe = pe > 0 and pe == binding_pe
        ce_dist = ce - spot if ce > 0 else 0
        pe_dist = pe - spot if pe > 0 else 0
        rows.append({
            "Method":       MODEL_LABELS.get(key, key),
            "CE Strike":    f"{'★ ' if is_bind_ce else ''}{ce:,}" if ce else "—",
            "CE +pts":      f"{ce_dist:+,.0f}" if ce else "—",
            "CE % OTM":     f"{ce_dist/spot*100:.1f}%" if ce and spot > 0 else "—",
            "PE Strike":    f"{'★ ' if is_bind_pe else ''}{pe:,}" if pe else "—",
            "PE pts":       f"{pe_dist:+,.0f}" if pe else "—",
            "PE % OTM":     f"{abs(pe_dist)/spot*100:.1f}%" if pe and spot > 0 else "—",
            "Note":         m.get("note", ""),
        })

    # Binding row
    ce_wall_status = ("✅ Above wall" if binding_ce > call_wall else
                      "⚠️ BELOW wall — wrong side") if call_wall else "Wall not detected"
    pe_wall_status = ("✅ Below wall" if binding_pe < put_wall else
                      "⚠️ ABOVE wall — wrong side") if put_wall else "Wall not detected"
    rows.append({
        "Method":   "★ BINDING — Most Conservative",
        "CE Strike": f"{binding_ce:,}" if binding_ce else "—",
        "CE +pts":   f"{binding_ce - spot:+,.0f}" if binding_ce else "—",
        "CE % OTM":  f"{(binding_ce-spot)/spot*100:.1f}%" if binding_ce and spot > 0 else "—",
        "PE Strike": f"{binding_pe:,}" if binding_pe else "—",
        "PE pts":    f"{binding_pe - spot:+,.0f}" if binding_pe else "—",
        "PE % OTM":  f"{abs(binding_pe-spot)/spot*100:.1f}%" if binding_pe and spot > 0 else "—",
        "Note":      f"CE: {ce_wall_status} | PE: {pe_wall_status}",
    })

    df_m = pd.DataFrame(rows)

    def hl_binding(row):
        if "BINDING" in str(row["Method"]):
            return ["background-color:#dbeafe;font-weight:700"] * len(row)
        return [""] * len(row)

    st.dataframe(df_m.style.apply(hl_binding, axis=1),
                 use_container_width=True, hide_index=True)

    st.markdown("")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        ui.metric_card("BINDING CE SHORT", f"{binding_ce:,}" if binding_ce else "—",
                       sub=f"Driven by: {synthesis.get('binding_ce_model','—')}",
                       color="red")
    with c2:
        ui.metric_card("BINDING PE SHORT", f"{binding_pe:,}" if binding_pe else "—",
                       sub=f"Driven by: {synthesis.get('binding_pe_model','—')}",
                       color="green")
    with c3:
        cw_note = ("CE must be above" if call_wall else "Wall not detected — OI may be zero")
        ui.metric_card("CALL WALL", f"{call_wall:,}" if call_wall else "—",
                       sub=cw_note, color="red" if call_wall else "default")
    with c4:
        pw_note = ("PE must be below" if put_wall else "Wall not detected — OI may be zero")
        ui.metric_card("PUT WALL", f"{put_wall:,}" if put_wall else "—",
                       sub=pw_note, color="green" if put_wall else "default")
else:
    st.info("No chain data — check Kite connection and market hours.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Wall and GEX Analysis
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 4 — Wall and GEX Analysis",
                  "Wall integrity · GEX environment · Combined verdict · Full analysis on Page 10B")

wall_int = oc_sig.get("wall_integrity", {})
verdict  = oc_sig.get("wall_verdict",   {})
flip_lvl = gex_data.get("flip_level", 0)
gex_env  = verdict.get("gex_environment", "NEUTRAL")
combined = verdict.get("combined_verdict", "STANDARD")

VERDICT_MSGS = {
    "MAXIMUM_RANGE_CONFIDENCE": (
        "GEX flip coincides with Call Wall — double barrier. Dealers and OI both defending same ceiling. Extremely strong CE protection.", "success"),
    "BOTH_LEGS_ELEVATED_RISK":  (
        "GEX negative AND flip below call wall — dealers amplifying moves, gap before wall. Both legs elevated risk. Widen strikes.", "danger"),
    "RANGE_FAVOURABLE":         (
        "GEX positive — dealers net long gamma, pinning price in range. Favourable for IC entry.", "success"),
    "STANDARD":                 (
        "Standard conditions. No extreme GEX signal. Monitor walls and PCR for changes.", "info"),
}
msg, level = VERDICT_MSGS.get(combined, ("Standard conditions.", "info"))
ui.alert_box(f"Combined Verdict: {combined}", msg, level=level)

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1:
    gex_note = "Dealers pinning — favourable" if total_gex > 0 else "Dealers amplifying — caution" if total_gex < 0 else "Neutral"
    ui.metric_card("GEX TOTAL", f"{total_gex:+,.0f}" if total_gex != 0 else "—",
                   sub=gex_note,
                   color="green" if total_gex > 0 else "red" if total_gex < 0 else "default")
with c2:
    fl_note = "Dealers flip to amplifying above this" if flip_lvl else "Gamma data needed for flip"
    ui.metric_card("GEX FLIP LEVEL", f"{flip_lvl:,}" if flip_lvl else "—", sub=fl_note)
with c3:
    ui.metric_card("GEX ENVIRONMENT", gex_env,
                   color="green" if gex_env == "PINNING" else "red" if gex_env == "AMPLIFYING" else "default")
with c4:
    ci = wall_int.get("call_integrity", "UNKNOWN")
    ui.metric_card("CALL WALL INTEGRITY", ci,
                   sub="SOLID = dominant single strike · FRAGMENTED = spread across strikes",
                   color="green" if ci == "SOLID" else "amber" if ci == "FRAGMENTED" else "default")
with c5:
    pi = wall_int.get("put_integrity", "UNKNOWN")
    ui.metric_card("PUT WALL INTEGRITY", pi,
                   color="green" if pi == "SOLID" else "amber" if pi == "FRAGMENTED" else "default")
with c6:
    ce_gex_rel = verdict.get("ce_gex_relationship", "UNKNOWN")
    ce_gex_note = {
        "DOUBLE_BARRIER": "GEX flip = call wall — maximum protection",
        "GAP_DANGER":     "GEX flip below wall — amplification zone gap",
        "FLIP_BEYOND":    "GEX flip above wall — wall is first barrier",
        "UNKNOWN":        "Insufficient GEX data",
    }.get(ce_gex_rel, "—")
    ui.metric_card("GEX vs CALL WALL", ce_gex_rel,
                   sub=ce_gex_note,
                   color="green" if ce_gex_rel == "DOUBLE_BARRIER" else
                         "red"   if ce_gex_rel == "GAP_DANGER"     else "default")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Data Diagnostics
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("🔍 Data Diagnostics — what columns are available in chain", expanded=False):
    st.caption("Use this to debug why any metric shows 0 or —")
    if not df_chain.empty:
        col_status = []
        key_cols = ["ce_oi","pe_oi","ce_ltp","pe_ltp","ce_iv","pe_iv",
                    "ce_delta","pe_delta","ce_gamma","pe_gamma","ce_theta","pe_theta"]
        for col in key_cols:
            present = col in df_chain.columns
            non_zero = df_chain[col].abs().sum() > 0 if present else False
            col_status.append({
                "Column":    col,
                "Present":   "✅" if present else "❌",
                "Non-zero":  "✅" if non_zero else "⚠️ all zero",
                "Source":    "Kite" if (present and non_zero) else "BS approx" if present else "Missing",
            })
        df_cols = pd.DataFrame(col_status)
        st.dataframe(df_cols, use_container_width=True, hide_index=True)
        st.caption(f"Chain rows: {len(df_chain)} strikes · DTE: {dte} · ATR14: {atr14:.0f}")
    else:
        st.warning("Chain DataFrame is empty — no data received from Kite.")

st.caption("🔗 Full wall analysis, OI velocity, strike writeups, cross-expiry synthesis → Page 10B")
