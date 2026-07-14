# analytics/rsi_fade_backtest.py
# Backtest for page 28 — fade hourly / 30-minute RSI overbought-oversold extremes.
#
# Thesis being tested: Nifty tends to run one-sided for ~3-6 trading days, then
# reverse for a similar stretch. An intraday RSI extreme (hourly/30m) sitting near
# day 3-5 of that run is a candidate turning-point signal — this module answers
# whether fading it (short on overbought, long on oversold) actually pays, at
# which timeframe, and at which OB/OS thresholds.
#
# One position at a time (no pyramiding). A new signal while a trade is open is
# skipped — mirrors a real swing trader who can only hold one position on this
# setup. Entry fills at the signal bar's CLOSE (same fill assumption used
# elsewhere in this repo, e.g. reversal_backtest's trigger-close entries).

import numpy as np
import pandas as pd

from analytics.base_strategy import BaseStrategy

_rsi = BaseStrategy.rsi   # Wilder's RSI — matches TradingView / Kite charts


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    return d[["open", "high", "low", "close"]].astype(float).sort_index()


def compute_rsi(df: pd.DataFrame, rsi_period: int = 14) -> pd.DataFrame:
    d = _norm(df)
    d["rsi"] = _rsi(d["close"], rsi_period)
    return d


def _entry_signals(d: pd.DataFrame, ob: float, os_: float, entry_mode: str) -> pd.DataFrame:
    """
    entry_mode:
      "touch"     — fires the bar RSI first crosses INTO the zone (>=ob or <=os_).
      "zone_exit" — fires the bar RSI crosses back OUT of the zone. More conservative:
                    during a strong one-sided run RSI can sit pinned at an extreme for
                    a day or two before actually turning, so "touch" risks entering too
                    early and eating that continuation.
    """
    d = d.copy()
    rsi = d["rsi"]
    prev = rsi.shift(1)
    if entry_mode == "touch":
        d["short_signal"] = ((prev < ob) & (rsi >= ob)).fillna(False)
        d["long_signal"] = ((prev > os_) & (rsi <= os_)).fillna(False)
    else:  # zone_exit
        d["short_signal"] = ((prev >= ob) & (rsi < ob)).fillna(False)
        d["long_signal"] = ((prev <= os_) & (rsi > os_)).fillna(False)
    return d


def simulate_fade_trades(df: pd.DataFrame, rsi_period: int = 14, ob: float = 70.0,
                         os_: float = 30.0, entry_mode: str = "zone_exit",
                         max_bars: int = 48, stop_pct: float = 1.5, target_pct: float = 2.5,
                         midline_exit: bool = True) -> pd.DataFrame:
    """
    Exit = first of: stop_pct hit, target_pct hit, RSI midline (50) cross-back
    (if midline_exit), or max_bars candles held (time stop). If a bar's high/low
    range hits both stop and target, the stop is assumed to have hit first
    (conservative — intrabar order is unknowable from OHLC alone).
    Returns a trade-log DataFrame, one row per completed trade.
    """
    d = compute_rsi(df, rsi_period)
    d = _entry_signals(d, ob, os_, entry_mode)
    n = len(d)
    idx = d.index
    close = d["close"].to_numpy()
    high = d["high"].to_numpy()
    low = d["low"].to_numpy()
    rsi = d["rsi"].to_numpy()
    short_sig = d["short_signal"].to_numpy()
    long_sig = d["long_signal"].to_numpy()

    trades = []
    i = 0
    while i < n:
        if short_sig[i]:
            side = "SHORT"
        elif long_sig[i]:
            side = "LONG"
        else:
            i += 1
            continue

        entry_price = close[i]
        entry_time = idx[i]
        entry_rsi = rsi[i]
        stop_price = entry_price * (1 + stop_pct / 100) if side == "SHORT" else entry_price * (1 - stop_pct / 100)
        target_price = entry_price * (1 - target_pct / 100) if side == "SHORT" else entry_price * (1 + target_pct / 100)

        j_last = min(i + max_bars, n - 1)
        exit_j = exit_price = exit_reason = None
        for j in range(i + 1, j_last + 1):
            hit_stop = (high[j] >= stop_price) if side == "SHORT" else (low[j] <= stop_price)
            hit_target = (low[j] <= target_price) if side == "SHORT" else (high[j] >= target_price)
            hit_mid = midline_exit and (
                (side == "SHORT" and rsi[j] <= 50) or (side == "LONG" and rsi[j] >= 50)
            )
            if hit_stop:
                exit_j, exit_price, exit_reason = j, stop_price, "STOP"
                break
            if hit_target:
                exit_j, exit_price, exit_reason = j, target_price, "TARGET"
                break
            if hit_mid:
                exit_j, exit_price, exit_reason = j, close[j], "RSI_MIDLINE"
                break
            if j == j_last:
                exit_j, exit_price, exit_reason = j, close[j], "TIME_STOP"
                break

        if exit_j is None:   # no bars left to exit on — drop the dangling trade
            break

        pnl_pts = (entry_price - exit_price) if side == "SHORT" else (exit_price - entry_price)
        trades.append(dict(
            entry_time=entry_time, side=side, entry_price=round(float(entry_price), 2),
            entry_rsi=round(float(entry_rsi), 1), exit_time=idx[exit_j],
            exit_price=round(float(exit_price), 2), exit_reason=exit_reason,
            bars_held=exit_j - i, pnl_pts=round(float(pnl_pts), 2),
            pnl_pct=round(float(pnl_pts / entry_price * 100), 3),
        ))
        i = exit_j + 1   # no new entries while a position is open

    return pd.DataFrame(trades)


def trade_stats(trades: pd.DataFrame) -> dict:
    if trades is None or trades.empty:
        return dict(n_trades=0, win_rate=np.nan, expectancy_pts=np.nan, profit_factor=np.nan,
                    total_pnl_pts=0.0, max_drawdown_pts=0.0, avg_bars_held=np.nan,
                    avg_win_pts=np.nan, avg_loss_pts=np.nan, long_trades=0, short_trades=0)
    n = len(trades)
    wins = trades[trades["pnl_pts"] > 0]
    losses = trades[trades["pnl_pts"] <= 0]
    gross_win = float(wins["pnl_pts"].sum())
    gross_loss = float(-losses["pnl_pts"].sum())
    equity = trades["pnl_pts"].cumsum()
    drawdown = equity - equity.cummax()
    return dict(
        n_trades=n,
        win_rate=round(len(wins) / n * 100, 1),
        avg_win_pts=round(float(wins["pnl_pts"].mean()), 2) if not wins.empty else 0.0,
        avg_loss_pts=round(float(losses["pnl_pts"].mean()), 2) if not losses.empty else 0.0,
        expectancy_pts=round(float(trades["pnl_pts"].mean()), 2),
        profit_factor=round(gross_win / gross_loss, 2) if gross_loss > 0 else np.inf,
        total_pnl_pts=round(float(trades["pnl_pts"].sum()), 2),
        max_drawdown_pts=round(float(drawdown.min()), 2) if not drawdown.empty else 0.0,
        avg_bars_held=round(float(trades["bars_held"].mean()), 1),
        long_trades=int((trades["side"] == "LONG").sum()),
        short_trades=int((trades["side"] == "SHORT").sum()),
    )


def equity_curve(trades: pd.DataFrame) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame()
    e = trades[["exit_time", "pnl_pts"]].copy()
    e["cum_pnl_pts"] = e["pnl_pts"].cumsum()
    return e


# Paired OB/OS levels — symmetric distance from the 50 midline, tightest to widest.
DEFAULT_OB_OS_PAIRS = ((65, 35), (70, 30), (75, 25), (80, 20))


def threshold_scan(df: pd.DataFrame, timeframe_label: str, rsi_period: int = 14,
                   ob_os_pairs=DEFAULT_OB_OS_PAIRS, entry_mode: str = "zone_exit",
                   max_bars: int = 48, stop_pct: float = 1.5, target_pct: float = 2.5,
                   midline_exit: bool = True) -> pd.DataFrame:
    """Grid-scan OB/OS threshold pairs for one timeframe — the table that answers
    'which threshold (and, joined across timeframes, which timeframe) actually works'."""
    rows = []
    for ob, os_ in ob_os_pairs:
        trades = simulate_fade_trades(df, rsi_period, ob, os_, entry_mode, max_bars,
                                      stop_pct, target_pct, midline_exit)
        stats = trade_stats(trades)
        stats.update(timeframe=timeframe_label, ob=ob, os=os_)
        rows.append(stats)
    out = pd.DataFrame(rows)
    cols = ["timeframe", "ob", "os", "n_trades", "win_rate", "expectancy_pts",
            "profit_factor", "total_pnl_pts", "max_drawdown_pts", "avg_bars_held",
            "avg_win_pts", "avg_loss_pts", "long_trades", "short_trades"]
    return out[[c for c in cols if c in out.columns]]


def compare_timeframes(dfs: dict, rsi_period: int = 14, ob_os_pairs=DEFAULT_OB_OS_PAIRS,
                       entry_mode: str = "zone_exit", max_bars_map: dict = None,
                       stop_pct: float = 1.5, target_pct: float = 2.5,
                       midline_exit: bool = True) -> pd.DataFrame:
    """dfs: {timeframe_label: ohlc_df}. max_bars_map: {timeframe_label: max_bars}
    (bar counts don't mean the same thing across timeframes — 48 30m-bars is 1
    trading day, 48 60m-bars is 8 — so each timeframe gets its own time-stop)."""
    max_bars_map = max_bars_map or {}
    parts = []
    for label, df in dfs.items():
        if df is None or df.empty:
            continue
        mb = max_bars_map.get(label, 48)
        parts.append(threshold_scan(df, label, rsi_period, ob_os_pairs, entry_mode,
                                    mb, stop_pct, target_pct, midline_exit))
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True).sort_values(
        ["expectancy_pts"], ascending=False, na_position="last").reset_index(drop=True)
