# Page 18 — Conviction Radar · Reference **Part 4 of 4** — How to act (playbook)

> Putting it together for an Iron Condor seller. These are odds, not certainties —
> keep your stop and size for the case where the signal is wrong.

> **Reference map:** Part 1 — overview & glossary · Part 2a/2b/2c — every calculation ·
> Part 3 — two-sided, gamma & close · Part 4 — playbook (this file).

---

## 1. You're short a PUT and the market is falling

1. **Headline card.** `BE PATIENT` → don't book at the low; wait for a VWAP reclaim.
   `DEFEND PUT — real downtrend` → manage the leg, no V coming.
2. **Both-sides cards (Part 3 §A).** Watch the 🟢 BULL CASE *Reversal* score vs the
   🔴 BEAR CASE *Downtrend* score. Reversal climbing while Downtrend stalls = the fall
   is tiring; Downtrend climbing through 58 with persistence = a real down-leg.
3. **Market mode.** Shock-absorber backs patience; accelerator says keep a hard line.
4. **Breadth.** A fall on <40% breadth is broad and real; a bounce on <50% breadth is
   narrow and fragile.
5. **Watch the latest candle.** A **green ▲** = exhaustion building; when it turns into a
   **blue ★ `RIDE THE UPTREND`**, the bounce is confirmed and your PUT side is safe.

---

## 2. Is the bounce / uptrend real, or a trap?

- A blue **★ RIDE THE UPTREND** means price reclaimed fair value **and** is making
  higher lows **and** breadth >50% **and** buyers (CVD) returned — a *confirmed* up-leg,
  not a one-candle pop. Stay in it; trail a stop under the last higher-low.
- Cross-check the **reads panel**: the blue *Uptrend* line should be above its 55
  threshold and above the amber *Topping* line. If *Topping* is climbing instead, the
  up-move is tiring — watch your sold-CALL leg.
- If the **Signal-agreement %** is low (pillars fighting), the engine withholds the ★ —
  treat a "looks like a breakout" with suspicion until agreement climbs.

---

## 3. Deciding whether to trust a late-day bounce

- Look at the **🔴 LIVE** close-quality row in the last hour. **LOW** = treat the bounce
  as a likely short-cover; don't chase, expect gap risk into next session.
- Read the **score build-up chips** (Part 3 §D): a `short-cover −25` chip with a
  `VWAP −18` chip is the classic trap — a late pop on heavy volume that still finished
  below fair value.

---

## 4. Using the 🔬 behind-the-scenes table

When a marker surprises you, open the table and read that candle's row:
- **Did the right score cross its threshold?** (Reversal/Uptrend ≥ 55–60 for bull marks,
  Downtrend ≥ 58 / Topping ≥ 55 for defend marks.)
- **Did the pillars agree?** `P/M/V/B/S` should mostly point the same way; 2+ opposing
  arrows (`Conf%` low) is why a continuation mark was withheld.
- **Which inputs fired?** e.g. a ▲ brewing with `BullDiv`, `CVDdiv`, a fat `LWick` and a
  deep red `Stretch` (well below fair value) is a high-quality exhaustion candle; one
  with only a small `Stretch` is thin. Glance at `Hi`/`Lo` for the swing skeleton.

This is the fastest way to build trust in (or healthy skepticism of) the signals.

---

## 5. Quick reference — what each chart mark means

| Mark | State | Plain meaning | Your leg |
|---|---|---|---|
| green **▲** | BOUNCE_BREWING | fall looks tired — be patient | sold-PUT relief building |
| blue **★** | UPTREND | bounce confirmed continuing — ride it | sold-PUT safe; watch CALL if it runs |
| red **▼** | DOWNTREND | persistent below fair value — defend | sold-PUT at risk |
| amber **▽** | TOPPING | up-move exhausted — defend | sold-CALL at risk |

---

## 6. Always

- These shift the odds; they are **not** a guarantee.
- Keep your hard stop.
- Position-size for the case where the signal is wrong.
- The gamma regime is **today-only**; the per-candle marks are price/volume/breadth.
- Candles are **futures**, gamma levels are on **spot** strikes → read flip/walls as
  *zones*, not to-the-point levels.

---

*Files: `pages/18_Conviction_Radar.py`, `analytics/intraday_conviction.py`,
`analytics/gamma_exposure.py`, fetchers in `data/live_fetcher.py`. Reference split:
`PAGE_18_PART_1_OVERVIEW.md` · `PAGE_18_PART_2A_INDICATORS.md` ·
`PAGE_18_PART_2B_SCORES.md` · `PAGE_18_PART_2C_CONFLUENCE_TABLE.md` ·
`PAGE_18_PART_3_TWO_SIDED_AND_GAMMA.md` · `PAGE_18_PART_4_PLAYBOOK.md`.*
