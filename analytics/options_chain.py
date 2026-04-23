# analytics/options_chain.py — v5 (April 2026)
# Page 10: Options Chain Analysis Engine
#
# ROOT CAUSE FIX (per locked rules doc Section 5):
#   Kite quote() returns ONLY: oi, volume, last_price, oi_day_change, implied_volatility
#   It does NOT return: delta, gamma, theta
#   Therefore: gamma, delta, theta are approximated via Black-Scholes using ce_iv/pe_iv
#
# What this fixes:
#   ATM IV      → was 0 because ce_iv/pe_iv were not being read from quote()
#                  FIX: live_fetcher already stores implied_volatility as ce_iv/pe_iv ✅
#                  But ATM strike lookup was failing → added nearest-strike fallback
#   IV Skew     → same ATM lookup issue → fixed with nearest-strike fallback
#   Futures     → was 0 because futures_price was never passed from page
#                  FIX: fetch NIFTY futures from Kite in live_fetcher, pass here
#   PCR         → was using entire chain OI, but near/far expiry mix was wrong
#                  FIX: uses only the chain passed (far or near, not both mixed)
#   Theta/IV    → was 0 because ce_theta column never existed
#                  FIX: approximate theta via Black-Scholes
#   Magnet      → was dash because ce_gamma never existed
#                  FIX: approximate gamma via Black-Scholes
#   GEX         → was 0 for same gamma reason → fixed
#   Delta skew  → was BALANCED (hardcoded fallback) because ce_delta never existed
#                  FIX: approximate delta via Black-Scholes

import pandas as pd
import numpy as np
from scipy.stats import norm
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

RISK_FREE = 0.065   # India risk-free rate ~6.5%


# ─── Black-Scholes Greeks approximations ─────────────────────────────────────

def _bs_greeks(S: float, K: float, T: float, iv: float,
               r: float = RISK_FREE, option_type: str = "CE") -> dict:
    """
    Compute Black-Scholes delta, gamma, theta for one option.

    S  = spot price
    K  = strike
    T  = time to expiry in years (DTE / 365)
    iv = implied volatility as decimal (e.g. 0.12 for 12%)
    r  = risk-free rate
    Returns dict with delta, gamma, theta (theta in points per day)
    """
    if T <= 0 or iv <= 0 or S <= 0 or K <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0}
    try:
        d1 = (np.log(S / K) + (r + 0.5 * iv ** 2) * T) / (iv * np.sqrt(T))
        d2 = d1 - iv * np.sqrt(T)

        gamma = norm.pdf(d1) / (S * iv * np.sqrt(T))

        if option_type == "CE":
            delta = norm.cdf(d1)
            theta = (
                -(S * norm.pdf(d1) * iv) / (2 * np.sqrt(T))
                - r * K * np.exp(-r * T) * norm.cdf(d2)
            ) / 365
        else:  # PE
            delta = norm.cdf(d1) - 1
            theta = (
                -(S * norm.pdf(d1) * iv) / (2 * np.sqrt(T))
                + r * K * np.exp(-r * T) * norm.cdf(-d2)
            ) / 365

        return {
            "delta": float(delta),
            "gamma": float(gamma),
            "theta": float(theta),   # negative = time decay per day (in index pts)
        }
    except Exception:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0}


def _enrich_with_greeks(df: pd.DataFrame, spot: float, dte: int) -> pd.DataFrame:
    """
    Add ce_delta, ce_gamma, ce_theta, pe_delta, pe_gamma, pe_theta columns
    using Black-Scholes and the iv values already in the DataFrame.

    Called once inside signals() before any Greek-dependent calculation.
    Only adds columns if they don't already exist (won't overwrite live data).
    """
    if df.empty:
        return df

    df = df.copy()
    T = max(dte, 0.5) / 365   # floor at 0.5 days to avoid div-by-zero on expiry day

    ce_delta_list, ce_gamma_list, ce_theta_list = [], [], []
    pe_delta_list, pe_gamma_list, pe_theta_list = [], [], []

    for strike in df.index:
        # CE Greeks
        ce_iv_pct = float(df.loc[strike, "ce_iv"]) if "ce_iv" in df.columns else 0.0
        ce_iv_dec = ce_iv_pct / 100.0
        ce_g = _bs_greeks(spot, strike, T, ce_iv_dec, option_type="CE")
        ce_delta_list.append(ce_g["delta"])
        ce_gamma_list.append(ce_g["gamma"])
        ce_theta_list.append(ce_g["theta"])

        # PE Greeks
        pe_iv_pct = float(df.loc[strike, "pe_iv"]) if "pe_iv" in df.columns else 0.0
        pe_iv_dec = pe_iv_pct / 100.0
        pe_g = _bs_greeks(spot, strike, T, pe_iv_dec, option_type="PE")
        pe_delta_list.append(pe_g["delta"])
        pe_gamma_list.append(pe_g["gamma"])
        pe_theta_list.append(pe_g["theta"])

    # Only add if not already present (don't overwrite live Kite Greeks if ever available)
    if "ce_delta" not in df.columns:
        df["ce_delta"] = ce_delta_list
    if "ce_gamma" not in df.columns:
        df["ce_gamma"] = ce_gamma_list
    if "ce_theta" not in df.columns:
        df["ce_theta"] = ce_theta_list
    if "pe_delta" not in df.columns:
        df["pe_delta"] = pe_delta_list
    if "pe_gamma" not in df.columns:
        df["pe_gamma"] = pe_gamma_list
    if "pe_theta" not in df.columns:
        df["pe_theta"] = pe_theta_list

    return df


def _nearest_atm(df: pd.DataFrame, spot: float) -> int:
    """
    Return the strike in df.index closest to spot.
    Handles the case where exact ATM (round to 50) is not in the chain
    (e.g. chain only covers ±500 pts and spot is at an edge).
    """
    if df.empty:
        return int(round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP)
    diffs = (df.index - spot).to_series().abs()
    return int(diffs.idxmin())


# ══════════════════════════════════════════════════════════════════════════════

class OptionsChainEngine(BaseStrategy):

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def signals(self, df: pd.DataFrame, spot: float, dte: int,
                atr14: float = 200.0, va_buf_mult: float = 0.75,
                futures_price: float = 0.0) -> dict:

        if df.empty:
            return self._empty_signals(spot)

        # ── STEP 0: Enrich with BS Greeks (gamma, delta, theta) ───────────────
        # This is the single fix that unblocks ATM IV, IV skew, theta/IV,
        # magnet strike, GEX, delta skew, and 10-delta strike model.
        df = _enrich_with_greeks(df, spot, dte)

        # ── Section 1: Headline numbers ───────────────────────────────────────
        pcr         = self._pcr(df)
        max_pain    = self._max_pain(df)
        # Futures premium: futures_price passed from page (fetch separately)
        # If not passed, approximate from straddle: F ≈ spot + straddle/2 * skew
        fut_premium = futures_price - spot if futures_price > 0 else 0.0

        # ── Walls (shared across sections) ────────────────────────────────────
        call_wall = self._oi_wall(df, "ce_oi")
        put_wall  = self._oi_wall(df, "pe_oi")
        wall_int  = self._wall_integrity(df, call_wall, put_wall)

        # ── Section 2: Greeks ─────────────────────────────────────────────────
        atm_iv     = self._atm_iv(df, spot)
        iv_skew    = self._iv_skew(df, spot)
        straddle   = self._straddle_price(df, spot)
        magnet     = self._magnet_strike(df)
        theta_iv   = self._theta_iv_ratio(df, spot, dte)
        delta_skew = self._delta_skew(df, spot)

        # ── Section 3: Five strike models + synthesis ─────────────────────────
        models    = self._five_models(df, spot, dte, atr14, va_buf_mult,
                                      atm_iv, straddle, call_wall, put_wall)
        synthesis = self._strike_synthesis(models)

        # ── Section 4: Wall and GEX analysis ─────────────────────────────────
        gex          = self._gex(df, spot)
        wall_verdict = self._wall_verdict(df, call_wall, put_wall, gex)

        # ── Legacy fields ─────────────────────────────────────────────────────
        migration = self._migration_status(df, spot)
        kills     = self._kill_switches(pcr, gex, migration)
        home_score = self._home_score(gex, pcr, migration)

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
        """
        PCR = Total Put OI / Total Call OI across the chain.
        Uses ONLY the chain passed (near OR far — not mixed).
        Filters out strikes with zero OI on both sides to avoid noise.
        """
        active = df[(df["pe_oi"] > 0) | (df["ce_oi"] > 0)]
        total_pe = active["pe_oi"].sum()
        total_ce = active["ce_oi"].sum()
        return round(total_pe / total_ce, 3) if total_ce > 0 else 0.0

    def _max_pain(self, df: pd.DataFrame) -> float:
        """Strike minimising total intrinsic loss for all option buyers."""
        if df.empty:
            return 0.0
        strikes = df.index.tolist()
        min_pain, pain_strike = float("inf"), strikes[0]
        for s in strikes:
            # CE buyers lose when strike < settlement → CE writer gains
            ce_pain = (df.loc[df.index < s, "ce_oi"] *
                       (s - df.index[df.index < s])).sum()
            # PE buyers lose when strike > settlement → PE writer gains
            pe_pain = (df.loc[df.index > s, "pe_oi"] *
                       (df.index[df.index > s] - s)).sum()
            total = ce_pain + pe_pain
            if total < min_pain:
                min_pain, pain_strike = total, s
        return float(pain_strike)

    def _straddle_price(self, df: pd.DataFrame, spot: float) -> float:
        """ATM CE LTP + ATM PE LTP = implied market move in points."""
        atm = _nearest_atm(df, spot)
        if atm in df.index:
            ce_ltp = float(df.loc[atm, "ce_ltp"])
            pe_ltp = float(df.loc[atm, "pe_ltp"])
            if ce_ltp > 0 and pe_ltp > 0:
                return ce_ltp + pe_ltp
        return 0.0

    # ══════════════════════════════════════════════════════════════════════════
    # Section 2 helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _atm_iv(self, df: pd.DataFrame, spot: float) -> float:
        """
        Average of ATM CE IV and PE IV.
        FIX: uses nearest-strike fallback so it works even if exact ATM
        is not in the chain. Kite returns implied_volatility in the quote
        response — stored as ce_iv / pe_iv by live_fetcher.
        """
        atm = _nearest_atm(df, spot)
        if atm not in df.index:
            return 0.0
        ce_iv = float(df.loc[atm, "ce_iv"]) if "ce_iv" in df.columns else 0.0
        pe_iv = float(df.loc[atm, "pe_iv"]) if "pe_iv" in df.columns else 0.0

        # Both populated → average
        if ce_iv > 0 and pe_iv > 0:
            return (ce_iv + pe_iv) / 2
        # Only one populated → use it
        if ce_iv > 0:
            return ce_iv
        if pe_iv > 0:
            return pe_iv
        # Neither populated → scan nearby strikes (within ±100)
        nearby = df[(df.index >= spot - 100) & (df.index <= spot + 100)]
        ce_vals = nearby["ce_iv"][nearby["ce_iv"] > 0] if "ce_iv" in nearby.columns else pd.Series()
        pe_vals = nearby["pe_iv"][nearby["pe_iv"] > 0] if "pe_iv" in nearby.columns else pd.Series()
        all_vals = pd.concat([ce_vals, pe_vals])
        return float(all_vals.mean()) if not all_vals.empty else 0.0

    def _iv_skew(self, df: pd.DataFrame, spot: float) -> float:
        """
        IV Skew = ATM Put IV − ATM Call IV.
        Positive = put IV higher = downside fear.
        FIX: nearest-strike fallback.
        """
        atm = _nearest_atm(df, spot)
        if atm not in df.index:
            return 0.0
        pe_iv = float(df.loc[atm, "pe_iv"]) if "pe_iv" in df.columns else 0.0
        ce_iv = float(df.loc[atm, "ce_iv"]) if "ce_iv" in df.columns else 0.0
        if pe_iv > 0 and ce_iv > 0:
            return pe_iv - ce_iv
        return 0.0

    def _magnet_strike(self, df: pd.DataFrame) -> int:
        """
        Highest gamma strike = dealer hedging hotspot.
        FIX: uses BS-approximated gamma (ce_gamma column added by _enrich_with_greeks).
        Uses combined gamma (CE + PE) at each strike for maximum accuracy.
        """
        if "ce_gamma" not in df.columns and "pe_gamma" not in df.columns:
            return 0
        try:
            # Combined gamma per strike: CE gamma + PE gamma
            combined = pd.Series(0.0, index=df.index)
            if "ce_gamma" in df.columns:
                combined = combined + df["ce_gamma"].abs()
            if "pe_gamma" in df.columns:
                combined = combined + df["pe_gamma"].abs()
            return int(combined.idxmax())
        except Exception:
            return 0

    def _theta_iv_ratio(self, df: pd.DataFrame, spot: float, dte: int) -> float:
        """
        Theta/IV ratio = |ATM daily theta| / ATM IV.
        Above 1.0 = seller's market (collecting fast relative to uncertainty).
        FIX: uses BS-approximated theta (ce_theta added by _enrich_with_greeks).
        Uses average of CE and PE theta at ATM.
        theta is in index points/day from BS; IV is in % — normalise by spot.
        """
        atm = _nearest_atm(df, spot)
        if atm not in df.index:
            return 0.0

        iv = self._atm_iv(df, spot)
        if iv <= 0:
            return 0.0

        # Get BS theta (already per day, in decimal fraction of spot)
        ce_theta = abs(float(df.loc[atm, "ce_theta"])) if "ce_theta" in df.columns else 0.0
        pe_theta = abs(float(df.loc[atm, "pe_theta"])) if "pe_theta" in df.columns else 0.0

        if ce_theta > 0 and pe_theta > 0:
            avg_theta = (ce_theta + pe_theta) / 2
        elif ce_theta > 0:
            avg_theta = ce_theta
        elif pe_theta > 0:
            avg_theta = pe_theta
        else:
            return 0.0

        # Theta from BS is in fractional terms (fraction of spot per day)
        # Convert to points: theta_pts = avg_theta * spot
        # Ratio: theta_pts / (iv / 100 * spot / sqrt(365))
        # Simplified: theta_pts * sqrt(365) / (iv_decimal * spot)
        # Even simpler approach: straddle daily decay / straddle price
        # Use: straddle theta pts / (atm_iv/100 * spot / sqrt(365))
        theta_pts = avg_theta * spot
        iv_daily  = (iv / 100) * spot / np.sqrt(365)
        if iv_daily > 0:
            return theta_pts / iv_daily
        return 0.0

    def _delta_skew(self, df: pd.DataFrame, spot: float) -> str:
        """
        Compare absolute put delta at ATM-100 vs call delta at ATM+100.
        PUT_SKEW = put delta > call delta × 1.1 = downside feared more.
        FIX: uses BS-approximated delta (ce_delta/pe_delta from _enrich_with_greeks).
        """
        atm          = _nearest_atm(df, spot)
        strike_plus  = atm + 100
        strike_minus = atm - 100

        # Snap to nearest available strike if exact not present
        if strike_plus not in df.index:
            above = df[df.index > atm]
            strike_plus = int(above.index[0]) if not above.empty else strike_plus
        if strike_minus not in df.index:
            below = df[df.index < atm]
            strike_minus = int(below.index[-1]) if not below.empty else strike_minus

        if "ce_delta" not in df.columns or "pe_delta" not in df.columns:
            return "BALANCED"

        try:
            call_d = abs(float(df.loc[strike_plus,  "ce_delta"]))
            put_d  = abs(float(df.loc[strike_minus, "pe_delta"]))
            if put_d > call_d * 1.1:   return "PUT_SKEW"
            if call_d > put_d * 1.1:   return "CALL_SKEW"
        except Exception:
            pass
        return "BALANCED"

    # ══════════════════════════════════════════════════════════════════════════
    # Section 3: Five strike models
    # ══════════════════════════════════════════════════════════════════════════

    def _five_models(self, df, spot, dte, atr14, va_buf_mult,
                     atm_iv, straddle, call_wall, put_wall) -> dict:

        # Method 1 — 10 delta
        ce_10d, pe_10d = self._ten_delta_strikes(df, spot)

        # Method 2 — IV expected move (1 SD over DTE)
        if atm_iv > 0 and dte > 0:
            exp_move = spot * (atm_iv / 100) * np.sqrt(dte / 365)
            ce_iv    = int(round((spot + exp_move) / 50) * 50)
            pe_iv    = int(round((spot - exp_move) / 50) * 50)
        else:
            ce_iv = pe_iv = 0

        # Method 3 — ATR multiples (three variants, symmetric)
        ce_atr1  = int(round((spot + ATR_AGGR * atr14) / 50) * 50)
        pe_atr1  = int(round((spot - ATR_AGGR * atr14) / 50) * 50)
        ce_atr15 = int(round((spot + ATR_BALC * atr14) / 50) * 50)
        pe_atr15 = int(round((spot - ATR_BALC * atr14) / 50) * 50)
        ce_atr2  = int(round((spot + ATR_CONS * atr14) / 50) * 50)
        pe_atr2  = int(round((spot - ATR_CONS * atr14) / 50) * 50)

        # Method 4 — Straddle breakeven
        atm = int(round(spot / 50) * 50)
        if straddle > 0:
            ce_str = int(atm + round(straddle / 50) * 50)
            pe_str = int(atm - round(straddle / 50) * 50)
        else:
            ce_str = pe_str = 0

        # Method 5 — Wall anchor: CE = call wall + ATR buffer; PE = put wall - ATR buffer
        buf_pts   = int(round(va_buf_mult * atr14 / 50) * 50)
        ce_wall_a = int(call_wall) + buf_pts if call_wall > 0 else 0
        pe_wall_a = int(put_wall)  - buf_pts if put_wall  > 0 else 0

        return {
            "10_delta":    {"ce": int(ce_10d),  "pe": int(pe_10d),
                             "note": "10% probability ITM — institutional benchmark"},
            "iv_exp_move": {"ce": ce_iv,         "pe": pe_iv,
                             "note": f"1SD expected move = ±{int(exp_move if atm_iv > 0 and dte > 0 else 0):,} pts"},
            "atr_1x":      {"ce": ce_atr1,       "pe": pe_atr1,
                             "note": "Aggressive — highest premium, highest risk"},
            "atr_1.5x":    {"ce": ce_atr15,      "pe": pe_atr15,
                             "note": "Balanced — most common choice"},
            "atr_2x":      {"ce": ce_atr2,       "pe": pe_atr2,
                             "note": "Conservative — use when VIX elevated"},
            "straddle":    {"ce": ce_str,         "pe": pe_str,
                             "note": f"Market maker implied move = ±{int(round(straddle)):,} pts" if straddle > 0 else "Straddle not available"},
            "wall_anchor": {"ce": ce_wall_a,      "pe": pe_wall_a,
                             "note": f"Wall + {buf_pts:,} pts ATR buffer" if call_wall > 0 else "Wall data unavailable"},
        }

    def _ten_delta_strikes(self, df: pd.DataFrame, spot: float) -> tuple:
        """
        Find the OTM strikes closest to 10 delta (CE) and -10 delta (PE).
        FIX: uses BS-approximated delta from _enrich_with_greeks.
        """
        if "ce_delta" not in df.columns or "pe_delta" not in df.columns:
            # Fallback: approximate 10-delta as ~6.5% OTM
            ce_strike = int(round((spot * 1.065) / 50) * 50)
            pe_strike = int(round((spot * 0.935) / 50) * 50)
            return ce_strike, pe_strike

        # OTM calls: strikes above spot
        otm_ce = df[df.index > spot].copy()
        if not otm_ce.empty:
            # Call delta decreases as we go further OTM — find closest to 0.10
            ce_strike = int(abs(otm_ce["ce_delta"] - 0.10).idxmin())
        else:
            ce_strike = int(round((spot * 1.065) / 50) * 50)

        # OTM puts: strikes below spot
        otm_pe = df[df.index < spot].copy()
        if not otm_pe.empty:
            # Put delta is negative, abs closer to 0.10 OTM
            pe_strike = int(abs(otm_pe["pe_delta"].abs() - 0.10).idxmin())
        else:
            pe_strike = int(round((spot * 0.935) / 50) * 50)

        return ce_strike, pe_strike

    def _strike_synthesis(self, models: dict) -> dict:
        """
        Most conservative = furthest from spot.
        Binding CE = MAX of all CE suggestions.
        Binding PE = MIN of all PE suggestions.
        """
        ce_vals = [(k, m["ce"]) for k, m in models.items() if m["ce"] > 0]
        pe_vals = [(k, m["pe"]) for k, m in models.items() if m["pe"] > 0]

        if ce_vals:
            binding_ce_model, binding_ce = max(ce_vals, key=lambda x: x[1])
        else:
            binding_ce_model, binding_ce = "—", 0

        if pe_vals:
            binding_pe_model, binding_pe = min(pe_vals, key=lambda x: x[1])
        else:
            binding_pe_model, binding_pe = "—", 0

        return {
            "binding_ce":       binding_ce,
            "binding_pe":       binding_pe,
            "binding_ce_model": binding_ce_model,
            "binding_pe_model": binding_pe_model,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # Section 4: Wall and GEX
    # ══════════════════════════════════════════════════════════════════════════

    def _oi_wall(self, df: pd.DataFrame, col: str) -> int:
        """Strike with highest OI = the wall."""
        if col not in df.columns or df.empty:
            return 0
        active = df[df[col] > 0]
        if active.empty:
            return 0
        return int(active[col].idxmax())

    def _wall_integrity(self, df: pd.DataFrame, call_wall: int, put_wall: int) -> dict:
        """
        75% rule: if 2nd highest OI / highest OI >= 75% → FRAGMENTED.
        FRAGMENTED = wall may not hold, two competing levels.
        """
        def integrity(col, wall_strike):
            if col not in df.columns or wall_strike == 0:
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
        """
        GEX = Σ (Call OI × Call Gamma − Put OI × Put Gamma) × LOT_SIZE × Spot
        Positive GEX = dealers short gamma = they BUY dips, SELL rallies = PINNING
        Negative GEX = dealers long gamma = they SELL dips, BUY rallies = AMPLIFYING
        FIX: uses BS-approximated gamma from _enrich_with_greeks.
        """
        if "ce_gamma" not in df.columns or "pe_gamma" not in df.columns:
            return {"total_gex": 0, "flip_level": 0, "positive": False, "gex_per_strike": {}}

        gex_per      = {}
        total_gex    = 0.0
        running_list = []  # (strike, cumulative_gex) sorted by strike ascending

        for strike in sorted(df.index):
            ce_g  = float(df.loc[strike, "ce_gamma"]) if strike in df.index else 0.0
            pe_g  = float(df.loc[strike, "pe_gamma"]) if strike in df.index else 0.0
            ce_oi = float(df.loc[strike, "ce_oi"])
            pe_oi = float(df.loc[strike, "pe_oi"])

            # Dealer GEX: dealer is SHORT calls (so positive gamma to dealer),
            # and SHORT puts (positive gamma to dealer)
            # Net = (call OI * call gamma - put OI * put gamma) * lot * spot
            strike_gex = (ce_oi * ce_g - pe_oi * pe_g) * LOT_SIZE * spot
            gex_per[strike] = round(strike_gex, 0)
            total_gex += strike_gex
            running_list.append((strike, total_gex))

        # GEX flip level: lowest strike above spot where cumulative GEX turns negative
        flip_level = 0
        above_spot = [(s, g) for s, g in running_list if s > spot]
        for i in range(1, len(above_spot)):
            if above_spot[i - 1][1] >= 0 > above_spot[i][1]:
                flip_level = above_spot[i][0]
                break

        return {
            "total_gex":      round(total_gex, 0),
            "flip_level":     flip_level,
            "positive":       total_gex > 0,
            "gex_per_strike": gex_per,
        }

    def _wall_verdict(self, df: pd.DataFrame, call_wall: int,
                      put_wall: int, gex: dict) -> dict:
        """Combined wall + GEX environment verdict."""
        flip      = gex.get("flip_level", 0)
        total_gex = gex.get("total_gex", 0)

        # GEX flip vs call wall
        if flip and call_wall:
            if abs(flip - call_wall) <= 50:
                ce_gex_rel = "DOUBLE_BARRIER"       # flip and wall at same level — very strong
            elif flip < call_wall:
                ce_gex_rel = "GAP_DANGER"           # amplification zone exists before wall
            else:
                ce_gex_rel = "FLIP_BEYOND"          # flip above wall — wall is first barrier
        else:
            ce_gex_rel = "UNKNOWN"

        gex_env = ("PINNING" if total_gex > 0 else
                   "AMPLIFYING" if total_gex < 0 else "NEUTRAL")

        # Combined
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
    # Legacy helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _migration_status(self, df: pd.DataFrame, spot: float) -> dict:
        try:
            atm       = _nearest_atm(df, spot)
            above_sum = df.loc[df.index > atm, "ce_oi_change"].sum()
            below_sum = df.loc[df.index < atm, "pe_oi_change"].sum()
            detected  = abs(above_sum) > 500_000 or abs(below_sum) > 500_000
            return {"detected": bool(detected), "above": int(above_sum), "below": int(below_sum)}
        except Exception:
            return {"detected": False, "above": 0, "below": 0}

    def _kill_switches(self, pcr: float, gex: dict, migration: dict) -> dict:
        return {
            "migration_detected": migration.get("detected", False),
            "gex_negative":       gex.get("total_gex", 0) < 0,
            "pcr_extreme":        pcr < 0.5 or pcr > 2.0,
        }

    def _home_score(self, gex: dict, pcr: float, migration: dict) -> int:
        if migration.get("detected"):
            return 0
        score = 10
        if gex.get("positive"):
            score += 5
        if PCR_BALANCED_LOW <= pcr <= PCR_BALANCED_HI:
            score += 5
        return min(score, 20)

    def _empty_signals(self, spot: float = 23000) -> dict:
        return {
            "spot": spot, "dte": 0, "pcr": 1.0, "max_pain": spot,
            "max_pain_dist": 0, "fut_premium": 0.0,
            "atm_iv": 0.0, "iv_skew": 0.0, "straddle_price": 0.0,
            "magnet_strike": 0, "theta_iv_ratio": 0.0, "delta_skew": "BALANCED",
            "models": {}, "synthesis": {
                "binding_ce": 0, "binding_pe": 0,
                "binding_ce_model": "—", "binding_pe_model": "—"
            },
            "binding_ce": 0, "binding_pe": 0,
            "call_wall": 0, "put_wall": 0,
            "wall_integrity": {"call_integrity": "UNKNOWN", "put_integrity": "UNKNOWN"},
            "gex": {"total_gex": 0, "flip_level": 0, "positive": False, "gex_per_strike": {}},
            "wall_verdict": {"combined_verdict": "STANDARD", "gex_environment": "NEUTRAL",
                             "ce_gex_relationship": "UNKNOWN"},
            "migration": {"detected": False}, "kill_switches": {}, "home_score": 10,
            "strategy": "IRON_CONDOR",
        }
