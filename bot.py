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

GROWW_TOTP_TOKEN  = "YOUR_TOTP_TOKEN_HERE"
GROWW_TOTP_SECRET = "YOUR_TOTP_SECRET_HERE"

LOT_SIZE         = 65
LOTS_TO_TRADE    = 1
HIGH_ONLY        = False

TARGET_MULT      = 1.5
SL_MULT          = 0.5
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

EMA1_LEN=9; EMA2_LEN=20; EMA4_LEN=45
RSI_LEN=14; ADX_LEN=14; ATR_LEN=14
ROC_LEN=10; ROC_SMOOTH=3; VOL_MULT=1.2
RSI_OB=70;  RSI_OS=30;   ADX_THRESH=20
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

def safe(s,idx=-1):
    try: return s[idx]
    except: return None

# ═════════════════════════════════════════════════════════════
#  SECTION 3 — SIGNAL ENGINE
# ═════════════════════════════════════════════════════════════

def compute_signals(candles):
    if len(candles) < 50:
        return {"signal":"NO_TRADE","confidence":None,"score":0,
                "details":{"reason":f"Need more candles: {len(candles)}/50"}}
    opens  =[c["open"]   for c in candles]
    highs  =[c["high"]   for c in candles]
    lows   =[c["low"]    for c in candles]
    closes =[c["close"]  for c in candles]
    volumes=[c["volume"] for c in candles]
    ema9_s =calc_ema(closes,EMA1_LEN); ema20_s=calc_ema(closes,EMA2_LEN)
    ema45_s=calc_ema(closes,EMA4_LEN); vwap_s =calc_vwap(highs,lows,closes,volumes)
    rsi_s  =calc_rsi(closes,RSI_LEN);  atr_s  =calc_atr(highs,lows,closes,ATR_LEN)
    adx_s,_,_=calc_adx(highs,lows,closes,ADX_LEN)
    roc_s  =calc_roc(closes,ROC_LEN)
    roc_sm =calc_ema([v if v is not None else 0 for v in roc_s],ROC_SMOOTH)
    vol_sma=calc_sma(volumes,20); body_s=[abs(c-o) for c,o in zip(closes,opens)]
    avg_body=calc_sma(body_s,20)
    bull_c=[c>o for c,o in zip(closes,opens)]; bear_c=[c<o for c,o in zip(closes,opens)]
    ce_cross=crossover(ema9_s,ema20_s); pe_cross=crossunder(ema9_s,ema20_s)
    lc=safe(closes); le9=safe(ema9_s); le20=safe(ema20_s); le45=safe(ema45_s)
    lv=safe(vwap_s); lr=safe(rsi_s);  la=safe(atr_s);     ladx=safe(adx_s)
    lroc=safe(roc_sm); proc=safe(roc_sm,-2); lvol=safe(volumes); lvsma=safe(vol_sma)
    lbody=safe(body_s); labody=safe(avg_body)
    if None in (lc,le9,le20,lv,lr):
        return {"signal":"NO_TRADE","confidence":None,"score":0,"details":{"reason":"Indicators not ready"}}
    above_vwap=lc>lv; below_vwap=lc<lv
    bull_stack=le9>le20 and le20>(le45 or le20)
    bear_stack=le9<le20 and le20<(le45 or le20)
    e9_4ago=safe(ema9_s,-4) or le9
    slope_up=le9>e9_4ago; slope_down=le9<e9_4ago
    vol_spike=lvol is not None and lvsma is not None and lvol>lvsma*VOL_MULT
    bull_mom=lroc is not None and proc is not None and lroc>0 and lroc>proc
    bear_mom=lroc is not None and proc is not None and lroc<0 and lroc<proc
    ab=labody or 1; pb1=safe(body_s,-2) or 0; pb2=safe(body_s,-3) or 0
    accum_bull=(lbody or 0)>ab*1.4 and pb1<ab*0.6 and pb2<ab*0.6 and bull_c[-1]
    accum_bear=(lbody or 0)>ab*1.4 and pb1<ab*0.6 and pb2<ab*0.6 and bear_c[-1]
    ce_trigger=ce_cross[-1] or (le9>le20 and lc>le9 and closes[-2]<=(ema9_s[-2] or 0))
    pe_trigger=pe_cross[-1] or (le9<le20 and lc<le9 and closes[-2]>=(ema9_s[-2] or 0))
    rsi_bull_ok=(not USE_RSI) or lr<RSI_OB; rsi_bear_ok=(not USE_RSI) or lr>RSI_OS
    adx_ok=(not USE_ADX) or (ladx is not None and ladx>ADX_THRESH)
    vol_ok=(not USE_VOL) or vol_spike
    ce_score=sum([int(above_vwap),int(bull_stack),int(slope_up),int(vol_spike),
                  int(bull_c[-1]),int(lr>50 if lr else False),int(ce_cross[-1]),
                  int(bull_mom),int(accum_bull)])
    pe_score=sum([int(below_vwap),int(bear_stack),int(slope_down),int(vol_spike),
                  int(bear_c[-1]),int(lr<50 if lr else False),int(pe_cross[-1]),
                  int(bear_mom),int(accum_bear)])
    ce_high=ce_score>=6; ce_med=4<=ce_score<6
    pe_high=pe_score>=6; pe_med=4<=pe_score<6
    if ce_trigger and (ce_high or ce_med) and rsi_bull_ok and adx_ok and vol_ok:
        signal,confidence,score="CE_BUY",("HIGH" if ce_high else "MED"),ce_score
    elif pe_trigger and (pe_high or pe_med) and rsi_bear_ok and adx_ok and vol_ok:
        signal,confidence,score="PE_BUY",("HIGH" if pe_high else "MED"),pe_score
    else:
        signal,confidence,score="NO_TRADE",None,0
    mkt="Ranging"
    for j in range(len(highs)-1,3,-1):
        if all(highs[j]>highs[j-k] for k in range(1,5)): mkt="Trending Up"; break
        if all(lows[j]<lows[j-k]   for k in range(1,5)): mkt="Trending Down"; break
    return {"signal":signal,"confidence":confidence,"score":score,"details":{
        "close":round(lc,2),"ema9":round(le9,2),"ema20":round(le20,2),
        "vwap":round(lv,2),"rsi":round(lr,1),
        "adx":round(ladx,1) if ladx else "N/A",
        "vwap_position":"Above VWAP" if above_vwap else "Below VWAP",
        "ema_stack":"Bullish" if bull_stack else "Bearish" if bear_stack else "Mixed",
        "ema_slope":"Rising" if slope_up else "Falling",
        "vol_spike":"Yes" if vol_spike else "No",
        "last_candle":"Bullish" if bull_c[-1] else "Bearish",
        "market_structure":mkt,
        "ce_score":f"{ce_score}/9","pe_score":f"{pe_score}/9"}}

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
    logging.info(f"Signal:{signal} | Conf:{confidence} | CE:{d.get('ce_score','N/A')} PE:{d.get('pe_score','N/A')} | Close:{d.get('close','N/A')} RSI:{d.get('rsi','N/A')} ADX:{d.get('adx','N/A')}")
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
    logging.info(f"TRADE DONE | {signal} {confidence} ({result['score']}/9) | {symbol} | Premium:Rs.{entry_premium} | T:Rs.{target_price} SL:Rs.{sl_price} | Entry:{oid} OCO:{smart_id} | {state['trade_count']}/{MAX_TRADES_DAY}")

if __name__ == "__main__":
    main()
