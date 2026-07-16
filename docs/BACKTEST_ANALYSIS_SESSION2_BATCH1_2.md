# Backtest Analysis: All 24 Combinations (Batches 1 & 2)

**Date:** 2026-07-16  
**Total Combos Tested:** 24 (12 Momentum + 12 Fade)  
**Data Source:** Pages 29 & 30 batch backtest results  

---

## Executive Summary

🏆 **TWO WINNERS IDENTIFIED:**

| Strategy | Combo | Parameters | HR % | EXP % | Status |
|----------|-------|-----------|------|-------|--------|
| **Momentum** | 12 | ±12/±4, 0.6/0.4, weak trans, +10% accel | 51.2 | +0.0660 | ✅ BEST |
| **Fade** | 04 | ±18/±6, 0.5/0.5, NO weak trans | 52.6 | +0.0430 | ✅ BEST |

**Portfolio expectation:** Combined system likely exceeds 52% HR with positive EXP from both legs.

---

## Overall Rankings (Top 12)

| Rank | Strategy | Combo | HR % | EXP % | Key Feature |
|------|----------|-------|------|-------|------------|
| 1 | Momentum | 12_AllOptimized | 51.2 | +0.0660 | ±12/±4, weak trans, accel |
| 2 | Momentum | 05_WeakTrans | 50.6 | +0.0600 | ±12/±4, weak trans |
| 3 | Momentum | 09_WeakTrans | 50.2 | +0.0480 | ±15/±5, weak trans |
| 4 | Fade | 04_TightEqual | 52.6 | +0.0430 | ±18/±6, 0.5/0.5 |
| 5 | Fade | 03_TightV2 | 52.1 | +0.0310 | ±20/±7 |
| 6 | Fade | 02_TightV1 | 52.1 | +0.0300 | ±18/±6 |
| 7 | Fade | 01_Baseline | 52.3 | +0.0280 | ±15/±5, 0.6/0.4 |
| 8 | Fade | 07_Medium | 52.3 | +0.0280 | ±16/±5 |
| 9 | Fade | 08_Equal | 51.8 | +0.0270 | ±15/±5, 0.5/0.5 |
| 10 | Fade | 06_Accel | 51.7 | +0.0190 | ±18/±6, +10% accel |
| 11 | Fade | 10_Loose | 51.8 | +0.0130 | ±12/±4 |
| 12 | Fade | 11_LooseAccel | 51.2 | +0.0070 | ±12/±4, +10% accel |

---

## Strategy Comparison

### Momentum Performance
- **Mean HR:** 48.7% (below 50% breakeven)
- **Mean EXP:** -0.0016% (slightly underwater)
- **Positive combos:** 3/12 (only weak trans variants work)
- **Best:** Combo 12 at 51.2% HR, +0.0660% EXP

**Key insight:** Momentum is difficult to trade directly. Only weak TRANSITIONING (reduced conviction) enables profitability.

### Fade Performance
- **Mean HR:** 51.4% (above 50% breakeven)
- **Mean EXP:** +0.0133% (consistently profitable)
- **Positive combos:** 9/12 (most variants profitable!)
- **Best:** Combo 04 at 52.6% HR, +0.0430% EXP

**Key insight:** Fade is inherently superior. Mean-reversion works better than trend-following in this market regime.

---

## Critical Pattern: WEAK TRANSITIONING

### Effect on Momentum (POSITIVE ✅)

| Config | EXP % | W/O Weak Trans | Effect |
|--------|-------|-----------------|--------|
| ±12/±4 | +0.0600 | -0.0280 | **+8.8 bps** ⭐ LARGEST SWING |
| ±15/±5 | +0.0480 | -0.0280 | **+7.6 bps** |

**Why it works:** Weak TRANS reduces false signals from quiet consolidations, letting momentum only trigger on real conviction moves.

### Effect on Fade (NEGATIVE ❌)

| Config | EXP % | W/O Weak Trans | Effect |
|--------|-------|-----------------|--------|
| ±18/±6 | -0.0470 | +0.0300 | **-7.7 bps** (catastrophic) |
| ±15/±5 | -0.0480 | +0.0280 | **-7.5 bps** (catastrophic) |

**Why it fails:** Fade thrives on STRONG conviction. Weak TRANS sabotages it by triggering reversals on ambiguous moves.

### Implication
Weak TRANS is **strategy-dependent:**
- Momentum: ACTIVATE (reverses the sign!)
- Fade: NEVER use (kills profitability)

---

## Equal Weighting (0.5/0.5 vs 0.6/0.4)

### Momentum Effect
Minimal. Both 0.5/0.5 and 0.6/0.4 give similar results (~-0.028% to -0.027%).

### Fade Effect
Positive synergy with tight thresholds:
- **±18/±6:** +0.0300% (0.6/0.4) → **+0.0430% (0.5/0.5)** = **+1.3 bps boost** ⭐
- **±15/±5:** +0.0280% (0.6/0.4) → +0.0270% (0.5/0.5) = minimal change

**Interpretation:** Equal weighting amplifies fade's edge when thresholds are tight (±18/±6 is the sweet spot).

---

## Acceleration (+10% accel weight)

### Momentum Effect
Marginal positive:
- ±12/±4: -0.013% → -0.007% (+0.6 bps)
- ±18/±6: -0.030% → -0.019% (+1.1 bps)

**Conclusion:** Acceleration helps momentum slightly but isn't essential. Combo 05 (no accel) at +0.0600% EXP is nearly as good as Combo 12 (+0.0660%).

### Fade Effect
Slight negative:
- ±18/±6: +0.0300% → +0.0190% (-1.1 bps)
- ±12/±4: +0.0130% → +0.0070% (-0.6 bps)

**Conclusion:** Acceleration trades off slightly worse for fade. Smoothness > speed for mean reversion.

---

## Threshold Optimization

### For Momentum
- **±12/±4** (tight) = Best overall (Combo 12: +0.0660%)
- **±15/±5** (medium) = Solid second choice (Combo 09: +0.0480%)
- **±18/±6** (loose) = Underperforms

**Insight:** Momentum needs tight conviction to work (±12/±4 wins).

### For Fade
- **±18/±6** (medium-tight) = Best overall (Combo 04: +0.0430%)
- **±20/±7** (loose) = Close second (Combo 03: +0.0310%)
- **±12/±4** (tight) = Underperforms (only +0.013%)

**Insight:** Fade needs more room to work (±18/±6 is optimal, not too tight, not too loose).

---

## Recommended Configurations

### ✅ Momentum: Combo 12 (Primary)
```
Thresholds: ±12/±4
Weighting: 0.6/0.4 (EMA3:EMA8 weight)
Transitioning: WEAK (0.25 threshold)
Acceleration: +10% accel_weight
Result: 51.2% HR, +0.0660% EXP
```

**Why this works:**
1. Tight thresholds (±12/±4) = capture only genuine momentum
2. Weak TRANS = filter out false positives in consolidations (+8.8 bps boost!)
3. Acceleration = adds marginal stability (+0.6 bps)

**Alternative (simpler):** Combo 05 (skip acceleration, still +0.0600% EXP)

### ✅ Fade: Combo 04 (Primary)
```
Thresholds: ±18/±6 (medium-tight, looser than momentum)
Weighting: 0.5/0.5 (equal weight)
Transitioning: STRONG (default, never use WEAK)
Acceleration: NO accel
Result: 52.6% HR, +0.0430% EXP
```

**Why this works:**
1. Medium-tight thresholds (±18/±6) = room for mean reversion without excessive noise
2. Equal weighting (0.5/0.5) = +1.3 bps boost on fade edge
3. STRONG conviction = avoid weak TRANS (-7.7 bps penalty!)
4. No acceleration = fade needs smoothness, not speed

---

## Walk-Forward Validation Plan

To confirm these combos work on out-of-sample data:

### Phase 1: Time-Series Split
- **Train:** 2024 full year
- **Test:** 2025 YTD (Jan-May)

Run Combo 12 (momentum) + Combo 04 (fade) on split sample.

**Success criteria:**
- Momentum: Maintain >50% HR, positive EXP
- Fade: Maintain >51% HR, positive EXP
- No significant degradation from backtest results

### Phase 2: Forward Walk
After walk-forward passes, deploy both in production:
- Momentum for trending days (when EMA slopes are steep)
- Fade for consolidation days (when ranges are tight)

---

## Next Steps

### Immediate (This Session)
- [ ] Run walk-forward validation (2024 vs 2025) on both winners
- [ ] Create `config.py` entries for Combo 12 & Combo 04
- [ ] Code the combined strategy: "Use momentum when HR > 50%, fade otherwise"

### Medium Term
- [ ] Backtest the portfolio effect (momentum + fade together)
- [ ] Test intraday layer (hourly 20-EMA for entries) on both
- [ ] Live paper trading to verify fills + slippage assumptions

### Documentation
- [ ] Update strategy guide with final parameter sets
- [ ] Create trading rules doc: "When to use momentum vs fade"

---

## Key Learnings

1. **Fade > Momentum in this regime.** Mean reversion outperforms trend following by 2.4% in accuracy.

2. **Weak TRANS is NOT universal.** It's a game-changer for momentum (+8.8 bps) but toxic for fade (-7.7 bps). Context matters.

3. **Threshold selection is strategy-specific.** Momentum needs tight (±12/±4), fade needs medium (±18/±6).

4. **Equal weighting boosts fade, not momentum.** Only applies to fade with tight thresholds.

5. **Acceleration is nice-to-have, not essential.** Both strategies work without it; it adds marginal gains only.

6. **Simplicity wins.** Combo 05 (momentum without accel) is nearly as good as Combo 12 (+0.0600% vs +0.0660%).

---

## Consolidated Data Files

All 24 combos ranked and saved to:
- `all_combos_ranked.csv` (in scratchpad for reference)
- Interactive visualization: `viz_hr_vs_exp.html`
