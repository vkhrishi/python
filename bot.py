# ============================================================
#  NIFTY SNIPER v2.1 - BAG + ORB + FVG + WebSocket Monitoring
#  VPS (Hetzner + Groww API)
#
#  ARCHITECTURE:
#    - Cron runs every minute for signal scanning (no position open)
#    - Once trade is entered -> long-running WebSocket monitors SL/TP
#    - GrowwFeed gives sub-second price updates
#
#  STRATEGY:
#    1. BAG  - Gap at open sets directional bias
#    2. ORB  - 15-min range breakout confirms direction
#    3. FVG  - Fair Value Gap gives sniper entry with tight SL
#
#  RULES:
#    - 2 trades/day MAX (allows one recovery trade)
#    - No trades after 12:30 PM
#    - RR minimum 1:2 enforced
#    - Adaptive SL% based on premium range (50-350)
#    - 5-min hold period to survive morning noise
#    - Catastrophic SL active during hold (max Rs.2000)
#    - ITM options for better delta
#    - Cached login + smart API budgeting
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
ITM_OFFSET       = 100

# -- PAPER TRADE MODE --
PAPER_TRADE      = False

# -- BAG (Breakaway Gap) --
MIN_GAP_POINTS       = 15
MAX_GAP_POINTS       = 200
GAP_CONFIRMATION_MIN = 15

# -- ORB (Opening Range Breakout) --
ORB_MINUTES          = 15
ORB_BUFFER_POINTS    = 3
MIN_ORB_RANGE        = 20
MAX_ORB_RANGE        = 200

# -- FVG (Fair Value Gap) --
FVG_MIN_SIZE_POINTS  = 5
FVG_MAX_AGE_CANDLES  = 12
FVG_ENTRY_BUFFER     = 2

# -- Risk (ADAPTIVE PERCENTAGE + RR RATIO) --
# SL scales with premium to give proper breathing room
# Low premium (Rs.50-100):   SL = 18%
# Mid premium (Rs.100-250):  SL = 14%
# High premium (Rs.250-400): SL = 10%
SL_PERCENT_LOW    = 18.0
SL_PERCENT_MID    = 14.0
SL_PERCENT_HIGH   = 10.0
RR_RATIO          = 2.0     # Target = SL x 2.0 (1:2.0 RR)
MIN_RR_RATIO      = 2.0     # Reject if below 1:2

# -- Capital risk --
CAPITAL_RUPEES        = 50000
RISK_PER_TRADE_PCT    = 4.0     # Lowered from 6% - protect small capital
MAX_RISK_RUPEES       = CAPITAL_RUPEES * RISK_PER_TRADE_PCT / 100  # Rs.2000
MAX_DAILY_LOSS_RUPEES = 3000  # Combined cap across BOTH bots (shared state file)

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
MIN_HOLD_MINUTES      = 5       # Reduced from 8 - valid breakouts prove out in 3-5 min
CATASTROPHIC_MAX_LOSS = 2000    # Absolute max loss during hold period

# -- Other limits --
MAX_TRADES_DAY            = 2   # Allow a recovery trade (was 1)
MIN_OPTION_PREMIUM        = 50
MAX_OPTION_PREMIUM        = 400
MAX_SPREAD_PCT            = 2.5
MAX_CAPITAL_EXPOSURE_PCT  = 100
SL_BUFFER_POINTS          = 5

# -- Time --
NO_TRADE_AFTER_HOUR  = 12      # Extended trade window to 12:30 (was 11:30)
NO_TRADE_AFTER_MIN   = 30
SQUAREOFF_HOUR       = 15
SQUAREOFF_MIN        = 10

# -- Market regime --
MIN_ADX_FOR_TRADE    = 15
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
TRAILING_SL_TRIGGER  = 0.35
TRAILING_SL_STEP     = 0.60     # Lock 60% of open profit (was 0.55) - protect winners

# -- Theta / stagnation exit (option buyers bleed premium on dead trades) --
STAGNATION_EXIT_ENABLED   = True
STAGNATION_EXIT_MIN       = 25    # If trade is going nowhere after 25 min...
STAGNATION_MIN_PROFIT_RR  = 0.5   # ...and profit < 0.5x risk, cut it to save theta

# -- Partial Profit (only fires with 2+ lots; inert at 1 lot) --
PARTIAL_EXIT_ENABLED = True
PARTIAL_EXIT_PCT     = 50      # Exit 50% at first target
PARTIAL_TARGET_RR    = 1.0     # First target at 1:1 RR, then SL -> breakeven

# -- Expiry --
NIFTY_EXPIRY_WEEKDAY = 1

# -- Files --
STATE_FILE    = "/root/scalper/state.json"
TOKEN_FILE    = "/root/scalper/token.json"
CANDLE_FILE   = "/root/scalper/candles.json"
ORB_FILE      = "/root/scalper/orb.json"
MONITOR_PID   = "/root/scalper/monitor.pid"

# =============================================================
#  SECTION 2 - INDICATORS
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
#  SECTION 3 - BAG + ORB + FVG SIGNAL ENGINE
# =============================================================

def load_orb():
    today = ist_now().strftime("%Y-%m-%d")
    try:
        with open(ORB_FILE) as f:
            data = json.load(f)
        if data.get("date") == today:
            return data
    except:
        pass
    return None

def save_orb(data):
    with open(ORB_FILE, "w") as f:
        json.dump(data, f, indent=2)

def compute_orb_levels(candles, target_date=None):
    orb_candles = []
    prev_day_close = None
    today = target_date or ist_now().date()

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
        if datetime.time(9, 15) <= t < datetime.time(9, 30):
            orb_candles.append(c)

    if len(orb_candles) < 2:
        return None

    orb_high = max(c["high"] for c in orb_candles)
    orb_low = min(c["low"] for c in orb_candles)
    orb_open = orb_candles[0]["open"]
    orb_close = orb_candles[-1]["close"]
    orb_range = orb_high - orb_low

    gap_size = 0
    gap_direction = "NONE"
    if prev_day_close:
        gap_size = round(orb_open - prev_day_close, 2)
        if gap_size > MIN_GAP_POINTS:
            gap_direction = "GAP_UP"
        elif gap_size < -MIN_GAP_POINTS:
            gap_direction = "GAP_DOWN"

    return {
        "date": today.strftime("%Y-%m-%d"),
        "orb_high": round(orb_high, 2),
        "orb_low": round(orb_low, 2),
        "orb_open": round(orb_open, 2),
        "orb_close": round(orb_close, 2),
        "orb_range": round(orb_range, 2),
        "prev_close": round(prev_day_close, 2) if prev_day_close else None,
        "gap_size": gap_size,
        "gap_direction": gap_direction,
        "computed_at": ist_now().strftime("%H:%M:%S")
    }

def detect_fvg(highs, lows, closes, direction):
    if len(highs) < 3:
        return None, None, None
    search_start = len(highs) - 1
    search_end = max(0, len(highs) - FVG_MAX_AGE_CANDLES)
    for i in range(search_start, search_end + 1, -1):
        if i < 2:
            break
        if direction == "BULL":
            c1_high = highs[i - 2]
            c3_low = lows[i]
            if c3_low > c1_high:
                fvg_size = c3_low - c1_high
                if fvg_size >= FVG_MIN_SIZE_POINTS:
                    return round(c3_low, 2), round(c1_high, 2), i
        elif direction == "BEAR":
            c1_low = lows[i - 2]
            c3_high = highs[i]
            if c1_low > c3_high:
                fvg_size = c1_low - c3_high
                if fvg_size >= FVG_MIN_SIZE_POINTS:
                    return round(c1_low, 2), round(c3_high, 2), i
    return None, None, None

def compute_signal(candles, orb, now=None):
    if not orb or not candles:
        return {"signal": "NO_TRADE", "details": {"reason": "No data"}}

    orb_high = orb["orb_high"]
    orb_low = orb["orb_low"]
    orb_range = orb["orb_range"]
    gap_dir = orb.get("gap_direction", "NONE")
    gap_size = orb.get("gap_size", 0)
    prev_close = orb.get("prev_close")

    details = {
        "orb_high": orb_high, "orb_low": orb_low, "orb_range": orb_range,
        "gap_direction": gap_dir, "gap_size": gap_size,
    }

    # CHEAP CHECKS FIRST (before indicator math) 

    now = now or ist_now()
    if now.hour > NO_TRADE_AFTER_HOUR or (now.hour == NO_TRADE_AFTER_HOUR and now.minute >= NO_TRADE_AFTER_MIN):
        details["reason"] = "Past %d:%02d" % (NO_TRADE_AFTER_HOUR, NO_TRADE_AFTER_MIN)
        return {"signal": "NO_TRADE", "details": details}

    # ORB range filter (percentagebased, autoscales with Nifty level)
    if prev_close and prev_close > 0:
        orb_range_pct = orb_range / prev_close * 100
        min_orb_pct = 0.08   # 20 pts at 25000
        max_orb_pct = 0.80   # 200 pts at 25000
        details["orb_range_pct"] = round(orb_range_pct, 3)
        if orb_range_pct < min_orb_pct:
            details["reason"] = "ORB too tight: %.0f pts (%.3f%% < %.2f%%)" % (orb_range, orb_range_pct, min_orb_pct)
            return {"signal": "NO_TRADE", "details": details}
        if orb_range_pct > max_orb_pct:
            details["reason"] = "ORB too wide: %.0f pts (%.3f%% > %.2f%%)" % (orb_range, orb_range_pct, max_orb_pct)
            return {"signal": "NO_TRADE", "details": details}
    else:
        if orb_range < MIN_ORB_RANGE:
            details["reason"] = "ORB too tight: %.0f < %d" % (orb_range, MIN_ORB_RANGE)
            return {"signal": "NO_TRADE", "details": details}
        if orb_range > MAX_ORB_RANGE:
            details["reason"] = "ORB too wide: %.0f > %d" % (orb_range, MAX_ORB_RANGE)
            return {"signal": "NO_TRADE", "details": details}

    # Exhaustion gap filter (percentage-based)
    if prev_close and prev_close > 0:
        gap_pct = abs(gap_size) / prev_close * 100
        max_gap_pct = 0.80   # 200 pts at 25000
        details["gap_pct"] = round(gap_pct, 3)
        if gap_pct > max_gap_pct:
            details["reason"] = "Exhaustion gap: %.0f pts (%.2f%% > %.2f%%)" % (abs(gap_size), gap_pct, max_gap_pct)
            return {"signal": "NO_TRADE", "details": details}
    else:
        if abs(gap_size) > MAX_GAP_POINTS:
            details["reason"] = "Exhaustion gap: %.0f pts" % gap_size
            return {"signal": "NO_TRADE", "details": details}

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c.get("volume", 0) for c in candles]

    if len(closes) < 30:
        details["reason"] = "Need 30 candles, have %d" % len(closes)
        return {"signal": "NO_TRADE", "details": details}

    # INDICATORS

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
    last_close = closes[-1]

    details.update({
        "close": round(last_close, 2),
        "adx": round(adx, 1) if adx else "N/A",
        "pdi": round(pdi, 1) if pdi else "N/A",
        "mdi": round(mdi, 1) if mdi else "N/A",
        "rsi": round(rsi, 1) if rsi else "N/A",
        "atr": round(atr, 1) if atr else "N/A",
        "vwap": round(vwap, 2) if vwap else "N/A",
        "ema9": round(ef, 2) if ef else "N/A",
        "ema21": round(es, 2) if es else "N/A",
    })

    if adx is not None and adx < MIN_ADX_FOR_TRADE:
        details["reason"] = "Sideways: ADX %.1f < %d" % (adx, MIN_ADX_FOR_TRADE)
        return {"signal": "NO_TRADE", "details": details}

    # CONFLUENCE SCORING 

    trend_bull = ef is not None and es is not None and ef > es
    trend_bear = ef is not None and es is not None and ef < es
    above_vwap = vwap is not None and last_close > vwap
    below_vwap = vwap is not None and last_close < vwap
    pdi_strong = pdi is not None and mdi is not None and pdi > mdi
    mdi_strong = pdi is not None and mdi is not None and mdi > pdi

    breakout_high = orb_high + ORB_BUFFER_POINTS
    breakout_low = orb_low - ORB_BUFFER_POINTS

    bull_score = sum([
        int(last_close > breakout_high),
        int(gap_dir == "GAP_UP"),
        int(trend_bull),
        int(above_vwap),
        int(pdi_strong),
        int(rsi is not None and 45 < rsi < 75),
    ])
    bear_score = sum([
        int(last_close < breakout_low),
        int(gap_dir == "GAP_DOWN"),
        int(trend_bear),
        int(below_vwap),
        int(mdi_strong),
        int(rsi is not None and 25 < rsi < 45),
    ])

    details["bull_score"] = "%d/6" % bull_score
    details["bear_score"] = "%d/6" % bear_score

    # DIRECTION DECISION 

    direction = None
    if bull_score >= 3 and last_close > breakout_high:
        direction = "BULL"
    elif bear_score >= 3 and last_close < breakout_low:
        direction = "BEAR"
    elif last_close > breakout_high and trend_bull and bull_score >= 2:
        direction = "BULL"
    elif last_close < breakout_low and trend_bear and bear_score >= 2:
        direction = "BEAR"

    if direction is None:
        details["reason"] = "Insufficient confluence: Bull=%d/6 Bear=%d/6" % (bull_score, bear_score)
        return {"signal": "NO_TRADE", "details": details}

    # POSTDIRECTION FILTERS

    if direction == "BULL" and rsi is not None and rsi > 78:
        details["reason"] = "RSI overbought: %.0f" % rsi
        return {"signal": "NO_TRADE", "details": details}
    if direction == "BEAR" and rsi is not None and rsi < 22:
        details["reason"] = "RSI oversold: %.0f" % rsi
        return {"signal": "NO_TRADE", "details": details}

    if direction == "BULL" and gap_dir == "GAP_DOWN":
        details["reason"] = "Counter-gap: BULL signal vs GAP_DOWN (%.0f pts)" % gap_size
        return {"signal": "NO_TRADE", "details": details}
    if direction == "BEAR" and gap_dir == "GAP_UP":
        details["reason"] = "Counter-gap: BEAR signal vs GAP_UP (%.0f pts)" % gap_size
        return {"signal": "NO_TRADE", "details": details}

    # FILTER 1: BREAKOUT CANDLE STRENGTH
    last_body = abs(closes[-1] - candles[-1]["open"])
    last_range = highs[-1] - lows[-1]
    if last_range > 0:
        body_ratio = last_body / last_range
        details["candle_body_pct"] = round(body_ratio * 100, 1)
        if body_ratio < 0.3:
            details["reason"] = "Weak breakout candle: body %d pct of range (need 30 pct+)" % round(body_ratio * 100)
            return {"signal": "NO_TRADE", "details": details}
    else:
        details["reason"] = "Zero-range candle (doji)"
        return {"signal": "NO_TRADE", "details": details}

    # FILTER 2: CANDLE DIRECTION ALIGNMENT
    candle_green = closes[-1] > candles[-1]["open"]
    candle_red = closes[-1] < candles[-1]["open"]
    if direction == "BULL" and not candle_green:
        details["reason"] = "BULL signal but breakout candle is red"
        return {"signal": "NO_TRADE", "details": details}
    if direction == "BEAR" and not candle_red:
        details["reason"] = "BEAR signal but breakout candle is green"
        return {"signal": "NO_TRADE", "details": details}

    # FILTER 3: VOLUME CONFIRMATION
    recent_volumes = [c.get("volume", 0) for c in candles[-20:]]
    avg_vol = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
    current_vol = candles[-1].get("volume", 0)
    if avg_vol > 0:
        vol_ratio = current_vol / avg_vol
        details["vol_ratio"] = round(vol_ratio, 2)
        details["avg_vol_20"] = round(avg_vol, 0)
        details["current_vol"] = round(current_vol, 0)
        if vol_ratio < 0.8:
            details["reason"] = "Low volume breakout: %.1fx avg (need 0.8x+)" % vol_ratio
            return {"signal": "NO_TRADE", "details": details}
    else:
        details["vol_ratio"] = "N/A (no vol data)"
        logging.warning("Volume data unavailable - skipping volume filter")

    # FILTER 4: CONSECUTIVE DIRECTIONAL CANDLES
    if len(candles) >= 3:
        if direction == "BULL":
            consec = sum(1 for c in candles[-3:] if c["close"] > c["open"])
        else:
            consec = sum(1 for c in candles[-3:] if c["close"] < c["open"])
        details["directional_candles_3"] = "%d/3" % consec
        if consec < 1:
            details["reason"] = "Weak momentum: only %d/3 candles in direction" % consec
            return {"signal": "NO_TRADE", "details": details}

    # FILTER 5: LATE ENTRY HIGHER CONFLUENCE
    score = bull_score if direction == "BULL" else bear_score
    is_late = now.hour > 10 or (now.hour == 10 and now.minute >= 30)
    if is_late:
        min_late_score = 4
        details["late_entry"] = True
        details["late_min_score"] = min_late_score
        if score < min_late_score:
            details["reason"] = "Late entry (%s): need %d/6, got %d/6" % (now.strftime("%H:%M"), min_late_score, score)
            return {"signal": "NO_TRADE", "details": details}
    else:
        details["late_entry"] = False

    # FILTER 6: ATR BREAKOUT DISTANCE CHECK
    if atr is not None and atr > 0:
        if direction == "BULL":
            breakout_distance = last_close - orb_high
        else:
            breakout_distance = orb_low - last_close

        if breakout_distance <= 0:
            details["reason"] = "Price back inside ORB (distance: %.1f)" % breakout_distance
            return {"signal": "NO_TRADE", "details": details}

        atr_multiple = breakout_distance / atr
        details["breakout_atr_mult"] = round(atr_multiple, 2)
        if atr_multiple < 0.2:
            details["reason"] = "Breakout too shallow: %.2fx ATR (need 0.2x+)" % atr_multiple
            return {"signal": "NO_TRADE", "details": details}
        if atr_multiple > 2.0:
            details["reason"] = "Overextended: %.2fx ATR (max 2.0x)" % atr_multiple
            return {"signal": "NO_TRADE", "details": details}

    # FVG DETECTION

    fvg_top, fvg_bot, fvg_idx = detect_fvg(highs, lows, closes, direction)

    if fvg_top is not None:
        details["fvg_top"] = fvg_top
        details["fvg_bot"] = fvg_bot
        details["fvg_size"] = round(fvg_top - fvg_bot, 1)

        if direction == "BULL":
            near_fvg = last_close <= fvg_top + FVG_ENTRY_BUFFER
        else:
            near_fvg = last_close >= fvg_bot - FVG_ENTRY_BUFFER

        details["entry_mode"] = "FVG_RETEST" if near_fvg else "FVG_PRESENT"
    else:
        details["entry_mode"] = "ORB_BREAKOUT"

    # FINAL OUTPUT 

    confidence = "HIGH" if score >= 4 else ("MED" if score >= 3 else "LOW")
    signal_type = "CE_BUY" if direction == "BULL" else "PE_BUY"

    if fvg_top is not None and details["entry_mode"] == "FVG_RETEST":
        trigger_tag = "BAG+ORB+FVG"
    elif fvg_top is not None:
        trigger_tag = "BAG+ORB+FVG_NEARBY"
    else:
        trigger_tag = "BAG+ORB+MOMENTUM"

    details["trigger"] = trigger_tag
    details["score"] = "%d/6" % score
    details["direction"] = direction

    return {
        "signal": signal_type, "confidence": confidence,
        "direction": direction, "details": details,
    }




# =============================================================
#  SECTION 4 - RISK MANAGER
# =============================================================

class RiskManager:
    def __init__(self, state):
        self.state = state

    def check_can_trade(self, groww):
        checks = [
            self._check_orb_formed(),
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

    def _check_orb_formed(self):
        now = ist_now()
        orb_end = now.replace(hour=9, minute=30, second=0)
        if now < orb_end:
            return False, "ORB forming: %d min" % int((orb_end - now).total_seconds() / 60)
        return True, "ORB formed"

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
    """Return SL percentage based on premium range."""
    if premium <= 100:
        return SL_PERCENT_LOW
    elif premium <= 250:
        return SL_PERCENT_MID
    else:
        return SL_PERCENT_HIGH

def calc_sl_tp(entry_price, qty):
    """
    Calculate SL and TP for given entry price.
    Returns: (sl_price, target_price, sl_drop, tp_rise, sl_pct, rr)
    """
    sl_pct = get_sl_percent(entry_price)
    sl_drop = entry_price * sl_pct / 100
    tp_rise = sl_drop * RR_RATIO

    # Cap risk at max allowed
    if sl_drop * qty > MAX_RISK_RUPEES:
        sl_drop = MAX_RISK_RUPEES / qty
        tp_rise = sl_drop * RR_RATIO
        sl_pct = sl_drop / entry_price * 100

    sl_price = round(max(entry_price - sl_drop, 1.0), 1)
    target_price = round(entry_price + tp_rise, 1)
    rr = tp_rise / sl_drop if sl_drop > 0 else 0

    return sl_price, target_price, sl_drop, tp_rise, sl_pct, rr

def get_catastrophic_sl(entry_price, qty):
    """Max loss during hold period = CATASTROPHIC_MAX_LOSS."""
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
#  SECTION 6 - LOGIN (CACHED)
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
#  SECTION 7 - FETCH CANDLES (3-day warmup)
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
#  SECTION 8 - SYMBOL RESOLUTION
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
            order_reference_id="SNP%s" % ist_now().strftime("%H%M%S"))
        oid = res.get("groww_order_id", "N/A")
        logging.info("ENTRY | %s | Qty:%d | ID:%s" % (symbol, qty, oid))
        return oid
    except Exception as e:
        logging.error("ENTRY FAILED: %s" % str(e))
        return None

def place_exit_order(groww, symbol, qty, reason):
    if PAPER_TRADE:
        logging.info("PAPER EXIT | %s | %s" % (symbol, reason))
        return True
    try:
        groww.place_order(
            trading_symbol=symbol, quantity=qty, validity=groww.VALIDITY_DAY,
            exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_FNO,
            product=groww.PRODUCT_MIS, order_type=groww.ORDER_TYPE_MARKET,
            transaction_type=groww.TRANSACTION_TYPE_SELL)
        logging.info("EXIT | %s | %s" % (symbol, reason))
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
#  SECTION 10 - WEBSOCKET MONITOR
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
    entry_premium = trade["entry_premium"]
    entry_time = datetime.datetime.strptime(trade["time"], "%Y-%m-%d %H:%M:%S")

    # Calculate SL and TP using adaptive percentage
    sl_price, target_price, sl_drop, tp_rise, sl_pct, actual_rr = calc_sl_tp(entry_premium, qty)
    catastrophic_sl = get_catastrophic_sl(entry_premium, qty)

    # Partial profit target (only fires with 2+ lots; inert at 1 lot)
    remaining_qty = trade.get("remaining_qty", qty)
    partial_target = round(entry_premium + sl_drop * PARTIAL_TARGET_RR, 1) if PARTIAL_EXIT_ENABLED else None
    partial_qty = int(remaining_qty * PARTIAL_EXIT_PCT / 100)
    partial_qty = max(partial_qty, LOT_SIZE)
    if partial_qty >= remaining_qty:
        partial_qty = 0

    logging.info("=== WS MONITOR START ===")
    logging.info("  Symbol: %s | Qty: %d" % (symbol, remaining_qty))
    logging.info("  Entry: Rs.%.1f | Band: %s" % (
        entry_premium,
        "LOW" if entry_premium <= 100 else ("MID" if entry_premium <= 250 else "HIGH")))
    logging.info("  SL: Rs.%.1f (-%.1f%%) | Target: Rs.%.1f (+%.1f%%)" % (
        sl_price, sl_pct, target_price, tp_rise / entry_premium * 100))
    logging.info("  Risk: Rs.%.0f | Reward: Rs.%.0f | RR 1:%.1f" % (
        sl_drop * qty, tp_rise * qty, actual_rr))
    logging.info("  Hold: %d min | Catastrophic SL: Rs.%.1f (max Rs.%d)" % (
        MIN_HOLD_MINUTES, catastrophic_sl, CATASTROPHIC_MAX_LOSS))
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

        # Log every 30 seconds
        if now_ts - monitor_state["last_log_time"] >= WS_TICK_LOG_INTERVAL:
            pnl = (current_ltp - entry_premium) * r_qty
            pnl_pct = (current_ltp - entry_premium) / entry_premium * 100
            logging.info("  TICK | LTP:%.1f | P&L:Rs.%+.0f (%+.1f%%) | SL:%.1f | T:%.1f | Qty:%d" % (
                current_ltp, pnl, pnl_pct, monitor_state["trailing_sl"], target_price, r_qty))
            monitor_state["last_log_time"] = now_ts

        # Heartbeat every 60 seconds
        if now_ts - monitor_state["last_heartbeat"] >= WS_HEARTBEAT_SEC:
            logging.info("  HEARTBEAT | LTP:%.1f" % current_ltp)
            monitor_state["last_heartbeat"] = now_ts

        # EOD squareoff (always active)
        now_ist = ist_now()
        if now_ist.hour > SQUAREOFF_HOUR or (now_ist.hour == SQUAREOFF_HOUR and now_ist.minute >= SQUAREOFF_MIN):
            pnl = (current_ltp - entry_premium) * r_qty
            _do_exit(current_ltp, pnl, "EOD SQUAREOFF Rs.%+.0f" % pnl, r_qty)
            return

        # PARTIAL PROFIT (only with 2+ lots)
        if (PARTIAL_EXIT_ENABLED and not monitor_state["partial_done"]
                and partial_target and partial_qty > 0
                and current_ltp >= partial_target):
            pnl_partial = (current_ltp - entry_premium) * partial_qty
            logging.info("=== PARTIAL EXIT ===")
            logging.info("  LTP:%.1f | Qty:%d | P&L:Rs.%+.0f" % (current_ltp, partial_qty, pnl_partial))
            place_exit_order(groww, symbol, partial_qty, "PARTIAL TP Rs.%+.0f" % pnl_partial)
            monitor_state["partial_done"] = True
            monitor_state["remaining_qty"] -= partial_qty
            monitor_state["trailing_sl"] = max(monitor_state["trailing_sl"], entry_premium)
            logging.info("  Remaining: %d | SL moved to breakeven: Rs.%.1f" % (
                monitor_state["remaining_qty"], monitor_state["trailing_sl"]))
            trade["partial_done"] = True
            trade["partial_pnl"] = round(pnl_partial, 2)
            trade["remaining_qty"] = monitor_state["remaining_qty"]
            state["daily_pnl_rupees"] = state.get("daily_pnl_rupees", 0) + pnl_partial
            save_state(state)
            return

        # TAKE PROFIT (always active, even during hold)
        if current_ltp >= target_price:
            pnl = (current_ltp - entry_premium) * r_qty
            _do_exit(current_ltp, pnl, "TAKE PROFIT Rs.%+.0f" % pnl, r_qty)
            return

        # Check hold period
        minutes_held = (now_ist - entry_time).total_seconds() / 60

        # DURING HOLD: only catastrophic SL active
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

        # STOP LOSS (after hold period)
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
            if final_ltp > 0:
                r_qty = monitor_state["remaining_qty"]
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
    qty = trade.get("remaining_qty", trade["qty"])
    entry_premium = trade["entry_premium"]
    entry_time = datetime.datetime.strptime(trade["time"], "%Y-%m-%d %H:%M:%S")

    sl_price, target_price, sl_drop, tp_rise, sl_pct, rr = calc_sl_tp(entry_premium, qty)
    catastrophic_sl = get_catastrophic_sl(entry_premium, qty)

    # Trailing SL state
    trailing_sl = sl_price
    highest_ltp = entry_premium

    # Partial profit (only fires with 2+ lots; inert at 1 lot)
    partial_done = trade.get("partial_done", False)
    partial_target = round(entry_premium + sl_drop * PARTIAL_TARGET_RR, 1) if PARTIAL_EXIT_ENABLED else None
    partial_qty = int(qty * PARTIAL_EXIT_PCT / 100)
    partial_qty = max(partial_qty, LOT_SIZE)
    if partial_qty >= qty:
        partial_qty = 0

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
                pnl = (current_ltp - entry_premium) * qty
                place_exit_order(groww, symbol, qty, "EOD SQUAREOFF Rs.%+.0f" % pnl)
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

            pnl = (current_ltp - entry_premium) * qty
            minutes_held = (now - entry_time).total_seconds() / 60

            now_ts = time.time()
            if now_ts - last_log >= 30:
                logging.info("  POLL | LTP:%.1f | P&L:%+.0f | SL:%.1f T:%.1f | Hold:%.0fm" % (
                    current_ltp, pnl, trailing_sl, target_price, minutes_held))
                last_log = now_ts

            # PARTIAL PROFIT (only with 2+ lots)
            if (PARTIAL_EXIT_ENABLED and not partial_done
                    and partial_target and partial_qty > 0
                    and current_ltp >= partial_target):
                pnl_partial = (current_ltp - entry_premium) * partial_qty
                place_exit_order(groww, symbol, partial_qty, "PARTIAL TP Rs.%+.0f" % pnl_partial)
                partial_done = True
                qty -= partial_qty
                trailing_sl = max(trailing_sl, entry_premium)
                logging.info("  PARTIAL EXIT %d qty | Remaining:%d | SL->breakeven:%.1f" % (
                    partial_qty, qty, trailing_sl))
                trade["partial_done"] = True
                trade["partial_pnl"] = round(pnl_partial, 2)
                trade["remaining_qty"] = qty
                state["daily_pnl_rupees"] = state.get("daily_pnl_rupees", 0) + pnl_partial
                save_state(state)
                time.sleep(5)
                continue

            # TP always active
            if current_ltp >= target_price:
                place_exit_order(groww, symbol, qty, "TP Rs.%+.0f" % pnl)
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
                    place_exit_order(groww, symbol, qty, "CATASTROPHIC SL Rs.%+.0f" % pnl)
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
                place_exit_order(groww, symbol, qty, "STAGNATION EXIT Rs.%+.0f" % pnl)
                trade["exited"] = True
                trade["exit_ltp"] = current_ltp
                trade["exit_pnl"] = round(pnl + trade.get("partial_pnl", 0), 2)
                trade["exit_reason"] = "STAGNATION_EXIT"
                trade["exit_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
                state["daily_pnl_rupees"] = state.get("daily_pnl_rupees", 0) + pnl
                save_state(state)
                break

            # After hold: trailing SL logic
            if TRAILING_SL_ENABLED and current_ltp > highest_ltp:
                highest_ltp = current_ltp
                profit = current_ltp - entry_premium
                if profit >= tp_rise * TRAILING_SL_TRIGGER:
                    new_sl = round(entry_premium + (profit * TRAILING_SL_STEP), 1)
                    if new_sl > trailing_sl:
                        logging.info("  TRAIL SL: Rs.%.1f -> Rs.%.1f" % (trailing_sl, new_sl))
                        trailing_sl = new_sl

            # Stop loss (uses trailing SL)
            if current_ltp <= trailing_sl:
                place_exit_order(groww, symbol, qty, "SL Rs.%+.0f" % pnl)
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
#  SECTION 10b - BACKTEST HARNESS (BAG + ORB + FVG)
# =============================================================
#  Replays the live signal engine over historical NIFTY index
#  candles to estimate the strategy's edge BEFORE risking money.
#  Reuses compute_orb_levels / compute_signal / calc_sl_tp so what
#  you backtest is what trades live.
#
#  IMPORTANT — OPTIONS APPROXIMATION:
#   The live bot trades ITM option PREMIUM, but historical option
#   premium is NOT fetched here. Option P&L is approximated from the
#   index move using a fixed delta + a synthetic entry premium.
#   Real results will differ because:
#     - delta changes as price/time move (gamma)
#     - implied volatility shifts premiums independently (vega)
#     - theta decay bleeds premium intraday
#   Treat the output as a DIRECTIONAL edge check, not a precise P&L
#   forecast. Confirm with paper trading on real premiums.
# =============================================================

BT_DELTA          = 0.55   # assumed delta of the ITM-by-ITM_OFFSET option
BT_TIME_VALUE_PCT = 0.45   # extrinsic value as % of spot (rough weekly)
BT_SQUAREOFF      = datetime.time(SQUAREOFF_HOUR, SQUAREOFF_MIN)


def _bt_entry_premium(entry_spot):
    """Synthetic entry premium for an ITM-by-ITM_OFFSET option."""
    intrinsic = ITM_OFFSET
    time_value = BT_TIME_VALUE_PCT / 100.0 * entry_spot
    return round(intrinsic + time_value, 1)


def _bt_premium(direction, entry_spot, entry_premium, spot):
    """Approximate option premium at a given index spot (constant-delta)."""
    if direction == "BULL":
        prem = entry_premium + (spot - entry_spot) * BT_DELTA
    else:
        prem = entry_premium + (entry_spot - spot) * BT_DELTA
    return max(prem, 0.5)


def fetch_history_nifty(groww, days=30):
    """Fetch historical 5-min NIFTY index candles for backtesting."""
    now = ist_now()
    start_dt = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%d 09:15:00")
    end_dt = now.strftime("%Y-%m-%d %H:%M:%S")
    try:
        res = groww.get_historical_candle_data(
            trading_symbol="NIFTY", exchange="NSE", segment="CASH",
            start_time=start_dt, end_time=end_dt, interval_in_minutes=5)
        raw = res.get("candles", []) if isinstance(res, dict) else []
        candles = _parse_candles(raw)
        candles.sort(key=lambda c: c["ts"])
        logging.info("Backtest history: %d candles" % len(candles))
        return candles
    except Exception as e:
        logging.error("History fetch failed: %s" % str(e))
        return []


def _simulate_option_trade(direction, entry_spot, forward):
    """Walk forward index candles; return option-trade P&L (Rs, net of costs).
    Mirrors the live monitor (catastrophic SL, hold period, partial, TP,
    trailing SL, stagnation) in premium space via the delta model.
    Conservative: checks the stop BEFORE the target within a candle."""
    qty = LOT_SIZE * LOTS_TO_TRADE
    entry_premium = _bt_entry_premium(entry_spot)
    sl_price, target_price, sl_drop, tp_rise, sl_pct, rr = calc_sl_tp(entry_premium, qty)
    if rr < MIN_RR_RATIO:
        return None

    gate = net_rr_after_costs(sl_drop, tp_rise, qty, entry_premium)
    if not gate:
        return None
    net_rr, rt_cost, net_reward = gate
    if net_reward <= 0 or net_rr < MIN_NET_RR:
        return None

    catastrophic_sl = get_catastrophic_sl(entry_premium, qty)
    partial_target = round(entry_premium + sl_drop * PARTIAL_TARGET_RR, 1)
    partial_qty = int(qty * PARTIAL_EXIT_PCT / 100)
    if partial_qty >= qty or LOTS_TO_TRADE < 2:
        partial_qty = 0   # inert at 1 lot, exactly like live

    trailing_sl = sl_price
    highest = entry_premium
    partial_done = False
    realized = 0.0        # rupees already booked
    remaining = qty
    reason = "SQUAREOFF"

    for i, c in enumerate(forward):
        minutes_held = (i + 1) * 5   # 5-min candles
        # premium at the adverse and favourable extremes of this candle
        adverse_spot = c["low"] if direction == "BULL" else c["high"]
        favour_spot  = c["high"] if direction == "BULL" else c["low"]
        prem_adverse = _bt_premium(direction, entry_spot, entry_premium, adverse_spot)
        prem_favour  = _bt_premium(direction, entry_spot, entry_premium, favour_spot)
        prem_close   = _bt_premium(direction, entry_spot, entry_premium, c["close"])

        # During hold: only catastrophic SL (checked first = conservative), TP still active
        if minutes_held < MIN_HOLD_MINUTES:
            if prem_adverse <= catastrophic_sl:
                realized += (catastrophic_sl - entry_premium) * remaining
                reason = "CATASTROPHIC"
                break
            if prem_favour >= target_price:
                realized += (target_price - entry_premium) * remaining
                reason = "TAKE_PROFIT"
                break
            continue

        # After hold — stop first (conservative)
        if prem_adverse <= trailing_sl:
            realized += (trailing_sl - entry_premium) * remaining
            reason = "STOP_LOSS" if trailing_sl == sl_price else "TRAIL_STOP"
            break

        # Partial profit
        if partial_qty > 0 and not partial_done and prem_favour >= partial_target:
            realized += (partial_target - entry_premium) * partial_qty
            remaining -= partial_qty
            partial_done = True
            trailing_sl = max(trailing_sl, entry_premium)  # move to breakeven

        # Take profit
        if prem_favour >= target_price:
            realized += (target_price - entry_premium) * remaining
            reason = "TAKE_PROFIT"
            break

        # Trailing-stop ratchet
        if TRAILING_SL_ENABLED and prem_favour > highest:
            highest = prem_favour
            open_profit = highest - entry_premium
            if open_profit >= tp_rise * TRAILING_SL_TRIGGER:
                new_sl = entry_premium + open_profit * TRAILING_SL_STEP
                trailing_sl = max(trailing_sl, new_sl)

        # Stagnation
        if (STAGNATION_EXIT_ENABLED and minutes_held >= STAGNATION_EXIT_MIN
                and (prem_close - entry_premium) < sl_drop * STAGNATION_MIN_PROFIT_RR):
            realized += (prem_close - entry_premium) * remaining
            reason = "STAGNATION"
            break
    else:
        last_prem = _bt_premium(direction, entry_spot, entry_premium, forward[-1]["close"])
        realized += (last_prem - entry_premium) * remaining

    net = realized - rt_cost
    return {"pnl": round(net, 0), "gross": round(realized, 0), "cost": round(rt_cost, 0),
            "reason": reason, "entry_prem": entry_premium}


def run_backtest_nifty(days=30):
    """Backtest the BAG+ORB+FVG strategy over the last `days` days."""
    groww = login()
    candles = fetch_history_nifty(groww, days=days)
    if len(candles) < 60:
        print("Not enough history fetched: %d candles" % len(candles))
        return
    print("Loaded %d candles (%s -> %s)" % (
        len(candles), candles[0]["ts"], candles[-1]["ts"]))

    ts_index = {c["ts"]: i for i, c in enumerate(candles)}
    days_seen = sorted({c["ts"][:10] for c in candles})
    cutoff = datetime.time(NO_TRADE_AFTER_HOUR, NO_TRADE_AFTER_MIN)
    orb_open = datetime.time(9, 30)

    trades, signals = [], 0

    for day in days_seen:
        d0 = datetime.datetime.strptime(day, "%Y-%m-%d").date()
        orb = compute_orb_levels(candles, target_date=d0)
        if not orb:
            continue

        for c in candles:
            dt = datetime.datetime.strptime(c["ts"], "%Y-%m-%d %H:%M:%S")
            if dt.date() != d0:
                continue
            t = dt.time()
            if t < orb_open or t >= cutoff:
                continue
            idx = ts_index[c["ts"]]
            if idx < 30 or idx + 1 >= len(candles):
                continue

            res = compute_signal(candles[:idx + 1], orb, now=dt)
            if res["signal"] not in ("CE_BUY", "PE_BUY"):
                continue
            if res.get("confidence") not in ("HIGH", "MED"):
                continue

            signals += 1
            direction = res["direction"]
            entry_spot = candles[idx + 1]["open"]  # realistic next-bar entry
            forward = []
            for fc in candles[idx + 1:]:
                fdt = datetime.datetime.strptime(fc["ts"], "%Y-%m-%d %H:%M:%S")
                if fdt.date() != d0 or fdt.time() > BT_SQUAREOFF:
                    break
                forward.append(fc)
            if not forward:
                break

            sim = _simulate_option_trade(direction, entry_spot, forward)
            if sim:
                sim["day"] = day
                sim["dir"] = "CE" if direction == "BULL" else "PE"
                sim["conf"] = res.get("confidence")
                sim["entry_spot"] = round(entry_spot, 1)
                trades.append(sim)
            break   # first valid signal per day

    _print_bt_report_nifty(trades, signals, days)


def _print_bt_report_nifty(trades, signals, days):
    print("\n" + "=" * 60)
    print(" NIFTY BACKTEST — BAG+ORB+FVG | last %d days" % days)
    print(" (option P&L APPROX: delta=%.2f, time-value=%.2f%% of spot)" % (
        BT_DELTA, BT_TIME_VALUE_PCT))
    print("=" * 60)
    if not trades:
        print(" Signals evaluated: %d | No trades taken." % signals)
        print("=" * 60)
        return

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total = sum(t["pnl"] for t in trades)
    gw = sum(t["pnl"] for t in wins)
    gl = -sum(t["pnl"] for t in losses)
    wr = len(wins) / len(trades) * 100
    aw = gw / len(wins) if wins else 0
    al = gl / len(losses) if losses else 0
    pf = gw / gl if gl > 0 else float("inf")
    exp = total / len(trades)
    eq = peak = mdd = 0.0
    for t in trades:
        eq += t["pnl"]
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)

    print(" Signals evaluated : %d" % signals)
    print(" Trades taken      : %d" % len(trades))
    print(" Win rate          : %.1f%% (%dW / %dL)" % (wr, len(wins), len(losses)))
    print(" Net P&L           : Rs.%+.0f" % total)
    print(" Avg win / loss    : Rs.%.0f / -Rs.%.0f" % (aw, al))
    print(" Profit factor     : %s" % ("%.2f" % pf if pf != float("inf") else "inf"))
    print(" Expectancy/trade  : Rs.%+.0f" % exp)
    print(" Max drawdown      : -Rs.%.0f" % mdd)
    print(" Return on capital : %+.1f%% (capital Rs.%d)" % (total / CAPITAL_RUPEES * 100, CAPITAL_RUPEES))

    print("-" * 60)
    print(" BY EXIT REASON:")
    reasons = {}
    for t in trades:
        r = reasons.setdefault(t["reason"], {"n": 0, "pnl": 0.0, "w": 0})
        r["n"] += 1
        r["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            r["w"] += 1
    for name in sorted(reasons, key=lambda k: reasons[k]["pnl"]):
        r = reasons[name]
        print("   %-13s | %2d | %dW | Rs.%+.0f" % (name, r["n"], r["w"], r["pnl"]))

    print(" BY DIRECTION:")
    for dn in ("CE", "PE"):
        sub = [t for t in trades if t["dir"] == dn]
        if sub:
            w = len([t for t in sub if t["pnl"] > 0])
            print("   %s | %2d | %dW (%.0f%%) | Rs.%+.0f" % (
                dn, len(sub), w, w / len(sub) * 100, sum(t["pnl"] for t in sub)))

    print("-" * 60)
    for t in trades:
        print(" %s | %s | spot %-9.1f | %-12s | Rs.%+.0f" % (
            t["day"], t["dir"], t["entry_spot"], t["reason"], t["pnl"]))
    print("=" * 60)
    print(" NOTE: option P&L is APPROXIMATED (no theta/vega/gamma).")
    print(" Real results differ — confirm with paper trading on live premiums.")
    print("=" * 60)


# =============================================================
#  SECTION 11 - MAIN
# =============================================================

def main():
    run_mode = sys.argv[1] if len(sys.argv) > 1 else "scan"

    # MODE: backtest
    if run_mode == "backtest":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        run_backtest_nifty(days=days)
        return

    # MODE: monitor
    if run_mode == "monitor":
        logging.info("=== MONITOR MODE ===")
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
        logging.info("[%s] Already traded. Skip." % now.strftime("%H:%M"))
        return

    past_cutoff = now.hour > NO_TRADE_AFTER_HOUR or (now.hour == NO_TRADE_AFTER_HOUR and now.minute >= NO_TRADE_AFTER_MIN)
    if past_cutoff and not is_squareoff_time():
        logging.info("[%s] Past cutoff. Waiting for squareoff." % now.strftime("%H:%M"))
        return

    mode_tag = "PAPER" if PAPER_TRADE else "LIVE"
    logging.info("=== %s SCAN | %s | Trades:%d/%d | P&L:Rs.%+.0f ===" % (
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

    orb = load_orb()
    if orb is None:
        if ist_now() < ist_now().replace(hour=9, minute=30, second=0):
            logging.info("ORB forming...")
            return
        orb = compute_orb_levels(candles)
        if orb is None:
            logging.error("Cannot compute ORB")
            return
        save_orb(orb)
        logging.info("ORB | H:%s L:%s R:%s GAP:%s(%s)" % (
            str(orb["orb_high"]), str(orb["orb_low"]), str(orb["orb_range"]),
            orb["gap_direction"], str(orb["gap_size"])))

    result = compute_signal(candles, orb)
    signal_type = result["signal"]
    confidence = result.get("confidence")
    d = result.get("details", {})

    logging.info("  Signal:%s | Conf:%s | %s" % (signal_type, str(confidence), d.get("trigger", "--")))
    logging.info("  Close:%s | ORB:%s/%s | Gap:%s(%s)" % (
        d.get("close", "--"), d.get("orb_high", "--"), d.get("orb_low", "--"),
        d.get("gap_direction", "--"), d.get("gap_size", "--")))
    logging.info("  ADX:%s RSI:%s VWAP:%s | Bull:%s Bear:%s" % (
        d.get("adx", "--"), d.get("rsi", "--"), d.get("vwap", "--"),
        d.get("bull_score", "--"), d.get("bear_score", "--")))
    if d.get("fvg_top"):
        logging.info("  FVG: %s-%s (%s pts)" % (str(d["fvg_bot"]), str(d["fvg_top"]), d.get("fvg_size", "")))
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

    # -- SL / TARGET (ADAPTIVE PERCENTAGE + RR RATIO) --
    sl_price, target_price, sl_drop, tp_rise, sl_pct, rr = calc_sl_tp(option_ltp, qty)
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
    premium_band = "LOW" if option_ltp <= 100 else ("MID" if option_ltp <= 250 else "HIGH")

    logging.info("PLAN | Entry:~Rs.%s | Band:%s" % (str(option_ltp), premium_band))
    logging.info("      SL:Rs.%s (-%.1f%%) | Target:Rs.%s (+%.1f%%)" % (
        str(sl_price), sl_pct,
        str(target_price), tp_rise / option_ltp * 100))
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

    # Recalc with actual fill
    sl_price, target_price, sl_drop, tp_rise, sl_pct, rr = calc_sl_tp(entry_premium, qty)

    # -- SAVE TRADE --
    state["trade_count"] += 1
    state["trades"].append({
        "signal": signal_type, "confidence": confidence,
        "symbol": symbol, "qty": qty,
        "remaining_qty": qty,
        "entry_id": str(oid),
        "entry_premium": entry_premium,
        "risk_premium": sl_drop,
        "target_premium": tp_rise,
        "sl_percent": sl_pct,
        "rr_ratio": rr,
        "target": target_price, "sl": sl_price,
        "nifty_ltp": nifty_ltp, "strike": strike,
        "orb_high": orb["orb_high"], "orb_low": orb["orb_low"],
        "gap": orb["gap_direction"], "gap_size": orb["gap_size"],
        "entry_mode": d.get("entry_mode", "unknown"),
        "trigger": d.get("trigger", "unknown"),
        "rr": "1:%.1f" % rr,
        "bull_score": d.get("bull_score", ""),
        "bear_score": d.get("bear_score", ""),
        "paper": PAPER_TRADE,
        "exited": False,
        "time": now.strftime("%Y-%m-%d %H:%M:%S")
    })
    save_state(state)

    tag = "PAPER TRADE" if PAPER_TRADE else "LIVE TRADE"
    logging.info("%s | %s %s | %s" % (tag, signal_type, str(confidence), symbol))
    logging.info("   E:Rs.%s SL:Rs.%s(-%.1f%%) T:Rs.%s RR:1:%.1f" % (
        str(entry_premium), str(sl_price), sl_pct, str(target_price), rr))
    logging.info("   %s | Score:%s" % (d.get("trigger", ""), d.get("score", "")))

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
