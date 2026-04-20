#!/usr/bin/env python3
"""
Pre-Market Gap Check — runs at 8:45 AM IST Mon-Fri.
Computes Gift Nifty gap (futures-to-futures) and fires Telegram alert if meaningful.
"""
import sys, os, json, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

def main():
    from config import GAP_NO_ACTION, GAP_HEDGE_ATM, GAP_CLOSE_LEG, GAP_CLOSE_ALL
    try:
        gap_pct, gap_pts, direction = _compute_gap()
    except Exception as e:
        log.error("Gap compute failed: %s", e); gap_pct, gap_pts, direction = 0, 0, "UNKNOWN"

    action = "NO_ACTION"
    if abs(gap_pct) >= GAP_CLOSE_ALL:    action = "CLOSE_ALL"
    elif abs(gap_pct) >= GAP_CLOSE_LEG:  action = "CLOSE_SKEWED_LEG"
    elif abs(gap_pct) >= GAP_HEDGE_ATM:  action = "HEDGE_ATM"

    result = {"gap_pct": round(gap_pct,3), "gap_pts": round(gap_pts,1),
              "direction": direction, "action": action}
    (DATA_DIR / "gap_check.json").write_text(json.dumps(result, indent=2))
    log.info("Gap: %.2f%%  %+.0f pts  %s  → %s", gap_pct, gap_pts, direction, action)

    token = os.environ.get("TELEGRAM_TOKEN"); chat = os.environ.get("TELEGRAM_CHAT")
    if token and chat and abs(gap_pct) >= GAP_HEDGE_ATM:
        import requests
        msg = (f"🌅 PRE-MARKET GAP\n"
               f"Gift Nifty gap: {gap_pct:+.2f}% ({gap_pts:+.0f} pts) {direction}\n"
               f"Calibrated action: {action}\n"
               f"Thresholds: 1.5%=hedge · 2.5%=close leg · 3.5%=close all")
        try:
            requests.get(f"https://api.telegram.org/bot{token}/sendMessage",
                        params={"chat_id": chat, "text": msg}, timeout=10)
        except Exception: pass


def _compute_gap():
    """
    Formula: (Gift Nifty 8:45 AM − Nifty Futures prev close) / Futures prev close × 100
    Futures-to-futures eliminates spot-futures basis noise.
    """
    from data.kite_client import get_kite
    kite = get_kite()
    # Fetch Gift Nifty live (approximate via NSE_IFSC instruments)
    # Fetch Nifty front-month futures previous close
    # NOTE: actual instrument tokens need to be set in production
    gift_nifty_live = 0.0  # placeholder — populate from Kite
    nifty_fut_prev  = 0.0  # placeholder
    if nifty_fut_prev == 0:
        return 0.0, 0.0, "UNKNOWN"
    gap_pct = (gift_nifty_live - nifty_fut_prev) / nifty_fut_prev * 100
    gap_pts = gift_nifty_live - nifty_fut_prev
    direction = "UP" if gap_pct > 0 else "DOWN" if gap_pct < 0 else "FLAT"
    return gap_pct, gap_pts, direction


if __name__ == "__main__":
    main()
