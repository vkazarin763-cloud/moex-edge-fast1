import os
import time
import logging
import requests
import pandas as pd
from datetime import datetime, timedelta, time as dt_time

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

FINAM_SECRET = os.getenv("FINAM_API_SECRET")
ACCOUNT_ID = os.getenv("FINAM_ACCOUNT_ID")
CSV_FILE = "futures_signals.csv"
TEST_MODE_MIN_VOLUME = True

BASE_URL = "https://api.finam.ru"
MIC = "RTSX"

MINI_MAPPING = {
    'SVZ6': 'S1Z6',   # Серебро
    'GDZ6': 'G1Z6',   # Золото
    'BRZ6': 'BRM',    # Нефть
    'LKZ6': 'LKM',    # Лукойл
    'GZZ6': 'GZM',    # Газпром
    'SRZ6': 'SRM',    # Сбербанк
    'RNZ6': 'RNM',    # Роснефть
}

def get_jwt_token():
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

def main():
    now_msk = datetime.utcnow() + timedelta(hours=3)
    current_time = now_msk.time()
    is_weekend = now_msk.weekday() >= 5
    
    if is_weekend:
        if not (dt_time(9, 50) <= current_time <= dt_time(19, 0)): return
    else:
        if not (dt_time(6, 50) <= current_time <= dt_time(23, 50)): return

    if not os.path.exists(CSV_FILE): return

    token = get_jwt_token()
    account_data, available_cash = get_account_info(token)
    logging.info(f"Свободные средства: {available_cash:.2f} RUB")

    open_symbols = {p["symbol"] for p in account_data.get("positions", [])}

    df = pd.read_csv(CSV_FILE)
    df_active = df[(df["h1_confirmed"] == True)]

    if df_active.empty:
        logging.info("Нет подтвержденных сигналов.")
        return

    for _, row in df_active.iterrows():
        secid = row["secid"].upper()
        direction = row["direction"]
        
        # --- ЗАЩИТА ОТ ОШИБКИ 666 (Пока пропускаем все шорты) ---
        if direction == "SHORT":
            logging.warning(f"⏭️ Пропускаем SHORT по {secid} (требуется настройка непокрытых сделок в Finam)")
            continue
        # ---------------------------------------------------------

        trade_secid = MINI_MAPPING.get(secid, secid)
        symbol = f"{trade_secid}@{MIC}"
        
        if symbol in open_symbols:
            logging.info(f"⏭️ Позиция по {symbol} уже открыта.")
            continue
            
        side = "SIDE_BUY" if direction == "LONG" else "SIDE_SELL"
        logging.info(f"🧪 Сигнал по {secid}. Пытаемся торговать {symbol}...")
        
        fresh_token = get_jwt_token()
        
        if place_market_order(fresh_token, symbol, 1, side):
            open_symbols.add(symbol)

if __name__ == "__main__":
    main()
