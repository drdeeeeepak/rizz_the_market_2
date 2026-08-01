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


def _validate_token(kite, token: str) -> str:
    """
    Check a token by calling profile(). Returns 'valid', 'invalid' or 'unknown'.

    The tri-state matters. This used to return a plain bool, and the caller DELETED
    the token whenever it was False — so a network blip, a timeout, or a Kite
    rate-limit (429; several pages autorefresh every 60s) destroyed a perfectly good
    token and forced a re-login. Only a genuine auth rejection should clear it;
    anything else is 'unknown' and the token is kept.
    """
    try:
        kite.set_access_token(token)
        kite.profile()
        return "valid"
    except Exception as e:
        blob = f"{type(e).__name__} {e}".lower()
        if any(s in blob for s in ("tokenexception", "invalid", "expired",
                                   "forbidden", "unauthor", "access_token")):
            return "invalid"
        log.warning("Token check inconclusive (%s) — keeping token", type(e).__name__)
        return "unknown"


# ─── GitHub token push ────────────────────────────────────────────────────────

_TOKEN_PATH = "access_token.txt"


def _gh_creds() -> tuple:
    return _get_secret("GH_PAT"), _get_secret("GITHUB_REPO")


def _push_token_to_github(access_token: str) -> tuple[bool, str]:
    """
    Push access_token.txt to the GitHub repo. Returns (ok, message).

    THIS IS WHAT KEEPS YOU LOGGED IN. Streamlit Cloud redeploys the app on every
    push to main — and this repo pushes to main seven times on a normal trading day
    (09:00, 11:00, 13:30, 15:15, 15:35, 16:05, 17:05 IST) plus any manual merge.
    Each redeploy is a brand-new container: st.session_state is gone and the local
    access_token.txt is gone with it. The repo copy is the only thing that survives,
    so if this push does not land you are dropped back to the login screen several
    times a day.

    It used to run in a daemon thread fired immediately before st.rerun(), so a
    failure was invisible AND the rerun could kill the thread before it finished.
    It is synchronous now and reports its result, because the whole day's data
    collection depends on it.
    """
    gh_pat, gh_repo = _gh_creds()
    if not gh_pat or not gh_repo:
        return False, ("GH_PAT / GITHUB_REPO not set in Streamlit secrets — the token "
                       "cannot be saved to the repo, so every redeploy will log you out.")
    try:
        import requests, base64

        payload = {"token": access_token.strip(), "date": _today_ist()}
        b64     = base64.b64encode(json.dumps(payload).encode()).decode()
        url     = f"https://api.github.com/repos/{gh_repo}/contents/{_TOKEN_PATH}"
        headers = {"Authorization": f"token {gh_pat}",
                   "Accept": "application/vnd.github+json"}

        resp = requests.get(url, headers=headers, timeout=10)
        sha  = resp.json().get("sha") if resp.status_code == 200 else None

        body = {"message": f"Token refresh {_today_ist()}", "content": b64, "branch": "main"}
        if sha:
            body["sha"] = sha

        put = requests.put(url, headers=headers, json=body, timeout=15)
        if put.status_code in (200, 201):
            log.info("Token pushed to GitHub repo")
            return True, "Token saved to the repo — you will stay logged in across redeploys."
        return False, f"GitHub returned {put.status_code}: {put.text[:160]}"
    except Exception as e:
        return False, f"GitHub token push failed: {e}"


"""
─── WHY THE TOKEN NEEDS THREE HOMES ──────────────────────────────────────────

Zerodha invalidates the access token at midnight IST, so ONE login per day is
unavoidable — that part is Kite's rule and no code can change it. Being asked
again at 11am is not: that is this app losing a token it already had.

It loses it because Streamlit Cloud rebuilds the container on every push to the
tracked branch, and this repo pushes to main about seven times on a trading day
(09:00, 11:00, 13:30, 15:15, 15:35, 16:05, 17:05 IST). A rebuild wipes
st.session_state and the container filesystem together.

So the token is kept in three places, each covering what the others cannot:

  1. st.session_state   — fastest, but dies on rebuild AND on browser refresh.
  2. BROWSER            — survives every rebuild, needs no configuration at all.
                          This is what gives you one login for the whole day.
  3. GitHub repo        — the only copy a GitHub Action can read. Optional, and
                          the ONLY thing that makes the 3:35 PM EOD job work.
                          Needs GH_PAT because writing to your repo requires a
                          credential only you can issue.

Browser storage covers YOUR logins completely on its own. The repo copy is a
separate problem: an Action runs on GitHub's machines with no access to your
browser, so it can only read a token that was written somewhere it can reach.
"""

_BROWSER_KEY = "premiumdecay_kite_token"


def _browser_store(access_token: str) -> None:
    """
    Save the token in the browser's localStorage.

    Survives container rebuilds, app restarts, tab closes and laptop reboots —
    everything except clearing site data or the token expiring at midnight IST.
    Needs no secrets and no setup.
    """
    try:
        import streamlit.components.v1 as components
        payload = json.dumps({"token": access_token.strip(), "date": _today_ist()})
        components.html(
            f"""<script>
              try {{ window.parent.localStorage.setItem({json.dumps(_BROWSER_KEY)},
                                                        {json.dumps(payload)}); }}
              catch (e) {{ }}
            </script>""",
            height=0,
        )
    except Exception as e:
        log.warning("Browser token store failed: %s", e)


def _browser_restore() -> None:
    """
    Ask the browser for a stored token and reload with it.

    Streamlit runs on the server and cannot read localStorage directly, so the
    page hands the value back through a query parameter and we strip it from the
    URL immediately. The reload happens once per rebuild, not per page view: the
    token is written to the container's own file on arrival, so every later load
    reads it locally without touching this path.
    """
    try:
        import streamlit.components.v1 as components
        components.html(
            f"""<script>
              try {{
                const raw = window.parent.localStorage.getItem({json.dumps(_BROWSER_KEY)});
                if (raw) {{
                  const d = JSON.parse(raw);
                  const u = new URL(window.parent.location.href);
                  // Only bounce when we have not already tried this reload, so a
                  // stale or rejected token cannot cause a refresh loop.
                  if (d && d.token && !u.searchParams.has('kite_restore')) {{
                    u.searchParams.set('kite_restore', d.token);
                    u.searchParams.set('kite_restore_date', d.date || '');
                    window.parent.location.replace(u.toString());
                  }}
                }}
              }} catch (e) {{ }}
            </script>""",
            height=0,
        )
    except Exception as e:
        log.warning("Browser token restore failed: %s", e)


def _browser_clear() -> None:
    """Drop the browser copy — used when Kite genuinely rejects the token."""
    try:
        import streamlit.components.v1 as components
        components.html(
            f"""<script>
              try {{ window.parent.localStorage.removeItem({json.dumps(_BROWSER_KEY)}); }}
              catch (e) {{ }}
            </script>""",
            height=0,
        )
    except Exception:
        pass


def _token_from_query() -> str | None:
    """Pick up a token handed back by _browser_restore, then clean the URL."""
    try:
        params = st.query_params
        tok = params.get("kite_restore")
        if not tok:
            return None
        d = params.get("kite_restore_date")
        # Reject anything not stamped today — the browser copy outlives the token.
        if d and d != _today_ist():
            log.info("Browser token is from %s, not today — ignoring", d)
            _browser_clear()
            try:
                st.query_params.clear()
            except Exception:
                pass
            return None
        return tok
    except Exception:
        return None


def session_health() -> dict:
    """
    Can this session survive a redeploy, and is today's data collection safe?

    Streamlit Cloud rebuilds the container on every push to main — seven scheduled
    pushes on a normal trading day, plus any merge — and the ONLY copy of the token
    that survives is the one in the repo. If that copy is missing you get bounced to
    the login screen repeatedly, and the 3:35 PM job cannot collect. That used to
    fail silently, so this reports it plainly.
    """
    gh_pat, gh_repo = _gh_creds()
    out = {
        "today":          _today_ist(),
        "local_token":    False,
        "repo_token":     False,
        "repo_token_date": None,
        "gh_configured":  bool(gh_pat and gh_repo),
        "repo":           gh_repo or "—",
        "error":          None,
    }

    try:
        if TOKEN_FILE.exists():
            payload = json.loads(TOKEN_FILE.read_text())
            out["local_token"] = payload.get("date") == out["today"]
    except Exception:
        pass

    if out["gh_configured"]:
        try:
            import requests, base64
            url = f"https://api.github.com/repos/{gh_repo}/contents/{_TOKEN_PATH}"
            r = requests.get(url, headers={"Authorization": f"token {gh_pat}",
                                           "Accept": "application/vnd.github+json"},
                             timeout=10)
            if r.status_code == 200:
                payload = json.loads(base64.b64decode(r.json().get("content", "")).decode())
                out["repo_token_date"] = payload.get("date")
                out["repo_token"] = payload.get("date") == out["today"]
            elif r.status_code == 404:
                out["error"] = "access_token.txt has never been written to the repo"
            else:
                out["error"] = f"GitHub returned {r.status_code}"
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
    else:
        out["error"] = "GH_PAT / GITHUB_REPO not set in Streamlit secrets"

    # Survives a redeploy only if the repo copy is present and current.
    out["survives_redeploy"] = bool(out["repo_token"])
    return out


def _load_token_from_github() -> str | None:
    """
    Read today's token back from the repo.

    The missing half of the design. The token was being PUSHED to GitHub but nothing
    ever read it back, and access_token.txt is not tracked in git — so a redeployed
    container started with no token file at all and went straight to the login
    screen, even though a valid token for today existed in the repo.
    """
    gh_pat, gh_repo = _gh_creds()
    if not gh_pat or not gh_repo:
        return None
    try:
        import requests, base64

        url     = f"https://api.github.com/repos/{gh_repo}/contents/{_TOKEN_PATH}"
        headers = {"Authorization": f"token {gh_pat}",
                   "Accept": "application/vnd.github+json"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        raw     = base64.b64decode(resp.json().get("content", "")).decode()
        payload = json.loads(raw)
        if payload.get("date") != _today_ist():
            log.info("Repo token is from %s, not today — ignoring", payload.get("date"))
            return None
        token = payload.get("token")
        if token:
            _save_token_local(token)      # cache locally so later loads skip the API
            log.info("Token recovered from GitHub repo after restart")
        return token
    except Exception as e:
        log.warning("Could not read token from GitHub: %s", e)
        return None


# ─── Full token save (local + GitHub) ────────────────────────────────────────

def _save_token(access_token: str) -> tuple[bool, str]:
    """Save token locally AND to the repo. Returns the repo push result."""
    _save_token_local(access_token)
    return _push_token_to_github(access_token)


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
            # Synchronous: the repo copy is what survives a redeploy, so we must know
            # whether it landed before moving on (see _push_token_to_github).
            ok, msg = _save_token(access_token)
            _browser_store(access_token)     # survives every redeploy, no setup needed
            st.session_state["kite_authenticated"] = True
            st.session_state["token_repo_ok"] = ok
            st.session_state["token_repo_msg"] = msg
            st.query_params.clear()
            log.info("OAuth complete — token saved (repo push ok=%s)", ok)
            st.rerun()
        except Exception as e:
            st.query_params.clear()
            st.session_state.pop("kite_authenticated", None)
            _clear_token()
            st.error(f"❌ Kite login failed: {e}")
            st.info("The login link expired before it was used — click below to try again.")
            _show_login_ui(kite)
            st.stop()

    # ② Try saved token — local file first, then the repo copy.
    # The repo fallback is what survives a Streamlit Cloud redeploy: the container is
    # rebuilt on every push to main (seven scheduled pushes on a normal trading day),
    # and access_token.txt is not tracked in git, so the local file is simply gone.
    # Order matters: local file (fastest) → browser hand-back → repo copy.
    saved_token = _load_token() or _token_from_query() or _load_token_from_github()
    if saved_token:
        state = _validate_token(kite, saved_token)
        if state == "valid":
            _save_token_local(saved_token)   # cache on this container for later loads
            _browser_store(saved_token)      # refresh the browser copy
            st.session_state["kite_authenticated"] = True
            try:
                st.query_params.clear()      # strip kite_restore from the URL
            except Exception:
                pass
            log.info("Valid token loaded")
            return kite
        if state == "unknown":
            # Transient failure (network / rate limit). Keep the token and use it —
            # clearing here is what used to force a needless re-login.
            st.session_state["kite_authenticated"] = True
            log.warning("Token check inconclusive — proceeding with saved token")
            return kite
        log.warning("Token genuinely rejected by Kite — re-login needed")
        _clear_token()
        _browser_clear()

    # ④ Nothing worked. Before showing the login screen, give the browser one
    # chance to hand back a token it is holding — this is the path that makes a
    # redeploy invisible instead of a fresh login.
    if not st.query_params.get("kite_restore"):
        _browser_restore()

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
                        width="stretch", type="primary")
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
