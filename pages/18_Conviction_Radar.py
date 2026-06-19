# pages/18_Conviction_Radar.py
# Conviction Radar — "Be patient or get out?" in plain English, drawn on the chart.
#
# Answers two questions a trader actually asks:
#   1. The market is falling and I'm under water — book the loss now, or wait?
#   2. Yesterday closed with a late bounce — can I trust it, or is it a trap?
#
# Everything complicated (dealer gamma, VWAP, momentum divergence, volume delta,
# breadth) is computed inside the analytics modules. This page shows only the
# plain verdict + an annotated candle chart so you can SEE how the signals would
# have behaved over the last ~7 days.

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import ui.components as ui
from page_utils import bootstrap_signals, show_page_header
from data.live_fetcher import (
    get_nifty_fut_intraday, get_nifty_intraday, get_nifty50_intraday,
    get_india_vix, get_dual_expiry_chains,
)
from analytics.gamma_exposure import compute_gex
from analytics import intraday_conviction as ic

st.set_page_config(page_title="P18 · Conviction Radar", layout="wide")
st.title("Page 18 — Conviction Radar")
st.caption("Plain-English answer to: *be patient on this fall, or get out?* · "
           "and *was yesterday's late bounce trustworthy?*")

sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)

# Be LOUD about a missing spot rather than silently faking a price.
if spot <= 0:
    spot = float(sig.get("spot", 0))
if spot <= 0:
    st.error("⚠️ Live Nifty spot is unavailable from Kite right now (login/market-data issue). "
             "Gamma levels need a real spot — refresh after logging in. Showing nothing rather "
             "than guessing a price.")
    st.stop()

# ── Controls ──────────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    interval_label = st.selectbox("Candle size", ["15 min", "5 min"], index=0)
    interval = "15minute" if interval_label == "15 min" else "5minute"
with c2:
    days = st.slider("Trading days shown", 3, 10, 7)
with c3:
    use_breadth = st.checkbox("Include Nifty-50 breadth (heavier first load ~20s)", value=True)

# ── Data ──────────────────────────────────────────────────────────────────────
# Candles come from the near-month FUTURE (real volume; the index reports 0).
with st.spinner("Loading intraday data…"):
    df_idx = get_nifty_fut_intraday(interval=interval, days=days)
    used_index_fallback = False
    if df_idx is None or df_idx.empty:
        df_idx = get_nifty_intraday(interval=interval, days=days)   # index fallback (no volume)
        used_index_fallback = not (df_idx is None or df_idx.empty)
    vix = get_india_vix() or 0.0
    chains = get_dual_expiry_chains(spot)

if df_idx is None or df_idx.empty:
    st.error("Could not load Nifty intraday data from Kite. Check login / market data, then refresh.")
    st.stop()

if used_index_fallback:
    st.warning("⚠️ Could not load Nifty futures — using the index instead. The index has no volume, "
               "so VWAP is a price-only proxy and the volume-delta read is disabled. Signals are weaker. "
               "Refresh once futures data is available.")

# Expected one-day move from VIX (same convention as the EMA-Ribbon DTB logic).
if vix > 0:
    expected_move_pts = spot * (vix / 100.0) / 16.0
else:
    expected_move_pts = spot * 0.006      # ~0.6% fallback when VIX is unavailable
    st.info("ℹ️ India VIX unavailable — using a 0.6% fallback for the 'expected move'. "
            "The 'stretch' read is approximate until VIX returns.")

# Breadth (optional).
breadth = pd.Series(dtype=float)
if use_breadth:
    with st.spinner("Building Nifty-50 breadth…"):
        stock_dfs = get_nifty50_intraday(interval=interval, days=days)
        breadth = ic.breadth_series(stock_dfs)

# Gamma regime from the near-expiry chain (most gamma sits here).
near_df = chains.get("near", pd.DataFrame())
near_dte = chains.get("near_dte", 7)
atm_iv = float(sig.get("atm_iv", 12.0) or 12.0)
if near_df is None or near_df.empty:
    st.warning("⚠️ Option chain unavailable — the dealer-gamma 'market mode' and flip line can't be "
               "computed right now. The price/volume/breadth signals below still work.")
gex = compute_gex(near_df, spot, near_dte, iv_fallback_pct=atm_iv)

# Per-candle enrichment + verdicts.
df = ic.enrich(df_idx, expected_move_pts=expected_move_pts,
               breadth=breadth if not breadth.empty else None)
verdict = ic.live_verdict(df, gex["regime"], gex.get("spot_vs_flip_pts"))
markers = ic.transition_markers(df)
cc = ic.close_conviction(df_idx, breadth=breadth if not breadth.empty else None)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — The plain-English verdict (top of page)
# ══════════════════════════════════════════════════════════════════════════════

def _card(title, body, color, sub=""):
    st.markdown(
        f"<div style='background:{color}15;border-left:6px solid {color};"
        f"border-radius:8px;padding:14px 16px;height:100%;'>"
        f"<div style='font-size:12px;font-weight:800;letter-spacing:.5px;"
        f"color:{color};text-transform:uppercase;'>{title}</div>"
        f"<div style='font-size:15px;font-weight:700;color:#0f172a;margin:6px 0;'>{body}</div>"
        f"<div style='font-size:12px;color:#475569;line-height:1.5;'>{sub}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

cL, cR = st.columns(2)
with cL:
    _card(f"Right now · {verdict['badge']}", verdict["headline"],
          verdict["color"], verdict.get("detail", ""))
with cR:
    g_color = "#10b981" if gex["regime"] == "POSITIVE" else \
              "#ef4444" if gex["regime"] == "NEGATIVE" else "#64748b"
    _card("Market mode (dealer gamma)", gex["gex_headline"], g_color,
          gex["gex_body"] + "<br><br><b>" + gex["gex_flip_line"] + "</b>")

st.markdown("")
m1, m2, m3, m4 = st.columns(4)
with m1:
    ui.metric_card("REVERSAL READ", f"{verdict.get('reversal_score', 0)}/100",
                   sub="Higher = bounce more likely (be patient)",
                   color="green" if verdict.get("reversal_score", 0) >= 60 else "default")
with m2:
    ui.metric_card("TREND READ", f"{verdict.get('trend_score', 0)}/100",
                   sub="Higher = real trend (defend now)",
                   color="red" if verdict.get("trend_score", 0) >= 60 else "default")
with m3:
    flip = gex.get("flip_level")
    ui.metric_card("GAMMA FLIP LINE", f"{flip:,.0f}" if flip else "—",
                   sub=(f"Spot {gex['spot_vs_flip_pts']:+,} pts vs line"
                        if gex.get("spot_vs_flip_pts") is not None else "near-the-money"),
                   color="green" if (gex.get("spot_vs_flip_pts") or 0) >= 0 else "red")
with m4:
    ui.metric_card("EXPECTED MOVE TODAY", f"±{expected_move_pts:,.0f}" if expected_move_pts else "—",
                   sub=f"From VIX {vix:.1f} — used for 'stretch'", color="default")

with st.expander("⏱ How far ahead does this actually see? (read me once)"):
    st.markdown(
        f"This is an **early-warning / context** tool, not a crystal ball that says 'price reverses in "
        f"exactly 10 minutes'. Be realistic about what it gives you:\n"
        f"- **Updates once per candle** — every **{interval_label}**. So a fresh read lands at each candle "
        f"close, not continuously. Use 5-min for faster (noisier) reads, 15-min for steadier ones.\n"
        f"- **The genuinely *leading* parts** are the **divergences** (momentum/volume stop confirming the "
        f"price low *before* it turns) and the **gamma flip line** (known in advance — it tells you the "
        f"*environment* before the move happens). These typically warn **1–3 candles early**.\n"
        f"- **Before the close:** the 🔴 LIVE row in the daily-close table grades *today* as it forms, so in "
        f"the **last 45–60 min** you get a pre-close 'is this bounce trustworthy?' read while you can still act.\n"
        f"- It **shifts the odds** in your favour and stops panic-decisions at the exact wrong moment — it "
        f"does **not** guarantee the turn. Always keep your hard stop."
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — The annotated chart
# ══════════════════════════════════════════════════════════════════════════════

ui.section_header("Last %d sessions — with the signals drawn on" % days,
                  "▲ green = 'bounce brewing, be patient'  ·  ▼ red = 'real trend, defend'  ·  "
                  "blue line = VWAP (fair price)  ·  dashed = gamma flip line")

# X as category strings to avoid overnight gaps in the candles.
x = [t.strftime("%d-%b %H:%M") for t in df.index]

rows = 3 if (not breadth.empty and df["breadth"].notna().any()) else 2
heights = [0.62, 0.20, 0.18] if rows == 3 else [0.74, 0.26]
fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                    row_heights=heights)

# Row 1 — candles + VWAP + flip + walls + markers
candle_name = "Nifty index" if used_index_fallback else "Nifty (near-month future)"
fig.add_trace(go.Candlestick(
    x=x, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
    name=candle_name, increasing_line_color="#16a34a", decreasing_line_color="#dc2626",
    showlegend=False), row=1, col=1)

fig.add_trace(go.Scatter(x=x, y=df["vwap"], mode="lines", name="VWAP (fair price)",
                         line=dict(color="#2563eb", width=1.4)), row=1, col=1)

flip = gex.get("flip_level")
if flip:
    fig.add_hline(y=flip, line=dict(color="#7c3aed", width=1.3, dash="dash"),
                  annotation_text=f"Gamma flip {flip:,.0f}", annotation_position="top left",
                  row=1, col=1)
for wall, col, lbl in [(gex.get("call_wall"), "#ef4444", "Call wall"),
                       (gex.get("put_wall"), "#10b981", "Put wall")]:
    if wall:
        fig.add_hline(y=wall, line=dict(color=col, width=1, dash="dot"),
                      annotation_text=lbl, annotation_position="bottom left",
                      row=1, col=1)

pat = markers["patience"]
if not pat.empty:
    fig.add_trace(go.Scatter(
        x=[t.strftime("%d-%b %H:%M") for t in pat.index], y=pat["low"] * 0.9985,
        mode="markers", name="Be patient (bounce brewing)",
        marker=dict(symbol="triangle-up", size=12, color="#16a34a",
                    line=dict(width=1, color="#065f46"))), row=1, col=1)
trd = markers["trend"]
if not trd.empty:
    fig.add_trace(go.Scatter(
        x=[t.strftime("%d-%b %H:%M") for t in trd.index], y=trd["high"] * 1.0015,
        mode="markers", name="Defend (real trend)",
        marker=dict(symbol="triangle-down", size=12, color="#dc2626",
                    line=dict(width=1, color="#7f1d1d"))), row=1, col=1)

# Row 2 — the two reads (reversal vs trend)
fig.add_trace(go.Scatter(x=x, y=df["reversal_score"], mode="lines",
                         name="Reversal read", line=dict(color="#16a34a", width=1.2)),
              row=2, col=1)
fig.add_trace(go.Scatter(x=x, y=df["trend_score"], mode="lines",
                         name="Trend read", line=dict(color="#dc2626", width=1.2)),
              row=2, col=1)
fig.add_hline(y=60, line=dict(color="#94a3b8", width=0.8, dash="dot"), row=2, col=1)
fig.update_yaxes(title_text="reads 0-100", range=[0, 100], row=2, col=1)

# Row 3 — breadth (optional)
if rows == 3:
    fig.add_trace(go.Scatter(x=x, y=df["breadth"], mode="lines",
                             name="% Nifty-50 above VWAP",
                             line=dict(color="#0891b2", width=1.2)), row=3, col=1)
    fig.add_hline(y=50, line=dict(color="#94a3b8", width=0.8, dash="dot"), row=3, col=1)
    fig.update_yaxes(title_text="breadth %", range=[0, 100], row=3, col=1)

fig.update_layout(
    height=760, margin=dict(l=10, r=10, t=30, b=10),
    xaxis_rangeslider_visible=False, plot_bgcolor="white",
    legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
    hovermode="x unified",
)
# Thin out x labels so they're readable.
step = max(1, len(x) // 14)
fig.update_xaxes(tickmode="array", tickvals=x[::step], tickangle=-40,
                 showgrid=True, gridcolor="#eef2f7")
fig.update_yaxes(showgrid=True, gridcolor="#eef2f7")
st.plotly_chart(fig, use_container_width=True)

with st.expander("📖 What each thing on the chart means (plain English)"):
    st.markdown(
        "- **Blue VWAP line** — the day's *fair price*. Above it, buyers are winning; "
        "below it, sellers are. A fall that reclaims this line is the first real sign a bounce has legs.\n"
        "- **Green ▲ 'Be patient'** — at this candle the fall looked *tired*: stretched far from fair "
        "value, momentum no longer making new lows, and selling drying up. Booking a loss right here is "
        "usually the worst moment. Look right of each ▲ to see whether price bounced.\n"
        "- **Red ▼ 'Defend'** — the opposite: fresh lows with momentum, volume and breadth all agreeing. "
        "A real trend day — don't wait for a V-recovery.\n"
        "- **Purple dashed 'Gamma flip'** — today's line in the sand from option positioning. Above it the "
        "market tends to *mean-revert* (patience pays); below it, it tends to *trend* (be defensive).\n"
        "- **Lower panel reads** — the green 'reversal' line and red 'trend' line are the two scores; "
        "whichever is higher (and above 60) drives the marker.\n"
        "- **Breadth panel** — what % of the 50 biggest stocks are above their own fair price. A bounce on "
        "*low* breadth is narrow and fragile; a fall on *low* breadth is broad and real."
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Close Conviction: was each day's CLOSE trustworthy?
# ══════════════════════════════════════════════════════════════════════════════

ui.section_header("Daily close quality — could you trust the late-day move?",
                  "Built for exactly your case: a late bounce that closes weak = short-cover = gap risk")

if cc is None or cc.empty:
    st.info("Not enough intraday history to grade daily closes.")
else:
    today_ist = pd.Timestamp.now(tz="Asia/Kolkata").date()
    GRADE_COLOR = {"HIGH": "#16a34a", "MEDIUM": "#d97706", "LOW": "#dc2626"}
    for _, r in cc.sort_values("date", ascending=False).iterrows():
        col = GRADE_COLOR.get(r["grade"], "#64748b")
        bounce_txt = "late bounce" if r["late_bounce"] else "no late bounce"
        vwap_txt = "closed ABOVE fair value" if r["above_vwap"] else "closed BELOW fair value"
        extra = f" · {r['note']}" if r["note"] else ""
        is_today = r["date"] == today_ist
        day_label = f"{r['date']} 🔴 LIVE" if is_today else str(r["date"])
        live_hint = (" <i>(in progress — firms up toward 3:30)</i>" if is_today else "")
        st.markdown(
            f"<div style='display:flex;gap:14px;align-items:center;padding:8px 12px;"
            f"border-left:5px solid {col};background:{col}10;border-radius:6px;margin-bottom:6px;'>"
            f"<div style='font-weight:800;color:{col};min-width:70px;'>{r['grade']}</div>"
            f"<div style='min-width:130px;color:#0f172a;font-weight:600;'>{day_label}</div>"
            f"<div style='min-width:80px;color:#334155;'>close {r['close']:,}</div>"
            f"<div style='color:#475569;font-size:13px;'>"
            f"closed {r['close_location']}% up the day's range · {vwap_txt} · {bounce_txt}{extra}{live_hint}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    st.caption("Reading: a **LOW** grade after a late bounce is the warning you were missing — "
               "it usually means the bounce was a short-cover into the close and the next session gaps against it. "
               "The **🔴 LIVE** row grades *today's* close as it forms, so in the last hour you get a pre-close read.")

# ── Gamma walls detail (optional deep-dive) ───────────────────────────────────
with st.expander("🔎 Where the gamma walls sit (option positioning detail)"):
    prof = gex.get("profile")
    if prof is None or prof.empty:
        st.info("Option chain not available.")
    else:
        bar = go.Figure()
        bar.add_trace(go.Bar(x=prof.index, y=prof["gex_net"],
                             marker_color=np.where(prof["gex_net"] >= 0, "#16a34a", "#dc2626"),
                             name="Net dealer gamma"))
        if flip:
            bar.add_vline(x=flip, line=dict(color="#7c3aed", dash="dash"),
                          annotation_text="flip")
        bar.add_vline(x=spot, line=dict(color="#2563eb", dash="dot"),
                      annotation_text="spot")
        bar.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                          plot_bgcolor="white", showlegend=False,
                          xaxis_title="strike", yaxis_title="net dealer gamma (relative)")
        st.plotly_chart(bar, use_container_width=True)
        st.caption("Green bars = strikes where dealers DAMP moves (price gets pinned / pulled back). "
                   "Red bars = strikes where dealers AMPLIFY moves. The flip is where green turns to red.")

st.caption("Notes: Candles are the near-month **future** (real volume); the gamma flip/walls are on the "
           "**spot** option chain, so they sit a few points off the futures price (basis) — read them as "
           "zones, not to-the-point levels. Gamma regime is a today-only snapshot (option open-interest "
           "isn't available for past days), so the ▲/▼ chart marks come from price, momentum, volume and "
           "breadth — things we can measure on every past candle — while the flip line gives today's "
           "structural context. These shift the odds; they are not a guarantee.")
