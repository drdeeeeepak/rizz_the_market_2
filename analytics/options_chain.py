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
# Theta/IV ratio = ATM premium decayed per day ÷ 1-day expected move, both in
# index points. It answers "am I being paid enough per day for the risk I carry
# overnight?" — higher is better for a seller.
#
# These were 1.0 / 0.7, which the ratio can NEVER reach: it decays roughly as
# 1/(2·√DTE) and tops out near 0.20 on expiry day. Those thresholds were written
# against the old formula, which multiplied theta by spot a second time and so read
# ~2,500 instead of ~0.11 (see _theta_iv_ratio), leaving the card permanently green.
#
# Values below are MEASURED from this engine (ATM, ~13% IV), not idealised — the
# ratio averages CE and PE theta, and put theta is smaller in magnitude because of
# the positive carry term, so it runs below a single-leg textbook figure:
#     DTE    1     2     3     5     7    10    14    21    30
#     ratio 0.200 0.141 0.115 0.090 0.076 0.064 0.054 0.044 0.037
#
# The biweekly cycle runs 14 DTE entry → 5 DTE exit, so the thresholds are pinned to
# those two points: you open the trade at "borderline", and decay earns its way to
# "good" as the position approaches its exit.
THETA_IV_SELL   = 0.090   # ≈ 5 DTE — the exit end; decay outpacing the daily move
THETA_IV_BORDER = 0.052   # just under the 14 DTE reading, so entry shows amber not red

RISK_FREE = 0.065   # India risk-free rate ~6.5%

# OI migration trigger: today's net OI change on one side, as a fraction of that
# side's standing OI. 12% of the book repositioning in a day is a real shift.
MIGRATION_OI_SHARE = 0.12


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


# ─── IV smile and delta-based skew ───────────────────────────────────────────
#
# The chain currently reports IV at ONE strike (ATM) and calls the difference
# between the ATM put and ATM call "skew". That is the weakest possible reading:
# at the money, puts and calls sit on the same point of the curve, so the number
# is mostly bid-ask noise. The real skew lives in the WINGS.
#
# The industry-standard measures are quoted at 25 delta:
#   RR25 = IV(25Δ call) − IV(25Δ put)
#          how lopsided the curve is. Negative means puts are richer than calls —
#          the normal state for an equity index, because people pay up for crash
#          protection. A sharply MORE negative RR25 means fear is being bid.
#   BF25 = (IV(25Δ call) + IV(25Δ put))/2 − IV(ATM)
#          how curved the smile is, i.e. how much the market is paying for BOTH
#          tails. Rising BF25 means tail risk is being priced on both sides.
#
# Both are read off OTM options only (puts below spot, calls above), which is
# where the liquidity is, and both interpolate IV along the DELTA axis rather
# than snapping to whichever listed strike happens to sit nearest 25 delta.

def iv_smile(df: pd.DataFrame, spot: float, dte: int) -> pd.DataFrame:
    """
    The OTM implied-vol curve: puts below spot, calls above, which is the side of
    each strike that actually trades. Returns a frame with strike, iv, delta,
    side and moneyness — empty if the chain carries no usable IV.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    if "ce_delta" not in df.columns or "pe_delta" not in df.columns:
        df = _enrich_with_greeks(df, spot, dte)

    rows = []
    for k in df.index:
        try:
            strike = float(k)
        except (TypeError, ValueError):
            continue
        side = "CE" if strike >= spot else "PE"
        iv = float(df.loc[k, f"{side.lower()}_iv"]) if f"{side.lower()}_iv" in df.columns else 0.0
        if iv <= 0:
            continue                     # illiquid / no quote — leave a gap, don't invent one
        delta = abs(float(df.loc[k, f"{side.lower()}_delta"]))
        rows.append({"strike": int(strike), "iv": round(iv, 3), "delta": round(delta, 4),
                     "side": side, "moneyness": round((strike - spot) / spot * 100, 2)})
    return pd.DataFrame(rows).set_index("strike").sort_index() if rows else pd.DataFrame()


def iv_at_delta(smile: pd.DataFrame, target_delta: float = 0.25,
                side: str = "CE") -> float:
    """
    IV at an exact delta, linearly interpolated along the delta axis.

    Snapping to the nearest listed strike would quantise the answer to whatever
    50-point grid Nifty happens to use, which moves RR25 around by more than the
    signal itself on a quiet day. Returns 0.0 when the wing is not covered.
    """
    if smile is None or smile.empty:
        return 0.0
    sub = smile[smile["side"] == side.upper()]
    # Keep the OTM branch only: delta below ~0.5, above a floor where quotes are junk.
    sub = sub[(sub["delta"] > 0.01) & (sub["delta"] < 0.55)]
    if len(sub) < 2:
        return 0.0
    s = sub.sort_values("delta")
    d, v = s["delta"].to_numpy(dtype=float), s["iv"].to_numpy(dtype=float)
    if target_delta < d.min() or target_delta > d.max():
        return 0.0                       # do not extrapolate past the quoted wing
    return round(float(np.interp(target_delta, d, v)), 3)


def skew_metrics(df: pd.DataFrame, spot: float, dte: int, atm_iv: float,
                 target_delta: float = 0.25) -> dict:
    """
    Risk reversal and butterfly at `target_delta`, plus the wing IVs they come from.
    Every field is None when the chain does not quote enough of a wing to support it —
    a missing wing must read as missing, not as zero skew.
    """
    smile = iv_smile(df, spot, dte)
    if smile.empty:
        return {"available": False}

    ce_iv = iv_at_delta(smile, target_delta, "CE")
    pe_iv = iv_at_delta(smile, target_delta, "PE")
    if ce_iv <= 0 or pe_iv <= 0:
        return {"available": False, "smile": smile}

    rr = round(ce_iv - pe_iv, 3)
    bf = round((ce_iv + pe_iv) / 2 - float(atm_iv), 3) if atm_iv and atm_iv > 0 else None

    if rr <= -2.0:      read = "Heavy put skew — crash protection being bid hard"
    elif rr <= -0.5:    read = "Normal index put skew"
    elif rr < 0.5:      read = "Flat — unusually symmetric for an index"
    else:               read = "Call skew — upside being chased"

    return {
        "available":  True,
        "delta":      target_delta,
        "rr":         rr,
        "bf":         bf,
        "call_wing_iv": ce_iv,
        "put_wing_iv":  pe_iv,
        "atm_iv":     round(float(atm_iv), 3) if atm_iv else None,
        "read":       read,
        "richer_side": "PUTS" if rr < 0 else "CALLS" if rr > 0 else "EVEN",
        "smile":      smile,
    }


# ─── Probability of touch / finishing ITM ────────────────────────────────────
#
# A short strike does not have to EXPIRE in the money to hurt you — it only has to
# be REACHED, because that is when the leg goes under water, margin rises, and the
# roll decision lands. Probability of touch is therefore the number that matters
# for managing an iron condor, and it is roughly DOUBLE the probability of
# finishing ITM. Reading the 10-delta model as "10% risk" understates the real
# chance of being tested by about half.
#
# Both use the risk-neutral measure. In log space X_t = ln(S_t/S_0) is Brownian
# motion with drift ν = r − σ²/2, and the barrier is b = ln(K/S_0). The touch
# probability is the standard reflection-principle result for a one-sided barrier:
#
#     upper (b > 0):  N((−b+νT)/σ√T) + e^(2νb/σ²)·N((−b−νT)/σ√T)
#     lower (b < 0):  N(( b−νT)/σ√T) + e^(2νb/σ²)·N(( b+νT)/σ√T)
#
# With ν = 0 both collapse to 2·N(−|b|/σ√T) — exactly twice the finish-beyond
# probability, which is where the "double it" rule of thumb comes from.

def prob_touch(spot: float, strike: float, dte: float, iv_pct: float,
               r: float = RISK_FREE) -> float:
    """
    Probability spot TOUCHES `strike` at any point before expiry. 0..1.
    iv_pct is the strike's own implied vol in percent (e.g. 13.5).
    """
    try:
        S, K = float(spot), float(strike)
        T = max(float(dte), 0.0) / 365.0
        sig = float(iv_pct) / 100.0
    except (TypeError, ValueError):
        return 0.0
    if S <= 0 or K <= 0 or sig <= 0:
        return 0.0
    if T <= 0:                       # at expiry it is touched only if already there
        return 1.0 if (K >= S if K > S else K <= S) and abs(K - S) < 1e-9 else 0.0
    if abs(K - S) < 1e-9:
        return 1.0                   # already at the strike

    b   = np.log(K / S)
    nu  = r - 0.5 * sig ** 2
    vol = sig * np.sqrt(T)
    try:
        # e^(2νb/σ²) overflows for far barriers with tiny vol; the term it
        # multiplies underflows faster, so clipping the exponent is safe.
        expo = np.clip(2.0 * nu * b / (sig ** 2), -700, 700)
        if b > 0:                    # upper barrier — call side
            p = norm.cdf((-b + nu * T) / vol) + np.exp(expo) * norm.cdf((-b - nu * T) / vol)
        else:                        # lower barrier — put side
            p = norm.cdf((b - nu * T) / vol) + np.exp(expo) * norm.cdf((b + nu * T) / vol)
        return float(np.clip(p, 0.0, 1.0))
    except Exception:
        return 0.0


def prob_itm(spot: float, strike: float, dte: float, iv_pct: float,
             option_type: str = "CE", r: float = RISK_FREE) -> float:
    """
    Probability the option FINISHES in the money — risk-neutral N(d2) for a call,
    N(−d2) for a put. This is what a strike's delta roughly approximates.
    """
    try:
        S, K = float(spot), float(strike)
        T = max(float(dte), 0.0) / 365.0
        sig = float(iv_pct) / 100.0
    except (TypeError, ValueError):
        return 0.0
    if S <= 0 or K <= 0 or sig <= 0 or T <= 0:
        return 0.0
    d2 = (np.log(S / K) + (r - 0.5 * sig ** 2) * T) / (sig * np.sqrt(T))
    return float(norm.cdf(d2) if option_type == "CE" else norm.cdf(-d2))


def strike_iv(df: pd.DataFrame, strike: int, side: str, fallback_pct: float) -> float:
    """
    That strike's OWN implied vol, falling back to ATM only when Kite returns 0.
    Using a flat ATM IV understates far-OTM risk, because skew prices those
    strikes at a higher vol than ATM — which is exactly where short legs sit.
    """
    col = f"{side.lower()}_iv"
    try:
        if col in df.columns and strike in df.index:
            v = float(df.loc[strike, col])
            if v > 0:
                return v
    except Exception:
        pass
    return float(fallback_pct or 0.0)


def strike_risk(df: pd.DataFrame, spot: float, strike: int, dte: float,
                side: str, fallback_iv: float) -> dict:
    """Full risk read for one short strike: touch, finish-ITM, and the gap between."""
    if not strike or strike <= 0:
        return {"available": False}
    iv = strike_iv(df, int(strike), side, fallback_iv)
    if iv <= 0:
        return {"available": False}
    pt  = prob_touch(spot, strike, dte, iv)
    pi  = prob_itm(spot, strike, dte, iv, option_type=side.upper())
    return {
        "available":    True,
        "strike":       int(strike),
        "side":         side.upper(),
        "iv":           round(iv, 2),
        "distance_pts": round(float(strike) - float(spot), 0),
        "distance_pct": round((float(strike) - float(spot)) / float(spot) * 100, 2),
        "prob_touch":   round(pt, 4),
        "prob_itm":     round(pi, 4),
        "prob_safe":    round(1.0 - pt, 4),   # never tested at all
        "touch_mult":   round(pt / pi, 2) if pi > 0 else None,
    }


def _nearest_atm(df: pd.DataFrame, spot: float) -> int:
    """
    Return the strike in df.index closest to spot.
    Handles the case where exact ATM (round to 50) is not in the chain
    (e.g. chain only covers ±500 pts and spot is at an edge).
    """
    if df.empty:
        return int(round(spot / OI_STRIKE_STEP) * OI_STRIKE_STEP)
    # NOTE: must build the Series from the INDEX, then subtract.
    # (df.index - spot).to_series() makes the *differences* both the index and the
    # values, so idxmin() returned the smallest difference (0.0) instead of the
    # strike — i.e. this function returned 0 on every call. That silently zeroed
    # ATM IV, IV skew, straddle, theta/IV, delta skew and the IV-expected-move and
    # straddle strike models, because each of them bails on `atm not in df.index`.
    diffs = (df.index.to_series() - spot).abs()
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
        # Wing skew. iv_skew above is the ATM put-minus-call difference, which is
        # mostly bid-ask noise because both legs sit on the same point of the curve.
        # RR25/BF25 read the actual wings. Both are kept — iv_skew is still shown.
        skew = skew_metrics(df, spot, dte, atm_iv)

        # ── Section 3: Five strike models + synthesis ─────────────────────────
        models    = self._five_models(df, spot, dte, atr14, va_buf_mult,
                                      atm_iv, straddle, call_wall, put_wall)
        synthesis = self._strike_synthesis(models)

        # ── Section 3b: Risk on the binding strikes ───────────────────────────
        # Probability of being TESTED, not just of finishing ITM — for a short leg
        # the test is what triggers the roll, so it is the number that matters.
        risk = {
            "ce": strike_risk(df, spot, synthesis["binding_ce"], dte, "CE", atm_iv),
            "pe": strike_risk(df, spot, synthesis["binding_pe"], dte, "PE", atm_iv),
        }

        # ── Section 4: Wall and GEX analysis ─────────────────────────────────
        gex          = self._gex(df, spot, dte, atm_iv)
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
            "skew":           skew,
            # Section 3
            "models":         models,
            "synthesis":      synthesis,
            "binding_ce":     synthesis["binding_ce"],
            "binding_pe":     synthesis["binding_pe"],
            "strike_risk":    risk,
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
        total_pe = float(active["pe_oi"].sum())
        total_ce = float(active["ce_oi"].sum())
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

        # _bs_greeks returns theta ALREADY in index points per day (the BS formula
        # is denominated in the same units as S). The old code multiplied it by spot
        # again, inflating the ratio ~25,000× — it read 2,500 instead of 0.11 and so
        # sat permanently above the 1.0 "good" threshold. This was invisible until
        # _nearest_atm was fixed, because atm resolved to 0 and this bailed out at 0.0.
        # Ratio = premium decayed per day ÷ 1-day expected move, both in points.
        theta_pts = avg_theta
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

    def _gex(self, df: pd.DataFrame, spot: float, dte: int, atm_iv: float) -> dict:
        """
        Dealer gamma exposure — delegated to analytics.gamma_exposure.compute_gex,
        the single GEX engine in this repo. Pages 18/19 already use it directly.

        Dealer convention (industry standard): dealers are net LONG calls (+gamma)
        and SHORT puts (−gamma).
            POSITIVE net gamma → dealers cushion: sell rallies, buy dips → PINNING
            NEGATIVE net gamma → dealers amplify: sell dips, buy rallies → AMPLIFYING

        This replaces a local implementation that was wrong in three ways:
          • flip level walked the CUMULATIVE SUM of per-strike GEX across strikes
            and reported the first sign change. That is an artifact of strike
            ordering, not a flip level — the real flip is the SPOT price at which
            net dealer gamma crosses zero, which needs re-pricing on a spot grid
            (what compute_gex._flip_level does).
          • it scaled by LOT_SIZE × spot while compute_gex uses spot² × 0.01, so
            pages 10/10B and pages 18/19 printed different numbers both labelled
            "GEX" — and page 10's flip level disagreed with page 18's.
          • its docstring had the sign convention inverted ("positive = dealers
            short gamma"), which is the opposite of what the formula computes.

        Output keys are unchanged so pages 10 / 10B / compute_signals / home_engine
        keep working; extra keys are additive.
        """
        from analytics.gamma_exposure import compute_gex

        g = compute_gex(df, spot, dte, iv_fallback_pct=(atm_iv if atm_iv > 0 else 12.0))
        prof = g.get("profile")
        per_strike = {}
        if prof is not None and not prof.empty and "gex_net" in prof.columns:
            per_strike = {int(k): round(float(v), 0) for k, v in prof["gex_net"].items()}

        flip = g.get("flip_level")
        return {
            "total_gex":      round(float(g.get("net_gex", 0.0)), 0),
            "flip_level":     int(round(flip)) if flip else 0,
            "positive":       g.get("regime") == "POSITIVE",
            "gex_per_strike": per_strike,
            # additive — the richer read from the shared engine
            "regime":            g.get("regime", "UNKNOWN"),
            "spot_vs_flip_pts":  g.get("spot_vs_flip_pts"),
            "gamma_call_wall":   g.get("call_wall"),
            "gamma_put_wall":    g.get("put_wall"),
            "headline":          g.get("gex_headline", ""),
            "verdict":           g.get("gex_verdict", "UNKNOWN"),
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
        """
        Has today's OI flow moved enough to count as real repositioning?

        Threshold is a SHARE of the side's standing OI, not a flat contract count.
        It was `> 500_000` absolute, which meant the trigger fired constantly on a
        heavy monthly chain and essentially never on a thin weekly one — the same
        flow read as "migration" or "quiet" purely from which expiry was loaded.
        """
        try:
            atm       = _nearest_atm(df, spot)
            above     = df.loc[df.index > atm]
            below     = df.loc[df.index < atm]
            above_sum = above["ce_oi_change"].sum()
            below_sum = below["pe_oi_change"].sum()
            above_base = float(above["ce_oi"].sum())
            below_base = float(below["pe_oi"].sum())
            detected = (
                (above_base > 0 and abs(above_sum) / above_base > MIGRATION_OI_SHARE) or
                (below_base > 0 and abs(below_sum) / below_base > MIGRATION_OI_SHARE)
            )
            return {"detected": bool(detected), "above": int(above_sum), "below": int(below_sum)}
        except Exception:
            return {"detected": False, "above": 0, "below": 0}

    def _kill_switches(self, pcr: float, gex: dict, migration: dict) -> dict:
        # Cast to plain bool: pcr comes off numpy sums, so the comparisons yield
        # numpy.bool_, which json.dumps refuses without a custom encoder.
        return {
            "migration_detected": bool(migration.get("detected", False)),
            "gex_negative":       bool(gex.get("total_gex", 0) < 0),
            "pcr_extreme":        bool(pcr < 0.5 or pcr > 2.0),
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
            "skew": {"available": False},
            "models": {}, "synthesis": {
                "binding_ce": 0, "binding_pe": 0,
                "binding_ce_model": "—", "binding_pe_model": "—"
            },
            "binding_ce": 0, "binding_pe": 0,
            "strike_risk": {"ce": {"available": False}, "pe": {"available": False}},
            "call_wall": 0, "put_wall": 0,
            "wall_integrity": {"call_integrity": "UNKNOWN", "put_integrity": "UNKNOWN"},
            "gex": {"total_gex": 0, "flip_level": 0, "positive": False, "gex_per_strike": {},
                    "regime": "UNKNOWN", "spot_vs_flip_pts": None,
                    "gamma_call_wall": None, "gamma_put_wall": None,
                    "headline": "", "verdict": "UNKNOWN"},
            "wall_verdict": {"combined_verdict": "STANDARD", "gex_environment": "NEUTRAL",
                             "ce_gex_relationship": "UNKNOWN"},
            "migration": {"detected": False}, "kill_switches": {}, "home_score": 10,
            "strategy": "IRON_CONDOR",
        }
