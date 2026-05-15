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
st.title("Page 15 — SuperTrend MTF")
st.caption("MTF Verdict · Strike-Path Corridors · Structural Backdrop · Moat Stack · SLEEPING/DRIVING")

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

def _run_st_engine(use_live: bool) -> bool:
    """Run SuperTrend engine — live candle during market hours, EOD data otherwise.
    Returns True on success, updates sig and spot_now in place via nonlocal."""
    global sig, spot_now
    try:
        from analytics.supertrend import SuperTrendEngine
        if use_live:
            from data.live_fetcher import (
                get_nifty_daily_live, get_nifty_1h_phase,
                get_nifty_30m, get_nifty_15m, get_nifty_5m, get_nifty_spot as _gs,
            )
            _daily = get_nifty_daily_live()
            _sp    = _gs() or spot_now
        else:
            from data.live_fetcher import (
                get_nifty_daily, get_nifty_1h_phase,
                get_nifty_30m, get_nifty_15m, get_nifty_5m,
            )
            _daily = get_nifty_daily()
            _sp    = spot_now
        _1h  = get_nifty_1h_phase()
        _30m = get_nifty_30m()
        _15m = get_nifty_15m()
        _5m  = get_nifty_5m()
        if _daily.empty or _1h.empty or _sp <= 0:
            return False
        _out = SuperTrendEngine().signals(
            df_daily=_daily, df_1h=_1h, df_30m=_30m,
            df_15m=_15m, df_5m=_5m, spot=_sp,
        )
        sig      = {**sig, **{f"st_{k}": v for k, v in _out.items()}}
        spot_now = _sp
        # Persist ST signals so 30M/15M survive after market close + cache expiry
        if use_live:
            try:
                from analytics.compute_signals import load_saved_signals, SIGNALS_PATH
                import json as _json
                _saved = load_saved_signals()
                _saved.update({k: v for k, v in sig.items() if k.startswith("st_")})
                SIGNALS_PATH.write_text(_json.dumps(
                    {k: v for k, v in _saved.items()
                     if not hasattr(v, "to_dict") and not hasattr(v, "iloc")},
                    default=str, indent=2,
                ))
            except Exception:
                pass
        return True
    except Exception as _e:
        st.caption(f"ST engine ({'live' if use_live else 'eod'}): {_e}")
        return False

if _is_mkt_live():
    _run_st_engine(use_live=True)
elif not sig.get("st_tf_signals"):
    # signals.json missing ST data — run engine from EOD data so page always shows real lines
    _run_st_engine(use_live=False)

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

# Ensure all 6 TF cards always appear — fill missing TFs with a no-data placeholder
for _lc, _uc in _TF_MAP:
    if _uc not in st_data:
        st_data[_uc] = {
            "val": 0, "dir": "N/A", "flip_price": 0, "flip_time": "No data",
            "weight": _TF_WTS.get(_lc, 0), "flip": False, "state_raw": "UNKNOWN",
            "no_data": True,
        }

# ── 2. ENGINE CALCULATIONS: States, Depth, and Corridors ─────────────────────
_DEF_THR, _PREP_LOSS = 2.5, 2.25
_OFF_THR, _PREP_PROF = 1.8, 1.35
ce_sold = int(round(tue_close * 1.035 / 50) * 50)
pe_sold = int(round(tue_close * 0.960 / 50) * 50)

for tf, data in st_data.items():
    if data.get("no_data"):
        continue
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
st_30 = st_data.get("30M", {})
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
elif st_30.get("state") == "🚀 DRIVING" or st_15.get("state") == "🚀 DRIVING":
    canary_state = f"👁️ PREPARE (Intraday)"
    canary_col   = "#d97706"
    canary_sub   = f"Tier 3 Canaries pushing (30m/15m), but 1H operational structure remains asleep."

st.markdown(
    f"<div style='background:{canary_col};border-radius:10px;padding:20px;text-align:center;margin-bottom:20px;'>"
    f"<div style='color:rgba(255,255,255,0.8);font-size:14px;font-weight:700;letter-spacing:1.5px;margin-bottom:4px;'>MTF VERDICT</div>"
    f"<div style='color:white;font-size:32px;font-weight:900;'>{canary_state}</div>"
    f"<div style='color:white;font-size:16px;margin-top:6px;opacity:0.9;'>{canary_sub}</div>"
    f"</div>", unsafe_allow_html=True
)

st.divider()

# ── 3b. MTF PRICE LADDER ──────────────────────────────────────────────────────
st.markdown("<h3 style='color:#334155;margin-bottom:4px;'>MTF Price Ladder</h3>", unsafe_allow_html=True)
st.caption("All 6 TFs sorted high → low · DRIVING = direction colour · SLEEPING = TF yellow shade + TF text colour · CMP dashed")

# SLEEPING: yellow BG shade per TF + distinct dark text per TF (same for ST line and flip level)
_SLEEP_PAL = {
    "DAILY": ("#fefce8", "#1e3a5f", "1px solid #fde68a"),  # palest cream,  dark navy
    "4H":    ("#fef9c3", "#4c1d95", "1px solid #fef08a"),  # light yellow,  dark purple
    "2H":    ("#fef08a", "#14532d", "1px solid #fde047"),  # medium yellow, dark green
    "1H":    ("#fde047", "#7f1d1d", "1px solid #facc15"),  # bright yellow, dark red
    "30M":   ("#fbbf24", "#0c4a6e", "1px solid #f59e0b"),  # golden amber,  dark teal
    "15M":   ("#f59e0b", "#431407", "1px solid #d97706"),  # deep amber,    dark brown
}
_DRV_BULL  = ("#16a34a", "white", "1px solid #15803d")
_DRV_BEAR  = ("#dc2626", "white", "1px solid #b91c1c")
_CMP_STYLE = ("#1d4ed8", "white", "2px dashed rgba(255,255,255,0.6)")

_ladder_items = []
_no_data_tfs  = []

for _tf, _d in st_data.items():
    if _d.get("no_data"):
        _no_data_tfs.append(_tf)
        continue
    _dir  = _d["dir"]
    _val  = float(_d["val"])
    _sraw = _d.get("state_raw", "UNKNOWN")
    _fp   = float(_d.get("flip_price", 0))
    _drv  = _sraw == "DRIVING"

    _ladder_items.append({
        "tf": _tf, "value": _val, "dir": _dir, "driving": _drv,
        "label": f"{_tf}  {'BEAR' if _dir == 'BEAR' else 'BULL'}  {'🚀 DRIVING' if _drv else '📦 SLEEPING'}",
    })

    if _sraw == "SLEEPING" and _fp > 0 and abs(_fp - _val) > 5:
        _flip_tag = "FLIP SUPPORT" if _dir == "BEAR" else "FLIP RESISTANCE"
        _ladder_items.append({
            "tf": _tf, "value": _fp, "dir": _dir, "driving": False,
            "label": f"{_tf}  {_flip_tag}  📦 SLEEPING",
        })

_ladder_items.append({"tf": "CMP", "value": spot_now, "dir": "", "driving": False, "label": "CMP"})
_ladder_items.sort(key=lambda x: x["value"], reverse=True)

_ldr_html  = "<div style='background:#0f172a;border-radius:12px;padding:20px;border:1px solid #1e293b;'>"
_ldr_html += "<div style='font-size:12px;font-weight:700;color:#64748b;letter-spacing:2px;margin-bottom:14px;'>PRICE · HIGH → LOW</div>"

for _it in _ladder_items:
    if _it["tf"] == "CMP":
        _bg, _tc, _br = _CMP_STYLE
    elif _it["driving"]:
        _bg, _tc, _br = _DRV_BULL if _it["dir"] == "BULL" else _DRV_BEAR
    else:
        _bg, _tc, _br = _SLEEP_PAL.get(_it["tf"], ("#fef3c7", "#78350f", "1px dashed #d97706"))

    _pct  = (_it["value"] - spot_now) / spot_now * 100 if _it["tf"] != "CMP" else None
    _pcts = f"{_pct:+.2f}%" if _pct is not None else "—"
    _mg   = "margin:10px 0;" if _it["tf"] == "CMP" else "margin:3px 0;"
    _ldr_html += (
        f"<div style='background:{_bg};color:{_tc};padding:9px 14px;border-radius:6px;"
        f"border:{_br};{_mg}display:flex;justify-content:space-between;align-items:center;'>"
        f"<span style='font-size:13px;font-weight:700;'>{_it['label']}</span>"
        f"<div style='text-align:right;'>"
        f"<div style='font-size:16px;font-weight:900;'>{_it['value']:,.0f}</div>"
        f"<div style='font-size:11px;opacity:0.75;'>{_pcts}</div>"
        f"</div></div>"
    )

# No-data TFs — always shown, greyed out at bottom
for _tf in _no_data_tfs:
    _bg, _tc, _br = _SLEEP_PAL.get(_tf, ("#1e293b", "#64748b", "1px dashed #334155"))
    _ldr_html += (
        f"<div style='background:{_bg};color:{_tc};padding:9px 14px;border-radius:6px;"
        f"border:{_br};margin:3px 0;display:flex;justify-content:space-between;"
        f"align-items:center;opacity:0.45;'>"
        f"<span style='font-size:13px;font-weight:700;'>{_tf}  📦 No data</span>"
        f"<div style='text-align:right;'>"
        f"<div style='font-size:16px;font-weight:900;'>—</div>"
        f"<div style='font-size:11px;'>awaiting fetch</div>"
        f"</div></div>"
    )

_ldr_html += "</div>"
st.markdown(_ldr_html, unsafe_allow_html=True)

st.divider()

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
    if data.get("no_data"):
        continue
    if data["dir"] == "BEAR":
        ce_items.append((f"🧱 {tf} MOAT", data["val"], "#fbcfe8", "#831843"))
    else:
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
        if data.get("no_data"):
            st.markdown(
                f"<div style='background:#f8fafc;border:1px dashed #cbd5e1;border-radius:8px;padding:16px;margin-bottom:16px;opacity:0.6;'>"
                f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;'>"
                f"<span style='font-weight:800;font-size:16px;color:#94a3b8;'>{tf} SuperTrend <span style='font-size:12px;font-weight:600;'>({_tier_map.get(tf, 'TF')})</span></span>"
                f"<span style='background:#94a3b8;color:white;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:700;'>N/A</span>"
                f"</div>"
                f"<div style='font-size:14px;color:#94a3b8;font-style:italic;padding:12px 0;'>Data unavailable — fetch failed or market closed</div>"
                f"</div>", unsafe_allow_html=True
            )
            continue

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
    if data.get("no_data"):
        continue
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
    * **✅ HOLD (Theta Farm):** 4H is SLEEPING 📦. 1H is SLEEPING 📦. Market is trapped inside operational boxes. Farm theta.
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
