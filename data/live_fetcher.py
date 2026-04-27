# data/live_fetcher.py
# All Kite data fetching lives here. Analytics modules never call Kite directly.
# Updated 27 Apr 2026: single get_nifty_1h_phase() replaces all previous 1H fetchers.

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
        quote = kite.quote([f"NSE:{NIFTY_INDEX_TOKEN}"])
        for key in [str(NIFTY_INDEX_TOKEN), f"NSE:{NIFTY_INDEX_TOKEN}"]:
            if key in quote:
                return float(quote[key]["last_price"])
        log.warning("Spot key not found. Keys: %s", list(quote.keys())[:5])
        return 0.0
    except Exception as e:
        log.error("Spot fetch failed: %s", e); return 0.0


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

    Window  : last N trading days (default 20 = 120 candles at 6/day)
    Interval: 60minute (Kite)
    Cache   : TTL_1H = 1 hour
    Frozen  : NO — fetched fresh every day

    This is the ONLY 1H fetch in the system.
    Replaces get_nifty_1h_structural() and get_nifty_1h_breach().

    Returns DataFrame with DatetimeIndex (ascending),
    columns: open, high, low, close, volume.

    NSE session = 9:15 AM to 3:30 PM = 6 complete 1H candles per day.
    20 trading days × 6 = 120 candles expected.
    """
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        to_date   = date.today()
        # Add buffer: 20 trading days ≈ 30 calendar days
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

        # Trim to last days×6 candles
        target = days * 6
        if len(df) > target:
            df = df.tail(target)

        # Sanity
        if len(df) < int(days * 6 * 0.6):
            log.warning("1H phase: only %d candles (expected ~%d)", len(df), target)

        log.info("1H phase ready: %d candles", len(df))
        return df
    except Exception as e:
        log.error("1H phase fetch failed: %s", e); return pd.DataFrame()


# ─── Top 10 stocks daily ──────────────────────────────────────────────────────

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
        quote = kite.quote(["NSE:INDIA VIX"])
        for key in ["NSE:INDIA VIX", str(INDIA_VIX_TOKEN), f"NSE:{INDIA_VIX_TOKEN}"]:
            if key in quote: return float(quote[key]["last_price"])
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
