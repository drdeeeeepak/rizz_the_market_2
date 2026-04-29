# pages/04_Stocks_EMA_Ribbon.py — v2 (22 April 2026)
# Constituent EMA Hold Monitor
# Per-stock Three-Source Canary · Group Canary · Moat Status · Group Action
#
# CHANGES FROM v1:
#   - Auto-compute fallback if session state empty
#   - Per-stock canary upgraded to three-source system (matching Page 2)
#   - Source breakdown section for worst stock (Section 3)
#   - Group action recommendation table (Section 5)
#   - BROAD_CANARY modifier updated to +150 pts in banner
#   - BROAD_CANARY and group canaries are the ONLY canary signals here —
#     Page 3 shows no canary at all

import streamlit as st
import pandas as pd
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P04 · Constituent Hold Monitor", layout="wide")
st_autorefresh(interval=60_000, key="p04")
st.title("Page 04 — Heavyweight Constituent Hold Monitor")
st.caption(
    "Per-stock Three-Source Canary · Group Canary Aggregation · "
    "Moat Status · Group Action Recommendation"
)

from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)
if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

canary_data = sig.get("constituent_canary", {})
per         = sig.get("constituent_per_stock", {})
breadth     = sig.get("constituent_breadth", {})

# ── Canary level helpers ──────────────────────────────────────────────────────
CANARY_COLOUR = {0: "green", 1: "amber", 2: "amber", 3: "red", 4: "red"}
CANARY_ICON   = {0: "✅", 1: "🟡", 2: "⚠️", 3: "🔴", 4: "🔴"}
CANARY_LABEL  = {0: "SINGING", 1: "Day 1", 2: "Day 2", 3: "Day 3", 4: "Day 4"}

def canary_text(level: int) -> str:
    return f"{CANARY_ICON.get(level, '⚪')} {CANARY_LABEL.get(level, '—')}"

# ── Overall page header colour from worst group canary ────────────────────────
bank_c   = canary_data.get("banking_canary_level", 0)
heavy_c  = canary_data.get("heavyweight_canary_level", 0)
broad_c  = canary_data.get("broad_canary_count", 0)
broad_ok = canary_data.get("broad_canary_active", False)
worst_group = max(bank_c, heavy_c, 4 if broad_ok else 0)

# ══════════════════════════════════════════════════════════════════════════════
# GROUP CANARY BANNERS (always at top)
# ══════════════════════════════════════════════════════════════════════════════
if broad_ok:
    st.error(
        f"🔴 BROAD CANARY ACTIVE — {broad_c} of 10 stocks at Day 3 or above. "
        f"Index-level regime deterioration spreading. +150 pts PE. "
        f"This is broader than Nifty\u2019s own canary \u2014 constituent weakness is widespread."
    )
if bank_c >= 3:
    st.warning(
        f"⚠️ BANKING CANARY Day {bank_c} — "
        f"Stock: {canary_data.get('worst_banking_stock', '—')} is the highest. "
        f"Banking group structural deterioration. Upgrade banking alert level."
    )
if heavy_c >= 3:
    st.warning(
        f"⚠️ HEAVYWEIGHT CANARY Day {heavy_c} — "
        f"Stock: {canary_data.get('worst_heavy_stock', '—')} is the highest. "
        f"Heavyweight structural deterioration. Upgrade heavyweight alert."
    )
if worst_group == 0:
    st.success("✅ All group canaries SINGING — No constituent deterioration detected.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Group Canary Dashboard
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 1 — Group Canary Dashboard",
                  "Three group-level canary signals \u2014 aggregated from per-stock three-source canary")

ui.simple_technical(
    "Each stock has its own three-source canary (EMA proximity + momentum acceleration + "
    "drift from its own Tuesday close). These are aggregated to group level. "
    "BROAD_CANARY fires when 4 or more stocks reach Day 3 simultaneously \u2014 "
    "this is an index-breadth early warning that often precedes Nifty\u2019s own canary.",
    "BANKING_CANARY: max canary of HDFC, ICICI, Axis, Kotak\n"
    "HEAVYWEIGHT_CANARY: max canary of HDFC, Reliance, ICICI\n"
    "BROAD_CANARY: count of all 10 stocks at Day 3+ \u2265 4 = fires"
)

c1, c2, c3, c4 = st.columns(4)
with c1:
    ui.metric_card("BANKING CANARY", canary_text(bank_c),
                   sub=f"Worst: {canary_data.get('worst_banking_stock', '—')}",
                   color=CANARY_COLOUR.get(bank_c, "default"))
with c2:
    ui.metric_card("HEAVYWEIGHT CANARY", canary_text(heavy_c),
                   sub=f"Worst: {canary_data.get('worst_heavy_stock', '—')}",
                   color=CANARY_COLOUR.get(heavy_c, "default"))
with c3:
    ui.metric_card("BROAD CANARY COUNT", f"{broad_c} / 10",
                   sub="Stocks at Day 3+",
                   color="red" if broad_ok else "amber" if broad_c >= 2 else "green")
with c4:
    ui.metric_card("BROAD CANARY",
                   "🔴 ACTIVE +150 pts" if broad_ok else "✅ Not active",
                   sub="PE modifier when active",
                   color="red" if broad_ok else "green")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Per-Stock Canary Table
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Per-Stock Canary Level",
                  "Three-source canary per stock \u2014 Day 0 (SINGING) to Day 4")

if per:
    rows = []
    for sym, d in per.items():
        overall  = d.get("canary_level", 0)
        pe_lvl   = d.get("canary_pe_level", 0)
        ce_lvl   = d.get("canary_ce_level", 0)
        driver   = d.get("canary_driver", "—")
        s1pe     = d.get("canary_src1_pe", 0)
        s2pe     = d.get("canary_src2_pe", 0)
        s3pe     = d.get("canary_src3_pe", 0)
        s1ce     = d.get("canary_src1_ce", 0)
        s2ce     = d.get("canary_src2_ce", 0)
        s3ce     = d.get("canary_src3_ce", 0)
        rows.append({
            "Stock":         sym,
            "Overall":       canary_text(overall),
            "PE Side":       canary_text(pe_lvl),
            "CE Side":       canary_text(ce_lvl),
            "Driving Source":driver,
            "S1 PE":         s1pe,
            "S2 PE":         s2pe,
            "S3 PE":         s3pe,
            "Put Moats":     d.get("put_moats", 0),
            "Regime":        d.get("regime", "—"),
            "_overall":      overall,
        })

    df_t = pd.DataFrame(rows)

    def colour_overall(val):
        label = str(val)
        if "Day 4" in label or "Day 3" in label:
            return "color:#dc2626;font-weight:700"
        if "Day 2" in label:
            return "color:#d97706;font-weight:600"
        if "Day 1" in label:
            return "color:#ca8a04"
        return "color:#16a34a"

    def colour_src(val):
        try:
            v = int(val)
            if v >= 3: return "color:#dc2626;font-weight:700"
            if v >= 2: return "color:#d97706"
            if v == 1: return "color:#ca8a04"
        except Exception:
            pass
        return "color:#16a34a"

    display_cols = ["Stock", "Overall", "PE Side", "CE Side",
                    "Driving Source", "S1 PE", "S2 PE", "S3 PE", "Put Moats", "Regime"]
    styled = (df_t[display_cols].style
              .map(colour_overall, subset=["Overall", "PE Side", "CE Side"])
              .map(colour_src, subset=["S1 PE", "S2 PE", "S3 PE"]))
    st.dataframe(styled, use_container_width=True, hide_index=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Source Breakdown for Worst Stock
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — Three-Source Breakdown",
                  "Inspect any stock\u2019s canary sources in detail")

if per:
    # Default to worst stock overall
    worst_stock = max(per.keys(), key=lambda s: per[s].get("canary_level", 0))
    stock_choice = st.selectbox(
        "Select stock to inspect",
        options=list(per.keys()),
        index=list(per.keys()).index(worst_stock) if worst_stock in per else 0
    )

    d = per.get(stock_choice, {})
    col1, col2 = st.columns(2)

    with col1:
        st.markdown(f"**{stock_choice} — PE Side Canary: {canary_text(d.get('canary_pe_level', 0))}**")
        src_rows_pe = [
            ["Source 1 — EMA Proximity",        d.get("canary_src1_pe", 0), "EMA3 vs EMA8 gap as % of ATR — fires before crossover"],
            ["Source 2 — Momentum Accel (3-day)", d.get("canary_src2_pe", 0), "Momentum score today vs 3 days ago — rolling deceleration"],
            ["Source 3 — Tuesday Close Drift",   d.get("canary_src3_pe", 0), "Spot drift from stock\u2019s own Tuesday close + mean reversion check"],
            ["PE Canary Overall",                d.get("canary_pe_level", 0), "Max of three sources on PE side"],
        ]
        df_pe = pd.DataFrame(src_rows_pe, columns=["Source", "Level", "What It Measures"])
        st.dataframe(df_pe, use_container_width=True, hide_index=True)

    with col2:
        st.markdown(f"**{stock_choice} — CE Side Canary: {canary_text(d.get('canary_ce_level', 0))}**")
        src_rows_ce = [
            ["Source 1 — EMA Proximity",        d.get("canary_src1_ce", 0), "Bullish EMA deterioration — gap before bullish crossover fades"],
            ["Source 2 — Momentum Accel (3-day)", d.get("canary_src2_ce", 0), "Upward momentum deceleration — tailwind fading for CE"],
            ["Source 3 — Tuesday Close Drift",   d.get("canary_src3_ce", 0), "Upward drift from Tuesday close — CE side encroachment"],
            ["CE Canary Overall",                d.get("canary_ce_level", 0), "Max of three sources on CE side"],
        ]
        df_ce = pd.DataFrame(src_rows_ce, columns=["Source", "Level", "What It Measures"])
        st.dataframe(df_ce, use_container_width=True, hide_index=True)

    # Context for selected stock
    st.markdown(f"**{stock_choice} — Current State**")
    c1, c2, c3, c4 = st.columns(4)
    with c1: ui.metric_card("REGIME", d.get("regime", "—"))
    with c2: ui.metric_card("PUT MOATS", f"{d.get('put_moats', 0):.1f}",
                              color="green" if d.get("put_moats", 0) >= 3
                              else "red" if d.get("put_moats", 0) == 0 else "amber")
    with c3: ui.metric_card("MOMENTUM", d.get("mom_state", "—"))
    with c4: ui.metric_card("ATR", f"{d.get('atr', 0):.0f} pts")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Live Moat Status Per Stock
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 4 — Live Moat Status Per Stock",
                  "Current put moat count \u2014 updates daily during hold as prices and EMAs move")

if per:
    moat_rows = []
    for sym, d in per.items():
        put_detail  = d.get("put_moat_detail", [])
        pm          = d.get("put_moats", 0)
        pm_label_v  = {5: "Fortress", 4: "Fortress", 3: "Strong",
                       2: "Adequate", 1: "Thin", 0: "Exposed"}.get(int(pm) if pm >= 1 else 0, "Exposed")

        # Clustering check
        clustered = False
        if len(put_detail) >= 2:
            for i in range(len(put_detail) - 1):
                v1 = put_detail[i][1] if isinstance(put_detail[i], (list, tuple)) else 0
                v2 = put_detail[i+1][1] if isinstance(put_detail[i+1], (list, tuple)) else 0
                if abs(v1 - v2) <= 50:
                    clustered = True

        moat_levels = ", ".join(
            f"{p}@{v:,.0f}" for p, v in put_detail
        ) if put_detail else "—"

        moat_rows.append({
            "Stock":             sym,
            "Put Moats (eff.)":  f"{pm:.1f} — {pm_label_v}",
            "Moat EMA Levels":   moat_levels,
            "Clustering Alert":  "⚠️ Yes — moats within 50 pts" if clustered else "No",
            "_pm":               float(pm),
        })

    df_m = pd.DataFrame(moat_rows)

    def colour_moat_eff(val):
        try:
            v = float(val.split("—")[0].strip())
            if v == 0:  return "color:#dc2626;font-weight:700"
            if v < 2:   return "color:#d97706;font-weight:600"
            if v >= 3:  return "color:#16a34a;font-weight:600"
        except Exception:
            pass
        return ""

    styled_m = df_m[["Stock", "Put Moats (eff.)", "Moat EMA Levels", "Clustering Alert"]].style\
        .map(colour_moat_eff, subset=["Put Moats (eff.)"])
    st.dataframe(styled_m, use_container_width=True, hide_index=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Group Action Recommendation
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 5 — Group Action Recommendation",
                  "Combined group canary + breadth moat score \u2014 HOLD / WATCH / PREPARE / ACT")

b_label = breadth.get("label", "ADEQUATE")

# Determine group recommendation
def group_action(canary_lvl: int, breadth_lbl: str) -> tuple:
    """Returns (action, colour, explanation)"""
    if canary_lvl >= 4:
        return "ACT", "red", "Broad constituent collapse. Roll or exit. Do not wait."
    if canary_lvl == 3 and breadth_lbl in ("THINNING", "COLLAPSE"):
        return "ACT", "red", "Constituent deterioration serious. Breadth also thinning. Act now."
    if canary_lvl == 3:
        return "PREPARE", "amber", "Deterioration spreading. Have roll plan ready. Know your exit strikes."
    if canary_lvl == 2:
        return "WATCH", "amber", "Constituent deterioration starting. Monitor at next EOD."
    if canary_lvl <= 1 and breadth_lbl == "THINNING":
        return "WATCH", "amber", "Breadth thinning even without canary. Monitor closely."
    return "HOLD", "green", "Constituents supporting IC. No action needed from this page."

banking_action, bank_col, bank_exp = group_action(bank_c, b_label)
heavy_action,   heavy_col, heavy_exp = group_action(heavy_c, b_label)
broad_action,   broad_col, broad_exp = group_action(4 if broad_ok else worst_group, b_label)

col1, col2, col3 = st.columns(3)
with col1:
    ui.alert_box(
        f"Banking Group — {banking_action}",
        f"Canary: Day {bank_c} \u00B7 Breadth: {b_label}\n{bank_exp}",
        level="danger" if bank_col == "red" else "warning" if bank_col == "amber" else "success"
    )
with col2:
    ui.alert_box(
        f"Heavyweight Group — {heavy_action}",
        f"Canary: Day {heavy_c} \u00B7 Breadth: {b_label}\n{heavy_exp}",
        level="danger" if heavy_col == "red" else "warning" if heavy_col == "amber" else "success"
    )
with col3:
    ui.alert_box(
        f"Broad Constituent — {broad_action}",
        f"BROAD CANARY: {'Active' if broad_ok else 'Not active'} \u00B7 "
        f"{broad_c}/10 stocks at Day 3+\n{broad_exp}",
        level="danger" if broad_col == "red" else "warning" if broad_col == "amber" else "success"
    )

st.markdown("")

# Reference table
ref_data = [
    ["Day 0\u20131", "BROAD_HEALTH or ADEQUATE", "HOLD",    "Constituents supporting IC"],
    ["Day 0\u20131", "THINNING",                 "WATCH",   "Breadth thinning — monitor daily"],
    ["Day 2",        "Any",                       "WATCH",   "Deterioration starting"],
    ["Day 3",        "ADEQUATE or better",        "PREPARE", "Have roll plan ready"],
    ["Day 3",        "THINNING or COLLAPSE",      "ACT",     "Deterioration serious"],
    ["Day 4",        "Any",                       "ACT",     "Broad constituent collapse"],
]
df_ref = pd.DataFrame(ref_data,
                      columns=["Group Canary", "Breadth Score", "Recommendation", "Note"])
st.caption("Group Action Reference Table")
st.dataframe(df_ref, use_container_width=True, hide_index=True)

st.divider()
st.caption(
    "Page 7 (Weekly RSI per stock) is the momentum and exhaustion lens. "
    "Pages 3+4 are the structural EMA lens. Different questions, same underlying stock data."
)
