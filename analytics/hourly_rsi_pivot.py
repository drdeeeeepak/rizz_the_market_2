# analytics/hourly_rsi_pivot.py
# Hourly RSI with Higher Low (HL) / Lower High (LH) pivot detection and breakout signals

import pandas as pd
import numpy as np
from typing import Tuple, List, Dict

try:
    import talib
    _HAS_TALIB = True
except ImportError:
    _HAS_TALIB = False
    import logging
    logging.warning("TA-Lib not installed, using fallback Wilder's smoothing")


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI using TA-Lib if available, else Wilder's smoothing."""
    if _HAS_TALIB:
        try:
            rsi = talib.RSI(series.values, timeperiod=period)
            return pd.Series(rsi, index=series.index)
        except Exception as e:
            import logging
            logging.warning(f"TA-Lib RSI failed ({e}), using fallback")
            pass

    # Fallback: Wilder's smoothing (manual)
    delta = series.diff().values
    gains = np.where(delta > 0, delta, 0)
    losses = np.where(delta < 0, -delta, 0)

    avg_gain = np.zeros_like(delta, dtype=float)
    avg_loss = np.zeros_like(delta, dtype=float)

    if len(gains) >= period:
        avg_gain[period - 1] = np.mean(gains[:period])
        avg_loss[period - 1] = np.mean(losses[:period])

    for i in range(period, len(delta)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i]) / period

    with np.errstate(divide='ignore', invalid='ignore'):
        rs = avg_gain / np.where(avg_loss != 0, avg_loss, np.nan)
        rsi = 100 - (100 / (1 + rs))

    return pd.Series(rsi, index=series.index)


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
            df.iloc[i, df.columns.get_loc('pivot_type')] = 'Valley'

        # Check if it's a local maximum (peak)
        if all(rsi[i] >= rsi[j] for j in range(max(0, i - lookback), min(n, i + lookback + 1)) if j != i and not pd.isna(rsi[j])):
            df.iloc[i, df.columns.get_loc('pivot_type')] = 'Peak'

    # Now detect HL and LH
    valley_indices = np.where(df['pivot_type'] == 'Valley')[0]
    peak_indices = np.where(df['pivot_type'] == 'Peak')[0]

    if len(valley_indices) > 1:
        for idx in range(1, len(valley_indices)):
            prev_i = valley_indices[idx - 1]
            curr_i = valley_indices[idx]
            prev_valley_rsi = rsi[prev_i]
            curr_valley_rsi = rsi[curr_i]

            if curr_valley_rsi > prev_valley_rsi:
                df.iloc[curr_i, df.columns.get_loc('pivot_type')] = 'HL'
                df.iloc[curr_i, df.columns.get_loc('pivot_value')] = curr_valley_rsi

    if len(peak_indices) > 1:
        for idx in range(1, len(peak_indices)):
            prev_i = peak_indices[idx - 1]
            curr_i = peak_indices[idx]
            prev_peak_rsi = rsi[prev_i]
            curr_peak_rsi = rsi[curr_i]

            if curr_peak_rsi < prev_peak_rsi:
                df.iloc[curr_i, df.columns.get_loc('pivot_type')] = 'LH'
                df.iloc[curr_i, df.columns.get_loc('pivot_value')] = curr_peak_rsi

    # Mark if pivots are broken
    last_hl = None
    last_lh = None

    for i in range(len(df)):
        ptype = df.iloc[i]['pivot_type']
        if ptype == 'HL':
            last_hl = (i, df.iloc[i]['pivot_value'])
        elif ptype == 'LH':
            last_lh = (i, df.iloc[i]['pivot_value'])
        else:
            # Check if recent pivot is broken
            if last_hl and i > last_hl[0]:
                if rsi[i] < last_hl[1]:
                    df.iloc[last_hl[0], df.columns.get_loc('is_broken')] = True

            if last_lh and i > last_lh[0]:
                if rsi[i] > last_lh[1]:
                    df.iloc[last_lh[0], df.columns.get_loc('is_broken')] = True

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


def backtest_rsi_pivots(df: pd.DataFrame, rsi_period: int = 14, lookback: int = 3) -> pd.DataFrame:
    """
    Backtest the RSI pivot strategy.

    Returns DataFrame with backtest results:
      - signal_type: 'BUY' or 'SELL'
      - signal_time: timestamp of signal
      - signal_price: price at signal
      - signal_rsi: RSI at signal
      - pivot_level: HL/LH pivot level
      - exit_time: when position closed
      - exit_price: close price
      - pnl_pts: profit/loss in points
      - pnl_pct: profit/loss in percent
      - bars_held: number of bars in position
    """
    df = df.copy()

    # Analyze
    df, signals = analyze_hourly_rsi(df, rsi_period, lookback)

    if not signals:
        return pd.DataFrame()

    backtest_results = []

    for i, signal in enumerate(signals):
        signal_idx = signal['index']
        signal_time = df.index[signal_idx]
        signal_type = signal['signal']
        signal_price = df['close'].iloc[signal_idx]
        signal_rsi = signal['rsi_at_signal']
        pivot_level = signal['pivot_level']

        # Find next opposite signal or end of data
        next_signal_idx = None
        for j in range(i + 1, len(signals)):
            if signals[j]['index'] > signal_idx:
                if (signal_type == 'BUY' and signals[j]['signal'] == 'SELL') or \
                   (signal_type == 'SELL' and signals[j]['signal'] == 'BUY'):
                    next_signal_idx = signals[j]['index']
                    break

        # If no opposite signal, close at last candle
        if next_signal_idx is None:
            next_signal_idx = len(df) - 1

        exit_time = df.index[next_signal_idx]
        exit_price = df['close'].iloc[next_signal_idx]

        # Calculate P&L
        if signal_type == 'BUY':
            pnl_pts = exit_price - signal_price
            pnl_pct = (pnl_pts / signal_price) * 100 if signal_price != 0 else 0
        else:  # SELL
            pnl_pts = signal_price - exit_price
            pnl_pct = (pnl_pts / signal_price) * 100 if signal_price != 0 else 0

        bars_held = next_signal_idx - signal_idx

        backtest_results.append({
            'signal_type': signal_type,
            'signal_time': signal_time,
            'signal_price': signal_price,
            'signal_rsi': signal_rsi,
            'pivot_level': pivot_level,
            'exit_time': exit_time,
            'exit_price': exit_price,
            'pnl_pts': pnl_pts,
            'pnl_pct': pnl_pct,
            'bars_held': bars_held
        })

    result_df = pd.DataFrame(backtest_results)
    return result_df


def backtest_stats(backtest_df: pd.DataFrame) -> Dict:
    """Calculate backtest statistics."""
    if backtest_df.empty:
        return {}

    total_trades = len(backtest_df)
    winning_trades = (backtest_df['pnl_pct'] > 0).sum()
    losing_trades = (backtest_df['pnl_pct'] < 0).sum()
    total_pnl_pct = backtest_df['pnl_pct'].sum()
    avg_pnl_pct = backtest_df['pnl_pct'].mean()
    max_win = backtest_df['pnl_pct'].max()
    max_loss = backtest_df['pnl_pct'].min()
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

    return {
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'total_pnl_pct': total_pnl_pct,
        'avg_pnl_pct': avg_pnl_pct,
        'max_win_pct': max_win,
        'max_loss_pct': max_loss,
    }
