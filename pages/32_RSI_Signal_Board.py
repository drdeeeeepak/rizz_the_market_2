# pages/32_RSI_Signal_Board.py
# One hourly-RSI signal board replacing pages 04 (Hourly RSI Breakout), 28 (RSI
# Swing Fade) and 31 (RSI Divergence Backtest) — those pages' interactive
# backtest tooling stays available in git history; this page keeps only the
# live signal (last 5, per system) and the backtested know-how already gathered
# from each, as a static writeup rather than re-runnable controls.

import importlib

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from data.live_fetcher import get_nifty_1h_phase, get_nifty_spot, get_nifty_30m, get_nifty_15m
from analytics import rsi_fade_backtest as rfb
from analytics.hourly_rsi_pivot import analyze_hourly_rsi

try:
    importlib.reload(rfb)
except Exception:
    pass

st.set_page_config(page_title="P32 · RSI Signal Board", layout="wide")

st.title("RSI Signal Board — Hourly")
st.caption(
    "Three independent hourly-RSI signal systems on one page: RSI Fade (75/25 zone "
    "cross), Pure Divergence, and HL/LH Pivot Breakout. Each shows its last 5 live "
    "signals, a chart, and the backtested findings gathered on it so far."
)

# ══════════════════════════════════════════════════════════════════════════════
# ACTIONABLE RULE — kept at the very top because it is the only thing on this
# page that changes what you actually do. Everything below is signal display.
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("📐 **STRIKE-TIGHTENING RULE** — sell the CALL nearer on a bearish "
                 "divergence day (calibrated 31 Jul 2026)", expanded=False):
    st.markdown("""
## The rule

On a **Pure Divergence** signal day, open the new position with the favoured leg
**0.25% nearer**. Leave the other leg exactly where it normally goes.

| Signal that day | CALL | PUT | Strength |
|---|---|---|---|
| **Bearish divergence** | **2.75%** (in from 3.0%) | 3.5% — unchanged | 🟢 **Strong** |
| **Bullish divergence** | 3.0% — unchanged | **3.25%** (in from 3.5%) | 🟡 **Weak — unconfirmed** |
| No signal | 3.0% | 3.5% | — |

⚠️ **The two halves are not equally proven.** The CALL rule passed at both expiry
horizons (p=0.008 and p=0.047). The PUT rule **did not** (p=0.059 near, p=0.452
biweekly) — it leans the right way but never cleared the bar. Treat the CALL rule
as actionable and the PUT rule as an experiment worth tracking.

## The numbers

Near expiry (5–9 trading days), Pure Divergence.

**CALL side — bearish signal, n=219** 🟢

| | Breach rate |
|---|---|
| CALL at your normal 3.0%, normal day | 9.2% |
| **CALL at 2.75%, bearish-signal day** | **6.4%** ✅ |
| CALL at 2.5%, bearish-signal day | 10.0% ❌ *worse than baseline* |

The PUT left at 3.5% on a bearish day breaches **5.9%** vs 7.1% normally — leaving it alone costs nothing. Both legs improve.

**PUT side — bullish signal, n=156** 🟡

| | Breach rate |
|---|---|
| PUT at your normal 3.5%, all days | 6.8% |
| **PUT at 3.25%, bullish-signal day** | **6.4%** ✅ *(thin margin)* |
| PUT at 3.0%, bullish-signal day | 8.3% ❌ *worse than baseline* |

The CALL left at 3.0% on a bullish day breaches 7.7% vs 8.1% — no penalty.

**Stronger PUT alternative, with a catch.** Using **ANY of the 3 systems'** bullish
signals instead of Pure Divergence alone is the only PUT-side result that reached
significance (p=0.023, n=331), and gives a better PUT number (6.0% at 3.25%). But
on those days the CALL left at 3.0% breaches **8.8% vs 7.7%** — you gain ~0.8pp on
the PUT and hand back ~0.8pp on the CALL, so total position risk is roughly
unchanged. That version buys **more premium, not more safety**. Pure Divergence is
the cleaner choice; ANY-of-3 is the statistically stronger one.

## Full breach ladder — near expiry, Pure Divergence

| OTM | CALL, bearish day | CALL, normal day | PUT, bullish day | PUT, normal day |
|---|---|---|---|---|
| 1.0% | 47.5% | 53.1% | 41.0% | 44.3% |
| 1.5% | 31.5% | 38.2% | 28.2% | 30.4% |
| 2.0% | 19.2% | 25.1% | 16.7% | 20.9% |
| 2.5% | 10.0% | 15.4% | 12.2% | 15.0% |
| **3.0%** | **4.1%** | **9.2%** | 8.3% | 10.1% |
| 3.5% | 1.4% | 6.0% | **3.8%** | **7.4%** |

Biweekly expiry (10–14 days) is the same shape, roughly doubled — e.g. CALL at 3.0%: 16.9% vs 22.1%.

Read the number at the distance you are actually considering. The curve is steep: a
comfortable single-digit breach rate at 3% becomes ~20% at 2% and ~48% at 1%.

## Do NOT

- **Don't go 0.5% nearer.** At 2.5% CALL / 3.0% PUT the edge is gone and you carry *more* risk than your normal position. 0.25% is the whole edge.
- **Don't tighten both legs on the same day.** Each rule fires on the opposite signal, so they can never both apply. A day is bearish or bullish, not both.
- **Don't sell at 1–2% OTM on a signal.** Breach runs 19–48%. A low breach rate is a property of *distance*, not of the signal.
- **Don't use Pivot Breakout or RSI Fade for this.** Tested, did not hold (see the grid below).
- **Don't apply this to a position you already hold.** Every result comes from opening a *new* position on the signal day. Shifting a leg you already sold means buying it back, and that cost is in none of these numbers.

## Why the PUT rule is weaker

Only the biweekly horizon disagrees, and it disagrees hard: bullish → PUT at biweekly
expiry is p=0.452, i.e. nothing at all (12.8% vs 13.2%). The near-expiry result
(p=0.059) is the only thing holding it up, and it misses the 0.05 bar. The CALL rule
by contrast holds at both horizons. That asymmetry is why the two carry different
confidence markers above — it is not a presentation choice, it is what the data says.

## What was tested, and what passed

All 3 systems plus 2 composites, both sides, both expiries — **20 tests**. Weekday-adjusted p-values:

| System | CALL near | CALL far | PUT near | PUT far |
|---|---|---|---|---|
| **Pure Divergence** | **0.008 ✅** | **0.047 ✅** | 0.059 | 0.452 |
| MAJORITY (≥2 of 3) | 0.044 ✅ | 0.126 | 0.104 | 0.335 |
| ANY of 3 | 0.193 | 0.448 | 0.023 ✅ | 0.103 |
| RSI Fade 75/25 | 0.229 | 0.199 | 0.405 | 0.134 |
| Pivot Breakout | 0.701 | 0.865 | 0.084 | 0.170 |

**Pure Divergence CALL is the only cell that passed at both horizons.** MAJORITY CALL and ANY-of-3 PUT passed near but failed biweekly — read those as unconfirmed.

## Why it works — direction, not volatility

A cross-test scored all four signal→side pairings. A bearish signal helps the CALL at every distance (−4.6 to −6.7) and does nothing for the PUT (≈0). A bullish signal helps the PUT and makes a *close* CALL worse (+4.5 to +6.2 at 2.0–2.5% OTM). That is a direction signal — a volatility signal would improve both sides together, and it doesn't. That +4.5/+6.2 penalty disappears by 3.0% OTM, which is why leaving the untouched leg at regular distance is safe.

## Honest limits

- **The edge is small** — 0.25% of strike distance, ~60 Nifty points.
- **Not proven.** p=0.008 as measured, but overlapping trades mean ~60 truly independent episodes rather than 219; corrected for that, p=0.134. 20 combinations were tested. Read as **promising, not established**.
- **Survival only.** No historical option-price data exists in this app, so nothing here says whether 2.75% *pays* better than 3.0% — only that it survives as often. The premium side of that trade-off is your judgement.

## Retest when

- After ~50 live signal-day positions
- If observed CALL breach at 2.75% runs above ~9%, or PUT breach at 3.25% above ~7% (the baselines each is meant to beat)
- 12 months from calibration (**Aug 2027**)
- After any sharp VIX regime change
- **Sooner for the PUT rule** — it is unconfirmed, so track it separately and drop it if live breach at 3.25% runs at or above your normal 3.5% rate

Re-run via page 33 — restore it from git first (see the retired-pages expander at the bottom).
The backtest engine itself, `analytics/strike_survival_backtest.py`, is still in the repo
and was never deleted.

*Calibrated 31 Jul 2026 · 4 years hourly + daily Nifty (Aug 2022 – Jul 2026) · 984 entry days.*
""")

DAYS = 365
RSI_PERIOD = 14


@st.cache_data(ttl=300, show_spinner="Fetching hourly data…")
def _load_hourly():
    df = get_nifty_1h_phase(days=DAYS)
    return df if df is not None and not df.empty else None


df_hourly = _load_hourly()

if df_hourly is None:
    st.error("Could not fetch hourly Nifty history. Log in via Home page, then retry.")
    st.stop()

if not isinstance(df_hourly.index, pd.DatetimeIndex):
    df_hourly.index = pd.to_datetime(df_hourly.index)

try:
    spot = get_nifty_spot()
except Exception:
    spot = None

st.caption(
    f"{len(df_hourly)} hourly candles · {df_hourly.index[0]:%d %b %Y} → "
    f"{df_hourly.index[-1]:%d %b %Y}" + (f" · Spot {spot:.0f}" if spot else "")
)


@st.cache_data(ttl=300, show_spinner=False)
def _load_30m(days=60):
    df = get_nifty_30m(days=days)
    return df if df is not None and not df.empty else None


@st.cache_data(ttl=300, show_spinner=False)
def _load_15m(days=40):
    df = get_nifty_15m(days=days)
    return df if df is not None and not df.empty else None


df_30m_raw = _load_30m()
df_15m_raw = _load_15m()
df_30m_hist = rfb.compute_rsi(df_30m_raw, RSI_PERIOD) if df_30m_raw is not None else None
df_15m_hist = rfb.compute_rsi(df_15m_raw, RSI_PERIOD) if df_15m_raw is not None else None


def _mini_rsi_chart(df_rsi, title, line_color="#3b82f6",
                    marker_times=None, marker_rsi=None, marker_labels=None, marker_colors=None,
                    min_candles=40):
    """
    Real date/time on the x-axis. Axis type is 'category' (not 'date') on purpose —
    a true date axis leaves visible gaps for closed market hours (evenings, weekends),
    which flattens and distorts an intraday RSI line; category type keeps candles
    evenly spaced like a trading platform while still labeling real timestamps.

    Window widens beyond 5 days automatically when needed so all 5 signal markers
    stay on-chart — Divergence/Breakout signals fire roughly weekly, far less often
    than the Fade zone-cross, so a fixed 5-day window would cut most of them off.
    """
    marker_times = marker_times or []
    n_candles = min_candles
    if marker_times:
        earliest_marker = min(marker_times)
        n_since_marker = (df_rsi.index >= earliest_marker).sum() + 3   # +3 candles padding
        n_candles = max(min_candles, n_since_marker)
    n_candles = min(n_candles, len(df_rsi))

    chart_slice = df_rsi.tail(n_candles)
    x_labels = [ts.strftime("%d %b %H:%M") for ts in chart_slice.index]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_labels, y=chart_slice["rsi"].tolist(),
        mode="lines+markers", line=dict(color=line_color, width=2), name="RSI(14)"
    ))

    fig.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="Overbought 70")
    fig.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="Oversold 30")
    fig.add_hline(y=75, line_dash="dot", line_color="darkred", annotation_text="Extreme 75")
    fig.add_hline(y=25, line_dash="dot", line_color="darkgreen", annotation_text="Extreme 25")

    if marker_times:
        label_of = {ts: lbl for ts, lbl in zip(chart_slice.index, x_labels)}
        xs, ys, texts, colors = [], [], [], []
        for t, r, lbl, c in zip(marker_times, marker_rsi, marker_labels, marker_colors):
            if t in label_of:
                xs.append(label_of[t]); ys.append(r); texts.append(lbl); colors.append(c)
        if xs:
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="markers+text", name="Signal",
                marker=dict(size=13, color=colors,
                           symbol=["triangle-up" if c == "#10b981" else "triangle-down" for c in colors]),
                text=texts, textposition="top center"
            ))

    fig.update_layout(title=title, height=320, margin=dict(l=10, r=10, t=40, b=10),
                      xaxis=dict(type="category", title="", tickangle=-45, nticks=12),
                      yaxis_title="RSI")
    return fig


def _last5_table(rows):
    if not rows:
        st.info("No signals in the lookback window.")
        return
    df = pd.DataFrame(rows)

    def _style(row):
        color = "#10b981" if row["Side"] in ("LONG", "BUY", "Bullish") else "#ef4444"
        return [f"background-color:{color};color:white;font-weight:700;" if col == "Side" else ""
                for col in row.index]

    st.dataframe(df.style.apply(_style, axis=1), use_container_width=True, hide_index=True)


def _numbered(sig_df):
    """Chronological order (oldest first) with a '#' 1..N — same numbers the
    chart markers use, so a table row and its chart marker can be matched up."""
    chrono = sig_df.tail(5).copy()
    chrono["#"] = range(1, len(chrono) + 1)
    return chrono


# ══════════════════════════════════════════════════════════════════════════════
# Signal computation — done once here, reused by the dashboard below AND by
# each system's own section further down (single source of truth).
# ══════════════════════════════════════════════════════════════════════════════

df_fade = rfb.compute_rsi(df_hourly, RSI_PERIOD)
prev_rsi = df_fade["rsi"].shift(1)
fade_short = (prev_rsi < 75) & (df_fade["rsi"] >= 75)
fade_long = (prev_rsi > 25) & (df_fade["rsi"] <= 25)
fade_sig = df_fade[fade_short.fillna(False) | fade_long.fillna(False)].copy()
fade_sig["side"] = ["SHORT" if fade_short.loc[i] else "LONG" for i in fade_sig.index]

df_div = rfb.detect_divergence_signals(df_hourly, RSI_PERIOD, div_lookback=20, div_min_gap=2.0)
div_sig = df_div[df_div["bullish"] | df_div["bearish"]].copy()
div_sig["side"] = ["Bullish" if b else "Bearish" for b in div_sig["bullish"]]

df_piv, piv_signals = analyze_hourly_rsi(df_hourly, rsi_period=RSI_PERIOD, lookback=3)


def _rsi_zone(rsi_val):
    """Same zone thresholds as the RSI Fade system (75/25 extreme, 70/30 caution)."""
    if rsi_val < 25:
        return "🟢", "OVERSOLD"
    elif rsi_val < 30:
        return "🟡", "CAUTION"
    elif rsi_val > 75:
        return "🟢", "OVERBOUGHT"
    elif rsi_val > 70:
        return "🟡", "CAUTION"
    else:
        return "⚫", "NEUTRAL"


def _trend_arrow(prev, curr):
    if curr > prev + 2:
        return "↗ Rising"
    elif curr < prev - 2:
        return "↘ Falling"
    else:
        return "→ Flat"


# ══════════════════════════════════════════════════════════════════════════════
# LIVE RSI DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.header("📊 Live RSI Dashboard")
st.caption("Real-time 60-minute & 30-minute RSI, plus the current read from each of the 3 signal systems below.")

rsi_60m_current = df_fade["rsi"].iloc[-1]
rsi_60m_prev = df_fade["rsi"].iloc[-2] if len(df_fade) > 1 else rsi_60m_current
price_60m = df_fade["close"].iloc[-1]

if df_30m_hist is not None and len(df_30m_hist) > 1:
    rsi_30m_current = df_30m_hist["rsi"].iloc[-1]
    rsi_30m_prev = df_30m_hist["rsi"].iloc[-2]
    price_30m = df_30m_hist["close"].iloc[-1]
else:
    rsi_30m_current = rsi_30m_prev = price_30m = None

dash_col1, dash_col2 = st.columns(2)
with dash_col1:
    zone_emoji, zone_label = _rsi_zone(rsi_60m_current)
    trend = _trend_arrow(rsi_60m_prev, rsi_60m_current)
    st.metric(f"{zone_emoji} 60-MINUTE RSI", f"{rsi_60m_current:.1f}",
             delta=f"{rsi_60m_current - rsi_60m_prev:.1f} — {trend}", delta_color="off")
    st.caption(f"Zone: {zone_label} | Spot: {price_60m:.0f}")

with dash_col2:
    if rsi_30m_current is not None:
        zone_emoji, zone_label = _rsi_zone(rsi_30m_current)
        trend = _trend_arrow(rsi_30m_prev, rsi_30m_current)
        st.metric(f"{zone_emoji} 30-MINUTE RSI", f"{rsi_30m_current:.1f}",
                 delta=f"{rsi_30m_current - rsi_30m_prev:.1f} — {trend}", delta_color="off")
        st.caption(f"Zone: {zone_label} | Spot: {price_30m:.0f}")
    else:
        st.warning("30m data unavailable")

# ── Combined read: current stance of each of the 3 systems ─────────────────────
st.markdown("**Combined signal read — current stance of all 3 systems**")

fade_zone_emoji, fade_zone_label = _rsi_zone(rsi_60m_current)
fade_stance = "LONG-leaning" if rsi_60m_current <= 30 else "SHORT-leaning" if rsi_60m_current >= 70 else "Neutral"
div_stance = div_sig["side"].iloc[-1] if not div_sig.empty else "No signal yet"
piv_stance = piv_signals[-1]["signal"] if piv_signals else "No signal yet"

bull_words = ("LONG-leaning", "Bullish", "BUY")
bear_words = ("SHORT-leaning", "Bearish", "SELL")
n_bull = sum(s in bull_words for s in (fade_stance, div_stance, piv_stance))
n_bear = sum(s in bear_words for s in (fade_stance, div_stance, piv_stance))

combo_col1, combo_col2, combo_col3 = st.columns(3)
for col, label, stance in [
    (combo_col1, "1. RSI Fade (zone)", fade_stance),
    (combo_col2, "2. Pure Divergence (last signal)", div_stance),
    (combo_col3, "3. Pivot Breakout (last signal)", piv_stance),
]:
    with col:
        color = "#10b981" if stance in bull_words else "#ef4444" if stance in bear_words else "#94a3b8"
        st.markdown(
            f"<div style='padding:10px;border-radius:6px;background-color:{color};"
            f"color:white;text-align:center;font-weight:700;'>{label}<br>{stance}</div>",
            unsafe_allow_html=True,
        )

if n_bull > n_bear:
    st.success(f"✅ **{n_bull} of 3 systems bullish** — {fade_stance} / {div_stance} / {piv_stance}")
elif n_bear > n_bull:
    st.error(f"🔻 **{n_bear} of 3 systems bearish** — {fade_stance} / {div_stance} / {piv_stance}")
else:
    st.info(f"⭕ **No majority** — {fade_stance} / {div_stance} / {piv_stance}")

with st.expander("ℹ️ Reference — what these 3 read-outs mean", expanded=False):
    st.markdown("""
The 3 systems are not measuring the same kind of thing, so read the combined tally
as "3 different lenses on the same market," not a single unified signal:

- **RSI Fade (zone)** is a *momentary* read — where hourly RSI sits right now.
  LONG-leaning below 30, SHORT-leaning above 70, Neutral in between. This can flip
  every candle as RSI moves; it does not "hold a position."
- **Pure Divergence (last signal)** is a *persistent* read — the direction of the
  most recent bullish/bearish divergence, which (per that system's own backtest
  logic) is treated as still "held" until an opposite divergence fires. It can stay
  the same stance for days.
- **Pivot Breakout (last signal)** is the same persistent style — the direction of
  the most recent BUY/SELL pivot break, held until reversed.

Because two of the three are "sticky" (persistent) and one is momentary, 3/3 or 0/3
agreement is more meaningful than a 2/1 split — a 2/1 can just mean the momentary
Fade read hasn't caught up yet with the other two, or is passing through on its way
to agreeing or disagreeing. Treat this as context, not a trade trigger on its own.
""")


# ══════════════════════════════════════════════════════════════════════════════
# 1. RSI FADE — 75/25 zone cross (contrarian)
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.header("1. RSI Fade — 75/25 Zone Cross")
st.caption("Contrarian: RSI crossing INTO overbought (≥75) → SHORT. RSI crossing INTO oversold (≤25) → LONG.")

fade_last5 = _numbered(fade_sig)
fade_rows = [
    {"#": int(r["#"]), "Time": ts.strftime("%d %b %H:%M"), "Side": r["side"],
     "RSI": f"{r['rsi']:.1f}", "Price": f"{r['close']:.0f}"}
    for ts, r in fade_last5.iterrows()
][::-1]   # display newest-first; "#" still carries the chronological chart number

col_a, col_b = st.columns([1, 1])
with col_a:
    st.subheader("Last 5 signals")
    _last5_table(fade_rows)
with col_b:
    fig = _mini_rsi_chart(
        df_fade, "RSI Fade — signals 1-5", line_color="#3b82f6",
        marker_times=fade_last5.index.tolist(), marker_rsi=fade_last5["rsi"].tolist(),
        marker_labels=[str(n) for n in fade_last5["#"]],
        marker_colors=["#ef4444" if s == "SHORT" else "#10b981" for s in fade_last5["side"]],
    )
    st.plotly_chart(fig, use_container_width=True, key="chart_fade")


# ══════════════════════════════════════════════════════════════════════════════
# 2. PURE DIVERGENCE — divergence is the only entry rule
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.header("2. Pure Divergence")
st.caption(
    "Price makes a fresh 20-bar extreme that RSI does NOT confirm. Bullish divergence "
    "→ LONG. Bearish divergence → SHORT. No RSI zone gate."
)

div_last5 = _numbered(div_sig)
div_rows = [
    {"#": int(r["#"]), "Time": ts.strftime("%d %b %H:%M"), "Side": r["side"],
     "RSI": f"{r['rsi']:.1f}", "Price": f"{r['close']:.0f}"}
    for ts, r in div_last5.iterrows()
][::-1]

col_a, col_b = st.columns([1, 1])
with col_a:
    st.subheader("Last 5 signals")
    _last5_table(div_rows)
with col_b:
    fig = _mini_rsi_chart(
        df_div, "Pure Divergence — signals 1-5", line_color="#f59e0b",
        marker_times=div_last5.index.tolist(), marker_rsi=div_last5["rsi"].tolist(),
        marker_labels=[str(n) for n in div_last5["#"]],
        marker_colors=["#10b981" if s == "Bullish" else "#ef4444" for s in div_last5["side"]],
    )
    st.plotly_chart(fig, use_container_width=True, key="chart_div")


# ══════════════════════════════════════════════════════════════════════════════
# 3. HL/LH PIVOT BREAKOUT
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.header("3. HL/LH Pivot Breakout")
st.caption("RSI breaks above the last Lower High (LH) → BUY. RSI breaks below the last Higher Low (HL) → SELL.")

piv_chrono5 = piv_signals[-5:] if piv_signals else []   # oldest first
piv_rows = [
    {
        "#": i + 1,
        "Time": df_piv.index[s["index"]].strftime("%d %b %H:%M"),
        "Side": s["signal"],
        "RSI": f"{s['rsi_at_signal']:.1f}",
        "Pivot": f"{s['pivot_level']:.1f}",
    }
    for i, s in enumerate(piv_chrono5)
][::-1]

col_a, col_b = st.columns([1, 1])
with col_a:
    st.subheader("Last 5 signals")
    _last5_table(piv_rows)
with col_b:
    marker_times = [df_piv.index[s["index"]] for s in piv_chrono5]
    marker_rsi = [s["rsi_at_signal"] for s in piv_chrono5]
    marker_side = [s["signal"] for s in piv_chrono5]
    fig = _mini_rsi_chart(
        df_piv, "Pivot Breakout — signals 1-5", line_color="#a855f7",
        marker_times=marker_times, marker_rsi=marker_rsi,
        marker_labels=[str(i + 1) for i in range(len(piv_chrono5))],
        marker_colors=["#10b981" if s == "BUY" else "#ef4444" for s in marker_side],
    )
    st.plotly_chart(fig, use_container_width=True, key="chart_pivot")


# ── RSI Trend mini-charts (last 5 trading days) ────────────────────────────────
st.divider()
mini_col1, mini_col2 = st.columns(2)

with mini_col1:
    fig_60m = _mini_rsi_chart(df_fade, "60m RSI Trend (last 5 trading days)", line_color="#3b82f6")
    st.plotly_chart(fig_60m, use_container_width=True, key="chart_60m_trend")

with mini_col2:
    if df_30m_hist is not None and len(df_30m_hist) > 1:
        fig_30m = _mini_rsi_chart(df_30m_hist, "30m RSI Trend (last 5 trading days)", line_color="#f59e0b")
        st.plotly_chart(fig_30m, use_container_width=True, key="chart_30m_trend")
    else:
        st.warning("30m data unavailable")

# ── Historical RSI Status table (finalized styling — see CLAUDE.md) ────────────
st.divider()
st.subheader("Historical RSI Status (Last 5 Trading Days)")
st.caption("60m/30m/15m RSI with Divergence")


def _rsi_css(val, trend=0):
    """
    RSI styling.
    Background by zone: RED ≥70 (overbought), GREEN ≤30 (oversold), GRAY neutral.
    Text by trend vs previous candle: RED if lower (trend=-1), GREEN if higher
    (trend=+1), dark slate if flat/first candle (trend=0).
    """
    try:
        rsi = float(val)
        if rsi >= 70:
            bg_color = "#fca5a5"
        elif rsi <= 30:
            bg_color = "#86efac"
        else:
            bg_color = "#e2e8f0"
        if trend < 0:
            text_color, text_weight = "#dc2626", "800"
        elif trend > 0:
            text_color, text_weight = "#15803d", "800"
        else:
            text_color, text_weight = "#334155", "600"
        return f"background-color:{bg_color};color:{text_color};font-weight:{text_weight};"
    except Exception:
        return ""


def _div_css(val):
    """Color divergence cells: Green=Bullish (LONG), Red=Bearish (SHORT)"""
    s = str(val)
    if "Bull" in s:
        return "background-color:#10b981;color:#ffffff;font-weight:800;"
    elif "Bear" in s:
        return "background-color:#ef4444;color:#ffffff;font-weight:800;"
    return ""


def _signal_css(val):
    """Color signal column: Green for LONG, Red for SHORT"""
    s = str(val)
    if "LONG" in s:
        return "background-color:#d1fae5;color:#065f46;font-weight:800;"
    elif "SHORT" in s:
        return "background-color:#fee2e2;color:#7f1d1d;font-weight:800;"
    return ""


def _detect_divergence(df, lookback=20, min_gap=2.0):
    """Detect bullish/bearish divergence: price extreme not confirmed by RSI"""
    if df is None or df.empty or 'rsi' not in df.columns:
        return pd.Series("", index=df.index if df is not None and not df.empty else pd.Index([]))
    d = df.copy()
    rsi = d['rsi'].fillna(0)
    prior_low_price = d['low'].shift(1).rolling(lookback).min()
    prior_low_rsi = rsi.shift(1).rolling(lookback).min()
    prior_high_price = d['high'].shift(1).rolling(lookback).max()
    prior_high_rsi = rsi.shift(1).rolling(lookback).max()
    bullish_div = (d['low'] <= prior_low_price) & (rsi > prior_low_rsi + min_gap)
    bearish_div = (d['high'] >= prior_high_price) & (rsi < prior_high_rsi - min_gap)
    div_signal = pd.Series("", index=d.index, dtype=str)
    div_signal[bullish_div] = "▲ Bull"
    div_signal[bearish_div] = "▼ Bear"
    return div_signal


def _build_hist_table(df_60m, df_30m, df_15m):
    """Build historical RSI table with combined RSI+Div columns for 60m, 30m, 15m"""
    if df_60m is None or df_60m.empty:
        df_60m = pd.DataFrame()
    if df_30m is None or df_30m.empty:
        df_30m = pd.DataFrame()
    if df_15m is None or df_15m.empty:
        df_15m = pd.DataFrame()

    rows = []
    for df in [df_60m, df_30m, df_15m]:
        if not df.empty and not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

    div_60m = _detect_divergence(df_60m) if not df_60m.empty else pd.Series()
    div_30m = _detect_divergence(df_30m) if not df_30m.empty else pd.Series()
    div_15m = _detect_divergence(df_15m) if not df_15m.empty else pd.Series()

    if not df_30m.empty:
        unique_dates = sorted(set(df_30m.index.date), reverse=True)[:5]
    elif not df_60m.empty:
        unique_dates = sorted(set(df_60m.index.date), reverse=True)[:5]
    else:
        return pd.DataFrame()

    for date in sorted(unique_dates, reverse=True):
        rows.append({'Time': f"📅 {date.strftime('%A, %B %d, %Y')}",
                     '60m': '', '30m': '', '15m': '', 'Signal': ''})

        if not df_15m.empty:
            day_15m = df_15m[df_15m.index.date == date]
            day_30m = df_30m[df_30m.index.date == date] if not df_30m.empty else pd.DataFrame()
            day_60m = df_60m[df_60m.index.date == date] if not df_60m.empty else pd.DataFrame()
            day_div_15m = div_15m[div_15m.index.date == date] if not div_15m.empty else pd.Series()
            day_div_30m = div_30m[div_30m.index.date == date] if not div_30m.empty else pd.Series()
            day_div_60m = div_60m[div_60m.index.date == date] if not div_60m.empty else pd.Series()

            shown_60m_hours = set()
            shown_30m_times = set()

            day_15m_reversed = day_15m.iloc[::-1]
            for idx_in_reversed, (idx_15m, row_15m) in enumerate(day_15m_reversed.iterrows()):
                rsi_15m = row_15m['rsi']
                if pd.isna(rsi_15m):
                    continue

                time_str = idx_15m.strftime('%H:%M')
                div_15m_str = day_div_15m.get(idx_15m, "") if not day_div_15m.empty else ""
                col_15m = f"{rsi_15m:.1f}" + (f" {div_15m_str}" if div_15m_str else "")

                hour_15m = idx_15m.hour
                minute_15m = idx_15m.minute
                target_30m_minute = 15 if minute_15m < 30 else 45
                time_key_30m = f"{hour_15m}:{target_30m_minute:02d}"
                col_30m = ""
                if time_key_30m not in shown_30m_times and not day_30m.empty:
                    shown_30m_times.add(time_key_30m)
                    for idx_30m, row_30m in day_30m.iterrows():
                        if idx_30m.hour == hour_15m and idx_30m.minute == target_30m_minute:
                            try:
                                rsi_30m = row_30m['rsi'] if 'rsi' in row_30m.index else None
                            except (KeyError, AttributeError):
                                rsi_30m = None
                            if rsi_30m is not None and not pd.isna(rsi_30m):
                                div_30m_str = day_div_30m.get(idx_30m, "") if not day_div_30m.empty else ""
                                col_30m = f"{rsi_30m:.1f}" + (f" {div_30m_str}" if div_30m_str else "")
                            break

                col_60m = ""
                if hour_15m not in shown_60m_hours and not day_60m.empty:
                    shown_60m_hours.add(hour_15m)
                    for idx_60m, row_60m in day_60m.iterrows():
                        if idx_60m.hour == hour_15m:
                            rsi_60m = row_60m.get('rsi') if isinstance(row_60m, dict) else row_60m['rsi']
                            if not pd.isna(rsi_60m):
                                div_60m_str = day_div_60m.get(idx_60m, "") if not day_div_60m.empty else ""
                                col_60m = f"{rsi_60m:.1f}" + (f" {div_60m_str}" if div_60m_str else "")
                            break

                signal = ""
                if minute_15m % 30 == 0 and not day_30m.empty:
                    matching_30m = day_30m[(day_30m.index.hour == hour_15m) & (day_30m.index.minute == minute_15m)]
                    if len(matching_30m) > 0:
                        rsi_30m_sig = matching_30m['rsi'].iloc[-1]
                        if not pd.isna(rsi_30m_sig):
                            prev_30m_idx = day_30m.index.get_loc(matching_30m.index[-1])
                            prev_rsi_30m = day_30m['rsi'].iloc[prev_30m_idx - 1] if prev_30m_idx > 0 else rsi_30m_sig
                            if rsi_30m_sig < 25 and prev_rsi_30m > 30:
                                signal = f"🟢 LONG {time_str}"
                            elif rsi_30m_sig > 75 and prev_rsi_30m < 70:
                                signal = f"🔴 SHORT {time_str}"
                            elif rsi_30m_sig < 22 and prev_rsi_30m > 25:
                                signal = f"↓ ROLL DOWN {time_str}"
                            elif rsi_30m_sig > 78 and prev_rsi_30m < 75:
                                signal = f"↑ ROLL UP {time_str}"

                rows.append({'Time': time_str, '60m': col_60m, '30m': col_30m, '15m': col_15m, 'Signal': signal})

    return pd.DataFrame(rows)


hist_table = _build_hist_table(df_fade, df_30m_hist, df_15m_hist)

if not hist_table.empty:
    def _style_rsi_table(df):
        styler = df.style

        def _prev_rsi_below(row_loc, col):
            import re
            for j in range(row_loc + 1, len(df)):
                v = df.iloc[j][col]
                if v:
                    m = re.search(r'(\d+\.?\d*)', str(v))
                    if m:
                        try:
                            return float(m.group(1))
                        except ValueError:
                            continue
            return None

        def _rsi_trend(row_loc, col, curr_val):
            try:
                curr = float(curr_val)
            except (TypeError, ValueError):
                return 0
            prev = _prev_rsi_below(row_loc, col)
            if prev is None:
                return 0
            if curr < prev:
                return -1
            if curr > prev:
                return 1
            return 0

        def _combined_rsi_div_row(row):
            import re
            styles = [''] * len(row)
            row_loc = df.index.get_loc(row.name)
            for i, col in enumerate(row.index):
                if col in ('60m', '30m', '15m'):
                    cell_val = row[col]
                    if cell_val:
                        # Divergence marker takes priority over the RSI-zone background —
                        # a cell can carry both (e.g. "35.4 ▲ Bull"), and the whole point
                        # of the marker is to stand out regardless of which zone RSI is in.
                        if "Bull" in str(cell_val) or "Bear" in str(cell_val):
                            styles[i] = _div_css(cell_val)
                        else:
                            m = re.search(r'(\d+\.?\d*)', str(cell_val))
                            if m:
                                trend = _rsi_trend(row_loc, col, m.group(1))
                                styles[i] = _rsi_css(m.group(1), trend)
                    else:
                        styles[i] = ''
                else:
                    styles[i] = ''
            return styles

        def _signal_row(row):
            styles = [''] * len(row)
            for i, col in enumerate(row.index):
                styles[i] = _signal_css(row[col]) if col == 'Signal' else ''
            return styles

        styler = styler.apply(_combined_rsi_div_row, axis=1)
        styler = styler.apply(_signal_row, axis=1)
        return styler

    styled_table = _style_rsi_table(hist_table)
    st.dataframe(styled_table, use_container_width=True, height=600, hide_index=True)
    st.download_button(
        "⬇ Download Historical RSI as CSV", hist_table.to_csv(index=False).encode('utf-8'),
        file_name="nifty_rsi_historical_5days.csv", mime="text/csv", key="hist_rsi_download",
    )
else:
    st.warning("Not enough historical data to display table.")


# ══════════════════════════════════════════════════════════════════════════════
# FINDINGS — what backtesting on each system found (static reference, not re-run)
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.header("Findings — what the backtests on each system found")
st.caption(
    "These are the results already gathered from the (now retired) dedicated pages for "
    "each system. Kept as static reference rather than re-runnable controls; the "
    "interactive backtest tooling that produced them still exists in git history."
)

with st.expander("1. RSI Fade 75/25 — findings", expanded=False):
    st.markdown("""
No single fixed calibration was finalized for the plain 75/25 fade — unlike the other
two systems below, its backtest tooling stayed fully interactive (adjustable OB/OS
threshold pairs, stop/target, entry mode, divergence filter, cooldown filter, threshold
scan across 65/35 → 80/20 on both 30m and hourly) and was never run to a single
recommended settled number.

**One real finding from a live run (March 2026):** plain OB/OS fades kept getting
stopped out during a genuine multi-day one-sided decline — price and RSI were both
making fresh lows in lockstep (a real trend, not a stalling move), so the fade kept
re-triggering into the same losing side. Two mitigations were tested against that
failure mode:
- **Require divergence to enter** — blocked the March pile-on entirely, but also
  blocked most of the best month (Feb 2026); fast V-shaped reversals don't leave RSI
  time to diverge either.
- **Cooldown between same-direction re-entries** — a less blunt fix: take the first
  fade of a stretch, refuse to re-enter the same direction until a cooldown window
  passes (clears immediately on a reversal). Doesn't touch the first trade of any
  stretch, so should cost less of the good trades — this was the more promising
  direction but wasn't taken to a final number either.

If you want a fixed recommended threshold/stop for this system the way the other two
have, that requires actually running the threshold scan to a conclusion — the tool to
do it (`analytics/rsi_fade_backtest.py: simulate_fade_trades` /
`threshold_scan` / `compare_timeframes`) is unchanged and still callable.
""")

with st.expander("2. Pure Divergence — findings", expanded=False):
    st.markdown("""
Divergence alone as the entry (no RSI zone gate), holding until the opposite
divergence fires (no midline exit, no time stop) — tested with and without a fixed
points stop, re-simulated per stop value (not estimated by clipping a finished trade
log, which distorts results because it can't create the extra re-entries a real stop
produces).

**No stop (baseline):**
| Timeframe | Trades | Win rate | Expectancy | Profit factor | Total P&L | Max DD |
|---|---|---|---|---|---|---|
| 60m (hourly) | 28 | 64.3% | +40.7 pts/trade | 1.25 | +1,138 pts | −2,254 pts |
| 30m | 25 | 60.0% | −48.6 pts/trade | 0.77 | −1,214 pts | −2,456 pts |

**With the optimum stop (from a full stop-loss re-simulation, not a clipped estimate):**
| Timeframe | Optimum stop | Trades | Win rate | Expectancy | Profit factor | Total P&L | Max DD |
|---|---|---|---|---|---|---|---|
| **60m (hourly)** | **100 pts** | 65 | 33.8% | **+71.3 pts/trade** | 2.08 | +4,632 pts | −671 pts |
| 30m | 150 pts | 54 | 37.0% | +39.3 pts/trade | 1.42 | +2,121 pts | −1,567 pts |

On hourly, a 100-pt stop more than quadruples total P&L vs no stop and cuts max
drawdown by ~70% — despite a lower win rate, because losses are capped small (exactly
the stop) while winners are left to run (avg win ≈ 406 pts at that stop). The
**100–250 pt band is the stable region** on hourly (all outperform no-stop); very
tight stops (50 pts) look good on a naive read but push win rate down to ~19–20% and
sit at the edge of what was tested — treat that edge as curve-fit risk, not a real
optimum. 300 pts is a genuine dip in the data, not a typo — don't use it.

⚠️ These numbers came from one ~1-year hourly sample (~6 months for 30m, Kite's
retention limit on that timeframe) — a real edge, but not a large one statistically.
""")

with st.expander("3. HL/LH Pivot Breakout — findings", expanded=False):
    st.markdown("""
**Last calibration: 28 Jul 2026 · 90 trades · 365 days of hourly candles, Nifty-50.**

**Recommended configuration:**
- **Entry filter — OS 40 / OB 55** (15-point RSI spread, narrower than the default
  30/70): 66.7% win rate, 24 trades, 2.30:1 reward:risk, +19.29% total P&L, profit
  factor 4.60x, expectancy +0.804%/trade.
- **Confirmation — none** (immediate entry on the OS/OB filter; it already screens out
  most false breakouts). Add a 2-candle wait only if too many trades fire.
- **Stop loss — 75 points** (practical): 4.79:1 R:R, +51.09% P&L. A 25-point stop is
  more aggressive (13.32:1 R:R, +59.26% P&L) but risks getting whipsawed on hourly
  noise.

| Stop loss | R:R | Win rate | Total P&L | Expectancy |
|---|---|---|---|---|
| 25 pts | 13.32:1 | 51.1% | +59.26% | +0.658%/trade |
| 50 pts | 6.87:1 | 51.1% | +54.96% | +0.611%/trade |
| **75 pts** | **4.79:1** | **51.1%** | **+51.09%** | **+0.568%/trade** |
| 100 pts | 3.71:1 | 51.1% | +47.39% | +0.527%/trade |
| 150 pts | 2.68:1 | 51.1% | +41.09% | +0.457%/trade |

**Retest triggers** (from the original calibration notes — worth rechecking
periodically even with the live tooling retired): after every 100 new live trades;
if live win rate drops below 55% (vs 66.7% backtest); if avg win/loss ratio drops
below 1.5:1; on a VIX spike (+30% vs 14-day avg); or if it's been 90+ days since the
last calibration.
""")


# ══════════════════════════════════════════════════════════════════════════════
# RESTORE — bring back a retired page
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
with st.expander("🗄️ Bring back a retired page (04 / 28 / 31 / 33)", expanded=False):
    st.markdown("""
This page replaced 3 older pages on **30 Jul 2026**. Nothing is deleted forever —
git keeps every version, so any of them can be restored exactly as they last looked.

Run this from the repo root (adjust the filename for whichever page you want back),
then commit and push like normal:

```bash
git show abe6634:pages/04_Hourly_RSI_Breakout.py     > pages/04_Hourly_RSI_Breakout.py
git show 189b6c0:pages/28_RSI_Swing_Fade.py          > pages/28_RSI_Swing_Fade.py
git show 189b6c0:pages/31_RSI_Divergence_Backtest.py > pages/31_RSI_Divergence_Backtest.py
git show 449aca4:pages/33_RSI_Leadtime_Backtest.py   > pages/33_RSI_Leadtime_Backtest.py
```

**What each one had:**
- **Page 04 — Hourly RSI Breakout.** HL/LH pivot breakout backtest, plus an OS/OB
  entry filter (mobile-visible sliders), RSI-wait and candle-wait confirmation
  filters — none of which made it into this page's findings writeup above.
- **Page 28 — RSI Swing Fade.** Fully interactive fade backtest: adjustable OB/OS
  thresholds, stop/target, entry mode, divergence filter, cooldown filter, a
  threshold scan across 65/35→80/20 on both 30m and hourly, plus the finalized
  Historical RSI Status table (60m/30m/15m combined) — that table's logic is
  already ported into this page, further up.
- **Page 31 — RSI Divergence Backtest.** The pure-divergence backtest with the
  full stop-loss sweep tool (re-simulates per stop value, not just clipped
  losses) and CSV export of both the trade log and the sweep table — the
  numbers it produced are summarized in the findings section above, but the
  interactive sweep tool itself isn't on this page.
- **Page 33 — RSI Lead-Time & Strike-Tightening Backtest** *(retired 31 Jul 2026)*.
  Produced the strike-tightening rule pinned at the top of this page. Two scans:
  **Q1** — entry on the signal day, exit at Tuesday expiry (near 5–9 sessions /
  biweekly 10–14), breach % at every OTM distance 1.00→4.50% for all 5 systems and
  both sides, plus the cross-test that proved it a direction rather than volatility
  signal. **Q2** — the lead-time test, which found these signals give **no** usable
  early warning of a breach (hit rates look high only because a signal is active on
  25–82% of all days). Restore this page to re-calibrate at the retest triggers.

**The backtest engine was NOT deleted.** `analytics/strike_survival_backtest.py`
is still in the repo — page 33 was only ever a thin UI over it, so restoring the
page above is enough to re-run everything. That module carries the guards that
matter (a false-positive trap where the naive equal-risk metric reports a
0.75–2.00% "pickup" on pure noise, the weekday hold-length confound under
expiry-anchored exits, and a lazy-matplotlib crash), all verified against
synthetic data with known answers.

If you're not comfortable running git commands yourself, just tell me "bring back
page 28" (or whichever) in a session and I'll do it.
""")
