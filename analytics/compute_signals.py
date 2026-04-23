# analytics/compute_signals.py — v6 (April 2026)
# Central orchestrator — runs all engines, assembles lens distance table.
#
# AGGREGATION PHILOSOPHY:
#   Each lens independently computes its own safe distance recommendation
#   for PE and CE. The result is a LENS TABLE — all distances shown side
#   by side. The "suggested" final strike is MAX per side (most conservative)
#   with the driving lens identified. Trader makes final decision.
#
#   NO STACKING. NO SUMMING. Each lens speaks once.

import json
import logging
from pathlib import Path
import pandas as pd
import streamlit as st

from analytics.ema            import EMAEngine
from analytics.constituent_ema import ConstituentEMAEngine
from analytics.rsi_engine     import RSIEngine
from analytics.bollinger      import BollingerOptionsEngine
from analytics.options_chain  import OptionsChainEngine
from analytics.oi_scoring     import OIScoringEngine
from analytics.vix_iv_regime  import VixIVRegimeEngine
from analytics.market_profile import MarketProfileEngine
from analytics.dow_theory     import DowTheoryEngine
from config import (
    BASELINE_OTM_PCT, WING_DISTANCE,
    BB_VIX_DIV_VIX, BB_VIX_DIV_BW,
    GEX_NEG_EXTRA, IV_SKEW_HIGH, IV_SKEW_PUT_EXTRA,
    GEX_FLIP_EXTRA, VRP_HIGH_POSITIVE, VRP_NEG_EXTRA,
    DUAL_FORTRESS_DIST_RED,
)

log = logging.getLogger(__name__)
SIGNALS_PATH = Path(__file__).parent.parent / "data" / "signals.json"


def compute_all_signals(
    nifty_df: pd.DataFrame,
    stock_dfs: dict,
    vix_live: float,
    vix_hist: pd.DataFrame,
    chains: dict,
    spot: float,
) -> dict:
    sig = {}

    # ── Pages 1+2: EMA ────────────────────────────────────────────────────
    try:
        ema_sig = EMAEngine().signals(nifty_df.copy())
        sig.update(ema_sig)
    except Exception as e:
        log.error("EMA engine: %s", e)
        sig.update({
            "atr14": 200, "net_skew": 0, "canary_level": 0,
            "canary_direction": "NONE", "canary_day": 0,
            "put_safety_adj": 50, "call_safety_adj": 50,
            "cr_regime": "INSIDE_BULL", "cr_pe_dist_pts": 860,
            "cr_ce_dist_pts": 860, "cr_base_mult": 2.0,
            "cr_put_moats": 2, "cr_call_moats": 2,
            "cr_mom_state": "FLAT", "cr_hard_skip": False,
        })

    # ── Dow Theory ────────────────────────────────────────────────────────
    try:
        dow_sig = DowTheoryEngine().signals(nifty_df.copy())
        sig.update({"dow_" + k: v for k, v in dow_sig.items()})
    except Exception as e:
        log.error("Dow Theory: %s", e)

    # ── Pages 3+4: Constituent EMA ─────────────────────────────────────────
    try:
        const_sig = ConstituentEMAEngine().signals(stock_dfs)
        sig.update(const_sig)
        breadth_data = const_sig.get("constituent_breadth", {})
        sig["breadth_score"]     = breadth_data.get("score_pct", 50)
        sig["breadth_label"]     = breadth_data.get("label", "ADEQUATE")
        sig["divergence_alert"]  = const_sig.get("INDEX_MASKING_WEAKNESS", False)
        sig["lead_warning"]      = const_sig.get("HEAVYWEIGHT_LEADING_DOWN", False)
        sig["sw3_active"]        = const_sig.get("BANKING_ALL_BULLISH", False)
        sig["sw4_active"]        = const_sig.get("HEAVYWEIGHT_COLLAPSE", False)
        sig["bfsi_softening"]    = const_sig.get("BANKING_SLOPE_WEAKENING", False)
        sig["sd5_active"]        = const_sig.get("IT_SECTOR_DRAG", False)
        sig["sd6_collapse"]      = const_sig.get("BANKING_DAILY_COLLAPSE", False)
        sig["rotation_signal"]   = const_sig.get("SECTOR_ROTATION_DETECTED", False)
        sig["constituent_pe_mod"]= const_sig.get("constituent_pe_mod", 0)
        sig["constituent_ce_mod"]= const_sig.get("constituent_ce_mod", 0)
    except Exception as e:
        log.error("Constituent EMA: %s", e)
        sig.update({"breadth_score": 50, "sw3_active": False, "sw4_active": False,
                    "bfsi_softening": False, "divergence_alert": False,
                    "lead_warning": False, "constituent_pe_mod": 0,
                    "constituent_ce_mod": 0})

    # ── Pages 5-8: RSI ─────────────────────────────────────────────────────
    try:
        rsi_eng = RSIEngine()
        rsi_sig = rsi_eng.signals(nifty_df.copy())
        sig.update(rsi_sig)
        stk_sig = rsi_eng.stock_signals(stock_dfs)
        sig.update(stk_sig)
    except Exception as e:
        log.error("RSI engine: %s", e)
        sig.update({"w_regime": "W_NEUTRAL", "d_zone": "D_BALANCE",
                    "alignment": "MIXED", "rsi_put_dist_mod": 0,
                    "rsi_call_dist_mod": 0})

    sig["weekly_regime"] = sig.get("w_regime", "W_NEUTRAL")
    sig["daily_zone"]    = sig.get("d_zone",   "D_BALANCE")
    sig["mtf_alignment"] = sig.get("alignment", "MIXED")
    sig["kill_active"]   = _first_active_kill(sig.get("kill_switches", {}))
    sig["near_dte"]      = chains.get("near_dte", 7)
    sig["far_dte"]       = chains.get("far_dte",  14)

    # ── Page 9: Bollinger ──────────────────────────────────────────────────
    try:
        bb_sig = BollingerOptionsEngine().signals(nifty_df.copy())
        sig.update({f"bb_{k}": v for k, v in bb_sig.items()})
        sig["bb_regime"]       = bb_sig["regime"]
        sig["bw_pct"]          = bb_sig["bw_pct"]
        atr14_val              = sig.get("atr14", 200)
        if vix_live > BB_VIX_DIV_VIX and bb_sig["bw_pct"] < BB_VIX_DIV_BW:
            div_pts = max(100, round(0.5 * atr14_val / 50) * 50)
            sig["bb_vix_divergence"] = True
            sig["bb_distance_put"]   = div_pts
            sig["bb_distance_call"]  = div_pts
        else:
            sig["bb_vix_divergence"] = False
            sig["bb_distance_put"]   = bb_sig.get("bb_distance_put", 0)
            sig["bb_distance_call"]  = bb_sig.get("bb_distance_call", 0)
        sig["bb_walk_up_count"]   = bb_sig.get("walk_up_count", 0)
        sig["bb_walk_down_count"] = bb_sig.get("walk_down_count", 0)
        sig["bb_kill_switches"]   = bb_sig.get("kill_switches", {})
        sig["bb_home_score"]      = bb_sig.get("home_score", 10)
    except Exception as e:
        log.error("Bollinger: %s", e)
        sig.update({"bb_regime": "NEUTRAL_WALK", "bw_pct": 6.0,
                    "bb_vix_divergence": False, "bb_distance_put": 0,
                    "bb_distance_call": 0, "bb_home_score": 10})

    # ── Page 10: Options Chain ─────────────────────────────────────────────
    try:
        atr14_val = sig.get("atr14", 200)
        oc_sig = OptionsChainEngine().signals(
            chains.get("far", pd.DataFrame()), spot,
            chains.get("far_dte", 7), atr14=atr14_val
        )
        sig["gex_total"]          = oc_sig["gex"]["total_gex"]
        sig["gex_flip_level"]     = oc_sig["gex"]["flip_level"]
        sig["call_wall"]          = oc_sig["call_wall"]
        sig["put_wall"]           = oc_sig["put_wall"]
        sig["pcr"]                = oc_sig["pcr"]
        sig["migration_detected"] = oc_sig["migration"]["detected"]
        sig["iv_skew"]            = oc_sig["iv_skew"]
        sig["atm_iv"]             = oc_sig["atm_iv"]
        sig["straddle_price"]     = oc_sig["straddle_price"]
        sig["oc_binding_ce"]      = oc_sig["synthesis"]["binding_ce"]
        sig["oc_binding_pe"]      = oc_sig["synthesis"]["binding_pe"]
        sig["oc_home_score"]      = oc_sig["home_score"]
    except Exception as e:
        log.error("Options Chain: %s", e)
        sig.update({"gex_total": 0, "gex_flip_level": 0, "call_wall": 0,
                    "put_wall": 0, "pcr": 1.0, "migration_detected": False,
                    "iv_skew": 0.0, "atm_iv": 12.0, "straddle_price": 0,
                    "oc_binding_ce": 0, "oc_binding_pe": 0, "oc_home_score": 10})

    # ── Page 10B: OI Scoring ───────────────────────────────────────────────
    try:
        oi_eng  = OIScoringEngine()
        near_sc = oi_eng.score_chain_near(chains.get("near", pd.DataFrame()).copy(), chains.get("near_dte", 5))
        far_sc  = oi_eng.score_chain_far( chains.get("far",  pd.DataFrame()).copy(), chains.get("far_dte",  7))
        atm = round(spot / 50) * 50
        sig["pe_net_score"]       = float(far_sc.loc[atm, "net_score"])     if atm in far_sc.index and "net_score"       in far_sc.columns else 0
        sig["pe_wall_strength"]   = float(far_sc.loc[atm, "pe_wall"])       if atm in far_sc.index and "pe_wall"         in far_sc.columns else 5
        sig["position_action_put"]= far_sc.loc[atm, "position_action"]      if atm in far_sc.index and "position_action" in far_sc.columns else "BALANCED_IC"
        sig["near_scored"] = near_sc
        sig["far_scored"]  = far_sc
    except Exception as e:
        log.error("OI Scoring: %s", e)
        sig.update({"pe_net_score": 0, "pe_wall_strength": 5})

    # ── Page 11: VIX / IV ─────────────────────────────────────────────────
    try:
        vix_sig = VixIVRegimeEngine().signals(
            nifty_df.copy(), vix_hist, vix_live, sig.get("atm_iv", 12.0)
        )
        sig["vix_state"]           = vix_sig.get("vix_state", "STABLE_NORMAL")
        sig["vix_zone"]            = sig["vix_state"]
        sig["ivp_1yr"]             = vix_sig["ivp_1yr"]
        sig["ivp_zone"]            = vix_sig.get("ivp_zone", "IDEAL")
        sig["vrp"]                 = vix_sig["vrp"]
        sig["hv20"]                = vix_sig["hv20"]
        sig["atm_iv"]              = vix_sig.get("atm_iv", sig.get("atm_iv", 12.0))
        sig["size_multiplier"]     = vix_sig["size_multiplier"]
        sig["vix_hard_kill"]       = False
        sig["vix_k4_vrp_neg"]      = vix_sig["kill_switches"].get("K4_vrp_negative", False)
        sig["vix_sma_200"]         = vix_sig.get("vix_sma_200", 13.0)
        sig["vix_sma_50"]          = vix_sig.get("vix_sma_50",  13.0)
        sig["vix_sma_20"]          = vix_sig.get("vix_sma_20",  13.0)
        sig["vix_ubb"]             = vix_sig.get("vix_ubb",     22.0)
        sig["vix_bb_width"]        = vix_sig.get("vix_bb_width", 9.0)
        sig["vix_spike_confirmed"] = vix_sig.get("vix_spike_confirmed", False)
        sig["vix_stable_confirmed"]= vix_sig.get("vix_stable_confirmed", True)
        sig["vix_spike_count"]     = vix_sig.get("vix_spike_count", 0)
        sig["warnings"]            = vix_sig.get("warnings", [])
        sig["is_danger"]           = vix_sig.get("is_danger", False)
        sig["is_caution"]          = vix_sig.get("is_caution", False)
        sig["is_spike_resolving"]  = vix_sig.get("is_spike_resolving", False)
        sig["vix_home_score"]      = vix_sig.get("home_score", 10)
    except Exception as e:
        log.error("VIX engine: %s", e)
        sig.update({"vix_zone": "STABLE_NORMAL", "vix_state": "STABLE_NORMAL",
                    "size_multiplier": 1.0, "vrp": 0.0, "ivp_1yr": 50,
                    "vix_home_score": 10, "warnings": []})

    # ── Page 12: Market Profile ────────────────────────────────────────────
    try:
        mp_sig = MarketProfileEngine().signals(
            nifty_df.copy(), spot,
            near_dte=chains.get("near_dte", 7),
            far_dte=chains.get("far_dte",   14),
            net_skew=sig.get("net_skew", 0.0),
            atr14=sig.get("atr14", 200.0),
        )
        sig["mp_nesting"]         = mp_sig["nesting_state"]
        sig["mp_behaviour"]       = mp_sig.get("price_behaviour", "NEUTRAL")
        sig["weekly_vah"]         = mp_sig["weekly_vah"]
        sig["weekly_poc"]         = mp_sig["weekly_poc"]
        sig["weekly_val"]         = mp_sig["weekly_val"]
        sig["mp_responsive"]      = mp_sig["responsive"]
        sig["mp_ce_anchor"]       = mp_sig["ce_strike_anchor"]
        sig["mp_pe_anchor"]       = mp_sig["pe_strike_anchor"]
        sig["mp_kills"]           = mp_sig.get("mp_kills", mp_sig.get("kill_switches", {}))
        sig["mp_day_type"]        = mp_sig.get("day_type", "NORMAL")
        sig["mp_cycle_day"]       = mp_sig.get("cycle_day", "")
        sig["mp_cycle_action"]    = mp_sig.get("cycle_action", "")
        sig["mp_poc_migration"]   = mp_sig.get("poc_migration", {})
        sig["mp_va_ratio"]        = mp_sig.get("va_ratio", 1.0)
        sig["mp_buf_mult"]        = mp_sig.get("buf_mult", 0.75)
        sig["mp_buffer_pts"]      = mp_sig.get("buffer_pts", 150)
        sig["mp_dte_factor"]      = mp_sig.get("dte_factor", 1.0)
        sig["mp_initiative_both"] = mp_sig.get("initiative_both", False)
        sig["mp_ce_biwkly_dist"]  = mp_sig.get("ce_biwkly_dist", 400)
        sig["mp_pe_biwkly_dist"]  = mp_sig.get("pe_biwkly_dist", 400)
        sig["mp_home_score"]      = mp_sig.get("home_score", 12)
    except Exception as e:
        log.error("Market Profile: %s", e)
        sig.update({"mp_nesting": "BALANCED", "mp_responsive": True,
                    "mp_behaviour": "NEUTRAL", "mp_initiative_both": False,
                    "mp_ce_anchor": spot + 400, "mp_pe_anchor": spot - 400,
                    "mp_home_score": 12, "mp_ce_biwkly_dist": 400,
                    "mp_pe_biwkly_dist": 400})

    # ── Lens table + final suggestion ─────────────────────────────────────
    _build_lens_table(sig, spot)
    _compute_master_score(sig)

    return sig


def _build_lens_table(sig: dict, spot: float) -> None:
    """
    Each lens produces its own standalone PE and CE distance recommendation.
    No stacking. No summing. MAX per side = suggested strike.
    Trader makes final decision from the full table.
    """
    atr14 = sig.get("atr14", 200)
    if atr14 <= 0: atr14 = 200

    # ── Lens 1: EMA (cluster + moat + momentum) ───────────────────────────
    l1_pe = sig.get("cr_pe_dist_pts", int(round(2.0 * atr14 / 50) * 50))
    l1_ce = sig.get("cr_ce_dist_pts", int(round(2.0 * atr14 / 50) * 50))

    # ── Lens 2: RSI regime ────────────────────────────────────────────────
    # RSI recommends a distance based on weekly regime only
    # Uses ATR multiples consistent with the EMA framework
    w_regime = sig.get("w_regime", sig.get("weekly_regime", "W_NEUTRAL"))
    RSI_REGIME_PE_MULT = {
        "W_CAPIT":     3.25,
        "W_BEAR":      2.75,
        "W_BEAR_TRANS":2.50,
        "W_NEUTRAL":   2.25,
        "W_BULL_TRANS":2.00,
        "W_BULL":      2.00,
        "W_BULL_EXH":  2.50,   # exhaustion = widen both
    }
    RSI_REGIME_CE_MULT = {
        "W_CAPIT":     2.00,
        "W_BEAR":      2.00,
        "W_BEAR_TRANS":2.25,
        "W_NEUTRAL":   2.25,
        "W_BULL_TRANS":2.50,
        "W_BULL":      2.75,
        "W_BULL_EXH":  2.50,
    }
    # Kill switch overrides
    kills = sig.get("kill_switches", {})
    dual_exh = kills.get("RSI_DUAL_EXHAUSTION") or kills.get("K3")
    rsi_pe_m = RSI_REGIME_PE_MULT.get(w_regime, 2.25)
    rsi_ce_m = RSI_REGIME_CE_MULT.get(w_regime, 2.25)
    if dual_exh:
        rsi_pe_m = max(rsi_pe_m, 3.0)
        rsi_ce_m = max(rsi_ce_m, 3.0)
    l2_pe = int(round(rsi_pe_m * atr14 / 50) * 50)
    l2_ce = int(round(rsi_ce_m * atr14 / 50) * 50)

    # ── Lens 3: Constituent EMA (stock breadth) ───────────────────────────
    # Maps breadth label to ATR multiple recommendation
    breadth_lbl = sig.get("breadth_label", "ADEQUATE")
    const_pe_mod = sig.get("constituent_pe_mod", 0)   # pts from named signals
    BREADTH_PE_MULT = {
    "BROAD_HEALTH": 1.50,
    "ADEQUATE":     1.75,
    "THINNING":     2.00,
    "COLLAPSE":     2.50,
}
    l3_pe_m = BREADTH_PE_MULT.get(breadth_lbl, 2.25)
    # Named signals (HEAVYWEIGHT_COLLAPSE etc) override upward
    if const_pe_mod >= 300:  l3_pe_m = max(l3_pe_m, 2.75)
    elif const_pe_mod >= 200: l3_pe_m = max(l3_pe_m, 2.50)
    elif const_pe_mod < 0:    l3_pe_m = max(l3_pe_m - 0.25, 2.00)
    l3_pe = int(round(l3_pe_m * atr14 / 50) * 50)
    l3_ce = int(round(2.25 * atr14 / 50) * 50)   # CE: constituent has no CE-specific signal

    # ── Lens 4: Bollinger ─────────────────────────────────────────────────
    bb_regime = sig.get("bb_regime", "NEUTRAL_WALK")
    bb_pe_pts = sig.get("bb_distance_put", 0)
    bb_ce_pts = sig.get("bb_distance_call", 0)
    # Bollinger outputs pts directly (ATR-scaled walk modifier or VIX divergence)
    # Convert to a full distance by adding to neutral base
    neutral_base = int(round(2.25 * atr14 / 50) * 50)
    if bb_regime == "MEAN_REVERT":
        l4_pe = int(round(2.00 * atr14 / 50) * 50)   # tighten
        l4_ce = int(round(2.00 * atr14 / 50) * 50)
    elif bb_regime == "SQUEEZE":
        l4_pe = int(round(2.50 * atr14 / 50) * 50)   # widen — coiled spring
        l4_ce = int(round(2.50 * atr14 / 50) * 50)
    else:
        l4_pe = neutral_base + bb_pe_pts
        l4_ce = neutral_base + bb_ce_pts

    # ── Lens 5: VIX / IV ──────────────────────────────────────────────────
    vix_state = sig.get("vix_state", "STABLE_NORMAL")
    vrp       = sig.get("vrp", 0.0)
    VIX_MULT = {
        "STABLE_LOW":      2.00,
        "STABLE_NORMAL":   2.25,
        "SPIKE_RESOLVING": 2.25,   # premium good, risk fading
        "ELEVATED":        2.50,
        "CAUTION":         2.75,
        "DANGER":          3.25,
    }
    vix_m = VIX_MULT.get(vix_state, 2.25)
    if vrp < 0:         vix_m = max(vix_m, 2.75)   # selling edge gone — widen
    if vrp > 5.0:       vix_m = max(vix_m - 0.25, 2.00)   # strong edge — mild tighten
    l5_pe = int(round(vix_m * atr14 / 50) * 50)
    l5_ce = int(round(vix_m * atr14 / 50) * 50)   # VIX affects both sides equally

    # ── Lens 6: Market Profile biweekly anchor ────────────────────────────
    l6_pe = sig.get("mp_pe_biwkly_dist", int(round(2.25 * atr14 / 50) * 50))
    l6_ce = sig.get("mp_ce_biwkly_dist", int(round(2.25 * atr14 / 50) * 50))

    # ── Assemble lens table ───────────────────────────────────────────────
    lens_table = {
        "EMA (regime+moat+momentum)":  {"pe": l1_pe, "ce": l1_ce},
        "RSI (weekly regime)":          {"pe": l2_pe, "ce": l2_ce},
        "Constituent EMA (breadth)":    {"pe": l3_pe, "ce": l3_ce},
        "Bollinger":                    {"pe": l4_pe, "ce": l4_ce},
        "VIX / IV":                     {"pe": l5_pe, "ce": l5_ce},
        "Market Profile (biweekly)":    {"pe": l6_pe, "ce": l6_ce},
    }
    sig["lens_table"] = lens_table

    # ── MAX per side = suggested (most conservative) ──────────────────────
    all_pe = {name: v["pe"] for name, v in lens_table.items()}
    all_ce = {name: v["ce"] for name, v in lens_table.items()}

    suggested_pe      = max(all_pe.values())
    suggested_ce      = max(all_ce.values())
    suggested_pe_lens = max(all_pe, key=all_pe.get)
    suggested_ce_lens = max(all_ce, key=all_ce.get)

    # Dual Fortress bonus (only applied when explicitly active)
    if sig.get("pe_dual_fortress"): suggested_pe = max(suggested_pe - DUAL_FORTRESS_DIST_RED, int(round(2.0 * atr14 / 50) * 50))
    if sig.get("ce_dual_fortress"): suggested_ce = max(suggested_ce - DUAL_FORTRESS_DIST_RED, int(round(2.0 * atr14 / 50) * 50))

    # Round to nearest 50
    suggested_pe = round(suggested_pe / 50) * 50
    suggested_ce = round(suggested_ce / 50) * 50

    final_pe_short  = round((spot - suggested_pe)  / 50) * 50
    final_ce_short  = round((spot + suggested_ce)  / 50) * 50

    sig["suggested_pe_dist"]  = int(suggested_pe)
    sig["suggested_ce_dist"]  = int(suggested_ce)
    sig["suggested_pe_lens"]  = suggested_pe_lens
    sig["suggested_ce_lens"]  = suggested_ce_lens
    sig["final_put_dist"]     = int(suggested_pe)
    sig["final_call_dist"]    = int(suggested_ce)
    sig["final_put_short"]    = int(final_pe_short)
    sig["final_call_short"]   = int(final_ce_short)
    sig["final_put_wing"]     = int(final_pe_short  - WING_DISTANCE)
    sig["final_call_wing"]    = int(final_ce_short  + WING_DISTANCE)


def _compute_master_score(sig: dict) -> None:
    """Per-lens home scores → master score 0-100."""
    ema_sc  = sig.get("home_score", 0)
    bb_sc   = sig.get("bb_home_score", 10)
    oc_sc   = sig.get("oc_home_score", 10)
    vx_sc   = sig.get("vix_home_score", 10)
    mp_sc   = sig.get("mp_home_score",  12)
    alignment = sig.get("mtf_alignment", sig.get("alignment", "MIXED"))
    rsi_sc = (20 if alignment == "ALIGNED_BULL" else
              18 if alignment == "ALIGNED_BULL_NEUTRAL" else
              15 if alignment == "ALIGNED_BEAR" else
               5 if "COUNTER" in alignment else 10)
    kills = sig.get("kill_switches", {})
    if kills.get("RSI_DUAL_EXHAUSTION") or kills.get("K3"): rsi_sc = max(0, rsi_sc - 10)
    if kills.get("RSI_REGIME_FLIP") or kills.get("K1"):      rsi_sc = max(0, rsi_sc - 5)
    if sig.get("BANKING_DAILY_COLLAPSE") or sig.get("sd6_collapse"):
        ema_sc = 0; rsi_sc = 0
    if sig.get("is_danger"): vx_sc = max(0, vx_sc - 5)
    master = min(100, ema_sc + rsi_sc + bb_sc + vx_sc + mp_sc)
    sig["master_score"]   = master
    sig["master_verdict"] = (
        "ENTER — high confidence" if master >= 75 else
        "ENTER — proceed with caution" if master >= 55 else
        "MARGINAL — reduce size" if master >= 40 else
        "STAND ASIDE"
    )
    sig["master_colour"] = (
        "#16a34a" if master >= 75 else
        "#d97706" if master >= 55 else
        "#ea580c" if master >= 40 else
        "#dc2626"
    )
    sig["_lens_scores"] = {
        "EMA (P1+2)":  ema_sc,
        "RSI (P5-8)":  rsi_sc,
        "Bollinger":   bb_sc,
        "VIX/IV":      vx_sc,
        "Mkt Profile": mp_sc,
    }


def _first_active_kill(kills: dict) -> str | None:
    for k, v in kills.items():
        if v: return k
    return None


def load_saved_signals() -> dict:
    if SIGNALS_PATH.exists():
        try:
            return json.loads(SIGNALS_PATH.read_text())
        except Exception:
            pass
    return {}


def save_signals(sig: dict) -> None:
    SIGNALS_PATH.parent.mkdir(exist_ok=True)
    clean = {k: v for k, v in sig.items()
             if not hasattr(v, "to_dict") and k not in ("near_scored", "far_scored")}
    try:
        SIGNALS_PATH.write_text(json.dumps(clean, default=str, indent=2))
    except Exception as e:
        log.error("Failed to save signals: %s", e)


@st.cache_data(ttl=300, show_spinner=False)
def get_cached_signals(nifty_df, stock_dfs, vix_live, vix_hist, chains, spot):
    return compute_all_signals(nifty_df, stock_dfs, vix_live, vix_hist, chains, spot)
