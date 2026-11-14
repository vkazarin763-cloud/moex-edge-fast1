import os
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

TICKERS = ["SBER", "GAZP", "LKOH", "ROSN", "NVTK", "TATN", "MTSS", "MOEX", "VTBR", "YDEX", "GMKN", "PLZL", "CHMF", "ALRS", "T"]
REF_TICKERS = {"IMOEX": ("SNDX", "index"), "BR": ("RTS", "share"), "Si": ("CETS", "share")}

WEIGHTS_FILE = "ai_weights.json"

def fetch_candles(ticker, interval, dfrom, dtill, board="TQBR"):
    if board == "SNDX":
        url = f"{ISS_BASE}/engines/stock/markets/index/boards/SNDX/securities/{ticker}/candles.json"
    elif board == "CETS":
        url = f"{ISS_BASE}/engines/currency/markets/selt/boards/CETS/securities/{ticker}/candles.json"
    else:
        url = f"{ISS_BASE}/engines/stock/markets/shares/boards/{board}/securities/{ticker}/candles.json"
        
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
            rows.append([row[idx.get(c, 0)] for c in ["open", "high", "low", "close", "volume", "begin"]])
        if len(data) < 500: break
        start += len(data)
        time.sleep(PAUSE)
        
    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume", "begin"])
    for c in ["open", "high", "low", "close", "volume"]: 
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df["begin"] = pd.to_datetime(df["begin"])
    return df.dropna().sort_values("begin").reset_index(drop=True)

def calc_indicators(df, ref_data=None):
    df = df.copy()
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['sma200'] = df['close'].rolling(200).mean()
    df['std200'] = df['close'].rolling(200).std()
    tr = pd.concat([df['high']-df['low'], (df['high']-df['close'].shift()).abs(), (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.rolling(14).mean()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi14'] = 100 - (100 / (1 + (gain / loss)))
    df['macd'] = df['close'].ewm(span=12, adjust=False).mean() - df['close'].ewm(span=26, adjust=False).mean()
    df['macd_sig'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['don20_high'] = df['high'].rolling(20).max().shift(1)
    df['don20_low'] = df['low'].rolling(20).min().shift(1)
    df['don55_high'] = df['high'].rolling(55).max().shift(1)
    df['don55_low'] = df['low'].rolling(55).min().shift(1)
    df['bb_mid'] = df['close'].rolling(20).mean()
    df['bb_std'] = df['close'].rolling(20).std()
    df['bb_up'] = df['bb_mid'] + 2 * df['bb_std']
    df['bb_dn'] = df['bb_mid'] - 2 * df['bb_std']
    df['kc_up'] = df['ema20'] + 2 * df['atr14']
    df['kc_dn'] = df['ema20'] - 2 * df['atr14']
    df['stoch_k'] = 100 * (df['close'] - df['low'].rolling(14).min()) / (df['high'].rolling(14).max() - df['low'].rolling(14).min())
    df['stoch_d'] = df['stoch_k'].rolling(3).mean()
    df['vwap'] = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / df['volume'].cumsum()
    df['obv'] = (np.sign(df['close'].diff()) * df['volume']).cumsum()
    df['obv_ema'] = df['obv'].ewm(span=20, adjust=False).mean()
    
    # Новые индикаторы
    df['z_score'] = (df['close'] - df['sma200']) / df['std200']
    df['inside_bar'] = (df['high'] < df['high'].shift(1)) & (df['low'] > df['low'].shift(1))
    df['gap'] = (df['open'] - df['close'].shift(1)) / df['close'].shift(1)
    df['pivot'] = (df['high'].shift(1) + df['low'].shift(1) + df['close'].shift(1)) / 3
    df['r1'] = 2 * df['pivot'] - df['low'].shift(1)
    df['s1'] = 2 * df['pivot'] - df['high'].shift(1)
    
    # Свечи
    df['body'] = (df['close'] - df['open']).abs()
    df['c_upper'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['c_lower'] = df[['open', 'close']].min(axis=1) - df['low']
    df['bull_engulf'] = (df['close'] > df['open']) & (df['close'].shift() < df['open'].shift()) & (df['close'] > df['open'].shift()) & (df['open'] < df['close'].shift())
    df['bear_engulf'] = (df['close'] < df['open']) & (df['close'].shift() > df['open'].shift()) & (df['close'] < df['open'].shift()) & (df['open'] > df['close'].shift())
    df['hammer'] = (df['c_lower'] > 2 * df['body']) & (df['c_upper'] < 0.3 * df['body'])
    df['shooting_star'] = (df['c_upper'] > 2 * df['body']) & (df['c_lower'] < 0.3 * df['body'])
    df['morning_star'] = (df['close'].shift(2) < df['open'].shift(2)) & (df['body'].shift(1) < df['body'].shift(2) * 0.5) & (df['close'] > df['open']) & (df['close'] > (df['open'].shift(2) + df['close'].shift(2))/2)
    df['evening_star'] = (df['close'].shift(2) > df['open'].shift(2)) & (df['body'].shift(1) < df['body'].shift(2) * 0.5) & (df['close'] < df['open']) & (df['close'] < (df['open'].shift(2) + df['close'].shift(2))/2)
    df['three_black'] = (df['close'] < df['open']) & (df['close'].shift() < df['open'].shift()) & (df['close'].shift(2) < df['open'].shift(2)) & (df['close'] < df['close'].shift()) & (df['close'].shift() < df['close'].shift(2))
    df['bull_harami'] = (df['close'].shift() < df['open'].shift()) & (df['close'] > df['open']) & (df['open'] > df['close'].shift()) & (df['close'] < df['open'].shift())
    df['bear_harami'] = (df['close'].shift() > df['open'].shift()) & (df['close'] < df['open']) & (df['open'] < df['close'].shift()) & (df['close'] > df['open'].shift())
    
    # Intermarket
    if ref_data:
        for ref_name, ref_df in ref_data.items():
            if not ref_df.empty and ref_name in ['IMOEX', 'BR', 'Si']:
                ref_df = ref_df[['begin', 'close']].rename(columns={'close': f'{ref_name}_close'})
                df = df.merge(ref_df, on='begin', how='left').ffill()
                df[f'{ref_name}_ema20'] = df[f'{ref_name}_close'].ewm(span=20, adjust=False).mean()
    
    return df

def get_signals(df):
    sigs = []
    # Старые сигналы
    df['cross_ema_up'] = (df['ema20'] > df['ema50']) & (df['ema20'].shift() <= df['ema50'].shift())
    df['cross_ema_dn'] = (df['ema20'] < df['ema50']) & (df['ema20'].shift() >= df['ema50'].shift())
    df['cross_macd_up'] = (df['macd'] > df['macd_sig']) & (df['macd'].shift() <= df['macd_sig'].shift())
    df['cross_macd_dn'] = (df['macd'] < df['macd_sig']) & (df['macd'].shift() >= df['macd_sig'].shift())
    df['vwap_up'] = (df['close'] > df['vwap']) & (df['close'].shift() <= df['vwap'].shift())
    df['vwap_dn'] = (df['close'] < df['vwap']) & (df['close'].shift() >= df['vwap'].shift())
    df['obv_up'] = (df['obv'] > df['obv_ema']) & (df['obv'].shift() <= df['obv_ema'].shift())
    df['obv_dn'] = (df['obv'] < df['obv_ema']) & (df['obv'].shift() >= df['obv_ema'].shift())
    
    # Новые сигналы
    df['squeeze_on'] = (df['bb_up'] < df['kc_up']) & (df['bb_dn'] > df['kc_dn'])
    df['squeeze_fire'] = (df['squeeze_on'].shift() == True) & (df['squeeze_on'] == False)
    
    if 'IMOEX_close' in df.columns:
        df['rs'] = df['close'] / df['IMOEX_close']
        df['rs_ema'] = df['rs'].ewm(span=20, adjust=False).mean()
    
    df['is_bull'] = df['close'] > df['sma200']
    df['is_bear'] = df['close'] < df['sma200']
    
    for i in range(200, len(df)):
        t = df.iloc[i]['begin']
        c = df.iloc[i]
        prev = df.iloc[i-1]
        
        if c['is_bull']:
            if c['cross_ema_up']: sigs.append((t, 1, 'EMA20/50'))
            if c['cross_macd_up']: sigs.append((t, 1, 'MACD'))
            if c['close'] > c['don20_high']: sigs.append((t, 1, 'Donchian20'))
            if c['close'] > c['don55_high']: sigs.append((t, 1, 'Donchian55'))
            if c['close'] > c['kc_up'] and prev['close'] <= prev['kc_up']: sigs.append((t, 1, 'Keltner'))
            if c['close'] > (c['don20_high'] + 0.25 * c['atr14']): sigs.append((t, 1, 'ATR'))
            if c['vwap_up']: sigs.append((t, 1, 'VWAP'))
            if c['obv_up']: sigs.append((t, 1, 'OBV'))
            if c['bull_engulf']: sigs.append((t, 1, 'Bull_Engulf'))
            if c['hammer']: sigs.append((t, 1, 'Hammer'))
            if c['morning_star']: sigs.append((t, 1, 'Morning_Star'))
            if c['bull_harami']: sigs.append((t, 1, 'Bull_Harami'))
            if c['rsi14'] > 30 and prev['rsi14'] <= 30: sigs.append((t, 1, 'RSI14'))
            if c['close'] > c['bb_dn'] and prev['close'] <= prev['bb_dn']: sigs.append((t, 1, 'Bollinger'))
            if c['close'] < c['vwap'] * 0.98 and c['close'] > c['open']: sigs.append((t, 1, 'VWAP_Reversion'))
            
            # Новые
            if c['squeeze_fire'] and c['close'] > c['open']: sigs.append((t, 1, 'Squeeze'))
            if c['z_score'] < -2.0: sigs.append((t, 1, 'ZScore'))
            if 'rs' in c and c['rs'] > c['rs_ema'] and prev['rs'] <= prev['rs_ema']: sigs.append((t, 1, 'RelativeStrength'))
            if c['inside_bar'] and c['close'] > c['high'].shift(1): sigs.append((t, 1, 'InsideBar'))
            if c['low'] <= c['s1'] and c['close'] > c['s1']: sigs.append((t, 1, 'Pivot'))
            if 'BR_close' in c and 'Si_close' in c:
                if c['BR_close'] > c['BR_ema20'] and c['Si_close'] < c['Si_ema20']: sigs.append((t, 1, 'Intermarket'))
            if c['gap'] > 0.01 and c['close'] > c['open']: sigs.append((t, 1, 'GapAndGo'))
            if c['begin'].weekday() == 0 and c['close'] > c['open']: sigs.append((t, 1, 'Seasonality'))
            if c['close'] > c['sma200'] and c['low'] <= c['ema20'] and c['close'] > c['ema20']: sigs.append((t, 1, 'Chandelier'))
        
        if c['is_bear']:
            if c['cross_ema_dn']: sigs.append((t, -1, 'EMA20/50'))
            if c['cross_macd_dn']: sigs.append((t, -1, 'MACD'))
            if c['close'] < c['don20_low']: sigs.append((t, -1, 'Donchian20'))
            if c['close'] < c['don55_low']: sigs.append((t, -1, 'Donchian55'))
            if c['close'] < c['kc_dn'] and prev['close'] >= prev['kc_dn']: sigs.append((t, -1, 'Keltner'))
            if c['close'] < (c['don20_low'] - 0.25 * c['atr14']): sigs.append((t, -1, 'ATR'))
            if c['vwap_dn']: sigs.append((t, -1, 'VWAP'))
            if c['obv_dn']: sigs.append((t, -1, 'OBV'))
            if c['bear_engulf']: sigs.append((t, -1, 'Bear_Engulf'))
            if c['shooting_star']: sigs.append((t, -1, 'Shooting_Star'))
            if c['evening_star']: sigs.append((t, -1, 'Evening_Star'))
            if c['bear_harami']: sigs.append((t, -1, 'Bear_Harami'))
            if c['three_black']: sigs.append((t, -1, 'Three_Black'))
            if c['rsi14'] < 70 and prev['rsi14'] >= 70: sigs.append((t, -1, 'RSI14'))
            if c['close'] < c['bb_up'] and prev['close'] >= prev['bb_up']: sigs.append((t, -1, 'Bollinger'))
            if c['close'] > c['vwap'] * 1.02 and c['close'] < c['open']: sigs.append((t, -1, 'VWAP_Reversion'))
            
            # Новые
            if c['squeeze_fire'] and c['close'] < c['open']: sigs.append((t, -1, 'Squeeze'))
            if c['z_score'] > 2.0: sigs.append((t, -1, 'ZScore'))
            if 'rs' in c and c['rs'] < c['rs_ema'] and prev['rs'] >= prev['rs_ema']: sigs.append((t, -1, 'RelativeStrength'))
            if c['inside_bar'] and c['close'] < c['low'].shift(1): sigs.append((t, -1, 'InsideBar'))
            if c['high'] >= c['r1'] and c['close'] < c['r1']: sigs.append((t, -1, 'Pivot'))
            if 'BR_close' in c and 'Si_close' in c:
                if c['BR_close'] < c['BR_ema20'] and c['Si_close'] > c['Si_ema20']: sigs.append((t, -1, 'Intermarket'))
            if c['gap'] < -0.01 and c['close'] < c['open']: sigs.append((t, -1, 'GapAndGo'))
            if c['begin'].weekday() == 4 and c['close'] < c['open']: sigs.append((t, -1, 'Seasonality'))
            if c['close'] < c['sma200'] and c['high'] >= c['ema20'] and c['close'] < c['ema20']: sigs.append((t, -1, 'Chandelier'))
            
    return sigs

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
    print("=== AI TRAINER (30+ стратегий) ===")
    d1_from = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    d1_till = datetime.now().strftime('%Y-%m-%d')
    
    # Загрузка референсов (IMOEX, BR, Si)
    ref_data = {}
    for ref_name, (board, _) in REF_TICKERS.items():
        print(f"Загрузка референса {ref_name}...")
        ref_data[ref_name] = fetch_candles(ref_name, 24, d1_from, d1_till, board)
    
    stats = {}
    for ticker in TICKERS:
        print(f"Анализ {ticker}...")
        d1 = fetch_candles(ticker, 24, d1_from, d1_till)
        if len(d1) < 200: continue
        h1 = fetch_candles(ticker, 60, d1_from, d1_till)
        if h1.empty: continue
        
        d1 = calc_indicators(d1, ref_data)
        sigs = get_signals(d1)
        
        for sig_time, direction, strat in sigs:
            next_h1 = h1[h1['begin'] > sig_time]
            if next_h1.empty: continue
            entry_time = next_h1.iloc[0]['begin']
            ret = simulate_trade(h1, entry_time, direction)
            if ret is not None:
                stats.setdefault(strat, []).append(ret)

    new_weights = {}
    print("\n=== РЕЗУЛЬТАТЫ СТРАТЕГИЙ ЗА 3 МЕСЯЦА ===")
    for strat, rets in stats.items():
        if len(rets) < 3:
            new_weights[strat] = 5
            print(f"{strat}: мало сделок ({len(rets)}), вес = 5")
            continue
            
        win = [r for r in rets if r > 0]
        loss = [r for r in rets if r < 0]
        win_rate = len(win) / len(rets)
        sum_win = sum(win)
        sum_loss = abs(sum(loss)) if loss else 1
        pf = sum_win / sum_loss if sum_loss > 0 else 10
        
        weight = min(10, max(1, int(pf * 1.5)))
        if win_rate < 0.3: weight = max(1, weight - 2)
            
        new_weights[strat] = weight
        print(f"{strat}: Сделок {len(rets)}, WR {win_rate*100:.0f}%, PF {pf:.2f} -> Вес: {weight}")

    with open(WEIGHTS_FILE, "w", encoding="utf-8") as f:
        json.dump(new_weights, f, ensure_ascii=False, indent=2)
    print(f"\nВеса сохранены в {WEIGHTS_FILE}")

if __name__ == "__main__":
    main()
