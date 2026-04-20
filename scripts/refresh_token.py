#!/usr/bin/env python3
"""
Token Refresh Helper — run this manually each morning after Kite login.
Updates KITE_ACCESS_TOKEN in GitHub repository secrets via GitHub API.

Usage:
    python scripts/refresh_token.py --token YOUR_KITE_ACCESS_TOKEN
    python scripts/refresh_token.py  # reads from token.txt if present

Requirements:
    pip install PyNaCl requests

GitHub Personal Access Token needs: repo + secrets write permissions.
Set GH_PAT environment variable or pass as --gh-pat argument.
"""
import sys, os, argparse, base64, json
from pathlib import Path

def update_github_secret(repo_owner: str, repo_name: str, gh_pat: str,
                          secret_name: str, secret_value: str):
    """Update a GitHub Actions secret via API."""
    try:
        import requests
        from nacl import encoding, public

        # Get repo public key for encryption
        headers = {"Authorization": f"token {gh_pat}", "Accept": "application/vnd.github+json"}
        url_base = f"https://api.github.com/repos/{repo_owner}/{repo_name}"

        key_resp = requests.get(f"{url_base}/actions/secrets/public-key", headers=headers)
        key_resp.raise_for_status()
        pub_key_data = key_resp.json()

        # Encrypt secret
        pub_key = public.PublicKey(pub_key_data["key"].encode(), encoding.Base64Encoder())
        sealed = public.SealedBox(pub_key)
        encrypted = base64.b64encode(sealed.encrypt(secret_value.encode())).decode()

        # Update secret
        resp = requests.put(
            f"{url_base}/actions/secrets/{secret_name}",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": pub_key_data["key_id"]}
        )
        resp.raise_for_status()
        print(f"✅ {secret_name} updated in {repo_owner}/{repo_name}")
    except ImportError:
        print("Install PyNaCl: pip install PyNaCl requests")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Refresh Kite token in GitHub secrets")
    parser.add_argument("--token",   help="Kite access token (or read from token.txt)")
    parser.add_argument("--gh-pat",  help="GitHub PAT (or GH_PAT env var)")
    parser.add_argument("--repo",    help="GitHub repo as owner/name", default="")
    args = parser.parse_args()

    # Get access token
    token = args.token
    if not token:
        token_file = Path(__file__).parent.parent / "token.txt"
        if token_file.exists():
            token = token_file.read_text().strip()
    if not token:
        print("❌ No access token. Pass --token or ensure token.txt exists.")
        sys.exit(1)

    # Get GitHub PAT
    gh_pat = args.gh_pat or os.environ.get("GH_PAT")
    if not gh_pat:
        print("❌ No GitHub PAT. Set GH_PAT env var or pass --gh-pat.")
        sys.exit(1)

    # Get repo
    repo = args.repo or os.environ.get("GITHUB_REPO", "")
    if not repo or "/" not in repo:
        print("❌ Provide --repo as owner/reponame or set GITHUB_REPO env var.")
        sys.exit(1)

    owner, name = repo.split("/", 1)
    update_github_secret(owner, name, gh_pat, "KITE_ACCESS_TOKEN", token)
    print(f"Token (last 6 chars): ...{token[-6:]}")
    print("GitHub Actions will use this token for tonight's EOD compute.")


if __name__ == "__main__":
    main()
