# ============================================================
#  CRYPTO FIBONACCI v1.0 - BTC/USDT Perpetual Futures
#  Binance USDT-M Futures API
#
#  ARCHITECTURE:
#    - Session-based impulse detection (replaces market hours)
#    - WebSocket for live price monitoring
#    - Fibonacci retracement + extension (same core logic)
#
#  SESSION (HIGH-LIQUIDITY EU/US OVERLAP):
#    - 18:30 - 23:30 IST (13:00 - 18:00 UTC)
#
#  Uses the SAME fibonacci golden pocket strategy:
#    1. Identify session impulse (first 45 min of session)
#    2. Plot fib retracement levels
#    3. Enter on bounce from 38.2% - 61.8% zone
#    4. SL below 78.6% | Targets at -27.2% and -61.8% ext
# ============================================================

from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
import datetime
import logging
import json
import time
import os
import sys
import signal
import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

# =============================================================
#  SECTION 1 - CONFIGURATION
# =============================================================

API_KEY    = "loIzlExfyBbyQI6OaL5FRL90Gnw1jtczafGic2JgTfPomajYipfASLSrdqIE80n8"
API_SECRET = "asSDoyc8wIMyI0pw1dzlIKfqEDboJQVJ9yFqvaM8aZl0vIUTx2lbupdBPr4WOKde"

# -- Account / market --
USE_TESTNET  = True        # START on testnet. Flip to False only after validating.
SYMBOL       = "BTCUSDT"
LEVERAGE     = 10
CAPITAL_USDT = 200

# -- Files --
STATE_FILE  = "/root/crypto-scalper/state.json"
FIB_FILE    = "/root/crypto-scalper/fib_levels.json"
CANDLE_FILE = "/root/crypto-scalper/candles.json"
MONITOR_PID = "/root/crypto-scalper/monitor.pid"
LOG_FILE    = "/root/crypto-scalper/bot.log"
MONITOR_LOG = "/root/crypto-scalper/monitor.log"

# -- Risk --
RISK_PER_TRADE_PCT    = 2.0
MAX_RISK_USDT         = CAPITAL_USDT * RISK_PER_TRADE_PCT / 100
MAX_TRADES_SESSION    = 2
MAX_DAILY_LOSS_USDT   = 20
MAX_CONSECUTIVE_LOSSES = 2
MIN_RR_RATIO          = 2.0

# -- Fibonacci Settings --
IMPULSE_CANDLE_MIN    = 5
IMPULSE_WINDOW_MIN    = 45   # First 45 min of each session

# Fibonacci Levels (same as NIFTY bot)
FIB_236  = 0.236
FIB_382  = 0.382
FIB_500  = 0.500
FIB_618  = 0.618
FIB_786  = 0.786
FIB_EXT_1 = 0.272
FIB_EXT_2 = 0.618

FIB_ENTRY_UPPER = FIB_382
FIB_ENTRY_LOWER = FIB_618
FIB_SL_LEVEL    = FIB_786

# Impulse validation (BTC moves more than NIFTY)
MIN_IMPULSE_PCT   = 0.3     # 0.3% of BTC price minimum
MAX_IMPULSE_PCT   = 3.0     # 3% max (avoid exhaustion)
MIN_IMPULSE_USDT  = 150     # Absolute min in USD
MAX_IMPULSE_USDT  = 3000    # Absolute max

# Bounce confirmation
BOUNCE_MIN_BODY_PCT  = 0.35
BOUNCE_CONSEC        = 1
# How many of the most-recent candles to scan for the bounce. The retracement
# bounce often prints 1-3 candles before the scanner next runs, so checking only
# the latest candle misses valid setups ("No bounce confirmation").
BOUNCE_LOOKBACK      = 3

# -- SL/TP (ATR-based for crypto — percentage doesn't work well) --
SL_ATR_MULTIPLIER    = 1.5   # SL = 1.5x ATR
TP_RR_RATIO          = 2.0   # Target = SL x 2

# -- Hold & Exit --
MIN_HOLD_MINUTES      = 3     # Crypto moves faster
CATASTROPHIC_LOSS_PCT = 5.0   # 5% of position value
STAGNATION_EXIT_MIN   = 20    # No theta in futures, but opportunity cost
STAGNATION_MIN_PNL    = 0.3   # < 0.3x risk = stagnant

# -- Trailing SL --
TRAILING_SL_ENABLED  = False
TRAILING_SL_TRIGGER  = 0.50   # Start trailing at 50% of target
TRAILING_SL_STEP     = 0.50   # Lock 50% of profit

# -- Partial Profit --
PARTIAL_EXIT_ENABLED = False
PARTIAL_EXIT_PCT     = 50     # Exit 50% at first target
PARTIAL_TARGET_RR    = 1.0    # First target at 1:1

# -- Indicators (kept minimal: trend=EMA, momentum=RSI, volatility=ATR) --
ATR_LEN  = 14
RSI_LEN  = 14
EMA_FAST = 9
EMA_SLOW = 21

# -- Higher-timeframe (HTF) trend filter --
# Confirm the 5M entry agrees with the 1H trend before trading. This is a pure
# GATE: it can only BLOCK a trade that fights the 1H trend, never change the
# Fibonacci logic, sizing, SL or TP. If the 1H trend is undecided we allow the
# trade (we don't add a new way to miss setups).
HTF_TREND_ENABLED = False
HTF_INTERVAL      = "1h"
HTF_EMA_FAST      = 9
HTF_EMA_SLOW      = 21
HTF_FETCH_LIMIT   = 100    # 100 x 1H = ~4 days, plenty to seed EMA21

# -- Sessions (UTC) --
# Trade only the high-liquidity EU/US overlap: 13:00 - 18:00 UTC (18:30 - 23:30 IST).
# Avoids the low-liquidity 02:00 - 07:00 IST window entirely.
SESSIONS = {
    "PRIME": {"start_utc": (13, 0), "end_utc": (18, 0), "impulse_end_min": 45},
}

# Trade weekends? Crypto runs 24/7, but the EU/US overlap is far less liquid on
# Sat/Sun (TradFi desks closed). Set False to trade Monday-Friday only.
TRADE_WEEKENDS = False

# Skip US market holidays? Crypto never closes, but on US holidays the TradFi
# desks are shut, so the EU/US overlap is thin (same reasoning as weekends).
# Full-closure dates only — early-close half-days are NOT skipped.
# NOTE: hardcoded for 2026; update this set each year.
SKIP_US_HOLIDAYS = True
US_HOLIDAYS = {
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # Martin Luther King, Jr. Day
    "2026-02-16",  # Presidents' Day
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving Day
    "2026-12-25",  # Christmas Day
}

# -- Logging --
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)


# =============================================================
#  SECTION 2 - UTILITIES
# =============================================================

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

def ist_now():
    return utc_now() + datetime.timedelta(hours=5, minutes=30)

def get_current_session():
    """Determine which trading session we're in (UTC-based)."""
    now = utc_now()

    # Skip weekends unless explicitly enabled (Mon=0 .. Sun=6).
    if not TRADE_WEEKENDS and now.weekday() >= 5:
        return None, None

    # Skip US market holidays (thin TradFi liquidity in the EU/US overlap).
    if SKIP_US_HOLIDAYS and now.strftime("%Y-%m-%d") in US_HOLIDAYS:
        return None, None

    current_minutes = now.hour * 60 + now.minute

    for name, sess in SESSIONS.items():
        start_min = sess["start_utc"][0] * 60 + sess["start_utc"][1]
        end_min = sess["end_utc"][0] * 60 + sess["end_utc"][1]

        if start_min <= end_min:
            if start_min <= current_minutes < end_min:
                return name, sess
        else:  # crosses midnight
            if current_minutes >= start_min or current_minutes < end_min:
                return name, sess

    return None, None

def get_impulse_window(session):
    """Return (start_time, end_time) for impulse detection in current session."""
    now = utc_now()
    sh, sm = session["start_utc"]
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = start + datetime.timedelta(minutes=session["impulse_end_min"])
    return start, end

def load_state():
    today = utc_now().strftime("%Y-%m-%d")
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        if data.get("date") == today:
            return data
    except:
        pass
    return {"date": today, "trade_count": 0, "trades": [],
            "daily_pnl_usdt": 0.0, "sessions_traded": []}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def load_fib_levels():
    try:
        with open(FIB_FILE) as f:
            data = json.load(f)
        # Check if same session
        session_name, _ = get_current_session()
        if data.get("session") == session_name and data.get("date") == utc_now().strftime("%Y-%m-%d"):
            return data
    except:
        pass
    return None

def save_fib_levels(data):
    with open(FIB_FILE, "w") as f:
        json.dump(data, f, indent=2)


# =============================================================
#  SECTION 3 - BINANCE CLIENT
# =============================================================

def get_client():
    """Initialize Binance Futures client."""
    if USE_TESTNET:
        client = UMFutures(
            key=API_KEY,
            secret=API_SECRET,
            base_url="https://testnet.binancefuture.com"
        )
        logging.info("Binance client: TESTNET")
    else:
        client = UMFutures(key=API_KEY, secret=API_SECRET)
        logging.info("Binance client: LIVE")
    return client

def setup_leverage(client):
    """Set leverage and margin type."""
    try:
        client.change_leverage(symbol=SYMBOL, leverage=LEVERAGE)
        logging.info("Leverage set: %dx" % LEVERAGE)
    except Exception as e:
        if "No need to change" not in str(e):
            logging.warning("Leverage error: %s" % str(e))

    try:
        client.change_margin_type(symbol=SYMBOL, marginType="ISOLATED")
        logging.info("Margin type: ISOLATED")
    except Exception as e:
        if "No need to change" not in str(e):
            logging.warning("Margin type error: %s" % str(e))

def get_symbol_info(client):
    """Get tick size, lot size, min notional for the symbol."""
    info = client.exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == SYMBOL:
            tick_size = None
            step_size = None
            min_notional = None
            for f in s["filters"]:
                if f["filterType"] == "PRICE_FILTER":
                    tick_size = float(f["tickSize"])
                elif f["filterType"] == "LOT_SIZE":
                    step_size = float(f["stepSize"])
                elif f["filterType"] == "MIN_NOTIONAL":
                    min_notional = float(f.get("notional", 5))
            return {
                "tick_size": tick_size or 0.10,
                "step_size": step_size or 0.001,
                "min_notional": min_notional or 5.0,
                "price_precision": s.get("pricePrecision", 2),
                "qty_precision": s.get("quantityPrecision", 3),
            }
    return None

def round_price(price, tick_size):
    """Snap price to the nearest valid tick using Decimal (no float artefacts)."""
    tick = Decimal(str(tick_size))
    steps = (Decimal(str(price)) / tick).to_integral_value(rounding=ROUND_HALF_UP)
    return float(steps * tick)

def round_qty(qty, step_size):
    """Floor quantity to a valid step using Decimal (no float artefacts)."""
    step = Decimal(str(step_size))
    steps = (Decimal(str(qty)) / step).to_integral_value(rounding=ROUND_DOWN)
    return float(steps * step)

def get_btc_price(client):
    """Get current BTC price."""
    ticker = client.ticker_price(symbol=SYMBOL)
    return float(ticker["price"])

def get_balance(client):
    """Get available USDT balance in futures wallet."""
    account = client.account()
    for asset in account.get("assets", []):
        if asset["asset"] == "USDT":
            return float(asset["availableBalance"])
    return 0.0


# =============================================================
#  SECTION 4 - FETCH CANDLES
# =============================================================

def fetch_candles(client, interval="5m", limit=200):
    """Fetch 5-minute klines from Binance."""
    try:
        raw = client.klines(symbol=SYMBOL, interval=interval, limit=limit)
        candles = []
        for k in raw:
            # Binance kline: [open_time, open, high, low, close, volume,
            #                  close_time, quote_vol, trades, taker_buy_vol,
            #                  taker_buy_quote, ignore]
            open_time_ms = k[0]
            dt = datetime.datetime.fromtimestamp(open_time_ms / 1000, datetime.timezone.utc).replace(tzinfo=None)
            candles.append({
                "ts": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            })
        logging.info("Fetched %d candles" % len(candles))
        return candles
    except Exception as e:
        logging.error("Candle fetch failed: %s" % str(e))
        return []


# =============================================================
#  SECTION 5 - INDICATORS (same as NIFTY bot)
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
            pdi_list.append(None); mdi_list.append(None); dx.append(None)
        else:
            p = 100 * ps / ts; m = 100 * ms / ts
            pdi_list.append(p); mdi_list.append(m)
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


def compute_htf_trend(htf_candles):
    """Determine the higher-timeframe trend from a list of HTF candle dicts
    (each with open/high/low/close). Returns (trend, ema_fast, ema_slow) where
    trend is 'BULL', 'BEAR', or None when undecided / insufficient data."""
    closes = [c["close"] for c in htf_candles]
    if len(closes) < HTF_EMA_SLOW + 1:
        return None, None, None
    ef = safe(ema(closes, HTF_EMA_FAST))
    es = safe(ema(closes, HTF_EMA_SLOW))
    if ef is None or es is None:
        return None, None, None
    if ef > es:
        return "BULL", ef, es
    if ef < es:
        return "BEAR", ef, es
    return None, ef, es


def resample_to_htf(candles, hours=1):
    """Aggregate chronologically-sorted 5m candle dicts into higher-timeframe
    candles grouped by clock-hour boundary. Used by the backtester so the HTF
    trend is derived from the same 5m history (no extra API calls)."""
    buckets = {}
    order = []
    for c in candles:
        try:
            dt = datetime.datetime.strptime(c["ts"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            continue
        bucket_hour = dt.hour - (dt.hour % hours)
        key = (dt.year, dt.month, dt.day, bucket_hour)
        if key not in buckets:
            buckets[key] = {
                "open": c["open"], "high": c["high"],
                "low": c["low"], "close": c["close"],
                "volume": c.get("volume", 0),
            }
            order.append(key)
        else:
            b = buckets[key]
            b["high"] = max(b["high"], c["high"])
            b["low"] = min(b["low"], c["low"])
            b["close"] = c["close"]
            b["volume"] += c.get("volume", 0)
    return [buckets[k] for k in order]


# =============================================================
#  SECTION 6 - FIBONACCI ENGINE (adapted for crypto sessions)
# =============================================================

def compute_impulse_and_fibs(candles, session_name, session):
    """
    Identify impulse move in first 45 min of current session.
    Same logic as NIFTY bot but session-based instead of 9:15-9:45.
    """
    impulse_start, impulse_end = get_impulse_window(session)
    impulse_candles = []
    pre_session_close = None

    for c in candles:
        try:
            dt = datetime.datetime.strptime(c["ts"], "%Y-%m-%d %H:%M:%S")
        except:
            continue

        if dt < impulse_start:
            pre_session_close = c["close"]
            continue

        if impulse_start <= dt < impulse_end:
            impulse_candles.append(c)

    return _fibs_from_impulse(impulse_candles, pre_session_close, session_name)


def _fibs_from_impulse(impulse_candles, pre_session_close, session_name):
    """
    Pure fib computation: given the impulse candles and the reference close,
    validate the impulse and build retracement + extension levels.
    Shared by the live scanner and the backtester so both stay in sync.
    """
    if len(impulse_candles) < 3:
        return None

    impulse_high = max(c["high"] for c in impulse_candles)
    impulse_low = min(c["low"] for c in impulse_candles)
    impulse_open = impulse_candles[0]["open"]
    impulse_close = impulse_candles[-1]["close"]
    impulse_range = impulse_high - impulse_low

    # Direction
    if impulse_close > impulse_open:
        direction = "BULL"
    elif impulse_close < impulse_open:
        direction = "BEAR"
    else:
        return None

    swing_low = impulse_low
    swing_high = impulse_high

    # Validate impulse size
    ref_price = pre_session_close or impulse_open
    if ref_price > 0:
        impulse_pct = impulse_range / ref_price * 100
        if impulse_pct < MIN_IMPULSE_PCT or impulse_pct > MAX_IMPULSE_PCT:
            logging.info("Impulse rejected: %.2f%% (need %.1f-%.1f%%)" % (
                impulse_pct, MIN_IMPULSE_PCT, MAX_IMPULSE_PCT))
            return None

    if impulse_range < MIN_IMPULSE_USDT or impulse_range > MAX_IMPULSE_USDT:
        logging.info("Impulse rejected: $%.0f range (need $%d-$%d)" % (
            impulse_range, MIN_IMPULSE_USDT, MAX_IMPULSE_USDT))
        return None

    diff = swing_high - swing_low

    if direction == "BULL":
        fibs = {
            "fib_0":   round(swing_high, 2),
            "fib_236": round(swing_high - diff * FIB_236, 2),
            "fib_382": round(swing_high - diff * FIB_382, 2),
            "fib_500": round(swing_high - diff * FIB_500, 2),
            "fib_618": round(swing_high - diff * FIB_618, 2),
            "fib_786": round(swing_high - diff * FIB_786, 2),
            "fib_100": round(swing_low, 2),
            "ext_272": round(swing_high + diff * FIB_EXT_1, 2),
            "ext_618": round(swing_high + diff * FIB_EXT_2, 2),
        }
        entry_upper = fibs["fib_382"]
        entry_lower = fibs["fib_618"]
        sl_level = fibs["fib_786"]
        tp1 = fibs["ext_272"]
        tp2 = fibs["ext_618"]
    else:
        fibs = {
            "fib_0":   round(swing_low, 2),
            "fib_236": round(swing_low + diff * FIB_236, 2),
            "fib_382": round(swing_low + diff * FIB_382, 2),
            "fib_500": round(swing_low + diff * FIB_500, 2),
            "fib_618": round(swing_low + diff * FIB_618, 2),
            "fib_786": round(swing_low + diff * FIB_786, 2),
            "fib_100": round(swing_high, 2),
            "ext_272": round(swing_low - diff * FIB_EXT_1, 2),
            "ext_618": round(swing_low - diff * FIB_EXT_2, 2),
        }
        entry_upper = fibs["fib_618"]
        entry_lower = fibs["fib_382"]
        sl_level = fibs["fib_786"]
        tp1 = fibs["ext_272"]
        tp2 = fibs["ext_618"]

    return {
        "date": utc_now().strftime("%Y-%m-%d"),
        "session": session_name,
        "direction": direction,
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
        "impulse_range": round(impulse_range, 2),
        "fibs": fibs,
        "entry_zone_upper": round(entry_upper, 2),
        "entry_zone_lower": round(entry_lower, 2),
        "fib_sl": round(sl_level, 2),
        "fib_tp1": round(tp1, 2),
        "fib_tp2": round(tp2, 2),
        "computed_at": utc_now().strftime("%H:%M:%S"),
    }


def _detect_bounce(candle, direction):
    """Return a bounce label (str) if this single candle confirms a fib-zone
    bounce in `direction`, else None. Factored out so the scanner can look back
    over several recent candles instead of only the latest one."""
    o = candle["open"]
    c = candle["close"]
    h = candle["high"]
    l = candle["low"]
    rng = h - l
    if rng <= 0:
        return None

    if direction == "BULL":
        body = c - o
        if c > o:
            if body / rng >= BOUNCE_MIN_BODY_PCT:
                return "BULLISH"
            lower_wick = o - l
            if lower_wick > body * 2:
                return "HAMMER"
    else:
        body = o - c
        if c < o:
            if body / rng >= BOUNCE_MIN_BODY_PCT:
                return "BEARISH"
            upper_wick = h - o
            if upper_wick > body * 2:
                return "SHOOTING_STAR"
    return None


def check_fib_signal(candles, fib_data):
    """
    Check for fibonacci retracement bounce signal.
    Same logic as NIFTY bot's check_fib_retracement().
    """
    if not fib_data or not candles:
        return {"signal": "NO_TRADE", "details": {"reason": "No data"}}

    direction = fib_data["direction"]
    entry_upper = fib_data["entry_zone_upper"]
    entry_lower = fib_data["entry_zone_lower"]
    fib_sl = fib_data["fib_sl"]
    fibs = fib_data["fibs"]

    details = {
        "direction": direction,
        "entry_zone": "%.1f - %.1f" % (entry_lower, entry_upper),
        "fib_sl": fib_sl,
    }

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

    # Indicators (minimal: RSI momentum, ATR volatility, EMA trend)
    rsi_s = calc_rsi(closes, RSI_LEN)
    rsi = safe(rsi_s)
    atr_s = calc_atr(highs, lows, closes, ATR_LEN)
    atr = safe(atr_s)
    ema_f = ema(closes, EMA_FAST)
    ema_s_arr = ema(closes, EMA_SLOW)
    ef = safe(ema_f)
    es = safe(ema_s_arr)

    details.update({
        "rsi": round(rsi, 1) if rsi else "N/A",
        "atr": round(atr, 1) if atr else "N/A",
    })

    # Zone check
    if direction == "BULL":
        in_zone = entry_lower <= last_low <= entry_upper or entry_lower <= last_close <= entry_upper
        touched_zone = last_low <= entry_upper
        if last_close < fib_sl:
            details["reason"] = "Fib invalidated"
            return {"signal": "NO_TRADE", "details": details}
    else:
        in_zone = entry_lower <= last_high <= entry_upper or entry_lower <= last_close <= entry_upper
        touched_zone = last_high >= entry_lower
        if last_close > fib_sl:
            details["reason"] = "Fib invalidated"
            return {"signal": "NO_TRADE", "details": details}

    if not touched_zone:
        # Check recent candles
        zone_touched = False
        for i in range(-6, 0):
            try:
                if direction == "BULL" and lows[i] <= entry_upper:
                    zone_touched = True; break
                elif direction == "BEAR" and highs[i] >= entry_lower:
                    zone_touched = True; break
            except IndexError:
                pass
        if not zone_touched:
            details["reason"] = "Waiting for retracement"
            return {"signal": "NO_TRADE", "details": details}

    # Bounce confirmation — scan the last BOUNCE_LOOKBACK candles (newest first),
    # not just candles[-1]. The retracement bounce frequently prints 1-3 candles
    # before the scanner runs again; only inspecting the latest candle returned
    # "No bounce confirmation" even though a valid bounce had already occurred.
    # This matches the multi-candle zone-touch window used above.
    bounce_confirmed = False
    lookback = min(BOUNCE_LOOKBACK, len(candles))
    for age in range(lookback):
        bounce_type = _detect_bounce(candles[-1 - age], direction)
        if bounce_type:
            bounce_confirmed = True
            details["bounce_type"] = bounce_type
            details["bounce_age"] = age  # 0 = latest candle, 1 = one candle ago, ...
            break

    if not bounce_confirmed:
        details["reason"] = "No bounce confirmation"
        return {"signal": "NO_TRADE", "details": details}

    # Simple confluence: the fib-zone bounce is the trigger; we require just
    # one confirmation — EMA trend alignment with the impulse direction.
    trend_aligned = bool(ef and es and (
        (direction == "BULL" and ef > es) or (direction == "BEAR" and ef < es)))
    details["trend_aligned"] = trend_aligned
    details["score"] = "trend+bounce" if trend_aligned else "bounce-only"

    if not trend_aligned:
        details["reason"] = "Trend not aligned (EMA%d vs EMA%d)" % (EMA_FAST, EMA_SLOW)
        return {"signal": "NO_TRADE", "details": details}

    # RSI extremes guard (avoid chasing exhausted moves)
    if direction == "BULL" and rsi and rsi > 78:
        details["reason"] = "RSI overbought"
        return {"signal": "NO_TRADE", "details": details}
    if direction == "BEAR" and rsi and rsi < 22:
        details["reason"] = "RSI oversold"
        return {"signal": "NO_TRADE", "details": details}

    # ATR for SL calculation
    details["atr_sl"] = round(atr * SL_ATR_MULTIPLIER, 2) if atr else "N/A"

    # Healthy momentum band -> HIGH confidence, otherwise MED.
    rsi_healthy = rsi is None or (30 < rsi < 70)
    confidence = "HIGH" if rsi_healthy else "MED"
    signal_type = "LONG" if direction == "BULL" else "SHORT"

    return {
        "signal": signal_type,
        "confidence": confidence,
        "direction": direction,
        "details": details,
        "atr": atr,
    }


# =============================================================
#  SECTION 7 - POSITION SIZING & RISK
# =============================================================

def calculate_position(client, btc_price, atr, fib_data, sym_info):
    """Calculate position size, SL, TP based on risk."""
    direction = fib_data["direction"]

    # ATR-based SL
    sl_distance = atr * SL_ATR_MULTIPLIER

    # Also consider fib-based SL
    if direction == "BULL":
        fib_sl_dist = btc_price - fib_data["fib_sl"]
    else:
        fib_sl_dist = fib_data["fib_sl"] - btc_price

    # Use the tighter of ATR and fib SL (but not too tight)
    sl_distance = min(sl_distance, fib_sl_dist) if fib_sl_dist > 0 else sl_distance
    sl_distance = max(sl_distance, atr * 0.8)  # Floor at 0.8x ATR

    # TP
    tp_distance = sl_distance * TP_RR_RATIO

    # Position size based on risk
    # Risk = qty * sl_distance <= MAX_RISK_USDT
    qty_from_risk = MAX_RISK_USDT / sl_distance
    # Also cap by leverage
    max_notional = CAPITAL_USDT * LEVERAGE
    qty_from_capital = max_notional / btc_price
    qty = min(qty_from_risk, qty_from_capital)

    # Round to valid step
    qty = round_qty(qty, sym_info["step_size"])

    # Check min notional
    if qty * btc_price < sym_info["min_notional"]:
        logging.warning("Position too small: $%.2f < min $%.2f" % (
            qty * btc_price, sym_info["min_notional"]))
        return None

    # SL and TP prices
    if direction == "BULL":
        sl_price = round_price(btc_price - sl_distance, sym_info["tick_size"])
        tp_price = round_price(btc_price + tp_distance, sym_info["tick_size"])
    else:
        sl_price = round_price(btc_price + sl_distance, sym_info["tick_size"])
        tp_price = round_price(btc_price - tp_distance, sym_info["tick_size"])

    rr = tp_distance / sl_distance if sl_distance > 0 else 0

    return {
        "qty": qty,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "sl_distance": round(sl_distance, 2),
        "tp_distance": round(tp_distance, 2),
        "risk_usdt": round(qty * sl_distance, 2),
        "reward_usdt": round(qty * tp_distance, 2),
        "rr": round(rr, 2),
        "notional": round(qty * btc_price, 2),
        "leverage_used": round(qty * btc_price / CAPITAL_USDT, 1),
    }


# =============================================================
#  SECTION 8 - ORDER EXECUTION
# =============================================================

def place_entry(client, direction, qty, sym_info):
    """Place market entry order."""
    side = "BUY" if direction == "BULL" else "SELL"
    if USE_TESTNET:
        logging.info("TESTNET ENTRY: %s %s %s" % (side, qty, SYMBOL))

    try:
        order = client.new_order(
            symbol=SYMBOL,
            side=side,
            type="MARKET",
            quantity=qty,
        )
        oid = order.get("orderId", "N/A")
        logging.info("ENTRY: %s | Side:%s | Qty:%s | ID:%s" % (SYMBOL, side, qty, oid))
        return oid, order
    except Exception as e:
        logging.error("ENTRY FAILED: %s" % str(e))
        return None, None

def place_exit(client, direction, qty, reason):
    """Place market exit order."""
    side = "SELL" if direction == "BULL" else "BUY"  # opposite side to close
    try:
        order = client.new_order(
            symbol=SYMBOL,
            side=side,
            type="MARKET",
            quantity=qty,
            reduceOnly="true",
        )
        logging.info("EXIT: %s | Qty:%s | %s" % (SYMBOL, qty, reason))
        return True
    except Exception as e:
        logging.error("EXIT FAILED: %s" % str(e))
        return False

def _place_stop(client, close_side, otype, stop_price, qty):
    """Place one stop order, trying closePosition first then reduceOnly+qty.
    Returns True on success. Raises the last error if every method fails."""
    # Method A: closePosition (whole-position stop) — works on LIVE futures.
    try:
        client.new_order(
            symbol=SYMBOL, side=close_side, type=otype,
            stopPrice=str(stop_price), closePosition="true",
            workingType="MARK_PRICE",
        )
        return True
    except Exception as e_a:
        last = e_a
    # Method B: reduceOnly with explicit quantity.
    try:
        client.new_order(
            symbol=SYMBOL, side=close_side, type=otype,
            stopPrice=str(stop_price), quantity=qty,
            reduceOnly="true", workingType="MARK_PRICE",
        )
        return True
    except Exception as e_b:
        last = e_b
    raise last

def place_sl_tp_orders(client, direction, qty, sl_price, tp_price):
    """Place stop-loss and take-profit on the exchange as a SAFETY NET.

    This is a backup only — the WebSocket monitor (run_monitor) is the
    primary exit manager. Some testnet endpoints reject STOP_MARKET /
    TAKE_PROFIT_MARKET with error -4120 ("use the Algo Order API"); in that
    case we log a warning and rely on the software monitor instead of
    treating it as a fatal error.
    """
    close_side = "SELL" if direction == "BULL" else "BUY"
    sl_ok = tp_ok = False
    try:
        _place_stop(client, close_side, "STOP_MARKET", sl_price, qty)
        logging.info("SL order placed: %s at $%s" % (close_side, sl_price))
        sl_ok = True
    except Exception as e:
        logging.warning("Exchange SL not placed (%s) — software monitor will manage SL" % str(e))
    try:
        _place_stop(client, close_side, "TAKE_PROFIT_MARKET", tp_price, qty)
        logging.info("TP order placed: %s at $%s" % (close_side, tp_price))
        tp_ok = True
    except Exception as e:
        logging.warning("Exchange TP not placed (%s) — software monitor will manage TP" % str(e))

    if not (sl_ok or tp_ok):
        logging.warning("No exchange-side SL/TP active. Exits depend ENTIRELY on the "
                        "monitor process — ensure it stays running.")
    return sl_ok and tp_ok

def cancel_open_orders(client):
    """Cancel all open orders for the symbol."""
    try:
        client.cancel_open_orders(symbol=SYMBOL)
        logging.info("Cancelled all open orders for %s" % SYMBOL)
    except Exception as e:
        if "No open orders" not in str(e):
            logging.warning("Cancel orders error: %s" % str(e))


# =============================================================
#  SECTION 9 - WEBSOCKET MONITOR
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

def run_monitor(client, state):
    """WebSocket-based trade monitor with trailing SL, partial profit."""
    trades = state.get("trades", [])
    if not trades:
        return
    trade = trades[-1]
    if trade.get("exited"):
        return

    direction = trade["direction"]
    qty = trade["qty"]
    remaining_qty = trade.get("remaining_qty", qty)
    entry_price = trade["entry_price"]
    entry_time = datetime.datetime.strptime(trade["time"], "%Y-%m-%d %H:%M:%S")
    sl_distance = trade["sl_distance"]
    tp_distance = trade["tp_distance"]
    sl_price = trade["sl_price"]
    tp_price = trade["tp_price"]

    partial_target_dist = sl_distance * PARTIAL_TARGET_RR
    partial_qty = round_qty(remaining_qty * PARTIAL_EXIT_PCT / 100, trade.get("step_size", 0.001))
    if partial_qty <= 0 or partial_qty >= remaining_qty:
        partial_qty = 0

    catastrophic_pct = CATASTROPHIC_LOSS_PCT / 100 * entry_price

    logging.info("=== CRYPTO MONITOR START ===")
    logging.info("  %s %s | Entry:$%.2f | Qty:%s" % (direction, SYMBOL, entry_price, remaining_qty))
    logging.info("  SL:$%.2f | TP:$%.2f | Risk:$%.2f" % (sl_price, tp_price, sl_distance * remaining_qty))

    write_monitor_pid()

    mon = {
        "exited": False,
        "last_log": time.time(),
        "trailing_sl": sl_price,
        "best_price": entry_price,
        "remaining_qty": remaining_qty,
        "partial_done": trade.get("partial_done", False),
    }

    def on_message(_, msg):
        if mon["exited"]:
            return
        try:
            data = json.loads(msg) if isinstance(msg, str) else msg
            if data.get("e") != "markPriceUpdate":
                return
            price = float(data["p"])
        except:
            return

        r_qty = mon["remaining_qty"]
        now = time.time()

        # Logging
        if now - mon["last_log"] >= 30:
            if direction == "BULL":
                pnl = (price - entry_price) * r_qty
            else:
                pnl = (entry_price - price) * r_qty
            logging.info("  TICK $%.2f | P&L:$%+.2f | SL:$%.2f | Qty:%s" % (
                price, pnl, mon["trailing_sl"], r_qty))
            mon["last_log"] = now

        minutes_held = (utc_now() - entry_time).total_seconds() / 60

        # --- EXIT LOGIC ---
        if direction == "BULL":
            unrealized = price - entry_price
            profit_for_trail = price - entry_price

            # Catastrophic
            if minutes_held < MIN_HOLD_MINUTES and price <= entry_price - catastrophic_pct:
                pnl = unrealized * r_qty
                _exit(price, pnl, "CATASTROPHIC SL", r_qty)
                return

            # Partial
            if (PARTIAL_EXIT_ENABLED and not mon["partial_done"]
                    and partial_qty > 0 and price >= entry_price + partial_target_dist):
                pnl_p = (price - entry_price) * partial_qty
                place_exit(client, direction, partial_qty, "PARTIAL $%+.2f" % pnl_p)
                mon["partial_done"] = True
                mon["remaining_qty"] -= partial_qty
                mon["trailing_sl"] = max(mon["trailing_sl"], entry_price)
                trade["partial_done"] = True
                trade["partial_pnl"] = round(pnl_p, 2)
                trade["remaining_qty"] = mon["remaining_qty"]
                state["daily_pnl_usdt"] = state.get("daily_pnl_usdt", 0) + pnl_p
                save_state(state)
                return

            # TP
            if price >= tp_price:
                pnl = unrealized * r_qty
                _exit(price, pnl, "TAKE PROFIT", r_qty)
                return

            # After hold period
            if minutes_held >= MIN_HOLD_MINUTES:
                # Trailing SL
                if TRAILING_SL_ENABLED and price > mon["best_price"]:
                    mon["best_price"] = price
                    if profit_for_trail >= tp_distance * TRAILING_SL_TRIGGER:
                        new_sl = round(entry_price + profit_for_trail * TRAILING_SL_STEP, 2)
                        if new_sl > mon["trailing_sl"]:
                            mon["trailing_sl"] = new_sl

                # Stagnation
                if minutes_held >= STAGNATION_EXIT_MIN and unrealized < sl_distance * STAGNATION_MIN_PNL:
                    pnl = unrealized * r_qty
                    _exit(price, pnl, "STAGNATION", r_qty)
                    return

                # SL hit
                if price <= mon["trailing_sl"]:
                    pnl = unrealized * r_qty
                    _exit(price, pnl, "STOP LOSS", r_qty)
                    return

        else:  # SHORT
            unrealized = entry_price - price
            profit_for_trail = entry_price - price

            if minutes_held < MIN_HOLD_MINUTES and price >= entry_price + catastrophic_pct:
                pnl = unrealized * r_qty
                _exit(price, pnl, "CATASTROPHIC SL", r_qty)
                return

            if (PARTIAL_EXIT_ENABLED and not mon["partial_done"]
                    and partial_qty > 0 and price <= entry_price - partial_target_dist):
                pnl_p = (entry_price - price) * partial_qty
                place_exit(client, direction, partial_qty, "PARTIAL $%+.2f" % pnl_p)
                mon["partial_done"] = True
                mon["remaining_qty"] -= partial_qty
                mon["trailing_sl"] = min(mon["trailing_sl"], entry_price)
                trade["partial_done"] = True
                trade["partial_pnl"] = round(pnl_p, 2)
                trade["remaining_qty"] = mon["remaining_qty"]
                state["daily_pnl_usdt"] = state.get("daily_pnl_usdt", 0) + pnl_p
                save_state(state)
                return

            if price <= tp_price:
                pnl = unrealized * r_qty
                _exit(price, pnl, "TAKE PROFIT", r_qty)
                return

            if minutes_held >= MIN_HOLD_MINUTES:
                if TRAILING_SL_ENABLED and price < mon["best_price"]:
                    mon["best_price"] = price
                    if profit_for_trail >= tp_distance * TRAILING_SL_TRIGGER:
                        new_sl = round(entry_price - profit_for_trail * TRAILING_SL_STEP, 2)
                        if new_sl < mon["trailing_sl"]:
                            mon["trailing_sl"] = new_sl

                if minutes_held >= STAGNATION_EXIT_MIN and unrealized < sl_distance * STAGNATION_MIN_PNL:
                    pnl = unrealized * r_qty
                    _exit(price, pnl, "STAGNATION", r_qty)
                    return

                if price >= mon["trailing_sl"]:
                    pnl = unrealized * r_qty
                    _exit(price, pnl, "STOP LOSS", r_qty)
                    return

    def _exit(price, pnl, reason, exit_qty):
        if mon["exited"]:
            return
        mon["exited"] = True

        logging.info("=== EXIT: %s ===" % reason)
        logging.info("  Price:$%.2f | P&L:$%+.2f | Qty:%s" % (price, pnl, exit_qty))

        cancel_open_orders(client)
        place_exit(client, direction, exit_qty, reason)

        trade["exited"] = True
        trade["exit_price"] = round(price, 2)
        trade["exit_pnl"] = round(pnl + trade.get("partial_pnl", 0), 2)
        trade["exit_reason"] = reason
        trade["exit_time"] = utc_now().strftime("%Y-%m-%d %H:%M:%S")
        state["daily_pnl_usdt"] = state.get("daily_pnl_usdt", 0) + pnl
        save_state(state)
        clear_monitor_pid()
        logging.info("  Daily P&L: $%+.2f" % state["daily_pnl_usdt"])

    # Use mark price stream for monitoring
    base_url = "wss://fstream.binance.com" if not USE_TESTNET else "wss://stream.binancefuture.com"

    ws_client = UMFuturesWebsocketClient(
        stream_url=base_url,
        on_message=on_message,
    )
    ws_client.mark_price(symbol=SYMBOL.lower(), speed=1)
    logging.info("WebSocket connected — monitoring %s" % SYMBOL)

    def handle_shutdown(signum, frame):
        if not mon["exited"]:
            logging.info("Shutdown signal — exiting position")
            price = get_btc_price(client)
            if direction == "BULL":
                pnl = (price - entry_price) * mon["remaining_qty"]
            else:
                pnl = (entry_price - price) * mon["remaining_qty"]
            _exit(price, pnl, "SHUTDOWN", mon["remaining_qty"])
        ws_client.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        while not mon["exited"]:
            time.sleep(1)
    except KeyboardInterrupt:
        handle_shutdown(None, None)
    finally:
        ws_client.stop()
        clear_monitor_pid()


# =============================================================
#  SECTION 9b - BACKTEST HARNESS
# =============================================================
#  Validate the strategy on historical 5m candles BEFORE risking
#  money. Reuses the live signal/sizing functions so what you test
#  is what you trade.
#
#  Caveats (read these before trusting the numbers):
#   - Intrabar order is unknown: within one candle we cannot tell if
#     the high or the low came first. To avoid optimistic bias we check
#     the stop-loss BEFORE the take-profit on each candle.
#   - No funding fees / exchange slippage are modelled beyond a flat
#     per-side cost. Live results will be worse than backtest.
#   - Past performance does NOT guarantee future results.
# =============================================================

BACKTEST_FEE_PCT = 0.05   # round-trip cost estimate per trade (% of notional)


def _parse_ts(s):
    return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def fetch_history(client, interval="5m", days=5):
    """Fetch up to `days` of klines (paginated; Binance caps 1500/call)."""
    limit = 1500
    target = days * 24 * 12  # 288 five-minute candles per day
    end_time = None
    collected = {}
    while len(collected) < target:
        params = {"symbol": SYMBOL, "interval": interval, "limit": limit}
        if end_time is not None:
            params["endTime"] = end_time
        try:
            raw = client.klines(**params)
        except Exception as e:
            logging.error("History fetch failed: %s" % str(e))
            break
        if not raw:
            break
        for k in raw:
            collected[k[0]] = k
        end_time = raw[0][0] - 1
        if len(raw) < limit:
            break

    candles = []
    for t in sorted(collected):
        k = collected[t]
        dt = datetime.datetime.fromtimestamp(k[0] / 1000, datetime.timezone.utc).replace(tzinfo=None)
        candles.append({
            "ts": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]),
            "volume": float(k[5]),
        })
    return candles


def _simulate_trade(direction, entry_price, atr, fib_data, sym_info, forward):
    """Walk forward candle-by-candle and return realized P&L (USDT) for one trade.
    Mirrors run_monitor's exit logic (catastrophic, partial, TP, trailing, stagnation).
    Conservative: checks adverse moves before favourable ones within a candle."""
    pos = calculate_position(None, entry_price, atr, fib_data, sym_info)
    if pos is None or pos["rr"] < MIN_RR_RATIO:
        return None

    qty = pos["qty"]
    sl_dist = pos["sl_distance"]
    tp_dist = pos["tp_distance"]
    sl_price = pos["sl_price"]
    tp_price = pos["tp_price"]

    catastrophic = CATASTROPHIC_LOSS_PCT / 100 * entry_price
    partial_target_dist = sl_dist * PARTIAL_TARGET_RR
    partial_qty = round_qty(qty * PARTIAL_EXIT_PCT / 100, sym_info["step_size"])
    if partial_qty <= 0 or partial_qty >= qty:
        partial_qty = 0

    remaining = qty
    trailing = sl_price
    best = entry_price
    partial_done = False
    realized = 0.0
    exit_reason = "SESSION_END"

    def sign(p):
        return (p - entry_price) if direction == "BULL" else (entry_price - p)

    for i, c in enumerate(forward):
        minutes_held = (i + 1) * IMPULSE_CANDLE_MIN
        hi, lo, close = c["high"], c["low"], c["close"]
        adverse = lo if direction == "BULL" else hi
        favour = hi if direction == "BULL" else lo

        # 1) Catastrophic stop during the no-touch hold window
        if minutes_held < MIN_HOLD_MINUTES:
            hit = (adverse <= entry_price - catastrophic) if direction == "BULL" \
                else (adverse >= entry_price + catastrophic)
            if hit:
                cat_price = entry_price - catastrophic if direction == "BULL" else entry_price + catastrophic
                realized += sign(cat_price) * remaining
                exit_reason = "CATASTROPHIC"
                break

        # 2) Stop-loss / trailing-stop (checked first = conservative)
        if minutes_held >= MIN_HOLD_MINUTES:
            sl_hit = (adverse <= trailing) if direction == "BULL" else (adverse >= trailing)
            if sl_hit:
                realized += sign(trailing) * remaining
                exit_reason = "STOP_LOSS" if trailing == sl_price else "TRAIL_STOP"
                break

        # 3) Partial profit
        if PARTIAL_EXIT_ENABLED and not partial_done and partial_qty > 0:
            p_hit = (favour >= entry_price + partial_target_dist) if direction == "BULL" \
                else (favour <= entry_price - partial_target_dist)
            if p_hit:
                realized += partial_target_dist * partial_qty
                remaining -= partial_qty
                partial_done = True
                trailing = entry_price  # move to break-even

        # 4) Take profit
        tp_hit = (favour >= tp_price) if direction == "BULL" else (favour <= tp_price)
        if tp_hit:
            realized += sign(tp_price) * remaining
            exit_reason = "TAKE_PROFIT"
            break

        # 5) Trailing-stop ratchet (uses the extreme of this candle)
        if minutes_held >= MIN_HOLD_MINUTES and TRAILING_SL_ENABLED:
            improved = favour > best if direction == "BULL" else favour < best
            if improved:
                best = favour
                open_profit = abs(best - entry_price)
                if open_profit >= tp_dist * TRAILING_SL_TRIGGER:
                    if direction == "BULL":
                        new_sl = entry_price + open_profit * TRAILING_SL_STEP
                        trailing = max(trailing, new_sl)
                    else:
                        new_sl = entry_price - open_profit * TRAILING_SL_STEP
                        trailing = min(trailing, new_sl)

        # 6) Stagnation exit
        if minutes_held >= STAGNATION_EXIT_MIN and sign(close) < sl_dist * STAGNATION_MIN_PNL:
            realized += sign(close) * remaining
            exit_reason = "STAGNATION"
            break
    else:
        # Ran out of session candles — close at last close
        realized += sign(forward[-1]["close"]) * remaining

    fee = BACKTEST_FEE_PCT / 100 * entry_price * qty
    net = realized - fee
    return {"pnl": net, "gross": realized, "fee": fee, "reason": exit_reason, "qty": qty}


def run_backtest(days=5):
    """Backtest the PRIME-session fib strategy over the last `days` days."""
    client = get_client()
    sym_info = get_symbol_info(client) or {
        "tick_size": 0.10, "step_size": 0.001, "min_notional": 5.0,
        "price_precision": 2, "qty_precision": 3,
    }

    candles = fetch_history(client, days=days)
    if len(candles) < 60:
        print("Not enough history fetched: %d candles" % len(candles))
        return
    print("Loaded %d candles (%s -> %s)" % (
        len(candles), candles[0]["ts"], candles[-1]["ts"]))

    ts_index = {c["ts"]: i for i, c in enumerate(candles)}
    sess = SESSIONS["PRIME"]
    sh, sm = sess["start_utc"]
    eh, em = sess["end_utc"]

    days_seen = sorted({c["ts"][:10] for c in candles})
    trades = []
    signals = 0

    # --- Diagnostics: find out WHERE setups die ---
    days_total = 0
    days_with_fib = 0
    reason_tally = {}   # NO_TRADE reason -> count (across all evaluated candles)

    for day in days_seen:
        d0 = datetime.datetime.strptime(day, "%Y-%m-%d")

        # Mirror live behaviour: skip weekends unless explicitly enabled.
        if not TRADE_WEEKENDS and d0.weekday() >= 5:
            continue

        # Mirror live behaviour: skip US market holidays.
        if SKIP_US_HOLIDAYS and day in US_HOLIDAYS:
            continue

        imp_start = d0.replace(hour=sh, minute=sm)
        imp_end = imp_start + datetime.timedelta(minutes=sess["impulse_end_min"])
        sess_end = d0.replace(hour=eh, minute=em)
        days_total += 1

        impulse, pre_close = [], None
        for c in candles:
            dt = _parse_ts(c["ts"])
            if dt.date() != d0.date():
                continue
            if dt < imp_start:
                pre_close = c["close"]
            elif imp_start <= dt < imp_end:
                impulse.append(c)

        fib_data = _fibs_from_impulse(impulse, pre_close, "PRIME")
        if not fib_data:
            continue
        days_with_fib += 1

        # Walk the rest of the session looking for the first valid signal
        for c in candles:
            dt = _parse_ts(c["ts"])
            if not (imp_end <= dt < sess_end):
                continue
            idx = ts_index[c["ts"]]
            if idx < 30 or idx + 1 >= len(candles):
                continue
            res = check_fib_signal(candles[:idx + 1], fib_data)
            if res["signal"] not in ("LONG", "SHORT"):
                reason = res.get("details", {}).get("reason", "unknown")
                reason_tally[reason] = reason_tally.get(reason, 0) + 1
                continue
            if res.get("confidence") not in ("HIGH", "MED"):
                continue
            # Higher-timeframe (1H) trend gate — derived by resampling the same
            # 5m history so backtest matches live behaviour.
            if HTF_TREND_ENABLED:
                htf = resample_to_htf(candles[:idx + 1], hours=1)
                htf_trend, _, _ = compute_htf_trend(htf)
                if htf_trend is not None and htf_trend != res["direction"]:
                    reason_tally["HTF trend mismatch"] = reason_tally.get("HTF trend mismatch", 0) + 1
                    continue
            signals += 1
            atr = res.get("atr")
            if not atr or atr <= 0:
                break

            entry_price = candles[idx + 1]["open"]  # realistic next-bar entry
            forward = [fc for fc in candles[idx + 1:] if _parse_ts(fc["ts"]) < sess_end]
            if not forward:
                break

            sim = _simulate_trade(res["direction"], entry_price, atr,
                                  fib_data, sym_info, forward)
            if sim:
                sim["day"] = day
                sim["dir"] = res["direction"]
                sim["conf"] = res.get("confidence", "")
                sim["entry"] = round(entry_price, 2)
                trades.append(sim)
            break  # one trade per session (matches live behaviour)

    diag = {
        "days_total": days_total,
        "days_with_fib": days_with_fib,
        "reason_tally": reason_tally,
    }
    _print_backtest_report(trades, signals, days, diag)


def _print_diag(diag):
    if not diag:
        return
    print("-" * 56)
    print(" DIAGNOSTICS (why setups die):")
    print("   Days scanned          : %d" % diag.get("days_total", 0))
    print("   Days w/ valid impulse : %d" % diag.get("days_with_fib", 0))
    tally = diag.get("reason_tally", {})
    if tally:
        print("   NO_TRADE reasons (candles rejected):")
        for reason, cnt in sorted(tally.items(), key=lambda kv: -kv[1]):
            print("     %5d  %s" % (cnt, reason))


def _print_backtest_report(trades, signals, days, diag=None):
    print("\n" + "=" * 56)
    print(" BACKTEST REPORT — %s | last %d days | %dx lev" % (SYMBOL, days, LEVERAGE))
    print("=" * 56)
    if not trades:
        print(" Signals evaluated: %d" % signals)
        print(" No trades taken (filters too tight or quiet market).")
        _print_diag(diag)
        print("=" * 56)
        return

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total = sum(t["pnl"] for t in trades)
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in losses)
    win_rate = len(wins) / len(trades) * 100
    avg_win = gross_win / len(wins) if wins else 0
    avg_loss = gross_loss / len(losses) if losses else 0
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    expectancy = total / len(trades)

    # Equity curve / max drawdown
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for t in trades:
        equity += t["pnl"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    print(" Signals evaluated : %d" % signals)
    print(" Trades taken      : %d" % len(trades))
    print(" Win rate          : %.1f%% (%dW / %dL)" % (win_rate, len(wins), len(losses)))
    print(" Net P&L           : $%+.2f" % total)
    print(" Avg win / loss    : $%.2f / -$%.2f" % (avg_win, avg_loss))
    print(" Profit factor     : %s" % ("%.2f" % pf if pf != float("inf") else "inf"))
    print(" Expectancy/trade  : $%+.2f" % expectancy)
    print(" Max drawdown      : -$%.2f" % max_dd)
    print(" Return on capital : %+.1f%% (capital $%d)" % (total / CAPITAL_USDT * 100, CAPITAL_USDT))

    # --- Breakdown by exit reason (where the money goes) ---
    print("-" * 56)
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
        print("   %-13s | %2d trades | %dW | $%+.2f" % (name, r["n"], r["w"], r["pnl"]))

    # --- Breakdown by direction (is one side dragging?) ---
    print(" BY DIRECTION:")
    for d in ("BULL", "BEAR"):
        sub = [t for t in trades if t["dir"] == d]
        if sub:
            w = len([t for t in sub if t["pnl"] > 0])
            print("   %-5s | %2d trades | %dW (%.0f%%) | $%+.2f" % (
                d, len(sub), w, w / len(sub) * 100, sum(t["pnl"] for t in sub)))

    print("-" * 56)
    for t in trades:
        print(" %s | %-5s | entry $%-9.2f | %-12s | $%+.2f" % (
            t["day"], t["dir"], t["entry"], t["reason"], t["pnl"]))
    _print_diag(diag)
    print("=" * 56)
    print(" NOTE: live results WILL be worse (slippage, funding, latency).")
    print(" Validate on testnet before going live.")
    print("=" * 56)


# =============================================================
#  SECTION 10 - MAIN
# =============================================================

def main():
    run_mode = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if run_mode == "backtest":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        run_backtest(days=days)
        return

    if run_mode == "monitor":
        logging.info("=== CRYPTO MONITOR MODE ===")
        state = load_state()
        trades = state.get("trades", [])
        if not trades or trades[-1].get("exited"):
            logging.info("No active trade")
            return
        client = get_client()
        run_monitor(client, state)
        return

    # SCAN MODE
    now = utc_now()
    state = load_state()

    if is_monitor_running():
        logging.info("Monitor active — skip scan")
        return

    trades = state.get("trades", [])
    if trades and not trades[-1].get("exited"):
        logging.info("Unexited trade — restarting monitor")
        _spawn_monitor()
        return

    # Check session
    session_name, session = get_current_session()
    if session is None:
        logging.info("[%s UTC] No active session" % now.strftime("%H:%M"))
        return

    # Check if already traded this session
    if session_name in state.get("sessions_traded", []):
        logging.info("[%s] Already traded %s session" % (now.strftime("%H:%M"), session_name))
        return

    # Check daily loss
    if state.get("daily_pnl_usdt", 0) <= -MAX_DAILY_LOSS_USDT:
        logging.info("Daily loss limit hit: $%.2f" % state["daily_pnl_usdt"])
        return

    # Check consecutive losses
    losses = 0
    for t in reversed(state.get("trades", [])):
        if t.get("exited") and t.get("exit_pnl", 0) < 0:
            losses += 1
        else:
            break
    if losses >= MAX_CONSECUTIVE_LOSSES:
        logging.info("Circuit breaker: %d consecutive losses" % losses)
        return

    # Check impulse window
    impulse_start, impulse_end = get_impulse_window(session)
    if now < impulse_end:
        logging.info("[%s] %s impulse forming (wait till %s UTC)" % (
            now.strftime("%H:%M"), session_name, impulse_end.strftime("%H:%M")))
        return

    tag = "TESTNET" if USE_TESTNET else "LIVE"
    logging.info("=== %s SCAN | %s | Session:%s | P&L:$%+.2f ===" % (
        tag, now.strftime("%Y-%m-%d %H:%M:%S"), session_name,
        state.get("daily_pnl_usdt", 0)))

    client = get_client()
    setup_leverage(client)
    sym_info = get_symbol_info(client)
    if sym_info is None:
        logging.error("Cannot get symbol info for %s" % SYMBOL)
        return

    candles = fetch_candles(client)
    if len(candles) < 30:
        logging.error("Not enough candles: %d" % len(candles))
        return

    # Compute fibs
    fib_data = load_fib_levels()
    if fib_data is None:
        fib_data = compute_impulse_and_fibs(candles, session_name, session)
        if fib_data is None:
            logging.info("No valid impulse in %s session" % session_name)
            return
        save_fib_levels(fib_data)
        logging.info("FIB | %s | Swing:$%.2f-$%.2f | Range:$%.2f" % (
            fib_data["direction"], fib_data["swing_low"],
            fib_data["swing_high"], fib_data["impulse_range"]))
        logging.info("  Zone: $%.2f - $%.2f | SL:$%.2f" % (
            fib_data["entry_zone_lower"], fib_data["entry_zone_upper"],
            fib_data["fib_sl"]))

    # Check signal
    result = check_fib_signal(candles, fib_data)
    signal_type = result["signal"]
    confidence = result.get("confidence")
    d = result.get("details", {})
    atr = result.get("atr")

    logging.info("  Signal:%s | Conf:%s | Score:%s" % (
        signal_type, confidence, d.get("score", "--")))
    if d.get("reason"):
        logging.info("  -> %s" % d["reason"])

    if signal_type == "NO_TRADE":
        return
    if confidence not in ("HIGH", "MED"):
        return

    # Higher-timeframe (1H) trend gate. Only BLOCKS trades that fight the 1H
    # trend; it never alters the fib/sizing/SL/TP logic below.
    if HTF_TREND_ENABLED:
        htf_candles = fetch_candles(client, interval=HTF_INTERVAL, limit=HTF_FETCH_LIMIT)
        htf_trend, hf, hs = compute_htf_trend(htf_candles)
        want = "BULL" if signal_type == "LONG" else "BEAR"
        if htf_trend is None:
            logging.info("  HTF(%s) trend undecided — allowing trade" % HTF_INTERVAL)
        else:
            logging.info("  HTF(%s) trend: %s | EMA%d:%.1f EMA%d:%.1f" % (
                HTF_INTERVAL, htf_trend, HTF_EMA_FAST, hf, HTF_EMA_SLOW, hs))
            if htf_trend != want:
                logging.info("  -> Blocked: 5M %s vs %s %s trend" % (
                    signal_type, HTF_INTERVAL, htf_trend))
                return

    # Get current price
    btc_price = get_btc_price(client)
    logging.info("  BTC: $%.2f" % btc_price)

    if atr is None or atr <= 0:
        logging.error("No ATR — cannot size position")
        return

    # Calculate position
    pos = calculate_position(client, btc_price, atr, fib_data, sym_info)
    if pos is None:
        logging.warning("Position too small")
        return

    if pos["rr"] < MIN_RR_RATIO:
        logging.warning("RR %.1f < %.1f — rejected" % (pos["rr"], MIN_RR_RATIO))
        return

    logging.info("  PLAN | Qty:%s | SL:$%.2f | TP:$%.2f" % (pos["qty"], pos["sl_price"], pos["tp_price"]))
    logging.info("       | Risk:$%.2f | Reward:$%.2f | RR:1:%.1f" % (
        pos["risk_usdt"], pos["reward_usdt"], pos["rr"]))
    logging.info("       | Notional:$%.2f | Leverage:%.1fx" % (pos["notional"], pos["leverage_used"]))

    # Check balance
    balance = get_balance(client)
    required = pos["notional"] / LEVERAGE * 1.05  # 5% buffer
    if balance < required:
        logging.warning("Insufficient balance: $%.2f < $%.2f required" % (balance, required))
        return

    # EXECUTE
    direction = fib_data["direction"]
    oid, order = place_entry(client, direction, pos["qty"], sym_info)
    if oid is None:
        return

    time.sleep(1)

    # Get fill price
    try:
        fill_price = btc_price
        if order and order.get("avgPrice"):
            fill_price = float(order["avgPrice"])
        elif not USE_TESTNET:
            fills = client.get_all_orders(symbol=SYMBOL, orderId=oid, limit=1)
            if fills:
                fill_price = float(fills[0].get("avgPrice", btc_price))
    except:
        fill_price = btc_price

    # Place SL/TP orders on exchange (backup to WebSocket monitor)
    exch_sl_tp = place_sl_tp_orders(client, direction, pos["qty"], pos["sl_price"], pos["tp_price"])
    if not exch_sl_tp:
        logging.info("  Exit protection: SOFTWARE MONITOR only (no exchange SL/TP).")

    # Save trade
    state["trade_count"] = state.get("trade_count", 0) + 1
    if session_name not in state.get("sessions_traded", []):
        state.setdefault("sessions_traded", []).append(session_name)

    state["trades"].append({
        "signal": signal_type,
        "confidence": confidence,
        "direction": direction,
        "symbol": SYMBOL,
        "qty": pos["qty"],
        "remaining_qty": pos["qty"],
        "entry_price": round(fill_price, 2),
        "entry_id": str(oid),
        "sl_price": pos["sl_price"],
        "tp_price": pos["tp_price"],
        "sl_distance": pos["sl_distance"],
        "tp_distance": pos["tp_distance"],
        "risk_usdt": pos["risk_usdt"],
        "reward_usdt": pos["reward_usdt"],
        "rr": pos["rr"],
        "step_size": sym_info["step_size"],
        "session": session_name,
        "fib_direction": fib_data["direction"],
        "fib_swing_high": fib_data["swing_high"],
        "fib_swing_low": fib_data["swing_low"],
        "bounce_type": d.get("bounce_type", ""),
        "score": d.get("score", ""),
        "testnet": USE_TESTNET,
        "exited": False,
        "partial_done": False,
        "time": utc_now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    save_state(state)

    logging.info("=== %s TRADE | %s %s | $%.2f | Qty:%s | RR:1:%.1f ===" % (
        tag, signal_type, SYMBOL, fill_price, pos["qty"], pos["rr"]))

    _spawn_monitor()


def _spawn_monitor():
    import subprocess
    script_path = os.path.abspath(__file__)
    popen_kwargs = {
        "stdout": open(MONITOR_LOG, "a"),
        "stderr": subprocess.STDOUT,
    }
    # Detach the monitor so it survives the parent scan process exiting.
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [sys.executable, script_path, "monitor"],
        **popen_kwargs,
    )
    logging.info("Monitor spawned: PID %d" % proc.pid)


if __name__ == "__main__":
    main()
