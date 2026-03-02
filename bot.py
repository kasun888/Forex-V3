"""
🤖 IG Markets Smart Trading Bot
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Capital: $10,000 SGD
Target:  $20-30 SGD/day
Markets: EUR/USD + GBP/USD + XAU/USD (Gold)
Mode:    Demo → Live when ready
"""

import os
import json
import logging
from datetime import datetime
import pytz

from signals import SignalEngine
from ig_trader import IGTrader
from auto_tune import AutoTuner
from telegram_alert import TelegramAlert

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("performance_log.txt"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─── Assets Configuration ─────────────────────────────────────────────────────
# IG uses "epics" as instrument identifiers
ASSETS = {
    "EURUSD": {
        "epic":       "CS.D.EURUSD.CFD.IP",
        "asset":      "EURUSD",
        "label":      "Euro/USD",
        "emoji":      "💱",
        "setting":    "trade_eurusd",
        "size":       2,        # lot size
        "stop_pts":   15,       # 15 pips stop loss
        "limit_pts":  30,       # 30 pips take profit
        "currency":   "USD"
    },
    "GBPUSD": {
        "epic":       "CS.D.GBPUSD.CFD.IP",
        "asset":      "GBPUSD",
        "label":      "GBP/USD",
        "emoji":      "💷",
        "setting":    "trade_gbpusd",
        "size":       2,
        "stop_pts":   20,
        "limit_pts":  40,
        "currency":   "USD"
    },
    "XAUUSD": {
        "epic":       "CS.D.CFDGOLD.CFD.IP",
        "asset":      "XAUUSD",
        "label":      "Gold",
        "emoji":      "🥇",
        "setting":    "trade_gold",
        "size":       1,        # 1 oz gold
        "stop_pts":   150,      # $1.50 stop
        "limit_pts":  300,      # $3.00 target
        "currency":   "USD"
    },
}

# ─── Load Settings ────────────────────────────────────────────────────────────
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

# ─── Trade One Asset ──────────────────────────────────────────────────────────
def trade_asset(name, config, settings, trader, signals, alert, today, trade_log_file):
    log.info(f"🔍 Scanning {name}...")
    epic = config["epic"]

    # Check existing position
    position = trader.get_position(epic)
    if position:
        pnl = trader.check_pnl(position)
        log.info(f"📊 Open {name} position | PnL: {pnl:.2f}")

        tp = config["limit_pts"]
        sl = config["stop_pts"]

        if pnl >= tp * 0.8 or pnl <= -sl * 0.8:
            trader.close_position(position)
            emoji = "✅" if pnl > 0 else "❌"
            alert.send(
                f"{emoji} {config['emoji']} {name} CLOSED!\n"
                f"PnL: {pnl:+.2f} USD\n"
                f"{'Target hit 🎯' if pnl > 0 else 'Stop loss 🛑'}"
            )
            today["daily_pnl"] += pnl
            with open(trade_log_file, "w") as f:
                json.dump(today, f, indent=2)
        return

    # Run 5-layer analysis
    score, direction, details = signals.analyze(asset=config["asset"])
    log.info(f"{name}: {score}/5 → {direction}")

    threshold = settings["signal_threshold"]
    if score < threshold or direction == "NONE":
        log.info(f"⏸️  {name}: Score {score} < {threshold}. Skip.")
        return score, direction, details

    # Place trade
    ig_direction = "BUY" if direction == "BUY" else "SELL"
    result = trader.place_order(
        epic           = epic,
        direction      = ig_direction,
        size           = config["size"],
        stop_distance  = config["stop_pts"],
        limit_distance = config["limit_pts"],
        currency       = config["currency"]
    )

    if result["success"]:
        today["trades"] += 1
        with open(trade_log_file, "w") as f:
            json.dump(today, f, indent=2)

        price, _, _ = trader.get_price(epic)
        arrow = "📈" if direction == "BUY" else "📉"
        alert.send(
            f"{arrow} {config['emoji']} {name} Trade #{today['trades']} OPENED!\n"
            f"Direction: {direction}\n"
            f"Entry: {price:.5f}\n"
            f"Stop:  {config['stop_pts']} pts\n"
            f"Target: {config['limit_pts']} pts\n"
            f"Score: {score}/5\n"
            f"━━━━━━━━━━━━\n"
            f"{details}\n"
            f"{'[DEMO 🎮]' if settings['demo_mode'] else '[LIVE 💰]'}"
        )
        log.info(f"✅ {name} trade placed!")
    else:
        log.error(f"❌ {name} trade failed: {result['error']}")
        alert.send(f"❌ {name} failed: {result['error']}")

    return score, direction, details

# ─── Main Bot ─────────────────────────────────────────────────────────────────
def run_bot():
    log.info("🤖 IG Markets Bot starting — EUR/USD + GBP/USD + Gold")

    settings = load_settings()
    sg_tz    = pytz.timezone("Asia/Singapore")
    now      = datetime.now(sg_tz)

    log.info(f"📅 {now.strftime('%Y-%m-%d %H:%M SGT')} | Demo: {settings['demo_mode']}")

    # IG Forex market hours (SGT):
    # Forex: 24hrs Mon-Fri
    # Gold:  24hrs Mon-Fri
    # Skip weekends
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        log.info("📅 Weekend. Markets closed. Skipping.")
        return

    # Trading hours 8am - 10pm SGT (London + NY sessions best)
    if now.hour < 8 or now.hour >= 22:
        log.info("⏰ Outside trading hours (8am-10pm SGT). Skipping.")
        return

    # Initialize
    trader = IGTrader(demo=settings["demo_mode"])
    if not trader.login():
        alert = TelegramAlert()
        alert.send("❌ IG Login failed! Check credentials in GitHub Secrets!")
        return

    signal = SignalEngine()
    alert  = TelegramAlert()

    # Load today's log
    trade_log_file = f"trades_{now.strftime('%Y%m%d')}.json"
    try:
        with open(trade_log_file) as f:
            today = json.load(f)
    except FileNotFoundError:
        today = {"trades": 0, "daily_pnl": 0.0, "stopped": False, "date": now.strftime('%Y-%m-%d')}

    # Daily loss limit
    if today.get("stopped"):
        log.info("🛑 Daily loss limit hit. Stopped.")
        return

    if today["daily_pnl"] <= -settings["max_daily_loss"]:
        today["stopped"] = True
        with open(trade_log_file, "w") as f:
            json.dump(today, f, indent=2)
        alert.send(f"🛑 Daily loss limit ${settings['max_daily_loss']} hit! Stopped for today.")
        return

    if today["trades"] >= settings["max_trades_day"]:
        log.info(f"✅ Max {settings['max_trades_day']} trades reached.")
        return

    # ── Scan ALL Assets ───────────────────────────────────────────────────────
    scan_results = []
    for name, config in ASSETS.items():
        if not settings.get(config["setting"], False):
            log.info(f"⏭️  {name} disabled. Skipping.")
            continue

        if today["trades"] >= settings["max_trades_day"]:
            break

        result = trade_asset(
            name           = name,
            config         = config,
            settings       = settings,
            trader         = trader,
            signals        = signal,
            alert          = alert,
            today          = today,
            trade_log_file = trade_log_file
        )

        if result:
            score, direction, _ = result
            scan_results.append(f"{config['emoji']} {name}: {score}/5 → {direction}")
        else:
            scan_results.append(f"{config['emoji']} {name}: position open")

    # ── Always Send Telegram Summary ──────────────────────────────────────────
    # Best trading windows SGT:
    # London open: 3pm-4pm SGT
    # NY open: 9:30pm SGT
    # London+NY overlap: 9pm-10pm SGT (most volatile!)
    now_hour = now.hour
    session = "🌏 Asia" if now_hour < 15 else ("🇬🇧 London" if now_hour < 21 else "🇺🇸 NY/London")

    summary = "\n".join(scan_results) if scan_results else "No assets scanned"
    alert.send(
        f"🤖 IG Bot Scan Complete!\n"
        f"{'─'*20}\n"
        f"🕐 {now.strftime('%H:%M SGT')} | {session} session\n"
        f"📊 Trades: {today['trades']}/{settings['max_trades_day']}\n"
        f"💰 PnL: ${today['daily_pnl']:.2f} USD\n"
        f"{'─'*20}\n"
        f"{summary}\n"
        f"{'─'*20}\n"
        f"{'[DEMO 🎮]' if settings['demo_mode'] else '[LIVE 💰]'}"
    )

    log.info(f"✅ Cycle done | Trades: {today['trades']} | PnL: ${today['daily_pnl']:.2f}")

if __name__ == "__main__":
    run_bot()
