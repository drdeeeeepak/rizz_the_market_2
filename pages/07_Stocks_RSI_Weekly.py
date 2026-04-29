# pages/07_Stocks_RSI_Weekly.py — Pages 07+08 Merged: Stocks RSI Monitor
# Per-stock RSI · D-W Divergence · Group signals · Combined weekly+daily reading
import streamlit as st
import pandas as pd
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P07+08 · Stocks RSI Monitor", layout="wide")
st_autorefresh(interval=60_000, key="p07")
st.title("Pages 07+08 — Stocks RSI Monitor")
st.caption("Top 10 stocks · Weekly regime · Daily divergence · Group signals")

from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)
if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

per  = sig.get("per_stock", {})
nifty_w_rsi = sig.get("rsi_weekly", sig.get("weekly_rsi", 50))

# ── Kill banners ──────────────────────────────────────────────────────────────
if sig.get("DAILY_BANKING_COLLAPSE") or sig.get("sd6_active"):
    st.error("🔴 DAILY_BANKING_COLLAPSE — 3 of 4 banks daily RSI <40. Hard kill. No new entry. Exit put if buffer <2×ATR.")
if sig.get("WEEKLY_HEAVYWEIGHT_COLLAPSE") or sig.get("sw4_active"):
    st.warning("⚠️ WEEKLY_HEAVYWEIGHT_COLLAPSE — 2+ heavyweights weekly RSI <40. +300 pts PE.")
if sig.get("WEEKLY_INDEX_MASKING"):
    st.warning("⚠️ WEEKLY_INDEX_MASKING — Nifty RSI healthy but 3+ stocks in W_BEAR. Hidden weakness. +300 pts PE.")
if sig.get("WEEKLY_BANKING_ANCHOR") or sig.get("sw3_active"):
    st.success("✅ WEEKLY_BANKING_ANCHOR — All 4 banks W_BULL or W_BULL_TRANS. PE floor anchored. -200 pts PE bonus.")
if sig.get("DAILY_LEADS_WEEKLY_DOWN"):
    st.warning(f"⚠️ DAILY_LEADS_WEEKLY_DOWN — {sig.get('leads_down_count',0)} stocks' daily RSI leading weekly lower by >8pts. Weekly downgrade imminent.")
if sig.get("DAILY_LEADS_WEEKLY_UP"):
    st.info(f"📈 DAILY_LEADS_WEEKLY_UP — {sig.get('leads_up_count',0)} stocks' daily RSI leading weekly higher. Weekly upgrade likely.")

# ── Headline metrics ──────────────────────────────────────────────────────────
breadth_lbl = sig.get("weekly_breadth_label", "WEEKLY_MIXED")
breadth_pe  = sig.get("weekly_breadth_pe_mod", 0)
avg_w_rsi   = sig.get("avg_w_rsi", 50.0)

c1,c2,c3,c4,c5,c6 = st.columns(6)
with c1: ui.metric_card("AVG WEEKLY RSI", f"{avg_w_rsi:.1f}", sub="Top 10 stocks")
with c2: ui.metric_card("BREADTH SIGNAL", breadth_lbl, sub=f"{breadth_pe:+,} pts PE",
                          color="green" if breadth_lbl=="WEEKLY_BROAD_BULL" else "red" if breadth_lbl=="WEEKLY_BROAD_WEAK" else "default")
with c3: ui.metric_card("DAILY BREADTH PE MOD", f"{sig.get('daily_breadth_pe_mod',0):+,}",
                          color="red" if sig.get("daily_breadth_pe_mod",0) > 0 else "default")
with c4: ui.metric_card("LEADS UP (DW>8)", f"{sig.get('leads_up_count',0)}/10", sub="Stocks", color="green" if sig.get("leads_up_count",0) >= 3 else "default")
with c5: ui.metric_card("LEADS DOWN (DW<-8)", f"{sig.get('leads_down_count',0)}/10", sub="Stocks", color="red" if sig.get("leads_down_count",0) >= 3 else "default")
with c6: ui.metric_card("NIFTY W RSI", f"{nifty_w_rsi:.1f}", sub="For index masking check")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Per-Stock Weekly RSI Table
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 1 — Weekly RSI Per Stock",
                  "Same seven regimes as Nifty (Page 05) applied to each stock independently")

WREG_COLOURS_HEX = {
    "W_CAPIT":    "#fecaca", "W_BEAR":       "#fee2e2", "W_BEAR_TRANS": "#fef3c7",
    "W_NEUTRAL":  "#f1f5f9", "W_BULL_TRANS": "#dcfce7", "W_BULL":       "#bbf7d0",
    "W_BULL_EXH": "#fef3c7",
}

if per:
    rows = []
    for sym, d in per.items():
        w_rsi_s = d.get("w_rsi", 50)
        d_rsi_s = d.get("d_rsi", 50)
        dw_div  = d.get("dw_divergence", round(d_rsi_s - w_rsi_s, 1))
        w_reg_s = d.get("w_regime", "W_NEUTRAL")
        dw_label = ("📈 LEADS UP" if dw_div > 8 else
                    "📉 LEADS DOWN" if dw_div < -8 else "—")
        ic_impl = ("PE anchored" if w_rsi_s >= 60 else
                   "CE drag" if w_rsi_s < 40 else "IC neutral")
        rows.append({
            "Stock":      sym,
            "W RSI":      round(w_rsi_s, 1),
            "W Regime":   w_reg_s,
            "W Slope":    round(d.get("w_slope", 0), 1),
            "D RSI":      round(d_rsi_s, 1),
            "D Zone":     d.get("d_zone", "D_BALANCE"),
            "D-W Div":    round(dw_div, 1),
            "DW Signal":  dw_label,
            "IC Impl":    ic_impl,
        })
    df_t = pd.DataFrame(rows)

    def colour_w_rsi(val):
        try:
            v = float(val)
            if v < 30:  return f"background-color:{WREG_COLOURS_HEX['W_CAPIT']};font-weight:700"
            if v < 40:  return f"background-color:{WREG_COLOURS_HEX['W_BEAR']}"
            if v >= 65: return f"background-color:{WREG_COLOURS_HEX['W_BULL']}"
            if v >= 60: return f"background-color:{WREG_COLOURS_HEX['W_BULL_TRANS']}"
        except: pass
        return ""

    def colour_dw(val):
        try:
            v = float(val)
            if v > 8:  return "color:#16a34a;font-weight:700"
            if v < -8: return "color:#dc2626;font-weight:700"
        except: pass
        return ""

    styled = (df_t.style
              .map(colour_w_rsi, subset=["W RSI"])
              .map(colour_dw, subset=["D-W Div"]))
    st.dataframe(styled, use_container_width=True, hide_index=True, height=380)
else:
    st.info("No stock data available.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Group Weekly Signals
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Weekly Group Signals",
                  "Aggregated from per-stock weekly RSI · PE and CE distance modifiers")

WSIG_ROWS = [
    ("WEEKLY_BANKING_ANCHOR",           "sw3_active",   "All 4 banks W_BULL or W_BULL_TRANS", "-200 pts PE",  "+0"),
    ("WEEKLY_HEAVYWEIGHT_COLLAPSE",     "sw4_active",   "2 of 3 heavyweights RSI <40",        "+300 pts PE",  "+0"),
    ("WEEKLY_BANKING_SOFTENING",        "bfsi_softening","2 of 4 banks weekly RSI falling",   "+200 pts PE",  "+0"),
    ("WEEKLY_INDEX_MASKING",            "",             "Nifty RSI >50 but 3+ stocks W_BEAR", "+300 pts PE",  "+0"),
    ("WEEKLY_HEAVYWEIGHT_LEADING_DOWN", "",             "HDFC or Reliance in W_BEAR",         "+200 pts PE",  "+0"),
    ("WEEKLY_SECTOR_ROTATION",          "rotation_signal","2+ banks W_BULL AND 1+ IT W_BEAR","Informational","Info"),
    ("WEEKLY_BROAD_BULL",               "",             "6+ stocks RSI ≥60",                  "-100 pts PE",  "+0"),
    ("WEEKLY_BROAD_WEAK",               "",             "3 or fewer stocks RSI ≥60",           "+200 pts PE",  "+0"),
]
sig_rows = []
for new_name, legacy, trigger, pe_mod, ce_mod in WSIG_ROWS:
    active = sig.get(new_name) or (legacy and sig.get(legacy))
    sig_rows.append({"Signal": new_name, "Active": "🔴 YES" if active else "✅ No",
                     "Trigger": trigger, "PE Mod": pe_mod, "CE Mod": ce_mod})
df_sig = pd.DataFrame(sig_rows)
def hl_active(val):
    if "YES" in str(val): return "color:#dc2626;font-weight:700"
    return "color:#16a34a"
st.dataframe(df_sig.style.map(hl_active, subset=["Active"]),
             use_container_width=True, hide_index=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Daily Signals + D-W Divergence
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — Daily Group Signals and D-W Divergence",
                  "8-point threshold · Daily leading weekly = early regime change signal")

DSIG_ROWS = [
    ("DAILY_BREADTH_BULL",    "sd5_active",  "6+ stocks daily RSI >54",          "+0 (PE confirmed)", "+0"),
    ("DAILY_BANKING_BULL",    "",            "2+ banks daily RSI >68",            "+0", "CE signal"),
    ("DAILY_LEADS_WEEKLY_UP", "",            "3+ stocks DW divergence >+8",       "Pre-empt upgrade", "+0"),
    ("DAILY_LEADS_WEEKLY_DOWN","",           "3+ stocks DW divergence <-8",       "Pre-empt downgrade","+0"),
    ("DAILY_IT_DRAG",         "sd5_active",  "INFY AND TCS daily RSI <40 + neg slope","+0", "+100 pts CE"),
    ("DAILY_BANKING_COLLAPSE","sd6_active",  "3 of 4 banks daily RSI <40",        "KILL SWITCH","KILL"),
]
dsig_rows = []
for new_name, legacy, trigger, pe_mod, ce_mod in DSIG_ROWS:
    active = sig.get(new_name) or (legacy and sig.get(legacy))
    dsig_rows.append({"Signal": new_name, "Active": "🔴 YES" if active else "✅ No",
                      "Trigger": trigger, "PE Mod": pe_mod, "CE Mod": ce_mod})
df_dsig = pd.DataFrame(dsig_rows)
st.dataframe(df_dsig.style.map(hl_active, subset=["Active"]),
             use_container_width=True, hide_index=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Combined Readings
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 4 — Combined Weekly + Daily Readings",
                  "Key combinations that drive IC action")

COMBOS = [
    ("WEEKLY_BANKING_ANCHOR + DAILY_BREADTH_BULL",
     sig.get("WEEKLY_BANKING_ANCHOR") and sig.get("DAILY_BREADTH_BULL"),
     "High confidence entry — PE can be tightest permissible. Both timeframes confirming."),
    ("WEEKLY_HEAVYWEIGHT_COLLAPSE + DAILY_LEADS_WEEKLY_DOWN",
     sig.get("WEEKLY_HEAVYWEIGHT_COLLAPSE") and sig.get("DAILY_LEADS_WEEKLY_DOWN"),
     "Maximum PE caution — +500 pts PE combined. Consider skipping."),
    ("WEEKLY_INDEX_MASKING + DAILY_LEADS_WEEKLY_DOWN",
     sig.get("WEEKLY_INDEX_MASKING") and sig.get("DAILY_LEADS_WEEKLY_DOWN"),
     "Strongest masking — +500 pts PE. High priority alert. Both timeframes hiding weakness."),
    ("WEEKLY_BANKING_SOFTENING + DAILY_BANKING_COLLAPSE",
     sig.get("WEEKLY_BANKING_SOFTENING") and sig.get("DAILY_BANKING_COLLAPSE"),
     "Hard kill — exit put leg. Do not enter."),
    ("DAILY_LEADS_WEEKLY_UP in 3+ stocks",
     sig.get("DAILY_LEADS_WEEKLY_UP"),
     "Pre-empt weekly upgrade — treat as one regime higher for IC sizing."),
]

for combo_name, active, desc in COMBOS:
    level = "danger" if active and "kill" in desc.lower() else "success" if active else "info"
    if active:
        ui.alert_box(f"{'🔴' if 'kill' in desc.lower() else '✅'} ACTIVE: {combo_name}", desc, level=level)

if not any(active for _, active, _ in COMBOS):
    ui.alert_box("No active high-priority combinations", "Standard IC conditions — no combined signals firing.", level="info")
