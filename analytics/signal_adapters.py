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
from analytics.ema import EMAEngine, MTF_EMA_PERIODS
from analytics.supertrend import compute_supertrend
from analytics.market_profile import MarketProfileEngine
from analytics.bollinger import BollingerOptionsEngine
from analytics.rsi_engine import RSIEngine
from analytics.ema_slope_phases import calculate_hourly_ema_slope_phases
from config import DOW_N, DOW_PHASE_DAYS


def _to_dt_index(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    return d.sort_index()


# ══════════════════════════════════════════════════════════════════════════════
# Dow Theory (page 00) — analytics/dow_theory.py
# ══════════════════════════════════════════════════════════════════════════════

def adapt_dow_theory(df_1h: pd.DataFrame, window_days: int = DOW_PHASE_DAYS) -> pd.Series:
    """Dow Theory structure sign, one value per trading day: +1 UPTREND,
    -1 DOWNTREND, 0 MIXED/CONSOLIDATING/insufficient pivots.

    Reuses the SAME pure pivot/structure functions as DowTheoryEngine.signals()
    (_atr14, _detect_pivots, _extract_reference_pivots, _classify_structure) —
    but calls them directly instead of .signals(), because .signals() writes
    data/dow_score_history.json on every call and reads date.today() for a
    display label, neither of which belong in a backtest loop.

    Rolling window = the last `window_days` trading days of 1H data ending
    that day — the SAME fixed-size window the live engine uses (not an
    expanding one), so pivot confirmation lag matches production."""
    d = _to_dt_index(df_1h)
    if d.empty:
        return pd.Series(dtype=float, name="dow_theory")
    days = sorted(set(d.index.normalize()))
    target = window_days * 6   # ≈6 1H candles/session
    out = {}
    for day in days:
        window = d[d.index.normalize() <= day].tail(target)
        if len(window) < DOW_N * 4 + 5:
            continue
        atr14 = dt._atr14(window)
        df_piv = dt._detect_pivots(window, DOW_N)
        pivots = dt._extract_reference_pivots(df_piv)
        if pivots is None:
            out[day] = 0.0
            continue
        structure = dt._classify_structure(pivots, atr14)
        out[day] = {"UPTREND": 1.0, "DOWNTREND": -1.0}.get(structure, 0.0)
    return pd.Series(out, name="dow_theory").sort_index()


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


def adapt_market_profile(daily: pd.DataFrame) -> pd.Series:
    """Market Profile nesting-state sign (page 12), one value per trading day:
    +1 INITIATIVE_UPPER (breakout continuation up) / -1 INITIATIVE_LOWER,
    -0.5 TESTING_UPPER (fade at the value-area ceiling) / +0.5 TESTING_LOWER
    (fade at the floor), 0 BALANCED. A RESPONSIVE daily read (rejected the
    test and closed back inside value) halves the magnitude — the same
    directional lean the live page treats as a softer signal.

    Reuses MarketProfileEngine._value_area / ._nesting_state / ._price_behaviour
    directly — pure functions, no I/O. The only date.today() use in the engine
    is inside its top-level .signals() (for the cycle_day/action display
    labels), which this adapter never calls. The Wed→day weekly window is
    re-derived per historical day (mirroring _weekly_window's own Wed-anchor
    logic) instead of using date.today()."""
    eng = MarketProfileEngine()
    d = _to_dt_index(daily)
    if len(d) < 2:
        return pd.Series(dtype=float, name="market_profile")
    out = {}
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
        sign = _MP_SIGN.get(nesting, 0.0)
        if behaviour == "RESPONSIVE" and abs(sign) == 1.0:
            sign *= 0.5
        out[day] = sign
    return pd.Series(out, name="market_profile").sort_index()


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

def adapt_oi_buildup(fut_daily: pd.DataFrame) -> pd.Series:
    """Classic long/short OI-buildup read from continuous-futures price + OI
    change, one value per trading day:
        price up  & OI up   → Long Buildup    → +1.0
        price down& OI up   → Short Buildup   → -1.0
        price up  & OI down → Short Covering  → +0.5 (bullish, weaker — closing shorts)
        price down& OI down → Long Unwinding  → -0.5
    Requires an 'oi' column (data.live_fetcher.get_nifty_fut_continuous). This
    is the one adapter here that genuinely cannot be back-filled from the
    index — option-chain OI has no history at all, but FUTURES OI does."""
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
    sign.index = sign.index.normalize()
    sign.name = "oi_buildup"
    return sign


# ══════════════════════════════════════════════════════════════════════════════
# Registry — for pages/23_Signal_Library.py to iterate generically
# ══════════════════════════════════════════════════════════════════════════════

ADAPTERS = {
    "Dow Theory":         {"fn": adapt_dow_theory,       "needs": ("h1",),        "cadence": "1H window, daily read"},
    "EMA Ribbon":         {"fn": adapt_ema_ribbon,       "needs": ("daily",),     "cadence": "daily"},
    "SuperTrend (daily)": {"fn": adapt_supertrend,       "needs": ("daily",),     "cadence": "daily"},
    "Market Profile":     {"fn": adapt_market_profile,   "needs": ("daily",),     "cadence": "daily (Wed→day VA)"},
    "Bollinger %B":       {"fn": adapt_bollinger_pctb,   "needs": ("daily",),     "cadence": "daily proxy of 2H/4H"},
    "RSI Weekly":         {"fn": adapt_rsi_weekly,       "needs": ("daily",),     "cadence": "weekly, ffilled daily"},
    "EMA Slope Phases":   {"fn": adapt_ema_slope_phases, "needs": ("h1",),        "cadence": "1H, daily read"},
    "Futures OI Buildup": {"fn": adapt_oi_buildup,       "needs": ("fut_daily",), "cadence": "daily (needs OI history)"},
}
