# pages/09_Bollinger.py — Page 09: Bollinger Bands Framework v4 MTF
# TF hierarchy: 2H=PRIMARY | 4H=SECONDARY | 1D=BG | 1W=MACRO
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P09 · Bollinger Bands", layout="wide")
st_autorefresh(interval=60_000, key="p09")
st.title("Page 09 — Bollinger Bands Framework")
st.caption("2H=PRIMARY · 4H=SECONDARY · 1D=BG · 1W=MACRO | Asymmetric IC: CE +3.5% / PE −4%")

from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)

# ─────────────────────────────────────────────────────────────────────────────
# BB PHASE CHARTS — 1H / 2H / 4H  (rendered before sig / st.stop())
# ─────────────────────────────────────────────────────────────────────────────
_PHASE_COLOR = {
    "EXTREME_SQUEEZE": "#ef4444",
    "SQUEEZE":         "#f97316",
    "CALM":            "#22c55e",
    "MOMENTUM":        "#eab308",
    "HIGH_VOL":        "#a855f7",
    "MEAN_REVERT":     "#ec4899",
}
_PHASE_FILL = {
    "EXTREME_SQUEEZE": "rgba(239,68,68,0.15)",
    "SQUEEZE":         "rgba(249,115,22,0.12)",
    "CALM":            "rgba(34,197,94,0.12)",
    "MOMENTUM":        "rgba(234,179,8,0.12)",
    "HIGH_VOL":        "rgba(168,85,247,0.15)",
    "MEAN_REVERT":     "rgba(236,72,153,0.15)",
}
_BW_LEVELS = [
    (2.0, "EXTREME_SQ", "#ef4444"),
    (3.5, "SQUEEZE",    "#f97316"),
    (4.5, "CALM",       "#22c55e"),
    (5.6, "MOMENTUM",   "#eab308"),
    (6.5, "HIGH_VOL",   "#a855f7"),
]
_EMA_PHASE_COLORS = {1: "#00C853", 2: "#69F0AE", 3: "#FFD600", 4: "#FF6D00", 5: "#D50000"}
_MPR_BULL_STRONG  = "#1565C0"   # mpr_shift < -0.30
_MPR_BULL_MILD    = "#90CAF9"   # -0.30 to -0.10
_MPR_NEUTRAL      = "#BDBDBD"
_MPR_BEAR_MILD    = "#EF9A9A"   # 0.10 to 0.30
_MPR_BEAR_STRONG  = "#B71C1C"   # > 0.30


def _classify_bw(bw):
    for thr, name in [(2.0,"EXTREME_SQUEEZE"),(3.5,"SQUEEZE"),(4.5,"CALM"),
                      (5.6,"MOMENTUM"),(6.5,"HIGH_VOL"),(None,"MEAN_REVERT")]:
        if thr is None or bw < thr:
            return name
    return "MEAN_REVERT"


def _add_mpr(df: pd.DataFrame, long_win: int, short_win: int) -> pd.DataFrame:
    if "bb_basis" not in df.columns or len(df) < long_win:
        df["mpr_shift"] = np.nan
        return df
    above = (df["close"] > df["bb_basis"]).astype(float)
    df["mpr_long"]  = above.rolling(long_win, min_periods=max(1, long_win // 2)).mean()
    df["mpr_short"] = above.rolling(short_win, min_periods=1).mean()
    df["mpr_shift"] = df["mpr_short"] - df["mpr_long"]
    return df


def _mpr_bar_color(v):
    if pd.isna(v):   return _MPR_NEUTRAL
    if v >  0.30:    return _MPR_BEAR_STRONG
    if v >  0.10:    return _MPR_BEAR_MILD
    if v < -0.30:    return _MPR_BULL_STRONG
    if v < -0.10:    return _MPR_BULL_MILD
    return _MPR_NEUTRAL


@st.cache_data(ttl=3600, show_spinner=False)
def _load_bb_all_tf():
    """Load 1H raw, compute BB + MPR + EMA phases on 1H / 2H / 4H."""
    try:
        from data.live_fetcher import get_nifty_1h_phase
        from analytics.supertrend import resample_ohlcv
        from analytics.bollinger import BollingerOptionsEngine
        from analytics.ema_slope_phases import calculate_hourly_ema_slope_phases
        eng = BollingerOptionsEngine()
        raw = get_nifty_1h_phase()
        if raw.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "1H data empty — Kite login needed"

        def _prep(df, long_win, short_win):
            df = eng.compute(df.copy())
            if "bb_bw" not in df.columns:
                return pd.DataFrame()
            if hasattr(df.index, "tz") and df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            df["phase"] = df["bb_bw"].apply(_classify_bw)
            df = _add_mpr(df, long_win, short_win)
            df = calculate_hourly_ema_slope_phases(df)
            return df.dropna(subset=["bb_bw"]).copy()

        df_1h = _prep(raw, long_win=35, short_win=3)
        df_2h = _prep(resample_ohlcv(raw, "2h"), long_win=20, short_win=2)
        df_4h = _prep(resample_ohlcv(raw, "4h"), long_win=10, short_win=2)
        return df_1h, df_2h, df_4h, None
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), str(e)


def _build_bb_chart(df: pd.DataFrame, title: str) -> object:
    """4-panel chart: price+BB | MPR ribbon | EMA ribbon | BW%+MPR line."""
    if df.empty or len(df) < 5:
        return None

    from analytics.ema_slope_phases import PHASE_LABELS as _EMA_LABELS

    plot = df.dropna(subset=["phase"]).copy()
    n    = len(plot)
    xp   = list(range(n))
    tsi  = plot.index.tolist()
    htxt = [t.strftime("%d %b %H:%M") for t in tsi]
    phs  = plot["phase"].tolist()
    bw   = plot["bb_bw"].tolist()
    has_mpr = "mpr_shift" in plot.columns
    has_ema = "Slope_Phase" in plot.columns

    # date ticks — first bar of each calendar day
    seen: dict = {}
    for i, t in enumerate(tsi):
        if t.date() not in seen:
            seen[t.date()] = i
    tv = list(seen.values())
    tl = [tsi[i].strftime("%d %b") for i in tv]

    # BB phase segments for background fill
    segs, s0, s_ph = [], 0, phs[0]
    for i in range(1, n):
        if phs[i] != s_ph:
            segs.append((s0, i - 1, s_ph))
            s0, s_ph = i, phs[i]
    segs.append((s0, n - 1, s_ph))

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.55, 0.06, 0.06, 0.33],
        vertical_spacing=0.01,
        specs=[
            [{"secondary_y": False}],
            [{"secondary_y": False}],
            [{"secondary_y": False}],
            [{"secondary_y": True}],
        ],
        subplot_titles=[
            f"Nifty {title} · BB Phases + EMA Slope",
            "MPR Shift  (blue=bullish pressure · red=bearish)",
            "EMA Slope Phase  (green→red = bullish→bearish)",
            "BW% by Phase  ·  MPR Shift line (right axis)",
        ],
    )

    # ── Panel 1: BB phase background ─────────────────────────────────────────
    for p0, p1, ph in segs:
        fig.add_shape(
            type="rect", x0=p0 - 0.5, x1=p1 + 0.5, y0=0, y1=1,
            xref="x", yref="y domain",
            fillcolor=_PHASE_FILL.get(ph, "rgba(128,128,128,0.1)"),
            line_width=0, layer="below", row=1, col=1,
        )
    for p0, p1, ph in segs:
        fig.add_annotation(
            x=(p0 + p1) / 2, y=1.0, xref="x", yref="y domain",
            text=f"<b>{ph.replace('_',' ')}</b>", showarrow=False,
            font=dict(color="#ffffff", size=9),
            bgcolor=_PHASE_COLOR.get(ph, "#888"), borderpad=2,
            row=1, col=1,
        )

    # vertical event lines: BB change (grey dot), EMA change (blue dash), MPR ±0.30 cross (solid)
    for i in range(1, n):
        if phs[i] != phs[i - 1]:
            fig.add_shape(type="line", x0=i-0.5, x1=i-0.5, y0=0, y1=1,
                          xref="x", yref="y domain",
                          line=dict(color="rgba(100,100,100,0.35)", width=1, dash="dot"),
                          row=1, col=1)
    if has_ema:
        eph_list = plot["Slope_Phase"].tolist()
        for i in range(1, n):
            a, b_ = eph_list[i-1], eph_list[i]
            if not (pd.isna(a) or pd.isna(b_)) and a != b_:
                fig.add_shape(type="line", x0=i-0.5, x1=i-0.5, y0=0, y1=1,
                              xref="x", yref="y domain",
                              line=dict(color="rgba(21,101,192,0.50)", width=1, dash="dash"),
                              row=1, col=1)
    if has_mpr:
        mpr_raw = plot["mpr_shift"].tolist()
        for i in range(1, n):
            vp, vc = mpr_raw[i-1], mpr_raw[i]
            if pd.isna(vp) or pd.isna(vc):
                continue
            if (vp <= 0.30 < vc) or (vp >= 0.30 > vc):
                fig.add_shape(type="line", x0=i-0.5, x1=i-0.5, y0=0, y1=1,
                              xref="x", yref="y domain",
                              line=dict(color="rgba(183,28,28,0.70)", width=1.5),
                              row=1, col=1)
            elif (vp >= -0.30 > vc) or (vp <= -0.30 < vc):
                fig.add_shape(type="line", x0=i-0.5, x1=i-0.5, y0=0, y1=1,
                              xref="x", yref="y domain",
                              line=dict(color="rgba(21,101,192,0.70)", width=1.5),
                              row=1, col=1)

    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=xp, open=plot["open"], high=plot["high"],
        low=plot["low"], close=plot["close"],
        text=htxt, name=f"Nifty {title}",
        increasing=dict(line=dict(color="#26a69a", width=1), fillcolor="#26a69a"),
        decreasing=dict(line=dict(color="#ef5350", width=1), fillcolor="#ef5350"),
        whiskerwidth=0.3, showlegend=False,
    ), row=1, col=1)

    # EMA phase colored dots at candle highs (phase indicator per bar)
    if has_ema:
        eph_f = [int(v) if not pd.isna(v) else 3 for v in plot["Slope_Phase"].tolist()]
        dot_colors = [_EMA_PHASE_COLORS.get(ep, "#888") for ep in eph_f]
        highs = plot["high"].tolist()
        dot_y = [h * 1.0005 for h in highs]
        fig.add_trace(go.Scatter(
            x=xp, y=dot_y, mode="markers",
            marker=dict(size=4, color=dot_colors, symbol="circle"),
            name="EMA Phase (dot)", showlegend=False,
            hovertext=[_EMA_LABELS.get(ep, "?") for ep in eph_f], hoverinfo="text",
        ), row=1, col=1)

    # BB bands
    fig.add_trace(go.Scatter(
        x=xp, y=plot["bb_upper"].tolist(), mode="lines", name="BB Upper",
        line=dict(color="#1565C0", width=1, dash="dot"), showlegend=True,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=xp, y=plot["bb_lower"].tolist(), mode="lines", name="BB Lower",
        line=dict(color="#1565C0", width=1, dash="dot"),
        fill="tonexty", fillcolor="rgba(21,101,192,0.07)", showlegend=False,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=xp, y=plot["bb_basis"].tolist(), mode="lines", name="BB Basis",
        line=dict(color="#1565C0", width=1.5), showlegend=True,
    ), row=1, col=1)

    # ── Panel 2: MPR shift ribbon ─────────────────────────────────────────────
    if has_mpr:
        mpr_vals = plot["mpr_shift"].fillna(0).tolist()
        mpr_clrs = [_mpr_bar_color(v) for v in mpr_vals]
        fig.add_trace(go.Bar(
            x=xp, y=[1] * n, marker_color=mpr_clrs, marker_line_width=0,
            name="MPR Shift ribbon", showlegend=True,
            hovertext=[f"MPR shift: {v:.3f}" for v in mpr_vals], hoverinfo="text",
        ), row=2, col=1)
    fig.update_yaxes(visible=False, row=2, col=1)

    # ── Panel 3: EMA slope phase ribbon ──────────────────────────────────────
    if has_ema:
        eph_f2 = [int(v) if not pd.isna(v) else 3 for v in plot["Slope_Phase"].tolist()]
        ema_clrs = [_EMA_PHASE_COLORS.get(ep, "#FFD600") for ep in eph_f2]
        fig.add_trace(go.Bar(
            x=xp, y=[1] * n, marker_color=ema_clrs, marker_line_width=0,
            name="EMA Phase ribbon", showlegend=True,
            hovertext=[_EMA_LABELS.get(ep, "?") for ep in eph_f2], hoverinfo="text",
        ), row=3, col=1)
    fig.update_yaxes(visible=False, row=3, col=1)

    # ── Panel 4: BW% bars (left) + MPR shift line (right) ────────────────────
    for ph, col in _PHASE_COLOR.items():
        mask = [i for i, p in enumerate(phs) if p == ph]
        if mask:
            fig.add_trace(go.Bar(
                x=[xp[i] for i in mask], y=[bw[i] for i in mask],
                name=ph.replace("_", " "), marker_color=col, opacity=0.85,
                showlegend=True,
            ), row=4, col=1)
    for thr, lbl, col in _BW_LEVELS:
        fig.add_hline(y=thr, line_width=1, line_dash="dot", line_color=col,
                      annotation_text=lbl, annotation_position="right",
                      row=4, col=1)

    if has_mpr:
        mpr_vals2 = plot["mpr_shift"].tolist()
        # threshold reference lines on secondary y (as scatter to avoid add_hline secondary_y issues)
        for thr_v, thr_c in [(0.30, _MPR_BEAR_STRONG), (-0.30, _MPR_BULL_STRONG), (0.0, "#757575")]:
            fig.add_trace(go.Scatter(
                x=[xp[0], xp[-1]], y=[thr_v, thr_v],
                mode="lines", line=dict(color=thr_c, width=1, dash="dot"),
                showlegend=False, hoverinfo="skip",
            ), row=4, col=1, secondary_y=True)
        fig.add_trace(go.Scatter(
            x=xp, y=mpr_vals2, mode="lines", name="MPR Shift",
            line=dict(color="#7B1FA2", width=1.5), showlegend=True,
        ), row=4, col=1, secondary_y=True)
        fig.update_yaxes(title_text="MPR", range=[-1.1, 1.1],
                         row=4, col=1, secondary_y=True,
                         gridcolor="#eeeeee", zeroline=False)

    fig.update_layout(
        height=850,
        margin=dict(l=10, r=65, t=50, b=10),
        paper_bgcolor="white", plot_bgcolor="white",
        font=dict(color="#222", size=12),
        legend=dict(orientation="h", x=0, y=-0.04,
                    bgcolor="rgba(255,255,255,0.9)", font=dict(size=10)),
        xaxis_rangeslider_visible=False,
        hovermode="x unified", barmode="overlay",
    )
    for r in [1, 2, 3, 4]:
        fig.update_yaxes(gridcolor="#eeeeee", zeroline=False, row=r, col=1,
                         secondary_y=False)
        fig.update_xaxes(tickvals=tv, ticktext=tl, gridcolor="#eeeeee",
                         range=[-0.5, n - 0.5], row=r, col=1)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="BW%",   row=4, col=1, secondary_y=False)
    return fig


# ── load all three TFs once ───────────────────────────────────────────────────
with st.spinner("Loading Bollinger data (1H · 2H · 4H)…"):
    _df1h, _df2h, _df4h, _bb_err = _load_bb_all_tf()

# ── 1H chart ─────────────────────────────────────────────────────────────────
ui.section_header("1H — Bollinger Phases  (1-month window)")
if _df1h.empty:
    st.warning(f"⚠️ 1H chart — {_bb_err or 'no data'}")
else:
    _fig1h = _build_bb_chart(_df1h, "1H")
    if _fig1h:
        st.caption(f"Latest 1H bar: **{_df1h.index[-1].strftime('%d %b %Y  %H:%M')} IST** · {len(_df1h)} candles")
        st.plotly_chart(_fig1h, use_container_width=True)

st.divider()

# ── 2H chart ─────────────────────────────────────────────────────────────────
ui.section_header("2H — Bollinger Phases  (PRIMARY · 1-month window)")
if _df2h.empty:
    st.warning(f"⚠️ 2H chart — {_bb_err or 'no data'}")
else:
    _fig2h = _build_bb_chart(_df2h, "2H")
    if _fig2h:
        st.caption(f"Latest 2H bar: **{_df2h.index[-1].strftime('%d %b %Y  %H:%M')} IST** · {len(_df2h)} candles")
        st.plotly_chart(_fig2h, use_container_width=True)

st.divider()

# ── 4H chart ─────────────────────────────────────────────────────────────────
ui.section_header("4H — Bollinger Phases  (SECONDARY · 1-month window)")
if _df4h.empty:
    st.warning(f"⚠️ 4H chart — {_bb_err or 'no data'}")
else:
    _fig4h = _build_bb_chart(_df4h, "4H")
    if _fig4h:
        st.caption(f"Latest 4H bar: **{_df4h.index[-1].strftime('%d %b %Y  %H:%M')} IST** · {len(_df4h)} candles")
        st.plotly_chart(_fig4h, use_container_width=True)

st.divider()

if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

import datetime, pytz
def _is_live():
    n = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
    t = n.hour * 60 + n.minute
    return n.weekday() < 5 and 9*60+15 <= t <= 15*60+30

if _is_live():
    try:
        from data.live_fetcher import get_nifty_daily_live, get_india_vix, get_nifty_1h_phase
        from analytics.bollinger import BollingerOptionsEngine
        from analytics.supertrend import resample_ohlcv
        from config import BB_VIX_DIV_VIX, BB_VIX_DIV_BW

        _df  = get_nifty_daily_live()
        _vix = get_india_vix()
        _atr = sig.get("atr14", 200)

        if not _df.empty:
            try:
                _df_1h = get_nifty_1h_phase()
                _df_2h = resample_ohlcv(_df_1h, "2h") if not _df_1h.empty else pd.DataFrame()
                _df_4h = resample_ohlcv(_df_1h, "4h") if not _df_1h.empty else pd.DataFrame()
            except Exception:
                _df_2h = _df_4h = pd.DataFrame()

            _df_1w = pd.DataFrame()
            try:
                _tmp = _df.copy()
                if not isinstance(_tmp.index, pd.DatetimeIndex):
                    _tmp.index = pd.to_datetime(_tmp.index)
                if getattr(_tmp.index, "tz", None) is not None:
                    _tmp.index = _tmp.index.tz_localize(None)
                _tmp = _tmp[~_tmp.index.duplicated(keep="last")]
                _df_1w = _tmp.resample("W-FRI").agg(
                    {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
                ).dropna(subset=["open","close"])
            except Exception:
                pass

            _bb = BollingerOptionsEngine().signals(_df_2h, _df_4h, _df, _df_1w, atr14=_atr)
            sig = {**sig, **{f"bb_{k}": v for k, v in _bb.items()}}
            sig["bb_regime"]            = _bb["regime_2h"]
            sig["bw_pct"]               = _bb["bw_2h"]
            sig["bb_squeeze_status"]    = _bb["squeeze_status"]
            sig["bb_asymmetry_signal"]  = _bb["asymmetry_signal"]
            sig["bb_confidence"]        = _bb["confidence"]
            sig["bb_skip_score"]        = _bb["skip_score"]
            sig["bb_skip_conditions"]   = _bb.get("skip_conditions", {})
            sig["bb_entry_verdict"]     = _bb["entry_verdict"]
            sig["bb_primary_risk_side"] = _bb["primary_risk_side"]
            sig["bb_drift_risk"]        = _bb["drift_risk"]
            sig["bb_l4_pe"]             = _bb["l4_pe"]
            sig["bb_l4_ce"]             = _bb["l4_ce"]
            sig["bb_walk_up_count"]     = _bb.get("walk_up_2h", 0)
            sig["bb_walk_down_count"]   = _bb.get("walk_down_2h", 0)
            sig["bb_kill_switches"]     = _bb.get("kill_switches", {})
            sig["bb_vix_divergence"]    = _vix > BB_VIX_DIV_VIX and _bb["bw_2h"] < BB_VIX_DIV_BW
            signals_ts = "LIVE"
    except Exception as _e:
        st.caption(f"Live Bollinger unavailable: {_e}")

# ── Read all signals ──────────────────────────────────────────────────────────
bb_regime   = sig.get("bb_regime",            "CALM")
bw_2h       = sig.get("bb_bw_2h",             sig.get("bw_pct", 5.0))
bw_4h       = sig.get("bb_bw_4h",             5.0)
bw_1d       = sig.get("bb_bw_1d",             5.0)
bw_1w       = sig.get("bb_bw_1w",             7.0)
reg_4h      = sig.get("bb_regime_4h",         "CALM")
reg_1d      = sig.get("bb_regime_1d",         "CALM")
reg_1w      = sig.get("bb_regime_1w",         "CALM")
zone_2h     = sig.get("bb_zone_2h",           "MIDLINE")
zone_4h     = sig.get("bb_zone_4h",           "MIDLINE")
pb_2h       = sig.get("bb_pct_b_2h",          0.5)
pb_4h       = sig.get("bb_pct_b_4h",          0.5)
squeeze     = sig.get("bb_squeeze_status",    "NONE")
asymmetry   = sig.get("bb_asymmetry_signal",  "1:1")
confidence  = sig.get("bb_confidence",        "MEDIUM")
skip_score  = sig.get("bb_skip_score",        0)
skip_conds  = sig.get("bb_skip_conditions",   {})
risk_side   = sig.get("bb_primary_risk_side", "NEUTRAL")
drift_risk  = sig.get("bb_drift_risk",        "BASE")
ma_2h       = sig.get("bb_ma_position_2h",   "AT_MA")
ma_4h       = sig.get("bb_ma_position_4h",   "AT_MA")
wu_2h       = sig.get("bb_walk_up_2h",       sig.get("bb_walk_up_count", 0))
wd_2h       = sig.get("bb_walk_down_2h",     sig.get("bb_walk_down_count", 0))
wu_4h       = sig.get("bb_walk_up_4h",       0)
wd_4h       = sig.get("bb_walk_down_4h",     0)
wlbl_2h     = sig.get("bb_walk_label_2h",    "NONE")
wlbl_4h     = sig.get("bb_walk_label_4h",    "NONE")
ce_watch    = sig.get("bb_ce_watch",         False)
pe_watch    = sig.get("bb_pe_watch",         False)
vix_div     = sig.get("bb_vix_divergence",   False)
l4_pe       = sig.get("bb_l4_pe",            0)
l4_ce       = sig.get("bb_l4_ce",            0)
atr14       = sig.get("atr14",               200)

# ── Derived trade parameters ──────────────────────────────────────────────────
ce_strike = int(round(spot * 1.035 / 50) * 50) if spot > 0 else 0
pe_strike = int(round(spot * 0.960 / 50) * 50) if spot > 0 else 0

# Lot size — stress drives sizing, never skips
lot_pct    = 100
lot_reason = "No significant stress — full entry"
if vix_div and bb_regime == "EXTREME_SQUEEZE":
    lot_pct    = 25
    lot_reason = "VIX divergence + EXTREME_SQUEEZE — dangerous combination"
elif bw_1w > 10.2:
    lot_pct    = 25
    lot_reason = f"1W macro event active (BW% {bw_1w:.1f}%) — weekly bands blown wide"
elif skip_score >= 3:
    lot_pct    = 25
    lot_reason = f"{skip_score}/5 stress conditions firing"
elif squeeze == "DEEP":
    lot_pct    = 50
    lot_reason = "DEEP SQUEEZE — coil before explosion, direction unknown"
elif bb_regime == "EXTREME_SQUEEZE":
    lot_pct    = 50
    lot_reason = "EXTREME_SQUEEZE — explosive move imminent"
elif skip_score == 2:
    lot_pct    = 50
    lot_reason = "2/5 stress conditions active"

# Ratio — engine output, forced 1:1 on DEEP squeeze
ratio = "1:1" if squeeze == "DEEP" else asymmetry

# Watch leg
if squeeze == "DEEP":
    watch_leg = "BOTH"
elif risk_side == "CE" or zone_2h in ("ABOVE_BAND", "UPPER") or (wlbl_2h != "NONE" and wu_2h >= wd_2h):
    watch_leg = "CE"
elif risk_side == "PE" or zone_2h in ("BELOW_BAND", "LOWER") or (wlbl_2h != "NONE" and wd_2h > wu_2h):
    watch_leg = "PE"
elif ma_4h == "BELOW_MA":
    watch_leg = "PE"
elif ce_watch:
    watch_leg = "CE"
elif pe_watch:
    watch_leg = "PE"
else:
    watch_leg = "BOTH"

# CE extra distance advisory
ce_extra_advisory = None
if (vix_div or bb_regime == "EXTREME_SQUEEZE") and ce_strike > 0:
    _ce_wide = ce_strike + 100
    ce_extra_advisory = (
        f"Consider CE {_ce_wide:,} (+100 pts wider) instead of {ce_strike:,} "
        f"given {'VIX divergence' if vix_div else 'EXTREME_SQUEEZE'} — implied risk is higher than intraday vol suggests."
    )

# Traffic light
if lot_pct == 25:
    tl_icon, tl_label, tl_color = "🔴", "HIGH STRESS", "red"
elif lot_pct == 50:
    tl_icon, tl_label, tl_color = "🟡", "MODERATE STRESS", "amber"
else:
    tl_icon, tl_label, tl_color = "🟢", "CLEAN WEEK", "green"

# Plain English summary (2–3 sentences)
def _build_summary():
    s = []
    # Sentence 1: what the chart looks like
    if squeeze == "DEEP" or bb_regime == "EXTREME_SQUEEZE":
        s.append(
            f"The 2H chart is extremely compressed (BW% {bw_2h:.1f}%) — "
            "Nifty is coiled like a spring before a sharp directional break."
        )
    elif squeeze == "ALIGNED":
        s.append(
            "Both the 2H and 4H bands are compressed — the best IC entry setup of the cycle. "
            "Options premium is rich relative to the actual move space available."
        )
    elif squeeze == "PARTIAL":
        s.append(
            f"The 2H is coiled (BW% {bw_2h:.1f}%) but the 4H hasn't compressed yet — "
            "a developing setup with decent edge."
        )
    elif bb_regime == "CALM":
        s.append(
            f"Bands are gently stable (2H BW% {bw_2h:.1f}%) — "
            "ideal premium decay conditions, no directional stress."
        )
    elif bb_regime == "MOMENTUM":
        s.append(
            f"Market is picking direction on the 2H (BW% {bw_2h:.1f}%) — "
            "one leg is under building pressure."
        )
    elif bb_regime == "HIGH_VOL":
        s.append(
            f"Volatility is elevated on the 2H (BW% {bw_2h:.1f}%) — "
            "a significant move is already in progress."
        )
    elif bb_regime == "MEAN_REVERT":
        s.append(
            f"The 2H bands are overextended (BW% {bw_2h:.1f}%) — "
            "the big move already happened and snap-back risk is high."
        )
    else:
        s.append(f"2H regime: {bb_regime} (BW% {bw_2h:.1f}%).")

    # Sentence 2: VIX / macro context
    if vix_div:
        s.append(
            "VIX is elevated while 2H realised vol is quiet — "
            "the options market is pricing in danger that intraday price hasn't shown yet."
        )
    elif bw_1w > 10.2:
        s.append(
            f"The weekly chart is in macro mean-revert territory (BW% {bw_1w:.1f}%) — "
            "a large event has already unfolded and aftershocks are possible."
        )
    elif reg_1w == "MEAN_REVERT":
        s.append(
            "Price is below its weekly moving average — macro drift is downward, PE leg carries more structural stress."
        )

    # Sentence 3: direction lean / action
    if squeeze == "DEEP":
        s.append(
            "Direction is genuinely unknowable — enter both legs at equal size and monitor daily for the breakout direction."
        )
    elif risk_side == "CE":
        s.append("Price is drifting toward the upper band — keep a closer eye on the CE leg after entry.")
    elif risk_side == "PE" or ma_4h == "BELOW_MA":
        s.append("Price is below the 4H moving average with a slight downside lean — PE leg has more structural stress.")
    elif ratio == "1:1":
        s.append("No directional pressure on either leg — this is a symmetric, well-balanced IC week.")

    return " ".join(s[:3])

plain_summary = _build_summary()

# ── Colour maps ───────────────────────────────────────────────────────────────
REGIME_COLOUR = {
    "EXTREME_SQUEEZE":"red","SQUEEZE":"red","CALM":"green",
    "MOMENTUM":"amber","HIGH_VOL":"red","MEAN_REVERT":"red",
}
SQ_COLOUR    = {"ALIGNED":"green","PARTIAL":"amber","DEEP":"red","NONE":"default"}
CONF_COLOUR  = {"HIGH":"green","MEDIUM":"amber","WEAK":"red"}
DRIFT_COLOUR = {"BASE":"green","ELEVATED":"amber","VERY_HIGH":"red","VETO":"red"}
WALK_COLOUR  = {"STRONG":"red","MODERATE":"red","MILD":"amber","NONE":"green"}
LOT_COLOUR   = {100:"green",50:"amber",25:"red"}

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — THIS WEEK'S TRADE
# ─────────────────────────────────────────────────────────────────────────────
ui.section_header(f"{tl_icon}  This Week's Trade — {tl_label}")
st.markdown(f"> {plain_summary}")
st.divider()

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    _ce_disp = f"{ce_strike:,}" if ce_strike > 0 else "—"
    ui.metric_card("SELL CE AT", _ce_disp,
                   sub=f"+3.5% from {spot:,.0f}" if spot > 0 else "spot unknown",
                   color="amber" if watch_leg in ("CE","BOTH") else "green")
with c2:
    _pe_disp = f"{pe_strike:,}" if pe_strike > 0 else "—"
    ui.metric_card("SELL PE AT", _pe_disp,
                   sub=f"−4.0% from {spot:,.0f}" if spot > 0 else "spot unknown",
                   color="amber" if watch_leg in ("PE","BOTH") else "green")
with c3:
    ui.metric_card("RATIO", ratio,
                   sub="CE lots : PE lots",
                   color="amber" if ratio != "1:1" else "green")
with c4:
    _reason_short = lot_reason[:42] + "…" if len(lot_reason) > 42 else lot_reason
    ui.metric_card("LOT SIZE", f"{lot_pct}%",
                   sub=_reason_short,
                   color=LOT_COLOUR.get(lot_pct, "green"))
with c5:
    _watch_color = "red" if (watch_leg == "BOTH" and squeeze == "DEEP") else \
                   "amber" if watch_leg in ("CE","PE") else "green"
    ui.metric_card("WATCH LEG", watch_leg,
                   sub="Post-entry monitoring priority",
                   color=_watch_color)

if ce_extra_advisory:
    st.info(f"ℹ️ {ce_extra_advisory}")

# Condition-specific callouts
if squeeze == "DEEP":
    st.warning(
        "⚠️ **DEEP SQUEEZE** — EXTREME_SQUEEZE active on 2H or 4H. "
        "Ratio locked to 1:1 and lots capped at 50%. "
        "Monitor daily: once bands start expanding, lean ratio toward the breakout direction."
    )
if wlbl_2h == "STRONG":
    _ws = "upper" if wu_2h >= wd_2h else "lower"
    _leg = "CE" if wu_2h >= wd_2h else "PE"
    st.warning(
        f"⚠️ **2H STRONG WALK** — Day {max(wu_2h,wd_2h)} along {_ws} band. "
        f"{_leg} short is under sustained pressure — ratio already reflects this, size reduced."
    )
elif wlbl_2h == "MODERATE":
    _ws = "upper" if wu_2h >= wd_2h else "lower"
    st.warning(f"⚠️ **2H MODERATE WALK** — Day {max(wu_2h,wd_2h)} along {_ws} band. Asymmetry applied.")

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — STRESS CHECK
# ─────────────────────────────────────────────────────────────────────────────
ui.section_header("Stress Check", f"{skip_score}/5 active  ·  0–1 = full lots  |  2 = half  |  3+ = quarter")

_yes = "background-color:#fee2e2;font-weight:700"
_no  = "background-color:#dcfce7"

_stress_rows = [
    ["1",
     "Daily chart heating up (1D BW% > 5.6%)",
     "YES" if skip_conds.get("1d_high_vol", bw_1d > 5.6) else "NO",
     f"{bw_1d:.2f}%  ({reg_1d})",
     "−25% lots"],
    ["2",
     "Weekly trend is down (1W price > 2% below MA)",
     "YES" if skip_conds.get("1w_below_ma", False) else "NO",
     f"1W {reg_1w}  BW% {bw_1w:.2f}%",
     "−25% lots"],
    ["3",
     "4H trend established — 4H walk ≥ 4 days",
     "YES" if skip_conds.get("4h_strong_walk", max(wu_4h,wd_4h)>=4) else "NO",
     f"max {max(wu_4h,wd_4h)} days  ({wlbl_4h})",
     "−25% lots"],
    ["4",
     "2H bands overextended (MEAN_REVERT)",
     "YES" if skip_conds.get("2h_mean_revert", bb_regime=="MEAN_REVERT") else "NO",
     f"{bb_regime}  ({bw_2h:.2f}%)",
     "−25% lots"],
    ["5",
     "Macro event in progress (1W BW% > 10.2%)",
     "YES" if skip_conds.get("1w_mean_revert", bw_1w > 10.2) else "NO",
     f"{bw_1w:.2f}%  ({reg_1w})",
     "→ 25% lots (hard)"],
]
_stress_df = pd.DataFrame(
    _stress_rows,
    columns=["#", "What it means in plain English", "Active", "Current value", "Impact on lots"],
)
st.dataframe(
    _stress_df.style.map(
        lambda v: _yes if v=="YES" else _no if v=="NO" else "",
        subset=["Active"],
    ),
    use_container_width=True, hide_index=True,
)

with st.expander("Lot Sizing Rules — Full Reference", expanded=False):
    st.markdown("""
You always enter — the stress score just tells you how big to be.

| Stress Score | Lot Size | What it means |
|---|---|---|
| 0–1 | **100%** | Clean week — deploy full capital, theta works efficiently |
| 2 | **50%** | Two things going wrong at once — halve size, reduce P&L variance |
| 3+ | **25%** | Multiple structural risks stacking — protect capital, collect small theta |

**Hard overrides** (take priority over the score above):

| Condition | Lot Size | Reason |
|---|---|---|
| VIX divergence + EXTREME_SQUEEZE | **25%** | Most dangerous setup — implied vol is warning, direction unknown |
| 1W BW% > 10.2% (macro event) | **25%** | Weekly move capacity is unbounded, stay very small |
| DEEP SQUEEZE (either TF < 2%) | **max 50%** | Can't know direction — enter small, add to winning side after breakout |
| EXTREME_SQUEEZE alone | **50%** | Coil is tight but 4H not confirming yet |
""")

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — MARKET ANALYSIS DETAIL (collapsed by default)
# ─────────────────────────────────────────────────────────────────────────────
with st.expander("Market Analysis — 4-TF Regime · %B · Walk · Drift Risk", expanded=False):

    ui.section_header("4-TF Regime Overview")
    c1, c2, c3, c4 = st.columns(4)
    for _col, _label, _bw, _reg, _note in [
        (c1, "2H — PRIMARY",   bw_2h, bb_regime, "Drives ratio + lot size"),
        (c2, "4H — SECONDARY", bw_4h, reg_4h,   "Confidence modifier"),
        (c3, "1D — BG",        bw_1d, reg_1d,   "Stress cond 1 if >5.6%"),
        (c4, "1W — MACRO",     bw_1w, reg_1w,   "Stress conds 2 and 5"),
    ]:
        with _col:
            ui.metric_card(_label, _reg, sub=f"BW% {_bw:.2f}% · {_note}",
                           color=REGIME_COLOUR.get(_reg, "default"))

    with st.expander("Regime Reference — What Each State Means for Your IC", expanded=False):
        st.markdown("""
| Regime | BW% (2H/4H) | Lot Size | Ratio | What it means |
|---|---|---|---|---|
| EXTREME_SQUEEZE | < 2% | 50% | 1:1 | Coiled spring — direction unknown, explosive move coming |
| SQUEEZE | 2–3.5% | 100% | From %B | Best entry — premium rich, bands compressed |
| CALM | 3.5–4.5% | 100% | 1:1 most weeks | Sweet spot — ideal decay environment |
| MOMENTUM | 4.5–5.6% | 100% | From %B | Market picking direction — one leg under pressure |
| HIGH_VOL | 5.6–6.5% | 50% | From %B | Move already in progress — widen both legs |
| MEAN_REVERT | > 6.5% | 50% | 1:1 | Overextended — snap-back risk, +1 stress |
""")

    st.divider()

    ui.section_header("%B Zone — Where Price Sits Within the Band")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: ui.metric_card("2H %B",   f"{pb_2h:.3f}", sub=zone_2h,
                             color="red"   if zone_2h in ("ABOVE_BAND","BELOW_BAND") else
                                   "amber" if zone_2h in ("UPPER","LOWER") else "default")
    with c2: ui.metric_card("2H ZONE",  zone_2h, sub="Primary ratio driver")
    with c3: ui.metric_card("2H MA",    ma_2h,
                             sub="±0.3% around 2H basis",
                             color="amber" if ma_2h != "AT_MA" else "green")
    with c4: ui.metric_card("4H %B",   f"{pb_4h:.3f}", sub=zone_4h,
                             color="red" if zone_4h in ("ABOVE_BAND","BELOW_BAND") else "default")
    with c5: ui.metric_card("4H ZONE",  zone_4h, sub="Confidence modifier")
    with c6: ui.metric_card("4H MA",    ma_4h,
                             sub="±0.3% around 4H basis",
                             color="amber" if ma_4h != "AT_MA" else "green")

    with st.expander("%B Zone Reference — How Each Zone Maps to Ratio", expanded=False):
        st.markdown("""
%B = (close − lower band) / (upper − lower). 0 = touching lower band. 1 = touching upper band.

| Zone | %B | Ratio | What it means |
|---|---|---|---|
| ABOVE_BAND | > 1.0 | 1:2 CE | Price outside upper band — sustained bullish push, CE under pressure |
| UPPER | 0.75–1.0 | 1:2 CE | Approaching upper band — CE needs more room |
| UP_NEUTRAL | 0.55–0.75 | 1:1 + CE watch | Drifting up, no asymmetry yet — monitor CE |
| MIDLINE | 0.45–0.55 | 1:1 | Centred on the 20-period MA — ideal symmetric week |
| LO_NEUTRAL | 0.25–0.45 | 1:1 + PE watch | Drifting down, no asymmetry yet — monitor PE |
| LOWER | 0.0–0.25 | 2:1 PE | Approaching lower band — PE needs more room |
| BELOW_BAND | < 0.0 | 2:1 PE | Price outside lower band — sustained bearish push, PE under pressure |
""")

    st.divider()

    ui.section_header("Band Walk Status", "Consecutive closes at or beyond the band")
    c1, c2, c3, c4 = st.columns(4)
    with c1: ui.metric_card("2H WALK UP",   f"Day {wu_2h}", sub=wlbl_2h, color=WALK_COLOUR.get(wlbl_2h,"default"))
    with c2: ui.metric_card("2H WALK DOWN", f"Day {wd_2h}", sub=wlbl_2h, color=WALK_COLOUR.get(wlbl_2h,"default"))
    with c3: ui.metric_card("4H WALK UP",   f"Day {wu_4h}", sub=wlbl_4h, color=WALK_COLOUR.get(wlbl_4h,"default"))
    with c4: ui.metric_card("4H WALK DOWN", f"Day {wd_4h}", sub=wlbl_4h, color=WALK_COLOUR.get(wlbl_4h,"default"))

    with st.expander("Walk Reference", expanded=False):
        st.markdown("""
A walk = price closing at or beyond the band on consecutive bars — a sustained push against your short leg.

| Days | Label | What to do |
|---|---|---|
| 1 | (breach) | Monitor only |
| 2 | **MILD** | Lean ratio toward walk side |
| 3 | **MODERATE** | Max ratio toward walk side |
| 4+ | **STRONG** | Reduce size, apply max ratio |

**4H walk ≥ 4 days** = stress condition 3 fires (+1 to stress score, −25% lots).
""")

    st.divider()

    ui.section_header("CE Breach Drift Risk", "CE short at +3.5% · base weekly breach probability ~5%")
    _DRIFT_DESC = {
        "VERY_HIGH": "EXTREME_SQUEEZE or HIGH_VOL active — breach probability ~20%. Nifty has statistical capacity for a 3.5%+ intraweek move.",
        "ELEVATED":  "SQUEEZE or MOMENTUM — breach probability ~10%. Directional energy is still building.",
        "BASE":      "CALM regime — CE at +3.5% is safely in the 95th pctl of weekly drift. Historical base rate ~5%.",
        "VETO":      "MEAN_REVERT — snap-back dynamics. CE exposed to a rapid return to basis.",
    }
    ui.alert_box(
        f"Drift Risk: {drift_risk}",
        _DRIFT_DESC.get(drift_risk, ""),
        level="danger" if drift_risk in ("VERY_HIGH","VETO") else
              "warning" if drift_risk == "ELEVATED" else "success",
    )

    st.divider()

    _LENS_MULT = {
        "CALM":2.0,"SQUEEZE":2.25,"MOMENTUM":2.25,
        "EXTREME_SQUEEZE":2.5,"HIGH_VOL":2.5,"MEAN_REVERT":2.75,
    }
    _base_mult = _LENS_MULT.get(bb_regime, 2.25)
    _conf_risk = risk_side if risk_side != "NEUTRAL" else "neither"
    _CONF_DESC = {
        "HIGH":   f"4H confirms direction → full extra (+{round(0.5*atr14/50)*50:,} pts on {_conf_risk} leg)",
        "MEDIUM": f"4H neutral → half extra (+{round(0.25*atr14/50)*50:,} pts on {_conf_risk} leg)",
        "WEAK":   "4H contradicts 2H → 1:1 override, no extra distance",
    }
    _ZONE_RATIO = {
        "ABOVE_BAND":"1:2 CE","UPPER":"1:2 CE","UP_NEUTRAL":"1:1+CE watch",
        "MIDLINE":"1:1","LO_NEUTRAL":"1:1+PE watch",
        "LOWER":"2:1 PE","BELOW_BAND":"2:1 PE",
    }
    _ma_note = ""
    if asymmetry == "1:1" and zone_2h in ("ABOVE_BAND","UPPER","LOWER","BELOW_BAND"):
        _ma_note = "  ⚠️ MA override → ratio stepped to 1:1"
    ui.section_header("Asymmetry Formula")
    ui.simple_technical(
        f"2H %B zone = {zone_2h} → base: {_ZONE_RATIO.get(zone_2h,'1:1')}\n"
        f"Squeeze: {squeeze}" +
        (" → uses %B value directly for direction" if squeeze in ("ALIGNED","PARTIAL") else "") + "\n"
        f"4H confidence = {confidence} → {_CONF_DESC.get(confidence,'')}\n"
        f"2H MA = {ma_2h}  |  4H MA = {ma_4h}{_ma_note}",
        f"Ratio: {ratio}  ·  Risk side: {risk_side}\n"
        f"L4 → PE {l4_pe:,} pts  |  CE {l4_ce:,} pts  (base {_base_mult}× ATR14)",
    )

    with st.expander("Asymmetry & Lens Reference", expanded=False):
        st.markdown(f"""
**Base distance multipliers (ATR14 = {atr14:,} pts):**

| 2H Regime | Mult | Distance |
|---|---|---|
| EXTREME_SQUEEZE | 2.5× | {round(2.5*atr14/50)*50:,} pts |
| SQUEEZE | 2.25× | {round(2.25*atr14/50)*50:,} pts |
| CALM | 2.0× | {round(2.0*atr14/50)*50:,} pts |
| MOMENTUM | 2.25× | {round(2.25*atr14/50)*50:,} pts |
| HIGH_VOL | 2.5× | {round(2.5*atr14/50)*50:,} pts |
| MEAN_REVERT | 2.75× | {round(2.75*atr14/50)*50:,} pts |

**Extra on threatened leg:**  HIGH +{round(0.5*atr14/50)*50:,} pts · MEDIUM +{round(0.25*atr14/50)*50:,} pts · WEAK +0 pts
**Hard cap:** max 3.0× ATR14 = {round(3.0*atr14/50)*50:,} pts on either leg.
""")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — POST-ENTRY MONITORING
# ─────────────────────────────────────────────────────────────────────────────
with st.expander("Post-Entry Monitoring — What to Watch After Tuesday EOD", expanded=False):
    st.markdown(f"""
These rules apply **after you've entered** using live 4H and 2H data during the week.

| What to check | Trigger | What it means | What to do |
|---|---|---|---|
| **CE leg threat** | 4H %B > 0.85 | Price deep in upper zone — CE short under daily pressure | Watch for roll. If sustained 2 days, act. |
| **PE leg threat** | 4H %B < 0.15 | Price deep in lower zone — PE short under daily pressure | Watch for roll. If sustained 2 days, act. |
| **Vol explosion** | 4H BW% > 1.5× entry BW% | Bands expanding fast after entry — market chose direction | Reduce losing leg or close and re-enter wider. |
| **Walk developing** | 2H walk ≥ 2 days | Directional push building post-entry | Flag threatened leg. Prepare for roll if walk reaches MODERATE. |
| **Perfect decay** | Both 2H + 4H %B in 0.30–0.70 all week | Price oscillating near basis — no stress | Do nothing. Hold to expiry. Theta working. |

**Entry BW% baseline:** {bw_2h:.2f}% (2H at time of this signal)
**Vol expansion triggers if 4H BW% exceeds:** {bw_2h * 1.5:.2f}% within 2 days of entry
""")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — REFERENCE EXPANDERS
# ─────────────────────────────────────────────────────────────────────────────
with st.expander("BW% Reference Tables — All 4 TFs", expanded=False):
    _ca, _cb = st.columns(2)
    with _ca:
        st.markdown("**2H / 4H thresholds (primary + secondary TF)**")
        st.dataframe(pd.DataFrame([
            ["< 2.0%",    "EXTREME_SQUEEZE", "50% lots · 1:1 ratio"],
            ["2.0–3.5%",  "SQUEEZE",         "100% lots · ratio from %B"],
            ["3.5–4.5%",  "CALM",            "100% lots · 1:1 most weeks"],
            ["4.5–5.6%",  "MOMENTUM",        "100% lots · ratio from %B"],
            ["5.6–6.5%",  "HIGH_VOL",        "50% lots · widen both legs"],
            ["> 6.5%",    "MEAN_REVERT",     "50% lots · +1 stress condition"],
        ], columns=["BW%","Regime","Sizing Rule"]), use_container_width=True, hide_index=True)
    with _cb:
        st.markdown("**1D BW% (stress check only)**")
        st.dataframe(pd.DataFrame([
            ["< 3.5%",    "SQUEEZE",     "No stress"],
            ["3.5–5.6%",  "CALM",        "No stress"],
            ["> 5.6%",    "HIGH_VOL+",   "+1 stress condition (cond 1)"],
        ], columns=["1D BW%","Regime","Effect"]), use_container_width=True, hide_index=True)
        st.markdown("**1W BW% (macro check)**")
        st.dataframe(pd.DataFrame([
            ["< 4.5%",    "EXTREME_SQ",  "Macro caution — note it"],
            ["4.5–6.5%",  "CALM",        "Clean macro"],
            ["6.5–10.2%", "MOV / H_VOL", "No direct stress"],
            ["> 10.2%",   "MEAN_REVERT", "→ 25% lots ALWAYS (cond 5)"],
        ], columns=["1W BW%","Regime","Effect"]), use_container_width=True, hide_index=True)

with st.expander("Squeeze State Reference — ALIGNED / PARTIAL / DEEP / NONE", expanded=False):
    st.markdown("""
| State | What it means | What to do |
|---|---|---|
| **ALIGNED** | 2H + 4H both in SQUEEZE (2–3.5%) | Best entry of the cycle. Full lots, use %B for ratio direction. |
| **PARTIAL** | 2H squeezed, 4H not yet | Good entry. Moderate confidence. Proceed at full lots. |
| **DEEP** | Either TF in EXTREME_SQUEEZE (< 2%) | Cap at 50% lots. Force 1:1. Monitor daily for breakout direction — lean ratio once confirmed. |
| **NONE** | 2H not in SQUEEZE or EXTREME_SQUEEZE | Standard operation — %B and regime drive everything. |

**Why ALIGNED squeeze = best entry:** when BW% is compressed, options sellers have reduced IV to match low realised vol. The IC premium is rich relative to actual move space. Time decay works fast.
""")

with st.expander("Drift Risk Reference — CE Breach Probability by Regime", expanded=False):
    st.markdown(f"""
CE short at **+3.5% OTM** · Nifty's 95th pctl weekly drift ≈ 3.51% → base breach probability ~5% (1 in 20 weeks).

| 2H Regime | Risk Level | Approx CE Breach Prob | Why |
|---|---|---|---|
| CALM | BASE | ~5% | Bounded drift — no momentum |
| SQUEEZE | ELEVATED | ~10% | Coiled spring — release move can be sharp |
| MOMENTUM | ELEVATED | ~10% | Directional energy building |
| EXTREME_SQUEEZE | VERY_HIGH | ~20% | Explosion imminent, size unknown |
| HIGH_VOL | VERY_HIGH | ~20% | Big move already in progress |
| MEAN_REVERT | VETO | Unmodelled | Snap-back risk — structural tail |

**This is informational** — it tells you CE leg quality, not whether to enter. Lot sizing handles the entry size decision.
""")

with st.expander("Walk Reference — Consecutive Band Closes and IC Response", expanded=False):
    st.markdown("""
A walk = price closing at or beyond the Bollinger Band on consecutive bars. It signals a trend on that TF against your short leg.

| Days | Label | 2H Action | 4H Effect |
|---|---|---|---|
| 1 | *(breach)* | Monitor only — single bar could be noise | — |
| 2 | **MILD** | Lean ratio toward threatened leg | — |
| 3 | **MODERATE** | Max ratio toward threatened leg | — |
| 4+ | **STRONG** | Max ratio + reduce size | +1 stress condition if on 4H |

**2H walk** drives ratio directly. **4H walk ≥ 4 days** adds +1 to stress score (condition 3 in the table above).
""")
