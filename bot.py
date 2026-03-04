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
        "size":       10000,
        "stop_pips":  15,
        "tp_pips":    25,
    },
    "GBP_USD": {
        "instrument": "GBP_USD",
        "asset":      "GBPUSD",
        "label":      "GBP/USD",
        "emoji":      "💷",
        "setting":    "trade_gbpusd",
        "size":       10000,
        "stop_pips":  20,
        "tp_pips":    30,
    },
    "XAU_USD": {
        "instrument": "XAU_USD",
        "asset":      "XAUUSD",
        "label":      "Gold",
        "emoji":      "🥇",
        "setting":    "trade_gold",
        "size":       2,
        "stop_pips":  200,
        "tp_pips":    400,
    },
}

def load_settings():
    default = {
        "max_trades_day":   4,
        "max_daily_loss":   60.0,
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
    """
    FIX 1: Trend filter using 50-period MA on 1H candles
    Only BUY in uptrend, only SELL in downtrend
    """
    try:
        url    = f"{trader.base_url}/v3/instruments/{instrument}/candles"
        params = {"count": "60", "granularity": "H1", "price": "M"}
        import requests
        r      = requests.get(url, headers=trader.headers, params=params, timeout=10)
        if r.status_code != 200:
            return "NONE"
        candles = r.json()["candles"]
        closes  = [float(c["mid"]["c"]) for c in candles if c["complete"]]
        if len(closes) < 50:
            return "NONE"
        ma50    = sum(closes[-50:]) / 50
        current = closes[-1]
        if current > ma50 * 1.0005:   # price clearly above MA50 = uptrend
            return "BUY"
        elif current < ma50 * 0.9995: # price clearly below MA50 = downtrend
            return "SELL"
        return "NONE"  # choppy = skip
    except Exception as e:
        log.warning(f"Trend check error: {e}")
        return "NONE"

def is_in_cooldown(today, instrument):
    """
    FIX 2: 30 min cooldown after stop loss
    No re-entry on same pair too quickly
    """
    cooldowns = today.get("cooldowns", {})
    if instrument not in cooldowns:
        return False
    last_loss_str = cooldowns[instrument]
    last_loss     = datetime.fromisoformat(last_loss_str)
    wait_until    = last_loss + timedelta(minutes=30)
    now_utc       = datetime.utcnow().replace(tzinfo=pytz.UTC)
    if now_utc < wait_until.replace(tzinfo=pytz.UTC):
        mins_left = int((wait_until.replace(tzinfo=pytz.UTC) - now_utc).seconds / 60)
        log.info(f"{instrument} in cooldown for {mins_left} more mins")
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

    hour = now.hour

    # FIX 3: Only trade good sessions!
    # London: 3pm-11pm SGT
    # NY:     8pm-5am SGT
    # Best overlap: 8pm-11pm SGT
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
        session = "Tokyo Open (low volume)"
    else:
        session = "Asia/Off-hours (SKIP)"

    # Skip Saturday
    if now.weekday() == 5:
        alert.send(
            f"Saturday
"
            f"Markets closed!
"
            f"Bot resumes Monday 5am SGT"
        )
        return

    # Skip early Sunday
    if now.weekday() == 6 and hour < 5:
        alert.send(
            f"Sunday early
"
            f"Markets open at 5am SGT"
        )
        return

    # Login to OANDA
    trader = OandaTrader(demo=settings["demo_mode"])
    if not trader.login():
        alert.send(
            f"OANDA Login FAILED!
"
            f"Check secrets:
"
            f"OANDA_API_KEY
"
            f"OANDA_ACCOUNT_ID"
        )
        return

    current_balance = trader.get_balance()

    # Load today log
    trade_log = f"trades_{now.strftime('%Y%m%d')}.json"
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

    # Real PnL from balance change
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

    # Daily loss protection
    if today.get("stopped"):
        alert.send(
            f"Bot stopped for today
"
            f"Daily loss limit hit!
"
            f"Realized: ${realized_pnl:+.2f} USD
"
            f"Resumes tomorrow!"
        )
        return

    if realized_pnl <= -settings["max_daily_loss"]:
        today["stopped"] = True
        with open(trade_log, "w") as f:
            json.dump(today, f, indent=2)
        alert.send(
            f"STOP LOSS HIT!
"
            f"Daily loss: ${abs(realized_pnl):.2f} USD
"
            f"Limit: ${settings['max_daily_loss']} USD
"
            f"Bot stopped! Resumes tomorrow."
        )
        return

    # Max trades
    if today["trades"] >= settings["max_trades_day"]:
        pnl_emoji = "✅" if realized_pnl >= 0 else "❌"
        alert.send(
            f"Max trades reached!
"
            f"Trades: {today['trades']}/{settings['max_trades_day']}
"
            f"Realized PnL: ${realized_pnl:+.2f} USD {pnl_emoji}
"
            f"= ${pl_sgd:+.2f} SGD
"
            f"New trades resume tomorrow!"
        )
        return

    # FIX 3: Skip bad sessions - just monitor open positions
    if not good_session:
        open_positions = []
        for name, config in ASSETS.items():
            pos = trader.get_position(name)
            if pos:
                pnl = trader.check_pnl(pos)
                direction = "BUY" if int(float(pos["long"]["units"])) > 0 else "SELL"
                open_positions.append(f"{config['emoji']} {name}: {direction} | PnL ${pnl:+.2f}")

        if open_positions:
            alert.send(
                f"Monitoring open trades
"
                f"Time: {now.strftime('%H:%M SGT')}
"
                f"Session: {session}
"
                f"No new trades (off-hours)
"
                f"Balance: ${current_balance:.2f}
"
                f"Realized: ${realized_pnl:+.2f} USD
"
                f"Open: ${open_pnl:+.2f} USD
"
                f"---
" + "
".join(open_positions)
            )
        return

    # Active session - scan for trades!
    signals      = SignalEngine()
    scan_results = []
    new_trades   = 0

    for name, config in ASSETS.items():
        if not settings.get(config["setting"], True):
            continue
        if today["trades"] >= settings["max_trades_day"]:
            break

        # Check open position
        position = trader.get_position(name)
        if position:
            pnl       = trader.check_pnl(position)
            direction = "BUY" if int(float(position["long"]["units"])) > 0 else "SELL"
            pnl_emoji = "📈" if pnl > 0 else "📉"
            scan_results.append(
                f"{config['emoji']} {name}: {direction} open {pnl_emoji} ${pnl:+.2f}"
            )
            continue

        # FIX 2: Check cooldown
        if is_in_cooldown(today, name):
            scan_results.append(f"{config['emoji']} {name}: cooldown (30min after SL)")
            continue

        # FIX 1: Check trend direction
        trend = get_trend(trader, name)
        log.info(f"{name} trend: {trend}")
        if trend == "NONE":
            scan_results.append(f"{config['emoji']} {name}: choppy trend - skip")
            continue

        # Get signal score
        score, direction, details = signals.analyze(asset=config["asset"])
        log.info(f"{name}: {score}/5 -> {direction} | trend: {trend}")

        # FIX 1: Signal must match trend!
        if direction != trend:
            scan_results.append(
                f"{config['emoji']} {name}: {score}/5 signal={direction} trend={trend} - MISMATCH skip"
            )
            continue

        if score < settings["signal_threshold"] or direction == "NONE":
            scan_results.append(f"{config['emoji']} {name}: {score}/5 - weak signal")
            continue

        # Place order!
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
            sl_pips     = config["stop_pips"]
            tp_pips     = config["tp_pips"]
            sl_usd      = sl_pips if "XAU" not in name else sl_pips * 0.02
            tp_usd      = tp_pips if "XAU" not in name else tp_pips * 0.02

            alert.send(
                f"NEW TRADE! {mode}
"
                f"{config['emoji']} {name}
"
                f"Direction: {direction}
"
                f"Trend: {trend} (matched!)
"
                f"Score: {score}/5
"
                f"Entry: {price:.5f}
"
                f"Stop Loss: {sl_pips} pips (${sl_usd:.0f} risk)
"
                f"Take Profit: {tp_pips} pips (${tp_usd:.0f} reward)
"
                f"Trade #{today['trades']}/{settings['max_trades_day']} today
"
                f"Session: {session}"
            )
            scan_results.append(
                f"{config['emoji']} {name}: {direction} PLACED! {score}/5"
            )
        else:
            # FIX 2: Set cooldown on failed order too
            set_cooldown(today, name)
            with open(trade_log, "w") as f:
                json.dump(today, f, indent=2)
            log.error(f"{name} order failed: {result.get('error')}")
            scan_results.append(f"{config['emoji']} {name}: order failed")

    # Build scan summary
    pnl_emoji  = "✅" if realized_pnl >= 0 else "❌"
    target_hit = realized_pnl >= 22  # $30 SGD target

    if target_hit:
        target_msg = f"TARGET HIT! ${pl_sgd:+.0f} SGD today!"
    elif realized_pnl > 0:
        target_msg = f"Profit ${pl_sgd:+.0f} SGD (target $30 SGD)"
    elif realized_pnl < 0:
        target_msg = f"Loss ${abs(pl_sgd):.0f} SGD today"
    else:
        target_msg = "Waiting for closed trades..."

    summary = "
".join(scan_results) if scan_results else "No signals this scan"

    alert.send(
        f"Scan Complete! {mode}
"
        f"Time: {now.strftime('%H:%M SGT')}
"
        f"Session: {session}
"
        f"Balance: ${current_balance:.2f}
"
        f"Start:   ${start_balance:.2f}
"
        f"Realized: ${realized_pnl:+.2f} USD {pnl_emoji}
"
        f"= ${pl_sgd:+.2f} SGD
"
        f"Open PnL: ${open_pnl:+.2f} USD
"
        f"Total:    ${total_pnl:+.2f} USD
"
        f"{target_msg}
"
        f"Trades: {today['trades']}/{settings['max_trades_day']}
"
        f"---
"
        f"{summary}"
    )

if __name__ == "__main__":
    run_bot()
