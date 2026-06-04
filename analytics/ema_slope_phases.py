# analytics/ema_slope_phases.py
# 5-Phase EMA Slope Trend Classification Engine — 60-Min Nifty 50
#
# Classifies the bar-to-bar slope of EMA-20 into 5 phases using
# ATR-14-scaled dynamic thresholds (K1, K2).
#
# Public API:
#   calculate_hourly_ema_slope_phases(df, m1, m2) → df with Slope_Phase column
#   EMASlopePhasesEngine().compute(df)             → same as above
#   EMASlopePhasesEngine().signals(df)             → scalar dict for dashboard

import logging

import numpy as np
import pandas as pd

from analytics.base_strategy import BaseStrategy
from config import (
    EMA_SLOPE_EMA_PERIOD,
    EMA_SLOPE_ATR_PERIOD,
    EMA_SLOPE_M1,
    EMA_SLOPE_M2,
)

log = logging.getLogger(__name__)

# Phase integer → human label
PHASE_LABELS = {
    1: "Phase 1 — Strongly Bullish",
    2: "Phase 2 — Mildly Bullish",
    3: "Phase 3 — Flat / Neutral",
    4: "Phase 4 — Mildly Bearish",
    5: "Phase 5 — Strongly Bearish",
}

# Phase integer → hex colour (used by Streamlit page)
PHASE_COLORS = {
    1: "#00C853",
    2: "#69F0AE",
    3: "#FFD600",
    4: "#FF6D00",
    5: "#D50000",
}

# Deployment guidance per phase
PHASE_DEPLOYMENT = {
    1: "Skewed — defend CE leg; widen PE distance",
    2: "Mild bullish lean — balanced IC with slight CE buffer",
    3: "Non-directional — balanced Iron Condor deployment",
    4: "Mild bearish lean — balanced IC with slight PE buffer",
    5: "Skewed — defend PE leg; widen CE distance",
}


# ══════════════════════════════════════════════════════════════════════════════
# Standalone utility function  (primary public API)
# ══════════════════════════════════════════════════════════════════════════════

def calculate_hourly_ema_slope_phases(
    df: pd.DataFrame,
    m1: float = EMA_SLOPE_M1,
    m2: float = EMA_SLOPE_M2,
    ema_period: int = EMA_SLOPE_EMA_PERIOD,
    atr_period: int = EMA_SLOPE_ATR_PERIOD,
) -> pd.DataFrame:
    """
    Append EMA slope phase columns to a 60-min OHLCV DataFrame.

    Parameters
    ----------
    df         : DataFrame with columns [open, high, low, close, volume]
    m1         : significance threshold multiplier  (K1 = m1 × ATR_14)
                 Lower to 0.02 to tighten the neutral zone (fewer Phase 3 bars).
    m2         : acceleration threshold multiplier  (K2 = m2 × ATR_14)
                 Lower to 0.08 to catch explosive moves earlier as Phase 1/5.
    ema_period : EMA window (default 20)
    atr_period : ATR window (default 14, Wilder smoothing)

    Returns
    -------
    DataFrame copy with added columns:
        ema_20      — 20-period EMA of close
        ema_slope   — bar-to-bar EMA change  (Raw Slope = EMA(t) − EMA(t-1))
        atr_14      — 14-period ATR (Wilder)
        k1          — significance threshold  (m1 × ATR_14)
        k2          — acceleration threshold  (m2 × ATR_14)
        Slope_Phase — integer 1–5  (NaN during warm-up rows)

    Phase definitions
    -----------------
        1  Strongly Bullish  slope > K2
        2  Mildly Bullish    K1 < slope ≤ K2
        3  Flat / Neutral    −K1 ≤ slope ≤ K1
        4  Mildly Bearish    −K2 ≤ slope < −K1
        5  Strongly Bearish  slope < −K2

    Notes
    -----
    * All calculations are fully vectorised (no Python loops).
    * ATR uses Wilder's smoothing (ewm com = period − 1) — identical to
      base_strategy.BaseStrategy.atr() used throughout the codebase.
    * The final shortened NSE candle (3:15–3:29 session close) does NOT
      break continuity: ewm smoothing absorbs narrow true-range bars
      gracefully without throwing errors or distorting the ATR series.
    * Warm-up rows (first bar for slope, first bar for ATR) receive NaN
      for Slope_Phase and are safe to dropna() before display.
    """
    if df.empty:
        return df.copy()

    df = df.copy()

    # ── EMA-20 on close ──────────────────────────────────────────────────────
    df["ema_20"] = df["close"].ewm(span=ema_period, adjust=False).mean()

    # ── Raw Slope: EMA(t) − EMA(t-1) ────────────────────────────────────────
    df["ema_slope"] = df["ema_20"].diff()

    # ── ATR-14 (Wilder smoothing = ewm com=period−1) ─────────────────────────
    hl  = df["high"] - df["low"]
    hpc = (df["high"] - df["close"].shift()).abs()
    lpc = (df["low"]  - df["close"].shift()).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    df["atr_14"] = tr.ewm(com=atr_period - 1, adjust=False).mean()

    # ── Dynamic thresholds ───────────────────────────────────────────────────
    df["k1"] = m1 * df["atr_14"]
    df["k2"] = m2 * df["atr_14"]

    s  = df["ema_slope"]
    k1 = df["k1"]
    k2 = df["k2"]

    # ── Vectorised phase classification via np.select ────────────────────────
    conditions = [
        s > k2,                           # Phase 1: Strongly Bullish
        (s > k1) & (s <= k2),             # Phase 2: Mildly Bullish
        (s >= -k1) & (s <= k1),           # Phase 3: Flat / Neutral
        (s >= -k2) & (s < -k1),           # Phase 4: Mildly Bearish
        s < -k2,                          # Phase 5: Strongly Bearish
    ]
    choices = [1, 2, 3, 4, 5]

    raw = np.select(conditions, choices, default=np.nan)

    # Preserve NaN during indicator warm-up (first bar of slope/ATR is always NaN)
    warm_up = df["ema_slope"].isna() | df["atr_14"].isna()
    raw     = raw.astype(float)
    raw[warm_up.values] = np.nan

    df["Slope_Phase"] = raw
    return df


# ══════════════════════════════════════════════════════════════════════════════
# Engine class (BaseStrategy interface)
# ══════════════════════════════════════════════════════════════════════════════

class EMASlopePhasesEngine(BaseStrategy):
    """
    5-Phase EMA Slope Trend Classification Engine.

    Designed for 60-min Nifty 50 data to guide weekly option selling:
      Phase 3 (Flat)      → non-directional balanced IC deployment
      Phase 1/5 (Strong)  → skewed defenses or standby
    """

    def __init__(
        self,
        m1: float = EMA_SLOPE_M1,
        m2: float = EMA_SLOPE_M2,
        ema_period: int = EMA_SLOPE_EMA_PERIOD,
        atr_period: int = EMA_SLOPE_ATR_PERIOD,
    ):
        self.m1         = m1
        self.m2         = m2
        self.ema_period = ema_period
        self.atr_period = atr_period

    # ── BaseStrategy interface ────────────────────────────────────────────────

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add ema_20, ema_slope, atr_14, k1, k2, Slope_Phase columns."""
        return calculate_hourly_ema_slope_phases(
            df,
            m1=self.m1, m2=self.m2,
            ema_period=self.ema_period, atr_period=self.atr_period,
        )

    def signals(self, df: pd.DataFrame) -> dict:
        """
        Return scalar signals dict for dashboard/compute_signals integration.

        Keys:
            phase          int 1–5
            phase_label    str
            phase_deploy   str (deployment guidance)
            slope          float (current raw slope, rounded)
            k1             float (current K1 threshold)
            k2             float (current K2 threshold)
            atr_14         float (current ATR-14)
            ema_20         float (current EMA-20 value)
            streak_bars    int (consecutive bars in current phase)
            phase_pct_20   dict {phase_int: pct_of_last_20_bars}
            kill_switches  dict (empty — this engine does not veto)
            home_score     int  (0 — informational lens, not scored)
        """
        df = self.compute(df.copy())
        if df.empty or "Slope_Phase" not in df.columns:
            return self._empty_signals()

        valid = df.dropna(subset=["Slope_Phase"])
        if valid.empty:
            return self._empty_signals()

        last           = valid.iloc[-1]
        current_phase  = int(last["Slope_Phase"])
        current_slope  = float(last["ema_slope"])
        current_k1     = float(last["k1"])
        current_k2     = float(last["k2"])
        current_atr    = float(last["atr_14"])
        current_ema20  = float(last["ema_20"])

        # Phase distribution over last 20 confirmed bars
        recent       = valid.tail(20)
        phase_counts = recent["Slope_Phase"].value_counts().to_dict()
        total        = len(recent)
        phase_pct    = {int(k): round(v / total * 100) for k, v in phase_counts.items()}

        # Consecutive bars in current phase (streak)
        phases_rev = valid["Slope_Phase"].iloc[::-1].values
        streak     = int(np.cumprod(phases_rev == current_phase).sum())

        return {
            "phase":         current_phase,
            "phase_label":   PHASE_LABELS.get(current_phase, "Unknown"),
            "phase_deploy":  PHASE_DEPLOYMENT.get(current_phase, ""),
            "slope":         round(current_slope, 4),
            "k1":            round(current_k1, 4),
            "k2":            round(current_k2, 4),
            "atr_14":        round(current_atr, 2),
            "ema_20":        round(current_ema20, 2),
            "streak_bars":   streak,
            "phase_pct_20":  phase_pct,
            "kill_switches": {},
            "home_score":    0,
        }

    # ── Internal ─────────────────────────────────────────────────────────────

    @staticmethod
    def _empty_signals() -> dict:
        return {
            "phase": 3, "phase_label": "Phase 3 — Flat / Neutral",
            "phase_deploy": PHASE_DEPLOYMENT[3],
            "slope": 0.0, "k1": 0.0, "k2": 0.0,
            "atr_14": 0.0, "ema_20": 0.0,
            "streak_bars": 0, "phase_pct_20": {},
            "kill_switches": {}, "home_score": 0,
        }
