# data/live_fetcher.py — v2 (22 April 2026)
# All Kite data fetching lives here. Analytics modules never call Kite directly.
# Caching: options=30s, price=60s, daily OHLCV=24hr.
#
# CHANGES vs v1:
#   - get_vix_history: added yfinance fallback when Kite fails
#   - get_vix_history: ensures "close" column always present
#   - get_nifty_futures_ltp: new function for futures premium on Page 10

import logging
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np

# Graceful Streamlit import — works headlessly in GitHub Actions too
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
    NIFTY_INDEX_TOKEN, TOP_10_TOKENS, TTL_OPTIONS, TTL_PRICE, TTL_DAILY,
    OI_STRIKE_STEP, OI_STRIKE_RANGE, EXPIRY_WEEKDAY
)

log = logging.getLogger(__name__)


# ─── Expiry helpers ───────────────────────────────────────────────────────────

def next_tuesday(from_date: Optional[date] = None) -> date:
    d = from_date or date.today()
    days_ahead = EXPIRY_WEEKDAY - d.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)


def get_near_far_expiries() -> tuple:
    today = date.today()
    near = next_tuesday(today)
    far  = next_tuesday(near + timedelta(days=1))
    return near, far


def get_dte(expiry: date) -> int:
    return max(0, (expiry - date.today()).days)


# ─── Nifty spot price ─────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_nifty_spot() -> float:
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        quote = kite.quote([f"NSE:{NIFTY_INDEX_TOKEN}"])
        if str(NIFTY_INDEX_TOKEN) in quote:
            return float(quote[str(NIFTY_INDEX_TOKEN)]["last_price"])
        key2 = f"NSE:{NIFTY_INDEX_TOKEN}"
        if key2 in quote:
            return float(quote[key2]["last_price"])
        log.warning("Spot key not found. Keys: %s", list(quote.keys())[:5])
        return 0.0
    except Exception as e:
        log.error("Spot fetch failed: %s", e)
        return 0.0


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
        log.error("Nifty daily fetch failed: %s", e)
        return pd.DataFrame()


# ─── Top 10 stocks daily OHLCV ───────────────────────────────────────────────

@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_top10_daily(days: int = 400) -> dict:
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    result = {}
    to_date   = date.today()
    from_date = to_date - timedelta(days=days)
    for symbol, token in TOP_10_TOKENS.items():
        try:
            data = kite.historical_data(
                token,
                from_date.strftime("%Y-%m-%d"),
                to_date.strftime("%Y-%m-%d"),
                "day"
            )
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            result[symbol] = df[["open", "high", "low", "close", "volume"]]
        except Exception as e:
            log.warning("Stock fetch failed %s: %s", symbol, e)
            result[symbol] = pd.DataFrame()
    return result


# ─── Options chain ────────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_OPTIONS, show_spinner=False)
def get_options_chain(expiry: date, spot: float) -> pd.DataFrame:
    """
    Fetch Nifty options chain for a given expiry.
    Returns DataFrame indexed by strike with columns:
    ce_oi, ce_vol, ce_ltp, ce_iv, ce_oi_change, ce_pct_change,
    pe_oi, pe_vol, pe_ltp, pe_iv, pe_oi_change, pe_pct_change
    """
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()

    atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
    strikes = range(
        atm - OI_STRIKE_RANGE,
        atm + OI_STRIKE_RANGE + OI_STRIKE_STEP,
        OI_STRIKE_STEP
    )

    yy  = expiry.strftime("%y")
    m   = expiry.month
    dd  = expiry.day
    expiry_str = f"{yy}{m}{dd}"

    symbols = []
    for strike in strikes:
        symbols.append(f"NFO:NIFTY{expiry_str}{strike}CE")
        symbols.append(f"NFO:NIFTY{expiry_str}{strike}PE")

    try:
        data = kite.quote(symbols)
    except Exception as e:
        log.error("Batch OI fetch failed: %s", e)
        data = {}

    records = []
    for strike in strikes:
        ce_sym = f"NFO:NIFTY{expiry_str}{strike}CE"
        pe_sym = f"NFO:NIFTY{expiry_str}{strike}PE"
        ce = data.get(ce_sym, {})
        pe = data.get(pe_sym, {})

        # Greeks — extracted from ohlc/depth sub-dicts if present
        ce_greeks = ce.get("greeks", {})
        pe_greeks = pe.get("greeks", {})

        records.append({
            "strike":       strike,
            # CE
            "ce_oi":        ce.get("oi", 0),
            "ce_vol":       ce.get("volume", 0),
            "ce_ltp":       ce.get("last_price", 0),
            "ce_iv":        ce.get("implied_volatility", 0),
            "ce_oi_change": ce.get("oi_day_change", 0),
            "ce_delta":     ce_greeks.get("delta", 0),
            "ce_gamma":     ce_greeks.get("gamma", 0),
            "ce_theta":     ce_greeks.get("theta", 0),
            "ce_vega":      ce_greeks.get("vega",  0),
            # PE
            "pe_oi":        pe.get("oi", 0),
            "pe_vol":       pe.get("volume", 0),
            "pe_ltp":       pe.get("last_price", 0),
            "pe_iv":        pe.get("implied_volatility", 0),
            "pe_oi_change": pe.get("oi_day_change", 0),
            "pe_delta":     pe_greeks.get("delta", 0),
            "pe_gamma":     pe_greeks.get("gamma", 0),
            "pe_theta":     pe_greeks.get("theta", 0),
            "pe_vega":      pe_greeks.get("vega",  0),
        })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records).set_index("strike")

    # Pct OI changes
    prev_ce = df["ce_oi"] - df["ce_oi_change"]
    prev_pe = df["pe_oi"] - df["pe_oi_change"]
    df["ce_pct_change"] = np.where(prev_ce > 0, df["ce_oi_change"] / prev_ce * 100, 0.0)
    df["pe_pct_change"] = np.where(prev_pe > 0, df["pe_oi_change"] / prev_pe * 100, 0.0)

    return df


@st.cache_data(ttl=TTL_OPTIONS, show_spinner=False)
def get_dual_expiry_chains(spot: float) -> dict:
    near_expiry, far_expiry = get_near_far_expiries()
    return {
        "near":        get_options_chain(near_expiry, spot),
        "far":         get_options_chain(far_expiry,  spot),
        "near_expiry": near_expiry,
        "far_expiry":  far_expiry,
        "near_dte":    get_dte(near_expiry),
        "far_dte":     get_dte(far_expiry),
    }


# ─── Nifty futures LTP (for futures premium on Page 10) ──────────────────────

@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_nifty_futures_ltp() -> float:
    """
    Nifty near-month futures last traded price.
    Used to compute futures premium = futures LTP - spot.
    Returns 0.0 if unavailable — Page 10 handles gracefully.
    """
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        # Near-month futures expiry
        today = date.today()
        # Last Thursday of current month
        # Approximate: use next_tuesday logic adapted for Thursday (weekday=3)
        d = today
        days_to_thu = (3 - d.weekday()) % 7
        if days_to_thu == 0 and d.weekday() == 3:
            days_to_thu = 7
        near_thu = d + timedelta(days=days_to_thu)

        yy = near_thu.strftime("%y")
        mon_abbr = near_thu.strftime("%b").upper()   # JAN, FEB ...
        sym = f"NFO:NIFTY{yy}{mon_abbr}FUT"

        quote = kite.quote([sym])
        if sym in quote:
            return float(quote[sym]["last_price"])
        log.warning("Futures symbol %s not found in quote", sym)
        return 0.0
    except Exception as e:
        log.warning("Futures LTP fetch failed: %s", e)
        return 0.0


# ─── India VIX ───────────────────────────────────────────────────────────────

INDIA_VIX_TOKEN = 264969   # NSE:INDIA VIX

@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_india_vix() -> float:
    """India VIX live value."""
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        quote = kite.quote(["NSE:INDIA VIX"])
        if "NSE:INDIA VIX" in quote:
            return float(quote["NSE:INDIA VIX"]["last_price"])
        if str(INDIA_VIX_TOKEN) in quote:
            return float(quote[str(INDIA_VIX_TOKEN)]["last_price"])
        key2 = f"NSE:{INDIA_VIX_TOKEN}"
        if key2 in quote:
            return float(quote[key2]["last_price"])
        log.warning("VIX key not found. Keys returned: %s", list(quote.keys())[:5])
        return 0.0
    except Exception as e:
        log.error("VIX fetch failed: %s", e)
        return 0.0


@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_vix_history(days: int = 400) -> pd.DataFrame:
    """
    Historical India VIX daily closes for IVP and SMA calculations.
    Cached daily — does not change intraday.
    Returns DataFrame with DatetimeIndex and 'close' column.
    Attempts Kite first, falls back to yfinance.
    days=400 gives enough history for 200-day SMA + buffer.
    """
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()

    # ── Attempt 1: Kite Connect ───────────────────────────────────────────────
    try:
        to_date   = date.today()
        from_date = to_date - timedelta(days=days + 60)   # buffer for holidays
        data = kite.historical_data(
            INDIA_VIX_TOKEN,
            from_date.strftime("%Y-%m-%d"),
            to_date.strftime("%Y-%m-%d"),
            "day"
        )
        if data:
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            # Ensure "close" column exists
            if "close" not in df.columns and "last_price" in df.columns:
                df["close"] = df["last_price"]
            if "close" in df.columns and len(df) > 100:
                log.info("VIX history: %d rows from Kite", len(df))
                return df[["close"]]
    except Exception as e:
        log.warning("VIX history Kite failed: %s — trying yfinance fallback", e)

    # ── Attempt 2: yfinance fallback ──────────────────────────────────────────
    try:
        import yfinance as yf
        vix_yf = yf.download(
            "^INDIAVIX",
            period="2y",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        if not vix_yf.empty:
            # yfinance returns MultiIndex columns or simple columns
            if isinstance(vix_yf.columns, pd.MultiIndex):
                vix_yf.columns = vix_yf.columns.get_level_values(0)
            close_col = "Close" if "Close" in vix_yf.columns else vix_yf.columns[0]
            df = vix_yf[[close_col]].rename(columns={close_col: "close"})
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            log.info("VIX history: %d rows from yfinance", len(df))
            return df
    except Exception as e:
        log.error("VIX history yfinance also failed: %s", e)

    log.error("VIX history: all sources failed — returning empty DataFrame")
    return pd.DataFrame()


# ─── Nifty 500 breadth ────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_nifty500_breadth() -> int:
    import os, json
    breadth_file = "data/parquet/market_health.json"
    if os.path.exists(breadth_file):
        with open(breadth_file) as f:
            data = json.load(f)
            return data.get("breadth_count", 0)
    return 0
