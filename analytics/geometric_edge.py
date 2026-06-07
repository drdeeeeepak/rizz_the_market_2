# analytics/geometric_edge.py
# Geometric Edge Scanner — Page 13
# Martin Luk methodology adapted for NSE India.
# 4 daily scans via GitHub Actions. Separate from options system.

import json
import os
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np
from analytics.base_strategy import BaseStrategy
from config import (
    GEO_PRICE_STRENGTH, GEO_VOL_MULT, GEO_ADR, GEO_EP_GAP,
    GEO_TIME_SCALERS, GEO_VOL_SMA_PERIOD, GEO_MAX_RESULTS, GEO_MIN_RR,
    GEO_MARKET_HEALTH_BULL, GEO_MARKET_HEALTH_SELECT,
    WATCHLIST_DIR, PARQUET_DIR,
)
log = logging.getLogger(__name__)


def _classify_segment(symbol: str) -> str:
    """
    Classify a symbol into its Nifty segment.
    In production, load from an instruments CSV.
    # TODO: replace hardcoded lists with data/nifty_segments.json once available.
    """
    nifty50 = {
        "HDFCBANK","RELIANCE","ICICIBANK","INFY","TCS",
        "KOTAKBANK","LT","BHARTIARTL","AXISBANK","ITC",
        "HINDUNILVR","WIPRO","POWERGRID","NTPC","ONGC",
        "MARUTI","TECHM","M&M","SUNPHARMA","BAJFINANCE",
    }
    nifty_next = {
        "TRENT","RVNL","HAL","MAZAGON","BEL","IRCTC",
        "ABBOTINDIA","PIIND","LTIM","MPHASIS",
    }
    if symbol in nifty50:    return "nifty50"
    if symbol in nifty_next: return "nifty_next"
    return "midcap"


class GeometricEdgeScanner(BaseStrategy):
    """
    Martin Luk strategy adapted for NSE India.
    Runs 4 times daily: 11am, 1:30pm, 3:15pm, EOD.
    Saves watchlists to JSON for Streamlit to read (no direct Kite calls from page).
    Scans run in all market phases; bear-phase results are watchlist-only.
    """

    SCAN_TIMES = ["11:00", "13:30", "15:15", "15:35"]

    # ─────────────────────────────────────────────────────────────────────────

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Pre-compute indicators. price_str uses prev_close to capture gap moves."""
        df["vol_sma20"]  = df["volume"].rolling(GEO_VOL_SMA_PERIOD).mean()
        df["adr_20"]     = (
            (df["high"] - df["low"]) / df["low"] * 100
        ).rolling(GEO_VOL_SMA_PERIOD).mean()
        df["price_str"]  = df["close"].pct_change()          # close vs prev close
        df["vol_mult"]   = df["volume"] / df["vol_sma20"]
        return df

    # ─────────────────────────────────────────────────────────────────────────

    def signals(self, df: pd.DataFrame) -> dict:
        """Not used directly — use scan() instead."""
        return {}

    # ─────────────────────────────────────────────────────────────────────────
    # Market health gate

    def market_health(self, nifty500_closes: pd.Series,
                      sma200s: pd.Series) -> dict:
        """
        Count Nifty 500 stocks above their 200-day SMA.
        Parameters: two Series indexed by symbol.
        """
        count = int((nifty500_closes > sma200s).sum())
        if count > GEO_MARKET_HEALTH_BULL:
            phase = "AGGR_BULL"
        elif count > GEO_MARKET_HEALTH_SELECT:
            phase = "SELECTIVE"
        else:
            phase = "BEAR"

        capital_alloc = {
            "AGGR_BULL":  {"large": 0.20, "mid": 0.50, "small": 0.30, "cash": 0.00},
            "SELECTIVE":  {"large": 0.60, "mid": 0.20, "small": 0.10, "cash": 0.10},
            "BEAR":       {"large": 0.10, "mid": 0.00, "small": 0.00, "cash": 0.90},
        }

        return {
            "count":        count,
            "phase":        phase,
            "run_scans":    True,   # always scan; bear results are watchlist-only
            "allocation":   capital_alloc[phase],
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Single stock scan

    def scan_stock(self, symbol: str, df: pd.DataFrame,
                   scan_label: str = "eod") -> dict | None:
        """
        Return scan result dict if stock passes all criteria, else None.
        scan_label drives pro-rata volume scaling for intraday scans.
        """
        if df.empty or len(df) < GEO_VOL_SMA_PERIOD + 2:
            return None

        df  = self.compute(df.copy())
        r   = df.iloc[-1]
        seg = _classify_segment(symbol)

        # ── Criteria ─────────────────────────────────────────────────────────
        # C1: Price strength (full-day move: prev close → today close, captures gaps)
        price_str_ok = r["price_str"] >= GEO_PRICE_STRENGTH[seg]

        # C2: Volume surge — pro-rata adjusted so intraday scans compare fairly
        scaler = GEO_TIME_SCALERS.get(scan_label, 1.0)
        vol_ok = (r["vol_mult"] / scaler) >= GEO_VOL_MULT[seg] if r["vol_sma20"] > 0 else False

        # C3: ADR filter — stock must have enough average daily range to be tradeable
        adr_ok = r["adr_20"] >= GEO_ADR[seg] if not pd.isna(r["adr_20"]) else False

        # C4: Circuit guard — pinned at high with negligible volume = likely upper circuit
        circuit_ok = not (r["close"] >= r["high"] * 0.999 and r["vol_mult"] < 0.3)

        if not (price_str_ok and vol_ok and adr_ok and circuit_ok):
            return None

        # ── Episodic Pivot (enhancer) ─────────────────────────────────────────
        prev_close = df["close"].iloc[-2]
        gap_pct    = (r["open"] - prev_close) / prev_close if prev_close > 0 else 0
        gap_held   = r["low"] > prev_close * 0.995
        ep_pivot   = gap_pct >= GEO_EP_GAP[seg] and gap_held

        # ── Risk-reward: price-anchored (rupees), stop = day low, target = 3× ADR ──
        risk_rupees   = r["close"] - r["low"]
        reward_rupees = r["close"] * r["adr_20"] / 100 * 3
        rr_ok = (reward_rupees / risk_rupees) >= GEO_MIN_RR if risk_rupees > 0 else False

        return {
            "symbol":        symbol,
            "segment":       seg,
            "price_str_pct": round(r["price_str"] * 100, 2),
            "vol_mult":      round(r["vol_mult"] / scaler, 1),  # normalised rate
            "adr_20":        round(r["adr_20"], 2),
            "gap_pct":       round(gap_pct * 100, 2),
            "ep_pivot":      ep_pivot,
            "rr_ok":         rr_ok,
            "ltp":           round(r["close"], 2),
            "scan_time":     datetime.now().strftime("%H:%M"),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Full universe scan

    def scan_universe(self, universe: dict[str, pd.DataFrame],
                      market_health: dict,
                      scan_label: str = "eod") -> list[dict]:
        """
        Scan all stocks in universe.
        Always runs — bear-phase results are flagged for watchlist-only display.
        In SELECTIVE phase, smallcap is excluded.
        Returns top GEO_MAX_RESULTS sorted by normalised volume multiple.
        """
        phase = market_health.get("phase", "AGGR_BULL")
        selective_ok = {"nifty50", "nifty_next", "midcap"}

        if phase == "BEAR":
            log.info("Market in BEAR phase — scanning for watchlist (no-trade) view.")

        results = []
        for symbol, df in universe.items():
            try:
                result = self.scan_stock(symbol, df, scan_label)
                if result:
                    if phase == "SELECTIVE" and result["segment"] not in selective_ok:
                        continue
                    result["bear_phase"] = (phase == "BEAR")
                    results.append(result)
            except Exception as e:
                log.warning("Scan failed %s: %s", symbol, e)

        results.sort(key=lambda x: x["vol_mult"], reverse=True)
        return results[:GEO_MAX_RESULTS]

    # ─────────────────────────────────────────────────────────────────────────
    # Conviction scoring

    def conviction_score(self, symbol: str,
                          watchlists: list[list[dict]]) -> int:
        """
        Count how many of the 4 daily scans the symbol appeared in.
        watchlists = [list_1100, list_1330, list_1515, list_eod]
        """
        return sum(
            1 for wl in watchlists
            if symbol in [s["symbol"] for s in wl]
        )

    def conviction_label(self, score: int, bookended: bool = False) -> str:
        if score == 4:    return "HIGHEST"
        if bookended:     return "HIGH_BOOKENDED"
        if score == 3:    return "MODERATE"
        if score == 2:    return "SPECULATIVE"
        if score == 1:    return "LOW"
        return "FAILED"

    def position_size_pct(self, score: int, ep_pivot: bool,
                           bookended: bool = False) -> float:
        """Recommended position size as % of capital (pilot entry). 0 in bear phase."""
        if score == 4 and ep_pivot: return 1.00
        if score == 4:              return 0.75
        if bookended:               return 0.50
        if score == 3:              return 0.35
        if score == 2:              return 0.20
        if score == 1:              return 0.10
        return 0.00

    # ─────────────────────────────────────────────────────────────────────────
    # Persistence (GitHub Actions writes, Streamlit reads)

    def save_watchlist(self, results: list[dict], scan_label: str) -> str:
        """
        Save scan results to JSON file.
        scan_label: "1100", "1330", "1515", "eod"
        """
        os.makedirs(WATCHLIST_DIR, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        path  = f"{WATCHLIST_DIR}/{today}_{scan_label}.json"
        with open(path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        log.info("Saved %d results to %s", len(results), path)
        return path

    def load_all_watchlists(self) -> dict[str, list]:
        """
        Load today's 4 watchlists for Streamlit display.
        Returns {"1100": [...], "1330": [...], "1515": [...], "eod": [...]}
        """
        today = datetime.now().strftime("%Y-%m-%d")
        result = {}
        for label in ("1100", "1330", "1515", "eod"):
            path = f"{WATCHLIST_DIR}/{today}_{label}.json"
            if os.path.exists(path):
                with open(path) as f:
                    result[label] = json.load(f)
            else:
                result[label] = []
        return result

    def build_eod_summary(self, watchlists: dict[str, list]) -> list[dict]:
        """
        Merge all 4 scans, compute conviction scores, sort by score then vol_mult.
        """
        all_symbols = set()
        for wl in watchlists.values():
            for s in wl:
                all_symbols.add(s["symbol"])

        summary = []
        wl_lists = [watchlists.get(k, []) for k in ("1100", "1330", "1515", "eod")]

        for sym in all_symbols:
            score     = self.conviction_score(sym, wl_lists)
            bookended = (
                any(s["symbol"] == sym for s in watchlists.get("1100", [])) and
                any(s["symbol"] == sym for s in watchlists.get("eod",  []))
            )
            latest = next(
                (s for wl in reversed(wl_lists)
                 for s in wl if s["symbol"] == sym),
                {}
            )
            if not latest:
                continue

            ep = latest.get("ep_pivot", False)
            bear = latest.get("bear_phase", False)
            summary.append({
                **latest,
                "conviction_score": score,
                "bookended":        bookended,
                "conviction_label": self.conviction_label(score, bookended),
                "size_pct":         0.0 if bear else self.position_size_pct(score, ep, bookended),
            })

        summary.sort(key=lambda x: (x["conviction_score"], x["vol_mult"]), reverse=True)
        return summary
