"""
Deriv Trading Bot
EUR/USD + GBP/USD + Gold (XAU/USD)
Demo mode by default
"""

import os
import json
import logging
from datetime import datetime
import pytz

from deriv_trader import DerivTrader
from signals import SignalEngine
from telegram_alert import TelegramAlert
from auto_tune import AutoTuner

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
    "EURUSD": {
        "asset":    "EURUSD",
        "label":    "Euro/USD",
        "emoji":    "💱",
        "setting":  "trade_eurusd",
        "size":     10,
        "stop":     15,
        "limit":    30,
    },
    "GBPUSD": {
        "asset":    "GBPUSD",
        "label":    "GBP/USD",
        "emoji":    "💷",
        "setting":  "trade_gbpusd",
        "size":     10,
        "stop":     20,
        "limit":    40,
    },
    "XAUUSD": {
        "asset":    "XAUUSD",
        "label":    "Gold",
        "emoji":    "🥇",
        "setting":  "trade_gold",
        "size":     10,
        "stop":     150,
        "limit":    300,
    },
}

def load_settings():
    default = {
        "max_trades_day":   5,
        "max_daily_loss":   50.0,
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

def run_bot():
    log.info("Deriv Bot starting!")
    settings = load_settings()
    sg_tz    = pytz.timezone("Asia/Singapore")
    now      = datetime.now(sg_tz)
    alert    = TelegramAlert()

    # Detect session
    hour = now.hour
    if 5 <= hour < 7:
        session = "Sydney"
    elif 7 <= hour < 15:
        session = "Tokyo/Asia"
    elif 15 <= hour < 20:
        session = "London"
    elif 20 <= hour <= 23 or hour < 1:
        session = "London+NY (BEST!)"
    else:
        session = "New York"

    alert.send(
        f"Bot starting...\n"
        f"Time: {now.strftime('%H:%M SGT')}\n"
        f"Session: {session}"
    )

    # Skip Saturday + early Sunday
    if now.weekday() == 5:
        alert.send("Saturday - markets closed!")
        return
    if now.weekday() == 6 and now.hour < 5:
        alert.send("Sunday early - markets opening soon!")
        return

    # Login
    trader = DerivTrader()
    if not trader.login():
        alert.send(
            "Deriv Login failed!\n"
            "Check GitHub Secret:\n"
            "DERIV_TOKEN correct?"
        )
        return

    alert.send(
        f"Deriv Login success!\n"
        f"Balance: ${trader.balance:.2f}\n"
        f"Scanning markets..."
    )

    signals = SignalEngine()

    # Load today's log
    trade_log = f"trades_{now.strftime('%Y%m%d')}.json"
    try:
        with open(trade_log) as f:
            today = json.load(f)
    except FileNotFoundError:
        today = {"trades": 0, "daily_pnl": 0.0, "stopped": False}

    if today.get("stopped"):
        alert.send("Daily loss limit hit! Stopped for today.")
        return

    if today["daily_pnl"] <= -settings["max_daily_loss"]:
        today["stopped"] = True
        with open(trade_log, "w") as f:
            json.dump(today, f, indent=2)
        alert.send(f"Daily loss limit hit! Stopped.")
        return

    if today["trades"] >= settings["max_trades_day"]:
        alert.send(f"Max {settings['max_trades_day']} trades reached today!")
        return

    # Scan all assets
    scan_results = []
    for name, config in ASSETS.items():
        if not settings.get(config["setting"], True):
            continue
        if today["trades"] >= settings["max_trades_day"]:
            break

        log.info(f"Scanning {name}...")

        # Check existing position
        position = trader.get_position(name)
        if position:
            pnl = trader.check_pnl(position)
            scan_results.append(f"{config['emoji']} {name}: position open PnL={pnl:.2f}")
            continue

        # Get signal
        score, direction, details = signals.analyze(asset=config["asset"])
        log.info(f"{name}: {score}/5 -> {direction}")

        if score < settings["signal_threshold"] or direction == "NONE":
            scan_results.append(f"{config['emoji']} {name}: {score}/5 -> skip")
            continue

        # Place trade
        result = trader.place_order(
            asset         = name,
            direction     = direction,
            size          = config["size"],
            stop_distance = config["stop"],
            limit_distance= config["limit"]
        )

        if result["success"]:
            today["trades"] += 1
            with open(trade_log, "w") as f:
                json.dump(today, f, indent=2)

            arrow = "UP" if direction == "BUY" else "DOWN"
            alert.send(
                f"{config['emoji']} {name} Trade!\n"
                f"Direction: {direction} {arrow}\n"
                f"Score: {score}/5\n"
                f"Size: ${config['size']}\n"
                f"Trade #{today['trades']}"
            )
            scan_results.append(f"{config['emoji']} {name}: {direction} PLACED!")
        else:
            scan_results.append(f"{config['emoji']} {name}: failed - {result['error']}")

    # Send summary
    summary = "\n".join(scan_results) if scan_results else "No signals found"
    alert.send(
        f"Scan Complete!\n"
        f"Time: {now.strftime('%H:%M SGT')}\n"
        f"Session: {session}\n"
        f"Trades: {today['trades']}/{settings['max_trades_day']}\n"
        f"PnL: ${today['daily_pnl']:.2f}\n"
        f"---\n"
        f"{summary}"
    )

if __name__ == "__main__":
    run_bot()
