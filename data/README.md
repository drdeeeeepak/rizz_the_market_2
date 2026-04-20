# data/

Files written by GitHub Actions and the Streamlit dashboard.

## How the token flows (fully automatic after setup)

```
Morning: Open dashboard on any device (mobile/PC/tablet)
→ No valid token → Login page shown
→ Click "Login with Kite"
→ Zerodha authenticates you
→ Redirected back to dashboard
→ access_token generated
→ Saved to access_token.txt on Streamlit Cloud (local)
→ Automatically pushed to THIS GitHub repo via GH_PAT
→ Dashboard serves immediately

3:35 PM IST: GitHub Actions EOD job
→ Checks out repo (access_token.txt is here from morning login)
→ Reads token, authenticates with Kite
→ Fetches all data, runs all engines
→ Writes signals.json, breach_levels.json
→ Commits back to repo

Next morning: signals.json still in repo — dashboard works in planning mode
→ You open dashboard → login again → fresh token → new day
```

## Files in this directory

| File | Written by | Stays until |
|---|---|---|
| `access_token.txt` | Dashboard login (auto) | Overwritten next day |
| `signals.json` | EOD GitHub Actions | Overwritten next EOD |
| `breach_levels.json` | EOD GitHub Actions | Overwritten next EOD |
| `gap_check.json` | Pre-market GitHub Actions | Overwritten next pre-market |
| `events.json` | Event calendar GitHub Actions | Overwritten daily |

## GitHub Actions Secrets (Settings → Secrets → Actions)

| Secret | Description |
|---|---|
| `GH_PAT` | Personal Access Token with repo Contents write |
| `KITE_API_KEY` | Your Kite API key |
| `KITE_API_SECRET` | Your Kite API secret |
| `TELEGRAM_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT` | Your Telegram chat ID |

No `KITE_ACCESS_TOKEN` secret needed — token comes from access_token.txt in the repo.
