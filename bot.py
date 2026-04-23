# ============================================================
#  OPTIONS SCALPER v3 — ORB (Opening Range Breakout)
#  VPS (Hetzner + Groww API)
#  Strategy: Trade ONCE per day on 15-min ORB breakout
#  with trailing SL + ITM strike + regime filter
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
ITM_OFFSET       = 100   # Buy 100 pts ITM for better delta

# ── ORB Strategy params ──
ORB_MINUTES          = 15      # First 15 min range
ORB_BUFFER_POINTS    = 5       # Buffer above/below ORB level
MIN_ORB_RANGE        = 30      # Skip if ORB range < 30 pts (too tight)
MAX_ORB_RANGE        = 250     # Skip if ORB range > 250 pts (too wide)
RETEST_REQUIRED      = True    # Wait for candle close beyond level
NO_TRADE_AFTER_HOUR  = 12      # No new entries after 12:00 PM
NO_TRADE_AFTER_MIN   = 0

# ── SL / Target ──
SL_BEYOND_ORB        = True    # SL at opposite ORB level
SL_BUFFER_POINTS     = 10      # Extra buffer on SL
TRAIL_ACTIVATE_MULT  = 1.3     # Start trailing at 1.3x entry
TRAIL_STEP_PCT       = 0.10    # Trail SL 10% below peak
TARGET_MULT          = 2.0     # Target = 2x risk

# ── Risk management ──
MAX_TRADES_DAY            = 1       # ONE trade per day
MAX_DAILY_LOSS_RUPEES     = 1500
MAX_LOSS_PER_TRADE_RUPEES = 1000
CAPITAL_RUPEES            = 50000
MAX_CAPITAL_EXPOSURE_PCT  = 20
MIN_OPTION_PREMIUM        = 30
MAX_OPTION_PREMIUM        = 300
MAX_SPREAD_PCT            = 3.0

# ── Market regime filter (ADX) ──
MIN_ADX_FOR_TRADE    = 18      # Don't trade if ADX < 18 (sideways)
ADX_LEN              = 14
ATR_LEN              = 14
RSI_LEN              = 14
EMA_FAST             = 8
EMA_SLOW             = 21

# ── Time ──
SQUAREOFF_HOUR       = 15
SQUAREOFF_MIN        = 10
OPENING_RANGE_END_H  = 9
OPENING_RANGE_END_M  = 30      # 9:15 + 15 min = 9:30

# ── Expiry ──
NIFTY_EXPIRY_WEEKDAY = 1       # 0=Monday

# ── Files ──
STATE_FILE  = "/root/scalper/state.json"
TOKEN_FILE  = "/root/scalper/token.json"
CANDLE_FILE = "/root/scalper/candles.json"
ORB_FILE    = "/root/scalper/orb.json"

# ═════════════════════════════════════════════════════════════
#  SECTION 2 — INDICATORS (minimal — only what ORB needs)
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
    tr = [None]+[max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
                 for i in range(1,len(closes))]
    return rma(tr, period)

def calc_adx(highs, lows, closes, period=14):
    plus_dm = [None]+[(highs[i]-highs[i-1]) if (highs[i]-highs[i-1])>(lows[i-1]-lows[i]) and (highs[i]-highs[i-1])>0 else 0.0 for i in range(1,len(closes))]
    minus_dm= [None]+[(lows[i-1]-lows[i]) if (lows[i-1]-lows[i])>(highs[i]-highs[i-1]) and (lows[i-1]-lows[i])>0 else 0.0 for i in range(1,len(closes))]
    tr      = [None]+[max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1,len(closes))]
    tr_s=rma(tr,period); pdm_s=rma(plus_dm,period); mdm_s=rma(minus_dm,period)
    dx=[]
    for ts,ps,ms in zip(tr_s,pdm_s,mdm_s):
        if None in (ts,ps,ms) or ts==0:
            dx.append(None)
        else:
            p=100*ps/ts; m=100*ms/ts
            dx.append(100*abs(p-m)/(p+m) if (p+m)!=0 else 0)
    return rma(dx,period)

def calc_rsi(closes, period=14):
    gains  = [None]+[max(closes[i]-closes[i-1],0) for i in range(1,len(closes))]
    losses = [None]+[max(closes[i-1]-closes[i],0) for i in range(1,len(closes))]
    ag,al  = rma(gains,period), rma(losses,period)
    return [None if g is None or l is None else (100.0 if l==0 else 100-100/(1+g/l))
            for g,l in zip(ag,al)]

def safe(s, idx=-1):
    try: return s[idx]
    except: return None

# ═════════════════════════════════════════════════════════════
#  SECTION 3 — ORB SIGNAL ENGINE
# ═════════════════════════════════════════════════════════════

def load_orb():
    """Load today's ORB levels."""
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
    """Extract ORB high/low from first 15-min candles (3 x 5-min candles after 9:15)."""
    orb_candles = []
    for c in candles:
        ts = c.get("ts", "")
        if not ts:
            continue
        try:
            dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except:
            continue
        today = ist_now().date()
        if dt.date() != today:
            continue
        # 9:15 to 9:30 = ORB window
        t = dt.time()
        if datetime.time(9, 15) <= t < datetime.time(9, 30):
            orb_candles.append(c)

    if len(orb_candles) < 2:
        return None

    orb_high = max(c["high"] for c in orb_candles)
    orb_low  = min(c["low"]  for c in orb_candles)
    orb_open = orb_candles[0]["open"]
    orb_range = orb_high - orb_low

    return {
        "date": ist_now().strftime("%Y-%m-%d"),
        "orb_high": round(orb_high, 2),
        "orb_low": round(orb_low, 2),
        "orb_open": round(orb_open, 2),
        "orb_range": round(orb_range, 2),
        "computed_at": ist_now().strftime("%H:%M:%S")
    }

def compute_orb_signal(candles, orb):
    """Check if current price breaks ORB with confirmation."""
    if not orb or not candles:
        return {"signal": "NO_TRADE", "details": {"reason": "No ORB data"}}

    orb_high  = orb["orb_high"]
    orb_low   = orb["orb_low"]
    orb_range = orb["orb_range"]

    # Range filter
    if orb_range < MIN_ORB_RANGE:
        return {"signal": "NO_TRADE", "details": {
            "reason": f"ORB range too tight: {orb_range:.0f} < {MIN_ORB_RANGE}",
            "orb_high": orb_high, "orb_low": orb_low, "orb_range": orb_range}}

    if orb_range > MAX_ORB_RANGE:
        return {"signal": "NO_TRADE", "details": {
            "reason": f"ORB range too wide: {orb_range:.0f} > {MAX_ORB_RANGE}",
            "orb_high": orb_high, "orb_low": orb_low, "orb_range": orb_range}}

    # Time filter
    now = ist_now()
    if now.hour > NO_TRADE_AFTER_HOUR or (now.hour == NO_TRADE_AFTER_HOUR and now.minute >= NO_TRADE_AFTER_MIN):
        return {"signal": "NO_TRADE", "details": {
            "reason": f"Past {NO_TRADE_AFTER_HOUR}:{NO_TRADE_AFTER_MIN:02d} cutoff"}}

    # Need enough candles for regime filter
    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]

    if len(closes) < 30:
        return {"signal": "NO_TRADE", "details": {"reason": f"Need 30 candles, have {len(closes)}"}}

    # Market regime: ADX filter
    adx_s = calc_adx(highs, lows, closes, ADX_LEN)
    adx   = safe(adx_s)
    if adx is not None and adx < MIN_ADX_FOR_TRADE:
        return {"signal": "NO_TRADE", "details": {
            "reason": f"Sideways market: ADX {adx:.1f} < {MIN_ADX_FOR_TRADE}",
            "adx": round(adx, 1), "orb_high": orb_high, "orb_low": orb_low}}

    # RSI extreme filter — don't buy CE if RSI > 80, don't buy PE if RSI < 20
    rsi_s = calc_rsi(closes, RSI_LEN)
    rsi = safe(rsi_s)

    # ATR for context
    atr_s = calc_atr(highs, lows, closes, ATR_LEN)
    atr = safe(atr_s)

    # EMA trend
    ema_f = ema(closes, EMA_FAST)
    ema_s = ema(closes, EMA_SLOW)
    ef = safe(ema_f)
    es = safe(ema_s)
    trend_bull = ef is not None and es is not None and ef > es
    trend_bear = ef is not None and es is not None and ef < es

    # Current candle (last closed)
    last_close = closes[-1]
    last_high  = highs[-1]
    last_low   = lows[-1]

    # Breakout detection: candle CLOSES beyond level
    breakout_high = orb_high + ORB_BUFFER_POINTS
    breakout_low  = orb_low  - ORB_BUFFER_POINTS

    signal = "NO_TRADE"
    confidence = None
    details = {
        "orb_high": orb_high, "orb_low": orb_low, "orb_range": round(orb_range, 1),
        "close": round(last_close, 2),
        "adx": round(adx, 1) if adx else "N/A",
        "rsi": round(rsi, 1) if rsi else "N/A",
        "atr": round(atr, 1) if atr else "N/A",
        "trend": "Bull" if trend_bull else ("Bear" if trend_bear else "Flat"),
        "breakout_high": round(breakout_high, 2),
        "breakout_low": round(breakout_low, 2),
    }

    if last_close > breakout_high:
        # Bullish breakout
        if rsi is not None and rsi > 80:
            details["reason"] = f"RSI overbought ({rsi:.0f}) — skip CE"
        elif not trend_bull:
            # Allow but mark lower confidence
            signal = "CE_BUY"
            confidence = "MED"
            details["trigger"] = "ORB_BREAKOUT_HIGH"
            details["note"] = "Against EMA trend"
        else:
            signal = "CE_BUY"
            confidence = "HIGH"
            details["trigger"] = "ORB_BREAKOUT_HIGH"

    elif last_close < breakout_low:
        # Bearish breakout
        if rsi is not None and rsi < 20:
            details["reason"] = f"RSI oversold ({rsi:.0f}) — skip PE"
        elif not trend_bear:
            signal = "PE_BUY"
            confidence = "MED"
            details["trigger"] = "ORB_BREAKOUT_LOW"
            details["note"] = "Against EMA trend"
        else:
            signal = "PE_BUY"
            confidence = "HIGH"
            details["trigger"] = "ORB_BREAKOUT_LOW"

    else:
        details["reason"] = "Price inside ORB range — waiting"

    return {"signal": signal, "confidence": confidence, "details": details}

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
            self._check_open_positions(groww),
        ]
        for passed, reason in checks:
            if not passed:
                return False, reason
        return True, "All risk checks passed"

    def _check_orb_formed(self):
        now = ist_now()
        orb_end = now.replace(hour=OPENING_RANGE_END_H, minute=OPENING_RANGE_END_M, second=0)
        if now < orb_end:
            remaining = int((orb_end - now).total_seconds() / 60)
            return False, f"ORB forming: {remaining} min left"
        return True, "ORB formed"

    def _check_time_window(self):
        now = ist_now()
        if now.hour > NO_TRADE_AFTER_HOUR or (now.hour == NO_TRADE_AFTER_HOUR and now.minute >= NO_TRADE_AFTER_MIN):
            return False, f"Past {NO_TRADE_AFTER_HOUR}:{NO_TRADE_AFTER_MIN:02d}"
        sq = now.replace(hour=SQUAREOFF_HOUR, minute=SQUAREOFF_MIN, second=0)
        mins = (sq - now).total_seconds() / 60
        if 0 < mins < 20:
            return False, f"Near squareoff: {int(mins)} min"
        return True, "Time OK"

    def _check_max_trades(self):
        c = self.state.get("trade_count", 0)
        if c >= MAX_TRADES_DAY:
            return False, f"MAX TRADES: {c}/{MAX_TRADES_DAY}"
        return True, f"Trades {c}/{MAX_TRADES_DAY}"

    def _check_daily_loss(self):
        pnl = self.state.get("daily_pnl_rupees", 0)
        if pnl <= -MAX_DAILY_LOSS_RUPEES:
            return False, f"MAX DAILY LOSS: Rs.{pnl}"
        return True, f"P&L Rs.{pnl:+.0f}"

    def _check_open_positions(self, groww):
        try:
            res = groww.get_positions_for_user(segment=groww.SEGMENT_FNO)
            open_pos = [p for p in res.get("positions", [])
                        if int(p.get("quantity", 0)) != 0 and "NIFTY" in p.get("trading_symbol", "")]
            if open_pos:
                return False, f"POSITION OPEN: {[p['trading_symbol'] for p in open_pos]}"
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
        if exposure > max_exp:
            return False, f"EXPOSURE: Rs.{exposure:.0f} ({pct:.1f}%) > max"
        return True, f"Exposure OK: Rs.{exposure:.0f} ({pct:.1f}%)"

    def calc_sl_target(self, entry_premium, orb, signal):
        """SL = opposite ORB level risk mapped to premium.
        Target = 2x risk."""
        orb_range = orb["orb_range"]
        # Risk in NIFTY points = ORB range + buffer
        risk_points = orb_range + SL_BUFFER_POINTS

        # Approximate premium movement (delta ~0.5 for ITM)
        delta = 0.55
        risk_in_premium = risk_points * delta

        # Cap to max loss
        qty = LOT_SIZE * LOTS_TO_TRADE
        if risk_in_premium * qty > MAX_LOSS_PER_TRADE_RUPEES:
            risk_in_premium = MAX_LOSS_PER_TRADE_RUPEES / qty

        sl_price = round(max(entry_premium - risk_in_premium, 1.0), 1)
        target_price = round(entry_premium + (risk_in_premium * TARGET_MULT), 1)

        return sl_price, target_price, risk_in_premium

    def check_spread(self, groww, symbol):
        try:
            q = groww.get_quote(exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_FNO, trading_symbol=symbol)
            bid = float(q.get("bid_price") or 0)
            ask = float(q.get("offer_price") or 0)
            ltp = float(q.get("last_price") or 1)
            if bid <= 0 or ask <= 0: return True, "Spread skipped (no bid/ask)"
            spread_pct = (ask - bid) / ltp * 100
            if spread_pct > MAX_SPREAD_PCT: return False, f"SPREAD: {spread_pct:.1f}% > {MAX_SPREAD_PCT}%"
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
    return (now.replace(hour=9, minute=15, second=0, microsecond=0) <= now <=
            now.replace(hour=SQUAREOFF_HOUR, minute=SQUAREOFF_MIN, second=0, microsecond=0))

def is_squareoff_time():
    now = ist_now()
    return now.hour > SQUAREOFF_HOUR or (now.hour == SQUAREOFF_HOUR and now.minute >= SQUAREOFF_MIN)

def get_atm_strike(ltp, step=50):
    return int(round(ltp / step) * step)

def get_expiry_date():
    today = ist_now().date()
    now = ist_now()
    target_weekday = NIFTY_EXPIRY_WEEKDAY
    days_ahead = (target_weekday - today.weekday()) % 7
    if days_ahead == 0:
        if now.hour > 15 or (now.hour == 15 and now.minute >= 30):
            days_ahead = 7
    expiry = today + datetime.timedelta(days=days_ahead)
    return expiry

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
#  SECTION 6 — LOGIN
# ═════════════════════════════════════════════════════════════

def login(force=True):
    logging.info("Generating fresh TOTP token...")
    totp_code = pyotp.TOTP(GROWW_TOTP_SECRET).now()
    access_token = GrowwAPI.get_access_token(api_key=GROWW_TOTP_TOKEN, totp=totp_code)
    groww = GrowwAPI(access_token)
    with open(TOKEN_FILE, "w") as f:
        json.dump({"date": ist_now().strftime("%Y-%m-%d"), "token": access_token,
                   "saved_at": ist_now().strftime("%Y-%m-%d %H:%M:%S")}, f)
    logging.info("✅ Groww login OK (FRESH TOKEN)")
    return groww

# ═════════════════════════════════════════════════════════════
#  SECTION 7 — FETCH CANDLES (uses new API + fallback)
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
    except Exception as e: logging.warning(f"Cache save failed: {e}")

def _get_nifty_quote(groww):
    try:
        q = groww.get_quote(exchange="NSE", segment="CASH", trading_symbol="NIFTY")
        if q and q.get("last_price"): return q
    except Exception as e:
        logging.warning(f"Nifty quote failed: {e}")
    return None

def fetch_candles(groww):
    now = ist_now()
    today = now.strftime("%Y-%m-%d")
    end_dt = now.strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(CANDLE_FILE) as f: cache = json.load(f)
    except: cache = {"date": "", "candles": []}
    if cache.get("date") != today:
        cache = {"date": today, "candles": []}
    existing = cache.get("candles", [])

    # Determine start time
    if existing and existing[-1].get("ts"):
        try:
            last_dt = datetime.datetime.strptime(existing[-1]["ts"], "%Y-%m-%d %H:%M:%S")
            start_dt = (last_dt + datetime.timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
        except:
            start_dt = f"{today} 09:15:00"
    else:
        # Fetch from start of today + previous day for indicators
        yesterday = (now - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
        start_dt = f"{yesterday} 09:15:00"

    # Try new API first
    try:
        res = groww.get_historical_candles(
            exchange="NSE",
            segment="CASH",
            groww_symbol="NSE-NIFTY",
            start_time=start_dt,
            end_time=end_dt,
            candle_interval=groww.CANDLE_INTERVAL_MIN_5
        )
        raw = res.get("candles", []) if isinstance(res, dict) else []
        if raw:
            new_candles = _parse_candles(raw)
            existing_ts = {c["ts"] for c in existing if c.get("ts")}
            merged = existing + [c for c in new_candles if c.get("ts") not in existing_ts]
            cache["candles"] = merged[-300:]
            _save_candles(cache)
            logging.info(f"Candles (new API): {len(cache['candles'])} total")
            return cache["candles"]
    except Exception as e:
        logging.warning(f"New candle API failed: {e}")

    # Fallback to deprecated API
    try:
        res = groww.get_historical_candle_data(
            trading_symbol="NIFTY", exchange="NSE", segment="CASH",
            start_time=start_dt, end_time=end_dt, interval_in_minutes=5)
        raw = res.get("candles", []) if isinstance(res, dict) else []
        if raw:
            new_candles = _parse_candles(raw)
            existing_ts = {c["ts"] for c in existing if c.get("ts")}
            merged = existing + [c for c in new_candles if c.get("ts") not in existing_ts]
            cache["candles"] = merged[-300:]
            _save_candles(cache)
            logging.info(f"Candles (legacy API): {len(cache['candles'])} total")
            return cache["candles"]
    except Exception as e:
        logging.warning(f"Legacy candle API failed: {e}")

    if existing:
        logging.info(f"Using cached candles: {len(existing)}")
        return existing

    # Last resort: live quote
    q = _get_nifty_quote(groww)
    if q:
        ltp = float(q["last_price"])
        ohlc = q.get("ohlc", {})
        snap = {"ts": now.strftime("%Y-%m-%d %H:%M:%S"),
                "open": float(ohlc.get("open", ltp)), "high": float(ohlc.get("high", ltp)),
                "low": float(ohlc.get("low", ltp)), "close": ltp, "volume": 0.0}
        cache["candles"].append(snap)
        _save_candles(cache)
        return cache["candles"]
    return []

# ═════════════════════════════════════════════════════════════
#  SECTION 8 — SYMBOL RESOLUTION (kept from v2)
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
        logging.warning(f"CSV expiry discovery failed: {e}")
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
            logging.info(f"Chain discovery: expiry={ds} has {len(strikes_data)} strikes")
            for sk in [str(strike), f"{strike}.0"]:
                if sk in strikes_data and opt_type in strikes_data[sk]:
                    opt_data = strikes_data[sk][opt_type]
                    tsym = opt_data.get("trading_symbol", "")
                    ltp = float(opt_data.get("ltp", 0))
                    if tsym:
                        return ds, tsym, ltp, strikes_data
            # Nearest strike
            available = []
            for k, v in strikes_data.items():
                if opt_type in v:
                    try: available.append(int(float(k)))
                    except: continue
            if available:
                nearest = min(available, key=lambda s: abs(s - strike))
                for sk in [str(nearest), f"{nearest}.0"]:
                    if sk in strikes_data and opt_type in strikes_data[sk]:
                        opt_data = strikes_data[sk][opt_type]
                        tsym = opt_data.get("trading_symbol", "")
                        ltp = float(opt_data.get("ltp", 0))
                        if tsym:
                            return ds, tsym, ltp, strikes_data
        except: continue
    return None, None, None, None

def get_valid_option_symbol(groww, strike, opt_type):
    expiry = get_expiry_date()
    expiry_str = expiry.strftime("%Y-%m-%d")
    logging.info(f"Resolving: strike={strike} type={opt_type} expiry={expiry_str}")

    # Try 1: Direct build
    sym = build_symbol(strike, opt_type, expiry)
    try:
        q = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=sym)
        ltp = float(q.get("last_price", 0))
        if ltp > 0:
            logging.info(f"Symbol OK (direct): {sym} | LTP: Rs.{ltp}")
            return sym, ltp
    except Exception as e:
        logging.warning(f"Direct symbol {sym} failed: {e}")

    # Try 2: Option chain
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
                # Nearest
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
        logging.error(f"Option chain failed: {e}")

    # Try 3: Discovery
    if not chain_found:
        disc_expiry, disc_sym, disc_ltp, _ = _discover_expiry_from_chain(groww, strike, opt_type, expiry)
        if disc_sym:
            if disc_ltp <= 0:
                try:
                    q2 = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=disc_sym)
                    disc_ltp = float(q2.get("last_price", 0))
                except: pass
            return disc_sym, disc_ltp

    # Try 4: CSV
    csv_expiry, csv_sym = _discover_expiry_from_csv(groww, strike, opt_type)
    if csv_sym:
        try:
            q = groww.get_quote(exchange="NSE", segment="FNO", trading_symbol=csv_sym)
            ltp = float(q.get("last_price", 0))
            if ltp > 0: return csv_sym, ltp
        except: pass
        return csv_sym, 0

    logging.error(f"ALL METHODS FAILED: strike={strike} type={opt_type}")
    return None, None

# ═════════════════════════════════════════════════════════════
#  SECTION 9 — ORDER PLACEMENT
# ═════════════════════════════════════════════════════════════

def place_entry_order(groww, symbol, qty, txn):
    try:
        res = groww.place_order(
            trading_symbol=symbol, quantity=qty, validity=groww.VALIDITY_DAY,
            exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_FNO,
            product=groww.PRODUCT_MIS, order_type=groww.ORDER_TYPE_MARKET,
            transaction_type=txn, order_reference_id=f"ORB{ist_now().strftime('%H%M%S')}")
        oid = res.get("groww_order_id", "N/A")
        logging.info(f"ENTRY | {symbol} | {txn} | Qty:{qty} | ID:{oid}")
        return oid, res.get("order_status", "N/A")
    except Exception as e:
        logging.error(f"ENTRY FAILED: {e}")
        return None, str(e)

def place_oco_order(groww, symbol, qty, entry_premium, sl_price, target_price):
    if not entry_premium or entry_premium <= 0: return None
    logging.info(f"OCO | Entry:Rs.{entry_premium} | Target:Rs.{target_price} | SL:Rs.{sl_price}")
    try:
        ref = f"OCO{ist_now().strftime('%H%M%S')}"
        res = groww.create_smart_order(
            smart_order_type=groww.SMART_ORDER_TYPE_OCO, reference_id=ref,
            segment=groww.SEGMENT_FNO, trading_symbol=symbol, quantity=qty,
            product_type=groww.PRODUCT_MIS, exchange=groww.EXCHANGE_NSE,
            duration=groww.VALIDITY_DAY, net_position_quantity=qty,
            transaction_type=groww.TRANSACTION_TYPE_SELL,
            target={"trigger_price": fmt(round(target_price * 0.99, 1)),
                    "order_type": groww.ORDER_TYPE_LIMIT,
                    "price": fmt(target_price)},
            stop_loss={"trigger_price": fmt(round(sl_price * 1.01, 1)),
                      "order_type": groww.ORDER_TYPE_STOP_LOSS_MARKET,
                      "price": None})
        sid = res.get("smart_order_id", "N/A")
        logging.info(f"OCO PLACED | ID:{sid}")
        return sid
    except Exception as e:
        logging.error(f"OCO FAILED: {e}")
        logging.warning(f"⚠️ MANUAL ACTION: SL=Rs.{sl_price} Target=Rs.{target_price}")
        return None

def cancel_and_squareoff(groww, state):
    logging.info("EOD: cancelling OCO + squaring off")
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
                logging.info(f"Cancelled OCO: {sid}")
    except Exception as e:
        logging.error(f"OCO cancel error: {e}")
    try:
        positions = groww.get_positions_for_user(segment=groww.SEGMENT_FNO).get("positions", [])
        for pos in positions:
            sym = pos.get("trading_symbol", "")
            qty = int(pos.get("quantity", 0))
            if qty != 0 and "NIFTY" in sym:
                side = groww.TRANSACTION_TYPE_SELL if qty > 0 else groww.TRANSACTION_TYPE_BUY
                res = groww.place_order(trading_symbol=sym, quantity=abs(qty),
                    validity=groww.VALIDITY_DAY, exchange=groww.EXCHANGE_NSE,
                    segment=groww.SEGMENT_FNO, product=groww.PRODUCT_MIS,
                    order_type=groww.ORDER_TYPE_MARKET, transaction_type=side)
                logging.info(f"Closed: {sym} Qty:{abs(qty)} ID:{res.get('groww_order_id')}")
    except Exception as e:
        logging.error(f"Square-off error: {e}")
    trades = state.get("trades", [])
    logging.info(f"DAILY SUMMARY | Trades:{len(trades)}/{MAX_TRADES_DAY} | P&L:Rs.{state.get('daily_pnl_rupees',0):+.0f}")
    for i, t in enumerate(trades, 1):
        logging.info(f"  {i}. {t.get('signal')} | {t.get('symbol')} | Entry:Rs.{t.get('entry_premium','?')} T:Rs.{t.get('target','?')} SL:Rs.{t.get('sl','?')}")

# ═════════════════════════════════════════════════════════════
#  SECTION 10 — MAIN
# ═════════════════════════════════════════════════════════════

def main():
    now = ist_now()
    state = load_state()
    logging.info(f"═══ Run: {now.strftime('%Y-%m-%d %H:%M:%S')} IST | Trades:{state['trade_count']}/{MAX_TRADES_DAY} | P&L:Rs.{state.get('daily_pnl_rupees',0):+.0f} ═══")

    # ── Squareoff check ──
    if is_squareoff_time():
        groww = login()
        cancel_and_squareoff(groww, state)
        return

    if not is_market_hours():
        logging.info("Outside market hours. Skipping.")
        return

    # ── Already traded today ──
    if state.get("trade_count", 0) >= MAX_TRADES_DAY:
        logging.info(f"Already traded {state['trade_count']}/{MAX_TRADES_DAY} today. Done.")
        return

    groww = login()

    # ── Fetch candles ──
    candles = fetch_candles(groww)
    if not candles:
        logging.error("No candles available")
        return

    # ── Compute or load ORB levels ──
    orb = load_orb()
    if orb is None:
        orb_end = ist_now().replace(hour=OPENING_RANGE_END_H, minute=OPENING_RANGE_END_M, second=0)
        if ist_now() < orb_end:
            logging.info(f"ORB still forming. Wait until {OPENING_RANGE_END_H}:{OPENING_RANGE_END_M:02d}")
            return
        orb = compute_orb_levels(candles)
        if orb is None:
            logging.error("Cannot compute ORB levels — not enough candles in 9:15–9:30 window")
            return
        save_orb(orb)
        logging.info(f"ORB COMPUTED | High:{orb['orb_high']} Low:{orb['orb_low']} Range:{orb['orb_range']}")

    logging.info(f"ORB | High:{orb['orb_high']} Low:{orb['orb_low']} Range:{orb['orb_range']}")

    # ── Generate signal ──
    result = compute_orb_signal(candles, orb)
    signal = result["signal"]
    confidence = result.get("confidence")
    d = result.get("details", {})

    logging.info("=" * 55)
    logging.info(f"  Signal: {signal} | Confidence: {confidence}")
    logging.info(f"  Close: {d.get('close','N/A')} | ORB High: {d.get('orb_high','N/A')} | ORB Low: {d.get('orb_low','N/A')}")
    logging.info(f"  ADX: {d.get('adx','N/A')} | RSI: {d.get('rsi','N/A')} | Trend: {d.get('trend','N/A')}")
    if d.get("trigger"): logging.info(f"  Trigger: {d['trigger']}")
    if d.get("reason"):  logging.info(f"  Reason: {d['reason']}")
    if d.get("note"):    logging.info(f"  Note: {d['note']}")
    logging.info("=" * 55)

    if signal == "NO_TRADE":
        logging.info("No breakout. Waiting.")
        return

    # Only trade HIGH confidence (trend-aligned breakouts)
    if confidence != "HIGH":
        logging.info(f"Confidence={confidence} — skipping (HIGH only)")
        return

    # ── Risk checks ──
    risk = RiskManager(state)
    ok, reason = risk.check_can_trade(groww)
    if not ok:
        logging.warning(f"BLOCKED: {reason}")
        return
    logging.info(f"Risk OK: {reason}")

    # ── Strike selection: ITM for better delta ──
    opt_type = "CE" if "CE" in signal else "PE"
    txn = groww.TRANSACTION_TYPE_BUY

    q = _get_nifty_quote(groww)
    if q is None:
        logging.error("Cannot get Nifty LTP")
        return
    nifty_ltp = float(q["last_price"])
    atm_strike = get_atm_strike(nifty_ltp)

    # Go ITM for better delta
    if opt_type == "CE":
        strike = atm_strike - ITM_OFFSET
    else:
        strike = atm_strike + ITM_OFFSET

    qty = LOT_SIZE * LOTS_TO_TRADE

    # ── Resolve symbol ──
    symbol, option_ltp_pre = get_valid_option_symbol(groww, strike, opt_type)
    if symbol is None:
        # Try ATM as fallback
        logging.warning(f"ITM {strike} failed, trying ATM {atm_strike}")
        symbol, option_ltp_pre = get_valid_option_symbol(groww, atm_strike, opt_type)
        if symbol is None:
            logging.error(f"Cannot resolve ANY symbol for {opt_type}")
            return
        strike = atm_strike

    logging.info(f"Resolved: {symbol} | LTP: Rs.{option_ltp_pre} | Nifty: {nifty_ltp} | Strike: {strike}")

    # ── Pre-trade checks ──
    spread_ok, spread_msg = risk.check_spread(groww, symbol)
    if not spread_ok:
        logging.warning(f"BLOCKED: {spread_msg}")
        return
    logging.info(spread_msg)

    prem_ok, prem_msg = risk.check_premium_range(option_ltp_pre)
    if not prem_ok:
        logging.warning(f"BLOCKED: {prem_msg}")
        return
    logging.info(prem_msg)

    cap_ok, cap_msg = risk.check_capital_exposure(option_ltp_pre, qty)
    if not cap_ok:
        logging.warning(f"BLOCKED: {cap_msg}")
        return
    logging.info(cap_msg)

    # ── Calculate SL and Target ──
    sl_price, target_price, risk_per_unit = risk.calc_sl_target(option_ltp_pre, orb, signal)
    total_risk = risk_per_unit * qty
    total_reward = (target_price - option_ltp_pre) * qty

    logging.info(f"PLAN | Entry:~Rs.{option_ltp_pre} | SL:Rs.{sl_price} | Target:Rs.{target_price}")
    logging.info(f"      Risk:Rs.{total_risk:.0f} | Reward:Rs.{total_reward:.0f} | RR:1:{total_reward/total_risk:.1f}" if total_risk > 0 else "")

    # ── PLACE ORDER ──
    oid, status = place_entry_order(groww, symbol, qty, txn)
    if not oid:
        logging.error("Entry FAILED")
        return

    time.sleep(1)
    entry_premium = get_option_ltp(groww, symbol) or option_ltp_pre

    # Recalculate with actual entry
    sl_price, target_price, risk_per_unit = risk.calc_sl_target(entry_premium, orb, signal)

    # ── Place OCO ──
    smart_id = place_oco_order(groww, symbol, qty, entry_premium, sl_price, target_price)

    # ── Save state ──
    state["trade_count"] += 1
    state["trades"].append({
        "signal": signal, "confidence": confidence,
        "symbol": symbol, "qty": qty,
        "entry_id": str(oid), "smart_id": str(smart_id) if smart_id else None,
        "entry_premium": entry_premium,
        "target": target_price, "sl": sl_price,
        "nifty_ltp": nifty_ltp, "strike": strike,
        "orb_high": orb["orb_high"], "orb_low": orb["orb_low"],
        "orb_range": orb["orb_range"],
        "trigger": d.get("trigger", "unknown"),
        "time": now.strftime("%Y-%m-%d %H:%M:%S")
    })
    save_state(state)

    logging.info(f"✅ TRADE DONE | {signal} {confidence} | {symbol}")
    logging.info(f"   Entry:Rs.{entry_premium} | SL:Rs.{sl_price} | Target:Rs.{target_price}")
    logging.info(f"   ORB:H={orb['orb_high']} L={orb['orb_low']} R={orb['orb_range']}")
    logging.info(f"   Order:{oid} | OCO:{smart_id}")

if __name__ == "__main__":
    main()
