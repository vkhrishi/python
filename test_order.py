# ============================================================
#  BINANCE TESTNET — ORDER ACCEPTANCE TEST
#  Standalone sanity check: proves your API key + testnet +
#  order placement actually work, with ZERO strategy logic.
#
#  What it does (in order):
#    1. Connect to testnet and ping
#    2. Read USDT futures balance
#    3. Read symbol filters (tick/step/min-notional)
#    4. Set leverage + isolated margin
#    5. Place a SMALL MARKET order (min allowed size)
#    6. Read the open position back
#    7. Place a STOP_MARKET + TAKE_PROFIT_MARKET (then cancel)
#    8. CLOSE the position (reduceOnly) so nothing lingers
#
#  Run:  python test_order.py
#  Safe: testnet only. Refuses to run if USE_TESTNET is False
#        unless you pass  --live-i-am-sure
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


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg))


def get_client():
    if USE_TESTNET:
        c = UMFutures(key=API_KEY, secret=API_SECRET,
                      base_url="https://testnet.binancefuture.com")
        log("Client: TESTNET")
    else:
        c = UMFutures(key=API_KEY, secret=API_SECRET)
        log("Client: LIVE")
    return c


def round_step(value, step):
    precision = max(0, int(round(-math.log10(step))))
    return round(math.floor(value / step) * step, precision)


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

    # 2) Balance — this is the first call that needs a VALID key.
    #    On testnet you MUST use keys generated at testnet.binancefuture.com.
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

    # 4) Leverage + margin
    try:
        client.change_leverage(symbol=SYMBOL, leverage=LEVERAGE)
        log("Leverage set: %dx" % LEVERAGE)
    except Exception as e:
        log("Leverage note: %s" % e)
    try:
        client.change_margin_type(symbol=SYMBOL, marginType="ISOLATED")
        log("Margin type: ISOLATED")
    except Exception as e:
        log("Margin note: %s" % e)

    # 5) Compute the smallest valid qty (min-notional + a small buffer)
    price = float(client.ticker_price(symbol=SYMBOL)["price"])
    log("%s price: $%.2f" % (SYMBOL, price))
    raw_qty = (filt["min_notional"] * 1.02) / price
    qty = round_step(raw_qty, filt["step"])
    if qty * price < filt["min_notional"]:
        qty = round_step(raw_qty + filt["step"], filt["step"])
    notional = qty * price
    log("Test qty: %s  (notional $%.2f, margin ~$%.2f at %dx)" % (
        qty, notional, notional / LEVERAGE, LEVERAGE))

    if usdt < notional / LEVERAGE:
        raise SystemExit("Not enough testnet margin ($%.2f) for this order ($%.2f). "
                         "Fund the testnet wallet from the faucet." % (usdt, notional / LEVERAGE))

    # 6) MARKET BUY — the actual "is a trade accepted?" test
    try:
        order = client.new_order(symbol=SYMBOL, side="BUY", type="MARKET", quantity=qty)
        log("MARKET BUY ACCEPTED. orderId=%s status=%s" % (
            order.get("orderId"), order.get("status")))
    except Exception as e:
        raise SystemExit("ORDER REJECTED: %s" % e)

    time.sleep(1)

    # 7) Read position back
    try:
        pos = client.get_position_risk(symbol=SYMBOL)
        for p in pos:
            if p["symbol"] == SYMBOL:
                log("Position: amt=%s entry=%s" % (p["positionAmt"], p["entryPrice"]))
    except Exception as e:
        log("Position read note: %s" % e)

    # 8) Place + cancel an SL/TP pair (exercises stop orders)
    try:
        sl = round(price * 0.95, 1)
        tp = round(price * 1.05, 1)
        client.new_order(symbol=SYMBOL, side="SELL", type="STOP_MARKET",
                         stopPrice=str(sl), closePosition="true", workingType="MARK_PRICE")
        client.new_order(symbol=SYMBOL, side="SELL", type="TAKE_PROFIT_MARKET",
                         stopPrice=str(tp), closePosition="true", workingType="MARK_PRICE")
        log("SL @ $%.1f and TP @ $%.1f ACCEPTED" % (sl, tp))
        client.cancel_open_orders(symbol=SYMBOL)
        log("Open SL/TP orders cancelled")
    except Exception as e:
        log("SL/TP note: %s" % e)

    # 9) Close the position so nothing is left open
    try:
        client.new_order(symbol=SYMBOL, side="SELL", type="MARKET",
                         quantity=qty, reduceOnly="true")
        log("Position CLOSED (reduceOnly). Round-trip complete.")
    except Exception as e:
        log("CLOSE FAILED — close it manually on testnet UI: %s" % e)

    log("DONE. If you saw 'MARKET BUY ACCEPTED', order placement works.")


if __name__ == "__main__":
    main()
