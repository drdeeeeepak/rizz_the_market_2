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
