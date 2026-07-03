# analytics/backtest.py
# Option-seller optimizer for the Conviction engine. Runs enrich()+candle_table() over a
# long DAILY history and asks the questions a premium seller actually has:
#   1. How far does Nifty travel in a week? → how close can I sell (percentile table).
#   2. Which conviction-column readings precede a breach of my sold strikes (+call% / -put%)
#      within the hold window → book-loss / roll warnings vs safe-to-hold.
#
# Fidelity notes (this is a first-cut backtest, not the live engine):
#   • Uses the continuous INDEX (futures contracts only carry ~2–3 months), with synthetic
#     equal volume=1 → VWAP is unweighted and the CVD/volume pillar is a price-action proxy.
#   • Expected-move (Stretch calibration) is a realized-vol estimate per cycle (no VIX history).
#   • Breadth is off (2y of 50-stock history is heavy) → the Brd% column is skipped.

import numpy as np
import pandas as pd

from analytics import intraday_conviction as ic
from data.rolled_positions import check_roll_event as _check_roll_event

# Columns we scan for cutoffs (numeric ones get binned; State is handled categorically).
# Brd% / CVD are only meaningful once real volume + breadth are wired in (see
# build_conviction_history_real / run_backtest_real below) — on the synthetic-volume
# Phase-1 run they'll just show a muted/flat read, which is exactly the caveat this
# backtest already documents.
SCAN_NUMERIC = ["Final", "Bull−Bear", "Conf%", "RSI", "ΔVWAP", "Stretch",
                "Reversal", "Uptrend", "Downtr", "Topping", "Brd%", "CVD"]


def _norm(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.copy()
    d.columns = [c.lower() for c in d.columns]
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    d = d[["open", "high", "low", "close", "volume"]].astype(float).sort_index()
    d["volume"] = 1.0   # equal weight → real VWAP + a close-location CVD proxy (index has none)
    return d


def build_conviction_history(daily: pd.DataFrame, warmup: int = 40) -> pd.DataFrame:
    """Run the anchored (positional) engine cycle-by-cycle with a per-cycle expected-move.
    Returns the candle_table columns indexed by date, plus a 'close' column."""
    d = _norm(daily)
    ret = np.log(d["close"] / d["close"].shift(1))
    rv = ret.rolling(14).std()                                  # realized daily vol
    key = pd.Series([ic._expiry_cycle_key(ix) for ix in d.index], index=d.index)
    cycles = list(dict.fromkeys(key.tolist()))
    pos = {ts: i for i, ts in enumerate(d.index)}
    parts = []
    for ck in cycles:
        idxs = d.index[key == ck]
        if len(idxs) == 0:
            continue
        first, last = pos[idxs[0]], pos[idxs[-1]]
        window = d.iloc[max(0, first - warmup): last + 1]
        rv0 = rv.iloc[first]
        c0 = d["close"].iloc[first]
        em_week = (rv0 * c0 * (5 ** 0.5)) if np.isfinite(rv0) and rv0 > 0 else 0.02 * c0
        w = ic.enrich(window, expected_move_pts=float(em_week), anchored_vwap=True)
        ct = ic.candle_table(w, newest_first=False)
        ct = ct.loc[ct.index.isin(idxs)]
        parts.append(ct)
    if not parts:
        return pd.DataFrame()
    conv = pd.concat(parts).sort_index()
    conv["close"] = d["close"].reindex(conv.index)
    return conv


def forward_outcomes(daily: pd.DataFrame, horizons=(5, 10),
                     call_pct: float = 3.5, put_pct: float = 4.0) -> pd.DataFrame:
    """Per-date forward max-up% / max-down% / close-to-close return over each horizon,
    plus breach flags for the sold strikes at the primary (first) horizon."""
    d = _norm(daily)
    close, high, low = d["close"].to_numpy(), d["high"].to_numpy(), d["low"].to_numpy()
    n = len(d)
    res = pd.DataFrame(index=d.index)
    for h in horizons:
        up, dn, rr = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
        for i in range(n):
            j1 = i + h
            if j1 >= n:
                continue
            c0 = close[i]
            up[i] = high[i + 1:j1 + 1].max() / c0 - 1.0
            dn[i] = low[i + 1:j1 + 1].min() / c0 - 1.0
            rr[i] = close[j1] / c0 - 1.0
        res[f"up{h}"] = up * 100
        res[f"dn{h}"] = dn * 100
        res[f"ret{h}"] = rr * 100
    h0 = horizons[0]
    res["breach_call"] = res[f"up{h0}"] >= call_pct
    res["breach_put"] = res[f"dn{h0}"] <= -put_pct
    return res


def weekly_move_distribution(outcomes: pd.DataFrame, horizons=(5, 10),
                             pcts=(50, 75, 90, 95), call_pct=3.5, put_pct=4.0) -> pd.DataFrame:
    """Percentiles of the forward max-up and max-down moves (how close you can sell),
    plus the base breach rate for the given strikes."""
    rows = []
    for h in horizons:
        up = outcomes[f"up{h}"].dropna()
        dn = (-outcomes[f"dn{h}"]).dropna()          # make the downside positive
        row = {"horizon": f"{h}d", "n": int(min(len(up), len(dn)))}
        for p in pcts:
            row[f"up_p{p}"] = round(float(np.percentile(up, p)), 2) if len(up) else np.nan
            row[f"dn_p{p}"] = round(float(np.percentile(dn, p)), 2) if len(dn) else np.nan
        row["call_breach%"] = round(float((up >= call_pct).mean() * 100), 1) if len(up) else np.nan
        row["put_breach%"] = round(float((dn >= put_pct).mean() * 100), 1) if len(dn) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _bucket_stats(g: "pd.core.groupby.DataFrameGroupBy", h0: int) -> pd.DataFrame:
    cols = g.obj.columns
    d = {
        "n": g.size(),
        f"avg_ret{h0}": g[f"ret{h0}"].mean().round(2),
        f"pct_up{h0}": g[f"ret{h0}"].apply(lambda x: round((x > 0).mean() * 100, 0)),
    }
    if "breach_call" in cols:          # daily/positional runs carry strike-breach flags
        d["call_breach%"] = (g["breach_call"].mean() * 100).round(0)
    if "breach_put" in cols:
        d["put_breach%"] = (g["breach_put"].mean() * 100).round(0)
    d[f"avg_maxup{h0}"] = g[f"up{h0}"].mean().round(2)
    d[f"avg_maxdn{h0}"] = g[f"dn{h0}"].mean().round(2)
    return pd.DataFrame(d)


def column_cutoff_scan(conv: pd.DataFrame, outcomes: pd.DataFrame,
                       horizons=(5, 10), nbins: int = 5) -> dict:
    """For each column, bucket the values and report forward edge + breach rates per bucket.
    Returns {column_name: stats_DataFrame}. Includes a categorical 'State' table."""
    h0 = horizons[0]
    df = conv.join(outcomes, how="inner")
    df = df[df[f"ret{h0}"].notna()]
    out = {}
    # State — categorical
    if "State" in df.columns:
        out["State"] = _bucket_stats(df.groupby("State"), h0).sort_values("n", ascending=False)
    # numeric columns — quantile bins
    for col in SCAN_NUMERIC:
        if col not in df.columns:
            continue
        vals = pd.to_numeric(df[col], errors="coerce")
        sub = df[vals.notna()].copy()
        sub["_v"] = vals[vals.notna()]
        if len(sub) < nbins * 3:
            continue
        try:
            sub["_bin"] = pd.qcut(sub["_v"], nbins, duplicates="drop")
        except Exception:
            sub["_bin"] = pd.cut(sub["_v"], nbins)
        out[col] = _bucket_stats(sub.groupby("_bin", observed=True), h0)
    return out


def run_backtest(daily: pd.DataFrame, horizons=(5, 10),
                 call_pct: float = 3.5, put_pct: float = 4.0, nbins: int = 5) -> dict:
    """One-call driver → dict with 'distribution', 'cutoffs', 'n_rows', 'span'."""
    conv = build_conviction_history(daily)
    outc = forward_outcomes(daily, horizons=horizons, call_pct=call_pct, put_pct=put_pct)
    dist = weekly_move_distribution(outc, horizons=horizons, call_pct=call_pct, put_pct=put_pct)
    cuts = column_cutoff_scan(conv, outc, horizons=horizons, nbins=nbins)
    span = (f"{conv.index.min():%d-%b-%Y} → {conv.index.max():%d-%b-%Y}"
            if not conv.empty else "—")
    return {"distribution": dist, "cutoffs": cuts, "n_rows": int(len(conv)),
            "span": span, "conv": conv, "outcomes": outc}


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — Intraday timing (one-sided selling: when to enter, which side, when to exit)
# Uses intraday FUTURES (real volume → CVD pillar works), session VWAP, forward move
# measured in CANDLES. Better fidelity than the daily/index run above.
# ══════════════════════════════════════════════════════════════════════════════

def _em_from_intraday(d: pd.DataFrame) -> float:
    """One-day expected move (points) from realized daily vol of the intraday series."""
    day_close = d["close"].resample("1D").last().dropna()
    dret = np.log(day_close / day_close.shift(1)).dropna()
    px = float(d["close"].iloc[-1])
    em = float(dret.std() * px) if len(dret) > 3 else 0.006 * px
    return em if np.isfinite(em) and em > 0 else 0.006 * px


def build_conviction_history_intraday(df: pd.DataFrame, anchored: bool = False) -> pd.DataFrame:
    """Run the engine on intraday candles (session VWAP by default, real volume kept).
    Single realized-vol expected-move over the window (flagged approximation)."""
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    d = d.sort_index()
    em = _em_from_intraday(d)
    w = ic.enrich(d, expected_move_pts=em, anchored_vwap=anchored)
    conv = ic.candle_table(w, newest_first=False)
    conv["close"] = d["close"].reindex(conv.index)
    return conv


def forward_outcomes_candles(df: pd.DataFrame, horizons=(6, 13, 25)) -> pd.DataFrame:
    """Forward max-up% / max-down% / close-to-close return over the next K CANDLES
    (no strike breach — intraday is about directional edge & exit timing)."""
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    close, high, low = d["close"].to_numpy(), d["high"].to_numpy(), d["low"].to_numpy()
    n = len(d)
    res = pd.DataFrame(index=d.index)
    for h in horizons:
        up, dn, rr = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
        for i in range(n):
            j1 = i + h
            if j1 >= n:
                continue
            c0 = close[i]
            up[i] = high[i + 1:j1 + 1].max() / c0 - 1.0
            dn[i] = low[i + 1:j1 + 1].min() / c0 - 1.0
            rr[i] = close[j1] / c0 - 1.0
        res[f"up{h}"] = up * 100
        res[f"dn{h}"] = dn * 100
        res[f"ret{h}"] = rr * 100
    return res


def state_horizon_edge(conv: pd.DataFrame, outc: pd.DataFrame, horizons) -> pd.DataFrame:
    """Per State: forward return + up-rate at each horizon — the directional edge and how
    fast it decays (→ entry side and exit timing for one-sided sells)."""
    df = conv.join(outc, how="inner")
    rows = []
    for stt, g in df.groupby("State"):
        row = {"State": stt, "n": int(len(g))}
        for h in horizons:
            if f"ret{h}" in g:
                row[f"ret{h}"] = round(float(g[f"ret{h}"].mean()), 2)
                row[f"up{h}%"] = round(float((g[f"ret{h}"] > 0).mean() * 100), 0)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("n", ascending=False)


def run_intraday_backtest(df: pd.DataFrame, horizons=(6, 13, 25),
                          anchored: bool = False, nbins: int = 5) -> dict:
    """One-call driver for the intraday timing study."""
    conv = build_conviction_history_intraday(df, anchored=anchored)
    outc = forward_outcomes_candles(df, horizons=horizons)
    cuts = column_cutoff_scan(conv, outc, horizons=horizons, nbins=nbins)
    edge = state_horizon_edge(conv, outc, horizons)
    span = (f"{conv.index.min():%d-%b %H:%M} → {conv.index.max():%d-%b %H:%M}"
            if not conv.empty else "—")
    return {"cutoffs": cuts, "state_edge": edge, "n_rows": int(len(conv)),
            "span": span, "conv": conv, "outcomes": outc, "horizons": horizons}


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — Real-volume + breadth-on re-run (data fidelity upgrade)
# Wires in REAL volume (from continuous NIFTY FUTURES,
# data.live_fetcher.get_nifty_fut_continuous) and daily advance/decline breadth,
# so CVD/VWAP/Brd% stop being muted/skipped like they were in the Phase-1 run.
#
# IMPORTANT — continuous-futures ROLL GAPS: Kite's historical_data(continuous=True)
# stitches contracts WITHOUT back-adjustment, so the front-month switch at each
# monthly expiry prints as a real price jump (cost-of-carry basis, not an actual
# market move). Using that price series directly would corrupt every indicator
# with memory (RSI, VWAP/Stretch) AND the forward-outcome labels at every
# rollover. So price here stays on the INDEX (gap-free, same series
# build_conviction_history() uses) — continuous futures contributes ONLY its
# real VOLUME, merged onto the index's OHLC by date. OI is deliberately not
# used in this function (see signal_adapters.adapt_oi_buildup for the one
# place OI is used, with its own roll-jump guard).
# ══════════════════════════════════════════════════════════════════════════════

def daily_advance_breadth(stock_dfs: dict) -> pd.Series:
    """% of Nifty-50 constituents closing ABOVE their own PREVIOUS DAILY CLOSE
    (classic advance/decline breadth), one value per trading day.

    This is a COUSIN of the live Conviction table's Brd% column (which is %
    above SESSION VWAP, intraday) — not a re-test of that exact column — but
    it tests whether breadth adds edge at the daily/weekly horizon a condor
    actually cares about. Needs only daily OHLC for ~50 stocks (cheap,
    multi-year), unlike intraday breadth which needs 50 historical intraday
    pulls per lookback window.

    Fidelity note: uses TODAY's Nifty-50 constituent list applied
    historically (membership/survivorship bias) — acceptable for a base-rate
    scan, not corrected here."""
    if not stock_dfs:
        return pd.Series(dtype=float)
    flags = []
    for sym, df in stock_dfs.items():
        if df is None or df.empty:
            continue
        d = df.copy()
        d.columns = [c.lower() for c in d.columns]
        if "close" not in d.columns:
            continue
        if not isinstance(d.index, pd.DatetimeIndex):
            d.index = pd.to_datetime(d.index)
        d.index = d.index.normalize()
        adv = (d["close"] > d["close"].shift(1)).astype(float)
        flags.append(adv.rename(sym))
    if not flags:
        return pd.Series(dtype=float)
    mat = pd.concat(flags, axis=1)
    return (mat.mean(axis=1) * 100.0).rename("breadth")


def _index_with_futures_volume(daily: pd.DataFrame, fut_daily: pd.DataFrame) -> pd.DataFrame:
    """INDEX OHLC (gap-free) + real VOLUME merged in from continuous futures by
    date. Days where the futures fetch has no matching date (e.g. the roll-day
    stitch drops/duplicates a row) fall back to volume=1 for that single day
    rather than dropping the row — matches the Phase-1 fallback so a handful
    of gaps don't shrink the sample."""
    idx = daily.copy()
    idx.columns = [c.lower() for c in idx.columns]
    if not isinstance(idx.index, pd.DatetimeIndex):
        idx.index = pd.to_datetime(idx.index)
    idx.index = idx.index.normalize()
    idx = idx[["open", "high", "low", "close"]].astype(float).sort_index()

    fut = fut_daily.copy()
    fut.columns = [c.lower() for c in fut.columns]
    if not isinstance(fut.index, pd.DatetimeIndex):
        fut.index = pd.to_datetime(fut.index)
    fut.index = fut.index.normalize()
    vol = pd.to_numeric(fut.get("volume"), errors="coerce") if "volume" in fut.columns else pd.Series(dtype=float)
    vol = vol[~vol.index.duplicated(keep="last")]

    idx["volume"] = vol.reindex(idx.index)
    idx["volume"] = idx["volume"].fillna(1.0)
    return idx


def build_conviction_history_real(daily: pd.DataFrame, fut_daily: pd.DataFrame,
                                  breadth: pd.Series = None, warmup: int = 40) -> pd.DataFrame:
    """Same cycle-by-cycle engine run as build_conviction_history(), but with
    REAL volume (from continuous futures, merged onto the gap-free INDEX price
    — see the roll-gap note above) so CVD/VWAP are genuine instead of the
    synthetic volume=1 Phase-1 used, and breadth (see daily_advance_breadth)
    wired through the engine's real breadth parameter instead of left as NaN."""
    d = _index_with_futures_volume(daily, fut_daily)
    ret = np.log(d["close"] / d["close"].shift(1))
    rv = ret.rolling(14).std()
    key = pd.Series([ic._expiry_cycle_key(ix) for ix in d.index], index=d.index)
    cycles = list(dict.fromkeys(key.tolist()))
    pos = {ts: i for i, ts in enumerate(d.index)}
    parts = []
    for ck in cycles:
        idxs = d.index[key == ck]
        if len(idxs) == 0:
            continue
        first, last = pos[idxs[0]], pos[idxs[-1]]
        window = d.iloc[max(0, first - warmup): last + 1]
        rv0 = rv.iloc[first]
        c0 = d["close"].iloc[first]
        em_week = (rv0 * c0 * (5 ** 0.5)) if np.isfinite(rv0) and rv0 > 0 else 0.02 * c0
        w = ic.enrich(window, expected_move_pts=float(em_week), breadth=breadth, anchored_vwap=True)
        ct = ic.candle_table(w, newest_first=False)
        ct = ct.loc[ct.index.isin(idxs)]
        parts.append(ct)
    if not parts:
        return pd.DataFrame()
    conv = pd.concat(parts).sort_index()
    conv["close"] = d["close"].reindex(conv.index)
    return conv


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4 — Roll-threshold optimizer (anchor management: WHEN to roll, not just
# how close to sell). Replays the same Tuesday-anchor / mid-week re-anchor
# logic as data/rolled_positions.py (check_roll_event + eod_update), but with
# configurable profit/loss triggers, over the full daily history. Answers:
# which trigger keeps a cycle one-sided (only the threatened leg gets re-sold)
# most often, vs. triggers that let both legs get touched in the same cycle
# (whipsaw) or that let a hard loss event through.
# ══════════════════════════════════════════════════════════════════════════════

def _simulate_roll_cycles(daily: pd.DataFrame, profit_thr: float, loss_thr: float) -> list:
    """Replay the anchor/roll logic (Tuesday hard reset + mid-week re-anchor on
    any event, exactly like data/rolled_positions.eod_update) over the full
    daily series. Returns one dict per completed Tue→Tue cycle:
      ce_touched / pe_touched — whether that leg was re-sold (loss OR profit
                                event) at any point in the cycle
      loss_event  — whether a hard *_LOSS event fired (adverse breach)
      n_events    — how many roll events fired in the cycle
    """
    d = _norm(daily)
    cycles = []
    anchor = None
    ce_touched = pe_touched = loss_event = False
    n_events = 0
    cycle_start = None
    for ts, row in d.iterrows():
        close = float(row["close"])
        if ts.weekday() == 1:                       # Tuesday — hard reset (set_expiry_anchor)
            if anchor is not None:
                cycles.append(dict(start=cycle_start, end=ts, ce_touched=ce_touched,
                                    pe_touched=pe_touched, loss_event=loss_event,
                                    n_events=n_events))
            anchor = close
            cycle_start = ts
            ce_touched = pe_touched = loss_event = False
            n_events = 0
            continue
        if anchor is None:
            continue
        event = _check_roll_event(close, anchor, loss_thr=loss_thr, profit_thr=profit_thr)
        if event is None:
            continue
        n_events += 1
        if event in ("CE_LOSS", "PE_LOSS"):
            loss_event = ce_touched = pe_touched = True
        elif event == "CE_PROFIT":
            ce_touched = True
        else:  # PE_PROFIT
            pe_touched = True
        anchor = close                               # mid-week re-anchor, same as eod_update
    return cycles


def roll_threshold_scan(daily: pd.DataFrame,
                        profit_thrs=tuple(round(x, 2) for x in np.arange(1.0, 3.01, 0.25)),
                        loss_thrs=tuple(round(x, 2) for x in np.arange(2.0, 4.01, 0.25))
                        ) -> pd.DataFrame:
    """Grid-scan candidate (profit_thr%, loss_thr%) roll triggers over every
    historical Tue→Tue cycle. loss_thr must sit outside profit_thr (skipped
    otherwise — the loss trigger has to be the wider, harder stop).
    clean_pct = % of cycles where only the threatened leg ever got re-sold
    (the opposite leg was left undisturbed) — the metric to maximise.
    loss_pct = % of cycles that saw a hard loss reset — the metric to avoid.
    score = clean_pct − 2×loss_pct (loss events weighted worse than whipsaw).
    Sorted best-score first."""
    rows = []
    for pt in profit_thrs:
        for lt in loss_thrs:
            if lt <= pt:
                continue
            cycles = _simulate_roll_cycles(daily, profit_thr=pt, loss_thr=lt)
            n = len(cycles)
            if n == 0:
                continue
            both = sum(1 for c in cycles if c["ce_touched"] and c["pe_touched"])
            loss = sum(1 for c in cycles if c["loss_event"])
            quiet = sum(1 for c in cycles if c["n_events"] == 0)
            avg_events = sum(c["n_events"] for c in cycles) / n
            clean_pct = round((n - both) / n * 100, 1)
            score = round(clean_pct - 2 * (loss / n * 100), 1)
            rows.append(dict(profit_thr=pt, loss_thr=lt, n_cycles=n,
                             clean_pct=clean_pct, both_touched_pct=round(both / n * 100, 1),
                             loss_pct=round(loss / n * 100, 1), quiet_pct=round(quiet / n * 100, 1),
                             avg_events_per_cycle=round(avg_events, 2), score=score))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("score", ascending=False).reset_index(drop=True)


def best_roll_threshold(scan: pd.DataFrame) -> dict:
    """Top-scoring row from roll_threshold_scan as a plain dict, or {} if empty."""
    if scan is None or scan.empty:
        return {}
    return scan.iloc[0].to_dict()


def run_backtest_real(daily: pd.DataFrame, fut_daily: pd.DataFrame, breadth: pd.Series = None,
                      horizons=(5, 10), call_pct: float = 3.5, put_pct: float = 4.0,
                      nbins: int = 5) -> dict:
    """Real-volume + breadth-on driver — mirrors run_backtest()'s return shape
    so pages can render either uniformly. Forward-outcome LABELS are computed
    on the INDEX (`daily`), same as run_backtest() — never on continuous
    futures directly, so a roll gap can't leak into the answer key."""
    conv = build_conviction_history_real(daily, fut_daily, breadth=breadth)
    outc = forward_outcomes(daily, horizons=horizons, call_pct=call_pct, put_pct=put_pct)
    dist = weekly_move_distribution(outc, horizons=horizons, call_pct=call_pct, put_pct=put_pct)
    cuts = column_cutoff_scan(conv, outc, horizons=horizons, nbins=nbins)
    span = (f"{conv.index.min():%d-%b-%Y} → {conv.index.max():%d-%b-%Y}"
            if not conv.empty else "—")
    return {"distribution": dist, "cutoffs": cuts, "n_rows": int(len(conv)),
            "span": span, "conv": conv, "outcomes": outc}
