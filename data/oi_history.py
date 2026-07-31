# data/oi_history.py
# Option-chain history — Kite serves NO historical option open interest, so nothing
# here can ever be back-filled. It is logged FORWARD, exactly like gamma_history.py:
#
#   • Daily summary  → written by the EOD job into data/oi_history.json (committed),
#                      building a real day-by-day record from the first run onward.
#   • Intraday today → appended on each live page load into data/oi_today.json
#                      (ephemeral / gitignored), so today's session can be replayed.
#   • Per-strike     → scripts/run_scan.py --snapshot already writes the full chain to
#                      data/parquet/{date}_{near,far}_chain.parquet (also committed).
#                      load_chain_history() reads those back for per-strike work.
#
# Days with no Kite login have no token → no chain → that day is simply MISSING.
# It is shown as a gap, never interpolated or faked.
#
# WHY THIS EXISTS: every metric below needs a time series, and none of them were
# possible before — the app only ever saw today's number versus yesterday's:
#   max-pain drift · PCR percentile · wall migration · rollover % · OI concentration
#   trend · intraday wall build rate · per-strike buildup across days.

import json
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd
import pytz

log = logging.getLogger(__name__)

_DIR = Path(__file__).resolve().parent
DAILY_FILE = _DIR / "oi_history.json"      # committed by the EOD job
TODAY_FILE = _DIR / "oi_today.json"        # ephemeral intraday log (gitignored)
PARQUET_DIR = _DIR / "parquet"             # per-strike chains, written by run_scan
IST = pytz.timezone("Asia/Kolkata")

_MAX_DAILY = 400        # ~18 months of trading days
_MAX_TODAY = 420        # ~1 point/min through a 6h15m session, with headroom


def _today_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


# ── Chain summary ─────────────────────────────────────────────────────────────

def _f(x, nd=2):
    """float() with a None guard, rounded — keeps the JSON small and readable."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd)


def summarise_chain(df: pd.DataFrame, spot: float) -> dict:
    """
    Compact, durable summary of ONE expiry's chain.

    Deliberately small: this file is rewritten and committed every day, so it stores
    scalars only. Anything needing per-strike detail reads the parquet snapshots via
    load_chain_history() instead.
    """
    if df is None or df.empty or "ce_oi" not in df.columns:
        return {}

    ce, pe = df["ce_oi"].astype(float), df["pe_oi"].astype(float)
    tot_ce, tot_pe = float(ce.sum()), float(pe.sum())
    if tot_ce <= 0 and tot_pe <= 0:
        return {}

    # Max pain — reuse the engine so there is one implementation, not two.
    try:
        from analytics.options_chain import OptionsChainEngine
        max_pain = float(OptionsChainEngine()._max_pain(df))
    except Exception as e:
        log.warning("max pain in OI snapshot failed: %s", e)
        max_pain = None

    def _wall(s):
        return int(s.idxmax()) if s.max() > 0 else None

    def _cog(s):
        """OI-weighted average strike — 'centre of gravity' of the positioning."""
        tot = float(s.sum())
        return _f((s.index.to_series() * s).sum() / tot, 0) if tot > 0 else None

    def _top3(s):
        """Share of the side's OI sitting in its 3 biggest strikes. High = sharp,
        well-defined levels. Low = OI smeared across the chain, vaguer levels."""
        tot = float(s.sum())
        return _f(float(s.nlargest(3).sum()) / tot, 4) if tot > 0 else None

    atm = int((df.index.to_series() - spot).abs().idxmin())
    atm_ce_iv = _f(df.loc[atm, "ce_iv"]) if "ce_iv" in df.columns else None
    atm_pe_iv = _f(df.loc[atm, "pe_iv"]) if "pe_iv" in df.columns else None
    atm_iv = None
    if atm_ce_iv and atm_pe_iv and atm_ce_iv > 0 and atm_pe_iv > 0:
        atm_iv = _f((atm_ce_iv + atm_pe_iv) / 2)

    straddle = None
    if "ce_ltp" in df.columns and "pe_ltp" in df.columns:
        c, p = _f(df.loc[atm, "ce_ltp"]), _f(df.loc[atm, "pe_ltp"])
        if c and p and c > 0 and p > 0:
            straddle = _f(c + p)

    return {
        "strikes":      int(len(df)),
        "total_ce_oi":  int(tot_ce),
        "total_pe_oi":  int(tot_pe),
        "pcr":          _f(tot_pe / tot_ce, 3) if tot_ce > 0 else None,
        "max_pain":     _f(max_pain, 0),
        "call_wall":    _wall(ce),
        "put_wall":     _wall(pe),
        "call_wall_oi": int(ce.max()) if tot_ce > 0 else 0,
        "put_wall_oi":  int(pe.max()) if tot_pe > 0 else 0,
        "ce_cog":       _cog(ce),
        "pe_cog":       _cog(pe),
        "ce_top3":      _top3(ce),
        "pe_top3":      _top3(pe),
        "atm_iv":       atm_iv,
        "atm_ce_iv":    atm_ce_iv,
        "atm_pe_iv":    atm_pe_iv,
        "iv_skew":      _f(atm_pe_iv - atm_ce_iv) if (atm_ce_iv and atm_pe_iv) else None,
        "straddle":     straddle,
        "ce_oi_change": int(df["ce_oi_change"].sum()) if "ce_oi_change" in df.columns else 0,
        "pe_oi_change": int(df["pe_oi_change"].sum()) if "pe_oi_change" in df.columns else 0,
    }


def build_snapshot(near_df: pd.DataFrame, far_df: pd.DataFrame, spot: float,
                   near_expiry=None, far_expiry=None,
                   near_dte: int = 0, far_dte: int = 0) -> dict:
    """One point in the history: both expiries plus the cross-expiry reads."""
    near = summarise_chain(near_df, spot)
    far  = summarise_chain(far_df,  spot)
    if not near and not far:
        return {}

    # Rollover: what share of total OI has moved out to the far expiry. Rises through
    # expiry week as positions roll forward; a stalled rollover means people are
    # letting positions expire rather than carrying them.
    n_tot = (near.get("total_ce_oi", 0) or 0) + (near.get("total_pe_oi", 0) or 0)
    f_tot = (far.get("total_ce_oi", 0) or 0) + (far.get("total_pe_oi", 0) or 0)
    rollover = _f(f_tot / (n_tot + f_tot), 4) if (n_tot + f_tot) > 0 else None

    # IV term structure: far ATM IV minus near ATM IV. Negative (inverted) means the
    # near expiry is pricing more risk than the far one — an event is expected soon.
    n_iv, f_iv = near.get("atm_iv"), far.get("atm_iv")
    term = _f(f_iv - n_iv) if (n_iv and f_iv) else None

    return {
        "spot":         _f(spot, 1),
        "near_expiry":  str(near_expiry) if near_expiry else None,
        "far_expiry":   str(far_expiry)  if far_expiry  else None,
        "near_dte":     int(near_dte),
        "far_dte":      int(far_dte),
        "rollover_pct": rollover,
        "iv_term":      term,
        "near":         near,
        "far":          far,
    }


# ── File helpers ──────────────────────────────────────────────────────────────

def _read(path: Path) -> list:
    try:
        if path.exists():
            data = json.loads(path.read_text())
            return data if isinstance(data, list) else []
    except Exception as e:
        log.warning("OI history read failed (%s): %s", path.name, e)
    return []


# ── Daily (EOD job) ───────────────────────────────────────────────────────────

def append_daily_snapshot(date_str: str, near_df: pd.DataFrame, far_df: pd.DataFrame,
                          spot: float, near_expiry=None, far_expiry=None,
                          near_dte: int = 0, far_dte: int = 0) -> None:
    """Idempotent per date: replace today's record if present, else append."""
    snap = build_snapshot(near_df, far_df, spot, near_expiry, far_expiry,
                          near_dte, far_dte)
    if not snap:
        log.info("OI snapshot skipped for %s — no usable chain (chain/auth issue).", date_str)
        return
    rows = [r for r in _read(DAILY_FILE) if r.get("date") != date_str]
    rows.append({"date": date_str, **snap})
    rows.sort(key=lambda r: r.get("date", ""))
    rows = rows[-_MAX_DAILY:]
    try:
        DAILY_FILE.write_text(json.dumps(rows, indent=1))
        log.info("OI daily snapshot saved for %s (near PCR=%s far PCR=%s rollover=%s)",
                 date_str, snap["near"].get("pcr"), snap["far"].get("pcr"),
                 snap.get("rollover_pct"))
    except Exception as e:
        log.warning("OI daily write failed: %s", e)


def load_daily_history() -> list:
    """Daily OI snapshots, oldest first."""
    return _read(DAILY_FILE)


# ── Intraday (live page) ──────────────────────────────────────────────────────

def log_intraday_snapshot(near_df: pd.DataFrame, far_df: pd.DataFrame,
                          spot: float, near_expiry=None, far_expiry=None,
                          near_dte: int = 0, far_dte: int = 0) -> None:
    """Append a timestamped OI point for TODAY; dedupes to ~1 per minute."""
    snap = build_snapshot(near_df, far_df, spot, near_expiry, far_expiry,
                          near_dte, far_dte)
    if not snap:
        return
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    rows = _read(TODAY_FILE)
    # Reset if the stored log is from a previous day.
    if rows and rows[-1].get("date") != today:
        rows = []
    stamp = now.strftime("%H:%M")
    if rows and rows[-1].get("time") == stamp:
        return                                  # already logged this minute
    rows.append({"date": today, "time": stamp, **snap})
    rows = rows[-_MAX_TODAY:]
    try:
        TODAY_FILE.write_text(json.dumps(rows))
    except Exception as e:
        log.warning("OI intraday write failed: %s", e)


def load_intraday_today() -> list:
    """Today's intraday OI points (empty if the file is from a prior day)."""
    rows = _read(TODAY_FILE)
    if rows and rows[-1].get("date") != _today_ist():
        return []
    return rows


# ── Per-strike history (parquet, written by scripts/run_scan.py --snapshot) ────

def load_chain_history(side: str = "far", days: int = 30) -> dict:
    """
    Per-strike daily chains, newest `days` files. Returns {date_str: DataFrame}.

    Feeds anything that needs strike-level detail across time — wall migration by
    strike, per-strike OI buildup, how a specific strike's OI grew through a cycle.
    Empty dict until the EOD job has run at least once.
    """
    out = {}
    if not PARQUET_DIR.exists():
        return out
    files = sorted(PARQUET_DIR.glob(f"*_{side}_chain.parquet"))[-days:]
    for f in files:
        try:
            out[f.name.split("_")[0]] = pd.read_parquet(f)
        except Exception as e:
            log.warning("chain parquet read failed (%s): %s", f.name, e)
    return out


# ── Derived series (what the history is FOR) ──────────────────────────────────

def history_frame(side: str = "far") -> pd.DataFrame:
    """
    Daily history flattened into a DataFrame indexed by date, for one expiry side.
    Columns are the summary fields plus the cross-expiry ones. Empty until the EOD
    job has logged at least one day.
    """
    rows = load_daily_history()
    if not rows:
        return pd.DataFrame()
    recs = []
    for r in rows:
        sub = r.get(side) or {}
        if not sub:
            continue
        recs.append({"date": r.get("date"), "spot": r.get("spot"),
                     "rollover_pct": r.get("rollover_pct"), "iv_term": r.get("iv_term"),
                     "dte": r.get(f"{side}_dte"), **sub})
    if not recs:
        return pd.DataFrame()
    df = pd.DataFrame(recs)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def percentile_of(series: pd.Series, value: float) -> float:
    """Where `value` sits in `series`, 0-100. The 'is 1.2 high?' answer."""
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty or value is None:
        return float("nan")
    return round(float((s <= value).sum()) / len(s) * 100, 1)
