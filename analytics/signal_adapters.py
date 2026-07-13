# analytics/signal_adapters.py
# Signal adapters for analytics/signal_lab.py — one function per page, each
# turning that page's REAL engine logic into a single daily directional score
# (see signal_lab.py's SIGNAL CONTRACT docstring).
#
# Every adapter reuses the underlying engine's own pure functions rather than
# reimplementing the math. Two engines (DowTheoryEngine.signals(),
# MarketProfileEngine.signals()) have I/O or date.today() side effects in
# their top-level signals() method, so those two adapters call the engine's
# private pure helpers directly instead (documented per-adapter below) —
# same formulas, no file writes, no live-date dependence.
#
# All adapters return a pd.Series indexed by normalized trading DATE (no
# time-of-day), one value per day, so signal_lab.evaluate_signal() can join
# them straight against a DAILY forward_outcomes() table.

import numpy as np
import pandas as pd

from analytics import dow_theory as dt
from analytics.ema import (
    EMAEngine, MTF_EMA_PERIODS, MOAT_SET,
    MOM_STRONG_UP_THRESH, MOM_MODERATE_UP_THRESH,
    MOM_MODERATE_DN_THRESH, MOM_STRONG_DN_THRESH,
)
from analytics.supertrend import compute_supertrend
from analytics.market_profile import MarketProfileEngine
from analytics.bollinger import BollingerOptionsEngine, _classify_bw, _pct_b_zone, _BW_2H
from analytics.rsi_engine import RSIEngine
from analytics.ema_slope_phases import calculate_hourly_ema_slope_phases
from config import (
    DOW_N, DOW_PHASE_DAYS,
    W_RSI_EXHAUST, D_RSI_EXHAUST, W_RSI_CAPIT, D_RSI_CAPIT,
)


def _to_dt_index(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    return d.sort_index()


# ══════════════════════════════════════════════════════════════════════════════
# Dow Theory (page 00) — analytics/dow_theory.py
# ══════════════════════════════════════════════════════════════════════════════

def _dow_theory_frame(df_1h: pd.DataFrame, window_days: int = DOW_PHASE_DAYS) -> pd.DataFrame:
    """Shared rolling-window Dow Theory computation, one row per trading day —
    feeds adapt_dow_theory (structure sign), adapt_dow_leg_health (CE/PE
    health imbalance), and signal_lab.dow_retrace_bucket_scan (retrace-%
    entry-timing study) from a SINGLE pass over the 1H history rather than
    walking the window separately for each.

    Reuses the SAME pure pivot/structure/sequence/retrace/health functions as
    DowTheoryEngine.signals() (_atr14, _detect_pivots, _extract_reference_pivots,
    _classify_structure, _sequence_check, _retrace_depth, _compute_health) —
    but calls them directly instead of .signals(), because .signals() writes
    data/dow_score_history.json on every call and reads date.today() for a
    display label, neither of which belong in a backtest loop.

    Rolling window = the last `window_days` trading days of 1H data ending
    that day — the SAME fixed-size window the live engine uses (not an
    expanding one), so pivot confirmation lag matches production.

    Columns: structure, sequence (RISING/FALLING — see _sequence_check),
    retrace_pct, ce_health, pe_health."""
    d = _to_dt_index(df_1h)
    if d.empty:
        return pd.DataFrame(columns=["structure", "sequence", "retrace_pct", "ce_health", "pe_health"])
    days = sorted(set(d.index.normalize()))
    target = window_days * 6   # ≈6 1H candles/session
    rows = {}
    for day in days:
        window = d[d.index.normalize() <= day].tail(target)
        if len(window) < DOW_N * 4 + 5:
            continue
        atr14 = dt._atr14(window)
        df_piv = dt._detect_pivots(window, DOW_N)
        pivots = dt._extract_reference_pivots(df_piv)
        if pivots is None:
            rows[day] = {"structure": None, "sequence": None, "retrace_pct": None,
                        "ce_health": None, "pe_health": None}
            continue
        structure = dt._classify_structure(pivots, atr14)
        spot = float(window["close"].iloc[-1])
        last_high = float(window["high"].iloc[-1])
        last_low = float(window["low"].iloc[-1])
        sequence = dt._sequence_check(pivots)
        retrace_pct = dt._retrace_depth(spot, pivots, sequence)
        ce_health, _, pe_health, _ = dt._compute_health(structure, spot, last_high, last_low, pivots)
        rows[day] = {"structure": structure, "sequence": sequence, "retrace_pct": retrace_pct,
                    "ce_health": ce_health, "pe_health": pe_health}
    return pd.DataFrame.from_dict(rows, orient="index")


def adapt_dow_theory(df_1h: pd.DataFrame, window_days: int = DOW_PHASE_DAYS) -> pd.Series:
    """Dow Theory structure sign, one value per trading day: +1 UPTREND,
    -1 DOWNTREND, 0 MIXED/CONSOLIDATING/insufficient pivots. See
    _dow_theory_frame for the shared computation this reads from."""
    frame = _dow_theory_frame(df_1h, window_days)
    if frame.empty:
        return pd.Series(dtype=float, name="dow_theory")
    sig = frame["structure"].map({"UPTREND": 1.0, "DOWNTREND": -1.0}).fillna(0.0).astype(float)
    sig.name = "dow_theory"
    return sig.sort_index()


_LEG_THREAT = {"BREACH": 4, "ALERT": 3, "WATCH": 2, "MODERATE": 1, "STRONG": 0}


def adapt_dow_leg_health(df_1h: pd.DataFrame, window_days: int = DOW_PHASE_DAYS) -> pd.Series:
    """Dow Theory CE/PE leg-health imbalance sign, one value per trading day:
    signal = (ce_threat - pe_threat) / 4, where threat = BREACH(4) > ALERT(3)
    > WATCH(2) > MODERATE(1) > STRONG(0) (via DowTheoryEngine._leg_health,
    same severity ladder page 00 displays). A threatened CE leg means price
    is at/through the resistance pivot → bullish; a threatened PE leg means
    price is at/through the support pivot → bearish. Shares
    _dow_theory_frame's single pass over the 1H history with adapt_dow_theory
    rather than re-walking the window a second time."""
    frame = _dow_theory_frame(df_1h, window_days)
    if frame.empty:
        return pd.Series(dtype=float, name="dow_leg_health")
    ce_t = frame["ce_health"].map(_LEG_THREAT)
    pe_t = frame["pe_health"].map(_LEG_THREAT)
    sig = ((ce_t - pe_t) / 4.0).astype(float)
    sig.name = "dow_leg_health"
    return sig.sort_index()


# ══════════════════════════════════════════════════════════════════════════════
# EMA Ribbon (pages 01/02) — analytics/ema.py cluster regime
# ══════════════════════════════════════════════════════════════════════════════

_REGIME_SIGN = {
    "STRONG_BULL": 1.0, "BULL_COMPRESSED": 0.6, "INSIDE_BULL": 0.3, "RECOVERING": 0.2,
    "INSIDE_BEAR": -0.3, "BEAR_COMPRESSED": -0.6, "STRONG_BEAR": -1.0,
}


def adapt_ema_ribbon(daily: pd.DataFrame) -> pd.Series:
    """EMA cluster-regime sign (pages 01/02's IC-shape driver), one value per
    trading day. Reuses EMAEngine._cluster_regime — the SAME regime classifier
    the live pages call for IC shape guidance. EMA columns are built with
    .ewm() (causal, expanding — no look-ahead); the regime call for a given
    row only reads that row's already-computed EMA values, so a single pass
    over the whole history is equivalent to running it fresh every day."""
    eng = EMAEngine()
    d = _to_dt_index(daily)
    if d.empty:
        return pd.Series(dtype=float, name="ema_ribbon")
    d = eng.compute(d)
    out = {}
    warm_col = f"ema{MTF_EMA_PERIODS[-1]}"
    for ts, row in d.iterrows():
        if pd.isna(row.get("atr14")) or pd.isna(row.get(warm_col)):
            continue
        spot = float(row["close"])
        regime, _, _ = eng._cluster_regime(row, spot)
        out[ts.normalize()] = _REGIME_SIGN.get(regime, 0.0)
    return pd.Series(out, name="ema_ribbon").sort_index()


_MOM_SIGN = {"STRONG_UP": 1.0, "MODERATE_UP": 0.5, "FLAT": 0.0,
            "MODERATE_DOWN": -0.5, "STRONG_DOWN": -1.0, "TRANSITIONING": 0.0}


def adapt_ema_momentum(daily: pd.DataFrame) -> pd.Series:
    """EMA momentum-state sign (pages 01/02's Component-3 read) — the page's
    own trend-momentum classifier, distinct from the cluster regime tested in
    adapt_ema_ribbon. TRANSITIONING (EMA3/EMA8 slopes disagree) scores 0 —
    genuinely no directional lean, not a missing read.

    EMAEngine._momentum_score() takes a trailing 4-row slice per call, so
    calling it inside a per-day loop would be O(n²) over a 2y history;
    instead this vectorises the SAME formula — EMA3/EMA8 3-bar slope scaled
    by ATR14, weighted 0.6/0.4, against the SAME threshold constants imported
    from analytics.ema (MOM_STRONG_UP_THRESH etc., not re-declared) — computed
    once over the whole EMA/ATR series that adapt_ema_ribbon also builds."""
    eng = EMAEngine()
    d = _to_dt_index(daily)
    if d.empty:
        return pd.Series(dtype=float, name="ema_momentum")
    d = eng.compute(d)
    atr = d["atr14"].replace(0, np.nan)
    ema3_slope = d["ema3"].diff(3) / 3.0
    ema8_slope = d["ema8"].diff(3) / 3.0
    combined = (ema3_slope / atr * 100) * 0.6 + (ema8_slope / atr * 100) * 0.4
    state = pd.Series("FLAT", index=d.index)
    state[combined > MOM_STRONG_UP_THRESH] = "STRONG_UP"
    state[(combined > MOM_MODERATE_UP_THRESH) & (combined <= MOM_STRONG_UP_THRESH)] = "MODERATE_UP"
    state[combined < MOM_STRONG_DN_THRESH] = "STRONG_DOWN"
    state[(combined < MOM_MODERATE_DN_THRESH) & (combined >= MOM_STRONG_DN_THRESH)] = "MODERATE_DOWN"
    transitioning = (ema3_slope > 0) != (ema8_slope > 0)   # same test as _momentum_score
    state[transitioning] = "TRANSITIONING"
    sig = state.map(_MOM_SIGN).astype(float)
    sig.index = pd.to_datetime(sig.index).normalize()
    sig.name = "ema_momentum"
    return sig


def adapt_ema_moat_balance(daily: pd.DataFrame) -> pd.Series:
    """EMA moat-COUNT balance (pages 01/02): signal = (put_moats - call_moats)
    / 5 — more EMA support clustered below spot (PUT moats) than resistance
    above (CALL moats) → bullish structural lean, and vice versa (moat counts
    typically run 0-5, so /5 keeps this in a comparable range to the other
    adapters). Reuses EMAEngine._count_moats_put/_count_moats_call directly —
    the SAME formulas the live moat-count display uses — fed by the SAME
    ewm()-computed EMA/ATR columns adapt_ema_ribbon already builds (no
    separate recompute); ema3_slope (needed for the degraded-EMA8 check
    inside _count_moats_put) is the same 3-bar slope adapt_ema_momentum uses."""
    eng = EMAEngine()
    d = _to_dt_index(daily)
    if d.empty:
        return pd.Series(dtype=float, name="ema_moat_balance")
    d = eng.compute(d)
    ema3_slope = d["ema3"].diff(3) / 3.0
    out = {}
    warm_col = f"ema{MTF_EMA_PERIODS[-1]}"
    for i, (ts, row) in enumerate(d.iterrows()):
        if pd.isna(row.get("atr14")) or pd.isna(row.get(warm_col)):
            continue
        spot = float(row["close"])
        atr = float(row.get("atr14", 0)) or 1.0
        ema_vals = {p: float(row.get(f"ema{p}", spot)) for p in MOAT_SET}
        slope = ema3_slope.iloc[i]
        slope = float(slope) if pd.notna(slope) else 0.0
        put_moats, _ = eng._count_moats_put(spot, ema_vals, atr, slope)
        call_moats, _ = eng._count_moats_call(spot, ema_vals, atr)
        out[ts.normalize()] = (put_moats - call_moats) / 5.0
    return pd.Series(out, name="ema_moat_balance").sort_index()


# ══════════════════════════════════════════════════════════════════════════════
# SuperTrend MTF (page 15) — analytics/supertrend.py — daily core direction
# ══════════════════════════════════════════════════════════════════════════════

def adapt_supertrend(daily: pd.DataFrame, period: int = 21, multiplier: float = 2.0) -> pd.Series:
    """Daily SuperTrend(21,2) direction, one value per trading day: +1 BULL,
    -1 BEAR. Uses the SAME compute_supertrend() page 15 calls for its daily
    TF — the recursive final-band formula only ever looks at the PREVIOUS
    final band, so it is already causal; one vectorized pass over the whole
    history equals refitting it fresh every day.

    Fidelity note: page 15's live signal is a 6-TF (daily/4H/2H/1H/30m/15m)
    moat stack used for STRIKE PLACEMENT; that stacking is a position-sizing
    overlay on top of this same indicator and isn't re-tested here — this
    adapter tests the core daily directional call only."""
    st = compute_supertrend(daily, period=period, multiplier=multiplier)
    if st.empty:
        return pd.Series(dtype=float, name="supertrend")
    sig = st["st_direction"].astype(float).copy()
    sig.index = pd.to_datetime(sig.index).normalize()
    sig.name = "supertrend"
    return sig


# ══════════════════════════════════════════════════════════════════════════════
# Market Profile (page 12) — analytics/market_profile.py
# ══════════════════════════════════════════════════════════════════════════════

_MP_SIGN = {
    "INITIATIVE_UPPER": 1.0, "INITIATIVE_LOWER": -1.0,
    "TESTING_UPPER": -0.5, "TESTING_LOWER": 0.5, "BALANCED": 0.0,
}
_MP_SIGN_FADE = {
    "INITIATIVE_UPPER": -1.0, "INITIATIVE_LOWER": 1.0,
    "TESTING_UPPER": 0.5, "TESTING_LOWER": -0.5, "BALANCED": 0.0,
}


def _market_profile_nesting_frame(daily: pd.DataFrame) -> pd.DataFrame:
    """Shared per-day (nesting, behaviour) computation, one pass over the
    daily history, feeding both adapt_market_profile (continuation) and
    adapt_market_profile_fade (mean-reversion) — same nesting-state read,
    different sign convention.

    Reuses MarketProfileEngine._value_area / ._nesting_state / ._price_behaviour
    directly — pure functions, no I/O. The only date.today() use in the engine
    is inside its top-level .signals() (for the cycle_day/action display
    labels), which this never calls. The Wed→day weekly window is re-derived
    per historical day (mirroring _weekly_window's own Wed-anchor logic)
    instead of using date.today()."""
    eng = MarketProfileEngine()
    d = _to_dt_index(daily)
    if len(d) < 2:
        return pd.DataFrame(columns=["nesting", "behaviour"])
    rows = {}
    for i in range(1, len(d)):
        day = d.index[i]
        days_since_wed = (day.weekday() - 2) % 7   # Wed=2
        wed = day - pd.Timedelta(days=days_since_wed)
        weekly = d[(d.index >= wed) & (d.index <= day)]
        if weekly.empty:
            continue
        daily_row = d.iloc[[i]]
        weekly_va = eng._value_area(weekly)
        daily_va = eng._value_area(daily_row)
        spot = float(d["close"].iloc[i])
        nesting = eng._nesting_state(weekly_va, daily_va, spot)
        behaviour = eng._price_behaviour(d.iloc[i - 1:i + 1], weekly_va, spot)
        rows[day] = {"nesting": nesting, "behaviour": behaviour}
    return pd.DataFrame.from_dict(rows, orient="index")


def _market_profile_signal(daily: pd.DataFrame, sign_map: dict) -> pd.Series:
    frame = _market_profile_nesting_frame(daily)
    if frame.empty:
        return pd.Series(dtype=float)
    out = {}
    for day, row in frame.iterrows():
        sign = sign_map.get(row["nesting"], 0.0)
        if row["behaviour"] == "RESPONSIVE" and abs(sign) == 1.0:
            sign *= 0.5
        out[day] = sign
    return pd.Series(out).sort_index()


def adapt_market_profile(daily: pd.DataFrame) -> pd.Series:
    """Market Profile nesting-state sign (page 12), one value per trading day:
    +1 INITIATIVE_UPPER (breakout continuation up) / -1 INITIATIVE_LOWER,
    -0.5 TESTING_UPPER (fade at the value-area ceiling) / +0.5 TESTING_LOWER
    (fade at the floor), 0 BALANCED. A RESPONSIVE daily read (rejected the
    test and closed back inside value) halves the magnitude — the same
    directional lean the live page treats as a softer signal. See
    adapt_market_profile_fade for the mirrored (mean-reversion) reading."""
    sig = _market_profile_signal(daily, _MP_SIGN)
    sig.name = "market_profile"
    return sig


def adapt_market_profile_fade(daily: pd.DataFrame) -> pd.Series:
    """MEAN-REVERSION mirror of adapt_market_profile — same nesting-state
    read (shares _market_profile_nesting_frame, not recomputed), sign
    flipped: INITIATIVE_UPPER (read as bullish breakout continuation above)
    now scores bearish (fade the initiative move back into value), and
    TESTING_UPPER/LOWER flip too. Added because the continuation version
    backtested with a 43.7% hit rate on ~4y of Nifty (notably below 50%,
    i.e. below coin-flip) — this checks whether reading it as a fade is
    what the data actually wants, same pattern already found for %B/RSI."""
    sig = _market_profile_signal(daily, _MP_SIGN_FADE)
    sig.name = "market_profile_fade"
    return sig


# ══════════════════════════════════════════════════════════════════════════════
# Bollinger %B (page 09) — analytics/bollinger.py — mean-reversion framed
# ══════════════════════════════════════════════════════════════════════════════

def adapt_bollinger_pctb(daily: pd.DataFrame) -> pd.Series:
    """Daily Bollinger %B, MEAN-REVERSION framed: signal = -(%B - 0.5) * 2, so
    a reading pinned to/above the upper band (%B >= 1) scores negative (fade)
    and a reading at/below the lower band scores positive (fade the other
    way) — matching the OVERBOUGHT-FADE edge the Conviction-table backtest
    (page 22) already found for %B. Uses BollingerOptionsEngine.compute()
    (rolling window, causal) on DAILY closes; page 09's live TF is 2H/4H —
    this is a daily proxy so it lines up with the harness's daily cadence."""
    eng = BollingerOptionsEngine()
    d = _to_dt_index(daily)
    if d.empty:
        return pd.Series(dtype=float, name="bollinger_pctb")
    d = eng.compute(d)
    pb = pd.to_numeric(d.get("bb_pct_b"), errors="coerce")
    sig = -(pb - 0.5) * 2.0
    sig.index = pd.to_datetime(sig.index).normalize()
    sig.name = "bollinger_pctb"
    return sig


_ASYMMETRY_SIGN = {"1:2": 1.0, "2:1": -1.0, "1:1": 0.0}
_ASYMMETRY_SIGN_FADE = {"1:2": -1.0, "2:1": 1.0, "1:1": 0.0}


def _bollinger_ratio_series(daily: pd.DataFrame) -> pd.Series:
    """Shared per-row asymmetry-ratio computation (raw '1:2'/'2:1'/'1:1'
    label, not yet signed), one pass over the daily history, feeding both
    adapt_bollinger_asymmetry (continuation) and adapt_bollinger_asymmetry_fade
    (mean-reversion) — same ratio, different sign convention.

    Reuses BollingerOptionsEngine._squeeze_status/_base_ratio/_ma_pos/_apply_ma
    directly — pure, row-wise functions once bb_bw/bb_pct_b/bb_basis are
    computed (same eng.compute() call as adapt_bollinger_pctb). Daily proxy of
    the live 2H/4H engine (same caveat as adapt_bollinger_pctb): the daily
    reading stands in for BOTH the '2H' and '4H' inputs those functions
    expect, since page 09's live TF is intraday and this harness is daily."""
    eng = BollingerOptionsEngine()
    d = _to_dt_index(daily)
    if d.empty:
        return pd.Series(dtype=object)
    d = eng.compute(d)
    out = {}
    for ts, row in d.iterrows():
        bw, pb = row.get("bb_bw"), row.get("bb_pct_b")
        basis, close = row.get("bb_basis"), row.get("close")
        if pd.isna(bw) or pd.isna(pb) or pd.isna(basis):
            continue
        reg = _classify_bw(float(bw), _BW_2H)
        zone = _pct_b_zone(float(pb))
        sq = eng._squeeze_status(reg, reg)
        ratio, _, _ = eng._base_ratio(zone, sq, float(pb))
        ma = eng._ma_pos(float(close), float(basis))
        ratio = eng._apply_ma(ratio, ma, ma)
        out[ts.normalize()] = ratio
    return pd.Series(out).sort_index()


def adapt_bollinger_asymmetry(daily: pd.DataFrame) -> pd.Series:
    """Bollinger asymmetry-ratio sign (page 09's real headline output — which
    leg needs more room) — CONTINUATION framed, the opposite convention from
    adapt_bollinger_pctb's mean-reversion framing, worth testing both ways.
    Ratio "1:2" means CE needs more room (primary_risk_side="CE" in the live
    page — price pushing toward/through the upper band) → bullish (+1.0).
    "2:1" (PE at risk, price toward the lower band) → bearish (-1.0). See
    adapt_bollinger_asymmetry_fade for the mirrored (mean-reversion) reading."""
    sig = _bollinger_ratio_series(daily).map(_ASYMMETRY_SIGN).astype(float)
    sig.name = "bollinger_asymmetry"
    return sig


def adapt_bollinger_asymmetry_fade(daily: pd.DataFrame) -> pd.Series:
    """MEAN-REVERSION mirror of adapt_bollinger_asymmetry — same ratio
    (shares _bollinger_ratio_series, not recomputed), sign flipped: "1:2"
    (read as CE-at-risk/bullish under the continuation reading) now scores
    bearish (fade), "2:1" now scores bullish. Added because the continuation
    version backtested NEGATIVE (~-0.11% expectancy on ~4y of Nifty) — this
    checks whether the fade framing is what's actually real, matching the
    pattern already found for %B/RSI."""
    sig = _bollinger_ratio_series(daily).map(_ASYMMETRY_SIGN_FADE).astype(float)
    sig.name = "bollinger_asymmetry_fade"
    return sig


# ══════════════════════════════════════════════════════════════════════════════
# RSI Weekly (page 05) — analytics/rsi_engine.py — continuation framed
# ══════════════════════════════════════════════════════════════════════════════

def adapt_rsi_weekly(daily: pd.DataFrame) -> pd.Series:
    """Weekly RSI, CONTINUATION framed (matches page 05's designed use: a high
    weekly RSI = W_BULL regime = an ongoing bullish trend, which the live page
    reads as reason to sell PUTs closer): signal = (weekly RSI - 50) / 50.

    NOTE: the Conviction-table backtest found the OPPOSITE (overbought-fade)
    works for RSI at that timeframe/column. A negative Spearman correlation
    here would say the same fade pattern holds at the weekly cadence too —
    deliberately left for the bucket scan/Spearman sign to reveal rather than
    assumed, per the brief ('let the backtest decide their fate')."""
    eng = RSIEngine()
    d = _to_dt_index(daily)
    if d.empty:
        return pd.Series(dtype=float, name="rsi_weekly")
    d = eng.compute(d)
    sig = (pd.to_numeric(d["rsi_weekly"], errors="coerce") - 50.0) / 50.0
    sig.index = pd.to_datetime(sig.index).normalize()
    sig.name = "rsi_weekly"
    return sig


_ALIGN_SIGN = {
    "ALIGNED_BULL": 1.0, "ALIGNED_BULL_NEUTRAL": 0.3, "ALIGNED_BEAR": -1.0,
    "COUNTER_TRAP_BEAR": 0.5, "COUNTER_TRAP_BULL": -0.5, "MIXED": 0.0,
}


def adapt_rsi_alignment(daily: pd.DataFrame) -> pd.Series:
    """RSI weekly-vs-daily MTF alignment sign (page 05's own combined read).
    ALIGNED_BULL/_BEAR = both timeframes agree (+1.0/-1.0). COUNTER_TRAP_* is
    page 05's own built-in contrarian read: a same-day move AGAINST the
    WEEKLY regime is read as a trap that fails, so the signal leans back
    toward the weekly direction rather than the daily one — COUNTER_TRAP_BEAR
    (bearish daily dip inside a bullish weekly regime) → +0.5, COUNTER_TRAP_BULL
    → -0.5.

    Reuses RSIEngine._weekly_regime/_daily_zone/_alignment directly — pure,
    row-wise once rsi_daily/rsi_weekly are computed (same eng.compute() call
    as adapt_rsi_weekly)."""
    eng = RSIEngine()
    d = _to_dt_index(daily)
    if d.empty:
        return pd.Series(dtype=float, name="rsi_alignment")
    d = eng.compute(d)
    out = {}
    for ts, row in d.iterrows():
        w_rsi, d_rsi = row.get("rsi_weekly"), row.get("rsi_daily")
        if pd.isna(w_rsi) or pd.isna(d_rsi):
            continue
        w_regime = eng._weekly_regime(float(w_rsi))
        d_zone = eng._daily_zone(float(d_rsi))
        alignment = eng._alignment(w_regime, d_zone)
        out[ts.normalize()] = _ALIGN_SIGN.get(alignment, 0.0)
    return pd.Series(out, name="rsi_alignment").sort_index()


def adapt_rsi_exhaustion_fade(daily: pd.DataFrame) -> pd.Series:
    """RSI exhaustion-fade signal: page 05's own RSI_DUAL_EXHAUSTION /
    RSI_DAILY_EXHAUSTION_REVERSAL kill-switches, re-read as a MEAN-REVERSION
    (fade) call rather than a binary veto — the natural companion to the
    overbought-fade edge already confirmed on the Conviction table.
        both weekly+daily overbought, OR daily overbought + slope turning
        down → -1.0 (fade down)
        both weekly+daily oversold → +1.0 (fade up)
    The original engine has no daily-only bullish-reversal counterpart
    (asymmetric by design) — consistent with the overbought-fade-ONLY
    pattern already found; this harness run will show whether that asymmetry
    holds here too.

    Formulas and thresholds (W_RSI_EXHAUST/D_RSI_EXHAUST/W_RSI_CAPIT/
    D_RSI_CAPIT) copied 1:1 from RSIEngine._kill_switches; both conditions
    only need the current row (no trailing-window lookback), so computed
    vectorised rather than via a per-day loop."""
    eng = RSIEngine()
    d = _to_dt_index(daily)
    if d.empty:
        return pd.Series(dtype=float, name="rsi_exhaustion_fade")
    d = eng.compute(d)
    w, r_, s1 = d["rsi_weekly"], d["rsi_daily"], d["d_slope_1d"]
    dual_bear = (w > W_RSI_EXHAUST) & (r_ > D_RSI_EXHAUST)
    dual_bull = (w < W_RSI_CAPIT) & (r_ < D_RSI_CAPIT)
    daily_rev_bear = (r_ > D_RSI_EXHAUST) & (s1 < 0)
    sig = pd.Series(0.0, index=d.index)
    sig[dual_bull] = 1.0
    sig[dual_bear] = -1.0
    sig[daily_rev_bear] = -1.0
    sig.index = pd.to_datetime(sig.index).normalize()
    sig.name = "rsi_exhaustion_fade"
    return sig


# ══════════════════════════════════════════════════════════════════════════════
# EMA Slope Phases (page 17) — analytics/ema_slope_phases.py
# ══════════════════════════════════════════════════════════════════════════════

_PHASE_SIGN = {1: 1.0, 2: 0.5, 3: 0.0, 4: -0.5, 5: -1.0}


def adapt_ema_slope_phases(df_1h: pd.DataFrame) -> pd.Series:
    """5-phase EMA-20 slope classification (page 17), one value per trading
    day (last confirmed 1H bar of that day): Phase1(strong bull)=+1 ...
    Phase5(strong bear)=-1. Uses calculate_hourly_ema_slope_phases() directly
    — fully vectorised (.ewm() + np.select), already causal — so a single
    pass over the whole history is used rather than a per-day re-fit."""
    d = _to_dt_index(df_1h)
    if d.empty:
        return pd.Series(dtype=float, name="ema_slope_phases")
    d = calculate_hourly_ema_slope_phases(d)
    d = d.dropna(subset=["Slope_Phase"])
    if d.empty:
        return pd.Series(dtype=float, name="ema_slope_phases")
    last_per_day = d.groupby(d.index.normalize())["Slope_Phase"].last()
    sig = last_per_day.map(_PHASE_SIGN).astype(float)
    sig.name = "ema_slope_phases"
    return sig


# ══════════════════════════════════════════════════════════════════════════════
# Futures OI Buildup — price + open-interest change (NOT back-fillable from
# the index; needs data.live_fetcher.get_nifty_fut_continuous(oi=True))
# ══════════════════════════════════════════════════════════════════════════════

def _roll_jump_mask(close: pd.Series, z_thresh: float = 4.5, window: int = 21) -> pd.Series:
    """Flag days whose return is a robust statistical outlier vs its own
    trailing window — a proxy for a futures contract-ROLL GAP. Kite's
    historical_data(continuous=True) stitches contracts WITHOUT back-adjustment,
    so the front-month switch at each monthly expiry prints as a real price
    jump (cost-of-carry basis, not an actual market move) — left unguarded,
    that jump gets read as a directional long/short-buildup call it isn't.

    Uses a median/MAD (modified z-score) rather than mean/std: a plain rolling
    std is itself dragged up by the very jump it's supposed to catch (a single
    5% day inside a 21-day window inflates std enough to hide itself), whereas
    the median and median-absolute-deviation stay put with one outlier in the
    window. Not a perfect detector (Kite's continuous response carries no
    per-row contract/expiry tag to key off instead, and a genuinely large real
    move looks identical to a roll gap) — but it keeps the OI-buildup signal
    from firing on the ~12 rollovers/year it would otherwise misread."""
    ret = close.pct_change()
    med = ret.rolling(window, min_periods=5).median()
    dev = (ret - med).abs()
    mad = dev.rolling(window, min_periods=5).median()
    z = dev / (1.4826 * mad.replace(0, np.nan))
    return z.fillna(0) > z_thresh


def adapt_oi_buildup(fut_daily: pd.DataFrame) -> pd.Series:
    """Classic long/short OI-buildup read from continuous-futures price + OI
    change, one value per trading day:
        price up  & OI up   → Long Buildup    → +1.0
        price down& OI up   → Short Buildup   → -1.0
        price up  & OI down → Short Covering  → +0.5 (bullish, weaker — closing shorts)
        price down& OI down → Long Unwinding  → -0.5
    Requires an 'oi' column (data.live_fetcher.get_nifty_fut_continuous). This
    is the one adapter here that genuinely cannot be back-filled from the
    index — option-chain OI has no history at all, but FUTURES OI does.

    Roll-gap days (see _roll_jump_mask) are set to 0 (no opinion) — both the
    price diff and the OI diff span the old→new contract switch on those
    days, so neither side of the read is trustworthy."""
    d = _to_dt_index(fut_daily)
    if "oi" not in d.columns or d.empty:
        return pd.Series(dtype=float, name="oi_buildup")
    dprice = d["close"].diff()
    doi = d["oi"].diff()
    sign = pd.Series(0.0, index=d.index)
    sign[(dprice > 0) & (doi > 0)] = 1.0
    sign[(dprice < 0) & (doi > 0)] = -1.0
    sign[(dprice > 0) & (doi < 0)] = 0.5
    sign[(dprice < 0) & (doi < 0)] = -0.5
    sign[_roll_jump_mask(d["close"])] = 0.0
    sign.index = sign.index.normalize()
    sign.name = "oi_buildup"
    return sign


# ══════════════════════════════════════════════════════════════════════════════
# Page 24's fall/bounce + rise/pullback reversal — EOD-only, one signal per day
# ══════════════════════════════════════════════════════════════════════════════

# Same numbers as docs/PAGE_24_RULE_BOOK.md and the FALL_TRIGGER_PCT/etc.
# constants in analytics/position_sizing_backtest.py (kept duplicated here,
# not imported, to avoid a circular import — position_sizing_backtest.py
# already imports FROM this module). If page 24's rule book numbers ever
# change, update both places.
_P24_FALL_TRIGGER_PCT = 0.1
_P24_RISE_TRIGGER_PCT = 0.1
_P24_BOUNCE_CONFIRM_PCT = 0.25
_P24_PULLBACK_CONFIRM_PCT = 0.25


def adapt_page24_reversal(daily: pd.DataFrame) -> pd.Series:
    """EOD-only translation of page 24's validated fall/bounce (PUT side) and
    rise/pullback (CALL side) rule into ONE per-day directional score, using
    each day's OWN close as the confirmation point (the live intraday version
    in position_sizing_backtest.intraday_reversal_snapshot uses today's
    still-forming high/low instead — this is its once-per-day, backtestable
    twin).

    IMPORTANT — this is a DIFFERENT claim than page 24 validated, not a
    re-statement of it: page 24 checked "does this day's own low/high get
    RE-TOUCHED in 3-5 days" (strike-placement safety). This checks something
    new — "does a confirmed reversal day predict which side (CALL/PUT) gets
    tested MORE over the coming week," the composite's own question. That is
    UNVALIDATED until it clears Page 26's split_validation, same bar
    bollinger_fade cleared before promotion — see REFERENCE_ADAPTERS in
    analytics/position_sizing_backtest.py.

    Sign convention matches the composite: a confirmed FALL+BOUNCE (price
    already reversing UP off a low — the same "shakeout, then a bounce that
    tests the call side" shape as this composite's own validated DOWN
    reading) scores NEGATIVE. A confirmed RISE+PULLBACK (reversing DOWN off
    a high) scores POSITIVE, matching the composite's UP convention. Both
    firing the same day (rare — a same-day double reversal) or neither
    firing scores 0 (no opinion)."""
    d = _to_dt_index(daily)
    if d.empty:
        return pd.Series(dtype=float, name="page24_reversal")
    close, high, low = d["close"].to_numpy(), d["high"].to_numpy(), d["low"].to_numpy()
    n = len(d)

    fall_pct = np.full(n, np.nan)
    bounce_pct = np.full(n, np.nan)
    rise_pct = np.full(n, np.nan)
    pullback_pct = np.full(n, np.nan)
    fall_pct[1:] = (close[:-1] - low[1:]) / close[:-1] * 100
    bounce_pct[1:] = np.where(low[1:] > 0, (close[1:] - low[1:]) / low[1:] * 100, np.nan)
    rise_pct[1:] = (high[1:] - close[:-1]) / close[:-1] * 100
    pullback_pct[1:] = np.where(high[1:] > 0, (high[1:] - close[1:]) / high[1:] * 100, np.nan)

    fall_confirmed = (np.nan_to_num(fall_pct) >= _P24_FALL_TRIGGER_PCT) & \
                     (np.nan_to_num(bounce_pct) >= _P24_BOUNCE_CONFIRM_PCT)
    rise_confirmed = (np.nan_to_num(rise_pct) >= _P24_RISE_TRIGGER_PCT) & \
                     (np.nan_to_num(pullback_pct) >= _P24_PULLBACK_CONFIRM_PCT)
    both = fall_confirmed & rise_confirmed   # same-day double reversal — ambiguous, treat as no opinion

    sig = np.zeros(n)
    sig[fall_confirmed & ~both] = -1.0
    sig[rise_confirmed & ~both] = 1.0

    out = pd.Series(sig, index=d.index, name="page24_reversal")
    out.index = out.index.normalize()
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Registry — for pages/23_Signal_Library.py to iterate generically
# ══════════════════════════════════════════════════════════════════════════════

ADAPTERS = {
    "Dow Theory":            {"fn": adapt_dow_theory,        "needs": ("h1",),        "cadence": "1H window, daily read"},
    "Dow Leg Health":        {"fn": adapt_dow_leg_health,    "needs": ("h1",),        "cadence": "1H window, daily read"},
    "EMA Ribbon":            {"fn": adapt_ema_ribbon,        "needs": ("daily",),     "cadence": "daily"},
    "EMA Momentum":          {"fn": adapt_ema_momentum,      "needs": ("daily",),     "cadence": "daily"},
    "EMA Moat Balance":      {"fn": adapt_ema_moat_balance,  "needs": ("daily",),     "cadence": "daily"},
    "SuperTrend (daily)":    {"fn": adapt_supertrend,        "needs": ("daily",),     "cadence": "daily"},
    "Market Profile":        {"fn": adapt_market_profile,    "needs": ("daily",),     "cadence": "daily (Wed→day VA)"},
    "Market Profile Fade":   {"fn": adapt_market_profile_fade, "needs": ("daily",),   "cadence": "daily (Wed→day VA)"},
    "Bollinger %B":          {"fn": adapt_bollinger_pctb,    "needs": ("daily",),     "cadence": "daily proxy of 2H/4H"},
    "Bollinger Asymmetry":   {"fn": adapt_bollinger_asymmetry, "needs": ("daily",),   "cadence": "daily proxy of 2H/4H"},
    "Bollinger Asymmetry Fade": {"fn": adapt_bollinger_asymmetry_fade, "needs": ("daily",), "cadence": "daily proxy of 2H/4H"},
    "RSI Weekly":            {"fn": adapt_rsi_weekly,        "needs": ("daily",),     "cadence": "weekly, ffilled daily"},
    "RSI Alignment":         {"fn": adapt_rsi_alignment,     "needs": ("daily",),     "cadence": "daily+weekly combined"},
    "RSI Exhaustion Fade":   {"fn": adapt_rsi_exhaustion_fade, "needs": ("daily",),   "cadence": "daily+weekly combined"},
    "EMA Slope Phases":      {"fn": adapt_ema_slope_phases,  "needs": ("h1",),        "cadence": "1H, daily read"},
    "Futures OI Buildup":    {"fn": adapt_oi_buildup,        "needs": ("fut_daily",), "cadence": "daily (needs OI history)"},
    "Page 24 Reversal":      {"fn": adapt_page24_reversal,   "needs": ("daily",),     "cadence": "daily, EOD-only twin of the live intraday check"},
}
