"""
Pages 29: EMA Momentum Optimization — threshold & weighting scans
Answers:
1. Is 0.6/0.4 weighting optimal? Test variants.
2. Are ±15/±5 thresholds actually best? Scan thresholds.
3. Should TRANSITIONING be 0.0 or weak signal?
4. Add acceleration (slope of slope)?
5. Pure slope vs ATR-scaled?
"""

import streamlit as st
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional

from analytics.ema import EMAEngine
from analytics import signal_lab as sl
from page_utils import format_number, load_signals
from ui.shared import show_page_header, section_header

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG & STATE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MomentumVariant:
    """One EMA momentum signal variant."""
    name: str
    w_ema3: float
    w_ema8: float
    thresh_strong_up: float
    thresh_moderate_up: float
    thresh_moderate_dn: float
    thresh_strong_dn: float
    transitioning_score: float | str
    atr_scale: bool
    accel_weight: float = 0.0

    def __post_init__(self):
        total = self.w_ema3 + self.w_ema8
        if total != 1.0:
            self.w_ema3 /= total
            self.w_ema8 /= total


# ═══════════════════════════════════════════════════════════════════════════════
# EMA MOMENTUM COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════════

def get_transitioning_value(score: float | str) -> float:
    if isinstance(score, float):
        return score
    if score == "weak":
        return 0.25
    if score == "strong":
        return 0.5
    return 0.0


def compute_variant(daily: pd.DataFrame, variant: MomentumVariant) -> pd.Series:
    """Compute signal for one variant."""
    eng = EMAEngine()
    d = daily.copy()
    d.columns = [c.lower() for c in d.columns]
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    d = d.sort_index()

    d = eng.compute(d)
    atr = d["atr14"].replace(0, np.nan)

    ema3_slope = d["ema3"].diff(3) / 3.0
    ema8_slope = d["ema8"].diff(3) / 3.0

    if variant.atr_scale:
        ema3_scaled = (ema3_slope / atr * 100)
        ema8_scaled = (ema8_slope / atr * 100)
    else:
        ema3_scaled = ema3_slope
        ema8_scaled = ema8_slope

    combined = ema3_scaled * variant.w_ema3 + ema8_scaled * variant.w_ema8

    if variant.accel_weight > 0:
        ema3_accel = ema3_slope.diff(3) / 3.0
        ema8_accel = ema8_slope.diff(3) / 3.0
        if variant.atr_scale:
            ema3_accel = (ema3_accel / atr * 100)
            ema8_accel = (ema8_accel / atr * 100)
        accel_combined = ema3_accel * variant.w_ema3 + ema8_accel * variant.w_ema8
        combined = combined * (1 - variant.accel_weight) + accel_combined * variant.accel_weight

    state = pd.Series("FLAT", index=d.index)
    state[combined > variant.thresh_strong_up] = "STRONG_UP"
    state[(combined > variant.thresh_moderate_up) & (combined <= variant.thresh_strong_up)] = "MODERATE_UP"
    state[combined < variant.thresh_strong_dn] = "STRONG_DOWN"
    state[(combined < variant.thresh_moderate_dn) & (combined >= variant.thresh_strong_dn)] = "MODERATE_DOWN"

    transitioning = (ema3_slope > 0) != (ema8_slope > 0)
    trans_val = get_transitioning_value(variant.transitioning_score)
    if trans_val == 0.0:
        state[transitioning] = "FLAT"
    else:
        state[transitioning] = "TRANSITIONING"

    sign_map = {
        "STRONG_UP": 1.0, "MODERATE_UP": 0.5, "FLAT": 0.0,
        "MODERATE_DOWN": -0.5, "STRONG_DOWN": -1.0,
        "TRANSITIONING": 0.0,
    }
    sig = state.map(sign_map).astype(float)

    if trans_val != 0.0:
        sig[state == "TRANSITIONING"] = trans_val * np.sign(ema3_slope[state == "TRANSITIONING"])

    sig.index = pd.to_datetime(sig.index).normalize()
    sig.name = variant.name
    return sig


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE UI
# ═══════════════════════════════════════════════════════════════════════════════

show_page_header("EMA Momentum Optimizer", "xp7rd2", """
Test different EMA momentum configurations (weighting, thresholds, transitioning handling, acceleration)
against forward price outcomes. Current config: 51.5% hit rate, -0.088% expectancy (slightly negative).
""")

# Tab layout
tab_analysis, tab_scanner, tab_explain = st.tabs(["📊 Analysis", "🔧 Threshold Scanner", "❓ Questions"])

with tab_analysis:
    section_header("Current Configuration Analysis")

    col1, col2 = st.columns([1.5, 1])
    with col1:
        st.markdown("""
        #### Current State
        - **Hit Rate**: 51.5% (target: >52%)
        - **Expectancy**: -0.088% (target: +positive)
        - **Weighting**: EMA3=0.6, EMA8=0.4 (favors faster EMA)
        - **Thresholds**: STRONG=±15, MODERATE=±5 (% ATR/day)
        - **Transitioning**: Mapped to 0.0 (no opinion)
        - **Scaling**: ATR14 normalized
        - **Acceleration**: Not included

        #### Questions to Answer
        1. Should weighting be dynamic (regime-based)?
        2. Are these thresholds actually optimal?
        3. Is TRANSITIONING really 0.0, or a weak signal?
        4. Does acceleration help trend confirmation?
        5. Does ATR scaling make sense, or pure slope better?
        """)

    with col2:
        st.markdown("""
        #### Opportunity
        Slight negative edge suggests:
        - Thresholds may be too loose
        - Weighting may not match current regimes
        - TRANSITIONING loses valuable info

        #### Test Strategy
        - Grid scan thresholds ±12→±20
        - Test weighting variants
        - TRANS: 0.0 vs weak vs strong
        - Add 10-25% acceleration weight
        - Compare pure slope vs ATR-scaled
        """)

    st.divider()

    section_header("Expected Improvements")
    st.markdown("""
    | Change | Hypothesis | Expected Impact |
    |--------|-----------|-----------------|
    | Tighter thresholds (±12/±3) | Fewer false signals | +0.1% to +0.3% expectancy |
    | 0.5/0.5 weighting | Better balance between fast/slow | Varies by regime |
    | TRANS = weak (±0.25) | Use information instead of ignoring | +0.05% to +0.15% expectancy |
    | +10% acceleration | Confirm trend continuation | +0.05% to +0.1% expectancy |
    | Pure slope (no ATR) | Regime-independent; may clip high-vol days | TBD |
    """)

with tab_scanner:
    section_header("Manual Threshold Scanner")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        w_ema3 = st.slider("EMA3 Weight", 0.3, 0.8, 0.6, step=0.05)
        w_ema8 = 1.0 - w_ema3
        st.caption(f"EMA8: {w_ema8:.2f}")

    with col2:
        thresh_strong_up = st.slider("STRONG_UP threshold", 8.0, 25.0, 15.0, step=1.0)
        thresh_strong_dn = -thresh_strong_up

    with col3:
        thresh_moderate_up = st.slider("MODERATE_UP threshold", 1.0, 10.0, 5.0, step=0.5)
        thresh_moderate_dn = -thresh_moderate_up

    with col4:
        trans_mode = st.selectbox("TRANSITIONING", ["0.0 (no opinion)", "weak (±0.25)", "strong (±0.5)"])
        trans_val = {"0.0 (no opinion)": 0.0, "weak (±0.25)": "weak", "strong (±0.5)": "strong"}[trans_mode]

    accel = st.checkbox("Add acceleration component (10%)?", value=False)
    atr_scaled = st.checkbox("ATR-scale slopes?", value=True)

    if st.button("Test This Configuration", type="primary"):
        with st.spinner("Computing signal and evaluating..."):
            try:
                # Get daily data
                from data.live_fetcher import get_nifty_daily
                daily = get_nifty_daily(days=400)
                if daily.empty:
                    st.error("Could not fetch daily data")
                else:
                    variant = MomentumVariant(
                        name="Custom Variant",
                        w_ema3=w_ema3,
                        w_ema8=w_ema8,
                        thresh_strong_up=thresh_strong_up,
                        thresh_moderate_up=thresh_moderate_up,
                        thresh_moderate_dn=thresh_moderate_dn,
                        thresh_strong_dn=thresh_strong_dn,
                        transitioning_score=trans_val,
                        atr_scale=atr_scaled,
                        accel_weight=0.1 if accel else 0.0,
                    )

                    sig = compute_variant(daily, variant)
                    result = sl.evaluate_signal(daily, sig, name=variant.name, horizons=(5, 10))

                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Hit Rate %", f"{result['hit_rate']:.1f}%",
                                delta=f"{result['hit_rate'] - 51.5:+.1f}pp" if result['hit_rate'] else None)
                    with col2:
                        st.metric("Expectancy %", f"{result['expectancy']:+.3f}%",
                                delta=f"{result['expectancy'] - (-0.088):+.3f}pp" if result['expectancy'] else None)
                    with col3:
                        st.metric("Spearman ρ", f"{result['spearman']:+.3f}" if result['spearman'] else "NaN")
                    with col4:
                        st.metric("n_active", result['n_active'], f"of {result['n']}")

                    # Bucket analysis
                    if not result['bucket'].empty:
                        st.subheader("Quantile Bucket Analysis")
                        st.dataframe(result['bucket'].round(3), use_container_width=True)

            except Exception as e:
                st.error(f"Error: {e}")

with tab_explain:
    section_header("Why These Questions Matter")

    st.markdown("""
    #### 1. Weighting: 0.6/0.4 vs Dynamic

    **Current**: EMA3 (3-bar) gets 60%, EMA8 (8-bar) gets 40%.

    **Hypothesis**: In strong trends, fast EMA dominates. In consolidations, slower EMA matters more.

    **Test**: 0.5/0.5 equal weighting, or regime-dependent weighting.

    ---

    #### 2. Threshold Optimization: ±15/±5

    **Current**: Need 15% ATR/day for STRONG, 5% for MODERATE (thresholds are absolute, not scaled).

    **Observation**: 51.5% hit rate = barely above coin-flip. Thresholds may be:
    - Too loose: false signals on small moves
    - Not regime-specific: same thresholds for high-vol and low-vol

    **Test**: Scan ±12→±20 for STRONG, ±3→±8 for MODERATE.

    ---

    #### 3. TRANSITIONING = 0.0 vs Weak Signal

    **Current**: When EMA3 and EMA8 slopes disagree (one up, one down) → signal = 0.0

    **Why it's wrong**: Disagreement ≠ No opinion. It's a weakly bullish or bearish state.
    - EMA3 > 0 AND EMA8 < 0 → price is decelerating but still up → weak bullish
    - EMA3 < 0 AND EMA8 > 0 → price falling, but momentum reversing → weak bearish

    **Test**: Treat as weak signal (±0.25) or strong (±0.5) instead of 0.0.

    ---

    #### 4. Acceleration Component

    **Idea**: Second derivative = rate of change of slope.
    - High positive acceleration = momentum strengthening = confirm long trades
    - Negative acceleration = momentum fading = reduce confidence

    **Test**: 10-25% weight on acceleration in combined signal.

    ---

    #### 5. ATR Scaling vs Pure Slope

    **Current**: Scale slopes by ATR14 (volatility-relative).
    - Pro: Handles high-vol days without threshold tweaking
    - Con: Very quiet days inflate thresholds relative to actual move

    **Alternative**: Pure slope (raw 3-bar change per point).
    - Pro: Regime-independent; you see real price change
    - Con: Need separate thresholds per volatility regime

    **Test**: Pure slope with adjusted thresholds vs ATR-scaled.
    """)
