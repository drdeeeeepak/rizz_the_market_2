# Page 26 — Position Sizing Backtest: workflow

**The question this answers**: does a trend-confirmation signal (or a
combination of signals) tell you, cycle by cycle, when it's safe to flip your
lot allocation from the static 2 CALL : 1 PUT default toward 2 PUT : 1 CALL
(uptrend) or further toward CALL-heavy (downtrend)? See
`docs/PAGE_25_RULE_BOOK.md` for the reference position this assumes (CALL
~3% above Tuesday anchor, PUT ~3.5% below, squared off within a week).

## Why this doesn't run in this chat

Claude Code sessions here don't hold a live Kite login — the historical
daily/1H Nifty data this backtest needs only exists behind an authenticated
Kite session. That session lives in the deployed Streamlit app (refreshed via
**Home → Kite login**, and kept warm day-to-day by the EOD GitHub Action —
`.github/workflows/eod_compute.yml` — which runs at 3:35 PM IST and writes
`access_token.txt`). So the fetch-and-analyze step has to happen **in the
app**, not here. This doc is the handoff: run it there, bring the output back
here, and I'll interpret it.

## Step by step

1. **Log in.** Open the deployed Streamlit app → `Home.py` → Kite login (skip
   if you logged in already today; the token is shared across pages).
2. **Open Page 26** (Position Sizing Backtest) from the sidebar.
3. **Set parameters** (defaults match your actual position, so usually just
   click Run):
   - Daily lookback — how many calendar days of history to test (default
     730 ≈ 2 years; the 1H slider below caps how far back Dow Theory can go).
   - Sold CALL / PUT distance % — default 3.0 / 3.5, matching your live
     strikes. Change these if your actual distances differ.
   - 1H lookback — capped by Kite's 60-minute history limit (60–380 trading
     days, default 260). Only affects the Dow Theory adapter.
   - Hold horizon — trading days until square-off (default 5 ≈ 1 week).
   - Composite UP/DOWN threshold and Min adapters agreeing — how strict the
     combined signal has to be before it overrides the static default. Start
     with the defaults (0.4, 3) and only loosen them if section 2 shows too
     few UP/DOWN cycles to read.
   - Tuesdays only — leave checked; that's when the sizing decision is
     actually made (Tuesday EOD anchor).
4. **Click ▶ Run.** Takes ~15–30s (fetches daily + 1H candles, scores 5
   adapters individually, builds the composite, scores 3 lot schemes).
5. **Read the three sections:**
   - **Section 1** — each of the 5 indicators scored alone: does UP show a
     lower call-breach% / higher put-breach% than DOWN (or the reverse)? A
     flat table (UP ≈ DOWN) means that indicator isn't separating CE risk
     from PE risk by itself.
   - **Section 2** — the composite (agreement-gated combination of all 5).
     Compare its UP/DOWN gap to the best single indicator in section 1 — if
     it's not wider, combining lenses isn't earning its complexity.
   - **Section 2b** — early half vs late half, out-of-sample check. The same
     cycles from section 2, split chronologically in two and scored
     independently (full history still feeds every indicator's warmup —
     only the evaluation rows split). **This is the one that actually
     answers "is this a real edge or one lucky stretch."** If
     call_breach%/put_breach% point the same direction in BOTH halves,
     that's genuine support. If they disagree, the whole-window number in
     section 2 was probably one regime talking, not a repeatable pattern.
   - **Section 3** — the lot-scheme scorecard: `static_2CE_1PE` (today's
     live default), `static_1_1` (symmetric baseline), `dynamic_flip` (the
     rule as originally hypothesized — flip toward the trend), and
     `flip_calibrated` (flip AGAINST the trend on a confirmed DOWN read,
     calibrated to what the first real run actually showed). Lower
     `expected_breached_lots_per_cycle` / `breach_rate_per_lot%` = fewer
     expected leg-breaches for the same premium-collecting effort.
6. **Export.** Use the download buttons under sections 1, 2b, and 3
   (per-indicator CSV, early/late split CSV, lot scorecard CSV) — or just
   copy/paste the on-screen tables, or a screenshot.

## Bringing it back to me

Paste (or attach) whatever combination of the three CSVs / table screenshots
you have. Tell me the parameters you ran with if they're not the defaults
(lookback, call%/put%, horizon, threshold, min_agree). I'll:

- read the breach-rate gaps and tell you whether any single indicator (or
  the composite) is actually separating CE risk from PE risk, or whether the
  gap is noise given the sample size (`n` per bucket matters — a 3-cycle
  bucket isn't a finding),
- tell you whether `dynamic_flip` actually beats the static default on
  `breach_rate_per_lot%`, and by how much,
- suggest threshold/min_agree adjustments to re-run if the first pass is
  inconclusive (too few UP/DOWN cycles, or thresholds too loose to mean
  anything),
- once a rule survives a couple of independent re-runs (different lookback
  windows), write it into `docs/PAGE_26_RULE_BOOK.md`, matching how pages 24
  and 25's rule books were built.

## Caveats carried over from pages 24/25

- **No historical option premium/IV data exists anywhere in this app** (Kite
  gives only a live chain snapshot). Every number here is a **breach rate**,
  not P&L — `expected_breached_lots_per_cycle` is a proxy for "how often the
  leg you sized up actually got tested," not a currency figure.
- These are base-rate cutoffs to stack the odds, not guarantees. Keep your
  existing roll/stop discipline regardless of what this shows.
