"""
Pages 30: Fade Strategy Optimizer — mean-reversion complement to momentum

FADE THESIS: Extreme EMA momentum (overbought/oversold) reverts.
  STRONG_UP momentum (15+ %ATR/day) → expect snap-down → FADE = SHORT (-1.0)
  STRONG_DOWN momentum (-15 %ATR/day) → expect snap-up → FADE = LONG (+1.0)

Compare fade performance vs momentum:
- Momentum: trend-following (works in trends, whipsawed in consolidation)
- Fade: mean-reversion (works in range-bound, hurt in strong trends)
- Combo: diversify approach, hedge each other
"""

import streamlit as st
import numpy as np
import pandas as pd
from dataclasses import dataclass

from analytics.ema import EMAEngine
from analytics import signal_lab as sl
from analytics.signal_adapters_fade import adapt_ema_momentum_fade
from page_utils import show_page_header
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

show_page_header("Fade Strategy Optimizer", "xp7rd2", """
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
    section_header("Fade Configuration Tuner")

    st.markdown("**Adjust fade thresholds** — same interface as momentum, will be sign-flipped in strategy.")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        w_ema3 = st.slider("EMA3 Weight (Fade)", 0.3, 0.8, 0.6, step=0.05, key="fade_w3")
        w_ema8 = 1.0 - w_ema3
        st.caption(f"EMA8: {w_ema8:.2f}")

    with col2:
        thresh_strong_up = st.slider("STRONG threshold (Fade)", 8.0, 25.0, 15.0, step=1.0, key="fade_strong")
        thresh_strong_dn = -thresh_strong_up

    with col3:
        thresh_moderate_up = st.slider("MODERATE threshold (Fade)", 1.0, 10.0, 5.0, step=0.5, key="fade_moderate")
        thresh_moderate_dn = -thresh_moderate_up

    with col4:
        trans_mode = st.selectbox("TRANSITIONING (Fade)", ["0.0 (no opinion)", "weak (±0.25)", "strong (±0.5)"], key="fade_trans")
        trans_val = {"0.0 (no opinion)": 0.0, "weak (±0.25)": "weak", "strong (±0.5)": "strong"}[trans_mode]

    accel = st.checkbox("Add acceleration (10%)?", value=False, key="fade_accel")
    atr_scaled = st.checkbox("ATR-scale slopes?", value=True, key="fade_atr")

    if st.button("Test This Fade Config", type="primary", key="test_fade"):
        with st.spinner("Computing fade signal..."):
            try:
                from data.live_fetcher import get_nifty_daily
                daily = get_nifty_daily(days=400)
                if daily.empty:
                    st.error("Could not fetch data")
                else:
                    config = FadeConfig(
                        name="Custom Fade",
                        w_ema3=w_ema3, w_ema8=w_ema8,
                        thresh_strong_up=thresh_strong_up,
                        thresh_moderate_up=thresh_moderate_up,
                        thresh_moderate_dn=thresh_moderate_dn,
                        thresh_strong_dn=thresh_strong_dn,
                        transitioning_score=trans_val,
                        atr_scale=atr_scaled,
                        accel_weight=0.1 if accel else 0.0,
                    )

                    sig = compute_fade_signal(daily, config)
                    result = sl.evaluate_signal(daily, sig, name="Fade", horizons=(5, 10))

                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Hit Rate %", f"{result['hit_rate']:.1f}%")
                    with col2:
                        st.metric("Expectancy %", f"{result['expectancy']:+.3f}%")
                    with col3:
                        st.metric("Spearman ρ", f"{result['spearman']:+.3f}" if result['spearman'] else "NaN")
                    with col4:
                        st.metric("n_active", result['n_active'], f"of {result['n']}")

                    if not result['bucket'].empty:
                        st.subheader("Bucket Analysis")
                        st.dataframe(result['bucket'].round(3), use_container_width=True)

            except Exception as e:
                st.error(f"Error: {e}")

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
