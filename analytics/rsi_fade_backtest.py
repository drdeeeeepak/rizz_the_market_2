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


def _entry_signals(d: pd.DataFrame, ob: float, os_: float, entry_mode: str,
                   require_divergence: bool = False, div_lookback: int = 20,
                   div_min_gap: float = 2.0) -> pd.DataFrame:
    """
    entry_mode:
      "touch"     — fires the bar RSI first crosses INTO the zone (>=ob or <=os_).
      "zone_exit" — fires the bar RSI crosses back OUT of the zone. More conservative:
                    during a strong one-sided run RSI can sit pinned at an extreme for
                    a day or two before actually turning, so "touch" risks entering too
                    early and eating that continuation.

    require_divergence — the fix for the "fade a genuine trend, get run over" failure
    mode: a real 3-6 day one-sided move keeps making fresh price extremes WITH RSI
    confirming each one (RSI also makes a fresh extreme), so plain OB/OS fades keep
    re-triggering all the way down/up. Requiring divergence — price makes a fresh
    div_lookback-bar extreme but RSI does NOT — only fades once momentum has visibly
    stopped confirming the move, which is much closer to "day 3-5, the move is
    stalling" than "RSI crossed 70/30 at all, trend or no trend."
      LONG:  low[i] <= rolling_min(low, div_lookback)  AND  rsi[i] > rolling_min(rsi, div_lookback) + div_min_gap
      SHORT: high[i] >= rolling_max(high, div_lookback) AND rsi[i] < rolling_max(rsi, div_lookback) - div_min_gap
    (rolling windows are computed on the PRIOR div_lookback bars, excluding bar i itself.)
    """
    d = d.copy()
    rsi = d["rsi"]
    prev = rsi.shift(1)
    if entry_mode == "touch":
        short_sig = (prev < ob) & (rsi >= ob)
        long_sig = (prev > os_) & (rsi <= os_)
    else:  # zone_exit
        short_sig = (prev >= ob) & (rsi < ob)
        long_sig = (prev <= os_) & (rsi > os_)

    if require_divergence:
        prior_low_price = d["low"].shift(1).rolling(div_lookback).min()
        prior_low_rsi = rsi.shift(1).rolling(div_lookback).min()
        prior_high_price = d["high"].shift(1).rolling(div_lookback).max()
        prior_high_rsi = rsi.shift(1).rolling(div_lookback).max()
        bullish_div = (d["low"] <= prior_low_price) & (rsi > prior_low_rsi + div_min_gap)
        bearish_div = (d["high"] >= prior_high_price) & (rsi < prior_high_rsi - div_min_gap)
        long_sig = long_sig & bullish_div
        short_sig = short_sig & bearish_div

    d["short_signal"] = short_sig.fillna(False)
    d["long_signal"] = long_sig.fillna(False)
    return d


def simulate_fade_trades(df: pd.DataFrame, rsi_period: int = 14, ob: float = 70.0,
                         os_: float = 30.0, entry_mode: str = "zone_exit",
                         max_bars: int = 48, stop_pct: float = 1.5, target_pct: float = 2.5,
                         midline_exit: bool = True, require_divergence: bool = False,
                         div_lookback: int = 20, div_min_gap: float = 2.0,
                         require_cooldown: bool = False, cooldown_bars: int = 20) -> pd.DataFrame:
    """
    Exit = first of: stop_pct hit, target_pct hit, RSI midline (50) cross-back
    (if midline_exit), or max_bars candles held (time stop). If a bar's high/low
    range hits both stop and target, the stop is assumed to have hit first
    (conservative — intrabar order is unknowable from OHLC alone).

    require_cooldown — alternative (less blunt) fix for the same "fade a genuine
    trend, get run over" failure mode require_divergence targets. Instead of
    judging each signal on momentum confirmation, this just refuses to re-enter
    the SAME direction within cooldown_bars of the last time that direction was
    traded — i.e. take the FIRST fade of a stretch, skip the repeat re-triggers
    that pile on while the trend grinds on. The cooldown for a side clears
    immediately the moment a trade fires in the OPPOSITE direction (a real
    reversal has shown up, so the "don't re-fade this side yet" restriction no
    longer applies).

    Returns a trade-log DataFrame, one row per completed trade.
    """
    d = compute_rsi(df, rsi_period)
    d = _entry_signals(d, ob, os_, entry_mode, require_divergence, div_lookback, div_min_gap)
    n = len(d)
    idx = d.index
    close = d["close"].to_numpy()
    high = d["high"].to_numpy()
    low = d["low"].to_numpy()
    rsi = d["rsi"].to_numpy()
    short_sig = d["short_signal"].to_numpy()
    long_sig = d["long_signal"].to_numpy()
    opposite = {"LONG": "SHORT", "SHORT": "LONG"}
    last_entry_bar = {"LONG": -10**9, "SHORT": -10**9}

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

        if require_cooldown and (i - last_entry_bar[side]) < cooldown_bars:
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
        last_entry_bar[side] = i
        last_entry_bar[opposite[side]] = -10**9   # a reversal clears the other side's cooldown
        i = exit_j + 1   # no new entries while a position is open

    return pd.DataFrame(trades)


def detect_divergence_signals(df: pd.DataFrame, rsi_period: int = 14,
                              div_lookback: int = 20, div_min_gap: float = 2.0) -> pd.DataFrame:
    """
    Bar-by-bar bullish/bearish divergence flags — the exact entry rule used by
    simulate_pure_divergence_trades(), factored out so a live "what's signalling right
    now" view and the backtest can never drift apart.

      bullish — price makes a fresh div_lookback-bar low, RSI does NOT confirm it
                (rsi > prior rsi low + div_min_gap).
      bearish — price makes a fresh div_lookback-bar high, RSI does NOT confirm it
                (rsi < prior rsi high - div_min_gap).

    Returns df (with an rsi column) plus boolean 'bullish' / 'bearish' columns.
    """
    d = compute_rsi(df, rsi_period)
    rsi_s = d["rsi"]
    prior_low_price = d["low"].shift(1).rolling(div_lookback).min()
    prior_low_rsi = rsi_s.shift(1).rolling(div_lookback).min()
    prior_high_price = d["high"].shift(1).rolling(div_lookback).max()
    prior_high_rsi = rsi_s.shift(1).rolling(div_lookback).max()
    d["bullish"] = ((d["low"] <= prior_low_price) & (rsi_s > prior_low_rsi + div_min_gap)).fillna(False)
    d["bearish"] = ((d["high"] >= prior_high_price) & (rsi_s < prior_high_rsi - div_min_gap)).fillna(False)
    return d


def simulate_pure_divergence_trades(df: pd.DataFrame, rsi_period: int = 14,
                                    div_lookback: int = 20,
                                    div_min_gap: float = 2.0,
                                    stop_pts: float = 0.0) -> pd.DataFrame:
    """
    Pure divergence — divergence is the ONLY entry rule. No RSI overbought/oversold
    gate, no stop, no target, no time stop. This is deliberately different from
    simulate_fade_trades(require_divergence=True), which fires only when an RSI
    zone cross AND a divergence land on the same bar (a much rarer coincidence,
    which is why that path returns a handful of trades).

      LONG  — price makes a fresh div_lookback-bar low, RSI does NOT confirm it
              (rsi > prior rsi low + div_min_gap).
      SHORT — price makes a fresh div_lookback-bar high, RSI does NOT confirm it
              (rsi < prior rsi high - div_min_gap).

    Exit — the OPPOSITE divergence, and nothing else when stop_pts == 0. No midline
    exit, no target, no time stop: a trade rides on until the market prints a
    divergence the other way, at which point it closes at that bar's close and the
    new signal opens the opposite trade. Always in the market once the first signal
    fires. Same-side divergences while a trade is open are ignored (already in it).
    A trade still open when the data ends is dropped from the log — it has no exit yet.

    stop_pts > 0 adds a fixed points stop measured from the entry price, checked
    against each bar's LOW (long) / HIGH (short) — so it uses the real intrabar
    excursion rather than the close, and a trade that dips through the stop before
    recovering is correctly recorded as stopped out. If a bar both trips the stop and
    prints the opposing divergence, the stop is taken first (intrabar order is
    unknowable from OHLC, so assume the adverse fill — same convention as
    simulate_fade_trades). Being stopped out goes FLAT rather than reversing: the next
    entry is then the next divergence of either side, which is why a stop changes the
    trade sequence itself and cannot be evaluated by capping losses in a finished
    trade log.
    """
    d = detect_divergence_signals(df, rsi_period, div_lookback, div_min_gap)
    rsi_s = d["rsi"]

    n = len(d)
    idx = d.index
    close = d["close"].to_numpy()
    high = d["high"].to_numpy()
    low = d["low"].to_numpy()
    rsi = rsi_s.to_numpy()
    long_sig = d["bullish"].to_numpy()
    short_sig = d["bearish"].to_numpy()

    trades = []
    prev_side = None   # side just closed, so an outside bar firing BOTH ways flips rather than repeats
    i = 0
    while i < n:
        if long_sig[i] and short_sig[i]:
            side = "LONG" if prev_side == "SHORT" else "SHORT" if prev_side == "LONG" else "LONG"
        elif long_sig[i]:
            side = "LONG"
        elif short_sig[i]:
            side = "SHORT"
        else:
            i += 1
            continue

        entry_price, entry_rsi = close[i], rsi[i]
        stop_price = ((entry_price - stop_pts) if side == "LONG" else (entry_price + stop_pts)) \
            if stop_pts > 0 else None

        exit_j = exit_price = exit_reason = None
        worst = 0.0   # maximum adverse excursion, in points, while the trade was open
        for j in range(i + 1, n):
            adverse = (entry_price - low[j]) if side == "LONG" else (high[j] - entry_price)
            worst = max(worst, float(adverse))
            if stop_price is not None:
                hit = (low[j] <= stop_price) if side == "LONG" else (high[j] >= stop_price)
                if hit:   # stop wins a tie with the opposing divergence on the same bar
                    exit_j, exit_price, exit_reason = j, stop_price, "STOP"
                    break
            # only a divergence the OTHER way ends the trade
            if (side == "LONG" and short_sig[j]) or (side == "SHORT" and long_sig[j]):
                exit_j, exit_price, exit_reason = j, close[j], "OPPOSITE_DIV"
                break
        if exit_j is None:   # still open at the end of the data — not a completed trade
            break

        pnl_pts = (exit_price - entry_price) if side == "LONG" else (entry_price - exit_price)
        trades.append(dict(
            entry_time=idx[i], side=side, entry_price=round(float(entry_price), 2),
            entry_rsi=round(float(entry_rsi), 1), exit_time=idx[exit_j],
            exit_price=round(float(exit_price), 2), exit_rsi=round(float(rsi[exit_j]), 1),
            exit_reason=exit_reason, bars_held=exit_j - i,
            mae_pts=round(worst, 2),
            pnl_pts=round(float(pnl_pts), 2),
            pnl_pct=round(float(pnl_pts / entry_price * 100), 3),
        ))
        prev_side = side
        # an opposing divergence rolls straight into the reverse trade; a stop goes flat
        i = exit_j if exit_reason == "OPPOSITE_DIV" else exit_j + 1

    return pd.DataFrame(trades)


def stop_sweep(df: pd.DataFrame, stop_pts_list, rsi_period: int = 14,
               div_lookback: int = 20, div_min_gap: float = 2.0) -> pd.DataFrame:
    """Re-run the pure-divergence simulation once per candidate stop and tabulate it.

    Each row is a full re-simulation on the real candles, NOT the finished trade log
    with its losses clipped. That distinction is the whole point: a stop also knocks
    out winners that dipped through it before recovering, and it changes every entry
    that follows, so clipping a trade log always flatters a tight stop and will report
    the tightest value tested as 'best'.
    """
    rows = []
    for s in stop_pts_list:
        tr = simulate_pure_divergence_trades(df, rsi_period, div_lookback, div_min_gap, stop_pts=s)
        stats = trade_stats(tr)
        stats["stop_pts"] = float(s) if s and s > 0 else np.nan
        stats["stopped_out"] = int((tr["exit_reason"] == "STOP").sum()) if not tr.empty else 0
        stats["stopped_pct"] = round(stats["stopped_out"] / len(tr) * 100, 1) if len(tr) else 0.0
        rows.append(stats)
    out = pd.DataFrame(rows)
    cols = ["stop_pts", "n_trades", "stopped_out", "stopped_pct", "win_rate",
            "expectancy_pts", "profit_factor", "total_pnl_pts", "max_drawdown_pts",
            "avg_win_pts", "avg_loss_pts", "avg_bars_held"]
    return out[[c for c in cols if c in out.columns]]


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
                   midline_exit: bool = True, require_divergence: bool = False,
                   div_lookback: int = 20, div_min_gap: float = 2.0,
                   require_cooldown: bool = False, cooldown_bars: int = 20) -> pd.DataFrame:
    """Grid-scan OB/OS threshold pairs for one timeframe — the table that answers
    'which threshold (and, joined across timeframes, which timeframe) actually works'."""
    rows = []
    for ob, os_ in ob_os_pairs:
        trades = simulate_fade_trades(df, rsi_period, ob, os_, entry_mode, max_bars,
                                      stop_pct, target_pct, midline_exit,
                                      require_divergence, div_lookback, div_min_gap,
                                      require_cooldown, cooldown_bars)
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
                       midline_exit: bool = True, require_divergence: bool = False,
                       div_lookback: int = 20, div_min_gap: float = 2.0,
                       require_cooldown: bool = False, cooldown_bars_map: dict = None) -> pd.DataFrame:
    """dfs: {timeframe_label: ohlc_df}. max_bars_map / cooldown_bars_map: {timeframe_label: bars}
    (bar counts don't mean the same thing across timeframes — 48 30m-bars is 1
    trading day, 48 60m-bars is 8 — so each timeframe gets its own time-stop and
    its own cooldown window)."""
    max_bars_map = max_bars_map or {}
    cooldown_bars_map = cooldown_bars_map or {}
    parts = []
    for label, df in dfs.items():
        if df is None or df.empty:
            continue
        mb = max_bars_map.get(label, 48)
        cb = cooldown_bars_map.get(label, 20)
        parts.append(threshold_scan(df, label, rsi_period, ob_os_pairs, entry_mode,
                                    mb, stop_pct, target_pct, midline_exit,
                                    require_divergence, div_lookback, div_min_gap,
                                    require_cooldown, cb))
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True).sort_values(
        ["expectancy_pts"], ascending=False, na_position="last").reset_index(drop=True)
