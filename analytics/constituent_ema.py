# analytics/constituent_ema.py — v2 (22 April 2026)
# Pages 3 + 4: Heavyweight Constituent EMA Framework
#
# CHANGES FROM v1:
#   - Named signal modifiers recalibrated (leaner — sized for new 1.5x ATR base)
#   - Breadth moat score modifiers recalibrated
#   - Combined modifier cap: +200 pts PE, +100 pts CE maximum
#   - Per-stock canary upgraded to three-source system (matching Page 2)
#   - Source 3 uses each stock's OWN Tuesday close and Tuesday ATR14
#   - BROAD_CANARY modifier updated to +150 pts (was +200)
#   - BROAD_CANARY lives on Page 4 ONLY — not surfaced on Page 3
#
# Aggregation philosophy:
#   Named signals: most severe active signal drives PE modifier — no stacking
#   IT drag: independent CE modifier — does not stack with other CE signals
#   Breadth: independent PE modifier from named signals
#   Cap: total constituent modifier capped at +200 PE, +100 CE

import json
import os
import logging
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import numpy as np

from analytics.ema import EMAEngine

log = logging.getLogger(__name__)

# ── Stock groupings ────────────────────────────────────────────────────────────
BANKING_GROUP     = ["HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK"]
HEAVYWEIGHT_GROUP = ["HDFCBANK", "RELIANCE", "ICICIBANK"]
IT_GROUP          = ["INFY", "TCS"]
TOP_10            = ["HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "BHARTIARTL",
                     "TCS", "LT", "AXISBANK", "KOTAKBANK", "ITC"]

# Regime buckets
BEAR_REGIMES = {"STRONG_BEAR", "BEAR_COMPRESSED", "INSIDE_BEAR"}
BULL_REGIMES = {"STRONG_BULL", "BULL_COMPRESSED"}

# ── New modifier values (recalibrated for 1.5x ATR base) ─────────────────────
# Named signal PE modifiers (most severe wins — no stacking)
MOD_BANKING_BULLISH    = -100   # bonus — PE can be tighter
MOD_SLOPE_WEAKENING    = +100
MOD_HEAVY_COLLAPSE     = +150
MOD_INDEX_MASKING      = +150
MOD_HEAVY_LEADING_DOWN = +100
MOD_IT_DRAG_CE         = +50    # CE only — independent
MOD_BROAD_CANARY_PE    = +150   # from Page 4 canary aggregation

# Breadth moat score PE modifiers (independent from named signals)
BREADTH_MOD = {
    "BROAD_HEALTH": -50,
    "ADEQUATE":       0,
    "THINNING":    +100,
    "COLLAPSE":    +200,
}

# Combined modifier caps
PE_MOD_CAP = +200
CE_MOD_CAP = +100

# ── Canary source thresholds (matching Page 2 new system) ────────────────────
# Source 1 — EMA3 vs EMA8 gap as % of ATR
SRC1_THRESHOLDS = [
    (15.0, 0),   # gap > 15% ATR  → Day 0
    (5.0,  1),   # gap 5–15%      → Day 1
    (0.0,  2),   # gap < 5%       → Day 2
    # EMA3 below EMA8 → Day 3 (handled separately)
    # EMA8 within 30pts of EMA16 → Day 4 (handled separately)
]

# Source 2 — Momentum acceleration (3-day rolling, % of ATR)
SRC2_THRESHOLDS = [
    ( 5.0, 0),   # accel > +5%    → Day 0
    (-5.0, 1),   # accel -5 to +5 → Day 1 (mild decel)
    (-10.0,2),   # -5 to -10%     → Day 2
    (-20.0,3),   # -10 to -20%    → Day 3
    # beyond -20% OR state flipped → Day 4
]

# Source 3 — Spot distance from Tuesday close (% of Tuesday ATR)
# Combined with Factor B (2-day return direction)
# See _source3_level() for full logic

# ── Tuesday anchor storage ────────────────────────────────────────────────────
ANCHOR_FILE = Path("data/tuesday_anchors.json")


def _load_anchors() -> dict:
    if ANCHOR_FILE.exists():
        try:
            return json.loads(ANCHOR_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_anchors(anchors: dict):
    ANCHOR_FILE.parent.mkdir(exist_ok=True)
    ANCHOR_FILE.write_text(json.dumps(anchors, indent=2))


class ConstituentEMAEngine:
    """
    Runs the new EMA cluster framework (Pages 1+2) on each top-10 stock.
    Aggregates into group signals for Pages 3+4 display.
    Three-source canary per stock (matching Page 2 architecture).
    """

    def __init__(self):
        self._ema_engine = EMAEngine()
        self._anchors    = _load_anchors()

    # ── Main entry point ──────────────────────────────────────────────────────

    def signals(self, stock_dfs: dict) -> dict:
        """
        stock_dfs: {symbol: pd.DataFrame with OHLCV daily data}
        Returns full constituent signals dict.
        """
        # Update Tuesday anchors if today is Tuesday
        if date.today().weekday() == 1:   # Monday=0, Tuesday=1
            self._update_tuesday_anchors(stock_dfs)

        # Per-stock cluster signals + three-source canary
        per_stock = {}
        for sym in TOP_10:
            df = stock_dfs.get(sym)
            if df is not None and not df.empty:
                per_stock[sym] = self._stock_signals(df, sym)
            else:
                per_stock[sym] = self._empty_stock_signals(sym)

        # Group aggregations
        banking_sig    = self._banking_signals(per_stock)
        heavyweight_sig = self._heavyweight_signals(per_stock)
        it_sig         = self._it_signals(per_stock)
        breadth        = self._breadth_signals(per_stock)
        canary_sig     = self._canary_signals(per_stock)

        # Named IC signals and modifiers
        named = self._named_signals(per_stock, breadth)

        return {
            "constituent_per_stock":   per_stock,
            "constituent_banking":     banking_sig,
            "constituent_heavyweight": heavyweight_sig,
            "constituent_it":          it_sig,
            "constituent_breadth":     breadth,
            "constituent_canary":      canary_sig,
            **named,
        }

    # ── Per-stock full signal computation ─────────────────────────────────────

    def _stock_signals(self, df: pd.DataFrame, symbol: str) -> dict:
        """
        Full signal computation for one stock.
        Returns cluster regime, moat count, momentum, and three-source canary.
        """
        try:
            base = self._ema_engine.stock_cluster_signals(df, symbol)

            # Three-source canary
            canary = self._three_source_canary(df, symbol, base)

            return {
                **base,
                "canary_level":     canary["level"],
                "canary_pe_level":  canary["pe_level"],
                "canary_ce_level":  canary["ce_level"],
                "canary_src1_pe":   canary["src1_pe"],
                "canary_src1_ce":   canary["src1_ce"],
                "canary_src2_pe":   canary["src2_pe"],
                "canary_src2_ce":   canary["src2_ce"],
                "canary_src3_pe":   canary["src3_pe"],
                "canary_src3_ce":   canary["src3_ce"],
                "canary_driver":    canary["driver"],
            }
        except Exception as e:
            log.warning("Stock signal failed %s: %s", symbol, e)
            return self._empty_stock_signals(symbol)

    # ── Three-source canary per stock ─────────────────────────────────────────

    def _three_source_canary(self, df: pd.DataFrame, symbol: str, base: dict) -> dict:
        """
        Three-source canary applied to one stock.
        PE and CE canary computed independently.
        Overall level = max of PE and CE.
        """
        atr = base.get("atr", 200.0)
        if atr == 0:
            atr = 200.0

        # ── Source 1: EMA3 vs EMA8 proximity ─────────────────────────────────
        try:
            df_c = df.copy()
            df_c["ema3"] = df_c["close"].ewm(span=3, adjust=False).mean()
            df_c["ema8"] = df_c["close"].ewm(span=8, adjust=False).mean()
            df_c["ema16"]= df_c["close"].ewm(span=16, adjust=False).mean()
            r = df_c.iloc[-1]
            e3, e8, e16 = float(r["ema3"]), float(r["ema8"]), float(r["ema16"])
            gap_pct = abs(e3 - e8) / atr * 100

            # PE side (bearish deterioration)
            if e8 < e16 and abs(e8 - e16) < 30:
                src1_pe = 4
            elif e8 < e16:
                src1_pe = 3
            elif e3 < e8:
                src1_pe = 2 if gap_pct < 5 else 1
            elif gap_pct < 5:
                src1_pe = 2
            elif gap_pct < 15:
                src1_pe = 1
            else:
                src1_pe = 0

            # CE side (bullish deterioration — EMAs stacking upward too fast)
            if e8 > e16 and abs(e8 - e16) < 30:
                src1_ce = 4
            elif e8 > e16 and e3 > e8:
                src1_ce = 3
            elif e3 > e8:
                src1_ce = 2 if gap_pct < 5 else 1
            elif gap_pct < 5:
                src1_ce = 2
            elif gap_pct < 15:
                src1_ce = 1
            else:
                src1_ce = 0
        except Exception:
            src1_pe = src1_ce = 0

        # ── Source 2: Momentum acceleration (3-day rolling) ───────────────────
        try:
            if len(df_c) >= 5:
                score_today = self._mom_score(df_c, atr, offset=0)
                score_3days = self._mom_score(df_c, atr, offset=3)
                accel = score_today - score_3days   # negative = decelerating

                src2_pe = self._src2_level(accel, base.get("mom_state", "FLAT"), pe_side=True)
                src2_ce = self._src2_level(accel, base.get("mom_state", "FLAT"), pe_side=False)
            else:
                src2_pe = src2_ce = 0
        except Exception:
            src2_pe = src2_ce = 0

        # ── Source 3: Drift from Tuesday close ────────────────────────────────
        try:
            anchor = self._anchors.get(symbol, {})
            tue_close = anchor.get("close", 0.0)
            tue_atr   = anchor.get("atr",   atr)
            if tue_close > 0 and tue_atr > 0:
                spot_today = float(df.iloc[-1]["close"])
                spot_2d    = float(df.iloc[-3]["close"]) if len(df) >= 3 else spot_today
                src3_pe, src3_ce = self._source3_level(
                    spot_today, spot_2d, tue_close, tue_atr, atr
                )
            else:
                src3_pe = src3_ce = 0
        except Exception:
            src3_pe = src3_ce = 0

        # ── Combine per side ──────────────────────────────────────────────────
        pe_level = max(src1_pe, src2_pe, src3_pe)
        ce_level = max(src1_ce, src2_ce, src3_ce)
        overall  = max(pe_level, ce_level)

        # Driving source
        driver_map = {src1_pe: "Source 1", src2_pe: "Source 2", src3_pe: "Source 3"}
        driver = driver_map.get(pe_level, "Source 1") if pe_level >= ce_level \
                 else {src1_ce: "Source 1", src2_ce: "Source 2", src3_ce: "Source 3"}.get(ce_level, "Source 1")

        return {
            "level":    overall,
            "pe_level": pe_level,
            "ce_level": ce_level,
            "src1_pe":  src1_pe,
            "src1_ce":  src1_ce,
            "src2_pe":  src2_pe,
            "src2_ce":  src2_ce,
            "src3_pe":  src3_pe,
            "src3_ce":  src3_ce,
            "driver":   driver,
        }

    def _mom_score(self, df: pd.DataFrame, atr: float, offset: int = 0) -> float:
        """Momentum score at a given offset from the end of df."""
        if len(df) < offset + 4:
            return 0.0
        idx = -(1 + offset)
        idx4 = -(4 + offset)
        e3 = df["ema3"].iloc[idx]
        e3_4 = df["ema3"].iloc[idx4]
        e8 = df["ema8"].iloc[idx]
        e8_4 = df["ema8"].iloc[idx4]
        slope3 = (e3 - e3_4) / 3
        slope8 = (e8 - e8_4) / 3
        return (slope3 / atr * 100) * 0.6 + (slope8 / atr * 100) * 0.4

    def _src2_level(self, accel: float, mom_state: str, pe_side: bool) -> int:
        """
        Convert momentum acceleration to canary day level.
        pe_side=True = deterioration toward put, False = toward call.
        Negative accel = decelerating (bad for pe_side when market was bullish).
        """
        # Only flag if deceleration is toward the relevant side
        if pe_side:
            # PE threatened when momentum decelerates (was bullish, now slowing)
            # or when momentum strongly negative
            if mom_state in ("STRONG_DOWN", "MODERATE_DOWN") or accel < -20:
                return 4 if accel < -20 else 3
            if accel < -10:
                return 2
            if accel < -5:
                return 1
            return 0
        else:
            # CE threatened when positive momentum decelerates (was bullish, now slowing)
            if mom_state in ("STRONG_UP", "MODERATE_UP") and accel < -10:
                return 3
            if mom_state == "STRONG_UP" and accel < -5:
                return 2
            if accel < -5 and mom_state not in ("STRONG_DOWN", "MODERATE_DOWN"):
                return 1
            return 0

    def _source3_level(self, spot: float, spot_2d: float,
                       tue_close: float, tue_atr: float,
                       live_atr: float) -> tuple:
        """
        Source 3: Two-factor drift from Tuesday close.
        Factor A: Distance from Tuesday close as % of Tuesday ATR.
        Factor B: 2-day return direction vs original direction.
        ATR expansion modifier: live_atr / tue_atr ratio.
        Returns (pe_level, ce_level).
        """
        move = spot - tue_close
        dist_pct = abs(move) / tue_atr * 100   # Factor A

        # Factor B: is price returning toward Tuesday close?
        two_day_move = spot - spot_2d
        returning = (move > 0 and two_day_move < 0) or (move < 0 and two_day_move > 0)

        # ATR expansion modifier
        atr_ratio = live_atr / tue_atr if tue_atr > 0 else 1.0
        expand_upgrade = 0
        if atr_ratio > 1.25 and not returning:
            expand_upgrade = 1
        elif atr_ratio > 1.10 and not returning:
            expand_upgrade = 0   # half level — we round down for conservatism

        # Base level from Factor A + Factor B combination
        if dist_pct < 20:
            base = 0
        elif dist_pct < 40:
            base = 0 if returning else 1
        elif dist_pct < 60:
            base = 1 if returning else 2
        elif dist_pct < 80:
            base = 2 if returning else 3
        else:
            base = 2 if returning else 4

        level = min(4, base + expand_upgrade)

        # Direction: positive move = CE threatened, negative = PE threatened
        if move > 0:
            return 0, level   # moving up = CE canary
        else:
            return level, 0   # moving down = PE canary

    # ── Tuesday anchor management ─────────────────────────────────────────────

    def _update_tuesday_anchors(self, stock_dfs: dict):
        """Called when today is Tuesday. Saves close and ATR14 for each stock."""
        anchors = {}
        for sym in TOP_10:
            df = stock_dfs.get(sym)
            if df is None or df.empty or len(df) < 15:
                continue
            try:
                # Compute ATR14
                high  = df["high"].values
                low   = df["low"].values
                close = df["close"].values
                tr    = [max(high[i]-low[i],
                             abs(high[i]-close[i-1]),
                             abs(low[i]-close[i-1]))
                         for i in range(1, len(df))]
                atr14 = float(np.mean(tr[-14:])) if len(tr) >= 14 else float(np.mean(tr))
                anchors[sym] = {
                    "close":    float(df["close"].iloc[-1]),
                    "atr":      round(atr14, 1),
                    "date":     str(date.today()),
                }
            except Exception as e:
                log.warning("Anchor update failed %s: %s", sym, e)

        if anchors:
            self._anchors = anchors
            _save_anchors(anchors)
            log.info("Tuesday anchors updated for %d stocks", len(anchors))

    # ── Group-level aggregations ──────────────────────────────────────────────

    def _banking_signals(self, per: dict) -> dict:
        stocks = {s: per[s] for s in BANKING_GROUP if s in per}
        regimes = [d["regime"] for d in stocks.values()]
        moats   = [d["put_moats"] for d in stocks.values()]
        return {
            "regimes":       regimes,
            "avg_put_moats": round(sum(moats) / len(moats), 1) if moats else 0,
            "all_bullish":   all(r in BULL_REGIMES for r in regimes),
            "any_bear":      any(r in BEAR_REGIMES for r in regimes),
            "count_bear":    sum(1 for r in regimes if r in BEAR_REGIMES),
            "weakening":     self._is_weakening(stocks),
        }

    def _heavyweight_signals(self, per: dict) -> dict:
        stocks  = {s: per[s] for s in HEAVYWEIGHT_GROUP if s in per}
        regimes = [d["regime"] for d in stocks.values()]
        return {
            "regimes":      regimes,
            "count_bear":   sum(1 for r in regimes if r in BEAR_REGIMES),
            "any_collapse": sum(1 for r in regimes if r in BEAR_REGIMES) >= 2,
        }

    def _it_signals(self, per: dict) -> dict:
        stocks  = {s: per[s] for s in IT_GROUP if s in per}
        regimes = [d["regime"] for d in stocks.values()]
        mom     = [d["mom_state"] for d in stocks.values()]
        return {
            "regimes":    regimes,
            "both_bear":  all(r in BEAR_REGIMES for r in regimes),
            "mom_states": mom,
        }

    def _breadth_signals(self, per: dict) -> dict:
        """% of top 10 stocks with 2+ put-side moats."""
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
        """
        Group-level canary aggregation from per-stock three-source canary levels.
        BROAD_CANARY fires when 4+ stocks at Day 3 or above.
        Lives on Page 4 ONLY — not surfaced on Page 3.
        """
        banking_canary = max(
            (per.get(s, {}).get("canary_level", 0) for s in BANKING_GROUP), default=0
        )
        heavy_canary = max(
            (per.get(s, {}).get("canary_level", 0) for s in HEAVYWEIGHT_GROUP), default=0
        )
        broad_count = sum(1 for d in per.values() if d.get("canary_level", 0) >= 3)
        broad_active = broad_count >= 4

        # Worst stock per group for display
        worst_banking = max(BANKING_GROUP,
            key=lambda s: per.get(s, {}).get("canary_level", 0))
        worst_heavy = max(HEAVYWEIGHT_GROUP,
            key=lambda s: per.get(s, {}).get("canary_level", 0))

        return {
            "banking_canary_level":     banking_canary,
            "heavyweight_canary_level": heavy_canary,
            "broad_canary_count":       broad_count,
            "broad_canary_active":      broad_active,
            "broad_canary_pe_mod":      MOD_BROAD_CANARY_PE if broad_active else 0,
            "worst_banking_stock":      worst_banking,
            "worst_heavy_stock":        worst_heavy,
        }

    # ── Named IC signals ──────────────────────────────────────────────────────

    def _named_signals(self, per: dict, breadth: dict) -> dict:
        """
        Named signals with recalibrated PE/CE modifiers.
        Most severe named signal drives PE modifier — no stacking.
        IT drag independent CE modifier.
        Combined cap applied at end.
        """
        banking   = {s: per[s] for s in BANKING_GROUP    if s in per}
        heavy     = {s: per[s] for s in HEAVYWEIGHT_GROUP if s in per}
        it_stocks = {s: per[s] for s in IT_GROUP          if s in per}

        nifty_bullish = breadth["score_pct"] >= 60

        # ── Named signal detection ────────────────────────────────────────────
        banking_all_bullish = all(
            d["regime"] in BULL_REGIMES for d in banking.values()
        )
        banking_weakening = self._is_weakening(banking)
        banking_collapse  = sum(
            1 for d in banking.values()
            if d["regime"] in {"STRONG_BEAR", "BEAR_COMPRESSED"}
        ) >= 3
        heavy_collapse = sum(
            1 for d in heavy.values()
            if d["regime"] in {"STRONG_BEAR", "BEAR_COMPRESSED"}
        ) >= 2
        masking_count  = sum(1 for d in per.values() if d["regime"] in BEAR_REGIMES)
        index_masking  = nifty_bullish and masking_count >= 3
        heavy_leading_down = any(
            per.get(s, {}).get("regime") in BEAR_REGIMES
            for s in ["HDFCBANK", "RELIANCE"]
        )
        it_drag = all(
            d["regime"] in {"STRONG_BEAR", "BEAR_COMPRESSED"}
            for d in it_stocks.values()
        )
        banks_bull = sum(1 for d in banking.values() if d["regime"] == "STRONG_BULL")
        it_bear    = sum(1 for d in it_stocks.values() if d["regime"] in BEAR_REGIMES)
        sector_rotation = banks_bull >= 2 and it_bear >= 1

        # ── PE modifier — most severe active signal wins ──────────────────────
        pe_mod = 0
        if banking_collapse:
            pe_mod = 9999   # KILL SWITCH
        elif heavy_collapse or index_masking:
            pe_mod = MOD_HEAVY_COLLAPSE      # +150
        elif banking_weakening or heavy_leading_down:
            pe_mod = MOD_HEAVY_LEADING_DOWN  # +100
        elif banking_all_bullish:
            pe_mod = MOD_BANKING_BULLISH     # -100

        # ── CE modifier — IT drag independent ────────────────────────────────
        ce_mod = MOD_IT_DRAG_CE if it_drag else 0   # +50 or 0

        # ── Breadth modifier — independent from named signals ─────────────────
        breadth_pe_mod = BREADTH_MOD.get(breadth["label"], 0)

        # ── Apply cap (kill switch bypasses cap) ──────────────────────────────
        if pe_mod != 9999:
            total_pe = pe_mod + breadth_pe_mod
            total_pe = min(total_pe, PE_MOD_CAP)
            total_pe = max(total_pe, -100)   # floor on bonus side
        else:
            total_pe = pe_mod

        total_ce = min(ce_mod, CE_MOD_CAP)

        return {
            # Signal flags
            "BANKING_ALL_BULLISH":      banking_all_bullish,
            "BANKING_SLOPE_WEAKENING":  banking_weakening,
            "BANKING_DAILY_COLLAPSE":   banking_collapse,
            "HEAVYWEIGHT_COLLAPSE":     heavy_collapse,
            "INDEX_MASKING_WEAKNESS":   index_masking,
            "HEAVYWEIGHT_LEADING_DOWN": heavy_leading_down,
            "IT_SECTOR_DRAG":           it_drag,
            "SECTOR_ROTATION_DETECTED": sector_rotation,
            # Raw modifiers (before cap)
            "constituent_pe_mod_named":   pe_mod,
            "constituent_pe_mod_breadth": breadth_pe_mod,
            "constituent_ce_mod_raw":     ce_mod,
            # Capped totals — these are what compute_signals uses
            "constituent_pe_mod":         total_pe,
            "constituent_ce_mod":         total_ce,
            # Kill switch
            "BANKING_DAILY_COLLAPSE_KILL": banking_collapse,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_weakening(self, stocks: dict) -> bool:
        """2+ banking stocks in INSIDE_BULL with downward momentum."""
        count = sum(
            1 for d in stocks.values()
            if d["regime"] == "INSIDE_BULL"
            and d["mom_state"] in ("MODERATE_DOWN", "STRONG_DOWN")
        )
        return count >= 2

    def _empty_stock_signals(self, symbol: str) -> dict:
        return {
            "symbol": symbol, "regime": "INSIDE_BULL",
            "put_moats": 2, "call_moats": 2,
            "put_moat_detail": [], "call_moat_detail": [],
            "mom_state": "FLAT", "mom_score": 0.0,
            "canary_level": 0,
            "canary_pe_level": 0, "canary_ce_level": 0,
            "canary_src1_pe": 0, "canary_src1_ce": 0,
            "canary_src2_pe": 0, "canary_src2_ce": 0,
            "canary_src3_pe": 0, "canary_src3_ce": 0,
            "canary_driver": "—",
            "size": 0.75, "atr": 0.0, "spot": 0.0,
        }
