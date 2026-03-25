# ============================================================
#  OPTIONS SCALPER v2 — VPS (Hetzner + Groww API)
#  Signal engine upgraded from Pine Script:
#    - EMA ribbon (8/21/55/144) trend filter
#    - MACD + RSI + Stoch + Volume + ADX confluence (0-7)
#    - SFP (Swing Failure Pattern) detection
#    - Supply/Demand pivot zones
#    - Instant candles via historical API (no 50-run warmup)
# ============================================================

from growwapi import GrowwAPI
import datetime
import logging
import json
import time
import pyotp

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

GROWW_TOTP_TOKEN  = "eyJraWQiOiJaTUtjVXciLCJhbGciOiJFUzI1NiJ9.eyJleHAiOjI1NjIwNzAwNjAsImlhdCI6MTc3MzY3MDA2MCwibmJmIjoxNzczNjcwMDYwLCJzdWIiOiJ7XCJ0b2tlblJlZklkXCI6XCJmYTIxZTUyMC1kNjMyLTRlYTQtOGE3NS0zMTdjZmY2YzEzNTBcIixcInZlbmRvckludGVncmF0aW9uS2V5XCI6XCJlMzFmZjIzYjA4NmI0MDZjODg3NGIyZjZkODQ5NTMxM1wiLFwidXNlckFjY291bnRJZFwiOlwiNjQ3NTk3YTItNTlmMC00MWQ2LTkyZjgtMGNjYzdkYTBkN2I2XCIsXCJkZXZpY2VJZFwiOlwiYzY2YmE0NmItMDlhNC01Zjk4LWI5NDMtZmMwNzQzZGNiMmZhXCIsXCJzZXNzaW9uSWRcIjpcIjMxZjMzODQ3LTMxN2ItNGFhMC04MGFiLTkzMGU4MzQxOGY4MlwiLFwiYWRkaXRpb25hbERhdGFcIjpcIno1NC9NZzltdjE2WXdmb0gvS0EwYkgyblRaQUhZYlRzeVhHdDk1ZzgxR1JSTkczdTlLa2pWZDNoWjU1ZStNZERhWXBOVi9UOUxIRmtQejFFQisybTdRPT1cIixcInJvbGVcIjpcImF1dGgtdG90cFwiLFwic291cmNlSXBBZGRyZXNzXCI6XCIyNDAxOjQ5MDA6YzkwODphNDE3OjQ5YWQ6ZTA1MzphNWIzOjJhOGYsMTcyLjY5LjEyOS4xOTksMzUuMjQxLjIzLjEyM1wiLFwidHdvRmFFeHBpcnlUc1wiOjI1NjIwNzAwNjAxMTMsXCJ2ZW5kb3JOYW1lXCI6XCJncm93d0FwaVwifSIsImlzcyI6ImFwZXgtYXV0aC1wcm9kLWFwcCJ9.NW_6x92tZNRbyYsGtw7yOTUcSAyh0RZcA5rMhwHlczoMF45_cbZKbtobadvKkzuBkPePNU2ETU5TPnwfJcONkw"
GROWW_TOTP_SECRET = "M52LDHMGZVUDO5VCSFTKAGZUJHXWSSSY"

LOT_SIZE         = 65
LOTS_TO_TRADE    = 1
HIGH_ONLY        = True         # only HIGH confluence signals — be selective

TARGET_MULT      = 2.0          # 2× target → strong R:R on intraday options
SL_MULT          = 0.4          # tight 40% SL — quick exit on wrong trades
USE_SMART_ORDERS = True

SQUAREOFF_HOUR          = 15
SQUAREOFF_MIN           = 10
NO_NEW_TRADE_HOUR       = 14
NO_NEW_TRADE_MIN        = 15
OPENING_RANGE_MINUTES   = 20
NO_TRADE_BEFORE_SQ_MINS = 20

MAX_TRADES_DAY            = 3
MAX_DAILY_LOSS_RUPEES     = 2000
MAX_CONSECUTIVE_LOSSES    = 2
MAX_OPEN_POSITIONS        = 1
COOLDOWN_MINUTES          = 15
CAPITAL_RUPEES            = 50000
MAX_CAPITAL_EXPOSURE_PCT  = 24
MAX_SPREAD_PCT            = 3.0
MIN_OPTION_PREMIUM        = 80
MAX_OPTION_PREMIUM        = 180
MAX_LOSS_PER_TRADE_RUPEES = 1000

# Signal engine settings (mirrors Pine Script)
EMA_SHORT   = 8
EMA_MED     = 21
EMA_LONG    = 55
EMA_XLONG   = 144
RSI_LEN     = 14
MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIG    = 9
STOCH_LEN   = 14
ADX_LEN     = 14
ATR_LEN     = 14
SFP_LOOKBACK= 20
PIVOT_LEN   = 5
MIN_CONFLUENCE = 4        # minimum score out of 7 to take trade
MIN_ATR_POINTS = 15       # min Nifty ATR pts — below this = choppy, skip all trades
VWAP_SESSION_BARS = 75    # ~1 full trading session of 5-min bars for session VWAP

STATE_FILE  = "/root/scalper/state.json"
TOKEN_FILE  = "/root/scalper/token.json"
CANDLE_FILE = "/root/scalper/candles.json"

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

def sma(data, period):
    return [None if i < period-1 else sum(data[i-period+1:i+1])/period
            for i in range(len(data))]

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

def calc_rsi(closes, period=14):
    gains  = [None]+[max(closes[i]-closes[i-1],0) for i in range(1,len(closes))]
    losses = [None]+[max(closes[i-1]-closes[i],0) for i in range(1,len(closes))]
    ag,al  = rma(gains,period), rma(losses,period)
    return [None if g is None or l is None else (100.0 if l==0 else 100-100/(1+g/l))
            for g,l in zip(ag,al)]

def calc_macd(closes, fast=12, slow=26, sig=9):
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [None if a is None or b is None else a-b
                 for a,b in zip(ema_fast, ema_slow)]
    # signal line = EMA of macd_line
    valid = [v if v is not None else 0 for v in macd_line]
    sig_line = ema(valid, sig)
    hist = [None if a is None or b is None else a-b
            for a,b in zip(macd_line, sig_line)]
    return macd_line, sig_line, hist

def calc_stoch(highs, lows, closes, period=14, smooth=3):
    stoch_k = []
    for i in range(len(closes)):
        if i < period-1:
            stoch_k.append(None)
        else:
            hh = max(highs[i-period+1:i+1])
            ll = min(lows[i-period+1:i+1])
            if hh == ll:
                stoch_k.append(50.0)
            else:
                stoch_k.append((closes[i]-ll)/(hh-ll)*100)
    stoch_d = sma([v if v is not None else 0 for v in stoch_k], smooth)
    return stoch_k, stoch_d

def calc_atr(highs, lows, closes, period=14):
    tr = [None]+[max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
                 for i in range(1,len(closes))]
    return rma(tr, period)

def calc_adx(highs, lows, closes, period=14):
    plus_dm  = [None]+[(highs[i]-highs[i-1]) if (highs[i]-highs[i-1])>(lows[i-1]-lows[i]) and (highs[i]-highs[i-1])>0 else 0.0 for i in range(1,len(closes))]
    minus_dm = [None]+[(lows[i-1]-lows[i]) if (lows[i-1]-lows[i])>(highs[i]-highs[i-1]) and (lows[i-1]-lows[i])>0 else 0.0 for i in range(1,len(closes))]
    tr       = [None]+[max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1,len(closes))]
    tr_s=rma(tr,period); pdm_s=rma(plus_dm,period); mdm_s=rma(minus_dm,period)
    pdi,mdi,dx=[],[],[]
    for ts,ps,ms in zip(tr_s,pdm_s,mdm_s):
        if None in (ts,ps,ms) or ts==0:
            pdi.append(None); mdi.append(None); dx.append(None)
        else:
            p=100*ps/ts; m=100*ms/ts
            pdi.append(p); mdi.append(m)
            dx.append(100*abs(p-m)/(p+m) if (p+m)!=0 else 0)
    return rma(dx,period), pdi, mdi

def safe(s, idx=-1):
    try: return s[idx]
    except: return None

def calc_vwap(highs, lows, closes, volumes):
    """Session-anchored VWAP — reset each time called on a fresh window."""
    result, cpv, cv = [], 0.0, 0.0
    for h, l, c, v in zip(highs, lows, closes, volumes):
        cpv += (h + l + c) / 3 * v
        cv  += v
        result.append(cpv / cv if cv > 0 else c)
    return result

# ═════════════════════════════════════════════════════════════
#  SECTION 3 — SIGNAL ENGINE (Pine Script logic in Python)
# ═════════════════════════════════════════════════════════════

def compute_signals(candles):
    if len(candles) < 150:
        return {"signal":"NO_TRADE","confidence":None,"score":0,
                "details":{"reason":f"Need candles: {len(candles)}/150"}}

    opens   = [c["open"]   for c in candles]
    highs   = [c["high"]   for c in candles]
    lows    = [c["low"]    for c in candles]
    closes  = [c["close"]  for c in candles]
    volumes = [c["volume"] for c in candles]

    # ── Indicators ───────────────────────────────────────────
    ema8_s   = ema(closes, EMA_SHORT)
    ema21_s  = ema(closes, EMA_MED)
    ema55_s  = ema(closes, EMA_LONG)
    ema144_s = ema(closes, EMA_XLONG)
    rsi_s            = calc_rsi(closes, RSI_LEN)
    _, _, macd_hist  = calc_macd(closes, MACD_FAST, MACD_SLOW, MACD_SIG)
    stoch_k, stoch_d = calc_stoch(highs, lows, closes, STOCH_LEN)
    atr_s            = calc_atr(highs, lows, closes, ATR_LEN)
    adx_s, pdi_s, mdi_s = calc_adx(highs, lows, closes, ADX_LEN)
    vol_sma          = sma(volumes, 20)

    # ── Session VWAP (last VWAP_SESSION_BARS bars ≈ 1 trading day)
    # CE trades only ABOVE session VWAP; PE trades only BELOW — institutional rule
    vb     = min(VWAP_SESSION_BARS, len(candles))
    vwap_s = calc_vwap(highs[-vb:], lows[-vb:], closes[-vb:], volumes[-vb:])
    lvwap  = safe(vwap_s)

    # ── CVD: cumulative volume delta (all candles, not just 30)
    cvd = sum(v if c > o else (-v if c < o else 0.0)
              for c, o, v in zip(closes, opens, volumes))

    # ── Scalar current values
    lc    = safe(closes);  le8   = safe(ema8_s);    le21  = safe(ema21_s)
    le55  = safe(ema55_s); le144 = safe(ema144_s);  lr    = safe(rsi_s)
    latr  = safe(atr_s);   ladx  = safe(adx_s);     lpdi  = safe(pdi_s)
    lmdi  = safe(mdi_s);   lmacd = safe(macd_hist); lsk   = safe(stoch_k)
    lsd   = safe(stoch_d); lvol  = safe(volumes);   lvsma = safe(vol_sma)

    if None in (lc, le8, le21, le55, le144, lr, lmacd, lsk, lsd, ladx):
        return {"signal":"NO_TRADE","confidence":None,"score":0,
                "details":{"reason":"Indicators not ready"}}

    # ── ATR volatility gate — never trade in choppy / low-range conditions
    # Professional rule: if average candle range < MIN_ATR_POINTS, options
    # won't move enough to overcome spread + slippage
    if latr is not None and latr < MIN_ATR_POINTS:
        return {"signal":"NO_TRADE","confidence":None,"score":0,
                "details":{"reason":f"ATR too low ({latr:.1f} pts) — choppy session",
                            "atr_state":"LOW","close":round(lc,2),
                            "long_score":"0/7","short_score":"0/7",
                            "long_pred":"0%","short_pred":"0%"}}

    rvol = (lvol / lvsma) if lvol and lvsma and lvsma > 0 else 1.0

    # ── ATR state
    atr_vals  = [v for v in atr_s[-20:] if v is not None]
    atr_avg   = sum(atr_vals) / len(atr_vals) if atr_vals else 1.0
    atr_state = "HIGH" if latr > atr_avg * 1.2 else ("LOW" if latr < atr_avg * 0.8 else "NORM")

    # ── Trend (EMA ribbon alignment)
    trend_bull  = lc > le21 and le21 > le55 and le55 > le144
    trend_bear  = lc < le21 and le21 < le55 and le55 < le144
    trend_state = 1 if trend_bull else (-1 if trend_bear else 0)

    # ── Session VWAP bias + overextension guard
    # If price > 1.5 ATR from VWAP it is extended — avoid chasing; wait for pullback
    vwap_bull     = lvwap is not None and lc > lvwap
    vwap_bear     = lvwap is not None and lc < lvwap
    vwap_dist     = abs(lc - lvwap) if lvwap is not None else 0.0
    vwap_extended = latr is not None and vwap_dist > latr * 1.5

    # ── SFP detection
    recent_highs = highs[-SFP_LOOKBACK-1:-1]
    recent_lows  = lows[-SFP_LOOKBACK-1:-1]
    hh = max(recent_highs) if recent_highs else lc
    ll = min(recent_lows)  if recent_lows  else lc
    bull_sfp = lows[-1]  < ll and closes[-1] > ll    # wick below low, close back above
    bear_sfp = highs[-1] > hh and closes[-1] < hh   # wick above high, close back below

    # ── Pivot zone proximity (supply / demand)
    pivot_highs, pivot_lows = [], []
    p = PIVOT_LEN
    for i in range(p, len(highs) - p):
        if all(highs[i] >= highs[i-j] for j in range(1, p+1)) and \
           all(highs[i] >= highs[i+j] for j in range(1, p+1)):
            pivot_highs.append(highs[i])
        if all(lows[i] <= lows[i-j] for j in range(1, p+1)) and \
           all(lows[i] <= lows[i+j] for j in range(1, p+1)):
            pivot_lows.append(lows[i])
    zone_buf    = latr * 0.6 if latr else 0
    near_supply = any(abs(lc - ph) < zone_buf for ph in pivot_highs[-6:])
    near_demand = any(abs(lc - pl) < zone_buf for pl in pivot_lows[-6:])

    # ── Engulfing candle — institutional momentum confirmation
    # A full engulf of the prior candle signals strong conviction
    bull_engulf = (opens[-1] <= closes[-2] and closes[-1] > opens[-2] and closes[-1] > opens[-1])
    bear_engulf = (opens[-1] >= closes[-2] and closes[-1] < opens[-2] and closes[-1] < opens[-1])

    # ── 7 Confluence components ──────────────────────────────
    macd_bull  = lmacd > 0;     macd_bear  = lmacd < 0
    rsi_bull   = lr >= 50;      rsi_bear   = lr < 50
    stoch_bull = lsk > lsd;     stoch_bear = lsk < lsd
    # High RVOL confirms participation in BOTH directions — CVD/delta gives direction
    vol_bull   = rvol >= 1.0;   vol_bear   = rvol >= 1.0
    delta_bull = cvd > 0;       delta_bear = cvd < 0
    adx_strong = ladx >= 25
    pdi_bull   = (lpdi > lmdi) if (lpdi and lmdi) else False
    mdi_bear   = (lmdi > lpdi) if (lpdi and lmdi) else False

    long_score  = sum([int(macd_bull), int(rsi_bull),  int(stoch_bull),
                       int(vol_bull),  int(delta_bull), int(adx_strong), int(pdi_bull)])
    short_score = sum([int(macd_bear), int(rsi_bear),  int(stoch_bear),
                       int(vol_bear),  int(delta_bear), int(adx_strong), int(mdi_bear)])

    # ── Engulfing bonus (+1, capped at 7) — strong candle elevates score
    if bull_engulf and delta_bull: long_score  = min(long_score  + 1, 7)
    if bear_engulf and delta_bear: short_score = min(short_score + 1, 7)

    # ── Entry triggers: EMA cross OR SFP near zone
    # Gated by: trend direction + VWAP side + not overextended from VWAP
    ema_cross_bull = (ema8_s[-2] is not None and ema21_s[-2] is not None and
                      ema8_s[-2] <= ema21_s[-2] and le8 > le21)
    ema_cross_bear = (ema8_s[-2] is not None and ema21_s[-2] is not None and
                      ema8_s[-2] >= ema21_s[-2] and le8 < le21)

    vwap_ce_ok = vwap_bull and not vwap_extended   # CE only above VWAP, not overextended
    vwap_pe_ok = vwap_bear and not vwap_extended   # PE only below VWAP, not overextended

    buy_trigger  = (ema_cross_bull or (bull_sfp and near_demand)) and trend_state >= 0 and vwap_ce_ok
    sell_trigger = (ema_cross_bear or (bear_sfp and near_supply)) and trend_state <= 0 and vwap_pe_ok

    # ── Confidence
    ce_conf = "HIGH" if long_score  >= 5 else ("MED" if long_score  >= MIN_CONFLUENCE else None)
    pe_conf = "HIGH" if short_score >= 5 else ("MED" if short_score >= MIN_CONFLUENCE else None)

    if   buy_trigger  and ce_conf:
        signal, confidence, score = "CE_BUY", ce_conf, long_score
    elif sell_trigger and pe_conf:
        signal, confidence, score = "PE_BUY", pe_conf, short_score
    else:
        signal, confidence, score = "NO_TRADE", None, 0

    long_pred  = round(long_score  / 7.0 * 100)
    short_pred = round(short_score / 7.0 * 100)

    return {
        "signal": signal, "confidence": confidence, "score": score,
        "details": {
            "close"         : round(lc,    2),
            "vwap"          : round(lvwap, 2) if lvwap else "N/A",
            "vwap_pos"      : "Above" if vwap_bull else ("Below" if vwap_bear else "At"),
            "vwap_ext"      : vwap_extended,
            "ema8"          : round(le8,   2),
            "ema21"         : round(le21,  2),
            "ema55"         : round(le55,  2),
            "rsi"           : round(lr,    1),
            "macd_hist"     : round(lmacd, 3),
            "stoch_k"       : round(lsk,   1),
            "adx"           : round(ladx,  1),
            "rvol"          : round(rvol,  2),
            "atr_state"     : atr_state,
            "trend"         : "Bullish" if trend_bull else "Bearish" if trend_bear else "Sideways",
            "bull_sfp"      : bull_sfp,
            "bear_sfp"      : bear_sfp,
            "bull_engulf"   : bull_engulf,
            "bear_engulf"   : bear_engulf,
            "near_demand"   : near_demand,
            "near_supply"   : near_supply,
            "ema_cross_bull": ema_cross_bull,
            "ema_cross_bear": ema_cross_bear,
            "long_score"    : f"{long_score}/7",
            "short_score"   : f"{short_score}/7",
            "long_pred"     : f"{long_pred}%",
            "short_pred"    : f"{short_pred}%",
        }
    }

# ═════════════════════════════════════════════════════════════
#  SECTION 4 — RISK MANAGER
# ═════════════════════════════════════════════════════════════

class RiskManager:
    def __init__(self, state): self.state = state

    def check_can_trade(self, groww):
        for passed, reason in [
            self._check_opening_range(),
            self._check_no_new_trade_time(),
            self._check_near_squareoff(),
            self._check_max_trades(),
            self._check_daily_loss(),
            self._check_consecutive_losses(),
            self._check_open_positions(groww),
            self._check_cooldown()]:
            if not passed: return False, reason
        return True, "All risk checks passed"

    def _check_opening_range(self):
        now    = ist_now()
        cutoff = now.replace(hour=9, minute=15, second=0, microsecond=0) + datetime.timedelta(minutes=OPENING_RANGE_MINUTES)
        if now < cutoff: return False, f"OPENING RANGE: {int((cutoff-now).total_seconds()/60)} min left"
        return True, "Opening range passed"

    def _check_no_new_trade_time(self):
        now    = ist_now()
        cutoff = now.replace(hour=NO_NEW_TRADE_HOUR, minute=NO_NEW_TRADE_MIN, second=0, microsecond=0)
        if now >= cutoff: return False, f"TIME: Past {NO_NEW_TRADE_HOUR}:{NO_NEW_TRADE_MIN:02d}"
        return True, "Time window OK"

    def _check_near_squareoff(self):
        now  = ist_now()
        sq   = now.replace(hour=SQUAREOFF_HOUR, minute=SQUAREOFF_MIN, second=0, microsecond=0)
        mins = (sq - now).total_seconds() / 60
        if 0 < mins < NO_TRADE_BEFORE_SQ_MINS: return False, f"NEAR SQUAREOFF: {int(mins)} min left"
        return True, "Square-off buffer OK"

    def _check_max_trades(self):
        c = self.state.get("trade_count", 0)
        return (False, f"MAX TRADES: {c}/{MAX_TRADES_DAY}") if c >= MAX_TRADES_DAY else (True, f"Trades {c}/{MAX_TRADES_DAY}")

    def _check_daily_loss(self):
        pnl = self.state.get("daily_pnl_rupees", 0)
        return (False, f"MAX DAILY LOSS: Rs.{pnl}") if pnl <= -MAX_DAILY_LOSS_RUPEES else (True, f"P&L Rs.{pnl:+.0f}")

    def _check_consecutive_losses(self):
        c = self.state.get("consecutive_losses", 0)
        return (False, f"CONSECUTIVE LOSSES: {c}/{MAX_CONSECUTIVE_LOSSES}") if c >= MAX_CONSECUTIVE_LOSSES else (True, f"Streak {c}/{MAX_CONSECUTIVE_LOSSES}")

    def _check_open_positions(self, groww):
        try:
            res      = groww.get_positions_for_user(segment=groww.SEGMENT_FNO)
            open_pos = [p for p in res.get("positions", [])
                        if int(p.get("quantity", 0)) != 0 and "NIFTY" in p.get("trading_symbol", "")]
            if len(open_pos) >= MAX_OPEN_POSITIONS:
                return False, f"POSITION LOCK: {[p['trading_symbol'] for p in open_pos]}"
            return True, f"Positions {len(open_pos)}/{MAX_OPEN_POSITIONS}"
        except Exception as e: return False, f"POSITION CHECK FAILED: {e}"

    def _check_cooldown(self):
        last = self.state.get("last_exit_time")
        if not last: return True, "No cooldown"
        elapsed = (ist_now() - datetime.datetime.strptime(last, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
        if elapsed < COOLDOWN_MINUTES: return False, f"COOLDOWN: {int(COOLDOWN_MINUTES-elapsed)} min remaining"
        return True, f"Cooldown OK ({int(elapsed)} min ago)"

    def check_premium_range(self, ltp):
        if not ltp or ltp <= 0: return False, "PREMIUM: Could not fetch"
        if ltp < MIN_OPTION_PREMIUM: return False, f"PREMIUM TOO LOW: Rs.{ltp}"
        if ltp > MAX_OPTION_PREMIUM: return False, f"PREMIUM TOO HIGH: Rs.{ltp}"
        return True, f"Premium OK: Rs.{ltp}"

    def check_capital_exposure(self, ltp, qty):
        exposure = ltp * qty
        max_exp  = CAPITAL_RUPEES * MAX_CAPITAL_EXPOSURE_PCT / 100
        pct      = exposure / CAPITAL_RUPEES * 100
        if exposure > max_exp: return False, f"EXPOSURE: Rs.{exposure:.0f} ({pct:.1f}%) > max"
        return True, f"Exposure OK: Rs.{exposure:.0f} ({pct:.1f}%)"

    def calc_adjusted_sl(self, ltp, qty):
        sl_mult = round(ltp * SL_MULT, 1)
        sl_cap  = round(max(ltp - MAX_LOSS_PER_TRADE_RUPEES / qty, 0.5), 1)
        final   = max(sl_mult, sl_cap)
        loss    = (ltp - final) * qty
        note    = "SL TIGHTENED" if final > sl_mult else "SL OK"
        return final, loss, f"{note}: Rs.{final} | Risk Rs.{loss:.0f}"

    def check_spread(self, groww, symbol):
        try:
            q   = groww.get_quote(exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_FNO, trading_symbol=symbol)
            bid = float(q.get("bid_price") or 0)
            ask = float(q.get("offer_price") or 0)
            ltp = float(q.get("last_price") or 1)
            if bid <= 0 or ask <= 0: return True, "Spread skipped"
            spread_pct = (ask - bid) / ltp * 100
            if spread_pct > MAX_SPREAD_PCT: return False, f"SPREAD: {spread_pct:.1f}% > {MAX_SPREAD_PCT}%"
            return True, f"Spread OK: {spread_pct:.1f}%"
        except Exception as e: return True, f"Spread skipped: {e}"

    def record_exit(self, pnl):
        self.state["daily_pnl_rupees"]   = self.state.get("daily_pnl_rupees", 0) + pnl
        self.state["consecutive_losses"] = (self.state.get("consecutive_losses", 0) + 1 if pnl < 0 else 0)
        self.state["last_exit_time"]     = ist_now().strftime("%Y-%m-%d %H:%M:%S")

# ═════════════════════════════════════════════════════════════
#  SECTION 5 — UTILITIES
# ═════════════════════════════════════════════════════════════

def ist_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)

def is_market_hours():
    now = ist_now()
    return (now.replace(hour=9, minute=15, second=0, microsecond=0) <= now <=
            now.replace(hour=SQUAREOFF_HOUR, minute=SQUAREOFF_MIN, second=0, microsecond=0))

def is_squareoff_time():
    now = ist_now()
    return now.hour > SQUAREOFF_HOUR or (now.hour == SQUAREOFF_HOUR and now.minute >= SQUAREOFF_MIN)

def get_atm_strike(ltp, step=50):
    return int(round(ltp / step) * step)

def get_expiry_str():
    today = ist_now().date()
    days  = (1 - today.weekday()) % 7
    if days == 0: days = 7
    return (today + datetime.timedelta(days=days)).strftime("%y%m%d")

def build_symbol(strike, opt_type):
    return f"NIFTY{get_expiry_str()}{strike}{opt_type}"

def fmt(p): return f"{p:.2f}"

def load_state():
    today = ist_now().strftime("%Y-%m-%d")
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
            if data.get("date") == today: return data
    except: pass
    return {"date":today,"trade_count":0,"trades":[],
            "daily_pnl_rupees":0.0,"consecutive_losses":0,"last_exit_time":None}

def save_state(state):
    with open(STATE_FILE, "w") as f: json.dump(state, f, indent=2)

# ═════════════════════════════════════════════════════════════
#  SECTION 6 — LOGIN (token cached — no repeat TOTP each run)
# ═════════════════════════════════════════════════════════════

def login():
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
            if data.get("date") == ist_now().strftime("%Y-%m-%d") and data.get("token"):
                groww = GrowwAPI(data["token"])
                logging.info("Groww login OK (cached token)")
                return groww
    except: pass
    logging.info("Generating fresh TOTP token...")
    totp_code    = pyotp.TOTP(GROWW_TOTP_SECRET).now()
    access_token = GrowwAPI.get_access_token(api_key=GROWW_TOTP_TOKEN, totp=totp_code)
    groww        = GrowwAPI(access_token)
    with open(TOKEN_FILE, "w") as f:
        json.dump({"date": ist_now().strftime("%Y-%m-%d"), "token": access_token}, f)
    logging.info("Groww login OK (fresh token cached)")
    return groww

# ═════════════════════════════════════════════════════════════
#  SECTION 7 — FETCH CANDLES
#  Incremental cache: cold-start loads 14 h (~200 candles);
#  subsequent runs fetch only the 1-2 new 5-min bars — fast.
# ═════════════════════════════════════════════════════════════

def fetch_candles(groww):
    now        = ist_now()
    today      = now.strftime("%Y-%m-%d")
    end_dt     = now.strftime("%Y-%m-%d %H:%M:%S")
    min_needed = 150

    try:
        with open(CANDLE_FILE) as f: cache = json.load(f)
    except: cache = {"date": "", "candles": []}
    if cache.get("date") != today:
        cache = {"date": today, "candles": []}
    existing = cache.get("candles", [])

    # Incremental if cache is warm, else full cold-start (14 h ≈ 200 candles)
    is_incremental = False
    if len(existing) >= min_needed and existing[-1].get("ts"):
        try:
            last_dt  = datetime.datetime.strptime(existing[-1]["ts"], "%Y-%m-%d %H:%M:%S")
            start_dt = (last_dt + datetime.timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
            is_incremental = True
        except Exception:
            start_dt = (now - datetime.timedelta(hours=14)).strftime("%Y-%m-%d %H:%M:%S")
    else:
        start_dt = (now - datetime.timedelta(hours=14)).strftime("%Y-%m-%d %H:%M:%S")

    # Primary: historical API
    try:
        res = groww.get_historical_candles(
            groww.EXCHANGE_NSE, groww.SEGMENT_CASH, "NIFTY",
            start_dt, end_dt, groww.CANDLE_INTERVAL_MIN_5)
        raw = res.get("candles", []) if isinstance(res, dict) else []
        if raw:
            new_candles = [{"ts"    : str(c[0]) if c[0] is not None else "",
                            "open"  : float(c[1]),
                            "high"  : float(c[2]),
                            "low"   : float(c[3]),
                            "close" : float(c[4]),
                            "volume": float(c[5]) if len(c) > 5 and c[5] else 0.0}
                           for c in raw if len(c) >= 5]
            if is_incremental:
                existing_ts = {c["ts"] for c in existing if c.get("ts")}
                merged = existing + [c for c in new_candles if c.get("ts") not in existing_ts]
                cache["candles"] = merged[-200:]
                logging.info(f"Incremental: +{len(new_candles)} candle(s) | total={len(cache['candles'])}")
            else:
                cache["candles"] = new_candles[-200:]
                logging.info(f"Full load: {len(cache['candles'])} candles — READY")
            try:
                with open(CANDLE_FILE, "w") as f: json.dump(cache, f)
            except Exception as e: logging.warning(f"Cache save failed: {e}")
            return [{k: v for k, v in c.items() if k != "ts"} for c in cache["candles"]]
        if is_incremental and len(existing) >= min_needed:
            logging.info(f"No new candles — reusing cache: {len(existing)}")
            return [{k: v for k, v in c.items() if k != "ts"} for c in existing[-200:]]
        logging.warning("Historical API returned empty — falling back to live quote")
    except Exception as e:
        logging.warning(f"Historical API failed: {e} — falling back to live quote")

    # Fallback: live quote snapshot (accumulates until warm)
    try:
        q     = groww.get_quote(exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_CASH, trading_symbol="NIFTY")
        ltp   = float(q["last_price"])
        ohlc  = q.get("ohlc", {})
        open_ = float(ohlc.get("open", ltp))
        high  = float(ohlc.get("high", ltp))
        low   = float(ohlc.get("low",  ltp))
        vol   = float(q.get("volume") or 0)
    except Exception as e:
        logging.error(f"Quote failed: {e}")
        return [{k: v for k, v in c.items() if k != "ts"} for c in existing[-200:]]

    snap_ts = now.strftime("%Y-%m-%d %H:%M:%S")
    candles = existing[:]
    if candles and candles[-1].get("ts") == snap_ts:
        candles[-1] = {"ts":snap_ts,"open":open_,"high":high,"low":low,"close":ltp,"volume":vol}
    else:
        candles.append({"ts":snap_ts,"open":open_,"high":high,"low":low,"close":ltp,"volume":vol})
    cache["candles"] = candles[-200:]
    try:
        with open(CANDLE_FILE, "w") as f: json.dump(cache, f)
    except Exception as e: logging.warning(f"Cache save failed: {e}")
    count = len(cache["candles"])
    logging.info(f"Live cache: {count} ({'READY' if count >= min_needed else f'need {min_needed - count} more'})")
    return [{k: v for k, v in c.items() if k != "ts"} for c in cache["candles"]]

# ═════════════════════════════════════════════════════════════
#  SECTION 8 — ORDER MANAGEMENT
# ═════════════════════════════════════════════════════════════

def get_option_ltp(groww, symbol):
    try:
        q = groww.get_quote(exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_FNO, trading_symbol=symbol)
        return float(q["last_price"])
    except Exception as e:
        logging.warning(f"Option LTP failed: {e}"); return None

def place_entry_order(groww, symbol, qty, txn):
    try:
        res = groww.place_order(
            trading_symbol=symbol, quantity=qty, validity=groww.VALIDITY_DAY,
            exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_FNO,
            product=groww.PRODUCT_MIS, order_type=groww.ORDER_TYPE_MARKET,
            transaction_type=txn, order_reference_id=f"ENTR{ist_now().strftime('%H%M%S')}")
        oid = res.get("groww_order_id", "N/A")
        logging.info(f"ENTRY | {symbol} | {txn} | Qty:{qty} | ID:{oid}")
        return oid, res.get("order_status", "N/A")
    except Exception as e:
        logging.error(f"ENTRY FAILED: {e}"); return None, str(e)

def place_oco_order(groww, symbol, qty, entry_premium, custom_sl=None):
    if not USE_SMART_ORDERS or not entry_premium or entry_premium <= 0: return None, None, None
    target = round(max(entry_premium * TARGET_MULT, entry_premium + 0.5), 1)
    sl     = custom_sl if custom_sl else round(max(entry_premium * SL_MULT, 0.5), 1)
    logging.info(f"OCO | Premium:Rs.{entry_premium} | Target:Rs.{target} | SL:Rs.{sl}")
    try:
        ref = f"OCO{ist_now().strftime('%H%M%S')}"
        res = groww.create_smart_order(
            smart_order_type=groww.SMART_ORDER_TYPE_OCO, reference_id=ref,
            segment=groww.SEGMENT_FNO, trading_symbol=symbol, quantity=qty,
            product_type=groww.PRODUCT_MIS, exchange=groww.EXCHANGE_NSE,
            duration=groww.VALIDITY_DAY, net_position_quantity=qty,
            transaction_type=groww.TRANSACTION_TYPE_SELL,
            target   ={"trigger_price":fmt(round(target*0.99,1)), "order_type":groww.ORDER_TYPE_LIMIT, "price":fmt(target)},
            stop_loss={"trigger_price":fmt(round(sl*1.01,1)),     "order_type":groww.ORDER_TYPE_STOP_LOSS_MARKET, "price":None})
        sid = res.get("smart_order_id", "N/A")
        logging.info(f"OCO PLACED | ID:{sid} | Target:Rs.{target} | SL:Rs.{sl}")
        return sid, target, sl
    except Exception as e:
        logging.error(f"OCO FAILED: {e}")
        logging.warning(f"ACTION NEEDED: Manual SL=Rs.{sl} Target=Rs.{target}")
        return None, target, sl

def cancel_and_squareoff(groww, state):
    logging.info("EOD: cancelling OCO + squaring off")
    try:
        now = ist_now()
        res = groww.get_smart_order_list(
            segment=groww.SEGMENT_FNO, smart_order_type=groww.SMART_ORDER_TYPE_OCO,
            status=groww.SMART_ORDER_STATUS_ACTIVE, page=0, page_size=50,
            start_date_time=now.replace(hour=9,minute=0).strftime("%Y-%m-%dT%H:%M:%S"),
            end_date_time=now.strftime("%Y-%m-%dT%H:%M:%S"))
        for o in res.get("orders", []):
            sid = o.get("smart_order_id")
            if sid and "NIFTY" in o.get("trading_symbol", ""):
                groww.cancel_smart_order(smart_order_id=sid, segment=groww.SEGMENT_FNO,
                    smart_order_type=groww.SMART_ORDER_TYPE_OCO)
                logging.info(f"Cancelled OCO: {sid}")
    except Exception as e: logging.error(f"OCO cancel error: {e}")
    try:
        positions = groww.get_positions_for_user(segment=groww.SEGMENT_FNO).get("positions", [])
        for pos in positions:
            sym = pos.get("trading_symbol", ""); qty = int(pos.get("quantity", 0))
            if qty != 0 and "NIFTY" in sym:
                side = groww.TRANSACTION_TYPE_SELL if qty > 0 else groww.TRANSACTION_TYPE_BUY
                res  = groww.place_order(trading_symbol=sym, quantity=abs(qty),
                    validity=groww.VALIDITY_DAY, exchange=groww.EXCHANGE_NSE,
                    segment=groww.SEGMENT_FNO, product=groww.PRODUCT_MIS,
                    order_type=groww.ORDER_TYPE_MARKET, transaction_type=side)
                logging.info(f"Closed: {sym} Qty:{abs(qty)} ID:{res.get('groww_order_id')}")
    except Exception as e: logging.error(f"Square-off error: {e}")
    trades = state.get("trades", [])
    logging.info(f"DAILY SUMMARY | Trades:{len(trades)}/{MAX_TRADES_DAY} | P&L:Rs.{state.get('daily_pnl_rupees',0):+.0f}")
    for i,t in enumerate(trades,1):
        logging.info(f"  {i}. {t.get('signal')} {t.get('confidence')} | {t.get('symbol')} | Rs.{t.get('entry_premium','?')} T:Rs.{t.get('target','?')} SL:Rs.{t.get('sl','?')}")

# ═════════════════════════════════════════════════════════════
#  SECTION 9 — MAIN
# ═════════════════════════════════════════════════════════════

def main():
    now   = ist_now()
    state = load_state()
    logging.info(f"Run: {now.strftime('%Y-%m-%d %H:%M:%S')} IST | Trades:{state['trade_count']}/{MAX_TRADES_DAY} | P&L:Rs.{state.get('daily_pnl_rupees',0):+.0f}")

    if is_squareoff_time():
        groww = login(); cancel_and_squareoff(groww, state); return

    if not is_market_hours():
        logging.info("Outside market hours. Skipping."); return

    groww   = login()
    candles = fetch_candles(groww)
    result  = compute_signals(candles)
    signal  = result["signal"]
    confidence = result["confidence"]
    d       = result.get("details", {})

    # Print dashboard
    logging.info("=" * 55)
    logging.info(f"  Signal:{signal} | Conf:{confidence} | Score:{result.get('score','N/A')}")
    logging.info(f"  Long:{d.get('long_score','N/A')} ({d.get('long_pred','N/A')}) | Short:{d.get('short_score','N/A')} ({d.get('short_pred','N/A')})")
    logging.info(f"  Close:{d.get('close','N/A')} | VWAP:{d.get('vwap','N/A')} ({d.get('vwap_pos','N/A')}) | Ext:{d.get('vwap_ext','N/A')}")
    logging.info(f"  Trend:{d.get('trend','N/A')} | ATR:{d.get('atr_state','N/A')} | RSI:{d.get('rsi','N/A')} | ADX:{d.get('adx','N/A')}")
    logging.info(f"  MACD:{d.get('macd_hist','N/A')} | StochK:{d.get('stoch_k','N/A')} | RVOL:{d.get('rvol','N/A')}")
    logging.info(f"  BullSFP:{d.get('bull_sfp','N/A')} | BearSFP:{d.get('bear_sfp','N/A')} | BullEng:{d.get('bull_engulf','N/A')} | BearEng:{d.get('bear_engulf','N/A')}")
    logging.info(f"  NearDemand:{d.get('near_demand','N/A')} | NearSupply:{d.get('near_supply','N/A')}")
    if d.get("reason"): logging.info(f"  Reason: {d['reason']}")
    logging.info("=" * 55)

    if signal == "NO_TRADE": logging.info("No signal."); return
    if HIGH_ONLY and confidence != "HIGH": logging.info(f"{confidence} skipped (HIGH_ONLY)"); return

    risk = RiskManager(state)
    ok, reason = risk.check_can_trade(groww)
    if not ok: logging.warning(f"BLOCKED: {reason}"); return
    logging.info(f"Risk OK: {reason}")

    opt_type = "CE" if "CE" in signal else "PE"
    txn      = groww.TRANSACTION_TYPE_BUY

    q      = groww.get_quote(exchange=groww.EXCHANGE_NSE, segment=groww.SEGMENT_CASH, trading_symbol="NIFTY")
    ltp    = float(q["last_price"])
    strike = get_atm_strike(ltp)
    symbol = build_symbol(strike, opt_type)
    qty    = LOT_SIZE * LOTS_TO_TRADE

    spread_ok, spread_msg = risk.check_spread(groww, symbol)
    if not spread_ok: logging.warning(f"BLOCKED: {spread_msg}"); return
    logging.info(spread_msg)

    option_ltp_pre = get_option_ltp(groww, symbol) or 0
    prem_ok, prem_msg = risk.check_premium_range(option_ltp_pre)
    if not prem_ok: logging.warning(f"BLOCKED: {prem_msg}"); return
    logging.info(prem_msg)

    if option_ltp_pre > 0:
        cap_ok, cap_msg = risk.check_capital_exposure(option_ltp_pre, qty)
        if not cap_ok: logging.warning(f"BLOCKED: {cap_msg}"); return
        logging.info(cap_msg)

    adjusted_sl, expected_loss, sl_msg = risk.calc_adjusted_sl(option_ltp_pre, qty)
    logging.info(f"{sl_msg} | Nifty:{ltp} Strike:{strike} Symbol:{symbol} Qty:{qty}")

    oid, status = place_entry_order(groww, symbol, qty, txn)
    if not oid: logging.error("Entry FAILED"); return

    time.sleep(1)
    entry_premium = get_option_ltp(groww, symbol)
    smart_id, target_price, sl_price = place_oco_order(
        groww, symbol, qty, entry_premium,
        custom_sl=adjusted_sl if option_ltp_pre > 0 else None)

    state["trade_count"] += 1
    state["trades"].append({
        "signal":signal, "symbol":symbol, "qty":qty,
        "entry_id":str(oid), "smart_id":str(smart_id) if smart_id else None,
        "entry_premium":entry_premium, "target":target_price, "sl":sl_price,
        "ltp":ltp, "strike":strike, "confidence":confidence,
        "score":result["score"], "time":now.strftime("%Y-%m-%d %H:%M:%S")})
    save_state(state)
    logging.info(f"TRADE DONE | {signal} {confidence} ({result['score']}/7) | {symbol} | Premium:Rs.{entry_premium} | T:Rs.{target_price} SL:Rs.{sl_price} | Entry:{oid} OCO:{smart_id} | {state['trade_count']}/{MAX_TRADES_DAY}")

if __name__ == "__main__":
    main()
