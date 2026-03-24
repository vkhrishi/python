# ============================================================
#  OPTIONS SCALPER — VPS VERSION (Hetzner + Groww API)
#  Runs every 5 min via cron | Historical candles
# ============================================================

from growwapi import GrowwAPI
import datetime
import logging
import os
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
#  SECTION 1 — CONFIGURATION  (fill in your values)
# ═════════════════════════════════════════════════════════════

GROWW_TOTP_TOKEN  = "eyJraWQiOiJaTUtjVXciLCJhbGciOiJFUzI1NiJ9.eyJleHAiOjI1NjIwNzAwNjAsImlhdCI6MTc3MzY3MDA2MCwibmJmIjoxNzczNjcwMDYwLCJzdWIiOiJ7XCJ0b2tlblJlZklkXCI6XCJmYTIxZTUyMC1kNjMyLTRlYTQtOGE3NS0zMTdjZmY2YzEzNTBcIixcInZlbmRvckludGVncmF0aW9uS2V5XCI6XCJlMzFmZjIzYjA4NmI0MDZjODg3NGIyZjZkODQ5NTMxM1wiLFwidXNlckFjY291bnRJZFwiOlwiNjQ3NTk3YTItNTlmMC00MWQ2LTkyZjgtMGNjYzdkYTBkN2I2XCIsXCJkZXZpY2VJZFwiOlwiYzY2YmE0NmItMDlhNC01Zjk4LWI5NDMtZmMwNzQzZGNiMmZhXCIsXCJzZXNzaW9uSWRcIjpcIjMxZjMzODQ3LTMxN2ItNGFhMC04MGFiLTkzMGU4MzQxOGY4MlwiLFwiYWRkaXRpb25hbERhdGFcIjpcIno1NC9NZzltdjE2WXdmb0gvS0EwYkgyblRaQUhZYlRzeVhHdDk1ZzgxR1JSTkczdTlLa2pWZDNoWjU1ZStNZERhWXBOVi9UOUxIRmtQejFFQisybTdRPT1cIixcInJvbGVcIjpcImF1dGgtdG90cFwiLFwic291cmNlSXBBZGRyZXNzXCI6XCIyNDAxOjQ5MDA6YzkwODphNDE3OjQ5YWQ6ZTA1MzphNWIzOjJhOGYsMTcyLjY5LjEyOS4xOTksMzUuMjQxLjIzLjEyM1wiLFwidHdvRmFFeHBpcnlUc1wiOjI1NjIwNzAwNjAxMTMsXCJ2ZW5kb3JOYW1lXCI6XCJncm93d0FwaVwifSIsImlzcyI6ImFwZXgtYXV0aC1wcm9kLWFwcCJ9.NW_6x92tZNRbyYsGtw7yOTUcSAyh0RZcA5rMhwHlczoMF45_cbZKbtobadvKkzuBkPePNU2ETU5TPnwfJcONkw"
GROWW_TOTP_SECRET = "M52LDHMGZVUDO5VCSFTKAGZUJHXWSSSY"

LOT_SIZE         = 65
LOTS_TO_TRADE    = 1
HIGH_ONLY        = True       # ↑ only HIGH-confluence signals trade

TARGET_MULT      = 2.0       # ↑ from 1.5 — better R:R per Pine-script 2× target
SL_MULT          = 0.4       # ↓ from 0.5 — tighter SL
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

EMA1_LEN=9; EMA2_LEN=21; EMA3_LEN=55; EMA4_LEN=144   # EMA ribbon (Pine: 9/21/55/144)
RSI_LEN=14; ADX_LEN=14; ATR_LEN=14
ROC_LEN=10; ROC_SMOOTH=3; VOL_MULT=1.2
RSI_OB=70;  RSI_OS=30;   ADX_THRESH=25               # ↑ ADX threshold: 20→25 (strong trend only)
USE_RSI=True; USE_ADX=True; USE_VOL=True

STATE_FILE  = "/root/scalper/state.json"
TOKEN_FILE  = "/root/scalper/token.json"
CANDLE_FILE = "/root/scalper/candles.json"

# ═════════════════════════════════════════════════════════════
#  SECTION 2 — INDICATORS
# ═════════════════════════════════════════════════════════════

def calc_ema(data, period):
    if len(data) < period: return [None]*len(data)
    k = 2/(period+1)
    result = [None]*(period-1)
    result.append(sum(data[:period])/period)
    for price in data[period:]:
        result.append(price*k + result[-1]*(1-k))
    return result

def calc_sma(data, period):
    return [None if i < period-1 else sum(data[i-period+1:i+1])/period
            for i in range(len(data))]

def calc_rma(data, period):
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
    ag,al  = calc_rma(gains,period), calc_rma(losses,period)
    return [None if g is None or l is None else (100.0 if l==0 else 100-100/(1+g/l))
            for g,l in zip(ag,al)]

def calc_atr(highs, lows, closes, period=14):
    tr = [None]+[max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1]))
                 for i in range(1,len(closes))]
    return calc_rma(tr, period)

def calc_adx(highs, lows, closes, period=14):
    plus_dm  = [None]+[(highs[i]-highs[i-1]) if (highs[i]-highs[i-1])>(lows[i-1]-lows[i]) and (highs[i]-highs[i-1])>0 else 0.0 for i in range(1,len(closes))]
    minus_dm = [None]+[(lows[i-1]-lows[i]) if (lows[i-1]-lows[i])>(highs[i]-highs[i-1]) and (lows[i-1]-lows[i])>0 else 0.0 for i in range(1,len(closes))]
    tr       = [None]+[max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])) for i in range(1,len(closes))]
    tr_s=calc_rma(tr,period); pdm_s=calc_rma(plus_dm,period); mdm_s=calc_rma(minus_dm,period)
    pdi,mdi,dx=[],[],[]
    for ts,ps,ms in zip(tr_s,pdm_s,mdm_s):
        if None in (ts,ps,ms) or ts==0:
            pdi.append(None); mdi.append(None); dx.append(None)
        else:
            p=100*ps/ts; m=100*ms/ts
            pdi.append(p); mdi.append(m)
            dx.append(100*abs(p-m)/(p+m) if (p+m)!=0 else 0)
    return calc_rma(dx,period), pdi, mdi

def calc_roc(closes, period=10):
    result = [None]*period
    for i in range(period,len(closes)):
        prev = closes[i-period]
        result.append((closes[i]-prev)/prev*100 if prev!=0 else 0.0)
    return result

def calc_vwap(highs, lows, closes, volumes):
    result,cpv,cv=[],0.0,0.0
    for h,l,c,v in zip(highs,lows,closes,volumes):
        cpv+=(h+l+c)/3*v; cv+=v
        result.append(cpv/cv if cv>0 else c)
    return result

def crossover(a,b):
    result=[False]
    for i in range(1,len(a)):
        a0,a1,b0,b1=a[i-1],a[i],b[i-1],b[i]
        result.append(False if None in (a0,a1,b0,b1) else a0<=b0 and a1>b1)
    return result

def crossunder(a,b):
    result=[False]
    for i in range(1,len(a)):
        a0,a1,b0,b1=a[i-1],a[i],b[i-1],b[i]
        result.append(False if None in (a0,a1,b0,b1) else a0>=b0 and a1<b1)
    return result

def calc_macd(closes, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    macd_line = [None if f is None or s is None else f - s for f, s in zip(ema_fast, ema_slow)]
    sig_line  = calc_ema([v if v is not None else 0.0 for v in macd_line], signal)
    histogram = [None if m is None or s is None else m - s for m, s in zip(macd_line, sig_line)]
    return macd_line, sig_line, histogram

def calc_stoch(highs, lows, closes, k_period=14, d_period=3):
    k_vals = []
    for i in range(len(closes)):
        if i < k_period - 1:
            k_vals.append(None)
        else:
            hh = max(highs[i - k_period + 1 : i + 1])
            ll = min(lows[i  - k_period + 1 : i + 1])
            k_vals.append((closes[i] - ll) / (hh - ll) * 100 if hh != ll else 50.0)
    d_vals = calc_sma([v if v is not None else 0.0 for v in k_vals], d_period)
    return k_vals, d_vals

def safe(s,idx=-1):
    try: return s[idx]
    except: return None

# ═════════════════════════════════════════════════════════════
#  SECTION 3 — SIGNAL ENGINE
# ═════════════════════════════════════════════════════════════

def compute_signals(candles):
    if len(candles) < 60:
        return {"signal":"NO_TRADE","confidence":None,"score":0,
                "details":{"reason":f"Need more candles: {len(candles)}/60"}}
    opens  =[c["open"]   for c in candles]
    highs  =[c["high"]   for c in candles]
    lows   =[c["low"]    for c in candles]
    closes =[c["close"]  for c in candles]
    volumes=[c["volume"] for c in candles]

    # ── EMA ribbon (9 / 21 / 55 / 144)
    ema9_s  = calc_ema(closes, EMA1_LEN)
    ema21_s = calc_ema(closes, EMA2_LEN)
    ema55_s = calc_ema(closes, EMA3_LEN)
    ema144_s= calc_ema(closes, EMA4_LEN)
    vwap_s  = calc_vwap(highs, lows, closes, volumes)

    # ── MACD (12/26/9)
    _, _, macd_hist = calc_macd(closes)

    # ── RSI-14
    rsi_s = calc_rsi(closes, RSI_LEN)

    # ── Stochastic K/D
    stoch_k_s, stoch_d_s = calc_stoch(highs, lows, closes)

    # ── ATR / ADX
    atr_s          = calc_atr(highs, lows, closes, ATR_LEN)
    adx_s, pdi_s, mdi_s = calc_adx(highs, lows, closes, ADX_LEN)

    # ── RVOL
    vol_sma = calc_sma(volumes, 20)

    # ── CVD: cumulative volume delta over last 30 bars (Pine: deltaVol sum)
    cvd = sum(v if c > o else (-v if c < o else 0.0)
              for c, o, v in zip(closes[-30:], opens[-30:], volumes[-30:]))

    # ── Scalar current values
    lc     = safe(closes)
    le9    = safe(ema9_s)
    le21   = safe(ema21_s)
    le55   = safe(ema55_s)
    le144  = safe(ema144_s)
    lv     = safe(vwap_s)
    lr     = safe(rsi_s)
    la     = safe(atr_s)
    ladx   = safe(adx_s)
    lmacd  = safe(macd_hist)
    lk     = safe(stoch_k_s)
    ld     = safe(stoch_d_s)
    lvol   = safe(volumes)
    lvsma  = safe(vol_sma)

    if None in (lc, le9, le21, lv, lr):
        return {"signal":"NO_TRADE","confidence":None,"score":0,
                "details":{"reason":"Indicators not ready"}}

    rvol = lvol / lvsma if (lvol and lvsma and lvsma > 0) else 1.0

    # ── 7 confluence components (mirrors Pine-Script dashboard) ────────────
    # 1. MACD histogram direction
    macd_bull = lmacd is not None and lmacd > 0
    macd_bear = lmacd is not None and lmacd < 0
    # 2. RSI side
    rsi_bull  = lr >= 50
    rsi_bear  = lr <  50
    # 3. Stochastic K vs D
    stoch_bull = lk is not None and ld is not None and lk > ld
    stoch_bear = lk is not None and ld is not None and lk < ld
    # 4. Relative volume ≥ 1× (Vol)
    vol_bull = rvol >= 1.0
    vol_bear = rvol >= 1.0          # volume is direction-neutral — high vol favours both
    # 5. CVD delta
    delta_bull = cvd > 0
    delta_bear = cvd < 0
    # 6. Full EMA ribbon trend alignment
    trend_bull = (le55 is not None and le144 is not None and
                  lc > le21 and le21 > le55 and le55 > le144)
    trend_bear = (le55 is not None and le144 is not None and
                  lc < le21 and le21 < le55 and le55 < le144)
    # 7. ADX strength
    adx_strong = ladx is not None and ladx >= ADX_THRESH

    long_score  = sum([int(macd_bull), int(rsi_bull),  int(stoch_bull),
                       int(vol_bull),  int(delta_bull), int(trend_bull), int(adx_strong)])
    short_score = sum([int(macd_bear), int(rsi_bear),  int(stoch_bear),
                       int(vol_bear),  int(delta_bear), int(trend_bear), int(adx_strong)])

    # ── SFP bonus: wick-trap pattern adds +1 when delta agrees ─────────────
    sfp_bull = sfp_bear = False
    if len(highs) >= 21:
        hh20 = max(highs[-21:-1])
        ll20 = min(lows[-21:-1])
        sfp_bull = lows[-1]  < ll20 and closes[-1] > ll20   # bear-trap → bullish reversal
        sfp_bear = highs[-1] > hh20 and closes[-1] < hh20   # bull-trap → bearish reversal
    if sfp_bull and delta_bull: long_score  = min(long_score  + 1, 7)
    if sfp_bear and delta_bear: short_score = min(short_score + 1, 7)

    # ── EMA trigger (crossover OR pullback-continuation) ───────────────────
    prev_e9  = safe(ema9_s,  -2)
    prev_e21 = safe(ema21_s, -2)
    ce_cross = (prev_e9 is not None and prev_e21 is not None and
                prev_e9 <= prev_e21 and le9 > le21)
    pe_cross = (prev_e9 is not None and prev_e21 is not None and
                prev_e9 >= prev_e21 and le9 < le21)
    ce_cont  = le9 > le21 and lc > le9  and closes[-2] <= (prev_e9 or lc)
    pe_cont  = le9 < le21 and lc < le9  and closes[-2] >= (prev_e9 or lc)

    ce_trigger = ce_cross or ce_cont or (sfp_bull and long_score  >= 3)
    pe_trigger = pe_cross or pe_cont or (sfp_bear and short_score >= 3)

    # ── Confidence gates ────────────────────────────────────────────────────
    rsi_bull_ok  = (not USE_RSI) or lr < RSI_OB
    rsi_bear_ok  = (not USE_RSI) or lr > RSI_OS
    adx_ok       = (not USE_ADX) or adx_strong
    vol_ok       = (not USE_VOL) or vol_bull

    ce_conf  = "HIGH" if long_score  >= 5 else ("MED" if long_score  >= 3 else None)
    pe_conf  = "HIGH" if short_score >= 5 else ("MED" if short_score >= 3 else None)

    if   ce_trigger and ce_conf and rsi_bull_ok and adx_ok and vol_ok:
        signal, confidence, score = "CE_BUY", ce_conf, long_score
    elif pe_trigger and pe_conf and rsi_bear_ok and adx_ok and vol_ok:
        signal, confidence, score = "PE_BUY", pe_conf, short_score
    else:
        signal, confidence, score = "NO_TRADE", None, 0

    mkt = "Ranging"
    for j in range(len(highs)-1, 3, -1):
        if all(highs[j] > highs[j-k] for k in range(1, 5)): mkt = "Trending Up";   break
        if all(lows[j]  < lows[j-k]  for k in range(1, 5)): mkt = "Trending Down"; break

    return {"signal":signal,"confidence":confidence,"score":score,"details":{
        "close":round(lc,2),"ema9":round(le9,2),"ema21":round(le21,2),
        "vwap":round(lv,2),"rsi":round(lr,1),
        "adx":round(ladx,1) if ladx else "N/A",
        "macd_hist":round(lmacd,4) if lmacd else "N/A",
        "stoch_k":round(lk,1) if lk else "N/A",
        "rvol":round(rvol,2),
        "cvd_sign":"Bull" if delta_bull else "Bear",
        "trend":"Bull" if trend_bull else "Bear" if trend_bear else "Side",
        "sfp_bull":sfp_bull,"sfp_bear":sfp_bear,
        "vwap_position":"Above VWAP" if lc > lv else "Below VWAP",
        "ema_stack":"Bullish" if trend_bull else "Bearish" if trend_bear else "Mixed",
        "market_structure":mkt,
        "long_score":f"{long_score}/7","short_score":f"{short_score}/7"}}

# ═════════════════════════════════════════════════════════════
#  SECTION 4 — RISK MANAGER
# ═════════════════════════════════════════════════════════════

class RiskManager:
    def __init__(self, state): self.state = state

    def check_can_trade(self, groww):
        for passed,reason in [
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
        now=ist_now()
        cutoff=now.replace(hour=9,minute=15,second=0,microsecond=0)+datetime.timedelta(minutes=OPENING_RANGE_MINUTES)
        if now<cutoff: return False,f"OPENING RANGE: {int((cutoff-now).total_seconds()/60)} min left"
        return True,"Opening range passed"

    def _check_no_new_trade_time(self):
        now=ist_now()
        cutoff=now.replace(hour=NO_NEW_TRADE_HOUR,minute=NO_NEW_TRADE_MIN,second=0,microsecond=0)
        if now>=cutoff: return False,f"TIME: Past {NO_NEW_TRADE_HOUR}:{NO_NEW_TRADE_MIN:02d} IST"
        return True,"Time window OK"

    def _check_near_squareoff(self):
        now=ist_now()
        sq=now.replace(hour=SQUAREOFF_HOUR,minute=SQUAREOFF_MIN,second=0,microsecond=0)
        mins=(sq-now).total_seconds()/60
        if 0<mins<NO_TRADE_BEFORE_SQ_MINS: return False,f"NEAR SQUAREOFF: {int(mins)} min left"
        return True,"Square-off buffer OK"

    def _check_max_trades(self):
        c=self.state.get("trade_count",0)
        return (False,f"MAX TRADES: {c}/{MAX_TRADES_DAY}") if c>=MAX_TRADES_DAY else (True,f"Trades {c}/{MAX_TRADES_DAY}")

    def _check_daily_loss(self):
        pnl=self.state.get("daily_pnl_rupees",0)
        return (False,f"MAX DAILY LOSS: Rs.{pnl}") if pnl<=-MAX_DAILY_LOSS_RUPEES else (True,f"Day P&L Rs.{pnl:+.0f}")

    def _check_consecutive_losses(self):
        c=self.state.get("consecutive_losses",0)
        return (False,f"CONSECUTIVE LOSSES: {c}/{MAX_CONSECUTIVE_LOSSES}") if c>=MAX_CONSECUTIVE_LOSSES else (True,f"Loss streak {c}/{MAX_CONSECUTIVE_LOSSES}")

    def _check_open_positions(self, groww):
        try:
            res=groww.get_positions_for_user(segment=groww.SEGMENT_FNO)
            open_pos=[p for p in res.get("positions",[])
                      if int(p.get("quantity",0))!=0 and "NIFTY" in p.get("trading_symbol","")]
            if len(open_pos)>=MAX_OPEN_POSITIONS:
                return False,f"OPEN POSITION LOCK: {[p['trading_symbol'] for p in open_pos]}"
            return True,f"Positions {len(open_pos)}/{MAX_OPEN_POSITIONS}"
        except Exception as e: return False,f"POSITION CHECK FAILED: {e}"

    def _check_cooldown(self):
        last=self.state.get("last_exit_time")
        if not last: return True,"No cooldown"
        elapsed=(ist_now()-datetime.datetime.strptime(last,"%Y-%m-%d %H:%M:%S")).total_seconds()/60
        if elapsed<COOLDOWN_MINUTES: return False,f"COOLDOWN: {int(COOLDOWN_MINUTES-elapsed)} min remaining"
        return True,f"Cooldown OK ({int(elapsed)} min ago)"

    def check_premium_range(self, ltp):
        if not ltp or ltp<=0: return False,"PREMIUM: Could not fetch"
        if ltp<MIN_OPTION_PREMIUM: return False,f"PREMIUM TOO LOW: Rs.{ltp}"
        if ltp>MAX_OPTION_PREMIUM: return False,f"PREMIUM TOO HIGH: Rs.{ltp}"
        return True,f"Premium OK: Rs.{ltp}"

    def check_capital_exposure(self, ltp, qty):
        exposure=ltp*qty; max_exp=CAPITAL_RUPEES*MAX_CAPITAL_EXPOSURE_PCT/100
        pct=exposure/CAPITAL_RUPEES*100
        if exposure>max_exp: return False,f"EXPOSURE: Rs.{exposure:.0f} ({pct:.1f}%) > max"
        return True,f"Exposure OK: Rs.{exposure:.0f} ({pct:.1f}%)"

    def calc_adjusted_sl(self, ltp, qty):
        sl_mult=round(ltp*SL_MULT,1)
        sl_cap=round(max(ltp-MAX_LOSS_PER_TRADE_RUPEES/qty,0.5),1)
        final=max(sl_mult,sl_cap); loss=(ltp-final)*qty
        note="SL TIGHTENED" if final>sl_mult else "SL OK"
        return final,loss,f"{note}: Rs.{final} | Risk Rs.{loss:.0f}"

    def check_spread(self, groww, symbol):
        try:
            q=groww.get_quote(exchange=groww.EXCHANGE_NSE,
                               segment=groww.SEGMENT_FNO,
                               trading_symbol=symbol)
            bid=float(q.get("bid_price") or 0)
            ask=float(q.get("offer_price") or 0)
            ltp=float(q.get("last_price") or 1)
            if bid<=0 or ask<=0: return True,"Spread skipped (no bid/ask)"
            spread_pct=(ask-bid)/ltp*100
            if spread_pct>MAX_SPREAD_PCT: return False,f"SPREAD: {spread_pct:.1f}% > {MAX_SPREAD_PCT}%"
            return True,f"Spread OK: {spread_pct:.1f}%"
        except Exception as e: return True,f"Spread skipped: {e}"

    def record_exit(self, pnl):
        self.state["daily_pnl_rupees"]=self.state.get("daily_pnl_rupees",0)+pnl
        self.state["consecutive_losses"]=(self.state.get("consecutive_losses",0)+1 if pnl<0 else 0)
        self.state["last_exit_time"]=ist_now().strftime("%Y-%m-%d %H:%M:%S")

# ═════════════════════════════════════════════════════════════
#  SECTION 5 — UTILITIES
# ═════════════════════════════════════════════════════════════

def ist_now():
    return datetime.datetime.utcnow()+datetime.timedelta(hours=5,minutes=30)

def is_market_hours():
    now=ist_now()
    return (now.replace(hour=9,minute=15,second=0,microsecond=0)<=now<=
            now.replace(hour=SQUAREOFF_HOUR,minute=SQUAREOFF_MIN,second=0,microsecond=0))

def is_squareoff_time():
    now=ist_now()
    return now.hour>SQUAREOFF_HOUR or (now.hour==SQUAREOFF_HOUR and now.minute>=SQUAREOFF_MIN)

def get_atm_strike(ltp,step=50):
    return int(round(ltp/step)*step)

def get_expiry_str():
    today=ist_now().date(); days=(1-today.weekday())%7
    if days==0: days=7
    return (today+datetime.timedelta(days=days)).strftime("%y%m%d")

def build_symbol(strike,opt_type):
    return f"NIFTY{get_expiry_str()}{strike}{opt_type}"

def fmt(p): return f"{p:.2f}"

def load_state():
    today=ist_now().strftime("%Y-%m-%d")
    try:
        with open(STATE_FILE) as f:
            data=json.load(f)
            if data.get("date")==today: return data
    except: pass
    return {"date":today,"trade_count":0,"trades":[],
            "daily_pnl_rupees":0.0,"consecutive_losses":0,"last_exit_time":None}

def save_state(state):
    with open(STATE_FILE,"w") as f: json.dump(state,f,indent=2)

# ═════════════════════════════════════════════════════════════
#  SECTION 6 — LOGIN (token cached to file — no repeat TOTP)
# ═════════════════════════════════════════════════════════════

def login():
    try:
        with open(TOKEN_FILE) as f:
            data=json.load(f)
            if data.get("date")==ist_now().strftime("%Y-%m-%d") and data.get("token"):
                groww=GrowwAPI(data["token"])
                logging.info("Groww login OK (cached token)")
                return groww
    except: pass
    logging.info("Generating fresh TOTP token...")
    totp_code=pyotp.TOTP(GROWW_TOTP_SECRET).now()
    access_token=GrowwAPI.get_access_token(api_key=GROWW_TOTP_TOKEN, totp=totp_code)
    groww=GrowwAPI(access_token)
    with open(TOKEN_FILE,"w") as f:
        json.dump({"date":ist_now().strftime("%Y-%m-%d"),"token":access_token},f)
    logging.info("Groww login OK (fresh token cached)")
    return groww

# ═════════════════════════════════════════════════════════════
#  SECTION 7 — FETCH CANDLES
# ═════════════════════════════════════════════════════════════

def fetch_candles(groww):
    now=ist_now()
    end_dt=(now).strftime("%Y-%m-%d %H:%M:%S")
    start_dt=(now-datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")

    # Try historical candles (VPS has full internet access)
    try:
        res=groww.get_historical_candles(
            groww.EXCHANGE_NSE, groww.SEGMENT_CASH, "NIFTY",
            start_dt, end_dt, groww.CANDLE_INTERVAL_MIN_5)
        raw=res.get("candles",[])
        if raw:
            candles=[{"open":float(c[1]),"high":float(c[2]),
                      "low":float(c[3]),"close":float(c[4]),
                      "volume":float(c[5]) if len(c)>5 and c[5] else 0.0}
                     for c in raw]
            logging.info(f"Historical candles: {len(candles)} fetched")
            return candles
    except Exception as e:
        logging.warning(f"Historical candles failed: {e} — using live quote cache")

    # Fallback: build cache from live quotes
    try:
        q=groww.get_quote(exchange=groww.EXCHANGE_NSE,
                           segment=groww.SEGMENT_CASH,
                           trading_symbol="NIFTY")
        ltp=float(q["last_price"])
        ohlc=q.get("ohlc",{})
        open_=float(ohlc.get("open",ltp))
        high =float(ohlc.get("high",ltp))
        low  =float(ohlc.get("low", ltp))
        vol  =float(q.get("volume") or 0)
    except Exception as e:
        logging.error(f"Quote failed: {e}"); return []

    try:
        with open(CANDLE_FILE) as f: cache=json.load(f)
    except: cache={"date":"","candles":[]}

    today=ist_now().strftime("%Y-%m-%d")
    if cache.get("date")!=today: cache={"date":today,"candles":[]}
    cache["candles"].append({"open":open_,"high":high,"low":low,"close":ltp,"volume":vol})
    cache["candles"]=cache["candles"][-150:]
    with open(CANDLE_FILE,"w") as f: json.dump(cache,f)
    count=len(cache["candles"])
    logging.info(f"Live cache: {count} candles ({'READY' if count>=50 else f'need {50-count} more'})")
    return cache["candles"]

# ═════════════════════════════════════════════════════════════
#  SECTION 8 — ORDER MANAGEMENT
# ═════════════════════════════════════════════════════════════

def get_option_ltp(groww, symbol):
    try:
        q=groww.get_quote(exchange=groww.EXCHANGE_NSE,
                           segment=groww.SEGMENT_FNO,
                           trading_symbol=symbol)
        return float(q["last_price"])
    except Exception as e:
        logging.warning(f"Option LTP failed: {e}"); return None

def place_entry_order(groww, symbol, qty, txn):
    try:
        res=groww.place_order(
            trading_symbol=symbol, quantity=qty,
            validity=groww.VALIDITY_DAY, exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_FNO, product=groww.PRODUCT_MIS,
            order_type=groww.ORDER_TYPE_MARKET, transaction_type=txn,
            order_reference_id=f"ENTR{ist_now().strftime('%H%M%S')}")
        oid=res.get("groww_order_id","N/A")
        logging.info(f"ENTRY | {symbol} | {txn} | Qty:{qty} | ID:{oid}")
        return oid, res.get("order_status","N/A")
    except Exception as e:
        logging.error(f"ENTRY FAILED: {e}"); return None,str(e)

def place_oco_order(groww, symbol, qty, entry_premium, custom_sl=None):
    if not USE_SMART_ORDERS or not entry_premium or entry_premium<=0:
        return None,None,None
    target=round(max(entry_premium*TARGET_MULT,entry_premium+0.5),1)
    sl=custom_sl if custom_sl else round(max(entry_premium*SL_MULT,0.5),1)
    logging.info(f"OCO | Premium:Rs.{entry_premium} | Target:Rs.{target} | SL:Rs.{sl}")
    try:
        ref=f"OCO{ist_now().strftime('%H%M%S')}"
        res=groww.create_smart_order(
            smart_order_type=groww.SMART_ORDER_TYPE_OCO,
            reference_id=ref, segment=groww.SEGMENT_FNO,
            trading_symbol=symbol, quantity=qty,
            product_type=groww.PRODUCT_MIS, exchange=groww.EXCHANGE_NSE,
            duration=groww.VALIDITY_DAY, net_position_quantity=qty,
            transaction_type=groww.TRANSACTION_TYPE_SELL,
            target={"trigger_price":fmt(round(target*0.99,1)),
                    "order_type":groww.ORDER_TYPE_LIMIT,"price":fmt(target)},
            stop_loss={"trigger_price":fmt(round(sl*1.01,1)),
                       "order_type":groww.ORDER_TYPE_STOP_LOSS_MARKET,"price":None})
        sid=res.get("smart_order_id","N/A")
        logging.info(f"OCO PLACED | ID:{sid} | Target:Rs.{target} | SL:Rs.{sl}")
        return sid,target,sl
    except Exception as e:
        logging.error(f"OCO FAILED: {e}")
        logging.warning(f"ACTION NEEDED: Manual SL=Rs.{sl} Target=Rs.{target}")
        return None,target,sl

def cancel_and_squareoff(groww, state):
    logging.info("EOD: cancelling OCO + squaring off")
    try:
        now=ist_now()
        res=groww.get_smart_order_list(
            segment=groww.SEGMENT_FNO,
            smart_order_type=groww.SMART_ORDER_TYPE_OCO,
            status=groww.SMART_ORDER_STATUS_ACTIVE,
            page=0, page_size=50,
            start_date_time=now.replace(hour=9,minute=0).strftime("%Y-%m-%dT%H:%M:%S"),
            end_date_time=now.strftime("%Y-%m-%dT%H:%M:%S"))
        for o in res.get("orders",[]):
            sid=o.get("smart_order_id")
            if sid and "NIFTY" in o.get("trading_symbol",""):
                groww.cancel_smart_order(smart_order_id=sid,
                    segment=groww.SEGMENT_FNO,
                    smart_order_type=groww.SMART_ORDER_TYPE_OCO)
                logging.info(f"Cancelled OCO: {sid}")
    except Exception as e: logging.error(f"OCO cancel error: {e}")
    try:
        positions=groww.get_positions_for_user(
            segment=groww.SEGMENT_FNO).get("positions",[])
        for pos in positions:
            sym=pos.get("trading_symbol",""); qty=int(pos.get("quantity",0))
            if qty!=0 and "NIFTY" in sym:
                side=groww.TRANSACTION_TYPE_SELL if qty>0 else groww.TRANSACTION_TYPE_BUY
                res=groww.place_order(
                    trading_symbol=sym, quantity=abs(qty),
                    validity=groww.VALIDITY_DAY, exchange=groww.EXCHANGE_NSE,
                    segment=groww.SEGMENT_FNO, product=groww.PRODUCT_MIS,
                    order_type=groww.ORDER_TYPE_MARKET, transaction_type=side)
                logging.info(f"Closed: {sym} Qty:{abs(qty)} ID:{res.get('groww_order_id')}")
    except Exception as e: logging.error(f"Square-off error: {e}")
    trades=state.get("trades",[])
    logging.info(f"DAILY SUMMARY | Trades:{len(trades)}/{MAX_TRADES_DAY} | P&L:Rs.{state.get('daily_pnl_rupees',0):+.0f}")
    for i,t in enumerate(trades,1):
        logging.info(f"  {i}. {t.get('signal')} {t.get('confidence')} | {t.get('symbol')} | Rs.{t.get('entry_premium','?')} T:Rs.{t.get('target','?')} SL:Rs.{t.get('sl','?')}")

# ═════════════════════════════════════════════════════════════
#  SECTION 9 — MAIN
# ═════════════════════════════════════════════════════════════

def main():
    now=ist_now(); state=load_state()
    logging.info(f"Run: {now.strftime('%Y-%m-%d %H:%M:%S')} IST | Trades:{state['trade_count']}/{MAX_TRADES_DAY} | P&L:Rs.{state.get('daily_pnl_rupees',0):+.0f}")

    if is_squareoff_time():
        groww=login(); cancel_and_squareoff(groww,state); return

    if not is_market_hours():
        logging.info("Outside market hours. Skipping."); return

    groww=login(); candles=fetch_candles(groww)
    result=compute_signals(candles)
    signal=result["signal"]; confidence=result["confidence"]
    d=result.get("details",{})
    logging.info(f"Signal:{signal} | Conf:{confidence} | Long:{d.get('long_score','N/A')} Short:{d.get('short_score','N/A')} | Close:{d.get('close','N/A')} RSI:{d.get('rsi','N/A')} ADX:{d.get('adx','N/A')} MACD:{d.get('macd_hist','N/A')} Stoch:{d.get('stoch_k','N/A')} CVD:{d.get('cvd_sign','N/A')} RVOL:{d.get('rvol','N/A')} Trend:{d.get('trend','N/A')} SFP_B:{d.get('sfp_bull',False)}/{d.get('sfp_bear',False)}")
    if d.get("reason"): logging.info(f"Reason: {d['reason']}")

    if signal=="NO_TRADE": logging.info("No signal."); return
    if HIGH_ONLY and confidence!="HIGH": logging.info(f"{confidence} skipped"); return

    risk=RiskManager(state)
    ok,reason=risk.check_can_trade(groww)
    if not ok: logging.warning(f"BLOCKED: {reason}"); return
    logging.info(f"Risk OK: {reason}")

    opt_type="CE" if "CE" in signal else "PE"
    txn=groww.TRANSACTION_TYPE_BUY
    q=groww.get_quote(exchange=groww.EXCHANGE_NSE,
                       segment=groww.SEGMENT_CASH,
                       trading_symbol="NIFTY")
    ltp=float(q["last_price"]); strike=get_atm_strike(ltp)
    symbol=build_symbol(strike,opt_type); qty=LOT_SIZE*LOTS_TO_TRADE

    spread_ok,spread_msg=risk.check_spread(groww,symbol)
    if not spread_ok: logging.warning(f"BLOCKED: {spread_msg}"); return
    logging.info(spread_msg)

    option_ltp_pre=get_option_ltp(groww,symbol) or 0
    prem_ok,prem_msg=risk.check_premium_range(option_ltp_pre)
    if not prem_ok: logging.warning(f"BLOCKED: {prem_msg}"); return
    logging.info(prem_msg)

    if option_ltp_pre>0:
        cap_ok,cap_msg=risk.check_capital_exposure(option_ltp_pre,qty)
        if not cap_ok: logging.warning(f"BLOCKED: {cap_msg}"); return
        logging.info(cap_msg)

    adjusted_sl,expected_loss,sl_msg=risk.calc_adjusted_sl(option_ltp_pre,qty)
    logging.info(f"{sl_msg} | Nifty:{ltp} Strike:{strike} Symbol:{symbol} Qty:{qty}")

    oid,status=place_entry_order(groww,symbol,qty,txn)
    if not oid: logging.error("Entry FAILED"); return

    time.sleep(1)
    entry_premium=get_option_ltp(groww,symbol)
    smart_id,target_price,sl_price=place_oco_order(
        groww,symbol,qty,entry_premium,
        custom_sl=adjusted_sl if option_ltp_pre>0 else None)

    state["trade_count"]+=1
    state["trades"].append({
        "signal":signal,"symbol":symbol,"qty":qty,
        "entry_id":str(oid),"smart_id":str(smart_id) if smart_id else None,
        "entry_premium":entry_premium,"target":target_price,"sl":sl_price,
        "ltp":ltp,"strike":strike,"confidence":confidence,
        "score":result["score"],"time":now.strftime("%Y-%m-%d %H:%M:%S")})
    save_state(state)
    logging.info(f"TRADE DONE | {signal} {confidence} ({result['score']}/7) | {symbol} | Premium:Rs.{entry_premium} | T:Rs.{target_price} SL:Rs.{sl_price} | Entry:{oid} OCO:{smart_id} | {state['trade_count']}/{MAX_TRADES_DAY}")

if __name__ == "__main__":
    main()
