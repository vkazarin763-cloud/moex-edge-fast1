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
MIC = "RTS"  # Для фьючерсов используется срочный рынок RTS

TEST_MODE_MIN_VOLUME = True  # True = всегда торгуем ровно 1 контракт
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
        logging.info(f"🛡️ SL/TP для {symbol} выставлены (SL: {sl_price}, TP: {tp_price}).")
        return True
    else:
        logging.error(f"❌ Ошибка SL/TP для {symbol}: {resp.text}")
        return False

def main():
    # Проверка на нерабочее время биржи (по Москве)
    now_msk = datetime.utcnow() + timedelta(hours=3)
    current_time = now_msk.time()
    is_weekend = now_msk.weekday() >= 5
    
    if is_weekend:
        if not (dt_time(9, 50) <= current_time <= dt_time(19, 0)):
            logging.info(f"Выходной. Нерабочее время (сейчас {current_time.strftime('%H:%M')} МСК). Торговля отменена.")
            return
    else:
        if not (dt_time(6, 50) <= current_time <= dt_time(23, 50)):
            logging.info(f"Будний день. Нерабочее время (сейчас {current_time.strftime('%H:%M')} МСК). Торговля отменена.")
            return

    if not os.path.exists(CSV_FILE):
        logging.error(f"Файл {CSV_FILE} не найден! Сначала запустите сканер фьючерсов.")
        return

    token = get_jwt_token()
    logging.info("Авторизация в Finam API успешна.")

    account_data, available_cash = get_account_info(token)
    logging.info(f"Свободные средства: {available_cash:.2f} RUB")

    open_symbols = {p["symbol"] for p in account_data.get("positions", [])}

    df = pd.read_csv(CSV_FILE)
    df_active = df[(df["h1_confirmed"] == True)]

    if df_active.empty:
        logging.info("Нет подтвержденных сигналов по фьючерсам.")
        return

    for _, row in df_active.iterrows():
        secid = row["secid"]
        direction = row["direction"]
        entry_price = float(row["entry_price"])
        symbol = f"{secid}@{MIC}"

        if symbol in open_symbols:
            logging.info(f"⏭️ Позиция по {symbol} уже открыта. Пропускаем.")
            continue

        # Для теста берем 1 контракт (лот фьючерса обычно равен 1)
        qty_to_buy = 1 if TEST_MODE_MIN_VOLUME else int(row.get("qty", 1))
        
        if TEST_MODE_MIN_VOLUME:
            logging.info(f"🧪 ТЕСТОВЫЙ РЕЖИМ: {secid} берем 1 контракт.")

        side = "SIDE_BUY" if direction == "LONG" else "SIDE_SELL"

        if not place_market_order(token, symbol, qty_to_buy, side):
            continue
        
        open_symbols.add(symbol) 

        # Для фьючерсов шаг цены может быть разным, но мы ставим проценты от цены
        if direction == "LONG":
            sl_price = entry_price * (1 - 0.03)
            tp_price = entry_price * (1 + 0.05)
        else:
            sl_price = entry_price * (1 + 0.03)
            tp_price = entry_price * (1 - 0.05)

        place_sltp_order(token, symbol, qty_to_buy, side, round(sl_price, 2), round(tp_price, 2))
        time.sleep(2)

if __name__ == "__main__":
    main()
