# pages/20_Conviction_Table.py
# Unified table-only Conviction Radar across timeframes (5m · 15m · 1H · 2H · 4H).
# No chart, cards or legend — just the behind-the-scenes candle table with a FROZEN
# header, sized to the viewport so only the table's rows scroll (the page itself stays
# put). Replaces the earlier separate 15m / 2H table pages.
#
# Per-timeframe behaviour:
#   • 5m, 15m      → SESSION VWAP (resets daily), daily expected-move for Stretch.
#   • 1H, 2H, 4H   → ANCHORED VWAP (resets each weekly expiry cycle), weekly expected-move.
#   • Breadth (all TFs) → % of Nifty-50 above each stock's own SESSION VWAP.

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

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

st.set_page_config(page_title="P20 · Conviction Table", layout="wide",
                   initial_sidebar_state="expanded")

# Trim Streamlit's chrome/top padding so the table fills the viewport. The table itself is
# sized to the viewport (below), so the page has nothing to scroll — only the table rows do.
st.markdown("""
<style>
.block-container { padding-top: 0.6rem !important; padding-bottom: 0 !important;
                   max-width: 100% !important; }
header[data-testid="stHeader"] { height: 0; visibility: hidden; }
[data-testid="stToolbar"] { display: none; }
</style>
""", unsafe_allow_html=True)

# Fetchers (bound after the reload).
get_nifty_fut_intraday = _lf.get_nifty_fut_intraday
get_nifty_intraday = _lf.get_nifty_intraday
get_nifty50_intraday = _lf.get_nifty50_intraday
get_india_vix = _lf.get_india_vix
get_dual_expiry_chains = _lf.get_dual_expiry_chains
get_nifty_fut_nh = getattr(_lf, "get_nifty_fut_nh", None)

# label → (source, anchored?).  source: a Kite interval string, or "2H"/"4H" (resample).
TF = {
    "5 min":  ("5minute",  False),
    "15 min": ("15minute", False),
    "1 hour": ("60minute", True),
    "2 hour": ("2H",       True),
    "4 hour": ("4H",       True),
}

# Auto-refresh cadence per timeframe (ms) — faster TFs refresh more often, slower ones
# back off (the underlying data caches are 5-min anyway, so this just paces the reruns).
REFRESH_MS = {
    "5 min": 60_000, "15 min": 60_000, "1 hour": 120_000,
    "2 hour": 180_000, "4 hour": 180_000,
}

sig, spot, _ = bootstrap_signals()
if spot <= 0:
    spot = float(sig.get("spot", 0))

# Controls live in the SIDEBAR so the main area is ONLY the table — that way the table
# fills the viewport and its bottom (horizontal) scrollbar is always reachable, with no
# top controls wrapping and shoving it off-screen.
_tf_keys = list(TF.keys())
SLUG = {"5 min": "5m", "15 min": "15m", "1 hour": "1h", "2 hour": "2h", "4 hour": "4h"}
SLUG_INV = {v: k for k, v in SLUG.items()}

# Seed the selection from the URL once per session (so a hard reload / shared link keeps
# the timeframe); thereafter session_state owns it.
if "tf20" not in st.session_state:
    st.session_state["tf20"] = SLUG_INV.get(st.query_params.get("tf"), "15 min")


def _sync_tf_to_url():
    st.query_params["tf"] = SLUG[st.session_state["tf20"]]


with st.sidebar:
    tf_label = st.selectbox("Timeframe", _tf_keys, key="tf20", on_change=_sync_tf_to_url)
    src, anchored = TF[tf_label]
    if anchored:
        # 1H over many cycles = a heavy breadth fetch → cap it tighter than 2H/4H.
        _max_cyc, _def_cyc = (4, 3) if src == "60minute" else (10, 6)
        n_cycles = st.slider("Expiry cycles", 2, _max_cyc, _def_cyc)
        days = n_cycles * 8 + 10
    else:
        days = st.slider("Trading days", 3, 10, 7)
        n_cycles = None
    use_breadth = st.checkbox("Nifty-50 breadth (heavier load)", value=True)
    if st.button("🔄 Refresh now", use_container_width=True):
        # Force fresh data: drop the cached fetches this page uses, then rerun.
        for _fn in (get_nifty_fut_intraday, get_nifty_intraday, get_nifty50_intraday,
                    get_india_vix, get_dual_expiry_chains):
            try:
                _fn.clear()
            except Exception:
                pass
        st.rerun()

# Keep the URL in sync with the current timeframe on every run (covers first load and
# hard reloads; assigning the same value is a no-op, so this won't loop).
st.query_params["tf"] = SLUG[tf_label]

# Per-timeframe auto-refresh cadence (soft rerun → keeps this tab's selected TF).
st_autorefresh(interval=REFRESH_MS.get(tf_label, 120_000), key="p20")

# ── Candles ───────────────────────────────────────────────────────────────────
if src in ("5minute", "15minute", "60minute"):
    df_raw = get_nifty_fut_intraday(interval=src, days=days)
    if df_raw is None or df_raw.empty:
        df_raw = get_nifty_intraday(interval=src, days=days)   # index fallback (no volume)
    breadth_interval = src
else:  # "2H" / "4H" — resampled from 60-min futures
    if get_nifty_fut_nh is None:
        st.warning("🔄 App just updated — open the menu (top-right ⋮) and **Reboot app** once "
                   "to load the N-hour resampler.")
        st.stop()
    df_raw = get_nifty_fut_nh(2 if src == "2H" else 4, days)
    breadth_interval = "60minute"

if df_raw is None or df_raw.empty:
    st.error("Could not load Nifty data from Kite for this timeframe. Check login / market "
             "data, then refresh.")
    st.stop()

# ── Expected move (Stretch calibration): weekly for anchored TFs, daily otherwise ──
vix = get_india_vix() or 0.0
if anchored:
    expected_move_pts = spot * (vix / 100.0) / 16.0 * (5 ** 0.5) if vix > 0 else spot * 0.013
else:
    expected_move_pts = spot * (vix / 100.0) / 16.0 if vix > 0 else spot * 0.006

# ── Breadth (always from each stock's session VWAP) ───────────────────────────
breadth = pd.Series(dtype=float)
if use_breadth:
    breadth = ic.breadth_series(get_nifty50_intraday(interval=breadth_interval, days=days))

df = ic.enrich(df_raw, expected_move_pts=expected_move_pts,
               breadth=breadth if not breadth.empty else None, anchored_vwap=anchored)

# Anchored TFs: keep only the last n_cycles weekly expiry cycles.
if anchored and n_cycles and not df.empty:
    _ck = pd.Series([ic._expiry_cycle_key(ts) for ts in df.index], index=df.index)
    _uc = sorted(_ck.unique())
    if len(_uc) > n_cycles:
        df = df[_ck >= _uc[-n_cycles]].copy()

# ── Gamma-by-date map (stored daily regimes + today's live) for the γ column ──
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

# ── Table only — frozen header, viewport-sized scroll box ─────────────────────
_REQ = {"bull_read", "bear_read", "state", "vwap", "confidence"}
if df.empty or not _REQ.issubset(df.columns) or not hasattr(ic, "candle_table"):
    st.warning("🔄 App just updated — open the menu (top-right ⋮) and **Reboot app** once.")
    st.stop()

ct = ic.candle_table(df, newest_first=True, gamma_by_date=_gmap)
if ct.empty:
    st.info("No candles to show.")
else:
    st.markdown(uict.candle_table_frozen_html(ct, height="calc(100vh - 60px)"),
                unsafe_allow_html=True)
