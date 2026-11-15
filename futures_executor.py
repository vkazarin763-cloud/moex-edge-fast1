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
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CSV_FILE = "futures_signals.csv"
TEST_MODE_MIN_VOLUME = True
# ============================================

BASE_URL = "https://api.finam.ru"
MIC = "RTSX" # Правильный MIC для фьючерсов Finam

# Словарь сопоставления обычных фьючерсов и их мини-версий
MINI_MAPPING = {
    'SVZ6': 'S1Z6', 'GDZ6': 'G1Z6', 'BRZ6': 'BRM',
    'LKZ6': 'LKM', 'GZZ6': 'GZM', 'SRZ6': 'SRM', 'RNZ6': 'RNM',
}

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Ошибка Telegram: {e}")

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

def place_sltp_order(token, symbol, quantity, side, sl_price, tp_price):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "symbol": symbol,
        "quantity": {"value": str(quantity)},
        "side": side,
        "account_id": ACCOUNT_ID,
        "stop_loss": {"type": "STOP_LOSS", "price": {"value": str(sl_price)}},
        "take_profit": {"type": "TAKE_PROFIT", "price": {"value": str(tp_price)}}
    }
    resp = requests.post(f"{BASE_URL}/v1/accounts/{ACCOUNT_ID}/sltp-orders", headers=headers, json=payload)
    if resp.status_code in (200, 201):
        logging.info(f"🛡️ SL/TP для {symbol} выставлены.")
        return True
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
        logging.info("Нет подтвержденных сигналов по фьючерсам.")
        return

    for _, row in df_active.iterrows():
        secid = row["secid"].upper()
        direction = row["direction"]
        entry_price = float(row["entry_price"])
        
        # =========================================================
        # ВАЖНО: ЗАЩИТА ОТ ОШИБКИ 666 (Пропускаем все шорты)
        # =========================================================
        if direction == "SHORT":
            logging.warning(f"⏭️ Пропускаем SHORT по {secid} (требуется статус КСУР для шортов)")
            continue
        # =========================================================

        trade_secid = MINI_MAPPING.get(secid, secid)
        symbol = f"{trade_secid}@{MIC}"
        
        if symbol in open_symbols: continue
            
        side = "SIDE_BUY" if direction == "LONG" else "SIDE_SELL"
        logging.info(f"🧪 Сигнал по {secid}. Пытаемся торговать {symbol}...")
        
        fresh_token = get_jwt_token()
        
        if place_market_order(fresh_token, symbol, 1, side):
            open_symbols.add(symbol)
            
            # Рассчитываем стоп и тейк
            if direction == "LONG":
                sl_price = entry_price * (1 - 0.03)
                tp_price = entry_price * (1 + 0.05)
            else:
                sl_price = entry_price * (1 + 0.03)
                tp_price = entry_price * (1 - 0.05)

            # Выставляем защиту и шлем уведомление
            if place_sltp_order(fresh_token, symbol, 1, side, round(sl_price, 2), round(tp_price, 2)):
                emoji = "🟢" if direction == "LONG" else "🔴"
                msg = (
                    f"{emoji} <b>Сделка по фьючерсу!</b>\n\n"
                    f"📈 <b>{secid}</b> ({direction})\n"
                    f"Цена входа: {entry_price:.2f}\n"
                    f"Объем: 1 контракт\n\n"
                    f"🛡️ Стоп-лосс: {round(sl_price, 2)}\n"
                    f"🎯 Тейк-профит: {round(tp_price, 2)}"
                )
                send_telegram(msg)

if __name__ == "__main__":
    main()
