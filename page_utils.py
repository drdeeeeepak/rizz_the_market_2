import datetime
import pytz
import streamlit as st
from pathlib import Path

_IST = pytz.timezone("Asia/Kolkata")


def _ist_now() -> datetime.datetime:
    return datetime.datetime.now(_IST)


def _fmt_ist(dt: datetime.datetime) -> str:
    if dt.tzinfo is None:
        dt = _IST.localize(dt)
    else:
        dt = dt.astimezone(_IST)
    return dt.strftime("%-d %b %-I:%M %p IST")


def bootstrap_signals() -> tuple[dict, float, str]:
    """
    Returns (sig, spot, signals_timestamp_str) for any page.

    Priority order:
      1. session_state["signals"]  — set by Home page on this session
      2. signals.json on disk      — written by EOD GitHub Actions job
      3. Live compute fallback     — fetches and computes on the fly (cold start)

    Always fetches a fresh spot price independently (60s TTL cache).
    """
    from data.live_fetcher import get_nifty_spot

    # ── 1. Try session_state ────────────────────────────────────────────────
    sig = st.session_state.get("signals", {})
    sig_source = "session"

    # ── 2. Fall back to signals.json ────────────────────────────────────────
    if not sig:
        try:
            from analytics.compute_signals import load_saved_signals
            sig = load_saved_signals()
            if sig:
                sig_source = "json"
                st.session_state["signals"] = sig
        except Exception:
            sig = {}

    # ── 3. Live compute fallback (cold start — no json yet) ─────────────────
    if not sig:
        try:
            from data.live_fetcher import (
                get_nifty_daily, get_top10_daily,
                get_india_vix, get_vix_history, get_dual_expiry_chains,
            )
            from analytics.compute_signals import compute_all_signals
            _spot = get_nifty_spot()
            _nifty_df = get_nifty_daily()
            _stock_dfs = get_top10_daily()
            _vix_live = get_india_vix()
            _vix_hist = get_vix_history()
            _chains = get_dual_expiry_chains(_spot if _spot > 0 else 23000)
            if _spot == 0 and not _nifty_df.empty:
                _spot = float(_nifty_df["close"].iloc[-1])
            sig = compute_all_signals(
                _nifty_df, _stock_dfs, _vix_live, _vix_hist, _chains, _spot
            )
            sig_source = "live"
            st.session_state["signals"] = sig
        except Exception as e:
            st.warning(f"⚠️ Could not load signals: {e}")
            sig = {}

    # ── Live spot (independent 60s TTL — always fresh) ──────────────────────
    spot = get_nifty_spot()
    if spot == 0:
        spot = sig.get("final_put_short", 0) + sig.get("final_put_dist", 0)
    if spot == 0:
        spot = float(sig.get("spot", 0))

    # ── Signals timestamp ───────────────────────────────────────────────────
    ts_str = sig.get("_saved_at", "")
    if ts_str:
        return sig, spot, ts_str

    ts_str = "—"
    try:
        if sig_source in ("json", "session"):
            _signals_path = Path(__file__).parent / "data" / "signals.json"
            if _signals_path.exists():
                mtime = _signals_path.stat().st_mtime
                dt = datetime.datetime.fromtimestamp(mtime, tz=_IST)
                ts_str = _fmt_ist(dt)
            else:
                _signals_path2 = Path(__file__).parent / "signals.json"
                if _signals_path2.exists():
                    mtime = _signals_path2.stat().st_mtime
                    dt = datetime.datetime.fromtimestamp(mtime, tz=_IST)
                    ts_str = _fmt_ist(dt)
        elif sig_source == "live":
            ts_str = _fmt_ist(_ist_now())
    except Exception:
        ts_str = "—"

    return sig, spot, ts_str


def show_page_header(spot: float, signals_ts: str, page_key: str = "") -> None:
    """Renders the live spot + signals timestamp caption at the top of every page."""
    spot_str = f"{spot:,.0f}" if spot > 0 else "—"
    st.caption(
        f"⏱  Spot: **{spot_str}**  ·  Signals: {signals_ts}"
    )
