# AUDIT: Recent Misreading Mistakes — Root Causes

## What Happened

User requested: "and also dont need 60m trend and 30m trend column also"

**What I did:** Removed `60m_Div` and `30m_Div` (divergence) columns ❌
**What they meant:** Trend columns were already removed; keep Div columns but show blank when no divergence ✓

Result: Lost divergence data display, lost text coloring on RSI values.

---

## Root Causes

### 1. **Ambiguous Request Without Clarification**
- User said: "dont need 60m trend and 30m trend column also"
- The word "trend" could mean:
  - The trend arrow columns (↗ Rising, → Flat, ↘ Falling) — ALREADY REMOVED
  - The Div columns (confusing naming) — WHAT I REMOVED
- **I should have:** Asked "Do you mean the trend arrow columns (already removed) or the Divergence columns?"
- Instead: Assumed and acted without clarifying

### 2. **Didn't Read the Code After Changes**
- I said I'd remove "trend columns" but didn't verify what I actually removed
- If I had read the code, I would have seen:
  ```python
  rows.append({
      'Time': time_str,
      '60m_RSI': rsi_60m_val,
      '60m_Div': div_60m_str,  # ← This is Divergence, not Trend!
      '30m_RSI': f"{rsi_30m:.1f}",
      '30m_Div': div_30m_str,  # ← This too
      'Signal': signal
  })
  ```
- One `Read` call would have shown this wasn't Trend data

### 3. **Cascading Changes Without Full Impact Assessment**
- Removed Div columns → also removed Div styling function
- Removed Div styling → accidentally lost RSI text coloring in the process
- **Why:** When I removed `_div_row()` styling, I was focused on that one piece and didn't think about whether removing the function would affect RSI coloring
- **Impact:** Lost the original text color convention:
  - RED text when RSI declining
  - Dark red/green/slate when rising
  - This was a core requirement from earlier

### 4. **Oversimplified Styling Function**
- Original requirement: "Text: RED when RSI falling (declining), dark text when rising"
- I interpreted "only color the text in rsi number column" as "use simple zone-based coloring"
- **Wrong interpretation:** User meant "color the text (not just background), use red/green", not "only use background"
- Result: Removed the `is_declining` parameter from `_rsi_css()` function, losing text color variation

### 5. **Didn't Maintain Mental Model of Full Feature Set**
- Lost track that we needed:
  - RSI background colors (red/green/gray by zone)
  - RSI text colors (red when declining, dark red/green/slate when rising)
  - Divergence column (showing values when present, blank when not)
  - Signal column colors (green for LONG, red for SHORT)
- Made changes to individual pieces without verifying all pieces still worked together

---

## Prevention Checklist for Future

✓ **When request is ambiguous:**
1. Ask clarifying question FIRST before making changes
2. Example: "Do you mean column X or column Y?"
3. Wait for answer before proceeding

✓ **After every structural change:**
1. Read the affected code section back
2. Verify what was actually removed/changed
3. Check that all dependent features still work

✓ **When removing or modifying styling:**
1. Map out ALL styling rules that exist
2. Verify changes don't affect other styling
3. Test that all styled elements still display correctly

✓ **Maintain feature checklist:**
Before committing, verify:
- [ ] RSI cells have background colors (red/green/gray by zone)
- [ ] RSI text has color convention (red declining, dark red/green/slate rising)
- [ ] Divergence column shows values when present, blank when not
- [ ] Signal column has colors (green LONG, red SHORT)
- [ ] All columns are displayed as required

✓ **When feature requirements are complex:**
1. Keep a written list of all styling rules
2. Reference it before/after any changes
3. Comment in code what each styling does

---

## Specific Issue This Time

**What got lost:**
```python
# BEFORE (correct)
def _rsi_css(val, is_declining=False):
    if is_declining:
        text_color = "#dc2626"  # RED for declining
    else:
        text_color = text_color_rise  # Dark red/green/slate when rising
    return f"background-color:{bg_color};color:{text_color};..."

# AFTER (wrong - lost text color variation)
def _rsi_css(val):
    text_color = "#7f1d1d"  # Only dark red, no red for declining
    return f"background-color:{bg_color};color:{text_color};..."
```

The `is_declining` parameter got lost when I removed the hidden declining columns. But I should have restored it using the trend calculation we already had in the row-building code.

---

## How to Avoid This Going Forward

1. **Ask first, act second** — Ambiguous request = clarification question
2. **Read after editing** — Verify what actually changed
3. **Keep feature map** — Document all styling rules in code comments
4. **Test full pipeline** — Don't assume one change doesn't affect others
5. **Version your requirements** — When requirements are complex, write them down explicitly
