# pages/15_SuperTrend_MTF.py — premiumdecay Page 15
# SuperTrend MTF (21,2) · Six scored TFs + 5m display-only
# Moat stack · Safe distance · Trajectory
# 27 Apr 2026

import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import plotly.graph_objects as go
import ui.components as ui
from page_utils import bootstrap_signals, show_page_header

st.set_page_config(page_title="P15 · SuperTrend MTF", layout="wide")
st_autorefresh(interval=60_000, key="p15")

st.title("Page 15 — SuperTrend MTF")
st.caption("SuperTrend (21,2) · Daily / 4H / 2H / 1H / 30m / 15m · 5m display-only · % CMP measuring unit")

sig, spot, signals_ts = bootstrap_signals()
show_page_header(spot, signals_ts)
if not sig:
    st.warning("⚠️ No signal data available. EOD job may not have run yet.")
    st.stop()

# ── Pull ST data from sig ────────────────────────────────────────────────────
put_stack      = sig.get("st_put_stack",  {})
call_stack     = sig.get("st_call_stack", {})
put_dist       = sig.get("st_put_dist",   {})
call_dist      = sig.get("st_call_dist",  {})
tf_signals     = sig.get("st_tf_signals", {})
flip_tfs       = sig.get("st_flip_tfs",   [])
ic_shape       = sig.get("st_ic_shape",   "SYMMETRIC")
home_score     = sig.get("st_home_score", 0)
st_traj        = sig.get("st_structural_trajectory", {})
it_traj        = sig.get("st_intraday_trajectory",   {})
tf5m           = sig.get("st_tf_5m_display",   {})

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1 — TIER 1 STRUCTURAL BACKDROP (Dynamic)
# ═════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 1 — Tier 1 Structural Backdrop",
                  "Daily · 4H · 2H · Dynamic — updates with every candle close")

tier1_tfs = ["daily", "4h", "2h"]

def _direction_badge(tf_sig: dict) -> str:
    d   = tf_sig.get("direction", "UNKNOWN")
    fl  = tf_sig.get("flip", False)
    col = "#16a34a" if d == "BULL" else "#dc2626" if d == "BEAR" else "#94a3b8"
    badge = f"<span style='background:{col};color:white;padding:2px 8px;border-radius:8px;font-size:11px;font-weight:700;'>{d}</span>"
    if fl:
        badge += " <span style='background:#f59e0b;color:white;padding:2px 6px;border-radius:6px;font-size:10px;font-weight:700;'>⚡ FLIP</span>"
    return badge

# Determine overall Tier 1 alignment
t1_directions = [tf_signals.get(tf, {}).get("direction", "UNKNOWN") for tf in tier1_tfs]
t1_bull_count = t1_directions.count("BULL")
t1_bear_count = t1_directions.count("BEAR")

if t1_bull_count == 3:
    t1_regime = "STRONG BULL"; t1_col = "#16a34a"
elif t1_bull_count == 2:
    t1_regime = "MILD BULL";   t1_col = "#22c55e"
elif t1_bear_count == 3:
    t1_regime = "STRONG BEAR"; t1_col = "#dc2626"
elif t1_bear_count == 2:
    t1_regime = "MILD BEAR";   t1_col = "#f87171"
elif any(tf_signals.get(tf, {}).get("flip") for tf in tier1_tfs):
    t1_regime = "TRANSITION";  t1_col = "#f59e0b"
else:
    t1_regime = "MIXED";       t1_col = "#94a3b8"

st.markdown(
    f"<div style='background:{t1_col}18;border-left:4px solid {t1_col};"
    f"padding:10px 16px;border-radius:6px;margin-bottom:12px;'>"
    f"<span style='font-size:16px;font-weight:700;color:{t1_col};'>{t1_regime}</span>"
    f"<span style='font-size:12px;color:#64748b;margin-left:12px;'>"
    f"IC Shape Signal: <b>{ic_shape}</b></span></div>",
    unsafe_allow_html=True
)

cols = st.columns(3)
for i, tf_name in enumerate(tier1_tfs):
    tfs = tf_signals.get(tf_name, {})
    label = tf_name.upper()
    with cols[i]:
        st_price  = tfs.get("st_price", 0)
        dist_pts  = tfs.get("dist_pts", 0)
        dist_pct  = tfs.get("dist_pct", 0.0)
        depth     = tfs.get("depth", "—")
        direction = tfs.get("direction", "UNKNOWN")
        side      = tfs.get("side", "—")
        above     = tfs.get("above", False)
        flip      = tfs.get("flip", False)

        depth_col = {"DEEP":"#16a34a","COMFORTABLE":"#2563eb","ADEQUATE":"#d97706",
                     "THIN":"#ea580c","CRITICAL":"#dc2626"}.get(depth, "#94a3b8")

        badge_html = _direction_badge(tfs)
        pos_word   = "above" if above else "below"
        protects   = "CALL leg" if direction == "BEAR" else "PUT leg" if direction == "BULL" else "—"

        st.markdown(
            f"<div style='border:1px solid #e2e8f0;border-radius:8px;padding:12px;'>"
            f"<div style='font-size:13px;font-weight:700;color:#0f1724;margin-bottom:6px;'>{label} SuperTrend</div>"
            f"<div style='margin-bottom:4px;'>{badge_html}</div>"
            f"<div style='font-size:12px;color:#334155;margin-top:6px;'>"
            f"ST Line: <b>{st_price:,.0f}</b></div>"
            f"<div style='font-size:12px;color:#334155;'>"
            f"{dist_pts:,} pts {pos_word} spot &nbsp;·&nbsp; <b style='color:{depth_col};'>{dist_pct:.2f}% CMP</b></div>"
            f"<div style='font-size:11px;color:{depth_col};font-weight:700;margin-top:4px;'>{depth}</div>"
            f"<div style='font-size:11px;color:#64748b;'>Protects: {protects}</div>"
            f"</div>",
            unsafe_allow_html=True
        )

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2 — MOAT STACK — BOTH SIDES
# ═════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 2 — Moat Stack",
                  "PUT side and CALL side · Weighted by TF importance and depth · % CMP measuring unit")

DEPTH_COLOURS = {
    "DEEP":        "#16a34a",
    "COMFORTABLE": "#2563eb",
    "ADEQUATE":    "#d97706",
    "THIN":        "#ea580c",
    "CRITICAL":    "#dc2626",
    "UNKNOWN":     "#94a3b8",
}
BAND_COLOURS = {
    "FORTRESS": "#16a34a", "STRONG": "#2563eb",
    "ADEQUATE": "#d97706", "THIN": "#ea580c",
    "EXPOSED":  "#dc2626", "BREACHED": "#7f1d1d",
}

def _render_moat_table(stack: dict, side_label: str, side_color: str):
    walls    = stack.get("walls", [])
    clusters = stack.get("clusters", [])
    raw      = stack.get("raw_score", 0)
    norm     = stack.get("normalised", 0)
    band     = stack.get("band", "BREACHED")
    band_col = BAND_COLOURS.get(band, "#94a3b8")

    # Cluster pairs for bracket display
    cluster_pairs = set()
    for c in clusters:
        cluster_pairs.add(c[0]); cluster_pairs.add(c[1])

    st.markdown(
        f"<div style='background:{side_color}18;border-left:4px solid {side_color};"
        f"padding:8px 14px;border-radius:6px;margin-bottom:8px;'>"
        f"<span style='font-size:14px;font-weight:700;color:{side_color};'>{side_label}</span>"
        f"&nbsp;&nbsp;<span style='background:{band_col};color:white;padding:2px 8px;"
        f"border-radius:8px;font-size:11px;font-weight:700;'>{band}</span>"
        f"&nbsp;&nbsp;<span style='font-size:12px;color:#334155;'>"
        f"Score: <b>{norm:.1f}/100</b> (raw {raw:.1f}/180)</span>"
        f"</div>",
        unsafe_allow_html=True
    )

    if not walls:
        st.markdown(
            "<div style='background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;"
            "padding:10px;color:#dc2626;font-size:12px;font-weight:600;'>No structural walls on this side. "
            "This leg has no ST protection.</div>",
            unsafe_allow_html=True
        )
        return

    # Build table rows
    rows_html = ""
    cluster_pairs_found = set()
    for w in walls:
        tf      = w["tf"]
        dc      = DEPTH_COLOURS.get(w["depth"], "#94a3b8")
        flip    = "⚡ FLIP" if w.get("flip") else ""
        cluster = "┐" if tf in cluster_pairs and tf not in cluster_pairs_found else ""
        if tf in cluster_pairs:
            cluster_pairs_found.add(tf)

        rows_html += (
            f"<tr>"
            f"<td style='padding:5px 8px;font-weight:700;color:#0f1724;'>{tf.upper()}</td>"
            f"<td style='padding:5px 8px;font-family:monospace;'>{w['st_price']:,.0f}</td>"
            f"<td style='padding:5px 8px;'>{w['dist_pts']:,} pts</td>"
            f"<td style='padding:5px 8px;font-weight:700;color:{dc};'>{w['dist_pct']:.2f}%</td>"
            f"<td style='padding:5px 8px;color:{dc};font-weight:600;'>{w['depth']}</td>"
            f"<td style='padding:5px 8px;color:#64748b;'>{w['mult']:.1f}×</td>"
            f"<td style='padding:5px 8px;'>{w['weight']}</td>"
            f"<td style='padding:5px 8px;font-weight:700;'>{w['raw_score']:.1f}</td>"
            f"<td style='padding:5px 8px;color:#f59e0b;font-weight:700;'>{flip}</td>"
            f"<td style='padding:5px 8px;color:#94a3b8;font-size:11px;'>{cluster}</td>"
            f"</tr>"
        )

    # Cluster warning if any
    cluster_warn = ""
    if clusters:
        cpairs = ", ".join([f"{c[0].upper()}+{c[1].upper()}" for c in clusters])
        cluster_warn = (
            f"<div style='font-size:11px;color:#d97706;margin-top:4px;'>"
            f"⚠️ Cluster detected: {cpairs} — within 0.5% CMP, treated as single wall</div>"
        )

    st.markdown(
        f"<table style='width:100%;border-collapse:collapse;font-size:12px;'>"
        f"<thead><tr style='background:#f1f5f9;'>"
        f"<th style='padding:5px 8px;text-align:left;'>TF</th>"
        f"<th style='padding:5px 8px;text-align:left;'>ST Line</th>"
        f"<th style='padding:5px 8px;text-align:left;'>Distance</th>"
        f"<th style='padding:5px 8px;text-align:left;'>% CMP</th>"
        f"<th style='padding:5px 8px;text-align:left;'>Depth</th>"
        f"<th style='padding:5px 8px;text-align:left;'>Mult</th>"
        f"<th style='padding:5px 8px;text-align:left;'>Weight</th>"
        f"<th style='padding:5px 8px;text-align:left;'>Score</th>"
        f"<th style='padding:5px 8px;text-align:left;'></th>"
        f"<th style='padding:5px 8px;text-align:left;'></th>"
        f"</tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        f"</table>"
        f"{cluster_warn}",
        unsafe_allow_html=True
    )


col_put, col_call = st.columns(2)

with col_put:
    st.markdown("#### 🟢 PUT Side Moat Stack")
    st.caption("BULL TFs — lines below spot — protecting PE leg")
    _render_moat_table(put_stack, "PUT SIDE", "#16a34a")

with col_call:
    st.markdown("#### 🔴 CALL Side Moat Stack")
    st.caption("BEAR TFs — lines above spot — protecting CE leg")
    _render_moat_table(call_stack, "CALL SIDE", "#dc2626")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 3 — ST SAFE DISTANCE
# ═════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 3 — ST Safe Distance",
                  "Tier 1 walls only (Daily / 4H / 2H) · 1% buffer · 2.0%–2.5% output range")

pe_dist   = sig.get("st_lens_pe_dist",   0)
pe_pct    = sig.get("st_lens_pe_pct",    0.0)
pe_strike = sig.get("st_lens_pe_strike", 0)
ce_dist   = sig.get("st_lens_ce_dist",   0)
ce_pct    = sig.get("st_lens_ce_pct",    0.0)
ce_strike = sig.get("st_lens_ce_strike", 0)
pe_label  = sig.get("st_pe_label", "—")
ce_label  = sig.get("st_ce_label", "—")
pe_case   = sig.get("st_pe_case", "NO_WALL")
ce_case   = sig.get("st_ce_case", "NO_WALL")

CASE_COL = {
    "WALL_USED":       "#16a34a",
    "WALL_TOO_CLOSE":  "#d97706",
    "WALL_DEEP":       "#2563eb",
    "NO_WALL":         "#94a3b8",
}

c1, c2, c3, col_div, c4, c5, c6 = st.columns([2, 1, 1, 0.1, 2, 1, 1])
with c1:
    pc = CASE_COL.get(pe_case, "#94a3b8")
    st.markdown(
        f"<div style='border-left:4px solid {pc};padding:8px 12px;border-radius:4px;"
        f"background:{pc}12;'>"
        f"<div style='font-size:11px;color:#64748b;font-weight:600;'>PUT SIDE — BASIS</div>"
        f"<div style='font-size:13px;color:{pc};font-weight:700;margin-top:2px;'>{pe_label}</div>"
        f"</div>", unsafe_allow_html=True
    )
with c2:
    ui.metric_card("PE Dist", f"{pe_dist:,} pts", sub=f"{pe_pct:.2f}% CMP", color="green")
with c3:
    ui.metric_card("PE Strike", f"~{pe_strike:,}", color="green")

with c4:
    cc = CASE_COL.get(ce_case, "#94a3b8")
    st.markdown(
        f"<div style='border-left:4px solid {cc};padding:8px 12px;border-radius:4px;"
        f"background:{cc}12;'>"
        f"<div style='font-size:11px;color:#64748b;font-weight:600;'>CALL SIDE — BASIS</div>"
        f"<div style='font-size:13px;color:{cc};font-weight:700;margin-top:2px;'>{ce_label}</div>"
        f"</div>", unsafe_allow_html=True
    )
with c5:
    ui.metric_card("CE Dist", f"{ce_dist:,} pts", sub=f"{ce_pct:.2f}% CMP", color="red")
with c6:
    ui.metric_card("CE Strike", f"~{ce_strike:,}", color="red")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 4 — ST STRIKES
# ═════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 4 — ST Strikes",
                  "ST-derived strikes only · Participates in Home lens table MAX")

s4c1, s4c2 = st.columns(2)
with s4c1:
    st.markdown(
        f"<div style='border:2px solid #16a34a;border-radius:10px;padding:16px;text-align:center;'>"
        f"<div style='font-size:12px;font-weight:600;color:#64748b;'>ST PE SHORT STRIKE</div>"
        f"<div style='font-size:28px;font-weight:800;color:#16a34a;margin:6px 0;'>~{pe_strike:,}</div>"
        f"<div style='font-size:12px;color:#334155;'>{pe_dist:,} pts below spot · {pe_pct:.2f}% OTM</div>"
        f"<div style='font-size:11px;color:#64748b;margin-top:4px;'>{pe_label}</div>"
        f"</div>", unsafe_allow_html=True
    )
with s4c2:
    st.markdown(
        f"<div style='border:2px solid #dc2626;border-radius:10px;padding:16px;text-align:center;'>"
        f"<div style='font-size:12px;font-weight:600;color:#64748b;'>ST CE SHORT STRIKE</div>"
        f"<div style='font-size:28px;font-weight:800;color:#dc2626;margin:6px 0;'>~{ce_strike:,}</div>"
        f"<div style='font-size:12px;color:#334155;'>{ce_dist:,} pts above spot · {ce_pct:.2f}% OTM</div>"
        f"<div style='font-size:11px;color:#64748b;margin-top:4px;'>{ce_label}</div>"
        f"</div>", unsafe_allow_html=True
    )

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 5 — TRAJECTORY
# ═════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 5 — Trajectory",
                  "Structural (Tier 1 EOD vs EOD) · Intraday (Tier 3 vs 9:15 AM)")

TRAJ_COL = {
    "STRENGTHENING":           "#16a34a",
    "IMPROVING":               "#22c55e",
    "STABLE":                  "#64748b",
    "WEAKENING":               "#ea580c",
    "DETERIORATING":           "#dc2626",
    "INTRADAY STRENGTHENING":  "#16a34a",
    "INTRADAY IMPROVING":      "#22c55e",
    "INTRADAY STABLE":         "#64748b",
    "INTRADAY WEAKENING":      "#ea580c",
    "INTRADAY DETERIORATING":  "#dc2626",
    "UNKNOWN":                 "#94a3b8",
}

def _traj_card(traj: dict, title: str):
    put_lbl  = traj.get("put_label",  "UNKNOWN")
    call_lbl = traj.get("call_label", "UNKNOWN")
    put_d    = traj.get("put_delta")
    call_d   = traj.get("call_delta")
    flip_ev  = traj.get("flip_event", False)
    flip_tfs = traj.get("flip_tfs",   [])
    pc       = TRAJ_COL.get(put_lbl,  "#94a3b8")
    cc       = TRAJ_COL.get(call_lbl, "#94a3b8")

    put_delta_str  = f"({put_d:+.1f} pts)"  if put_d  is not None else ""
    call_delta_str = f"({call_d:+.1f} pts)" if call_d is not None else ""
    flip_str = (f"<div style='font-size:11px;color:#f59e0b;margin-top:4px;'>"
                f"⚡ FLIP EVENT: {', '.join([t.upper() for t in flip_tfs])}</div>") if flip_ev else ""

    st.markdown(
        f"<div style='border:1px solid #e2e8f0;border-radius:8px;padding:12px;'>"
        f"<div style='font-size:13px;font-weight:700;color:#0f1724;margin-bottom:8px;'>{title}</div>"
        f"<div style='margin-bottom:4px;font-size:12px;'>"
        f"PUT: <span style='color:{pc};font-weight:700;'>{put_lbl}</span> {put_delta_str}</div>"
        f"<div style='font-size:12px;'>"
        f"CALL: <span style='color:{cc};font-weight:700;'>{call_lbl}</span> {call_delta_str}</div>"
        f"{flip_str}"
        f"</div>",
        unsafe_allow_html=True
    )


tc1, tc2 = st.columns(2)
with tc1:
    _traj_card(st_traj, "Structural Trajectory — Daily / 4H / 2H (EOD vs EOD)")
with tc2:
    _traj_card(it_traj, "Intraday Trajectory — 1H / 30m / 15m (vs 9:15 AM)")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 6 — INTRADAY ACTION PANEL (Tier 3)
# ═════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 6 — Intraday Action Panel",
                  "Tier 3: 1H / 30m / 15m · Plus 5m display-only")

tier3_tfs = ["1h", "30m", "15m"]
tier3_cols = st.columns(3)

for i, tf_name in enumerate(tier3_tfs):
    tfs = tf_signals.get(tf_name, {})
    with tier3_cols[i]:
        direction = tfs.get("direction", "UNKNOWN")
        st_price  = tfs.get("st_price", 0)
        dist_pct  = tfs.get("dist_pct", 0.0)
        depth     = tfs.get("depth", "—")
        side      = tfs.get("side", "—")
        flip      = tfs.get("flip", False)
        dc        = DEPTH_COLOURS.get(depth, "#94a3b8")
        dir_col   = "#16a34a" if direction == "BULL" else "#dc2626" if direction == "BEAR" else "#94a3b8"

        flip_html = ("<div style='background:#f59e0b;color:white;border-radius:6px;"
                     "padding:4px 8px;font-size:11px;font-weight:700;margin-top:6px;"
                     "display:inline-block;'>⚡ FLIP — Direction changed</div>") if flip else ""

        st.markdown(
            f"<div style='border:2px solid {dir_col};border-radius:8px;padding:12px;'>"
            f"<div style='font-size:14px;font-weight:800;color:#0f1724;'>{tf_name.upper()}</div>"
            f"<div style='font-size:18px;font-weight:700;color:{dir_col};margin:4px 0;'>{direction}</div>"
            f"<div style='font-size:12px;color:#334155;'>ST Line: {st_price:,.0f}</div>"
            f"<div style='font-size:12px;color:{dc};font-weight:700;'>{dist_pct:.2f}% CMP — {depth}</div>"
            f"<div style='font-size:11px;color:#64748b;'>Protects: {side} leg</div>"
            f"{flip_html}"
            f"</div>",
            unsafe_allow_html=True
        )

# 5m display panel
st.markdown("---")
st.markdown("**5m SuperTrend — Display Only · Zero decision weight**")
if tf5m and tf5m.get("direction", "UNKNOWN") != "UNKNOWN":
    dir5 = tf5m.get("direction", "—")
    dc5  = "#16a34a" if dir5 == "BULL" else "#dc2626"
    fl5  = "⚡ FLIP" if tf5m.get("flip") else ""
    st.markdown(
        f"<span style='background:#f1f5f9;border:1px solid #e2e8f0;border-radius:6px;"
        f"padding:4px 10px;font-size:12px;color:#334155;'>"
        f"5m ST: <b style='color:{dc5};'>{dir5}</b> · "
        f"Line: {tf5m.get('st_price',0):,.0f} · "
        f"{tf5m.get('dist_pct',0):.2f}% CMP · "
        f"{tf5m.get('depth','—')} "
        f"<span style='color:#f59e0b;'>{fl5}</span></span>",
        unsafe_allow_html=True
    )
else:
    st.caption("5m data not available.")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 7 — HOME SCORE CONTRIBUTION
# ═════════════════════════════════════════════════════════════════════════════
ui.section_header("Section 7 — Home Score Contribution",
                  "ST MTF contributes up to 9 pts to Home master score (rescaled, total max = 100)")

score_col = "#16a34a" if home_score >= 7 else "#d97706" if home_score >= 4 else "#dc2626"
ic_shape_colours = {
    "CE_SKEW":  "#2563eb", "PE_SKEW":  "#dc2626",
    "SYMMETRIC":"#16a34a", "SINGLE_CE":"#f59e0b", "SINGLE_PE":"#f59e0b",
}
ic_col = ic_shape_colours.get(ic_shape, "#64748b")

c1, c2, c3 = st.columns(3)
with c1:
    ui.metric_card("ST Home Score", f"{home_score} / 9",
                   sub="Rescaled from 10 (Option B)",
                   color=("green" if home_score>=7 else "amber" if home_score>=4 else "red"))
with c2:
    ui.metric_card("IC Shape Signal", ic_shape,
                   sub="Feeds _suggest_strategy on Home",
                   color=("green" if ic_shape=="SYMMETRIC" else
                          "blue" if "SKEW" in ic_shape else "amber"))
with c3:
    flip_count = len(flip_tfs)
    ui.metric_card("Flipped TFs", f"{flip_count} TF{'s' if flip_count!=1 else ''}",
                   sub="⚡ = direction changed this session",
                   color="amber" if flip_count > 0 else "green")

if flip_tfs:
    st.info(f"⚡ Flipped TFs this session: {', '.join([t.upper() for t in flip_tfs])}")
