# pages/10_Options_Chain.py — Page 10: Options Chain Analysis Engine
# Four Headline Numbers · Greeks · Five Strike Models · Strike Synthesis
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P10 · Options Chain", layout="wide")
st_autorefresh(interval=60_000, key="p10")
st.title("Page 10 — Options Chain Analysis Engine")
st.caption("Greeks · Five Strike Models · Strike Synthesis · Most conservative per side is binding")

from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)
if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

# ── Data fetch ────────────────────────────────────────────────────────────────
# CHANGED: added get_nifty_futures import — required for futures premium/discount
from data.live_fetcher import get_nifty_spot, get_dual_expiry_chains, get_nifty_futures
from analytics.options_chain import OptionsChainEngine

spot          = get_nifty_spot()
futures_price = get_nifty_futures()   # ← NEW: live Nifty futures LTP

if spot == 0:
    from data.live_fetcher import get_nifty_daily
    df_t = get_nifty_daily()
    spot = float(df_t["close"].iloc[-1]) if not df_t.empty else 23000.0

chains   = get_dual_expiry_chains(spot)
near_exp = chains["near_expiry"]; far_exp  = chains["far_expiry"]
near_dte = chains["near_dte"];   far_dte  = chains["far_dte"]

choice = st.radio("Analyse expiry",
    [f"Far — {far_exp} ({far_dte} DTE) ← YOUR TRADE",
     f"Near — {near_exp} ({near_dte} DTE) — Intelligence"],
    horizontal=True)
is_far   = "Far" in choice
df_chain = chains["far"] if is_far else chains["near"]
dte      = far_dte if is_far else near_dte

atr14    = sig.get("atr14", 200.0)
net_skew = sig.get("net_skew", 0.0)
va_mult  = sig.get("mp_buf_mult", 0.75)

oc_eng = OptionsChainEngine()
# CHANGED: futures_price now passed — enables real futures premium calculation
oc_sig = oc_eng.signals(
    df_chain, spot, dte,
    atr14=atr14,
    va_buf_mult=va_mult,
    futures_price=futures_price,
)

# ── Banners ───────────────────────────────────────────────────────────────────
if sig.get("migration_detected"):
    st.error("🔴 OI MIGRATION DETECTED — review open positions.")
if not oc_sig["gex"].get("positive") and oc_sig["gex"].get("total_gex", 0) < 0:
    st.warning("⚠️ NEGATIVE GEX — Dealers amplifying moves. +300 pts both sides applied. Widen IC.")
pcr = oc_sig["pcr"]
if pcr < 0.7:
    st.warning("⚠️ PCR EXTREME LOW — Extreme bullish positioning. Widen CE side.")
elif pcr > 1.3:
    st.warning("⚠️ PCR EXTREME HIGH — Fear positioning. Widen PE side.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Four Headline Numbers
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 1 — Four Headline Numbers",
                  "Overall state of the options market at a glance")

PCR_COLOUR = ("red" if pcr < 0.7 else "red" if pcr > 1.3 else
              "amber" if pcr < 0.9 or pcr > 1.1 else "green")
fut_p = oc_sig.get("fut_premium", 0)

c1,c2,c3,c4 = st.columns(4)
with c1: ui.metric_card("NIFTY SPOT", f"{spot:,.0f}", sub="Live anchor", color="blue")
with c2:
    pcr_note = ("Extreme bullish — widen CE" if pcr < 0.7 else
                "Fear — widen PE" if pcr > 1.3 else
                "Balanced — ideal IC" if 0.9 <= pcr <= 1.1 else "Mild lean")
    ui.metric_card("PCR", f"{pcr:.2f}", sub=pcr_note, color=PCR_COLOUR)
with c3: ui.metric_card("MAX PAIN", f"{oc_sig['max_pain']:,.0f}",
                          sub=f"±{oc_sig['max_pain_dist']:,.0f} pts from spot")
with c4:
    fp_note = ("Bullish conviction — more CE room" if fut_p > 50 else
               "Bearish lean — more PE room" if fut_p < -50 else "Neutral")
    ui.metric_card("FUTURES PREMIUM", f"{fut_p:+.0f} pts", sub=fp_note,
                    color="amber" if abs(fut_p) > 50 else "default")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Greeks Context
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Greeks Context",
                  "Magnet strike · Theta/IV selling edge · Delta skew direction")

atm_iv   = oc_sig.get("atm_iv", 0)
straddle = oc_sig.get("straddle_price", 0)
magnet   = oc_sig.get("magnet_strike", 0)
th_iv    = oc_sig.get("theta_iv_ratio", 0)
d_skew   = oc_sig.get("delta_skew", "BALANCED")
iv_skew  = oc_sig.get("iv_skew", 0)

c1,c2,c3,c4,c5,c6 = st.columns(6)
with c1: ui.metric_card("ATM IV", f"{atm_iv:.1f}%", sub="ATM implied vol")
with c2: ui.metric_card("STRADDLE", f"{straddle:,.0f} pts", sub="Market maker implied move")
with c3: ui.metric_card("MAGNET STRIKE", f"{magnet:,}" if magnet else "—",
                          sub="Highest gamma — dealer hotspot",
                          color="red" if magnet and abs(magnet - spot) < 200 else "default")
with c4:
    th_note = ("Good — collect well" if th_iv >= 1.0 else
               "Borderline" if th_iv >= 0.7 else "Poor selling edge")
    th_col  = "green" if th_iv >= 1.0 else "amber" if th_iv >= 0.7 else "red"
    ui.metric_card("THETA/IV RATIO", f"{th_iv:.3f}", sub=th_note, color=th_col)
with c5:
    sk_note = ("Downside feared more — add PE buffer" if d_skew == "PUT_SKEW" else
               "Upside squeeze risk — add CE buffer" if d_skew == "CALL_SKEW" else "Balanced")
    sk_col  = "red" if d_skew != "BALANCED" else "green"
    ui.metric_card("DELTA SKEW", d_skew, sub=sk_note, color=sk_col)
with c6: ui.metric_card("IV SKEW (Put-Call)", f"{iv_skew:+.1f}%",
                          sub="Put IV minus Call IV at ATM",
                          color="amber" if abs(iv_skew) > 2 else "default")

with st.expander("Greeks plain English guide", expanded=False):
    ui.simple_technical(
        "Magnet strike: this is where dealer hedging is most violent. If spot moves toward it, moves amplify. If it's between spot and your strike — it acts as a buffer absorbing hedging before price reaches you.\n\nTheta/IV ratio above 1.0 = good time to sell — you're collecting strong time decay relative to uncertainty.\n\nDelta skew tells you which direction options traders are paying more to hedge.",
        "Magnet: highest gamma strike\nTheta/IV = |ATM Theta| / ATM IV\nDelta skew: compare |put delta @-100pts| vs |call delta @+100pts|\nPUT_SKEW = put delta larger = downside feared"
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Five Strike Models + Synthesis
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — Five Strike Models and Strike Synthesis",
                  "Five independent methods — most conservative per side is binding")

ui.simple_technical(
    "Five different mathematical approaches each suggest where your short strikes should go. They use different data and different logic — so they won't always agree. Showing all five lets you see the range of reasonable answers and their spread. The furthest from spot per side is highlighted as the binding recommendation.",
    "Binding CE = MAX of all five CE suggestions\nBinding PE = MIN of all five PE suggestions\nCE must always be above call wall\nPE must always be below put wall\nLot size = 65"
)
st.markdown("")

models     = oc_sig.get("models", {})
synthesis  = oc_sig.get("synthesis", {})
binding_ce = synthesis.get("binding_ce", 0)
binding_pe = synthesis.get("binding_pe", 0)
call_wall  = oc_sig.get("call_wall", 0)
put_wall   = oc_sig.get("put_wall", 0)

if models:
    MODEL_LABELS = {
        "10_delta":    "1. 10 Delta",
        "iv_exp_move": "2. IV Expected Move",
        "atr_1x":      "3a. ATR 1× (Aggressive)",
        "atr_1.5x":    "3b. ATR 1.5× (Balanced)",
        "atr_2x":      "3c. ATR 2× (Conservative)",
        "straddle":    "4. Straddle Breakeven",
        "wall_anchor": "5. Wall Anchor",
    }
    rows = []
    for key, m in models.items():
        ce = m["ce"]; pe = m["pe"]
        is_bind_ce = ce == binding_ce
        is_bind_pe = pe == binding_pe
        rows.append({
            "Method":       MODEL_LABELS.get(key, key),
            "CE Suggested": f"{'★ ' if is_bind_ce else ''}{ce:,}",
            "CE Dist":      f"{ce - spot:+,.0f}" if ce > 0 else "—",
            "PE Suggested": f"{'★ ' if is_bind_pe else ''}{pe:,}",
            "PE Dist":      f"{pe - spot:+,.0f}" if pe > 0 else "—",
            "Note":         m.get("note", ""),
        })
    # Binding summary row
    ce_vs_wall = (f"{'✅ Above wall' if binding_ce > call_wall else '⚠️ BELOW wall — wrong side'}"
                  if call_wall else "—")
    pe_vs_wall = (f"{'✅ Below wall' if binding_pe < put_wall else '⚠️ ABOVE wall — wrong side'}"
                  if put_wall else "—")
    rows.append({
        "Method":       "★ BINDING (Most Conservative)",
        "CE Suggested": f"{binding_ce:,}",
        "CE Dist":      f"{binding_ce - spot:+,.0f}",
        "PE Suggested": f"{binding_pe:,}",
        "PE Dist":      f"{binding_pe - spot:+,.0f}",
        "Note":         f"CE: {ce_vs_wall} | PE: {pe_vs_wall}",
    })

    df_m = pd.DataFrame(rows)
    def hl_binding(row):
        if "BINDING" in str(row["Method"]):
            return ["background-color:#dbeafe;font-weight:700"] * len(row)
        return [""] * len(row)
    st.dataframe(df_m.style.apply(hl_binding, axis=1), width="stretch", hide_index=True)

    st.markdown("")
    c1, c2, c3, c4 = st.columns(4)
    with c1: ui.metric_card("BINDING CE SHORT", f"{binding_ce:,}",
                              sub=f"Driven by: {synthesis.get('binding_ce_model', '—')}",
                              color="red")
    with c2: ui.metric_card("BINDING PE SHORT", f"{binding_pe:,}",
                              sub=f"Driven by: {synthesis.get('binding_pe_model', '—')}",
                              color="green")
    with c3: ui.metric_card("CALL WALL", f"{call_wall:,}" if call_wall else "—",
                              sub="CE must be above this", color="red")
    with c4: ui.metric_card("PUT WALL", f"{put_wall:,}" if put_wall else "—",
                              sub="PE must be below this", color="green")
else:
    st.info("Chain data not available — check Kite connection.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Wall and GEX
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 4 — Wall and GEX Analysis",
                  "Wall integrity · GEX environment · Combined verdict · Full analysis on Page 10B")

gex       = oc_sig.get("gex", {})
wall_int  = oc_sig.get("wall_integrity", {})
verdict   = oc_sig.get("wall_verdict", {})
flip_lvl  = gex.get("flip_level", 0)
total_gex = gex.get("total_gex", 0)
gex_env   = verdict.get("gex_environment", "NEUTRAL")
combined  = verdict.get("combined_verdict", "STANDARD")

VERDICT_MSGS = {
    "MAXIMUM_RANGE_CONFIDENCE": ("GEX flip = Call Wall — double barrier. Dealers and OI both defending same ceiling. Extremely strong CE protection.", "success"),
    "BOTH_LEGS_ELEVATED_RISK":  ("GEX negative + flip below call wall — amplification zone before wall. Both legs elevated risk.", "danger"),
    "RANGE_FAVOURABLE":         ("GEX positive — dealers pinning price in range. Favourable for IC.", "success"),
    "STANDARD":                 ("Standard conditions. Monitor walls and GEX for changes.", "info"),
}
msg, level = VERDICT_MSGS.get(combined, ("Standard conditions.", "info"))
ui.alert_box(f"Combined Verdict: {combined}", msg, level=level)

c1,c2,c3,c4,c5,c6 = st.columns(6)
with c1: ui.metric_card("GEX TOTAL", f"{total_gex:+,.0f}",
                          sub="+ = Pinning | − = Amplifying",
                          color="green" if total_gex > 0 else "red")
with c2: ui.metric_card("GEX FLIP LEVEL", f"{flip_lvl:,}" if flip_lvl else "—",
                          sub="Dealers switch to amplifying above")
with c3: ui.metric_card("GEX ENVIRONMENT", gex_env,
                          color="green" if gex_env == "PINNING" else "red")
with c4: ui.metric_card("CALL WALL INTEGRITY", wall_int.get("call_integrity", "—"),
                          color="green" if wall_int.get("call_integrity") == "SOLID" else "amber")
with c5: ui.metric_card("PUT WALL INTEGRITY", wall_int.get("put_integrity", "—"),
                          color="green" if wall_int.get("put_integrity") == "SOLID" else "amber")
with c6: ui.metric_card("GEX vs CALL WALL", verdict.get("ce_gex_relationship", "—"),
                          color="green" if verdict.get("ce_gex_relationship") == "DOUBLE_BARRIER" else
                                "red"   if verdict.get("ce_gex_relationship") == "GAP_DANGER" else "default")

st.caption("🔗 Full wall analysis, OI velocity, strike writeups, and cross-expiry synthesis → Page 10B")
