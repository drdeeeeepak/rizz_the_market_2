# pages/27_BB_Fade_Rule_Book.py
# BB Fade — Rule Book. Same pattern as page 24/25's in-app rule-book expander,
# as its own page: renders docs/PAGE_27_RULE_BOOK.md, which only gets filled in
# once page 26's walk-forward split has actually confirmed an edge.

from pathlib import Path

import streamlit as st

st.set_page_config(page_title="P27 · BB Fade Rule Book", layout="wide")
st.title("Page 27 — BB Fade: Rule Book")
st.caption("Confirmed-rule record for the Bollinger-fade signals tested on page 26 — mirrors "
           "docs/PAGE_24_RULE_BOOK.md and docs/PAGE_25_RULE_BOOK.md. Nothing here is real until "
           "page 26's walk-forward split has actually confirmed it.")

_rulebook_path = Path(__file__).resolve().parent.parent / "docs" / "PAGE_27_RULE_BOOK.md"
if _rulebook_path.exists():
    st.markdown(_rulebook_path.read_text())
else:
    st.caption("Rule book file not found — see docs/PAGE_27_RULE_BOOK.md in the repo.")

st.divider()
st.caption("Go to page 26 to run (or re-run) the BB fade backtest.")
