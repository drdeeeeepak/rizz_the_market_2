"""
scripts/kite_auto_login.py
Automates Zerodha Kite login for GitHub Actions — no browser needed.

Requires these GitHub Actions secrets:
  KITE_API_KEY     — Kite Connect app API key
  KITE_API_SECRET  — Kite Connect app API secret
  KITE_USER_ID     — Zerodha login ID (e.g. AB1234)
  KITE_PASSWORD    — Zerodha login password
  KITE_TOTP_SECRET — TOTP seed shown when you set up 2FA (base32 string)

Writes access_token.txt with today's IST date so the EOD job and the
Streamlit app can both read it without a manual login.
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pyotp
import pytz
import requests
from kiteconnect import KiteConnect

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

IST       = pytz.timezone("Asia/Kolkata")
TOKEN_FILE = Path("access_token.txt")


def _require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        log.error("Missing required env var / secret: %s", key)
        sys.exit(1)
    return val


def auto_login() -> str:
    api_key     = _require("KITE_API_KEY")
    api_secret  = _require("KITE_API_SECRET")
    user_id     = _require("KITE_USER_ID")
    password    = _require("KITE_PASSWORD")
    totp_secret = _require("KITE_TOTP_SECRET")

    session = requests.Session()
    session.headers.update({"X-Kite-Version": "3"})

    # Step 1 — password login
    log.info("Step 1: password login for %s", user_id)
    resp = session.post(
        "https://kite.zerodha.com/api/login",
        data={"user_id": user_id, "password": password},
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != "success":
        log.error("Login failed: %s", body)
        sys.exit(1)
    request_id = body["data"]["request_id"]
    log.info("Password login OK, request_id: %s", request_id)

    # Step 2 — TOTP 2FA
    totp_code = pyotp.TOTP(totp_secret).now()
    log.info("Step 2: submitting TOTP")
    resp = session.post(
        "https://kite.zerodha.com/api/twofa",
        data={
            "user_id":    user_id,
            "request_id": request_id,
            "twofa_value": totp_code,
            "twofa_type": "totp",
        },
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != "success":
        log.error("2FA failed: %s", body)
        sys.exit(1)
    log.info("2FA OK")

    # Step 3 — Kite Connect OAuth, grab request_token from redirect
    kite      = KiteConnect(api_key=api_key)
    oauth_url = kite.login_url()
    log.info("Step 3: fetching OAuth URL")
    resp = session.get(oauth_url, allow_redirects=False, timeout=15)
    location  = resp.headers.get("Location", "")
    if not location:
        # Follow one more redirect manually
        resp = session.get(resp.url, allow_redirects=False, timeout=15)
        location = resp.headers.get("Location", "")
    if "request_token" not in location:
        log.error("Could not find request_token in redirect: %s", location)
        sys.exit(1)
    request_token = parse_qs(urlparse(location).query)["request_token"][0]
    log.info("request_token obtained")

    # Step 4 — exchange for access_token
    log.info("Step 4: generating session")
    session_data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = session_data["access_token"]
    log.info("access_token obtained")

    # Save to access_token.txt (same format as kite_client.py)
    today_ist = datetime.now(IST).strftime("%Y-%m-%d")
    TOKEN_FILE.write_text(
        json.dumps({"token": access_token, "date": today_ist}),
        encoding="utf-8",
    )
    log.info("Saved access_token.txt for %s", today_ist)
    return access_token


if __name__ == "__main__":
    auto_login()
    log.info("Kite auto-login complete.")
