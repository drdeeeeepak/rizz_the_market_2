# analytics/constituent_ema.py — NEW (April 2026)
# Pages 3 + 4: Heavyweight Constituent EMA Framework
#
# Exact extrapolation of Pages 1+2 new cluster framework
# applied to each of the top 10 Nifty 50 stocks on their own daily candles.
#
# Each stock gets: cluster regime, moat count, momentum score, canary level.
# Outputs are aggregated into group signals (banking, heavyweight, IT, breadth).

from analytics.ema import EMAEngine

# ── Stock groupings (from Pages 1-4 doc) ──────────────────────────────────────
BANKING_GROUP    = ["HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK"]
HEAVYWEIGHT_GROUP = ["HDFCBANK", "RELIANCE", "ICICIBANK"]
IT_GROUP         = ["INFY", "TCS"]
TOP_10           = ["HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "BHARTIARTL",
                    "TCS", "LT", "AXISBANK", "KOTAKBANK", "ITC"]

# Bear regimes for signal detection
BEAR_REGIMES     = {"STRONG_BEAR", "BEAR_COMPRESSED", "INSIDE_BEAR"}
BULL_REGIMES     = {"STRONG_BULL", "BULL_COMPRESSED"}
GOOD_REGIMES     = {"STRONG_BULL", "BULL_COMPRESSED", "INSIDE_BULL"}


class ConstituentEMAEngine:
    """
    Runs the new EMA cluster framework (Pages 1+2) on each top-10 stock.
    Aggregates into group signals for Pages 3+4 display.
    """

    def __init__(self):
        self._ema_engine = EMAEngine()

    def signals(self, stock_dfs: dict) -> dict:
        """
        Main entry point.
        stock_dfs: {symbol: pd.DataFrame with OHLCV daily data}
        Returns full constituent signals dict.
        """
        # Per-stock cluster signals
        per_stock = {}
        for sym in TOP_10:
            df = stock_dfs.get(sym)
            if df is not None and not df.empty:
                per_stock[sym] = self._ema_engine.stock_cluster_signals(df, sym)
            else:
                per_stock[sym] = self._ema_engine._empty_stock_signals(sym)

        # Group aggregations
        banking_signals    = self._banking_signals(per_stock)
        heavyweight_signals = self._heavyweight_signals(per_stock)
        it_signals         = self._it_signals(per_stock)
        breadth            = self._breadth_signals(per_stock)
        canary_signals     = self._canary_signals(per_stock)

        # Named IC signals from doc
        named = self._named_signals(per_stock, breadth)

        return {
            "constituent_per_stock":   per_stock,
            "constituent_banking":     banking_signals,
            "constituent_heavyweight": heavyweight_signals,
            "constituent_it":          it_signals,
            "constituent_breadth":     breadth,
            "constituent_canary":      canary_signals,
            **named,
        }

    # ── Per-group helpers ─────────────────────────────────────────────────────

    def _banking_signals(self, per: dict) -> dict:
        stocks = {s: per[s] for s in BANKING_GROUP if s in per}
        regimes = [d["regime"] for d in stocks.values()]
        moats   = [d["put_moats"] for d in stocks.values()]
        mom     = [d["mom_state"] for d in stocks.values()]
        return {
            "regimes":       regimes,
            "avg_put_moats": round(sum(moats)/len(moats), 1) if moats else 0,
            "all_bullish":   all(r in BULL_REGIMES for r in regimes),
            "any_bear":      any(r in BEAR_REGIMES for r in regimes),
            "count_bear":    sum(1 for r in regimes if r in BEAR_REGIMES),
            "weakening":     self._is_weakening(stocks),
        }

    def _heavyweight_signals(self, per: dict) -> dict:
        stocks = {s: per[s] for s in HEAVYWEIGHT_GROUP if s in per}
        regimes = [d["regime"] for d in stocks.values()]
        return {
            "regimes":      regimes,
            "count_bear":   sum(1 for r in regimes if r in BEAR_REGIMES),
            "any_collapse": sum(1 for r in regimes if r in BEAR_REGIMES) >= 2,
        }

    def _it_signals(self, per: dict) -> dict:
        stocks = {s: per[s] for s in IT_GROUP if s in per}
        regimes = [d["regime"] for d in stocks.values()]
        mom     = [d["mom_state"] for d in stocks.values()]
        return {
            "regimes":   regimes,
            "both_bear": all(r in BEAR_REGIMES for r in regimes),
            "mom_states": mom,
        }

    def _breadth_signals(self, per: dict) -> dict:
        """
        Breadth Moat Score: % of top 10 stocks with 2+ downside moats.
        """
        total = len(per)
        if total == 0:
            return {"score_pct": 50, "count_2plus": 5, "label": "ADEQUATE"}
        count_2plus = sum(1 for d in per.values() if d["put_moats"] >= 2)
        pct = round(count_2plus / total * 100)
        if   pct >= 80: label = "BROAD_HEALTH"
        elif pct >= 60: label = "ADEQUATE"
        elif pct >= 40: label = "THINNING"
        else:           label = "COLLAPSE"
        return {"score_pct": pct, "count_2plus": count_2plus, "label": label}

    def _canary_signals(self, per: dict) -> dict:
        """Group-level Canary aggregation from per-stock canary levels."""
        banking_canary = max(
            (per.get(s, {}).get("canary_level", 0) for s in BANKING_GROUP), default=0
        )
        heavy_canary = max(
            (per.get(s, {}).get("canary_level", 0) for s in HEAVYWEIGHT_GROUP), default=0
        )
        broad_count = sum(1 for d in per.values() if d.get("canary_level", 0) >= 3)
        return {
            "banking_canary_level":     banking_canary,
            "heavyweight_canary_level": heavy_canary,
            "broad_canary_count":       broad_count,
            # Broad canary fires when 4+ stocks at Canary Day 3 or above
            "broad_canary_active":      broad_count >= 4,
        }

    def _is_weakening(self, stocks: dict) -> bool:
        """
        BANKING_SLOPE_WEAKENING: 2+ banking stocks transitioning from
        Bull Compressed to Inside Bull (regime weakening).
        Detected as: regime is INSIDE_BULL with momentum state MODERATE_DOWN or STRONG_DOWN.
        """
        count = sum(
            1 for d in stocks.values()
            if d["regime"] == "INSIDE_BULL"
            and d["mom_state"] in ("MODERATE_DOWN", "STRONG_DOWN")
        )
        return count >= 2

    # ── Named IC signals from doc ─────────────────────────────────────────────

    def _named_signals(self, per: dict, breadth: dict) -> dict:
        """
        Eight named signals with PE/CE modifiers per Pages 3+4 doc.
        Returns dict ready to merge into main signals.
        """
        banking    = {s: per[s] for s in BANKING_GROUP if s in per}
        heavy      = {s: per[s] for s in HEAVYWEIGHT_GROUP if s in per}
        it_stocks  = {s: per[s] for s in IT_GROUP if s in per}

        # Nifty regime (from Nifty signals — approximate from breadth)
        nifty_bullish = breadth["score_pct"] >= 60

        # BANKING_ALL_BULLISH: all 4 banking in Strong Bull or Bull Compressed
        banking_all_bullish = all(
            d["regime"] in BULL_REGIMES for d in banking.values()
        )

        # BANKING_SLOPE_WEAKENING: 2+ banks INSIDE_BULL + downward momentum
        banking_weakening = self._is_weakening(banking)

        # BANKING_DAILY_COLLAPSE: 3 of 4 banks in Strong Bear or Bear Compressed
        banking_collapse = sum(
            1 for d in banking.values() if d["regime"] in {"STRONG_BEAR", "BEAR_COMPRESSED"}
        ) >= 3

        # HEAVYWEIGHT_COLLAPSE: 2 of 3 heavyweights in Bear Compressed or Strong Bear
        heavy_collapse = sum(
            1 for d in heavy.values() if d["regime"] in {"STRONG_BEAR", "BEAR_COMPRESSED"}
        ) >= 2

        # INDEX_MASKING_WEAKNESS: Nifty bullish but 3+ top 10 in Inside Bear or worse
        masking_count = sum(1 for d in per.values() if d["regime"] in BEAR_REGIMES)
        index_masking = nifty_bullish and masking_count >= 3

        # HEAVYWEIGHT_LEADING_DOWN: HDFC or Reliance in Inside Bear or worse
        heavy_leading_down = any(
            per.get(s, {}).get("regime") in BEAR_REGIMES
            for s in ["HDFCBANK", "RELIANCE"]
        )

        # IT_SECTOR_DRAG: Infosys and TCS both Bear Compressed or Strong Bear
        it_drag = all(
            d["regime"] in {"STRONG_BEAR", "BEAR_COMPRESSED"}
            for d in it_stocks.values()
        )

        # SECTOR_ROTATION: 2+ banks Strong Bull AND 1+ IT stocks Strong Bear
        banks_bull = sum(1 for d in banking.values() if d["regime"] == "STRONG_BULL")
        it_bear    = sum(1 for d in it_stocks.values() if d["regime"] in BEAR_REGIMES)
        sector_rotation = banks_bull >= 2 and it_bear >= 1

        # Distance modifiers (independent — do not stack)
        pe_mod  = 0
        ce_mod  = 0

        # Only the most severe active signal drives the modifier
        if banking_collapse:
            pe_mod = 9999  # KILL SWITCH — handled separately
            ce_mod = 9999
        elif heavy_collapse or index_masking:
            pe_mod = 300
        elif banking_weakening or heavy_leading_down:
            pe_mod = 200
        elif banking_all_bullish:
            pe_mod = -200  # bonus

        if it_drag:
            ce_mod = max(ce_mod, 100)

        # Breadth modifier (independent from named signals)
        breadth_pe_mod = {"BROAD_HEALTH": -100, "ADEQUATE": 0,
                          "THINNING": 200, "COLLAPSE": 400
                          }.get(breadth["label"], 0)

        return {
            # Named signal flags
            "BANKING_ALL_BULLISH":      banking_all_bullish,
            "BANKING_SLOPE_WEAKENING":  banking_weakening,
            "BANKING_DAILY_COLLAPSE":   banking_collapse,
            "HEAVYWEIGHT_COLLAPSE":     heavy_collapse,
            "INDEX_MASKING_WEAKNESS":   index_masking,
            "HEAVYWEIGHT_LEADING_DOWN": heavy_leading_down,
            "IT_SECTOR_DRAG":           it_drag,
            "SECTOR_ROTATION_DETECTED": sector_rotation,
            # Modifiers
            "constituent_pe_mod":       pe_mod,
            "constituent_ce_mod":       ce_mod,
            "constituent_breadth_pe_mod": breadth_pe_mod,
            # Kill switch
            "BANKING_DAILY_COLLAPSE_KILL": banking_collapse,
        }
