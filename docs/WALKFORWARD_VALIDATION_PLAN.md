# Walk-Forward Validation Plan

**Objective:** Confirm Combo 12 (momentum) and Combo 04 (fade) maintain performance on unseen data.

---

## Test Configuration

### Combo 12: Momentum (Primary Winner)
```python
# Test params
thresholds_strong = (12, 4)      # ±12 up, ±4 down
thresholds_moderate = (?, ?)     # Derived from overall ratio
w_ema3 = 0.6
w_ema8 = 0.4
transitioning = "weak"           # Critical param
accel_weight = 0.1               # +10%
```

**Expected backtest result:** 51.2% HR, +0.0660% EXP (on full 2024-2025 data)

### Combo 04: Fade (Primary Winner)
```python
# Test params
thresholds_strong = (18, 6)      # ±18 up, ±7 down
thresholds_moderate = (?, ?)     # Derived from overall ratio
w_ema3 = 0.5
w_ema8 = 0.5
transitioning = "strong"         # NEVER weak for fade
accel_weight = 0.0               # No acceleration
```

**Expected backtest result:** 52.6% HR, +0.0430% EXP (on full 2024-2025 data)

---

## Phase 1: Train/Test Split

### Train: 2024 Full Year
- Run both combos on 2024 daily OHLCV
- Expected: Momentum ~50-51% HR, Fade ~51-52% HR
- Document any seasonal patterns (Q1 vs Q4)

### Test: 2025 YTD (Jan-May)
- Run SAME parameter sets on 2025 data (no reoptimization)
- Success if HR/EXP within 2% of train results
- Failure if one combo's HR drops below 50% or goes negative EXP

### Acceptance Criteria

| Metric | Momentum | Fade | Status |
|--------|----------|------|--------|
| Train HR | 50-52% | 51-53% | To test |
| Test HR | >48% | >50% | Pass threshold |
| Train EXP | +0.04% to +0.08% | +0.02% to +0.05% | To test |
| Test EXP | Positive | Positive | Required |
| Correlation (train→test) | >0.8 | >0.8 | To measure |

---

## Phase 2: Forward Walk

If both pass Phase 1:

### Live Testing (Virtual)
1. Simulate 2026 YTD trades using Combo 12 + Combo 04
2. Track hit rate, expectancy, slippage assumptions
3. Monitor for regime change (is mean reversion still dominant?)

### Deployment Readiness
- HR maintained above acceptance threshold ✅
- EXP stays positive ✅
- No catastrophic loss scenarios detected ✅

---

## Implementation Strategy

### Step 1: Create Config Entries
```python
# config.py (or equivalent)

MOMENTUM_CONFIG_COMBO12 = {
    "name": "EMA_Momentum_Combo12",
    "thresholds_strong": (12, 4),
    "w_ema3": 0.6,
    "w_ema8": 0.4,
    "transitioning": "weak",
    "accel_weight": 0.1,
    "expected_hr": 0.512,
    "expected_exp": 0.000660,
}

FADE_CONFIG_COMBO04 = {
    "name": "Fade_Combo04",
    "thresholds_strong": (18, 6),
    "w_ema3": 0.5,
    "w_ema8": 0.5,
    "transitioning": "strong",
    "accel_weight": 0.0,
    "expected_hr": 0.526,
    "expected_exp": 0.000430,
}
```

### Step 2: Backtest Script
Create `scripts/validate_combo12_combo04.py`:
- Input: CSV of daily OHLCV for 2024, 2025
- Split at 2025-01-01
- Run both combos, output HR/EXP for each period
- Generate train/test comparison table

### Step 3: Run Validation
```bash
python scripts/validate_combo12_combo04.py data/nifty_daily_2024_2025.csv
```

Expected output:
```
=== COMBO 12: MOMENTUM ===
Train (2024): 51.2% HR, +0.0660% EXP, n=252
Test  (2025): 50.8% HR, +0.0645% EXP, n=130
Degradation: -0.4% HR, -0.2 bps EXP ✅ PASS

=== COMBO 04: FADE ===
Train (2024): 52.6% HR, +0.0430% EXP, n=252
Test  (2025): 52.1% HR, +0.0420% EXP, n=130
Degradation: -0.5% HR, -1.0 bps EXP ✅ PASS

Portfolio Effect: 51.9% HR combined, +0.055% EXP
```

---

## Decision Tree

```
Does Combo 12 (Momentum) pass walk-forward? 
├─ YES: HR > 48%, EXP > 0
│  └─ PROCEED: Deploy as primary momentum entry
└─ NO: 
   └─ PAUSE: Revert to baseline, investigate degradation

Does Combo 04 (Fade) pass walk-forward?
├─ YES: HR > 50%, EXP > 0
│  └─ PROCEED: Deploy as primary fade entry
└─ NO:
   └─ PAUSE: Revert to baseline, investigate degradation

Both pass?
├─ YES: 
│  └─ PORTFOLIO: Code combined strategy
│     - Momentum on trending days
│     - Fade on consolidation days
│     - Expected combined HR: 52%+
└─ NO:
   └─ SINGLE: Deploy whichever passes, disable failing one
```

---

## Monitoring During Live Deployment

Once both combos are live, monitor:

### Weekly Checks
- Actual HR vs expected (should stay within 2%)
- Actual EXP vs expected (should stay positive)
- Win streak (max consecutive losses shouldn't exceed 10)

### Monthly Reviews
- Compare 30-day rolling metrics vs baseline
- Check for seasonal patterns
- Verify momentum vs fade split is balanced

### Red Flags
- HR drops below 48% → investigate signal quality
- EXP turns negative → regime change detected
- Spearman rho drops below -0.05 → poor market fit

---

## Timeline

- **Session 2 (now):** Create validation scripts
- **Session 3:** Run 2024 train backtests
- **Session 4:** Run 2025 test backtests
- **Session 5:** If pass, deploy both to config
- **Live monitoring:** Track metrics weekly

---

## Reference

- **Source:** `docs/BACKTEST_ANALYSIS_SESSION2_BATCH1_2.md`
- **Combos:** Momentum Combo 12, Fade Combo 04
- **Data:** See `pages/29_EMA_Momentum_Optimizer.py` and `pages/30_Fade_Strategy_Optimizer.py` for signal logic
