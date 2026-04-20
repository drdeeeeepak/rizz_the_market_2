# analytics/base_strategy.py
# Parent class for all analytics engines.
# Every analytics module inherits from BaseStrategy.

from abc import ABC, abstractmethod
import pandas as pd
import numpy as np


class BaseStrategy(ABC):
    """
    Abstract base class for all analytics engines.

    Contract:
        compute(df) → df with new indicator columns
        signals(df) → dict of named scalar signals for home page + pages
    """

    # ── Shared utility: EMA ───────────────────────────────────────────────────

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        """Exponential moving average (Wilder-style via ewm)."""
        return series.ewm(span=period, adjust=False).mean()

    # ── Shared utility: RSI ───────────────────────────────────────────────────

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """
        14-period RSI using Wilder's smoothing (ewm com=period-1).
        Matches TradingView and Kite chart RSI exactly.
        """
        delta = series.diff()
        gain  = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
        loss  = (-delta).clip(lower=0).ewm(com=period - 1, adjust=False).mean()
        rs    = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    # ── Shared utility: SMA ───────────────────────────────────────────────────

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(window=period).mean()

    # ── Shared utility: ATR ───────────────────────────────────────────────────

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        hl   = df["high"] - df["low"]
        hpc  = (df["high"] - df["close"].shift()).abs()
        lpc  = (df["low"]  - df["close"].shift()).abs()
        tr   = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
        return tr.ewm(com=period - 1, adjust=False).mean()

    # ── Shared utility: Bollinger Bands ──────────────────────────────────────

    @staticmethod
    def bollinger(series: pd.Series, period: int = 20, std: float = 2.0):
        """Returns (basis, upper, lower, bandwidth_pct)."""
        basis  = series.rolling(period).mean()
        sd     = series.rolling(period).std()
        upper  = basis + std * sd
        lower  = basis - std * sd
        bw_pct = (upper - lower) / basis * 100
        return basis, upper, lower, bw_pct

    # ── Shared utility: round to nearest strike ───────────────────────────────

    @staticmethod
    def round_strike(price: float, step: int = 50, direction: str = "nearest") -> int:
        """Round to nearest / floor / ceil Nifty strike."""
        if direction == "floor":
            return int(price // step) * step
        elif direction == "ceil":
            return int(-(-price // step)) * step
        else:
            return round(price / step) * step

    # ── Shared utility: safe percentage change ────────────────────────────────

    @staticmethod
    def pct_change_safe(new: float, old: float) -> float:
        if old == 0:
            return 0.0
        return (new - old) / abs(old) * 100

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add indicator columns to df and return it."""

    @abstractmethod
    def signals(self, df: pd.DataFrame) -> dict:
        """
        Return a dict of named scalars for the home page and the page UI.
        Must include 'kill_switches' key → dict of bool values.
        Must include 'home_score' key → int (contribution to 100-pt total).
        """
