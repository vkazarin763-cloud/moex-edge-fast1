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

# 15 самых ликвидных акций для агента
TICKERS = ["SBER", "GAZP", "LKOH", "ROSN", "NVTK", "TATN", "MTSS", "MOEX", "VTBR", "YDEX", "GMKN", "PLZL", "CHMF", "ALRS", "T"]

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
    'Keltner': 8, 'ATR': 8, 'Donchian55': 7, 'Donchian20': 7,
    'VWAP': 7, 'OBV': 6, 'MACD': 6, 'Evening_Star': 6, 'Three_Black': 6,
    'ADX+DI': 5, 'Bollinger': 4, 'RSI14': 4, 'Stochastic': 3, 'EMA20/50': 3,
    'Morning_Star': 5, 'Bull_Harami': 4, 'Bear_Harami': 4, 'Hammer': 4, 'Shooting_Star': 4
}

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        pass

def fetch_candles(ticker, interval, dfrom, dtill):
    url = f"{ISS_BASE}/engines/stock/markets/shares/boards/{BOARD}/securities/{ticker}/candles.json"
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
    
    # Volume indicators
    df['vwap'] = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / df['volume'].cumsum()
    df['obv'] = (np.sign(df['close'].diff()) * df['volume']).cumsum()
    df['obv_ema'] = df['obv'].ewm(span=20, adjust=False).mean()
    
    # Candles
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
    
    return df

def get_signals(df):
    sigs = []
    df['cross_ema_up'] = (df['ema20'] > df['ema50']) & (df['ema20'].shift() <= df['ema50'].shift())
    df['cross_ema_dn'] = (df['ema20'] < df['ema50']) & (df['ema20'].shift() >= df['ema50'].shift())
    df['cross_macd_up'] = (df['macd'] > df['macd_sig']) & (df['macd'].shift() <= df['macd_sig'].shift())
    df['cross_macd_dn'] = (df['macd'] < df['macd_sig']) & (df['macd'].shift() >= df['macd_sig'].shift())
    df['vwap_up'] = (df['close'] > df['vwap']) & (df['close'].shift() <= df['vwap'].shift())
    df['vwap_dn'] = (df['close'] < df['vwap']) & (df['close'].shift() >= df['vwap'].shift())
    df['obv_up'] = (df['obv'] > df['obv_ema']) & (df['obv'].shift() <= df['obv_ema'].shift())
    df['obv_dn'] = (df['obv'] < df['obv_ema']) & (df['obv'].shift() >= df['obv_ema'].shift())
    
    df['is_bull'] = df['close'] > df['ema200']
    df['is_bear'] = df['close'] < df['ema200']
    
    i = len(df) - 1
    t = df.iloc[i]['begin']
    c = df.iloc[i]
    
    if c['is_bull']:
        if c['cross_ema_up']: sigs.append((t, 1, 'EMA20/50'))
        if c['cross_macd_up']: sigs.append((t, 1, 'MACD'))
        if c['don20_high'] and c['close'] > c['don20_high']: sigs.append((t, 1, 'Donchian20'))
        if c['don55_high'] and c['close'] > c['don55_high']: sigs.append((t, 1, 'Donchian55'))
        if c['close'] > c['kc_up'] and c['close'].shift() <= c['kc_up'].shift(): sigs.append((t, 1, 'Keltner'))
        if c['close'] > (c['don20_high'] + 0.25 * c['atr14']): sigs.append((t, 1, 'ATR'))
        if c['vwap_up']: sigs.append((t, 1, 'VWAP'))
        if c['obv_up']: sigs.append((t, 1, 'OBV'))
        if c['bull_engulf']: sigs.append((t, 1, 'Bull_Engulf'))
        if c['hammer']: sigs.append((t, 1, 'Hammer'))
        if c['morning_star']: sigs.append((t, 1, 'Morning_Star'))
        if c['bull_harami']: sigs.append((t, 1, 'Bull_Harami'))
        if c['rsi14'] > 30 and c['rsi14'].shift() <= 30: sigs.append((t, 1, 'RSI14'))
        if c['close'] > c['bb_dn'] and c['close'].shift() <= c['bb_dn'].shift(): sigs.append((t, 1, 'Bollinger'))
        
    if c['is_bear']:
        if c['cross_ema_dn']: sigs.append((t, -1, 'EMA20/50'))
        if c['cross_macd_dn']: sigs.append((t, -1, 'MACD'))
        if c['don20_low'] and c['close'] < c['don20_low']: sigs.append((t, -1, 'Donchian20'))
        if c['don55_low'] and c['close'] < c['don55_low']: sigs.append((t, -1, 'Donchian55'))
        if c['close'] < c['kc_dn'] and c['close'].shift() >= c['kc_dn'].shift(): sigs.append((t, -1, 'Keltner'))
        if c['close'] < (c['don20_low'] - 0.25 * c['atr14']): sigs.append((t, -1, 'ATR'))
        if c['vwap_dn']: sigs.append((t, -1, 'VWAP'))
        if c['obv_dn']: sigs.append((t, -1, 'OBV'))
        if c['bear_engulf']: sigs.append((t, -1, 'Bear_Engulf'))
        if c['shooting_star']: sigs.append((t, -1, 'Shooting_Star'))
        if c['evening_star']: sigs.append((t, -1, 'Evening_Star'))
        if c['bear_harami']: sigs.append((t, -1, 'Bear_Harami'))
        if c['three_black']: sigs.append((t, -1, 'Three_Black'))
        if c['rsi14'] < 70 and c['rsi14'].shift() >= 70: sigs.append((t, -1, 'RSI14'))
        if c['close'] < c['bb_up'] and c['close'].shift() >= c['bb_up'].shift(): sigs.append((t, -1, 'Bollinger'))
        
    return sigs

def load_data(file, default):
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f: return json.load(f)
    return default

def save_data(file, data):
    with open(file, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2, default=str)

def check_positions(portfolio):
    still_open = []
    for pos in portfolio["positions"]:
        dfrom = pos["entry_time"][:10]
        dtill = datetime.now().strftime('%Y-%m-%d')
        h1 = fetch_candles(pos["ticker"], 60, dfrom, dtill)
        if h1.empty:
            still_open.append(pos)
            continue
            
        h1 = h1[h1["begin"] >= pd.to_datetime(pos["entry_time"])]
        if h1.empty:
            still_open.append(pos)
            continue
            
        direction = 1 if pos["direction"] == "LONG" else -1
        sl, tp, be = pos["sl_price"], pos["tp_price"], pos["be_price"]
        activated = pos.get("activated", False)
        exit_price, reason = None, None
        
        for i in range(len(h1)):
            row = h1.iloc[i]
            op, hi, lo = row["open"], row["high"], row["low"]
            if direction == 1:
                if op >= tp or hi >= tp: exit_price, reason = tp, "TP"; break
                if not activated:
                    if op <= sl: exit_price, reason = op, "SL"; break
                    if lo <= sl: exit_price, reason = sl, "SL"; break
                    if hi >= be: activated = True
                else:
                    if op <= be: exit_price, reason = op, "BE"; break
                    if lo <= be: exit_price, reason = be, "BE"; break
            else:
                if op <= tp or lo <= tp: exit_price, reason = tp, "TP"; break
                if not activated:
                    if op >= sl: exit_price, reason = op, "SL"; break
                    if hi >= sl: exit_price, reason = sl, "SL"; break
                    if lo <= be: activated = True
                else:
                    if op >= be: exit_price, reason = op, "BE"; break
                    if hi >= be: exit_price, reason = be, "BE"; break
                    
        if exit_price:
            net_ret = direction * (exit_price - pos["entry_price"]) / pos["entry_price"] - COMMISSION
            pnl = pos["entry_price"] * pos["qty"] * net_ret
            portfolio["cash"] += pos["entry_price"] * pos["qty"] + pnl
            portfolio["closed_trades"].append({**pos, "exit_price": exit_price, "exit_reason": reason, "net_ret": net_ret, "pnl": pnl, "exit_time": str(h1.iloc[i]["begin"])})
            
            emoji = "✅" if pnl > 0 else "❌"
            send_telegram(f"{emoji} <b>АГЕНТ ЗАКРЫЛ СДЕЛКУ</b>\n{pos['ticker']} {pos['direction']}\nВход: {pos['entry_price']:.2f} -> Выход: {exit_price:.2f}\nПричина: {reason}\nРезультат: {net_ret*100:+.2f}% ({pnl:+.0f} ₽)")
        else:
            pos["activated"] = activated
            still_open.append(pos)
            
    portfolio["positions"] = still_open

def main():
    print("=== AI VIRTUAL AGENT ===")
    weights = load_data(WEIGHTS_FILE, DEFAULT_WEIGHTS)
    portfolio = load_data(PORTFOLIO_FILE, {"cash": INITIAL_DEPOSIT, "positions": [], "closed_trades": []})
    
    print(f"Кэш: {portfolio['cash']:.2f} ₽ | Открытых: {len(portfolio['positions'])}")
    
    # 1. Проверяем старые позиции
    check_positions(portfolio)
    
    # 2. Ищем новые сигналы
    open_tickers = {p["ticker"] for p in portfolio["positions"]}
    slots = MAX_POSITIONS - len(portfolio["positions"])
    
    for ticker in TICKERS:
        if slots <= 0 or ticker in open_tickers: continue
        
        d1 = fetch_candles(ticker, 24, (datetime.now() - timedelta(days=300)).strftime('%Y-%m-%d'), datetime.now().strftime('%Y-%m-%d'))
        if len(d1) < 200: continue
        d1 = calc_indicators(d1)
        sigs = get_signals(d1)
        
        if not sigs: continue
        
        # Выбираем лучший сигнал по весу
        best_sig = max(sigs, key=lambda x: weights.get(x[2], 0))
        t, direction, strat = best_sig
        
        weight = weights.get(strat, 0)
        if weight < 5: continue  # Пропускаем слабые стратегии
        
        # Проверка H1
        h1 = fetch_candles(ticker, 60, (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'), datetime.now().strftime('%Y-%m-%d'))
        if h1.empty: continue
        h1['ema20'] = h1['close'].ewm(span=20, adjust=False).mean()
        entry_price = h1.iloc[-1]['close']
        
        if direction == 1 and entry_price < h1.iloc[-1]['ema20']: continue
        if direction == -1 and entry_price > h1.iloc[-1]['ema20']: continue
        
        # Виртуальная покупка
        qty = 1 if (entry_price * 1) > portfolio["cash"] else int((portfolio["cash"] * 0.25) / entry_price)
        if qty == 0: qty = 1
        cost = entry_price * qty
        
        if cost > portfolio["cash"]: continue
        
        if direction == 1:
            sl, tp, be = entry_price * 0.97, entry_price * 1.05, entry_price * 1.02
        else:
            sl, tp, be = entry_price * 1.03, entry_price * 0.95, entry_price * 0.98
            
        portfolio["positions"].append({
            "ticker": ticker, "direction": "LONG" if direction == 1 else "SHORT",
            "entry_price": entry_price, "entry_time": str(t.iloc[-1] if hasattr(t, 'iloc') else t),
            "qty": qty, "activated": False, "strategy": strat,
            "sl_price": round(sl, 2), "tp_price": round(tp, 2), "be_price": round(be, 2)
        })
        portfolio["cash"] -= cost
        slots -= 1
        
        emoji = "🟢" if direction == 1 else "🔴"
        send_telegram(f"{emoji} <b>АГЕНТ ОТКРЫЛ СДЕЛКУ (Виртуально)</b>\n{ticker} {portfolio['positions'][-1]['direction']} ({strat})\nЦена: {entry_price:.2f}\nОбъем: {qty} шт. ({cost:.0f} ₽)\nСтоп: {sl:.2f}\nТейк: {tp:.2f}\nБУ: {be:.2f}")
        
    save_data(PORTFOLIO_FILE, portfolio)
    
    # Вывод статистики
    if portfolio["closed_trades"]:
        df = pd.DataFrame(portfolio["closed_trades"])
        win = df[df["pnl"] > 0]
        print(f"\n=== СТАТИСТИКА ===")
        print(f"Сделок: {len(df)} | Win Rate: {len(win)/len(df)*100:.1f}% | PnL: {df['pnl'].sum():+.0f} ₽")

if __name__ == "__main__":
    main()
