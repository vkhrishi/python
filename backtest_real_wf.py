#!/usr/bin/env python
# ============================================================
#  REAL-PREMIUM WALK-FORWARD VALIDATOR  (run ON THE VPS)
#  (NIFTY Fibonacci options strategy)
#
#  WHY THIS FILE EXISTS:
#    backtest.py validates the strategy OFFLINE on a SYNTHETIC option
#    model (no theta/vega/gamma) - good for a quick directional check,
#    but its P&L is approximate. This file runs the SAME fold + luck
#    verdict on bot.py's REAL historical option premiums.
#
#  WHERE TO RUN:
#    On the VPS (root@HriPlay:~/scalper) where the Groww SDK + network
#    work. It needs the REAL growwapi, so - unlike backtest.py - it does
#    NOT stub anything. Do not run it on the VDI (no API there).
#
#  HOW IT STAYS HONEST (single source of truth):
#    It does NOT re-implement the trade logic. It calls bot.py's own
#    run_backtest_fib_real() and just CAPTURES the trades that function
#    already collects (by hooking fetch_history_nifty + the report fn),
#    then folds them. So this can never drift from the live strategy.
#
#  GROWW DATA LIMIT:
#    Groww caps how much 5-min intraday data it returns per request, so a
#    single big pull gets truncated. This script fetches the index history
#    in small windows (default 15 days) and stitches them - tune with
#    --chunk N if it still truncates (smaller = more requests, more data).
#
#  USAGE (on the VPS):
#    python backtest_real_wf.py [days] [folds] [--chunk N] [--htf] [--adx N] [--rr N]
#    e.g.  python backtest_real_wf.py 120 4
#           python backtest_real_wf.py 120 4 --chunk 10
#           python backtest_real_wf.py 120 4 --adx 18
# ============================================================

import sys
import time
import datetime

import bot  # REAL bot.py - NO shims (we want the real Groww API on the VPS)


# -------------------------------------------------------------------
#  Capture hooks - grab what bot.py's real-premium backtest produces
#  without changing bot.py.
# -------------------------------------------------------------------
_captured = {"trades": None, "signals": 0, "diag": None, "candles": None}

# Groww caps how much 5-min intraday data it returns per request, so we
# pull the index history in small windows and stitch them together.
# Tune with the --chunk CLI option if Groww still truncates.
_CHUNK_DAYS = 15

_orig_fetch_history = bot.fetch_history_nifty
_orig_report = bot._print_bt_report_fib


def _fetch_history_capture(groww, days=30):
    """Replacement for bot.fetch_history_nifty that fetches in CHUNKS.
    bot.py asks Groww for the whole span at once, which Groww truncates.
    Here we walk the range in _CHUNK_DAYS windows and merge (dedup by ts)."""
    now = bot.ist_now()
    start_global = now - datetime.timedelta(days=days)
    merged = {}
    win_start = start_global
    n_win = ok_win = 0
    while win_start < now:
        win_end = min(win_start + datetime.timedelta(days=_CHUNK_DAYS), now)
        s = win_start.strftime("%Y-%m-%d 09:15:00")
        e = win_end.strftime("%Y-%m-%d %H:%M:%S")
        n_win += 1
        try:
            res = groww.get_historical_candle_data(
                trading_symbol="NIFTY", exchange="NSE", segment="CASH",
                start_time=s, end_time=e, interval_in_minutes=5)
            raw = res.get("candles", []) if isinstance(res, dict) else []
            got = bot._parse_candles(raw)
            for c in got:
                merged[c["ts"]] = c
            ok_win += 1
            print("  chunk %s -> %s : %d candles" % (s[:10], e[:10], len(got)))
        except Exception as ex:
            print("  chunk %s -> %s FAILED: %s" % (s[:10], e[:10], ex))
        win_start = win_end
        time.sleep(0.4)   # be gentle with the API
    candles = sorted(merged.values(), key=lambda c: c["ts"])
    print("  fetched %d unique candles across %d/%d windows" % (
        len(candles), ok_win, n_win))
    _captured["candles"] = candles
    return candles


def _report_capture(trades, signals, days, approx=True, diag=None):
    _captured["trades"] = trades
    _captured["signals"] = signals
    _captured["diag"] = diag
    # Still print bot.py's own single-window report for reference.
    _orig_report(trades, signals, days, approx=approx, diag=diag)


def _install_capture():
    bot.fetch_history_nifty = _fetch_history_capture
    bot._print_bt_report_fib = _report_capture


# -------------------------------------------------------------------
#  Walk-forward / fragility verdict  (same logic as backtest.py, on
#  REAL-premium trades).
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
    if candles:
        days_seen = sorted({c["ts"][:10] for c in candles})
    else:
        days_seen = sorted({t["day"] for t in trades})
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
    print(" REAL-PREMIUM WALK-FORWARD / OUT-OF-SAMPLE | %d folds" % len(bounds))
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
        print("   -> Edge holds out-of-sample on REAL premiums AND survives luck.")
        print("      Next: forward paper-trade before risking capital.")
    else:
        print("   -> Not robust. Kill/adjust the weakest assumption and re-run.")
        print("      Need: >=75%% folds green, PF>=1.3, +expectancy, >=15 trades,")
        print("      AND profit survives dropping the best fold + top 2 trades.")
    print("=" * 64)
    print(" NOTE: REAL historical option premiums (with costs/slippage).")
    print("=" * 64)


# -------------------------------------------------------------------
#  Runtime experiment toggles (no bot.py edit). Each is a hypothesis to
#  validate on the walk-forward, NOT a knob to tune until this one
#  sample passes (that would be overfitting).
# -------------------------------------------------------------------
def _apply_overrides(args):
    active = []
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
    return active


def main():
    args = sys.argv[1:]

    # Positional ints: first = days (default 60), second = folds (default 4).
    # Skip the value that follows --adx / --rr / --chunk so it isn't read as
    # days/folds.
    ints = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a in ("--adx", "--rr", "--chunk"):
            skip = True
            continue
        if a.isdigit():
            ints.append(int(a))
    days = ints[0] if len(ints) >= 1 else 60
    folds = ints[1] if len(ints) >= 2 else 4

    # Optional chunk size for the history pull.
    global _CHUNK_DAYS
    for i, a in enumerate(args):
        if a == "--chunk" and i + 1 < len(args) and args[i + 1].isdigit():
            _CHUNK_DAYS = max(1, int(args[i + 1]))

    overrides = _apply_overrides(args)

    print("=" * 64)
    print(" REAL-PREMIUM VALIDATION | days=%d folds=%d chunk=%dd" % (
        days, folds, _CHUNK_DAYS))
    if overrides:
        print(" Overrides: " + " | ".join(overrides))
    print("=" * 64)

    _install_capture()
    bot.run_backtest_fib_real(days=days)

    trades = _captured["trades"]
    if not trades:
        print("\nNo trades collected - nothing to fold. "
              "Check the diagnostics above for why setups died.")
        return
    walk_forward(trades, _captured["candles"], folds=folds)


if __name__ == "__main__":
    main()
