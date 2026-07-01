import pandas as pd
import numpy as np
import math
import argparse
import datetime as dt


# ====== Strategy Params ======
LOT_SIZE = 65
LOTS_TO_TRADE = 1
ITM_OFFSET = 100
MIN_GAP_POINTS = 15
MAX_GAP_POINTS = 200
GAP_CONFIRMATION_MIN = 15
ORB_MINUTES = 15
ORB_BUFFER_POINTS = 3
MIN_ORB_RANGE = 20
MAX_ORB_RANGE = 200
FVG_MIN_SIZE_POINTS = 5
FVG_MAX_AGE_CANDLES = 12
FVG_ENTRY_BUFFER = 2
SL_PERCENT_LOW = 20.0
SL_PERCENT_MID = 16.0
SL_PERCENT_HIGH = 12.0
RR_RATIO = 2.0
MIN_RR_RATIO = 2.0
CAPITAL_RUPEES = 50000
RISK_PER_TRADE_PCT = 6.0
MAX_RISK_RUPEES = CAPITAL_RUPEES * RISK_PER_TRADE_PCT / 100
MIN_HOLD_MINUTES = 8
CATASTROPHIC_MAX_LOSS = 2000
MAX_TRADES_DAY = 1
MIN_OPTION_PREMIUM = 50
MAX_OPTION_PREMIUM = 400
MAX_SPREAD_PCT = 2.5
MAX_CAPITAL_EXPOSURE_PCT = 100
SL_BUFFER_POINTS = 5
NO_TRADE_AFTER_HOUR = 11
NO_TRADE_AFTER_MIN = 30
SQUAREOFF_HOUR = 15
SQUAREOFF_MIN = 10
MIN_ADX_FOR_TRADE = 15
ADX_LEN = 14
ATR_LEN = 14
RSI_LEN = 14
EMA_FAST = 9
EMA_SLOW = 21
VWAP_SESSION_BARS = 75
TRAILING_SL_ENABLED = True
TRAILING_SL_TRIGGER = 0.35
TRAILING_SL_STEP = 0.55

# Costs
SLIPPAGE_PCT = 0.005
FEE_PER_ORDER = 40.0


# ====== Indicator Helpers ======

def ema_calc(arr, n):
    a = pd.Series(arr, dtype=float)
    return a.ewm(span=n, adjust=False).mean().values


def rma_calc(x, n):
    x = pd.Series(x, dtype=float)
    return x.ewm(alpha=1.0 / n, adjust=False).mean().values


def calc_atr(h, l, c, n=14):
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    c = np.asarray(c, dtype=float)
    tr = np.zeros_like(c, dtype=float)
    tr[0] = h[0] - l[0]
    for i in range(1, len(c)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    return rma_calc(tr, n)


def calc_adx(h, l, c, n=14):
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    c = np.asarray(c, dtype=float)
    length = len(c)
    plus_dm = np.zeros(length, dtype=float)
    minus_dm = np.zeros(length, dtype=float)
    tr = np.zeros(length, dtype=float)
    tr[0] = h[0] - l[0]
    for i in range(1, length):
        up = h[i] - h[i - 1]
        dn = l[i - 1] - l[i]
        if up > dn and up > 0:
            plus_dm[i] = up
        if dn > up and dn > 0:
            minus_dm[i] = dn
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr_arr = rma_calc(tr, n)
    pdm_s = rma_calc(plus_dm, n)
    mdm_s = rma_calc(minus_dm, n)
    pdi = np.zeros(length, dtype=float)
    mdi = np.zeros(length, dtype=float)
    dx = np.zeros(length, dtype=float)
    for i in range(length):
        if atr_arr[i] > 0:
            pdi[i] = 100.0 * pdm_s[i] / atr_arr[i]
            mdi[i] = 100.0 * mdm_s[i] / atr_arr[i]
            total = pdi[i] + mdi[i]
            if total > 0:
                dx[i] = 100.0 * abs(pdi[i] - mdi[i]) / total
    adx_arr = rma_calc(dx, n)
    return adx_arr, pdi, mdi


def calc_rsi(c, n=14):
    c = np.asarray(c, dtype=float)
    length = len(c)
    gains = np.zeros(length, dtype=float)
    losses_arr = np.zeros(length, dtype=float)
    for i in range(1, length):
        diff = c[i] - c[i - 1]
        if diff > 0:
            gains[i] = diff
        else:
            losses_arr[i] = -diff
    ag = rma_calc(gains, n)
    al = rma_calc(losses_arr, n)
    rsi = np.zeros(length, dtype=float)
    for i in range(length):
        if al[i] == 0:
            rsi[i] = 100.0
        else:
            rsi[i] = 100.0 - 100.0 / (1.0 + ag[i] / al[i])
    return rsi


def calc_vwap(h, l, c, v):
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    c = np.asarray(c, dtype=float)
    v = np.asarray(v, dtype=float)
    tp = (h + l + c) / 3.0
    cpv = np.cumsum(tp * v)
    cv = np.cumsum(v)
    out = np.where(cv > 0, cpv / cv, c)
    return out


def detect_fvg(highs, lows, closes, direction):
    n = len(highs)
    if n < 3:
        return None, None
    search_end = max(2, n - FVG_MAX_AGE_CANDLES)
    for i in range(n - 1, search_end - 1, -1):
        if i < 2:
            break
        if direction == "BULL":
            c1_high = highs[i - 2]
            c3_low = lows[i]
            if c3_low > c1_high and (c3_low - c1_high) >= FVG_MIN_SIZE_POINTS:
                return round(c3_low, 2), round(c1_high, 2)
        elif direction == "BEAR":
            c1_low = lows[i - 2]
            c3_high = highs[i]
            if c1_low > c3_high and (c1_low - c3_high) >= FVG_MIN_SIZE_POINTS:
                return round(c1_low, 2), round(c3_high, 2)
    return None, None


def get_sl_percent(prem):
    if prem <= 100:
        return SL_PERCENT_LOW
    elif prem <= 250:
        return SL_PERCENT_MID
    else:
        return SL_PERCENT_HIGH


def calc_sl_tp(entry_price, qty):
    sl_pct = get_sl_percent(entry_price)
    sl_drop = entry_price * sl_pct / 100.0
    tp_rise = sl_drop * RR_RATIO
    if sl_drop * qty > MAX_RISK_RUPEES:
        sl_drop = MAX_RISK_RUPEES / qty
        tp_rise = sl_drop * RR_RATIO
        sl_pct = sl_drop / entry_price * 100.0
    sl_price = round(max(entry_price - sl_drop, 1.0), 1)
    target = round(entry_price + tp_rise, 1)
    rr = tp_rise / max(sl_drop, 0.01)
    return sl_price, target, sl_drop, tp_rise, sl_pct, rr


def get_catastrophic_sl(entry_price, qty):
    max_drop = CATASTROPHIC_MAX_LOSS / qty
    return round(max(entry_price - max_drop, 1.0), 1)


def within_cutoff(t):
    if t.hour < NO_TRADE_AFTER_HOUR:
        return True
    if t.hour == NO_TRADE_AFTER_HOUR and t.minute < NO_TRADE_AFTER_MIN:
        return True
    return False


# ====== Backtester ======

class Backtester:
    def __init__(self, df):
        self.df = df.copy()
        self.df["ts"] = pd.to_datetime(self.df["ts"])
        self.df = self.df.sort_values("ts").reset_index(drop=True)

    def run(self, start, end, out_csv):
        df = self.df[(self.df.ts.dt.date >= start) & (self.df.ts.dt.date <= end)].copy()
        trades = []
        eq = [0.0]
        dates = []
        qty = LOT_SIZE * LOTS_TO_TRADE

        grouped = df.groupby(df.ts.dt.date)

        for day, d in grouped:
            d = d.copy()
            day_df = d[
                (d.ts.dt.time >= dt.time(9, 15)) &
                (d.ts.dt.time <= dt.time(SQUAREOFF_HOUR, SQUAREOFF_MIN))
            ].copy()

            if len(day_df) < 30:
                eq.append(eq[-1])
                dates.append(day)
                continue

            prev_close = self._prev_close(df, day)

            orb_slice = day_df[
                (day_df.ts.dt.time >= dt.time(9, 15)) &
                (day_df.ts.dt.time < dt.time(9, 30))
            ]

            if len(orb_slice) < 2:
                eq.append(eq[-1])
                dates.append(day)
                continue

            orb_high = orb_slice.high.max()
            orb_low = orb_slice.low.min()
            orb_open = orb_slice.iloc[0].open
            orb_close = orb_slice.iloc[-1].close
            orb_range = orb_high - orb_low

            if prev_close is not None:
                gap_size = round(orb_open - prev_close, 2)
            else:
                gap_size = 0.0

            gap_dir = "NONE"
            if gap_size > MIN_GAP_POINTS:
                gap_dir = "GAP_UP"
            elif gap_size < -MIN_GAP_POINTS:
                gap_dir = "GAP_DOWN"

            # ORB range filter
            skip_day = False
            if prev_close is not None and prev_close > 0:
                orb_pct = orb_range / prev_close * 100.0
                if orb_pct < 0.08 or orb_pct > 0.80:
                    skip_day = True
            else:
                if orb_range < MIN_ORB_RANGE or orb_range > MAX_ORB_RANGE:
                    skip_day = True

            # Gap filter
            if not skip_day:
                if prev_close is not None and prev_close > 0:
                    gap_pct = abs(gap_size) / prev_close * 100.0
                    if gap_pct > 0.80:
                        skip_day = True
                else:
                    if abs(gap_size) > MAX_GAP_POINTS:
                        skip_day = True

            if skip_day:
                eq.append(eq[-1])
                dates.append(day)
                continue

            entered = False
            H = []
            L = []
            C = []
            V = []
            opens_list = []

            for idx in range(len(day_df)):
                row = day_df.iloc[idx]
                t = row.ts.to_pydatetime()

                H.append(row.high)
                L.append(row.low)
                C.append(row.close)
                V.append(row.volume if not pd.isna(row.volume) else 0.0)
                opens_list.append(row.open)

                # Skip ORB period candles for signal
                if t < dt.datetime.combine(day, dt.time(9, 30)):
                    continue

                if not within_cutoff(t):
                    break

                if entered:
                    break

                if len(C) < 30:
                    continue

                # Calculate indicators
                h_arr = list(H)
                l_arr = list(L)
                c_arr = list(C)
                v_arr = list(V)

                adx_arr, pdi_arr, mdi_arr = calc_adx(h_arr, l_arr, c_arr, ADX_LEN)
                rsi_arr = calc_rsi(c_arr, RSI_LEN)
                atr_arr = calc_atr(h_arr, l_arr, c_arr, ATR_LEN)
                ef = ema_calc(c_arr, EMA_FAST)
                es = ema_calc(c_arr, EMA_SLOW)
                vb = min(VWAP_SESSION_BARS, len(c_arr))
                vwap_arr = calc_vwap(h_arr[-vb:], l_arr[-vb:], c_arr[-vb:], v_arr[-vb:])

                adx_val = adx_arr[-1]
                pdi_val = pdi_arr[-1]
                mdi_val = mdi_arr[-1]
                rsi_val = rsi_arr[-1]
                atr_val = atr_arr[-1]
                ef_val = ef[-1]
                es_val = es[-1]
                vwap_val = vwap_arr[-1]
                last_close = c_arr[-1]
                last_open = opens_list[-1]

                # ADX filter
                if math.isnan(adx_val) or adx_val < MIN_ADX_FOR_TRADE:
                    continue

                breakout_high = orb_high + ORB_BUFFER_POINTS
                breakout_low = orb_low - ORB_BUFFER_POINTS

                trend_bull = ef_val > es_val
                trend_bear = ef_val < es_val
                above_vwap = last_close > vwap_val
                below_vwap = last_close < vwap_val

                pdi_str = False
                mdi_str = False
                if not math.isnan(pdi_val) and not math.isnan(mdi_val):
                    pdi_str = pdi_val > mdi_val
                    mdi_str = mdi_val > pdi_val

                rsi_bull = (not math.isnan(rsi_val)) and 45 < rsi_val < 75
                rsi_bear = (not math.isnan(rsi_val)) and 25 < rsi_val < 45

                bull_score = 0
                bull_score += int(last_close > breakout_high)
                bull_score += int(gap_dir == "GAP_UP")
                bull_score += int(trend_bull)
                bull_score += int(above_vwap)
                bull_score += int(pdi_str)
                bull_score += int(rsi_bull)

                bear_score = 0
                bear_score += int(last_close < breakout_low)
                bear_score += int(gap_dir == "GAP_DOWN")
                bear_score += int(trend_bear)
                bear_score += int(below_vwap)
                bear_score += int(mdi_str)
                bear_score += int(rsi_bear)

                # Direction decision
                direction = None
                if bull_score >= 3 and last_close > breakout_high:
                    direction = "BULL"
                elif bear_score >= 3 and last_close < breakout_low:
                    direction = "BEAR"
                elif last_close > breakout_high and trend_bull and bull_score >= 2:
                    direction = "BULL"
                elif last_close < breakout_low and trend_bear and bear_score >= 2:
                    direction = "BEAR"

                if direction is None:
                    continue

                # Post-direction filters
                if direction == "BULL" and (not math.isnan(rsi_val)) and rsi_val > 78:
                    continue
                if direction == "BEAR" and (not math.isnan(rsi_val)) and rsi_val < 22:
                    continue
                if direction == "BULL" and gap_dir == "GAP_DOWN":
                    continue
                if direction == "BEAR" and gap_dir == "GAP_UP":
                    continue

                # Breakout candle strength
                last_range = row.high - row.low
                if last_range <= 0:
                    continue
                body_ratio = abs(last_close - last_open) / last_range
                if body_ratio < 0.4:
                    continue

                # Candle color alignment
                if direction == "BULL" and not (last_close > last_open):
                    continue
                if direction == "BEAR" and not (last_close < last_open):
                    continue

                # Volume confirmation
                recent_v = v_arr[-20:] if len(v_arr) >= 20 else v_arr
                avg_v = sum(recent_v) / len(recent_v) if len(recent_v) > 0 else 0
                cur_v = row.volume if not pd.isna(row.volume) else 0
                if avg_v > 0 and cur_v / avg_v < 1.0:
                    continue

                # Directional candles (last 3)
                if len(c_arr) >= 3 and len(opens_list) >= 3:
                    if direction == "BULL":
                        consec = 0
                        for k in range(1, 4):
                            if c_arr[-k] > opens_list[-k]:
                                consec += 1
                    else:
                        consec = 0
                        for k in range(1, 4):
                            if c_arr[-k] < opens_list[-k]:
                                consec += 1
                    if consec < 2:
                        continue

                # Late entry filter
                is_late = t.hour > 10 or (t.hour == 10 and t.minute >= 30)
                score = bull_score if direction == "BULL" else bear_score
                if is_late and score < 4:
                    continue

                # ATR breakout distance
                if not math.isnan(atr_val) and atr_val > 0:
                    if direction == "BULL":
                        breakout_distance = last_close - orb_high
                    else:
                        breakout_distance = orb_low - last_close
                    if breakout_distance <= 0:
                        continue
                    atr_mult = breakout_distance / atr_val
                    if atr_mult < 0.3 or atr_mult > 2.0:
                        continue

                # FVG detection
                fvg_top, fvg_bot = detect_fvg(h_arr, l_arr, c_arr, direction)
                entry_mode = "ORB_BREAKOUT"
                if fvg_top is not None:
                    if direction == "BULL":
                        near = last_close <= fvg_top + FVG_ENTRY_BUFFER
                    else:
                        near = last_close >= fvg_bot - FVG_ENTRY_BUFFER
                    if near:
                        entry_mode = "FVG_RETEST"
                    else:
                        entry_mode = "FVG_PRESENT"

                # Entry at next bar open
                nxt_idx = idx + 1
                if nxt_idx >= len(day_df):
                    break

                entry_row = day_df.iloc[nxt_idx]
                entry_time = entry_row.ts.to_pydatetime()
                if not within_cutoff(entry_time):
                    break

                # Option proxy
                opt_type = "CE" if direction == "BULL" else "PE"
                delta = 0.6 if opt_type == "CE" else -0.6
                qty_opt = LOT_SIZE * LOTS_TO_TRADE
                entry_under = entry_row.open

                entry_prem = ITM_OFFSET + 20.0
                if entry_prem < MIN_OPTION_PREMIUM:
                    entry_prem = MIN_OPTION_PREMIUM
                if entry_prem > MAX_OPTION_PREMIUM:
                    entry_prem = MAX_OPTION_PREMIUM

                # Slippage at entry
                entry_fill = entry_prem * (1.0 + SLIPPAGE_PCT)

                sl_price, target_price, sl_drop, tp_rise, sl_pct, rr = calc_sl_tp(entry_fill, qty_opt)
                if rr < MIN_RR_RATIO:
                    continue

                cat_sl = get_catastrophic_sl(entry_fill, qty_opt)

                # Simulate forward from entry
                trail_sl = sl_price
                highest = entry_fill
                exited = False
                exit_reason = ""
                exit_prem = entry_fill
                exit_time = entry_time
                exit_under = entry_under

                for j in range(nxt_idx, len(day_df)):
                    r2 = day_df.iloc[j]
                    t2 = r2.ts.to_pydatetime()

                    # EOD squareoff
                    if t2.hour > SQUAREOFF_HOUR or (t2.hour == SQUAREOFF_HOUR and t2.minute >= SQUAREOFF_MIN):
                        cur_prem = self._option_px(entry_fill, entry_under, r2.close, delta)
                        exit_prem = cur_prem * (1.0 - SLIPPAGE_PCT)
                        exit_reason = "EOD"
                        exit_time = t2
                        exit_under = r2.close
                        exited = True
                        break

                    cur_prem = self._option_px(entry_fill, entry_under, r2.close, delta)

                    # Take profit (always active)
                    if cur_prem >= target_price:
                        exit_prem = cur_prem * (1.0 - SLIPPAGE_PCT)
                        exit_reason = "TP"
                        exit_time = t2
                        exit_under = r2.close
                        exited = True
                        break

                    minutes_held = (t2 - entry_time).total_seconds() / 60.0

                    # During hold: only catastrophic SL
                    if minutes_held < MIN_HOLD_MINUTES:
                        if cur_prem <= cat_sl:
                            exit_prem = cur_prem * (1.0 - SLIPPAGE_PCT)
                            exit_reason = "CATASTROPHIC_SL"
                            exit_time = t2
                            exit_under = r2.close
                            exited = True
                            break
                    else:
                        # After hold: trailing SL
                        if TRAILING_SL_ENABLED and cur_prem > highest:
                            highest = cur_prem
                            profit = highest - entry_fill
                            if profit >= tp_rise * TRAILING_SL_TRIGGER:
                                new_sl = round(entry_fill + profit * TRAILING_SL_STEP, 1)
                                if new_sl > trail_sl:
                                    trail_sl = new_sl

                        if cur_prem <= trail_sl:
                            exit_prem = cur_prem * (1.0 - SLIPPAGE_PCT)
                            exit_reason = "SL"
                            exit_time = t2
                            exit_under = r2.close
                            exited = True
                            break

                if not exited:
                    r2 = day_df.iloc[-1]
                    exit_time = r2.ts.to_pydatetime()
                    exit_reason = "EOD"
                    exit_under = r2.close
                    exit_prem = self._option_px(entry_fill, entry_under, r2.close, delta) * (1.0 - SLIPPAGE_PCT)

                gross_pnl = (exit_prem - entry_fill) * qty_opt
                net_pnl = gross_pnl - (2.0 * FEE_PER_ORDER)

                trades.append({
                    "date": str(day),
                    "entry_time": str(entry_time),
                    "exit_time": str(exit_time),
                    "signal": opt_type + "_BUY",
                    "direction": direction,
                    "entry_under": round(entry_under, 2),
                    "exit_under": round(exit_under, 2),
                    "entry_prem": round(entry_fill, 1),
                    "exit_prem": round(exit_prem, 1),
                    "qty": qty_opt,
                    "reason": exit_reason,
                    "pnl": round(net_pnl, 2),
                    "bull_score": bull_score,
                    "bear_score": bear_score,
                    "entry_mode": entry_mode,
                    "gap_dir": gap_dir,
                    "gap_size": gap_size,
                    "orb_range": round(orb_range, 2),
                    "adx": round(adx_val, 1),
                    "rsi": round(rsi_val, 1),
                })

                entered = True
                break

            # Equity curve update
            if trades and trades[-1]["date"] == str(day):
                eq.append(eq[-1] + trades[-1]["pnl"])
            else:
                eq.append(eq[-1])
            dates.append(day)

        # Print results
        if len(trades) == 0:
            print("No trades generated in this date range.")
            return

        res = pd.DataFrame(trades)
        res.to_csv(out_csv, index=False)

        wins = res[res.pnl > 0]
        losses = res[res.pnl <= 0]
        win_count = len(wins)
        loss_count = len(losses)
        total = len(res)
        win_rate = win_count / total * 100.0

        total_pnl = res.pnl.sum()
        avg_win = wins.pnl.mean() if win_count > 0 else 0.0
        avg_loss = losses.pnl.mean() if loss_count > 0 else 0.0
        gross_wins = wins.pnl.sum() if win_count > 0 else 0.0
        gross_losses = abs(losses.pnl.sum()) if loss_count > 0 else 0.01
        profit_factor = gross_wins / gross_losses
        expectancy = total_pnl / total

        eq_array = np.array(eq)
        peak = np.maximum.accumulate(eq_array)
        dd = peak - eq_array
        max_dd = dd.max()

        # Exit reason breakdown
        reason_counts = res.groupby("reason").size()
        reason_pnl = res.groupby("reason")["pnl"].sum()

        print("")
        print("=" * 60)
        print("  BACKTEST RESULTS")
        print("=" * 60)
        print("  Period: %s to %s" % (start, end))
        print("  Total trading days: %d" % len(dates))
        print("  Total trades: %d" % total)
        print("  Winners: %d | Losers: %d" % (win_count, loss_count))
        print("  Win rate: %.1f%%" % win_rate)
        print("  Avg win: Rs.%.0f | Avg loss: Rs.%.0f" % (avg_win, avg_loss))
        print("  Profit factor: %.2f" % profit_factor)
        print("  Expectancy per trade: Rs.%.0f" % expectancy)
        print("  Total P&L: Rs.%.0f" % total_pnl)
        print("  Max drawdown: Rs.%.0f" % max_dd)
        print("  Final equity: Rs.%.0f" % eq[-1])
        print("")
        print("  Exit reasons:")
        for reason in reason_counts.index:
            count = reason_counts[reason]
            pnl_sum = reason_pnl[reason]
            print("    %s: %d trades, Rs.%.0f" % (reason, count, pnl_sum))
        print("")
        print("  Direction breakdown:")
        for d_name in ["BULL", "BEAR"]:
            d_trades = res[res.direction == d_name]
            if len(d_trades) > 0:
                d_wins = len(d_trades[d_trades.pnl > 0])
                d_wr = d_wins / len(d_trades) * 100.0
                d_pnl = d_trades.pnl.sum()
                print("    %s: %d trades, %d wins (%.1f%%), Rs.%.0f" % (d_name, len(d_trades), d_wins, d_wr, d_pnl))
        print("")
        print("  Saved trades to: %s" % out_csv)
        print("=" * 60)

    def _prev_close(self, df, cur_day):
        prev = df[df.ts.dt.date < cur_day].tail(1)
        if len(prev) > 0:
            return float(prev.close.values[0])
        return None

    def _option_px(self, entry_prem, under_entry, under_now, delta):
        opt = entry_prem + delta * (under_now - under_entry)
        if opt < 0.5:
            opt = 0.5
        return opt


def main():
    ap = argparse.ArgumentParser(description="NIFTY Sniper Backtest")
    ap.add_argument("--csv", required=True, help="Path to 5-min NIFTY CSV")
    ap.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    ap.add_argument("--out", default="trades.csv", help="Output trades CSV")
    args = ap.parse_args()

    print("Loading data from: %s" % args.csv)
    df = pd.read_csv(args.csv)
    print("Loaded %d rows" % len(df))

    start = pd.to_datetime(args.start).date()
    end = pd.to_datetime(args.end).date()

    bt = Backtester(df)
    bt.run(start, end, args.out)


if __name__ == "__main__":
    main()
