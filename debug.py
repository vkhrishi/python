import pyotp
from growwapi import GrowwAPI
import json

GROWW_TOTP_TOKEN  = "eyJraWQiOiJaTUtjVXciLCJhbGciOiJFUzI1NiJ9.eyJleHAiOjI1NjQ0NTYyODMsImlhdCI6MTc3NjA1NjI4MywibmJmIjoxNzc2MDU2MjgzLCJzdWIiOiJ7XCJ0b2tlblJlZklkXCI6XCI2MGFhOTQ0MC0wMmViLTRiY2UtODIyNS1lYmU5MjUzNjI0NTFcIixcInZlbmRvckludGVncmF0aW9uS2V5XCI6XCJlMzFmZjIzYjA4NmI0MDZjODg3NGIyZjZkODQ5NTMxM1wiLFwidXNlckFjY291bnRJZFwiOlwiNjQ3NTk3YTItNTlmMC00MWQ2LTkyZjgtMGNjYzdkYTBkN2I2XCIsXCJkZXZpY2VJZFwiOlwiYzY2YmE0NmItMDlhNC01Zjk4LWI5NDMtZmMwNzQzZGNiMmZhXCIsXCJzZXNzaW9uSWRcIjpcIjZjNWQ0ZWE0LTc1OTEtNDc5NC05MGEyLTAwMjliMTg0YmEyN1wiLFwiYWRkaXRpb25hbERhdGFcIjpcIno1NC9NZzltdjE2WXdmb0gvS0EwYkgyblRaQUhZYlRzeVhHdDk1ZzgxR1JSTkczdTlLa2pWZDNoWjU1ZStNZERhWXBOVi9UOUxIRmtQejFFQisybTdRPT1cIixcInJvbGVcIjpcImF1dGgtdG90cFwiLFwic291cmNlSXBBZGRyZXNzXCI6XCI1OS4xNDQuNjcuNjEsMTcyLjY4LjIzOS4xNTUsMzUuMjQxLjIzLjEyM1wiLFwidHdvRmFFeHBpcnlUc1wiOjI1NjQ0NTYyODM2NTcsXCJ2ZW5kb3JOYW1lXCI6XCJncm93d0FwaVwifSIsImlzcyI6ImFwZXgtYXV0aC1wcm9kLWFwcCJ9.29NEA3lzynnlbGvzFJ1bOgEVe-yG48Asyqvpq2hrHXN85Qn42_DfUPESHXF7Y-_KiE3D_O2hjp-xZ3pBxit62g"
GROWW_TOTP_SECRET = "PVHRANLNIHXTVSWU5ODZ7US6DWSRDFF7"

print("=" * 60)
print("STEP 1: Generating TOTP code...")
totp_code = pyotp.TOTP(GROWW_TOTP_SECRET).now()
print(f"  TOTP code: {totp_code}")

print("\nSTEP 2: Getting fresh access token from Groww...")
try:
    access_token = GrowwAPI.get_access_token(api_key=GROWW_TOTP_TOKEN, totp=totp_code)
    print(f"  Access token (first 60 chars): {access_token[:60]}...")
    print("  ✓ Login SUCCESS")
except Exception as e:
    print(f"  ✗ Login FAILED: {e}")
    exit(1)

print("\nSTEP 3: Initializing GrowwAPI with fresh token...")
groww = GrowwAPI(access_token)

print("\nSTEP 4: Saving fresh token to file...")
import datetime
def ist_now():
    import datetime, datetime as dt
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=5, minutes=30)

with open("/root/scalper/token.json", "w") as f:
    json.dump({
        "date": ist_now().strftime("%Y-%m-%d"),
        "token": access_token,
        "saved_at": ist_now().strftime("%Y-%m-%d %H:%M:%S")
    }, f)
print("  ✓ Token saved to /root/scalper/token.json")

print("\nSTEP 5: Fetching Nifty quote...")
try:
    q = groww.get_quote(exchange="NSE", segment="CASH", trading_symbol="NIFTY")
    print(f"  Nifty LTP: {q.get('last_price')}")
    print("  ✓ Quote OK")
except Exception as e:
    print(f"  ✗ Quote FAILED: {e}")

print("\nSTEP 6: Fetching positions (FNO)...")
try:
    res = groww.get_positions_for_user(segment=groww.SEGMENT_FNO)
    positions = res.get("positions", [])
    print(f"  Open positions: {len(positions)}")
    print("  ✓ Positions OK")
except Exception as e:
    print(f"  ✗ Positions FAILED: {e}")

print("\nSTEP 7: Placing a DUMMY order (1 qty, will likely reject on qty/margin but NOT on IP)...")
try:
    res = groww.place_order(
        trading_symbol="NIFTY2641323700PE",
        quantity=1,
        validity=groww.VALIDITY_DAY,
        exchange=groww.EXCHANGE_NSE,
        segment=groww.SEGMENT_FNO,
        product=groww.PRODUCT_MIS,
        order_type=groww.ORDER_TYPE_MARKET,
        transaction_type=groww.TRANSACTION_TYPE_BUY,
        order_reference_id="DEBUG001"
    )
    print(f"  Order response: {res}")
    status = res.get("order_status", "")
    if "unregistered" in str(res).lower():
        print("  ✗ STILL getting IP error — token is tied to wrong IP")
    else:
        print("  ✓ IP is accepted! Order went through (may fail for other reasons)")
except Exception as e:
    err = str(e)
    print(f"  Order error: {err}")
    if "unregistered" in err.lower():
        print("  ✗ CONFIRMED: IP error persists even with fresh token")
        print("  → The TOTP_TOKEN itself was generated on a different machine")
        print("  → Go to groww.in/trade-api → delete HriPlay key → recreate it FROM THIS VPS")
    else:
        print("  ✓ IP accepted — error is something else (margin/qty/etc)")

print("\n" + "=" * 60)
print("DEBUG COMPLETE")