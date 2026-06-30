#!/usr/bin/env python
# ============================================================
#  STANDALONE BACKTEST + WALK-FORWARD VALIDATOR for bot.py
#  (NIFTY Fibonacci options strategy)
#
#  WHY A SEPARATE FILE:
#    - Does NOT modify bot.py. It imports bot.py's EXACT strategy
#      functions so the backtest can never silently drift from the
#      live logic (single source of truth).
#    - Runs FULLY OFFLINE on any machine: the trading SDK, network
#      and Linux log path that bot.py touches at import time are
#      stubbed out below, so no credentials / internet are needed.
#
#  WHAT IT MEASURES:
#    - Full backtest report (win rate, P&L, profit factor, drawdown).
#    - WALK-FORWARD: splits history into time folds and prints a blunt
#      PASS/FAIL verdict. An edge that only wins in one lucky stretch
#      gets FAIL -> that is your "kill the weak idea" signal.
#
#  OPTION P&L IS APPROXIMATE:
#    Uses bot.py's synthetic delta model (no theta/vega/gamma), so it
#    only needs NIFTY INDEX 5-min candles -> runs with zero API access.
#    Treat the output as a DIRECTIONAL edge check, then confirm with
#    bot.py's `backtest_real` (real premiums) and paper trading.
#
#  USAGE:
#    python backtest.py <data.csv|data.json> [folds]
#    python backtest.py            # auto-uses bot.py's data cache if present
#
#  DATA FORMAT (CSV): a header row with columns (case-insensitive):
#    datetime/date(+time), open, high, low, close, [volume]
#    e.g.  2026-06-01 09:15:00,24010,24025,24000,24020,0
#  JSON: a list of {ts,open,high,low,close,volume} or bot's cache
#    object {"candles": [...]}.
# ============================================================

import sys
import os
import csv
import json
import types
import logging
import datetime


# -------------------------------------------------------------------
#  Neutralise bot.py's import-time side effects BEFORE importing it.
#  bot.py imports the Groww SDK + pyotp, fetches its public IP, and
#  configures a log file at a Linux path. None of that is wanted for an
#  offline backtest, so we inject lightweight stand-ins.
# -------------------------------------------------------------------
def _install_import_shims():
    # Trading SDK (almost never installed on a dev box)
    if "growwapi" not in sys.modules:
        m = types.ModuleType("growwapi")
        class _Stub:
            def __init__(self, *a, **k):
                pass
        m.GrowwAPI = _Stub
        m.GrowwFeed = _Stub
        sys.modules["growwapi"] = m

    if "pyotp" not in sys.modules:
        m = types.ModuleType("pyotp")
        m.TOTP = lambda *a, **k: types.SimpleNamespace(now=lambda: "000000")
        sys.modules["pyotp"] = m

    # requests: stub so the import-time IP fetch makes NO network call
    if "requests" not in sys.modules:
        m = types.ModuleType("requests")
        def _no_net(*a, **k):
            raise RuntimeError("offline backtest: network disabled")
        m.get = _no_net
        sys.modules["requests"] = m

    # urllib3.util.connection: bot.force_ipv4() patches create_connection
    if "urllib3" not in sys.modules:
        u3 = types.ModuleType("urllib3")
        u3util = types.ModuleType("urllib3.util")
        u3conn = types.ModuleType("urllib3.util.connection")
        u3conn.create_connection = lambda *a, **k: None
        u3util.connection = u3conn
        u3.util = u3util
        sys.modules["urllib3"] = u3
        sys.modules["urllib3.util"] = u3util
        sys.modules["urllib3.util.connection"] = u3conn

    # bot.py adds a FileHandler to a Linux path at import -> redirect to no-op
    logging.FileHandler = lambda *a, **k: logging.NullHandler()


_install_import_shims()

# Make sure we can import the sibling bot.py regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot  # noqa: E402  (imported after shims on purpose)

# Quieten bot.py's INFO chatter during the backtest
logging.getLogger().setLevel(logging.WARNING)


# -------------------------------------------------------------------
#  Data loading (CSV / JSON -> bot's candle dict format)
# -------------------------------------------------------------------
_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M",
    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
)


def _norm_ts(date_part, time_part=None):
    """Normalise assorted timestamp shapes into 'YYYY-MM-DD HH:MM:SS'."""
    s = str(date_part).strip()
    if time_part is not None and str(time_part).strip():
        s = s + " " + str(time_part).strip()
    s = s.replace("T", " ").strip()

    # Epoch seconds?
    try:
        if s.isdigit() and len(s) >= 9:
            dt = datetime.datetime.utcfromtimestamp(int(s)) + datetime.timedelta(hours=5, minutes=30)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OverflowError):
        pass

    for fmt in _TS_FORMATS:
        try:
            return datetime.datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    # Date only -> assume market open
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            d = datetime.datetime.strptime(s, fmt)
            return d.strftime("%Y-%m-%d 09:15:00")
        except ValueError:
            continue
    raise ValueError("Unrecognised timestamp: %r" % date_part)


def _load_csv(path):
    candles = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        cols = {c.lower().strip(): c for c in reader.fieldnames}

        def pick(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            return None

        ts_c = pick("ts", "timestamp", "datetime", "date_time", "date")
        time_c = pick("time")
        o_c = pick("open", "o")
        h_c = pick("high", "h")
        l_c = pick("low", "l")
        cl_c = pick("close", "c", "ltp")
        v_c = pick("volume", "vol", "v")
        if not all([ts_c, o_c, h_c, l_c, cl_c]):
            raise ValueError(
                "CSV needs datetime + open/high/low/close columns. Found: %s"
                % reader.fieldnames)

        for row in reader:
            try:
                ts = _norm_ts(row[ts_c], row[time_c] if (time_c and time_c != ts_c) else None)
                candles.append({
                    "ts": ts,
                    "open": float(row[o_c]),
                    "high": float(row[h_c]),
                    "low": float(row[l_c]),
                    "close": float(row[cl_c]),
                    "volume": float(row[v_c]) if (v_c and row.get(v_c) not in (None, "")) else 0.0,
                })
            except (ValueError, KeyError):
                continue
    return candles


def _load_json(path):
    with open(path) as f:
        data = json.load(f)
    raw = data.get("candles", []) if isinstance(data, dict) else data
    candles = []
    for c in raw:
        if isinstance(c, dict) and "ts" in c:
            candles.append({
                "ts": _norm_ts(c["ts"]),
                "open": float(c["open"]), "high": float(c["high"]),
                "low": float(c["low"]), "close": float(c["close"]),
                "volume": float(c.get("volume", 0) or 0),
            })
        elif isinstance(c, (list, tuple)) and len(c) >= 5:
            candles.append({
                "ts": _norm_ts(c[0]),
                "open": float(c[1]), "high": float(c[2]),
                "low": float(c[3]), "close": float(c[4]),
                "volume": float(c[5]) if len(c) > 5 and c[5] is not None else 0.0,
            })
    return candles


def load_candles(path):
    if path.lower().endswith(".json"):
        candles = _load_json(path)
    else:
        candles = _load_csv(path)
    candles.sort(key=lambda c: c["ts"])
    # de-dup by timestamp, keep last
    seen = {}
    for c in candles:
        seen[c["ts"]] = c
    return [seen[k] for k in sorted(seen)]


# -------------------------------------------------------------------
#  Strategy replay (APPROX option P&L) using bot.py's exact functions
# -------------------------------------------------------------------
def collect_trades(candles):
    """Replay the live Fibonacci engine over `candles` with bot.py's own
    functions and simulate each day's option trade on the synthetic premium
    model. Returns (trades, signals, diag) - mirrors bot.run_backtest_fib."""
    ts_index = {c["ts"]: i for i, c in enumerate(candles)}
    days_seen = sorted({c["ts"][:10] for c in candles})
    scan_start = datetime.time(bot.IMPULSE_END_HOUR, bot.IMPULSE_END_MIN)
    cutoff = datetime.time(bot.NO_TRADE_AFTER_HOUR, bot.NO_TRADE_AFTER_MIN)

    trades, signals = [], 0
    days_total = days_with_fib = 0
    reason_tally = {}

    for day in days_seen:
        d0 = datetime.datetime.strptime(day, "%Y-%m-%d").date()
        days_total += 1
        fib_data = bot.compute_impulse_and_fibs(candles, target_date=d0)
        if not fib_data:
            continue
        days_with_fib += 1
        direction = fib_data["direction"]

        for c in candles:
            dt = datetime.datetime.strptime(c["ts"], "%Y-%m-%d %H:%M:%S")
            if dt.date() != d0:
                continue
            t = dt.time()
            if t < scan_start or t >= cutoff:
                continue
            idx = ts_index[c["ts"]]
            if idx < 30 or idx + 1 >= len(candles):
                continue

            res = bot.check_fib_retracement(candles[:idx + 1], fib_data, now=dt)
            if res["signal"] not in ("CE_BUY", "PE_BUY"):
                reason = res.get("details", {}).get("reason", "unknown")
                reason_tally[reason] = reason_tally.get(reason, 0) + 1
                continue
            if res.get("confidence") not in ("HIGH", "MED"):
                continue

            if bot.HTF_TREND_ENABLED:
                htf = bot.resample_to_htf(candles[:idx + 1], minutes=bot.HTF_INTERVAL_MIN)
                htf_trend, _, _ = bot.compute_htf_trend(htf)
                if htf_trend is not None and htf_trend != direction:
                    reason_tally["HTF trend mismatch"] = reason_tally.get("HTF trend mismatch", 0) + 1
                    continue

            signals += 1
            last_close = candles[idx]["close"]
            if direction == "BULL":
                fib_sl_distance = last_close - fib_data["fib_sl"]
            else:
                fib_sl_distance = fib_data["fib_sl"] - last_close
            if fib_sl_distance <= 0:
                fib_sl_distance = None

            entry_spot = candles[idx + 1]["open"]
            forward = []
            for fc in candles[idx + 1:]:
                fdt = datetime.datetime.strptime(fc["ts"], "%Y-%m-%d %H:%M:%S")
                if fdt.date() != d0 or fdt.time() > bot.BT_SQUAREOFF:
                    break
                forward.append(fc)
            if not forward:
                break

            sim = bot._simulate_fib_trade(direction, entry_spot, fib_sl_distance, forward)
            if sim:
                sim["day"] = day
                sim["dir"] = "CE" if direction == "BULL" else "PE"
                sim["conf"] = res.get("confidence")
                sim["entry_spot"] = round(entry_spot, 1)
                trades.append(sim)
            break  # first valid signal per day

    diag = {"days_total": days_total, "days_with_fib": days_with_fib,
            "reason_tally": reason_tally}
    return trades, signals, diag


# -------------------------------------------------------------------
#  Walk-forward / out-of-sample robustness check
# -------------------------------------------------------------------
def _stats(trades):
    if not trades:
        return None
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total = sum(t["pnl"] for t in trades)
    gw = sum(t["pnl"] for t in wins)
    gl = -sum(t["pnl"] for t in losses)
    eq = peak = mdd = 0.0
    for t in trades:
        eq += t["pnl"]
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "n": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100.0,
        "net": total, "expectancy": total / len(trades),
        "profit_factor": (gw / gl) if gl > 0 else float("inf"),
        "max_dd": mdd,
    }


def _pf_str(pf):
    return "%.2f" % pf if pf != float("inf") else "inf"


def walk_forward(trades, candles, folds=4):
    days_seen = sorted({c["ts"][:10] for c in candles})
    if folds < 2:
        folds = 2
    fold_size = max(1, len(days_seen) // folds)
    bounds = []
    for f in range(folds):
        start = f * fold_size
        end = len(days_seen) if f == folds - 1 else (f + 1) * fold_size
        if start >= len(days_seen):
            break
        bounds.append((days_seen[start], days_seen[end - 1]))

    print("\n" + "=" * 64)
    print(" WALK-FORWARD / OUT-OF-SAMPLE | %d folds" % len(bounds))
    print(" (edge must hold ACROSS folds - one lucky fold proves nothing)")
    print("=" * 64)

    profitable = 0
    fold_nets = []
    for i, (lo, hi) in enumerate(bounds, 1):
        ft = [t for t in trades if lo <= t["day"] <= hi]
        s = _stats(ft)
        print("-" * 64)
        print(" Fold %d  %s -> %s" % (i, lo, hi))
        if not s:
            print("   no trades")
            fold_nets.append(0.0)
            continue
        print("   trades %2d | win %.0f%% | net Rs.%+.0f | PF %s | exp Rs.%+.0f | maxDD -Rs.%.0f" % (
            s["n"], s["win_rate"], s["net"], _pf_str(s["profit_factor"]),
            s["expectancy"], s["max_dd"]))
        fold_nets.append(s["net"])
        if s["net"] > 0:
            profitable += 1

    overall = _stats(trades)
    print("=" * 64)
    if not overall:
        print(" No trades generated - strategy too restrictive on this data.")
        print("=" * 64)
        return
    print(" OVERALL  trades %d | win %.0f%% | net Rs.%+.0f | PF %s | exp Rs.%+.0f | maxDD -Rs.%.0f" % (
        overall["n"], overall["win_rate"], overall["net"], _pf_str(overall["profit_factor"]),
        overall["expectancy"], overall["max_dd"]))
    print(" Return on capital: %+.1f%% (capital Rs.%d)" % (
        overall["net"] / bot.CAPITAL_RUPEES * 100.0, bot.CAPITAL_RUPEES))
    print(" Profitable folds : %d / %d" % (profitable, len(bounds)))

    # --- Fragility: is the profit real, or just a few lucky outliers? ---
    net_ex_best_fold = overall["net"] - max(fold_nets) if fold_nets else overall["net"]
    pnls_sorted = sorted((t["pnl"] for t in trades), reverse=True)
    top2 = sum(pnls_sorted[:2])
    net_ex_top2 = overall["net"] - top2
    print("-" * 64)
    print(" FRAGILITY CHECK (profit should survive removing a little luck):")
    print("   Net excluding BEST fold   : Rs.%+.0f%s" % (
        net_ex_best_fold, "   <- collapses!" if net_ex_best_fold <= 0 else ""))
    print("   Net excluding TOP 2 trades: Rs.%+.0f%s" % (
        net_ex_top2, "   <- collapses!" if net_ex_top2 <= 0 else ""))
    robust_to_luck = net_ex_best_fold > 0 and net_ex_top2 > 0

    passed = (
        profitable >= max(2, int(0.75 * len(bounds)))
        and overall["profit_factor"] >= 1.3
        and overall["expectancy"] > 0
        and overall["n"] >= 15
        and robust_to_luck
    )
    print("=" * 64)
    print(" VERDICT: %s" % ("PASS" if passed else "FAIL"))
    if passed:
        print("   -> Edge holds out-of-sample AND survives the luck check.")
        print("      Confirm on REAL premiums (bot.py backtest_real), paper-trade.")
    else:
        print("   -> Not robust. Kill/adjust the weakest assumption and re-run.")
        print("      Need: >=75%% folds green, PF>=1.3, +expectancy, >=15 trades,")
        print("      AND profit survives dropping the best fold + top 2 trades.")
    print("=" * 64)
    print(" NOTE: option P&L APPROX (synthetic delta, no theta/vega/gamma).")
    print("=" * 64)


# -------------------------------------------------------------------
#  Entry point
# -------------------------------------------------------------------
def _resolve_data_path(argv):
    for a in argv[1:]:
        if a.lower().endswith((".csv", ".json")):
            return a
    # Fall back to bot.py's own index cache if it exists
    cache = getattr(bot, "INDEX_CACHE", None)
    if cache and os.path.exists(cache):
        return cache
    return None


def _apply_overrides(argv):
    """Apply STRUCTURAL experiment toggles at runtime WITHOUT editing bot.py.
    Each is a hypothesis to validate on the walk-forward, not a knob to tune
    until this one sample passes (that would be overfitting). Returns a list of
    human-readable override descriptions for the report header."""
    active = []
    args = argv[1:]
    for i, a in enumerate(args):
        if a == "--htf":
            bot.HTF_TREND_ENABLED = True
            active.append("HTF 15M trend filter = ON")
        elif a == "--adx" and i + 1 < len(args):
            try:
                bot.MIN_ADX_FOR_TRADE = float(args[i + 1])
                active.append("MIN_ADX_FOR_TRADE = %g" % bot.MIN_ADX_FOR_TRADE)
            except ValueError:
                pass
        elif a == "--rr" and i + 1 < len(args):
            try:
                bot.MIN_RR_RATIO = float(args[i + 1])
                active.append("MIN_RR_RATIO = %g" % bot.MIN_RR_RATIO)
            except ValueError:
                pass
        elif a == "--slatr" and i + 1 < len(args):
            try:
                bot.MAX_SL_ATR_MULT = float(args[i + 1])
                active.append("MAX_SL_ATR_MULT = %g" % bot.MAX_SL_ATR_MULT)
            except ValueError:
                pass
    return active


def main():
    # folds = first BARE integer arg (not the value following --adx/--rr)
    folds = 4
    skip_next = False
    for a in sys.argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if a in ("--adx", "--rr", "--slatr"):
            skip_next = True
            continue
        if a.isdigit():
            folds = int(a)

    overrides = _apply_overrides(sys.argv)

    path = _resolve_data_path(sys.argv)
    if not path:
        print("No data file given and no cache found.\n")
        print("Usage: python backtest.py <data.csv|data.json> [folds] [--htf] [--adx N] [--rr N] [--slatr N]\n")
        print("Provide NIFTY index 5-min candles as CSV with columns:")
        print("  datetime, open, high, low, close[, volume]")
        print("or JSON list of {ts,open,high,low,close,volume}.")
        return

    print("Loading candles from: %s" % path)
    try:
        candles = load_candles(path)
    except Exception as e:
        print("Failed to load data: %s" % e)
        return

    if len(candles) < 60:
        print("Not enough candles (%d). Need >=60 (several trading days)." % len(candles))
        return

    print("Loaded %d candles (%s -> %s)" % (
        len(candles), candles[0]["ts"], candles[-1]["ts"]))
    if overrides:
        print("Overrides: " + " | ".join(overrides))
    else:
        print("Overrides: none (baseline strategy config)")

    trades, signals, diag = collect_trades(candles)

    days = len({c["ts"][:10] for c in candles})
    bot._print_bt_report_fib(trades, signals, days, approx=True, diag=diag)
    walk_forward(trades, candles, folds=folds)


if __name__ == "__main__":
    main()
