# Page 18 — Conviction Radar · Reference **Part 2a** — Data & per-candle indicators

> All maths lives in `analytics/intraday_conviction.py` (per-candle engine) and
> `analytics/gamma_exposure.py` (dealer gamma — Part 3). This sub-part covers the
> **raw inputs**: where the data comes from and the per-candle indicators built from it.
> Part 2b turns these into the four scores & states; Part 2c covers confluence and the
> behind-the-scenes table. **Nothing is hidden** — every value here appears in the 🔬 table.

> **Reference map:** 1 overview · **2a indicators** · 2b scores & states · 2c confluence
> & table · 3 two-sided/gamma/close · 4 playbook.

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
`above_vwap` / `below_vwap` flags follow directly. *(Table cols: `VWAP`, `ΔVWAP`.)*

### B.2 RSI (momentum, 0–100)
14-period RSI using Wilder-style smoothing (`ewm(alpha = 1/14)`):
```
RSI = 100 − 100 / (1 + avg_gain / avg_loss)
```
In the table the `RSI` cell is **banded by regime** for instant reading:
🟣 **capitulation** (< 30) · 🔴 **downtrend** (30–45) · ⚪ **neutral** (45–55) ·
🟢 **uptrend** (55–70) · 🟠 **overbought** (> 70). *(Table col: `RSI`.)*

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
Close near the high → buyers won (+); near the low → sellers won (−).

Two CVD-direction reads, for two different jobs:
- **`cvd_rising`** = CVD rose vs the **immediately previous candle** (a same-day diff).
  This is the instant tick shown by the table's `CVD↑` arrow — "are buyers adding *right
  now*".
- **`cvd_up`** = CVD higher than **6 candles ago** — the smoother, less-noisy version
  used inside the *scores* ("buyers regaining control over the swing"). Don't confuse the
  two: the arrow is the fast read, the score uses the slow one.

*(Table cols: `CVD` (raw, far right), `CVD↑` = `cvd_rising`.)*

### B.5 Expected move & Stretch (is the move over-extended?)
```
expected_move = spot × (VIX / 100) / 16        # FULL-DAY one-sigma move, in points
                (fallback = 0.6% of spot if VIX is missing)
stretch_down  = (VWAP − close) / (expected_move × 0.3)   # only when below VWAP
stretch_up    = (close − VWAP) / (expected_move × 0.3)   # only when above VWAP
```
The `expected_move` is a **full-day** move, but price's deviation *from VWAP* intraday is
only a fraction of that — so stretch is measured against `expected_move × 0.3`
(`STRETCH_EM_FRAC`). That means stretch reaches its cap of 2 at ~0.6 of a daily expected
move, which matches realistic intraday extension (the old ×0.5 needed a near-full-day
move and so under-fired). A stretch of 1.0 ≈ 0.3 of a daily EM from fair value; 2.0 (the
cap) ≈ 0.6. *(Table col: a single signed `Stretch` — positive 🟢 above fair value,
negative 🔴 below. The dotted **Stretch band on the chart** is drawn at this same
over-extension line — VWAP ± (EM × 0.3 × 2) ≈ ±0.6 of a daily move — so a candle poking
outside it is exactly a maxed-out Stretch, not a full-day-away outlier.)*

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
volume (CVD) divergence input. A candle can be a bull *or* a bear divergence but **never
both** (bull needs RSI up, bear needs RSI down), so each is a single signed column.
*(Table cols: `RSIdiv` 🟢▲ bull / 🔴▼ bear for the RSI divergence; `CVDdiv` 🟢▲ / 🔴▼ for
the CVD one. The price lower-low / higher-high themselves show in the `Hi`/`Lo` swing
columns — see B.8.)*

### B.7 Rejection wicks (who stepped in)
```
lower_wick_frac = (min(open, close) − low) / (high − low)   # long lower tail = buyers
upper_wick_frac = (high − max(open, close)) / (high − low)  # long upper tail = sellers
```
`> 0.4` = a long rejection tail. *(Table cols: `LWick`, `UWick`.)*

### B.8 Swing structure & persistence
Four swing flags, compared to **6 candles earlier**, give a *symmetric* read of the
trend skeleton — higher highs/lows = up, lower highs/lows = down:
```
higher_high = high > high[6 ago]        higher_low = rolling-6 swing low is rising
lower_high  = high < high[6 ago]        lower_low  = low  < low[6 ago]
```
```
persist_below = 3 consecutive candles below VWAP     # a real down-leg, not a dip
persist_above = 3 consecutive candles above VWAP     # holding above fair value
```
**Display:** rather than three separate flags, the table shows **two arrow columns**:
- `Hi` = the swing **high** direction — 🟢▲ higher-high or 🔴▼ lower-high;
- `Lo` = the swing **low** direction — 🟢▲ higher-low or 🔴▼ lower-low.

Read them as a pair for instant meaning: **▲▲ uptrend · ▼▼ downtrend · ▲▼ expanding
(outside bar) · ▼▲ inside (contracting)**. *(`lower_high` was added so the down-side has
the same skeleton the up-side already had — previously only `higher_low` existed.)*
*(Table cols: `Hi`, `Lo`, `Persist` shown as ↑3 / ↓3.)*

### B.9 Breadth (real vs fake)
For all 50 Nifty-50 stocks: the % whose `close > their own session VWAP`, per
timestamp. High = broad strength; low = broad weakness. `breadth_div_down` = price
makes a higher high while breadth falls (hidden weakness at the top). *(Table col: `Brd%`.)*

➡️ **Next: Part 2b — the four scores & the 4-state map** (`PAGE_18_PART_2B_SCORES.md`).
