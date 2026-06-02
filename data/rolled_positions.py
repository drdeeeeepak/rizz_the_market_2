"""
Unified anchor for Iron Condor position management.

Storage: data/rolled_positions.json
Format:
  {
    "anchor":       float,          # current anchor price
    "anchor_date":  "YYYY-MM-DD",  # date anchor was set
    "ce_strike":    int,            # anchor × 1.035 nearest 50pt
    "pe_strike":    int,            # anchor × 0.960 nearest 50pt
    "history":      [...]           # current cycle events (cleared each Tuesday)
  }

Rules:
- EOD job on Tuesday: calls set_expiry_anchor(eod_close, date) → starts new cycle
- EOD job Mon/Wed/Thu/Fri: calls eod_update(eod_close, date) → checks book levels
- Book loss:   EOD close drifts ≥ 2.5% adverse from anchor → roll both strikes
- Book profit: EOD close drifts ≥ 1.8% favorable from anchor → roll both strikes
- Both sides always reset together from unified anchor = that day's EOD close
- No intraday triggers. No filter gates. Pure price, EOD only.
"""

import json
import logging
import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_PATH    = Path(__file__).parent / "rolled_positions.json"
_DEF_THR = 2.5   # % adverse → BOOK LOSS
_OFF_THR = 1.8   # % favorable → BOOK PROFIT


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_rolled() -> dict:
    try:
        if _PATH.exists():
            d = json.loads(_PATH.read_text())
            d.setdefault("anchor",      None)
            d.setdefault("anchor_date", None)
            d.setdefault("ce_strike",   None)
            d.setdefault("pe_strike",   None)
            d.setdefault("history",     [])
            return d
    except Exception:
        pass
    return {"anchor": None, "anchor_date": None,
            "ce_strike": None, "pe_strike": None, "history": []}


def save_rolled(data: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, indent=2, default=str))


# ── Strike calculation ─────────────────────────────────────────────────────────

def rolled_strikes(anchor: float) -> tuple:
    """Return (ce_strike, pe_strike) from anchor price."""
    ce = int(round(anchor * 1.035 / 50) * 50)
    pe = int(round(anchor * 0.960 / 50) * 50)
    return ce, pe


# ── Roll event check ─────────────────────────────────────────────────────────

def check_roll_event(eod_close: float, anchor: float) -> str | None:
    """
    Pure price check against current anchor.
    Returns event string or None.
    Priority: LOSS events before PROFIT events.
    """
    if anchor <= 0 or eod_close <= 0:
        return None
    drift = (eod_close - anchor) / anchor * 100
    if drift >= _DEF_THR:   return "CE_LOSS"
    if drift <= -_DEF_THR:  return "PE_LOSS"
    if drift <= -_OFF_THR:  return "CE_PROFIT"
    if drift >= _OFF_THR:   return "PE_PROFIT"
    return None


# ── EOD update functions ──────────────────────────────────────────────────────

def set_expiry_anchor(eod_close: float, eod_date: str) -> dict:
    """
    Called by EOD job on Tuesday (expiry day).
    Starts a new cycle: clears history, sets anchor = today's EOD close.
    """
    rolled   = load_rolled()
    old_anc  = rolled.get("anchor")
    old_ce   = rolled.get("ce_strike")
    old_pe   = rolled.get("pe_strike")
    ce, pe   = rolled_strikes(eod_close)

    rolled["anchor"]      = round(eod_close, 2)
    rolled["anchor_date"] = eod_date
    rolled["ce_strike"]   = ce
    rolled["pe_strike"]   = pe
    rolled["history"]     = [{
        "date":       eod_date,
        "event":      "EXPIRY_ANCHOR",
        "eod_close":  round(eod_close, 2),
        "old_anchor": old_anc,
        "new_anchor": round(eod_close, 2),
        "old_ce":     old_ce,
        "new_ce":     ce,
        "old_pe":     old_pe,
        "new_pe":     pe,
    }]
    save_rolled(rolled)
    return rolled


def eod_update(eod_close: float, eod_date: str) -> dict:
    """
    Called by EOD job on non-Tuesday days.
    Checks if book profit or book loss was reached on closing basis.
    If so, rolls both strikes to new anchor = today's EOD close.
    Idempotent: skips if already updated today.
    """
    rolled = load_rolled()
    anchor = float(rolled.get("anchor") or 0)
    if anchor <= 0:
        return rolled

    # Idempotent: skip if already updated today
    history = rolled.get("history", [])
    if history and history[-1].get("date") == eod_date:
        return rolled

    event = check_roll_event(eod_close, anchor)
    if event is None:
        return rolled

    old_ce, old_pe = rolled.get("ce_strike"), rolled.get("pe_strike")
    new_anc        = round(eod_close, 2)
    new_ce, new_pe = rolled_strikes(new_anc)

    rolled["anchor"]      = new_anc
    rolled["anchor_date"] = eod_date
    rolled["ce_strike"]   = new_ce
    rolled["pe_strike"]   = new_pe
    rolled.setdefault("history", []).append({
        "date":       eod_date,
        "event":      event,
        "eod_close":  new_anc,
        "old_anchor": anchor,
        "new_anchor": new_anc,
        "old_ce":     old_ce,
        "new_ce":     new_ce,
        "old_pe":     old_pe,
        "new_pe":     new_pe,
    })
    save_rolled(rolled)
    return rolled


# ── Bootstrap from historical daily data ──────────────────────────────────────

def bootstrap_from_history(daily_df) -> dict:
    """
    Compute anchor and full cycle history from historical daily OHLCV.

    Walks back to find the most recent Tuesday close, sets that as
    EXPIRY_ANCHOR, then replays each subsequent day's close through
    check_roll_event() to rebuild the cycle history up to today.

    Writes and returns the resulting rolled dict.
    Only runs if rolled_positions.json is missing or has no valid anchor.
    """
    import pandas as pd

    rolled = load_rolled()
    # Re-bootstrap if anchor is missing OR if history has no EXPIRY_ANCHOR entry
    _hist = rolled.get("history", [])
    _has_anchor_event = any(h.get("event") == "EXPIRY_ANCHOR" for h in _hist)
    if rolled.get("anchor") and _has_anchor_event:
        return rolled  # already have valid data — don't overwrite

    if daily_df is None or (hasattr(daily_df, "empty") and daily_df.empty):
        log.warning("bootstrap_from_history: no daily data available")
        return rolled

    df = daily_df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        if "date" in df.columns:
            df = df.set_index(pd.to_datetime(df["date"]))
        else:
            df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    # Find the most recent COMPLETED Tuesday — exclude today to avoid partial candle
    today = datetime.date.today()
    tue_rows = df[(df.index.weekday == 1) & (df.index.date < today)]
    if tue_rows.empty:
        # Fallback: include today only if it's not Tuesday (shouldn't happen)
        tue_rows = df[df.index.weekday == 1]
    if tue_rows.empty:
        log.warning("bootstrap_from_history: no Tuesday found in daily data")
        return rolled

    tue_row   = tue_rows.iloc[-1]
    tue_date  = tue_row.name.strftime("%Y-%m-%d")
    tue_close = float(tue_row["close"])

    # Start fresh cycle from that Tuesday
    ce, pe = rolled_strikes(tue_close)
    result = {
        "anchor":      round(tue_close, 2),
        "anchor_date": tue_date,
        "ce_strike":   ce,
        "pe_strike":   pe,
        "history": [{
            "date":       tue_date,
            "event":      "EXPIRY_ANCHOR",
            "eod_close":  round(tue_close, 2),
            "old_anchor": None,
            "new_anchor": round(tue_close, 2),
            "old_ce":     None,
            "new_ce":     ce,
            "old_pe":     None,
            "new_pe":     pe,
        }],
    }

    # Replay each day after Tuesday through roll logic
    post_tue = df[df.index > tue_rows.index[-1]]
    for ts, row in post_tue.iterrows():
        day_str   = ts.strftime("%Y-%m-%d")
        eod_close = float(row["close"])
        anchor    = float(result["anchor"])
        event     = check_roll_event(eod_close, anchor)
        if event:
            new_anc        = round(eod_close, 2)
            new_ce, new_pe = rolled_strikes(new_anc)
            result["history"].append({
                "date":       day_str,
                "event":      event,
                "eod_close":  new_anc,
                "old_anchor": anchor,
                "new_anchor": new_anc,
                "old_ce":     result["ce_strike"],
                "new_ce":     new_ce,
                "old_pe":     result["pe_strike"],
                "new_pe":     new_pe,
            })
            result["anchor"]      = new_anc
            result["anchor_date"] = day_str
            result["ce_strike"]   = new_ce
            result["pe_strike"]   = new_pe

    log.info("bootstrap_from_history: anchor %.0f (%s)  CE %d  PE %d  events: %d",
             result["anchor"], result["anchor_date"],
             result["ce_strike"], result["pe_strike"],
             len(result["history"]))
    save_rolled(result)
    return result
