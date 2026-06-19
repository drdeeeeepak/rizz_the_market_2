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
           breadth: pd.Series = None) -> pd.DataFrame:
    """
    Add every per-candle column used by the chart and the verdict.
    df must be intraday OHLCV with a DatetimeIndex.
    expected_move_pts : today's VIX-implied one-day move (points). Used for stretch.
    breadth           : optional Series (% of Nifty-50 above their VWAP), aligned later.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    df["vwap"] = _session_vwap(df)
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
    em_half = max(expected_move_pts * 0.5, 1.0)
    df["stretch_down"] = ((df["vwap"] - df["close"]) / em_half).clip(lower=0)
    df["stretch_up"] = ((df["close"] - df["vwap"]) / em_half).clip(lower=0)

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
    df["lower_low"] = px_ll
    df["higher_high"] = px_hh

    # Swing structure: higher-lows = uptrend skeleton.
    rl = df["low"].rolling(DIV_LOOKBACK).min()
    df["higher_low"] = rl > rl.shift(DIV_LOOKBACK)

    # Buyers regaining control (CVD turning up) — the continuation tell.
    df["cvd_up"] = df["cvd"] > df["cvd"].shift(DIV_LOOKBACK)

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

    df["state"] = _state(df)
    return df


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
    s += np.where(df["breadth_div_down"], 17, 0)                              # fewer stocks confirming the high
    s += np.where(df["upper_wick_frac"] > 0.4, 12, 0)                         # rejection wick at the top
    return s.clip(0, 100).round()


def _state(df: pd.DataFrame) -> pd.Series:
    """Label each candle into the 4-state swing map (+ NEUTRAL)."""
    out = pd.Series("NEUTRAL", index=df.index)
    above, below = df["above_vwap"], df["below_vwap"]
    rev, down = df["reversal_score"], df["downtrend_score"]
    up, top = df["uptrend_score"], df["topping_score"]

    m_down = below & df["persist_below"] & (down >= DOWNTREND_THRESH) & (down > rev)
    m_top = above & (top >= TOPPING_THRESH) & (top > up)
    m_brew = below & (rev >= REVERSAL_THRESH) & (rev >= down)
    m_up = above & (up >= UPTREND_THRESH) & (up >= top)

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
    pos_gamma = gamma_regime == "POSITIVE"
    above_flip = (spot_vs_flip or 0) >= 0
    cushioned = pos_gamma or above_flip          # dealers dampening = mean-revert friendly

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
            badge, color = "BE PATIENT", "#10b981"
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

    return {"badge": badge, "color": color, "headline": headline, "detail": detail,
            "bull_read": bull, "bear_read": bear, "state": state}


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

        # Score the trustworthiness of an up-close.
        score = 50
        score += 18 if close_vs_vwap > 0 else -18             # closed above/below fair value
        score += 12 if close_loc > 0.7 else (-12 if close_loc < 0.4 else 0)
        if late_bounce and vol_backloaded and close_vs_vwap < 0:
            score -= 25                                       # classic short-cover into the close
        if breadth is not None and not breadth.empty:
            br_close = breadth.reindex(g.index, method="nearest").iloc[-1]
            if pd.notna(br_close):
                score += 10 if br_close > 55 else (-10 if br_close < 40 else 0)
        score = int(np.clip(score, 0, 100))

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
            "plain": gtext,
            "note": note,
        })

    return pd.DataFrame(rows)
