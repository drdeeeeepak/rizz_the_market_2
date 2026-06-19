# Page 18 — Conviction Radar · Full Reference

> *"Be patient on this fall, or get out?"* and *"Was yesterday's late bounce trustworthy?"*
> This page answers both in plain English and draws the evidence on a candle chart.
> This document explains **everything** on the page — what to look at, every
> abbreviation, and every calculation behind the scenes.

---

## 1. Read it in 30 seconds

1. **Top-left card = what to do right now.** It reads `RIDE THE UPTREND`,
   `BE PATIENT`, `WAIT — BUT STAY ALERT`, `DEFEND PUT — real downtrend`,
   `DEFEND CALL — upside tiring`, or `NEUTRAL`.
2. **Top-right card = the market's mood (dealer gamma).** `Shock-absorber` = dips
   tend to get bought back (patience pays). `Accelerator` = falls can snowball
   (defend). The **Gamma Flip line** is the price that separates the two.
3. **Chart = the proof.** Four marks show where the engine fired over the last ~7 days:
   - **green ▲** = bounce *brewing* (early, be patient)
   - **blue ★** = uptrend, *ride it* (bounce **continuing** — the stay-in-it signal)
   - **red ▼** = downtrend, *defend PUT*
   - **amber ▽** = topping, *defend CALL*
4. **Bottom table = close quality.** Grades each day's *close* HIGH / MEDIUM / LOW.
   A LOW after a late bounce = likely short-cover = gap risk. Today's row is 🔴 LIVE.

**Golden rule:** this *shifts the odds and stops panic at the worst moment*. It is
not a guarantee. Always keep your hard stop.

---

## 2. Glossary — every abbreviation on the page

| Term | Plain meaning |
|---|---|
| **VWAP** | Volume-Weighted Average Price — the day's "fair price". Above it, buyers are in control; below it, sellers are. Resets each day. |
| **CVD** | Cumulative Volume Delta — running tally of whether buyers or sellers are winning. (We use a *proxy*; see §4.4.) |
| **GEX** | Gamma Exposure — how much the big option dealers must hedge as price moves. Drives whether the market mean-reverts or trends. |
| **Gamma Flip** | The price where dealer hedging flips from *dampening* moves to *amplifying* them. The single most useful level on the page. |
| **Call wall / Put wall** | The strikes with the strongest gamma "magnet" — price tends to get pinned or pulled toward/around them. |
| **RSI** | Relative Strength Index (0–100) — a momentum gauge. Low = oversold, high = overbought. |
| **%B** | Where price sits inside its Bollinger Bands. <0 = below the lower band (stretched down), >1 = above the upper band. |
| **ATR** | Average True Range — typical candle size; a volatility yardstick. |
| **Expected move** | How far the market is "expected" to travel today, implied by India VIX. Used to judge if a move is *over-extended*. |
| **Stretch** | How far below fair value (VWAP) price has run, measured in *expected-move* units. Big stretch = more likely to snap back. |
| **Divergence** | Price makes a new low but momentum/volume does **not** — a sign the selling is tiring. |
| **Breadth** | % of the 50 biggest stocks trading above their own VWAP. Broad strength vs a narrow, fragile move. |
| **OI** | Open Interest — number of live option contracts at a strike (how much positioning sits there). |
| **IV** | Implied Volatility — the option market's expected volatility, used to price gamma. |
| **DTE** | Days To Expiry of the option chain used for gamma. |
| **VIX** | India VIX — the market's 30-day expected volatility (the "fear gauge"). |
| **Bull read** | 0–100: the case for *staying / long* — when above VWAP it's the uptrend (ride-it) score; when below VWAP it's the bounce-brewing (be-patient) score. |
| **Bear read** | 0–100: the case for *defending* — when above VWAP it's the topping (defend-CALL) score; when below VWAP it's the downtrend (defend-PUT) score. |
| **The 4 states** | BOUNCE_BREWING (▲), UPTREND/ride-it (★), DOWNTREND/defend-PUT (▼), TOPPING/defend-CALL (▽), or NEUTRAL. |
| **Signal agreement / Confidence** | 0–100: of the independent pillars (momentum, volume, breadth, structure), how many *agree* with the price direction. High = trustworthy; low = conflicted. |
| **Pillar scorecard** | The ✅/❌ row showing exactly which signals agree vs fight right now. |
| **IST** | Indian Standard Time. All day/session logic uses IST. |

---

## 3. What data the page uses (and why)

| What | Source | Why |
|---|---|---|
| **Candles** | Near-month **NIFTY FUTURES** (5-min or 15-min) | The future carries real **volume**; the Nifty *index* reports volume = 0, which would break VWAP/CVD. If futures can't load, it falls back to the index and **warns you** (VWAP becomes price-only, CVD off). |
| **Spot** | Live Nifty spot (index) | Used to anchor the gamma calculation. If unavailable the page **stops** rather than guess a price. |
| **Option chain** | Near-expiry chain (ATM ± 500 pts), OI + IV per strike | Builds the dealer-gamma profile, flip line and walls. |
| **VIX** | India VIX | Sets the "expected move" used by Stretch. Fallback 0.6% of spot if missing. |
| **Breadth** | All **50 Nifty-50 stocks**, intraday | % above their own VWAP = real-vs-fake confirmation. |

**Refresh / limits:** candles cache 5 min, breadth caches 10 min, the chain ~30 s.
The 50-stock breadth fetch is **throttled to ~3 requests/second** (Kite's historical
limit) with a back-off retry, so it never trips the rate limiter (first load ~20 s).

**Important honesty notes** (also printed on the page):
- The **gamma regime is a *today-only* snapshot** — historical option open-interest
  isn't available, so the ▲/▼ chart marks come only from **price/volume/breadth**
  (things measurable on every past candle). The flip line is today's context.
- **Candles are futures; gamma levels are on spot strikes** → a few points of *basis*
  difference. Read the flip/walls as **zones**, not to-the-point levels.
- **CVD is a proxy** (Kite gives no tick-level buy/sell aggressor data).
- It **updates once per candle** (every 5 or 15 min) — not continuously.

---

## 4. Every calculation, explained

All maths lives in `analytics/intraday_conviction.py` and `analytics/gamma_exposure.py`.
Below, each formula is given with the exact numbers used in the code.

### 4.1 Session VWAP (the "fair price" line)
For each trading day, with typical price `TP = (high + low + close) / 3`:

```
VWAP = cumulative(TP × volume) / cumulative(volume)        (resets each day)
```
If the series has **no volume** (index fallback), VWAP becomes a running average of
`TP` instead — still a usable fair-value line, just not volume-weighted.

### 4.2 RSI (momentum, 0–100)
14-period RSI using Wilder-style smoothing (`ewm(alpha = 1/14)`):
```
RSI = 100 − 100 / (1 + avg_gain / avg_loss)
```

### 4.3 Bollinger %B (stretch inside the bands)
20-period basis `SMA20`, bands = `SMA20 ± 2 × std20`:
```
%B = (close − lower_band) / (upper_band − lower_band)
```
`%B < 0.05` = stabbed below the lower band (over-stretched down).

### 4.4 CVD proxy (are sellers still hitting it?)
True buy/sell aggressor data isn't on Kite, so we infer it from **where each candle
closes inside its range** (Close-Location-Value):
```
CLV     = ((close − low) − (high − close)) / (high − low)     # −1 .. +1
CVD     = cumulative( CLV × volume )                          # resets each day
```
Close near the high → buyers won that candle (+); near the low → sellers won (−).

### 4.5 Expected move & Stretch (is the move over-extended?)
```
expected_move = spot × (VIX / 100) / 16        # one-day move, in points
                (fallback = 0.6% of spot if VIX is missing)
stretch_down  = (VWAP − close) / (expected_move × 0.5)   # only when below VWAP
```
A stretch of 1.0 means price is half an expected-move below fair value; 2.0+ is very
stretched (mean-reversion odds rise). Stretch is capped at 2 in the scoring.

### 4.6 Divergences (the genuinely *leading* signal)
Comparing each candle to **6 candles earlier** (`DIV_LOOKBACK = 6`):
```
price_lower_low = low < low[6 bars ago]
RSI bull div    = price_lower_low AND RSI > RSI[6 bars ago]   # momentum not confirming
CVD bull div    = price_lower_low AND CVD > CVD[6 bars ago]   # selling drying up
```

### 4.7 Lower-wick fraction (buyers stepping in)
```
lower_wick_frac = (min(open, close) − low) / (high − low)
```
`> 0.4` = a long lower tail = rejection of lower prices.

### 4.8 Breadth (real vs fake)
For all 50 Nifty-50 stocks: the % whose `close > their own session VWAP`, per timestamp.
High = broad strength, low = broad weakness.

### 4.9 Reversal read (0–100) — "be patient" score
Sum of these, then capped 0–100 (computed only meaningfully when **below VWAP**):

| Condition | Points |
|---|---|
| Stretched below fair value | `min(stretch, 2) × 18`  (max 36) |
| Oversold (RSI < 35) | `min(35 − RSI, 20) × 1.2`  (max 24) |
| RSI bullish divergence | +22 |
| CVD bullish divergence (selling drying up) | +18 |
| Long lower rejection wick (>0.4) | +12 |
| Stabbed below lower Bollinger band (%B < 0.05) | +10 |
| Breadth turning up while price is down | +10 |

### 4.10 Downtrend score (0–100) — "defend PUT" (below VWAP)
The `+25 just for being below VWAP` of the old version is **gone** — that's what
painted false ▼ on every pullback. It now needs **persistence** (3 consecutive
below-VWAP candles) before it can fire.
| Condition | Points |
|---|---|
| **Persistent** below VWAP (3 candles in a row) | +28 |
| Fresh lower low **with** momentum agreeing (no RSI div) | +20 |
| Fresh lower low **with** buyers not returning (CVD not turning up) | +15 |
| Weak momentum (RSI < 40) | +10 |
| Broad participation in the fall (breadth < 40%) | +15 |

### 4.11 Uptrend score (0–100) — "ride it / bounce continuing" (above VWAP)
The new **strict** continuation signal you asked for. A bounce only counts as
*continuing* when it is reclaimed **and** structurally healthy:
| Condition | Points |
|---|---|
| **Holding** above VWAP (3 candles in a row) | +25 |
| Higher-low structure (swing low rising) | +25 |
| Buyers regaining control (CVD turning up) | +20 |
| Breadth confirms (>50% of Nifty-50 above their VWAP)* | +20 |
| Healthy, not-overbought momentum (55 ≤ RSI ≤ 72) | +10 |

\* if breadth isn't loaded, this gets +10 partial credit so the signal still works.

### 4.12 Topping score (0–100) — "defend CALL" (above VWAP)
| Condition | Points |
|---|---|
| Overbought (RSI > 70) | +25 |
| Stretched far above fair value (stretch-up > 1.2) | +20 |
| Higher high but momentum fading (bearish RSI divergence) | +18 |
| Fewer stocks confirming the high (breadth diverging down) | +17 |
| Long upper rejection wick (>0.4) | +12 |

### 4.13 State + chart markers (the 4-state swing map)
Each candle is labelled (and the marker is drawn only when the state **changes**):
- **BOUNCE_BREWING** (green ▲) — below VWAP, `reversal ≥ 60`, `reversal ≥ downtrend`.
- **UPTREND / ride it** (blue ★) — above VWAP, `uptrend ≥ 55`, `uptrend ≥ topping`.
- **DOWNTREND / defend PUT** (red ▼) — below VWAP **and persistent**, `downtrend ≥ 58`, `downtrend > reversal`.
- **TOPPING / defend CALL** (amber ▽) — above VWAP, `topping ≥ 55`, `topping > uptrend`.
- **NEUTRAL** otherwise.

Because the up-side now has its own state, **counter-trend red ▼ are suppressed
during a confirmed uptrend** — fixing the "defend arrows all over a rally" problem.

The lower **reads panel** shows two lines that work in *both* regimes:
`bull_read` (green) = uptrend score when above VWAP, else the bounce-brewing score;
`bear_read` (red) = topping score when above VWAP, else the downtrend score.

### 4.14 Live verdict (top-left card) — gamma gates the call
The latest candle's state is combined with **today's gamma regime**
(`cushioned = positive gamma OR spot above the flip`):
- **UPTREND** + cushioned → **`RIDE THE UPTREND`** (bounce confirmed, PUT side safe).
- **UPTREND** + accelerator → **`UPTREND — BUT THIN AIR`** (ride with a trailing stop).
- **TOPPING** → **`DEFEND CALL — upside tiring`**.
- **BOUNCE_BREWING** + cushioned → **`BE PATIENT`** (a VWAP reclaim flips it to RIDE).
- **BOUNCE_BREWING** + accelerator → **`WAIT — BUT STAY ALERT`** (bounce may be shallow).
- **DOWNTREND** → **`DEFEND PUT — real downtrend`** (don't wait for a V-recovery).
- Else → `NEUTRAL — NO EDGE`.

Key design point: **a bounce is only fully trusted ("ride it") when price reclaims
fair value AND the structure (higher lows, breadth, buyers) AND dealer gamma all agree.**

### 4.15 Conflict weighting — "don't enter a move that won't materialise"
Five independent **pillars** each vote bull (+1) / bear (−1) / neutral (0):
*Price vs VWAP · Momentum (RSI) · Volume (CVD) · Breadth · Structure (higher/lower lows)*
(plus *Dealer gamma* as a today-only sixth pillar in the live verdict).

We count how many **agree** with the current price direction:
```
confidence = agree / (agree + oppose) × 100
conflict   = (2 or more pillars fighting the direction)
```
- The **Signal-agreement %** (purple dotted line + the top metric card) is this number.
- The **scorecard** shows each pillar as ✅ agrees / ❌ fights / • flat.
- **Continuation calls (UPTREND ★ / DOWNTREND ▼) are withheld when conflicted** — a
  conflicted tape is exactly the move that chops and fails, so the engine refuses to
  send you in. (Exhaustion turns — ▲ brewing, ▽ topping — are *allowed* to fire against
  the move, since that's their job.)
- When conflicted with no clean turn, the verdict becomes **`MIXED — STAND ASIDE`**:
  the honest "no edge, don't initiate" call.

---

## 5. Dealer gamma — the "market mode" (top-right card)

In `analytics/gamma_exposure.py`. Black-Scholes gamma per strike with `r = 6.5%`,
`T = max(DTE, 0.5)/365`:
```
unit       = spot² × 0.01
GEX(call)  = +gamma_call × call_OI × unit       # dealers net long calls
GEX(put)   = −gamma_put  × put_OI  × unit       # dealers net short puts
Net GEX    = Σ over all strikes
```
- **Net GEX ≥ 0 → POSITIVE / "Shock-absorber"**: dealers sell rallies & buy dips →
  moves get cushioned → **dips recoverable, late bounces stick → patience pays.**
- **Net GEX < 0 → NEGATIVE / "Accelerator"**: dealers sell dips & buy rallies →
  moves snowball → **falls feed on themselves, bounces fail → defend.**

**Gamma Flip level** — found by *re-pricing* net dealer gamma at 81 hypothetical
spot prices from −5% to +5% and locating where it crosses zero, nearest to spot:
- **Above the flip** → calm / mean-reverting (patience-friendly).
- **Below the flip** → fast / trending (be defensive).

**Walls:** `call wall = strike with the most +GEX`, `put wall = strike with the most
−GEX` — gamma magnets shown as dotted lines on the chart.

---

## 6. Daily close quality (bottom table) — built for your exact case

In `close_conviction()`. For each day (needs ≥ 4 candles):
```
close_location = (close − day_low) / (day_high − day_low)      # 0 = at low, 1 = at high
close_vs_vwap  = close − day's VWAP
last_chunk     = final ~1 hour of candles (len/7)
late_bounce    = last hour closed up, close in top 45% of range, day not down
vol_backloaded = last hour's volume share > 1.6× its fair share  (volume piled into close)
```
Score starts at 50, then:
| Factor | Effect |
|---|---|
| Closed **above** fair value (VWAP) | +18 (else −18) |
| Closed in top 30% of range | +12 (bottom 40% → −12) |
| **Late bounce + back-loaded volume + still below VWAP** | **−25** (classic short-cover into the close) |
| Breadth at close > 55% / < 40% | +10 / −10 |

Grade: **HIGH ≥ 65 · MEDIUM 45–64 · LOW < 45.**
A **LOW** after a late bounce is the warning that yesterday's bounce was a
short-cover into the close — the kind that often **gaps against you next session**.
The **🔴 LIVE** row grades *today* as it forms, so in the last 45–60 minutes you get
a **pre-close** read while you can still act.

---

## 7. How to act — a simple playbook

**You're short a PUT and the market is falling:**
1. Check the **top-left card**. `BE PATIENT` → don't book at the low; wait for a VWAP
   reclaim. `DEFEND PUT — real downtrend` → manage the leg, no V coming.
2. Confirm with the **market mode**: shock-absorber backs patience; accelerator says
   keep a hard line.
3. Glance at **breadth**: a fall on <40% breadth is broad and real; a bounce on
   <50% breadth is narrow and fragile.
4. Watch the latest candle: a **green ▲** = exhaustion building; when it turns into a
   **blue ★ `RIDE THE UPTREND`**, the bounce is confirmed and your PUT side is safe.

**Is the bounce/uptrend real, or a trap? (your "bounce continuing" question)**
- A blue **★ RIDE THE UPTREND** means price reclaimed fair value **and** is making
  higher lows **and** breadth >50% **and** buyers (CVD) returned — a *confirmed*
  up-leg, not a one-candle pop. Stay in it; trail a stop under the last higher-low.
- If instead you see an amber **▽ DEFEND CALL**, the up-move is tiring — watch your
  sold-CALL leg.

**Deciding whether to trust a late-day bounce:**
- Look at the **🔴 LIVE** close-quality row in the last hour. **LOW** = treat the
  bounce as a likely short-cover; don't chase, expect gap risk into next session.

**Always:** these are odds, not certainties. Keep your stop. Position size for the
case where the signal is wrong.

---

*Files: `pages/18_Conviction_Radar.py`, `analytics/gamma_exposure.py`,
`analytics/intraday_conviction.py`, fetchers in `data/live_fetcher.py`.*
