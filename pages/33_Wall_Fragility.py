# pages/33_Wall_Fragility.py — Page 33: Wall Fragility Board
# If price tests this OI wall today, does it break violently or hold?
# Window: 3 buckets above and below ATM, rounded to 100 points.
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

import ui.components as ui
from analytics.wall_fragility import (
    BAND_BRITTLE, BAND_FORTRESS, BAND_NORMAL, WallFragilityEngine, band,
)

st.set_page_config(page_title="P33 · Wall Fragility", layout="wide")
st_autorefresh(interval=60_000, key="p33")
st.title("Page 33 — Wall Fragility Board")
st.caption("Air pocket · Wall vintage · LVN coincidence — conditional break risk at each OI wall")

from page_utils import bootstrap_signals, show_page_header

sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)

# ── Palette (matches pg02) ────────────────────────────────────────────────────
CE_RED   = "#ff4757"
PE_GREEN = "#00b894"
ATM_CYAN = "#0ea5e9"

# ── Expiry selector — default FAR, the expiry actually held ───────────────────
c1, c2 = st.columns([1, 3])
with c1:
    which = st.radio("Expiry", ["Far (traded)", "Near (tracked)"],
                     index=0, horizontal=True, key="p33_exp")

# ── Live data ─────────────────────────────────────────────────────────────────
chain, fut, expiry, dte, err = pd.DataFrame(), pd.DataFrame(), None, 0, ""
try:
    from data.live_fetcher import (
        get_dte, get_near_far_expiries, get_nifty_fut_intraday, get_nifty_spot,
        get_options_chain,
    )

    near_exp, far_exp = get_near_far_expiries()
    expiry = far_exp if which.startswith("Far") else near_exp
    dte    = get_dte(expiry)

    _live_spot = get_nifty_spot() or spot
    if _live_spot and _live_spot > 0:
        spot = _live_spot

    chain = get_options_chain(expiry, spot)
    # Futures, NOT the index — the index reports volume = 0 on Kite, so an
    # index-based profile would silently produce no LVNs at all.
    fut = get_nifty_fut_intraday(interval="30minute", days=10)
except Exception as e:
    err = f"{type(e).__name__}: {e}"

if err:
    st.error(f"Live data unavailable — {err}")
if chain.empty:
    ui.alert_box(
        "No usable option chain",
        "The chain could not be read (not logged in, or Kite returned an all-zero "
        "chain, which this app rejects rather than showing as real data). "
        "Fragility needs live OI — nothing below would be meaningful.",
        level="danger", big=True,
    )
    st.stop()

res   = WallFragilityEngine().signals(chain, spot, fut)
board = res["board"]
if board.empty:
    ui.alert_box("Board empty", "Chain read but no buckets fell inside the ATM window.",
                 level="warning")
    st.stop()

# ── Row 1 — headline cards ────────────────────────────────────────────────────
ui.section_header("Where the weak walls are",
                  f"{expiry:%d-%b-%Y} · {dte} DTE · ATM {res['atm']:,}")

k1, k2, k3, k4 = st.columns(4)
with k1:
    ui.metric_card("SPOT", f"{spot:,.0f}", f"ATM bucket {res['atm']:,}", "blue")
with k2:
    _s = res["weakest_above_sc"]
    ui.metric_card("WEAKEST ABOVE",
                   f"{res['weakest_above']:,}" if res["weakest_above"] else "—",
                   f"{res['weakest_above_bd']} · {_s:.0f}" if np.isfinite(_s) else "—",
                   border=CE_RED)
with k3:
    _s = res["weakest_below_sc"]
    ui.metric_card("WEAKEST BELOW",
                   f"{res['weakest_below']:,}" if res["weakest_below"] else "—",
                   f"{res['weakest_below_bd']} · {_s:.0f}" if np.isfinite(_s) else "—",
                   border=PE_GREEN)
with k4:
    ui.metric_card("VALIDATION", "UNVALIDATED", f"n = {res['sample_n']} breaks measured",
                   "amber")

# ── Row 2 — the board ─────────────────────────────────────────────────────────
ui.section_header("Fragility board", "3 buckets above and below ATM · 100-point steps")


def _lakh(v: float) -> str:
    return "—" if not np.isfinite(v) or v <= 0 else f"{v / 1e5:,.1f}L"


def _ratio(v: float) -> str:
    if not np.isfinite(v):
        return "—"
    return "∞" if np.isinf(v) else f"{v:.1f}×"


disp = pd.DataFrame({
    "Level":     [f"{i:,}" for i in board.index],
    "Side":      board["side"].values,
    "Wall OI":   [_lakh(v) for v in board["wall_oi"]],
    "Air Pocket": [_ratio(v) for v in board["air_ratio"]],
    "Fresh %":   [f"{v:.0f}%" if np.isfinite(v) else "—" for v in board["fresh_pct"]],
    "LVN":       ["●" if v else "" for v in board["at_lvn"]],
    "Fragility": [f"{v:.0f}" if np.isfinite(v) else "—" for v in board["fragility"]],
    "Band":      board["band"].values,
})
_atm_mask = board["is_atm"].values
_sides    = board["side"].values
_scores   = board["fragility"].values


def _row_style(row: pd.Series) -> list:
    i = row.name
    side_col = ATM_CYAN if _atm_mask[i] else (CE_RED if _sides[i] == "CE" else PE_GREEN)
    base = f"border-left:4px solid {side_col};"
    if _atm_mask[i]:
        base += "font-weight:700;background:#0a2a45;color:#67e8f9;"
    return [base] * len(row)


def _band_style(v: str) -> str:
    _, col = band({"FORTRESS": 0, "NORMAL": 45, "BRITTLE": 70,
                   "PAPER": 95}.get(v, float("nan")))
    return f"background:{col};color:#0b1220;font-weight:700;"


sty = (disp.style
       .apply(_row_style, axis=1)
       .map(_band_style, subset=["Band"])
       .set_properties(**{"font-family": "monospace", "font-size": "13px"}))
st.write(sty.hide(axis="index").to_html(), unsafe_allow_html=True)

ui.simple_technical(
    simple=("Higher fragility means: <b>if</b> price reaches this level today it is "
            "more likely to break through fast than to hold. It does NOT say price "
            "will get there."),
    technical=("Air Pocket = wall OI ÷ mean OI of the 3 buckets behind it in the break "
               "direction. Fresh % = share of the wall written today (Kite oi_day_change). "
               "LVN = the volume profile shows price does not trade here."),
)

# ── Row 3 — component breakdown ───────────────────────────────────────────────
ui.section_header("Component breakdown", "Shown unweighted — the composite is not yet earned")

comp = pd.DataFrame({
    "Level":       [f"{i:,}" for i in board.index],
    "Air pocket":  board["s_air"].values,
    "Vintage":     board["s_vintage"].values,
    "LVN":         board["s_lvn"].values,
}).set_index("Level")
st.bar_chart(comp, height=240)

st.caption(
    "F1 Air pocket · F2 Vintage · F3 LVN are live. "
    "F4 test decay, F5 coiling and F6 OI unwind need stored intraday history and are "
    "not built yet — the composite therefore rests on three of six components."
)

# ── Row 4 — validation notice ─────────────────────────────────────────────────
ui.alert_box(
    "UNVALIDATED — no measured break rates yet",
    "Every threshold on this page (air-pocket 1.0–3.0 scaling, 50% vintage, 30% LVN cut, "
    "and the 30/60/80 band edges) is a placeholder chosen to make the rules computable — "
    "not a value derived from data. Break rates per band are n = 0. Treat the board as a "
    "way to SEE wall structure, not as a signal to act on, until the sample exists.",
    level="warning", big=True,
)

# ── Diagnostics — stays in production (CLAUDE.md Lessons Rule 7) ──────────────
with st.expander("🔧 Diagnostics"):
    st.write({
        "expiry":            str(expiry),
        "dte":               dte,
        "spot":              spot,
        "atm_bucket":        res["atm"],
        "chain_strikes":     int(len(chain)),
        "chain_range":       f"{chain.index.min():,} … {chain.index.max():,}" if not chain.empty else "—",
        "chain_total_ce_oi": float(chain["ce_oi"].sum()),
        "chain_total_pe_oi": float(chain["pe_oi"].sum()),
        "fut_candles":       int(len(fut)),
        "fut_last_ts":       str(fut.index[-1]) if not fut.empty else "—",
        "fut_last_close":    float(fut["close"].iloc[-1]) if not fut.empty else 0.0,
        "fut_total_volume":  float(fut["volume"].sum()) if not fut.empty else 0.0,
        "spot_vs_fut_close": (float(spot) - float(fut["close"].iloc[-1])) if not fut.empty else 0.0,
        "lvn_detected":      bool(board["at_lvn"].any()),
        "bands_placeholder": f"{BAND_FORTRESS}/{BAND_NORMAL}/{BAND_BRITTLE}",
    })
    st.caption(
        "fut_total_volume must be > 0. If it is zero the profile was built on the INDEX "
        "(which reports no volume on Kite) and every LVN reading is meaningless."
    )
    st.dataframe(board, use_container_width=True)
