#!/usr/bin/env python3
"""
Event Calendar Fetch — runs at 6:00 AM IST daily.
Fetches RBI events, NSE corporate actions, and high-impact economic events.
"""
import sys, json, logging
from pathlib import Path
from datetime import date, timedelta
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

HIGH_IMPACT = ["RBI MPC","Budget","Election","GDP","CPI","IIP","FOMC"]

def main():
    events = _fetch_events()
    (DATA_DIR / "events.json").write_text(json.dumps(events, indent=2, default=str))
    try:
        import pandas as pd
        df = pd.DataFrame(events)
        if not df.empty:
            df.to_parquet(DATA_DIR / "events.parquet", index=False)
    except Exception as e:
        log.warning("Parquet write failed: %s", e)
    log.info("Events saved: %d", len(events))
    _check_near_events(events)


def _fetch_events():
    """Fetch from available sources. Extend with real API integrations."""
    events = []
    today = date.today()
    # Placeholder structure — integrate with:
    # - NSE corporate actions API
    # - RBI calendar: https://www.rbi.org.in/Scripts/BS_ViewBulletin.aspx
    # - Investing.com economic calendar
    for i in range(14):
        d = today + timedelta(days=i)
        if d.weekday() >= 5: continue  # skip weekends
        events.append({
            "date": str(d), "event": "", "type": "NONE",
            "impact": "LOW", "sustain_override": False,
        })
    return [e for e in events if e["type"] != "NONE"]


def _check_near_events(events):
    """Telegram alert if high-impact event within 5 days."""
    import os
    token = os.environ.get("TELEGRAM_TOKEN"); chat = os.environ.get("TELEGRAM_CHAT")
    if not token or not chat: return
    today = date.today()
    near = [e for e in events if e.get("impact") == "HIGH"
            and 0 <= (date.fromisoformat(e["date"]) - today).days <= 5]
    if not near: return
    import requests
    msg = "📅 HIGH-IMPACT EVENTS within 5 days:\n" + "\n".join(
        f"  {e['date']}: {e['event']}" for e in near)
    msg += "\n\nSustain rule shortened to 30 min (2 bars) on event day."
    try:
        requests.get(f"https://api.telegram.org/bot{token}/sendMessage",
                    params={"chat_id": chat, "text": msg}, timeout=10)
    except Exception: pass


if __name__ == "__main__":
    main()
