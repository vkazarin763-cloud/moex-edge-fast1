
import os
import time
import logging
import requests
import pandas as pd

from decimal import Decimal, InvalidOperation
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
MIC = "MISX"

# True = минимальный допустимый торговый лот каждого инструмента.
# False = использовать qty из CSV, считая его количеством акций.
TEST_MODE_MIN_VOLUME = True

# По умолчанию безопасный режим: только проверка, без реальных заявок.
# Для реальной торговли установить FINAM_DRY_RUN=false в GitHub Secrets/Variables.
DRY_RUN = os.getenv("FINAM_DRY_RUN", "true").strip().lower() in (
    "1", "true", "yes", "да"
)

BASE_URL = "https://api.finam.ru"
REQUEST_TIMEOUT = 20
REQUEST_PAUSE = 0.5

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


# ============================================================
# INSTRUMENT PARAMETERS
# ============================================================

def get_trade_parameters(token, ticker):
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
# MARKET ORDER
# ============================================================

def place_market_order(token, symbol, quantity, side):
    if not isinstance(quantity, int) or quantity <= 0:
        logging.error(
            "Отказ от заявки %s: недопустимое количество %s",
            symbol,
            quantity
        )
        return False

    payload = {
        "symbol": symbol,
        "quantity": {
            "value": str(quantity)
        },
        "side": side,
        "type": "ORDER_TYPE_MARKET",
        "account_id": ACCOUNT_ID
    }

    if DRY_RUN:
        logging.warning(
            "[DRY RUN] Заявка не отправлена: %s %s %s шт.",
            side,
            symbol,
            quantity
        )
        return True

    try:
        response = api_post(
            f"{BASE_URL}/v1/accounts/{ACCOUNT_ID}/orders",
            token,
            payload
        )

        if response.status_code in (200, 201):
            logging.info(
                "Ордер %s %s (%s шт.) отправлен.",
                side,
                symbol,
                quantity
            )
            return True

        logging.error(
            "Ошибка ордера %s: HTTP %s: %s",
            symbol,
            response.status_code,
            response.text
        )
        return False

    except requests.RequestException as exc:
        logging.error(
            "Ошибка соединения при отправке %s: %s",
            symbol,
            exc
        )
        return False


# ============================================================
# SL / TP
# ============================================================

def place_sltp_order(
    token,
    symbol,
    quantity,
    position_direction,
    sl_price,
    tp_price
):
    """
    SL/TP отправляются в штуках.

    Для LONG защитные заявки направлены на продажу.
    Для SHORT защитные заявки направлены на покупку.
    """

    if not isinstance(quantity, int) or quantity <= 0:
        logging.error(
            "SL/TP %s: некорректное количество %s",
            symbol,
            quantity
        )
        return False

    exit_side = (
        "SIDE_SELL"
        if position_direction == "LONG"
        else "SIDE_BUY"
    )

    payload = {
        "symbol": symbol,
        "side": exit_side,
        "quantity_sl": {
            "value": str(quantity)
        },
        "sl_price": {
            "value": str(sl_price)
        },
        "quantity_tp": {
            "value": str(quantity)
        },
        "tp_price": {
            "value": str(tp_price)
        }
    }

    if DRY_RUN:
        logging.warning(
            "[DRY RUN] SL/TP не отправлены: %s SL=%s TP=%s",
            symbol,
            sl_price,
            tp_price
        )
        return True

    try:
        response = api_post(
            f"{BASE_URL}/v1/accounts/{ACCOUNT_ID}/sltp-orders",
            token,
            payload
        )

        if response.status_code in (200, 201):
            logging.info(
                "SL/TP для %s отправлены.",
                symbol
            )
            return True

        logging.error(
            "Ошибка SL/TP %s: HTTP %s: %s",
            symbol,
            response.status_code,
            response.text
        )
        return False

    except requests.RequestException as exc:
        logging.error(
            "Ошибка соединения SL/TP %s: %s",
            symbol,
            exc
        )
        return False


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

    logging.info(
        "Свободные средства: %s RUB",
        available_cash
    )

    open_symbols = {
        p["symbol"].split("@")[0]
        for p in account_data.get("positions", [])
        if p.get("symbol")
    }

    busy_sectors = set()

    for ticker in open_symbols:
        sector = SECTOR_GROUPS.get(ticker)
        if sector:
            busy_sectors.add(sector)

    logging.info("Открытые инструменты: %s", open_symbols)
    logging.info("Занятые сектора: %s", busy_sectors)

    df_active = load_active_signals()

    if df_active.empty:
        logging.info("Нет подтвержденных сигналов.")
        return

    for _, row in df_active.iterrows():

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
                ticker
            )

            # Рассчитываем количество акций.
            quantity = calculate_order_quantity(
                ticker,
                row["_qty_numeric"],
                trade_lot_size
            )

            if direction == "LONG":
                sl_price = entry_price * Decimal("0.97")
                tp_price = entry_price * Decimal("1.05")
                side = "SIDE_BUY"
            else:
                sl_price = entry_price * Decimal("1.03")
                tp_price = entry_price * Decimal("0.95")
                side = "SIDE_SELL"

            sl_price = round(float(sl_price), 2)
            tp_price = round(float(tp_price), 2)

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

        # Отправка рыночной заявки.
        order_ok = place_market_order(
            token,
            symbol,
            quantity,
            side
        )

        if not order_ok:
            continue

        if not DRY_RUN:
            # После принятия заявки не отправляем повторную заявку
            # на этот тикер в рамках текущего запуска.
            open_symbols.add(ticker)

            if sector:
                busy_sectors.add(sector)

        # Постановка SL/TP.
        sltp_ok = place_sltp_order(
            token,
            symbol,
            quantity,
            direction,
            sl_price,
            tp_price
        )

        if not sltp_ok:
            message = (
                f"⚠️ <b>ВНИМАНИЕ: SL/TP не установлены!</b>\n\n"
                f"Инструмент: {ticker}\n"
                f"Направление: {direction}\n"
                f"Количество: {quantity} шт.\n"
                f"Требуется ручная проверка открытой позиции."
            )

            logging.critical(
                "SL/TP не установлены для %s. "
                "Позиция требует проверки.",
                ticker
            )

            if not DRY_RUN:
                send_telegram_message(message)

        else:
            emoji = "🟢" if direction == "LONG" else "🔴"

            message = (
                f"{emoji} <b>Заявка обработана</b>\n\n"
                f"📈 <b>{ticker}</b> ({direction})\n"
                f"Количество: {quantity} шт.\n"
                f"Торговый лот: {trade_lot_size}\n"
                f"Цена сигнала: {entry_price}\n\n"
                f"🛡️ SL: {sl_price}\n"
                f"🎯 TP: {tp_price}"
            )

            if not DRY_RUN:
                send_telegram_message(message)

        time.sleep(REQUEST_PAUSE)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Критическая ошибка finam_executor")
        raise
        
