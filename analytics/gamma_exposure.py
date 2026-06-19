# analytics/gamma_exposure.py
# Dealer Gamma Exposure (GEX) + Gamma-Flip engine — Page 18 (Conviction Radar)
#
# WHAT THIS ANSWERS (in plain words):
#   "If Nifty falls today, will the dip get bought back (be patient), or will it
#    keep falling (get out)?"  The single best structural answer comes from where
#    the big option dealers are positioned in GAMMA.
#
#   POSITIVE gamma  → dealers act as shock-absorbers: they SELL rallies and BUY
#                     dips. Moves get cushioned → falls usually recover, late
#                     bounces tend to hold. Patience is rewarded.
#   NEGATIVE gamma  → dealers act as accelerators: they SELL dips and BUY rallies.
#                     Moves feed on themselves → falls snowball, bounces fail.
#                     Do NOT wait for a V-recovery; defend the threatened leg.
#
#   GAMMA FLIP LEVEL = the price that separates the two worlds. Above it = calm
#   / mean-reverting. Below it = fast / trending. It is the single most useful
#   number this whole page produces.
#
# All heavy maths (Black-Scholes gamma, dealer-sign convention, flip search by
# repricing) is done here. The page only shows the plain-English verdict.

import math
import logging

import numpy as np
import pandas as pd

try:
    from scipy.stats import norm
    _NPDF = norm.pdf
except Exception:                       # scipy always present per requirements
    def _NPDF(x):
        return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

log = logging.getLogger(__name__)

RISK_FREE = 0.065


# ── Black-Scholes gamma (same convention as pages/16_Gamma_Roll.py) ────────────

def bs_gamma(S: float, K: float, T: float, iv_dec: float) -> float:
    """Black-Scholes gamma. T in years, iv as decimal (0.12 = 12%)."""
    if T <= 0 or iv_dec <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (RISK_FREE + 0.5 * iv_dec ** 2) * T) / (iv_dec * math.sqrt(T))
        return _NPDF(d1) / (S * iv_dec * math.sqrt(T))
    except Exception:
        return 0.0


def _strike_iv(row, side: str, fallback_dec: float) -> float:
    """Pick a usable IV (decimal) for one leg, falling back when Kite returns 0."""
    raw = row.get(f"{side}_iv", 0) or 0
    iv = float(raw) / 100.0
    if iv <= 0.001:
        return fallback_dec
    return iv


def compute_gex(chain_df: pd.DataFrame, spot: float, dte: int,
                iv_fallback_pct: float = 12.0) -> dict:
    """
    Compute the dealer-gamma profile from one option chain snapshot.

    chain_df : DataFrame indexed by strike with columns ce_oi, pe_oi, ce_iv, pe_iv
               (exactly what data.live_fetcher.get_options_chain returns).
    spot     : current Nifty spot.
    dte      : days to expiry for this chain.

    Returns a dict with the per-strike profile plus the headline numbers and a
    plain-English read. Dealer-sign convention (industry standard):
        dealers are net LONG calls (+gamma) and SHORT puts (-gamma).
    Net positive  → positive-gamma (mean-reverting) regime.
    """
    if chain_df is None or chain_df.empty or spot <= 0:
        return _empty_gex(spot)

    fb = max(iv_fallback_pct, 1.0) / 100.0
    T = max(int(dte), 0.5) / 365.0
    unit = spot * spot * 0.01            # scales gamma → $ per 1% move (relative)

    rows = []
    for K, r in chain_df.iterrows():
        try:
            K = float(K)
        except Exception:
            continue
        ce_iv = _strike_iv(r, "ce", fb)
        pe_iv = _strike_iv(r, "pe", fb)
        ce_oi = float(r.get("ce_oi", 0) or 0)
        pe_oi = float(r.get("pe_oi", 0) or 0)
        g_ce = bs_gamma(spot, K, T, ce_iv)
        g_pe = bs_gamma(spot, K, T, pe_iv)
        gex_ce = g_ce * ce_oi * unit        # calls: +gamma to dealers
        gex_pe = -g_pe * pe_oi * unit       # puts:  -gamma to dealers
        rows.append({
            "strike": K, "ce_iv": ce_iv, "pe_iv": pe_iv,
            "ce_oi": ce_oi, "pe_oi": pe_oi,
            "gex_ce": gex_ce, "gex_pe": gex_pe, "gex_net": gex_ce + gex_pe,
        })

    if not rows:
        return _empty_gex(spot)

    prof = pd.DataFrame(rows).set_index("strike").sort_index()

    net_total = float(prof["gex_net"].sum())
    regime = "POSITIVE" if net_total >= 0 else "NEGATIVE"

    # Walls = the strikes that pin price the hardest (biggest gamma magnets).
    call_wall = float(prof["gex_ce"].idxmax()) if prof["gex_ce"].max() > 0 else None
    put_wall = float(prof["gex_pe"].idxmin()) if prof["gex_pe"].min() < 0 else None

    flip = _flip_level(prof, spot, T, fb)

    spot_vs_flip = (spot - flip) if flip is not None else None

    out = {
        "profile": prof,
        "net_gex": net_total,
        "regime": regime,
        "flip_level": flip,
        "spot_vs_flip_pts": round(spot_vs_flip) if spot_vs_flip is not None else None,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "dte": int(dte),
        "spot": spot,
    }
    out.update(_plain_english(out))
    return out


def _flip_level(prof: pd.DataFrame, spot: float, T: float, fb: float):
    """
    Find the gamma-flip price by RE-PRICING net dealer gamma at a grid of
    hypothetical spot levels (the proper method, cheap at this size).
    Returns the price where net dealer gamma crosses zero nearest to spot.
    """
    try:
        strikes = prof.index.values.astype(float)
        ce_oi = prof["ce_oi"].values
        pe_oi = prof["pe_oi"].values
        ce_iv = prof["ce_iv"].values
        pe_iv = prof["pe_iv"].values

        grid = np.linspace(spot * 0.95, spot * 1.05, 81)
        net = np.zeros_like(grid)
        for i, S in enumerate(grid):
            u = S * S * 0.01
            tot = 0.0
            for j, K in enumerate(strikes):
                tot += bs_gamma(S, K, T, ce_iv[j] or fb) * ce_oi[j] * u
                tot -= bs_gamma(S, K, T, pe_iv[j] or fb) * pe_oi[j] * u
            net[i] = tot

        sign = np.sign(net)
        crossings = np.where(np.diff(sign) != 0)[0]
        if len(crossings) == 0:
            return None
        # Pick the zero-crossing nearest to current spot, linear-interpolated.
        best = min(crossings, key=lambda k: abs(grid[k] - spot))
        x0, x1 = grid[best], grid[best + 1]
        y0, y1 = net[best], net[best + 1]
        if (y1 - y0) == 0:
            return float((x0 + x1) / 2)
        return float(x0 - y0 * (x1 - x0) / (y1 - y0))
    except Exception as e:
        log.warning("flip-level search failed: %s", e)
        return None


def _plain_english(g: dict) -> dict:
    """Turn the numbers into a one-line headline + a paragraph anyone can read."""
    regime = g["regime"]
    flip = g["flip_level"]
    spot = g["spot"]
    svf = g["spot_vs_flip_pts"]

    if regime == "POSITIVE":
        headline = "🛡️ SHOCK-ABSORBER MODE — dips tend to get bought back"
        body = ("Big option players are positioned so that they cushion the market: "
                "they sell into rallies and buy into dips. Falls are usually "
                "recoverable and late-day bounces tend to stick. If you are forced "
                "to act against a move, you can generally afford to be patient.")
        verdict = "PATIENCE-FRIENDLY"
    else:
        headline = "⚠️ ACCELERATOR MODE — falls can snowball, bounces can fail"
        body = ("Big option players are positioned so that they amplify the market: "
                "they sell into dips and buy into rallies. A fall can feed on itself "
                "and a bounce can be a trap. Do NOT count on a V-shaped recovery — "
                "protect the threatened side first.")
        verdict = "DEFENSIVE"

    if flip is not None:
        side = "above" if (svf or 0) >= 0 else "below"
        flip_line = (f"Line in the sand: ~{flip:,.0f}. Spot is {abs(svf):,} pts {side} it. "
                     f"Above this line the market behaves calmly; below it, it moves fast.")
        # The live regime is governed by where spot sits vs the flip.
        if (svf or 0) < 0 and regime == "POSITIVE":
            body += (" ⚠️ Note: spot is currently BELOW the flip line even though the "
                     "overall book is positive — treat moves as faster than usual until "
                     "price reclaims the line.")
    else:
        flip_line = "Flip line could not be located in the near-the-money strikes."

    return {"gex_headline": headline, "gex_body": body,
            "gex_flip_line": flip_line, "gex_verdict": verdict}


def _empty_gex(spot: float) -> dict:
    return {
        "profile": pd.DataFrame(),
        "net_gex": 0.0, "regime": "UNKNOWN", "flip_level": None,
        "spot_vs_flip_pts": None, "call_wall": None, "put_wall": None,
        "dte": 0, "spot": spot,
        "gex_headline": "Gamma data unavailable",
        "gex_body": "Option chain could not be read — gamma regime unknown.",
        "gex_flip_line": "—", "gex_verdict": "UNKNOWN",
    }
