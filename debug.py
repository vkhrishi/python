#!/usr/bin/env python3
"""
Debug 2 — Find exact working option symbol format
Save as: /root/scalper/debug2.py
Run:     python3 /root/scalper/debug2.py
"""

from growwapi import GrowwAPI
import json, datetime

# Load token
with open("/root/scalper/token.json") as f:
    t = json.load(f)
g = GrowwAPI(t["token"])

# Get Nifty LTP
q = g.get_quote(exchange="NSE", segment="CASH", trading_symbol="NIFTY")
ltp = float(q["last_price"])
strike = int(round(ltp / 50) * 50)
print(f"Nifty LTP: {ltp}")
print(f"ATM Strike: {strike}")

# Calculate expiry (next Tuesday)
now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
today = now.date()
days_ahead = (1 - today.weekday()) % 7
if days_ahead == 0:
    if now.hour > 15:
        days_ahead = 7
expiry = today + datetime.timedelta(days=days_ahead)
print(f"Expiry: {expiry} ({expiry.strftime('%A')})")
print()

# Try EVERY possible format with actual strike
print("=" * 60)
print(f"Testing ALL symbol formats for strike={strike} CE")
print("=" * 60)

formats = {
    "DDMONYY"     : f"NIFTY{expiry.strftime('%d%b%y').upper()}{strike}CE",
    "DDMONYYYY"   : f"NIFTY{expiry.strftime('%d%b%Y').upper()}{strike}CE",
    "YYMMDD"      : f"NIFTY{expiry.strftime('%y%m%d')}{strike}CE",
    "YYYYMMDD"    : f"NIFTY{expiry.strftime('%Y%m%d')}{strike}CE",
    "DDMMYY"      : f"NIFTY{expiry.strftime('%d%m%y')}{strike}CE",
    "YYMDD"       : f"NIFTY{expiry.strftime('%y')}{expiry.month}{expiry.strftime('%d')}{strike}CE",
    "YYM0DD"      : f"NIFTY{expiry.strftime('%y')}{expiry.strftime('%m')}{expiry.strftime('%d')}{strike}CE",
    "DMONYY"      : f"NIFTY{expiry.day}{expiry.strftime('%b%y').upper()}{strike}CE",
    "DDMON"       : f"NIFTY{expiry.strftime('%d%b').upper()}{strike}CE",
    "MONYY"       : f"NIFTY{expiry.strftime('%b%y').upper()}{strike}CE",
    "YYMON"       : f"NIFTY{expiry.strftime('%y%b').upper()}{strike}CE",
    "MONDD"       : f"NIFTY{expiry.strftime('%b%d').upper()}{strike}CE",
    "YYMONDD"     : f"NIFTY{expiry.strftime('%y%b%d').upper()}{strike}CE",
    "strike_dot"  : f"NIFTY{expiry.strftime('%d%b%y').upper()}{strike}.0CE",
    "C_not_CE"    : f"NIFTY{expiry.strftime('%d%b%y').upper()}C{strike}",
    "CE_space"    : f"NIFTY {expiry.strftime('%d%b%y').upper()} {strike} CE",
    "dash_sep"    : f"NIFTY-{expiry.strftime('%d%b%y').upper()}-{strike}-CE",
    "no_NIFTY"    : f"{expiry.strftime('%d%b%y').upper()}{strike}CE",
    "BANKNIFTY"   : f"BANKNIFTY{expiry.strftime('%d%b%y').upper()}{strike}CE",
}

# Also try strike +/- 50
extra_strikes = [strike - 50, strike, strike + 50]

working = []

for s in extra_strikes:
    # Update formats with this strike
    test_formats = {
        f"DDMONYY_s{s}"     : f"NIFTY{expiry.strftime('%d%b%y').upper()}{s}CE",
        f"YYMMDD_s{s}"      : f"NIFTY{expiry.strftime('%y%m%d')}{s}CE",
        f"DDMONYYYY_s{s}"   : f"NIFTY{expiry.strftime('%d%b%Y').upper()}{s}CE",
        f"YYYYMMDD_s{s}"    : f"NIFTY{expiry.strftime('%Y%m%d')}{s}CE",
        f"DDMMYY_s{s}"      : f"NIFTY{expiry.strftime('%d%m%y')}{s}CE",
        f"MONYY_s{s}"       : f"NIFTY{expiry.strftime('%b%y').upper()}{s}CE",
    }
    for name, sym in test_formats.items():
        try:
            q2 = g.get_quote(exchange="NSE", segment="FNO", trading_symbol=sym)
            l = q2.get("last_price", "N/A")
            print(f"  OK   | {name:25s} | {sym:35s} | LTP={l}")
            working.append((name, sym, l))
        except Exception as e:
            err = str(e)[:50]
            print(f"  FAIL | {name:25s} | {sym:35s} | {err}")

# Also try option chain to discover format
print()
print("=" * 60)
print("Trying get_option_chain to discover symbol format")
print("=" * 60)

if hasattr(g, 'get_option_chain'):
    # Try different param combos
    param_combos = [
        {},
        {"underlying": "NIFTY"},
        {"symbol": "NIFTY"},
        {"trading_symbol": "NIFTY"},
        {"scrip_name": "NIFTY"},
        {"instrument_name": "NIFTY"},
    ]
    for params in param_combos:
        try:
            res = g.get_option_chain(**params)
            out = json.dumps(res, indent=2, default=str)[:1000]
            print(f"  Params: {params}")
            print(f"  Result: {out}")
            print()
            break
        except Exception as e:
            print(f"  Params: {params} -> {str(e)[:80]}")

# Try get_contracts
print()
print("=" * 60)
print("Trying get_contracts")
print("=" * 60)

if hasattr(g, 'get_contracts'):
    param_combos = [
        {},
        {"segment": "FNO"},
        {"exchange": "NSE"},
        {"exchange": "NSE", "segment": "FNO"},
    ]
    for params in param_combos:
        try:
            res = g.get_contracts(**params)
            # Filter for NIFTY entries
            if isinstance(res, dict):
                for key in res:
                    items = res[key] if isinstance(res[key], list) else [res[key]]
                    nifty_items = [i for i in items if isinstance(i, (dict, str)) and "NIFTY" in str(i)][:5]
                    if nifty_items:
                        print(f"  Key: {key}")
                        for item in nifty_items:
                            print(f"    {json.dumps(item, default=str)[:200]}")
            elif isinstance(res, list):
                nifty_items = [i for i in res if "NIFTY" in str(i)][:5]
                for item in nifty_items:
                    print(f"    {json.dumps(item, default=str)[:200]}")
            else:
                print(f"  Result type: {type(res)}")
                print(f"  {str(res)[:500]}")
            break
        except Exception as e:
            print(f"  Params: {params} -> {str(e)[:80]}")

# Try searching for NIFTY options
print()
print("=" * 60)
print("Trying search method")
print("=" * 60)

if hasattr(g, 'search'):
    queries = [f"NIFTY {strike} CE", f"NIFTY CE {strike}", "NIFTY CE", f"NIFTY {expiry.strftime('%d%b').upper()}"]
    for q_str in queries:
        try:
            res = g.search(query=q_str)
            out = json.dumps(res, indent=2, default=str)[:500]
            print(f"  Query: '{q_str}'")
            print(f"  {out}")
            break
        except Exception as e:
            print(f"  Query: '{q_str}' -> {str(e)[:80]}")

# Print method signatures for key methods
print()
print("=" * 60)
print("Method signatures")
print("=" * 60)

import inspect
for method_name in ['get_quote', 'get_option_chain', 'get_contracts', 'place_order', 'get_historical_candle_data']:
    if hasattr(g, method_name):
        try:
            sig = inspect.signature(getattr(g, method_name))
            print(f"  {method_name}{sig}")
        except:
            print(f"  {method_name} (cannot read signature)")

print()
print("=" * 60)
if working:
    print("WORKING SYMBOLS:")
    for name, sym, l in working:
        print(f"  {sym} -> LTP={l}")
    print(f"\nUSE THIS FORMAT: {working[0][1]}")
else:
    print("NO WORKING OPTION SYMBOL FOUND")
    print("The issue is likely the segment or exchange parameter")
    print()
    print("Trying with different exchange/segment combos for one symbol:")
    test_sym = f"NIFTY{expiry.strftime('%d%b%y').upper()}{strike}CE"
    for exc in ["NSE", "NFO", "BSE", "MCX"]:
        for seg in ["FNO", "CASH", "COMMODITY", "CURRENCY", "OPT", "FUT", "EQUITY"]:
            try:
                q3 = g.get_quote(exchange=exc, segment=seg, trading_symbol=test_sym)
                print(f"  OK   | exchange={exc} segment={seg} -> LTP={q3.get('last_price')}")
            except:
                pass

print("=" * 60)
print("DEBUG 2 COMPLETE — share full output")
