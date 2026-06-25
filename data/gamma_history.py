# data/gamma_history.py
# Dealer-gamma history — because Kite serves no HISTORICAL option open-interest, gamma
# can't be back-filled onto past candles. So we LOG IT FORWARD instead:
#   • Daily snapshot  → written by the EOD job into data/gamma_history.json (committed),
#                       building a real day-by-day gamma history from now on.
#   • Intraday today  → appended on each live page load into data/gamma_today.json
#                       (ephemeral / gitignored), so you can see how today's flip line
#                       migrated through the session.
# Days you don't log in have no token → the EOD job can't fetch the chain → that day is
# simply MISSING (shown as a gap, never faked).

import json
import logging
from pathlib import Path
from datetime import datetime

import pytz

log = logging.getLogger(__name__)

_DIR = Path(__file__).resolve().parent
DAILY_FILE = _DIR / "gamma_history.json"      # committed by the EOD job
TODAY_FILE = _DIR / "gamma_today.json"        # ephemeral intraday log (gitignored)
IST = pytz.timezone("Asia/Kolkata")

_MAX_DAILY = 180        # keep ~6 months of daily snapshots
_MAX_TODAY = 200        # plenty of intraday points for one session


def _today_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def _snapshot(gex: dict, spot: float) -> dict:
    """Extract the small, durable gamma fields we want to keep."""
    return {
        "regime":   gex.get("regime", "UNKNOWN"),
        "flip":     gex.get("flip_level"),
        "net_gex":  gex.get("net_gex", 0.0),
        "call_wall": gex.get("call_wall"),
        "put_wall":  gex.get("put_wall"),
        "spot":     round(float(spot), 1) if spot else None,
    }


def _read(path: Path) -> list:
    try:
        if path.exists():
            data = json.loads(path.read_text())
            return data if isinstance(data, list) else []
    except Exception as e:
        log.warning("gamma history read failed (%s): %s", path.name, e)
    return []


# ── Daily (EOD job) ───────────────────────────────────────────────────────────

def append_daily_snapshot(date_str: str, gex: dict, spot: float) -> None:
    """Idempotent per date: replace today's record if it already exists, else append."""
    if not gex or gex.get("regime") in (None, "UNKNOWN"):
        log.info("Gamma snapshot skipped for %s — no usable gamma (chain/auth issue).", date_str)
        return
    rows = [r for r in _read(DAILY_FILE) if r.get("date") != date_str]
    rows.append({"date": date_str, **_snapshot(gex, spot)})
    rows.sort(key=lambda r: r.get("date", ""))
    rows = rows[-_MAX_DAILY:]
    try:
        DAILY_FILE.write_text(json.dumps(rows, indent=2))
        log.info("Gamma daily snapshot saved for %s (regime=%s flip=%s)",
                 date_str, gex.get("regime"), gex.get("flip_level"))
    except Exception as e:
        log.warning("gamma daily write failed: %s", e)


def load_daily_history() -> list:
    """List of daily gamma snapshots, oldest first."""
    return _read(DAILY_FILE)


# ── Intraday (live page) ──────────────────────────────────────────────────────

def log_intraday_snapshot(gex: dict, spot: float) -> None:
    """Append a timestamped gamma point for TODAY; dedupes to ~1 per minute."""
    if not gex or gex.get("regime") in (None, "UNKNOWN"):
        return
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    rows = _read(TODAY_FILE)
    # Reset if the stored log is from a previous day.
    if rows and rows[-1].get("date") != today:
        rows = []
    stamp = now.strftime("%H:%M")
    if rows and rows[-1].get("time") == stamp:
        return                                  # already logged this minute
    rows.append({"date": today, "time": stamp, **_snapshot(gex, spot)})
    rows = rows[-_MAX_TODAY:]
    try:
        TODAY_FILE.write_text(json.dumps(rows))
    except Exception as e:
        log.warning("gamma intraday write failed: %s", e)


def load_intraday_today() -> list:
    """Today's intraday gamma points (empty if the file is from a prior day)."""
    rows = _read(TODAY_FILE)
    if rows and rows[-1].get("date") != _today_ist():
        return []
    return rows
