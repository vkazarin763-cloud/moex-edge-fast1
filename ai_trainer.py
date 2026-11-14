import json
import time
import requests
import pandas as pd
import numpy as np
import warnings
from datetime import datetime, timedelta
warnings.filterwarnings('ignore')

ISS_BASE = "https://iss.moex.com/iss"
BOARD = "TQBR"
PAUSE = 0.2
TICKERS = ["SBER", "GAZP", "LKOH", "ROSN", "NVTK", "TATN", "MTSS", "MOEX", "VTBR", "YDEX"]
WEIGHTS_FILE = "ai_weights.json"

def fetch_candles(ticker, interval, dfrom, dtill):
    url = f"{ISS_BASE}/engines/stock/markets/shares/boards/{BOARD}/securities/{ticker}/candles.json"
    rows, start = [], 0
    while True:
        p = {"from": dfrom, "till": dtill, "interval": interval, "start": start, "iss.reverse": "false"}
        try: r = requests.get(url, params=p, timeout=30).json()
        except: break
        b = r.get("candles", {})
        data, cols = b.get("data", []), b.get("columns", [])
        if not data: break
        idx = {c: i for i, c in enumerate(cols)}
        for row in data:
            rows.append([row[idx.get(c, 0)] for c in ["open", "high", "low", "close", "volume", "begin"]])
        if len(data) < 500: break
        start += len(data)
        time.sleep(PAUSE)
    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume", "begin"])
    for c in ["open", "high", "low", "close", "volume"]: df[c] = pd.to_numeric(df[c], errors='coerce')
    df["begin"] = pd.to_datetime(df["begin"])
    return df.dropna().sort_values("begin").reset_index(drop=True)

# ... (ВСТАВЬТЕ СЮДА ФУНКЦИИ calc_indicators и get_signals ИЗ ai_agent.py) ...
# Чтобы не дублировать код, просто скопируйте их из ai_agent.py

def simulate_trade(h1_df, entry_time, direction):
    h1_future = h1_df[h1_df['begin'] >= entry_time].copy()
    if h1_future.empty: return None
    actual_entry = h1_future.iloc[0]['open']
    act_price = actual_entry * (1 + direction * 0.02)
    tp_price = actual_entry * (1 + direction * 0.05)
    be_price = actual_entry * (1 + direction * 0.0026)
    sl_price = actual_entry * (1 - direction * 0.03)
    activated = False
    
    for i in range(len(h1_future)):
        op, hi, lo = h1_future.iloc[i]['open'], h1_future.iloc[i]['high'], h1_future.iloc[i]['low']
        if direction == 1:
            if op >= tp_price or hi >= tp_price: return 5.0 - 0.26
            if not activated:
                if op <= sl_price or lo <= sl_price: return -3.0 - 0.26
                if hi >= act_price: activated = True
            else:
                if op <= be_price or lo <= be_price: return 0.0 - 0.26
        else:
            if op <= tp_price or lo <= tp_price: return 5.0 - 0.26
            if not activated:
                if op >= sl_price or hi >= sl_price: return -3.0 - 0.26
                if lo <= act_price: activated = True
            else:
                if op >= be_price or hi >= be_price: return 0.0 - 0.26
    return 0.0

def main():
    print("=== AI TRAINER ===")
    d1_from = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    d1_till = datetime.now().strftime('%Y-%m-%d')
    
    stats = {}
    for ticker in TICKERS:
        print(f"Анализ {ticker}...")
        d1 = fetch_candles(ticker, 24, d1_from, d1_till)
        if len(d1) < 200: continue
        h1 = fetch_candles(ticker, 60, d1_from, d1_till)
        if h1.empty: continue
        
        d1 = calc_indicators(d1)
        for i in range(200, len(d1)):
            sigs = get_signals(d1.iloc[:i+1].copy())
            for direction, strat in sigs:
                sig_date = d1.iloc[i]['begin']
                next_h1 = h1[h1['begin'] > sig_date]
                if next_h1.empty: continue
                ret = simulate_trade(h1, next_h1.iloc[0]['begin'], direction)
                if ret is not None:
                    stats.setdefault(strat, []).append(ret)

    new_weights = {}
    print("\n=== РЕЗУЛЬТАТЫ ===")
    for strat, rets in stats.items():
        if len(rets) < 3:
            new_weights[strat] = 5; continue
        win = [r for r in rets if r > 0]
        pf = sum(win) / abs(sum(r for r in rets if r < 0)) if any(r < 0 for r in rets) else 10
        weight = min(10, max(1, int(pf * 1.5)))
        new_weights[strat] = weight
        print(f"{strat}: Сделок {len(rets)}, PF {pf:.2f} -> Вес: {weight}")

    with open(WEIGHTS_FILE, "w", encoding="utf-8") as f:
        json.dump(new_weights, f, ensure_ascii=False, indent=2)
    print(f"Веса сохранены в {WEIGHTS_FILE}")

if __name__ == "__main__":
    main()
