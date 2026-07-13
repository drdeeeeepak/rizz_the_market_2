# pages/26_BB_Fade_Backtest.py
# BB Fade — dedicated, lightweight out-of-sample check for the two
# mean-reversion ("fade") Bollinger signals already coded in
# analytics/signal_adapters.py (Bollinger %B, Bollinger Asymmetry Fade), which
# today can only be seen buried inside page 23's full Signal Library run.
# This page isolates just those two signals with their own scorecard +
# walk-forward split — the actual out-of-sample check needed before writing a
# confirmed BB-fade rule (page 27).
#
# Only needs Nifty daily candles (no 1H/futures pull) — light and fast.
#
# You just: log in (Home → Kite) so the token is fresh, then click Run.

import pandas as pd
import streamlit as st

import importlib
import data.live_fetcher as _lf
from analytics import signal_lab as sl
from analytics import signal_adapters as sa

try:
    importlib.reload(_lf)
    importlib.reload(sl)
    importlib.reload(sa)
except Exception:
    pass

st.set_page_config(page_title="P26 · BB Fade Backtest", layout="wide")
st.title("Page 26 — BB Fade Backtest")
st.caption("Out-of-sample check for the two MEAN-REVERSION Bollinger signals already coded in "
           "analytics/signal_adapters.py — isolates them from page 23's full Signal Library run "
           "so you can check confidence quickly, before deciding whether to write a confirmed "
           "rule on page 27.")

with st.expander("⚠️ What this is (and its limits) — read once"):
    st.markdown(
        "- **Bollinger %B Fade** — %B pinned to/above the upper band scores as a fade-SHORT "
        "(expects reversion down); at/below the lower band scores fade-LONG. Matches the "
        "overbought-fade edge already found for RSI/%B on the page-22 Conviction table.\n"
        "- **Bollinger Asymmetry Fade** — the mean-reversion mirror of page 09's real live "
        "output (the asymmetry ratio), which backtested NEGATIVE read as continuation — this "
        "checks whether the fade framing is what's actually real.\n"
        "- Both are DAILY proxies of page 09's live 2H/4H engine (same rolling BollingerOptionsEngine, "
        "just re-sampled to daily closes) — a directional/robustness check, not a live-timeframe "
        "replay.\n"
        "- **The walk-forward split (section 2) is the actual confidence gate** — an edge that "
        "only shows up in the whole-sample average and disappears or flips sign split-by-split is "
        "a single-regime artifact, not a real edge. Only treat this as confirmed if it holds up "
        "across most/all splits, same direction, non-trivial magnitude.\n"
        "- Base-rate evidence, not a guarantee.")


@st.cache_data(ttl=3600, show_spinner=False)
def _load_daily(days):
    return _lf.get_nifty_daily(days=days)


c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1])
with c1:
    lookback = st.slider("Lookback (calendar days)", 365, 1460, 730, step=30, key="p26_lookback")
with c2:
    call_pct = st.number_input("Sold CALL distance %", 1.0, 8.0, 3.5, 0.25, key="p26_call_pct")
with c3:
    put_pct = st.number_input("Sold PUT distance %", 1.0, 8.0, 4.0, 0.25, key="p26_put_pct")
with c4:
    nbins = st.select_slider("Buckets/column", options=[3, 4, 5, 6], value=5, key="p26_nbins")

split_by = st.radio("Walk-forward split", ["year", "half"], horizontal=True, key="p26_split")

# Gate on session_state rather than the button's own return value — same pattern used
# elsewhere in this app: any later widget interaction (the split radio, a download
# button) triggers its own rerun where a raw st.button() gate would wipe the page.
if st.button("▶ Run BB fade backtest", type="primary"):
    st.session_state.p26_ran = True
    st.session_state.p26_inputs = dict(lookback=lookback, call_pct=call_pct, put_pct=put_pct,
                                       nbins=nbins, split_by=split_by)

if not st.session_state.get("p26_ran"):
    st.info("Pick your lookback and click Run. Only needs daily candles (~5-10s).")
    st.stop()

_in = st.session_state.p26_inputs
lookback, call_pct, put_pct = _in["lookback"], _in["call_pct"], _in["put_pct"]
nbins, split_by = _in["nbins"], _in["split_by"]
horizons = (5, 10)

with st.spinner("Fetching daily history and scoring both BB-fade signals…"):
    daily = _load_daily(lookback)

if daily is None or daily.empty:
    st.error("Could not load daily Nifty history. Log in via Home → Kite, then retry.")
    st.stop()

pctb_sig = sa.adapt_bollinger_pctb(daily)
asym_fade_sig = sa.adapt_bollinger_asymmetry_fade(daily)

res_pctb = sl.evaluate_signal(daily, pctb_sig, name="Bollinger %B Fade", horizons=horizons,
                              call_pct=float(call_pct), put_pct=float(put_pct), nbins=int(nbins))
res_asym = sl.evaluate_signal(daily, asym_fade_sig, name="Bollinger Asymmetry Fade", horizons=horizons,
                              call_pct=float(call_pct), put_pct=float(put_pct), nbins=int(nbins))

st.success(f"Analysed **{res_pctb['n']}** daily rows · {res_pctb['span']}")

# ── 1. Scorecard — both fade signals side by side ───────────────────────────
st.subheader("1 · Scorecard — whole-sample")
st.caption("**hit_rate%** = share of active days the signal called the forward direction "
          "correctly · **expectancy%** = avg forward move in the called direction · "
          "**spearman** = rank correlation between the raw score and the forward return.")
leaderboard = sl.rank_signals([res_pctb, res_asym])
st.dataframe(leaderboard, use_container_width=True, hide_index=True)

pick = st.selectbox("Signal detail", [res_pctb["name"], res_asym["name"]], key="p26_pick")
r = res_pctb if pick == res_pctb["name"] else res_asym
cA, cB = st.columns(2)
with cA:
    st.markdown(f"**{pick} — scorecard**")
    st.json({k: r[k] for k in ("n", "n_active", "hit_rate", "expectancy", "spearman", "span")})
with cB:
    st.markdown("**Weekly move distribution (this Nifty history, all days)**")
    st.dataframe(r["distribution"], use_container_width=True, hide_index=True)

st.markdown(f"**{pick} — bucket scan** (quantile-binned raw score → forward edge)")
if r["bucket"].empty:
    st.caption("Not enough active rows to bucket.")
else:
    st.dataframe(r["bucket"], use_container_width=True)

with st.expander(f"⬇ Download {pick}'s raw per-day table"):
    st.download_button("Download CSV", r["detail"].to_csv().encode("utf-8"),
                       file_name=f"bb_fade_{pick.replace(' ', '_').lower()}.csv", mime="text/csv",
                       key=f"p26_dl_{pick}")

# ── 2. Walk-forward — the actual confidence gate ────────────────────────────
st.divider()
st.subheader("2 · Walk-forward check — does the edge survive split-by-split?")
st.caption("Same out-of-sample check page 23 gives the RSI overbought-fade rule — split by "
          "year or half, does hit_rate/expectancy hold the SAME sign and a non-trivial "
          "magnitude in every split, or does it flip/collapse (a single-regime artifact)?")

wf_pctb = sl.walk_forward(daily, pctb_sig, horizons=horizons, call_pct=float(call_pct),
                          put_pct=float(put_pct), by=split_by)
wf_asym = sl.walk_forward(daily, asym_fade_sig, horizons=horizons, call_pct=float(call_pct),
                          put_pct=float(put_pct), by=split_by)

wc1, wc2 = st.columns(2)
with wc1:
    st.markdown("**Bollinger %B Fade — by split**")
    if wf_pctb.empty:
        st.caption("Not enough rows to split.")
    else:
        st.dataframe(wf_pctb, use_container_width=True, hide_index=True)
        st.download_button("⬇ Download CSV", wf_pctb.to_csv(index=False).encode("utf-8"),
                           file_name="bb_pctb_fade_walk_forward.csv", mime="text/csv",
                           key="p26_dl_wf_pctb")
with wc2:
    st.markdown("**Bollinger Asymmetry Fade — by split**")
    if wf_asym.empty:
        st.caption("Not enough rows to split.")
    else:
        st.dataframe(wf_asym, use_container_width=True, hide_index=True)
        st.download_button("⬇ Download CSV", wf_asym.to_csv(index=False).encode("utf-8"),
                           file_name="bb_asymmetry_fade_walk_forward.csv", mime="text/csv",
                           key="p26_dl_wf_asym")

st.divider()
st.caption("Once you're confident from the split table above (same sign, non-trivial magnitude, "
          "most/all splits) — page 27 holds the confirmed rule book, mirroring the pattern used "
          "for pages 24 and 25.")
