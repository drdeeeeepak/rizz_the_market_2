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

        _df  = get_nifty_daily_live()
        _vix = get_india_vix()
        _atr = sig.get("atr14", 200)

        if not _df.empty:
            # 2H / 4H from 1H resample
            try:
                _df_1h = get_nifty_1h_phase()
                _df_2h = resample_ohlcv(_df_1h, "2h") if not _df_1h.empty else pd.DataFrame()
                _df_4h = resample_ohlcv(_df_1h, "4h") if not _df_1h.empty else pd.DataFrame()
            except Exception:
                _df_2h = _df_4h = pd.DataFrame()

            # 1W from daily — guarded for tz and duplicates
            _df_1w = pd.DataFrame()
            try:
                _tmp = _df.copy()
                if not isinstance(_tmp.index, pd.DatetimeIndex):
                    _tmp.index = pd.to_datetime(_tmp.index)
                if getattr(_tmp.index, "tz", None) is not None:
                    _tmp.index = _tmp.index.tz_localize(None)
                _tmp = _tmp[~_tmp.index.duplicated(keep="last")]
                _df_1w = _tmp.resample("W-FRI").agg(
                    {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
                ).dropna(subset=["open","close"])
            except Exception:
                pass

            _bb = BollingerOptionsEngine().signals(_df_2h, _df_4h, _df, _df_1w, atr14=_atr)

            sig = {**sig, **{f"bb_{k}": v for k, v in _bb.items()}}
            sig["bb_regime"]            = _bb["regime_2h"]
            sig["bw_pct"]               = _bb["bw_2h"]
            sig["bb_squeeze_status"]    = _bb["squeeze_status"]
            sig["bb_asymmetry_signal"]  = _bb["asymmetry_signal"]
            sig["bb_confidence"]        = _bb["confidence"]
            sig["bb_skip_score"]        = _bb["skip_score"]
            sig["bb_skip_conditions"]   = _bb.get("skip_conditions", {})
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
bb_regime   = sig.get("bb_regime",            "CALM")
bw_2h       = sig.get("bb_bw_2h",             sig.get("bw_pct", 5.0))
bw_4h       = sig.get("bb_bw_4h",             5.0)
bw_1d       = sig.get("bb_bw_1d",             5.0)
bw_1w       = sig.get("bb_bw_1w",             7.0)
reg_4h      = sig.get("bb_regime_4h",         "CALM")
reg_1d      = sig.get("bb_regime_1d",         "CALM")
reg_1w      = sig.get("bb_regime_1w",         "CALM")
zone_2h     = sig.get("bb_zone_2h",           "MIDLINE")
zone_4h     = sig.get("bb_zone_4h",           "MIDLINE")
pb_2h       = sig.get("bb_pct_b_2h",          0.5)
pb_4h       = sig.get("bb_pct_b_4h",          0.5)
squeeze     = sig.get("bb_squeeze_status",    "NONE")
asymmetry   = sig.get("bb_asymmetry_signal",  "1:1")
confidence  = sig.get("bb_confidence",        "MEDIUM")
skip_score  = sig.get("bb_skip_score",        0)
skip_conds  = sig.get("bb_skip_conditions",   {})
verdict     = sig.get("bb_entry_verdict",     "PROCEED")
risk_side   = sig.get("bb_primary_risk_side", "NEUTRAL")
drift_risk  = sig.get("bb_drift_risk",        "BASE")
ma_2h       = sig.get("bb_ma_position_2h",   "AT_MA")
ma_4h       = sig.get("bb_ma_position_4h",   "AT_MA")
wu_2h       = sig.get("bb_walk_up_2h",       sig.get("bb_walk_up_count", 0))
wd_2h       = sig.get("bb_walk_down_2h",     sig.get("bb_walk_down_count", 0))
wu_4h       = sig.get("bb_walk_up_4h",       0)
wd_4h       = sig.get("bb_walk_down_4h",     0)
wlbl_2h     = sig.get("bb_walk_label_2h",    "NONE")
wlbl_4h     = sig.get("bb_walk_label_4h",    "NONE")
ce_watch    = sig.get("bb_ce_watch",         False)
pe_watch    = sig.get("bb_pe_watch",         False)
vix_div     = sig.get("bb_vix_divergence",   False)
l4_pe       = sig.get("bb_l4_pe",            0)
l4_ce       = sig.get("bb_l4_ce",            0)
atr14       = sig.get("atr14",               200)

REGIME_COLOUR = {
    "EXTREME_SQUEEZE": "red", "SQUEEZE": "red", "CALM": "green",
    "MOMENTUM": "amber",      "HIGH_VOL": "red", "MEAN_REVERT": "red",
}
VERDICT_COLOUR = {"PROCEED": "green", "CAUTION": "amber", "SKIP": "red"}
CONF_COLOUR    = {"HIGH": "green", "MEDIUM": "amber", "WEAK": "red"}
DRIFT_COLOUR   = {"BASE": "green", "ELEVATED": "amber", "VERY_HIGH": "red", "VETO": "red"}
WALK_COLOUR    = {"STRONG": "red", "MODERATE": "red", "MILD": "amber", "NONE": "green"}
SQ_COLOUR      = {"ALIGNED": "green", "PARTIAL": "amber", "DEEP": "red", "NONE": "default"}

# ── Alert banners ─────────────────────────────────────────────────────────────
if verdict == "SKIP":
    if squeeze == "DEEP":
        st.error("🔴 SKIP — DEEP SQUEEZE. EXTREME_SQUEEZE active on 2H or 4H. Direction unknowable. Do NOT enter.")
    else:
        st.error(f"🔴 SKIP — skip score {skip_score}/5. Multiple structural risk conditions active. Stand aside this week.")
elif verdict == "CAUTION":
    st.warning(f"⚠️ CAUTION — skip score {skip_score}/5. Proceed at 50% lots only.")
else:
    st.success("✅ PROCEED — BB conditions acceptable for full IC entry.")

if squeeze == "ALIGNED":
    st.info("🔵 ALIGNED SQUEEZE — 2H+4H both coiled. Best IC setup of the cycle: IV elevated vs realised vol. Use %B for direction lean.")
elif squeeze == "PARTIAL":
    st.info("🔵 PARTIAL SQUEEZE — 2H squeezed, 4H not yet aligned. Good setup — use %B for direction.")

walk_2h_max = max(wu_2h, wd_2h)
if wlbl_2h == "STRONG":
    _ws = "upper" if wu_2h >= wd_2h else "lower"
    st.error(f"🔴 2H STRONG WALK — Day {walk_2h_max} along {_ws} band. Hard skip regardless of skip score.")
elif wlbl_2h == "MODERATE":
    _ws = "upper" if wu_2h >= wd_2h else "lower"
    st.warning(f"⚠️ 2H MODERATE WALK — Day {walk_2h_max} along {_ws} band. Apply strong asymmetry or skip.")
elif wlbl_2h == "MILD":
    _ws = "upper" if wu_2h >= wd_2h else "lower"
    _leg = "CE" if wu_2h >= wd_2h else "PE"
    st.warning(f"⚠️ 2H MILD WALK — Day {walk_2h_max} along {_ws} band. Lean asymmetry, flag {_leg} leg.")

if vix_div:
    st.warning(f"⚠️ BB-VIX DIVERGENCE — VIX elevated but 2H BW% tight ({bw_2h:.2f}%). Implied vol says danger, realised vol quiet. Treat as extra caution.")

if ce_watch:
    st.info("ℹ️ CE WATCH — 2H %B in UP_NEUTRAL (0.55–0.75). Price drifting toward upper band. Monitor CE leg.")
if pe_watch:
    st.info("ℹ️ PE WATCH — 2H %B in LO_NEUTRAL (0.25–0.45). Price drifting toward lower band. Monitor PE leg.")

st.divider()

# ── Headline metrics ──────────────────────────────────────────────────────────
c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1: ui.metric_card("ENTRY VERDICT", verdict,    sub=f"Skip score {skip_score}/5",        color=VERDICT_COLOUR.get(verdict,"default"))
with c2: ui.metric_card("2H REGIME",    bb_regime,   sub=f"BW% {bw_2h:.2f}% (primary TF)",   color=REGIME_COLOUR.get(bb_regime,"default"))
with c3: ui.metric_card("SQUEEZE",      squeeze,     sub="ALIGNED = best IC setup",           color=SQ_COLOUR.get(squeeze,"default"))
with c4: ui.metric_card("ASYMMETRY",    asymmetry,   sub=f"Primary risk: {risk_side}",        color="amber" if asymmetry != "1:1" else "green")
with c5: ui.metric_card("CONFIDENCE",   confidence,  sub="4H agreement quality",              color=CONF_COLOUR.get(confidence,"default"))
with c6: ui.metric_card("DRIFT RISK",   drift_risk,  sub="CE breach probability level",       color=DRIFT_COLOUR.get(drift_risk,"default"))

st.divider()

# ── 4-TF Regime Overview ──────────────────────────────────────────────────────
ui.section_header("4-TF Regime Overview")
c1, c2, c3, c4 = st.columns(4)
for _col, _label, _bw, _reg, _note in [
    (c1, "2H — PRIMARY",   bw_2h, bb_regime, "Drives asymmetry + lens distance"),
    (c2, "4H — SECONDARY", bw_4h, reg_4h,   "Confidence modifier on ratio"),
    (c3, "1D — BG",        bw_1d, reg_1d,   "Skip score cond 1 if BW% >5.6%"),
    (c4, "1W — MACRO",     bw_1w, reg_1w,   "Skip score conds 2 and 5"),
]:
    with _col:
        ui.metric_card(_label, _reg, sub=f"BW% {_bw:.2f}% · {_note}",
                       color=REGIME_COLOUR.get(_reg, "default"))

with st.expander("Regime Reference — What Each State Means for Your IC", expanded=False):
    st.markdown("""
| Regime | BW% (2H/4H) | IC Meaning | Action |
|---|---|---|---|
| **EXTREME_SQUEEZE** | < 2% | Bands collapsed — explosive move imminent, direction unknown | Hard skip · DEEP squeeze veto |
| **SQUEEZE** | 2–3.5% | Bands coiled — IV elevated vs realised vol, premium-rich setup | Best IC entry if direction known from %B |
| **CALM** | 3.5–4.5% | Bands gently compressed — ideal premium decay environment | Proceed · tight distance (2.0× ATR14) |
| **MOMENTUM** | 4.5–5.6% | Market picking direction — one leg building pressure | Proceed with asymmetry · 2.25× ATR14 |
| **HIGH_VOL** | 5.6–6.5% | Elevated volatility — significant move already in progress | Widen both legs · 2.5× ATR14 |
| **MEAN_REVERT** | > 6.5% | Bands overextended — snap-back risk is high | Skip (adds to skip score) |

**1D thresholds are wider** (SQUEEZE <3.5%, CALM 3.5–5.6%, HIGH_VOL >5.6%) because daily bands compress more slowly.
**1W thresholds are different** (EXTREME_SQ <4.5%, MEAN_REVERT >10.2%) — weekly bands move in a different vol regime.
""")

st.divider()

# ── %B Zone + MA Position ─────────────────────────────────────────────────────
ui.section_header("%B Zone — Position Within the Band", "2H %B drives the asymmetry ratio · 4H %B drives confidence")
c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1: ui.metric_card("2H %B",   f"{pb_2h:.3f}", sub=zone_2h,
                         color="red"   if zone_2h in ("ABOVE_BAND","BELOW_BAND") else
                               "amber" if zone_2h in ("UPPER","LOWER") else "default")
with c2: ui.metric_card("2H ZONE",  zone_2h, sub="Primary ratio driver")
with c3: ui.metric_card("2H MA",    ma_2h,   sub="±0.3% around 2H basis",
                         color="amber" if ma_2h != "AT_MA" else "green")
with c4: ui.metric_card("4H %B",   f"{pb_4h:.3f}", sub=zone_4h,
                         color="red"   if zone_4h in ("ABOVE_BAND","BELOW_BAND") else "default")
with c5: ui.metric_card("4H ZONE",  zone_4h, sub="Confidence modifier")
with c6: ui.metric_card("4H MA",    ma_4h,   sub="±0.3% around 4H basis",
                         color="amber" if ma_4h != "AT_MA" else "green")

with st.expander("%B Zone Reference — How Each Zone Maps to IC Ratio", expanded=False):
    st.markdown("""
%B = (close − lower band) / (upper − lower band). Values outside 0–1 mean close is outside the band.

| Zone | %B Range | Base Ratio | IC Meaning |
|---|---|---|---|
| **ABOVE_BAND** | > 1.0 | **1:2** (CE threatened) | Price above upper band — sustained bullish pressure, CE short at risk |
| **UPPER** | 0.75–1.0 | **1:2** (CE threatened) | Price in upper quartile — approaching upper band, CE needs extra distance |
| **UP_NEUTRAL** | 0.55–0.75 | 1:1 + CE watch | Price drifting up — no asymmetry yet, flag CE leg for monitoring |
| **MIDLINE** | 0.45–0.55 | **1:1** | Price centred on 20-period SMA — ideal symmetric IC |
| **LO_NEUTRAL** | 0.25–0.45 | 1:1 + PE watch | Price drifting down — no asymmetry yet, flag PE leg for monitoring |
| **LOWER** | 0.0–0.25 | **2:1** (PE threatened) | Price in lower quartile — approaching lower band, PE needs extra distance |
| **BELOW_BAND** | < 0.0 | **2:1** (PE threatened) | Price below lower band — sustained bearish pressure, PE short at risk |

**MA override:** if the 2H basis (20-SMA) contradicts the %B direction, the ratio steps to 1:1.
Example: %B = UPPER (→1:2) but price is 0.5% below basis (BELOW_MA) → overrides to 1:1.
Same rule applies if 4H MA contradicts 2H direction.
""")

st.divider()

# ── Asymmetry Formula ─────────────────────────────────────────────────────────
ui.section_header("Asymmetry Formula — Active Computation")
_ZONE_RATIO = {
    "ABOVE_BAND": "1:2 (CE threatened)", "UPPER":      "1:2 (CE threatened)",
    "UP_NEUTRAL": "1:1 + CE watch",      "MIDLINE":    "1:1",
    "LO_NEUTRAL": "1:1 + PE watch",
    "LOWER":      "2:1 (PE threatened)", "BELOW_BAND": "2:1 (PE threatened)",
}
_CONF_DESC = {
    "HIGH":   f"4H confirms 2H direction → full ratio (+{round(0.5*atr14/50)*50:,} pts extra on {risk_side} leg)",
    "MEDIUM": f"4H neutral or MA contradicts → half ratio (+{round(0.25*atr14/50)*50:,} pts extra on {risk_side} leg)",
    "WEAK":   "4H contradicts 2H direction → override to 1:1, no extra distance",
}
_ma_note = ""
if asymmetry == "1:1" and zone_2h in ("ABOVE_BAND","UPPER","LOWER","BELOW_BAND"):
    _ma_note = "  ⚠️ MA override applied — ratio stepped to 1:1 (MA contradicts %B direction)"
ui.simple_technical(
    f"2H %B zone = {zone_2h} → base: {_ZONE_RATIO.get(zone_2h,'1:1')}\n"
    f"Squeeze: {squeeze}" + (" → uses %B value directly for direction" if squeeze in ("ALIGNED","PARTIAL") else "") + "\n"
    f"4H confidence = {confidence} → {_CONF_DESC.get(confidence,'')}\n"
    f"2H MA = {ma_2h}  |  4H MA = {ma_4h}{_ma_note}",
    f"Final asymmetry: {asymmetry}  ·  Primary risk: {risk_side}\n"
    f"Lens L4 → PE {l4_pe:,} pts  |  CE {l4_ce:,} pts  (from {round(_LENS_BASE := 2.0 if bb_regime=='CALM' else 2.25 if bb_regime in ('SQUEEZE','MOMENTUM') else 2.5 if bb_regime=='HIGH_VOL' else 2.75, 2) if False else ''}base {round(2.0 if bb_regime=='CALM' else 2.25 if bb_regime in ('SQUEEZE','MOMENTUM') else 2.5 if bb_regime=='HIGH_VOL' else 2.75, 2)}× ATR14)"
)

with st.expander("Asymmetry & Confidence Reference — Full Rule Table", expanded=False):
    st.markdown(f"""
**Lens L4 base multipliers (ATR14 = {atr14:,} pts):**

| 2H Regime | Base Mult | Base Pts | IC Meaning |
|---|---|---|---|
| EXTREME_SQUEEZE | 2.5× | {round(2.5*atr14/50)*50:,} | Precautionary wide — but verdict is SKIP |
| SQUEEZE | 2.25× | {round(2.25*atr14/50)*50:,} | Standard — direction lean from %B |
| CALM | 2.0× | {round(2.0*atr14/50)*50:,} | Tighter — ideal environment |
| MOMENTUM | 2.25× | {round(2.25*atr14/50)*50:,} | Standard |
| HIGH_VOL | 2.5× | {round(2.5*atr14/50)*50:,} | Wider — vol elevated |
| MEAN_REVERT | 2.75× | {round(2.75*atr14/50)*50:,} | Widest — snap risk |

**Asymmetry extra on threatened leg:**

| Confidence | Extra Mult | Extra Pts | Condition |
|---|---|---|---|
| HIGH | +0.5× ATR14 | +{round(0.5*atr14/50)*50:,} | 4H %B agrees with 2H direction |
| MEDIUM | +0.25× ATR14 | +{round(0.25*atr14/50)*50:,} | 4H neutral, or 4H MA contradicts |
| WEAK | +0.0 | +0 | 4H in opposite directional half → default 1:1 |

**Hard cap:** threatened leg capped at 3.0× ATR14 = {round(3.0*atr14/50)*50:,} pts.

**Squeeze direction rule:** when ALIGNED or PARTIAL, %B value overrides zone name:
- %B > 0.55 → 1:2 (expansion likely upward)
- %B < 0.45 → 2:1 (expansion likely downward)
- %B 0.45–0.55 → 1:1 (direction genuinely unknown — do not force a lean)
""")

st.divider()

# ── Skip Score ────────────────────────────────────────────────────────────────
ui.section_header("Skip Score", f"{skip_score}/5  ·  SKIP ≥3  |  CAUTION =2  |  PROCEED 0–1")

_yes = "background-color:#fee2e2;font-weight:700"
_no  = "background-color:#dcfce7"

_skip_rows = [
    ["1", "1D BW% > 5.6%",
     "YES" if skip_conds.get("1d_high_vol", bw_1d > 5.6)  else "NO",
     f"{bw_1d:.2f}%  ({reg_1d})"],
    ["2", "1W price > 2% below 1W MA",
     "YES" if skip_conds.get("1w_below_ma", False)         else "NO",
     f"1W regime: {reg_1w}"],
    ["3", "4H STRONG walk ≥ 4 days",
     "YES" if skip_conds.get("4h_strong_walk", max(wu_4h,wd_4h)>=4) else "NO",
     f"max {max(wu_4h,wd_4h)} days  ({wlbl_4h})"],
    ["4", "2H regime = MEAN_REVERT",
     "YES" if skip_conds.get("2h_mean_revert", bb_regime=="MEAN_REVERT") else "NO",
     f"{bb_regime}  ({bw_2h:.2f}%)"],
    ["5", "1W BW% > 10.2%",
     "YES" if skip_conds.get("1w_mean_revert", bw_1w > 10.2) else "NO",
     f"{bw_1w:.2f}%  ({reg_1w})"],
]
_skip_df = pd.DataFrame(_skip_rows, columns=["#","Condition","Active","Value"])
st.dataframe(
    _skip_df.style.map(lambda v: _yes if v=="YES" else _no if v=="NO" else "",
                       subset=["Active"]),
    use_container_width=True, hide_index=True,
)
if squeeze == "DEEP":
    st.error("DEEP SQUEEZE is a hard veto — skip score is bypassed.")

with st.expander("Skip Score Reference — Why Each Condition Exists", expanded=False):
    st.markdown("""
Each condition represents a structural risk that materially increases the probability of an IC leg breach during the 5-day hold.

| # | Condition | Rationale |
|---|---|---|
| 1 | **1D BW% > 5.6%** | Daily market already in HIGH_VOL or MEAN_REVERT. The move has happened — entering IC now means selling into momentum with insufficient distance. |
| 2 | **1W price > 2% below 1W MA** | Macro bearish drift — the weekly trend is structurally down. Entry IC is working against the weekly current. PE leg is at elevated structural risk. |
| 3 | **4H STRONG walk ≥ 4 days** | Four consecutive 4H closes outside the band = confirmed trend on the 4H timeframe. IC boundary will be tested. The edge has flipped from IC to directional. |
| 4 | **2H MEAN_REVERT** | 2H BW% > 6.5% means the intraday bands are extremely wide — the explosive move already happened. What follows is a snap-back that is statistically violent in both directions. |
| 5 | **1W BW% > 10.2%** | Weekly bands at macro mean-revert level — implies a major volatility event (budget, election, global shock). IC is structurally unsuited. |

**DEEP SQUEEZE veto** is separate — it fires when 2H or 4H BW% < 2%, making direction genuinely unknowable. Entering an IC before a direction-unknown explosion is asymmetrically punished.

**Score thresholds:** 0–1 = proceed. 2 = caution (50% lots — your theta still works, you reduce P&L variance). ≥3 = skip (multiple conditions failing simultaneously = structurally bad week).
""")

st.divider()

# ── Walk Status ───────────────────────────────────────────────────────────────
ui.section_header("Band Walk Status", "Consecutive closes at or beyond the band on each TF")
c1, c2, c3, c4 = st.columns(4)
with c1: ui.metric_card("2H WALK UP",   f"Day {wu_2h}", sub=wlbl_2h, color=WALK_COLOUR.get(wlbl_2h,"default"))
with c2: ui.metric_card("2H WALK DOWN", f"Day {wd_2h}", sub=wlbl_2h, color=WALK_COLOUR.get(wlbl_2h,"default"))
with c3: ui.metric_card("4H WALK UP",   f"Day {wu_4h}", sub=wlbl_4h, color=WALK_COLOUR.get(wlbl_4h,"default"))
with c4: ui.metric_card("4H WALK DOWN", f"Day {wd_4h}", sub=wlbl_4h, color=WALK_COLOUR.get(wlbl_4h,"default"))

with st.expander("Walk Reference — Rules and IC Implications", expanded=False):
    st.markdown("""
A "walk" is when price closes at or beyond the Bollinger Band for consecutive bars. It signals sustained directional momentum — the IC boundary on that side is being tested repeatedly.

| Days | Label | 2H/4H Action | IC Implication |
|---|---|---|---|
| 1 | *(breach)* | Monitor only — single bar outside band | No action — could be noise |
| 2 | **MILD** | Lean asymmetry + flag threatened leg | Apply 1:2 or 2:1 ratio toward threatened side |
| 3 | **MODERATE** | Strong asymmetry OR skip | If confidence is WEAK, prefer skip. If HIGH, apply max ratio. |
| 4+ | **STRONG** | Hard skip | 4+ days = trend established. IC is the wrong strategy this week. |

**TF scope:**
- **2H walk** → primary actionable signal. Drives asymmetry directly.
- **4H walk STRONG (≥4)** → adds +1 to skip score (condition 3).
- **1D walk** → informational display. A confirmed 1D walk adds context but doesn't independently trigger action.
- **1W walk** → macro veto signal. Treat any 1W walk day ≥2 as structural — combine with 1W BW% and MA position.

**Why the walk modifier is NOT in pts:** the old engine added ATR-scaled pts to the walk leg. The new system instead flows through the skip score (for strong walks) and the asymmetry ratio (for mild/moderate), which is more principled — you're not arbitrarily widening a boundary, you're deciding whether to enter at all and at what ratio.
""")

st.divider()

# ── Drift Risk ────────────────────────────────────────────────────────────────
ui.section_header("CE Breach Drift Risk", "CE short at +3.5% OTM · base breach probability = 1/20 (5%)")
_DRIFT_DESC = {
    "VERY_HIGH": "EXTREME_SQUEEZE or HIGH_VOL regime active — CE breach probability elevated to ~20% (4×). Nifty has statistical capacity for a 3.5%+ intraweek move.",
    "ELEVATED":  "SQUEEZE or MOMENTUM regime — CE breach probability elevated to ~10% (2×). Market picking direction with energy remaining.",
    "BASE":      "CALM regime — CE at +3.5% is at the 95th pctl of weekly drift. Breach probability at historical base rate (~5%).",
    "VETO":      "MEAN_REVERT — bands overextended. A violent snap-back is statistically probable. CE side is exposed to a rapid move back to basis.",
}
ui.alert_box(
    f"Drift Risk: {drift_risk}",
    _DRIFT_DESC.get(drift_risk, ""),
    level="danger" if drift_risk in ("VERY_HIGH","VETO") else "warning" if drift_risk == "ELEVATED" else "success",
)

with st.expander("Drift Risk Reference — Regime → CE Breach Probability", expanded=False):
    st.markdown(f"""
The base CE breach probability is calibrated to your entry: CE short at **+3.5% OTM**, with **95th pctl weekly drift = 3.51%**. This means 1 in 20 weeks the market moves far enough to test the CE strike.

The drift risk modifier adjusts this base rate based on how much structural momentum is present:

| 2H Regime | Risk Level | Approx CE Breach Prob | Reason |
|---|---|---|---|
| CALM | BASE | ~5% (1/20) | No momentum — drift is bounded |
| SQUEEZE | ELEVATED | ~10% (2/20) | Coiled spring — release move can be sharp |
| MOMENTUM | ELEVATED | ~10% (2/20) | Directional energy building |
| EXTREME_SQUEEZE | VERY_HIGH | ~20% (4/20) | Explosion imminent, magnitude unknown |
| HIGH_VOL | VERY_HIGH | ~20% (4/20) | Large move already in progress |
| MEAN_REVERT | VETO | Not modelled | Snap-back dynamics — structural tail risk |

**Note:** drift risk is informational — it tells you the quality of the CE short, not whether to skip. The skip score handles the binary entry decision. Drift risk informs sizing and roll readiness.
""")

st.divider()

# ── Squeeze States ────────────────────────────────────────────────────────────
with st.expander("Squeeze State Reference — ALIGNED / PARTIAL / DEEP / NONE", expanded=False):
    st.markdown("""
Squeeze status combines 2H and 4H BW% to characterise the volatility compression state across timeframes.

| State | Definition | IC Strategy |
|---|---|---|
| **ALIGNED** | 2H in SQUEEZE (2–3.5%) AND 4H in SQUEEZE | **Best IC entry of the cycle.** Both TFs coiled — IV is elevated relative to realised vol. Premium is rich. Use %B value to determine direction lean. Home score = 12/14. |
| **PARTIAL** | 2H in SQUEEZE, 4H not in SQUEEZE | Good setup — 2H has compressed but 4H has not yet confirmed. Confidence will be MEDIUM or WEAK. Proceed but size conservatively. Home score = 10/14. |
| **DEEP** | Either TF in EXTREME_SQUEEZE (<2%) | **Hard skip.** The coil is so tight that any release will be violent. The direction cannot be known from %B. An IC entered here risks a full-leg breach on the first significant move. |
| **NONE** | 2H not in SQUEEZE or EXTREME_SQUEEZE | Standard operation — use %B zone for asymmetry, BW% regime for distance. |

**Why squeeze + %B is the best IC entry setup:** when BW% is compressed, the market has been range-bound long enough that options sellers have bid down IV to match the low realised vol. The IC premium collected is therefore rich relative to the actual statistical move space available. When the bands eventually expand, they return to a wider range — but in the meantime, time decay is fast.
""")

# ── BW% Reference ────────────────────────────────────────────────────────────
with st.expander("BW% Reference Tables — All 4 TFs", expanded=False):
    _ca, _cb = st.columns(2)
    with _ca:
        st.markdown("**2H and 4H thresholds** (same table)")
        st.dataframe(pd.DataFrame([
            ["< 2.0%",    "EXTREME_SQUEEZE", "Hard skip — DEEP squeeze veto"],
            ["2.0–3.5%",  "SQUEEZE",         "Best IC entry if %B gives direction"],
            ["3.5–4.5%",  "CALM",            "Sweet spot — tight distance (2.0× ATR)"],
            ["4.5–5.6%",  "MOMENTUM",        "Directional — apply asymmetry"],
            ["5.6–6.5%",  "HIGH_VOL",        "Widen both legs (2.5× ATR)"],
            ["> 6.5%",    "MEAN_REVERT",     "Skip — adds +1 to skip score"],
        ], columns=["BW%","Regime","IC Rule"]), use_container_width=True, hide_index=True)
    with _cb:
        st.markdown("**1D thresholds** (skip score + display only)")
        st.dataframe(pd.DataFrame([
            ["< 3.5%",    "SQUEEZE",     "—"],
            ["3.5–5.6%",  "CALM",        "—"],
            ["5.6–7.0%",  "MOMENTUM",    "Skip +1 if BW% > 5.6%"],
            ["7.0–9.0%",  "HIGH_VOL",    "Skip +1"],
            ["> 9.0%",    "MEAN_REVERT", "Skip +1"],
        ], columns=["1D BW%","Regime","Skip Score"]), use_container_width=True, hide_index=True)
        st.markdown("**1W thresholds** (macro skip score + display)")
        st.dataframe(pd.DataFrame([
            ["< 4.5%",    "EXTREME_SQ",  "Macro caution"],
            ["4.5–6.5%",  "CALM",        "—"],
            ["6.5–8.0%",  "MOMENTUM",    "—"],
            ["8.0–10.2%", "HIGH_VOL",    "—"],
            ["> 10.2%",   "MEAN_REVERT", "Skip +1 (cond 5)"],
        ], columns=["1W BW%","Regime","Skip Score"]), use_container_width=True, hide_index=True)

# ── Midweek Monitoring ────────────────────────────────────────────────────────
with st.expander("Midweek Monitoring Rules — Post-Entry (4H + 2H)", expanded=False):
    st.markdown(f"""
These rules apply **after Tuesday EOD entry** using live 4H and 2H data. They are informational — they tell you when the IC is being stressed and whether to act. They do not change strikes retrospectively.

| Signal | Condition | Interpretation | Action |
|---|---|---|---|
| CE leg threat | 4H %B > 0.85 | Price deep in upper zone — CE short under daily pressure | Reassess CE distance. Consider defensive roll if sustained. |
| PE leg threat | 4H %B < 0.15 | Price deep in lower zone — PE short under daily pressure | Reassess PE distance. Consider defensive roll if sustained. |
| Vol expansion | 4H BW > 1.5× entry BW in ≤ 2 days | Bands expanding rapidly post-entry — market chose direction | IC width may be insufficient. Size reduction or close weaker leg. |
| Directional pressure | 2H walk_day ≥ 2 | 2H band walk developing after entry | Monitor threatened leg daily. Flag for early exit if walk reaches MODERATE. |
| Ideal decay | 2H + 4H %B both 0.30–0.70 all week | Price oscillating near basis — no directional stress | No action needed. Theta working cleanly. Hold to expiry. |

**Entry BW% baseline:** store the 2H BW% at Tuesday EOD close. The vol expansion alert uses this stored value as the reference. If BW% at entry was {bw_2h:.2f}%, vol expansion triggers if 4H BW% exceeds {bw_2h*1.5:.2f}% within 2 days.
""")
