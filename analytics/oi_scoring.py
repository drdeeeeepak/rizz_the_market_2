# analytics/oi_scoring.py
# OI Momentum Scoring Engine — Page 10B
# v4.1 — Fixed far expiry showing zeros:
#   Near expiry: scored on % OI CHANGE (intraday flow — changes rapidly)
#   Far expiry:  scored on ABSOLUTE OI LEVELS (structural positioning — changes slowly)
#   Both chains now show meaningful data regardless of intraday activity.

import pandas as pd
import numpy as np
from analytics.base_strategy import BaseStrategy
from config import (
    DTE_THETA_MIN, DTE_WARN_MIN,
    OI_SCORE_HIGH, OI_SCORE_MED, OI_SCORE_LOW, OI_NOISE,
    OI_UNWIND_MILD, OI_UNWIND_HEAVY, OI_PANIC,
    WALL_RATIO_LOW, WALL_RATIO_MID,
    WALL_INTRADAY_REINFORCE, WALL_INTRADAY_ABANDON,
)

# Far expiry OI thresholds — absolute levels (contracts)
# Far expiry barely changes intraday so we score on total OI size
FAR_OI_VERY_HIGH  = 5_000_000   # very strong wall
FAR_OI_HIGH       = 2_000_000   # strong wall
FAR_OI_MED        = 1_000_000   # moderate wall
FAR_OI_LOW        = 300_000     # thin positioning


class OIScoringEngine(BaseStrategy):
    """
    Dual expiry OI scoring.
    Near expiry: flow-based (% change) — catches intraday momentum
    Far expiry:  level-based (absolute OI) — shows structural positioning
    """

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    # ─────────────────────────────────────────────────────────────────────────

    def signals(self, near_df: pd.DataFrame, far_df: pd.DataFrame,
                near_dte: int, far_dte: int,
                near_expiry=None, far_expiry=None) -> dict:
        near_scored = self.score_chain_near(near_df.copy(), near_dte) if not near_df.empty else pd.DataFrame()
        far_scored  = self.score_chain_far(far_df.copy(),  far_dte)  if not far_df.empty  else pd.DataFrame()
        return {
            "near_scored":   near_scored,
            "far_scored":    far_scored,
            "near_dte":      near_dte,
            "far_dte":       far_dte,
            "near_mult":     self.get_dte_multiplier(near_dte),
            "far_mult":      self.get_dte_multiplier(far_dte),
            "near_wall_mod": self.get_wall_modifier(near_dte),
            "far_wall_mod":  self.get_wall_modifier(far_dte),
            "near_expiry":   near_expiry,
            "far_expiry":    far_expiry,
            "kill_switches": {},
            "home_score":    0,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # NEAR EXPIRY — flow-based scoring (% OI change)

    def score_chain_near(self, df: pd.DataFrame, dte: int) -> pd.DataFrame:
        """Near expiry: scored on % OI change — intraday flow momentum."""
        if df.empty:
            return df
        mult     = self.get_dte_multiplier(dte)
        df["pe_base"] = df["pe_pct_change"].apply(self.score_pe_base)
        df["ce_base"] = df["ce_pct_change"].apply(self.score_ce_base)
        df["pe_adj"]  = df["pe_base"].apply(lambda b: b * mult if b < 0 else float(b))
        df["ce_adj"]  = df["ce_base"].apply(lambda b: b * mult if b > 0 else float(b))
        df["net_score"] = (df["pe_adj"] + df["ce_adj"]).clip(-6, 6).round()
        df["pe_wall"]   = df.apply(lambda r: self.wall_strength(r["pe_oi"], r["ce_oi"], r["pe_pct_change"], dte), axis=1)
        df["ce_wall"]   = df.apply(lambda r: self.wall_strength(r["ce_oi"], r["pe_oi"], r["ce_pct_change"], dte), axis=1)
        df["position_action"] = df.apply(lambda r: self._position_action(r["net_score"], r["pe_wall"], r["ce_wall"]), axis=1)
        df["score_method"] = "FLOW"
        return df

    # ─────────────────────────────────────────────────────────────────────────
    # FAR EXPIRY — level-based scoring (absolute OI)

    def score_chain_far(self, df: pd.DataFrame, dte: int) -> pd.DataFrame:
        """
        Far expiry: scored on ABSOLUTE OI LEVELS not % change.
        Far expiry OI barely changes intraday — scoring on % change always gives zeros.
        Absolute OI tells you the structural positioning — where large option sellers
        have committed their positions. This IS meaningful for your trade.
        """
        if df.empty:
            return df

        df["pe_base"] = df["pe_oi"].apply(self._score_far_pe_oi)
        df["ce_base"] = df["ce_oi"].apply(self._score_far_ce_oi)

        # For far expiry, no DTE panic multiplier on base scores
        # But still use % change for wall strength calculation
        df["pe_adj"]  = df["pe_base"].astype(float)
        df["ce_adj"]  = df["ce_base"].astype(float)

        df["net_score"] = (df["pe_adj"] + df["ce_adj"]).clip(-6, 6).round()

        # Wall strength uses absolute OI for far expiry
        df["pe_wall"] = df.apply(
            lambda r: self._far_wall_strength(r["pe_oi"], r["ce_oi"], dte), axis=1
        )
        df["ce_wall"] = df.apply(
            lambda r: self._far_wall_strength(r["ce_oi"], r["pe_oi"], dte), axis=1
        )

        df["position_action"] = df.apply(
            lambda r: self._position_action(r["net_score"], r["pe_wall"], r["ce_wall"]), axis=1
        )
        df["score_method"] = "STRUCTURAL"

        # Also compute velocity signals where available (non-zero change)
        df["pe_velocity_label"] = df["pe_pct_change"].apply(self._velocity_label_pe)
        df["ce_velocity_label"] = df["ce_pct_change"].apply(self._velocity_label_ce)

        return df

    # Kept for backward compatibility — routes to near scoring
    def score_chain(self, df: pd.DataFrame, dte: int) -> pd.DataFrame:
        """Backward-compatible: routes based on DTE. <5 DTE = near flow, else far structural."""
        if dte <= 5:
            return self.score_chain_near(df, dte)
        return self.score_chain_far(df, dte)

    # ─────────────────────────────────────────────────────────────────────────
    # Far expiry absolute OI scoring

    def _score_far_pe_oi(self, oi: float) -> int:
        """
        Score put OI by absolute level for far expiry.
        Large put OI = strong floor = positive (PE side protected).
        """
        if   oi >= FAR_OI_VERY_HIGH: return  3
        elif oi >= FAR_OI_HIGH:      return  2
        elif oi >= FAR_OI_MED:       return  1
        elif oi >= FAR_OI_LOW:       return  0
        else:                         return -1   # very thin — no floor

    def _score_far_ce_oi(self, oi: float) -> int:
        """
        Score call OI by absolute level for far expiry.
        Large call OI = strong ceiling = negative (CE side resistance).
        """
        if   oi >= FAR_OI_VERY_HIGH: return -3
        elif oi >= FAR_OI_HIGH:      return -2
        elif oi >= FAR_OI_MED:       return -1
        elif oi >= FAR_OI_LOW:       return  0
        else:                         return  1   # very thin ceiling — less resistance

    def _far_wall_strength(self, dominant_oi: float, weaker_oi: float, dte: int) -> int:
        """Wall strength for far expiry based on absolute OI levels."""
        if   dominant_oi >= FAR_OI_VERY_HIGH: base = 9
        elif dominant_oi >= FAR_OI_HIGH:      base = 7
        elif dominant_oi >= FAR_OI_MED:       base = 5
        elif dominant_oi >= FAR_OI_LOW:       base = 3
        else:                                  base = 1
        # DTE modifier
        score = base + self.get_wall_modifier(dte)
        return int(np.clip(score, 1, 10))

    def _velocity_label_pe(self, pct_change: float) -> str:
        """Plain language velocity label for PE side."""
        if   pct_change >  5:  return "FLOOR BUILDING"
        elif pct_change >  1:  return "Floor Growing"
        elif pct_change > -1:  return "Stable"
        elif pct_change > -5:  return "Floor Softening"
        else:                   return "FLOOR CRUMBLING"

    def _velocity_label_ce(self, pct_change: float) -> str:
        """Plain language velocity label for CE side."""
        if   pct_change >  5:  return "WALL BUILDING"
        elif pct_change >  1:  return "Wall Growing"
        elif pct_change > -1:  return "Stable"
        elif pct_change > -5:  return "Wall Softening"
        else:                   return "WALL CRUMBLING"

    # ─────────────────────────────────────────────────────────────────────────
    # DTE zone helpers

    def get_dte_multiplier(self, dte: int) -> float:
        if   dte > DTE_THETA_MIN: return 1.0
        elif dte >= DTE_WARN_MIN:  return 1.5
        else:                      return 2.0

    def get_wall_modifier(self, dte: int) -> int:
        if   dte > DTE_THETA_MIN: return +2
        elif dte >= DTE_WARN_MIN:  return  0
        else:                      return -2

    def dte_zone(self, dte: int) -> str:
        if   dte > DTE_THETA_MIN: return "THETA_BUFFER"
        elif dte >= DTE_WARN_MIN:  return "WARNING"
        else:                      return "GAMMA_DANGER"

    # ─────────────────────────────────────────────────────────────────────────
    # Near expiry flow scoring functions

    def score_pe_base(self, pct_change: float) -> int:
        if   pct_change >  OI_SCORE_HIGH:  return  3
        elif pct_change >  OI_SCORE_MED:   return  2
        elif pct_change >  OI_SCORE_LOW:   return  1
        elif pct_change > -OI_NOISE:       return  0
        elif pct_change > OI_UNWIND_HEAVY: return -1
        elif pct_change > OI_PANIC:        return -2
        else:                               return -3

    def score_ce_base(self, pct_change: float) -> int:
        if   pct_change >  OI_SCORE_HIGH:  return -3
        elif pct_change >  OI_SCORE_MED:   return -2
        elif pct_change >  OI_SCORE_LOW:   return -1
        elif pct_change > -OI_NOISE:       return  0
        elif pct_change > OI_UNWIND_HEAVY: return  1
        elif pct_change > OI_PANIC:        return  2
        else:                               return  3

    # ─────────────────────────────────────────────────────────────────────────
    # Wall strength (near expiry — flow-based)

    def wall_strength(self, dominant_oi: float, weaker_oi: float,
                      dominant_intraday_pct: float, dte: int) -> int:
        ratio = dominant_oi / weaker_oi if weaker_oi > 0 else 10.0
        if   ratio < WALL_RATIO_LOW: base = 3
        elif ratio < WALL_RATIO_MID: base = 5
        else:                        base = 8
        score = base + self.get_wall_modifier(dte)
        if   dominant_intraday_pct > WALL_INTRADAY_REINFORCE * 100: score += 2
        elif dominant_intraday_pct < WALL_INTRADAY_ABANDON:         score -= 3
        return int(np.clip(score, 1, 10))

    # ─────────────────────────────────────────────────────────────────────────
    # Position action

    def _position_action(self, net_score: float, pe_wall: int, ce_wall: int) -> str:
        ns = int(net_score)
        if   ns >= 3 and pe_wall >= 7:  return "HOLD_PE_CONFIDENT"
        elif ns >= 1 and pe_wall >= 4:  return "HOLD_PE_MONITOR"
        elif ns <= -1:                  return "REDUCE_PE_50PCT"
        elif ns <= -2 and pe_wall <= 3: return "EXIT_PE"
        elif ns <= -3 and ce_wall >= 7: return "HOLD_CE_CONFIDENT"
        elif ns <  0  and ce_wall >= 4: return "HOLD_CE_MONITOR"
        elif ns >= 1  and ce_wall <= 3: return "REDUCE_CE_50PCT"
        elif ns >= 3:                   return "EXIT_CE"
        return "BALANCED_IC"

    # ─────────────────────────────────────────────────────────────────────────
    # Convergence check

    def convergence_check(self, near_scored: pd.DataFrame,
                           far_scored: pd.DataFrame,
                           ce_strike: int, pe_strike: int) -> dict:
        def safe_get(df, strike, col):
            if df.empty or strike not in df.index: return 0
            return df.loc[strike, col] if col in df.columns else 0
        return {
            "pe_near_wall":     safe_get(near_scored, pe_strike, "pe_wall"),
            "pe_far_wall":      safe_get(far_scored,  pe_strike, "pe_wall"),
            "ce_near_wall":     safe_get(near_scored, ce_strike, "ce_wall"),
            "ce_far_wall":      safe_get(far_scored,  ce_strike, "ce_wall"),
            "pe_near_score":    safe_get(near_scored, pe_strike, "net_score"),
            "pe_far_score":     safe_get(far_scored,  pe_strike, "net_score"),
            "ce_near_score":    safe_get(near_scored, ce_strike, "net_score"),
            "ce_far_score":     safe_get(far_scored,  ce_strike, "net_score"),
            "pe_dual_fortress": (safe_get(near_scored, pe_strike, "pe_wall") >= 7 and
                                  safe_get(far_scored,  pe_strike, "pe_wall") >= 7),
            "ce_dual_fortress": (safe_get(near_scored, ce_strike, "ce_wall") >= 7 and
                                  safe_get(far_scored,  ce_strike, "ce_wall") >= 7),
        }
