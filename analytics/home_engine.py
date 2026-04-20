# analytics/home_engine.py
# Master Scoring Engine — Page 00 (Home)
# Aggregates all analytics modules into one 100-point weighted score.
# Majority vote: ≥50 pts = trade. Any kill switch = absolute veto.

from analytics.ema            import EMAEngine
from analytics.rsi_engine     import RSIEngine
from analytics.bollinger      import BollingerOptionsEngine
from analytics.options_chain  import OptionsChainEngine
from analytics.oi_scoring     import OIScoringEngine
from analytics.vix_iv_regime  import VixIVRegimeEngine
from analytics.market_profile import MarketProfileEngine
from config import HOME_WEIGHTS, HOME_SCORE_BANDS, BREADTH_MULTIPLIERS


class HomeEngine:
    """
    Reads cached signals from all analytics modules.
    Never calls Kite directly — depends on signals dicts already computed.
    """

    def __init__(self):
        self.ema   = EMAEngine()
        self.rsi   = RSIEngine()
        self.bb    = BollingerOptionsEngine()
        self.oc    = OptionsChainEngine()
        self.oi    = OIScoringEngine()
        self.vix   = VixIVRegimeEngine()
        self.mp    = MarketProfileEngine()

    # ─────────────────────────────────────────────────────────────────────────

    def compute_score(self, all_signals: dict) -> dict:
        """
        Parameters
        ----------
        all_signals : {
            "ema":           ema.signals() output,
            "breadth":       ema.breadth_signals() output,
            "rsi":           rsi.signals() output,
            "bollinger":     bb.signals() output,
            "options_chain": oc.signals() output,
            "vix_iv":        vix.signals() output,
            "market_profile":mp.signals() output,
        }

        Returns
        -------
        dict with total_score, any_kill, base_size, breadth_mult, effective_size,
        verdict, per_system breakdown, alert_feed.
        """
        # ── 1. Check all kill switches ────────────────────────────────────────
        any_kill   = False
        kill_detail= {}
        for system_name, sig in all_signals.items():
            kills = sig.get("kill_switches", {})
            for k, v in kills.items():
                if v:
                    any_kill = True
                    kill_detail[f"{system_name}.{k}"] = True

        # ── 2. Collect per-system scores ──────────────────────────────────────
        per_system = {}
        total_score = 0

        system_map = {
            "options_chain":  ("options_chain",  HOME_WEIGHTS["options_chain"]),
            "market_profile": ("market_profile", HOME_WEIGHTS["market_profile"]),
            "rsi":            ("rsi",            HOME_WEIGHTS["rsi"]),
            "bollinger":      ("bollinger",       HOME_WEIGHTS["bollinger"]),
            "vix_iv":         ("vix_iv",          HOME_WEIGHTS["vix_iv"]),
            "ema":            ("ema",             HOME_WEIGHTS["ema_regime"]),
            "breadth":        ("breadth",         HOME_WEIGHTS["breadth"]),
        }

        for label, (sig_key, max_pts) in system_map.items():
            sig   = all_signals.get(sig_key, {})
            score = min(sig.get("home_score", 0), max_pts)
            per_system[label] = {"score": score, "max": max_pts}
            total_score += score

        # ── 3. Position sizing ────────────────────────────────────────────────
        if any_kill:
            base_size = 0.0
        else:
            base_size = 0.0
            for (lo, hi), size in HOME_SCORE_BANDS.items():
                if lo <= total_score <= hi:
                    base_size = size
                    break

        breadth_count = all_signals.get("breadth", {}).get("above_ema60", 5)
        breadth_mult  = BREADTH_MULTIPLIERS.get(breadth_count, 0.65)
        effective_size= round(base_size * breadth_mult, 2)

        # ── 4. Verdict ────────────────────────────────────────────────────────
        if any_kill:
            verdict = "KILL_VETO"
        elif total_score < 35:
            verdict = "NO_TRADE"
        elif total_score < 50:
            verdict = "WAIT"
        elif effective_size >= 0.75:
            verdict = "TRADE_FULL"
        elif effective_size >= 0.50:
            verdict = "TRADE_REDUCED"
        else:
            verdict = "TRADE_MINIMAL"

        # ── 5. Strategy suggestion ────────────────────────────────────────────
        oc_sig = all_signals.get("options_chain", {})
        mp_sig = all_signals.get("market_profile", {})
        strategy = self._suggest_strategy(
            total_score, any_kill, oc_sig, mp_sig, all_signals.get("rsi", {})
        )

        # ── 6. Alert feed ─────────────────────────────────────────────────────
        alerts = self._build_alerts(all_signals, kill_detail, total_score, effective_size)

        return {
            "total_score":    total_score,
            "any_kill":       any_kill,
            "kill_detail":    kill_detail,
            "base_size":      base_size,
            "breadth_mult":   breadth_mult,
            "breadth_count":  breadth_count,
            "effective_size": effective_size,
            "verdict":        verdict,
            "strategy":       strategy,
            "per_system":     per_system,
            "alerts":         alerts,
        }

    # ─────────────────────────────────────────────────────────────────────────

    def _suggest_strategy(self, score, any_kill, oc_sig, mp_sig, rsi_sig) -> str:
        if any_kill or score < 50:
            return "NO_TRADE"
        oc_strategy = oc_sig.get("strategy", "IRON_CONDOR")
        mp_nesting  = mp_sig.get("nesting_state", "BALANCED")
        rsi_align   = rsi_sig.get("alignment", "MIXED")

        if mp_nesting == "BULL_VALUE_SHIFT" and "BULL" in rsi_align:
            return "BULL_PUT_SPREAD"
        if mp_nesting == "BEAR_VALUE_SHIFT" and "BEAR" in rsi_align:
            return "BEAR_CALL_SPREAD"
        return oc_strategy   # default to options chain decision

    # ─────────────────────────────────────────────────────────────────────────

    def _build_alerts(self, all_signals, kill_detail, score, eff_size) -> list[dict]:
        """
        Build priority-sorted alert feed.
        Level 1 (RED) = kill switches.
        Level 2 (AMBER) = caution flags.
        Level 3 (BLUE) = info.
        Level 4 (GREEN) = confirmations.
        """
        alerts = []

        # Level 1 — kills
        for kill_key in kill_detail:
            alerts.append({
                "level": 1, "color": "RED",
                "title": f"KILL SWITCH: {kill_key}",
                "body":  "Trade vetoed regardless of score.",
            })

        # Level 2 — cautions
        vix_sig = all_signals.get("vix_iv", {})
        if vix_sig.get("ivp_1yr", 100) < 25:
            alerts.append({
                "level": 2, "color": "AMBER",
                "title": f"IVP {vix_sig.get('ivp_1yr')} — below 25 threshold",
                "body":  "Premiums thin. Reduce size. Wider wings required.",
            })
        if vix_sig.get("vix", 0) > 20:
            alerts.append({
                "level": 2, "color": "AMBER",
                "title": f"VIX {vix_sig.get('vix')} — above sweet spot",
                "body":  "Elevated vol. Widen IC wings by 100pts each side.",
            })

        rsi_sig = all_signals.get("rsi", {})
        if rsi_sig.get("momentum_phase") == "EXHAUSTION":
            alerts.append({
                "level": 2, "color": "AMBER",
                "title": f"RSI Phase 3 — Exhaustion. Daily RSI {rsi_sig.get('rsi_daily')}",
                "body":  "CE spread setup approaching. Tighten PE stops.",
            })

        ema_sig = all_signals.get("ema", {})
        if ema_sig.get("ribbon_state") == "COMPRESSED":
            alerts.append({
                "level": 2, "color": "AMBER",
                "title": "EMA Ribbon compressed — breakout imminent",
                "body":  "No directional bias. Defer new positions.",
            })

        # Level 3 — info
        oc_sig = all_signals.get("options_chain", {})
        oi_sig = all_signals.get("oi_scoring", {})
        if oc_sig.get("migration", {}).get("detected"):
            alerts.append({
                "level": 3, "color": "AMBER",
                "title": "OI Migration detected (P10)",
                "body":  "OI peaks shifting. Disable weakness rules.",
            })

        # Level 4 — confirmations
        mp_sig = all_signals.get("market_profile", {})
        if mp_sig.get("nesting_state") == "BALANCED" and mp_sig.get("responsive"):
            alerts.append({
                "level": 4, "color": "GREEN",
                "title": "Market Profile balanced + responsive (P12)",
                "body":  f"VA: {mp_sig.get('weekly_val')}–{mp_sig.get('weekly_vah')}. IC thesis intact.",
            })

        if oc_sig.get("gex", {}).get("total_gex", 0) > 0:
            alerts.append({
                "level": 4, "color": "GREEN",
                "title": f"GEX positive +{oc_sig['gex']['total_gex']:,.0f} Cr — pinning (P10)",
                "body":  "Dealers long gamma. Range-bound bias confirmed.",
            })

        # Sort: kills first, then severity
        alerts.sort(key=lambda x: x["level"])
        return alerts
