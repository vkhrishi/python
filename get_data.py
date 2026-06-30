#!/usr/bin/env python
# ============================================================
#  get_data.py - fetch NIFTY 5-min index candles -> data.csv
#
#  Free, no broker account / API keys needed. Uses Yahoo Finance
#  (^NSEI = NIFTY 50 index) via the `yfinance` package.
#
#  LIMITATION: Yahoo only serves ~60 days of 5-minute history.
#  That is enough for a first edge check. For longer/again-accurate
#  history use your Groww `backtest_real` path instead.
#
#  SETUP (one time):   pip install yfinance
#  RUN:                python get_data.py            -> writes data.csv
#                      python get_data.py 30         -> last 30 days
#                      python get_data.py 60 nifty.csv
#
#  Output columns (what backtest.py reads):
#      datetime, open, high, low, close, volume
# ============================================================

import sys

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed. Run:  pip install yfinance")
    sys.exit(1)


def main():
    days = 60
    out = "data.csv"
    for a in sys.argv[1:]:
        if a.isdigit():
            days = min(int(a), 60)          # Yahoo caps 5m history at ~60d
        else:
            out = a

    period = "%dd" % days
    print("Downloading NIFTY (^NSEI) 5-min candles, last %s ..." % period)

    df = yf.download(
        "^NSEI", period=period, interval="5m",
        auto_adjust=False, progress=False,
    )
    if df is None or df.empty:
        print("No data returned. Try a smaller day count or check your connection.")
        sys.exit(1)

    # yfinance may return multi-index columns (ticker level) - flatten them.
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    # The datetime column is the first one (Datetime / Date).
    ts_col = df.columns[0]

    # Normalise to tz-naive IST timestamps so they read as 09:15..15:30.
    ts = df[ts_col]
    try:
        if getattr(ts.dt, "tz", None) is not None:
            ts = ts.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    except (AttributeError, TypeError):
        pass
    df[ts_col] = ts

    rows = 0
    with open(out, "w", newline="") as f:
        f.write("datetime,open,high,low,close,volume\n")
        for _, r in df.iterrows():
            try:
                t = r[ts_col]
                stamp = t.strftime("%Y-%m-%d %H:%M:%S")
                o, h, l, c = float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"])
                v = float(r["Volume"]) if "Volume" in r and r["Volume"] == r["Volume"] else 0.0
            except (ValueError, KeyError, TypeError):
                continue
            # keep regular session only (09:15 - 15:30 IST)
            hm = t.hour * 60 + t.minute
            if hm < 9 * 60 + 15 or hm > 15 * 60 + 30:
                continue
            f.write("%s,%.2f,%.2f,%.2f,%.2f,%.0f\n" % (stamp, o, h, l, c, v))
            rows += 1

    print("Wrote %d candles -> %s" % (rows, out))
    if rows:
        print("Next:  python SM2\\backtest.py %s" % out)


if __name__ == "__main__":
    main()
