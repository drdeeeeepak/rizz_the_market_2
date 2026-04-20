# pages/11_VIX_IV.py — Page 11: VIX / IV Framework
# Six VIX states · SMA-based classification · IVP · VRP · Advisory warnings only
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P11 · VIX / IV", layout="wide")
st_autorefresh(interval=900_000, key="p11")
st.title("Page 11 — VIX / IV Framework")
st.caption("India VIX state · IVP · VRP · No hard kills — all warnings advisory · Trader retains final authority")

sig = st.session_state.get("signals", {})
if not sig:
    st.info("⬅️ Open **Home** page first."); st.stop()

vix_live  = sig.get("vix", 0.0)
state     = sig.get("vix_state", sig.get("vix_zone", "STABLE_NORMAL"))
sma_200   = sig.get("vix_sma_200", 13.0)
sma_50    = sig.get("vix_sma_50",  13.0)
sma_20    = sig.get("vix_sma_20",  13.0)
ubb       = sig.get("vix_ubb",     22.0)
bb_width  = sig.get("vix_bb_width", 9.0)
spike_ok  = sig.get("vix_spike_confirmed", False)
stable_ok = sig.get("vix_stable_confirmed", True)
spike_cnt = sig.get("vix_spike_count", 0)
ivp       = sig.get("ivp_1yr", 50)
ivp_zone  = sig.get("ivp_zone", "IDEAL")
vrp       = sig.get("vrp", 0.0)
hv20      = sig.get("hv20", 0.0)
atm_iv    = sig.get("atm_iv", 0.0)
size_mult = sig.get("size_multiplier", 1.0)
warnings  = sig.get("warnings", [])

# ── State banners ─────────────────────────────────────────────────────────────
STATE_BANNERS = {
    "DANGER": ("🔴 DANGER — VIX IN ACTIVE SPIKE TERRITORY. Above UBB AND above 20 SMA. "
               "If you enter: USE MAXIMUM DISTANCE BOTH LEGS. Size 50%. Market can move 3-5% in a week. "
               "This is your maximum caution state. Proceed only with full awareness.", "danger"),
    "CAUTION": ("⚡ CAUTION — VIX above UBB but falling below 20 SMA. Spike may be resolving. "
                "Use wider distances. Monitor daily candle range — if contracts below 1.5 pts for 3 days → SPIKE_RESOLVING.", "warning"),
    "SPIKE_RESOLVING": ("★ BEST ENTRY WINDOW — VIX was above UBB, now fallen below 20 SMA with "
                        "candle range contracting. Premium still fat from spike but IV falling = tailwind. "
                        "Full size. Standard to wider distances. This is your best entry of the year.", "success"),
    "ELEVATED": ("⚡ ELEVATED — VIX above 200 SMA but below UBB. Premiums above average. "
                 "Good collection but realised movement higher. Use wider distances. Full size.", "warning"),
}
if state in STATE_BANNERS:
    msg, level = STATE_BANNERS[state]
    ui.alert_box(f"VIX State: {state}", msg, level=level)

if vrp < 0:
    ui.alert_box("VRP NEGATIVE — Selling Edge Gone",
                 f"ATM IV ({atm_iv:.1f}%) is BELOW HV20 ({hv20:.1f}%). "
                 "You are selling volatility cheaper than the market is realising. Edge absent. Widen both sides, reconsider entry.",
                 level="danger")

st.divider()

# ── Headline metrics ──────────────────────────────────────────────────────────
STATE_COLOURS = {
    "STABLE_LOW": "default", "STABLE_NORMAL": "green", "ELEVATED": "amber",
    "CAUTION": "amber", "DANGER": "red", "SPIKE_RESOLVING": "green",
}
c1,c2,c3,c4,c5,c6 = st.columns(6)
with c1: ui.metric_card("INDIA VIX", f"{vix_live:.1f}", sub="Live", color=STATE_COLOURS.get(state,"default"))
with c2: ui.metric_card("VIX STATE", state, sub="Advisory only", color=STATE_COLOURS.get(state,"default"))
with c3: ui.metric_card("SIZE", f"{size_mult:.0%}", sub="VIX-based guidance",
                          color="green" if size_mult >= 1.0 else "amber" if size_mult >= 0.75 else "red")
with c4: ui.metric_card("IVP (1yr)", f"{ivp:.0f}%", sub=ivp_zone,
                          color="green" if 25 <= ivp <= 80 else "red" if ivp < 15 else "amber")
with c5: ui.metric_card("VRP", f"{vrp:+.1f}%", sub="ATM IV minus HV20",
                          color="green" if vrp > 5 else "red" if vrp < 0 else "default")
with c6: ui.metric_card("SPIKE CONFIRMED", f"{'YES ⚠️' if spike_ok else 'No ✅'}",
                          sub=f"{spike_cnt}/3 thresholds", color="red" if spike_ok else "green")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — VIX Technical Setup
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 1 — India VIX Technical Setup",
                  "4 indicators on VIX itself — treating VIX as a price series")

ui.simple_technical(
    "The key insight: it's not about WHERE VIX is — it's about WHAT VIX is DOING and whether it is STABLE at that level. A high but stable VIX is your friend. A rising VIX is the enemy.",
    "200 SMA = gravitational centre (~13 historically)\nUBB = 200 SMA + 2σ (~20-22 for India VIX)\n50 SMA = medium-term fear trend\n20 SMA = short-term fear trend"
)
st.markdown("")

c1,c2,c3,c4,c5 = st.columns(5)
with c1: ui.metric_card("VIX 200 SMA", f"{sma_200:.1f}", sub="Gravitational centre")
with c2: ui.metric_card("VIX UBB", f"{ubb:.1f}", sub="Abnormal territory above this")
with c3: ui.metric_card("VIX 50 SMA", f"{sma_50:.1f}")
with c4: ui.metric_card("VIX 20 SMA", f"{sma_20:.1f}")
with c5: ui.metric_card("VIX BB WIDTH", f"{bb_width:.1f}", sub=">10 = spike active")

# Spike and stability indicators
c1, c2, c3 = st.columns(3)
with c1: ui.metric_card("SPIKE DETECTED", f"{spike_cnt}/3 thresholds met",
                          sub="Any 2 of 3 = confirmed",
                          color="red" if spike_ok else "green")
with c2: ui.metric_card("STABLE CONFIRMED", "YES ✅" if stable_ok else "NO ⚠️",
                          sub="All 3 conditions needed",
                          color="green" if stable_ok else "amber")
with c3: ui.metric_card("ABOVE UBB", "YES ⚠️" if vix_live > ubb else "No ✅",
                          color="red" if vix_live > ubb else "green")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Six VIX States
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Six VIX Environment States",
                  "All states permit trading — warnings are advisory, not blocking")

import pandas as pd
rows = [
    ["STABLE_LOW",      "Below 200 SMA, stable",           "None",         "Thin",      "Tighter",     "100%"],
    ["STABLE_NORMAL",   "Near 200 SMA, SMAs converging",   "None",         "Normal",    "Standard",    "100%"],
    ["ELEVATED",        "Above 200 SMA, below UBB",        "Mild caution", "Above avg", "Wider",       "100%"],
    ["CAUTION",         "Above UBB, below 20 SMA",         "Orange warn",  "Very fat",  "+1.5×ATR",    "75%"],
    ["DANGER",          "Above UBB AND above 20 SMA",      "Red warn MAX", "Extreme",   "Maximum",     "50%"],
    ["SPIKE_RESOLVING", "Was >UBB, now <20 SMA, settling", "Best window ★","Still fat", "Standard+",   "100%"],
]
df_states = pd.DataFrame(rows, columns=["State","VIX Condition","Warning","Premium","Distance","Size"])
def hl_state(val):
    if val == state: return "background-color:#dbeafe;font-weight:700"
    return ""
st.dataframe(df_states.style.map(hl_state, subset=["State"]),
             use_container_width=True, hide_index=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — IVP
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — IVP: Implied Volatility Percentile",
                  "Is today's premium historically cheap or expensive?")

ui.simple_technical(
    f"IVP tells you WHERE today's VIX sits in its historical distribution over the past year. Current IVP: {ivp:.0f}% — today's VIX is higher than {ivp:.0f}% of days in the past year.",
    "IVP = % of past 252 days where VIX was below today's level\nSource: historical India VIX closes"
)
st.markdown("")

IVP_DATA = [
    ["Below 15%",  "HISTORICALLY_LOW",  "Premiums at annual lows — reduce size"],
    ["15%-25%",    "BELOW_AVERAGE",     "Below average — reduce size slightly"],
    ["25%-70%",    "IDEAL",             "Normal historical range — full size standard IC"],
    ["70%-80%",    "HISTORICALLY_HIGH", "Fat premium but IV mean reversion likely"],
    ["Above 80%",  "EXTREME",           "Very elevated — IC still works, IV tailwind on your side"],
]
df_ivp = pd.DataFrame(IVP_DATA, columns=["IVP Range","Zone","Action"])
def hl_ivp(val):
    if val == ivp_zone: return "background-color:#dbeafe;font-weight:700"
    return ""
st.dataframe(df_ivp.style.map(hl_ivp, subset=["Zone"]), use_container_width=True, hide_index=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — VRP
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 4 — VRP: Volatility Risk Premium",
                  "Are you selling above or below what the market is realising?")

ui.simple_technical(
    f"VRP = ATM IV ({atm_iv:.1f}%) minus HV20 ({hv20:.1f}%) = {vrp:+.1f}%. "
    f"{'Positive VRP = selling edge exists — IV above what market is realising.' if vrp >= 0 else 'NEGATIVE VRP = selling below realised vol. Edge is gone. Widen and reconsider.'}",
    "VRP > +5%: Strong seller advantage — mild tightening bonus\nVRP 0 to +5%: Normal — no modifier\nVRP < 0: Seller disadvantage — widen both sides, reduce size"
)
st.markdown("")

c1, c2, c3 = st.columns(3)
with c1: ui.metric_card("ATM IV", f"{atm_iv:.1f}%", sub="Options implied vol")
with c2: ui.metric_card("HV20", f"{hv20:.1f}%", sub="20-day realised vol")
with c3: ui.metric_card("VRP", f"{vrp:+.1f}%",
                          sub="Positive = selling edge | Negative = disadvantage",
                          color="green" if vrp > 5 else "red" if vrp < 0 else "default")

if warnings:
    st.divider()
    ui.section_header("Active Warnings")
    for w in warnings:
        ui.alert_box("Warning", w, level="warning")
