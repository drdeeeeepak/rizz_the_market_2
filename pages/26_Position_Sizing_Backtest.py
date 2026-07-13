# pages/26_Position_Sizing_Backtest.py
# Position SIZING — a third question, distinct from page 24 (is a fresh short
# safe to place right now) and page 25 (when should I roll an existing leg):
# given the reference position (2 lots CALL ~3% above Tuesday anchor, 1 lot
# PUT ~3.5% below, squared off within a week), does a trend-confirmation
# signal identify cycles where it's safe to flip toward 2 PUT : 1 CALL (or
# 2 CALL : 1 PUT) instead of the static default?
#
# You just: log in (Home → Kite) so the token is fresh, then click Run.

from pathlib import Path

import pandas as pd
import streamlit as st

import importlib
import data.live_fetcher as _lf
from analytics import position_sizing_backtest as ps
import ui.conviction_table as uict

try:
    importlib.reload(_lf)
    importlib.reload(ps)
    importlib.reload(uict)
except Exception:
    pass

st.set_page_config(page_title="P26 · Position Sizing", layout="wide")
st.title("Page 26 — Position Sizing Backtest")
st.caption("Does a trend-confirmation signal (or combination of signals) tell you WHICH leg to "
           "double, before you place the trade? Distinct from page 24 (strike distance / entry "
           "timing) and page 25 (rolling an existing leg) — this is the LOT ALLOCATION question.")

with st.expander("⚠️ What this is (and its limits) — read once", expanded=True):
    st.markdown(
        "- **Reference position**: 2 lots CALL ~3% above Tuesday anchor, 1 lot PUT ~3.5% below, "
        "squared off within a week — same reference position as `docs/PAGE_25_RULE_BOOK.md`. "
        "Change the % inputs below if your actual strikes differ.\n"
        "- **Survival-only, same as pages 24/25.** No historical option premium/IV data exists "
        "anywhere in this app (Kite gives only a LIVE chain snapshot) — every table here is "
        "scored on strike-**breach rate**, never realized P&L. `expected_breached_lots_per_cycle` "
        "is the closest proxy for 'more lots on the leg that gets tested more often,' not a real "
        "P&L number.\n"
        "- **Tuesdays-only** by default: the sizing decision is made ONCE per cycle, at Tuesday "
        "EOD anchor (`data/rolled_positions.py: set_expiry_anchor`) — every other day would score "
        "a hypothetical cycle that was never actually entered.\n"
        "- **Composite signal** = mean of 6 adapters (Dow Theory structure, EMA Ribbon regime, "
        "EMA Moat Balance, RSI weekly/daily alignment, daily SuperTrend, Bollinger %B fade), "
        "reusing the SAME pure engine functions `analytics/signal_lab.py` already ranks "
        "individually — this page only adds the combine-and-bucket step on top. Bollinger fade "
        "is sign-flipped before joining the mean (`_bollinger_fade_composite_adapter`) so its "
        "OWN validated (oversold) reading aligns with this composite's DOWN convention — see the "
        "comment above `DEFAULT_ADAPTERS` in `analytics/position_sizing_backtest.py` for why. A "
        "bucket only reads UP/DOWN if the composite clears `up_thresh` AND at least `min_agree` "
        "adapters independently agree — one lens alone never flips the recommendation.\n"
        "- 1H history (needed for Dow Theory) is capped by Kite's 60-minute history limit, same "
        "as pages 22/23 — pick a lookback within that cap.")

_workflow_path = Path(__file__).resolve().parent.parent / "docs" / "PAGE_26_WORKFLOW.md"
with st.expander("📋 How to use this page (workflow)"):
    if _workflow_path.exists():
        st.markdown(_workflow_path.read_text())
    else:
        st.caption("Not written yet.")

_rulebook_path = Path(__file__).resolve().parent.parent / "docs" / "PAGE_26_RULE_BOOK.md"
with st.expander("📜 Position-sizing rule book (read this first)"):
    if _rulebook_path.exists():
        st.markdown(_rulebook_path.read_text())
    else:
        st.caption("Not written yet — run the sections below first, then record findings here.")


@st.cache_data(ttl=3600, show_spinner=False)
def _load_daily(days):
    return _lf.get_nifty_daily(days=days)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_h1(days):
    return _lf.get_nifty_1h_phase(days=days)


def _frozen(df: pd.DataFrame, height=280, reset=True):
    d = df.reset_index() if reset else df
    st.markdown(uict.candle_table_frozen_html(d, height=height), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# Controls
# ══════════════════════════════════════════════════════════════════════════════
c1, c2, c3 = st.columns([1.3, 1, 1])
with c1:
    lookback = st.slider("Daily lookback (calendar days)", 365, 1460, 730, step=30, key="p26_lookback")
with c2:
    call_pct = st.number_input("Sold CALL distance %", 1.0, 8.0, 3.0, 0.25, key="p26_call_pct")
with c3:
    put_pct = st.number_input("Sold PUT distance %", 1.0, 8.0, 3.5, 0.25, key="p26_put_pct")

h1_days = st.slider("1H lookback for Dow Theory (trading days, capped by Kite's 60-min history "
                    "limit)", 60, 380, 260, step=20, key="p26_h1_days")

c4, c5, c6, c7 = st.columns(4)
with c4:
    horizon = st.select_slider("Hold horizon (trading days)", options=[3, 5, 7, 10], value=5, key="p26_horizon")
with c5:
    up_thresh = st.slider("Composite UP/DOWN threshold", 0.1, 0.8, 0.4, 0.05, key="p26_up_thresh")
with c6:
    min_agree = st.slider("Min adapters agreeing", 1, 6, 3, key="p26_min_agree")
with c7:
    tuesdays_only = st.checkbox("Tuesdays only (anchor days)", value=True, key="p26_tue_only")

if st.button("▶ Run position-sizing backtest", type="primary", key="p26_run"):
    st.session_state.p26_ran = True
    st.session_state.p26_inputs = dict(
        lookback=lookback, h1_days=h1_days, call_pct=call_pct, put_pct=put_pct,
        horizon=horizon, up_thresh=up_thresh, min_agree=min_agree, tuesdays_only=tuesdays_only,
    )

if not st.session_state.get("p26_ran"):
    st.info("Pick your lookback and thresholds, then click Run. First run pulls daily + 1H "
            "candles and scores 6 adapters individually plus their composite (~15-30s).")
    st.stop()

_in = st.session_state.p26_inputs

with st.spinner("Fetching history and scoring signals…"):
    daily = _load_daily(_in["lookback"])
    h1 = _load_h1(_in["h1_days"])

if daily is None or daily.empty:
    st.error("Could not load daily Nifty history. Log in via Home → Kite, then retry.")
    st.stop()
if h1 is None or h1.empty:
    st.warning("Could not load 1H history — Dow Theory will be skipped, other adapters still run.")

with st.spinner("Building composite signal and scoring buckets…"):
    result = ps.run_position_sizing_backtest(
        daily, h1 if h1 is not None else pd.DataFrame(),
        horizon=_in["horizon"], call_pct=_in["call_pct"], put_pct=_in["put_pct"],
        up_thresh=_in["up_thresh"], min_agree=_in["min_agree"], tuesdays_only=_in["tuesdays_only"],
        reference_adapters=ps.REFERENCE_ADAPTERS,
    )

# ══════════════════════════════════════════════════════════════════════════════
# 1 · Per-indicator breach rate — which lenses actually separate CE from PE risk
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("1 · Per-indicator breach rate, bucketed UP / NEUTRAL / DOWN")
st.caption("Each row is ONE adapter, scored alone (no combining yet). If a row shows a clean gap — "
           "e.g. UP bucket has low call_breach% and high put_breach%, and DOWN is the mirror — that "
           "indicator alone is doing real work for the sizing decision. If UP and DOWN look similar, "
           "that indicator isn't separating CE risk from PE risk and shouldn't drive lot allocation "
           "on its own.")

if not result["per_signal_breach"]:
    st.warning("No adapters produced data — check daily/1H history loaded above.")
else:
    for name, table in result["per_signal_breach"].items():
        st.markdown(f"**{name}**")
        if table.empty:
            st.caption("No cycles in any bucket at this threshold.")
        else:
            _frozen(table, height=140)
            sc = result["per_signal_scorecard"].get(name)
            if sc is not None and not sc.empty:
                with st.expander(f"Lot scorecard scored off {name} alone"):
                    _frozen(sc, height=140)

    _per_signal_parts = []
    for name, table in result["per_signal_breach"].items():
        if table.empty:
            continue
        part = table.reset_index()
        part.insert(0, "indicator", name)
        _per_signal_parts.append(part)
    if _per_signal_parts:
        _per_signal_csv = pd.concat(_per_signal_parts, ignore_index=True)
        st.download_button("⬇ Download all per-indicator tables CSV",
                           _per_signal_csv.to_csv(index=False).encode(),
                           "p26_per_indicator_breach.csv", key="p26_dl_per_signal")

# ══════════════════════════════════════════════════════════════════════════════
# 1b · Per-indicator early/late split — the promotion bar for a candidate adapter
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("1b · Per-indicator early half vs late half")
st.caption("Same out-of-sample check section 2b gives the COMPOSITE, but scored off EACH "
          "indicator alone (now including bollinger_fade, promoted into DEFAULT_ADAPTERS after "
          "clearing this exact bar). This is what ANY future candidate signal needs to clear "
          "before it's safe to promote — same direction call_breach%/put_breach% asymmetry in "
          "BOTH the early and late half, not just a whole-window average that could be one "
          "dominant stretch. Add a candidate to `REFERENCE_ADAPTERS` in "
          "analytics/position_sizing_backtest.py and pass it via this function's "
          "`reference_adapters` argument to test it here without touching the composite.")

_psplit = result.get("per_signal_split", {})
if not _psplit:
    st.warning("No per-indicator split data — check daily/1H history loaded above.")
else:
    for name, split in _psplit.items():
        if not split:
            continue
        st.markdown(f"**{name}**")
        _cols = st.columns(len(split))
        for _col, (_label, _seg) in zip(_cols, split.items()):
            with _col:
                st.markdown(f"*{_label.replace('_', ' ').title()}* ({_seg['span']}, n={_seg['n']})")
                if _seg["table"].empty:
                    st.caption("No cycles in any bucket at this threshold.")
                else:
                    _frozen(_seg["table"], height=140)

    _split_parts = []
    for name, split in _psplit.items():
        for _label, _seg in split.items():
            if _seg["table"].empty:
                continue
            _part = _seg["table"].reset_index()
            _part.insert(0, "indicator", name)
            _part.insert(1, "half", _label)
            _part.insert(2, "span", _seg["span"])
            _split_parts.append(_part)
    if _split_parts:
        _psplit_csv = pd.concat(_split_parts, ignore_index=True)
        st.download_button("⬇ Download all per-indicator split tables CSV",
                           _psplit_csv.to_csv(index=False).encode(),
                           "p26_per_indicator_split.csv", key="p26_dl_per_signal_split")

# ══════════════════════════════════════════════════════════════════════════════
# 2 · Composite signal — does combining lenses sharpen the gap?
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("2 · Composite signal (all adapters combined, agreement-gated)")
st.caption(f"UP/DOWN only fire when the composite clears ±{_in['up_thresh']} AND at least "
           f"{_in['min_agree']} adapters independently agree — compare this gap to the per-indicator "
           "rows above. A wider CE/PE breach gap here than any single indicator alone is the case "
           "for combining lenses; if it's no better than the best single indicator, the extra "
           "adapters aren't earning their complexity.")

if result["composite_breach"].empty:
    st.warning("No cycles cleared the composite threshold — try lowering up_thresh or min_agree.")
else:
    _frozen(result["composite_breach"], height=160)

st.markdown("**2b · Early half vs late half — does the same asymmetry hold in BOTH?**")
st.caption("The table above is ONE average over the whole lookback — it can't tell you whether an "
           "asymmetry is a genuine, repeatable edge or just one dominant stretch (e.g. one sharp "
           "correction-and-bounce) skewing the whole-period number. This splits the SAME cycles "
           "chronologically into an early half and a late half and scores each independently — full "
           "daily/1H history still feeds every indicator's warmup, only the evaluation rows are split. "
           "If call_breach%/put_breach% point the SAME direction in both halves, that's real "
           "out-of-sample support. If they disagree or flip, treat the full-window number as noise "
           "from one regime, not a rule.")

_split = result.get("composite_split", {})
if not _split:
    st.warning("Not enough cycles to split — try a longer daily lookback.")
else:
    _cols = st.columns(len(_split))
    for _col, (_label, _seg) in zip(_cols, _split.items()):
        with _col:
            st.markdown(f"*{_label.replace('_', ' ').title()}* ({_seg['span']}, n={_seg['n']})")
            if _seg["table"].empty:
                st.caption("No cycles in any bucket at this threshold.")
            else:
                _frozen(_seg["table"], height=140)
            with st.expander("Lot scorecard, this half only"):
                _frozen(_seg["scorecard"], height=140)

    _split_parts = []
    for _label, _seg in _split.items():
        if _seg["table"].empty:
            continue
        _part = _seg["table"].reset_index()
        _part.insert(0, "half", _label)
        _part.insert(1, "span", _seg["span"])
        _split_parts.append(_part)
    if _split_parts:
        _split_csv = pd.concat(_split_parts, ignore_index=True)
        st.download_button("⬇ Download early/late split CSV",
                           _split_csv.to_csv(index=False).encode(),
                           "p26_composite_split.csv", key="p26_dl_split")

# ══════════════════════════════════════════════════════════════════════════════
# 3 · Lot-scheme scorecard
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("3 · Lot-scheme scorecard")
st.caption("Three lot allocations scored against the SAME composite-bucket breach rates from "
           "section 2: **static_2CE_1PE** (today's live default, every cycle), **static_1_1** "
           "(symmetric baseline), **dynamic_flip** (2 PE : 1 CE on a confirmed UP cycle, 3 CE : 1 PE "
           "on a confirmed DOWN cycle, default 2 CE : 1 PE otherwise). Lower "
           "`expected_breached_lots_per_cycle` / `breach_rate_per_lot%` = fewer expected leg-"
           "breaches for the same premium-collecting effort — the survival-space stand-in for "
           "'better,' since no premium data exists to price this in real currency.")

if result["lot_scorecard"].empty:
    st.warning("No bucket data to score — run section 2 first.")
else:
    _frozen(result["lot_scorecard"], height=140)
    st.download_button("⬇ Download lot scorecard CSV",
                       result["lot_scorecard"].to_csv().encode(),
                       "p26_lot_scorecard.csv", key="p26_dl_scorecard")
    st.download_button("⬇ Download composite bucket table CSV",
                       result["composite_breach"].to_csv().encode(),
                       "p26_composite_breach.csv", key="p26_dl_composite")
