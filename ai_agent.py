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

# Акции для агента
TICKERS = ["SBER", "GAZP", "LKOH", "ROSN", "NVTK", "TATN", "MTSS", "MOEX", "VTBR", "YDEX", "GMKN", "PLZL", "CHMF", "ALRS", "T"]
# Индексы и товары для Intermarket
REF_TICKERS = {"IMOEX": ("SNDX", "index"), "BR": ("RTS", "share"), "Si": ("CETS", "share")}

INITIAL_DEPOSIT = 10000
COMMISSION = 0.0026
SL_PCT = 0.03
TP_PCT = 0.05
BE_PCT = 0.02
MAX_POSITIONS = 4
PORTFOLIO_FILE = "ai_portfolio.json"
WEIGHTS_FILE = "ai_weights.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DEFAULT_WEIGHTS = {
    'Keltner': 8, 'ATR': 8, 'Donchian55': 7, 'Donchian20': 7, 'VWAP': 7, 'OBV': 6,
    'MACD': 6, 'Evening_Star': 6, 'Three_Black': 6, 'ADX+DI': 5, 'Bollinger': 4,
    'RSI14': 4, 'Stochastic': 3, 'EMA20/50': 3, 'Morning_Star': 5, 'Bull_Harami': 4,
    'Bear_Harami': 4, 'Hammer': 4, 'Shooting_Star': 4,
    'Squeeze': 7, 'ZScore': 6, 'RelativeStrength': 7, 'InsideBar': 6, 'Pivot': 5,
    'Intermarket': 7, 'GapAndGo': 6, 'VWAP_Reversion': 5, 'Seasonality': 4, 'Chandelier': 6
}

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except: pass

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
    
    # Пивот-уровни
    df['pivot'] = (df['high'].shift(1) + df['low'].shift(1) + df['close'].shift(1)) / 3
    df['r1'] = 2 * df['pivot'] - df['low'].shift(1)
    df['s1'] = 2 * df['pivot'] - df['high'].shift(1)
    
    # Intermarket (сравнение с референсами)
    if ref_data:
        for ref_name, ref_df in ref_data.items():
            if not ref_df.empty and ref_name in ['IMOEX', 'BR', 'Si']:
                # Выравниваем по датам
                ref_df = ref_df[['begin', 'close']].rename(columns={'close': f'{ref_name}_close'})
                df = df.merge(ref_df, on='begin', how='left').ffill()
                df[f'{ref_name}_ema20'] = df[f'{ref_name}_close'].ewm(span=20, adjust=False).mean()
    
    return df

def get_signals(df, ref_data=None):
    sigs = []
    # ... (стандартные сигналы, как в предыдущем коде) ...
    # Чтобы код не был 1000 строк, я опускаю дублирование старых 19 сигналов. 
    # Они остаются внутри функции.
    
    # НОВЫЕ СИГНАЛЫ:
    # 1. Squeeze
    df['squeeze_on'] = (df['bb_up'] < df['kc_up']) & (df['bb_dn'] > df['kc_dn'])
    df['squeeze_fire'] = (df['squeeze_on'].shift() == True) & (df['squeeze_on'] == False)
    
    # 2. Relative Strength
    if 'IMOEX_close' in df.columns:
        df['rs'] = df['close'] / df['IMOEX_close']
        df['rs_ema'] = df['rs'].ewm(span=20, adjust=False).mean()
        
    i = len(df) - 1
    t = df.iloc[i]['begin']
    c = df.iloc[i]
    
    # ... (старые 19 стратегий) ...
    
    # Новые:
    if c['squeeze_fire']:
        if c['close'] > c['open']: sigs.append((t, 1, 'Squeeze'))
        else: sigs.append((t, -1, 'Squeeze'))
        
    if c['z_score'] < -2.0: sigs.append((t, 1, 'ZScore'))
    if c['z_score'] > 2.0: sigs.append((t, -1, 'ZScore'))
    
    if 'rs' in c and 'rs_ema' in c:
        if c['rs'] > c['rs_ema'] and c['rs'].shift() <= c['rs_ema'].shift(): sigs.append((t, 1, 'RelativeStrength'))
        if c['rs'] < c['rs_ema'] and c['rs'].shift() >= c['rs_ema'].shift(): sigs.append((t, -1, 'RelativeStrength'))
        
    if c['inside_bar'] and c['close'] > c['high'].shift(1): sigs.append((t, 1, 'InsideBar'))
    if c['inside_bar'] and c['close'] < c['low'].shift(1): sigs.append((t, -1, 'InsideBar'))
    
    if c['low'] <= c['s1'] and c['close'] > c['s1']: sigs.append((t, 1, 'Pivot'))
    if c['high'] >= c['r1'] and c['close'] < c['r1']: sigs.append((t, -1, 'Pivot'))
    
    if 'BR_close' in c and 'Si_close' in c:
        br_up = c['BR_close'] > c['BR_ema20']
        si_up = c['Si_close'] > c['Si_ema20']
        if br_up and si_up and c['close'] > c['ema20']: sigs.append((t, 1, 'Intermarket'))
        if not br_up and not si_up and c['close'] < c['ema20']: sigs.append((t, -1, 'Intermarket'))
        
    if c['gap'] > 0.01 and c['close'] > c['open']: sigs.append((t, 1, 'GapAndGo'))
    if c['gap'] < -0.01 and c['close'] < c['open']: sigs.append((t, -1, 'GapAndGo'))
    
    if c['close'] < c['vwap'] * 0.98 and c['close'] > c['open']: sigs.append((t, 1, 'VWAP_Reversion'))
    if c['close'] > c['vwap'] * 1.02 and c['close'] < c['open']: sigs.append((t, -1, 'VWAP_Reversion'))
    
    if c['begin'].weekday() == 0 and c['close'] > c['open']: sigs.append((t, 1, 'Seasonality'))
    if c['begin'].weekday() == 4 and c['close'] < c['open']: sigs.append((t, -1, 'Seasonality'))
    
    if c['close'] > c['sma200'] and c['low'] <= c['ema20'] and c['close'] > c['ema20']: sigs.append((t, 1, 'Chandelier'))
    if c['close'] < c['sma200'] and c['high'] >= c['ema20'] and c['close'] < c['ema20']: sigs.append((t, -1, 'Chandelier'))
    
    return sigs

# ... (дальше функции load_data, save_data, check_positions) ...

def main():
    print("=== AI VIRTUAL AGENT (30 Strategies) ===")
    weights = load_data(WEIGHTS_FILE, DEFAULT_WEIGHTS)
    portfolio = load_data(PORTFOLIO_FILE, {"cash": INITIAL_DEPOSIT, "positions": [], "closed_trades": []})
    
    # Загружаем референсы
    d1_from = (datetime.now() - timedelta(days=300)).strftime('%Y-%m-%d')
    d1_till = datetime.now().strftime('%Y-%m-%d')
    
    ref_data = {}
    for ref_name, (board, _) in REF_TICKERS.items():
        ref_data[ref_name] = fetch_candles(ref_name, 24, d1_from, d1_till, board)
        
    check_positions(portfolio)
    open_tickers = {p["ticker"] for p in portfolio["positions"]}
    slots = MAX_POSITIONS - len(portfolio["positions"])
    
    for ticker in TICKERS:
        if slots <= 0 or ticker in open_tickers: continue
        
        d1 = fetch_candles(ticker, 24, d1_from, d1_till)
        if len(d1) < 200: continue
        d1 = calc_indicators(d1, ref_data)
        sigs = get_signals(d1, ref_data)
        
        if not sigs: continue
        
        best_sig = max(sigs, key=lambda x: weights.get(x[2], 0))
        t, direction, strat = best_sig
        
        if weights.get(strat, 0) < 5: continue
        
        h1 = fetch_candles(ticker, 60, (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'), datetime.now().strftime('%Y-%m-%d'))
        if h1.empty: continue
        h1['ema20'] = h1['close'].ewm(span=20, adjust=False).mean()
        entry_price = h1.iloc[-1]['close']
        
        if direction == 1 and entry_price < h1.iloc[-1]['ema20']: continue
        if direction == -1 and entry_price > h1.iloc[-1]['ema20']: continue
        
        qty = 1 if (entry_price * 1) > portfolio["cash"] else int((portfolio["cash"] * 0.25) / entry_price)
        if qty == 0: continue
        cost = entry_price * qty
        if cost > portfolio["cash"]: continue
        
        if direction == 1:
            sl, tp, be = entry_price * 0.97, entry_price * 1.05, entry_price * 1.02
        else:
            sl, tp, be = entry_price * 1.03, entry_price * 0.95, entry_price * 0.98
            
        portfolio["positions"].append({
            "ticker": ticker, "direction": "LONG" if direction == 1 else "SHORT",
            "entry_price": entry_price, "entry_time": str(t),
            "qty": qty, "activated": False, "strategy": strat,
            "sl_price": round(sl, 2), "tp_price": round(tp, 2), "be_price": round(be, 2)
        })
        portfolio["cash"] -= cost
        slots -= 1
        
        emoji = "🟢" if direction == 1 else "🔴"
        send_telegram(f"{emoji} <b>АГЕНТ ОТКРЫЛ СДЕЛКУ</b>\n{ticker} {portfolio['positions'][-1]['direction']} ({strat})\nЦена: {entry_price:.2f}\nОбъем: {qty} шт.\nСтоп: {sl:.2f}\nТейк: {tp:.2f}")
        
    save_data(PORTFOLIO_FILE, portfolio)
    
    if portfolio["closed_trades"]:
        df = pd.DataFrame(portfolio["closed_trades"])
        win = df[df["pnl"] > 0]
        print(f"\n=== СТАТИСТИКА ===")
        print(f"Сделок: {len(df)} | Win Rate: {len(win)/len(df)*100:.1f}% | PnL: {df['pnl'].sum():+.0f} ₽")

if __name__ == "__main__":
    main()
