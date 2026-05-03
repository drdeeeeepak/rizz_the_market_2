# data/live_fetcher.py
# All Kite data fetching lives here. Analytics modules never call Kite directly.
# Updated 27 Apr 2026: single get_nifty_1h_phase() replaces all previous 1H fetchers.
# Updated 27 Apr 2026: added get_nifty_15m(), get_nifty_30m(), get_nifty_5m() for SuperTrend MTF page.

import logging
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


# ─── India VIX ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_india_vix() -> tuple:
    """Returns (vix_current, vix_change_pct). Both 0.0 on failure."""
    try:
        from data.kite_client import get_kite
        kite = get_kite()
        quote = kite.quote(["NSE:INDIA VIX"])
        for key in ["NSE:INDIA VIX", "INDIA VIX"]:
            if key in quote:
                q = quote[key]
                cur = float(q.get("last_price", 0) or 0)
                chg = float(q.get("change_percent", 0) or q.get("net_change", 0) or 0)
                return cur, chg
        return 0.0, 0.0
    except Exception:
        return 0.0, 0.0


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
def get_nifty_daily(days: int = 400) -> pd.DataFrame:
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
        log.error("Nifty daily fetch failed: %s", e); return pd.DataFrame()


# ─── Nifty 1H OHLCV — Dow Theory Phase Window ────────────────────────────────

@st.cache_data(ttl=TTL_1H, show_spinner=False)
def get_nifty_1h_phase(days: int = DOW_PHASE_DAYS) -> pd.DataFrame:
    """
    Fetch 1H candles for Dow Theory phase engine.
    Also used by SuperTrend engine for 1H TF and proxy resampling to 2H/4H.

    Window  : last N trading days (default 20 = 120 candles at 6/day)
    Interval: 60minute (Kite)
    Cache   : TTL_1H = 1 hour
    Frozen  : NO — fetched fresh every day

    This is the ONLY 1H fetch in the system.
    SuperTrend resamples 2H and 4H from this same DataFrame.
    """
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        to_date   = date.today()
        from_date = to_date - timedelta(days=days + 12)

        log.info("Fetching 1H phase: %s → %s (%d trading days)", from_date, to_date, days)
        data = kite.historical_data(
            NIFTY_INDEX_TOKEN,
            from_date.strftime("%Y-%m-%d"),
            to_date.strftime("%Y-%m-%d"),
            "60minute"
        )
        if not data:
            log.error("1H phase fetch empty"); return pd.DataFrame()

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
    except Exception as e:
        log.error("1H phase fetch failed: %s", e); return pd.DataFrame()


# ─── Nifty 30m OHLCV — SuperTrend Tier 3 ────────────────────────────────────

@st.cache_data(ttl=TTL_30M, show_spinner=False)
def get_nifty_30m(days: int = ST_30M_DAYS) -> pd.DataFrame:
    """
    Fetch 30m candles for SuperTrend Tier 3.
    Window : last ST_30M_DAYS trading days
    Cache  : TTL_30M = 30 minutes
    Used by: SuperTrend MTF engine (analytics/supertrend.py)
    Returns DataFrame with DatetimeIndex, columns: open/high/low/close/volume
    NSE session: 6 × 1H = 12 × 30m candles per day
    """
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        to_date   = date.today()
        from_date = to_date - timedelta(days=days + 5)

        log.info("Fetching 30m ST: %s → %s", from_date, to_date)
        data = kite.historical_data(
            NIFTY_INDEX_TOKEN,
            from_date.strftime("%Y-%m-%d"),
            to_date.strftime("%Y-%m-%d"),
            "30minute"
        )
        if not data:
            log.error("30m fetch empty"); return pd.DataFrame()

        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        df = df[["open", "high", "low", "close", "volume"]]

        # Need enough candles for ST(21): at least 21 + buffer
        # 12 candles/day × days
        target = days * 12
        if len(df) > target:
            df = df.tail(target)

        log.info("30m ST ready: %d candles", len(df))
        return df
    except Exception as e:
        log.error("30m fetch failed: %s", e); return pd.DataFrame()


# ─── Nifty 15m OHLCV — SuperTrend Tier 3 ────────────────────────────────────

@st.cache_data(ttl=TTL_15M, show_spinner=False)
def get_nifty_15m(days: int = ST_15M_DAYS) -> pd.DataFrame:
    """
    Fetch 15m candles for SuperTrend Tier 3.
    Window : last ST_15M_DAYS trading days
    Cache  : TTL_15M = 15 minutes
    Used by: SuperTrend MTF engine (analytics/supertrend.py)
    Returns DataFrame with DatetimeIndex, columns: open/high/low/close/volume
    NSE session: 24 × 15m candles per day
    """
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        to_date   = date.today()
        from_date = to_date - timedelta(days=days + 3)

        log.info("Fetching 15m ST: %s → %s", from_date, to_date)
        data = kite.historical_data(
            NIFTY_INDEX_TOKEN,
            from_date.strftime("%Y-%m-%d"),
            to_date.strftime("%Y-%m-%d"),
            "15minute"
        )
        if not data:
            log.error("15m fetch empty"); return pd.DataFrame()

        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        df = df[["open", "high", "low", "close", "volume"]]

        # 24 candles/day × days
        target = days * 24
        if len(df) > target:
            df = df.tail(target)

        log.info("15m ST ready: %d candles", len(df))
        return df
    except Exception as e:
        log.error("15m fetch failed: %s", e); return pd.DataFrame()


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


# ─── Nifty 500 breadth ────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_nifty500_breadth() -> int:
    import os, json
    f = "data/parquet/market_health.json"
    if os.path.exists(f):
        with open(f) as fh:
            return json.load(fh).get("breadth_count", 0)
    return 0
