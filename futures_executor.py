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

def get_finam_futures_map(token):
    """Скачиваем справочник и делаем умную карту сопоставления"""
    headers = {"Authorization": f"Bearer {token}"}
    futures_map = {}
    cursor = None
    
    logging.info("Загрузка справочника фьючерсов из Финама...")
    while True:
        params = {"only_active": "true"}
        if cursor: params["cursor"] = cursor
        
        resp = requests.get(f"{BASE_URL}/v1/assets/all", headers=headers, params=params)
        if resp.status_code != 200: break
        
        data = resp.json()
        assets = data.get("assets", [])
        if not assets: break
        
        for a in assets:
            if a.get("type") == "FUTURES":
                ticker = a.get("ticker", "").upper()
                name = a.get("name", "").upper()
                symbol = a.get("symbol", "")
                
                # 1. Прямое совпадение по тикеру
                if ticker: futures_map[ticker] = symbol
                
                # 2. Умный поиск (вытаскиваем базовый актив)
                # Например, ищем "SILV" или "GOLD" в названии
                bases = ['SILV', 'GOLD', 'BR', 'SI', 'CNY', 'MIX', 'GAZR', 'SBRF', 'LKOH', 'ROSN', 'VTBR', 'NOTK']
                for b in bases:
                    if b in name or b in ticker:
                        # Сохраняем по базовому имени, если там есть "MINI" или "МИНИ"
                        if "MINI" in name or "МИНИ" in name:
                            futures_map[f"{b}_MINI"] = symbol
                        # Сохраняем просто по базе, если еще не занято
                        if b not in futures_map:
                            futures_map[b] = symbol
        
        cursor = data.get("next_cursor")
        if not cursor: break

    logging.info(f"Справочник загружен. Найдено {len(futures_map)} связей.")
    return futures_map

def find_symbol(secid, finam_map):
    """Ищет правильный символ в Финаме для нашего MOEX тикера"""
    secid = secid.upper()
    
    # 1. Прямое совпадение (например, SVZ6)
    if secid in finam_map: return finam_map[secid]
    
    # 2. Отрезаем последние 2 символа (месяц и год: Z6, H7) и ищем базу (SV)
    base_short = secid[:-2]
    if base_short in finam_map: return finam_map[base_short]
    
    # 3. Ищем расширенное имя (SILV, GOLD)
    mapping_dict = {
        'SV': 'SILV', 'GD': 'GOLD', 'BR': 'BR', 'SR': 'SBRF', 'GZ': 'GAZR',
        'LK': 'LKOH', 'RN': 'ROSN', 'VB': 'VTBR', 'MX': 'MIX', 'CR': 'CNY'
    }
    base_long = mapping_dict.get(base_short, base_short)
    
    # Сначала ищем мини-версию (так как у нас маленький депозит)
    if f"{base_long}_MINI" in finam_map: return finam_map[f"{base_long}_MINI"]
    if base_long in finam_map: return finam_map[base_long]
    
    return None

def place_market_order(token, symbol, quantity, side):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"symbol": symbol, "quantity": {"value": str(quantity)}, "side": side, "type": "ORDER_TYPE_MARKET", "account_id": ACCOUNT_ID}
    resp = requests.post(f"{BASE_URL}/v1/accounts/{ACCOUNT_ID}/orders", headers=headers, json=payload)
    if resp.status_code in (200, 201):
        logging.info(f"✅ Ордер {side} {symbol} выставлен.")
        return True
    else:
        logging.error(f"❌ Ошибка: {resp.text}")
        return False

def main():
    now_msk = datetime.utcnow() + timedelta(hours=3)
    if now_msk.weekday() >= 5 and not (dt_time(9, 50) <= now_msk.time() <= dt_time(19, 0)): return
    if now_msk.weekday() < 5 and not (dt_time(6, 50) <= now_msk.time() <= dt_time(23, 50)): return

    if not os.path.exists(CSV_FILE): return

    token = get_jwt_token()
    account_data, available_cash = get_account_info(token)
    finam_map = get_finam_futures_map(token)
    open_symbols = {p["symbol"] for p in account_data.get("positions", [])}

    df = pd.read_csv(CSV_FILE)
    df_active = df[(df["h1_confirmed"] == True)]

    for _, row in df_active.iterrows():
        secid = row["secid"]
        direction = row["direction"]
        entry_price = float(row["entry_price"])

        symbol = find_symbol(secid, finam_map)
        
        if not symbol:
            logging.warning(f"⚠️ Для {secid} не найден аналог в Финаме. Пропускаем.")
            continue

        if symbol in open_symbols: continue

        side = "SIDE_BUY" if direction == "LONG" else "SIDE_SELL"
        logging.info(f"🧪 Торгуем {secid} через символ {symbol}")

        if place_market_order(token, symbol, 1, side):
            open_symbols.add(symbol)

if __name__ == "__main__":
    main()
