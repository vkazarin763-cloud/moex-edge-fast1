import os
import time
import logging
import requests
import pandas as pd
from datetime import datetime, timedelta, time as dt_time

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ================= НАСТРОЙКИ =================
FINAM_SECRET = os.getenv("FINAM_API_SECRET")
ACCOUNT_ID = os.getenv("FINAM_ACCOUNT_ID")
CSV_FILE = "futures_signals.csv"
TEST_MODE_MIN_VOLUME = True
# ============================================

BASE_URL = "https://api.finam.ru"

def get_jwt_token():
    if not FINAM_SECRET:
        raise ValueError("Не задан FINAM_API_SECRET")
    resp = requests.post(f"{BASE_URL}/v1/sessions", json={"secret": FINAM_SECRET})
    resp.raise_for_status()
    return resp.json()["token"]

def get_account_info(token):
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{BASE_URL}/v1/accounts/{ACCOUNT_ID}", headers=headers)
    resp.raise_for_status()
    data = resp.json()
    available_cash = data.get("portfolio_mc", {}).get("available_cash", {}).get("value", "0")
    return data, float(available_cash)

def get_finam_futures_symbols(token):
    """Запрашиваем у Финама список всех доступных фьючерсов"""
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{BASE_URL}/v1/assets", headers=headers)
    
    # Защита на случай, если API вернет ошибку
    if resp.status_code != 200:
        logging.error(f"Не удалось получить список инструментов: {resp.text}")
        return {}
        
    assets = resp.json().get("assets", [])
    futures_map = {}
    
    for asset in assets:
        # Нас интересуют только фьючерсы
        if asset.get("type") == "FUTURES":
            ticker = asset.get("ticker", "")
            symbol = asset.get("symbol", "")
            # Сохраняем в словарь: ключ = тикер (например, SVZ6), значение = полный символ (например, SVZ6@ROFX)
            if ticker:
                futures_map[ticker] = symbol
                
    return futures_map

def place_market_order(token, symbol, quantity, side):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "symbol": symbol,
        "quantity": {"value": str(quantity)},
        "side": side,
        "type": "ORDER_TYPE_MARKET",
        "account_id": ACCOUNT_ID
    }
    resp = requests.post(f"{BASE_URL}/v1/accounts/{ACCOUNT_ID}/orders", headers=headers, json=payload)
    if resp.status_code in (200, 201):
        logging.info(f"✅ Ордер {side} {symbol} ({quantity} шт.) выставлен.")
        return True
    else:
        logging.error(f"❌ Ошибка ордера {symbol}: {resp.text}")
        return False

def place_sltp_order(token, symbol, quantity, side, sl_price, tp_price):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "symbol": symbol,
        "quantity": {"value": str(quantity)},
        "side": side,
        "account_id": ACCOUNT_ID,
        "stop_loss": {"price": {"value": str(sl_price)}},
        "take_profit": {"price": {"value": str(tp_price)}}
    }
    resp = requests.post(f"{BASE_URL}/v1/accounts/{ACCOUNT_ID}/sltp-orders", headers=headers, json=payload)
    if resp.status_code in (200, 201):
        logging.info(f"🛡️ SL/TP для {symbol} выставлены.")
        return True
    return False

def main():
    # Проверка времени
    now_msk = datetime.utcnow() + timedelta(hours=3)
    current_time = now_msk.time()
    is_weekend = now_msk.weekday() >= 5
    
    if is_weekend:
        if not (dt_time(9, 50) <= current_time <= dt_time(19, 0)):
            return
    else:
        if not (dt_time(6, 50) <= current_time <= dt_time(23, 50)):
            return

    if not os.path.exists(CSV_FILE):
        return

    token = get_jwt_token()
    logging.info("Авторизация в Finam API успешна.")

    account_data, available_cash = get_account_info(token)
    logging.info(f"Свободные средства: {available_cash:.2f} RUB")

    # Получаем карту доступных фьючерсов от Финама
    logging.info("Загрузка справочника фьючерсов из Finam API...")
    finam_futures = get_finam_futures_symbols(token)
    logging.info(f"Найдено доступных фьючерсов в Финаме: {len(finam_futures)}")

    open_symbols = {p["symbol"] for p in account_data.get("positions", [])}

    df = pd.read_csv(CSV_FILE)
    df_active = df[(df["h1_confirmed"] == True)]

    if df_active.empty:
        logging.info("Нет подтвержденных сигналов.")
        return

    for _, row in df_active.iterrows():
        secid = row["secid"] # Это тикер с MOEX (например, SVZ6)
        direction = row["direction"]
        entry_price = float(row["entry_price"])

        # Ищем этот тикер в справочнике Финама
        if secid not in finam_futures:
            logging.warning(f"⚠️ Инструмент {secid} не найден в Финаме. Проверьте, доступен ли он для торговли.")
            # Выведем первые 5 фьючерсов для примера, чтобы видеть формат
            sample = list(finam_futures.keys())[:5]
            logging.info(f"Примеры доступных тикеров: {sample}")
            continue

        symbol = finam_futures[secid] # Получаем правильный символ (например, SVZ6@ROFX)

        if symbol in open_symbols:
            logging.info(f"⏭️ Позиция по {symbol} уже открыта. Пропускаем.")
            continue

        qty = 1 if TEST_MODE_MIN_VOLUME else int(row.get("qty", 1))
        side = "SIDE_BUY" if direction == "LONG" else "SIDE_SELL"

        logging.info(f"🧪 Попытка торговли: {secid} (Символ: {symbol})")
        
        if not place_market_order(token, symbol, qty, side):
            continue
        
        open_symbols.add(symbol) 

        if direction == "LONG":
            sl_price = entry_price * (1 - 0.03)
            tp_price = entry_price * (1 + 0.05)
        else:
            sl_price = entry_price * (1 + 0.03)
            tp_price = entry_price * (1 - 0.05)

        place_sltp_order(token, symbol, qty, side, round(sl_price, 2), round(tp_price, 2))
        time.sleep(2)

if __name__ == "__main__":
    main()
