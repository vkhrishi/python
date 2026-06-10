# ============================================================
#  NIFTY SNIPER v3.0 - FIBONACCI RETRACEMENT + EXTENSION
#  VPS (Hetzner + Groww API)
#
#  ARCHITECTURE:
#    - Cron runs every minute for signal scanning (no position open)
#    - Once trade is entered -> long-running WebSocket monitors SL/TP
#    - GrowwFeed gives sub-second price updates
#
#  STRATEGY:
#    1. Identify the morning impulse leg (9:15 - configurable end)
#    2. Draw Fibonacci retracement levels on that leg
#    3. Enter on price bounce from key fib levels (38.2%, 50%, 61.8%)
#    4. SL below the fib level / beyond 78.6% retracement
#    5. Targets at fib extensions (127.2%, 161.8%)
#
#  RULES:
#    - 1 trade/day MAX (so max risk = max daily loss)
#    - No trades after 14:30
#    - RR minimum 1:2 enforced
#    - Adaptive SL% based on premium range (50-350)
#    - 8-min hold period to survive morning noise
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
import warnings
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
LOT_SIZE         = 65
LOTS_TO_TRADE    = 1
ITM_OFFSET       = 100

# -- PAPER TRADE MODE --
PAPER_TRADE      = False

# -- Fibonacci Impulse Leg --
IMPULSE_START_HOUR    = 9
IMPULSE_START_MIN     = 15
IMPULSE_END_HOUR      = 10
IMPULSE_END_MIN       = 0
MIN_IMPULSE_POINTS    = 15
MAX_IMPULSE_POINTS    = 300

# -- Fibonacci Retracement Levels --
FIB_LEVEL_382   = 0.382
FIB_LEVEL_500   = 0.500
FIB_LEVEL_618   = 0.618
FIB_LEVEL_786   = 0.786

FIB_ENTRY_TOLERANCE   = 8

# -- Fibonacci Extension Targets --
FIB_EXT_1272    = 1.272
FIB_EXT_1618    = 1.618

# -- Bounce Confirmation --
BOUNCE_MIN_CANDLES    = 2
BOUNCE_MAX_CANDLES    = 8

# -- Risk (ADAPTIVE PERCENTAGE + RR RATIO) --
SL_PERCENT_LOW    = 20.0
SL_PERCENT_MID    = 16.0
SL_PERCENT_HIGH   = 12.0
RR_RATIO          = 2.0
MIN_RR_RATIO      = 2.0

# -- Capital risk --
CAPITAL_RUPEES        = 50000
RISK_PER_TRADE_PCT    = 6.0
MAX_RISK_RUPEES       = CAPITAL_RUPEES * RISK_PER_TRADE_PCT / 100
MAX_DAILY_LOSS_RUPEES = MAX_RISK_RUPEES

# -- Hold time and catastrophic SL --
MIN_HOLD_MINUTES      = 8
CATASTROPHIC_MAX_LOSS = 2000

# -- Other limits --
MAX_TRADES_DAY            = 1
MIN_OPTION_PREMIUM        = 50
MAX_OPTION_PREMIUM        = 400
MAX_SPREAD_PCT            = 2.5
MAX_CAPITAL_EXPOSURE_PCT  = 100
SL_BUFFER_POINTS          = 5

# -- Time --
NO_TRADE_AFTER_HOUR  = 15
NO_TRADE_AFTER_MIN   = 00
SQUAREOFF_HOUR       = 15
SQUAREOFF_MIN        = 10

# -- Market regime (used as secondary filters) --
ADX_LEN              = 14
ATR_LEN              = 14
RSI_LEN              = 14
MIN_ADX_FOR_TRADE    = 15

# -- WebSocket monitor --
WS_TICK_LOG_INTERVAL = 30
WS_HEARTBEAT_SEC     = 60
TRAILING_SL_ENABLED  = True
TRAILING_SL_TRIGGER  = 0.35
TRAILING_SL_STEP     = 0.55

# -- Expiry --
NIFTY_EXPIRY_WEEKDAY = 1

# -- Files --
STATE_FILE    = "/root/scalper/state.json"
TOKEN_FILE    = "/root/scalper/token.json"
CANDLE_FILE   = "/root/scalper/candles.json"
FIB_FILE      = "/root/scalper/fib.json"
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

def safe(s, idx=-1):
    try:
        return s[idx]
    except:
        return None

# =============================================================
#  SECTION 3 - FIBONACCI SIGNAL ENGINE
# =============================================================

def load_fib():
    today = ist_now().strftime("%Y-%m-%d")
    try:
        with open(FIB_FILE) as f:
            data = json.load(f)
        if data.get("date") == today:
            return data
    except:
        pass
    return None

def save_fib(data):
    with open(FIB_FILE, "w") as f:
        json.dump(data, f, indent=2)

def compute_impulse_leg(candles):
    today = ist_now().date()
    impulse_candles = []

    impulse_start = datetime.time(IMPULSE_START_HOUR, IMPULSE_START_MIN)
    impulse_end = datetime.time(IMPULSE_END_HOUR, IMPULSE_END_MIN)

    logging.info("IMPULSE SCAN | Looking for candles %s to %s on %s" % (
        impulse_start.strftime("%H:%M"), impulse_end.strftime("%H:%M"), str(today)))
    logging.info("IMPULSE SCAN | Total candles in buffer: %d" % len(candles))

    today_candle_count = 0
    for c in candles:
        ts = c.get("ts", "")
        if not ts:
            continue
        try:
            dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except:
            try:
                dt = datetime.datetime.strptime(ts.replace("T", " ").split(".")[0].split("+")[0], "%Y-%m-%d %H:%M:%S")
            except:
                continue

        if dt.date() != today:
            continue
        today_candle_count += 1
        t = dt.time()

        if impulse_start <= t < impulse_end:
            impulse_candles.append(c)

    logging.info("IMPULSE SCAN | Today's candles: %d | Impulse window candles: %d" % (
        today_candle_count, len(impulse_candles)))

    if len(impulse_candles) < 2:
        logging.warning("IMPULSE SCAN | FAILED: Only %d candles in window (need >= 2)" % len(impulse_candles))
        if today_candle_count > 0:
            today_ts = []
            for c in candles:
                ts = c.get("ts", "")
                try:
                    dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                    if dt.date() == today:
                        today_ts.append(ts)
                except:
                    pass
            if today_ts:
                logging.info("IMPULSE SCAN | Today's candle range: %s to %s" % (today_ts[0], today_ts[-1]))
        return None

    swing_high = max(c["high"] for c in impulse_candles)
    swing_low = min(c["low"] for c in impulse_candles)
    impulse_size = swing_high - swing_low

    logging.info("IMPULSE SCAN | Swing H:%.2f L:%.2f Size:%.2f pts" % (swing_high, swing_low, impulse_size))

    if impulse_size < MIN_IMPULSE_POINTS:
        logging.warning("IMPULSE SCAN | FAILED: Size %.1f < min %d pts" % (impulse_size, MIN_IMPULSE_POINTS))
        return None
    if impulse_size > MAX_IMPULSE_POINTS:
        logging.warning("IMPULSE SCAN | FAILED: Size %.1f > max %d pts" % (impulse_size, MAX_IMPULSE_POINTS))
        return None

    first_open = impulse_candles[0]["open"]
    last_close = impulse_candles[-1]["close"]

    high_idx = max(range(len(impulse_candles)), key=lambda i: impulse_candles[i]["high"])
    low_idx = min(range(len(impulse_candles)), key=lambda i: impulse_candles[i]["low"])

    if last_close > first_open and high_idx >= low_idx:
        direction = "BULL"
    elif last_close < first_open and low_idx >= high_idx:
        direction = "BEAR"
    else:
        if last_close > first_open:
            direction = "BULL"
        elif last_close < first_open:
            direction = "BEAR"
        else:
            if high_idx > low_idx:
                direction = "BULL"
            elif low_idx > high_idx:
                direction = "BEAR"
            else:
                logging.warning("IMPULSE SCAN | FAILED: Perfect doji impulse")
                return None

    if direction == "BULL":
        fib_382 = round(swing_high - (impulse_size * FIB_LEVEL_382), 2)
        fib_500 = round(swing_high - (impulse_size * FIB_LEVEL_500), 2)
        fib_618 = round(swing_high - (impulse_size * FIB_LEVEL_618), 2)
        fib_786 = round(swing_high - (impulse_size * FIB_LEVEL_786), 2)
        ext_1272 = round(swing_low + (impulse_size * FIB_EXT_1272), 2)
        ext_1618 = round(swing_low + (impulse_size * FIB_EXT_1618), 2)
    else:
        fib_382 = round(swing_low + (impulse_size * FIB_LEVEL_382), 2)
        fib_500 = round(swing_low + (impulse_size * FIB_LEVEL_500), 2)
        fib_618 = round(swing_low + (impulse_size * FIB_LEVEL_618), 2)
        fib_786 = round(swing_low + (impulse_size * FIB_LEVEL_786), 2)
        ext_1272 = round(swing_high - (impulse_size * FIB_EXT_1272), 2)
        ext_1618 = round(swing_high - (impulse_size * FIB_EXT_1618), 2)

    logging.info("IMPULSE SCAN | SUCCESS: %s | %d candles | %.1f pts" % (
        direction, len(impulse_candles), impulse_size))

    return {
        "date": ist_now().strftime("%Y-%m-%d"),
        "direction": direction,
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
        "impulse_size": round(impulse_size, 2),
        "impulse_open": round(first_open, 2),
        "impulse_close": round(last_close, 2),
        "impulse_candles": len(impulse_candles),
        "fib_382": fib_382,
        "fib_500": fib_500,
        "fib_618": fib_618,
        "fib_786": fib_786,
        "ext_1272": ext_1272,
        "ext_1618": ext_1618,
        "computed_at": ist_now().strftime("%H:%M:%S"),
    }

def _find_nearest_fib_level(price, fib_data):
    levels = [
        ("38.2%", fib_data["fib_382"]),
        ("50.0%", fib_data["fib_500"]),
        ("61.8%", fib_data["fib_618"]),
    ]
    best_name, best_val, best_dist = None, None, float("inf")
    for name, val in levels:
        dist = abs(price - val)
        if dist < best_dist:
            best_name, best_val, best_dist = name, val, dist
    return best_name, best_val, best_dist

def _check_bounce(candles, fib_level, direction, tolerance):
    if len(candles) < BOUNCE_MIN_CANDLES:
        return False, 0, 0.0

    recent = candles[-(BOUNCE_MAX_CANDLES + 2):]
    candles_near_level = 0
    touched_level = False

    for c in recent:
        low = c["low"]
        high = c["high"]

        if direction == "BULL":
            if low <= fib_level + tolerance and low >= fib_level - tolerance:
                candles_near_level += 1
                touched_level = True
            elif high <= fib_level + tolerance and high >= fib_level - tolerance:
                candles_near_level += 1
                touched_level = True
        else:
            if high >= fib_level - tolerance and high <= fib_level + tolerance:
                candles_near_level += 1
                touched_level = True
            elif low >= fib_level - tolerance and low <= fib_level + tolerance:
                candles_near_level += 1
                touched_level = True

    if not touched_level or candles_near_level < BOUNCE_MIN_CANDLES:
        return False, candles_near_level, 0.0

    last = candles[-1]

    if direction == "BULL":
        bounce_confirmed = (last["close"] > last["open"] and
                           last["close"] > fib_level and
                           last["low"] >= fib_level - tolerance)
        bounce_strength = (last["close"] - fib_level) / tolerance if tolerance > 0 else 0
    else:
        bounce_confirmed = (last["close"] < last["open"] and
                           last["close"] < fib_level and
                           last["high"] <= fib_level + tolerance)
        bounce_strength = (fib_level - last["close"]) / tolerance if tolerance > 0 else 0

    return bounce_confirmed, candles_near_level, round(bounce_strength, 2)

def compute_signal(candles, fib_data):
    if not fib_data or not candles:
        return {"signal": "NO_TRADE", "details": {"reason": "No data"}}

    direction = fib_data["direction"]
    swing_high = fib_data["swing_high"]
    swing_low = fib_data["swing_low"]
    impulse_size = fib_data["impulse_size"]

    details = {
        "direction": direction,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "impulse_size": impulse_size,
        "fib_382": fib_data["fib_382"],
        "fib_500": fib_data["fib_500"],
        "fib_618": fib_data["fib_618"],
        "fib_786": fib_data["fib_786"],
        "ext_1272": fib_data["ext_1272"],
        "ext_1618": fib_data["ext_1618"],
    }

    now = ist_now()

    if now.hour > NO_TRADE_AFTER_HOUR or (now.hour == NO_TRADE_AFTER_HOUR and now.minute >= NO_TRADE_AFTER_MIN):
        details["reason"] = "Past %d:%02d" % (NO_TRADE_AFTER_HOUR, NO_TRADE_AFTER_MIN)
        return {"signal": "NO_TRADE", "details": details}

    impulse_end_time = now.replace(hour=IMPULSE_END_HOUR, minute=IMPULSE_END_MIN, second=0)
    if now < impulse_end_time:
        details["reason"] = "Impulse leg forming until %d:%02d" % (IMPULSE_END_HOUR, IMPULSE_END_MIN)
        return {"signal": "NO_TRADE", "details": details}

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    if len(closes) < 30:
        details["reason"] = "Need 30 candles, have %d" % len(closes)
        return {"signal": "NO_TRADE", "details": details}

    last_close = closes[-1]
    details["close"] = round(last_close, 2)

    fib_786 = fib_data["fib_786"]

    if direction == "BULL" and last_close < fib_786:
        details["reason"] = "Impulse invalidated: price %.1f below 78.6%% fib (%.1f)" % (last_close, fib_786)
        return {"signal": "NO_TRADE", "details": details}
    if direction == "BEAR" and last_close > fib_786:
        details["reason"] = "Impulse invalidated: price %.1f above 78.6%% fib (%.1f)" % (last_close, fib_786)
        return {"signal": "NO_TRADE", "details": details}

    if direction == "BULL" and last_close > fib_data["ext_1272"]:
        details["reason"] = "Price already at 127.2%% ext (%.1f) - missed pullback" % last_close
        return {"signal": "NO_TRADE", "details": details}
    if direction == "BEAR" and last_close < fib_data["ext_1272"]:
        details["reason"] = "Price already at 127.2%% ext (%.1f) - missed pullback" % last_close
        return {"signal": "NO_TRADE", "details": details}

    adx_s, pdi_s, mdi_s = calc_adx(highs, lows, closes, ADX_LEN)
    adx = safe(adx_s)
    rsi_s = calc_rsi(closes, RSI_LEN)
    rsi = safe(rsi_s)
    atr_s = calc_atr(highs, lows, closes, ATR_LEN)
    atr = safe(atr_s)

    details.update({
        "adx": round(adx, 1) if adx else "N/A",
        "rsi": round(rsi, 1) if rsi else "N/A",
        "atr": round(atr, 1) if atr else "N/A",
    })

    if adx is not None and adx < MIN_ADX_FOR_TRADE:
        details["reason"] = "Sideways: ADX %.1f < %d (fib needs trend)" % (adx, MIN_ADX_FOR_TRADE)
        return {"signal": "NO_TRADE", "details": details}

    fib_name, fib_value, fib_distance = _find_nearest_fib_level(last_close, fib_data)
    details["nearest_fib"] = fib_name
    details["nearest_fib_value"] = fib_value
    details["fib_distance"] = round(fib_distance, 2)

    if fib_distance > FIB_ENTRY_TOLERANCE:
        details["reason"] = "Price %.1f not near any fib level (nearest: %s at %.1f, dist: %.1f > tol %d)" % (
            last_close, fib_name, fib_value, fib_distance, FIB_ENTRY_TOLERANCE)
        return {"signal": "NO_TRADE", "details": details}

    today = ist_now().date()
    post_impulse_candles = []
    for c in candles:
        ts = c.get("ts", "")
        if not ts:
            continue
        try:
            dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except:
            continue
        if dt.date() == today and dt.time() >= datetime.time(IMPULSE_END_HOUR, IMPULSE_END_MIN):
            post_impulse_candles.append(c)

    is_bouncing, candles_at_level, bounce_strength = _check_bounce(
        post_impulse_candles, fib_value, direction, FIB_ENTRY_TOLERANCE)

    details["bounce_confirmed"] = is_bouncing
    details["candles_at_fib"] = candles_at_level
    details["bounce_strength"] = bounce_strength

    if not is_bouncing:
        details["reason"] = "No bounce at %s (%.1f) - candles_near: %d, need %d+ confirmed" % (
            fib_name, fib_value, candles_at_level, BOUNCE_MIN_CANDLES)
        return {"signal": "NO_TRADE", "details": details}

    if direction == "BULL" and rsi is not None and rsi > 75:
        details["reason"] = "RSI overbought at fib bounce: %.0f" % rsi
        return {"signal": "NO_TRADE", "details": details}
    if direction == "BEAR" and rsi is not None and rsi < 25:
        details["reason"] = "RSI oversold at fib bounce: %.0f" % rsi
        return {"signal": "NO_TRADE", "details": details}

    last_candle = candles[-1]
    if direction == "BULL" and last_candle["close"] <= last_candle["open"]:
        details["reason"] = "BULL bounce but last candle is red"
        return {"signal": "NO_TRADE", "details": details}
    if direction == "BEAR" and last_candle["close"] >= last_candle["open"]:
        details["reason"] = "BEAR bounce but last candle is green"
        return {"signal": "NO_TRADE", "details": details}

    last_body = abs(last_candle["close"] - last_candle["open"])
    last_range = last_candle["high"] - last_candle["low"]
    if last_range > 0:
        body_ratio = last_body / last_range
        details["candle_body_pct"] = round(body_ratio * 100, 1)
        if body_ratio < 0.4:
            details["reason"] = "Weak bounce candle: body %d%% of range (need 40%%+)" % round(body_ratio * 100)
            return {"signal": "NO_TRADE", "details": details}
    else:
        details["reason"] = "Zero-range candle (doji) at fib level"
        return {"signal": "NO_TRADE", "details": details}

    recent_volumes = [c.get("volume", 0) for c in candles[-20:]]
    avg_vol = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
    current_vol = last_candle.get("volume", 0)
    if avg_vol > 0:
        vol_ratio = current_vol / avg_vol
        details["vol_ratio"] = round(vol_ratio, 2)
        if vol_ratio < 0.8:
            details["reason"] = "Low volume bounce: %.1fx avg (need 0.8x+)" % vol_ratio
            return {"signal": "NO_TRADE", "details": details}
    else:
        details["vol_ratio"] = "N/A"

    is_late = now.hour > 10 or (now.hour == 10 and now.minute >= 30)
    details["late_entry"] = is_late
    if is_late:
        if fib_name != "61.8%":
            details["reason"] = "Late entry: only 61.8%% fib accepted, got %s" % fib_name
            return {"signal": "NO_TRADE", "details": details}
        if bounce_strength < 1.5:
            details["reason"] = "Late entry: weak bounce strength %.1f (need 1.5+)" % bounce_strength
            return {"signal": "NO_TRADE", "details": details}

    if direction == "BULL":
        if fib_name == "38.2%":
            fib_sl_level = fib_data["fib_500"] - SL_BUFFER_POINTS
        elif fib_name == "50.0%":
            fib_sl_level = fib_data["fib_618"] - SL_BUFFER_POINTS
        else:
            fib_sl_level = fib_data["fib_786"] - SL_BUFFER_POINTS
        nifty_target = fib_data["ext_1272"]
    else:
        if fib_name == "38.2%":
            fib_sl_level = fib_data["fib_500"] + SL_BUFFER_POINTS
        elif fib_name == "50.0%":
            fib_sl_level = fib_data["fib_618"] + SL_BUFFER_POINTS
        else:
            fib_sl_level = fib_data["fib_786"] + SL_BUFFER_POINTS
        nifty_target = fib_data["ext_1272"]

    details["fib_sl_level"] = round(fib_sl_level, 2)
    details["nifty_target"] = round(nifty_target, 2)

    if direction == "BULL":
        nifty_risk = last_close - fib_sl_level
        nifty_reward = nifty_target - last_close
    else:
        nifty_risk = fib_sl_level - last_close
        nifty_reward = last_close - nifty_target

    if nifty_risk <= 0:
        details["reason"] = "Invalid SL: risk=%.1f" % nifty_risk
        return {"signal": "NO_TRADE", "details": details}

    nifty_rr = nifty_reward / nifty_risk
    details["nifty_rr"] = round(nifty_rr, 2)

    if nifty_rr < MIN_RR_RATIO:
        details["reason"] = "Nifty RR %.1f < %.1f minimum" % (nifty_rr, MIN_RR_RATIO)
        return {"signal": "NO_TRADE", "details": details}

    score = 0
    score += 1
    score += 1 if fib_name == "61.8%" else 0
    score += 1 if bounce_strength >= 1.5 else 0
    score += 1 if candles_at_level >= 3 else 0
    score += 1 if adx is not None and adx >= 20 else 0
    score += 1 if (direction == "BULL" and rsi is not None and 40 < rsi < 65) else (
                 1 if (direction == "BEAR" and rsi is not None and 35 < rsi < 60) else 0)

    details["fib_score"] = "%d/6" % score
    confidence = "HIGH" if score >= 4 else ("MED" if score >= 3 else "LOW")

    signal_type = "CE_BUY" if direction == "BULL" else "PE_BUY"

    trigger_tag = "FIB_%s_BOUNCE" % fib_name.replace(".", "").replace("%", "")
    details["trigger"] = trigger_tag
    details["entry_fib_level"] = fib_name

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
            self._check_impulse_formed(),
            self._check_time_window(),
            self._check_max_trades(),
            self._check_daily_loss(),
        ]
        if not PAPER_TRADE:
            checks.append(self._check_open_positions(groww))
        for passed, reason in checks:
            if not passed:
                return False, reason
        return True, "All risk checks passed"

    def _check_impulse_formed(self):
        now = ist_now()
        impulse_end = now.replace(hour=IMPULSE_END_HOUR, minute=IMPULSE_END_MIN, second=0)
        if now < impulse_end:
            return False, "Impulse forming: %d min" % int((impulse_end - now).total_seconds() / 60)
        return True, "Impulse formed"

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

def calc_sl_tp(entry_price, qty):
    sl_pct = get_sl_percent(entry_price)
    sl_drop = entry_price * sl_pct / 100
    tp_rise = sl_drop * RR_RATIO

    if sl_drop * qty > MAX_RISK_RUPEES:
        sl_drop = MAX_RISK_RUPEES / qty
        tp_rise = sl_drop * RR_RATIO
        sl_pct = sl_drop / entry_price * 100

    sl_price = round(max(entry_price - sl_drop, 1.0), 1)
    target_price = round(entry_price + tp_rise, 1)
    rr = tp_rise / sl_drop if sl_drop > 0 else 0

    return sl_price, target_price, sl_drop, tp_rise, sl_pct, rr

def get_catastrophic_sl(entry_price, qty):
    max_drop = CATASTROPHIC_MAX_LOSS / qty
    return round(max(entry_price - max_drop, 1.0), 1)

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
#  SECTION 7 - FETCH CANDLES (MULTI-METHOD WITH FALLBACKS)
# =============================================================

def _parse_candles_list(raw):
    """Parse candles returned as list of lists (old API format)."""
    result = []
    for c in raw:
        if not isinstance(c, (list, tuple)) or len(c) < 5:
            continue
        t = c[0]
        if isinstance(t, (int, float)):
            if t > 1e12:
                t = t / 1000
            dt = (datetime.datetime.fromtimestamp(t, datetime.timezone.utc).replace(tzinfo=None)
                  + datetime.timedelta(hours=5, minutes=30))
            ts = dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts = str(t).replace("T", " ").split(".")[0].split("+")[0] if t is not None else ""
        result.append({
            "ts": ts, "open": float(c[1]), "high": float(c[2]),
            "low": float(c[3]), "close": float(c[4]),
            "volume": float(c[5]) if len(c) > 5 and c[5] is not None else 0.0,
        })
    return result

def _parse_candles_dict(raw_list):
    """Parse candles returned as list of dicts (new API format)."""
    result = []
    for c in raw_list:
        if isinstance(c, dict):
            ts = ""
            t = c.get("timestamp") or c.get("time") or c.get("date") or c.get("ts") or c.get("candle_timestamp") or ""
            if isinstance(t, (int, float)):
                if t > 1e12:
                    t = t / 1000
                dt = (datetime.datetime.fromtimestamp(t, datetime.timezone.utc).replace(tzinfo=None)
                      + datetime.timedelta(hours=5, minutes=30))
                ts = dt.strftime("%Y-%m-%d %H:%M:%S")
            elif t:
                ts = str(t).replace("T", " ").split(".")[0].split("+")[0]
            result.append({
                "ts": ts,
                "open": float(c.get("open", 0)),
                "high": float(c.get("high", 0)),
                "low": float(c.get("low", 0)),
                "close": float(c.get("close", 0)),
                "volume": float(c.get("volume", 0)),
            })
        elif isinstance(c, (list, tuple)):
            parsed = _parse_candles_list([c])
            result.extend(parsed)
    return result

def _parse_any_candles(raw):
    """Auto-detect format and parse."""
    if not raw:
        return []
    if isinstance(raw[0], dict):
        return _parse_candles_dict(raw)
    else:
        return _parse_candles_list(raw)

def _extract_raw(res):
    """Extract raw candle list from various response shapes."""
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        for key in ["candles", "data", "records", "result"]:
            if key in res and isinstance(res[key], list):
                return res[key]
    return []

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

    # Also prepare epoch millis versions
    try:
        start_epoch = int(datetime.datetime.strptime(start_dt, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30))).timestamp() * 1000)
        end_epoch = int(datetime.datetime.strptime(end_dt, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30))).timestamp() * 1000)
    except:
        start_epoch = None
        end_epoch = None

    raw = []
    method_used = ""

    # METHOD 1: New API - get_historical_candles (Backtesting endpoint)
    if not raw:
        try:
            res = groww.get_historical_candles(
                trading_symbol="NIFTY", exchange="NSE", segment="CASH",
                start_time=start_dt, end_time=end_dt, interval_in_minutes=5)
            raw = _extract_raw(res)
            if raw:
                method_used = "get_historical_candles(str)"
                logging.info("Candle OK via %s: %d raw" % (method_used, len(raw)))
        except AttributeError:
            logging.info("get_historical_candles not in SDK - try upgrading: pip install --upgrade growwapi")
        except Exception as e:
            logging.warning("get_historical_candles(str) failed: %s" % str(e))

    # METHOD 2: New API with epoch millis
    if not raw and start_epoch:
        try:
            res = groww.get_historical_candles(
                trading_symbol="NIFTY", exchange="NSE", segment="CASH",
                start_time=start_epoch, end_time=end_epoch, interval_in_minutes=5)
            raw = _extract_raw(res)
            if raw:
                method_used = "get_historical_candles(epoch)"
                logging.info("Candle OK via %s: %d raw" % (method_used, len(raw)))
        except AttributeError:
            pass
        except Exception as e:
            logging.warning("get_historical_candles(epoch) failed: %s" % str(e))

    # METHOD 3: Old deprecated API (with warning suppression)
    if not raw:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                res = groww.get_historical_candle_data(
                    trading_symbol="NIFTY", exchange="NSE", segment="CASH",
                    start_time=start_dt, end_time=end_dt, interval_in_minutes=5)
            raw = _extract_raw(res)
            if raw:
                method_used = "get_historical_candle_data(str)"
                logging.info("Candle OK via %s: %d raw" % (method_used, len(raw)))
        except Exception as e:
            logging.warning("get_historical_candle_data(str) failed: %s" % str(e))

    # METHOD 4: Old deprecated API with epoch millis
    if not raw and start_epoch:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                res = groww.get_historical_candle_data(
                    trading_symbol="NIFTY", exchange="NSE", segment="CASH",
                    start_time=start_epoch, end_time=end_epoch, interval_in_minutes=5)
            raw = _extract_raw(res)
            if raw:
                method_used = "get_historical_candle_data(epoch)"
                logging.info("Candle OK via %s: %d raw" % (method_used, len(raw)))
        except Exception as e:
            logging.warning("get_historical_candle_data(epoch) failed: %s" % str(e))

    # METHOD 5: Try "NIFTY 50" as symbol
    if not raw:
        for sym in ["NIFTY 50", "NIFTY50"]:
            for fn_name in ["get_historical_candles", "get_historical_candle_data"]:
                fn = getattr(groww, fn_name, None)
                if fn is None:
                    continue
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", DeprecationWarning)
                        res = fn(trading_symbol=sym, exchange="NSE", segment="CASH",
                                 start_time=start_dt, end_time=end_dt, interval_in_minutes=5)
                    raw = _extract_raw(res)
                    if raw:
                        method_used = "%s(%s)" % (fn_name, sym)
                        logging.info("Candle OK via %s: %d raw" % (method_used, len(raw)))
                        break
                except:
                    continue
            if raw:
                break

    # PROCESS RESULTS
    if raw:
        new_candles = _parse_any_candles(raw)

        if new_candles:
            if is_incremental:
                existing_ts = {c["ts"] for c in existing if c.get("ts")}
                merged = existing + [c for c in new_candles if c.get("ts") not in existing_ts]
            else:
                merged = new_candles

            cache["candles"] = merged[-300:]
            cache["date"] = today
            _save_candles(cache)

            today_count = sum(1 for c in cache["candles"] if c.get("ts", "").startswith(today))
            logging.info("Candles: %d total | %d today | method=%s | incr=%s" % (
                len(cache["candles"]), today_count, method_used, str(is_incremental)))
            return cache["candles"]
        else:
            logging.warning("Raw candles received (%d) but parsing returned 0" % len(raw))

    # ALL METHODS FAILED - diagnostic
    logging.error("ALL candle fetch methods failed")
    try:
        methods = [m for m in dir(groww) if 'candle' in m.lower() or 'histor' in m.lower()]
        logging.info("Available candle methods: %s" % str(methods))
    except:
        pass

    if existing:
        today_count = sum(1 for c in existing if c.get("ts", "").startswith(today))
        logging.info("Using cached: %d total, %d today" % (len(existing), today_count))
        if today_count == 0:
            logging.error("CRITICAL: No today's candles. Run: pip install --upgrade growwapi")
        return existing

    return []

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

    sl_price, target_price, sl_drop, tp_rise, sl_pct, actual_rr = calc_sl_tp(entry_premium, qty)
    catastrophic_sl = get_catastrophic_sl(entry_premium, qty)

    logging.info("=== WS MONITOR START ===")
    logging.info("  Symbol: %s | Qty: %d" % (symbol, qty))
    logging.info("  Entry: Rs.%.1f | Band: %s" % (
        entry_premium,
        "LOW" if entry_premium <= 100 else ("MID" if entry_premium <= 250 else "HIGH")))
    logging.info("  SL: Rs.%.1f (-%.1f%%) | Target: Rs.%.1f (+%.1f%%)" % (
        sl_price, sl_pct, target_price, tp_rise / entry_premium * 100))
    logging.info("  Risk: Rs.%.0f | Reward: Rs.%.0f | RR 1:%.1f" % (
        sl_drop * qty, tp_rise * qty, actual_rr))
    logging.info("  Hold: %d min | Catastrophic SL: Rs.%.1f (max Rs.%d)" % (
        MIN_HOLD_MINUTES, catastrophic_sl, CATASTROPHIC_MAX_LOSS))

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

        if now_ts - monitor_state["last_log_time"] >= WS_TICK_LOG_INTERVAL:
            pnl = (current_ltp - entry_premium) * qty
            pnl_pct = (current_ltp - entry_premium) / entry_premium * 100
            logging.info("  TICK | LTP:%.1f | P&L:Rs.%+.0f (%+.1f%%) | SL:%.1f | T:%.1f" % (
                current_ltp, pnl, pnl_pct, monitor_state["trailing_sl"], target_price))
            monitor_state["last_log_time"] = now_ts

        if now_ts - monitor_state["last_heartbeat"] >= WS_HEARTBEAT_SEC:
            logging.info("  HEARTBEAT | LTP:%.1f" % current_ltp)
            monitor_state["last_heartbeat"] = now_ts

        now_ist = ist_now()
        if now_ist.hour > SQUAREOFF_HOUR or (now_ist.hour == SQUAREOFF_HOUR and now_ist.minute >= SQUAREOFF_MIN):
            pnl = (current_ltp - entry_premium) * qty
            _do_exit(current_ltp, pnl, "EOD SQUAREOFF Rs.%+.0f" % pnl)
            return

        if current_ltp >= target_price:
            pnl = (current_ltp - entry_premium) * qty
            _do_exit(current_ltp, pnl, "TAKE PROFIT Rs.%+.0f" % pnl)
            return

        minutes_held = (now_ist - entry_time).total_seconds() / 60

        if minutes_held < MIN_HOLD_MINUTES:
            if current_ltp <= catastrophic_sl:
                pnl = (current_ltp - entry_premium) * qty
                _do_exit(current_ltp, pnl, "CATASTROPHIC SL Rs.%+.0f" % pnl)
            return

        if TRAILING_SL_ENABLED and current_ltp > monitor_state["highest_ltp"]:
            monitor_state["highest_ltp"] = current_ltp
            profit = current_ltp - entry_premium
            if profit >= tp_rise * TRAILING_SL_TRIGGER:
                new_sl = round(entry_premium + (profit * TRAILING_SL_STEP), 1)
                if new_sl > monitor_state["trailing_sl"]:
                    old_sl = monitor_state["trailing_sl"]
                    monitor_state["trailing_sl"] = new_sl
                    logging.info("  TRAIL SL: Rs.%.1f -> Rs.%.1f" % (old_sl, new_sl))

        if current_ltp <= monitor_state["trailing_sl"]:
            pnl = (current_ltp - entry_premium) * qty
            _do_exit(current_ltp, pnl, "STOP LOSS Rs.%+.0f" % pnl)
            return

    def _do_exit(current_ltp, pnl, reason):
        if monitor_state["exited"]:
            return
        monitor_state["exited"] = True

        logging.info("=== EXIT ===")
        logging.info("  %s" % reason)
        logging.info("  LTP:%.1f | Entry:%.1f | P&L:Rs.%+.0f" % (current_ltp, entry_premium, pnl))

        place_exit_order(groww, symbol, qty, reason)

        trade["exited"] = True
        trade["exit_ltp"] = current_ltp
        trade["exit_pnl"] = round(pnl, 2)
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
                pnl = (final_ltp - entry_premium) * qty
                _do_exit(final_ltp, pnl, "SHUTDOWN Rs.%+.0f" % pnl)
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
    entry_premium = trade["entry_premium"]
    entry_time = datetime.datetime.strptime(trade["time"], "%Y-%m-%d %H:%M:%S")

    sl_price, target_price, sl_drop, tp_rise, sl_pct, rr = calc_sl_tp(entry_premium, qty)
    catastrophic_sl = get_catastrophic_sl(entry_premium, qty)

    trailing_sl = sl_price
    highest_ltp = entry_premium

    logging.info("POLL MONITOR | %s | SL:%.1f | T:%.1f | Cat:%.1f" % (
        symbol, sl_price, target_price, catastrophic_sl))
    write_monitor_pid()

    last_log = 0

    try:
        while True:
            now = ist_now()

            if now.hour > SQUAREOFF_HOUR or (now.hour == SQUAREOFF_HOUR and now.minute >= SQUAREOFF_MIN):
                current_ltp = get_option_ltp(groww, symbol) or entry_premium
                pnl = (current_ltp - entry_premium) * qty
                place_exit_order(groww, symbol, qty, "EOD SQUAREOFF Rs.%+.0f" % pnl)
                trade["exited"] = True
                trade["exit_ltp"] = current_ltp
                trade["exit_pnl"] = round(pnl, 2)
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

            if current_ltp >= target_price:
                place_exit_order(groww, symbol, qty, "TP Rs.%+.0f" % pnl)
                trade["exited"] = True
                trade["exit_ltp"] = current_ltp
                trade["exit_pnl"] = round(pnl, 2)
                trade["exit_reason"] = "TAKE_PROFIT"
                trade["exit_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
                state["daily_pnl_rupees"] = state.get("daily_pnl_rupees", 0) + pnl
                save_state(state)
                break

            if minutes_held < MIN_HOLD_MINUTES:
                if current_ltp <= catastrophic_sl:
                    place_exit_order(groww, symbol, qty, "CATASTROPHIC SL Rs.%+.0f" % pnl)
                    trade["exited"] = True
                    trade["exit_ltp"] = current_ltp
                    trade["exit_pnl"] = round(pnl, 2)
                    trade["exit_reason"] = "CATASTROPHIC_SL"
                    trade["exit_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
                    state["daily_pnl_rupees"] = state.get("daily_pnl_rupees", 0) + pnl
                    save_state(state)
                    break
                time.sleep(5)
                continue

            if TRAILING_SL_ENABLED and current_ltp > highest_ltp:
                highest_ltp = current_ltp
                profit = current_ltp - entry_premium
                if profit >= tp_rise * TRAILING_SL_TRIGGER:
                    new_sl = round(entry_premium + (profit * TRAILING_SL_STEP), 1)
                    if new_sl > trailing_sl:
                        logging.info("  TRAIL SL: Rs.%.1f -> Rs.%.1f" % (trailing_sl, new_sl))
                        trailing_sl = new_sl

            if current_ltp <= trailing_sl:
                place_exit_order(groww, symbol, qty, "SL Rs.%+.0f" % pnl)
                trade["exited"] = True
                trade["exit_ltp"] = current_ltp
                trade["exit_pnl"] = round(pnl, 2)
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

    # Diagnostic: check today's candles exist
    today_candles = [c for c in candles if c.get("ts", "").startswith(now.strftime("%Y-%m-%d"))]
    if not today_candles:
        logging.error("CRITICAL: 0 candles from today in buffer of %d" % len(candles))
        logging.error("Cached range: %s to %s" % (
            candles[0].get("ts", "?"), candles[-1].get("ts", "?")))
        logging.error("FIX: Run 'pip install --upgrade growwapi' on your VPS")
        return
    else:
        logging.info("Today's candles: %d | First: %s | Last: %s" % (
            len(today_candles), today_candles[0]["ts"], today_candles[-1]["ts"]))

    fib_data = load_fib()
    if fib_data is None:
        if ist_now() < ist_now().replace(hour=IMPULSE_END_HOUR, minute=IMPULSE_END_MIN, second=0):
            logging.info("Impulse leg forming until %d:%02d..." % (IMPULSE_END_HOUR, IMPULSE_END_MIN))
            return
        fib_data = compute_impulse_leg(candles)
        if fib_data is None:
            logging.error("Cannot compute impulse leg (too small/large or ambiguous)")
            return
        save_fib(fib_data)
        logging.info("FIB | Dir:%s | H:%.1f L:%.1f | Size:%.1f" % (
            fib_data["direction"], fib_data["swing_high"], fib_data["swing_low"], fib_data["impulse_size"]))
        logging.info("     38.2%%:%.1f | 50%%:%.1f | 61.8%%:%.1f | 78.6%%:%.1f" % (
            fib_data["fib_382"], fib_data["fib_500"], fib_data["fib_618"], fib_data["fib_786"]))
        logging.info("     Ext 127.2%%:%.1f | Ext 161.8%%:%.1f" % (
            fib_data["ext_1272"], fib_data["ext_1618"]))

    result = compute_signal(candles, fib_data)
    signal_type = result["signal"]
    confidence = result.get("confidence")
    d = result.get("details", {})

    logging.info("  Signal:%s | Conf:%s | %s" % (signal_type, str(confidence), d.get("trigger", "--")))
    logging.info("  Close:%s | Swing H/L:%s/%s | Impulse:%s" % (
        d.get("close", "--"), d.get("swing_high", "--"), d.get("swing_low", "--"), d.get("impulse_size", "--")))
    logging.info("  ADX:%s RSI:%s | Fib:%s(%.1f) Dist:%.1f | Score:%s" % (
        d.get("adx", "--"), d.get("rsi", "--"),
        d.get("nearest_fib", "--"), d.get("nearest_fib_value", 0), d.get("fib_distance", 0),
        d.get("fib_score", "--")))
    if d.get("bounce_confirmed"):
        logging.info("  Bounce: confirmed | Candles@fib:%s | Strength:%.1f" % (
            d.get("candles_at_fib", "--"), d.get("bounce_strength", 0)))
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

    sl_price, target_price, sl_drop, tp_rise, sl_pct, rr = calc_sl_tp(option_ltp, qty)
    catastrophic_sl = get_catastrophic_sl(option_ltp, qty)

    if rr < MIN_RR_RATIO:
        logging.warning("RR %.1f < %.1f minimum - REJECTED" % (rr, MIN_RR_RATIO))
        return

    total_risk = sl_drop * qty
    total_reward = tp_rise * qty
    premium_band = "LOW" if option_ltp <= 100 else ("MID" if option_ltp <= 250 else "HIGH")

    logging.info("PLAN | Entry:~Rs.%s | Band:%s" % (str(option_ltp), premium_band))
    logging.info("      SL:Rs.%s (-%.1f%%) | Target:Rs.%s (+%.1f%%)" % (
        str(sl_price), sl_pct,
        str(target_price), tp_rise / option_ltp * 100))
    logging.info("      Risk:Rs.%.0f | Reward:Rs.%.0f | RR 1:%.1f" % (total_risk, total_reward, rr))
    logging.info("      Hold:%dmin | Catastrophic SL:Rs.%.1f" % (MIN_HOLD_MINUTES, catastrophic_sl))

    oid = place_entry_order(groww, symbol, qty, groww.TRANSACTION_TYPE_BUY)
    if not oid:
        return

    time.sleep(1)

    if PAPER_TRADE:
        entry_premium = option_ltp
    else:
        entry_premium = get_option_ltp(groww, symbol) or option_ltp

    sl_price, target_price, sl_drop, tp_rise, sl_pct, rr = calc_sl_tp(entry_premium, qty)

    state["trade_count"] += 1
    state["trades"].append({
        "signal": signal_type, "confidence": confidence,
        "symbol": symbol, "qty": qty,
        "entry_id": str(oid),
        "entry_premium": entry_premium,
        "risk_premium": sl_drop,
        "target_premium": tp_rise,
        "sl_percent": sl_pct,
        "rr_ratio": rr,
        "target": target_price, "sl": sl_price,
        "nifty_ltp": nifty_ltp, "strike": strike,
        "swing_high": fib_data["swing_high"],
        "swing_low": fib_data["swing_low"],
        "impulse_direction": fib_data["direction"],
        "impulse_size": fib_data["impulse_size"],
        "entry_fib_level": d.get("entry_fib_level", ""),
        "trigger": d.get("trigger", "unknown"),
        "fib_score": d.get("fib_score", ""),
        "nifty_rr": d.get("nifty_rr", 0),
        "rr": "1:%.1f" % rr,
        "paper": PAPER_TRADE,
        "exited": False,
        "time": now.strftime("%Y-%m-%d %H:%M:%S")
    })
    save_state(state)

    tag = "PAPER TRADE" if PAPER_TRADE else "LIVE TRADE"
    logging.info("%s | %s %s | %s" % (tag, signal_type, str(confidence), symbol))
    logging.info("   E:Rs.%s SL:Rs.%s(-%.1f%%) T:Rs.%s RR:1:%.1f" % (
        str(entry_premium), str(sl_price), sl_pct, str(target_price), rr))
    logging.info("   %s | Fib:%s | Score:%s" % (
        d.get("trigger", ""), d.get("entry_fib_level", ""), d.get("fib_score", "")))

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
