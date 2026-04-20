# analytics/ema.py — v6 (April 2026)
# New unified EMA framework — Pages 1+2
#
# Three independent components — no double counting:
#   Component 1: Cluster Regime (7 regimes — RECOVERING added)
#                Symmetric ATR-multiple base. No moat info encoded.
#   Component 2: Moat Count (creates ALL asymmetry between PE and CE)
#                Clustering rule (50pts), Degraded EMA8 rule (neg slope = 0.5)
#   Component 3: Momentum Score (threatened leg only)
#
# Distance formula: (Base_mult + Moat_mult + Mom_mult) × ATR14 = distance pts
# Each lens outputs its own standalone distance — aggregation in compute_signals
#
# Legacy P1 Duration Score retained for canary/kill switch logic only
# Legacy P2 Stack Score retained for backward compat display

import pandas as pd
import numpy as np
from analytics.base_strategy import BaseStrategy
from config import (
    MTF_EMA_PERIODS,
    DURATION_LOOKBACK,
    PUT_SAFETY_W1, PUT_SAFETY_W2, PUT_EMA_PRIMARY, PUT_EMA_SECONDARY,
    CALL_SAFETY_W1, CALL_SAFETY_W2, CALL_EMA_PRIMARY, CALL_EMA_SECONDARY,
    WICK_THRESHOLD_PCT, WICK_PENALTY,
    EMA38_THRESHOLD, EMA38_PENALTY_PCT,
    FLAT_PCT, FLAT_1_2_DAYS, FLAT_3_4_DAYS,
    SAFETY_DISC, NET_SKEW_TABLE,
    P1_EMA60_1_DECAY, P1_EMA60_2_DECAY, P1_EMA120_DECAY,
    P1_WHIPSAW_PCT, P1_HARD_EXIT,
    STACK_WEIGHTS, CV_KNOT, CV_FAN, CONSISTENCY_BASE, CONSISTENCY_SLOPE,
    REGIME_DISTANCES,
)

# ── Cluster definitions ────────────────────────────────────────────────────
FAST_CLUSTER      = [8, 16, 30]
SLOW_CLUSTER      = [60, 120, 200]
MOAT_SET          = [8, 16, 30, 60, 120, 200]
MOAT_CLUSTER_DIST = 50    # pts — moats this close count as one
ATR_WEEKLY_MULT   = 2.0
ATR_BIWEEKLY_MULT = 3.0

# ── Regime base ATR multiples (symmetric — moat count creates asymmetry) ──
# Base = how structurally threatening / uncertain is the overall regime?
# 2.0× = clean structure  |  2.25× = transitional  |  2.5× = deteriorating
REGIME_BASE_MULT = {
    "STRONG_BULL":     2.00,
    "BULL_COMPRESSED": 2.00,
    "INSIDE_BULL":     2.00,
    "RECOVERING":      2.25,   # spot above fast, fast entirely below slow
    "INSIDE_BEAR":     2.50,
    "BEAR_COMPRESSED": 2.25,
    "STRONG_BEAR":     2.50,
}

# IC shape and size guidance per regime (for display only — not distance calc)
REGIME_GUIDE = {
    "STRONG_BULL":     {"ratio": "1:2", "size": 1.00, "desc": "Full bullish stack. CE needs room — moats define asymmetry."},
    "BULL_COMPRESSED": {"ratio": "1:2", "size": 0.75, "desc": "Fast cluster penetrating slow. Mild upward pressure."},
    "INSIDE_BULL":     {"ratio": "1:1", "size": 0.75, "desc": "Pullback in uptrend. Spot inside fast cluster."},
    "RECOVERING":      {"ratio": "1:1", "size": 0.75, "desc": "Bounced above fast cluster. Slow cluster still overhead as ceiling."},
    "INSIDE_BEAR":     {"ratio": "1:1", "size": 0.50, "desc": "Deteriorating structure. Fast below slow. Both legs uncertain."},
    "BEAR_COMPRESSED": {"ratio": "2:1", "size": 0.75, "desc": "Fast cluster trying to break below slow."},
    "STRONG_BEAR":     {"ratio": "2:1", "size": 0.625,"desc": "Full bearish stack. PE exposed. CE has all EMAs as overhead resistance."},
}

# ── Moat count → ATR multiple adjustment ──────────────────────────────────
# Applied independently per side. Creates all asymmetry.
MOAT_MULT = {
    "fortress": -0.25,   # 5-6 moats
    "strong":    0.00,   # 3-4 moats
    "adequate":  0.25,   # 2 moats
    "thin":      0.50,   # 1 moat
    "exposed":   0.75,   # 0 moats
}

def moat_label_and_mult(count: float) -> tuple:
    """Returns (label, atm_multiple) for a given (possibly fractional) moat count."""
    if   count >= 5:  return "fortress", MOAT_MULT["fortress"]
    elif count >= 3:  return "strong",   MOAT_MULT["strong"]
    elif count >= 2:  return "adequate", MOAT_MULT["adequate"]
    elif count >= 1:  return "thin",     MOAT_MULT["thin"]
    else:             return "exposed",  MOAT_MULT["exposed"]

# ── Momentum → ATR multiple adjustment (threatened leg only) ─────────────
MOM_STRONG_UP_THRESH   = +15.0  # % ATR/day
MOM_MODERATE_UP_THRESH =  +5.0
MOM_MODERATE_DN_THRESH =  -5.0
MOM_STRONG_DN_THRESH   = -15.0

MOM_MULTS = {
    "STRONG_UP":    (0.00, 0.50),   # (PE add, CE add)
    "MODERATE_UP":  (0.00, 0.25),
    "FLAT":         (0.00, 0.00),
    "MODERATE_DOWN":(0.25, 0.00),
    "STRONG_DOWN":  (0.50, 0.00),
    "TRANSITIONING":(0.25, 0.25),   # both sides uncertain
}


class EMAEngine(BaseStrategy):

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        for p in MTF_EMA_PERIODS:
            df[f"ema{p}"] = self.ema(df["close"], p)
        df["ema3"]  = self.ema(df["close"], 3)
        df["atr14"] = self.atr(df, 14)
        return df

    def signals(self, df: pd.DataFrame) -> dict:
        df  = self.compute(df.copy())
        p1  = self._page1_signals(df)    # legacy — for canary/kill switches
        p2  = self._page2_signals(df)    # legacy — for backward compat
        cr  = self._cluster_regime_signals(df)  # new framework
        return {**p1, **p2, **cr}

    # ══════════════════════════════════════════════════════════════════════
    # LEGACY Page 1 — retained for canary and kill switch logic only
    # ══════════════════════════════════════════════════════════════════════

    def _page1_signals(self, df: pd.DataFrame) -> dict:
        r = df.iloc[-1]
        put_raw  = self._put_safety_raw(df)
        call_raw = self._call_safety_raw(df)

        ema3_lt_ema8 = float(r["ema3"]) < float(r["ema8"])
        ema3_gt_ema8 = float(r["ema3"]) > float(r["ema8"])

        if ema3_lt_ema8 and put_raw > EMA38_THRESHOLD:
            put_raw *= (1 - EMA38_PENALTY_PCT)
        if ema3_gt_ema8 and call_raw > EMA38_THRESHOLD:
            call_raw *= (1 - EMA38_PENALTY_PCT)

        flat_days  = self._flat_days(df)
        flat_block = flat_days >= 5
        if flat_days >= 5:
            put_raw *= 0.80; call_raw *= 0.80
        elif flat_days >= 3:
            put_raw *= (1 - FLAT_3_4_DAYS); call_raw *= (1 - FLAT_3_4_DAYS)
        elif flat_days >= 1:
            put_raw *= (1 - FLAT_1_2_DAYS); call_raw *= (1 - FLAT_1_2_DAYS)

        p1_decay  = self._p1_decay(df)
        put_adj   = round(max(0, put_raw  * (1 - p1_decay["put_decay_pct"])), 1)
        call_adj  = round(max(0, call_raw * (1 - p1_decay["call_decay_pct"])), 1)
        net_skew  = round(call_adj - put_adj, 1)
        atr       = float(r.get("atr14", 200))
        hard_exit = (put_adj < P1_HARD_EXIT and ema3_lt_ema8)

        # Legacy distances (kept for compute_signals legacy path — not primary)
        call_dist, put_dist, ratio = self._distances_from_skew(net_skew)

        return {
            "put_safety_adj": put_adj,  "call_safety_adj": call_adj,
            "put_safety_raw": round(put_raw, 1), "call_safety_raw": round(call_raw, 1),
            "net_skew": net_skew, "flat_days": flat_days, "flat_block": flat_block,
            "p1_decay": p1_decay, "p1_decay_level": p1_decay["decay_level"],
            "p1_call_dist": call_dist, "p1_put_dist": put_dist, "p1_ratio": ratio,
            "p1_hard_exit": hard_exit, "atr14": round(atr, 1),
            "ema3_below_ema8": ema3_lt_ema8, "ema3_above_ema8": ema3_gt_ema8,
            "ema3":   round(float(r["ema3"]),   0), "ema8":   round(float(r["ema8"]),   0),
            "ema16":  round(float(r["ema16"]),  0), "ema30":  round(float(r["ema30"]),  0),
            "ema60":  round(float(r["ema60"]),  0), "ema120": round(float(r["ema120"]), 0),
            "ema200": round(float(r["ema200"]), 0),
            "kill_switches": {"flat_block": flat_block, "p1_hard_exit": hard_exit},
            "home_score": self._p1_home_score(put_adj, call_adj, p1_decay, flat_block),
        }

    def _put_safety_raw(self, df):
        recent   = df.tail(DURATION_LOOKBACK)
        above60  = (recent["close"] > recent["ema60"]).mean() * 100
        above120 = (recent["close"] > recent["ema120"]).mean() * 100
        raw = PUT_SAFETY_W1 * above60 + PUT_SAFETY_W2 * above120
        stress = sum(
            WICK_PENALTY for _, row in recent.iterrows()
            if row["low"] < row["ema60"] * (1 - WICK_THRESHOLD_PCT)
            and row["close"] > row["ema60"]
        )
        return max(0.0, raw - stress)

    def _call_safety_raw(self, df):
        recent = df.tail(DURATION_LOOKBACK)
        b30 = (recent["close"] < recent["ema30"]).mean() * 100
        b60 = (recent["close"] < recent["ema60"]).mean() * 100
        return CALL_SAFETY_W1 * b30 + CALL_SAFETY_W2 * b60

    def _flat_days(self, df):
        count = 0
        for i in range(len(df) - 1, -1, -1):
            row = df.iloc[i]
            if row["ema8"] and abs(row["ema3"] - row["ema8"]) / row["ema8"] < FLAT_PCT:
                count += 1
            else:
                break
        return count

    def _p1_decay(self, df):
        if len(df) < 3:
            return {"put_decay_pct": 0, "call_decay_pct": 0, "decay_level": "none"}
        r = df.iloc[-1]; prev = df.iloc[-2]
        put_decay = 0.0
        if r["close"] < r["ema120"]:
            put_decay = P1_EMA120_DECAY
        elif r["close"] < r["ema60"] and prev["close"] < prev["ema60"]:
            put_decay = P1_EMA60_2_DECAY
        elif r["close"] < r["ema60"]:
            put_decay = P1_EMA60_1_DECAY
        if abs(r["close"] - r["ema60"]) / r["ema60"] < P1_WHIPSAW_PCT:
            if len(df) >= 3 and df.iloc[-3]["close"] > df.iloc[-3]["ema60"]:
                put_decay = 0.0
        level = ("severe"   if put_decay >= P1_EMA120_DECAY else
                 "high"     if put_decay >= P1_EMA60_2_DECAY else
                 "moderate" if put_decay > 0 else "none")
        return {"put_decay_pct": put_decay, "call_decay_pct": 0.0, "decay_level": level}

    def _safety_disc_pts(self, adj):
        for lo, hi, pts in SAFETY_DISC:
            if lo <= adj <= hi: return pts
        return 600

    def _distances_from_skew(self, skew):
        for lo, hi, cd, pd_, ratio in NET_SKEW_TABLE:
            if lo <= skew <= hi: return cd, pd_, ratio
        return 1200, 1200, "1:1"

    def _p1_home_score(self, put_adj, call_adj, decay, flat_block):
        if flat_block or decay["decay_level"] == "severe": return 0
        s = 0
        if put_adj >= 75: s += 4
        elif put_adj >= 50: s += 2
        if call_adj >= 75: s += 4
        elif call_adj >= 50: s += 2
        if decay["decay_level"] == "none": s += 2
        return min(s, 10)

    # ══════════════════════════════════════════════════════════════════════
    # LEGACY Page 2 — Stack Score / CV (retained for backward compat)
    # ══════════════════════════════════════════════════════════════════════

    def _page2_signals(self, df):
        r    = df.iloc[-1]
        emas = {p: float(r.get(f"ema{p}", 0)) for p in MTF_EMA_PERIODS}
        stack = self._stack_score(emas)
        cv    = self._cv(emas)
        regime= self._classify_regime_legacy(stack, cv, emas)
        cons  = self._consistency(df)
        adj   = round(stack * cons, 1)
        dist  = REGIME_DISTANCES.get(regime, REGIME_DISTANCES["WEAK_MIXED"])
        canary= self._canary_level(df)
        ext   = self._extension(df, emas)
        cvc   = self._cv_compress(df)
        return {
            "p2_stack_score": stack, "p2_stack_adj": adj, "p2_cv": round(cv, 3),
            "p2_regime": regime, "p2_consistency": round(cons, 3),
            "p2_call_dist": dist["call"], "p2_put_dist": dist["put"],
            "p2_ratio": dist["ratio"], "p2_size": dist["size"],
            "canary_level": canary["level"], "canary_direction": canary["direction"],
            "canary_day": canary["day"], "cv_compress": cvc, "extension_pct": ext,
        }

    def _stack_score(self, e):
        return sum(w for (f, s), w in STACK_WEIGHTS.items() if e.get(f,0) > e.get(s,0))

    def _cv(self, e):
        v = list(e.values()); m = np.mean(v)
        return (np.std(v) / m * 100) if m else 0

    def _classify_regime_legacy(self, stack, cv, e):
        bull = stack >= 60; bear = stack <= 40
        if cv < CV_KNOT: return "KNOT"
        if bull and cv > CV_FAN * 1.5: return "STRONG_BULL"
        if bull: return "BULLISH_FAN"
        if bear and cv > CV_FAN * 1.5: return "STRONG_BEAR"
        if bear: return "BEARISH_FAN"
        return "WEAK_MIXED"

    def _consistency(self, df):
        recent = df.tail(20)
        pairs  = [(3,8),(8,16),(16,30),(30,60),(60,120),(120,200)]
        cons   = sum(
            1 for f, s in pairs
            if f"ema{f}" in recent.columns and f"ema{s}" in recent.columns
            and ((recent[f"ema{f}"] > recent[f"ema{s}"]).mean() >= 0.8 or
                 (recent[f"ema{f}"] > recent[f"ema{s}"]).mean() <= 0.2)
        ) / len(pairs)
        return CONSISTENCY_BASE + cons * CONSISTENCY_SLOPE

    def _canary_level(self, df):
        r = df.iloc[-1]
        e3, e8, e16, e30 = (float(r.get(f"ema{p}", 0)) for p in [3, 8, 16, 30])
        if e16 > e30 and e8 < e16: return {"level": 4, "direction": "BEAR", "day": 4}
        if e8 < e16:               return {"level": 3, "direction": "BEAR", "day": 3}
        if abs(e8 - e16) < 30:     return {"level": 2, "direction": "BEAR", "day": 2}
        if e3 < e8:                return {"level": 1, "direction": "BEAR", "day": 1}
        if e16 < e30 and e8 > e16: return {"level": 4, "direction": "BULL", "day": 4}
        if e8 > e16:               return {"level": 3, "direction": "BULL", "day": 3}
        if e3 > e8:                return {"level": 1, "direction": "BULL", "day": 1}
        return {"level": 0, "direction": "NONE", "day": 0}

    def _extension(self, df, emas):
        close = float(df.iloc[-1]["close"]); ema60 = emas.get(60, close)
        return round(abs(close - ema60) / ema60 * 100, 2) if ema60 else 0.0

    def _cv_compress(self, df):
        if len(df) < 3: return 0.0
        def cv_at(row):
            v = [float(row.get(f"ema{p}", 0)) for p in [3,8,16,30,60,120,200]]
            m = np.mean(v); return (np.std(v)/m*100) if m else 0
        return round(cv_at(df.iloc[-1]) - cv_at(df.iloc[-3]), 3)

    # ══════════════════════════════════════════════════════════════════════
    # NEW FRAMEWORK — Component 1: Cluster Regime
    # ══════════════════════════════════════════════════════════════════════

    def _cluster_regime(self, r, spot: float) -> tuple:
        """
        Seven-regime classification.
        Detection order matters — RECOVERING must be checked before fallback.

        Regimes:
          STRONG_BULL:     spot > fast > slow
          BULL_COMPRESSED: spot > fast, fast inside slow
          INSIDE_BULL:     fast > slow, spot inside fast
          RECOVERING:      spot > fast, fast entirely below slow  ← NEW
          INSIDE_BEAR:     fast < slow, spot inside fast
          BEAR_COMPRESSED: spot < fast, fast inside slow
          STRONG_BEAR:     spot < fast < slow
        """
        fast = {p: float(r.get(f"ema{p}", spot)) for p in FAST_CLUSTER}
        slow = {p: float(r.get(f"ema{p}", spot)) for p in SLOW_CLUSTER}

        fast_max = max(fast.values()); fast_min = min(fast.values())
        slow_max = max(slow.values()); slow_min = min(slow.values())

        spot_above_fast = spot > fast_max
        spot_below_fast = spot < fast_min
        spot_in_fast    = fast_min <= spot <= fast_max

        fast_above_slow = fast_min > slow_max
        fast_below_slow = fast_max < slow_min
        fast_in_slow    = not fast_above_slow and not fast_below_slow

        # Detection in priority order — most specific first
        if spot_above_fast and fast_above_slow:
            regime = "STRONG_BULL"
        elif spot_below_fast and fast_below_slow:
            regime = "STRONG_BEAR"
        elif spot_above_fast and fast_in_slow:
            regime = "BULL_COMPRESSED"
        elif spot_below_fast and fast_in_slow:
            regime = "BEAR_COMPRESSED"
        elif spot_above_fast and fast_below_slow:
            regime = "RECOVERING"          # ← the missing regime — now explicit
        elif fast_above_slow and spot_in_fast:
            regime = "INSIDE_BULL"
        elif fast_below_slow and spot_in_fast:
            regime = "INSIDE_BEAR"
        else:
            # True edge case: spot exactly at cluster boundary
            # Classify conservatively by overall direction
            if spot > (fast_min + fast_max) / 2:
                regime = "INSIDE_BULL"
            else:
                regime = "INSIDE_BEAR"

        base_mult = REGIME_BASE_MULT[regime]
        guide     = REGIME_GUIDE[regime]
        return regime, base_mult, guide

    # ══════════════════════════════════════════════════════════════════════
    # NEW FRAMEWORK — Component 2: Moat Count
    # ══════════════════════════════════════════════════════════════════════

    def _count_moats_put(self, spot: float, ema_vals: dict, atr: float,
                          ema3_slope: float = 0.0) -> tuple:
        """
        Count EMAs protecting the put leg (below spot, within 3×ATR).
        Rules:
          - Clustering: moats within 50pts count as ONE
          - Degraded: EMA8 with negative slope counts as 0.5 moat
        Returns (effective_count, detail_list)
        """
        biweekly_floor = spot - atr * ATR_BIWEEKLY_MULT
        candidates = []
        for p in MOAT_SET:
            v = ema_vals[p]
            if biweekly_floor < v < spot:
                candidates.append((p, v))

        if not candidates:
            return 0.0, []

        # Sort by value descending (closest to spot first)
        candidates.sort(key=lambda x: x[1], reverse=True)

        # Apply clustering rule: moats within 50 pts merge
        merged = []
        for p, v in candidates:
            if merged and abs(v - merged[-1][1]) <= MOAT_CLUSTER_DIST:
                # Merge — keep the label as combined, use the higher value
                prev_p, prev_v = merged[-1]
                merged[-1] = (f"{prev_p}+{p}", prev_v)
            else:
                merged.append((p, v))

        # Apply degraded moat rule: EMA8 with negative slope = 0.5
        effective_count = 0.0
        detail = []
        for label, v in merged:
            is_ema8 = "8" in str(label) and "+" not in str(label)
            if is_ema8 and ema3_slope < 0:
                effective_count += 0.5
                detail.append((f"EMA{label}(degraded)", round(v, 0)))
            else:
                effective_count += 1.0
                detail.append((f"EMA{label}", round(v, 0)))

        return effective_count, detail

    def _count_moats_call(self, spot: float, ema_vals: dict, atr: float) -> tuple:
        """
        Count EMAs protecting the call leg (above spot, within 3×ATR).
        Clustering rule applies. No degraded rule for call side.
        Returns (effective_count, detail_list)
        """
        biweekly_ceil = spot + atr * ATR_BIWEEKLY_MULT
        candidates = []
        for p in MOAT_SET:
            v = ema_vals[p]
            if spot < v < biweekly_ceil:
                candidates.append((p, v))

        if not candidates:
            return 0.0, []

        # Sort ascending (closest to spot first)
        candidates.sort(key=lambda x: x[1])

        # Clustering
        merged = []
        for p, v in candidates:
            if merged and abs(v - merged[-1][1]) <= MOAT_CLUSTER_DIST:
                prev_p, prev_v = merged[-1]
                merged[-1] = (f"{prev_p}+{p}", prev_v)
            else:
                merged.append((p, v))

        count  = float(len(merged))
        detail = [(f"EMA{label}", round(v, 0)) for label, v in merged]
        return count, detail

    # ══════════════════════════════════════════════════════════════════════
    # NEW FRAMEWORK — Component 3: Momentum Score
    # ══════════════════════════════════════════════════════════════════════

    def _momentum_score(self, df: pd.DataFrame, atr: float) -> tuple:
        """
        Combined momentum from EMA3 and EMA8 slopes normalised by ATR14.
        Returns (combined_score_pct, state, ema3_slope_pts, ema8_slope_pts)
        """
        if len(df) < 4 or atr == 0:
            return 0.0, "FLAT", 0.0, 0.0

        ema3_slope = (float(df["ema3"].iloc[-1]) - float(df["ema3"].iloc[-4])) / 3
        ema8_slope = (float(df["ema8"].iloc[-1]) - float(df["ema8"].iloc[-4])) / 3

        ema3_str = ema3_slope / atr * 100
        ema8_str = ema8_slope / atr * 100
        combined = ema3_str * 0.6 + ema8_str * 0.4

        # Transitioning: EMA3 and EMA8 disagree on direction
        if (ema3_slope > 0) != (ema8_slope > 0):
            state = "TRANSITIONING"
        elif combined > MOM_STRONG_UP_THRESH:
            state = "STRONG_UP"
        elif combined > MOM_MODERATE_UP_THRESH:
            state = "MODERATE_UP"
        elif combined < MOM_STRONG_DN_THRESH:
            state = "STRONG_DOWN"
        elif combined < MOM_MODERATE_DN_THRESH:
            state = "MODERATE_DOWN"
        else:
            state = "FLAT"

        return combined, state, round(ema3_slope, 1), round(ema8_slope, 1)

    # ══════════════════════════════════════════════════════════════════════
    # NEW FRAMEWORK — Assemble all three components
    # ══════════════════════════════════════════════════════════════════════

    def _cluster_regime_signals(self, df: pd.DataFrame) -> dict:
        r    = df.iloc[-1]
        spot = float(r["close"])
        atr  = float(r.get("atr14", 200))
        if atr == 0: atr = 200

        # Component 1 — Cluster Regime
        regime, base_mult, guide = self._cluster_regime(r, spot)

        # ATR danger zones
        weekly_zone   = atr * ATR_WEEKLY_MULT
        biweekly_zone = atr * ATR_BIWEEKLY_MULT

        # Component 3 — Momentum (needed for degraded moat check)
        mom_score, mom_state, ema3_slope, ema8_slope = self._momentum_score(df, atr)

        # Component 2 — Moat Count
        ema_vals = {p: float(r.get(f"ema{p}", spot)) for p in MOAT_SET}
        put_moats,  put_moat_detail  = self._count_moats_put(spot, ema_vals, atr, ema3_slope)
        call_moats, call_moat_detail = self._count_moats_call(spot, ema_vals, atr)

        # Moat labels and ATR multiples
        put_moat_label,  put_moat_mult  = moat_label_and_mult(put_moats)
        call_moat_label, call_moat_mult = moat_label_and_mult(call_moats)

        # Momentum ATR multiples
        mom_pe_mult, mom_ce_mult = MOM_MULTS.get(mom_state, (0.0, 0.0))

        # Final ATR multiples per side
        pe_total_mult = base_mult + put_moat_mult  + mom_pe_mult
        ce_total_mult = base_mult + call_moat_mult + mom_ce_mult

        # Convert to points (round to nearest 50)
        pe_dist_pts = int(round(pe_total_mult * atr / 50) * 50)
        ce_dist_pts = int(round(ce_total_mult * atr / 50) * 50)

        # EMAs in weekly/biweekly danger zones (for ATR zone display)
        put_danger_emas    = [p for p in MOAT_SET if 0 < (spot - ema_vals[p]) <= weekly_zone]
        call_danger_emas   = [p for p in MOAT_SET if 0 < (ema_vals[p] - spot) <= weekly_zone]
        put_relevant_emas  = [p for p in MOAT_SET if weekly_zone < (spot - ema_vals[p]) <= biweekly_zone]
        call_relevant_emas = [p for p in MOAT_SET if weekly_zone < (ema_vals[p] - spot) <= biweekly_zone]

        # Hard skip: INSIDE_BEAR + 0 put moats + Strong Down
        hard_skip = (regime == "INSIDE_BEAR" and put_moats == 0 and mom_state == "STRONG_DOWN")

        return {
            # ── Regime ──────────────────────────────────────────────────
            "cr_regime":       regime,
            "cr_base_mult":    base_mult,
            "cr_ic_shape":     guide["ratio"],
            "cr_size":         guide["size"],
            "cr_regime_desc":  guide["desc"],
            # ── ATR zones ────────────────────────────────────────────────
            "cr_atr":              round(atr, 1),
            "cr_weekly_zone":      round(weekly_zone, 0),
            "cr_biweekly_zone":    round(biweekly_zone, 0),
            "cr_put_danger_emas":  put_danger_emas,
            "cr_call_danger_emas": call_danger_emas,
            "cr_put_relevant_emas": put_relevant_emas,
            "cr_call_relevant_emas": call_relevant_emas,
            # ── Moat count ───────────────────────────────────────────────
            "cr_put_moats":        put_moats,
            "cr_call_moats":       call_moats,
            "cr_put_moat_label":   put_moat_label,
            "cr_call_moat_label":  call_moat_label,
            "cr_put_moat_mult":    put_moat_mult,
            "cr_call_moat_mult":   call_moat_mult,
            "cr_put_moat_detail":  put_moat_detail,
            "cr_call_moat_detail": call_moat_detail,
            # ── Momentum ─────────────────────────────────────────────────
            "cr_mom_score":    round(mom_score, 2),
            "cr_mom_state":    mom_state,
            "cr_mom_ema3_slope": ema3_slope,
            "cr_mom_ema8_slope": ema8_slope,
            "cr_mom_pe_mult":  mom_pe_mult,
            "cr_mom_ce_mult":  mom_ce_mult,
            # ── Final EMA lens distances ──────────────────────────────────
            "cr_pe_total_mult":    round(pe_total_mult, 2),
            "cr_ce_total_mult":    round(ce_total_mult, 2),
            "cr_pe_dist_pts":      pe_dist_pts,
            "cr_ce_dist_pts":      ce_dist_pts,
            # Legacy aliases kept for compute_signals compat
            "cr_final_put_dist":   pe_dist_pts,
            "cr_final_call_dist":  ce_dist_pts,
            "cr_base_put":         int(round(base_mult * atr / 50) * 50),
            "cr_base_call":        int(round(base_mult * atr / 50) * 50),
            # ── Flags ─────────────────────────────────────────────────────
            "cr_hard_skip":        hard_skip,
            "cr_ema_vals":         {p: round(v, 0) for p, v in ema_vals.items()},
        }

    # ── Used by constituent_ema.py ────────────────────────────────────────
    def stock_cluster_signals(self, df: pd.DataFrame, symbol: str) -> dict:
        if df.empty or len(df) < 30:
            return self._empty_stock_signals(symbol)
        try:
            df   = self.compute(df.copy())
            r    = df.iloc[-1]
            spot = float(r["close"])
            atr  = float(r.get("atr14", max(spot * 0.01, 1)))
            regime, base_mult, guide = self._cluster_regime(r, spot)
            ema_vals = {p: float(r.get(f"ema{p}", spot)) for p in MOAT_SET}
            mom_score, mom_state, ema3_slope, _ = self._momentum_score(df, atr)
            put_moats, put_detail  = self._count_moats_put(spot, ema_vals, atr, ema3_slope)
            call_moats, call_detail = self._count_moats_call(spot, ema_vals, atr)
            canary = self._canary_level(df)
            return {
                "symbol": symbol, "regime": regime,
                "put_moats": put_moats, "call_moats": call_moats,
                "put_moat_detail": put_detail, "call_moat_detail": call_detail,
                "mom_state": mom_state, "mom_score": round(mom_score, 2),
                "canary_level": canary["level"], "canary_day": canary["day"],
                "size": guide["size"], "atr": round(atr, 1), "spot": round(spot, 0),
            }
        except Exception:
            return self._empty_stock_signals(symbol)

    def _empty_stock_signals(self, symbol):
        return {
            "symbol": symbol, "regime": "INSIDE_BULL",
            "put_moats": 2, "call_moats": 2,
            "put_moat_detail": [], "call_moat_detail": [],
            "mom_state": "FLAT", "mom_score": 0.0,
            "canary_level": 0, "canary_day": 0,
            "size": 0.75, "atr": 0.0, "spot": 0.0,
        }
