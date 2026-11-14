import time
import requests
import pandas as pd
import numpy as np
import warnings
from datetime import datetime, timedelta
warnings.filterwarnings('ignore')

# Базовые коды фьючерсов (30 самых ликвидных контрактов MOEX)
TARGET_ASSETS = [
    # 1. Индексы
    'MIX', 'RTS', 'MOEXCNY',
    # 2. Валюта
    'Si', 'CNY', 'Eu',
    # 3. Сырье и Товары
    'BR', 'GOLD', 'SILV', 'PLT', 'NG', 'WTI',
    # 4. Акции (Single Stock Futures)
    'SBRF', 'GAZR', 'LKOH', 'ROSN', 'VTBR', 
    'T', 'MGNT', 'NVTK', 'PLZL', 'SNGR', 'ALRS', 
    'MTSS', 'GMKN', 'CHMF', 'NLMK', 'MOEX', 'AFLT'
]

REC_TAKE_PCT = 5.0
REC_BE_PCT = 2.0
REC_SL_PCT = 3.0

# ПРИОРИТЕТ СТРАТЕГИЙ
STRATEGY_PRIORITY = {
    'Keltner': 10, 'ATR': 9, 'Donchian55': 8, 'Donchian20': 7,
    'Evening_Star': 6, 'Three_Black': 6, 'Dark_Cloud': 5, 'MACD': 5,
    'Candlestick': 4, 'ADX+DI': 4, 'Bollinger': 3, 'RSI14': 3,
    'Stochastic': 2, 'EMA20/50': 1
}

MIN_PRIORITY_THRESHOLD = 7

def get_iss_json(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Ошибка запроса к ISS: {e}")
        return {}

def get_active_futures():
    url = "https://iss.moex.com/iss/engines/futures/markets/forts/securities.json"
    payload = get_iss_json(url)
    if not payload: return {}
    
    data = payload.get('securities', {})
    cols = data.get('columns', [])
    rows = data.get('data', [])
    
    df = pd.DataFrame(rows, columns=cols)
    df = df[df['ASSETCODE'].isin(TARGET_ASSETS)].copy()
    
    df['LASTTRADEDATE'] = pd.to_datetime(df['LASTTRADEDATE'], errors='coerce')
    df = df.dropna(subset=['LASTTRADEDATE'])
    df = df[df['LASTTRADEDATE'] > datetime.now()]
    df = df.sort_values('LASTTRADEDATE')
    
    active = df.groupby('ASSETCODE').first().reset_index()
    return active[['ASSETCODE', 'SECID']].to_dict('records')

def fetch_candles(secid, interval, days_back):
    d_from = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    d_till = datetime.now().strftime('%Y-%m-%d')
    url = f"https://iss.moex.com/iss/engines/futures/markets/forts/securities/{secid}/candles.json"
    
    rows_all = []
    start = 0
    while True:
        params = {"from": d_from, "till": d_till, "interval": interval, "start": start, "iss.reverse": "false"}
        payload = get_iss_json(url, params)
        data = payload.get('candles', {})
        cols = data.get('columns', [])
        rows = data.get('data', [])
        if not rows: break
        
        idx = {c: i for i, c in enumerate(cols)}
        for r in rows:
            rows_all.append([r[idx.get(c, 0)] for c in ["open","high","low","close","volume","begin"]])
            
        if len(rows) < 500: break
        start += len(rows)
        time.sleep(0.2)
        
    if not rows_all: return pd.DataFrame()
    
    df = pd.DataFrame(rows_all, columns=["open","high","low","close","volume","begin"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df["begin"] = pd.to_datetime(df["begin"])
    return df.dropna().sort_values("begin").reset_index(drop=True)

def calc_indicators(df):
    df = df.copy()
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    tr = pd.concat([df['high']-df['low'], (df['high']-df['close'].shift()).abs(), (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.rolling(14).mean()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi14'] = 100 - (100 / (1 + (gain / loss)))
    df['macd'] = df['close'].ewm(span=12, adjust=False).mean() - df['close'].ewm(span=26, adjust=False).mean()
    df['macd_sig'] = df['macd'].ewm(span=9, adjust=False).mean()
    up = df['high'] - df['high'].shift()
    down = df['low'].shift() - df['low']
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr_s = pd.Series(tr)
    atr_s = tr_s.rolling(14).mean()
    df['di_plus'] = 100 * pd.Series(plus_dm).rolling(14).mean() / atr_s
    df['di_minus'] = 100 * pd.Series(minus_dm).rolling(14).mean() / atr_s
    dx = 100 * (df['di_plus'] - df['di_minus']).abs() / (df['di_plus'] + df['di_minus'])
    df['adx14'] = dx.rolling(14).mean()
    df['don20_high'] = df['high'].rolling(20).max().shift(1)
    df['don20_low'] = df['low'].rolling(20).min().shift(1)
    df['don55_high'] = df['high'].rolling(55).max().shift(1)
    df['don55_low'] = df['low'].rolling(55).min().shift(1)
    df['bb_mid'] = df['close'].rolling(20).mean()
    df['bb_std'] = df['close'].rolling(20).std()
    df['bb_up'] = df['bb_mid'] + 2 * df['bb_std']
    df['bb_dn'] = df['bb_mid'] - 2 * df['bb_std']
    df['stoch_k'] = 100 * (df['close'] - df['low'].rolling(14).min()) / (df['high'].rolling(14).max() - df['low'].rolling(14).min())
    df['stoch_d'] = df['stoch_k'].rolling(3).mean()
    
    df['kc_up'] = df['ema20'] + 2 * df['atr14']
    df['kc_dn'] = df['ema20'] - 2 * df['atr14']
    
    df['body'] = (df['close'] - df['open']).abs()
    df['c_upper'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['c_lower'] = df[['open', 'close']].min(axis=1) - df['low']
    
    df['bull_engulf'] = (df['close'] > df['open']) & (df['close'].shift() < df['open'].shift()) & (df['close'] > df['open'].shift()) & (df['open'] < df['close'].shift())
    df['bear_engulf'] = (df['close'] < df['open']) & (df['close'].shift() > df['open'].shift()) & (df['close'] < df['open'].shift()) & (df['open'] > df['close'].shift())
    df['hammer'] = (df['c_lower'] > 2 * df['body']) & (df['c_upper'] < 0.3 * df['body'])
    df['shooting_star'] = (df['c_upper'] > 2 * df['body']) & (df['c_lower'] < 0.3 * df['body'])
    
    df['evening_star'] = (df['close'].shift(2) > df['open'].shift(2)) & (df['body'].shift(1) < df['body'].shift(2) * 0.5) & (df['close'] < df['open']) & (df['close'] < (df['open'].shift(2) + df['close'].shift(2))/2)
    df['three_black'] = (df['close'] < df['open']) & (df['close'].shift() < df['open'].shift()) & (df['close'].shift(2) < df['open'].shift(2)) & (df['close'] < df['close'].shift()) & (df['close'].shift() < df['close'].shift(2))
    df['dark_cloud'] = (df['close'].shift() > df['open'].shift()) & (df['open'] > df['high'].shift()) & (df['close'] < (df['open'].shift() + df['close'].shift())/2) & (df['close'] > df['open'].shift())
    
    return df

def get_signals(df):
    sigs = []
    df['cross_ema_up'] = (df['ema20'] > df['ema50']) & (df['ema20'].shift() <= df['ema50'].shift())
    df['cross_ema_dn'] = (df['ema20'] < df['ema50']) & (df['ema20'].shift() >= df['ema50'].shift())
    df['cross_macd_up'] = (df['macd'] > df['macd_sig']) & (df['macd'].shift() <= df['macd_sig'].shift())
    df['cross_macd_dn'] = (df['macd'] < df['macd_sig']) & (df['macd'].shift() >= df['macd_sig'].shift())
    df['cross_adx_up'] = (df['di_plus'] > df['di_minus']) & (df['di_plus'].shift() <= df['di_minus'].shift()) & (df['adx14'] > 20)
    df['cross_adx_dn'] = (df['di_plus'] < df['di_minus']) & (df['di_plus'].shift() >= df['di_minus'].shift()) & (df['adx14'] > 20)
    df['break_don20_up'] = df['close'] > df['don20_high']
    df['break_don20_dn'] = df['close'] < df['don20_low']
    df['break_don55_up'] = df['close'] > df['don55_high']
    df['break_don55_dn'] = df['close'] < df['don55_low']
    df['rsi_buy'] = (df['rsi14'] > 30) & (df['rsi14'].shift() <= 30)
    df['rsi_sell'] = (df['rsi14'] < 70) & (df['rsi14'].shift() >= 70)
    df['bb_buy'] = (df['close'] > df['bb_dn']) & (df['close'].shift() <= df['bb_dn'].shift())
    df['bb_sell'] = (df['close'] < df['bb_up']) & (df['close'].shift() >= df['bb_up'].shift())
    df['stoch_buy'] = (df['stoch_k'] > df['stoch_d']) & (df['stoch_k'].shift() <= df['stoch_d'].shift()) & (df['stoch_k'] < 20)
    df['stoch_sell'] = (df['stoch_k'] < df['stoch_d']) & (df['stoch_k'].shift() >= df['stoch_d'].shift()) & (df['stoch_k'] > 80)
    df['atr_break_up'] = df['close'] > (df['don20_high'] + 0.25 * df['atr14'])
    df['atr_break_dn'] = df['close'] < (df['don20_low'] - 0.25 * df['atr14'])
    df['keltner_up'] = (df['close'] > df['kc_up']) & (df['close'].shift() <= df['kc_up'].shift())
    df['keltner_dn'] = (df['close'] < df['kc_dn']) & (df['close'].shift() >= df['kc_dn'].shift())
    
    df['is_bull'] = df['close'] > df['ema200']
    df['is_bear'] = df['close'] < df['ema200']
    
    i = len(df) - 1
    t = df.iloc[i]['begin'] 
    c = df.iloc[i]
    
    if c['is_bull']:
        if c['cross_ema_up']: sigs.append((t, 1, 'EMA20/50'))
        if c['cross_macd_up']: sigs.append((t, 1, 'MACD'))
        if c['cross_adx_up']: sigs.append((t, 1, 'ADX+DI'))
        if c['break_don20_up']: sigs.append((t, 1, 'Donchian20'))
        if c['break_don55_up']: sigs.append((t, 1, 'Donchian55'))
        if c['rsi_buy']: sigs.append((t, 1, 'RSI14'))
        if c['bb_buy']: sigs.append((t, 1, 'Bollinger'))
        if c['stoch_buy']: sigs.append((t, 1, 'Stochastic'))
        if c['atr_break_up']: sigs.append((t, 1, 'ATR'))
        if c['bull_engulf'] or c['hammer']: sigs.append((t, 1, 'Candlestick'))
        if c['keltner_up']: sigs.append((t, 1, 'Keltner'))
        
    if c['is_bear']:
        if c['cross_ema_dn']: sigs.append((t, -1, 'EMA20/50'))
        if c['cross_macd_dn']: sigs.append((t, -1, 'MACD'))
        if c['cross_adx_dn']: sigs.append((t, -1, 'ADX+DI'))
        if c['break_don20_dn']: sigs.append((t, -1, 'Donchian20'))
        if c['break_don55_dn']: sigs.append((t, -1, 'Donchian55'))
        if c['rsi_sell']: sigs.append((t, -1, 'RSI14'))
        if c['bb_sell']: sigs.append((t, -1, 'Bollinger'))
        if c['stoch_sell']: sigs.append((t, -1, 'Stochastic'))
        if c['atr_break_dn']: sigs.append((t, -1, 'ATR'))
        if c['bear_engulf'] or c['shooting_star']: sigs.append((t, -1, 'Candlestick'))
        if c['evening_star']: sigs.append((t, -1, 'Evening_Star'))
        if c['three_black']: sigs.append((t, -1, 'Three_Black'))
        if c['dark_cloud']: sigs.append((t, -1, 'Dark_Cloud'))
        if c['keltner_dn']: sigs.append((t, -1, 'Keltner'))
        
    return sigs

def main():
    print(f"=== Сканер фьючерсов MOEX (Sniper Mode) ===")
    active_contracts = get_active_futures()
    
    if not active_contracts:
        print("Не удалось найти активные контракты.")
        return
        
    print(f"Найдено контрактов: {len(active_contracts)}")
    signals_found = []
    
    for contract in active_contracts:
        asset = contract['ASSETCODE']
        secid = contract['SECID']
        print(f"Обработка {asset} ({secid})...")
        
        d1 = fetch_candles(secid, 24, 400)
        if len(d1) < 200: 
            continue
            
        d1 = calc_indicators(d1)
        d1_sigs = get_signals(d1)
        
        if not d1_sigs: continue
        
        # ФИЛЬТР ПРИОРИТЕТА
        sorted_sigs = sorted(d1_sigs, key=lambda x: STRATEGY_PRIORITY.get(x[2], 0), reverse=True)
        best_sig = sorted_sigs[0]
        
        if STRATEGY_PRIORITY.get(best_sig[2], 0) < MIN_PRIORITY_THRESHOLD:
            continue
            
        t, direction, strat = best_sig
        
        h1 = fetch_candles(secid, 60, 5)
        if h1.empty: continue
        
        h1['ema20'] = h1['close'].ewm(span=20, adjust=False).mean()
        last_h1 = h1.iloc[-1]
        entry_price = last_h1['close']
        
        h1_confirmed = False
        if direction == 1 and entry_price > last_h1['ema20']: h1_confirmed = True
        elif direction == -1 and entry_price < last_h1['ema20']: h1_confirmed = True
        
        signals_found.append({
            'asset': asset,
            'secid': secid,
            'direction': 'LONG' if direction == 1 else 'SHORT',
            'strategy': strat,
            'h1_confirmed': h1_confirmed,
            'date': t,
            'entry_price': entry_price
        })

    if signals_found:
        df_res = pd.DataFrame(signals_found)
        df_res.to_csv("futures_signals.csv", index=False)
    else:
        pd.DataFrame(columns=["asset","secid","direction","strategy","h1_confirmed","date","entry_price"]).to_csv("futures_signals.csv", index=False)

    print("\n" + "="*50)
    if not signals_found:
        print("Сильных сигналов по фьючерсам нет.")
    else:
        for s in signals_found:
            status = "✅ H1 ПОДТВЕРЖДЕН" if s['h1_confirmed'] else "❌ H1 НЕ ПОДТВЕРЖДЕН"
            print(f"\n🎯 СИЛЬНЫЙ СИГНАЛ: {s['direction']} {s['asset']} ({s['secid']}) по стратегии {s['strategy']}")
            print(f"   Цена входа: {s['entry_price']:.2f} | Статус: {status}")
            if s['h1_confirmed']:
                print(f"   👉 РЕКОМЕНДАЦИЯ: Вход. Стоп: {REC_SL_PCT}% | Тейк: {REC_TAKE_PCT}% | БУ: {REC_BE_PCT}%")

if __name__ == "__main__":
    main()
