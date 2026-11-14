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
CSV_FILE = "moex_signals.csv"
MIC = "MISX"
TEST_MODE_MIN_VOLUME = True
# ============================================

BASE_URL = "https://api.finam.ru"

def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Ошибка отправки в Telegram: {e}")

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

def get_lot_size(token, ticker):
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{BASE_URL}/v1/assets/{ticker}@{MIC}", headers=headers)
    if resp.status_code == 200:
        return int(float(resp.json().get("lot_size", {}).get("value", "1")))
    return 1

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
        logging.info(f"🛡️ SL/TP для {symbol} выставлены (SL: {sl_price}, TP: {tp_price}).")
        return True
    else:
        logging.error(f"❌ Ошибка SL/TP для {symbol}: {resp.text}")
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
    df_active = df[(df["h1_confirmed"] == True) & (df["qty"] > 0)]

    if df_active.empty:
        logging.info("Нет подтвержденных сигналов.")
        return

    for _, row in df_active.iterrows():
        ticker = row["ticker"]
        direction = row["direction"]
        entry_price = float(row["entry_price"])
        symbol = f"{ticker}@{MIC}"

        if symbol in open_symbols:
            continue

        lot_size = get_lot_size(token, ticker)
        qty_lots = 1 if TEST_MODE_MIN_VOLUME else int(row["qty"]) // lot_size

        if qty_lots == 0: continue

        qty_shares_to_buy = qty_lots * lot_size
        side = "SIDE_BUY" if direction == "LONG" else "SIDE_SELL"

        if not place_market_order(token, symbol, qty_shares_to_buy, side):
            continue
        
        open_symbols.add(symbol) 

        if direction == "LONG":
            sl_price = entry_price * (1 - 0.03)
            tp_price = entry_price * (1 + 0.05)
        else:
            sl_price = entry_price * (1 + 0.03)
            tp_price = entry_price * (1 - 0.05)

        if place_sltp_order(token, symbol, qty_shares_to_buy, side, round(sl_price, 2), round(tp_price, 2)):
            # ОТПРАВЛЯЕМ УВЕДОМЛЕНИЕ ТОЛЬКО ЕСЛИ ВСЁ ПРОШЛО УСПЕШНО
            emoji = "🟢" if direction == "LONG" else "🔴"
            msg = (
                f"{emoji} <b>Сделка открыта!</b>\n\n"
                f"📈 <b>{ticker}</b> ({direction})\n"
                f"Цена входа: {entry_price:.2f}\n"
                f"Объем: {qty_shares_to_buy} шт.\n\n"
                f"🛡️ Стоп-лосс: {round(sl_price, 2)}\n"
                f"🎯 Тейк-профит: {round(tp_price, 2)}"
            )
            send_telegram_message(msg)

        time.sleep(2)

if __name__ == "__main__":
    main()
