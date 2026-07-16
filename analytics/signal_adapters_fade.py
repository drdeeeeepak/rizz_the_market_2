# analytics/signal_adapters_fade.py
# Fade variants — inverse of momentum signals
#
# FADE THESIS: Extreme EMA momentum reverts.
#   STRONG_UP momentum → expect snap-down → FADE = SHORT (-1.0)
#   STRONG_DOWN momentum → expect snap-up → FADE = LONG (+1.0)
#   MODERATE → weaker fade
#   FLAT/TRANSITIONING → no opinion (0.0)
#
# Mirrors adapt_ema_momentum() but with flipped sign convention.

import numpy as np
import pandas as pd

from analytics.ema import EMAEngine


def adapt_ema_momentum_fade(daily: pd.DataFrame, **momentum_config) -> pd.Series:
    """EMA momentum FADE (mean-reversion) — inverse of momentum directional bet.

    Same computation as adapt_ema_momentum (EMA3/EMA8 slopes, weighted, scaled),
    but sign-flipped: STRONG_UP becomes SHORT (-1.0), STRONG_DOWN becomes LONG (+1.0).

    Hypothesis: Extreme momentum overshoots and snaps back. Fade the extremes,
    catch the reversion.

    momentum_config: optional overrides for thresholds/weighting (used by optimizer)
      - w_ema3, w_ema8: weights (default 0.6, 0.4)
      - thresh_strong_up, thresh_moderate_up, thresh_moderate_dn, thresh_strong_dn
      - transitioning_score: 0.0 or "weak" or "strong"
      - atr_scale: bool (default True)
      - accel_weight: float (default 0.0)
    """
    # Use production defaults from analytics.ema if not overridden
    from analytics.ema import (
        MOM_STRONG_UP_THRESH, MOM_MODERATE_UP_THRESH,
        MOM_MODERATE_DN_THRESH, MOM_STRONG_DN_THRESH,
    )

    w_ema3 = momentum_config.get("w_ema3", 0.6)
    w_ema8 = momentum_config.get("w_ema8", 0.4)
    thresh_strong_up = momentum_config.get("thresh_strong_up", MOM_STRONG_UP_THRESH)
    thresh_moderate_up = momentum_config.get("thresh_moderate_up", MOM_MODERATE_UP_THRESH)
    thresh_moderate_dn = momentum_config.get("thresh_moderate_dn", MOM_MODERATE_DN_THRESH)
    thresh_strong_dn = momentum_config.get("thresh_strong_dn", MOM_STRONG_DN_THRESH)
    transitioning_score = momentum_config.get("transitioning_score", 0.0)
    atr_scale = momentum_config.get("atr_scale", True)
    accel_weight = momentum_config.get("accel_weight", 0.0)

    # Normalize weights
    total = w_ema3 + w_ema8
    if total != 1.0:
        w_ema3 /= total
        w_ema8 /= total

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

    if atr_scale:
        ema3_scaled = (ema3_slope / atr * 100)
        ema8_scaled = (ema8_slope / atr * 100)
    else:
        ema3_scaled = ema3_slope
        ema8_scaled = ema8_slope

    combined = ema3_scaled * w_ema3 + ema8_scaled * w_ema8

    if accel_weight > 0:
        ema3_accel = ema3_slope.diff(3) / 3.0
        ema8_accel = ema8_slope.diff(3) / 3.0
        if atr_scale:
            ema3_accel = (ema3_accel / atr * 100)
            ema8_accel = (ema8_accel / atr * 100)
        accel_combined = ema3_accel * w_ema3 + ema8_accel * w_ema8
        combined = combined * (1 - accel_weight) + accel_combined * accel_weight

    # Classify (same as momentum)
    state = pd.Series("FLAT", index=d.index)
    state[combined > thresh_strong_up] = "STRONG_UP"
    state[(combined > thresh_moderate_up) & (combined <= thresh_strong_up)] = "MODERATE_UP"
    state[combined < thresh_strong_dn] = "STRONG_DOWN"
    state[(combined < thresh_moderate_dn) & (combined >= thresh_strong_dn)] = "MODERATE_DOWN"

    transitioning = (ema3_slope > 0) != (ema8_slope > 0)
    trans_val = _get_trans_value(transitioning_score)
    if trans_val == 0.0:
        state[transitioning] = "FLAT"
    else:
        state[transitioning] = "TRANSITIONING"

    # FADE MAP: flip signs (SHORT the momentum, LONG the weakness)
    fade_map = {
        "STRONG_UP":      -1.0,   # Fade strength down → SHORT
        "MODERATE_UP":    -0.5,   # Weak fade
        "FLAT":            0.0,   # No opinion
        "MODERATE_DOWN":  +0.5,   # Weak fade
        "STRONG_DOWN":    +1.0,   # Fade weakness up → LONG
        "TRANSITIONING":   0.0,   # Starts here, override below if needed
    }
    sig = state.map(fade_map).astype(float)

    if trans_val != 0.0:
        # Transitioning: fade in direction of faster EMA deceleration
        # If EMA3 was up but now flat, fading upside (short); vice versa
        sig[state == "TRANSITIONING"] = -trans_val * np.sign(ema3_slope[state == "TRANSITIONING"])

    sig.index = pd.to_datetime(sig.index).normalize()
    sig.name = "ema_momentum_fade"
    return sig


def _get_trans_value(score: float | str) -> float:
    """Convert transitioning_score config to numeric."""
    if isinstance(score, float):
        return score
    if score == "weak":
        return 0.25
    if score == "strong":
        return 0.5
    return 0.0
