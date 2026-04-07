#!/usr/bin/env python3
"""
Debug 3 — Use get_option_chain to discover exact symbol format
Save as: /root/scalper/debug3.py
Run:     python3 /root/scalper/debug3.py
"""

from growwapi import GrowwAPI
import json, datetime

with open("/root/scalper/token.json") as f:
    t = json.load(f)
g = GrowwAPI(t["token"])

# Get Nifty LTP
q = g.get_quote(exchange="NSE", segment="CASH", trading_symbol="NIFTY")
ltp = float(q["last_price"])
strike = int(round(ltp / 50) * 50)
print(f"Nifty LTP: {ltp}")
print(f"ATM Strike: {strike}")

# Calculate expiry
now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
today = now.date()
days_ahead = (1 - today.weekday()) % 7
if days_ahead == 0:
    if now.hour > 15:
        days_ahead = 7
expiry = today + datetime.timedelta(days=days_ahead)
print(f"Expiry date: {expiry} ({expiry.strftime('%A')})")

# ══════════════════════════════════════════════════════════
# TEST 1: get_option_chain with different expiry_date formats
# ══════════════════════════════════════════════════════════
print()
print("=" * 60)
print("TEST 1: get_option_chain — trying expiry_date formats")
print("=" * 60)

expiry_formats = [
    expiry.strftime("%Y-%m-%d"),           # 2026-04-07
    expiry.strftime("%d-%m-%Y"),           # 07-04-2026
    expiry.strftime("%d/%m/%Y"),           # 07/04/2026
    expiry.strftime("%Y/%m/%d"),           # 2026/04/07
    expiry.strftime("%d %b %Y"),           # 07 Apr 2026
    expiry.strftime("%d-%b-%Y"),           # 07-Apr-2026
    expiry.strftime("%d%b%Y").upper(),     # 07APR2026
    expiry.strftime("%d%b%y").upper(),     # 07APR26
    expiry.strftime("%Y%m%d"),             # 20260407
    expiry.strftime("%d%m%Y"),             # 07042026
    expiry.strftime("%b %d, %Y"),          # Apr 07, 2026
    expiry.isoformat(),                    # 2026-04-07
    str(int(datetime.datetime.combine(expiry, datetime.time()).timestamp())),  # epoch
    expiry.strftime("%Y-%m-%dT00:00:00"),  # ISO with time
]

underlyings = ["NIFTY", "NIFTY 50", "Nifty 50", "NIFTY50", "NSE_FO|NIFTY"]
exchanges = ["NSE", "NFO"]

chain_data = None

for exc in exchanges:
    for underlying in underlyings:
        for exp_fmt in expiry_formats:
            try:
                res = g.get_option_chain(
                    exchange=exc,
                    underlying=underlying,
                    expiry_date=exp_fmt
                )
                out = json.dumps(res, indent=2, default=str)[:1500]
                print(f"\n  OK | exchange={exc} underlying={underlying} expiry={exp_fmt}")
                print(f"  {out}")
                chain_data = res
                break
            except Exception as e:
                err = str(e)[:80]
                print(f"  FAIL | exc={exc} und={underlying:12s} exp={exp_fmt:20s} | {err}")
        if chain_data:
            break
    if chain_data:
        break

# ══════════════════════════════════════════════════════════
# TEST 2: If chain found, extract trading_symbols
# ══════════════════════════════════════════════════════════
if chain_data:
    print()
    print("=" * 60)
    print("TEST 2: Extracting symbols from option chain")
    print("=" * 60)

    # Try to find symbol keys in the response
    def find_symbols(data, path=""):
        if isinstance(data, dict):
            for k, v in data.items():
                if "symbol" in k.lower() or "trading" in k.lower() or "scrip" in k.lower():
                    print(f"  {path}.{k} = {v}")
                find_symbols(v, f"{path}.{k}")
        elif isinstance(data, list) and len(data) > 0:
            for i, item in enumerate(data[:3]):  # first 3 items
                find_symbols(item, f"{path}[{i}]")

    find_symbols(chain_data)

    # Print full first few entries
    print()
    print("  Full chain data keys:", list(chain_data.keys()) if isinstance(chain_data, dict) else type(chain_data))
    print()
    full_out = json.dumps(chain_data, indent=2, default=str)[:3000]
    print(full_out)

# ══════════════════════════════════════════════════════════
# TEST 3: Try historical candle data with different params
# ══════════════════════════════════════════════════════════
print()
print("=" * 60)
print("TEST 3: get_historical_candle_data — find working params")
print("=" * 60)

end_dt = now.strftime("%Y-%m-%d %H:%M:%S")
start_dt = (now - datetime.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")

# Try different time formats too
time_formats = [
    (start_dt, end_dt, "YYYY-MM-DD HH:MM:SS"),
    ((now - datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S"),
     now.strftime("%Y-%m-%dT%H:%M:%S"), "ISO format"),
    (str(int((now - datetime.timedelta(hours=2)).timestamp())),
     str(int(now.timestamp())), "epoch seconds"),
]

symbols_to_try = ["NIFTY", "NIFTY 50", "Nifty 50", "NIFTY50"]
segments_to_try = ["CASH", "FNO"]

for sym in symbols_to_try:
    for seg in segments_to_try:
        for s_time, e_time, fmt_name in time_formats:
            try:
                res = g.get_historical_candle_data(
                    trading_symbol=sym,
                    exchange="NSE",
                    segment=seg,
                    start_time=s_time,
                    end_time=e_time,
                    interval_in_minutes=5
                )
                candles = res.get("candles", []) if isinstance(res, dict) else []
                print(f"  OK   | sym={sym:10s} seg={seg:5s} fmt={fmt_name:20s} | {len(candles)} candles")
                if candles:
                    print(f"         First: {candles[0]}")
                    print(f"         Last:  {candles[-1]}")
                    break
            except Exception as e:
                err = str(e)[:60]
                print(f"  FAIL | sym={sym:10s} seg={seg:5s} fmt={fmt_name:20s} | {err}")

# ══════════════════════════════════════════════════════════
# TEST 4: Try get_quote for options with exchange=NFO
# ══════════════════════════════════════════════════════════
print()
print("=" * 60)
print("TEST 4: Option quote with exchange=NFO instead of NSE")
print("=" * 60)

test_syms = [
    f"NIFTY{expiry.strftime('%d%b%y').upper()}{strike}CE",
    f"NIFTY{expiry.strftime('%d%b%y').upper()}{strike - 50}CE",
    f"NIFTY{expiry.strftime('%d%b%y').upper()}{strike + 50}CE",
]

for exc in ["NSE", "NFO"]:
    for seg in ["FNO", "CASH", "OPT"]:
        for sym in test_syms:
            try:
                q2 = g.get_quote(exchange=exc, segment=seg, trading_symbol=sym)
                print(f"  OK   | exc={exc} seg={seg:5s} | {sym:35s} | LTP={q2.get('last_price')}")
            except Exception as e:
                err = str(e)[:50]
                print(f"  FAIL | exc={exc} seg={seg:5s} | {sym:35s} | {err}")

# ══════════════════════════════════════════════════════════
# TEST 5: Dump full get_quote response for Nifty (find all keys)
# ══════════════════════════════════════════════════════════
print()
print("=" * 60)
print("TEST 5: Full Nifty quote response (all keys)")
print("=" * 60)
try:
    q = g.get_quote(exchange="NSE", segment="CASH", trading_symbol="NIFTY")
    print(json.dumps(q, indent=2, default=str))
except Exception as e:
    print(f"  Error: {e}")

print()
print("=" * 60)
print("DEBUG 3 COMPLETE — share full output")
print("=" * 60)
