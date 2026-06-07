# pages/13_Geometric_Edge.py
import json
import os
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
from datetime import datetime, date, timedelta

from analytics.geometric_edge import GeometricEdgeScanner
from data.live_fetcher import get_nifty500_breadth
from config import GEO_MARKET_HEALTH_BULL, GEO_MARKET_HEALTH_SELECT

st.set_page_config(page_title="P13 · Geometric Edge", layout="wide")
st_autorefresh(interval=300_000, key="p13_refresh")

st.title("Page 13 — Geometric Edge Scanner")
st.caption(
    "Martin Luk methodology · NSE India adapted · "
    "5 daily scans (9am brief, 11am, 1:30pm, 3:15pm, EOD) · "
    "Conviction scoring · Trade levels included"
)

eng = GeometricEdgeScanner()

# ── MARKET HEALTH GATE ────────────────────────────────────────────────────────
breadth_count = get_nifty500_breadth()

if breadth_count > GEO_MARKET_HEALTH_BULL:
    health_phase = "AGGR_BULL"
    health_label = "Aggressive Bull"
elif breadth_count > GEO_MARKET_HEALTH_SELECT:
    health_phase = "SELECTIVE"
    health_label = "Selective"
else:
    health_phase = "BEAR"
    health_label = "Bear — Scans Paused"

c1, c2, c3, c4 = st.columns(4)
c1.metric("Nifty 500 above 200 SMA", breadth_count)
c2.metric("Market Phase",            health_label)
c3.metric("Scan Status",             "RUNNING ✅" if health_phase != "BEAR" else "PAUSED 🔴")
c4.metric("Last refresh",            datetime.now().strftime("%H:%M"))

if health_phase == "BEAR":
    st.error(
        "🔴 Market in Bear phase — Capital preservation mode. "
        "Stocks shown below are **watchlist only — no trades**."
    )
elif health_phase == "SELECTIVE":
    st.warning("🟡 Selective phase — large-cap and midcap only. Smallcap excluded.")

st.divider()

# ── HELPERS ───────────────────────────────────────────────────────────────────

def _bear_note(wl: list) -> bool:
    return any(item.get("bear_phase", False) for item in wl)


def _load_premarket() -> list[dict]:
    for delta in (0, 1):
        d    = date.today() - timedelta(days=delta)
        path = f"data/watchlists/{d.strftime('%Y-%m-%d')}_premarket.json"
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    return []


# ── LOAD DATA ─────────────────────────────────────────────────────────────────
watchlists   = eng.load_all_watchlists()
eod_summary  = eng.build_eod_summary(watchlists)
premarket    = _load_premarket()

# ── TABS ──────────────────────────────────────────────────────────────────────
tab_pre, tab_eod, tab2, tab3, tab4, tab5 = st.tabs([
    "9am Pre-Market Brief", "EOD Summary", "11:00am", "1:30pm", "3:15pm", "EOD Scan"
])


# ── TAB: PRE-MARKET BRIEF ────────────────────────────────────────────────────
with tab_pre:
    st.subheader("Pre-Market Brief — Today's Actionable Picks")
    st.caption("Generated at 9:00am IST · Based on last night's EOD scan + Gift Nifty direction")

    if not premarket:
        st.info(
            "Pre-market brief not yet available. "
            "It is generated at 9:00am IST from last night's EOD watchlist."
        )
    else:
        gift_gap = premarket[0].get("gift_gap_pct", 0) if premarket else 0
        bias     = premarket[0].get("market_bias", "UNKNOWN") if premarket else "UNKNOWN"
        bias_col = {"BULLISH": "🟢", "NEUTRAL": "🟡", "BEARISH": "🔴", "UNKNOWN": "⚪"}.get(bias, "⚪")

        st.info(f"Gift Nifty gap: **{gift_gap:+.2f}%** · Market bias: {bias_col} **{bias}**")

        if _bear_note(premarket):
            st.warning("⚠️ Bear phase — all entries are watchlist only.")

        rows = []
        for item in premarket:
            action = item.get("action", "VALID")
            bear   = item.get("bear_phase", False)
            rows.append({
                "Symbol":       item.get("symbol", "—"),
                "Segment":      item.get("segment", "—"),
                "Action":       "⛔ SKIP" if "SKIP" in action else ("⚠️ WATCHLIST" if bear else "✅ ENTER"),
                "Entry (₹)":   item.get("entry", "—"),
                "SL (₹)":      item.get("sl", "—"),
                "Risk/share":   f"₹{item.get('risk_per_share', 0):.1f}",
                "Target 3R":    item.get("tgt_3r", "—"),
                "Target 6R":    item.get("tgt_6r", "—"),
                "EP Pivot":     "✅" if item.get("ep_pivot") else "—",
                "Conviction":   f"{item.get('conviction_score', 0)}/4",
                "Note":         item.get("note", ""),
            })

        df_pre = pd.DataFrame(rows)

        def _pre_color(row):
            if "SKIP" in str(row.get("Action", "")):
                return ["background-color:#fee2e2"] * len(row)
            if "WATCHLIST" in str(row.get("Action", "")):
                return ["background-color:#fef9c3"] * len(row)
            if row.get("EP Pivot") == "✅":
                return ["background-color:#dcfce7"] * len(row)
            return ["background-color:#f0fdf4"] * len(row)

        st.dataframe(df_pre.style.apply(_pre_color, axis=1),
                     use_container_width=True, hide_index=True)

        with st.expander("How to use this brief"):
            st.markdown("""
**Tonight (after EOD scan fires at 3:35pm):**
1. Open this page and go to **EOD Summary** tab
2. Note the stocks with 4/4 or bookended conviction
3. For each one: note **Entry**, **SL**, **Target 3R**, **Target 6R**

**Next morning (9am brief fires):**
1. Check the **Pre-Market Brief** tab — stocks marked SKIP means the gap is against you
2. For VALID stocks: place a **limit buy order at the Entry price** before 9:15am
3. Keep the order valid for today only (GTT or DAY order, not GTC)

**During the day:**
- If order triggers: your SL is already set at the **SL (₹)** price shown
- If stock hits **Target 3R**: sell 50% of position, move stop to breakeven
- If stock hits **Target 6R**: exit remaining 50%
- If stock closes below **9 EMA daily**: exit entire position regardless of target
""")


# ── TAB: EOD SUMMARY ─────────────────────────────────────────────────────────
with tab_eod:
    st.subheader("EOD Conviction Summary — All 4 Scans")
    if not eod_summary:
        st.info("No scans completed yet today. Scans run at 11am, 1:30pm, 3:15pm, and 3:35pm IST.")
    else:
        if _bear_note(eod_summary):
            st.warning("⚠️ Bear phase — position sizes 0%. Watchlist candidates only.")

        rows = []
        for item in eod_summary:
            conviction = item.get("conviction_score", 0)
            bear       = item.get("bear_phase", False)
            size_pct   = item.get("size_pct", 0)
            rows.append({
                "Symbol":       item.get("symbol", "—"),
                "Segment":      item.get("segment", "—"),
                "Conviction":   f"{conviction}/4",
                "Label":        item.get("conviction_label", "—"),
                "EP Pivot":     "✅" if item.get("ep_pivot") else "—",
                "Bookended":    "✅" if item.get("bookended") else "—",
                "Size %":       "WATCHLIST" if bear else f"{size_pct*100:.0f}%",
                "Entry (₹)":   item.get("entry", "—"),
                "SL (₹)":      item.get("sl", "—"),
                "Risk/share":   f"₹{item.get('risk_per_share', 0):.1f}",
                "Tgt 3R (₹)":  item.get("tgt_3r", "—"),
                "Tgt 6R (₹)":  item.get("tgt_6r", "—"),
                "LTP":          item.get("ltp", "—"),
                "Vol ×":        f"{item.get('vol_mult', 0):.1f}×",
            })

        df_eod = pd.DataFrame(rows)

        def _eod_color(row):
            if str(row.get("Size %")) == "WATCHLIST":
                return ["background-color:#fef9c3"] * len(row)
            c = str(row.get("Conviction", ""))
            if "4" in c: return ["background-color:#dcfce7"] * len(row)
            if "3" in c: return ["background-color:#dbeafe"] * len(row)
            if "2" in c: return ["background-color:#ede9fe"] * len(row)
            if "1" in c: return ["background-color:#fef3c7"] * len(row)
            return [""] * len(row)

        st.dataframe(df_eod.style.apply(_eod_color, axis=1),
                     use_container_width=True, hide_index=True)

        st.markdown("""
<div style="display:flex;gap:10px;flex-wrap:wrap;font-size:11px;font-family:monospace;margin-top:6px;">
  <span style="background:#dcfce7;padding:3px 8px;border-radius:4px;">4/4 = Max conviction</span>
  <span style="background:#dbeafe;padding:3px 8px;border-radius:4px;">3/4 = Moderate</span>
  <span style="background:#ede9fe;padding:3px 8px;border-radius:4px;">2/4 = Speculative</span>
  <span style="background:#fef3c7;padding:3px 8px;border-radius:4px;">1/4 = Low</span>
  <span style="background:#fef9c3;padding:3px 8px;border-radius:4px;">Bear = Watchlist only</span>
</div>
        """, unsafe_allow_html=True)


# ── SHARED INTRADAY TAB RENDERER ─────────────────────────────────────────────
def render_watchlist_tab(label: str, wl: list):
    if not wl:
        st.info(f"No results from {label} scan yet.")
        return
    if _bear_note(wl):
        st.warning("⚠️ Bear phase scan — watchlist only, no trades.")
    rows = []
    for item in wl:
        rows.append({
            "Symbol":      item.get("symbol", "—"),
            "Segment":     item.get("segment", "—"),
            "Price Str %": f"{item.get('price_str_pct', 0):.1f}%",
            "Vol ×":       f"{item.get('vol_mult', 0):.1f}×",
            "Gap %":       f"{item.get('gap_pct', 0):.1f}%",
            "EP Pivot":    "✅" if item.get("ep_pivot") else "—",
            "Entry (₹)":  item.get("entry", "—"),
            "SL (₹)":     item.get("sl", "—"),
            "Risk/share":  f"₹{item.get('risk_per_share', 0):.1f}",
            "Tgt 3R (₹)": item.get("tgt_3r", "—"),
            "Tgt 6R (₹)": item.get("tgt_6r", "—"),
            "LTP":         item.get("ltp", "—"),
            "Phase":       "🔴 BEAR" if item.get("bear_phase") else "✅",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


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

# ── POSITION MANAGEMENT RULES ────────────────────────────────────────────────
with st.expander("Position Management Rules — Read Before Trading"):
    st.markdown("""
### Your Daily Routine

| Time | What to do |
|------|-----------|
| **3:35pm** | EOD scan fires. Check **EOD Summary** tab — note stocks with 3/4 or 4/4 conviction |
| **Evening** | For each VALID stock: write down Entry, SL, Target 3R, Target 6R from the table |
| **9:00am next day** | Check **Pre-Market Brief** tab — skip any stock marked SKIP (bearish gap) |
| **9:10am** | Place **limit buy orders** at the Entry price. Use DAY order (not GTC) |
| **During day** | Monitor positions. If order doesn't trigger by 11am → cancel and skip that stock |

---

### Entry Rules
- **Entry price** = today's high + 0.1% — confirms breakout is real, not a false move
- **Order type**: Limit only — never market order (India slippage + STT cost)
- **Cancel if**: stock opens more than 2% above your entry — too much slippage, skip it

### Stop Loss Rules
- **SL price** = today's low — this is your hard stop, no exceptions
- Place a **GTT stop-loss order** immediately after your buy triggers
- If stock hits SL intraday → **exit same day, no holding**
- If stock closes below SL but didn't hit it intraday → exit next morning at open

### Profit Booking Rules
| Level | Action |
|-------|--------|
| **Target 3R** | Sell **50% of position** → move stop to breakeven on remaining 50% |
| **Target 6R** | Exit **remaining 50%** — this is the full target |
| **9 EMA daily** | If close drops below 9 EMA → exit **entire position** (overrides target) |
| **End of week** | If position is flat with no momentum → exit by Friday close |

### Position Sizing
- Size % shown in the table = % of **total trading capital** (not total net worth)
- Example: ₹5L capital, 4/4 conviction stock, EP Pivot = 1.0% = ₹5,000 pilot entry
- Add more only if stock proves itself (hits 3R, pulls back to 9 EMA, re-entry)

### Conviction Scoring
- **4/4 + EP Pivot** = 1.0% → maximum conviction, gap-up with institutional footprint
- **4/4 no EP** = 0.75% → strong accumulation pattern across the whole day
- **Bookended** (11am + EOD) = 0.50% → consistent strength, institutional buying all day
- **3/4** = 0.35% → good signal, missing one scan
- **2/4** = 0.20% → speculative — smaller size, tighter stop
- **EOD only** = 0.10% → single data point — smallest size only
    """)

with st.expander("Scan Criteria Reference"):
    st.markdown("""
| Segment | Price Strength | Volume Mult | ADR 20d | EP Gap |
|---------|---------------|-------------|---------|--------|
| Nifty 50 | ≥2.0% | ≥1.5× | ≥1.5% | ≥2.0% |
| Nifty Next 50 | ≥2.5% | ≥2.0× | ≥2.2% | ≥3.0% |
| Midcap | ≥3.0% | ≥2.0× | ≥3.0% | ≥4.0% |
| Smallcap | ≥3.5% | ≥2.5× | ≥4.0% | ≥6.0% |

**Volume** is pro-rata normalised — 1× at 11am = same rate as 1× at EOD.
**Market health gate**: >350 = Aggressive Bull · 200–350 = Selective · <200 = Bear (watchlist only)
    """)
