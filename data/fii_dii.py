# data/fii_dii.py
# Participant-wise derivative open interest from NSE — who is actually positioned
# where. This is the one dataset that says whether FIIs are net long or short index
# options, which the Kite feed cannot tell you: Kite reports TOTAL open interest at
# a strike, never who is on which side of it.
#
# NSE publishes "Participant wise Open Interest" once a day, around 7:00–7:30 PM
# IST, as a CSV covering four categories:
#     FII    — foreign institutional investors  (the flow usually worth following)
#     DII    — domestic institutions            (often the other side of FII)
#     Pro    — proprietary desks
#     Client — retail and everyone else
# for Future Index / Stock and Option Index / Stock, long and short.
#
# ─── THIS IS A FRAGILE SOURCE, AND IT IS TREATED AS ONE ──────────────────────
# Unlike Kite, this is a public web endpoint with no contract and no support:
#   • it rejects plain programmatic requests, so a cookie must be picked up from
#     the homepage first and sent with the download
#   • the file appears at a time NSE does not guarantee, and not at all on holidays
#   • the column layout has changed before and will change again
# So every record carries the date it was fetched and every read exposes how old
# the newest row is. A silent failure must never be able to look like fresh data —
# that is exactly the class of bug this codebase has been cleaning up all session.

import csv
import io
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytz

log = logging.getLogger(__name__)

_DIR = Path(__file__).resolve().parent
HISTORY_FILE = _DIR / "fii_dii_history.json"     # committed by the 8 PM job
IST = pytz.timezone("Asia/Kolkata")

_MAX_ROWS = 500          # ~2 years of trading days

_HOME = "https://www.nseindia.com"
_CSV  = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d}.csv"

_HEADERS = {
    # NSE blocks anything that does not look like a browser.
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _HOME + "/all-reports-derivatives",
}

CATEGORIES = ("FII", "DII", "Pro", "Client")


def _today_ist() -> datetime:
    return datetime.now(IST)


def _num(x) -> float:
    try:
        return float(str(x).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


# ─── Fetch ────────────────────────────────────────────────────────────────────

def fetch_participant_oi(for_date=None, timeout: int = 20) -> dict:
    """
    Download one day's participant-wise OI.

    Returns {"ok": bool, "date": "YYYY-MM-DD", "rows": {...}, "error": str|None}.
    Never raises and never invents numbers — a failure returns ok=False with the
    reason, so the caller can say "not available" rather than show a stale figure
    as if it were today's.
    """
    import requests

    d = for_date or _today_ist().date()
    dstr = d.strftime("%d%m%Y")
    out = {"ok": False, "date": d.strftime("%Y-%m-%d"), "rows": {}, "error": None,
           "fetched_at": _today_ist().strftime("%Y-%m-%d %H:%M")}

    try:
        s = requests.Session()
        s.headers.update(_HEADERS)
        # Pick up the cookie NSE sets on the homepage — the archive rejects requests
        # that arrive without it.
        try:
            s.get(_HOME, timeout=timeout)
        except Exception as e:
            log.info("NSE homepage warm-up failed (continuing): %s", e)

        resp = s.get(_CSV.format(d=dstr), timeout=timeout)
        if resp.status_code != 200:
            out["error"] = f"HTTP {resp.status_code} for {dstr} (file may not be published yet)"
            return out
        text = resp.text.strip()
        if not text or "<html" in text[:200].lower():
            out["error"] = "NSE returned a web page, not the CSV (blocked or not published)"
            return out

        rows = _parse_csv(text)
        if not rows:
            out["error"] = "CSV downloaded but no participant rows recognised — layout may have changed"
            return out

        out["rows"] = rows
        out["ok"] = True
        return out
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out


def _parse_csv(text: str) -> dict:
    """
    Pull the four participant rows out of the CSV.

    NSE puts a title line above the real header, and the column names have shifted
    over the years, so columns are matched by a normalised substring rather than an
    exact string — an exact match would break silently the next time NSE edits a
    caption.
    """
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return {}

    # The header is the first line that names the participant column.
    hdr_i = next((i for i, l in enumerate(lines)
                  if "client type" in l.lower() or "clienttype" in l.lower()), None)
    if hdr_i is None:
        return {}

    reader = csv.reader(io.StringIO("\n".join(lines[hdr_i:])))
    header = [h.strip() for h in next(reader, [])]
    norm = [h.lower().replace(" ", "").replace("_", "") for h in header]

    def col(*subs):
        for i, h in enumerate(norm):
            if all(s in h for s in subs):
                return i
        return None

    idx = {
        "client":    col("clienttype") or 0,
        "fut_long":  col("future", "index", "long"),
        "fut_short": col("future", "index", "short"),
        "ce_long":   col("option", "index", "call", "long"),
        "ce_short":  col("option", "index", "call", "short"),
        "pe_long":   col("option", "index", "put", "long"),
        "pe_short":  col("option", "index", "put", "short"),
    }

    out = {}
    for row in reader:
        if not row:
            continue
        name = str(row[idx["client"]]).strip()
        match = next((c for c in CATEGORIES if c.lower() == name.lower()), None)
        if not match:
            continue
        rec = {}
        for k, i in idx.items():
            if k == "client" or i is None or i >= len(row):
                continue
            rec[k] = _num(row[i])
        if rec:
            # Net index-option position. A call bought and a put sold are both
            # bullish, so the directional read pairs them that way.
            rec["fut_net"] = rec.get("fut_long", 0) - rec.get("fut_short", 0)
            rec["ce_net"]  = rec.get("ce_long", 0)  - rec.get("ce_short", 0)
            rec["pe_net"]  = rec.get("pe_long", 0)  - rec.get("pe_short", 0)
            rec["opt_bias"] = rec["ce_net"] - rec["pe_net"]
            out[match] = rec
    return out


# ─── Store ────────────────────────────────────────────────────────────────────

def _read() -> list:
    try:
        if HISTORY_FILE.exists():
            data = json.loads(HISTORY_FILE.read_text())
            return data if isinstance(data, list) else []
    except Exception as e:
        log.warning("FII/DII history read failed: %s", e)
    return []


def append_snapshot(snap: dict) -> bool:
    """Idempotent per date. Only successful fetches are stored — never a failure."""
    if not snap or not snap.get("ok") or not snap.get("rows"):
        log.info("FII/DII snapshot not stored for %s — %s",
                 snap.get("date"), snap.get("error"))
        return False
    rows = [r for r in _read() if r.get("date") != snap["date"]]
    rows.append({"date": snap["date"], "fetched_at": snap.get("fetched_at"),
                 **snap["rows"]})
    rows.sort(key=lambda r: r.get("date", ""))
    try:
        HISTORY_FILE.write_text(json.dumps(rows[-_MAX_ROWS:], indent=1))
        log.info("FII/DII snapshot saved for %s", snap["date"])
        return True
    except Exception as e:
        log.warning("FII/DII write failed: %s", e)
        return False


def load_history() -> list:
    """All stored days, oldest first."""
    return _read()


def latest(max_age_days: int = 5) -> dict:
    """
    Most recent stored day, with an explicit staleness read.

    Always returns 'age_days' and 'stale' so the page can say how old the number is.
    Showing a five-day-old institutional position as if it were tonight's is the
    failure mode this whole module is built to avoid.
    """
    rows = _read()
    if not rows:
        return {"available": False, "reason": "No FII/DII data collected yet."}
    last = rows[-1]
    try:
        d = datetime.strptime(last["date"], "%Y-%m-%d").date()
        age = (_today_ist().date() - d).days
    except Exception:
        age = None
    return {
        "available": True,
        "date": last.get("date"),
        "fetched_at": last.get("fetched_at"),
        "age_days": age,
        "stale": (age is not None and age > max_age_days),
        "rows": {k: v for k, v in last.items()
                 if k in CATEGORIES and isinstance(v, dict)},
        "days_stored": len(rows),
    }


def read_bias(rec: dict) -> tuple:
    """
    Plain-English read of one participant's index-option book.
    Returns (label, note). Long calls and short puts are both bullish.
    """
    if not rec:
        return "—", "No data"
    bias = rec.get("opt_bias", 0)
    ce_n, pe_n = rec.get("ce_net", 0), rec.get("pe_net", 0)
    if bias > 0:
        lbl = "BULLISH"
        note = f"Net long calls ({ce_n:+,.0f}) versus puts ({pe_n:+,.0f})"
    elif bias < 0:
        lbl = "BEARISH"
        note = f"Net long puts ({pe_n:+,.0f}) versus calls ({ce_n:+,.0f})"
    else:
        lbl = "NEUTRAL"
        note = "Calls and puts balanced"
    return lbl, note
