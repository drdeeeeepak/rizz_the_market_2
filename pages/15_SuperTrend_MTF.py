# pages/03_SuperTrend_MTF.py — v3.0 (Strict Rule Engine)
# SuperTrend Multi-Timeframe Monitor — Biweekly 3.5% / 4.0% Engine
#
# LOCKED CHANGES:
#   - Single MTF Canary based on 4H/1H Directional Rules
#   - Strike-Path Corridors with integrated P&L nodes
#   - Section 1 Cards: Tiers 1/2/3, State (SLEEPING/DRIVING), Flip Timestamps
#   - Section 2 Tables: Moat Stacks (PE and CE)
#   - Explicit Reference and Rulebook at bottom

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

st.set_page_config(page_title="P15 · SuperTrend MTF", layout="wide")

# ── 1. BOOTSTRAP & MOCK DATA (Fallback for UI visualization) ──────────────────
# In production, this pulls from your SuperTrend signal dictionary.
spot_now = 22150.0
tue_close = 22000.0  # Anchor

_mock_st = {
    "DAILY": {"val": 21450.0, "dir": "BULL", "flip_price": 21300.0, "flip_time": "May 02, 14:15", "weight": 30},
    "4H":    {"val": 21850.0, "dir": "BULL", "flip_price": 21950.0, "flip_time": "May 08, 09:15", "weight": 20},
    "2H":    {"val": 22400.0, "dir": "BEAR", "flip_price": 22350.0, "flip_time": "May 09, 13:15", "weight": 15},
    "1H":    {"val": 22320.0, "dir": "BEAR", "flip_price": 22200.0, "flip_time": "May 10, 10:15", "weight": 12},
    "30M":   {"val": 22210.0, "dir": "BEAR", "flip_price": 22100.0, "flip_time": "May 11, 09:45", "weight": 8},
    "15M":   {"val": 22100.0, "dir": "BULL", "flip_price": 22120.0, "flip_time": "May 11, 14:30", "weight": 5},
}

st_data = _mock_st # Replace with your sig.get("supertrend_mtf", _mock_st)

# ── 2. ENGINE CALCULATIONS: States, Depth, and Corridors ──────────────────────
_DEF_THR, _PREP_LOSS = 2.5, 2.25
_OFF_THR, _PREP_PROF = 1.8, 1.35
ce_sold = int(round(tue_close * 1.035 / 50) * 50)
pe_sold = int(round(tue_close * 0.960 / 50) * 50)

# Process ST Data
for tf, data in st_data.items():
    dist_pts = abs(spot_now - data["val"])
    dist_pct = (dist_pts / spot_now) * 100
    data["dist_pts"] = dist_pts
    data["dist_pct"] = dist_pct
    
    if dist_pct >= 1.8:
        data["depth"] = "DEEP"
        data["mult"]  = 1.5
    elif dist_pct >= 1.0:
        data["depth"] = "ADEQUATE"
        data["mult"]  = 1.0
    else:
        data["depth"] = "THIN"
        data["mult"]  = 0.5
        
    data["score"] = data["weight"] * data["mult"]
    data["protects"] = "PUT leg" if data["dir"] == "BULL" else "CALL leg"
    
    # State Logic: Expansion vs Compression
    if data["dir"] == "BULL":
        data["state"] = "🚀 DRIVING" if spot_now > data["flip_price"] else "📦 SLEEPING"
    else:
        data["state"] = "🚀 DRIVING" if spot_now < data["flip_price"] else "📦 SLEEPING"

# ── 3. SINGLE MTF CANARY (4H / 1H Directional Rules) ──────────────────────────
# Tier 1 = 4H, Tier 2 = 1H, Tier 3 = 15m
st_4h = st_data.get("4H", {})
st_1h = st_data.get("1H", {})
st_15 = st_data.get("15M", {})

canary_state = "✅ HOLD"
canary_col   = "#16a34a"
canary_sub   = "Theta Farm — Market trapped inside operational boxes."

# Logic Engine based on strict rules
_1h_threat_dir = "CE" if st_1h.get("dir") == "BULL" else "PE"
_4h_threat_dir = "CE" if st_4h.get("dir") == "BULL" else "PE"

# Calculate simple freshness based on mock strings (in production, use datetime delta)
def _is_recent(time_str):
    return "May 11" in time_str or "May 10" in time_str # Mock logic for "recent flip"

if _is_recent(st_4h.get("flip_time", "")):
    canary_state = f"🚨 EXIT {_4h_threat_dir}"
    canary_col   = "#7f1d1d"
    canary_sub   = f"Structure Collapse — 4H wall has flipped. {_4h_threat_dir} macro thesis dead."
elif _is_recent(st_1h.get("flip_time", "")) or (st_1h.get("state") == "🚀 DRIVING" and st_4h.get("state") == "🚀 DRIVING"):
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

# ── 4. STRIKE-PATH CORRIDORS (Visual Map with P&L Nodes) ──────────────────────
ui_col1, ui_col2 = st.columns(2)

# P&L Node Calculations
ce_bk_loss = tue_close * (1 + _DEF_THR/100)
ce_pr_loss = tue_close * (1 + _PREP_LOSS/100)
ce_bk_prof = tue_close * (1 - _OFF_THR/100)
ce_pr_prof = tue_close * (1 - _PREP_PROF/100)

pe_bk_loss = tue_close * (1 - _DEF_THR/100)
pe_pr_loss = tue_close * (1 - _PREP_LOSS/100)
pe_bk_prof = tue_close * (1 + _OFF_THR/100)
pe_pr_prof = tue_close * (1 + _PREP_PROF/100)

# Build unified item lists for sorting
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

# Inject ST Moats
for tf, data in st_data.items():
    if data["dir"] == "BEAR": # Ceiling (CE Corridor)
        ce_items.append((f"🧱 {tf} MOAT", data["val"], "#dc2626", "white"))
    else: # Floor (PE Corridor)
        pe_items.append((f"🧱 {tf} MOAT", data["val"], "#16a34a", "white"))

# Sort Corridors
ce_items.sort(key=lambda x: x[1], reverse=True) # Highest price at top
pe_items.sort(key=lambda x: x[1], reverse=True) # Highest price at top

def _render_corridor(title, items, is_ce):
    html = f"<div style='background:#0f172a;border-radius:10px;padding:16px;border:1px solid #1e293b;'>"
    html += f"<div style='font-size:15px;font-weight:700;color:#94a3b8;margin-bottom:16px;letter-spacing:1px;'>{title}</div>"
    
    for lbl, val, bg, txt in items:
        # Highlight spot
        border = "border: 2px solid #60a5fa;" if "SPOT" in lbl else "border: 1px solid rgba(255,255,255,0.1);"
        margin = "margin: 12px 0;" if "SPOT" in lbl else "margin: 4px 0;"
        pct_from_spot = ((val - spot_now) / spot_now) * 100
        pct_str = f"{pct_from_spot:+.2f}%" if not "SPOT" in lbl else "—"
        
        # Only show items that make geographical sense (e.g., ignore CE profit nodes if spot is already past them)
        if is_ce and val < spot_now and "PROFIT" not in lbl: continue
        if not is_ce and val > spot_now and "PROFIT" not in lbl: continue

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
        state_col = "#0f766e" if "SLEEPING" in data["state"] else "#b91c1c"
        depth_col = "#ea580c" if data["depth"] == "THIN" else "#16a34a"
        
        st.markdown(
            f"<div style='background:white;border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin-bottom:16px;box-shadow: 0 1px 3px rgba(0,0,0,0.1);'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;'>"
            f"<span style='font-weight:800;font-size:16px;color:#1e293b;'>{tf} SuperTrend <span style='font-size:12px;color:#64748b;font-weight:600;'>({_tier_map[tf]})</span></span>"
            f"<span style='background:{dir_col};color:white;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:700;'>{data['dir']}</span>"
            f"</div>"
            
            f"<div style='font-size:22px;font-weight:900;color:#0f172a;'>{data['val']:,.0f}</div>"
            f"<div style='font-size:13px;color:#475569;margin-bottom:12px;'>"
            f"{data['dist_pts']:,.0f} pts from spot · <span style='font-weight:700;'>{data['dist_pct']:.2f}% CMP</span>"
            f"</div>"
            
            f"<div style='display:flex;gap:6px;margin-bottom:12px;'>"
            f"<span style='font-size:11px;font-weight:700;color:{depth_col};border:1px solid {depth_col};padding:2px 6px;border-radius:4px;'>{data['depth']}</span>"
            f"<span style='font-size:11px;font-weight:700;color:white;background:{state_col};padding:2px 6px;border-radius:4px;'>{data['state']}</span>"
            f"</div>"
            
            f"<div style='background:#f8fafc;padding:8px;border-radius:6px;font-size:12px;color:#475569;'>"
            f"<div style='margin-bottom:4px;'><span style='font-weight:600;'>Protects:</span> {data['protects']}</div>"
            f"<div style='margin-bottom:4px;'><span style='font-weight:600;'>Flip Time:</span> {data['flip_time']}</div>"
            f"<div><span style='font-weight:600;'>Flip Price:</span> {data['flip_price']:,.0f}</div>"
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
        "ST Line": f"{data['val']:,.0f}",
        "Distance": f"{data['dist_pts']:,.0f} pts",
        "% CMP": f"{data['dist_pct']:.2f}%",
        "Depth": data['depth'],
        "Mult": f"{data['mult']}x",
        "Weight": data['weight'],
        "Score": data['score']
    }
    if data["dir"] == "BULL":
        pe_rows.append(row)
        pe_score += data['score']
    else:
        ce_rows.append(row)
        ce_score += data['score']

df_pe = pd.DataFrame(pe_rows)
df_ce = pd.DataFrame(ce_rows)

col_tbl1, col_tbl2 = st.columns(2)

with col_tbl1:
    st.markdown(f"#### 🟢 PUT Side Moat Stack")
    st.markdown(f"<div style='background:#dcfce7;color:#166534;padding:8px 12px;border-radius:6px;font-weight:700;margin-bottom:10px;'>Score: {pe_score}/100</div>", unsafe_allow_html=True)
    if not df_pe.empty:
        st.dataframe(df_pe, hide_index=True, use_container_width=True)
    else:
        st.warning("No Bullish Moats detected.")

with col_tbl2:
    st.markdown(f"#### 🔴 CALL Side Moat Stack")
    st.markdown(f"<div style='background:#fee2e2;color:#991b1b;padding:8px 12px;border-radius:6px;font-weight:700;margin-bottom:10px;'>Score: {ce_score}/100</div>", unsafe_allow_html=True)
    if not df_ce.empty:
        st.dataframe(df_ce, hide_index=True, use_container_width=True)
    else:
        st.warning("No Bearish Moats detected.")

st.divider()

# ── 7. STRATEGY REFERENCE & RULES ─────────────────────────────────────────────
with st.expander("SuperTrend MTF — Strategy Reference & Rules", expanded=False):
    st.markdown("""
    **1. The 3-Tier Architecture**
    * **Tier 1 (Daily, 4H): The Macro Walls.** These dictate the macro trend and provide the foundational support/resistance walls. Used strictly as Strike Anchors. 
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