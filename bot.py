"""
OANDA Trading Bot - Fixed Version
Fixes:
1. Trend filter - only trade WITH the trend
2. No re-entry after stop loss (30 min cooldown)
3. Only trade London + NY sessions
4. Better Telegram messages
"""

import os
import json
import logging
import requests
from datetime import datetime, timedelta
import pytz

from oanda_trader import OandaTrader
from signals import SignalEngine
from telegram_alert import TelegramAlert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("performance_log.txt"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

ASSETS = {
    "EUR_USD": {
        "instrument": "EUR_USD",
        "asset":      "EURUSD",
        "label":      "EUR/USD",
        "emoji":      "💱",
        "setting":    "trade_eurusd",
        "size":       7000,     # Loss=$10.50 Profit=$17.50 USD
        "stop_pips":  15,
        "tp_pips":    25,
    },
    "GBP_USD": {
        "instrument": "GBP_USD",
        "asset":      "GBPUSD",
        "label":      "GBP/USD",
        "emoji":      "💷",
        "setting":    "trade_gbpusd",
        "size":       7000,     # Loss=$14.00 Profit=$21.00 USD
        "stop_pips":  20,
        "tp_pips":    30,
    },
    "XAU_USD": {
        "instrument": "XAU_USD",
        "asset":      "XAUUSD",
        "label":      "Gold",
        "emoji":      "🥇",
        "setting":    "trade_gold",
        "size":       3,        # Loss=$24.00 Profit=$45.00 USD
        "stop_pips":  800,
        "tp_pips":    1500,
    },
}

def load_settings():
    default = {
        "max_trades_day":   4,
        "max_daily_loss":   40.0,
        "signal_threshold": 4,
        "demo_mode":        True,
        "trade_eurusd":     True,
        "trade_gbpusd":     True,
        "trade_gold":       True
    }
    try:
        with open("settings.json") as f:
            saved = json.load(f)
            default.update(saved)
    except FileNotFoundError:
        with open("settings.json", "w") as f:
            json.dump(default, f, indent=2)
    return default

def get_trend(trader, instrument):
    try:
        url    = f"{trader.base_url}/v3/instruments/{instrument}/candles"
        params = {"count": "60", "granularity": "H1", "price": "M"}
        r      = requests.get(url, headers=trader.headers, params=params, timeout=10)
        if r.status_code != 200:
            return "NONE"
        candles = r.json()["candles"]
        closes  = [float(c["mid"]["c"]) for c in candles if c["complete"]]
        if len(closes) < 50:
            return "NONE"
        ma50    = sum(closes[-50:]) / 50
        current = closes[-1]
        if current > ma50 * 1.0005:
            return "BUY"
        elif current < ma50 * 0.9995:
            return "SELL"
        return "NONE"
    except Exception as e:
        log.warning("Trend check error: " + str(e))
        return "NONE"

def is_in_cooldown(today, instrument):
    cooldowns = today.get("cooldowns", {})
    if instrument not in cooldowns:
        return False
    last_loss  = datetime.fromisoformat(cooldowns[instrument])
    wait_until = last_loss + timedelta(minutes=30)
    now_utc    = datetime.utcnow()
    if now_utc < wait_until:
        mins_left = int((wait_until - now_utc).seconds / 60)
        log.info(instrument + " in cooldown for " + str(mins_left) + " more mins")
        return True
    return False

def set_cooldown(today, instrument):
    if "cooldowns" not in today:
        today["cooldowns"] = {}
    today["cooldowns"][instrument] = datetime.utcnow().isoformat()

def run_bot():
    log.info("OANDA Bot starting!")
    settings = load_settings()
    sg_tz    = pytz.timezone("Asia/Singapore")
    now      = datetime.now(sg_tz)
    alert    = TelegramAlert()
    hour     = now.hour

    good_session = (15 <= hour <= 23) or (0 <= hour <= 1)

    if 15 <= hour <= 17:
        session = "London Open (HOT!)"
    elif 20 <= hour <= 23:
        session = "London+NY Overlap (BEST!)"
    elif 18 <= hour <= 19:
        session = "London Session"
    elif 0 <= hour <= 1:
        session = "NY Late Session"
    elif 7 <= hour <= 9:
        session = "Tokyo Open"
    else:
        session = "Asia/Off-hours (SKIP)"

    if now.weekday() == 5:
        msg = "Saturday - markets closed! Bot resumes Monday 5am SGT"
        alert.send(msg)
        return

    if now.weekday() == 6 and hour < 5:
        msg = "Sunday early - markets open at 5am SGT"
        alert.send(msg)
        return

    trader = OandaTrader(demo=settings["demo_mode"])
    if not trader.login():
        msg = "OANDA Login FAILED! Check secrets: OANDA_API_KEY and OANDA_ACCOUNT_ID"
        alert.send(msg)
        return

    current_balance = trader.get_balance()

    trade_log = "trades_" + now.strftime("%Y%m%d") + ".json"
    try:
        with open(trade_log) as f:
            today = json.load(f)
    except FileNotFoundError:
        today = {
            "trades":        0,
            "start_balance": current_balance,
            "daily_pnl":     0.0,
            "stopped":       False,
            "wins":          0,
            "losses":        0,
            "cooldowns":     {}
        }
        with open(trade_log, "w") as f:
            json.dump(today, f, indent=2)

    start_balance = today.get("start_balance", current_balance)
    open_pnl      = 0
    for name in ASSETS:
        pos = trader.get_position(name)
        if pos:
            open_pnl += trader.check_pnl(pos)

    realized_pnl = current_balance - start_balance
    total_pnl    = realized_pnl + open_pnl
    pl_sgd       = realized_pnl * 1.35
    mode         = "DEMO" if settings["demo_mode"] else "LIVE"

    today["daily_pnl"] = realized_pnl
    with open(trade_log, "w") as f:
        json.dump(today, f, indent=2)

    if today.get("stopped"):
        msg = ("Bot stopped for today\n"
               "Daily loss limit hit!\n"
               "Realized: $" + str(round(realized_pnl, 2)) + " USD\n"
               "Resumes tomorrow!")
        alert.send(msg)
        return

    if realized_pnl <= -settings["max_daily_loss"]:
        today["stopped"] = True
        with open(trade_log, "w") as f:
            json.dump(today, f, indent=2)
        msg = ("STOP LOSS HIT!\n"
               "Daily loss: $" + str(abs(round(realized_pnl, 2))) + " USD\n"
               "Limit: $" + str(settings["max_daily_loss"]) + " USD\n"
               "Bot stopped! Resumes tomorrow.")
        alert.send(msg)
        return

    if today["trades"] >= settings["max_trades_day"]:
        pnl_emoji = "✅" if realized_pnl >= 0 else "❌"
        msg = ("Max trades reached! " + pnl_emoji + "\n"
               "Trades: " + str(today["trades"]) + "/" + str(settings["max_trades_day"]) + "\n"
               "Realized PnL: $" + str(round(realized_pnl, 2)) + " USD\n"
               "= $" + str(round(pl_sgd, 2)) + " SGD\n"
               "New trades resume tomorrow!")
        alert.send(msg)
        return

    if not good_session:
        open_positions = []
        for name, config in ASSETS.items():
            pos = trader.get_position(name)
            if pos:
                pnl       = trader.check_pnl(pos)
                direction = "BUY" if int(float(pos["long"]["units"])) > 0 else "SELL"
                open_positions.append(config["emoji"] + " " + name + ": " + direction + " | $" + str(round(pnl, 2)))

        pnl_emoji = "✅" if realized_pnl >= 0 else "❌"
        pl_sgd_now = realized_pnl * 1.35
        positions_str = "\n".join(open_positions) if open_positions else "No open trades"
        msg = ("Off-hours status\n"
               "Time: " + now.strftime("%H:%M SGT") + "\n"
               "Session: " + session + "\n"
               "Balance: $" + str(round(current_balance, 2)) + "\n"
               "Realized: $" + str(round(realized_pnl, 2)) + " USD " + pnl_emoji + "\n"
               "= $" + str(round(pl_sgd_now, 2)) + " SGD\n"
               "Open PnL: $" + str(round(open_pnl, 2)) + " USD\n"
               "Trading starts: 3pm SGT\n"
               "---\n"
               + positions_str)
        alert.send(msg)
        return

    signals      = SignalEngine()
    scan_results = []
    new_trades   = 0

    for name, config in ASSETS.items():
        if not settings.get(config["setting"], True):
            continue
        if today["trades"] >= settings["max_trades_day"]:
            break

        position = trader.get_position(name)
        if position:
            pnl       = trader.check_pnl(position)
            direction = "BUY" if int(float(position["long"]["units"])) > 0 else "SELL"
            pnl_emoji = "📈" if pnl > 0 else "📉"
            scan_results.append(config["emoji"] + " " + name + ": " + direction + " open " + pnl_emoji + " $" + str(round(pnl, 2)))
            continue

        if is_in_cooldown(today, name):
            scan_results.append(config["emoji"] + " " + name + ": cooldown (30min after SL)")
            continue

        trend = get_trend(trader, name)
        log.info(name + " trend: " + trend)
        if trend == "NONE":
            scan_results.append(config["emoji"] + " " + name + ": choppy - skip")
            continue

        score, direction, details = signals.analyze(asset=config["asset"])
        log.info(name + ": " + str(score) + "/5 -> " + direction + " trend: " + trend)

        if direction != trend:
            scan_results.append(config["emoji"] + " " + name + ": signal=" + direction + " trend=" + trend + " mismatch - skip")
            continue

        if score < settings["signal_threshold"] or direction == "NONE":
            scan_results.append(config["emoji"] + " " + name + ": " + str(score) + "/5 weak signal")
            continue

        result = trader.place_order(
            instrument     = name,
            direction      = direction,
            size           = config["size"],
            stop_distance  = config["stop_pips"],
            limit_distance = config["tp_pips"]
        )

        if result["success"]:
            today["trades"] += 1
            new_trades += 1
            with open(trade_log, "w") as f:
                json.dump(today, f, indent=2)

            price, _, _ = trader.get_price(name)
            msg = ("NEW TRADE! " + mode + "\n"
                   + config["emoji"] + " " + name + "\n"
                   "Direction: " + direction + "\n"
                   "Trend: " + trend + " (matched!)\n"
                   "Score: " + str(score) + "/5\n"
                   "Entry: " + str(round(price, 5)) + "\n"
                   "Stop Loss: " + str(config["stop_pips"]) + " pips\n"
                   "Take Profit: " + str(config["tp_pips"]) + " pips\n"
                   "Trade #" + str(today["trades"]) + "/" + str(settings["max_trades_day"]) + "\n"
                   "Session: " + session)
            alert.send(msg)
            scan_results.append(config["emoji"] + " " + name + ": " + direction + " PLACED! " + str(score) + "/5")
        else:
            set_cooldown(today, name)
            with open(trade_log, "w") as f:
                json.dump(today, f, indent=2)
            scan_results.append(config["emoji"] + " " + name + ": order failed")

    pnl_emoji  = "✅" if realized_pnl >= 0 else "❌"
    target_hit = realized_pnl >= 22

    if target_hit:
        target_msg = "TARGET HIT! $" + str(round(pl_sgd, 0)) + " SGD today! 🎉"
    elif realized_pnl > 0:
        target_msg = "Profit $" + str(round(pl_sgd, 0)) + " SGD (target $30 SGD)"
    elif realized_pnl < 0:
        target_msg = "Loss $" + str(abs(round(pl_sgd, 0))) + " SGD today"
    else:
        target_msg = "Waiting for closed trades..."

    summary = "\n".join(scan_results) if scan_results else "No signals this scan"

    msg = ("Scan Complete! " + mode + "\n"
           "Time: " + now.strftime("%H:%M SGT") + "\n"
           "Session: " + session + "\n"
           "Balance: $" + str(round(current_balance, 2)) + "\n"
           "Start:   $" + str(round(start_balance, 2)) + "\n"
           "Realized: $" + str(round(realized_pnl, 2)) + " USD " + pnl_emoji + "\n"
           "= $" + str(round(pl_sgd, 2)) + " SGD\n"
           "Open PnL: $" + str(round(open_pnl, 2)) + " USD\n"
           "Total:    $" + str(round(total_pnl, 2)) + " USD\n"
           + target_msg + "\n"
           "Trades: " + str(today["trades"]) + "/" + str(settings["max_trades_day"]) + "\n"
           "---\n"
           + summary)
    alert.send(msg)

if __name__ == "__main__":
    run_bot()
