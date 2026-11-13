import os
import time
import logging
import requests
import pandas as pd
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ================= НАСТРОЙКИ =================
FINAM_SECRET = os.getenv("FINAM_API_SECRET")
ACCOUNT_ID = os.getenv("FINAM_ACCOUNT_ID")
CSV_FILE = "moex_signals.csv"
MIC = "MISX"

TEST_MODE_MIN_VOLUME = True  # True = всегда торгуем ровно 1 лот
# ============================================

BASE_URL = "https://api.finam.ru"

def get_jwt_token():
    if not FINAM_SECRET:
        raise ValueError("Не задан FINAM_API_SECRET в переменных окружения")
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

def get_lot_size(token, ticker):
    headers = {"Authorization": f"Bearer {token}"}
    symbol = f"{ticker}@{MIC}"
    resp = requests.get(f"{BASE_URL}/v1/assets/{symbol}", headers=headers)
    if resp.status_code == 200:
        return int(float(resp.json().get("lot_size", {}).get("value", "1")))
    return 1

def place_market_order(token, symbol, quantity, side):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "symbol": symbol,
        "quantity": {"value": str(quantity)},  # ИСПРАВЛЕНО: передаем как объект
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
        "stop_loss": {"price": {"value": str(sl_price)}},      # ИСПРАВЛЕНО
        "take_profit": {"price": {"value": str(tp_price)}}     # ИСПРАВЛЕНО
    }
    resp = requests.post(f"{BASE_URL}/v1/accounts/{ACCOUNT_ID}/sltp-orders", headers=headers, json=payload)
    if resp.status_code in (200, 201):
        logging.info(f"🛡️ SL/TP для {symbol} выставлены (SL: {sl_price}, TP: {tp_price}).")
        return True
    else:
        logging.error(f"❌ Ошибка SL/TP для {symbol}: {resp.text}")
        return False

def main():
    # Проверка на выходные и нерабочее время (по Москве)
    now_msk = datetime.utcnow() + timedelta(hours=3)
    if now_msk.weekday() >= 5: # 5 - суббота, 6 - воскресенье
        logging.info("Сегодня выходной. Биржа закрыта. Торговля отменена.")
        return
    if now_msk.hour < 10 or now_msk.hour >= 19: # С 10:00 до 19:00 МСК
        logging.info("Нерабочее время биржи. Торговля отменена.")
        return

    if not os.path.exists(CSV_FILE):
        logging.error("Файл moex_signals.csv не найден! Сначала запустите сканер.")
        return

    token = get_jwt_token()
    logging.info("Авторизация в Finam API успешна.")

    account_data, available_cash = get_account_info(token)
    logging.info(f"Свободные средства: {available_cash:.2f} RUB")

    open_symbols = {p["symbol"] for p in account_data.get("positions", [])}

    df = pd.read_csv(CSV_FILE)
    df_active = df[(df["h1_confirmed"] == True) & (df["qty"] > 0)]

    if df_active.empty:
        logging.info("Нет подтвержденных сигналов для исполнения.")
        return

    for _, row in df_active.iterrows():
        ticker = row["ticker"]
        direction = row["direction"]
        entry_price = float(row["entry_price"])
        symbol = f"{ticker}@{MIC}"

        if symbol in open_symbols:
            logging.info(f"⏭️ Позиция по {symbol} уже открыта или заявка отправлена. Пропускаем.")
            continue

        lot_size = get_lot_size(token, ticker)
        
        if TEST_MODE_MIN_VOLUME:
            qty_lots = 1
            logging.info(f"🧪 ТЕСТОВЫЙ РЕЖИМ: {ticker} берем 1 лот.")
        else:
            qty_shares = int(row["qty"])
            qty_lots = qty_shares // lot_size

        if qty_lots == 0:
            continue

        qty_shares_to_buy = qty_lots * lot_size
        required_cash = qty_shares_to_buy * entry_price
        
        if required_cash > available_cash:
            logging.warning(f"⚠️ {ticker}: недостаточно средств. Требуется {required_cash:.2f} RUB, доступно {available_cash:.2f} RUB.")
            continue

        side = "SIDE_BUY" if direction == "LONG" else "SIDE_SELL"

        if not place_market_order(token, symbol, qty_shares_to_buy, side):
            continue
        
        # СРАЗУ ДОБАВЛЯЕМ В СПИСОК, ЧТОБЫ НЕ КУПИТЬ ДВА РАЗА
        open_symbols.add(symbol) 

        if direction == "LONG":
            sl_price = entry_price * (1 - 0.03)
            tp_price = entry_price * (1 + 0.05)
        else:
            sl_price = entry_price * (1 + 0.03)
            tp_price = entry_price * (1 - 0.05)

        place_sltp_order(token, symbol, qty_shares_to_buy, side, round(sl_price, 2), round(tp_price, 2))

        available_cash -= required_cash
        time.sleep(2)

if __name__ == "__main__":
    main()
