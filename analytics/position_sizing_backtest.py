# analytics/position_sizing_backtest.py
# Backtests the LOT-SIZE decision, not the strike-distance or roll decision
# pages 24/25 already cover: given the reference position (2 lots CALL ~3%
# above Tuesday anchor, 1 lot PUT ~3.5% below, squared off within a week —
# see docs/PAGE_25_RULE_BOOK.md), does a trend-confirmation signal identify
# cycles where the CALL side is structurally more likely to breach than the
# PUT side (or vice versa) — a genuine reason to flip to 2 PUT : 1 CALL
# instead of the default?
#
# Survival-only, same convention as pages 24/25: no historical option
# premium/IV data exists anywhere in this app (Kite gives only a LIVE chain
# snapshot), so results are scored on strike-BREACH RATE, never realized P&L.
# "Expected breached lots per cycle" (lots_CE * call_breach_rate + lots_PE *
# put_breach_rate) is the proxy used to rank lot allocations — smaller is
# safer, not a currency figure.
#
# Every signal reuses the SAME adapters analytics/signal_lab.py already ranks
# individually (analytics/signal_adapters.py) — this module only adds the
# combine-into-a-composite step and the bucket -> breach-rate -> lot-scorecard
# pipeline on top.

import numpy as np
import pandas as pd

from analytics import backtest as bt
from analytics import signal_adapters as sa

# Adapters used to build the composite trend-confirmation signal. All are
# DAILY-cadence directional reads except dow_theory, which needs the 1H
# window (see signal_adapters._dow_theory_frame). Dow Theory is the one
# adapter that was already purpose-built for skewed-IC lot/strike guidance
# (DowTheoryEngine.ic_shape emits "1:2 — CE further" on UPTREND today) —
# kept first in the dict for that reason, not because it's weighted higher.
DEFAULT_ADAPTERS = {
    "dow_theory":       sa.adapt_dow_theory,
    "ema_ribbon":       sa.adapt_ema_ribbon,
    "ema_moat_balance": sa.adapt_ema_moat_balance,
    "rsi_alignment":    sa.adapt_rsi_alignment,
    "supertrend":       sa.adapt_supertrend,
}
_NEEDS_1H = {"dow_theory"}


def _norm_idx(idx) -> pd.DatetimeIndex:
    idx = pd.to_datetime(idx)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


# ══════════════════════════════════════════════════════════════════════════════
# Composite signal
# ══════════════════════════════════════════════════════════════════════════════

def build_composite_signal(daily: pd.DataFrame, df_1h: pd.DataFrame,
                            adapters: dict = None) -> pd.DataFrame:
    """One row per trading day: every adapter's raw reading, a composite
    (mean of the readings available that day) and an agreement count
    (adapters reading >=0.3 in magnitude AND the same sign as the
    composite). Missing adapters (e.g. no 1H data) just shrink n_signals —
    they never force a NEUTRAL read on their own."""
    adapters = adapters or DEFAULT_ADAPTERS
    cols = {}
    for name, fn in adapters.items():
        try:
            raw = fn(df_1h) if name in _NEEDS_1H else fn(daily)
        except Exception:
            raw = pd.Series(dtype=float)
        if raw is not None and len(raw):
            raw = raw.copy()
            raw.index = _norm_idx(raw.index)
            raw = raw[~raw.index.duplicated(keep="last")]
        cols[name] = raw

    frame = pd.DataFrame(cols)
    if frame.empty:
        frame = pd.DataFrame(columns=list(adapters.keys()))
    frame = frame.sort_index()

    names = list(adapters.keys())
    composite = frame[names].mean(axis=1, skipna=True)
    comp_sign = np.sign(composite)

    agree = pd.Series(0, index=frame.index, dtype=int)
    for name in names:
        same_dir = np.sign(frame[name]) == comp_sign
        strong = frame[name].abs() >= 0.3
        agree = agree + (same_dir & strong).fillna(False).astype(int)

    frame["composite"] = composite
    frame["agree_count"] = agree
    frame["n_signals"] = frame[names].notna().sum(axis=1)
    return frame


def classify_composite(frame: pd.DataFrame, up_thresh: float = 0.4,
                        min_agree: int = 3) -> pd.Series:
    """UP / DOWN / NEUTRAL from the composite — UP/DOWN require BOTH a strong
    composite reading AND enough independent adapters agreeing, mirroring the
    app's own gating pattern (DowTheoryEngine.phase_score only fires PRIME on
    structure+phase+retrace agreement together, never on one lens alone)."""
    bucket = pd.Series("NEUTRAL", index=frame.index)
    up = (frame["composite"] >= up_thresh) & (frame["agree_count"] >= min_agree)
    dn = (frame["composite"] <= -up_thresh) & (frame["agree_count"] >= min_agree)
    bucket[up] = "UP"
    bucket[dn] = "DOWN"
    return bucket


def classify_single(signal: pd.Series, thresh: float = 0.3) -> pd.Series:
    """UP / DOWN / NEUTRAL from ONE adapter's raw reading — the single-
    indicator counterpart to classify_composite, so each lens can be scored
    on its own before deciding whether combining lenses actually helps."""
    s = signal.copy()
    s.index = _norm_idx(s.index)
    bucket = pd.Series("NEUTRAL", index=s.index)
    bucket[s >= thresh] = "UP"
    bucket[s <= -thresh] = "DOWN"
    return bucket


# ══════════════════════════════════════════════════════════════════════════════
# Breach rate by bucket
# ══════════════════════════════════════════════════════════════════════════════

def breach_by_bucket(daily: pd.DataFrame, bucket: pd.Series, horizon: int = 5,
                      call_pct: float = 3.0, put_pct: float = 3.5,
                      tuesdays_only: bool = True) -> pd.DataFrame:
    """Forward CE/PE breach rate at `horizon` trading days, grouped by
    bucket. Reuses bt.forward_outcomes — the SAME breach-rate machinery
    pages 24/25 already use — this only adds the group-by.

    tuesdays_only=True restricts to actual anchor days (the reference
    position is set once per cycle, at Tuesday EOD — data/rolled_positions.py
    set_expiry_anchor()), matching how the sizing decision is really made:
    call_pct/put_pct are measured from that day's close, which on a Tuesday
    IS the anchor. Set False only for a larger-sample sanity check that is
    no longer cadence-realistic (every day gets scored as if it were an
    anchor, which it isn't)."""
    outc = bt.forward_outcomes(daily, horizons=(horizon,), call_pct=call_pct, put_pct=put_pct)
    outc.index = _norm_idx(outc.index)
    b = bucket.reindex(outc.index)

    if tuesdays_only:
        is_tue = outc.index.weekday == 1
        outc = outc[is_tue]
        b = b[is_tue]

    df = outc.copy()
    df["bucket"] = b
    df = df[df[f"ret{horizon}"].notna() & df["bucket"].notna()]

    rows = []
    for name, g in df.groupby("bucket"):
        rows.append({
            "bucket": name,
            "n": int(len(g)),
            "call_breach%": round(float(g["breach_call"].mean() * 100), 1),
            "put_breach%":  round(float(g["breach_put"].mean() * 100), 1),
            f"avg_ret{horizon}": round(float(g[f"ret{horizon}"].mean()), 2),
        })
    out = pd.DataFrame(rows).set_index("bucket") if rows else pd.DataFrame(
        columns=["n", "call_breach%", "put_breach%", f"avg_ret{horizon}"])
    order = [x for x in ("UP", "NEUTRAL", "DOWN") if x in out.index]
    return out.reindex(order)


# ══════════════════════════════════════════════════════════════════════════════
# Lot-scheme scorecard
# ══════════════════════════════════════════════════════════════════════════════

# (lots_CE, lots_PE) per bucket. "dynamic_flip" is the rule as ORIGINALLY
# hypothesized: flip to PE-heavy on a confirmed uptrend, CE-heavy on a
# confirmed downtrend (the naive "downtrend threatens the put" assumption),
# falling back to today's live default (2 CE : 1 PE) whenever the signal
# doesn't clear the bar. Kept in the registry even after it back-tested
# WORSE than the static default (first real run, n=194: 0.201 expected
# breached lots vs 0.186 static, see docs/PAGE_26_RULE_BOOK.md) — it's the
# reference point "flip_calibrated" is measured against, not a live
# recommendation.
#
# "flip_calibrated" is the DATA-DRIVEN correction: same first run showed the
# DOWN bucket's call-breach% running 3x its put-breach% (18.8% vs 6.2%) with
# a strongly POSITIVE average forward return — i.e. the composite's DOWN
# reading precedes a bounce that tests the CALL side, not a continuation
# that tests the put. So DOWN flips to PE-heavy here too, instead of CE-heavy.
# UP stays at the static default (2:1) because the same run showed literally
# zero separation there (5.7% call breach == 5.7% put breach) — no evidence
# to flip anything on a confirmed uptrend read. Both DOWN's n=16 and UP's
# lack-of-signal are single-run results and need a second, longer-lookback
# confirmation before this is anything more than a hypothesis to re-test.
LOT_SCHEMES = {
    "static_2CE_1PE":  {"UP": (2, 1), "NEUTRAL": (2, 1), "DOWN": (2, 1)},
    "static_1_1":      {"UP": (1, 1), "NEUTRAL": (1, 1), "DOWN": (1, 1)},
    "dynamic_flip":    {"UP": (1, 2), "NEUTRAL": (2, 1), "DOWN": (3, 1)},
    "flip_calibrated": {"UP": (2, 1), "NEUTRAL": (2, 1), "DOWN": (1, 2)},
}


def lot_scheme_scorecard(bucket_table: pd.DataFrame,
                          schemes: dict = None,
                          horizon_col: str = None) -> pd.DataFrame:
    """Expected-breached-lots per cycle, per scheme:
        sum over buckets of n_bucket * (lots_CE * call_breach_rate
                                         + lots_PE * put_breach_rate)
    normalised by total cycles and by total lots sold — the survival-space
    proxy for 'better' allocation, since no premium data exists to price
    this in currency (same limitation pages 24/25 already documented).
    A lower breach_rate_per_lot% means fewer expected leg-breaches for the
    same premium-collecting effort, not a P&L number."""
    schemes = schemes or LOT_SCHEMES
    total_n = int(bucket_table["n"].sum()) if not bucket_table.empty else 0
    rows = []
    for scheme_name, alloc in schemes.items():
        breached_lots = 0.0
        total_lots = 0.0
        for bucket, row in bucket_table.iterrows():
            lots_ce, lots_pe = alloc.get(bucket, (2, 1))
            n = row["n"]
            breached_lots += n * (lots_ce * row["call_breach%"] / 100.0
                                   + lots_pe * row["put_breach%"] / 100.0)
            total_lots += n * (lots_ce + lots_pe)
        rows.append({
            "scheme": scheme_name,
            "n_cycles": total_n,
            "expected_breached_lots_per_cycle": round(breached_lots / total_n, 3) if total_n else np.nan,
            "avg_lots_sold_per_cycle": round(total_lots / total_n, 2) if total_n else np.nan,
            "breach_rate_per_lot%": round(breached_lots / total_lots * 100, 2) if total_lots else np.nan,
        })
    return pd.DataFrame(rows).set_index("scheme")


# ══════════════════════════════════════════════════════════════════════════════
# One-call driver
# ══════════════════════════════════════════════════════════════════════════════

def run_position_sizing_backtest(daily: pd.DataFrame, df_1h: pd.DataFrame,
                                  horizon: int = 5, call_pct: float = 3.0,
                                  put_pct: float = 3.5, up_thresh: float = 0.4,
                                  min_agree: int = 3, tuesdays_only: bool = True,
                                  adapters: dict = None) -> dict:
    """Single entry point a page (or a standalone script) can call: builds
    the composite, scores every individual adapter AND the composite through
    breach_by_bucket, and scores the lot schemes off the composite bucket
    table. Returns everything a rule-book writeup needs in one dict."""
    adapters = adapters or DEFAULT_ADAPTERS
    frame = build_composite_signal(daily, df_1h, adapters)

    per_signal = {}
    per_signal_scorecard = {}
    for name in adapters:
        if name not in frame.columns or frame[name].dropna().empty:
            continue
        b = classify_single(frame[name])
        table = breach_by_bucket(daily, b, horizon=horizon,
                                 call_pct=call_pct, put_pct=put_pct,
                                 tuesdays_only=tuesdays_only)
        per_signal[name] = table
        # Same 3-scheme scorecard, scored off THIS indicator's own buckets
        # alone — lets each lens be judged on whether ITS OWN UP/DOWN read
        # is worth sizing off, before deciding the composite is needed.
        per_signal_scorecard[name] = lot_scheme_scorecard(table)

    composite_bucket = classify_composite(frame, up_thresh=up_thresh, min_agree=min_agree)
    composite_table = breach_by_bucket(daily, composite_bucket, horizon=horizon,
                                        call_pct=call_pct, put_pct=put_pct,
                                        tuesdays_only=tuesdays_only)
    scorecard = lot_scheme_scorecard(composite_table)

    return {
        "frame": frame,
        "per_signal_breach": per_signal,
        "per_signal_scorecard": per_signal_scorecard,
        "composite_bucket": composite_bucket,
        "composite_breach": composite_table,
        "lot_scorecard": scorecard,
        "params": {
            "horizon": horizon, "call_pct": call_pct, "put_pct": put_pct,
            "up_thresh": up_thresh, "min_agree": min_agree,
            "tuesdays_only": tuesdays_only,
        },
    }
