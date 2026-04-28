# config.py — premiumdecay / nifty_options_dashboard
# Single source of truth for ALL strategy constants.
# Dow Theory updated: 1H single-window phase system — 27 Apr 2026
# SuperTrend MTF added — 27 Apr 2026
# Home score rescaled (Option B): total max = 100 across 8 lenses — 27 Apr 2026

# ─── Universe ────────────────────────────────────────────────────────────────
NIFTY_INDEX_TOKEN = "256265"
TOP_10_NIFTY = [
    "HDFCBANK","RELIANCE","ICICIBANK","INFY",
    "BHARTIARTL","TCS","LT","AXISBANK","KOTAKBANK","ITC",
]
BANKING_QUARTET = ["HDFCBANK","ICICIBANK","AXISBANK","KOTAKBANK"]
HEAVY_STOCKS    = ["HDFCBANK","RELIANCE","ICICIBANK"]
IT_STOCKS       = ["INFY","TCS"]

# ─── Core Strategy ───────────────────────────────────────────────────────────
BASELINE_OTM_PCT  = 0.05
WING_DISTANCE     = 500
MIN_NET_CREDIT    = 20
HOLD_DAYS         = 7

# ─── VIX-Based Sizing ────────────────────────────────────────────────────────
VIX_NO_TRADE      = 11
VIX_HALF_SIZE     = 12
VIX_FULL_SIZE     = 17
VIX_SWEET_SPOT    = 20
VIX_ELEVATED      = 28
VIX_CRISIS        = 28
VIX_EXTREME       = 40

# ─── Gift Nifty Gap ──────────────────────────────────────────────────────────
GAP_NO_ACTION     = 1.0
GAP_HEDGE_ATM     = 1.5
GAP_CLOSE_LEG     = 2.5
GAP_CLOSE_ALL     = 3.5

# ─── EMA ─────────────────────────────────────────────────────────────────────
MTF_EMA_PERIODS   = [3, 8, 16, 30, 60, 120, 200]

# ─── Page 1: Duration Score ──────────────────────────────────────────────────
DURATION_LOOKBACK   = 14
PUT_SAFETY_W1       = 0.65; PUT_EMA_PRIMARY   = 60
PUT_SAFETY_W2       = 0.35; PUT_EMA_SECONDARY = 120
CALL_SAFETY_W1      = 0.65; CALL_EMA_PRIMARY  = 30
CALL_SAFETY_W2      = 0.35; CALL_EMA_SECONDARY= 60
WICK_THRESHOLD_PCT  = 0.005; WICK_PENALTY = 5
EMA38_THRESHOLD     = 60;   EMA38_PENALTY_PCT = 0.20
FLAT_PCT            = 0.0005
FLAT_1_2_DAYS       = 0.10; FLAT_3_4_DAYS = 0.20; FLAT_5_BLOCK = True
SAFETY_DISC = [(75,100,0),(50,74,200),(35,49,400),(0,34,600)]
P1_EMA60_1_DECAY    = 0.30; P1_EMA60_2_DECAY = 0.51
P1_EMA120_DECAY     = 0.50; P1_RECOVERY      = 5
P1_WHIPSAW_PCT      = 0.003; P1_WHIPSAW_CANDLES = 2
P1_HARD_EXIT        = 50
NET_SKEW_TABLE = [
    ( 60, 100, 1000, 1600, "1:2"),
    ( 30,  60, 1100, 1400, "1:2"),
    (-30,  30, 1200, 1200, "1:1"),
    (-60, -30, 1400, 1100, "2:1"),
    (-100,-60, 1600, 1000, "2:1"),
]

# ─── Page 2: EMA Regime ──────────────────────────────────────────────────────
STACK_WEIGHTS = {(120,200):25,(60,120):20,(30,60):15,(16,30):15,(8,16):13,(3,8):12}
CV_KNOT=0.3; CV_FAN=0.8
CONSISTENCY_BASE=0.70; CONSISTENCY_SLOPE=0.30
REGIME_DISTANCES = {
    "KNOT":       {"call":1600,"put":1600,"ratio":"1:1","size":0.5},
    "BULLISH_FAN":{"call":1100,"put":1500,"ratio":"1:2","size":1.0},
    "STRONG_BULL":{"call":1000,"put":1600,"ratio":"1:2","size":1.0},
    "BEARISH_FAN":{"call":1500,"put":1100,"ratio":"2:1","size":1.0},
    "STRONG_BEAR":{"call":1600,"put":1000,"ratio":"2:1","size":1.0},
    "WEAK_MIXED": {"call":1300,"put":1300,"ratio":"1:1","size":0.5},
}

# ─── Pages 3+4: Breadth ──────────────────────────────────────────────────────
BREADTH_PUT_DIST = [(65,100,0),(40,64,100),(0,39,200)]
DIVERGENCE_EXTRA  = 300; LEAD_WARNING_EXTRA = 200

# ─── Pages 5-8: RSI ──────────────────────────────────────────────────────────
RSI_PERIOD=14
W_RSI_CAPIT=30; W_RSI_BEAR_MAX=40; W_RSI_BEAR_TRANS=45
W_RSI_NEUTRAL_MID=50; W_RSI_BULL_TRANS=60; W_RSI_BULL_MIN=65; W_RSI_EXHAUST=70
D_RSI_CAPIT=32; D_RSI_BEAR_P=39; D_RSI_BAL_LOW=46
D_RSI_BAL_HIGH=54; D_RSI_BULL_P=61; D_RSI_EXHAUST=68
RSI_KS_W_FLIP_BULL=55; RSI_KS_W_FLIP_BEAR=45
RSI_W_BULL_TRANS_BONUS=10; RSI_W_BULL_EXH_EXTRA=200; RSI_K3_EXTRA=300
RSI_BFSI_SOFTENING=200; RSI_SD5_CALL_EXTRA=100; RSI_SD6_EXIT_BUF=2.0

# ─── Page 9: Bollinger ───────────────────────────────────────────────────────
BB_PERIOD=20; BB_STD=2.0; BB_SQUEEZE=3.5; BB_NORMAL_L=5.0; BB_NORMAL_H=7.0; BB_EXPAND=8.0
BB_SQUEEZE_CREDIT  = 20; BB_SQUEEZE_EXTRA = 300; BB_WALK_EXTRA = 400
BB_MR_REDUCE       = 100; BB_BREACH_EXTRA = 200
BB_VIX_DIV_VIX     = 16; BB_VIX_DIV_BW = 4.5; BB_VIX_DIV_EXTRA = 200

# ─── Page 10: Options Chain ──────────────────────────────────────────────────
OI_STRIKE_RANGE=500; OI_STRIKE_STEP=50; OI_WALL_PCT=0.75
PCR_BALANCED_LOW=0.9; PCR_BALANCED_HI=1.1
WALL_DIST_RANGE=1.2; WALL_DIST_EXPAND=2.5
GEX_NEG_EXTRA=300; GEX_NOTRADE_CANARY=2; GEX_NOTRADE_VIX=17
IV_SKEW_HIGH=5.0; IV_SKEW_PUT_EXTRA=200; IV_SKEW_LOW=1.0
GEX_FLIP_EXTRA=200

# ─── Page 10B: OI Momentum ───────────────────────────────────────────────────
DTE_THETA_MIN=5; DTE_WARN_MIN=3
OI_SCORE_HIGH=50; OI_SCORE_MED=25; OI_SCORE_LOW=10; OI_NOISE=10
OI_UNWIND_MILD=-10; OI_UNWIND_HEAVY=-20; OI_PANIC=-35
WALL_RATIO_LOW=1.5; WALL_RATIO_MID=2.5
WALL_INTRADAY_REINFORCE=0.15; WALL_INTRADAY_ABANDON=0.0
DUAL_FORTRESS_BONUS=2; DUAL_FORTRESS_DIST_RED=100

# ─── Page 11: VIX / IV ───────────────────────────────────────────────────────
VIX_COMPLACENT=11; VIX_LOW_NORMAL=12; VIX_TRADEABLE=17; VIX_SWEET_SPOT_HI=20
IVP_AVOID=15; IVP_HALF=25; IVP_IDEAL_H=70; IVP_EXTREME=80
HV_PERIOD=20; VRP_HIGH_POSITIVE=5.0; VRP_NEG_EXTRA=200
VIX_SPIKE_MODERATE=0.30; VIX_SPIKE_EXTREME=0.50; VIX_SPIKE_BUF_MULT=2.0; VIX_SPIKE_WIDEN=300

# ─── Page 12: Market Profile ─────────────────────────────────────────────────
MP_BUCKET=50; MP_VA_PCT=0.70; MP_IC_WIDTH_MIN=1.5
MP_POC_CLOSE_DIST=200; MP_RESPONSIVE_RED=100; MP_INITIATIVE_EXTRA=200
MP_K1_EXTRA=200; MP_K3_ATR_MULT=2.0; MP_PARTIAL_EXTRA=100

# ─── Page 14: SuperTrend MTF ─────────────────────────────────────────────────
#
# Indicator: SuperTrend(21, 2) on 6 scored TFs + 5m display-only
# Proxy TFs: 2H and 4H resampled from 1H OHLCV inside supertrend.py
# Measuring unit: % of CMP throughout (not ATR)
#
# TF weights (total = 90, max raw score = 180 at all DEEP 2.0×)
ST_PERIOD          = 21
ST_MULTIPLIER      = 2.0
ST_TF_WEIGHTS      = {"daily":30, "4h":20, "2h":15, "1h":12, "30m":8, "15m":5}

# Depth thresholds (% of CMP)
ST_DEPTH_DEEP        = 3.0   # > 3.0%  → DEEP
ST_DEPTH_COMFORTABLE = 2.0   # 2.0-3.0% → COMFORTABLE
ST_DEPTH_ADEQUATE    = 1.0   # 1.0-2.0% → ADEQUATE
ST_DEPTH_THIN        = 0.5   # 0.5-1.0% → THIN
                              # < 0.5%   → CRITICAL

# Depth multipliers
ST_MULT_DEEP        = 2.0
ST_MULT_COMFORTABLE = 1.5
ST_MULT_ADEQUATE    = 1.0
ST_MULT_THIN        = 0.5
ST_MULT_CRITICAL    = 0.2

# Safe distance: cumulative normalised score threshold (0-100)
ST_SAFE_DIST_THRESHOLD = 50.0

# Minimum distance floor when threshold never reached
ST_MIN_FLOOR_PCT = 2.0

# Cluster rule: adjacent TF lines within this % CMP = single wall bracket
ST_CLUSTER_PCT = 0.5

# IC shape skew threshold (normalised score difference between sides)
ST_SHAPE_SKEW_THRESHOLD = 25.0

# Home score max (rescaled from 10 → 9 under Option B)
ST_HOME_SCORE_MAX = 9

# Data fetch windows
ST_30M_DAYS = 10   # 30m candles: 10 trading days × 12 = 120 candles
ST_15M_DAYS = 5    # 15m candles: 5 trading days × 24 = 120 candles
ST_5M_DAYS  = 2    # 5m candles: display only, 2 days × 72 = 144 candles

# ─── ATR / Breach / Survival ─────────────────────────────────────────────────
ATR_PERIOD=14
BREACH_PCT=0.005
SUSTAIN_PUT_BARS=4; SUSTAIN_CALL_BARS=8; SUSTAIN_EVENT_BARS=2
RSI_VEL_FAST=-5; RSI_VEL_MOD=0
ROLL_TABLE = [(5,6,600),(3,4,400),(2,2,300),(1,1,200)]

# ─── Leg-Shift ───────────────────────────────────────────────────────────────
LS_MIN_DTE=4; LS_UNTHREATENED_MIN=0.40; LS_PROFIT_TARGET=0.40; LS_DTE_EXIT=2
LS_ATR_FACTOR=1.2; LS_CREDIT_VIABLE=15; LS_CREDIT_MARGINAL=8; LS_FORBIDDEN_DIST=1500

# ─── Expiry Cycle ─────────────────────────────────────────────────────────────
EXIT_PROFIT_PCT=0.55; EXIT_DTE=5
EXPIRY_DELTA_MON=0.30; EXPIRY_TUE_CLOSE=150

# ─── Dow Theory — Single Window Phase System ─────────────────────────────────
# ONE window. ONE N. Everything derived from same pivot series.
#
# DATA:
#   20 trading days × 6 candles/day = 120 candles of 1H OHLCV
#   Fetched daily. NOT frozen. Cache TTL = 1 hour.
#
# PIVOT DETECTION (N=3):
#   Pivot HIGH at bar i:
#     high[i] >= high[i-1,i-2,i-3]  AND  high[i] >= high[i+1,i+2,i+3]
#   Pivot LOW at bar i:
#     low[i]  <= low[i-1,i-2,i-3]   AND  low[i]  <= low[i+1,i+2,i+3]
#   Confirmation lag = 3 hours. Last 3 candles of today always unconfirmed.
#   Acceptable for EOD use.
#
# REFERENCE PIVOTS:
#   PH_last, PH_prev  = last two confirmed pivot highs
#   PL_last, PL_prev  = last two confirmed pivot lows
#   Minimum 2 of each required. Else → INSUFFICIENT_DATA.
#
# STRUCTURE:
#   PH_last > PH_prev AND PL_last > PL_prev → UPTREND
#   PH_last < PH_prev AND PL_last < PL_prev → DOWNTREND
#   PH_last > PH_prev AND PL_last < PL_prev → MIXED_EXPANDING
#   PH_last < PH_prev AND PL_last > PL_prev → MIXED_CONTRACTING
#   abs(PH_last - PL_last) < DOW_CONSOLIDATION_ATR × ATR14 → CONSOLIDATING
#
# SEQUENCE:
#   Which pivot was most recent in time?
#   PH_last.time > PL_last.time → price fell FROM a high → FALLING
#   PL_last.time > PH_last.time → price rose FROM a low  → RISING
#
# RETRACE DEPTH %:
#   RISING:  (spot - PL_last) / (PH_last - PL_last) × 100
#   FALLING: (PH_last - spot) / (PH_last - PL_last) × 100
#   Range: 0% (just left pivot) to 100% (back at opposite pivot)
#   >100% = new pivot forming (continuation)
#
# DURATION:
#   Sessions since PH_last or PL_last confirmed (whichever is most recent)
#   = (current_index - pivot_index) / 6
#   Rounded to 0.5. Minimum display = "today" if < 1.
#
# PHASE (8 states + 2 mixed + 1 consolidating):
#   UPTREND:
#     UT-1  RETRACING     → rising from PL_last, retrace_pct 0-90%, below PH_last
#     UT-2  CONTINUING    → spot > PH_last (last candle HIGH crossed raw level)
#     UT-3  HL_THREATENED → rising from PL_last, retrace_pct > 90%, within 50pts of PL_last
#     UT-4  BROKEN        → last candle LOW < PL_last (raw level, no buffer)
#   DOWNTREND:
#     DT-1  RETRACING     → rising from PL_last, retrace_pct 0-90%, below PH_last
#     DT-2  CONTINUING    → spot < PL_last (last candle LOW crossed raw level)
#     DT-3  LH_THREATENED → rising from PL_last, retrace_pct > 90%, within 50pts of PH_last
#     DT-4  BROKEN        → last candle HIGH > PH_last (raw level, no buffer)
#   MIXED_EXPANDING, MIXED_CONTRACTING, CONSOLIDATING → always WAIT
#
# HEALTH (per leg, based on skewed IC):
#   In DOWNTREND (2:1 — CE is vulnerable leg):
#     CE health = distance from spot to PH_last
#     PE health = distance from spot to PL_last
#   In UPTREND (1:2 — PE is vulnerable leg):
#     PE health = distance from spot to PL_last
#     CE health = distance from spot to PH_last
#   Thresholds (pts from reference level):
#     > 200pts  → STRONG
#     100-200   → MODERATE
#     50-100    → WATCH
#     < 50pts   → ALERT
#     crossed   → BREACH
#
# PHASE SCORE (runs every day — not just Tuesday):
#   DOWNTREND:
#     DT-1 retrace 60-90%  → PRIME    (at ceiling — max CE protection)
#     DT-1 retrace 30-60%  → GOOD
#     DT-1 retrace 0-30%   → WAIT     (PE still has room to rise)
#     DT-3 LH threatened   → PRIME    (last moment at ceiling)
#     DT-2 continuing down → AVOID    (PE threatened)
#     DT-4 broken          → NO_TRADE
#   UPTREND: mirror (PE/CE reversed)
#   MIXED/CONSOLIDATING    → WAIT always
#   Label: "Entry Decision" on Tuesday / "Nifty Health" Wed-Mon
#
# BREACH LEVELS:
#   Call breach = PH_last + 50 pts
#   Put  breach = PL_last - 50 pts
#   Proximity warning when spot within ATR14/3 of either level
#
# SCORE HISTORY:
#   Last 5 trading days stored in data/dow_score_history.json
#   Fields per day: date, weekday, structure, phase, retrace_pct,
#                   ce_health, pe_health, phase_score, narrative

DOW_N                  = 3      # bars each side for pivot confirmation
DOW_PHASE_DAYS         = 20     # trading days of 1H data (= 120 candles)
DOW_BREACH_BUFFER_PTS  = 50     # fixed points added/subtracted from pivot level
DOW_HEALTH_ALERT_PTS   = 50     # within 50pts  → ALERT
DOW_HEALTH_WATCH_PTS   = 100    # within 100pts → WATCH
DOW_HEALTH_MOD_PTS     = 200    # within 200pts → MODERATE  (beyond = STRONG)
DOW_CONSOLIDATION_ATR  = 1.0    # PH-PL < 1×ATR14 → CONSOLIDATING
DOW_SCORE_HISTORY_DAYS = 5      # days of score history to retain

# Legacy aliases — DO NOT USE in new code
DOW_PIVOT_LOOKBACK   = 3
DOW_PIVOT_BREACH_PCT = 0.005

PIVOT_HIGHER_HIGH = "HH"
PIVOT_HIGHER_LOW  = "HL"
PIVOT_LOWER_HIGH  = "LH"
PIVOT_LOWER_LOW   = "LL"

# ─── Live Fetcher Constants ──────────────────────────────────────────────────
TTL_OPTIONS    = 30
TTL_PRICE      = 60
TTL_DAILY      = 86400
TTL_1H         = 3600
TTL_30M        = 1800    # 30 minutes — SuperTrend Tier 3
TTL_15M        = 900     # 15 minutes — SuperTrend Tier 3
TTL_5M         = 300     # 5 minutes  — SuperTrend display only
EXPIRY_WEEKDAY = 1

IVP_SMALL = 25

TOP_10_TOKENS = {
    "HDFCBANK":   341249,
    "RELIANCE":   738561,
    "ICICIBANK":  1270529,
    "INFY":       408065,
    "BHARTIARTL": 2714625,
    "TCS":        2953217,
    "LT":         2939649,
    "AXISBANK":   1510401,
    "KOTAKBANK":  492033,
    "ITC":        424961,
}

GIFT_NIFTY_TOKEN = "NSE_IFSC:GIFTNIFTY"

# ─── Geometric Edge Scanner (Page 13) ────────────────────────────────────────
GEO_PRICE_STRENGTH = {
    "nifty50": 0.020, "nifty_next": 0.025,
    "midcap":  0.030, "smallcap":   0.035,
}
GEO_VOL_MULT=2.0; GEO_ADR=0.04; GEO_EP_GAP=0.005
GEO_VOL_SMA_PERIOD=50; GEO_MAX_RESULTS=20; GEO_MIN_RR=2.0
GEO_MARKET_HEALTH_BULL=300; GEO_MARKET_HEALTH_SELECT=200
WATCHLIST_DIR="data/watchlists"; PARQUET_DIR="data/parquet"

# ─── Home Score Rescaling (Option B) — 8 lenses, total max = 100 ─────────────
# Previous max per lens:  OC=25, RSI=20, MP=20, BB=15, VIX=10, Dow=5, EMA=5
# ST adds 9 pts. Rescaled so total max = 100.
# Options Chain: 22, RSI: 18, Market Profile: 18, Bollinger: 14,
# VIX/IV: 9, Dow Theory: 5, EMA: 5, SuperTrend MTF: 9  → Total: 100
HOME_SCORE_MAX_OC  = 22
HOME_SCORE_MAX_RSI = 18
HOME_SCORE_MAX_MP  = 18
HOME_SCORE_MAX_BB  = 14
HOME_SCORE_MAX_VIX = 9
HOME_SCORE_MAX_DOW = 5
HOME_SCORE_MAX_EMA = 5
HOME_SCORE_MAX_ST  = 9
