"""
💱 IG Markets Trade Executor
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Uses official trading-ig Python library
Much more reliable than raw API calls!

acc_type="DEMO" → Demo Trading
acc_type="LIVE" → Live Trading
"""

import os
import logging

log = logging.getLogger(__name__)

class IGTrader:
    def __init__(self, demo=True):
        self.username   = os.environ.get("IG_USERNAME", "")
        self.password   = os.environ.get("IG_PASSWORD", "")
        self.api_key    = os.environ.get("IG_API_KEY", "")
        self.acc_number = os.environ.get("IG_ACC_NUMBER", "")
        self.acc_type   = "DEMO" if demo else "LIVE"
        self.demo       = demo
        self.ig         = None
        log.info(f"IG Trader init | Mode: {self.acc_type}")

    # ─── Login ───────────────────────────────────────────────────────────────
    def login(self):
        try:
            from trading_ig import IGService

            self.ig = IGService(
                username   = self.username,
                password   = self.password,
                api_key    = self.api_key,
                acc_type   = self.acc_type,
                acc_number = self.acc_number
            )
            self.ig.create_session()
            log.info("✅ IG Login successful!")
            return True
        except Exception as e:
            log.error(f"❌ IG Login failed: {e}")
            return False

    # ─── Get Price ───────────────────────────────────────────────────────────
    def get_price(self, epic):
        try:
            market = self.ig.fetch_market_by_epic(epic)
            bid    = float(market["snapshot"]["bid"])
            ask    = float(market["snapshot"]["offer"])
            mid    = (bid + ask) / 2
            log.info(f"{epic}: bid={bid} ask={ask} mid={mid:.5f}")
            return mid, bid, ask
        except Exception as e:
            log.error(f"get_price error: {e}")
            return None, None, None

    # ─── Get Balance ────────────────────────────────────────────────────────
    def get_balance(self):
        try:
            accounts = self.ig.fetch_accounts()
            for acc in accounts["accounts"]:
                if acc["accountId"] == self.acc_number:
                    bal = float(acc["balance"]["available"])
                    log.info(f"Balance: ${bal:,.2f}")
                    return bal
            return 0
        except Exception as e:
            log.error(f"get_balance error: {e}")
            return 0

    # ─── Get Open Position ───────────────────────────────────────────────────
    def get_position(self, epic):
        try:
            positions = self.ig.fetch_open_positions()
            for pos in positions.get("positions", []):
                if pos["market"]["epic"] == epic:
                    log.info(f"Found open position for {epic}")
                    return pos
            return None
        except Exception as e:
            log.error(f"get_position error: {e}")
            return None

    # ─── Get PnL ────────────────────────────────────────────────────────────
    def check_pnl(self, position):
        try:
            return float(position["position"].get("upl", 0))
        except:
            return 0

    # ─── Place Order ────────────────────────────────────────────────────────
    def place_order(self, epic, direction, size, stop_distance, limit_distance, currency="USD"):
        try:
            result = self.ig.create_open_position(
                currency_code    = currency,
                direction        = direction,      # "BUY" or "SELL"
                epic             = epic,
                expiry           = "-",
                force_open       = True,
                guaranteed_stop  = False,
                level            = None,
                limit_distance   = limit_distance,
                limit_level      = None,
                order_type       = "MARKET",
                quote_id         = None,
                size             = size,
                stop_distance    = stop_distance,
                stop_level       = None,
                time_in_force    = "FILL_OR_KILL",
                trailing_stop    = False,
                trailing_stop_increment = None
            )
            log.info(f"Order result: {result}")
            if result.get("dealStatus") == "ACCEPTED":
                return {"success": True, "dealRef": result.get("dealReference")}
            else:
                return {"success": False, "error": result.get("reason", "Rejected")}
        except Exception as e:
            log.error(f"place_order error: {e}")
            return {"success": False, "error": str(e)}

    # ─── Close Position ──────────────────────────────────────────────────────
    def close_position(self, position):
        try:
            deal_id   = position["position"]["dealId"]
            direction = "SELL" if position["position"]["direction"] == "BUY" else "BUY"
            size      = abs(float(position["position"]["size"]))
            epic      = position["market"]["epic"]

            result = self.ig.close_open_position(
                deal_id    = deal_id,
                direction  = direction,
                epic       = epic,
                expiry     = "-",
                level      = None,
                order_type = "MARKET",
                quote_id   = None,
                size       = size
            )
            log.info(f"Close result: {result}")
            return {"success": result.get("dealStatus") == "ACCEPTED"}
        except Exception as e:
            log.error(f"close_position error: {e}")
            return {"success": False, "error": str(e)}

