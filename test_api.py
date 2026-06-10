from growwapi import GrowwAPI
import pyotp, json

TOKEN_FILE = "/root/scalper/token.json"
TOTP_TOKEN = "eyJraWQiOiJaTUtjVXciLCJhbGciOiJFUzI1NiJ9.eyJleHAiOjI1NjQ0NjQ3NTEsImlhdCI6MTc3NjA2NDc1MSwibmJmIjoxNzc2MDY0NzUxLCJzdWIiOiJ7XCJ0b2tlblJlZklkXCI6XCI4OTFmMzExNi04NGRjLTQxNWMtOWUxYy1iOTc3YzNhMWExZmJcIixcInZlbmRvckludGVncmF0aW9uS2V5XCI6XCJlMzFmZjIzYjA4NmI0MDZjODg3NGIyZjZkODQ5NTMxM1wiLFwidXNlckFjY291bnRJZFwiOlwiNjQ3NTk3YTItNTlmMC00MWQ2LTkyZjgtMGNjYzdkYTBkN2I2XCIsXCJkZXZpY2VJZFwiOlwiYWM4Y2Y5NzctMTY5OC01NDM3LTkxNTItMzg2ZTFiZmM2YzQwXCIsXCJzZXNzaW9uSWRcIjpcIjAzM2E2OWRhLWQ3YzQtNDJkMS04YTJiLWNiMDc0NjQxMGIwZFwiLFwiYWRkaXRpb25hbERhdGFcIjpcIno1NC9NZzltdjE2WXdmb0gvS0EwYkgyblRaQUhZYlRzeVhHdDk1ZzgxR1JSTkczdTlLa2pWZDNoWjU1ZStNZERhWXBOVi9UOUxIRmtQejFFQisybTdRPT1cIixcInJvbGVcIjpcImF1dGgtdG90cFwiLFwic291cmNlSXBBZGRyZXNzXCI6XCIyNDAxOjQ5MDA6OTM5NTpjZTQ1OjdjNWM6NWVlYjoyMTAwOjZiYzUsMTcyLjY5LjEzMS4xODcsMzUuMjQxLjIzLjEyM1wiLFwidHdvRmFFeHBpcnlUc1wiOjI1NjQ0NjQ3NTEzMTgsXCJ2ZW5kb3JOYW1lXCI6XCJncm93d0FwaVwifSIsImlzcyI6ImFwZXgtYXV0aC1wcm9kLWFwcCJ9.Oyi_wQZPgluXSJTYzwyWEJ4Q3nW40o6e9sr7oD6gsfLwgMB0eNmG6TQDM2_yyEXZp2Z9z1tCuqTgJYd6rBJdOA"
TOTP_SECRET = "5TJKK3FZ2NFN73QTENQLKH5AOVDRC7CQ"

with open(TOKEN_FILE) as f:
    data = json.load(f)
groww = GrowwAPI(data["token"])

print("=== ALL PUBLIC METHODS ===")
methods = sorted([m for m in dir(groww) if not m.startswith("_") and callable(getattr(groww, m))])
for m in methods:
    print("  " + m)

print("\n=== CANDLE/HISTORY METHODS ===")
for m in methods:
    if any(k in m.lower() for k in ["candle", "histor", "ohlc", "chart", "bar"]):
        print("  >>> " + m)
        # Show signature
        import inspect
        try:
            sig = inspect.signature(getattr(groww, m))
            print("      params: " + str(sig))
        except:
            pass

print("\n=== TRYING get_historical_candles ===")
try:
    res = groww.get_historical_candles(
        trading_symbol="NIFTY", exchange="NSE", segment="CASH",
        start_time="2026-06-10 09:15:00", end_time="2026-06-10 11:00:00",
        interval_in_minutes=5)
    print("SUCCESS! Type:", type(res))
    if isinstance(res, dict):
        print("Keys:", list(res.keys()))
        for k, v in res.items():
            if isinstance(v, list) and len(v) > 0:
                print("  %s: %d items, first=" % (k, len(v)), v[0])
    else:
        print("Response:", str(res)[:500])
except Exception as e:
    print("FAILED:", e)

print("\n=== TRYING with different params ===")
try:
    res = groww.get_historical_candles(
        trading_symbol="NIFTY", exchange="NSE", segment="CASH",
        start_date_time="2026-06-10T09:15:00", end_date_time="2026-06-10T11:00:00",
        candle_interval="5m")
    print("SUCCESS v2! Type:", type(res))
    if isinstance(res, dict):
        print("Keys:", list(res.keys()))
except Exception as e:
    print("FAILED v2:", e)
