# pages/17_EMA_Slope_Phases.py — EMA Slope Phase Engine
# Chart-first: 60-Min Nifty candlestick + EMA-20 + colour-coded phase bands

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import numpy as np
import datetime
import pytz

from page_utils import bootstrap_signals, show_page_header
from analytics.ema_slope_phases import (
    PHASE_COLORS, PHASE_LABELS, PHASE_DEPLOYMENT,
)

st.set_page_config(page_title="P17 · EMA Slope Phases", layout="wide")
st_autorefresh(interval=3_600_000, key="p17")

sig, spot_live, signals_ts = bootstrap_signals()
show_page_header(spot_live, signals_ts)
sig = sig or {}

# ── Phase background fill colours (semi-transparent) ─────────────────────────
_PHASE_FILL = {
    1: "rgba(0,200,83,0.18)",
    2: "rgba(105,240,174,0.13)",
    3: "rgba(255,214,0,0.12)",
    4: "rgba(255,109,0,0.15)",
    5: "rgba(213,0,0,0.18)",
}

# ── Fetch + compute (cached 1 hour) ──────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _load() -> tuple[pd.DataFrame, dict]:
    from data.live_fetcher import get_nifty_1h_ema_slope
    from analytics.ema_slope_phases import EMASlopePhasesEngine
    df_raw = get_nifty_1h_ema_slope()
    if df_raw.empty:
        return pd.DataFrame(), {}
    engine = EMASlopePhasesEngine()
    df_out = engine.compute(df_raw)
    sigs   = engine.signals(df_raw)
    return df_out, sigs


with st.spinner("Loading 60-min Nifty data…"):
    df_full, live_sigs = _load()

# ── Merge signals ─────────────────────────────────────────────────────────────
display = {
    "phase": 3, "phase_label": "Phase 3 — Flat / Neutral",
    "phase_deploy": "Non-directional — balanced Iron Condor deployment",
    "slope": 0.0, "k1": 0.0, "k2": 0.0, "atr_14": 0.0, "ema_20": 0.0,
    "streak_bars": 0, "phase_pct_20": {},
    **live_sigs,
}

current_phase = int(display["phase"])
phase_color   = PHASE_COLORS.get(current_phase, "#FFD600")
streak_bars   = int(display["streak_bars"])

# ══════════════════════════════════════════════════════════════════════════════
# HEADER ROW — phase badge + key scalars
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(
    f"""<div style="
        background:{_PHASE_FILL.get(current_phase,'rgba(255,214,0,0.12)')};
        border-left:6px solid {phase_color};
        border-radius:6px; padding:12px 18px; margin-bottom:8px;">
        <span style="font-size:1.55rem;font-weight:700;color:{phase_color};">
            {display['phase_label']}
        </span><br/>
        <span style="font-size:0.95rem;color:#ccc;">{display['phase_deploy']}</span>
    </div>""",
    unsafe_allow_html=True,
)

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Streak", f"{streak_bars} bars",    help="Consecutive 60-min bars in current phase")
m2.metric("EMA-20",  f"{display['ema_20']:,.2f}")
m3.metric("Slope",   f"{display['slope']:+.3f}", help="EMA(t) − EMA(t-1)")
m4.metric("K1",      f"{display['k1']:.3f}",    help="Significance threshold = m1 × ATR-14")
m5.metric("K2",      f"{display['k2']:.3f}",    help="Acceleration threshold = m2 × ATR-14")
m6.metric("ATR-14",  f"{display['atr_14']:.1f}", help="14-period ATR on 60-min bars")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# MAIN CHART
# ══════════════════════════════════════════════════════════════════════════════
if df_full.empty or "Slope_Phase" not in df_full.columns:
    st.warning("No 60-min Nifty data — check Kite connection and re-login if needed.")
    st.stop()

# Use last 80 bars ≈ 2+ weeks of 60-min sessions
plot_df = df_full.dropna(subset=["Slope_Phase"]).tail(80).copy()
plot_df["phase_int"] = plot_df["Slope_Phase"].astype(int)

last_ts = plot_df.index[-1]
st.caption(
    f"Showing last **{len(plot_df)} hourly bars** · "
    f"Latest: **{last_ts.strftime('%d %b %Y  %H:%M')} IST**"
)

# ── Build 2-row subplot ───────────────────────────────────────────────────────
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    row_heights=[0.72, 0.28],
    vertical_spacing=0.03,
    subplot_titles=["Nifty 60-Min  ·  EMA-20  ·  Phase Bands", "EMA Slope  ·  K1 / K2 Thresholds"],
)

# ── Colour-coded phase background bands (both rows) ──────────────────────────
x_idx      = plot_df.index.tolist()
phases     = plot_df["phase_int"].tolist()
seg_start  = x_idx[0]
seg_phase  = phases[0]

# Collect segments
segments = []
for i in range(1, len(x_idx)):
    if phases[i] != seg_phase:
        segments.append((seg_start, x_idx[i], seg_phase))
        seg_start = x_idx[i]
        seg_phase = phases[i]
segments.append((seg_start, x_idx[-1], seg_phase))

for x0, x1, ph in segments:
    fill = _PHASE_FILL.get(ph, "rgba(128,128,128,0.1)")
    # Row 1 (price chart)
    fig.add_vrect(x0=x0, x1=x1, fillcolor=fill, line_width=0, row=1, col=1)
    # Row 2 (slope chart)
    fig.add_vrect(x0=x0, x1=x1, fillcolor=fill, line_width=0, row=2, col=1)

# ── Candlestick (Row 1) ───────────────────────────────────────────────────────
fig.add_trace(
    go.Candlestick(
        x=plot_df.index,
        open=plot_df["open"],
        high=plot_df["high"],
        low=plot_df["low"],
        close=plot_df["close"],
        name="Nifty",
        increasing=dict(line=dict(color="#26a69a", width=1), fillcolor="#26a69a"),
        decreasing=dict(line=dict(color="#ef5350", width=1), fillcolor="#ef5350"),
        whiskerwidth=0.3,
    ),
    row=1, col=1,
)

# ── EMA-20 line (Row 1) ───────────────────────────────────────────────────────
fig.add_trace(
    go.Scatter(
        x=plot_df.index,
        y=plot_df["ema_20"],
        mode="lines",
        name="EMA-20",
        line=dict(color="#1565C0", width=2.5),
    ),
    row=1, col=1,
)

# ── Phase label annotations at top of each segment (Row 1) ───────────────────
_SHORT_LABEL = {1: "P1 ▲▲", 2: "P2 ▲", 3: "P3 —", 4: "P4 ▼", 5: "P5 ▼▼"}
_yref_domain_map = {1: "y domain", 2: "y2 domain"}  # subplot y domains

for x0, x1, ph in segments:
    mid_idx = x0 + (x1 - x0) / 2 if hasattr(x0, '__sub__') else x0
    try:
        mid_idx = pd.Timestamp(x0) + (pd.Timestamp(x1) - pd.Timestamp(x0)) / 2
    except Exception:
        mid_idx = x0
    fig.add_annotation(
        x=mid_idx,
        y=1.0,
        yref="y domain",
        xref="x",
        text=f"<b>{_SHORT_LABEL.get(ph,'')}</b>",
        showarrow=False,
        font=dict(color="#ffffff", size=10),
        bgcolor=PHASE_COLORS.get(ph, "#888"),
        borderpad=3,
        row=1, col=1,
    )

# ── Zero line + K1/K2 bands fill (Row 2) ─────────────────────────────────────
# Filled band between -K1 and +K1 (neutral zone)
fig.add_trace(
    go.Scatter(
        x=list(plot_df.index) + list(plot_df.index[::-1]),
        y=list(plot_df["k1"]) + list((-plot_df["k1"])[::-1]),
        fill="toself",
        fillcolor="rgba(255,214,0,0.20)",
        line=dict(width=0),
        name="Neutral zone (±K1)",
        showlegend=True,
        hoverinfo="skip",
    ),
    row=2, col=1,
)

# K2 upper band fill (between K1 and K2)
fig.add_trace(
    go.Scatter(
        x=list(plot_df.index) + list(plot_df.index[::-1]),
        y=list(plot_df["k2"]) + list(plot_df["k1"][::-1]),
        fill="toself",
        fillcolor="rgba(0,200,83,0.14)",
        line=dict(width=0),
        name="Mild bull zone (K1–K2)",
        showlegend=False,
        hoverinfo="skip",
    ),
    row=2, col=1,
)

# K2 lower band fill (between -K1 and -K2)
fig.add_trace(
    go.Scatter(
        x=list(plot_df.index) + list(plot_df.index[::-1]),
        y=list(-plot_df["k1"]) + list((-plot_df["k2"])[::-1]),
        fill="toself",
        fillcolor="rgba(213,0,0,0.14)",
        line=dict(width=0),
        name="Mild bear zone (−K1 to −K2)",
        showlegend=False,
        hoverinfo="skip",
    ),
    row=2, col=1,
)

# Threshold lines
for col_name, col_color, dash, lbl in [
    ("k2",  "#2E7D32", "dot",  "+K2"),
    ("k1",  "#43A047", "dash", "+K1"),
]:
    fig.add_trace(
        go.Scatter(
            x=plot_df.index, y=plot_df[col_name],
            mode="lines", name=lbl,
            line=dict(color=col_color, width=1, dash=dash),
        ),
        row=2, col=1,
    )
for col_name, col_color, dash, lbl in [
    ("k1",  "#FF6D00", "dash", "−K1"),
    ("k2",  "#D50000", "dot",  "−K2"),
]:
    fig.add_trace(
        go.Scatter(
            x=plot_df.index, y=-plot_df[col_name],
            mode="lines", name=lbl,
            line=dict(color=col_color, width=1, dash=dash),
        ),
        row=2, col=1,
    )

# Slope bars coloured by phase
slope_bar_colors = [PHASE_COLORS.get(ph, "#888") for ph in plot_df["phase_int"]]
fig.add_trace(
    go.Bar(
        x=plot_df.index,
        y=plot_df["ema_slope"],
        marker_color=slope_bar_colors,
        name="EMA Slope",
        opacity=0.85,
    ),
    row=2, col=1,
)
fig.add_hline(y=0, line_width=1, line_color="#bbb", row=2, col=1)

# ── Layout ────────────────────────────────────────────────────────────────────
fig.update_layout(
    height=620,
    margin=dict(l=10, r=10, t=50, b=10),
    paper_bgcolor="white",
    plot_bgcolor="white",
    font=dict(color="#222", size=12),
    legend=dict(
        orientation="h", x=0, y=-0.06,
        bgcolor="rgba(255,255,255,0.9)", font=dict(size=11),
    ),
    xaxis_rangeslider_visible=False,
    hovermode="x unified",
)

for row_n in [1, 2]:
    fig.update_yaxes(gridcolor="#eeeeee", zeroline=False, row=row_n, col=1)
    fig.update_xaxes(gridcolor="#eeeeee", row=row_n, col=1)

# Zoom slope panel so K1/K2 threshold lines are clearly visible
_k2_max = float(plot_df["k2"].max()) if not plot_df["k2"].empty else 1.0
fig.update_yaxes(range=[-_k2_max * 2.2, _k2_max * 2.2], row=2, col=1)

fig.update_xaxes(
    rangebreaks=[
        dict(bounds=["sat", "mon"]),               # skip weekends
        dict(bounds=[15.5, 9.25], pattern="hour"), # skip overnight gap
    ],
    row=2, col=1,
)

st.plotly_chart(fig, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# PHASE LEGEND ROW
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("**Phase legend:**", unsafe_allow_html=False)
legend_cols = st.columns(5)
for i, p in enumerate([1, 2, 3, 4, 5]):
    c = PHASE_COLORS[p]
    highlight = "font-weight:700;border:1px solid " + c if p == current_phase else "opacity:0.7"
    legend_cols[i].markdown(
        f"<div style='background:{_PHASE_FILL[p]};border-left:4px solid {c};"
        f"border-radius:4px;padding:6px 10px;{highlight}'>"
        f"<span style='color:{c};font-size:0.9rem;'>{PHASE_LABELS[p]}</span></div>",
        unsafe_allow_html=True,
    )

# ══════════════════════════════════════════════════════════════════════════════
# TUNING GUIDE
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("Threshold Tuning Guide", expanded=False):
    from config import EMA_SLOPE_M1, EMA_SLOPE_M2
    st.markdown(f"""
**Current:** `m1 = {EMA_SLOPE_M1}` (K1 multiplier)  ·  `m2 = {EMA_SLOPE_M2}` (K2 multiplier)

| Observation | Fix | Effect |
|---|---|---|
| Phase 3 catching too many mild trends as "Flat" | Lower `m1`: `0.03` → `0.02` | Tightens neutral band — mild slopes exit Phase 3 sooner |
| Phase 1/5 transitions feel late on explosive moves | Lower `m2`: `0.10` → `0.08` | K2 shrinks — strong moves hit Phase 1/5 earlier |
| Too many Phase 1/5 whipsaws | Raise `m2`: `0.10` → `0.12` | K2 widens — only genuine acceleration qualifies |

Edit `config.py` → `EMA_SLOPE_M1` / `EMA_SLOPE_M2`.
Both thresholds auto-scale with ATR — no re-tuning needed across volatility regimes.
    """)
