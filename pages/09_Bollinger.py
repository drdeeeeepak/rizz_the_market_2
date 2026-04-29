# pages/09_Bollinger.py — Page 09: Bollinger Bands Framework
# ATR-scaled walk modifier · 5 regimes · BB-VIX divergence · Band breach
import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P09 · Bollinger Bands", layout="wide")
st_autorefresh(interval=60_000, key="p09")
st.title("Page 09 — Bollinger Bands Framework")
st.caption("Volatility state · Band regime · Walk detection · ATR-scaled modifiers · Independent modifier")

# ── Bootstrap: works without Home page ───────────────────────────────────────
from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)
if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

bb_regime = sig.get("bb_regime", sig.get("bb_bb_regime", "NEUTRAL_WALK"))
bw_pct    = sig.get("bw_pct",    sig.get("bb_bw_pct", 6.0))
walk_up   = sig.get("bb_walk_up_count", 0)
walk_down = sig.get("bb_walk_down_count", 0)
atr14     = sig.get("atr14", 200)
kills     = sig.get("bb_kill_switches", sig.get("kill_switches", {}))
put_mod   = sig.get("bb_distance_put", 0)
call_mod  = sig.get("bb_distance_call", 0)

# ── Alert banners ─────────────────────────────────────────────────────────────
if bb_regime == "SQUEEZE":
    st.error("🔴 SQUEEZE — BW% <3.5%. Coiled spring. Do NOT enter new IC positions.")
elif bb_regime == "WALK_UPPER":
    st.warning(f"⚠️ WALK_UPPER — Day {walk_up} of walk. CE leg under sustained pressure. Walk modifier: +{call_mod:,} pts CE.")
elif bb_regime == "WALK_LOWER":
    st.warning(f"⚠️ WALK_LOWER — Day {walk_down} of walk. PE leg under sustained pressure. Walk modifier: +{put_mod:,} pts PE.")
elif bb_regime == "MEAN_REVERT":
    st.success("✅ MEAN_REVERT — BW% >10%. Bands overextended. Mean reversion likely. -100 pts both sides bonus.")
if sig.get("bb_vix_divergence"):
    st.warning(f"⚠️ BB-VIX DIVERGENCE — BW% <4.5% but VIX elevated. Realised vs implied disagree. +{round(0.5*atr14/50)*50:,} pts both sides.")
if kills.get("BAND_BREACH") or kills.get("K1"):
    st.info(f"ℹ️ BAND_BREACH — Single close outside band (Days 1-2). +{round(0.5*atr14/50)*50:,} pts both sides as precaution.")

st.divider()

# ── Headline metrics ──────────────────────────────────────────────────────────
REGIME_COLOURS = {
    "SQUEEZE": "red", "WALK_UPPER": "red", "WALK_LOWER": "red",
    "NEUTRAL_WALK": "green", "MEAN_REVERT": "amber",
}
c1,c2,c3,c4,c5,c6 = st.columns(6)
with c1: ui.metric_card("REGIME", bb_regime, color=REGIME_COLOURS.get(bb_regime,"default"))
with c2: ui.metric_card("BW%", f"{bw_pct:.2f}%",
                          sub="<3.5 Squeeze | 4-7 Normal | >10 MR",
                          color="red" if bw_pct < 3.5 else "green" if 4 <= bw_pct <= 7 else "amber")
with c3: ui.metric_card("WALK UP DAYS", str(walk_up), sub="≥3 = WALK_UPPER active",
                          color="red" if walk_up >= 3 else "default")
with c4: ui.metric_card("WALK DOWN DAYS", str(walk_down), sub="≥3 = WALK_LOWER active",
                          color="red" if walk_down >= 3 else "default")
with c5: ui.metric_card("BB PUT MOD", f"{put_mod:+,} pts", sub="ATR-scaled walk modifier",
                          color="red" if put_mod > 0 else "green" if put_mod < 0 else "default")
with c6: ui.metric_card("BB CALL MOD", f"{call_mod:+,} pts", sub="ATR-scaled walk modifier",
                          color="red" if call_mod > 0 else "green" if call_mod < 0 else "default")

st.divider()

# ── Regime explanations ───────────────────────────────────────────────────────
ui.section_header("Band Regime — What It Means For Your IC")
REGIME_DESC = {
    "SQUEEZE":     ("Bands extremely narrow. Coiled spring — explosive move building. Direction unknown. Do not enter.", "danger"),
    "WALK_UPPER":  ("Market walking along upper band — sustained upside breakout. CE leg under daily pressure. ATR-scaled modifier applied to CE only.", "warning"),
    "WALK_LOWER":  ("Market walking along lower band — sustained downside breakout. PE leg under daily pressure. ATR-scaled modifier applied to PE only.", "warning"),
    "NEUTRAL_WALK":("Market inside bands oscillating near basis. IC-friendly. Premium decays cleanly. No BB modifier.", "success"),
    "MEAN_REVERT": ("Bands very wide — explosive move already happened. Mean reversion back to basis statistically likely. Mild -100 pts tightening bonus.", "info"),
}
desc, level = REGIME_DESC.get(bb_regime, ("Normal conditions", "info"))
ui.alert_box(f"Current: {bb_regime}", desc, level=level)

st.divider()

# ── ATR-scaled walk modifier detail ──────────────────────────────────────────
ui.section_header("ATR-Scaled Walk Modifier",
                  "Age-adjusted — largest on Day 3, reduces as walk ages and mean reversion risk builds")

ui.simple_technical(
    "The walk modifier is largest when a walk is freshly confirmed (Day 3) — the threat has maximum forward energy. As the walk ages, the market becomes statistically overdue for mean reversion. By Day 6+, you are actually positioned well for the snap back — you need less extra distance, not more.",
    f"Day 3: 1.5 × ATR14 ({round(1.5*atr14):,} pts)\nDay 4-5: 1.0 × ATR14 ({round(1.0*atr14):,} pts)\nDay 6+: 0.5 × ATR14 ({round(0.5*atr14):,} pts)\nCap: 2.0 × ATR14 ({round(2.0*atr14):,} pts)\nFloor: 100 pts\nRounded to nearest 50 pts"
)
st.markdown("")

if bb_regime in ("WALK_UPPER", "WALK_LOWER"):
    walk_age = walk_up if bb_regime == "WALK_UPPER" else walk_down
    if walk_age == 3:   mult, desc_w = 1.5, "Maximum threat — walk freshly confirmed"
    elif walk_age <= 5: mult, desc_w = 1.0, "Momentum present but mean reversion building"
    else:               mult, desc_w = 0.5, "Walk extended — mean reversion statistically overdue"

    raw    = mult * atr14
    capped = min(raw, 2.0 * atr14)
    final  = max(capped, 100)
    rounded= round(final / 50) * 50

    c1, c2, c3, c4 = st.columns(4)
    with c1: ui.metric_card("WALK AGE", f"Day {walk_age}", sub=desc_w, color="red" if walk_age <= 3 else "amber")
    with c2: ui.metric_card("MULTIPLIER", f"{mult}× ATR14", sub=f"= {round(raw):,} pts raw")
    with c3: ui.metric_card("AFTER CAP/FLOOR", f"{rounded:,} pts", sub="Rounded to 50 pts")
    with c4: ui.metric_card("APPLIED TO", "CE only" if bb_regime=="WALK_UPPER" else "PE only", sub="Other leg gets 0 from BB")
else:
    st.info("No walk active — walk modifier is 0 for both sides.")

st.divider()

# ── BW% reference ────────────────────────────────────────────────────────────
with st.expander("BandWidth Reference Table", expanded=False):
    import pandas as pd
    rows = [
        ["Below 3.5%",  "SQUEEZE",     "Dangerous — skip entry or widen both sides"],
        ["3.5% to 4%",  "Resolving",   "Caution — watch for walk direction developing"],
        ["4% to 7%",    "NEUTRAL_WALK","Ideal IC environment — premium decays cleanly"],
        ["7% to 10%",   "Elevated",    "Monitor walk conditions — check daily closes vs bands"],
        ["Above 10%",   "MEAN_REVERT", "Bands very wide — mean reversion bonus -100 pts both"],
    ]
    df_ref = pd.DataFrame(rows, columns=["BW%","State","IC Implication"])
    def hl_bw(val):
        if "3.5%" in str(val) and bw_pct < 3.5: return "background-color:#fee2e2;font-weight:700"
        if "4% to 7%" in str(val) and 4 <= bw_pct <= 7: return "background-color:#dcfce7;font-weight:700"
        if "10%" in str(val) and bw_pct > 10: return "background-color:#fef3c7;font-weight:700"
        return ""
    st.dataframe(df_ref.style.map(hl_bw, subset=["BW%"]), use_container_width=True, hide_index=True)
