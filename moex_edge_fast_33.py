import time
import requests
import pandas as pd
import numpy as np
import warnings
from datetime import datetime, timedelta
warnings.filterwarnings('ignore')

# ================= НАСТРОЙКИ РИСК-МЕНЕДЖМЕНТА =================
DEPOSIT_RUB = 100000
RISK_PER_TRADE_PCT = 1.0
# ==============================================================

ISS_BASE = "https://iss.moex.com/iss"
BOARD = "TQBR"
PAUSE = 0.2

TICKERS = ["AFKS","AFLT","ALRS","BSPB","CBOM","CHMF","CNRU","DOMRF","ENPG","FLOT",
"GAZP","GMKN","HEAD","IRAO","LKOH","MAGN","MDMG","MOEX","MTSS","NLMK",
"NVTK","OZON","PHOR","PLZL","POSI","RAGR","RENI","ROSN","RTKM","RUAL",
"SBER","SBERP","SNGS","SNGSP","SVCB","T","TATN","TATNP","TRNFP","UGLD",
"VKCO","VTBR","X5","YDEX"]

REC_TAKE_PCT = 5.0
REC_BE_PCT = 2.0
REC_SL_PCT = 3.0

# ПРИОРИТЕТ СТРАТЕГИЙ (от самого сильного к слабому)
STRATEGY_PRIORITY = {
    'Keltner': 10,
    'ATR': 9,
    'Donchian55': 8,
    'Donchian20': 7,
    'Evening_Star': 6,
    'Three_Black': 6,
    'Dark_Cloud': 5,
    'MACD': 5,
    'Candlestick': 4,
    'ADX+DI': 4,
    'Bollinger': 3,
    'RSI14': 3,
    'Stochastic': 2,
    'EMA20/50': 1
}

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
    
    # КАНАЛ КЕЛЬТНЕРА
    df['kc_up'] = df['ema20'] + 2 * df['atr14']
    df['kc_dn'] = df['ema20'] - 2 * df['atr14']
    
    # Свечные паттерны
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
    
    # Кельтнер
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
    print(f"=== MOEX EDGE FAST 3.6 (Priority Engine) ===")
    print(f"Депозит: {DEPOSIT_RUB} RUB | Риск на сделку: {RISK_PER_TRADE_PCT}%")
    
    d1_from = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d')
    d1_till = datetime.now().strftime('%Y-%m-%d')
    h1_from = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
    h1_till = datetime.now().strftime('%Y-%m-%d')

    signals_found = []
    
    for ticker in TICKERS:
        try:
            d1 = fetch_candles(ticker, 24, d1_from, d1_till)
            if len(d1) < 200: continue
            d1 = calc_indicators(d1)
            d1_sigs = get_signals(d1)
            
            if not d1_sigs: continue
            
            h1 = fetch_candles(ticker, 60, h1_from, h1_till)
            if h1.empty: continue
            h1['ema20'] = h1['close'].ewm(span=20, adjust=False).mean()
            last_h1 = h1.iloc[-1]
            entry_price = last_h1['close']
            
            for t, direction, strat in d1_sigs:
                h1_confirmed = False
                if direction == 1 and entry_price > last_h1['ema20']: h1_confirmed = True
                elif direction == -1 and entry_price < last_h1['ema20']: h1_confirmed = True
                
                qty = 0
                if h1_confirmed:
                    risk_rub = DEPOSIT_RUB * (RISK_PER_TRADE_PCT / 100.0)
                    stop_distance = entry_price * (REC_SL_PCT / 100.0)
                    if stop_distance > 0:
                        pos_size_rub = risk_rub / (REC_SL_PCT / 100.0)
                        qty = int(pos_size_rub / entry_price)
                
                signals_found.append({
                    'ticker': ticker, 'direction': 'LONG' if direction == 1 else 'SHORT',
                    'strategy': strat, 'h1_confirmed': h1_confirmed, 'date': t, 'entry_price': entry_price, 'qty': qty
                })
        except Exception as e:
            print(f"Ошибка {ticker}: {e}")
            time.sleep(1)

    # ДЕДУПЛИКАЦИЯ И ПРИОРИТЕТ
    if signals_found:
        df_res = pd.DataFrame(signals_found)
        # Добавляем колонку с весом стратегии
        df_res['priority'] = df_res['strategy'].map(STRATEGY_PRIORITY).fillna(0)
        
        # Сортируем по весу (сначала сильные сигналы)
        df_res = df_res.sort_values('priority', ascending=False)
        
        # Оставляем только ОДИН лучший сигнал для каждого тикера и направления
        df_res = df_res.drop_duplicates(subset=['ticker', 'direction'], keep='first')
        
        # Удаляем служебную колонку и сохраняем
        df_res = df_res.drop(columns=['priority'])
        df_res.to_csv("moex_signals.csv", index=False)
    else:
        pd.DataFrame(columns=["ticker","direction","strategy","h1_confirmed","date","entry_price","qty"]).to_csv("moex_signals.csv", index=False)

    print("\n" + "="*50)
    if signals_found and not df_res.empty:
        ticker_dirs = {}
        for _, s in df_res.iterrows():
            if s['ticker'] not in ticker_dirs: ticker_dirs[s['ticker']] = set()
            ticker_dirs[s['ticker']].add(s['direction'])
        
        for _, s in df_res.iterrows():
            conflict = "⚠️ КОНФЛИКТ НАПРАВЛЕНИЙ!" if len(ticker_dirs[s['ticker']]) > 1 else ""
            status = "✅ H1 ПОДТВЕРЖДЕН" if s['h1_confirmed'] else "❌ H1 НЕ ПОДТВЕРЖДЕН (ЖДЕМ)"
            
            print(f"\n🔥 {s['direction']} {s['ticker']} ({s['strategy']}) {conflict}")
            print(f"   Сигнал D1: {s['date']}")
            print(f"   Статус: {status}")
            
            if s['h1_confirmed']:
                entry = s['entry_price']
                sl_price = entry * (1 - (REC_SL_PCT/100.0)) if s['direction'] == 'LONG' else entry * (1 + (REC_SL_PCT/100.0))
                tp_price = entry * (1 + (REC_TAKE_PCT/100.0)) if s['direction'] == 'LONG' else entry * (1 - (REC_TAKE_PCT/100.0))
                be_price = entry * (1 + (REC_BE_PCT/100.0)) if s['direction'] == 'LONG' else entry * (1 - (REC_BE_PCT/100.0))
                
                print(f"   👉 РЕКОМЕНДАЦИЯ: Вход по цене ~{entry:.2f}")
                print(f"      - Объем: {s['qty']} шт. (расчет под риск {DEPOSIT_RUB * (RISK_PER_TRADE_PCT/100.0):.0f} RUB)")
                print(f"      - Стоп-лосс: {sl_price:.2f} (-{REC_SL_PCT}%)")
                print(f"      - Тейк-профит: {tp_price:.2f} (+{REC_TAKE_PCT}%)")
                print(f"      - Перевод в безубыток при: {be_price:.2f} (+{REC_BE_PCT}%)")
    else:
        print("Сегодня сигналов нет. Рынок не дает точек входа по нашим правилам.")
    
    print("\n" + "="*50)

if __name__ == "__main__":
    main()
