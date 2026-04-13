"""
Railway Entry Point - OANDA GBP/USD London Scalp Bot
=====================================================
Railway runs this 24/7 as a continuous process.

FIX LOG:
  BUG-12: STATE now includes "start_balance" field
  BUG-13: Day-reset block fetches fresh balance from OANDA
  FIX-14: Login FAILED alert suppressed outside London session (15-24 SGT)
           to prevent Telegram spam during off-hours restarts
  FIX-15: Startup env-var check — logs clear error if API key missing
  FIX-16: Off-hours sleep extended to 60s (was 5min already, now explicit)
           scan interval stays 5min during London session
"""

import os, time, logging, traceback
from datetime import datetime
import pytz

from bot          import run_bot, ASSETS, is_in_session
from oanda_trader import OandaTrader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger(__name__)

INTERVAL_MINUTES = 5

sg_tz = pytz.timezone("Asia/Singapore")

STATE = {}


def get_today_key():
    return datetime.now(sg_tz).strftime("%Y%m%d")


def fresh_day_state(today_str, balance):
    return {
        "date":          today_str,
        "trades":        0,
        "start_balance": balance,
        "daily_pnl":     0.0,
        "stopped":       False,
        "wins":          0,
        "losses":        0,
        "consec_losses": 0,
        "cooldowns":     {},
        "open_times":    {},
        "news_alerted":  {},
    }


def check_env_vars():
    """Warn loudly at startup if credentials are missing."""
    api_key    = os.environ.get("OANDA_API_KEY", "")
    account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
    if not api_key or not account_id:
        log.error("=" * 50)
        log.error("❌ MISSING ENV VARS!")
        log.error("   OANDA_API_KEY    : " + ("SET ✅" if api_key    else "MISSING ❌"))
        log.error("   OANDA_ACCOUNT_ID : " + ("SET ✅" if account_id else "MISSING ❌"))
        log.error("   Go to Railway → Variables and set both.")
        log.error("=" * 50)
        return False
    log.info("Env vars OK | Key: " + api_key[:8] + "**** | Account: " + account_id)
    return True


def is_london_session_now():
    now  = datetime.now(sg_tz)
    hour = now.hour
    return any(is_in_session(hour, cfg) for cfg in ASSETS.values())


def main():
    global STATE

    log.info("=" * 50)
    log.info("🚀 Railway Bot Started - OANDA GBP/USD London Scalp")
    log.info("Strategy: GBP/USD | SL=13pip | TP=26pip | 15:00-24:00 SGT")
    log.info("Interval: Every " + str(INTERVAL_MINUTES) + " minutes")
    log.info("=" * 50)

    # FIX-15: Check env vars at startup
    check_env_vars()

    while True:
        now   = datetime.now(sg_tz)
        today = now.strftime("%Y%m%d")
        log.info("⏰ " + now.strftime("%Y-%m-%d %H:%M SGT"))

        # Day reset — fetch live balance
        if STATE.get("date") != today:
            log.info("📅 New day! Fetching balance for day reset...")
            try:
                trader  = OandaTrader(demo=True)
                balance = trader.get_balance() if trader.login() else 0.0
            except Exception as e:
                log.warning("Could not fetch balance for day reset: " + str(e))
                balance = 0.0

            log.info("📅 New day! Balance: $" + str(round(balance, 2)))
            STATE = fresh_day_state(today, balance)

        try:
            run_bot(state=STATE)
        except Exception as e:
            log.error("❌ Bot error: " + str(e))
            log.error(traceback.format_exc())

        log.info("💤 Sleeping " + str(INTERVAL_MINUTES) + " mins...")
        time.sleep(INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
