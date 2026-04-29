# pages/14_Positions.py — premiumdecay Position Tracker
# Phase 1: Position memory + Live P&L only
# Up to 3 IC positions · 8 legs per position · Persists to JSON across restarts
# No automated recommendations in Phase 1.

import streamlit as st
import json
import datetime
import pytz
from pathlib import Path
from streamlit_autorefresh import st_autorefresh
import ui.components as ui

st.set_page_config(page_title="P14 · Positions", layout="wide")
st_autorefresh(interval=60_000, key="p14")

st.title("Page 14 — Position Tracker")
st.caption("Multi-leg IC position memory · Live P&L · Booked legs · Persists across restarts")

# ── Bootstrap ─────────────────────────────────────────────────────────────────
from page_utils import bootstrap_signals, show_page_header
sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)

_IST = pytz.timezone("Asia/Kolkata")

# ── Persistence helpers ───────────────────────────────────────────────────────
_POSITIONS_PATH = Path(__file__).parent.parent / "data" / "positions.json"
LOT_SIZE = 75  # Nifty lot size — update if NSE changes


def _empty_leg() -> dict:
    return {
        "strike": 0,
        "type": "CE",
        "direction": "Short",
        "expiry": "",
        "entry_premium": 0.0,
        "lots": 1,
        "status": "open",
    }


def _empty_position(slot: int) -> dict:
    return {
        "slot": slot,
        "label": f"Position {slot}",
        "structure": "Standard IC",
        "entry_date": "",
        "notes": "",
        "legs": [_empty_leg() for _ in range(8)],
        "booked_legs": [],
        "active": False,
    }


def _load_positions() -> list:
    try:
        _POSITIONS_PATH.parent.mkdir(exist_ok=True)
        if _POSITIONS_PATH.exists():
            raw = json.loads(_POSITIONS_PATH.read_text())
            while len(raw) < 3:
                raw.append(_empty_position(len(raw) + 1))
            return raw[:3]
    except Exception:
        pass
    return [_empty_position(i + 1) for i in range(3)]


def _save_positions(positions: list) -> None:
    try:
        _POSITIONS_PATH.parent.mkdir(exist_ok=True)
        _POSITIONS_PATH.write_text(json.dumps(positions, indent=2))
    except Exception as e:
        st.error(f"Failed to save positions: {e}")


def _get_ltp(strike: int, opt_type: str, expiry: str) -> float:
    """Fetch LTP for a single option leg via Kite direct quote."""
    if strike == 0 or not expiry:
        return 0.0
    try:
        from data.kite_client import get_kite
        kite = get_kite()
        symbol = f"NFO:NIFTY{expiry}{strike}{opt_type}"
        quote = kite.quote([symbol])
        if symbol in quote:
            return float(quote[symbol]["last_price"])
    except Exception:
        pass
    return 0.0


def _leg_pnl_pts(leg: dict) -> float:
    """P&L in points per unit for an open leg."""
    if leg.get("status") != "open" or leg["strike"] == 0 or leg["entry_premium"] == 0:
        return 0.0
    ltp = _get_ltp(leg["strike"], leg["type"], leg["expiry"])
    if ltp == 0:
        return 0.0
    if leg["direction"] == "Short":
        return leg["entry_premium"] - ltp
    return ltp - leg["entry_premium"]


def _leg_pnl_inr(leg: dict) -> float:
    return _leg_pnl_pts(leg) * leg.get("lots", 1) * LOT_SIZE


def _booked_pnl_inr(bl: dict) -> float:
    qty = bl.get("lots", 1) * LOT_SIZE
    if bl.get("direction") == "Short":
        return (bl.get("entry_premium", 0) - bl.get("exit_premium", 0)) * qty
    return (bl.get("exit_premium", 0) - bl.get("entry_premium", 0)) * qty


# ── Load into session state once per session ──────────────────────────────────
if "positions" not in st.session_state:
    st.session_state["positions"] = _load_positions()

positions = st.session_state["positions"]

# ══════════════════════════════════════════════════════════════════════════════
# GRAND TOTAL P&L
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
ui.section_header("Grand Total P&L", "Live across all active positions — updates every 60s")

total_live   = 0.0
total_booked = 0.0
active_count = 0

for pos in positions:
    if not pos["active"]:
        continue
    active_count += 1
    total_live   += sum(_leg_pnl_inr(leg) for leg in pos["legs"])
    total_booked += sum(_booked_pnl_inr(bl) for bl in pos.get("booked_legs", []))

grand_total = total_live + total_booked

if active_count == 0:
    st.info("No active positions. Activate a slot below and fill in leg details.")
else:
    tc1, tc2, tc3, tc4 = st.columns(4)
    with tc1:
        ui.metric_card("GRAND TOTAL", f"₹{grand_total:+,.0f}",
                       sub="Live + Booked",
                       color="green" if grand_total >= 0 else "red")
    with tc2:
        ui.metric_card("LIVE P&L", f"₹{total_live:+,.0f}",
                       sub="Open legs at current LTP",
                       color="green" if total_live >= 0 else "red")
    with tc3:
        ui.metric_card("BOOKED P&L", f"₹{total_booked:+,.0f}",
                       sub="Closed legs — locked in",
                       color="green" if total_booked >= 0 else "red")
    with tc4:
        ui.metric_card("ACTIVE SLOTS", str(active_count), sub="of 3 slots in use")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# POSITION SLOTS
# ══════════════════════════════════════════════════════════════════════════════
STRUCTURES = ["Standard IC", "Single Spread", "IC with Calendar", "Ratio", "Diagonal", "Custom"]
OPT_TYPES  = ["CE", "PE"]
DIRECTIONS = ["Short", "Long"]

for slot_idx, pos in enumerate(positions):
    slot_num  = pos["slot"]
    is_active = pos["active"]

    pos_live   = sum(_leg_pnl_inr(leg) for leg in pos["legs"]) if is_active else 0.0
    pos_booked = sum(_booked_pnl_inr(bl) for bl in pos.get("booked_legs", [])) if is_active else 0.0
    pos_total  = pos_live + pos_booked

    status_icon = "🟢" if is_active else "⚪"
    pnl_str     = f"  ·  ₹{pos_total:+,.0f}" if is_active else ""
    exp_title   = f"{status_icon}  Slot {slot_num} — {pos['label']}{pnl_str}"

    with st.expander(exp_title, expanded=is_active):

        # ── Header controls ───────────────────────────────────────────────
        hc1, hc2, hc3, hc4 = st.columns([2, 2, 2, 1])
        with hc1:
            new_label = st.text_input("Label", value=pos["label"],
                                      key=f"label_{slot_idx}")
        with hc2:
            new_structure = st.selectbox(
                "Structure", STRUCTURES,
                index=STRUCTURES.index(pos.get("structure", "Standard IC")),
                key=f"struct_{slot_idx}"
            )
        with hc3:
            new_entry_date = st.text_input("Entry date", value=pos.get("entry_date", ""),
                                           placeholder="e.g. 29-Apr-26",
                                           key=f"edate_{slot_idx}")
        with hc4:
            new_active = st.toggle("Active", value=is_active, key=f"active_{slot_idx}")

        new_notes = st.text_input("Notes", value=pos.get("notes", ""),
                                  key=f"notes_{slot_idx}")
        st.markdown("---")

        # ── Leg entry grid ────────────────────────────────────────────────
        st.markdown("**Open Legs** — up to 8 legs. Leave Strike = 0 for unused slots.")

        col_headers = st.columns([1.5, 1, 1.5, 2.5, 1.5, 1, 1.5, 1.5])
        for col, hdr in zip(col_headers, ["Strike", "CE/PE", "Direction",
                                           "Expiry (e.g. 06MAY26)", "Entry Prem",
                                           "Lots", "LTP", "P&L"]):
            col.markdown(
                f"<p style='font-size:11px;color:#64748b;font-weight:600;"
                f"margin:0;padding-bottom:4px'>{hdr}</p>",
                unsafe_allow_html=True
            )

        updated_legs = []
        for li, leg in enumerate(pos["legs"]):
            lc = st.columns([1.5, 1, 1.5, 2.5, 1.5, 1, 1.5, 1.5])
            with lc[0]:
                s = st.number_input("", value=int(leg["strike"]), step=50,
                                    min_value=0, key=f"s_{slot_idx}_{li}",
                                    label_visibility="collapsed")
            with lc[1]:
                t = st.selectbox("", OPT_TYPES,
                                 index=OPT_TYPES.index(leg.get("type", "CE")),
                                 key=f"t_{slot_idx}_{li}",
                                 label_visibility="collapsed")
            with lc[2]:
                d = st.selectbox("", DIRECTIONS,
                                 index=DIRECTIONS.index(leg.get("direction", "Short")),
                                 key=f"d_{slot_idx}_{li}",
                                 label_visibility="collapsed")
            with lc[3]:
                ex = st.text_input("", value=leg.get("expiry", ""),
                                   key=f"ex_{slot_idx}_{li}",
                                   label_visibility="collapsed")
            with lc[4]:
                ep = st.number_input("", value=float(leg.get("entry_premium", 0.0)),
                                     step=0.25, min_value=0.0,
                                     key=f"ep_{slot_idx}_{li}",
                                     label_visibility="collapsed")
            with lc[5]:
                lots = st.number_input("", value=int(leg.get("lots", 1)),
                                       step=1, min_value=1,
                                       key=f"lots_{slot_idx}_{li}",
                                       label_visibility="collapsed")

            leg_active = s > 0 and ep > 0
            new_leg = {
                "strike": int(s), "type": t, "direction": d,
                "expiry": ex, "entry_premium": float(ep),
                "lots": int(lots),
                "status": "open" if leg_active else "empty",
            }

            ltp_val = _get_ltp(s, t, ex) if leg_active else 0.0
            pnl_inr = _leg_pnl_inr(new_leg) if leg_active and ltp_val > 0 else 0.0
            pnl_col = "#16a34a" if pnl_inr >= 0 else "#dc2626"

            with lc[6]:
                st.markdown(
                    f"<div style='padding-top:6px;font-size:13px;color:#334155'>"
                    f"{f'{ltp_val:.2f}' if ltp_val > 0 else '—'}</div>",
                    unsafe_allow_html=True
                )
            with lc[7]:
                st.markdown(
                    f"<div style='padding-top:6px;font-size:13px;"
                    f"font-weight:700;color:{pnl_col}'>"
                    f"{'₹' + f'{pnl_inr:+,.0f}' if leg_active and ltp_val > 0 else '—'}</div>",
                    unsafe_allow_html=True
                )
            updated_legs.append(new_leg)

        st.markdown("---")

        # ── Book a leg ────────────────────────────────────────────────────
        open_legs = [(li, leg) for li, leg in enumerate(updated_legs)
                     if leg["status"] == "open"]
        if open_legs:
            st.markdown("**Close a Leg**")
            bc1, bc2, bc3 = st.columns([3, 2, 1])
            leg_labels = [
                f"Leg {li+1}: {leg['strike']} {leg['type']} {leg['direction']}"
                for li, leg in open_legs
            ]
            with bc1:
                choice = st.selectbox("Select leg to close", leg_labels,
                                      key=f"book_sel_{slot_idx}")
            with bc2:
                exit_p = st.number_input("Exit premium", value=0.0, step=0.25,
                                         min_value=0.0, key=f"exit_p_{slot_idx}")
            with bc3:
                st.markdown("<div style='padding-top:28px'>", unsafe_allow_html=True)
                book_btn = st.button("📒 Book", key=f"book_{slot_idx}",
                                     use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)

            if book_btn and exit_p > 0:
                chosen_li = open_legs[leg_labels.index(choice)][0]
                bl = updated_legs[chosen_li].copy()
                bl["exit_premium"] = float(exit_p)
                bl["booked_at"] = datetime.datetime.now(_IST).strftime(
                    "%-d %b %Y %-I:%M %p IST"
                )
                bl["status"] = "closed"
                pos.setdefault("booked_legs", []).append(bl)
                updated_legs[chosen_li]["status"] = "closed"
                updated_legs[chosen_li]["entry_premium"] = 0.0
                st.success(f"✅ Booked at ₹{exit_p:.2f}")

        # ── Booked legs display ───────────────────────────────────────────
        booked = pos.get("booked_legs", [])
        if booked:
            st.markdown("**Booked Legs**")
            for bl in booked:
                bl_pnl = _booked_pnl_inr(bl)
                pnl_c  = "#16a34a" if bl_pnl >= 0 else "#dc2626"
                st.markdown(
                    f"<div style='font-size:12px;padding:5px 10px;"
                    f"background:#f8fafc;border-radius:4px;margin-bottom:3px;"
                    f"display:flex;gap:20px;align-items:center'>"
                    f"<span style='color:#334155;font-weight:600'>"
                    f"{bl['strike']} {bl['type']} {bl['direction']}</span>"
                    f"<span style='color:#64748b'>"
                    f"Entry: {bl.get('entry_premium',0):.2f}  →  "
                    f"Exit: {bl.get('exit_premium',0):.2f}</span>"
                    f"<span style='color:{pnl_c};font-weight:700'>₹{bl_pnl:+,.0f}</span>"
                    f"<span style='color:#94a3b8;font-size:11px'>"
                    f"{bl.get('booked_at','')}</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )

        # ── Slot P&L summary ──────────────────────────────────────────────
        if new_active and (pos_live != 0 or pos_booked != 0):
            pc1, pc2, pc3 = st.columns(3)
            with pc1:
                ui.metric_card("LIVE P&L", f"₹{pos_live:+,.0f}",
                               sub="Open legs at LTP",
                               color="green" if pos_live >= 0 else "red")
            with pc2:
                ui.metric_card("BOOKED P&L", f"₹{pos_booked:+,.0f}",
                               sub="Closed legs",
                               color="green" if pos_booked >= 0 else "red")
            with pc3:
                ui.metric_card("SLOT TOTAL", f"₹{pos_total:+,.0f}",
                               sub="Live + Booked",
                               color="green" if pos_total >= 0 else "red")

        # ── Save / Clear ──────────────────────────────────────────────────
        sv1, sv2 = st.columns([4, 1])
        with sv1:
            if st.button(f"💾 Save Position {slot_num}", key=f"save_{slot_idx}",
                         use_container_width=True):
                positions[slot_idx].update({
                    "label":      new_label,
                    "structure":  new_structure,
                    "entry_date": new_entry_date,
                    "active":     new_active,
                    "notes":      new_notes,
                    "legs":       updated_legs,
                })
                st.session_state["positions"] = positions
                _save_positions(positions)
                st.success("✅ Saved to disk — persists across restarts.")
        with sv2:
            if st.button("🗑 Clear", key=f"clear_{slot_idx}",
                         use_container_width=True, type="secondary"):
                positions[slot_idx] = _empty_position(slot_num)
                st.session_state["positions"] = positions
                _save_positions(positions)
                st.rerun()

st.divider()
st.caption(
    "LTP fetched live from Kite NFO quote API. Lot size = 75. "
    "Booked P&L is permanent — locked in at exit premium entered. "
    "All data saved to data/positions.json — survives app restarts. "
    "Phase 1: position memory and P&L only. No automated recommendations."
)
