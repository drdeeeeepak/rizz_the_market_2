# pages/13_Geometric_Edge.py
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime

from analytics.geometric_edge import GeometricEdgeScanner
from data.live_fetcher import get_nifty500_breadth

st.set_page_config(page_title="P13 · Geometric Edge", layout="wide")
st_autorefresh(interval=300_000, key="p13_refresh")   # 5-min refresh (EOD scan)

st.title("Page 13 — Geometric Edge Scanner")
st.caption(
    "Martin Luk methodology · NSE India adapted · "
    "4 daily scans (11am, 1:30pm, 3:15pm, EOD) · "
    "Conviction scoring · Separate from options system"
)

eng = GeometricEdgeScanner()

# ── MARKET HEALTH GATE ────────────────────────────────────────────────────────
breadth_count = get_nifty500_breadth()

# Derive phase from count
if breadth_count > 350:
    health_phase = "AGGR_BULL"
    health_color = "#16a34a"
    health_label = "Aggressive Bull"
elif breadth_count > 200:
    health_phase = "SELECTIVE"
    health_color = "#d97706"
    health_label = "Selective"
else:
    health_phase = "BEAR"
    health_color = "#dc2626"
    health_label = "Bear — Scans Paused"

c1,c2,c3,c4 = st.columns(4)
c1.metric("Nifty 500 above 200 SMA", breadth_count)
c2.metric("Market Phase",            health_label)
c3.metric("Scan Status",             "RUNNING ✅" if health_phase != "BEAR" else "PAUSED 🔴")
c4.metric("Last scan",               datetime.now().strftime("%H:%M"))

if health_phase == "BEAR":
    st.error("🔴 Market in Bear phase — all Geometric Edge scans are paused. Capital preservation mode.")

st.divider()

# ── LOAD TODAY'S WATCHLISTS ───────────────────────────────────────────────────
watchlists = eng.load_all_watchlists()
eod_summary = eng.build_eod_summary(watchlists)

# ── SCAN TABS ─────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs(["EOD Summary", "11:00am", "1:30pm", "3:15pm", "EOD Scan"])

with tab1:
    st.subheader("EOD Conviction Summary — All 4 Scans")
    if not eod_summary:
        st.info("No scans completed yet today. Scans run at 11am, 1:30pm, 3:15pm, and 3:35pm IST.")
    else:
        rows = []
        for item in eod_summary:
            conviction = item.get("conviction_score", 0)
            ep_pivot   = item.get("ep_pivot", False)
            bookended  = item.get("bookended", False)
            size_pct   = item.get("size_pct", 0)

            rows.append({
                "Symbol":       item.get("symbol", "—"),
                "Segment":      item.get("segment", "—"),
                "Conviction":   f"{conviction}/4",
                "Label":        item.get("conviction_label", "—"),
                "EP Pivot":     "✅" if ep_pivot  else "—",
                "Bookended":    "✅" if bookended else "—",
                "Size % of cap":f"{size_pct*100:.0f}%",
                "Price Str":    f"{item.get('price_str_pct', 0):.1f}%",
                "Vol Mult":     f"{item.get('vol_mult', 0):.1f}×",
                "ADR 20d":      f"{item.get('adr_20', 0):.1f}%",
                "Scan Time":    item.get("scan_time", "—"),
            })

        df_eod = pd.DataFrame(rows)

        def highlight_conviction(row):
            c = row["Conviction"]
            if "4" in c:  return ["background-color:#dcfce7"] * len(row)
            if "3" in c:  return ["background-color:#dbeafe"] * len(row)
            if "1" in c:  return ["background-color:#fef3c7"] * len(row)
            return [""] * len(row)

        st.dataframe(
            df_eod.style.apply(highlight_conviction, axis=1),
            width='stretch', hide_index=True,
        )

        # Conviction legend
        st.markdown("""
<div style="display:flex;gap:12px;flex-wrap:wrap;font-size:11px;font-family:monospace;margin-top:6px;">
  <span style="background:#dcfce7;padding:3px 8px;border-radius:4px;">4/4 scans = Maximum conviction</span>
  <span style="background:#dbeafe;padding:3px 8px;border-radius:4px;">3/4 scans = Moderate</span>
  <span style="background:#fef3c7;padding:3px 8px;border-radius:4px;">1/4 = EOD only = Lowest</span>
  <span style="background:#f0fdf4;padding:3px 8px;border-radius:4px;">EP Pivot = Episodic event (strongest)</span>
</div>
        """, unsafe_allow_html=True)


def render_watchlist_tab(label: str, wl: list):
    if not wl:
        st.info(f"No results from {label} scan yet.")
        return
    rows = []
    for item in wl:
        rows.append({
            "Symbol":     item.get("symbol", "—"),
            "Segment":    item.get("segment", "—"),
            "Price Str %":f"{item.get('price_str_pct', 0):.1f}%",
            "Vol ×":      f"{item.get('vol_mult', 0):.1f}×",
            "ADR 20d %":  f"{item.get('adr_20', 0):.1f}%",
            "Gap %":      f"{item.get('gap_pct', 0):.1f}%",
            "EP Pivot":   "✅" if item.get("ep_pivot") else "—",
            "R:R Ok":     "✅" if item.get("rr_ok")    else "—",
            "LTP":        item.get("ltp", "—"),
        })
    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)


with tab2:
    st.subheader("11:00am Scan")
    render_watchlist_tab("11:00am", watchlists.get("1100", []))

with tab3:
    st.subheader("1:30pm Scan")
    render_watchlist_tab("1:30pm", watchlists.get("1330", []))

with tab4:
    st.subheader("3:15pm Scan")
    render_watchlist_tab("3:15pm", watchlists.get("1515", []))

with tab5:
    st.subheader("EOD Scan (3:35pm)")
    render_watchlist_tab("EOD", watchlists.get("eod", []))

st.divider()

# ── CRITERIA REFERENCE ────────────────────────────────────────────────────────
with st.expander("Scan Criteria Reference — Martin Luk NSE Adapted"):
    st.markdown("""
| Segment | Price Strength | Volume Mult | ADR 20d | EP Gap |
|---------|---------------|-------------|---------|--------|
| Nifty 50 | ≥2.0% | ≥1.5× | ≥1.5% | ≥2.0% |
| Nifty Next 50 | ≥2.5% | ≥2.0× | ≥2.2% | ≥3.0% |
| Midcap | ≥3.0% | ≥2.0× | ≥3.0% | ≥4.0% |
| Smallcap | ≥3.5% | ≥2.5× | ≥4.0% | ≥6.0% |

**Conviction Scoring:**
- 4/4 scans + EP Pivot = **1.0%** capital (pilot entry)
- 4/4 scans, no EP = **0.75%**
- Bookended (11am + EOD) = **0.50%**
- 3/4 scans = **0.35%**
- EOD only = **0.25%**

**India-specific rules:**
- No stocks in 5% circuit
- Limit orders only (no market orders)
- 9 EMA daily trailing stop
- Minimum 6:1 risk-reward (India friction: STT, brokerage, slippage)

**Market health gate:**
- Nifty 500 > 350 above 200 SMA = Aggressive Bull (all segments)
- 200–350 = Selective (large-cap and midcap only)
- < 200 = Bear (pause all scans, capital preservation)
    """)
