"""
Pro Signal Engine v2
====================
Strategy: Trend following with pullback entry
Timeframes: H1 trend + M5 entry
Indicators: EMA50/200 trend | EMA20 pullback | RSI | ATR
"""

import os
import requests
import logging
import math
from datetime import datetime
import pytz

log = logging.getLogger(__name__)

# Remove any accidental API key exposure
class SafeFilter(logging.Filter):
    def __init__(self):
        self.api_key = os.environ.get("OANDA_API_KEY", "")
    def filter(self, record):
        if self.api_key and self.api_key in str(record.getMessage()):
            record.msg = record.msg.replace(self.api_key, "***API_KEY***")
        return True

safe_filter = SafeFilter()
log.addFilter(safe_filter)

class SignalEngine:
    def __init__(self):
        self.sg_tz      = pytz.timezone("Asia/Singapore")
        self.asset      = "EURUSD"
        self.api_key    = os.environ.get("OANDA_API_KEY", "")
        self.account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
        self.base_url   = "https://api-fxpractice.oanda.com"
        self.headers    = {"Authorization": "Bearer " + self.api_key}

    OANDA_MAP = {
        "EURUSD": "EUR_USD",
        "GBPUSD": "GBP_USD",
        "XAUUSD": "XAU_USD"
    }

    def _fetch_candles(self, instrument, granularity, count=200):
        """Fetch candles with retry logic - 3 attempts"""
        url    = self.base_url + "/v3/instruments/" + instrument + "/candles"
        params = {"count": str(count), "granularity": granularity, "price": "M"}
        for attempt in range(3):
            try:
                r = requests.get(url, headers=self.headers, params=params, timeout=10)
                if r.status_code == 200:
                    candles = r.json()["candles"]
                    c = [x for x in candles if x["complete"]]
                    closes = [float(x["mid"]["c"]) for x in c]
                    highs  = [float(x["mid"]["h"]) for x in c]
                    lows   = [float(x["mid"]["l"]) for x in c]
                    return closes, highs, lows
                log.warning("Candle fetch attempt " + str(attempt+1) + " failed: " + str(r.status_code))
            except Exception as e:
                log.warning("Candle fetch attempt " + str(attempt+1) + " error: " + str(e))
        return [], [], []

    def _fetch_yahoo(self, ticker, interval="1d", range_="5d"):
        """Fetch Yahoo Finance data with retry"""
        url = "https://query1.finance.yahoo.com/v8/finance/chart/" + ticker + "?interval=" + interval + "&range=" + range_
        for attempt in range(3):
            try:
                r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200:
                    closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                    return closes
            except Exception as e:
                log.warning("Yahoo attempt " + str(attempt+1) + " error: " + str(e))
        return []

    def analyze(self, asset="EURUSD"):
        self.asset = asset
        log.info("Analyzing " + asset + "...")
        if asset == "XAUUSD":
            return self._analyze_gold()
        return self._analyze_forex()

    # ══════════════════════════════════════════════
    # FOREX STRATEGY
    # H1: EMA50/200 trend direction
    # M5: Price near EMA20 + RSI pullback entry
    # ATR: Volatility filter
    # ══════════════════════════════════════════════
    def _analyze_forex(self):
        instrument = self.OANDA_MAP.get(self.asset, "EUR_USD")
        reasons    = []
        bull = 0
        bear = 0

        # ── H1 TREND FILTER (EMA50 vs EMA200) ──────────
        h1_closes, h1_highs, h1_lows = self._fetch_candles(instrument, "H1", 250)
        if len(h1_closes) < 200:
            log.warning(self.asset + " not enough H1 data")
            return 0, "NONE", "Not enough H1 data"

        ema50_h1  = self._ema(h1_closes, 50)
        ema200_h1 = self._ema(h1_closes, 200)
        h1_trend  = "BUY" if ema50_h1[-1] > ema200_h1[-1] else "SELL"
        log.info(self.asset + " H1 EMA50=" + str(round(ema50_h1[-1], 5)) + " EMA200=" + str(round(ema200_h1[-1], 5)) + " Trend=" + h1_trend)

        # ATR volatility filter on H1
        atr_h1     = self._atr(h1_highs, h1_lows, h1_closes, 14)
        atr_avg_h1 = sum(self._atr(h1_highs[:i+14], h1_lows[:i+14], h1_closes[:i+14], 14)
                        for i in range(0, 40, 8)) / 5
        if atr_h1 < atr_avg_h1 * 0.7:
            log.info(self.asset + " H1 ATR too low: " + str(round(atr_h1, 5)) + " < " + str(round(atr_avg_h1*0.7, 5)))
            return 0, "NONE", "Low volatility - ATR filter"

        log.info(self.asset + " H1 ATR=" + str(round(atr_h1, 5)) + " OK")
        reasons.append("H1 trend=" + h1_trend + " ATR OK")

        # ── M5 ENTRY (Pullback near EMA20 + RSI) ───────
        m5_closes, m5_highs, m5_lows = self._fetch_candles(instrument, "M5", 100)
        if len(m5_closes) < 50:
            log.warning(self.asset + " not enough M5 data")
            return 0, "NONE", "Not enough M5 data"

        ema20_m5 = self._ema(m5_closes, 20)
        rsi_m5   = self._rsi(m5_closes, 14)
        current  = m5_closes[-1]

        # Check price near EMA20 (within 0.05% = pullback zone)
        ema20_val    = ema20_m5[-1]
        near_ema20   = abs(current - ema20_val) / ema20_val < 0.0005
        log.info(self.asset + " M5 price=" + str(round(current, 5)) + " EMA20=" + str(round(ema20_val, 5)) + " near=" + str(near_ema20) + " RSI=" + str(round(rsi_m5, 1)))

        # MACD for momentum confirmation
        ema12_m5 = self._ema(m5_closes, 12)
        ema26_m5 = self._ema(m5_closes, 26)
        macd     = [a - b for a, b in zip(ema12_m5[-len(ema26_m5):], ema26_m5)]
        sig      = self._ema(macd, 9)
        hist     = macd[-1] - sig[-1]
        prev     = macd[-2] - sig[-2] if len(macd) >= 2 else 0

        if h1_trend == "BUY":
            # BUY conditions: pullback near EMA20 + RSI > 50 + MACD positive
            score = 0
            if near_ema20:
                score += 2
                reasons.append("Price at EMA20 pullback BUY")
            elif current < ema20_val:
                score += 1
                reasons.append("Price below EMA20 BUY zone")

            if rsi_m5 > 50:
                score += 1
                reasons.append("RSI=" + str(round(rsi_m5, 0)) + " bullish")
            if rsi_m5 > 55:
                score += 1
                reasons.append("RSI strong BUY")

            if hist > 0 and prev <= 0:
                score += 2
                reasons.append("MACD bullish cross!")
            elif hist > 0:
                score += 1
                reasons.append("MACD positive")

            # Macro confirmation
            macro = self._macro_check()
            if macro == "BULL":
                score += 1
                reasons.append("Macro USD weak=BUY")

            log.info(self.asset + " BUY score=" + str(score))
            if score >= 4:
                return min(score, 5), "BUY", " | ".join(reasons)
            return score, "NONE", " | ".join(reasons)

        else:  # SELL
            score = 0
            if near_ema20:
                score += 2
                reasons.append("Price at EMA20 pullback SELL")
            elif current > ema20_val:
                score += 1
                reasons.append("Price above EMA20 SELL zone")

            if rsi_m5 < 50:
                score += 1
                reasons.append("RSI=" + str(round(rsi_m5, 0)) + " bearish")
            if rsi_m5 < 45:
                score += 1
                reasons.append("RSI strong SELL")

            if hist < 0 and prev >= 0:
                score += 2
                reasons.append("MACD bearish cross!")
            elif hist < 0:
                score += 1
                reasons.append("MACD negative")

            macro = self._macro_check()
            if macro == "BEAR":
                score += 1
                reasons.append("Macro USD strong=SELL")

            log.info(self.asset + " SELL score=" + str(score))
            if score >= 4:
                return min(score, 5), "SELL", " | ".join(reasons)
            return score, "NONE", " | ".join(reasons)

    def _macro_check(self):
        """Quick USD direction check"""
        try:
            closes = self._fetch_yahoo("DX-Y.NYB", "1h", "2d")
            if len(closes) >= 3:
                chg = ((closes[-1] - closes[-3]) / closes[-3]) * 100
                if chg < -0.15:
                    return "BULL"
                elif chg > 0.15:
                    return "BEAR"
        except:
            pass
        return "NEUTRAL"

    # ══════════════════════════════════════════════
    # GOLD STRATEGY
    # H1: EMA20/50 trend + ATR
    # M15: MACD + Stochastic entry
    # ══════════════════════════════════════════════
    def _analyze_gold(self):
        reasons = []
        bull = 0
        bear = 0

        # USD direction (most important for gold!)
        dxy = self._fetch_yahoo("DX-Y.NYB", "1h", "2d")
        if len(dxy) >= 3:
            chg = ((dxy[-1] - dxy[-3]) / dxy[-3]) * 100
            log.info("Gold DXY 2h chg: " + str(round(chg, 3)))
            if chg < -0.3:
                bull += 2
                reasons.append("USD falling=" + str(round(chg, 2)) + "% Gold up")
            elif chg > 0.3:
                bear += 2
                reasons.append("USD rising=" + str(round(chg, 2)) + "% Gold down")

        # VIX fear gauge
        vix = self._fetch_yahoo("%5EVIX", "1d", "5d")
        if vix:
            v = vix[-1]
            log.info("Gold VIX=" + str(round(v, 1)))
            if v > 18:
                bull += 1
                reasons.append("VIX=" + str(round(v, 0)) + " fear=Gold up")
            elif v < 13:
                bear += 1
                reasons.append("VIX=" + str(round(v, 0)) + " calm=Gold weak")

        # Bond yields
        yields = self._fetch_yahoo("%5ETNX", "1d", "5d")
        if len(yields) >= 2:
            chg = yields[-1] - yields[-2]
            log.info("Gold yields chg=" + str(round(chg, 3)))
            if chg < -0.04:
                bull += 1
                reasons.append("Yields falling=Gold up")
            elif chg > 0.04:
                bear += 1
                reasons.append("Yields rising=Gold down")

        # H1 technical
        h1_closes, h1_highs, h1_lows = self._fetch_candles("XAU_USD", "H1", 100)
        if len(h1_closes) >= 50:
            ema20 = self._ema(h1_closes, 20)
            ema50 = self._ema(h1_closes, 50)
            atr   = self._atr(h1_highs, h1_lows, h1_closes, 14)
            rsi   = self._rsi(h1_closes, 14)

            log.info("Gold H1 EMA20=" + str(round(ema20[-1], 2)) + " EMA50=" + str(round(ema50[-1], 2)) + " RSI=" + str(round(rsi, 1)))

            if len(ema20) >= 2 and len(ema50) >= 2:
                if ema20[-1] > ema50[-1] and ema20[-2] <= ema50[-2]:
                    bull += 2
                    reasons.append("Gold EMA20 cross above EMA50!")
                elif ema20[-1] < ema50[-1] and ema20[-2] >= ema50[-2]:
                    bear += 2
                    reasons.append("Gold EMA20 cross below EMA50!")
                elif ema20[-1] > ema50[-1]:
                    bull += 1
                    reasons.append("Gold H1 uptrend")
                else:
                    bear += 1
                    reasons.append("Gold H1 downtrend")

            if rsi < 40:
                bull += 1
                reasons.append("Gold RSI oversold=" + str(round(rsi, 0)))
            elif rsi > 60:
                bear += 1
                reasons.append("Gold RSI overbought=" + str(round(rsi, 0)))

        # M15 momentum
        m15_closes, m15_highs, m15_lows = self._fetch_candles("XAU_USD", "M15", 50)
        if len(m15_closes) >= 26:
            ema12 = self._ema(m15_closes, 12)
            ema26 = self._ema(m15_closes, 26)
            macd  = [a - b for a, b in zip(ema12[-len(ema26):], ema26)]
            sig   = self._ema(macd, 9)
            hist  = macd[-1] - sig[-1]
            prev  = macd[-2] - sig[-2] if len(macd) >= 2 else 0
            stoch = self._stochastic(m15_closes, m15_highs, m15_lows, 14)

            log.info("Gold M15 MACD=" + str(round(hist, 2)) + " Stoch=" + str(round(stoch, 1)))

            if hist > 0 and prev <= 0:
                bull += 2
                reasons.append("Gold M15 MACD bullish cross!")
            elif hist < 0 and prev >= 0:
                bear += 2
                reasons.append("Gold M15 MACD bearish cross!")
            elif hist > 0:
                bull += 1
                reasons.append("Gold M15 MACD positive")
            elif hist < 0:
                bear += 1
                reasons.append("Gold M15 MACD negative")

            if stoch < 25:
                bull += 1
                reasons.append("Gold Stoch oversold=" + str(round(stoch, 0)))
            elif stoch > 75:
                bear += 1
                reasons.append("Gold Stoch overbought=" + str(round(stoch, 0)))

        log.info("Gold bull=" + str(bull) + " bear=" + str(bear))

        reason_str = " | ".join(reasons) if reasons else "No signals"
        if bull >= 4 and bull > bear:
            return min(bull, 5), "BUY", reason_str
        elif bear >= 4 and bear > bull:
            return min(bear, 5), "SELL", reason_str
        return max(bull, bear), "NONE", reason_str

    # ══════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════
    def _rsi(self, closes, period=14):
        gains, losses = [], []
        for i in range(1, len(closes)):
            d = closes[i] - closes[i-1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        if len(gains) < period:
            return 50
        ag = sum(gains[-period:]) / period
        al = sum(losses[-period:]) / period
        if al == 0:
            return 100
        return 100 - (100 / (1 + ag / al))

    def _ema(self, data, period):
        if not data:
            return [0.0]
        if len(data) < period:
            avg = sum(data) / len(data)
            return [avg] * len(data)
        seed = sum(data[:period]) / period
        emas = [seed] * period
        mult = 2 / (period + 1)
        for p in data[period:]:
            emas.append((p - emas[-1]) * mult + emas[-1])
        return emas

    def _stochastic(self, closes, highs, lows, period=14):
        if len(closes) < period:
            return 50
        h = max(highs[-period:])
        l = min(lows[-period:])
        if h == l:
            return 50
        return ((closes[-1] - l) / (h - l)) * 100

    def _atr(self, highs, lows, closes, period=14):
        if len(closes) < period + 1:
            return 0.001
        trs = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            trs.append(tr)
        return sum(trs[-period:]) / period
