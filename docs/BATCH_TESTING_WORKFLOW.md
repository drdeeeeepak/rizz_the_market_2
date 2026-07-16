# Batch Testing Workflow — Pages 29 & 30

**Goal**: Test 12 parameter combinations per page (momentum + fade = 24 total) systematically and compare results.

---

## Quick Start

### Page 29: Momentum Optimizer

**12 pre-defined combinations:**

1. **01_Baseline** — Current production (0.6/0.4, ±15/±5, TRANS=0.0, Accel=0%)
2. **02_Tight_v1** — ±12/±4 thresholds (first test here for tighter)
3. **03_Tight_v2** — ±13/±4 thresholds
4. **04_Tight_Equal** — ±12/±4 + equal weighting (0.5/0.5)
5. **05_Tight_WeakTrans** — ±12/±4 + weak transitioning
6. **06_Tight_Accel** — ±12/±4 + 10% acceleration
7. **07_Moderate** — ±14/±5 (between tight and baseline)
8. **08_EqualWeight** — Equal weighting (0.5/0.5) on baseline
9. **09_WeakTrans** — Baseline + weak transitioning only
10. **10_Loose** — ±18/±6 (looser thresholds)
11. **11_Loose_Accel** — ±18/±6 + acceleration
12. **12_AllOptimized** — ±12/±4 + weak trans + acceleration (combines all improvements)

### Page 30: Fade Optimizer

**12 fade combinations** (similar structure, but optimized for mean-reversion):

1. **01_Baseline_Fade** — Current (0.6/0.4, ±15/±5, TRANS=0.0, Accel=0%)
2. **02_Tight_v1** — ±18/±6 (fade needs looser = higher thresholds)
3. **03_Tight_v2** — ±20/±7 (even tighter for fade)
4. **04_Tight_Equal** — ±18/±6 + 0.5/0.5
5. **05_Tight_WeakTrans** — ±18/±6 + weak trans
6. **06_Tight_Accel** — ±18/±6 + acceleration
7. **07_Medium** — ±16/±5
8. **08_EqualWeight** — 0.5/0.5 on baseline
9. **09_WeakTrans** — Baseline + weak trans
10. **10_Loose** — ±12/±4 (inverted logic from momentum)
11. **11_Loose_Accel** — ±12/±4 + acceleration
12. **12_AllOptimized** — ±20/±7 + weak trans + acceleration

---

## Workflow

### Step 1: Select Combinations (Page 29)

```
Open Page 29 → Tab: "🔧 Threshold Scanner"
↓
Dropdown: "Select combinations to test (max 5 at a time)"
↓
Choose 5 combos:
  ☑ 01_Baseline
  ☑ 02_Tight_v1
  ☑ 03_Tight_v2
  ☑ 04_Tight_Equal
  ☑ 05_Tight_WeakTrans
```

### Step 2: Run Batch Backtest

```
Click "🚀 Run Batch Backtest"
↓
Streamlit fetches 400 days of Nifty data
↓
Tests all 5 combinations (each computes signal + evaluates)
↓
Shows results table with:
  - Combo name
  - Hit Rate %
  - Expectancy %
  - Spearman ρ
  - n_active (days with signal)
  - n_total (total days tested)
```

### Step 3: Download CSV

```
Click "📥 Download Results CSV"
↓
File saved: momentum_backtest_YYYYMMDD_HHMMSS.csv
↓
Example CSV content:
  Combo,Hit_Rate_%,Expectancy_%,Spearman_rho,n_active,n_total
  01_Baseline (Current Prod),51.5,-0.0880,0.0471,342,400
  02_Tight v1 (±12/±4),52.3,0.1245,0.0523,298,400
  03_Tight v2 (±13/±4),52.1,0.0985,0.0512,315,400
  ...
```

### Step 4: Repeat Batches

```
Batch 1: Combos 01-05 → momentum_20260716_143000.csv
         (time: ~5-7 min)

Batch 2: Combos 06-10 → momentum_20260716_143500.csv
         (time: ~5-7 min)

Batch 3: Combo 11-12   → momentum_20260716_144000.csv
         (time: ~3 min)

Total time Page 29: ~15-20 min
```

### Step 5: Repeat for Page 30 (Fade)

```
Switch to Page 30 → Tab: "🔧 Fade Tuner"
↓
Same workflow: Select 5 → Run → Download CSV
↓
Batch 1: Fade combos 01-05 → fade_20260716_150000.csv
Batch 2: Fade combos 06-10 → fade_20260716_150500.csv
Batch 3: Fade combos 11-12 → fade_20260716_151000.csv

Total time Page 30: ~15-20 min
```

### Step 6: Consolidate & Share Results

```
You now have 6 CSVs total:
  ✓ momentum_batch1.csv
  ✓ momentum_batch2.csv
  ✓ momentum_batch3.csv
  ✓ fade_batch1.csv
  ✓ fade_batch2.csv
  ✓ fade_batch3.csv

Share all 6 CSVs back
↓
I consolidate and create:
  - Comparison table (all 24 combos ranked by expectancy)
  - Top 5 recommendations (highest expectancy + HR)
  - Charts: HR % vs Expectancy % scatter
  - Walk-forward validation plan for top 3
```

---

## Expected Results

### Momentum (Page 29)

| Combo | Expected HR | Expected EXP | Notes |
|---|---|---|---|
| Baseline | 51.5% | -0.088% | Current production |
| **Tight_v1** | **52.2–52.8%** | **+0.08–0.20%** | ← LIKELY WINNER |
| Tight_v2 | 52.0–52.5% | +0.05–0.15% | Close to tight_v1 |
| Tight_Equal | 51.8–52.2% | -0.05–0.10% | Equal weight helps? |
| Tight_WeakTrans | 52.3–52.9% | +0.15–0.25% | Combines improvements |
| Tight_Accel | 52.1–52.6% | +0.10–0.18% | Acceleration helps |
| AllOptimized | 52.4–53.0% | +0.20–0.30% | Best case scenario |

**Success criteria**: Find combo with HR > 52% AND expectancy > 0%

### Fade (Page 30)

| Combo | Expected HR | Expected EXP | Notes |
|---|---|---|---|
| Baseline_Fade | 49–50% | -0.15–-0.05% | Opposite bet, slightly worse |
| Tight_v1 | 50–51% | -0.10–+0.05% | Tighter helps fade? |
| Tight_v2 | 49–50% | -0.15–0.00% | Too tight? |
| Loose | 48–49% | -0.20–-0.10% | Worst combo for fade |
| AllOptimized | 50–52% | +0.00–+0.15% | Best combo for fade |

**Success criteria**: Find fade combo with HR > 50% (better than random)

---

## Tips & Tricks

### Running Efficiently

- **Don't wait between batches** — Download, move on, run next batch
- **Time per combo**: ~1-1.5 min (includes Kite API fetch + computation)
- **Total time**: ~45 min for all 24 combos (6 batches × 7 min average)

### CSV Management

```
Create folder: ~/Downloads/momentum_fade_backtest/
  ├─ momentum_batch1.csv
  ├─ momentum_batch2.csv
  ├─ momentum_batch3.csv
  ├─ fade_batch1.csv
  ├─ fade_batch2.csv
  └─ fade_batch3.csv

Zip and share all 6 files at once
```

### If Error Occurs

- **"Could not fetch daily data"** → Kite API timeout; wait 2 min, re-run batch
- **"Backtesting..." spinner stuck** → Streamlit Cloud overloaded; refresh page
- **CSV download doesn't work** → Try different browser or incognito mode

---

## Next: Analysis Phase

Once you share all 6 CSVs:

1. **Consolidate**: Merge all results into one master table
2. **Rank**: Sort by expectancy % (highest first)
3. **Recommend**: Top 3 momentum + top 3 fade combos
4. **Compare**: What changed? Why did tight_v1 beat baseline?
5. **Walk-forward**: Validate top combo on 2024 vs 2025 split
6. **Commit**: Update config.py with best combo

---

## Checklist

- [ ] Run Page 29 Batch 1–3 (momentum, all 12 combos)
- [ ] Run Page 30 Batch 1–3 (fade, all 12 combos)
- [ ] Download all 6 CSVs
- [ ] Organize in folder
- [ ] Share all CSVs back
- [ ] Wait for consolidated analysis & recommendations
- [ ] Pick winner & commit to config.py

**ETA**: 1 hour total (including running batches + organizing files)

---

**Ready?** Open Page 29 and start batch 1! 🚀
