#!/usr/bin/env python3
"""
Fetch NSE participant-wise derivative OI and append it to the history file.

Runs on its own schedule (~8:00 PM IST) because NSE publishes this around
7:00-7:30 PM — every other job in this repo finishes by 5:05 PM and would only
ever find yesterday's file.

Usage:
    python scripts/fetch_fii_dii.py            # today
    python scripts/fetch_fii_dii.py 2026-07-30 # a specific date (backfill)

Exit codes:
    0  stored, or nothing to do (weekend / holiday — not a failure)
    1  the file should have been there and was not
"""
import logging
import sys
from datetime import datetime, date, timedelta

import pytz

sys.path.insert(0, ".")

from data.fii_dii import fetch_participant_oi, append_snapshot, load_history

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fii_dii")

IST = pytz.timezone("Asia/Kolkata")


def _telegram(msg: str) -> None:
    import os
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT")
    if not tok or not chat:
        return
    try:
        import requests
        requests.get(f"https://api.telegram.org/bot{tok}/sendMessage",
                     params={"chat_id": chat, "text": msg}, timeout=10)
    except Exception as e:
        log.warning("telegram failed: %s", e)


def main() -> int:
    if len(sys.argv) > 1:
        target = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        target = datetime.now(IST).date()

    # NSE publishes nothing for Saturday or Sunday. Skipping quietly is correct —
    # flagging it as a failure would train us to ignore the alerts that matter.
    if target.weekday() >= 5:
        log.info("%s is a weekend — nothing published, skipping.", target)
        return 0

    snap = fetch_participant_oi(target)
    if snap["ok"]:
        stored = append_snapshot(snap)
        fii = snap["rows"].get("FII", {})
        log.info("FII index options: CE net %+,.0f | PE net %+,.0f | bias %+,.0f",
                 fii.get("ce_net", 0), fii.get("pe_net", 0), fii.get("opt_bias", 0))
        log.info("Stored=%s · history now %d day(s)", stored, len(load_history()))
        return 0

    # A public holiday looks the same as a genuine outage from here, so say what
    # was actually observed rather than guessing which one it was.
    log.error("FII/DII fetch failed for %s: %s", target, snap["error"])
    _telegram(f"⚠️ FII/DII fetch failed for {target}\n{snap['error']}\n\n"
              "If it was a trading day, NSE may have published late or changed the "
              "file. Re-run: python scripts/fetch_fii_dii.py " + str(target))
    return 1


if __name__ == "__main__":
    sys.exit(main())
