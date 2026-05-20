# ============================================
# STEP 1: Install dependencies
# ============================================
pip install pandas numpy kaggle

# ============================================
# STEP 2: Setup Kaggle API key
# ============================================
# Go to https://www.kaggle.com/settings ? Create New Token
# It downloads kaggle.json, then:
mkdir -p ~/.kaggle
# Upload kaggle.json to your VPS, then:
mv kaggle.json ~/.kaggle/
chmod 600 ~/.kaggle/kaggle.json

# ============================================
# STEP 3: Download NIFTY 1-min data
# ============================================
cd /root/scalper
kaggle datasets download -d debashis74017/nifty-50-minute-data
unzip nifty-50-minute-data.zip -d nifty_raw

# Check what files you got:
ls -la nifty_raw/

# ============================================
# STEP 4: Resample 1-min ? 5-min
# ============================================
# Create this file: resample.py
cat > resample.py << 'EOF'
import pandas as pd
import glob, sys, os

# Find the NIFTY 50 index file (adjust if filename differs)
files = glob.glob("nifty_raw/*NIFTY*50*") + glob.glob("nifty_raw/*nifty*50*") + glob.glob("nifty_raw/*NIFTY*")
print("Found files:", files)

if not files:
    print("ERROR: No NIFTY file found. Check nifty_raw/ folder and update filename below.")
    sys.exit(1)

# Use first match - change if needed
src = files[0]
print(f"Using: {src}")

df = pd.read_csv(src)
print(f"Columns: {list(df.columns)}")
print(f"First 3 rows:\n{df.head(3)}")

# Auto-detect timestamp column
ts_col = None
for col in df.columns:
    if col.lower() in ('date', 'datetime', 'timestamp', 'ts', 'time'):
        ts_col = col
        break
if ts_col is None:
    ts_col = df.columns[0]  # assume first column
print(f"Timestamp column: {ts_col}")

df['ts'] = pd.to_datetime(df[ts_col])
df = df.sort_values('ts')

# Auto-detect OHLCV columns
col_map = {}
for col in df.columns:
    cl = col.lower().strip()
    if cl == 'open': col_map['open'] = col
    elif cl == 'high': col_map['high'] = col
    elif cl == 'low': col_map['low'] = col
    elif cl == 'close': col_map['close'] = col
    elif cl in ('volume', 'vol'): col_map['volume'] = col

print(f"Column mapping: {col_map}")

if 'volume' not in col_map:
    df['volume'] = 0
    col_map['volume'] = 'volume'

df = df.set_index('ts')
df5 = df.resample('5min').agg({
    col_map['open']: 'first',
    col_map['high']: 'max',
    col_map['low']: 'min',
    col_map['close']: 'last',
    col_map['volume']: 'sum'
}).dropna()

# Rename to standard columns
df5.columns = ['open', 'high', 'low', 'close', 'volume']
df5.index.name = 'ts'

# Filter market hours only (9:15 to 15:30 IST)
df5 = df5.between_time('09:15', '15:30')

df5.to_csv('nifty_5m.csv')
print(f"\nDone! {len(df5)} bars")
print(f"Range: {df5.index.min()} to {df5.index.max()}")
print(f"Saved: nifty_5m.csv ({os.path.getsize('nifty_5m.csv') / 1024 / 1024:.1f} MB)")
EOF

python3 resample.py

# ============================================
# STEP 5: Save the backtest script
# ============================================
# Copy the backtest.py code I gave you earlier into this file:
nano /root/scalper/backtest.py
# Paste the full code, save with Ctrl+X ? Y ? Enter

# ============================================
# STEP 6: RUN THE BACKTEST
# ============================================
cd /root/scalper

# 2 year backtest
python3 backtest.py --csv nifty_5m.csv --start 2024-01-01 --end 2025-12-31 --out trades.csv

# ============================================
# STEP 7: View results
# ============================================
# Summary prints automatically. To see individual trades:
cat trades.csv | head -20

# Or pretty-print:
python3 -c "
import pandas as pd
df = pd.read_csv('trades.csv')
print(f'Total trades: {len(df)}')
print(f'Winners: {len(df[df.pnl>0])}')
print(f'Losers: {len(df[df.pnl<=0])}')
print(f'Win rate: {len(df[df.pnl>0])/len(df)*100:.1f}%')
print(f'Total P&L: Rs.{df.pnl.sum():.0f}')
print(f'Avg win: Rs.{df[df.pnl>0].pnl.mean():.0f}')
print(f'Avg loss: Rs.{df[df.pnl<=0].pnl.mean():.0f}')
print(f'Max DD: Rs.{(df.pnl.cumsum() - df.pnl.cumsum().cummax()).min():.0f}')
print()
print(df[['date','signal','entry_prem','exit_prem','reason','pnl']].to_string(index=False))
"
