# Fade Strategy — Mean-Reversion Complement to Momentum

**Concept**: Fade (short) extreme EMA momentum, expecting snap-back reversals.

**Status**: TBD — optimizer built, waiting for backtest results.

---

## Strategy Logic

### Core Thesis
Extreme momentum (STRONG_UP, STRONG_DOWN) is **unsustainable**. Price tends to snap back.

### Signal Mapping (Opposite of Momentum)

| EMA Momentum State | Signal Strength | Momentum Bet | **Fade Bet** |
|---|---|---|---|
| STRONG_UP (15+) | Very confident | +1.0 (BUY) | **-1.0 (SHORT)** |
| MODERATE_UP (5-15) | Somewhat | +0.5 (long) | **-0.5 (short)** |
| FLAT/TRANS | No opinion | 0.0 | **0.0** |
| MODERATE_DOWN (-15 to -5) | Somewhat | -0.5 (short) | **+0.5 (long)** |
| STRONG_DOWN (-15-) | Very confident | -1.0 (SELL) | **+1.0 (LONG)** |

**Key insight**: Same EMA signal, opposite directional bet.

---

## Why Fade Works (Theory)

### 1. Volatility Clustering
- Large intraday swings (up 300+ pts) are followed by consolidation
- Exhaustion: sellers overwhelmed, then buyers take control
- Reversion: whipsaw creates 1-2 day snap-back

### 2. Order Flow Imbalance
- STRONG_UP: institutional sellers triggered on breakout failure
- STRONG_DOWN: short covering or panic buying at support
- Both create violent countertrend move

### 3. Fear/Greed Extremes
- STRONG momentum = crowd behavior (FOMO, panic selling)
- Extreme greed/fear = unsustainable; reversal soon
- Fade = betting on mean-reversion of sentiment

### 4. Structural Levels
- Momentum peaks at resistance/support
- Fade = sell the resistance bounce, buy the support bounce
- ATR-normalized thresholds catch regime-specific extremes

---

## Why Fade Fails (Counterargument)

### 1. Trending Markets
**Problem**: In strong 3-5 day uptrends, STRONG_UP reads many times in a row.
- Fade the 1st STRONG_UP → whipsawed by 2nd and 3rd
- Hit rate suffers when trend is genuine

**Mitigation**: Use **combo** (momentum + fade) so strong trends don't consistently lose

### 2. Breakouts
**Problem**: New bull/bear market starts with extreme momentum → no immediate reversion
- Gap up + STRONG_UP → faders crushed
- Requires regime detection (is this a new trend or bounce?)

**Mitigation**: Regime-switch combo (use momentum in early breakouts, fade consolidation)

### 3. News Events
**Problem**: Earnings, RBI decisions, global shocks print STRONG momentum that persists
- Fade = fighting the fundamental move
- Can't overcome information asymmetry

**Mitigation**: Avoid trading around scheduled events; fade quiet/normal-vol days

### 4. Sparse Signals
**Problem**: If EMA momentum rarely hits ±15, few trade setups
- High-conviction trades are rare
- But maybe that's good (fewer false signals)?

**Mitigation**: Lower thresholds (±12, ±10) to increase frequency vs hit rate trade-off

---

## Optimizer Variants to Test

### Phase 1: Baseline Fade Config
- Same weights/thresholds as momentum (0.6/0.4, ±15/±5)
- ATR-scaled
- TRANS = 0.0
- Expectation: Lower hit rate than momentum (opposite bet)

### Phase 2: Tighter Thresholds
- STRONG = ±18 (fade only biggest extremes)
- MODERATE = ±6 (reduce false taps)
- Rationale: Only extreme momentum reverts; medium moves can continue

### Phase 3: Weighting Variants
- 0.5/0.5: Equal weight both EMAs
- 0.4/0.6: Favor slower EMA (longer reversal horizon?)

### Phase 4: TRANSITIONING = Weak Signal
- Map TRANS to ±0.25 (not 0.0)
- Theory: Deceleration is also a fade setup (momentum fading = reversal near)

### Phase 5: Combo Strategies
- **Average**: (momentum + fade) / 2 = neutral when they disagree
- **Voting**: Use momentum when STRONG, fall back to fade when MODERATE
- **Regime-Switch**: Use momentum in trending markets, fade in range-bound
- **Separate Allocations**: 50% momentum, 50% fade portfolio

---

## Expected Performance

### Momentum vs Fade: Theoretical
| Market Regime | Momentum HR | Fade HR | Winner |
|---|---|---|---|
| **Strong Uptrend** | 55%+ | 45%- | Momentum wins big |
| **Strong Downtrend** | 55%+ | 45%- | Momentum wins big |
| **Consolidation** | 48%- | 52%+ | Fade wins slightly |
| **High Volatility** | 50-52% | 48-50% | Momentum (barely) |
| **Low Volatility** | 51%- | 49%+ | Toss-up |

**Blended**: If you hold both 50/50, you hedge tail risks but reduce max payoff.

---

## Combination Strategies

### 1. Simple Average: (MOM + FADE) / 2
**Pros**:
- When momentum and fade agree (both in same direction), confidence high
- Neutral when they disagree → avoids whipsaws

**Cons**:
- Cuts edge in half (if MOM=+0.3%, average = +0.15%)
- Spreads positions across both

**Expected**: ~+0.05% to +0.15% expectancy if both are ~zero

### 2. Confidence Voting
```
if |momentum| > 0.75 (high confidence):
    use momentum signal
else:
    use fade signal
```

**Pros**:
- Momentum takes strong directional calls
- Fade fills in weak/moderate momentum with reversal read

**Cons**:
- Fade takes the hardest cases (weak momentum = ambiguous)
- May pile fade losses

**Expected**: Varies by which regime (trending vs range)

### 3. Regime-Switch Adaptive
```
atr = rolling_20(atr14)
if atr14 > atr:  # high volatility
    use fade  (reversions happen quick)
else:  # low volatility
    use momentum  (trends persist)
```

**Pros**:
- Theoretically adaptive
- Fade high-vol spike-reversals; ride low-vol trends

**Cons**:
- Complex; hard to walk-forward validate
- Overfitting risk in regime detection

**Expected**: +0.1% to +0.3% if regimes truly separate

### 4. Separate Portfolio (50% Allocations)
- Position 1: Long 50% of size on momentum signal
- Position 2: Long 50% of size on fade signal
- Both trade simultaneously, hedge each other

**Pros**:
- Clear risk separation
- Both edges compound (if both are positive)
- Reduces drawdown from either strategy failing alone

**Cons**:
- Requires 2× position management
- Margin/capital intensity

**Expected**: +0.1% to +0.2% from diversification (lower correlation)

---

## Implementation Checklist

### Pages 30 (Fade_Strategy_Optimizer.py)
- [x] Momentum vs Fade comparison UI
- [x] Fade config tuner (thresholds, weighting)
- [x] Combo methods tester (average, voting, regime, separate)
- [ ] Walk-forward validation per variant
- [ ] Export best variant to config.py

### Analytics Layer
- [x] `signal_adapters_fade.py`: Fade adapter
- [ ] `fade_backtests.py`: Batch testing of all phases
- [ ] Combo signal adapter: `signal_adapters_combo.py`

### Config Updates
- [ ] Add FADE_* thresholds to `config.py`
- [ ] Add COMBO_MODE selector

---

## Phase-by-Phase Test Plan

### Phase 1: Baseline Fade (Week 1)
**Config**: Same as momentum (0.6/0.4, ±15/±5)
**Question**: Does fading opposite direction beat 50% hit rate?
**Success**: HR > 50% + expectancy > -0.05% (margin of error)

### Phase 2: Threshold Tuning (Week 1-2)
**Variants**: ±12, ±14, ±16, ±18 (STRONG); ±3, ±4, ±5, ±6 (MODERATE)
**Question**: Do tighter thresholds (fade only biggest moves) work better?
**Success**: HR > 51%, expectancy > 0%

### Phase 3: Weighting & Transitioning (Week 2)
**Variants**: 0.5/0.5 weight; TRANS = weak ±0.25
**Question**: Does rebalancing signal composition help fade?
**Success**: Any improvement over Phase 2 winner

### Phase 4: Combo Methods (Week 2-3)
**Variants**: Average, voting, regime-switch, separate allocations
**Question**: Can combining hedge tail risks while keeping edge?
**Success**: Combo HR > both individuals, or lower drawdown

### Phase 5: Walk-Forward Validation (Week 3)
**Setup**: Test Phase 4 winners on split sample (2022-2023 vs 2024)
**Question**: Does edge hold out-of-sample, or overfitted?
**Success**: Both splits have similar HR/EXP (within ±1pp, ±0.05%)

---

## Risk Management

### Position Sizing
- Start small: fade = untested, use 50% position vs momentum
- Scale up if HR > 52% + EXP > +0.05%

### Stop Losses
- Fade SHORT (expecting down): stop above recent swing high
- Fade LONG (expecting up): stop below recent swing low
- Trail: use 1.5× ATR as trail

### Drawdown Limits
- Max daily loss: 0.5% account
- Max trade loss: 1% account
- If fade hit rate < 48% in a month: pause strategy

### Diversification
- Don't put all position size on fade alone
- Combo with momentum reduces correlation
- Consider independent signals (RSI, BB) for diversification

---

## Hourly Intraday Entry/Exit (Future)

Current fade/momentum are **daily signals** (EOD read, next-day execution).

**Enhancement**: Use **hourly proxy EMAs** for:
- **Entry timing**: Daily says FADE SHORT, wait for hourly pullback to 20-EMA then enter
- **Exit timing**: Take profit 0.5% reversal, or exit on hourly trend reversal
- **Stop placement**: Hourly reversal + 1× ATR

(See next section: Intraday Layer Design)

---

## Next: Hourly Intraday Layer

Once fade optimizer settles and we know which combo works best, we can layer:

1. **Daily signal**: Momentum or Fade
2. **Hourly entry**: Wait for pullback to 20-EMA (intraday) to confirm entry
3. **Hourly exit**: 
   - Take profit: +0.5% to +1.0% move
   - Stop loss: Hourly close below entry ± 0.3% ATR
   - Time stop: Exit if >4 hours in trade with <+0.1%

This adds **intraday precision** without changing the daily directional bet.

---

**Status**: Waiting for optimizer runs. Update as results come in.
