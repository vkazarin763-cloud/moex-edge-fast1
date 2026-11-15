import time
import math
import requests
import pandas as pd
import numpy as np
import warnings
from datetime import datetime, timedelta
from scipy.stats import norm
warnings.filterwarnings('ignore')

ISS_BASE = "https://iss.moex.com/iss"
PAUSE = 0.2

# Базовые активы для теста (фьючерсы на акции + индекс)
ASSETS = ["SBER", "GAZP", "LKOH", "ROSN", "MOEX"]
FUTURES_MAP = {"SBER": "SRZ6", "GAZP": "GZZ6", "LKOH": "LKZ6", "ROSN": "RNZ6", "MOEX": "MEZ6"}

# Параметры симуляции
SIGMA = 0.30       # Годовая волатильность (30%)
DAYS_TO_EXPIRY = 30 # Дней до экспирации
RISK_FREE = 0.15   # Безрисковая ставка (15%)
SL_PCT = 0.03
TP_PCT = 0.05

def black_scholes(S, K, T, r, sigma, option_type):
    """Цена опциона по Блэку-Шоулзу (T в годах)."""
    if T <= 0: return max(0, (S - K) if option_type == 'call' else (K - S))
    d1 = (math.log(S/K) + (r + sigma**2/2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == 'call':
        return S * norm.cdf(d1) - K * math.exp(-r*T) * norm.cdf(d2)
    else:
        return K * math.exp(-r*T) * norm.cdf(-d2) - S * norm.cdf(-d1)

def fetch_candles(secid, interval, dfrom, dtill):
    url = f"{ISS_BASE}/engines/futures/markets/forts/securities/{secid}/candles.json"
    rows, start = [], 0
    while True:
        p = {"from": dfrom, "till": dtill, "interval": interval, "start": start, "iss.reverse": "false"}
        try:
            r = requests.get(url, params=p, timeout=30).json()
        except:
            break
        b = r.get("candles", {})
        data, cols = b.get("data", []), b.get("columns", [])
        if not data: break
        idx = {c: i for i, c in enumerate(cols)}
        for row in data:
            rows.append([row[idx.get(c, 0)] for c in ["open", "high", "low", "close", "begin"]])
        if len(data) < 500: break
        start += len(data)
        time.sleep(PAUSE)
    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "begin"])
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df["begin"] = pd.to_datetime(df["begin"])
    return df.dropna().sort_values("begin").reset_index(drop=True)

def calc_signals(df):
    """Простые сигналы на основе EMA и ATR (как в основном сканере)."""
    df = df.copy()
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['tr'] = pd.concat([df['high']-df['low'], (df['high']-df['close'].shift()).abs(), (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr14'] = df['tr'].rolling(14).mean()
    df['don20_high'] = df['high'].rolling(20).max().shift(1)
    df['don20_low'] = df['low'].rolling(20).min().shift(1)
    
    signals = []
    for i in range(200, len(df)):
        c = df.iloc[i]
        direction = 0
        if c['ema20'] > c['ema50'] and c['close'] > c['don20_high']:
            direction = 1
        elif c['ema20'] < c['ema50'] and c['close'] < c['don20_low']:
            direction = -1
        if direction != 0:
            signals.append((c['begin'], direction, c['close'], c['atr14']))
    return signals

def simulate_linear(signals, h1):
    """Базовая линейная торговля фьючерсом."""
    results = []
    trade_end = pd.Timestamp.min
    for sig_time, direction, entry_price, atr in signals:
        if sig_time <= trade_end: continue
        future = h1[h1['begin'] > sig_time]
        if future.empty: continue
        actual_entry = future.iloc[0]['open']
        sl = actual_entry * (1 - direction * SL_PCT)
        tp = actual_entry * (1 + direction * TP_PCT)
        activated = False
        be = actual_entry * (1 + direction * 0.0026)
        for i in range(len(future)):
            op, hi, lo = future.iloc[i]['open'], future.iloc[i]['high'], future.iloc[i]['low']
            if direction == 1:
                if op >= tp or hi >= tp: 
                    results.append((tp, 'TP')); trade_end = future.iloc[i]['begin']; break
                if not activated:
                    if op <= sl or lo <= sl:
                        results.append((sl, 'SL')); trade_end = future.iloc[i]['begin']; break
                    if hi >= be: activated = True
                else:
                    if op <= be or lo <= be:
                        results.append((be, 'BE')); trade_end = future.iloc[i]['begin']; break
            else:
                if op <= tp or lo <= tp:
                    results.append((tp, 'TP')); trade_end = future.iloc[i]['begin']; break
                if not activated:
                    if op >= sl or hi >= sl:
                        results.append((sl, 'SL')); trade_end = future.iloc[i]['begin']; break
                    if lo <= be: activated = True
                else:
                    if op >= be or hi >= be:
                        results.append((be, 'BE')); trade_end = future.iloc[i]['begin']; break
    return results

def simulate_options(signals, h1, strategy):
    """Симуляция опционных стратегий через Black-Scholes."""
    results = []
    trade_end = pd.Timestamp.min
    T = DAYS_TO_EXPIRY / 365.0
    
    for sig_time, direction, entry_price, atr in signals:
        if sig_time <= trade_end: continue
        future = h1[h1['begin'] > sig_time]
        if future.empty: continue
        
        entry_price = future.iloc[0]['open']
        # Считаем премию на входе
        if strategy == 'Long_Call' and direction == 1:
            K = entry_price
            premium = black_scholes(entry_price, K, T, RISK_FREE, SIGMA, 'call')
            target = 'call'
        elif strategy == 'Long_Put' and direction == -1:
            K = entry_price
            premium = black_scholes(entry_price, K, T, RISK_FREE, SIGMA, 'put')
            target = 'put'
        elif strategy == 'Straddle':
            K = entry_price
            premium = black_scholes(entry_price, K, T, RISK_FREE, SIGMA, 'call') + black_scholes(entry_price, K, T, RISK_FREE, SIGMA, 'put')
            target = 'straddle'
        elif strategy == 'Strangle':
            K_call = entry_price * 1.05
            K_put = entry_price * 0.95
            premium = black_scholes(entry_price, K_call, T, RISK_FREE, SIGMA, 'call') + black_scholes(entry_price, K_put, T, RISK_FREE, SIGMA, 'put')
            target = 'strangle'
        else:
            continue
        
        # Держим опцион до экспирации или до TP
        expiry_time = sig_time + pd.Timedelta(days=DAYS_TO_EXPIRY)
        exit_pnl = None
        for i in range(len(future)):
            t_current = future.iloc[i]['begin']
            if t_current > expiry_time:
                # На экспирации считаем intrinsic value
                S = future.iloc[i]['close']
                if target == 'call': exit_pnl = max(0, S - entry_price) - premium
                elif target == 'put': exit_pnl = max(0, entry_price - S) - premium
                elif target == 'straddle': exit_pnl = abs(S - entry_price) - premium
                elif target == 'strangle': 
                    exit_pnl = max(0, S - entry_price*1.05) + max(0, entry_price*0.95 - S) - premium
                trade_end = t_current
                break
            
            # Проверяем TP (если прибыль достигла 50% от премии)
            T_left = max(0, (expiry_time - t_current).days / 365.0)
            S = future.iloc[i]['close']
            
            if target == 'call': current_value = black_scholes(S, entry_price, T_left, RISK_FREE, SIGMA, 'call')
            elif target == 'put': current_value = black_scholes(S, entry_price, T_left, RISK_FREE, SIGMA, 'put')
            elif target == 'straddle': 
                current_value = black_scholes(S, entry_price, T_left, RISK_FREE, SIGMA, 'call') + black_scholes(S, entry_price, T_left, RISK_FREE, SIGMA, 'put')
            elif target == 'strangle':
                current_value = black_scholes(S, entry_price*1.05, T_left, RISK_FREE, SIGMA, 'call') + black_scholes(S, entry_price*0.95, T_left, RISK_FREE, SIGMA, 'put')
            
            pnl = current_value - premium
            # TP: 100% прибыли от премии
            if pnl >= premium: 
                exit_pnl = pnl
                trade_end = t_current
                break
        
        if exit_pnl is not None:
            results.append((exit_pnl, 'TP' if exit_pnl > 0 else 'EXP'))
    return results

def main():
    print("=== OPTIONS BACKTEST (сравнение с линейной торговлей) ===")
    d1_from = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    d1_till = datetime.now().strftime('%Y-%m-%d')
    
    all_linear = []
    all_options = {s: [] for s in ['Long_Call', 'Long_Put', 'Straddle', 'Strangle']}
    
    for asset in ASSETS:
        secid = FUTURES_MAP.get(asset)
        if not secid: continue
        print(f"\nАнализ {asset} ({secid})...")
        h1 = fetch_candles(secid, 60, d1_from, d1_till)
        if h1.empty: continue
        
        # Сигналы считаем на H1 (упрощенно)
        signals = calc_signals(h1)
        print(f"  Сигналов: {len(signals)}")
        if not signals: continue
        
        # Линейная
        linear_results = simulate_linear(signals, h1)
        all_linear.extend(linear_results)
        
        # Опционы
        for strat in all_options:
            opts = simulate_options(signals, h1, strat)
            all_options[strat].extend(opts)
    
    # Статистика
    print("\n" + "="*60)
    print("РЕЗУЛЬТАТЫ (PnL в % от премии/цены):")
    print("="*60)
    
    # Линейная
    lin = pd.DataFrame(all_linear, columns=['exit', 'reason'])
    if not lin.empty:
        lin_ret = (lin['exit'] - lin['exit'].mean()) / 100  # упрощенно
        print(f"\nЛинейная (фьючерс): {len(lin)} сделок")
        print(f"  Причины: {lin['reason'].value_counts().to_dict()}")
    
    # Опционы
    for strat, results in all_options.items():
        if not results: continue
        df = pd.DataFrame(results, columns=['pnl', 'reason'])
        win = df[df['pnl'] > 0]
        print(f"\n{strat}: {len(df)} сделок")
        print(f"  Win Rate: {len(win)/len(df)*100:.1f}%")
        print(f"  Средний PnL: {df['pnl'].mean():.2f}")
        print(f"  Причины: {df['reason'].value_counts().to_dict()}")

if __name__ == "__main__":
    main()
