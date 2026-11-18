
import os
import time
import json
import base64
import hashlib
import logging
import requests
import pandas as pd

from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_CEILING
from datetime import datetime, timedelta, time as dt_time
from urllib.parse import quote

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ============================================================
# SETTINGS
# ============================================================

FINAM_SECRET = os.getenv("FINAM_API_SECRET")
ACCOUNT_ID = os.getenv("FINAM_ACCOUNT_ID")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CSV_FILE = "moex_signals.csv"
SIGNAL_STATE_FILE = "finam_signal_state.json"
GITHUB_API = "https://api.github.com"
MIC = "MISX"

# True = минимальный допустимый торговый лот каждого инструмента.
# False = использовать qty из CSV, считая его количеством акций.
TEST_MODE_MIN_VOLUME = True

# Жёсткий лимит открытых позиций, включая теоретические позиции по активным заявкам.
MAX_OPEN_POSITIONS = 10

# Live test guard: no more than one new broker order per manual invocation.
MAX_NEW_ORDERS_PER_RUN = 1


def can_submit_live_order(submitted_count):
    return submitted_count < MAX_NEW_ORDERS_PER_RUN

# По умолчанию безопасный режим: только проверка, без реальных заявок.
# Для реальной торговли установить FINAM_DRY_RUN=false в GitHub Secrets/Variables.
def parse_dry_run(value):
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "да"):
        return True
    if normalized in ("0", "false", "no", "нет"):
        return False
    raise RuntimeError(
        "Некорректный FINAM_DRY_RUN. Допустимы true/false; "
        "при ошибке торговля запрещается."
    )


DRY_RUN = parse_dry_run(os.getenv("FINAM_DRY_RUN", "true"))

BASE_URL = "https://api.finam.ru"
REQUEST_TIMEOUT = 20
REQUEST_PAUSE = 0.5
TRADE_RECONCILE_ATTEMPTS = 10
TRADE_RECONCILE_PAUSE = 1

# ============================================================
# SECTORS
# ============================================================

SECTOR_GROUPS = {
    "SBER": "BANKS",
    "SBERP": "BANKS",
    "VTBR": "BANKS",
    "MOEX": "BANKS",
    "SVCB": "BANKS",

    "GAZP": "OIL",
    "ROSN": "OIL",
    "LKOH": "OIL",
    "NVTK": "OIL",
    "TATN": "OIL",
    "SNGS": "OIL",
    "SNGSP": "OIL",

    "GMKN": "METALS",
    "NLMK": "METALS",
    "CHMF": "METALS",
    "MAGN": "METALS",
    "RUAL": "METALS",
    "ALRS": "METALS",
    "PLZL": "METALS",

    "YDEX": "TECH",
    "VKCO": "TECH",
    "OZON": "TECH",
    "HEAD": "TECH",
}

# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()


def auth_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }


def api_get(url, token, params=None):
    response = SESSION.get(
        url,
        headers=auth_headers(token),
        params=params,
        timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def api_post(url, token, payload):
    response = SESSION.post(
        url,
        headers=auth_headers(token),
        json=payload,
        timeout=REQUEST_TIMEOUT
    )
    return response


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        url = (
            f"https://api.telegram.org/"
            f"bot{TELEGRAM_TOKEN}/sendMessage"
        )

        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            },
            timeout=10
        )

        if not response.ok:
            logging.error(
                "Telegram error: %s",
                response.text
            )

    except Exception as exc:
        logging.error("Telegram error: %s", exc)


# ============================================================
# AUTHENTICATION
# ============================================================

def get_jwt_token():
    if not FINAM_SECRET:
        raise RuntimeError("FINAM_API_SECRET не задан")

    if not ACCOUNT_ID:
        raise RuntimeError("FINAM_ACCOUNT_ID не задан")

    response = SESSION.post(
        f"{BASE_URL}/v1/sessions",
        json={"secret": FINAM_SECRET},
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    token = response.json().get("token")

    if not token:
        raise RuntimeError("Finam не вернул JWT token")

    return token


# ============================================================
# ACCOUNT
# ============================================================

def get_account_info(token):
    data = api_get(
        f"{BASE_URL}/v1/accounts/{quote(ACCOUNT_ID, safe='')}",
        token
    )

    available_cash = (
        data.get("portfolio_mc", {})
        .get("available_cash", {})
        .get("value", "0")
    )

    return data, Decimal(str(available_cash))


def get_active_order_symbols(token):
    """
    Return symbols reserved by non-terminal account orders.
    Unknown statuses are treated as active (fail closed).
    """
    data = api_get(
        f"{BASE_URL}/v1/accounts/{quote(ACCOUNT_ID, safe='')}/orders",
        token
    )
    if not isinstance(data, dict) or not isinstance(data.get("orders"), list):
        raise RuntimeError("Finam вернул некорректный список активных заявок")

    terminal = {
        "FILLED", "EXECUTED", "CANCELED", "CANCELLED",
        "REJECTED", "REJECTED_BY_EXCHANGE", "DENIED_BY_BROKER",
        "EXPIRED", "FAILED", "DONE_FOR_DAY", "REPLACED"
    }
    symbols = set()
    for item in data["orders"]:
        if not isinstance(item, dict):
            raise RuntimeError("Finam вернул некорректную запись заявки")
        status = _normalized_order_status(item)
        if status in terminal and not item.get("triggered_order_id"):
            continue
        order = item.get("order") or {}
        sltp = item.get("sltp_order") or {}
        symbol = (
            order.get("symbol")
            or sltp.get("symbol")
            or item.get("symbol")
        )
        if not symbol:
            raise RuntimeError(
                "Finam вернул активную заявку без символа; новые заявки запрещены"
            )
        symbols.add(str(symbol).split("@")[0].upper())
    return symbols


# ============================================================
# INSTRUMENT PARAMETERS
# ============================================================

def get_trade_parameters(token, ticker, direction=None):
    """
    Получает параметры инструмента для конкретного счёта.

    ВАЖНО:
    trade_lot_size используется для расчёта количества акций.
    lot_size из общего описания инструмента не подменяет
    торговый размер лота счёта.
    """

    symbol = f"{ticker}@{MIC}"
    encoded_symbol = quote(symbol, safe="")

    url = (
        f"{BASE_URL}/v1/assets/"
        f"{encoded_symbol}/params"
    )

    data = api_get(
        url,
        token,
        params={"account_id": ACCOUNT_ID}
    )

    if not isinstance(data, dict):
        raise ValueError("Некорректный ответ параметров инструмента")

    if data.get("is_tradable") is not True:
        raise ValueError(
            f"{ticker}: инструмент недоступен для торговли "
            f"(is_tradable={data.get('is_tradable')})"
        )

    if direction in ("LONG", "SHORT"):
        permission = data.get("longable" if direction == "LONG" else "shortable")
        permission_value = (
            permission.get("value") if isinstance(permission, dict) else permission
        )
        allowed = (
            {"AVAILABLE", "1", 1}
            if direction == "LONG"
            else {"AVAILABLE", "AVAILABLE_STRATEGY", "1", "4", 1, 4}
        )
        if permission_value not in allowed:
            raise ValueError(
                f"{ticker}: Finam не подтвердил доступность {direction}; "
                f"permission={permission_value}"
            )

    raw_trade_lot = data.get("trade_lot_size")

    if raw_trade_lot is None:
        raise ValueError(
            f"{ticker}: отсутствует trade_lot_size"
        )

    try:
        trade_lot_size = Decimal(str(raw_trade_lot))
    except InvalidOperation:
        raise ValueError(
            f"{ticker}: некорректный trade_lot_size={raw_trade_lot}"
        )

    if not trade_lot_size.is_finite():
        raise ValueError(
            f"{ticker}: trade_lot_size не является конечным числом"
        )

    if trade_lot_size <= 0:
        raise ValueError(
            f"{ticker}: недопустимый trade_lot_size={trade_lot_size}"
        )

    if trade_lot_size != trade_lot_size.to_integral_value():
        raise ValueError(
            f"{ticker}: дробный trade_lot_size={trade_lot_size}"
        )

    return int(trade_lot_size)


def round_price_to_tick(token, ticker, price, rounding):
    """
    Round a protective price to the instrument's actual Finam tick size.
    GetAsset supplies decimals/min_step or a price-dependent price_step.
    Fail closed if the broker does not return valid tick metadata.
    """
    symbol = f"{ticker}@{MIC}"
    data = api_get(
        f"{BASE_URL}/v1/assets/{quote(symbol, safe='')}",
        token,
        params={"account_id": ACCOUNT_ID}
    )
    if not isinstance(data, dict):
        raise OrderProtectionError(f"{ticker}: некорректные параметры шага цены")

    try:
        decimals = int(data.get("decimals"))
        min_step = Decimal(str(data.get("min_step", "0")))
    except (TypeError, ValueError, InvalidOperation):
        raise OrderProtectionError(f"{ticker}: отсутствуют decimals/min_step")

    if decimals < 0 or not min_step.is_finite() or min_step < 0:
        raise OrderProtectionError(f"{ticker}: некорректные decimals/min_step")

    if min_step > 0:
        tick = min_step / (Decimal(10) ** decimals)
    else:
        price_step = data.get("price_step")
        if not isinstance(price_step, dict):
            raise OrderProtectionError(f"{ticker}: Finam не вернул price_step")
        threshold = _decimal_value(
            price_step.get("threshold_price"), "price_step.threshold_price"
        )
        candidate = (
            price_step.get("step")
            if Decimal(str(price)) < threshold
            else price_step.get("step_from_threshold")
        )
        tick = _decimal_value(candidate, "price_step.step")
    if not tick.is_finite() or tick <= 0:
        raise OrderProtectionError(f"{ticker}: недопустимый шаг цены {tick}")

    price_decimal = Decimal(str(price))
    ticks = (price_decimal / tick).to_integral_value(rounding=rounding)
    return ticks * tick


# ============================================================
# QUANTITY VALIDATION
# ============================================================

def calculate_order_quantity(ticker, row_qty, trade_lot_size):
    """
    Возвращает количество акций, а не количество лотов.

    TEST_MODE_MIN_VOLUME=True:
        один минимальный торговый лот.

    TEST_MODE_MIN_VOLUME=False:
        row_qty трактуется как количество акций;
        количество округляется вниз до полного торгового лота.
    """

    if trade_lot_size <= 0:
        raise ValueError(
            f"{ticker}: размер лота должен быть больше нуля"
        )

    if TEST_MODE_MIN_VOLUME:
        quantity = trade_lot_size

    else:
        try:
            requested = Decimal(str(row_qty))
        except (InvalidOperation, TypeError):
            raise ValueError(
                f"{ticker}: некорректное qty в CSV: {row_qty}"
            )

        if not requested.is_finite() or requested <= 0:
            raise ValueError(
                f"{ticker}: qty должно быть положительным числом"
            )

        # Количество акций округляется вниз до полного лота.
        lots = int(requested // Decimal(trade_lot_size))
        quantity = lots * trade_lot_size

    if quantity <= 0:
        raise ValueError(
            f"{ticker}: итоговое количество равно нулю"
        )

    if quantity % trade_lot_size != 0:
        raise ValueError(
            f"{ticker}: количество {quantity} "
            f"не кратно торговому лоту {trade_lot_size}"
        )

    if not isinstance(quantity, int):
        raise ValueError(
            f"{ticker}: количество должно быть целым числом"
        )

    logging.info(
        "%s: trade_lot_size=%s, quantity=%s акций",
        ticker,
        trade_lot_size,
        quantity
    )

    return quantity


# ============================================================
# MARKET ORDER + EXECUTION RECONCILIATION
# ============================================================

class OrderSubmissionUnknown(RuntimeError):
    """POST мог быть принят брокером, но ответ не получен. Повтор запрещён."""


class OrderProtectionError(RuntimeError):
    """Нельзя достоверно подтвердить исполнение или защитить позицию."""


def _decimal_value(value, field_name):
    if isinstance(value, dict):
        value = value.get("value")
    if value is None:
        raise OrderProtectionError(f"В ответе Finam отсутствует {field_name}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise OrderProtectionError(f"Некорректное значение {field_name}: {value}")
    if not result.is_finite():
        raise OrderProtectionError(f"Неконечное значение {field_name}: {value}")
    return result


def get_open_position_symbols(account_data):
    """
    Return only symbols with a non-zero signed position quantity.

    Finam's account response may include position records with zero quantity.
    Counting every record that has a symbol incorrectly blocks fresh signals
    after a position has been closed. Missing or malformed quantities fail
    closed so an incomplete broker response cannot enable a new order.
    """
    positions = account_data.get("positions", [])
    if not isinstance(positions, list):
        raise RuntimeError("Finam вернул некорректный список позиций")

    symbols = set()
    for position in positions:
        if not isinstance(position, dict):
            raise RuntimeError("Finam вернул некорректную запись позиции")
        symbol = position.get("symbol")
        if not symbol:
            raise RuntimeError(
                "Finam вернул позицию без symbol; новые заявки запрещены"
            )
        quantity = _decimal_value(
            position.get("quantity"), "positions[].quantity"
        )
        if quantity == 0:
            continue
        symbols.add(str(symbol).split("@")[0].upper())
    return symbols


def find_order_by_client_id(token, client_order_id):
    """Try to reconcile an ambiguous POST using the broker's order list."""
    data = api_get(
        f"{BASE_URL}/v1/accounts/{quote(ACCOUNT_ID, safe='')}/orders",
        token
    )
    orders = data.get("orders", []) if isinstance(data, dict) else []
    matches = [
        order for order in orders
        if str(
            order.get("client_order_id")
            or (order.get("order") or {}).get("client_order_id")
            or (order.get("sltp_order") or {}).get("client_order_id", "")
        ) == client_order_id
    ]
    if len(matches) > 1:
        raise OrderProtectionError(
            f"Найдено несколько заявок с client_order_id={client_order_id}"
        )
    if not matches:
        return None
    order_id = matches[0].get("order_id")
    if not order_id:
        raise OrderProtectionError(
            f"Найдена заявка {client_order_id} без order_id"
        )
    return str(order_id)


def place_market_order(token, symbol, quantity, side):
    if not isinstance(quantity, int) or quantity <= 0:
        raise ValueError(f"Недопустимое количество: {quantity}")

    client_order_id = __import__("uuid").uuid4().hex[:20]
    payload = {
        "symbol": symbol,
        "quantity": {"value": str(quantity)},
        "side": side,
        "type": "ORDER_TYPE_MARKET",
        "client_order_id": client_order_id
    }

    if DRY_RUN:
        logging.warning(
            "[DRY RUN] Рыночная заявка НЕ отправлена: %s %s %s шт.",
            side, symbol, quantity
        )
        return {"dry_run": True, "client_order_id": client_order_id}

    try:
        response = api_post(
            f"{BASE_URL}/v1/accounts/{quote(ACCOUNT_ID, safe='')}/orders",
            token,
            payload
        )
    except requests.RequestException as exc:
        # POST мог дойти до брокера. Сначала сверяем список заявок,
        # но никогда не отправляем повторный POST.
        try:
            reconciled_order_id = find_order_by_client_id(
                token, client_order_id
            )
        except Exception as reconcile_exc:
            raise OrderSubmissionUnknown(
                f"Не удалось сверить отправку {symbol}; "
                f"client_order_id={client_order_id}. Повтор запрещён. "
                f"POST error={exc}; reconcile error={reconcile_exc}"
            ) from exc
        if not reconciled_order_id:
            raise OrderSubmissionUnknown(
                f"Заявка {symbol} не найдена при сверке после сетевой ошибки; "
                f"client_order_id={client_order_id}. Результат всё ещё "
                "неизвестен, повтор запрещён."
            ) from exc
        logging.warning(
            "POST ответ потерян, но заявка найдена сверкой: %s",
            reconciled_order_id
        )
        return {
            "order_id": reconciled_order_id,
            "client_order_id": client_order_id,
            "submitted_at": datetime.utcnow()
        }

    if response.status_code not in (200, 201):
        # 5xx/408 may be returned after the broker accepted the order.
        # Reconcile by client_order_id; never retry the POST blindly.
        if response.status_code >= 500 or response.status_code == 408:
            try:
                reconciled_order_id = find_order_by_client_id(
                    token, client_order_id
                )
            except Exception as reconcile_exc:
                raise OrderSubmissionUnknown(
                    f"Не удалось сверить HTTP {response.status_code} для "
                    f"{symbol}; client_order_id={client_order_id}. "
                    f"Повтор запрещён: {reconcile_exc}"
                )
            if reconciled_order_id:
                return {
                    "order_id": reconciled_order_id,
                    "client_order_id": client_order_id,
                    "submitted_at": datetime.utcnow()
                }
            raise OrderSubmissionUnknown(
                f"HTTP {response.status_code} для {symbol}; результат "
                f"неоднозначен, client_order_id={client_order_id}. "
                "Повтор запрещён."
            )
        logging.error("Finam order rejected HTTP %s: %s",
                      response.status_code, response.text)
        raise OrderProtectionError(
            f"Finam отклонил заявку {symbol}: HTTP {response.status_code}"
        )

    try:
        data = response.json()
    except ValueError:
        data = {}

    order_id = data.get("order_id") if isinstance(data, dict) else None
    if not order_id:
        try:
            order_id = find_order_by_client_id(token, client_order_id)
        except Exception as reconcile_exc:
            raise OrderSubmissionUnknown(
                f"Finam не вернул order_id для {symbol}; "
                f"client_order_id={client_order_id}; сверка не удалась: "
                f"{reconcile_exc}. Повтор запрещён."
            )
        if not order_id:
            raise OrderSubmissionUnknown(
                f"Finam не вернул order_id для {symbol}; "
                f"client_order_id={client_order_id}. Заявка не найдена "
                "при сверке, повтор запрещён."
            )

    logging.info("Заявка принята: %s order_id=%s client_order_id=%s",
                 symbol, order_id, client_order_id)
    return {
        "order_id": str(order_id),
        "client_order_id": client_order_id,
        "submitted_at": datetime.utcnow()
    }


def get_order_state(token, order_id):
    return api_get(
        f"{BASE_URL}/v1/accounts/{quote(ACCOUNT_ID, safe='')}/orders/"
        f"{quote(str(order_id), safe='')}",
        token
    )


def cancel_order_remainder(token, order_id):
    url = (
        f"{BASE_URL}/v1/accounts/{quote(ACCOUNT_ID, safe='')}/orders/"
        f"{quote(str(order_id), safe='')}"
    )
    response = SESSION.delete(url, headers=auth_headers(token),
                              timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response


def _normalized_order_status(state):
    """Normalize Finam enum strings such as ORDER_STATUS_FILLED."""
    return str((state or {}).get("status", "")).removeprefix("ORDER_STATUS_")


def wait_for_terminal_order(token, order_id, timeout_seconds=25):
    # These states mean the exchange order will no longer execute further.
    terminal = {
        "FILLED", "EXECUTED", "CANCELED", "REJECTED",
        "REJECTED_BY_EXCHANGE", "DENIED_BY_BROKER",
        "EXPIRED", "FAILED", "DONE_FOR_DAY", "REPLACED", "CANCELLED"
    }
    deadline = time.monotonic() + timeout_seconds
    state = None

    while time.monotonic() < deadline:
        state = get_order_state(token, order_id)
        if _normalized_order_status(state) in terminal:
            return state
        time.sleep(1)

    if state is None:
        raise OrderProtectionError(f"Не удалось получить состояние {order_id}")

    remaining = _decimal_value(state.get("remaining_quantity"), "remaining_quantity")
    if remaining > 0:
        logging.warning("Отменяю неисполненный остаток заявки %s: %s",
                        order_id, remaining)
        try:
            cancel_order_remainder(token, order_id)
        except requests.RequestException as cancel_exc:
            # Cancellation may have reached the broker even if its response
            # was lost. Re-read state before deciding the order is unresolved.
            try:
                state = get_order_state(token, order_id)
            except Exception as state_exc:
                raise OrderProtectionError(
                    f"Не удалось подтвердить отмену остатка {order_id}: "
                    f"{cancel_exc}; повторная проверка: {state_exc}"
                ) from cancel_exc
            if _normalized_order_status(state) in terminal:
                return state
            logging.warning(
                "Ответ отмены не получен, заявка %s ещё не терминальная; "
                "продолжаю сверку.",
                order_id
            )

    # После отмены обязательно повторно сверяем состояние.
    for _ in range(10):
        state = get_order_state(token, order_id)
        if _normalized_order_status(state) in terminal:
            return state
        time.sleep(1)

    raise OrderProtectionError(
        f"Не удалось подтвердить конечный статус заявки {order_id}"
    )


def get_weighted_average_fill(token, order_id, submitted_at, expected_quantity):
    start_time = (
        submitted_at - timedelta(minutes=2)
    ).isoformat(timespec="seconds") + "Z"
    total_qty = Decimal("0")
    total_value = Decimal("0")
    last_error = None

    # Finam trade history may lag behind the terminal order state.
    # Poll read-only history instead of declaring an execution mismatch
    # after a single immediately-following request.
    for attempt in range(TRADE_RECONCILE_ATTEMPTS):
        end_time = (
            datetime.utcnow() + timedelta(minutes=1)
        ).isoformat(timespec="seconds") + "Z"
        try:
            data = api_get(
                f"{BASE_URL}/v1/accounts/{quote(ACCOUNT_ID, safe='')}/trades",
                token,
                params={
                    "limit": 500,
                    "interval.start_time": start_time,
                    "interval.end_time": end_time
                }
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < TRADE_RECONCILE_ATTEMPTS:
                time.sleep(TRADE_RECONCILE_PAUSE)
                continue
            raise OrderProtectionError(
                f"Не удалось получить историю сделок по заявке {order_id}; "
                "исполнение не сверено, SL/TP не выставлены."
            ) from exc

        trades = data.get("trades", []) if isinstance(data, dict) else []
        matched = [
            trade for trade in trades
            if str(trade.get("order_id")) == str(order_id)
        ]
        total_qty = Decimal("0")
        total_value = Decimal("0")
        for trade in matched:
            size = _decimal_value(trade.get("size"), "trade.size")
            price = _decimal_value(trade.get("price"), "trade.price")
            if size <= 0 or price <= 0:
                continue
            total_qty += size
            total_value += size * price

        if total_qty == expected_quantity:
            if total_qty <= 0 or total_value <= 0:
                raise OrderProtectionError(
                    f"Некорректная история сделок по заявке {order_id}."
                )
            return total_qty, total_value / total_qty

        if total_qty > expected_quantity:
            raise OrderProtectionError(
                f"История сделок по {order_id} подтверждает {total_qty} шт., "
                f"что больше объёма исполнения заявки {expected_quantity}. "
                "SL/TP не выставлены: требуется ручная сверка."
            )

        if attempt + 1 < TRADE_RECONCILE_ATTEMPTS:
            time.sleep(TRADE_RECONCILE_PAUSE)

    detail = f"последний объём в истории {total_qty} шт."
    if last_error:
        detail += f"; последняя ошибка {type(last_error).__name__}"
    raise OrderProtectionError(
        f"Сделки по {order_id} не подтверждают исполненный объём "
        f"{expected_quantity} шт. за {TRADE_RECONCILE_ATTEMPTS} попыток "
        f"({detail}). SL/TP не выставлены: требуется ручная сверка."
    )

# ============================================================
# SL / TP
# ============================================================

def place_sltp_order(
    token, symbol, quantity, position_direction, sl_price, tp_price
):
    if not isinstance(quantity, int) or quantity <= 0:
        raise ValueError(f"Некорректное количество SL/TP: {quantity}")

    exit_side = "SIDE_SELL" if position_direction == "LONG" else "SIDE_BUY"
    client_order_id = __import__("uuid").uuid4().hex[:20]
    payload = {
        "symbol": symbol,
        "side": exit_side,
        "quantity_sl": {"value": str(quantity)},
        "sl_price": {"value": str(sl_price)},
        "quantity_tp": {"value": str(quantity)},
        "tp_price": {"value": str(tp_price)},
        "sl_qty_measure": "SLTP_QTY_MEASURE_VALUE",
        "tp_qty_measure": "SLTP_QTY_MEASURE_VALUE",
        "client_order_id": client_order_id
    }

    if DRY_RUN:
        logging.warning("[DRY RUN] SL/TP не отправлены: %s SL=%s TP=%s",
                        symbol, sl_price, tp_price)
        return True

    def reconcile_sltp_order():
        last_error = None
        for attempt in range(5):
            try:
                reconciled_id = find_order_by_client_id(token, client_order_id)
                if reconciled_id:
                    logging.warning(
                        "%s: неоднозначный ответ SL/TP сверен по client_order_id",
                        symbol
                    )
                    return reconciled_id
            except requests.RequestException as exc:
                last_error = exc
            if attempt < 4:
                time.sleep(1)
        detail = f"; последняя ошибка сверки: {type(last_error).__name__}" if last_error else ""
        raise OrderProtectionError(
            f"{symbol}: результат отправки SL/TP неизвестен "
            f"(client_order_id={client_order_id}); повтор запрещён{detail}. "
            "Позиция может оставаться без защиты."
        )

    try:
        response = api_post(
            f"{BASE_URL}/v1/accounts/{quote(ACCOUNT_ID, safe='')}/sltp-orders",
            token,
            payload
        )
    except requests.RequestException:
        order_id = reconcile_sltp_order()
    else:
        if response.status_code not in (200, 201):
            if response.status_code >= 500 or response.status_code == 408:
                order_id = reconcile_sltp_order()
            else:
                logging.critical("Ошибка SL/TP %s: HTTP %s: %s",
                                 symbol, response.status_code, response.text)
                return False
        else:
            try:
                data = response.json()
            except (ValueError, AttributeError):
                data = {}
            order_id = data.get("order_id") if isinstance(data, dict) else None
            if not order_id:
                order_id = reconcile_sltp_order()

    # Always read the broker's authoritative order state, including after
    # reconciliation of an ambiguous POST response.
    readback = None
    active_statuses = {"NEW", "WAIT", "WATCHING", "FORWARDING", "LINK_WAIT"}
    pending_statuses = {"PENDING_NEW"}
    rejected_statuses = {
        "REJECTED", "REJECTED_BY_EXCHANGE", "DENIED_BY_BROKER",
        "FAILED", "EXPIRED", "CANCELED", "CANCELLED", "DISABLED",
        "EXECUTED", "FILLED", "SL_EXECUTED", "TP_EXECUTED",
        "SL_GUARD_TIME", "TP_GUARD_TIME", "SL_FORWARDING",
        "TP_FORWARDING", "TP_CORRECTION", "TP_CORR_GUARD_TIME"
    }
    for attempt in range(5):
        try:
            readback = get_order_state(token, order_id)
        except requests.RequestException as exc:
            if attempt == 4:
                raise OrderProtectionError(
                    f"{symbol}: не удалось прочитать SL/TP заявку {order_id}. "
                    "Позиция может оставаться без защиты."
                ) from exc
            time.sleep(1)
            continue

        if not isinstance(readback, dict):
            readback = None
            time.sleep(1)
            continue

        readback_status = _normalized_order_status(readback)
        if readback_status in active_statuses:
            break
        if readback_status in rejected_statuses:
            raise OrderProtectionError(
                f"{symbol}: SL/TP заявка {order_id} имеет статус "
                f"{readback.get('status')}."
            )
        if readback_status in pending_statuses:
            time.sleep(1)
            continue
        raise OrderProtectionError(
            f"{symbol}: неизвестный/неактивный статус SL/TP после "
            f"повторного чтения: {readback.get('status')}."
        )
    else:
        raise OrderProtectionError(
            f"{symbol}: Finam не подтвердил активное состояние SL/TP "
            f"заявки {order_id}."
        )

    if readback.get("order_id") != order_id:
        raise OrderProtectionError(
            f"{symbol}: order_id SL/TP не совпал при повторном чтении."
        )
    if readback.get("triggered_order_id"):
        raise OrderProtectionError(
            f"{symbol}: SL/TP уже сработал; требуется сверка позиции "
            "и дочерней заявки."
        )

    readback_sltp = readback.get("sltp_order")
    if not isinstance(readback_sltp, dict):
        raise OrderProtectionError(
            f"{symbol}: повторное чтение не содержит sltp_order."
        )
    if readback_sltp.get("symbol") != symbol:
        raise OrderProtectionError(
            f"{symbol}: символ SL/TP не совпал при повторном чтении."
        )
    if readback_sltp.get("side") != exit_side:
        raise OrderProtectionError(
            f"{symbol}: сторона SL/TP не совпала при повторном чтении."
        )

    expected_fields = {
        "quantity_sl": Decimal(str(quantity)),
        "quantity_tp": Decimal(str(quantity)),
        "sl_price": Decimal(str(sl_price)),
        "tp_price": Decimal(str(tp_price))
    }
    for field, expected in expected_fields.items():
        actual = _decimal_value(
            readback_sltp.get(field), f"readback.sltp_order.{field}"
        )
        if actual != expected:
            raise OrderProtectionError(
                f"{symbol}: параметры {field} в SL/TP read-back "
                f"не совпадают: {actual}, ожидалось {expected}."
            )

    logging.info(
        "%s: SL/TP подтверждены чтением, order_id=%s, quantity=%s",
        symbol, order_id, quantity
    )
    return True


# ============================================================
# CSV SIGNALS
# ============================================================

def load_active_signals():
    if not os.path.exists(CSV_FILE):
        logging.warning("%s не найден", CSV_FILE)
        return pd.DataFrame()

    df = pd.read_csv(CSV_FILE)

    required_columns = {
        "ticker",
        "direction",
        "strategy",
        "date",
        "entry_price",
        "qty",
        "h1_confirmed"
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            f"В CSV отсутствуют обязательные столбцы: {missing}"
        )

    confirmed = (
        df["h1_confirmed"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(["true", "1", "yes", "да"])
    )

    qty = pd.to_numeric(df["qty"], errors="coerce")

    df = df.copy()
    df["_confirmed"] = confirmed
    df["_qty_numeric"] = qty

    active = df[
        df["_confirmed"]
        & (df["_qty_numeric"] > 0)
    ].copy()

    return active


def position_limit_reached(open_symbols, ticker):
    """Block a new symbol when the live account already has MAX_OPEN_POSITIONS."""
    return ticker not in open_symbols and len(open_symbols) >= MAX_OPEN_POSITIONS

def signal_fingerprint(row):
    """Stable identity for one scanner signal; independent of CSV row order."""
    required = ("ticker", "direction", "strategy", "date", "entry_price")
    missing = [name for name in required if name not in row or pd.isna(row[name])]
    if missing:
        raise ValueError(
            "Нельзя безопасно идентифицировать сигнал; отсутствуют поля: "
            + ", ".join(missing)
        )
    ticker = str(row["ticker"]).strip().upper()
    direction = str(row["direction"]).strip().upper()
    strategy = str(row["strategy"]).strip()
    signal_date = str(row["date"]).strip()
    price = Decimal(str(row["entry_price"])).normalize()
    if not ticker or direction not in ("LONG", "SHORT") or not strategy or not signal_date:
        raise ValueError("Некорректные поля идентификатора сигнала")
    raw = "|".join((ticker, direction, strategy, signal_date, format(price, "f")))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _github_state_request(method, payload=None):
    token = os.getenv("GITHUB_TOKEN")
    repository = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("FINAM_STATE_BRANCH") or os.getenv("GITHUB_REF_NAME", "main")
    if not token or not repository:
        raise RuntimeError(
            "Для постоянной защиты от повторных сделок нужны GITHUB_TOKEN "
            "и GITHUB_REPOSITORY; новая заявка запрещена."
        )
    url = f"{GITHUB_API}/repos/{repository}/contents/{SIGNAL_STATE_FILE}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    response = requests.request(
        method, url, headers=headers, json=payload, params={"ref": branch},
        timeout=REQUEST_TIMEOUT
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Не удалось сохранить постоянный журнал сигналов "
            f"(GitHub HTTP {response.status_code}); торговля остановлена."
        )
    return response.json()


def load_signal_state():
    # In live mode, the durable GitHub file is authoritative. Never fall back
    # to an ephemeral runner file if the remote journal cannot be read.
    if DRY_RUN:
        if not os.path.exists(SIGNAL_STATE_FILE):
            return {}
        with open(SIGNAL_STATE_FILE, "r", encoding="utf-8") as stream:
            state = json.load(stream)
        if not isinstance(state, dict):
            raise RuntimeError("Локальный журнал сигналов повреждён")
        return state

    token = os.getenv("GITHUB_TOKEN")
    repository = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("FINAM_STATE_BRANCH") or os.getenv("GITHUB_REF_NAME", "main")
    if not token or not repository:
        raise RuntimeError("Нет доступа к постоянному журналу сигналов")
    url = f"{GITHUB_API}/repos/{repository}/contents/{SIGNAL_STATE_FILE}"
    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        },
        params={"ref": branch},
        timeout=REQUEST_TIMEOUT
    )
    if response.status_code == 404:
        return {}
    if response.status_code != 200:
        raise RuntimeError(
            f"Не удалось прочитать журнал сигналов (GitHub HTTP "
            f"{response.status_code}); торговля остановлена."
        )
    try:
        decoded = base64.b64decode(response.json()["content"]).decode("utf-8")
        state = json.loads(decoded)
    except Exception as exc:
        raise RuntimeError("Постоянный журнал сигналов повреждён") from exc
    if not isinstance(state, dict):
        raise RuntimeError("Постоянный журнал сигналов имеет неверный формат")
    return state


def save_signal_state(state):
    if DRY_RUN:
        with open(SIGNAL_STATE_FILE, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2, sort_keys=True)
        return

    token = os.getenv("GITHUB_TOKEN")
    repository = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("FINAM_STATE_BRANCH") or os.getenv("GITHUB_REF_NAME", "main")
    if not token or not repository:
        raise RuntimeError("Нет доступа к постоянному журналу сигналов")
    url = f"{GITHUB_API}/repos/{repository}/contents/{SIGNAL_STATE_FILE}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    current = requests.get(
        url, headers=headers, params={"ref": branch}, timeout=REQUEST_TIMEOUT
    )
    sha = None
    if current.status_code == 200:
        sha = current.json().get("sha")
    elif current.status_code != 404:
        raise RuntimeError(
            f"Не удалось проверить версию журнала сигналов "
            f"(GitHub HTTP {current.status_code})"
        )
    content = base64.b64encode(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    ).decode("ascii")
    payload = {
        "message": "chore: persist Finam processed signal state",
        "content": content,
        "branch": branch
    }
    if sha:
        payload["sha"] = sha
    saved = requests.put(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    if saved.status_code not in (200, 201):
        raise RuntimeError(
            f"Не удалось зафиксировать журнал сигналов "
            f"(GitHub HTTP {saved.status_code}); заявка не отправляется."
        )


def reserve_signal(state, signal_id, ticker, direction):
    if signal_id in state:
        return False
    # Reserve BEFORE market-order POST. A crash/timeout leaves the signal
    # blocked until an operator reconciles it, preventing duplicate entries.
    state[signal_id] = {
        "ticker": ticker,
        "direction": direction,
        "status": "SUBMISSION_ATTEMPTED",
        "updated_at": datetime.utcnow().isoformat() + "Z"
    }
    save_signal_state(state)
    return True


def update_signal_state(state, signal_id, status, **details):
    if signal_id not in state:
        raise RuntimeError("Попытка обновить незарезервированный сигнал")
    state[signal_id].update(details)
    state[signal_id]["status"] = status
    state[signal_id]["updated_at"] = datetime.utcnow().isoformat() + "Z"
    save_signal_state(state)



# ============================================================
# MAIN
# ============================================================

def main():
    now_msk = datetime.utcnow() + timedelta(hours=3)
    current_time = now_msk.time()
    is_weekend = now_msk.weekday() >= 5

    if is_weekend:
        if not (dt_time(9, 50) <= current_time <= dt_time(19, 0)):
            logging.info("Выходной: вне рабочего окна")
            return
    else:
        if not (dt_time(6, 50) <= current_time <= dt_time(23, 50)):
            logging.info("Вне рабочего окна")
            return

    if DRY_RUN:
        logging.warning(
            "ВНИМАНИЕ: FINAM_DRY_RUN включён. "
            "Реальные заявки отправляться не будут."
        )

    token = get_jwt_token()

    account_data, available_cash = get_account_info(token)

    logging.info("Свободные средства получены (значение скрыто)")

    open_symbols = get_open_position_symbols(account_data)

    # Pending orders reserve a slot too. If Finam cannot provide this list,
    # abort this run rather than risk exceeding the account position cap.
    open_symbols.update(get_active_order_symbols(token))

    busy_sectors = set()

    for ticker in open_symbols:
        sector = SECTOR_GROUPS.get(ticker)
        if sector:
            busy_sectors.add(sector)

    logging.info("Открытых инструментов: %s", len(open_symbols))
    logging.info(
        "Открытых позиций: %s/%s",
        len(open_symbols), MAX_OPEN_POSITIONS
    )
    logging.info("Занятых секторов: %s", len(busy_sectors))

    if len(open_symbols) >= MAX_OPEN_POSITIONS:
        logging.warning(
            "Достигнут лимит открытых позиций (%s). Новые заявки запрещены.",
            MAX_OPEN_POSITIONS
        )
        return

    df_active = load_active_signals()
    signal_state = load_signal_state()

    if df_active.empty:
        logging.info("Нет подтвержденных сигналов.")
        return

    live_orders_submitted = 0

    for _, row in df_active.iterrows():
        if not DRY_RUN and not can_submit_live_order(live_orders_submitted):
            logging.warning(
                "Достигнут лимит боевого запуска: не более %s новой заявки за запуск.",
                MAX_NEW_ORDERS_PER_RUN
            )
            break
        # Never let a previous row's identifier leak into this row's error path.
        signal_id = None
        ticker = str(row["ticker"]).strip().upper()
        direction = str(row["direction"]).strip().upper()

        if not ticker:
            logging.warning("Пропуск строки: пустой тикер")
            continue

        if direction not in ("LONG", "SHORT"):
            logging.warning(
                "%s: неизвестное направление %s",
                ticker,
                direction
            )
            continue

        symbol = f"{ticker}@{MIC}"
        sector = SECTOR_GROUPS.get(ticker)

        if ticker in open_symbols:
            logging.info(
                "%s пропущен: позиция уже открыта",
                ticker
            )
            continue

        if position_limit_reached(open_symbols, ticker):
            logging.warning(
                "%s пропущен: достигнут лимит открытых позиций (%s)",
                ticker, MAX_OPEN_POSITIONS
            )
            continue

        if sector and sector in busy_sectors:
            logging.warning(
                "%s пропущен: сектор %s уже занят",
                ticker,
                sector
            )
            continue

        try:
            entry_price = Decimal(str(row["entry_price"]))

            if not entry_price.is_finite() or entry_price <= 0:
                raise ValueError("Некорректная цена входа")

            # Получаем параметры именно этого инструмента и счёта.
            trade_lot_size = get_trade_parameters(
                token,
                ticker,
                direction
            )

            # Рассчитываем количество акций.
            quantity = calculate_order_quantity(
                ticker,
                row["_qty_numeric"],
                trade_lot_size
            )

            if direction == "LONG":
                sl_raw = entry_price * Decimal("0.97")
                tp_raw = entry_price * Decimal("1.05")
                side = "SIDE_BUY"
                sl_rounding, tp_rounding = ROUND_FLOOR, ROUND_CEILING
            else:
                sl_raw = entry_price * Decimal("1.03")
                tp_raw = entry_price * Decimal("0.95")
                side = "SIDE_SELL"
                sl_rounding, tp_rounding = ROUND_CEILING, ROUND_FLOOR

            sl_price = round_price_to_tick(
                token, ticker, sl_raw, sl_rounding
            )
            tp_price = round_price_to_tick(
                token, ticker, tp_raw, tp_rounding
            )

        except Exception as exc:
            logging.error(
                "%s: проверка параметров не пройдена. "
                "Заявка пропущена: %s",
                ticker,
                exc
            )
            continue

        logging.info(
            "Подготовлена заявка: %s %s, "
            "лот=%s, количество=%s шт., "
            "вход=%s, SL=%s, TP=%s",
            ticker,
            direction,
            trade_lot_size,
            quantity,
            entry_price,
            sl_price,
            tp_price
        )

        # Durable dedupe reservation is committed before any broker POST.
        try:
            signal_id = signal_fingerprint(row)
            if signal_id in signal_state:
                logging.warning(
                    "%s: сигнал уже обработан/зарезервирован (status=%s); "
                    "повторная заявка запрещена.",
                    ticker, signal_state[signal_id].get("status", "UNKNOWN")
                )
                continue
            if not DRY_RUN:
                reserve_signal(signal_state, signal_id, ticker, direction)

        except Exception as exc:
            logging.critical(
                "%s: не удалось безопасно зарезервировать сигнал: %s. "
                "Новые заявки остановлены.",
                ticker, exc
            )
            send_telegram_message(
                f"🚨 <b>Журнал сигналов недоступен</b>\n"
                f"Инструмент: {ticker}\n{exc}\nНовая заявка не отправлена."
            )
            break

        # Отправка и обязательная сверка фактического исполнения.
        try:
            # Count the attempt before POST: an ambiguous timeout must not allow
            # another live order to be submitted in the same workflow run.
            if not DRY_RUN:
                live_orders_submitted += 1
            order_result = place_market_order(token, symbol, quantity, side)
            if DRY_RUN:
                continue

            order_id = order_result["order_id"]
            final_state = wait_for_terminal_order(token, order_id)
            status = str(final_state.get("status", ""))
            executed = _decimal_value(
                final_state.get("executed_quantity"), "executed_quantity"
            )
            remaining = _decimal_value(
                final_state.get("remaining_quantity"), "remaining_quantity"
            )

            if _normalized_order_status(final_state) in {"REJECTED", "REJECTED_BY_EXCHANGE", "DENIED_BY_BROKER", "FAILED", "EXPIRED", "CANCELED", "DONE_FOR_DAY"} and executed <= 0:
                update_signal_state(
                    signal_state, signal_id, "NO_FILL_TERMINAL",
                    order_id=str(order_id), broker_status=status,
                    filled_quantity="0"
                )
                logging.error("%s: заявка завершилась без исполнения, статус %s",
                              ticker, status)
                continue

            if executed <= 0:
                update_signal_state(
                    signal_state, signal_id, "NO_FILL_TERMINAL",
                    order_id=str(order_id), broker_status=status,
                    filled_quantity="0"
                )
                logging.info("%s: заявка не исполнена (status=%s)",
                             ticker, status)
                continue
            if executed != executed.to_integral_value():
                raise OrderProtectionError(
                    f"{ticker}: исполненное количество нецелое: {executed}"
                )

            filled_qty, avg_fill_price = get_weighted_average_fill(
                token, order_id, order_result["submitted_at"], executed
            )
            filled_qty_int = int(filled_qty)

            if remaining > 0:
                logging.warning("%s: остаток %s шт. не исполнен; защищаю "
                                "только исполненные %s шт.",
                                ticker, remaining, filled_qty_int)

            if direction == "LONG":
                sl_raw = avg_fill_price * Decimal("0.97")
                tp_raw = avg_fill_price * Decimal("1.05")
                sl_rounding, tp_rounding = ROUND_FLOOR, ROUND_CEILING
            else:
                sl_raw = avg_fill_price * Decimal("1.03")
                tp_raw = avg_fill_price * Decimal("0.95")
                sl_rounding, tp_rounding = ROUND_CEILING, ROUND_FLOOR

            sl_price = round_price_to_tick(
                token, ticker, sl_raw, sl_rounding
            )
            tp_price = round_price_to_tick(
                token, ticker, tp_raw, tp_rounding
            )

            open_symbols.add(ticker)
            if sector:
                busy_sectors.add(sector)

            sltp_ok = place_sltp_order(
                token, symbol, filled_qty_int, direction, sl_price, tp_price
            )
            if not sltp_ok:
                raise OrderProtectionError(
                    f"{ticker}: позиция {filled_qty_int} шт. открыта, "
                    "но SL/TP не подтверждены брокером."
                )

            update_signal_state(
                signal_state, signal_id, "EXECUTED_AND_PROTECTED",
                order_id=str(order_id), filled_quantity=filled_qty_int,
                average_fill_price=str(avg_fill_price),
                sl_price=str(sl_price), tp_price=str(tp_price)
            )

            emoji = "🟢" if direction == "LONG" else "🔴"
            send_telegram_message(
                f"{emoji} <b>Заявка исполнена и защищена</b>\n\n"
                f"📈 <b>{ticker}</b> ({direction})\n"
                f"Исполнено: {filled_qty_int} шт.\n"
                f"Средняя цена исполнения: {avg_fill_price}\n"
                f"Статус заявки: {status}\n"
                f"🛡️ SL: {sl_price}\n🎯 TP: {tp_price}"
            )

        except Exception as exc:
            logging.critical(
                "%s: КРИТИЧЕСКАЯ ОШИБКА ИСПОЛНЕНИЯ/ЗАЩИТЫ: %s. "
                "Останавливаю обработку следующих сигналов.",
                ticker, exc
            )
            if not DRY_RUN and "signal_id" in locals() and signal_id in signal_state:
                try:
                    update_signal_state(
                        signal_state, signal_id, "REQUIRES_MANUAL_RECONCILIATION",
                        error=str(exc)[:1000]
                    )
                except Exception as state_exc:
                    logging.critical(
                        "Не удалось обновить журнал после ошибки: %s", state_exc
                    )
            send_telegram_message(
                f"🚨 <b>КРИТИЧЕСКАЯ ПРОБЛЕМА Finam Executor</b>\n"
                f"Инструмент: {ticker}\n{exc}\n"
                "Новые заявки в этом запуске остановлены. "
                "Проверь позицию и заявки в терминале Finam."
            )
            break

        time.sleep(REQUEST_PAUSE)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Критическая ошибка finam_executor")
        raise
        
