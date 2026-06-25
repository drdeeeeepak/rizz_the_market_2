# Page 18 — Conviction Radar · Reference **Part 2b** — The four scores & the 4-state map

> Part 2a built the raw indicators. This sub-part turns them into the **four 0–100
> scores** (both sides of both regimes), the **4-state swing map** that drives the chart
> marks, the **reads panel**, and the two-line bull/bear summary. Part 2c then covers
> confluence and the behind-the-scenes table.

> **Reference map:** 1 overview · 2a indicators · **2b scores & states** · 2c confluence
> & table · 3 two-sided/gamma/close · 4 playbook.

---

## C. The four raw scores (both sides of both regimes)

Each is 0–100, summed from the Part 2a inputs, then capped. **These are the heart of the
two-sided view** — Part 1's Bull/Bear cards and the chart's reads panel are just these
four lines. *(Table cols: `Reversal`, `Uptrend`, `Downtr`, `Topping`.)*

### C.1 Reversal — "bounce brewing" (🟢 bull, only meaningful **below** VWAP)
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
- green **Reversal** (bounce brewing) and blue **Uptrend** (ride it) = the *bull* case;
- red **Downtrend** (defend PUT) and amber **Topping** (defend CALL) = the *bear* case.

The dotted lines at **55** and **60** are the trigger thresholds; a chart marker fires
when a score crosses its threshold (and beats the competing score). The purple-dotted
**Signal-agreement %** is overlaid (see Part 2c §G).

---

## F. Bull read & Bear read (the two-line summary)

A convenience collapse used by the metric cards (Part 2c §H):
```
bull_read = uptrend  (if above VWAP)   else  reversal
bear_read = topping  (if above VWAP)   else  downtrend
```
The two-sided cards in Part 3 §A use the **raw four** so you never lose the other side.

### F.1 Bull−Bear and Final — the two summary numbers
Two layers sit on top of the four scores (see also the card row in Part 3 §A):

```
Bull−Bear = bull_read − bear_read                  # raw lean, −100 .. +100
Final     = Bull−Bear × (Conf% / 100)              # trust-adjusted, −100 .. +100
```

- **`Bull−Bear`** (renamed from "Net") is the *raw* directional lean of the two case
  scores: >0 bull (stay / ride), <0 defend, ≈0 no edge.
- **`Final`** discounts that lean by **signal agreement** (`Conf%`, Part 2c §G) — so a
  strong-but-conflicted read shrinks (e.g. Bull−Bear +60 at 50% agreement → Final +30),
  exactly the "looks like a move but the pillars fight it" trap. This is the **headline**
  number; `Bull−Bear` is kept beside it so you can see how much the discount cost.

**Reading `Final` (both directions):** **+35 or more** = strong, agreed bull → act (stay /
roll the sold-PUT up) · **+15…+35** = real but unconfirmed bull → wait · **−15…+15** = no
edge → stand aside · **−15…−35** = real but unconfirmed bear → caution on the threatened
leg · **−35 or less** = strong, agreed bear → defend (manage the leg / sell-CALL).

Both are heat-shaded green (bull) / red (defend), darker as they get more extreme. Neither
replaces the four raw scores (which tell you *why*).

**Gamma tilt:** the **live Final *card*** multiplies in today's dealer gamma — `× 1.15` if
the regime backs the direction (cushioned + bull, or accelerator + bear), `× 0.85` if it
fights it — so the headline number is as real as possible *now*. The **table `Final`
column omits gamma**, because gamma is a daily value with no history before we began
logging it, so it can't be applied candle-by-candle to the past (see Part 3 §B for how the
stored daily gamma could be folded in where available). *(Table cols: `Final`, `Bull−Bear`.)*

➡️ **Next: Part 2c — confluence, metric cards & the behind-the-scenes table**
(`PAGE_18_PART_2C_CONFLUENCE_TABLE.md`).
