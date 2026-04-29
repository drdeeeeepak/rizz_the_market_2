# pages/04_Stocks_EMA_Ribbon.py — Page 4: Constituent EMA Hold Monitor
# Per-stock Canary · Group Canary Aggregation · Moat Clustering Check
import streamlit as st
import pandas as pd
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P04 · Constituent Hold Monitor", layout="wide")
st_autorefresh(interval=60_000, key="p04")
st.title("Page 04 — Heavyweight Constituent Hold Monitor")
st.caption("Per-stock Canary · Group-level Canary Aggregation · Intraweek PE/CE Adjustment")

# ── Bootstrap: works without Home page ───────────────────────────────────────
from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)
if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

canary_data = sig.get("constituent_canary", {})

# ── Group Canary banners ──────────────────────────────────────────────────────
if canary_data.get("broad_canary_active"):
    st.error(f"🔴 BROAD CANARY — {canary_data.get('broad_canary_count',0)} of 10 stocks at Canary Day 3+. "
             f"Index-level regime deterioration. Add +200 pts PE regardless of Nifty canary.")
if canary_data.get("banking_canary_level", 0) >= 3:
    st.warning(f"⚠️ BANKING_CANARY Day {canary_data['banking_canary_level']} — "
               f"At least one banking stock in structural deterioration. Upgrade banking group alert.")
if canary_data.get("heavyweight_canary_level", 0) >= 3:
    st.warning(f"⚠️ HEAVYWEIGHT_CANARY Day {canary_data['heavyweight_canary_level']} — "
               f"At least one heavyweight in structural deterioration. Upgrade heavyweight alert.")

# ── Group Canary metrics ──────────────────────────────────────────────────────
st.subheader("Group-Level Canary Aggregation")
ui.simple_technical(
    "Each stock has its own canary level. We aggregate to group level — banking, heavyweight, and broad (all 10). A high canary in even one banking stock is a warning for the whole group.",
    "BANKING_CANARY: max canary of HDFC, ICICI, Axis, Kotak\nHEAVYWEIGHT_CANARY: max of HDFC, Reliance, ICICI\nBROAD_CANARY: count of stocks at Day 3+ ≥ 4 = fires"
)
st.markdown("")

c1, c2, c3, c4 = st.columns(4)
bank_c = canary_data.get("banking_canary_level", 0)
heavy_c = canary_data.get("heavyweight_canary_level", 0)
broad_c = canary_data.get("broad_canary_count", 0)
broad_active = canary_data.get("broad_canary_active", False)

with c1: ui.metric_card("BANKING CANARY", f"Day {bank_c}",
                          sub="Max of 4 banking stocks", color="red" if bank_c >= 3 else "amber" if bank_c >= 2 else "green")
with c2: ui.metric_card("HEAVYWEIGHT CANARY", f"Day {heavy_c}",
                          sub="Max of top 3 weights", color="red" if heavy_c >= 3 else "amber" if heavy_c >= 2 else "green")
with c3: ui.metric_card("BROAD CANARY COUNT", f"{broad_c}/10",
                          sub="Stocks at Day 3+", color="red" if broad_active else "amber" if broad_c >= 2 else "green")
with c4: ui.metric_card("BROAD CANARY ACTIVE", "🔴 YES" if broad_active else "✅ NO",
                          sub="+200 pts PE when active", color="red" if broad_active else "green")

st.divider()

# ── Per-stock Canary table ────────────────────────────────────────────────────
st.subheader("Per-Stock Canary Level")
st.caption("Same four Canary levels as Page 02 — run on each stock's EMA3, EMA8, EMA16, EMA30 daily.")

per = sig.get("constituent_per_stock", {})
if per:
    rows = []
    for sym, d in per.items():
        cl = d.get("canary_level", 0)
        regime = d.get("regime", "—")
        mom = d.get("mom_state", "FLAT")
        icon = "🔴" if cl >= 3 else "⚠️" if cl >= 2 else "🟡" if cl >= 1 else "✅"
        rows.append({
            "Stock":       sym,
            "Canary":      f"{icon} Day {cl}",
            "Canary Lvl":  cl,
            "Regime":      regime,
            "Momentum":    mom,
            "Put Moats":   d.get("put_moats", 0),
        })
    df_t = pd.DataFrame(rows)

    def colour_canary(val):
        try:
            v = int(val)
            if v >= 3: return "color:#dc2626;font-weight:700"
            if v >= 2: return "color:#d97706;font-weight:600"
            if v == 1: return "color:#ca8a04"
        except: pass
        return "color:#16a34a"

    styled = df_t.style.map(colour_canary, subset=["Canary Lvl"])
    st.dataframe(styled[["Stock","Canary","Regime","Momentum","Put Moats"]],
                 use_container_width=True, hide_index=True)

st.divider()

# ── Moat Clustering Check ─────────────────────────────────────────────────────
st.subheader("Moat Clustering Check Per Stock")
ui.simple_technical(
    "If a stock has multiple moats within 50 points of each other, they count as one combined moat. Closely bunched EMAs will fall together — not sequentially. This prevents false sense of security.",
    "Clustering threshold: 50 points. Applied same as Page 01. A stock showing 3 moats all within 50 pts of each other = effectively 1 moat."
)
st.markdown("")

if per:
    cluster_rows = []
    for sym, d in per.items():
        put_detail = d.get("put_moat_detail", [])
        # Detect clustering: any consecutive moats within 50 pts
        clustered = False
        if len(put_detail) >= 2:
            for i in range(len(put_detail)-1):
                v1 = put_detail[i][1] if isinstance(put_detail[i], tuple) else 0
                v2 = put_detail[i+1][1] if isinstance(put_detail[i+1], tuple) else 0
                if abs(v1-v2) <= 50:
                    clustered = True
        cluster_rows.append({
            "Stock":          sym,
            "Put Moats (eff.)": d.get("put_moats",0),
            "Moat Levels":    ", ".join(f"EMA{p}@{v:,.0f}" for p,v in put_detail) if put_detail else "—",
            "Clustering":     "⚠️ Yes" if clustered else "No",
        })
    st.dataframe(pd.DataFrame(cluster_rows), use_container_width=True, hide_index=True)

st.divider()
st.caption("Page 7 (Weekly RSI per stock) is the momentum lens. Pages 3+4 are the structural EMA lens. Different questions, same data.")
