# ============================================================
#  NIFTY FIBONACCI v1.0 - Fibonacci Retracement + Extension
#  VPS (Hetzner + Groww API)
#
#  ARCHITECTURE:
#    - Same as before: Cron scan + WebSocket monitor
#    - GrowwFeed for sub-second price updates
#
#  STRATEGY:
#    1. Identify morning impulse move (9:15 - 9:45)
#    2. Plot Fibonacci retracement levels on the impulse
#    3. Wait for retracement into 38.2% - 61.8% golden pocket
#    4. Enter on bounce confirmation (engulfing / strong body)
#    5. SL below 78.6% fib | Targets at -27.2% and -61.8% ext
#
#  RULES:
#    - Max 2 trades/day (allows 1 recovery attempt)
#    - No trades after 13:00 (more time for fib setups)
#    - RR minimum 1:2 enforced
#    - Adaptive SL% based on premium range
#    - 5-min hold period with catastrophic SL
#    - OTM/ATM options for better % moves
#    - Partial profit booking at Extension 1
# ============================================================

from growwapi import GrowwAPI, GrowwFeed
import datetime
import logging
import json
import time
import pyotp
import os
import sys
import signal
import requests
import urllib3.util.connection as urllib3_cn

# ===== FORCE IPV4 =====
def force_ipv4():
    orig = urllib3_cn.create_connection
    def patched(address, *args, **kwargs):
        return orig((address[0], address[1]), *args, **kwargs)
    urllib3_cn.create_connection = patched

force_ipv4()

try:
    SERVER_IP = requests.get("https://api.ipify.org", timeout=5).text
    print("SERVER IP: " + SERVER_IP)
except:
    SERVER_IP = "unknown"
    print("Unable to fetch IP")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/root/scalper/bot.log"),
        logging.StreamHandler()
    ]
)

# =============================================================
#  SECTION 1 - CONFIGURATION
# =============================================================

GROWW_TOTP_TOKEN  = "eyJraWQiOiJaTUtjVXciLCJhbGciOiJFUzI1NiJ9.eyJleHAiOjI1NjQ0NjQ3NTEsImlhdCI6MTc3NjA2NDc1MSwibmJmIjoxNzc2MDY0NzUxLCJzdWIiOiJ7XCJ0b2tlblJlZklkXCI6XCI4OTFmMzExNi04NGRjLTQxNWMtOWUxYy1iOTc3YzNhMWExZmJcIixcInZlbmRvckludGVncmF0aW9uS2V5XCI6XCJlMzFmZjIzYjA4NmI0MDZjODg3NGIyZjZkODQ5NTMxM1wiLFwidXNlckFjY291bnRJZFwiOlwiNjQ3NTk3YTItNTlmMC00MWQ2LTkyZjgtMGNjYzdkYTBkN2I2XCIsXCJkZXZpY2VJZFwiOlwiYWM4Y2Y5NzctMTY5OC01NDM3LTkxNTItMzg2ZTFiZmM2YzQwXCIsXCJzZXNzaW9uSWRcIjpcIjAzM2E2OWRhLWQ3YzQtNDJkMS04YTJiLWNiMDc0NjQxMGIwZFwiLFwiYWRkaXRpb25hbERhdGFcIjpcIno1NC9NZzltdjE2WXdmb0gvS0EwYkgyblRaQUhZYlRzeVhHdDk1ZzgxR1JSTkczdTlLa2pWZDNoWjU1ZStNZERhWXBOVi9UOUxIRmtQejFFQisybTdRPT1cIixcInJvbGVcIjpcImF1dGgtdG90cFwiLFwic291cmNlSXBBZGRyZXNzXCI6XCIyNDAxOjQ5MDA6OTM5NTpjZTQ1OjdjNWM6NWVlYjoyMTAwOjZiYzUsMTcyLjY5LjEzMS4xODcsMzUuMjQxLjIzLjEyM1wiLFwidHdvRmFFeHBpcnlUc1wiOjI1NjQ0NjQ3NTEzMTgsXCJ2ZW5kb3JOYW1lXCI6XCJncm93d0FwaVwifSIsImlzcyI6ImFwZXgtYXV0aC1wcm9kLWFwcCJ9.Oyi_wQZPgluXSJTYzwyWEJ4Q3nW40o6e9sr7oD6gsfLwgMB0eNmG6TQDM2_yyEXZp2Z9z1tCuqTgJYd6rBJdOA"
GROWW_TOTP_SECRET = "5TJKK3FZ2NFN73QTENQLKH5AOVDRC7CQ"

# -- Trade sizing --
LOT_SIZE         = 65      # Updated to current NIFTY lot size (was 65)
LOTS_TO_TRADE    = 1
ITM_OFFSET       = 100     # 1-step ITM (better delta, less theta bleed than ATM)

# -- PAPER TRADE MODE --
PAPER_TRADE      = False     # START WITH PAPER - validate first!

# -- Fibonacci Settings --
IMPULSE_START_HOUR   = 9
IMPULSE_START_MIN    = 15
IMPULSE_END_HOUR     = 10    # Extended impulse window to 10:00 (was 9:45) for more setups
IMPULSE_END_MIN      = 0
IMPULSE_CANDLE_MIN   = 5     # 5-min candles

# Fibonacci Retracement Levels
FIB_236  = 0.236
FIB_382  = 0.382
FIB_500  = 0.500
FIB_618  = 0.618
FIB_786  = 0.786

# Golden pocket entry zone
FIB_ENTRY_UPPER = FIB_382    # Enter when price reaches 38.2%
FIB_ENTRY_LOWER = FIB_618    # Deepest acceptable retracement
FIB_SL_LEVEL    = FIB_786    # SL beyond 78.6%

# Fibonacci Extension Levels (for targets)
FIB_EXT_1 = -0.272           # First target: -27.2% extension
FIB_EXT_2 = -0.618           # Second target: -61.8% extension

# Minimum impulse move (percentage-based, auto-scales)
MIN_IMPULSE_PCT      = 0.12   # 0.12% of Nifty - avoids too-tight fib levels (noise stop-outs)
MAX_IMPULSE_PCT      = 1.00   # Max 1% (avoid exhaustion moves)
MIN_IMPULSE_POINTS   = 28     # Absolute minimum (raised from 25)
MAX_IMPULSE_POINTS   = 250    # Absolute maximum

# -- Bounce confirmation --
BOUNCE_MIN_BODY_PCT  = 0.35   # Candle body >= 35% of range (loosened from 45%)
BOUNCE_CONSEC_CANDLES = 1     # Need at least 1 strong bounce candle

# -- Risk (ADAPTIVE PERCENTAGE + RR RATIO) --
SL_PERCENT_LOW    = 18.0      # Premium Rs.50-100
SL_PERCENT_MID    = 14.0      # Premium Rs.100-250
SL_PERCENT_HIGH   = 10.0      # Premium Rs.250-400
RR_RATIO          = 2.0       # Target = SL x 2.0
MIN_RR_RATIO      = 2.0       # Reject if below 1:2

# -- Capital risk --
CAPITAL_RUPEES        = 50000
RISK_PER_TRADE_PCT    = 4.0    # Reduced from 6% to 4%
MAX_RISK_RUPEES       = CAPITAL_RUPEES * RISK_PER_TRADE_PCT / 100  # Rs.2000
MAX_DAILY_LOSS_RUPEES = 3000   # Combined cap across BOTH bots (shared state file)

# -- Cost-aware trade gate (option buyers must clear costs to be profitable) --
BROKERAGE_PER_ORDER   = 20.0    # Groww flat per executed order
STT_SELL_PCT          = 0.0625  # % of sell premium turnover (options)
EXCH_TXN_PCT          = 0.03503 # % NSE txn charge (both sides)
GST_PCT               = 18.0    # % on (brokerage + exch txn)
SLIPPAGE_PER_SIDE_PCT = 0.5     # % premium slippage per side (entry+exit)
MIN_NET_RR            = 1.5     # Reject trade if RR after all costs < 1.5

# -- Circuit breaker (survive losing streaks) --
MAX_CONSECUTIVE_LOSSES = 2      # Stop trading for the day after 2 losses in a row

# -- Hold time and catastrophic SL --
MIN_HOLD_MINUTES      = 5      # Reduced from 8 to 5
CATASTROPHIC_MAX_LOSS = 1500   # Reduced from 2000

# -- Other limits --
MAX_TRADES_DAY            = 2   # Allow recovery trade
MIN_OPTION_PREMIUM        = 40
MAX_OPTION_PREMIUM        = 350
MAX_SPREAD_PCT            = 2.5
MAX_CAPITAL_EXPOSURE_PCT  = 100
SL_BUFFER_POINTS          = 3

# -- Time --
NO_TRADE_AFTER_HOUR  = 13      # Extended to 1 PM (fibs need time)
NO_TRADE_AFTER_MIN   = 0
SQUAREOFF_HOUR       = 15
SQUAREOFF_MIN        = 10

# -- Market regime filters --
MIN_ADX_FOR_TRADE    = 14      # Lowered from 18 - allow more trending days
ADX_LEN              = 14
ATR_LEN              = 14
RSI_LEN              = 14
EMA_FAST             = 9
EMA_SLOW             = 21
VWAP_SESSION_BARS    = 75

# -- WebSocket monitor --
WS_TICK_LOG_INTERVAL = 30
WS_HEARTBEAT_SEC     = 60
TRAILING_SL_ENABLED  = True
TRAILING_SL_TRIGGER  = 0.30    # Start trailing at 30% of target
TRAILING_SL_STEP     = 0.60    # Lock 60% of open profit (was 0.50) - protect winners

# -- Theta / stagnation exit (option buyers bleed premium on dead trades) --
STAGNATION_EXIT_ENABLED   = True
STAGNATION_EXIT_MIN       = 25    # If trade is going nowhere after 25 min...
STAGNATION_MIN_PROFIT_RR  = 0.5   # ...and profit < 0.5x risk, cut it to save theta

# -- Partial Profit --
PARTIAL_EXIT_ENABLED = True
PARTIAL_EXIT_PCT     = 50      # Exit 50% at first target
PARTIAL_TARGET_RR    = 1.0     # First target at 1:1 RR

# -- Expiry --
NIFTY_EXPIRY_WEEKDAY = 1       # Tuesday

# -- Files --
STATE_FILE    = "/root/scalper/state.json"
TOKEN_FILE    = "/root/scalper/token.json"
CANDLE_FILE   = "/root/scalper/candles.json"
FIB_FILE      = "/root/scalper/fib_levels.json"
MONITOR_PID   = "/root/scalper/monitor.pid"


# =============================================================
#  SECTION 2 - INDICATORS (kept from original, still useful)
# =============================================================

def ema(data, period):
    if len(data) < period:
        return [None] * len(data)
    k = 2 / (period + 1)
    result = [None] * (period - 1)
    result.append(sum(data[:period]) / period)
    for p in data[period:]:
        result.append(p * k + result[-1] * (1 - k))
    return result

def rma(data, period):
    result = [None] * len(data)
    start = next((i for i, v in enumerate(data) if v is not None), None)
    if start is None or start + period > len(data):
        return result
    seeds = [v for v in data[start:start + period] if v is not None]
    if len(seeds) < period:
        return result
    result[start + period - 1] = sum(seeds) / period
    for i in range(start + period, len(data)):
        if data[i] is not None and result[i - 1] is not None:
            result[i] = (result[i - 1] * (period - 1) + data[i]) / period
    return result

def calc_atr(highs, lows, closes, period=14):
    tr = [None] + [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])) for i in range(1, len(closes))]
    return rma(tr, period)

def calc_adx(highs, lows, closes, period=14):
    plus_dm = [None] + [(highs[i] - highs[i - 1]) if (highs[i] - highs[i - 1]) > (lows[i - 1] - lows[i])
                        and (highs[i] - highs[i - 1]) > 0 else 0.0 for i in range(1, len(closes))]
    minus_dm = [None] + [(lows[i - 1] - lows[i]) if (lows[i - 1] - lows[i]) > (highs[i] - highs[i - 1])
                         and (lows[i - 1] - lows[i]) > 0 else 0.0 for i in range(1, len(closes))]
    tr = [None] + [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])) for i in range(1, len(closes))]
    tr_s = rma(tr, period)
    pdm_s = rma(plus_dm, period)
    mdm_s = rma(minus_dm, period)
    pdi_list, mdi_list, dx = [], [], []
    for ts, ps, ms in zip(tr_s, pdm_s, mdm_s):
        if None in (ts, ps, ms) or ts == 0:
            pdi_list.append(None)
            mdi_list.append(None)
            dx.append(None)
        else:
            p = 100 * ps / ts
            m = 100 * ms / ts
            pdi_list.append(p)
            mdi_list.append(m)
            dx.append(100 * abs(p - m) / (p + m) if (p + m) != 0 else 0)
    return rma(dx, period), pdi_list, mdi_list

def calc_rsi(closes, period=14):
    gains = [None] + [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [None] + [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag, al = rma(gains, period), rma(losses, period)
    return [None if g is None or l is None else (100.0 if l == 0 else 100 - 100 / (1 + g / l))
            for g, l in zip(ag, al)]

def calc_vwap(highs, lows, closes, volumes):
    result, cpv, cv = [], 0.0, 0.0
    for h, l, c, v in zip(highs, lows, closes, volumes):
        cpv += (h + l + c) / 3 * v
        cv += v
        result.append(cpv / cv if cv > 0 else c)
    return result

def safe(s, idx=-1):
    try:
        return s[idx]
    except:
        return None


# =============================================================
#  SECTION 3 - FIBONACCI ENGINE
# =============================================================

def load_fib_levels():
    today = ist_now().strftime("%Y-%m-%d")
    try:
        with open(FIB_FILE) as f:
            data = json.load(f)
        if data.get("date") == today:
            return data
    except:
        pass
    return None

def save_fib_levels(data):
    with open(FIB_FILE, "w") as f:
        json.dump(data, f, indent=2)

def compute_impulse_and_fibs(candles):
    """
    Identify the morning impulse move (9:15 - 9:45) and compute
    Fibonacci retracement + extension levels.
    """
    impulse_candles = []
    prev_day_close = None
    today = ist_now().date()

    for c in candles:
        ts = c.get("ts", "")
        if not ts:
            continue
        try:
            dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except:
            continue
        if dt.date() < today:
            prev_day_close = c["close"]
            continue
        if dt.date() != today:
            continue
        t = dt.time()
        start_t = datetime.time(IMPULSE_START_HOUR, IMPULSE_START_MIN)
        end_t = datetime.time(IMPULSE_END_HOUR, IMPULSE_END_MIN)
        if start_t <= t < end_t:
            impulse_candles.append(c)

    if len(impulse_candles) < 3:
        return None

    impulse_high = max(c["high"] for c in impulse_candles)
    impulse_low = min(c["low"] for c in impulse_candles)
    impulse_open = impulse_candles[0]["open"]
    impulse_close = impulse_candles[-1]["close"]
    impulse_range = impulse_high - impulse_low

    # Determine impulse direction
    # Use the overall move from open to close, confirmed by high/low position
    if impulse_close > impulse_open:
        direction = "BULL"
        swing_low = impulse_low
        swing_high = impulse_high
    elif impulse_close < impulse_open:
        direction = "BEAR"
        swing_low = impulse_low
        swing_high = impulse_high
    else:
        return None  # No clear direction

    # Validate impulse size
    if prev_day_close and prev_day_close > 0:
        impulse_pct = impulse_range / prev_day_close * 100
        if impulse_pct < MIN_IMPULSE_PCT or impulse_pct > MAX_IMPULSE_PCT:
            return None
    else:
        if impulse_range < MIN_IMPULSE_POINTS or impulse_range > MAX_IMPULSE_POINTS:
            return None

    # Compute Fibonacci levels
    if direction == "BULL":
        # For bullish impulse: swing_low -> swing_high
        # Retracements go DOWN from high
        fib_0   = swing_high  # 0% (top)
        fib_100 = swing_low   # 100% (bottom)
        diff = swing_high - swing_low

        fibs = {
            "fib_0":    round(fib_0, 2),
            "fib_236":  round(swing_high - diff * FIB_236, 2),
            "fib_382":  round(swing_high - diff * FIB_382, 2),
            "fib_500":  round(swing_high - diff * FIB_500, 2),
            "fib_618":  round(swing_high - diff * FIB_618, 2),
            "fib_786":  round(swing_high - diff * FIB_786, 2),
            "fib_100":  round(fib_100, 2),
            # Extensions (above swing high)
            "ext_272":  round(swing_high + diff * 0.272, 2),
            "ext_618":  round(swing_high + diff * 0.618, 2),
        }
        # Entry zone for BULL: price retraces DOWN into 38.2% - 61.8%
        entry_upper = fibs["fib_382"]
        entry_lower = fibs["fib_618"]
        sl_level = fibs["fib_786"]
        tp1 = fibs["ext_272"]
        tp2 = fibs["ext_618"]

    else:
        # For bearish impulse: swing_high -> swing_low
        # Retracements go UP from low
        fib_0   = swing_low   # 0% (bottom)
        fib_100 = swing_high  # 100% (top)
        diff = swing_high - swing_low

        fibs = {
            "fib_0":    round(fib_0, 2),
            "fib_236":  round(swing_low + diff * FIB_236, 2),
            "fib_382":  round(swing_low + diff * FIB_382, 2),
            "fib_500":  round(swing_low + diff * FIB_500, 2),
            "fib_618":  round(swing_low + diff * FIB_618, 2),
            "fib_786":  round(swing_low + diff * FIB_786, 2),
            "fib_100":  round(fib_100, 2),
            # Extensions (below swing low)
            "ext_272":  round(swing_low - diff * 0.272, 2),
            "ext_618":  round(swing_low - diff * 0.618, 2),
        }
        # Entry zone for BEAR: price retraces UP into 38.2% - 61.8%
        entry_upper = fibs["fib_618"]
        entry_lower = fibs["fib_382"]
        sl_level = fibs["fib_786"]
        tp1 = fibs["ext_272"]
        tp2 = fibs["ext_618"]

    return {
        "date": ist_now().strftime("%Y-%m-%d"),
        "direction": direction,
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
        "impulse_range": round(impulse_range, 2),
        "impulse_open": round(impulse_open, 2),
        "impulse_close": round(impulse_close, 2),
        "prev_close": round(prev_day_close, 2) if prev_day_close else None,
        "fibs": fibs,
        "entry_zone_upper": round(entry_upper, 2),
        "entry_zone_lower": round(entry_lower, 2),
        "fib_sl": round(sl_level, 2),
        "fib_tp1": round(tp1, 2),
        "fib_tp2": round(tp2, 2),
        "computed_at": ist_now().strftime("%H:%M:%S"),
    }


def check_fib_retracement(candles, fib_data):
    """
    Check if price has retraced into the golden pocket (38.2%-61.8%)
    and is showing a bounce.

    Returns signal dict.
    """
    if not fib_data or not candles:
        return {"signal": "NO_TRADE", "details": {"reason": "No data"}}

    direction = fib_data["direction"]
    entry_upper = fib_data["entry_zone_upper"]
    entry_lower = fib_data["entry_zone_lower"]
    fib_sl = fib_data["fib_sl"]
    fib_tp1 = fib_data["fib_tp1"]
    fib_tp2 = fib_data["fib_tp2"]
    fibs = fib_data["fibs"]

    details = {
        "direction": direction,
        "swing_high": fib_data["swing_high"],
        "swing_low": fib_data["swing_low"],
        "impulse_range": fib_data["impulse_range"],
        "entry_zone": "%.1f - %.1f" % (entry_lower, entry_upper),
        "fib_sl": fib_sl,
        "fib_tp1": fib_tp1,
        "fib_tp2": fib_tp2,
    }

    now = ist_now()

    # Time check
    if now.hour > NO_TRADE_AFTER_HOUR or (now.hour == NO_TRADE_AFTER_HOUR and now.minute >= NO_TRADE_AFTER_MIN):
        details["reason"] = "Past %d:%02d" % (NO_TRADE_AFTER_HOUR, NO_TRADE_AFTER_MIN)
        return {"signal": "NO_TRADE", "details": details}

    # Must be after impulse period
    impulse_end = now.replace(hour=IMPULSE_END_HOUR, minute=IMPULSE_END_MIN, second=0)
    if now < impulse_end:
        details["reason"] = "Impulse period not over (wait till %d:%02d)" % (IMPULSE_END_HOUR, IMPULSE_END_MIN)
        return {"signal": "NO_TRADE", "details": details}

    # Need enough candles for indicators
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c.get("volume", 0) for c in candles]

    if len(closes) < 30:
        details["reason"] = "Need 30 candles, have %d" % len(closes)
        return {"signal": "NO_TRADE", "details": details}

    last_close = closes[-1]
    last_high = highs[-1]
    last_low = lows[-1]
    last_open = candles[-1]["open"]
    details["close"] = round(last_close, 2)

    # COMPUTE INDICATORS
    adx_s, pdi_s, mdi_s = calc_adx(highs, lows, closes, ADX_LEN)
    adx = safe(adx_s)
    pdi = safe(pdi_s)
    mdi = safe(mdi_s)
    rsi_s = calc_rsi(closes, RSI_LEN)
    rsi = safe(rsi_s)
    atr_s = calc_atr(highs, lows, closes, ATR_LEN)
    atr = safe(atr_s)
    ema_f = ema(closes, EMA_FAST)
    ema_s_arr = ema(closes, EMA_SLOW)
    ef = safe(ema_f)
    es = safe(ema_s_arr)
    vb = min(VWAP_SESSION_BARS, len(candles))
    vwap_s = calc_vwap(highs[-vb:], lows[-vb:], closes[-vb:], volumes[-vb:])
    vwap = safe(vwap_s)

    details.update({
        "adx": round(adx, 1) if adx else "N/A",
        "rsi": round(rsi, 1) if rsi else "N/A",
        "atr": round(atr, 1) if atr else "N/A",
        "vwap": round(vwap, 2) if vwap else "N/A",
        "ema9": round(ef, 2) if ef else "N/A",
        "ema21": round(es, 2) if es else "N/A",
    })

    # ADX filter - need trending market
    if adx is not None and adx < MIN_ADX_FOR_TRADE:
        details["reason"] = "Sideways: ADX %.1f < %d" % (adx, MIN_ADX_FOR_TRADE)
        return {"signal": "NO_TRADE", "details": details}

    # ===== FIBONACCI ENTRY LOGIC =====

    # STEP 1: Check if price is in the golden pocket
    if direction == "BULL":
        # Price should retrace DOWN into zone (entry_lower < price < entry_upper)
        in_zone = entry_lower <= last_low <= entry_upper or entry_lower <= last_close <= entry_upper
        # Allow candle that wicked into zone and bounced
        touched_zone = last_low <= entry_upper  # at least touched upper boundary

        # Invalidation: price broke below 78.6% fib
        if last_close < fib_sl:
            details["reason"] = "Fib invalidated: close %.1f < 78.6%% fib %.1f" % (last_close, fib_sl)
            details["fib_state"] = "INVALIDATED"
            return {"signal": "NO_TRADE", "details": details}

        # Check if price already went past the swing high (impulse continued, no retrace)
        if last_close > fib_data["swing_high"] * 1.002:  # 0.2% buffer
            # Price never retraced, check if it's pulling back now
            # This could be a re-entry opportunity
            pass

    else:  # BEAR
        # Price should retrace UP into zone
        in_zone = entry_lower <= last_high <= entry_upper or entry_lower <= last_close <= entry_upper
        touched_zone = last_high >= entry_lower

        if last_close > fib_sl:
            details["reason"] = "Fib invalidated: close %.1f > 78.6%% fib %.1f" % (last_close, fib_sl)
            details["fib_state"] = "INVALIDATED"
            return {"signal": "NO_TRADE", "details": details}

    details["in_golden_pocket"] = in_zone
    details["touched_zone"] = touched_zone

    if not touched_zone:
        # Check if price has already retraced and bounced (we might have missed the zone)
        # Look back last 6 candles for zone touch
        zone_touched_recently = False
        for i in range(-6, 0):
            try:
                if direction == "BULL" and lows[i] <= entry_upper:
                    zone_touched_recently = True
                    break
                elif direction == "BEAR" and highs[i] >= entry_lower:
                    zone_touched_recently = True
                    break
            except IndexError:
                pass

        if not zone_touched_recently:
            details["reason"] = "Waiting for retracement into golden pocket (%.1f - %.1f)" % (entry_lower, entry_upper)
            details["fib_state"] = "WAITING_RETRACE"
            return {"signal": "NO_TRADE", "details": details}
        else:
            details["fib_state"] = "RECENT_ZONE_TOUCH"
    else:
        details["fib_state"] = "IN_ZONE" if in_zone else "ZONE_TOUCHED"

    # STEP 2: Bounce confirmation
    bounce_confirmed = False

    if direction == "BULL":
        # Need bullish candle bouncing from zone
        candle_body = last_close - last_open
        candle_range = last_high - last_low
        is_bullish = last_close > last_open

        if is_bullish and candle_range > 0:
            body_pct = candle_body / candle_range
            # Strong bounce: bullish candle with body > 45% of range
            if body_pct >= BOUNCE_MIN_BODY_PCT:
                bounce_confirmed = True
                details["bounce_type"] = "BULLISH_ENGULF"
                details["body_pct"] = round(body_pct * 100, 1)

            # Hammer pattern (long lower wick, small body at top)
            lower_wick = last_open - last_low  # since bullish
            upper_wick = last_high - last_close
            if lower_wick > candle_body * 2 and upper_wick < candle_body:
                bounce_confirmed = True
                details["bounce_type"] = "HAMMER"

        # Also check: previous candle was in zone, current bounced up
        if len(candles) >= 2 and not bounce_confirmed:
            prev = candles[-2]
            if prev["low"] <= entry_upper and last_close > prev["high"]:
                bounce_confirmed = True
                details["bounce_type"] = "PREV_CANDLE_BOUNCE"

    else:  # BEAR
        candle_body = last_open - last_close
        candle_range = last_high - last_low
        is_bearish = last_close < last_open

        if is_bearish and candle_range > 0:
            body_pct = candle_body / candle_range
            if body_pct >= BOUNCE_MIN_BODY_PCT:
                bounce_confirmed = True
                details["bounce_type"] = "BEARISH_ENGULF"
                details["body_pct"] = round(body_pct * 100, 1)

            upper_wick = last_high - last_open
            lower_wick = last_close - last_low
            if upper_wick > candle_body * 2 and lower_wick < candle_body:
                bounce_confirmed = True
                details["bounce_type"] = "SHOOTING_STAR"

        if len(candles) >= 2 and not bounce_confirmed:
            prev = candles[-2]
            if prev["high"] >= entry_lower and last_close < prev["low"]:
                bounce_confirmed = True
                details["bounce_type"] = "PREV_CANDLE_BOUNCE"

    if not bounce_confirmed:
        details["reason"] = "In zone but no bounce confirmation yet"
        details["fib_state"] = "AWAITING_BOUNCE"
        return {"signal": "NO_TRADE", "details": details}

    # STEP 3: Confluence scoring
    score = 0
    max_score = 7

    # 1. Price bounced from golden pocket
    score += 1  # Already confirmed above
    details["c1_zone_bounce"] = True

    # 2. RSI divergence / appropriate level
    if direction == "BULL" and rsi is not None:
        if 30 < rsi < 60:
            score += 1
            details["c2_rsi"] = "OK (%.0f)" % rsi
        else:
            details["c2_rsi"] = "SKIP (%.0f)" % rsi
    elif direction == "BEAR" and rsi is not None:
        if 40 < rsi < 70:
            score += 1
            details["c2_rsi"] = "OK (%.0f)" % rsi
        else:
            details["c2_rsi"] = "SKIP (%.0f)" % rsi
    else:
        details["c2_rsi"] = "N/A"

    # 3. EMA trend alignment
    if direction == "BULL" and ef is not None and es is not None:
        if ef > es:
            score += 1
            details["c3_ema"] = "ALIGNED"
        else:
            details["c3_ema"] = "COUNTER"
    elif direction == "BEAR" and ef is not None and es is not None:
        if ef < es:
            score += 1
            details["c3_ema"] = "ALIGNED"
        else:
            details["c3_ema"] = "COUNTER"
    else:
        details["c3_ema"] = "N/A"

    # 4. VWAP alignment
    if direction == "BULL" and vwap is not None:
        if last_close >= vwap * 0.998:  # Close to or above VWAP
            score += 1
            details["c4_vwap"] = "ABOVE"
        else:
            details["c4_vwap"] = "BELOW"
    elif direction == "BEAR" and vwap is not None:
        if last_close <= vwap * 1.002:
            score += 1
            details["c4_vwap"] = "BELOW"
        else:
            details["c4_vwap"] = "ABOVE"
    else:
        details["c4_vwap"] = "N/A"

    # 5. ADX strength
    if adx is not None and adx >= 20:
        score += 1
        details["c5_adx"] = "STRONG (%.0f)" % adx
    else:
        details["c5_adx"] = "WEAK (%.0f)" % (adx or 0)

    # 6. Fib level precision (bounced from deeper level = stronger)
    if direction == "BULL":
        if last_low <= fibs["fib_618"] + SL_BUFFER_POINTS:
            score += 1  # Deep retrace to 61.8% = strong
            details["c6_fib_depth"] = "61.8%% (deep)"
        elif last_low <= fibs["fib_500"] + SL_BUFFER_POINTS:
            score += 1
            details["c6_fib_depth"] = "50%% (mid)"
        else:
            details["c6_fib_depth"] = "38.2%% (shallow)"
    else:
        if last_high >= fibs["fib_618"] - SL_BUFFER_POINTS:
            score += 1
            details["c6_fib_depth"] = "61.8%% (deep)"
        elif last_high >= fibs["fib_500"] - SL_BUFFER_POINTS:
            score += 1
            details["c6_fib_depth"] = "50%% (mid)"
        else:
            details["c6_fib_depth"] = "38.2%% (shallow)"

    # 7. Volume on bounce candle vs average
    recent_volumes = [c.get("volume", 0) for c in candles[-20:]]
    avg_vol = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
    current_vol = candles[-1].get("volume", 0)
    if avg_vol > 0 and current_vol > 0:
        vol_ratio = current_vol / avg_vol
        if vol_ratio >= 1.0:
            score += 1
            details["c7_volume"] = "%.1fx avg" % vol_ratio
        else:
            details["c7_volume"] = "LOW %.1fx" % vol_ratio
    else:
        details["c7_volume"] = "N/A"

    details["confluence_score"] = "%d/%d" % (score, max_score)

    # Minimum score threshold
    min_score = 3
    is_late = now.hour >= 11
    if is_late:
        min_score = 4  # Higher bar for late entries

    if score < min_score:
        details["reason"] = "Low confluence: %d/%d (need %d)" % (score, max_score, min_score)
        return {"signal": "NO_TRADE", "details": details}

    # STEP 4: Post-direction filters

    # RSI extremes
    if direction == "BULL" and rsi is not None and rsi > 78:
        details["reason"] = "RSI overbought: %.0f" % rsi
        return {"signal": "NO_TRADE", "details": details}
    if direction == "BEAR" and rsi is not None and rsi < 22:
        details["reason"] = "RSI oversold: %.0f" % rsi
        return {"signal": "NO_TRADE", "details": details}

    # ATR-based SL sanity check (SL shouldn't be wider than 2x ATR)
    if atr is not None and atr > 0:
        if direction == "BULL":
            fib_sl_distance = last_close - fib_sl
        else:
            fib_sl_distance = fib_sl - last_close

        if fib_sl_distance > atr * 3:
            details["reason"] = "SL too wide: %.1f pts (%.1fx ATR)" % (fib_sl_distance, fib_sl_distance / atr)
            return {"signal": "NO_TRADE", "details": details}
        details["sl_atr_mult"] = round(fib_sl_distance / atr, 2)

    # FINAL OUTPUT
    confidence = "HIGH" if score >= 5 else ("MED" if score >= 4 else "LOW")
    signal_type = "CE_BUY" if direction == "BULL" else "PE_BUY"

    details["trigger"] = "FIB_RETRACE_BOUNCE"
    details["score"] = "%d/%d" % (score, max_score)

    return {
        "signal": signal_type,
        "confidence": confidence,
        "direction": direction,
        "details": details,
    }


# =============================================================
#  SECTION 4 - RISK MANAGER
# =============================================================

class RiskManager:
    def __init__(self, state):
        self.state = state

    def check_can_trade(self, groww):
        checks = [
            self._check_impulse_computed(),
            self._check_time_window(),
            self._check_max_trades(),
            self._check_daily_loss(),
            self._check_loss_streak(),
        ]
        if not PAPER_TRADE:
            checks.append(self._check_open_positions(groww))
        for passed, reason in checks:
            if not passed:
                return False, reason
        return True, "All risk checks passed"

    def _check_impulse_computed(self):
        now = ist_now()
        impulse_end = now.replace(hour=IMPULSE_END_HOUR, minute=IMPULSE_END_MIN, second=0)
        if now < impulse_end:
            return False, "Impulse forming: wait till %d:%02d" % (IMPULSE_END_HOUR, IMPULSE_END_MIN)
        return True, "Impulse period done"

    def _check_time_window(self):
        now = ist_now()
        if now.hour > NO_TRADE_AFTER_HOUR or (now.hour == NO_TRADE_AFTER_HOUR and now.minute >= NO_TRADE_AFTER_MIN):
            return False, "Past %d:%02d" % (NO_TRADE_AFTER_HOUR, NO_TRADE_AFTER_MIN)
        return True, "Time OK"

    def _check_max_trades(self):
        c = self.state.get("trade_count", 0)
        if c >= MAX_TRADES_DAY:
            return False, "MAX TRADES: %d/%d" % (c, MAX_TRADES_DAY)
        return True, "Trades %d/%d" % (c, MAX_TRADES_DAY)

    def _check_daily_loss(self):
        pnl = self.state.get("daily_pnl_rupees", 0)
        if pnl <= -MAX_DAILY_LOSS_RUPEES:
            return False, "MAX LOSS: Rs.%d" % pnl
        return True, "P&L Rs.%+.0f" % pnl

    def _check_loss_streak(self):
        losses = 0
        for t in reversed(self.state.get("trades", [])):
            if not t.get("exited"):
                continue
            if t.get("exit_pnl", 0) < 0:
                losses += 1
            else:
                break
        if losses >= MAX_CONSECUTIVE_LOSSES:
            return False, "CIRCUIT BREAKER: %d losses in a row" % losses
        return True, "Loss streak %d/%d" % (losses, MAX_CONSECUTIVE_LOSSES)

    def _check_open_positions(self, groww):
        try:
            res = groww.get_positions_for_user(segment=groww.SEGMENT_FNO)
            open_pos = [p for p in res.get("positions", [])
                        if int(p.get("quantity", 0)) != 0 and "NIFTY" in p.get("trading_symbol", "")]
            if open_pos:
                return False, "POSITION OPEN: %s" % str([p["trading_symbol"] for p in open_pos])
            return True, "No open positions"
        except Exception as e:
            return False, "POSITION CHECK FAILED: %s" % str(e)

    def check_premium_range(self, ltp):
        if not ltp or ltp <= 0:
            return False, "PREMIUM: Could not fetch"
        if ltp < MIN_OPTION_PREMIUM:
            return False, "PREMIUM TOO LOW: Rs.%s" % str(ltp)
        if ltp > MAX_OPTION_PREMIUM:
            return False, "PREMIUM TOO HIGH: Rs.%s" % str(ltp)
        return True, "Premium OK: Rs.%s" % str(ltp)

    def check_capital_exposure(self, ltp, qty):
        exposure = ltp * qty
        max_exp = CAPITAL_RUPEES * MAX_CAPITAL_EXPOSURE_PCT / 100
        pct = exposure / CAPITAL_RUPEES * 100
        if exposure > max_exp:
            return False, "EXPOSURE: Rs.%.0f (%.1f%%) > max" % (exposure, pct)
        return True, "Exposure OK: Rs.%.0f (%.1f%%)" % (exposure, pct)

    def check_spread(self, groww, symbol):
        if PAPER_TRADE:
            return True, "Spread skipped (paper)"
        try:
            q = groww.get_quote(exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_FNO, trading_symbol=symbol)
            bid = float(q.get("bid_price") or 0)
            ask = float(q.get("offer_price") or 0)
            ltp = float(q.get("last_price") or 1)
            if bid <= 0 or ask <= 0:
                return True, "Spread skipped"
            spread_pct = (ask - bid) / ltp * 100
            if spread_pct > MAX_SPREAD_PCT:
                return False, "SPREAD: %.1f%%" % spread_pct
            return True, "Spread OK: %.1f%%" % spread_pct
        except Exception as e:
            return True, "Spread skipped: %s" % str(e)


# =============================================================
#  SECTION 5 - UTILITIES
# =============================================================

def ist_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=5, minutes=30)

def is_market_hours():
    now = ist_now()
    return (now.replace(hour=9, minute=15, second=0) <= now <=
            now.replace(hour=SQUAREOFF_HOUR, minute=SQUAREOFF_MIN, second=0))

def is_squareoff_time():
    now = ist_now()
    return now.hour > SQUAREOFF_HOUR or (now.hour == SQUAREOFF_HOUR and now.minute >= SQUAREOFF_MIN)

def get_atm_strike(ltp, step=50):
    return int(round(ltp / step) * step)

def get_expiry_date():
    today = ist_now().date()
    now = ist_now()
    days_ahead = (NIFTY_EXPIRY_WEEKDAY - today.weekday()) % 7
    if days_ahead == 0:
        if now.hour > 15 or (now.hour == 15 and now.minute >= 30):
            days_ahead = 7
    return today + datetime.timedelta(days=days_ahead)

def _nse_month_code(month):
    if month <= 9:
        return str(month)
    return {10: "O", 11: "N", 12: "D"}[month]

def build_symbol(strike, opt_type, expiry=None):
    if expiry is None:
        expiry = get_expiry_date()
    yy = expiry.strftime("%y")
    m_code = _nse_month_code(expiry.month)
    dd = expiry.strftime("%d")
    return "NIFTY%s%s%s%s%s" % (yy, m_code, dd, strike, opt_type)

def fmt(p):
    return "%.2f" % p

def load_state():
    today = ist_now().strftime("%Y-%m-%d")
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
            if data.get("date") == today:
                return data
    except:
        pass
    return {"date": today, "trade_count": 0, "trades": [],
            "daily_pnl_rupees": 0.0, "last_exit_time": None}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def get_sl_percent(premium):
    if premium <= 100:
        return SL_PERCENT_LOW
    elif premium <= 250:
        return SL_PERCENT_MID
    else:
        return SL_PERCENT_HIGH

def calc_sl_tp(entry_price, qty, fib_sl_distance=None):
    """
    Calculate SL and TP.
    If fib_sl_distance is provided, use Fibonacci-derived SL.
    Otherwise fall back to percentage-based.
    """
    if fib_sl_distance and fib_sl_distance > 0:
        # Use fib-derived SL on the OPTION premium
        # Scale: if Nifty SL = X pts, option SL �X * delta
        # For ATM options, delta � 0.5, so option moves ~50% of index
        sl_drop = fib_sl_distance * 0.50  # rough delta scaling
        # But also cap by percentage
        pct_sl = entry_price * get_sl_percent(entry_price) / 100
        sl_drop = min(sl_drop, pct_sl)
    else:
        sl_pct = get_sl_percent(entry_price)
        sl_drop = entry_price * sl_pct / 100

    tp_rise = sl_drop * RR_RATIO

    # Cap risk
    if sl_drop * qty > MAX_RISK_RUPEES:
        sl_drop = MAX_RISK_RUPEES / qty
        tp_rise = sl_drop * RR_RATIO

    sl_pct = sl_drop / entry_price * 100 if entry_price > 0 else 0
    sl_price = round(max(entry_price - sl_drop, 1.0), 1)
    target_price = round(entry_price + tp_rise, 1)
    rr = tp_rise / sl_drop if sl_drop > 0 else 0

    return sl_price, target_price, sl_drop, tp_rise, sl_pct, rr

def get_catastrophic_sl(entry_price, qty):
    max_drop = CATASTROPHIC_MAX_LOSS / qty
    return round(max(entry_price - max_drop, 1.0), 1)

def estimate_roundtrip_cost(entry_price, qty):
    """Estimate total round-trip cost (Rs) for an options buy+sell.
    Includes brokerage, STT, exchange txn, GST, stamp, SEBI and slippage."""
    turnover = entry_price * qty
    brokerage = 2 * BROKERAGE_PER_ORDER
    stt = STT_SELL_PCT / 100.0 * turnover            # sell side only
    exch = EXCH_TXN_PCT / 100.0 * (turnover * 2)     # both sides
    sebi = 0.0001 / 100.0 * (turnover * 2)
    stamp = 0.003 / 100.0 * turnover                 # buy side
    gst = GST_PCT / 100.0 * (brokerage + exch + sebi)
    slippage = SLIPPAGE_PER_SIDE_PCT / 100.0 * (turnover * 2)
    return brokerage + stt + exch + sebi + stamp + gst + slippage

def net_rr_after_costs(sl_drop, tp_rise, qty, entry_price):
    """RR after deducting round-trip costs from reward and adding to risk."""
    cost = estimate_roundtrip_cost(entry_price, qty)
    net_reward = tp_rise * qty - cost
    net_risk = sl_drop * qty + cost
    if net_risk <= 0:
        return 0.0, cost, net_reward
    return net_reward / net_risk, cost, net_reward


# =============================================================
#  SECTION 6 - LOGIN (CACHED) - same as original
# =============================================================

def login():
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        if data.get("date") == ist_now().strftime("%Y-%m-%d") and data.get("token"):
            saved_at = data.get("saved_at", "")
            if saved_at:
                age_h = (ist_now() - datetime.datetime.strptime(saved_at, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600
                if age_h < 3:
                    groww = GrowwAPI(data["token"])
                    logging.info("Login OK (cached)")
                    return groww
                logging.info("Token age %.1fh - refreshing" % age_h)
    except:
        pass

    logging.info("Generating fresh token...")
    totp_code = pyotp.TOTP(GROWW_TOTP_SECRET).now()
    access_token = GrowwAPI.get_access_token(api_key=GROWW_TOTP_TOKEN, totp=totp_code)
    groww = GrowwAPI(access_token)
    with open(TOKEN_FILE, "w") as f:
        json.dump({"date": ist_now().strftime("%Y-%m-%d"), "token": access_token,
                   "saved_at": ist_now().strftime("%Y-%m-%d %H:%M:%S")}, f)
    logging.info("Login OK (fresh)")
    return groww


# =============================================================
#  SECTION 7 - FETCH CANDLES - same as original
# =============================================================

def _parse_candles(raw):
    result = []
    for c in raw:
        if len(c) < 5:
            continue
        t = c[0]
        if isinstance(t, (int, float)):
            dt = (datetime.datetime.fromtimestamp(t, datetime.timezone.utc).replace(tzinfo=None)
                  + datetime.timedelta(hours=5, minutes=30))
            ts = dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts = str(t).replace("T", " ") if t is not None else ""
        result.append({
            "ts": ts, "open": float(c[1]), "high": float(c[2]),
            "low": float(c[3]), "close": float(c[4]),
            "volume": float(c[5]) if len(c) > 5 and c[5] is not None else 0.0,
        })
    return result

def _save_candles(cache):
    try:
        with open(CANDLE_FILE, "w") as f:
            json.dump(cache, f)
    except:
        pass

def _get_nifty_quote(groww):
    try:
        q = groww.get_quote(exchange="NSE", segment="CASH", trading_symbol="NIFTY")
        if q and q.get("last_price"):
            return q
    except Exception as e:
        logging.warning("Nifty quote failed: %s" % str(e))
    return None

def fetch_candles(groww):
    now = ist_now()
    today = now.strftime("%Y-%m-%d")
    end_dt = now.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(CANDLE_FILE) as f:
            cache = json.load(f)
    except:
        cache = {"date": "", "candles": []}

    existing = cache.get("candles", [])
    is_incremental = False
    if len(existing) >= 30 and existing[-1].get("ts"):
        try:
            last_dt = datetime.datetime.strptime(existing[-1]["ts"], "%Y-%m-%d %H:%M:%S")
            if last_dt.date() == now.date():
                start_dt = (last_dt + datetime.timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
                is_incremental = True
            else:
                start_dt = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d 09:15:00")
        except:
            start_dt = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d 09:15:00")
    else:
        start_dt = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d 09:15:00")

    try:
        res = groww.get_historical_candle_data(
            trading_symbol="NIFTY", exchange="NSE", segment="CASH",
            start_time=start_dt, end_time=end_dt, interval_in_minutes=5)
        raw = res.get("candles", []) if isinstance(res, dict) else []
        if raw:
            new_candles = _parse_candles(raw)
            if is_incremental:
                existing_ts = {c["ts"] for c in existing if c.get("ts")}
                merged = existing + [c for c in new_candles if c.get("ts") not in existing_ts]
            else:
                merged = new_candles
            cache["candles"] = merged[-300:]
            cache["date"] = today
            _save_candles(cache)
            logging.info("Candles: %d (incremental=%s)" % (len(cache["candles"]), str(is_incremental)))
            return cache["candles"]
        elif is_incremental and len(existing) >= 30:
            return existing
    except Exception as e:
        logging.warning("Candle API failed: %s" % str(e))

    if existing and len(existing) >= 30:
        return existing
    return existing if existing else []


# =============================================================
#  SECTION 8 - SYMBOL RESOLUTION - same as original
# =============================================================

def get_option_ltp(groww, symbol):
    try:
        q = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=symbol)
        return float(q["last_price"])
    except Exception as e:
        logging.warning("Option LTP failed for %s: %s" % (symbol, str(e)))
        return None

def get_exchange_token(groww, trading_symbol):
    try:
        inst = groww.get_instrument_by_exchange_and_trading_symbol(
            exchange=groww.EXCHANGE_NSE, trading_symbol=trading_symbol)
        if inst:
            return str(inst.get("exchange_token", ""))
    except Exception as e:
        logging.warning("Instrument lookup failed for %s: %s" % (trading_symbol, str(e)))
    return None

def _discover_expiry_from_csv(groww, strike, opt_type):
    try:
        instruments_df = groww._load_instruments()
        mask = ((instruments_df["underlying_symbol"] == "NIFTY") &
                (instruments_df["segment"] == "FNO") &
                (instruments_df["instrument_type"] == opt_type))
        nifty_opts = instruments_df[mask].copy()
        if nifty_opts.empty:
            return None, None
        nifty_opts["strike_int"] = nifty_opts["strike_price"].apply(
            lambda x: int(float(x)) if not (isinstance(x, float) and x != x) else 0)
        strike_matches = nifty_opts[nifty_opts["strike_int"] == strike]
        if strike_matches.empty:
            return None, None
        today = ist_now().date()
        best_expiry, best_row = None, None
        for _, row in strike_matches.iterrows():
            exp_str = str(row.get("expiry_date", "")).strip()[:10]
            try:
                exp_date = datetime.datetime.strptime(exp_str, "%Y-%m-%d").date()
            except:
                continue
            if exp_date < today:
                continue
            if best_expiry is None or exp_date < best_expiry:
                best_expiry, best_row = exp_date, row
        if best_row is not None:
            return best_expiry.strftime("%Y-%m-%d"), best_row["trading_symbol"]
    except Exception as e:
        logging.warning("CSV discovery failed: %s" % str(e))
    return None, None

def _discover_expiry_from_chain(groww, strike, opt_type, calculated_expiry):
    today = ist_now().date()
    calc_str = calculated_expiry.strftime("%Y-%m-%d")
    for offset in range(0, 8):
        d = today + datetime.timedelta(days=offset)
        ds = d.strftime("%Y-%m-%d")
        if ds == calc_str:
            continue
        try:
            chain = groww.get_option_chain(exchange="NSE", underlying="NIFTY", expiry_date=ds)
            if not isinstance(chain, dict):
                continue
            strikes_data = chain.get("strikes", {})
            if not strikes_data:
                continue
            for sk in [str(strike), "%s.0" % str(strike)]:
                if sk in strikes_data and opt_type in strikes_data[sk]:
                    opt_data = strikes_data[sk][opt_type]
                    tsym = opt_data.get("trading_symbol", "")
                    ltp = float(opt_data.get("ltp", 0))
                    if tsym:
                        return ds, tsym, ltp, strikes_data
            available = [int(float(k)) for k in strikes_data if opt_type in strikes_data.get(k, {})]
            if available:
                nearest = min(available, key=lambda s: abs(s - strike))
                for sk in [str(nearest), "%s.0" % str(nearest)]:
                    if sk in strikes_data and opt_type in strikes_data[sk]:
                        opt_data = strikes_data[sk][opt_type]
                        tsym = opt_data.get("trading_symbol", "")
                        ltp = float(opt_data.get("ltp", 0))
                        if tsym:
                            return ds, tsym, ltp, strikes_data
        except:
            continue
    return None, None, None, None

def get_valid_option_symbol(groww, strike, opt_type):
    expiry = get_expiry_date()
    expiry_str = expiry.strftime("%Y-%m-%d")
    logging.info("Resolving: %d %s exp=%s" % (strike, opt_type, expiry_str))

    sym = build_symbol(strike, opt_type, expiry)
    try:
        q = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=sym)
        ltp = float(q.get("last_price", 0))
        if ltp > 0:
            logging.info("OK (direct): %s Rs.%s" % (sym, str(ltp)))
            return sym, ltp
    except Exception as e:
        logging.warning("Direct %s failed: %s" % (sym, str(e)))

    chain_found = False
    try:
        chain = groww.get_option_chain(exchange="NSE", underlying="NIFTY", expiry_date=expiry_str)
        if isinstance(chain, dict):
            strikes_data = chain.get("strikes", {})
            if strikes_data:
                chain_found = True
                for sk in [str(strike), "%s.0" % str(strike)]:
                    if sk in strikes_data and opt_type in strikes_data[sk]:
                        opt_data = strikes_data[sk][opt_type]
                        tsym = opt_data.get("trading_symbol", "")
                        ltp = float(opt_data.get("ltp", 0))
                        if tsym:
                            if ltp <= 0:
                                try:
                                    q2 = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=tsym)
                                    ltp = float(q2.get("last_price", 0))
                                except:
                                    pass
                            return tsym, ltp
                available = sorted([int(float(k)) for k in strikes_data if opt_type in strikes_data.get(k, {})])
                if available:
                    nearest = min(available, key=lambda s: abs(s - strike))
                    for sk in [str(nearest), "%s.0" % str(nearest)]:
                        if sk in strikes_data and opt_type in strikes_data[sk]:
                            opt_data = strikes_data[sk][opt_type]
                            tsym = opt_data.get("trading_symbol", "")
                            ltp = float(opt_data.get("ltp", 0))
                            if tsym:
                                if ltp <= 0:
                                    try:
                                        q2 = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=tsym)
                                        ltp = float(q2.get("last_price", 0))
                                    except:
                                        pass
                                return tsym, ltp
    except Exception as e:
        logging.error("Chain failed: %s" % str(e))

    if not chain_found:
        disc_expiry, disc_sym, disc_ltp, _ = _discover_expiry_from_chain(groww, strike, opt_type, expiry)
        if disc_sym:
            if disc_ltp <= 0:
                try:
                    q2 = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=disc_sym)
                    disc_ltp = float(q2.get("last_price", 0))
                except:
                    pass
            return disc_sym, disc_ltp

    csv_expiry, csv_sym = _discover_expiry_from_csv(groww, strike, opt_type)
    if csv_sym:
        try:
            q = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=csv_sym)
            ltp = float(q.get("last_price", 0))
            if ltp > 0:
                return csv_sym, ltp
        except:
            pass
        return csv_sym, 0

    logging.error("ALL FAILED: %d %s" % (strike, opt_type))
    return None, None


# =============================================================
#  SECTION 9 - ORDERS
# =============================================================

def place_entry_order(groww, symbol, qty, txn):
    if PAPER_TRADE:
        fake_id = "PAPER-%s" % ist_now().strftime("%H%M%S")
        logging.info("PAPER ENTRY | %s | Qty:%d | ID:%s" % (symbol, qty, fake_id))
        return fake_id
    try:
        res = groww.place_order(
            trading_symbol=symbol, quantity=qty, validity=groww.VALIDITY_DAY,
            exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_FNO,
            product=groww.PRODUCT_MIS, order_type=groww.ORDER_TYPE_MARKET,
            transaction_type=txn,
            order_reference_id="FIB%s" % ist_now().strftime("%H%M%S"))
        oid = res.get("groww_order_id", "N/A")
        logging.info("ENTRY | %s | Qty:%d | ID:%s" % (symbol, qty, oid))
        return oid
    except Exception as e:
        logging.error("ENTRY FAILED: %s" % str(e))
        return None

def place_exit_order(groww, symbol, qty, reason):
    if PAPER_TRADE:
        logging.info("PAPER EXIT | %s | Qty:%d | %s" % (symbol, qty, reason))
        return True
    try:
        groww.place_order(
            trading_symbol=symbol, quantity=qty, validity=groww.VALIDITY_DAY,
            exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_FNO,
            product=groww.PRODUCT_MIS, order_type=groww.ORDER_TYPE_MARKET,
            transaction_type=groww.TRANSACTION_TYPE_SELL)
        logging.info("EXIT | %s | Qty:%d | %s" % (symbol, qty, reason))
        return True
    except Exception as e:
        logging.error("EXIT FAILED: %s" % str(e))
        return False

def cancel_and_squareoff(groww, state):
    if PAPER_TRADE:
        logging.info("PAPER SQUAREOFF")
        trades = state.get("trades", [])
        logging.info("SUMMARY | Trades:%d | P&L:Rs.%+.0f" % (len(trades), state.get("daily_pnl_rupees", 0)))
        return
    logging.info("EOD SQUAREOFF")
    try:
        now = ist_now()
        res = groww.get_smart_order_list(
            segment=groww.SEGMENT_FNO, smart_order_type=groww.SMART_ORDER_TYPE_OCO,
            status=groww.SMART_ORDER_STATUS_ACTIVE, page=0, page_size=50,
            start_date_time=now.replace(hour=9, minute=0).strftime("%Y-%m-%dT%H:%M:%S"),
            end_date_time=now.strftime("%Y-%m-%dT%H:%M:%S"))
        for o in res.get("orders", []):
            sid = o.get("smart_order_id")
            if sid and "NIFTY" in o.get("trading_symbol", ""):
                groww.cancel_smart_order(smart_order_id=sid, segment=groww.SEGMENT_FNO,
                    smart_order_type=groww.SMART_ORDER_TYPE_OCO)
                logging.info("Cancelled OCO: %s" % sid)
    except Exception as e:
        logging.error("OCO cancel error: %s" % str(e))
    try:
        positions = groww.get_positions_for_user(segment=groww.SEGMENT_FNO).get("positions", [])
        for pos in positions:
            sym = pos.get("trading_symbol", "")
            qty = int(pos.get("quantity", 0))
            if qty != 0 and "NIFTY" in sym:
                side = groww.TRANSACTION_TYPE_SELL if qty > 0 else groww.TRANSACTION_TYPE_BUY
                groww.place_order(trading_symbol=sym, quantity=abs(qty),
                    validity=groww.VALIDITY_DAY, exchange=groww.EXCHANGE_NSE,
                    segment=groww.SEGMENT_FNO, product=groww.PRODUCT_MIS,
                    order_type=groww.ORDER_TYPE_MARKET, transaction_type=side)
                logging.info("Closed: %s Qty:%d" % (sym, abs(qty)))
    except Exception as e:
        logging.error("Squareoff error: %s" % str(e))
    trades = state.get("trades", [])
    logging.info("SUMMARY | Trades:%d | P&L:Rs.%+.0f" % (len(trades), state.get("daily_pnl_rupees", 0)))


# =============================================================
#  SECTION 10 - WEBSOCKET MONITOR (with partial profit)
# =============================================================

def write_monitor_pid():
    with open(MONITOR_PID, "w") as f:
        f.write(str(os.getpid()))

def clear_monitor_pid():
    try:
        os.remove(MONITOR_PID)
    except:
        pass

def is_monitor_running():
    try:
        with open(MONITOR_PID) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ValueError):
        return False
    except ProcessLookupError:
        clear_monitor_pid()
        return False
    except PermissionError:
        return True

def run_websocket_monitor(groww, state):
    trades = state.get("trades", [])
    if not trades:
        logging.error("WS Monitor: No trades found")
        return

    trade = trades[-1]
    if trade.get("exited", False):
        logging.info("WS Monitor: Trade already exited")
        return

    symbol = trade["symbol"]
    qty = trade["qty"]
    remaining_qty = trade.get("remaining_qty", qty)
    entry_premium = trade["entry_premium"]
    entry_time = datetime.datetime.strptime(trade["time"], "%Y-%m-%d %H:%M:%S")

    sl_price, target_price, sl_drop, tp_rise, sl_pct, actual_rr = calc_sl_tp(
        entry_premium, qty, trade.get("fib_sl_distance"))
    catastrophic_sl = get_catastrophic_sl(entry_premium, qty)

    # Partial profit target
    partial_target = round(entry_premium + sl_drop * PARTIAL_TARGET_RR, 1) if PARTIAL_EXIT_ENABLED else None
    partial_qty = int(remaining_qty * PARTIAL_EXIT_PCT / 100)
    partial_qty = max(partial_qty, LOT_SIZE)  # At least 1 lot
    if partial_qty >= remaining_qty:
        partial_qty = 0  # Can't partial if only 1 lot

    logging.info("=== WS MONITOR START (FIBONACCI) ===")
    logging.info("  Symbol: %s | Qty: %d" % (symbol, remaining_qty))
    logging.info("  Entry: Rs.%.1f" % entry_premium)
    logging.info("  SL: Rs.%.1f (-%.1f%%) | Target: Rs.%.1f (+%.1f%%)" % (
        sl_price, sl_pct, target_price, tp_rise / entry_premium * 100))
    logging.info("  Risk: Rs.%.0f | Reward: Rs.%.0f | RR 1:%.1f" % (
        sl_drop * remaining_qty, tp_rise * remaining_qty, actual_rr))
    logging.info("  Hold: %d min | Catastrophic SL: Rs.%.1f" % (MIN_HOLD_MINUTES, catastrophic_sl))
    if partial_target and partial_qty > 0:
        logging.info("  Partial: %d qty at Rs.%.1f (1:%.1f RR)" % (
            partial_qty, partial_target, PARTIAL_TARGET_RR))

    write_monitor_pid()

    exchange_token = get_exchange_token(groww, symbol)
    if not exchange_token:
        logging.error("Cannot get exchange_token for %s - falling back to polling" % symbol)
        _fallback_polling_monitor(groww, state, trade)
        return

    logging.info("  Exchange token: %s" % exchange_token)

    monitor_state = {
        "exited": False,
        "last_log_time": time.time(),
        "last_heartbeat": time.time(),
        "last_ltp": None,
        "trailing_sl": sl_price,
        "highest_ltp": entry_premium,
        "remaining_qty": remaining_qty,
        "partial_done": trade.get("partial_done", False),
    }

    feed = GrowwFeed(groww)

    instrument_list = [{
        "exchange": "NSE",
        "segment": "FNO",
        "exchange_token": exchange_token,
    }]

    def on_tick(meta):
        if monitor_state["exited"]:
            return

        now_ts = time.time()

        try:
            ltp_data = feed.get_ltp()
            if not ltp_data:
                return

            current_ltp = 0
            ltp_root = ltp_data.get("ltp", ltp_data) if isinstance(ltp_data, dict) else {}

            if isinstance(ltp_root, dict):
                nse = ltp_root.get("NSE", {})
                if isinstance(nse, dict):
                    fno = nse.get("FNO", {})
                    if isinstance(fno, dict):
                        token_data = fno.get(exchange_token, {})
                        if isinstance(token_data, dict):
                            current_ltp = float(token_data.get("ltp", 0))
                        elif token_data:
                            current_ltp = float(token_data)

            if current_ltp <= 0:
                return

        except Exception as e:
            logging.warning("WS tick parse error: %s" % str(e))
            return

        monitor_state["last_ltp"] = current_ltp
        r_qty = monitor_state["remaining_qty"]

        # Log
        if now_ts - monitor_state["last_log_time"] >= WS_TICK_LOG_INTERVAL:
            pnl = (current_ltp - entry_premium) * r_qty
            pnl_pct = (current_ltp - entry_premium) / entry_premium * 100
            logging.info("  TICK | LTP:%.1f | P&L:Rs.%+.0f (%+.1f%%) | SL:%.1f | T:%.1f | Qty:%d" % (
                current_ltp, pnl, pnl_pct, monitor_state["trailing_sl"], target_price, r_qty))
            monitor_state["last_log_time"] = now_ts

        # Heartbeat
        if now_ts - monitor_state["last_heartbeat"] >= WS_HEARTBEAT_SEC:
            logging.info("  HEARTBEAT | LTP:%.1f | Qty:%d" % (current_ltp, r_qty))
            monitor_state["last_heartbeat"] = now_ts

        # EOD squareoff
        now_ist = ist_now()
        if now_ist.hour > SQUAREOFF_HOUR or (now_ist.hour == SQUAREOFF_HOUR and now_ist.minute >= SQUAREOFF_MIN):
            pnl = (current_ltp - entry_premium) * r_qty
            _do_exit(current_ltp, pnl, "EOD SQUAREOFF Rs.%+.0f" % pnl, r_qty)
            return

        # PARTIAL PROFIT
        if (PARTIAL_EXIT_ENABLED and not monitor_state["partial_done"]
                and partial_target and partial_qty > 0
                and current_ltp >= partial_target):
            pnl_partial = (current_ltp - entry_premium) * partial_qty
            logging.info("=== PARTIAL EXIT ===")
            logging.info("  LTP:%.1f | Qty:%d | P&L:Rs.%+.0f" % (current_ltp, partial_qty, pnl_partial))
            place_exit_order(groww, symbol, partial_qty, "PARTIAL TP Rs.%+.0f" % pnl_partial)
            monitor_state["partial_done"] = True
            monitor_state["remaining_qty"] -= partial_qty
            # Move SL to breakeven after partial
            monitor_state["trailing_sl"] = max(monitor_state["trailing_sl"], entry_premium)
            logging.info("  Remaining: %d | SL moved to breakeven: Rs.%.1f" % (
                monitor_state["remaining_qty"], monitor_state["trailing_sl"]))
            trade["partial_done"] = True
            trade["partial_pnl"] = round(pnl_partial, 2)
            trade["remaining_qty"] = monitor_state["remaining_qty"]
            state["daily_pnl_rupees"] = state.get("daily_pnl_rupees", 0) + pnl_partial
            save_state(state)
            return

        # TAKE PROFIT (full target on remaining qty)
        if current_ltp >= target_price:
            pnl = (current_ltp - entry_premium) * r_qty
            _do_exit(current_ltp, pnl, "TAKE PROFIT Rs.%+.0f" % pnl, r_qty)
            return

        # Hold period check
        minutes_held = (now_ist - entry_time).total_seconds() / 60

        # DURING HOLD: only catastrophic SL
        if minutes_held < MIN_HOLD_MINUTES:
            if current_ltp <= catastrophic_sl:
                pnl = (current_ltp - entry_premium) * r_qty
                _do_exit(current_ltp, pnl, "CATASTROPHIC SL Rs.%+.0f" % pnl, r_qty)
            return

        # STAGNATION EXIT: cut dead trades to stop theta bleed
        if STAGNATION_EXIT_ENABLED and minutes_held >= STAGNATION_EXIT_MIN \
                and (current_ltp - entry_premium) < sl_drop * STAGNATION_MIN_PROFIT_RR:
            pnl = (current_ltp - entry_premium) * r_qty
            _do_exit(current_ltp, pnl, "STAGNATION EXIT Rs.%+.0f" % pnl, r_qty)
            return

        # AFTER HOLD: trailing SL
        if TRAILING_SL_ENABLED and current_ltp > monitor_state["highest_ltp"]:
            monitor_state["highest_ltp"] = current_ltp
            profit = current_ltp - entry_premium
            if profit >= tp_rise * TRAILING_SL_TRIGGER:
                new_sl = round(entry_premium + (profit * TRAILING_SL_STEP), 1)
                if new_sl > monitor_state["trailing_sl"]:
                    old_sl = monitor_state["trailing_sl"]
                    monitor_state["trailing_sl"] = new_sl
                    logging.info("  TRAIL SL: Rs.%.1f -> Rs.%.1f" % (old_sl, new_sl))

        # STOP LOSS
        if current_ltp <= monitor_state["trailing_sl"]:
            pnl = (current_ltp - entry_premium) * r_qty
            _do_exit(current_ltp, pnl, "STOP LOSS Rs.%+.0f" % pnl, r_qty)
            return

    def _do_exit(current_ltp, pnl, reason, exit_qty):
        if monitor_state["exited"]:
            return
        monitor_state["exited"] = True

        logging.info("=== EXIT ===")
        logging.info("  %s" % reason)
        logging.info("  LTP:%.1f | Entry:%.1f | P&L:Rs.%+.0f | Qty:%d" % (
            current_ltp, entry_premium, pnl, exit_qty))

        place_exit_order(groww, symbol, exit_qty, reason)

        trade["exited"] = True
        trade["exit_ltp"] = current_ltp
        trade["exit_pnl"] = round(pnl + trade.get("partial_pnl", 0), 2)
        trade["exit_reason"] = reason
        trade["exit_time"] = ist_now().strftime("%Y-%m-%d %H:%M:%S")
        state["daily_pnl_rupees"] = state.get("daily_pnl_rupees", 0) + pnl
        save_state(state)

        try:
            feed.unsubscribe_ltp(instrument_list)
        except:
            pass
        clear_monitor_pid()

        logging.info("  Daily P&L: Rs.%+.0f" % state["daily_pnl_rupees"])
        logging.info("=== WS MONITOR END ===")

    def handle_shutdown(signum, frame):
        logging.info("WS Monitor: Shutdown signal")
        if not monitor_state["exited"]:
            final_ltp = monitor_state.get("last_ltp") or entry_premium
            r_qty = monitor_state["remaining_qty"]
            if final_ltp > 0:
                pnl = (final_ltp - entry_premium) * r_qty
                _do_exit(final_ltp, pnl, "SHUTDOWN Rs.%+.0f" % pnl, r_qty)
        clear_monitor_pid()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    logging.info("  Subscribing to %s (token: %s)..." % (symbol, exchange_token))

    try:
        feed.subscribe_ltp(instrument_list, on_data_received=on_tick)
        logging.info("  WebSocket connected - monitoring live")
        feed.consume()
    except KeyboardInterrupt:
        handle_shutdown(None, None)
    except Exception as e:
        logging.error("WS Monitor crashed: %s" % str(e))
        if not monitor_state["exited"]:
            logging.info("Falling back to polling...")
            _fallback_polling_monitor(groww, state, trade)
    finally:
        clear_monitor_pid()


def _fallback_polling_monitor(groww, state, trade):
    symbol = trade["symbol"]
    qty = trade["qty"]
    remaining_qty = trade.get("remaining_qty", qty)
    entry_premium = trade["entry_premium"]
    entry_time = datetime.datetime.strptime(trade["time"], "%Y-%m-%d %H:%M:%S")

    sl_price, target_price, sl_drop, tp_rise, sl_pct, rr = calc_sl_tp(
        entry_premium, qty, trade.get("fib_sl_distance"))
    catastrophic_sl = get_catastrophic_sl(entry_premium, qty)

    partial_target = round(entry_premium + sl_drop * PARTIAL_TARGET_RR, 1) if PARTIAL_EXIT_ENABLED else None
    partial_qty = int(remaining_qty * PARTIAL_EXIT_PCT / 100)
    partial_qty = max(partial_qty, LOT_SIZE)
    if partial_qty >= remaining_qty:
        partial_qty = 0

    trailing_sl = sl_price
    highest_ltp = entry_premium
    partial_done = trade.get("partial_done", False)

    logging.info("POLL MONITOR | %s | SL:%.1f | T:%.1f | Cat:%.1f" % (
        symbol, sl_price, target_price, catastrophic_sl))
    write_monitor_pid()

    last_log = 0

    try:
        while True:
            now = ist_now()

            # EOD squareoff
            if now.hour > SQUAREOFF_HOUR or (now.hour == SQUAREOFF_HOUR and now.minute >= SQUAREOFF_MIN):
                current_ltp = get_option_ltp(groww, symbol) or entry_premium
                pnl = (current_ltp - entry_premium) * remaining_qty
                place_exit_order(groww, symbol, remaining_qty, "EOD SQUAREOFF Rs.%+.0f" % pnl)
                trade["exited"] = True
                trade["exit_ltp"] = current_ltp
                trade["exit_pnl"] = round(pnl + trade.get("partial_pnl", 0), 2)
                trade["exit_reason"] = "EOD_SQUAREOFF"
                trade["exit_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
                state["daily_pnl_rupees"] = state.get("daily_pnl_rupees", 0) + pnl
                save_state(state)
                break

            current_ltp = get_option_ltp(groww, symbol)
            if current_ltp is None:
                time.sleep(5)
                continue

            pnl = (current_ltp - entry_premium) * remaining_qty
            minutes_held = (now - entry_time).total_seconds() / 60

            now_ts = time.time()
            if now_ts - last_log >= 30:
                logging.info("  POLL | LTP:%.1f | P&L:%+.0f | SL:%.1f T:%.1f | Hold:%.0fm | Qty:%d" % (
                    current_ltp, pnl, trailing_sl, target_price, minutes_held, remaining_qty))
                last_log = now_ts

            # Partial profit
            if (PARTIAL_EXIT_ENABLED and not partial_done
                    and partial_target and partial_qty > 0
                    and current_ltp >= partial_target):
                pnl_partial = (current_ltp - entry_premium) * partial_qty
                place_exit_order(groww, symbol, partial_qty, "PARTIAL TP Rs.%+.0f" % pnl_partial)
                partial_done = True
                remaining_qty -= partial_qty
                trailing_sl = max(trailing_sl, entry_premium)
                trade["partial_done"] = True
                trade["partial_pnl"] = round(pnl_partial, 2)
                trade["remaining_qty"] = remaining_qty
                state["daily_pnl_rupees"] = state.get("daily_pnl_rupees", 0) + pnl_partial
                save_state(state)
                logging.info("  PARTIAL: %d qty | Remaining: %d | SL->BE: %.1f" % (
                    partial_qty, remaining_qty, trailing_sl))
                time.sleep(2)
                continue

            # TP
            if current_ltp >= target_price:
                place_exit_order(groww, symbol, remaining_qty, "TP Rs.%+.0f" % pnl)
                trade["exited"] = True
                trade["exit_ltp"] = current_ltp
                trade["exit_pnl"] = round(pnl + trade.get("partial_pnl", 0), 2)
                trade["exit_reason"] = "TAKE_PROFIT"
                trade["exit_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
                state["daily_pnl_rupees"] = state.get("daily_pnl_rupees", 0) + pnl
                save_state(state)
                break

            # During hold: only catastrophic SL
            if minutes_held < MIN_HOLD_MINUTES:
                if current_ltp <= catastrophic_sl:
                    place_exit_order(groww, symbol, remaining_qty, "CATASTROPHIC SL Rs.%+.0f" % pnl)
                    trade["exited"] = True
                    trade["exit_ltp"] = current_ltp
                    trade["exit_pnl"] = round(pnl + trade.get("partial_pnl", 0), 2)
                    trade["exit_reason"] = "CATASTROPHIC_SL"
                    trade["exit_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
                    state["daily_pnl_rupees"] = state.get("daily_pnl_rupees", 0) + pnl
                    save_state(state)
                    break
                time.sleep(5)
                continue

            # Stagnation exit: cut dead trades to stop theta bleed
            if STAGNATION_EXIT_ENABLED and minutes_held >= STAGNATION_EXIT_MIN \
                    and (current_ltp - entry_premium) < sl_drop * STAGNATION_MIN_PROFIT_RR:
                place_exit_order(groww, symbol, remaining_qty, "STAGNATION EXIT Rs.%+.0f" % pnl)
                trade["exited"] = True
                trade["exit_ltp"] = current_ltp
                trade["exit_pnl"] = round(pnl + trade.get("partial_pnl", 0), 2)
                trade["exit_reason"] = "STAGNATION_EXIT"
                trade["exit_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
                state["daily_pnl_rupees"] = state.get("daily_pnl_rupees", 0) + pnl
                save_state(state)
                break

            # After hold: trailing SL
            if TRAILING_SL_ENABLED and current_ltp > highest_ltp:
                highest_ltp = current_ltp
                profit = current_ltp - entry_premium
                if profit >= tp_rise * TRAILING_SL_TRIGGER:
                    new_sl = round(entry_premium + (profit * TRAILING_SL_STEP), 1)
                    if new_sl > trailing_sl:
                        logging.info("  TRAIL SL: Rs.%.1f -> Rs.%.1f" % (trailing_sl, new_sl))
                        trailing_sl = new_sl

            # Stop loss
            if current_ltp <= trailing_sl:
                place_exit_order(groww, symbol, remaining_qty, "SL Rs.%+.0f" % pnl)
                trade["exited"] = True
                trade["exit_ltp"] = current_ltp
                trade["exit_pnl"] = round(pnl + trade.get("partial_pnl", 0), 2)
                trade["exit_reason"] = "STOP_LOSS"
                trade["exit_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
                state["daily_pnl_rupees"] = state.get("daily_pnl_rupees", 0) + pnl
                save_state(state)
                break

            time.sleep(5)

    except Exception as e:
        logging.error("Polling error: %s" % str(e))
    finally:
        clear_monitor_pid()


# =============================================================
#  SECTION 11 - MAIN
# =============================================================

def main():
    run_mode = sys.argv[1] if len(sys.argv) > 1 else "scan"

    # MODE: monitor
    if run_mode == "monitor":
        logging.info("=== MONITOR MODE (FIBONACCI) ===")
        state = load_state()
        trades = state.get("trades", [])
        if not trades or trades[-1].get("exited", False):
            logging.info("No active trade to monitor")
            return
        groww = login()
        run_websocket_monitor(groww, state)
        return

    # MODE: scan (default)
    now = ist_now()
    state = load_state()

    if is_monitor_running():
        logging.info("[%s] Monitor active. Skip scan." % now.strftime("%H:%M"))
        return

    trades = state.get("trades", [])
    if trades and not trades[-1].get("exited", False):
        logging.info("Found unexited trade - restarting monitor...")
        _spawn_monitor()
        return

    if not is_market_hours() and not is_squareoff_time():
        logging.info("[%s] Outside hours. Skip." % now.strftime("%H:%M"))
        return

    if state.get("trade_count", 0) >= MAX_TRADES_DAY and not is_squareoff_time():
        logging.info("[%s] Already traded %d/%d. Skip." % (now.strftime("%H:%M"), state["trade_count"], MAX_TRADES_DAY))
        return

    past_cutoff = now.hour > NO_TRADE_AFTER_HOUR or (now.hour == NO_TRADE_AFTER_HOUR and now.minute >= NO_TRADE_AFTER_MIN)
    if past_cutoff and not is_squareoff_time():
        logging.info("[%s] Past cutoff. Waiting for squareoff." % now.strftime("%H:%M"))
        return

    mode_tag = "PAPER" if PAPER_TRADE else "LIVE"
    logging.info("=== %s SCAN (FIBONACCI) | %s | Trades:%d/%d | P&L:Rs.%+.0f ===" % (
        mode_tag, now.strftime("%Y-%m-%d %H:%M:%S"),
        state["trade_count"], MAX_TRADES_DAY,
        state.get("daily_pnl_rupees", 0)))

    groww = login()

    if is_squareoff_time():
        cancel_and_squareoff(groww, state)
        return

    candles = fetch_candles(groww)
    if not candles:
        logging.error("No candles")
        return

    # COMPUTE FIBONACCI LEVELS
    fib_data = load_fib_levels()
    if fib_data is None:
        if ist_now() < ist_now().replace(hour=IMPULSE_END_HOUR, minute=IMPULSE_END_MIN, second=0):
            logging.info("Impulse forming (9:15-9:45)...")
            return
        fib_data = compute_impulse_and_fibs(candles)
        if fib_data is None:
            logging.error("Cannot compute Fibonacci levels (impulse too small/no direction)")
            return
        save_fib_levels(fib_data)
        logging.info("FIB LEVELS | Dir:%s | Swing:%.1f-%.1f | Range:%.1f" % (
            fib_data["direction"], fib_data["swing_low"], fib_data["swing_high"],
            fib_data["impulse_range"]))
        logging.info("  Golden Pocket: %.1f - %.1f" % (
            fib_data["entry_zone_lower"], fib_data["entry_zone_upper"]))
        logging.info("  SL: %.1f | TP1: %.1f | TP2: %.1f" % (
            fib_data["fib_sl"], fib_data["fib_tp1"], fib_data["fib_tp2"]))

    # CHECK FOR FIBONACCI SIGNAL
    result = check_fib_retracement(candles, fib_data)
    signal_type = result["signal"]
    confidence = result.get("confidence")
    d = result.get("details", {})

    logging.info("  Signal:%s | Conf:%s | State:%s" % (
        signal_type, str(confidence), d.get("fib_state", "--")))
    logging.info("  Close:%s | Zone:%s | Score:%s" % (
        d.get("close", "--"), d.get("entry_zone", "--"), d.get("confluence_score", "--")))
    if d.get("bounce_type"):
        logging.info("  Bounce: %s" % d["bounce_type"])
    if d.get("reason"):
        logging.info("  -> %s" % d["reason"])

    if signal_type == "NO_TRADE":
        return
    if confidence not in ("HIGH", "MED"):
        logging.info("  -> %s confidence - skip" % str(confidence))
        return

    risk = RiskManager(state)
    ok, reason = risk.check_can_trade(groww)
    if not ok:
        logging.warning("BLOCKED: %s" % reason)
        return
    logging.info("Risk OK: %s" % reason)

    opt_type = "CE" if "CE" in signal_type else "PE"
    q = _get_nifty_quote(groww)
    if q is None:
        logging.error("No Nifty LTP")
        return
    nifty_ltp = float(q["last_price"])
    atm = get_atm_strike(nifty_ltp)
    strike = (atm - ITM_OFFSET) if opt_type == "CE" else (atm + ITM_OFFSET)
    qty = LOT_SIZE * LOTS_TO_TRADE

    symbol, option_ltp = get_valid_option_symbol(groww, strike, opt_type)
    if symbol is None:
        logging.warning("ITM %d failed, trying ATM %d" % (strike, atm))
        symbol, option_ltp = get_valid_option_symbol(groww, atm, opt_type)
        if symbol is None:
            logging.error("Cannot resolve symbol")
            return
        strike = atm

    logging.info("Resolved: %s | Rs.%s | Nifty:%s" % (symbol, str(option_ltp), str(nifty_ltp)))

    for check_fn, args in [
        (risk.check_spread, (groww, symbol)),
        (risk.check_premium_range, (option_ltp,)),
        (risk.check_capital_exposure, (option_ltp, qty)),
    ]:
        ok, msg = check_fn(*args)
        if not ok:
            logging.warning("BLOCKED: %s" % msg)
            return
        logging.info(msg)

    # Compute fib-based SL distance on Nifty (for option SL scaling)
    fib_sl_distance = None
    if fib_data:
        direction = fib_data["direction"]
        last_close = candles[-1]["close"]
        if direction == "BULL":
            fib_sl_distance = last_close - fib_data["fib_sl"]
        else:
            fib_sl_distance = fib_data["fib_sl"] - last_close
        if fib_sl_distance <= 0:
            fib_sl_distance = None

    # -- SL / TARGET --
    sl_price, target_price, sl_drop, tp_rise, sl_pct, rr = calc_sl_tp(option_ltp, qty, fib_sl_distance)
    catastrophic_sl = get_catastrophic_sl(option_ltp, qty)

    if rr < MIN_RR_RATIO:
        logging.warning("RR %.1f < %.1f minimum - REJECTED" % (rr, MIN_RR_RATIO))
        return

    # Cost-aware gate: must clear brokerage + STT + slippage
    net_rr, rt_cost, net_reward = net_rr_after_costs(sl_drop, tp_rise, qty, option_ltp)
    if net_reward <= 0 or net_rr < MIN_NET_RR:
        logging.warning("COST GATE: net RR %.2f < %.1f (cost Rs.%.0f, net reward Rs.%.0f) - REJECTED" % (
            net_rr, MIN_NET_RR, rt_cost, net_reward))
        return
    logging.info("Cost gate OK: net RR %.2f (round-trip cost Rs.%.0f)" % (net_rr, rt_cost))

    total_risk = sl_drop * qty
    total_reward = tp_rise * qty

    logging.info("PLAN | Entry:~Rs.%s | Fib SL dist: %s pts" % (
        str(option_ltp), str(round(fib_sl_distance, 1)) if fib_sl_distance else "N/A"))
    logging.info("      SL:Rs.%s (-%.1f%%) | Target:Rs.%s (+%.1f%%)" % (
        str(sl_price), sl_pct, str(target_price), tp_rise / option_ltp * 100))
    logging.info("      Risk:Rs.%.0f | Reward:Rs.%.0f | RR 1:%.1f" % (total_risk, total_reward, rr))
    logging.info("      Hold:%dmin | Catastrophic SL:Rs.%.1f" % (MIN_HOLD_MINUTES, catastrophic_sl))

    # -- EXECUTE ENTRY --
    oid = place_entry_order(groww, symbol, qty, groww.TRANSACTION_TYPE_BUY)
    if not oid:
        return

    time.sleep(1)

    if PAPER_TRADE:
        entry_premium = option_ltp
    else:
        entry_premium = get_option_ltp(groww, symbol) or option_ltp

    sl_price, target_price, sl_drop, tp_rise, sl_pct, rr = calc_sl_tp(entry_premium, qty, fib_sl_distance)

    # -- SAVE TRADE --
    state["trade_count"] += 1
    state["trades"].append({
        "signal": signal_type, "confidence": confidence,
        "symbol": symbol, "qty": qty, "remaining_qty": qty,
        "entry_id": str(oid),
        "entry_premium": entry_premium,
        "risk_premium": sl_drop,
        "target_premium": tp_rise,
        "sl_percent": sl_pct,
        "rr_ratio": rr,
        "target": target_price, "sl": sl_price,
        "nifty_ltp": nifty_ltp, "strike": strike,
        "fib_direction": fib_data["direction"],
        "fib_swing_high": fib_data["swing_high"],
        "fib_swing_low": fib_data["swing_low"],
        "fib_entry_zone": d.get("entry_zone", ""),
        "fib_sl_level": fib_data["fib_sl"],
        "fib_sl_distance": fib_sl_distance,
        "bounce_type": d.get("bounce_type", ""),
        "confluence_score": d.get("confluence_score", ""),
        "trigger": "FIB_RETRACE_BOUNCE",
        "rr": "1:%.1f" % rr,
        "paper": PAPER_TRADE,
        "exited": False,
        "partial_done": False,
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
    })
    save_state(state)

    tag = "PAPER TRADE" if PAPER_TRADE else "LIVE TRADE"
    logging.info("%s | %s %s | %s" % (tag, signal_type, str(confidence), symbol))
    logging.info("   E:Rs.%s SL:Rs.%s(-%.1f%%) T:Rs.%s RR:1:%.1f" % (
        str(entry_premium), str(sl_price), sl_pct, str(target_price), rr))
    logging.info("   Bounce:%s | Score:%s" % (d.get("bounce_type", ""), d.get("confluence_score", "")))

    # -- LAUNCH WEBSOCKET MONITOR --
    _spawn_monitor()


def _spawn_monitor():
    import subprocess
    script_path = os.path.abspath(__file__)
    cmd = [sys.executable, script_path, "monitor"]

    logging.info("Spawning monitor: %s" % " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdout=open("/root/scalper/monitor.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    logging.info("Monitor spawned: PID %d" % proc.pid)


if __name__ == "__main__":
    main()
