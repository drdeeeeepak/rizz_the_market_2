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
DIV_LOOKBACK = 6        # candles back to compare for divergence
REVERSAL_THRESH = 60    # score ≥ this while below VWAP → patience signal
TREND_THRESH = 60       # score ≥ this → defend / trend signal


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

    # Stretch: how far below VWAP, measured in "expected daily moves".
    em_half = max(expected_move_pts * 0.5, 1.0)
    df["stretch_down"] = ((df["vwap"] - df["close"]) / em_half).clip(lower=0)

    # Rejection wick: long lower wick after a push down = buyers stepping in.
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    df["lower_wick_frac"] = ((df[["open", "close"]].min(axis=1) - df["low"]) / rng).fillna(0)

    # Divergences over the last DIV_LOOKBACK candles (within the visible series).
    px_ll = df["low"] < df["low"].shift(DIV_LOOKBACK)            # price lower low
    df["rsi_bull_div"] = px_ll & (df["rsi"] > df["rsi"].shift(DIV_LOOKBACK))
    df["cvd_bull_div"] = px_ll & (df["cvd"] > df["cvd"].shift(DIV_LOOKBACK))
    df["lower_low"] = px_ll

    # Breadth alignment (optional).
    if breadth is not None and not breadth.empty:
        df["breadth"] = breadth.reindex(df.index, method="nearest", tolerance=pd.Timedelta("20min"))
        df["breadth"] = df["breadth"].astype(float)
    else:
        df["breadth"] = np.nan

    # ── Scores ────────────────────────────────────────────────────────────────
    df["reversal_score"] = _reversal_score(df)
    df["trend_score"] = _trend_score(df)
    df["state"] = _state(df)
    return df


def _reversal_score(df: pd.DataFrame) -> pd.Series:
    """0-100: how strongly a downside move looks ready to bounce (be patient)."""
    s = pd.Series(0.0, index=df.index)
    s += np.where(df["below_vwap"], df["stretch_down"].clip(0, 2) * 18, 0)   # extended below fair value
    s += np.where(df["rsi"] < 35, (35 - df["rsi"]).clip(0, 20) * 1.2, 0)     # oversold
    s += np.where(df["rsi_bull_div"], 22, 0)                                  # momentum diverging up
    s += np.where(df["cvd_bull_div"], 18, 0)                                  # selling drying up
    s += np.where(df["lower_wick_frac"] > 0.4, 12, 0)                         # rejection wick
    s += np.where(df["pct_b"] < 0.05, 10, 0)                                  # stabbed below lower band
    # Breadth turning up while price is down = real exhaustion confirmation.
    br = df["breadth"]
    s += np.where(br.notna() & (br > br.shift(DIV_LOOKBACK)) & df["below_vwap"], 10, 0)
    return s.clip(0, 100).round()


def _trend_score(df: pd.DataFrame) -> pd.Series:
    """0-100: how strongly a downside move looks like a real trend (defend now)."""
    s = pd.Series(0.0, index=df.index)
    s += np.where(df["below_vwap"], 25, 0)                                    # sellers in control
    s += np.where(df["lower_low"] & ~df["rsi_bull_div"], 22, 0)              # fresh lows, momentum agrees
    s += np.where(df["lower_low"] & ~df["cvd_bull_div"], 18, 0)              # sellers still hitting it
    s += np.where(df["rsi"] < 40, 12, 0)
    s += np.where(df["pct_b"] < 0.2, 10, 0)                                   # riding the lower band = trend
    br = df["breadth"]
    s += np.where(br.notna() & (br < 35), 15, 0)                              # broad participation in the fall
    return s.clip(0, 100).round()


def _state(df: pd.DataFrame) -> pd.Series:
    """Label each candle: PATIENCE (bounce brewing) / TREND (defend) / NEUTRAL."""
    out = pd.Series("NEUTRAL", index=df.index)
    patience = (df["reversal_score"] >= REVERSAL_THRESH) & df["below_vwap"] & \
               (df["reversal_score"] >= df["trend_score"])
    trend = (df["trend_score"] >= TREND_THRESH) & df["below_vwap"] & \
            (df["trend_score"] > df["reversal_score"])
    out[trend] = "TREND"
    out[patience] = "PATIENCE"
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Markers — only when the state CHANGES (keeps the chart readable)
# ══════════════════════════════════════════════════════════════════════════════

def transition_markers(df: pd.DataFrame) -> dict:
    """Return {'patience': sub-df, 'trend': sub-df} at state-change candles only."""
    if df.empty or "state" not in df.columns:
        return {"patience": df.iloc[0:0], "trend": df.iloc[0:0]}
    changed = df["state"] != df["state"].shift(1)
    pat = df[(df["state"] == "PATIENCE") & changed]
    trd = df[(df["state"] == "TREND") & changed]
    return {"patience": pat, "trend": trd}


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
    Combine the latest candle's intraday state with today's dealer-gamma regime
    into one plain-English call.
    """
    if df.empty:
        return {"badge": "NO DATA", "color": "#64748b",
                "headline": "No intraday data yet.", "detail": ""}

    last = df.iloc[-1]
    state = last["state"]
    rev = int(last["reversal_score"])
    trd = int(last["trend_score"])
    below = bool(last["below_vwap"])
    pos_gamma = gamma_regime == "POSITIVE"
    above_flip = (spot_vs_flip or 0) >= 0

    # Master switch: gamma regime gates how much we trust "patience".
    if not below:
        badge, color = "ABOVE FAIR VALUE", "#10b981"
        headline = "Price is above the day's fair value (VWAP) — buyers in control."
        detail = ("Your sold-PUT side is comfortable here. No loss-booking pressure. "
                  "Watch the CALL side if price keeps pushing up.")
    elif state == "PATIENCE" and (pos_gamma or above_flip):
        badge, color = "BE PATIENT", "#10b981"
        headline = "Falling, but the move looks tired AND dealers cushion dips."
        detail = (f"Reversal read {rev}/100. The market is stretched and momentum is "
                  "fading while big players are in shock-absorber mode. Booking the loss "
                  "right at the low is usually the worst moment — wait for a VWAP reclaim "
                  "or for price to settle before deciding.")
    elif state == "PATIENCE" and not (pos_gamma or above_flip):
        badge, color = "WAIT — BUT STAY ALERT", "#f59e0b"
        headline = "The fall looks tired, but dealers are NOT cushioning today."
        detail = (f"Reversal read {rev}/100. A bounce may come, but in accelerator mode "
                  "it can be shallow and fail. Give it a little room, but keep a hard line: "
                  "if price loses the recent low on volume, act.")
    elif state == "TREND":
        badge, color = "DEFEND NOW", "#ef4444"
        headline = "This is behaving like a real trend day, not a dip."
        detail = (f"Trend read {trd}/100. Fresh lows, momentum and volume agree, breadth is "
                  "weak. Do not wait for a V-recovery — manage the threatened (PUT) side now.")
    else:
        badge, color = "NEUTRAL — NO EDGE", "#64748b"
        headline = "Below fair value but no clear exhaustion or trend signal yet."
        detail = ("Nothing decisive. Let the next few candles resolve. Avoid acting on "
                  "emotion in the chop.")

    return {"badge": badge, "color": color, "headline": headline, "detail": detail,
            "reversal_score": rev, "trend_score": trd, "state": state}


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
