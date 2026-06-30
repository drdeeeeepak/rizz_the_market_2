# data/live_fetcher.py
# All Kite data fetching lives here. Analytics modules never call Kite directly.
# Updated 27 Apr 2026: single get_nifty_1h_phase() replaces all previous 1H fetchers.
# Updated 27 Apr 2026: added get_nifty_15m(), get_nifty_30m(), get_nifty_5m() for SuperTrend MTF page.

import logging
import time
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

try:
    import streamlit as st
    _HAS_ST = True
except ImportError:
    _HAS_ST = False
    class _StStub:
        @staticmethod
        def cache_data(ttl=None, show_spinner=False):
            def decorator(fn): return fn
            return decorator
        def __getattr__(self, name): return lambda *a, **k: None
    st = _StStub()

from config import (
    NIFTY_INDEX_TOKEN, TOP_10_TOKENS,
    TTL_OPTIONS, TTL_PRICE, TTL_DAILY, TTL_1H,
    OI_STRIKE_STEP, OI_STRIKE_RANGE, EXPIRY_WEEKDAY,
    DOW_PHASE_DAYS,
    TTL_15M, TTL_30M, TTL_5M,
    ST_15M_DAYS, ST_30M_DAYS, ST_5M_DAYS,
    EMA_SLOPE_FETCH_DAYS,
)

log = logging.getLogger(__name__)


# ─── Expiry helpers ───────────────────────────────────────────────────────────

def next_tuesday(from_date: Optional[date] = None) -> date:
    d = from_date or date.today()
    days_ahead = EXPIRY_WEEKDAY - d.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)


def get_near_far_expiries() -> tuple[date, date]:
    today = date.today()
    near  = next_tuesday(today)
    far   = next_tuesday(near + timedelta(days=1))
    return near, far


def get_dte(expiry: date) -> int:
    return max(0, (expiry - date.today()).days)


# ─── Nifty spot ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_nifty_spot() -> float:
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        # Try token-based quote first
        quote = kite.quote([f"NSE:{NIFTY_INDEX_TOKEN}"])
        for key in [str(NIFTY_INDEX_TOKEN), f"NSE:{NIFTY_INDEX_TOKEN}"]:
            if key in quote:
                return float(quote[key]["last_price"])
        # Fallback: try by trading symbol
        quote2 = kite.quote(["NSE:NIFTY 50"])
        for key in ["NSE:NIFTY 50", "NIFTY 50"]:
            if key in quote2:
                return float(quote2[key]["last_price"])
        if quote or quote2:  # only warn when API returned something but key was unexpected
            log.warning("Spot key not found. Keys: %s | %s", list(quote.keys())[:5], list(quote2.keys())[:5])
        return 0.0
    except Exception as e:
        log.error("Spot fetch failed: %s", e); return 0.0


@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_nifty_daily_live(days: int = 400) -> pd.DataFrame:
    """Same as get_nifty_daily but with short TTL for live RSI during market hours."""
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        to_date   = date.today()
        from_date = to_date - timedelta(days=days)
        data = kite.historical_data(
            NIFTY_INDEX_TOKEN,
            from_date.strftime("%Y-%m-%d"),
            to_date.strftime("%Y-%m-%d"),
            "day"
        )
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        log.error("Nifty daily live fetch failed: %s", e); return pd.DataFrame()


# ─── Nifty daily OHLCV ───────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def _get_nifty_daily_cached(days: int = 400) -> pd.DataFrame:
    """Raises RuntimeError on empty — prevents Streamlit from caching failures.
    Streamlit only caches successful (non-exception) returns, so the next call
    after a pre-market empty-result will retry fresh once market data is available."""
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()

    def _fetch(to_dt) -> pd.DataFrame:
        from_dt = to_dt - timedelta(days=days)
        data    = kite.historical_data(
            NIFTY_INDEX_TOKEN,
            from_dt.strftime("%Y-%m-%d"),
            to_dt.strftime("%Y-%m-%d"),
            "day",
        )
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        return df[["open", "high", "low", "close", "volume"]]

    for _delta in (0, 1):
        try:
            result = _fetch(date.today() - timedelta(days=_delta))
            if not result.empty:
                return result
        except Exception as e:
            log.warning("Nifty daily fetch (delta=%d) failed: %s", _delta, e)

    raise RuntimeError("Nifty daily: all fetch attempts returned empty")


def get_nifty_daily(days: int = 400) -> pd.DataFrame:
    """Public wrapper — returns empty DataFrame on failure, never raises."""
    try:
        return _get_nifty_daily_cached(days)
    except Exception as e:
        log.error("Nifty daily (all failed): %s", e)
        return pd.DataFrame()


# ─── Nifty 1H OHLCV — Dow Theory Phase Window ────────────────────────────────

@st.cache_data(ttl=TTL_1H, show_spinner=False)
def _get_nifty_1h_phase_cached(days: int = DOW_PHASE_DAYS) -> pd.DataFrame:
    """Inner fetch — raises on failure so Streamlit never caches an empty result."""
    kite      = _get_kite_safe()
    to_date   = date.today()
    from_date = to_date - timedelta(days=days + 12)
    log.info("Fetching 1H phase: %s → %s (%d trading days)", from_date, to_date, days)
    data = kite.historical_data(
        NIFTY_INDEX_TOKEN,
        from_date.strftime("%Y-%m-%d"),
        to_date.strftime("%Y-%m-%d"),
        "60minute",
    )
    if not data:
        raise RuntimeError("1H phase fetch returned empty — will retry on next call")
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[["open", "high", "low", "close", "volume"]]
    target = days * 6
    if len(df) > target:
        df = df.tail(target)
    if len(df) < int(days * 6 * 0.6):
        log.warning("1H phase: only %d candles (expected ~%d)", len(df), target)
    log.info("1H phase ready: %d candles", len(df))
    return df


def get_nifty_1h_phase(days: int = DOW_PHASE_DAYS) -> pd.DataFrame:
    """
    Fetch 1H candles for Dow Theory phase engine.
    Also used by SuperTrend engine for 1H TF and proxy resampling to 2H/4H.
    Public wrapper — returns empty DataFrame on failure, never raises.
    """
    try:
        return _get_nifty_1h_phase_cached(days)
    except Exception as e:
        log.error("1H phase fetch failed: %s", e)
        return pd.DataFrame()


# ─── Auth helper — session first, token file fallback ────────────────────────

def _get_kite_safe():
    """Return authenticated Kite client.
    Tries browser-session auth first (works during live page loads),
    then falls back to access_token.txt (works any time on the same day).
    Never calls st.stop() — safe to use inside @st.cache_data functions.
    """
    from data.kite_client import get_kite_action
    if _HAS_ST:
        try:
            from data.kite_client import get_kite
            return get_kite()
        except Exception:
            pass
    return get_kite_action()


# ─── Nifty 30m OHLCV — SuperTrend Tier 3 ────────────────────────────────────

@st.cache_data(ttl=TTL_30M, show_spinner=False)
def _get_nifty_30m_cached(days: int = ST_30M_DAYS) -> pd.DataFrame:
    """Inner fetch — raises on failure so Streamlit never caches an empty result."""
    kite      = _get_kite_safe()
    to_date   = date.today()
    from_date = to_date - timedelta(days=days + 5)
    log.info("Fetching 30m ST: %s → %s", from_date, to_date)
    data = kite.historical_data(
        NIFTY_INDEX_TOKEN,
        from_date.strftime("%Y-%m-%d"),
        to_date.strftime("%Y-%m-%d"),
        "30minute",
    )
    if not data:
        raise RuntimeError("30m fetch returned empty — will retry on next call")
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[["open", "high", "low", "close", "volume"]]
    target = days * 12   # 12 × 30m candles per NSE session
    if len(df) > target:
        df = df.tail(target)
    log.info("30m ST ready: %d candles", len(df))
    return df


def get_nifty_30m(days: int = ST_30M_DAYS) -> pd.DataFrame:
    """Public wrapper — returns empty DataFrame on failure, never raises."""
    try:
        return _get_nifty_30m_cached(days)
    except Exception as e:
        log.error("30m fetch failed: %s", e)
        return pd.DataFrame()


# ─── Nifty 15m OHLCV — SuperTrend Tier 3 ────────────────────────────────────

@st.cache_data(ttl=TTL_15M, show_spinner=False)
def _get_nifty_15m_cached(days: int = ST_15M_DAYS) -> pd.DataFrame:
    """Inner fetch — raises on failure so Streamlit never caches an empty result."""
    kite      = _get_kite_safe()
    to_date   = date.today()
    from_date = to_date - timedelta(days=days + 3)
    log.info("Fetching 15m ST: %s → %s", from_date, to_date)
    data = kite.historical_data(
        NIFTY_INDEX_TOKEN,
        from_date.strftime("%Y-%m-%d"),
        to_date.strftime("%Y-%m-%d"),
        "15minute",
    )
    if not data:
        raise RuntimeError("15m fetch returned empty — will retry on next call")
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[["open", "high", "low", "close", "volume"]]
    target = days * 24   # 24 × 15m candles per NSE session
    if len(df) > target:
        df = df.tail(target)
    log.info("15m ST ready: %d candles", len(df))
    return df


def get_nifty_15m(days: int = ST_15M_DAYS) -> pd.DataFrame:
    """Public wrapper — returns empty DataFrame on failure, never raises."""
    try:
        return _get_nifty_15m_cached(days)
    except Exception as e:
        log.error("15m fetch failed: %s", e)
        return pd.DataFrame()


# ─── Nifty 5m OHLCV — SuperTrend display only ────────────────────────────────

@st.cache_data(ttl=TTL_5M, show_spinner=False)
def get_nifty_5m(days: int = ST_5M_DAYS) -> pd.DataFrame:
    """
    Fetch 5m candles for SuperTrend display-only panel.
    ZERO decision weight. Visual reference only.
    Window : last ST_5M_DAYS trading days
    Cache  : TTL_5M = 5 minutes
    NSE session: 72 × 5m candles per day
    """
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        to_date   = date.today()
        from_date = to_date - timedelta(days=days + 2)

        data = kite.historical_data(
            NIFTY_INDEX_TOKEN,
            from_date.strftime("%Y-%m-%d"),
            to_date.strftime("%Y-%m-%d"),
            "5minute"
        )
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        df = df[["open", "high", "low", "close", "volume"]]

        target = days * 72
        if len(df) > target:
            df = df.tail(target)

        return df
    except Exception as e:
        log.error("5m fetch failed: %s", e); return pd.DataFrame()


# ─── Top 10 stocks daily ──────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_top10_daily_live(days: int = 400) -> dict[str, pd.DataFrame]:
    """Same as get_top10_daily but with short TTL for live RSI during market hours."""
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    result = {}
    to_date   = date.today()
    from_date = to_date - timedelta(days=days)
    for symbol, token in TOP_10_TOKENS.items():
        try:
            data = kite.historical_data(
                token, from_date.strftime("%Y-%m-%d"),
                to_date.strftime("%Y-%m-%d"), "day"
            )
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            result[symbol] = df[["open", "high", "low", "close", "volume"]]
        except Exception as e:
            log.warning("Stock live fetch %s: %s", symbol, e)
            result[symbol] = pd.DataFrame()
    return result


@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_top10_daily(days: int = 400) -> dict[str, pd.DataFrame]:
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    result = {}
    to_date   = date.today()
    from_date = to_date - timedelta(days=days)
    for symbol, token in TOP_10_TOKENS.items():
        try:
            data = kite.historical_data(
                token, from_date.strftime("%Y-%m-%d"),
                to_date.strftime("%Y-%m-%d"), "day"
            )
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            result[symbol] = df[["open", "high", "low", "close", "volume"]]
        except Exception as e:
            log.warning("Stock fetch %s: %s", symbol, e)
            result[symbol] = pd.DataFrame()
    return result


# ─── Options chain ────────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_OPTIONS, show_spinner=False)
def get_options_chain(expiry: date, spot: float) -> pd.DataFrame:
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    atm     = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
    strikes = range(atm-OI_STRIKE_RANGE, atm+OI_STRIKE_RANGE+OI_STRIKE_STEP, OI_STRIKE_STEP)
    exp     = f"{expiry.strftime('%y')}{expiry.month}{expiry.day}"
    symbols = []
    for s in strikes:
        symbols += [f"NFO:NIFTY{exp}{s}CE", f"NFO:NIFTY{exp}{s}PE"]
    try:
        data = kite.quote(symbols)
    except Exception as e:
        log.error("Batch OI failed: %s", e); data = {}
    records = []
    for s in strikes:
        ce = data.get(f"NFO:NIFTY{exp}{s}CE", {})
        pe = data.get(f"NFO:NIFTY{exp}{s}PE", {})
        records.append({
            "strike": s,
            "ce_oi": ce.get("oi",0), "ce_vol": ce.get("volume",0),
            "ce_ltp": ce.get("last_price",0), "ce_iv": ce.get("implied_volatility",0),
            "ce_oi_change": ce.get("oi_day_change",0),
            "pe_oi": pe.get("oi",0), "pe_vol": pe.get("volume",0),
            "pe_ltp": pe.get("last_price",0), "pe_iv": pe.get("implied_volatility",0),
            "pe_oi_change": pe.get("oi_day_change",0),
        })
    if not records: return pd.DataFrame()
    df = pd.DataFrame(records).set_index("strike")
    prev_ce = df["ce_oi"] - df["ce_oi_change"]
    prev_pe = df["pe_oi"] - df["pe_oi_change"]
    df["ce_pct_change"] = np.where(prev_ce>0, df["ce_oi_change"]/prev_ce*100, 0.0)
    df["pe_pct_change"] = np.where(prev_pe>0, df["pe_oi_change"]/prev_pe*100, 0.0)
    return df


@st.cache_data(ttl=TTL_OPTIONS, show_spinner=False)
def get_dual_expiry_chains(spot: float) -> dict:
    near_expiry, far_expiry = get_near_far_expiries()
    return {
        "near": get_options_chain(near_expiry, spot),
        "far":  get_options_chain(far_expiry,  spot),
        "near_expiry": near_expiry, "far_expiry": far_expiry,
        "near_dte": get_dte(near_expiry), "far_dte": get_dte(far_expiry),
    }


# ─── India VIX ───────────────────────────────────────────────────────────────

INDIA_VIX_TOKEN = 264969

@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_india_vix() -> float:
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        # Try token-based (same pattern as Nifty spot — most reliable)
        quote = kite.quote([f"NSE:{INDIA_VIX_TOKEN}"])
        for key in [f"NSE:{INDIA_VIX_TOKEN}", str(INDIA_VIX_TOKEN)]:
            if key in quote:
                return float(quote[key]["last_price"])
        # Fallback: symbol with space (may fail on some Kite versions)
        quote = kite.quote(["NSE:INDIA VIX"])
        for key in ["NSE:INDIA VIX", str(INDIA_VIX_TOKEN)]:
            if key in quote:
                return float(quote[key]["last_price"])
        return 0.0
    except Exception as e:
        log.error("VIX fetch: %s", e); return 0.0


@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_india_vix_detail() -> tuple:
    """Returns (vix_current, vix_chg_pts, vix_chg_pct). All 0.0 on failure."""
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        for symbols in [[f"NSE:{INDIA_VIX_TOKEN}"], ["NSE:INDIA VIX"]]:
            try:
                quote = kite.quote(symbols)
            except Exception:
                continue
            for key in [symbols[0], str(INDIA_VIX_TOKEN)]:
                if key in quote:
                    q       = quote[key]
                    cur     = float(q.get("last_price", 0) or 0)
                    prev    = float((q.get("ohlc") or {}).get("close", 0) or 0)
                    net_chg = float(q.get("net_change", 0) or 0)
                    # Use ohlc.close for pts/pct; fall back to net_change for pts
                    if prev > 0:
                        pts = cur - prev
                        pct = (pts / prev) * 100
                    else:
                        pts = net_chg
                        pct = (net_chg / cur * 100) if cur > 0 else 0.0
                    return cur, round(pts, 3), round(pct, 2)
        return 0.0, 0.0, 0.0
    except Exception as e:
        log.error("VIX detail fetch: %s", e); return 0.0, 0.0, 0.0


@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_vix_history(days: int = 365) -> pd.DataFrame:
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        to_date   = date.today()
        from_date = to_date - timedelta(days=days)
        data = kite.historical_data(INDIA_VIX_TOKEN,
            from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d"), "day")
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date").sort_index()
    except Exception as e:
        log.error("VIX history: %s", e); return pd.DataFrame()


# ─── Nifty 1H OHLCV — EMA Slope Phase Engine (Page 17) ─────────────────────

@st.cache_data(ttl=TTL_1H, show_spinner=False)
def _get_nifty_1h_ema_slope_cached(days: int) -> pd.DataFrame:
    """Inner fetch — raises on failure so Streamlit never caches an empty result."""
    kite      = _get_kite_safe()
    to_date   = date.today()
    from_date = to_date - timedelta(days=days + 14)  # +14 calendar-day buffer
    log.info("Fetching 1H EMA slope: %s → %s (%d trading days)", from_date, to_date, days)
    data = kite.historical_data(
        NIFTY_INDEX_TOKEN,
        from_date.strftime("%Y-%m-%d"),
        to_date.strftime("%Y-%m-%d"),
        "60minute",
    )
    if not data:
        raise RuntimeError("1H EMA slope fetch returned empty — will retry on next call")
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[["open", "high", "low", "close", "volume"]]
    target = days * 6
    if len(df) > target:
        df = df.tail(target)
    if len(df) < int(days * 6 * 0.6):
        log.warning("1H EMA slope: only %d candles (expected ~%d)", len(df), target)
    log.info("1H EMA slope ready: %d candles", len(df))
    return df


def get_nifty_1h_ema_slope(days: int = EMA_SLOPE_FETCH_DAYS) -> pd.DataFrame:
    """
    Fetch 60-min candles for the EMA Slope Phase Engine (Page 17).
    Default: 30 trading days = ~180 candles (ample warm-up for EMA-20 + ATR-14).
    Public wrapper — returns empty DataFrame on failure, never raises.
    """
    try:
        return _get_nifty_1h_ema_slope_cached(days)
    except Exception as e:
        log.error("1H EMA slope fetch failed: %s", e)
        return pd.DataFrame()


# ─── Generic Nifty intraday (Page 18 — Conviction Radar) ─────────────────────


def _trim_sessions(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Keep only the last `days` distinct trading sessions."""
    sessions = sorted(set(df.index.normalize()))
    if len(sessions) > days:
        cutoff = sessions[-days]
        df = df[df.index.normalize() >= cutoff]
    return df


@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_nifty_fut_token() -> int:
    """
    Resolve the CURRENT near-month NIFTY futures instrument token.
    Futures carry real traded volume (the index itself reports volume=0 on Kite),
    so VWAP / volume-delta must be computed on the future. Cached daily.
    Returns 0 on failure.
    """
    kite = _get_kite_safe()
    try:
        insts = kite.instruments("NFO")
        today = date.today()
        cands = []
        for i in insts:
            if i.get("name") == "NIFTY" and i.get("instrument_type") == "FUT":
                try:
                    exp = pd.to_datetime(i.get("expiry")).date()
                except Exception:
                    continue
                cands.append((exp, int(i["instrument_token"])))
        if not cands:
            return 0
        future = sorted([c for c in cands if c[0] >= today])
        return future[0][1] if future else sorted(cands)[-1][1]
    except Exception as e:
        log.error("Nifty fut token resolve failed: %s", e)
        return 0


def _fetch_intraday(token: int, interval: str, days: int) -> pd.DataFrame:
    kite = _get_kite_safe()
    to_date = date.today()
    from_date = to_date - timedelta(days=days + 5)   # +5 calendar buffer for weekends/holidays
    data = kite.historical_data(
        token, from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d"), interval,
    )
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return _trim_sessions(df[["open", "high", "low", "close", "volume"]], days)


@st.cache_data(ttl=TTL_5M, show_spinner=False)
def get_nifty_fut_intraday(interval: str = "15minute", days: int = 7) -> pd.DataFrame:
    """
    Near-month NIFTY FUTURES intraday OHLCV (WITH volume) for the Conviction Radar.
    Public wrapper — returns empty DataFrame on failure, never raises.
    """
    tok = get_nifty_fut_token()
    if not tok:
        return pd.DataFrame()
    try:
        return _fetch_intraday(tok, interval, days)
    except Exception as e:
        log.error("Nifty fut intraday (%s) fetch failed: %s", interval, e)
        return pd.DataFrame()


def _resample_to_nh(df: pd.DataFrame, hours: int) -> pd.DataFrame:
    """
    Session-aware resample of 60-min OHLCV → N-hour candles, stamped at the bucket
    start (always 09:15, then every `hours`). Buckets never span a day boundary.
    e.g. 2H → 09:15/11:15/13:15/15:15 · 4H → 09:15/13:15.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    block = int(hours) * 60
    idx = df.index
    mins = (idx.hour * 60 + idx.minute).to_numpy()
    bucket = np.clip((mins - (9 * 60 + 15)) // block, 0, None)
    start_min = 555 + bucket * block                               # 555 = 09:15 in minutes
    floored = idx.normalize() + pd.to_timedelta(start_min, unit="m")
    out = df.groupby(floored).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"))
    out.index.name = "date"
    return out.sort_index()


def _resample_to_2h(df: pd.DataFrame) -> pd.DataFrame:
    """Back-compat shim — 60-min → 2-hour candles (see _resample_to_nh)."""
    return _resample_to_nh(df, 2)


def get_nifty_fut_nh(hours: int = 2, days: int = 60) -> pd.DataFrame:
    """
    Near-month NIFTY FUTURES N-hour OHLCV (resampled from 60-min, WITH volume) for the
    positional Conviction tables (2H, 4H). Falls back to the index (no volume) if futures
    fail. Returns empty DataFrame on failure, never raises.
    """
    try:
        raw = get_nifty_fut_intraday(interval="60minute", days=days)
        if raw is None or raw.empty:
            raw = get_nifty_intraday(interval="60minute", days=days)   # index fallback
        return _resample_to_nh(raw, hours)
    except Exception as e:
        log.error("Nifty fut %sH fetch failed: %s", hours, e)
        return pd.DataFrame()


@st.cache_data(ttl=TTL_1H, show_spinner=False)
def get_nifty_fut_2h(days: int = 60) -> pd.DataFrame:
    """
    Near-month NIFTY FUTURES 2-hour OHLCV (resampled from 60-min, WITH volume) for the
    positional 2H Conviction Radar. Falls back to the index (no volume) if futures fail.
    Public wrapper — returns empty DataFrame on failure, never raises.
    """
    return get_nifty_fut_nh(2, days)


@st.cache_data(ttl=TTL_5M, show_spinner=False)
def get_nifty_intraday(interval: str = "15minute", days: int = 7) -> pd.DataFrame:
    """
    Nifty INDEX intraday OHLCV — fallback only. NOTE: the index reports volume=0,
    so VWAP / volume-delta degrade to a price-only proxy. Prefer the futures fetch.
    """
    try:
        return _fetch_intraday(NIFTY_INDEX_TOKEN, interval, days)
    except Exception as e:
        log.error("Nifty index intraday (%s) fetch failed: %s", interval, e)
        return pd.DataFrame()


@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_nifty50_tokens() -> dict:
    """
    Resolve the 50 Nifty-50 constituent instrument tokens.
    Uses data/nifty500_tokens.json if present, else resolves the first 50
    symbols from data/nifty500_symbols.json via Kite's NSE instrument dump.
    Returns {symbol: token}. Empty dict on failure.
    """
    import json, os
    try:
        syms_path = "data/nifty500_symbols.json"
        if not os.path.exists(syms_path):
            return {}
        with open(syms_path) as fh:
            nifty50 = json.load(fh)[:50]
        nset = set(nifty50)

        tok_path = "data/nifty500_tokens.json"
        if os.path.exists(tok_path):
            with open(tok_path) as fh:
                m = json.load(fh)
            out = {s: int(m[s]) for s in nifty50 if s in m}
            if len(out) >= 40:
                return out

        # Fall back to live resolution from the NSE instrument list.
        kite = _get_kite_safe()
        instruments = kite.instruments("NSE")
        out = {}
        for inst in instruments:
            sym = inst.get("tradingsymbol", "")
            if inst.get("instrument_type") == "EQ" and sym in nset:
                out[sym] = inst["instrument_token"]
        return out
    except Exception as e:
        log.error("Nifty50 token resolve failed: %s", e)
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def get_nifty50_intraday(interval: str = "15minute", days: int = 7) -> dict:
    """
    Fetch intraday OHLCV for all 50 Nifty-50 constituents (for breadth).
    Heavy (~50 historical calls) — cached 10 min. Returns {symbol: DataFrame};
    failed symbols are skipped. Empty dict on total failure.
    """
    tokens = get_nifty50_tokens()
    if not tokens:
        return {}
    kite = _get_kite_safe()
    to_date = date.today()
    from_date = to_date - timedelta(days=days + 5)
    out = {}
    # Kite historical API limit ≈ 3 requests/sec. Throttle + one backoff retry.
    THROTTLE = 0.34
    for sym, tok in tokens.items():
        data = None
        for attempt in range(2):
            try:
                data = kite.historical_data(
                    tok, from_date.strftime("%Y-%m-%d"),
                    to_date.strftime("%Y-%m-%d"), interval,
                )
                break
            except Exception as e:
                msg = str(e).lower()
                if attempt == 0 and ("too many" in msg or "rate" in msg or "throttle" in msg):
                    time.sleep(1.0)          # rate-limited — back off once and retry
                    continue
                log.warning("Breadth fetch %s failed: %s", sym, e)
                break
        if data:
            try:
                df = pd.DataFrame(data)
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date").sort_index()
                out[sym] = _trim_sessions(df[["open", "high", "low", "close", "volume"]], days)
            except Exception as e:
                log.warning("Breadth parse %s failed: %s", sym, e)
        time.sleep(THROTTLE)                 # stay under the per-second limit
    return out


# ─── Nifty 500 breadth ────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_nifty500_breadth() -> int:
    import os, json
    f = "data/parquet/market_health.json"
    if os.path.exists(f):
        with open(f) as fh:
            return json.load(fh).get("breadth_count", 0)
    return 0
