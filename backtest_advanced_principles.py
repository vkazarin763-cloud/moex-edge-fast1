import requests, pandas as pd, numpy as np, time
from datetime import datetime, timedelta
TICKERS = ["SBER", "GAZP", "LKOH", "ROSN", "NVTK", "TATN", "MTSS", "MOEX", "VTBR", "YDEX"]
COMMISSION = 0.0026
def fetch(t, interval, dfrom, dtill):
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{t}/candles.json"
    rows, start = [], 0
    while True:
        p = {"from": dfrom, "till": dtill, "interval": interval, "start": start}
        try: r = requests.get(url, params=p, timeout=30).json()
        except: break
        data = r.get("candles", {}).get("data", [])
        if not data: break
        for row in data: rows.append([row[0], row[1], row[2], row[3], row[4], row[6]])
        if len(data) < 500: break
        start += len(data); time.sleep(0.1)
    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["open","high","low","close","volume","begin"])
    for c in ["open","high","low","close","volume"]: df[c] = pd.to_numeric(df[c], errors='coerce')
    df["begin"] = pd.to_datetime(df["begin"])
    return df.dropna().sort_values("begin").reset_index(drop=True)
def calc(df):
    tr = pd.concat([df['high']-df['low'], (df['high']-df['close'].shift()).abs(), (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.rolling(14).mean()
    df['sma200'] = df['close'].rolling(200).mean()
    df['don55_high'] = df['high'].rolling(55).max().shift(1)
    df['don55_low'] = df['low'].rolling(55).min().shift(1)
    return df
def simulate(h1, sig_time, direction, mode):
    h1_fut = h1[h1['begin'] >= sig_time]
    if h1_fut.empty: return None
    entry = h1_fut.iloc[0]['open']
    sl = entry * (1 - direction * 0.03)
    highest, lowest = entry, entry
    p1, p2 = False, False
    rem_size = 1.0
    pnl = 0.0
    for i in range(len(h1_fut)):
        row = h1_fut.iloc[i]
        hi, lo, atr = row['high'], row['low'], row['atr14']
        if direction == 1: highest = max(highest, hi)
        else: lowest = min(lowest, lo)
        if (direction == 1 and lo <= sl) or (direction == -1 and hi >= sl):
            pnl += rem_size * (direction * (sl - entry)/entry - COMMISSION)
            return (pnl, 'SL')
        if mode == 'Fixed':
            tp = entry * (1 + direction * 0.05)
            if (direction == 1 and hi >= tp) or (direction == -1 and lo <= tp):
                pnl += rem_size * (direction * (tp - entry)/entry - COMMISSION)
                return (pnl, 'TP')
        elif mode.startswith('Partial'):
            level = float(mode.split('_')[1]) / 100.0
            if not p1:
                tp1 = entry * (1 + direction * level)
                if (direction == 1 and hi >= tp1) or (direction == -1 and lo <= tp1):
                    p1 = True
                    pnl += 0.5 * (direction * (tp1 - entry)/entry - COMMISSION)
                    rem_size = 0.5
                    sl = entry
            if p1:
                if direction == 1: sl = max(sl, highest - 2.0 * atr) if atr > 0 else sl
                else: sl = min(sl, lowest + 2.0 * atr) if atr > 0 else sl
        elif mode.startswith('Trail'):
            mult = float(mode.split('_')[1])
            if direction == 1: sl = max(sl, highest - mult * atr) if atr > 0 else sl
            else: sl = min(sl, lowest + mult * atr) if atr > 0 else sl
        elif mode == 'MultiPartial':
            if not p1:
                tp1 = entry * (1 + direction * 0.03)
                if (direction == 1 and hi >= tp1) or (direction == -1 and lo <= tp1):
                    p1 = True
                    pnl += 0.33 * (direction * (tp1 - entry)/entry - COMMISSION)
                    rem_size -= 0.33
                    sl = entry
            elif not p2:
                tp2 = entry * (1 + direction * 0.06)
                if (direction == 1 and hi >= tp2) or (direction == -1 and lo <= tp2):
                    p2 = True
                    pnl += 0.33 * (direction * (tp2 - entry)/entry - COMMISSION)
                    rem_size -= 0.33
            if p1:
                if direction == 1: sl = max(sl, highest - 2.0 * atr) if atr > 0 else sl
                else: sl = min(sl, lowest + 2.0 * atr) if atr > 0 else sl
    pnl += rem_size * (direction * (h1_fut.iloc[-1]['close'] - entry)/entry - COMMISSION)
    return (pnl, 'OPEN')
def main():
    print("Загрузка данных...")
    d1 = (datetime.now() - timedelta(days=365*2)).strftime('%Y-%m-%d')
    d2 = datetime.now().strftime('%Y-%m-%d')
    out_data = []
    modes = ['Fixed', 'Partial_1.5', 'Partial_3.0', 'Partial_5.0', 'Trail_1.5', 'Trail_2.0', 'Trail_3.0', 'MultiPartial']
    for t in TICKERS:
        print(f"Анализ {t}...")
        d1_df = fetch(t, 24, d1, d2)
        if d1_df.empty or len(d1_df) < 100: continue
        d1_df = calc(d1_df)
        signals = []
        for i in range(100, len(d1_df)-1):
            c = d1_df.iloc[i]
            sig_time = d1_df.iloc[i+1]['begin']
            if c['close'] > c['don55_high']: signals.append((sig_time, 1, 'Single'))
            if c['close'] < c['don55_low']: signals.append((sig_time, -1, 'Single'))
            if c['close'] > c['don55_high'] and c['close'] > c['sma200']: signals.append((sig_time, 1, 'TrendFilter'))
            if c['close'] < c['don55_low'] and c['close'] < c['sma200']: signals.append((sig_time, -1, 'TrendFilter'))
        if not signals: continue
        h1 = fetch(t, 60, d1, d2)
        if h1.empty: continue
        h1 = calc(h1)
        for sig_time, direction, entry_mode in signals:
            for exit_mode in modes:
                res = simulate(h1, sig_time, direction, exit_mode)
                if res:
                    pnl, reason = res
                    out_data.append({'ticker':t, 'direction':direction, 'entry':entry_mode, 'exit':exit_mode, 'pnl':pnl})
    df_res = pd.DataFrame(out_data)
    if df_res.empty: print("Нет данных"); return
    print("\n=== РЕЗУЛЬТАТЫ СРАВНЕНИЯ (2 года) ===")
    summary = df_res.groupby(['entry', 'exit']).agg(
        Trades=('pnl', 'count'),
        WinRate=('pnl', lambda x: (x > 0).mean() * 100),
        AvgRet=('pnl', lambda x: x.mean() * 100),
        TotalRet=('pnl', lambda x: x.sum() * 100)
    ).reset_index()
    summary = summary.sort_values('TotalRet', ascending=False)
    print(summary.to_string(index=False))
if __name__ == "__main__": main()
