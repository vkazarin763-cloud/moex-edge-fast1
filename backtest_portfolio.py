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
FEE_ROUND = 0.0026
SL_PCT = 0.03
ACT_PCT = 2.0
TAKE_PCT = 5.0

STRATEGY_PRIORITY = {
    'Keltner': 10, 'ATR': 9, 'Donchian55': 8, 'Donchian20': 7,
    'Evening_Star': 6, 'Three_Black': 6, 'Dark_Cloud': 5, 'MACD': 5,
    'Candlestick': 4, 'ADX+DI': 4, 'Bollinger': 3, 'RSI14': 3,
    'Stochastic': 2, 'EMA20/50': 1
}
MIN_PRIORITY = 7

SECTOR_GROUPS = {
    'SBER': 'BANKS', 'SBERP': 'BANKS', 'VTBR': 'BANKS', 'MOEX': 'BANKS', 'SVCB': 'BANKS',
    'GAZP': 'OIL', 'ROSN': 'OIL', 'LKOH': 'OIL', 'NVTK': 'OIL', 'TATN': 'OIL', 'SNGS': 'OIL', 'SNGSP': 'OIL',
    'GMKN': 'METALS', 'NLMK': 'METALS', 'CHMF': 'METALS', 'MAGN': 'METALS', 'RUAL': 'METALS', 'ALRS': 'METALS', 'PLZL': 'METALS',
    'YDEX': 'TECH', 'VKCO': 'TECH', 'OZON': 'TECH', 'HEAD': 'TECH',
}

def iss_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except:
        return {}

def fetch_candles(ticker, interval, dfrom, dtill, is_index=False):
    if is_index:
        url = f"{ISS_BASE}/engines/stock/markets/index/boards/SNDX/securities/{ticker}/candles.json"
    else:
        url = f"{ISS_BASE}/engines/stock/markets/shares/boards/{BOARD}/securities/{ticker}/candles.json"
        
    rows_all, start = [], 0
    while True:
        p = {"from": dfrom, "till": dtill, "interval": interval, "start": start, "iss.reverse": "false"}
        b = iss_get(url, p).get("candles", {})
        cols = b.get("columns", [])
        rows = b.get("data", [])
        if not rows: break
        idx = {c: i for i, c in enumerate(cols)}
        for r in rows:
            rows_all.append([r[idx.get(c, 0)] for c in ["open","high","low","close","volume","begin"]])
        if len(rows) < 500: break
        start += len(rows)
        time.sleep(PAUSE)
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

def simulate_trade(h1_df, entry_time, direction):
    h1_future = h1_df[h1_df['begin'] >= entry_time].copy()
    if h1_future.empty: return None
    actual_entry = h1_future.iloc[0]['open']
    act_price = actual_entry * (1 + direction * ACT_PCT / 100)
    tp_price = actual_entry * (1 + direction * TAKE_PCT / 100)
    be_price = actual_entry * (1 + direction * FEE_ROUND)
    sl_price = actual_entry * (1 - direction * SL_PCT)
    activated = False
    
    for i in range(len(h1_future)):
        row = h1_future.iloc[i]
        op, hi, lo = row['open'], row['high'], row['low']
        if direction == 1:
            if op >= tp_price: return (tp_price, h1_future.iloc[i]['begin'], 'TP')
            if hi >= tp_price: return (tp_price, h1_future.iloc[i]['begin'], 'TP')
            if not activated:
                if op <= sl_price: return (op, h1_future.iloc[i]['begin'], 'SL')
                if lo <= sl_price: return (sl_price, h1_future.iloc[i]['begin'], 'SL')
                if hi >= act_price: activated = True
            else:
                if op <= be_price: return (op, h1_future.iloc[i]['begin'], 'BE')
                if lo <= be_price: return (be_price, h1_future.iloc[i]['begin'], 'BE')
        else:
            if op <= tp_price: return (tp_price, h1_future.iloc[i]['begin'], 'TP')
            if lo <= tp_price: return (tp_price, h1_future.iloc[i]['begin'], 'TP')
            if not activated:
                if op >= sl_price: return (op, h1_future.iloc[i]['begin'], 'SL')
                if hi >= sl_price: return (sl_price, h1_future.iloc[i]['begin'], 'SL')
                if lo <= act_price: activated = True
            else:
                if op >= be_price: return (op, h1_future.iloc[i]['begin'], 'BE')
                if hi >= be_price: return (be_price, h1_future.iloc[i]['begin'], 'BE')
                
    return (h1_future.iloc[-1]['close'], h1_future.iloc[-1]['begin'], 'OPEN')

def main():
    print("Загрузка индекса IMOEX...")
    imoex = fetch_candles("IMOEX", 24, "2024-01-01", "2026-11-13", is_index=True)
    imoex['change'] = (imoex['close'] - imoex['open']) / imoex['open'] * 100
    imoex_dict = dict(zip(imoex['begin'].dt.date, imoex['change']))

    all_signals = []
    h1_data = {}
    
    for ticker in TICKERS:
        print(f"Обработка {ticker}...")
        d1 = fetch_candles(ticker, 24, "2024-01-01", "2026-11-13")
        if len(d1) < 200: continue
        h1 = fetch_candles(ticker, 60, "2024-01-01", "2026-11-13")
        if h1.empty: continue
        h1_data[ticker] = h1
        
        d1 = calc_indicators(d1)
        
        # Собираем все сигналы за всю историю
        for i in range(200, len(d1)):
            df_slice = d1.iloc[:i+1].copy()
            sigs = get_signals(df_slice)
            for t, direction, strat in sigs:
                prio = STRATEGY_PRIORITY.get(strat, 0)
                if prio >= MIN_PRIORITY:
                    all_signals.append({
                        'date': t.date(), 'ticker': ticker, 'direction': direction, 
                        'strategy': strat, 'prio': prio, 'entry_price': df_slice.iloc[-1]['close']
                    })

    # Симуляция портфеля
    print("Симуляция портфеля...")
    all_signals.sort(key=lambda x: (x['date'], -x['prio']))
    
    active_sectors = {} # sector -> exit_date
    active_tickers = {} # ticker -> exit_date
    results = []

    for sig in all_signals:
        d = sig['date']
        ticker = sig['ticker']
        direction = sig['direction']
        sector = SECTOR_GROUPS.get(ticker)
        
        # 1. Проверка: не занят ли тикер
        if ticker in active_tickers and active_tickers[ticker] > d: continue
        
        # 2. Проверка: не занят ли сектор
        if sector and sector in active_sectors and active_sectors[sector] > d: continue
        
        # 3. Проверка рыночного режима
        if direction == 1:
            change = imoex_dict.get(d, 0)
            if change < -1.0: continue
            
        # Симуляция
        h1 = h1_data[ticker]
        next_h1 = h1[h1['begin'].dt.date >= d]
        if next_h1.empty: continue
        entry_time = next_h1.iloc[0]['begin']
        
        res = simulate_trade(h1, entry_time, direction)
        if not res: continue
        
        exit_price, exit_time, exit_reason = res
        entry_price = next_h1.iloc[0]['open']
        net_ret = (direction * (exit_price - entry_price) / entry_price) - FEE_ROUND
        
        # Обновляем занятость
        active_tickers[ticker] = exit_time.date()
        if sector: active_sectors[sector] = exit_time.date()
        
        results.append({'ticker': ticker, 'direction': direction, 'net_ret': net_ret, 'exit_reason': exit_reason})

    # Итоговая статистика
    if results:
        df_res = pd.DataFrame(results)
        win = df_res[df_res['net_ret'] > 0]
        loss = df_res[df_res['net_ret'] <= 0]
        pf = win['net_ret'].sum() / abs(loss['net_ret'].sum()) if len(loss) > 0 else np.nan
        
        print("\n================ РЕЗУЛЬТАТЫ ПОРТФЕЛЯ С ФИЛЬТРАМИ ================")
        print(f"Всего сделок: {len(df_res)}")
        print(f"Win Rate: {len(win) / len(df_res) * 100:.1f}%")
        print(f"Profit Factor: {pf:.2f}")
        print(f"Средняя прибыль на сделку: {df_res['net_ret'].mean() * 100:.2f}%")
        print(f"Общий PnL (в %): {df_res['net_ret'].sum() * 100:.1f}%")
        
        # Распределение причин выхода
        print("\nПричины выхода:")
        print(df_res['exit_reason'].value_counts().to_string())
    else:
        print("Нет сделок.")

if __name__ == "__main__":
    main()
