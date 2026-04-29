# pages/02_Nifty_EMA_Ribbon.py — Page 02: EMA Hold Monitor
# Canary Signal · Live Moat Status · Momentum Direction · Hold/Act Table
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P02 · EMA Hold Monitor", layout="wide")
st_autorefresh(interval=60_000, key="p02")
st.title("Page 02 — EMA Hold Monitor")
st.caption("Canary Signal · Live Moat Status · Momentum Direction · Hold / Watch / Prepare / Act")

# ── Bootstrap: works without Home page ───────────────────────────────────────
from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)
if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

atr14     = sig.get("atr14", 200)
canary    = sig.get("canary_level",    0)
can_dir   = sig.get("canary_direction","NONE")
put_moats = sig.get("cr_put_moats",    2)
call_moats= sig.get("cr_call_moats",   2)
put_label = sig.get("cr_put_moat_label", "adequate")
call_label= sig.get("cr_call_moat_label","adequate")
mom_state = sig.get("cr_mom_state",   "FLAT")
mom_score = sig.get("cr_mom_score",    0.0)
regime    = sig.get("cr_regime",      "INSIDE_BULL")

# ── Canary banners ────────────────────────────────────────────────────────────
CANARY_MSGS = {
    4: ("FULL CANARY — EMA16 crossed EMA30. Regime has shifted. Consider defensive roll immediately.", "danger"),
    3: ("CANARY DAY 3 — EMA8 crossed EMA16. Structural weakness confirmed. Tighten monitoring. Prepare roll plan.", "danger"),
    2: ("CANARY DAY 2 — EMA8 within 30 pts of EMA16. Regime weakening. Be ready.", "warning"),
    1: ("CANARY DAY 1 — EMA3 crossed EMA8. Watch for reversal — no mechanical action yet.", "warning"),
}
if canary in CANARY_MSGS:
    msg, level = CANARY_MSGS[canary]
    ui.alert_box(f"Canary Day {canary} ({can_dir})", msg, level=level)
elif canary == 0:
    ui.alert_box("Canary Clear", "No regime deterioration signals. EMA sequence intact.", level="success")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Canary Signal Detail
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 1 — Canary Signal",
                  "Catches regime deterioration 3-4 days before it shows in spot price")

ui.simple_technical(
    "The Canary watches the sequence of short EMA crossovers. Day 4 means the regime has already "
    "shifted — act before it shows in price. Day 3 or 4 firing automatically upgrades the "
    "monitoring table below by one severity level regardless of moat count.",
    "Day 1: EMA3 < EMA8\n"
    "Day 2: EMA8 within 30 pts of EMA16\n"
    "Day 3: EMA8 < EMA16\n"
    "Day 4: EMA16 > EMA30 AND EMA8 < EMA16"
)
st.markdown("")

CANARY_COLOURS = {0: "green", 1: "amber", 2: "amber", 3: "red", 4: "red"}
ema_vals = sig.get("cr_ema_vals", {})

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1: ui.metric_card("CANARY LEVEL", f"Day {canary}",
                          sub="0=clear · 4=full alert",
                          color=CANARY_COLOURS.get(canary,"default"))
with c2: ui.metric_card("DIRECTION", can_dir,
                          sub="BEAR=deteriorating · BULL=recovering")
with c3: ui.metric_card("EMA3", f"{sig.get('ema3', ema_vals.get(3,0)):,.0f}", sub="Fastest")
with c4: ui.metric_card("EMA8", f"{sig.get('ema8', ema_vals.get(8,0)):,.0f}", sub="Fast")
with c5: ui.metric_card("EMA16",f"{sig.get('ema16',ema_vals.get(16,0)):,.0f}")
with c6: ui.metric_card("EMA30", f"{sig.get('ema30',ema_vals.get(30,0)):,.0f}")

if canary >= 3:
    st.warning("⚠️ Canary Day 3 or 4 active — each row in the Hold Table below is upgraded one severity level.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Live Moat Status
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Live Moat Status",
                  "Updated every EOD — how many EMA walls remain between spot and your short strikes")

ui.simple_technical(
    "During your hold, moats get consumed as spot moves. Each moat consumed means one less wall "
    "between spot and your strike. The combination of remaining moats and momentum direction "
    "tells you whether to hold, watch, prepare, or act.",
    "Moat = EMA between spot and short strike within 3× ATR14\n"
    "Consumed = spot has crossed above/below it\n"
    "Count updates every EOD as new candles compute"
)
st.markdown("")

MOAT_COLOUR = {"fortress":"green","strong":"green","adequate":"amber","thin":"red","exposed":"red"}

col1, col2, col3 = st.columns(3)
with col1:
    ui.metric_card("PUT MOATS REMAINING", f"{put_moats:.1f}",
                   sub=put_label.capitalize(),
                   color=MOAT_COLOUR.get(put_label,"default"))
    detail_p = sig.get("cr_put_moat_detail", [])
    if detail_p:
        st.caption("Active: " + " | ".join(f"{lbl}: {val:,.0f}" for lbl, val in detail_p))

with col2:
    ui.metric_card("CALL MOATS REMAINING", f"{call_moats:.1f}",
                   sub=call_label.capitalize(),
                   color=MOAT_COLOUR.get(call_label,"default"))
    detail_c = sig.get("cr_call_moat_detail", [])
    if detail_c:
        st.caption("Active: " + " | ".join(f"{lbl}: {val:,.0f}" for lbl, val in detail_c))

with col3:
    MOM_COLOUR = {
        "STRONG_UP":"red","MODERATE_UP":"amber","FLAT":"green",
        "MODERATE_DOWN":"amber","STRONG_DOWN":"red","TRANSITIONING":"amber"
    }
    threatened = ("PE" if "DOWN" in mom_state else
                  "CE" if "UP" in mom_state else
                  "Both" if mom_state == "TRANSITIONING" else "Neither")
    ui.metric_card("MOMENTUM", mom_state,
                   sub=f"Threatening: {threatened}  ·  Score: {mom_score:+.1f}%",
                   color=MOM_COLOUR.get(mom_state,"default"))

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Hold / Act Decision Table
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — Hold / Watch / Prepare / Act",
                  "Based on live moat count and momentum · Canary Day 3+ upgrades each row one level")

def _action(moats: float, mom: str, side: str, canary_active: bool) -> tuple:
    """Returns (action_text, alert_level)."""
    # Determine if momentum is toward this specific side
    toward = (("DOWN" in mom and side == "PE") or
              ("UP" in mom and side == "CE") or
              mom == "TRANSITIONING")
    strong = "STRONG" in mom
    moderate = "MODERATE" in mom

    if moats >= 3:
        action, level = "✅ Comfortable — hold. No action.", "success"
    elif moats >= 2:
        if strong and toward:    action, level = "🔴 Active alert — review roll plan NOW", "danger"
        elif moderate and toward:action, level = "⚠️ Elevated watch — prepare roll plan", "warning"
        else:                    action, level = "ℹ️ Monitor daily — no action yet", "info"
    elif moats >= 1:
        if strong and toward:    action, level = "🔴 Execute defensive roll", "danger"
        elif toward:             action, level = "🔴 Prepare defensive roll IMMEDIATELY", "danger"
        else:                    action, level = "⚠️ Caution — watch closely", "warning"
    else:
        action, level = "🔴 No moats — exit or roll IMMEDIATELY", "danger"

    # Canary upgrade: bump severity one level
    if canary_active:
        if level == "info":    level = "warning"
        elif level == "warning":level = "danger"

    return action, level

canary_active = canary >= 3

col1, col2 = st.columns(2)
with col1:
    st.markdown("**Put Side (PE leg)**")
    action_p, level_p = _action(put_moats, mom_state, "PE", canary_active)
    ui.alert_box(
        f"PE: {put_moats:.1f} moats · {put_label}",
        f"{action_p}\n{'⚠️ Canary Day '+str(canary)+' active — severity upgraded one level.' if canary_active else ''}",
        level=level_p
    )

with col2:
    st.markdown("**Call Side (CE leg)**")
    action_c, level_c = _action(call_moats, mom_state, "CE", canary_active)
    ui.alert_box(
        f"CE: {call_moats:.1f} moats · {call_label}",
        f"{action_c}\n{'⚠️ Canary Day '+str(canary)+' active — severity upgraded one level.' if canary_active else ''}",
        level=level_c
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Reference Table
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("Hold Table Reference — full grid", expanded=False):
    import pandas as pd
    rows = [
        ["3+ moats", "Any",             "✅ Comfortable — no action"],
        ["2 moats",  "Flat or away",    "ℹ️ Monitor daily — no action yet"],
        ["2 moats",  "Moderate toward", "⚠️ Elevated watch — prepare roll plan"],
        ["2 moats",  "Strong toward",   "🔴 Active alert — review roll NOW"],
        ["1 moat",   "Flat or away",    "⚠️ Caution — watch closely"],
        ["1 moat",   "Moderate toward", "🔴 Prepare defensive roll IMMEDIATELY"],
        ["1 moat",   "Strong toward",   "🔴 Execute defensive roll"],
        ["0 moats",  "Any",             "🔴 Last moat gone — exit or roll IMMEDIATELY"],
    ]
    df_ref = pd.DataFrame(rows, columns=["Moats Remaining","Momentum","Action"])
    st.dataframe(df_ref, use_container_width=True, hide_index=True)
    st.caption("If Canary is Day 3 or 4: upgrade each row above by one severity level. "
               "2 moats moderate becomes active alert. 1 moat flat becomes prepare roll.")
