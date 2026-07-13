# pages/27_Trend_Fade_Monitor.py
# LIVE dashboard — "what is the trend-confirmation signal saying TODAY,
# indicator by indicator and combined, and how ripe is it to fade?" The
# live counterpart to page 26's historical backtest: page 26 asks whether
# the idea works at all; this page reads today's value off the SAME
# adapters and grades it, using the rule this app has actually validated.
#
# You just: log in (Home → Kite) so the token is fresh, then click Run.

from pathlib import Path

import pandas as pd
import streamlit as st

import importlib
import data.live_fetcher as _lf
from analytics import position_sizing_backtest as ps

try:
    importlib.reload(_lf)
    importlib.reload(ps)
except Exception:
    pass

st.set_page_config(page_title="P27 · Trend Fade Monitor", layout="wide")
st.title("Page 27 — Trend Fade Monitor")
st.caption("Live reading of the same 5 adapters page 26 backtests, individually and combined, "
           "for TODAY only — not a backtest. See page 26 / docs/PAGE_26_WORKFLOW.md for how this "
           "was validated.")

with st.expander("⚠️ What's actually confirmed here — read once", expanded=True):
    st.markdown(
        "- **5 indicators, one composite.** Dow Theory (swing structure), EMA Ribbon (regime), "
        "EMA Moat Balance (support/resistance count), RSI Alignment (weekly/daily MTF), daily "
        "SuperTrend. Composite = their mean; UP/DOWN only fire when it clears a threshold AND "
        "enough indicators independently agree (same gating as page 26).\n"
        "- **Only the DOWN read is validated as a sizing edge.** Page 26's backtest showed "
        "call-side breaches running higher than put-side breaches when the composite reads DOWN, "
        "confirmed with the SAME direction in an early half AND a separate late half of the test "
        "history (docs/PAGE_26_WORKFLOW.md, section 2b) — genuine, if modest, evidence.\n"
        "- **The UP read is NOT validated.** It looked real in the early half of the backtest but "
        "showed zero breaches either side in the late half — inconclusive. It's shown here for "
        "completeness, never as a call to action.\n"
        "- **The grade below reflects confirmation STRENGTH (how many indicators agree), not "
        "profitability.** A 'STRONG UP' reading is a strongly-agreed-upon uptrend read that still "
        "has NO confirmed sizing edge behind it — strength of signal and strength of edge are two "
        "different things, and this page labels both separately so they don't get conflated.\n"
        "- No historical option premium/IV data exists in this app — nothing here is P&L, only "
        "directional/breach-rate evidence (same limitation as every other backtest page).")


@st.cache_data(ttl=1800, show_spinner=False)
def _load_daily(days):
    return _lf.get_nifty_daily(days=days)


@st.cache_data(ttl=1800, show_spinner=False)
def _load_h1(days):
    return _lf.get_nifty_1h_phase(days=days)


c1, c2 = st.columns(2)
with c1:
    lookback = st.slider("Daily lookback for indicator warmup (calendar days)", 365, 1460, 730,
                         step=30, key="p27_lookback")
with c2:
    h1_days = st.slider("1H lookback for Dow Theory (trading days, capped by Kite's 60-min "
                        "history limit)", 60, 380, 260, step=20, key="p27_h1_days")

if st.button("▶ Refresh today's reading", type="primary", key="p27_run"):
    st.session_state.p27_ran = True
    st.session_state.p27_inputs = dict(lookback=lookback, h1_days=h1_days)

if not st.session_state.get("p27_ran"):
    st.info("Click Refresh to pull today's candles and score all 5 indicators (~15-30s).")
    st.stop()

_in = st.session_state.p27_inputs

with st.spinner("Fetching history and reading today's signals…"):
    daily = _load_daily(_in["lookback"])
    h1 = _load_h1(_in["h1_days"])

if daily is None or daily.empty:
    st.error("Could not load daily Nifty history. Log in via Home → Kite, then retry.")
    st.stop()

snap = ps.live_snapshot(daily, h1 if h1 is not None else pd.DataFrame())

if not snap:
    st.error("Not enough history to compute a reading yet — try a longer lookback.")
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# Headline
# ══════════════════════════════════════════════════════════════════════════════
_bucket_colour = {"UP": "#16a34a", "DOWN": "#dc2626", "NEUTRAL": "#64748b"}
st.markdown(
    f"### As of {snap['as_of']} — composite reads "
    f"<span style='color:{_bucket_colour.get(snap['bucket'],'#64748b')}'>**{snap['bucket']}**</span> "
    f"({snap['agree_count']}/{snap['n_signals']} indicators agree, composite score {snap['composite']:+.2f})",
    unsafe_allow_html=True)
st.markdown(f"**{snap['grade']}**")

sc1, sc2, sc3 = st.columns(3)
sc1.metric("Suggested CE lots (flip_calibrated rule)", snap["suggested_lots_ce"])
sc2.metric("Suggested PE lots (flip_calibrated rule)", snap["suggested_lots_pe"])
sc3.metric("Your live default", "2 CE : 1 PE")

if snap["bucket"] != "DOWN":
    st.caption("Suggested ratio matches your default here — the flip_calibrated rule only "
               "changes sizing on a confirmed DOWN read.")

# ══════════════════════════════════════════════════════════════════════════════
# Per-indicator breakdown
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("Individual indicators, today")
rows = []
for name, info in snap["per_indicator"].items():
    rows.append({
        "indicator": name,
        "raw value": info["value"] if info["value"] is not None else "—",
        "reading": info["bucket"],
    })
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
st.caption("raw value ranges roughly -1 (strong bearish) to +1 (strong bullish) per indicator; "
           "±0.3 is the UP/DOWN cutoff for that indicator alone. 'reading' is that indicator's "
           "own opinion — the composite above is their combined, agreement-gated read, not a "
           "simple majority of this column.")
