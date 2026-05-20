import pandas as pd
import glob
import sys
import os

files = glob.glob("nifty_raw/*NIFTY*") + glob.glob("nifty_raw/*nifty*")
print("Found files:", files)

if not files:
    print("ERROR: No NIFTY file found")
    sys.exit(1)

src = files[0]
print("Using:", src)

df = pd.read_csv(src)
print("Columns:", list(df.columns))
print(df.head(3))

ts_col = None
for col in df.columns:
    if col.lower().strip() in ("date", "datetime", "timestamp", "ts", "time"):
        ts_col = col
        break
if ts_col is None:
    ts_col = df.columns[0]

df["ts"] = pd.to_datetime(df[ts_col])
df = df.sort_values("ts")

col_map = {}
for col in df.columns:
    cl = col.lower().strip()
    if cl == "open":
        col_map["open"] = col
    elif cl == "high":
        col_map["high"] = col
    elif cl == "low":
        col_map["low"] = col
    elif cl == "close":
        col_map["close"] = col
    elif cl in ("volume", "vol"):
        col_map["volume"] = col

if "volume" not in col_map:
    df["volume"] = 0
    col_map["volume"] = "volume"

print("Column mapping:", col_map)

df = df.set_index("ts")
df5 = df.resample("5min").agg({
    col_map["open"]: "first",
    col_map["high"]: "max",
    col_map["low"]: "min",
    col_map["close"]: "last",
    col_map["volume"]: "sum"
}).dropna()

df5.columns = ["open", "high", "low", "close", "volume"]
df5.index.name = "ts"
df5 = df5.between_time("09:15", "15:30")

df5.to_csv("nifty_5m.csv")
print("Done!", len(df5), "bars")
print("Range:", df5.index.min(), "to", df5.index.max())
print("Saved: nifty_5m.csv")
