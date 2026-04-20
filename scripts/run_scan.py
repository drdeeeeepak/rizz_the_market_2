# scripts/run_scan.py
# GitHub Actions runner for Geometric Edge scans + EOD OI snapshot.
# Called by all 4 workflow files.
#
# Usage:
#   python scripts/run_scan.py --label 1100
#   python scripts/run_scan.py --label eod --snapshot

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def run_geometric_scan(label: str):
    """Run Geometric Edge scan and save watchlist JSON."""
    from data.kite_client import get_kite_action
    from data.live_fetcher import get_nifty500_breadth
    from analytics.geometric_edge import GeometricEdgeScanner
    from config import TOP_10_NIFTY, TOP_10_TOKENS

    log.info("Starting Geometric Edge scan: %s", label)
    kite    = get_kite_action()
    scanner = GeometricEdgeScanner()

    # ── Fetch universe (top 10 for now; extend to broader universe later) ──
    from datetime import timedelta
    to_date   = date.today()
    from_date = to_date - timedelta(days=400)

    universe = {}
    import pandas as pd
    for sym, token in TOP_10_TOKENS.items():
        try:
            data = kite.historical_data(
                token,
                from_date.strftime("%Y-%m-%d"),
                to_date.strftime("%Y-%m-%d"),
                "day"
            )
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            universe[sym] = df[["open","high","low","close","volume"]]
        except Exception as e:
            log.warning("Failed fetch %s: %s", sym, e)

    # Market health
    breadth_count = get_nifty500_breadth()
    if breadth_count > 350:
        phase = "AGGR_BULL"
    elif breadth_count > 200:
        phase = "SELECTIVE"
    else:
        phase = "BEAR"

    health = {
        "count": breadth_count,
        "phase": phase,
        "run_scans": phase != "BEAR",
        "allocation": {},
    }

    results = scanner.scan_universe(universe, health)
    log.info("Scan found %d results", len(results))

    path = scanner.save_watchlist(results, label)
    log.info("Watchlist saved: %s", path)
    return results


def run_oi_snapshot():
    """
    EOD OI snapshot for Page 10 / 10B.
    Saves near and far expiry chains to parquet for historical analysis.
    """
    from data.kite_client import get_kite_action
    from data.live_fetcher import get_near_far_expiries, get_dte
    from analytics.oi_scoring import OIScoringEngine
    import pandas as pd

    log.info("Running EOD OI snapshot")
    kite = get_kite_action()

    # Nifty spot
    from config import NIFTY_INDEX_TOKEN, OI_STRIKE_STEP, OI_STRIKE_RANGE
    try:
        quote = kite.quote([f"NSE:{NIFTY_INDEX_TOKEN}"])
        spot  = float(quote[str(NIFTY_INDEX_TOKEN)]["last_price"])
    except Exception as e:
        log.error("Spot fetch failed: %s", e)
        return

    near_exp, far_exp = get_near_far_expiries()
    near_dte = get_dte(near_exp)
    far_dte  = get_dte(far_exp)

    def fetch_chain(expiry):
        atm    = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
        strikes= range(atm - OI_STRIKE_RANGE, atm + OI_STRIKE_RANGE + OI_STRIKE_STEP, OI_STRIKE_STEP)
        expiry_str = expiry.strftime("%d%b%Y").upper()
        records = []
        import numpy as np
        for strike in strikes:
            ce_sym = f"NFO:NIFTY{expiry_str}{strike}CE"
            pe_sym = f"NFO:NIFTY{expiry_str}{strike}PE"
            try:
                data = kite.quote([ce_sym, pe_sym])
                ce   = data.get(ce_sym, {})
                pe   = data.get(pe_sym, {})
                records.append({
                    "strike":       strike,
                    "ce_oi":        ce.get("oi", 0),
                    "ce_vol":       ce.get("volume", 0),
                    "ce_ltp":       ce.get("last_price", 0),
                    "ce_iv":        ce.get("implied_volatility", 0),
                    "ce_oi_change": ce.get("oi_day_change", 0),
                    "pe_oi":        pe.get("oi", 0),
                    "pe_vol":       pe.get("volume", 0),
                    "pe_ltp":       pe.get("last_price", 0),
                    "pe_iv":        pe.get("implied_volatility", 0),
                    "pe_oi_change": pe.get("oi_day_change", 0),
                })
            except Exception as e:
                log.warning("Strike %s fetch failed: %s", strike, e)
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records).set_index("strike")
        prev_ce = df["ce_oi"] - df["ce_oi_change"]
        prev_pe = df["pe_oi"] - df["pe_oi_change"]
        df["ce_pct_change"] = np.where(prev_ce > 0, df["ce_oi_change"]/prev_ce*100, 0.0)
        df["pe_pct_change"] = np.where(prev_pe > 0, df["pe_oi_change"]/prev_pe*100, 0.0)
        return df

    near_chain = fetch_chain(near_exp)
    far_chain  = fetch_chain(far_exp)

    # Score chains
    oi_eng = OIScoringEngine()
    near_scored = oi_eng.score_chain(near_chain.copy(), near_dte) if not near_chain.empty else pd.DataFrame()
    far_scored  = oi_eng.score_chain(far_chain.copy(),  far_dte)  if not far_chain.empty  else pd.DataFrame()

    # Save to parquet
    os.makedirs("data/parquet", exist_ok=True)
    today = date.today().strftime("%Y-%m-%d")

    if not near_scored.empty:
        near_scored.to_parquet(f"data/parquet/{today}_near_chain.parquet")
        log.info("Near chain saved: %d strikes", len(near_scored))

    if not far_scored.empty:
        far_scored.to_parquet(f"data/parquet/{today}_far_chain.parquet")
        log.info("Far chain saved: %d strikes", len(far_scored))

    # Save summary JSON for home page
    summary = {
        "date":       today,
        "spot":       spot,
        "near_expiry":str(near_exp),
        "far_expiry": str(far_exp),
        "near_dte":   near_dte,
        "far_dte":    far_dte,
        "near_call_wall": int(near_chain["ce_oi"].idxmax()) if not near_chain.empty else 0,
        "near_put_wall":  int(near_chain["pe_oi"].idxmax()) if not near_chain.empty else 0,
        "far_call_wall":  int(far_chain["ce_oi"].idxmax())  if not far_chain.empty  else 0,
        "far_put_wall":   int(far_chain["pe_oi"].idxmax())  if not far_chain.empty  else 0,
    }
    with open("data/parquet/oi_snapshot_latest.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    log.info("OI snapshot complete: %s", summary)


def run_market_health():
    """
    Compute and save Nifty 500 market health (stocks above 200 SMA).
    Runs EOD only — expensive full-universe fetch.
    """
    from data.kite_client import get_kite_action
    import pandas as pd
    from datetime import timedelta

    log.info("Computing market health breadth")
    kite = get_kite_action()

    # Load Nifty 500 instrument tokens (requires instruments file)
    instruments_file = "data/nifty500_tokens.json"
    if not os.path.exists(instruments_file):
        log.warning("Nifty 500 tokens file not found at %s — skipping breadth", instruments_file)
        return

    with open(instruments_file) as f:
        tokens = json.load(f)   # {symbol: token}

    count_above_200 = 0
    total = len(tokens)
    to_date   = date.today()
    from_date = to_date - timedelta(days=250)

    for i, (sym, token) in enumerate(tokens.items()):
        try:
            data = kite.historical_data(
                token,
                from_date.strftime("%Y-%m-%d"),
                to_date.strftime("%Y-%m-%d"),
                "day"
            )
            df = pd.DataFrame(data)
            if len(df) >= 200:
                sma200 = df["close"].tail(200).mean()
                last   = float(df["close"].iloc[-1])
                if last > sma200:
                    count_above_200 += 1
        except Exception:
            pass

        if (i + 1) % 50 == 0:
            log.info("Breadth progress: %d/%d", i+1, total)

    result = {
        "date":          date.today().strftime("%Y-%m-%d"),
        "breadth_count": count_above_200,
        "total":         total,
    }
    os.makedirs("data/parquet", exist_ok=True)
    with open("data/parquet/market_health.json", "w") as f:
        json.dump(result, f, indent=2)
    log.info("Market health: %d/%d above 200 SMA", count_above_200, total)


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Nifty Options Dashboard scan runner")
    parser.add_argument("--label",    required=True,
                        choices=["1100","1330","1515","eod"],
                        help="Scan label")
    parser.add_argument("--snapshot", action="store_true",
                        help="Also run EOD OI snapshot (only for --label eod)")
    parser.add_argument("--health",   action="store_true",
                        help="Also run market health breadth (only for --label eod)")
    args = parser.parse_args()

    try:
        run_geometric_scan(args.label)
    except Exception as e:
        log.error("Geometric scan failed: %s", e)

    if args.snapshot:
        try:
            run_oi_snapshot()
        except Exception as e:
            log.error("OI snapshot failed: %s", e)

    if args.health:
        try:
            run_market_health()
        except Exception as e:
            log.error("Market health failed: %s", e)

    log.info("Scan complete: %s", args.label)


if __name__ == "__main__":
    main()
