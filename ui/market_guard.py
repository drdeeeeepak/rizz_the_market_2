# ui/market_guard.py
# Shared market-hours utility for all pages.
# Usage:
#   from ui.market_guard import market_closed_banner, is_market_open
#
#   if not is_market_open():
#       market_closed_banner()
#       st.stop()

import datetime
import streamlit as st

try:
    import pytz
    _HAS_PYTZ = True
except ImportError:
    _HAS_PYTZ = False


def is_market_open() -> bool:
    """Return True if NSE is currently in session (Mon–Fri, 9:15–15:30 IST)."""
    if not _HAS_PYTZ:
        return True  # can't determine — let it try
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.datetime.now(ist)
    if now.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    open_  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    close_ = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return open_ <= now <= close_


def _next_open_label() -> str:
    if not _HAS_PYTZ:
        return "next trading session"
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.datetime.now(ist)
    dow = now.weekday()   # 0=Mon … 6=Sun
    after_close = now.hour > 15 or (now.hour == 15 and now.minute >= 30)
    if dow < 4:
        return ("tomorrow" if after_close else "today") + " 9:15 AM IST"
    return "Monday 9:15 AM IST"


def market_closed_banner(extra_note: str = "") -> None:
    """Render a friendly 'market is closed' message. Call before st.stop()."""
    note_html = (
        f"<p style='color:#64748b;font-size:13px;margin-top:8px;'>{extra_note}</p>"
        if extra_note else ""
    )
    st.markdown(
        "<div style='text-align:center;padding:60px 20px;'>"
        "<div style='font-size:64px;'>🌙</div>"
        "<h2 style='color:#1e293b;margin:16px 0 8px;'>Market is Closed</h2>"
        "<p style='color:#5a6b8a;font-size:15px;margin:0 0 4px;'>"
        "NSE trading hours: <b>Mon–Fri 9:15 AM – 3:30 PM IST</b></p>"
        f"<p style='color:#94a3b8;font-size:13px;'>"
        f"Next session opens: <b>{_next_open_label()}</b></p>"
        f"{note_html}"
        "<hr style='border:none;border-top:1px solid #e2e8f0;margin:24px auto;width:280px;'>"
        "<p style='color:#94a3b8;font-size:12px;'>"
        "Live data (Options Chain, OI, VIX, Spot) is only available during market hours.</p>"
        "</div>",
        unsafe_allow_html=True,
    )


def require_live_data(spot: float, label: str = "live market data") -> None:
    """
    Call after fetching spot. If spot == 0 and market is closed,
    show the banner and stop. If spot == 0 but market is open,
    show a token-error message and stop.
    """
    if spot > 0:
        return  # all good
    if not is_market_open():
        market_closed_banner()
    else:
        st.error(
            f"⚠️ Could not fetch {label} (spot = 0). "
            "Market is open but Kite returned no data — "
            "your access token may have expired."
        )
        st.info("Use the **Logout** button in the sidebar to re-authenticate.")
    st.stop()
