# Backtest / Optimizer — handoff & plan

Reusable brief for building the **generic signal backtester** and interpreting results.
Repo: `drdeeeeepak/rizz_the_market_2` · develop on `claude/pg18-table-layout-vdynd7`,
push to that branch **and** `main`.

## Who / what
Trader = Iron-Condor + one-sided premium seller on Nifty **weekly (Tuesday) expiries**.
Condor strikes ≈ **+3.5% call / −4% put** from Tuesday close, squared off ~next Tuesday.
Goals: sell closer, better mid-week book/roll decisions, and time one-sided sells.

## What already exists
- `analytics/backtest.py` — `run_backtest` (daily/positional) and `run_intraday_backtest`
  (intraday timing). Helpers: `build_conviction_history`, `forward_outcomes`,
  `weekly_move_distribution`, `column_cutoff_scan`, `_bucket_stats`, `state_horizon_edge`.
- `pages/22_Backtest_Optimizer.py` — Mode 1 positional (daily), Mode 2 intraday timing.

## Findings from the first backtest (2y daily + ~2mo 1H/15m)
- **Only RSI and %B carry a consistent edge → OVERBOUGHT FADE (mean-reversion).**
  Best rule: **SHORT / sell-CALLs when RSI ≥ 62 & Bull−Bear ≥ 45** (~60–65% hit daily,
  ~70–76% on 15m; avg favourable ~0.3–0.9%). Beats the sample's up-drift → real counter-drift.
- **Asymmetric:** the LONG / oversold side does **not** work (~coin-flip).
- **No standalone edge:** Final, Bull−Bear, Conf%, ΔVWAP, Stretch, Candle. Trend-following
  reads were weak/contrarian. The "conviction" synthesis did **not** beat raw RSI.
- **Sizing (solid, high-confidence):** weekly max-up p90 2.68% / p95 3.84%; max-down p90 3.17%
  / p95 4.32%. +3.5%/−4% touched ~6%/~6% of weeks (≈94% safe, 1-week). Downside travels
  farther → keep the put further out (as the trader does). Carrying 2 weeks ≈ doubles breach
  risk (~14% each side) → roll/widen past the first Tuesday.
- **CAVEAT — not a fair test of two pillars:** the daily run used the **INDEX with SYNTHETIC
  volume** (CVD muted) and **breadth OFF**, plus a realized-vol expected-move (no VIX history).
  So CVD and breadth were never fairly tested. Intraday used real futures volume but only ~2mo
  (one regime).

## Column verdicts (for the live Conviction Table)
- **Keep / elevate:** RSI, %B (overbought fade), State (as a regime label, read *contrarian* at
  extremes).
- **Demote (fairly tested, ~zero edge):** Final, Bull−Bear, Conf%, ΔVWAP, Stretch, Candle, wicks.
- **Untested — do NOT judge yet (were muted):** CVD↑ / CVDdiv / CVD, Brd%, γ. Re-test fairly
  before cutting.

## Data availability (confirmed)
- **Futures OI:** available historically via Kite `historical_data(continuous=True, oi=True)`,
  which also gives **real volume over years** → the backbone for the daily run; fixes the muted
  CVD pillar and enables **futures OI-buildup** signals.
- **CVD (proxy = close-location × volume):** derivable wherever volume exists → futures candles,
  not the index. Continuous futures solves it. (Still a proxy, not true order-flow.)
- **Option-chain GEX / gamma-flip:** NOT back-fillable (needs every strike's OI through time).
  Only the forward-accumulated `data/gamma_history.json` exists → test forward-only or skip.
- **Breadth:** see below.

## Breadth approach
- **Daily/positional:** breadth = **% of Nifty-50 constituents ABOVE their PREVIOUS DAILY CLOSE**
  (advance/decline breadth). Needs only 50 stocks' **daily** OHLC → cheap, multi-year. Label it
  **"daily advance breadth"** — a **cousin of, not identical to,** the live `Brd%` (% above
  *session VWAP*, intraday). It tests whether breadth adds edge at the daily/weekly horizon
  (which suits the condor), not the exact live column.
- **Intraday timing:** use an intraday breadth (% above session VWAP, or lighter % above prior
  close / above open) if we want to validate the live column specifically.
- **Membership bias** (today's 50 used historically) is acceptable; note it.

## What to build — generic signal backtester
1. **Harness** (extend `analytics/backtest.py` or new `analytics/signal_lab.py`): takes a price df
   (OHLCV) + a SIGNAL (Series of −1/0/+1 or a numeric score, from an adapter) + horizons +
   optional strike distances → returns uniformly: n, hit-rate, expectancy (avg forward move in
   signal direction), Spearman corr, bucket scan, and (daily) strike-breach rates + weekly move
   percentiles. Reuse `forward_outcomes` / `_bucket_stats` / `column_cutoff_scan`.
2. **Signal adapters** for the price-derived pages — reuse each page's real logic where possible:
   Dow Theory (`analytics/dow_theory.py`), EMA Ribbon (pages 01/02), SuperTrend MTF (page 15),
   Market Profile (page 12), Bollinger %B (page 09), RSI Weekly (page 05), EMA Slope Phases
   (page 17). (Trader is optimistic about Dow Theory / EMA Ribbon / SuperTrend / Market Profile —
   let the numbers decide.)
3. **Data fidelity upgrade:** add a Kite **continuous-futures** fetch (`continuous=True, oi=True`)
   to `data/live_fetcher.py` for real **volume + OI** over years. Then **re-run the Conviction
   test** with real volume + **breadth ON** (daily advance breadth) to fairly test CVD and Brd%.
   Add a **futures OI-buildup** signal adapter.
4. **Walk-forward / out-of-sample** the overbought-fade RSI rule (split by year/regime) — does it
   survive beyond the one sample regime?
5. **Page** (extend page 22 with a "Signal Library" mode, or new page 23): run the harness over all
   adapters → **ranked table** (signal, hit-rate, expectancy, sample size) + per-signal detail +
   CSV download. Table-only, frozen-header style.

## Constraints
- No Kite in the build env → **unit-test all math on SYNTHETIC data**; the user runs real fetches
  by logging in (Home → Kite) and clicking Run.
- Keep honest fidelity caveats visible on the page (proxy CVD, breadth membership bias,
  realized-vol EM when VIX history absent).
- IST timezone everywhere (`Asia/Kolkata`); Streamlit Cloud runs UTC.
- Commit in small steps; push to `claude/pg18-table-layout-vdynd7` **and** `main`.

## Suggested build order
1. Harness API + adapter interface (propose, then implement with synthetic tests).
2. Continuous-futures fetch (real volume + OI).
3. Fair Conviction re-test (volume on, daily advance breadth on) → confirm/deny CVD & breadth edge.
4. Price-page adapters (Dow, EMA Ribbon, SuperTrend, Market Profile, Bollinger, RSI-weekly, slope).
5. Ranked "Signal Library" page + CSV.
6. Walk-forward the RSI overbought-fade rule.
