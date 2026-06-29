# analytics/intraday_conviction.py
# Intraday Conviction Engine — Page 18 (Conviction Radar)
#
# PURPOSE (plain words):
#   Two everyday trading questions, answered candle-by-candle so they can be
#   drawn straight onto a price chart:
#
#   1. "The market is falling and I'm under water — do I book the loss now, or
#       wait?"  → the PATIENCE / REVERSAL read.
#   2. "Yesterday closed with a late bounce — can I trust it, or is it a trap?"
#       → the CLOSE CONVICTION grade.
#
#   The engine looks at the same things a seasoned trader watches:
#     • VWAP  — the day's "fair price". Buyers in control above it, sellers below.
#     • Stretch — how far price has run vs the move the market expected today
#                 (from VIX). A very stretched move is more likely to snap back.
#     • Momentum divergence — price makes a new low but momentum doesn't =
#                 selling is tiring (a bounce is brewing).
#     • Volume delta (proxy) — are sellers still hitting it, or drying up?
#     • Breadth — are most Nifty-50 stocks falling too (real), or is it narrow?
#
#   All of the maths is here. The page shows only plain-English labels + markers.
#
# IMPORTANT HONESTY NOTE:
#   The per-candle marks (▲ patience / ▼ trend) are built from PRICE / VOLUME /
#   BREADTH, which we *can* compute for every past candle — so you can see how
#   they would have behaved over the last 7 days. The dealer-GAMMA regime is a
#   *today-only* snapshot (option open-interest isn't available historically),
#   so it is shown as today's context, not back-painted onto old candles.

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

RSI_PERIOD = 14
BB_PERIOD = 20
DIV_LOOKBACK = 6        # candles back to compare for divergence / swing structure
PERSIST = 3             # consecutive candles needed to call a move "persistent"
# Stretch denominator as a fraction of the full-day expected move. The EM is a *full-day*
# 1-sigma move, but intraday deviation from VWAP is a fraction of that, so we measure
# stretch against EM × this factor (0.3 ⇒ stretch hits its cap at ~0.6 of a daily EM,
# which matches realistic intraday extension). Lower = stretch fires more readily.
STRETCH_EM_FRAC = 0.3
REVERSAL_THRESH = 60    # below VWAP + tired → bounce brewing (be patient)
DOWNTREND_THRESH = 58   # below VWAP + persistent → defend PUT
UPTREND_THRESH = 55     # above VWAP + continuation confirmed → ride it
TOPPING_THRESH = 55     # above VWAP + tired → defend CALL
# Legacy alias (kept so any old import doesn't break)
TREND_THRESH = DOWNTREND_THRESH


# ══════════════════════════════════════════════════════════════════════════════
# Per-candle indicators
# ══════════════════════════════════════════════════════════════════════════════

def _session_vwap(df: pd.DataFrame) -> pd.Series:
    """
    VWAP that resets every trading day (true intraday VWAP).
    If the instrument carries no volume (e.g. the Nifty index reports volume=0),
    fall back to a running average of the typical price — still a usable
    "fair price" line, just without volume weighting.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    day = df.index.normalize() if hasattr(df.index, "normalize") else pd.to_datetime(df.index).normalize()
    if float(pd.to_numeric(df["volume"], errors="coerce").fillna(0).sum()) <= 0:
        return tp.groupby(day).transform(lambda s: s.expanding().mean())
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vv = df["volume"].groupby(day).cumsum().replace(0, np.nan)
    return (pv / vv).ffill()


def _expiry_cycle_key(ts) -> "pd.Timestamp":
    """
    Identify which weekly options cycle a timestamp belongs to, keyed by the cycle's
    *expiry Tuesday*. The cycle runs from the first trading day AFTER expiry (Wednesday,
    or Thursday if Wed is a holiday) through the next expiry Tuesday. Tue/Mon belong to
    the cycle that is still running (the prior Tuesday's), Wed–Sun to the cycle that
    started this week.
    """
    import datetime as _dt
    d = ts.date() if hasattr(ts, "date") else pd.Timestamp(ts).date()
    wd = d.weekday()                                   # Mon=0 … Sun=6 (Tue=1)
    this_tue = d + _dt.timedelta(days=(1 - wd))        # the Tuesday of this Mon–Sun week
    return pd.Timestamp(this_tue if wd >= 2 else this_tue - _dt.timedelta(days=7))


def _anchored_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Anchored VWAP for positional tracking — resets each WEEKLY cycle at the first
    trading candle after expiry (post-Tuesday Wednesday, or Thursday on a holiday),
    instead of every day. Same volume-weighting (or price-only fallback) as the
    session VWAP, just grouped by expiry cycle rather than by calendar day.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    key = pd.Series([_expiry_cycle_key(ix) for ix in df.index], index=df.index)
    vol = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    if float(vol.sum()) <= 0:
        return tp.groupby(key).transform(lambda s: s.expanding().mean())
    pv = (tp * vol).groupby(key).cumsum()
    vv = vol.groupby(key).cumsum().replace(0, np.nan)
    return (pv / vv).ffill()


def _rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _cvd_proxy(df: pd.DataFrame) -> pd.Series:
    """
    Cumulative Volume Delta proxy (resets daily). True buy/sell aggressor data
    isn't on Kite, so we infer it from WHERE each candle closes in its range:
    close near the high → buyers won; near the low → sellers won.
    """
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    clv = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng   # -1..+1
    clv = clv.fillna(0)
    signed = clv * df["volume"]
    day = df.index.normalize() if hasattr(df.index, "normalize") else pd.to_datetime(df.index).normalize()
    return signed.groupby(day).cumsum()


def enrich(df: pd.DataFrame, expected_move_pts: float = 0.0,
           breadth: pd.Series = None, anchored_vwap: bool = False) -> pd.DataFrame:
    """
    Add every per-candle column used by the chart and the verdict.
    df must be intraday OHLCV with a DatetimeIndex.
    expected_move_pts : today's VIX-implied one-day move (points). Used for stretch.
    breadth           : optional Series (% of Nifty-50 above their VWAP), aligned later.
    anchored_vwap     : if True, VWAP anchors to the weekly expiry cycle (post-Tuesday
                        Wednesday) instead of resetting daily — for positional 2H tracking.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    df["vwap"] = _anchored_vwap(df) if anchored_vwap else _session_vwap(df)
    df["rsi"] = _rsi(df["close"])
    df["cvd"] = _cvd_proxy(df)

    # Bollinger %B on the chosen interval (band-stab + snap = reversion).
    basis = df["close"].rolling(BB_PERIOD).mean()
    sd = df["close"].rolling(BB_PERIOD).std()
    upper, lower = basis + 2 * sd, basis - 2 * sd
    width = (upper - lower).replace(0, np.nan)
    df["pct_b"] = ((df["close"] - lower) / width).clip(-0.5, 1.5)
    df["bb_lower"] = lower
    df["bb_upper"] = upper

    df["below_vwap"] = df["close"] < df["vwap"]
    df["above_vwap"] = df["close"] > df["vwap"]

    # Stretch above/below VWAP, measured in "expected daily moves".
    em_unit = max(expected_move_pts * STRETCH_EM_FRAC, 1.0)
    df["stretch_down"] = ((df["vwap"] - df["close"]) / em_unit).clip(lower=0)
    df["stretch_up"] = ((df["close"] - df["vwap"]) / em_unit).clip(lower=0)

    # Rejection wicks: long lower wick = buyers stepping in; long upper wick = sellers.
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    df["lower_wick_frac"] = ((df[["open", "close"]].min(axis=1) - df["low"]) / rng).fillna(0)
    df["upper_wick_frac"] = ((df["high"] - df[["open", "close"]].max(axis=1)) / rng).fillna(0)

    # Divergences over the last DIV_LOOKBACK candles.
    px_ll = df["low"] < df["low"].shift(DIV_LOOKBACK)            # price lower low
    px_hh = df["high"] > df["high"].shift(DIV_LOOKBACK)          # price higher high
    df["rsi_bull_div"] = px_ll & (df["rsi"] > df["rsi"].shift(DIV_LOOKBACK))
    df["cvd_bull_div"] = px_ll & (df["cvd"] > df["cvd"].shift(DIV_LOOKBACK))
    df["rsi_bear_div"] = px_hh & (df["rsi"] < df["rsi"].shift(DIV_LOOKBACK))
    df["cvd_bear_div"] = px_hh & (df["cvd"] < df["cvd"].shift(DIV_LOOKBACK))   # buying drying up at the high
    df["lower_low"] = px_ll
    df["higher_high"] = px_hh
    df["lower_high"] = df["high"] < df["high"].shift(DIV_LOOKBACK)   # mirror of lower_low (downtrend skeleton)

    # Swing structure: higher-lows = uptrend skeleton.
    rl = df["low"].rolling(DIV_LOOKBACK).min()
    df["higher_low"] = rl > rl.shift(DIV_LOOKBACK)

    # Buyers regaining control. `cvd_up` (vs 6 candles ago) is the smoother version used
    # in the scores; `cvd_rising` (vs the PREVIOUS candle) is the instant tick shown in
    # the table's CVD↑ arrow.
    df["cvd_up"] = df["cvd"] > df["cvd"].shift(DIV_LOOKBACK)
    df["cvd_rising"] = df.groupby(df.index.normalize())["cvd"].diff() > 0

    # Persistence filters — kill single-candle noise.
    df["persist_below"] = df["below_vwap"].rolling(PERSIST).sum() >= PERSIST
    df["persist_above"] = df["above_vwap"].rolling(PERSIST).sum() >= PERSIST

    # Breadth alignment (optional).
    if breadth is not None and not breadth.empty:
        df["breadth"] = breadth.reindex(df.index, method="nearest", tolerance=pd.Timedelta("20min"))
        df["breadth"] = df["breadth"].astype(float)
    else:
        df["breadth"] = np.nan
    br = df["breadth"]
    # Breadth diverging down while price makes a higher high = hidden weakness at the top.
    df["breadth_div_down"] = df["higher_high"] & br.notna() & (br < br.shift(DIV_LOOKBACK))

    # ── Four scores (symmetric: downside AND upside) ───────────────────────────
    df["reversal_score"] = _reversal_score(df)     # below VWAP, tired → bounce brewing
    df["downtrend_score"] = _downtrend_score(df)   # below VWAP, persistent → defend PUT
    df["uptrend_score"] = _uptrend_score(df)       # above VWAP, confirmed → ride it
    df["topping_score"] = _topping_score(df)       # above VWAP, tired → defend CALL
    # Legacy alias used by older callers / tests.
    df["trend_score"] = df["downtrend_score"]

    # Two-line dashboard read that works in BOTH regimes:
    #   bull_read = the case for staying / patience    bear_read = the case for defending
    df["bull_read"] = np.where(df["above_vwap"], df["uptrend_score"], df["reversal_score"])
    df["bear_read"] = np.where(df["above_vwap"], df["topping_score"], df["downtrend_score"])

    # Conflict-weighting: do the independent signals AGREE with the price direction?
    df = _confluence(df)

    df["state"] = _state(df)
    return df


# ──────────────────────────────────────────────────────────────────────────────
# Conflict weighting — the "don't enter a move that won't materialise" layer
# ──────────────────────────────────────────────────────────────────────────────
# Five independent pillars each vote bull (+1) / bear (−1) / neutral (0).
# We measure how many AGREE with the current price direction (above/below VWAP).
# When 2+ pillars FIGHT the direction, the tape is conflicted → low confidence →
# we refuse to flag a continuation trade (it tends to chop and fail).

PILLARS = ["Price vs VWAP", "Momentum (RSI)", "Volume (CVD)", "Breadth", "Structure"]


def _confluence(df: pd.DataFrame) -> pd.DataFrame:
    above, below = df["above_vwap"].to_numpy(), df["below_vwap"].to_numpy()
    bias = np.where(above, 1, np.where(below, -1, 0))

    rsi = df["rsi"].to_numpy()
    vote_mom = np.where(rsi >= 55, 1, np.where(rsi <= 45, -1, 0))
    vote_vol = np.where(df["cvd_up"].to_numpy(), 1, -1)
    br = df["breadth"].to_numpy()
    has_br = ~np.isnan(br)
    vote_brd = np.where(has_br & (br > 55), 1, np.where(has_br & (br < 45), -1, 0))
    vote_str = np.where(df["higher_low"].to_numpy(), 1,
                        np.where(df["lower_low"].to_numpy(), -1, 0))

    votes = np.vstack([vote_mom, vote_vol, vote_brd, vote_str])      # (4, N)
    agree = ((votes == bias) & (bias != 0)).sum(axis=0)
    oppose = ((votes == -bias) & (bias != 0)).sum(axis=0)
    # Net agreement out of ALL 4 voting pillars (Momentum, Volume, Breadth, Structure).
    # Counting neutrals against the score means 3-agree/1-neutral (75%) ranks below
    # 4-agree (100%) — the old agree/(agree+oppose) scored both 100%. An opposing pillar
    # also costs more than a neutral one ((agree−oppose) vs just agree).
    conf = np.clip((agree - oppose) / 4.0 * 100.0, 0.0, 100.0)

    df["bias"] = bias
    df["vote_mom"] = vote_mom
    df["vote_vol"] = vote_vol
    df["vote_brd"] = vote_brd
    df["vote_str"] = vote_str
    df["agree_count"] = agree
    df["oppose_count"] = oppose
    df["confidence"] = np.round(conf)
    df["conflict"] = oppose >= 2
    df["signal_quality"] = np.where(df["conflict"], "MIXED",
                            np.where(df["confidence"] >= 67, "HIGH", "FAIR"))
    return df


def pillar_scorecard(row: pd.Series, gamma_regime: str = "UNKNOWN",
                     spot_vs_flip=None) -> list:
    """Plain-English ✅/❌ per pillar for the latest candle (for the page)."""
    bias = int(row.get("bias", 0))
    dir_word = "up" if bias > 0 else ("down" if bias < 0 else "flat")
    cards = []

    def add(name, vote, read_up, read_dn, read_flat):
        if vote > 0:
            read, lean = read_up, 1
        elif vote < 0:
            read, lean = read_dn, -1
        else:
            read, lean = read_flat, 0
        # A neutral pillar neither agrees nor fights — show it as flat, not a conflict.
        agrees = None if (lean == 0 or bias == 0) else (lean == bias)
        cards.append({"pillar": name, "read": read, "lean": lean, "agrees": agrees})

    cards.append({"pillar": "Price vs VWAP",
                  "read": f"{'above' if bias>0 else 'below' if bias<0 else 'at'} fair value (move is {dir_word})",
                  "lean": bias, "agrees": True if bias != 0 else None})
    add("Momentum (RSI)", int(row.get("vote_mom", 0)), "strong (>55)", "weak (<45)", "middling")
    add("Volume (CVD)", int(row.get("vote_vol", 0)), "buyers winning", "sellers winning", "balanced")
    add("Breadth", int(row.get("vote_brd", 0)), "broad (>55%)", "narrow (<45%)", "mixed / n/a")
    add("Structure", int(row.get("vote_str", 0)), "higher lows", "lower lows", "no clear swing")

    # Gamma is a today-only extra pillar (not in the per-candle history).
    if gamma_regime in ("POSITIVE", "NEGATIVE"):
        g_lean = 1 if (gamma_regime == "POSITIVE" or (spot_vs_flip or 0) >= 0) else -1
        cards.append({"pillar": "Dealer gamma",
                      "read": "cushioning (mean-revert)" if g_lean > 0 else "amplifying (trend)",
                      "lean": g_lean, "agrees": (g_lean == bias) if bias != 0 else None})
    return cards


def _reversal_score(df: pd.DataFrame) -> pd.Series:
    """0-100: a downside move looks ready to BOUNCE (be patient). Only below VWAP."""
    s = pd.Series(0.0, index=df.index)
    s += np.where(df["below_vwap"], df["stretch_down"].clip(0, 2) * 18, 0)   # extended below fair value
    s += np.where(df["rsi"] < 35, (35 - df["rsi"]).clip(0, 20) * 1.2, 0)     # oversold
    s += np.where(df["rsi_bull_div"], 22, 0)                                  # momentum diverging up
    s += np.where(df["cvd_bull_div"], 18, 0)                                  # selling drying up
    s += np.where(df["lower_wick_frac"] > 0.4, 12, 0)                         # rejection wick
    s += np.where(df["pct_b"] < 0.05, 10, 0)                                  # stabbed below lower band
    br = df["breadth"]
    s += np.where(br.notna() & (br > br.shift(DIV_LOOKBACK)) & df["below_vwap"], 10, 0)
    return s.clip(0, 100).round()


def _downtrend_score(df: pd.DataFrame) -> pd.Series:
    """0-100: a real DOWNTREND (defend PUT). Persistence-gated to cut pullback noise."""
    s = pd.Series(0.0, index=df.index)
    s += np.where(df["persist_below"], 28, 0)                                 # sustained below fair value
    s += np.where(df["lower_low"] & ~df["rsi_bull_div"], 20, 0)              # fresh lows, momentum agrees
    s += np.where(df["lower_low"] & ~df["cvd_up"], 15, 0)                    # sellers still in control
    s += np.where(df["rsi"] < 40, 10, 0)
    br = df["breadth"]
    s += np.where(br.notna() & (br < 40), 15, 0)                              # broad participation in the fall
    return s.clip(0, 100).round()


def _uptrend_score(df: pd.DataFrame) -> pd.Series:
    """0-100: a bounce is CONTINUING / real UPTREND (ride it). Only above VWAP.
    Strict confirmation: reclaimed & holding VWAP + higher-lows + breadth + buyers (CVD up)."""
    s = pd.Series(0.0, index=df.index)
    s += np.where(df["persist_above"], 25, 0)                                 # holding above fair value
    s += np.where(df["higher_low"], 25, 0)                                    # higher-low skeleton
    s += np.where(df["cvd_up"], 20, 0)                                        # buyers regaining control
    s += np.where((df["rsi"] >= 55) & (df["rsi"] <= 72), 10, 0)             # healthy (not overbought) momentum
    br = df["breadth"]
    # Breadth confirms when available; partial credit when breadth not loaded.
    s += np.where(br.notna() & (br > 50), 20, np.where(br.isna(), 10, 0))
    return s.clip(0, 100).round()


def _topping_score(df: pd.DataFrame) -> pd.Series:
    """0-100: an up move looks TIRED / topping (defend CALL). Only above VWAP."""
    s = pd.Series(0.0, index=df.index)
    s += np.where(df["rsi"] > 70, 25, 0)                                      # overbought
    s += np.where(df["stretch_up"] > 1.2, 20, 0)                              # stretched far above fair value
    s += np.where(df["rsi_bear_div"], 18, 0)                                  # higher high, momentum fading
    s += np.where(df["cvd_bear_div"], 18, 0)                                  # buying drying up (mirror of cvd_bull_div)
    s += np.where(df["breadth_div_down"], 17, 0)                              # fewer stocks confirming the high
    s += np.where(df["upper_wick_frac"] > 0.4, 12, 0)                         # rejection wick at the top
    return s.clip(0, 100).round()


def _state(df: pd.DataFrame) -> pd.Series:
    """Label each candle into the 4-state swing map (+ NEUTRAL)."""
    out = pd.Series("NEUTRAL", index=df.index)
    above, below = df["above_vwap"], df["below_vwap"]
    rev, down = df["reversal_score"], df["downtrend_score"]
    up, top = df["uptrend_score"], df["topping_score"]

    # Continuation calls (UPTREND / DOWNTREND) require the signals to AGREE — a
    # conflicted tape (2+ pillars fighting) is exactly the trade that fizzles, so
    # we withhold the marker rather than send you into a move that won't follow through.
    ok = ~df["conflict"]
    m_down = below & df["persist_below"] & (down >= DOWNTREND_THRESH) & (down > rev) & ok
    m_top = above & (top >= TOPPING_THRESH) & (top > up)
    m_brew = below & (rev >= REVERSAL_THRESH) & (rev >= down)
    m_up = above & (up >= UPTREND_THRESH) & (up >= top) & ok

    out[m_down] = "DOWNTREND"        # defend PUT
    out[m_top] = "TOPPING"           # defend CALL
    out[m_brew] = "BOUNCE_BREWING"   # be patient (early reversal)
    out[m_up] = "UPTREND"            # ride it (bounce continuing)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Markers — only when the state CHANGES (keeps the chart readable)
# ══════════════════════════════════════════════════════════════════════════════

_STATE_KEYS = {
    "brewing": "BOUNCE_BREWING",
    "uptrend": "UPTREND",
    "downtrend": "DOWNTREND",
    "topping": "TOPPING",
}


def transition_markers(df: pd.DataFrame) -> dict:
    """
    Return {'brewing','uptrend','downtrend','topping': sub-df} at state-change
    candles only (so each marker appears once when the state flips, not every bar).
    """
    empty = df.iloc[0:0] if not df.empty else df
    if df.empty or "state" not in df.columns:
        return {k: empty for k in _STATE_KEYS}
    changed = df["state"] != df["state"].shift(1)
    return {k: df[(df["state"] == v) & changed] for k, v in _STATE_KEYS.items()}


# ══════════════════════════════════════════════════════════════════════════════
# Breadth — % of Nifty-50 stocks above their own VWAP (a real-vs-fake check)
# ══════════════════════════════════════════════════════════════════════════════

def breadth_series(stock_dfs: dict) -> pd.Series:
    """
    Given {symbol: intraday OHLCV}, return a Series (indexed by timestamp) of the
    percentage of Nifty-50 stocks trading ABOVE their own session VWAP.
    High = broad strength; low = broad weakness. Empty Series if no data.
    """
    if not stock_dfs:
        return pd.Series(dtype=float)
    flags = []
    for sym, df in stock_dfs.items():
        if df is None or df.empty or "close" not in df.columns:
            continue
        d = df.copy()
        d.columns = [c.lower() for c in d.columns]
        if not isinstance(d.index, pd.DatetimeIndex):
            d.index = pd.to_datetime(d.index)
        try:
            v = _session_vwap(d)
            flags.append((d["close"] > v).astype(float).rename(sym))
        except Exception:
            continue
    if not flags:
        return pd.Series(dtype=float)
    mat = pd.concat(flags, axis=1)
    return (mat.mean(axis=1) * 100.0).rename("breadth")


# ══════════════════════════════════════════════════════════════════════════════
# Current live verdict (combines the intraday read with today's gamma regime)
# ══════════════════════════════════════════════════════════════════════════════

def live_verdict(df: pd.DataFrame, gamma_regime: str, spot_vs_flip: float) -> dict:
    """
    Combine the latest candle's 4-state read with today's dealer-gamma regime
    into one plain-English call covering BOTH the PUT and CALL side.
    """
    if df.empty:
        return {"badge": "NO DATA", "color": "#64748b",
                "headline": "No intraday data yet.", "detail": "",
                "bull_read": 0, "bear_read": 0, "state": "NO_DATA"}

    last = df.iloc[-1]
    state = last["state"]
    bull = int(last.get("bull_read", 0))
    bear = int(last.get("bear_read", 0))
    conf = int(last.get("confidence", 0))
    conflict = bool(last.get("conflict", False))
    agree = int(last.get("agree_count", 0))
    oppose = int(last.get("oppose_count", 0))
    pos_gamma = gamma_regime == "POSITIVE"
    above_flip = (spot_vs_flip or 0) >= 0
    cushioned = pos_gamma or above_flip          # dealers dampening = mean-revert friendly

    def _ret(badge, color, headline, detail):
        return {"badge": badge, "color": color, "headline": headline, "detail": detail,
                "bull_read": bull, "bear_read": bear, "state": state,
                "confidence": conf, "conflict": conflict, "agree": agree, "oppose": oppose}

    # Conflict gate first: if the tape is fighting itself and there's no clean
    # exhaustion turn, the honest call is STAND ASIDE — this is the move that
    # usually doesn't materialise and traps you.
    if conflict and state in ("NEUTRAL",):
        return _ret(
            "MIXED — STAND ASIDE", "#a855f7",
            f"Signals disagree ({oppose} of the pillars are fighting the direction).",
            "This is the classic 'looks like a move but doesn't follow through' setup. The honest edge "
            "here is to NOT initiate — wait until the pillars line up (confidence climbs) before trusting "
            "a continuation. See the scorecard below for exactly which signals conflict.")

    if state == "UPTREND":
        if cushioned:
            badge, color = "RIDE THE UPTREND", "#16a34a"
            headline = "Bounce is CONTINUING — reclaimed fair value with higher lows, breadth and buyers."
            detail = (f"Up-read {bull}/100. This is a confirmed up-leg, not a one-candle pop. Your sold-PUT "
                      "side is getting safer by the candle. Stay in it; only the CALL side needs watching "
                      "if it runs into the topping signal.")
        else:
            badge, color = "UPTREND — BUT THIN AIR", "#22c55e"
            headline = "Bounce is continuing, but dealers are in accelerator mode (moves over-extend)."
            detail = (f"Up-read {bull}/100. Fine to ride, but in this regime up-moves can spike then snap. "
                      "Trail a stop under the most recent higher-low rather than assuming it glides.")
    elif state == "TOPPING":
        badge, color = "DEFEND CALL — upside tiring", "#f59e0b"
        headline = "Above fair value but the up-move looks exhausted (overbought / stretched / fewer stocks confirming)."
        detail = (f"Bear-read {bear}/100. Momentum is fading at the highs. Your sold-CALL leg is the one to "
                  "watch now — tighten it or be ready if price rolls back under VWAP.")
    elif state == "BOUNCE_BREWING":
        if cushioned:
            badge, color = "BOUNCE BREWING", "#10b981"
            headline = "Falling, but the move looks tired AND dealers cushion dips."
            detail = (f"Bull-read {bull}/100. Stretched, momentum fading, big players in shock-absorber mode. "
                      "Booking the loss right at the low is usually the worst moment — wait for a VWAP reclaim "
                      "(which would flip this to RIDE THE UPTREND) before deciding.")
        else:
            badge, color = "WAIT — BUT STAY ALERT", "#f59e0b"
            headline = "The fall looks tired, but dealers are NOT cushioning today."
            detail = (f"Bull-read {bull}/100. A bounce may come, but in accelerator mode it can be shallow and "
                      "fail. Give it room, but keep a hard line: if price loses the recent low on volume, act.")
    elif state == "DOWNTREND":
        badge, color = "DEFEND PUT — real downtrend", "#ef4444"
        headline = "Persistent below fair value, not a one-candle dip."
        detail = (f"Bear-read {bear}/100. Sustained lower lows with momentum and breadth agreeing. Do not wait "
                  "for a V-recovery — manage the threatened PUT side now.")
    else:
        side = "above" if bool(last.get("above_vwap")) else "below"
        badge, color = "NEUTRAL — NO EDGE", "#64748b"
        headline = f"Price is {side} fair value but no clear continuation or exhaustion signal yet."
        detail = "Nothing decisive. Let the next few candles resolve. Avoid acting on emotion in the chop."

    return _ret(badge, color, headline, detail)


# ══════════════════════════════════════════════════════════════════════════════
# Two-sided verdict — BOTH legs of the condor are always live, so show BOTH cases
# ══════════════════════════════════════════════════════════════════════════════
# The live_verdict() above collapses everything into ONE badge (the dominant
# state). But an Iron Condor seller always carries a sold-PUT *and* a sold-CALL,
# so the honest read is two-sided: how loud is the BULL case (stay / be patient)
# vs the BEAR case (defend) right now — using the raw sub-scores, not the merge.

def two_sided_verdict(df: pd.DataFrame, gamma_regime: str = "UNKNOWN",
                      spot_vs_flip=None) -> dict:
    """
    Return {'bull': {...}, 'bear': {...}} for the latest candle, each with a
    plain-English label + 0-100 score, so both sides are visible at once.
      bull  = the case for staying / patience  (above VWAP → uptrend/ride,
                                                 below VWAP → bounce-brewing/be-patient)
      bear  = the case for defending           (above VWAP → topping/defend-CALL,
                                                 below VWAP → downtrend/defend-PUT)
    """
    if df is None or df.empty:
        z = {"label": "—", "leg": "", "score": 0, "color": "#64748b", "detail": "No data."}
        return {"bull": dict(z), "bear": dict(z)}

    last = df.iloc[-1]
    above = bool(last.get("above_vwap", False))
    rev = int(last.get("reversal_score", 0))
    up = int(last.get("uptrend_score", 0))
    down = int(last.get("downtrend_score", 0))
    top = int(last.get("topping_score", 0))

    def _intensity(base_hex_dark, base_hex_light, score):
        # brighter / more saturated as the score climbs (visual heat)
        return base_hex_dark if score >= 60 else base_hex_light

    if above:
        bull = {"label": "Uptrend — ride it", "leg": "sold-PUT safer", "score": up,
                "color": _intensity("#16a34a", "#86efac", up),
                "detail": "Holding above fair value with higher lows / buyers."}
        bear = {"label": "Topping — defend CALL", "leg": "sold-CALL at risk", "score": top,
                "color": _intensity("#f59e0b", "#fcd34d", top),
                "detail": "Above fair value but the up-move looks tired."}
    else:
        bull = {"label": "Bounce brewing", "leg": "sold-PUT relief", "score": rev,
                "color": _intensity("#10b981", "#6ee7b7", rev),
                "detail": "Below fair value but the fall looks stretched / tired."}
        bear = {"label": "Downtrend — defend PUT", "leg": "sold-PUT at risk", "score": down,
                "color": _intensity("#ef4444", "#fca5a5", down),
                "detail": "Persistent below fair value — a real trend down."}

    # Dealer-gamma context tilts which side to trust more (today-only).
    cushioned = (gamma_regime == "POSITIVE") or ((spot_vs_flip or 0) >= 0)
    bull["gamma"] = "dealers cushion dips (helps the bull case)" if cushioned \
        else "dealers in accelerator mode (bull case weaker)"
    bear["gamma"] = "dealers amplify moves (helps the bear case)" if not cushioned \
        else "dealers cushion moves (bear case weaker)"
    return {"bull": bull, "bear": bear, "above_vwap": above}


# ══════════════════════════════════════════════════════════════════════════════
# Behind-the-scenes — every per-candle calculation as one tidy table
# ══════════════════════════════════════════════════════════════════════════════
# Nothing new is computed here: we only RE-EXPOSE the columns enrich() already
# produced so a trader can audit, candle by candle, exactly why a marker did or
# did not fire — both the BULL sub-scores and the BEAR sub-scores side by side.

_VOTE_ARROW = {1: "▲", -1: "▼", 0: "·"}


def candle_table(df: pd.DataFrame, newest_first: bool = True,
                 gamma_by_date: dict = None) -> pd.DataFrame:
    """
    Build a display DataFrame: one row per candle, every calculation in columns,
    grouped Price → Momentum → Volume → Stretch → Structure → Breadth →
    the 4 raw scores (bull pair / bear pair) → pillar votes → confidence → state.
    Returns plain values (the page applies the colour heat-map).
    """
    if df is None or df.empty:
        return pd.DataFrame()

    d = df.copy()

    def _b(col, mark="●"):
        return np.where(d.get(col, False).astype(bool), mark, "") if col in d else ""

    def _persist():
        # Actual run length of consecutive candles on the same side of VWAP (not just ≥3):
        # e.g. ↑5 = 5 candles in a row above fair value, ↓2 = 2 below.
        side = pd.Series(np.where(d["above_vwap"], 1, np.where(d["below_vwap"], -1, 0)),
                         index=d.index)
        run = side.groupby((side != side.shift()).cumsum()).cumcount() + 1
        return [f"↑{n}" if s > 0 else (f"↓{n}" if s < 0 else "")
                for s, n in zip(side, run)]

    t = pd.DataFrame(index=d.index)
    t["Time"] = [ix.strftime("%d-%b %H:%M") for ix in d.index]
    t["ΔVWAP"] = (d["close"] - d["vwap"]).round(1)
    # Momentum + the two divergences. Bull/bear divergence are mutually exclusive
    # (one needs RSI up, the other RSI down) → one signed column each.
    t["RSI"] = d["rsi"].round(1)
    t["RSIdiv"] = np.where(d["rsi_bull_div"].astype(bool), "▲",
                           np.where(d["rsi_bear_div"].astype(bool), "▼", ""))
    # Volume: CVD↑ = CVD rose vs the PREVIOUS candle; CVDdiv = 6-bar volume divergence.
    t["CVD↑"] = _b("cvd_rising", "▲")
    t["CVDdiv"] = np.where(d["cvd_bull_div"].astype(bool), "▲",
                           np.where(d["cvd_bear_div"].astype(bool), "▼", ""))
    # Swing structure in ONE space-saving column: Hi char + Lo char side by side.
    # ▲▲ uptrend · ▼▼ downtrend · ▲▼ expanding (outside) · ▼▲ inside (contracting).
    _hi_c = np.where(d["higher_high"].astype(bool), "▲",
                     np.where(d["lower_high"].astype(bool), "▼", "·"))
    _lo_c = np.where(d["lower_low"].astype(bool), "▼",
                     np.where(d["higher_low"].astype(bool), "▲", "·"))
    t["HiLo"] = [f"{a} {b}" for a, b in zip(_hi_c, _lo_c)]
    t["%B"] = d["pct_b"].round(2)
    # One signed Stretch column: + = stretched ABOVE fair value, − = stretched BELOW.
    t["Stretch"] = (d["stretch_up"] - d["stretch_down"]).round(2)
    t["LWick"] = d["lower_wick_frac"].round(2)
    t["UWick"] = d["upper_wick_frac"].round(2)
    # Single bidirectional candle-strength read (close-location-value): +1 = closed at the
    # high (bulls won), −1 = at the low (bears won). Captures momentum AND rejection in one.
    _rng = (d["high"] - d["low"]).replace(0, np.nan)
    t["Candle"] = (((d["close"] - d["low"]) - (d["high"] - d["close"])) / _rng).fillna(0).round(2)
    t["Persist"] = _persist()
    t["Brd%"] = d["breadth"].round(0)
    # ── the four raw scores, then a single NET conviction for a clear read ──────
    t["Reversal"] = d["reversal_score"].astype(int)     # 🟢 be patient
    t["Uptrend"] = d["uptrend_score"].astype(int)       # 🟢 ride it
    t["Downtr"] = d["downtrend_score"].astype(int)      # 🔴 defend PUT
    t["Topping"] = d["topping_score"].astype(int)       # 🔴 defend CALL
    # Bull−Bear = raw lean of the case scores (bull_read − bear_read).
    _bb = (d["bull_read"] - d["bear_read"])
    t["Bull−Bear"] = _bb.astype(int)                    # +bull / −bear (−100..+100)
    # Two separate columns so you can see gamma's push at a glance:
    #   Final = Bull−Bear × Conf% — the trust-adjusted conviction WITHOUT any gamma tilt.
    #   γ     = that SAME figure WITH today's-or-stored dealer-gamma tilt folded in, where we
    #           have a stored regime. A cushioned regime (POSITIVE) backs the bull case,
    #           accelerator (NEGATIVE) the bear case → ×1.15 if aligned, ×0.85 if it fights.
    #           Days with no stored gamma (e.g. no login) show "—" — never guessed.
    gamma_by_date = gamma_by_date or {}
    _dates = [ix.strftime("%Y-%m-%d") for ix in d.index]
    _conf = d["confidence"].to_numpy()
    _final, _gcol = [], []
    for _dt, _bbv, _cf in zip(_dates, _bb.to_numpy(), _conf):
        _base = max(-100.0, min(100.0, _bbv * _cf / 100.0))
        _final.append(int(round(_base)))
        _reg = gamma_by_date.get(_dt)
        if _reg in ("POSITIVE", "NEGATIVE"):
            _cush = _reg == "POSITIVE"
            _tilt = 1.0 if _bbv == 0 else (1.15 if (_cush if _bbv > 0 else not _cush) else 0.85)
            _gcol.append(int(round(max(-100.0, min(100.0, _base * _tilt)))))
        else:
            _gcol.append("—")
    t["Final"] = _final
    t["γ"] = _gcol
    # ── pillar votes ──────────────────────────────────────────────────────────
    t["P"] = [_VOTE_ARROW.get(int(v), "·") for v in d["bias"]]
    t["M"] = [_VOTE_ARROW.get(int(v), "·") for v in d["vote_mom"]]
    t["V"] = [_VOTE_ARROW.get(int(v), "·") for v in d["vote_vol"]]
    t["B"] = [_VOTE_ARROW.get(int(v), "·") for v in d["vote_brd"]]
    t["S"] = [_VOTE_ARROW.get(int(v), "·") for v in d["vote_str"]]
    t["Agree"] = d["agree_count"].astype(int)
    t["Oppose"] = d["oppose_count"].astype(int)
    t["Conf%"] = d["confidence"].astype(int)
    t["State"] = d["state"]
    # Raw price/VWAP/CVD inputs pushed to the far right.
    t["Open"] = d["open"].round(1)
    t["High"] = d["high"].round(1)
    t["Low"] = d["low"].round(1)
    t["Close"] = d["close"].round(1)
    t["VWAP"] = d["vwap"].round(1)
    t["CVD"] = d["cvd"].round(0)

    # Results lead (State · Net · Brd% · Conf%), then the key reads, then the rest, raw last.
    order = [
        "Time", "State", "Final", "γ", "Bull−Bear", "Brd%", "Conf%",
        "ΔVWAP", "RSI", "RSIdiv", "CVD↑", "CVDdiv", "HiLo", "LWick", "UWick", "Candle", "%B", "Stretch", "Persist",
        "Reversal", "Uptrend", "Downtr", "Topping",
        "P", "M", "V", "B", "S", "Agree", "Oppose",
        "Open", "High", "Low", "Close", "VWAP", "CVD",
    ]
    t = t[[c for c in order if c in t.columns]]

    return t.iloc[::-1] if newest_first else t


# ══════════════════════════════════════════════════════════════════════════════
# Close Conviction — was the LATE-DAY move trustworthy? (per trading day)
# ══════════════════════════════════════════════════════════════════════════════

def close_conviction(df: pd.DataFrame, breadth: pd.Series = None) -> pd.DataFrame:
    """
    Grade each completed day's CLOSE: a late bounce that closes below VWAP, on
    back-loaded volume, with no broad participation, is a low-conviction
    short-cover that often gives back the next morning (gap risk).

    Returns one row per day with a plain-English grade.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    d["vwap"] = _session_vwap(d)
    d["day"] = d.index.normalize()

    rows = []
    for day, g in d.groupby("day"):
        if len(g) < 4:
            continue
        hi, lo = g["high"].max(), g["low"].min()
        rng = (hi - lo) or 1.0
        close = float(g["close"].iloc[-1])
        open_ = float(g["open"].iloc[0])
        close_loc = (close - lo) / rng                       # 0=at low, 1=at high
        close_vs_vwap = close - float(g["vwap"].iloc[-1])

        # Last-hour behaviour vs the whole day.
        n_last = max(1, len(g) // 7)                          # ~ last hour of candles
        last_chunk = g.iloc[-n_last:]
        last_ret = float(last_chunk["close"].iloc[-1] - last_chunk["open"].iloc[0])
        day_vol = g["volume"].sum() or 1
        last_vol_share = float(last_chunk["volume"].sum()) / day_vol
        avg_share = n_last / len(g)
        vol_backloaded = last_vol_share > avg_share * 1.6     # volume piled into the close

        late_bounce = last_ret > 0 and close_loc > 0.55 and (close - open_) >= 0

        # Score the trustworthiness of an up-close (keep each contribution so the
        # page can show exactly how the grade was built).
        c_base = 50
        c_vwap = 18 if close_vs_vwap > 0 else -18            # closed above/below fair value
        c_loc = 12 if close_loc > 0.7 else (-12 if close_loc < 0.4 else 0)
        c_shortcover = -25 if (late_bounce and vol_backloaded and close_vs_vwap < 0) else 0
        c_breadth = 0
        if breadth is not None and not breadth.empty:
            br_close = breadth.reindex(g.index, method="nearest").iloc[-1]
            if pd.notna(br_close):
                c_breadth = 10 if br_close > 55 else (-10 if br_close < 40 else 0)
        score = int(np.clip(c_base + c_vwap + c_loc + c_shortcover + c_breadth, 0, 100))

        if score >= 65:
            grade, gtext = "HIGH", "Strong, trustworthy close — backed by fair-value & participation."
        elif score >= 45:
            grade, gtext = "MEDIUM", "Mixed close — some support, but not fully confirmed."
        else:
            grade, gtext = "LOW", "Weak close — looks like a late short-cover. Gap risk elevated; don't chase."

        note = ""
        if late_bounce and vol_backloaded and close_vs_vwap < 0:
            note = "Late bounce on a volume spike but still below fair value → typically retraced next session."

        rows.append({
            "date": day.date(),
            "close": round(close),
            "close_location": round(close_loc * 100),
            "above_vwap": close_vs_vwap > 0,
            "late_bounce": late_bounce,
            "vol_backloaded": vol_backloaded,
            "grade": grade,
            "score": score,
            "c_base": c_base,
            "c_vwap": c_vwap,
            "c_loc": c_loc,
            "c_shortcover": c_shortcover,
            "c_breadth": c_breadth,
            "plain": gtext,
            "note": note,
        })

    return pd.DataFrame(rows)
