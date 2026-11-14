import os
import time
import logging
import requests
import pandas as pd
from datetime import datetime, timedelta, time as dt_time

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

FINAM_SECRET = os.getenv("FINAM_API_SECRET")
ACCOUNT_ID = os.getenv("FINAM_ACCOUNT_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CSV_FILE = "futures_signals.csv"
TEST_MODE_MIN_VOLUME = True
BASE_URL = "https://api.finam.ru"
MIC = "RTSX"

MINI_MAPPING = {'SVZ6': 'S1Z6', 'GDZ6': 'G1Z6', 'BRZ6': 'BRM', 'LKZ6': 'LKM', 'GZZ6': 'GZM', 'SRZ6': 'SRM', 'RNZ6': 'RNM'}

def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e: logging.error(f"Telegram error: {e}")

def get_jwt_token():
    resp = requests.post(f"{BASE_URL}/v1/sessions", json={"secret": FINAM_SECRET})
    resp.raise_for_status(); return resp.json()["token"]

def get_account_info(token):
    resp = requests.get(f"{BASE_URL}/v1/accounts/{ACCOUNT_ID}", headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    data = resp.json()
    return data, float(data.get("portfolio_mc", {}).get("available_cash", {}).get("value", "0"))

def check_shortable(token, symbol):
    try:
        url = f"{BASE_URL}/v1/assets/{symbol}/params?account_id={ACCOUNT_ID}"
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 200:
            status = resp.json().get("shortable", {}).get("value", "NOT_AVAILABLE")
            return status in ("AVAILABLE", "AVAILABLE_STRATEGY")
    except: pass
    return False

def place_limit_order(token, symbol, quantity, side, price):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "symbol": symbol, "quantity": {"value": str(quantity)}, "side": side,
        "type": "ORDER_TYPE_LIMIT", "limit_price": {"value": str(price)}, "account_id": ACCOUNT_ID
    }
    resp = requests.post(f"{BASE_URL}/v1/accounts/{ACCOUNT_ID}/orders", headers=headers, json=payload)
    if resp.status_code in (200, 201):
        logging.info(f"✅ Лимитный ордер {side} {symbol} выставлен."); return True
    logging.error(f"❌ Ошибка {symbol}: {resp.text}"); return False

def place_sltp_order(token, symbol, quantity, side, sl_price, tp_price):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "symbol": symbol, "quantity": {"value": str(quantity)}, "side": side, "account_id": ACCOUNT_ID,
        "stop_loss": {"type": "STOP_LOSS", "price": {"value": str(sl_price)}},
        "take_profit": {"type": "TAKE_PROFIT", "price": {"value": str(tp_price)}}
    }
    resp = requests.post(f"{BASE_URL}/v1/accounts/{ACCOUNT_ID}/sltp-orders", headers=headers, json=payload)
    if resp.status_code in (200, 201):
        logging.info(f"🛡️ SL/TP для {symbol} выставлены."); return True
    return False

def main():
    now_msk = datetime.utcnow() + timedelta(hours=3)
    if now_msk.weekday() >= 5 and not (dt_time(9,50) <= now_msk.time() <= dt_time(19,0)): return
    if now_msk.weekday() < 5 and not (dt_time(6,50) <= now_msk.time() <= dt_time(23,50)): return
    if not os.path.exists(CSV_FILE): return

    token = get_jwt_token()
    account_data, available_cash = get_account_info(token)
    open_symbols = {p["symbol"] for p in account_data.get("positions", [])}
    df = pd.read_csv(CSV_FILE)
    df_active = df[(df["h1_confirmed"] == True)]

    for _, row in df_active.iterrows():
        secid = row["secid"].upper()
        direction = row["direction"]
        entry_price = float(row["entry_price"])
        trade_secid = MINI_MAPPING.get(secid, secid)
        symbol = f"{trade_secid}@{MIC}"

        if symbol in open_symbols: continue

        side = "SIDE_BUY" if direction == "LONG" else "SIDE_SELL"

        if side == "SIDE_SELL" and not check_shortable(token, symbol):
            logging.warning(f"⏭️ Шорт по {symbol} недоступен (статус). Пропускаем.")
            continue

        # Для шорта ставим лимит чуть ниже рынка, чтобы гарантировать исполнение
        exec_price = round(entry_price * 0.998, 2) if side == "SIDE_SELL" else round(entry_price, 2)

        fresh_token = get_jwt_token()
        if place_limit_order(fresh_token, symbol, 1, side, exec_price):
            open_symbols.add(symbol)
            sl_price = entry_price * (1 + 0.03) if side == "SIDE_SELL" else entry_price * (1 - 0.03)
            tp_price = entry_price * (1 - 0.05) if side == "SIDE_SELL" else entry_price * (1 + 0.05)

            if place_sltp_order(fresh_token, symbol, 1, side, round(sl_price, 2), round(tp_price, 2)):
                emoji = "🟢" if side == "SIDE_BUY" else "🔴"
                send_telegram_message(f"{emoji} <b>Сделка!</b>\n{secid} ({direction})\nВход: {exec_price}\nСтоп: {round(sl_price,2)}\nТейк: {round(tp_price,2)}")

if __name__ == "__main__":
    main()
