# ============================================================
#  NIFTY SNIPER v3.0 - S/R + ORB + VWAP (Simple & Profitable)
#  VPS (Hetzner + Groww API)
#
#  ARCHITECTURE:
#    - Cron runs every minute for signal scanning
#    - Once trade entered -> WebSocket monitors SL/TP
#
#  STRATEGY (SIMPLE - replaces BAG+ORB+FVG):
#    1. ORB  - 30-min range (9:15-9:45) defines the battlefield
#    2. S/R  - Previous day High/Low/Close as key levels
#    3. VWAP - Institutional bias filter
#
#  WHAT CHANGED FROM v2.1:
#    - Removed: FVG, BAG (gap), ADX, body ratio, vol ratio,
#               consecutive candles, ATR distance, counter-gap
#    - Added: S/R levels (PDH/PDL/PDC/Pivot), structural SL
#    - ORB: 15min -> 30min (more stable)
#    - RR: 1:2 -> 1:1.5 (more realistic, hits target more)
#    - Cutoff: 11:30 -> 13:00 (more opportunities)
#    - Hold: 8min -> 3min (less time in losers)
#    - Filters: 6+ -> 3 (VWAP + RSI extreme + EMA)
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
LOT_SIZE         = 65
LOTS_TO_TRADE    = 1
ITM_OFFSET       = 50

# -- PAPER TRADE MODE --
PAPER_TRADE      = False

# -- ORB (Opening Range Breakout) - 30 min --
ORB_BUFFER_PCT       = 0.15

# -- Support/Resistance --
SR_ZONE_POINTS       = 15

# -- Risk (STRUCTURAL SL - behind ORB level) --
SL_BUFFER_BEHIND_ORB = 10
MAX_SL_POINTS        = 30
MIN_SL_POINTS        = 8
RR_RATIO             = 1.5
MIN_RR_RATIO         = 1.5

# -- Capital risk --
CAPITAL_RUPEES        = 50000
MAX_RISK_RUPEES       = 3000
MAX_DAILY_LOSS_RUPEES = 3000

# -- Hold time --
MIN_HOLD_MINUTES      = 3
CATASTROPHIC_MAX_LOSS = 2500

# -- Other limits --
MAX_TRADES_DAY            = 1
MIN_OPTION_PREMIUM        = 80
MAX_OPTION_PREMIUM        = 350
MAX_SPREAD_PCT            = 2.0
MAX_CAPITAL_EXPOSURE_PCT  = 100

# -- Time --
NO_TRADE_AFTER_HOUR  = 13
NO_TRADE_AFTER_MIN   = 0
SQUAREOFF_HOUR       = 15
SQUAREOFF_MIN        = 10

# -- Indicators (minimal) --
RSI_LEN              = 14
EMA_FAST             = 9
EMA_SLOW             = 21
VWAP_SESSION_BARS    = 75

# -- WebSocket monitor --
WS_TICK_LOG_INTERVAL = 30
WS_HEARTBEAT_SEC     = 60
TRAILING_SL_ENABLED  = True
TRAILING_SL_TRIGGER  = 0.50
TRAILING_SL_STEP     = 0.40

# -- Expiry --
NIFTY_EXPIRY_WEEKDAY = 2

# -- Files --
STATE_FILE    = "/root/scalper/state.json"
TOKEN_FILE    = "/root/scalper/token.json"
CANDLE_FILE   = "/root/scalper/candles.json"
ORB_FILE      = "/root/scalper/orb.json"
SR_FILE       = "/root/scalper/sr_levels.json"
MONITOR_PID   = "/root/scalper/monitor.pid"

# =============================================================
#  SECTION 2 - INDICATORS (MINIMAL)
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
#  SECTION 3 - SUPPORT/RESISTANCE LEVELS
# =============================================================

def compute_sr_levels(candles):
    today = ist_now().date()
    prev_day_candles = []
    prev_date = None

    for c in reversed(candles):
        ts = c.get("ts", "")
        if not ts:
            continue
        try:
            dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except:
            continue
        if dt.date() < today:
            if prev_date is None:
                prev_date = dt.date()
            if dt.date() == prev_date:
                prev_day_candles.append(c)
            elif dt.date() < prev_date:
                break

    if not prev_day_candles:
        return None

    prev_day_candles.reverse()

    pdc = prev_day_candles[-1]["close"]
    pdh = max(c["high"] for c in prev_day_candles)
    pdl = min(c["low"] for c in prev_day_candles)

    pivot = (pdh + pdl + pdc) / 3
    r1 = 2 * pivot - pdl
    s1 = 2 * pivot - pdh
    r2 = pivot + (pdh - pdl)
    s2 = pivot - (pdh - pdl)

    return {
        "date": ist_now().strftime("%Y-%m-%d"),
        "prev_date": str(prev_date),
        "pdh": round(pdh, 2),
        "pdl": round(pdl, 2),
        "pdc": round(pdc, 2),
        "pivot": round(pivot, 2),
        "r1": round(r1, 2),
        "s1": round(s1, 2),
        "r2": round(r2, 2),
        "s2": round(s2, 2),
    }

def load_sr_levels():
    today = ist_now().strftime("%Y-%m-%d")
    try:
        with open(SR_FILE) as f:
            data = json.load(f)
        if data.get("date") == today:
            return data
    except:
        pass
    return None

def save_sr_levels(data):
    with open(SR_FILE, "w") as f:
        json.dump(data, f, indent=2)

def check_sr_confluence(price, direction, sr):
    levels = {
        "PDH": sr["pdh"], "PDL": sr["pdl"], "PDC": sr["pdc"],
        "Pivot": sr["pivot"], "R1": sr["r1"], "S1": sr["s1"],
    }
    if direction == "BULL":
        for name, level in levels.items():
            if level > 0 and abs(price - level) <= SR_ZONE_POINTS * 2:
                if price >= level:
                    return True, name, level
        for name, level in levels.items():
            if level > 0 and price > level and (price - level) <= SR_ZONE_POINTS * 3:
                return True, name + "_bounce", level
    else:
        for name, level in levels.items():
            if level > 0 and abs(price - level) <= SR_ZONE_POINTS * 2:
                if price <= level:
                    return True, name, level
        for name, level in levels.items():
            if level > 0 and price < level and (level - price) <= SR_ZONE_POINTS * 3:
                return True, name + "_reject", level
    return False, None, None

# =============================================================
#  SECTION 4 - ORB (30-min)
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

def compute_orb_levels(candles):
    orb_candles = []
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
        if datetime.time(9, 15) <= t < datetime.time(9, 45):
            orb_candles.append(c)

    if len(orb_candles) < 3:
        return None

    orb_high = max(c["high"] for c in orb_candles)
    orb_low = min(c["low"] for c in orb_candles)
    orb_range = orb_high - orb_low

    return {
        "date": ist_now().strftime("%Y-%m-%d"),
        "orb_high": round(orb_high, 2),
        "orb_low": round(orb_low, 2),
        "orb_range": round(orb_range, 2),
        "orb_mid": round((orb_high + orb_low) / 2, 2),
        "prev_close": round(prev_day_close, 2) if prev_day_close else None,
        "computed_at": ist_now().strftime("%H:%M:%S")
    }

# =============================================================
#  SECTION 5 - SIGNAL ENGINE (ORB + S/R + VWAP)
# =============================================================

def compute_signal(candles, orb, sr):
    if not orb or not candles:
        return {"signal": "NO_TRADE", "details": {"reason": "No data"}}

    orb_high = orb["orb_high"]
    orb_low = orb["orb_low"]
    orb_range = orb["orb_range"]
    prev_close = orb.get("prev_close")

    details = {
        "orb_high": orb_high, "orb_low": orb_low, "orb_range": orb_range,
    }

    now = ist_now()
    if now.hour > NO_TRADE_AFTER_HOUR or (now.hour == NO_TRADE_AFTER_HOUR and now.minute >= NO_TRADE_AFTER_MIN):
        details["reason"] = "Past %d:%02d" % (NO_TRADE_AFTER_HOUR, NO_TRADE_AFTER_MIN)
        return {"signal": "NO_TRADE", "details": details}

    if prev_close and prev_close > 0:
        orb_range_pct = orb_range / prev_close * 100
        details["orb_range_pct"] = round(orb_range_pct, 3)
        if orb_range_pct < 0.05:
            details["reason"] = "ORB too tight: %.0f pts (%.3f%%)" % (orb_range, orb_range_pct)
            return {"signal": "NO_TRADE", "details": details}
        if orb_range_pct > 1.0:
            details["reason"] = "ORB too wide: %.0f pts (%.3f%%)" % (orb_range, orb_range_pct)
            return {"signal": "NO_TRADE", "details": details}

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c.get("volume", 0) for c in candles]

    if len(closes) < 20:
        details["reason"] = "Need 20 candles, have %d" % len(closes)
        return {"signal": "NO_TRADE", "details": details}

    last_close = closes[-1]
    details["close"] = round(last_close, 2)

    vb = min(VWAP_SESSION_BARS, len(candles))
    vwap_s = calc_vwap(highs[-vb:], lows[-vb:], closes[-vb:], volumes[-vb:])
    vwap = safe(vwap_s)
    details["vwap"] = round(vwap, 2) if vwap else "N/A"

    ema_f = ema(closes, EMA_FAST)
    ema_s_arr = ema(closes, EMA_SLOW)
    ef = safe(ema_f)
    es = safe(ema_s_arr)
    details["ema9"] = round(ef, 2) if ef else "N/A"
    details["ema21"] = round(es, 2) if es else "N/A"

    rsi_s = calc_rsi(closes, RSI_LEN)
    rsi = safe(rsi_s)
    details["rsi"] = round(rsi, 1) if rsi else "N/A"

    buffer = last_close * ORB_BUFFER_PCT / 100
    breakout_high = orb_high + buffer
    breakout_low = orb_low - buffer

    direction = None
    if last_close > breakout_high:
        direction = "BULL"
    elif last_close < breakout_low:
        direction = "BEAR"

    if direction is None:
        details["reason"] = "Inside ORB (%.1f to %.1f)" % (breakout_low, breakout_high)
        return {"signal": "NO_TRADE", "details": details}

    details["direction"] = direction

    # FILTER 1: VWAP alignment
    if vwap is not None:
        if direction == "BULL" and last_close < vwap:
            details["reason"] = "BULL but below VWAP (%.1f < %.1f)" % (last_close, vwap)
            return {"signal": "NO_TRADE", "details": details}
        if direction == "BEAR" and last_close > vwap:
            details["reason"] = "BEAR but above VWAP (%.1f > %.1f)" % (last_close, vwap)
            return {"signal": "NO_TRADE", "details": details}

    # FILTER 2: RSI extremes only
    if rsi is not None:
        if direction == "BULL" and rsi > 80:
            details["reason"] = "RSI overbought: %.0f" % rsi
            return {"signal": "NO_TRADE", "details": details}
        if direction == "BEAR" and rsi < 20:
            details["reason"] = "RSI oversold: %.0f" % rsi
            return {"signal": "NO_TRADE", "details": details}

    # FILTER 3: EMA trend (soft - affects score not reject)
    ema_aligned = True
    if ef is not None and es is not None:
        if direction == "BULL" and ef < es:
            ema_aligned = False
        elif direction == "BEAR" and ef > es:
            ema_aligned = False
    details["ema_aligned"] = ema_aligned

    # S/R confluence
    sr_confluence = False
    sr_level_name = None
    sr_level_value = None
    if sr:
        sr_confluence, sr_level_name, sr_level_value = check_sr_confluence(last_close, direction, sr)
        details["sr_confluence"] = sr_confluence
        details["sr_level"] = "%s=%.0f" % (sr_level_name, sr_level_value) if sr_level_name else "None"
        details["pdh"] = sr["pdh"]
        details["pdl"] = sr["pdl"]
        details["pdc"] = sr["pdc"]
        details["pivot"] = sr["pivot"]

    # SCORE
    score = 1  # ORB breakout
    if vwap is not None and ((direction == "BULL" and last_close > vwap) or
                              (direction == "BEAR" and last_close < vwap)):
        score += 1
    if ema_aligned:
        score += 1
    if sr_confluence:
        score += 1
    if rsi is not None and 30 < rsi < 70:
        score += 1

    details["score"] = "%d/5" % score

    if score < 3:
        details["reason"] = "Low confluence: %d/5 (need 3)" % score
        return {"signal": "NO_TRADE", "details": details}

    if score >= 4:
        confidence = "HIGH"
    else:
        confidence = "MED"

    is_late = now.hour >= 12
    if is_late and score < 4:
        details["reason"] = "Late entry (%s): need 4/5, got %d/5" % (now.strftime("%H:%M"), score)
        return {"signal": "NO_TRADE", "details": details}

    signal_type = "CE_BUY" if direction == "BULL" else "PE_BUY"
    trigger = "ORB+VWAP+SR" if sr_confluence else "ORB+VWAP"
    details["trigger"] = trigger

    return {
        "signal": signal_type, "confidence": confidence,
        "direction": direction, "details": details,
    }

# =============================================================
#  SECTION 6 - RISK MANAGER
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
        ]
        if not PAPER_TRADE:
            checks.append(self._check_open_positions(groww))
        for passed, reason in checks:
            if not passed:
                return False, reason
        return True, "All risk checks passed"

    def _check_orb_formed(self):
        now = ist_now()
        orb_end = now.replace(hour=9, minute=45, second=0)
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
#  SECTION 7 - UTILITIES
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

def calc_sl_tp(entry_price, nifty_ltp, direction, orb, qty):
    orb_high = orb["orb_high"]
    orb_low = orb["orb_low"]

    if direction == "BULL":
        sl_nifty = orb_high - SL_BUFFER_BEHIND_ORB
        sl_distance_nifty = nifty_ltp - sl_nifty
    else:
        sl_nifty = orb_low + SL_BUFFER_BEHIND_ORB
        sl_distance_nifty = sl_nifty - nifty_ltp

    sl_distance_nifty = max(MIN_SL_POINTS, min(MAX_SL_POINTS, sl_distance_nifty))

    delta = 0.55
    sl_drop = sl_distance_nifty * delta
    tp_rise = sl_drop * RR_RATIO

    if sl_drop * qty > MAX_RISK_RUPEES:
        sl_drop = MAX_RISK_RUPEES / qty
        tp_rise = sl_drop * RR_RATIO

    sl_price = round(max(entry_price - sl_drop, 1.0), 1)
    target_price = round(entry_price + tp_rise, 1)
    sl_pct = sl_drop / entry_price * 100 if entry_price > 0 else 0
    rr = tp_rise / sl_drop if sl_drop > 0 else 0

    return sl_price, target_price, sl_drop, tp_rise, sl_pct, rr

def get_catastrophic_sl(entry_price, qty):
    max_drop = CATASTROPHIC_MAX_LOSS / qty
    return round(max(entry_price - max_drop, 1.0), 1)

# =============================================================
#  SECTION 8 - LOGIN (CACHED)
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
#  SECTION 9 - FETCH CANDLES (YOUR ORIGINAL - WORKING)
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
#  SECTION 10 - SYMBOL RESOLUTION (YOUR ORIGINAL - WORKING)
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
#  SECTION 11 - ORDERS (YOUR ORIGINAL - WORKING)
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
#  SECTION 12 - WEBSOCKET MONITOR (YOUR ORIGINAL - WORKING)
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
    sl_price = trade["sl"]
    target_price = trade["target"]
    sl_drop = trade["risk_premium"]
    tp_rise = trade["target_premium"]
    catastrophic_sl = get_catastrophic_sl(entry_premium, qty)

    logging.info("=== WS MONITOR START ===")
    logging.info("  Symbol: %s | Qty: %d" % (symbol, qty))
    logging.info("  Entry: Rs.%.1f" % entry_premium)
    logging.info("  SL: Rs.%.1f | Target: Rs.%.1f" % (sl_price, target_price))
    logging.info("  Risk: Rs.%.0f | Reward: Rs.%.0f | RR 1:%.1f" % (
        sl_drop * qty, tp_rise * qty, tp_rise / sl_drop if sl_drop > 0 else 0))
    logging.info("  Hold: %d min | Catastrophic SL: Rs.%.1f" % (MIN_HOLD_MINUTES, catastrophic_sl))

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

    sl_price = trade["sl"]
    target_price = trade["target"]
    tp_rise = trade["target_premium"]
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
#  SECTION 13 - MAIN
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

    # ORB
    orb = load_orb()
    if orb is None:
        if ist_now() < ist_now().replace(hour=9, minute=45, second=0):
            logging.info("ORB forming (30-min)...")
            return
        orb = compute_orb_levels(candles)
        if orb is None:
            logging.error("Cannot compute ORB")
            return
        save_orb(orb)
        logging.info("ORB | H:%s L:%s R:%s" % (
            str(orb["orb_high"]), str(orb["orb_low"]), str(orb["orb_range"])))

    # S/R
    sr = load_sr_levels()
    if sr is None:
        sr = compute_sr_levels(candles)
        if sr:
            save_sr_levels(sr)
            logging.info("S/R | PDH:%s PDL:%s PDC:%s Pivot:%s" % (
                str(sr["pdh"]), str(sr["pdl"]), str(sr["pdc"]), str(sr["pivot"])))
        else:
            logging.warning("No S/R levels (no prev day data)")

    # SIGNAL
    result = compute_signal(candles, orb, sr)
    signal_type = result["signal"]
    confidence = result.get("confidence")
    d = result.get("details", {})

    logging.info("  Signal:%s | Conf:%s | %s" % (signal_type, str(confidence), d.get("trigger", "--")))
    logging.info("  Close:%s | ORB:%s/%s | VWAP:%s" % (
        d.get("close", "--"), d.get("orb_high", "--"), d.get("orb_low", "--"), d.get("vwap", "--")))
    if sr:
        logging.info("  S/R: PDH:%s PDL:%s PDC:%s | Confluence:%s %s" % (
            d.get("pdh", "--"), d.get("pdl", "--"), d.get("pdc", "--"),
            d.get("sr_confluence", "--"), d.get("sr_level", "--")))
    logging.info("  RSI:%s EMA9:%s EMA21:%s | Score:%s" % (
        d.get("rsi", "--"), d.get("ema9", "--"), d.get("ema21", "--"), d.get("score", "--")))
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

    # SL / TARGET (STRUCTURAL)
    direction = result.get("direction", "BULL")
    sl_price, target_price, sl_drop, tp_rise, sl_pct, rr = calc_sl_tp(
        option_ltp, nifty_ltp, direction, orb, qty)
    catastrophic_sl = get_catastrophic_sl(option_ltp, qty)

    if rr < MIN_RR_RATIO:
        logging.warning("RR %.1f < %.1f minimum - REJECTED" % (rr, MIN_RR_RATIO))
        return

    total_risk = sl_drop * qty
    total_reward = tp_rise * qty

    logging.info("PLAN | Entry:~Rs.%s | Dir:%s" % (str(option_ltp), direction))
    logging.info("      SL:Rs.%s (structural) | Target:Rs.%s" % (str(sl_price), str(target_price)))
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

    sl_price, target_price, sl_drop, tp_rise, sl_pct, rr = calc_sl_tp(
        entry_premium, nifty_ltp, direction, orb, qty)

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
        "direction": direction,
        "orb_high": orb["orb_high"], "orb_low": orb["orb_low"],
        "sr_confluence": d.get("sr_confluence", False),
        "sr_level": d.get("sr_level", ""),
        "trigger": d.get("trigger", "unknown"),
        "score": d.get("score", ""),
        "rr": "1:%.1f" % rr,
        "paper": PAPER_TRADE,
        "exited": False,
        "time": now.strftime("%Y-%m-%d %H:%M:%S")
    })
    save_state(state)

    tag = "PAPER TRADE" if PAPER_TRADE else "LIVE TRADE"
    logging.info("%s | %s %s | %s" % (tag, signal_type, str(confidence), symbol))
    logging.info("   E:Rs.%s SL:Rs.%s T:Rs.%s RR:1:%.1f" % (
        str(entry_premium), str(sl_price), str(target_price), rr))
    logging.info("   %s | Score:%s | SR:%s" % (
        d.get("trigger", ""), d.get("score", ""), d.get("sr_level", "none")))

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
