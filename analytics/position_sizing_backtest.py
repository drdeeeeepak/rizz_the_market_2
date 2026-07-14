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
from analytics import reversal_backtest as rb

# Adapters used to build the composite trend-confirmation signal. All are
# DAILY-cadence directional reads except dow_theory, which needs the 1H
# window (see signal_adapters._dow_theory_frame). Dow Theory is the one
# adapter that was already purpose-built for skewed-IC lot/strike guidance
# (DowTheoryEngine.ic_shape emits "1:2 — CE further" on UPTREND today) —
# kept first in the dict for that reason, not because it's weighted higher.
#
# bollinger_fade was promoted here from REFERENCE_ADAPTERS after Page 26's
# split_validation confirmed it: adapt_bollinger_pctb reads POSITIVE on
# oversold (%B low) and this direction showed the SAME "call side tested
# more" asymmetry as this composite's own DOWN rule, in BOTH history halves
# (Page 26 per-indicator split run). Its OTHER (overbought/negative) reading
# stayed noise-level in the first half and was never confirmed.
#
# _bollinger_fade_composite_adapter flips that sign before it joins the mean/
# agreement math below: this composite's OWN convention is negative=bearish/
# DOWN=the validated "sell more puts" side, the OPPOSITE of adapt_bollinger_
# pctb's own mean-reversion convention (positive=oversold=confirmed). Without
# the flip, the CONFIRMED oversold reading would incorrectly count toward
# UP agreement (never acted on) and the UNCONFIRMED overbought reading would
# incorrectly count toward DOWN (the one rule this app actually trusts). With
# the flip: confirmed-oversold -> negative -> can only ever help DOWN agree,
# unconfirmed-overbought -> positive -> can only ever help UP agree (already
# informational-only) — so the unvalidated half can never influence the
# sell-2-puts call, structurally, not just by convention.
def _bollinger_fade_composite_adapter(daily: pd.DataFrame) -> pd.Series:
    sig = sa.adapt_bollinger_pctb(daily)
    return -sig if sig is not None else sig


DEFAULT_ADAPTERS = {
    "dow_theory":       sa.adapt_dow_theory,
    "ema_ribbon":       sa.adapt_ema_ribbon,
    "ema_moat_balance": sa.adapt_ema_moat_balance,
    "rsi_alignment":    sa.adapt_rsi_alignment,
    "supertrend":       sa.adapt_supertrend,
    "bollinger_fade":   _bollinger_fade_composite_adapter,
}
_NEEDS_1H = {"dow_theory"}

# page24_reversal / page24_reversal_tight are candidates, not yet validated
# for THIS composite's question. Page 24 validated a DIFFERENT claim (does
# this day's own low/high get re-touched in 3-5 days — strike-placement
# safety); this composite asks whether a confirmed reversal day predicts
# which side (CALL/PUT) gets tested MORE over the coming week. Both
# adapters' sign convention already matches this composite's (no flip
# needed, unlike bollinger_fade) — see their docstrings in
# analytics/signal_adapters.py.
#
# page24_reversal (0.1%/0.25%, page 24's own numbers) tested WEAK on Page 26:
# DOWN side barely separated (1.4pp/2.8pp gap across the two halves), UP
# side showed ZERO separation in the first half — not promoted.
# page24_reversal_tight (0.3%/0.4%) is the tightened re-test, kept here
# reference-only until ITS split_validation is checked the same way.
REFERENCE_ADAPTERS = {
    "page24_reversal": sa.adapt_page24_reversal,
    "page24_reversal_tight": sa.adapt_page24_reversal_tight,
}


def _norm_idx(idx) -> pd.DatetimeIndex:
    idx = pd.to_datetime(idx)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


# ══════════════════════════════════════════════════════════════════════════════
# Composite signal
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_adapter_series(name: str, fn, daily: pd.DataFrame, df_1h: pd.DataFrame) -> pd.Series:
    """Shared per-adapter fetch+normalize step — used by build_composite_signal
    for its composite-forming adapters, and separately by
    run_position_sizing_backtest for REFERENCE_ADAPTERS (which must be scored
    individually WITHOUT ever touching the composite mean/agreement)."""
    try:
        raw = fn(df_1h) if name in _NEEDS_1H else fn(daily)
    except Exception:
        raw = pd.Series(dtype=float)
    if raw is not None and len(raw):
        raw = raw.copy()
        raw.index = _norm_idx(raw.index)
        raw = raw[~raw.index.duplicated(keep="last")]
    return raw


def build_composite_signal(daily: pd.DataFrame, df_1h: pd.DataFrame,
                            adapters: dict = None) -> pd.DataFrame:
    """One row per trading day: every adapter's raw reading, a composite
    (mean of the readings available that day) and an agreement count
    (adapters reading >=0.3 in magnitude AND the same sign as the
    composite). Missing adapters (e.g. no 1H data) just shrink n_signals —
    they never force a NEUTRAL read on their own."""
    adapters = adapters or DEFAULT_ADAPTERS
    cols = {name: _fetch_adapter_series(name, fn, daily, df_1h) for name, fn in adapters.items()}

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
    df = _joined_bucket_outcomes(daily, bucket, horizon, call_pct, put_pct, tuesdays_only)
    return _table_from_joined(df, horizon)


def _joined_bucket_outcomes(daily: pd.DataFrame, bucket: pd.Series, horizon: int,
                             call_pct: float, put_pct: float,
                             tuesdays_only: bool) -> pd.DataFrame:
    """Shared prep step for breach_by_bucket and split_validation: forward
    outcomes joined to the bucket label, filtered to valid rows (and to
    Tuesdays if requested), sorted chronologically. Kept separate so a
    chronological SPLIT can be taken after this step without re-deriving it."""
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
    return df.sort_index()


def _table_from_joined(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Group a _joined_bucket_outcomes() frame into the UP/NEUTRAL/DOWN
    breach-rate table breach_by_bucket returns."""
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


def split_validation(daily: pd.DataFrame, bucket: pd.Series, horizon: int = 5,
                     call_pct: float = 3.0, put_pct: float = 3.5,
                     tuesdays_only: bool = True, n_splits: int = 2) -> dict:
    """Chronological out-of-sample check: split the SAME cycles
    breach_by_bucket would score into n_splits equal-count, TIME-ORDERED
    segments (default: first half / second half) and score each
    independently. Answers the question a single full-history run can't:
    does an asymmetry found over the whole window hold up in BOTH an early
    and a late slice, or does it only exist because one stretch (e.g. one
    sharp correction-and-bounce) dominates the average?

    The full daily/1H history still goes into BUILDING the signal (adapter
    warmup — EMA/RSI/ATR — is unaffected); only the evaluation rows get
    split, so this is not the same as re-running with a shorter lookback.

    Returns {segment_label: {"table": breach_df, "scorecard": lot_scheme_df,
    "span": "dd-Mon-YYYY -> dd-Mon-YYYY", "n": int}}."""
    df = _joined_bucket_outcomes(daily, bucket, horizon, call_pct, put_pct, tuesdays_only)
    if df.empty:
        return {}

    seg_size = len(df) // n_splits
    labels = ["first_half", "second_half"] if n_splits == 2 else [f"segment_{i+1}" for i in range(n_splits)]
    out = {}
    for i, label in enumerate(labels):
        start = i * seg_size
        end = (i + 1) * seg_size if i < n_splits - 1 else len(df)
        seg = df.iloc[start:end]
        table = _table_from_joined(seg, horizon)
        out[label] = {
            "table": table,
            "scorecard": lot_scheme_scorecard(table),
            "span": (f"{seg.index.min():%d-%b-%Y} -> {seg.index.max():%d-%b-%Y}"
                     if not seg.empty else "-"),
            "n": int(len(seg)),
        }
    return out


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
                                  adapters: dict = None, reference_adapters: dict = None) -> dict:
    """Single entry point a page (or a standalone script) can call: builds
    the composite, scores every individual adapter AND the composite through
    breach_by_bucket, and scores the lot schemes off the composite bucket
    table. Returns everything a rule-book writeup needs in one dict.

    Every individual adapter also gets its OWN split_validation (not just the
    composite) — this is the exact bar REFERENCE_ADAPTERS entries (e.g.
    bollinger_fade) need to clear before being promoted into DEFAULT_ADAPTERS:
    same UP/DOWN breach-rate asymmetry direction in both the early and late
    half, not just a whole-window average.

    `reference_adapters` (e.g. pass REFERENCE_ADAPTERS) are scored per-signal
    the SAME way — breach table, lot scorecard, split_validation — but are
    NEVER passed into build_composite_signal, so they cannot influence the
    composite mean/agreement or the "sell 2 puts" call. This is what lets you
    test a candidate signal here without silently changing what page 27 shows
    live."""
    adapters = adapters or DEFAULT_ADAPTERS
    reference_adapters = reference_adapters or {}
    frame = build_composite_signal(daily, df_1h, adapters)
    for name, fn in reference_adapters.items():
        if name not in frame.columns:
            frame[name] = _fetch_adapter_series(name, fn, daily, df_1h)

    per_signal = {}
    per_signal_scorecard = {}
    per_signal_split = {}
    for name in list(adapters.keys()) + [n for n in reference_adapters if n not in adapters]:
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
        # Same early/late chronological check the composite gets below,
        # scored off THIS indicator alone — the missing piece for any
        # REFERENCE_ADAPTERS entry to graduate to DEFAULT_ADAPTERS.
        per_signal_split[name] = split_validation(daily, b, horizon=horizon,
                                                  call_pct=call_pct, put_pct=put_pct,
                                                  tuesdays_only=tuesdays_only)

    composite_bucket = classify_composite(frame, up_thresh=up_thresh, min_agree=min_agree)
    composite_table = breach_by_bucket(daily, composite_bucket, horizon=horizon,
                                        call_pct=call_pct, put_pct=put_pct,
                                        tuesdays_only=tuesdays_only)
    scorecard = lot_scheme_scorecard(composite_table)
    # Out-of-sample check: does the composite's UP/DOWN breach-rate asymmetry
    # hold up in BOTH an early and a late slice of the same history, or only
    # in the full-window average? See split_validation's docstring.
    composite_split = split_validation(daily, composite_bucket, horizon=horizon,
                                        call_pct=call_pct, put_pct=put_pct,
                                        tuesdays_only=tuesdays_only)

    return {
        "frame": frame,
        "per_signal_breach": per_signal,
        "per_signal_scorecard": per_signal_scorecard,
        "per_signal_split": per_signal_split,
        "composite_bucket": composite_bucket,
        "composite_breach": composite_table,
        "lot_scorecard": scorecard,
        "composite_split": composite_split,
        "params": {
            "horizon": horizon, "call_pct": call_pct, "put_pct": put_pct,
            "up_thresh": up_thresh, "min_agree": min_agree,
            "tuesdays_only": tuesdays_only,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# Live snapshot — TODAY's reading, not a backtest
# ══════════════════════════════════════════════════════════════════════════════

# Only the DOWN read has cleared BOTH validation bars this app has actually
# run: the full ~4-year window (docs/PAGE_26_WORKFLOW.md) AND an early/late
# chronological split (split_validation) confirming the SAME direction in
# two independent halves — call breaches more than put when the composite
# reads DOWN. The UP read showed the mirror pattern in the early half but
# was inconclusive (zero breaches either side) in the late half — shown for
# completeness, never labeled as a confirmed edge.
_GRADE_NOTE = {
    "DOWN": "fade setup — historically the CALL side gets tested more this week (confirmed in both an early and a late independent half of the backtest)",
    "UP":   "read only — NOT validated as a sizing edge (confirmed in one half of the backtest, inconclusive in the other). Keep default sizing.",
    "NEUTRAL": "no confirmed trend read today — keep default sizing.",
}


def grade_ripeness(bucket: str, agree_count: int) -> str:
    """Human label for how STRONGLY today's composite reading is confirmed
    (agreement count, not a claim of profitability by itself) plus the
    validation status note for that bucket. STRONG/MODERATE/WEAK reflects
    only how many of the 5 adapters agree — see _GRADE_NOTE for whether
    that bucket has actually earned a sizing change in this app's own
    backtest."""
    if bucket == "NEUTRAL":
        return f"NOT RIPE — {_GRADE_NOTE['NEUTRAL']}"
    strength = "STRONG" if agree_count >= 4 else "MODERATE" if agree_count >= 3 else "WEAK"
    return f"{strength} {bucket} — {_GRADE_NOTE.get(bucket, 'unrecognized bucket')}"


def live_snapshot(daily: pd.DataFrame, df_1h: pd.DataFrame, up_thresh: float = 0.4,
                   min_agree: int = 3, adapters: dict = None,
                   reference_adapters: dict = None) -> dict:
    """TODAY's reading only — the live counterpart to run_position_sizing_backtest's
    historical scoring. Same build_composite_signal() used everywhere else in
    this module, just reading the LAST row instead of scoring history. Returns
    {} if there's no usable data (e.g. daily/1H both empty).

    reference_adapters (default REFERENCE_ADAPTERS) are computed and returned
    under "reference" for display only — they never touch composite/
    agree_count/bucket, so an unvalidated addition can't quietly change what
    the "sell 2 puts" call means."""
    adapters = adapters or DEFAULT_ADAPTERS
    frame = build_composite_signal(daily, df_1h, adapters)
    if frame.empty:
        return {}

    reference_adapters = REFERENCE_ADAPTERS if reference_adapters is None else reference_adapters
    reference = {}
    for name, fn in reference_adapters.items():
        try:
            ref_series = fn(daily)
        except Exception:
            ref_series = pd.Series(dtype=float)
        if ref_series is None or ref_series.empty:
            reference[name] = {"value": None, "bucket": "NO DATA"}
            continue
        ref_series = ref_series.copy()
        ref_series.index = _norm_idx(ref_series.index)
        val = ref_series.iloc[-1] if len(ref_series) else None
        if val is None or pd.isna(val):
            reference[name] = {"value": None, "bucket": "NO DATA"}
        else:
            val = float(val)
            b = "UP" if val >= 0.3 else "DOWN" if val <= -0.3 else "NEUTRAL"
            reference[name] = {"value": round(val, 1), "bucket": b}

    last = frame.iloc[-1]
    as_of = frame.index[-1]

    per_indicator = {}
    for name in adapters:
        val = last.get(name)
        if pd.isna(val):
            per_indicator[name] = {"value": None, "bucket": "NO DATA"}
            continue
        val = float(val)
        b = "UP" if val >= 0.3 else "DOWN" if val <= -0.3 else "NEUTRAL"
        per_indicator[name] = {"value": round(val, 1), "bucket": b}

    composite_val = float(last["composite"]) if pd.notna(last["composite"]) else 0.0
    agree = int(last["agree_count"]) if pd.notna(last["agree_count"]) else 0
    n_sig = int(last["n_signals"]) if pd.notna(last["n_signals"]) else 0

    if n_sig == 0:
        bucket = "NEUTRAL"
    elif composite_val >= up_thresh and agree >= min_agree:
        bucket = "UP"
    elif composite_val <= -up_thresh and agree >= min_agree:
        bucket = "DOWN"
    else:
        bucket = "NEUTRAL"

    lots_ce, lots_pe = LOT_SCHEMES["flip_calibrated"].get(bucket, (2, 1))

    return {
        "as_of": str(as_of.date()) if hasattr(as_of, "date") else str(as_of),
        "per_indicator": per_indicator,
        "composite": round(composite_val, 3),
        "agree_count": agree,
        "n_signals": n_sig,
        "bucket": bucket,
        "grade": grade_ripeness(bucket, agree),
        "suggested_lots_ce": lots_ce,
        "suggested_lots_pe": lots_pe,
        "frame": frame,
        "reference": reference,
    }


def hourly_history_table(h1: pd.DataFrame, frame: pd.DataFrame, up_thresh: float = 0.4,
                          min_agree: int = 3, days: int = 3,
                          adapters: dict = None) -> pd.DataFrame:
    """Last `days` TRADING days of hourly candles, newest first, each hour
    tagged with that CALENDAR day's reading — both the individual indicator
    VALUES (now 6, including bollinger_fade) and the combined day's reading /
    agreement count. The signals are a once-per-day (EOD) read, not an
    intraday one, so every hour inside the same trading day carries the SAME
    values — this table exists to show recent price action next to what
    each signal said on that day, not to imply any of them update hourly.
    Uses classify_composite (the SAME function live_snapshot's bucket and
    every backtest bucket table already use) so the reading column always
    matches the rest of the app."""
    if h1 is None or h1.empty or frame.empty:
        return pd.DataFrame()

    d = h1.copy()
    d.index = pd.to_datetime(d.index)
    if getattr(d.index, "tz", None) is not None:
        d.index = d.index.tz_localize(None)   # match frame's tz-naive index (_norm_idx) — Kite
                                                # returns tz-aware timestamps, frame does not, so
                                                # every `day in frame.index` lookup below silently
                                                # failed and every signal column came back None.
    d = d.sort_index()
    all_days = sorted(set(d.index.normalize()))
    if not all_days:
        return pd.DataFrame()
    keep = set(all_days[-days:])
    d = d[d.index.normalize().isin(keep)]
    if d.empty:
        return pd.DataFrame()

    adapters = adapters or DEFAULT_ADAPTERS
    indicator_names = [n for n in adapters if n in frame.columns]
    bucket_series = classify_composite(frame, up_thresh=up_thresh, min_agree=min_agree)

    rows = []
    prev_close = None
    for ts, row in d.iterrows():
        close = float(row["close"])
        chg = round(close - prev_close, 1) if prev_close is not None else 0.0
        prev_close = close
        day = ts.normalize()

        row_dict = {"time": ts.strftime("%d-%b %H:%M"), "close": round(close, 1), "chg pts": chg}
        for name in indicator_names:
            v = frame.loc[day, name] if day in frame.index else None
            row_dict[name.replace("_", " ")] = round(float(v), 1) if pd.notna(v) else None

        reading = bucket_series.get(day, "—")
        ac = frame.loc[day, "agree_count"] if day in frame.index else None
        ns = frame.loc[day, "n_signals"] if day in frame.index else None
        row_dict["day's reading"] = reading
        row_dict["agreement"] = f"{int(ac)}/{int(ns)}" if pd.notna(ac) and pd.notna(ns) else "—"
        rows.append(row_dict)

    out = pd.DataFrame(rows)
    return out.iloc[::-1].reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# Swing-signal backtest — Pinpoint (page 24's episode-anchored turning-point
# trigger) crossed with the x/6 composite's OWN direction that same day,
# scored as an options-sell ENTRY ON THE TRIGGER DAY ITSELF — not the weekly
# Tuesday anchor breach_by_bucket/split_validation use above. That's the
# actual swing question: does composite agreement on a Pinpoint trigger day
# improve the entry (fewer breaches) over Pinpoint alone, and does chasing
# MORE Pinpoint triggers (a looser preset) still hold up once crossed with
# the composite, or does it just add noise (as the preset comparison CSV
# already suggested — tighter_formation_0.5 roughly 4x'd the trigger count
# by segmenting episodes differently, not by loosening a % threshold, and
# tripled+ the touch-again rate in the process).
# ══════════════════════════════════════════════════════════════════════════════

def swing_signal_backtest(daily: pd.DataFrame, df_1h: pd.DataFrame,
                           horizons: tuple = (3, 5, 10),
                           call_pct: float = 3.0, put_pct: float = 3.5,
                           pinpoint_preset: str = "current_live",
                           up_thresh: float = 0.4, min_agree: int = 3,
                           adapters: dict = None, n_splits: int = 2) -> dict:
    """Backtests selling an OTM strike on the day Pinpoint fires (PUT_ONLY /
    CALL_ONLY / BOTH — NEITHER is ~94% of days and isn't a trigger, excluded
    here), tagged by what the x/6 composite ALSO said that same day
    (UP/DOWN/NEUTRAL, or NO_1H_DATA if the composite couldn't be computed).
    Joint buckets like "PUT_ONLY | composite=UP" (both lenses agree bullish)
    are what a real swing filter would require; "PUT_ONLY | composite=DOWN"
    (Pinpoint says bounce, composite says the down-leg isn't done) is the
    disagreement case worth seeing scored separately rather than averaged
    away.

    Returns {"full": df, "first_half": df, "second_half": df} (chronological
    out-of-sample split on TRIGGER days, same convention as split_validation
    above). Each df is indexed by joint bucket, columns
    n / call_breach{h}% / put_breach{h}% / avg_ret{h}% per horizon, sorted by
    n descending so the buckets with enough sample to trust sit on top."""
    adapters = adapters or DEFAULT_ADAPTERS
    frame = build_composite_signal(daily, df_1h, adapters)
    composite_bucket = classify_composite(frame, up_thresh=up_thresh, min_agree=min_agree) \
        if not frame.empty else pd.Series(dtype=object)

    preset = rb.PINPOINT_PRESETS.get(pinpoint_preset, rb.PINPOINT_PRESETS["current_live"])
    pin = rb.dual_confirmation_daily_labels(daily, **preset)
    if pin.empty:
        return {}
    pin_label = pin["label"].copy()
    pin_label.index = _norm_idx(pin_label.index)
    pin_label = pin_label[pin_label != "NEITHER"]   # only actual trigger days = the swing entries
    if pin_label.empty:
        return {}

    per_horizon = {}
    for h in horizons:
        outc = bt.forward_outcomes(daily, horizons=(h,), call_pct=call_pct, put_pct=put_pct)
        outc.index = _norm_idx(outc.index)
        df = outc.copy()
        df["pinpoint"] = pin_label.reindex(df.index)
        df = df[df[f"ret{h}"].notna() & df["pinpoint"].notna()]
        df["composite"] = composite_bucket.reindex(df.index).fillna("NO_1H_DATA")
        df["joint"] = df["pinpoint"].astype(str) + " | composite=" + df["composite"].astype(str)
        per_horizon[h] = df.sort_index()

    def _score(seg_frames: dict) -> pd.DataFrame:
        rows = {}
        for h, seg in seg_frames.items():
            for name, g in seg.groupby("joint"):
                r = rows.setdefault(name, {"joint": name, "n": int(len(g))})
                r[f"call_breach{h}%"] = round(float(g["breach_call"].mean() * 100), 1)
                r[f"put_breach{h}%"] = round(float(g["breach_put"].mean() * 100), 1)
                r[f"avg_ret{h}%"] = round(float(g[f"ret{h}"].mean()), 2)
        out = pd.DataFrame(list(rows.values()))
        return out.set_index("joint").sort_values("n", ascending=False) if not out.empty else out

    result = {"full": _score(per_horizon)}

    all_trigger_days = sorted(pin_label.index)
    seg_size = len(all_trigger_days) // n_splits
    labels = ["first_half", "second_half"] if n_splits == 2 else [f"segment_{i+1}" for i in range(n_splits)]
    for i, label in enumerate(labels):
        start = i * seg_size
        end = (i + 1) * seg_size if i < n_splits - 1 else len(all_trigger_days)
        seg_days = set(all_trigger_days[start:end])
        seg_frames = {h: df[df.index.isin(seg_days)] for h, df in per_horizon.items()}
        result[label] = _score(seg_frames)

    return result


def swing_signal_scan_to_frame(result: dict) -> pd.DataFrame:
    """Flattens swing_signal_backtest's {segment: df} dict into ONE frame
    tagged by a 'segment' column — same stacking convention
    reversal_backtest.compare_pinpoint_presets uses for its 'preset' column,
    so this exports in a shape directly comparable to
    pinpoint_preset_comparison.csv."""
    parts = []
    for label, table in result.items():
        if table is None or table.empty:
            continue
        t = table.reset_index()
        t.insert(0, "segment", label)
        parts.append(t)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
