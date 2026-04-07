#!/usr/bin/env python3
"""
Debug script — discovers correct symbol format for Groww API
Save as: /root/scalper/debug.py
Run as:  python3 /root/scalper/debug.py
"""

from growwapi import GrowwAPI
import pyotp, os, json, datetime

# ── Load cached token
with open("/root/scalper/token.json") as f:
    t = json.load(f)
g = GrowwAPI(t["token"])

print("=" * 60)
print("  GROWW API DEBUG — Symbol & Method Discovery")
print("=" * 60)

# ── 1. List ALL available methods
methods = [m for m in dir(g) if not m.startswith("_")]
print("\n[1] ALL AVAILABLE METHODS:")
for m in methods:
    print(f"    {m}")

# ── 2. List all constants (EXCHANGE_, SEGMENT_, etc.)
print("\n[2] ALL CONSTANTS:")
for m in methods:
    val = getattr(g, m, None)
    if isinstance(val, (str, int, float)):
        print(f"    {m} = {val}")

# ── 3. Try Nifty index quote with every possible symbol
print("\n[3] NIFTY INDEX QUOTE — trying all symbol formats:")
nifty_symbols = [
    "NIFTY", "NIFTY 50", "Nifty 50", "NIFTY50",
    "NSE-NIFTY", "NIFTY-INDEX", "NIFTY INDEX",
    "Nifty", "NIFTY_50", "NIFTY-50"
]
segments = ["CASH"]
if hasattr(g, "SEGMENT_CASH"):
    segments.append(g.SEGMENT_CASH)
if hasattr(g, "SEGMENT_INDEX"):
    segments.append(g.SEGMENT_INDEX)
if hasattr(g, "SEGMENT_EQUITY"):
    segments.append(g.SEGMENT_EQUITY)
# deduplicate
segments = list(set(segments))

nifty_ltp = None
working_nifty_sym = None
working_nifty_seg = None

for seg in segments:
    for sym in nifty_symbols:
        try:
            q = g.get_quote(exchange="NSE", segment=seg, trading_symbol=sym)
            ltp = q.get("last_price", "N/A")
            print(f"    OK   | segment={seg:10s} | symbol={sym:15s} | LTP={ltp}")
            if ltp and float(ltp) > 0:
                nifty_ltp = float(ltp)
                working_nifty_sym = sym
                working_nifty_seg = seg
        except Exception as e:
            err = str(e)[:60]
            print(f"    FAIL | segment={seg:10s} | symbol={sym:15s} | {err}")

if nifty_ltp:
    print(f"\n    >>> WORKING: symbol='{working_nifty_sym}' segment='{working_nifty_seg}' LTP={nifty_ltp}")
else:
    print("\n    >>> NO WORKING NIFTY SYMBOL FOUND")

# ── 4. Try option chain methods
print("\n[4] OPTION CHAIN METHODS:")
chain_methods = [
    "get_option_chain", "get_option_chain_data",
    "get_option_chain_v2", "option_chain",
    "search_scrips", "search", "search_symbols",
    "get_contracts", "get_contract_info"
]
for method in chain_methods:
    if hasattr(g, method):
        print(f"\n    FOUND: {method}")
        # Try multiple param combos
        param_combos = [
            {"trading_symbol": "NIFTY", "exchange": "NSE"},
            {"trading_symbol": "NIFTY"},
            {"symbol": "NIFTY", "exchange": "NSE"},
            {"query": "NIFTY"},
            {"search_query": "NIFTY"},
        ]
        for params in param_combos:
            try:
                res = getattr(g, method)(**params)
                out = json.dumps(res, indent=2, default=str)[:800]
                print(f"    Params: {params}")
                print(f"    Result: {out}")
                break
            except Exception as e:
                print(f"    Params: {params} -> {str(e)[:80]}")
    else:
        print(f"    NOT FOUND: {method}")

# ── 5. Try option symbol formats
print("\n[5] OPTION SYMBOL FORMATS — trying all patterns:")

now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
today = now.date()
# Next Tuesday
days_ahead = (1 - today.weekday()) % 7
if days_ahead == 0:
    if now.hour > 15:
        days_ahead = 7
expiry = today + datetime.timedelta(days=days_ahead)

if nifty_ltp:
    strike = int(round(nifty_ltp / 50) * 50)
else:
    strike = 24500  # fallback guess
    print(f"    Using fallback strike: {strike}")

print(f"    Expiry date: {expiry} ({expiry.strftime('%A')})")
print(f"    Strike: {strike}")
print()

# Generate ALL possible symbol formats
option_symbols = [
    f"NIFTY{expiry.strftime('%y%m%d')}{strike}CE",
    f"NIFTY{expiry.strftime('%d%b%y').upper()}{strike}CE",
    f"NIFTY{expiry.strftime('%d%b%Y').upper()}{strike}CE",
    f"NIFTY{expiry.strftime('%y%b%d').upper()}{strike}CE",
    f"NIFTY {expiry.strftime('%d%b%y').upper()} {strike} CE",
    f"NIFTY{strike}CE{expiry.strftime('%d%b%y').upper()}",
    f"NIFTY{expiry.strftime('%d%b%y').upper()}C{strike}",
    f"NIFTY{expiry.strftime('%y%m%d')}C{strike}",
    f"NIFTY-{expiry.strftime('%d%b%y').upper()}-{strike}-CE",
    f"NIFTY{expiry.strftime('%y%m%d')}{strike}.0CE",
    f"NIFTY{expiry.strftime('%d%b%y').upper()}{strike}.00CE",
    f"NIFTY{expiry.strftime('%y%m%d')}{int(strike)}CE",
    f"NIFTY{expiry.strftime('%d%m%y')}{strike}CE",
    f"NIFTY{expiry.strftime('%Y%m%d')}{strike}CE",
    f"NIFTY{expiry.day}{expiry.strftime('%b').upper()}{strike}CE",
    f"NIFTY{expiry.strftime('%d%b').upper()}{strike}CE",
    f"NIFTY{expiry.strftime('%b%y').upper()}{strike}CE",
    f"NIFTY{expiry.strftime('%b').upper()}{strike}CE",
    f"NIFTY{expiry.strftime('%y%b').upper()}{strike}CE",
    f"NIFTY{expiry.strftime('%y%b').upper()}FUT",
]

fno_segments = ["FNO"]
if hasattr(g, "SEGMENT_FNO"):
    fno_segments.append(g.SEGMENT_FNO)
fno_segments = list(set(fno_segments))

working_option_sym = None
working_option_seg = None

for seg in fno_segments:
    for sym in option_symbols:
        try:
            q = g.get_quote(exchange="NSE", segment=seg, trading_symbol=sym)
            ltp = q.get("last_price", "N/A")
            print(f"    OK   | seg={seg:5s} | {sym:45s} | LTP={ltp}")
            if ltp and float(ltp) > 0:
                working_option_sym = sym
                working_option_seg = seg
        except Exception as e:
            err = str(e)[:50]
            print(f"    FAIL | seg={seg:5s} | {sym:45s} | {err}")

if working_option_sym:
    print(f"\n    >>> WORKING OPTION SYMBOL: '{working_option_sym}' segment='{working_option_seg}'")
else:
    print("\n    >>> NO WORKING OPTION SYMBOL FOUND")

# ── 6. Try get_positions to see existing symbol format
print("\n[6] EXISTING POSITIONS (to see symbol format):")
try:
    for seg in fno_segments:
        res = g.get_positions_for_user(segment=seg)
        positions = res.get("positions", [])
        if positions:
            for p in positions[:5]:
                print(f"    {json.dumps(p, default=str)[:200]}")
        else:
            print(f"    No positions in segment={seg}")
except Exception as e:
    print(f"    Error: {e}")

# ── 7. Try get_orders to see historical symbol format
print("\n[7] TODAY'S ORDERS (to see symbol format):")
try:
    if hasattr(g, "get_order_book"):
        res = g.get_order_book(segment="FNO" if not hasattr(g, "SEGMENT_FNO") else g.SEGMENT_FNO)
        orders = res.get("orders", res.get("data", []))
        if orders:
            for o in orders[:5]:
                print(f"    {json.dumps(o, default=str)[:200]}")
        else:
            print("    No orders today")
    elif hasattr(g, "get_orders"):
        res = g.get_orders()
        print(f"    {json.dumps(res, default=str)[:500]}")
    else:
        print("    No order book method found")
except Exception as e:
    print(f"    Error: {e}")

# ── 8. Try historical candle methods
print("\n[8] HISTORICAL CANDLE METHODS:")
hist_methods = [
    "get_historical_candles", "get_historical_candle_data",
    "get_candles", "get_ohlc", "historical"
]
for method in hist_methods:
    if hasattr(g, method):
        print(f"    FOUND: {method}")
        # Print method signature
        import inspect
        try:
            sig = inspect.signature(getattr(g, method))
            print(f"    Signature: {method}{sig}")
        except:
            print(f"    (cannot read signature)")
    else:
        print(f"    NOT FOUND: {method}")

print("\n" + "=" * 60)
print("  DEBUG COMPLETE — share this full output")
print("=" * 60)
