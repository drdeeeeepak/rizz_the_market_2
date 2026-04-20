# analytics/vix_iv_regime.py — v3 (April 2026)
# Page 11: VIX / IV Framework
#
# New vs v2:
#   - Six VIX states based on 200 SMA + UBB + 20/50 SMA (not fixed level zones)
#   - Spike detection: any 2 of 3 thresholds (speed, SMA gap, BB width on VIX)
#   - Stability detection: all 3 conditions required
#   - SPIKE_RESOLVING state: was above UBB, below 20 SMA, candle range contracting
#   - DANGER state: above UBB AND above 20 SMA (red warning, not hard kill)
#   - CAUTION state: above UBB, below 20 SMA (orange warning)
#   - No hard kill switches — all warnings advisory
#   - IVP zones renamed: HISTORICALLY_LOW, BELOW_AVERAGE, IDEAL, HISTORICALLY_HIGH, EXTREME
#   - VRP unchanged

import pandas as pd
import numpy as np
from analytics.base_strategy import BaseStrategy
from config import (
    IVP_AVOID, IVP_SMALL, IVP_IDEAL_H, IVP_EXTREME, HV_PERIOD,
)

# VIX SMA periods
VIX_SMA_200 = 200
VIX_SMA_50  = 50
VIX_SMA_20  = 20

# Spike detection thresholds
SPIKE_SPEED_PTS   = 4.0   # weekly VIX change > 4 pts for 2 consecutive weeks
SPIKE_SMA_GAP     = 3.0   # 20 SMA > 50 SMA by more than 3 pts
SPIKE_BB_WIDTH    = 10.0  # BB width on VIX > 10 pts

# Stability detection thresholds
STABLE_SPEED_MAX  = 2.0   # weekly change < 2 pts for 2 weeks
STABLE_RANGE_MAX  = 1.5   # 3-day avg daily candle range < 1.5 pts
STABLE_CONSEC     = 3     # consecutive days of contraction


class VixIVRegimeEngine(BaseStrategy):

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df["log_ret"] = np.log(df["close"] / df["close"].shift(1))
        df["hv20"]    = df["log_ret"].rolling(HV_PERIOD).std() * np.sqrt(252) * 100
        return df

    def signals(self, price_df: pd.DataFrame, vix_history: pd.DataFrame,
                current_vix: float, atm_iv: float) -> dict:

        price_df = self.compute(price_df.copy())
        hv20     = float(price_df["hv20"].iloc[-1]) if not price_df.empty else 0.0
        vrp      = atm_iv - hv20
        ivp_1yr  = self._ivp(current_vix, vix_history, 252)
        ivp_5yr  = self._ivp(current_vix, vix_history, 1260)
        ivp_zone = self._ivp_zone(ivp_1yr)

        # VIX technical analysis
        vix_tech = self._vix_technical(vix_history, current_vix)
        state    = vix_tech["state"]
        size_mult = self._size_multiplier(state)

        # Warnings (advisory only — no hard kills)
        warnings = self._warnings(state, vrp, ivp_1yr)

        return {
            "vix":            round(current_vix, 2),
            # New state-based classification
            "vix_state":      state,
            "vix_zone":       state,   # legacy alias
            # SMA values
            "vix_sma_200":    vix_tech.get("sma_200", 0),
            "vix_sma_50":     vix_tech.get("sma_50", 0),
            "vix_sma_20":     vix_tech.get("sma_20", 0),
            "vix_ubb":        vix_tech.get("ubb", 0),
            "vix_bb_width":   vix_tech.get("bb_width", 0),
            # Spike/stability
            "vix_spike_confirmed": vix_tech.get("spike_confirmed", False),
            "vix_stable_confirmed":vix_tech.get("stable_confirmed", False),
            "vix_spike_count": vix_tech.get("spike_threshold_count", 0),
            # IV metrics
            "hv20":           round(hv20, 2),
            "atm_iv":         round(atm_iv, 2),
            "vrp":            round(vrp, 2),
            "vrp_positive":   vrp > 0,
            "ivp_1yr":        round(ivp_1yr, 0),
            "ivp_5yr":        round(ivp_5yr, 0),
            "ivp_zone":       ivp_zone,
            "size_multiplier":size_mult,
            # Warnings
            "warnings":       warnings,
            "is_danger":      state == "DANGER",
            "is_caution":     state == "CAUTION",
            "is_spike_resolving": state == "SPIKE_RESOLVING",
            "is_best_entry":  state == "SPIKE_RESOLVING",
            # Kill switches (advisory only)
            "kill_switches": {
                "HARD_KILL":      False,  # no hard kills in new framework
                "K4_vrp_negative": vrp < 0,
                "VRP_NEGATIVE":   vrp < 0,
                "DANGER_WARNING": state == "DANGER",
                "CAUTION_WARNING":state in ("CAUTION", "DANGER"),
            },
            "vix_hard_kill":  False,   # no hard kills — legacy key kept
            "vix_k4_vrp_neg": vrp < 0,
            "home_score":     self._home_score(state, ivp_1yr, vrp),
        }

    # ── VIX Technical Analysis ────────────────────────────────────────────────

    def _vix_technical(self, vix_hist: pd.DataFrame, current_vix: float) -> dict:
        """
        Compute VIX SMAs, UBB, and classify into one of six states.
        """
        if vix_hist.empty or "close" not in vix_hist.columns:
            return self._fallback_tech(current_vix)

        vix = vix_hist["close"].dropna()
        if len(vix) < VIX_SMA_200:
            return self._fallback_tech(current_vix)

        # Append current VIX as running close
        vix = pd.concat([vix, pd.Series([current_vix])], ignore_index=True)

        sma_200 = float(vix.rolling(VIX_SMA_200).mean().iloc[-1])
        sma_50  = float(vix.rolling(VIX_SMA_50).mean().iloc[-1])
        sma_20  = float(vix.rolling(VIX_SMA_20).mean().iloc[-1])

        # UBB = 200 SMA + 2 std of VIX over 200 days
        std_200 = float(vix.rolling(VIX_SMA_200).std().iloc[-1])
        ubb     = sma_200 + 2 * std_200

        # BB width on VIX = (UBB - LBB) = 4 * std_200
        bb_width = 4 * std_200

        # Spike detection — any 2 of 3 thresholds
        speed_ok = self._spike_speed(vix, SPIKE_SPEED_PTS)
        sma_gap_ok = (
            (sma_20 - sma_50) > SPIKE_SMA_GAP and
            (len(vix) < 2 or sma_20 > vix.iloc[-2] if len(vix) >= 2 else False) and
            current_vix > ubb
        )
        bb_width_ok = bb_width > SPIKE_BB_WIDTH and bb_width > (
            float(vix.rolling(VIX_SMA_200).std().iloc[-2]) * 4
            if len(vix) >= VIX_SMA_200 + 1 else 0
        )
        spike_count = sum([speed_ok, sma_gap_ok, bb_width_ok])
        spike_confirmed = spike_count >= 2

        # Stability detection — all 3 required
        stable_confirmed = self._stable_confirmed(vix, sma_20, sma_50)

        # State classification
        state = self._classify_state(
            current_vix, sma_200, ubb, sma_20, sma_50,
            spike_confirmed, stable_confirmed
        )

        return {
            "state":                 state,
            "sma_200":               round(sma_200, 2),
            "sma_50":                round(sma_50, 2),
            "sma_20":                round(sma_20, 2),
            "ubb":                   round(ubb, 2),
            "bb_width":              round(bb_width, 2),
            "spike_confirmed":       spike_confirmed,
            "stable_confirmed":      stable_confirmed,
            "spike_threshold_count": spike_count,
        }

    def _fallback_tech(self, current_vix: float) -> dict:
        """Fallback when insufficient VIX history."""
        state = ("STABLE_LOW" if current_vix < 12 else
                 "STABLE_NORMAL" if current_vix < 16 else
                 "ELEVATED")
        return {"state": state, "sma_200": 13.0, "sma_50": 13.0, "sma_20": 13.0,
                "ubb": 22.0, "bb_width": 9.0, "spike_confirmed": False,
                "stable_confirmed": True, "spike_threshold_count": 0}

    def _spike_speed(self, vix: pd.Series, threshold: float) -> bool:
        """VIX rose more than threshold pts week-on-week for 2 consecutive weeks."""
        if len(vix) < 15:
            return False
        # Approximate weekly change (5 trading days)
        w1 = float(vix.iloc[-1]) - float(vix.iloc[-6])
        w2 = float(vix.iloc[-6]) - float(vix.iloc[-11])
        return w1 > threshold and w2 > threshold

    def _stable_confirmed(self, vix: pd.Series, sma_20: float, sma_50: float) -> bool:
        """All three stability conditions met."""
        if len(vix) < 15:
            return True
        # 1: weekly change < 2 pts for 2 weeks
        w1 = abs(float(vix.iloc[-1]) - float(vix.iloc[-6]))
        w2 = abs(float(vix.iloc[-6]) - float(vix.iloc[-11]))
        speed_stable = w1 < STABLE_SPEED_MAX and w2 < STABLE_SPEED_MAX
        # 2: 20/50 SMA gap narrowing
        sma_gap_narrowing = (sma_20 - sma_50) < 2.0
        # 3: daily candle range contracting (approximate — use last 3 points)
        if len(vix) >= 4:
            ranges = [abs(float(vix.iloc[-i]) - float(vix.iloc[-i-1])) for i in range(1, 4)]
            range_stable = np.mean(ranges) < STABLE_RANGE_MAX
        else:
            range_stable = True
        return speed_stable and sma_gap_narrowing and range_stable

    def _classify_state(self, vix: float, sma_200: float, ubb: float,
                        sma_20: float, sma_50: float,
                        spike_confirmed: bool, stable_confirmed: bool) -> str:
        above_ubb = vix > ubb
        above_20  = vix > sma_20
        above_200 = vix > sma_200

        if above_ubb and above_20:
            return "DANGER"
        if above_ubb and not above_20:
            if stable_confirmed:
                return "SPIKE_RESOLVING"
            return "CAUTION"
        if above_200:
            return "ELEVATED"
        # Below 200 SMA
        if stable_confirmed:
            return "STABLE_LOW" if vix < sma_200 - 1 else "STABLE_NORMAL"
        return "STABLE_NORMAL"

    # ── IVP ──────────────────────────────────────────────────────────────────

    def _ivp(self, current_vix: float, vix_history: pd.DataFrame,
             lookback: int = 252) -> float:
        if vix_history.empty or "close" not in vix_history.columns:
            return 50.0
        hist = vix_history["close"].tail(lookback).dropna()
        if len(hist) == 0:
            return 50.0
        return round(float((hist < current_vix).mean() * 100), 1)

    def _ivp_zone(self, ivp: float) -> str:
        if   ivp < 15: return "HISTORICALLY_LOW"
        elif ivp < 25: return "BELOW_AVERAGE"
        elif ivp < 70: return "IDEAL"
        elif ivp < 80: return "HISTORICALLY_HIGH"
        else:          return "EXTREME"

    # ── Size multiplier ───────────────────────────────────────────────────────

    def _size_multiplier(self, state: str) -> float:
        return {
            "STABLE_LOW":       1.0,
            "STABLE_NORMAL":    1.0,
            "ELEVATED":         1.0,
            "CAUTION":          0.75,
            "DANGER":           0.50,
            "SPIKE_RESOLVING":  1.0,
        }.get(state, 1.0)

    # ── Warnings ──────────────────────────────────────────────────────────────

    def _warnings(self, state: str, vrp: float, ivp: float) -> list:
        w = []
        if state == "DANGER":
            w.append("VIX IN ACTIVE SPIKE TERRITORY — use maximum distance both sides, size 50%")
        elif state == "CAUTION":
            w.append("VIX above UBB but falling — spike may be resolving, monitor daily candle range")
        if vrp < 0:
            w.append("VRP NEGATIVE — IV below realised vol. Selling edge gone. Widen both sides.")
        if ivp < 15:
            w.append("IVP HISTORICALLY LOW — premiums at annual lows. Reduce size.")
        return w

    # ── Home score ────────────────────────────────────────────────────────────

    def _home_score(self, state: str, ivp: float, vrp: float) -> int:
        scores = {
            "STABLE_NORMAL": 15, "ELEVATED": 12, "SPIKE_RESOLVING": 18,
            "STABLE_LOW": 8, "CAUTION": 6, "DANGER": 3,
        }
        s = scores.get(state, 10)
        if vrp < 0:   s -= 3
        if ivp < 15:  s -= 3
        if ivp > 70:  s += 2
        return max(0, min(s, 20))
