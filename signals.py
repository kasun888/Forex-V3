"""
🧠 5-Layer Signal Intelligence Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Supports: EUR/USD + GBP/USD + XAU/USD (Gold)

Layer 1: Sentiment (Fear & Greed, Gold demand)
Layer 2: Macro (DXY, Fed, CPI, Interest rates)
Layer 3: Cross-Market (S&P500, VIX, Oil)
Layer 4: Fundamentals (COT report, Central banks)
Layer 5: Technical (RSI, MACD, BB, Stochastic, ATR)
"""

import requests
import logging
import math
from datetime import datetime
import pytz

log = logging.getLogger(__name__)

class SignalEngine:
    def __init__(self):
        self.sg_tz = pytz.timezone("Asia/Singapore")
        self.asset = "EURUSD"

    # ─── MASTER ANALYSIS ────────────────────────────────────────────────────
    def analyze(self, asset="EURUSD"):
        self.asset = asset
        log.info(f"\n{'='*40}")
        log.info(f"🔍 Analyzing {asset}...")

        results = {}
        results["sentiment"]   = self._layer1_sentiment()
        results["macro"]       = self._layer2_macro()
        results["crossmarket"] = self._layer3_crossmarket()
        results["fundamental"] = self._layer4_fundamental()
        results["technical"]   = self._layer5_technical()

        bull = sum(1 for v in results.values() if v["signal"] == "BULL")
        bear = sum(1 for v in results.values() if v["signal"] == "BEAR")

        score     = max(bull, bear)
        direction = "BUY" if bull > bear else ("SELL" if bear > bull else "NONE")

        if bull == bear:
            direction = "NONE"
            score     = 0

        details = "\n".join([
            f"  L{i+1} {k}: {v['signal']} → {v['reason']}"
            for i, (k, v) in enumerate(results.items())
        ])

        log.info(f"{asset} | Bull:{bull} Bear:{bear} → {direction} ({score}/5)")
        return score, direction, details

    # ─── LAYER 1: SENTIMENT ──────────────────────────────────────────────────
    def _layer1_sentiment(self):
        try:
            if self.asset == "XAUUSD":
                # Gold loves fear! Check VIX
                r = requests.get(
                    "https://query1.finance.yahoo.com/v8/finance/chart/^VIX?interval=1d&range=5d",
                    timeout=10, headers={"User-Agent": "Mozilla/5.0"}
                )
                closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                if closes:
                    vix = closes[-1]
                    log.info(f"VIX: {vix:.1f}")
                    if vix > 20:
                        return {"signal": "BULL", "reason": f"VIX={vix:.0f} → fear rising → Gold bullish 🥇"}
                    elif vix < 15:
                        return {"signal": "BEAR", "reason": f"VIX={vix:.0f} → calm market → Gold weak"}
                return {"signal": "NEUTRAL", "reason": "VIX neutral"}

            else:
                # Forex: check USD sentiment via Dollar Index
                r = requests.get(
                    "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1d&range=5d",
                    timeout=10, headers={"User-Agent": "Mozilla/5.0"}
                )
                closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                if len(closes) >= 2:
                    dxy = closes[-1]
                    dxy_chg = ((closes[-1] - closes[-2]) / closes[-2]) * 100
                    log.info(f"DXY: {dxy:.2f} ({dxy_chg:+.2f}%)")

                    # EUR/USD and GBP/USD are INVERSE to DXY
                    if dxy_chg < -0.2:
                        return {"signal": "BULL", "reason": f"USD weakening {dxy_chg:.2f}% → {self.asset} bullish"}
                    elif dxy_chg > 0.2:
                        return {"signal": "BEAR", "reason": f"USD strengthening {dxy_chg:.2f}% → {self.asset} bearish"}
                return {"signal": "NEUTRAL", "reason": "USD sentiment neutral"}
        except Exception as e:
            log.warning(f"Layer 1 error: {e}")
            return {"signal": "NEUTRAL", "reason": "Sentiment unavailable"}

    # ─── LAYER 2: MACRO ──────────────────────────────────────────────────────
    def _layer2_macro(self):
        try:
            now = datetime.now(self.sg_tz)

            # Check US 10Y Treasury yield (affects forex + gold)
            r = requests.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/^TNX?interval=1d&range=5d",
                timeout=10, headers={"User-Agent": "Mozilla/5.0"}
            )
            closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]

            if len(closes) >= 2:
                yield_chg = closes[-1] - closes[-2]
                log.info(f"US 10Y yield change: {yield_chg:+.3f}%")

                if self.asset == "XAUUSD":
                    # Rising yields = bad for Gold (no yield)
                    if yield_chg > 0.05:
                        return {"signal": "BEAR", "reason": f"Bond yields rising {yield_chg:+.3f}% → Gold headwind"}
                    elif yield_chg < -0.05:
                        return {"signal": "BULL", "reason": f"Bond yields falling {yield_chg:+.3f}% → Gold bullish"}
                else:
                    # Rising US yields = USD stronger = EUR/GBP weaker
                    if yield_chg > 0.05:
                        return {"signal": "BEAR", "reason": f"US yields rising → USD stronger → {self.asset} bearish"}
                    elif yield_chg < -0.05:
                        return {"signal": "BULL", "reason": f"US yields falling → USD weaker → {self.asset} bullish"}

            # High risk day check
            if now.weekday() == 4:  # Friday
                return {"signal": "BEAR", "reason": "Friday → position closing → caution"}

            return {"signal": "NEUTRAL", "reason": "Macro conditions neutral"}
        except Exception as e:
            log.warning(f"Layer 2 error: {e}")
            return {"signal": "NEUTRAL", "reason": "Macro data unavailable"}

    # ─── LAYER 3: CROSS-MARKET ───────────────────────────────────────────────
    def _layer3_crossmarket(self):
        try:
            signals = {}

            for ticker, name in [("^GSPC", "SP500"), ("GC=F", "Gold"), ("CL=F", "Oil")]:
                try:
                    r = requests.get(
                        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d",
                        timeout=10, headers={"User-Agent": "Mozilla/5.0"}
                    )
                    closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                    if len(closes) >= 2:
                        chg = ((closes[-1] - closes[-2]) / closes[-2]) * 100
                        signals[name] = chg
                        log.info(f"{name}: {chg:+.2f}%")
                except:
                    pass

            if self.asset == "XAUUSD":
                sp500 = signals.get("SP500", 0)
                oil   = signals.get("Oil", 0)
                if sp500 < -0.5:
                    return {"signal": "BULL", "reason": f"SP500 down {sp500:.1f}% → safe haven → Gold up"}
                elif oil > 1.0:
                    return {"signal": "BULL", "reason": f"Oil up {oil:.1f}% → inflation → Gold up"}
                elif sp500 > 1.0:
                    return {"signal": "BEAR", "reason": f"Risk-on SP500 +{sp500:.1f}% → Gold weak"}

            elif self.asset in ["EURUSD", "GBPUSD"]:
                sp500 = signals.get("SP500", 0)
                if sp500 > 0.5:
                    return {"signal": "BULL", "reason": f"Risk-on SP500 +{sp500:.1f}% → EUR/GBP stronger"}
                elif sp500 < -0.5:
                    return {"signal": "BEAR", "reason": f"Risk-off SP500 {sp500:.1f}% → USD stronger"}

            return {"signal": "NEUTRAL", "reason": "Cross-market neutral"}
        except Exception as e:
            log.warning(f"Layer 3 error: {e}")
            return {"signal": "NEUTRAL", "reason": "Cross-market unavailable"}

    # ─── LAYER 4: FUNDAMENTALS ───────────────────────────────────────────────
    def _layer4_fundamental(self):
        try:
            now = datetime.now(self.sg_tz)

            if self.asset == "XAUUSD":
                # Gold: check inflation expectations (TIPS ETF)
                r = requests.get(
                    "https://query1.finance.yahoo.com/v8/finance/chart/TIP?interval=1d&range=5d",
                    timeout=10, headers={"User-Agent": "Mozilla/5.0"}
                )
                closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                if len(closes) >= 2:
                    tip_chg = ((closes[-1] - closes[-2]) / closes[-2]) * 100
                    log.info(f"TIPS ETF: {tip_chg:+.2f}%")
                    if tip_chg > 0.1:
                        return {"signal": "BULL", "reason": f"Inflation expectations rising → Gold bullish"}
                    elif tip_chg < -0.1:
                        return {"signal": "BEAR", "reason": f"Real yields rising → Gold headwind"}

            elif self.asset == "EURUSD":
                # EUR: check EU vs US yield differential
                r = requests.get(
                    "https://query1.finance.yahoo.com/v8/finance/chart/FXE?interval=1d&range=5d",
                    timeout=10, headers={"User-Agent": "Mozilla/5.0"}
                )
                closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                if len(closes) >= 2:
                    fxe_chg = ((closes[-1] - closes[-2]) / closes[-2]) * 100
                    log.info(f"EUR ETF: {fxe_chg:+.2f}%")
                    if fxe_chg > 0.1:
                        return {"signal": "BULL", "reason": f"EUR ETF momentum positive → EURUSD bullish"}
                    elif fxe_chg < -0.1:
                        return {"signal": "BEAR", "reason": f"EUR ETF momentum negative → EURUSD bearish"}

            elif self.asset == "GBPUSD":
                # GBP: check UK ETF / GBP momentum
                r = requests.get(
                    "https://query1.finance.yahoo.com/v8/finance/chart/FXB?interval=1d&range=5d",
                    timeout=10, headers={"User-Agent": "Mozilla/5.0"}
                )
                closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                if len(closes) >= 2:
                    fxb_chg = ((closes[-1] - closes[-2]) / closes[-2]) * 100
                    log.info(f"GBP ETF: {fxb_chg:+.2f}%")
                    if fxb_chg > 0.1:
                        return {"signal": "BULL", "reason": f"GBP ETF positive → GBPUSD bullish"}
                    elif fxb_chg < -0.1:
                        return {"signal": "BEAR", "reason": f"GBP ETF negative → GBPUSD bearish"}

            return {"signal": "NEUTRAL", "reason": "Fundamentals neutral"}
        except Exception as e:
            log.warning(f"Layer 4 error: {e}")
            return {"signal": "NEUTRAL", "reason": "Fundamental data unavailable"}

    # ─── LAYER 5: TECHNICAL ──────────────────────────────────────────────────
    def _layer5_technical(self):
        try:
            # Get price data from Yahoo Finance
            ticker_map = {
                "EURUSD": "EURUSD=X",
                "GBPUSD": "GBPUSD=X",
                "XAUUSD": "GC=F"
            }
            ticker = ticker_map.get(self.asset, "EURUSD=X")

            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=15m&range=5d",
                timeout=10, headers={"User-Agent": "Mozilla/5.0"}
            )
            result = r.json()["chart"]["result"][0]
            quotes = result["indicators"]["quote"][0]

            closes = [c for c in quotes["close"] if c]
            highs  = [c for c in quotes["high"]  if c]
            lows   = [c for c in quotes["low"]   if c]
            vols   = [c for c in quotes.get("volume", [1]*200) if c]

            if len(closes) < 30:
                return {"signal": "NEUTRAL", "reason": "Not enough data"}

            bull_signals = 0
            bear_signals = 0
            reasons      = []

            # ── RSI (14) ─────────────────────────────────────────────────────
            rsi = self._calc_rsi(closes, 14)
            log.info(f"RSI: {rsi:.1f}")
            if rsi < 30:
                bull_signals += 2
                reasons.append(f"RSI oversold {rsi:.0f} 🟢🟢")
            elif rsi < 45:
                bull_signals += 1
                reasons.append(f"RSI low {rsi:.0f} 🟢")
            elif rsi > 70:
                bear_signals += 2
                reasons.append(f"RSI overbought {rsi:.0f} 🔴🔴")
            elif rsi > 55:
                bear_signals += 1
                reasons.append(f"RSI high {rsi:.0f} 🔴")

            # ── MACD (12,26,9) ────────────────────────────────────────────────
            ema12      = self._ema(closes, 12)
            ema26      = self._ema(closes, 26)
            macd_line  = [e12 - e26 for e12, e26 in zip(ema12[-len(ema26):], ema26)]
            signal_ema = self._ema(macd_line, 9)
            macd_hist  = macd_line[-1] - signal_ema[-1]
            macd_prev  = macd_line[-2] - signal_ema[-2]
            log.info(f"MACD hist: {macd_hist:.6f}")
            if macd_hist > 0 and macd_prev <= 0:
                bull_signals += 2
                reasons.append("MACD bullish cross 🟢🟢")
            elif macd_hist < 0 and macd_prev >= 0:
                bear_signals += 2
                reasons.append("MACD bearish cross 🔴🔴")
            elif macd_hist > 0:
                bull_signals += 1
                reasons.append("MACD positive 🟢")
            else:
                bear_signals += 1
                reasons.append("MACD negative 🔴")

            # ── Bollinger Bands (20,2) ────────────────────────────────────────
            bb_period = 20
            bb_mid    = sum(closes[-bb_period:]) / bb_period
            bb_std    = math.sqrt(sum((c - bb_mid)**2 for c in closes[-bb_period:]) / bb_period)
            bb_upper  = bb_mid + 2 * bb_std
            bb_lower  = bb_mid - 2 * bb_std
            bb_pct    = (closes[-1] - bb_lower) / (bb_upper - bb_lower) * 100
            log.info(f"BB %B: {bb_pct:.1f}%")
            if bb_pct < 10:
                bull_signals += 2
                reasons.append(f"BB oversold %B={bb_pct:.0f}% 🟢🟢")
            elif bb_pct > 90:
                bear_signals += 2
                reasons.append(f"BB overbought %B={bb_pct:.0f}% 🔴🔴")
            elif bb_pct < 30:
                bull_signals += 1
                reasons.append(f"Near BB lower 🟢")
            elif bb_pct > 70:
                bear_signals += 1
                reasons.append(f"Near BB upper 🔴")

            # ── Stochastic (14,3) ─────────────────────────────────────────────
            stoch = self._calc_stochastic(closes, highs, lows, 14)
            log.info(f"Stochastic: {stoch:.1f}")
            if stoch < 20:
                bull_signals += 1
                reasons.append(f"Stoch oversold {stoch:.0f} 🟢")
            elif stoch > 80:
                bear_signals += 1
                reasons.append(f"Stoch overbought {stoch:.0f} 🔴")

            # ── MA50 Trend ────────────────────────────────────────────────────
            if len(closes) >= 50:
                ma50 = sum(closes[-50:]) / 50
                if closes[-1] > ma50:
                    bull_signals += 1
                    reasons.append("Above MA50 🟢")
                else:
                    bear_signals += 1
                    reasons.append("Below MA50 🔴")

            # ── Final Decision ────────────────────────────────────────────────
            reason_str = " | ".join(reasons)
            log.info(f"Technical: Bull={bull_signals} Bear={bear_signals}")
            if bull_signals > bear_signals:
                return {"signal": "BULL", "reason": reason_str}
            elif bear_signals > bull_signals:
                return {"signal": "BEAR", "reason": reason_str}
            return {"signal": "NEUTRAL", "reason": reason_str}

        except Exception as e:
            log.warning(f"Layer 5 error: {e}")
            return {"signal": "NEUTRAL", "reason": f"Technical error: {e}"}

    # ─── HELPERS ─────────────────────────────────────────────────────────────
    def _calc_rsi(self, closes, period=14):
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i-1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        if len(gains) < period:
            return 50
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100
        return 100 - (100 / (1 + avg_gain / avg_loss))

    def _ema(self, data, period):
        if len(data) < period:
            return [sum(data) / len(data)] * len(data)
        emas = [sum(data[:period]) / period]
        mult = 2 / (period + 1)
        for price in data[period:]:
            emas.append((price - emas[-1]) * mult + emas[-1])
        return emas

    def _calc_stochastic(self, closes, highs, lows, period=14):
        if len(closes) < period:
            return 50
        highest = max(highs[-period:])
        lowest  = min(lows[-period:])
        if highest == lowest:
            return 50
        return ((closes[-1] - lowest) / (highest - lowest)) * 100
