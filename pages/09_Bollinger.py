# pages/09_Bollinger.py — Page 09: Bollinger Bands Framework v4 MTF
# TF hierarchy: 2H=PRIMARY | 4H=SECONDARY | 1D=BG | 1W=MACRO
import streamlit as st
import pandas as pd
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P09 · Bollinger Bands", layout="wide")
st_autorefresh(interval=60_000, key="p09")
st.title("Page 09 — Bollinger Bands Framework")
st.caption("2H=PRIMARY · 4H=SECONDARY · 1D=BG · 1W=MACRO | Asymmetric IC: CE +3.5% / PE −4%")

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
        from data.live_fetcher import get_nifty_daily_live, get_india_vix, get_nifty_1h_phase
        from analytics.bollinger import BollingerOptionsEngine
        from analytics.supertrend import resample_ohlcv
        from config import BB_VIX_DIV_VIX, BB_VIX_DIV_BW

        _df   = get_nifty_daily_live()
        _vix  = get_india_vix()
        _atr  = sig.get("atr14", 200)

        if not _df.empty:
            _df_1h = get_nifty_1h_phase()
            _df_2h = resample_ohlcv(_df_1h, "2h") if not _df_1h.empty else pd.DataFrame()
            _df_4h = resample_ohlcv(_df_1h, "4h") if not _df_1h.empty else pd.DataFrame()

            _tmp = _df.copy()
            if not isinstance(_tmp.index, pd.DatetimeIndex):
                _tmp.index = pd.to_datetime(_tmp.index)
            _df_1w = _tmp.resample("W-FRI").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
            ).dropna(subset=["open", "close"])

            _bb = BollingerOptionsEngine().signals(_df_2h, _df_4h, _df, _df_1w, atr14=_atr)

            sig = {**sig, **{f"bb_{k}": v for k, v in _bb.items()}}
            sig["bb_regime"]            = _bb["regime_2h"]
            sig["bw_pct"]               = _bb["bw_2h"]
            sig["bb_squeeze_status"]    = _bb["squeeze_status"]
            sig["bb_asymmetry_signal"]  = _bb["asymmetry_signal"]
            sig["bb_confidence"]        = _bb["confidence"]
            sig["bb_skip_score"]        = _bb["skip_score"]
            sig["bb_entry_verdict"]     = _bb["entry_verdict"]
            sig["bb_primary_risk_side"] = _bb["primary_risk_side"]
            sig["bb_drift_risk"]        = _bb["drift_risk"]
            sig["bb_l4_pe"]             = _bb["l4_pe"]
            sig["bb_l4_ce"]             = _bb["l4_ce"]
            sig["bb_walk_up_count"]     = _bb.get("walk_up_2h", 0)
            sig["bb_walk_down_count"]   = _bb.get("walk_down_2h", 0)
            sig["bb_kill_switches"]     = _bb.get("kill_switches", {})
            sig["bb_vix_divergence"]    = _vix > BB_VIX_DIV_VIX and _bb["bw_2h"] < BB_VIX_DIV_BW
            signals_ts = "LIVE"
    except Exception as _e:
        st.caption(f"Live Bollinger unavailable: {_e}")

# ── Read all signals ──────────────────────────────────────────────────────────
bb_regime  = sig.get("bb_regime",           "CALM")
bw_2h      = sig.get("bb_bw_2h",            sig.get("bw_pct", 5.0))
bw_4h      = sig.get("bb_bw_4h",            5.0)
bw_1d      = sig.get("bb_bw_1d",            5.0)
bw_1w      = sig.get("bb_bw_1w",            7.0)
reg_4h     = sig.get("bb_regime_4h",        "CALM")
reg_1d     = sig.get("bb_regime_1d",        "CALM")
reg_1w     = sig.get("bb_regime_1w",        "CALM")
zone_2h    = sig.get("bb_zone_2h",          "MIDLINE")
zone_4h    = sig.get("bb_zone_4h",          "MIDLINE")
pb_2h      = sig.get("bb_pct_b_2h",         0.5)
pb_4h      = sig.get("bb_pct_b_4h",         0.5)
squeeze    = sig.get("bb_squeeze_status",   "NONE")
asymmetry  = sig.get("bb_asymmetry_signal", "1:1")
confidence = sig.get("bb_confidence",       "MEDIUM")
skip_score = sig.get("bb_skip_score",       0)
verdict    = sig.get("bb_entry_verdict",    "PROCEED")
risk_side  = sig.get("bb_primary_risk_side","NEUTRAL")
drift_risk = sig.get("bb_drift_risk",       "BASE")
ma_2h      = sig.get("bb_ma_position_2h",  "AT_MA")
ma_4h      = sig.get("bb_ma_position_4h",  "AT_MA")
wu_2h      = sig.get("bb_walk_up_2h",      sig.get("bb_walk_up_count", 0))
wd_2h      = sig.get("bb_walk_down_2h",    sig.get("bb_walk_down_count", 0))
wu_4h      = sig.get("bb_walk_up_4h",      0)
wd_4h      = sig.get("bb_walk_down_4h",    0)
wlbl_2h    = sig.get("bb_walk_label_2h",   "NONE")
wlbl_4h    = sig.get("bb_walk_label_4h",   "NONE")
ce_watch   = sig.get("bb_ce_watch",        False)
pe_watch   = sig.get("bb_pe_watch",        False)
vix_div    = sig.get("bb_vix_divergence",  False)
l4_pe      = sig.get("bb_l4_pe",           0)
l4_ce      = sig.get("bb_l4_ce",           0)
atr14      = sig.get("atr14",              200)

# ── Alert banners ─────────────────────────────────────────────────────────────
if verdict == "SKIP":
    if squeeze == "DEEP":
        st.error("🔴 SKIP — DEEP SQUEEZE (EXTREME_SQUEEZE on 2H or 4H). Direction unknowable. Do NOT enter.")
    elif skip_score >= 3:
        st.error(f"🔴 SKIP — skip score {skip_score}/5. Multiple risk conditions active. Stand aside.")
elif verdict == "CAUTION":
    st.warning(f"⚠️ CAUTION — skip score {skip_score}/5. Enter at 50% lots only.")
else:
    st.success("✅ PROCEED — conditions acceptable for IC entry.")

if squeeze == "ALIGNED":
    st.info("🔵 ALIGNED SQUEEZE — 2H+4H both coiled. Best IC setup: IV elevated vs realised vol. Direction from %B.")
elif squeeze == "PARTIAL":
    st.info("🔵 PARTIAL SQUEEZE — 2H squeezed, 4H not yet aligned. Monitor for confirmation.")

if wlbl_2h == "STRONG":
    side = "upper" if wu_2h > wd_2h else "lower"
    st.error(f"🔴 2H STRONG WALK — Day {max(wu_2h,wd_2h)} along {side} band. Hard skip.")
elif wlbl_2h == "MODERATE":
    side = "upper" if wu_2h > wd_2h else "lower"
    st.warning(f"⚠️ 2H MODERATE WALK — Day {max(wu_2h,wd_2h)} along {side} band. Strong asymmetry or skip.")
elif wlbl_2h == "MILD":
    side = "upper" if wu_2h > wd_2h else "lower"
    st.warning(f"⚠️ 2H MILD WALK — Day {max(wu_2h,wd_2h)} along {side} band. Lean ratio + flag {'CE' if wu_2h>wd_2h else 'PE'}.")

if vix_div:
    st.warning(f"⚠️ BB-VIX DIVERGENCE — VIX elevated but 2H BW% tight ({bw_2h:.2f}%). Implied vs realised disagree.")

if ce_watch:
    st.info("ℹ️ CE WATCH — 2H %B in UP_NEUTRAL. Price drifting toward upper band. Monitor CE leg.")
if pe_watch:
    st.info("ℹ️ PE WATCH — 2H %B in LO_NEUTRAL. Price drifting toward lower band. Monitor PE leg.")

st.divider()

# ── Headline metrics ──────────────────────────────────────────────────────────
VERDICT_COLOUR = {"PROCEED": "green", "CAUTION": "amber", "SKIP": "red"}
CONF_COLOUR    = {"HIGH": "green",    "MEDIUM":  "amber", "WEAK": "red"}
DRIFT_COLOUR   = {"BASE": "green", "ELEVATED": "amber", "VERY_HIGH": "red", "VETO": "red"}
REGIME_COLOUR  = {
    "EXTREME_SQUEEZE": "red",  "SQUEEZE": "red",    "CALM": "green",
    "MOMENTUM": "amber",       "HIGH_VOL": "red",   "MEAN_REVERT": "red",
}

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1: ui.metric_card("ENTRY VERDICT", verdict, sub=f"Skip score {skip_score}/5",
                         color=VERDICT_COLOUR.get(verdict, "default"))
with c2: ui.metric_card("2H REGIME",    bb_regime, sub=f"BW% {bw_2h:.2f}%",
                         color=REGIME_COLOUR.get(bb_regime, "default"))
with c3: ui.metric_card("SQUEEZE",      squeeze, sub="ALIGNED=best IC entry",
                         color="green" if squeeze == "ALIGNED" else "red" if squeeze == "DEEP" else "amber" if squeeze == "PARTIAL" else "default")
with c4: ui.metric_card("ASYMMETRY",   asymmetry, sub=f"Risk side: {risk_side}",
                         color="amber" if asymmetry != "1:1" else "green")
with c5: ui.metric_card("CONFIDENCE",  confidence, sub="4H alignment quality",
                         color=CONF_COLOUR.get(confidence, "default"))
with c6: ui.metric_card("DRIFT RISK",  drift_risk, sub="CE breach risk level",
                         color=DRIFT_COLOUR.get(drift_risk, "default"))

st.divider()

# ── 4-TF Overview ────────────────────────────────────────────────────────────
ui.section_header("4-TF Regime Overview")
c1, c2, c3, c4 = st.columns(4)
for col, label, bw, regime, note in [
    (c1, "2H (PRIMARY)",   bw_2h, bb_regime, "Drives asymmetry + strikes"),
    (c2, "4H (SECONDARY)", bw_4h, reg_4h,   "Confidence modifier"),
    (c3, "1D (BG)",        bw_1d, reg_1d,   "Skip score cond 1 if >5.6%"),
    (c4, "1W (MACRO)",     bw_1w, reg_1w,   "Skip score conds 2+5"),
]:
    with col:
        ui.metric_card(label, regime, sub=f"BW% {bw:.2f}% · {note}",
                       color=REGIME_COLOUR.get(regime, "default"))

st.divider()

# ── %B Position ──────────────────────────────────────────────────────────────
ui.section_header("%B Zone — Position within Band", "2H drives asymmetry | 4H drives confidence")
c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1: ui.metric_card("2H %B",  f"{pb_2h:.3f}", sub=zone_2h,
                         color="red" if zone_2h in ("ABOVE_BAND","BELOW_BAND") else
                               "amber" if zone_2h in ("UPPER","LOWER") else "default")
with c2: ui.metric_card("2H ZONE", zone_2h, sub="Primary asymmetry driver")
with c3: ui.metric_card("2H MA",   ma_2h,   sub="±0.3% basis band",
                         color="amber" if ma_2h != "AT_MA" else "green")
with c4: ui.metric_card("4H %B",  f"{pb_4h:.3f}", sub=zone_4h,
                         color="red" if zone_4h in ("ABOVE_BAND","BELOW_BAND") else "default")
with c5: ui.metric_card("4H ZONE", zone_4h, sub="Confidence modifier")
with c6: ui.metric_card("4H MA",   ma_4h,   sub="±0.3% basis band",
                         color="amber" if ma_4h != "AT_MA" else "green")

st.divider()

# ── Asymmetry Formula ─────────────────────────────────────────────────────────
ui.section_header("Asymmetry Formula")
ZONE_RATIO = {
    "ABOVE_BAND": "1:2 (CE threatened)",  "UPPER":      "1:2 (CE threatened)",
    "UP_NEUTRAL": "1:1 + CE watch",       "MIDLINE":    "1:1",
    "LO_NEUTRAL": "1:1 + PE watch",
    "LOWER":      "2:1 (PE threatened)",  "BELOW_BAND": "2:1 (PE threatened)",
}
CONF_DESC = {
    "HIGH":   "4H agrees with 2H direction → apply full ratio (50% extra on threatened leg)",
    "MEDIUM": "4H neutral/contradicting MA → apply half ratio (25% extra)",
    "WEAK":   "4H contradicts 2H direction → default 1:1",
}
ui.simple_technical(
    f"2H %B zone = {zone_2h} → base ratio: {ZONE_RATIO.get(zone_2h, '1:1')}\n"
    f"4H confidence = {confidence} → {CONF_DESC.get(confidence, '')}\n"
    f"MA modifier: 2H={ma_2h}, 4H={ma_4h}"
    + (" → ratio stepped to 1:1 (MA contradiction)" if (
        (asymmetry == "1:1" and zone_2h in ("ABOVE_BAND","UPPER","LOWER","BELOW_BAND"))
    ) else ""),
    f"Final asymmetry: {asymmetry}\nPrimary risk leg: {risk_side}\n"
    f"Lens L4: PE {l4_pe:,} pts | CE {l4_ce:,} pts"
)

st.divider()

# ── Skip Score Breakdown ──────────────────────────────────────────────────────
ui.section_header("Skip Score", f"{skip_score}/5 — {'SKIP ≥3 | CAUTION =2 | PROCEED 0-1'}")

_skip_rows = [
    ["1D BW% > 5.6%",         "YES" if bw_1d > 5.6 else "NO",           f"{bw_1d:.2f}%"],
    ["1W price >2% below MA", "YES" if sig.get("bb_bw_1w",0)>0 and False else "—",      "see 1W regime"],
    ["4H STRONG walk (≥4d)",  "YES" if max(wu_4h,wd_4h) >= 4 else "NO", f"max {max(wu_4h,wd_4h)} days"],
    ["2H MEAN_REVERT",        "YES" if bb_regime == "MEAN_REVERT" else "NO", bb_regime],
    ["1W BW% > 10.2%",        "YES" if bw_1w > 10.2 else "NO",          f"{bw_1w:.2f}%"],
]
_skip_df = pd.DataFrame(_skip_rows, columns=["Condition","Active","Value"])

def _hl_skip(val):
    if val == "YES": return "background-color:#fee2e2;font-weight:700"
    if val == "NO":  return "background-color:#dcfce7"
    return ""

st.dataframe(_skip_df.style.map(_hl_skip, subset=["Active"]), use_container_width=True, hide_index=True)

st.divider()

# ── Walk Status ───────────────────────────────────────────────────────────────
ui.section_header("Band Walk Status")
WALK_COLOUR = {"STRONG": "red", "MODERATE": "red", "MILD": "amber", "NONE": "green"}
c1, c2, c3, c4 = st.columns(4)
with c1: ui.metric_card("2H WALK UP",   f"Day {wu_2h}",   sub=wlbl_2h, color=WALK_COLOUR.get(wlbl_2h,"default"))
with c2: ui.metric_card("2H WALK DOWN", f"Day {wd_2h}",   sub=wlbl_2h, color=WALK_COLOUR.get(wlbl_2h,"default"))
with c3: ui.metric_card("4H WALK UP",   f"Day {wu_4h}",   sub=wlbl_4h, color=WALK_COLOUR.get(wlbl_4h,"default"))
with c4: ui.metric_card("4H WALK DOWN", f"Day {wd_4h}",   sub=wlbl_4h, color=WALK_COLOUR.get(wlbl_4h,"default"))

ui.simple_technical(
    "Walk thresholds: Day 2=MILD (lean+flag) | Day 3=MODERATE (strong asymmetry or skip) | Day 4+=STRONG (hard skip)",
    "2H+4H walks are actionable. 1D walk adds to skip score. 1W walk = macro veto."
)

st.divider()

# ── Drift Risk ────────────────────────────────────────────────────────────────
ui.section_header("CE Breach Drift Risk", "Base CE breach risk = 1/20 (5%) at entry CE +3.5%")
DRIFT_DESC = {
    "VERY_HIGH": "EXTREME_SQUEEZE or HIGH_VOL → +2 risk levels (~20% CE breach probability)",
    "ELEVATED":  "SQUEEZE or MOMENTUM → +1 risk level (~10% CE breach probability)",
    "BASE":      "CALM regime → base rate (5% CE breach probability)",
    "VETO":      "MEAN_REVERT → bands overextended, snap risk. Skip or treat as SKIP.",
}
ui.alert_box(
    f"Drift Risk: {drift_risk}",
    DRIFT_DESC.get(drift_risk, ""),
    level="danger" if drift_risk in ("VERY_HIGH","VETO") else "warning" if drift_risk == "ELEVATED" else "success",
)

st.divider()

# ── BW% Reference Tables ──────────────────────────────────────────────────────
with st.expander("BW% Regime Reference — All 4 TFs", expanded=False):
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**2H / 4H thresholds**")
        st.dataframe(pd.DataFrame([
            ["<2.0%",     "EXTREME_SQUEEZE", "Hard skip — direction unknowable"],
            ["2.0–3.5%",  "SQUEEZE",         "Coiled — use %B for direction lean"],
            ["3.5–4.5%",  "CALM",            "IC sweet spot — bands compressed"],
            ["4.5–5.6%",  "MOMENTUM",        "Directional picking up — one leg at risk"],
            ["5.6–6.5%",  "HIGH_VOL",        "Elevated — widen both sides"],
            [">6.5%",     "MEAN_REVERT",     "Bands wide — skip (skip score +1)"],
        ], columns=["BW%","Regime","IC Implication"]), use_container_width=True, hide_index=True)
    with col_b:
        st.markdown("**1D thresholds** (display + skip score) / **1W thresholds** (macro)")
        st.dataframe(pd.DataFrame([
            ["1D <3.5%",     "SQUEEZE",         "—"],
            ["1D 3.5–5.6%",  "CALM",            "—"],
            ["1D 5.6–7.0%",  "MOMENTUM",        "—"],
            ["1D 7.0–9.0%",  "HIGH_VOL",        "Skip score +1 if >5.6%"],
            ["1D >9.0%",     "MEAN_REVERT",     "Skip score +1"],
            ["1W <4.5%",     "EXTREME_SQUEEZE", "Macro caution"],
            ["1W 4.5–6.5%",  "CALM",            "—"],
            ["1W 6.5–8.0%",  "MOMENTUM",        "—"],
            ["1W 8.0–10.2%", "HIGH_VOL",        "—"],
            ["1W >10.2%",    "MEAN_REVERT",     "Skip score +1"],
        ], columns=["TF + BW%","Regime","Skip Score"]), use_container_width=True, hide_index=True)

# ── Midweek Monitoring ────────────────────────────────────────────────────────
with st.expander("Midweek Monitoring Rules (post-entry, 4H+2H)", expanded=False):
    st.markdown("""
| Signal | Condition | Action |
|---|---|---|
| CE leg threat | 4H %B > 0.85 | Reassess CE distance — may need defensive roll |
| PE leg threat | 4H %B < 0.15 | Reassess PE distance — may need defensive roll |
| Vol expansion | 4H BW > 1.5× entry BW within 2 days | Alert — IC width may be insufficient |
| Directional pressure | 2H walk_day ≥ 2 | Monitor threatened leg daily |
| Ideal decay | 2H+4H %B both 0.30–0.70 all week | No action needed — premium decaying cleanly |
""")
