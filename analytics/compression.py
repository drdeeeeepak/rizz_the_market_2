# analytics/compression.py — Compression / Vega Regime engine (Page 34)
#
# Purpose: a VEGA filter for a short-volatility book, not a directional signal.
#
# The one idea here with real support behind it is that volatility CONTRACTION
# precedes EXPANSION. For a 13→7 DTE short strangle that matters twice over:
#
#   Compression  →  low realised vol  →  IV usually low too  →  THIN PREMIUM
#   Compression  →  expansion due                            →  MAXIMUM RISK
#
# Minimum compensation at maximum risk is the worst pairing available to a
# seller, and a fixed-percentage strike formula cannot see it. That pairing —
# state x IV percentile — is what this engine exists to surface.
#
# States (rule set C):
#   COMPRESSION   VA width in the bottom pctile band AND contracting >= 2 sessions.
#                 Resolves in 1-3 sessions; if it has not by session 4 the read
#                 was wrong and the state is cleared (rule C3).
#   ACCUMULATION  Range-bound, width NOT contracting, several HVN clusters.
#                 Breakouts here hunt stops across multiple nodes.
#   TREND         Neither, with POC migrating consistently.
#
# EVERY threshold below is an UNVALIDATED placeholder chosen to make the rules
# computable. None is derived from measured outcomes. Page 34 must say so.

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from analytics.base_strategy import BaseStrategy
# Reuse the histogram from the wall engine rather than writing a third volume
# bucketer. market_profile._value_area is a FOURTH one at 50-pt buckets for the
# weekly condor VA on page 12 — deliberately left alone; do not "unify" these
# without re-checking page 12 still renders.
from analytics.wall_fragility import volume_histogram

log = logging.getLogger(__name__)

# ── Tunables — all UNVALIDATED placeholders ──────────────────────────────────
VA_PCT             = 0.70   # value area share
VOL_BUCKET         = 25     # price bucket for the session histogram
LOOKBACK_SESSIONS  = 20     # window for the width percentile
COMPRESS_PCTILE    = 20.0   # width at/below this percentile = compressed
CONTRACT_SESSIONS  = 2      # consecutive narrowing sessions required
ACCUM_ATR_MULT     = 1.2    # session range <= this x ATR14 = range-bound
ACCUM_MIN_HVN      = 3      # distinct HVN clusters for accumulation
HVN_PCT_OF_POC     = 0.70   # bucket >= this share of POC volume = HVN
TREND_POC_PCT      = 0.40   # POC migration % over 2 sessions to call TREND
COMPRESS_MAX_DAYS  = 3      # rule C3 — stale after this many sessions
IVP_LOW            = 30.0   # IV percentile at/below this = thin premium
IVP_HIGH           = 70.0   # IV percentile at/above this = richly paid

STATE_COLORS = {
    "COMPRESSION":  "#f59e0b",
    "ACCUMULATION": "#64748b",
    "TREND":        "#0ea5e9",
    "NEUTRAL":      "#334155",   # failed every test — NOT accumulation
    "UNKNOWN":      "#475569",   # not enough history, or a stale compression
}


# ── Value area from a volume histogram ───────────────────────────────────────

def value_area_from_hist(hist: pd.Series, va_pct: float = VA_PCT) -> dict:
    """
    POC / VAH / VAL / width, expanding outward from POC until va_pct of volume
    is enclosed. Returns zeros when the histogram is unusable.
    """
    empty = {"poc": 0.0, "vah": 0.0, "val": 0.0, "width": 0.0, "hvn_count": 0}
    if hist is None or hist.empty:
        return empty

    vals = hist.to_numpy(dtype=float)
    edges = hist.index.to_numpy()
    total = float(vals.sum())
    if total <= 0:
        return empty

    step = int(edges[1] - edges[0]) if len(edges) > 1 else VOL_BUCKET
    poc_i = int(np.argmax(vals))
    acc = vals[poc_i]
    lo = hi = poc_i
    while acc < va_pct * total:
        up = vals[hi + 1] if hi + 1 < len(vals) else -1.0
        dn = vals[lo - 1] if lo - 1 >= 0 else -1.0
        if up < 0 and dn < 0:
            break
        if up >= dn:
            hi += 1
            acc += vals[hi]
        else:
            lo -= 1
            acc += vals[lo]

    poc_vol = float(vals[poc_i])
    hvn = int((vals >= poc_vol * HVN_PCT_OF_POC).sum()) if poc_vol > 0 else 0

    val = float(edges[lo])
    vah = float(edges[hi] + step)
    return {"poc": float(edges[poc_i]), "vah": vah, "val": val,
            "width": vah - val, "hvn_count": hvn}


# ── Per-session profiles ─────────────────────────────────────────────────────

def session_profiles(fut: pd.DataFrame, bucket: int = VOL_BUCKET) -> pd.DataFrame:
    """
    One volume-profile row per trading session, oldest first.

    MUST be fed NIFTY FUTURES — the index reports volume = 0 on Kite, which would
    silently produce a flat histogram and a meaningless value area.

    Sessions are never spanned across a futures roll because each session is
    profiled independently; no composite crosses a contract boundary.
    """
    if fut is None or fut.empty:
        return pd.DataFrame()
    if not {"high", "low", "volume"}.issubset(fut.columns):
        return pd.DataFrame()

    rows = []
    for day, grp in fut.groupby(fut.index.normalize()):
        if grp.empty:
            continue
        va = value_area_from_hist(volume_histogram(grp, bucket))
        if va["width"] <= 0:
            continue
        rows.append({
            "session":   pd.Timestamp(day).date(),
            "poc":       va["poc"],
            "vah":       va["vah"],
            "val":       va["val"],
            "width":     va["width"],
            "hvn_count": va["hvn_count"],
            "range_pts": float(grp["high"].max() - grp["low"].min()),
            "volume":    float(grp["volume"].sum()),
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("session").sort_index()


# ── State classification ─────────────────────────────────────────────────────

def classify_states(prof: pd.DataFrame, atr14: float,
                    lookback: int = LOOKBACK_SESSIONS) -> pd.DataFrame:
    """
    Adds width_pctile / contracting / state / days_in_state to a profile frame.

    days_in_state counts consecutive sessions in the SAME state, and is what
    rule C3 uses: a COMPRESSION older than COMPRESS_MAX_DAYS is stale and gets
    demoted to UNKNOWN rather than left standing as a live read.
    """
    if prof is None or prof.empty:
        return pd.DataFrame()

    d = prof.copy()
    # Percentile of each session's width within the trailing window, using the
    # MIDRANK convention (strictly-below + half the ties). A plain `<=` count
    # returns the UPPER edge of a tie group, so when several sessions share the
    # same width the narrowest one scores mid-pack instead of near-zero and
    # COMPRESSION becomes undetectable. Widths tie readily because they are
    # quantised to the histogram bucket.
    def _midrank_pctile(w: pd.Series) -> float:
        cur = w.iloc[-1]
        below = float((w < cur).sum())
        ties = float((w == cur).sum())
        return (below + 0.5 * ties) / len(w) * 100.0

    d["width_pctile"] = (
        d["width"].rolling(lookback, min_periods=3).apply(_midrank_pctile, raw=False)
    )
    # Contracting = width strictly lower than the prior session, N sessions running.
    narrower = d["width"].diff() < 0
    d["contracting"] = narrower.rolling(CONTRACT_SESSIONS).sum() >= CONTRACT_SESSIONS

    poc_chg = d["poc"].pct_change(2).abs() * 100.0
    atr = float(atr14) if atr14 and np.isfinite(atr14) and atr14 > 0 else np.nan

    states = []
    for i in range(len(d)):
        r = d.iloc[i]
        pct = r["width_pctile"]
        if not np.isfinite(pct):
            states.append("UNKNOWN")
            continue

        if pct <= COMPRESS_PCTILE and bool(r["contracting"]):
            states.append("COMPRESSION")
            continue

        rangey = np.isfinite(atr) and r["range_pts"] <= ACCUM_ATR_MULT * atr
        if rangey and not bool(r["contracting"]) and r["hvn_count"] >= ACCUM_MIN_HVN:
            states.append("ACCUMULATION")
            continue

        # Fallback is NEUTRAL, never ACCUMULATION. ACCUMULATION carries a specific
        # trading meaning (stop-hunt risk, do not take the first breakout), so a
        # session that merely failed every other test must not inherit it.
        pc = poc_chg.iloc[i]
        states.append("TREND" if np.isfinite(pc) and pc >= TREND_POC_PCT else "NEUTRAL")

    d["state"] = states

    # Consecutive run length of the current state.
    runs, n = [], 0
    prev = None
    for s in d["state"]:
        n = n + 1 if s == prev else 1
        runs.append(n)
        prev = s
    d["days_in_state"] = runs

    # Rule C3 — a compression that has not resolved is a failed read, not a signal.
    stale = (d["state"] == "COMPRESSION") & (d["days_in_state"] > COMPRESS_MAX_DAYS)
    d.loc[stale, "state"] = "UNKNOWN"
    return d


# ── C2 — the state x IV quadrant ─────────────────────────────────────────────

def vega_read(state: str, ivp: float) -> dict:
    """
    The pairing that matters to a short-vol seller: is expansion due, and are we
    being paid for it? Returns label / detail / level for the UI.
    """
    if not np.isfinite(ivp):
        return {"label": "IV UNKNOWN", "detail": "No IV percentile available.",
                "level": "info", "quadrant": "—"}

    thin = ivp <= IVP_LOW
    rich = ivp >= IVP_HIGH

    if state == "COMPRESSION" and thin:
        return {"label": "WORST PAIRING",
                "detail": ("Expansion is due and premium is thin. Minimum compensation "
                           "at maximum risk — the configuration a fixed-% strike "
                           "formula cannot see."),
                "level": "danger", "quadrant": "COMPRESSION x LOW IV"}
    if state == "COMPRESSION":
        return {"label": "EXPANSION DUE — PAID",
                "detail": ("Expansion is due, but premium is not thin. Risk is real "
                           "and at least compensated."),
                "level": "warning", "quadrant": f"COMPRESSION x {'HIGH' if rich else 'MID'} IV"}
    if state == "ACCUMULATION" and rich:
        return {"label": "BEST PAIRING",
                "detail": "Range-bound with rich premium — the condition short vol earns in.",
                "level": "success", "quadrant": "ACCUMULATION x HIGH IV"}
    if state == "ACCUMULATION" and thin:
        return {"label": "THIN BUT CALM",
                "detail": "Range-bound but poorly paid. Selling cheap vol for little.",
                "level": "warning", "quadrant": "ACCUMULATION x LOW IV"}
    if state == "TREND":
        return {"label": "DIRECTIONAL",
                "detail": "POC migrating. Drift, not expansion, is the live risk.",
                "level": "warning", "quadrant": f"TREND x {'HIGH' if rich else 'LOW' if thin else 'MID'} IV"}
    iv_band = "HIGH" if rich else "LOW" if thin else "MID"
    return {"label": "NO STANDOUT PAIRING",
            "detail": ("Structure did not meet the compression, accumulation or trend "
                       "tests. No vega read is being claimed."),
            "level": "info", "quadrant": f"{state} x {iv_band} IV"}


# ── Engine wrapper ───────────────────────────────────────────────────────────

class CompressionEngine(BaseStrategy):
    """BaseStrategy contract so this can join compute_signals / the home score."""

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def signals(self, fut: pd.DataFrame, atr14: float = 0.0,
                ivp: float = float("nan")) -> dict:
        prof = session_profiles(fut)
        if prof.empty:
            return self._empty()

        d = classify_states(prof, atr14)
        if d.empty:
            return self._empty()

        cur = d.iloc[-1]
        state = str(cur["state"])
        read = vega_read(state, ivp)

        return {
            "sessions":     d,
            "state":        state,
            "state_color":  STATE_COLORS.get(state, STATE_COLORS["UNKNOWN"]),
            "va_width":     float(cur["width"]),
            "width_pctile": float(cur["width_pctile"]) if np.isfinite(cur["width_pctile"]) else float("nan"),
            "contracting":  bool(cur["contracting"]),
            "days_in_state": int(cur["days_in_state"]),
            "poc":          float(cur["poc"]),
            "vah":          float(cur["vah"]),
            "val":          float(cur["val"]),
            "hvn_count":    int(cur["hvn_count"]),
            "ivp":          float(ivp) if np.isfinite(ivp) else float("nan"),
            "vega_label":   read["label"],
            "vega_detail":  read["detail"],
            "vega_level":   read["level"],
            "quadrant":     read["quadrant"],
            "validated":    False,      # no measured outcomes yet
            "sample_n":     0,
            "kill_switches": {},
            "home_score":   0,          # contributes nothing until validated
        }

    @staticmethod
    def _empty() -> dict:
        return {
            "sessions": pd.DataFrame(), "state": "UNKNOWN",
            "state_color": STATE_COLORS["UNKNOWN"], "va_width": 0.0,
            "width_pctile": float("nan"), "contracting": False, "days_in_state": 0,
            "poc": 0.0, "vah": 0.0, "val": 0.0, "hvn_count": 0,
            "ivp": float("nan"), "vega_label": "—", "vega_detail": "No data.",
            "vega_level": "info", "quadrant": "—",
            "validated": False, "sample_n": 0, "kill_switches": {}, "home_score": 0,
        }
