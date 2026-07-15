# CLAUDE.md — rizz_the_market_2 project cheatsheet

## Repo overview
- Streamlit multi-page app for Nifty options (Iron Condor) position management
- Entry: `Home.py` — Kite login/logout (token file: `access_token.txt`)
- Main page: `pages/02_Nifty_EMA_Ribbon.py` — EMA Hold Monitor (most worked-on page)
- EOD automation: `scripts/eod_compute.py` via GitHub Actions at 3:35 PM IST Mon–Fri

## Branch
- Develop on whatever feature branch the session is assigned — but ALWAYS also push every
  commit to `main` (fast-forward when possible), without waiting to be asked. Don't leave
  work sitting only on the feature branch.

## Key files
| File | Purpose |
|---|---|
| `pages/02_Nifty_EMA_Ribbon.py` | Main Iron Condor monitor page |
| `data/rolled_positions.py` | Anchor + roll state management |
| `data/rolled_positions.json` | Persisted anchor/history (committed by EOD job) |
| `data/live_fetcher.py` | Kite API wrappers (spot, daily OHLCV, VIX, chains) |
| `data/signals.json` | Output of EOD compute job |
| `analytics/compute_signals.py` | All signal logic |
| `analytics/dow_theory.py` | DowTheoryEngine — `signals(df, spot)` |
| `scripts/eod_compute.py` | EOD job — fetches, computes, writes, sends Telegram |
| `.github/workflows/eod_compute.yml` | GH Actions schedule |
| `ui/` | Shared UI helpers (section_header, show_page_header, etc.) |
| `page_utils.py` | `load_signals()`, `format_number()` etc. |

## pg02 — EMA Hold Monitor: key concepts

### Anchor & rolled positions
- **Anchor** = unified price for both CE and PE legs
- Set every **Tuesday EOD** via `set_expiry_anchor(spot, date)` → clears history, starts new cycle
- Non-Tuesday EOD: `eod_update(spot, date)` → checks roll events
- **CE strike** = `round(anchor × 1.035 / 50) * 50`
- **PE strike** = `round(anchor × 0.960 / 50) * 50`
- Roll triggers (EOD only, no intraday):
  - BOOK LOSS: drift ≥ 2.5% adverse
  - BOOK PROFIT: drift ≥ 1.8% favorable
- `bootstrap_from_history(daily_df)` — finds last completed Tuesday, sets anchor, replays roll logic
  - Skip condition: anchor exists AND has EXPIRY_ANCHOR event AND anchor_date ≠ today IST
  - IST date check is critical — Streamlit Cloud runs UTC

### VIX
- `get_india_vix_detail()` returns `(vix_current, vix_chg_pts, vix_chg_pct)`
- Compute pct from `ohlc.close` vs `last_price` — `change_percent` field does NOT exist in Kite API

### DTB (Days To Breach)
- `DTB = gap_pts / max(today_move_pts, vix_implied_move_pts)`
- VIX-implied = `spot × (VIX/100) / 16`
- `max()` ensures pace never drops below VIX-implied (prevents false confidence on flat days)
- Red cell rule: DTB < 2.0d
- Red text rule: Threat multiplier > 1.15

### Threat Multiplier
- `Chng% × RTR` where RTR = today true range / 14-day ATR

### Cycle history display
- Chronological (oldest first, NOT reversed)
- Header shows `_rp_history[0].get('date')` — the EXPIRY_ANCHOR date that started the cycle

## pg02 — Color palette

```python
PE_GREEN = {0:"#064e3b", 1:"#065f46", 2:"#00b894", 3:"#55efc4", 4:"#d1fae5"}
CE_RED   = {0:"#7f1d1d", 1:"#be123c", 2:"#ff4757", 3:"#ff8fa3", 4:"#ffe0e6"}
BOTH_AMBER = "#f59e0b"
CANARY_HEADER_COLOUR = {0:"#10b981", 1:"#f59e0b", 2:"#f97316", 3:"#ef4444", 4:"#dc2626"}
_LIGHT_COLS = {"#55efc4","#d1fae5","#ff8fa3","#fecaca","#ffe0e6"}
_lvl_col = {"success":"#10b981","info":"#38bdf8","warning":"#f59e0b","danger":"#ff4757"}
```

### Roll state colors
```python
def _roll_state(bl, bp):
    if bl: return "🔴 BOOK LOSS",   "#be123c"
    if bp: return "🟢 BOOK PROFIT", "#00b894"
    return         "✅ HOLD",        "#0ea5e9"
```

### Corridor `_KIND_BG` — (bg, text, accent)
```python
_KIND_BG = {
    "neutral":     ("#2a2000", "#fde68a", "#f59e0b"),   # amber — anchor
    "cmp":         ("#0a2a45", "#67e8f9", "#0ea5e9"),   # cyan  — spot
    "above":       ("#3a1010", "#ff9090", "#ef4444"),   # EMA overhead
    "below":       ("#0a2e1e", "#6ee7b7", "#10b981"),   # EMA support
    "sold_ce":     ("#4a0a20", "#ff4757", "#ff4757"),   # CE sold
    "sold_pe":     ("#002e20", "#00e5b0", "#00b894"),   # PE sold
    "book_loss":   ("#3a1000", "#fb923c", "#f97316"),   # orange-red — distinct from EMAs
    "book_profit": ("#052e18", "#4ade80", "#22c55e"),   # bright green
}
```

## pg02 — Structure (line number hints)
- ~L1–60: imports, constants, color palette
- ~L175–200: bootstrap trigger (page load)
- ~L290–350: roll state pre-compute (ce/pe book_loss, book_profit, adverse, favor)
- ~L430–450: side card roll state labels
- ~L895–950: `_side_card()` function
- ~L957–1027: corridor `_KIND_BG` + `_render_vc()` + render call
- ~L1036+: Canary Sources section
- ~L1220+: EMA Ribbon section + regime table

## Common gotchas
- Always use IST timezone (`pytz.timezone("Asia/Kolkata")`) — Streamlit Cloud is UTC
- `@st.cache_data` caches exceptions if you return empty df on failure — raise instead
- Kite `access_token.txt` is in repo root (not `data/`)
- `dow_eng.signals(df, spot)` — spot is required positional arg
- `rolled_positions.json` is committed by EOD job (see `eod_compute.yml` git add step)
- Corridor rows: each has `border-left:4px solid {accent}` — that's the key visual differentiator

## Token-saving tips for future sessions
- Start fresh session, paste only the relevant section of pg02 (read just the lines you need)
- Use `/clear` after each completed sub-task
- Reference this file for context instead of re-explaining the architecture

## Lessons Learned — Do Not Repeat

**See full audit:** `docs/AUDIT_Page28_Backtest_Collapse_Failure.md`

### Pattern: Structural/UI Changes (expander, container, scope changes)
When moving code into/out of containers (expanders, columns, etc.):

❌ **Don't:**
- Try to fix symptoms (e.g., "session state") without understanding root cause
- Make multiple small edits without verifying structure after each
- Push without reading the code back to verify indentation

✓ **Do:**
1. Ask clarifying questions upfront ("Should X and Y collapse together?")
2. Read file and map what's inside vs outside current structure
3. Identify exact line numbers for code to move
4. Make ONE comprehensive edit with proper indentation
5. Read back affected section to verify structure is correct
6. Only commit after verification

**Key lesson:** When indenting code into containers, a single `Read` call catches 90% of mistakes. Use it.
