# Page 18 — Conviction Radar · Reference **Part 1 of 4** — Overview & glossary

> *"Be patient on this fall, or get out?"* and *"Was yesterday's late bounce trustworthy?"*
> This page answers both in plain English, draws the evidence on a candle chart, and
> now exposes **every number behind the scenes** so you can audit it candle by candle.
>
> **Reference map:** Part 1 — overview & glossary (this file) · Part 2 — every
> calculation · Part 3 — two-sided view, dealer gamma & daily close quality ·
> Part 4 — how to act (playbook).

---

## 1. Read it in 30 seconds

1. **Top-left card = the single headline call right now.** It reads `RIDE THE
   UPTREND`, `BE PATIENT`, `WAIT — BUT STAY ALERT`, `DEFEND PUT — real downtrend`,
   `DEFEND CALL — upside tiring`, `MIXED — STAND ASIDE`, or `NEUTRAL`.
2. **Top-right card = the market's mood (dealer gamma).** `Shock-absorber` = dips
   tend to get bought back (patience pays). `Accelerator` = falls can snowball
   (defend). The **Gamma Flip line** is the price that separates the two.
3. **"Both sides, right now" cards = your two condor legs at once.** A 🟢 **BULL
   CASE** card (stay / be patient) and a 🔴 **BEAR CASE** card (defend), each with
   its own raw 0–100 score and heat-bar — so you see the case for the sold-PUT *and*
   the sold-CALL even when one side dominates the single headline. (Detail in Part 3.)
4. **Chart = the proof.** Four marks show where the engine fired over the last ~7 days:
   - **green ▲** = bounce *brewing* (early, be patient)
   - **blue ★** = uptrend, *ride it* (bounce **continuing** — the stay-in-it signal)
   - **red ▼** = downtrend, *defend PUT*
   - **amber ▽** = topping, *defend CALL*

   The lower **reads panel** plots all **four raw scores** together (both sides of
   both regimes), with the trigger thresholds drawn in.
5. **🔬 Behind-the-scenes table** (collapsible, under the chart) = every calculation,
   one row per candle, newest first. This is exactly what the engine "saw". (Part 2/3.)
6. **Bottom table = close quality.** Grades each day's *close* HIGH / MEDIUM / LOW,
   and now shows the **score build-up** (`base 50 ± factors`). A LOW after a late
   bounce = likely short-cover = gap risk. Today's row is 🔴 LIVE.

**Golden rule:** this *shifts the odds and stops panic at the worst moment*. It is
not a guarantee. Always keep your hard stop.

---

## 2. What's on the page, top to bottom

| Section | What it tells you | Detail |
|---|---|---|
| Headline verdict + market-mode cards | The one call now, gated by dealer gamma | Part 3 §C |
| Bull/Bear metric cards | Bull-read, bear-read, gamma flip, signal agreement | Part 2 §H |
| **Both sides, right now** | Both condor legs' live scores side by side | Part 3 §A |
| Pillar scorecard | ✅/❌ which signals agree vs fight | Part 2 §G |
| Annotated chart | Candles + VWAP + bands + flip/walls + 4-state marks + 4-score reads | Part 2 |
| **🔬 Behind the scenes** | Every per-candle number, auditable | Part 2 §I |
| Daily close quality | Was each day's close trustworthy, with score build-up | Part 3 §D |
| Gamma walls detail | Where dealer gamma sits by strike | Part 3 §B |

---

## 3. Glossary — every abbreviation on the page

| Term | Plain meaning |
|---|---|
| **VWAP** | Volume-Weighted Average Price — the day's "fair price". Above it, buyers are in control; below it, sellers are. Resets each day. |
| **CVD** | Cumulative Volume Delta — running tally of whether buyers or sellers are winning. (We use a *proxy*; Part 2 §D.) |
| **GEX** | Gamma Exposure — how much the big option dealers must hedge as price moves. Drives whether the market mean-reverts or trends. |
| **Gamma Flip** | The price where dealer hedging flips from *dampening* moves to *amplifying* them. The single most useful level on the page. |
| **Call wall / Put wall** | The strikes with the strongest gamma "magnet" — price tends to get pinned or pulled toward/around them. |
| **RSI** | Relative Strength Index (0–100) — a momentum gauge. Low = oversold, high = overbought. |
| **%B** | Where price sits inside its Bollinger Bands. <0 = below the lower band (stretched down), >1 = above the upper band. |
| **ATR** | Average True Range — typical candle size; a volatility yardstick. |
| **Expected move** | How far the market is "expected" to travel today, implied by India VIX. Used to judge if a move is *over-extended*. |
| **Stretch** | How far price has run from fair value (VWAP), measured in *expected-move* units. Big stretch = more likely to snap back. |
| **Divergence** | Price makes a new low/high but momentum/volume does **not** — a sign the move is tiring. |
| **Breadth** | % of the 50 biggest stocks trading above their own VWAP. Broad strength vs a narrow, fragile move. |
| **OI** | Open Interest — number of live option contracts at a strike (how much positioning sits there). |
| **IV** | Implied Volatility — the option market's expected volatility, used to price gamma. |
| **DTE** | Days To Expiry of the option chain used for gamma. |
| **VIX** | India VIX — the market's 30-day expected volatility (the "fear gauge"). |
| **Bull read** | 0–100, the case for *staying / long*: above VWAP it's the uptrend (ride-it) score; below VWAP it's the bounce-brewing (be-patient) score. |
| **Bear read** | 0–100, the case for *defending*: above VWAP it's the topping (defend-CALL) score; below VWAP it's the downtrend (defend-PUT) score. |
| **The 4 raw scores** | Reversal, Uptrend, Downtrend, Topping — the underlying 0–100 scores that Bull/Bear read are picked from (Part 2 §E). |
| **The 4 states** | BOUNCE_BREWING (▲), UPTREND/ride-it (★), DOWNTREND/defend-PUT (▼), TOPPING/defend-CALL (▽), or NEUTRAL. |
| **Pillars / votes** | Five independent checks — Price vs VWAP, Momentum, Volume, Breadth, Structure — each votes ▲ bull / ▼ bear / · flat. |
| **Signal agreement / Confidence** | 0–100: of the pillars, how many *agree* with the price direction. High = trustworthy; low = conflicted. |
| **Two-sided view** | Showing the BULL case and BEAR case for both condor legs at once (Part 3 §A). |
| **IST** | Indian Standard Time. All day/session logic uses IST. |

---

## 4. The honesty notes (also printed on the page)

- The **gamma regime is a *today-only* snapshot** — historical option open-interest
  isn't available, so the ▲/▼ chart marks come only from **price / volume / breadth**
  (things measurable on every past candle). The flip line is today's context.
- **Candles are futures; gamma levels are on spot strikes** → a few points of *basis*
  difference. Read the flip/walls as **zones**, not to-the-point levels.
- **CVD is a proxy** (Kite gives no tick-level buy/sell aggressor data).
- It **updates once per candle** (every 5 or 15 min) — not continuously.

➡️ **Next: Part 2 — every calculation, explained** (`PAGE_18_PART_2_CALCULATIONS.md`).
