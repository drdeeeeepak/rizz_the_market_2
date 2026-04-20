#!/usr/bin/env python3
"""
EOD Compute — runs at 3:35 PM IST Mon-Fri via GitHub Actions.
Fetches Kite EOD data, runs all analytics, writes data/signals.json.
Sends Telegram EOD summary with final strikes.
"""
import sys, os, json, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

def main():
    log.info("EOD compute starting...")
    from data.live_fetcher import (
        get_nifty_spot, get_nifty_daily, get_top10_daily,
        get_india_vix, get_vix_history, get_dual_expiry_chains,
    )
    from analytics.compute_signals import compute_all_signals, save_signals
    from analytics.dow_theory import DowTheoryEngine

    DATA_DIR = Path(__file__).parent.parent / "data"
    DATA_DIR.mkdir(exist_ok=True)

    spot      = get_nifty_spot()
    nifty_df  = get_nifty_daily()
    stock_dfs = get_top10_daily()
    vix_live  = get_india_vix()
    vix_hist  = get_vix_history()

    if spot == 0 and not nifty_df.empty:
        spot = float(nifty_df["close"].iloc[-1])

    chains = get_dual_expiry_chains(spot)
    log.info("Spot: %.0f  VIX: %.2f  Far DTE: %d", spot, vix_live, chains.get("far_dte",7))

    sig = compute_all_signals(nifty_df, stock_dfs, vix_live, vix_hist, chains, spot)
    save_signals(sig)

    # Write breach levels
    dow_eng = DowTheoryEngine()
    dow_sig = dow_eng.signals(nifty_df.copy())
    (DATA_DIR / "breach_levels.json").write_text(json.dumps({
        "put_breach_level":  dow_sig.get("put_breach_level",  0),
        "call_breach_level": dow_sig.get("call_breach_level", 0),
        "dow_structure":     dow_sig.get("dow_structure",     "MIXED"),
        "pivot_high_ref":    dow_sig.get("pivot_high_ref",    0),
        "pivot_low_ref":     dow_sig.get("pivot_low_ref",     0),
        "spot": spot,
    }, indent=2))

    _send_telegram_eod(sig, spot, vix_live)
    log.info("Done. PE short: %s  CE short: %s",
             sig.get("final_put_short"), sig.get("final_call_short"))


def _send_telegram_eod(sig: dict, spot: float, vix: float):
    token = os.environ.get("TELEGRAM_TOKEN"); chat = os.environ.get("TELEGRAM_CHAT")
    if not token or not chat: return
    import requests
    canary = sig.get("canary_level", 0)
    canary_txt = f"🐤 Canary Day{canary} {sig.get('canary_direction','')}" if canary else "✅ No canary"
    msg = (
        f"📊 EOD premiumdecay · Nifty {spot:,.0f}\n"
        f"VIX {vix:.2f} ({sig.get('vix_zone','—')}) · IVP {sig.get('ivp_1yr',0):.0f}\n"
        f"Regime: {sig.get('p2_regime','—')} · {canary_txt}\n"
        f"Skew {sig.get('net_skew',0):+.0f} → {sig.get('p1_ratio','1:1')} · Size {sig.get('size_multiplier',1.0):.0%}\n"
        f"🎯 PE {sig.get('final_put_short',0):,} / CE {sig.get('final_call_short',0):,}\n"
        f"Wings: PE {sig.get('final_put_wing',0):,} / CE {sig.get('final_call_wing',0):,}"
    )
    try:
        requests.get(f"https://api.telegram.org/bot{token}/sendMessage",
                     params={"chat_id": chat, "text": msg}, timeout=10)
    except Exception as e:
        print(f"Telegram failed: {e}")


if __name__ == "__main__":
    main()
