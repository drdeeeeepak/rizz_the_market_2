# pages/17_EMA_Slope_Phases.py — EMA Slope Phase Engine
# 5-Phase 60-Min Nifty Trend Classification for Weekly IC Deployment

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import numpy as np
import datetime
import pytz

from page_utils import bootstrap_signals, show_page_header

st.set_page_config(page_title="P17 · EMA Slope Phases", layout="wide")
st_autorefresh(interval=3_600_000, key="p17")
st.title("Page 17 — EMA Slope Phase Engine")
st.caption(
    "60-Min Nifty · EMA-20 Slope · ATR-14 Dynamic Thresholds · "
    "5 Phases · Weekly IC Deployment Guide"
)

sig, spot_live, signals_ts = bootstrap_signals()
show_page_header(spot_live, signals_ts)

# ── Defaults if no pre-computed signal ───────────────────────────────────────
_DEFAULT_SIG = {
    "phase": 3, "phase_label": "Phase 3 — Flat / Neutral",
    "phase_deploy": "Non-directional — balanced Iron Condor deployment",
    "slope": 0.0, "k1": 0.0, "k2": 0.0,
    "atr_14": 0.0, "ema_20": 0.0,
    "streak_bars": 0, "phase_pct_20": {},
}
sig = sig or {}

# ── Market-hours detection ────────────────────────────────────────────────────
def _is_live() -> bool:
    n = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
    t = n.hour * 60 + n.minute
    return n.weekday() < 5 and 9 * 60 + 15 <= t <= 15 * 60 + 30


# ── Live engine run ───────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_and_compute() -> tuple[pd.DataFrame, dict]:
    """Fetch 1H data and run the EMA slope engine. Cached for 1 hour."""
    from data.live_fetcher import get_nifty_1h_ema_slope
    from analytics.ema_slope_phases import EMASlopePhasesEngine

    df_raw = get_nifty_1h_ema_slope()
    if df_raw.empty:
        return pd.DataFrame(), {}

    engine = EMASlopePhasesEngine()
    df_out = engine.compute(df_raw)
    sigs   = engine.signals(df_raw)
    return df_out, sigs


df, live_sigs = _fetch_and_compute()

# Merge live signals into display dict (live takes precedence)
display = {**_DEFAULT_SIG, **{k.replace("esp_", ""): v for k, v in sig.items() if k.startswith("esp_")}, **live_sigs}

# ── Phase colour + label helpers ──────────────────────────────────────────────
from analytics.ema_slope_phases import PHASE_COLORS, PHASE_LABELS, PHASE_DEPLOYMENT

_PHASE_BG = {
    1: "rgba(0,200,83,0.15)",
    2: "rgba(105,240,174,0.15)",
    3: "rgba(255,214,0,0.15)",
    4: "rgba(255,109,0,0.15)",
    5: "rgba(213,0,0,0.15)",
}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 0 — Current Phase Banner
# ══════════════════════════════════════════════════════════════════════════════
current_phase  = int(display.get("phase", 3))
phase_label    = display.get("phase_label",  PHASE_LABELS.get(current_phase, "Unknown"))
phase_deploy   = display.get("phase_deploy", PHASE_DEPLOYMENT.get(current_phase, ""))
phase_color    = PHASE_COLORS.get(current_phase, "#FFD600")
streak_bars    = int(display.get("streak_bars", 0))

st.markdown(
    f"""
    <div style="
        background:{_PHASE_BG.get(current_phase,'rgba(255,214,0,0.15)')};
        border-left:6px solid {phase_color};
        border-radius:6px;
        padding:14px 18px;
        margin-bottom:12px;
    ">
        <span style="font-size:1.5rem;font-weight:700;color:{phase_color};">
            {phase_label}
        </span><br/>
        <span style="font-size:1.0rem;color:#ccc;">{phase_deploy}</span>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Streak + data freshness note ──────────────────────────────────────────────
col_s1, col_s2 = st.columns([1, 3])
with col_s1:
    st.metric("Streak (bars)", f"{streak_bars}", help="Consecutive 60-min bars in current phase")
with col_s2:
    if df.empty:
        st.warning("No 1H data available — check Kite connection.")
    else:
        valid_df = df.dropna(subset=["Slope_Phase"])
        if not valid_df.empty:
            last_ts = valid_df.index[-1]
            st.caption(f"Last bar: **{last_ts.strftime('%d %b %Y  %H:%M')} IST** — {len(valid_df)} confirmed candles")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Current Metrics
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Current Readings")

slope   = display.get("slope", 0.0)
k1      = display.get("k1", 0.0)
k2      = display.get("k2", 0.0)
atr_14  = display.get("atr_14", 0.0)
ema_20  = display.get("ema_20", 0.0)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("EMA-20", f"{ema_20:,.2f}",  help="Current value of 20-period EMA on 60-min close")
c2.metric("Raw Slope", f"{slope:+.4f}", help="EMA(t) − EMA(t-1)")
c3.metric("K1 (significance)", f"{k1:.4f}", help=f"m1 × ATR-14  (m1 = {display.get('m1', 0.03):.2f} default 0.03)")
c4.metric("K2 (acceleration)", f"{k2:.4f}", help=f"m2 × ATR-14  (m2 = {display.get('m2', 0.10):.2f} default 0.10)")
c5.metric("ATR-14 (1H)", f"{atr_14:.2f}", help="14-period Average True Range on 60-min bars")

# Threshold distance visualiser
if k1 > 0 and k2 > 0:
    slope_abs = abs(slope)
    pct_of_k1 = slope_abs / k1 * 100 if k1 else 0
    pct_of_k2 = slope_abs / k2 * 100 if k2 else 0
    direction  = "Bullish" if slope >= 0 else "Bearish"
    st.caption(
        f"Current slope is **{direction}** at "
        f"**{pct_of_k1:.0f}%** of K1 and **{pct_of_k2:.0f}%** of K2"
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Phase Distribution (last 20 bars)
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Phase Distribution — Last 20 Bars")

phase_pct_20 = display.get("phase_pct_20", {})

if phase_pct_20:
    bars_data = []
    for p in [1, 2, 3, 4, 5]:
        bars_data.append({
            "phase": PHASE_LABELS.get(p, f"Phase {p}"),
            "pct":   phase_pct_20.get(p, 0),
            "color": PHASE_COLORS.get(p, "#888"),
        })

    fig_dist = go.Figure()
    for row in bars_data:
        fig_dist.add_trace(go.Bar(
            x=[row["pct"]],
            y=[row["phase"]],
            orientation="h",
            marker_color=row["color"],
            text=[f"{row['pct']}%"],
            textposition="outside",
            showlegend=False,
            name=row["phase"],
        ))
    fig_dist.update_layout(
        height=220,
        margin=dict(l=10, r=60, t=10, b=10),
        xaxis=dict(range=[0, 100], title="% of last 20 bars", showgrid=True),
        yaxis=dict(autorange="reversed"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ddd"),
        barmode="overlay",
    )
    st.plotly_chart(fig_dist, use_container_width=True)
else:
    st.caption("Phase distribution unavailable — run engine to populate.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Phase History Chart (last 120 bars ≈ 20 sessions)
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Phase History — Last 120 Bars (≈ 20 Sessions)")

if not df.empty and "Slope_Phase" in df.columns:
    from config import EMA_SLOPE_DISPLAY_BARS

    plot_df = df.dropna(subset=["Slope_Phase"]).tail(EMA_SLOPE_DISPLAY_BARS).copy()
    plot_df["phase_int"] = plot_df["Slope_Phase"].astype(int)

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.50, 0.25, 0.25],
        vertical_spacing=0.04,
        subplot_titles=("Nifty Close + EMA-20", "Raw Slope vs K1/K2 Bands", "Phase"),
    )

    # ── Row 1: Close + EMA-20, background coloured by phase ──────────────────
    # Phase background shapes
    phase_series = plot_df["phase_int"]
    x_idx        = plot_df.index

    prev_phase = None
    seg_start  = None
    for i, (ts, ph) in enumerate(zip(x_idx, phase_series)):
        if ph != prev_phase:
            if prev_phase is not None:
                fig.add_vrect(
                    x0=seg_start, x1=ts,
                    fillcolor=_PHASE_BG.get(prev_phase, "rgba(128,128,128,0.1)"),
                    line_width=0, row=1, col=1,
                )
            seg_start  = ts
            prev_phase = ph
    if prev_phase is not None and seg_start is not None:
        fig.add_vrect(
            x0=seg_start, x1=x_idx[-1],
            fillcolor=_PHASE_BG.get(prev_phase, "rgba(128,128,128,0.1)"),
            line_width=0, row=1, col=1,
        )

    fig.add_trace(
        go.Scatter(
            x=plot_df.index, y=plot_df["close"],
            mode="lines", name="Close",
            line=dict(color="#90CAF9", width=1),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=plot_df.index, y=plot_df["ema_20"],
            mode="lines", name="EMA-20",
            line=dict(color="#FFD600", width=2),
        ),
        row=1, col=1,
    )

    # ── Row 2: Slope vs ±K1/K2 bands ─────────────────────────────────────────
    fig.add_trace(
        go.Scatter(
            x=plot_df.index, y=plot_df["k2"],
            mode="lines", name="+K2",
            line=dict(color="#00C853", width=1, dash="dot"),
            showlegend=True,
        ),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=plot_df.index, y=plot_df["k1"],
            mode="lines", name="+K1",
            line=dict(color="#69F0AE", width=1, dash="dash"),
            showlegend=True,
        ),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=plot_df.index, y=-plot_df["k1"],
            mode="lines", name="−K1",
            line=dict(color="#FF6D00", width=1, dash="dash"),
            showlegend=True,
        ),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=plot_df.index, y=-plot_df["k2"],
            mode="lines", name="−K2",
            line=dict(color="#D50000", width=1, dash="dot"),
            showlegend=True,
        ),
        row=2, col=1,
    )
    # Slope bars coloured by phase
    slope_colors = plot_df["phase_int"].map(PHASE_COLORS).fillna("#888")
    fig.add_trace(
        go.Bar(
            x=plot_df.index,
            y=plot_df["ema_slope"],
            marker_color=slope_colors,
            name="Slope",
            showlegend=False,
        ),
        row=2, col=1,
    )
    fig.add_hline(y=0, line_width=1, line_color="#555", row=2, col=1)

    # ── Row 3: Phase integer timeline ─────────────────────────────────────────
    fig.add_trace(
        go.Scatter(
            x=plot_df.index,
            y=plot_df["phase_int"],
            mode="markers",
            marker=dict(
                color=plot_df["phase_int"].map(PHASE_COLORS),
                size=6,
                symbol="circle",
            ),
            name="Phase",
            showlegend=False,
        ),
        row=3, col=1,
    )
    fig.update_yaxes(
        tickvals=[1, 2, 3, 4, 5],
        ticktext=["1 Str.Bull", "2 Mild Bull", "3 Flat", "4 Mild Bear", "5 Str.Bear"],
        row=3, col=1,
    )

    fig.update_layout(
        height=680,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(20,20,20,0.5)",
        font=dict(color="#ddd"),
        legend=dict(orientation="h", y=1.02, x=0),
        xaxis3=dict(showgrid=True, gridcolor="#333"),
    )
    for row_n in [1, 2, 3]:
        fig.update_yaxes(gridcolor="#333", row=row_n, col=1)
        fig.update_xaxes(gridcolor="#333", row=row_n, col=1)

    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No computed data to display. The engine requires a valid Kite session.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Phase Reference Table
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Phase Reference")

_ref_rows = []
for p in [1, 2, 3, 4, 5]:
    if p == 1:
        condition = "Slope > K2"
    elif p == 2:
        condition = "K1 < Slope ≤ K2"
    elif p == 3:
        condition = "−K1 ≤ Slope ≤ K1"
    elif p == 4:
        condition = "−K2 ≤ Slope < −K1"
    else:
        condition = "Slope < −K2"
    _ref_rows.append({
        "Phase": p,
        "Label": PHASE_LABELS[p],
        "Condition": condition,
        "Deployment Guidance": PHASE_DEPLOYMENT[p],
    })

ref_df = pd.DataFrame(_ref_rows).set_index("Phase")

# Highlight current phase
def _highlight_phase(row):
    if row.name == current_phase:
        return [f"background-color:{PHASE_COLORS.get(current_phase,'#FFD600')}22;font-weight:bold"] * len(row)
    return [""] * len(row)

st.dataframe(ref_df.style.apply(_highlight_phase, axis=1), use_container_width=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Tuning Guide
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("Threshold Tuning Guide", expanded=False):
    from config import EMA_SLOPE_M1, EMA_SLOPE_M2

    st.markdown(f"""
**Current defaults:** `m1 = {EMA_SLOPE_M1}`  |  `m2 = {EMA_SLOPE_M2}`

| Observation | Action | Effect |
|---|---|---|
| Phase 3 (Flat) is over-classifying mild trends as neutral | Lower `m1` from `0.03` → `0.02` | Tightens the neutral zone — K1 shrinks, mild slopes exit Phase 3 sooner |
| Phase 1 / Phase 5 transitions feel late on explosive moves | Lower `m2` from `0.10` → `0.08` | K2 shrinks — strong moves classify as Phase 1/5 earlier |
| Too many Phase 1/5 whipsaws on normal volatility | Raise `m2` from `0.10` → `0.12` | K2 expands — requires larger slope to reach strong phases |

**Where to change:** `config.py` → `EMA_SLOPE_M1` and `EMA_SLOPE_M2`

**Formula recap:**
```
K1 = m1 × ATR_14   (significance threshold)
K2 = m2 × ATR_14   (acceleration threshold)
```
Both thresholds adapt to current volatility — wider in high-VIX sessions,
narrower in consolidating markets. No manual re-tuning needed for regime shifts.
    """)
