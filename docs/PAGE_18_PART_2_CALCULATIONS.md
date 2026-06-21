# Page 18 — Conviction Radar · Reference **Part 2 of 4** — Every calculation

> All maths lives in `analytics/intraday_conviction.py` (per-candle engine) and
> `analytics/gamma_exposure.py` (dealer gamma — covered in Part 3). Below, each
> formula is given with the exact numbers used in the code. **Nothing is hidden:**
> every value here also appears in the 🔬 behind-the-scenes table (§I).

> **Reference map:** Part 1 — overview & glossary · Part 2 — every calculation (this
> file) · Part 3 — two-sided view, gamma & close quality · Part 4 — playbook.

---

## A. What data the page uses (and why)

| What | Source | Why |
|---|---|---|
| **Candles** | Near-month **NIFTY FUTURES** (5-min or 15-min) | The future carries real **volume**; the Nifty *index* reports volume = 0, which would break VWAP/CVD. If futures can't load, it falls back to the index and **warns you** (VWAP becomes price-only, CVD off). |
| **Spot** | Live Nifty spot (index) | Anchors the gamma calculation. If unavailable the page **stops** rather than guess a price. |
| **Option chain** | Near-expiry chain (ATM ± 500 pts), OI + IV per strike | Builds the dealer-gamma profile, flip line and walls (Part 3). |
| **VIX** | India VIX | Sets the "expected move" used by Stretch. Fallback 0.6% of spot if missing. |
| **Breadth** | All **50 Nifty-50 stocks**, intraday | % above their own VWAP = real-vs-fake confirmation. |

**Refresh / limits:** candles cache 5 min, breadth caches 10 min, the chain ~30 s.
The 50-stock breadth fetch is **throttled to ~3 requests/second** (Kite's historical
limit) with a back-off retry, so it never trips the rate limiter (first load ~20 s).

---

## B. The per-candle indicators (the raw inputs)

### B.1 Session VWAP (the "fair price" line)
For each trading day, with typical price `TP = (high + low + close) / 3`:
```
VWAP = cumulative(TP × volume) / cumulative(volume)        (resets each day)
```
If the series has **no volume** (index fallback), VWAP becomes a running average of
`TP` instead — still a usable fair-value line, just not volume-weighted.
`above_vwap` / `below_vwap` flags follow directly. *(Table cols: `VWAP`, `ΔVWAP`, `Side`.)*

### B.2 RSI (momentum, 0–100)
14-period RSI using Wilder-style smoothing (`ewm(alpha = 1/14)`):
```
RSI = 100 − 100 / (1 + avg_gain / avg_loss)
```
*(Table col: `RSI`.)*

### B.3 Bollinger %B (stretch inside the bands)
20-period basis `SMA20`, bands = `SMA20 ± 2 × std20`:
```
%B = (close − lower_band) / (upper_band − lower_band)
```
`%B < 0.05` = stabbed below the lower band (over-stretched down). *(Table col: `%B`.)*

### B.4 CVD proxy (are sellers still hitting it?)
True buy/sell aggressor data isn't on Kite, so we infer it from **where each candle
closes inside its range** (Close-Location-Value):
```
CLV = ((close − low) − (high − close)) / (high − low)     # −1 .. +1
CVD = cumulative( CLV × volume )                          # resets each day
```
Close near the high → buyers won (+); near the low → sellers won (−). `cvd_up` = CVD
higher than 6 candles ago. *(Table cols: `CVD`, `CVD↑`.)*

### B.5 Expected move & Stretch (is the move over-extended?)
```
expected_move = spot × (VIX / 100) / 16        # one-day move, in points
                (fallback = 0.6% of spot if VIX is missing)
stretch_down  = (VWAP − close) / (expected_move × 0.5)   # only when below VWAP
stretch_up    = (close − VWAP) / (expected_move × 0.5)   # only when above VWAP
```
A stretch of 1.0 = half an expected-move from fair value; 2.0+ is very stretched
(mean-reversion odds rise). Stretch is capped at 2 in the scoring. *(Table cols: `Str↑`, `Str↓`.)*

### B.6 Divergences (the genuinely *leading* signal)
Comparing each candle to **6 candles earlier** (`DIV_LOOKBACK = 6`):
```
price_lower_low  = low  < low[6 bars ago]
price_higher_high= high > high[6 bars ago]
RSI bull div = price_lower_low  AND RSI > RSI[6 ago]   # momentum not confirming the low
CVD bull div = price_lower_low  AND CVD > CVD[6 ago]   # selling drying up
RSI bear div = price_higher_high AND RSI < RSI[6 ago]  # momentum not confirming the high
CVD bear div = price_higher_high AND CVD < CVD[6 ago]  # buying drying up at the high
```
The bull and bear sides are **symmetric**: each gets both a momentum (RSI) *and* a
volume (CVD) divergence input. *(Table cols: `BullDiv`, `BearDiv`, `LL`, `HH`, and
`CVDdiv` shows ▲ for a bullish CVD divergence / ▼ for a bearish one.)*

### B.7 Rejection wicks (who stepped in)
```
lower_wick_frac = (min(open, close) − low) / (high − low)   # long lower tail = buyers
upper_wick_frac = (high − max(open, close)) / (high − low)  # long upper tail = sellers
```
`> 0.4` = a long rejection tail. *(Table cols: `LWick`, `UWick`.)*

### B.8 Swing structure & persistence
```
higher_low   = rolling-6 swing low is rising            # uptrend skeleton
persist_below= 3 consecutive candles below VWAP         # a real down-leg, not a dip
persist_above= 3 consecutive candles above VWAP         # holding above fair value
```
*(Table cols: `HL`, `Persist` shown as ↑3 / ↓3.)*

### B.9 Breadth (real vs fake)
For all 50 Nifty-50 stocks: the % whose `close > their own session VWAP`, per
timestamp. High = broad strength; low = broad weakness. `breadth_div_down` = price
makes a higher high while breadth falls (hidden weakness at the top). *(Table col: `Brd%`.)*

---

## C. The four raw scores (both sides of both regimes)

Each is 0–100, summed from the inputs above, then capped. **These are the heart of the
two-sided view** — Part 1's Bull/Bear cards and the chart's reads panel are just these
four lines. *(Table cols: `Reversal`, `Uptrend`, `Downtr`, `Topping`.)*

### C.1 Reversal — "be patient" (🟢 bull, only meaningful **below** VWAP)
| Condition | Points |
|---|---|
| Stretched below fair value | `min(stretch, 2) × 18`  (max 36) |
| Oversold (RSI < 35) | `min(35 − RSI, 20) × 1.2`  (max 24) |
| RSI bullish divergence | +22 |
| CVD bullish divergence (selling drying up) | +18 |
| Long lower rejection wick (>0.4) | +12 |
| Stabbed below lower Bollinger band (%B < 0.05) | +10 |
| Breadth turning up while price is down | +10 |

### C.2 Downtrend — "defend PUT" (🔴 bear, **below** VWAP)
The old `+25 just for being below VWAP` is **gone** — that's what painted false ▼ on
every pullback. It now needs **persistence** (3 below-VWAP candles) before it can fire.
| Condition | Points |
|---|---|
| **Persistent** below VWAP (3 in a row) | +28 |
| Fresh lower low **with** momentum agreeing (no RSI div) | +20 |
| Fresh lower low **with** buyers not returning (CVD not up) | +15 |
| Weak momentum (RSI < 40) | +10 |
| Broad participation in the fall (breadth < 40%) | +15 |

### C.3 Uptrend — "ride it / bounce continuing" (🟢 bull, **above** VWAP)
The **strict** continuation signal: a bounce only counts as *continuing* when reclaimed
**and** structurally healthy.
| Condition | Points |
|---|---|
| **Holding** above VWAP (3 in a row) | +25 |
| Higher-low structure (swing low rising) | +25 |
| Buyers regaining control (CVD turning up) | +20 |
| Breadth confirms (>50% of Nifty-50 above their VWAP)\* | +20 |
| Healthy, not-overbought momentum (55 ≤ RSI ≤ 72) | +10 |

\* if breadth isn't loaded, this gets +10 partial credit so the signal still works.

### C.4 Topping — "defend CALL" (🔴 bear, **above** VWAP)
| Condition | Points |
|---|---|
| Overbought (RSI > 70) | +25 |
| Stretched far above fair value (stretch-up > 1.2) | +20 |
| Higher high but momentum fading (bearish RSI divergence) | +18 |
| Higher high but **buying drying up** (bearish CVD divergence) | +18 |
| Fewer stocks confirming the high (breadth diverging down) | +17 |
| Long upper rejection wick (>0.4) | +12 |

This mirrors the Reversal side (§C.1), which gets both an RSI **and** a CVD bullish
divergence — so neither leg is better-confirmed than the other.

---

## D. State + chart markers (the 4-state swing map)

Each candle is labelled (and the marker is drawn only when the state **changes**):
- **BOUNCE_BREWING** (green ▲) — below VWAP, `reversal ≥ 60`, `reversal ≥ downtrend`.
- **UPTREND / ride it** (blue ★) — above VWAP, `uptrend ≥ 55`, `uptrend ≥ topping`.
- **DOWNTREND / defend PUT** (red ▼) — below VWAP **and persistent**, `downtrend ≥ 58`, `downtrend > reversal`.
- **TOPPING / defend CALL** (amber ▽) — above VWAP, `topping ≥ 55`, `topping > uptrend`.
- **NEUTRAL** otherwise.

Because the up-side has its own state, **counter-trend red ▼ are suppressed during a
confirmed uptrend** — fixing the "defend arrows all over a rally" problem. *(Table col: `State`.)*

---

## E. The reads panel (lower chart panel)

Instead of two collapsed lines, the panel plots **all four raw scores together** so you
watch both sides of both regimes build over ~7 days:
- green **Reversal** (be patient) and blue **Uptrend** (ride it) = the *bull* case;
- red **Downtrend** (defend PUT) and amber **Topping** (defend CALL) = the *bear* case.

The dotted lines at **55** and **60** are the trigger thresholds; a chart marker fires
when a score crosses its threshold (and beats the competing score). The purple-dotted
**Signal-agreement %** is overlaid (see §G).

---

## F. Bull read & Bear read (the two-line summary)

A convenience collapse used by the metric cards (§H):
```
bull_read = uptrend  (if above VWAP)   else  reversal
bear_read = topping  (if above VWAP)   else  downtrend
```
The two-sided cards in Part 3 §A use the **raw four** so you never lose the other side.

---

## G. Conflict weighting — "don't enter a move that won't materialise"

Five independent **pillars** each vote bull (+1) / bear (−1) / neutral (0):
*Price vs VWAP · Momentum (RSI) · Volume (CVD) · Breadth · Structure (higher/lower lows)*
(plus *Dealer gamma* as a today-only sixth pillar in the live verdict).
```
confidence = agree / (agree + oppose) × 100
conflict   = (2 or more pillars fighting the price direction)
```
- The **Signal-agreement %** (purple dotted line + the top metric card) is this number.
- The **scorecard** shows each pillar as ✅ agrees / ❌ fights / • flat.
- **Continuation calls (UPTREND ★ / DOWNTREND ▼) are withheld when conflicted** — a
  conflicted tape is exactly the move that chops and fails. (Exhaustion turns — ▲
  brewing, ▽ topping — are *allowed* to fire against the move; that's their job.)
- When conflicted with no clean turn, the verdict becomes **`MIXED — STAND ASIDE`**.

*(Table cols: `P` `M` `V` `B` `S` votes, `Agree`, `Oppose`, `Conf%`.)*

---

## H. The metric cards (under the headline)

| Card | Value |
|---|---|
| **BULL READ** | `bull_read` 0–100 (§F) |
| **BEAR READ** | `bear_read` 0–100 (§F) |
| **GAMMA FLIP LINE** | the flip price + spot's distance from it (Part 3 §B) |
| **SIGNAL AGREEMENT** | `confidence` % + how many pillars agree vs fight (§G) |

---

## I. 🔬 Behind the scenes — every calculation, candle by candle

A collapsible table under the chart, **one row per candle, newest first**, re-exposing
the columns above so you can audit exactly why a marker did or did not fire. Nothing new
is computed — it just makes every number visible.

**Column key** (signals lead; raw price/VWAP/CVD inputs are pushed to the far right)
`Time` · `ΔVWAP` `Side` (above/below) · `RSI` `BullDiv` `BearDiv` · `CVD↑` `CVDdiv`
(▲ bull / ▼ bear volume divergence) · `%B` `Str↑` `Str↓` `LWick` `UWick` · `HL` `LL`
`HH` `Persist` (↑3/↓3) · `Brd%` · **`Reversal` `Uptrend`** (🟢 bull pair) ·
**`Downtr` `Topping`** (🔴 bear pair) · `P/M/V/B/S` pillar votes (▲/▼/·) · `Agree`
`Oppose` `Conf%` · `State` · *then at the end:* `Open` `High` `Low` `Close` `VWAP` `CVD`.

**Reading it:** the four score columns are **heat-shaded** (darker = louder), so scan
across a row to see which side is winning; the `State` text colour matches the
▲★▼▽ chart marks; a fired marker should line up with its score crossing 55/60 in the
reads panel and the pillar votes agreeing.

➡️ **Next: Part 3 — two-sided view, dealer gamma & daily close quality**
(`PAGE_18_PART_3_TWO_SIDED_AND_GAMMA.md`).
