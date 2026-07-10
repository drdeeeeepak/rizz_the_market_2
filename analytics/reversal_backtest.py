# analytics/reversal_backtest.py
# Standalone backtest for page 24: after a FALL — >=1% in a single day (using
# that day's own LOW, so a pure intraday drop vs. yesterday's close counts
# even if the close recovers) OR >=1.5% over two closes — how big does the
# bounce off the low need to be before Nifty reliably keeps going up, vs.
# rolling over into a fresh lower low?
#
# EPISODE = a run of flagged "fall" days merged together, anchored on its
# lowest LOW. Walking forward day-by-day, a new lower low RESETS the anchor
# (the fall isn't over yet). Once the running high since the (current) anchor
# first climbs threshold% above it, that's the trigger day — score the
# forward return/hit-rate from the trigger close over each horizon, and
# whether price ever closes back below the anchor low again (a failed/
# whipsaw reversal).

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


def find_fall_episodes_daily(daily: pd.DataFrame, fall_1d_pct: float = 1.0,
                             fall_2d_pct: float = 1.5, merge_gap_days: int = 1,
                             require_green_confirmation: bool = True) -> pd.DataFrame:
    """Flag every day whose fall crosses either threshold and merge nearby
    flagged days into episodes anchored on the lowest LOW in the run.
    fall_1d_pct is measured prior-close -> today's LOW (catches an intraday-
    only drop even on a day that closes flat/up); fall_2d_pct is close(t-2)
    -> close(t).

    If require_green_confirmation, an episode only qualifies if the low day
    ITSELF closes green (close > open — buyers already took it back that
    same day) OR the very next trading day closes green (bought the low the
    next morning) — i.e. some visible sign of buying at/right after the
    low, not just a quiet low that could still give way. Episodes without
    that confirmation are dropped."""
    d = _norm_ohlc(daily)
    n = len(d)
    if n < 5:
        return pd.DataFrame()

    open_, close, low = d["open"].to_numpy(), d["close"].to_numpy(), d["low"].to_numpy()
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

        green_low_day = bool(close[low_idx] > open_[low_idx])
        green_next_day = bool(low_idx + 1 < n and close[low_idx + 1] > open_[low_idx + 1])
        if require_green_confirmation and not (green_low_day or green_next_day):
            continue

        rows.append({"start_date": dates[s], "low_date": dates[low_idx], "low_idx": low_idx,
                     "low": fall_low, "peak_ref": peak_ref, "fall_pct": round(fall_pct, 2),
                     "green_low_day": green_low_day, "green_next_day": green_next_day})
    return pd.DataFrame(rows)


def reversal_threshold_scan_daily(daily: pd.DataFrame, episodes: pd.DataFrame,
                                  thresholds=DEFAULT_THRESHOLDS,
                                  forward_horizons=(3, 5, 10),
                                  max_track_days: int = 30) -> dict:
    """For each threshold, scores the forward outcome from the trigger day
    over EVERY horizon in forward_horizons separately (not just the longest
    one), with two different notions of "the low broke again":
      - close_fail_{h}d  : CLOSING price fell back below the anchor low
                           within h days of the trigger (whipsaw on a
                           closing basis — the original metric).
      - touch_low_{h}d   : the day's LOW (intraday) touched/breached the
                           anchor low again within h days of the trigger —
                           the relevant one for an option SELLER, since a
                           strike parked below the anchor low can get
                           threatened intraday even on a day that closes
                           back above it."""
    if episodes is None or episodes.empty:
        return {"scan": pd.DataFrame(), "detail": pd.DataFrame()}

    d = _norm_ohlc(daily)
    close, low, high = d["close"].to_numpy(), d["low"].to_numpy(), d["high"].to_numpy()
    dates = d.index
    n = len(d)
    thresholds = tuple(float(t) for t in thresholds)
    max_h = max(forward_horizons)

    detail_rows = []
    for _, ep in episodes.iterrows():
        anchor_idx = int(ep["low_idx"])
        anchor_low = float(ep["low"])
        triggered = {t: None for t in thresholds}
        j = anchor_idx + 1
        steps = 0
        while j < n and steps < max_track_days:
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
            row = {"episode_low_date": ep["low_date"], "threshold%": t,
                  "trigger_date": dates[trig_idx], "trigger_close": round(float(trig_close), 2),
                  "anchor_low_at_trigger": round(anchor_low, 2)}
            for h in forward_horizons:
                k = trig_idx + h
                end_k = min(k, n - 1)
                window_close = close[trig_idx + 1:end_k + 1]
                window_low = low[trig_idx + 1:end_k + 1]
                row[f"close_fail_{h}d"] = bool(len(window_close) and (window_close < anchor_low).any())
                row[f"touch_low_{h}d"] = bool(len(window_low) and (window_low < anchor_low).any())
                row[f"fwd_ret_{h}d%"] = round((close[k] - trig_close) / trig_close * 100, 2) \
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
              "pct_of_episodes_triggered%": round(len(sub) / n_episodes * 100, 1)}
        for h in forward_horizons:
            ret_col = f"fwd_ret_{h}d%"
            valid = sub[ret_col].dropna()
            row[f"hit_rate_{h}d%"] = round((valid > 0).mean() * 100, 1) if len(valid) else np.nan
            row[f"avg_fwd_ret_{h}d%"] = round(valid.mean(), 2) if len(valid) else np.nan
            row[f"close_fail_rate_{h}d%"] = round(sub[f"close_fail_{h}d"].mean() * 100, 1)
            row[f"touch_low_rate_{h}d%"] = round(sub[f"touch_low_{h}d"].mean() * 100, 1)
        scan_rows.append(row)
    return {"scan": pd.DataFrame(scan_rows), "detail": detail}


def pick_min_reliable_threshold(scan: pd.DataFrame, horizon: int, min_hit_rate: float = 60.0,
                                min_n: int = 10) -> dict | None:
    """Smallest reversal% threshold whose forward hit-rate at `horizon`
    trading days clears `min_hit_rate`, with at least `min_n` triggered
    episodes behind it — i.e. the minimum bounce-off-the-low size after
    which Nifty reliably kept going up in this history. None if nothing in
    the scan clears the bar."""
    if scan is None or scan.empty:
        return None
    col = f"hit_rate_{horizon}d%"
    if col not in scan.columns:
        return None
    ok = scan[(scan[col] >= min_hit_rate) & (scan["n_triggered"] >= min_n)]
    if ok.empty:
        return None
    return ok.sort_values("threshold%").iloc[0].to_dict()


def pick_min_safe_threshold(scan: pd.DataFrame, horizon: int, max_touch_rate: float = 0.0,
                            min_n: int = 10) -> dict | None:
    """Smallest reversal% threshold whose intraday touch-the-low-again rate
    at `horizon` trading days is at/below `max_touch_rate` (default 0.0 —
    never touched in this sample), with at least `min_n` triggered episodes
    behind it. Answers: 'what's the minimum bounce after which a put strike
    sitting below the low would have stayed safe for `horizon` days?' None
    if nothing in the scan clears the bar."""
    if scan is None or scan.empty:
        return None
    col = f"touch_low_rate_{horizon}d%"
    if col not in scan.columns:
        return None
    ok = scan[(scan[col] <= max_touch_rate) & (scan["n_triggered"] >= min_n)]
    if ok.empty:
        return None
    return ok.sort_values("threshold%").iloc[0].to_dict()


def fall_size_safety_scan(daily: pd.DataFrame, fall_pcts=DEFAULT_THRESHOLDS,
                          forward_horizons=(1, 2, 3, 5), merge_gap_days: int = 1,
                          require_green_confirmation: bool = False) -> pd.DataFrame:
    """A DIFFERENT scan from reversal_threshold_scan_daily: instead of
    varying how big a BOUNCE off the low needs to be, this varies how big
    the FALL itself needs to be, and checks — with NO bounce or confirmation
    wait at all, straight from the low day forward — whether the low ever
    got touched (intraday) or closed through again within each horizon.

    Answers: 'how big does a single-day fall need to be before its own low
    reliably holds on its own, before any bounce even happens?' The 2-day
    fall path is always muted here (fall_2d_pct effectively off) so the
    fall-size axis being scanned isn't confounded with a different-shaped
    trigger; each fall_pct in fall_pcts is its own independent episode
    search (a bigger cutoff finds fewer, deeper-fall episodes, not a subset
    of the smaller cutoff's episodes)."""
    fall_pcts = tuple(round(float(x), 2) for x in fall_pcts)
    d = _norm_ohlc(daily)
    close, low = d["close"].to_numpy(), d["low"].to_numpy()
    n = len(d)

    rows = []
    for fp in fall_pcts:
        episodes = find_fall_episodes_daily(daily, fall_1d_pct=fp, fall_2d_pct=1e9,
                                            merge_gap_days=merge_gap_days,
                                            require_green_confirmation=require_green_confirmation)
        n_eps = len(episodes)
        row = {"fall_pct": fp, "n_episodes": n_eps}
        if n_eps == 0:
            for h in forward_horizons:
                row[f"hit_rate_{h}d%"] = np.nan
                row[f"avg_fwd_ret_{h}d%"] = np.nan
                row[f"close_fail_rate_{h}d%"] = np.nan
                row[f"touch_low_rate_{h}d%"] = np.nan
            rows.append(row)
            continue

        per_h = {h: {"touch": [], "close_fail": [], "ret": []} for h in forward_horizons}
        for _, ep in episodes.iterrows():
            low_idx = int(ep["low_idx"])
            anchor_low = float(ep["low"])
            base_close = close[low_idx]
            for h in forward_horizons:
                k = low_idx + h
                end_k = min(k, n - 1)
                window_low = low[low_idx + 1:end_k + 1]
                window_close = close[low_idx + 1:end_k + 1]
                per_h[h]["touch"].append(bool(len(window_low) and (window_low < anchor_low).any()))
                per_h[h]["close_fail"].append(bool(len(window_close) and (window_close < anchor_low).any()))
                if k < n:
                    per_h[h]["ret"].append((close[k] - base_close) / base_close * 100)

        for h in forward_horizons:
            touches, closes_fail, rets = per_h[h]["touch"], per_h[h]["close_fail"], per_h[h]["ret"]
            row[f"touch_low_rate_{h}d%"] = round(float(np.mean(touches)) * 100, 1) if touches else np.nan
            row[f"close_fail_rate_{h}d%"] = round(float(np.mean(closes_fail)) * 100, 1) if closes_fail else np.nan
            if rets:
                rets_arr = np.array(rets)
                row[f"hit_rate_{h}d%"] = round(float((rets_arr > 0).mean()) * 100, 1)
                row[f"avg_fwd_ret_{h}d%"] = round(float(rets_arr.mean()), 2)
            else:
                row[f"hit_rate_{h}d%"] = np.nan
                row[f"avg_fwd_ret_{h}d%"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def pick_min_certain_fall(scan: pd.DataFrame, horizon: int, max_touch_rate: float = 0.0,
                          min_n: int = 10) -> dict | None:
    """Smallest fall%-cutoff whose intraday touch-the-low-again rate at
    `horizon` trading days is at/below `max_touch_rate` (default 0.0 —
    never touched in this sample) — the minimum single-day fall size that,
    on its own low with no bounce confirmation required at all, held for
    `horizon` days. None if nothing in the scan clears the bar."""
    if scan is None or scan.empty:
        return None
    col = f"touch_low_rate_{horizon}d%"
    if col not in scan.columns:
        return None
    ok = scan[(scan[col] <= max_touch_rate) & (scan["n_episodes"] >= min_n)]
    if ok.empty:
        return None
    return ok.sort_values("fall_pct").iloc[0].to_dict()
