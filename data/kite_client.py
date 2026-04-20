# data/kite_client.py
# Kite Connect authentication — fully automatic token management.
#
# Streamlit secrets only ever need:
#   KITE_API_KEY    = "..."
#   KITE_API_SECRET = "..."
#   GH_PAT          = "..."   ← needed to push token to GitHub Actions
#   GITHUB_REPO     = "owner/repo-name"  ← your GitHub repo
#
# Token lifecycle (fully automatic — zero manual steps):
#   1. First load of the day → no valid token → show Login button
#   2. You click Login (on any device/browser) → Zerodha auth → redirected back
#   3. request_token exchanged for access_token via generate_session()
#   4. Token saved to access_token.txt with today's IST date
#   5. Token ALSO pushed to GitHub repo file via API → GitHub Actions can read it
#   6. All subsequent page loads → read access_token.txt → validate → serve
#   7. At midnight IST → Zerodha invalidates token → next morning step 1 again
#
# GitHub Actions reads access_token.txt from repo — no separate secret needed.

import os
import json
import logging
import threading
from datetime import datetime
from pathlib import Path

import pytz
import streamlit as st

log = logging.getLogger(__name__)

TOKEN_FILE = Path("access_token.txt")
IST        = pytz.timezone("Asia/Kolkata")


# ─── Secrets ──────────────────────────────────────────────────────────────────

def _get_secret(key: str) -> str | None:
    try:
        val = st.secrets.get(key)
        if val and str(val) not in ("", "your_api_key_here", "your_api_secret_here",
                                    "your_gh_pat_here", "owner/your-repo-name"):
            return str(val)
    except Exception:
        pass
    return os.environ.get(key)


def _api_key() -> str:
    k = _get_secret("KITE_API_KEY")
    if not k:
        st.error("🔑 **KITE_API_KEY not set.** Add it to Streamlit Cloud → Settings → Secrets.")
        st.stop()
    return k


def _api_secret() -> str:
    s = _get_secret("KITE_API_SECRET")
    if not s:
        st.error("🔑 **KITE_API_SECRET not set.** Add it to Streamlit Cloud → Settings → Secrets.")
        st.stop()
    return s


# ─── Date helper ──────────────────────────────────────────────────────────────

def _today_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


# ─── Local token file ─────────────────────────────────────────────────────────

def _save_token_local(access_token: str) -> None:
    """Save token to access_token.txt with today's IST date."""
    try:
        payload = {"token": access_token.strip(), "date": _today_ist()}
        TOKEN_FILE.write_text(json.dumps(payload))
        log.info("Token saved locally → %s", TOKEN_FILE)
    except Exception as e:
        log.warning("Could not save token locally: %s", e)


def _load_token() -> str | None:
    """
    Read token from access_token.txt.
    Returns token string if date = today IST, else None (expired).
    """
    if not TOKEN_FILE.exists():
        return None
    try:
        raw = TOKEN_FILE.read_text().strip()
        if not raw:
            return None
        payload = json.loads(raw)
        if payload.get("date") != _today_ist():
            log.info("Token date %s ≠ today %s — expired", payload.get("date"), _today_ist())
            TOKEN_FILE.unlink(missing_ok=True)
            return None
        return payload.get("token")
    except Exception as e:
        log.warning("Token file unreadable: %s", e)
        TOKEN_FILE.unlink(missing_ok=True)
        return None


def _clear_token() -> None:
    try:
        TOKEN_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _validate_token(kite, token: str) -> bool:
    """Validate token by calling profile() — returns True if still valid."""
    try:
        kite.set_access_token(token)
        kite.profile()
        return True
    except Exception:
        return False


# ─── GitHub token push ────────────────────────────────────────────────────────

def _push_token_to_github(access_token: str) -> None:
    """
    Push access_token.txt to GitHub repo so GitHub Actions can read it.
    Runs in a background thread so login doesn't feel slow.
    Requires GH_PAT and GITHUB_REPO in Streamlit secrets.
    """
    gh_pat  = _get_secret("GH_PAT")
    gh_repo = _get_secret("GITHUB_REPO")   # e.g. "drdeeeeepak/rizz_the_market"

    if not gh_pat or not gh_repo:
        log.info("GH_PAT or GITHUB_REPO not set — skipping GitHub push (Actions will use yesterday's token if any)")
        return

    def _push():
        try:
            import requests, base64

            payload  = {"token": access_token.strip(), "date": _today_ist()}
            content  = json.dumps(payload).encode()
            b64      = base64.b64encode(content).decode()

            url      = f"https://api.github.com/repos/{gh_repo}/contents/access_token.txt"
            headers  = {"Authorization": f"token {gh_pat}",
                        "Accept":        "application/vnd.github+json"}

            # Get current SHA (needed for update vs create)
            resp = requests.get(url, headers=headers, timeout=10)
            sha  = resp.json().get("sha") if resp.status_code == 200 else None

            body = {"message": f"Token refresh {_today_ist()}",
                    "content": b64,
                    "branch":  "main"}
            if sha:
                body["sha"] = sha

            put = requests.put(url, headers=headers, json=body, timeout=15)
            if put.status_code in (200, 201):
                log.info("✅ Token pushed to GitHub repo successfully")
            else:
                log.warning("GitHub push returned %s: %s", put.status_code, put.text[:200])

        except Exception as e:
            log.warning("GitHub token push failed (non-critical): %s", e)

    # Run in background — don't block the Streamlit login redirect
    threading.Thread(target=_push, daemon=True).start()


# ─── Full token save (local + GitHub) ────────────────────────────────────────

def _save_token(access_token: str) -> None:
    """Save token locally AND push to GitHub repo."""
    _save_token_local(access_token)
    _push_token_to_github(access_token)


# ─── Main public function ────────────────────────────────────────────────────

def get_kite():
    """
    Returns authenticated KiteConnect instance.

    Flow:
      ① Session cache hit → return immediately
      ② Read access_token.txt → check date = today IST → validate via profile()
      ③ URL has request_token (OAuth callback) → generate_session → save → push to GitHub → cache
      ④ Nothing works → show Login button → st.stop()
    """
    from kiteconnect import KiteConnect

    # ① Cached session
    if st.session_state.get("kite_authenticated") and "kite" in st.session_state:
        return st.session_state["kite"]

    api_key    = _api_key()
    api_secret = _api_secret()

    if "kite" not in st.session_state:
        st.session_state["kite"] = KiteConnect(api_key=api_key)
    kite = st.session_state["kite"]

    # ③ OAuth callback — Zerodha redirected back with request_token
    params = st.query_params
    if "request_token" in params:
        request_token = params["request_token"]
        try:
            session_data  = kite.generate_session(request_token, api_secret=api_secret)
            access_token  = session_data["access_token"]
            kite.set_access_token(access_token)
            _save_token(access_token)          # saves locally + pushes to GitHub in background
            st.session_state["kite_authenticated"] = True
            st.query_params.clear()
            log.info("OAuth complete — token saved and GitHub push initiated")
            st.rerun()
        except Exception as e:
            st.error(f"❌ Kite login failed: {e}")
            _clear_token()
            st.stop()

    # ② Try saved token from file
    saved_token = _load_token()
    if saved_token:
        if _validate_token(kite, saved_token):
            st.session_state["kite_authenticated"] = True
            log.info("Valid token loaded from access_token.txt")
            return kite
        else:
            log.warning("Token date matched today but profile() failed — re-login needed")
            _clear_token()

    # ④ No valid token — show login UI
    st.session_state.pop("kite_authenticated", None)
    _clear_token()
    _show_login_ui(kite)
    st.stop()


# ─── Login UI ─────────────────────────────────────────────────────────────────

def _show_login_ui(kite) -> None:
    st.markdown("""
    <div style='text-align:center;padding:80px 20px 24px;'>
      <div style='font-size:52px;'>📊</div>
      <h1 style='margin:12px 0 6px;color:#0f2140;'>premiumdecay</h1>
      <p style='color:#5a6b8a;font-size:14px;margin-bottom:8px;'>Nifty 50 Options Dashboard</p>
      <p style='color:#94a3b8;font-size:12px;margin-bottom:32px;'>
        Login once per day — token saves automatically until midnight IST.<br>
        Works from any device: mobile, PC, tablet.
      </p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.link_button("🔑 Login with Kite (Zerodha)", kite.login_url(),
                        use_container_width=True, type="primary")
        st.markdown("""
        <p style='text-align:center;color:#94a3b8;font-size:11px;margin-top:14px;'>
        After login, your token is automatically saved to GitHub<br>
        so tonight's EOD compute runs without any manual steps.
        </p>
        """, unsafe_allow_html=True)

    st.divider()
    with st.expander("ℹ️ Setup — Streamlit Secrets required"):
        st.code("""
# Streamlit Cloud → your app → Settings → Secrets

KITE_API_KEY    = "your_kite_api_key"
KITE_API_SECRET = "your_kite_api_secret"
GH_PAT          = "your_github_personal_access_token"
GITHUB_REPO     = "yourusername/rizz_the_market"
        """, language="toml")
        st.markdown("""
**GH_PAT** needs: `repo` → `Contents: Read and Write` permission.

After login, the token is pushed to your GitHub repo automatically.
GitHub Actions EOD job reads it from there — no manual steps ever.
        """)


# ─── GitHub Actions variant ──────────────────────────────────────────────────

def get_kite_action():
    """
    For GitHub Actions scripts — no browser, no Streamlit.
    Reads access_token.txt which was committed when you logged in via dashboard.
    """
    from kiteconnect import KiteConnect

    api_key = os.environ.get("KITE_API_KEY") or _get_secret("KITE_API_KEY")
    if not api_key:
        raise RuntimeError("KITE_API_KEY not set in GitHub Actions secrets")

    kite  = KiteConnect(api_key=api_key)
    token = _load_token()

    if not token:
        raise RuntimeError(
            "access_token.txt missing or expired (date ≠ today IST).\n"
            "Fix: log in via the Streamlit dashboard before 3:35 PM IST.\n"
            "The dashboard automatically pushes the token to this repo."
        )

    kite.set_access_token(token)
    log.info("GitHub Actions: token loaded from access_token.txt")
    return kite


# ─── Logout ──────────────────────────────────────────────────────────────────

def logout() -> None:
    _clear_token()
    st.session_state.pop("kite", None)
    st.session_state.pop("kite_authenticated", None)
    st.rerun()
