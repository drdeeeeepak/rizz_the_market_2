# scripts/test_signal_lab.py
# Synthetic-data sanity checks for analytics/signal_lab.py + analytics/signal_adapters.py.
# No Kite access needed — run with:  python3 scripts/test_signal_lab.py
#
# This is NOT pytest (repo has no test framework) — plain asserts + a pass/fail
# summary, matching the style of the other one-off scripts in scripts/.

import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from analytics import signal_lab as sl
from analytics import signal_adapters as sa

RNG = np.random.default_rng(42)


# ══════════════════════════════════════════════════════════════════════════════
# Synthetic data builders
# ══════════════════════════════════════════════════════════════════════════════

def make_daily(n=520, start_price=22000.0, drift=0.0002, vol=0.009, seed=1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=n, freq="B")
    rets = rng.normal(drift, vol, n)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.roll(close, 1); open_[0] = start_price
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    vol_ = rng.integers(50_000, 500_000, n).astype(float)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol_}, index=idx)
    return df


def make_perfectly_bullish_daily(n=300, start_price=20000.0) -> pd.DataFrame:
    """A monotonic-ish uptrend so directional adapters have an obvious answer
    to get right (used as a sign-convention sanity check, not an edge test)."""
    idx = pd.bdate_range("2023-01-02", periods=n, freq="B")
    close = start_price * (1.0008 ** np.arange(n)) * (1 + RNG.normal(0, 0.0015, n))
    open_ = np.roll(close, 1); open_[0] = start_price
    high = np.maximum(open_, close) * 1.002
    low = np.minimum(open_, close) * 0.998
    vol_ = np.full(n, 200_000.0)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol_}, index=idx)


def make_1h(n_days=250, start_price=22000.0, seed=2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    price = start_price
    for d in pd.bdate_range("2023-01-02", periods=n_days, freq="B"):
        for h in range(6):   # 6 1H candles/session, 09:15 .. 14:15
            ret = rng.normal(0.00003, 0.0015)
            o = price
            c = price * (1 + ret)
            hi = max(o, c) * (1 + abs(rng.normal(0, 0.0008)))
            lo = min(o, c) * (1 - abs(rng.normal(0, 0.0008)))
            ts = d + pd.Timedelta(hours=9, minutes=15) + pd.Timedelta(hours=h)
            rows.append((ts, o, hi, lo, c, rng.integers(1000, 5000)))
            price = c
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"]).set_index("date")
    return df


def make_fut_daily_with_oi(n=400, seed=3) -> pd.DataFrame:
    base = make_daily(n=n, seed=seed)
    rng = np.random.default_rng(seed + 1)
    oi = 5_000_000 + np.cumsum(rng.normal(0, 40_000, n))
    base = base.copy()
    base["oi"] = np.abs(oi)
    return base


def make_fut_with_roll_gaps(n=400, seed=3, gap_every=21, gap_pct=0.05) -> pd.DataFrame:
    """Synthetic continuous-futures series with periodic un-back-adjusted
    rollover jumps (like Kite's continuous=True), to test the roll-gap guard."""
    df = make_fut_daily_with_oi(n=n, seed=seed)
    gap_mult = np.ones(n)
    for i in range(gap_every, n, gap_every):
        gap_mult[i:] *= (1 + gap_pct)
    df = df.copy()
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col] * gap_mult
    # OI also resets sharply at each synthetic rollover (old contract decays, new ramps)
    for i in range(gap_every, n, gap_every):
        df.loc[df.index[i], "oi"] = df["oi"].iloc[i] * 0.15
    return df


# ══════════════════════════════════════════════════════════════════════════════
# Test runner
# ══════════════════════════════════════════════════════════════════════════════

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        _PASS.append(name)
    else:
        _FAIL.append(f"{name}  {detail}")


def run():
    daily = make_daily()
    h1 = make_1h()
    fut = make_fut_daily_with_oi()

    # ── 1. forward outcomes / signal_stats math on a KNOWN signal ─────────────
    outc = sl.bt.forward_outcomes(daily, horizons=(5, 10))
    # A signal that's always +1 should have hit_rate == % of up-weeks (sanity, not edge)
    always_up = pd.Series(1.0, index=daily.index)
    st = sl.signal_stats(always_up, outc, 5)
    check("signal_stats: n matches available forward rows", st["n"] == outc["ret5"].notna().sum(),
          f"n={st['n']} vs {outc['ret5'].notna().sum()}")
    expected_hit = float((outc["ret5"].dropna() > 0).mean() * 100)
    check("signal_stats: always-bullish hit_rate == %days up", abs(st["hit_rate"] - expected_hit) < 0.5,
          f"{st['hit_rate']} vs {expected_hit}")
    expected_exp = float(outc["ret5"].dropna().mean())
    check("signal_stats: always-bullish expectancy == mean fwd ret", abs(st["expectancy"] - expected_exp) < 1e-2)

    # A perfect-foresight signal (sign of the actual forward return) must hit ~100%
    perfect = np.sign(outc["ret5"]).reindex(daily.index)
    st_perfect = sl.signal_stats(perfect, outc, 5)
    check("signal_stats: perfect-foresight hit_rate ~100%", st_perfect["hit_rate"] > 99.0,
          str(st_perfect["hit_rate"]))

    # An inverted perfect signal must hit ~0%
    st_inverted = sl.signal_stats(-perfect, outc, 5)
    check("signal_stats: inverted perfect-foresight hit_rate ~0%", st_inverted["hit_rate"] < 1.0,
          str(st_inverted["hit_rate"]))

    # All-zero signal → n_active == 0, stats NaN
    zeros = pd.Series(0.0, index=daily.index)
    st_zero = sl.signal_stats(zeros, outc, 5)
    check("signal_stats: all-zero signal has n_active==0", st_zero["n_active"] == 0)
    check("signal_stats: all-zero signal hit_rate is NaN", st_zero["hit_rate"] != st_zero["hit_rate"])

    # ── 2. evaluate_signal end-to-end shape ────────────────────────────────────
    res = sl.evaluate_signal(daily, always_up, name="always_up")
    check("evaluate_signal: has bucket table", "bucket" in res)
    check("evaluate_signal: has distribution table", not res["distribution"].empty)
    check("evaluate_signal: detail has signal+ret5 cols", {"signal", "ret5"}.issubset(res["detail"].columns))

    # ── 3. rank_signals sorts by |expectancy| ──────────────────────────────────
    res2 = sl.evaluate_signal(daily, zeros, name="zeros")
    ranked = sl.rank_signals([res, res2])
    check("rank_signals: 2 rows for 2 results", len(ranked) == 2)
    check("rank_signals: always_up ranks above zeros (nonzero expectancy)",
          ranked.iloc[0]["signal"] == "always_up" or pd.isna(ranked.iloc[1]["expectancy%"]))

    # ── 4. walk_forward splits by year and each split is internally consistent ─
    wf = sl.walk_forward(daily, always_up, by="year")
    check("walk_forward: at least 1 split", len(wf) >= 1)
    check("walk_forward: split n's sum <= overall n", wf["n"].sum() <= st["n"] + len(wf))

    # ── 5. rsi_fade_walk_forward runs end-to-end without raising ───────────────
    rf = sl.rsi_fade_walk_forward(daily)
    check("rsi_fade_walk_forward: returns overall+by_split", "overall" in rf and "by_split" in rf)

    # ── 6. Adapters run on synthetic data and return a daily-indexed Series ────
    adapters_daily = {
        "ema_ribbon": lambda: sa.adapt_ema_ribbon(daily),
        "supertrend": lambda: sa.adapt_supertrend(daily),
        "market_profile": lambda: sa.adapt_market_profile(daily),
        "bollinger_pctb": lambda: sa.adapt_bollinger_pctb(daily),
        "rsi_weekly": lambda: sa.adapt_rsi_weekly(daily),
        "oi_buildup": lambda: sa.adapt_oi_buildup(fut),
    }
    for label, fn in adapters_daily.items():
        try:
            s = fn()
            check(f"adapter[{label}]: returns a Series", isinstance(s, pd.Series))
            check(f"adapter[{label}]: nonempty on {len(daily)}-row synthetic daily", len(s) > 0,
                  f"len={len(s)}")
            check(f"adapter[{label}]: values are finite where not NaN",
                  bool(np.isfinite(s.dropna().to_numpy()).all()) if s.notna().any() else True)
        except Exception as e:
            check(f"adapter[{label}]: raised", False, repr(e))

    adapters_1h = {
        "dow_theory": lambda: sa.adapt_dow_theory(h1),
        "ema_slope_phases": lambda: sa.adapt_ema_slope_phases(h1),
    }
    for label, fn in adapters_1h.items():
        try:
            s = fn()
            check(f"adapter[{label}]: returns a Series", isinstance(s, pd.Series))
            check(f"adapter[{label}]: nonempty on synthetic 1H", len(s) > 0, f"len={len(s)}")
        except Exception as e:
            check(f"adapter[{label}]: raised", False, repr(e))

    # ── 7. Sign-convention check on a clean uptrend (adapters should lean bullish) ─
    bull_daily = make_perfectly_bullish_daily()
    for label, fn in [("ema_ribbon", sa.adapt_ema_ribbon), ("supertrend", sa.adapt_supertrend)]:
        s = fn(bull_daily).dropna()
        s = s[s.index >= s.index[len(s) // 3]]   # skip warm-up third
        mean_sign = float(np.sign(s).mean()) if len(s) else 0.0
        check(f"adapter[{label}]: leans bullish (+) on a clean uptrend", mean_sign > 0,
              f"mean_sign={mean_sign}")

    # ── 8. ADAPTERS registry sanity ─────────────────────────────────────────────
    check("ADAPTERS registry: all 8 entries present", len(sa.ADAPTERS) == 8, str(len(sa.ADAPTERS)))
    for label, meta in sa.ADAPTERS.items():
        check(f"ADAPTERS[{label}]: has callable fn", callable(meta["fn"]))
        check(f"ADAPTERS[{label}]: needs is a tuple", isinstance(meta["needs"], tuple))

    # ── 9. backtest.py real-volume/breadth path (imported lazily below) ────────
    from analytics import backtest as bt
    breadth = bt.daily_advance_breadth({"A": daily, "B": bull_daily})
    check("daily_advance_breadth: returns a Series", isinstance(breadth, pd.Series))
    check("daily_advance_breadth: values within [0,100]",
          bool(((breadth.dropna() >= 0) & (breadth.dropna() <= 100)).all()))
    conv_real = bt.build_conviction_history_real(daily, fut, breadth=breadth)
    check("build_conviction_history_real: returns nonempty on synthetic futures+OI",
          not conv_real.empty, f"rows={len(conv_real)}")
    check("build_conviction_history_real: price stays on the INDEX (gap-free)",
          not conv_real.empty and abs(float(conv_real["close"].iloc[-1]) - float(daily["close"].iloc[-1])) < 1.0,
          f"{conv_real['close'].iloc[-1] if not conv_real.empty else None} vs {daily['close'].iloc[-1]}")
    real_res = bt.run_backtest_real(daily, fut, breadth=breadth)
    check("run_backtest_real: returns nonempty distribution", not real_res["distribution"].empty)

    # ── 10. Roll-gap guard on the OI-buildup adapter ────────────────────────────
    fut_gappy = make_fut_with_roll_gaps()
    sig_gappy = sa.adapt_oi_buildup(fut_gappy)
    gap_days = sa._roll_jump_mask(fut_gappy["close"])
    gap_dates = fut_gappy.index[gap_days]
    check("_roll_jump_mask: flags at least one synthetic rollover", gap_days.sum() > 0,
          f"flagged={gap_days.sum()}")
    aligned = sig_gappy.reindex(pd.to_datetime(gap_dates).normalize())
    check("adapt_oi_buildup: roll-gap days are neutralised (signal==0)",
          bool((aligned.fillna(0) == 0).all()) if len(aligned) else False,
          f"{aligned.tolist()}")

    # ── 11. CAUSALITY GUARD — no look-ahead in ANY adapter ──────────────────────
    # The whole backtest is invalid if an adapter's signal for a PAST day changes
    # once future bars are added. Verify by running each adapter on the full series
    # vs a series truncated at a full-day boundary, and requiring the overlapping
    # PAST days (strictly before the cut day) to be bit-identical. Cutting on a day
    # boundary (not mid-session) avoids a false positive from an incomplete last day.
    def _assert_causal(label, fn, df):
        s_full = fn(df)
        days = sorted(set(pd.DatetimeIndex(df.index).normalize()))
        if len(days) < 20 or s_full is None or s_full.empty:
            check(f"causal: {label}", False, "insufficient data / empty signal")
            return
        cutday = days[int(len(days) * 0.8)]
        s_tr = fn(df[pd.DatetimeIndex(df.index).normalize() <= cutday])
        both = s_full.index.intersection(s_tr.index)
        both = both[both < cutday]                       # strictly-past, fully-formed both runs
        a, b = s_full.reindex(both), s_tr.reindex(both)
        m = a.notna() & b.notna()
        maxdiff = float((a[m] - b[m]).abs().max()) if int(m.sum()) else float("nan")
        check(f"causal: {label} (past signals unchanged when future removed)",
              int(m.sum()) > 0 and maxdiff < 1e-9, f"overlap={int(m.sum())} maxdiff={maxdiff}")

    for _lbl, _fn, _df in [
        ("ema_ribbon", sa.adapt_ema_ribbon, daily),
        ("supertrend", sa.adapt_supertrend, daily),
        ("market_profile", sa.adapt_market_profile, daily),
        ("bollinger_pctb", sa.adapt_bollinger_pctb, daily),
        ("rsi_weekly", sa.adapt_rsi_weekly, daily),
        ("oi_buildup", sa.adapt_oi_buildup, fut),
        ("dow_theory", sa.adapt_dow_theory, h1),
        ("ema_slope_phases", sa.adapt_ema_slope_phases, h1),
    ]:
        _assert_causal(_lbl, _fn, _df)


if __name__ == "__main__":
    run()
    print(f"\n{len(_PASS)} passed, {len(_FAIL)} failed\n")
    if _FAIL:
        print("FAILURES:")
        for f in _FAIL:
            print("  ✗", f)
        sys.exit(1)
    print("All checks passed.")
