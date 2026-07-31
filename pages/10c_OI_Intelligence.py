# pages/10c_OI_Intelligence.py — Page 10C: OI Intelligence
# Buildup quadrants · Volume vs OI conviction · Concentration · History-backed drift
#
# Split from pages 10 / 10B on purpose: those show TODAY'S SNAPSHOT, this shows
# WHAT CHANGED — within today's session and across recorded days. Mixing the two on
# one page makes it easy to misread a stored value as a live one.
import datetime

import pandas as pd
import plotly.graph_objects as go
import pytz
import streamlit as st
from streamlit_autorefresh import st_autorefresh

import ui.components as ui

st.set_page_config(page_title="P10C · OI Intelligence", layout="wide")
st_autorefresh(interval=60_000, key="p10c")
st.title("Page 10C — OI Intelligence")
st.caption("Is that wall real? · Buildup quadrants · Volume vs OI · Concentration · Drift over time")

from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)
if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

from data.live_fetcher import get_nifty_spot, get_dual_expiry_chains
from analytics.oi_analytics import (
    buildup_table, buildup_summary, volume_oi_table, concentration,
    history_series, pcr_percentile, drift, intraday_frame,
    chain_history_matrix, wall_migration, wall_migration_summary, strike_oi_growth,
    LONG_BUILDUP, SHORT_BUILDUP, LONG_UNWIND, SHORT_COVER, FLAT,
)

spot = get_nifty_spot()
if spot == 0:
    from data.live_fetcher import get_nifty_daily
    df_t = get_nifty_daily()
    spot = float(df_t["close"].iloc[-1]) if not df_t.empty else 23000.0

chains   = get_dual_expiry_chains(spot)
near_exp = chains["near_expiry"]; far_exp = chains["far_expiry"]
near_dte = chains["near_dte"];   far_dte = chains["far_dte"]

if chains["far"].empty:
    st.error(
        f"⚠️ Far option chain unavailable for **{far_exp}** ({far_dte} DTE). "
        "Kite returned no usable data — nothing is shown rather than something wrong.\n\n"
        "Check the Kite login on the Home page, then refresh."
    )
    st.stop()

# Log an intraday point (same as page 10B — whichever page you open keeps the
# session record going). Deduped to one per minute inside the logger.
try:
    from data.oi_history import log_intraday_snapshot
    log_intraday_snapshot(chains["near"], chains["far"], spot,
                          near_expiry=near_exp, far_expiry=far_exp,
                          near_dte=near_dte, far_dte=far_dte)
except Exception:
    pass

side_choice = st.radio(
    "Expiry",
    [f"Far — {far_exp} ({far_dte} DTE) ← YOUR TRADE",
     f"Near — {near_exp} ({near_dte} DTE) — Intelligence"],
    horizontal=True,
)
is_far   = "Far" in side_choice
df_chain = chains["far"] if is_far else chains["near"]
side_key = "far" if is_far else "near"

if df_chain.empty:
    st.warning(f"Near chain ({near_exp}) unavailable — switch to Far.")
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Buildup: is the wall real?
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 1 — Buildup: is that wall real?",
                  "Open interest alone cannot tell writing from buying — premium direction can")

ui.simple_technical(
    "Open interest going UP does not tell you who did it. If traders BUY calls, OI rises. "
    "If traders WRITE calls, OI also rises. The two mean opposite things for your position — "
    "writing builds a ceiling that protects your short call, buying is a bet that price breaks "
    "through it.\n\nThe premium tells them apart. OI up with premium DOWN means fresh writing "
    "(sellers pressing, price falling). OI up with premium UP means fresh buying. And when OI "
    "FALLS while premium rises, writers are buying back — the wall is dissolving, which is the "
    "earliest warning you can get.",
    "OI ↑ & premium ↑ = Long buildup (fresh buying)\n"
    "OI ↑ & premium ↓ = Short buildup (fresh WRITING — wall building)\n"
    "OI ↓ & premium ↓ = Long unwinding (buyers exiting)\n"
    "OI ↓ & premium ↑ = Short covering (writers buying back — wall DISSOLVING)\n"
    "Noise bands: |OI change| < 1% or |premium change| < 2% → Flat"
)
st.markdown("")

bt  = buildup_table(df_chain)
bsum = buildup_summary(bt, spot)

if not bt.empty and bsum:
    _BIAS_COL = {"bull_ce": "green", "bear_ce": "red", "bull_pe": "green", "bear_pe": "red"}
    c1, c2 = st.columns(2)
    with c1:
        ui.metric_card(
            "ABOVE SPOT (your CE leg)", bsum["ce_dominant"],
            sub=f"{bsum['ce_note']} · {bsum['ce_share']*100:.0f}% of call OI above spot",
            color=_BIAS_COL.get(bsum["ce_bias"], "default"),
        )
    with c2:
        ui.metric_card(
            "BELOW SPOT (your PE leg)", bsum["pe_dominant"],
            sub=f"{bsum['pe_note']} · {bsum['pe_share']*100:.0f}% of put OI below spot",
            color=_BIAS_COL.get(bsum["pe_bias"], "default"),
        )

    # Warn loudly on the one pattern that most threatens a short strike.
    if bsum["ce_dominant"] == SHORT_COVER:
        ui.alert_box("CEILING DISSOLVING",
                     "Call writers above spot are buying back their positions. The resistance "
                     "that protects your short CE is being removed — this usually precedes an "
                     "upward move. Watch the CE leg.", level="danger")
    if bsum["pe_dominant"] == SHORT_COVER:
        ui.alert_box("FLOOR DISSOLVING",
                     "Put writers below spot are buying back. The support under your short PE "
                     "is being removed — this usually precedes a fall. Watch the PE leg.",
                     level="danger")
    if bsum["ce_dominant"] == SHORT_BUILDUP and bsum["pe_dominant"] == SHORT_BUILDUP:
        ui.alert_box("BOTH SIDES BEING WRITTEN",
                     "Fresh writing above AND below spot — the market is selling the range. "
                     "This is the most favourable backdrop for an iron condor.", level="success")

    st.markdown("")
    _BUILDUP_COL = {
        LONG_BUILDUP:  "#dc2626",   # buying against the wall — bad for a short there
        SHORT_BUILDUP: "#16a34a",   # writing — wall building
        LONG_UNWIND:   "#65a30d",   # bets closing — mildly good
        SHORT_COVER:   "#ea580c",   # wall dissolving — warning
        FLAT:          "#94a3b8",
    }

    def _style_buildup(v):
        return f"background-color:{_BUILDUP_COL.get(str(v), '#94a3b8')};color:white;font-weight:600"

    ce_s = st.session_state.get("ce_short", 0)
    pe_s = st.session_state.get("pe_short", 0)

    def _mark_strikes(row):
        if ce_s and row.name == ce_s: return ["border-top:2px solid #ef4444"] * len(row)
        if pe_s and row.name == pe_s: return ["border-top:2px solid #10b981"] * len(row)
        return [""] * len(row)

    show = bt[["pe_oi", "pe_oi_pct", "pe_price_pct", "pe_buildup",
               "ce_oi", "ce_oi_pct", "ce_price_pct", "ce_buildup"]].copy()
    show.columns = ["PE OI", "PE OI %", "PE Prem %", "PE Buildup",
                    "CE OI", "CE OI %", "CE Prem %", "CE Buildup"]
    styled = (show.style
              .map(_style_buildup, subset=["PE Buildup", "CE Buildup"])
              .format({"PE OI": "{:,.0f}", "CE OI": "{:,.0f}",
                       "PE OI %": "{:+.1f}", "CE OI %": "{:+.1f}",
                       "PE Prem %": "{:+.1f}", "CE Prem %": "{:+.1f}"}))
    if ce_s or pe_s:
        styled = styled.apply(_mark_strikes, axis=1)
    st.dataframe(styled, width="stretch", height=420)
    st.caption("🟢 Short buildup = wall building · 🟠 Short covering = wall dissolving · "
               "🔴 Long buildup = traders betting through this strike · "
               "🟩 Long unwinding = bets being closed")
else:
    st.info("Buildup needs premium change data — available once the chain returns "
            "previous-close prices. Refresh during market hours.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Volume vs OI, and concentration
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Conviction and concentration",
                  "Is today's activity real positioning · Are the levels sharp or smeared")

ui.simple_technical(
    "A strike can show huge volume and still mean nothing — if contracts were opened and "
    "closed the same day, open interest barely moves and nobody has committed to anything. "
    "Volume divided by open interest separates the two.\n\nConcentration answers a different "
    "question: if most of the open interest sits in three strikes, those are sharp levels worth "
    "trading against. If it is spread thinly across thirty, the 'wall' is really a soft zone.",
    "Volume ÷ OI ≥ 1.0 → churn (day trading)\n"
    "Volume ÷ OI ≥ 0.25 → active real interest\n"
    "Below → quiet, stale inventory\n"
    "Top-3 share = OI in 3 biggest strikes ÷ total\nHHI = Σ(share²), higher = more concentrated"
)
st.markdown("")

conc = concentration(df_chain)
vt   = volume_oi_table(df_chain)

c1, c2, c3, c4 = st.columns(4)
if conc:
    ce_t3 = conc.get("ce_top3"); pe_t3 = conc.get("pe_top3")
    with c1:
        ui.metric_card("CALL CONCENTRATION",
                       f"{ce_t3*100:.0f}%" if ce_t3 else "—",
                       sub="OI in the 3 biggest call strikes",
                       color="green" if (ce_t3 or 0) >= 0.35 else "amber")
    with c2:
        ui.metric_card("PUT CONCENTRATION",
                       f"{pe_t3*100:.0f}%" if pe_t3 else "—",
                       sub="OI in the 3 biggest put strikes",
                       color="green" if (pe_t3 or 0) >= 0.35 else "amber")
if not vt.empty:
    ce_ratio = float(vt["ce_ratio"].replace([float("inf")], 0).mean())
    pe_ratio = float(vt["pe_ratio"].replace([float("inf")], 0).mean())
    with c3:
        ui.metric_card("CALL VOL/OI", f"{ce_ratio:.2f}",
                       sub="Churn above 1.0 · quiet below 0.25",
                       color="red" if ce_ratio >= 1.0 else "green" if ce_ratio >= 0.25 else "default")
    with c4:
        ui.metric_card("PUT VOL/OI", f"{pe_ratio:.2f}",
                       sub="Churn above 1.0 · quiet below 0.25",
                       color="red" if pe_ratio >= 1.0 else "green" if pe_ratio >= 0.25 else "default")

if conc.get("ce_top3") and conc["ce_top3"] < 0.20:
    ui.alert_box("Call OI is smeared",
                 f"Only {conc['ce_top3']*100:.0f}% of call OI sits in the top 3 strikes. "
                 "There is no sharp ceiling — treat the 'call wall' as a soft zone, not a level.",
                 level="warning")

with st.expander("Per-strike volume and conviction"):
    if vt.empty:
        st.info("Volume data unavailable.")
    else:
        v = vt[["pe_vol", "pe_ratio", "pe_read", "ce_vol", "ce_ratio", "ce_read"]].copy()
        v.columns = ["PE Vol", "PE Vol/OI", "PE Read", "CE Vol", "CE Vol/OI", "CE Read"]
        st.dataframe(v.style.format({"PE Vol": "{:,.0f}", "CE Vol": "{:,.0f}",
                                     "PE Vol/OI": "{:.2f}", "CE Vol/OI": "{:.2f}"}),
                     width="stretch", height=340)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Today's session (intraday log)
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — Today's session",
                  "How the walls and PCR moved through the day · logged on each page load")

intra = intraday_frame()
if intra.empty or len(intra) < 2:
    st.info("Today's intraday log is still filling. A point is recorded each minute you have "
            "page 10B or 10C open — leave a tab open during market hours to build the session "
            "record. It resets every morning.")
else:
    c1, c2, c3 = st.columns(3)
    first, last = intra.iloc[0], intra.iloc[-1]
    with c1:
        ui.metric_card("POINTS LOGGED TODAY", f"{len(intra)}",
                       sub=f"{intra.index[0]} → {intra.index[-1]} IST")
    with c2:
        cw_move = (last.get("far_call_wall") or 0) - (first.get("far_call_wall") or 0)
        ui.metric_card("CALL WALL MOVE", f"{cw_move:+,.0f}",
                       sub="Since first log today",
                       color="green" if cw_move > 0 else "red" if cw_move < 0 else "default")
    with c3:
        pw_move = (last.get("far_put_wall") or 0) - (first.get("far_put_wall") or 0)
        ui.metric_card("PUT WALL MOVE", f"{pw_move:+,.0f}",
                       sub="Since first log today",
                       color="green" if pw_move > 0 else "red" if pw_move < 0 else "default")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(intra.index), y=intra["spot"], name="Spot",
                             line=dict(color="#0ea5e9", width=2)))
    fig.add_trace(go.Scatter(x=list(intra.index), y=intra["far_call_wall"], name="Call wall",
                             line=dict(color="#ef4444", width=2, dash="dot")))
    fig.add_trace(go.Scatter(x=list(intra.index), y=intra["far_put_wall"], name="Put wall",
                             line=dict(color="#10b981", width=2, dash="dot")))
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10),
                      title="Spot vs walls, today", xaxis_title="IST", yaxis_title="level")
    st.plotly_chart(fig, width="stretch")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Across recorded days (history)
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 4 — Across recorded days",
                  "Wall migration · max-pain drift · PCR percentile · rollover — built forward only")

hist = history_series(side_key)

if hist.empty:
    ui.alert_box(
        "History is still being built",
        "Kite serves no historical option open interest, so none of this can be back-filled — "
        "it is recorded forward, one row per day, by the EOD job. This section fills in from the "
        "first EOD run after the logger went live and gets more useful every day.\n\n"
        "Roughly 3 weeks of rows makes the percentile and drift readings meaningful. Days with "
        "no Kite login are simply missing — they are shown as gaps, never invented.",
        level="info",
    )
else:
    st.caption(f"📈 {len(hist)} day(s) recorded — {hist.index[0].date()} → {hist.index[-1].date()}")

    pctl = pcr_percentile(side_key)
    mp   = drift(side_key, "max_pain", lookback=10)
    cw   = drift(side_key, "call_wall", lookback=10)
    pw   = drift(side_key, "put_wall", lookback=10)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if pctl.get("available"):
            ui.metric_card("PCR PERCENTILE", f"{pctl['pctl']:.0f}th",
                           sub=f"PCR {pctl['value']} · range {pctl['min']}–{pctl['max']} over {pctl['days']}d",
                           color="red" if pctl["pctl"] >= 85 or pctl["pctl"] <= 15 else "green")
        else:
            ui.metric_card("PCR PERCENTILE", "—", sub="Needs more days")
    with c2:
        if mp.get("available"):
            ui.metric_card("MAX PAIN DRIFT", f"{mp['change']:+,.0f}",
                           sub=f"{mp['first']:,.0f} → {mp['last']:,.0f} over {mp['days']}d",
                           color="green" if mp["change"] > 0 else "red" if mp["change"] < 0 else "default")
        else:
            ui.metric_card("MAX PAIN DRIFT", "—", sub="Needs 2+ days")
    with c3:
        if cw.get("available"):
            ui.metric_card("CALL WALL DRIFT", f"{cw['change']:+,.0f}",
                           sub=f"{cw['first']:,.0f} → {cw['last']:,.0f}",
                           color="green" if cw["change"] > 0 else "red" if cw["change"] < 0 else "default")
        else:
            ui.metric_card("CALL WALL DRIFT", "—", sub="Needs 2+ days")
    with c4:
        if pw.get("available"):
            ui.metric_card("PUT WALL DRIFT", f"{pw['change']:+,.0f}",
                           sub=f"{pw['first']:,.0f} → {pw['last']:,.0f}",
                           color="green" if pw["change"] > 0 else "red" if pw["change"] < 0 else "default")
        else:
            ui.metric_card("PUT WALL DRIFT", "—", sub="Needs 2+ days")

    if len(hist) >= 2:
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=hist.index, y=hist["spot"], name="Spot",
                                  line=dict(color="#0ea5e9", width=2)))
        for col, colr, nm in (("call_wall", "#ef4444", "Call wall"),
                              ("put_wall", "#10b981", "Put wall"),
                              ("max_pain", "#f59e0b", "Max pain")):
            if col in hist.columns:
                fig2.add_trace(go.Scatter(x=hist.index, y=hist[col], name=nm,
                                          line=dict(color=colr, width=2, dash="dot")))
        fig2.update_layout(height=340, margin=dict(l=10, r=10, t=30, b=10),
                           title="Walls and max pain vs spot, by day",
                           xaxis_title="date", yaxis_title="level")
        st.plotly_chart(fig2, width="stretch")

        cA, cB = st.columns(2)
        with cA:
            if "rollover_pct" in hist.columns and hist["rollover_pct"].notna().any():
                f3 = go.Figure(go.Scatter(x=hist.index, y=hist["rollover_pct"] * 100,
                                          line=dict(color="#8b5cf6", width=2), name="Rollover %"))
                f3.update_layout(height=260, margin=dict(l=10, r=10, t=30, b=10),
                                 title="Rollover — share of OI in the far expiry",
                                 yaxis_title="%")
                st.plotly_chart(f3, width="stretch")
        with cB:
            if "iv_term" in hist.columns and hist["iv_term"].notna().any():
                f4 = go.Figure(go.Scatter(x=hist.index, y=hist["iv_term"],
                                          line=dict(color="#ec4899", width=2), name="IV term"))
                f4.add_hline(y=0, line_dash="dash", line_color="#94a3b8")
                f4.update_layout(height=260, margin=dict(l=10, r=10, t=30, b=10),
                                 title="IV term structure (far ATM IV − near)",
                                 yaxis_title="IV pts")
                st.plotly_chart(f4, width="stretch")
                st.caption("Below zero = near expiry pricing more risk than far — an event is expected soon.")

    with st.expander("Raw recorded history"):
        cols = [c for c in ["spot", "dte", "pcr", "max_pain", "call_wall", "put_wall",
                            "ce_top3", "pe_top3", "atm_iv", "iv_skew", "straddle",
                            "rollover_pct", "iv_term"] if c in hist.columns]
        st.dataframe(hist[cols].sort_index(ascending=False), width="stretch", height=320)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Per-strike history
# ══════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 5 — Per-strike history",
                  "Did the wall migrate strike by strike, or get abandoned and rebuilt elsewhere?")

ui.simple_technical(
    "Section 4 keeps one wall level per day. That tells you WHERE the wall is, but not how "
    "it got there — and two very different things look identical in a single number.\n\n"
    "A wall that MIGRATES moves in small steps: the same writers are defending a level and "
    "dragging it along with price. It is a real level and it tends to keep holding.\n\n"
    "A wall that JUMPS was abandoned. Writers closed out at the old strike and rebuilt "
    "somewhere else entirely. Anything sitting between the old and new level just lost its "
    "protection — and if your short strike is in that gap, that is the moment to act.",
    "Reads the per-strike chains the EOD job commits to data/parquet/\n"
    "Heat = open interest at that strike on that day; blank = strike outside the window\n"
    "'jumped' = biggest single-day step ≈ the whole net drift, and ≥ 150 pts\n"
    "The far expiry ROLLS — steps across a roll are excluded, since the same strike\n"
    "on either side is a different contract"
)
st.markdown("")

mig = wall_migration(side_key, days=30)

if mig.empty:
    ui.alert_box(
        "Per-strike history is still being built",
        "This section reads the full option chain that the EOD job saves each day to "
        "data/parquet/. Nothing has been written yet — the snapshot job could not read the "
        "chain before the symbol fix, so there is no back history to show, and Kite serves "
        "no historical option OI to backfill from.\n\n"
        "It starts filling from the next EOD run, and needs about a week before the migrate-"
        "vs-jump reading means anything.",
        level="info")
else:
    summ = wall_migration_summary(mig)
    st.caption(f"📈 {len(mig)} day(s) of per-strike chains — {mig.index[0]} → {mig.index[-1]}")

    if summ.get("available"):
        _BEHAV = {"migrated": ("green", "Level defended and dragged along"),
                  "jumped":   ("red",   "Abandoned here, rebuilt elsewhere"),
                  "held":     ("green", "Barely moved"),
                  "unknown":  ("default", "Not enough data")}
        c1, c2 = st.columns(2)
        for colobj, key, lbl in ((c1, "call", "CALL WALL"), (c2, "put", "PUT WALL")):
            d = summ.get(key, {})
            beh = d.get("behaviour", "unknown")
            colr, note = _BEHAV.get(beh, ("default", ""))
            with colobj:
                if d.get("from") is not None:
                    ui.metric_card(
                        f"{lbl} — {beh.upper()}",
                        f"{d['from']:,.0f} → {d['to']:,.0f}",
                        sub=f"{note} · net {d['net']:+,.0f}, biggest step {d['biggest_step']:,.0f}",
                        color=colr)
                else:
                    ui.metric_card(f"{lbl}", "—", sub="Not enough data")

        for key, lbl in (("call", "Call"), ("put", "Put")):
            if summ.get(key, {}).get("behaviour") == "jumped":
                d = summ[key]
                ui.alert_box(
                    f"{lbl} wall was RELOCATED, not dragged",
                    f"Biggest single-day move was {d['biggest_step']:,.0f} pts against a net "
                    f"drift of {d['net']:+,.0f}. Writers closed at the old level and rebuilt "
                    f"elsewhere rather than defending it. Any strike between "
                    f"{min(d['from'], d['to']):,.0f} and {max(d['from'], d['to']):,.0f} lost "
                    "its cover when that happened.",
                    level="warning")

    if mig["expiry_rolled"].astype(bool).any():
        _rolls = list(mig.index[mig["expiry_rolled"].astype(bool)])
        st.caption(f"⚠️ Expiry rolled on {', '.join(_rolls)} — OI is not comparable across "
                   "those dates (different contract), so those steps are excluded above.")

    _hm_col = st.radio("Heatmap side", ["Call OI", "Put OI"], horizontal=True)
    _col = "ce_oi" if _hm_col == "Call OI" else "pe_oi"
    matrix = chain_history_matrix(side_key, days=30, col=_col)

    if matrix.empty or matrix.shape[1] < 2:
        st.info("Heatmap needs at least two recorded days.")
    else:
        figh = go.Figure(go.Heatmap(
            z=matrix.values, x=list(matrix.columns), y=list(matrix.index),
            colorscale="YlOrRd", hoverongaps=False,
            colorbar=dict(title="OI"),
            hovertemplate="%{x}<br>strike %{y:,}<br>OI %{z:,.0f}<extra></extra>"))
        # Overlay the wall path so migration vs relocation is visible directly.
        wall_col = "call_wall" if _col == "ce_oi" else "put_wall"
        wl = mig[wall_col].dropna()
        if not wl.empty:
            figh.add_trace(go.Scatter(
                x=list(wl.index), y=list(wl.values), mode="lines+markers",
                name="Wall", line=dict(color="#0ea5e9", width=2),
                marker=dict(size=7, symbol="diamond")))
        figh.update_layout(height=460, margin=dict(l=10, r=10, t=30, b=10),
                           title=f"{_hm_col} by strike and day (blue = the wall)",
                           xaxis_title="date", yaxis_title="strike")
        st.plotly_chart(figh, width="stretch")
        st.caption("Blank cells are strikes outside that day's fetch window — missing data, "
                   "not zero open interest.")

    growth = strike_oi_growth(side_key, days=30, col=_col, top=8)
    if not growth.empty:
        with st.expander(f"Strikes that gained or lost the most {_hm_col.lower()}"):
            g = growth.copy()
            g.index.name = "Strike"
            g = g.rename(columns={"first": "First day", "last": "Last day",
                                  "change": "Change", "pct": "Change %"})
            st.dataframe(
                g.style.format({"First day": "{:,.0f}", "Last day": "{:,.0f}",
                                "Change": "{:+,.0f}", "Change %": "{:+.1f}%"}),
                width="stretch")
            st.caption("Only strikes present on BOTH the first and last recorded day — a "
                       "strike that drifted into the window mid-period is not counted as growth.")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Your IC Strikes")
    ce_in = st.number_input("CE Short Strike", value=int(st.session_state.get("ce_short", 0)), step=50)
    pe_in = st.number_input("PE Short Strike", value=int(st.session_state.get("pe_short", 0)), step=50)
    if st.button("Set strikes", width="stretch"):
        st.session_state["ce_short"] = ce_in
        st.session_state["pe_short"] = pe_in
        st.rerun()
    st.divider()
    ist = pytz.timezone("Asia/Kolkata")
    st.caption(f"Spot: {spot:,.0f}")
    st.caption(f"Near: {near_exp} ({near_dte} DTE)")
    st.caption(f"Far:  {far_exp} ({far_dte} DTE)")
    st.caption(f"Days recorded: {len(hist) if not hist.empty else 0}")
    st.caption(f"Now: {datetime.datetime.now(ist):%H:%M} IST")
