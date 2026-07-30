# pages/33_RSI_Leadtime_Backtest.py
#
# Answers one question: do the 3 hourly-RSI signal systems on page 32 (RSI Fade
# 75/25, Pure Divergence, HL/LH Pivot Breakout) give useful early warning before
# a live Iron Condor anchor roll/breach event — or is a same-direction signal
# noise relative to what actually threatens a sold strike?
#
# data/rolled_positions.json has never existed in this repo (checked across all
# branches) and its `history` field is wiped every Tuesday by design — there is
# no persisted multi-cycle log of roll events to read. So roll/breach events are
# RECONSTRUCTED here by replaying the real production rule (Tuesday hard reset +
# check_roll_event mid-week, from data/rolled_positions.py — 2.5% adverse /
# 1.8% favorable drift) over historical daily closes, then joined against the 3
# systems' real historical signal-firing timestamps on hourly candles. See
# analytics/strike_survival_backtest.py for the actual backtest logic.

import importlib

import pandas as pd
import streamlit as st

from data.live_fetcher import get_nifty_daily, get_nifty_1h_extended
from analytics import strike_survival_backtest as ssb

try:
    importlib.reload(ssb)
except Exception:
    pass

st.set_page_config(page_title="P33 · RSI Lead-Time Backtest", layout="wide")

st.title("RSI Signal Lead-Time vs Strike Survival")
st.caption(
    "Joint backtest: for every reconstructed BOOK LOSS / BOOK PROFIT roll event, did a "
    "same-direction signal from RSI Fade 75/25, Pure Divergence, or Pivot Breakout fire "
    "beforehand — and how much lead time did it actually give? Plus each system's "
    "false-positive rate (fired, but no matching event followed)."
)

with st.expander("⚠️ How events are reconstructed, and what this can't tell you", expanded=False):
    st.markdown("""
- **No persisted event log exists.** `data/rolled_positions.json` has never been committed to
  this repo, and its `history` field is cleared every Tuesday (`set_expiry_anchor`) even once
  it exists — so there's no multi-cycle archive to read from directly.
- **Events are reconstructed instead** by replaying the exact live functions from
  `data/rolled_positions.py` (`check_roll_event`, `rolled_strikes`) over historical daily
  closes: Tuesday = hard anchor reset, any other day = check 2.5% loss / 1.8% favorable drift
  against the current anchor, re-anchor on any event. Same approach `analytics/backtest.py`
  already uses for roll-threshold scanning — this just keeps the per-event dates instead of
  only cycle-level aggregates.
- **Direction mapping:** `CE_LOSS` / `PE_PROFIT` both come from an **UP** move (threatens the
  short CALL / benefits the short PUT). `PE_LOSS` / `CE_PROFIT` come from a **DOWN** move.
  A signal is scored as a "hit" only if it fired in the **same direction** as the event within
  the lookback window below.
- **LOSS events are the actual threat** (≥2.5% adverse drift — your sold strike is under
  pressure). **PROFIT events are a roll opportunity, not a threat** (≥1.8% favorable drift) —
  shown separately, don't read them as "danger."
- **No option premium/IV data anywhere in this app** (Kite gives a live chain snapshot only,
  never historical option prices) — this is a spot-only survival/lead-time test, not a P&L
  backtest.
- One sample period, spot-only, reconstructed rather than logged live — read the numbers as a
  real signal, not a large-sample guarantee.
""")

c1, c2, c3 = st.columns(3)
with c1:
    hourly_days = st.slider("Hourly lookback (calendar days, up to ~4 years)", 180, 1460, 1460, 30,
                            key="p33_hourly_days")
with c2:
    lookback_days = st.slider("Lead-time search window (trading days before event)", 1, 15, 5, 1,
                              key="p33_lookback_days")
with c3:
    lookahead_days = st.slider("False-positive window (trading days after signal)", 1, 15, 5, 1,
                               key="p33_lookahead_days")

st.caption(
    f"A signal counts as a 'hit' if it fired in the matching direction within "
    f"{lookback_days} trading days before an event. A signal counts as a 'false positive' if "
    f"no matching-direction event of that severity followed within {lookahead_days} trading days. "
    f"Hourly history is fetched in chunks (Kite caps a single 60-minute call at ~400 days) — at "
    f"1460 days that's several sequential API calls, so this can take a minute. If Kite doesn't "
    f"actually retain 4 years of 60-minute candles, you'll get however much it has, not an error."
)

if st.button("▶ Run joint lead-time backtest", type="primary", key="p33_run"):
    with st.spinner(f"Fetching up to {hourly_days} days of daily + hourly Nifty history "
                    f"(chunked for hourly) and running the joint backtest…"):
        daily = get_nifty_daily(days=hourly_days + 60)
        hourly = get_nifty_1h_extended(days=hourly_days)
        if daily is None or daily.empty or hourly is None or hourly.empty:
            st.session_state.p33_result = None
            st.session_state.p33_error = True
        else:
            if not isinstance(hourly.index, pd.DatetimeIndex):
                hourly.index = pd.to_datetime(hourly.index)
            st.session_state.p33_result = ssb.joint_lead_time_backtest(
                daily, hourly, lookback_days=lookback_days, lookahead_days=lookahead_days)
            st.session_state.p33_error = False
            st.session_state.p33_coverage = dict(
                daily_n=len(daily), daily_start=daily.index[0], daily_end=daily.index[-1],
                hourly_n=len(hourly), hourly_start=hourly.index[0], hourly_end=hourly.index[-1],
            )

if st.session_state.get("p33_error"):
    st.error("Could not fetch Nifty history (daily or hourly came back empty). "
            "Log in via Home → Kite, then retry.")

result = st.session_state.get("p33_result")

if result is not None:
    cov = st.session_state.p33_coverage
    st.success(
        f"Daily: {cov['daily_n']} candles ({cov['daily_start']:%d %b %Y} → {cov['daily_end']:%d %b %Y}) · "
        f"Hourly: {cov['hourly_n']} candles ({cov['hourly_start']:%d %b %Y} → {cov['hourly_end']:%d %b %Y})"
    )

    events, signals, detail = result["events"], result["signals"], result["detail"]
    loss_stats, profit_stats = result["loss_stats"], result["profit_stats"]

    st.divider()
    st.header("Reconstructed roll/breach events")
    if events.empty:
        st.warning("No roll events reconstructed in this window — try a longer hourly lookback.")
    else:
        n_loss = int((events["severity"] == "LOSS").sum())
        n_profit = int((events["severity"] == "PROFIT").sum())
        st.caption(f"{len(events)} total events reconstructed · {n_loss} BOOK LOSS (threat) · "
                  f"{n_profit} BOOK PROFIT (roll opportunity)")
        show_cols = ["date", "event", "severity", "direction", "drift_pct", "eod_close",
                    "anchor_before", "ce_strike", "pe_strike"]
        st.dataframe(events[show_cols], use_container_width=True, hide_index=True)
        st.download_button("⬇ Download events CSV", events[show_cols].to_csv(index=False).encode("utf-8"),
                           file_name="reconstructed_roll_events.csv", mime="text/csv", key="p33_dl_events")

    st.divider()
    st.header("1. BOOK LOSS — does a signal warn you before your strike is actually threatened?")
    st.caption("This is the headline question: a hit here means a same-direction signal fired "
              "before an adverse ≥2.5% breach. n_events excludes events too close to the start "
              "of the hourly window to fairly search for a prior signal.")
    if loss_stats.empty:
        st.warning("No BOOK LOSS events in the usable window — nothing to score.")
    else:
        st.dataframe(loss_stats, use_container_width=True, hide_index=True)
        st.download_button("⬇ Download LOSS stats CSV", loss_stats.to_csv(index=False).encode("utf-8"),
                           file_name="loss_leadtime_stats.csv", mime="text/csv", key="p33_dl_loss")

        best = loss_stats.sort_values(["hit_rate_pct", "n_events"], ascending=False).iloc[0]
        st.markdown(
            f"**Best hit-rate in this run:** {best['system']} ({best['direction']} signals) — "
            f"{best['hit_rate_pct']:.0f}% hit rate on {int(best['n_events'])} LOSS event(s), "
            f"median lead time {best['lead_hours_median']:.0f}h "
            f"(~{best['lead_calendar_days_median']:.1f} calendar days) when it fired, "
            f"but {best['false_positive_rate_pct']:.0f}% of its {int(best['n_signals_fired'])} "
            f"{best['direction']}-direction signals overall were false positives (fired, no "
            f"matching LOSS event followed within {lookahead_days} trading days)."
            if pd.notna(best.get("hit_rate_pct")) else "No usable comparison — too few events."
        )

    st.divider()
    st.header("2. BOOK PROFIT — informational (roll opportunity, not a threat)")
    st.caption("Same mechanics, scored against favorable ≥1.8% drift events instead. Not a "
              "danger signal — shown for completeness since the request asked for both event types.")
    if profit_stats.empty:
        st.warning("No BOOK PROFIT events in the usable window — nothing to score.")
    else:
        st.dataframe(profit_stats, use_container_width=True, hide_index=True)
        st.download_button("⬇ Download PROFIT stats CSV", profit_stats.to_csv(index=False).encode("utf-8"),
                           file_name="profit_leadtime_stats.csv", mime="text/csv", key="p33_dl_profit")

    st.divider()
    st.header("3. Per-event detail — the actual join")
    st.caption("One row per usable event, with each system's most recent matching-direction "
              "signal (if any) and the exact lead time in hours.")
    if detail.empty:
        st.warning("No usable events to join against signals.")
    else:
        st.dataframe(detail, use_container_width=True, hide_index=True)
        st.download_button("⬇ Download per-event detail CSV", detail.to_csv(index=False).encode("utf-8"),
                           file_name="event_signal_detail.csv", mime="text/csv", key="p33_dl_detail")

    st.divider()
    st.header("Raw signal log (all 3 systems)")
    with st.expander(f"All {len(signals)} signals fired over this window", expanded=False):
        st.dataframe(signals, use_container_width=True, hide_index=True)
        st.download_button("⬇ Download all signals CSV", signals.to_csv(index=False).encode("utf-8"),
                           file_name="all_rsi_signals.csv", mime="text/csv", key="p33_dl_signals")
else:
    st.info("Set the windows above and click Run.")
