import time
import requests
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

ISS_BASE = "https://iss.moex.com/iss"
BOARD = "TQBR"
PAUSE = 0.2

TICKERS = ["SBER", "GAZP", "LKOH", "ROSN", "NVTK", "TATN", "MTSS", "MOEX", "VTBR", "YDEX"]
COMBOS = [(2, 5)] # Фокусируемся на лучшей комбинации выходов
FEE_ROUND = 0.0026
SL_PCT = 0.03

STRATEGY_PRIORITY = {
    'Keltner': 10, 'ATR': 9, 'Donchian55': 8, 'Donchian20': 7,
    'Evening_Star': 6, 'Three_Black': 6, 'Dark_Cloud': 5, 'MACD': 5,
    'Candlestick': 4, 'ADX+DI': 4, 'Bollinger': 3, 'RSI14': 3,
    'Stochastic': 2, 'EMA20/50': 1
}

# Порядок старых стратегий (как они шли в коде бота)
OLD_ORDER = ['EMA20/50', 'MACD', 'ADX+DI', 'Donchian20', 'Donchian55', 'RSI14', 'Bollinger', 'Stochastic', 'ATR', 'Candlestick', 'Keltner', 'Evening_Star', 'Three_Black', 'Dark_Cloud']

def iss_get(url, params=None, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200: return r.json()
            if 500 <= r.status_code < 600: time.sleep(1+i); continue
            r.raise_for_status()
        except requests.RequestException:
            if i == retries-1: return {}
            time.sleep(1+i)
    return {}

def fetch_candles(ticker, interval, dfrom, dtill):
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
    df = df.dropna().reset_index(drop=True)
    df["begin"] = pd.to_datetime(df["begin"])
    return df.sort_values("begin").reset_index(drop=True)

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

def get_signals_per_day(df):
    """Возвращает список всех сигналов на последнюю свечу"""
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
    
    # Берем только последнюю свечу (как делает сканер)
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
        if c['evening_star']: sigs.append((t, 1, 'Evening_Star'))
        if c['three_black']: sigs.append((t, 1, 'Three_Black'))
        if c['dark_cloud']: sigs.append((t, 1, 'Dark_Cloud'))
        
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

def simulate_trade(h1_df, entry_time, direction, act_pct, take_pct):
    h1_future = h1_df[h1_df['begin'] >= entry_time].copy()
    if h1_future.empty: return None
    actual_entry = h1_future.iloc[0]['open']
    act_price = actual_entry * (1 + direction * act_pct / 100)
    tp_price = actual_entry * (1 + direction * take_pct / 100)
    be_price = actual_entry * (1 + direction * FEE_ROUND)
    sl_price = actual_entry * (1 - direction * SL_PCT)
    activated = False
    mae = 0.0
    for i in range(len(h1_future)):
        row = h1_future.iloc[i]
        op, hi, lo = row['open'], row['high'], row['low']
        if direction == 1:
            mae = min(mae, (lo - actual_entry) / actual_entry)
            if op >= tp_price: return (tp_price, i, 'TP', mae)
            if hi >= tp_price: return (tp_price, i, 'TP', mae)
            if not activated:
                if op <= sl_price: return (op, i, 'SL', mae)
                if lo <= sl_price: return (sl_price, i, 'SL', mae)
                if hi >= act_price: activated = True
            else:
                if op <= be_price: return (op, i, 'BE', mae)
                if lo <= be_price: return (be_price, i, 'BE', mae)
        else:
            mae = min(mae, (actual_entry - hi) / actual_entry)
            if op <= tp_price: return (tp_price, i, 'TP', mae)
            if lo <= tp_price: return (tp_price, i, 'TP', mae)
            if not activated:
                if op >= sl_price: return (op, i, 'SL', mae)
                if hi >= sl_price: return (sl_price, i, 'SL', mae)
                if lo <= act_price: activated = True
            else:
                if op >= be_price: return (op, i, 'BE', mae)
                if hi >= be_price: return (be_price, i, 'BE', mae)
    return (h1_future.iloc[-1]['close'], len(h1_future)-1, 'OPEN', mae)

def main():
    all_results = []
    for ticker in TICKERS:
        print(f"Обработка {ticker}...")
        d1 = fetch_candles(ticker, 24, "2024-01-01", "2026-11-13")
        if len(d1) < 200: continue
        h1 = fetch_candles(ticker, 60, "2024-01-01", "2026-11-13")
        if h1.empty: continue
        
        # Прогоняем сканер по всей истории
        d1_calc = calc_indicators(d1)
        
        for i in range(200, len(d1_calc)):
            # Отрезаем данные до текущего дня (как в реальном времени)
            df_slice = d1_calc.iloc[:i+1].copy()
            sigs = get_signals_per_day(df_slice)
            
            if not sigs: continue
            
            sig_date = sigs[0][0]
            next_h1 = h1[h1['begin'] > sig_date]
            if next_h1.empty: continue
            entry_time = next_h1.iloc[0]['begin']
            
            # ==========================================
            # СЦЕНАРИЙ 1: СТАРЫЙ МЕТОД (Берем первый по порядку)
            # ==========================================
            first_sig = sigs[0]
            res_old = simulate_trade(h1, entry_time, first_sig[1], 2, 5)
            if res_old:
                exit_price, bars_held, exit_reason, mae = res_old
                entry_price = h1[h1['begin'] == entry_time].iloc[0]['open']
                net_ret = (first_sig[1] * (exit_price - entry_price) / entry_price) - FEE_ROUND
                all_results.append({'method': 'Old_NoPriority', 'strategy': first_sig[2], 'direction': 'LONG' if first_sig[1] == 1 else 'SHORT', 'entry_time': entry_time, 'net_ret': net_ret})

            # ==========================================
            # СЦЕНАРИЙ 2: НОВЫЙ МЕТОД (Приоритет)
            # ==========================================
            # Сортируем сигналы по убыванию приоритета
            sorted_sigs = sorted(sigs, key=lambda x: STRATEGY_PRIORITY.get(x[2], 0), reverse=True)
            best_sig = sorted_sigs[0]
            
            res_new = simulate_trade(h1, entry_time, best_sig[1], 2, 5)
            if res_new:
                exit_price, bars_held, exit_reason, mae = res_new
                entry_price = h1[h1['begin'] == entry_time].iloc[0]['open']
                net_ret = (best_sig[1] * (exit_price - entry_price) / entry_price) - FEE_ROUND
                all_results.append({'method': 'New_Priority', 'strategy': best_sig[2], 'direction': 'LONG' if best_sig[1] == 1 else 'SHORT', 'entry_time': entry_time, 'net_ret': net_ret})

    df_res = pd.DataFrame(all_results)
    df_res['period'] = np.where(df_res['entry_time'].dt.year <= 2025, 'Train', 'Test')
    
    def agg_stats(g):
        win = g[g['net_ret'] > 0]
        loss = g[g['net_ret'] <= 0]
        pf = win['net_ret'].sum() / abs(loss['net_ret'].sum()) if len(loss) > 0 and loss['net_ret'].sum() != 0 else np.nan
        return pd.Series({'trades': len(g), 'win_rate': len(win) / len(g), 'avg_ret': g['net_ret'].mean(), 'profit_factor': pf})

    summary = df_res.groupby(['method', 'period']).apply(agg_stats).reset_index()
    print("\n================ СРАВНЕНИЕ: СТАРЫЙ БОТ vs НОВЫЙ БОТ ================")
    print(summary.to_string(index=False))

if __name__ == "__main__":
    main()
