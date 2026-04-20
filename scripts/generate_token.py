# scripts/generate_token.py
# Used ONLY for GitHub Actions CI — not needed for the Streamlit dashboard.
# The Streamlit dashboard handles token generation automatically via OAuth.
#
# Run this locally once to get a token for GitHub Actions:
#   python scripts/generate_token.py --request_token PASTE_REQUEST_TOKEN_HERE
#
# To get the request_token:
#   1. Open: https://kite.zerodha.com/connect/login?api_key=YOUR_API_KEY&v=3
#   2. Log in → copy request_token from the redirect URL
#   3. Run this script → it prints the access_token
#   4. Add it to GitHub repo secrets as KITE_ACCESS_TOKEN

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    parser = argparse.ArgumentParser(
        description="Generate Kite access token for GitHub Actions"
    )
    parser.add_argument("--request_token", required=True,
                        help="request_token from Kite login redirect URL")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    api_key    = os.environ.get("KITE_API_KEY")
    api_secret = os.environ.get("KITE_API_SECRET")

    if not api_key or not api_secret:
        print("ERROR: Set KITE_API_KEY and KITE_API_SECRET in your .env file")
        sys.exit(1)

    try:
        from kiteconnect import KiteConnect
    except ImportError:
        print("ERROR: Run: pip install kiteconnect")
        sys.exit(1)

    kite = KiteConnect(api_key=api_key)

    try:
        data         = kite.generate_session(args.request_token, api_secret=api_secret)
        access_token = data["access_token"]
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"\nAccess token: {access_token}\n")

    # Save to token.txt so GitHub Actions can pick it up
    Path("token.txt").write_text(access_token)
    print("Saved to token.txt")
    print("\nAlso add to GitHub repo secrets as KITE_ACCESS_TOKEN")


if __name__ == "__main__":
    main()
