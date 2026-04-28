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

# Safe distance cumulative threshold (normalised 0-100)
SAFE_DIST_THRESHOLD  = 50.0

# Minimum floor % CMP when threshold never reached
MIN_FLOOR_PCT        = 2.0

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
        "tf":         tf_name,
        "direction":  "BULL" if direction == 1 else "BEAR",
        "side":       side,          # which IC leg this protects
        "st_price":   st_price,
        "dist_pts":   round(dist_pts),
        "dist_pct":   round(dist_pct, 2),
        "depth":      depth,
        "mult":       mult,
        "weight":     weight,
        "raw_score":  round(raw_score, 1),
        "flip":       flip,
        "above":      above,         # True = line above spot
    }


def _empty_tf_signal(tf_name: str) -> dict:
    return {
        "tf": tf_name, "direction": "UNKNOWN", "side": "NONE",
        "st_price": 0.0, "dist_pts": 0, "dist_pct": 0.0,
        "depth": "UNKNOWN", "mult": 0.0, "weight": TF_WEIGHTS.get(tf_name, 0),
        "raw_score": 0.0, "flip": False, "above": False,
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

def compute_safe_distance(moat_stack: dict, spot: float) -> dict:
    """
    Compute ST safe distance for one leg.
    Builds cumulative score from deepest wall inward.
    Returns distance at first wall where cumulative >= SAFE_DIST_THRESHOLD.
    Falls back to MIN_FLOOR_PCT if threshold never reached.
    """
    walls = moat_stack["walls"]

    if not walls:
        # No walls at all — minimum floor
        dist_pct  = MIN_FLOOR_PCT
        dist_pts  = int(round(spot * dist_pct / 100 / 50) * 50)
        strike    = int(round((spot - dist_pts) / 50) * 50) if moat_stack["side"] == "PUT" \
                    else int(round((spot + dist_pts) / 50) * 50)
        return {
            "dist_pts":     dist_pts,
            "dist_pct":     round(dist_pct, 2),
            "strike":       strike,
            "floor_applied": True,
            "threshold_wall": None,
        }

    cumulative   = 0.0
    anchor_wall  = None

    for wall in walls:
        cumulative += wall["raw_score"]
        norm_cum    = (cumulative / MAX_RAW) * 100
        if norm_cum >= SAFE_DIST_THRESHOLD:
            anchor_wall = wall
            break

    floor_applied = False
    if anchor_wall is None:
        # Threshold never reached — use minimum floor
        dist_pct  = MIN_FLOOR_PCT
        floor_applied = True
    else:
        dist_pct = anchor_wall["dist_pct"]

    dist_pct = max(dist_pct, MIN_FLOOR_PCT)   # hard floor always applies
    dist_pts = int(round(spot * dist_pct / 100 / 50) * 50)

    if moat_stack["side"] == "PUT":
        strike = int(round((spot - dist_pts) / 50) * 50)
    else:
        strike = int(round((spot + dist_pts) / 50) * 50)

    return {
        "dist_pts":      dist_pts,
        "dist_pct":      round(dist_pct, 2),
        "strike":        strike,
        "floor_applied": floor_applied,
        "threshold_wall": anchor_wall["tf"] if anchor_wall else None,
    }


# ─── Strike Validation ───────────────────────────────────────────────────────

def validate_strike(moat_stack: dict, strike: float, spot: float) -> dict:
    """
    Audit how many ST walls stand between spot and the given strike.
    Returns protection score and verdict for the ⭐ MAX strike.
    """
    side   = moat_stack["side"]
    walls  = moat_stack["walls"]

    # Walls that are between spot and strike (protecting the strike)
    protecting = []
    passed     = []

    for wall in walls:
        wp = wall["st_price"]
        if side == "PUT":
            # PUT: strike below spot. Wall protects if wall is above strike (between spot and strike)
            if wp > strike:
                protecting.append(wall)
            else:
                passed.append(wall)
        else:
            # CALL: strike above spot. Wall protects if wall is below strike
            if wp < strike:
                protecting.append(wall)
            else:
                passed.append(wall)

    prot_raw  = sum(w["raw_score"] for w in protecting)
    prot_norm = round((prot_raw / MAX_RAW) * 100, 1)

    # Overly conservative: all walls protecting AND score is FORTRESS
    all_protecting = len(passed) == 0 and len(protecting) == len(walls) and len(walls) > 0

    if   prot_norm >= 75: verdict = "FORTRESS PROTECTED"
    elif prot_norm >= 55: verdict = "WELL PROTECTED"
    elif prot_norm >= 35: verdict = "ADEQUATELY PROTECTED"
    elif prot_norm >= 20: verdict = "THINLY PROTECTED"
    elif prot_norm >= 5:  verdict = "EXPOSED"
    else:                 verdict = "STRUCTURALLY EXPOSED"

    return {
        "protecting_tfs":   [w["tf"] for w in protecting],
        "passed_tfs":       [w["tf"] for w in passed],
        "prot_raw":         round(prot_raw, 1),
        "prot_norm":        prot_norm,
        "verdict":          verdict,
        "all_protecting":   all_protecting,
        "wall_count":       len(walls),
        "protecting_count": len(protecting),
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
      star_pe_strike      : current ⭐ MAX PE strike (for validation)
      star_ce_strike      : current ⭐ MAX CE strike (for validation)
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
        star_pe_strike:     Optional[float] = None,
        star_ce_strike:     Optional[float] = None,
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
        put_dist  = compute_safe_distance(put_stack,  spot)
        call_dist = compute_safe_distance(call_stack, spot)
        out["put_dist"]  = put_dist
        out["call_dist"] = call_dist

        # ── Strike validation (for ⭐ MAX strikes) ────────────────────────
        if star_pe_strike and star_pe_strike > 0:
            out["put_validation"]  = validate_strike(put_stack,  star_pe_strike, spot)
        else:
            out["put_validation"]  = None

        if star_ce_strike and star_ce_strike > 0:
            out["call_validation"] = validate_strike(call_stack, star_ce_strike, spot)
        else:
            out["call_validation"] = None

        # ── Structural trajectory (Tier 1: daily/4h/2h) ───────────────────
        tier1_tfs   = ["daily", "4h", "2h"]
        tier1_flips = [tf for tf in flip_tfs if tf in tier1_tfs]
        # Compute Tier1-only scores
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
            "put_dist":   {"dist_pts":0, "dist_pct":0, "strike":0, "floor_applied":True, "threshold_wall":None},
            "call_dist":  {"dist_pts":0, "dist_pct":0, "strike":0, "floor_applied":True, "threshold_wall":None},
            "put_validation": None, "call_validation": None,
            "structural_trajectory": {"put_label":"UNKNOWN","call_label":"UNKNOWN","flip_event":False,"flip_tfs":[],"kind":"structural","put_delta":None,"call_delta":None},
            "intraday_trajectory":   {"put_label":"UNKNOWN","call_label":"UNKNOWN","flip_event":False,"flip_tfs":[],"kind":"intraday","put_delta":None,"call_delta":None},
            "ic_shape": "SYMMETRIC",
            "home_score": 0,
            "lens_pe_dist": 0, "lens_pe_pct": 0.0, "lens_pe_strike": 0,
            "lens_ce_dist": 0, "lens_ce_pct": 0.0, "lens_ce_strike": 0,
            "tf_5m_display": {},
        }
