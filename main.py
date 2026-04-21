"""
Railway Entry Point - OANDA EUR/USD London+NY Session Scalp Bot
================================================================
Windows (SGT):
  15:00–19:00 SGT — London Open
  20:00–00:00 SGT — NY Session
Account: SGD
"""

import os, time, logging, traceback
from datetime import datetime
import pytz

from bot            import run_bot, ASSETS, is_in_session, usd_to_sgd
from oanda_trader   import OandaTrader
from telegram_alert import TelegramAlert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger(__name__)

INTERVAL_MINUTES = 5
sg_tz            = pytz.timezone("Asia/Singapore")
STATE            = {}


def get_today_key():
    return datetime.now(sg_tz).strftime("%Y%m%d")


def fresh_day_state(today_str, balance_usd):
    return {
        "date":               today_str,
        "trades":             0,
        "start_balance":      balance_usd,
        "daily_pnl":          0.0,
        "stopped":            False,
        "wins":               0,
        "losses":             0,
        "consec_losses":      0,
        "cooldowns":          {},
        "open_times":         {},
        "news_alerted":       {},
        "session_alerted":    {},
        "login_fail_alerted": {},
    }


def check_env_vars():
    api_key    = os.environ.get("OANDA_API_KEY", "")
    account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
    tg_token   = os.environ.get("TELEGRAM_TOKEN", "")
    tg_chat    = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not api_key or not account_id:
        log.error("=" * 50)
        log.error("❌ MISSING OANDA ENV VARS!")
        log.error("   OANDA_API_KEY    : " + ("SET ✅" if api_key    else "MISSING ❌"))
        log.error("   OANDA_ACCOUNT_ID : " + ("SET ✅" if account_id else "MISSING ❌"))
        log.error("=" * 50)
        return False

    log.info("Env vars OK | Key: " + api_key[:8] + "**** | Account: " + account_id)
    if not tg_token or not tg_chat:
        log.warning("Telegram not configured — no alerts will be sent")
    return True


def main():
    global STATE

    log.info("=" * 50)
    log.info("🚀 Railway Bot Started - OANDA EUR/USD London+NY Scalp")
    log.info("Window 1: 15:00–19:00 SGT (London) | Window 2: 20:00–00:00 SGT (NY)")
    log.info("EUR/USD | SL=13pip | TP=26pip | Signal: 4/4 | SGD Account")
    log.info("=" * 50)

    if not check_env_vars():
        log.error("Missing env vars — sleeping 60s then exiting")
        time.sleep(60)
        return

    alert = TelegramAlert()

    # Get balance for startup message
    try:
        import json
        settings_path = "settings.json"
        demo_mode = True
        try:
            with open(settings_path) as f:
                demo_mode = json.load(f).get("demo_mode", True)
        except:
            pass
        trader = OandaTrader(demo=demo_mode)
        balance_usd = trader.get_balance() if trader.login() else 0.0
        balance_sgd = usd_to_sgd(balance_usd)
        mode_str    = "DEMO" if demo_mode else "LIVE"
    except Exception as e:
        balance_sgd = 0.0
        mode_str    = "DEMO"
        log.warning("Startup balance fetch error: " + str(e))

    alert.send_startup(balance_sgd=balance_sgd, mode=mode_str)

    while True:
        try:
            now   = datetime.now(sg_tz)
            today = now.strftime("%Y%m%d")
            log.info("⏰ " + now.strftime("%Y-%m-%d %H:%M SGT"))

            # Day reset
            if STATE.get("date") != today:
                # Send daily summary if we have a previous day
                if STATE.get("date"):
                    try:
                        bal_usd = trader.get_balance() if trader.login() else 0.0
                        bal_sgd = usd_to_sgd(bal_usd)
                        alert.send_daily_summary(
                            balance_sgd=bal_sgd,
                            start_balance_sgd=usd_to_sgd(STATE.get("start_balance", 0)),
                            trades=STATE.get("trades", 0),
                            wins=STATE.get("wins", 0),
                            losses=STATE.get("losses", 0),
                            pnl_sgd=usd_to_sgd(STATE.get("daily_pnl", 0.0)),
                        )
                    except Exception as e:
                        log.warning("Daily summary error: " + str(e))

                log.info("📅 New day! Fetching balance...")
                try:
                    trader  = OandaTrader(demo=True)
                    bal_usd = trader.get_balance() if trader.login() else 0.0
                except Exception as e:
                    log.warning("Balance fetch error: " + str(e))
                    bal_usd = 0.0
                log.info("📅 New day! Balance: SGD " + str(usd_to_sgd(bal_usd)))
                STATE = fresh_day_state(today, bal_usd)

            run_bot(state=STATE)

        except Exception as e:
            log.error("❌ Bot error: " + str(e))
            log.error(traceback.format_exc())
            time.sleep(30)

        log.info("💤 Sleeping " + str(INTERVAL_MINUTES) + " mins...")
        time.sleep(INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
