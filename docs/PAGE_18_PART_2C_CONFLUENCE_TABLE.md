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
| **BULL READ** | `bull_read` 0–100 (Part 2b §F) |
| **BEAR READ** | `bear_read` 0–100 (Part 2b §F) |
| **GAMMA FLIP LINE** | the flip price + spot's distance from it (Part 3 §B) |
| **SIGNAL AGREEMENT** | `confidence` % + how many pillars agree vs fight (§G) |

---

## I. 🔬 Behind the scenes — every calculation, candle by candle

A collapsible table under the chart, **one row per candle, newest first**, re-exposing
the columns above so you can audit exactly why a marker did or did not fire. Nothing new
is computed — it just makes every number visible.

**Column key** (signals lead; raw price/VWAP/CVD inputs are pushed to the far right)
`Time` · `ΔVWAP` (close − fair value) · `RSI` `BullDiv` (🟢▲) `BearDiv` (🔴▼) · `CVD↑`
`CVDdiv` (🟢▲ bull / 🔴▼ bear volume divergence) · `%B` `Str↑` `Str↓` `LWick` `UWick` ·
`HL` `LL` `HH` `Persist` (↑3/↓3) · `Brd%` · **`Reversal` `Uptrend`** (🟢 bull pair) ·
**`Downtr` `Topping`** (🔴 bear pair) · `P/M/V/B/S` pillar votes (▲/▼/·) · `Agree`
`Oppose` `Conf%` · `State` · *then at the end:* `Open` `High` `Low` `Close` `VWAP` `CVD`.

**Reading it:** the four score columns are **heat-shaded** (darker = louder), so scan
across a row to see which side is winning; the divergence arrows are coloured 🟢 green
(bull) / 🔴 red (bear); the `State` text colour matches the ▲★▼▽ chart marks; a fired
marker should line up with its score crossing 55/60 in the reads panel and the pillar
votes agreeing.

➡️ **Next: Part 3 — two-sided view, dealer gamma & daily close quality**
(`PAGE_18_PART_3_TWO_SIDED_AND_GAMMA.md`).
