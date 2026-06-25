# Page 18 — Conviction Radar · Reference **Part 2c** — Confluence, metric cards & the table

> The final sub-part of the calculations: how the five **pillars** vote and produce the
> signal-agreement %, the **metric cards** under the headline, and the 🔬 **behind-the-
> scenes table** that re-exposes every number, candle by candle.

> **Reference map:** 1 overview · 2a indicators · 2b scores & states · **2c confluence
> & table** · 3 two-sided/gamma/close · 4 playbook.

---

## G. Conflict weighting — "don't enter a move that won't materialise"

Five independent **pillars** each vote bull (+1) / bear (−1) / neutral (0):
*Price vs VWAP · Momentum (RSI) · Volume (CVD) · Breadth · Structure (higher/lower lows)*
(plus *Dealer gamma* as a today-only sixth pillar in the live verdict). Price-vs-VWAP is
the **reference direction (the bias)**, so the four that actually *vote* are Momentum,
Volume, Breadth, Structure.
```
confidence = clip( (agree − oppose) / 4 , 0..1 ) × 100      # net of the 4 voting pillars
conflict   = (2 or more pillars fighting the price direction)
```
**Why net-of-4 (not `agree / (agree+oppose)`):** the old ratio scored *3-agree/0-oppose*
and *4-agree/0-oppose* both at **100%**, hiding the difference in strength. Counting all 4
pillars in the denominator fixes that — `4 agree = 100%`, `3 agree + 1 neutral = 75%`,
`3 agree + 1 oppose = 50%`, `2 agree + 2 oppose = 0%` — so both *how many* confirm and
*how many fight* move the number.
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
| **BULL READ** | `bull_read` 0–100 (Part 2b §F) |
| **BEAR READ** | `bear_read` 0–100 (Part 2b §F) |
| **GAMMA FLIP LINE** | the flip price + spot's distance from it (Part 3 §B) |
| **SIGNAL AGREEMENT** | `confidence` % + how many pillars agree vs fight (§G) |

---

## I. 🔬 Behind the scenes — every calculation, candle by candle

A collapsible table under the chart, **one row per candle, newest first**, re-exposing
the columns above so you can audit exactly why a marker did or did not fire. Nothing new
is computed — it just makes every number visible.

**Column key** — the **results lead**, then the inputs that produced them, raw price last:

`Time` · **`State`** (the resulting call) · **`Net`** (bull-read − bear-read, the single
directional conviction — 🟢 + stay / 🔴 − defend, heat-shaded) · **`Brd%`** (breadth — 🟢
>55 broad / 🔴 <45 weak) · **`Conf%`** ((agree − oppose) ÷ 4 voting pillars, tinted 🟢 when
the prevailing lean is bullish / 🔴 when bearish, darker = stronger) · `ΔVWAP` (close − fair
value) · `RSI` (banded: 🟣 capitulation <30 · 🔴 downtrend 30–45 · ⚪ neutral 45–55 · 🟢
uptrend 55–70 · 🟠 overbought >70; **text red when RSI fell vs the previous candle**) ·
`RSIdiv` (🟢▲ bull / 🔴▼ bear RSI divergence) · `CVD↑`
(🟢▲ CVD rose vs the *previous* candle) · `CVDdiv` (🟢▲ bull / 🔴▼ bear 6-bar volume
divergence) · `HiLo` (swing high+low in one cell — 🟢 ▲▲ uptrend · 🔴 ▼▼ downtrend · 🟠 ▲▼
expanding/outside · ▼▲ inside) · `LWick` (🟢 bullish lower side — long lower wick *or* green
body with no lower wick) `UWick` (🔴 bearish upper side — long upper wick *or* red body with
no upper wick) · `Candle` (single close-location read: 🟢 +1 closed at high / 🔴 −1 at low —
momentum *and* rejection in one column; on trial alongside the two-column LWick/UWick split)
· `%B` (momentum **gated by fast structure** + reversal: high %B *with* a new high → 🟢
up-momentum / pale if no new high; low %B with a new low → 🔴; stretched beyond a band but
no new extreme → 🟠 amber reversal-watch; ~0.5 grey) · `Stretch` (signed heat-gradient —
🟢 + above fair value / 🔴 − below) · `Persist` (↑N 🟢 / ↓N 🔴 = N candles in a row
above / below VWAP) · **`Reversal` `Uptrend`**
(🟢 bull pair) · **`Downtr` `Topping`** (🔴 bear pair) · `P/M/V/B/S` pillar votes (▲/▼/·) ·
`Agree` `Oppose` · *then at the end:* `Open` `High` `Low` `Close` `VWAP` `CVD`.

**Reading it:** the four score columns and `Net` are **heat-shaded** (darker = louder),
so scan a row to see which side is winning and how strongly; the arrow columns are
coloured 🟢 green (up / bull) / 🔴 red (down / bear); `RSI` is banded by regime; the
`State` text colour matches the ▲★▼▽ chart marks; a fired marker should line up with its
score crossing 55/60 in the reads panel and the pillar votes agreeing.

➡️ **Next: Part 3 — two-sided view, dealer gamma & daily close quality**
(`PAGE_18_PART_3_TWO_SIDED_AND_GAMMA.md`).
