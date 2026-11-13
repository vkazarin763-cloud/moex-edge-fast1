import time
import requests
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

ISS_BASE = "https://iss.moex.com/iss"
BOARD = "TQBR"
PAUSE = 0.2

# 10 самых ликвидных акций для быстрого и честного теста
TICKERS = ["SBER", "GAZP", "LKOH", "ROSN", "NVTK", "TATN", "MTSS", "MOEX", "VTBR", "YDEX"]

ACTIVATIONS = [1, 2, 3, 5, 7]
TAKES = [3, 5, 7, 10, 12, 15, 20]
COMBOS = [(a, t) for a in ACTIVATIONS for t in TAKES]
FEE_ROUND = 0.0026
SL_PCT = 0.03  # Первоначальный стоп-лосс 3%

def iss_get(url, params=None, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200: return r.json()
            if 500 <= r.status_code < 600: time.sleep(1+i); continue
            r.raise_for_status()
        except requests.RequestException:
            if i == retries-1: raise
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
    df["begin"] = pd.to_datetime(df["begin"])
    return df.sort_values("begin").reset_index(drop=True)

def calc_indicators(df):
    df = df.copy()
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
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
    df['body'] = (df['close'] - df['open']).abs()
    df['c_upper'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['c_lower'] = df[['open', 'close']].min(axis=1) - df['low']
    df['bull_engulf'] = (df['close'] > df['open']) & (df['close'].shift() < df['open'].shift()) & (df['close'] > df['open'].shift()) & (df['open'] < df['close'].shift())
    df['bear_engulf'] = (df['close'] < df['open']) & (df['close'].shift() > df['open'].shift()) & (df['close'] < df['open'].shift()) & (df['open'] > df['close'].shift())
    df['hammer'] = (df['c_lower'] > 2 * df['body']) & (df['c_upper'] < 0.3 * df['body'])
    df['shooting_star'] = (df['c_upper'] > 2 * df['body']) & (df['c_lower'] < 0.3 * df['body'])
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
    
    for i in range(200, len(df)):
        t = df.iloc[i]['begin'] 
        c = df.iloc[i]
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
    return sigs

def simulate_trade(h1_df, entry_time, direction, act_pct, take_pct):
    h1_future = h1_df[h1_df['begin'] >= entry_time]
    if h1_future.empty: return None
    actual_entry = h1_future.iloc[0]['open']
    
    act_price = actual_entry * (1 + direction * act_pct / 100)
    tp_price = actual_entry * (1 + direction * take_pct / 100)
    be_price = actual_entry * (1 + direction * FEE_ROUND)
    sl_price = actual_entry * (1 - direction * SL_PCT) # СТОП-ЛОСС
    
    activated = False
    mae = 0.0
    
    for i in range(len(h1_future)):
        row = h1_future.iloc[i]
        op, hi, lo = row['open'], row['high'], row['low']
        
        if direction == 1: # LONG
            mae = min(mae, (lo - actual_entry) / actual_entry)
            # Проверка ТП
            if op >= tp_price: return (tp_price, i, 'TP', mae)
            if hi >= tp_price: return (tp_price, i, 'TP', mae)
            
            # Проверка Стоп-Лосса (если не активирован безубыток)
            if not activated:
                if op <= sl_price: return (op, i, 'SL', mae)
                if lo <= sl_price: return (sl_price, i, 'SL', mae)
                if hi >= act_price: activated = True
            else:
                # Проверка Безубытка (если активирован)
                if op <= be_price: return (op, i, 'BE', mae)
                if lo <= be_price: return (be_price, i, 'BE', mae)
                
        else: # SHORT
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
        try:
            d1 = fetch_candles(ticker, 24, "2024-01-01", "2026-11-13")
            if len(d1) < 200: continue
            d1 = calc_indicators(d1)
            signals = get_signals(d1)
            if not signals: continue
            h1 = fetch_candles(ticker, 60, "2024-01-01", "2026-11-13")
            if h1.empty: continue
            
            for strat in set([s[2] for s in signals]):
                for direction in [1, -1]:
                    strat_sigs = [(t, d) for t, d, s in signals if s == strat and d == direction]
                    if not strat_sigs: continue
                    for act, take in COMBOS:
                        trade_end_time = pd.Timestamp.min
                        for sig_time, _ in strat_sigs:
                            if sig_time <= trade_end_time: continue
                            next_h1 = h1[h1['begin'] > sig_time]
                            if next_h1.empty: continue
                            entry_time = next_h1.iloc[0]['begin']
                            res = simulate_trade(h1, entry_time, direction, act, take)
                            if not res: continue
                            exit_price, bars_held, exit_reason, mae = res
                            entry_price = h1[h1['begin'] == entry_time].iloc[0]['open']
                            net_ret = (direction * (exit_price - entry_price) / entry_price) - FEE_ROUND
                            trade_end_time = entry_time + pd.Timedelta(hours=bars_held)
                            all_results.append({'ticker': ticker, 'strategy': strat, 'direction': 'LONG' if direction == 1 else 'SHORT', 'act': act, 'take': take, 'entry_time': entry_time, 'net_ret': net_ret, 'exit_reason': exit_reason, 'mae': mae, 'bars': bars_held})
        except Exception as e:
            print(f"Ошибка {ticker}: {e}")

    if not all_results:
        print("Нет сделок."); return

    df_res = pd.DataFrame(all_results)
    df_res['year'] = df_res['entry_time'].dt.year
    df_res['period'] = np.where(df_res['year'] <= 2025, 'Train', 'Test')
    
    def agg_stats(g):
        closed = g[g['exit_reason'] != 'OPEN']
        opn = g[g['exit_reason'] == 'OPEN']
        win = closed[closed['net_ret'] > 0]
        loss = closed[closed['net_ret'] <= 0]
        pf = win['net_ret'].sum() / abs(loss['net_ret'].sum()) if len(loss) > 0 and loss['net_ret'].sum() != 0 else np.nan
        return pd.Series({'trades': len(closed), 'win_rate': len(win) / len(closed) if len(closed) > 0 else 0, 'avg_ret': closed['net_ret'].mean(), 'profit_factor': pf, 'avg_bars': closed['bars'].mean(), 'open_trades': len(opn), 'worst_open_pnl': opn['net_ret'].min() if len(opn) > 0 else 0})

    summary = df_res.groupby(['period', 'strategy', 'direction', 'act', 'take']).apply(agg_stats).reset_index()
    summary.to_csv("backtest_results.csv", index=False)
    
    # Показываем ТОП-15 лучших комбинаций, где было минимум 15 сделок
    best = summary[(summary['trades'] >= 15)].sort_values('profit_factor', ascending=False).head(15)
    
    print("\n================ ТОП-15 ЛУЧШИХ КОМБИНАЦИЙ (со стоп-лоссом 3%) ================")
    print(best.to_string(index=False))
    print("\n(Файл с полными данными по всем 35 комбинациям сохранен в артефактах)")

if __name__ == "__main__":
    main()
