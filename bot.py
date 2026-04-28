# ============================================================
#  NIFTY SNIPER v2.0 - BAG + ORB + FVG + WebSocket Monitoring
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
#    - 1 trade/day MAX
#    - No trades after 11:30 AM
#    - RR minimum 1:2 enforced
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
LOT_SIZE         = 65
LOTS_TO_TRADE    = 1
ITM_OFFSET       = 100

# -- PAPER TRADE MODE --
PAPER_TRADE      = True

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

# -- Risk / Reward --
MIN_RR_RATIO         = 2.0
TARGET_RR_RATIO      = 2.5
MAX_RISK_RUPEES      = 800
SL_BUFFER_POINTS     = 5

# -- Risk management --
MAX_TRADES_DAY            = 1
MAX_DAILY_LOSS_RUPEES     = 1200
CAPITAL_RUPEES            = 50000
MAX_CAPITAL_EXPOSURE_PCT  = 100
MIN_OPTION_PREMIUM        = 50
MAX_OPTION_PREMIUM        = 350
MAX_SPREAD_PCT            = 2.5

# -- Time --
NO_TRADE_AFTER_HOUR  = 15
NO_TRADE_AFTER_MIN   = 00
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
TRAILING_SL_ENABLED  = False
TRAILING_SL_TRIGGER  = 0.5
TRAILING_SL_STEP     = 0.3

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
        "date": ist_now().strftime("%Y-%m-%d"),
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

def compute_signal(candles, orb):
    if not orb or not candles:
        return {"signal": "NO_TRADE", "details": {"reason": "No data"}}

    orb_high = orb["orb_high"]
    orb_low = orb["orb_low"]
    orb_range = orb["orb_range"]
    gap_dir = orb.get("gap_direction", "NONE")
    gap_size = orb.get("gap_size", 0)

    details = {
        "orb_high": orb_high, "orb_low": orb_low, "orb_range": orb_range,
        "gap_direction": gap_dir, "gap_size": gap_size,
    }

    if orb_range < MIN_ORB_RANGE:
        details["reason"] = "ORB too tight: %.0f < %d" % (orb_range, MIN_ORB_RANGE)
        return {"signal": "NO_TRADE", "details": details}
    if orb_range > MAX_ORB_RANGE:
        details["reason"] = "ORB too wide: %.0f > %d" % (orb_range, MAX_ORB_RANGE)
        return {"signal": "NO_TRADE", "details": details}

    now = ist_now()
    if now.hour > NO_TRADE_AFTER_HOUR or (now.hour == NO_TRADE_AFTER_HOUR and now.minute >= NO_TRADE_AFTER_MIN):
        details["reason"] = "Past %d:%02d" % (NO_TRADE_AFTER_HOUR, NO_TRADE_AFTER_MIN)
        return {"signal": "NO_TRADE", "details": details}

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c.get("volume", 0) for c in candles]

    if len(closes) < 30:
        details["reason"] = "Need 30 candles, have %d" % len(closes)
        return {"signal": "NO_TRADE", "details": details}

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
        int(rsi is not None and 25 < rsi < 55),
    ])

    details["bull_score"] = "%d/6" % bull_score
    details["bear_score"] = "%d/6" % bear_score

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

    if direction == "BULL" and rsi is not None and rsi > 78:
        details["reason"] = "RSI overbought: %.0f" % rsi
        return {"signal": "NO_TRADE", "details": details}
    if direction == "BEAR" and rsi is not None and rsi < 22:
        details["reason"] = "RSI oversold: %.0f" % rsi
        return {"signal": "NO_TRADE", "details": details}
    if abs(gap_size) > MAX_GAP_POINTS:
        details["reason"] = "Exhaustion gap: %.0f pts" % gap_size
        return {"signal": "NO_TRADE", "details": details}

    fvg_top, fvg_bot, fvg_idx = detect_fvg(highs, lows, closes, direction)

    if fvg_top is not None:
        details["fvg_top"] = fvg_top
        details["fvg_bot"] = fvg_bot
        details["fvg_size"] = round(fvg_top - fvg_bot, 1)
        details["entry_mode"] = "FVG_RETEST"
        if direction == "BULL":
            sl_nifty = fvg_bot - SL_BUFFER_POINTS
            risk_points = last_close - sl_nifty
        else:
            sl_nifty = fvg_top + SL_BUFFER_POINTS
            risk_points = sl_nifty - last_close
    else:
        details["entry_mode"] = "ORB_BREAKOUT"
        if direction == "BULL":
            sl_nifty = orb_low - SL_BUFFER_POINTS
            risk_points = last_close - sl_nifty
        else:
            sl_nifty = orb_high + SL_BUFFER_POINTS
            risk_points = sl_nifty - last_close

    if risk_points <= 0:
        details["reason"] = "Invalid risk: %.1f pts" % risk_points
        return {"signal": "NO_TRADE", "details": details}

    delta = 0.55
    risk_in_premium = risk_points * delta
    target_in_premium = risk_in_premium * TARGET_RR_RATIO

    qty = LOT_SIZE * LOTS_TO_TRADE
    if risk_in_premium * qty > MAX_RISK_RUPEES:
        risk_in_premium = MAX_RISK_RUPEES / qty
        target_in_premium = risk_in_premium * TARGET_RR_RATIO

    details.update({
        "direction": direction,
        "risk_points": round(risk_points, 1),
        "risk_premium": round(risk_in_premium, 1),
        "target_premium": round(target_in_premium, 1),
        "rr_ratio": "1:%.1f" % TARGET_RR_RATIO,
        "sl_nifty": round(sl_nifty, 1),
    })

    score = bull_score if direction == "BULL" else bear_score
    confidence = "HIGH" if score >= 3 else "MED"
    signal_type = "CE_BUY" if direction == "BULL" else "PE_BUY"
    details["trigger"] = "BAG+ORB+" + ("FVG" if fvg_top else "MOMENTUM")
    details["score"] = "%d/6" % score

    return {
        "signal": signal_type, "confidence": confidence,
        "direction": direction, "details": details,
        "risk_premium": risk_in_premium,
        "target_premium": target_in_premium,
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
                start_dt = (now - datetime.timedelta(days=3)).strftime("%Y-%m-%d 09:15:00")
        except:
            start_dt = (now - datetime.timedelta(days=3)).strftime("%Y-%m-%d 09:15:00")
    else:
        start_dt = (now - datetime.timedelta(days=3)).strftime("%Y-%m-%d 09:15:00")

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
    """Get exchange_token from instruments CSV for WebSocket subscription."""
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
    """
    Long-running WebSocket monitor. Called after entry order is placed.
    Uses GrowwFeed.subscribe_ltp() for real-time price updates.
    Exits when SL/TP is hit or squareoff time reached.
    """
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
    risk_premium = trade["risk_premium"]
    target_premium = trade["target_premium"]

    sl_price = round(max(entry_premium - risk_premium, 1.0), 1)
    target_price = round(entry_premium + target_premium, 1)
    trailing_sl = sl_price

    logging.info("=== WS MONITOR START ===")
    logging.info("  Symbol: %s | Qty: %d" % (symbol, qty))
    logging.info("  Entry: Rs.%s | SL: Rs.%s | Target: Rs.%s" % (str(entry_premium), str(sl_price), str(target_price)))
    logging.info("  Risk: Rs.%.0f | Reward: Rs.%.0f" % (risk_premium * qty, target_premium * qty))

    write_monitor_pid()

    # Get exchange_token for WebSocket subscription
    exchange_token = get_exchange_token(groww, symbol)
    if not exchange_token:
        logging.error("Cannot get exchange_token for %s - falling back to polling" % symbol)
        _fallback_polling_monitor(groww, state, trade)
        return

    logging.info("  Exchange token: %s" % exchange_token)

    # State for the monitor
    monitor_state = {
        "exited": False,
        "exit_reason": None,
        "exit_ltp": None,
        "last_log_time": time.time(),
        "last_heartbeat": time.time(),
        "last_ltp": None,
        "trailing_sl": trailing_sl,
        "highest_ltp": entry_premium,
    }

    # Create feed client
    feed = GrowwFeed(groww)

    instrument_list = [{
        "exchange": "NSE",
        "segment": "FNO",
        "exchange_token": exchange_token,
    }]

    def on_tick(meta):
        """Called on every price update from WebSocket."""
        if monitor_state["exited"]:
            return

        now_ts = time.time()

        # Get current LTP from feed
        try:
            ltp_data = feed.get_ltp()
            if not ltp_data:
                return

            # Navigate nested response: {"ltp": {"NSE": {"FNO": {"token": {"ltp": x}}}}}
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

        # -- Periodic logging --
        if now_ts - monitor_state["last_log_time"] >= WS_TICK_LOG_INTERVAL:
            pnl = (current_ltp - entry_premium) * qty
            logging.info("  TICK | LTP: Rs.%.1f | P&L: Rs.%+.0f | SL: Rs.%.1f | T: Rs.%.1f" % (
                current_ltp, pnl, monitor_state["trailing_sl"], target_price))
            monitor_state["last_log_time"] = now_ts

        # -- Heartbeat --
        if now_ts - monitor_state["last_heartbeat"] >= WS_HEARTBEAT_SEC:
            logging.info("  HEARTBEAT | LTP: Rs.%.1f" % current_ltp)
            monitor_state["last_heartbeat"] = now_ts

        # -- Squareoff time check --
        now_ist = ist_now()
        if now_ist.hour > SQUAREOFF_HOUR or (now_ist.hour == SQUAREOFF_HOUR and now_ist.minute >= SQUAREOFF_MIN):
            pnl = (current_ltp - entry_premium) * qty
            _execute_exit(groww, state, trade, feed, instrument_list,
                         current_ltp, pnl, "EOD SQUAREOFF Rs.%+.0f" % pnl, monitor_state)
            return

        # -- Trailing SL --
        if TRAILING_SL_ENABLED and current_ltp > monitor_state["highest_ltp"]:
            monitor_state["highest_ltp"] = current_ltp
            profit_so_far = current_ltp - entry_premium
            trigger_profit = target_premium * TRAILING_SL_TRIGGER

            if profit_so_far >= trigger_profit:
                new_sl = round(entry_premium + (profit_so_far * TRAILING_SL_STEP), 1)
                if new_sl > monitor_state["trailing_sl"]:
                    old_sl = monitor_state["trailing_sl"]
                    monitor_state["trailing_sl"] = new_sl
                    logging.info("  TRAILING SL: Rs.%.1f -> Rs.%.1f" % (old_sl, new_sl))

        active_sl = monitor_state["trailing_sl"]

        # -- TAKE PROFIT --
        if current_ltp >= target_price:
            pnl = (current_ltp - entry_premium) * qty
            _execute_exit(groww, state, trade, feed, instrument_list,
                         current_ltp, pnl, "TAKE PROFIT Rs.%+.0f" % pnl, monitor_state)
            return

        # -- STOP LOSS --
        if current_ltp <= active_sl:
            pnl = (current_ltp - entry_premium) * qty
            _execute_exit(groww, state, trade, feed, instrument_list,
                         current_ltp, pnl, "STOP LOSS Rs.%+.0f" % pnl, monitor_state)
            return

    def _execute_exit(groww_ref, state_ref, trade_ref, feed_ref, inst_list,
                      current_ltp, pnl, reason, mstate):
        if mstate["exited"]:
            return
        mstate["exited"] = True

        logging.info("=== EXIT TRIGGERED ===")
        logging.info("  %s" % reason)
        logging.info("  LTP: Rs.%.1f | Entry: Rs.%s" % (current_ltp, str(entry_premium)))

        place_exit_order(groww_ref, symbol, qty, reason)

        trade_ref["exited"] = True
        trade_ref["exit_ltp"] = current_ltp
        trade_ref["exit_pnl"] = round(pnl, 2)
        trade_ref["exit_reason"] = reason
        trade_ref["exit_time"] = ist_now().strftime("%Y-%m-%d %H:%M:%S")
        state_ref["daily_pnl_rupees"] = state_ref.get("daily_pnl_rupees", 0) + pnl
        save_state(state_ref)

        try:
            feed_ref.unsubscribe_ltp(inst_list)
        except:
            pass
        clear_monitor_pid()

        logging.info("  Daily P&L: Rs.%+.0f" % state_ref["daily_pnl_rupees"])
        logging.info("=== WS MONITOR END ===")

    # -- Signal handler for clean shutdown --
    def handle_shutdown(signum, frame):
        logging.info("WS Monitor: Shutdown signal received")
        if not monitor_state["exited"]:
            final_ltp = monitor_state.get("last_ltp") or entry_premium
            if final_ltp > 0:
                pnl = (final_ltp - entry_premium) * qty
                _execute_exit(groww, state, trade, feed, instrument_list,
                             final_ltp, pnl, "SHUTDOWN Rs.%+.0f" % pnl, monitor_state)
        clear_monitor_pid()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # -- Subscribe and start consuming --
    logging.info("  Subscribing to %s (token: %s)..." % (symbol, exchange_token))

    try:
        feed.subscribe_ltp(instrument_list, on_data_received=on_tick)
        logging.info("  WebSocket connected - monitoring live")

        # feed.consume() is a BLOCKING call - keeps running until disconnect
        feed.consume()

    except KeyboardInterrupt:
        logging.info("WS Monitor: Keyboard interrupt")
        handle_shutdown(None, None)
    except Exception as e:
        logging.error("WS Monitor crashed: %s" % str(e))
        if not monitor_state["exited"]:
            logging.info("Falling back to polling monitor...")
            _fallback_polling_monitor(groww, state, trade)
    finally:
        clear_monitor_pid()


def _fallback_polling_monitor(groww, state, trade):
    """
    Fallback: poll LTP via REST API every 5 seconds.
    Used if WebSocket fails to connect.
    """
    symbol = trade["symbol"]
    qty = trade["qty"]
    entry_premium = trade["entry_premium"]
    risk_premium = trade["risk_premium"]
    target_premium = trade["target_premium"]

    sl_price = round(max(entry_premium - risk_premium, 1.0), 1)
    target_price = round(entry_premium + target_premium, 1)

    logging.info("POLLING MONITOR | %s | SL:%s | T:%s" % (symbol, str(sl_price), str(target_price)))
    write_monitor_pid()

    last_log = 0

    try:
        while True:
            now = ist_now()

            # Squareoff check
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

            # Log every 30 seconds
            now_ts = time.time()
            if now_ts - last_log >= 30:
                logging.info("  POLL | LTP:%.1f | P&L:%+.0f | SL:%s T:%s" % (
                    current_ltp, pnl, str(sl_price), str(target_price)))
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

            if current_ltp <= sl_price:
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
        logging.error("Polling monitor error: %s" % str(e))
    finally:
        clear_monitor_pid()

# =============================================================
#  SECTION 11 - MAIN
# =============================================================

def main():
    # Check run mode from command line
    run_mode = sys.argv[1] if len(sys.argv) > 1 else "scan"

    # MODE: monitor - launched by the scanner after entry
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

    # MODE: scan (default) - cron runs this every minute
    now = ist_now()
    state = load_state()

    # -- If monitor is already running, skip --
    if is_monitor_running():
        logging.info("[%s] Monitor active. Skip scan." % now.strftime("%H:%M"))
        return

    # -- Check if there is an unexited trade (monitor crashed?) --
    trades = state.get("trades", [])
    if trades and not trades[-1].get("exited", False):
        logging.info("Found unexited trade - restarting monitor...")
        _spawn_monitor()
        return

    # -- EARLY EXITS --
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

    # -- SQUAREOFF --
    if is_squareoff_time():
        cancel_and_squareoff(groww, state)
        return

    # -- CANDLES --
    candles = fetch_candles(groww)
    if not candles:
        logging.error("No candles")
        return

    # -- ORB --
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

    # -- SIGNAL --
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

    # -- RISK --
    risk = RiskManager(state)
    ok, reason = risk.check_can_trade(groww)
    if not ok:
        logging.warning("BLOCKED: %s" % reason)
        return
    logging.info("Risk OK: %s" % reason)

    # -- STRIKE --
    opt_type = "CE" if "CE" in signal_type else "PE"
    q = _get_nifty_quote(groww)
    if q is None:
        logging.error("No Nifty LTP")
        return
    nifty_ltp = float(q["last_price"])
    atm = get_atm_strike(nifty_ltp)
    strike = (atm - ITM_OFFSET) if opt_type == "CE" else (atm + ITM_OFFSET)
    qty = LOT_SIZE * LOTS_TO_TRADE

    # -- RESOLVE --
    symbol, option_ltp = get_valid_option_symbol(groww, strike, opt_type)
    if symbol is None:
        logging.warning("ITM %d failed, trying ATM %d" % (strike, atm))
        symbol, option_ltp = get_valid_option_symbol(groww, atm, opt_type)
        if symbol is None:
            logging.error("Cannot resolve symbol")
            return
        strike = atm

    logging.info("Resolved: %s | Rs.%s | Nifty:%s" % (symbol, str(option_ltp), str(nifty_ltp)))

    # -- PRE-TRADE CHECKS --
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

    # -- SL / TARGET --
    risk_premium = result.get("risk_premium", 0)
    target_premium = result.get("target_premium", 0)
    if risk_premium <= 0:
        logging.error("Invalid risk calculation")
        return

    sl_price = round(max(option_ltp - risk_premium, 1.0), 1)
    target_price = round(option_ltp + target_premium, 1)
    rr = target_premium / risk_premium if risk_premium > 0 else 0

    if rr < MIN_RR_RATIO:
        logging.warning("RR %.1f < %.1f minimum - REJECTED" % (rr, MIN_RR_RATIO))
        return

    total_risk = risk_premium * qty
    total_reward = target_premium * qty

    logging.info("PLAN | Entry:~Rs.%s SL:Rs.%s Target:Rs.%s" % (str(option_ltp), str(sl_price), str(target_price)))
    logging.info("      Risk:Rs.%.0f Reward:Rs.%.0f RR:1:%.1f" % (total_risk, total_reward, rr))

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
    sl_price = round(max(entry_premium - risk_premium, 1.0), 1)
    target_price = round(entry_premium + target_premium, 1)

    # -- SAVE TRADE --
    state["trade_count"] += 1
    state["trades"].append({
        "signal": signal_type, "confidence": confidence,
        "symbol": symbol, "qty": qty,
        "entry_id": str(oid),
        "entry_premium": entry_premium,
        "risk_premium": risk_premium,
        "target_premium": target_premium,
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
    logging.info("   E:Rs.%s SL:Rs.%s T:Rs.%s RR:1:%.1f" % (
        str(entry_premium), str(sl_price), str(target_price), rr))
    logging.info("   %s | Score:%s" % (d.get("trigger", ""), d.get("score", "")))

    # -- LAUNCH WEBSOCKET MONITOR --
    _spawn_monitor()


def _spawn_monitor():
    """
    Spawn the WebSocket monitor as a detached background process.
    This way the cron job can exit while the monitor keeps running.
    """
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
