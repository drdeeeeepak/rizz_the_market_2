# analytics/iv_solver.py
# Implied volatility, solved from the option's traded price.
#
# WHY THIS EXISTS: Kite Connect's quote() does NOT return an implied_volatility
# field. The chain builder read `ce.get("implied_volatility", 0)`, which therefore
# returned 0 on every strike, every time. A comment in options_chain.py asserted
# Kite supplies it — that was an assumption, never true. Everything downstream that
# needs IV bailed out silently:
#     ATM IV → 0 · IV skew → 0 · theta/IV → 0 · delta skew → always BALANCED
#     the whole smile / RR25 / BF25 block → "unavailable"
#     probability of touch → "unavailable"     (all Greeks are 0 when sigma is 0)
# gamma_exposure.py had already discovered this and worked around it with a flat
# 12% fallback, which is why the gamma pages kept working while page 10 did not.
#
# IV is by definition the volatility that makes the model price equal the market
# price, so with spot, strike, expiry and the traded premium we can just solve for
# it. That is what this module does.
#
# TWO ACCURACY CHOICES WORTH KNOWING:
#
# 1. We price off the FORWARD, not spot (Black-76 rather than plain Black-Scholes),
#    and we take the forward from put-call parity on the chain itself:
#        F = K + (C − P)·e^(rT)     at the strike where |C − P| is smallest
#    This matters because Nifty pays dividends and carries a basis. Using spot with
#    an assumed rate biases calls and puts in OPPOSITE directions — and RR25 is
#    exactly "call IV minus put IV", so that bias would land straight on the number.
#    Deriving the forward from the chain removes the dividend and rate guess.
#
# 2. We solve on OTM options only (calls above the forward, puts below). ITM options
#    are mostly intrinsic value, so their price barely moves with volatility and the
#    inversion is numerically unstable. OTM is where the vol information lives, and
#    it is also the branch the smile is quoted on.

import logging

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

log = logging.getLogger(__name__)

RISK_FREE = 0.065

_IV_LO, _IV_HI = 0.005, 5.0      # 0.5% .. 500% — brackets anything real
MIN_PRICE = 0.05                 # below this the quote is a stub, not a price


def black76_price(F: float, K: float, T: float, sigma: float,
                  r: float = RISK_FREE, opt_type: str = "CE") -> float:
    """Undiscounted-forward option price (Black-76)."""
    if T <= 0 or sigma <= 0 or F <= 0 or K <= 0:
        return 0.0
    v = sigma * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    disc = np.exp(-r * T)
    if opt_type.upper() == "CE":
        return float(disc * (F * norm.cdf(d1) - K * norm.cdf(d2)))
    return float(disc * (K * norm.cdf(-d2) - F * norm.cdf(-d1)))


def implied_forward(strikes, ce_ltp, pe_ltp, spot: float, T: float,
                    r: float = RISK_FREE) -> float:
    """
    Forward price implied by put-call parity: F = K + (C − P)·e^(rT).

    Evaluated at the strike with the smallest |C − P|, i.e. nearest the money,
    where both legs are liquid and the parity relation is tightest. Falls back to
    spot·e^(rT) if the chain cannot support it.
    """
    best_F, best_gap = None, None
    for K, c, p in zip(strikes, ce_ltp, pe_ltp):
        try:
            K, c, p = float(K), float(c), float(p)
        except (TypeError, ValueError):
            continue
        if c < MIN_PRICE or p < MIN_PRICE:
            continue
        gap = abs(c - p)
        if best_gap is None or gap < best_gap:
            best_gap, best_F = gap, K + (c - p) * np.exp(r * T)
    if best_F and best_F > 0:
        # Sanity band: a forward more than 5% from spot means the parity strike was
        # illiquid or stale. Prefer the carry estimate over an absurd forward.
        if abs(best_F - spot) / spot <= 0.05:
            return float(best_F)
    return float(spot * np.exp(r * T))


def implied_vol(price: float, F: float, K: float, T: float,
                r: float = RISK_FREE, opt_type: str = "CE") -> float:
    """
    Solve Black-76 for sigma. Returns IV in PERCENT (13.5 = 13.5%), or 0.0 when
    the quote cannot support a solution — never a made-up number.
    """
    try:
        price, F, K, T = float(price), float(F), float(K), float(T)
    except (TypeError, ValueError):
        return 0.0
    if price < MIN_PRICE or T <= 0 or F <= 0 or K <= 0:
        return 0.0

    disc = np.exp(-r * T)
    # No-arbitrage bounds. Outside them no sigma can reproduce the price, which
    # means the quote is stale or crossed — report nothing rather than guess.
    if opt_type.upper() == "CE":
        lo_bound, hi_bound = disc * max(F - K, 0.0), disc * F
    else:
        lo_bound, hi_bound = disc * max(K - F, 0.0), disc * K
    if price <= lo_bound + 1e-9 or price >= hi_bound:
        return 0.0

    def f(sig):
        return black76_price(F, K, T, sig, r, opt_type) - price

    try:
        f_lo, f_hi = f(_IV_LO), f(_IV_HI)
        if f_lo * f_hi > 0:          # price outside the vol range we search
            return 0.0
        sigma = brentq(f, _IV_LO, _IV_HI, xtol=1e-6, maxiter=100)
        return round(float(sigma) * 100.0, 3)
    except Exception:
        return 0.0


def solve_chain_iv(df, spot: float, dte: float, r: float = RISK_FREE):
    """
    Fill ce_iv / pe_iv on a chain DataFrame by solving each OTM leg from its LTP.

    Only overwrites values that are missing or zero, so if a data source ever does
    supply a real IV it is preserved. Adds an 'implied_fwd' attribute on the frame
    for anything that wants the forward we used.

    ITM legs are deliberately left at 0: their price is nearly all intrinsic, so
    inverting them is unstable and the result would be noise dressed as signal.
    Every consumer already treats iv <= 0 as "unavailable".
    """
    if df is None or df.empty:
        return df
    need = ("ce_ltp", "pe_ltp")
    if not all(c in df.columns for c in need):
        return df

    T = max(float(dte), 0.5) / 365.0
    F = implied_forward(df.index, df["ce_ltp"], df["pe_ltp"], spot, T, r)

    ce_out, pe_out = [], []
    for K in df.index:
        row = df.loc[K]
        # CE: solve when OTM (strike above forward). PE: when OTM (below forward).
        ce_existing = float(row["ce_iv"]) if "ce_iv" in df.columns else 0.0
        pe_existing = float(row["pe_iv"]) if "pe_iv" in df.columns else 0.0
        ce_out.append(ce_existing if ce_existing > 0 else
                      (implied_vol(row["ce_ltp"], F, float(K), T, r, "CE")
                       if float(K) >= F else 0.0))
        pe_out.append(pe_existing if pe_existing > 0 else
                      (implied_vol(row["pe_ltp"], F, float(K), T, r, "PE")
                       if float(K) <= F else 0.0))

    df = df.copy()
    df["ce_iv"] = ce_out
    df["pe_iv"] = pe_out
    df.attrs["implied_fwd"] = F

    solved = int((df["ce_iv"] > 0).sum() + (df["pe_iv"] > 0).sum())
    log.info("IV solved for %d legs (forward %.1f, spot %.1f, %.1f DTE)",
             solved, F, spot, dte)
    return df


def fill_atm_gap(df, spot: float):
    """
    Near the forward, the OTM branch has a one-strike hole on each side (the ITM leg
    was skipped). ATM IV readers look up ONE strike, so mirror the solved leg across
    at strikes where only one side solved — put-call parity says a European call and
    put on the same strike share the same implied vol.
    """
    if df is None or df.empty or "ce_iv" not in df.columns:
        return df
    df = df.copy()
    ce, pe = df["ce_iv"].astype(float), df["pe_iv"].astype(float)
    df["ce_iv"] = np.where((ce <= 0) & (pe > 0), pe, ce)
    df["pe_iv"] = np.where((pe <= 0) & (ce > 0), ce, pe)
    return df
