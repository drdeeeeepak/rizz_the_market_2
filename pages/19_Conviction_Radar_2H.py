# pages/19_Conviction_Radar_2H.py
# Conviction Radar · 2H (positional) — the SAME engine as page 18, run on 2-hour candles
# with VWAP ANCHORED to each weekly cycle (first trading candle after the Tuesday expiry —
# i.e. the post-expiry Wednesday, or Thursday on a holiday). Built to track an Iron Condor
# across the whole weekly cycle, not intraday.

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import ui.components as ui
import ui.conviction_table as uict
from page_utils import bootstrap_signals, show_page_header
from data.live_fetcher import get_nifty_fut_2h, get_india_vix, get_dual_expiry_chains
from analytics.gamma_exposure import compute_gex
from analytics import intraday_conviction as ic

# Always run against current engine code (Streamlit caches imported modules across deploys).
import importlib
try:
    importlib.reload(ic)
    importlib.reload(uict)
except Exception:
    pass

st.set_page_config(page_title="P19 · Conviction Radar 2H", layout="wide")
st.title("Page 19 — Conviction Radar · 2H (positional)")
st.caption("Same engine as page 18 on **2-hour candles**, with VWAP **anchored to each "
           "post-expiry Wednesday** (Thursday on a holiday) — fair value *since the position "
           "was opened*, for tracking the Iron Condor across the weekly cycle.")

sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)

if spot <= 0:
    spot = float(sig.get("spot", 0))
if spot <= 0:
    st.error("⚠️ Live Nifty spot unavailable from Kite — log in / refresh. Showing nothing "
             "rather than guessing a price.")
    st.stop()

c1, c2 = st.columns([1, 3])
with c1:
    days = st.slider("Calendar days of 2H history", 20, 90, 60)

with st.spinner("Loading 2H data…"):
    df2 = get_nifty_fut_2h(days=days)
    vix = get_india_vix() or 0.0
    chains = get_dual_expiry_chains(spot)

if df2 is None or df2.empty:
    st.error("Could not load Nifty 2H data from Kite. Check login / market data, then refresh.")
    st.stop()

# Positional stretch uses a WEEKLY expected move (daily VIX 1-sigma × √5) so deviation from
# the weekly anchored VWAP is calibrated to the cycle, not a single day.
if vix > 0:
    expected_move_pts = spot * (vix / 100.0) / 16.0 * (5 ** 0.5)
else:
    expected_move_pts = spot * 0.013

near_df = chains.get("near", pd.DataFrame())
near_dte = chains.get("near_dte", 7)
atm_iv = float(sig.get("atm_iv", 12.0) or 12.0)
gex = compute_gex(near_df, spot, near_dte, iv_fallback_pct=atm_iv)
try:
    from data.gamma_history import log_intraday_snapshot
    log_intraday_snapshot(gex, spot)
except Exception:
    pass

df = ic.enrich(df2, expected_move_pts=expected_move_pts, breadth=None, anchored_vwap=True)

_REQ = {"bull_read", "bear_read", "state", "vwap", "above_vwap", "confidence", "conflict"}
if df.empty or not _REQ.issubset(df.columns) or not hasattr(ic, "candle_table"):
    st.warning("🔄 The app was just updated — open the menu (top-right ⋮) and **Reboot app** once "
               "to load the current engine.")
    st.stop()

verdict = ic.live_verdict(df, gex["regime"], gex.get("spot_vs_flip_pts"))
two_sided = ic.two_sided_verdict(df, gex.get("regime", "UNKNOWN"), gex.get("spot_vs_flip_pts"))
markers = ic.transition_markers(df)

# ══════════════════════════════════════════════════════════════════════════════
# Cards — bull · bear · Bull−Bear · Final (with today's gamma tilt on the live Final)
# ══════════════════════════════════════════════════════════════════════════════

def _side_card(d, kind):
    score = d.get("score", 0)
    bar_w = max(2, min(100, score))
    icon = "🟢" if kind == "bull" else "🔴"
    title = "BULL CASE — stay / be patient" if kind == "bull" else "BEAR CASE — defend"
    st.markdown(
        f"<div style='background:{d['color']}18;border-left:6px solid {d['color']};"
        f"border-radius:8px;padding:12px 16px;'>"
        f"<div style='font-size:13px;font-weight:800;letter-spacing:.4px;color:{d['color']};"
        f"text-transform:uppercase;'>{icon} {title}</div>"
        f"<div style='font-size:17px;font-weight:700;color:#0f172a;margin:5px 0 2px 0;'>{d['label']}"
        f" <span style='font-size:14px;color:#475569;font-weight:600;'>· {d['leg']}</span></div>"
        f"<div style='display:flex;align-items:center;gap:10px;margin:6px 0;'>"
        f"<div style='font-size:20px;font-weight:800;color:{d['color']};min-width:54px;'>{score}/100</div>"
        f"<div style='flex:1;background:#e2e8f0;border-radius:6px;height:10px;'>"
        f"<div style='width:{bar_w}%;background:{d['color']};height:10px;border-radius:6px;'></div></div></div>"
        f"<div style='font-size:14px;color:#475569;line-height:1.45;'>{d['detail']}<br>"
        f"<span style='color:#64748b;'>↳ {d['gamma']}</span></div>"
        f"</div>", unsafe_allow_html=True)

def _mini_card(title, value, color, label, detail):
    mag = max(2, min(100, abs(value)))
    st.markdown(
        f"<div style='background:{color}18;border-left:6px solid {color};"
        f"border-radius:8px;padding:12px 16px;'>"
        f"<div style='font-size:13px;font-weight:800;letter-spacing:.4px;color:{color};"
        f"text-transform:uppercase;'>{title}</div>"
        f"<div style='font-size:16px;font-weight:700;color:#0f172a;margin:5px 0 2px 0;'>{label}</div>"
        f"<div style='display:flex;align-items:center;gap:10px;margin:6px 0;'>"
        f"<div style='font-size:20px;font-weight:800;color:{color};min-width:54px;'>{value:+d}</div>"
        f"<div style='flex:1;background:#e2e8f0;border-radius:6px;height:10px;'>"
        f"<div style='width:{mag}%;background:{color};height:10px;border-radius:6px;'></div></div></div>"
        f"<div style='font-size:14px;color:#475569;line-height:1.45;'>{detail}</div>"
        f"</div>", unsafe_allow_html=True)

_net_val = int(two_sided["bull"].get("score", 0)) - int(two_sided["bear"].get("score", 0))
_conf_now = int(verdict.get("confidence", 0))
_cushioned = (gex.get("regime") == "POSITIVE") or ((gex.get("spot_vs_flip_pts") or 0) >= 0)
_gamma_known = gex.get("regime") in ("POSITIVE", "NEGATIVE")
_dir = 1 if _net_val > 0 else (-1 if _net_val < 0 else 0)
if _gamma_known and _dir:
    _aligned = _cushioned if _dir > 0 else (not _cushioned)
    _gtilt = 1.15 if _aligned else 0.85
    _gnote = (f"×{_gtilt:.2f} gamma " + ("✓ backs this direction" if _aligned else "✗ fights it"))
else:
    _gtilt, _gnote = 1.0, "gamma n/a today"
_final_val = int(round(max(-100, min(100, _net_val * _conf_now / 100.0 * _gtilt))))

if _final_val >= 35:
    _fcol, _flab = "#15803d", "STRONG BULL — act (stay / roll PUT up)"
elif _final_val >= 15:
    _fcol, _flab = "#16a34a", "Mild bull — real but unconfirmed, wait"
elif _final_val > -15:
    _fcol, _flab = "#64748b", "No edge — stand aside"
elif _final_val > -35:
    _fcol, _flab = "#dc2626", "Mild bear — caution on the threatened leg"
else:
    _fcol, _flab = "#b91c1c", "STRONG BEAR — defend (leg / sell-CALL)"

if _net_val > 8:
    _ncol, _nlab = "#16a34a", "Bull case ahead"
elif _net_val < -8:
    _ncol, _nlab = "#dc2626", "Bear case ahead"
else:
    _ncol, _nlab = "#64748b", "Balanced"

ui.section_header("Both sides, right now — on the weekly (2H) cycle",
                  "Bull case · Bear case · raw Bull−Bear · gamma-tilted Final")
bc, kc, nc, fc = st.columns(4)
with bc:
    _side_card(two_sided["bull"], "bull")
with kc:
    _side_card(two_sided["bear"], "bear")
with nc:
    _mini_card("⚖️ BULL − BEAR (raw)", _net_val, _ncol, _nlab,
               "bull-read − bear-read before the agreement & gamma adjustments.")
with fc:
    _mini_card("🎯 FINAL CONVICTION", _final_val, _fcol, _flab,
               "Bull−Bear × signal-agreement × today's gamma. ±35 agreed = act-worthy."
               + (f"<br><span style='color:#64748b;'>↳ {_gnote}</span>"))
st.caption("Positional read on the weekly cycle: **+35/-35** = strong, agreed, gamma-backed → act "
           "(roll the threatened leg) · **±15-35** = real but unconfirmed → wait · **near 0** = no edge.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# Chart — 2H candles + anchored VWAP + state marks + RSI + 4-score reads
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("2H candles since the cycle anchor — signals drawn on",
                  "Blue line = **anchored VWAP** (resets each post-expiry Wednesday) · "
                  "▲ bounce brewing · ★ uptrend ride · ▼ downtrend defend-PUT · ▽ topping defend-CALL")

x = [t.strftime("%d-%b %H:%M") for t in df.index]
fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                    row_heights=[0.58, 0.20, 0.22])

# Bollinger band
fig.add_trace(go.Scatter(x=x, y=df["bb_upper"], mode="lines", line=dict(width=0),
                         hoverinfo="skip", showlegend=False), row=1, col=1)
fig.add_trace(go.Scatter(x=x, y=df["bb_lower"], mode="lines", line=dict(width=0),
                         fill="tonexty", fillcolor="rgba(100,116,139,0.10)",
                         name="Bollinger band", hoverinfo="skip"), row=1, col=1)
# Stretch band (anchored): VWAP ± weekly-EM × STRETCH_EM_FRAC × 2
_sf = getattr(ic, "STRETCH_EM_FRAC", 0.3)
_band = expected_move_pts * _sf * 2.0
if _band:
    for sgn in (1, -1):
        fig.add_trace(go.Scatter(x=x, y=df["vwap"] + sgn * _band, mode="lines",
                                 line=dict(color="#f59e0b", width=0.8, dash="dot"),
                                 name="Stretch band" if sgn == 1 else None,
                                 showlegend=(sgn == 1), hoverinfo="skip"), row=1, col=1)
fig.add_trace(go.Candlestick(x=x, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
                             name="Nifty 2H (future)", increasing_line_color="#16a34a",
                             decreasing_line_color="#dc2626", showlegend=False), row=1, col=1)
fig.add_trace(go.Scatter(x=x, y=df["vwap"], mode="lines", name="Anchored VWAP",
                         line=dict(color="#2563eb", width=1.6)), row=1, col=1)

flip = gex.get("flip_level")
if flip:
    fig.add_hline(y=flip, line=dict(color="#7c3aed", width=1.5, dash="dash"),
                  annotation_text=f"Gamma flip {flip:,.0f}", annotation_position="top left",
                  annotation_font=dict(size=14, color="#7c3aed"),
                  annotation_bgcolor="rgba(255,255,255,0.88)", row=1, col=1)

_MARKER_SPECS = [
    ("brewing",   "low",  0.998, "triangle-up",        "#16a34a", "#065f46", "Bounce brewing"),
    ("uptrend",   "low",  0.996, "star-triangle-up",   "#0ea5e9", "#075985", "Uptrend — ride it"),
    ("downtrend", "high", 1.002, "triangle-down",      "#dc2626", "#7f1d1d", "Downtrend — defend PUT"),
    ("topping",   "high", 1.004, "triangle-down-open", "#f59e0b", "#92400e", "Topping — defend CALL"),
]
for key, anchor, mult, sym, fill, edge, label in _MARKER_SPECS:
    md = markers.get(key)
    if md is None or md.empty:
        continue
    fig.add_trace(go.Scatter(x=[t.strftime("%d-%b %H:%M") for t in md.index], y=md[anchor] * mult,
                  mode="markers", name=label,
                  marker=dict(symbol=sym, size=13, color=fill, line=dict(width=1, color=edge))),
                  row=1, col=1)

# RSI
fig.add_trace(go.Scatter(x=x, y=df["rsi"], mode="lines", name="RSI",
                         line=dict(color="#8b5cf6", width=1.1)), row=2, col=1)
for yv in (30, 50, 70):
    fig.add_hline(y=yv, line=dict(color="#cbd5e1", width=0.7,
                  dash="dot" if yv == 50 else "dash"), row=2, col=1)
fig.update_yaxes(title_text="RSI", range=[0, 100], row=2, col=1)

# Reads — 4 raw scores
fig.add_trace(go.Scatter(x=x, y=df["reversal_score"], mode="lines", name="Reversal (bounce brewing)",
                         line=dict(color="#16a34a", width=1.3)), row=3, col=1)
fig.add_trace(go.Scatter(x=x, y=df["uptrend_score"], mode="lines", name="Uptrend (ride it)",
                         line=dict(color="#0ea5e9", width=1.3, dash="dash")), row=3, col=1)
fig.add_trace(go.Scatter(x=x, y=df["downtrend_score"], mode="lines", name="Downtrend (defend PUT)",
                         line=dict(color="#dc2626", width=1.3)), row=3, col=1)
fig.add_trace(go.Scatter(x=x, y=df["topping_score"], mode="lines", name="Topping (defend CALL)",
                         line=dict(color="#f59e0b", width=1.3, dash="dash")), row=3, col=1)
fig.add_trace(go.Scatter(x=x, y=df["confidence"], mode="lines", name="Signal agreement %",
                         line=dict(color="#a855f7", width=1.0, dash="dot")), row=3, col=1)
for yv in (55, 60):
    fig.add_hline(y=yv, line=dict(color="#cbd5e1", width=0.7, dash="dot"), row=3, col=1)
fig.update_yaxes(title_text="raw scores / agree", range=[0, 100], row=3, col=1)

fig.update_layout(height=860, margin=dict(l=10, r=10, t=30, b=10),
                  xaxis_rangeslider_visible=False, plot_bgcolor="white", font=dict(size=14),
                  legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0, font=dict(size=13)),
                  hovermode="x unified")
fig.update_annotations(font_size=14)
step = max(1, len(x) // 16)
fig.update_xaxes(tickmode="array", tickvals=x[::step], tickangle=-40, showgrid=True, gridcolor="#eef2f7")
fig.update_yaxes(showgrid=True, gridcolor="#eef2f7")
# headroom so the unified hover box (top-anchored) clears the candles
_ph = [float(df["low"].min()), float(df["high"].max())]
for _lv in (flip, gex.get("call_wall"), gex.get("put_wall")):
    if isinstance(_lv, (int, float)):
        _ph.append(float(_lv))
_lo_p, _hi_p = min(_ph), max(_ph)
_rng_p = (_hi_p - _lo_p) or 1.0
fig.update_yaxes(range=[_lo_p - 0.04 * _rng_p, _hi_p + 0.22 * _rng_p], row=1, col=1)
st.plotly_chart(fig, use_container_width=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# Behind the scenes — every calculation, 2H candle by candle (always on)
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("🔬 Behind the scenes — every calculation, 2H candle by candle",
                  "Always on · newest candle first · column key in the expander below the table")
_gmap = {}
try:
    from data.gamma_history import load_daily_history
    _gmap = {r.get("date"): r.get("regime") for r in load_daily_history() if r.get("date")}
except Exception:
    pass
if gex.get("regime") in ("POSITIVE", "NEGATIVE"):
    _gmap[pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d")] = gex.get("regime")

ct = ic.candle_table(df, newest_first=True, gamma_by_date=_gmap)
if ct.empty:
    st.info("No candles to show.")
else:
    st.dataframe(uict.style_candle_table(ct), use_container_width=True, height=520, hide_index=True)
    with st.expander("📋 Column key — what each column & colour means"):
        st.markdown(uict.column_key_md(vwap_label="anchored VWAP"))

st.caption("Notes: 2H candles are resampled from near-month **futures** 60-min (real volume). "
           "VWAP is **anchored** to each weekly cycle (post-expiry Wednesday / Thursday on a holiday), "
           "so ΔVWAP and Stretch read against fair value *since the position opened*. Breadth is omitted "
           "on this timeframe. Gamma is a today-only snapshot. These shift the odds; not a guarantee.")
