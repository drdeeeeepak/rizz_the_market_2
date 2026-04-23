# live_fetcher.py
# All Kite data fetching lives here. Analytics modules never call Kite directly.
#
# KEY FIXES in this version (Apr 2026):
#   1. get_nifty_spot()     → uses "NSE:NIFTY 50" symbol (not token number)
#   2. get_nfo_instruments()→ NEW — fetches live NFO dump from Kite (cached 24h)
#   3. get_options_chain()  → uses validated tradingsymbol from instruments dump
#                             (not manually constructed strings)
#   4. get_nifty_daily()    → timezone-normalized index (fixes Market Profile crash)
#   5. get_vix_history()    → timezone-normalized index
#
# Caching: options=30s, price=60s, daily OHLCV=24h, instruments=24h

import logging
import os
import json
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

# ─── Kite client helper ───────────────────────────────────────────────────────

def _get_kite():
    """
    Return authenticated KiteConnect — works in both Streamlit and Actions.

    Both live_fetcher.py and kite_client.py live in the data/ package.
    Use a relative import (.kite_client) which always works regardless of
    how Python's sys.path is configured.
    """
    from .kite_client import get_kite, get_kite_action
    return get_kite_action() if not _HAS_ST else get_kite()


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
    Near expiry = this week's Tuesday (intelligence / OI wall read).
    Far expiry  = next week's Tuesday (your actual trade leg).
    """
    today = date.today()
    near  = next_tuesday(today)
    far   = next_tuesday(near + timedelta(days=1))
    return near, far


def get_dte(expiry: date) -> int:
    """Days to expiry from today (floor 0)."""
    return max(0, (expiry - date.today()).days)


# ─── Nifty spot price ─────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_nifty_spot() -> float:
    """
    Live Nifty 50 spot price.

    FIX: Kite quote() must be called with the SYMBOL string "NSE:NIFTY 50",
    not with the integer token number. When called by token, Kite returns an
    empty dict {} — which caused the "Spot key not found. Keys: []" log error.
    """
    kite = _get_kite()
    try:
        quote = kite.quote(["NSE:NIFTY 50"])

        # Primary key — Kite returns result keyed exactly as you requested
        if "NSE:NIFTY 50" in quote:
            return float(quote["NSE:NIFTY 50"]["last_price"])

        # Fallback — some older kiteconnect versions key by token string
        token_str = str(NIFTY_INDEX_TOKEN)
        if token_str in quote:
            return float(quote[token_str]["last_price"])

        # Nothing found — log all returned keys so you can diagnose quickly
        log.warning("Spot key not found. Keys returned: %s", list(quote.keys()))
        return 0.0

    except Exception as e:
        log.error("Spot fetch failed: %s", e)
        return 0.0


# ─── NFO instruments master (the key to correct options symbols) ──────────────

@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_nfo_instruments() -> pd.DataFrame:
    """
    Fetch the full NFO instruments dump from Kite and filter to NIFTY options.

    WHY THIS EXISTS:
      Kite's quote() API requires EXACT tradingsymbol strings
      (e.g. "NFO:NIFTY2542922500CE"). These cannot be guessed reliably because:
        - Monthly expiries use 3-letter month codes (e.g. 26APR)
        - Weekly expiries use numeric format (e.g. 2542)
        - Strike formatting varies (no leading zeros, exact integer)
      The instruments dump is Kite's own source of truth.

    Returns DataFrame with columns:
      instrument_token, tradingsymbol, name, expiry (date), strike,
      instrument_type (CE/PE), lot_size
    Cached for 24 hours (instruments don't change intraday).
    """
    kite = _get_kite()
    try:
        raw = kite.instruments("NFO")
        df  = pd.DataFrame(raw)

        if df.empty:
            log.error("NFO instruments dump returned empty DataFrame")
            return pd.DataFrame()

        # Keep only NIFTY index options (not NIFTYNXT50, BANKNIFTY etc.)
        df = df[df["name"] == "NIFTY"].copy()
        df = df[df["instrument_type"].isin(["CE", "PE"])].copy()

        # Normalize expiry to Python date (Kite returns datetime or date)
        df["expiry"] = pd.to_datetime(df["expiry"]).dt.date

        # Strike as integer for easy ATM math
        df["strike"] = df["strike"].astype(int)

        log.info(
            "NFO instruments loaded: %d NIFTY CE/PE rows, expiries: %s",
            len(df),
            sorted(df["expiry"].unique())[:6]
        )
        return df.reset_index(drop=True)

    except Exception as e:
        log.error("NFO instruments fetch failed: %s", e)
        return pd.DataFrame()


# ─── Options chain ────────────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_OPTIONS, show_spinner=False)
def get_options_chain(expiry: date, spot: float) -> pd.DataFrame:
    """
    Fetch Nifty options chain for a given expiry using validated instrument symbols.

    HOW IT WORKS:
      1. Load NFO instruments master (cached 24h — one call per day)
      2. Filter to this expiry date
      3. Filter strikes within ATM ± OI_STRIKE_RANGE
      4. Use exact tradingsymbol strings from Kite's own dump
      5. Batch quote() — up to 500 symbols per call
      6. Build clean DataFrame

    Returns DataFrame indexed by strike with columns:
      ce_oi, ce_vol, ce_ltp, ce_iv, ce_oi_change, ce_pct_change
      pe_oi, pe_vol, pe_ltp, pe_iv, pe_oi_change, pe_pct_change
    """
    kite = _get_kite()

    # ── Step 1: Get instruments master ────────────────────────────────────────
    instruments = get_nfo_instruments()
    if instruments.empty:
        log.error("Options chain: instruments dump unavailable")
        return pd.DataFrame()

    # ── Step 2: Filter to requested expiry ────────────────────────────────────
    expiry_df = instruments[instruments["expiry"] == expiry].copy()
    if expiry_df.empty:
        available = sorted(instruments["expiry"].unique())
        log.warning(
            "Options chain: no instruments for expiry %s. Available: %s",
            expiry, available[:8]
        )
        return pd.DataFrame()

    # ── Step 3: Filter strikes near ATM ───────────────────────────────────────
    atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
    lo  = atm - OI_STRIKE_RANGE
    hi  = atm + OI_STRIKE_RANGE
    expiry_df = expiry_df[
        (expiry_df["strike"] >= lo) & (expiry_df["strike"] <= hi)
    ].copy()

    if expiry_df.empty:
        log.warning(
            "Options chain: no strikes in range %d–%d for expiry %s",
            lo, hi, expiry
        )
        return pd.DataFrame()

    # ── Step 4: Build symbol list from instruments master ─────────────────────
    # Format: "NFO:NIFTY2542922500CE"  ← exact string Kite wants
    symbol_map: dict[str, dict] = {}   # "NFO:SYMBOL" → {strike, type}
    for _, row in expiry_df.iterrows():
        sym = f"NFO:{row['tradingsymbol']}"
        symbol_map[sym] = {
            "strike": int(row["strike"]),
            "type":   row["instrument_type"],   # "CE" or "PE"
        }

    symbols = list(symbol_map.keys())
    log.info("Options chain: quoting %d symbols for expiry %s", len(symbols), expiry)

    # ── Step 5: Batch quote (max 500 per call) ────────────────────────────────
    quote_data: dict = {}
    for i in range(0, len(symbols), 500):
        batch = symbols[i : i + 500]
        try:
            result = kite.quote(batch)
            quote_data.update(result)
        except Exception as e:
            log.error("Batch quote failed (batch %d): %s", i // 500, e)
            # Continue — partial data is better than nothing

    if not quote_data:
        log.error("Options chain: quote() returned empty for expiry %s", expiry)
        return pd.DataFrame()

    # ── Step 6: Build records dict keyed by strike ────────────────────────────
    records: dict[int, dict] = {}

    for sym, meta in symbol_map.items():
        strike = meta["strike"]
        opt_t  = meta["type"]   # "CE" or "PE"
        q      = quote_data.get(sym, {})

        if strike not in records:
            records[strike] = {
                "strike":       strike,
                "ce_oi":        0,
                "ce_vol":       0,
                "ce_ltp":       0.0,
                "ce_iv":        0.0,
                "ce_oi_change": 0,
                "pe_oi":        0,
                "pe_vol":       0,
                "pe_ltp":       0.0,
                "pe_iv":        0.0,
                "pe_oi_change": 0,
            }

        p = "ce_" if opt_t == "CE" else "pe_"
        records[strike][f"{p}oi"]        = int(q.get("oi", 0))
        records[strike][f"{p}vol"]       = int(q.get("volume", 0))
        records[strike][f"{p}ltp"]       = float(q.get("last_price", 0.0))
        records[strike][f"{p}iv"]        = float(q.get("implied_volatility", 0.0))
        records[strike][f"{p}oi_change"] = int(q.get("oi_day_change", 0))

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records.values()).set_index("strike").sort_index()

    # ── Step 7: Compute % OI change (avoid division by zero) ─────────────────
    prev_ce = df["ce_oi"] - df["ce_oi_change"]
    prev_pe = df["pe_oi"] - df["pe_oi_change"]
    df["ce_pct_change"] = np.where(
        prev_ce > 0, df["ce_oi_change"] / prev_ce * 100, 0.0
    )
    df["pe_pct_change"] = np.where(
        prev_pe > 0, df["pe_oi_change"] / prev_pe * 100, 0.0
    )

    log.info(
        "Options chain: %d strikes fetched for expiry %s (ATM=%d)",
        len(df), expiry, atm
    )
    return df


@st.cache_data(ttl=TTL_OPTIONS, show_spinner=False)
def get_dual_expiry_chains(spot: float) -> dict:
    """
    Fetch both near and far expiry chains.
    Near = this week's Tuesday (OI wall / PCR read).
    Far  = next week's Tuesday (your trade legs).

    Returns:
      {
        "near": DataFrame, "far": DataFrame,
        "near_expiry": date, "far_expiry": date,
        "near_dte": int, "far_dte": int
      }
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


# ─── Nifty daily OHLCV ───────────────────────────────────────────────────────

@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_nifty_daily(days: int = 400) -> pd.DataFrame:
    """
    Daily OHLCV for Nifty 50 index.

    FIX: Index is timezone-normalized to naive UTC so Market Profile
    comparisons against pd.Timestamp don't crash with:
    "Invalid comparison between dtype=datetime64[us, tzoffset(None, 19800)] and Timestamp"

    Returns DataFrame with columns: open, high, low, close, volume
    Index: date (timezone-naive)
    """
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

        # Normalize datetime — remove timezone so comparisons work everywhere
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.set_index("date").sort_index()
        return df[["open", "high", "low", "close", "volume"]]

    except Exception as e:
        log.error("Nifty daily fetch failed: %s", e)
        return pd.DataFrame()


# ─── Top 10 stocks daily OHLCV ───────────────────────────────────────────────

@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_top10_daily(days: int = 400) -> dict[str, pd.DataFrame]:
    """
    Daily OHLCV for each of the top 10 Nifty 50 stocks.
    Returns {symbol: DataFrame} with timezone-naive index.
    """
    kite      = _get_kite()
    result    = {}
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
            if df.empty:
                result[symbol] = pd.DataFrame()
                continue
            # Timezone-normalize (same fix as Nifty daily)
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
            df = df.set_index("date").sort_index()
            result[symbol] = df[["open", "high", "low", "close", "volume"]]
        except Exception as e:
            log.warning("Stock fetch failed %s: %s", symbol, e)
            result[symbol] = pd.DataFrame()

    return result


# ─── India VIX ───────────────────────────────────────────────────────────────

INDIA_VIX_TOKEN = 264969   # NSE:INDIA VIX integer token (for historical_data)

@st.cache_data(ttl=TTL_PRICE, show_spinner=False)
def get_india_vix() -> float:
    """
    Live India VIX value.
    quote() must use the string "NSE:INDIA VIX" — not the token number.
    """
    kite = _get_kite()
    try:
        quote = kite.quote(["NSE:INDIA VIX"])

        if "NSE:INDIA VIX" in quote:
            return float(quote["NSE:INDIA VIX"]["last_price"])

        # Fallback by token string
        if str(INDIA_VIX_TOKEN) in quote:
            return float(quote[str(INDIA_VIX_TOKEN)]["last_price"])

        log.warning("VIX key not found. Keys returned: %s", list(quote.keys()))
        return 0.0

    except Exception as e:
        log.error("VIX fetch failed: %s", e)
        return 0.0


@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_vix_history(days: int = 365) -> pd.DataFrame:
    """
    Historical India VIX for IVP calculation.
    FIX: timezone-normalized index.
    """
    kite = _get_kite()
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
        if df.empty:
            return pd.DataFrame()

        # Timezone-normalize
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        return df.set_index("date").sort_index()

    except Exception as e:
        log.error("VIX history failed: %s", e)
        return pd.DataFrame()


# ─── Nifty 500 breadth (for Geometric Edge health gate) ──────────────────────

@st.cache_data(ttl=TTL_DAILY, show_spinner=False)
def get_nifty500_breadth() -> int:
    """
    Count of Nifty 500 stocks trading above their 200-day SMA.
    Computed once daily by GitHub Actions EOD job → saved to JSON.
    Dashboard reads from file — does NOT make live API calls here.
    """
    breadth_file = "data/parquet/market_health.json"
    if os.path.exists(breadth_file):
        try:
            with open(breadth_file) as f:
                data = json.load(f)
                return int(data.get("breadth_count", 0))
        except Exception as e:
            log.warning("market_health.json read failed: %s", e)
    return 0   # fallback if not yet computed today


# ─── Debug helper (call from any page during development) ────────────────────

def debug_instruments_sample(expiry: Optional[date] = None) -> None:
    """
    Call this from any Streamlit page to verify what Kite actually returns.

    Usage in 10_Options_Chain.py:
        from live_fetcher import debug_instruments_sample
        debug_instruments_sample()   # shows nearest expiry
    """
    try:
        import streamlit as st
    except ImportError:
        return

    instr = get_nfo_instruments()
    if instr.empty:
        st.error("instruments dump is empty — check Kite auth")
        return

    all_expiries = sorted(instr["expiry"].unique())
    st.write("**Available NIFTY expiries:**", all_expiries[:10])

    target = expiry or all_expiries[0]
    sample = instr[instr["expiry"] == target]["tradingsymbol"].head(10).tolist()
    st.write(f"**Sample symbols for {target}:**", sample)
    st.caption(
        "These are the exact strings Kite expects inside quote(). "
        "If they look correct, your options chain will work."
    )
