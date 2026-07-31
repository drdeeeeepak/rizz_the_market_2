# analytics/oi_analytics.py
# Page 10C — OI Intelligence. The reads that were missing from pages 10 / 10B.
#
# Two families of metric live here:
#
#   SNAPSHOT  — computed from today's chain alone, so they work from the first run:
#               buildup quadrants per strike, volume/OI conviction, OI concentration.
#
#   HISTORY   — computed from data/oi_history.py, so they stay blank until the EOD
#               job has logged a few days: wall migration, max-pain drift, PCR
#               percentile, rollover %. Never faked or interpolated when absent.
#
# The buildup read is the important one. OI direction ALONE cannot tell you whether
# a wall is real: open interest rises both when someone buys an option and when
# someone writes one. Pairing the OI change with the PREMIUM change separates them,
# which is the difference between "resistance is being built" and "people are
# betting on a breakout".

import numpy as np
import pandas as pd

from config import (
    BUILDUP_OI_NOISE_PCT, BUILDUP_PRICE_NOISE_PCT,
    VOL_OI_CHURN, VOL_OI_CONVICTION,
)

# ── Buildup quadrants ─────────────────────────────────────────────────────────

LONG_BUILDUP   = "Long buildup"      # OI ↑ premium ↑ — fresh BUYING
SHORT_BUILDUP  = "Short buildup"     # OI ↑ premium ↓ — fresh WRITING
LONG_UNWIND    = "Long unwinding"    # OI ↓ premium ↓ — buyers giving up
SHORT_COVER    = "Short covering"    # OI ↓ premium ↑ — writers buying back
FLAT           = "Flat"

# What each quadrant means for a wall on that side of the chain.
# A CALL strike being written into is resistance forming; the same strike being
# covered is resistance dissolving — the single most useful thing this page says.
BUILDUP_MEANING = {
    ("CE", LONG_BUILDUP):  ("Traders buying calls — betting price goes ABOVE this strike", "bear_ce"),
    ("CE", SHORT_BUILDUP): ("Fresh call writing — resistance BUILDING here", "bull_ce"),
    ("CE", LONG_UNWIND):   ("Call buyers giving up — upside bets being closed", "bull_ce"),
    ("CE", SHORT_COVER):   ("Call writers buying back — resistance DISSOLVING", "bear_ce"),
    ("PE", LONG_BUILDUP):  ("Traders buying puts — betting price goes BELOW this strike", "bear_pe"),
    ("PE", SHORT_BUILDUP): ("Fresh put writing — support BUILDING here", "bull_pe"),
    ("PE", LONG_UNWIND):   ("Put buyers giving up — downside bets being closed", "bull_pe"),
    ("PE", SHORT_COVER):   ("Put writers buying back — support DISSOLVING", "bear_pe"),
}


def classify_buildup(oi_pct: float, price_pct: float) -> str:
    """
    One strike, one side → which of the four quadrants (or Flat).

    Both moves must clear a noise band, otherwise a strike that barely traded gets
    labelled as if something happened. Thresholds live in config.
    """
    try:
        oi_pct, price_pct = float(oi_pct), float(price_pct)
    except (TypeError, ValueError):
        return FLAT
    if abs(oi_pct) < BUILDUP_OI_NOISE_PCT or abs(price_pct) < BUILDUP_PRICE_NOISE_PCT:
        return FLAT
    if oi_pct > 0:
        return LONG_BUILDUP if price_pct > 0 else SHORT_BUILDUP
    return SHORT_COVER if price_pct > 0 else LONG_UNWIND


def buildup_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-strike buildup for both sides, plus the plain-English meaning.
    Returns a frame indexed by strike; empty in, empty out.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    need = ("ce_pct_change", "ce_price_pct", "pe_pct_change", "pe_price_pct")
    if not all(c in df.columns for c in need):
        return pd.DataFrame()

    out = pd.DataFrame(index=df.index)
    out["ce_oi"]        = df["ce_oi"]
    out["ce_oi_pct"]    = df["ce_pct_change"].round(1)
    out["ce_price_pct"] = df["ce_price_pct"].round(1)
    out["ce_buildup"]   = [classify_buildup(o, p)
                           for o, p in zip(df["ce_pct_change"], df["ce_price_pct"])]
    out["pe_oi"]        = df["pe_oi"]
    out["pe_oi_pct"]    = df["pe_pct_change"].round(1)
    out["pe_price_pct"] = df["pe_price_pct"].round(1)
    out["pe_buildup"]   = [classify_buildup(o, p)
                           for o, p in zip(df["pe_pct_change"], df["pe_price_pct"])]
    out["ce_meaning"]   = [BUILDUP_MEANING.get(("CE", b), ("—", ""))[0] for b in out["ce_buildup"]]
    out["pe_meaning"]   = [BUILDUP_MEANING.get(("PE", b), ("—", ""))[0] for b in out["pe_buildup"]]
    return out


def buildup_summary(bt: pd.DataFrame, spot: float) -> dict:
    """
    Chain-level read: what is happening ABOVE spot (the CE leg's territory) and
    BELOW spot (the PE leg's), weighted by how much OI sits behind each quadrant.
    """
    if bt is None or bt.empty:
        return {}
    above = bt[bt.index > spot]
    below = bt[bt.index < spot]

    def _dom(sub: pd.DataFrame, side: str) -> tuple:
        """Quadrant holding the most OI on this side, and its share."""
        if sub.empty:
            return FLAT, 0.0
        col, oicol = f"{side}_buildup", f"{side}_oi"
        grp = sub.groupby(col)[oicol].sum()
        grp = grp.drop(FLAT, errors="ignore")
        tot = float(sub[oicol].sum())
        if grp.empty or tot <= 0:
            return FLAT, 0.0
        return str(grp.idxmax()), round(float(grp.max()) / tot, 3)

    ce_q, ce_share = _dom(above, "ce")
    pe_q, pe_share = _dom(below, "pe")
    return {
        "ce_dominant": ce_q, "ce_share": ce_share,
        "pe_dominant": pe_q, "pe_share": pe_share,
        "ce_note": BUILDUP_MEANING.get(("CE", ce_q), ("No clear pattern above spot", ""))[0],
        "pe_note": BUILDUP_MEANING.get(("PE", pe_q), ("No clear pattern below spot", ""))[0],
        "ce_bias": BUILDUP_MEANING.get(("CE", ce_q), ("", ""))[1],
        "pe_bias": BUILDUP_MEANING.get(("PE", pe_q), ("", ""))[1],
    }


# ── Volume vs OI — conviction or churn ────────────────────────────────────────

def volume_oi_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Volume ÷ OI per strike. High volume against unchanged OI means contracts were
    passed between day traders and closed again — churn, not positioning. A wall
    with heavy volume but a low ratio is being defended; a low-volume wall is
    stale inventory nobody is actively maintaining.

    ce_vol / pe_vol were already fetched on every refresh and used nowhere.
    """
    if df is None or df.empty or "ce_vol" not in df.columns:
        return pd.DataFrame()
    out = pd.DataFrame(index=df.index)
    for side in ("ce", "pe"):
        oi  = df[f"{side}_oi"].astype(float)
        vol = df[f"{side}_vol"].astype(float)
        ratio = np.where(oi > 0, vol / oi, 0.0)
        out[f"{side}_vol"]   = vol.astype(int)
        out[f"{side}_ratio"] = np.round(ratio, 2)
        out[f"{side}_read"]  = [
            "Churn — day trading, not positioning" if r >= VOL_OI_CHURN else
            "Active — real interest today"          if r >= VOL_OI_CONVICTION else
            "Quiet — stale inventory"
            for r in ratio
        ]
    return out


# ── Concentration ─────────────────────────────────────────────────────────────

def concentration(df: pd.DataFrame) -> dict:
    """
    Is OI packed into a few strikes or smeared across the chain?
    Concentrated = sharp, defensible levels. Diffuse = the "wall" is a soft zone.

    top3 = share of the side's OI in its 3 biggest strikes.
    hhi  = Herfindahl index (sum of squared shares); higher = more concentrated.
    """
    if df is None or df.empty:
        return {}
    out = {}
    for side in ("ce", "pe"):
        s = df[f"{side}_oi"].astype(float)
        tot = float(s.sum())
        if tot <= 0:
            out[f"{side}_top3"] = out[f"{side}_hhi"] = None
            continue
        shares = s / tot
        out[f"{side}_top3"] = round(float(s.nlargest(3).sum()) / tot, 3)
        out[f"{side}_hhi"]  = round(float((shares ** 2).sum()), 4)
    return out


# ── History-backed series (blank until the EOD job has logged days) ───────────

def history_series(side: str = "far") -> pd.DataFrame:
    """Daily OI history as a frame. Empty until data/oi_history.json has rows."""
    try:
        from data.oi_history import history_frame
        return history_frame(side)
    except Exception:
        return pd.DataFrame()


def pcr_percentile(side: str = "far", current_pcr: float = None) -> dict:
    """
    Where today's PCR sits in its own recorded history — the "is 1.15 actually
    high?" answer that a bare number can never give.
    """
    df = history_series(side)
    if df.empty or "pcr" not in df.columns:
        return {"available": False, "days": 0}
    s = pd.to_numeric(df["pcr"], errors="coerce").dropna()
    if s.empty:
        return {"available": False, "days": 0}
    val = float(current_pcr) if current_pcr is not None else float(s.iloc[-1])
    from data.oi_history import percentile_of
    return {
        "available": True, "days": int(len(s)), "value": round(val, 3),
        "pctl": percentile_of(s, val),
        "min": round(float(s.min()), 3), "max": round(float(s.max()), 3),
        "median": round(float(s.median()), 3),
    }


def drift(side: str = "far", col: str = "max_pain", lookback: int = 10) -> dict:
    """Change in a history column over the last `lookback` recorded days."""
    df = history_series(side)
    if df.empty or col not in df.columns:
        return {"available": False, "days": 0}
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(s) < 2:
        return {"available": False, "days": int(len(s))}
    window = s.iloc[-lookback:]
    return {
        "available": True, "days": int(len(window)),
        "first": float(window.iloc[0]), "last": float(window.iloc[-1]),
        "change": float(window.iloc[-1] - window.iloc[0]),
        "series": window,
    }


def intraday_frame() -> pd.DataFrame:
    """Today's intraday OI points, flattened. Empty before the first page load."""
    try:
        from data.oi_history import load_intraday_today
        rows = load_intraday_today()
    except Exception:
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    recs = []
    for r in rows:
        far = r.get("far") or {}
        near = r.get("near") or {}
        recs.append({
            "time": r.get("time"), "spot": r.get("spot"),
            "far_pcr": far.get("pcr"), "far_call_wall": far.get("call_wall"),
            "far_put_wall": far.get("put_wall"),
            "far_ce_oi": far.get("total_ce_oi"), "far_pe_oi": far.get("total_pe_oi"),
            "near_pcr": near.get("pcr"),
        })
    df = pd.DataFrame(recs)
    return df.set_index("time") if not df.empty else df
