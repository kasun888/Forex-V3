"""
OANDA Trading Bot v3 - Pro Strategy
=====================================
Dynamic position sizing
Spread protection
Consecutive loss protection
API security (no key logging)
Retry logic
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
from calendar_filter import EconomicCalendar

# Safe logging - never expose API keys
class SafeFormatter(logging.Formatter):
    def format(self, record):
        msg = super().format(record)
        key = os.environ.get("OANDA_API_KEY", "")
        if key and key in msg:
            msg = msg.replace(key, "***")
        return msg

handler = logging.StreamHandler()
handler.setFormatter(SafeFormatter("%(asctime)s | %(levelname)s | %(message)s"))
file_handler = logging.FileHandler("performance_log.txt")
file_handler.setFormatter(SafeFormatter("%(asctime)s | %(levelname)s | %(message)s"))

logging.basicConfig(level=logging.INFO, handlers=[handler, file_handler])
log = logging.getLogger(__name__)

# ── ASSET CONFIGURATION ─────────────────────────────────────────────────────
ASSETS = {
    "EUR_USD": {
        "instrument": "EUR_USD",
        "asset":      "EURUSD",
        "emoji":      "💱",
        "setting":    "trade_eurusd",
        "stop_pips":  20,       # 20 pips SL
        "tp_pips":    30,       # 30 pips TP = 1:1.5 R:R
        "pip":        0.0001,
        "precision":  5,
        "min_atr":    0.0008,   # Skip if ATR below this (low volatility)
    },
    "GBP_USD": {
        "instrument": "GBP_USD",
        "asset":      "GBPUSD",
        "emoji":      "💷",
        "setting":    "trade_gbpusd",
        "stop_pips":  20,
        "tp_pips":    30,
        "pip":        0.0001,
        "precision":  5,
        "min_atr":    0.0010,
    },
    "XAU_USD": {
        "instrument": "XAU_USD",
        "asset":      "XAUUSD",
        "emoji":      "🥇",
        "setting":    "trade_gold",
        "stop_pips":  800,
        "tp_pips":    1500,
        "pip":        0.01,
        "precision":  2,
        "min_atr":    5.0,
    },
}

def load_settings():
    default = {
        "max_trades_day":       4,
        "max_daily_loss":       40.0,
        "signal_threshold":     4,
        "demo_mode":            True,
        "trade_eurusd":         True,
        "trade_gbpusd":         True,
        "trade_gold":           True,
        "risk_pct":             0.005,   # 0.5% risk per trade
        "max_consec_losses":    2,       # Stop after 2 consecutive losses
        "max_spread_pips":      2,       # Skip if spread > 2 pips
    }
    try:
        with open("settings.json") as f:
            saved = json.load(f)
            default.update(saved)
    except FileNotFoundError:
        with open("settings.json", "w") as f:
            json.dump(default, f, indent=2)
    return default

def calc_position_size(balance, risk_pct, stop_pips, pip_value):
    """
    Dynamic position sizing
    Risk per trade = 0.5% of balance
    Example: $10,000 x 0.5% = $50 max loss
    Size = max_loss / (stop_pips x pip_per_unit)
    """
    max_loss   = balance * risk_pct
    size       = max_loss / (stop_pips * pip_value)
    # Round to nearest 1000 for forex, 1 for gold
    if pip_value <= 0.0001:
        size = round(size / 1000) * 1000
        size = max(1000, min(size, 50000))   # Min 1k max 50k
    else:
        size = max(1, min(round(size), 10))  # Min 1 max 10 oz gold
    return size

def check_spread(trader, instrument, max_spread_pips, pip):
    """Skip trade if spread too wide"""
    try:
        bid, ask, _ = trader.get_price(instrument)
        spread_pips = (ask - bid) / pip
        log.info(instrument + " spread=" + str(round(spread_pips, 1)) + " pips")
        if spread_pips > max_spread_pips:
            log.warning(instrument + " spread too wide: " + str(round(spread_pips, 1)) + " > " + str(max_spread_pips))
            return False, spread_pips
        return True, spread_pips
    except Exception as e:
        log.warning("Spread check error: " + str(e))
        return True, 0  # Allow trade if check fails

def is_in_cooldown(today, instrument):
    cooldowns = today.get("cooldowns", {})
    if instrument not in cooldowns:
        return False
    last_loss  = datetime.fromisoformat(cooldowns[instrument])
    wait_until = last_loss + timedelta(minutes=30)
    now_utc    = datetime.utcnow()
    if now_utc < wait_until:
        mins = int((wait_until - now_utc).seconds / 60)
        log.info(instrument + " cooldown " + str(mins) + " mins left")
        return True
    return False

def set_cooldown(today, instrument):
    if "cooldowns" not in today:
        today["cooldowns"] = {}
    today["cooldowns"][instrument] = datetime.utcnow().isoformat()

def get_trend_h1(trader, instrument):
    """H1 EMA50 vs EMA200 trend filter"""
    try:
        url    = trader.base_url + "/v3/instruments/" + instrument + "/candles"
        params = {"count": "250", "granularity": "H1", "price": "M"}
        for attempt in range(3):
            try:
                r = requests.get(url, headers=trader.headers, params=params, timeout=10)
                if r.status_code == 200:
                    break
            except:
                pass
        else:
            return "NONE"

        candles = r.json()["candles"]
        closes  = [float(c["mid"]["c"]) for c in candles if c["complete"]]
        if len(closes) < 200:
            return "NONE"

        def ema(data, period):
            if len(data) < period:
                return [sum(data)/len(data)] * len(data)
            seed = sum(data[:period]) / period
            emas = [seed] * period
            mult = 2 / (period + 1)
            for p in data[period:]:
                emas.append((p - emas[-1]) * mult + emas[-1])
            return emas

        ema50  = ema(closes, 50)[-1]
        ema200 = ema(closes, 200)[-1]
        log.info(instrument + " H1 EMA50=" + str(round(ema50, 5)) + " EMA200=" + str(round(ema200, 5)))

        if ema50 > ema200 * 1.0002:
            return "BUY"
        elif ema50 < ema200 * 0.9998:
            return "SELL"
        return "NONE"
    except Exception as e:
        log.warning("Trend error: " + str(e))
        return "NONE"

def run_bot():
    log.info("OANDA Bot v3 starting!")
    settings = load_settings()
    sg_tz    = pytz.timezone("Asia/Singapore")
    now      = datetime.now(sg_tz)
    alert    = TelegramAlert()
    hour     = now.hour

    # Session detection
    # Singapore time: 2pm-11pm SGT (proposed improvement!)
    good_session = (14 <= hour <= 23) or (0 <= hour <= 1)

    if 14 <= hour <= 17:
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

    # Weekend check
    if now.weekday() == 5:
        alert.send("Saturday - markets closed! Bot resumes Monday 5am SGT")
        return
    if now.weekday() == 6 and hour < 5:
        alert.send("Sunday early - markets open at 5am SGT")
        return

    # Login with retry
    trader = OandaTrader(demo=settings["demo_mode"])
    if not trader.login():
        alert.send("OANDA Login FAILED! Check OANDA_API_KEY and OANDA_ACCOUNT_ID secrets")
        return

    current_balance = trader.get_balance()
    mode            = "DEMO" if settings["demo_mode"] else "LIVE"

    # Load today log
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
            "consec_losses": 0,
            "cooldowns":     {}
        }
        with open(trade_log, "w") as f:
            json.dump(today, f, indent=2)
        log.info("New day! Start balance: $" + str(round(current_balance, 2)))

    # Real PnL tracking
    start_balance = today.get("start_balance", current_balance)
    open_pnl      = sum(
        trader.check_pnl(trader.get_position(n))
        for n in ASSETS if trader.get_position(n)
    )
    realized_pnl  = current_balance - start_balance
    total_pnl     = realized_pnl + open_pnl
    pl_sgd        = realized_pnl * 1.35
    pnl_emoji     = "✅" if realized_pnl >= 0 else "❌"

    today["daily_pnl"] = realized_pnl
    with open(trade_log, "w") as f:
        json.dump(today, f, indent=2)

    # Daily loss protection
    if today.get("stopped"):
        alert.send(
            "Bot stopped for today\n"
            "Daily loss limit or consecutive losses hit!\n"
            "Realized: $" + str(round(realized_pnl, 2)) + " USD\n"
            "Resumes tomorrow!"
        )
        return

    if realized_pnl <= -settings["max_daily_loss"]:
        today["stopped"] = True
        with open(trade_log, "w") as f:
            json.dump(today, f, indent=2)
        alert.send(
            "DAILY LOSS LIMIT HIT!\n"
            "Loss: $" + str(abs(round(realized_pnl, 2))) + " USD\n"
            "Limit: $" + str(settings["max_daily_loss"]) + " USD\n"
            "Bot stopped! Resumes tomorrow."
        )
        return

    # Consecutive loss protection
    consec = today.get("consec_losses", 0)
    if consec >= settings.get("max_consec_losses", 2):
        today["stopped"] = True
        with open(trade_log, "w") as f:
            json.dump(today, f, indent=2)
        alert.send(
            "2 CONSECUTIVE LOSSES!\n"
            "Bot protecting capital!\n"
            "Stopped for today.\n"
            "Realized: $" + str(round(realized_pnl, 2)) + " USD\n"
            "Resumes tomorrow!"
        )
        return

    # Max trades
    if today["trades"] >= settings["max_trades_day"]:
        alert.send(
            "Max trades reached!\n"
            "Trades: " + str(today["trades"]) + "/" + str(settings["max_trades_day"]) + "\n"
            "Realized: $" + str(round(realized_pnl, 2)) + " USD " + pnl_emoji + "\n"
            "= $" + str(round(pl_sgd, 2)) + " SGD\n"
            "New trades resume tomorrow!"
        )
        return

    # Off hours - just monitor
    if not good_session:
        open_positions = []
        for name, config in ASSETS.items():
            pos = trader.get_position(name)
            if pos:
                pnl       = trader.check_pnl(pos)
                direction = "BUY" if int(float(pos["long"]["units"])) > 0 else "SELL"
                open_positions.append(config["emoji"] + " " + name + ": " + direction + " $" + str(round(pnl, 2)))

        positions_str = "\n".join(open_positions) if open_positions else "No open trades"
        alert.send(
            "Off-hours status\n"
            "Time: " + now.strftime("%H:%M SGT") + "\n"
            "Session: " + session + "\n"
            "Balance: $" + str(round(current_balance, 2)) + "\n"
            "Realized: $" + str(round(realized_pnl, 2)) + " USD " + pnl_emoji + "\n"
            "= $" + str(round(pl_sgd, 2)) + " SGD\n"
            "Trading starts: 2pm SGT\n"
            "---\n" + positions_str
        )
        return

    # Active session - scan!
    signals      = SignalEngine()
    calendar     = EconomicCalendar()
    scan_results = []
    new_trades   = 0

    # Warn about news events today
    news_summary = calendar.get_today_summary()
    if "No high" not in news_summary:
        alert.send("NEWS ALERT TODAY!\n" + news_summary)

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
            emoji     = "📈" if pnl > 0 else "📉"
            scan_results.append(config["emoji"] + " " + name + ": " + direction + " open " + emoji + " $" + str(round(pnl, 2)))
            continue

        # Cooldown check
        if is_in_cooldown(today, name):
            scan_results.append(config["emoji"] + " " + name + ": cooldown (30min after SL)")
            continue

        # Spread check
        spread_ok, spread_val = check_spread(trader, name, settings.get("max_spread_pips", 2), config["pip"])
        if not spread_ok:
            scan_results.append(config["emoji"] + " " + name + ": spread=" + str(round(spread_val, 1)) + " pips too wide - skip")
            continue

        # News blackout check
        news_active, news_reason = calendar.is_news_time(name)
        if news_active:
            scan_results.append(config["emoji"] + " " + name + ": PAUSED - " + news_reason)
            continue

        # Trend filter
        trend = get_trend_h1(trader, name)
        log.info(name + " H1 trend: " + trend)
        if trend == "NONE":
            scan_results.append(config["emoji"] + " " + name + ": no clear H1 trend - skip")
            continue

        # Signal analysis
        score, direction, details = signals.analyze(asset=config["asset"])
        log.info(name + ": score=" + str(score) + " dir=" + direction + " trend=" + trend)

        # Signal must match trend!
        if direction != trend:
            scan_results.append(config["emoji"] + " " + name + ": signal=" + direction + " trend=" + trend + " mismatch - skip")
            continue

        if score < settings["signal_threshold"] or direction == "NONE":
            scan_results.append(config["emoji"] + " " + name + ": " + str(score) + "/5 weak signal")
            continue

        # Dynamic position sizing
        risk_pct  = settings.get("risk_pct", 0.005)
        size      = calc_position_size(
            current_balance, risk_pct,
            config["stop_pips"], config["pip"]
        )
        max_loss  = round(size * config["stop_pips"] * config["pip"], 2)
        max_profit = round(size * config["tp_pips"] * config["pip"], 2)

        log.info(name + " size=" + str(size) + " risk=$" + str(max_loss) + " reward=$" + str(max_profit))

        # Place order
        result = trader.place_order(
            instrument     = name,
            direction      = direction,
            size           = size,
            stop_distance  = config["stop_pips"],
            limit_distance = config["tp_pips"]
        )

        if result["success"]:
            today["trades"]        += 1
            today["consec_losses"]  = 0  # Reset on new trade
            new_trades             += 1
            with open(trade_log, "w") as f:
                json.dump(today, f, indent=2)

            price, _, _ = trader.get_price(name)
            alert.send(
                "NEW TRADE! " + mode + "\n"
                + config["emoji"] + " " + name + "\n"
                "Direction: " + direction + "\n"
                "H1 Trend:  " + trend + " matched!\n"
                "Score:     " + str(score) + "/5\n"
                "Entry:     " + str(round(price, config["precision"])) + "\n"
                "Size:      " + str(size) + " units\n"
                "Stop Loss: " + str(config["stop_pips"]) + " pips = $" + str(max_loss) + "\n"
                "Take Prof: " + str(config["tp_pips"]) + " pips = $" + str(max_profit) + "\n"
                "Spread:    " + str(round(spread_val, 1)) + " pips\n"
                "Trade #" + str(today["trades"]) + "/" + str(settings["max_trades_day"]) + "\n"
                "Session: " + session
            )
            scan_results.append(config["emoji"] + " " + name + ": " + direction + " PLACED! " + str(score) + "/5")
        else:
            set_cooldown(today, name)
            with open(trade_log, "w") as f:
                json.dump(today, f, indent=2)
            scan_results.append(config["emoji"] + " " + name + ": order failed")

    # Target message
    target_hit = realized_pnl >= 22
    if target_hit:
        target_msg = "TARGET HIT! $" + str(round(pl_sgd, 0)) + " SGD today!"
    elif realized_pnl > 0:
        target_msg = "Profit $" + str(round(pl_sgd, 0)) + " SGD (target $30 SGD)"
    elif realized_pnl < 0:
        target_msg = "Loss $" + str(abs(round(pl_sgd, 0))) + " SGD today"
    else:
        target_msg = "Waiting for closed trades..."

    summary = "\n".join(scan_results) if scan_results else "No signals this scan"
    wins    = today.get("wins", 0)
    losses  = today.get("losses", 0)
    consec  = today.get("consec_losses", 0)

    alert.send(
        "Scan Complete! " + mode + "\n"
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
        "W/L: " + str(wins) + "/" + str(losses) + " | Consec loss: " + str(consec) + "\n"
        "---\n"
        + summary
    )

if __name__ == "__main__":
    run_bot()
