"""
OANDA — EUR/USD London + NY Session Scalp Bot
==============================================
Pair:    EUR/USD only
Size:    74,000 units
SL:      13 pips
TP:      26 pips  [2:1 R:R]
Max dur: 30 minutes
Account: SGD

WINDOWS (SGT = UTC+8):
  London Open  15:00–19:00 SGT  (max spread 1.2 pip)
  NY Session   20:00–00:00 SGT  (max spread 1.5 pip)
"""

import os, json, time, logging, requests
from datetime import datetime, timezone
from pathlib import Path
import pytz

from signals         import SignalEngine
from oanda_trader    import OandaTrader
from telegram_alert  import TelegramAlert
from calendar_filter import EconomicCalendar as CalendarFilter

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

sg_tz   = pytz.timezone("Asia/Singapore")
signals = SignalEngine()

TRADE_SIZE   = 74000
SL_PIPS      = 13
TP_PIPS      = 26
MAX_DURATION = 30

# SGD conversion rate — update periodically or fetch live if desired
USD_SGD = 1.35

ASSETS = {
    "EUR_USD": {
        "instrument": "EUR_USD",
        "asset":      "EURUSD",
        "emoji":      "🇪🇺",
        "pip":        0.0001,
        "precision":  5,
        "stop_pips":  SL_PIPS,
        "tp_pips":    TP_PIPS,
        "sessions": [
            {"start": 15, "end": 19, "max_spread": 1.2, "label": "London"},
            {"start": 20, "end": 24, "max_spread": 1.5, "label": "NY"},
        ],
    },
}

DEFAULT_SETTINGS = {"signal_threshold": 4, "demo_mode": True}
_SETTINGS_PATH   = Path(__file__).parent / "settings.json"


def load_settings():
    try:
        with open(_SETTINGS_PATH) as f:
            DEFAULT_SETTINGS.update(json.load(f))
    except FileNotFoundError:
        with open(_SETTINGS_PATH, "w") as f:
            json.dump(DEFAULT_SETTINGS, f, indent=2)
    return DEFAULT_SETTINGS


def usd_to_sgd(usd_amount):
    return round(usd_amount * USD_SGD, 2)


def get_active_session(hour):
    cfg = ASSETS["EUR_USD"]
    for s in cfg["sessions"]:
        if s["start"] <= hour < s["end"]:
            return s
    return None


def is_in_session(hour, cfg):
    for s in cfg["sessions"]:
        if s["start"] <= hour < s["end"]:
            return True
    return False


def window_key(session_label, date_str):
    return "window_" + date_str + "_" + session_label


def set_cooldown(state, name):
    if "cooldowns" not in state:
        state["cooldowns"] = {}
    state["cooldowns"][name] = datetime.now(timezone.utc).isoformat()
    log.info(name + " cooldown 30 min")


def in_cooldown(state, name):
    cd = state.get("cooldowns", {}).get(name)
    if not cd:
        return False
    try:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(cd)).total_seconds() / 60
        return elapsed < 30
    except:
        return False


def cooldown_remaining(state, name):
    cd = state.get("cooldowns", {}).get(name)
    if not cd:
        return 0
    try:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(cd)).total_seconds() / 60
        return max(0, int(30 - elapsed))
    except:
        return "?"


def _login_fail_key(now):
    slot = now.hour * 2 + (1 if now.minute >= 30 else 0)
    return now.strftime("%Y%m%d") + "_" + str(slot)


def detect_sl_tp_hits(state, trader, alert):
    """Detect closed trades and fire TP/SL alerts with full SGD display."""
    if "open_times" not in state:
        return
    for name in list(state["open_times"].keys()):
        if trader.get_position(name):
            continue
        try:
            url  = (trader.base_url + "/v3/accounts/" + trader.account_id +
                    "/trades?state=CLOSED&instrument=" + name + "&count=1")
            data = requests.get(url, headers=trader.headers, timeout=10).json().get("trades", [])
            if data:
                trade     = data[0]
                pnl_usd   = float(trade.get("realizedPL", "0"))
                pnl_sgd   = usd_to_sgd(pnl_usd)
                open_price  = float(trade.get("price", 0))
                close_price = float(trade.get("averageClosePrice", open_price))
                balance_sgd = usd_to_sgd(trader.get_balance())
                wins   = state.get("wins", 0)
                losses = state.get("losses", 0)

                # Update daily pnl
                state["daily_pnl"] = state.get("daily_pnl", 0.0) + pnl_usd

                if pnl_usd < 0:
                    set_cooldown(state, name)
                    state["losses"]        = losses + 1
                    state["consec_losses"] = state.get("consec_losses", 0) + 1
                    alert.send_sl_hit(pnl_usd, pnl_sgd, balance_sgd,
                                      state["wins"], state["losses"],
                                      open_price, close_price)
                else:
                    state["wins"]          = wins + 1
                    state["consec_losses"] = 0
                    alert.send_tp_hit(pnl_usd, pnl_sgd, balance_sgd,
                                      state["wins"], state["losses"],
                                      open_price, close_price)
        except Exception as e:
            log.warning("SL/TP detect error " + name + ": " + str(e))
        del state["open_times"][name]


def check_session_open_alerts(state, alert, trader, now, today):
    """Send session open alert once per window per day."""
    hour = now.hour
    windows = [
        {"start": 15, "label": "London", "hours": "15:00–19:00"},
        {"start": 20, "label": "NY",     "hours": "20:00–00:00"},
    ]
    for w in windows:
        if hour == w["start"]:
            akey = "session_open_" + today + "_" + w["label"]
            if not state.get("session_alerted", {}).get(akey):
                if "session_alerted" not in state:
                    state["session_alerted"] = {}
                state["session_alerted"][akey] = True

                # Reset session stats
                state["session_trades_" + w["label"]] = 0
                state["session_pnl_" + w["label"]]    = 0.0

                try:
                    balance_usd = trader.get_balance() if trader.login() else state.get("start_balance", 0)
                except:
                    balance_usd = state.get("start_balance", 0)
                balance_sgd = usd_to_sgd(balance_usd)

                alert.send_session_open(
                    session_label=w["label"],
                    session_hours=w["hours"],
                    balance_sgd=balance_sgd,
                    trades_today=state.get("trades", 0),
                    wins=state.get("wins", 0),
                    losses=state.get("losses", 0),
                )


def check_session_close_alerts(state, alert, trader, now, today):
    """Send session close alert when a window ends."""
    hour = now.hour
    windows = [
        {"end": 19, "label": "London"},
        {"end":  0, "label": "NY"},
    ]
    for w in windows:
        # Fire at the first minute of the closing hour
        if hour == w["end"] and now.minute == 0:
            akey = "session_close_" + today + "_" + w["label"]
            if not state.get("session_alerted", {}).get(akey):
                if "session_alerted" not in state:
                    state["session_alerted"] = {}
                state["session_alerted"][akey] = True
                try:
                    balance_usd = trader.get_balance() if trader.login() else state.get("start_balance", 0)
                except:
                    balance_usd = state.get("start_balance", 0)
                balance_sgd = usd_to_sgd(balance_usd)
                session_pnl_sgd = usd_to_sgd(state.get("session_pnl_" + w["label"], 0.0))
                alert.send_session_close(
                    session_label=w["label"],
                    balance_sgd=balance_sgd,
                    session_trades=state.get("session_trades_" + w["label"], 0),
                    session_pnl_sgd=session_pnl_sgd,
                    wins=state.get("wins", 0),
                    losses=state.get("losses", 0),
                )


def run_bot(state):
    settings = load_settings()
    now      = datetime.now(sg_tz)
    hour     = now.hour
    today    = now.strftime("%Y%m%d")
    alert    = TelegramAlert()
    calendar = CalendarFilter()

    log.info("Scan at " + now.strftime("%H:%M:%S SGT"))

    # ── Session open/close alerts ──────────────────────────────────────
    trader_for_alerts = OandaTrader(demo=settings["demo_mode"])
    check_session_open_alerts(state, alert, trader_for_alerts, now, today)
    check_session_close_alerts(state, alert, trader_for_alerts, now, today)

    # ── Check active session ───────────────────────────────────────────
    session = get_active_session(hour)
    if not session:
        log.info("Outside trading windows (" + str(hour) + "h SGT) — next: 15:00 (London) or 20:00 (NY)")
        return

    log.info("Window: " + session["label"] + " | Max spread: " + str(session["max_spread"]) + " pip")

    # ── Login ──────────────────────────────────────────────────────────
    trader = OandaTrader(demo=settings["demo_mode"])
    if not trader.login():
        fail_key = _login_fail_key(now)
        if not state.get("login_fail_alerted", {}).get(fail_key):
            if "login_fail_alerted" not in state:
                state["login_fail_alerted"] = {}
            state["login_fail_alerted"][fail_key] = True
            api_key    = os.environ.get("OANDA_API_KEY", "")
            account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
            alert.send_login_fail(
                api_key_hint=api_key[:8] + "****" if api_key else "MISSING",
                account_id=account_id
            )
        else:
            log.warning("Login failed — alert already sent this 30-min window")
        return

    current_balance_usd = trader.get_balance()
    current_balance_sgd = usd_to_sgd(current_balance_usd)

    if "start_balance" not in state or state["start_balance"] == 0.0:
        state["start_balance"] = current_balance_usd

    detect_sl_tp_hits(state, trader, alert)

    # ── 30-MIN HARD CLOSE ──────────────────────────────────────────────
    for name in ASSETS:
        pos = trader.get_position(name)
        if not pos:
            continue
        try:
            trade_id, open_str = trader.get_open_trade_id(name)
            if not trade_id or not open_str:
                continue
            open_utc = datetime.fromisoformat(open_str.replace("Z", "+00:00"))
            mins     = (datetime.now(pytz.utc) - open_utc).total_seconds() / 60
            log.info(name + ": open " + str(round(mins, 1)) + " min")
            if mins >= MAX_DURATION:
                pnl_usd = trader.check_pnl(pos)
                pnl_sgd = usd_to_sgd(pnl_usd)
                trader.close_position(name)
                state.get("open_times", {}).pop(name, None)
                alert.send_timeout_close(
                    minutes=mins,
                    pnl_usd=pnl_usd,
                    pnl_sgd=pnl_sgd,
                    balance_sgd=current_balance_sgd,
                )
        except Exception as e:
            log.warning("Duration check " + name + ": " + str(e))

    # ── SCAN + TRADE ───────────────────────────────────────────────────
    threshold = settings.get("signal_threshold", 4)

    for name, cfg in ASSETS.items():

        pos = trader.get_position(name)
        if pos:
            pnl_sgd = usd_to_sgd(trader.check_pnl(pos))
            dirn    = "BUY" if int(float(pos.get("long", {}).get("units", 0))) > 0 else "SELL"
            log.info(name + ": " + dirn + " open | Unrealised SGD " + str(pnl_sgd))
            continue

        if in_cooldown(state, name):
            log.info(name + ": cooldown " + str(cooldown_remaining(state, name)) + "min")
            continue

        price, bid, ask = trader.get_price(name)
        if price is None:
            log.warning(name + ": price error")
            continue

        spread = (ask - bid) / cfg["pip"]
        if spread > session["max_spread"] + 0.05:
            log.info(name + ": spread " + str(round(spread, 2)) + "p — skip (max " + str(session["max_spread"]) + "p)")
            continue

        # News filter
        news_active, news_reason = calendar.is_news_time(name)
        if news_active:
            alert_key = name + "_news_" + now.strftime("%Y%m%d%H")
            if not state.get("news_alerted", {}).get(alert_key):
                if "news_alerted" not in state:
                    state["news_alerted"] = {}
                state["news_alerted"][alert_key] = True
                alert.send_news_block(name, news_reason)
            log.info(name + ": news — " + news_reason)
            continue

        # Signal check — returns (score, direction, details, layer_breakdown)
        result = signals.analyze(asset=cfg["asset"], state=state)
        if len(result) == 4:
            score, direction, details, layer_breakdown = result
        else:
            score, direction, details = result
            layer_breakdown = {}

        log.info(name + ": score=" + str(score) + "/" + str(threshold) +
                 " dir=" + direction + " | " + details)

        if score < threshold or direction == "NONE":
            log.info(name + ": no setup — waiting (score " + str(score) + "/" + str(threshold) + ")")
            continue

        # ── Place trade ────────────────────────────────────────────────
        sl_sgd = round(TRADE_SIZE * SL_PIPS * cfg["pip"] * USD_SGD, 2)
        tp_sgd = round(TRADE_SIZE * TP_PIPS * cfg["pip"] * USD_SGD, 2)

        result_order = trader.place_order(
            instrument=name, direction=direction, size=TRADE_SIZE,
            stop_distance=SL_PIPS, limit_distance=TP_PIPS
        )
        if result_order["success"]:
            state["trades"] = state.get("trades", 0) + 1
            if "open_times" not in state:
                state["open_times"] = {}
            state["open_times"][name] = now.isoformat()

            # Track session-level trades
            sess_key = "session_trades_" + session["label"]
            state[sess_key] = state.get(sess_key, 0) + 1

            price_now, _, _ = trader.get_price(name)
            entry_price = price_now if price_now else price

            alert.send_trade_open(
                direction=direction,
                entry_price=entry_price,
                sl_pips=SL_PIPS,
                tp_pips=TP_PIPS,
                sl_sgd=sl_sgd,
                tp_sgd=tp_sgd,
                spread=spread,
                score=score,
                session_label=session["label"],
                layer_breakdown=layer_breakdown,
                balance_sgd=current_balance_sgd,
                trades_today=state["trades"],
            )
            log.info(name + ": PLACED " + direction + " SL=SGD" + str(sl_sgd) + " TP=SGD" + str(tp_sgd))
        else:
            set_cooldown(state, name)
            log.warning(name + ": order failed — " + str(result_order.get("error", "")))

    log.info("Scan complete.")
