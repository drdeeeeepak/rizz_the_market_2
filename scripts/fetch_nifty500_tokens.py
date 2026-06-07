# scripts/fetch_nifty500_tokens.py
# Fetches Kite instrument tokens for all symbols in data/nifty500_symbols.json.
# Saves result to data/nifty500_tokens.json  {symbol: token}
# Run once at setup, then via the monthly-refresh workflow.
#
# Usage:
#   python scripts/fetch_nifty500_tokens.py

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SYMBOLS_FILE = Path("data/nifty500_symbols.json")
TOKENS_FILE  = Path("data/nifty500_tokens.json")


def main():
    from data.kite_client import get_kite_action

    if not SYMBOLS_FILE.exists():
        log.error("data/nifty500_symbols.json not found")
        sys.exit(1)

    with open(SYMBOLS_FILE) as f:
        target_symbols = set(json.load(f))

    log.info("Target: %d symbols", len(target_symbols))

    kite = get_kite_action()
    log.info("Fetching NSE instrument list from Kite...")

    instruments = kite.instruments("NSE")
    log.info("Kite returned %d NSE instruments", len(instruments))

    token_map = {}
    for inst in instruments:
        sym = inst.get("tradingsymbol", "")
        if inst.get("instrument_type") == "EQ" and sym in target_symbols:
            token_map[sym] = inst["instrument_token"]

    matched   = len(token_map)
    unmatched = target_symbols - set(token_map.keys())

    log.info("Matched %d / %d symbols", matched, len(target_symbols))
    if unmatched:
        log.warning("Unmatched symbols (not found in Kite NSE EQ list): %s", sorted(unmatched))

    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKENS_FILE, "w") as f:
        json.dump(token_map, f, indent=2, sort_keys=True)

    log.info("Saved to %s", TOKENS_FILE)


if __name__ == "__main__":
    main()
