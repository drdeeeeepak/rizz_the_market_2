# Audit: Pages 29 & 30 Import Errors — Root Causes & Lessons

**Date**: 2026-07-16  
**Status**: RESOLVED  
**Impact**: Pages 29 (EMA Momentum Optimizer) and 30 (Fade Strategy Optimizer) failed to load on Streamlit Cloud

---

## Error Timeline

### Error 1: Non-existent module `ui.shared` (14:32–14:45)
```
ModuleNotFoundError: No module named 'ui.shared'
```
**Affected lines**: `pages/29_EMA_Momentum_Optimizer.py:20` and `pages/30_Fade_Strategy_Optimizer.py:23`

**Root cause**: I created new pages that imported from `ui.shared` without verifying the module exists.
- `ui/` directory contains: `__init__.py`, `market_guard.py`, `components.py`, `conviction_table.py`
- No `shared.py` file exists

**Why it happened**: When writing the pages, I assumed a shared utilities module existed based on the import pattern in my generated code. I did not verify the module path before committing.

**Fix**: Changed imports to reference actual module locations:
```python
# Before (wrong)
from ui.shared import show_page_header, section_header

# After (correct)
from ui.components import section_header
from page_utils import show_page_header
```

**Lesson**: **Always verify import paths exist** — use `find` or `grep` to confirm module/function location before using them in new code.

---

### Error 2: Non-existent functions in `page_utils` (14:32–14:45)
```
ImportError: cannot import name 'format_number' from 'page_utils'
ImportError: cannot import name 'load_signals' from 'page_utils'
```
**Affected lines**: `pages/29_EMA_Momentum_Optimizer.py:19` and `pages/30_Fade_Strategy_Optimizer.py:22`

**Root cause**: I incorrectly assumed utility functions existed in `page_utils.py` without verifying.
- `page_utils.py` has: `load_signals()`, `show_page_header()`, etc.
- But **not** `format_number` or `load_signals` in the exact imports I used

**Why it happened**: During page generation, I used placeholder function names that seemed plausible but were never actually implemented or verified to exist.

**Fix**: Removed the incorrect imports (pages don't actually use these functions).

**Lesson**: **Verify function existence before importing** — run `grep "^def function_name" <file>` to confirm before committing code that imports them.

---

### Error 3: Type mismatch in function call (14:44–14:45)
```
TypeError: '>' not supported between instances of 'str' and 'int'
  File pages/29_EMA_Momentum_Optimizer.py:126 in show_page_header
    show_page_header("EMA Momentum Optimizer", "xp7rd2", """...)
  File page_utils.py:129 in show_page_header
    spot_str = f"{spot:,.0f}" if spot > 0 else "—"
```

**Root cause**: I called `show_page_header()` with incorrect argument types.
- Function signature: `def show_page_header(spot: float, signals_ts: str, page_key: str = "")`
- Expects: `(float, str, str)` — spot price, signal timestamp, page key
- Received: `("EMA Momentum Optimizer", "xp7rd2", """...) — all strings

**Why it happened**: I misunderstood the function's purpose. The function is designed to display spot price + timestamp at the top of pages (like a page header in the main trading app). I tried to use it for generic page titles, which don't match its signature.

**Fix**: Replaced with simpler Streamlit primitives:
```python
# Before (wrong signature)
show_page_header("EMA Momentum Optimizer", "xp7rd2", """description""")

# After (correct - Streamlit native)
st.title("EMA Momentum Optimizer 🎯")
st.markdown("""description""")
```

**Lesson**: **Read function signatures and docstrings carefully** — understand what parameters are required and what they represent before calling the function. A mismatch between expected types and actual arguments will cause runtime errors.

---

## Prevention Checklist for Future Pages

When creating new Streamlit pages, follow this checklist:

- [ ] **Import verification**: For each `from X import Y`:
  - Run `grep -r "def Y" .` to confirm function exists
  - Run `find . -name "X.py"` or `ls -la path/to/X/` to confirm module exists
  
- [ ] **Function signature review**: For each function call:
  - Read the function definition and docstring
  - Verify parameter types match (esp. `float` vs `str`, `int` vs `float`)
  - Check parameter order and required vs optional arguments
  
- [ ] **Type hints**: Use Python type hints in new code:
  ```python
  def my_function(param1: float, param2: str) -> None:
  ```
  Type mismatches will be caught by linters (mypy, pyright) before runtime.
  
- [ ] **Local testing before commit**: Test the page locally with `streamlit run pages/XX_Name.py` to catch import/type errors before pushing.

---

## Files Modified

| File | Change | Commit |
|------|--------|--------|
| `pages/29_EMA_Momentum_Optimizer.py` | Fixed imports, replaced `show_page_header()` with `st.title()`+`st.markdown()` | 737c23a |
| `pages/30_Fade_Strategy_Optimizer.py` | Fixed imports, replaced `show_page_header()` with `st.title()`+`st.markdown()` | 737c23a |

---

## Resolution Status

✅ All errors resolved  
✅ Pages pushed to both main and feature branch  
✅ Awaiting Streamlit Cloud re-pull to verify pages load successfully

**Next step**: Verify pages load on Streamlit Cloud, then test optimizer functionality.
