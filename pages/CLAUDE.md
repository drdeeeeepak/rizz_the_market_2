# pages/CLAUDE.md — Page Development Index

## Bootstrap Pattern (every page)

```python
from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()   # 3-tier: session_state → signals.json → live
show_page_header(spot, signals_ts, "page_key")
```

`bootstrap_signals()` returns `(sig: dict, spot: float, signals_ts: str)`.
Never call analytics engines or `live_fetcher` directly from a page.

---

## Signal Keys by Page

| Page | Key signals consumed | Producing engine |
|---|---|---|
| `00_Dow_Theory` | `dow_structure`, `dow_phase`, `dow_narrative`, `dow_phase_score`, `dow_ce_health`, `dow_pe_health`, `dow_call_breach`, `dow_put_breach` | `analytics/dow_theory.py` |
| `01_Nifty_EMA_Price` | `cr_regime`, `cr_pe_dist_pts`, `cr_ce_dist_pts`, `put_safety_adj`, `call_safety_adj`, `atr14` | `analytics/ema.py` |
| `02_Nifty_EMA_Ribbon` | `cr_regime`, `cr_put_moats`, `cr_call_moats`, `cr_mom_state`, `cr_hard_skip`, `net_skew`, `tue_close`, `tue_atr` | `analytics/ema.py` |
| `03_Stocks_EMA_Price` | `constituent_breadth`, `breadth_score`, `breadth_label` | `analytics/constituent_ema.py` |
| `04_Stocks_EMA_Ribbon` | `constituent_breadth`, `divergence_alert`, `lead_warning`, `sw3_active`, `sw4_active` | `analytics/constituent_ema.py` |
| `05_Nifty_RSI_Weekly` | `w_regime`, `d_zone`, `alignment`, `kill_switches` | `analytics/rsi_engine.py` |
| `07_Stocks_RSI_Weekly` | `w_regime` (per stock keys from `stk_sig`) | `analytics/rsi_engine.py` |
| `09_Bollinger` | `bb_regime`, `bw_pct`, `bb_vix_divergence`, `bb_distance_put`, `bb_distance_call`, `bb_walk_up_count`, `bb_walk_down_count` | `analytics/bollinger.py` |
| `10_Options_Chain` | `gex_total`, `gex_flip_level`, `call_wall`, `put_wall`, `pcr`, `iv_skew`, `atm_iv`, `straddle_price`, `oc_binding_ce`, `oc_binding_pe` | `analytics/options_chain.py` |
| `10b_OI_Scoring` | `near_scored` (DataFrame), `far_scored` (DataFrame), `pe_net_score`, `pe_wall_strength`, `position_action_put` | `analytics/oi_scoring.py` |
| `11_VIX_IV` | `vix`, `vix_state`, `ivp_1yr`, `vrp`, `hv20`, `size_multiplier`, `vix_sma_200`, `vix_ubb`, `vix_spike_confirmed`, `warnings` | `analytics/vix_iv_regime.py` |
| `12_Market_Profile` | `mp_nesting`, `mp_behaviour`, `weekly_vah`, `weekly_poc`, `weekly_val`, `mp_ce_anchor`, `mp_pe_anchor`, `mp_day_type`, `mp_poc_migration` | `analytics/market_profile.py` |
| `13_Geometric_Edge` | reads `data/scan_results.json` directly (not from `sig`) | `scripts/run_scan.py` |
| `14_Position_Tracker` | `spot`, `atm_iv`, `near_dte`, `far_dte` + `st.session_state` for position persistence | `data/rolled_positions.py` |
| `15_SuperTrend_MTF` | `st_put_stack`, `st_call_stack`, `st_flip_tfs`, `st_ic_shape`, `st_lens_pe_dist`, `st_lens_ce_dist`, `st_pe_case`, `st_ce_case` | `analytics/supertrend.py` |
| `16_Gamma_Roll` | `lens_table`, `suggested_pe_dist`, `suggested_ce_dist`, `final_put_short`, `final_call_short`, `final_put_wing`, `final_call_wing`, `master_score` | `analytics/compute_signals.py` (`_build_lens_table`) |

---

## UI Helpers (`ui/components.py`)

| Function | Use |
|---|---|
| `metric_card(label, value, sub, color)` | Standard KPI tile — no tooltip |
| `metric_card_with_tip(label, value, sub, tip_term, tip_l1/2/3)` | KPI tile + hover/overlay tooltip |
| `tooltip(term, line1, line2, line3)` | Inline HTML tooltip for text |
| `kill_switch_row(name, active, detail)` | Red/green kill-switch indicator row |
| `alert_box(title, body, level)` | Coloured alert banner (`info`/`warn`/`danger`) |
| `expiry_banner(expiry, dte, role, mult)` | Expiry header strip with DTE badge |
| `section_header(title, subtitle)` | Dark section divider with subtitle |
| `net_score_chip(score)` | HTML colour chip for OI net score |
| `wall_dots(score, color)` | Dot-bar strength indicator |

`market_guard.market_closed_banner()` — call at page top to show closed state.
`market_guard.require_live_data(spot)` — hard-stop if spot is stale/zero.

---

## Gotchas

- **Page 10** expects dual-expiry chains (`near` + `far` keys in `chains` dict). Never pass a single expiry.
- **Page 10b** `near_scored` / `far_scored` are DataFrames — they are stripped from `signals.json`. Cold-start fallback will be empty; handle gracefully.
- **Page 13** is the only page that does **not** use `bootstrap_signals()` for its core data — it reads `data/scan_results.json` written by `scripts/run_scan.py`.
- **Page 14** persists position state in `st.session_state` (not `signals.json`). State is lost on session restart.
- **Page 15** uses `st.session_state["st_open_put_norm"]` / `st_open_call_norm` for intraday trajectory. Only captured once per session at 9:15 AM.
- All `dow_*` signal keys are double-prefixed in `signals.json` (e.g. `dow_dow_phase`) for some fields — check `compute_signals.py` line ~114 if consuming raw JSON.
