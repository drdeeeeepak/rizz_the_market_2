# data/notify.py
# One place to send an alert, over email and/or Telegram.
#
# Alerts used to be Telegram-only and written inline in each script. Email is the
# channel that actually gets seen, so it is the default here; Telegram still fires
# when configured, and both are optional.
#
# ─── SETTING UP EMAIL ────────────────────────────────────────────────────────
# Repository secrets (Settings → Secrets and variables → Actions):
#     ALERT_EMAIL   where to send to      e.g. you@gmail.com
#     SMTP_USER     the sending account   e.g. you@gmail.com
#     SMTP_PASS     an APP PASSWORD, not your normal password
#     SMTP_HOST     optional, default smtp.gmail.com
#     SMTP_PORT     optional, default 587 (STARTTLS)
#
# For Gmail: turn on 2-factor auth, then create an App Password
# (myaccount.google.com → Security → App passwords). Gmail refuses plain account
# passwords from scripts, so an app password is required.
#
# ─── THE ZERO-CONFIG OPTION ──────────────────────────────────────────────────
# GitHub already emails the repository owner whenever a scheduled workflow FAILS,
# with no setup at all. That covers "the EOD job did not run". What it cannot do
# is explain WHY in plain words, or reach you when a job succeeds but the data was
# unusable — which is what this module is for.

import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)

_DEF_HOST = "smtp.gmail.com"
_DEF_PORT = 587


def _cfg(key: str, default: str = "") -> str:
    """Read from the environment (Actions secrets), falling back to Streamlit
    secrets when running inside the app."""
    val = os.environ.get(key, "").strip()
    if val:
        return val
    try:
        import streamlit as st
        v = st.secrets.get(key)
        return str(v).strip() if v else default
    except Exception:
        return default


def email_configured() -> bool:
    return bool(_cfg("ALERT_EMAIL") and _cfg("SMTP_USER") and _cfg("SMTP_PASS"))


def telegram_configured() -> bool:
    return bool(_cfg("TELEGRAM_TOKEN") and _cfg("TELEGRAM_CHAT"))


def send_email(subject: str, body: str) -> tuple[bool, str]:
    """Send one alert email. Returns (ok, detail). Never raises."""
    to   = _cfg("ALERT_EMAIL")
    user = _cfg("SMTP_USER")
    pw   = _cfg("SMTP_PASS")
    host = _cfg("SMTP_HOST", _DEF_HOST)
    port = int(_cfg("SMTP_PORT", str(_DEF_PORT)) or _DEF_PORT)

    if not (to and user and pw):
        return False, "email not configured (need ALERT_EMAIL, SMTP_USER, SMTP_PASS)"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"]    = user
    msg["To"]      = to
    msg.set_content(body)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=20) as s:
                s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls()
                s.login(user, pw)
                s.send_message(msg)
        log.info("Alert email sent to %s", to)
        return True, f"sent to {to}"
    except Exception as e:
        # Most common cause by far: using the account password instead of an
        # app password, which Gmail rejects outright.
        log.warning("Alert email failed: %s", e)
        return False, f"{type(e).__name__}: {e}"


def send_telegram(text: str) -> tuple[bool, str]:
    """Send one Telegram message. Returns (ok, detail). Never raises."""
    tok, chat = _cfg("TELEGRAM_TOKEN"), _cfg("TELEGRAM_CHAT")
    if not (tok and chat):
        return False, "telegram not configured"
    try:
        import requests
        r = requests.get(f"https://api.telegram.org/bot{tok}/sendMessage",
                         params={"chat_id": chat, "text": text}, timeout=10)
        return (r.status_code == 200), f"HTTP {r.status_code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def send_alert(subject: str, body: str, telegram_text: str = None) -> dict:
    """
    Send over every configured channel. Returns what each one did.

    Deliberately does not stop after the first success: an alert about lost data is
    worth delivering twice, and a channel that quietly stopped working is worse than
    a duplicate. Returns a dict rather than a bool so the caller can log which
    channels actually delivered.
    """
    result = {}
    if email_configured():
        ok, detail = send_email(subject, body)
        result["email"] = {"ok": ok, "detail": detail}
    if telegram_configured():
        ok, detail = send_telegram(telegram_text or f"{subject}\n\n{body}")
        result["telegram"] = {"ok": ok, "detail": detail}
    if not result:
        result["none"] = {"ok": False,
                          "detail": "no alert channel configured — set ALERT_EMAIL/"
                                    "SMTP_USER/SMTP_PASS, or TELEGRAM_TOKEN/TELEGRAM_CHAT"}
    log.info("Alert '%s' → %s", subject, result)
    return result
