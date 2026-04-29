# pages/03_Stocks_EMA_Price.py — Page 3: Constituent EMA Entry Engine
# Cluster Regime per stock · Moat Count · Momentum · Group signals · Breadth
import streamlit as st
import pandas as pd
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P03 · Constituent EMA Entry", layout="wide")
st_autorefresh(interval=60_000, key="p03")
st.title("Page 03 — Heavyweight Constituent EMA Entry Engine")
st.caption("Cluster Regime per stock · Moat Count · Momentum · Group Signals · Breadth Score")

# ── Bootstrap: works without Home page ───────────────────────────────────────
from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)
if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

# ── Kill and alert banners ────────────────────────────────────────────────────
if sig.get("BANKING_DAILY_COLLAPSE"):
    st.error("🔴 BANKING_DAILY_COLLAPSE — 3 of 4 banking stocks in Strong Bear or Bear Compressed. KILL SWITCH. No new entries. Review open positions.")
if sig.get("HEAVYWEIGHT_COLLAPSE"):
    st.warning("⚠️ HEAVYWEIGHT_COLLAPSE — 2 of 3 heavyweights in Bear Compressed or Strong Bear. +300 pts PE distance.")
if sig.get("INDEX_MASKING_WEAKNESS"):
    st.warning("⚠️ INDEX_MASKING_WEAKNESS — Nifty looks bullish but 3+ top 10 stocks in bear regime. Hidden weakness. +300 pts PE.")
if sig.get("HEAVYWEIGHT_LEADING_DOWN"):
    st.warning("⚠️ HEAVYWEIGHT_LEADING_DOWN — HDFC Bank or Reliance in Inside Bear while Nifty bullish. +200 pts PE.")
if sig.get("BANKING_ALL_BULLISH"):
    st.success("✅ BANKING_ALL_BULLISH — All 4 banking stocks in Strong Bull or Bull Compressed. PE floor anchored. -200 pts PE bonus.")

# ── Headline metrics ──────────────────────────────────────────────────────────
breadth = sig.get("constituent_breadth", {})
c1,c2,c3,c4,c5,c6 = st.columns(6)
with c1: ui.metric_card("BREADTH SCORE", f"{breadth.get('score_pct',50):.0f}%",
                          sub=breadth.get("label","—"),
                          color="green" if breadth.get("score_pct",50) >= 60 else "red" if breadth.get("score_pct",50) < 40 else "amber")
with c2: ui.metric_card("BANKING ALL BULL", "✅ YES" if sig.get("BANKING_ALL_BULLISH") else "NO",
                          color="green" if sig.get("BANKING_ALL_BULLISH") else "default")
with c3: ui.metric_card("HEAVY COLLAPSE", "🔴 YES" if sig.get("HEAVYWEIGHT_COLLAPSE") else "NO",
                          color="red" if sig.get("HEAVYWEIGHT_COLLAPSE") else "default")
with c4: ui.metric_card("INDEX MASKING", "⚠️ YES" if sig.get("INDEX_MASKING_WEAKNESS") else "NO",
                          color="red" if sig.get("INDEX_MASKING_WEAKNESS") else "default")
with c5: ui.metric_card("IT DRAG", "⚠️ YES" if sig.get("IT_SECTOR_DRAG") else "NO",
                          color="amber" if sig.get("IT_SECTOR_DRAG") else "default")
with c6: ui.metric_card("CONSTITUENT PE MOD", f"{sig.get('constituent_pe_mod',0):+,} pts",
                          color="red" if sig.get("constituent_pe_mod",0) > 200 else "green" if sig.get("constituent_pe_mod",0) < 0 else "default")

st.divider()

# ── Per-stock cluster table ───────────────────────────────────────────────────
st.subheader("Per-Stock Cluster Regime and Moat Count")
st.caption("Same framework as Page 01 — applied to each stock's own daily candles independently.")

per = sig.get("constituent_per_stock", {})
if per:
    rows = []
    for sym, d in per.items():
        regime = d.get("regime", "—")
        regime_icon = ("🟢" if regime in ("STRONG_BULL","BULL_COMPRESSED") else
                       "🔴" if regime in ("STRONG_BEAR","BEAR_COMPRESSED") else
                       "⚠️" if regime == "INSIDE_BEAR" else "🔵")
        mom = d.get("mom_state","FLAT")
        rows.append({
            "Stock":        sym,
            "Regime":       f"{regime_icon} {regime}",
            "Put Moats":    d.get("put_moats", 0),
            "Call Moats":   d.get("call_moats", 0),
            "Momentum":     mom,
            "Canary Lvl":   d.get("canary_level", 0),
            "ATR":          f"{d.get('atr',0):.0f}",
            "Spot":         f"{d.get('spot',0):,.0f}",
        })
    df_t = pd.DataFrame(rows)

    def colour_moat(val):
        try:
            v = int(val)
            if v == 0: return "color:#dc2626;font-weight:700"
            if v == 1: return "color:#d97706;font-weight:600"
            if v >= 3: return "color:#16a34a;font-weight:600"
        except: pass
        return ""

    def colour_mom(val):
        if "STRONG" in str(val): return "color:#dc2626;font-weight:700"
        if "MODERATE" in str(val): return "color:#d97706"
        if "TRANSITIONING" in str(val): return "color:#7c3aed"
        return "color:#5a6b8a"

    styled = (df_t.style
              .map(colour_moat, subset=["Put Moats","Call Moats"])
              .map(colour_mom, subset=["Momentum"]))
    st.dataframe(styled, use_container_width=True, hide_index=True)
else:
    st.info("No constituent data — check stock data loading.")

st.divider()

# ── Group summary ─────────────────────────────────────────────────────────────
st.subheader("Group Summary")
banking = sig.get("constituent_banking", {})
heavy   = sig.get("constituent_heavyweight", {})
it_d    = sig.get("constituent_it", {})

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("**Banking Group** (HDFC, ICICI, Axis, Kotak)")
    st.write(f"All bullish: {'✅' if banking.get('all_bullish') else '❌'}")
    st.write(f"Any bear: {'⚠️' if banking.get('any_bear') else '✅ No'}")
    st.write(f"Bear count: {banking.get('count_bear', 0)} of 4")
    st.write(f"Weakening: {'⚠️ Yes' if banking.get('weakening') else 'No'}")

with col2:
    st.markdown("**Heavyweight Group** (HDFC, Reliance, ICICI)")
    st.write(f"Bear count: {heavy.get('count_bear', 0)} of 3")
    st.write(f"Collapse active: {'🔴 Yes' if heavy.get('any_collapse') else 'No'}")

with col3:
    st.markdown("**IT Group** (Infosys, TCS)")
    st.write(f"Both bear: {'⚠️ Yes' if it_d.get('both_bear') else 'No'}")
    it_regimes = it_d.get("regimes", [])
    if it_regimes:
        st.write(f"Regimes: {', '.join(it_regimes)}")

st.divider()

# ── Breadth moat score ────────────────────────────────────────────────────────
st.subheader("Breadth Moat Score")
ui.simple_technical(
    f"How many of the top 10 stocks have 2 or more downside moats protecting them. Currently {breadth.get('count_2plus',0)} of 10 stocks have adequate moat protection ({breadth.get('score_pct',50)}%).",
    "Breadth ≥80% = BROAD_HEALTH (-100 pts PE bonus)\nBreadth 60-79% = ADEQUATE (no modifier)\nBreadth 40-59% = THINNING (+200 pts PE)\nBreadth <40% = COLLAPSE (+400 pts PE)"
)
