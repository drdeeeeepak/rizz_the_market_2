# Page 27 — BB Fade: Rule Book

Working record for the Bollinger-Band mean-reversion ("fade") signals tested on
page 26. Same pattern as `docs/PAGE_24_RULE_BOOK.md` / `docs/PAGE_25_RULE_BOOK.md`
— nothing goes here until page 26's walk-forward split has actually confirmed it.

## Status: pending — no confirmed rule yet

Page 26 tests two already-coded signals from `analytics/signal_adapters.py`:

1. **Bollinger %B Fade** (`adapt_bollinger_pctb`) — %B pinned to/above the upper
   band scores as fade-SHORT (expects reversion down); at/below the lower band
   scores fade-LONG.
2. **Bollinger Asymmetry Fade** (`adapt_bollinger_asymmetry_fade`) — mean-reversion
   mirror of page 09's live asymmetry-ratio output.

## What "confident" means before this section gets filled in

From page 26 section 2 (walk-forward split, by year or half):

- **Same sign** of expectancy/hit_rate in most or all splits — not flipping
  between fade-works and fade-fails depending on the regime.
- **Non-trivial magnitude** — an expectancy that rounds to ~0% in most splits
  isn't a real edge, even if the whole-sample average looks fine.
- Whole-sample stats (section 1) are a starting point, not the proof — the
  walk-forward split is the actual gate, same standard already applied to the
  RSI overbought-fade rule on page 23.

## Next step

Run page 26, read the walk-forward tables, and bring the result back — this
file gets the same treatment as the roll rule book once one or both signals
clear that bar: a numbered rule set with the exact trigger, confidence level,
and caveats, plus a cross-reference to where/how to actually use it.
