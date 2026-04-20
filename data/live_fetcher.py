# data/live_fetcher.py
# All Kite data fetching lives here. Analytics modules never call Kite directly.
# Caching: options=30s, price=60s, daily OHLCV=24hr.

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
    # Stub for @st.cache_data when running outside Streamlit (e.g. GitHub Actions)
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
    """Return the next Tuesday on or after from_date."""
    d = from_date or date.today()
    days_ahead = EXPIRY_WEEKDAY - d.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)


def get_near_far_expiries() -> tuple[date, date]:
    """
    Near expiry = this week's Tuesday.
    Far expiry  = next week's Tuesday (your trade).
    """
    today = date.today()
    near = next_tuesday(today)
    far  = next_tuesday(near + timedelta(days=1))
    return near, far


def get_dte(expiry: date) -> int:
    """Days to expiry from today."""
    return max(0, (expiry - date.today()).days)


# ─── Nifty spot price ─────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_nifty_spot() -> float:
    """Live Nifty 50 spot price."""
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        quote = kite.quote([f"NSE:{NIFTY_INDEX_TOKEN}"])
        # Kite returns data keyed by token string
        if str(NIFTY_INDEX_TOKEN) in quote:
            return float(quote[str(NIFTY_INDEX_TOKEN)]["last_price"])
        # Fallback: exchange:token key
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
    """
    Daily OHLCV for Nifty 50 index.
    Returns DataFrame with columns: date, open, high, low, close, volume.
    """
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
def get_top10_daily(days: int = 400) -> dict[str, pd.DataFrame]:
    """
    Daily OHLCV for each top 10 stock.
    Returns {symbol: DataFrame}.
    """
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
    Fetch Nifty options chain for a given expiry date.
    Returns DataFrame with strikes ± OI_STRIKE_RANGE from spot.
    Columns: strike, ce_oi, ce_vol, ce_ltp, ce_iv, ce_oi_change,
                      pe_oi, pe_vol, pe_ltp, pe_iv, pe_oi_change
    """
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()

    # Build ATM ± range strikes
    atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
    strikes = range(
        atm - OI_STRIKE_RANGE,
        atm + OI_STRIKE_RANGE + OI_STRIKE_STEP,
        OI_STRIKE_STEP
    )

    # Kite NFO weekly format: YY + M (no zero pad) + DD
    # e.g. Apr 14 2026 → 26414 → NIFTY2641422500CE
    # e.g. Oct 14 2026 → 261014 → NIFTY26101422500CE
    yy  = expiry.strftime("%y")   # 26
    m   = expiry.month            # 4 (no zero pad — Kite uses 1-digit months)
    dd  = expiry.day              # 14
    expiry_str = f"{yy}{m}{dd}"   # 26414
    # Build all symbols at once for batch quote (far more efficient)
    symbols = []
    for strike in strikes:
        symbols.append(f"NFO:NIFTY{expiry_str}{strike}CE")
        symbols.append(f"NFO:NIFTY{expiry_str}{strike}PE")

    # Kite quote accepts up to 500 symbols per call
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
        records.append({
            "strike":      strike,
            "ce_oi":       ce.get("oi", 0),
            "ce_vol":      ce.get("volume", 0),
            "ce_ltp":      ce.get("last_price", 0),
            "ce_iv":       ce.get("implied_volatility", 0),
            "ce_oi_change":ce.get("oi_day_change", 0),
            "pe_oi":       pe.get("oi", 0),
            "pe_vol":      pe.get("volume", 0),
            "pe_ltp":      pe.get("last_price", 0),
            "pe_iv":       pe.get("implied_volatility", 0),
            "pe_oi_change":pe.get("oi_day_change", 0),
        })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records).set_index("strike")

    # Compute % OI changes (avoid division by zero)
    prev_ce = df["ce_oi"] - df["ce_oi_change"]
    prev_pe = df["pe_oi"] - df["pe_oi_change"]
    df["ce_pct_change"] = np.where(
        prev_ce > 0, df["ce_oi_change"] / prev_ce * 100, 0.0
    )
    df["pe_pct_change"] = np.where(
        prev_pe > 0, df["pe_oi_change"] / prev_pe * 100, 0.0
    )
    return df


@st.cache_data(ttl=TTL_OPTIONS, show_spinner=False)
def get_dual_expiry_chains(spot: float) -> dict:
    """
    Fetch both near and far expiry chains in one call.
    Returns {"near": df, "far": df, "near_expiry": date, "far_expiry": date,
             "near_dte": int, "far_dte": int}
    """
    near_expiry, far_expiry = get_near_far_expiries()
    return {
        "near":        get_options_chain(near_expiry, spot),
        "far":         get_options_chain(far_expiry,  spot),
        "near_expiry": near_expiry,
        "far_expiry":  far_expiry,
        "near_dte":    get_dte(near_expiry),
        "far_dte":     get_dte(far_expiry),
    }


# ─── India VIX ───────────────────────────────────────────────────────────────

INDIA_VIX_TOKEN = 264969   # NSE:INDIA VIX

@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_india_vix() -> float:
    """India VIX live value."""
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        # India VIX is a special index — fetch by symbol name, not token number.
        # Kite returns it keyed as "NSE:INDIA VIX" in the response dict.
        quote = kite.quote(["NSE:INDIA VIX"])
        if "NSE:INDIA VIX" in quote:
            return float(quote["NSE:INDIA VIX"]["last_price"])
        # Fallback: try by integer token (264969) as string key
        if str(INDIA_VIX_TOKEN) in quote:
            return float(quote[str(INDIA_VIX_TOKEN)]["last_price"])
        # Fallback 2: try NSE:token format
        key2 = f"NSE:{INDIA_VIX_TOKEN}"
        if key2 in quote:
            return float(quote[key2]["last_price"])
        log.warning("VIX key not found. Keys returned: %s", list(quote.keys())[:5])
        return 0.0
    except Exception as e:
        log.error("VIX fetch failed: %s", e)
        return 0.0


@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_vix_history(days: int = 365) -> pd.DataFrame:
    """Historical India VIX for IVP calculation."""
    from data.kite_client import get_kite, get_kite_action
    kite = get_kite_action() if not _HAS_ST else get_kite()
    try:
        to_date   = date.today()
        from_date = to_date - timedelta(days=days)
        data = kite.historical_data(
            INDIA_VIX_TOKEN,
            from_date.strftime("%Y-%m-%d"),
            to_date.strftime("%Y-%m-%d"),
            "day"
        )
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date").sort_index()
    except Exception as e:
        log.error("VIX history failed: %s", e)
        return pd.DataFrame()


# ─── Nifty 500 breadth (for Geometric Edge health gate) ──────────────────────

@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_nifty500_breadth() -> int:
    """
    Count of Nifty 500 stocks trading above their 200-day SMA.
    Used as market health gate for Geometric Edge scanner.
    NOTE: This requires fetching all Nifty 500 instruments — expensive.
    Runs once daily via GitHub Actions and saves result to parquet.
    In live dashboard, reads from saved file instead.
    """
    import os, json
    breadth_file = "data/parquet/market_health.json"
    if os.path.exists(breadth_file):
        with open(breadth_file) as f:
            data = json.load(f)
            return data.get("breadth_count", 0)
    return 0   # fallback if not yet computed
