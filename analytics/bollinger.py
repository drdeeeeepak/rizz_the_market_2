# analytics/bollinger.py — v3 (April 2026)
# Page 09: Bollinger Bands Framework
#
# Changes from v2:
#   - Walk modifier now ATR-scaled and age-adjusted (replaces flat +400)
#     Day 3: 1.5x ATR14, Day 4-5: 1.0x ATR14, Day 6+: 0.5x ATR14
#     Cap: 2.0x ATR14, Floor: 100 pts
#   - MEAN_REVERT regime added (BW% > 10%) with -100 pts tightening bonus
#   - BB-VIX divergence: 0.5x ATR14 both sides (was fixed 200 pts)
#   - Band breach: 0.5x ATR14 both sides (was fixed 200 pts), Days 1-2 only
#   - All modifiers are INDEPENDENT — do not stack with other lenses

import pandas as pd
import numpy as np
from analytics.base_strategy import BaseStrategy
from config import (
    BB_PERIOD, BB_STD, BB_SQUEEZE, BB_NORMAL_L, BB_NORMAL_H, BB_EXPAND,
    BB_VIX_DIV_VIX, BB_VIX_DIV_BW,
    OI_STRIKE_STEP,
)

# BW% thresholds
BW_SQUEEZE        = 3.5   # below = squeeze
BW_SQUEEZE_WARN   = 4.0   # 3.5-4.0 = resolving
BW_NORMAL_LOW     = 4.0
BW_NORMAL_HIGH    = 7.0
BW_ELEVATED       = 10.0  # above = mean revert regime

# Walk age → ATR multiplier
WALK_MULTIPLIERS = {3: 1.5, 4: 1.0, 5: 1.0}   # day 6+ = 0.5
WALK_MULT_EXTENDED = 0.5
WALK_CAP_MULT  = 2.0    # max = 2x ATR14
WALK_FLOOR_PTS = 100    # minimum modifier

# BB-VIX divergence and breach multipliers
BB_VIX_MULT    = 0.5   # 0.5x ATR14 both sides
BB_BREACH_MULT = 0.5   # 0.5x ATR14 both sides (Days 1-2 only)

# Mean revert bonus
MEAN_REVERT_BONUS = -100  # pts both sides


class BollingerOptionsEngine(BaseStrategy):

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        basis, upper, lower, bw_pct = self.bollinger(
            df["close"], BB_PERIOD, BB_STD
        )
        df["bb_basis"] = basis
        df["bb_upper"] = upper
        df["bb_lower"] = lower
        df["bb_bw"]    = bw_pct
        df["bb_pct_b"] = (df["close"] - lower) / (upper - lower)
        df["atr14"]    = self.atr(df, 14)

        # Walk streaks — consecutive closes at/beyond band
        for col in ("walk_up", "walk_down"):
            at_band = (df["close"] >= df["bb_upper"]) if col == "walk_up" \
                      else (df["close"] <= df["bb_lower"])
            streak, c = [], 0
            for v in at_band:
                c = c + 1 if v else 0
                streak.append(c)
            df[f"{col}_count"] = streak

        return df

    def signals(self, df: pd.DataFrame) -> dict:
        df = self.compute(df.copy())
        r  = df.iloc[-1]

        spot      = float(r["close"])
        basis     = float(r["bb_basis"])
        upper     = float(r["bb_upper"])
        lower     = float(r["bb_lower"])
        bw_pct    = float(r["bb_bw"])
        pct_b     = float(r["bb_pct_b"])
        walk_up   = int(r["walk_up_count"])
        walk_down = int(r["walk_down_count"])
        atr14     = float(r.get("atr14", 200))

        regime = self._regime(spot, basis, upper, lower, bw_pct, walk_up, walk_down)

        # ATR-scaled walk modifier (independent — only for threatened leg)
        put_mod, call_mod = self._walk_modifier(regime, walk_up, walk_down, atr14)

        # BB-VIX divergence — needs live VIX, defaulted here; computed in compute_signals
        bb_vix_div = False  # set externally in compute_signals
        bb_breach  = self._band_breach(df)

        kills = self._kill_switches(df)
        home  = self._home_score(regime, bw_pct, kills)

        return {
            "basis":           round(basis, 0),
            "upper":           round(upper, 0),
            "lower":           round(lower, 0),
            "bw_pct":          round(bw_pct, 2),
            "pct_b":           round(pct_b, 3),
            "spot":            round(spot, 0),
            "walk_up_count":   walk_up,
            "walk_down_count": walk_down,
            "atr14":           round(atr14, 1),
            "regime":          regime,
            # ATR-scaled modifiers (independent)
            "bb_distance_put":  put_mod,
            "bb_distance_call": call_mod,
            "bb_vix_divergence": bb_vix_div,
            "bb_breach":        bb_breach,
            "bb_breach_pts":    round(BB_BREACH_MULT * atr14 / 50) * 50 if bb_breach else 0,
            "kill_switches":    kills,
            "home_score":       home,
            # Strike guidance (legacy — kept for existing page display)
            "ce_strike": self._ce_strike(regime, upper, lower, basis),
            "pe_strike": self._pe_strike(regime, upper, lower, basis),
        }

    # ── Regime ────────────────────────────────────────────────────────────────

    def _regime(self, spot, basis, upper, lower, bw_pct,
                walk_up, walk_down) -> str:
        if bw_pct < BW_SQUEEZE:
            return "SQUEEZE"
        if bw_pct > BW_ELEVATED:
            return "MEAN_REVERT"
        if walk_up >= 3:
            return "WALK_UPPER"
        if walk_down >= 3:
            return "WALK_LOWER"
        return "NEUTRAL_WALK"

    # ── ATR-scaled walk modifier ──────────────────────────────────────────────

    def _walk_modifier(self, regime: str, walk_up: int, walk_down: int,
                       atr14: float) -> tuple:
        """
        Returns (put_modifier_pts, call_modifier_pts).
        WALK_UPPER → CE threatened (call_mod), PE safe (put_mod=0)
        WALK_LOWER → PE threatened (put_mod), CE safe (call_mod=0)
        MEAN_REVERT → mild tightening bonus both sides
        All other regimes → 0
        """
        if regime == "MEAN_REVERT":
            return MEAN_REVERT_BONUS, MEAN_REVERT_BONUS

        if regime == "WALK_UPPER":
            walk_age = walk_up
            mult = WALK_MULTIPLIERS.get(walk_age, WALK_MULT_EXTENDED)
            raw  = mult * atr14
            capped   = min(raw, WALK_CAP_MULT * atr14)
            final    = max(capped, WALK_FLOOR_PTS)
            rounded  = round(final / 50) * 50
            return 0, int(rounded)   # CE threatened only

        if regime == "WALK_LOWER":
            walk_age = walk_down
            mult = WALK_MULTIPLIERS.get(walk_age, WALK_MULT_EXTENDED)
            raw  = mult * atr14
            capped   = min(raw, WALK_CAP_MULT * atr14)
            final    = max(capped, WALK_FLOOR_PTS)
            rounded  = round(final / 50) * 50
            return int(rounded), 0   # PE threatened only

        return 0, 0

    def _band_breach(self, df: pd.DataFrame) -> bool:
        """
        Single close outside band without qualifying as walk (Day 1-2).
        Once walk is confirmed (Day 3), breach no longer applies — walk takes over.
        """
        if len(df) < 2:
            return False
        r = df.iloc[-1]
        walk_up   = int(r.get("walk_up_count", 0))
        walk_down = int(r.get("walk_down_count", 0))
        # Only breach signal if NOT yet a walk
        if walk_up >= 3 or walk_down >= 3:
            return False
        close = float(r["close"])
        return close >= float(r["bb_upper"]) or close <= float(r["bb_lower"])

    # ── Kill switches ─────────────────────────────────────────────────────────

    def _kill_switches(self, df: pd.DataFrame) -> dict:
        r = df.iloc[-1]
        bw = float(r.get("bb_bw", 6.0))
        wu = int(r.get("walk_up_count", 0))
        wd = int(r.get("walk_down_count", 0))
        breach = self._band_breach(df)
        return {
            "SQUEEZE":     bw < BW_SQUEEZE,
            "WALK_UPPER":  wu >= 3,
            "WALK_LOWER":  wd >= 3,
            "BAND_BREACH": breach,
            "MEAN_REVERT": bw > BW_ELEVATED,
            # Legacy
            "K1": breach,
        }

    # ── Home score ────────────────────────────────────────────────────────────

    def _home_score(self, regime: str, bw_pct: float, kills: dict) -> int:
        if regime == "SQUEEZE": return 0
        if regime in ("WALK_UPPER", "WALK_LOWER"): return 5
        if regime == "NEUTRAL_WALK": return 15
        if regime == "MEAN_REVERT":  return 12
        return 10

    # ── Legacy strike selection ───────────────────────────────────────────────

    def _ce_strike(self, regime, upper, lower, basis) -> int:
        half = upper - basis
        if regime == "SQUEEZE":    return 0
        if regime == "WALK_UPPER": return self.round_strike(upper + 0.5*half, "ceil")
        if regime == "WALK_LOWER": return self.round_strike(basis, "ceil")
        return self.round_strike(upper, "ceil")

    def _pe_strike(self, regime, upper, lower, basis) -> int:
        half = basis - lower
        if regime == "SQUEEZE":    return 0
        if regime == "WALK_UPPER": return self.round_strike(basis, "floor")
        if regime == "WALK_LOWER": return self.round_strike(lower - 0.5*half, "floor")
        return self.round_strike(lower, "floor")

    def round_strike(self, price: float, direction: str = "round") -> int:
        if direction == "ceil":  return int(np.ceil(price / 50)) * 50
        if direction == "floor": return int(np.floor(price / 50)) * 50
        return int(round(price / 50)) * 50
