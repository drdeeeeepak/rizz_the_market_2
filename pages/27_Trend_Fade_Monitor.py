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
from analytics import reversal_backtest as rb

try:
    importlib.reload(_lf)
    importlib.reload(ps)
    importlib.reload(rb)
except Exception:
    pass

st.set_page_config(page_title="P27 · Trend Fade Monitor", layout="wide")
st.title("Page 27 — Trend Fade Monitor")
st.caption("Live reading of 6 trend signals, one by one and combined, for today — "
           "plus recent hourly price for context.")

st.success("🟢 **GREEN shading = confirmed DOWNTREND day = sell 2 PUTS : 1 CALL.** "
          "That's the only colour that means anything on this page — no shading, "
          "no change to your normal sizing.")

with st.expander("What this page is telling you", expanded=True):
    st.markdown(
        "- **6 signals watch the market from different angles** (swing structure, moving-average "
        "trend, support/resistance count, RSI momentum, SuperTrend, Bollinger %B fade). Each one "
        "says UP, DOWN, or no clear read.\n"
        "- **The \"combined\" reading only fires when several of them agree.** One signal alone "
        "saying UP or DOWN isn't enough — it needs backup from the others.\n"
        "- **Only a confirmed DOWN reading has been shown to actually matter.** When we tested "
        "it on real history, a confirmed downtrend reading was reliably followed by the CALL side "
        "getting tested more than the put side — checked twice, on two separate stretches of time, "
        "same result both times. So on a confirmed DOWN day, it can make sense to sell more puts "
        "than calls.\n"
        "- **A confirmed UP reading is NOT proven yet** — it looked promising in one test but not "
        "in the other, so treat it as informational only, not something to act on.\n"
        "- **Bollinger %B fade joined this composite** after its OWN early/late split-check on "
        "page 26 confirmed it: its oversold reading showed the same call-tested-more asymmetry, "
        "in both history halves. It's sign-flipped internally so that confirmed reading lines up "
        "with this composite's DOWN convention — see `_bollinger_fade_composite_adapter` in "
        "`analytics/position_sizing_backtest.py`.\n"
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
# Pinpoint signal — page 24's episode-anchored fall/bounce + rise/pullback,
# replaces the old intraday-only check
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("Pinpoint signal — page 24's exact-day long/short")
st.caption("Replaces the old intraday-only check, which compared today's price against TODAY's "
           "OWN high/low — a shallow level that turned out NOT to match what page 24 actually "
           "validated (that version would have shown 51-89% touch rates if backtested — a real "
           "bug, not a real finding). This uses the SAME episode-anchored trigger the rest of "
           "page 24 is built on: the true capitulation low/high, which can sit days earlier and "
           "can walk further before the bounce/pullback confirms. That makes this EOD-only, like "
           "the composite reading above — no longer a live intraday updater.")

pinpoint_labels = rb.dual_confirmation_daily_labels(daily)

if pinpoint_labels.empty:
    st.info("Not enough daily history to compute this.")
else:
    today_row = pinpoint_labels.iloc[-1]
    today_lbl = today_row["label"]
    _pin_word = {"PUT_ONLY": "LEAN LONG — sell PUT", "CALL_ONLY": "LEAN SHORT — sell CALL",
                "BOTH": "BOTH SIDES SAFE (rare — no tiebreak needed)", "NEITHER": "NO SIGNAL — stay out"}
    _pin_colour = {"PUT_ONLY": "#16a34a", "CALL_ONLY": "#dc2626", "BOTH": "#0ea5e9", "NEITHER": "#64748b"}
    _today_colour = _pin_colour.get(today_lbl, "#64748b")
    _today_word = _pin_word.get(today_lbl, today_lbl)
    st.markdown(
        f"### As of {pinpoint_labels.index[-1].date()}: "
        f"<span style='color:{_today_colour}'>**{_today_word}**</span>",
        unsafe_allow_html=True)
    if today_lbl == "PUT_ONLY":
        st.caption(f"Anchor low: {today_row['anchor_low']:,.1f} — this reading held (never touched "
                  f"again) 97.4%/94.9% of the time out to 3d/5d in the live backtest (n=40).")
    elif today_lbl == "CALL_ONLY":
        st.caption(f"Anchor high: {today_row['anchor_high']:,.1f} — this reading held 100%/100% of "
                  f"the time out to 3d/5d in the live backtest (n=18 — small sample, treat as "
                  f"strong evidence, not a guarantee).")
    elif today_lbl == "NEITHER":
        st.caption("No confirmed reversal trigger today — this is the MAJORITY reading (only ~6% "
                  "of days show any trigger at all in the live backtest), not a gap in the data.")
    else:
        st.caption("Both sides confirmed today — historically a near-zero-occurrence event "
                  "(n=0 in the live backtest). Worth a second look before acting on it.")

    st.markdown("**Last 10 days — visual verification**")
    hist10 = pinpoint_labels.tail(10).iloc[::-1].reset_index()
    hist10["date"] = hist10["date"].dt.strftime("%d-%b-%Y")
    hist10["close"] = hist10["close"].round(1)
    hist10["anchor_low"] = hist10["anchor_low"].round(1)
    hist10["anchor_high"] = hist10["anchor_high"].round(1)

    def _colour_pin_label(val):
        if val == "PUT_ONLY":
            return "background-color:#16a34a; color:#ffffff; font-weight:600;"
        if val == "CALL_ONLY":
            return "background-color:#dc2626; color:#ffffff; font-weight:600;"
        if val == "BOTH":
            return "background-color:#0ea5e9; color:#ffffff; font-weight:600;"
        return ""

    st.dataframe(hist10.style.map(_colour_pin_label, subset=["label"]),
                hide_index=True, use_container_width=True)
    st.caption("Green = PUT_ONLY (leaned long that day) · Red = CALL_ONLY (leaned short) · Blue = "
              "BOTH (rare) · Blank = NEITHER (no signal that day). Cross-check each labeled day "
              "against the chart below — a green ▲ / red ▼ marks the same days there.")

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
           "alone. Bollinger %B fade's row is sign-flipped so its confirmed (oversold) reading "
           "shows as 'Downtrend' here, matching the direction the composite actually validated — "
           "see the page-level note above. The headline above is these 6 combined, not a simple "
           "vote.")

# ══════════════════════════════════════════════════════════════════════════════
# Swing-signal backtest — Pinpoint trigger x composite direction, joint +
# split-validated. Answers: does requiring x/6 agreement on a Pinpoint
# trigger day improve the entry over Pinpoint alone, and does a looser
# Pinpoint preset (more triggers) still hold up once crossed with the
# composite, or is it just more noise?
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("🔬 Swing-signal backtest — x/6 composite × Pinpoint, joint")
st.caption(
    "Sells the OTM strike on the day **Pinpoint fires** (not the weekly Tuesday anchor "
    "breach_by_bucket/split_validation above use), tagged by what the **x/6 composite also said "
    "that same day**. Joint buckets like `PUT_ONLY | composite=UP` are both lenses agreeing "
    "bullish; `PUT_ONLY | composite=DOWN` is Pinpoint saying bounce while the composite says the "
    "down-leg isn't done — scored separately, not averaged away. Split into first/second half "
    "(chronological, out-of-sample) same as the composite's own DOWN validation, so a joint bucket "
    "only means something if it holds in BOTH halves, not just the full-history average.")

_sw1, _sw2, _sw3 = st.columns(3)
_sw_call_pct = _sw1.number_input("Call strike OTM %", value=3.0, step=0.5, key="p27_sw_call")
_sw_put_pct = _sw2.number_input("Put strike OTM %", value=3.5, step=0.5, key="p27_sw_put")
_sw_preset = _sw3.selectbox("Pinpoint preset", list(rb.PINPOINT_PRESETS.keys()),
                            index=list(rb.PINPOINT_PRESETS.keys()).index(rb.ACTIVE_PINPOINT_PRESET),
                            key="p27_sw_preset")

if st.button("▶ Run swing-signal backtest", key="p27_sw_run"):
    st.session_state.p27_sw_ran = True

if st.session_state.get("p27_sw_ran"):
    sw_result = ps.swing_signal_backtest(daily, h1 if h1 is not None else pd.DataFrame(),
                                         call_pct=_sw_call_pct, put_pct=_sw_put_pct,
                                         pinpoint_preset=_sw_preset)
    if not sw_result:
        st.info("Not enough history to run this — check daily/1H data loaded above.")
    else:
        for _seg_label, _seg_title in (("full", "Full history"), ("first_half", "First half"),
                                       ("second_half", "Second half")):
            _tbl = sw_result.get(_seg_label)
            if _tbl is None or _tbl.empty:
                continue
            st.markdown(f"**{_seg_title}**")
            st.dataframe(_tbl, use_container_width=True)
        sw_csv = ps.swing_signal_scan_to_frame(sw_result)
        st.download_button("Download swing-signal backtest CSV",
                           sw_csv.to_csv(index=False).encode("utf-8"),
                           file_name="swing_signal_backtest.csv", mime="text/csv",
                           key="p27_sw_dl")
        st.caption("A joint bucket is only worth trading if `n` is large enough to trust AND the "
                  "same direction/sign holds in both first_half and second_half — exactly the bar "
                  "the composite's own DOWN reading had to clear before being called validated.")

# ══════════════════════════════════════════════════════════════════════════════
# Last 3 days, hourly
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("Last 10 days, hour by hour")
st.caption("Day's reading and agreement come right after price — green means that day's reading "
           "is DOWN, the validated \"sell 2 puts\" setup. Everything else is plain, no colour.")
st.caption("Why every hour in a day shows the same number: none of these 6 signals look at the "
           "market during the day. Each one only checks ONCE — after trading ends at 3:30pm — and "
           "makes its call using that day's final closing price. So the reading for, say, Tuesday "
           "9:15am and Tuesday 2:15pm is identical, because both are showing \"what Tuesday's "
           "close said,\" and neither hour has a closing price of its own yet. The number will "
           "only change once the NEXT day closes.")

hist = ps.hourly_history_table(h1, snap["frame"], days=10)

if hist.empty:
    st.info("Not enough hourly data to show recent history.")
else:
    _signal_cols = [c for c in hist.columns
                    if c not in ("time", "close", "chg pts", "day's reading", "agreement")]
    hist = hist[["time", "close", "chg pts", "day's reading", "agreement"] + _signal_cols]

    def _colour_signal(val):
        try:
            v = float(val)
        except (TypeError, ValueError):
            return "color:#94a3b8;"
        if pd.isna(v) or v == 0:
            return "color:#94a3b8;"
        f = min(1.0, abs(v))  # 0..1 strength
        r, g, b = (22, 163, 74) if v > 0 else (220, 38, 38)
        rr, gg, bb = (int(255 + (c - 255) * f) for c in (r, g, b))
        txt = "#ffffff" if f > 0.55 else "#0f172a"
        return f"background-color:rgb({rr},{gg},{bb}); color:{txt}; font-weight:600;"

    def _colour_chg(val):
        try:
            v = float(val)
        except (TypeError, ValueError):
            return ""
        if v > 0:
            return "color:#16a34a;"
        if v < 0:
            return "color:#dc2626;"
        return "color:#64748b;"

    def _colour_reading(val):
        if val == "DOWN":
            return "background-color:#16a34a; color:#ffffff; font-weight:600;"
        return ""

    styled = (hist.style
              .map(_colour_signal, subset=_signal_cols)
              .map(_colour_chg, subset=["chg pts"])
              .map(_colour_reading, subset=["day's reading"]))
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
           "neither changes your default sizing). **Green ▲ = Pinpoint PUT_ONLY (leaned long) · "
           "Red ▼ = Pinpoint CALL_ONLY (leaned short)** — same days as the table above.")

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

    # Pinpoint markers: green ▲ below the day's low (PUT_ONLY, leaned long),
    # red ▼ above the day's high (CALL_ONLY, leaned short) — same convention
    # as buy/sell arrows on a normal charting tool.
    for day, (first_i, last_i) in day_bounds.items():
        if day not in pinpoint_labels.index:
            continue
        lbl = pinpoint_labels.loc[day, "label"]
        if lbl not in ("PUT_ONLY", "CALL_ONLY"):
            continue
        mid_i = (first_i + last_i) / 2
        day_slice = h1c.iloc[first_i:last_i + 1]
        if lbl == "PUT_ONLY":
            fig.add_annotation(x=mid_i, y=float(day_slice["low"].min()), text="▲", showarrow=False,
                              font=dict(size=20, color="#16a34a"), yshift=-16)
        else:
            fig.add_annotation(x=mid_i, y=float(day_slice["high"].max()), text="▼", showarrow=False,
                              font=dict(size=20, color="#dc2626"), yshift=16)

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
