# pages/03_SuperTrend_MTF.py — v3.2 (Dynamic Fallback & Live Engine)
# SuperTrend Multi-Timeframe Monitor — Biweekly 3.5% / 4.0% Engine

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
from streamlit_autorefresh import st_autorefresh
from page_utils import bootstrap_signals, show_page_header

# ── 0. CONFIG & LIVE BOOTSTRAP ────────────────────────────────────────────────
st.set_page_config(page_title="P15 · SuperTrend MTF", layout="wide")
st_autorefresh(interval=180_000, key="p15")

sig, spot_live, signals_ts = bootstrap_signals()

if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

show_page_header(spot_live, signals_ts)

# ── 1. DATA EXTRACTION & LIVE ENGINE ───────────────────────────────────────────
spot_now = float(spot_live) if spot_live > 0 else 22150.0

# Fetch Tuesday Anchor Close
tue_close = float(sig.get("tue_close", 0))
if tue_close == 0:
    try:
        from analytics.constituent_ema import _load_anchors
        _anch = _load_anchors().get("NIFTY", {})
        tue_close = float(_anch.get("close", 0))
    except Exception:
        pass
if tue_close == 0:
    tue_close = round(spot_now / 50) * 50

# Live engine call during market hours
def _is_mkt_live():
    n = datetime.now(pytz.timezone("Asia/Kolkata"))
    t = n.hour * 60 + n.minute
    return n.weekday() < 5 and 9*60+15 <= t <= 15*60+30

if _is_mkt_live():
    try:
        from data.live_fetcher import (
            get_nifty_daily_live, get_nifty_1h_phase,
            get_nifty_30m, get_nifty_15m, get_nifty_5m, get_nifty_spot as _gs15,
        )
        from analytics.supertrend import SuperTrendEngine
        _df15  = get_nifty_daily_live()
        _1h15  = get_nifty_1h_phase()
        _30m15 = get_nifty_30m()
        _15m15 = get_nifty_15m()
        _5m15  = get_nifty_5m()
        _sp15  = _gs15() or spot_now
        if not _df15.empty and not _1h15.empty and _sp15 > 0:
            _st15 = SuperTrendEngine().signals(
                df_daily=_df15, df_1h=_1h15, df_30m=_30m15,
                df_15m=_15m15, df_5m=_5m15, spot=_sp15
            )
            sig = {**sig, **{f"st_{k}": v for k, v in _st15.items()}}
            spot_now = _sp15
    except Exception as _e15:
        st.caption(f"Live engine: {_e15}")

# Build st_data from engine output (st_tf_signals) or fallback to mock
_TF_MAP = [("daily","DAILY"),("4h","4H"),("2h","2H"),("1h","1H"),("30m","30M"),("15m","15M")]
_TF_WTS = {"daily":30,"4h":20,"2h":15,"1h":12,"30m":8,"15m":5}

def _generate_dynamic_mock(spot):
    return {
        "DAILY": {"val":spot-600,"dir":"BULL","flip_price":spot-800,"flip_time":"(mock)","weight":30,"flip":False},
        "4H":    {"val":spot-350,"dir":"BULL","flip_price":spot-450,"flip_time":"(mock)","weight":20,"flip":False},
        "2H":    {"val":spot+200,"dir":"BEAR","flip_price":spot+150,"flip_time":"(mock)","weight":15,"flip":False},
        "1H":    {"val":spot+100,"dir":"BEAR","flip_price":spot+50, "flip_time":"(mock)","weight":12,"flip":False},
        "30M":   {"val":spot-40, "dir":"BULL","flip_price":spot-60, "flip_time":"(mock)","weight":8, "flip":False},
        "15M":   {"val":spot+30, "dir":"BEAR","flip_price":spot+10, "flip_time":"(mock)","weight":5, "flip":False},
    }

_tf_sigs = sig.get("st_tf_signals", {})
if _tf_sigs:
    st_data = {}
    for _lc, _uc in _TF_MAP:
        _tfs = _tf_sigs.get(_lc, {})
        if _tfs.get("direction", "UNKNOWN") != "UNKNOWN":
            st_data[_uc] = {
                "val":       _tfs["st_price"],
                "dir":       _tfs["direction"],
                "flip_price":_tfs.get("flip_price", 0),
                "flip_time": _tfs.get("flip_time", "—"),
                "weight":    _TF_WTS.get(_lc, 0),
                "flip":      _tfs.get("flip", False),
                "state_raw": _tfs.get("state", "UNKNOWN"),
            }
    if not st_data:
        st.warning("⚠️ Engine returned no TF signals — using structural fallbacks.")
        st_data = _generate_dynamic_mock(spot_now)
else:
    st.warning("⚠️ SuperTrend engine not yet run — using structural fallbacks based on live spot.")
    st_data = _generate_dynamic_mock(spot_now)

# ── 2. ENGINE CALCULATIONS: States, Depth, and Corridors ─────────────────────
_DEF_THR, _PREP_LOSS = 2.5, 2.25
_OFF_THR, _PREP_PROF = 1.8, 1.35
ce_sold = int(round(tue_close * 1.035 / 50) * 50)
pe_sold = int(round(tue_close * 0.960 / 50) * 50)

for tf, data in st_data.items():
    dist_pts = abs(spot_now - data["val"])
    dist_pct = (dist_pts / spot_now) * 100
    data["dist_pts"] = dist_pts
    data["dist_pct"] = dist_pct

    if dist_pct >= 1.8:
        data["depth"] = "DEEP";     data["mult"] = 1.5
    elif dist_pct >= 1.0:
        data["depth"] = "ADEQUATE"; data["mult"] = 1.0
    else:
        data["depth"] = "THIN";     data["mult"] = 0.5

    data["score"]    = data["weight"] * data["mult"]
    data["protects"] = "PUT leg" if data["dir"] == "BULL" else "CALL leg"

    # Use engine state if available, else compute from flip_price
    _raw = data.get("state_raw", "")
    if _raw in ("DRIVING", "SLEEPING"):
        data["state"] = "🚀 DRIVING" if _raw == "DRIVING" else "📦 SLEEPING"
    elif data["dir"] == "BULL":
        data["state"] = "🚀 DRIVING" if spot_now > data.get("flip_price", 0) else "📦 SLEEPING"
    else:
        data["state"] = "🚀 DRIVING" if spot_now < data.get("flip_price", 999999) else "📦 SLEEPING"

# ── 3. SINGLE MTF CANARY (4H / 1H Directional Rules) ──────────────────────
st_4h = st_data.get("4H", {})
st_1h = st_data.get("1H", {})
st_15 = st_data.get("15M", {})

canary_state = "✅ HOLD"
canary_col   = "#16a34a"
canary_sub   = "Theta Farm — Market trapped inside operational boxes. Premium decaying safely."

_1h_threat_dir = "CE" if st_1h.get("dir") == "BULL" else "PE"
_4h_threat_dir = "CE" if st_4h.get("dir") == "BULL" else "PE"

# Use engine flip bool (precise: flipped in last 1-2 candles)
_4h_flipped = st_4h.get("flip", False)
_1h_flipped = st_1h.get("flip", False)

if _4h_flipped:
    canary_state = f"🚨 EXIT {_4h_threat_dir}"
    canary_col   = "#7f1d1d"
    canary_sub   = f"Structure Collapse — 4H wall has flipped. {_4h_threat_dir} macro thesis dead."
elif _1h_flipped or (st_1h.get("state") == "🚀 DRIVING" and st_4h.get("state") == "🚀 DRIVING" and st_1h.get("dir") == st_4h.get("dir")):
    canary_state = f"🔴 ACT / ROLL {_1h_threat_dir}"
    canary_col   = "#dc2626"
    canary_sub   = f"Roll Trigger — 1H has flipped or dragged 4H into driving. {_1h_threat_dir} challenged."
elif st_1h.get("state") == "🚀 DRIVING":
    canary_state = f"👁️ WATCH {_1h_threat_dir}"
    canary_col   = "#ea580c"
    canary_sub   = f"Boundary Test — 1H driving toward {_1h_threat_dir}, but 4H wall is absorbing."
elif st_15.get("state") == "🚀 DRIVING":
    canary_state = f"👁️ PREPARE (Intraday)"
    canary_col   = "#d97706"
    canary_sub   = f"15m Canaries pushing, but 1H operational structure remains asleep."

st.markdown(
    f"<div style='background:{canary_col};border-radius:10px;padding:20px;text-align:center;margin-bottom:20px;'>"
    f"<div style='color:rgba(255,255,255,0.8);font-size:14px;font-weight:700;letter-spacing:1.5px;margin-bottom:4px;'>MTF VERDICT</div>"
    f"<div style='color:white;font-size:32px;font-weight:900;'>{canary_state}</div>"
    f"<div style='color:white;font-size:16px;margin-top:6px;opacity:0.9;'>{canary_sub}</div>"
    f"</div>", unsafe_allow_html=True
)

# ── 4. STRIKE-PATH CORRIDORS (Visual Map with P&L Nodes) ────────────────────
ui_col1, ui_col2 = st.columns(2)

ce_bk_loss = tue_close * (1 + _DEF_THR/100)
ce_pr_loss = tue_close * (1 + _PREP_LOSS/100)
ce_bk_prof = tue_close * (1 - _OFF_THR/100)
ce_pr_prof = tue_close * (1 - _PREP_PROF/100)

pe_bk_loss = tue_close * (1 - _DEF_THR/100)
pe_pr_loss = tue_close * (1 - _PREP_LOSS/100)
pe_bk_prof = tue_close * (1 + _OFF_THR/100)
pe_pr_prof = tue_close * (1 + _PREP_PROF/100)

ce_items = [
    ("CE SOLD (+3.5%)", ce_sold, "#1e293b", "white"),
    ("🔴 BOOK LOSS", ce_bk_loss, "#7f1d1d", "white"),
    ("🟠 PREP LOSS", ce_pr_loss, "#ea580c", "white"),
    ("🔵 PREP PROFIT", ce_pr_prof, "#0369a1", "white"),
    ("🟢 BOOK PROFIT", ce_bk_prof, "#0f766e", "white"),
    ("SPOT PRICE", spot_now, "#3b82f6", "white"),
]
pe_items = [
    ("PE SOLD (-4.0%)", pe_sold, "#1e293b", "white"),
    ("🔴 BOOK LOSS", pe_bk_loss, "#7f1d1d", "white"),
    ("🟠 PREP LOSS", pe_pr_loss, "#ea580c", "white"),
    ("🔵 PREP PROFIT", pe_pr_prof, "#0369a1", "white"),
    ("🟢 BOOK PROFIT", pe_bk_prof, "#0f766e", "white"),
    ("SPOT PRICE", spot_now, "#3b82f6", "white"),
]

for tf, data in st_data.items():
    if data["dir"] == "BEAR":
        # Light pink background, deep pink text
        ce_items.append((f"🧱 {tf} MOAT", data["val"], "#fbcfe8", "#831843"))
    else:
        # Light pastel green background, dark green text
        pe_items.append((f"🧱 {tf} MOAT", data["val"], "#bbf7d0", "#14532d"))

ce_items.sort(key=lambda x: x[1], reverse=True)
pe_items.sort(key=lambda x: x[1], reverse=True)

def _render_corridor(title, items, is_ce):
    html = f"<div style='background:#0f172a;border-radius:10px;padding:16px;border:1px solid #1e293b;'>"
    html += f"<div style='font-size:15px;font-weight:700;color:#94a3b8;margin-bottom:16px;letter-spacing:1px;'>{title}</div>"
    
    for lbl, val, bg, txt in items:
        border = "border: 2px solid #60a5fa;" if "SPOT" in lbl else "border: 1px solid rgba(255,255,255,0.1);"
        margin = "margin: 12px 0;" if "SPOT" in lbl else "margin: 4px 0;"
        pct_str = f"{((val - spot_now) / spot_now) * 100:+.2f}%" if not "SPOT" in lbl else "—"
        
        # Spatial filtering
        if is_ce and val < spot_now and "PROFIT" not in lbl and "SOLD" not in lbl: continue
        if not is_ce and val > spot_now and "PROFIT" not in lbl and "SOLD" not in lbl: continue

        html += f"<div style='background:{bg};color:{txt};padding:10px 14px;border-radius:6px;{border}{margin}display:flex;justify-content:space-between;align-items:center;'>"
        html += f"<span style='font-weight:700;font-size:14px;'>{lbl}</span>"
        html += f"<div style='text-align:right;'>"
        html += f"<div style='font-weight:900;font-size:16px;'>{val:,.0f}</div>"
        html += f"<div style='font-size:11px;opacity:0.8;'>{pct_str}</div>"
        html += f"</div></div>"
    
    html += "</div>"
    return html

with ui_col1:
    st.markdown(_render_corridor("CE STRIKE-PATH CORRIDOR (Overhead)", ce_items, is_ce=True), unsafe_allow_html=True)
with ui_col2:
    st.markdown(_render_corridor("PE STRIKE-PATH CORRIDOR (Downside)", pe_items, is_ce=False), unsafe_allow_html=True)

st.divider()

# ── 5. SECTION 1 — MTF STRUCTURAL BACKDROP ────────────────────────────────────
st.markdown("<h3 style='color:#334155;'>Section 1 — MTF Structural Backdrop</h3>", unsafe_allow_html=True)
st.caption("Daily · 4H · 2H · 1H · 30m · 15m (Sorted by structural importance)")

_tier_map = {"DAILY": "Tier 1", "4H": "Tier 1", "2H": "Tier 2", "1H": "Tier 2", "30M": "Tier 3", "15M": "Tier 3"}

cols = st.columns(3)
for i, (tf, data) in enumerate(st_data.items()):
    with cols[i % 3]:
        dir_col = "#16a34a" if data["dir"] == "BULL" else "#dc2626"
        state_col = "#0f766e" if "SLEEPING" in data.get("state", "") else "#b91c1c"
        depth_col = "#ea580c" if data.get("depth") == "THIN" else "#16a34a"
        
        st.markdown(
            f"<div style='background:white;border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin-bottom:16px;box-shadow: 0 1px 3px rgba(0,0,0,0.1);'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;'>"
            f"<span style='font-weight:800;font-size:16px;color:#1e293b;'>{tf} SuperTrend <span style='font-size:12px;color:#64748b;font-weight:600;'>({_tier_map.get(tf, 'TF')})</span></span>"
            f"<span style='background:{dir_col};color:white;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:700;'>{data['dir']}</span>"
            f"</div>"
            f"<div style='font-size:22px;font-weight:900;color:#0f172a;'>{data.get('val', 0):,.0f}</div>"
            f"<div style='font-size:13px;color:#475569;margin-bottom:12px;'>"
            f"{data.get('dist_pts', 0):,.0f} pts from spot · <span style='font-weight:700;'>{data.get('dist_pct', 0):.2f}% CMP</span>"
            f"</div>"
            f"<div style='display:flex;gap:6px;margin-bottom:12px;'>"
            f"<span style='font-size:11px;font-weight:700;color:{depth_col};border:1px solid {depth_col};padding:2px 6px;border-radius:4px;'>{data.get('depth', 'N/A')}</span>"
            f"<span style='font-size:11px;font-weight:700;color:white;background:{state_col};padding:2px 6px;border-radius:4px;'>{data.get('state', 'UNKNOWN')}</span>"
            f"</div>"
            f"<div style='background:#f8fafc;padding:8px;border-radius:6px;font-size:12px;color:#475569;'>"
            f"<div style='margin-bottom:4px;'><span style='font-weight:600;'>Protects:</span> {data.get('protects', '-')}</div>"
            f"<div style='margin-bottom:4px;'><span style='font-weight:600;'>Flip Time:</span> {data.get('flip_time', '-')}</div>"
            f"<div><span style='font-weight:600;'>Flip Price:</span> {data.get('flip_price', 0):,.0f}</div>"
            f"</div>"
            f"</div>", unsafe_allow_html=True
        )

st.divider()

# ── 6. SECTION 2 — MOAT STACK TABLES ──────────────────────────────────────────
st.markdown("<h3 style='color:#334155;'>Section 2 — Moat Stack</h3>", unsafe_allow_html=True)
st.caption("PUT side and CALL side · Weighted by TF importance and depth")

pe_rows, ce_rows = [], []
pe_score, ce_score = 0.0, 0.0

for tf, data in st_data.items():
    row = {
        "TF": tf,
        "ST Line": f"{data.get('val', 0):,.0f}",
        "Distance": f"{data.get('dist_pts', 0):,.0f} pts",
        "% CMP": f"{data.get('dist_pct', 0):.2f}%",
        "Depth": data.get('depth', '-'),
        "Mult": f"{data.get('mult', 0)}x",
        "Weight": data.get('weight', 0),
        "Score": data.get('score', 0)
    }
    if data.get("dir") == "BULL":
        pe_rows.append(row); pe_score += data.get('score', 0)
    else:
        ce_rows.append(row); ce_score += data.get('score', 0)

col_tbl1, col_tbl2 = st.columns(2)
with col_tbl1:
    st.markdown(f"#### 🟢 PUT Side Moat Stack")
    st.markdown(f"<div style='background:#dcfce7;color:#166534;padding:8px 12px;border-radius:6px;font-weight:700;margin-bottom:10px;'>Score: {pe_score}/100</div>", unsafe_allow_html=True)
    if pe_rows: st.dataframe(pd.DataFrame(pe_rows), hide_index=True, use_container_width=True)
    else: st.warning("No Bullish Moats detected.")

with col_tbl2:
    st.markdown(f"#### 🔴 CALL Side Moat Stack")
    st.markdown(f"<div style='background:#fee2e2;color:#991b1b;padding:8px 12px;border-radius:6px;font-weight:700;margin-bottom:10px;'>Score: {ce_score}/100</div>", unsafe_allow_html=True)
    if ce_rows: st.dataframe(pd.DataFrame(ce_rows), hide_index=True, use_container_width=True)
    else: st.warning("No Bearish Moats detected.")

st.divider()

# ── 7. STRATEGY REFERENCE & RULES ─────────────────────────────────────────────
with st.expander("SuperTrend MTF — Strategy Reference & Rules", expanded=False):
    st.markdown("""
    **1. The 3-Tier Architecture**
    * **Tier 1 (Daily, 4H): The Macro Walls.** These dictate the macro trend and provide foundational support/resistance. Used strictly as Strike Anchors. 
    * **Tier 2 (2H, 1H): Operational Triggers.** The bridge. Filters out intraday noise but reacts fast enough to capture a real regime shift. A flip on Tier 2 is the definitive Action/Roll Trigger.
    * **Tier 3 (30m, 15m): Intraday Canaries.** Highly reactive. Used strictly as Early Warnings to enter a "Watch" state. No capital is moved based on Tier 3 flips.

    **2. The Directional 4H / 1H Rules (The Canary Engine)**
    * **✅ HOLD (Theta Farm):** 4H is SLEEPING 📦. 1H is SLEEPING 📦. Market is trapped inside macro and operational boxes. Farm theta.
    * **👁️ WATCH (Boundary Test):** 4H is SLEEPING 📦. 1H enters DRIVING 🚀. Operational momentum has spiked and is testing the macro wall.
    * **🔴 ACT / ROLL (Roll Trigger):** 1H FLIPS polarity, OR 1H drives hard enough to drag 4H into DRIVING 🚀. The operational buffer is breached. Execute defensive roll on the challenged leg.
    * **🚨 EXIT (Structure Collapse):** 4H FLIPS polarity. The macro wall has fallen. Exit the challenged leg immediately.

    **3. Strike-Path Corridors & Polarity Flipping**
    * Short strikes must be placed *outside* the Tier 1 structural walls. 
    * If Spot drops below a Green PE moat, the line instantly flips Red and mathematically moves into the CE corridor to act as overhead resistance.
    
    **4. Expansion (DRIVING) vs Compression (SLEEPING)**
    * **DRIVING 🚀**: Spot price has broken past the historical price point that originally caused the SuperTrend to flip. Institutional momentum is actively pushing.
    * **SLEEPING 📦**: Spot price has pulled back and is trapped between the SuperTrend line and the historical flip point. The market is chopping sideways.
    """)
