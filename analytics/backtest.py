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

# Columns we scan for cutoffs (numeric ones get binned; State is handled categorically).
SCAN_NUMERIC = ["Final", "Bull−Bear", "Conf%", "RSI", "ΔVWAP", "Stretch",
                "Reversal", "Uptrend", "Downtr", "Topping"]


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
    return pd.DataFrame({
        "n": g.size(),
        f"avg_ret{h0}": g[f"ret{h0}"].mean().round(2),
        f"pct_up{h0}": g[f"ret{h0}"].apply(lambda x: round((x > 0).mean() * 100, 0)),
        "call_breach%": (g["breach_call"].mean() * 100).round(0),
        "put_breach%": (g["breach_put"].mean() * 100).round(0),
        f"avg_maxup{h0}": g[f"up{h0}"].mean().round(2),
        f"avg_maxdn{h0}": g[f"dn{h0}"].mean().round(2),
    })


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
