# ui/components.py — v5 (22 April 2026)
# Shared Streamlit UI helpers used across all pages.
# Import as: import ui.components as ui
#
# ADDED: tooltip() — reusable ⓘ icon tooltip system
#   Mobile: tap to open overlay. Desktop: hover 400ms.
#   Three-line content template: what it means, good/bad, what to do.
#   One build, used everywhere.

import streamlit as st

# ── Tooltip system ─────────────────────────────────────────────────────────────
# Inject CSS/JS once per session using a flag in session_state
_TOOLTIP_CSS_JS = """
<style>
.pd-tip-wrap { position: relative; display: inline-flex; align-items: center; }
.pd-tip-icon {
  display: inline-flex; align-items: center; justify-content: center;
  width: 16px; height: 16px; border-radius: 50%;
  background: #dbeafe; color: #2563eb;
  font-size: 9px; font-weight: 700; cursor: pointer;
  margin-left: 4px; flex-shrink: 0;
  -webkit-tap-highlight-color: transparent;
  user-select: none;
}
.pd-tip-box {
  display: none; position: absolute; z-index: 9999;
  bottom: calc(100% + 6px); left: 50%; transform: translateX(-50%);
  background: #0f172a; color: #f1f5f9;
  border-radius: 8px; padding: 10px 12px;
  min-width: 220px; max-width: 300px;
  font-size: 11px; line-height: 1.5;
  box-shadow: 0 4px 16px rgba(0,0,0,0.3);
  pointer-events: none;
}
.pd-tip-box::after {
  content: ''; position: absolute; top: 100%; left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent; border-top-color: #0f172a;
}
.pd-tip-box .pd-tip-label {
  font-size: 9px; font-weight: 700; letter-spacing: .8px;
  text-transform: uppercase; color: #94a3b8; margin-bottom: 4px;
}
.pd-tip-box .pd-tip-line { margin-bottom: 3px; }
.pd-tip-box .pd-tip-line:last-child { margin-bottom: 0; color: #7dd3fc; }
/* Show on hover (desktop) */
@media (hover: hover) {
  .pd-tip-wrap:hover .pd-tip-box { display: block; }
}
/* Show on tap (mobile) — toggled by JS */
.pd-tip-box.pd-active { display: block; }
</style>
<script>
(function() {
  // Close any open tooltip when tapping elsewhere
  document.addEventListener('click', function(e) {
    if (!e.target.closest('.pd-tip-wrap')) {
      document.querySelectorAll('.pd-tip-box.pd-active')
        .forEach(function(el) { el.classList.remove('pd-active'); });
    }
  });
  // Toggle on tap of icon
  document.addEventListener('click', function(e) {
    var icon = e.target.closest('.pd-tip-icon');
    if (icon) {
      e.stopPropagation();
      var box = icon.parentElement.querySelector('.pd-tip-box');
      if (box) { box.classList.toggle('pd-active'); }
    }
  });
})();
</script>
"""


def _ensure_tooltip_injected():
    """Inject tooltip CSS/JS once per Streamlit session."""
    if not st.session_state.get("_pd_tooltip_injected"):
        st.components.v1.html(_TOOLTIP_CSS_JS, height=0, scrolling=False)
        st.session_state["_pd_tooltip_injected"] = True


def tooltip(term: str, line1: str, line2: str, line3: str) -> str:
    """
    Returns HTML string with ⓘ icon and tooltip popup.
    Locked three-line template:
      line1: What this term means in plain English
      line2: What a good vs bad value looks like for the IC
      line3: What to do differently based on this reading

    Usage: st.markdown(ui.tooltip("PCR", "Put/Call ratio...", "0.9-1.1 = ideal...", "Below 0.7 = widen CE..."), unsafe_allow_html=True)
    Or wrap around a label: f"{label} {ui.tooltip(...)}"
    """
    _ensure_tooltip_injected()
    # Escape any quotes in content
    def esc(s):
        return s.replace('"', '&quot;').replace("'", "&#39;")

    return (
        f"<span class='pd-tip-wrap'>"
        f"<span class='pd-tip-icon' title=''>ⓘ</span>"
        f"<div class='pd-tip-box'>"
        f"<div class='pd-tip-label'>{esc(term)}</div>"
        f"<div class='pd-tip-line'>{esc(line1)}</div>"
        f"<div class='pd-tip-line'>{esc(line2)}</div>"
        f"<div class='pd-tip-line'>{esc(line3)}</div>"
        f"</div>"
        f"</span>"
    )


def metric_card_with_tip(label: str, value: str, sub: str = "",
                          color: str = "default", border: str = "",
                          tip_term: str = "", tip1: str = "",
                          tip2: str = "", tip3: str = "") -> None:
    """
    metric_card with optional inline tooltip on the label.
    If tip_term is provided, adds ⓘ icon after label.
    """
    tip_html = tooltip(tip_term, tip1, tip2, tip3) if tip_term else ""
    named = {
        "green":      ("#16a34a", "#f0fdf4"),
        "red":        ("#dc2626", "#fef2f2"),
        "amber":      ("#d97706", "#fffbeb"),
        "blue":       ("#2563eb", "#eff6ff"),
        "default":    ("#e2e6ef", "#f8f9fb"),
        "anchor":     ("#d97706", "#fde68a"),
        "sold_ce":    ("#991b1b", "#fca5a5"),
        "sold_pe":    ("#166534", "#86efac"),
    }
    b_color, bg = named.get(color, named["default"])
    if border:
        b_color = border
        bg = "#f8f9fb"

    _sub_html = (f"<div style='font-size:13px;color:#334155;"
                 f"font-family:monospace;margin-top:3px;'>{sub}</div>") if sub else ""
    st.markdown(
        f"<div style='border-top:3px solid {b_color};background:{bg};"
        f"border-radius:6px;padding:12px 14px;min-height:72px;'>"
        f"<div style='font-size:12px;color:#334155;text-transform:uppercase;"
        f"letter-spacing:.7px;font-family:monospace;margin-bottom:4px;"
        f"font-weight:600;display:flex;align-items:center;'>{label}{tip_html}</div>"
        f"<div style='font-size:22px;font-weight:800;color:#0f1724;"
        f"line-height:1.1;letter-spacing:-0.3px;'>{value}</div>"
        f"{_sub_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


# ── Existing helpers (unchanged) ───────────────────────────────────────────────

def metric_card(label: str, value: str, sub: str = "",
                color: str = "default", border: str = "") -> None:
    named = {
        "green":      ("#16a34a", "#f0fdf4"),
        "red":        ("#dc2626", "#fef2f2"),
        "amber":      ("#d97706", "#fffbeb"),
        "blue":       ("#2563eb", "#eff6ff"),
        "default":    ("#e2e6ef", "#f8f9fb"),
        "anchor":     ("#d97706", "#fde68a"),
        "sold_ce":    ("#991b1b", "#fca5a5"),
        "sold_pe":    ("#166534", "#86efac"),
    }
    _thick = color in ("anchor", "sold_ce", "sold_pe")
    b_color, bg = named.get(color, named["default"])
    if border:
        b_color = border
        bg = "#f8f9fb"

    _sub_html2 = (f"<div style='font-size:13px;color:#334155;"
                  f"font-family:monospace;margin-top:3px;'>{sub}</div>") if sub else ""
    _bw = "5px" if _thick else "3px"
    st.markdown(
        f"<div style='border-top:{_bw} solid {b_color};background:{bg};"
        f"border-radius:6px;padding:12px 14px;min-height:72px;'>"
        f"<div style='font-size:12px;color:#334155;text-transform:uppercase;"
        f"letter-spacing:.7px;font-family:monospace;margin-bottom:4px;"
        f"font-weight:600;'>{label}</div>"
        f"<div style='font-size:22px;font-weight:800;color:#0f1724;"
        f"line-height:1.1;letter-spacing:-0.3px;'>{value}</div>"
        f"{_sub_html2}"
        f"</div>",
        unsafe_allow_html=True,
    )


def kill_switch_row(name: str, active: bool, detail: str = "") -> None:
    icon  = "🔴" if active else "✅"
    label = "ACTIVE" if active else "Clear"
    st.markdown(
        f"{icon} **{name}** — {label}"
        + (f" — {detail}" if detail and active else ""),
    )


def alert_box(title: str, body: str, level: str = "info") -> None:
    colors = {
        "danger":  ("#fef2f2", "#dc2626", "#fee2e2"),
        "warning": ("#fffbeb", "#d97706", "#fef3c7"),
        "info":    ("#eff6ff", "#2563eb", "#dbeafe"),
        "success": ("#f0fdf4", "#16a34a", "#dcfce7"),
    }
    bg, border, _ = colors.get(level, colors["info"])
    st.markdown(
        f"<div style='background:{bg};border:1px solid {border};"
        f"border-left:4px solid {border};border-radius:6px;"
        f"padding:9px 13px;margin-bottom:6px;'>"
        f"<div style='font-size:11px;font-weight:700;color:#0f1724;margin-bottom:3px;'>{title}</div>"
        f"<div style='font-size:10px;color:#5a6b8a;font-family:monospace;line-height:1.5;'>{body}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def expiry_banner(expiry, dte: int, role: str, mult: float) -> None:
    is_far  = "trade" in role.lower()
    bg      = "#f0fdf4" if is_far else "#eff6ff"
    border  = "#16a34a" if is_far else "#2563eb"
    label_c = "#16a34a" if is_far else "#2563eb"

    st.markdown(
        f"<div style='background:{bg};border:1.5px solid {border};"
        f"border-radius:7px;padding:10px 15px;display:flex;"
        f"justify-content:space-between;align-items:center;margin-bottom:8px;'>"
        f"<div>"
        f"<div style='font-size:9px;font-family:monospace;font-weight:700;"
        f"color:{label_c};letter-spacing:.8px;text-transform:uppercase;'>{role}</div>"
        f"<div style='font-size:14px;font-weight:700;color:{label_c};"
        f"font-family:monospace;'>{expiry} · {dte} DTE</div>"
        f"</div>"
        f"<div style='text-align:right;'>"
        f"<div style='font-size:9px;color:#5a6b8a;font-family:monospace;'>Panic mult</div>"
        f"<div style='font-size:16px;font-weight:700;color:{label_c};'>{mult:.1f}×</div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def net_score_chip(score: float) -> str:
    s = int(round(score))
    styles = {
         6: ("background:#14532d;color:#fff;",    f"+{s}"),
         5: ("background:#14532d;color:#fff;",    f"+{s}"),
         4: ("background:#166534;color:#fff;",    f"+{s}"),
         3: ("background:#16a34a;color:#fff;",    f"+{s}"),
         2: ("background:#4ade80;color:#14532d;", f"+{s}"),
         1: ("background:#bbf7d0;color:#14532d;", f"+{s}"),
         0: ("background:#f1f5f9;color:#5a6b8a;",  "0"),
        -1: ("background:#fee2e2;color:#7f1d1d;",  f"{s}"),
        -2: ("background:#fca5a5;color:#7f1d1d;",  f"{s}"),
        -3: ("background:#dc2626;color:#fff;",      f"{s}"),
        -4: ("background:#b91c1c;color:#fff;",      f"{s}"),
        -5: ("background:#7f1d1d;color:#fff;",      f"{s}"),
        -6: ("background:#7f1d1d;color:#fff;",      f"{s}"),
    }
    style, text = styles.get(max(-6, min(6, s)), ("background:#f1f5f9;color:#5a6b8a;", str(s)))
    return (
        f"<span style='{style}padding:2px 8px;border-radius:4px;"
        f"font-family:monospace;font-size:11px;font-weight:700;'>{text}</span>"
    )


def wall_dots(score: int, dominant_color: str = "#16a34a") -> str:
    filled = min(max(score, 0), 10)
    dots   = "".join([
        f"<div style='width:8px;height:8px;border-radius:2px;"
        f"background:{dominant_color if i < filled else '#e2e6ef'};"
        f"display:inline-block;margin-right:1px;'></div>"
        for i in range(5)
    ])
    return (
        f"<div style='display:flex;align-items:center;gap:2px;'>"
        f"{dots}"
        f"<span style='font-size:11px;font-weight:700;font-family:monospace;"
        f"margin-left:4px;color:{dominant_color};'>{score}</span>"
        f"</div>"
    )


def section_header(title: str, subtitle: str = "") -> None:
    _sub_hdr = (f"<div style='font-size:13px;color:#475569;"
                f"font-family:monospace;'>{subtitle}</div>") if subtitle else ""
    st.markdown(
        f"<div style='border-left:3px solid #2563eb;padding-left:10px;margin:16px 0 8px 0;'>"
        f"<div style='font-size:14px;font-weight:700;color:#0f1724;'>{title}</div>"
        f"{_sub_hdr}"
        f"</div>",
        unsafe_allow_html=True,
    )


def simple_technical(simple: str, technical: str) -> None:
    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown(
            f"<div style='background:#f0fdf4;border-left:3px solid #16a34a;"
            f"padding:10px 12px;border-radius:4px;'>"
            f"<div style='font-size:9px;font-weight:700;color:#16a34a;"
            f"text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;'>Plain English</div>"
            f"<div style='font-size:11px;color:#0f1724;line-height:1.5;'>{simple}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"<div style='background:#eff6ff;border-left:3px solid #2563eb;"
            f"padding:10px 12px;border-radius:4px;'>"
            f"<div style='font-size:9px;font-weight:700;color:#2563eb;"
            f"text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;'>Technical</div>"
            f"<div style='font-size:11px;color:#0f1724;font-family:monospace;line-height:1.5;'>{technical}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
