"""
📱 Telegram Alert System
"""
import os
import requests
import logging

log = logging.getLogger(__name__)

class TelegramAlert:
    def __init__(self):
        self.token   = os.environ.get("TELEGRAM_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    def send(self, message: str):
        if not self.token or not self.chat_id:
            log.warning("Telegram not configured")
            return False
        try:
            url  = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text":    f"🤖 IG Bot\n{'─'*20}\n{message}"
            }
            r = requests.post(url, data=data, timeout=10)
            log.info(f"Telegram status: {r.status_code}")
            if r.status_code == 200:
                log.info("✅ Telegram sent!")
                return True
            log.warning(f"Telegram error: {r.text}")
            return False
        except Exception as e:
            log.error(f"Telegram error: {e}")
            return False

    def send_daily_summary(self, trades, pnl, win_rate):
        emoji = "✅" if pnl > 0 else "❌"
        self.send(
            f"📊 DAILY SUMMARY\n"
            f"Trades: {trades}\n"
            f"PnL: {pnl:+.2f} USD {emoji}\n"
            f"Win rate: {win_rate:.0f}%\n"
            f"{'Great day! 🎉' if pnl > 0 else 'Better tomorrow! 💪'}"
        )
