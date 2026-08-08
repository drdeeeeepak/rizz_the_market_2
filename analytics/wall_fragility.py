# analytics/wall_fragility.py — Wall Fragility engine (Page 33)
#
# Answers ONE question: if price tests this OI wall today, does it break violently
# or hold? Fragility is a CONDITIONAL read — it never predicts that a wall will be
# tested, only what happens if it is.
#
# Components (see docs / CLAUDE.md build notes):
#   F1  Air pocket   — wall OI vs the strikes BEHIND it in the break direction.
#                      A tall lone wall with thin strikes behind it has nothing to
#                      absorb the covering flow, so the break cascades.
#   F2  Vintage      — how much of this wall was built TODAY. Fresh writers carry no
#                      decay cushion and cover early. Uses Kite's oi_day_change.
#   F3  LVN          — wall sits where volume profile says price does not trade.
#                      Two independent sources agreeing = fastest break.
#   F4  Test decay   — requires intraday level tracking       (STAGE 2, not built)
#   F5  Coiling      — requires intraday range tracking       (STAGE 2, not built)
#   F6  OI unwind    — requires intraday OI history           (STAGE 2, not built)
#
# The composite score is DELIBERATELY unweighted (plain mean of available
# components) and must be rendered as UNVALIDATED until break rates are measured
# with a real sample. We do not have hit rates yet, and a confident-looking number
# without them is exactly the failure mode this project is trying to avoid.

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from analytics.base_strategy import BaseStrategy

log = logging.getLogger(__name__)

# ── Tunables — every one of these is an UNVALIDATED placeholder ───────────────
BUCKET_STEP      = 100     # display/aggregation step (user spec: rounded to hundred)
WINDOW_BUCKETS   = 3       # how many buckets above AND below ATM to display
AIR_LOOKAHEAD    = 3       # strikes behind the wall used for the air-pocket mean
AIR_RATIO_FLOOR  = 1.0     # ratio at/below this scores 0
AIR_RATIO_CAP    = 3.0     # ratio at/above this scores 100
VINTAGE_FULL_PCT = 50.0    # this % of wall built today scores 100
VOL_BUCKET       = 25      # price bucket for the volume histogram (LVN detection)
LVN_PCT_OF_POC   = 0.30    # bucket volume <= this fraction of POC volume = LVN

# Fragility bands — placeholders, to be set by measured break rates, not by us.
BAND_FORTRESS = 30
BAND_NORMAL   = 60
BAND_BRITTLE  = 80


# ── Bucketing ─────────────────────────────────────────────────────────────────

def bucket_chain(chain: pd.DataFrame, step: int = BUCKET_STEP) -> pd.DataFrame:
    """
    Collapse a 50-point strike chain into `step`-point buckets, summing OI.

    Each 50-strike is assigned to its NEAREST bucket (deterministic half-up), so
    no OI is dropped and none is double counted. This is rule W3 — a wall is a
    ZONE across adjacent strikes, never a single strike. It is also what makes an
    overnight max-OI flip between two near-tied strikes a non-event: both sit in
    the same bucket.
    """
    if chain is None or chain.empty:
        return pd.DataFrame()

    d = chain.copy()
    d["bucket"] = ((d.index.to_numpy() + step / 2) // step).astype(int) * step

    cols = [c for c in ("ce_oi", "pe_oi", "ce_oi_change", "pe_oi_change",
                        "ce_vol", "pe_vol") if c in d.columns]
    out = d.groupby("bucket")[cols].sum()
    return out.sort_index()


# ── F3 support: volume histogram / LVN ────────────────────────────────────────

def volume_histogram(fut: pd.DataFrame, bucket: int = VOL_BUCKET) -> pd.Series:
    """
    Volume distributed across price buckets, index = bucket low edge.

    Kept separate from market_profile._value_area on purpose: that one runs at a
    50-point bucket for the weekly condor value area (page 12), while LVN
    detection needs finer granularity. Same maths, different resolution — do not
    "unify" them without re-checking page 12 still renders.

    NOTE: must be fed NIFTY FUTURES. The index reports volume = 0 on Kite, so an
    index-based profile is silently meaningless.
    """
    if fut is None or fut.empty:
        return pd.Series(dtype=float)

    need = {"high", "low", "volume"}
    if not need.issubset(fut.columns):
        return pd.Series(dtype=float)

    lo_all = float(fut["low"].min())
    hi_all = float(fut["high"].max())
    if not np.isfinite(lo_all) or not np.isfinite(hi_all) or lo_all >= hi_all:
        return pd.Series(dtype=float)

    edges = np.arange(int(lo_all // bucket) * bucket,
                      int(hi_all // bucket) * bucket + bucket * 2, bucket)
    hist = np.zeros(len(edges))

    for _, row in fut.iterrows():
        vol = float(row.get("volume", 0) or 0)
        if vol <= 0:
            continue
        lo, hi = float(row["low"]), float(row["high"])
        span = hi - lo
        if span <= 0:                       # flat candle — dump it in one bucket
            idx = int((lo - edges[0]) // bucket)
            if 0 <= idx < len(hist):
                hist[idx] += vol
            continue
        overlap = np.minimum(edges + bucket, hi) - np.maximum(edges, lo)
        share = np.clip(overlap, 0, None) / span
        hist += vol * share

    return pd.Series(hist, index=edges, name="volume")


def lvn_edges(hist: pd.Series, pct_of_poc: float = LVN_PCT_OF_POC) -> set[int]:
    """Bucket low-edges whose volume is <= pct_of_poc of the POC bucket."""
    if hist is None or hist.empty:
        return set()
    poc_vol = float(hist.max())
    if poc_vol <= 0:
        return set()
    thin = hist[hist <= poc_vol * pct_of_poc]
    return {int(e) for e in thin.index}


def _at_lvn(level: int, lvn: set[int], step: int = BUCKET_STEP,
            vol_bucket: int = VOL_BUCKET) -> bool:
    """True when any volume bucket inside this price bucket is an LVN."""
    if not lvn:
        return False
    lo = level - step // 2
    hi = level + step // 2
    return any(e in lvn for e in range(int(lo // vol_bucket) * vol_bucket,
                                       hi + vol_bucket, vol_bucket))


# ── F1 air pocket ─────────────────────────────────────────────────────────────

def air_pocket(buckets: pd.DataFrame, level: int, side: str,
               step: int = BUCKET_STEP, lookahead: int = AIR_LOOKAHEAD) -> float:
    """
    wall OI / mean(OI of the next `lookahead` buckets BEHIND it).

    "Behind" = the direction price travels once the wall breaks: up for a call
    wall, down for a put wall. High ratio = tall lone wall, nothing to absorb the
    covering flow. Returns nan when there are not enough buckets to judge.
    """
    col = "ce_oi" if side == "CE" else "pe_oi"
    if buckets.empty or col not in buckets.columns or level not in buckets.index:
        return float("nan")

    wall = float(buckets.at[level, col])
    if wall <= 0:
        return float("nan")

    sign = 1 if side == "CE" else -1
    behind = [level + sign * step * i for i in range(1, lookahead + 1)]
    vals = [float(buckets.at[b, col]) for b in behind if b in buckets.index]
    if not vals:
        return float("nan")

    mean_behind = float(np.mean(vals))
    if mean_behind <= 0:
        return float("inf")            # genuinely empty behind it
    return wall / mean_behind


# ── Component scoring ─────────────────────────────────────────────────────────

def _score_air(ratio: float) -> float:
    if not np.isfinite(ratio):
        return float("nan") if np.isnan(ratio) else 100.0
    return float(np.clip((ratio - AIR_RATIO_FLOOR) /
                         (AIR_RATIO_CAP - AIR_RATIO_FLOOR) * 100, 0, 100))


def _score_vintage(fresh_pct: float) -> float:
    if not np.isfinite(fresh_pct):
        return float("nan")
    return float(np.clip(fresh_pct / VINTAGE_FULL_PCT * 100, 0, 100))


def band(score: float) -> tuple[str, str]:
    """(label, hex) for a composite score. Bands are placeholders."""
    if not np.isfinite(score):
        return "—", "#64748b"
    if score <= BAND_FORTRESS:
        return "FORTRESS", "#10b981"
    if score <= BAND_NORMAL:
        return "NORMAL", "#f59e0b"
    if score <= BAND_BRITTLE:
        return "BRITTLE", "#f97316"
    return "PAPER", "#dc2626"


# ── Board ─────────────────────────────────────────────────────────────────────

def wall_board(chain: pd.DataFrame, spot: float, fut: pd.DataFrame | None = None,
               step: int = BUCKET_STEP, window: int = WINDOW_BUCKETS) -> pd.DataFrame:
    """
    The Page 33 table: `window` buckets above and below ATM, at `step` points.

    Components are computed against the FULL bucketed chain (so the outermost row
    can still see the strikes behind it), then the display window is sliced out.

    Returns an EMPTY frame when the chain is unusable — never a frame of zeros.
    A zero-filled board looks exactly like a real reading of "no walls anywhere".
    """
    buckets = bucket_chain(chain, step)
    if buckets.empty or not spot or spot <= 0:
        return pd.DataFrame()

    atm = int((spot + step / 2) // step) * step
    lvn = lvn_edges(volume_histogram(fut)) if fut is not None else set()

    rows = []
    for i in range(window, -window - 1, -1):          # highest strike first
        level = atm + i * step
        if level not in buckets.index:
            continue

        if level > atm:
            side = "CE"
        elif level < atm:
            side = "PE"
        else:
            side = "BOTH"

        # At ATM take whichever side carries the bigger book — that is the one
        # with something to defend.
        eff = side
        if side == "BOTH":
            eff = "CE" if float(buckets.at[level, "ce_oi"]) >= \
                          float(buckets.at[level, "pe_oi"]) else "PE"

        oi_col  = f"{eff.lower()}_oi"
        chg_col = f"{eff.lower()}_oi_change"
        wall_oi = float(buckets.at[level, oi_col]) if oi_col in buckets.columns else 0.0
        chg     = float(buckets.at[level, chg_col]) if chg_col in buckets.columns else 0.0

        ratio   = air_pocket(buckets, level, eff, step)
        fresh   = (chg / wall_oi * 100) if wall_oi > 0 else float("nan")
        at_lvn  = _at_lvn(level, lvn, step)

        s_air   = _score_air(ratio)
        s_vin   = _score_vintage(fresh)
        s_lvn   = 100.0 if at_lvn else 0.0

        parts = [s for s in (s_air, s_vin, s_lvn) if np.isfinite(s)]
        composite = float(np.mean(parts)) if parts else float("nan")
        lbl, _col = band(composite)

        rows.append({
            "level":      level,
            "side":       side,
            "wall_oi":    wall_oi,
            "oi_change":  chg,
            "air_ratio":  ratio,
            "fresh_pct":  fresh,
            "at_lvn":     at_lvn,
            "s_air":      s_air,
            "s_vintage":  s_vin,
            "s_lvn":      s_lvn,
            "fragility":  composite,
            "band":       lbl,
            "is_atm":     level == atm,
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("level")


# ── Engine wrapper ────────────────────────────────────────────────────────────

class WallFragilityEngine(BaseStrategy):
    """BaseStrategy contract so this can join compute_signals / the home score."""

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """No indicator columns — fragility is chain-derived, not price-derived."""
        return df

    def signals(self, chain: pd.DataFrame, spot: float = 0.0,
                fut: pd.DataFrame | None = None) -> dict:
        board = wall_board(chain, spot, fut)
        if board.empty:
            return self._empty()

        above = board[board["side"] == "CE"]
        below = board[board["side"] == "PE"]

        def _weakest(sub: pd.DataFrame) -> tuple:
            if sub.empty or not sub["fragility"].notna().any():
                return 0, float("nan"), "—"
            r = sub.loc[sub["fragility"].idxmax()]
            return int(r.name), float(r["fragility"]), str(r["band"])

        up_lvl, up_score, up_band = _weakest(above)
        dn_lvl, dn_score, dn_band = _weakest(below)

        return {
            "board":            board,
            "atm":              int(board[board["is_atm"]].index[0]) if board["is_atm"].any() else 0,
            "weakest_above":    up_lvl,
            "weakest_above_sc": up_score,
            "weakest_above_bd": up_band,
            "weakest_below":    dn_lvl,
            "weakest_below_sc": dn_score,
            "weakest_below_bd": dn_band,
            "validated":        False,     # no measured break rates yet — always False
            "sample_n":         0,
            "kill_switches":    {},
            "home_score":       0,         # contributes nothing until validated
        }

    @staticmethod
    def _empty() -> dict:
        return {
            "board": pd.DataFrame(), "atm": 0,
            "weakest_above": 0, "weakest_above_sc": float("nan"), "weakest_above_bd": "—",
            "weakest_below": 0, "weakest_below_sc": float("nan"), "weakest_below_bd": "—",
            "validated": False, "sample_n": 0,
            "kill_switches": {}, "home_score": 0,
        }
