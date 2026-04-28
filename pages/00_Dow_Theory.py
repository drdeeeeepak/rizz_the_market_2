# pages/00_Dow_Theory.py — Dow Theory Phase Engine
# Redesigned 27 Apr 2026 — single window, N=3, phase narrative
# Section 0: Narrative (first thing seen)
# Section 1: Phase metrics + score trajectory
# Section 2: Structural pivots
# Section 3: Breach levels + proximity
# Section 4: Level chart
# Section 5: Reference table

import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import ui.components as ui

st.set_page_config(page_title="P00 · Dow Theory", layout="wide")
st_autorefresh(interval=900_000, key="p00")
st.title("Page 00 — Nifty Structure & Phase")
st.caption("20-day 1H · N=3 · Single rolling window · Phase narrative · Nifty Health Monitor")

sig = st.session_state.get("signals", {})
if not sig:
    st.info("⬅️ Open **Home** page first."); st.stop()

# ── Pull signals ──────────────────────────────────────────────────────────────
structure    = sig.get("dow_structure",          "MIXED")
phase        = sig.get("dow_phase",              "MX")
narrative    = sig.get("dow_narrative",          "—")
score        = sig.get("dow_phase_score",        "WAIT")
score_label  = sig.get("dow_dow_phase_score_label", "Nifty Health Monitor")
retrace_pct  = sig.get("dow_retrace_pct",        0.0)
sessions     = sig.get("dow_sessions_in_phase",  0.0)
ph_last      = sig.get("dow_ph_last",            0.0)
ph_prev      = sig.get("dow_ph_prev",            0.0)
pl_last      = sig.get("dow_pl_last",            0.0)
pl_prev      = sig.get("dow_pl_prev",            0.0)
ce_health    = sig.get("dow_ce_health",          "STRONG")
pe_health    = sig.get("dow_pe_health",          "STRONG")
ce_pts       = sig.get("dow_ce_health_pts",      0.0)
pe_pts       = sig.get("dow_pe_health_pts",      0.0)
call_breach  = sig.get("dow_call_breach",        0.0)
put_breach   = sig.get("dow_put_breach",         0.0)
prox_pts     = sig.get("dow_proximity_pts",      66.0)
call_prox    = sig.get("dow_call_prox_warn",     False)
put_prox     = sig.get("dow_put_prox_warn",      False)
atr14_1h     = sig.get("dow_atr14_1h",           200.0)
ic_shape     = sig.get("dow_ic_shape",           "1:1 — Symmetric")
ic_size      = sig.get("dow_ic_size",            "Full size")
score_hist   = sig.get("dow_score_history",      [])
candles_used = sig.get("dow_candles_used",       0)
insufficient = sig.get("dow_insufficient_data",  False)

spot = sig.get("final_put_short", 0) + sig.get("final_put_dist", 0)

_STRUCT_COL = {
    "UPTREND": "#16a34a", "DOWNTREND": "#dc2626",
    "MIXED_EXPANDING": "#d97706", "MIXED_CONTRACTING": "#d97706",
    "CONSOLIDATING": "#64748b",
}
_SCORE_COL = {
    "PRIME": "success", "GOOD": "info",
    "WAIT": "warning", "AVOID": "danger", "NO_TRADE": "danger",
}
_HEALTH_COL = {
    "STRONG": "green", "MODERATE": "default",
    "WATCH": "amber", "ALERT": "red", "BREACH": "red",
}
struct_col = _STRUCT_COL.get(structure, "#64748b")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 0 — NARRATIVE (first thing you see)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(
    f"<div style='background:#f0f9ff;border-left:5px solid {struct_col};"
    f"padding:16px 20px;border-radius:8px;margin-bottom:16px;"
    f"font-size:16px;color:#0f1724;font-weight:500;line-height:1.6;'>"
    f"📍 {narrative}"
    f"</div>",
    unsafe_allow_html=True
)

if insufficient:
    ui.alert_box(
        "Insufficient Pivot Data",
        "Fewer than 2 confirmed pivot highs or 2 confirmed pivot lows in the 20-day window. "
        "Structure defaults to MIXED. This can happen during low-volatility compression "
        "or if 1H data fetch is incomplete.",
        level="warning"
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — PHASE METRICS + SCORE TRAJECTORY
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 1 — Phase Metrics & Score Trajectory",
                  "Current phase, depth, health, and 5-day history")

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1: ui.metric_card("STRUCTURE",  structure, color=("green" if structure=="UPTREND" else "red" if structure=="DOWNTREND" else "amber"))
with c2: ui.metric_card("PHASE",      phase,     sub="Current phase code")
with c3: ui.metric_card(score_label,  score,     color=("green" if score=="PRIME" else "blue" if score=="GOOD" else "amber" if score=="WAIT" else "red"))
with c4: ui.metric_card("RETRACE",    f"{retrace_pct:.0f}%", sub=f"of last swing")
with c5: ui.metric_card("SESSIONS",   f"{sessions:.0f}" if sessions==int(sessions) else f"{sessions:.1f}", sub="in current phase")
with c6: ui.metric_card("IC SHAPE",   ic_shape,  sub=ic_size)

# ── CE and PE health ──────────────────────────────────────────────────────────
st.markdown("")
c1, c2 = st.columns(2)
with c1:
    ui.metric_card(
        "CE HEALTH (Vulnerable in DOWNTREND)",
        f"{ce_health} — {ce_pts:,.0f} pts",
        sub=f"Distance from spot to structural LH/HH",
        color=_HEALTH_COL.get(ce_health, "default")
    )
with c2:
    ui.metric_card(
        "PE HEALTH (Vulnerable in UPTREND)",
        f"{pe_health} — {pe_pts:,.0f} pts",
        sub=f"Distance from spot to structural LL/HL",
        color=_HEALTH_COL.get(pe_health, "default")
    )

# ── Score trajectory table ────────────────────────────────────────────────────
if score_hist:
    st.markdown("**Score Trajectory — Last 5 Sessions**")
    rows = []
    for r in score_hist:
        rows.append({
            "Date":       r.get("date",""),
            "Day":        r.get("weekday","")[:3],
            "Structure":  r.get("structure",""),
            "Phase":      r.get("phase",""),
            "Retrace %":  f"{r.get('retrace_pct',0):.0f}%",
            "CE Health":  r.get("ce_health",""),
            "PE Health":  r.get("pe_health",""),
            "Score":      r.get("phase_score",""),
        })
    df_hist = pd.DataFrame(rows)

    def _colour_score(val):
        c = {"PRIME":"background-color:#dcfce7;font-weight:700",
             "GOOD":"background-color:#dbeafe;font-weight:700",
             "WAIT":"background-color:#fef9c3",
             "AVOID":"background-color:#fee2e2;font-weight:700",
             "NO_TRADE":"background-color:#fecaca;font-weight:700"}
        return c.get(val,"")

    def _colour_health(val):
        c = {"STRONG":"color:#16a34a;font-weight:600",
             "MODERATE":"color:#2563eb",
             "WATCH":"color:#d97706;font-weight:600",
             "ALERT":"color:#ea580c;font-weight:700",
             "BREACH":"color:#dc2626;font-weight:700"}
        return c.get(val,"")

    st.dataframe(
        df_hist.style
            .map(_colour_score,  subset=["Score"])
            .map(_colour_health, subset=["CE Health","PE Health"]),
        use_container_width=True, hide_index=True
    )
    st.caption(
        f"PRIME = ideal entry zone · GOOD = acceptable · WAIT = not yet · "
        f"AVOID = threat active · NO_TRADE = structure changing"
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — STRUCTURAL PIVOTS
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Structural Pivots",
                  "Last two confirmed pivot highs and lows · 20-day 1H · N=3")

c1, c2, c3, c4 = st.columns(4)
hh = ph_last > ph_prev if ph_prev > 0 else None
hl = pl_last > pl_prev if pl_prev > 0 else None

with c1: ui.metric_card(
    "PIVOT HIGH 1 (Recent)", f"{ph_last:,.0f}" if ph_last>0 else "—",
    sub="Most recent confirmed swing high"
)
with c2: ui.metric_card(
    "PIVOT HIGH 2 (Prior)", f"{ph_prev:,.0f}" if ph_prev>0 else "—",
    sub=("↑ HH — Higher High" if hh else "↓ LH — Lower High") if hh is not None else "Prior high",
    color="green" if hh else "red" if hh is not None else "default"
)
with c3: ui.metric_card(
    "PIVOT LOW 1 (Recent)", f"{pl_last:,.0f}" if pl_last>0 else "—",
    sub="Most recent confirmed swing low"
)
with c4: ui.metric_card(
    "PIVOT LOW 2 (Prior)", f"{pl_prev:,.0f}" if pl_prev>0 else "—",
    sub=("↑ HL — Higher Low" if hl else "↓ LL — Lower Low") if hl is not None else "Prior low",
    color="green" if hl else "red" if hl is not None else "default"
)

st.caption(
    f"Window: 20 trading days of 1H OHLCV · {candles_used} candles · "
    f"N=3 (3 hours each side for pivot confirmation) · "
    f"ATR14(1H) = {atr14_1h:.0f} pts"
)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — BREACH LEVELS
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — Breach Levels & Proximity",
                  "PH_last + 50 pts · PL_last − 50 pts · Warning within ATR14/3")

c1, c2, c3, c4 = st.columns(4)
with c1: ui.metric_card("CALL BREACH", f"{call_breach:,.0f}" if call_breach>0 else "—",
                          sub="PH_last + 50 pts", color="red" if call_prox else "default")
with c2: ui.metric_card("PUT BREACH",  f"{put_breach:,.0f}"  if put_breach>0  else "—",
                          sub="PL_last − 50 pts",  color="red" if put_prox  else "default")
with c3: ui.metric_card("PROXIMITY ZONE", f"±{prox_pts:.0f} pts",
                          sub=f"ATR14(1H) / 3 = {atr14_1h:.0f}/3")
with c4: ui.metric_card("CALL STATUS",
                          "⚠️ IN ZONE" if call_prox else "✓ Clear",
                          color="red" if call_prox else "green")

if call_prox:
    ui.alert_box("⚠️ CALL PROXIMITY WARNING",
        f"Spot is within {prox_pts:.0f} pts of call breach level {call_breach:,.0f}. "
        f"CE leg approaching structural trigger. Check moat count (Page 02) and nesting (Page 12).",
        level="danger")
if put_prox:
    ui.alert_box("⚠️ PUT PROXIMITY WARNING",
        f"Spot is within {prox_pts:.0f} pts of put breach level {put_breach:,.0f}. "
        f"PE leg approaching structural trigger. Check moat count (Page 02) and nesting (Page 12).",
        level="danger")
if not call_prox and not put_prox:
    ui.alert_box("✓ Breach Levels Clear",
        f"Spot is more than {prox_pts:.0f} pts from both breach levels. "
        f"Structural protection intact on both sides.",
        level="success")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — LEVEL CHART
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 4 — Structural Level Map",
                  "Last 5 days of 1H candles · Pivot markers · Breach levels · Proximity zones")

nifty_1h_full = st.session_state.get("nifty_1h", pd.DataFrame())

if ph_last > 0 and pl_last > 0 and not nifty_1h_full.empty:
    df_chart = nifty_1h_full.tail(30).copy()
    if not isinstance(df_chart.index, pd.DatetimeIndex):
        df_chart.index = pd.to_datetime(df_chart.index)

    ph_last_ts = sig.get("dow_ph_last_ts", "")
    ph_prev_ts = sig.get("dow_dow_ph_prev_ts", sig.get("dow_ph_prev_ts", ""))
    pl_last_ts = sig.get("dow_pl_last_ts", "")
    pl_prev_ts = sig.get("dow_dow_pl_prev_ts", sig.get("dow_pl_prev_ts", ""))

    def _find_pivot_bar(df, ts_str, col):
        if not ts_str:
            return None, None
        try:
            ts = pd.to_datetime(ts_str)
            diffs = (df.index - ts).abs()
            idx   = diffs.argmin()
            return df.index[idx], float(df[col].iloc[idx])
        except Exception:
            return None, None

    ph_last_x, ph_last_y = _find_pivot_bar(df_chart, ph_last_ts, "high")
    ph_prev_x, ph_prev_y = _find_pivot_bar(df_chart, ph_prev_ts, "high")
    pl_last_x, pl_last_y = _find_pivot_bar(df_chart, pl_last_ts, "low")
    pl_prev_x, pl_prev_y = _find_pivot_bar(df_chart, pl_prev_ts, "low")

    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=df_chart.index,
        open=df_chart["open"], high=df_chart["high"],
        low=df_chart["low"],   close=df_chart["close"],
        name="Nifty 1H",
        increasing_line_color="#16a34a", decreasing_line_color="#dc2626",
        increasing_fillcolor="#16a34a",  decreasing_fillcolor="#dc2626",
        line_width=1,
    ))

    x0 = df_chart.index[0]
    x1 = df_chart.index[-1]

    line_levels = [
        (call_breach, "Call Breach +50", "#7f1d1d", "dash",  1.5),
        (ph_last,     "PH_last",         "#dc2626", "solid", 2.0),
        (ph_prev,     "PH_prev",         "#f87171", "dot",   1.5) if ph_prev > 0 else None,
        (spot,        "Spot",            "#7c3aed", "dot",   1.5) if spot > 0   else None,
        (pl_last,     "PL_last",         "#16a34a", "solid", 2.0),
        (pl_prev,     "PL_prev",         "#4ade80", "dot",   1.5) if pl_prev > 0 else None,
        (put_breach,  "Put Breach -50",  "#14532d", "dash",  1.5),
    ]
    for item in line_levels:
        if item is None: continue
        level, name, colour, dash, width = item
        if level <= 0: continue
        fig.add_shape(type="line", x0=x0, x1=x1, y0=level, y1=level,
                      line=dict(color=colour, dash=dash, width=width))
        fig.add_annotation(x=x1, y=level, text=f"  {name}: {level:,.0f}",
                           showarrow=False, xanchor="left",
                           font=dict(color=colour, size=10))

    if call_breach > 0 and prox_pts > 0:
        fig.add_hrect(y0=call_breach - prox_pts, y1=call_breach + prox_pts,
                      fillcolor="#fee2e2", opacity=0.20, line_width=0)
    if put_breach > 0 and prox_pts > 0:
        fig.add_hrect(y0=put_breach - prox_pts, y1=put_breach + prox_pts,
                      fillcolor="#fef9c3", opacity=0.20, line_width=0)
    if pl_last > 0 and ph_last > 0:
        fig.add_hrect(y0=pl_last, y1=ph_last,
                      fillcolor="#dcfce7", opacity=0.07, line_width=0)

    swing_range = (ph_last - pl_last) if ph_last > pl_last else 200
    marker_offset = swing_range * 0.012

    pivot_markers = [
        (ph_last_x, ph_last_y, "triangle-down", "#dc2626", "PH_last", True),
        (ph_prev_x, ph_prev_y, "triangle-down", "#f87171", "PH_prev", True),
        (pl_last_x, pl_last_y, "triangle-up",   "#16a34a", "PL_last", False),
        (pl_prev_x, pl_prev_y, "triangle-up",   "#4ade80", "PL_prev", False),
    ]
    for px, py, sym, col, name, is_high in pivot_markers:
        if px is None or py is None:
            continue
        marker_y = py + marker_offset if is_high else py - marker_offset
        fig.add_trace(go.Scatter(
            x=[px], y=[marker_y], mode="markers+text",
            marker=dict(symbol=sym, size=12, color=col),
            text=[name],
            textposition="top center" if is_high else "bottom center",
            textfont=dict(size=9, color=col),
            showlegend=False,
        ))

    all_y = [v[0] for v in line_levels if v and v[0] > 0]
    y_min  = min(all_y) * 0.996 if all_y else df_chart["low"].min()
    y_max  = max(all_y) * 1.004 if all_y else df_chart["high"].max()

    fig.update_layout(
        height=460, margin=dict(l=10, r=200, t=20, b=20),
        yaxis=dict(range=[y_min, y_max], title="Nifty", tickformat=",.0f"),
        xaxis=dict(rangeslider=dict(visible=False), tickformat="%d %b %H:%M"),
        plot_bgcolor="#f8f9fb", paper_bgcolor="#f8f9fb", showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"Last 5 trading days · {len(df_chart)} candles of 1H OHLCV · "
        f"▼ = pivot high · ▲ = pivot low · green band = structural range · "
        f"dashed = breach levels · shaded = proximity zones"
    )

elif ph_last > 0 and pl_last > 0:
    # Pivot data exists but no 1H df available — horizontal lines fallback
    fig = go.Figure()
    all_levels = [
        (call_breach, "Call Breach (+50)", "#dc2626", "dash",  2),
        (ph_last,     "PH_last",           "#f97316", "solid", 2),
        (ph_prev,     "PH_prev",           "#fb923c", "dot",   1) if ph_prev > 0 else None,
        (spot,        "Current Spot",      "#7c3aed", "dot",   2) if spot > 0   else None,
        (pl_last,     "PL_last",           "#16a34a", "solid", 2),
        (pl_prev,     "PL_prev",           "#4ade80", "dot",   1) if pl_prev > 0 else None,
        (put_breach,  "Put Breach (-50)",  "#15803d", "dash",  2),
    ]
    y_vals = [v[0] for v in all_levels if v and v[0] > 0]
    y_min  = min(y_vals) * 0.997 if y_vals else 22000
    y_max  = max(y_vals) * 1.003 if y_vals else 26000
    for item in all_levels:
        if item is None: continue
        level, name, colour, dash, width = item
        if level <= 0: continue
        fig.add_hline(y=level, line_color=colour, line_dash=dash, line_width=width,
                      annotation_text=f"{name}: {level:,.0f}",
                      annotation_position="right", annotation_font_color=colour)
    fig.update_layout(
        height=350, margin=dict(l=0, r=220, t=20, b=20),
        yaxis=dict(range=[y_min, y_max], title="Nifty Level", tickformat=",.0f"),
        xaxis=dict(visible=False),
        plot_bgcolor="#f8f9fb", paper_bgcolor="#f8f9fb", showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("1H candle data unavailable — level lines only. Open Home page first to load candles.")

else:
    st.info("Pivot levels not yet computed — open Home page first.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — REFERENCE TABLE
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 5 — Phase Reference",
                  "All phases, conditions, and IC implications")

ref_rows = [
    # Structure  Phase  Condition                    IC Note
    ["UPTREND",    "UT-1", "Retracing — below PH_last, above PL_last",      "1:2 CE further · PE structurally supported"],
    ["UPTREND",    "UT-2", "Continuing — last candle HIGH > PH_last",        "1:2 CE further · Uptrend extending — verify"],
    ["UPTREND",    "UT-3", "HL threatened — retrace >90%, near PL_last",     "1:2 CE further · Monitor HL closely"],
    ["UPTREND",    "UT-4", "BROKEN — last candle LOW < PL_last",             "NO_TRADE — structure changing"],
    ["DOWNTREND",  "DT-1", "Retracing up — above PL_last, below PH_last",   "2:1 PE further · CE structurally capped"],
    ["DOWNTREND",  "DT-2", "Continuing — last candle LOW < PL_last",         "2:1 PE further · Downtrend extending — verify PE"],
    ["DOWNTREND",  "DT-3", "LH threatened — retrace >90%, near PH_last",    "2:1 PE further · PRIME entry zone"],
    ["DOWNTREND",  "DT-4", "BROKEN — last candle HIGH > PH_last",           "NO_TRADE — structure changing"],
    ["MIXED",      "MX",   "Expanding or contracting range",                 "1:1 Symmetric · Wait for structure to resolve"],
    ["CONSOL.",    "SC",   "PH-PL range < 1×ATR14",                         "Wait — no actionable structure"],
]
df_ref = pd.DataFrame(ref_rows, columns=["Structure","Phase","Condition","IC Note"])

def hl_current(val):
    return "background-color:#dbeafe;font-weight:700" if val == phase else ""

st.dataframe(
    df_ref.style.map(hl_current, subset=["Phase"]),
    use_container_width=True, hide_index=True
)
st.caption("Highlighted row = current phase. Phase codes: UT=Uptrend, DT=Downtrend, MX=Mixed, SC=Consolidating.")
