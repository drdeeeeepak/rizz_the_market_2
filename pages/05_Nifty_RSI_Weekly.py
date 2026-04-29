# pages/05_Nifty_RSI_Weekly.py — Pages 05+06 Merged: Nifty RSI Monitor
# Weekly context + Daily execution + MTF Alignment + Kill Switches + Phase
import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import ui.components as ui

st.set_page_config(page_title="P05+06 · Nifty RSI Monitor", layout="wide")
st_autorefresh(interval=900_000, key="p05")  # 15 min
st.title("Pages 05+06 — Nifty RSI Monitor")
st.caption("Weekly context · Daily execution · MTF Alignment · Kill Switches · Phase — updates every 15 min")

sig = st.session_state.get("signals", {})
if not sig:
    st.info("⬅️ Open **Home** page first."); st.stop()

w_rsi   = sig.get("rsi_weekly", sig.get("weekly_rsi", 50))
d_rsi   = sig.get("rsi_daily",  sig.get("daily_rsi",  50))
w_reg   = sig.get("weekly_regime", sig.get("w_regime", "W_NEUTRAL"))
d_zone  = sig.get("daily_zone",   sig.get("d_zone",   "D_BALANCE"))
align   = sig.get("mtf_alignment", sig.get("alignment", "MIXED"))
phase   = sig.get("rsi_phase", sig.get("momentum_phase", "CONTINUING"))
timing  = sig.get("entry_timing", "Mid")
kills   = sig.get("kill_switches", {})

# ── Hard kill banners ─────────────────────────────────────────────────────────
if kills.get("RSI_DUAL_EXHAUSTION") or kills.get("K3"):
    st.error("🔴 RSI_DUAL_EXHAUSTION — Weekly >70 AND Daily >68 simultaneously. Flatten 1:1. Add +300 pts both sides. Do NOT flip ratio.")
if kills.get("RSI_REGIME_FLIP") or kills.get("K1"):
    st.error("🔴 RSI_REGIME_FLIP — Weekly RSI crossed a zone boundary. Fire Canary Day 1. Check buffer vs 2×ATR.")
if kills.get("RSI_ZONE_SKIP") or kills.get("K2"):
    st.error("🔴 RSI_ZONE_SKIP — Daily RSI skipped a zone this session. Check buffer vs 2×ATR before holding.")
if kills.get("RSI_RANGE_BREAKDOWN") or kills.get("K4"):
    st.warning("⚠️ RSI_RANGE_BREAKDOWN — Weekly held 45+ for 10 weeks then broke below 40. Reduce size 50%. P1 decay -30%.")
if kills.get("RSI_DAILY_EXHAUSTION_REVERSAL") or kills.get("K5"):
    st.warning("⚠️ RSI_DAILY_EXHAUSTION_REVERSAL — Daily >68 and slope negative. Reduce PE 50%. Leave CE.")

# Counter-trap block
if align in ("COUNTER_TRAP_BEAR", "COUNTER_TRAP_BULL"):
    st.error(f"🔴 {align} — DO NOT ENTER. Blocks leg-shift. Weekly and daily contradicting each other.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Weekly RSI
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 1 — Weekly RSI: Strategic Context",
                  "Slow high-conviction signal · Sets IC shape, ratio, size for the week")

WREG_COLOURS = {
    "W_CAPIT":    "red",  "W_BEAR":       "red",   "W_BEAR_TRANS": "amber",
    "W_NEUTRAL":  "default", "W_BULL_TRANS": "green", "W_BULL":       "green",
    "W_BULL_EXH": "amber",
}
WREG_STRATEGY = {
    "W_CAPIT":    "Put leg BLOCKED. Call spread only at 50% if D RSI <45.",
    "W_BEAR":     "Bear call only. PE forced to <35% bracket — min +600 pts PE.",
    "W_BEAR_TRANS":"1:1.5 IC half size. Both sides wide. No directional conviction.",
    "W_NEUTRAL":  "Standard 1:1 IC. Net Skew governs asymmetry.",
    "W_BULL_TRANS":"1:2 IC full size. +10 pts bonus to Put Safety.",
    "W_BULL":     "Full 1:2 IC. +10 pts bonus to Put Safety. Strong floor.",
    "W_BULL_EXH": "Flatten to 1:1. +200 pts both sides. Do NOT flip ratio. Size 75%.",
}
WREG_SIZE = {
    "W_CAPIT": "0%/50%", "W_BEAR": "100%", "W_BEAR_TRANS": "50%",
    "W_NEUTRAL": "100%", "W_BULL_TRANS": "100%", "W_BULL": "100%", "W_BULL_EXH": "75%",
}

c1, c2, c3, c4, c5 = st.columns(5)
with c1: ui.metric_card("WEEKLY RSI", f"{w_rsi:.1f}", color=WREG_COLOURS.get(w_reg,"default"))
with c2: ui.metric_card("W REGIME",   w_reg, sub=WREG_SIZE.get(w_reg,""), color=WREG_COLOURS.get(w_reg,"default"))
with c3: ui.metric_card("W SLOPE",    f"{sig.get('w_slope_1w',0):+.2f}", sub="pts/week")
with c4: ui.metric_card("PHASE",      phase, sub="Regime cycle position",
                          color="green" if phase=="CONTINUING" else "amber" if phase=="TRANSITIONING" else "red")
with c5: ui.metric_card("ENTRY TIMING", timing, sub="Early/Mid/Late in cycle")

st.markdown("")
ui.alert_box(f"Strategy: {w_reg}", WREG_STRATEGY.get(w_reg,""),
             level="danger" if w_reg in ("W_CAPIT","W_BULL_EXH") else
                   "warning" if w_reg in ("W_BEAR","W_BEAR_TRANS") else
                   "success" if w_reg in ("W_BULL","W_BULL_TRANS") else "info")

# Regime table
with st.expander("Weekly Regime Reference Table", expanded=False):
    rows = [
        ["W_CAPIT",    "<30",    "Put BLOCKED. Call spread 50% if D RSI <45.", "0%/50%"],
        ["W_BEAR",     "30-40",  "Bear call only. +600 pts PE min.",            "100%"],
        ["W_BEAR_TRANS","40-45", "1:1.5 half size. Both wide.",                 "50%"],
        ["W_NEUTRAL",  "45-60",  "Standard 1:1. Net Skew governs.",             "100%"],
        ["W_BULL_TRANS","60-65", "1:2 full. +10 pts Put Safety bonus.",         "100%"],
        ["W_BULL",     "65-70",  "Full 1:2. +10 pts Put Safety.",               "100%"],
        ["W_BULL_EXH", "≥70",   "Flatten 1:1. +200 pts both. No flip.",        "75%"],
    ]
    df_ref = pd.DataFrame(rows, columns=["Regime","RSI","IC Strategy","Size"])
    def hl_regime(val):
        if val == w_reg: return "background-color:#dbeafe;font-weight:700"
        return ""
    st.dataframe(df_ref.style.map(hl_regime, subset=["Regime"]),
                 use_container_width=True, hide_index=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Daily RSI + MTF Alignment
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Daily RSI: Execution Layer",
                  "Real-time execution signal · Combines with weekly via MTF matrix")

DZONE_COLOURS = {
    "D_CAPIT": "red", "D_BEAR_PRESSURE": "red", "D_BALANCE": "green",
    "D_BULL_PRESSURE": "amber", "D_BULL_PRESSURE_PLUS": "amber", "D_EXHAUST": "red",
}
DZONE_DESC = {
    "D_CAPIT":             "Capitulation — no new entry regardless of weekly",
    "D_BEAR_PRESSURE":     "Bearish pressure — widen PE",
    "D_BALANCE":           "Balanced — most comfortable entry zone",
    "D_BULL_PRESSURE":     "Bullish push — CE side needs attention",
    "D_BULL_PRESSURE_PLUS":"Strong bull — watch CE exhaustion",
    "D_EXHAUST":           "Daily exhaustion — RSI_DAILY_EXHAUSTION_REVERSAL watch",
}

ALIGN_COLOURS = {
    "ALIGNED_BULL":         "green", "ALIGNED_BULL_NEUTRAL": "green",
    "ALIGNED_BEAR":         "red",   "COUNTER_TRAP_BEAR":    "red",
    "COUNTER_TRAP_BULL":    "red",   "MIXED":                "amber",
}
ALIGN_ACTION = {
    "ALIGNED_BULL":         "Full size 1:2 IC — standard entry",
    "ALIGNED_BULL_NEUTRAL": "Full size 1:1 IC — symmetric",
    "ALIGNED_BEAR":         "Bear call only or 2:1 CE heavy — widen PE sharply",
    "COUNTER_TRAP_BEAR":    "WAIT — no entry. Daily pullback in bull trend. Blocks leg-shift.",
    "COUNTER_TRAP_BULL":    "Small CE only at maximum distance. Bounce in bear — do not trust.",
    "MIXED":                "Standard IC with extra caution. Reduce size.",
}

c1, c2, c3, c4 = st.columns(4)
with c1: ui.metric_card("DAILY RSI", f"{d_rsi:.1f}", color=DZONE_COLOURS.get(d_zone,"default"))
with c2: ui.metric_card("D ZONE",    d_zone, sub=DZONE_DESC.get(d_zone,""), color=DZONE_COLOURS.get(d_zone,"default"))
with c3: ui.metric_card("D SLOPE",   f"{sig.get('d_slope_1d',0):+.2f}", sub="1-day RSI change")
with c4: ui.metric_card("MTF ALIGNMENT", align, sub=ALIGN_ACTION.get(align,""),
                          color=ALIGN_COLOURS.get(align,"default"))
st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Kill Switches
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — RSI Kill Switches",
                  "Checked every 15 min · Hard kills = no entry · Soft = warning with action")

ui.simple_technical(
    "Hard kills block entry entirely. Soft kills give you specific actions to take. All five are checked every 15 minutes against live RSI data.",
    "Hard: RSI_REGIME_FLIP, RSI_ZONE_SKIP, RSI_DUAL_EXHAUSTION\nSoft: RSI_RANGE_BREAKDOWN, RSI_DAILY_EXHAUSTION_REVERSAL"
)
st.markdown("")

KILL_DETAILS = {
    "RSI_REGIME_FLIP":               ("Weekly RSI flipped zones this week", "Fire Canary Day 1. Exit if buffer ≤ 2×ATR.", True),
    "RSI_ZONE_SKIP":                 ("Daily RSI skipped a zone in one session", "Hold if buffer > 2×ATR. Exit if ≤ 2×ATR.", True),
    "RSI_DUAL_EXHAUSTION":           ("Weekly >70 AND Daily >68 simultaneously", "Flatten 1:1. +300 pts both. Do NOT flip.", True),
    "RSI_RANGE_BREAKDOWN":           ("Weekly held 45+ for 10 weeks then broke <40", "Reduce size 50%. Fires P1 decay -30%.", False),
    "RSI_DAILY_EXHAUSTION_REVERSAL": ("Daily >68 AND slope turned negative", "Reduce PE 50%. Leave CE unchanged.", False),
}
KILL_LEGACY = {
    "RSI_REGIME_FLIP": "K1", "RSI_ZONE_SKIP": "K2", "RSI_DUAL_EXHAUSTION": "K3",
    "RSI_RANGE_BREAKDOWN": "K4", "RSI_DAILY_EXHAUSTION_REVERSAL": "K5",
}

cols = st.columns(5)
for i, (name, (trigger, action, is_hard)) in enumerate(KILL_DETAILS.items()):
    active = kills.get(name) or kills.get(KILL_LEGACY.get(name, ""), False)
    with cols[i]:
        label = "🔴 HARD" if is_hard else "⚠️ SOFT"
        ui.metric_card(
            name.replace("RSI_",""),
            f"{'🔴 ACTIVE' if active else '✅ Clear'}",
            sub=f"{label} — {trigger[:40]}",
            color="red" if active else "green"
        )
