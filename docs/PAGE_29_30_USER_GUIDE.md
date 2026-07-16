# Pages 29 & 30 User Guide — Momentum & Fade Optimizer

**How to use the interactive threshold scanners to test momentum and fade signals.**

---

## Page 29: EMA Momentum Optimizer

### What It Does
Interactive scanner to test different EMA momentum configurations (weights, thresholds, modes) and evaluate hit rate & expectancy on live/historical data.

### Parameter Guide

#### 1. EMA3 Weight (Slider: 0.3–0.8)
**What**: How much of the signal comes from the fast 3-bar EMA vs slow 8-bar EMA.

**Starting Recommendations**:
| Value | When to Use | Expected HR |
|---|---|---|
| 0.3 | Favor slow EMA; consolidation-heavy | ~50.5% |
| **0.5** | **Equal weight; neutral bias** | **~51.2%** |
| **0.6** | **Current production; fast bias** | **~51.5% (baseline)** |
| 0.8 | Extreme fast bias; trend-following | ~50.8% |

**How to interpret**: 
- Slider goes left (0.3) → EMA8 gets more say → slower response, fewer false signals
- Slider goes right (0.8) → EMA3 gets more say → faster response, more whipsaws
- The slider auto-normalizes: EMA8 = 1.0 - EMA3

**Test sequence**:
1. Start at 0.5 (equal), note hit rate
2. Move to 0.6 (current), compare
3. Try 0.4 and 0.7, see which wins
4. Pick the highest hit rate variant

#### 2. STRONG_UP Threshold (Slider: 8.0–25.0)
**What**: The momentum score needed to call a STRONG uptrend. Higher = fewer false signals, lower = catch more moves.

**Starting Recommendations**:
| Value | Signal Frequency | Expected HR | Notes |
|---|---|---|---|
| 12.0 | Many/day | 52–53% | **Try this first (tighter)** |
| 14.0 | Several/day | 51.5–52% | Moderate |
| **15.0** | **Moderate/day** | **~51.5%** | **Current baseline** |
| 18.0 | Few/day | 50–51% | Only extremes |
| 20.0 | Rare/week | ~49% | Too loose |

**How to interpret**:
- **Tight threshold (±12)**: Only VERY strong momentum → fewer signals, higher conviction
- **Medium threshold (±15)**: Current baseline; balance of signals vs quality
- **Loose threshold (±20)**: Too many false signals; rarely helps

**Critical insight**: Your baseline is 51.5% hit rate. If ±15 is baseline, try ±12 or ±13 first because tighter thresholds often improve hit rate (fewer noise trades).

**Test sequence**:
1. Set to 12 (tight), run test
2. If HR improves → **you've found an edge!**
3. If HR worse → try 14, 16, 18 incrementally
4. Pick value where HR > 51.5% + expectancy turns positive

#### 3. MODERATE_UP Threshold (Slider: 1.0–10.0)
**What**: The momentum score for "somewhat bullish" trades. STRONG_UP must be above this.

**Starting Recommendations**:
| Value | Relative to STRONG | Expected HR |
|---|---|---|
| 2.0–3.0 | Wide gap | 51–52% |
| **5.0** | **Gap = 10 (current ±15/±5)** | **~51.5%** |
| 6.0–7.0 | Narrower gap | 50.5–51% |

**Rule of thumb**: `MODERATE = STRONG / 3` (e.g., if STRONG = 12, use MODERATE = 4)

**Test sequence**:
1. If STRONG = 12, set MODERATE = 4
2. If STRONG = 15, set MODERATE = 5 (current)
3. Test; pick best combo by hit rate

#### 4. TRANSITIONING Mode (Dropdown)
**What**: How to handle situations where EMA3 and EMA8 slopes disagree (one up, one down).

**Options & When to Use**:

| Mode | Value | When to Choose | Expected HR Impact |
|---|---|---|---|
| **0.0 (no opinion)** | Ignore conflict | Conservative; don't guess | Current baseline |
| **weak (±0.25)** | Mild signal | Slight momentum fading; capture early reversals | +0.05–0.15% |
| **strong (±0.5)** | Half-signal | Aggressive; assumes deceleration = reversal setup | +0.1–0.2% |

**How to interpret**:
- **0.0**: When slopes disagree, output 0.0 signal (neutral)
- **0.25**: When EMA3 > 0 & EMA8 < 0 → output +0.25 (weak bullish); when EMA3 < 0 & EMA8 > 0 → output -0.25 (weak bearish)
- **0.5**: Same logic but doubled to ±0.5

**Hypothesis**: Disagreement isn't "no opinion" — it's deceleration. If EMA3 up but EMA8 flat, momentum is FADING, which might precede reversal.

**Test sequence**:
1. Start with 0.0 (current) as baseline
2. Try weak (±0.25) — smaller risk of overfitting
3. Try strong (±0.5) — only if weak improves hit rate
4. Pick mode with highest expectancy

#### 5. Acceleration (Checkbox)
**What**: Include the slope-of-slope (2nd derivative) to boost confidence in strong trends.

**How it works**: 
- If momentum is accelerating (getting stronger), boost signal confidence by 10%
- If momentum is decelerating (getting weaker), reduce confidence by 10%

**When to use**:
- ✓ Check box if you want to "lean harder" into confirmed trends
- ✗ Leave unchecked to stay conservative

**Expected impact**: +0.05–0.1% expectancy if real

**Test sequence**:
1. First run WITHOUT acceleration (baseline)
2. Then check the box (add 10% acceleration weight)
3. Compare hit rates — if better, keep it; if worse, uncheck it

#### 6. ATR-Scale Slopes (Checkbox)
**What**: Normalize momentum by daily volatility (ATR14).

**Checked (current)**:
- ✓ Higher ATR days get smaller scaled slopes
- ✓ Same thresholds work across high-vol and low-vol
- ✓ Fair comparison across market regimes

**Unchecked (pure slope)**:
- ✗ Raw slope in price points; regime-dependent thresholds needed
- ✗ Very quiet days inflate relative changes
- ✗ Harder to calibrate thresholds

**Recommendation**: Keep checked. ATR scaling is good; problem is thresholds, not scaling method.

---

### How to Run a Test

**Step 1: Set your parameters** (use recommendations above)
```
EMA3 Weight:        0.6 (current) or 0.5 (test equal)
STRONG_UP:          15 (current) or 12 (test tight)
MODERATE_UP:        5 (current)
TRANSITIONING:      0.0 (baseline) or weak (test weak)
Add acceleration:   ☐ (unchecked, baseline)
ATR-scale slopes:   ☑ (checked, baseline)
```

**Step 2: Click "Test This Configuration"**
- Streamlit will fetch 400 days of Nifty daily data
- Compute your signal variant
- Evaluate hit rate, expectancy, correlation

**Step 3: Review Results**
```
📊 RESULTS
Hit Rate %:     51.5%  (vs baseline 51.5%)
Expectancy %:   -0.088%  (vs baseline -0.088%)
Spearman ρ:     0.047  (low = weak signal)
n_active:       342 of 400  (days with signal)
```

**Step 4: Interpret**
- If Hit Rate > 51.5% → **Improvement! Note the parameters.**
- If Expectancy > 0% → **Edge found!**
- If Spearman > 0.1 → **Signal has real correlation with returns**

**Step 5: Save Best Variant**
- Screenshot or note the winning parameters
- You'll use them to commit to config.py once validated

---

### Recommended Test Sequence

**Session 1: Threshold Scan (30 min)**
```
Test 1:  STRONG=±12, MODERATE=±4  (tight thresholds)
Test 2:  STRONG=±13, MODERATE=±4  
Test 3:  STRONG=±14, MODERATE=±5
Test 4:  STRONG=±15, MODERATE=±5  (current baseline)
Test 5:  STRONG=±16, MODERATE=±5
Test 6:  STRONG=±18, MODERATE=±6  (loose)

→ Pick combo with highest Hit Rate > 51.5%
```

**Session 2: Weighting & TRANSITIONING (20 min)**
```
(Use best threshold from Session 1)

Test 7:  EMA Weight = 0.5 (equal)
Test 8:  EMA Weight = 0.4 (slow bias)
Test 9:  TRANSITIONING = weak (±0.25)
Test 10: TRANSITIONING = strong (±0.5)

→ Pick mode with highest Expectancy
```

**Session 3: Acceleration & Validation (20 min)**
```
(Use best params from Sessions 1–2)

Test 11: Add acceleration (10%)
Test 12: Final validation on full 400-day dataset

→ Report back: "Best config is STRONG=±X, MODERATE=±Y, TRANS=Z, HR=A%, EXP=B%"
```

---

## Page 30: Fade Strategy Optimizer

### What It Does
Fade (short) extreme momentum, expecting snap-back reversals. Compare fade vs momentum head-to-head and test combo strategies.

### Three Sections

#### Section 1: Momentum vs Fade Comparison

**What**: Side-by-side backtest of momentum (current strategy) vs fade (opposite bet).

**How to use**:
1. Click **"Compare Live on Latest Data"** button
2. Streamlit fetches 400 days, computes both signals
3. Shows:
   - Momentum Hit Rate (should be ~51.5%)
   - Fade Hit Rate (expect ~49–50%)
   - Expectancy for both

**What to expect**:
```
Momentum:  HR = 51.5%, EXP = -0.088%
Fade:      HR = 48.7%, EXP = -0.15%  (opposite bet, slightly worse)

Combo (50/50): HR = 50%, EXP = -0.12% (hedge but no edge)
```

**Interpretation**:
- If Fade HR > 50% + EXP positive → **fade works! Recalibrate.**
- If Fade HR < 48% → fade doesn't work yet; try next section

#### Section 2: Fade Configuration Tuner

**Same parameters as Page 29**, but tests FADE signal instead of momentum.

**Test these combinations**:

| STRONG | MODERATE | TRANS | Notes |
|---|---|---|---|
| ±15 | ±5 | 0.0 | Current baseline (for comparison) |
| ±18 | ±6 | 0.0 | Tighter; only biggest extremes |
| ±12 | ±4 | 0.0 | Looser; catch more fades |
| ±15 | ±5 | weak | Add weak signal handling |

**Test sequence**:
1. Run Test 1 (baseline) — should match momentum but inverted HR
2. Run Test 2–4, compare HR
3. Pick config with highest fade HR + positive expectancy

**Key insight**: Fade works differently than momentum. Momentum wins in trends (both EMAs agree). Fade wins in reversals (extremes snap back). You need tighter thresholds to fade only REAL extremes.

#### Section 3: Combo Analysis (Advanced)

**What**: Blend momentum + fade to hedge both strategies.

**Four combo methods**:

| Method | Formula | When to Use | Expected Benefit |
|---|---|---|---|
| **Average** | `(mom + fade) / 2` | Neutral when they disagree | Reduces drawdown |
| **Voting** | Use MOM if STRONG, fade if MODERATE | Confidence-based | Works if regimes separate |
| **Regime-Switch** | Use fade if ATR high, momentum if ATR low | Adaptive | Best if regimes real |
| **Separate 50/50** | Run both, size each at 50% | Capital-intensive | Lowest correlation |

**How to use**:
1. Click sliders to adjust thresholds for both momentum AND fade
2. Click **"Run Full Combo Analysis"** button
3. Streamlit shows all 4 combo methods compared

**What to expect**:
```
Momentum:          HR = 51.5%, EXP = -0.088%
Fade:              HR = 49.0%, EXP = -0.15%
──────────────────────────────────────────
Average:           HR = 50.0%, EXP = -0.12% (splits the difference)
Voting:            HR = 50.5%, EXP = -0.10% (slightly better)
Regime-Switch:     HR = 51.2%, EXP = -0.05% (adaptive win?)
Separate 50/50:    HR = 50.3%, EXP = -0.12% (hedged)
```

**Interpretation**:
- If **Regime-Switch HR > 51.5%** → **Use adaptive combo!** (fade in high-vol, momentum in low-vol)
- If all combos worse → momentum alone is best; stick with page 29

---

## Quick Decision Tree

**Q1: What's your goal?**
- Improve momentum signal (51.5% → 52%+) → Use **Page 29**
- Test fade strategy → Use **Page 30 Section 2**
- Blend both strategies → Use **Page 30 Section 3**

**Q2: How much time?**
- 30 min → Run threshold scans (Page 29, Session 1)
- 1 hour → Add weighting + transitioning tests (Page 29, Sessions 1–2)
- 2 hours → Test fade + combos (Page 30 Sections 2–3)

**Q3: What to commit first?**
1. Find threshold combo with HR > 52% + EXP > 0%
2. Walk-forward validate on split sample (2024 vs 2025)
3. Commit best variant to `config.py`
4. Update `pages/02` (main page) to use new thresholds

---

## Success Checklist

After testing, you should be able to say:

- [ ] "Threshold ±X/±Y beats baseline by +Z% hit rate"
- [ ] "Expectancy is now +W% (positive!)"
- [ ] "Spearman correlation ≥ 0.1 (signal has strength)"
- [ ] "Fade works / doesn't work" (clear answer)
- [ ] "Best combo is [average/voting/regime/separate]"

---

## Common Mistakes to Avoid

❌ **Don't**: Chase tiny improvements (0.1% in one test is noise)  
✓ **Do**: Require ≥ 0.3% improvement before getting excited

❌ **Don't**: Overfit to recent 400 days only  
✓ **Do**: Test on 2+ year backtest before committing

❌ **Don't**: Run 100 variants and pick the best (overfitting)  
✓ **Do**: Form hypothesis, test it, report results

❌ **Don't**: Ignore walk-forward splits  
✓ **Do**: Test on 2024 and 2025 separately to ensure edge holds

---

## Troubleshooting

**"Test button doesn't work / takes forever"**
- Kite API timeout → try again in 5 min
- 400 days is a lot; first run may take 30 sec
- Check Streamlit logs for errors

**"Hit rate went DOWN after I changed threshold"**
- Normal — many changes make signals worse
- Only commit changes where HR improves consistently

**"Expectancy still negative"**
- Hit rate alone isn't enough; expectancy = real edge
- Try tighter thresholds (±12) or add transitioning (weak mode)
- If still negative after all tweaks → maybe momentum signal is just noisy

---

**Next Step**: Run the optimizer and report back with best variant! 🚀
