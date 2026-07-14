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

# Named Pinpoint parameter sets — dual_confirmation_daily_labels/dual_confirmation_scan
# (used live by page 27's Pinpoint section and page 24's Pinpoint mode) default to
# whichever preset ACTIVE_PINPOINT_PRESET names below. To switch what's live everywhere
# (page 27 snapshot/table/chart, page 24 defaults), change ONLY the ACTIVE_PINPOINT_PRESET
# string and reload — no other file needs editing. Add new presets here as more get tested.
PINPOINT_PRESETS = {
    "current_live": dict(bounce_pct=0.25, pullback_pct=0.25, fall_trigger_pct=0.0,
                         rise_trigger_pct=0.0, merge_gap_days=1),
    "lower_confirmation_0.1": dict(bounce_pct=0.10, pullback_pct=0.10, fall_trigger_pct=0.0,
                                   rise_trigger_pct=0.0, merge_gap_days=1),
    "tighter_formation_0.5": dict(bounce_pct=0.25, pullback_pct=0.25, fall_trigger_pct=0.5,
                                  rise_trigger_pct=0.5, merge_gap_days=1),
    "both_combined": dict(bounce_pct=0.10, pullback_pct=0.10, fall_trigger_pct=0.5,
                          rise_trigger_pct=0.5, merge_gap_days=1),
}
ACTIVE_PINPOINT_PRESET = "current_live"


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


def fall_bounce_grid_scan(daily: pd.DataFrame, fall_pcts=DEFAULT_THRESHOLDS,
                          bounce_pcts=DEFAULT_THRESHOLDS, forward_horizons=(3, 5, 10),
                          merge_gap_days: int = 1, require_green_confirmation: bool = False,
                          max_track_days: int = 30) -> pd.DataFrame:
    """The 2D combination of the two 1D scans above: every (fall_pct,
    bounce_pct) pair in one table, instead of holding one dimension fixed.
    For each fall_pct, finds episodes at that fall-size cutoff (2-day path
    muted, same as fall_size_safety_scan), then reuses
    reversal_threshold_scan_daily's bounce logic against bounce_pcts on
    those episodes. This is what answers 'given a fall this big, how much
    bounce do I actually need' rather than either dimension scanned alone
    with the other one implicitly fixed."""
    rows = []
    for fp in fall_pcts:
        fp = round(float(fp), 2)
        episodes = find_fall_episodes_daily(daily, fall_1d_pct=fp, fall_2d_pct=1e9,
                                            merge_gap_days=merge_gap_days,
                                            require_green_confirmation=require_green_confirmation)
        if episodes.empty:
            continue
        res = reversal_threshold_scan_daily(daily, episodes, thresholds=bounce_pcts,
                                            forward_horizons=forward_horizons,
                                            max_track_days=max_track_days)
        scan = res["scan"]
        if scan.empty:
            continue
        scan = scan.rename(columns={"threshold%": "bounce_pct", "n_triggered": "n_combo"})
        scan.insert(0, "fall_pct", fp)
        rows.append(scan)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def min_bounce_by_fall_size(grid: pd.DataFrame, horizon: int, max_touch_rate: float = 0.0,
                            min_n: int = 10) -> pd.DataFrame:
    """Collapses the 2D grid into one row per fall_pct: the SMALLEST
    bounce_pct that keeps the touch-the-low-again rate at `horizon` days
    at/below max_touch_rate, with at least min_n episodes behind that
    combo — a live lookup table: 'the market just fell this much — how
    much bounce do I need to wait for before it's safe.' A fall_pct row
    where no bounce_pct clears the bar shows NaN in min_bounce_pct."""
    if grid is None or grid.empty:
        return pd.DataFrame()
    col = f"touch_low_rate_{horizon}d%"
    if col not in grid.columns:
        return pd.DataFrame()
    rows = []
    for fp, sub in grid.groupby("fall_pct"):
        ok = sub[(sub[col] <= max_touch_rate) & (sub["n_combo"] >= min_n)]
        if ok.empty:
            rows.append({"fall_pct": fp, "min_bounce_pct": np.nan, "n_combo": np.nan,
                        f"touch_low_rate_{horizon}d%": np.nan, f"hit_rate_{horizon}d%": np.nan})
            continue
        best = ok.sort_values("bounce_pct").iloc[0]
        rows.append({"fall_pct": fp, "min_bounce_pct": best["bounce_pct"],
                    "n_combo": int(best["n_combo"]),
                    f"touch_low_rate_{horizon}d%": best[col],
                    f"hit_rate_{horizon}d%": best[f"hit_rate_{horizon}d%"]})
    return pd.DataFrame(rows).sort_values("fall_pct").reset_index(drop=True)


# ── mirror suite: RISE / HIGH — the call-seller side ────────────────────────
# Same mechanics as the fall/low suite above, flipped: anchor on the HIGHEST
# high instead of the lowest low, track a PULLBACK down instead of a bounce
# up, and touch_high_rate (not touch_low_rate) is the bad outcome for a
# SELLER (of calls, not puts). Expect this to behave very differently from
# the fall side, not as a bug: uptrends persistently make new highs as
# normal, healthy behavior, so don't expect touch_high_rate to flatten near
# zero the way touch_low_rate did — the point of this suite is to measure
# that curve honestly, not force a match to the put side.

def find_rise_episodes_daily(daily: pd.DataFrame, rise_1d_pct: float = 0.5,
                             rise_2d_pct: float = 0.75, merge_gap_days: int = 1,
                             require_red_confirmation: bool = False) -> pd.DataFrame:
    """Mirror of find_fall_episodes_daily: flags every day whose RISE
    crosses either threshold and merges nearby flagged days into episodes
    anchored on the HIGHEST high in the run. rise_1d_pct is measured
    prior-close -> today's HIGH (catches an intraday-only spike even on a
    day that closes lower); rise_2d_pct is close(t-2) -> close(t).

    If require_red_confirmation, an episode only qualifies if the high day
    ITSELF closes red (close < open) OR the very next trading day closes
    red. Off by default — matches the simplified fall-side rule where the
    pullback-threshold trigger itself is confirmation enough."""
    d = _norm_ohlc(daily)
    n = len(d)
    if n < 5:
        return pd.DataFrame()

    open_, close, high = d["open"].to_numpy(), d["close"].to_numpy(), d["high"].to_numpy()
    dates = d.index

    rise1 = np.full(n, np.nan)
    rise2 = np.full(n, np.nan)
    rise1[1:] = (high[1:] - close[:-1]) / close[:-1] * 100
    rise2[2:] = (close[2:] - close[:-2]) / close[:-2] * 100

    is_rise = (np.nan_to_num(rise1) >= rise_1d_pct) | (np.nan_to_num(rise2) >= rise_2d_pct)
    flagged = np.where(is_rise)[0]
    if len(flagged) == 0:
        return pd.DataFrame()

    rows = []
    for s, e in _merge_flagged(flagged, merge_gap_days):
        trough_idx = max(s - 1, 0)
        high_idx = s + int(np.argmax(high[s:e + 1]))
        rise_high = float(high[high_idx])
        trough_ref = float(close[trough_idx])
        rise_pct = (rise_high - trough_ref) / trough_ref * 100 if trough_ref else np.nan

        red_high_day = bool(close[high_idx] < open_[high_idx])
        red_next_day = bool(high_idx + 1 < n and close[high_idx + 1] < open_[high_idx + 1])
        if require_red_confirmation and not (red_high_day or red_next_day):
            continue

        rows.append({"start_date": dates[s], "high_date": dates[high_idx], "high_idx": high_idx,
                     "high": rise_high, "trough_ref": trough_ref, "rise_pct": round(rise_pct, 2),
                     "red_high_day": red_high_day, "red_next_day": red_next_day})
    return pd.DataFrame(rows)


def pullback_threshold_scan_daily(daily: pd.DataFrame, episodes: pd.DataFrame,
                                  thresholds=DEFAULT_THRESHOLDS,
                                  forward_horizons=(3, 5, 10),
                                  max_track_days: int = 30) -> dict:
    """Mirror of reversal_threshold_scan_daily: for each pullback
    threshold, scores the forward outcome from the trigger day over every
    horizon, with two different notions of "the high broke again":
      - close_fail_{h}d : CLOSING price rose back above the anchor high
                          within h days of the trigger.
      - touch_high_{h}d : the day's HIGH (intraday) touched/exceeded the
                          anchor high again within h days — the relevant
                          one for a CALL seller.
    hit_rate here means the forward return was NEGATIVE (price kept
    falling after the pullback trigger) — the continuation-DOWN read that
    matters for a call seller's conviction, the mirror of "closed higher"
    on the put side."""
    if episodes is None or episodes.empty:
        return {"scan": pd.DataFrame(), "detail": pd.DataFrame()}

    d = _norm_ohlc(daily)
    close, low, high = d["close"].to_numpy(), d["low"].to_numpy(), d["high"].to_numpy()
    dates = d.index
    n = len(d)
    thresholds = tuple(float(t) for t in thresholds)

    detail_rows = []
    for _, ep in episodes.iterrows():
        anchor_idx = int(ep["high_idx"])
        anchor_high = float(ep["high"])
        triggered = {t: None for t in thresholds}
        j = anchor_idx + 1
        steps = 0
        while j < n and steps < max_track_days:
            if high[j] > anchor_high:
                anchor_high = float(high[j])
                anchor_idx = j
            pullback_val = (anchor_high - low[j]) / anchor_high * 100
            for t in thresholds:
                if triggered[t] is None and pullback_val >= t:
                    triggered[t] = j
            j += 1
            steps += 1

        for t, trig_idx in triggered.items():
            if trig_idx is None:
                continue
            trig_close = close[trig_idx]
            row = {"episode_high_date": ep["high_date"], "threshold%": t,
                  "trigger_date": dates[trig_idx], "trigger_close": round(float(trig_close), 2),
                  "anchor_high_at_trigger": round(anchor_high, 2)}
            for h in forward_horizons:
                k = trig_idx + h
                end_k = min(k, n - 1)
                window_close = close[trig_idx + 1:end_k + 1]
                window_high = high[trig_idx + 1:end_k + 1]
                row[f"close_fail_{h}d"] = bool(len(window_close) and (window_close > anchor_high).any())
                row[f"touch_high_{h}d"] = bool(len(window_high) and (window_high > anchor_high).any())
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
            row[f"hit_rate_{h}d%"] = round((valid < 0).mean() * 100, 1) if len(valid) else np.nan
            row[f"avg_fwd_ret_{h}d%"] = round(valid.mean(), 2) if len(valid) else np.nan
            row[f"close_fail_rate_{h}d%"] = round(sub[f"close_fail_{h}d"].mean() * 100, 1)
            row[f"touch_high_rate_{h}d%"] = round(sub[f"touch_high_{h}d"].mean() * 100, 1)
        scan_rows.append(row)
    return {"scan": pd.DataFrame(scan_rows), "detail": detail}


def pick_min_reliable_pullback(scan: pd.DataFrame, horizon: int, min_hit_rate: float = 60.0,
                               min_n: int = 10) -> dict | None:
    """Mirror of pick_min_reliable_threshold: smallest pullback% threshold
    whose forward hit-rate (share that kept FALLING) at `horizon` trading
    days clears min_hit_rate — the downside-continuation read a call
    seller cares about."""
    if scan is None or scan.empty:
        return None
    col = f"hit_rate_{horizon}d%"
    if col not in scan.columns:
        return None
    ok = scan[(scan[col] >= min_hit_rate) & (scan["n_triggered"] >= min_n)]
    if ok.empty:
        return None
    return ok.sort_values("threshold%").iloc[0].to_dict()


def pick_min_safe_pullback(scan: pd.DataFrame, horizon: int, max_touch_rate: float = 0.0,
                          min_n: int = 10) -> dict | None:
    """Mirror of pick_min_safe_threshold: smallest pullback% threshold
    whose intraday touch-the-high-again rate at `horizon` trading days is
    at/below max_touch_rate — 'minimum pullback after which a call strike
    sitting above the high would have stayed safe for `horizon` days.'"""
    if scan is None or scan.empty:
        return None
    col = f"touch_high_rate_{horizon}d%"
    if col not in scan.columns:
        return None
    ok = scan[(scan[col] <= max_touch_rate) & (scan["n_triggered"] >= min_n)]
    if ok.empty:
        return None
    return ok.sort_values("threshold%").iloc[0].to_dict()


def rise_size_certainty_scan(daily: pd.DataFrame, rise_pcts=DEFAULT_THRESHOLDS,
                             forward_horizons=(1, 2, 3, 5), merge_gap_days: int = 1,
                             require_red_confirmation: bool = False) -> pd.DataFrame:
    """Mirror of fall_size_safety_scan: varies the RISE size itself and
    checks — with NO pullback wait at all, straight from the high day
    forward — whether the high ever got touched (intraday) or closed
    through again within each horizon. Answers: 'how big does a single-day
    rise need to be before its own high reliably holds, before any
    pullback even happens?'"""
    rise_pcts = tuple(round(float(x), 2) for x in rise_pcts)
    d = _norm_ohlc(daily)
    close, high = d["close"].to_numpy(), d["high"].to_numpy()
    n = len(d)

    rows = []
    for rp in rise_pcts:
        episodes = find_rise_episodes_daily(daily, rise_1d_pct=rp, rise_2d_pct=1e9,
                                            merge_gap_days=merge_gap_days,
                                            require_red_confirmation=require_red_confirmation)
        n_eps = len(episodes)
        row = {"rise_pct": rp, "n_episodes": n_eps}
        if n_eps == 0:
            for h in forward_horizons:
                row[f"hit_rate_{h}d%"] = np.nan
                row[f"avg_fwd_ret_{h}d%"] = np.nan
                row[f"close_fail_rate_{h}d%"] = np.nan
                row[f"touch_high_rate_{h}d%"] = np.nan
            rows.append(row)
            continue

        per_h = {h: {"touch": [], "close_fail": [], "ret": []} for h in forward_horizons}
        for _, ep in episodes.iterrows():
            high_idx = int(ep["high_idx"])
            anchor_high = float(ep["high"])
            base_close = close[high_idx]
            for h in forward_horizons:
                k = high_idx + h
                end_k = min(k, n - 1)
                window_high = high[high_idx + 1:end_k + 1]
                window_close = close[high_idx + 1:end_k + 1]
                per_h[h]["touch"].append(bool(len(window_high) and (window_high > anchor_high).any()))
                per_h[h]["close_fail"].append(bool(len(window_close) and (window_close > anchor_high).any()))
                if k < n:
                    per_h[h]["ret"].append((close[k] - base_close) / base_close * 100)

        for h in forward_horizons:
            touches, closes_fail, rets = per_h[h]["touch"], per_h[h]["close_fail"], per_h[h]["ret"]
            row[f"touch_high_rate_{h}d%"] = round(float(np.mean(touches)) * 100, 1) if touches else np.nan
            row[f"close_fail_rate_{h}d%"] = round(float(np.mean(closes_fail)) * 100, 1) if closes_fail else np.nan
            if rets:
                rets_arr = np.array(rets)
                row[f"hit_rate_{h}d%"] = round(float((rets_arr < 0).mean()) * 100, 1)
                row[f"avg_fwd_ret_{h}d%"] = round(float(rets_arr.mean()), 2)
            else:
                row[f"hit_rate_{h}d%"] = np.nan
                row[f"avg_fwd_ret_{h}d%"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def pick_min_certain_rise(scan: pd.DataFrame, horizon: int, max_touch_rate: float = 0.0,
                         min_n: int = 10) -> dict | None:
    """Mirror of pick_min_certain_fall for the upside."""
    if scan is None or scan.empty:
        return None
    col = f"touch_high_rate_{horizon}d%"
    if col not in scan.columns:
        return None
    ok = scan[(scan[col] <= max_touch_rate) & (scan["n_episodes"] >= min_n)]
    if ok.empty:
        return None
    return ok.sort_values("rise_pct").iloc[0].to_dict()


def rise_pullback_grid_scan(daily: pd.DataFrame, rise_pcts=DEFAULT_THRESHOLDS,
                            pullback_pcts=DEFAULT_THRESHOLDS, forward_horizons=(3, 5, 10),
                            merge_gap_days: int = 1, require_red_confirmation: bool = False,
                            max_track_days: int = 30) -> pd.DataFrame:
    """Mirror of fall_bounce_grid_scan: every (rise_pct, pullback_pct) pair
    in one table — 'given a rise this big, how much pullback do I actually
    need to see before a call strike above the high is safe.'"""
    rows = []
    for rp in rise_pcts:
        rp = round(float(rp), 2)
        episodes = find_rise_episodes_daily(daily, rise_1d_pct=rp, rise_2d_pct=1e9,
                                            merge_gap_days=merge_gap_days,
                                            require_red_confirmation=require_red_confirmation)
        if episodes.empty:
            continue
        res = pullback_threshold_scan_daily(daily, episodes, thresholds=pullback_pcts,
                                            forward_horizons=forward_horizons,
                                            max_track_days=max_track_days)
        scan = res["scan"]
        if scan.empty:
            continue
        scan = scan.rename(columns={"threshold%": "pullback_pct", "n_triggered": "n_combo"})
        scan.insert(0, "rise_pct", rp)
        rows.append(scan)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def min_pullback_by_rise_size(grid: pd.DataFrame, horizon: int, max_touch_rate: float = 0.0,
                              min_n: int = 10) -> pd.DataFrame:
    """Mirror of min_bounce_by_fall_size: one row per rise_pct, the
    smallest pullback_pct that keeps touch_high_rate at `horizon` days
    at/below max_touch_rate — 'the market just rallied this much — how
    much pullback do I need to see before a call strike above the high is
    safe.'"""
    if grid is None or grid.empty:
        return pd.DataFrame()
    col = f"touch_high_rate_{horizon}d%"
    if col not in grid.columns:
        return pd.DataFrame()
    rows = []
    for rp, sub in grid.groupby("rise_pct"):
        ok = sub[(sub[col] <= max_touch_rate) & (sub["n_combo"] >= min_n)]
        if ok.empty:
            rows.append({"rise_pct": rp, "min_pullback_pct": np.nan, "n_combo": np.nan,
                        f"touch_high_rate_{horizon}d%": np.nan, f"hit_rate_{horizon}d%": np.nan})
            continue
        best = ok.sort_values("pullback_pct").iloc[0]
        rows.append({"rise_pct": rp, "min_pullback_pct": best["pullback_pct"],
                    "n_combo": int(best["n_combo"]),
                    f"touch_high_rate_{horizon}d%": best[col],
                    f"hit_rate_{horizon}d%": best[f"hit_rate_{horizon}d%"]})
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# Dual-confirmation — the case neither the fall-episode nor rise-episode scans
# above ever isolate: a day whose PROPER episode-anchored bounce (PUT side)
# AND episode-anchored pullback (CALL side) trigger confirm on the SAME
# calendar day. Since PUT-safety and CALL-safety are validated as two
# SEPARATE claims (not mutually exclusive), a day satisfying both isn't
# automatically a conflict needing a directional tiebreak — it could just
# mean both sides are protected (an Iron Condor day). This scan measures
# which is actually true, instead of assuming either way.
#
# REBUILT from a first version that compared forward touches against a
# single day's OWN low/high (a shallow, easily-touched level) instead of
# the EPISODE's anchor (the true capitulation low/high, which can walk
# further before the bounce/pullback trigger actually fires) — that version
# scored 51-89% touch rates, wildly inconsistent with the ~0% the validated
# engine finds elsewhere in this file. This version reuses the EXACT same
# anchor-walk trigger mechanism as reversal_threshold_scan_daily /
# pullback_threshold_scan_daily, so its numbers are directly comparable to
# the rest of page 24's validated results.
# ══════════════════════════════════════════════════════════════════════════════

def _dual_confirmation_triggers(daily: pd.DataFrame, bounce_pct: float, pullback_pct: float,
                                fall_trigger_pct: float, rise_trigger_pct: float,
                                merge_gap_days: int, max_track_days: int):
    """Shared core for dual_confirmation_scan (aggregate stats) and
    dual_confirmation_daily_labels (per-day table / live snapshot / chart
    markers) — finds every fall-episode's PUT trigger day (bounce_pct off
    the episode's anchor low, walking the anchor down on new lower lows
    exactly like reversal_threshold_scan_daily) and every rise-episode's
    CALL trigger day (pullback_pct off the episode's anchor high, mirrored).
    Returns (put_triggers, call_triggers) — each a dict of trigger day index
    -> anchor level at the moment of trigger, one entry per episode that
    actually confirms within max_track_days."""
    d = _norm_ohlc(daily)
    close, high, low = d["close"].to_numpy(), d["high"].to_numpy(), d["low"].to_numpy()
    n = len(d)

    fall_episodes = find_fall_episodes_daily(daily, fall_1d_pct=fall_trigger_pct, fall_2d_pct=1e9,
                                             merge_gap_days=merge_gap_days,
                                             require_green_confirmation=False)
    rise_episodes = find_rise_episodes_daily(daily, rise_1d_pct=rise_trigger_pct, rise_2d_pct=1e9,
                                             merge_gap_days=merge_gap_days,
                                             require_red_confirmation=False)

    put_triggers: dict[int, float] = {}
    for _, ep in fall_episodes.iterrows():
        anchor_idx, anchor_low = int(ep["low_idx"]), float(ep["low"])
        j, steps = anchor_idx + 1, 0
        while j < n and steps < max_track_days:
            if low[j] < anchor_low:
                anchor_low, anchor_idx = float(low[j]), j
            if (high[j] - anchor_low) / anchor_low * 100 >= bounce_pct:
                put_triggers.setdefault(j, anchor_low)
                break
            j += 1
            steps += 1

    call_triggers: dict[int, float] = {}
    for _, ep in rise_episodes.iterrows():
        anchor_idx, anchor_high = int(ep["high_idx"]), float(ep["high"])
        j, steps = anchor_idx + 1, 0
        while j < n and steps < max_track_days:
            if high[j] > anchor_high:
                anchor_high, anchor_idx = float(high[j]), j
            if (anchor_high - low[j]) / anchor_high * 100 >= pullback_pct:
                call_triggers.setdefault(j, anchor_high)
                break
            j += 1
            steps += 1

    return put_triggers, call_triggers


def dual_confirmation_daily_labels(
        daily: pd.DataFrame,
        bounce_pct: float = PINPOINT_PRESETS[ACTIVE_PINPOINT_PRESET]["bounce_pct"],
        pullback_pct: float = PINPOINT_PRESETS[ACTIVE_PINPOINT_PRESET]["pullback_pct"],
        fall_trigger_pct: float = PINPOINT_PRESETS[ACTIVE_PINPOINT_PRESET]["fall_trigger_pct"],
        rise_trigger_pct: float = PINPOINT_PRESETS[ACTIVE_PINPOINT_PRESET]["rise_trigger_pct"],
        merge_gap_days: int = PINPOINT_PRESETS[ACTIVE_PINPOINT_PRESET]["merge_gap_days"],
        max_track_days: int = 30) -> pd.DataFrame:
    """Per-day table — one row per trading day with its Pinpoint label
    (PUT_ONLY / CALL_ONLY / BOTH / NEITHER) and the relevant anchor level(s),
    for the live snapshot (today's row), a historical verification table
    (last N rows), and chart markers (every PUT_ONLY/CALL_ONLY row). Same
    trigger definitions as dual_confirmation_scan — see that function's
    docstring for the full rationale."""
    d = _norm_ohlc(daily)
    n = len(d)
    if n < 5:
        return pd.DataFrame()

    put_triggers, call_triggers = _dual_confirmation_triggers(
        daily, bounce_pct, pullback_pct, fall_trigger_pct, rise_trigger_pct,
        merge_gap_days, max_track_days)

    label = np.full(n, "NEITHER", dtype=object)
    anchor_low_col = np.full(n, np.nan)
    anchor_high_col = np.full(n, np.nan)
    for idx, anchor in put_triggers.items():
        label[idx] = "BOTH" if idx in call_triggers else "PUT_ONLY"
        anchor_low_col[idx] = anchor
    for idx, anchor in call_triggers.items():
        label[idx] = "BOTH" if idx in put_triggers else "CALL_ONLY"
        anchor_high_col[idx] = anchor

    return pd.DataFrame({
        "date": d.index, "close": d["close"].to_numpy(), "label": label,
        "anchor_low": anchor_low_col, "anchor_high": anchor_high_col,
    }).set_index("date")


def dual_confirmation_scan(
        daily: pd.DataFrame,
        bounce_pct: float = PINPOINT_PRESETS[ACTIVE_PINPOINT_PRESET]["bounce_pct"],
        pullback_pct: float = PINPOINT_PRESETS[ACTIVE_PINPOINT_PRESET]["pullback_pct"],
        fall_trigger_pct: float = PINPOINT_PRESETS[ACTIVE_PINPOINT_PRESET]["fall_trigger_pct"],
        rise_trigger_pct: float = PINPOINT_PRESETS[ACTIVE_PINPOINT_PRESET]["rise_trigger_pct"],
        merge_gap_days: int = PINPOINT_PRESETS[ACTIVE_PINPOINT_PRESET]["merge_gap_days"],
        max_track_days: int = 30,
        forward_horizons=(3, 5, 10)) -> pd.DataFrame:
    """Finds every fall-episode's PUT trigger day (bounce_pct off the
    episode's anchor low, walking the anchor down on new lower lows exactly
    like reversal_threshold_scan_daily) and every rise-episode's CALL
    trigger day (pullback_pct off the episode's anchor high, mirrored),
    then classifies each trigger day as PUT_ONLY / CALL_ONLY / BOTH
    depending on whether the other side ALSO triggered that same day. Days
    with neither trigger are NEITHER (touch rates not meaningful there — no
    anchor was ever established, so they're reported as n only).

    Forward touch tracking uses each side's PROPER anchor (not the single
    day's own low/high) — the anchor_low from the fall episode that
    triggered (which may sit well before the trigger day itself, and may
    have walked down multiple times), and the anchor_high from the rise
    episode, matching reversal_threshold_scan_daily/
    pullback_threshold_scan_daily exactly. The BOTH row directly answers
    "on a day that confirms both ways, which side actually breaches more" —
    compare its touch_low_rate vs touch_high_rate columns."""
    d = _norm_ohlc(daily)
    close, high, low = d["close"].to_numpy(), d["high"].to_numpy(), d["low"].to_numpy()
    n = len(d)
    if n < 5:
        return pd.DataFrame()

    put_triggers, call_triggers = _dual_confirmation_triggers(
        daily, bounce_pct, pullback_pct, fall_trigger_pct, rise_trigger_pct,
        merge_gap_days, max_track_days)

    put_days, call_days = set(put_triggers), set(call_triggers)
    both_days = put_days & call_days
    put_only_days = put_days - both_days
    call_only_days = call_days - both_days
    neither_days = set(range(n)) - put_days - call_days

    def _score(idxs, use_put_anchor: bool, use_call_anchor: bool) -> dict:
        row = {"n": int(len(idxs))}
        for h in forward_horizons:
            touch_low, touch_high, rets = [], [], []
            for t in idxs:
                end_k = min(t + h, n - 1)
                if end_k <= t:
                    continue
                if use_put_anchor:
                    window_low = low[t + 1:end_k + 1]
                    touch_low.append(bool(len(window_low) and (window_low < put_triggers[t]).any()))
                if use_call_anchor:
                    window_high = high[t + 1:end_k + 1]
                    touch_high.append(bool(len(window_high) and (window_high > call_triggers[t]).any()))
                rets.append((close[end_k] - close[t]) / close[t] * 100)
            row[f"touch_low_rate_{h}d%"] = round(float(np.mean(touch_low)) * 100, 1) if touch_low else np.nan
            row[f"touch_high_rate_{h}d%"] = round(float(np.mean(touch_high)) * 100, 1) if touch_high else np.nan
            row[f"avg_fwd_ret_{h}d%"] = round(float(np.mean(rets)), 2) if rets else np.nan
        return row

    rows = [
        {"bucket": "PUT_ONLY", **_score(put_only_days, True, False)},
        {"bucket": "CALL_ONLY", **_score(call_only_days, False, True)},
        {"bucket": "BOTH", **_score(both_days, True, True)},
        {"bucket": "NEITHER", **_score(neither_days, False, False)},
    ]
    return pd.DataFrame(rows)


def same_day_bounce_scan(daily: pd.DataFrame, bounce_pcts=DEFAULT_THRESHOLDS,
                         forward_horizons=(3, 5, 10)) -> pd.DataFrame:
    """The naive, no-merge, no-anchor version of the low-side signal: does
    TODAY's close sit bounce_pct% above TODAY's OWN low (close is the ~3:25pm
    proxy - daily bars carry no intraday ticks), with no episode-merging and
    no multi-day anchor tracking at all. For each threshold, reports how
    often TODAY's own low gets touched again within the next h trading days.
    Directly answers "if today's close is X% above today's low, is today's
    low safe for N days" without needing to track a running low across
    multiple days - contrast with reversal_threshold_scan_daily, which asks
    the same safety question but off an anchor that may be several days old."""
    d = _norm_ohlc(daily)
    close, low = d["close"].to_numpy(), d["low"].to_numpy()
    n = len(d)
    bounce_today = (close - low) / low * 100

    rows = []
    for thr in bounce_pcts:
        idxs = np.where(bounce_today >= thr)[0]
        row = {"bounce_pct": float(thr), "n": int(len(idxs))}
        for h in forward_horizons:
            touch = []
            for t in idxs:
                end_k = min(t + h, n - 1)
                if end_k <= t:
                    continue
                touch.append(bool((low[t + 1:end_k + 1] < low[t]).any()))
            row[f"touch_low_rate_{h}d%"] = round(float(np.mean(touch)) * 100, 1) if touch else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def same_day_pullback_scan(daily: pd.DataFrame, pullback_pcts=DEFAULT_THRESHOLDS,
                           forward_horizons=(3, 5, 10)) -> pd.DataFrame:
    """Mirror of same_day_bounce_scan for the high side: does today's close
    sit pullback_pct% below today's OWN high, no merging/anchor tracking.
    For each threshold, reports how often today's own high gets touched
    again within the next h trading days."""
    d = _norm_ohlc(daily)
    close, high = d["close"].to_numpy(), d["high"].to_numpy()
    n = len(d)
    pullback_today = (high - close) / high * 100

    rows = []
    for thr in pullback_pcts:
        idxs = np.where(pullback_today >= thr)[0]
        row = {"pullback_pct": float(thr), "n": int(len(idxs))}
        for h in forward_horizons:
            touch = []
            for t in idxs:
                end_k = min(t + h, n - 1)
                if end_k <= t:
                    continue
                touch.append(bool((high[t + 1:end_k + 1] > high[t]).any()))
            row[f"touch_high_rate_{h}d%"] = round(float(np.mean(touch)) * 100, 1) if touch else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def rolling_low_bounce_scan(daily: pd.DataFrame, lookback_days: int = 2,
                            bounce_pcts=DEFAULT_THRESHOLDS,
                            forward_horizons=(3, 5, 10)) -> pd.DataFrame:
    """Bounded middle ground between same_day_bounce_scan (lookback_days=1:
    anchor = today's own low) and the full open-ended episode anchor used by
    reversal_threshold_scan_daily/Pinpoint. Anchor = the lowest low over the
    last `lookback_days` days INCLUDING today (a fixed, small window - no
    open-ended walk). lookback_days=2 is "today's low is at/above yesterday's
    low, i.e. the decline paused" - the user's proposed rule. Trigger: today's
    high bounces bounce_pct% off that rolling anchor. Forward touch checked
    against the SAME anchor level, starting the day after."""
    d = _norm_ohlc(daily)
    high, low = d["high"].to_numpy(), d["low"].to_numpy()
    n = len(d)
    anchor = pd.Series(low).rolling(lookback_days, min_periods=lookback_days).min().to_numpy()

    rows = []
    for thr in bounce_pcts:
        idxs = [t for t in range(n) if not np.isnan(anchor[t]) and
               (high[t] - anchor[t]) / anchor[t] * 100 >= thr]
        row = {"bounce_pct": float(thr), "n": int(len(idxs))}
        for h in forward_horizons:
            touch = []
            for t in idxs:
                end_k = min(t + h, n - 1)
                if end_k <= t:
                    continue
                touch.append(bool((low[t + 1:end_k + 1] < anchor[t]).any()))
            row[f"touch_low_rate_{h}d%"] = round(float(np.mean(touch)) * 100, 1) if touch else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def rolling_high_pullback_scan(daily: pd.DataFrame, lookback_days: int = 2,
                               pullback_pcts=DEFAULT_THRESHOLDS,
                               forward_horizons=(3, 5, 10)) -> pd.DataFrame:
    """Mirror of rolling_low_bounce_scan for the high side. Anchor = the
    highest high over the last `lookback_days` days including today.
    lookback_days=2 is "today's high is at/below yesterday's high, i.e. the
    rise paused." Trigger: today's low pulls back pullback_pct% off that
    rolling anchor."""
    d = _norm_ohlc(daily)
    high, low = d["high"].to_numpy(), d["low"].to_numpy()
    n = len(d)
    anchor = pd.Series(high).rolling(lookback_days, min_periods=lookback_days).max().to_numpy()

    rows = []
    for thr in pullback_pcts:
        idxs = [t for t in range(n) if not np.isnan(anchor[t]) and
               (anchor[t] - low[t]) / anchor[t] * 100 >= thr]
        row = {"pullback_pct": float(thr), "n": int(len(idxs))}
        for h in forward_horizons:
            touch = []
            for t in idxs:
                end_k = min(t + h, n - 1)
                if end_k <= t:
                    continue
                touch.append(bool((high[t + 1:end_k + 1] > anchor[t]).any()))
            row[f"touch_high_rate_{h}d%"] = round(float(np.mean(touch)) * 100, 1) if touch else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def compare_pinpoint_presets(daily: pd.DataFrame, presets: dict = None,
                             forward_horizons=(3, 5, 10)) -> pd.DataFrame:
    """Runs dual_confirmation_scan once per named preset in PINPOINT_PRESETS (or a
    custom presets dict passed in) and stacks every result into ONE comparison table,
    tagged by a 'preset' column — so testing several parameter sets never requires
    touching sliders one at a time. 'current_live' is always the baseline row to
    compare everything else against; it's whatever ACTIVE_PINPOINT_PRESET points to
    in dual_confirmation_daily_labels/dual_confirmation_scan's own defaults, so this
    table and the live page always describe the same thing unless you deliberately
    pass a different presets dict here."""
    presets = presets or PINPOINT_PRESETS
    rows = []
    for name, p in presets.items():
        scan = dual_confirmation_scan(daily, bounce_pct=p["bounce_pct"], pullback_pct=p["pullback_pct"],
                                      fall_trigger_pct=p["fall_trigger_pct"],
                                      rise_trigger_pct=p["rise_trigger_pct"],
                                      merge_gap_days=p["merge_gap_days"],
                                      forward_horizons=forward_horizons)
        scan.insert(0, "preset", name)
        rows.append(scan)
    return pd.concat(rows, ignore_index=True)
