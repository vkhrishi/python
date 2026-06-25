# ============================================================
#  BINANCE TESTNET — VISIBLE ORDER PROCEDURE
#  Standalone sanity check that proves your API key + testnet +
#  order placement work, AND leaves orders/positions on screen
#  long enough for you to SEE them in the testnet web UI.
#
#  Procedure (pauses between each step so you can check the UI):
#    1. Connect to testnet and ping
#    2. Read USDT futures balance
#    3. Read symbol filters (tick/step/min-notional)
#    4. Set leverage
#    5. Place a RESTING LIMIT BUY ~10% below market   -> Open Orders tab
#    6. Cancel that limit order
#    7. Place a MARKET BUY (opens a position)         -> Positions tab
#    8. Attach a STOP-LOSS + TAKE-PROFIT              -> Open Orders tab
#    9. Close the position + cancel leftover orders
#
#  WHERE TO LOOK IN THE UI  (https://testnet.binancefuture.com):
#    - You MUST be logged in with the SAME account the API key
#      belongs to. Keys are account-specific. Different login =
#      you will NOT see these trades.
#    - Resting limit orders + SL/TP  -> "Open Orders" tab
#    - The market position            -> "Positions" tab
#    - Filled/closed trades           -> "Order History" / "Trade History"
#
#  Run (interactive, recommended):  python test_order.py
#  Run (no pauses):                 python test_order.py --no-pause
#  Safe: testnet only. Refuses LIVE unless you pass --live-i-am-sure
# ============================================================

import sys
import math
import time

from binance.um_futures import UMFutures

# ---- Reuse the SAME credentials/config as bot.py ----
API_KEY    = "loIzlExfyBbyQI6OaL5FRL90Gnw1jtczafGic2JgTfPomajYipfASLSrdqIE80n8"
API_SECRET = "asSDoyc8wIMyI0pw1dzlIKfqEDboJQVJ9yFqvaM8aZl0vIUTx2lbupdBPr4WOKde"

USE_TESTNET = True
SYMBOL      = "BTCUSDT"
LEVERAGE    = 3

NO_PAUSE = "--no-pause" in sys.argv


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg))


def pause(msg):
    """Stop so the user can look at the testnet UI."""
    print("\n>>> %s" % msg)
    if NO_PAUSE:
        print("    (--no-pause set, waiting 8s instead...)")
        time.sleep(8)
    else:
        try:
            input("    Look at the testnet UI now, then press ENTER to continue... ")
        except EOFError:
            time.sleep(8)
    print("")


def get_client():
    if USE_TESTNET:
        c = UMFutures(key=API_KEY, secret=API_SECRET,
                      base_url="https://testnet.binancefuture.com")
        log("Client: TESTNET  (UI: https://testnet.binancefuture.com)")
    else:
        c = UMFutures(key=API_KEY, secret=API_SECRET)
        log("Client: LIVE")
    return c


def round_step(value, step):
    precision = max(0, int(round(-math.log10(step))))
    return round(math.floor(value / step) * step, precision)


def round_tick(value, tick):
    precision = max(0, int(round(-math.log10(tick))))
    return round(round(value / tick) * tick, precision)


def get_filters(client):
    info = client.exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == SYMBOL:
            tick = step = min_notional = None
            for f in s["filters"]:
                if f["filterType"] == "PRICE_FILTER":
                    tick = float(f["tickSize"])
                elif f["filterType"] == "LOT_SIZE":
                    step = float(f["stepSize"])
                elif f["filterType"] == "MIN_NOTIONAL":
                    min_notional = float(f.get("notional", 100))
            return {
                "tick": tick or 0.10,
                "step": step or 0.001,
                "min_notional": min_notional or 100.0,
            }
    raise SystemExit("Symbol %s not found in exchange_info" % SYMBOL)


def show_open_orders(client):
    try:
        oo = client.get_orders(symbol=SYMBOL)
        if not oo:
            log("Open orders now: (none)")
        for o in oo:
            log("  OPEN ORDER id=%s %s %s stop=%s price=%s reduceOnly=%s closePos=%s" % (
                o.get("orderId"), o.get("side"), o.get("type"),
                o.get("stopPrice"), o.get("price"),
                o.get("reduceOnly"), o.get("closePosition")))
    except Exception as e:
        log("Open-orders read note: %s" % e)


def show_position(client):
    try:
        pos = client.get_position_risk(symbol=SYMBOL)
        for p in pos:
            if p["symbol"] == SYMBOL:
                log("Position now: amt=%s entry=%s uPnL=%s" % (
                    p["positionAmt"], p["entryPrice"], p.get("unRealizedProfit")))
    except Exception as e:
        log("Position read note: %s" % e)


def place_stop(client, side, stop_price, qty, kind):
    """Try to attach a stop. Falls back across methods for testnet quirks.
    Returns the order dict on success, raises on total failure."""
    otype = "STOP_MARKET" if kind == "SL" else "TAKE_PROFIT_MARKET"

    # Method A: closePosition=true (whole-position stop, no qty)
    try:
        return client.new_order(symbol=SYMBOL, side=side, type=otype,
                                stopPrice=str(stop_price), closePosition="true",
                                workingType="MARK_PRICE")
    except Exception as e1:
        log("  %s method A (closePosition) failed: %s" % (kind, e1))

    # Method B: reduceOnly with explicit quantity
    try:
        return client.new_order(symbol=SYMBOL, side=side, type=otype,
                                stopPrice=str(stop_price), quantity=qty,
                                reduceOnly="true", workingType="MARK_PRICE")
    except Exception as e2:
        log("  %s method B (reduceOnly+qty) failed: %s" % (kind, e2))

    # Method C: reduceOnly with CONTRACT_PRICE working type
    try:
        return client.new_order(symbol=SYMBOL, side=side, type=otype,
                                stopPrice=str(stop_price), quantity=qty,
                                reduceOnly="true", workingType="CONTRACT_PRICE")
    except Exception as e3:
        log("  %s method C (CONTRACT_PRICE) failed: %s" % (kind, e3))
        raise


def main():
    if not USE_TESTNET and "--live-i-am-sure" not in sys.argv:
        raise SystemExit("Refusing to run on LIVE. Set USE_TESTNET=True (recommended) "
                         "or pass --live-i-am-sure.")

    client = get_client()

    # 1) Connectivity
    try:
        t = client.time()
        log("Ping OK. Server time: %s" % t.get("serverTime"))
    except Exception as e:
        raise SystemExit("PING FAILED (network/base_url): %s" % e)

    # 2) Balance — first call that needs a VALID testnet key.
    try:
        acct = client.account()
        usdt = 0.0
        for a in acct.get("assets", []):
            if a["asset"] == "USDT":
                usdt = float(a["availableBalance"])
        log("USDT available balance: $%.2f" % usdt)
    except Exception as e:
        raise SystemExit("ACCOUNT/BALANCE FAILED — almost always a bad/wrong-env API key "
                         "(error -2015 = invalid key/IP/permissions): %s" % e)

    # 3) Filters
    filt = get_filters(client)
    log("Filters: tick=%s step=%s min_notional=$%.2f" % (
        filt["tick"], filt["step"], filt["min_notional"]))

    # 4) Leverage
    try:
        client.change_leverage(symbol=SYMBOL, leverage=LEVERAGE)
        log("Leverage set: %dx" % LEVERAGE)
    except Exception as e:
        log("Leverage note: %s" % e)

    # Sizing: smallest valid qty (min-notional + small buffer)
    price = float(client.ticker_price(symbol=SYMBOL)["price"])
    log("%s price: $%.2f" % (SYMBOL, price))
    raw_qty = (filt["min_notional"] * 1.05) / price
    qty = round_step(raw_qty, filt["step"])
    if qty * price < filt["min_notional"]:
        qty = round_step(raw_qty + filt["step"], filt["step"])
    notional = qty * price
    log("Test qty: %s  (notional $%.2f, margin ~$%.2f at %dx)" % (
        qty, notional, notional / LEVERAGE, LEVERAGE))

    if usdt < notional / LEVERAGE:
        raise SystemExit("Not enough testnet margin ($%.2f) for this order ($%.2f). "
                         "Fund the testnet wallet from the faucet." % (usdt, notional / LEVERAGE))

    # 5) RESTING LIMIT BUY ~10% below market (will NOT fill -> stays visible)
    limit_px = round_tick(price * 0.90, filt["tick"])
    try:
        lo = client.new_order(symbol=SYMBOL, side="BUY", type="LIMIT",
                              timeInForce="GTC", quantity=qty, price=str(limit_px))
        log("RESTING LIMIT BUY placed @ $%.1f  orderId=%s status=%s" % (
            limit_px, lo.get("orderId"), lo.get("status")))
        show_open_orders(client)
        pause("STEP 5: Open the 'Open Orders' tab in the testnet UI. "
              "You should see a BUY LIMIT @ $%.1f." % limit_px)
        # 6) cancel it
        client.cancel_open_orders(symbol=SYMBOL)
        log("Resting limit order cancelled.")
    except Exception as e:
        log("Limit-order step note: %s" % e)

    # 7) MARKET BUY — opens a real position
    try:
        order = client.new_order(symbol=SYMBOL, side="BUY", type="MARKET", quantity=qty)
        log("MARKET BUY ACCEPTED. orderId=%s status=%s" % (
            order.get("orderId"), order.get("status")))
    except Exception as e:
        raise SystemExit("ORDER REJECTED: %s" % e)

    time.sleep(1)
    show_position(client)
    pause("STEP 7: Open the 'Positions' tab in the testnet UI. "
          "You should see a LONG %s position of %s BTC." % (SYMBOL, qty))

    # 8) Attach SL + TP (these stay visible until filled/cancelled)
    sl_px = round_tick(price * 0.95, filt["tick"])
    tp_px = round_tick(price * 1.05, filt["tick"])
    sl_ok = tp_ok = False
    try:
        place_stop(client, "SELL", sl_px, qty, "SL")
        log("STOP-LOSS placed @ $%.1f" % sl_px)
        sl_ok = True
    except Exception:
        log("STOP-LOSS could not be placed by any method.")
    try:
        place_stop(client, "SELL", tp_px, qty, "TP")
        log("TAKE-PROFIT placed @ $%.1f" % tp_px)
        tp_ok = True
    except Exception:
        log("TAKE-PROFIT could not be placed by any method.")

    if sl_ok or tp_ok:
        show_open_orders(client)
        pause("STEP 8: Open the 'Open Orders' tab again. You should see the "
              "STOP/TAKE-PROFIT order(s) attached to the position.")

    # 9) Clean up: cancel leftover orders + close the position
    try:
        client.cancel_open_orders(symbol=SYMBOL)
        log("Leftover SL/TP orders cancelled.")
    except Exception as e:
        log("Cancel note: %s" % e)
    try:
        client.new_order(symbol=SYMBOL, side="SELL", type="MARKET",
                         quantity=qty, reduceOnly="true")
        log("Position CLOSED (reduceOnly). Round-trip complete.")
    except Exception as e:
        log("CLOSE FAILED — close it manually on the testnet UI: %s" % e)

    print("\n" + "=" * 56)
    log("SUMMARY")
    log("  Order placement works: YES (you saw MARKET BUY ACCEPTED)")
    log("  Stop-loss placement:   %s" % ("OK" if sl_ok else "FAILED (see notes above)"))
    log("  Take-profit placement: %s" % ("OK" if tp_ok else "FAILED (see notes above)"))
    print("=" * 56)
    log("If you STILL see nothing in the testnet UI, your browser is logged")
    log("into a DIFFERENT account than this API key. Keys are account-bound:")
    log("re-create the key at testnet.binancefuture.com on the SAME login,")
    log("or check the 'Order History' / 'Trade History' tab (not just 'Open Orders').")


if __name__ == "__main__":
    main()
