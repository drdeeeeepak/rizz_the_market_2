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

import numpy as np
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


# ── Conditional strike-distance backtest ─────────────────────────────────────
#
# Different question from the lead-time test below. That one asked "does a
# signal warn me my strike is about to be BREACHED" (answer: no). This asks
# "when a bearish signal is active, is the UPSIDE contained enough that I can
# sell the CALL closer than routine (and vice versa for the PUT)?" — a strictly
# easier bar, because both a fall AND a flat market leave a sold CALL safe.
#
# Sign convention: a bearish signal (direction "DOWN") is the one that would
# let you tighten the CALL; a bullish signal ("UP") the one that tightens the PUT.

_CALL_SIGNAL_DIR = "DOWN"   # bearish signal → upside capped → tighten CALL
_PUT_SIGNAL_DIR = "UP"      # bullish signal → downside capped → tighten PUT

DEFAULT_DISTANCES = tuple(round(x, 2) for x in
                          [1.0 + 0.25 * i for i in range(15)])   # 1.00% … 4.50%

# Minimum trading sessions to expiry per mode. A position is never written into
# an expiry closer than this — a 1-2 session Tuesday is not a trade worth having
# (no premium, expiry-day gamma), so the scan rolls out to the next Tuesday.
EXPIRY_MIN_SESSIONS = {"near": 5, "far": 10}


def _expiry_index(idx: pd.DatetimeIndex, i: int, min_sessions: int):
    """Index of the Tuesday-expiry session a position opened at `i` runs to,
    skipping any expiry closer than `min_sessions` trading sessions.

    Positions die on a calendar date, so the raw next Tuesday can be 1 session
    away (Monday signal) — which is not a trade worth writing: no premium left
    and expiry-day gamma. So roll forward to the first Tuesday at least
    min_sessions out. With min_sessions=5 that yields 5-9 sessions held
    (Tue entry→5, Mon→6, Fri→7, Thu→8, Wed→9); with 10 it yields 10-14.

    A holiday Tuesday isn't in the index, so we take the last session on or
    before it (Monday), matching compute_anchor_live's holiday handling.
    """
    d0 = idx[i].normalize()
    ahead = (1 - d0.weekday()) % 7 or 7          # Tue=1; always strictly forward
    tue = d0 + pd.Timedelta(days=ahead)
    last = idx[-1]
    while tue <= last:
        j = int(idx.searchsorted(tue, side="right")) - 1
        if j > i and (j - i) >= min_sessions:
            return j
        tue += pd.Timedelta(days=7)
    return None


def conditional_strike_distance_scan(daily: pd.DataFrame, hourly: pd.DataFrame,
                                     horizon_days: int = 5,
                                     distances=DEFAULT_DISTANCES,
                                     rsi_period: int = 14,
                                     routine_call_pct: float = 3.5,
                                     routine_put_pct: float = 4.0,
                                     expiry_mode=None) -> dict:
    """
    Entry is triggered BY THE SIGNAL FIRING, not by the calendar: every day on
    which a tightening signal is generated is an entry day. Anchor = that day's
    close (the price you'd write the strike from, in the EOD workflow the rest
    of this app uses); the forward window is the next `horizon_days` sessions.
    At each candidate strike distance, was the strike breached on a CLOSING
    basis (same basis as the live roll rule)?

    Compared against every other day as the control, so "signal day" vs
    "non-signal day" is one construction measured two ways.

    No lookahead: the forward window starts the session AFTER the entry day,
    and a day counts as a signal day only for signals timestamped that day
    (hourly bars end 15:15, so they all precede the 15:30 close).

    Returns dict with:
      breach   — long-form: system, side, condition, distance_pct, n, n_breach, breach_pct
      excursion— percentiles of the max ADVERSE forward move per system/side/condition
      equal_risk — for each system/side, how much closer you could sell while
                   keeping breach risk at or below the all-days routine baseline
      n_entries, horizon_days
    """
    d = daily.copy()
    d.columns = [c.lower() for c in d.columns]
    if not isinstance(d.index, pd.DatetimeIndex):
        d.index = pd.to_datetime(d.index)
    d = d.sort_index()

    sigs = all_signals(hourly, rsi_period)
    if sigs.empty or len(d) < horizon_days + 2:
        return dict(breach=pd.DataFrame(), excursion=pd.DataFrame(),
                   equal_risk=pd.DataFrame(), hold_profile=pd.DataFrame(),
                   cross=pd.DataFrame(), n_entries=0,
                   horizon_days=horizon_days, expiry_mode=expiry_mode)

    # Days on which each system generated a signal, per direction.
    sig_days = {}
    _sd = sigs.assign(day=sigs["ts"].dt.normalize())
    for (sy, di), g in _sd.groupby(["system", "direction"]):
        sig_days[(sy, di)] = set(g["day"])
    for di in (_CALL_SIGNAL_DIR, _PUT_SIGNAL_DIR):
        per = [sig_days.get((s, di), set()) for s in SYSTEMS]
        sig_days[("ANY of 3", di)] = set().union(*per) if per else set()
        counts = {}
        for st_ in per:
            for day in st_:
                counts[day] = counts.get(day, 0) + 1
        sig_days[("MAJORITY (>=2 of 3)", di)] = {k for k, v in counts.items() if v >= 2}

    hourly_start = pd.Timestamp(hourly.index.min()).normalize()
    hourly_end = pd.Timestamp(hourly.index.max()).normalize()
    close = d["close"].to_numpy()
    idx = d.index

    systems = list(SYSTEMS) + ["ANY of 3", "MAJORITY (>=2 of 3)"]
    records = []      # one row per (entry day, system, side)
    for i in range(len(idx)):
        entry_day = idx[i].normalize()
        # only days actually covered by the hourly signal history are comparable
        if entry_day < hourly_start or entry_day > hourly_end:
            continue
        anchor = float(close[i])
        if anchor <= 0:
            continue

        if expiry_mode:
            j = _expiry_index(idx, i, EXPIRY_MIN_SESSIONS[expiry_mode])
            if j is None or j >= len(d):
                continue
            fwd = close[i + 1: j + 1]
        else:
            if i + horizon_days >= len(d):
                continue
            fwd = close[i + 1: i + 1 + horizon_days]
        if len(fwd) == 0:
            continue
        held = len(fwd)
        up_move = (fwd.max() - anchor) / anchor * 100     # worst case for a sold CALL
        down_move = (anchor - fwd.min()) / anchor * 100   # worst case for a sold PUT

        # One rich row per (entry, system) carrying BOTH forward moves and BOTH
        # signal states, so every pairing — matched and crossed — comes from the
        # same single pass over the data.
        for system in systems:
            records.append(dict(
                entry=entry_day, system=system, sessions_held=held,
                entry_weekday=entry_day.day_name()[:3],
                up_pct=up_move, down_pct=down_move,
                bearish_on=entry_day in sig_days.get((system, _CALL_SIGNAL_DIR), set()),
                bullish_on=entry_day in sig_days.get((system, _PUT_SIGNAL_DIR), set())))

    rich = pd.DataFrame(records)
    if rich.empty:
        return dict(breach=pd.DataFrame(), excursion=pd.DataFrame(),
                   equal_risk=pd.DataFrame(), hold_profile=pd.DataFrame(),
                   cross=pd.DataFrame(), n_entries=0,
                   horizon_days=horizon_days, expiry_mode=expiry_mode)

    # Side-matched view (CALL paired with bearish, PUT with bullish) — the
    # pairing every table below the cross-test uses.
    _keep = ["entry", "system", "sessions_held", "entry_weekday"]
    rec = pd.concat([
        rich[_keep].assign(side="CALL", adverse_pct=rich["up_pct"],
                          signal_on=rich["bearish_on"]),
        rich[_keep].assign(side="PUT", adverse_pct=rich["down_pct"],
                          signal_on=rich["bullish_on"]),
    ], ignore_index=True)

    n_entries = rich["entry"].nunique()

    def _cond_slices(g):
        yield "signal ACTIVE", g[g["signal_on"]]
        yield "no signal", g[~g["signal_on"]]
        yield "ALL days (baseline)", g

    breach_rows, exc_rows = [], []
    for (system, side), g in rec.groupby(["system", "side"]):
        for cond, sub in _cond_slices(g):
            n = len(sub)
            if n == 0:
                continue
            exc_rows.append(dict(
                system=system, side=side, condition=cond, n=n,
                median_pct=round(float(sub["adverse_pct"].median()), 2),
                p75_pct=round(float(sub["adverse_pct"].quantile(0.75)), 2),
                p90_pct=round(float(sub["adverse_pct"].quantile(0.90)), 2),
                p95_pct=round(float(sub["adverse_pct"].quantile(0.95)), 2),
                max_pct=round(float(sub["adverse_pct"].max()), 2)))
            for dist in distances:
                nb = int((sub["adverse_pct"] >= dist).sum())
                breach_rows.append(dict(
                    system=system, side=side, condition=cond, distance_pct=dist,
                    n=n, n_breach=nb, breach_pct=round(nb / n * 100, 1)))

    breach = pd.DataFrame(breach_rows)
    excursion = pd.DataFrame(exc_rows)

    # ── equal-risk: how much closer can you sell and still be no riskier? ──────
    # GUARDED. Naively solving "smallest distance where conditional breach <=
    # baseline breach" reports a fat bogus pickup whenever the baseline breach
    # count is 0 — it just finds another zero and calls it equal risk. Verified
    # against random no-edge data, where the unguarded version claimed a
    # 0.75-1.25% pickup on pure noise. So a pickup is only reported when the
    # baseline actually breached MIN_BREACH_EVENTS times at the routine
    # distance; otherwise there is no risk to be "equal" to and the answer is
    # "not enough breaches to tell", not a number.
    MIN_BREACH_EVENTS = 10
    MIN_SIGNAL_DAYS = 20
    try:
        from scipy.stats import fisher_exact
        _have_scipy = True
    except Exception:
        _have_scipy = False

    eq_rows = []
    for (system, side), g in breach.groupby(["system", "side"]):
        routine = routine_call_pct if side == "CALL" else routine_put_pct
        nearest = min(sorted(set(g["distance_pct"])), key=lambda x: abs(x - routine))
        base_r = g[(g["condition"] == "ALL days (baseline)") & (g["distance_pct"] == nearest)]
        on_r = g[(g["condition"] == "signal ACTIVE") & (g["distance_pct"] == nearest)]
        off_r = g[(g["condition"] == "no signal") & (g["distance_pct"] == nearest)]
        if base_r.empty or on_r.empty or off_r.empty:
            continue
        base_breach_pct = float(base_r["breach_pct"].iloc[0])
        base_breach_n = int(base_r["n_breach"].iloc[0])
        on_n, on_b = int(on_r["n"].iloc[0]), int(on_r["n_breach"].iloc[0])
        off_n, off_b = int(off_r["n"].iloc[0]), int(off_r["n_breach"].iloc[0])

        # signal-ON vs signal-OFF at the routine distance — independent groups,
        # so this is the honest test of whether the signal carries information.
        pval = np.nan
        if _have_scipy and (on_n and off_n):
            try:
                pval = float(fisher_exact([[on_b, on_n - on_b],
                                          [off_b, off_n - off_b]],
                                         alternative="less")[1])
            except Exception:
                pval = np.nan

        # Confounder control. Under expiry-anchored exits the hold length is set
        # by WHICH WEEKDAY you entered on (a Monday signal buys ~1 day of risk
        # before Tuesday expiry, a Wednesday signal ~4-5). So if a signal tends
        # to fire late in the week, it would post a lower breach rate purely
        # from carrying less time — no skill involved. This re-tests within
        # weekday strata (Cochran-Mantel-Haenszel), where hold length is held
        # constant, so only a real effect survives.
        pval_strat = np.nan
        if expiry_mode is not None:
            sub = rec[(rec["system"] == system) & (rec["side"] == side)]
            num = den = 0.0
            obs = 0
            for _wd, gw in sub.groupby("entry_weekday"):
                a = int(((gw["adverse_pct"] >= nearest) & gw["signal_on"]).sum())
                b = int((~gw["signal_on"] & (gw["adverse_pct"] >= nearest)).sum())
                r1 = int(gw["signal_on"].sum())
                r2 = int((~gw["signal_on"]).sum())
                c1 = a + b
                nk = r1 + r2
                if nk < 2 or r1 == 0 or r2 == 0 or c1 == 0 or c1 == nk:
                    continue
                obs += a
                num += r1 * c1 / nk
                den += r1 * r2 * c1 * (nk - c1) / (nk * nk * (nk - 1))
            if den > 0:
                from scipy.stats import chi2 as _chi2
                z2 = (abs(obs - num) - 0.5) ** 2 / den
                # one-sided: only counts if signal days breached LESS than expected
                pval_strat = (float(_chi2.sf(z2, 1)) / 2 if obs < num
                             else 1 - float(_chi2.sf(z2, 1)) / 2)

        enough = base_breach_n >= MIN_BREACH_EVENTS and on_n >= MIN_SIGNAL_DAYS
        closest = pickup = np.nan
        if enough:
            act = g[g["condition"] == "signal ACTIVE"].sort_values("distance_pct")
            ok = act[act["breach_pct"] <= base_breach_pct]
            if not ok.empty:
                closest = float(ok["distance_pct"].min())
                pickup = round(routine - closest, 2)

        # Verdict must fold in significance itself. Reporting a bare "pickup"
        # is how this metric lies: on random no-edge data it happily finds a
        # 0.75-2.00% pickup (verified), and only the p-value exposes it as
        # noise. So a pickup is only ever called real when the signal-on vs
        # signal-off difference clears p<0.05 on its own.
        # Under expiry-anchored exits the weekday-stratified p-value is the
        # honest one — the raw one can be driven purely by hold length.
        # NEVER fall back to the raw p when the stratified one is unavailable:
        # it comes back NaN precisely when the signal fires only on certain
        # weekdays, which is the case where the raw p is MOST confounded. A
        # Friday-only signal with no real edge posts raw p=0.0007 purely because
        # Friday->Tuesday is a 2-session hold vs 3.25 average (verified).
        p_judge = pval_strat if expiry_mode is not None else pval
        confounded = expiry_mode is not None and pd.isna(pval_strat)
        if not enough:
            verdict = f"can't judge (need >={MIN_BREACH_EVENTS} baseline breaches, >={MIN_SIGNAL_DAYS} signal days)"
        elif pd.isna(pickup) or pickup <= 0:
            verdict = "no pickup — signal day is no safer"
        elif confounded:
            verdict = "CONFOUNDED — signal fires on set weekdays; can't separate edge from hold length"
        elif pd.isna(p_judge) or p_judge >= 0.05:
            verdict = f"NOT significant (p={p_judge:.2f}) — treat as noise"
        else:
            verdict = f"significant pickup (p={p_judge:.3f})"

        _s = rec[(rec["system"] == system) & (rec["side"] == side)]
        _hold_on = float(_s[_s["signal_on"]]["sessions_held"].mean()) if _s["signal_on"].any() else np.nan
        _hold_off = float(_s[~_s["signal_on"]]["sessions_held"].mean()) if (~_s["signal_on"]).any() else np.nan

        eq_rows.append(dict(
            system=system, side=side, routine_pct=routine,
            n_signal_on=on_n, breach_on_pct=round(on_b / on_n * 100, 1) if on_n else np.nan,
            n_signal_off=off_n, breach_off_pct=round(off_b / off_n * 100, 1) if off_n else np.nan,
            mean_hold_on=round(_hold_on, 2) if pd.notna(_hold_on) else np.nan,
            mean_hold_off=round(_hold_off, 2) if pd.notna(_hold_off) else np.nan,
            baseline_breach_pct=base_breach_pct, baseline_breach_events=base_breach_n,
            p_value_on_vs_off=round(pval, 4) if pd.notna(pval) else np.nan,
            p_value_weekday_adjusted=round(pval_strat, 4) if pd.notna(pval_strat) else np.nan,
            closest_equal_risk_pct=closest, pickup_pct=pickup, verdict=verdict))
    equal_risk = pd.DataFrame(eq_rows)

    # Hold-length diagnostic — makes the confounder inspectable rather than
    # implicit: if signal days carry systematically fewer sessions to expiry
    # than non-signal days, any raw breach advantage is partly just less time.
    hold_rows = []
    for (system, side), g in rec.groupby(["system", "side"]):
        for cond, sub in (("signal ACTIVE", g[g["signal_on"]]), ("no signal", g[~g["signal_on"]])):
            if sub.empty:
                continue
            hold_rows.append(dict(
                system=system, side=side, condition=cond, n=len(sub),
                mean_sessions_held=round(float(sub["sessions_held"].mean()), 2),
                median_sessions_held=float(sub["sessions_held"].median()),
                pct_entries_Mon=round(float((sub["entry_weekday"] == "Mon").mean() * 100), 1),
                pct_entries_Tue=round(float((sub["entry_weekday"] == "Tue").mean() * 100), 1),
                pct_entries_Wed=round(float((sub["entry_weekday"] == "Wed").mean() * 100), 1),
                pct_entries_Thu=round(float((sub["entry_weekday"] == "Thu").mean() * 100), 1),
                pct_entries_Fri=round(float((sub["entry_weekday"] == "Fri").mean() * 100), 1)))
    hold_profile = pd.DataFrame(hold_rows)

    # ── CROSS-TEST: direction signal, or volatility signal? ───────────────────
    # Every table above pairs a bearish signal only with the CALL side and a
    # bullish signal only with the PUT side, so it can never distinguish these:
    #   DIRECTION  — a bearish signal caps the upside (CALL safer) but leaves or
    #                worsens the downside (PUT no better).
    #   VOLATILITY — a bearish signal precedes a quieter market, so BOTH sides
    #                get safer, and the right response is to tighten the whole
    #                condor rather than one leg.
    # This scores all four pairings, so the two are finally separable.
    cross_rows = []
    for sig_dir, flag in (("bearish", "bearish_on"), ("bullish", "bullish_on")):
        for side, move_col in (("CALL", "up_pct"), ("PUT", "down_pct")):
            pairing = "matched" if ((sig_dir == "bearish") == (side == "CALL")) else "CROSSED"
            for system, g in rich.groupby("system"):
                on, off = g[g[flag]], g[~g[flag]]
                if on.empty or off.empty:
                    continue
                routine = routine_call_pct if side == "CALL" else routine_put_pct
                nearest_d = min(distances, key=lambda x: abs(x - routine))
                for dist in distances:
                    b_on = int((on[move_col] >= dist).sum())
                    b_off = int((off[move_col] >= dist).sum())
                    cross_rows.append(dict(
                        system=system, signal=sig_dir, side=side, pairing=pairing,
                        distance_pct=dist, at_routine=(dist == nearest_d),
                        n_signal_on=len(on), breach_on_pct=round(b_on / len(on) * 100, 1),
                        n_signal_off=len(off), breach_off_pct=round(b_off / len(off) * 100, 1),
                        delta_pct=round(b_on / len(on) * 100 - b_off / len(off) * 100, 1)))
    cross = pd.DataFrame(cross_rows)

    return dict(breach=breach, excursion=excursion, equal_risk=equal_risk,
               hold_profile=hold_profile, cross=cross, n_entries=n_entries,
               horizon_days=horizon_days, expiry_mode=expiry_mode)


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
