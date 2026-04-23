# pages/14_Position_Tracker.py — Phase 1 (22 April 2026)
# Multi-Leg Position Tracker
#
# LOCKED SPEC (per premiumdecay_locked_rules_22Apr2026_1600IST.docx Section 8.1):
#   - Separate page — not integrated into Home
#   - Persists across sessions via JSON file on disk
#   - Up to 3 simultaneous IC position placeholders
#   - 4 legs per side (2 short + 2 long) on both CE and PE sides — max 8 legs per position
#   - Leg inputs: strike, type (CE/PE), direction (Long/Short), expiry, entry premium, lots
#   - Live P&L: current LTP vs entry premium per leg, summed per position
#   - Total P&L: grand total across all 3 positions at top
#   - Booked legs: entry + exit premium stored, booked P&L shown separately
#   - Phase 1 is position memory and P&L ONLY — no automated recommendations
#
# Storage: data/positions.json
# LTP: fetched live from Kite for each leg's strike/expiry/type

import streamlit as st
import pandas as pd
import json
import datetime
from pathlib import Path
import ui.components as ui

st.set_page_config(page_title="P14 · Position Tracker", layout="wide")
# No auto-refresh — manual refresh button below
st.title("Page 14 — Multi-Leg Position Tracker")
st.caption("Up to 3 IC positions · 4 legs per side · Live P&L · Booked P&L · Persists across sessions")

# ── Auto-compute signals if needed ────────────────────────────────────────────
sig = st.session_state.get("signals", {})
if not sig:
    with st.spinner("Loading signals…"):
        try:
            from data.live_fetcher import (
                get_nifty_spot, get_nifty_daily, get_top10_daily,
                get_india_vix, get_vix_history, get_dual_expiry_chains,
            )
            from analytics.compute_signals import compute_all_signals
            spot     = get_nifty_spot()
            nifty_df = get_nifty_daily()
            stock_dfs= get_top10_daily()
            vix_live = get_india_vix()
            vix_hist = get_vix_history()
            chains   = get_dual_expiry_chains(spot)
            if spot == 0 and not nifty_df.empty:
                spot = float(nifty_df["close"].iloc[-1])
            sig = compute_all_signals(nifty_df, stock_dfs, vix_live, vix_hist, chains, spot)
            st.session_state["signals"] = sig
        except Exception:
            sig = {}

# ── Constants ─────────────────────────────────────────────────────────────────
POSITIONS_FILE = Path("data/positions.json")
LOT_SIZE       = 65
MAX_POSITIONS  = 3
MAX_LEGS_SIDE  = 4   # 2 short + 2 long per side

# Default empty leg structure
def empty_leg(leg_id: str) -> dict:
    return {
        "id":            leg_id,
        "active":        False,
        "type":          "CE",         # CE or PE
        "direction":     "Short",      # Short or Long
        "strike":        0,
        "expiry":        "",
        "entry_premium": 0.0,
        "lots":          1,
        "booked":        False,
        "exit_premium":  0.0,
        "entry_date":    "",
        "exit_date":     "",
    }

def default_position(pos_id: int) -> dict:
    legs = {}
    for side in ["CE", "PE"]:
        for i in range(1, MAX_LEGS_SIDE + 1):
            leg_id = f"{side}_{i}"
            legs[leg_id] = empty_leg(leg_id)
            legs[leg_id]["type"] = side
            # Alternate Short/Long: 1,2=Short 3,4=Long
            legs[leg_id]["direction"] = "Short" if i <= 2 else "Long"
    return {
        "id":    pos_id,
        "name":  f"Position {pos_id}",
        "legs":  legs,
        "notes": "",
    }

# ── Persistence ───────────────────────────────────────────────────────────────
def load_positions() -> list:
    if POSITIONS_FILE.exists():
        try:
            data = json.loads(POSITIONS_FILE.read_text())
            # Ensure 3 positions always exist
            while len(data) < MAX_POSITIONS:
                data.append(default_position(len(data) + 1))
            return data[:MAX_POSITIONS]
        except Exception:
            pass
    return [default_position(i) for i in range(1, MAX_POSITIONS + 1)]

def save_positions(positions: list):
    POSITIONS_FILE.parent.mkdir(exist_ok=True)
    POSITIONS_FILE.write_text(json.dumps(positions, indent=2))

# ── Live LTP fetch ────────────────────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def get_leg_ltp(strike: int, expiry_str: str, opt_type: str) -> float:
    """
    Fetch LTP for a single option leg.
    expiry_str: YYYY-MM-DD format
    opt_type: CE or PE
    Returns 0.0 if unavailable.
    """
    if not strike or not expiry_str:
        return 0.0
    try:
        from data.kite_client import get_kite
        from datetime import date
        exp = date.fromisoformat(expiry_str)
        yy  = exp.strftime("%y")
        m   = exp.month
        dd  = exp.day
        sym = f"NFO:NIFTY{yy}{m}{dd}{strike}{opt_type}"
        kite = get_kite()
        quote = kite.quote([sym])
        if sym in quote:
            return float(quote[sym]["last_price"])
        return 0.0
    except Exception:
        return 0.0

def compute_leg_pnl(leg: dict) -> dict:
    """
    Compute live P&L and booked P&L for a single leg.
    Returns dict with live_ltp, live_pnl, booked_pnl, total_pnl.
    """
    if not leg["active"]:
        return {"live_ltp": 0.0, "live_pnl": 0.0, "booked_pnl": 0.0, "total_pnl": 0.0}

    entry  = leg["entry_premium"]
    lots   = leg["lots"]
    dirn   = leg["direction"]   # Short or Long
    mult   = -1 if dirn == "Short" else 1   # Short = sold premium, profit if price falls

    if leg["booked"]:
        exit_p = leg["exit_premium"]
        # For Short: profit = entry - exit. For Long: profit = exit - entry
        booked = (entry - exit_p) * mult * lots * LOT_SIZE
        return {"live_ltp": exit_p, "live_pnl": 0.0, "booked_pnl": round(booked, 0), "total_pnl": round(booked, 0)}

    # Live leg
    live_ltp = get_leg_ltp(leg["strike"], leg["expiry"], leg["type"])
    if live_ltp == 0.0 and entry > 0:
        # LTP unavailable — show entry as placeholder
        live_ltp = entry

    live_pnl = (entry - live_ltp) * mult * lots * LOT_SIZE
    return {
        "live_ltp":   round(live_ltp, 2),
        "live_pnl":   round(live_pnl, 0),
        "booked_pnl": 0.0,
        "total_pnl":  round(live_pnl, 0),
    }

# ── Load state ────────────────────────────────────────────────────────────────
if "positions" not in st.session_state:
    st.session_state["positions"] = load_positions()

positions = st.session_state["positions"]

# ── Compute grand totals ──────────────────────────────────────────────────────
grand_live   = 0.0
grand_booked = 0.0
pos_summaries = []

for pos in positions:
    pos_live = pos_booked = 0.0
    active_leg_count = 0
    for leg in pos["legs"].values():
        if leg["active"]:
            active_leg_count += 1
            pnl = compute_leg_pnl(leg)
            pos_live   += pnl["live_pnl"]
            pos_booked += pnl["booked_pnl"]
    grand_live   += pos_live
    grand_booked += pos_booked
    pos_summaries.append({
        "name":        pos["name"],
        "active_legs": active_leg_count,
        "live_pnl":    pos_live,
        "booked_pnl":  pos_booked,
        "total_pnl":   pos_live + pos_booked,
    })

grand_total = grand_live + grand_booked

# ══════════════════════════════════════════════════════════════════════════════
# GRAND TOTAL HEADER
# ══════════════════════════════════════════════════════════════════════════════
total_col = "#16a34a" if grand_total >= 0 else "#dc2626"
st.markdown(
    f"<div style='background:{total_col};border-radius:10px;padding:16px 24px;"
    f"display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;'>"
    f"<div>"
    f"<div style='color:white;font-size:11px;font-weight:700;letter-spacing:1px;'>TOTAL P&L — ALL POSITIONS</div>"
    f"<div style='color:rgba(255,255,255,0.75);font-size:10px;'>Live: {grand_live:+,.0f} pts · Booked: {grand_booked:+,.0f} pts</div>"
    f"</div>"
    f"<div style='color:white;font-size:32px;font-weight:900;'>{grand_total:+,.0f} pts</div>"
    f"</div>",
    unsafe_allow_html=True)

# Position summary strip
cols_top = st.columns(3)
for i, ps in enumerate(pos_summaries):
    col = "#16a34a" if ps["total_pnl"] >= 0 else "#dc2626" if ps["total_pnl"] < 0 else "#94a3b8"
    with cols_top[i]:
        ui.metric_card(
            ps["name"],
            f"{ps['total_pnl']:+,.0f} pts",
            sub=f"{ps['active_legs']} active legs · Live {ps['live_pnl']:+,.0f} · Booked {ps['booked_pnl']:+,.0f}",
            color="green" if ps["total_pnl"] >= 0 else "red" if ps["total_pnl"] < 0 else "default"
        )

# Manual refresh button
col_ref, col_time, _ = st.columns([1, 2, 5])
with col_ref:
    if st.button("🔄 Refresh P&L", use_container_width=True,
                 help="Fetch latest LTP for all live legs and recalculate P&L"):
        st.cache_data.clear()
        st.rerun()
with col_time:
    st.caption(f"Last refreshed: {datetime.datetime.now().strftime('%H:%M:%S')}")

st.divider()


# ── Leg rendering function ────────────────────────────────────────────────────
def _render_legs(tab_idx: int, pos: dict, side: str, positions: list):
    """Render 4 legs for one side (CE or PE) in a grid."""
    leg_ids   = [f"{side}_1", f"{side}_2", f"{side}_3", f"{side}_4"]
    leg_labels = [f"{side} Short 1", f"{side} Short 2", f"{side} Long 1", f"{side} Long 2"]

    # Two rows of two legs
    for row_start in [0, 2]:
        cols = st.columns(2)
        for col_offset in range(2):
            leg_idx = row_start + col_offset
            leg_id  = leg_ids[leg_idx]
            label   = leg_labels[leg_idx]
            leg     = pos["legs"][leg_id]
            dirn    = "Short" if leg_idx < 2 else "Long"

            with cols[col_offset]:
                _render_single_leg(tab_idx, pos, leg_id, leg, label, dirn, positions)


def _render_single_leg(tab_idx, pos, leg_id, leg, label, default_dirn, positions):
    """Render input form for one leg."""
    # Color header by direction
    header_col = "#dc2626" if default_dirn == "Short" else "#16a34a"
    is_active  = leg["active"]
    is_booked  = leg.get("booked", False)

    status_badge = ("🔴 BOOKED" if is_booked else
                    "🟢 LIVE"   if is_active  else
                    "⚪ Empty")

    st.markdown(
        f"<div style='border-left:4px solid {header_col};padding:4px 8px;"
        f"background:#f8f9fb;border-radius:4px;margin-bottom:8px;'>"
        f"<span style='font-size:11px;font-weight:700;color:{header_col};'>{label}</span>"
        f"<span style='font-size:10px;color:#94a3b8;margin-left:8px;'>{status_badge}</span>"
        f"</div>",
        unsafe_allow_html=True)

    key_pfx = f"p{tab_idx}_{leg_id}"

    with st.expander(f"{'Edit' if is_active else 'Add'} {label}", expanded=is_active):

        col1, col2 = st.columns(2)
        with col1:
            strike = st.number_input("Strike", value=int(leg["strike"]) if leg["strike"] else 0,
                                      step=50, min_value=0, key=f"{key_pfx}_strike")
            expiry = st.text_input("Expiry (YYYY-MM-DD)", value=leg["expiry"],
                                    placeholder="2026-04-29", key=f"{key_pfx}_expiry")
            lots   = st.number_input("Lots", value=int(leg["lots"]) if leg["lots"] else 1,
                                      step=1, min_value=1, max_value=50, key=f"{key_pfx}_lots")

        with col2:
            entry_prem = st.number_input("Entry premium (pts)", value=float(leg["entry_premium"]),
                                          step=0.5, min_value=0.0, key=f"{key_pfx}_entry")
            entry_date = st.text_input("Entry date (YYYY-MM-DD)",
                                        value=leg.get("entry_date", ""),
                                        placeholder=str(datetime.date.today()),
                                        key=f"{key_pfx}_edate")
            # Booked exit
            if is_booked:
                exit_prem = st.number_input("Exit premium (pts)", value=float(leg.get("exit_premium",0)),
                                             step=0.5, min_value=0.0, key=f"{key_pfx}_exit")
                exit_date = st.text_input("Exit date", value=leg.get("exit_date",""),
                                           key=f"{key_pfx}_xdate")

        # Buttons
        btn1, btn2, btn3 = st.columns(3)
        with btn1:
            if st.button("💾 Save leg", key=f"{key_pfx}_save", use_container_width=True):
                positions[tab_idx]["legs"][leg_id].update({
                    "active":        True,
                    "booked":        False,
                    "type":          leg_id.split("_")[0],
                    "direction":     default_dirn,
                    "strike":        int(strike),
                    "expiry":        expiry,
                    "entry_premium": float(entry_prem),
                    "lots":          int(lots),
                    "entry_date":    entry_date,
                })
                save_positions(positions)
                st.rerun()

        with btn2:
            if is_active and not is_booked:
                exit_prem_quick = st.number_input("Exit @ (pts)", value=0.0,
                                                   step=0.5, min_value=0.0,
                                                   key=f"{key_pfx}_exitquick",
                                                   label_visibility="collapsed")
                if st.button("📦 Book", key=f"{key_pfx}_book", use_container_width=True,
                             help="Mark leg as closed at exit premium"):
                    positions[tab_idx]["legs"][leg_id].update({
                        "booked":       True,
                        "exit_premium": float(exit_prem_quick),
                        "exit_date":    str(datetime.date.today()),
                    })
                    save_positions(positions)
                    st.rerun()

        with btn3:
            if is_active:
                if st.button("🗑 Remove", key=f"{key_pfx}_del", use_container_width=True):
                    positions[tab_idx]["legs"][leg_id] = empty_leg(leg_id)
                    positions[tab_idx]["legs"][leg_id]["type"]      = leg_id.split("_")[0]
                    positions[tab_idx]["legs"][leg_id]["direction"]  = default_dirn
                    save_positions(positions)
                    st.rerun()

        # Live P&L display for active leg
        if is_active:
            pnl = compute_leg_pnl(leg)
            ltp_display = f"LTP: {pnl['live_ltp']:.1f}" if not is_booked else f"Booked @ {leg.get('exit_premium',0):.1f}"
            pnl_val = pnl["booked_pnl"] if is_booked else pnl["live_pnl"]
            pnl_col = "#16a34a" if pnl_val >= 0 else "#dc2626"
            st.markdown(
                f"<div style='background:#f0f4ff;border-radius:4px;padding:6px 10px;"
                f"display:flex;justify-content:space-between;font-size:11px;margin-top:6px;'>"
                f"<span style='color:#334155;'>{ltp_display} · {lots} lots × {LOT_SIZE}</span>"
                f"<span style='font-weight:700;color:{pnl_col};'>{pnl_val:+,.0f} pts</span>"
                f"</div>",
                unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# POSITION TABS
# ══════════════════════════════════════════════════════════════════════════════
tab_labels = [f"📋 {p['name']}" for p in positions]
tabs = st.tabs(tab_labels)

for tab_idx, (tab, pos) in enumerate(zip(tabs, positions)):
    with tab:

        # Position name edit
        col_name, col_notes, col_clear = st.columns([2, 4, 1])
        with col_name:
            new_name = st.text_input("Position name", value=pos["name"],
                                      key=f"posname_{tab_idx}")
            if new_name != pos["name"]:
                positions[tab_idx]["name"] = new_name
                save_positions(positions)
                st.rerun()
        with col_notes:
            new_notes = st.text_area("Notes", value=pos.get("notes",""),
                                      height=68, key=f"posnotes_{tab_idx}")
            if new_notes != pos.get("notes",""):
                positions[tab_idx]["notes"] = new_notes
                save_positions(positions)
        with col_clear:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑 Clear all", key=f"clearpos_{tab_idx}",
                         help="Clear all legs in this position"):
                positions[tab_idx] = default_position(tab_idx + 1)
                positions[tab_idx]["name"] = pos["name"]
                save_positions(positions)
                st.rerun()

        st.markdown("")

        # ── CE Side ──────────────────────────────────────────────────────────
        ui.section_header("CE Side (Call Legs)",
                          "2 Short + 2 Long · Short = sold, Long = bought")
        _render_legs(tab_idx, pos, "CE", positions)

        st.markdown("")

        # ── PE Side ──────────────────────────────────────────────────────────
        ui.section_header("PE Side (Put Legs)",
                          "2 Short + 2 Long · Short = sold, Long = bought")
        _render_legs(tab_idx, pos, "PE", positions)

        st.markdown("")

        # ── Position P&L summary ─────────────────────────────────────────────
        ps = pos_summaries[tab_idx]
        if ps["active_legs"] > 0:
            ui.section_header("Position P&L Summary", "Live + Booked")
            c1, c2, c3 = st.columns(3)
            with c1: ui.metric_card("LIVE P&L",   f"{ps['live_pnl']:+,.0f} pts",
                                      color="green" if ps["live_pnl"] >= 0 else "red")
            with c2: ui.metric_card("BOOKED P&L", f"{ps['booked_pnl']:+,.0f} pts",
                                      color="green" if ps["booked_pnl"] >= 0 else "red")
            with c3: ui.metric_card("TOTAL P&L",  f"{ps['total_pnl']:+,.0f} pts",
                                      color="green" if ps["total_pnl"] >= 0 else "red")
            # Points to rupees
            spot_now = sig.get("final_put_short", 0) + sig.get("final_put_dist", 0)
            if spot_now > 0:
                # 1 pt = LOT_SIZE rupees
                live_inr  = ps["live_pnl"]  * LOT_SIZE
                total_inr = ps["total_pnl"] * LOT_SIZE
                st.caption(f"In rupees (approx): Live ₹{live_inr:+,.0f} · Total ₹{total_inr:+,.0f} · Lot size {LOT_SIZE}")

