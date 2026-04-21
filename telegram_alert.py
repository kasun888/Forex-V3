"""
Telegram Alert System — Rich formatted messages for EUR/USD bot
SGD account display throughout.
"""
import os
import requests
import logging
from datetime import datetime
import pytz

log = logging.getLogger(__name__)
sg_tz = pytz.timezone("Asia/Singapore")


class TelegramAlert:
    def __init__(self):
        self.token   = os.environ.get("TELEGRAM_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    def send(self, message: str):
        if not self.token or not self.chat_id:
            log.warning("Telegram not configured — TELEGRAM_TOKEN or TELEGRAM_CHAT_ID missing")
            return False
        try:
            url  = f"https://api.telegram.org/bot{self.token}/sendMessage"
            now  = datetime.now(sg_tz).strftime("%H:%M SGT")
            text = f"🤖 EUR/USD Bot  |  {now}\n{'━'*26}\n{message}"
            data = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
            r    = requests.post(url, data=data, timeout=10)
            if r.status_code == 200:
                log.info("Telegram sent!")
                return True
            # Retry without parse_mode in case of HTML issue
            data.pop("parse_mode", None)
            text_plain = text.replace("<b>", "").replace("</b>", "").replace("<i>","").replace("</i>","")
            data["text"] = text_plain
            r2 = requests.post(url, data=data, timeout=10)
            if r2.status_code == 200:
                return True
            log.warning(f"Telegram error {r.status_code}: {r.text[:200]}")
            return False
        except Exception as e:
            log.error(f"Telegram error: {e}")
            return False

    # ── Rich message builders ─────────────────────────────────────────

    def send_startup(self, balance_sgd, mode="DEMO"):
        mode_emoji = "🟡" if mode == "DEMO" else "🔴"
        self.send(
            f"{mode_emoji} <b>Bot Started — {mode} MODE</b>\n"
            f"Pair:    EUR/USD 🇪🇺\n"
            f"Balance: SGD {balance_sgd:,.2f}\n"
            f"SL:      13 pip | TP: 26 pip | 2:1 R:R\n"
            f"Signal:  4/4 layers required\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📅 Windows (SGT):\n"
            f"  🇬🇧 London  15:00 – 19:00\n"
            f"  🇺🇸 NY      20:00 – 00:00\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ Option A loosening active:\n"
            f"  ATR ≥ 2.5p | RSI 35–65 | L2 buf 15p | 90min window"
        )

    def send_session_open(self, session_label, session_hours, balance_sgd, trades_today, wins, losses):
        session_emoji = "🇬🇧" if session_label == "London" else "🇺🇸"
        win_rate = f"{round(wins/(wins+losses)*100)}%" if (wins+losses) > 0 else "—"
        self.send(
            f"{session_emoji} <b>{session_label} Window OPEN</b>\n"
            f"⏰ {session_hours} SGT\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance:     SGD {balance_sgd:,.2f}\n"
            f"📊 Today:       {trades_today} trade(s)\n"
            f"🏆 W/L:         {wins}W / {losses}L  ({win_rate})\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔍 Scanning EUR/USD every 5 min..."
        )

    def send_session_close(self, session_label, balance_sgd, session_trades, session_pnl_sgd, wins, losses):
        pnl_emoji = "✅" if session_pnl_sgd >= 0 else "🔴"
        pnl_sign  = "+" if session_pnl_sgd >= 0 else ""
        self.send(
            f"🔔 <b>{session_label} Window CLOSED</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 Trades:    {session_trades}\n"
            f"💰 Session P&L: {pnl_emoji} SGD {pnl_sign}{session_pnl_sgd:,.2f}\n"
            f"💼 Balance:   SGD {balance_sgd:,.2f}\n"
            f"🏆 Today W/L: {wins}W / {losses}L"
        )

    def send_trade_open(self, direction, entry_price, sl_pips, tp_pips,
                        sl_sgd, tp_sgd, spread, score, session_label,
                        layer_breakdown, balance_sgd, trades_today):
        dir_emoji = "🟢" if direction == "BUY" else "🔴"
        layers_str = ""
        for k, v in layer_breakdown.items():
            layers_str += f"  {k}: {v}\n"

        self.send(
            f"{dir_emoji} <b>NEW TRADE — {direction}</b>  [{session_label}]\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Pair:    EUR/USD 🇪🇺\n"
            f"Entry:   {entry_price:.5f}\n"
            f"Size:    74,000 units\n"
            f"Spread:  {spread:.2f} pip\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎯 Signal Score: {score}/4 ✅\n"
            f"🛑 SL:  {sl_pips} pip ≈ SGD -{sl_sgd:,.2f}\n"
            f"✅ TP:  {tp_pips} pip ≈ SGD +{tp_sgd:,.2f}\n"
            f"⏱  Max: 30 min\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📋 Layer Breakdown:\n{layers_str}"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💼 Balance: SGD {balance_sgd:,.2f}\n"
            f"📊 Trade #{trades_today} today"
        )

    def send_tp_hit(self, pnl_usd, pnl_sgd, balance_sgd, wins, losses, entry, close_price):
        self.send(
            f"✅ <b>TAKE PROFIT HIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Pair:    EUR/USD 🇪🇺\n"
            f"Entry:   {entry:.5f} → {close_price:.5f}\n"
            f"P&L:     +SGD {pnl_sgd:,.2f}  (USD {pnl_usd:+.2f})\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💼 Balance: SGD {balance_sgd:,.2f}\n"
            f"🏆 W/L:     {wins}W / {losses}L"
        )

    def send_sl_hit(self, pnl_usd, pnl_sgd, balance_sgd, wins, losses, entry, close_price):
        self.send(
            f"🔴 <b>STOP LOSS HIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Pair:    EUR/USD 🇪🇺\n"
            f"Entry:   {entry:.5f} → {close_price:.5f}\n"
            f"P&L:     -SGD {abs(pnl_sgd):,.2f}  (USD {pnl_usd:+.2f})\n"
            f"⏳ Cooldown: 30 min\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💼 Balance: SGD {balance_sgd:,.2f}\n"
            f"🏆 W/L:     {wins}W / {losses}L"
        )

    def send_timeout_close(self, minutes, pnl_usd, pnl_sgd, balance_sgd):
        pnl_emoji = "✅" if pnl_sgd >= 0 else "🔴"
        pnl_sign  = "+" if pnl_sgd >= 0 else ""
        self.send(
            f"⏰ <b>30-MIN TIMEOUT CLOSE</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Pair:    EUR/USD 🇪🇺\n"
            f"Duration: {minutes:.1f} min\n"
            f"P&L:     {pnl_emoji} SGD {pnl_sign}{pnl_sgd:,.2f}  (USD {pnl_usd:+.2f})\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💼 Balance: SGD {balance_sgd:,.2f}"
        )

    def send_news_block(self, instrument, news_reason):
        self.send(
            f"📰 <b>NEWS BLOCK</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Pair:   {instrument}\n"
            f"Reason: {news_reason}\n"
            f"⏭  Skipping this scan"
        )

    def send_login_fail(self, api_key_hint, account_id):
        self.send(
            f"❌ <b>LOGIN FAILED</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Key:     {api_key_hint}\n"
            f"Account: {account_id or 'MISSING'}\n"
            f"⚠️ Check Railway env vars"
        )

    def send_daily_summary(self, balance_sgd, start_balance_sgd, trades, wins, losses, pnl_sgd):
        pnl_emoji = "✅" if pnl_sgd >= 0 else "🔴"
        pnl_sign  = "+" if pnl_sgd >= 0 else ""
        win_rate  = f"{round(wins/(wins+losses)*100)}%" if (wins+losses) > 0 else "—"
        self.send(
            f"📅 <b>Daily Summary</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance:   SGD {balance_sgd:,.2f}\n"
            f"📈 Day P&L:   {pnl_emoji} SGD {pnl_sign}{pnl_sgd:,.2f}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 Trades:    {trades}\n"
            f"🏆 W/L:       {wins}W / {losses}L  ({win_rate})\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔄 Starting new day..."
        )
