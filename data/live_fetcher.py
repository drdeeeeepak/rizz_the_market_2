# data/live_fetcher.py
# All Kite data fetching lives here. Analytics modules never call Kite directly.
#
# ALL FIXES (Apr 2026):
#   1. get_nifty_spot()     → "NSE:NIFTY 50" not token number
#   2. get_nifty_futures()  → NFO:NIFTY26APRFUT (YEAR first, then MONTH) — was reversed
#   3. get_nfo_instruments()→ instruments master, cached 24h
#   4. get_options_chain()  → validated tradingsymbol + BS IV fallback
#   5. _fill_iv_from_ltp()  → BS inversion when Kite IV=0 (pre-market / illiquid)
#   6. get_nifty_daily()    → timezone-normalized (fixes Market Profile crash)
#   7. get_vix_history()    → timezone-normalized
#   8. _get_kite()          → relative import .kite_client

import logging
import os
import json
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np

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

RISK_FREE = 0.065   # India risk-free ~6.5%


# ─── Kite client helper ───────────────────────────────────────────────────────

def _get_kite():
    """
    Relative import — both files are in data/ package.
    .kite_client resolves correctly regardless of sys.path.
    """
    from .kite_client import get_kite, get_kite_action
    return get_kite_action() if not _HAS_ST else get_kite()


# ─── Black-Scholes IV inversion ───────────────────────────────────────────────

def _bs_price(S, K, T, iv, r, opt_type):
    """Black-Scholes theoretical price."""
    from scipy.stats import norm
    if T <= 0 or iv <= 0:
        return max(0.0, (S - K) if opt_type == "CE" else (K - S))
    d1 = (np.log(S / K) + (r + 0.5 * iv ** 2) * T) / (iv * np.sqrt(T))
    d2 = d1 - iv * np.sqrt(T)
    if opt_type == "CE":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def _implied_vol(S, K, T, price, r=RISK_FREE, opt_type="CE"):
    """
    Newton-Raphson IV solver from market price.
    Returns IV as percentage (e.g. 12.5 for 12.5%). Returns 0.0 on failure.
    """
    from scipy.stats import norm
    intrinsic = max(0.0, (S - K) if opt_type == "CE" else (K - S))
    if price <= intrinsic + 0.01 or T <= 0:
        return 0.0
    iv = 0.20  # 20% starting guess
    try:
        for _ in range(50):
            p    = _bs_price(S, K, T, iv, r, opt_type)
            d1   = (np.log(S / K) + (r + 0.5 * iv ** 2) * T) / (iv * np.sqrt(T))
            vega = S * norm.pdf(d1) * np.sqrt(T)
            if vega < 1e-10:
                break
            diff = p - price
            if abs(diff) < 1e-5:
                break
            iv = iv - diff / vega
            iv = max(0.001, min(iv, 5.0))
        return round(iv * 100, 4)
    except Exception:
        return 0.0


def _fill_iv_from_ltp(df: pd.DataFrame, spot: float, expiry: date) -> pd.DataFrame:
    """
    For strikes where Kite returned implied_volatility=0 but LTP>0,
    compute IV via Black-Scholes inversion using LTP.

    Kite only populates implied_volatility after actual trades occur.
    Pre-market (before 9:15 AM IST) and illiquid strikes get IV=0 from Kite.
    This fallback ensures Greeks calculations work all day.
    """
    T = max((expiry - date.today()).days, 0.5) / 365.0
    df = df.copy()

    ce_iv_col, pe_iv_col = [], []
    for strike in df.index:
        # CE
        ce_iv  = float(df.loc[strike, "ce_iv"])
        ce_ltp = float(df.loc[strike, "ce_ltp"])
        if ce_iv == 0.0 and ce_ltp > 0.5:
            ce_iv = _implied_vol(spot, strike, T, ce_ltp, opt_type="CE")
        ce_iv_col.append(ce_iv)

        # PE
        pe_iv  = float(df.loc[strike, "pe_iv"])
        pe_ltp = float(df.loc[strike, "pe_ltp"])
        if pe_iv == 0.0 and pe_ltp > 0.5:
            pe_iv = _implied_vol(spot, strike, T, pe_ltp, opt_type="PE")
        pe_iv_col.append(pe_iv)

    df["ce_iv"] = ce_iv_col
    df["pe_iv"] = pe_iv_col
    return df


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


# ─── Nifty spot ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_nifty_spot() -> float:
    """Live Nifty 50 spot. Uses symbol string not token number."""
    kite = _get_kite()
    try:
        quote = kite.quote(["NSE:NIFTY 50"])
        if "NSE:NIFTY 50" in quote:
            return float(quote["NSE:NIFTY 50"]["last_price"])
        if str(NIFTY_INDEX_TOKEN) in quote:
            return float(quote[str(NIFTY_INDEX_TOKEN)]["last_price"])
        log.warning("Spot key not found. Keys: %s", list(quote.keys()))
        return 0.0
    except Exception as e:
        log.error("Spot fetch failed: %s", e)
        return 0.0


# ─── Nifty futures ───────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_nifty_futures() -> float:
    """
    Live Nifty near-month futures LTP.
    Kite format: NFO:NIFTY{YY}{MON}FUT  — YEAR first, then MONTH.
    e.g. April 2026 → NFO:NIFTY26APRFUT
    Previous bug: was NFO:NIFTYAPR26FUT (month first) — that returns nothing.
    """
    kite = _get_kite()
    try:
        now      = date.today()
        year_str = now.strftime("%y")           # 26
        mon_str  = now.strftime("%b").upper()   # APR
        symbol   = f"NFO:NIFTY{year_str}{mon_str}FUT"

        quote = kite.quote([symbol])
        if symbol in quote:
            return float(quote[symbol]["last_price"])

        # Fallback: next month (for rollover week)
        nm = (now.replace(day=28) + timedelta(days=4)).replace(day=1)
        sym2 = f"NFO:NIFTY{nm.strftime('%y')}{nm.strftime('%b').upper()}FUT"
        q2 = kite.quote([sym2])
        if sym2 in q2:
            return float(q2[sym2]["last_price"])

        log.warning("Futures not found. Tried: %s, %s", symbol, sym2)
        return 0.0
    except Exception as e:
        log.error("Futures fetch failed: %s", e)
        return 0.0


# ─── NFO instruments master ───────────────────────────────────────────────────

@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_nfo_instruments() -> pd.DataFrame:
    """
    Full NFO instruments dump filtered to NIFTY CE/PE.
    Cached 24h. This is Kite's source of truth for tradingsymbol strings.
    Columns: instrument_token, tradingsymbol, name, expiry, strike, instrument_type, lot_size
    """
    kite = _get_kite()
    try:
        df = pd.DataFrame(kite.instruments("NFO"))
        if df.empty:
            log.error("NFO instruments dump empty")
            return pd.DataFrame()
        df = df[df["name"] == "NIFTY"].copy()
        df = df[df["instrument_type"].isin(["CE", "PE"])].copy()
        df["expiry"] = pd.to_datetime(df["expiry"]).dt.date
        df["strike"] = df["strike"].astype(int)
        log.info("NFO instruments: %d rows, expiries: %s",
                 len(df), sorted(df["expiry"].unique())[:6])
        return df.reset_index(drop=True)
    except Exception as e:
        log.error("NFO instruments failed: %s", e)
        return pd.DataFrame()


# ─── Options chain ────────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_OPTIONS, show_spinner=False)
def get_options_chain(expiry: date, spot: float) -> pd.DataFrame:
    """
    Nifty options chain for one expiry. Returns DataFrame indexed by strike.
    Columns: ce_oi, ce_ltp, ce_iv, ce_vol, ce_oi_change, ce_pct_change
             pe_oi, pe_ltp, pe_iv, pe_vol, pe_oi_change, pe_pct_change

    IV is filled via Black-Scholes inversion where Kite returns 0
    (pre-market, illiquid strikes, non-traded contracts).
    """
    kite = _get_kite()

    instruments = get_nfo_instruments()
    if instruments.empty:
        return pd.DataFrame()

    expiry_df = instruments[instruments["expiry"] == expiry].copy()
    if expiry_df.empty:
        log.warning("No instruments for expiry %s. Available: %s",
                    expiry, sorted(instruments["expiry"].unique())[:8])
        return pd.DataFrame()

    atm = int(round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP)
    expiry_df = expiry_df[
        (expiry_df["strike"] >= atm - OI_STRIKE_RANGE) &
        (expiry_df["strike"] <= atm + OI_STRIKE_RANGE)
    ].copy()
    if expiry_df.empty:
        return pd.DataFrame()

    symbol_map: dict[str, dict] = {
        f"NFO:{row['tradingsymbol']}": {"strike": int(row["strike"]), "type": row["instrument_type"]}
        for _, row in expiry_df.iterrows()
    }

    quote_data: dict = {}
    symbols = list(symbol_map.keys())
    log.info("Quoting %d symbols for %s", len(symbols), expiry)
    for i in range(0, len(symbols), 500):
        try:
            quote_data.update(kite.quote(symbols[i: i + 500]))
        except Exception as e:
            log.error("Batch quote failed batch %d: %s", i // 500, e)

    if not quote_data:
        log.error("quote() empty for %s", expiry)
        return pd.DataFrame()

    records: dict[int, dict] = {}
    for sym, meta in symbol_map.items():
        strike = meta["strike"]
        p      = "ce_" if meta["type"] == "CE" else "pe_"
        q      = quote_data.get(sym, {})
        if strike not in records:
            records[strike] = {
                "strike":       strike,
                "ce_oi": 0,     "pe_oi": 0,
                "ce_vol": 0,    "pe_vol": 0,
                "ce_ltp": 0.0,  "pe_ltp": 0.0,
                "ce_iv": 0.0,   "pe_iv": 0.0,
                "ce_oi_change": 0, "pe_oi_change": 0,
            }
        records[strike][f"{p}oi"]        = int(q.get("oi", 0))
        records[strike][f"{p}vol"]       = int(q.get("volume", 0))
        records[strike][f"{p}ltp"]       = float(q.get("last_price", 0.0))
        records[strike][f"{p}iv"]        = float(q.get("implied_volatility", 0.0))
        records[strike][f"{p}oi_change"] = int(q.get("oi_day_change", 0))

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records.values()).set_index("strike").sort_index()

    for side in ["ce", "pe"]:
        prev = df[f"{side}_oi"] - df[f"{side}_oi_change"]
        df[f"{side}_pct_change"] = np.where(prev > 0, df[f"{side}_oi_change"] / prev * 100, 0.0)

    # Fill zero IV from LTP via Black-Scholes inversion
    df = _fill_iv_from_ltp(df, spot, expiry)

    log.info("Chain: %d strikes for %s ATM=%d", len(df), expiry, atm)
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


# ─── Nifty daily OHLCV ───────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_nifty_daily(days: int = 400) -> pd.DataFrame:
    """Timezone-naive daily OHLCV for Nifty 50."""
    kite = _get_kite()
    try:
        to_date   = date.today()
        from_date = to_date - timedelta(days=days)
        data = kite.historical_data(
            int(NIFTY_INDEX_TOKEN),
            from_date.strftime("%Y-%m-%d"),
            to_date.strftime("%Y-%m-%d"),
            "day"
        )
        df = pd.DataFrame(data)
        if df.empty:
            return pd.DataFrame()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        return df.set_index("date").sort_index()[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        log.error("Nifty daily failed: %s", e)
        return pd.DataFrame()


# ─── Top 10 stocks ───────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_top10_daily(days: int = 400) -> dict[str, pd.DataFrame]:
    """Timezone-naive daily OHLCV for top 10 Nifty stocks."""
    kite      = _get_kite()
    result    = {}
    to_date   = date.today()
    from_date = to_date - timedelta(days=days)
    for symbol, token in TOP_10_TOKENS.items():
        try:
            data = kite.historical_data(token,
                from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d"), "day")
            df = pd.DataFrame(data)
            if df.empty:
                result[symbol] = pd.DataFrame(); continue
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
            result[symbol] = df.set_index("date").sort_index()[["open","high","low","close","volume"]]
        except Exception as e:
            log.warning("Stock failed %s: %s", symbol, e)
            result[symbol] = pd.DataFrame()
    return result


# ─── India VIX ───────────────────────────────────────────────────────────────

INDIA_VIX_TOKEN = 264969

@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_india_vix() -> float:
    kite = _get_kite()
    try:
        q = kite.quote(["NSE:INDIA VIX"])
        if "NSE:INDIA VIX" in q:
            return float(q["NSE:INDIA VIX"]["last_price"])
        if str(INDIA_VIX_TOKEN) in q:
            return float(q[str(INDIA_VIX_TOKEN)]["last_price"])
        log.warning("VIX key not found. Keys: %s", list(q.keys()))
        return 0.0
    except Exception as e:
        log.error("VIX fetch failed: %s", e)
        return 0.0


@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_vix_history(days: int = 365) -> pd.DataFrame:
    kite = _get_kite()
    try:
        to_date   = date.today()
        from_date = to_date - timedelta(days=days)
        data = kite.historical_data(INDIA_VIX_TOKEN,
            from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d"), "day")
        df = pd.DataFrame(data)
        if df.empty:
            return pd.DataFrame()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        return df.set_index("date").sort_index()
    except Exception as e:
        log.error("VIX history failed: %s", e)
        return pd.DataFrame()


# ─── Nifty 500 breadth ───────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_nifty500_breadth() -> int:
    breadth_file = "data/parquet/market_health.json"
    if os.path.exists(breadth_file):
        try:
            with open(breadth_file) as f:
                return int(json.load(f).get("breadth_count", 0))
        except Exception as e:
            log.warning("market_health.json read failed: %s", e)
    return 0


# ─── Debug helper ────────────────────────────────────────────────────────────

def debug_instruments_sample(expiry: Optional[date] = None) -> None:
    """Verify Kite symbol format live. Add to any page temporarily."""
    try:
        import streamlit as st
    except ImportError:
        return
    instr = get_nfo_instruments()
    if instr.empty:
        st.error("Instruments empty — check Kite auth"); return
    all_exp = sorted(instr["expiry"].unique())
    st.write("**NIFTY expiries available:**", all_exp[:10])
    target = expiry or all_exp[0]
    st.write(f"**Sample symbols for {target}:**",
             instr[instr["expiry"] == target]["tradingsymbol"].head(10).tolist())
    st.caption("These are the exact strings Kite quote() accepts.")
