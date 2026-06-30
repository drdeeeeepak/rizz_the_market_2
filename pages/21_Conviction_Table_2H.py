# pages/21_Conviction_Table_2H.py
# Table-only view of the 2H positional Conviction Radar (page-19 engine, VWAP anchored
# to each weekly expiry cycle). No chart, no cards, no legend/reference — just the
# behind-the-scenes candle table with a FROZEN header. The PAGE itself does not scroll;
# only the table's rows scroll, so the header never slips away.

import pandas as pd
import streamlit as st

import ui.conviction_table as uict
from page_utils import bootstrap_signals
from analytics.gamma_exposure import compute_gex
from analytics import intraday_conviction as ic

# Reload data + engine + table styler so a fresh deploy never runs against a stale module.
import importlib
import data.live_fetcher as _lf
try:
    importlib.reload(_lf)
    importlib.reload(ic)
    importlib.reload(uict)
except Exception:
    pass

st.set_page_config(page_title="P21 · 2H Table", layout="wide")

# Lock the page: no page scroll — only the table rows scroll. Trim Streamlit's chrome and
# top padding so the 600px table fits the viewport.
st.markdown("""
<style>
section[data-testid="stMain"], [data-testid="stAppViewContainer"] section.main,
[data-testid="stMainBlockContainer"] { overflow: hidden !important; }
.block-container { padding-top: 0.6rem !important; padding-bottom: 0 !important;
                   max-width: 100% !important; }
header[data-testid="stHeader"] { height: 0; visibility: hidden; }
[data-testid="stToolbar"] { display: none; }
</style>
""", unsafe_allow_html=True)

if not hasattr(_lf, "get_nifty_fut_2h"):
    st.warning("🔄 App just updated — open the menu (top-right ⋮) and **Reboot app** once "
               "to load the 2H data fetcher.")
    st.stop()
get_nifty_fut_2h = _lf.get_nifty_fut_2h
get_india_vix = _lf.get_india_vix
get_dual_expiry_chains = _lf.get_dual_expiry_chains
get_nifty50_intraday = _lf.get_nifty50_intraday

sig, spot, _ = bootstrap_signals()
if spot <= 0:
    spot = float(sig.get("spot", 0))

c1, c3 = st.columns([1, 3])
with c1:
    n_cycles = st.slider("Cycles", 2, 10, 6)
with c3:
    use_breadth = st.checkbox("Nifty-50 breadth (heavier load)", value=True)

days = n_cycles * 8 + 10

# ── Data ──────────────────────────────────────────────────────────────────────
df2 = get_nifty_fut_2h(days=days)
if df2 is None or df2.empty:
    st.error("Could not load Nifty 2H data from Kite. Check login / market data, then refresh.")
    st.stop()

vix = get_india_vix() or 0.0
expected_move_pts = spot * (vix / 100.0) / 16.0 * (5 ** 0.5) if vix > 0 else spot * 0.013

breadth = pd.Series(dtype=float)
if use_breadth:
    breadth = ic.breadth_series(get_nifty50_intraday(interval="60minute", days=days))

df = ic.enrich(df2, expected_move_pts=expected_move_pts,
               breadth=breadth if not breadth.empty else None, anchored_vwap=True)

# Slice to the last n_cycles expiry cycles.
if not df.empty:
    _ck = pd.Series([ic._expiry_cycle_key(ts) for ts in df.index], index=df.index)
    _uc = sorted(_ck.unique())
    if len(_uc) > n_cycles:
        df = df[_ck >= _uc[-n_cycles]].copy()

# Gamma-by-date map (stored daily regimes + today's live) for the γ column.
_gmap = {}
try:
    from data.gamma_history import load_daily_history
    _gmap = {r.get("date"): r.get("regime") for r in load_daily_history() if r.get("date")}
except Exception:
    pass
if spot > 0:
    chains = get_dual_expiry_chains(spot)
    near_df = chains.get("near", pd.DataFrame())
    near_dte = chains.get("near_dte", 7)
    atm_iv = float(sig.get("atm_iv", 12.0) or 12.0)
    gex = compute_gex(near_df, spot, near_dte, iv_fallback_pct=atm_iv)
    if gex.get("regime") in ("POSITIVE", "NEGATIVE"):
        _gmap[pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d")] = gex.get("regime")

# ── Table only — frozen header, fixed 600px scroll box ────────────────────────
_REQ = {"bull_read", "bear_read", "state", "vwap", "confidence"}
if df.empty or not _REQ.issubset(df.columns) or not hasattr(ic, "candle_table"):
    st.warning("🔄 App just updated — open the menu (top-right ⋮) and **Reboot app** once.")
    st.stop()

ct = ic.candle_table(df, newest_first=True, gamma_by_date=_gmap)
if ct.empty:
    st.info("No candles to show.")
else:
    st.markdown(uict.candle_table_frozen_html(ct, height=600), unsafe_allow_html=True)
