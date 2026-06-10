from growwapi import GrowwAPI
import inspect

# Check the new method signature
try:
    sig = inspect.signature(GrowwAPI.get_historical_candles)
    print('get_historical_candles params:', sig)
except Exception as e:
    print('Signature error:', e)

# Also try source code
try:
    src = inspect.getsource(GrowwAPI.get_historical_candles)
    print()
    print('SOURCE CODE:')
    print(src[:2000])
except Exception as e:
    print('Source error:', e)