import time
import requests
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

ISS_BASE = "https://iss.moex.com/iss"
BOARD = "TQBR"
PAUSE = 0.2

COMBOS = [(2, 5), (3, 7)]
FEE_ROUND = 0.0026
SL_PCT = 0.03

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
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    tr = pd.concat([df['high']-df['low'], (df['high']-df['close'].shift()).abs(), (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.rolling(14).mean()
    
    # Канал Кельтнера
    df['kc_up'] = df['ema20'] + 2 * df['atr14']
    df['kc_dn'] = df['ema20'] - 2 * df['atr14']
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi14'] = 100 - (100 / (1 + (gain / loss)))
    
    return df

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
    
    # ==========================================
    # ТЕСТ 1: Keltner Channel (Адаптивный тренд)
    # ==========================================
    print("Тестирование Keltner Channel...")
    for ticker in ["SBER", "GAZP", "LKOH", "ROSN", "NVTK"]:
        d1 = fetch_candles(ticker, 24, "2024-01-01", "2026-11-13")
        if len(d1) < 200: continue
        d1 = calc_indicators(d1)
        h1 = fetch_candles(ticker, 60, "2024-01-01", "2026-11-13")
        if h1.empty: continue
        
        # Сигналы Keltner
        d1['long_sig'] = (d1['close'] > d1['kc_up']) & (d1['close'].shift() <= d1['kc_up'].shift()) & (d1['close'] > d1['ema200'])
        d1['short_sig'] = (d1['close'] < d1['kc_dn']) & (d1['close'].shift() >= d1['kc_dn'].shift()) & (d1['close'] < d1['ema200'])
        
        sigs = []
        for i in range(200, len(d1)):
            if d1.iloc[i]['long_sig']: sigs.append((d1.iloc[i]['begin'], 1, 'Keltner_LONG'))
            if d1.iloc[i]['short_sig']: sigs.append((d1.iloc[i]['begin'], -1, 'Keltner_SHORT'))
            
        for strat in set([s[2] for s in sigs]):
            for direction in [1, -1]:
                strat_sigs = [(t, d) for t, d, s in sigs if s == strat and d == direction]
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
                        all_results.append({'strategy': strat, 'direction': 'LONG' if direction == 1 else 'SHORT', 'act': act, 'take': take, 'entry_time': entry_time, 'net_ret': net_ret, 'exit_reason': exit_reason, 'mae': mae, 'bars': bars_held})

    # ==========================================
    # ТЕСТ 2: Pairs Trading (SBER / SBERP)
    # ==========================================
    print("Тестирование Pairs Trading (SBER/SBERP)...")
    sber = fetch_candles("SBER", 24, "2024-01-01", "2026-11-13")
    sberp = fetch_candles("SBERP", 24, "2024-01-01", "2026-11-13")
    h1_sber = fetch_candles("SBER", 60, "2024-01-01", "2026-11-13")
    
    if not sber.empty and not sberp.empty and not h1_sber.empty:
        # Сливаем по датам
        merged = pd.merge(sber[['begin', 'close']], sberp[['begin', 'close']], on='begin', suffixes=('_SBER', '_SBERP'))
        merged['spread'] = merged['close_SBER'] / merged['close_SBERP']
        merged['mean'] = merged['spread'].rolling(30).mean()
        merged['std'] = merged['spread'].rolling(30).std()
        merged['z_score'] = (merged['spread'] - merged['mean']) / merged['std']
        
        # Сигналы: z > 2 (SBER дорог относительно SBERP) -> Шорт SBER, Лонг SBERP
        # z < -2 (SBER дешев) -> Лонг SBER, Шорт SBERP
        merged['long_sber'] = (merged['z_score'] < -2) & (merged['z_score'].shift() >= -2)
        merged['short_sber'] = (merged['z_score'] > 2) & (merged['z_score'].shift() <= 2)
        
        sigs = []
        for i in range(30, len(merged)):
            if merged.iloc[i]['long_sber']: sigs.append((merged.iloc[i]['begin'], 1, 'Pairs_LONG'))
            if merged.iloc[i]['short_sber']: sigs.append((merged.iloc[i]['begin'], -1, 'Pairs_SHORT'))
            
        # Симулируем только ногу SBER (для простоты бэктеста)
        for strat in set([s[2] for s in sigs]):
            for direction in [1, -1]:
                strat_sigs = [(t, d) for t, d, s in sigs if s == strat and d == direction]
                for act, take in COMBOS:
                    trade_end_time = pd.Timestamp.min
                    for sig_time, _ in strat_sigs:
                        if sig_time <= trade_end_time: continue
                        next_h1 = h1_sber[h1_sber['begin'] > sig_time]
                        if next_h1.empty: continue
                        entry_time = next_h1.iloc[0]['begin']
                        res = simulate_trade(h1_sber, entry_time, direction, act, take)
                        if not res: continue
                        exit_price, bars_held, exit_reason, mae = res
                        entry_price = h1_sber[h1_sber['begin'] == entry_time].iloc[0]['open']
                        net_ret = (direction * (exit_price - entry_price) / entry_price) - FEE_ROUND
                        trade_end_time = entry_time + pd.Timedelta(hours=bars_held)
                        all_results.append({'strategy': strat, 'direction': 'LONG' if direction == 1 else 'SHORT', 'act': act, 'take': take, 'entry_time': entry_time, 'net_ret': net_ret, 'exit_reason': exit_reason, 'mae': mae, 'bars': bars_held})

    if not all_results:
        print("Нет сделок."); return

    df_res = pd.DataFrame(all_results)
    df_res['year'] = df_res['entry_time'].dt.year
    df_res['period'] = np.where(df_res['year'] <= 2025, 'Train', 'Test')
    
    def agg_stats(g):
        closed = g[g['exit_reason'] != 'OPEN']
        win = closed[closed['net_ret'] > 0]
        loss = closed[closed['net_ret'] <= 0]
        pf = win['net_ret'].sum() / abs(loss['net_ret'].sum()) if len(loss) > 0 and loss['net_ret'].sum() != 0 else np.nan
        return pd.Series({'trades': len(closed), 'win_rate': len(win) / len(closed) if len(closed) > 0 else 0, 'avg_ret': closed['net_ret'].mean(), 'profit_factor': pf})

    summary = df_res.groupby(['period', 'strategy', 'direction', 'act', 'take']).apply(agg_stats).reset_index()
    
    print("\n================ РЕЗУЛЬТАТЫ ADVANCED СТРАТЕГИЙ ================")
    print(summary.to_string(index=False))

if __name__ == "__main__":
    main()
