# pages/16_Gamma_Roll.py — Gamma Provisioning & Defensive Roll Advisor
#
# Purpose: monitor gamma risk on active SHORT legs of biweekly IC positions.
#
# Biweekly cycle definition (Nifty):
#   Entry: ~14 DTE (far Tuesday expiry)
#   Target exit: DTE ≤ 5 or 55% profit
#   Defensive roll trigger: any of —
#     • DTE ≤ 5  AND spot within GAMMA_ROLL_MONO_RED pts of short strike
#     • DTE ≤ 3  (any proximity — terminal gamma risk)
#     • Current gamma ≥ GAMMA_ACCEL_ROLL × entry gamma
#
# What gamma provisioning means:
#   As DTE drops, gamma of short options accelerates. The delta of the short
#   position can change rapidly, making P&L unpredictable. Provisioning = knowing
#   WHEN to roll before gamma explodes, and WHERE to roll to next.
#
# Only SHORT legs are flagged (Long legs benefit from gamma, not harmed by it).

import datetime
import json
import math
from pathlib import Path

import numpy as np
import streamlit as st
from scipy.stats import norm

import ui.components as ui
from config import (
    GAMMA_BIWEEKLY_ENTRY_DTE,
    GAMMA_ROLL_DTE_RED,
    GAMMA_ROLL_DTE_AMBER,
    GAMMA_ROLL_MONO_RED,
    GAMMA_ROLL_MONO_AMBER,
    GAMMA_ACCEL_ROLL,
    GAMMA_ACCEL_WATCH,
    GAMMA_DEFAULT_IV,
)

LOT_SIZE = 65
RISK_FREE = 0.065

st.set_page_config(page_title="P16 · Gamma Roll", layout="wide")
st.title("Page 16 — Gamma Provisioning & Defensive Roll")
st.caption(
    "Monitors gamma acceleration on biweekly short legs · "
    "Entry ~14 DTE · Roll triggers: DTE ≤ 5 + proximity, or gamma ≥ 2× entry"
)

# ── Bootstrap signals ─────────────────────────────────────────────────────────
from page_utils import bootstrap_signals, show_page_header

sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)

if spot == 0:
    st.warning("⚠️ Spot price unavailable — gamma values will be approximate.")
    spot = 24000.0  # fallback for display

atm_iv = sig.get("atm_iv", GAMMA_DEFAULT_IV) or GAMMA_DEFAULT_IV
binding_ce = sig.get("binding_ce", 0)
binding_pe = sig.get("binding_pe", 0)

# ── Load positions ────────────────────────────────────────────────────────────
POSITIONS_FILE = Path("data/positions.json")


def _load_positions() -> list:
    if POSITIONS_FILE.exists():
        try:
            return json.loads(POSITIONS_FILE.read_text())
        except Exception:
            pass
    return []


positions = _load_positions()

# ── Greeks helpers ────────────────────────────────────────────────────────────

def _bs_gamma(S: float, K: float, T: float, iv_dec: float) -> float:
    """Black-Scholes gamma. T in years."""
    if T <= 0 or iv_dec <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (RISK_FREE + 0.5 * iv_dec ** 2) * T) / (iv_dec * math.sqrt(T))
        return norm.pdf(d1) / (S * iv_dec * math.sqrt(T))
    except Exception:
        return 0.0


def _dte_from_expiry(expiry_str: str) -> int:
    if not expiry_str:
        return 0
    try:
        exp = datetime.date.fromisoformat(expiry_str)
        return max(0, (exp - datetime.date.today()).days)
    except Exception:
        return 0


def _entry_dte(leg: dict) -> int:
    """DTE at entry, inferred from entry_date and expiry."""
    try:
        exp   = datetime.date.fromisoformat(leg["expiry"])
        entry = datetime.date.fromisoformat(leg["entry_date"])
        return max(1, (exp - entry).days)
    except Exception:
        return GAMMA_BIWEEKLY_ENTRY_DTE


def _gamma_metrics(leg: dict) -> dict:
    """
    Returns current gamma, entry gamma, gamma multiple, DTE, moneyness.
    Only meaningful for active, non-booked, Short legs.
    """
    strike = int(leg.get("strike", 0))
    expiry = leg.get("expiry", "")
    lots   = int(leg.get("lots", 1))

    if not strike or not expiry:
        return {}

    dte_now   = _dte_from_expiry(expiry)
    dte_entry = _entry_dte(leg)

    iv_dec = atm_iv / 100.0
    T_now   = max(dte_now, 0.25) / 365
    T_entry = max(dte_entry, 0.25) / 365

    g_now   = _bs_gamma(spot, strike, T_now,   iv_dec)
    g_entry = _bs_gamma(spot, strike, T_entry, iv_dec)

    gamma_multiple = (g_now / g_entry) if g_entry > 0 else 1.0
    moneyness_pts  = abs(spot - strike)

    # Gamma PnL sensitivity: if spot moves 1%, how many pts does delta change?
    # Δ(delta) per 1% spot move = gamma × spot × 0.01
    # Scaled to position: × lots × LOT_SIZE
    gamma_pnl_sens = g_now * spot * 0.01 * lots * LOT_SIZE

    return {
        "strike":         strike,
        "dte_now":        dte_now,
        "dte_entry":      dte_entry,
        "gamma_now":      g_now,
        "gamma_entry":    g_entry,
        "gamma_multiple": gamma_multiple,
        "moneyness_pts":  moneyness_pts,
        "gamma_pnl_sens": gamma_pnl_sens,
        "lots":           lots,
    }


def _roll_urgency(metrics: dict) -> tuple[str, str]:
    """Returns (label, color) for roll urgency."""
    dte     = metrics["dte_now"]
    mono    = metrics["moneyness_pts"]
    gmult   = metrics["gamma_multiple"]

    if dte <= 3:
        return "EMERGENCY ROLL", "red"
    if dte <= GAMMA_ROLL_DTE_RED and mono <= GAMMA_ROLL_MONO_RED:
        return "ROLL NOW", "red"
    if gmult >= GAMMA_ACCEL_ROLL and mono <= GAMMA_ROLL_MONO_RED * 1.5:
        return "ROLL NOW", "red"
    if dte <= GAMMA_ROLL_DTE_AMBER and mono <= GAMMA_ROLL_MONO_AMBER:
        return "WATCH", "amber"
    if gmult >= GAMMA_ACCEL_WATCH:
        return "WATCH", "amber"
    if mono <= GAMMA_ROLL_MONO_RED:
        return "ALERT", "amber"
    return "SAFE", "green"


# ── Next biweekly roll target ─────────────────────────────────────────────────

def _next_tuesdays() -> tuple[datetime.date, datetime.date, datetime.date]:
    """Return near, far, and next-far Tuesday dates."""
    today = datetime.date.today()
    days_ahead = (1 - today.weekday()) % 7  # Tuesday = weekday 1
    if days_ahead == 0:
        days_ahead = 7
    near = today + datetime.timedelta(days=days_ahead)
    far  = near  + datetime.timedelta(days=7)
    next_far = far + datetime.timedelta(days=7)
    return near, far, next_far


near_exp, far_exp, next_far_exp = _next_tuesdays()
near_dte = (near_exp - datetime.date.today()).days
far_dte  = (far_exp  - datetime.date.today()).days


def _roll_target_expiry(leg_dte: int) -> datetime.date:
    """For a biweekly position, suggest the roll-to expiry."""
    if near_dte >= 7:
        return far_exp
    return next_far_exp


def _roll_strike_suggestion(side: str) -> int:
    """Suggest a roll strike: binding level from signals, or ATR-based fallback."""
    if side == "CE":
        return binding_ce if binding_ce > 0 else int(round((spot * 1.05) / 50) * 50)
    return binding_pe if binding_pe > 0 else int(round((spot * 0.95) / 50) * 50)


# ── Collect all active short legs across positions ────────────────────────────

flagged_legs = []   # legs with WATCH or worse
all_short_legs = [] # all active, non-booked, Short legs

for pos in positions:
    pos_name = pos.get("name", f"Position {pos.get('id', '?')}")
    for leg_id, leg in pos.get("legs", {}).items():
        if not leg.get("active") or leg.get("booked"):
            continue
        if leg.get("direction") != "Short":
            continue
        m = _gamma_metrics(leg)
        if not m:
            continue
        urgency, color = _roll_urgency(m)
        row = {
            "pos_name": pos_name,
            "leg_id":   leg_id,
            "side":     leg.get("type", "?"),
            "strike":   m["strike"],
            "dte":      m["dte_now"],
            "expiry":   leg.get("expiry", ""),
            "gamma_now":      m["gamma_now"],
            "gamma_entry":    m["gamma_entry"],
            "gamma_multiple": m["gamma_multiple"],
            "moneyness_pts":  m["moneyness_pts"],
            "gamma_pnl_sens": m["gamma_pnl_sens"],
            "lots":           m["lots"],
            "urgency":        urgency,
            "color":          color,
            "roll_expiry":    _roll_target_expiry(m["dte_now"]),
            "roll_strike":    _roll_strike_suggestion(leg.get("type", "CE")),
        }
        all_short_legs.append(row)
        if urgency != "SAFE":
            flagged_legs.append(row)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 0: Biweekly cycle dashboard
# ══════════════════════════════════════════════════════════════════════════════

ui.section_header(
    "Biweekly Expiry Cycle",
    "Near = next Tuesday · Far = the Tuesday after · Roll target = next-far"
)

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    ui.metric_card("NEAR EXPIRY", near_exp.strftime("%-d %b"),
                   sub=f"DTE {near_dte}",
                   color="red" if near_dte <= 3 else "amber" if near_dte <= 5 else "default")
with c2:
    ui.metric_card("FAR EXPIRY", far_exp.strftime("%-d %b"),
                   sub=f"DTE {far_dte}",
                   color="amber" if far_dte <= 7 else "default")
with c3:
    ui.metric_card("NEXT-FAR (ROLL TO)", next_far_exp.strftime("%-d %b"),
                   sub=f"DTE {(next_far_exp - datetime.date.today()).days}",
                   color="green")
with c4:
    ui.metric_card("ATM IV", f"{atm_iv:.1f}%", sub="Used for gamma calc",
                   color="default")
with c5:
    ui.metric_card("NIFTY SPOT", f"{spot:,.0f}", sub="Live",
                   color="default")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Roll alert summary
# ══════════════════════════════════════════════════════════════════════════════

URGENCY_ORDER = {"EMERGENCY ROLL": 0, "ROLL NOW": 1, "WATCH": 2, "ALERT": 3, "SAFE": 4}
COLOR_MAP = {
    "red":   ("#dc2626", "#fef2f2"),
    "amber": ("#d97706", "#fffbeb"),
    "green": ("#16a34a", "#f0fdf4"),
}

if flagged_legs:
    n_roll = sum(1 for r in flagged_legs if r["color"] == "red")
    n_watch = sum(1 for r in flagged_legs if r["color"] == "amber")
    level = "danger" if n_roll > 0 else "warning"
    ui.alert_box(
        f"{'🔴' if n_roll else '⚡'} {n_roll} leg(s) require action · {n_watch} on watch",
        (f"ROLL NOW / EMERGENCY: {n_roll} short leg(s) breaching gamma thresholds. "
         f"WATCH: {n_watch} leg(s) approaching. "
         f"Scroll down for per-leg details and roll targets."),
        level=level
    )
elif all_short_legs:
    ui.alert_box(
        "✅ All short legs within safe gamma range",
        f"{len(all_short_legs)} active short leg(s) monitored · "
        f"No leg breaches DTE/moneyness/gamma-multiple thresholds.",
        level="success"
    )
else:
    st.info(
        "No active short legs found in Position Tracker. "
        "Enter positions on Page 14 to enable gamma monitoring."
    )
    st.stop()

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Gamma acceleration explainer
# ══════════════════════════════════════════════════════════════════════════════

with st.expander("How gamma acceleration works for biweekly positions", expanded=False):
    ui.simple_technical(
        "Gamma is the rate at which delta changes per point move in Nifty. "
        "For a short IC position, high gamma = your risk exposure doubles or triples for the same move. "
        "In a 14 DTE biweekly cycle, gamma roughly doubles every time DTE halves.",
        "Gamma ∝ 1/√T · N'(d1)/(S·σ)\n"
        "At 14 DTE: gamma baseline\n"
        "At 7 DTE: ~1.4× baseline (√2 factor)\n"
        "At 3 DTE: ~2.2× baseline\n"
        "At 1 DTE: ~3.7× baseline\n"
        "ATM strikes have the highest gamma. Roll when gamma multiple ≥ 2× AND spot is approaching."
    )
    st.markdown("")

    # Gamma curve table (illustrative, using current IV and ATM strike)
    atm_strike = int(round(spot / 50) * 50)
    iv_dec = atm_iv / 100.0
    rows = []
    for dte_val in [14, 10, 7, 5, 3, 2, 1]:
        T = max(dte_val, 0.25) / 365
        g = _bs_gamma(spot, atm_strike, T, iv_dec)
        baseline_T = max(GAMMA_BIWEEKLY_ENTRY_DTE, 0.25) / 365
        g_baseline = _bs_gamma(spot, atm_strike, baseline_T, iv_dec)
        mult = g / g_baseline if g_baseline > 0 else 1.0
        sens = g * spot * 0.01 * LOT_SIZE  # per lot, per 1% move
        zone = ("🔴 ROLL ZONE" if dte_val <= GAMMA_ROLL_DTE_RED else
                "🟡 WATCH" if dte_val <= GAMMA_ROLL_DTE_AMBER else
                "🟢 SAFE")
        rows.append({
            "DTE": dte_val,
            "ATM Gamma": f"{g:.6f}",
            "Multiple vs Entry (14 DTE)": f"{mult:.2f}×",
            "Δ-Delta per 1% Nifty move (1 lot)": f"{sens:.1f} pts",
            "Zone": zone,
        })
    import pandas as pd
    st.dataframe(pd.DataFrame(rows).set_index("DTE"), use_container_width=True)
    st.caption(f"Computed at current spot {spot:,.0f} · ATM strike {atm_strike:,} · IV {atm_iv:.1f}%")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Per-leg gamma detail
# ══════════════════════════════════════════════════════════════════════════════

ui.section_header(
    "Active Short Legs — Gamma Monitor",
    "Only SHORT legs shown · Long legs benefit from gamma (no roll needed)"
)

sorted_legs = sorted(all_short_legs, key=lambda r: URGENCY_ORDER[r["urgency"]])

for row in sorted_legs:
    fg, bg = COLOR_MAP[row["color"]]
    urgency_icon = {"EMERGENCY ROLL": "🚨", "ROLL NOW": "🔴", "WATCH": "🟡",
                    "ALERT": "⚡", "SAFE": "🟢"}.get(row["urgency"], "")

    header_html = (
        f"<div style='background:{bg};border-left:5px solid {fg};"
        f"border-radius:6px;padding:10px 14px;margin-bottom:4px;'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
        f"<div>"
        f"<span style='font-size:13px;font-weight:700;color:{fg};'>"
        f"{urgency_icon} {row['pos_name']} · {row['side']} {row['strike']:,} Short"
        f"</span>"
        f"<span style='font-size:11px;color:#64748b;margin-left:10px;'>"
        f"Expiry {row['expiry']} · DTE {row['dte']} · {row['lots']} lot(s)"
        f"</span>"
        f"</div>"
        f"<div style='font-size:14px;font-weight:800;color:{fg};'>{row['urgency']}</div>"
        f"</div>"
        f"</div>"
    )
    st.markdown(header_html, unsafe_allow_html=True)

    with st.expander("Gamma detail", expanded=(row["color"] == "red")):
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            ui.metric_card("DTE", str(row["dte"]),
                           sub="Days to expiry",
                           color="red" if row["dte"] <= GAMMA_ROLL_DTE_RED else
                                 "amber" if row["dte"] <= GAMMA_ROLL_DTE_AMBER else "default")
        with col2:
            ui.metric_card("MONEYNESS",
                           f"{row['moneyness_pts']:,.0f} pts",
                           sub=f"{'ITM ⚠' if row['moneyness_pts'] < 0 else 'OTM'} from {row['strike']:,}",
                           color="red" if row["moneyness_pts"] <= GAMMA_ROLL_MONO_RED else
                                 "amber" if row["moneyness_pts"] <= GAMMA_ROLL_MONO_AMBER else "default")
        with col3:
            ui.metric_card("GAMMA NOW",
                           f"{row['gamma_now']:.5f}",
                           sub=f"Entry: {row['gamma_entry']:.5f}",
                           color="default")
        with col4:
            ui.metric_card("GAMMA MULTIPLE",
                           f"{row['gamma_multiple']:.2f}×",
                           sub=f"vs entry ({GAMMA_BIWEEKLY_ENTRY_DTE} DTE baseline)",
                           color="red" if row["gamma_multiple"] >= GAMMA_ACCEL_ROLL else
                                 "amber" if row["gamma_multiple"] >= GAMMA_ACCEL_WATCH else "green")
        with col5:
            ui.metric_card("Δ-DELTA / 1% MOVE",
                           f"{row['gamma_pnl_sens']:.1f} pts",
                           sub=f"{row['lots']} lot(s) × {LOT_SIZE}",
                           color="red" if row["gamma_pnl_sens"] > 50 else
                                 "amber" if row["gamma_pnl_sens"] > 25 else "green")

        # Gamma progress bar
        g_pct = min(100.0, (row["gamma_multiple"] / GAMMA_ACCEL_ROLL) * 100)
        bar_col = fg
        st.markdown(
            f"<div style='margin-top:8px;'>"
            f"<div style='font-size:10px;color:#64748b;margin-bottom:3px;'>"
            f"Gamma acceleration vs entry — {g_pct:.0f}% of roll threshold ({GAMMA_ACCEL_ROLL:.1f}×)"
            f"</div>"
            f"<div style='height:8px;background:#e2e8f0;border-radius:4px;overflow:hidden;'>"
            f"<div style='height:100%;width:{g_pct:.0f}%;background:{bar_col};"
            f"border-radius:4px;transition:width .4s;'></div>"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True
        )

        # Roll suggestion (shown for non-safe legs)
        if row["color"] != "green":
            roll_exp  = row["roll_expiry"]
            roll_str  = row["roll_strike"]
            roll_dte  = (roll_exp - datetime.date.today()).days

            st.markdown(
                f"<div style='background:#fffbeb;border:1px solid #fcd34d;"
                f"border-radius:6px;padding:10px 14px;margin-top:10px;'>"
                f"<div style='font-size:11px;font-weight:700;color:#92400e;"
                f"letter-spacing:.5px;margin-bottom:6px;'>DEFENSIVE ROLL TARGET</div>"
                f"<div style='display:flex;gap:32px;font-size:12px;color:#1e293b;'>"
                f"<div><span style='color:#64748b;'>Roll to expiry:</span> "
                f"<b>{roll_exp.strftime('%-d %b %Y')}</b> (DTE {roll_dte})</div>"
                f"<div><span style='color:#64748b;'>Suggested strike:</span> "
                f"<b>{roll_str:,}</b> "
                f"({'binding CE' if row['side'] == 'CE' else 'binding PE'} from signals)</div>"
                f"<div><span style='color:#64748b;'>New DTE after roll:</span> "
                f"<b>{roll_dte}</b> — resets gamma to ~baseline</div>"
                f"</div>"
                f"<div style='font-size:10px;color:#92400e;margin-top:6px;'>"
                f"Close current {row['side']} {row['strike']:,} · "
                f"Open new {row['side']} {roll_str:,} @ {roll_exp.strftime('%-d %b')} · "
                f"Target net credit or neutral debit"
                f"</div>"
                f"</div>",
                unsafe_allow_html=True
            )

        st.markdown("")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Roll summary table (all short legs at a glance)
# ══════════════════════════════════════════════════════════════════════════════

ui.section_header("All Short Legs — Quick Reference", "Sorted by urgency")

import pandas as pd

table_rows = []
for row in sorted_legs:
    urgency_icon = {"EMERGENCY ROLL": "🚨", "ROLL NOW": "🔴", "WATCH": "🟡",
                    "ALERT": "⚡", "SAFE": "🟢"}.get(row["urgency"], "")
    table_rows.append({
        "Position":     row["pos_name"],
        "Leg":          f"{row['side']} {row['strike']:,}",
        "Expiry":       row["expiry"],
        "DTE":          row["dte"],
        "Moneyness":    f"{row['moneyness_pts']:,.0f} pts",
        "Gamma Now":    f"{row['gamma_now']:.5f}",
        "γ Multiple":   f"{row['gamma_multiple']:.2f}×",
        "Δδ/1% Nifty":  f"{row['gamma_pnl_sens']:.1f}",
        "Status":       f"{urgency_icon} {row['urgency']}",
        "Roll Expiry":  row["roll_expiry"].strftime("%-d %b"),
        "Roll Strike":  f"{row['roll_strike']:,}",
    })

if table_rows:
    df_table = pd.DataFrame(table_rows)
    st.dataframe(df_table, use_container_width=True, hide_index=True)
else:
    st.info("No active short legs to display.")

st.divider()

# ── Footer note ───────────────────────────────────────────────────────────────
st.caption(
    f"Gamma computed via Black-Scholes · ATM IV used: {atm_iv:.1f}% · "
    f"Spot: {spot:,.0f} · "
    f"Roll triggers: DTE ≤ {GAMMA_ROLL_DTE_RED} + mono ≤ {GAMMA_ROLL_MONO_RED} pts, "
    f"OR DTE ≤ 3, OR γ ≥ {GAMMA_ACCEL_ROLL:.1f}× entry · "
    f"Long legs excluded (gamma helps longs) · "
    f"Page auto-refreshes on manual refresh from header button."
)
