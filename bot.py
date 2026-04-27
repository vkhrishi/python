# ============================================================
#  NIFTY SNIPER v1.1 — BAG + ORB + FVG Combined Strategy
#  VPS (Hetzner + Groww API)
#
#  STRATEGY:
#    1. BAG  — Gap at open sets directional bias
#    2. ORB  — 15-min range breakout confirms direction
#    3. FVG  — Fair Value Gap gives sniper entry with tight SL
#
#  RULES:
#    • 1 trade/day MAX
#    • No trades after 11:30 AM
#    • RR minimum 1:2 enforced
#    • ITM options for better delta
#    • Cached login + smart API budgeting
#
#  v1.1 CHANGES:
#    • MIN_GAP reduced 30→15 (more trading days)
#    • MIN_ADX reduced 20→15 (morning ADX often low)
#    • HIGH confidence = 3+ score (was 4+)
#    • Allow MED confidence trades (ORB+trend aligned)
#    • Score 2 allowed if ORB breakout + EMA trend match
#    • 3-day candle warmup (indicators ready at 9:30)
# ============================================================

from growwapi import GrowwAPI
import datetime
import logging
import json
import time
import pyotp
import os
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
    print(f"✅ SERVER IP: {SERVER_IP}")
except:
    SERVER_IP = "unknown"
    print("❌ Unable to fetch IP")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/root/scalper/bot.log"),
        logging.StreamHandler()
    ]
)

# ═════════════════════════════════════════════════════════════
#  SECTION 1 — CONFIGURATION
# ═════════════════════════════════════════════════════════════

GROWW_TOTP_TOKEN  = "eyJraWQiOiJaTUtjVXciLCJhbGciOiJFUzI1NiJ9.eyJleHAiOjI1NjQ0NjQ3NTEsImlhdCI6MTc3NjA2NDc1MSwibmJmIjoxNzc2MDY0NzUxLCJzdWIiOiJ7XCJ0b2tlblJlZklkXCI6XCI4OTFmMzExNi04NGRjLTQxNWMtOWUxYy1iOTc3YzNhMWExZmJcIixcInZlbmRvckludGVncmF0aW9uS2V5XCI6XCJlMzFmZjIzYjA4NmI0MDZjODg3NGIyZjZkODQ5NTMxM1wiLFwidXNlckFjY291bnRJZFwiOlwiNjQ3NTk3YTItNTlmMC00MWQ2LTkyZjgtMGNjYzdkYTBkN2I2XCIsXCJkZXZpY2VJZFwiOlwiYWM4Y2Y5NzctMTY5OC01NDM3LTkxNTItMzg2ZTFiZmM2YzQwXCIsXCJzZXNzaW9uSWRcIjpcIjAzM2E2OWRhLWQ3YzQtNDJkMS04YTJiLWNiMDc0NjQxMGIwZFwiLFwiYWRkaXRpb25hbERhdGFcIjpcIno1NC9NZzltdjE2WXdmb0gvS0EwYkgyblRaQUhZYlRzeVhHdDk1ZzgxR1JSTkczdTlLa2pWZDNoWjU1ZStNZERhWXBOVi9UOUxIRmtQejFFQisybTdRPT1cIixcInJvbGVcIjpcImF1dGgtdG90cFwiLFwic291cmNlSXBBZGRyZXNzXCI6XCIyNDAxOjQ5MDA6OTM5NTpjZTQ1OjdjNWM6NWVlYjoyMTAwOjZiYzUsMTcyLjY5LjEzMS4xODcsMzUuMjQxLjIzLjEyM1wiLFwidHdvRmFFeHBpcnlUc1wiOjI1NjQ0NjQ3NTEzMTgsXCJ2ZW5kb3JOYW1lXCI6XCJncm93d0FwaVwifSIsImlzcyI6ImFwZXgtYXV0aC1wcm9kLWFwcCJ9.Oyi_wQZPgluXSJTYzwyWEJ4Q3nW40o6e9sr7oD6gsfLwgMB0eNmG6TQDM2_yyEXZp2Z9z1tCuqTgJYd6rBJdOA"
GROWW_TOTP_SECRET = "5TJKK3FZ2NFN73QTENQLKH5AOVDRC7CQ"

# ── Trade sizing ──
LOT_SIZE         = 65
LOTS_TO_TRADE    = 1
ITM_OFFSET       = 100      # Buy 100 pts ITM for delta ~0.6

# ── PAPER TRADE MODE ──
PAPER_TRADE      = True     # Set False ONLY after 40+ paper trades

# ── BAG (Breakaway Gap) ──
MIN_GAP_POINTS       = 15   # Reduced from 30 — catches more valid gaps
MAX_GAP_POINTS       = 200  # Too large = exhaustion gap
GAP_CONFIRMATION_MIN = 15   # Wait 15 min to confirm gap holds

# ── ORB (Opening Range Breakout) ──
ORB_MINUTES          = 15
ORB_BUFFER_POINTS    = 3
MIN_ORB_RANGE        = 20
MAX_ORB_RANGE        = 200

# ── FVG (Fair Value Gap) ──
FVG_MIN_SIZE_POINTS  = 5    # Min gap size in NIFTY points
FVG_MAX_AGE_CANDLES  = 12   # FVG must be within last 12 candles
FVG_ENTRY_BUFFER     = 2    # Enter 2 pts inside FVG zone

# ── Risk / Reward ──
MIN_RR_RATIO         = 2.0  # Minimum 1:2 RR (reject trades below this)
TARGET_RR_RATIO      = 2.5  # Aim for 1:2.5
MAX_RISK_RUPEES      = 800  # Max loss per trade
TAKE_PROFIT_RUPEES   = 300
STOP_LOSS_RUPEES     = 500
SL_BUFFER_POINTS     = 5    # SL buffer beyond FVG/ORB level

# ── Risk management ──
MAX_TRADES_DAY            = 1
MAX_DAILY_LOSS_RUPEES     = 1200
CAPITAL_RUPEES            = 50000
MAX_CAPITAL_EXPOSURE_PCT  = 100
MIN_OPTION_PREMIUM        = 50
MAX_OPTION_PREMIUM        = 350
MAX_SPREAD_PCT            = 2.5

# ── Time ──
NO_TRADE_AFTER_HOUR  = 11
NO_TRADE_AFTER_MIN   = 30   # Strict: no entries after 11:30
SQUAREOFF_HOUR       = 15
SQUAREOFF_MIN        = 10

# ── Market regime ──
MIN_ADX_FOR_TRADE    = 15   # Reduced from 20 — morning ADX often 15-19
ADX_LEN              = 14
ATR_LEN              = 14
RSI_LEN              = 14
EMA_FAST             = 9
EMA_SLOW             = 21
VWAP_SESSION_BARS    = 75

# ── Expiry ──
NIFTY_EXPIRY_WEEKDAY = 1    # 0=Mon, 1=Tue — CHANGE if NSE shifts

# ── Files ──
STATE_FILE  = "/root/scalper/state.json"
TOKEN_FILE  = "/root/scalper/token.json"
CANDLE_FILE = "/root/scalper/candles.json"
ORB_FILE    = "/root/scalper/orb.json"

# ═════════════════════════════════════════════════════════════
#  SECTION 2 — INDICATORS
# ═════════════════════════════════════════════════════════════

def ema(data, period):
    if len(data) < period: return [None]*len(data)
    k = 2/(period+1)
    result = [None]*(period-1)
    result.append(sum(data[:period])/period)
    for p in data[period:]:
        result.append(p*k + result[-1]*(1-k))
    return result

def rma(data, period):
    result = [None]*len(data)
    start = next((i for i,v in enumerate(data) if v is not None), None)
    if start is None or start+period > len(data): return result
    seeds = [v for v in data[start:start+period] if v is not None]
    if len(seeds) < period: return result
    result[start+period-1] = sum(seeds)/period
    for i in range(start+period, len(data)):
        if data[i] is not None and result[i-1] is not None:
            result[i] = (result[i-1]*(period-1)+data[i])/period
    return result

def calc_atr(highs, lows, closes, period=14):
    tr = [None]+[max(highs[i]-lows[i], abs(highs[i]-closes[i-1]),
                     abs(lows[i]-closes[i-1])) for i in range(1,len(closes))]
    return rma(tr, period)

def calc_adx(highs, lows, closes, period=14):
    plus_dm = [None]+[(highs[i]-highs[i-1]) if (highs[i]-highs[i-1])>(lows[i-1]-lows[i])
                      and (highs[i]-highs[i-1])>0 else 0.0 for i in range(1,len(closes))]
    minus_dm= [None]+[(lows[i-1]-lows[i]) if (lows[i-1]-lows[i])>(highs[i]-highs[i-1])
                      and (lows[i-1]-lows[i])>0 else 0.0 for i in range(1,len(closes))]
    tr = [None]+[max(highs[i]-lows[i], abs(highs[i]-closes[i-1]),
                     abs(lows[i]-closes[i-1])) for i in range(1,len(closes))]
    tr_s=rma(tr,period); pdm_s=rma(plus_dm,period); mdm_s=rma(minus_dm,period)
    pdi_list, mdi_list, dx = [], [], []
    for ts,ps,ms in zip(tr_s,pdm_s,mdm_s):
        if None in (ts,ps,ms) or ts==0:
            pdi_list.append(None); mdi_list.append(None); dx.append(None)
        else:
            p=100*ps/ts; m=100*ms/ts
            pdi_list.append(p); mdi_list.append(m)
            dx.append(100*abs(p-m)/(p+m) if (p+m)!=0 else 0)
    return rma(dx,period), pdi_list, mdi_list

def calc_rsi(closes, period=14):
    gains  = [None]+[max(closes[i]-closes[i-1],0) for i in range(1,len(closes))]
    losses = [None]+[max(closes[i-1]-closes[i],0) for i in range(1,len(closes))]
    ag,al  = rma(gains,period), rma(losses,period)
    return [None if g is None or l is None else (100.0 if l==0 else 100-100/(1+g/l))
            for g,l in zip(ag,al)]

def calc_vwap(highs, lows, closes, volumes):
    result, cpv, cv = [], 0.0, 0.0
    for h, l, c, v in zip(highs, lows, closes, volumes):
        cpv += (h + l + c) / 3 * v
        cv  += v
        result.append(cpv / cv if cv > 0 else c)
    return result

def safe(s, idx=-1):
    try: return s[idx]
    except: return None

# ═════════════════════════════════════════════════════════════
#  SECTION 3 — BAG + ORB + FVG SIGNAL ENGINE
# ═════════════════════════════════════════════════════════════

def load_orb():
    today = ist_now().strftime("%Y-%m-%d")
    try:
        with open(ORB_FILE) as f:
            data = json.load(f)
        if data.get("date") == today: return data
    except: pass
    return None

def save_orb(data):
    with open(ORB_FILE, "w") as f: json.dump(data, f, indent=2)

def compute_orb_levels(candles):
    """Extract ORB + previous close for BAG detection."""
    orb_candles = []
    prev_day_close = None
    today = ist_now().date()

    for c in candles:
        ts = c.get("ts", "")
        if not ts: continue
        try: dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except: continue

        if dt.date() < today:
            prev_day_close = c["close"]
            continue
        if dt.date() != today: continue
        t = dt.time()
        if datetime.time(9, 15) <= t < datetime.time(9, 30):
            orb_candles.append(c)

    if len(orb_candles) < 2:
        return None

    orb_high  = max(c["high"] for c in orb_candles)
    orb_low   = min(c["low"]  for c in orb_candles)
    orb_open  = orb_candles[0]["open"]
    orb_close = orb_candles[-1]["close"]
    orb_range = orb_high - orb_low

    # BAG detection
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
    """Find most recent FVG in the given direction.
    Bullish FVG: candle[i-2].high < candle[i].low (gap up imbalance)
    Bearish FVG: candle[i-2].low > candle[i].high (gap down imbalance)
    Returns: (fvg_top, fvg_bottom, fvg_index) or (None, None, None)
    """
    if len(highs) < 3: return None, None, None

    search_start = len(highs) - 1
    search_end = max(0, len(highs) - FVG_MAX_AGE_CANDLES)

    for i in range(search_start, search_end + 1, -1):
        if i < 2: break

        if direction == "BULL":
            c1_high = highs[i-2]
            c3_low  = lows[i]
            if c3_low > c1_high:
                fvg_size = c3_low - c1_high
                if fvg_size >= FVG_MIN_SIZE_POINTS:
                    return round(c3_low, 2), round(c1_high, 2), i

        elif direction == "BEAR":
            c1_low  = lows[i-2]
            c3_high = highs[i]
            if c1_low > c3_high:
                fvg_size = c1_low - c3_high
                if fvg_size >= FVG_MIN_SIZE_POINTS:
                    return round(c1_low, 2), round(c3_high, 2), i

    return None, None, None

def compute_signal(candles, orb):
    """Combined BAG + ORB + FVG signal engine."""
    if not orb or not candles:
        return {"signal": "NO_TRADE", "details": {"reason": "No data"}}

    orb_high  = orb["orb_high"]
    orb_low   = orb["orb_low"]
    orb_range = orb["orb_range"]
    gap_dir   = orb.get("gap_direction", "NONE")
    gap_size  = orb.get("gap_size", 0)

    details = {
        "orb_high": orb_high, "orb_low": orb_low, "orb_range": orb_range,
        "gap_direction": gap_dir, "gap_size": gap_size,
    }

    # ── Range filter ──
    if orb_range < MIN_ORB_RANGE:
        details["reason"] = f"ORB too tight: {orb_range:.0f} < {MIN_ORB_RANGE}"
        return {"signal": "NO_TRADE", "details": details}
    if orb_range > MAX_ORB_RANGE:
        details["reason"] = f"ORB too wide: {orb_range:.0f} > {MAX_ORB_RANGE}"
        return {"signal": "NO_TRADE", "details": details}

    # ── Time filter ──
    now = ist_now()
    if now.hour > NO_TRADE_AFTER_HOUR or (now.hour == NO_TRADE_AFTER_HOUR and now.minute >= NO_TRADE_AFTER_MIN):
        details["reason"] = f"Past {NO_TRADE_AFTER_HOUR}:{NO_TRADE_AFTER_MIN:02d}"
        return {"signal": "NO_TRADE", "details": details}

    # ── Extract data ──
    closes  = [c["close"]  for c in candles]
    highs   = [c["high"]   for c in candles]
    lows    = [c["low"]    for c in candles]
    volumes = [c.get("volume", 0) for c in candles]

    if len(closes) < 30:
        details["reason"] = f"Need 30 candles, have {len(closes)}"
        return {"signal": "NO_TRADE", "details": details}

    # ── Indicators ──
    adx_s, pdi_s, mdi_s = calc_adx(highs, lows, closes, ADX_LEN)
    adx  = safe(adx_s)
    pdi  = safe(pdi_s)
    mdi  = safe(mdi_s)
    rsi_s = calc_rsi(closes, RSI_LEN)
    rsi   = safe(rsi_s)
    atr_s = calc_atr(highs, lows, closes, ATR_LEN)
    atr   = safe(atr_s)
    ema_f = ema(closes, EMA_FAST)
    ema_s_arr = ema(closes, EMA_SLOW)
    ef = safe(ema_f); es = safe(ema_s_arr)

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

    # ── REGIME FILTER: must be trending ──
    if adx is not None and adx < MIN_ADX_FOR_TRADE:
        details["reason"] = f"Sideways: ADX {adx:.1f} < {MIN_ADX_FOR_TRADE}"
        return {"signal": "NO_TRADE", "details": details}

    # ── STEP 1: Determine bias from BAG + ORB + indicators ──
    trend_bull = ef is not None and es is not None and ef > es
    trend_bear = ef is not None and es is not None and ef < es
    above_vwap = vwap is not None and last_close > vwap
    below_vwap = vwap is not None and last_close < vwap
    pdi_strong = pdi is not None and mdi is not None and pdi > mdi
    mdi_strong = pdi is not None and mdi is not None and mdi > pdi

    breakout_high = orb_high + ORB_BUFFER_POINTS
    breakout_low  = orb_low  - ORB_BUFFER_POINTS

    # Score bullish/bearish confluence
    bull_score = sum([
        int(last_close > breakout_high),           # ORB breakout up
        int(gap_dir == "GAP_UP"),                   # Gap up
        int(trend_bull),                            # EMA trend up
        int(above_vwap),                            # Above VWAP
        int(pdi_strong),                            # +DI > -DI
        int(rsi is not None and 45 < rsi < 75),     # RSI healthy
    ])

    bear_score = sum([
        int(last_close < breakout_low),             # ORB breakout down
        int(gap_dir == "GAP_DOWN"),                  # Gap down
        int(trend_bear),                            # EMA trend down
        int(below_vwap),                            # Below VWAP
        int(mdi_strong),                            # -DI > +DI
        int(rsi is not None and 25 < rsi < 55),     # RSI healthy
    ])

    details["bull_score"] = f"{bull_score}/6"
    details["bear_score"] = f"{bear_score}/6"

    # ── DIRECTION DECISION (relaxed from v1.0) ──
    direction = None

    # Primary: score 3+ with ORB breakout
    if bull_score >= 3 and last_close > breakout_high:
        direction = "BULL"
    elif bear_score >= 3 and last_close < breakout_low:
        direction = "BEAR"
    # Secondary: score 2 but ORB breakout + EMA trend both align
    elif last_close > breakout_high and trend_bull and bull_score >= 2:
        direction = "BULL"
    elif last_close < breakout_low and trend_bear and bear_score >= 2:
        direction = "BEAR"

    if direction is None:
        details["reason"] = f"Insufficient confluence: Bull={bull_score}/6 Bear={bear_score}/6"
        return {"signal": "NO_TRADE", "details": details}

    # ── RSI extreme rejection ──
    if direction == "BULL" and rsi is not None and rsi > 78:
        details["reason"] = f"RSI overbought: {rsi:.0f}"
        return {"signal": "NO_TRADE", "details": details}
    if direction == "BEAR" and rsi is not None and rsi < 22:
        details["reason"] = f"RSI oversold: {rsi:.0f}"
        return {"signal": "NO_TRADE", "details": details}

    # ── Exhaustion gap rejection ──
    if abs(gap_size) > MAX_GAP_POINTS:
        details["reason"] = f"Exhaustion gap: {gap_size:.0f} pts"
        return {"signal": "NO_TRADE", "details": details}

    # ── STEP 2: Find FVG for sniper entry ──
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

    # ── STEP 3: Calculate RR and enforce minimum ──
    if risk_points <= 0:
        details["reason"] = f"Invalid risk: {risk_points:.1f} pts"
        return {"signal": "NO_TRADE", "details": details}

    delta = 0.55
    risk_in_premium = risk_points * delta
    target_in_premium = risk_in_premium * TARGET_RR_RATIO
    actual_rr = TARGET_RR_RATIO

    qty = LOT_SIZE * LOTS_TO_TRADE
    if risk_in_premium * qty > MAX_RISK_RUPEES:
        risk_in_premium = MAX_RISK_RUPEES / qty
        target_in_premium = risk_in_premium * TARGET_RR_RATIO

    details.update({
        "direction": direction,
        "risk_points": round(risk_points, 1),
        "risk_premium": round(risk_in_premium, 1),
        "target_premium": round(target_in_premium, 1),
        "rr_ratio": f"1:{actual_rr:.1f}",
        "sl_nifty": round(sl_nifty, 1),
    })

    # ── Confidence: 3+ = HIGH, 2 with trend = MED ──
    score = bull_score if direction == "BULL" else bear_score
    confidence = "HIGH" if score >= 3 else "MED"

    signal = "CE_BUY" if direction == "BULL" else "PE_BUY"
    details["trigger"] = f"BAG+ORB+{'FVG' if fvg_top else 'MOMENTUM'}"
    details["score"] = f"{score}/6"

    return {
        "signal": signal, "confidence": confidence,
        "direction": direction, "details": details,
        "risk_premium": risk_in_premium,
        "target_premium": target_in_premium,
    }

# ═════════════════════════════════════════════════════════════
#  SECTION 4 — RISK MANAGER
# ═════════════════════════════════════════════════════════════

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
        # Skip position check in paper mode
        if not PAPER_TRADE:
            checks.append(self._check_open_positions(groww))
        for passed, reason in checks:
            if not passed: return False, reason
        return True, "All risk checks passed"

    def _check_orb_formed(self):
        now = ist_now()
        orb_end = now.replace(hour=9, minute=30, second=0)
        if now < orb_end:
            return False, f"ORB forming: {int((orb_end-now).total_seconds()/60)} min"
        return True, "ORB formed"

    def _check_time_window(self):
        now = ist_now()
        if now.hour > NO_TRADE_AFTER_HOUR or (now.hour == NO_TRADE_AFTER_HOUR and now.minute >= NO_TRADE_AFTER_MIN):
            return False, f"Past {NO_TRADE_AFTER_HOUR}:{NO_TRADE_AFTER_MIN:02d}"
        return True, "Time OK"

    def _check_max_trades(self):
        c = self.state.get("trade_count", 0)
        if c >= MAX_TRADES_DAY: return False, f"MAX TRADES: {c}/{MAX_TRADES_DAY}"
        return True, f"Trades {c}/{MAX_TRADES_DAY}"

    def _check_daily_loss(self):
        pnl = self.state.get("daily_pnl_rupees", 0)
        if pnl <= -MAX_DAILY_LOSS_RUPEES: return False, f"MAX LOSS: Rs.{pnl}"
        return True, f"P&L Rs.{pnl:+.0f}"

    def _check_open_positions(self, groww):
        try:
            res = groww.get_positions_for_user(segment=groww.SEGMENT_FNO)
            open_pos = [p for p in res.get("positions", [])
                        if int(p.get("quantity", 0)) != 0 and "NIFTY" in p.get("trading_symbol", "")]
            if open_pos: return False, f"POSITION OPEN: {[p['trading_symbol'] for p in open_pos]}"
            return True, "No open positions"
        except Exception as e:
            return False, f"POSITION CHECK FAILED: {e}"

    def check_premium_range(self, ltp):
        if not ltp or ltp <= 0: return False, "PREMIUM: Could not fetch"
        if ltp < MIN_OPTION_PREMIUM: return False, f"PREMIUM TOO LOW: Rs.{ltp}"
        if ltp > MAX_OPTION_PREMIUM: return False, f"PREMIUM TOO HIGH: Rs.{ltp}"
        return True, f"Premium OK: Rs.{ltp}"

    def check_capital_exposure(self, ltp, qty):
        exposure = ltp * qty
        max_exp = CAPITAL_RUPEES * MAX_CAPITAL_EXPOSURE_PCT / 100
        pct = exposure / CAPITAL_RUPEES * 100
        if exposure > max_exp: return False, f"EXPOSURE: Rs.{exposure:.0f} ({pct:.1f}%) > max"
        return True, f"Exposure OK: Rs.{exposure:.0f} ({pct:.1f}%)"

    def check_spread(self, groww, symbol):
        if PAPER_TRADE: return True, "Spread skipped (paper)"
        try:
            q = groww.get_quote(exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_FNO, trading_symbol=symbol)
            bid = float(q.get("bid_price") or 0)
            ask = float(q.get("offer_price") or 0)
            ltp = float(q.get("last_price") or 1)
            if bid <= 0 or ask <= 0: return True, "Spread skipped"
            spread_pct = (ask - bid) / ltp * 100
            if spread_pct > MAX_SPREAD_PCT: return False, f"SPREAD: {spread_pct:.1f}%"
            return True, f"Spread OK: {spread_pct:.1f}%"
        except Exception as e:
            return True, f"Spread skipped: {e}"

# ═════════════════════════════════════════════════════════════
#  SECTION 5 — UTILITIES
# ═════════════════════════════════════════════════════════════

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
    if month <= 9: return str(month)
    return {10: "O", 11: "N", 12: "D"}[month]

def build_symbol(strike, opt_type, expiry=None):
    if expiry is None: expiry = get_expiry_date()
    yy = expiry.strftime("%y")
    m_code = _nse_month_code(expiry.month)
    dd = expiry.strftime("%d")
    return f"NIFTY{yy}{m_code}{dd}{strike}{opt_type}"

def fmt(p): return f"{p:.2f}"

def load_state():
    today = ist_now().strftime("%Y-%m-%d")
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
            if data.get("date") == today: return data
    except: pass
    return {"date": today, "trade_count": 0, "trades": [],
            "daily_pnl_rupees": 0.0, "last_exit_time": None}

def save_state(state):
    with open(STATE_FILE, "w") as f: json.dump(state, f, indent=2)

# ═════════════════════════════════════════════════════════════
#  SECTION 6 — LOGIN (CACHED)
# ═════════════════════════════════════════════════════════════

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
                logging.info(f"Token age {age_h:.1f}h — refreshing")
    except: pass

    logging.info("Generating fresh token...")
    totp_code = pyotp.TOTP(GROWW_TOTP_SECRET).now()
    access_token = GrowwAPI.get_access_token(api_key=GROWW_TOTP_TOKEN, totp=totp_code)
    groww = GrowwAPI(access_token)
    with open(TOKEN_FILE, "w") as f:
        json.dump({"date": ist_now().strftime("%Y-%m-%d"), "token": access_token,
                   "saved_at": ist_now().strftime("%Y-%m-%d %H:%M:%S")}, f)
    logging.info("✅ Login OK (fresh)")
    return groww

# ═════════════════════════════════════════════════════════════
#  SECTION 7 — FETCH CANDLES (3-day warmup)
# ═════════════════════════════════════════════════════════════

def _parse_candles(raw):
    result = []
    for c in raw:
        if len(c) < 5: continue
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
        with open(CANDLE_FILE, "w") as f: json.dump(cache, f)
    except: pass

def _get_nifty_quote(groww):
    try:
        q = groww.get_quote(exchange="NSE", segment="CASH", trading_symbol="NIFTY")
        if q and q.get("last_price"): return q
    except Exception as e:
        logging.warning(f"Nifty quote failed: {e}")
    return None

def fetch_candles(groww):
    """Single API call per run — loads 3 days for indicator warmup."""
    now = ist_now()
    today = now.strftime("%Y-%m-%d")
    end_dt = now.strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(CANDLE_FILE) as f: cache = json.load(f)
    except: cache = {"date": "", "candles": []}

    existing = cache.get("candles", [])

    # Determine fetch mode
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
            logging.info(f"Candles: {len(cache['candles'])} (incremental={is_incremental})")
            return cache["candles"]
        elif is_incremental and len(existing) >= 30:
            logging.info(f"No new candles — reusing cache ({len(existing)})")
            return existing
    except Exception as e:
        logging.warning(f"Candle API failed: {e}")

    if existing and len(existing) >= 30:
        logging.info(f"Using cached: {len(existing)} candles")
        return existing
    return existing if existing else []

# ═════════════════════════════════════════════════════════════
#  SECTION 8 — SYMBOL RESOLUTION
# ═════════════════════════════════════════════════════════════

def get_option_ltp(groww, symbol):
    try:
        q = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=symbol)
        return float(q["last_price"])
    except Exception as e:
        logging.warning(f"Option LTP failed for {symbol}: {e}")
        return None

def _discover_expiry_from_csv(groww, strike, opt_type):
    try:
        instruments_df = groww._load_instruments()
        mask = ((instruments_df["underlying_symbol"] == "NIFTY") &
                (instruments_df["segment"] == "FNO") &
                (instruments_df["instrument_type"] == opt_type))
        nifty_opts = instruments_df[mask].copy()
        if nifty_opts.empty: return None, None
        nifty_opts["strike_int"] = nifty_opts["strike_price"].apply(
            lambda x: int(float(x)) if not (isinstance(x, float) and x != x) else 0)
        strike_matches = nifty_opts[nifty_opts["strike_int"] == strike]
        if strike_matches.empty: return None, None
        today = ist_now().date()
        best_expiry, best_row = None, None
        for _, row in strike_matches.iterrows():
            exp_str = str(row.get("expiry_date", "")).strip()[:10]
            try: exp_date = datetime.datetime.strptime(exp_str, "%Y-%m-%d").date()
            except: continue
            if exp_date < today: continue
            if best_expiry is None or exp_date < best_expiry:
                best_expiry, best_row = exp_date, row
        if best_row is not None:
            return best_expiry.strftime("%Y-%m-%d"), best_row["trading_symbol"]
    except Exception as e:
        logging.warning(f"CSV discovery failed: {e}")
    return None, None

def _discover_expiry_from_chain(groww, strike, opt_type, calculated_expiry):
    today = ist_now().date()
    calc_str = calculated_expiry.strftime("%Y-%m-%d")
    for offset in range(0, 8):
        d = today + datetime.timedelta(days=offset)
        ds = d.strftime("%Y-%m-%d")
        if ds == calc_str: continue
        try:
            chain = groww.get_option_chain(exchange="NSE", underlying="NIFTY", expiry_date=ds)
            if not isinstance(chain, dict): continue
            strikes_data = chain.get("strikes", {})
            if not strikes_data: continue
            for sk in [str(strike), f"{strike}.0"]:
                if sk in strikes_data and opt_type in strikes_data[sk]:
                    opt_data = strikes_data[sk][opt_type]
                    tsym = opt_data.get("trading_symbol", "")
                    ltp = float(opt_data.get("ltp", 0))
                    if tsym: return ds, tsym, ltp, strikes_data
            available = [int(float(k)) for k in strikes_data if opt_type in strikes_data.get(k, {})]
            if available:
                nearest = min(available, key=lambda s: abs(s - strike))
                for sk in [str(nearest), f"{nearest}.0"]:
                    if sk in strikes_data and opt_type in strikes_data[sk]:
                        opt_data = strikes_data[sk][opt_type]
                        tsym = opt_data.get("trading_symbol", "")
                        ltp = float(opt_data.get("ltp", 0))
                        if tsym: return ds, tsym, ltp, strikes_data
        except: continue
    return None, None, None, None

def get_valid_option_symbol(groww, strike, opt_type):
    expiry = get_expiry_date()
    expiry_str = expiry.strftime("%Y-%m-%d")
    logging.info(f"Resolving: {strike} {opt_type} exp={expiry_str}")

    sym = build_symbol(strike, opt_type, expiry)
    try:
        q = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=sym)
        ltp = float(q.get("last_price", 0))
        if ltp > 0:
            logging.info(f"OK (direct): {sym} Rs.{ltp}")
            return sym, ltp
    except Exception as e:
        logging.warning(f"Direct {sym} failed: {e}")

    chain_found = False
    try:
        chain = groww.get_option_chain(exchange="NSE", underlying="NIFTY", expiry_date=expiry_str)
        if isinstance(chain, dict):
            strikes_data = chain.get("strikes", {})
            if strikes_data:
                chain_found = True
                for sk in [str(strike), f"{strike}.0"]:
                    if sk in strikes_data and opt_type in strikes_data[sk]:
                        opt_data = strikes_data[sk][opt_type]
                        tsym = opt_data.get("trading_symbol", "")
                        ltp = float(opt_data.get("ltp", 0))
                        if tsym:
                            if ltp <= 0:
                                try:
                                    q2 = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=tsym)
                                    ltp = float(q2.get("last_price", 0))
                                except: pass
                            return tsym, ltp
                available = sorted([int(float(k)) for k in strikes_data if opt_type in strikes_data.get(k, {})])
                if available:
                    nearest = min(available, key=lambda s: abs(s - strike))
                    for sk in [str(nearest), f"{nearest}.0"]:
                        if sk in strikes_data and opt_type in strikes_data[sk]:
                            opt_data = strikes_data[sk][opt_type]
                            tsym = opt_data.get("trading_symbol", "")
                            ltp = float(opt_data.get("ltp", 0))
                            if tsym:
                                if ltp <= 0:
                                    try:
                                        q2 = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=tsym)
                                        ltp = float(q2.get("last_price", 0))
                                    except: pass
                                return tsym, ltp
    except Exception as e:
        logging.error(f"Chain failed: {e}")

    if not chain_found:
        disc_expiry, disc_sym, disc_ltp, _ = _discover_expiry_from_chain(groww, strike, opt_type, expiry)
        if disc_sym:
            if disc_ltp <= 0:
                try:
                    q2 = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=disc_sym)
                    disc_ltp = float(q2.get("last_price", 0))
                except: pass
            return disc_sym, disc_ltp

    csv_expiry, csv_sym = _discover_expiry_from_csv(groww, strike, opt_type)
    if csv_sym:
        try:
            q = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=csv_sym)
            ltp = float(q.get("last_price", 0))
            if ltp > 0: return csv_sym, ltp
        except: pass
        return csv_sym, 0

    logging.error(f"ALL FAILED: {strike} {opt_type}")
    return None, None

# ═════════════════════════════════════════════════════════════
#  SECTION 9 — ORDERS (with PAPER TRADE support)
# ═════════════════════════════════════════════════════════════

def place_entry_order(groww, symbol, qty, txn):
    if PAPER_TRADE:
        fake_id = f"PAPER-{ist_now().strftime('%H%M%S')}"
        logging.info(f"📝 PAPER ENTRY | {symbol} | Qty:{qty} | ID:{fake_id}")
        return fake_id
    try:
        res = groww.place_order(
            trading_symbol=symbol, quantity=qty, validity=groww.VALIDITY_DAY,
            exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_FNO,
            product=groww.PRODUCT_MIS, order_type=groww.ORDER_TYPE_MARKET,
            transaction_type=txn, order_reference_id=f"SNP{ist_now().strftime('%H%M%S')}")
        oid = res.get("groww_order_id", "N/A")
        logging.info(f"ENTRY | {symbol} | Qty:{qty} | ID:{oid}")
        return oid
    except Exception as e:
        logging.error(f"ENTRY FAILED: {e}")
        return None

def monitor_and_exit(groww, state):
    trades = state.get("trades", [])
    if not trades: return False
    last_trade = trades[-1]
    if last_trade.get("exited", False): return False
    symbol = last_trade["symbol"]
    qty = last_trade["qty"]
    entry_premium = last_trade["entry_premium"]
    current_ltp = get_option_ltp(groww, symbol)
    if current_ltp is None:
        logging.warning(f"MONITOR: Cannot fetch LTP for {symbol}")
        return False
    pnl_total = (current_ltp - entry_premium) * qty
    logging.info(f"MONITOR | {symbol} | Entry:Rs.{entry_premium} | Now:Rs.{current_ltp} | P&L:Rs.{pnl_total:+.0f}")
    exit_reason = None
    if pnl_total >= TAKE_PROFIT_RUPEES:
        exit_reason = f"TAKE PROFIT Rs.{pnl_total:+.0f}"
    elif pnl_total <= -STOP_LOSS_RUPEES:
        exit_reason = f"STOP LOSS Rs.{pnl_total:+.0f}"
    if exit_reason is None:
        return False
    logging.info(f"{exit_reason} | Selling {symbol} Qty:{qty}")
    try:
        groww.place_order(trading_symbol=symbol, quantity=qty, validity="DAY", exchange="NSE", segment="FNO", product="MIS", order_type="MARKET", transaction_type="SELL", order_reference_id=f"EXIT{ist_now().strftime('%H%M%S')}")
        logging.info(f"EXIT ORDER PLACED | {symbol}")
    except Exception as e:
        logging.error(f"EXIT FAILED: {e}")
        return False
    last_trade["exited"] = True
    last_trade["exit_ltp"] = current_ltp
    last_trade["exit_pnl"] = round(pnl_total, 0)
    last_trade["exit_reason"] = exit_reason
    last_trade["exit_time"] = ist_now().strftime("%Y-%m-%d %H:%M:%S")
    state["daily_pnl_rupees"] = state.get("daily_pnl_rupees", 0) + pnl_total
    save_state(state)
    logging.info(f"CLOSED | {exit_reason} | Daily P&L:Rs.{state['daily_pnl_rupees']:+.0f}")
    return True


def cancel_and_squareoff(groww, state):
    if PAPER_TRADE:
        logging.info("📝 PAPER SQUAREOFF — no real orders to cancel")
        trades = state.get("trades", [])
        logging.info(f"SUMMARY | Trades:{len(trades)} | P&L:Rs.{state.get('daily_pnl_rupees',0):+.0f}")
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
                logging.info(f"Cancelled: {sid}")
    except Exception as e: logging.error(f"OCO cancel error: {e}")
    try:
        positions = groww.get_positions_for_user(segment=groww.SEGMENT_FNO).get("positions", [])
        for pos in positions:
            sym = pos.get("trading_symbol", ""); qty = int(pos.get("quantity", 0))
            if qty != 0 and "NIFTY" in sym:
                side = groww.TRANSACTION_TYPE_SELL if qty > 0 else groww.TRANSACTION_TYPE_BUY
                groww.place_order(trading_symbol=sym, quantity=abs(qty),
                    validity=groww.VALIDITY_DAY, exchange=groww.EXCHANGE_NSE,
                    segment=groww.SEGMENT_FNO, product=groww.PRODUCT_MIS,
                    order_type=groww.ORDER_TYPE_MARKET, transaction_type=side)
                logging.info(f"Closed: {sym} Qty:{abs(qty)}")
    except Exception as e: logging.error(f"Squareoff error: {e}")
    trades = state.get("trades", [])
    logging.info(f"SUMMARY | Trades:{len(trades)} | P&L:Rs.{state.get('daily_pnl_rupees',0):+.0f}")

# ═════════════════════════════════════════════════════════════
#  SECTION 10 — MAIN
# ═════════════════════════════════════════════════════════════

def main():
    now = ist_now()
    state = load_state()

    if not is_market_hours() and not is_squareoff_time():
        logging.info(f"[{now.strftime('%H:%M')}] Outside hours. Skip.")
        return

    if is_squareoff_time():
        groww = login()
        cancel_and_squareoff(groww, state)
        return

    # -- MONITOR OPEN POSITION FIRST --
    trades = state.get("trades", [])
    if trades and not trades[-1].get("exited", False):
        groww = login()
        exited = monitor_and_exit(groww, state)
        if not exited:
            logging.info(f"[{now.strftime('%H:%M')}] Position open. Monitoring...")
        return

    if state.get("trade_count", 0) >= MAX_TRADES_DAY:
        logging.info(f"[{now.strftime('%H:%M')}] Already traded. Skip.")
        return

    past_cutoff = now.hour > NO_TRADE_AFTER_HOUR or (now.hour == NO_TRADE_AFTER_HOUR and now.minute >= NO_TRADE_AFTER_MIN)
    if past_cutoff:
        logging.info(f"[{now.strftime('%H:%M')}] Past cutoff. Waiting for squareoff.")
        return

    mode_tag = "PAPER" if PAPER_TRADE else "LIVE"
    logging.info(f"=== {mode_tag} | {now.strftime('%Y-%m-%d %H:%M:%S')} | Trades:{state['trade_count']}/{MAX_TRADES_DAY} | P&L:Rs.{state.get('daily_pnl_rupees',0):+.0f} ===")

    groww = login()

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
        logging.info(f"ORB | H:{orb['orb_high']} L:{orb['orb_low']} R:{orb['orb_range']} GAP:{orb['gap_direction']}({orb['gap_size']})")

    result = compute_signal(candles, orb)
    signal = result["signal"]
    confidence = result.get("confidence")
    d = result.get("details", {})

    logging.info(f"  Signal:{signal} | Conf:{confidence} | {d.get('trigger','--')}")
    logging.info(f"  Close:{d.get('close','--')} | ORB:{d.get('orb_high','--')}/{d.get('orb_low','--')} | Gap:{d.get('gap_direction','--')}({d.get('gap_size','--')})")
    logging.info(f"  ADX:{d.get('adx','--')} RSI:{d.get('rsi','--')} VWAP:{d.get('vwap','--')} | Bull:{d.get('bull_score','--')} Bear:{d.get('bear_score','--')}")
    if d.get("fvg_top"):
        logging.info(f"  FVG: {d['fvg_bot']}-{d['fvg_top']} ({d.get('fvg_size','')} pts)")
    if d.get("reason"):
        logging.info(f"  -> {d['reason']}")

    if signal == "NO_TRADE":
        return

    if confidence not in ("HIGH", "MED"):
        logging.info(f"  -> {confidence} confidence -- skip")
        return

    risk = RiskManager(state)
    ok, reason = risk.check_can_trade(groww)
    if not ok:
        logging.warning(f"BLOCKED: {reason}")
        return
    logging.info(f"Risk OK: {reason}")

    opt_type = "CE" if "CE" in signal else "PE"
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
        logging.warning(f"ITM {strike} failed, trying ATM {atm}")
        symbol, option_ltp = get_valid_option_symbol(groww, atm, opt_type)
        if symbol is None:
            logging.error("Cannot resolve symbol")
            return
        strike = atm

    logging.info(f"Resolved: {symbol} | Rs.{option_ltp} | Nifty:{nifty_ltp}")

    for check_fn, args in [
        (risk.check_spread, (groww, symbol)),
        (risk.check_premium_range, (option_ltp,)),
        (risk.check_capital_exposure, (option_ltp, qty)),
    ]:
        ok, msg = check_fn(*args)
        if not ok:
            logging.warning(f"BLOCKED: {msg}")
            return
        logging.info(msg)

    risk_premium = result.get("risk_premium", 0)
    target_premium = result.get("target_premium", 0)

    if risk_premium <= 0:
        logging.error("Invalid risk calculation")
        return

    sl_price = round(max(option_ltp - risk_premium, 1.0), 1)
    target_price = round(option_ltp + target_premium, 1)
    rr = target_premium / risk_premium if risk_premium > 0 else 0

    if rr < MIN_RR_RATIO:
        logging.warning(f"RR {rr:.1f} < {MIN_RR_RATIO} minimum -- REJECTED")
        return

    total_risk = risk_premium * qty
    total_reward = target_premium * qty

    tp_at = round(option_ltp + TAKE_PROFIT_RUPEES / qty, 1)
    sl_at = round(max(option_ltp - STOP_LOSS_RUPEES / qty, 1.0), 1)

    logging.info(f"PLAN | Entry:~Rs.{option_ltp} SL:Rs.{sl_price} Target:Rs.{target_price}")
    logging.info(f"      Risk:Rs.{total_risk:.0f} Reward:Rs.{total_reward:.0f} RR:1:{rr:.1f}")
    logging.info(f"      TP at Rs.{tp_at} (+Rs.{TAKE_PROFIT_RUPEES}) | SL at Rs.{sl_at} (-Rs.{STOP_LOSS_RUPEES})")

    oid = place_entry_order(groww, symbol, qty, groww.TRANSACTION_TYPE_BUY)
    if not oid:
        return

    time.sleep(1)

    if PAPER_TRADE:
        entry_premium = option_ltp
    else:
        entry_premium = get_option_ltp(groww, symbol) or option_ltp

    sl_price = round(max(entry_premium - risk_premium, 1.0), 1)
    target_price = round(entry_premium + target_premium, 1)

    # NO OCO - bot monitors via cron
    smart_id = None

    state["trade_count"] += 1
    state["trades"].append({
        "signal": signal, "confidence": confidence,
        "symbol": symbol, "qty": qty,
        "entry_id": str(oid), "smart_id": None,
        "entry_premium": entry_premium,
        "target": target_price, "sl": sl_price,
        "tp_rupees": TAKE_PROFIT_RUPEES, "sl_rupees": STOP_LOSS_RUPEES,
        "nifty_ltp": nifty_ltp, "strike": strike,
        "orb_high": orb["orb_high"], "orb_low": orb["orb_low"],
        "gap": orb["gap_direction"], "gap_size": orb["gap_size"],
        "entry_mode": d.get("entry_mode", "unknown"),
        "trigger": d.get("trigger", "unknown"),
        "rr": f"1:{rr:.1f}",
        "bull_score": d.get("bull_score", ""), "bear_score": d.get("bear_score", ""),
        "paper": PAPER_TRADE,
        "exited": False,
        "time": now.strftime("%Y-%m-%d %H:%M:%S")
    })
    save_state(state)

    tag = "PAPER TRADE" if PAPER_TRADE else "LIVE TRADE"
    logging.info(f"{tag} | {signal} {confidence} | {symbol}")
    logging.info(f"   Entry:Rs.{entry_premium} | TP:+Rs.{TAKE_PROFIT_RUPEES} | SL:-Rs.{STOP_LOSS_RUPEES}")
    logging.info(f"   Bot monitors every cron run -- no OCO needed")

if __name__ == "__main__":
    main()

