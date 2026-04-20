# analytics/market_profile.py — v4 (April 2026)
# Page 12: Market Profile Engine — Volume Profile Edition
#
# Key changes from v3 (TPO-based):
#   - Volume Profile from daily OHLCV proxy (5-min Kite data handled in live_fetcher)
#   - Wednesday–Tuesday weekly cycle (synchronised with IC expiry cycle)
#   - VA Width Ratio → ATR-scaled buffer (inverse: narrow VA = larger buffer)
#   - Biweekly tinge: DTE expansion via √(biweekly_DTE/near_DTE) + Net Skew ±0.25×ATR14
#   - 5 nesting states: BALANCED, TESTING_UPPER, TESTING_LOWER, INITIATIVE_UPPER, INITIATIVE_LOWER
#   - 3 price behaviour states: RESPONSIVE, INITIATIVE, NEUTRAL
#   - 6 day types: NORMAL, TREND_DAY, DOUBLE_DISTRIBUTION, P_SHAPE, b_SHAPE, NEUTRAL_EXTREME
#   - Wed–Tue cycle guide: DTE-specific actions per day
#   - POC migration thresholds: <100=stable, 100-300=mild, 300+=review
#   - No hard kill switches — all advisory (consistent with doc)

import pandas as pd
import numpy as np
from datetime import date, timedelta
from analytics.base_strategy import BaseStrategy

BUCKET       = 50      # price bucket size in points
VA_PCT       = 0.70    # 70% value area

# VA Width Ratio → buffer multiplier (inverse relationship)
VA_RATIO_NARROW  = 0.8   # below = coiled spring → 1.0×ATR buffer
VA_RATIO_NORMAL  = 1.5   # 0.8-1.5 = normal → 0.75×ATR
VA_RATIO_WIDE    = 1.5   # above = wide → 0.5×ATR

# Net Skew tinge threshold
NET_SKEW_NEUTRAL = 30   # within ±30 = symmetric, no extra tinge

# POC migration thresholds
POC_STABLE  = 100
POC_MILD    = 300


class MarketProfileEngine(BaseStrategy):

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def signals(self, df: pd.DataFrame, spot: float,
                near_dte: int = 7, far_dte: int = 14,
                net_skew: float = 0.0, atr14: float = 200.0) -> dict:
        if df.empty:
            return self._empty_signals(spot)

        # Wed–Tue weekly window
        weekly_df  = self._weekly_window(df)
        daily_df   = df.tail(1)   # today only

        weekly_va  = self._value_area(weekly_df)
        daily_va   = self._value_area(daily_df)

        nesting    = self._nesting_state(weekly_va, daily_va, spot)
        behaviour  = self._price_behaviour(df, weekly_va, spot)
        day_type   = self._day_type(df, spot)
        poc_mig    = self._poc_migration(weekly_va["poc"], spot)
        cycle_day  = self._cycle_day()

        # VA width ratio and ATR-scaled buffer
        va_width   = weekly_va["vah"] - weekly_va["val"]
        va_ratio   = va_width / atr14 if atr14 > 0 else 1.0
        if   va_ratio < VA_RATIO_NARROW: buf_mult = 1.00
        elif va_ratio < VA_RATIO_WIDE:   buf_mult = 0.75
        else:                            buf_mult = 0.50
        buffer_pts = round(buf_mult * atr14 / 50) * 50

        # Step 1: nearest expiry safe anchors
        ce_near = weekly_va["vah"] + buffer_pts
        pe_near = weekly_va["val"] - buffer_pts

        # Step 2: biweekly tinge (DTE expansion + Net Skew)
        dte_factor = self._dte_factor(near_dte, far_dte)
        ce_biwkly  = round((ce_near - spot) * dte_factor / 50) * 50
        pe_biwkly  = round((spot - pe_near) * dte_factor / 50) * 50

        # Net Skew tinge: ±0.25×ATR14 on the vulnerable side
        skew_adj = round(0.25 * atr14 / 50) * 50
        if net_skew > NET_SKEW_NEUTRAL:    # bullish → PE needs extra room
            pe_biwkly  += skew_adj
        elif net_skew < -NET_SKEW_NEUTRAL: # bearish → CE needs extra room
            ce_biwkly  += skew_adj

        ce_anchor = spot + ce_biwkly
        pe_anchor = spot - pe_biwkly

        # Combined alert state
        initiative_both = (nesting in ("INITIATIVE_UPPER", "INITIATIVE_LOWER") and
                           behaviour == "INITIATIVE")

        home_score = self._home_score(nesting, behaviour, initiative_both)

        return {
            # Weekly VA
            "weekly_vah":   round(weekly_va["vah"], 0),
            "weekly_val":   round(weekly_va["val"], 0),
            "weekly_poc":   round(weekly_va["poc"], 0),
            "weekly_va_width": round(va_width, 0),
            # Daily VA
            "daily_vah":    round(daily_va["vah"], 0),
            "daily_val":    round(daily_va["val"], 0),
            "daily_poc":    round(daily_va["poc"], 0),
            # VA Width analysis
            "va_ratio":     round(va_ratio, 2),
            "buffer_pts":   int(buffer_pts),
            "buf_mult":     buf_mult,
            # Nesting and behaviour
            "nesting_state":   nesting,
            "price_behaviour": behaviour,
            "responsive":      behaviour == "RESPONSIVE",
            "initiative_both": initiative_both,
            # Day type and cycle
            "day_type":        day_type,
            "cycle_day":       cycle_day,
            "cycle_action":    self._cycle_action(cycle_day),
            # Biweekly tinge
            "dte_factor":      round(dte_factor, 3),
            "ce_biwkly_dist":  int(ce_biwkly),
            "pe_biwkly_dist":  int(pe_biwkly),
            "ce_strike_anchor":round(ce_anchor / 50) * 50,
            "pe_strike_anchor":round(pe_anchor / 50) * 50,
            # POC migration
            "poc_migration":   poc_mig,
            # Kill switches (advisory only)
            "kill_switches": {
                "INITIATIVE_BOTH": initiative_both,
                "MP_K1": initiative_both,
                # Legacy
                "MP_K2": day_type == "TREND_DAY",
            },
            "mp_kills":     {"INITIATIVE_BOTH": initiative_both},
            "home_score":   home_score,
        }

    # ── Volume Profile / Value Area ───────────────────────────────────────────

    def _value_area(self, df: pd.DataFrame) -> dict:
        if df.empty:
            return {"poc": 0, "vah": 0, "val": 0, "vol_at_poc": 0}

        low_all  = df["low"].min()
        high_all = df["high"].max()
        if low_all >= high_all:
            mid = float(df["close"].iloc[-1])
            return {"poc": mid, "vah": mid + 100, "val": mid - 100, "vol_at_poc": 0}

        buckets   = np.arange(
            int(low_all // BUCKET) * BUCKET,
            int(high_all // BUCKET) * BUCKET + BUCKET * 2,
            BUCKET
        )
        vol_hist  = np.zeros(len(buckets))

        for _, row in df.iterrows():
            vol   = max(float(row.get("volume", 0)), 1)
            lo    = float(row["low"])
            hi    = float(row["high"])
            span  = hi - lo
            for i, b in enumerate(buckets):
                overlap = min(b + BUCKET, hi) - max(b, lo)
                if overlap > 0:
                    vol_hist[i] += vol * (overlap / span)

        total_vol = vol_hist.sum()
        poc_idx   = int(np.argmax(vol_hist))
        poc       = float(buckets[poc_idx])

        # Expand 70% VA symmetrically from POC
        va_vol    = vol_hist[poc_idx]
        lo_idx, hi_idx = poc_idx, poc_idx
        while va_vol < VA_PCT * total_vol:
            add_hi  = vol_hist[hi_idx + 1] if hi_idx + 1 < len(buckets) else 0
            add_lo  = vol_hist[lo_idx - 1] if lo_idx - 1 >= 0 else 0
            if add_hi >= add_lo and hi_idx + 1 < len(buckets):
                hi_idx += 1; va_vol += vol_hist[hi_idx]
            elif lo_idx - 1 >= 0:
                lo_idx -= 1; va_vol += vol_hist[lo_idx]
            else:
                break

        return {
            "poc":        poc,
            "vah":        float(buckets[hi_idx] + BUCKET),
            "val":        float(buckets[lo_idx]),
            "vol_at_poc": float(vol_hist[poc_idx]),
        }

    def _weekly_window(self, df: pd.DataFrame) -> pd.DataFrame:
        """Slice Wed–Tue window from df index."""
        if df.empty:
            return df
        today = date.today()
        # Find last Wednesday
        days_since_wed = (today.weekday() - 2) % 7   # Wed=2
        last_wed = today - timedelta(days=days_since_wed)
        start    = pd.Timestamp(last_wed)
        window   = df[df.index >= start]
        return window if not window.empty else df.tail(5)

    # ── Nesting ───────────────────────────────────────────────────────────────

    def _nesting_state(self, weekly: dict, daily: dict, spot: float) -> str:
        wvah, wval = weekly["vah"], weekly["val"]
        dvah, dval = daily["vah"],  daily["val"]

        if dvah == 0 or dval == 0:
            return "BALANCED"

        daily_inside = dval >= wval and dvah <= wvah
        if daily_inside:
            return "BALANCED"

        overlap_top    = dvah > wvah and dval < wvah   # daily VA overlapping top
        overlap_bottom = dval < wval and dvah > wval   # daily VA overlapping bottom
        daily_above    = dval >= wvah                  # daily VA fully above weekly
        daily_below    = dvah <= wval                  # daily VA fully below weekly

        if daily_above:    return "INITIATIVE_UPPER"
        if daily_below:    return "INITIATIVE_LOWER"
        if overlap_top:    return "TESTING_UPPER"
        if overlap_bottom: return "TESTING_LOWER"
        return "BALANCED"

    # ── Price behaviour ───────────────────────────────────────────────────────

    def _price_behaviour(self, df: pd.DataFrame, weekly: dict, spot: float) -> str:
        if df.empty or len(df) < 2:
            return "NEUTRAL"
        wvah, wval = weekly["vah"], weekly["val"]
        last  = df.iloc[-1]
        prev  = df.iloc[-2]

        tested_vah = last["high"] >= wvah or prev["high"] >= wvah
        tested_val = last["low"]  <= wval or prev["low"]  <= wval
        close_inside = wval <= float(last["close"]) <= wvah

        if (tested_vah or tested_val) and close_inside:
            return "RESPONSIVE"
        if not close_inside:
            return "INITIATIVE"
        return "NEUTRAL"

    # ── Day type ──────────────────────────────────────────────────────────────

    def _day_type(self, df: pd.DataFrame, spot: float) -> str:
        if df.empty:
            return "NORMAL"
        last      = df.iloc[-1]
        day_range = float(last["high"]) - float(last["low"])
        if day_range <= 0:
            return "NORMAL"

        open_  = float(last["open"])
        close_ = float(last["close"])
        body   = abs(close_ - open_)
        pct_b  = (close_ - float(last["low"])) / day_range

        # Trend day: body > 60% of range, strong directional close
        if body > 0.60 * day_range and (pct_b > 0.80 or pct_b < 0.20):
            return "TREND_DAY"

        # P-shape: strong early rally, closes near bottom (buying climax)
        upper_wick = float(last["high"]) - max(open_, close_)
        lower_wick = min(open_, close_)  - float(last["low"])
        if upper_wick > 0.35 * day_range and pct_b < 0.35:
            return "P_SHAPE"

        # b-shape: strong early drop, closes near top (selling climax)
        if lower_wick > 0.35 * day_range and pct_b > 0.65:
            return "b_SHAPE"

        # Neutral extreme: large range, closes near middle
        if day_range > spot * 0.02 and 0.35 < pct_b < 0.65:
            return "NEUTRAL_EXTREME"

        # Double distribution: price action in two distinct zones
        # Approximate: open and close in different quartiles with a middle gap
        open_pct  = (open_  - float(last["low"])) / day_range
        close_pct = (close_ - float(last["low"])) / day_range
        if abs(open_pct - close_pct) > 0.50 and min(open_pct, close_pct) < 0.30 and max(open_pct, close_pct) > 0.70:
            return "DOUBLE_DISTRIBUTION"

        return "NORMAL"

    # ── DTE factor ────────────────────────────────────────────────────────────

    def _dte_factor(self, near_dte: int, far_dte: int) -> float:
        """Biweekly distance = nearest × √(far_DTE / near_DTE)."""
        if near_dte <= 0:
            return 1.0
        return float(np.sqrt(far_dte / near_dte))

    # ── POC migration ─────────────────────────────────────────────────────────

    def _poc_migration(self, poc: float, spot: float) -> dict:
        dist = abs(poc - spot)
        if dist < POC_STABLE:
            label = "STABLE"
            action = "No action — hold with confidence"
        elif dist < POC_MILD:
            direction = "UPWARD" if poc > spot else "DOWNWARD"
            label = f"MILD_{direction}"
            action = ("CE side mild pressure — confirm with nesting" if poc > spot
                      else "PE side mild pressure — confirm with nesting")
        else:
            direction = "UPWARD" if poc > spot else "DOWNWARD"
            label = f"STRONG_{direction}"
            action = ("CE leg review — check if CE short near new value area" if poc > spot
                      else "PE leg review — check if PE short near new value area")
        return {"distance": round(dist, 0), "label": label, "action": action}

    # ── Wed–Tue cycle day ─────────────────────────────────────────────────────

    def _cycle_day(self) -> str:
        wd = date.today().weekday()   # Mon=0 … Sun=6
        return {0: "Monday", 1: "Tuesday", 2: "Wednesday",
                3: "Thursday", 4: "Friday"}.get(wd, "Weekend")

    def _cycle_action(self, cycle_day: str) -> str:
        actions = {
            "Wednesday": "OBSERVE ONLY — Never enter on Wednesday. Use last completed cycle VA as reference.",
            "Thursday":  "PRIME ENTRY — Enter before 11 AM. Check BALANCED nesting + RESPONSIVE behaviour. Dual boundary MAX wins.",
            "Friday":    "FOLLOW THURSDAY BIAS — No new entries. Hold if nesting BALANCED. Assess distance vs moats if TESTING.",
            "Monday":    "GAP CHECK CRITICAL — Re-run all engines at 9:15 AM. Gap inside VA = hold. Gap outside + INITIATIVE = assess immediately.",
            "Tuesday":   "EXPIRY DAY — No new positions. Close profitable legs by 12 PM. If either strike within 200 pts at 12 PM — exit full position.",
            "Weekend":   "Market closed — review weekly VA levels for Thursday entry preparation.",
        }
        return actions.get(cycle_day, "")

    # ── Home score ────────────────────────────────────────────────────────────

    def _home_score(self, nesting: str, behaviour: str, initiative_both: bool) -> int:
        if initiative_both:
            return 0
        base = {
            "BALANCED":         20,
            "TESTING_UPPER":    12,
            "TESTING_LOWER":    12,
            "INITIATIVE_UPPER": 5,
            "INITIATIVE_LOWER": 5,
        }.get(nesting, 10)
        if behaviour == "RESPONSIVE": base += 3
        if behaviour == "INITIATIVE": base -= 5
        return max(0, min(base, 20))

    # ── Market state label ────────────────────────────────────────────────────

    def _market_state(self, nesting: str) -> str:
        return {
            "BALANCED":         "Value Contained — IC Optimal",
            "TESTING_UPPER":    "Testing Upper Boundary — CE Watch",
            "TESTING_LOWER":    "Testing Lower Boundary — PE Watch",
            "INITIATIVE_UPPER": "Initiative Upper — CE Threatened",
            "INITIATIVE_LOWER": "Initiative Lower — PE Threatened",
        }.get(nesting, "Unknown")

    def round_strike(self, price: float, direction: str = "round") -> int:
        if direction == "ceil":  return int(np.ceil(price / 50)) * 50
        if direction == "floor": return int(np.floor(price / 50)) * 50
        return int(round(price / 50)) * 50

    def _empty_signals(self, spot: float = 23000) -> dict:
        return {
            "weekly_vah": spot + 300, "weekly_val": spot - 300, "weekly_poc": spot,
            "weekly_va_width": 600, "daily_vah": spot + 150, "daily_val": spot - 150,
            "daily_poc": spot, "va_ratio": 1.0, "buffer_pts": 150, "buf_mult": 0.75,
            "nesting_state": "BALANCED", "price_behaviour": "NEUTRAL",
            "responsive": True, "initiative_both": False,
            "day_type": "NORMAL", "cycle_day": self._cycle_day(),
            "cycle_action": self._cycle_action(self._cycle_day()),
            "dte_factor": 1.0, "ce_biwkly_dist": 400, "pe_biwkly_dist": 400,
            "ce_strike_anchor": spot + 400, "pe_strike_anchor": spot - 400,
            "poc_migration": {"distance": 0, "label": "STABLE", "action": "No action"},
            "kill_switches": {"INITIATIVE_BOTH": False, "MP_K1": False, "MP_K2": False},
            "mp_kills": {"INITIATIVE_BOTH": False},
            "home_score": 12,
        }
