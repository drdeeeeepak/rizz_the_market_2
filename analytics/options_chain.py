# analytics/options_chain.py — v4 (April 2026)
# Page 10: Options Chain Analysis Engine
#
# New per doc:
#   - Five strike models: 10-delta, IV expected move, ATR multiples (1x/1.5x/2x),
#     straddle breakeven, wall anchor
#   - Strike synthesis: most conservative per side is binding recommendation
#   - Section 1 four headline numbers: spot, PCR, max pain, futures premium
#   - Section 2 Greeks: magnet strike (highest gamma), theta/IV ratio, delta skew
#   - Section 3 five models + synthesis table
#   - Section 4 wall analysis: call wall, put wall, GEX flip, combined verdict
#   - CE short ABOVE call wall, PE short BELOW put wall (wall = protection beyond)
#   - GEX lot size = 65
#   - All modifiers independent

import pandas as pd
import numpy as np
from analytics.base_strategy import BaseStrategy
from config import (
    OI_STRIKE_STEP, PCR_BALANCED_LOW, PCR_BALANCED_HI,
    OI_WALL_PCT, DTE_THETA_MIN, DTE_WARN_MIN,
)

LOT_SIZE = 65

# PCR thresholds from doc
PCR_WIDEN_CE  = 0.7    # below = extreme bullish = widen CE
PCR_WIDEN_PE  = 1.3    # above = fear = widen PE

# ATR multipliers for Method 3
ATR_AGGR = 1.0
ATR_BALC = 1.5
ATR_CONS = 2.0

# Theta/IV ratio thresholds
THETA_IV_SELL   = 1.0
THETA_IV_BORDER = 0.7


class OptionsChainEngine(BaseStrategy):

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def signals(self, df: pd.DataFrame, spot: float, dte: int,
                atr14: float = 200.0, va_buf_mult: float = 0.75,
                futures_price: float = 0.0) -> dict:
        if df.empty:
            return self._empty_signals(spot)

        # ── Section 1: Headline numbers ───────────────────────────────────────
        pcr         = self._pcr(df)
        max_pain    = self._max_pain(df)
        fut_premium = futures_price - spot if futures_price > 0 else 0.0

        # ── Walls (shared across sections) ────────────────────────────────────
        call_wall   = self._oi_wall(df, "ce_oi")
        put_wall    = self._oi_wall(df, "pe_oi")
        wall_int    = self._wall_integrity(df, call_wall, put_wall)

        # ── Section 2: Greeks ─────────────────────────────────────────────────
        atm_iv      = self._atm_iv(df, spot)
        iv_skew     = self._iv_skew(df, spot)
        straddle    = self._straddle_price(df, spot)
        magnet      = self._magnet_strike(df)
        theta_iv    = self._theta_iv_ratio(df, spot)
        delta_skew  = self._delta_skew(df, spot)

        # ── Section 3: Five strike models + synthesis ─────────────────────────
        models      = self._five_models(df, spot, dte, atr14, va_buf_mult,
                                        atm_iv, straddle, call_wall, put_wall)
        synthesis   = self._strike_synthesis(models)

        # ── Section 4: Wall and GEX analysis ─────────────────────────────────
        gex         = self._gex(df, spot)
        wall_verdict = self._wall_verdict(df, call_wall, put_wall, gex)

        # ── Legacy fields (kept for compute_signals compat) ───────────────────
        migration   = self._migration_status(df, spot)
        kills       = self._kill_switches(pcr, gex, migration)
        home_score  = self._home_score(gex, pcr, migration)

        return {
            # Section 1
            "spot":           round(spot, 0),
            "dte":            dte,
            "pcr":            round(pcr, 2),
            "max_pain":       max_pain,
            "max_pain_dist":  round(abs(spot - max_pain), 0),
            "fut_premium":    round(fut_premium, 1),
            # Section 2
            "atm_iv":         round(atm_iv, 2),
            "iv_skew":        round(iv_skew, 2),
            "straddle_price": round(straddle, 2),
            "magnet_strike":  magnet,
            "theta_iv_ratio": round(theta_iv, 3),
            "delta_skew":     delta_skew,
            # Section 3
            "models":         models,
            "synthesis":      synthesis,
            # Binding strikes from synthesis
            "binding_ce":     synthesis["binding_ce"],
            "binding_pe":     synthesis["binding_pe"],
            # Section 4
            "call_wall":      call_wall,
            "put_wall":       put_wall,
            "wall_integrity": wall_int,
            "gex":            gex,
            "wall_verdict":   wall_verdict,
            # Legacy
            "migration":      migration,
            "kill_switches":  kills,
            "home_score":     home_score,
            "strategy":       "IRON_CONDOR",
        }

    # ══════════════════════════════════════════════════════════════════════════
    # Section 1 helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _pcr(self, df: pd.DataFrame) -> float:
        total_pe = df["pe_oi"].sum(); total_ce = df["ce_oi"].sum()
        return total_pe / total_ce if total_ce > 0 else 0.0

    def _max_pain(self, df: pd.DataFrame) -> float:
        """Strike minimising total intrinsic loss for option buyers."""
        if df.empty or "strike" not in df.index.name and df.index.dtype == object:
            return 0.0
        strikes = df.index.tolist()
        min_pain, pain_strike = float("inf"), 0
        for s in strikes:
            pain = (df.loc[df.index < s, "ce_oi"] * (s - df.index[df.index < s])).sum()
            pain += (df.loc[df.index > s, "pe_oi"] * (df.index[df.index > s] - s)).sum()
            if pain < min_pain:
                min_pain, pain_strike = pain, s
        return float(pain_strike)

    def _straddle_price(self, df: pd.DataFrame, spot: float) -> float:
        atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
        if atm in df.index:
            return float(df.loc[atm, "ce_ltp"]) + float(df.loc[atm, "pe_ltp"])
        return 0.0

    def _atm_iv(self, df: pd.DataFrame, spot: float) -> float:
        atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
        if atm in df.index:
            ce_iv = float(df.loc[atm, "ce_iv"])
            pe_iv = float(df.loc[atm, "pe_iv"])
            return (ce_iv + pe_iv) / 2 if ce_iv > 0 and pe_iv > 0 else max(ce_iv, pe_iv)
        return 12.0

    def _iv_skew(self, df: pd.DataFrame, spot: float) -> float:
        atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
        if atm in df.index:
            return float(df.loc[atm, "pe_iv"]) - float(df.loc[atm, "ce_iv"])
        return 0.0

    # ══════════════════════════════════════════════════════════════════════════
    # Section 2: Greeks helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _magnet_strike(self, df: pd.DataFrame) -> int:
        """Strike with highest gamma = dealer hedging hotspot."""
        if "ce_gamma" not in df.columns and "pe_gamma" not in df.columns:
            return 0
        gamma_col = "ce_gamma" if "ce_gamma" in df.columns else "pe_gamma"
        try:
            return int(df[gamma_col].abs().idxmax())
        except Exception:
            return 0

    def _theta_iv_ratio(self, df: pd.DataFrame, spot: float) -> float:
        """ATM Theta / IV ratio. Above 1.0 = seller's market."""
        atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
        if atm not in df.index:
            return 0.0
        theta_col = "ce_theta" if "ce_theta" in df.columns else None
        iv = self._atm_iv(df, spot)
        if theta_col and iv > 0:
            theta = abs(float(df.loc[atm, theta_col]))
            return theta / iv
        # Approximate: straddle theta ~ straddle price / DTE
        return 0.0

    def _delta_skew(self, df: pd.DataFrame, spot: float) -> str:
        """Compare put delta vs call delta at ±100 from ATM."""
        atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
        strike_plus  = atm + 100
        strike_minus = atm - 100
        ce_col = "ce_delta" if "ce_delta" in df.columns else None
        pe_col = "pe_delta" if "pe_delta" in df.columns else None
        if ce_col and pe_col:
            if strike_plus in df.index and strike_minus in df.index:
                call_d = abs(float(df.loc[strike_plus,  ce_col]))
                put_d  = abs(float(df.loc[strike_minus, pe_col]))
                if put_d > call_d * 1.1:   return "PUT_SKEW"    # downside feared
                if call_d > put_d * 1.1:   return "CALL_SKEW"   # upside squeeze
        return "BALANCED"

    # ══════════════════════════════════════════════════════════════════════════
    # Section 3: Five strike models
    # ══════════════════════════════════════════════════════════════════════════

    def _five_models(self, df, spot, dte, atr14, va_buf_mult,
                     atm_iv, straddle, call_wall, put_wall) -> dict:
        """Compute all five models. Returns dict with CE and PE for each."""

        # Method 1 — 10 delta
        ce_10d, pe_10d = self._ten_delta_strikes(df, spot)

        # Method 2 — IV expected move
        if atm_iv > 0 and dte > 0:
            exp_move = spot * (atm_iv / 100) * np.sqrt(dte / 365)
            ce_iv    = round((spot + exp_move) / 50) * 50
            pe_iv    = round((spot - exp_move) / 50) * 50
        else:
            ce_iv = pe_iv = 0

        # Method 3 — ATR multiples (three variants)
        ce_atr1  = round((spot + ATR_AGGR * atr14) / 50) * 50
        pe_atr1  = round((spot - ATR_AGGR * atr14) / 50) * 50
        ce_atr15 = round((spot + ATR_BALC * atr14) / 50) * 50
        pe_atr15 = round((spot - ATR_BALC * atr14) / 50) * 50
        ce_atr2  = round((spot + ATR_CONS * atr14) / 50) * 50
        pe_atr2  = round((spot - ATR_CONS * atr14) / 50) * 50

        # Method 4 — Straddle breakeven
        atm = round(spot / 50) * 50
        if straddle > 0:
            ce_str = atm + round(straddle / 50) * 50
            pe_str = atm - round(straddle / 50) * 50
        else:
            ce_str = pe_str = 0

        # Method 5 — Wall anchor
        buf_pts  = round(va_buf_mult * atr14 / 50) * 50
        ce_wall_a = int(call_wall) + buf_pts if call_wall > 0 else 0
        pe_wall_a = int(put_wall)  - buf_pts if put_wall  > 0 else 0

        return {
            "10_delta":    {"ce": int(ce_10d), "pe": int(pe_10d),
                             "note": "10% probability ITM — institutional benchmark"},
            "iv_exp_move": {"ce": int(ce_iv),  "pe": int(pe_iv),
                             "note": f"1SD expected move = ±{round(ce_iv-spot):,} pts"},
            "atr_1x":      {"ce": int(ce_atr1), "pe": int(pe_atr1),
                             "note": "Aggressive — highest premium, highest risk"},
            "atr_1.5x":    {"ce": int(ce_atr15),"pe": int(pe_atr15),
                             "note": "Balanced — most common choice"},
            "atr_2x":      {"ce": int(ce_atr2), "pe": int(pe_atr2),
                             "note": "Conservative — use when VIX elevated"},
            "straddle":    {"ce": int(ce_str),  "pe": int(pe_str),
                             "note": f"Market maker implied move = ±{round(straddle):,} pts"},
            "wall_anchor": {"ce": int(ce_wall_a),"pe": int(pe_wall_a),
                             "note": f"Call wall + {buf_pts:,} pts ATR buffer"},
        }

    def _ten_delta_strikes(self, df: pd.DataFrame, spot: float) -> tuple:
        """Find strikes closest to 10 delta for CE and -10 delta for PE."""
        ce_delta_col = "ce_delta" if "ce_delta" in df.columns else None
        pe_delta_col = "pe_delta" if "pe_delta" in df.columns else None

        if ce_delta_col and pe_delta_col:
            otm_ce = df[df.index > spot]
            otm_pe = df[df.index < spot]
            if not otm_ce.empty:
                ce_strike = int(abs(otm_ce[ce_delta_col] - 0.10).idxmin())
            else:
                ce_strike = round((spot + 1.5 * 200) / 50) * 50  # fallback
            if not otm_pe.empty:
                pe_strike = int(abs(otm_pe[pe_delta_col].abs() - 0.10).idxmin())
            else:
                pe_strike = round((spot - 1.5 * 200) / 50) * 50
        else:
            # Fallback: use straddle IV to approximate 10 delta strike
            ce_strike = round((spot * 1.065) / 50) * 50
            pe_strike = round((spot * 0.935) / 50) * 50
        return ce_strike, pe_strike

    def _strike_synthesis(self, models: dict) -> dict:
        """
        Most conservative (furthest from spot) CE = MAX.
        Most conservative PE = MIN.
        Also note distance from each binding strike to the wall.
        """
        ce_vals = [m["ce"] for m in models.values() if m["ce"] > 0]
        pe_vals = [m["pe"] for m in models.values() if m["pe"] > 0]

        binding_ce = max(ce_vals) if ce_vals else 0
        binding_pe = min(pe_vals) if pe_vals else 0

        # Which model drove the binding recommendation
        binding_ce_model = next(
            (k for k, m in models.items() if m["ce"] == binding_ce), "—"
        )
        binding_pe_model = next(
            (k for k, m in models.items() if m["pe"] == binding_pe), "—"
        )

        return {
            "binding_ce":        binding_ce,
            "binding_pe":        binding_pe,
            "binding_ce_model":  binding_ce_model,
            "binding_pe_model":  binding_pe_model,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # Section 4: Wall and GEX analysis
    # ══════════════════════════════════════════════════════════════════════════

    def _oi_wall(self, df: pd.DataFrame, col: str) -> int:
        if col not in df.columns or df.empty:
            return 0
        return int(df[col].idxmax())

    def _wall_integrity(self, df: pd.DataFrame, call_wall: int, put_wall: int) -> dict:
        """75% rule: if 2nd highest / highest >= 75% = FRAGMENTED."""
        def integrity(col, wall_strike):
            if col not in df.columns or wall_strike not in df.index:
                return "SOLID"
            sorted_oi = df[col].nlargest(2)
            if len(sorted_oi) < 2:
                return "SOLID"
            ratio = sorted_oi.iloc[1] / sorted_oi.iloc[0]
            return "FRAGMENTED" if ratio >= 0.75 else "SOLID"
        return {
            "call_integrity": integrity("ce_oi", call_wall),
            "put_integrity":  integrity("pe_oi", put_wall),
        }

    def _gex(self, df: pd.DataFrame, spot: float) -> dict:
        """GEX = Σ(Call OI × Call Gamma × 65 × Spot) - Σ(Put OI × Put Gamma × 65 × Spot)."""
        total_gex = 0.0; flip_level = 0
        if "ce_gamma" not in df.columns or "pe_gamma" not in df.columns:
            return {"total_gex": 0, "flip_level": 0, "gex_per_strike": {}}

        gex_per = {}
        cum_gex_sorted = []
        for strike in df.index:
            ce_g = float(df.loc[strike, "ce_gamma"]) if "ce_gamma" in df.columns else 0
            pe_g = float(df.loc[strike, "pe_gamma"]) if "pe_gamma" in df.columns else 0
            ce_oi = float(df.loc[strike, "ce_oi"])
            pe_oi = float(df.loc[strike, "pe_oi"])
            g = (ce_oi * ce_g - pe_oi * pe_g) * LOT_SIZE * spot
            gex_per[strike] = round(g, 0)
            total_gex += g
            cum_gex_sorted.append((strike, total_gex))

        # Flip level: strike where cumulative GEX crosses zero going upward
        for i in range(1, len(cum_gex_sorted)):
            if cum_gex_sorted[i-1][1] >= 0 > cum_gex_sorted[i][1]:
                flip_level = cum_gex_sorted[i][0]
                break

        return {
            "total_gex":    round(total_gex, 0),
            "flip_level":   flip_level,
            "positive":     total_gex > 0,
            "gex_per_strike": gex_per,
        }

    def _wall_verdict(self, df: pd.DataFrame, call_wall: int,
                      put_wall: int, gex: dict) -> dict:
        """Combined wall + GEX directional statement."""
        flip = gex.get("flip_level", 0)
        total_gex = gex.get("total_gex", 0)

        # GEX flip vs wall relationship
        if flip and call_wall:
            if abs(flip - call_wall) <= 50:
                ce_gex_rel = "DOUBLE_BARRIER"
            elif flip < call_wall:
                ce_gex_rel = "GAP_DANGER"     # amplification zone before wall
            else:
                ce_gex_rel = "FLIP_BEYOND"
        else:
            ce_gex_rel = "UNKNOWN"

        if total_gex > 0:
            gex_env = "PINNING"
        elif total_gex < 0:
            gex_env = "AMPLIFYING"
        else:
            gex_env = "NEUTRAL"

        # Combined statement
        if ce_gex_rel == "DOUBLE_BARRIER" and gex_env == "PINNING":
            combined = "MAXIMUM_RANGE_CONFIDENCE"
        elif gex_env == "AMPLIFYING" and ce_gex_rel == "GAP_DANGER":
            combined = "BOTH_LEGS_ELEVATED_RISK"
        elif gex_env == "PINNING":
            combined = "RANGE_FAVOURABLE"
        else:
            combined = "STANDARD"

        return {
            "ce_gex_relationship": ce_gex_rel,
            "gex_environment":     gex_env,
            "combined_verdict":    combined,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # Legacy helpers (kept for compute_signals compat)
    # ══════════════════════════════════════════════════════════════════════════

    def _migration_status(self, df: pd.DataFrame, spot: float) -> dict:
        """OI migration proxy."""
        try:
            atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
            above_sum = df.loc[df.index > atm, "ce_oi_change"].sum()
            below_sum = df.loc[df.index < atm, "pe_oi_change"].sum()
            detected  = abs(above_sum) > 500_000 or abs(below_sum) > 500_000
            return {"detected": detected, "above": above_sum, "below": below_sum}
        except Exception:
            return {"detected": False, "above": 0, "below": 0}

    def _kill_switches(self, pcr: float, gex: dict, migration: dict) -> dict:
        return {
            "migration_detected": migration.get("detected", False),
            "gex_negative":       gex.get("total_gex", 0) < 0,
            "pcr_extreme":        pcr < 0.5 or pcr > 2.0,
        }

    def _home_score(self, gex: dict, pcr: float, migration: dict) -> int:
        if migration.get("detected"): return 0
        score = 10
        if gex.get("positive"): score += 5
        if PCR_BALANCED_LOW <= pcr <= PCR_BALANCED_HI: score += 5
        return min(score, 20)

    def _empty_signals(self, spot: float = 23000) -> dict:
        return {
            "spot": spot, "dte": 0, "pcr": 1.0, "max_pain": spot,
            "max_pain_dist": 0, "fut_premium": 0.0,
            "atm_iv": 12.0, "iv_skew": 0.0, "straddle_price": 0.0,
            "magnet_strike": 0, "theta_iv_ratio": 0.0, "delta_skew": "BALANCED",
            "models": {}, "synthesis": {"binding_ce": 0, "binding_pe": 0,
                                         "binding_ce_model": "—", "binding_pe_model": "—"},
            "binding_ce": 0, "binding_pe": 0,
            "call_wall": 0, "put_wall": 0,
            "wall_integrity": {"call_integrity": "SOLID", "put_integrity": "SOLID"},
            "gex": {"total_gex": 0, "flip_level": 0, "positive": False},
            "wall_verdict": {"combined_verdict": "STANDARD"},
            "migration": {"detected": False}, "kill_switches": {}, "home_score": 10,
            "strategy": "IRON_CONDOR",
        }
