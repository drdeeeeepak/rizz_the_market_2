"""
Pages 29: EMA Momentum Optimization — Batch Testing of Parameter Combinations

Workflow:
1. Select 5 pre-defined combinations from dropdown
2. Click "Run Batch Backtest"
3. Code tests all 5, generates results CSV
4. Download CSV
5. Repeat until all 12 combos tested
6. Share CSVs back for comparison analysis
"""

import streamlit as st
import numpy as np
import pandas as pd
import csv
import io
from dataclasses import dataclass
from typing import Optional

from analytics.ema import EMAEngine
from analytics import signal_lab as sl
from ui.components import section_header

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
# PRE-DEFINED COMBINATIONS FOR BATCH TESTING
# ═══════════════════════════════════════════════════════════════════════════════

MOMENTUM_COMBOS = {
    "01_Baseline": MomentumVariant(
        name="01_Baseline (Current Prod)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=15, thresh_moderate_up=5, thresh_moderate_dn=-5, thresh_strong_dn=-15,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "02_Tight_v1": MomentumVariant(
        name="02_Tight v1 (±12/±4)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=12, thresh_moderate_up=4, thresh_moderate_dn=-4, thresh_strong_dn=-12,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "03_Tight_v2": MomentumVariant(
        name="03_Tight v2 (±13/±4)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=13, thresh_moderate_up=4, thresh_moderate_dn=-4, thresh_strong_dn=-13,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "04_Tight_Equal": MomentumVariant(
        name="04_Tight + Equal (0.5/0.5, ±12/±4)", w_ema3=0.5, w_ema8=0.5,
        thresh_strong_up=12, thresh_moderate_up=4, thresh_moderate_dn=-4, thresh_strong_dn=-12,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "05_Tight_WeakTrans": MomentumVariant(
        name="05_Tight + Weak Trans (±12/±4, TRANS=weak)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=12, thresh_moderate_up=4, thresh_moderate_dn=-4, thresh_strong_dn=-12,
        transitioning_score="weak", atr_scale=True, accel_weight=0.0
    ),
    "06_Tight_Accel": MomentumVariant(
        name="06_Tight + Accel (±12/±4, +10% accel)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=12, thresh_moderate_up=4, thresh_moderate_dn=-4, thresh_strong_dn=-12,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.1
    ),
    "07_Moderate": MomentumVariant(
        name="07_Moderate (±14/±5)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=14, thresh_moderate_up=5, thresh_moderate_dn=-5, thresh_strong_dn=-14,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "08_EqualWeight": MomentumVariant(
        name="08_Equal Weight (0.5/0.5, ±15/±5)", w_ema3=0.5, w_ema8=0.5,
        thresh_strong_up=15, thresh_moderate_up=5, thresh_moderate_dn=-5, thresh_strong_dn=-15,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "09_WeakTrans": MomentumVariant(
        name="09_Weak Trans Only (±15/±5, TRANS=weak)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=15, thresh_moderate_up=5, thresh_moderate_dn=-5, thresh_strong_dn=-15,
        transitioning_score="weak", atr_scale=True, accel_weight=0.0
    ),
    "10_Loose": MomentumVariant(
        name="10_Loose (±18/±6)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=18, thresh_moderate_up=6, thresh_moderate_dn=-6, thresh_strong_dn=-18,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "11_Loose_Accel": MomentumVariant(
        name="11_Loose + Accel (±18/±6, +10% accel)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=18, thresh_moderate_up=6, thresh_moderate_dn=-6, thresh_strong_dn=-18,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.1
    ),
    "12_AllOptimized": MomentumVariant(
        name="12_All Optimized (±12/±4, 0.6/0.4, weak, +10% accel)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=12, thresh_moderate_up=4, thresh_moderate_dn=-4, thresh_strong_dn=-12,
        transitioning_score="weak", atr_scale=True, accel_weight=0.1
    ),
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # NEW BATCH: Testing EMA period variants & stronger acceleration
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    "13_UltraTight": MomentumVariant(
        name="13_Ultra-Tight (±10/±3)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=10, thresh_moderate_up=3, thresh_moderate_dn=-3, thresh_strong_dn=-10,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "14_UltraTight_WeakTrans": MomentumVariant(
        name="14_Ultra-Tight + Weak Trans (±10/±3, TRANS=weak)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=10, thresh_moderate_up=3, thresh_moderate_dn=-3, thresh_strong_dn=-10,
        transitioning_score="weak", atr_scale=True, accel_weight=0.0
    ),
    "15_Aggressive_Accel": MomentumVariant(
        name="15_Aggressive Accel (±12/±4, +20% accel, weak TRANS)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=12, thresh_moderate_up=4, thresh_moderate_dn=-4, thresh_strong_dn=-12,
        transitioning_score="weak", atr_scale=True, accel_weight=0.2
    ),
}


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

st.title("EMA Momentum Optimizer 🎯")
st.markdown("""
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
    section_header("Batch Backtest: Select 5 Combinations")

    st.markdown("""
    **How it works:**
    1. Select 5 combinations from the list below
    2. Click "Run Batch Backtest"
    3. Code tests all 5 on 400 days of data
    4. Download CSV with results
    5. Repeat batches until all 12 combinations tested
    """)

    # Multi-select for combos
    combo_names = list(MOMENTUM_COMBOS.keys())
    combo_labels = [MOMENTUM_COMBOS[k].name for k in combo_names]
    selected_combos = st.multiselect(
        "Select combinations to test (max 5 at a time):",
        options=combo_names,
        format_func=lambda x: MOMENTUM_COMBOS[x].name,
        max_selections=5,
        help="Pick 5 combos, run backtest, download CSV. Repeat for remaining combos."
    )

    if st.button("🚀 Run Batch Backtest", type="primary"):
        if not selected_combos:
            st.error("Please select at least 1 combination")
        else:
            with st.spinner(f"Backtesting {len(selected_combos)} combinations..."):
                try:
                    from data.live_fetcher import get_nifty_daily
                    daily = get_nifty_daily(days=400)

                    if daily.empty:
                        st.error("Could not fetch daily data")
                    else:
                        results_list = []

                        for combo_key in selected_combos:
                            variant = MOMENTUM_COMBOS[combo_key]
                            sig = compute_variant(daily, variant)
                            result = sl.evaluate_signal(daily, sig, name=variant.name, horizons=(5, 10))

                            results_list.append({
                                "Combo": variant.name,
                                "Hit_Rate_%": f"{result['hit_rate']:.1f}" if result['hit_rate'] else "NaN",
                                "Expectancy_%": f"{result['expectancy']:.4f}" if result['expectancy'] else "NaN",
                                "Spearman_rho": f"{result['spearman']:.4f}" if result['spearman'] else "NaN",
                                "n_active": result['n_active'],
                                "n_total": result['n'],
                            })

                        results_df = pd.DataFrame(results_list)
                        st.success(f"✓ Backtest complete for {len(selected_combos)} combos")

                        # Display results table
                        st.subheader("Results")
                        st.dataframe(results_df, use_container_width=True)

                        # CSV download
                        csv_buffer = io.StringIO()
                        results_df.to_csv(csv_buffer, index=False)
                        csv_data = csv_buffer.getvalue()

                        st.download_button(
                            label="📥 Download Results CSV",
                            data=csv_data,
                            file_name=f"momentum_backtest_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv"
                        )

                        st.info("💡 **Next steps:** Download CSV, save it. Repeat with next batch of combos. Once all done, share all CSVs back.")

                except Exception as e:
                    st.error(f"Error: {e}")
                    import traceback
                    st.write(traceback.format_exc())

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
