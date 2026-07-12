# Page 24 — Market Reversal Backtest: Final Rule Book

Consolidated conclusions from the full backtest series (fall/put side + rise/call
side), validated across multiple independent live-data pulls. This is the record —
update it if a future run changes a conclusion.

## A note on the small numbers (0.1–0.25%)

These aren't precision claims — they're the floor of what was tested. Safety stayed
**flat** from that floor up through several percent, across hundreds of episodes and
multiple reruns, checked programmatically (not eyeballed). The finding is "any small
confirmed move already gives full safety, a bigger one adds nothing" — not "exactly
0.25% is special." If that feels too small to act on in practice, use 0.5–1% instead —
the data says it costs nothing in safety, only a slightly worse entry price.

**Update — the 0% boundary is now confirmed, not extrapolated.** The literal "no
minimum move required at all" case (fall/rise trigger = 0.0%) was explicitly tested
on both sides: once even a 0.1% confirmed bounce/pullback shows up, touch-rate is
0.0% across the ENTIRE confirmation range (0.1–3%), on every horizon, on both the
1D scan and the 2D grid, independently. This closes the one gap previously flagged
as untested. The only edge-of-sample noise is in the ZERO-confirmation scans (no
bounce/pullback at all) — the 0.0% row there reads anomalously low compared to the
climbing trend just above it, on n=18–40, i.e. 0–1 actual events — a small-sample
artifact at the boundary, not a new pattern, consistent with what showed up at every
other edge in this series.

## PUT SELLING — after a FALL

1. **Fall trigger:** prior close → today's LOW drops ≥ **0.1%** (catches an
   intraday-only dip), OR close two days ago → today's close drops ≥ **0.75%**.
   0.1% is not "no trigger" — it's the smallest value actually tested, and
   checked directly against episode-merging: at 0.1% it produced FEWER distinct
   episodes than at 0.5% (63 vs. 93 in the same dataset), because closely-spaced
   small dips merge into one longer episode rather than firing separately. It
   does not turn into a daily/trivial signal.
2. **Confirmation:** an EOD close that bounces **≥0.1–0.25%** off the low. No
   green-candle filter needed — the bounce itself is confirmation enough.
3. **Deciding metric: `touch_low_rate`**, not `hit_rate`. A put seller doesn't need
   price to rise, only to not fall through the strike — that's what touch-rate
   measures. Confirmed flat at ~0% from the smallest tested bounce up through ~4%.
4. **Confidence:** ~100% at 3 trading days, ~97–99% at 5 days, once the bounce
   confirms — across every fall size tested (0.1% to 3%+).
5. **Strike placement:** sold put strike must sit a real distance BELOW the low —
   this rule protects the low itself, not automatically wherever your strike sits.
6. **`hit_rate` (continuation-up) is secondary** — useful for conviction/timing on a
   fresh directional bet, not for the safety decision. Bigger falls show *lower*
   continuation-up odds (messier recovery) — informative, not a safety gate.
7. **Caveats:** base-rate evidence from a few years of history, not a guarantee.
   Spot not breaching ≠ your option is fine (IV can still hurt). Keep your existing
   stop/roll rules regardless.

## CALL SELLING — after a RISE (mirror of the above, with one real asymmetry)

1. **Rise trigger:** prior close → today's HIGH climbs ≥ **0.1%**, OR close two
   days ago → today's close climbs ≥ **0.75%**. Same reasoning as the fall side —
   0.1% is the smallest value tested, and episode-merging keeps it from firing on
   ordinary daily noise.
2. **Confirmation is MANDATORY, not optional:** never sell a call with zero
   pullback. Acting immediately after a rise, with no pullback wait, showed a
   **70–80% touch-rate** — this is the real shakeout asymmetry (uptrends
   persistently make new highs as normal behavior). Wait for an EOD close that
   pulls back **≥0.25%** off the high before doing anything.
3. **Deciding metric: `touch_high_rate`**, not `hit_rate` — same reasoning as
   puts, mirrored. A short call pays off on survival (strike not breached), not on
   direction; time decay works in your favor whether price falls, chops, or drifts
   up a little. touch_high_rate is measured against the anchor high itself, which
   sits *below* your actual strike — a stricter, more conservative test than "did
   my strike survive," so passing it is extra reassurance, not less.
4. **Confidence:** once the ≥0.25% pullback confirms, touch_high_rate stays
   ~0–0.9% across the ENTIRE pullback range tested (0.25% to 3%) — no cutoff
   found. The occasional 0.9% blip (pullback 1.5–2.25%, specific rise sizes) is a
   single-episode sample artifact, not a trend — it appears in a narrow band and
   vanishes past it, the signature of one historical case, not a real pattern.
5. **Strike placement:** sold call strike must sit a real distance ABOVE the high.
6. **`hit_rate` (continuation-down) is secondary, and shaped differently than
   puts:** it peaks at the SMALLEST pullback (~0.25%, ~62%) and decays toward a
   coin flip (sometimes flipping slightly positive) past ~1.5–1.75% pullback. This
   means a bigger pullback is *not* stronger confirmation of a top — it
   increasingly looks like the shakeout itself. Useful for capital-allocation /
   conviction on a fresh directional bet; **does not** mean the position becomes
   unsafe past that point — safety (touch_high_rate) holds throughout.
7. **One simplification vs. puts:** the 0.25% pullback confirmation works the same
   way regardless of how big the preceding rise was — no need to scale the
   pullback requirement to rise size.
8. **Caveats:** same as puts, plus samples thin out fast above ~2% rise size (down
   to single digits) — treat those rows as directional, not precise.

## Position-management tools for the CALL leg specifically (separate from page 24)

Page 24's call-side analysis answers "is a fresh short call safe to place." For
managing an *existing* Iron Condor's CE leg (when to roll it), use the tools built
for that instead — a symmetric "will the high hold" rule isn't the right shape for
active roll decisions:
- **Page 22 → "Roll threshold" mode**: tests your live anchor/roll trigger
  against history.
- **Page 23 → section 7, "Roll-rule optimizer"**: finds the best strike-shift rule
  for defending a leg as drift builds.
