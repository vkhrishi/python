from growwapi import GrowwAPI
import json
with open('/root/scalper/token.json') as f:
    data = json.load(f)
groww = GrowwAPI(data['token'])

# Find NIFTY groww_symbol
print('=== Method 1: instrument lookup ===')
try:
    inst = groww.get_instrument_by_exchange_and_trading_symbol(exchange='NSE', trading_symbol='NIFTY')
    print('Found:', inst)
    print('groww_symbol:', inst.get('groww_symbol', 'NOT FOUND'))
    print('exchange_token:', inst.get('exchange_token', 'NOT FOUND'))
except Exception as e:
    print('Failed:', e)

print()
print('=== Method 2: try NIFTY 50 ===')
try:
    inst = groww.get_instrument_by_exchange_and_trading_symbol(exchange='NSE', trading_symbol='NIFTY 50')
    print('Found:', inst)
    print('groww_symbol:', inst.get('groww_symbol', 'NOT FOUND'))
except Exception as e:
    print('Failed:', e)

print()
print('=== Method 3: get_ohlc ===')
try:
    res = groww.get_ohlc(exchange_trading_symbols=('NIFTY',), segment='CASH')
    print('OHLC:', res)
except Exception as e:
    print('Failed:', e)

print()
print('=== Method 4: try candles with guessed groww_symbol ===')
for gs in ['NIFTY', 'NIFTY50', 'NIFTY 50', 'nifty', 'GIDXNIFTY']:
    try:
        res = groww.get_historical_candles(
            exchange='NSE', segment='CASH', groww_symbol=gs,
            start_time='2026-06-10 09:15:00', end_time='2026-06-10 11:00:00',
            candle_interval='5m')
        print('SUCCESS with groww_symbol=%s' % gs)
        if isinstance(res, dict):
            print('Keys:', list(res.keys()))
            for k,v in res.items():
                if isinstance(v, list) and len(v) > 0:
                    print('  %s[0]:' % k, v[0])
                    print('  %s count:' % k, len(v))
        break
    except Exception as e:
        print('  %s -> %s' % (gs, str(e)[:80]))

