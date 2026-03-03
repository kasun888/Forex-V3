"""
🔄 Auto-Tuner — Self Learning Engine
Runs every Sunday 2am SGT
"""
import json
import logging
import glob
from datetime import datetime
import pytz

log = logging.getLogger(__name__)

class AutoTuner:
    def __init__(self, settings):
        self.settings = settings
        self.sg_tz    = pytz.timezone("Asia/Singapore")

    def run_weekly_tune(self):
        log.info("🔄 Weekly auto-tune starting...")
        trade_files = glob.glob("trades_*.json")
        all_trades  = []
        for f in trade_files:
            try:
                with open(f) as fp:
                    all_trades.append(json.load(fp))
            except:
                pass

        if not all_trades:
            log.info("No trade data yet.")
            return

        total_pnl    = sum(t.get("daily_pnl", 0) for t in all_trades)
        total_trades = sum(t.get("trades", 0)    for t in all_trades)
        winning_days = sum(1 for t in all_trades if t.get("daily_pnl", 0) > 0)
        total_days   = len(all_trades)
        win_rate     = (winning_days / total_days * 100) if total_days > 0 else 0

        log.info(f"📊 PnL: ${total_pnl:.2f} | Trades: {total_trades} | Win: {win_rate:.0f}%")

        new = self.settings.copy()

        if win_rate < 40:
            new["signal_threshold"] = min(5, self.settings["signal_threshold"] + 1)
            log.info(f"⬆️ Raising threshold to {new['signal_threshold']}")
        elif win_rate > 65:
            new["signal_threshold"] = max(3, self.settings["signal_threshold"] - 1)
            log.info(f"⬇️ Lowering threshold to {new['signal_threshold']}")

        with open("settings.json", "w") as f:
            json.dump(new, f, indent=2)

        log.info(f"✅ Settings updated!")
        return new

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        with open("settings.json") as f:
            settings = json.load(f)
    except:
        settings = {}
    AutoTuner(settings).run_weekly_tune()
