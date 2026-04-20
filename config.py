# config.py — premiumdecay / nifty_options_dashboard
# Single source of truth for ALL strategy constants.
# Derived from nifty_complete_reference.docx (April 2026).

# ─── Universe ────────────────────────────────────────────────────────────────
NIFTY_INDEX_TOKEN = "256265"
# Top 10 Nifty 50 by free-float market cap weight (April 2026)
# Update only at NSE semi-annual rebalance — March and September
TOP_10_NIFTY = [
    "HDFCBANK","RELIANCE","ICICIBANK","INFY",
    "BHARTIARTL","TCS","LT","AXISBANK","KOTAKBANK","ITC",
]
BANKING_QUARTET = ["HDFCBANK","ICICIBANK","AXISBANK","KOTAKBANK"]
HEAVY_STOCKS    = ["HDFCBANK","RELIANCE","ICICIBANK"]   # top 3 by weight
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

# ─── Dow Theory Pivots ───────────────────────────────────────────────────────
DOW_PIVOT_LOOKBACK = 5    # bars each side for swing point detection
DOW_PIVOT_BREACH_PCT = 0.005  # 0.5% below/above pivot
PIVOT_HIGHER_HIGH  = "HH"
PIVOT_HIGHER_LOW   = "HL"
PIVOT_LOWER_HIGH   = "LH"
PIVOT_LOWER_LOW    = "LL"

# ─── Live Fetcher Constants ──────────────────────────────────────────────────
TTL_OPTIONS   = 30      # seconds — options chain cache
TTL_PRICE     = 60      # seconds — spot / VIX live
TTL_DAILY     = 86400   # seconds — 24h OHLCV cache
EXPIRY_WEEKDAY = 1      # Tuesday = 1 (Mon=0, Tue=1, ..., Sun=6)

# IVP alias (old code uses IVP_SMALL, new doc uses IVP_HALF=25)
IVP_SMALL = 25   # alias for IVP_HALF — keeps old imports working

# Nifty token map for top 10 stocks (NSE instrument tokens)
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
# KOTAKBANK token added. SBIN removed from top 10 (weight dropped).
# Verify tokens against Kite instruments list before trading.

# Gift Nifty / Futures tokens
GIFT_NIFTY_TOKEN = "NSE_IFSC:GIFTNIFTY"

# ─── Geometric Edge Scanner (Page 13) ────────────────────────────────────────
GEO_PRICE_STRENGTH = {
    "nifty50":    0.020,
    "nifty_next": 0.025,
    "midcap":     0.030,
    "smallcap":   0.035,
}
GEO_VOL_MULT          = 2.0
GEO_ADR               = 0.04
GEO_EP_GAP            = 0.005
GEO_VOL_SMA_PERIOD    = 50
GEO_MAX_RESULTS       = 20
GEO_MIN_RR            = 2.0
GEO_MARKET_HEALTH_BULL   = 300
GEO_MARKET_HEALTH_SELECT = 200
WATCHLIST_DIR  = "data/watchlists"
PARQUET_DIR    = "data/parquet"
