# pages/03_Stocks_EMA_Price.py — v2 (22 April 2026)
# Constituent EMA Entry Engine
# Cluster Regime per stock · Moat Count · Momentum · Group Signals · Breadth
#
# CHANGES FROM v1:
#   - Auto-compute fallback if session state empty (no forced Home redirect)
#   - Updated modifier values in banners (recalibrated)
#   - Removed canary column from per-stock table (canary is Page 4 only)
#   - Added modifier summary section (Section 6)
#   - SECTOR_ROTATION_DETECTED banner added
#   - Breadth modifier shown alongside named modifier

import streamlit as st
import pandas as pd
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P03 · Constituent EMA Entry", layout="wide")
st_autorefresh(interval=60_000, key="p03")
st.title("Page 03 — Heavyweight Constituent EMA Entry Engine")
st.caption("Cluster Regime per stock · Moat Count · Momentum · Group Signals · Breadth Score")

from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)
if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

import datetime, pytz
def _is_live():
    n = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
    t = n.hour * 60 + n.minute
    return n.weekday() < 5 and 9*60+15 <= t <= 15*60+30

if _is_live():
    try:
        from data.live_fetcher import get_top10_daily_live
        from analytics.constituent_ema import ConstituentEMAEngine
        _cema = ConstituentEMAEngine().signals(get_top10_daily_live())
        sig = {**sig, **_cema}
        sig["breadth_score"]    = _cema.get("constituent_breadth", {}).get("score_pct", sig.get("breadth_score", 50))
        sig["breadth_label"]    = _cema.get("constituent_breadth", {}).get("label", sig.get("breadth_label", "ADEQUATE"))
        sig["divergence_alert"] = _cema.get("INDEX_MASKING_WEAKNESS", sig.get("divergence_alert", False))
        signals_ts = "LIVE"
    except Exception as _e:
        st.caption(f"Live Constituent EMA unavailable: {_e}")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Alert Banners
# ══════════════════════════════════════════════════════════════════════════════
if sig.get("BANKING_DAILY_COLLAPSE"):
    st.error(
        "🔴 BANKING_DAILY_COLLAPSE — 3 of 4 banking stocks in Strong Bear or Bear Compressed. "
        "KILL SWITCH — No new entries. Review all open positions immediately."
    )
if sig.get("HEAVYWEIGHT_COLLAPSE"):
    st.warning(
        "⚠️ HEAVYWEIGHT_COLLAPSE — 2 of 3 heavyweights in Bear Compressed or Strong Bear. "
        "+150 pts PE distance."
    )
if sig.get("INDEX_MASKING_WEAKNESS"):
    st.warning(
        "⚠️ INDEX_MASKING_WEAKNESS — Nifty looks bullish but 3+ top 10 stocks in bear regime. "
        "Hidden weakness beneath the surface. +150 pts PE."
    )
if sig.get("HEAVYWEIGHT_LEADING_DOWN"):
    st.warning(
        "⚠️ HEAVYWEIGHT_LEADING_DOWN — HDFC Bank or Reliance in Inside Bear while Nifty bullish. "
        "Heavyweight leading down. +100 pts PE."
    )
if sig.get("BANKING_SLOPE_WEAKENING"):
    st.warning(
        "⚠️ BANKING_SLOPE_WEAKENING — 2+ banking stocks transitioning into Inside Bull with "
        "downward momentum. Early deterioration signal. +100 pts PE."
    )
if sig.get("IT_SECTOR_DRAG"):
    st.warning(
        "⚠️ IT_SECTOR_DRAG — Infosys and TCS both in Strong Bear or Bear Compressed. "
        "IT sector dragging CE side. +50 pts CE."
    )
if sig.get("BANKING_ALL_BULLISH"):
    st.success(
        "✅ BANKING_ALL_BULLISH — All 4 banking stocks in Strong Bull or Bull Compressed. "
        "PE floor structurally anchored. −100 pts PE bonus."
    )
if sig.get("SECTOR_ROTATION_DETECTED"):
    st.info(
        "ℹ️ SECTOR_ROTATION_DETECTED — 2+ banking stocks in Strong Bull AND 1+ IT stocks "
        "in bear regime. Sector rotation underway — informational only."
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Headline Metrics
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Headline Metrics", "Key constituent signals at a glance")

breadth = sig.get("constituent_breadth", {})
pe_mod  = sig.get("constituent_pe_mod", 0)
ce_mod  = sig.get("constituent_ce_mod", 0)

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1:
    b_pct = breadth.get("score_pct", 50)
    ui.metric_card("BREADTH SCORE", f"{b_pct:.0f}%",
                   sub=breadth.get("label", "—"),
                   color="green" if b_pct >= 60 else "red" if b_pct < 40 else "amber")
with c2:
    ui.metric_card("BANKING ALL BULL",
                   "✅ YES" if sig.get("BANKING_ALL_BULLISH") else "NO",
                   color="green" if sig.get("BANKING_ALL_BULLISH") else "default")
with c3:
    ui.metric_card("HEAVY COLLAPSE",
                   "🔴 YES" if sig.get("HEAVYWEIGHT_COLLAPSE") else "NO",
                   color="red" if sig.get("HEAVYWEIGHT_COLLAPSE") else "default")
with c4:
    ui.metric_card("INDEX MASKING",
                   "⚠️ YES" if sig.get("INDEX_MASKING_WEAKNESS") else "NO",
                   color="red" if sig.get("INDEX_MASKING_WEAKNESS") else "default")
with c5:
    ui.metric_card("IT DRAG",
                   "⚠️ YES" if sig.get("IT_SECTOR_DRAG") else "NO",
                   color="amber" if sig.get("IT_SECTOR_DRAG") else "default")
with c6:
    pe_color = "red" if pe_mod > 100 else "green" if pe_mod < 0 else "amber" if pe_mod > 0 else "default"
    ui.metric_card("CONSTITUENT PE MOD", f"{pe_mod:+,} pts",
                   sub="Capped at +200 / −100",
                   color=pe_color)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Per-Stock Cluster Table
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — Per-Stock Cluster Regime and Moat Count",
                  "Same framework as Page 01 applied to each stock\u2019s own daily candles independently")

per = sig.get("constituent_per_stock", {})

REGIME_ICON = {
    "STRONG_BULL":     "🟢",
    "BULL_COMPRESSED": "🟢",
    "INSIDE_BULL":     "🔵",
    "RECOVERING":      "🔵",
    "INSIDE_BEAR":     "⚠️",
    "BEAR_COMPRESSED": "🔴",
    "STRONG_BEAR":     "🔴",
}
MOAT_LABEL = {5: "Fortress", 4: "Fortress", 3: "Strong", 2: "Adequate", 1: "Thin", 0: "Exposed"}

if per:
    rows = []
    for sym in [s for s in per if s in per]:   # preserve TOP_10 order
        d      = per[sym]
        regime = d.get("regime", "—")
        icon   = REGIME_ICON.get(regime, "⚪")
        pm     = d.get("put_moats", 0)
        cm     = d.get("call_moats", 0)
        pm_label = MOAT_LABEL.get(int(pm) if pm >= 1 else 0, "Exposed")
        cm_label = MOAT_LABEL.get(int(cm) if cm >= 1 else 0, "Exposed")
        mom    = d.get("mom_state", "FLAT")
        rows.append({
            "Stock":      sym,
            "Regime":     f"{icon} {regime}",
            "Put Moats":  f"{pm:.1f} — {pm_label}",
            "Call Moats": f"{cm:.1f} — {cm_label}",
            "Momentum":   mom,
            "ATR":        f"{d.get('atr', 0):.0f}",
            "Spot":       f"{d.get('spot', 0):,.0f}",
            "_pm_val":    float(pm),
            "_cm_val":    float(cm),
            "_mom":       mom,
        })

    df_t = pd.DataFrame(rows)

    def colour_moat_col(val):
        try:
            v = float(val.split("—")[0].strip())
            if v == 0:   return "color:#dc2626;font-weight:700"
            if v < 2:    return "color:#d97706;font-weight:600"
            if v >= 3:   return "color:#16a34a;font-weight:600"
        except Exception:
            pass
        return ""

    def colour_mom(val):
        s = str(val)
        if "STRONG" in s:       return "color:#dc2626;font-weight:700"
        if "MODERATE" in s:     return "color:#d97706"
        if "TRANSITIONING" in s: return "color:#7c3aed"
        return "color:#5a6b8a"

    display_cols = ["Stock", "Regime", "Put Moats", "Call Moats", "Momentum", "ATR", "Spot"]
    styled = (df_t[display_cols].style
              .map(colour_moat_col, subset=["Put Moats", "Call Moats"])
              .map(colour_mom, subset=["Momentum"]))
    st.dataframe(styled, width="stretch", hide_index=True)

    st.caption("Note: No canary shown here — canary is a hold monitor signal and lives on Page 04 only.")
else:
    st.info("No constituent data — check stock data loading in Home page.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Group Summary
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 4 — Group Summary",
                  "Banking · Heavyweight · IT — structural state at a glance")

banking = sig.get("constituent_banking", {})
heavy   = sig.get("constituent_heavyweight", {})
it_d    = sig.get("constituent_it", {})

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**Banking Group** — HDFC, ICICI, Axis, Kotak")
    st.write(f"All bullish: {'✅ Yes' if banking.get('all_bullish') else '❌ No'}")
    st.write(f"Any bear: {'⚠️ Yes' if banking.get('any_bear') else '✅ No'}")
    st.write(f"Bear count: {banking.get('count_bear', 0)} of 4")
    st.write(f"Slope weakening: {'⚠️ Yes' if banking.get('weakening') else 'No'}")
    st.write(f"Avg put moats: {banking.get('avg_put_moats', 0):.1f}")

with col2:
    st.markdown("**Heavyweight Group** — HDFC, Reliance, ICICI")
    st.write(f"Bear count: {heavy.get('count_bear', 0)} of 3")
    st.write(f"Collapse active: {'🔴 Yes' if heavy.get('any_collapse') else '✅ No'}")
    h_regimes = heavy.get("regimes", [])
    if h_regimes:
        st.write(f"Regimes: {', '.join(h_regimes)}")

with col3:
    st.markdown("**IT Group** — Infosys, TCS")
    st.write(f"Both bear: {'⚠️ Yes' if it_d.get('both_bear') else '✅ No'}")
    it_regimes = it_d.get("regimes", [])
    if it_regimes:
        st.write(f"Regimes: {', '.join(it_regimes)}")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Breadth Moat Score
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 5 — Breadth Moat Score",
                  "How many of top 10 stocks have 2+ downside moats — structural health of the index")

b_pct    = breadth.get("score_pct", 50)
b_label  = breadth.get("label", "ADEQUATE")
b_count  = breadth.get("count_2plus", 5)
b_pe_mod = sig.get("constituent_pe_mod_breadth", 0)

ui.simple_technical(
    f"{b_count} of 10 top stocks have 2 or more downside moats ({b_pct}%). "
    f"Breadth label: {b_label}. PE modifier from breadth: {b_pe_mod:+} pts.",
    "BROAD_HEALTH (≥80%) = −50 pts PE bonus\n"
    "ADEQUATE (60-79%) = +0 pts\n"
    "THINNING (40-59%) = +100 pts PE\n"
    "COLLAPSE (<40%) = +200 pts PE"
)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Constituent PE/CE Modifier Summary
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 6 — Constituent Modifier Summary",
                  "Named signal + breadth combined → final IC distance adjustment")

pe_named  = sig.get("constituent_pe_mod_named", 0)
pe_bread  = sig.get("constituent_pe_mod_breadth", 0)
pe_total  = sig.get("constituent_pe_mod", 0)
ce_total  = sig.get("constituent_ce_mod", 0)

# Identify active named signal
active_signal = "None active"
if sig.get("BANKING_DAILY_COLLAPSE"):   active_signal = "BANKING_DAILY_COLLAPSE (KILL SWITCH)"
elif sig.get("HEAVYWEIGHT_COLLAPSE"):   active_signal = "HEAVYWEIGHT_COLLAPSE (+150 pts)"
elif sig.get("INDEX_MASKING_WEAKNESS"): active_signal = "INDEX_MASKING_WEAKNESS (+150 pts)"
elif sig.get("HEAVYWEIGHT_LEADING_DOWN"): active_signal = "HEAVYWEIGHT_LEADING_DOWN (+100 pts)"
elif sig.get("BANKING_SLOPE_WEAKENING"): active_signal = "BANKING_SLOPE_WEAKENING (+100 pts)"
elif sig.get("BANKING_ALL_BULLISH"):    active_signal = "BANKING_ALL_BULLISH (−100 pts bonus)"


rows_mod = [
    ["Active named signal",         active_signal,               "Most severe wins — no stacking"],
    ["Named signal PE modifier",     f"{pe_named:+} pts",         "Raw before cap"],
    ["Breadth PE modifier",          f"{pe_bread:+} pts",         f"Breadth label: {b_label}"],
    ["Combined PE (before cap)",     f"{pe_named + pe_bread:+} pts", "Named + breadth"],
    ["PE cap applied",               "+200 / −100 pts",           "Hard cap — constituents inform, not dominate"],
    ["Final constituent PE modifier",f"{pe_total:+} pts",         "This is added to EMA lens output"],
    ["Final constituent CE modifier",f"{ce_total:+} pts",         "IT drag only — capped at +100 pts"],
]
df_mod = pd.DataFrame(rows_mod, columns=["Item", "Value", "Note"])
st.dataframe(df_mod, width="stretch", hide_index=True)
