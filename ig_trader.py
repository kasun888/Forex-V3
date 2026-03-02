"""
💱 IG Markets Trade Executor
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Direct REST API calls to IG Markets
Demo URL: https://demo-api.ig.com/gateway/deal
Live URL: https://api.ig.com/gateway/deal
"""

import os
import requests
import logging
import json

log = logging.getLogger(__name__)

class IGTrader:
    def __init__(self, demo=True):
        self.username   = os.environ.get("IG_USERNAME", "")
        self.password   = os.environ.get("IG_PASSWORD", "")
        self.api_key    = os.environ.get("IG_API_KEY", "")
        self.acc_number = os.environ.get("IG_ACC_NUMBER", "")
        self.demo       = demo
        self.base_url   = "https://demo-api.ig.com/gateway/deal" if demo else "https://api.ig.com/gateway/deal"
        self.cst        = None
        self.x_st       = None

        log.info(f"IG Trader | Mode: {'DEMO' if demo else 'LIVE'}")
        log.info(f"Username: {self.username[:4]}**** | Key: {self.api_key[:4]}****")

    # ─── Login ───────────────────────────────────────────────────────────────
    def login(self):
        try:
            url = f"{self.base_url}/session"
            headers = {
                "X-IG-API-KEY": self.api_key,
                "Content-Type": "application/json; charset=UTF-8",
                "Accept":       "application/json; charset=UTF-8",
                "Version":      "2"
            }
            payload = {
                "identifier":        self.username,
                "password":          self.password,
                "encryptedPassword": False
            }
            log.info(f"Logging in to IG... URL: {url}")
            r = requests.post(url, headers=headers, json=payload, timeout=15)
            log.info(f"Login response: {r.status_code}")

            if r.status_code == 200:
                self.cst  = r.headers.get("CST")
                self.x_st = r.headers.get("X-SECURITY-TOKEN")
                log.info("✅ IG Login successful!")
                return True
            else:
                log.error(f"❌ IG Login failed! Status: {r.status_code}")
                log.error(f"Response: {r.text}")
                return False
        except Exception as e:
            log.error(f"❌ Login exception: {e}")
            return False

    # ─── Headers ─────────────────────────────────────────────────────────────
    def _headers(self, version="1"):
        return {
            "X-IG-API-KEY":     self.api_key,
            "CST":              self.cst,
            "X-SECURITY-TOKEN": self.x_st,
            "Content-Type":     "application/json",
            "Accept":           "application/json",
            "Version":          version
        }

    # ─── Get Price ───────────────────────────────────────────────────────────
    def get_price(self, epic):
        try:
            r    = requests.get(f"{self.base_url}/markets/{epic}", headers=self._headers(), timeout=10)
            data = r.json()
            bid  = float(data["snapshot"]["bid"])
            ask  = float(data["snapshot"]["offer"])
            mid  = (bid + ask) / 2
            log.info(f"{epic}: {mid:.5f}")
            return mid, bid, ask
        except Exception as e:
            log.error(f"get_price error: {e}")
            return None, None, None

    # ─── Get Balance ─────────────────────────────────────────────────────────
    def get_balance(self):
        try:
            r    = requests.get(f"{self.base_url}/accounts", headers=self._headers(), timeout=10)
            data = r.json()
            for acc in data.get("accounts", []):
                if acc["accountId"] == self.acc_number:
                    bal = float(acc["balance"]["available"])
                    log.info(f"Balance: ${bal:,.2f}")
                    return bal
            # Return first account balance as fallback
            if data.get("accounts"):
                return float(data["accounts"][0]["balance"]["available"])
            return 10000
        except Exception as e:
            log.error(f"get_balance error: {e}")
            return 10000

    # ─── Get Position ────────────────────────────────────────────────────────
    def get_position(self, epic):
        try:
            r    = requests.get(f"{self.base_url}/positions", headers=self._headers("2"), timeout=10)
            data = r.json()
            for pos in data.get("positions", []):
                if pos["market"]["epic"] == epic:
                    return pos
            return None
        except Exception as e:
            log.error(f"get_position error: {e}")
            return None

    # ─── Check PnL ───────────────────────────────────────────────────────────
    def check_pnl(self, position):
        try:
            return float(position["position"].get("upl", 0))
        except:
            return 0

    # ─── Place Order ─────────────────────────────────────────────────────────
    def place_order(self, epic, direction, size, stop_distance, limit_distance, currency="USD"):
        try:
            payload = {
                "epic":           epic,
                "expiry":         "-",
                "direction":      direction,
                "size":           str(size),
                "orderType":      "MARKET",
                "timeInForce":    "FILL_OR_KILL",
                "guaranteedStop": False,
                "stopDistance":   str(stop_distance),
                "limitDistance":  str(limit_distance),
                "currencyCode":   currency,
                "forceOpen":      True
            }
            r    = requests.post(f"{self.base_url}/positions/otc", headers=self._headers("2"), json=payload, timeout=15)
            data = r.json()
            log.info(f"Order result: {data}")
            if data.get("dealStatus") == "ACCEPTED":
                return {"success": True,  "dealRef": data.get("dealReference")}
            else:
                return {"success": False, "error": data.get("reason", "Unknown")}
        except Exception as e:
            log.error(f"place_order error: {e}")
            return {"success": False, "error": str(e)}

    # ─── Close Position ───────────────────────────────────────────────────────
    def close_position(self, position):
        try:
            deal_id   = position["position"]["dealId"]
            direction = "SELL" if position["position"]["direction"] == "BUY" else "BUY"
            size      = abs(float(position["position"]["size"]))
            epic      = position["market"]["epic"]
            payload   = {
                "dealId":      deal_id,
                "epic":        epic,
                "direction":   direction,
                "size":        str(size),
                "orderType":   "MARKET",
                "timeInForce": "FILL_OR_KILL",
                "expiry":      "-"
            }
            headers          = self._headers("1")
            headers["_method"] = "DELETE"
            r    = requests.post(f"{self.base_url}/positions/otc", headers=headers, json=payload, timeout=15)
            data = r.json()
            return {"success": data.get("dealStatus") == "ACCEPTED"}
        except Exception as e:
            log.error(f"close_position error: {e}")
            return {"success": False, "error": str(e)}

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
            for _, acc in accounts.iterrows():
                if acc["accountId"] == self.acc_number:
                    bal = float(acc["balance"])
                    log.info(f"Balance: ${bal:,.2f}")
                    return bal
            # Fallback - return first account balance
            if len(accounts) > 0:
                return float(accounts.iloc[0]["balance"])
            return 10000
        except Exception as e:
            log.error(f"get_balance error: {e}")
            return 10000

    # ─── Get Open Position ───────────────────────────────────────────────────
    def get_position(self, epic):
        try:
            positions = self.ig.fetch_open_positions()
            if positions is None or len(positions) == 0:
                return None
            for _, pos in positions.iterrows():
                if pos.get("epic") == epic:
                    log.info(f"Found open position for {epic}")
                    return pos
            return None
        except Exception as e:
            log.error(f"get_position error: {e}")
            return None

    # ─── Get PnL ────────────────────────────────────────────────────────────
    def check_pnl(self, position):
        try:
            return float(position.get("upl", 0))
        except:
            return 0

    # ─── Place Order ────────────────────────────────────────────────────────
    def place_order(self, epic, direction, size, stop_distance, limit_distance, currency="USD"):
        try:
            result = self.ig.create_open_position(
                currency_code           = currency,
                direction               = direction,
                epic                    = epic,
                expiry                  = "-",
                force_open              = True,
                guaranteed_stop         = False,
                level                   = None,
                limit_distance          = limit_distance,
                limit_level             = None,
                order_type              = "MARKET",
                quote_id                = None,
                size                    = size,
                stop_distance           = stop_distance,
                stop_level              = None,
                time_in_force           = "FILL_OR_KILL",
                trailing_stop           = False,
                trailing_stop_increment = None
            )
            log.info(f"Order result: {result}")
            if result.get("dealStatus") == "ACCEPTED":
                return {"success": True,  "dealRef": result.get("dealReference")}
            else:
                return {"success": False, "error": result.get("reason", "Rejected")}
        except Exception as e:
            log.error(f"place_order error: {e}")
            return {"success": False, "error": str(e)}

    # ─── Close Position ──────────────────────────────────────────────────────
    def close_position(self, position):
        try:
            deal_id   = position.get("dealId")
            direction = "SELL" if position.get("direction") == "BUY" else "BUY"
            size      = abs(float(position.get("size", 1)))
            epic      = position.get("epic")

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
