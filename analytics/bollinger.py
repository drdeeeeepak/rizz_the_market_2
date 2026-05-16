# analytics/bollinger.py — v4 (May 2026)
# Page 09: Bollinger Bands Framework — 4-TF MTF engine
#
# TF_HIERARCHY:
#   2H = PRIMARY   → BW% regime, %B zone, MA position, walk, asymmetry ratio
#   4H = SECONDARY → confidence modifier, secondary walk, squeeze alignment
#   1D = REGIME_BG → display only + skip score condition 1
#   1W = MACRO     → display only + skip score conditions 2 and 5
#
# RULE: Only 2H+4H feed asymmetry formula. 1D/1W never drive strike or ratio.
# All signals are INDEPENDENT — do not stack with other lenses.

import logging
import pandas as pd
import numpy as np
from analytics.base_strategy import BaseStrategy
from config import BB_PERIOD, BB_STD, BB_MA_BAND

log = logging.getLogger(__name__)

MIN_BARS = BB_PERIOD + 5   # minimum bars for a meaningful BB signal on any TF

# ── BW% regime threshold tables ────────────────────────────────────────────────
# Format: (upper_bound_exclusive, regime_name). None = open-ended (catch-all).

_BW_2H = [          # 2H and 4H — intraday, tighter thresholds
    (2.0,  "EXTREME_SQUEEZE"),
    (3.5,  "SQUEEZE"),
    (4.5,  "CALM"),
    (5.6,  "MOMENTUM"),
    (6.5,  "HIGH_VOL"),
    (None, "MEAN_REVERT"),
]
_BW_1D = [          # 1D — daily bands compress more slowly, wider thresholds
    (3.5,  "SQUEEZE"),
    (5.6,  "CALM"),
    (7.0,  "MOMENTUM"),
    (9.0,  "HIGH_VOL"),
    (None, "MEAN_REVERT"),
]
_BW_1W = [          # 1W — weekly override thresholds from spec
    (4.5,  "EXTREME_SQUEEZE"),
    (6.5,  "CALM"),
    (8.0,  "MOMENTUM"),
    (10.2, "HIGH_VOL"),
    (None, "MEAN_REVERT"),
]

# Lens table: ATR base multiplier per 2H regime
_LENS_BASE_MULT = {
    "EXTREME_SQUEEZE": 2.5,
    "SQUEEZE":         2.25,
    "CALM":            2.0,    # IC sweet spot — tighter distance
    "MOMENTUM":        2.25,
    "HIGH_VOL":        2.5,
    "MEAN_REVERT":     2.75,
}
# Extra ATR fraction added to threatened leg, scaled by confidence
_LENS_EXTRA = {"HIGH": 0.5, "MEDIUM": 0.25, "WEAK": 0.0}

# Home score by 2H regime when no special squeeze status applies
_HOME_REGIME = {
    "CALM":            14,
    "MOMENTUM":        7,
    "SQUEEZE":         5,
    "HIGH_VOL":        3,
    "MEAN_REVERT":     1,
    "EXTREME_SQUEEZE": 0,
}


def _classify_bw(bw: float, table: list) -> str:
    for threshold, name in table:
        if threshold is None or bw < threshold:
            return name
    return table[-1][1]


def _pct_b_zone(pct_b: float) -> str:
    if pct_b > 1.0:   return "ABOVE_BAND"
    if pct_b >= 0.75: return "UPPER"
    if pct_b >= 0.55: return "UP_NEUTRAL"
    if pct_b >= 0.45: return "MIDLINE"
    if pct_b >= 0.25: return "LO_NEUTRAL"
    if pct_b >= 0.0:  return "LOWER"
    return "BELOW_BAND"


class BollingerOptionsEngine(BaseStrategy):

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add BB columns + consecutive-close walk streaks to a single-TF df."""
        if df is None or df.empty or "close" not in df.columns:
            return df if df is not None else pd.DataFrame()
        basis, upper, lower, bw = self.bollinger(df["close"], BB_PERIOD, BB_STD)
        df["bb_basis"]  = basis
        df["bb_upper"]  = upper
        df["bb_lower"]  = lower
        df["bb_bw"]     = bw
        # Safe %B: avoid division by zero when bands collapse (extremely flat market)
        width = (upper - lower).replace(0, np.nan)
        df["bb_pct_b"]  = ((df["close"] - lower) / width).fillna(0.5)
        for col, at_band in [
            ("walk_up",   (df["close"] >= upper).fillna(False)),
            ("walk_down", (df["close"] <= lower).fillna(False)),
        ]:
            streak, c = [], 0
            for v in at_band:
                c = c + 1 if bool(v) else 0
                streak.append(c)
            df[f"{col}_count"] = streak
        return df

    def _safe_tf(self, df: pd.DataFrame, label: str = "") -> pd.DataFrame:
        """compute() with full data-quality guards — never raises."""
        if df is None or df.empty:
            return pd.DataFrame()
        if "close" not in df.columns:
            log.warning("BB %s: missing 'close' column — skipping TF", label)
            return pd.DataFrame()
        if len(df) < MIN_BARS:
            log.warning("BB %s: %d bars < MIN_BARS=%d — using defaults", label, len(df), MIN_BARS)
            return pd.DataFrame()
        try:
            result = self.compute(df.copy())
            # Sanity: last BW% must be finite and positive
            if "bb_bw" in result.columns:
                last_bw = result["bb_bw"].iloc[-1]
                if not np.isfinite(float(last_bw)) or float(last_bw) <= 0:
                    log.warning("BB %s: last BW%% = %.3f — marginal quality", label, float(last_bw))
            return result
        except Exception as e:
            log.warning("BB %s compute failed: %s", label, e)
            return pd.DataFrame()

    def signals(
        self,
        df_2h: pd.DataFrame,
        df_4h: pd.DataFrame,
        df_1d: pd.DataFrame,
        df_1w: pd.DataFrame,
        atr14: float = 200,
    ) -> dict:
        # ── compute BB on each TF — each isolated so one bad TF can't kill all ─
        c2h = self._safe_tf(df_2h, "2H")
        c4h = self._safe_tf(df_4h, "4H")
        c1d = self._safe_tf(df_1d, "1D")
        c1w = self._safe_tf(df_1w, "1W")

        def _s(df, col, default=0.0):
            if df.empty or col not in df.columns:
                return default
            v = df[col].iloc[-1]
            return float(v) if not pd.isna(v) else default

        bw_2h    = _s(c2h, "bb_bw",          6.0)
        bw_4h    = _s(c4h, "bb_bw",          6.0)
        bw_1d    = _s(c1d, "bb_bw",          6.0)
        bw_1w    = _s(c1w, "bb_bw",          8.0)
        pb_2h    = _s(c2h, "bb_pct_b",       0.5)
        pb_4h    = _s(c4h, "bb_pct_b",       0.5)
        basis_2h = _s(c2h, "bb_basis",       0.0)
        basis_4h = _s(c4h, "bb_basis",       0.0)
        basis_1w = _s(c1w, "bb_basis",       0.0)
        cl_2h    = _s(c2h, "close",          0.0)
        cl_4h    = _s(c4h, "close",          0.0)
        cl_1w    = _s(c1w, "close",          0.0)
        wu_2h    = int(_s(c2h, "walk_up_count",   0))
        wd_2h    = int(_s(c2h, "walk_down_count", 0))
        wu_4h    = int(_s(c4h, "walk_up_count",   0))
        wd_4h    = int(_s(c4h, "walk_down_count", 0))

        # ── regime, zones, MA position ───────────────────────────────────────
        reg_2h  = _classify_bw(bw_2h, _BW_2H)
        reg_4h  = _classify_bw(bw_4h, _BW_2H)   # same thresholds as 2H
        reg_1d  = _classify_bw(bw_1d, _BW_1D)
        reg_1w  = _classify_bw(bw_1w, _BW_1W)
        zone_2h = _pct_b_zone(pb_2h)
        zone_4h = _pct_b_zone(pb_4h)
        ma_2h   = self._ma_pos(cl_2h, basis_2h)
        ma_4h   = self._ma_pos(cl_4h, basis_4h)

        # ── squeeze status ────────────────────────────────────────────────────
        sq = self._squeeze_status(reg_2h, reg_4h)

        # ── asymmetry ratio: 2H %B drives base, then MA steps it toward 1:1 ─
        ratio, ce_watch, pe_watch = self._base_ratio(zone_2h, sq, pb_2h)
        ratio      = self._apply_ma(ratio, ma_2h, ma_4h)
        confidence = self._confidence(zone_2h, zone_4h, ma_4h)

        # ── walk labels (NONE/MILD/MODERATE/STRONG) ───────────────────────────
        wlbl_2h = self._walk_label(max(wu_2h, wd_2h))
        wlbl_4h = self._walk_label(max(wu_4h, wd_4h))

        # ── skip score: 5 additive conditions, each adds 1 ───────────────────
        sc1 = bw_1d > 5.6                                   # 1D HIGH_VOL+
        sc2 = basis_1w > 0 and cl_1w < basis_1w * 0.98     # 1W >2% below MA
        sc3 = max(wu_4h, wd_4h) >= 4                        # 4H STRONG walk
        sc4 = reg_2h == "MEAN_REVERT"                       # 2H mean revert
        sc5 = bw_1w > 10.2                                  # 1W mean revert
        skip = sum([sc1, sc2, sc3, sc4, sc5])
        skip_conditions = {
            "1d_high_vol":    sc1,
            "1w_below_ma":    sc2,
            "4h_strong_walk": sc3,
            "2h_mean_revert": sc4,
            "1w_mean_revert": sc5,
        }

        # ── entry verdict ─────────────────────────────────────────────────────
        if sq == "DEEP" or skip >= 3:
            verdict = "SKIP"
        elif skip == 2:
            verdict = "CAUTION"
        else:
            verdict = "PROCEED"

        primary_risk = "CE" if ratio == "1:2" else "PE" if ratio == "2:1" else "NEUTRAL"
        drift_risk   = self._drift_risk(reg_2h)
        home         = self._home_score(sq, reg_2h, verdict)
        l4_pe, l4_ce = self._lens_row(reg_2h, ratio, confidence, atr14)

        return {
            # Per-TF regime + BW%
            "regime_2h":      reg_2h,
            "regime_4h":      reg_4h,
            "regime_1d":      reg_1d,
            "regime_1w":      reg_1w,
            "bw_2h":          round(bw_2h, 2),
            "bw_4h":          round(bw_4h, 2),
            "bw_1d":          round(bw_1d, 2),
            "bw_1w":          round(bw_1w, 2),
            # %B and zones
            "pct_b_2h":       round(pb_2h, 3),
            "pct_b_4h":       round(pb_4h, 3),
            "zone_2h":        zone_2h,
            "zone_4h":        zone_4h,
            # Walk
            "walk_up_2h":     wu_2h,
            "walk_down_2h":   wd_2h,
            "walk_up_4h":     wu_4h,
            "walk_down_4h":   wd_4h,
            "walk_label_2h":  wlbl_2h,
            "walk_label_4h":  wlbl_4h,
            # MA position
            "ma_position_2h": ma_2h,
            "ma_position_4h": ma_4h,
            # Primary signals (new)
            "squeeze_status":    sq,
            "asymmetry_signal":  ratio,
            "confidence":        confidence,
            "ce_watch":          ce_watch,
            "pe_watch":          pe_watch,
            "skip_score":        skip,
            "skip_conditions":   skip_conditions,
            "entry_verdict":     verdict,
            "primary_risk_side": primary_risk,
            "drift_risk":        drift_risk,
            # Aliases for downstream compat (compute_signals, Home.py, page reads)
            "regime":            reg_2h,
            "bw_pct":            round(bw_2h, 2),
            # Lens table row (pts, computed from ratio + regime + confidence)
            "l4_pe":             l4_pe,
            "l4_ce":             l4_ce,
            # Home score
            "home_score":        home,
            # Kill switches
            "kill_switches": {
                "EXTREME_SQUEEZE": reg_2h == "EXTREME_SQUEEZE",
                "SQUEEZE":         reg_2h == "SQUEEZE",
                "CALM":            reg_2h == "CALM",
                "MOMENTUM":        reg_2h == "MOMENTUM",
                "HIGH_VOL":        reg_2h == "HIGH_VOL",
                "MEAN_REVERT":     reg_2h == "MEAN_REVERT",
                "DEEP_SQUEEZE":    sq == "DEEP",
                "ALIGNED_SQUEEZE": sq == "ALIGNED",
                "WALK_STRONG_2H":  wlbl_2h == "STRONG",
                "WALK_STRONG_4H":  wlbl_4h == "STRONG",
            },
        }

    # ── private helpers ────────────────────────────────────────────────────────

    def _squeeze_status(self, r2h: str, r4h: str) -> str:
        # DEEP: any EXTREME_SQUEEZE on either TF → hard skip
        if r2h == "EXTREME_SQUEEZE" or r4h == "EXTREME_SQUEEZE":
            return "DEEP"
        if r2h == "SQUEEZE" and r4h == "SQUEEZE":
            return "ALIGNED"    # best IC setup — both TFs coiled
        if r2h == "SQUEEZE":
            return "PARTIAL"    # 2H squeezed, 4H not yet
        return "NONE"

    def _base_ratio(self, zone: str, sq: str, pb: float) -> tuple:
        # Squeeze overrides %B zone — direction from %B value directly
        if sq in ("ALIGNED", "PARTIAL"):
            if pb > 0.55:  return "1:2", False, False   # expansion likely up
            if pb < 0.45:  return "2:1", False, False   # expansion likely down
            return "1:1", False, False                   # direction unknown
        if zone in ("ABOVE_BAND", "UPPER"): return "1:2", False, False
        if zone == "UP_NEUTRAL":            return "1:1", True,  False
        if zone == "LO_NEUTRAL":            return "1:1", False, True
        if zone in ("LOWER", "BELOW_BAND"): return "2:1", False, False
        return "1:1", False, False   # MIDLINE

    def _ma_pos(self, close: float, basis: float) -> str:
        if basis <= 0 or close <= 0:
            return "AT_MA"
        r = close / basis
        if r > 1 + BB_MA_BAND:  return "ABOVE_MA"
        if r < 1 - BB_MA_BAND:  return "BELOW_MA"
        return "AT_MA"

    def _apply_ma(self, ratio: str, ma_2h: str, ma_4h: str) -> str:
        # 2H MA contradicts ratio → step toward 1:1
        if ratio == "1:2" and ma_2h == "BELOW_MA": return "1:1"
        if ratio == "2:1" and ma_2h == "ABOVE_MA": return "1:1"
        # 4H MA contradicts ratio → also step toward 1:1 (4H override)
        if ratio == "1:2" and ma_4h == "BELOW_MA": return "1:1"
        if ratio == "2:1" and ma_4h == "ABOVE_MA": return "1:1"
        return ratio

    def _confidence(self, zone_2h: str, zone_4h: str, ma_4h: str) -> str:
        _bull = {"ABOVE_BAND", "UPPER", "UP_NEUTRAL"}
        _bear = {"LOWER", "BELOW_BAND", "LO_NEUTRAL"}
        d2 = "bull" if zone_2h in _bull else "bear" if zone_2h in _bear else "neutral"
        d4 = "bull" if zone_4h in _bull else "bear" if zone_4h in _bear else "neutral"
        if d2 == "neutral":   return "MEDIUM"   # 2H at midline — no strong signal
        if d2 == d4:          return "HIGH"      # 4H agrees with 2H direction
        if d4 == "neutral":   return "MEDIUM"    # 4H neutral while 2H directional
        # 4H MA contradicts 2H directional signal
        if d2 == "bull" and ma_4h == "BELOW_MA": return "MEDIUM"
        if d2 == "bear" and ma_4h == "ABOVE_MA": return "MEDIUM"
        return "WEAK"   # 4H in opposite directional half to 2H

    def _walk_label(self, days: int) -> str:
        if days >= 4:  return "STRONG"    # hard skip
        if days >= 3:  return "MODERATE"  # strong asymmetry or skip
        if days >= 2:  return "MILD"      # lean + flag
        return "NONE"

    def _drift_risk(self, r2h: str) -> str:
        return {
            "EXTREME_SQUEEZE": "VERY_HIGH",
            "HIGH_VOL":        "VERY_HIGH",
            "SQUEEZE":         "ELEVATED",
            "MOMENTUM":        "ELEVATED",
            "CALM":            "BASE",
            "MEAN_REVERT":     "VETO",
        }.get(r2h, "BASE")

    def _home_score(self, sq: str, r2h: str, verdict: str) -> int:
        if verdict == "SKIP" or sq == "DEEP":  return 0
        if sq == "ALIGNED":                    return 12
        if sq == "PARTIAL":                    return 10
        return _HOME_REGIME.get(r2h, 7)

    def _lens_row(self, r2h: str, ratio: str, conf: str, atr14: float) -> tuple:
        """Translate asymmetry ratio + regime → (l4_pe_pts, l4_ce_pts) for lens table."""
        base  = round(_LENS_BASE_MULT.get(r2h, 2.25) * atr14 / 50) * 50
        extra = round(_LENS_EXTRA.get(conf, 0.0)      * atr14 / 50) * 50
        cap   = round(3.0 * atr14 / 50) * 50

        if conf == "WEAK" or ratio == "1:1":
            return int(base), int(base)
        if ratio == "1:2":   # CE threatened → widen CE
            return int(base), int(min(base + extra, cap))
        if ratio == "2:1":   # PE threatened → widen PE
            return int(min(base + extra, cap)), int(base)
        return int(base), int(base)
