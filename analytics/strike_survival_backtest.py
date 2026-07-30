# analytics/strike_survival_backtest.py
#
# Joint backtest: do the 3 hourly-RSI signal systems on page 32 (RSI Fade 75/25,
# Pure Divergence, HL/LH Pivot Breakout) give useful lead time before a live
# Iron Condor anchor roll/breach event (data/rolled_positions.py — 2.5% adverse
# drift / 1.8% favorable drift)?
#
# data/rolled_positions.json has never existed in this repo's history, and by
# design its `history` field is wiped every Tuesday (set_expiry_anchor) — so
# there is no persisted multi-cycle log to read events from. Instead, roll
# events are RECONSTRUCTED by replaying the exact production rule (Tuesday hard
# reset + check_roll_event mid-week) over historical daily closes, the same
# approach analytics/backtest.py's _simulate_roll_cycles already uses for
# threshold scanning — this module does the same replay but keeps per-event
# dates (that one only keeps cycle-level touched/loss flags).

import pandas as pd

from data.rolled_positions import check_roll_event, rolled_strikes
from analytics import rsi_fade_backtest as rfb
from analytics.hourly_rsi_pivot import analyze_hourly_rsi

SYSTEMS = ("RSI Fade 75/25", "Pure Divergence", "Pivot Breakout")


def _event_direction(event: str) -> str:
    """CE_LOSS / PE_PROFIT both come from an UP move; PE_LOSS / CE_PROFIT from DOWN."""
    return "UP" if event in ("CE_LOSS", "PE_PROFIT") else "DOWN"


def reconstruct_roll_events(daily: pd.DataFrame) -> pd.DataFrame:
    """
    Replay the LIVE anchor/roll rule over the full daily series: Tuesday hard
    reset (set_expiry_anchor), mid-week check_roll_event + re-anchor on any
    event (eod_update) — bit-for-bit the production functions, not a
    reimplementation, so this can't drift from the real rule.

    Returns one row per roll event with date, event, eod_close, anchor_before,
    drift_pct, direction (UP/DOWN), severity (LOSS/PROFIT), ce_strike, pe_strike.
    EXPIRY_ANCHOR resets aren't events (nothing was threatened) but drive anchor.
    """
    d = daily.copy()
    d.columns = [c.lower() for c in d.columns]
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    d = d.sort_index()

    events = []
    anchor = None
    ce_strike = pe_strike = None
    for ts, row in d.iterrows():
        close = float(row["close"])
        if ts.weekday() == 1:                       # Tuesday — hard reset
            anchor = close
            ce_strike, pe_strike = rolled_strikes(anchor)
            continue
        if anchor is None:
            continue
        ev = check_roll_event(close, anchor)
        if ev is None:
            continue
        drift_pct = (close - anchor) / anchor * 100
        calc_ce, calc_pe = rolled_strikes(close)
        if ev in ("CE_LOSS", "PE_LOSS"):
            ce_strike, pe_strike = calc_ce, calc_pe
        elif ev == "CE_PROFIT":
            ce_strike = calc_ce
        else:                                        # PE_PROFIT
            pe_strike = calc_pe
        events.append(dict(
            date=ts, event=ev, eod_close=round(close, 2),
            anchor_before=round(anchor, 2), drift_pct=round(drift_pct, 2),
            direction=_event_direction(ev), severity=("LOSS" if "LOSS" in ev else "PROFIT"),
            ce_strike=ce_strike, pe_strike=pe_strike,
        ))
        anchor = close                                # mid-week re-anchor, same as eod_update
    out = pd.DataFrame(events)
    if not out.empty:
        out["event_dt"] = out["date"] + pd.Timedelta(hours=15, minutes=30)  # EOD decision time
    return out


# ── Signal extraction — bar-by-bar direction, one row per firing ──────────────

def _fade_signals(hourly: pd.DataFrame, rsi_period: int = 14) -> pd.DataFrame:
    """RSI Fade 75/25 — same zone-cross rule as page 32's live dashboard
    (touch semantics: fires the bar RSI first crosses INTO the zone).
    SHORT (overbought fade) bets price falls next -> DOWN. LONG -> UP."""
    trades = rfb.simulate_fade_trades(hourly, rsi_period=rsi_period, ob=75.0, os_=25.0,
                                      entry_mode="touch")
    if trades.empty:
        return pd.DataFrame(columns=["ts", "direction", "system"])
    direction = trades["side"].map({"SHORT": "DOWN", "LONG": "UP"})
    return pd.DataFrame({"ts": trades["entry_time"], "direction": direction,
                         "system": "RSI Fade 75/25"})


def _divergence_signals(hourly: pd.DataFrame, rsi_period: int = 14,
                        div_lookback: int = 20, div_min_gap: float = 2.0) -> pd.DataFrame:
    """Bullish divergence -> UP. Bearish divergence -> DOWN."""
    d = rfb.detect_divergence_signals(hourly, rsi_period, div_lookback, div_min_gap)
    fired = d[d["bullish"] | d["bearish"]]
    if fired.empty:
        return pd.DataFrame(columns=["ts", "direction", "system"])
    direction = fired["bullish"].map({True: "UP", False: "DOWN"})
    return pd.DataFrame({"ts": fired.index, "direction": direction.to_numpy(),
                         "system": "Pure Divergence"})


def _pivot_signals(hourly: pd.DataFrame, rsi_period: int = 14, lookback: int = 3) -> pd.DataFrame:
    """BUY (LH broken up) -> UP. SELL (HL broken down) -> DOWN."""
    df_piv, signals = analyze_hourly_rsi(hourly, rsi_period=rsi_period, lookback=lookback)
    if not signals:
        return pd.DataFrame(columns=["ts", "direction", "system"])
    rows = [dict(ts=df_piv.index[s["index"]],
                direction="UP" if s["signal"] == "BUY" else "DOWN",
                system="Pivot Breakout") for s in signals]
    return pd.DataFrame(rows)


def all_signals(hourly: pd.DataFrame, rsi_period: int = 14) -> pd.DataFrame:
    """Every signal from all 3 systems, one row each: ts, direction, system."""
    if hourly is None or hourly.empty:
        return pd.DataFrame(columns=["ts", "direction", "system"])
    parts = [_fade_signals(hourly, rsi_period), _divergence_signals(hourly, rsi_period),
            _pivot_signals(hourly, rsi_period)]
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values("ts").reset_index(drop=True) if not out.empty else out


# ── Joint lead-time / hit-rate / false-positive backtest ──────────────────────

def _trading_day_window(trading_dates: pd.DatetimeIndex, date_pos: dict,
                        center_date, n_days: int, forward: bool):
    """Trading-day-aware window edge — weekends/holidays don't count as lead time,
    since nothing trades on them. `forward=False` looks back n_days trading days
    (for lead-time search), `forward=True` looks ahead (for false-positive check)."""
    i = date_pos.get(pd.Timestamp(center_date).normalize())
    if i is None:
        return None
    j = min(len(trading_dates) - 1, i + n_days) if forward else max(0, i - n_days)
    return trading_dates[j]


def joint_lead_time_backtest(daily: pd.DataFrame, hourly: pd.DataFrame,
                             lookback_days: int = 5, lookahead_days: int = 5,
                             rsi_period: int = 14) -> dict:
    """
    The actual joint test: for every reconstructed roll/breach event, did a
    signal fire in the threatening/matching direction within `lookback_days`
    trading days beforehand, and what was the lead time? For every signal, did
    a matching-direction event follow within `lookahead_days` trading days
    (false-positive check)?

    Events in the first `lookback_days` trading days of the hourly window are
    dropped from lead-time stats (left-censored — there isn't enough prior
    hourly history to fairly search for a signal).

    Returns dict with:
      events        — full reconstructed event log (all severities/directions)
      signals       — every signal fired, all 3 systems
      detail        — one row per (usable) event x each system's matched signal
                      (ts, lead_hours — raw calendar hours, or None if no hit)
      loss_stats    — per-system hit-rate/lead-time/false-positive, LOSS events only
                      (the actual "is my strike threatened" question)
      profit_stats  — same, PROFIT events only (informational — roll opportunity,
                      not a threat)
    """
    events = reconstruct_roll_events(daily)
    sigs = all_signals(hourly, rsi_period)
    result = dict(events=events, signals=sigs, detail=pd.DataFrame(),
                 loss_stats=pd.DataFrame(), profit_stats=pd.DataFrame())
    if events.empty or sigs.empty:
        return result

    trading_dates = pd.DatetimeIndex(sorted(pd.Series(daily.index).dt.normalize().unique()))
    date_pos = {d: i for i, d in enumerate(trading_dates)}

    hourly_start = pd.Timestamp(hourly.index.min()).normalize()
    safe_start_idx = date_pos.get(hourly_start, 0) + lookback_days
    usable_events = events[events["date"].apply(
        lambda d: date_pos.get(pd.Timestamp(d).normalize(), -1) >= safe_start_idx
        and pd.Timestamp(d).normalize() <= pd.Timestamp(hourly.index.max()).normalize()
    )].copy()

    # ── per-event: most recent same-direction signal per system within lookback ──
    detail_rows = []
    for _, ev in usable_events.iterrows():
        win_start = _trading_day_window(trading_dates, date_pos, ev["date"], lookback_days, forward=False)
        row = dict(date=ev["date"], event=ev["event"], severity=ev["severity"],
                  direction=ev["direction"], drift_pct=ev["drift_pct"])
        for system in SYSTEMS:
            cand = sigs[(sigs["system"] == system) & (sigs["direction"] == ev["direction"]) &
                       (sigs["ts"] >= win_start) & (sigs["ts"] <= ev["event_dt"])]
            if cand.empty:
                row[f"{system}_signal_ts"] = None
                row[f"{system}_lead_hours"] = None
            else:
                sig_ts = cand["ts"].max()
                lead_hours = (ev["event_dt"] - sig_ts).total_seconds() / 3600
                row[f"{system}_signal_ts"] = sig_ts
                row[f"{system}_lead_hours"] = round(lead_hours, 1)
        detail_rows.append(row)
    detail = pd.DataFrame(detail_rows)
    result["detail"] = detail

    # ── false positives: signals with no matching event within lookahead ─────────
    # Signals whose forward window would be truncated by the data actually ending
    # (right-censored — not enough days left to fairly judge them) are excluded
    # from both numerator and denominator, mirroring the left-censor guard on events.
    last_idx = len(trading_dates) - 1

    def _fp_rate(system: str, direction: str, severity_filter) -> tuple:
        fired_all = sigs[(sigs["system"] == system) & (sigs["direction"] == direction)]
        if fired_all.empty:
            return 0, 0.0
        fired = fired_all[fired_all["ts"].apply(
            lambda t: (date_pos.get(t.normalize(), -1) + lookahead_days) <= last_idx)]
        if fired.empty:
            return 0, 0.0
        ev_sub = events[(events["direction"] == direction) & severity_filter(events)]
        n_fp = 0
        for ts in fired["ts"]:
            win_end = _trading_day_window(trading_dates, date_pos, ts, lookahead_days, forward=True)
            hit = ((ev_sub["date"] >= ts.normalize()) & (ev_sub["date"] <= win_end)).any()
            if not hit:
                n_fp += 1
        return len(fired), round(n_fp / len(fired) * 100, 1)

    def _severity_stats(severity: str) -> pd.DataFrame:
        rows = []
        sev_events = usable_events[usable_events["severity"] == severity]
        for system in SYSTEMS:
            lead_col = f"{system}_lead_hours"
            for direction in ("UP", "DOWN"):
                dir_events = sev_events[sev_events["direction"] == direction]
                n_events = len(dir_events)
                if n_events == 0:
                    continue
                leads = dir_events.merge(
                    detail[["date", lead_col]], on="date", how="left"
                )[lead_col].dropna() if not detail.empty else pd.Series(dtype=float)
                n_hit = len(leads)
                n_fired, fp_rate = _fp_rate(system, direction, lambda e, s=severity: e["severity"] == s)
                rows.append(dict(
                    system=system, direction=direction, n_events=n_events,
                    n_hit=n_hit, hit_rate_pct=round(n_hit / n_events * 100, 1) if n_events else 0.0,
                    lead_hours_min=round(leads.min(), 1) if n_hit else None,
                    lead_hours_median=round(leads.median(), 1) if n_hit else None,
                    lead_hours_max=round(leads.max(), 1) if n_hit else None,
                    lead_calendar_days_median=round(leads.median() / 24, 1) if n_hit else None,
                    n_signals_fired=n_fired, false_positive_rate_pct=fp_rate,
                ))
        return pd.DataFrame(rows)

    result["loss_stats"] = _severity_stats("LOSS")
    result["profit_stats"] = _severity_stats("PROFIT")
    return result
