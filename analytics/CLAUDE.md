# analytics/CLAUDE.md — Engine Development Index

## Engine Registry

| Engine class | File | Signal key prefix | Input data required |
|---|---|---|---|
| `EMAEngine` | `ema.py` | `cr_*`, `atr14`, `net_skew`, `canary_*`, `put_safety_adj`, `call_safety_adj` | `nifty_df` (daily OHLCV) |
| `ConstituentEMAEngine` | `constituent_ema.py` | `constituent_breadth`, `breadth_score`, `divergence_alert`, `sw3/4_active`, `bfsi_softening`, `sd5/6_*` | `stock_dfs` (dict of per-stock daily OHLCV) |
| `RSIEngine` | `rsi_engine.py` | `w_regime`, `d_zone`, `alignment`, `kill_switches`, `rsi_put/call_dist_mod` | `nifty_df`, `stock_dfs` |
| `BollingerOptionsEngine` | `bollinger.py` | `bb_regime`, `bb_*`, `bw_pct` | `nifty_df` |
| `OptionsChainEngine` | `options_chain.py` | `gex_total`, `gex_flip_level`, `call_wall`, `put_wall`, `pcr`, `iv_skew`, `atm_iv`, `straddle_price`, `oc_binding_*`, `oc_home_score` | `chains["far"]` DataFrame, `spot`, `far_dte`, `atr14` |
| `OIScoringEngine` | `oi_scoring.py` | `near_scored`, `far_scored` (DataFrames), `pe_net_score`, `pe_wall_strength` | `chains["near"]`, `chains["far"]` DataFrames, DTEs |
| `VixIVRegimeEngine` | `vix_iv_regime.py` | `vix_state`, `ivp_1yr`, `vrp`, `hv20`, `vix_sma_*`, `vix_ubb`, `size_multiplier`, `vix_home_score` | `nifty_df`, `vix_hist` (daily), `vix_live` (float), `atm_iv` (float) |
| `MarketProfileEngine` | `market_profile.py` | `mp_nesting`, `mp_behaviour`, `weekly_vah/poc/val`, `mp_ce/pe_anchor`, `mp_day_type`, `mp_poc_migration`, `mp_home_score` | `nifty_df`, `spot`, `near_dte`, `far_dte`, `net_skew`, `atr14` |
| `DowTheoryEngine` | `dow_theory.py` | `dow_*` (all prefixed) | `nifty_1h` (1H OHLCV, 20-day window) |
| `SuperTrendEngine` | `supertrend.py` | `st_*` (all prefixed) | `nifty_df`, `nifty_1h`, `nifty_30m`, `nifty_15m`, `nifty_5m`, `spot` |
| `HomeEngine` | `home_engine.py` | Used by `Home.py` only — not in `compute_signals.py` | Reads `sig` dict |

---

## Base Class (`base_strategy.py`)

Every engine `extends BaseStrategy`. Shared utilities:
- `ema(series, period)` — exponential moving average
- `rsi(series, period=14)` — Wilder's smoothed RSI
- `sma(series, period)` — simple moving average
- `atr(df, period=14)` — average true range

Each engine must implement `signals(*args) -> dict`.

---

## Adding a New Engine

1. Create `analytics/new_engine.py` extending `BaseStrategy`; implement `signals() -> dict`
2. Import and call it in `compute_signals.py::compute_all_signals()`; merge result into `sig`
3. Add signal key prefix to the registry table above
4. If it contributes to the home score: add `HOME_SCORE_MAX_*` constant in `config.py`, cap in `_compute_master_score()`, add weight to `_lens_scores` dict
5. Add engine → page mapping to `pages/CLAUDE.md`

---

## Home Score Weights (from `config.py`)

| Lens | Max points | Signal key |
|---|---|---|
| Options Chain | 22 | `oc_home_score` |
| RSI | 18 | derived from `mtf_alignment` + kill switches |
| Market Profile | 18 | `mp_home_score` |
| Bollinger | 14 | `bb_home_score` |
| SuperTrend MTF | 9 | `st_home_score` |
| VIX/IV | 9 | `vix_home_score` |
| EMA | 5 | `home_score` (raw from EMAEngine) |
| Dow Theory | 5 | `dow_home_score` |
| **Total** | **100** | `master_score` |

---

## Signal Key Conventions

- Engine-specific keys are prefixed: `bb_*`, `mp_*`, `st_*`, `dow_*`, `vix_*`, `oc_*`
- EMA engine keys use `cr_*` (corridor) prefix for distance/moat fields
- `kill_switches` is a flat dict of `{name: bool}` — aggregated across engines in RSI engine
- DataFrames (`near_scored`, `far_scored`) are **excluded** from `signals.json` — handle missing gracefully in pages
- `spot` is always stored in `sig` as the primary price anchor
