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
/* Pull the table to the top: kill Streamlit's big default top padding (1.58 uses
   stMainBlockContainer; older builds use .block-container — target both). */
[data-testid="stMainBlockContainer"], .block-container, .stMainBlockContainer {
    padding-top: 0.3rem !important; padding-bottom: 0 !important; max-width: 100% !important;
}
header[data-testid="stHeader"] { height: 0; visibility: hidden; }
[data-testid="stToolbar"], [data-testid="stDecoration"] { display: none; }
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
# parent-bucket size (minutes) per source — used to group children under a parent candle.
_BLOCK_MIN = {"5minute": 5, "15minute": 15, "60minute": 60, "2H": 120, "4H": 240}

# Seed the selection from the URL once per session (so a hard reload / shared link keeps
# the timeframe); thereafter session_state owns it.
if "tf20" not in st.session_state:
    st.session_state["tf20"] = SLUG_INV.get(st.query_params.get("tf"), "15 min")


def _sync_tf_to_url():
    st.query_params["tf"] = SLUG[st.session_state["tf20"]]


def _fetch_enriched(label, days, want_breadth):
    """Fetch + enrich one timeframe's candles (no cycle slicing). Returns a df or None.
    5m/15m use session VWAP + daily expected-move; 1H/2H/4H use anchored VWAP + weekly."""
    s, anch = TF[label]
    if s in ("5minute", "15minute", "60minute"):
        d = get_nifty_fut_intraday(interval=s, days=days)
        if d is None or d.empty:
            d = get_nifty_intraday(interval=s, days=days)
        b_int = s
    else:
        if get_nifty_fut_nh is None:
            return None
        d = get_nifty_fut_nh(2 if s == "2H" else 4, days)
        b_int = "60minute"
    if d is None or d.empty:
        return None
    v = get_india_vix() or 0.0
    if v > 0:
        em = spot * (v / 100.0) / 16.0 * ((5 ** 0.5) if anch else 1.0)
    else:
        em = spot * (0.013 if anch else 0.006)
    br = pd.Series(dtype=float)
    if want_breadth:
        br = ic.breadth_series(get_nifty50_intraday(interval=b_int, days=days))
    return ic.enrich(d, expected_move_pts=em,
                     breadth=br if not br.empty else None, anchored_vwap=anch)


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
    # Drill-down: expand each candle to ANY lower timeframe's candles inside it.
    _lower = _tf_keys[:_tf_keys.index(tf_label)]
    drill_label = (st.selectbox("Drill-down into", ["Off"] + _lower, index=0)
                   if _lower else "Off")
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

# ── Parent timeframe ──────────────────────────────────────────────────────────
df = _fetch_enriched(tf_label, days, use_breadth)
if df is None or df.empty:
    st.error("Could not load Nifty data from Kite for this timeframe. Check login / market "
             "data, then refresh.")
    st.stop()

# Anchored TFs: keep only the last n_cycles weekly expiry cycles.
if anchored and n_cycles:
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
    st.stop()

_H = "calc(100vh - 45px)"
if drill_label == "Off":
    st.markdown(uict.candle_table_frozen_html(ct, height=_H), unsafe_allow_html=True)
else:
    # ── Drill-down: show each parent candle's lower-TF children, expandable in place ──
    child_df = _fetch_enriched(drill_label, days, use_breadth)
    if child_df is None or child_df.empty:
        st.warning(f"No {drill_label} data to drill into — showing the flat table.")
        st.markdown(uict.candle_table_frozen_html(ct, height=_H), unsafe_allow_html=True)
    else:
        # Keep only children inside the parent's displayed span, then group by parent bucket.
        child_df = child_df[(child_df.index >= df.index.min()) &
                            (child_df.index <= df.index.max())]
        ct_child = ic.candle_table(child_df, newest_first=False, gamma_by_date=_gmap)
        ct_p = ct[uict.DRILL_COLS]
        ct_c = ct_child[uict.DRILL_COLS].copy()
        _blk = _BLOCK_MIN[src]

        def _parent_bucket(ts):
            m = ts.hour * 60 + ts.minute
            b = max(0, (m - 555) // _blk)
            return ts.normalize() + pd.Timedelta(minutes=555 + b * _blk)

        ct_c["_pk"] = [_parent_bucket(ts) for ts in ct_c.index]
        kids = {k: g.drop(columns="_pk").iloc[::-1] for k, g in ct_c.groupby("_pk")}
        st.markdown(
            uict.candle_table_drilldown_html(ct_p, kids, height=_H, child_label=drill_label),
            unsafe_allow_html=True)
