# pages/17_EMA_Slope_Phases.py — EMA Slope Phase Engine
# 60-Min + 4-Hour Nifty candlestick charts with colour-coded phase ribbon

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import numpy as np

from page_utils import bootstrap_signals, show_page_header
from analytics.ema_slope_phases import (
    PHASE_COLORS, PHASE_LABELS, PHASE_DEPLOYMENT,
)

st.set_page_config(page_title="P17 · EMA Slope Phases", layout="wide")
st_autorefresh(interval=3_600_000, key="p17")

sig, spot_live, signals_ts = bootstrap_signals()
show_page_header(spot_live, signals_ts)
sig = sig or {}

_PHASE_FILL = {
    1: "rgba(0,200,83,0.18)",
    2: "rgba(105,240,174,0.13)",
    3: "rgba(255,214,0,0.12)",
    4: "rgba(255,109,0,0.15)",
    5: "rgba(213,0,0,0.18)",
}
_SHORT_LABEL = {1: "P1 ▲▲", 2: "P2 ▲", 3: "P3 —", 4: "P4 ▼", 5: "P5 ▼▼"}


# ── Fetch + compute both timeframes (cached 1 hour) ───────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _load():
    from data.live_fetcher import get_nifty_1h_ema_slope
    from analytics.ema_slope_phases import EMASlopePhasesEngine

    df_raw = get_nifty_1h_ema_slope()
    if df_raw.empty:
        return pd.DataFrame(), {}, pd.DataFrame(), {}

    engine = EMASlopePhasesEngine()

    # 60-min phases
    df_1h  = engine.compute(df_raw)
    sig_1h = engine.signals(df_raw)

    # Resample to 4H then compute phases on the resampled candles
    df_4h_raw = (
        df_raw
        .resample("4h")
        .agg({"open": "first", "high": "max", "low": "min",
              "close": "last",  "volume": "sum"})
        .dropna(subset=["close"])
    )
    if not df_4h_raw.empty:
        df_4h  = engine.compute(df_4h_raw)
        sig_4h = engine.signals(df_4h_raw)
    else:
        df_4h, sig_4h = pd.DataFrame(), {}

    return df_1h, sig_1h, df_4h, sig_4h


with st.spinner("Loading 60-min + 4H Nifty data…"):
    df_1h_full, live_sigs_1h, df_4h_full, live_sigs_4h = _load()


# ── Current phase banner (60-min is the primary signal) ──────────────────────
_DEF = {
    "phase": 3, "phase_label": "Phase 3 — Flat / Neutral",
    "phase_deploy": "Non-directional — balanced Iron Condor deployment",
    "slope": 0.0, "k1": 0.0, "k2": 0.0, "atr_14": 0.0, "ema_20": 0.0,
    "streak_bars": 0,
}
d1h = {**_DEF, **live_sigs_1h}
cur_phase = int(d1h["phase"])
cur_color = PHASE_COLORS.get(cur_phase, "#FFD600")

st.markdown(
    f"""<div style="background:{_PHASE_FILL.get(cur_phase,'rgba(255,214,0,0.12)')};
        border-left:6px solid {cur_color};border-radius:6px;
        padding:12px 18px;margin-bottom:8px;">
        <span style="font-size:1.55rem;font-weight:700;color:{cur_color};">
            {d1h['phase_label']}
        </span><br/>
        <span style="font-size:0.95rem;color:#555;">{d1h['phase_deploy']}</span>
    </div>""",
    unsafe_allow_html=True,
)
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Streak (1H)", f"{d1h['streak_bars']} bars")
c2.metric("EMA-20",  f"{d1h['ema_20']:,.2f}")
c3.metric("Slope",   f"{d1h['slope']:+.3f}")
c4.metric("K1",      f"{d1h['k1']:.3f}")
c5.metric("K2",      f"{d1h['k2']:.3f}")
c6.metric("ATR-14",  f"{d1h['atr_14']:.1f}")

st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# Shared chart builder — works for any computed OHLCV+phase DataFrame
# ══════════════════════════════════════════════════════════════════════════════
def _build_chart(df_in: pd.DataFrame, n_display: int, chart_title: str):
    """Return a 2-panel Plotly figure (price + slope) or None if data too short."""
    if df_in.empty or "Slope_Phase" not in df_in.columns:
        return None
    plot_df = df_in.dropna(subset=["Slope_Phase"]).tail(n_display).copy()
    if len(plot_df) < 5:
        return None

    plot_df["phase_int"] = plot_df["Slope_Phase"].astype(int)
    n    = len(plot_df)
    xp   = list(range(n))
    phs  = plot_df["phase_int"].tolist()
    tsi  = plot_df.index.tolist()
    htxt = [ts.strftime("%d %b %H:%M") for ts in tsi]

    # One x-tick per trading day (first bar of that date)
    seen: dict = {}
    for i, ts in enumerate(tsi):
        if ts.date() not in seen:
            seen[ts.date()] = i
    tv = list(seen.values())
    tl = [tsi[i].strftime("%d %b") for i in tv]

    # Phase segments
    segs, s0, s_ph = [], 0, phs[0]
    for i in range(1, n):
        if phs[i] != s_ph:
            segs.append((s0, i - 1, s_ph))
            s0, s_ph = i, phs[i]
    segs.append((s0, n - 1, s_ph))

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.72, 0.28], vertical_spacing=0.01,
        subplot_titles=[
            f"Nifty {chart_title}  ·  EMA-20  ·  Phase Ribbon",
            f"EMA Slope  ·  K1 / K2  ({chart_title})",
        ],
    )

    # ── Phase ribbon — gapless, Row 1 only ───────────────────────────────────
    for p0, p1, ph in segs:
        fig.add_shape(
            type="rect",
            x0=p0 - 0.5, x1=p1 + 0.5, y0=0, y1=1,
            xref="x", yref="y domain",
            fillcolor=_PHASE_FILL.get(ph, "rgba(128,128,128,0.1)"),
            line_width=0, layer="below",
            row=1, col=1,
        )

    # ── Candlestick ───────────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=xp, open=plot_df["open"], high=plot_df["high"],
        low=plot_df["low"], close=plot_df["close"],
        text=htxt, name="Nifty",
        increasing=dict(line=dict(color="#26a69a", width=1), fillcolor="#26a69a"),
        decreasing=dict(line=dict(color="#ef5350", width=1), fillcolor="#ef5350"),
        whiskerwidth=0.3,
    ), row=1, col=1)

    # ── EMA-20 ────────────────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=xp, y=plot_df["ema_20"],
        mode="lines", name="EMA-20",
        line=dict(color="#1565C0", width=2.5),
    ), row=1, col=1)

    # ── Phase label pills (Row 1) ─────────────────────────────────────────────
    for p0, p1, ph in segs:
        fig.add_annotation(
            x=(p0 + p1) / 2, y=1.0,
            yref="y domain", xref="x",
            text=f"<b>{_SHORT_LABEL.get(ph,'')}</b>",
            showarrow=False,
            font=dict(color="#ffffff", size=10),
            bgcolor=PHASE_COLORS.get(ph, "#888"),
            borderpad=3,
            row=1, col=1,
        )

    # ── K1/K2 band fills (Row 2) ──────────────────────────────────────────────
    xr = xp[::-1]
    k1f = list(plot_df["k1"]); k1r = list(plot_df["k1"][::-1])
    k2f = list(plot_df["k2"]); k2r = list(plot_df["k2"][::-1])

    fig.add_trace(go.Scatter(
        x=xp + xr, y=k1f + [-v for v in k1r],
        fill="toself", fillcolor="rgba(255,214,0,0.20)",
        line=dict(width=0), name="±K1 neutral zone",
        showlegend=True, hoverinfo="skip",
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=xp + xr, y=k2f + k1r,
        fill="toself", fillcolor="rgba(0,200,83,0.14)",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=xp + xr, y=[-v for v in k1f] + [-v for v in k2r],
        fill="toself", fillcolor="rgba(213,0,0,0.14)",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ), row=2, col=1)

    for cname, color, dash, lbl, sign in [
        ("k2", "#2E7D32", "dot",  "+K2",  1),
        ("k1", "#43A047", "dash", "+K1",  1),
        ("k1", "#FF6D00", "dash", "−K1", -1),
        ("k2", "#D50000", "dot",  "−K2", -1),
    ]:
        fig.add_trace(go.Scatter(
            x=xp, y=sign * plot_df[cname],
            mode="lines", name=lbl,
            line=dict(color=color, width=1.5, dash=dash),
        ), row=2, col=1)

    slope_colors = [PHASE_COLORS.get(ph, "#888") for ph in phs]
    fig.add_trace(go.Bar(
        x=xp, y=plot_df["ema_slope"],
        marker_color=slope_colors,
        text=htxt, name="Slope", opacity=0.85,
    ), row=2, col=1)
    fig.add_hline(y=0, line_width=1, line_color="#bbb", row=2, col=1)

    # ── Layout ────────────────────────────────────────────────────────────────
    k2_max = float(plot_df["k2"].max()) if not plot_df["k2"].empty else 1.0
    fig.update_layout(
        height=600,
        margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor="white", plot_bgcolor="white",
        font=dict(color="#222", size=12),
        legend=dict(orientation="h", x=0, y=-0.06,
                    bgcolor="rgba(255,255,255,0.9)", font=dict(size=11)),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )
    for row_n in [1, 2]:
        fig.update_yaxes(gridcolor="#eeeeee", zeroline=False, row=row_n, col=1)
        fig.update_xaxes(tickvals=tv, ticktext=tl, gridcolor="#eeeeee",
                         range=[-0.5, n - 0.5], row=row_n, col=1)
    fig.update_yaxes(range=[-k2_max * 2.2, k2_max * 2.2], row=2, col=1)
    return fig


def _phase_legend(active_phase: int) -> None:
    cols = st.columns(5)
    for i, p in enumerate([1, 2, 3, 4, 5]):
        c  = PHASE_COLORS[p]
        hl = f"font-weight:700;border:1px solid {c}" if p == active_phase else "opacity:0.7"
        cols[i].markdown(
            f"<div style='background:{_PHASE_FILL[p]};border-left:4px solid {c};"
            f"border-radius:4px;padding:6px 10px;{hl}'>"
            f"<span style='color:{c};font-size:0.9rem;'>{PHASE_LABELS[p]}</span></div>",
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# 60-MIN CHART — 1 month (≈ 120 bars)
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("60-Minute Chart — 1 Month")

if df_1h_full.empty or "Slope_Phase" not in df_1h_full.columns:
    st.warning("No 60-min data — check Kite connection.")
else:
    v1h = df_1h_full.dropna(subset=["Slope_Phase"])
    if not v1h.empty:
        st.caption(
            f"Latest bar: **{v1h.index[-1].strftime('%d %b %Y  %H:%M')} IST** "
            f"· {len(v1h)} confirmed candles"
        )
    fig_1h = _build_chart(df_1h_full, 120, "60-Min")
    if fig_1h:
        st.plotly_chart(fig_1h, use_container_width=True)
    else:
        st.info("Insufficient 60-min data to render chart.")

st.markdown("**Phase legend:**")
_phase_legend(cur_phase)

st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# 4-HOUR CHART — 1 month (≈ 40 bars)
# Resampled from 60-min OHLCV; same EMA-20 slope + ATR-14 phase engine
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("4-Hour Chart — 1 Month")

d4h = {**_DEF, **live_sigs_4h}
cur_phase_4h = int(d4h["phase"])
cur_color_4h = PHASE_COLORS.get(cur_phase_4h, "#FFD600")

st.markdown(
    f"""<div style="background:{_PHASE_FILL.get(cur_phase_4h,'rgba(255,214,0,0.12)')};
        border-left:6px solid {cur_color_4h};border-radius:6px;
        padding:10px 18px;margin-bottom:8px;">
        <span style="font-size:1.2rem;font-weight:700;color:{cur_color_4h};">
            4H · {d4h['phase_label']}
        </span><br/>
        <span style="font-size:0.9rem;color:#555;">{d4h['phase_deploy']}</span>
    </div>""",
    unsafe_allow_html=True,
)
n1, n2, n3, n4, n5, n6 = st.columns(6)
n1.metric("Streak (4H)", f"{d4h['streak_bars']} bars")
n2.metric("EMA-20",  f"{d4h['ema_20']:,.2f}")
n3.metric("Slope",   f"{d4h['slope']:+.3f}")
n4.metric("K1",      f"{d4h['k1']:.3f}")
n5.metric("K2",      f"{d4h['k2']:.3f}")
n6.metric("ATR-14",  f"{d4h['atr_14']:.1f}")

if df_4h_full.empty or "Slope_Phase" not in df_4h_full.columns:
    st.warning("No 4H data — need more 1H history to resample.")
else:
    v4h = df_4h_full.dropna(subset=["Slope_Phase"])
    if not v4h.empty:
        st.caption(
            f"Latest 4H bar: **{v4h.index[-1].strftime('%d %b %Y  %H:%M')} IST** "
            f"· {len(v4h)} confirmed candles · resampled from 60-min"
        )
    fig_4h = _build_chart(df_4h_full, 40, "4H")
    if fig_4h:
        st.plotly_chart(fig_4h, use_container_width=True)
    else:
        st.info("Insufficient 4H data to render chart.")

st.markdown("**Phase legend:**")
_phase_legend(cur_phase_4h)

st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# TUNING GUIDE
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("Threshold Tuning Guide", expanded=False):
    from config import EMA_SLOPE_M1, EMA_SLOPE_M2
    st.markdown(f"""
**Current:** `m1 = {EMA_SLOPE_M1}` (K1)  ·  `m2 = {EMA_SLOPE_M2}` (K2)
Same multipliers apply to both 60-Min and 4H charts. ATR auto-scales to each timeframe's volatility.

| Observation | Fix | Effect |
|---|---|---|
| Phase 3 catching mild trends as "Flat" | Lower `m1`: `0.03` → `0.02` | Tightens neutral band |
| Phase 1/5 transitions feel late | Lower `m2`: `0.10` → `0.08` | Strong moves classified earlier |
| Too many Phase 1/5 whipsaws | Raise `m2`: `0.10` → `0.12` | Only genuine acceleration qualifies |

Edit `config.py` → `EMA_SLOPE_M1` / `EMA_SLOPE_M2`.
    """)
