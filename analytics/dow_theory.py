# analytics/dow_theory.py — v2 (22 April 2026)
# Dow Theory+ Pivot Engine
#
# LOCKED CHANGES (per premiumdecay_locked_rules_22Apr2026_1600IST.docx Section 2):
#   - Three pivot windows: Recent N=3, Intermediate N=7, Structural N=15
#   - Breach levels from RECENT pivots ONLY (N=3)
#   - Buffer: 50 fixed points (NOT percentage — old 0.5% replaced)
#   - Breach confirmation: daily close basis only (not intraday)
#   - Proximity warning: spot within 1/3 of ATR14 from recent pivot
#   - Staleness flag: most recent pivot > 10 trading days old

import pandas as pd
import numpy as np
from datetime import date
from analytics.base_strategy import BaseStrategy

# LOCKED constants
BREACH_BUFFER_PTS   = 50     # fixed points both sides
PROXIMITY_FRAC      = 1/3    # within 1/3 of ATR14 from pivot = proximity warning
STALENESS_DAYS      = 10     # trading days — if no pivot in this window, flag stale


class DowTheoryEngine(BaseStrategy):
    """
    Three-window pivot detection.
    Breach levels from recent (N=3) pivots only.
    50pt fixed buffer on daily close basis.
    Proximity warning + staleness flag.
    """

    # Three lookback windows
    N_RECENT       = 3
    N_INTERMEDIATE = 7
    N_STRUCTURAL   = 15

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute pivot highs and lows for all three windows."""
        df = df.copy()
        for n, suffix in [(self.N_RECENT, "_r"), (self.N_INTERMEDIATE, "_i"), (self.N_STRUCTURAL, "_s")]:
            df[f"pivot_high{suffix}"] = False
            df[f"pivot_low{suffix}"]  = False
            for i in range(n, len(df) - n):
                hi = df["high"].iloc[i]
                lo = df["low"].iloc[i]
                if (hi >= df["high"].iloc[i-n:i].max() and
                        hi >= df["high"].iloc[i+1:i+n+1].max()):
                    df.iloc[i, df.columns.get_loc(f"pivot_high{suffix}")] = True
                if (lo <= df["low"].iloc[i-n:i].min() and
                        lo <= df["low"].iloc[i+1:i+n+1].min()):
                    df.iloc[i, df.columns.get_loc(f"pivot_low{suffix}")] = True

            df[f"ph_level{suffix}"] = np.where(df[f"pivot_high{suffix}"], df["high"], np.nan)
            df[f"pl_level{suffix}"] = np.where(df[f"pivot_low{suffix}"],  df["low"],  np.nan)

        return df

    def signals(self, df: pd.DataFrame, atr14: float = 200.0) -> dict:
        df  = self.compute(df.copy())

        # Structure from structural window (N=15) — for IC shape classification
        structure_sig = self._classify_structure(df, suffix="_s")

        # Breach levels from recent window (N=3) ONLY
        breach_sig    = self._breach_levels(df, suffix="_r")

        # Proximity and staleness from recent window
        proximity_sig = self._proximity_and_staleness(df, breach_sig, atr14)

        # Recent and intermediate pivots for display
        display_sig   = self._pivot_display(df)

        score = self._home_score_contribution(structure_sig)
        sig = {
            **structure_sig,
            **breach_sig,
            **proximity_sig,
            **display_sig,
            **score,
            "kill_switches": {},
        }
        return sig

    # ── Structure classification (from structural N=15 pivots) ───────────────

    def _classify_structure(self, df: pd.DataFrame, suffix: str) -> dict:
        """HH/HL/LH/LL from last 3 pivots in the given window."""
        ph_col = f"ph_level{suffix}"
        pl_col = f"pl_level{suffix}"

        ph = df.dropna(subset=[ph_col])[ph_col].tail(3).values
        pl = df.dropna(subset=[pl_col])[pl_col].tail(3).values

        structure = "MIXED"
        if len(ph) >= 2 and len(pl) >= 2:
            hh = ph[-1] > ph[-2]
            hl = pl[-1] > pl[-2]
            lh = ph[-1] < ph[-2]
            ll = pl[-1] < pl[-2]
            if hh and hl:   structure = "UPTREND"
            elif lh and ll: structure = "DOWNTREND"
            elif hh and ll: structure = "MIXED_BULL_DIVERGE"
            elif lh and hl: structure = "MIXED_BEAR_DIVERGE"

        last_ph_s = float(df.dropna(subset=[ph_col])[ph_col].iloc[-1]) \
                    if df[ph_col].notna().any() else 0.0
        last_pl_s = float(df.dropna(subset=[pl_col])[pl_col].iloc[-1]) \
                    if df[pl_col].notna().any() else 0.0

        return {
            "dow_structure":        structure,
            "last_pivot_high":      round(last_ph_s, 0),   # structural — for IC shape display
            "last_pivot_low":       round(last_pl_s, 0),
            "uptrend":              structure == "UPTREND",
            "downtrend":            structure == "DOWNTREND",
        }

    # ── Breach levels (from recent N=3 pivots ONLY) ──────────────────────────

    def _breach_levels(self, df: pd.DataFrame, suffix: str) -> dict:
        """
        LOCKED: Breach = recent pivot ± 50 fixed points.
        Confirmation on daily close basis only.
        """
        ph_col = f"ph_level{suffix}"
        pl_col = f"pl_level{suffix}"

        ph_series = df.dropna(subset=[ph_col])[ph_col]
        pl_series = df.dropna(subset=[pl_col])[pl_col]

        last_ph_r = float(ph_series.iloc[-1]) if len(ph_series) > 0 else float(df["high"].iloc[-1])
        last_pl_r = float(pl_series.iloc[-1]) if len(pl_series) > 0 else float(df["low"].iloc[-1])

        # LOCKED: 50 fixed pts buffer — NOT percentage
        put_breach  = round(last_pl_r - BREACH_BUFFER_PTS, 0)
        call_breach = round(last_ph_r + BREACH_BUFFER_PTS, 0)

        # Check if today's CLOSE has breached (not intraday)
        last_close  = float(df["close"].iloc[-1])
        put_breached  = last_close < put_breach
        call_breached = last_close > call_breach

        return {
            "put_breach_level":    put_breach,
            "call_breach_level":   call_breach,
            "pivot_low_ref":       round(last_pl_r, 0),   # recent pivot
            "pivot_high_ref":      round(last_ph_r, 0),
            "put_breach_active":   put_breached,
            "call_breach_active":  call_breached,
            "breach_note":         "Close-basis only. Intraday wick through pivot is NOT a breach.",
        }

    # ── Proximity warning and staleness flag ─────────────────────────────────

    def _proximity_and_staleness(self, df: pd.DataFrame, breach: dict,
                                  atr14: float) -> dict:
        """
        Proximity warning: spot within 1/3 of ATR14 from recent pivot.
        Staleness flag: no confirmed pivot in any window for > 10 trading days.
        """
        last_close  = float(df["close"].iloc[-1])
        prox_thresh = atr14 * PROXIMITY_FRAC

        pivot_low_r  = breach["pivot_low_ref"]
        pivot_high_r = breach["pivot_high_ref"]

        pe_proximity  = pivot_low_r > 0 and (last_close - pivot_low_r) < prox_thresh
        ce_proximity  = pivot_high_r > 0 and (pivot_high_r - last_close) < prox_thresh

        # Staleness: find index of most recent pivot across all three windows
        most_recent_pivot_idx = 0
        for suffix in ["_r", "_i", "_s"]:
            for col in [f"ph_level{suffix}", f"pl_level{suffix}"]:
                if col in df.columns:
                    notna_idx = df[col].dropna().index
                    if len(notna_idx) > 0:
                        try:
                            # Get position of last pivot
                            last_pos = df.index.get_loc(notna_idx[-1])
                            most_recent_pivot_idx = max(most_recent_pivot_idx, last_pos)
                        except Exception:
                            pass

        bars_since_pivot = len(df) - 1 - most_recent_pivot_idx
        stale = bars_since_pivot > STALENESS_DAYS

        return {
            "pe_proximity_warning":  pe_proximity,
            "ce_proximity_warning":  ce_proximity,
            "pivot_proximity_pts_pe": round(last_close - pivot_low_r,  0) if pivot_low_r  > 0 else 0,
            "pivot_proximity_pts_ce": round(pivot_high_r - last_close, 0) if pivot_high_r > 0 else 0,
            "pivot_staleness_flag":  stale,
            "bars_since_pivot":      bars_since_pivot,
            "staleness_note":        f"No pivot confirmed in {bars_since_pivot} trading days — structural reference unreliable." if stale else "",
        }

    # ── Pivot data for display ───────────────────────────────────────────────

    def _pivot_display(self, df: pd.DataFrame) -> dict:
        """Recent and intermediate pivot levels for chart overlay."""
        def last_val(col):
            s = df.dropna(subset=[col])[col]
            return float(s.iloc[-1]) if len(s) > 0 else 0.0

        return {
            "recent_pivot_high":       round(last_val("ph_level_r"), 0),
            "recent_pivot_low":        round(last_val("pl_level_r"),  0),
            "intermediate_pivot_high": round(last_val("ph_level_i"), 0),
            "intermediate_pivot_low":  round(last_val("pl_level_i"),  0),
            "structural_pivot_high":   round(last_val("ph_level_s"), 0),
            "structural_pivot_low":    round(last_val("pl_level_s"),  0),
        }

    # ── Home score ───────────────────────────────────────────────────────────

    def _home_score_contribution(self, sig: dict) -> dict:
        score = 0
        if   sig["dow_structure"] == "UPTREND":   score = 5
        elif sig["dow_structure"] == "DOWNTREND":  score = 5
        elif sig["dow_structure"] == "MIXED":       score = 2
        else:                                       score = 3
        return {"home_score": score}

    # ── Chart overlay helper ─────────────────────────────────────────────────

    def get_pivot_series(self, df: pd.DataFrame) -> tuple:
        """Returns (recent_highs, recent_lows) for chart overlay."""
        df = self.compute(df.copy())
        return df["ph_level_r"], df["pl_level_r"]
