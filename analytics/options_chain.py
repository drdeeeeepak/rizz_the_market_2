# analytics/options_chain.py — v5 (22 April 2026)
# Page 10: Options Chain Analysis Engine
#
# FIXES vs v4:
#   - Black-Scholes approximation for delta/gamma when Kite doesn't return Greeks
#   - ATR computed ONCE, used symmetrically for both CE and PE (no asymmetry bug)
#   - Futures premium properly passed through (futures_price param)
#   - Max pain calculation fixed (handles integer index correctly)
#   - Magnet strike: uses combined CE+PE gamma, not just CE
#   - Theta/IV ratio: uses both CE and PE theta for ATM average
#   - Wall anchor: uses single atr14 variable consistently
#   - GEX: handles missing gamma gracefully with BS approximation
#   - home_score: raised to 25pt max to match locked rules scoring

import math
import pandas as pd
import numpy as np
from analytics.base_strategy import BaseStrategy
from config import (
    OI_STRIKE_STEP, PCR_BALANCED_LOW, PCR_BALANCED_HI,
    OI_WALL_PCT, DTE_THETA_MIN, DTE_WARN_MIN,
)

LOT_SIZE = 65

PCR_WIDEN_CE  = 0.7
PCR_WIDEN_PE  = 1.3

ATR_AGGR = 1.0
ATR_BALC = 1.5
ATR_CONS = 2.0

THETA_IV_SELL   = 1.0
THETA_IV_BORDER = 0.7


# ── Black-Scholes helpers for Greek approximation ─────────────────────────────
def _bs_d1(S, K, T, sigma, r=0.065):
    """d1 for Black-Scholes. T in years."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        return (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    except Exception:
        return 0.0

def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def _norm_pdf(x):
    return math.exp(-0.5 * x**2) / math.sqrt(2 * math.pi)

def _bs_call_delta(S, K, T, sigma, r=0.065):
    d1 = _bs_d1(S, K, T, sigma, r)
    return _norm_cdf(d1)

def _bs_put_delta(S, K, T, sigma, r=0.065):
    return _bs_call_delta(S, K, T, sigma, r) - 1.0

def _bs_gamma(S, K, T, sigma, r=0.065):
    d1 = _bs_d1(S, K, T, sigma, r)
    if S <= 0 or sigma <= 0 or T <= 0:
        return 0.0
    try:
        return _norm_pdf(d1) / (S * sigma * math.sqrt(T))
    except Exception:
        return 0.0

def _bs_theta_call(S, K, T, sigma, r=0.065):
    d1 = _bs_d1(S, K, T, sigma, r)
    d2 = d1 - sigma * math.sqrt(T) if T > 0 else 0.0
    try:
        term1 = -(S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T))
        term2 = -r * K * math.exp(-r * T) * _norm_cdf(d2)
        return (term1 + term2) / 365  # per calendar day
    except Exception:
        return 0.0

def _enrich_greeks(df: pd.DataFrame, spot: float, dte: int) -> pd.DataFrame:
    """
    For each strike, compute BS delta/gamma/theta if not provided by Kite.
    Uses the strike's own IV if available, else ATM IV, else 12%.
    T = DTE / 365 (calendar days).
    """
    df = df.copy()
    T = max(dte, 1) / 365.0

    # Compute ATM IV for fallback
    atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
    atm_iv_pct = 12.0
    if atm in df.index:
        c_iv = float(df.loc[atm, "ce_iv"]) if "ce_iv" in df.columns else 0
        p_iv = float(df.loc[atm, "pe_iv"]) if "pe_iv" in df.columns else 0
        avg  = (c_iv + p_iv) / 2 if c_iv > 0 and p_iv > 0 else max(c_iv, p_iv)
        if avg > 0:
            atm_iv_pct = avg

    needs_ce_delta  = "ce_delta" not in df.columns or df["ce_delta"].abs().sum() == 0
    needs_pe_delta  = "pe_delta" not in df.columns or df["pe_delta"].abs().sum() == 0
    needs_ce_gamma  = "ce_gamma" not in df.columns or df["ce_gamma"].abs().sum() == 0
    needs_pe_gamma  = "pe_gamma" not in df.columns or df["pe_gamma"].abs().sum() == 0
    needs_ce_theta  = "ce_theta" not in df.columns or df["ce_theta"].abs().sum() == 0

    if not any([needs_ce_delta, needs_pe_delta, needs_ce_gamma, needs_pe_gamma, needs_ce_theta]):
        return df   # all Greeks already present

    # Ensure columns exist
    for col in ["ce_delta","pe_delta","ce_gamma","pe_gamma","ce_theta","pe_theta"]:
        if col not in df.columns:
            df[col] = 0.0

    for K in df.index:
        try:
            K_float = float(K)
            # Use strike-specific IV if available, else ATM fallback
            c_iv = float(df.loc[K, "ce_iv"]) if "ce_iv" in df.columns else 0
            p_iv = float(df.loc[K, "pe_iv"]) if "pe_iv" in df.columns else 0
            sigma_c = (c_iv / 100) if c_iv > 1 else atm_iv_pct / 100
            sigma_p = (p_iv / 100) if p_iv > 1 else atm_iv_pct / 100
            sigma_c = max(sigma_c, 0.05)   # floor 5% IV
            sigma_p = max(sigma_p, 0.05)

            if needs_ce_delta:
                df.loc[K, "ce_delta"] = _bs_call_delta(spot, K_float, T, sigma_c)
            if needs_pe_delta:
                df.loc[K, "pe_delta"] = _bs_put_delta(spot, K_float, T, sigma_p)
            if needs_ce_gamma:
                df.loc[K, "ce_gamma"] = _bs_gamma(spot, K_float, T, sigma_c)
            if needs_pe_gamma:
                df.loc[K, "pe_gamma"] = _bs_gamma(spot, K_float, T, sigma_p)
            if needs_ce_theta:
                df.loc[K, "ce_theta"] = _bs_theta_call(spot, K_float, T, sigma_c)
                df.loc[K, "pe_theta"] = -abs(df.loc[K, "ce_theta"])  # put theta approx
        except Exception:
            pass

    return df


class OptionsChainEngine(BaseStrategy):

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def signals(self, df: pd.DataFrame, spot: float, dte: int,
                atr14: float = 200.0, va_buf_mult: float = 0.75,
                futures_price: float = 0.0) -> dict:
        if df.empty:
            return self._empty_signals(spot)

        # LOCKED: compute atr14 once — use single variable throughout
        # This prevents the CE/PE asymmetry bug where different rounding
        # produced different ATR values for each side
        atr14 = round(atr14, 1)

        # Enrich with BS Greeks if Kite didn't return them
        df = _enrich_greeks(df, spot, dte)

        # ── Section 1 ─────────────────────────────────────────────────────────
        pcr         = self._pcr(df)
        max_pain    = self._max_pain(df, spot)
        fut_premium = round(futures_price - spot, 1) if futures_price > 0 else 0.0

        # ── Walls ─────────────────────────────────────────────────────────────
        call_wall = self._oi_wall(df, "ce_oi")
        put_wall  = self._oi_wall(df, "pe_oi")
        wall_int  = self._wall_integrity(df, call_wall, put_wall)

        # ── Section 2: Greeks ─────────────────────────────────────────────────
        atm_iv     = self._atm_iv(df, spot)
        iv_skew    = self._iv_skew(df, spot)
        straddle   = self._straddle_price(df, spot)
        magnet     = self._magnet_strike(df)
        theta_iv   = self._theta_iv_ratio(df, spot)
        delta_skew = self._delta_skew(df, spot)

        # ── Section 3: Five models ────────────────────────────────────────────
        models   = self._five_models(df, spot, dte, atr14, va_buf_mult,
                                     atm_iv, straddle, call_wall, put_wall)
        synthesis = self._strike_synthesis(models)

        # ── Section 4: GEX + wall verdict ────────────────────────────────────
        gex          = self._gex(df, spot)
        wall_verdict = self._wall_verdict(df, call_wall, put_wall, gex)

        # ── Legacy ────────────────────────────────────────────────────────────
        migration = self._migration_status(df, spot)
        kills     = self._kill_switches(pcr, gex, migration)
        home_sc   = self._home_score(gex, pcr, migration)

        return {
            "spot":           round(spot, 0),
            "dte":            dte,
            "pcr":            round(pcr, 2),
            "max_pain":       max_pain,
            "max_pain_dist":  round(abs(spot - max_pain), 0),
            "fut_premium":    fut_premium,
            "atm_iv":         round(atm_iv, 2),
            "iv_skew":        round(iv_skew, 2),
            "straddle_price": round(straddle, 1),
            "magnet_strike":  magnet,
            "theta_iv_ratio": round(theta_iv, 3),
            "delta_skew":     delta_skew,
            "models":         models,
            "synthesis":      synthesis,
            "binding_ce":     synthesis["binding_ce"],
            "binding_pe":     synthesis["binding_pe"],
            "call_wall":      call_wall,
            "put_wall":       put_wall,
            "wall_integrity": wall_int,
            "gex":            gex,
            "wall_verdict":   wall_verdict,
            "migration":      migration,
            "kill_switches":  kills,
            "home_score":     home_sc,
            "strategy":       "IRON_CONDOR",
        }

    # ── Section 1 helpers ─────────────────────────────────────────────────────

    def _pcr(self, df: pd.DataFrame) -> float:
        if "pe_oi" not in df.columns or "ce_oi" not in df.columns:
            return 1.0
        total_pe = df["pe_oi"].sum()
        total_ce = df["ce_oi"].sum()
        return round(total_pe / total_ce, 3) if total_ce > 0 else 1.0

    def _max_pain(self, df: pd.DataFrame, spot: float) -> float:
        """Strike minimising total intrinsic value for option buyers."""
        if df.empty or "ce_oi" not in df.columns or "pe_oi" not in df.columns:
            return round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP

        strikes = sorted(df.index.tolist())
        if not strikes:
            return round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP

        min_pain, pain_strike = float("inf"), strikes[0]
        for s in strikes:
            try:
                # Call loss: all calls below s are ITM for buyers
                call_pain = sum(
                    float(df.loc[k, "ce_oi"]) * (s - k)
                    for k in strikes if k < s and "ce_oi" in df.columns
                )
                # Put loss: all puts above s are ITM for buyers
                put_pain = sum(
                    float(df.loc[k, "pe_oi"]) * (k - s)
                    for k in strikes if k > s and "pe_oi" in df.columns
                )
                total = call_pain + put_pain
                if total < min_pain:
                    min_pain, pain_strike = total, s
            except Exception:
                continue
        return float(pain_strike)

    def _straddle_price(self, df: pd.DataFrame, spot: float) -> float:
        atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
        if atm in df.index:
            ce_ltp = float(df.loc[atm, "ce_ltp"]) if "ce_ltp" in df.columns else 0
            pe_ltp = float(df.loc[atm, "pe_ltp"]) if "pe_ltp" in df.columns else 0
            return ce_ltp + pe_ltp
        return 0.0

    def _atm_iv(self, df: pd.DataFrame, spot: float) -> float:
        atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
        if atm in df.index:
            ce_iv = float(df.loc[atm, "ce_iv"]) if "ce_iv" in df.columns else 0
            pe_iv = float(df.loc[atm, "pe_iv"]) if "pe_iv" in df.columns else 0
            if ce_iv > 0 and pe_iv > 0:
                return (ce_iv + pe_iv) / 2
            return max(ce_iv, pe_iv)
        return 12.0

    def _iv_skew(self, df: pd.DataFrame, spot: float) -> float:
        atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
        if atm in df.index:
            pe_iv = float(df.loc[atm, "pe_iv"]) if "pe_iv" in df.columns else 0
            ce_iv = float(df.loc[atm, "ce_iv"]) if "ce_iv" in df.columns else 0
            return pe_iv - ce_iv
        return 0.0

    # ── Section 2: Greeks helpers ─────────────────────────────────────────────

    def _magnet_strike(self, df: pd.DataFrame) -> int:
        """Strike with highest combined gamma = dealer hotspot."""
        if "ce_gamma" not in df.columns and "pe_gamma" not in df.columns:
            return 0
        try:
            gamma_sum = pd.Series(0.0, index=df.index)
            if "ce_gamma" in df.columns:
                gamma_sum = gamma_sum + df["ce_gamma"].abs()
            if "pe_gamma" in df.columns:
                gamma_sum = gamma_sum + df["pe_gamma"].abs()
            return int(gamma_sum.idxmax())
        except Exception:
            return 0

    def _theta_iv_ratio(self, df: pd.DataFrame, spot: float) -> float:
        """ATM |Theta| / IV. Above 1.0 = seller's edge."""
        atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
        if atm not in df.index:
            return 0.0
        iv = self._atm_iv(df, spot)
        if iv <= 0:
            return 0.0
        try:
            ce_th = abs(float(df.loc[atm, "ce_theta"])) if "ce_theta" in df.columns else 0
            pe_th = abs(float(df.loc[atm, "pe_theta"])) if "pe_theta" in df.columns else 0
            theta = (ce_th + pe_th) / 2 if ce_th > 0 and pe_th > 0 else max(ce_th, pe_th)
            return round(theta / iv, 3) if theta > 0 else 0.0
        except Exception:
            return 0.0

    def _delta_skew(self, df: pd.DataFrame, spot: float) -> str:
        atm      = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
        s_plus   = atm + 100
        s_minus  = atm - 100
        ce_col   = "ce_delta" if "ce_delta" in df.columns else None
        pe_col   = "pe_delta" if "pe_delta" in df.columns else None
        if ce_col and pe_col and s_plus in df.index and s_minus in df.index:
            call_d = abs(float(df.loc[s_plus,  ce_col]))
            put_d  = abs(float(df.loc[s_minus, pe_col]))
            if put_d > call_d * 1.1:  return "PUT_SKEW"
            if call_d > put_d * 1.1:  return "CALL_SKEW"
        return "BALANCED"

    # ── Section 3: Five strike models ────────────────────────────────────────

    def _five_models(self, df, spot, dte, atr14, va_buf_mult,
                     atm_iv, straddle, call_wall, put_wall) -> dict:

        # LOCKED: single atr14 used symmetrically — no rounding per side
        atr = atr14

        # Method 1 — 10 delta
        ce_10d, pe_10d = self._ten_delta_strikes(df, spot, dte, atm_iv)

        # Method 2 — IV expected move (1 SD)
        if atm_iv > 0 and dte > 0:
            exp_move = spot * (atm_iv / 100) * math.sqrt(dte / 365)
            ce_iv    = round((spot + exp_move) / 50) * 50
            pe_iv    = round((spot - exp_move) / 50) * 50
        else:
            ce_iv = pe_iv = 0

        # Method 3 — ATR multiples (LOCKED: same atr for CE and PE)
        ce_atr1  = int(round((spot + ATR_AGGR * atr) / 50) * 50)
        pe_atr1  = int(round((spot - ATR_AGGR * atr) / 50) * 50)
        ce_atr15 = int(round((spot + ATR_BALC * atr) / 50) * 50)
        pe_atr15 = int(round((spot - ATR_BALC * atr) / 50) * 50)
        ce_atr2  = int(round((spot + ATR_CONS * atr) / 50) * 50)
        pe_atr2  = int(round((spot - ATR_CONS * atr) / 50) * 50)

        # Method 4 — Straddle breakeven
        atm = round(spot / 50) * 50
        if straddle > 0:
            ce_str = int(atm + round(straddle / 50) * 50)
            pe_str = int(atm - round(straddle / 50) * 50)
        else:
            ce_str = pe_str = 0

        # Method 5 — Wall anchor (LOCKED: single atr used)
        buf_pts   = int(round(va_buf_mult * atr / 50) * 50)
        ce_wall_a = int(call_wall) + buf_pts if call_wall > 0 else 0
        pe_wall_a = int(put_wall)  - buf_pts if put_wall  > 0 else 0

        return {
            "10_delta":    {"ce": int(ce_10d), "pe": int(pe_10d),
                             "note": "10% probability ITM — institutional benchmark"},
            "iv_exp_move": {"ce": int(ce_iv),  "pe": int(pe_iv),
                             "note": f"1SD expected move = ±{round(ce_iv - spot):,} pts" if ce_iv else "IV unavailable"},
            "atr_1x":      {"ce": ce_atr1,   "pe": pe_atr1,
                             "note": f"Aggressive — ±{int(ATR_AGGR * atr):,} pts from spot"},
            "atr_1.5x":    {"ce": ce_atr15,  "pe": pe_atr15,
                             "note": f"Balanced — ±{int(ATR_BALC * atr):,} pts from spot"},
            "atr_2x":      {"ce": ce_atr2,   "pe": pe_atr2,
                             "note": f"Conservative — ±{int(ATR_CONS * atr):,} pts from spot"},
            "straddle":    {"ce": ce_str,    "pe": pe_str,
                             "note": f"Straddle = {round(straddle):,} pts" if straddle else "Straddle unavailable"},
            "wall_anchor": {"ce": ce_wall_a, "pe": pe_wall_a,
                             "note": f"Wall + {buf_pts:,} pts ATR buffer" if call_wall else "Wall not detected"},
        }

    def _ten_delta_strikes(self, df: pd.DataFrame, spot: float,
                            dte: int = 7, atm_iv: float = 12.0) -> tuple:
        """
        Find strikes closest to 10 delta CE and -10 delta PE.
        Uses actual deltas if available, else BS approximation.
        """
        ce_col = "ce_delta" if "ce_delta" in df.columns else None
        pe_col = "pe_delta" if "pe_delta" in df.columns else None

        if ce_col and pe_col:
            otm_ce = df[df.index > spot]
            otm_pe = df[df.index < spot]
            try:
                if not otm_ce.empty and otm_ce[ce_col].abs().sum() > 0:
                    ce_strike = int(abs(otm_ce[ce_col] - 0.10).idxmin())
                else:
                    raise ValueError("no CE delta")
                if not otm_pe.empty and otm_pe[pe_col].abs().sum() > 0:
                    pe_strike = int(abs(otm_pe[pe_col].abs() - 0.10).idxmin())
                else:
                    raise ValueError("no PE delta")
                return ce_strike, pe_strike
            except Exception:
                pass

        # BS approximation: search for 10-delta strike
        T  = max(dte, 1) / 365.0
        sigma = max((atm_iv or 12.0) / 100, 0.05)

        # CE: find strike where call delta ≈ 0.10
        ce_strike = int(round((spot * (1 + 1.3 * sigma * math.sqrt(T))) / 50) * 50)
        pe_strike = int(round((spot * (1 - 1.3 * sigma * math.sqrt(T))) / 50) * 50)
        return ce_strike, pe_strike

    def _strike_synthesis(self, models: dict) -> dict:
        ce_vals = [m["ce"] for m in models.values() if m["ce"] > 0]
        pe_vals = [m["pe"] for m in models.values() if m["pe"] > 0]
        binding_ce = max(ce_vals) if ce_vals else 0
        binding_pe = min(pe_vals) if pe_vals else 0
        binding_ce_model = next((k for k, m in models.items() if m["ce"] == binding_ce), "—")
        binding_pe_model = next((k for k, m in models.items() if m["pe"] == binding_pe), "—")
        return {
            "binding_ce": binding_ce, "binding_pe": binding_pe,
            "binding_ce_model": binding_ce_model, "binding_pe_model": binding_pe_model,
        }

    # ── Section 4: Wall and GEX ───────────────────────────────────────────────

    def _oi_wall(self, df: pd.DataFrame, col: str) -> int:
        if col not in df.columns or df.empty or df[col].sum() == 0:
            return 0
        return int(df[col].idxmax())

    def _wall_integrity(self, df: pd.DataFrame, call_wall: int, put_wall: int) -> dict:
        def integrity(col, wall_strike):
            if col not in df.columns or wall_strike == 0:
                return "UNKNOWN"
            if wall_strike not in df.index:
                return "UNKNOWN"
            sorted_oi = df[col].nlargest(2)
            if len(sorted_oi) < 2 or sorted_oi.iloc[0] == 0:
                return "SOLID"
            ratio = sorted_oi.iloc[1] / sorted_oi.iloc[0]
            return "FRAGMENTED" if ratio >= 0.75 else "SOLID"
        return {
            "call_integrity": integrity("ce_oi", call_wall),
            "put_integrity":  integrity("pe_oi", put_wall),
        }

    def _gex(self, df: pd.DataFrame, spot: float) -> dict:
        """GEX = Σ(Call OI × Call Gamma − Put OI × Put Gamma) × LOT_SIZE × Spot"""
        if "ce_gamma" not in df.columns and "pe_gamma" not in df.columns:
            return {"total_gex": 0, "flip_level": 0, "positive": False, "gex_per_strike": {}}

        total_gex = 0.0
        gex_per   = {}
        cumulative = []

        for K in df.index:
            try:
                ce_g  = float(df.loc[K, "ce_gamma"]) if "ce_gamma" in df.columns else 0
                pe_g  = float(df.loc[K, "pe_gamma"]) if "pe_gamma" in df.columns else 0
                ce_oi = float(df.loc[K, "ce_oi"])    if "ce_oi"    in df.columns else 0
                pe_oi = float(df.loc[K, "pe_oi"])    if "pe_oi"    in df.columns else 0
                g = (ce_oi * ce_g - pe_oi * pe_g) * LOT_SIZE * spot
                gex_per[int(K)] = round(g, 0)
                total_gex += g
                cumulative.append((int(K), total_gex))
            except Exception:
                continue

        # Flip level: where sorted cumulative GEX crosses zero upward
        flip_level = 0
        for i in range(1, len(cumulative)):
            if cumulative[i-1][1] >= 0 > cumulative[i][1]:
                flip_level = cumulative[i][0]
                break

        return {
            "total_gex":      round(total_gex, 0),
            "flip_level":     flip_level,
            "positive":       total_gex > 0,
            "gex_per_strike": gex_per,
        }

    def _wall_verdict(self, df, call_wall, put_wall, gex) -> dict:
        flip      = gex.get("flip_level", 0)
        total_gex = gex.get("total_gex", 0)
        gex_env   = "PINNING" if total_gex > 0 else "AMPLIFYING" if total_gex < 0 else "NEUTRAL"

        if flip and call_wall:
            if abs(flip - call_wall) <= 50:  ce_gex = "DOUBLE_BARRIER"
            elif flip < call_wall:            ce_gex = "GAP_DANGER"
            else:                             ce_gex = "FLIP_BEYOND"
        else:
            ce_gex = "UNKNOWN"

        if ce_gex == "DOUBLE_BARRIER" and gex_env == "PINNING":
            combined = "MAXIMUM_RANGE_CONFIDENCE"
        elif gex_env == "AMPLIFYING" and ce_gex == "GAP_DANGER":
            combined = "BOTH_LEGS_ELEVATED_RISK"
        elif gex_env == "PINNING":
            combined = "RANGE_FAVOURABLE"
        else:
            combined = "STANDARD"

        return {"ce_gex_relationship": ce_gex, "gex_environment": gex_env,
                "combined_verdict": combined}

    # ── Legacy helpers ────────────────────────────────────────────────────────

    def _migration_status(self, df: pd.DataFrame, spot: float) -> dict:
        try:
            atm = round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP
            if "ce_oi_change" not in df.columns:
                return {"detected": False, "above": 0, "below": 0}
            above = df.loc[df.index > atm, "ce_oi_change"].sum()
            below = df.loc[df.index < atm, "pe_oi_change"].sum() if "pe_oi_change" in df.columns else 0
            return {"detected": abs(above) > 500_000 or abs(below) > 500_000,
                    "above": above, "below": below}
        except Exception:
            return {"detected": False, "above": 0, "below": 0}

    def _kill_switches(self, pcr, gex, migration) -> dict:
        return {
            "migration_detected": migration.get("detected", False),
            "gex_negative":       gex.get("total_gex", 0) < 0,
            "pcr_extreme":        pcr < 0.5 or pcr > 2.0,
        }

    def _home_score(self, gex, pcr, migration) -> int:
        """Home score — max 25 pts per locked rules Section 7.1"""
        if migration.get("detected"): return 0
        score = 10
        if gex.get("positive"):                           score += 8
        if PCR_BALANCED_LOW <= pcr <= PCR_BALANCED_HI:    score += 7
        return min(score, 25)

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
            "wall_integrity": {"call_integrity": "UNKNOWN", "put_integrity": "UNKNOWN"},
            "gex": {"total_gex": 0, "flip_level": 0, "positive": False, "gex_per_strike": {}},
            "wall_verdict": {"combined_verdict": "STANDARD", "gex_environment": "NEUTRAL",
                             "ce_gex_relationship": "UNKNOWN"},
            "migration": {"detected": False}, "kill_switches": {}, "home_score": 10,
            "strategy": "IRON_CONDOR",
        }
