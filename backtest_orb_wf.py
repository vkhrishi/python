#!/usr/bin/env python
# ============================================================
#  REAL-PREMIUM WALK-FORWARD VALIDATOR  (run ON THE VPS)
#  for SM/bot.py  --  NIFTY "BAG + ORB + FVG" options strategy
#
#  Mirror of SM2/backtest_real_wf.py, but for the ORB bot. The ORB
#  bot only ships an APPROXIMATE backtest (synthetic delta model); this
#  validates it on REAL historical option premiums + the same blunt
#  fold + fragility verdict, so the two strategies are judged the same.
#
#  WHERE TO RUN:
#    On the VPS (root@HriPlay:~/scalper) where the Groww SDK + network
#    work, sitting next to SM/bot.py. NOT on the VDI (no API there).
#
#  HOW IT STAYS HONEST (single source of truth):
#    It does NOT re-implement the strategy. It calls bot.compute_orb_levels
#    + bot.compute_signal for entries, and bot.calc_sl_tp / get_catastrophic_sl
#    / net_rr_after_costs + the bot's own exit constants for the trade sim.
#    Only the OPTION-PREMIUM fetch is swapped to the correct backtesting API
#    (the bot's deprecated get_historical_candle_data + old trading symbol
#    never resolves expired FNO contracts).
#
#  GROWW DATA LIMIT:
#    5-min history is capped PER REQUEST (~30 days), not by depth, so index
#    candles are pulled in small windows and stitched; single-day option
#    requests work across the full span. Tune the window with --chunk N.
#
#  USAGE (on the VPS):
#    python backtest_orb_wf.py [days] [folds] [--chunk N] [--adx N]
#    e.g.  python backtest_orb_wf.py 120 4
# ============================================================

import sys
import time
import datetime

import bot  # SM/bot.py - REAL (no shims; we want the real Groww API on the VPS)


# -------------------------------------------------------------------
#  Index history: pull in CHUNKS (Groww caps the per-request range for
#  5-min data) and stitch, dedup by timestamp.
# -------------------------------------------------------------------
_CHUNK_DAYS = 15
_expiry_cache = {}   # (year, month) -> sorted [date, ...]


def _g(groww, name, default):
    return getattr(groww, name, default)


def _fetch_history_chunked(groww, days):
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
        time.sleep(0.4)
    candles = sorted(merged.values(), key=lambda c: c["ts"])
    print("  fetched %d unique candles across %d/%d windows" % (
        len(candles), ok_win, n_win))
    return candles


# -------------------------------------------------------------------
#  Option premium history via the CORRECT backtesting API.
#  (bot.py's _fetch path uses the deprecated method + old live-trading
#  symbol, which never resolves expired FNO contracts.)
# -------------------------------------------------------------------
def _real_expiry_on_or_after(groww, day):
    d0 = datetime.datetime.strptime(day, "%Y-%m-%d").date()
    nxt = (d0.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
    cands = []
    for yy, mm in {(d0.year, d0.month), (nxt.year, nxt.month)}:
        key = (yy, mm)
        if key not in _expiry_cache:
            try:
                r = groww.get_expiries(
                    exchange=_g(groww, "EXCHANGE_NSE", "NSE"),
                    underlying_symbol="NIFTY", year=yy, month=mm)
                exps = r.get("expiries", []) if isinstance(r, dict) else []
                _expiry_cache[key] = sorted(
                    datetime.datetime.strptime(x, "%Y-%m-%d").date() for x in exps)
            except Exception:
                _expiry_cache[key] = []
        cands.extend(_expiry_cache[key])
    for ex in sorted(set(cands)):
        if ex >= d0:
            return ex
    return None


def _fetch_option_history(groww, expiry_date, strike, opt_type, day):
    gsym = "NSE-NIFTY-%s-%d-%s" % (expiry_date.strftime("%d%b%y"), int(round(strike)), opt_type)
    start_dt = "%s 09:15:00" % day
    end_dt = "%s 15:30:00" % day
    try:
        res = groww.get_historical_candles(
            exchange=_g(groww, "EXCHANGE_NSE", "NSE"),
            segment=_g(groww, "SEGMENT_FNO", "FNO"),
            groww_symbol=gsym, start_time=start_dt, end_time=end_dt,
            candle_interval=_g(groww, "CANDLE_INTERVAL_MIN_5", 5))
        raw = res.get("candles", []) if isinstance(res, dict) else []
        return bot._parse_candles(raw)
    except Exception as e:
        print("  opt history failed %s (%s): %s" % (gsym, day, e))
        return []


# -------------------------------------------------------------------
#  REAL-premium trade simulation. Mirrors the ORB bot's synthetic
#  _simulate_option_trade exit logic exactly, but on actual option
#  OHLC candles. Uses the bot's own SL/TP/cost helpers + constants.
# -------------------------------------------------------------------
def _simulate_premium_trade(entry_premium, prem_forward):
    qty = bot.LOT_SIZE * bot.LOTS_TO_TRADE
    sl_price, target_price, sl_drop, tp_rise, sl_pct, rr = bot.calc_sl_tp(entry_premium, qty)
    if rr < bot.MIN_RR_RATIO:
        return None
    net_rr, rt_cost, net_reward = bot.net_rr_after_costs(sl_drop, tp_rise, qty, entry_premium)
    if net_reward <= 0 or net_rr < bot.MIN_NET_RR:
        return None

    catastrophic_sl = bot.get_catastrophic_sl(entry_premium, qty)
    partial_target = round(entry_premium + sl_drop * bot.PARTIAL_TARGET_RR, 1)
    partial_qty = int(qty * bot.PARTIAL_EXIT_PCT / 100)
    partial_qty = max(partial_qty, bot.LOT_SIZE)
    if partial_qty >= qty:
        partial_qty = 0   # inert at 1 lot, exactly like live

    trailing_sl = sl_price
    highest = entry_premium
    partial_done = False
    realized = 0.0
    remaining = qty
    reason = "SQUAREOFF"

    for i, c in enumerate(prem_forward):
        minutes_held = (i + 1) * 5
        low = c["low"]
        high = c["high"]
        close = c["close"]

        if minutes_held < bot.MIN_HOLD_MINUTES:
            if low <= catastrophic_sl:
                realized += (catastrophic_sl - entry_premium) * remaining
                reason = "CATASTROPHIC"
                break
            if high >= target_price:
                realized += (target_price - entry_premium) * remaining
                reason = "TAKE_PROFIT"
                break
            continue

        if low <= trailing_sl:
            realized += (trailing_sl - entry_premium) * remaining
            reason = "STOP_LOSS" if trailing_sl == sl_price else "TRAIL_STOP"
            break

        if partial_qty > 0 and not partial_done and high >= partial_target:
            realized += (partial_target - entry_premium) * partial_qty
            remaining -= partial_qty
            partial_done = True
            trailing_sl = max(trailing_sl, entry_premium)

        if high >= target_price:
            realized += (target_price - entry_premium) * remaining
            reason = "TAKE_PROFIT"
            break

        if bot.TRAILING_SL_ENABLED and high > highest:
            highest = high
            open_profit = highest - entry_premium
            if open_profit >= tp_rise * bot.TRAILING_SL_TRIGGER:
                new_sl = entry_premium + open_profit * bot.TRAILING_SL_STEP
                trailing_sl = max(trailing_sl, new_sl)

        if (bot.STAGNATION_EXIT_ENABLED and minutes_held >= bot.STAGNATION_EXIT_MIN
                and (close - entry_premium) < sl_drop * bot.STAGNATION_MIN_PROFIT_RR):
            realized += (close - entry_premium) * remaining
            reason = "STAGNATION"
            break
    else:
        realized += (prem_forward[-1]["close"] - entry_premium) * remaining

    net = realized - rt_cost
    return {"pnl": round(net, 0), "gross": round(realized, 0), "cost": round(rt_cost, 0),
            "reason": reason, "entry_prem": round(entry_premium, 1)}


# -------------------------------------------------------------------
#  Replay the ORB strategy day-by-day on REAL option premiums.
# -------------------------------------------------------------------
def collect_trades(groww, candles):
    ts_index = {c["ts"]: i for i, c in enumerate(candles)}
    days_seen = sorted({c["ts"][:10] for c in candles})
    scan_start = datetime.time(9, 30)   # ORB window is 9:15-9:30
    cutoff = datetime.time(bot.NO_TRADE_AFTER_HOUR, bot.NO_TRADE_AFTER_MIN)

    trades, signals, skipped = [], 0, 0
    days_total = days_with_orb = 0
    reason_tally = {}

    for day in days_seen:
        d0 = datetime.datetime.strptime(day, "%Y-%m-%d").date()
        days_total += 1
        orb = bot.compute_orb_levels(candles, target_date=d0)
        if not orb:
            continue
        days_with_orb += 1

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

            res = bot.compute_signal(candles[:idx + 1], orb, now=dt)
            sig = res.get("signal")
            if sig not in ("CE_BUY", "PE_BUY"):
                reason = res.get("details", {}).get("reason", "unknown")
                reason_tally[reason] = reason_tally.get(reason, 0) + 1
                continue
            if res.get("confidence") not in ("HIGH", "MED"):
                continue

            signals += 1
            opt_type = "CE" if sig == "CE_BUY" else "PE"
            entry_spot = candles[idx + 1]["open"]
            atm = bot.get_atm_strike(entry_spot)
            strike = (atm - bot.ITM_OFFSET) if opt_type == "CE" else (atm + bot.ITM_OFFSET)
            expiry = _real_expiry_on_or_after(groww, day)
            if expiry is None:
                skipped += 1
                break

            prem_candles = _fetch_option_history(groww, expiry, strike, opt_type, day)
            if not prem_candles:
                skipped += 1
                break

            entry_dt = datetime.datetime.strptime(candles[idx + 1]["ts"], "%Y-%m-%d %H:%M:%S")
            prem_forward = []
            entry_premium = None
            for pc in prem_candles:
                pdt = datetime.datetime.strptime(pc["ts"], "%Y-%m-%d %H:%M:%S")
                if pdt < entry_dt:
                    continue
                if pdt.time() > bot.BT_SQUAREOFF:
                    break
                if entry_premium is None:
                    entry_premium = pc["open"]
                prem_forward.append(pc)

            if entry_premium is None or entry_premium <= 0 or not prem_forward:
                skipped += 1
                break

            sim = _simulate_premium_trade(entry_premium, prem_forward)
            if sim:
                sim["day"] = day
                sim["dir"] = opt_type
                sim["conf"] = res.get("confidence")
                sim["entry_spot"] = round(entry_spot, 1)
                trades.append(sim)
            break   # first valid signal per day

    diag = {"days_total": days_total, "days_with_orb": days_with_orb,
            "reason_tally": reason_tally, "skipped": skipped}
    return trades, signals, diag


# -------------------------------------------------------------------
#  Stats + walk-forward / fragility verdict (same yardstick as the Fib
#  harness, on REAL-premium trades).
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


def _print_breakdown(trades, diag):
    print("-" * 64)
    print(" DIAGNOSTICS:")
    print("   Days scanned        : %d" % diag.get("days_total", 0))
    print("   Days w/ valid ORB   : %d" % diag.get("days_with_orb", 0))
    print("   Signal days skipped : %d (no option history)" % diag.get("skipped", 0))
    tally = diag.get("reason_tally", {})
    if tally:
        print("   Top NO_TRADE reasons (candles rejected):")
        for reason, cnt in sorted(tally.items(), key=lambda kv: -kv[1])[:12]:
            print("     %5d  %s" % (cnt, reason))
    if not trades:
        return
    print("-" * 64)
    print(" BY EXIT REASON:")
    reasons = {}
    for t in trades:
        r = reasons.setdefault(t["reason"], {"n": 0, "pnl": 0.0, "w": 0})
        r["n"] += 1
        r["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            r["w"] += 1
    for name in sorted(reasons, key=lambda k: reasons[k]["pnl"]):
        r = reasons[name]
        print("   %-13s | %2d | %dW | Rs.%+.0f" % (name, r["n"], r["w"], r["pnl"]))
    print(" BY DIRECTION:")
    for dn in ("CE", "PE"):
        sub = [t for t in trades if t["dir"] == dn]
        if sub:
            w = len([t for t in sub if t["pnl"] > 0])
            print("   %s | %2d | %dW (%.0f%%) | Rs.%+.0f" % (
                dn, len(sub), w, w / len(sub) * 100, sum(t["pnl"] for t in sub)))


def walk_forward(trades, candles, folds=4):
    days_seen = sorted({c["ts"][:10] for c in candles}) if candles else \
        sorted({t["day"] for t in trades})
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
    print(" ORB REAL-PREMIUM WALK-FORWARD / OUT-OF-SAMPLE | %d folds" % len(bounds))
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


def _apply_overrides(args):
    active = []
    for i, a in enumerate(args):
        if a == "--adx" and i + 1 < len(args):
            try:
                bot.MIN_ADX_FOR_TRADE = float(args[i + 1])
                active.append("MIN_ADX_FOR_TRADE = %g" % bot.MIN_ADX_FOR_TRADE)
            except ValueError:
                pass
    return active


def main():
    args = sys.argv[1:]

    ints = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a in ("--adx", "--chunk"):
            skip = True
            continue
        if a.isdigit():
            ints.append(int(a))
    days = ints[0] if len(ints) >= 1 else 60
    folds = ints[1] if len(ints) >= 2 else 4

    global _CHUNK_DAYS
    for i, a in enumerate(args):
        if a == "--chunk" and i + 1 < len(args) and args[i + 1].isdigit():
            _CHUNK_DAYS = max(1, int(args[i + 1]))

    overrides = _apply_overrides(args)

    print("=" * 64)
    print(" ORB REAL-PREMIUM VALIDATION | days=%d folds=%d chunk=%dd" % (
        days, folds, _CHUNK_DAYS))
    if overrides:
        print(" Overrides: " + " | ".join(overrides))
    print("=" * 64)

    groww = bot.login()
    candles = _fetch_history_chunked(groww, days)
    if len(candles) < 60:
        print("Not enough history fetched: %d candles" % len(candles))
        return
    print("Loaded %d candles (%s -> %s)" % (
        len(candles), candles[0]["ts"], candles[-1]["ts"]))

    trades, signals, diag = collect_trades(groww, candles)
    print("\n Signals evaluated : %d | Trades taken: %d" % (signals, len(trades)))
    _print_breakdown(trades, diag)

    if not trades:
        print("\nNo trades collected - nothing to fold. See diagnostics above.")
        return
    walk_forward(trades, candles, folds=folds)


if __name__ == "__main__":
    main()
