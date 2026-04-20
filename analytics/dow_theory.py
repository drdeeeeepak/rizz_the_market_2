# analytics/dow_theory.py
# Dow Theory+ Pivot Engine
# Detects swing highs/lows, classifies market structure,
# derives breach trigger levels for IC position management.

import pandas as pd
import numpy as np
from analytics.base_strategy import BaseStrategy
from config import DOW_PIVOT_LOOKBACK, DOW_PIVOT_BREACH_PCT


class DowTheoryEngine(BaseStrategy):
    """
    Identifies structural pivot highs and lows (Dow Theory+).
    Breach levels = 0.5% beyond the most recent structural pivot.
    Used by Home page for sustain logic and breach monitoring.
    """

    LOOKBACK = DOW_PIVOT_LOOKBACK   # bars each side for swing detection

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add pivot_high, pivot_low, structure columns."""
        df = df.copy()
        n  = self.LOOKBACK

        # Swing High: high[i] > high[i-n..i-1] AND high[i] > high[i+1..i+n]
        df["pivot_high"] = False
        df["pivot_low"]  = False

        for i in range(n, len(df) - n):
            hi = df["high"].iloc[i]
            lo = df["low"].iloc[i]
            # Use >= / <= not == — exact equality almost never occurs with float prices
            if (hi >= df["high"].iloc[i-n:i].max() and
                    hi >= df["high"].iloc[i+1:i+n+1].max()):
                df.iloc[i, df.columns.get_loc("pivot_high")] = True
            if (lo <= df["low"].iloc[i-n:i].min() and
                    lo <= df["low"].iloc[i+1:i+n+1].min()):
                df.iloc[i, df.columns.get_loc("pivot_low")] = True

        # Tag each pivot with price level
        df["ph_level"] = np.where(df["pivot_high"], df["high"], np.nan)
        df["pl_level"] = np.where(df["pivot_low"],  df["low"],  np.nan)

        return df

    def signals(self, df: pd.DataFrame) -> dict:
        df  = self.compute(df.copy())
        sig = self._classify_structure(df)
        sig.update(self._breach_levels(df))
        sig.update(self._home_score_contribution(sig))
        sig["kill_switches"] = {}
        return sig

    # ── Structure classification ──────────────────────────────────────────────

    def _classify_structure(self, df: pd.DataFrame) -> dict:
        """Classify market as uptrend, downtrend, or mixed using last 4 pivots."""
        ph = df.dropna(subset=["ph_level"])["ph_level"].tail(3).values
        pl = df.dropna(subset=["pl_level"])["pl_level"].tail(3).values

        structure = "MIXED"
        if len(ph) >= 2 and len(pl) >= 2:
            hh = ph[-1] > ph[-2]      # higher high
            hl = pl[-1] > pl[-2]      # higher low
            lh = ph[-1] < ph[-2]      # lower high
            ll = pl[-1] < pl[-2]      # lower low

            if hh and hl:
                structure = "UPTREND"
            elif lh and ll:
                structure = "DOWNTREND"
            elif hh and ll:
                structure = "MIXED_BULL_DIVERGE"
            elif lh and hl:
                structure = "MIXED_BEAR_DIVERGE"

        last_ph = float(df.dropna(subset=["ph_level"])["ph_level"].iloc[-1]) if df["ph_level"].notna().any() else 0.0
        last_pl = float(df.dropna(subset=["pl_level"])["pl_level"].iloc[-1]) if df["pl_level"].notna().any() else 0.0

        return {
            "dow_structure":    structure,
            "last_pivot_high":  round(last_ph, 0),
            "last_pivot_low":   round(last_pl, 0),
            "uptrend":          structure == "UPTREND",
            "downtrend":        structure == "DOWNTREND",
        }

    # ── Breach trigger levels ─────────────────────────────────────────────────

    def _breach_levels(self, df: pd.DataFrame) -> dict:
        """
        Put breach level = 0.5% below most recent structural pivot low (daily HL).
        Call breach level = 0.5% above most recent structural pivot high (daily LH).
        """
        ph_series = df.dropna(subset=["ph_level"])["ph_level"]
        pl_series = df.dropna(subset=["pl_level"])["pl_level"]

        last_ph = float(ph_series.iloc[-1]) if len(ph_series) > 0 else float(df["high"].iloc[-1])
        last_pl = float(pl_series.iloc[-1]) if len(pl_series) > 0 else float(df["low"].iloc[-1])

        put_breach  = round(last_pl  * (1 - DOW_PIVOT_BREACH_PCT), 0)
        call_breach = round(last_ph  * (1 + DOW_PIVOT_BREACH_PCT), 0)

        return {
            "put_breach_level":  put_breach,
            "call_breach_level": call_breach,
            "pivot_low_ref":     round(last_pl, 0),
            "pivot_high_ref":    round(last_ph, 0),
        }

    def _home_score_contribution(self, sig: dict) -> dict:
        """Structural clarity bonus for IC selection."""
        score = 0
        if sig["dow_structure"] == "UPTREND":
            score = 5
        elif sig["dow_structure"] == "DOWNTREND":
            score = 5
        elif sig["dow_structure"] == "MIXED":
            score = 2
        else:
            score = 3
        return {"home_score": score}

    # ── Get recent pivots list for charting ───────────────────────────────────

    def get_pivot_series(self, df: pd.DataFrame) -> tuple:
        """Returns (highs_series, lows_series) for chart overlay."""
        df = self.compute(df.copy())
        return df["ph_level"], df["pl_level"]
