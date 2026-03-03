"""
💱 Deriv Trade Executor
Uses WebSocket API
Supports: EUR/USD, GBP/USD, Gold (XAU/USD)
"""

import os
import json
import asyncio
import websockets
import logging

log = logging.getLogger(__name__)

DERIV_WS = "wss://ws.derivws.com/websockets/v3?app_id=1089"

# Symbol map
SYMBOLS = {
    "EURUSD": "frxEURUSD",
    "GBPUSD": "frxGBPUSD",
    "XAUUSD": "frxXAUUSD"
}

class DerivTrader:
    def __init__(self):
        self.token   = os.environ.get("DERIV_TOKEN", "")
        self.account = None
        self.balance = 0
        log.info(f"Deriv Trader | Token: {self.token[:6]}****")

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    # ── Login / Authorize ─────────────────────────────────────────────────────
    async def _authorize(self, ws):
        await ws.send(json.dumps({"authorize": self.token}))
        resp = json.loads(await ws.recv())
        if "error" in resp:
            log.error(f"Auth failed: {resp['error']['message']}")
            return False
        self.account = resp["authorize"]["loginid"]
        self.balance = float(resp["authorize"]["balance"])
        log.info(f"Authorized! Account: {self.account} Balance: {self.balance}")
        return True

    def login(self):
        try:
            async def _do():
                async with websockets.connect(DERIV_WS) as ws:
                    return await self._authorize(ws)
            result = self._run(_do())
            if result:
                log.info("Deriv login successful!")
            return result
        except Exception as e:
            log.error(f"Login error: {e}")
            return False

    # ── Get Price ─────────────────────────────────────────────────────────────
    def get_price(self, asset):
        try:
            symbol = SYMBOLS.get(asset, "frxEURUSD")
            async def _do():
                async with websockets.connect(DERIV_WS) as ws:
                    await self._authorize(ws)
                    await ws.send(json.dumps({"ticks": symbol}))
                    resp = json.loads(await ws.recv())
                    if "tick" in resp:
                        price = float(resp["tick"]["quote"])
                        log.info(f"{asset} price: {price}")
                        return price, price, price
                    return None, None, None
            return self._run(_do())
        except Exception as e:
            log.error(f"get_price error: {e}")
            return None, None, None

    # ── Get Balance ───────────────────────────────────────────────────────────
    def get_balance(self):
        try:
            async def _do():
                async with websockets.connect(DERIV_WS) as ws:
                    await self._authorize(ws)
                    await ws.send(json.dumps({"balance": 1, "subscribe": 0}))
                    resp = json.loads(await ws.recv())
                    if "balance" in resp:
                        bal = float(resp["balance"]["balance"])
                        log.info(f"Balance: {bal}")
                        return bal
                    return self.balance
            return self._run(_do())
        except Exception as e:
            log.error(f"get_balance error: {e}")
            return self.balance

    # ── Get Open Position ─────────────────────────────────────────────────────
    def get_position(self, asset):
        try:
            symbol = SYMBOLS.get(asset, "frxEURUSD")
            async def _do():
                async with websockets.connect(DERIV_WS) as ws:
                    await self._authorize(ws)
                    await ws.send(json.dumps({"portfolio": 1}))
                    resp = json.loads(await ws.recv())
                    for contract in resp.get("portfolio", {}).get("contracts", []):
                        if contract.get("symbol") == symbol:
                            return contract
                    return None
            return self._run(_do())
        except Exception as e:
            log.error(f"get_position error: {e}")
            return None

    # ── Check PnL ─────────────────────────────────────────────────────────────
    def check_pnl(self, position):
        try:
            return float(position.get("profit", 0))
        except:
            return 0

    # ── Place Order ───────────────────────────────────────────────────────────
    def place_order(self, asset, direction, size, stop_distance, limit_distance, currency="USD"):
        try:
            symbol        = SYMBOLS.get(asset, "frxEURUSD")
            contract_type = "CALL" if direction == "BUY" else "PUT"

            async def _do():
                async with websockets.connect(DERIV_WS) as ws:
                    await self._authorize(ws)

                    # Get proposal first
                    await ws.send(json.dumps({
                        "proposal":       1,
                        "amount":         size,
                        "basis":          "stake",
                        "contract_type":  contract_type,
                        "currency":       currency,
                        "duration":       5,
                        "duration_unit":  "m",
                        "symbol":         symbol
                    }))

                    proposal = json.loads(await ws.recv())
                    if "error" in proposal:
                        log.error(f"Proposal error: {proposal['error']['message']}")
                        return {"success": False, "error": proposal["error"]["message"]}

                    proposal_id = proposal["proposal"]["id"]
                    log.info(f"Proposal: {proposal_id}")

                    # Buy contract
                    await ws.send(json.dumps({
                        "buy":   proposal_id,
                        "price": size
                    }))

                    buy_resp = json.loads(await ws.recv())
                    if "error" in buy_resp:
                        log.error(f"Buy error: {buy_resp['error']['message']}")
                        return {"success": False, "error": buy_resp["error"]["message"]}

                    contract_id = buy_resp["buy"]["contract_id"]
                    log.info(f"Contract placed! ID: {contract_id}")
                    return {"success": True, "contract_id": contract_id}

            return self._run(_do())
        except Exception as e:
            log.error(f"place_order error: {e}")
            return {"success": False, "error": str(e)}

    # ── Close Position ────────────────────────────────────────────────────────
    def close_position(self, position):
        try:
            contract_id = position.get("contract_id")
            async def _do():
                async with websockets.connect(DERIV_WS) as ws:
                    await self._authorize(ws)
                    await ws.send(json.dumps({"sell": contract_id, "price": 0}))
                    resp = json.loads(await ws.recv())
                    if "error" in resp:
                        return {"success": False, "error": resp["error"]["message"]}
                    return {"success": True}
            return self._run(_do())
        except Exception as e:
            log.error(f"close_position error: {e}")
            return {"success": False, "error": str(e)}
