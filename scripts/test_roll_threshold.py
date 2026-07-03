# scripts/test_roll_threshold.py
# Synthetic-data sanity checks for the roll-threshold optimizer in
# analytics/backtest.py (_simulate_roll_cycles, roll_threshold_scan,
# best_roll_threshold). No Kite access needed — run with:
#   python3 scripts/test_roll_threshold.py

import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from analytics import backtest as bt

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def make_daily(prices, start="2024-01-02"):
    """Build a daily OHLCV df (business days) from a plain close-price list."""
    idx = pd.bdate_range(start, periods=len(prices), freq="B")
    close = np.array(prices, dtype=float)
    open_ = np.roll(close, 1); open_[0] = close[0]
    high = np.maximum(open_, close)
    low = np.minimum(open_, close)
    vol = np.full(len(prices), 100_000.0)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                        "volume": vol}, index=idx)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Quiet cycle — no move at all → zero events, neither leg touched.
# ══════════════════════════════════════════════════════════════════════════════
# 2024-01-02 is a Tuesday. One flat cycle Tue→Tue (6 business days incl. both Tuesdays).
flat = make_daily([100, 100, 100, 100, 100, 100])
cycles = bt._simulate_roll_cycles(flat, profit_thr=1.8, loss_thr=2.5)
check("flat cycle produces exactly 1 completed cycle", len(cycles) == 1)
if cycles:
    c = cycles[0]
    check("flat cycle: no events", c["n_events"] == 0)
    check("flat cycle: neither leg touched", not c["ce_touched"] and not c["pe_touched"])
    check("flat cycle: no loss event", not c["loss_event"])

# ══════════════════════════════════════════════════════════════════════════════
# 2. One-sided profit move — spot drifts up, crosses +1.8% once, stays under +2.5%
#    → only PE_PROFIT fires (PE re-sold), CE untouched, no loss event.
# ══════════════════════════════════════════════════════════════════════════════
# anchor 100 on Tue. Wed 100.5, Thu 101.0, Fri 101.9 (+1.9% → PE_PROFIT, re-anchors to 101.9),
# Mon 102.5 (+0.59% from new anchor, under 1.8 → no event), Tue 103 (hard reset).
up_one_sided = make_daily([100, 100.5, 101.0, 101.9, 102.5, 103.0])
cycles = bt._simulate_roll_cycles(up_one_sided, profit_thr=1.8, loss_thr=2.5)
check("one-sided up cycle produces 1 completed cycle", len(cycles) == 1)
if cycles:
    c = cycles[0]
    check("one-sided up: exactly 1 event", c["n_events"] == 1)
    check("one-sided up: PE touched (profit re-sell), CE untouched",
          c["pe_touched"] and not c["ce_touched"])
    check("one-sided up: no loss event", not c["loss_event"])

# ══════════════════════════════════════════════════════════════════════════════
# 3. Loss event — spot drifts up past +2.5% → CE_LOSS fires, BOTH legs reset.
# ══════════════════════════════════════════════════════════════════════════════
up_loss = make_daily([100, 100.5, 101.5, 102.6, 103.0, 103.5])   # Fri +2.6% → CE_LOSS
cycles = bt._simulate_roll_cycles(up_loss, profit_thr=1.8, loss_thr=2.5)
check("loss cycle produces 1 completed cycle", len(cycles) == 1)
if cycles:
    c = cycles[0]
    check("loss cycle: loss_event flagged", c["loss_event"])
    check("loss cycle: both legs touched", c["ce_touched"] and c["pe_touched"])

# ══════════════════════════════════════════════════════════════════════════════
# 4. Whipsaw — spot rallies past +1.8% (PE_PROFIT, re-anchors), then reverses
#    and falls past -1.8% from the NEW anchor (CE_PROFIT) → both legs touched
#    in the same cycle, but no loss event.
# ══════════════════════════════════════════════════════════════════════════════
# Thu 102.0 is +2.0% from anchor 100 → PE_PROFIT fires, anchor re-anchors to 102.0.
# Fri 100.1 is -1.86% from the NEW anchor (102.0) → CE_PROFIT fires (stays inside
# the 2.5% loss band: 102.0 * 0.975 = 99.45).
whipsaw = make_daily([100, 100.5, 102.0, 100.1, 100.6, 100.7])
cycles = bt._simulate_roll_cycles(whipsaw, profit_thr=1.8, loss_thr=2.5)
check("whipsaw cycle produces 1 completed cycle", len(cycles) == 1)
if cycles:
    c = cycles[0]
    check("whipsaw: 2 events (PE_PROFIT then CE_PROFIT)", c["n_events"] == 2)
    check("whipsaw: both legs touched", c["ce_touched"] and c["pe_touched"])
    check("whipsaw: no loss event", not c["loss_event"])

# ══════════════════════════════════════════════════════════════════════════════
# 5. roll_threshold_scan / best_roll_threshold — sanity on a longer synthetic
#    random-walk series (many cycles), just checking shape/ordering, not edge.
# ══════════════════════════════════════════════════════════════════════════════
rng = np.random.default_rng(7)
n = 500
rets = rng.normal(0.0002, 0.008, n)
close = 100 * np.exp(np.cumsum(rets))
long_df = make_daily(close.tolist())

scan = bt.roll_threshold_scan(long_df,
                              profit_thrs=(1.0, 1.5, 2.0),
                              loss_thrs=(2.0, 2.5, 3.0))
check("scan returns rows", not scan.empty)
check("scan only keeps loss_thr > profit_thr", (scan["loss_thr"] > scan["profit_thr"]).all())
check("scan sorted by score descending",
      list(scan["score"]) == sorted(scan["score"], reverse=True))

best = bt.best_roll_threshold(scan)
check("best_roll_threshold returns the top row", best.get("score") == scan.iloc[0]["score"])
check("best_roll_threshold on empty scan returns {}", bt.best_roll_threshold(pd.DataFrame()) == {})

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
