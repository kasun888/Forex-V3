"""
Signal Engine — EUR/USD London+NY Session Scalp
=================================================
Pair:   EUR/USD ONLY
Target: 26 pip TP | 13 pip SL | 2:1 R:R

OPTION A LOOSENING APPLIED:
  - MIN_ATR_PIPS: 4.0 → 2.5  (allows lower-volatility entries)
  - L2 breakout tolerance: 8 pips → 15 pips (wider breakout zone)
  - RSI_BUY_MAX:  58 → 65  (easier RSI confirmation on longs)
  - RSI_SELL_MIN: 42 → 35  (easier RSI confirmation on shorts)
  - L2_EXPIRY_MINUTES: 45 → 90 (doubles window for L3 to follow)
  - EMA_TOL: 1.0 pip → 2.0 pip (more flexible EMA13 touch)
  - MIN_M5_RANGE: 1.5 pip → 1.0 pip (allow smaller M5 candles)

FIXES INHERITED:
  FIX-A: L2 and L3 are separated via state memory.
  FIX-B: RSI thresholds further loosened for more reachable pullbacks.
  FIX-C: Every layer logs pass/fail for Railway debugging.
"""

import os, requests, logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


class SafeFilter(logging.Filter):
    def __init__(self):
        self.api_key = os.environ.get("OANDA_API_KEY", "")
    def filter(self, record):
        if self.api_key and self.api_key in str(record.getMessage()):
            record.msg = record.msg.replace(self.api_key, "***")
        return True

log.addFilter(SafeFilter())

# ── OPTION A: Loosened parameters ────────────────────────────────────
L2_EXPIRY_MINUTES = 90       # was 45 — doubles L3 wait window
MIN_ATR_PIPS      = 2.5      # was 4.0 — allow quieter markets
L2_BREAK_BUFFER   = 0.00150  # was 0.00080 (8 pip) → now 15 pip
RSI_BUY_MAX       = 65       # was 58 — easier long confirmation
RSI_SELL_MIN      = 35       # was 42 — easier short confirmation
EMA_TOL           = 0.00020  # was 0.00010 (1 pip) → 2 pip EMA touch
MIN_M5_RANGE      = 0.00010  # was 0.00015 — allow smaller M5 candles


class SignalEngine:
    def __init__(self):
        self.api_key  = os.environ.get("OANDA_API_KEY", "")
        self.base_url = "https://api-fxpractice.oanda.com"
        self.headers  = {"Authorization": "Bearer " + self.api_key}

    def _fetch_candles(self, instrument, granularity, count=60):
        url    = self.base_url + "/v3/instruments/" + instrument + "/candles"
        params = {"count": str(count), "granularity": granularity, "price": "M"}
        for attempt in range(3):
            try:
                r = requests.get(url, headers=self.headers, params=params, timeout=10)
                if r.status_code == 200:
                    c = [x for x in r.json()["candles"] if x["complete"]]
                    return (
                        [float(x["mid"]["c"]) for x in c],
                        [float(x["mid"]["h"]) for x in c],
                        [float(x["mid"]["l"]) for x in c],
                        [float(x["mid"]["o"]) for x in c],
                    )
                log.warning("Candle " + granularity + " attempt " + str(attempt+1) + " HTTP " + str(r.status_code))
            except Exception as e:
                log.warning("Candle fetch error: " + str(e))
        return [], [], [], []

    def _ema(self, data, period):
        if not data:
            return [0.0]
        if len(data) < period:
            return [sum(data) / len(data)] * len(data)
        seed = sum(data[:period]) / period
        emas = [seed] * period
        mult = 2 / (period + 1)
        for p in data[period:]:
            emas.append((p - emas[-1]) * mult + emas[-1])
        return emas

    def _rsi(self, closes, period=7):
        if len(closes) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(1, len(closes)):
            delta = closes[i] - closes[i-1]
            gains.append(max(delta, 0))
            losses.append(max(-delta, 0))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _atr(self, highs, lows, closes, period=14):
        if len(highs) < period + 1:
            return 0.0
        trs = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            trs.append(tr)
        return sum(trs[-period:]) / period

    def analyze(self, asset="EURUSD", state=None):
        """
        Returns (score, direction, details, layer_breakdown_dict).
        layer_breakdown shows pass/fail per layer for Telegram display.
        """
        return self._scalp_eurusd("EUR_USD", state=state)

    def _scalp_eurusd(self, instrument, state=None):
        reasons = []
        score   = 0

        # ── FIX-A: Check if L2 already fired ─────────────────────────────
        if state is not None:
            pending = state.get("l2_pending", {})
            if pending.get("instrument") == instrument:
                age_minutes = (
                    datetime.now(timezone.utc) -
                    datetime.fromisoformat(pending["timestamp"])
                ).total_seconds() / 60

                if age_minutes <= L2_EXPIRY_MINUTES:
                    log.info(
                        instrument + ": L2 pending (" + pending["direction"] +
                        ") — checking L3 [" + str(round(age_minutes, 1)) + " min elapsed]"
                    )
                    return self._check_l3_only(
                        instrument,
                        direction=pending["direction"],
                        score_so_far=3,
                        reasons=["(L0+L1+L2 already confirmed — checking L3 only)"],
                        state=state,
                    )
                else:
                    log.info(instrument + ": L2 pending EXPIRED (" + str(round(age_minutes, 1)) + " min) — resetting")
                    state.pop("l2_pending", None)

        # ── L0: H4 MACRO TREND — EMA50 ───────────────────────────────────
        h4_c, h4_h, h4_l, _ = self._fetch_candles(instrument, "H4", 60)
        if len(h4_c) < 51:
            return 0, "NONE", "Not enough H4 data", {"L0":"⚠️ NO DATA"}

        h4_ema50 = self._ema(h4_c, 50)[-1]
        h4_price = h4_c[-1]

        if h4_price > h4_ema50:
            direction = "BUY"
            reasons.append("✅ L0 H4 BUY above EMA50=" + str(round(h4_ema50, 5)))
        elif h4_price < h4_ema50:
            direction = "SELL"
            reasons.append("✅ L0 H4 SELL below EMA50=" + str(round(h4_ema50, 5)))
        else:
            return 0, "NONE", "H4 EMA50 flat", {"L0":"❌ FLAT"}

        score = 1

        # ── VETO: ATR FLAT BLOCK (2.5 pip threshold) ──────────────────────
        h1_c, h1_h, h1_l, _ = self._fetch_candles(instrument, "H1", 60)
        if len(h1_c) < 20:
            return score, "NONE", " | ".join(reasons) + " | No H1 data", {"L0":"✅","ATR":"⚠️ NO DATA"}

        h1_atr     = self._atr(h1_h, h1_l, h1_c, 14)
        h1_atr_pip = h1_atr / 0.0001

        if h1_atr_pip < MIN_ATR_PIPS:
            msg = "🚫 ATR VETO: " + str(round(h1_atr_pip, 1)) + "p < " + str(MIN_ATR_PIPS) + "p"
            reasons.append(msg)
            return score, "NONE", " | ".join(reasons), {
                "L0":"✅ " + direction, "ATR":"❌ " + str(round(h1_atr_pip,1)) + "p"
            }
        reasons.append("✅ ATR=" + str(round(h1_atr_pip, 1)) + "p")

        # ── L1: H1 DUAL EMA ALIGNMENT ────────────────────────────────────
        h1_ema21 = self._ema(h1_c, 21)[-1]
        h1_ema50 = self._ema(h1_c, 50)[-1]
        h1_close = h1_c[-1]

        bull_h1 = (h1_close > h1_ema21) and (h1_ema21 > h1_ema50)
        bear_h1 = (h1_close < h1_ema21) and (h1_ema21 < h1_ema50)

        if direction == "BUY" and bull_h1:
            reasons.append("✅ L1 H1 BULL: price>EMA21>EMA50")
            score = 2
        elif direction == "SELL" and bear_h1:
            reasons.append("✅ L1 H1 BEAR: price<EMA21<EMA50")
            score = 2
        else:
            msg = "L1 FAIL — H1 EMAs not aligned"
            reasons.append(msg)
            return score, "NONE", " | ".join(reasons), {
                "L0":"✅ " + direction,
                "ATR":"✅ " + str(round(h1_atr_pip,1)) + "p",
                "L1":"❌ NOT ALIGNED"
            }

        # ── L2: M15 IMPULSE CANDLE BREAK ─────────────────────────────────
        m15_c, m15_h, m15_l, m15_o = self._fetch_candles(instrument, "M15", 20)
        if len(m15_c) < 8:
            return score, "NONE", " | ".join(reasons) + " | No M15 data", {
                "L0":"✅","ATR":"✅","L1":"✅","L2":"⚠️ NO DATA"
            }

        lookback       = 5
        structure_high = max(m15_h[-lookback-1:-1])
        structure_low  = min(m15_l[-lookback-1:-1])
        last_close     = m15_c[-1]
        last_open      = m15_o[-1]
        last_high      = m15_h[-1]
        last_low       = m15_l[-1]
        candle_range   = max(last_high - last_low, 0.00001)

        bull_body_m15 = (last_close > last_open) and ((last_close - last_low) / candle_range >= 0.50)
        bear_body_m15 = (last_close < last_open) and ((last_high - last_close) / candle_range >= 0.50)

        bull_break = (last_close > structure_high) and (last_close <= structure_high + L2_BREAK_BUFFER) and bull_body_m15
        bear_break = (last_close < structure_low)  and (last_close >= structure_low  - L2_BREAK_BUFFER) and bear_body_m15

        if direction == "BUY" and bull_break:
            reasons.append("✅ L2 M15 BREAK UP body=" + str(round((last_close - last_low)/candle_range*100)) + "%")
            score = 3
        elif direction == "SELL" and bear_break:
            reasons.append("✅ L2 M15 BREAK DOWN body=" + str(round((last_high - last_close)/candle_range*100)) + "%")
            score = 3
        else:
            msg = "L2 FAIL — no M15 impulse (body=" + str(bull_body_m15 or bear_body_m15) + ")"
            reasons.append(msg)
            return score, "NONE", " | ".join(reasons), {
                "L0":"✅ " + direction,
                "ATR":"✅ " + str(round(h1_atr_pip,1)) + "p",
                "L1":"✅", "L2":"❌ NO BREAK"
            }

        # ── FIX-A: Save L2 state, wait for L3 next scan ──────────────────
        if state is not None:
            state["l2_pending"] = {
                "instrument": instrument,
                "direction":  direction,
                "timestamp":  datetime.now(timezone.utc).isoformat(),
            }
            reasons.append("⏳ L2 confirmed — awaiting L3 pullback (next scan, up to " + str(L2_EXPIRY_MINUTES) + "min)")
            return score, "NONE", " | ".join(reasons), {
                "L0":"✅ " + direction,
                "ATR":"✅ " + str(round(h1_atr_pip,1)) + "p",
                "L1":"✅", "L2":"✅ FIRED — awaiting L3", "L3":"⏳ pending"
            }

        return self._check_l3_only(instrument, direction, score, reasons, state=None)

    # ─────────────────────────────────────────────────────────────────────
    def _check_l3_only(self, instrument, direction, score_so_far, reasons, state=None):
        score = score_so_far

        m5_c, m5_h, m5_l, m5_o = self._fetch_candles(instrument, "M5", 50)
        if len(m5_c) < 15:
            return score, "NONE", " | ".join(reasons) + " | No M5 data", {
                "L0":"✅","ATR":"✅","L1":"✅","L2":"✅","L3":"⚠️ NO DATA"
            }

        ema13    = self._ema(m5_c, 13)[-1]
        rsi7     = self._rsi(m5_c, 7)
        m5_close = m5_c[-1]
        m5_open  = m5_o[-1]
        m5_high  = m5_h[-1]
        m5_low   = m5_l[-1]
        m5_range = max(m5_high - m5_low, 0.00001)

        bull_m5_body = (m5_close > m5_open) and ((m5_close - m5_low) / m5_range >= 0.50) and (m5_range >= MIN_M5_RANGE)
        bear_m5_body = (m5_close < m5_open) and ((m5_high - m5_close) / m5_range >= 0.50) and (m5_range >= MIN_M5_RANGE)

        recent_lows_m5  = m5_l[-3:-1]
        recent_highs_m5 = m5_h[-3:-1]
        bull_pb = any(l <= ema13 + EMA_TOL for l in recent_lows_m5)
        bear_pb = any(h >= ema13 - EMA_TOL for h in recent_highs_m5)

        bull_rsi = rsi7 < RSI_BUY_MAX
        bear_rsi = rsi7 > RSI_SELL_MIN

        rsi_str = "RSI7=" + str(round(rsi7, 1))

        if direction == "BUY" and bull_pb and bull_m5_body and bull_rsi:
            reasons.append("✅ L3 M5 bounce EMA13=" + str(round(ema13,5)) + " " + rsi_str)
            score = 4
        elif direction == "SELL" and bear_pb and bear_m5_body and bear_rsi:
            reasons.append("✅ L3 M5 bounce EMA13=" + str(round(ema13,5)) + " " + rsi_str)
            score = 4
        else:
            fail_reasons = []
            if direction == "BUY":
                if not bull_pb:   fail_reasons.append("no EMA touch")
                if not bull_m5_body: fail_reasons.append("weak body")
                if not bull_rsi:  fail_reasons.append("RSI too high (" + str(round(rsi7,1)) + ">=" + str(RSI_BUY_MAX) + ")")
            else:
                if not bear_pb:   fail_reasons.append("no EMA touch")
                if not bear_m5_body: fail_reasons.append("weak body")
                if not bear_rsi:  fail_reasons.append("RSI too low (" + str(round(rsi7,1)) + "<=" + str(RSI_SELL_MIN) + ")")
            msg = "L3 FAIL — " + ", ".join(fail_reasons)
            log.info(instrument + ": " + msg)
            reasons.append(msg)
            return score, "NONE", " | ".join(reasons), {
                "L0":"✅","ATR":"✅","L1":"✅","L2":"✅",
                "L3":"❌ " + ", ".join(fail_reasons)
            }

        # ── VETO 1: H1 EMA200 ────────────────────────────────────────────
        h1_long_c, _, _, _ = self._fetch_candles(instrument, "H1", 210)
        if len(h1_long_c) >= 200:
            h1_ema200 = self._ema(h1_long_c, 200)[-1]
            price_now = m5_c[-1]
            if direction == "BUY" and price_now < h1_ema200:
                msg = "🚫 VETO1 price below EMA200=" + str(round(h1_ema200, 5))
                reasons.append(msg)
                return score, "NONE", " | ".join(reasons), {
                    "L0":"✅","ATR":"✅","L1":"✅","L2":"✅","L3":"✅","V1":"❌ EMA200 BLOCK"
                }
            elif direction == "SELL" and price_now > h1_ema200:
                msg = "🚫 VETO1 price above EMA200=" + str(round(h1_ema200, 5))
                reasons.append(msg)
                return score, "NONE", " | ".join(reasons), {
                    "L0":"✅","ATR":"✅","L1":"✅","L2":"✅","L3":"✅","V1":"❌ EMA200 BLOCK"
                }
            else:
                reasons.append("✅ V1 EMA200=" + str(round(h1_ema200, 5)) + " ok")
        else:
            reasons.append("⚠️ EMA200 unavailable — skipped")

        # ── VETO 2: M30 COUNTER-TREND ─────────────────────────────────────
        m30_c, m30_h, m30_l, m30_o = self._fetch_candles(instrument, "M30", 10)
        if len(m30_c) >= 4:
            counter_trend_count = 0
            for i in range(-3, 0):
                c_rng = max(m30_h[i] - m30_l[i], 0.00001)
                if direction == "BUY":
                    if (m30_c[i] < m30_o[i]) and ((m30_h[i] - m30_c[i]) / c_rng >= 0.65):
                        counter_trend_count += 1
                else:
                    if (m30_c[i] > m30_o[i]) and ((m30_c[i] - m30_l[i]) / c_rng >= 0.65):
                        counter_trend_count += 1

            if counter_trend_count >= 3:
                msg = "🚫 VETO2 M30: 3/3 counter-trend candles"
                reasons.append(msg)
                return score, "NONE", " | ".join(reasons), {
                    "L0":"✅","ATR":"✅","L1":"✅","L2":"✅","L3":"✅","V1":"✅","V2":"❌ M30 COUNTER"
                }
            reasons.append("✅ V2 M30 ok (" + str(counter_trend_count) + "/3)")

        # ── ALL PASSED ────────────────────────────────────────────────────
        if state is not None:
            state.pop("l2_pending", None)
            log.info(instrument + ": ✅ ALL 4 LAYERS PASSED — firing trade")

        return score, direction, " | ".join(reasons), {
            "L0": "✅ H4 " + direction,
            "ATR": "✅",
            "L1": "✅ H1 stack",
            "L2": "✅ M15 break",
            "L3": "✅ M5 " + rsi_str,
            "V1": "✅ EMA200",
            "V2": "✅ M30",
        }
