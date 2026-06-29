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

# Streamlit Cloud hot-reloads this page on each git push but keeps already-imported
# modules cached in memory, so a freshly-pushed engine can lag the page and crash
# (e.g. the page styles a column the stale candle_table hasn't produced yet). Force a
# reload of the per-candle engine so the page always runs against current code — no
# manual "Reboot app" needed after a deploy. (Pure-function module → reload is safe.)
import importlib
try:
    importlib.reload(ic)
except Exception:
    pass

st.set_page_config(page_title="P18 · Conviction Radar", layout="wide")
st.title("Page 18 — Conviction Radar")
st.caption("Plain-English answer to: *be patient on this fall, or get out?* · "
           "and *was yesterday's late bounce trustworthy?*")

sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)

# ── Full reference (split into 4 parts under docs/, shown as tabs) ─────────────
with st.expander("📚 How to read this page — full reference (overview · calculations ×3 · "
                 "two-sided & gamma · playbook)"):
    from pathlib import Path as _Path
    _docs = _Path(__file__).resolve().parent.parent / "docs"
    _parts = [
        ("① Overview & glossary", "PAGE_18_PART_1_OVERVIEW.md"),
        ("②a Data & indicators", "PAGE_18_PART_2A_INDICATORS.md"),
        ("②b Scores & states", "PAGE_18_PART_2B_SCORES.md"),
        ("②c Confluence & table", "PAGE_18_PART_2C_CONFLUENCE_TABLE.md"),
        ("③ Two-sided · gamma · close", "PAGE_18_PART_3_TWO_SIDED_AND_GAMMA.md"),
        ("④ How to act", "PAGE_18_PART_4_PLAYBOOK.md"),
    ]
    for _tab, (_, _fname) in zip(st.tabs([t for t, _ in _parts]), _parts):
        with _tab:
            _p = _docs / _fname
            if _p.exists():
                st.markdown(_p.read_text(encoding="utf-8"))
            else:
                # Fall back to the legacy single-file reference if the parts aren't deployed yet.
                _legacy = _docs / "PAGE_18_CONVICTION_RADAR.md"
                st.info(f"Reference part `{_fname}` not found." +
                        ("" if not _legacy.exists() else " Showing the combined legacy reference below.") )
                if _legacy.exists():
                    st.markdown(_legacy.read_text(encoding="utf-8"))

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

# Log a forward gamma history — daily snapshots come from the EOD job; here we append
# an intraday point each load so the flip line's migration through TODAY is recorded
# (Kite has no historical OI, so gamma can only be accumulated going forward).
try:
    from data.gamma_history import log_intraday_snapshot
    log_intraday_snapshot(gex, spot)
except Exception:
    pass

# Per-candle enrichment + verdicts.
df = ic.enrich(df_idx, expected_move_pts=expected_move_pts,
               breadth=breadth if not breadth.empty else None)

# Safety net: if the app was just updated, Streamlit may still hold an OLD cached
# engine module in memory while running the NEW page. Detect the mismatch — either
# missing DataFrame columns OR a new engine function the stale module lacks — and
# ask for a clean refresh instead of crashing with a raw KeyError / AttributeError.
_REQUIRED = {"bull_read", "bear_read", "state", "vwap", "above_vwap", "confidence", "conflict"}
_REQUIRED_FUNCS = ("two_sided_verdict", "candle_table")
_stale = (df.empty or not _REQUIRED.issubset(df.columns)
          or any(not hasattr(ic, _fn) for _fn in _REQUIRED_FUNCS))
if _stale:
    st.warning("🔄 The app was just updated and Streamlit is still holding the **older engine** in "
               "memory. A page refresh alone won't clear it — open the app menu (top-right ⋮) and "
               "choose **Reboot app** once. After it restarts, this page loads the new two-sided "
               "engine cleanly.")
    st.stop()

verdict = ic.live_verdict(df, gex["regime"], gex.get("spot_vs_flip_pts"))
two_sided = ic.two_sided_verdict(df, gex.get("regime", "UNKNOWN"), gex.get("spot_vs_flip_pts"))
markers = ic.transition_markers(df)
scorecard = ic.pillar_scorecard(df.iloc[-1], gex.get("regime", "UNKNOWN"), gex.get("spot_vs_flip_pts"))
cc = ic.close_conviction(df_idx, breadth=breadth if not breadth.empty else None)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — The plain-English verdict (top of page)
# ══════════════════════════════════════════════════════════════════════════════

def _card(title, body, color, sub=""):
    st.markdown(
        f"<div style='background:{color}15;border-left:6px solid {color};"
        f"border-radius:8px;padding:14px 16px;height:100%;'>"
        f"<div style='font-size:15px;font-weight:800;letter-spacing:.5px;"
        f"color:{color};text-transform:uppercase;'>{title}</div>"
        f"<div style='font-size:18px;font-weight:700;color:#0f172a;margin:6px 0;'>{body}</div>"
        f"<div style='font-size:15px;color:#475569;line-height:1.5;'>{sub}</div>"
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
    ui.metric_card("BULL READ", f"{verdict.get('bull_read', 0)}/100",
                   sub="Case for staying/long (ride or be patient)",
                   color="green" if verdict.get("bull_read", 0) >= 55 else "default")
with m2:
    ui.metric_card("BEAR READ", f"{verdict.get('bear_read', 0)}/100",
                   sub="Case for defending (downtrend or topping)",
                   color="red" if verdict.get("bear_read", 0) >= 55 else "default")
with m3:
    flip = gex.get("flip_level")
    ui.metric_card("GAMMA FLIP LINE", f"{flip:,.0f}" if flip else "—",
                   sub=(f"Spot {gex['spot_vs_flip_pts']:+,} pts vs line"
                        if gex.get("spot_vs_flip_pts") is not None else "near-the-money"),
                   color="green" if (gex.get("spot_vs_flip_pts") or 0) >= 0 else "red")
with m4:
    _conf = verdict.get("confidence", 0)
    _agree = verdict.get("agree", 0)
    _oppose = verdict.get("oppose", 0)
    ui.metric_card("SIGNAL AGREEMENT", f"{_conf}%",
                   sub=f"{_agree} signals agree · {_oppose} fight — higher = more trustworthy",
                   color="green" if _conf >= 67 else "red" if verdict.get("conflict") else "amber")

# ── Two-sided read — BOTH condor legs are live, so show BOTH cases at once ─────
ui.section_header("Both sides, right now (your condor has a sold-PUT *and* a sold-CALL)",
                  "Bull case · Bear case · and their Net — the single directional conviction")

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

def _final_card(final, gnote=""):
    # Trust-adjusted conviction: Bull−Bear discounted by signal agreement AND tilted by
    # today's dealer gamma. Full spectrum, both sides.
    if final >= 35:
        color, label = "#15803d", "STRONG BULL — act (stay / roll PUT up)"
    elif final >= 15:
        color, label = "#16a34a", "Mild bull — real but unconfirmed, wait"
    elif final > -15:
        color, label = "#64748b", "No edge — stand aside"
    elif final > -35:
        color, label = "#dc2626", "Mild bear — caution on the threatened leg"
    else:
        color, label = "#b91c1c", "STRONG BEAR — defend (leg / sell-CALL)"
    _mini_card("🎯 FINAL CONVICTION", final, color, label,
               "Bull−Bear × signal-agreement × today's gamma — the headline number. "
               "±35 agreed = act-worthy; near 0 = no edge."
               + (f"<br><span style='color:#64748b;'>↳ {gnote}</span>" if gnote else ""))

def _net_card(net):
    if net > 8:
        color, lean = "#16a34a", "Bull case ahead"
    elif net < -8:
        color, lean = "#dc2626", "Bear case ahead"
    else:
        color, lean = "#64748b", "Balanced"
    _mini_card("⚖️ BULL − BEAR (raw)", net, color, lean,
               "bull-read − bear-read before the agreement discount — the raw lean of the "
               "two case scores. The Final card discounts this by Conf%.")

_net_val = int(two_sided["bull"].get("score", 0)) - int(two_sided["bear"].get("score", 0))
_conf_now = int(verdict.get("confidence", 0))
# Today's dealer-gamma tilt on the LIVE Final card (gamma is real only for today):
# cushioned regime backs the bull case, accelerator backs the bear case.
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
bc, kc, nc, fc = st.columns(4)
with bc:
    _side_card(two_sided["bull"], "bull")
with kc:
    _side_card(two_sided["bear"], "bear")
with nc:
    _net_card(_net_val)
with fc:
    _final_card(_final_val, _gnote)
st.caption("**Reading the Final conviction (both ways):** "
           "**+35 or more** = strong, agreed, regime-backed *bull* → act (stay / roll the sold-PUT up) · "
           "**+15…+35** = real but unconfirmed bull → wait for a clean state · "
           "**−15…+15** = no edge → stand aside · "
           "**−15…−35** = real but unconfirmed *bear* → caution, watch the threatened leg · "
           "**−35 or less** = strong, agreed *bear* → defend (manage the leg / sell-CALL). "
           "The **live Final card** = Bull−Bear × Conf% × today's gamma tilt (×1.15 if gamma backs the "
           "direction, ×0.85 if it fights it); the table `Final` column omits gamma since it can't be "
           "applied to past candles.")

# ── Conflict scorecard — exactly which signals agree vs fight right now ────────
ui.section_header("Do the signals agree? (so you don't enter a move that won't follow through)",
                  "Each pillar votes; a continuation call is only trusted when they line up")
sc_cols = st.columns(len(scorecard))
for col, c in zip(sc_cols, scorecard):
    if c["agrees"] is True:
        mark, mc = "✅ agrees", "#16a34a"
    elif c["agrees"] is False:
        mark, mc = "❌ fights", "#dc2626"
    else:
        mark, mc = "• flat", "#64748b"
    with col:
        st.markdown(
            f"<div style='border:1px solid {mc}55;border-radius:8px;padding:8px 10px;text-align:center;'>"
            f"<div style='font-size:14px;font-weight:700;color:#334155;'>{c['pillar']}</div>"
            f"<div style='font-size:15px;color:#475569;margin:4px 0;min-height:40px;'>{c['read']}</div>"
            f"<div style='font-size:15px;font-weight:800;color:{mc};'>{mark}</div>"
            f"</div>", unsafe_allow_html=True)
if verdict.get("conflict"):
    st.caption("⚠️ The signals are **conflicted** — this is the kind of move that often fizzles. "
               "The engine is withholding any 'ride it / defend' continuation call until they line up.")

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
                  "▲ green = bounce brewing · ★ blue = uptrend, ride it (bounce continuing) · "
                  "▼ red = downtrend, defend PUT · ▽ amber = topping, defend CALL · "
                  "blue line = VWAP · dashed = gamma flip")

# X as category strings to avoid overnight gaps in the candles.
x = [t.strftime("%d-%b %H:%M") for t in df.index]

has_breadth = (not breadth.empty and df["breadth"].notna().any())
rows = 4 if has_breadth else 3
heights = [0.50, 0.16, 0.18, 0.16] if has_breadth else [0.58, 0.20, 0.22]
fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.025,
                    row_heights=heights)

# Row 1 — candles + VWAP + Bollinger band + expected-move envelope + flip + walls + markers
candle_name = "Nifty index" if used_index_fallback else "Nifty (near-month future)"

# Bollinger band shading (visualises %B / how stretched price is)
fig.add_trace(go.Scatter(x=x, y=df["bb_upper"], mode="lines", line=dict(width=0),
                         hoverinfo="skip", showlegend=False), row=1, col=1)
fig.add_trace(go.Scatter(x=x, y=df["bb_lower"], mode="lines", line=dict(width=0),
                         fill="tonexty", fillcolor="rgba(100,116,139,0.10)",
                         name="Bollinger band", hoverinfo="skip"), row=1, col=1)

# Stretch envelope around fair value. The full-day VIX move is too wide for an intraday
# read, so we draw the band at the over-extension line the engine actually uses: VWAP ±
# (EM × STRETCH_EM_FRAC × 2) = the point where the Stretch score maxes out (≈0.6× a daily
# move). Candles poking outside it are genuinely over-stretched (mean-revert zone).
_stretch_frac = getattr(ic, "STRETCH_EM_FRAC", 0.3)
band_pts = expected_move_pts * _stretch_frac * 2.0
if band_pts:
    for sgn in (1, -1):
        fig.add_trace(go.Scatter(x=x, y=df["vwap"] + sgn * band_pts, mode="lines",
                                 line=dict(color="#f59e0b", width=0.8, dash="dot"),
                                 name="Stretch band (over-extended)" if sgn == 1 else None,
                                 showlegend=(sgn == 1), hoverinfo="skip"), row=1, col=1)

fig.add_trace(go.Candlestick(
    x=x, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
    name=candle_name, increasing_line_color="#16a34a", decreasing_line_color="#dc2626",
    showlegend=False), row=1, col=1)

fig.add_trace(go.Scatter(x=x, y=df["vwap"], mode="lines", name="VWAP (fair price)",
                         line=dict(color="#2563eb", width=1.4)), row=1, col=1)

flip = gex.get("flip_level")
if flip:
    fig.add_hline(y=flip, line=dict(color="#7c3aed", width=1.5, dash="dash"),
                  annotation_text=f"Gamma flip {flip:,.0f}", annotation_position="top left",
                  annotation_font=dict(size=15, color="#7c3aed"),
                  annotation_bgcolor="rgba(255,255,255,0.88)", annotation_borderpad=3,
                  row=1, col=1)
# Separate corners + white background boxes so labels never sit unreadable on candles.
for wall, col, lbl, pos in [(gex.get("call_wall"), "#ef4444", "Call wall", "top right"),
                            (gex.get("put_wall"), "#10b981", "Put wall", "bottom right")]:
    if wall:
        fig.add_hline(y=wall, line=dict(color=col, width=1.2, dash="dot"),
                      annotation_text=lbl, annotation_position=pos,
                      annotation_font=dict(size=15, color=col),
                      annotation_bgcolor="rgba(255,255,255,0.88)", annotation_borderpad=3,
                      row=1, col=1)

# Four marker types (drawn only when the state flips).
#   below candle = bullish-case markers · above candle = defend markers
_MARKER_SPECS = [
    ("brewing",   "low",  0.9985, "triangle-up",      "#16a34a", "#065f46", "Bounce brewing"),
    ("uptrend",   "low",  0.9970, "star-triangle-up", "#0ea5e9", "#075985", "Uptrend — ride it (bounce continuing)"),
    ("downtrend", "high", 1.0015, "triangle-down",    "#dc2626", "#7f1d1d", "Downtrend — defend PUT"),
    ("topping",   "high", 1.0030, "triangle-down-open", "#f59e0b", "#92400e", "Topping — defend CALL"),
]
for key, anchor, mult, sym, fill, edge, label in _MARKER_SPECS:
    md = markers.get(key)
    if md is None or md.empty:
        continue
    fig.add_trace(go.Scatter(
        x=[t.strftime("%d-%b %H:%M") for t in md.index], y=md[anchor] * mult,
        mode="markers", name=label,
        marker=dict(symbol=sym, size=13, color=fill, line=dict(width=1, color=edge))),
        row=1, col=1)

# Row 2 — RSI (momentum) with 30/70 lines + divergence markers (the leading tells)
fig.add_trace(go.Scatter(x=x, y=df["rsi"], mode="lines", name="RSI (momentum)",
                         line=dict(color="#8b5cf6", width=1.1)), row=2, col=1)
for yv in (30, 50, 70):
    fig.add_hline(y=yv, line=dict(color="#cbd5e1", width=0.7,
                  dash="dot" if yv == 50 else "dash"), row=2, col=1)
_bd = df[df["rsi_bull_div"]]
if not _bd.empty:
    fig.add_trace(go.Scatter(x=[t.strftime("%d-%b %H:%M") for t in _bd.index], y=_bd["rsi"],
                  mode="markers", name="Bullish RSI divergence",
                  marker=dict(symbol="circle", size=7, color="#16a34a")), row=2, col=1)
_rd = df[df["rsi_bear_div"]]
if not _rd.empty:
    fig.add_trace(go.Scatter(x=[t.strftime("%d-%b %H:%M") for t in _rd.index], y=_rd["rsi"],
                  mode="markers", name="Bearish RSI divergence",
                  marker=dict(symbol="circle", size=7, color="#dc2626")), row=2, col=1)
fig.update_yaxes(title_text="RSI", range=[0, 100], row=2, col=1)

# Row 3 — all FOUR raw scores (both sides of both regimes) + signal-agreement.
# Greens = the bull case (be-patient / ride); red+amber = the bear case (defend PUT / CALL).
fig.add_trace(go.Scatter(x=x, y=df["reversal_score"], mode="lines",
                         name="Reversal (bounce brewing)", line=dict(color="#16a34a", width=1.3)),
              row=3, col=1)
fig.add_trace(go.Scatter(x=x, y=df["uptrend_score"], mode="lines",
                         name="Uptrend (ride it)", line=dict(color="#0ea5e9", width=1.3, dash="dash")),
              row=3, col=1)
fig.add_trace(go.Scatter(x=x, y=df["downtrend_score"], mode="lines",
                         name="Downtrend (defend PUT)", line=dict(color="#dc2626", width=1.3)),
              row=3, col=1)
fig.add_trace(go.Scatter(x=x, y=df["topping_score"], mode="lines",
                         name="Topping (defend CALL)", line=dict(color="#f59e0b", width=1.3, dash="dash")),
              row=3, col=1)
fig.add_trace(go.Scatter(x=x, y=df["confidence"], mode="lines",
                         name="Signal agreement %", line=dict(color="#a855f7", width=1.0, dash="dot")),
              row=3, col=1)
# Trigger thresholds the engine uses to fire each state.
for yv, cc_ in ((55, "#94a3b8"), (60, "#cbd5e1")):
    fig.add_hline(y=yv, line=dict(color=cc_, width=0.7, dash="dot"), row=3, col=1)
fig.update_yaxes(title_text="raw scores / agree", range=[0, 100], row=3, col=1)

# Row 4 — breadth (optional)
if has_breadth:
    fig.add_trace(go.Scatter(x=x, y=df["breadth"], mode="lines",
                             name="% Nifty-50 above VWAP",
                             line=dict(color="#0891b2", width=1.2)), row=4, col=1)
    fig.add_hline(y=50, line=dict(color="#94a3b8", width=0.8, dash="dot"), row=4, col=1)
    fig.update_yaxes(title_text="breadth %", range=[0, 100], row=4, col=1)

fig.update_layout(
    height=980 if has_breadth else 860, margin=dict(l=10, r=10, t=30, b=10),
    xaxis_rangeslider_visible=False, plot_bgcolor="white",
    font=dict(size=15),                                  # +3pt global (ticks, titles, hover)
    legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0, font=dict(size=14)),
    hovermode="x unified",
)
fig.update_annotations(font_size=15)
# Thin out x labels so they're readable.
step = max(1, len(x) // 14)
fig.update_xaxes(tickmode="array", tickvals=x[::step], tickangle=-40,
                 showgrid=True, gridcolor="#eef2f7")
fig.update_yaxes(showgrid=True, gridcolor="#eef2f7")
# Headroom on the price panel: in x-unified mode the combined hover box anchors to the
# TOP of the panel, so giving the candles ~22% empty space above keeps the box off them.
_ph = [float(df["low"].min()), float(df["high"].max())]
for _lv in (flip, gex.get("call_wall"), gex.get("put_wall")):
    if isinstance(_lv, (int, float)):
        _ph.append(float(_lv))
_lo_p, _hi_p = min(_ph), max(_ph)
_rng_p = (_hi_p - _lo_p) or 1.0
fig.update_yaxes(range=[_lo_p - 0.04 * _rng_p, _hi_p + 0.22 * _rng_p], row=1, col=1)
st.plotly_chart(fig, use_container_width=True)

with st.expander("📖 What each thing on the chart means (plain English)"):
    st.markdown(
        "- **Blue VWAP line** — the day's *fair price*. Above it, buyers are winning; below it, sellers are. "
        "Reclaiming this line is the first real sign a bounce has legs.\n"
        "- **Green ▲ 'Bounce brewing'** — below fair value but the fall looks *tired* (stretched, momentum no "
        "longer making new lows, selling drying up). The early 'bounce brewing' nudge — a turn may be near.\n"
        "- **Blue ★ 'Uptrend — ride it'** — the bounce is now *confirmed continuing*: price reclaimed and is "
        "holding above fair value, making higher lows, with breadth and buyers (CVD) behind it. **This is the "
        "uptrend / stay-in-it signal.** Counter-trend red marks are suppressed while this is active.\n"
        "- **Red ▼ 'Downtrend — defend PUT'** — *persistent* below fair value (not a one-candle dip): fresh "
        "lows with momentum and breadth agreeing. A real trend down — don't wait for a V-recovery.\n"
        "- **Amber ▽ 'Topping — defend CALL'** — above fair value but the up-move looks exhausted (overbought, "
        "stretched, fewer stocks confirming the high). Watch your sold-CALL leg.\n"
        "- **Grey Bollinger band** — normal price envelope. Candles poking outside it = stretched (snap-back risk).\n"
        "- **Amber dotted 'Stretch band'** — fair value ± the over-extension line the engine uses "
        "(≈0.6× the full-day VIX move). It's intentionally tighter than the whole-day move so it tracks "
        "*intraday* extension: a candle beyond it is maximally stretched (Stretch score capped) and often "
        "mean-reverts.\n"
        "- **Purple dashed 'Gamma flip'** — today's line in the sand from option positioning. Above it the "
        "market tends to *mean-revert* (patience/continuation favoured); below it, it tends to *trend*.\n"
        "- **RSI panel** — momentum (0–100). The green/red dots are **divergences** (price makes a new "
        "low/high but momentum doesn't) — the *earliest* warning a move is tiring, usually 1–3 candles ahead.\n"
        "- **Reads panel** — all **four raw scores** plotted together so you see both sides at once: green "
        "**Reversal** (bounce brewing) and blue **Uptrend** (ride it) are the *bull* case; red **Downtrend** "
        "(defend PUT) and amber **Topping** (defend CALL) are the *bear* case. A marker on the candles fires "
        "when a line crosses its dotted threshold (55/60). The purple dotted **Signal-agreement %** shows how "
        "many pillars agree — when it dips, the pillars are fighting and continuation calls are withheld.\n"
        "- **Breadth panel** — % of the 50 biggest stocks above their own fair price. A bounce on *low* breadth "
        "is narrow and fragile; a fall on *low* breadth is broad and real."
    )

# ══════════════════════════════════════════════════════════════════════════════
# Behind the scenes — every per-candle calculation in one auditable table
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("🔬 Behind the scenes — every calculation, candle by candle",
                  "Always on · newest candle first · column key in the expander below the table")
with st.container():
    # Gamma-by-date map: stored daily regimes (past) + today's live regime → lets the
    # Final column fold in dealer gamma WHERE we have it; missing days stay un-tilted.
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
        import ui.conviction_table as _uict
        st.dataframe(_uict.style_candle_table(ct), use_container_width=True,
                     height=670, hide_index=True)
        with st.expander("📋 Column key — what each column & colour means"):
            st.markdown(_uict.column_key_md())

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
        # Score build-up so the grade is auditable (base 50 ± each factor).
        def _chip(lbl, val):
            if not val:
                return ""
            c = "#16a34a" if val > 0 else "#dc2626"
            return (f"<span style='font-size:13px;color:{c};background:{c}14;border-radius:4px;"
                    f"padding:1px 6px;margin-right:4px;white-space:nowrap;'>{lbl} {val:+d}</span>")
        breakdown = ("".join([
            "<span style='font-size:13px;color:#64748b;margin-right:4px;'>base 50</span>",
            _chip("VWAP", int(r.get("c_vwap", 0))),
            _chip("range", int(r.get("c_loc", 0))),
            _chip("short-cover", int(r.get("c_shortcover", 0))),
            _chip("breadth", int(r.get("c_breadth", 0))),
            f"<span style='font-size:13px;color:{col};font-weight:700;margin-left:2px;'>"
            f"= {int(r.get('score', 0))}/100</span>",
        ]))
        st.markdown(
            f"<div style='border-left:5px solid {col};background:{col}10;border-radius:6px;"
            f"margin-bottom:6px;padding:8px 12px;'>"
            f"<div style='display:flex;gap:14px;align-items:center;'>"
            f"<div style='font-size:16px;font-weight:800;color:{col};min-width:70px;'>{r['grade']}</div>"
            f"<div style='font-size:16px;min-width:130px;color:#0f172a;font-weight:600;'>{day_label}</div>"
            f"<div style='font-size:16px;min-width:80px;color:#334155;'>close {r['close']:,}</div>"
            f"<div style='color:#475569;font-size:16px;'>"
            f"closed {r['close_location']}% up the day's range · {vwap_txt} · {bounce_txt}{extra}{live_hint}</div>"
            f"</div>"
            f"<div style='margin-top:6px;'>{breakdown}</div>"
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
                          annotation_text="flip", annotation_font=dict(size=15),
                          annotation_bgcolor="rgba(255,255,255,0.88)")
        bar.add_vline(x=spot, line=dict(color="#2563eb", dash="dot"),
                      annotation_text="spot", annotation_font=dict(size=15),
                      annotation_bgcolor="rgba(255,255,255,0.88)")
        bar.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                          plot_bgcolor="white", showlegend=False, font=dict(size=15),
                          xaxis_title="strike", yaxis_title="net dealer gamma (relative)")
        st.plotly_chart(bar, use_container_width=True)
        st.caption("Green bars = strikes where dealers DAMP moves (price gets pinned / pulled back). "
                   "Red bars = strikes where dealers AMPLIFY moves. The flip is where green turns to red.")

# ══════════════════════════════════════════════════════════════════════════════
# Dealer-gamma history — accumulated forward (Kite has no historical OI)
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Dealer-gamma history (built forward — no back-fill possible)",
                  "Daily regime strip from the EOD job · today's flip-line migration from live loads")
try:
    from data.gamma_history import load_daily_history, load_intraday_today
    _g_daily = load_daily_history()
    _g_today = load_intraday_today()

    if not _g_daily and not _g_today:
        st.info("No gamma history yet. The EOD job logs one snapshot per trading day, and this page logs "
                "intraday points as you view it — both start accumulating from today. Days you don't log in "
                "(no Kite token) will show as gaps, never guessed.")
    else:
        # ── Daily regime strip — green = shock-absorber (POSITIVE), red = accelerator ──
        if _g_daily:
            _cells = ""
            for r in _g_daily[-30:]:
                _reg = r.get("regime", "UNKNOWN")
                _c = "#16a34a" if _reg == "POSITIVE" else "#dc2626" if _reg == "NEGATIVE" else "#cbd5e1"
                _flip = r.get("flip")
                _flip_s = f"{_flip:,.0f}" if isinstance(_flip, (int, float)) else "—"
                _d = str(r.get("date", ""))[5:]   # MM-DD
                _cells += (f"<div title='{r.get('date','')} · {_reg} · flip {_flip_s}' "
                           f"style='flex:1;min-width:34px;background:{_c};border-radius:4px;"
                           f"padding:6px 2px;text-align:center;'>"
                           f"<div style='color:#fff;font-size:9px;font-weight:700;'>{_d}</div>"
                           f"<div style='color:#fff;font-size:10px;font-weight:800;'>{_flip_s}</div></div>")
            st.markdown(
                f"<div style='display:flex;gap:3px;flex-wrap:wrap;margin-bottom:4px;'>{_cells}</div>",
                unsafe_allow_html=True)
            st.caption("🟢 shock-absorber (dips bought back · patience pays) · 🔴 accelerator "
                       "(moves snowball · defend) · grey/missing = no login that day. Number = gamma flip level.")
        else:
            st.caption("Daily history starts after the next EOD run.")

        # ── Today's intraday flip-line migration ──────────────────────────────
        if len(_g_today) >= 2:
            _ts = [p.get("time", "") for p in _g_today]
            _fl = [p.get("flip") for p in _g_today]
            _sp = [p.get("spot") for p in _g_today]
            gh = go.Figure()
            gh.add_trace(go.Scatter(x=_ts, y=_fl, mode="lines+markers", name="Gamma flip",
                                    line=dict(color="#7c3aed", width=1.6)))
            gh.add_trace(go.Scatter(x=_ts, y=_sp, mode="lines", name="Spot",
                                    line=dict(color="#2563eb", width=1.2, dash="dot")))
            gh.update_layout(height=240, margin=dict(l=10, r=10, t=24, b=10), plot_bgcolor="white",
                             font=dict(size=13), legend=dict(orientation="h", y=1.02, x=0),
                             title=dict(text="Today — flip line vs spot through the session", font=dict(size=13)))
            gh.update_xaxes(showgrid=True, gridcolor="#eef2f7")
            gh.update_yaxes(showgrid=True, gridcolor="#eef2f7")
            st.plotly_chart(gh, use_container_width=True)
            st.caption("Spot crossing BELOW the flip = entering trend/accelerator territory; reclaiming "
                       "ABOVE = back to mean-revert/patience. Built from your live loads today.")
        elif _g_today:
            st.caption("Today's intraday flip path will draw once a few more live points are logged.")
except Exception as _e_gh:
    st.caption(f"Gamma history unavailable: {_e_gh}")

st.caption("Notes: Candles are the near-month **future** (real volume); the gamma flip/walls are on the "
           "**spot** option chain, so they sit a few points off the futures price (basis) — read them as "
           "zones, not to-the-point levels. Gamma regime is a today-only snapshot (option open-interest "
           "isn't available for past days), so the ▲/▼ chart marks come from price, momentum, volume and "
           "breadth — things we can measure on every past candle — while the flip line gives today's "
           "structural context. These shift the odds; they are not a guarantee.")
