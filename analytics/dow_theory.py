# analytics/dow_theory.py
# Dow Theory Phase Engine — Single Window System
# Rewritten: 27 Apr 2026
#
# ONE window: 20-day 1H = 120 candles, N=3, rolling daily, never frozen.
# Derives: structure, sequence, phase, retrace%, duration, health per leg,
#          phase score, breach levels, proximity warnings, plain narrative.
# Score history: last 5 days stored in data/dow_score_history.json

import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    DOW_N, DOW_BREACH_BUFFER_PTS,
    DOW_HEALTH_ALERT_PTS, DOW_HEALTH_WATCH_PTS, DOW_HEALTH_MOD_PTS,
    DOW_CONSOLIDATION_ATR, DOW_SCORE_HISTORY_DAYS,
    ATR_PERIOD,
)

log = logging.getLogger(__name__)

_HISTORY_PATH = Path(__file__).parent.parent / "data" / "dow_score_history.json"


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — PIVOT DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def _detect_pivots(df: pd.DataFrame, n: int = DOW_N) -> pd.DataFrame:
    """
    Detect confirmed pivot highs and lows on any 1H OHLCV DataFrame.

    Pivot HIGH at bar i:
        high[i] >= high[i-n .. i-1]   AND   high[i] >= high[i+1 .. i+n]
    Pivot LOW at bar i:
        low[i]  <= low[i-n  .. i-1]   AND   low[i]  <= low[i+1  .. i+n]

    Uses >= / <= so flat-top / flat-bottom pivots are caught.
    Confirmation lag = n hours. Last n candles are always unconfirmed.

    Returns df copy with added columns:
        pivot_high  bool
        pivot_low   bool
        ph_level    float | NaN
        pl_level    float | NaN
    """
    df = df.copy()
    length = len(df)
    highs  = df["high"].values
    lows   = df["low"].values

    ph = np.zeros(length, dtype=bool)
    pl = np.zeros(length, dtype=bool)

    for i in range(n, length - n):
        if highs[i] >= highs[i-n:i].max() and highs[i] >= highs[i+1:i+n+1].max():
            ph[i] = True
        if lows[i]  <= lows[i-n:i].min()  and lows[i]  <= lows[i+1:i+n+1].min():
            pl[i] = True

    df["pivot_high"] = ph
    df["pivot_low"]  = pl
    df["ph_level"]   = np.where(ph, highs, np.nan)
    df["pl_level"]   = np.where(pl, lows,  np.nan)
    return df


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — EXTRACT REFERENCE PIVOTS
# ══════════════════════════════════════════════════════════════════════════════

def _extract_reference_pivots(df: pd.DataFrame) -> Optional[dict]:
    """
    Extract last two confirmed pivot highs and lows with timestamps.

    Returns dict with:
        ph_last, ph_last_ts, ph_last_idx
        ph_prev, ph_prev_ts
        pl_last, pl_last_ts, pl_last_idx
        pl_prev, pl_prev_ts

    Returns None if fewer than 2 of either type confirmed.
    """
    ph_df = df.dropna(subset=["ph_level"])[["ph_level"]].copy()
    pl_df = df.dropna(subset=["pl_level"])[["pl_level"]].copy()

    if len(ph_df) < 2 or len(pl_df) < 2:
        log.warning(
            "Insufficient pivots: %d highs, %d lows (need 2 each)",
            len(ph_df), len(pl_df)
        )
        return None

    ph_vals = ph_df["ph_level"].values
    pl_vals = pl_df["pl_level"].values
    ph_idx  = list(ph_df.index)
    pl_idx  = list(pl_df.index)

    # Get integer positional index for duration counting
    all_idx = list(df.index)

    return {
        "ph_last":     float(ph_vals[-1]),
        "ph_last_ts":  ph_idx[-1],
        "ph_last_pos": all_idx.index(ph_idx[-1]),
        "ph_prev":     float(ph_vals[-2]),
        "ph_prev_ts":  ph_idx[-2],
        "pl_last":     float(pl_vals[-1]),
        "pl_last_ts":  pl_idx[-1],
        "pl_last_pos": all_idx.index(pl_idx[-1]),
        "pl_prev":     float(pl_vals[-2]),
        "pl_prev_ts":  pl_idx[-2],
        "total_candles": len(df),
    }


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — STRUCTURE CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

def _classify_structure(pivots: dict, atr14: float) -> str:
    """
    Compare last two pivot highs and lows to classify trend structure.
    Consolidating check: if PH_last - PL_last < 1 × ATR14.
    """
    ph_last = pivots["ph_last"]; ph_prev = pivots["ph_prev"]
    pl_last = pivots["pl_last"]; pl_prev = pivots["pl_prev"]

    swing_range = ph_last - pl_last
    if swing_range < DOW_CONSOLIDATION_ATR * atr14:
        return "CONSOLIDATING"

    hh = ph_last > ph_prev
    hl = pl_last > pl_prev
    lh = ph_last < ph_prev
    ll = pl_last < pl_prev

    if hh and hl: return "UPTREND"
    if lh and ll: return "DOWNTREND"
    if hh and ll: return "MIXED_EXPANDING"
    if lh and hl: return "MIXED_CONTRACTING"
    return "MIXED_CONTRACTING"   # flat pivots — treat as contracting


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — SEQUENCE CHECK
# ══════════════════════════════════════════════════════════════════════════════

def _sequence_check(pivots: dict) -> str:
    """
    Which pivot was most recently confirmed?

    FALLING: PH_last is more recent → price came up to high, now falling
    RISING:  PL_last is more recent → price came down to low, now rising
    """
    if pivots["ph_last_ts"] > pivots["pl_last_ts"]:
        return "FALLING"
    return "RISING"


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — RETRACE DEPTH %
# ══════════════════════════════════════════════════════════════════════════════

def _retrace_depth(spot: float, pivots: dict, sequence: str) -> float:
    """
    How far through the current move is spot?

    RISING  (bounced from PL_last):
        0%   = just at PL_last
        100% = back at PH_last level

    FALLING (turned from PH_last):
        0%   = just at PH_last
        100% = back at PL_last level

    >100% = new pivot forming (continuation confirmed)
    Capped at 110% for display.
    """
    ph = pivots["ph_last"]
    pl = pivots["pl_last"]
    swing = ph - pl
    if swing <= 0:
        return 0.0

    if sequence == "RISING":
        pct = (spot - pl) / swing * 100
    else:
        pct = (ph - spot) / swing * 100

    return round(min(max(pct, 0.0), 110.0), 1)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — DURATION IN SESSIONS
# ══════════════════════════════════════════════════════════════════════════════

def _duration_sessions(pivots: dict, sequence: str, total_candles: int) -> float:
    """
    Sessions elapsed since the most recent pivot was confirmed.
    Sessions = candles elapsed / 6  (6 candles per NSE session).
    Rounded to 0.5.
    """
    current_pos = total_candles - 1   # last candle index

    if sequence == "RISING":
        pivot_pos = pivots["pl_last_pos"]
    else:
        pivot_pos = pivots["ph_last_pos"]

    candles_elapsed = current_pos - pivot_pos
    sessions = candles_elapsed / 6.0
    # Round to nearest 0.5
    sessions = round(sessions * 2) / 2
    return max(sessions, 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — PHASE DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def _detect_phase(
    structure: str,
    sequence:  str,
    spot:      float,
    last_high: float,   # last candle's HIGH
    last_low:  float,   # last candle's LOW
    pivots:    dict,
    retrace_pct: float,
) -> str:
    """
    Determine current phase within the trend structure.

    Phase codes:
      UT-1  UPTREND_RETRACING
      UT-2  UPTREND_CONTINUING
      UT-3  UPTREND_HL_THREATENED
      UT-4  UPTREND_BROKEN
      DT-1  DOWNTREND_RETRACING
      DT-2  DOWNTREND_CONTINUING
      DT-3  DOWNTREND_LH_THREATENED
      DT-4  DOWNTREND_BROKEN
      MX    MIXED
      SC    CONSOLIDATING

    Continuation uses RAW pivot level — no buffer.
    Buffer only applies to breach level display.
    """
    ph = pivots["ph_last"]
    pl = pivots["pl_last"]

    if structure in ("MIXED_EXPANDING", "MIXED_CONTRACTING"):
        return "MX"

    if structure == "CONSOLIDATING":
        return "SC"

    if structure == "UPTREND":
        # Broken: last candle closed below last HL (raw, no buffer)
        if last_low < pl:
            return "UT-4"
        # Continuing: last candle high crossed above last HH
        if last_high > ph:
            return "UT-2"
        # HL threatened: rising but within 50pts of HL support
        if sequence == "RISING" and retrace_pct > 90:
            return "UT-3"
        # Normal retrace
        return "UT-1"

    if structure == "DOWNTREND":
        # Broken: last candle high crossed above last LH (raw)
        if last_high > ph:
            return "DT-4"
        # Continuing: last candle low crossed below last LL
        if last_low < pl:
            return "DT-2"
        # LH threatened: retracing up within 50pts of LH ceiling
        if sequence == "RISING" and retrace_pct > 90:
            return "DT-3"
        # Normal retrace up
        return "DT-1"

    return "MX"


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8 — LEG HEALTH
# ══════════════════════════════════════════════════════════════════════════════

def _leg_health(distance_pts: float, last_candle_crossed: bool) -> str:
    """
    Convert distance from structural level to health label.

    BREACH   → last candle already crossed the level
    ALERT    → within 50 pts
    WATCH    → within 100 pts
    MODERATE → within 200 pts
    STRONG   → beyond 200 pts
    """
    if last_candle_crossed:
        return "BREACH"
    if distance_pts <= DOW_HEALTH_ALERT_PTS:
        return "ALERT"
    if distance_pts <= DOW_HEALTH_WATCH_PTS:
        return "WATCH"
    if distance_pts <= DOW_HEALTH_MOD_PTS:
        return "MODERATE"
    return "STRONG"


def _compute_health(
    structure: str,
    spot:      float,
    last_high: float,
    last_low:  float,
    pivots:    dict,
) -> tuple[str, float, str, float]:
    """
    Compute CE and PE health based on skewed IC structure.

    DOWNTREND (2:1 — CE is vulnerable):
        CE health = distance from spot to PH_last (LH ceiling)
        PE health = distance from spot to PL_last (LL floor)

    UPTREND (1:2 — PE is vulnerable):
        PE health = distance from spot to PL_last (HL floor)
        CE health = distance from spot to PH_last (HH ceiling)

    Returns: ce_health_label, ce_dist_pts, pe_health_label, pe_dist_pts
    """
    ph = pivots["ph_last"]
    pl = pivots["pl_last"]

    ce_dist = abs(ph - spot)
    pe_dist = abs(spot - pl)

    ce_crossed = last_high > ph
    pe_crossed = last_low  < pl

    ce_health = _leg_health(ce_dist, ce_crossed)
    pe_health = _leg_health(pe_dist, pe_crossed)

    return ce_health, round(ce_dist, 0), pe_health, round(pe_dist, 0)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 9 — PHASE SCORE
# ══════════════════════════════════════════════════════════════════════════════

def _phase_score(structure: str, phase: str, retrace_pct: float) -> str:
    """
    Entry/health score based on structure + phase + retrace depth.

    Runs every day — not just Tuesday.
    On Tuesday: answers "should I enter?"
    On Wed-Mon: answers "is Nifty supporting my position?"

    PRIME    → best structural moment for skewed IC entry
    GOOD     → acceptable
    WAIT     → conditions not yet favourable
    AVOID    → active threat to vulnerable leg
    NO_TRADE → structure broken or changing
    """
    if structure in ("MIXED_EXPANDING", "MIXED_CONTRACTING", "CONSOLIDATING"):
        return "WAIT"

    if structure == "DOWNTREND":
        if phase == "DT-4":
            return "NO_TRADE"
        if phase == "DT-2":
            return "AVOID"
        if phase == "DT-3":
            return "PRIME"     # at LH ceiling — maximum CE protection
        if phase == "DT-1":
            if retrace_pct >= 60:
                return "PRIME"
            if retrace_pct >= 30:
                return "GOOD"
            return "WAIT"

    if structure == "UPTREND":
        if phase == "UT-4":
            return "NO_TRADE"
        if phase == "UT-2":
            return "AVOID"
        if phase == "UT-3":
            return "PRIME"     # at HL floor — maximum PE protection
        if phase == "UT-1":
            if retrace_pct >= 60:
                return "PRIME"
            if retrace_pct >= 30:
                return "GOOD"
            return "WAIT"

    return "WAIT"


# ══════════════════════════════════════════════════════════════════════════════
# STEP 10 — BREACH LEVELS
# ══════════════════════════════════════════════════════════════════════════════

def _breach_levels(pivots: dict, atr14: float, spot: float) -> dict:
    """
    Call breach = PH_last + 50 pts
    Put  breach = PL_last - 50 pts
    Proximity warning when spot within ATR14/3 of either level.
    """
    buf  = DOW_BREACH_BUFFER_PTS
    call = round(pivots["ph_last"] + buf, 0)
    put  = round(pivots["pl_last"] - buf, 0)
    prox = atr14 / 3.0

    return {
        "call_breach":       call,
        "put_breach":        put,
        "breach_buffer_pts": buf,
        "proximity_pts":     round(prox, 1),
        "call_prox_warn":    spot >= call - prox,
        "put_prox_warn":     spot <= put  + prox,
    }


# ══════════════════════════════════════════════════════════════════════════════
# STEP 11 — NARRATIVE
# ══════════════════════════════════════════════════════════════════════════════

_PHASE_LABELS = {
    "UT-1": "retracing after HH",
    "UT-2": "breaking above last HH — uptrend extending",
    "UT-3": "retrace approaching last HL — support being tested",
    "UT-4": "broke below last HL — uptrend structure broken",
    "DT-1": "retracing up after LL",
    "DT-2": "breaking below last LL — downtrend extending",
    "DT-3": "retrace approaching last LH — ceiling being tested",
    "DT-4": "broke above last LH — downtrend structure broken",
    "MX":   "mixed structure — no directional bias",
    "SC":   "consolidating — range too narrow to read",
}

def _session_label(sessions: float) -> str:
    if sessions < 1:   return "today"
    if sessions == 1:  return "1 session"
    if sessions == 1.5: return "1.5 sessions"
    return f"{sessions:.0f} sessions" if sessions == int(sessions) else f"{sessions:.1f} sessions"


def _build_narrative(
    structure:   str,
    phase:       str,
    retrace_pct: float,
    sessions:    float,
    pivots:      dict,
    score:       str,
) -> str:
    """
    Build one plain English sentence describing current Nifty state.

    Examples:
      "DOWNTREND (LH 24,600 → LL 22,300) — retracing up after LL,
       72% of last swing, 3 sessions. Approaching LH ceiling. PRIME."

      "UPTREND (HL 23,800 → HH 24,600) — retracing after HH,
       35% of last swing, 2 sessions. HL floor intact. GOOD."

      "DOWNTREND — breaking below last LL 22,300 today. Trend extending. AVOID."
    """
    ph = pivots["ph_last"]; pl = pivots["pl_last"]
    phase_txt  = _PHASE_LABELS.get(phase, phase)
    sess_txt   = _session_label(sessions)

    if structure == "UPTREND":
        struct_txt = f"UPTREND (HL {pl:,.0f} → HH {ph:,.0f})"
    elif structure == "DOWNTREND":
        struct_txt = f"DOWNTREND (LH {ph:,.0f} → LL {pl:,.0f})"
    elif structure == "MIXED_EXPANDING":
        return "MIXED EXPANDING — higher highs AND lower lows. Range widening. Wait for direction."
    elif structure == "MIXED_CONTRACTING":
        return "MIXED CONTRACTING — coiling wedge. Lower highs and higher lows. Breakout building. Wait."
    elif structure == "CONSOLIDATING":
        return f"CONSOLIDATING — range {pl:,.0f}–{ph:,.0f} is too narrow. No actionable structure."
    else:
        return "MIXED — insufficient pivot data to read structure."

    # Continuation phases — no retrace% needed
    if phase in ("UT-2", "DT-2", "UT-4", "DT-4"):
        return f"{struct_txt} — {phase_txt}, {sess_txt}. [{score}]"

    # Retrace phases — include depth%
    retrace_str = f"{retrace_pct:.0f}% of last swing"

    # Add context based on retrace depth
    if retrace_pct >= 90:
        context = "Near end of retrace."
    elif retrace_pct >= 60:
        context = "Retrace maturing."
    elif retrace_pct >= 30:
        context = "Retrace in progress."
    else:
        context = "Early retrace."

    return (
        f"{struct_txt} — {phase_txt}, "
        f"{retrace_str}, {sess_txt}. "
        f"{context} [{score}]"
    )


# ══════════════════════════════════════════════════════════════════════════════
# STEP 12 — ATR14 ON 1H DATA
# ══════════════════════════════════════════════════════════════════════════════

def _atr14(df: pd.DataFrame) -> float:
    """ATR14 computed on 1H OHLCV. Returns 200 as safe fallback."""
    try:
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"]  - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        val = tr.rolling(ATR_PERIOD).mean().iloc[-1]
        return float(val) if not np.isnan(val) else 200.0
    except Exception:
        return 200.0


# ══════════════════════════════════════════════════════════════════════════════
# STEP 13 — SCORE HISTORY
# ══════════════════════════════════════════════════════════════════════════════

def _load_history() -> list:
    try:
        if _HISTORY_PATH.exists():
            return json.loads(_HISTORY_PATH.read_text())
    except Exception:
        pass
    return []


def _save_history(record: dict) -> list:
    """Append today's record to history. Keep last N days."""
    history = _load_history()
    # Remove any existing entry for today
    today_str = str(date.today())
    history = [r for r in history if r.get("date") != today_str]
    history.append(record)
    # Keep last N days only
    history = history[-DOW_SCORE_HISTORY_DAYS:]
    try:
        _HISTORY_PATH.parent.mkdir(exist_ok=True)
        _HISTORY_PATH.write_text(json.dumps(history, default=str, indent=2))
    except Exception as e:
        log.error("Failed to save dow score history: %s", e)
    return history


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class DowTheoryEngine:
    """
    Dow Theory Phase Engine.

    Usage:
        engine = DowTheoryEngine()
        sig = engine.signals(df_1h, spot)

    df_1h must be a 20-day 1H OHLCV DataFrame from get_nifty_1h_phase().
    spot is current Nifty spot price.
    """

    def signals(self, df: pd.DataFrame, spot: float) -> dict:
        """
        Run complete phase analysis. Returns flat dict of all dow_ signals.
        Called every day during live/transition/pre-market modes.
        """
        sig = {}

        # Guard
        if df is None or df.empty or len(df) < 10:
            log.error("1H phase data empty or too short (%d candles)", len(df) if df is not None else 0)
            return self._empty_signals()

        # ── ATR14 ─────────────────────────────────────────────────────────────
        atr14 = _atr14(df)
        sig["atr14_1h"] = round(atr14, 1)

        # ── Step 1: Pivot detection ───────────────────────────────────────────
        df_piv = _detect_pivots(df, DOW_N)

        # ── Step 2: Reference pivots ──────────────────────────────────────────
        pivots = _extract_reference_pivots(df_piv)
        if pivots is None:
            log.warning("Insufficient confirmed pivots — returning INSUFFICIENT_DATA")
            sig.update(self._insufficient_signals(atr14))
            return sig

        sig["ph_last"]      = round(pivots["ph_last"], 0)
        sig["ph_prev"]      = round(pivots["ph_prev"], 0)
        sig["pl_last"]      = round(pivots["pl_last"], 0)
        sig["pl_prev"]      = round(pivots["pl_prev"], 0)
        sig["ph_last_ts"]   = str(pivots["ph_last_ts"])
        sig["pl_last_ts"]   = str(pivots["pl_last_ts"])
        sig["candles_used"] = pivots["total_candles"]

        # ── Step 3: Structure ─────────────────────────────────────────────────
        structure = _classify_structure(pivots, atr14)
        sig["structure"] = structure

        # ── Step 4: Sequence ──────────────────────────────────────────────────
        sequence = _sequence_check(pivots)
        sig["sequence"] = sequence

        # ── Step 5: Retrace depth ─────────────────────────────────────────────
        retrace_pct = _retrace_depth(spot, pivots, sequence)
        sig["retrace_pct"] = retrace_pct

        # ── Step 6: Duration ──────────────────────────────────────────────────
        sessions = _duration_sessions(pivots, sequence, pivots["total_candles"])
        sig["sessions_in_phase"] = sessions

        # ── Last candle high/low for phase and health checks ──────────────────
        last_high = float(df["high"].iloc[-1])
        last_low  = float(df["low"].iloc[-1])

        # ── Step 7: Phase ─────────────────────────────────────────────────────
        phase = _detect_phase(
            structure, sequence, spot,
            last_high, last_low, pivots, retrace_pct
        )
        sig["phase"] = phase

        # ── Step 8: Health ────────────────────────────────────────────────────
        ce_health, ce_pts, pe_health, pe_pts = _compute_health(
            structure, spot, last_high, last_low, pivots
        )
        sig["ce_health"]      = ce_health
        sig["ce_health_pts"]  = ce_pts
        sig["pe_health"]      = pe_health
        sig["pe_health_pts"]  = pe_pts

        # ── Step 9: Phase score ───────────────────────────────────────────────
        score = _phase_score(structure, phase, retrace_pct)
        sig["phase_score"] = score

        # Score label: entry decision on Tuesday, Nifty health otherwise
        sig["phase_score_label"] = (
            "Entry Decision" if date.today().weekday() == 1
            else "Nifty Health Monitor"
        )

        # ── Step 10: Breach levels ────────────────────────────────────────────
        breach = _breach_levels(pivots, atr14, spot)
        sig.update(breach)

        # ── Step 11: Narrative ────────────────────────────────────────────────
        sig["narrative"] = _build_narrative(
            structure, phase, retrace_pct, sessions, pivots, score
        )

        # ── Step 12: IC shape from structure ──────────────────────────────────
        IC_SHAPE = {
            "UPTREND":            ("1:2 — CE further",          "Full size"),
            "DOWNTREND":          ("2:1 — PE further",          "75% size"),
            "MIXED_EXPANDING":    ("1:1 — Symmetric wide",      "75% size"),
            "MIXED_CONTRACTING":  ("1:1 — Symmetric watch",     "75% size"),
            "CONSOLIDATING":      ("1:1 — Wait",                "Wait"),
        }
        ic_shape, ic_size = IC_SHAPE.get(structure, ("1:1 — Symmetric", "Full size"))
        sig["ic_shape"] = ic_shape
        sig["ic_size"]  = ic_size

        # ── Step 13: Home score contribution (0-5) ────────────────────────────
        HOME_SCORE = {
            "UPTREND": 5, "DOWNTREND": 5,
            "MIXED_EXPANDING": 3, "MIXED_CONTRACTING": 3,
            "CONSOLIDATING": 1,
        }
        sig["home_score"] = HOME_SCORE.get(structure, 2)

        # ── Step 14: Save to history ──────────────────────────────────────────
        record = {
            "date":        str(date.today()),
            "weekday":     date.today().strftime("%A"),
            "structure":   structure,
            "phase":       phase,
            "retrace_pct": retrace_pct,
            "sessions":    sessions,
            "ce_health":   ce_health,
            "pe_health":   pe_health,
            "phase_score": score,
            "narrative":   sig["narrative"],
        }
        sig["score_history"] = _save_history(record)

        sig["kill_switches"]    = {}
        sig["insufficient_data"] = False
        return sig

    # ── Fallback signals when data is missing ─────────────────────────────────

    def _empty_signals(self) -> dict:
        return {
            "structure": "MIXED", "phase": "MX", "sequence": "RISING",
            "retrace_pct": 0.0, "sessions_in_phase": 0.0,
            "ph_last": 0.0, "ph_prev": 0.0, "pl_last": 0.0, "pl_prev": 0.0,
            "ce_health": "STRONG", "ce_health_pts": 0.0,
            "pe_health": "STRONG", "pe_health_pts": 0.0,
            "phase_score": "WAIT", "phase_score_label": "Nifty Health Monitor",
            "call_breach": 0.0, "put_breach": 0.0,
            "call_prox_warn": False, "put_prox_warn": False,
            "proximity_pts": 66.0, "breach_buffer_pts": 50,
            "atr14_1h": 200.0, "narrative": "No data available.",
            "ic_shape": "1:1 — Symmetric", "ic_size": "Wait",
            "home_score": 0, "score_history": [],
            "kill_switches": {}, "insufficient_data": True,
        }

    def _insufficient_signals(self, atr14: float) -> dict:
        base = self._empty_signals()
        base["atr14_1h"] = round(atr14, 1)
        base["narrative"] = (
            "Insufficient confirmed pivots in 20-day 1H window. "
            "Need at least 2 pivot highs and 2 pivot lows. "
            "Check if market data is complete."
        )
        return base
