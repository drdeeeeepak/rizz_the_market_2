# CLAUDE.md — Master Index

## 1. Project Overview

**rizz_the_market_2** is a production-grade Nifty 50 Iron Condor options trading dashboard built with Streamlit and Zerodha Kite Connect. It runs a 16-page multi-timeframe analysis suite, aggregates 11 signal engines into a 100-point home score, and automates EOD signal computation via GitHub Actions.

- **Stack:** Python 3.11+, Streamlit 1.35+, Kite Connect 5.0+, Pandas 2.2+, Plotly
- **Broker API:** Zerodha Kite Connect (OAuth, automatic token lifecycle)
- **Automation:** GitHub Actions crons (EOD compute, pre-market gap, event fetch, scans)
- **Mode dispatcher:** PLANNING / PRE_MARKET / LIVE / TRANSITION (driven by IST clock in `Home.py`)
- **No test suite.** No Docker. No pyproject.toml.

---

## 2. File Index

### Root

| File | Purpose |
|---|---|
| `Home.py` | Streamlit entry point; mode dispatcher; 100-point home score dashboard |
| `config.py` | **Single source of truth** for all strategy constants (VIX bands, EMA periods, DTE targets, scoring weights, universe tokens) |
| `page_utils.py` | `bootstrap_signals()` 3-tier fallback; IST helpers; Streamlit caching wrappers |
| `requirements.txt` | All runtime dependencies |
| `README.md` | Setup guide, page index, GitHub Actions cron schedule, scoring system |

### `analytics/` — Signal Engines

| File | Purpose |
|---|---|
| `compute_signals.py` | Master orchestrator; calls all 11 engines; saves/loads `data/signals.json` |
| `home_engine.py` | Rescales 8 lens scores to max=100 (weights in `config.py`) |
| `base_strategy.py` | Abstract base; shared `ema()`, `rsi()`, `sma()`, `atr()` utilities |
| `ema.py` | EMA Ribbon engine (Pages 1–4); dual PUT/CALL safety scores |
| `rsi_engine.py` | RSI regime detection (Pages 5, 7); Wilder's 14-period |
| `bollinger.py` | Bollinger Bands + VIX-adjusted width (Page 9) |
| `options_chain.py` | PCR, GEX, max pain, IV skew (Page 10) |
| `oi_scoring.py` | OI momentum; strike accumulation patterns (Page 10b) |
| `vix_iv_regime.py` | VIX/IV regime; VRP; IV term structure (Page 11) |
| `market_profile.py` | POC/VAH/VAL; initial balance; balance area (Page 12) |
| `geometric_edge.py` | Price strength + volatility breakout scanner (Page 13) |
| `dow_theory.py` | 5-phase Dow Theory cycle; 1H single-window (Page 0) |
| `supertrend.py` | SuperTrend MTF 15m/30m/5m cascade; flip detection (Page 15) |
| `constituent_ema.py` | Top-10 stock EMA breadth counting (Pages 3–4) |

### `data/` — API & Persistence

| File | Purpose |
|---|---|
| `kite_client.py` | Kite Connect OAuth wrapper; automatic token lifecycle → GitHub push |
| `live_fetcher.py` | All Kite data fetching (`get_nifty_spot`, `get_nifty_daily`, `get_top10_daily`, `get_india_vix`, `get_dual_expiry_chains`, `get_nifty_1h_phase`, MTF candles); Streamlit TTL caching |
| `rolled_positions.py` | Position state for gamma/gamma_accel calculations |
| `signals.json` | EOD compute output; cold-start fallback for all pages |
| `gap_check.json` | Pre-market gap check result (direction, action, pct, pts) |
| `events.json` | RBI/NSE economic event calendar |
| `README.md` | Token flow diagram; file manifest; required GitHub secrets |

### `pages/` — Streamlit Dashboard (16 pages)

| File | Page | Topic |
|---|---|---|
| `00_Dow_Theory.py` | 0 | Dow Theory phase command center |
| `01_Nifty_EMA_Price.py` | 1 | Nifty spot vs EMA ribbon |
| `02_Nifty_EMA_Ribbon.py` | 2 | EMA ribbon clustering + moat/momentum |
| `03_Stocks_EMA_Price.py` | 3 | Top-10 stocks vs EMA(60) |
| `04_Stocks_EMA_Ribbon.py` | 4 | Top-10 EMA ribbon breadth |
| `05_Nifty_RSI_Weekly.py` | 5 | Weekly RSI regime |
| `07_Stocks_RSI_Weekly.py` | 7 | Top-10 weekly RSI regimes |
| `09_Bollinger.py` | 9 | Bollinger Bands + squeeze signals |
| `10_Options_Chain.py` | 10 | Live chain; PCR; GEX; dual-expiry |
| `10b_OI_Scoring.py` | 10b | OI momentum scoring heatmap |
| `11_VIX_IV.py` | 11 | VIX/IV regime; VRP heatmap |
| `12_Market_Profile.py` | 12 | Volume profile TPO/VAH/VAL/VWAP |
| `13_Geometric_Edge.py` | 13 | Geometric edge scanner + watchlist |
| `14_Position_Tracker.py` | 14 | Manual position entry; Greeks; P&L |
| `15_SuperTrend_MTF.py` | 15 | SuperTrend MTF cascade; canary rules |
| `16_Gamma_Roll.py` | 16 | Gamma provisioning; defensive roll signals |

### `scripts/` — GitHub Actions Runners

| File | Schedule (IST) | Purpose |
|---|---|---|
| `eod_compute.py` | 3:35 PM | Fetch EOD OHLCV; run all engines; write `signals.json`; Telegram |
| `premarket_gap.py` | 8:45 AM | Gift Nifty gap → action enum; write `gap_check.json`; Telegram |
| `fetch_events.py` | 6:00 AM | RBI/NSE event calendar → `events.json` + `events.parquet` |
| `run_scan.py` | Multiple | Geometric Edge scans; EOD OI snapshot; watchlist JSON |
| `generate_token.py` | Manual | One-time: Kite request_token → access_token |
| `refresh_token.py` | Manual | Push new `KITE_ACCESS_TOKEN` to GitHub repo secrets via API |

### `ui/` — Shared UI Components

| File | Purpose |
|---|---|
| `components.py` | `tooltip()`, metric cards, color helpers, layout builders |
| `market_guard.py` | Kill-switch; market hours validation; hard stop conditions |

---

## 3. Standard Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run dashboard locally
streamlit run Home.py

# Run EOD signal compute manually
python scripts/eod_compute.py

# Run pre-market gap check manually
python scripts/premarket_gap.py

# One-time: generate Kite access token
python scripts/generate_token.py

# Refresh GitHub Actions secret
python scripts/refresh_token.py

# Run geometric edge scanner
python scripts/run_scan.py
```

**Required environment variables** (`.env` or Streamlit secrets):
`KITE_API_KEY`, `KITE_API_SECRET`, `KITE_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GH_PAT` (for secret refresh only)

---

## 4. Architectural Decisions

**Single config module (`config.py`):** All strategy constants, thresholds, universe tokens, and scoring weights live in one file. No magic numbers in engine or page files.

**Modular engine pattern:** Every analytics engine extends `base_strategy.BaseStrategy` and is independently testable. `compute_signals.py` is the only caller; pages never import engines directly.

**3-tier bootstrap fallback (`page_utils.bootstrap_signals`):** Pages first check `st.session_state`, then `data/signals.json`, then trigger live compute. This decouples UI from live API availability.

**Automatic token lifecycle (`kite_client.py`):** The dashboard's first login generates the access token and pushes it to the GitHub repo. GitHub Actions consume it for overnight cron jobs. Token expires at midnight IST and is regenerated on the next dashboard login.

**Streamlit TTL caching in `live_fetcher.py`:** All Kite API calls are wrapped in `@st.cache_data`. TTLs are tuned per data type (spot: 60s, daily OHLCV: 3600s, options chain: 300s). Analytics engines receive DataFrames, never raw API objects.

**No shared state between pages:** Pages communicate only through `st.session_state` (position tracker) or `data/*.json` files written by scripts. There are no shared singletons or global mutable state.

**Score rescaling in `home_engine.py`:** Eight lens scores (raw 0–100) are weighted and summed to a max of 100. Weights are defined in `config.py` (OC=22, RSI=18, MP=18, BB=14, ST=9, VIX=9, EMA=5, Dow=5).
