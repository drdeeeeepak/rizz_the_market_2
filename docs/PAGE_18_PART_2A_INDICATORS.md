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
(mean-reversion odds rise). Stretch is capped at 2 in the scoring. *(Table col: a single
signed `Stretch` — positive 🟢 when above fair value, negative 🔴 when below.)*

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
volume (CVD) divergence input. *(Table cols: `BullDiv` 🟢▲ / `BearDiv` 🔴▼ for RSI;
`CVDdiv` shows 🟢▲ for a bullish CVD divergence / 🔴▼ for a bearish one. The price
lower-low / higher-high themselves are shown in the `Hi`/`Lo` swing columns — see B.8.)*

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
