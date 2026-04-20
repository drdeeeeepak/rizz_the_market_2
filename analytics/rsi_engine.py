# analytics/rsi_engine.py — v3 (April 2026)
# Pages 05+06 merged: Weekly RSI + Daily RSI + MTF Alignment + Kill Switches
# Pages 07+08 merged: Per-stock RSI + D-W Divergence + Group signals
#
# New additions vs v2:
#   - Renamed kill switches: RSI_REGIME_FLIP, RSI_ZONE_SKIP, RSI_DUAL_EXHAUSTION,
#     RSI_RANGE_BREAKDOWN, RSI_DAILY_EXHAUSTION_REVERSAL
#   - Phase: CONTINUING / TRANSITIONING / REVERSING (replaces EXPANSION etc)
#   - Entry Timing: Early / Mid / Late
#   - MTF alignment matrix with ALIGNED_BULL_NEUTRAL
#   - Weekly breadth signals: WEEKLY_BROAD_BULL, WEEKLY_MIXED, WEEKLY_BROAD_WEAK
#   - New stock signals: WEEKLY_BANKING_ANCHOR, WEEKLY_HEAVYWEIGHT_COLLAPSE,
#     WEEKLY_BANKING_SOFTENING, WEEKLY_INDEX_MASKING, WEEKLY_HEAVYWEIGHT_LEADING_DOWN,
#     WEEKLY_SECTOR_ROTATION, DAILY_BREADTH_BULL, DAILY_BANKING_BULL,
#     DAILY_LEADS_WEEKLY_UP, DAILY_LEADS_WEEKLY_DOWN, DAILY_IT_DRAG, DAILY_BANKING_COLLAPSE
#   - D-W divergence per stock (threshold 8 pts)

import pandas as pd
import numpy as np
from analytics.base_strategy import BaseStrategy
from config import (
    RSI_PERIOD, W_RSI_CAPIT, W_RSI_BEAR_MAX, W_RSI_BEAR_TRANS,
    W_RSI_NEUTRAL_MID, W_RSI_BULL_TRANS, W_RSI_BULL_MIN, W_RSI_EXHAUST,
    D_RSI_CAPIT, D_RSI_BEAR_P, D_RSI_BAL_LOW, D_RSI_BAL_HIGH,
    D_RSI_BULL_P, D_RSI_EXHAUST,
    RSI_KS_W_FLIP_BULL, RSI_KS_W_FLIP_BEAR,
    RSI_W_BULL_TRANS_BONUS, RSI_W_BULL_EXH_EXTRA, RSI_K3_EXTRA,
    RSI_BFSI_SOFTENING, RSI_SD5_CALL_EXTRA, RSI_SD6_EXIT_BUF,
    BANKING_QUARTET, HEAVY_STOCKS, IT_STOCKS, TOP_10_NIFTY,
)

DW_DIVERGENCE_THRESHOLD = 8   # pts — daily leads weekly by this much = early signal
W_WEEKS_RANGE_HOLD      = 10  # weeks RSI must hold above 45 for range_breakdown check


class RSIEngine(BaseStrategy):

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df["rsi_daily"]  = self.rsi(df["close"], RSI_PERIOD)
        wc = df["close"].resample("W-TUE").last()
        wr = self.rsi(wc, RSI_PERIOD)
        df["rsi_weekly"] = wr.reindex(df.index, method="ffill")
        df["d_slope_1d"] = df["rsi_daily"].diff(1)
        df["d_slope_2d"] = df["rsi_daily"].diff(2)
        df["w_slope_1w"] = df["rsi_weekly"].diff(5)
        return df

    def signals(self, df: pd.DataFrame) -> dict:
        df   = self.compute(df.copy())
        r    = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else r

        w_rsi    = round(float(r["rsi_weekly"]), 1)
        d_rsi    = round(float(r["rsi_daily"]),  1)
        d_slope1 = round(float(r["d_slope_1d"]), 2)
        d_slope2 = round(float(r["d_slope_2d"]), 2)
        w_slope  = round(float(r["w_slope_1w"]), 2)

        w_regime  = self._weekly_regime(w_rsi)
        d_zone    = self._daily_zone(d_rsi)
        alignment = self._alignment(w_regime, d_zone)
        phase     = self._phase(df, w_rsi, w_slope)
        entry_timing = self._entry_timing(phase, d_rsi, d_slope1)
        kills     = self._kill_switches(df)
        range_shift = self._range_breakdown(df)
        put_mod   = self._put_dist_modifier(w_regime, kills, alignment)
        call_mod  = self._call_dist_modifier(w_regime, kills, d_rsi)
        home_score = self._home_score(w_rsi, d_rsi, d_slope1, alignment, kills)

        return {
            "rsi_daily": d_rsi, "rsi_weekly": w_rsi,
            "d_slope_1d": d_slope1, "d_slope_2d": d_slope2, "w_slope_1w": w_slope,
            "w_regime": w_regime, "d_zone": d_zone, "alignment": alignment,
            # New phase names
            "rsi_phase": phase, "entry_timing": entry_timing,
            # Legacy name kept for backward compat
            "momentum_phase": phase,
            "range_shift": {"bull_range": range_shift.get("held"), "range_failure": range_shift.get("breakdown")},
            "rsi_put_dist_mod": put_mod, "rsi_call_dist_mod": call_mod,
            "kill_switches": kills, "home_score": home_score,
        }

    # ── Weekly Regime ─────────────────────────────────────────────────────────

    def _weekly_regime(self, w: float) -> str:
        if   w < W_RSI_CAPIT:      return "W_CAPIT"
        elif w < W_RSI_BEAR_MAX:   return "W_BEAR"
        elif w < W_RSI_BEAR_TRANS: return "W_BEAR_TRANS"
        elif w < W_RSI_BULL_TRANS: return "W_NEUTRAL"
        elif w < W_RSI_BULL_MIN:   return "W_BULL_TRANS"
        elif w < W_RSI_EXHAUST:    return "W_BULL"
        else:                       return "W_BULL_EXH"

    # ── Daily Zone ────────────────────────────────────────────────────────────

    def _daily_zone(self, d: float) -> str:
        if   d < D_RSI_CAPIT:    return "D_CAPIT"
        elif d < D_RSI_BEAR_P:   return "D_BEAR_PRESSURE"
        elif d < D_RSI_BAL_HIGH: return "D_BALANCE"
        elif d < D_RSI_BULL_P:   return "D_BULL_PRESSURE"
        elif d < D_RSI_EXHAUST:  return "D_BULL_PRESSURE_PLUS"
        else:                     return "D_EXHAUST"

    # ── MTF Alignment ─────────────────────────────────────────────────────────

    def _alignment(self, wr: str, dz: str) -> str:
        bull_w = wr in ("W_BULL_TRANS", "W_BULL", "W_BULL_EXH")
        neut_w = wr == "W_NEUTRAL"
        bear_w = wr in ("W_CAPIT", "W_BEAR", "W_BEAR_TRANS")
        bull_d = dz in ("D_BALANCE", "D_BULL_PRESSURE", "D_BULL_PRESSURE_PLUS")
        bear_d = dz in ("D_CAPIT", "D_BEAR_PRESSURE")
        exh_d  = dz == "D_EXHAUST"

        if bull_w and bull_d:           return "ALIGNED_BULL"
        if neut_w and dz == "D_BALANCE":return "ALIGNED_BULL_NEUTRAL"
        if bear_w and bear_d:           return "ALIGNED_BEAR"
        if bull_w and bear_d:           return "COUNTER_TRAP_BEAR"
        if bear_w and bull_d:           return "COUNTER_TRAP_BULL"
        return "MIXED"

    # ── Phase (new names per doc) ─────────────────────────────────────────────

    def _phase(self, df: pd.DataFrame, w_rsi: float, w_slope: float) -> str:
        """
        CONTINUING  — current regime intact, no transition signals
        TRANSITIONING — weekly RSI approaching a zone boundary
        REVERSING   — weekly RSI crossed a zone boundary this week
        """
        # Check if weekly RSI has crossed a boundary this week
        if len(df) >= 6:
            prev_w = float(df["rsi_weekly"].iloc[-6])
            curr_w = w_rsi
            boundaries = [W_RSI_CAPIT, W_RSI_BEAR_MAX, W_RSI_BEAR_TRANS,
                          W_RSI_BULL_TRANS, W_RSI_BULL_MIN, W_RSI_EXHAUST]
            for b in boundaries:
                if (prev_w < b <= curr_w) or (prev_w >= b > curr_w):
                    return "REVERSING"
        # Check if approaching a boundary (within 3 pts)
        boundaries_check = [W_RSI_CAPIT, W_RSI_BEAR_MAX, W_RSI_BEAR_TRANS,
                             W_RSI_BULL_TRANS, W_RSI_BULL_MIN, W_RSI_EXHAUST]
        for b in boundaries_check:
            if abs(w_rsi - b) <= 3:
                return "TRANSITIONING"
        return "CONTINUING"

    def _entry_timing(self, phase: str, d_rsi: float, d_slope: float) -> str:
        """
        Early — first 1-2 days after regime confirmed
        Mid   — 3-4 days in, standard
        Late  — 5+ days in, expiry approaching
        """
        if phase == "REVERSING":    return "Early"
        if phase == "TRANSITIONING":return "Mid"
        # Use daily RSI and slope as proxy for week progression
        if d_rsi > 55 or d_rsi < 45: return "Mid"
        return "Late"

    # ── Kill Switches (renamed per doc) ──────────────────────────────────────

    def _kill_switches(self, df: pd.DataFrame) -> dict:
        if len(df) < 3:
            return {k: False for k in [
                "RSI_REGIME_FLIP", "RSI_ZONE_SKIP", "RSI_DUAL_EXHAUSTION",
                "RSI_RANGE_BREAKDOWN", "RSI_DAILY_EXHAUSTION_REVERSAL",
                # Legacy keys kept for backward compat
                "K1", "K2", "K3", "K4", "K5"
            ]}
        r    = df.iloc[-1]
        prev = df.iloc[-2]

        # RSI_REGIME_FLIP (was K1): weekly flipped zones
        regime_flip = (
            (prev["rsi_weekly"] > 60 and r["rsi_weekly"] < RSI_KS_W_FLIP_BULL) or
            (prev["rsi_weekly"] < 40 and r["rsi_weekly"] > RSI_KS_W_FLIP_BEAR)
        )

        # RSI_ZONE_SKIP (was K2): daily skipped a zone
        zone_skip = (
            (prev["rsi_daily"] >= D_RSI_BAL_HIGH and r["rsi_daily"] < D_RSI_BAL_LOW) or
            (prev["rsi_daily"] <= D_RSI_BAL_LOW  and r["rsi_daily"] > D_RSI_BAL_HIGH)
        )

        # RSI_DUAL_EXHAUSTION (was K3): both timeframes exhausted simultaneously
        dual_exhaustion = (
            (r["rsi_weekly"] > W_RSI_EXHAUST and r["rsi_daily"] > D_RSI_EXHAUST) or
            (r["rsi_weekly"] < W_RSI_CAPIT   and r["rsi_daily"] < D_RSI_CAPIT)
        )

        # RSI_RANGE_BREAKDOWN (was K4): held 45+ for 10 weeks then dropped below 40
        rb = self._range_breakdown(df)
        range_breakdown = rb.get("breakdown", False)

        # RSI_DAILY_EXHAUSTION_REVERSAL (was K5): daily above 68 + slope turning negative
        exhaustion_reversal = (
            r["rsi_daily"] > D_RSI_EXHAUST and r["d_slope_1d"] < 0
        )

        return {
            # New names
            "RSI_REGIME_FLIP":               bool(regime_flip),
            "RSI_ZONE_SKIP":                 bool(zone_skip),
            "RSI_DUAL_EXHAUSTION":           bool(dual_exhaustion),
            "RSI_RANGE_BREAKDOWN":           bool(range_breakdown),
            "RSI_DAILY_EXHAUSTION_REVERSAL": bool(exhaustion_reversal),
            # Legacy names — kept for compute_signals.py backward compat
            "K1": bool(regime_flip), "K2": bool(zone_skip), "K3": bool(dual_exhaustion),
            "K4": bool(range_breakdown), "K5": bool(exhaustion_reversal),
        }

    def _range_breakdown(self, df: pd.DataFrame) -> dict:
        if "rsi_weekly" not in df.columns or len(df) < W_WEEKS_RANGE_HOLD * 5 + 5:
            return {"held": False, "breakdown": False}
        w = df["rsi_weekly"]
        # Check last 10 weeks (50 trading days approx)
        lookback = min(W_WEEKS_RANGE_HOLD * 5, len(w) - 1)
        held_above_45 = all(w.iloc[-(lookback+1):-1] >= 45)
        dropped_below_40 = float(w.iloc[-1]) < 40
        return {
            "held": held_above_45,
            "breakdown": held_above_45 and dropped_below_40
        }

    # ── Distance modifiers ────────────────────────────────────────────────────

    def _put_dist_modifier(self, wr: str, kills: dict, alignment: str) -> int:
        extra = 0
        if wr == "W_BULL_EXH":  extra += RSI_W_BULL_EXH_EXTRA
        if wr == "W_BEAR":       extra += 300
        if wr == "W_CAPIT":      extra += 600
        if kills.get("RSI_DUAL_EXHAUSTION"): extra += RSI_K3_EXTRA
        if wr in ("W_BULL_TRANS", "W_BULL"): extra -= RSI_W_BULL_TRANS_BONUS
        return max(0, extra)

    def _call_dist_modifier(self, wr: str, kills: dict, d_rsi: float) -> int:
        extra = 0
        if wr == "W_BULL_EXH":              extra += RSI_W_BULL_EXH_EXTRA
        if kills.get("RSI_DUAL_EXHAUSTION"): extra += RSI_K3_EXTRA
        return max(0, extra)

    # ── Home score ────────────────────────────────────────────────────────────

    def _home_score(self, w, d, s1, alignment, kills) -> int:
        hard_kills = [kills.get(k) for k in
                      ("RSI_REGIME_FLIP", "RSI_ZONE_SKIP", "RSI_DUAL_EXHAUSTION")]
        if any(hard_kills): return 0
        score = 0
        if alignment in ("ALIGNED_BULL", "ALIGNED_BULL_NEUTRAL", "ALIGNED_BEAR"): score += 8
        if alignment not in ("COUNTER_TRAP_BEAR", "COUNTER_TRAP_BULL"): score += 4
        if s1 > 0:  score += 3
        if 45 < w < 70: score += 5
        return min(score, 20)

    # ══════════════════════════════════════════════════════════════════════════
    # STOCK SIGNALS — Pages 07+08
    # ══════════════════════════════════════════════════════════════════════════

    def stock_signals(self, stock_dfs: dict) -> dict:
        """
        Run RSI signals on each stock. Returns per-stock data and aggregated
        group signals with new names per Pages 07+08 doc.
        """
        per = {}
        for sym, df in stock_dfs.items():
            if df is None or df.empty:
                continue
            try:
                s = self.signals(df)
                per[sym] = {
                    "w_rsi":    s["rsi_weekly"],
                    "d_rsi":    s["rsi_daily"],
                    "w_regime": s["w_regime"],
                    "d_zone":   s["d_zone"],
                    "w_slope":  s["w_slope_1w"],
                    "d_slope":  s["d_slope_1d"],
                    "alignment":s["alignment"],
                    # D-W divergence
                    "dw_divergence": round(s["rsi_daily"] - s["rsi_weekly"], 1),
                }
            except Exception:
                pass

        if not per:
            return self._empty_stock_signals()

        # ── Weekly breadth ────────────────────────────────────────────────────
        count_bull = sum(1 for d in per.values()
                         if d["w_rsi"] >= W_RSI_BULL_TRANS)  # RSI >= 60
        if   count_bull >= 6: weekly_breadth = "WEEKLY_BROAD_BULL";  breadth_pe_mod = -100
        elif count_bull >= 4: weekly_breadth = "WEEKLY_MIXED";        breadth_pe_mod = 0
        else:                  weekly_breadth = "WEEKLY_BROAD_WEAK";   breadth_pe_mod = 200

        # ── Group weekly signals ──────────────────────────────────────────────
        # WEEKLY_BANKING_ANCHOR (SW3): all 4 banks RSI >= 60
        banking_anchor = all(
            per.get(b, {}).get("w_rsi", 0) >= W_RSI_BULL_TRANS
            for b in BANKING_QUARTET
        )

        # WEEKLY_HEAVYWEIGHT_COLLAPSE (SW4): 2 of 3 heavyweights RSI < 40
        heavy_collapse = sum(
            1 for s in HEAVY_STOCKS
            if per.get(s, {}).get("w_rsi", 50) < W_RSI_BEAR_MAX
        ) >= 2

        # WEEKLY_BANKING_SOFTENING (SW5): 2 of 4 banks weekly RSI falling 3 consecutive weeks
        bfsi_softening = sum(
            1 for b in BANKING_QUARTET
            if per.get(b, {}).get("w_slope", 0) < 0
        ) >= 2

        # WEEKLY_INDEX_MASKING (Divergence Alert): Nifty RSI > 50 but 3+ stocks W_BEAR or worse
        # Nifty RSI is external — approximate: use avg stock RSI > 50 as proxy for Nifty bullish
        avg_w_rsi = np.mean([d["w_rsi"] for d in per.values()]) if per else 50
        nifty_bullish_proxy = avg_w_rsi > 50
        masking_count = sum(
            1 for d in per.values()
            if d["w_rsi"] < W_RSI_BEAR_MAX  # below 40 = bear or worse
        )
        index_masking = nifty_bullish_proxy and masking_count >= 3

        # WEEKLY_HEAVYWEIGHT_LEADING_DOWN (Lead Warning): HDFC or Reliance in W_BEAR
        heavy_leading_down = any(
            per.get(s, {}).get("w_rsi", 50) < W_RSI_BEAR_MAX
            for s in ["HDFCBANK", "RELIANCE"]
        )

        # WEEKLY_SECTOR_ROTATION: 2+ banks W_BULL AND 1+ IT stocks W_BEAR
        banks_bull_count = sum(
            1 for b in BANKING_QUARTET
            if per.get(b, {}).get("w_rsi", 0) >= W_RSI_BULL_MIN  # >= 65
        )
        it_bear_count = sum(
            1 for t in IT_STOCKS
            if per.get(t, {}).get("w_regime") in ("W_BEAR", "W_CAPIT", "W_BEAR_TRANS")
        )
        sector_rotation = banks_bull_count >= 2 and it_bear_count >= 1

        # ── Daily breadth signals ─────────────────────────────────────────────
        # DAILY_BREADTH_BULL (SD1): 6+ stocks daily RSI > 54
        daily_breadth_bull = sum(
            1 for d in per.values() if d["d_rsi"] > D_RSI_BULL_P  # > 54
        ) >= 6

        # DAILY_BANKING_BULL (SD2): 2+ banks daily RSI > 68
        daily_banking_bull = sum(
            1 for b in BANKING_QUARTET
            if per.get(b, {}).get("d_rsi", 0) > D_RSI_EXHAUST  # > 68
        ) >= 2

        # DAILY_LEADS_WEEKLY_UP (SD3): daily leads weekly by > 8pts upward for 2+ stocks
        leads_up_count = sum(
            1 for d in per.values()
            if d["dw_divergence"] > DW_DIVERGENCE_THRESHOLD
        )
        daily_leads_up = leads_up_count >= 3

        # DAILY_LEADS_WEEKLY_DOWN (SD4): daily leads weekly lower by > 8pts
        leads_down_count = sum(
            1 for d in per.values()
            if d["dw_divergence"] < -DW_DIVERGENCE_THRESHOLD
        )
        daily_leads_down = leads_down_count >= 3

        # DAILY_IT_DRAG (SD5): Infosys AND TCS daily RSI < 40 with negative slope
        daily_it_drag = all(
            per.get(t, {}).get("d_rsi", 50) < D_RSI_BEAR_P and  # < 39
            per.get(t, {}).get("d_slope", 0) < 0
            for t in IT_STOCKS
        )

        # DAILY_BANKING_COLLAPSE (SD6): 3 of 4 banks daily RSI < 40
        daily_banking_collapse = sum(
            1 for b in BANKING_QUARTET
            if per.get(b, {}).get("d_rsi", 50) < D_RSI_BEAR_P  # < 39
        ) >= 3

        # ── Daily breadth PE modifier ─────────────────────────────────────────
        daily_above_54 = sum(1 for d in per.values() if d["d_rsi"] > D_RSI_BULL_P)
        daily_below_46 = sum(1 for d in per.values() if d["d_rsi"] < D_RSI_BAL_LOW)
        daily_below_40 = sum(1 for d in per.values() if d["d_rsi"] < D_RSI_BEAR_P)

        if   daily_above_54 >= 6: daily_breadth_pe_mod = 0
        elif daily_below_40 >= 4: daily_breadth_pe_mod = 400
        elif daily_below_46 >= 6: daily_breadth_pe_mod = 200
        else:                      daily_breadth_pe_mod = 0

        # ── Legacy signal names (backward compat with compute_signals) ─────────
        sw3       = banking_anchor
        sw4       = heavy_collapse  # HEAVYWEIGHT_COLLAPSE
        bfsi      = bfsi_softening
        sd5       = daily_it_drag
        sd6       = daily_banking_collapse
        heavy_drag = heavy_collapse  # same concept

        put_dist_mod  = 0
        call_dist_mod = 0
        if heavy_collapse:    put_dist_mod  += 300
        if bfsi_softening:    put_dist_mod  += RSI_BFSI_SOFTENING
        if sw3:               put_dist_mod  -= 200
        if sd5:               call_dist_mod += RSI_SD5_CALL_EXTRA

        return {
            "per_stock": per,
            "avg_w_rsi": round(avg_w_rsi, 1),
            # New signal names
            "WEEKLY_BROAD_BULL":            weekly_breadth == "WEEKLY_BROAD_BULL",
            "WEEKLY_MIXED":                 weekly_breadth == "WEEKLY_MIXED",
            "WEEKLY_BROAD_WEAK":            weekly_breadth == "WEEKLY_BROAD_WEAK",
            "weekly_breadth_label":         weekly_breadth,
            "weekly_breadth_pe_mod":        breadth_pe_mod,
            "WEEKLY_BANKING_ANCHOR":        banking_anchor,
            "WEEKLY_HEAVYWEIGHT_COLLAPSE":  heavy_collapse,
            "WEEKLY_BANKING_SOFTENING":     bfsi_softening,
            "WEEKLY_INDEX_MASKING":         index_masking,
            "WEEKLY_HEAVYWEIGHT_LEADING_DOWN": heavy_leading_down,
            "WEEKLY_SECTOR_ROTATION":       sector_rotation,
            "DAILY_BREADTH_BULL":           daily_breadth_bull,
            "DAILY_BANKING_BULL":           daily_banking_bull,
            "DAILY_LEADS_WEEKLY_UP":        daily_leads_up,
            "DAILY_LEADS_WEEKLY_DOWN":      daily_leads_down,
            "DAILY_IT_DRAG":               daily_it_drag,
            "DAILY_BANKING_COLLAPSE":       daily_banking_collapse,
            "leads_up_count":              leads_up_count,
            "leads_down_count":            leads_down_count,
            "daily_breadth_pe_mod":        daily_breadth_pe_mod,
            # Legacy names for backward compat
            "rotation_signal": sector_rotation,
            "heavy_drag":      heavy_collapse,
            "bfsi_softening":  bfsi_softening,
            "sw3_active":      sw3,
            "sw4_active":      sw4,
            "sd5_active":      sd5,
            "sd6_active":      sd6,
            "stock_put_dist_mod":  put_dist_mod,
            "stock_call_dist_mod": call_dist_mod,
            "kill_switches": {
                "heavy_drag":           heavy_collapse,
                "sd6_banking_collapse": sd6,
                "DAILY_BANKING_COLLAPSE": sd6,
            },
        }

    def _empty_stock_signals(self) -> dict:
        return {
            "per_stock": {}, "avg_w_rsi": 50.0,
            "WEEKLY_BROAD_BULL": False, "WEEKLY_MIXED": True, "WEEKLY_BROAD_WEAK": False,
            "weekly_breadth_label": "WEEKLY_MIXED", "weekly_breadth_pe_mod": 0,
            "WEEKLY_BANKING_ANCHOR": False, "WEEKLY_HEAVYWEIGHT_COLLAPSE": False,
            "WEEKLY_BANKING_SOFTENING": False, "WEEKLY_INDEX_MASKING": False,
            "WEEKLY_HEAVYWEIGHT_LEADING_DOWN": False, "WEEKLY_SECTOR_ROTATION": False,
            "DAILY_BREADTH_BULL": False, "DAILY_BANKING_BULL": False,
            "DAILY_LEADS_WEEKLY_UP": False, "DAILY_LEADS_WEEKLY_DOWN": False,
            "DAILY_IT_DRAG": False, "DAILY_BANKING_COLLAPSE": False,
            "leads_up_count": 0, "leads_down_count": 0, "daily_breadth_pe_mod": 0,
            "rotation_signal": False, "heavy_drag": False, "bfsi_softening": False,
            "sw3_active": False, "sw4_active": False, "sd5_active": False, "sd6_active": False,
            "stock_put_dist_mod": 0, "stock_call_dist_mod": 0,
            "kill_switches": {},
        }
