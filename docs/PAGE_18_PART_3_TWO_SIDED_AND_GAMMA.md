# Page 18 — Conviction Radar · Reference **Part 3 of 4** — Two-sided view, dealer gamma & close quality

> This part covers the parts that make Page 18 *two-sided* — both condor legs at once —
> plus the dealer-gamma "market mode" and the daily close-quality grade.

> **Reference map:** Part 1 — overview & glossary · Part 2a/2b/2c — every calculation ·
> Part 3 — two-sided, gamma & close (this file) · Part 4 — playbook.

---

## A. The two-sided view — see BOTH condor legs at once

An Iron Condor seller always carries a **sold-PUT *and* a sold-CALL** at the same time,
so a single badge ("the one call now") only ever tells half the story. Three things on
the page now expose both sides and every intermediate number:

### A.1 "Both sides, right now" cards
Under the headline verdict, two cards show the live case for each leg side by side,
each with its own **raw 0–100 sub-score** and a heat-bar:

| Card | Above VWAP it reads | Below VWAP it reads | Score used |
|---|---|---|---|
| 🟢 **BULL CASE** — stay / be patient | *Uptrend — ride it* (sold-PUT safer) | *Bounce brewing — be patient* (sold-PUT relief) | `uptrend` / `reversal` |
| 🔴 **BEAR CASE** — defend | *Topping — defend CALL* (sold-CALL at risk) | *Downtrend — defend PUT* (sold-PUT at risk) | `topping` / `downtrend` |

So even when the headline is dominated by one side, you still see the other leg's
score. Each card also notes the dealer-gamma tilt (does gamma help or weaken that case).
*(Engine: `two_sided_verdict()`.)*

### A.2 Reads panel = all four raw scores
The lower chart panel plots `reversal` (green), `uptrend` (blue), `downtrend` (red) and
`topping` (amber) **together**, with the **55/60 trigger lines**, so you watch both
sides of both regimes build over the last ~7 days — not just the one winning line.
(Full detail in Part 2b §E.)

### A.3 🔬 Behind-the-scenes table
One row per candle with **the four raw scores side by side** (heat-shaded), the five
pillar votes, agreement %, and the resulting state. This is where you audit, candle by
candle, why each side did or didn't fire. (Column key in Part 2c §I.)

**Why two-sided matters for you:** when price is *below* VWAP your sold-PUT is the leg in
focus (Reversal vs Downtrend), and when price is *above* VWAP your sold-CALL is in focus
(Uptrend vs Topping). The cards and the reads panel let you watch the *threatened* leg
and the *relief* leg at the same time, instead of guessing from one merged badge.

---

## B. Dealer gamma — the "market mode" (top-right card)

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

**Gamma Flip level** — found by *re-pricing* net dealer gamma at 81 hypothetical spot
prices from −5% to +5% and locating where it crosses zero, nearest to spot:
- **Above the flip** → calm / mean-reverting (patience-friendly).
- **Below the flip** → fast / trending (be defensive).

**Walls:** `call wall = strike with the most +GEX`, `put wall = strike with the most
−GEX` — gamma magnets shown as dotted lines on the chart, and as a bar chart in the
"Where the gamma walls sit" expander (green bars damp moves, red bars amplify; the flip
is where green turns to red).

**Honesty note:** gamma is a **today-only** snapshot (no historical OI), so it is shown
as today's *context* and as a sixth pillar in the live verdict — it is **not**
back-painted onto the old candles. The ▲★▼▽ marks come only from price/volume/breadth.

---

## C. The headline verdict — how gamma gates the call

The latest candle's state (Part 2b §D) is combined with **today's gamma regime**
(`cushioned = positive gamma OR spot above the flip`):
- **UPTREND** + cushioned → **`RIDE THE UPTREND`** (bounce confirmed, PUT side safe).
- **UPTREND** + accelerator → **`UPTREND — BUT THIN AIR`** (ride with a trailing stop).
- **TOPPING** → **`DEFEND CALL — upside tiring`**.
- **BOUNCE_BREWING** + cushioned → **`BE PATIENT`** (a VWAP reclaim flips it to RIDE).
- **BOUNCE_BREWING** + accelerator → **`WAIT — BUT STAY ALERT`** (bounce may be shallow).
- **DOWNTREND** → **`DEFEND PUT — real downtrend`** (don't wait for a V-recovery).
- **Conflicted + no clean turn** → **`MIXED — STAND ASIDE`**.
- Else → `NEUTRAL — NO EDGE`.

Key design point: **a bounce is only fully trusted ("ride it") when price reclaims fair
value AND the structure (higher lows, breadth, buyers) AND dealer gamma all agree.**

---

## D. Daily close quality (bottom table) — built for your exact case

In `close_conviction()`. For each day (needs ≥ 4 candles):
```
close_location = (close − day_low) / (day_high − day_low)      # 0 = at low, 1 = at high
close_vs_vwap  = close − day's VWAP
last_chunk     = final ~1 hour of candles (len / 7)
late_bounce    = last hour closed up, close in top 45% of range, day not down
vol_backloaded = last hour's volume share > 1.6× its fair share  (volume piled into close)
```
Score starts at **base 50**, then each factor adds/subtracts — and the page now prints
this **build-up** on each row so the grade is auditable:

| Factor | Effect | Chip on the row |
|---|---|---|
| Closed **above** fair value (VWAP) | +18 (else −18) | `VWAP ±18` |
| Closed in top 30% of range (bottom 40% → −12) | +12 / −12 / 0 | `range ±12` |
| **Late bounce + back-loaded volume + still below VWAP** | **−25** (short-cover into the close) | `short-cover −25` |
| Breadth at close > 55% / < 40% | +10 / −10 / 0 | `breadth ±10` |

```
score = clip(50 + VWAP + range + short-cover + breadth, 0, 100)
```
Grade: **HIGH ≥ 65 · MEDIUM 45–64 · LOW < 45.**

A **LOW** after a late bounce is the warning that the bounce was a short-cover into the
close — the kind that often **gaps against you next session**. The **🔴 LIVE** row
grades *today* as it forms, so in the last 45–60 minutes you get a **pre-close** read
while you can still act.

---

## E. How far ahead does this actually see?

It's an **early-warning / context** tool, not a crystal ball:
- **Updates once per candle** (every 5 or 15 min) — a fresh read at each close.
- The genuinely *leading* parts are the **divergences** (Part 2a §B.6) and the **gamma
  flip line** (known in advance) — typically 1–3 candles early.
- **Before the close:** the 🔴 LIVE close-quality row grades *today* as it forms.
- It **shifts the odds**; it does **not** guarantee the turn. Always keep your hard stop.

➡️ **Next: Part 4 — how to act (playbook)** (`PAGE_18_PART_4_PLAYBOOK.md`).
