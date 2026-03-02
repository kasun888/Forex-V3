"""
🧠 5-Layer Signal Intelligence Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Supports: BTC/USDT + GOLD (XAU/USDT)

Layer 1: Fear & Greed + Gold Sentiment
Layer 2: Macro Events (Fed, DXY, CPI)
Layer 3: Cross-Market (S&P500, Gold, Asia)
Layer 4: On-Chain Whale Data (BTC) / Central Bank (Gold)
Layer 5: Technical (RSI, MACD, Bollinger Bands, Stochastic, ATR)
"""

import requests
import logging
from datetime import datetime
import pytz
import math

log = logging.getLogger(__name__)

class SignalEngine:
    def __init__(self, asset="BTC"):
        self.sg_tz = pytz.timezone("Asia/Singapore")
        self.asset = asset  # "BTC" or "GOLD"

    # ─── MASTER ANALYSIS ────────────────────────────────────────────────────
    def analyze(self, asset="BTC"):
        self.asset = asset
        log.info(f"🔍 Analyzing {asset}...")

        results = {}
        results["sentiment"]   = self._layer1_sentiment()
        results["macro"]       = self._layer2_macro()
        results["crossmarket"] = self._layer3_crossmarket()
        results["onchain"]     = self._layer4_onchain()
        results["technical"]   = self._layer5_technical()

        bull = sum(1 for v in results.values() if v["signal"] == "BULL")
        bear = sum(1 for v in results.values() if v["signal"] == "BEAR")

        score     = max(bull, bear)
        direction = "LONG" if bull > bear else ("SHORT" if bear > bull else "NONE")

        if bull == bear:
            direction = "NONE"
            score     = 0

        details = "\n".join([
            f"  Layer {i+1} ({k}): {v['signal']} → {v['reason']}"
            for i, (k, v) in enumerate(results.items())
        ])
        log.info(f"{asset} | Bull:{bull} Bear:{bear} → {direction} ({score}/5)")
        return score, direction, details

    # ─── LAYER 1: SENTIMENT ──────────────────────────────────────────────────
    def _layer1_sentiment(self):
        try:
            if self.asset == "BTC":
                # Crypto Fear & Greed
                r   = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
                val = int(r.json()["data"][0]["value"])
                name = r.json()["data"][0]["value_classification"]
                log.info(f"Fear & Greed: {val} ({name})")
                if val >= 65:
                    return {"signal": "BULL", "reason": f"Crypto greed={val} ({name})"}
                elif val <= 35:
                    return {"signal": "BEAR", "reason": f"Crypto fear={val} ({name})"}
                return {"signal": "NEUTRAL", "reason": f"Neutral sentiment={val}"}

            else:  # GOLD
                # Gold sentiment via GLD ETF momentum + VIX
                r = requests.get(
                    "https://query1.finance.yahoo.com/v8/finance/chart/GLD?interval=1d&range=10d",
                    timeout=10, headers={"User-Agent": "Mozilla/5.0"}
                )
                closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                if len(closes) >= 5:
                    momentum = ((closes[-1] - closes[-5]) / closes[-5]) * 100
                    log.info(f"Gold 5-day momentum: {momentum:.2f}%")
                    if momentum > 1.0:
                        return {"signal": "BULL", "reason": f"Gold ETF momentum +{momentum:.1f}% → bullish"}
                    elif momentum < -1.0:
                        return {"signal": "BEAR", "reason": f"Gold ETF momentum {momentum:.1f}% → bearish"}
                return {"signal": "NEUTRAL", "reason": "Gold sentiment neutral"}
        except Exception as e:
            log.warning(f"Layer 1 error: {e}")
            return {"signal": "NEUTRAL", "reason": "Sentiment data unavailable"}

    # ─── LAYER 2: MACRO ──────────────────────────────────────────────────────
    def _layer2_macro(self):
        try:
            r = requests.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1d&range=5d",
                timeout=10, headers={"User-Agent": "Mozilla/5.0"}
            )
            closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]

            if len(closes) >= 2:
                dxy_chg = ((closes[-1] - closes[-2]) / closes[-2]) * 100
                log.info(f"DXY change: {dxy_chg:.2f}%")

                if self.asset == "BTC":
                    # BTC inverse to DXY
                    if dxy_chg <= -0.3:
                        return {"signal": "BULL", "reason": f"DXY falling {dxy_chg:.2f}% → BTC bullish"}
                    elif dxy_chg >= 0.3:
                        return {"signal": "BEAR", "reason": f"DXY rising {dxy_chg:.2f}% → BTC bearish"}
                else:
                    # Gold ALSO inverse to DXY (even stronger!)
                    if dxy_chg <= -0.2:
                        return {"signal": "BULL", "reason": f"DXY falling {dxy_chg:.2f}% → Gold bullish (strong signal!)"}
                    elif dxy_chg >= 0.2:
                        return {"signal": "BEAR", "reason": f"DXY rising {dxy_chg:.2f}% → Gold bearish"}

            now = datetime.now(self.sg_tz)
            if now.weekday() == 2 and now.day <= 15:
                if self.asset == "GOLD":
                    return {"signal": "BULL", "reason": "CPI day → inflation fear → Gold bullish!"}
                return {"signal": "BEAR", "reason": "Possible CPI/Fed day → BTC caution"}

            return {"signal": "NEUTRAL", "reason": "DXY stable, no major macro events"}
        except Exception as e:
            log.warning(f"Layer 2 error: {e}")
            return {"signal": "NEUTRAL", "reason": "Macro data unavailable"}

    # ─── LAYER 3: CROSS-MARKET ───────────────────────────────────────────────
    def _layer3_crossmarket(self):
        try:
            results = {}
            for ticker, name in [("^GSPC", "SP500"), ("^VIX", "VIX"), ("GC=F", "Gold_spot")]:
                try:
                    r = requests.get(
                        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d",
                        timeout=10, headers={"User-Agent": "Mozilla/5.0"}
                    )
                    closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                    if len(closes) >= 2:
                        chg = ((closes[-1] - closes[-2]) / closes[-2]) * 100
                        results[name] = chg
                        log.info(f"{name}: {chg:.2f}%")
                except:
                    pass

            if self.asset == "BTC":
                sp500_chg = results.get("SP500", 0)
                vix       = results.get("VIX", 20)
                if sp500_chg > 0.5 and vix < 20:
                    return {"signal": "BULL", "reason": f"SP500 +{sp500_chg:.1f}%, VIX low → risk-on → BTC bullish"}
                elif sp500_chg < -0.5 or vix > 25:
                    return {"signal": "BEAR", "reason": f"SP500 {sp500_chg:.1f}%, VIX={vix:.0f} → risk-off → BTC bearish"}

            else:  # GOLD
                vix      = results.get("VIX", 20)
                gold_chg = results.get("Gold_spot", 0)
                sp500    = results.get("SP500", 0)
                # Gold loves uncertainty!
                if vix > 20 or sp500 < -0.5:
                    return {"signal": "BULL", "reason": f"VIX={vix:.0f} elevated / SP500 weak → safe haven → Gold bullish"}
                elif gold_chg > 0.3:
                    return {"signal": "BULL", "reason": f"Gold spot momentum +{gold_chg:.1f}%"}
                elif vix < 15 and sp500 > 0.5:
                    return {"signal": "BEAR", "reason": f"Risk-on market → capital leaving Gold"}

            return {"signal": "NEUTRAL", "reason": "Cross-market signals mixed"}
        except Exception as e:
            log.warning(f"Layer 3 error: {e}")
            return {"signal": "NEUTRAL", "reason": "Cross-market data unavailable"}

    # ─── LAYER 4: ON-CHAIN / FUNDAMENTALS ───────────────────────────────────
    def _layer4_onchain(self):
        try:
            if self.asset == "BTC":
                # BTC Dominance
                r       = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
                btc_dom = r.json()["data"]["market_cap_percentage"]["btc"]
                log.info(f"BTC Dominance: {btc_dom:.1f}%")
                if btc_dom > 55:
                    return {"signal": "BULL", "reason": f"BTC dominance {btc_dom:.1f}% → strong BTC season"}
                elif btc_dom < 45:
                    return {"signal": "BEAR", "reason": f"BTC dominance low {btc_dom:.1f}% → altcoin rotation"}
                return {"signal": "NEUTRAL", "reason": f"BTC dominance neutral {btc_dom:.1f}%"}

            else:  # GOLD
                # Gold: check inflation expectations via TIPS (real yields)
                r = requests.get(
                    "https://query1.finance.yahoo.com/v8/finance/chart/TIP?interval=1d&range=5d",
                    timeout=10, headers={"User-Agent": "Mozilla/5.0"}
                )
                closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                if len(closes) >= 2:
                    tip_chg = ((closes[-1] - closes[-2]) / closes[-2]) * 100
                    log.info(f"TIPS ETF change: {tip_chg:.2f}%")
                    # Rising TIPS = inflation expectations rising = Gold bullish
                    if tip_chg > 0.1:
                        return {"signal": "BULL", "reason": f"Inflation expectations rising → Gold bullish"}
                    elif tip_chg < -0.1:
                        return {"signal": "BEAR", "reason": f"Real yields rising → Gold headwind"}
                return {"signal": "NEUTRAL", "reason": "Gold fundamentals neutral"}
        except Exception as e:
            log.warning(f"Layer 4 error: {e}")
            return {"signal": "NEUTRAL", "reason": "Fundamental data unavailable"}

    # ─── LAYER 5: ADVANCED TECHNICAL ─────────────────────────────────────────
    def _layer5_technical(self):
        try:
            # Get candles from OKX
            if self.asset == "BTC":
                inst_id = "BTC-USDT"
                swap_id = "BTC-USDT-SWAP"
            else:
                inst_id = "XAU-USDT"   # Gold on OKX
                swap_id = None

            r = requests.get(
                f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=1H&limit=100",
                timeout=10
            )
            candles = r.json()["data"]
            if not candles:
                return {"signal": "NEUTRAL", "reason": "No candle data"}

            closes = [float(c[4]) for c in reversed(candles)]
            highs  = [float(c[2]) for c in reversed(candles)]
            lows   = [float(c[3]) for c in reversed(candles)]
            vols   = [float(c[5]) for c in reversed(candles)]

            bull_signals = 0
            bear_signals = 0
            reasons      = []

            # ── RSI (14) ────────────────────────────────────────────────────
            rsi = self._calc_rsi(closes, 14)
            log.info(f"RSI(14): {rsi:.1f}")
            if rsi < 35:
                bull_signals += 2  # Strong oversold
                reasons.append(f"RSI oversold {rsi:.0f} 🟢🟢")
            elif rsi < 45:
                bull_signals += 1
                reasons.append(f"RSI low {rsi:.0f} 🟢")
            elif rsi > 65:
                bear_signals += 2  # Strong overbought
                reasons.append(f"RSI overbought {rsi:.0f} 🔴🔴")
            elif rsi > 55:
                bear_signals += 1
                reasons.append(f"RSI high {rsi:.0f} 🔴")

            # ── MACD (12,26,9) ───────────────────────────────────────────────
            ema12      = self._ema(closes, 12)
            ema26      = self._ema(closes, 26)
            macd_line  = [e12 - e26 for e12, e26 in zip(ema12[-len(ema26):], ema26)]
            signal_line = self._ema(macd_line, 9)
            macd_hist  = macd_line[-1] - signal_line[-1]
            macd_hist_prev = macd_line[-2] - signal_line[-2]
            log.info(f"MACD histogram: {macd_hist:.2f}")
            if macd_hist > 0 and macd_hist_prev <= 0:
                bull_signals += 2
                reasons.append("MACD bullish crossover 🟢🟢")
            elif macd_hist < 0 and macd_hist_prev >= 0:
                bear_signals += 2
                reasons.append("MACD bearish crossover 🔴🔴")
            elif macd_hist > 0:
                bull_signals += 1
                reasons.append("MACD positive 🟢")
            else:
                bear_signals += 1
                reasons.append("MACD negative 🔴")

            # ── Bollinger Bands (20,2) ───────────────────────────────────────
            bb_period = 20
            if len(closes) >= bb_period:
                bb_mid   = sum(closes[-bb_period:]) / bb_period
                bb_std   = math.sqrt(sum((c - bb_mid)**2 for c in closes[-bb_period:]) / bb_period)
                bb_upper = bb_mid + 2 * bb_std
                bb_lower = bb_mid - 2 * bb_std
                price    = closes[-1]
                bb_pct   = (price - bb_lower) / (bb_upper - bb_lower) * 100
                log.info(f"Bollinger %B: {bb_pct:.1f}%")
                if bb_pct < 10:
                    bull_signals += 2
                    reasons.append(f"BB oversold %B={bb_pct:.0f}% 🟢🟢")
                elif bb_pct > 90:
                    bear_signals += 2
                    reasons.append(f"BB overbought %B={bb_pct:.0f}% 🔴🔴")
                elif bb_pct < 30:
                    bull_signals += 1
                    reasons.append(f"Near BB lower band 🟢")
                elif bb_pct > 70:
                    bear_signals += 1
                    reasons.append(f"Near BB upper band 🔴")

            # ── Stochastic (14,3) ────────────────────────────────────────────
            stoch = self._calc_stochastic(closes, highs, lows, 14, 3)
            log.info(f"Stochastic: {stoch:.1f}")
            if stoch < 20:
                bull_signals += 1
                reasons.append(f"Stochastic oversold {stoch:.0f} 🟢")
            elif stoch > 80:
                bear_signals += 1
                reasons.append(f"Stochastic overbought {stoch:.0f} 🔴")

            # ── Volume Confirmation ──────────────────────────────────────────
            avg_vol    = sum(vols[-20:]) / 20
            latest_vol = vols[-1]
            if latest_vol > avg_vol * 1.5:
                # High volume confirms direction
                if closes[-1] > closes[-2]:
                    bull_signals += 1
                    reasons.append(f"High volume bullish candle 🟢")
                else:
                    bear_signals += 1
                    reasons.append(f"High volume bearish candle 🔴")

            # ── Moving Averages (50, 200) ────────────────────────────────────
            if len(closes) >= 50:
                ma50  = sum(closes[-50:]) / 50
                price = closes[-1]
                if price > ma50:
                    bull_signals += 1
                    reasons.append(f"Price above MA50 🟢")
                else:
                    bear_signals += 1
                    reasons.append(f"Price below MA50 🔴")

            # ── Funding Rate (BTC only) ──────────────────────────────────────
            if swap_id:
                try:
                    r2      = requests.get(
                        f"https://www.okx.com/api/v5/public/funding-rate?instId={swap_id}",
                        timeout=10
                    )
                    funding = float(r2.json()["data"][0]["fundingRate"])
                    log.info(f"Funding rate: {funding:.5f}")
                    if funding < -0.0001:
                        bull_signals += 1
                        reasons.append(f"Funding negative → short squeeze likely 🟢")
                    elif funding > 0.0003:
                        bear_signals += 1
                        reasons.append(f"Funding high → overleveraged longs 🔴")
                except:
                    pass

            # ── Final Score ──────────────────────────────────────────────────
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

    def _calc_stochastic(self, closes, highs, lows, k_period=14, d_period=3):
        if len(closes) < k_period:
            return 50
        recent_highs = highs[-k_period:]
        recent_lows  = lows[-k_period:]
        highest      = max(recent_highs)
        lowest       = min(recent_lows)
        if highest == lowest:
            return 50
        k = ((closes[-1] - lowest) / (highest - lowest)) * 100
        return k
