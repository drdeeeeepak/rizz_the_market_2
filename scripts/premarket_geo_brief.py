# scripts/premarket_geo_brief.py
# Pre-market scan: re-checks last night's EOD watchlist against Gift Nifty direction.
# Runs at 9:00am IST (3:30 UTC). Outputs a filtered "act today" list with trade levels.
#
# Usage:
#   python scripts/premarket_geo_brief.py

import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

WATCHLIST_DIR = Path("data/watchlists")
BRIEF_DIR     = Path("data/watchlists")


def get_gift_nifty_direction(kite) -> dict:
    """
    Fetch Gift Nifty to determine pre-market bias.
    Returns {"ltp": float, "prev_close": float, "gap_pct": float, "bias": str}
    """
    from config import GIFT_NIFTY_TOKEN
    try:
        quote = kite.quote([GIFT_NIFTY_TOKEN])
        data  = quote.get(GIFT_NIFTY_TOKEN, {})
        ltp   = float(data.get("last_price", 0) or 0)
        prev  = float((data.get("ohlc") or {}).get("close", 0) or 0)
        gap   = ((ltp - prev) / prev * 100) if prev > 0 else 0
        if gap >= 0.3:
            bias = "BULLISH"
        elif gap <= -0.3:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"
        return {"ltp": ltp, "prev_close": prev, "gap_pct": round(gap, 2), "bias": bias}
    except Exception as e:
        log.warning("Gift Nifty fetch failed: %s", e)
        return {"ltp": 0, "prev_close": 0, "gap_pct": 0, "bias": "UNKNOWN"}


def load_eod_watchlist() -> list[dict]:
    """Load yesterday's or today's EOD watchlist JSON."""
    for delta in (0, 1):
        d    = date.today() - timedelta(days=delta)
        path = WATCHLIST_DIR / f"{d.strftime('%Y-%m-%d')}_eod.json"
        if path.exists():
            with open(path) as f:
                wl = json.load(f)
            log.info("Loaded EOD watchlist: %s (%d stocks)", path, len(wl))
            return wl
    log.warning("No EOD watchlist found for today or yesterday.")
    return []


def build_brief(eod_list: list[dict], market: dict) -> list[dict]:
    """
    Filter EOD watchlist against Gift Nifty direction.
    - BULLISH gap: all stocks VALID
    - NEUTRAL: all VALID but flag caution on smallcap
    - BEARISH gap: only nifty50/nifty_next VALID; rest SKIP
    """
    brief = []
    for item in eod_list:
        seg    = item.get("segment", "midcap")
        action = "VALID"

        if market["bias"] == "BEARISH":
            if seg not in ("nifty50", "nifty_next"):
                action = "SKIP — bearish gap, avoid midcap/smallcap"

        note = ""
        if item.get("ep_pivot"):
            note = "EP Pivot — strong signal, gap-up continuation likely"
        elif market["bias"] == "BEARISH" and action == "VALID":
            note = "Large-cap only — bearish gap, tighter position"

        brief.append({
            **item,
            "action":      action,
            "market_bias": market["bias"],
            "gift_gap_pct":market["gap_pct"],
            "note":        note,
        })

    brief.sort(key=lambda x: (0 if x["action"] == "VALID" else 1,
                               -x.get("conviction_score", 0),
                               -x.get("vol_mult", 0)))
    return brief


def main():
    from data.kite_client import get_kite_action

    kite   = get_kite_action()
    market = get_gift_nifty_direction(kite)
    log.info("Gift Nifty: %.2f%% gap | Bias: %s", market["gap_pct"], market["bias"])

    eod_list = load_eod_watchlist()
    if not eod_list:
        log.info("No EOD watchlist to process — nothing to save.")
        return

    brief = build_brief(eod_list, market)

    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    today     = date.today().strftime("%Y-%m-%d")
    out_path  = BRIEF_DIR / f"{today}_premarket.json"
    with open(out_path, "w") as f:
        json.dump(brief, f, indent=2, default=str)

    valid = sum(1 for x in brief if x["action"] == "VALID")
    log.info("Pre-market brief saved: %s | %d VALID / %d total",
             out_path, valid, len(brief))


if __name__ == "__main__":
    main()
