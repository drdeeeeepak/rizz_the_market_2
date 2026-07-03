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
- Book loss:   EOD close drifts ≥ 2.5% adverse from anchor → roll BOTH strikes from new anchor
- Book profit: EOD close drifts ≥ 1.8% favorable from anchor → roll ONLY the profitable leg; other stays
- Loss events always reset both sides; profit events re-sell only the triggered leg
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

def check_roll_event(eod_close: float, anchor: float,
                      loss_thr: float = _DEF_THR, profit_thr: float = _OFF_THR) -> str | None:
    """
    Pure price check against current anchor.
    Returns event string or None.
    Priority: LOSS events before PROFIT events.
    loss_thr / profit_thr let a backtest scan alternate roll triggers; live callers
    rely on the defaults (2.5% / 1.8%) and never need to pass them.
    """
    if anchor <= 0 or eod_close <= 0:
        return None
    drift = (eod_close - anchor) / anchor * 100
    if drift >= loss_thr:    return "CE_LOSS"
    if drift <= -loss_thr:   return "PE_LOSS"
    if drift <= -profit_thr: return "CE_PROFIT"
    if drift >= profit_thr:  return "PE_PROFIT"
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
    Loss events (CE_LOSS / PE_LOSS): both strikes reset to new anchor.
    Profit events (CE_PROFIT / PE_PROFIT): only the profitable leg re-sold
    from new anchor; the other strike stays in place.
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

    old_ce  = rolled.get("ce_strike")
    old_pe  = rolled.get("pe_strike")
    new_anc = round(eod_close, 2)
    calc_ce, calc_pe = rolled_strikes(new_anc)

    if event in ("CE_LOSS", "PE_LOSS"):
        new_ce, new_pe = calc_ce, calc_pe          # both sides reset
    elif event == "CE_PROFIT":
        new_ce, new_pe = calc_ce, old_pe           # only CE re-sold further OTM
    else:  # PE_PROFIT
        new_ce, new_pe = old_ce, calc_pe           # only PE re-sold further OTM

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


def compute_anchor_live(daily_df) -> dict:
    """
    Compute anchor in-memory from historical daily OHLCV — no disk write.
    Primary anchor source for pg02, same pattern as live EMA signals.

    Logic:
    - Finds the most recent Tuesday CALENDAR date (the anchor week start).
    - If that Tuesday was a market holiday, uses the last trading day
      BEFORE it (e.g. Monday or prior Friday) as the anchor — no data lost.
    - Replays each subsequent completed EOD close through check_roll_event
      to rebuild loss/profit roll history up to today.
    - Today's candle is included only if market is closed (>=15:30 IST).

    Returns dict with anchor, anchor_date, ce_strike, pe_strike, history.
    Returns {} if data is insufficient.
    """
    import pandas as pd
    import pytz as _pytz

    if daily_df is None or (hasattr(daily_df, "empty") and daily_df.empty):
        return {}

    df = daily_df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        if "date" in df.columns:
            df = df.set_index(pd.to_datetime(df["date"]))
        else:
            df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    _now_ist      = datetime.datetime.now(_pytz.timezone("Asia/Kolkata"))
    _today_ist    = _now_ist.strftime("%Y-%m-%d")
    _mkt_closed   = _now_ist.hour > 15 or (_now_ist.hour == 15 and _now_ist.minute >= 30)
    _today_is_tue = _now_ist.weekday() == 1
    _idx_dates    = df.index.strftime("%Y-%m-%d")

    # ── Step 1: find the most recent anchor-Tuesday calendar date ─────────────
    # If today is Tuesday and market not closed yet, anchor is last week's Tuesday.
    days_since_tue = (_now_ist.weekday() - 1) % 7   # Mon=6,Tue=0,Wed=1,...,Fri=3
    if _today_is_tue and not _mkt_closed:
        days_since_tue = 7  # today's candle is partial — use previous Tuesday
    anchor_tue_cal = (_now_ist - datetime.timedelta(days=days_since_tue)).strftime("%Y-%m-%d")

    # ── Step 2: last trading day ON OR BEFORE that calendar Tuesday ───────────
    # Handles Tuesday holidays: e.g. if Tue Jun 3 is holiday, uses Mon Jun 2.
    anchor_candidates = df[_idx_dates <= anchor_tue_cal]
    if anchor_candidates.empty:
        return {}

    anchor_row   = anchor_candidates.iloc[-1]
    anchor_date  = anchor_row.name.strftime("%Y-%m-%d")
    anchor_close = float(anchor_row["close"])
    ce, pe       = rolled_strikes(anchor_close)

    result = {
        "anchor":      round(anchor_close, 2),
        "anchor_date": anchor_date,
        "ce_strike":   ce,
        "pe_strike":   pe,
        "history": [{
            "date":       anchor_date,
            "event":      "EXPIRY_ANCHOR",
            "eod_close":  round(anchor_close, 2),
            "old_anchor": None,
            "new_anchor": round(anchor_close, 2),
            "old_ce":     None,
            "new_ce":     ce,
            "old_pe":     None,
            "new_pe":     pe,
        }],
    }

    # ── Step 3: replay each day after anchor through roll logic ───────────────
    for ts, row in df[df.index > anchor_row.name].iterrows():
        day_str = ts.strftime("%Y-%m-%d")
        # Skip today's candle if market is still open (partial data)
        if day_str >= _today_ist and not _mkt_closed:
            break
        eod_close = float(row["close"])
        anchor    = float(result["anchor"])
        event     = check_roll_event(eod_close, anchor)
        if event:
            new_anc          = round(eod_close, 2)
            calc_ce, calc_pe = rolled_strikes(new_anc)
            old_ce           = result["ce_strike"]
            old_pe           = result["pe_strike"]

            if event in ("CE_LOSS", "PE_LOSS"):
                new_ce, new_pe = calc_ce, calc_pe   # both sides reset
            elif event == "CE_PROFIT":
                new_ce, new_pe = calc_ce, old_pe    # only CE re-sold further OTM
            else:  # PE_PROFIT
                new_ce, new_pe = old_ce, calc_pe    # only PE re-sold further OTM

            result["history"].append({
                "date":       day_str,
                "event":      event,
                "eod_close":  new_anc,
                "old_anchor": anchor,
                "new_anchor": new_anc,
                "old_ce":     old_ce,
                "new_ce":     new_ce,
                "old_pe":     old_pe,
                "new_pe":     new_pe,
            })
            result["anchor"]      = new_anc
            result["anchor_date"] = day_str
            result["ce_strike"]   = new_ce
            result["pe_strike"]   = new_pe

    return result