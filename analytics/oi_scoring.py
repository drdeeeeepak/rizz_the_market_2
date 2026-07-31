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

# Far expiry OI thresholds — PERCENTILE RANK within the chain being scored,
# not absolute contract counts.
#
# These were absolute levels (5M / 2M / 1M / 300k contracts). That breaks in three
# ways: a monthly expiry carries far more OI than a weekly, so an entire weekly
# chain scored as "thin"; total market OI drifts over months, so the bands silently
# re-calibrate themselves; and the same strike could be the single biggest wall in
# its chain yet still score -1. What matters is whether a strike is big RELATIVE TO
# THE OTHER STRIKES in the same chain, which is exactly a percentile.
#
# Rank is computed per side (pe_oi and ce_oi separately) over the chain passed in.
FAR_PCTL_VERY_HIGH = 0.90   # top 10% of strikes in this chain — very strong wall
FAR_PCTL_HIGH      = 0.75   # top 25% — strong wall
FAR_PCTL_MED       = 0.50   # upper half — moderate wall
FAR_PCTL_LOW       = 0.25   # bottom quartile below this — thin positioning


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

        # Percentile rank within THIS chain, per side. pct=True gives 0..1.
        pe_rank = df["pe_oi"].rank(pct=True)
        ce_rank = df["ce_oi"].rank(pct=True)

        df["pe_base"] = pe_rank.apply(self._score_far_pe_rank)
        df["ce_base"] = ce_rank.apply(self._score_far_ce_rank)

        # For far expiry, no DTE panic multiplier on base scores
        # But still use % change for wall strength calculation
        df["pe_adj"]  = df["pe_base"].astype(float)
        df["ce_adj"]  = df["ce_base"].astype(float)

        df["net_score"] = (df["pe_adj"] + df["ce_adj"]).clip(-6, 6).round()

        # Wall strength from the same in-chain rank
        df["pe_wall"] = [self._far_wall_strength(r, dte) for r in pe_rank]
        df["ce_wall"] = [self._far_wall_strength(r, dte) for r in ce_rank]

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

    def _score_far_pe_rank(self, rank: float) -> int:
        """
        Score put OI by its percentile rank within this chain.
        Large put OI = strong floor = positive (PE side protected).
        """
        if   rank >= FAR_PCTL_VERY_HIGH: return  3
        elif rank >= FAR_PCTL_HIGH:      return  2
        elif rank >= FAR_PCTL_MED:       return  1
        elif rank >= FAR_PCTL_LOW:       return  0
        else:                            return -1   # very thin — no floor

    def _score_far_ce_rank(self, rank: float) -> int:
        """
        Score call OI by its percentile rank within this chain.
        Large call OI = strong ceiling = negative (CE side resistance).
        """
        if   rank >= FAR_PCTL_VERY_HIGH: return -3
        elif rank >= FAR_PCTL_HIGH:      return -2
        elif rank >= FAR_PCTL_MED:       return -1
        elif rank >= FAR_PCTL_LOW:       return  0
        else:                            return  1   # thin ceiling — less resistance

    def _far_wall_strength(self, rank: float, dte: int) -> int:
        """Wall strength (1-10) for far expiry from the strike's in-chain OI rank."""
        if   rank >= FAR_PCTL_VERY_HIGH: base = 9
        elif rank >= FAR_PCTL_HIGH:      base = 7
        elif rank >= FAR_PCTL_MED:       base = 5
        elif rank >= FAR_PCTL_LOW:       base = 3
        else:                            base = 1
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
        """
        Turn (net OI score, put-wall strength, call-wall strength) into one action.

        net_score sign convention, from score_pe_base / score_ce_base:
            POSITIVE = put writing dominant  → floor building → bullish drift
                       → the PE leg is well defended, the CE leg is the threatened one
            NEGATIVE = call writing dominant → ceiling building → bearish drift
                       → the CE leg is well defended, the PE leg is the threatened one

        So each branch first asks WHICH leg is under threat (sign of ns), then how
        well that leg is walled. The threatened leg always decides the action —
        a comfortable leg never overrides a leg that needs defending.

        The previous version was ordered so that `ns <= -1 → REDUCE_PE_50PCT` sat
        above the EXIT_PE / HOLD_CE_CONFIDENT / HOLD_CE_MONITOR branches, making all
        three unreachable: every negative score returned REDUCE_PE_50PCT and the CE
        side could never be recommended a hold. All nine outcomes are reachable now
        (verified by exhaustive enumeration over ns × pe_wall × ce_wall).
        """
        ns = int(net_score)

        # ── Bullish OI flow → CE leg is the threatened one ────────────────────
        if ns >= 3:
            if ce_wall <= 3:            return "EXIT_CE"
            if ce_wall <= 6:            return "REDUCE_CE_50PCT"
            return "HOLD_PE_CONFIDENT" if pe_wall >= 7 else "HOLD_PE_MONITOR"
        if ns >= 1:
            if ce_wall <= 3:            return "REDUCE_CE_50PCT"
            return "HOLD_PE_MONITOR" if pe_wall >= 4 else "BALANCED_IC"

        # ── Bearish OI flow → PE leg is the threatened one ────────────────────
        if ns <= -3:
            if pe_wall <= 3:            return "EXIT_PE"
            if pe_wall <= 6:            return "REDUCE_PE_50PCT"
            return "HOLD_CE_CONFIDENT" if ce_wall >= 7 else "HOLD_CE_MONITOR"
        if ns <= -1:
            if pe_wall <= 3:            return "REDUCE_PE_50PCT"
            return "HOLD_CE_MONITOR" if ce_wall >= 4 else "BALANCED_IC"

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
