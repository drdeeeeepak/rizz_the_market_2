# analytics/signal_lab.py
# Generic signal backtest harness — rank ANY page's signal against forward price
# outcomes, on the SAME machinery as analytics/backtest.py (the Conviction-table
# optimizer): forward_outcomes() for the price side, _bucket_stats()/qcut for the
# bucket scan. This module adds nothing new on the price/outcome side — it only
# adds a uniform way to score an arbitrary SIGNAL against those outcomes.
#
# SIGNAL CONTRACT
#   A "signal" is a pandas Series indexed by trading DATE (normalized, no
#   time-of-day), holding a directional score:
#       > 0      → the adapter believes price will be HIGHER over the horizon
#       < 0      → believes LOWER
#       0 / NaN  → no opinion that day (excluded from hit-rate/expectancy;
#                  a day simply missing from the Series is the same as NaN)
#   Magnitude need not be ±1 — continuous scores (raw RSI, %B, a phase index)
#   are fine: only the SIGN feeds hit-rate/expectancy, the raw value feeds
#   Spearman correlation and the quantile bucket scan.
#
# ADAPTER CONTRACT — see analytics/signal_adapters.py
#   def adapt_xxx(**raw_ohlcv_frames) -> pd.Series
#   Each adapter returns ONE signal value per trading day, computed causally
#   (no look-ahead), reusing the real engine's pure functions wherever the
#   engine has no I/O side effects (falling back to a rolling/expanding replay
#   of those same functions where the engine only exposes a live snapshot).

import numpy as np
import pandas as pd

from analytics import backtest as bt
from analytics import intraday_conviction as ic

DEFAULT_HORIZONS = (5, 10)


# ══════════════════════════════════════════════════════════════════════════════
# Alignment helpers
# ══════════════════════════════════════════════════════════════════════════════

def _norm_daily(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    d.index = d.index.normalize()
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in d.columns]
    return d[keep].sort_index()


def _align_signal(signal: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Normalize a signal's index to dates and align to the price index.
    No ffill — a date absent from the signal is 'no opinion', not carried
    forward from the prior reading."""
    if signal is None or len(signal) == 0:
        return pd.Series(np.nan, index=index)
    s = pd.to_numeric(signal, errors="coerce").copy()
    s.index = pd.to_datetime(s.index).normalize()
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(index)


# ══════════════════════════════════════════════════════════════════════════════
# Core scorecard
# ══════════════════════════════════════════════════════════════════════════════

def signal_stats(signal: pd.Series, outcomes: pd.DataFrame, h0: int) -> dict:
    """n / n_active / hit_rate% / expectancy% / spearman for one signal at the
    primary horizon h0.
      hit_rate   = % of signal-active days where sign(forward ret) == sign(signal)
      expectancy = mean(sign(signal) * forward ret%) over active days — the
                   average forward move IN the signal's called direction
      spearman   = rank correlation between the raw signal value and the
                   forward return (works for continuous scores too)"""
    df = pd.DataFrame({"sig": signal}).join(outcomes, how="inner")
    df = df[df["sig"].notna() & df[f"ret{h0}"].notna()]
    n = int(len(df))
    if n == 0:
        return {"n": 0, "n_active": 0, "hit_rate": np.nan, "expectancy": np.nan, "spearman": np.nan}
    active = df[df["sig"] != 0]
    n_active = int(len(active))
    if n_active:
        direction = np.sign(active["sig"])
        hit = float((np.sign(active[f"ret{h0}"]) == direction).mean() * 100)
        expectancy = float((direction * active[f"ret{h0}"]).mean())
    else:
        hit, expectancy = np.nan, np.nan
    spearman = float(df["sig"].corr(df[f"ret{h0}"], method="spearman")) if n >= 5 else np.nan
    return {
        "n": n, "n_active": n_active,
        "hit_rate": round(hit, 1) if hit == hit else hit,
        "expectancy": round(expectancy, 3) if expectancy == expectancy else expectancy,
        "spearman": round(spearman, 3) if spearman == spearman else spearman,
    }


def bucket_scan(signal: pd.Series, outcomes: pd.DataFrame, horizons=DEFAULT_HORIZONS,
                nbins: int = 5) -> pd.DataFrame:
    """Quantile-bucket the raw signal value and report the forward edge per
    bucket — same shape/columns as backtest.column_cutoff_scan's per-column
    tables (n, avg_ret, pct_up, breach rates, avg_maxup/dn)."""
    h0 = horizons[0]
    df = pd.DataFrame({"_v": signal}).join(outcomes, how="inner")
    df = df[df["_v"].notna() & df[f"ret{h0}"].notna()]
    if len(df) < nbins * 3:
        return pd.DataFrame()
    try:
        df["_bin"] = pd.qcut(df["_v"], nbins, duplicates="drop")
    except Exception:
        df["_bin"] = pd.cut(df["_v"], nbins)
    return bt._bucket_stats(df.groupby("_bin", observed=True), h0)


def evaluate_signal(daily: pd.DataFrame, signal: pd.Series, name: str = "signal",
                    horizons=DEFAULT_HORIZONS, call_pct: float = 3.5, put_pct: float = 4.0,
                    nbins: int = 5) -> dict:
    """One-call driver for a single signal against DAILY OHLCV: forward
    outcomes + scorecard + bucket scan + weekly-move distribution (with
    strike-breach rates at the primary horizon). Mirrors the shape of
    analytics.backtest.run_backtest()'s return dict so a page can render
    either uniformly."""
    d = _norm_daily(daily)
    outc = bt.forward_outcomes(d, horizons=horizons, call_pct=call_pct, put_pct=put_pct)
    sig = _align_signal(signal, d.index)
    stats = signal_stats(sig, outc, horizons[0])
    bucket = bucket_scan(sig, outc, horizons=horizons, nbins=nbins)
    dist = bt.weekly_move_distribution(outc, horizons=horizons, call_pct=call_pct, put_pct=put_pct)
    detail = pd.DataFrame({"signal": sig}).join(outc, how="inner")
    span = f"{d.index.min():%d-%b-%Y} → {d.index.max():%d-%b-%Y}" if not d.empty else "—"
    return {
        "name": name, **stats,
        "bucket": bucket, "distribution": dist, "detail": detail,
        "span": span, "horizons": horizons,
    }


def rank_signals(results: list) -> pd.DataFrame:
    """Leaderboard — one row per evaluate_signal() result, ranked by the size
    of the edge (|expectancy|) regardless of direction."""
    rows = []
    for r in results:
        rows.append({
            "signal": r["name"], "n": r["n"], "n_active": r["n_active"],
            "hit_rate%": r["hit_rate"], "expectancy%": r["expectancy"],
            "spearman": r["spearman"], "span": r["span"],
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["_abs_exp"] = out["expectancy%"].abs()
    out = out.sort_values("_abs_exp", ascending=False, na_position="last").drop(columns="_abs_exp")
    return out.reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# Walk-forward / out-of-sample check
# ══════════════════════════════════════════════════════════════════════════════

def walk_forward(daily: pd.DataFrame, signal: pd.Series, horizons=DEFAULT_HORIZONS,
                 call_pct: float = 3.5, put_pct: float = 4.0, by: str = "year") -> pd.DataFrame:
    """Split the sample by calendar year (by='year') or into two halves
    (by='half') and report the scorecard per split — does the edge survive
    out of the one regime it was found in, or was it a single-sample fluke?"""
    d = _norm_daily(daily)
    outc = bt.forward_outcomes(d, horizons=horizons, call_pct=call_pct, put_pct=put_pct)
    sig = _align_signal(signal, d.index)
    h0 = horizons[0]
    if by == "half" and len(d) >= 2:
        mid = d.index[len(d) // 2]
        groups = {"H1 (early)": d.index < mid, "H2 (late)": d.index >= mid}
    else:
        groups = {str(y): (d.index.year == y) for y in sorted(set(d.index.year))}
    rows = []
    for label, mask in groups.items():
        idx = d.index[mask]
        if len(idx) == 0:
            continue
        st = signal_stats(sig.reindex(idx), outc.reindex(idx), h0)
        rows.append({"split": label, **st})
    return pd.DataFrame(rows)


def rsi_fade_walk_forward(daily: pd.DataFrame, horizons=DEFAULT_HORIZONS,
                          rsi_thresh: float = 62.0, bb_thresh: float = 45.0,
                          call_pct: float = 3.5, put_pct: float = 4.0,
                          by: str = "year") -> dict:
    """Out-of-sample check for the specific OVERBOUGHT-FADE rule the Conviction
    backtest (page 22) found: SHORT/sell-CALLs when RSI >= rsi_thresh AND
    Bull−Bear >= bb_thresh. Reuses build_conviction_history()/forward_outcomes()
    unchanged — this only re-encodes that exact rule as a signal (-1 = fade/
    short, 0 = no read) and walk-forward-splits it by year, to see whether the
    edge found in the ~2y sample holds up regime-by-regime rather than being a
    single-sample artefact.
    Returns {'signal': the -1/0 Series, 'overall': signal_stats dict,
             'by_split': per-split DataFrame}."""
    conv = bt.build_conviction_history(daily)
    d = _norm_daily(daily)
    outc = bt.forward_outcomes(d, horizons=horizons, call_pct=call_pct, put_pct=put_pct)
    if conv.empty or "RSI" not in conv.columns or "Bull−Bear" not in conv.columns:
        empty = pd.Series(dtype=float)
        return {"signal": empty, "overall": signal_stats(empty, outc, horizons[0]),
                "by_split": pd.DataFrame()}
    rsi = pd.to_numeric(conv["RSI"], errors="coerce")
    bb = pd.to_numeric(conv["Bull−Bear"], errors="coerce")
    fade = (rsi >= rsi_thresh) & (bb >= bb_thresh)
    signal = pd.Series(np.where(fade, -1.0, 0.0), index=conv.index)
    signal.index = pd.to_datetime(signal.index).normalize()
    h0 = horizons[0]
    overall = signal_stats(_align_signal(signal, d.index), outc, h0)
    by_split = walk_forward(daily, signal, horizons=horizons, call_pct=call_pct,
                            put_pct=put_pct, by=by)
    return {"signal": signal, "overall": overall, "by_split": by_split}


# ══════════════════════════════════════════════════════════════════════════════
# Dow Theory — which retrace-% zone is actually the best entry?
# ══════════════════════════════════════════════════════════════════════════════

def dow_retrace_bucket_scan(daily: pd.DataFrame, df_1h: pd.DataFrame,
                            horizons=DEFAULT_HORIZONS, window_days: int = None,
                            bins=(0, 30, 60, 90, 101)) -> pd.DataFrame:
    """Is 60%+ retrace (labelled PRIME) actually a better entry than 30-45%
    (labelled GOOD), or is that just a wider stop dressed up as a label?
    Buckets every UPTREND day by (sequence, retrace_pct) assuming you ALWAYS
    buy there, and every DOWNTREND day by (sequence, retrace_pct) assuming
    you ALWAYS short there — then reports forward hit-rate/expectancy per
    bucket, empirically.

    `sequence` matters because retrace_pct means something different
    depending on it (see dow_theory._retrace_depth): RISING = bouncing AWAY
    from the most recent pivot low (0%=at the low, 100%=back at the old
    high) — this is the UT-1/DT-1 'GOOD vs PRIME' question directly. FALLING
    = pulling back FROM the most recent pivot high toward the old low
    (0%=at the high, 100%=back at the old low) — in an UPTREND this is the
    UT-3 retest-the-floor case (90-101% bucket); in a DOWNTREND it's the
    leg that follows a fresh new low.

    Reuses signal_adapters._dow_theory_frame (the SAME rolling-window pivot/
    structure/sequence/retrace computation the structure-sign and leg-health
    adapters already use) plus backtest.forward_outcomes — nothing new is
    computed here, just re-sliced by retrace_pct instead of by signal sign."""
    from analytics import signal_adapters as sa   # local import — signal_adapters imports nothing from here
    window_days = window_days or sa.DOW_PHASE_DAYS
    frame = sa._dow_theory_frame(df_1h, window_days)
    if frame.empty:
        return pd.DataFrame()
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index).normalize()

    d = _norm_daily(daily)
    outc = bt.forward_outcomes(d, horizons=horizons)
    h0 = horizons[0]

    df = frame.join(outc, how="inner")
    df = df[df[f"ret{h0}"].notna() & df["retrace_pct"].notna()
            & df["structure"].isin(["UPTREND", "DOWNTREND"])].copy()
    if df.empty:
        return pd.DataFrame()

    labels = [f"{int(bins[i])}-{int(bins[i + 1])}%" for i in range(len(bins) - 1)]
    df["retrace_bucket"] = pd.cut(pd.to_numeric(df["retrace_pct"]), bins=bins,
                                  labels=labels, right=False)

    rows = []
    for (structure, sequence, rb), g in df.groupby(
            ["structure", "sequence", "retrace_bucket"], observed=True):
        if len(g) == 0:
            continue
        direction = 1.0 if structure == "UPTREND" else -1.0
        ret = g[f"ret{h0}"] * direction
        fav = g[f"up{h0}"] if direction > 0 else -g[f"dn{h0}"]
        adv = -g[f"dn{h0}"] if direction > 0 else g[f"up{h0}"]
        rows.append({
            "structure": structure, "sequence": sequence, "retrace_bucket": rb,
            "n": int(len(g)),
            "hit_rate%": round(float((ret > 0).mean() * 100), 1),
            f"avg_ret{h0}%": round(float(ret.mean()), 3),
            f"avg_favorable{h0}%": round(float(fav.mean()), 2),
            f"avg_adverse{h0}%": round(float(adv.mean()), 2),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    struct_order = {"UPTREND": 0, "DOWNTREND": 1}
    seq_order = {"RISING": 0, "FALLING": 1}
    out["_so"] = out["structure"].map(struct_order)
    out["_qo"] = out["sequence"].map(seq_order)
    out = out.sort_values(["_so", "_qo", "retrace_bucket"]).drop(columns=["_so", "_qo"])
    return out.reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# Roll-rule optimizer — "when drift from anchor hits X%, roll the profit leg in
# by Y%, does it survive to expiry?"
# ══════════════════════════════════════════════════════════════════════════════

def _roll_rule_simulate(d: pd.DataFrame, anchor_ts, end_ts, x_pct: float, y_pct: float,
                        call_pct: float, put_pct: float) -> dict:
    """One weekly cycle, one (X, Y) pair. Starting CALL = anchor*(1+call_pct%),
    PUT = anchor*(1-put_pct%). Each time drift from ANCHOR reaches a NEW
    multiple of X% in one direction, the leg on the OTHER side (now safer)
    rolls inward by Y% of its OWN current strike (not re-centered to spot/
    anchor — a shift of the strike itself, so repeated rolls compound).
    Breach = a day's CLOSE (not intraday high/low) at or beyond a strike.
    Walks day-by-day from the day after anchor_ts through end_ts (inclusive);
    a single big gap can cross multiple X-thresholds in one day (handled by
    the while loops, not just an if)."""
    anchor = float(d.loc[anchor_ts, "close"])
    ce = anchor * (1 + call_pct / 100)
    pe = anchor * (1 - put_pct / 100)
    roll_up = roll_down = 0   # how many X-multiples already used, upside/downside
    window = d[(d.index > anchor_ts) & (d.index <= end_ts)]
    for ts, row in window.iterrows():
        close = float(row["close"])
        drift = (close - anchor) / anchor * 100
        while drift >= (roll_up + 1) * x_pct:
            pe *= (1 + y_pct / 100)   # PUT is the profit leg on an up-move — roll it up/inward
            roll_up += 1
        while drift <= -(roll_down + 1) * x_pct:
            ce *= (1 - y_pct / 100)   # CALL is the profit leg on a down-move — roll it down/inward
            roll_down += 1
        if close >= ce:
            return {"survived": False, "rolls": roll_up + roll_down,
                    "breach_side": "call", "breach_was_rolled": roll_down > 0}
        if close <= pe:
            return {"survived": False, "rolls": roll_up + roll_down,
                    "breach_side": "put", "breach_was_rolled": roll_up > 0}
    return {"survived": True, "rolls": roll_up + roll_down,
            "breach_side": None, "breach_was_rolled": None}


def _roll_rule_aggregate(results: list) -> dict:
    n = len(results)
    if n == 0:
        return {"n": 0, "survival_rate%": np.nan, "avg_rolls": np.nan,
                "breach_on_rolled_leg%": np.nan, "breach_on_original_leg%": np.nan}
    survived = sum(1 for r in results if r["survived"])
    avg_rolls = float(np.mean([r["rolls"] for r in results]))
    rolled_breach = sum(1 for r in results if not r["survived"] and r["breach_was_rolled"])
    orig_breach = sum(1 for r in results if not r["survived"] and r["breach_was_rolled"] is False)
    return {
        "n": n,
        "survival_rate%": round(survived / n * 100, 1),
        "avg_rolls": round(avg_rolls, 2),
        "breach_on_rolled_leg%": round(rolled_breach / n * 100, 1),
        "breach_on_original_leg%": round(orig_breach / n * 100, 1),
    }


def roll_rule_scan(daily: pd.DataFrame, x_grid=(0.5, 1.0, 1.5, 2.0, 2.5),
                   y_grid=(0.25, 0.5, 0.75, 1.0, 1.5), call_pct: float = 3.0,
                   put_pct: float = 3.5) -> dict:
    """Grid-search which (X% drift trigger, Y% roll-in size) survives best,
    for BOTH the near (this-week) and biweekly (next-week, since positions
    are held two cycles) expiry windows.

    Anchor = each Tuesday's close actually present in `daily` (a Tuesday
    market holiday just skips that week's anchor — same simplification the
    rest of this app makes only implicitly). near_end = the following
    Tuesday; far_end = the Tuesday after THAT (two cycles out).

    Returns {'near': DataFrame, 'far': DataFrame, 'best_near': dict,
    'best_far': dict, 'call_pct':, 'put_pct':} — each DataFrame has one row
    per (x%, y%) with n / survival_rate% / avg_rolls / breach_on_rolled_leg%
    / breach_on_original_leg% (the last two only among the FAILURES, telling
    you whether a loss came from the rule itself reversing on you, or from
    the original untouched threatened leg finally giving way — a risk this
    rule was never trying to solve)."""
    d = _norm_daily(daily)
    tuesdays = sorted(d.index[d.index.weekday == 1])
    cycles = []
    for i in range(len(tuesdays) - 1):
        anchor_ts = tuesdays[i]
        near_end = tuesdays[i + 1]
        far_end = tuesdays[i + 2] if i + 2 < len(tuesdays) else None
        cycles.append((anchor_ts, near_end, far_end))

    rows_near, rows_far = [], []
    for x in x_grid:
        for y in y_grid:
            near_res, far_res = [], []
            for anchor_ts, near_end, far_end in cycles:
                near_res.append(_roll_rule_simulate(d, anchor_ts, near_end, x, y, call_pct, put_pct))
                if far_end is not None:
                    far_res.append(_roll_rule_simulate(d, anchor_ts, far_end, x, y, call_pct, put_pct))
            rows_near.append({"x%": x, "y%": y, **_roll_rule_aggregate(near_res)})
            if far_res:
                rows_far.append({"x%": x, "y%": y, **_roll_rule_aggregate(far_res)})

    near_df = pd.DataFrame(rows_near)
    far_df = pd.DataFrame(rows_far)

    def _best(tbl: pd.DataFrame):
        if tbl.empty:
            return None
        # Highest survival rate first; among ties, more rolls = more of the
        # profit leg's premium captured (our only available proxy — no real
        # option premium/IV data in a spot-only backtest).
        t = tbl.sort_values(["survival_rate%", "avg_rolls"], ascending=[False, False])
        return t.iloc[0].to_dict()

    return {"near": near_df, "far": far_df, "best_near": _best(near_df), "best_far": _best(far_df),
            "call_pct": call_pct, "put_pct": put_pct, "n_cycles": len(cycles)}


# ══════════════════════════════════════════════════════════════════════════════
# Anchor-drift continuation vs. mean-reversion — "does Nifty revert below X%
# drift and continue above it?"
# ══════════════════════════════════════════════════════════════════════════════

def _anchor_drift_observations(d: pd.DataFrame, weeks: int = 1) -> pd.DataFrame:
    """Shared row-builder for the anchor-drift scans. anchor_ts is a Tuesday's
    close; end_ts is `weeks` Tuesdays later (1 = the immediately following
    Tuesday, 2 = the Tuesday after that — the biweekly/'far' cycle). Every
    other-than-anchor day strictly inside that window contributes one row:
    its |drift| from anchor at that point, and the signed 'extension' between
    then and the cycle's end (>0 = continuation, <0 = reversion toward/through
    anchor). Same cycle definition as roll_rule_scan."""
    tuesdays = sorted(d.index[d.index.weekday == 1])
    rows = []
    for i in range(len(tuesdays) - weeks):
        anchor_ts, end_ts = tuesdays[i], tuesdays[i + weeks]
        anchor = float(d.loc[anchor_ts, "close"])
        final_drift = (float(d.loc[end_ts, "close"]) - anchor) / anchor * 100
        window = d[(d.index > anchor_ts) & (d.index < end_ts)]
        for ts, row in window.iterrows():
            close = float(row["close"])
            drift_t = (close - anchor) / anchor * 100
            if drift_t == 0:
                continue
            extension = np.sign(drift_t) * (final_drift - drift_t)
            rows.append({
                "abs_drift_t": abs(drift_t),
                "extension": extension,
                "days_remaining": int((end_ts - ts).days),
            })
    return pd.DataFrame(rows)


def anchor_drift_reversion_scan(daily: pd.DataFrame,
                                drift_bins=(0, 1, 2, 3, 5, 100)) -> pd.DataFrame:
    """For every non-Tuesday day inside a weekly Tuesday-anchor cycle, buckets
    that day's CURRENT |drift| from anchor, then checks where price ends up
    at THAT SAME cycle's close (the following Tuesday): did drift EXTEND
    further in the same direction (continuation) or shrink/flip back toward
    anchor (mean-reversion)? Directly tests claims like 'reverts below 2%,
    continues above 2%' with real numbers instead of a hunch.

    extension = sign(drift_t) * (final_drift - drift_t):
        > 0  → price kept moving the SAME way (continuation)
        < 0  → price gave back ground toward/through anchor (reversion)
    continuation_rate% = share of days in that bucket where extension > 0.

    Shares the same Tuesday-anchor cycle definition as roll_rule_scan (each
    calendar Tuesday actually present in `daily`; a Tuesday market holiday
    just skips that week's anchor)."""
    d = _norm_daily(daily)
    labels = [f"{drift_bins[i]}-{drift_bins[i + 1]}%" for i in range(len(drift_bins) - 1)]
    obs = _anchor_drift_observations(d, weeks=1)
    if obs.empty:
        return pd.DataFrame()

    obs = obs.copy()
    obs["bucket"] = pd.cut(obs["abs_drift_t"], bins=drift_bins, labels=labels, right=False)
    agg = obs.groupby("bucket", observed=True).agg(
        n=("extension", "size"),
        **{"continuation_rate%": ("extension", lambda s: round(float((s > 0).mean() * 100), 1))},
        avg_extension_pts=("extension", lambda s: round(float(s.mean()), 3)),
        avg_days_remaining=("days_remaining", lambda s: round(float(s.mean()), 1)),
    )
    return agg.reset_index()


def anchor_drift_optimum_threshold_scan(daily: pd.DataFrame, drift_grid=None,
                                        min_n_per_side: int = 15) -> dict:
    """Find the single drift% breakpoint that best separates 'reverts below
    it' from 'continues above it' — instead of pre-picked buckets, scans a
    grid of candidate thresholds X and scores each one by how well the split
    (abs_drift_t < X) vs (abs_drift_t >= X) matches (reversion) vs
    (continuation), for BOTH the one-week and two-week (biweekly) cycle.

    For each threshold X:
      reversion_rate_below%     = % of below-X observations where extension < 0
      continuation_rate_above%  = % of at/above-X observations where extension > 0
      accuracy%                 = n-weighted average of those two rates — how
                                   often the 'below reverts / above continues'
                                   rule of thumb would have been right overall

    Thresholds where either side has fewer than `min_n_per_side` observations
    are dropped (too few samples to trust). The 'best' row per horizon is the
    threshold with the highest accuracy%.

    Returns {'1_week': {'scan': DataFrame, 'best': dict|None},
             '2_week': {'scan': DataFrame, 'best': dict|None}}."""
    d = _norm_daily(daily)
    if drift_grid is None:
        drift_grid = np.arange(0.25, 5.01, 0.25)

    out = {}
    for weeks, key in ((1, "1_week"), (2, "2_week")):
        obs = _anchor_drift_observations(d, weeks=weeks)
        if obs.empty:
            out[key] = {"scan": pd.DataFrame(), "best": None}
            continue
        rows = []
        for x in drift_grid:
            x = float(x)
            below = obs[obs["abs_drift_t"] < x]
            above = obs[obs["abs_drift_t"] >= x]
            n_below, n_above = int(len(below)), int(len(above))
            if n_below < min_n_per_side or n_above < min_n_per_side:
                continue
            reversion_rate_below = round(float((below["extension"] < 0).mean() * 100), 1)
            continuation_rate_above = round(float((above["extension"] > 0).mean() * 100), 1)
            accuracy = round(
                (n_below * reversion_rate_below + n_above * continuation_rate_above)
                / (n_below + n_above), 1)
            rows.append({
                "threshold%": round(x, 2),
                "n_below": n_below, "reversion_rate_below%": reversion_rate_below,
                "n_above": n_above, "continuation_rate_above%": continuation_rate_above,
                "accuracy%": accuracy,
            })
        scan_df = pd.DataFrame(rows)
        best = None
        if not scan_df.empty:
            best = scan_df.loc[scan_df["accuracy%"].idxmax()].to_dict()
        out[key] = {"scan": scan_df, "best": best}
    return out


def anchor_close_distribution_scan(daily: pd.DataFrame, bin_width: float = 0.5,
                                   cap: float = 5.0) -> dict:
    """Histogram of where Nifty actually CLOSES relative to the Tuesday anchor
    at cycle-end — 1-week (next Tuesday) and 2-week/biweekly (the Tuesday
    after that) — split by direction (up-close vs down-close) and bucketed
    into fixed bin_width% bands, with everything beyond `cap`% grouped into
    one '{cap}%+' catch-all. Unlike anchor_drift_reversion_scan (which tracks
    MID-CYCLE readings vs where the cycle ends up), this only looks at the
    single final close of each cycle — the direct histogram behind picking a
    strike distance: 'what % of weeks/biweeks end up beyond X% from anchor,
    and in which direction'.

    pct_of_all_cycles% is out of ALL cycles for that window (not just that
    direction), so the up-row and down-row percentages for one window sum to
    100% together.

    Only needs `daily` — no 1H/futures data, no adapter suite — so this can
    run standalone without the full Signal Library pipeline.

    Returns {'1_week': DataFrame, '2_week': DataFrame}, each with columns
    direction / bucket / n / pct_of_all_cycles%."""
    d = _norm_daily(daily)
    tuesdays = sorted(d.index[d.index.weekday == 1])

    edges = list(np.arange(0, cap, bin_width)) + [cap, np.inf]
    labels = [f"{edges[i]:g}-{edges[i + 1]:g}%" for i in range(len(edges) - 2)] + [f"{cap:g}%+"]

    def _one(weeks: int) -> pd.DataFrame:
        rows = []
        for i in range(len(tuesdays) - weeks):
            anchor_ts, end_ts = tuesdays[i], tuesdays[i + weeks]
            anchor = float(d.loc[anchor_ts, "close"])
            final_drift = (float(d.loc[end_ts, "close"]) - anchor) / anchor * 100
            rows.append({"direction": "up" if final_drift >= 0 else "down",
                        "abs_drift": abs(final_drift)})
        if not rows:
            return pd.DataFrame()
        obs = pd.DataFrame(rows)
        total = len(obs)
        obs["bucket"] = pd.cut(obs["abs_drift"], bins=edges, labels=labels, right=False)
        out_rows = []
        for direction in ("up", "down"):
            sub = obs[obs["direction"] == direction]
            for label in labels:
                n = int((sub["bucket"] == label).sum())
                out_rows.append({"direction": direction, "bucket": label, "n": n,
                                 "pct_of_all_cycles%": round(n / total * 100, 1)})
        out = pd.DataFrame(out_rows)
        order = {lbl: i for i, lbl in enumerate(labels)}
        out["_o"] = out["bucket"].map(order)
        return out.sort_values(["direction", "_o"]).drop(columns="_o").reset_index(drop=True)

    return {"1_week": _one(1), "2_week": _one(2)}


# ══════════════════════════════════════════════════════════════════════════════
# Strike-shift ladder — a FIXED, asymmetric roll schedule (as opposed to
# roll_rule_scan's grid search): whichever leg sits opposite the move is the
# 'safe' leg, and it shifts inward by a flat %-of-anchor amount (not
# compounding on the current strike) each time |drift| from anchor reaches
# the next trigger — CALL shifts down on a fall, PUT shifts up on a rise.
# ══════════════════════════════════════════════════════════════════════════════

LADDER_TRIGGERS_DEFAULT = (1.0, 2.0, 2.5)   # cumulative |drift from anchor| % that arms each step
LADDER_SHIFTS_DEFAULT = (0.25, 0.25, 1.0)   # % of ANCHOR the safe leg moves at each step


def _strike_shift_ladder_simulate(d: pd.DataFrame, anchor_ts, end_ts, call_pct: float,
                                  put_pct: float, triggers, shifts) -> dict:
    """One cycle, ONE fixed ladder (no grid search — triggers()/shifts() are an
    empty tuple for the no-shift baseline). Each direction's ladder position
    (up_step / dn_step) is tracked independently, so drift crossing triggers
    on one side, then reversing and climbing the OTHER side's ladder, is
    handled correctly — neither counter resets when direction flips.
    Breach = a day's CLOSE (not intraday high/low) at/beyond a strike."""
    anchor = float(d.loc[anchor_ts, "close"])
    ce = anchor * (1 + call_pct / 100)
    pe = anchor * (1 - put_pct / 100)
    up_step = dn_step = 0
    window = d[(d.index > anchor_ts) & (d.index <= end_ts)]
    for ts, row in window.iterrows():
        close = float(row["close"])
        drift = (close - anchor) / anchor * 100
        while up_step < len(triggers) and drift >= triggers[up_step]:
            pe += anchor * shifts[up_step] / 100   # PUT is the safe leg on an up-move
            up_step += 1
        while dn_step < len(triggers) and -drift >= triggers[dn_step]:
            ce -= anchor * shifts[dn_step] / 100   # CALL is the safe leg on a down-move
            dn_step += 1
        if close >= ce:
            return {"survived": False, "steps_used": up_step + dn_step,
                    "breach_side": "call", "breach_was_shifted": dn_step > 0}
        if close <= pe:
            return {"survived": False, "steps_used": up_step + dn_step,
                    "breach_side": "put", "breach_was_shifted": up_step > 0}
    return {"survived": True, "steps_used": up_step + dn_step,
            "breach_side": None, "breach_was_shifted": None}


def _ladder_aggregate(results: list) -> dict:
    n = len(results)
    if n == 0:
        return {"n": 0, "survival_rate%": np.nan, "avg_steps_used": np.nan,
                "breach_on_shifted_leg%": np.nan, "breach_on_original_leg%": np.nan}
    survived = sum(1 for r in results if r["survived"])
    avg_steps = float(np.mean([r["steps_used"] for r in results]))
    shifted_breach = sum(1 for r in results if not r["survived"] and r["breach_was_shifted"])
    orig_breach = sum(1 for r in results if not r["survived"] and r["breach_was_shifted"] is False)
    return {
        "n": n,
        "survival_rate%": round(survived / n * 100, 1),
        "avg_steps_used": round(avg_steps, 2),
        "breach_on_shifted_leg%": round(shifted_breach / n * 100, 1),
        "breach_on_original_leg%": round(orig_breach / n * 100, 1),
    }


def strike_shift_ladder_scan(daily: pd.DataFrame, call_pct: float = 3.0, put_pct: float = 3.5,
                             triggers=LADDER_TRIGGERS_DEFAULT,
                             shifts=LADDER_SHIFTS_DEFAULT) -> dict:
    """Backtests ONE fixed strike-shift ladder (not a parameter grid) against
    every weekly (near) and biweekly (far) Tuesday-anchor cycle, alongside a
    no-shift baseline computed on the SAME cycles for direct comparison.

    Default ladder matches: CALL 3% / PUT 3.5% OTM; whichever leg is safe
    shifts inward by 0.25% of anchor the first time |drift| reaches 1%,
    another 0.25% at 2%, then 1.0% at 2.5% (three steps, then the ladder is
    exhausted — no further shifts past that for the rest of the cycle).

    Returns {'near': {'agg': dict, 'detail': DataFrame}, 'far': {...},
    'call_pct':, 'put_pct':, 'triggers':, 'shifts':, 'n_cycles':}. `detail`
    has one row per cycle (anchor date, survived, steps_used, breach info) —
    'agg' additionally carries 'baseline_survival_rate%' from the no-shift
    run on the identical cycles."""
    d = _norm_daily(daily)
    tuesdays = sorted(d.index[d.index.weekday == 1])
    cycles = []
    for i in range(len(tuesdays) - 1):
        anchor_ts = tuesdays[i]
        near_end = tuesdays[i + 1]
        far_end = tuesdays[i + 2] if i + 2 < len(tuesdays) else None
        cycles.append((anchor_ts, near_end, far_end))

    near_ladder, near_base, near_detail = [], [], []
    far_ladder, far_base, far_detail = [], [], []
    for anchor_ts, near_end, far_end in cycles:
        r_near = _strike_shift_ladder_simulate(d, anchor_ts, near_end, call_pct, put_pct, triggers, shifts)
        b_near = _strike_shift_ladder_simulate(d, anchor_ts, near_end, call_pct, put_pct, (), ())
        near_ladder.append(r_near)
        near_base.append(b_near)
        near_detail.append({"anchor": anchor_ts, **r_near})
        if far_end is not None:
            r_far = _strike_shift_ladder_simulate(d, anchor_ts, far_end, call_pct, put_pct, triggers, shifts)
            b_far = _strike_shift_ladder_simulate(d, anchor_ts, far_end, call_pct, put_pct, (), ())
            far_ladder.append(r_far)
            far_base.append(b_far)
            far_detail.append({"anchor": anchor_ts, **r_far})

    def _bundle(ladder_results, base_results, detail_rows):
        agg = _ladder_aggregate(ladder_results)
        agg["baseline_survival_rate%"] = _ladder_aggregate(base_results)["survival_rate%"]
        return {"agg": agg, "detail": pd.DataFrame(detail_rows)}

    return {"near": _bundle(near_ladder, near_base, near_detail),
            "far": _bundle(far_ladder, far_base, far_detail),
            "call_pct": call_pct, "put_pct": put_pct,
            "triggers": list(triggers), "shifts": list(shifts), "n_cycles": len(cycles)}
