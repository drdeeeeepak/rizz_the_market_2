# EMA Momentum Optimization — Analysis & Recommendations

**Status**: Current performance is 51.5% hit rate, -0.088% expectancy (slightly negative edge).

**Goal**: Improve edge to >52% hit rate and positive expectancy.

---

## Executive Summary: Five Questions & Answers

### 1. **Is the 0.6/0.4 weighting (EMA3/EMA8) optimal? Should it be dynamic?**

**Current State**:
- EMA3 (3-period) gets 60%, EMA8 (8-period) gets 40%
- Favors the faster (shorter) moving average
- Static — same weighting in all regimes

**Analysis**:
- **Pro (0.6/0.4)**: Fast momentum usually leads trend turns; weighting it higher makes sense
- **Con**: In consolidation, slower EMA has more signal power; in strong trends, both agree anyway
- **Static weakness**: High volatility vs quiet regimes don't adjust weighting

**Recommendation**:
1. **First test**: Try 0.5/0.5 equal weighting (removes directional bias toward fast EMA)
2. **Second test**: Try regime-dependent weighting:
   - Strong trends (cluster spread > 2×ATR): 0.7/0.3 (trust fast)
   - Consolidation (cluster spread < 0.5×ATR): 0.4/0.6 (trust slow)
   - Normal: 0.6/0.4 (baseline)

**Expected impact**: +0.1% to +0.3% expectancy if regime-weighted.

**Code location**: `analytics/signal_adapters.py:189` — combined formula

---

### 2. **What are the actual threshold values in config.py? Are they optimized?**

**Current Thresholds** (`analytics/ema.py:92-95`):
```python
MOM_STRONG_UP_THRESH   = +15.0  # % ATR/day
MOM_MODERATE_UP_THRESH =  +5.0
MOM_MODERATE_DN_THRESH =  -5.0
MOM_STRONG_DN_THRESH   = -15.0
```

**Analysis of 51.5% hit rate**:
- Barely above 50% coin flip = thresholds are likely **too loose** (too many false signals)
- Three possible root causes:
  1. ±15/±5 are wrong absolute values
  2. Thresholds don't account for regime (high-vol vs low-vol)
  3. Weighted average (0.6/0.4) creates noise

**Historical threshold scan needed**:
| Thresholds | Rationale | Expected HR |
|---|---|---|
| ±12/±3 (tighter) | Fewer false signals; higher confidence trades | 52.5%–53.5% |
| ±15/±5 (current) | Current baseline | 51.5% |
| ±18/±4 (asymmetric) | UP requires more confidence; DN is hair-trigger | TBD |
| ±20/±8 (looser) | Catch only strongest moves | 50.0%–51.0% |

**Recommendation**:
1. **Grid scan**: Test ±12, ±13, ±14, ±15, ±16, ±18 for STRONG and ±2→±6 for MODERATE
2. **Volatility adjustment**: Scale thresholds by (ATR14 / 20-day avg ATR) if not already
3. **Stop loss integration**: Tighter thresholds may help; looser ones catch follow-through

**Code location**: `analytics/ema.py:92-95` — can be moved to `config.py` for easy tuning

---

### 3. **Does TRANSITIONING really deserve 0.0, or is it a valid weak signal?**

**Current State** (`analytics/signal_adapters.py:195-196`):
```python
transitioning = (ema3_slope > 0) != (ema8_slope > 0)  # slopes disagree
state[transitioning] = "TRANSITIONING"
# ... mapped to 0.0
```

**What TRANSITIONING means**:
- EMA3 > 0 AND EMA8 < 0 → price momentum fading; risk of reversal
- EMA3 < 0 AND EMA8 > 0 → momentum reversing; early sign of bounce

**Current problem**: Mapped to 0.0 = **throws away information**.

**Analysis**:
- Disagreement ≠ "No opinion"
- Instead: **Weakly bullish or weakish bearish**
  - If EMA3 > 0: Momentum still up, so weight it +0.25 (weak long)
  - If EMA3 < 0: Momentum still down, so weight it -0.25 (weak short)

**Three variants to test**:

| Transitioning Handling | Value | Rationale |
|---|---|---|
| **0.0 (current)** | No signal | Conservative; loses information |
| **weak (±0.25)** | 0.25 × sign(EMA3) | Mild signal from direction of faster EMA |
| **strong (±0.5)** | 0.5 × sign(EMA3) | Treat as half-strength signal |

**Recommendation**:
Test **weak (±0.25)** first:
- Adds information without overcommitting
- In consolidation (frequent TRANSITIONING), provides low-confidence reads
- Expected gain: +0.05% to +0.15% expectancy if actual info is there

**Code location**: `analytics/signal_adapters.py:166` — `_MOM_SIGN` mapping

---

### 4. **Should we add an acceleration check (3-bar slope of the slope)?**

**Idea**: Second derivative = how fast momentum is changing.

**Formula**:
```
accel = (slope[t] - slope[t-3]) / 3
```

**Hypothesis**:
- High positive acceleration → momentum strengthening → **lean more bullish**
- Negative acceleration → momentum fading → **reduce confidence**

**Implementation strategy**:

1. **Component weight** (0–25%):
   - 0%: ignore acceleration (current)
   - 10%: mild boost (5% acceleration impact on total signal)
   - 25%: strong boost (1:3 ratio with primary slope)

2. **Example with 10% weight**:
   ```
   combined = (0.6×ema3_scaled + 0.4×ema8_scaled) × 0.9 + accel_scaled × 0.1
   ```

3. **Use case**: 
   - STRONG UP (15) + positive accel → UP_ACCELERATING (weight ↑ to +1.2?)
   - STRONG UP (15) + negative accel → UP_DECELERATING (weight ↓ to +0.8?)

**Recommendation**:
1. Start with 10% acceleration weight (conservative)
2. Threshold scan becomes: test with/without accel, compare HR
3. Expected impact: **+0.05% to +0.1%** expectancy if acceleration correlates with follow-through

**Code location**: Would be added to `adapt_ema_momentum()` in `signal_adapters.py`

---

### 5. **Does ATR scaling make sense, or should it be pure slope?**

**Current State** (`signal_adapters.py:189`):
```python
combined = (ema3_slope / atr * 100) * 0.6 + (ema8_slope / atr * 100) * 0.4
```

**Pros of ATR scaling**:
✓ Volatility-adjusted (high-vol days don't always = strong momentum)
✓ Same thresholds work across all volatility regimes
✓ Handles quiet days vs explosive days fairly

**Cons of ATR scaling**:
✗ Very quiet days (ATR=5, slope=2) → 2/5×100 = 40 (huge scaled slope!)
✗ Can flip signals on low-volatility consolidations
✗ Thresholds become indirect (±15 in ATR-scaled space is opaque)

**Alternative: Pure slope** (no ATR):
```python
combined = (ema3_slope) * 0.6 + (ema8_slope) * 0.4
```

**Pros**:
✓ Direct: threshold ±0.10 = 10 pts/bar of 3-bar change
✓ Regime-independent
✓ More intuitive to backtestors

**Cons**:
✗ Same threshold across all volatility regimes
✗ Need separate thresholds for high-vol (Nifty 300pts range) vs low-vol (50pts range)

**Recommendation**:
1. **Keep ATR scaling** for the main signal (it's working, just needs threshold tuning)
2. Test as alternative/comparison if tighter thresholds don't help enough
3. **Better alternative**: Conditional scaling
   ```python
   if atr > 100-day-median(atr):  # high vol
       scale = atr / 100-day-median(atr)  # scale UP slightly
   else:
       scale = 0.8  # low vol gets less scaling
   ```

**Code location**: `signal_adapters.py:186-189`

---

## Recommended Test Plan

### Phase 1: Threshold Optimization (Highest ROI)
**Effort**: 2-3 hours (grid scan)
**Expected impact**: +0.2% to +0.5% expectancy

1. Create threshold grid:
   ```
   strong_up ∈ [12, 13, 14, 15, 16, 17, 18, 20]
   moderate_up ∈ [2, 3, 4, 5, 6, 7, 8]
   (symmetric for down)
   ```

2. Test each combination on 2-4 years of historical daily data
3. Report hit rate + expectancy for each
4. **Commit best thresholds** to `config.py`

### Phase 2: Weighting Variants
**Effort**: 1-2 hours
**Expected impact**: +0.1% to +0.3% expectancy

Test these weights:
- 0.6/0.4 (current)
- 0.5/0.5 (equal)
- 0.7/0.3 (heavy fast)
- 0.4/0.6 (heavy slow)

### Phase 3: TRANSITIONING Signal Treatment
**Effort**: 30 min
**Expected impact**: +0.05% to +0.15% expectancy

Test:
- 0.0 (current)
- 0.25 (weak)
- 0.5 (strong)

### Phase 4: Acceleration Component
**Effort**: 1 hour
**Expected impact**: +0.05% to +0.1% expectancy

Test 10% and 25% acceleration weighting with best thresholds from Phase 1

### Phase 5: Pure Slope (if Phase 1-4 still negative)
**Effort**: 2-3 hours
**Expected impact**: TBD (high variance; only if other phases don't solve it)

---

## Implementation Checklist

### For Pages 29 (EMA_Momentum_Optimizer.py)
- [x] Interactive threshold scanner UI
- [x] Manual variant testing (compute + evaluate)
- [x] Weighting sliders
- [x] Transitioning mode selector
- [x] Acceleration toggle
- [ ] Walk-forward validation (split by year)
- [ ] Export best variant to config.py

### For analytics/signal_adapters.py
- [ ] Support variant weighting (currently hardcoded 0.6/0.4)
- [ ] Support TRANSITIONING options (currently hardcoded 0.0)
- [ ] Optional acceleration component
- [ ] Optional pure-slope mode (fallback)

### For analytics/ema.py
- [ ] Move threshold constants to config.py for easy tuning
- [ ] Document what "% ATR/day" means (normalized by daily ATR14)

### For config.py
- [ ] Add MOM_THRESHOLDS dict with variants
- [ ] Add EMA_MOM_WEIGHTING config
- [ ] Add EMA_MOM_TRANSITIONING mode

---

## Risk & Gotchas

### Watch Out For:
1. **Overfitting to recent data**: Always walk-forward validate (test on out-of-sample years)
2. **Threshold chasing**: If HR drops from 51.5% → 51.3% across most changes, thresholds aren't the issue
3. **ATR edge cases**: Very low ATR (< 5) can create huge scaled slopes; check filtering
4. **Regime blindness**: Same thresholds may work for bull years but fail in bear years
5. **TRANSITIONING trap**: Using ±0.25 may introduce too much noise; start with 0.0 and increment

### Validation Rules:
- Backtest on **2+ years** of data (minimum)
- Walk-forward split by year (in-sample vs out-of-sample)
- Require **>52% hit rate** before claiming improvement
- Require **>0% expectancy** (positive edge)
- Report Spearman correlation (should be >0.1 if signal is real)

---

## Code References

| File | Function | What to Modify |
|---|---|---|
| `analytics/signal_adapters.py:169–200` | `adapt_ema_momentum()` | Main signal adapter; weights & transitioning |
| `analytics/ema.py:92–95` | Constants | Thresholds (move to config.py) |
| `config.py` | (new section) | Add MOM_* thresholds & mode flags |
| `pages/29_EMA_Momentum_Optimizer.py` | (new page) | Interactive scanner UI |

---

## Next Steps

1. **This week**: Run Phase 1 (threshold grid scan) using pages/29
2. **Document findings** in a simple table (threshold → HR, EXP, ρ)
3. **Pick top 3 candidates** and walk-forward validate
4. **Commit best variant** to main config.py once validated
5. **Update pages/02** to use new thresholds if improvement > +0.1% expectancy

---

## Questions for Data Review

After running Phase 1 scan, ask:
- "Why does ±14/±4 win? Is it coincidence or real structure?"
- "Does best variant hold across bull/bear/range-bound years?"
- "At what hit rate does expectancy turn positive? (≈52%? 53%?)"
- "Is ATR scaling actually helping, or just hiding bad thresholds?"

---

**Appendix**: Signal Contract

From `analytics/signal_lab.py`:
```
SIGNAL CONTRACT:
  > 0      → the adapter believes price will be HIGHER over horizon
  < 0      → believes LOWER
  0 / NaN  → no opinion that day (excluded from stats)

EVALUATION:
  hit_rate   = % of signal-active days where sign(ret) == sign(signal)
  expectancy = mean(sign(signal) × ret%) over active days
  spearman   = rank correlation between raw signal and forward return
```
