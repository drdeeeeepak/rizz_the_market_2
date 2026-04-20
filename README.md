# Nifty 50 Biweekly Credit Options Dashboard

Systematic dashboard for Iron Condor / Bull Put Spread / Bear Call Spread
on Nifty 50 Tuesday weekly expiry using Zerodha Kite Connect API.

## Architecture

```
Near expiry  → Intelligence layer (walls, PCR, GEX, Max Pain)
Far expiry   → Your trade (IC position, 12 DTE entry, 5 DTE exit)
```

## Pages

| Page | Title | Home pts |
|------|-------|----------|
| 00 | Command Center (Home) | 100 total |
| 01 | Nifty Price vs MTF EMAs | 6 |
| 02 | Nifty EMA Ribbon | — |
| 03 | Top 10 Stocks EMA vs Price | 4 (breadth) |
| 04 | Top 10 Stocks EMA Ribbon | — |
| 05 | Nifty Weekly RSI Regime | 20 |
| 06 | Nifty Daily RSI Execution | — |
| 07 | Stocks Weekly RSI | — |
| 08 | Stocks Daily RSI | — |
| 09 | Bollinger Bands | 15 |
| 10 | Options Chain Engine | 25 |
| 10B | OI Momentum Scoring | additive |
| 11 | VIX / IV Regime | 10 |
| 12 | Market Profile | 20 |
| 13 | Geometric Edge Scanner | — |

## Setup

### 1. Clone and install
```bash
git clone https://github.com/your-username/nifty-options-dashboard.git
cd nifty-options-dashboard
pip install -r requirements.txt
```

### 2. Credentials
```bash
cp .env.example .env
# Fill in KITE_API_KEY and KITE_ACCESS_TOKEN in .env
```

For Streamlit dashboard, also create `.streamlit/secrets.toml`:
```toml
KITE_API_KEY      = "your_key"
KITE_ACCESS_TOKEN = "your_token"
```

### 3. Run locally
```bash
streamlit run Home.py
```

### 4. GitHub Actions setup
In your GitHub repository:
- Settings → Secrets → Actions
- Add `KITE_API_KEY` and `KITE_ACCESS_TOKEN`
- Workflows run automatically at scheduled IST times

**Important**: Kite access tokens expire daily at midnight IST.
Update `KITE_ACCESS_TOKEN` in GitHub Secrets each morning before 11am.

## GitHub Actions Schedule (IST → UTC)

| Scan | IST | UTC | Cron |
|------|-----|-----|------|
| 11am | 11:00 AM | 05:30 | `30 5 * * 1-5` |
| 1:30pm | 1:30 PM | 08:00 | `0 8 * * 1-5` |
| 3:15pm | 3:15 PM | 09:45 | `45 9 * * 1-5` |
| EOD | 3:35 PM | 10:05 | `5 10 * * 1-5` |

## Scoring System

| Score | Verdict | Size |
|-------|---------|------|
| 0–34 | No trade | 0% |
| 35–49 | Wait | 0% |
| 50–64 | Trade reduced | 50% |
| 65–79 | Trade standard | 75% |
| 80–100 | Trade full | 100% |

Breadth multiplier applied after score:
8–10 stocks above EMA60 → 1.0× · 6–7 → 0.85× · 4–5 → 0.65× · 0–3 → 0.40×

Any kill switch = absolute veto regardless of score.

## Expiry Cycle

```
Wednesday  → Cycle start. Observe only. Do not enter.
Thursday   → PRIME entry. VA firmed. OI concentrating.
Friday     → Follow or confirm.
Monday     → Adjust after weekend gap.
Tuesday    → Expiry. No new positions.
```

## Stack

Python 3.11 · Streamlit · Pandas · Plotly · Kite Connect · GitHub Actions · Parquet
