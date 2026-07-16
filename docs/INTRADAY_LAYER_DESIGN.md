# Intraday Entry/Exit Layer Design — Hourly Proxy EMAs

**Status**: Design phase — no code yet. For discussion.

**Goal**: Add **hourly timing** to daily momentum/fade signals using proxy EMAs.

**Problem we're solving**:
- Daily signals fire at EOD (3:30 PM) or next morning
- Miss intraday entry points (early morning move) or overstay late-day weakness
- Drawdowns from bad entry/exit timing even when direction is right

**Solution**: Layer hourly 20-EMA for entry/exit precision while daily signal calls direction.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  DAILY LAYER (Signal)                                       │
│  ├─ EMA3/EMA8 momentum (±15/±5 thresholds)                 │
│  ├─ Outputs: momentum or fade signal at EOD                │
│  └─ Valid 1–4 trading days                                 │
├─────────────────────────────────────────────────────────────┤
│  HOURLY LAYER (Execution)                                   │
│  ├─ 20-EMA slope / volatility regime                        │
│  ├─ Entry: Daily says BUY → wait for hourly pullback       │
│  ├─ Exit: Take profit, stop loss, time stop                │
│  └─ Active during 9:15 AM — 3:30 PM session                │
├─────────────────────────────────────────────────────────────┤
│  POSITION MANAGER                                           │
│  ├─ Size: based on daily ATR14 (vol-adjusted)              │
│  ├─ Entry fills: hourly EMA confirm + limit order          │
│  ├─ Exits: profit target, stop, time, or next-day EOD      │
│  └─ Logging: every fill, every reason for exit             │
└─────────────────────────────────────────────────────────────┘
```

---

## Detailed Layer Design

### Layer 1: Daily Signal (What We Have)

**Input**: Daily OHLCV (close 3:30 PM)

**Computation** (EOD):
- EMA3/EMA8 slopes (3-bar)
- ATR14-scaled momentum
- Classify: STRONG_UP, MODERATE_UP, FLAT, MODERATE_DOWN, STRONG_DOWN

**Output**: 
- Signal: +1.0 (MOMENTUM BUY), -1.0 (MOMENTUM SHORT), +0.5 (FADE LONG), -0.5 (FADE SHORT), 0.0 (FLAT)
- Duration: Valid until next EOD signal OR 5 trading days (whichever comes first)
- Strength: STRONG (confidence +1) vs MODERATE (confidence +0.5)

**Example**:
```
2024-07-16 EOD:
  Close: 24200
  EMA3 slope: +2.1 pts/bar
  EMA8 slope: +0.8 pts/bar
  ATR14: 150
  Combined = (2.1/150 × 100) × 0.6 + (0.8/150 × 100) × 0.4 = +0.95
  → MODERATE_UP (5 < 0.95 < 15 ✗ wrong)
  
  [Let me recalc: combined should be larger]
  Combined = (210/150) × 0.6 + (80/150) × 0.4 = 0.84 + 0.21 = 1.05 ✗
  
  [Actually slope should already be big]
  Let's say EMA3 slope = +100 pts (very strong day)
  Combined = (100/150 × 100) × 0.6 + (80/150 × 100) × 0.4 = 40 + 21.3 = +61.3
  → STRONG_UP (>15)
  
  Signal: BUY (+1.0)
  Confidence: STRONG
  Valid until 2024-07-23 EOD (or until next STRONG signal)
```

### Layer 2: Hourly Entry/Exit (What We're Adding)

**Input**: Hourly OHLCV (09:15 — 15:30, 6 candles/session)

**Proxy Indicators** (recomputed each hourly candle):
1. **20-EMA slope** (3-bar change, hourly scale)
2. **ATR-on-hourly** (14-bar on 1H = ~1 trading day window)
3. **Volume regime** (above/below 10-session MA)

**Entry Rules** (when daily signal is active):

**Case 1: Daily says BUY (momentum or fade long)**
```
if daily_signal > 0:  # BUY signal
    if 20ema_is_sloping_up:  # hourly confirmation
        entry_action = "immediately BUY at market"
    elif hourly_price > 20ema:  # price above EMA
        entry_action = "wait for pullback to 20ema, then BUY on touch"
    elif hourly_price < 20ema:  # price way below EMA (unlikely)
        entry_action = "skip, don't force; wait for better setup next hour"
    else:
        entry_action = "neutral; no strong hourly lean; pass or half-size"
```

**Case 2: Daily says SHORT (momentum or fade short)**
```
if daily_signal < 0:  # SHORT signal
    if 20ema_is_sloping_down:  # hourly confirmation
        entry_action = "immediately SHORT at market"
    elif hourly_price < 20ema:  # price below EMA
        entry_action = "wait for rally to 20ema, then SHORT on touch"
    elif hourly_price > 20ema:  # price way above EMA (unlikely)
        entry_action = "skip, don't force; wait for better setup next hour"
    else:
        entry_action = "neutral; no strong hourly lean; pass or half-size"
```

**Key insight**: We're using **20-EMA as a pullback/resistance level** for entry, not as a separate trade signal.

---

### Entry Mechanics

**Order Type**: Limit order at 20-EMA level (not market).

**Why limit?**
- Market orders: overpay on entries (buy breakouts at resistance)
- Limit at 20-EMA: catch the actual pullback (entry closer to support/resistance)
- Patience: miss ~10% of entries, but better fill quality on the ones you take

**Example entry sequence**:
```
09:30 AM:  Daily signal = BUY (issued at 3:30 PM yesterday)
           Hourly 20-EMA = 24150

09:45 AM:  Price = 24180 (above EMA, rallying)
           Hourly: 20-EMA is still positive slope
           Action: WAIT (momentum strong; no pullback yet)

10:15 AM:  Price = 24160 (pullback starting)
           Hourly: 20-EMA starting to flatten
           Action: POST LIMIT ORDER at 24150 (20-EMA level)

10:30 AM:  Price = 24152 (limit filled!)
           Entry: LONG 24150, qty = 1 lot
           Stop: 24000 (24150 - 150 pts = 1× ATR below)
           Target: 24450 (24150 + 300 pts = 2× ATR above)

11:00 AM:  Price = 24400 (near target)
           Action: Trail stop to breakeven, or take 50% profit
           
12:00 PM:  Price = 24480 (above target)
           Action: Exit remaining 50%, take profit
           Result: +150 and +330 pts = +240 avg
```

---

### Exit Mechanics

**Three exit scenarios**:

#### 1. **Profit Target Exit**
- Target: +0.5% to +1.0% move (about 120–240 pts on Nifty 24000)
- Calculation: Entry + (2 × ATR14)
- Example: Entry 24150, ATR 150 → Target = 24450

#### 2. **Stop Loss Exit**
- Hard stop: Entry ± 1.5 × hourly ATR14
- Example: Entry 24150, Hourly ATR ~60 → Stop = 24150 - 90 = 24060

- Trailing stop: After +0.5% gain, trail by 0.5 × hourly ATR
- Example: After reaching 24300, trail to 24300 - 30 = 24270

#### 3. **Time Stop**
- If in trade > 4 hours with < +0.2% gain → exit
- Rationale: Daily setup is intraday focused; don't hold overnight
- Exception: If within 1 hour of close (3:00 PM) and >+0.2% → hold for close

#### 4. **Hourly Reversal Exit** (Advanced)
- If hourly 20-EMA slope reverses (was up, now down) → exit
- Requires 2-bar confirmation (slope negative on 2 consecutive hours)
- Example: Entered LONG on up-slope, then slope goes negative for 2 hours → EXIT

**Exit priority** (first to trigger wins):
1. Profit target (highest priority — lock in edge)
2. Stop loss (hard limit — protect capital)
3. Time stop (move on if not working)
4. Hourly reversal (trail and adapt)

---

### Proxy EMA Variants

**Option A: 20-EMA (Suggested)**
- Fast enough to catch intraday movement
- Smooth enough to filter noise
- Matches "support/resistance" intuition
- Used on 1H candles

**Option B: 8-EMA (Aggressive)**
- Faster, more responsive
- Higher false signals
- For scalper mentality
- Less suitable for daily directional trades

**Option C: Dual 20/50 EMA (Crossover)**
- 20-EMA: fast signal
- 50-EMA: slow (directional confirmation)
- Entry: wait for 20 > 50 (bullish) or 20 < 50 (bearish)
- Exit: 20 < 50 (if long) or 20 > 50 (if short)
- More robust, but fewer trades

**Recommendation**: Start with Option A (20-EMA), test Option C if noise issues.

---

## Signal Strength Impact on Entry

**STRONG daily signal** (confidence +1):
- Position size: 100% (full lot)
- Entry criteria: Strict (wait for 20-EMA confirmation)
- Stop loss: Tighter (1× ATR)

**MODERATE daily signal** (confidence +0.5):
- Position size: 50% (half lot)
- Entry criteria: More flexible (can enter without perfect hourly alignment)
- Stop loss: Looser (1.5× ATR)

**Example**:
```
Daily: STRONG_UP (conf=+1) → Size: 1 lot, Stop: 24060 (tight)
Daily: MODERATE_UP (conf=+0.5) → Size: 0.5 lot, Stop: 24030 (loose)
Daily: FLAT (conf=0) → Don't trade
```

---

## Volatility Regime Adjustments

**High Volatility Regime** (ATR14 > 20-day MA(ATR14)):
- Widen profit targets: +1.0% to +1.5% (wider range)
- Widen stops: 2 × hourly ATR (more room)
- Entry frequency: Lower (fewer false 20-EMA touches)

**Normal Volatility Regime** (ATR14 near 20-day MA):
- Profit targets: +0.5% to +1.0%
- Stops: 1.5 × hourly ATR
- Entry frequency: Standard

**Low Volatility Regime** (ATR14 < 20-day MA(ATR14)):
- Tighter profit targets: +0.3% to +0.5%
- Tighter stops: 1 × hourly ATR
- Entry frequency: Increase (more opportunities)

**Rationale**: Higher volatility = wider swings = larger targets needed to risk-reward. Lower volatility = tighter moves = tighter targets make sense.

---

## Implementation Strategy (Phased)

### Phase 1: Manual Alerts (Week 1)
- Daily signal fires at 3:30 PM
- Notification: "BUY signal — tomorrow watch for 20-EMA pullback"
- Trader executes manually at 20-EMA level
- Log: Entry time, fill price, exit time, P&L

### Phase 2: Semi-Auto Entry (Week 2-3)
- Daily signal fires at EOD
- Hourly algorithm continuously monitors 20-EMA
- When price touches 20-EMA: **alert** (trader decides to fill or skip)
- Limit order ready to post on alert

### Phase 3: Full Automation (Week 3-4)
- Daily signal fires
- Hourly algorithm monitors and auto-fills at 20-EMA limit
- Exits (profit target, stop, time stop) auto-execute
- Logging and post-trade analytics automated

**Caution**: Only move to Phase 3 after **2 weeks** of Phase 2 live testing to catch edge cases.

---

## Code Structure (High-Level, No Implementation Yet)

```python
# pages/31_Intraday_Live_Monitor.py (NEW)
#   │
#   ├─ Daily Signal Display
#   │   └─ show_active_daily_signal(signal, strength, valid_until)
#   │
#   ├─ Hourly Chart + 20-EMA
#   │   └─ plot_hourly_with_ema20()
#   │
#   ├─ Entry Alert Logic
#   │   ├─ if price touches 20-EMA and daily_active:
#   │   │    └─ ALERT: "Entry opportunity! Price at EMA20, limit order ready"
#   │   └─ manual_fill_or_skip()
#   │
#   └─ Active Position Monitor
#       ├─ if position_open:
#       │    ├─ show_entry_price()
#       │    ├─ show_stop_loss()
#       │    ├─ show_profit_target()
#       │    ├─ show_time_elapsed()
#       │    └─ show_realtime_pnl()
#       └─ exit_triggers()


# analytics/intraday_executor.py (NEW, framework)
#   │
#   ├─ class IntraDayExecutor:
#   │   ├─ __init__(daily_signal, entry_config)
#   │   ├─ compute_hourly_ema20(hourly_df)
#   │   ├─ check_entry_condition()  # price at EMA20?
#   │   ├─ place_limit_order()
#   │   └─ check_exit_conditions()  # profit/stop/time/reversal?
#   │
#   └─ ExitReason (enum)
#       ├─ PROFIT_TARGET
#       ├─ STOP_LOSS
#       ├─ TIME_STOP
#       ├─ HOURLY_REVERSAL
#       └─ MANUAL_EXIT


# utils/position_tracker.py (NEW)
#   │
#   ├─ class Position:
#   │   ├─ entry_time, entry_price, qty
#   │   ├─ stop_loss_price, profit_target_price
#   │   ├─ exit_time, exit_price, exit_reason
#   │   └─ pnl_points, pnl_pct, pnl_duration
#   │
#   └─ log_position_to_sqlite()  # post-trade analysis


# config.py (additions)
#   │
#   ├─ INTRADAY_EMA_PERIOD = 20
#   ├─ INTRADAY_ATR_PERIOD = 14
#   ├─ PROFIT_TARGET_PCT = 0.007  # +0.7%
#   ├─ PROFIT_TARGET_ATR_MULT = 2.0  # OR (entry + 2×ATR)
#   ├─ STOP_LOSS_ATR_MULT = 1.5
#   ├─ TIME_STOP_HOURS = 4
#   ├─ ENTRY_LIMIT_OFFSET = 0  # buy AT 20-EMA, not below
#   ├─ VOLATILITY_REGIME_LOOKBACK = 20  # days for HV/normal/LV calc
#   └─ POSITION_SIZE_STRONG = 1.0  # lots
```

---

## Comparison: Daily vs Intraday Layer

| Aspect | Daily Signal | Hourly Entry/Exit |
|--------|---|---|
| **Timeframe** | D (close 3:30 PM) | 1H (6 candles/session) |
| **What it does** | Calls direction | Calls entry/exit timing |
| **Frequency** | 1 signal/day | Up to 6 entry opportunities/day |
| **Holding period** | 1–5 days | Hours (usually <4 hours) |
| **Indicator** | EMA3/EMA8 momentum | 20-EMA + ATR |
| **Entry fills** | At market (next day open) | At limit (20-EMA level) |
| **Stop loss** | Daily ATR14 | Hourly ATR14 |
| **Profit target** | Daily move (5–10 days) | Intraday move (0.5–1.0%) |

**Synergy**: Daily momentum calls direction (trend), hourly entry/exit adds precision (timing).

---

## Risk Considerations

### Slippage & Liquidity
- Nifty futures: very liquid 9:30 AM — 3:00 PM
- Risk: 1–2 pts slippage on limit orders during fast moves
- Mitigation: Use market orders during high-vol spikes; accept slippage

### Overnight Gap
- If position still open at 3:30 PM close, what happens?
- Options:
  - A: Auto-exit at close (no overnight holding)
  - B: Trail stop to breakeven, hold if >+0.5%
  - C: Move stop to previous hourly low, hold for next day

### False Entries at EMA20
- Some pullbacks to EMA20 are decoys (quick bounce)
- Solution: Require **volume confirmation** or **2-bar bounce** at EMA20
- Alternative: Use 50-EMA instead of 20-EMA (smoother, fewer whipsaws)

### Divergence: Daily Momentum vs Hourly Movement
- Daily says BUY, but hourly is stuck in downtrend
- Solution: **Skip entry** if 20-EMA slope is negative for 2+ hours
- Don't force; wait for next day's signal

---

## Testing Strategy (Phase 1: Manual)

**Setup**:
1. Run Pages 29 (momentum optimizer) to lock in best daily config
2. Run Pages 30 (fade optimizer) to lock in best fade config
3. Decide: momentum only, fade only, or combo?

**Daily tracking (1 week)**:
- Print daily signal at 3:30 PM (spreadsheet log)
- Manually monitor hourly chart for 20-EMA touches
- Record: entry time, entry price, exit time, exit price, P&L
- Reason for exit: profit target? stop? time? other?

**Analysis after 1 week**:
- Avg entry fill vs daily close: did limit order save money?
- Avg exit P&L: better than holding to next day?
- Whipsaws: how many false 20-EMA touches?
- Hit rate: % of entries that went positive?

**Decision point**:
- If P&L > daily signal alone → move to Phase 2 (semi-auto)
- If P&L same or worse → stick with daily; hourly adds noise
- If P&L mixed → try different 20-EMA (try 50-EMA instead)

---

## Questions for Discussion

1. **Entry confirmation**: Require 20-EMA slope UP for buy, DOWN for short? Or just price touch?
2. **Profit target**: Fixed +0.7% (120 pts), or dynamic 2×ATR? Or price-based levels?
3. **Overnight risk**: Exit at close, or allow holding with trailing stop?
4. **Volume filter**: Weight entries higher if volume > 10-MA? Or ignore volume?
5. **Combo signals**: If daily momentum + fade disagreement, use the stronger one? Or wait?
6. **Drawdown limit**: Max loss/day before pausing intraday layer? (e.g., -0.5% account)

---

## Next Steps

1. **Lock in best daily config** (momentum or fade) from Pages 29/30
2. **Manual 1-week test** of 20-EMA entry/exit (no automation)
3. **Analyze results**: Compare daily-only vs daily + hourly intraday
4. **If promising**: Build Pages 31 (Intraday Live Monitor) for Phase 2
5. **If successful on Phase 2**: Implement full automation (Phase 3)

---

**Status**: Ready for discussion. What questions do you have?
