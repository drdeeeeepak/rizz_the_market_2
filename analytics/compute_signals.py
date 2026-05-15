# analytics/compute_signals.py — v9 (27 Apr 2026)
# Dow Theory: single DowTheoryEngine().signals(df_1h, spot) call.
# SuperTrend MTF added: SuperTrendEngine().signals(...) — Page 14.
# Home score rescaled: 8 lenses, total max = 100 (Option B).
# No frozen windows. No entry-day detection. One fetch, one compute.

import json
import logging
from datetime import date
from pathlib import Path
import pandas as pd
import streamlit as st

from analytics.ema             import EMAEngine
from analytics.constituent_ema import ConstituentEMAEngine
from analytics.rsi_engine      import RSIEngine
from analytics.bollinger       import BollingerOptionsEngine
from analytics.options_chain   import OptionsChainEngine
from analytics.oi_scoring      import OIScoringEngine
from analytics.vix_iv_regime   import VixIVRegimeEngine
from analytics.market_profile  import MarketProfileEngine
from analytics.dow_theory      import DowTheoryEngine
from analytics.supertrend      import SuperTrendEngine
from config import (
    BASELINE_OTM_PCT, WING_DISTANCE,
    BB_VIX_DIV_VIX, BB_VIX_DIV_BW,
    GEX_NEG_EXTRA, IV_SKEW_HIGH, IV_SKEW_PUT_EXTRA,
    GEX_FLIP_EXTRA, VRP_HIGH_POSITIVE, VRP_NEG_EXTRA,
    DUAL_FORTRESS_DIST_RED,
    HOME_SCORE_MAX_OC, HOME_SCORE_MAX_RSI, HOME_SCORE_MAX_MP,
    HOME_SCORE_MAX_BB, HOME_SCORE_MAX_VIX, HOME_SCORE_MAX_DOW,
    HOME_SCORE_MAX_EMA, HOME_SCORE_MAX_ST,
)

log = logging.getLogger(__name__)
SIGNALS_PATH = Path(__file__).parent.parent / "data" / "signals.json"


def compute_all_signals(
    nifty_df:   pd.DataFrame,
    stock_dfs:  dict,
    vix_live:   float,
    vix_hist:   pd.DataFrame,
    chains:     dict,
    spot:       float,
    nifty_1h:   pd.DataFrame = None,   # 20-day 1H for Dow Theory + ST proxy
    nifty_30m:  pd.DataFrame = None,   # 30m for ST Tier 3
    nifty_15m:  pd.DataFrame = None,   # 15m for ST Tier 3
    nifty_5m:   pd.DataFrame = None,   # 5m for ST display only
) -> dict:
    sig = {}
    sig["spot"] = spot   # always store so bootstrap_signals() fallback works

    # Store daily candle metrics for pre-market fallback (threat_mult, anchor)
    if nifty_df is not None and not nifty_df.empty and len(nifty_df) >= 2:
        try:
            import numpy as _np2
            from datetime import timedelta as _td
            _td_c  = float(nifty_df["close"].iloc[-1])
            _pr_c  = float(nifty_df["close"].iloc[-2])
            _td_v  = float(nifty_df["volume"].iloc[-1])
            _vs14  = float(nifty_df["volume"].rolling(14).mean().iloc[-1]) if len(nifty_df) >= 14 else _td_v
            _dret  = (_td_c - _pr_c) / _pr_c * 100 if _pr_c > 0 else 0.0
            _rv    = _td_v / _vs14 if _vs14 > 0 else 1.0
            sig["daily_ret_pct"] = round(_dret, 3)
            sig["rel_vol"]       = round(_rv, 3)
            sig["threat_mult"]   = round(abs(_dret) * _rv, 4)

            # Tuesday anchor — computed every run, not just on Tuesdays.
            # Page 02 uses this as a fallback when get_nifty_daily() is unavailable.
            _idx_dates = set(nifty_df.index.date) if hasattr(nifty_df.index, "date") else set()
            _today2    = date.today()
            _last_tue2 = _today2 - _td(days=(_today2.weekday() - 1) % 7)
            for _off in range(7):
                _cand = _last_tue2 - _td(days=_off)
                if _cand in _idx_dates:
                    _ah = nifty_df[nifty_df.index.date <= _cand].tail(15)
                    if not _ah.empty:
                        _ah_h = _ah["high"].values; _ah_l = _ah["low"].values; _ah_c = _ah["close"].values
                        _tr2 = [max(_ah_h[i]-_ah_l[i], abs(_ah_h[i]-_ah_c[i-1]), abs(_ah_l[i]-_ah_c[i-1]))
                                for i in range(1, len(_ah))]
                        sig["tue_close"] = float(_ah_c[-1])
                        sig["tue_atr"]   = round(float(_np2.mean(_tr2[-14:])) if len(_tr2) >= 14
                                                 else float(_np2.mean(_tr2)) if _tr2 else 200.0, 1)
                        sig["tue_date"]  = str(_cand)
                    break
        except Exception:
            pass

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

    # ── Page 00: Dow Theory Phase Engine ─────────────────────────────────
    try:
        if nifty_1h is not None and not nifty_1h.empty:
            dow_raw = DowTheoryEngine().signals(nifty_1h.copy(), spot)
        else:
            log.warning("Dow Theory: 1H data not provided — using empty fallback")
            dow_raw = DowTheoryEngine()._empty_signals()

        sig.update({f"dow_{k}": v for k, v in dow_raw.items()})

        # Unprefixed for backward compat with old Page 00
        sig["dow_structure"]  = dow_raw.get("structure", "MIXED")
        sig["dow_phase"]      = dow_raw.get("phase", "MX")
        sig["dow_narrative"]  = dow_raw.get("narrative", "")
        sig["dow_phase_score"]= dow_raw.get("phase_score", "WAIT")

    except Exception as e:
        log.error("Dow Theory: %s", e)
        sig.update({
            "dow_structure":        "MIXED",
            "dow_phase":            "MX",
            "dow_narrative":        "Dow Theory error — check logs.",
            "dow_phase_score":      "WAIT",
            "dow_ce_health":        "STRONG",
            "dow_pe_health":        "STRONG",
            "dow_call_breach":      0.0,
            "dow_put_breach":       0.0,
            "dow_call_prox_warn":   False,
            "dow_put_prox_warn":    False,
            "dow_home_score":       2,
            "dow_insufficient_data": True,
        })

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

    # ── Tuesday anchor: save NIFTY entry (stocks saved by ConstituentEMAEngine) ──
    if date.today().weekday() == 1 and not nifty_df.empty:
        try:
            from analytics.constituent_ema import _load_anchors, _save_anchors
            import numpy as _np
            _df = nifty_df.copy()
            _h, _l, _c = _df["high"].values, _df["low"].values, _df["close"].values
            _tr = [max(_h[i]-_l[i], abs(_h[i]-_c[i-1]), abs(_l[i]-_c[i-1]))
                   for i in range(1, len(_df))]
            _atr = float(_np.mean(_tr[-14:])) if len(_tr) >= 14 else float(_np.mean(_tr))
            _anchors = _load_anchors()
            _anchors["NIFTY"] = {
                "close": float(_df["close"].iloc[-1]),
                "atr":   round(_atr, 1),
                "date":  str(date.today()),
            }
            _save_anchors(_anchors)
            log.info("Tuesday NIFTY anchor saved: close=%.0f atr=%.1f",
                     _anchors["NIFTY"]["close"], _anchors["NIFTY"]["atr"])
        except Exception as e:
            log.error("Tuesday NIFTY anchor: %s", e)

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
                    "alignment": "MIXED", "rsi_put_dist_mod": 0, "rsi_call_dist_mod": 0})

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
        sig["bb_home_score"]      = min(bb_sig.get("home_score", HOME_SCORE_MAX_BB), HOME_SCORE_MAX_BB)
    except Exception as e:
        log.error("Bollinger: %s", e)
        sig.update({"bb_regime": "NEUTRAL_WALK", "bw_pct": 6.0,
                    "bb_vix_divergence": False, "bb_distance_put": 0,
                    "bb_distance_call": 0, "bb_home_score": HOME_SCORE_MAX_BB})

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
        sig["oc_home_score"]      = min(oc_sig["home_score"], HOME_SCORE_MAX_OC)
    except Exception as e:
        log.error("Options Chain: %s", e)
        sig.update({"gex_total": 0, "gex_flip_level": 0, "call_wall": 0,
                    "put_wall": 0, "pcr": 1.0, "migration_detected": False,
                    "iv_skew": 0.0, "atm_iv": 12.0, "straddle_price": 0,
                    "oc_binding_ce": 0, "oc_binding_pe": 0,
                    "oc_home_score": HOME_SCORE_MAX_OC // 2})

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
        sig["vix"]                 = vix_live
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
        sig["vix_home_score"]      = min(vix_sig.get("home_score", HOME_SCORE_MAX_VIX), HOME_SCORE_MAX_VIX)
    except Exception as e:
        log.error("VIX engine: %s", e)
        sig.update({"vix_zone": "STABLE_NORMAL", "vix_state": "STABLE_NORMAL",
                    "size_multiplier": 1.0, "vrp": 0.0, "ivp_1yr": 50,
                    "vix_home_score": HOME_SCORE_MAX_VIX, "warnings": []})

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
        sig["mp_home_score"]      = min(mp_sig.get("home_score", HOME_SCORE_MAX_MP), HOME_SCORE_MAX_MP)
    except Exception as e:
        log.error("Market Profile: %s", e)
        sig.update({"mp_nesting": "BALANCED", "mp_responsive": True,
                    "mp_behaviour": "NEUTRAL", "mp_initiative_both": False,
                    "mp_ce_anchor": spot+400, "mp_pe_anchor": spot-400,
                    "mp_home_score": HOME_SCORE_MAX_MP // 2,
                    "mp_ce_biwkly_dist": 400, "mp_pe_biwkly_dist": 400})

    # ── Page 15: SuperTrend MTF ────────────────────────────────────────────
    try:
        st_have_data = (
            nifty_df is not None and not nifty_df.empty and
            nifty_1h is not None and not nifty_1h.empty
        )

        # Trajectory: read yesterday's EOD normalised scores from signals.json
        saved              = load_saved_signals()
        prev_put_norm_eod  = saved.get("st_put_norm_eod")
        prev_call_norm_eod = saved.get("st_call_norm_eod")

        # Trajectory: intraday snapshot — Streamlit session only; safe to None in script context
        try:
            open_put_norm  = st.session_state.get("st_open_put_norm")
            open_call_norm = st.session_state.get("st_open_call_norm")
        except Exception:
            open_put_norm = open_call_norm = None

        if st_have_data:
            st_raw = SuperTrendEngine().signals(
                df_daily  = nifty_df.copy(),
                df_1h     = nifty_1h.copy(),
                df_30m    = nifty_30m.copy() if nifty_30m is not None and not nifty_30m.empty else pd.DataFrame(),
                df_15m    = nifty_15m.copy() if nifty_15m is not None and not nifty_15m.empty else pd.DataFrame(),
                df_5m     = nifty_5m.copy()  if nifty_5m  is not None and not nifty_5m.empty  else pd.DataFrame(),
                spot      = spot,
                prev_put_norm_eod  = prev_put_norm_eod,
                prev_call_norm_eod = prev_call_norm_eod,
                open_put_norm      = open_put_norm,
                open_call_norm     = open_call_norm,
            )
        else:
            log.warning("SuperTrend: insufficient data — using empty fallback")
            st_raw = SuperTrendEngine()._empty_signals()

        sig.update({f"st_{k}": v for k, v in st_raw.items()})
        sig["st_home_score"] = min(st_raw.get("home_score", 0), HOME_SCORE_MAX_ST)
        sig["st_ic_shape"]   = st_raw.get("ic_shape", "SYMMETRIC")

        # Store EOD normalised scores for tomorrow's structural trajectory
        sig["st_put_norm_eod"]  = st_raw.get("put_stack",  {}).get("normalised", 0)
        sig["st_call_norm_eod"] = st_raw.get("call_stack", {}).get("normalised", 0)

    except Exception as e:
        log.error("SuperTrend MTF: %s", e)
        sig.setdefault("st_home_score",     0)
        sig.setdefault("st_ic_shape",       "SYMMETRIC")
        sig.setdefault("st_put_stack",      {"normalised": 0, "band": "BREACHED", "walls": [], "clusters": []})
        sig.setdefault("st_call_stack",     {"normalised": 0, "band": "BREACHED", "walls": [], "clusters": []})
        sig.setdefault("st_flip_tfs",       [])
        sig.setdefault("st_put_norm_eod",   0)
        sig.setdefault("st_call_norm_eod",  0)

    # Intraday 9:15 AM snapshot — write to session_state only in Streamlit context
    try:
        tf_sigs_snap = sig.get("st_tf_signals", {})
        if tf_sigs_snap and st.session_state.get("st_open_put_norm") is None:
            tier3 = ["1h", "30m", "15m"]
            from analytics.supertrend import MAX_RAW as ST_MAX_RAW
            t3_put_raw  = sum(tf_sigs_snap.get(tf, {}).get("raw_score", 0)
                              for tf in tier3 if tf_sigs_snap.get(tf, {}).get("side") == "PUT")
            t3_call_raw = sum(tf_sigs_snap.get(tf, {}).get("raw_score", 0)
                              for tf in tier3 if tf_sigs_snap.get(tf, {}).get("side") == "CALL")
            st.session_state["st_open_put_norm"]  = round((t3_put_raw  / ST_MAX_RAW) * 100, 1)
            st.session_state["st_open_call_norm"] = round((t3_call_raw / ST_MAX_RAW) * 100, 1)
    except Exception:
        pass  # not a Streamlit session — snapshot skipped, harmless

    _build_lens_table(sig, spot)
    _compute_master_score(sig)
    return sig


def _build_lens_table(sig: dict, spot: float) -> None:
    atr14 = max(sig.get("atr14", 200), 1)

    l1_pe = sig.get("cr_pe_dist_pts", int(round(2.0 * atr14 / 50) * 50))
    l1_ce = sig.get("cr_ce_dist_pts", int(round(2.0 * atr14 / 50) * 50))

    w_regime = sig.get("w_regime", sig.get("weekly_regime", "W_NEUTRAL"))
    RSI_PE = {"W_CAPIT":3.25,"W_BEAR":2.75,"W_BEAR_TRANS":2.50,"W_NEUTRAL":2.25,
              "W_BULL_TRANS":2.00,"W_BULL":2.00,"W_BULL_EXH":2.50}
    RSI_CE = {"W_CAPIT":2.00,"W_BEAR":2.00,"W_BEAR_TRANS":2.25,"W_NEUTRAL":2.25,
              "W_BULL_TRANS":2.50,"W_BULL":2.75,"W_BULL_EXH":2.50}
    kills    = sig.get("kill_switches", {})
    dual_exh = kills.get("RSI_DUAL_EXHAUSTION") or kills.get("K3")
    rsi_pe_m = RSI_PE.get(w_regime, 2.25)
    rsi_ce_m = RSI_CE.get(w_regime, 2.25)
    if dual_exh: rsi_pe_m = max(rsi_pe_m, 3.0); rsi_ce_m = max(rsi_ce_m, 3.0)
    l2_pe = int(round(rsi_pe_m * atr14 / 50) * 50)
    l2_ce = int(round(rsi_ce_m * atr14 / 50) * 50)

    breadth_lbl  = sig.get("breadth_label", "ADEQUATE")
    const_pe_mod = sig.get("constituent_pe_mod", 0)
    BP = {"BROAD_HEALTH":2.00,"ADEQUATE":2.25,"THINNING":2.50,"COLLAPSE":3.00}
    l3_pe_m = BP.get(breadth_lbl, 2.25)
    if const_pe_mod >= 300:   l3_pe_m = max(l3_pe_m, 2.75)
    elif const_pe_mod >= 200: l3_pe_m = max(l3_pe_m, 2.50)
    elif const_pe_mod < 0:    l3_pe_m = max(l3_pe_m - 0.25, 2.00)
    l3_pe = int(round(l3_pe_m * atr14 / 50) * 50)
    l3_ce = int(round(2.25 * atr14 / 50) * 50)

    bb_regime = sig.get("bb_regime", "NEUTRAL_WALK")
    neutral   = int(round(2.25 * atr14 / 50) * 50)
    if bb_regime == "MEAN_REVERT":
        l4_pe = l4_ce = int(round(2.00 * atr14 / 50) * 50)
    elif bb_regime == "SQUEEZE":
        l4_pe = l4_ce = int(round(2.50 * atr14 / 50) * 50)
    else:
        l4_pe = neutral + sig.get("bb_distance_put", 0)
        l4_ce = neutral + sig.get("bb_distance_call", 0)

    vix_state = sig.get("vix_state", "STABLE_NORMAL")
    vrp       = sig.get("vrp", 0.0)
    VM = {"STABLE_LOW":2.00,"STABLE_NORMAL":2.25,"SPIKE_RESOLVING":2.25,
          "ELEVATED":2.50,"CAUTION":2.75,"DANGER":3.25}
    vix_m = VM.get(vix_state, 2.25)
    if vrp < 0:   vix_m = max(vix_m, 2.75)
    if vrp > 5.0: vix_m = max(vix_m - 0.25, 2.00)
    l5_pe = l5_ce = int(round(vix_m * atr14 / 50) * 50)

    l6_pe = sig.get("mp_pe_biwkly_dist", int(round(2.25 * atr14 / 50) * 50))
    l6_ce = sig.get("mp_ce_biwkly_dist", int(round(2.25 * atr14 / 50) * 50))

    # SuperTrend MTF lens row
    l7_pe = sig.get("st_lens_pe_dist", 0)
    l7_ce = sig.get("st_lens_ce_dist", 0)
    # If ST produced no data, exclude from table (don't add a zero row)
    st_has_data = l7_pe > 0 or l7_ce > 0

    lens_table = {
        "EMA (regime+moat+momentum)": {"pe": l1_pe, "ce": l1_ce},
        "RSI (weekly regime)":         {"pe": l2_pe, "ce": l2_ce},
        "Constituent EMA (breadth)":   {"pe": l3_pe, "ce": l3_ce},
        "Bollinger":                   {"pe": l4_pe, "ce": l4_ce},
        "VIX / IV":                    {"pe": l5_pe, "ce": l5_ce},
        "Market Profile (biweekly)":   {"pe": l6_pe, "ce": l6_ce},
    }
    if st_has_data:
        lens_table["SuperTrend MTF"] = {"pe": l7_pe, "ce": l7_ce}

    sig["lens_table"] = lens_table

    # ST floor/ceiling warning flags for display
    put_dist_d = sig.get("st_put_dist", {})
    call_dist_d = sig.get("st_call_dist", {})
    sig["st_pe_case"] = put_dist_d.get("case", "NO_WALL")
    sig["st_ce_case"] = call_dist_d.get("case", "NO_WALL")
    sig["st_pe_label"] = put_dist_d.get("label", "—")
    sig["st_ce_label"] = call_dist_d.get("label", "—")

    all_pe = {n: v["pe"] for n, v in lens_table.items()}
    all_ce = {n: v["ce"] for n, v in lens_table.items()}
    suggested_pe      = max(all_pe.values())
    suggested_ce      = max(all_ce.values())
    suggested_pe_lens = max(all_pe, key=all_pe.get)
    suggested_ce_lens = max(all_ce, key=all_ce.get)

    if sig.get("pe_dual_fortress"): suggested_pe = max(suggested_pe - DUAL_FORTRESS_DIST_RED, int(round(2.0 * atr14 / 50) * 50))
    if sig.get("ce_dual_fortress"): suggested_ce = max(suggested_ce - DUAL_FORTRESS_DIST_RED, int(round(2.0 * atr14 / 50) * 50))

    suggested_pe = round(suggested_pe / 50) * 50
    suggested_ce = round(suggested_ce / 50) * 50

    sig["suggested_pe_dist"]  = int(suggested_pe)
    sig["suggested_ce_dist"]  = int(suggested_ce)
    sig["suggested_pe_lens"]  = suggested_pe_lens
    sig["suggested_ce_lens"]  = suggested_ce_lens
    sig["final_put_dist"]     = int(suggested_pe)
    sig["final_call_dist"]    = int(suggested_ce)
    sig["final_put_short"]    = int(round((spot - suggested_pe) / 50) * 50)
    sig["final_call_short"]   = int(round((spot + suggested_ce) / 50) * 50)
    sig["final_put_wing"]     = sig["final_put_short"]  - WING_DISTANCE
    sig["final_call_wing"]    = sig["final_call_short"] + WING_DISTANCE


def _compute_master_score(sig: dict) -> None:
    # All scores capped at their rescaled maximums (Option B)
    ema_sc = min(sig.get("home_score", 0),            HOME_SCORE_MAX_EMA)
    bb_sc  = min(sig.get("bb_home_score", 0),         HOME_SCORE_MAX_BB)
    vx_sc  = min(sig.get("vix_home_score", 0),        HOME_SCORE_MAX_VIX)
    mp_sc  = min(sig.get("mp_home_score",  0),        HOME_SCORE_MAX_MP)
    dow_sc = min(sig.get("dow_home_score", 0),        HOME_SCORE_MAX_DOW)
    st_sc  = min(sig.get("st_home_score",  0),        HOME_SCORE_MAX_ST)

    alignment = sig.get("mtf_alignment", sig.get("alignment", "MIXED"))
    rsi_raw = (
        HOME_SCORE_MAX_RSI     if alignment == "ALIGNED_BULL" else
        HOME_SCORE_MAX_RSI - 2 if alignment == "ALIGNED_BULL_NEUTRAL" else
        HOME_SCORE_MAX_RSI - 4 if alignment == "ALIGNED_BEAR" else
        HOME_SCORE_MAX_RSI // 4 if "COUNTER" in alignment else
        HOME_SCORE_MAX_RSI // 2
    )
    kills = sig.get("kill_switches", {})
    if kills.get("RSI_DUAL_EXHAUSTION") or kills.get("K3"):
        rsi_raw = max(0, rsi_raw - min(10, HOME_SCORE_MAX_RSI // 2))
    if kills.get("RSI_REGIME_FLIP")     or kills.get("K1"):
        rsi_raw = max(0, rsi_raw - min(5,  HOME_SCORE_MAX_RSI // 4))
    rsi_sc = min(rsi_raw, HOME_SCORE_MAX_RSI)

    if sig.get("BANKING_DAILY_COLLAPSE") or sig.get("sd6_collapse"):
        ema_sc = 0; rsi_sc = 0
    if sig.get("is_danger"): vx_sc = max(0, vx_sc - 3)

    master = min(100, ema_sc + rsi_sc + bb_sc + vx_sc + mp_sc + dow_sc + st_sc)
    sig["master_score"]   = master
    sig["master_verdict"] = (
        "ENTER — high confidence"      if master >= 75 else
        "ENTER — proceed with caution" if master >= 55 else
        "MARGINAL — reduce size"       if master >= 40 else
        "STAND ASIDE"
    )
    sig["master_colour"] = (
        "#16a34a" if master >= 75 else
        "#d97706" if master >= 55 else
        "#ea580c" if master >= 40 else
        "#dc2626"
    )
    sig["_lens_scores"] = {
        "EMA (P1+2)":       ema_sc,
        "RSI (P5-8)":       rsi_sc,
        "Bollinger":        bb_sc,
        "VIX/IV":           vx_sc,
        "Mkt Profile":      mp_sc,
        "Dow Theory":       dow_sc,
        "SuperTrend MTF":   st_sc,
    }


def _first_active_kill(kills: dict) -> str | None:
    for k, v in kills.items():
        if v: return k
    return None


def load_saved_signals() -> dict:
    if SIGNALS_PATH.exists():
        try: return json.loads(SIGNALS_PATH.read_text())
        except Exception: pass
    return {}


def save_signals(sig: dict) -> None:
    SIGNALS_PATH.parent.mkdir(exist_ok=True)
    clean = {k: v for k, v in sig.items()
             if not hasattr(v, "to_dict") and k not in ("near_scored","far_scored")}
    try: SIGNALS_PATH.write_text(json.dumps(clean, default=str, indent=2))
    except Exception as e: log.error("Failed to save signals: %s", e)


@st.cache_data(ttl=300, show_spinner=False)
def get_cached_signals(nifty_df, stock_dfs, vix_live, vix_hist, chains, spot,
                       nifty_1h=None, nifty_30m=None, nifty_15m=None, nifty_5m=None):
    return compute_all_signals(
        nifty_df, stock_dfs, vix_live, vix_hist, chains, spot,
        nifty_1h=nifty_1h, nifty_30m=nifty_30m,
        nifty_15m=nifty_15m, nifty_5m=nifty_5m,
    )
