# scripts/analyze_dual_confirmation.py
# Runs the exact same Pinpoint engine used live on page 27 / page 24
# (analytics.reversal_backtest.dual_confirmation_daily_labels +
# dual_confirmation_scan) against a CSV of real daily OHLC data, so results
# here are directly comparable to what the app shows - no separate logic.
#
# CSV must have a date column (any common name/format) plus open/high/low/close
# (case-insensitive). Usage:
#   python3 scripts/analyze_dual_confirmation.py path/to/nifty_daily.csv

import sys
import pandas as pd

sys.path.insert(0, ".")

from analytics import reversal_backtest as rb

DATE_COL_CANDIDATES = ("date", "datetime", "timestamp", "Date", "Datetime")


def load_daily(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    date_col = next((c for c in df.columns if c.strip().lower() in
                     [d.lower() for d in DATE_COL_CANDIDATES]), df.columns[0])
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col)
    return df


def main():
    if len(sys.argv) < 2:
        print("usage: python3 scripts/analyze_dual_confirmation.py <csv_path>")
        sys.exit(1)

    daily = load_daily(sys.argv[1])
    print(f"Loaded {len(daily)} rows: {daily.index.min().date()} -> {daily.index.max().date()}\n")

    # Same defaults as the live page 27 section / page 24 Pinpoint mode.
    labels = rb.dual_confirmation_daily_labels(daily)
    scan = rb.dual_confirmation_scan(daily)

    fall_eps = rb.find_fall_episodes_daily(daily, fall_1d_pct=0.0, fall_2d_pct=1e9,
                                           merge_gap_days=1, require_green_confirmation=False)
    rise_eps = rb.find_rise_episodes_daily(daily, rise_1d_pct=0.0, rise_2d_pct=1e9,
                                           merge_gap_days=1, require_red_confirmation=False)

    counts = labels["label"].value_counts()
    n_days = len(labels)
    n_triggers = int(counts.get("PUT_ONLY", 0) + counts.get("CALL_ONLY", 0) + counts.get("BOTH", 0))
    years = (daily.index.max() - daily.index.min()).days / 365.25

    print("=== Episodes found (before confirmation) ===")
    print(f"Fall episodes (candidate downswings): {len(fall_eps)}")
    print(f"Rise episodes (candidate upswings):   {len(rise_eps)}\n")

    print("=== Trigger frequency (after 0.25% bounce/pullback confirmation) ===")
    for lbl in ["PUT_ONLY", "CALL_ONLY", "BOTH", "NEITHER"]:
        n = int(counts.get(lbl, 0))
        print(f"  {lbl:10s} n={n:4d}  ({n / n_days * 100:.1f}% of days)")
    print(f"\n  Total triggers (PUT_ONLY+CALL_ONLY+BOTH): {n_triggers} over {years:.1f} years "
          f"=> ~{n_triggers / years:.1f}/year, ~1 every {365.25 * years / max(n_triggers, 1):.0f} days")

    print("\n=== Sample trigger days (first 5 PUT_ONLY, first 5 CALL_ONLY) ===")
    for side, lbl in [("PUT_ONLY (bounce off a running low)", "PUT_ONLY"),
                      ("CALL_ONLY (pullback off a running high)", "CALL_ONLY")]:
        print(f"\n-- {side} --")
        sub = labels[labels["label"] == lbl].head(5)
        anchor_col = "anchor_low" if lbl == "PUT_ONLY" else "anchor_high"
        for date, row in sub.iterrows():
            print(f"  {date.date()}  close={row['close']:.1f}  {anchor_col}={row[anchor_col]:.1f}")

    print("\n=== Forward safety (touch-rate) by bucket ===")
    print(scan.to_string(index=False))

    print("\n=== Same-day, no-merge, no-anchor scan (low side) ===")
    print("If TODAY's close sits X% above TODAY's own low, does TODAY's own low")
    print("hold for the next 3/5/10 days? No episode-merging, no running anchor.")
    print(rb.same_day_bounce_scan(daily).to_string(index=False))

    print("\n=== Same-day, no-merge, no-anchor scan (high side) ===")
    print("If TODAY's close sits X% below TODAY's own high, does TODAY's own high")
    print("hold for the next 3/5/10 days?")
    print(rb.same_day_pullback_scan(daily).to_string(index=False))

    out_path = sys.argv[1].rsplit(".", 1)[0] + "_pinpoint_labels.csv"
    labels.to_csv(out_path)
    print(f"\nFull per-day label table written to {out_path}")


if __name__ == "__main__":
    main()
