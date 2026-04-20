# pages/00_Dow_Theory.py — Dow Theory+ Structural Analysis
# Market structure · Pivot sequence · Breach levels · IC implication
import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import numpy as np
import ui.components as ui

st.set_page_config(page_title="P00 · Dow Theory", layout="wide")
st_autorefresh(interval=900_000, key="p00")
st.title("Page 00 — Dow Theory+ Structural Analysis")
st.caption(
    "Market structure · Pivot sequence (HH/HL/LH/LL) · "
    "Breach trigger levels · IC shape implication"
)

sig = st.session_state.get("signals", {})
if not sig:
    st.info("⬅️ Open **Home** page first."); st.stop()

# Pull Dow signals (all prefixed dow_ in sig dict)
structure    = sig.get("dow_dow_structure",   sig.get("dow_structure",   "MIXED"))
last_ph      = sig.get("dow_last_pivot_high", sig.get("last_pivot_high", 0))
last_pl      = sig.get("dow_last_pivot_low",  sig.get("last_pivot_low",  0))
call_breach  = sig.get("dow_call_breach_level",sig.get("call_breach_level", 0))
put_breach   = sig.get("dow_put_breach_level", sig.get("put_breach_level",  0))
pivot_hi_ref = sig.get("dow_pivot_high_ref",  sig.get("pivot_high_ref",   last_ph))
pivot_lo_ref = sig.get("dow_pivot_low_ref",   sig.get("pivot_low_ref",    last_pl))
uptrend      = sig.get("dow_uptrend",         sig.get("uptrend",          False))
downtrend    = sig.get("dow_downtrend",        sig.get("downtrend",        False))
spot         = sig.get("final_put_short", 0) + sig.get("final_put_dist", 0)

# ── Structure banner ──────────────────────────────────────────────────────────
STRUCTURE_CONFIG = {
    "UPTREND": (
        "green",
        "UPTREND — Higher Highs and Higher Lows",
        "Market printing HH+HL sequence. Put floor structurally supported. "
        "IC can be asymmetric 1:2 (CE further). PE side benefits from structural support. "
        "CE side needs room — market has upward bias.",
        "1:2 — CE further",
        "Full size"
    ),
    "DOWNTREND": (
        "red",
        "DOWNTREND — Lower Highs and Lower Lows",
        "Market printing LH+LL sequence. Call ceiling structurally suppressed. "
        "IC can be asymmetric 2:1 (PE further). CE side benefits from structural resistance. "
        "PE side needs more room — market has downward bias.",
        "2:1 — PE further",
        "75% size"
    ),
    "MIXED_BULL_DIVERGE": (
        "amber",
        "MIXED — Higher Highs but Lower Lows",
        "Expanding range — higher highs but lows also dropping. Market volatile in both directions. "
        "Both legs under pressure. Symmetric IC recommended. Widen both sides beyond standard. "
        "This is the most volatile structure — consider reducing size.",
        "1:1 — Symmetric, wide",
        "75% size"
    ),
    "MIXED_BEAR_DIVERGE": (
        "amber",
        "MIXED — Lower Highs but Higher Lows",
        "Contracting range — coiling. Lower highs and higher lows forming a wedge. "
        "Big move building — direction unknown. Symmetric IC with caution. "
        "Monitor for breakout direction before entry. Wedge resolution often violent.",
        "1:1 — Symmetric, watch for breakout",
        "75% size"
    ),
    "MIXED": (
        "default",
        "MIXED — No clear structure",
        "Insufficient pivot data or conflicting pivot sequence. "
        "Treat as symmetric — no directional structural bias. Standard 1:1 IC.",
        "1:1 — Symmetric",
        "Full size"
    ),
}

cfg = STRUCTURE_CONFIG.get(structure, STRUCTURE_CONFIG["MIXED"])
s_col, s_title, s_desc, s_ratio, s_size = cfg

ALERT_LEVEL = {
    "green": "success", "red": "danger", "amber": "warning", "default": "info"
}
ui.alert_box(s_title, f"{s_desc}\n\nIC shape: {s_ratio} · Size guidance: {s_size}",
             level=ALERT_LEVEL.get(s_col, "info"))

st.divider()

# ── Headline metrics ──────────────────────────────────────────────────────────
c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1: ui.metric_card("STRUCTURE", structure, color=s_col)
with c2: ui.metric_card("IC SHAPE",  s_ratio,   sub="Dow Theory guidance")
with c3: ui.metric_card("LAST PIVOT HIGH", f"{last_ph:,.0f}",
                          sub="Recent swing high")
with c4: ui.metric_card("LAST PIVOT LOW",  f"{last_pl:,.0f}",
                          sub="Recent swing low")
with c5: ui.metric_card("CALL BREACH LEVEL", f"{call_breach:,.0f}",
                          sub=f"+0.5% above pivot high",
                          color="red" if spot > 0 and call_breach > 0 and spot > call_breach * 0.98 else "default")
with c6: ui.metric_card("PUT BREACH LEVEL", f"{put_breach:,.0f}",
                          sub=f"−0.5% below pivot low",
                          color="red" if spot > 0 and put_breach > 0 and spot < put_breach * 1.02 else "default")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — What Dow Theory Tells You
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 1 — What Dow Theory Tells You",
                  "Structural context for IC shape and bias")

ui.simple_technical(
    "Dow Theory reads the market's structural rhythm — the sequence of swing highs and lows over days and weeks. "
    "An uptrend is confirmed not by price being high, but by each new high being higher than the last AND each "
    "pullback holding above the previous pullback. This structural support is what makes the PE floor reliable. "
    "A downtrend is the mirror — each rally fails lower, each drop takes out the previous low. "
    "This structural ceiling is what makes the CE leg safer.\n\n"
    "Dow Theory does NOT tell you direction from today. It tells you the current structural bias "
    "that has been validated over the past several weeks of price action.",

    "Pivot detection: swing high = high[i] > all highs within N bars either side (N=5)\n"
    "HH = higher high (last pivot high > prior pivot high)\n"
    "HL = higher low (last pivot low > prior pivot low)\n"
    "LH = lower high | LL = lower low\n"
    "UPTREND = HH + HL simultaneously\n"
    "DOWNTREND = LH + LL simultaneously\n"
    "Breach level = 0.5% beyond pivot → structural break trigger"
)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Pivot Sequence and Breach Levels
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Pivot Sequence and Breach Levels",
                  "Structural pivot highs and lows · Breach = structural change signal")

col1, col2 = st.columns(2)

with col1:
    st.markdown("**Call (CE) Side — Resistance Structure**")
    ui.simple_technical(
        f"The last confirmed pivot high is at **{last_ph:,.0f}**. "
        f"The call breach level is **{call_breach:,.0f}** — 0.5% above this pivot. "
        f"{'Price is currently near or above the breach level — structural resistance is being tested.' if spot > 0 and call_breach > 0 and spot > call_breach * 0.98 else 'Price is currently below the breach level — CE structural protection intact.'}\n\n"
        f"In an uptrend (HH+HL), each new high is expected to exceed the previous. "
        f"A failure to break above the last pivot high is the first Dow Theory warning "
        f"that the uptrend may be stalling.",
        f"Last pivot high: {last_ph:,.0f}\n"
        f"Breach level: {call_breach:,.0f} (+0.5%)\n"
        f"Breach signal: close above {call_breach:,.0f} = structural breakout\n"
        f"CE implication: strike must be above {call_breach:,.0f} in uptrend"
    )

with col2:
    st.markdown("**Put (PE) Side — Support Structure**")
    ui.simple_technical(
        f"The last confirmed pivot low is at **{last_pl:,.0f}**. "
        f"The put breach level is **{put_breach:,.0f}** — 0.5% below this pivot. "
        f"{'Price is currently near or below the breach level — structural support is being tested.' if spot > 0 and put_breach > 0 and spot < put_breach * 1.02 else 'Price is currently above the breach level — PE structural protection intact.'}\n\n"
        f"In an uptrend (HH+HL), each pullback must hold above the previous pivot low. "
        f"A close below the put breach level means the HL pattern has failed — "
        f"the uptrend structure is broken and the IC PE leg loses its structural support.",
        f"Last pivot low: {last_pl:,.0f}\n"
        f"Breach level: {put_breach:,.0f} (−0.5%)\n"
        f"Breach signal: close below {put_breach:,.0f} = structural breakdown\n"
        f"PE implication: pivot low must be between spot and PE short"
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Structure Reference Table
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — Structure Reference Table",
                  "All four Dow Theory structures and their IC implications")

import pandas as pd
rows = [
    ["UPTREND",            "HH + HL",      "1:2 — CE further", "Full",  "Strong PE floor. CE needs room. Ideal IC entry."],
    ["DOWNTREND",          "LH + LL",      "2:1 — PE further", "75%",   "Strong CE ceiling. PE needs room. Valid but cautious."],
    ["MIXED_BULL_DIVERGE", "HH + LL",      "1:1 — Wide both",  "75%",   "Expanding range. Both legs volatile. Reduce size."],
    ["MIXED_BEAR_DIVERGE", "LH + HL",      "1:1 — Watch",      "75%",   "Contracting range — coiling. Breakout risk. Monitor."],
    ["MIXED",              "Unclear",       "1:1 — Standard",   "Full",  "No structural bias. Symmetric IC. Standard approach."],
]
df_ref = pd.DataFrame(rows, columns=["Structure","Pivot Pattern","IC Shape","Size","Note"])

def hl_structure(val):
    if val == structure:
        return "background-color:#dbeafe;font-weight:700"
    return ""

st.dataframe(
    df_ref.style.map(hl_structure, subset=["Structure"]),
    use_container_width=True, hide_index=True
)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Live Price Chart with Pivot Levels
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 4 — Price Context with Structural Levels",
                  "Pivot highs, pivot lows, breach levels, and current spot")

# We only have sig dict — draw a simple level chart
if last_ph > 0 and last_pl > 0:
    fig = go.Figure()

    levels = [
        (call_breach, "Call Breach Level (+0.5%)", "#dc2626", "dash"),
        (last_ph,     "Last Pivot High",            "#f97316", "solid"),
        (spot,        "Current Spot",               "#7c3aed", "dot") if spot > 0 else None,
        (last_pl,     "Last Pivot Low",             "#16a34a", "solid"),
        (put_breach,  "Put Breach Level (−0.5%)",   "#15803d", "dash"),
    ]

    # Approximate a mini range for y axis
    y_min = min(put_breach * 0.998, last_pl * 0.998) if put_breach > 0 else last_pl * 0.99
    y_max = max(call_breach * 1.002, last_ph * 1.002) if call_breach > 0 else last_ph * 1.01

    for item in levels:
        if item is None:
            continue
        level, name, colour, dash = item
        if level <= 0:
            continue
        fig.add_hline(
            y=level, line_color=colour, line_dash=dash, line_width=2,
            annotation_text=f"{name}: {level:,.0f}",
            annotation_position="right",
            annotation_font_color=colour,
        )

    # Shade zone between pivots = value zone
    if last_pl > 0 and last_ph > 0:
        fig.add_hrect(
            y0=last_pl, y1=last_ph,
            fillcolor="#dcfce7", opacity=0.15,
            annotation_text="Structural Range",
            annotation_position="top left",
        )

    fig.update_layout(
        height=320,
        margin=dict(l=0, r=180, t=20, b=20),
        yaxis=dict(range=[y_min, y_max], title="Nifty Level",
                   tickformat=",.0f"),
        xaxis=dict(visible=False),
        plot_bgcolor="#f8f9fb",
        paper_bgcolor="#f8f9fb",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Pivot levels not yet computed — open Home page first to load signals.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — IC Implication Summary
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 5 — IC Implication Summary",
                  "How Dow Theory structure feeds into your IC decisions")

# Determine which leg is structurally supported
if uptrend:
    pe_note = "PE leg benefits from HH+HL structural support. Put floor is validated by the uptrend sequence."
    ce_note = "CE leg needs extra room — market has upward structural bias. Strike must sit above last pivot high."
    entry   = "Prime entry: on HL pullback confirmation — after a dip holds above last pivot low."
elif downtrend:
    pe_note = "PE leg needs extra room — market has downward structural bias. Strike must sit below last pivot low."
    ce_note = "CE leg benefits from LH+LL structural resistance. Call ceiling validated by downtrend sequence."
    entry   = "Prime entry: on LH rally confirmation — after a bounce fails below last pivot high."
else:
    pe_note = "Mixed structure — no structural directional support for PE. Use symmetric IC."
    ce_note = "Mixed structure — no structural directional support for CE. Use symmetric IC."
    entry   = "Wait for structure to clarify. Monitor pivot sequence over next 1-2 weeks."

col1, col2 = st.columns(2)
with col1:
    ui.alert_box("PE (Put) Leg — Structural View", pe_note,
                 level="success" if uptrend else "danger" if downtrend else "info")
with col2:
    ui.alert_box("CE (Call) Leg — Structural View", ce_note,
                 level="success" if downtrend else "danger" if uptrend else "info")

st.markdown("")
ui.alert_box("Entry Timing Guidance", entry, level="info")

# Breach monitoring
st.markdown("**Breach Level Monitoring — During Your Hold**")
ui.simple_technical(
    f"If spot closes below {put_breach:,.0f} (put breach level) during your hold — the HH+HL uptrend "
    f"structure is broken. The PE leg loses its structural support. This is a signal to review "
    f"your put short immediately — not necessarily to exit, but to confirm moat count and buffer.\n\n"
    f"If spot closes above {call_breach:,.0f} (call breach level) — the LH+LL downtrend structure is "
    f"broken. The CE ceiling has been taken out. Review your call short.",

    f"Put breach trigger: close < {put_breach:,.0f}\n"
    f"Call breach trigger: close > {call_breach:,.0f}\n"
    f"Action on breach: check moat count (Page 02) + nesting state (Page 12)\n"
    f"Breach alone ≠ exit — combine with moat count and nesting"
)

