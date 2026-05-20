import datetime
import json
import time
import sys
import os
import pyotp

sys.path.insert(0, "/root/scalper")
from growwapi import GrowwAPI

TOKEN_FILE = "/root/scalper/token.json"
GROWW_TOTP_TOKEN = "YOUR_TOKEN_HERE"
GROWW_TOTP_SECRET = "YOUR_SECRET_HERE"

def login():
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
        if data.get("date") == now.strftime("%Y-%m-%d") and data.get("token"):
            return GrowwAPI(data["token"])
    except:
        pass
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    totp_code = pyotp.TOTP(GROWW_TOTP_SECRET).now()
    access_token = GrowwAPI.get_access_token(api_key=GROWW_TOTP_TOKEN, totp=totp_code)
    groww = GrowwAPI(access_token)
    with open(TOKEN_FILE, "w") as f:
        json.dump({
            "date": now.strftime("%Y-%m-%d"),
            "token": access_token,
            "saved_at": now.strftime("%Y-%m-%d %H:%M:%S")
        }, f)
    return groww

def fetch_chunk(groww, start_str, end_str):
    try:
        res = groww.get_historical_candle_data(
            trading_symbol="NIFTY",
            exchange="NSE",
            segment="CASH",
            start_time=start_str,
            end_time=end_str,
            interval_in_minutes=5
        )
        raw = res.get("candles", []) if isinstance(res, dict) else []
        rows = []
        for c in raw:
            if len(c) < 5:
                continue
            t = c[0]
            if isinstance(t, (int, float)):
                dt_obj = datetime.datetime.utcfromtimestamp(t) + datetime.timedelta(hours=5, minutes=30)
                ts = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
            else:
                ts = str(t).replace("T", " ")
            rows.append({
                "ts": ts,
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]) if len(c) > 5 and c[5] is not None else 0.0
            })
        return rows
    except Exception as e:
        print("Error fetching %s to %s: %s" % (start_str, end_str, str(e)))
        return []

def main():
    groww = login()
    print("Logged in OK")

    # Fetch data in 7-day chunks going back 2 years
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    end_date = now.date()
    start_date = end_date - datetime.timedelta(days=730)

    print("Fetching from %s to %s" % (start_date, end_date))

    all_rows = []
    current = start_date

    while current < end_date:
        chunk_end = min(current + datetime.timedelta(days=7), end_date)
        start_str = current.strftime("%Y-%m-%d 09:15:00")
        end_str = chunk_end.strftime("%Y-%m-%d 15:30:00")

        print("  Fetching %s to %s..." % (start_str, end_str))
        rows = fetch_chunk(groww, start_str, end_str)
        print("    Got %d candles" % len(rows))
        all_rows.extend(rows)

        current = chunk_end + datetime.timedelta(days=1)
        time.sleep(0.5)

    # Remove duplicates by timestamp
    seen = set()
    unique = []
    for r in all_rows:
        if r["ts"] not in seen:
            seen.add(r["ts"])
            unique.append(r)

    unique.sort(key=lambda x: x["ts"])

    # Write CSV
    out_file = "nifty_5m.csv"
    with open(out_file, "w") as f:
        f.write("ts,open,high,low,close,volume\n")
        for r in unique:
            f.write("%s,%.2f,%.2f,%.2f,%.2f,%.0f\n" % (
                r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"]
            ))

    print("")
    print("Done! Saved %d candles to %s" % (len(unique), out_file))
    print("First: %s" % unique[0]["ts"])
    print("Last: %s" % unique[-1]["ts"])
    size_mb = os.path.getsize(out_file) / 1024 / 1024
    print("Size: %.1f MB" % size_mb)

if __name__ == "__main__":
    main()
