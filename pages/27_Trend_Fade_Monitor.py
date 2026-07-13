# pages/27_Trend_Fade_Monitor.py
# LIVE dashboard — "what is the trend signal saying TODAY, indicator by
# indicator and combined, and how strong is the read?" Loads automatically,
# no buttons or lookback sliders — history depth is fixed in the background
# (see LOOKBACK_DAYS / H1_DAYS below) since it doesn't need tuning day to
# day. The live counterpart to page 26's historical backtest.

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

import importlib
import data.live_fetcher as _lf
from analytics import position_sizing_backtest as ps

try:
    importlib.reload(_lf)
    importlib.reload(ps)
except Exception:
    pass

st.set_page_config(page_title="P27 · Trend Fade Monitor", layout="wide")
st.title("Page 27 — Trend Fade Monitor")
st.caption("Live reading of 5 trend signals, one by one and combined, for today — "
           "plus the last 3 days of hourly price for context.")

with st.expander("What this page is telling you", expanded=True):
    st.markdown(
        "- **5 signals watch the market from different angles** (swing structure, moving-average "
        "trend, support/resistance count, RSI momentum, SuperTrend). Each one says UP, DOWN, or "
        "no clear read.\n"
        "- **The \"combined\" reading only fires when several of them agree.** One signal alone "
        "saying UP or DOWN isn't enough — it needs backup from the others.\n"
        "- **Only a confirmed DOWN reading has been shown to actually matter.** When we tested "
        "it on real history, a confirmed downtrend reading was reliably followed by the CALL side "
        "getting tested more than the put side — checked twice, on two separate stretches of time, "
        "same result both times. So on a confirmed DOWN day, it can make sense to sell more puts "
        "than calls.\n"
        "- **A confirmed UP reading is NOT proven yet** — it looked promising in one test but not "
        "in the other, so treat it as informational only, not something to act on.\n"
        "- **This page never shows profit or loss.** There's no price-history data for options in "
        "this app, only whether a strike got touched — so everything here is about which side is "
        "more likely to get tested, not how much money it made or lost.")

# Fixed in the background — no need to tune this day to day. 730 days gives
# every indicator enough warm-up history; 380 is Kite's practical cap for
# 60-minute candles (used only by the swing-structure signal).
LOOKBACK_DAYS = 730
H1_DAYS = 380


@st.cache_data(ttl=900, show_spinner=False)
def _load_daily():
    return _lf.get_nifty_daily(days=LOOKBACK_DAYS)


@st.cache_data(ttl=900, show_spinner=False)
def _load_h1():
    return _lf.get_nifty_1h_phase(days=H1_DAYS)


with st.spinner("Reading today's signals…"):
    daily = _load_daily()
    h1 = _load_h1()

if daily is None or daily.empty:
    st.error("Could not load Nifty price history. Log in via Home → Kite, then refresh this page.")
    st.stop()

snap = ps.live_snapshot(daily, h1 if h1 is not None else pd.DataFrame())

if not snap:
    st.error("Not enough price history yet to compute a reading.")
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# Headline
# ══════════════════════════════════════════════════════════════════════════════
_bucket_word = {"UP": "UPTREND", "DOWN": "DOWNTREND", "NEUTRAL": "NO CLEAR TREND"}
_bucket_colour = {"UP": "#16a34a", "DOWN": "#dc2626", "NEUTRAL": "#64748b"}
_word = _bucket_word.get(snap["bucket"], snap["bucket"])
_colour = _bucket_colour.get(snap["bucket"], "#64748b")

st.markdown(
    f"### As of {snap['as_of']}: <span style='color:{_colour}'>**{_word}**</span> "
    f"&nbsp;·&nbsp; {snap['agree_count']} of {snap['n_signals']} signals agree",
    unsafe_allow_html=True)
st.markdown(f"**{snap['grade']}**")

sc1, sc2, sc3 = st.columns(3)
sc1.metric("Suggested CALL lots today", snap["suggested_lots_ce"])
sc2.metric("Suggested PUT lots today", snap["suggested_lots_pe"])
sc3.metric("Your usual default", "2 CALL : 1 PUT")

if snap["bucket"] != "DOWN":
    st.caption("Suggestion matches your usual default — this only changes on a confirmed "
               "downtrend day.")

# ══════════════════════════════════════════════════════════════════════════════
# Per-indicator breakdown
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("Each signal, on its own")
_label = {"UP": "Uptrend", "DOWN": "Downtrend", "NEUTRAL": "No clear read", "NO DATA": "No data"}
rows = []
for name, info in snap["per_indicator"].items():
    rows.append({
        "signal": name.replace("_", " ").title(),
        "says": _label.get(info["bucket"], info["bucket"]),
        "strength (-1 to +1)": info["value"] if info["value"] is not None else "—",
    })
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
            column_config={"strength (-1 to +1)": st.column_config.NumberColumn(format="%.1f")})
st.caption("Strength runs roughly -1 (strongly bearish) to +1 (strongly bullish) for that signal "
           "alone. The headline above is these 5 combined, not a simple vote.")

# ══════════════════════════════════════════════════════════════════════════════
# Last 3 days, hourly
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("Last 10 days, hour by hour")
st.caption("Day's reading and agreement come right after price — green means that day's reading "
           "is DOWN, the validated \"sell 2 puts\" setup. Everything else is plain, no colour. "
           "The signals only update once a day (at market close), so every hour within the same "
           "day repeats that day's numbers — this is here to see recent price moves alongside "
           "what the signals were saying that day, not to imply they change hour to hour.")

hist = ps.hourly_history_table(h1, snap["frame"], days=10)

if hist.empty:
    st.info("Not enough hourly data to show recent history.")
else:
    _signal_cols = [c for c in hist.columns
                    if c not in ("time", "close", "chg pts", "day's reading", "agreement")]
    hist = hist[["time", "close", "chg pts", "day's reading", "agreement"] + _signal_cols]

    def _colour_reading(val):
        if val == "DOWN":
            return "background-color:#16a34a; color:#ffffff; font-weight:600;"
        return ""

    styled = hist.style.map(_colour_reading, subset=["day's reading"])
    _num_cols = ["close", "chg pts"] + _signal_cols
    st.dataframe(styled, hide_index=True, use_container_width=True, height=420,
                column_config={c: st.column_config.NumberColumn(format="%.1f") for c in _num_cols})

# ══════════════════════════════════════════════════════════════════════════════
# 10-day hourly chart
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("10-day hourly chart")
st.caption("Real hourly price candles. **Shaded background = confirmed downtrend day — the "
           "validated 2-puts setup.** No shading = no action (either uptrend or no clear read; "
           "neither changes your default sizing).")

CHART_DAYS = 10
if h1 is not None and not h1.empty:
    h1c = h1.copy()
    h1c.index = pd.to_datetime(h1c.index)
    if getattr(h1c.index, "tz", None) is not None:
        h1c.index = h1c.index.tz_localize(None)
    h1c = h1c.sort_index()
    chart_days = sorted(set(h1c.index.normalize()))[-CHART_DAYS:]
    h1c = h1c[h1c.index.normalize().isin(set(chart_days))]

    bucket_series = ps.classify_composite(snap["frame"])

    # Position candles by ROW INDEX, not real time. A real-time x-axis leaves a visible
    # blank gap for every night, weekend, and holiday (Kite simply has no data for those
    # hours, but Plotly still reserves the space for them on a true time axis). Spacing by
    # index instead makes every candle sit flush against the next, regardless of how many
    # non-trading days fall in the window — no gap list to maintain, holidays included.
    x_pos = list(range(len(h1c)))
    labels = [ts.strftime("%d-%b %H:%M") for ts in h1c.index]
    days_arr = h1c.index.normalize()

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=x_pos, open=h1c["open"], high=h1c["high"], low=h1c["low"], close=h1c["close"],
        name="Nifty", increasing_line_color="#16a34a", decreasing_line_color="#dc2626",
        showlegend=False, text=labels, hoverinfo="text+y"))

    # One tick per day, positioned at that day's first candle; also tracks each day's
    # first/last row index so the DOWN-day shading below can cover the right span.
    tick_pos, tick_text, day_bounds = [], [], {}
    for i, day in enumerate(days_arr):
        if day not in day_bounds:
            day_bounds[day] = [i, i]
            tick_pos.append(i)
            tick_text.append(day.strftime("%d-%b"))
        else:
            day_bounds[day][1] = i

    # Only the actionable (DOWN) day gets shaded, in green — UP/NEUTRAL are left blank on
    # purpose, since neither of those calls for any change to your default sizing.
    for day, (first_i, last_i) in day_bounds.items():
        if bucket_series.get(day, "NEUTRAL") == "DOWN":
            fig.add_vrect(x0=first_i - 0.5, x1=last_i + 0.5,
                          fillcolor="rgba(22,163,74,0.16)", line_width=0)

    # dragmode="pan": one-finger/mouse drag PANS the chart body itself; two-finger pinch
    # zooms BOTH axes at once (this is Plotly's native pinch behavior on a cartesian plot
    # once scrollZoom is on — no rangeslider or off-chart control needed for it). No
    # rangeslider here on purpose: it would be a SECOND, separate zoom control below the
    # chart, which is the opposite of what was asked for.
    # height kept short relative to typical mobile width — a tall fixed height against a
    # narrow phone screen was exaggerating how "stretched" each candle looked vertically.
    fig.update_layout(height=340, xaxis_rangeslider_visible=False, plot_bgcolor="white",
                      margin=dict(l=10, r=10, t=20, b=10), yaxis_title="Nifty",
                      dragmode="pan")
    fig.update_xaxes(tickvals=tick_pos, ticktext=tick_text, fixedrange=False)
    fig.update_yaxes(fixedrange=False)   # dragging ON the Y-axis itself zooms just that axis
    st.plotly_chart(fig, use_container_width=True,
                    config={"scrollZoom": True, "displayModeBar": True,
                           "modeBarButtonsToAdd": ["zoomIn2d", "zoomOut2d", "autoScale2d"]})
    st.caption("On the chart itself: pinch with two fingers (or scroll) to zoom both axes "
               "together, one-finger/mouse drag to pan, drag directly on the Y-axis numbers or "
               "X-axis dates to stretch just that one axis, double-tap/double-click to reset.")
else:
    st.info("Not enough hourly data to draw the chart.")
