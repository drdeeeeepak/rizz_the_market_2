# Page 25 — Roll & Position Management: Rule Book

Working record for managing an EXISTING Iron Condor (when to roll the profit leg
in, when to roll/shift the loss leg out). Separate from `docs/PAGE_24_RULE_BOOK.md`,
which answers a different question — is a FRESH short safe to place right now.

This page assumes the reference position: **CALL sold ~3% above Tuesday anchor,
PUT sold ~3.5% below**, squared off within 5 trading days (biweekly hold).

## Status: partially confirmed — loss-leg side still needs a dedicated re-run

## PROFIT LEG — when to roll it in, and by how much

Derived from Page 25 section 7 (Roll-rule optimizer), using the real 3%/3.5%
strike distances (`roll_rule_near.csv` = near/weekly window, `roll_rule_far.csv` =
biweekly window).

1. **Trigger (X): roll at ~0.75% drift from anchor.** This is the earliest point
   survival_rate reaches its plateau — 90.2% near-expiry, 69.9% biweekly. Waiting
   longer (up to ~2.5%) doesn't lose you anything (same plateau), but triggering
   *earlier* (0.25–0.5%) actively hurts survival, especially paired with a larger
   shift-in size.
2. **Shift size (Y): the smallest tested value, 0.25%, is safest at every X
   tested** — survival decreases monotonically as Y grows, at every trigger:

   | X (trigger) | Y=0.25% | Y=0.75% | Y=1.25% |
   |---|---|---|---|
   | 0.75% | 90.2% / 69.9% | 88.7% / 66.3% | 86.1% / 57.5% |
   | 1.25% | 90.2% / 69.9% | 89.7% / 69.4% | 88.1% / 66.3% |
   | 1.75% | 90.2% / 70.5% | 90.2% / 70.5% | 90.2% / 69.9% |

   (near-expiry% / biweekly%)
3. **If you want a bigger, more comfortable Y (largest tested = 1.25%) with
   ZERO breach risk on the leg you just rolled**, pair it with a later trigger:
   **X ≥ 1.75%, Y = 1.25%** gives 90.2% survival AND 0.0% breach-on-rolled-leg
   (near-expiry table), vs. 5.2% breach-on-rolled-leg if you use Y=1.25% at
   X=0.75%. Cost: fewer, later rolls (avg_rolls 0.47 vs 1.82).
4. **Recommended pairing for "roll as early as possible" (the stated goal):
   X = 0.75%, Y = 0.25%.** Small, frequent, safe steps — 90.2%/69.9% survival,
   ~1.8 rolls per near-expiry cycle.
5. **No real premium/IV data exists in this app** (Kite gives only a live chain
   snapshot, no historical option prices) — `avg_rolls` is the only available
   proxy for "premium captured," not an actual P&L number. A follow-up backtest
   using a parametric premium model (e.g. Black-Scholes + historical VIX as an
   IV proxy) was considered and explicitly declined — decision was to keep this
   survival-only for now.

## LOSS LEG — when to roll/shift it out

**Not yet finalized.** Page 22's original "Roll threshold" scan (section 1 on
this page) found loss_thr=4.0% best, but that number is invalid for this
purpose: it sits at the edge of the scanned range (unverified true optimum) AND
it exceeds the actual 3%/3.5% strike distances — a trigger that can only fire
*after* the strike distance in the reference position is already breached.

**Needed:** re-run section 1 (Roll threshold) or, better, extend the roll-rule
optimizer (section 7) with a defend/loss-side mode, scanning loss-trigger %
capped BELOW 3% (the nearer strike), not above it.

## Position-management cross-reference

- **Page 24** — is a fresh short safe to place right now (entry timing, not
  roll timing). See `docs/PAGE_24_RULE_BOOK.md`.
- **Section 1 (Roll threshold)** on this page — pattern-only, no strike
  awareness; useful for sanity-checking the shape of the anchor-drift rule, not
  for a final number.
- **Sections 2–4 (Anchor close-distribution / drift-reversion / optimum
  threshold)** — the empirical basis for why a drift-based trigger makes sense
  at all, and roughly where the reversion/continuation line sits.
- **Sections 5–6 (Strike-shift ladders)** — a fixed-schedule alternative to the
  optimizer in section 7 (points-based steps instead of a repeatable %-based
  rule) — useful if you'd rather use a fixed plan than a repeatable trigger.
