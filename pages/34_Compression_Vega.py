# pages/34_Compression_Vega.py — Page 34: Compression / Vega Regime
# A vega filter for a short-vol book — NOT a directional signal.
# Compression means expansion is due; paired with a low IV percentile it means
# thin premium at maximum risk, the worst configuration for a seller.
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

import ui.components as ui
from analytics.base_strategy import BaseStrategy
from analytics.compression import (
    ACCUM_ATR_MULT, COMPRESS_MAX_DAYS, COMPRESS_PCTILE, CONTRACT_SESSIONS,
    IVP_HIGH, IVP_LOW, LOOKBACK_SESSIONS, STATE_COLORS, CompressionEngine,
)

st.set_page_config(page_title="P34 · Compression / Vega", layout="wide")
st_autorefresh(interval=60_000, key="p34")
st.title("Page 34 — Compression / Vega Regime")
st.caption("Value-area width · contraction · IV percentile — is expansion due, and are you paid for it?")

from page_utils import bootstrap_signals, show_page_header

sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)

# ── Data ──────────────────────────────────────────────────────────────────────
fut, daily, atr14, ivp, err = pd.DataFrame(), pd.DataFrame(), 0.0, float("nan"), ""
try:
    from data.live_fetcher import (
        get_india_vix_detail, get_nifty_daily, get_nifty_fut_intraday, get_vix_history,
    )

    # FUTURES, not the index — the index reports volume = 0 on Kite, which would
    # give a flat histogram and a meaningless value area on every session.
    fut = get_nifty_fut_intraday(interval="30minute", days=40)

    daily = get_nifty_daily(days=120)
    if not daily.empty:
        atr14 = float(BaseStrategy.atr(daily, 14).iloc[-1])

    vix_cur, _vix_pts, _vix_pct = get_india_vix_detail()
    vix_hist = get_vix_history(days=365)
    if vix_cur > 0 and not vix_hist.empty and not daily.empty:
        from analytics.vix_iv_regime import VixIVRegimeEngine
        # Reused so this page's IV percentile matches page 11 exactly rather than
        # being a second implementation that can silently disagree.
        # atm_iv is passed 0.0 on purpose: ivp_1yr does not depend on it, and the
        # vrp / home_score / warnings it would affect are NOT read here.
        _v = VixIVRegimeEngine().signals(daily.copy(), vix_hist, vix_cur, 0.0)
        ivp = float(_v.get("ivp_1yr", float("nan")))
except Exception as e:
    err = f"{type(e).__name__}: {e}"

if err:
    st.error(f"Live data unavailable — {err}")

res = CompressionEngine().signals(fut, atr14, ivp)
sess = res["sessions"]

if sess.empty:
    ui.alert_box(
        "No session profiles",
        "Futures 30m data could not be read, or carried no volume. Every reading on "
        "this page is built from volume-at-price, so nothing below would be meaningful.",
        level="danger", big=True,
    )
    st.stop()

# ── Row 1 — state banner ──────────────────────────────────────────────────────
_state = res["state"]
_col   = res["state_color"]
_days  = res["days_in_state"]
_pctl  = res["width_pctile"]

_sub = {
    "COMPRESSION":  f"Expansion due · no retest expected · resolves within {COMPRESS_MAX_DAYS} sessions",
    "ACCUMULATION": "Range-bound · breakouts here hunt stops across multiple nodes",
    "TREND":        "POC migrating · drift is the live risk, not expansion",
    "NEUTRAL":      "Failed every structural test · no state is being claimed",
    "UNKNOWN":      "Not classifiable — insufficient history, or a compression that never resolved",
}.get(_state, "")

st.markdown(
    f"<div style='background:{_col};border-radius:8px;padding:16px 20px;margin-bottom:10px;'>"
    f"<div style='font-size:26px;font-weight:800;color:#0b1220;letter-spacing:-0.5px;'>"
    f"{_state} &nbsp;·&nbsp; day {_days}</div>"
    f"<div style='font-size:13px;color:#0b1220;font-family:monospace;margin-top:4px;'>"
    f"VA width {res['va_width']:,.0f} pts"
    + (f" ({_pctl:.0f}th %ile)" if np.isfinite(_pctl) else "")
    + (" · contracting ▼" if res["contracting"] else "")
    + f" &nbsp;—&nbsp; {_sub}</div></div>",
    unsafe_allow_html=True,
)

# ── Row 2 — cards ─────────────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
with k1:
    ui.metric_card("VA WIDTH", f"{res['va_width']:,.0f}",
                   f"VAL {res['val']:,.0f} – VAH {res['vah']:,.0f}", "blue")
with k2:
    ui.metric_card("WIDTH %ILE",
                   f"{_pctl:.0f}" if np.isfinite(_pctl) else "—",
                   f"≤{COMPRESS_PCTILE:.0f} = compressed", border=_col)
with k3:
    ui.metric_card("DAYS IN STATE", f"{_days}",
                   f"POC {res['poc']:,.0f} · {res['hvn_count']} HVN", "default")
with k4:
    _ivp_col = "red" if np.isfinite(ivp) and ivp <= IVP_LOW else (
        "green" if np.isfinite(ivp) and ivp >= IVP_HIGH else "amber")
    ui.metric_card("IV PERCENTILE", f"{ivp:.0f}" if np.isfinite(ivp) else "—",
                   f"≤{IVP_LOW:.0f} thin · ≥{IVP_HIGH:.0f} rich", _ivp_col)

# ── Row 3 — the vega read (the point of the page) ─────────────────────────────
ui.section_header("Vega read", "State × IV percentile — the pairing that decides whether to sell")
ui.alert_box(f"{res['vega_label']} — {res['quadrant']}", res["vega_detail"],
             level=res["vega_level"], big=True)

ui.simple_technical(
    simple=("Compression says a big move is coming but not which way. If premium is also "
            "thin, you are taking maximum risk for minimum pay — that is the one "
            "combination worth stepping aside for."),
    technical=(f"COMPRESSION = VA width ≤ {COMPRESS_PCTILE:.0f}th percentile over "
               f"{LOOKBACK_SESSIONS} sessions AND narrowing {CONTRACT_SESSIONS} sessions running. "
               f"ACCUMULATION = session range ≤ {ACCUM_ATR_MULT}× ATR14, not contracting, ≥3 HVN. "
               f"A compression unresolved after {COMPRESS_MAX_DAYS} sessions is cleared to UNKNOWN."),
)

# ── Row 4 — width history ─────────────────────────────────────────────────────
ui.section_header("Value-area width", f"Last {LOOKBACK_SESSIONS} sessions · bar colour = state")

view = sess.tail(LOOKBACK_SESSIONS)
fig = go.Figure()
fig.add_trace(go.Bar(
    x=[str(d) for d in view.index],
    y=view["width"],
    marker_color=[STATE_COLORS.get(s, STATE_COLORS["UNKNOWN"]) for s in view["state"]],
    hovertemplate="%{x}<br>width %{y:.0f} pts<extra></extra>",
    name="VA width",
))
if view["width"].notna().any():
    thr = float(np.nanpercentile(view["width"].to_numpy(dtype=float), COMPRESS_PCTILE))
    fig.add_hline(y=thr, line_dash="dot", line_color="#f59e0b",
                  annotation_text=f"{COMPRESS_PCTILE:.0f}th %ile = {thr:,.0f}",
                  annotation_position="top left")
fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10),
                  showlegend=False, yaxis_title="points")
st.plotly_chart(fig, use_container_width=True)

# ── Row 5 — session table ─────────────────────────────────────────────────────
ui.section_header("Session detail", "Newest last")

tbl = pd.DataFrame({
    "Session":   [str(d) for d in view.index],
    "VAL":       [f"{v:,.0f}" for v in view["val"]],
    "POC":       [f"{v:,.0f}" for v in view["poc"]],
    "VAH":       [f"{v:,.0f}" for v in view["vah"]],
    "Width":     [f"{v:,.0f}" for v in view["width"]],
    "%ile":      [f"{v:.0f}" if np.isfinite(v) else "—" for v in view["width_pctile"]],
    "Range":     [f"{v:,.0f}" for v in view["range_pts"]],
    "HVN":       view["hvn_count"].astype(int).values,
    "Contr":     ["▼" if v else "" for v in view["contracting"]],
    "State":     view["state"].values,
})


def _state_css(v: str) -> str:
    return (f"background:{STATE_COLORS.get(v, STATE_COLORS['UNKNOWN'])};"
            f"color:#0b1220;font-weight:700;")


st.write(
    tbl.style.map(_state_css, subset=["State"])
    .set_properties(**{"font-family": "monospace", "font-size": "12.5px"})
    .hide(axis="index").to_html(),
    unsafe_allow_html=True,
)

# ── Row 6 — validation notice ─────────────────────────────────────────────────
ui.alert_box(
    "UNVALIDATED — no measured outcomes yet",
    f"Every threshold here is a placeholder chosen to make the rules computable, not a "
    f"value derived from data: the {COMPRESS_PCTILE:.0f}th-percentile compression cut, "
    f"{CONTRACT_SESSIONS}-session contraction, {ACCUM_ATR_MULT}× ATR range test, 3-HVN "
    f"accumulation floor, {COMPRESS_MAX_DAYS}-session staleness, and the "
    f"{IVP_LOW:.0f}/{IVP_HIGH:.0f} IV cuts. Sample n = {res['sample_n']}. "
    "Whether compression actually precedes expansion in Nifty has not been measured — "
    "run it through analytics/signal_lab.py before trusting the state to size a position.",
    level="warning", big=True,
)

# ── Diagnostics — stays in production (CLAUDE.md Lessons Rule 7) ──────────────
with st.expander("🔧 Diagnostics"):
    st.write({
        "fut_candles":       int(len(fut)),
        "fut_last_ts":       str(fut.index[-1]) if not fut.empty else "—",
        "fut_last_close":    float(fut["close"].iloc[-1]) if not fut.empty else 0.0,
        "fut_total_volume":  float(fut["volume"].sum()) if not fut.empty else 0.0,
        "spot":              spot,
        "spot_vs_fut_close": (float(spot) - float(fut["close"].iloc[-1])) if not fut.empty else 0.0,
        "sessions_profiled": int(len(sess)),
        "session_first":     str(sess.index[0]),
        "session_last":      str(sess.index[-1]),
        "atr14":             atr14,
        "daily_rows":        int(len(daily)),
        "ivp_1yr":           ivp,
        "state":             _state,
        "days_in_state":     _days,
    })
    st.caption(
        "fut_total_volume must be > 0 — a zero means the profile was built on the INDEX "
        "(no volume on Kite) and every value area on this page is meaningless. "
        "sessions_profiled should be ≥ 20 for the width percentile to be stable; fewer "
        "and early sessions read as UNKNOWN by design."
    )
    st.dataframe(sess.tail(40), use_container_width=True)
