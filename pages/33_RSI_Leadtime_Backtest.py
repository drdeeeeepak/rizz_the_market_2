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
import importlib.util

import pandas as pd
import streamlit as st

# Styler.background_gradient needs matplotlib. Resolve once here rather than
# per-render — see the note at the key-distances table for why try/except fails.
_HAS_MPL = importlib.util.find_spec("matplotlib") is not None

import data.live_fetcher as _lf
from analytics import strike_survival_backtest as ssb

try:
    importlib.reload(_lf)
    importlib.reload(ssb)
except Exception:
    pass

get_nifty_daily = _lf.get_nifty_daily
get_nifty_1h_extended = _lf.get_nifty_1h_extended

st.set_page_config(page_title="P33 · RSI Lead-Time Backtest", layout="wide")

st.title("RSI Signals vs Iron Condor Strike Survival")
st.caption(
    "Two different questions about the same 3 hourly-RSI systems (RSI Fade 75/25, Pure "
    "Divergence, HL/LH Pivot Breakout). **Q1 — strike tightening:** on the day a bearish "
    "signal fires, is the upside contained enough to sell the CALL closer than routine (and "
    "vice versa for the PUT)? **Q2 — early warning:** does a signal give useful lead time "
    "before a roll/breach event? Q1 is the more useful question; Q2 was answered 'no'."
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

# ══════════════════════════════════════════════════════════════════════════════
# Q1 — STRIKE TIGHTENING: sell closer on a signal day?
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.header("Q1 · Can I sell CLOSER on the day a signal fires?")
st.caption(
    "The rule under test: **a bearish signal fires today → the upside is capped → sell the "
    "CALL closer than routine.** Mirror for the PUT on a bullish signal. Entry is triggered "
    "BY THE SIGNAL — every day a signal is generated is an entry, anchored at that day's "
    "close, then checked over the next N sessions on a closing basis. Note this is an easier "
    "bar than Q2: for a sold CALL, the market falling AND going sideways both count as safe."
)

# Exit is expiry-anchored (always a Tuesday), and never into an expiry closer
# than the mode's minimum — a 1-2 session Tuesday is not a trade worth writing.
# "near" = first Tuesday >=5 sessions out -> 5-9 sessions held.
# "far"  = first Tuesday >=10 sessions out -> 10-14 sessions held.
Q1_MODES = (("near", "Near expiry (min 5 sessions → 5-9 held)"),
            ("far", "Biweekly (min 10 sessions → 10-14 held)"))

q1a, q1b = st.columns(2)
with q1a:
    q1_days = st.slider("History (calendar days)", 180, 1460, 1460, 30, key="p33_q1_days")
with q1b:
    # Defaults are what is actually TRADED (CALL 3.0 / PUT 3.5), which is not what
    # rolled_positions.py computes for pg02 (3.5 / 4.0 via anchor x 1.035 / x 0.960).
    # Deliberate: this scan must be scored against the real position, and pg02 is
    # a separate open question the user has parked.
    q1_call = st.number_input("Routine CALL % OTM", 1.0, 8.0, 3.0, 0.25, key="p33_q1_call")
    q1_put = st.number_input("Routine PUT % OTM", 1.0, 8.0, 3.5, 0.25, key="p33_q1_put")

st.caption(
    "Entry on the signal day, exit **at Tuesday expiry**, never into an expiry closer than "
    "the mode's minimum — a 1-2 session Tuesday is no trade (no premium, expiry gamma), so "
    "it rolls to the next one. Near holds 5-9 sessions, biweekly 10-14; both run in one click. "
    "Hold length still varies with entry weekday (Tue→5, Mon→6, Fri→7, Thu→8, Wed→9), and "
    "that is a trap: a signal firing on the short-hold weekdays would post a lower breach "
    "rate purely from carrying less time. So the verdict uses a **weekday-adjusted** p-value "
    "(Cochran-Mantel-Haenszel), which holds hold length constant. A big gap between it and "
    "the raw p-value means the raw number was mostly time, not skill."
)

if st.button("▶ Run Q1 — strike-tightening scan (near + biweekly expiry)", type="primary",
             key="p33_q1_run"):
    with st.spinner("Fetching history and testing signal-day entries to Tuesday expiry…"):
        _daily = get_nifty_daily(days=q1_days + 60)
        _hourly = get_nifty_1h_extended(days=q1_days)
        if _daily is None or _daily.empty or _hourly is None or _hourly.empty:
            st.session_state.p33_q1 = None
            st.session_state.p33_q1_err = True
        else:
            if not isinstance(_hourly.index, pd.DatetimeIndex):
                _hourly.index = pd.to_datetime(_hourly.index)
            st.session_state.p33_q1 = {
                m: ssb.conditional_strike_distance_scan(
                    _daily, _hourly, expiry_mode=m,
                    routine_call_pct=float(q1_call), routine_put_pct=float(q1_put))
                for m, _ in Q1_MODES}
            st.session_state.p33_q1_err = False

if st.session_state.get("p33_q1_err"):
    st.error("Could not fetch Nifty history. Log in via Home → Kite, then retry.")

_q1all = st.session_state.get("p33_q1")
if _q1all:
    _tabs = st.tabs([lbl for _, lbl in Q1_MODES])
    for _tab, (_m, _lbl) in zip(_tabs, Q1_MODES):
        _q1 = _q1all[_m]
        with _tab:
            if _q1["equal_risk"].empty:
                st.warning("Not enough data to score — try a longer history window.")
                continue
            st.success(f"{_q1['n_entries']} entry days · exit at {_lbl}")

            st.markdown("**Verdict — is a signal day actually safer at your routine distance?**")
            st.caption("Trust `p_value_weekday_adjusted` over `p_value_on_vs_off` — the raw "
                      "one can be inflated purely by shorter holds.")
            for _side in ("CALL", "PUT"):
                _sig_name = "bearish" if _side == "CALL" else "bullish"
                st.markdown(f"*{_side} side (tighten on a {_sig_name} signal)*")
                _er = _q1["equal_risk"]
                st.dataframe(_er[_er.side == _side], use_container_width=True, hide_index=True)

            st.markdown("**Hold-length check — is the comparison even fair?**")
            st.caption("If signal days show fewer mean sessions held than non-signal days, "
                      "part of any raw breach advantage is just less time at risk.")
            st.dataframe(_q1["hold_profile"], use_container_width=True, hide_index=True)

            st.markdown("**How close can I actually sell? — breach % at every distance**")
            st.caption("This is the sizing table. Breach % rises steeply as you move "
                      "closer, so a low breach rate at 3% is NOT a licence to sell at 1% — "
                      "read the number at the distance you're actually considering.")
            _b = _q1["breach"]
            _sys = st.selectbox("System", sorted(_b["system"].unique()), key=f"p33_q1_sys_{_m}")
            _sd = st.radio("Side", ["CALL", "PUT"], horizontal=True, key=f"p33_q1_side_{_m}")
            _piv = _b[(_b.system == _sys) & (_b.side == _sd)].pivot_table(
                index="condition", columns="distance_pct", values="breach_pct")
            _key_d = [c for c in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5) if c in _piv.columns]
            st.markdown("*Key distances*")
            # background_gradient needs matplotlib (declared in requirements.txt).
            # It is LAZY — calling it never raises; the ImportError surfaces later
            # when the Styler renders inside st.dataframe, so a try/except around
            # the call is useless. Check the module is importable up front instead.
            _styled = _piv[_key_d].style.format("{:.1f}%")
            if _HAS_MPL:
                _styled = _styled.background_gradient(cmap="RdYlGn_r", axis=None)
            st.dataframe(_styled, use_container_width=True)
            with st.expander("Full distance ladder (1.00% → 4.50%)"):
                st.dataframe(_piv.style.format("{:.1f}%"), use_container_width=True)

            st.markdown("**Cross-test — direction signal, or volatility signal?**")
            st.caption("Every other table pairs a bearish signal only with the CALL side. "
                      "This scores all four pairings. If a bearish signal makes the CALL "
                      "safer but leaves the PUT no better (or worse), it reads DIRECTION — "
                      "tighten one leg. If BOTH sides get safer, it reads VOLATILITY — the "
                      "right move is tightening the whole condor. `delta_pct` is signal minus "
                      "non-signal breach: negative = safer on signal days.")
            _c = _q1["cross"]
            if _c.empty:
                st.info("No cross-test rows.")
            else:
                _cr = _c[(_c.system == _sys) & _c.at_routine][
                    ["signal", "side", "pairing", "n_signal_on", "breach_on_pct",
                     "breach_off_pct", "delta_pct"]]
                st.dataframe(_cr, use_container_width=True, hide_index=True)

            st.markdown("**Worst adverse move over the hold** (percentiles, % from entry close)")
            st.dataframe(_q1["excursion"], use_container_width=True, hide_index=True)
            st.download_button(f"⬇ Download Q1 breach table CSV ({_m})",
                               _b.to_csv(index=False).encode("utf-8"),
                               file_name=f"q1_strike_tightening_breach_{_m}.csv",
                               mime="text/csv", key=f"p33_dl_q1_{_m}")

    # combined export so both expiries come back in one file
    _parts = []
    for _m, _lbl in Q1_MODES:
        _er = _q1all[_m]["equal_risk"]
        if not _er.empty:
            _parts.append(_er.assign(expiry=_m))
        _hp = _q1all[_m]["hold_profile"]
    if _parts:
        _combined = pd.concat(_parts, ignore_index=True)
        st.download_button("⬇ Download BOTH expiries — verdict table (send me this one)",
                           _combined.to_csv(index=False).encode("utf-8"),
                           file_name="q1_verdict_both_expiries.csv", mime="text/csv",
                           key="p33_dl_q1_both", type="primary")
        _hpc = pd.concat([_q1all[m]["hold_profile"].assign(expiry=m)
                          for m, _ in Q1_MODES if not _q1all[m]["hold_profile"].empty],
                         ignore_index=True)
        if not _hpc.empty:
            st.download_button("⬇ Download hold-length check (send this too)",
                               _hpc.to_csv(index=False).encode("utf-8"),
                               file_name="q1_hold_profile_both_expiries.csv", mime="text/csv",
                               key="p33_dl_q1_hold")
        _cc = pd.concat([_q1all[m]["cross"].assign(expiry=m)
                         for m, _ in Q1_MODES if not _q1all[m]["cross"].empty],
                        ignore_index=True)
        if not _cc.empty:
            st.download_button("⬇ Download CROSS-TEST + full distance ladder (send this too)",
                               _cc.to_csv(index=False).encode("utf-8"),
                               file_name="q1_cross_test_both_expiries.csv", mime="text/csv",
                               key="p33_dl_q1_cross", type="primary")


# ══════════════════════════════════════════════════════════════════════════════
# Q2 — EARLY WARNING (original lead-time test)
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.header("Q2 · Does a signal warn me before a breach? (answered: no)")
st.caption(
    "For every reconstructed BOOK LOSS / BOOK PROFIT roll event, did a same-direction signal "
    "fire beforehand, and with how much lead time? Headline hit rates here look strong but "
    "are an artifact — these signals fire so often that one is 'active' on 25-82% of ALL days, "
    "so hitting an event proves little. Read hit rate against that base rate, not on its own."
)

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
