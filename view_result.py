import pandas as pd
import numpy as np

df = pd.read_csv("trades.csv")
wins = df[df.pnl > 0]
losses = df[df.pnl <= 0]

print("Total trades:", len(df))
print("Winners:", len(wins))
print("Losers:", len(losses))

if len(df) > 0:
    print("Win rate: %.1f%%" % (len(wins) / len(df) * 100))
    print("Total P&L: Rs.%.0f" % df.pnl.sum())
    if len(wins) > 0:
        print("Avg win: Rs.%.0f" % wins.pnl.mean())
    if len(losses) > 0:
        print("Avg loss: Rs.%.0f" % losses.pnl.mean())
    cum = df.pnl.cumsum()
    dd = cum - cum.cummax()
    print("Max DD: Rs.%.0f" % dd.min())
    print("")
    cols = ["date", "signal", "direction", "entry_prem", "exit_prem", "reason", "pnl"]
    print(df[cols].to_string(index=False))
