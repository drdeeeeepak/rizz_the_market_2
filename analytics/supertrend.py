# analytics/supertrend.py — premiumdecay Page 14
# SuperTrend MTF Engine (21, 2) · Six scored TFs + 5m display-only
# Measuring unit: % of CMP throughout
# Proxy TFs: 2H and 4H resampled from 1H OHLCV
# 27 Apr 2026

import logging
import numpy as np
import pandas as pd
from datetime import datetime, time as dtime
from typing import Optional

log = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

ST_PERIOD     = 21
ST_MULTIPLIER = 2.0

# TF weights (total = 90, max raw score = 180 when all DEEP 2.0×)
TF_WEIGHTS = {
    "daily": 30,
    "4h":    20,
    "2h":    15,
    "1h":    12,
    "30m":    8,
    "15m":    5,
}

TF_ORDER = ["daily", "4h", "2h", "1h", "30m", "15m"]   # deepest → shallowest

# Depth thresholds as % CMP
DEPTH_DEEP        = 3.0
DEPTH_COMFORTABLE = 2.0
DEPTH_ADEQUATE    = 1.0
DEPTH_THIN        = 0.5
# < THIN = CRITICAL

# Depth multipliers
DEPTH_MULT = {
    "DEEP":        2.0,
    "COMFORTABLE": 1.5,
    "ADEQUATE":    1.0,
    "THIN":        0.5,
    "CRITICAL":    0.2,
}

# Safe distance — Tier 1 only (Daily, 4H, 2H)
TIER1_TFS            = ["daily", "4h", "2h"]
SD_WALL_TOO_CLOSE    = 1.0    # wall < 1% → use floor
SD_WALL_TOO_DEEP     = 2.0    # wall > 2% → use ceiling
SD_BUFFER            = 1.0    # add 1% to wall when in sweet spot
SD_FLOOR             = 2.0    # output when no wall / wall too close / wall too deep (< 2%)
SD_CEILING           = 2.5    # hard ceiling — never exceeded
# Case summary:
#   no wall         → 2.0%
#   wall < 1%       → 2.0%  (too close)
#   wall 1%–2%      → min(wall + 1%, 2.5%)
#   wall > 2%       → 2.5%  (deep wall, structure strong)

# Cluster rule: two adjacent TF lines within this % CMP = single wall
CLUSTER_PCT          = 0.5

# IC shape skew threshold (normalised score difference)
SHAPE_SKEW_THRESHOLD = 25.0

# Max normalised score denominator
MAX_RAW = 180.0

# Home score max contribution
ST_HOME_SCORE_MAX = 9   # rescaled from 10 → 9 per Option B


# ─── SuperTrend Computation ───────────────────────────────────────────────────

def compute_supertrend(df: pd.DataFrame, period: int = ST_PERIOD,
                       multiplier: float = ST_MULTIPLIER) -> pd.DataFrame:
    """
    Compute SuperTrend on OHLCV DataFrame.
    Returns df with columns: st_line, st_direction (1=BULL, -1=BEAR), st_flip
    st_flip=True means direction changed on this candle.
    """
    if df is None or df.empty or len(df) < period + 1:
        return pd.DataFrame()

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    # ATR
    hl  = df["high"] - df["low"]
    hc  = (df["high"] - df["close"].shift(1)).abs()
    lc  = (df["low"]  - df["close"].shift(1)).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    # Basic bands
    hl2         = (df["high"] + df["low"]) / 2
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    # Final bands (vectorised using loop — required for path dependency)
    n            = len(df)
    upper_final  = upper_basic.copy()
    lower_final  = lower_basic.copy()
    direction    = pd.Series(1, index=df.index)   # 1=BULL, -1=BEAR

    for i in range(1, n):
        # Upper band
        if upper_basic.iloc[i] < upper_final.iloc[i-1] or df["close"].iloc[i-1] > upper_final.iloc[i-1]:
            upper_final.iloc[i] = upper_basic.iloc[i]
        else:
            upper_final.iloc[i] = upper_final.iloc[i-1]

        # Lower band
        if lower_basic.iloc[i] > lower_final.iloc[i-1] or df["close"].iloc[i-1] < lower_final.iloc[i-1]:
            lower_final.iloc[i] = lower_basic.iloc[i]
        else:
            lower_final.iloc[i] = lower_final.iloc[i-1]

        # Direction
        if direction.iloc[i-1] == -1 and df["close"].iloc[i] > upper_final.iloc[i-1]:
            direction.iloc[i] = 1
        elif direction.iloc[i-1] == 1 and df["close"].iloc[i] < lower_final.iloc[i-1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i-1]

    # ST line = lower_final when BULL, upper_final when BEAR
    st_line = pd.Series(np.where(direction == 1, lower_final, upper_final), index=df.index)
    st_flip = direction.diff().fillna(0) != 0

    result = df[["open", "high", "low", "close", "volume"]].copy()
    result["st_line"]      = st_line
    result["st_direction"] = direction
    result["st_flip"]      = st_flip
    return result


# ─── Proxy Resampling ─────────────────────────────────────────────────────────

def resample_ohlcv(df_1h: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Resample 1H OHLCV to 2H or 4H.
    rule: '2h' or '4h'
    Returns OHLCV DataFrame with DatetimeIndex.
    """
    if df_1h is None or df_1h.empty:
        return pd.DataFrame()

    df = df_1h.copy()
    df.columns = [c.lower() for c in df.columns]

    # Ensure datetime index
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # Localize if naive
    if df.index.tz is None:
        df.index = df.index.tz_localize("Asia/Kolkata")

    freq = "2h" if rule == "2h" else "4h"
    resampled = df.resample(freq, origin="start_day").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna(subset=["open", "close"])

    return resampled


# ─── Depth Classification ─────────────────────────────────────────────────────

def classify_depth(pct: float) -> str:
    if pct >= DEPTH_DEEP:        return "DEEP"
    if pct >= DEPTH_COMFORTABLE: return "COMFORTABLE"
    if pct >= DEPTH_ADEQUATE:    return "ADEQUATE"
    if pct >= DEPTH_THIN:        return "THIN"
    return "CRITICAL"


# ─── Per-TF Signal Extraction ─────────────────────────────────────────────────

def extract_tf_signal(st_df: pd.DataFrame, spot: float, tf_name: str) -> dict:
    """
    Extract signal for one TF from a computed ST DataFrame.
    Returns dict with all fields needed for moat scoring and display.
    """
    if st_df is None or st_df.empty:
        return _empty_tf_signal(tf_name)

    last      = st_df.iloc[-1]
    prev      = st_df.iloc[-2] if len(st_df) >= 2 else last

    direction = int(last["st_direction"])   # 1=BULL, -1=BEAR
    st_price  = float(last["st_line"])

    # FLIP: direction changed in last 2 candles
    flip = bool(last["st_flip"]) or bool(prev["st_flip"])

    # Last flip candle → flip_price and flip_time for SLEEPING/DRIVING detection
    _flip_rows = st_df[st_df["st_flip"] == True]
    if not _flip_rows.empty:
        _lf        = _flip_rows.iloc[-1]
        flip_price = float(_lf["close"])
        flip_time  = str(_lf.name)[:16]   # "YYYY-MM-DD HH:MM"
    else:
        flip_price = st_price
        flip_time  = "—"

    # SLEEPING: spot trapped between ST line and flip price (chop zone)
    # DRIVING:  spot has cleared the flip price (institutional expansion)
    if direction == 1:   # BULL — ST line below spot
        state = "DRIVING" if spot > flip_price else "SLEEPING"
    else:                # BEAR — ST line above spot
        state = "DRIVING" if spot < flip_price else "SLEEPING"

    # Distance from spot
    dist_pts = abs(spot - st_price)
    dist_pct = (dist_pts / spot * 100) if spot > 0 else 0.0

    # Which side does this wall protect?
    # BULL = line below spot = PUT wall
    # BEAR = line above spot = CALL wall
    if direction == 1:
        side = "PUT"
        above = False
    else:
        side = "CALL"
        above = True

    # Depth label
    depth = classify_depth(dist_pct)

    # Depth multiplier
    mult = DEPTH_MULT.get(depth, 0.2)

    # Raw score contribution
    weight    = TF_WEIGHTS.get(tf_name, 0)
    raw_score = weight * mult

    return {
        "tf":          tf_name,
        "direction":   "BULL" if direction == 1 else "BEAR",
        "side":        side,          # which IC leg this protects
        "st_price":    st_price,
        "dist_pts":    round(dist_pts),
        "dist_pct":    round(dist_pct, 2),
        "depth":       depth,
        "mult":        mult,
        "weight":      weight,
        "raw_score":   round(raw_score, 1),
        "flip":        flip,
        "above":       above,         # True = line above spot
        "flip_price":  round(flip_price, 0),
        "flip_time":   flip_time,
        "state":       state,         # "DRIVING" | "SLEEPING"
    }


def _empty_tf_signal(tf_name: str) -> dict:
    return {
        "tf": tf_name, "direction": "UNKNOWN", "side": "NONE",
        "st_price": 0.0, "dist_pts": 0, "dist_pct": 0.0,
        "depth": "UNKNOWN", "mult": 0.0, "weight": TF_WEIGHTS.get(tf_name, 0),
        "raw_score": 0.0, "flip": False, "above": False,
        "flip_price": 0.0, "flip_time": "—", "state": "UNKNOWN",
    }


# ─── Moat Stack Builder ───────────────────────────────────────────────────────

def build_moat_stack(tf_signals: dict, side: str) -> dict:
    """
    Build moat stack for one side (PUT or CALL).
    side: "PUT" or "CALL"

    Returns:
      walls: list of tf signal dicts on this side, ordered deepest first
      raw_score: sum of raw scores
      normalised: 0-100
      band: FORTRESS/STRONG/ADEQUATE/THIN/EXPOSED/BREACHED
      clusters: list of cluster pairs (tf names)
    """
    walls = []
    for tf in TF_ORDER:
        sig = tf_signals.get(tf)
        if sig is None or sig["direction"] == "UNKNOWN":
            continue
        if sig["side"] == side:
            walls.append(sig)

    # Sort deepest (highest dist_pct) first
    walls_sorted = sorted(walls, key=lambda x: x["dist_pct"], reverse=True)

    raw = sum(w["raw_score"] for w in walls_sorted)
    normalised = round((raw / MAX_RAW) * 100, 1)

    # Cluster detection: adjacent walls within CLUSTER_PCT of each other
    clusters = []
    for i in range(len(walls_sorted) - 1):
        w1 = walls_sorted[i]
        w2 = walls_sorted[i+1]
        if abs(w1["dist_pct"] - w2["dist_pct"]) <= CLUSTER_PCT:
            clusters.append((w1["tf"], w2["tf"]))

    # Band
    if   normalised >= 75: band = "FORTRESS"
    elif normalised >= 55: band = "STRONG"
    elif normalised >= 35: band = "ADEQUATE"
    elif normalised >= 20: band = "THIN"
    elif normalised >= 5:  band = "EXPOSED"
    else:                  band = "BREACHED"

    return {
        "side":       side,
        "walls":      walls_sorted,
        "wall_count": len(walls_sorted),
        "raw_score":  round(raw, 1),
        "normalised": normalised,
        "band":       band,
        "clusters":   clusters,
    }


# ─── Safe Distance Computation ────────────────────────────────────────────────

def compute_safe_distance(tf_signals: dict, side: str, spot: float) -> dict:
    """
    Compute ST safe distance for one IC leg using Tier 1 walls only.

    Only Daily, 4H, 2H walls are used for strike placement.
    Lower TFs are S/R reference only — not used here.

    Four cases:
      Case 3 — No Tier 1 wall on this side      → 2.0% floor
      Case 1a — Nearest wall < 1%               → 2.0% floor (too close)
      Case 1b — Nearest wall 1%–2%              → min(wall% + 1%, 2.5%)
      Case 2  — Nearest wall > 2%               → 2.5% ceiling (deep, strong)

    Returns dict with dist_pct, dist_pts, strike, case, wall_tf, wall_pct.
    """
    # Collect Tier 1 walls on this side
    tier1_walls = []
    for tf in TIER1_TFS:
        sig = tf_signals.get(tf, {})
        if sig.get("side") == side and sig.get("direction") != "UNKNOWN":
            tier1_walls.append(sig)

    # Sort by distance ascending (nearest first)
    tier1_walls.sort(key=lambda w: w["dist_pct"])

    if not tier1_walls:
        # Case 3 — no Tier 1 wall
        dist_pct  = SD_FLOOR
        case      = "NO_WALL"
        wall_tf   = None
        wall_pct  = None
        label     = "No Tier 1 wall — 2.0% floor"
    else:
        nearest   = tier1_walls[0]
        wall_pct  = nearest["dist_pct"]
        wall_tf   = nearest["tf"]

        if wall_pct < SD_WALL_TOO_CLOSE:
            # Case 1a — wall too close
            dist_pct = SD_FLOOR
            case     = "WALL_TOO_CLOSE"
            label    = f"{wall_tf.upper()} ST at {wall_pct:.2f}% — too close, 2.0% floor"

        elif wall_pct <= SD_WALL_TOO_DEEP:
            # Case 1b — sweet spot
            dist_pct = min(wall_pct + SD_BUFFER, SD_CEILING)
            case     = "WALL_USED"
            label    = (f"{wall_tf.upper()} ST at {wall_pct:.2f}% + 1% buffer"
                        + (" — capped at 2.5%" if dist_pct == SD_CEILING else ""))

        else:
            # Case 2 — wall deep beyond 2%
            dist_pct = SD_CEILING
            case     = "WALL_DEEP"
            label    = f"{wall_tf.upper()} ST at {wall_pct:.2f}% — deep wall, 2.5% applied"

    # Convert to points and strike
    dist_pts = int(round(spot * dist_pct / 100 / 50) * 50)

    if side == "PUT":
        strike = int(round((spot - dist_pts) / 50) * 50)
    else:
        strike = int(round((spot + dist_pts) / 50) * 50)

    return {
        "dist_pct":  round(dist_pct, 2),
        "dist_pts":  dist_pts,
        "strike":    strike,
        "case":      case,
        "wall_tf":   wall_tf,
        "wall_pct":  wall_pct,
        "label":     label,
        "all_tier1_walls": tier1_walls,
    }


# ─── Trajectory ───────────────────────────────────────────────────────────────

def compute_trajectory(
    current_put_norm:  float,
    current_call_norm: float,
    prev_put_norm:     Optional[float],
    prev_call_norm:    Optional[float],
    kind:              str,           # "structural" or "intraday"
    flip_tfs:          list,
) -> dict:
    """
    kind='structural': compare EOD-to-EOD (Tier 1 TFs: daily/4h/2h)
    kind='intraday':   compare current to 9:15 AM snapshot (Tier 3: 1h/30m/15m)
    """
    if prev_put_norm is None or prev_call_norm is None:
        return {
            "put_delta": None, "call_delta": None,
            "put_label": "UNKNOWN", "call_label": "UNKNOWN",
            "flip_event": bool(flip_tfs), "flip_tfs": flip_tfs,
            "kind": kind,
        }

    put_delta  = round(current_put_norm  - prev_put_norm,  1)
    call_delta = round(current_call_norm - prev_call_norm, 1)

    def _label(delta, kind):
        if kind == "structural":
            if delta >  10: return "STRENGTHENING"
            if delta >   3: return "IMPROVING"
            if delta >= -3: return "STABLE"
            if delta >= -10:return "WEAKENING"
            return "DETERIORATING"
        else:  # intraday
            if delta >   8: return "INTRADAY STRENGTHENING"
            if delta >   3: return "INTRADAY IMPROVING"
            if delta >= -3: return "INTRADAY STABLE"
            if delta >= -8: return "INTRADAY WEAKENING"
            return "INTRADAY DETERIORATING"

    return {
        "put_delta":  put_delta,
        "call_delta": call_delta,
        "put_label":  _label(put_delta, kind),
        "call_label": _label(call_delta, kind),
        "flip_event": bool(flip_tfs),
        "flip_tfs":   flip_tfs,
        "kind":       kind,
    }


# ─── IC Shape Signal ──────────────────────────────────────────────────────────

def compute_ic_shape(put_norm: float, call_norm: float,
                     put_band: str, call_band: str) -> str:
    if put_band == "BREACHED":  return "SINGLE_CE"
    if call_band == "BREACHED": return "SINGLE_PE"

    diff = put_norm - call_norm
    if diff > SHAPE_SKEW_THRESHOLD:    return "CE_SKEW"
    if diff < -SHAPE_SKEW_THRESHOLD:   return "PE_SKEW"
    return "SYMMETRIC"


# ─── Home Score ───────────────────────────────────────────────────────────────

def compute_home_score(put_norm: float, call_norm: float) -> int:
    avg_norm = (put_norm + call_norm) / 2.0
    raw      = (avg_norm / 100.0) * ST_HOME_SCORE_MAX
    return min(ST_HOME_SCORE_MAX, max(0, round(raw)))


# ─── Main Engine ──────────────────────────────────────────────────────────────

class SuperTrendEngine:
    """
    SuperTrend MTF Engine for premiumdecay Page 15.

    Required inputs:
      df_daily  : daily OHLCV (from get_nifty_daily)
      df_1h     : 1H OHLCV   (from get_nifty_1h_phase — same fetch as Dow Theory)
      df_30m    : 30m OHLCV  (from get_nifty_30m)
      df_15m    : 15m OHLCV  (from get_nifty_15m)
      df_5m     : 5m OHLCV   (from get_nifty_5m — display only)
      spot      : current Nifty spot price
      prev_put_norm_eod   : yesterday's PUT normalised score (for structural trajectory)
      prev_call_norm_eod  : yesterday's CALL normalised score
      open_put_norm       : PUT normalised score at 9:15 AM today (for intraday trajectory)
      open_call_norm      : CALL normalised score at 9:15 AM today
    """

    def signals(
        self,
        df_daily:  pd.DataFrame,
        df_1h:     pd.DataFrame,
        df_30m:    pd.DataFrame,
        df_15m:    pd.DataFrame,
        df_5m:     pd.DataFrame,
        spot:      float,
        prev_put_norm_eod:  Optional[float] = None,
        prev_call_norm_eod: Optional[float] = None,
        open_put_norm:      Optional[float] = None,
        open_call_norm:     Optional[float] = None,
    ) -> dict:

        out = {}

        if spot <= 0:
            return self._empty_signals()

        # ── Proxy resampling ──────────────────────────────────────────────
        df_2h = resample_ohlcv(df_1h, "2h")
        df_4h = resample_ohlcv(df_1h, "4h")

        # ── Compute ST for each TF ────────────────────────────────────────
        st_dfs = {}
        for tf_name, df in [
            ("daily", df_daily),
            ("4h",    df_4h),
            ("2h",    df_2h),
            ("1h",    df_1h),
            ("30m",   df_30m),
            ("15m",   df_15m),
            ("5m",    df_5m),    # display only
        ]:
            try:
                st_dfs[tf_name] = compute_supertrend(df)
            except Exception as e:
                log.error("ST compute %s: %s", tf_name, e)
                st_dfs[tf_name] = pd.DataFrame()

        # ── Extract per-TF signals ────────────────────────────────────────
        tf_signals = {}
        for tf_name in [*TF_ORDER, "5m"]:
            tf_signals[tf_name] = extract_tf_signal(st_dfs.get(tf_name, pd.DataFrame()), spot, tf_name)

        out["tf_signals"] = tf_signals

        # ── Identify flipped TFs (for trajectory and display) ─────────────
        flip_tfs = [tf for tf in TF_ORDER if tf_signals[tf].get("flip")]
        out["flip_tfs"] = flip_tfs

        # ── Build moat stacks ─────────────────────────────────────────────
        put_stack  = build_moat_stack(tf_signals, "PUT")
        call_stack = build_moat_stack(tf_signals, "CALL")
        out["put_stack"]  = put_stack
        out["call_stack"] = call_stack

        # ── Safe distances ────────────────────────────────────────────────
        put_dist  = compute_safe_distance(tf_signals, "PUT",  spot)
        call_dist = compute_safe_distance(tf_signals, "CALL", spot)
        out["put_dist"]  = put_dist
        out["call_dist"] = call_dist

        # ── Structural trajectory (Tier 1: daily/4h/2h) ───────────────────
        tier1_tfs   = ["daily", "4h", "2h"]
        tier1_flips = [tf for tf in flip_tfs if tf in tier1_tfs]
        tier1_put_walls  = [tf_signals[tf] for tf in tier1_tfs if tf_signals[tf]["side"] == "PUT"]
        tier1_call_walls = [tf_signals[tf] for tf in tier1_tfs if tf_signals[tf]["side"] == "CALL"]
        tier1_put_raw    = sum(w["raw_score"] for w in tier1_put_walls)
        tier1_call_raw   = sum(w["raw_score"] for w in tier1_call_walls)
        t1_put_norm      = round((tier1_put_raw  / MAX_RAW) * 100, 1)
        t1_call_norm     = round((tier1_call_raw / MAX_RAW) * 100, 1)

        out["structural_trajectory"] = compute_trajectory(
            t1_put_norm, t1_call_norm,
            prev_put_norm_eod, prev_call_norm_eod,
            "structural", tier1_flips,
        )

        # ── Intraday trajectory (Tier 3: 1h/30m/15m) ──────────────────────
        tier3_tfs   = ["1h", "30m", "15m"]
        tier3_flips = [tf for tf in flip_tfs if tf in tier3_tfs]
        tier3_put_walls  = [tf_signals[tf] for tf in tier3_tfs if tf_signals[tf]["side"] == "PUT"]
        tier3_call_walls = [tf_signals[tf] for tf in tier3_tfs if tf_signals[tf]["side"] == "CALL"]
        tier3_put_raw    = sum(w["raw_score"] for w in tier3_put_walls)
        tier3_call_raw   = sum(w["raw_score"] for w in tier3_call_walls)
        t3_put_norm      = round((tier3_put_raw  / MAX_RAW) * 100, 1)
        t3_call_norm     = round((tier3_call_raw / MAX_RAW) * 100, 1)

        out["intraday_trajectory"] = compute_trajectory(
            t3_put_norm, t3_call_norm,
            open_put_norm, open_call_norm,
            "intraday", tier3_flips,
        )

        # ── IC Shape ──────────────────────────────────────────────────────
        ic_shape = compute_ic_shape(
            put_stack["normalised"], call_stack["normalised"],
            put_stack["band"],       call_stack["band"],
        )
        out["ic_shape"] = ic_shape

        # ── Home score ────────────────────────────────────────────────────
        home_score = compute_home_score(
            put_stack["normalised"], call_stack["normalised"]
        )
        out["home_score"] = home_score

        # ── Lens row values ───────────────────────────────────────────────
        out["lens_pe_dist"]   = put_dist["dist_pts"]
        out["lens_pe_pct"]    = put_dist["dist_pct"]
        out["lens_pe_strike"] = put_dist["strike"]
        out["lens_ce_dist"]   = call_dist["dist_pts"]
        out["lens_ce_pct"]    = call_dist["dist_pct"]
        out["lens_ce_strike"] = call_dist["strike"]

        # ── 5m display signal (no decision weight) ────────────────────────
        out["tf_5m_display"] = tf_signals.get("5m", {})

        return out

    def _empty_signals(self) -> dict:
        return {
            "tf_signals": {}, "flip_tfs": [],
            "put_stack":  {"side":"PUT",  "walls":[], "wall_count":0, "raw_score":0, "normalised":0, "band":"BREACHED", "clusters":[]},
            "call_stack": {"side":"CALL", "walls":[], "wall_count":0, "raw_score":0, "normalised":0, "band":"BREACHED", "clusters":[]},
            "put_dist":   {"dist_pts":0,"dist_pct":0.0,"strike":0,"case":"NO_WALL","wall_tf":None,"wall_pct":None,"label":"No data","all_tier1_walls":[]},
            "call_dist":  {"dist_pts":0,"dist_pct":0.0,"strike":0,"case":"NO_WALL","wall_tf":None,"wall_pct":None,"label":"No data","all_tier1_walls":[]},
            "structural_trajectory": {"put_label":"UNKNOWN","call_label":"UNKNOWN","flip_event":False,"flip_tfs":[],"kind":"structural","put_delta":None,"call_delta":None},
            "intraday_trajectory":   {"put_label":"UNKNOWN","call_label":"UNKNOWN","flip_event":False,"flip_tfs":[],"kind":"intraday","put_delta":None,"call_delta":None},
            "ic_shape": "SYMMETRIC",
            "home_score": 0,
            "lens_pe_dist": 0, "lens_pe_pct": 0.0, "lens_pe_strike": 0,
            "lens_ce_dist": 0, "lens_ce_pct": 0.0, "lens_ce_strike": 0,
            "tf_5m_display": {},
        }
