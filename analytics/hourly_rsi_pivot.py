# analytics/hourly_rsi_pivot.py
# Hourly RSI with Higher Low (HL) / Lower High (LH) pivot detection and breakout signals

import pandas as pd
import numpy as np
from typing import Tuple, List, Dict


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI for a given series (typically close prices)."""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def detect_hl_lh_pivots(rsi_series: pd.Series, lookback: int = 3) -> pd.DataFrame:
    """
    Detect Higher Low (HL) and Lower High (LH) pivots in RSI.

    HL: Current RSI valley is higher than previous valley
    LH: Current RSI peak is lower than previous peak

    Returns DataFrame with columns:
      - pivot_type: 'HL' (Higher Low), 'LH' (Lower High), or None
      - pivot_value: RSI value at the pivot
      - is_broken: True if the pivot has been broken (exceeded for LH, fallen below for HL)
    """
    df = pd.DataFrame({
        'rsi': rsi_series,
        'pivot_type': None,
        'pivot_value': np.nan,
        'is_broken': False
    })

    rsi = rsi_series.values
    n = len(rsi)

    # Find local minima (valleys) and maxima (peaks)
    for i in range(lookback, n - lookback):
        if pd.isna(rsi[i]):
            continue

        # Check if it's a local minimum (valley)
        if all(rsi[i] <= rsi[j] for j in range(max(0, i - lookback), min(n, i + lookback + 1)) if j != i and not pd.isna(rsi[j])):
            df.loc[i, 'pivot_type'] = 'Valley'

        # Check if it's a local maximum (peak)
        if all(rsi[i] >= rsi[j] for j in range(max(0, i - lookback), min(n, i + lookback + 1)) if j != i and not pd.isna(rsi[j])):
            df.loc[i, 'pivot_type'] = 'Peak'

    # Now detect HL and LH
    valleys = df[df['pivot_type'] == 'Valley'].copy()
    peaks = df[df['pivot_type'] == 'Peak'].copy()

    if len(valleys) > 1:
        for idx, i in enumerate(valleys.index[1:], 1):
            prev_valley_idx = valleys.index[idx - 1]
            prev_valley_rsi = rsi[prev_valley_idx]
            curr_valley_rsi = rsi[i]

            if curr_valley_rsi > prev_valley_rsi:
                df.loc[i, 'pivot_type'] = 'HL'
                df.loc[i, 'pivot_value'] = curr_valley_rsi

    if len(peaks) > 1:
        for idx, i in enumerate(peaks.index[1:], 1):
            prev_peak_idx = peaks.index[idx - 1]
            prev_peak_rsi = rsi[prev_peak_idx]
            curr_peak_rsi = rsi[i]

            if curr_peak_rsi < prev_peak_rsi:
                df.loc[i, 'pivot_type'] = 'LH'
                df.loc[i, 'pivot_value'] = curr_peak_rsi

    # Mark if pivots are broken
    last_hl = None
    last_lh = None

    for i in range(len(df)):
        if df.loc[i, 'pivot_type'] == 'HL':
            last_hl = (i, df.loc[i, 'pivot_value'])
        elif df.loc[i, 'pivot_type'] == 'LH':
            last_lh = (i, df.loc[i, 'pivot_value'])
        else:
            # Check if recent pivot is broken
            if last_hl and i > last_hl[0]:
                if rsi[i] < last_hl[1]:
                    df.loc[last_hl[0], 'is_broken'] = True

            if last_lh and i > last_lh[0]:
                if rsi[i] > last_lh[1]:
                    df.loc[last_lh[0], 'is_broken'] = True

    return df


def get_breakout_signals(rsi_df: pd.DataFrame) -> List[Dict]:
    """
    Generate buy/sell signals when pivots are broken.

    Returns list of signals with:
      - index: candlestick index
      - signal: 'BUY' (LH broken UP) or 'SELL' (HL broken DOWN)
      - pivot_level: RSI level that was broken
      - rsi_at_signal: RSI value when signal triggered
    """
    signals = []

    rsi_values = rsi_df['rsi'].values
    pivot_types = rsi_df['pivot_type'].values
    pivot_values = rsi_df['pivot_value'].values

    last_lh = None
    last_hl = None
    last_lh_broken = False
    last_hl_broken = False

    for i in range(len(rsi_df)):
        curr_rsi = rsi_values[i]

        if pd.isna(curr_rsi):
            continue

        # Track last HL and LH
        if pivot_types[i] == 'HL':
            last_hl = (i, pivot_values[i])
            last_hl_broken = False
        elif pivot_types[i] == 'LH':
            last_lh = (i, pivot_values[i])
            last_lh_broken = False

        # Check for breakout signals
        if last_lh and not last_lh_broken:
            if curr_rsi > last_lh[1]:  # LH broken UP → BUY
                signals.append({
                    'index': i,
                    'signal': 'BUY',
                    'pivot_level': last_lh[1],
                    'rsi_at_signal': curr_rsi
                })
                last_lh_broken = True

        if last_hl and not last_hl_broken:
            if curr_rsi < last_hl[1]:  # HL broken DOWN → SELL
                signals.append({
                    'index': i,
                    'signal': 'SELL',
                    'pivot_level': last_hl[1],
                    'rsi_at_signal': curr_rsi
                })
                last_hl_broken = True

    return signals


def analyze_hourly_rsi(df: pd.DataFrame, rsi_period: int = 14, lookback: int = 3) -> Tuple[pd.DataFrame, List[Dict]]:
    """
    Main analysis function.

    Args:
        df: DataFrame with OHLCV data (must have 'close' column)
        rsi_period: RSI calculation period (default 14)
        lookback: Number of candles to look back for pivot detection

    Returns:
        (df_with_rsi_and_pivots, list_of_signals)
    """
    df = df.copy()

    # Calculate RSI
    df['rsi'] = calculate_rsi(df['close'], rsi_period)

    # Detect pivots
    pivot_df = detect_hl_lh_pivots(df['rsi'], lookback)
    df['pivot_type'] = pivot_df['pivot_type']
    df['pivot_value'] = pivot_df['pivot_value']
    df['pivot_broken'] = pivot_df['is_broken']

    # Generate signals
    signals = get_breakout_signals(df)

    return df, signals
