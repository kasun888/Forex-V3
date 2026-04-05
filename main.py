"""
Railway Entry Point - OANDA Demo 2 Mean Reversion Bot
======================================================
Railway runs this 24/7 as a continuous process.
Runs bot every 5 minutes with IN-MEMORY state
(Railway filesystem is ephemeral - no file storage!)

FIX LOG:
  BUG-12: STATE now includes "start_balance" field (was missing -- broke daily PnL calc)
  BUG-13: Day-reset block now fetches fresh balance from OANDA to seed start_balance
           (previously reset to 0.0, making daily PnL always show $0)
  BUG-14: REMOVED heartbeat -- was spamming Telegram every hour
  BUG-15: Weekend silence -- no Telegram messages on Saturday or Sunday before 5am SGT
  BUG-16: "New Day Started" alert suppressed on weekends
"""

import time
import logging
import traceback
from datetime import datetime
import pytz

from bot           import run_bot
from oanda_trader  import OandaTrader
from telegram_alert import TelegramAlert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger(__name__)

INTERVAL_MINUTES = 5

# ── IN-MEMORY STATE (persists across 5-min runs, resets on restart) ──────────
STATE = {}


def get_today_key():
    sg_tz = pytz.timezone("Asia/Singapore")
    return datetime.now(sg_tz).strftime("%Y%m%d")


def is_weekend(now):
    """True during market-closed weekend: Saturday all day, Sunday before 5am SGT."""
    wd = now.weekday()
    return wd == 5 or (wd == 6 and now.hour < 5)


def fresh_day_state(today_str, balance):
    """Return a clean state dict for a new trading day."""
    return {
        "date":          today_str,
        "trades":        0,
        # BUG-12/13 FIX: seed start_balance from live account balance
        "start_balance": balance,
        "daily_pnl":     0.0,
        "stopped":       False,
        "wins":          0,
        "losses":        0,
        "consec_losses": 0,
        "cooldowns":     {},
        "open_times":    {},
        "news_alerted":  {},
        "daily_summary_sent": False,
    }


def main():
    sg_tz = pytz.timezone("Asia/Singapore")
    global STATE

    log.info("=" * 50)
    log.info("Railway Bot Started - OANDA Demo 2")
    log.info("Strategy: M1 Ultra-Scalp")
    log.info("Interval: Every " + str(INTERVAL_MINUTES) + " minutes")
    log.info("=" * 50)

    while True:
        now   = datetime.now(sg_tz)
        today = now.strftime("%Y%m%d")
        log.info("Scan: " + now.strftime("%Y-%m-%d %H:%M SGT"))

        # BUG-15/16 FIX: skip entirely on weekend -- no trades, no Telegram noise
        if is_weekend(now):
            log.info("Weekend -- bot silent, sleeping...")
            time.sleep(INTERVAL_MINUTES * 60)
            continue

        # BUG-12/13 FIX: fetch live balance when resetting for a new day
        if STATE.get("date") != today:
            log.info("New day! Fetching balance for day reset...")
            try:
                trader  = OandaTrader(demo=True)
                balance = trader.get_balance() if trader.login() else 0.0
            except Exception as e:
                log.warning("Could not fetch balance for day reset: " + str(e))
                balance = 0.0

            log.info("New day! Balance: $" + str(round(balance, 2)))
            STATE = fresh_day_state(today, balance)

            # BUG-16 FIX: only send new-day alert on weekdays (weekend check above)
            alert = TelegramAlert()
            alert.send(
                "New Day Started\n"
                "Balance: $" + str(round(balance, 2)) + "\n"
                "Bot is running every 5 min"
            )

        try:
            run_bot(state=STATE)
        except Exception as e:
            log.error("Bot error: " + str(e))
            log.error(traceback.format_exc())

        log.info("Sleeping " + str(INTERVAL_MINUTES) + " mins...")
        time.sleep(INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
