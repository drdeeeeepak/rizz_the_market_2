"""
Per-side rolled-anchor positions.

Storage: data/rolled_positions.json
Format:
  {
    "CE": {"active": bool, "anchor": float, "strike": int,
           "anchor_date": "YYYY-MM-DD", "roll_type": "LOSS"|"PROFIT"},
    "PE": { same },
    "last_expiry_clear": "YYYY-MM-DD" | null,
    "provisional_anchor": float | null
  }

Rules (per spec):
- At 3:15 PM IST each trading day, if BOOK_LOSS or BOOK_PROFIT is still active
  on a side, that day's 3:15 PM spot becomes the new anchor for that side.
- New rolled strike = anchor × 1.035 (CE) or × 0.960 (PE), nearest 50pt.
- Expiry = Tuesday of each week; if Tuesday is a holiday use the last trading day before.
- At 3:16 PM on expiry day: both sides clear; spot becomes provisional anchor.
"""

import json
import datetime
from pathlib import Path
import pytz

_PATH = Path(__file__).parent / "rolled_positions.json"
_IST  = pytz.timezone("Asia/Kolkata")

_DEF_THR = 2.5   # % adverse for BOOK_LOSS
_OFF_THR = 1.8   # % favorable for BOOK_PROFIT

_EMPTY_SIDE: dict = {
    "active": False, "anchor": None, "strike": None,
    "anchor_date": None, "roll_type": None,
}


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_rolled() -> dict:
    try:
        if _PATH.exists():
            d = json.loads(_PATH.read_text())
            d.setdefault("CE", dict(_EMPTY_SIDE))
            d.setdefault("PE", dict(_EMPTY_SIDE))
            d.setdefault("last_expiry_clear", None)
            d.setdefault("provisional_anchor", None)
            return d
    except Exception:
        pass
    return {
        "CE": dict(_EMPTY_SIDE), "PE": dict(_EMPTY_SIDE),
        "last_expiry_clear": None, "provisional_anchor": None,
    }


def save_rolled(data: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, indent=2, default=str))


# ── Expiry ────────────────────────────────────────────────────────────────────

def get_expiry_date(ref_date: datetime.date | None = None) -> datetime.date:
    """Return this/next Tuesday (weekday=1). If today IS Tuesday, return today."""
    if ref_date is None:
        ref_date = datetime.date.today()
    days_ahead = (1 - ref_date.weekday()) % 7   # 0 when today is Tuesday
    return ref_date + datetime.timedelta(days=days_ahead)


# ── Book-state logic ──────────────────────────────────────────────────────────

def _side_book_state(
    spot: float, anchor: float, side: str,
    threat_mult: float, canary_count: int, mom_score: float,
) -> str:
    """
    Returns one of: BOOK_LOSS | PREPARE_LOSS | BOOK_PROFIT | PREPARE_PROFIT | HOLD.
    canary_count is the per-side canary day (0-4).
    """
    if anchor <= 0 or spot <= 0:
        return "HOLD"

    if side == "CE":
        adv = max((spot - anchor) / anchor * 100, 0.0)
        fav = max((anchor - spot) / anchor * 100, 0.0)
        mom_ok = mom_score > 0
    else:
        adv = max((anchor - spot) / anchor * 100, 0.0)
        fav = max((spot - anchor) / anchor * 100, 0.0)
        mom_ok = mom_score < 0

    f1 = adv >= _DEF_THR
    f2 = threat_mult > 1.15
    f3 = canary_count >= 2
    f4 = mom_ok
    fp = int(f1) + int(f2) + int(f3) + int(f4)

    if f1 and f2 and f3 and f4:
        return "BOOK_LOSS"
    if adv >= _DEF_THR * 0.90 or (adv >= _DEF_THR * 0.80 and fp >= 3):
        return "PREPARE_LOSS"
    if fav >= _OFF_THR:
        return "BOOK_PROFIT"
    if fav >= _OFF_THR * 0.75:
        return "PREPARE_PROFIT"
    return "HOLD"


def rolled_strike(anchor: float, side: str) -> int:
    """3.5 % above anchor for CE, 4 % below for PE, nearest 50 pt."""
    pct = 1.035 if side == "CE" else 0.960
    return int(round(anchor * pct / 50) * 50)


# ── Main update function ──────────────────────────────────────────────────────

def maybe_update_anchors(
    spot: float,
    tue_close: float,
    sig: dict,
    rolled: dict | None = None,
    ce_canary: int = 0,
    pe_canary: int = 0,
) -> dict:
    """
    Call on every page load.  Before 3:15 PM returns unchanged.
    At/after 3:15 PM: evaluates each side; if BOOK_LOSS or BOOK_PROFIT is active
    and the anchor has not already been updated today, sets new anchor = spot.
    At 3:16 PM on expiry day: clears both sides.
    """
    now     = datetime.datetime.now(_IST)
    minutes = now.hour * 60 + now.minute
    today   = now.date()

    if rolled is None:
        rolled = load_rolled()

    expiry = get_expiry_date(today)

    # ── Expiry auto-clear ─────────────────────────────────────────────────────
    if today == expiry and minutes >= 15 * 60 + 16:
        if rolled.get("last_expiry_clear") != str(today):
            rolled["CE"]                 = dict(_EMPTY_SIDE)
            rolled["PE"]                 = dict(_EMPTY_SIDE)
            rolled["last_expiry_clear"]  = str(today)
            rolled["provisional_anchor"] = round(spot, 2)
            save_rolled(rolled)
        return rolled

    # ── Only evaluate at/after 3:15 PM ───────────────────────────────────────
    if minutes < 15 * 60 + 15:
        return rolled

    threat_mult = float(sig.get("threat_mult", 0.0))
    mom_score   = float(sig.get("cr_mom_score", 0.0))

    # Per-side canary counts: prefer caller-supplied; fall back to sig direction
    if ce_canary == 0 and pe_canary == 0:
        _cdir = str(sig.get("canary_direction", "NONE"))
        _clvl = int(sig.get("canary_level", 0))
        ce_canary = _clvl if _cdir in ("BULL",) else 0
        pe_canary = _clvl if _cdir in ("BEAR",) else 0

    changed = False
    for side, canary_cnt in (("CE", ce_canary), ("PE", pe_canary)):
        s = rolled.setdefault(side, dict(_EMPTY_SIDE))
        # Effective anchor for this side
        anchor = (float(s["anchor"]) if s.get("active") and s.get("anchor")
                  else float(tue_close or 0))
        if anchor <= 0:
            continue

        state = _side_book_state(spot, anchor, side, threat_mult, canary_cnt, mom_score)

        if state in ("BOOK_LOSS", "BOOK_PROFIT"):
            if s.get("anchor_date") != str(today):   # not already updated today
                s["active"]      = True
                s["anchor"]      = round(spot, 2)
                s["strike"]      = rolled_strike(spot, side)
                s["anchor_date"] = str(today)
                s["roll_type"]   = "LOSS" if state == "BOOK_LOSS" else "PROFIT"
                changed = True

    if changed:
        save_rolled(rolled)

    return rolled
