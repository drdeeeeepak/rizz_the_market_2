# Momentum & Fade Strategies with Hourly Intraday Layer

**Status**: Pages 29–30 built, optimizer running; intraday layer in design phase  
**Updated**: 2026-07-16  
**Target**: +0.2%+ expectancy, >52% hit rate, validated on 2+ year backtest

---

## I. EMA Momentum Signal (Page 29 Optimizer)

### Current State
- **Hit Rate**: 51.5% (baseline)
- **Expectancy**: -0.088% (slightly negative)
- **Signal**: EMA3/EMA8 3-bar slopes, ATR-scaled, 0.6/0.4 weighted
- **Thresholds**: STRONG ±15, MODERATE ±5

### Five Optimization Questions

#### 1. Weighting: 0.6/0.4 Optimal?
**Current**: EMA3 (3-bar) 60%, EMA8 (8-bar) 40% — favors fast EMA.

**Analysis**: 
- In strong trends, both agree anyway; doesn't matter
- In consolidation, slower EMA carries more weight
- Static weighting ignores volatility regimes

**Test Plan**:
- 0.5/0.5 (equal weight) — removes fast-bias
- 0.7/0.3 (heavy fast) — only if trends dominate
- 0.4/0.6 (heavy slow) — only if consolidation dominates

**Expected**: +0.1–0.3% expectancy if regime-adaptive

#### 2. Thresholds: ±15/±5 Optimal?
**Current Problem**: 51.5% hit rate = barely above coin flip → **thresholds too loose**

**Grid Scan Recommended**:
| Config | STRONG | MODERATE | Rationale | Expected HR |
|---|---|---|---|---|
| Tight | ±12 | ±3 | Fewer false signals | 52.5–53.5% |
| Current | ±15 | ±5 | Baseline | 51.5% |
| Loose | ±18 | ±7 | Catch momentum only | 50–51% |

**Phase 1 ROI**: +0.2–0.5% expectancy from threshold tuning alone

#### 3. TRANSITIONING: 0.0 or Weak Signal?
**Current**: EMA3 and EMA8 slopes disagree → mapped to 0.0 (no opinion). **Wastes information.**

**Reality**: Disagreement = deceleration, not "no opinion":
- EMA3 > 0, EMA8 < 0 → momentum fading, risk of reversal
- EMA3 < 0, EMA8 > 0 → momentum accelerating down, early bounce warning

**Variants to Test**:
- 0.0 (current) — conservative
- ±0.25 (weak) — mild signal from faster EMA direction
- ±0.5 (strong) — treat as half-strength

**Expected**: +0.05–0.15% expectancy

#### 4. Acceleration Component?
**Idea**: Add slope-of-slope (how fast momentum is changing) at 10% weight.

**Formula**: `combined = main_signal × 0.9 + accel × 0.1`

**Use case**: STRONG UP + positive acceleration → lean more bullish; STRONG UP + negative acceleration → reduce confidence.

**Expected**: +0.05–0.1% expectancy

#### 5. ATR Scaling vs Pure Slope?
**Current**: Normalize slopes by ATR14 (volatility-relative)

**Pros**: Same thresholds work across high-vol and low-vol  
**Cons**: Very quiet days can inflate scaled slopes artificially

**Alternative**: Pure slope (raw 3-bar change)

**Recommendation**: Keep ATR scaling; test conditional scaling as fallback if Phase 1 threshold tuning doesn't solve negative edge.

---

## II. Fade Strategy (Page 30 Optimizer)

### Core Thesis
Extreme momentum (STRONG_UP, STRONG_DOWN) is **unsustainable**. Price snaps back.

### Signal Mapping
**Same EMA signal, opposite directional bet:**

| EMA State | Momentum | Fade |
|---|---|---|
| STRONG_UP (15+) | BUY +1.0 | SHORT -1.0 |
| MODERATE_UP (5–15) | LONG +0.5 | SHORT -0.5 |
| FLAT | 0.0 | 0.0 |
| MODERATE_DOWN (-15 to -5) | SHORT -0.5 | LONG +0.5 |
| STRONG_DOWN (-15–) | SELL -1.0 | LONG +1.0 |

### Why Fade Works
1. **Volatility clustering**: Large swings exhausted; reversions follow
2. **Order flow imbalance**: Institutional sellers on breakout failure, short covering on panic
3. **Sentiment extremes**: Greed/fear unsustainable; mean-reversion quick
4. **Structural levels**: Momentum peaks at resistance/support; fade the bounce

### Why Fade Fails
1. **Trending markets**: STRONG momentum multiple times in a row whipsaws faders
2. **Breakouts**: New trends start with extreme momentum; fade gets crushed
3. **News events**: Fundamental moves override mean-reversion thesis
4. **Sparse signals**: If ±15 rarely hit, few trade setups

**Mitigation**: Use combo strategies (momentum + fade together) to hedge.

### Fade Test Phases

**Phase 1: Baseline** (same config as momentum: 0.6/0.4, ±15/±5)
- Question: Does fade beat 50%?
- Success: HR > 50% + expectancy > -0.05%

**Phase 2: Tighter Thresholds** (±18, ±6)
- Question: Does fading only biggest extremes work better?
- Success: HR > 51%, expectancy > 0%

**Phase 3: Weighting + TRANS** (0.5/0.5, TRANS=±0.25)
- Question: Does rebalancing help?
- Success: Any improvement over Phase 2

**Phase 4: Combo Methods**
- Average: `(momentum + fade) / 2` → neutral when they disagree
- Voting: Use momentum for STRONG, fall back to fade for MODERATE
- Regime-switch: Fade in high-vol, momentum in low-vol
- Separate: 50% momentum, 50% fade portfolio

**Phase 5: Walk-Forward Validation** (split sample)
- Test on 2024 vs 2025, ensure edge holds out-of-sample

---

## III. Hourly Intraday Entry/Exit Layer

**Status**: Design phase (no code yet). Layers hourly 20-EMA for execution precision.

### Problem Solved
- Daily signals fire at EOD (3:30 PM) or next morning
- Miss intraday entry points (early morning move) or overstay late-day weakness
- Good direction but bad timing = painful drawdowns

### Architecture

```
Daily Signal (Direction)
  ↓
Hourly Entry/Exit (Timing)
  ↓
Position Manager (Size & Risk)
```

### Daily Signal (Unchanged)
- EMA3/EMA8 momentum at EOD
- Valid for 1–4 trading days or until next EOD signal
- Output: +1 (BUY), -1 (SHORT), 0 (FLAT)

### Hourly Layer (New)

**Proxy Indicators** (computed each hourly candle):
1. **20-EMA slope** (3-bar change on 1H scale)
2. **Hourly ATR14** (volatility on 1H window)
3. **Volume regime** (above/below 10-session MA)

**Entry Rules**:

**If daily says BUY (+1)**:
```
if 20ema_rising:
    → Buy at market immediately
elif price > 20ema:
    → Wait for pullback to 20ema, buy on touch (limit order)
elif price << 20ema:
    → Skip this hour; wait for setup to align
```

**If daily says SHORT (-1)**:
```
if 20ema_falling:
    → Short at market immediately
elif price < 20ema:
    → Wait for rally to 20ema, short on touch (limit order)
elif price >> 20ema:
    → Skip this hour; wait for setup to align
```

**Exit Rules**:
1. **Profit Target**: +0.5–1.0% move (2× hourly ATR)
2. **Stop Loss**: 1.5× hourly ATR below entry (for longs) or above entry (for shorts)
3. **Time Stop**: Exit if >4 hours in trade with <+0.2% gain
4. **Hourly Reversal**: 2-bar slope reversal (early exit signal)

### Expected Improvement
- **Intraday timing**: Avoid early-move whipsaws, exit on late-day weakness
- **Expected HR**: +1–2% improvement (51.5% → 52.5–53.5%)
- **Expected EXP**: +0.1–0.2% (timing = pure edge)

### 3-Phase Rollout
1. **Phase 1 (Manual Alerts)**: Algo alerts trader; trader decides on entry/exit
2. **Phase 2 (Semi-Auto)**: Algo alerts on setup; trader approves exit
3. **Phase 3 (Full Auto)**: Algo executes both entry and exit (requires risk guardrails)

---

## IV. Implementation Checklist

### Pages 29 & 30 (Optimizer UI)
- [x] Interactive threshold scanner
- [x] Manual variant testing
- [x] Weighting, transitioning, acceleration controls
- [ ] Walk-forward validation by year
- [ ] Export best variant to config.py

### Phase 1: Threshold Scan
**Effort**: 2–3 hours  
**Expected ROI**: +0.2–0.5% expectancy

1. Grid scan: test STRONG ∈ [12–20], MODERATE ∈ [2–8]
2. Report hit rate + expectancy for each combo
3. Pick top 3 candidates

### Phase 2: Combo Testing
**Effort**: 2–3 hours  
**Expected ROI**: +0.1–0.3% expectancy

1. Test momentum vs fade on best threshold combo from Phase 1
2. Test 4 combo methods (average, voting, regime, separate)
3. Walk-forward validate winners

### Phase 3: Intraday Layer (Future)
**Effort**: 4–6 hours (code only)  
**Expected ROI**: +0.1–0.2% expectancy  
(only if daily signal reaches >52% hit rate)

---

## V. Success Criteria

| Metric | Baseline | Target | Status |
|---|---|---|---|
| **Hit Rate** | 51.5% | >52.5% | TBD |
| **Expectancy** | -0.088% | >+0.05% | TBD |
| **Spearman ρ** | ? | >0.10 | TBD |
| **Walk-Forward** | — | Hold across years | TBD |

---

## VI. Risk Management

### Position Sizing
- Start small: untested strategies use 50% position
- Scale up if HR > 52% + expectancy > +0.05%

### Drawdown Limits
- Max daily loss: 0.5% account
- Max trade loss: 1% account
- If HR < 48% in a month: pause strategy

### Diversification
- Don't put all capital on one signal
- Combo strategies (momentum + fade) reduce correlation
- Consider RSI, Bollinger Bands for independent signals

---

## VII. Code References

| File | Function | Purpose |
|---|---|---|
| `analytics/signal_adapters.py:169–200` | `adapt_ema_momentum()` | Main momentum signal |
| `analytics/signal_adapters_fade.py:1–130` | `adapt_ema_momentum_fade()` | Fade signal (inverted) |
| `pages/29_EMA_Momentum_Optimizer.py` | Manual scanner | Test momentum variants |
| `pages/30_Fade_Strategy_Optimizer.py` | Fade + combo tester | Test fade and combos |
| `config.py` | (new section) | Store best thresholds |

---

## VIII. Next Steps

**Week 1**: Run Phase 1 (threshold grid scan) using page 29  
**Week 2**: Test fade + combos using page 30  
**Week 2–3**: Walk-forward validate winners on split sample  
**Week 3+**: Implement intraday layer if daily signal ≥ 52% HR

---

**Appendix: Signal Contract**
```
signal > 0  → expects HIGHER price over horizon
signal < 0  → expects LOWER price
signal = 0  → no opinion (excluded from stats)

hit_rate   = % of days where sign(signal) == sign(forward_return)
expectancy = mean(signal × return%) over active days
spearman   = rank correlation between signal and return
```
