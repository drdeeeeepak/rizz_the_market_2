# analytics/reversal_backtest.py
# Standalone backtest for page 24: after a FALL — >=1% in a single day (using
# that day's own LOW, so a pure intraday drop counts even if the close
# recovers) OR >=1.5% over two closes — how big does the bounce off the low
# need to be before Nifty reliably keeps going up, vs. rolling over into a
# fresh lower low?
#
# EPISODE = a run of flagged "fall" bars merged together, anchored on its
# lowest LOW. Walking forward bar-by-bar, a new lower low RESETS the anchor
# (the fall isn't over yet). Once the running high since the (current) anchor
# first climbs threshold% above it, that's the trigger bar — score the
# forward return/hit-rate from the trigger close over each horizon, and
# whether price ever closes back below the anchor low again (a failed/
# whipsaw reversal).
#
# Two engines share the same core scan:
#   - daily   : long history (~years), reference = prior close(s), bar = 1 day.
#   - intraday: short history (Kite-limited), reference = running high SINCE
#               THAT SESSION'S OPEN, bar = 1 candle — catches a same-day
#               drop-and-recover that a daily close might mask entirely.

import numpy as np
import pandas as pd

DEFAULT_THRESHOLDS = tuple(round(x, 2) for x in np.arange(0.25, 3.01, 0.25))


def _norm_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    return d[["open", "high", "low", "close"]].astype(float).sort_index()


def _merge_flagged(flagged_idx: np.ndarray, merge_gap: int) -> list[tuple[int, int]]:
    spans = []
    start = prev = int(flagged_idx[0])
    for idx in flagged_idx[1:]:
        idx = int(idx)
        if idx - prev <= merge_gap + 1:
            prev = idx
            continue
        spans.append((start, prev))
        start = prev = idx
    spans.append((start, prev))
    return spans


# ── daily engine ────────────────────────────────────────────────────────────

def find_fall_episodes_daily(daily: pd.DataFrame, fall_1d_pct: float = 1.0,
                             fall_2d_pct: float = 1.5, merge_gap_days: int = 1) -> pd.DataFrame:
    """Flag every day whose fall crosses either threshold and merge nearby
    flagged days into episodes anchored on the lowest LOW in the run.
    fall_1d_pct is measured prior-close -> today's LOW (catches an intraday-
    only drop even on a day that closes flat/up); fall_2d_pct is close(t-2)
    -> close(t)."""
    d = _norm_ohlc(daily)
    n = len(d)
    if n < 5:
        return pd.DataFrame()

    close, low = d["close"].to_numpy(), d["low"].to_numpy()
    dates = d.index

    fall1 = np.full(n, np.nan)
    fall2 = np.full(n, np.nan)
    fall1[1:] = (close[:-1] - low[1:]) / close[:-1] * 100
    fall2[2:] = (close[:-2] - close[2:]) / close[:-2] * 100

    is_fall = (np.nan_to_num(fall1) >= fall_1d_pct) | (np.nan_to_num(fall2) >= fall_2d_pct)
    flagged = np.where(is_fall)[0]
    if len(flagged) == 0:
        return pd.DataFrame()

    rows = []
    for s, e in _merge_flagged(flagged, merge_gap_days):
        peak_idx = max(s - 1, 0)
        low_idx = s + int(np.argmin(low[s:e + 1]))
        fall_low = float(low[low_idx])
        peak_ref = float(close[peak_idx])
        fall_pct = (peak_ref - fall_low) / peak_ref * 100 if peak_ref else np.nan
        rows.append({"start_date": dates[s], "low_date": dates[low_idx], "low_idx": low_idx,
                     "low": fall_low, "peak_ref": peak_ref, "fall_pct": round(fall_pct, 2)})
    return pd.DataFrame(rows)


def reversal_threshold_scan_daily(daily: pd.DataFrame, episodes: pd.DataFrame,
                                  thresholds=DEFAULT_THRESHOLDS,
                                  forward_horizons=(3, 5, 10),
                                  max_track_bars: int = 30) -> dict:
    d = _norm_ohlc(daily)
    return _scan_reversals(d, episodes, thresholds, forward_horizons, max_track_bars,
                           low_col="low_date")


# ── intraday engine ─────────────────────────────────────────────────────────

def find_fall_episodes_intraday(intraday: pd.DataFrame, fall_pct: float = 1.0,
                                merge_gap_bars: int = 2) -> pd.DataFrame:
    """Same idea, but the reference peak is the RUNNING HIGH SINCE THAT
    SESSION'S OPEN — a fall must occur within a single trading session, so
    this catches a pure intraday drop-and-recover a daily bar would hide."""
    d = _norm_ohlc(intraday)
    n = len(d)
    if n < 10:
        return pd.DataFrame()

    high, low = d["high"].to_numpy(), d["low"].to_numpy()
    dates = d.index
    session = dates.date

    running_high = np.empty(n)
    running_high[0] = high[0]
    for i in range(1, n):
        running_high[i] = high[i] if session[i] != session[i - 1] else max(running_high[i - 1], high[i])

    drawdown_pct = (running_high - low) / running_high * 100
    flagged = np.where(drawdown_pct >= fall_pct)[0]
    if len(flagged) == 0:
        return pd.DataFrame()

    rows = []
    for s, e in _merge_flagged(flagged, merge_gap_bars):
        low_idx = s + int(np.argmin(low[s:e + 1]))
        fall_low = float(low[low_idx])
        peak_ref = float(running_high[low_idx])
        fall_pct_val = (peak_ref - fall_low) / peak_ref * 100 if peak_ref else np.nan
        rows.append({"start_date": dates[s], "low_date": dates[low_idx], "low_idx": low_idx,
                     "low": fall_low, "peak_ref": peak_ref, "fall_pct": round(fall_pct_val, 2)})
    return pd.DataFrame(rows)


def reversal_threshold_scan_intraday(intraday: pd.DataFrame, episodes: pd.DataFrame,
                                     thresholds=DEFAULT_THRESHOLDS,
                                     forward_horizons=(4, 8, 26),
                                     max_track_bars: int = 120) -> dict:
    """forward_horizons are in BARS, not days — with 15-min candles the
    defaults (4/8/26) are roughly 1h / 2h / 1 session ahead."""
    d = _norm_ohlc(intraday)
    return _scan_reversals(d, episodes, thresholds, forward_horizons, max_track_bars,
                           low_col="low_date")


# ── shared core ──────────────────────────────────────────────────────────────

def _scan_reversals(d: pd.DataFrame, episodes: pd.DataFrame, thresholds, forward_horizons,
                    max_track_bars: int, low_col: str) -> dict:
    if episodes is None or episodes.empty:
        return {"scan": pd.DataFrame(), "detail": pd.DataFrame()}

    close, low, high = d["close"].to_numpy(), d["low"].to_numpy(), d["high"].to_numpy()
    dates = d.index
    n = len(d)
    max_h = max(forward_horizons)
    thresholds = tuple(float(t) for t in thresholds)

    detail_rows = []
    for _, ep in episodes.iterrows():
        anchor_idx = int(ep["low_idx"])
        anchor_low = float(ep["low"])
        triggered = {t: None for t in thresholds}
        j = anchor_idx + 1
        steps = 0
        while j < n and steps < max_track_bars:
            if low[j] < anchor_low:
                anchor_low = float(low[j])
                anchor_idx = j
            rev_pct = (high[j] - anchor_low) / anchor_low * 100
            for t in thresholds:
                if triggered[t] is None and rev_pct >= t:
                    triggered[t] = j
            j += 1
            steps += 1

        for t, trig_idx in triggered.items():
            if trig_idx is None:
                continue
            trig_close = close[trig_idx]
            row = {"episode_low_date": ep[low_col], "threshold%": t,
                  "trigger_date": dates[trig_idx], "trigger_close": round(float(trig_close), 2),
                  "anchor_low_at_trigger": round(anchor_low, 2)}
            end_k = min(trig_idx + max_h, n - 1)
            row["failed_back_below_low"] = bool(end_k > trig_idx and
                                                (close[trig_idx + 1:end_k + 1] < anchor_low).any())
            for h in forward_horizons:
                k = trig_idx + h
                row[f"fwd_ret_{h}b%"] = round((close[k] - trig_close) / trig_close * 100, 2) \
                    if k < n else np.nan
            detail_rows.append(row)

    detail = pd.DataFrame(detail_rows)
    if detail.empty:
        return {"scan": pd.DataFrame(), "detail": detail}

    n_episodes = len(episodes)
    scan_rows = []
    for t in thresholds:
        sub = detail[detail["threshold%"] == t]
        if sub.empty:
            continue
        row = {"threshold%": t, "n_triggered": len(sub),
              "pct_of_episodes_triggered%": round(len(sub) / n_episodes * 100, 1),
              "failure_rate%": round(sub["failed_back_below_low"].mean() * 100, 1)}
        for h in forward_horizons:
            col = f"fwd_ret_{h}b%"
            valid = sub[col].dropna()
            row[f"hit_rate_{h}b%"] = round((valid > 0).mean() * 100, 1) if len(valid) else np.nan
            row[f"avg_fwd_ret_{h}b%"] = round(valid.mean(), 2) if len(valid) else np.nan
        scan_rows.append(row)
    return {"scan": pd.DataFrame(scan_rows), "detail": detail}


def pick_min_reliable_threshold(scan: pd.DataFrame, horizon, min_hit_rate: float = 60.0,
                                min_n: int = 10) -> dict | None:
    """Smallest reversal% threshold whose forward hit-rate at `horizon`
    (days for the daily engine, bars for the intraday one) clears
    `min_hit_rate`, with at least `min_n` triggered episodes behind it —
    i.e. the minimum bounce-off-the-low size after which Nifty reliably
    kept going up in this history. None if nothing in the scan clears the bar."""
    if scan is None or scan.empty:
        return None
    col = f"hit_rate_{horizon}b%" if f"hit_rate_{horizon}b%" in scan.columns else f"hit_rate_{horizon}d%"
    if col not in scan.columns:
        return None
    ok = scan[(scan[col] >= min_hit_rate) & (scan["n_triggered"] >= min_n)]
    if ok.empty:
        return None
    return ok.sort_values("threshold%").iloc[0].to_dict()
