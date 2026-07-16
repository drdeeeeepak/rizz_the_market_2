"""
Pages 30: Fade Strategy Optimizer — Batch Testing of Mean-Reversion Combos

FADE THESIS: Extreme EMA momentum (overbought/oversold) reverts.
  STRONG_UP momentum (15+ %ATR/day) → expect snap-down → FADE = SHORT (-1.0)
  STRONG_DOWN momentum (-15 %ATR/day) → expect snap-up → FADE = LONG (+1.0)

Workflow: Select 5 fade combinations, batch test, download CSV results.
"""

import streamlit as st
import numpy as np
import pandas as pd
import io
from dataclasses import dataclass

from analytics.ema import EMAEngine
from analytics import signal_lab as sl
from analytics.signal_adapters_fade import adapt_ema_momentum_fade
from ui.components import section_header

# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class FadeConfig:
    """Fade strategy configuration — mirrors momentum but flipped."""
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

    def to_dict(self) -> dict:
        return {
            "w_ema3": self.w_ema3,
            "w_ema8": self.w_ema8,
            "thresh_strong_up": self.thresh_strong_up,
            "thresh_moderate_up": self.thresh_moderate_up,
            "thresh_moderate_dn": self.thresh_moderate_dn,
            "thresh_strong_dn": self.thresh_strong_dn,
            "transitioning_score": self.transitioning_score,
            "atr_scale": self.atr_scale,
            "accel_weight": self.accel_weight,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PRE-DEFINED FADE COMBINATIONS FOR BATCH TESTING
# ═══════════════════════════════════════════════════════════════════════════════

FADE_COMBOS = {
    "01_Baseline": FadeConfig(
        name="01_Baseline Fade (±15/±5, 0.6/0.4)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=15, thresh_moderate_up=5, thresh_moderate_dn=-5, thresh_strong_dn=-15,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "02_Tight_v1": FadeConfig(
        name="02_Tight Fade v1 (±18/±6)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=18, thresh_moderate_up=6, thresh_moderate_dn=-6, thresh_strong_dn=-18,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "03_Tight_v2": FadeConfig(
        name="03_Tight Fade v2 (±20/±7)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=20, thresh_moderate_up=7, thresh_moderate_dn=-7, thresh_strong_dn=-20,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "04_Tight_Equal": FadeConfig(
        name="04_Tight + Equal (0.5/0.5, ±18/±6)", w_ema3=0.5, w_ema8=0.5,
        thresh_strong_up=18, thresh_moderate_up=6, thresh_moderate_dn=-6, thresh_strong_dn=-18,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "05_Tight_WeakTrans": FadeConfig(
        name="05_Tight + Weak Trans (±18/±6, TRANS=weak)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=18, thresh_moderate_up=6, thresh_moderate_dn=-6, thresh_strong_dn=-18,
        transitioning_score="weak", atr_scale=True, accel_weight=0.0
    ),
    "06_Tight_Accel": FadeConfig(
        name="06_Tight + Accel (±18/±6, +10% accel)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=18, thresh_moderate_up=6, thresh_moderate_dn=-6, thresh_strong_dn=-18,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.1
    ),
    "07_Medium": FadeConfig(
        name="07_Medium (±16/±5)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=16, thresh_moderate_up=5, thresh_moderate_dn=-5, thresh_strong_dn=-16,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "08_EqualWeight": FadeConfig(
        name="08_Equal Weight (0.5/0.5, ±15/±5)", w_ema3=0.5, w_ema8=0.5,
        thresh_strong_up=15, thresh_moderate_up=5, thresh_moderate_dn=-5, thresh_strong_dn=-15,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "09_WeakTrans": FadeConfig(
        name="09_Weak Trans Only (±15/±5, TRANS=weak)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=15, thresh_moderate_up=5, thresh_moderate_dn=-5, thresh_strong_dn=-15,
        transitioning_score="weak", atr_scale=True, accel_weight=0.0
    ),
    "10_Loose": FadeConfig(
        name="10_Loose (±12/±4, reverse tight)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=12, thresh_moderate_up=4, thresh_moderate_dn=-4, thresh_strong_dn=-12,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.0
    ),
    "11_Loose_Accel": FadeConfig(
        name="11_Loose + Accel (±12/±4, +10% accel)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=12, thresh_moderate_up=4, thresh_moderate_dn=-4, thresh_strong_dn=-12,
        transitioning_score=0.0, atr_scale=True, accel_weight=0.1
    ),
    "12_AllOptimized": FadeConfig(
        name="12_All Optimized (±20/±7, weak trans, +10% accel)", w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=20, thresh_moderate_up=7, thresh_moderate_dn=-7, thresh_strong_dn=-20,
        transitioning_score="weak", atr_scale=True, accel_weight=0.1
    ),
}


def compute_fade_signal(daily: pd.DataFrame, config: FadeConfig) -> pd.Series:
    """Compute fade signal using adapter."""
    return adapt_ema_momentum_fade(daily, **config.to_dict())


def compute_momentum_signal(daily: pd.DataFrame, config: FadeConfig) -> pd.Series:
    """Compute momentum signal (same config, opposite interpretation)."""
    from analytics.signal_adapters import adapt_ema_momentum as adapt_mom

    # Build a dummy signal using same weights/thresholds but momentum interpretation
    # For now, call the original with fixed config
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

    if config.atr_scale:
        ema3_scaled = (ema3_slope / atr * 100)
        ema8_scaled = (ema8_slope / atr * 100)
    else:
        ema3_scaled = ema3_slope
        ema8_scaled = ema8_slope

    combined = ema3_scaled * config.w_ema3 + ema8_scaled * config.w_ema8

    state = pd.Series("FLAT", index=d.index)
    state[combined > config.thresh_strong_up] = "STRONG_UP"
    state[(combined > config.thresh_moderate_up) & (combined <= config.thresh_strong_up)] = "MODERATE_UP"
    state[combined < config.thresh_strong_dn] = "STRONG_DOWN"
    state[(combined < config.thresh_moderate_dn) & (combined >= config.thresh_strong_dn)] = "MODERATE_DOWN"

    # MOMENTUM MAP: same direction as signal
    mom_map = {
        "STRONG_UP":     +1.0,
        "MODERATE_UP":   +0.5,
        "FLAT":           0.0,
        "MODERATE_DOWN": -0.5,
        "STRONG_DOWN":   -1.0,
    }
    sig = state.map(mom_map).astype(float)
    sig.index = pd.to_datetime(sig.index).normalize()
    sig.name = "ema_momentum"
    return sig


# ═══════════════════════════════════════════════════════════════════════════════

st.title("Fade Strategy Optimizer 📉")
st.markdown("""
Mean-reversion complement to momentum. Fade extreme EMA momentum for snap-back trades.
Compare: momentum (trend-following) vs fade (mean-reversion) — which regime is active?
""")

tab_compare, tab_fade_config, tab_combo, tab_explain = st.tabs(
    ["📊 Momentum vs Fade", "🔧 Fade Tuner", "⚗️ Combo Analysis", "❓ Why Fade?"]
)

with tab_compare:
    section_header("Momentum vs Fade: Head-to-Head")

    st.markdown("""
    **Same EMA momentum signal, opposite interpretation:**

    | Metric | Momentum (Trend-Follow) | Fade (Mean-Reversion) |
    |--------|---|---|
    | STRONG_UP signal | BUY (+1.0) | SHORT (-1.0) |
    | STRONG_DOWN signal | SELL (-1.0) | LONG (+1.0) |
    | Works best in | Strong trends | Consolidation/range |
    | Hurt by | Reversals, whipsaws | Trend continuation |
    | Hit rate target | >52% | ? (TBD) |
    | Expectancy target | >+0% | ? (TBD) |
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Current Momentum Config")
        st.markdown("""
        - **Weighting**: 0.6 EMA3 / 0.4 EMA8
        - **Thresholds**: STRONG ±15, MODERATE ±5
        - **Transitioning**: 0.0 (no opinion)
        - **Scaling**: ATR-normalized
        - **Hit Rate**: 51.5% (baseline)
        - **Expectancy**: -0.088% (slightly negative)
        """)

    with col2:
        st.subheader("Fade Hypothesis")
        st.markdown("""
        **Expected**: Fade should work better when:
        - Price swings are sharp (high volatility)
        - Momentum extremes reverse quickly
        - Market is mean-reverting (not trending)

        **Risk**: Will underperform if:
        - Trends are strong (early part faded, then whipsawed)
        - Consolidation is tight (few extreme readings)
        """)

    if st.button("Compare Live on Latest Data", key="compare_live"):
        with st.spinner("Fetching data and computing both signals..."):
            try:
                from data.live_fetcher import get_nifty_daily
                daily = get_nifty_daily(days=400)
                if daily.empty:
                    st.error("Could not fetch data")
                else:
                    config = FadeConfig(
                        name="Production Config",
                        w_ema3=0.6, w_ema8=0.4,
                        thresh_strong_up=15.0, thresh_moderate_up=5.0,
                        thresh_moderate_dn=-5.0, thresh_strong_dn=-15.0,
                        transitioning_score=0.0,
                        atr_scale=True,
                    )

                    mom_sig = compute_momentum_signal(daily, config)
                    fade_sig = compute_fade_signal(daily, config)

                    mom_result = sl.evaluate_signal(daily, mom_sig, name="Momentum", horizons=(5, 10))
                    fade_result = sl.evaluate_signal(daily, fade_sig, name="Fade", horizons=(5, 10))

                    comp_cols = st.columns(4)
                    with comp_cols[0]:
                        st.metric("Momentum HR%", f"{mom_result['hit_rate']:.1f}%",
                                 delta=f"{mom_result['hit_rate'] - 50.0:.1f}pp vs coin")
                    with comp_cols[1]:
                        st.metric("Fade HR%", f"{fade_result['hit_rate']:.1f}%",
                                 delta=f"{fade_result['hit_rate'] - 50.0:.1f}pp vs coin")
                    with comp_cols[2]:
                        st.metric("Momentum EXP%", f"{mom_result['expectancy']:+.3f}%")
                    with comp_cols[3]:
                        st.metric("Fade EXP%", f"{fade_result['expectancy']:+.3f}%")

                    # Detailed comparison
                    st.divider()
                    st.subheader("Detailed Scorecard")
                    comp_df = pd.DataFrame({
                        "Metric": ["Hit Rate %", "Expectancy %", "Spearman ρ", "n_active"],
                        "Momentum": [
                            f"{mom_result['hit_rate']:.1f}",
                            f"{mom_result['expectancy']:+.3f}",
                            f"{mom_result['spearman']:+.3f}" if mom_result['spearman'] else "NaN",
                            mom_result['n_active'],
                        ],
                        "Fade": [
                            f"{fade_result['hit_rate']:.1f}",
                            f"{fade_result['expectancy']:+.3f}",
                            f"{fade_result['spearman']:+.3f}" if fade_result['spearman'] else "NaN",
                            fade_result['n_active'],
                        ],
                    })
                    st.dataframe(comp_df, use_container_width=True)

                    # Bucket breakdown for both
                    st.subheader("Momentum: Quantile Buckets (5-day horizon)")
                    if not mom_result['bucket'].empty:
                        st.dataframe(mom_result['bucket'].round(3), use_container_width=True)

                    st.subheader("Fade: Quantile Buckets (5-day horizon)")
                    if not fade_result['bucket'].empty:
                        st.dataframe(fade_result['bucket'].round(3), use_container_width=True)

            except Exception as e:
                st.error(f"Error: {e}")

with tab_fade_config:
    section_header("Batch Backtest: Select 5 Fade Combinations")

    st.markdown("""
    **How it works:**
    1. Select 5 fade combinations from the list
    2. Click "Run Batch Backtest"
    3. Code tests all 5 on 400 days of data
    4. Download CSV with results
    5. Repeat batches until all 12 combinations tested

    **Note**: Fade thresholds are typically LOOSER than momentum (to only fade biggest extremes).
    """)

    # Multi-select for combos
    combo_names = list(FADE_COMBOS.keys())
    combo_labels = [FADE_COMBOS[k].name for k in combo_names]
    selected_combos = st.multiselect(
        "Select fade combinations to test (max 5 at a time):",
        options=combo_names,
        format_func=lambda x: FADE_COMBOS[x].name,
        max_selections=5,
        key="fade_combo_select",
        help="Pick 5 combos, run backtest, download CSV. Repeat for remaining combos."
    )

    if st.button("🚀 Run Batch Backtest (Fade)", type="primary", key="run_fade_batch"):
        if not selected_combos:
            st.error("Please select at least 1 fade combination")
        else:
            with st.spinner(f"Backtesting {len(selected_combos)} fade combinations..."):
                try:
                    from data.live_fetcher import get_nifty_daily
                    daily = get_nifty_daily(days=400)

                    if daily.empty:
                        st.error("Could not fetch daily data")
                    else:
                        results_list = []

                        for combo_key in selected_combos:
                            config = FADE_COMBOS[combo_key]
                            sig = compute_fade_signal(daily, config)
                            result = sl.evaluate_signal(daily, sig, name=config.name, horizons=(5, 10))

                            results_list.append({
                                "Combo": config.name,
                                "Hit_Rate_%": f"{result['hit_rate']:.1f}" if result['hit_rate'] else "NaN",
                                "Expectancy_%": f"{result['expectancy']:.4f}" if result['expectancy'] else "NaN",
                                "Spearman_rho": f"{result['spearman']:.4f}" if result['spearman'] else "NaN",
                                "n_active": result['n_active'],
                                "n_total": result['n'],
                            })

                        results_df = pd.DataFrame(results_list)
                        st.success(f"✓ Backtest complete for {len(selected_combos)} fade combos")

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
                            file_name=f"fade_backtest_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv",
                            key="fade_csv_download"
                        )

                        st.info("💡 **Next steps:** Download CSV, save it. Repeat with next batch of combos. Once all done, share all CSVs back.")

                except Exception as e:
                    st.error(f"Error: {e}")
                    import traceback
                    st.write(traceback.format_exc())

with tab_combo:
    section_header("Combo: Momentum + Fade (Ensemble)")

    st.markdown("""
    **Hypothesis**: Combine both signals for a more robust edge.

    Options:
    1. **Average**: (momentum + fade) / 2
       - Hedge each other; neutral when both disagree
       - Reduced edge but more stable

    2. **Voting**: Use whichever has higher confidence
       - STRONG_UP momentum beats fade
       - STRONG_DOWN momentum beats fade
       - FLAT/MODERATE → check fade signal

    3. **Regime-switch**: Use momentum in trending markets, fade in range-bound
       - Adaptive: switch based on ATR, volatility regime
       - Complex but highest theoretical edge

    4. **Separate positions**: Allocate separately
       - 50% momentum, 50% fade
       - Diversify, hedge tail risk
    """)

    combo_mode = st.radio(
        "Combination Method:",
        ["Average Both Signals", "Voting (Confidence-Based)", "Regime Switch", "Separate Allocations"],
        key="combo_mode"
    )

    if st.button("Test Combo", key="test_combo"):
        with st.spinner("Computing combo signal..."):
            try:
                from data.live_fetcher import get_nifty_daily
                daily = get_nifty_daily(days=400)
                if daily.empty:
                    st.error("Could not fetch data")
                else:
                    config = FadeConfig(
                        name="Base",
                        w_ema3=0.6, w_ema8=0.4,
                        thresh_strong_up=15.0, thresh_moderate_up=5.0,
                        thresh_moderate_dn=-5.0, thresh_strong_dn=-15.0,
                        transitioning_score=0.0,
                        atr_scale=True,
                    )

                    mom_sig = compute_momentum_signal(daily, config)
                    fade_sig = compute_fade_signal(daily, config)

                    if combo_mode == "Average Both Signals":
                        combo_sig = (mom_sig + fade_sig) / 2.0
                        combo_name = "Combo: Average (MOM+FADE)/2"
                    elif combo_mode == "Voting (Confidence-Based)":
                        # STRONG beats WEAK, STRONG beats FADE
                        combo_sig = mom_sig.copy()
                        weak_mom = (mom_sig.abs() < 0.75)
                        combo_sig[weak_mom] = fade_sig[weak_mom]
                        combo_name = "Combo: Voting (confidence)"
                    elif combo_mode == "Regime Switch":
                        # Switch based on ATR regime (high vol → fade, low vol → momentum)
                        eng = EMAEngine()
                        d = daily.copy()
                        d.columns = [c.lower() for c in d.columns]
                        d.index = pd.to_datetime(d.index)
                        d = eng.compute(d)
                        atr_ma = d["atr14"].rolling(20).mean()
                        high_vol = d["atr14"] > atr_ma
                        combo_sig = mom_sig.copy()
                        combo_sig[high_vol] = fade_sig[high_vol]
                        combo_name = "Combo: Regime-Switch (ATR)"
                    else:  # Separate
                        combo_sig = (mom_sig + fade_sig) / 2.0
                        combo_name = "Combo: 50/50 Allocation"

                    result = sl.evaluate_signal(daily, combo_sig, name=combo_name, horizons=(5, 10))

                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Hit Rate %", f"{result['hit_rate']:.1f}%")
                    with col2:
                        st.metric("Expectancy %", f"{result['expectancy']:+.3f}%")
                    with col3:
                        st.metric("Spearman ρ", f"{result['spearman']:+.3f}" if result['spearman'] else "NaN")
                    with col4:
                        st.metric("n_active", result['n_active'], f"of {result['n']}")

            except Exception as e:
                st.error(f"Error: {e}")

with tab_explain:
    section_header("Why Fade the Momentum Signal?")

    st.markdown("""
    #### Thesis: Extremes Revert

    **Observation**: When EMA3/EMA8 momentum is EXTREME (±15 %ATR/day), price has usually
    moved a lot already. Mean-reversion theory says it's now ripe for snap-back.

    **Example 1: STRONG UP momentum**
    ```
    Day 1: Price +300 pts (up 1.5%), EMA3 slope +2.5 pts/bar
    Momentum = (2.5 / ATR) × 100 = +18 (STRONG_UP)

    Next days: Big up move exhausts buyers
    → Price consolidates or pulls back
    → Fade signal = SHORT (-1.0)
    → You catch the reversion
    ```

    **Example 2: STRONG DOWN momentum**
    ```
    Day 1: Price -250 pts (down 1.2%), EMA8 slope -1.8 pts/bar
    Momentum = -15 (STRONG_DOWN)
    → Sellers exhausted, buyers stepping in
    → Fade signal = LONG (+1.0)
    → You catch the bounce
    ```

    #### Why It Might Work

    1. **Volatility Clustering**: Big moves tend to be followed by consolidation
    2. **Order Flow Imbalance**: Extreme momentum = one side dominant → reversal near
    3. **Fear/Greed Extremes**: Overbought/oversold psychology = reversal setup
    4. **ATR Normalization**: Comparing relative to volatility, not absolute pts

    #### Why It Might Fail

    1. **Trending Markets**: Strong trends have multiple STRONG_UP/DOWN readings in a row
       - Fade the first STRONG_UP → gets whipsawed by continuation
    2. **Breakouts**: New regime starts with extreme momentum → fade loses
    3. **News Events**: Gap opens with huge momentum → no immediate reversion
    4. **Thin Consolidation**: If momentum rarely hits STRONG → few trading signals

    #### What We're Testing

    - **Hit Rate**: Does fade beat 50% coin flip?
    - **Expectancy**: Is the edge positive?
    - **Regime**: When does fade work (consolidation/range) vs momentum (trend)?
    - **Combo**: Can averaging/voting both signals hedge each other?

    #### Next: Hourly Intraday Layer

    Current momentum/fade are on DAILY timeframe.
    - **Limitation**: Wait until EOD to see signal
    - **Opportunity**: Intraday entry/exit using **proxy EMAs on hourly**
      - Momentum signal: daily trend
      - Entry/exit: hourly 20-EMA for timing
      - Stop loss: hourly reversal or time-based

    (Discuss in next tab after fade optimizer settles)
    """)
