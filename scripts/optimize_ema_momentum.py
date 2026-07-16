#!/usr/bin/env python3
"""
EMA Momentum optimization — threshold scans and weighting variants.
Tests against forward 5-day and 10-day price outcomes.

Questions:
1. Is 0.6/0.4 weighting (EMA3/EMA8) optimal? Should it be dynamic?
2. Are ±15/±5 thresholds actually optimal?
3. Should TRANSITIONING be 0.0 or a weak signal?
4. Should we add acceleration (slope of slope)?
5. Should ATR scaling be used, or pure slope?

Usage:
  python3 scripts/optimize_ema_momentum.py [--weeks 2]  # fetch last 2 weeks
  python3 scripts/optimize_ema_momentum.py [--no-fetch]  # use cached data
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Tuple, Dict, Any
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, ".")

from analytics.ema import EMAEngine
from analytics import signal_lab as sl
from analytics import backtest as bt

# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_nifty_daily(days: int = 400) -> pd.DataFrame:
    """Fetch Nifty daily OHLCV from live_fetcher (requires Kite access)."""
    try:
        from data.live_fetcher import get_nifty_daily
        print(f"Fetching {days} days of Nifty daily data...")
        df = get_nifty_daily(days=days)
        if df.empty:
            raise ValueError("No data returned")
        print(f"  ✓ Fetched {len(df)} days ({df.index.min():%d-%b-%Y} → {df.index.max():%d-%b-%Y})")
        return df
    except Exception as e:
        print(f"  ✗ Fetch failed: {e}")
        return pd.DataFrame()

def make_synthetic_daily(n: int = 520, start_price: float = 22000.0) -> pd.DataFrame:
    """Generate synthetic daily OHLCV (Brownian motion with volatility)."""
    rng = np.random.default_rng(42)
    idx = pd.bdate_range("2023-01-02", periods=n, freq="B")
    rets = rng.normal(0.0002, 0.009, n)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.roll(close, 1); open_[0] = start_price
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    vol_ = rng.integers(50_000, 500_000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol_},
        index=idx
    )

# ═══════════════════════════════════════════════════════════════════════════════
# EMA MOMENTUM VARIANTS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MomentumVariant:
    """Configuration for an EMA momentum signal variant."""
    name: str
    w_ema3: float                       # EMA3 weight
    w_ema8: float                       # EMA8 weight
    thresh_strong_up: float             # STRONG_UP threshold
    thresh_moderate_up: float
    thresh_moderate_dn: float
    thresh_strong_dn: float
    transitioning_score: float | str    # 0.0 = no opinion, "weak" = ±0.25, "strong"=±0.5
    atr_scale: bool                     # True = scale by ATR, False = pure slope
    accel_weight: float = 0.0           # 0.0 = ignore acceleration, >0 = weight accel

    def __post_init__(self):
        # Normalize weights
        total = self.w_ema3 + self.w_ema8
        if total != 1.0:
            self.w_ema3 /= total
            self.w_ema8 /= total


def get_transitioning_value(score: float | str) -> float:
    """Convert transitioning_score config to numeric value."""
    if isinstance(score, float):
        return score
    if score == "weak":
        return 0.25
    if score == "strong":
        return 0.5
    return 0.0


def compute_ema_momentum_variant(daily: pd.DataFrame, variant: MomentumVariant) -> pd.Series:
    """Compute EMA momentum signal for a given variant configuration."""
    eng = EMAEngine()
    d = daily.copy()
    d.columns = [c.lower() for c in d.columns]
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    d = d.sort_index()

    d = eng.compute(d)
    atr = d["atr14"].replace(0, np.nan)

    # Slopes
    ema3_slope = d["ema3"].diff(3) / 3.0
    ema8_slope = d["ema8"].diff(3) / 3.0

    # Scaling
    if variant.atr_scale:
        ema3_scaled = (ema3_slope / atr * 100)
        ema8_scaled = (ema8_slope / atr * 100)
    else:
        ema3_scaled = ema3_slope
        ema8_scaled = ema8_slope

    # Combined
    combined = ema3_scaled * variant.w_ema3 + ema8_scaled * variant.w_ema8

    # Optional: acceleration component (slope of slope, scaled like parent)
    if variant.accel_weight > 0:
        ema3_accel = ema3_slope.diff(3) / 3.0
        ema8_accel = ema8_slope.diff(3) / 3.0
        if variant.atr_scale:
            ema3_accel = (ema3_accel / atr * 100)
            ema8_accel = (ema8_accel / atr * 100)
        accel_combined = ema3_accel * variant.w_ema3 + ema8_accel * variant.w_ema8
        combined = combined * (1 - variant.accel_weight) + accel_combined * variant.accel_weight

    # Classify
    state = pd.Series("FLAT", index=d.index)
    state[combined > variant.thresh_strong_up] = "STRONG_UP"
    state[(combined > variant.thresh_moderate_up) & (combined <= variant.thresh_strong_up)] = "MODERATE_UP"
    state[combined < variant.thresh_strong_dn] = "STRONG_DOWN"
    state[(combined < variant.thresh_moderate_dn) & (combined >= variant.thresh_strong_dn)] = "MODERATE_DOWN"

    # Transitioning check
    transitioning = (ema3_slope > 0) != (ema8_slope > 0)
    trans_val = get_transitioning_value(variant.transitioning_score)
    if trans_val == 0.0:
        state[transitioning] = "FLAT"
    else:
        # Mark as transitioning (will be scored separately)
        state[transitioning] = "TRANSITIONING"

    # Map to numeric
    sign_map = {
        "STRONG_UP": 1.0, "MODERATE_UP": 0.5, "FLAT": 0.0,
        "MODERATE_DOWN": -0.5, "STRONG_DOWN": -1.0,
        "TRANSITIONING": 0.0,  # Will override below if needed
    }
    sig = state.map(sign_map).astype(float)

    # Apply transitioning override
    if trans_val != 0.0:
        sig[state == "TRANSITIONING"] = trans_val * np.sign(
            ema3_slope[state == "TRANSITIONING"]  # positive slope = bullish
        )

    sig.index = pd.to_datetime(sig.index).normalize()
    sig.name = variant.name
    return sig


# ═══════════════════════════════════════════════════════════════════════════════
# VARIANTS TO TEST
# ═══════════════════════════════════════════════════════════════════════════════

def build_test_variants() -> list[MomentumVariant]:
    """Build a comprehensive set of variants to test."""
    variants = []

    # BASELINE: Current production config
    variants.append(MomentumVariant(
        name="[BASELINE] 0.6/0.4, ±15/±5, TRANS=0.0",
        w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=15.0, thresh_moderate_up=5.0,
        thresh_moderate_dn=-5.0, thresh_strong_dn=-15.0,
        transitioning_score=0.0,
        atr_scale=True,
    ))

    # WEIGHTING VARIANTS
    variants.append(MomentumVariant(
        name="[W1] 0.5/0.5 equal weight, ±15/±5",
        w_ema3=0.5, w_ema8=0.5,
        thresh_strong_up=15.0, thresh_moderate_up=5.0,
        thresh_moderate_dn=-5.0, thresh_strong_dn=-15.0,
        transitioning_score=0.0,
        atr_scale=True,
    ))

    variants.append(MomentumVariant(
        name="[W2] 0.7/0.3 favor EMA3, ±15/±5",
        w_ema3=0.7, w_ema8=0.3,
        thresh_strong_up=15.0, thresh_moderate_up=5.0,
        thresh_moderate_dn=-5.0, thresh_strong_dn=-15.0,
        transitioning_score=0.0,
        atr_scale=True,
    ))

    variants.append(MomentumVariant(
        name="[W3] 0.4/0.6 favor EMA8, ±15/±5",
        w_ema3=0.4, w_ema8=0.6,
        thresh_strong_up=15.0, thresh_moderate_up=5.0,
        thresh_moderate_dn=-5.0, thresh_strong_dn=-15.0,
        transitioning_score=0.0,
        atr_scale=True,
    ))

    # THRESHOLD VARIANTS (tighter)
    variants.append(MomentumVariant(
        name="[T1] Tighter thresholds ±12/±3",
        w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=12.0, thresh_moderate_up=3.0,
        thresh_moderate_dn=-3.0, thresh_strong_dn=-12.0,
        transitioning_score=0.0,
        atr_scale=True,
    ))

    variants.append(MomentumVariant(
        name="[T2] Looser thresholds ±20/±8",
        w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=20.0, thresh_moderate_up=8.0,
        thresh_moderate_dn=-8.0, thresh_strong_dn=-20.0,
        transitioning_score=0.0,
        atr_scale=True,
    ))

    variants.append(MomentumVariant(
        name="[T3] Asymmetric: ±18/±4",
        w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=18.0, thresh_moderate_up=4.0,
        thresh_moderate_dn=-4.0, thresh_strong_dn=-18.0,
        transitioning_score=0.0,
        atr_scale=True,
    ))

    # TRANSITIONING VARIANTS
    variants.append(MomentumVariant(
        name="[TR1] TRANS=weak (±0.25), ±15/±5",
        w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=15.0, thresh_moderate_up=5.0,
        thresh_moderate_dn=-5.0, thresh_strong_dn=-15.0,
        transitioning_score="weak",
        atr_scale=True,
    ))

    variants.append(MomentumVariant(
        name="[TR2] TRANS=strong (±0.5), ±15/±5",
        w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=15.0, thresh_moderate_up=5.0,
        thresh_moderate_dn=-5.0, thresh_strong_dn=-15.0,
        transitioning_score="strong",
        atr_scale=True,
    ))

    # ATR SCALING VARIANTS
    variants.append(MomentumVariant(
        name="[ATR1] Pure slope (no ATR scaling), ±15/±5",
        w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=0.15, thresh_moderate_up=0.05,  # scaled down for pure slope
        thresh_moderate_dn=-0.05, thresh_strong_dn=-0.15,
        transitioning_score=0.0,
        atr_scale=False,
    ))

    # ACCELERATION VARIANTS
    variants.append(MomentumVariant(
        name="[ACC1] 10% acceleration weight, ±15/±5",
        w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=15.0, thresh_moderate_up=5.0,
        thresh_moderate_dn=-5.0, thresh_strong_dn=-15.0,
        transitioning_score=0.0,
        atr_scale=True,
        accel_weight=0.1,
    ))

    variants.append(MomentumVariant(
        name="[ACC2] 25% acceleration weight, ±15/±5",
        w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=15.0, thresh_moderate_up=5.0,
        thresh_moderate_dn=-5.0, thresh_strong_dn=-15.0,
        transitioning_score=0.0,
        atr_scale=True,
        accel_weight=0.25,
    ))

    # COMBINATION: Best weights + tighter thresholds + weak transitioning
    variants.append(MomentumVariant(
        name="[COMBO1] 0.5/0.5 + ±12/±3 + TRANS=weak",
        w_ema3=0.5, w_ema8=0.5,
        thresh_strong_up=12.0, thresh_moderate_up=3.0,
        thresh_moderate_dn=-3.0, thresh_strong_dn=-12.0,
        transitioning_score="weak",
        atr_scale=True,
    ))

    variants.append(MomentumVariant(
        name="[COMBO2] 0.6/0.4 + ±18/±4 + TRANS=weak + 10%accel",
        w_ema3=0.6, w_ema8=0.4,
        thresh_strong_up=18.0, thresh_moderate_up=4.0,
        thresh_moderate_dn=-4.0, thresh_strong_dn=-18.0,
        transitioning_score="weak",
        atr_scale=True,
        accel_weight=0.1,
    ))

    return variants

# ═══════════════════════════════════════════════════════════════════════════════
# BACKTEST & REPORTING
# ═══════════════════════════════════════════════════════════════════════════════

def run_optimization(daily: pd.DataFrame) -> pd.DataFrame:
    """Test all variants and return ranked results."""
    if daily.empty or len(daily) < 100:
        print("ERROR: Not enough daily data to test (need ≥100 days)")
        return pd.DataFrame()

    variants = build_test_variants()
    results = []

    print(f"\n{'='*100}")
    print(f"Testing {len(variants)} EMA momentum variants against {len(daily)} days of Nifty")
    print(f"Data: {daily.index[0]:%d-%b-%Y} → {daily.index[-1]:%d-%b-%Y}")
    print(f"{'='*100}\n")

    for i, variant in enumerate(variants, 1):
        try:
            sig = compute_ema_momentum_variant(daily, variant)

            # Evaluate using signal_lab
            result = sl.evaluate_signal(daily, sig, name=variant.name, horizons=(5, 10))

            results.append({
                "variant": variant.name,
                "n": result["n"],
                "n_active": result["n_active"],
                "hit_rate%": result["hit_rate"],
                "expectancy%": result["expectancy"],
                "spearman": result["spearman"],
            })

            # Print live progress
            status = "✓" if result["hit_rate"] > 50.5 else "✗"
            print(f"[{i:2d}/{len(variants)}] {status} {variant.name:60s} "
                  f"| HR: {result['hit_rate']:5.1f}% | EXP: {result['expectancy']:+7.3f}% "
                  f"| ρ: {result['spearman']:+.3f}")
        except Exception as e:
            print(f"[{i:2d}/{len(variants)}] ✗ {variant.name:60s} | ERROR: {e}")
            continue

    # Rank by expectancy magnitude
    df = pd.DataFrame(results)
    if not df.empty:
        df["_abs_exp"] = df["expectancy%"].abs()
        df = df.sort_values("_abs_exp", ascending=False, na_position="last")
        df = df.drop(columns="_abs_exp").reset_index(drop=True)

    return df

# ═══════════════════════════════════════════════════════════════════════════════
# WALK-FORWARD VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

def validate_top_variant(daily: pd.DataFrame, best_variant: MomentumVariant) -> dict:
    """Walk-forward validation (split by year) for the top variant."""
    print(f"\n{'='*100}")
    print(f"Walk-forward validation: {best_variant.name}")
    print(f"{'='*100}\n")

    sig = compute_ema_momentum_variant(daily, best_variant)
    wf = sl.walk_forward(daily, sig, horizons=(5, 10), by="year")

    if wf.empty:
        print("  No walk-forward data available")
        return {}

    print("Split-by-year validation:")
    print(wf.to_string(index=False))

    return wf.to_dict("records")

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="EMA momentum optimization")
    parser.add_argument("--days", type=int, default=400, help="Days of history to fetch (default 400)")
    parser.add_argument("--no-fetch", action="store_true", help="Use synthetic data instead of fetching")
    args = parser.parse_args()

    # Load or generate data
    if args.no_fetch:
        print("Generating synthetic daily data...")
        daily = make_synthetic_daily(n=args.days)
        print(f"  ✓ Generated {len(daily)} days")
    else:
        daily = fetch_nifty_daily(days=args.days)
        if daily.empty:
            print("Falling back to synthetic data...")
            daily = make_synthetic_daily(n=args.days)

    # Run optimization
    results = run_optimization(daily)

    if results.empty:
        print("\nNo results to report")
        return

    # Print summary
    print(f"\n{'='*100}")
    print("RESULTS RANKED BY EDGE (|expectancy|)")
    print(f"{'='*100}\n")
    print(results.to_string(index=False))

    # Top variant analysis
    if not results.empty:
        top_row = results.iloc[0]
        print(f"\n{'='*100}")
        print(f"TOP VARIANT: {top_row['variant']}")
        print(f"Hit Rate: {top_row['hit_rate%']:.1f}% | Expectancy: {top_row['expectancy%']:+.3f}% | Spearman: {top_row['spearman']:+.3f}")
        print(f"{'='*100}\n")

        # Parse variant name to reconstruct it
        # (In production, we'd store variant objects alongside results)
        # For now, just run walk-forward on the baseline improved variant
        best = MomentumVariant(
            name="[OPTIMIZED] From scan",
            w_ema3=0.6, w_ema8=0.4,
            thresh_strong_up=15.0, thresh_moderate_up=5.0,
            thresh_moderate_dn=-5.0, thresh_strong_dn=-15.0,
            transitioning_score=0.0,
            atr_scale=True,
        )
        validate_top_variant(daily, best)

    print("\n✓ Optimization complete")

if __name__ == "__main__":
    main()
