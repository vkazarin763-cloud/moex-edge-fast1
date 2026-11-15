import os, json, time, math, requests, pandas as pd, numpy as np, warnings
from datetime import datetime, timedelta
from scipy.stats import norm
warnings.filterwarnings('ignore')

ISS_BASE = "https://iss.moex.com/iss"
PAUSE = 0.2
OPTIONS_MODE = True
SIGMA = 0.30
DAYS_TO_EXPIRY = 30
TICKERS = ["SBER", "GAZP", "LKOH", "ROSN", "NVTK", "TATN", "MTSS", "MOEX", "VTBR", "YDEX", "GMKN", "PLZL", "CHMF", "ALRS", "T"]
REF_TICKERS = {"IMOEX": ("SNDX", "index"), "BR": ("RTS", "share"), "Si": ("CETS", "share")}
INITIAL_DEPOSIT = 150000
COMMISSION = 0.0026
MAX_POSITIONS = 10
PORTFOLIO_FILE = "ai_portfolio.json"
WEIGHTS_FILE = "ai_weights.json"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DEFAULT_WEIGHTS = {'Keltner': 8, 'ATR': 8, 'Donchian55': 7, 'Donchian20': 7, 'VWAP': 7, 'OBV': 6, 'MACD': 6, 'Evening_Star': 6, 'Three_Black': 6, 'ADX+DI': 5, 'Bollinger': 4, 'RSI14': 4, 'Stochastic': 3, 'EMA20/50': 3, 'Morning_Star': 5, 'Bull_Harami': 4, 'Bear_Harami': 4, 'Hammer': 4, 'Shooting_Star': 4, 'Squeeze': 7, 'ZScore': 6, 'RelativeStrength': 7, 'InsideBar': 6, 'Pivot': 5, 'Intermarket': 7, 'GapAndGo': 6, 'VWAP_Reversion': 5, 'Seasonality': 4, 'Chandelier': 6, 'SMC_Sweep': 8, 'SMC_FVG': 8}

def bs(S, K, T, r, sig, opt):
    if T <= 0: return max(0, (S-K) if opt == 'call' else (K-S))
    d1 = (math.log(S/K) + (r + sig**2/2) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    return S * norm.cdf(d1) - K * math.exp(-r*T) * norm.cdf(d2) if opt == 'call' else K * math.exp(-r*T) * norm.cdf(-d2) - S * norm.cdf(-d1)

def load(f, d):
    if os.path.exists(f):
        try:
            with open(f, "r", encoding="utf-8") as file: return json.load(file)
        except: return d
    return d

def save(f, d):
    with open(f, "w", encoding="utf-8") as file: json.dump(d, file, ensure_ascii=False, indent=2, default=str)

def tg(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
        if resp.status_code != 200: print(f"❌ ОШИБКА TELEGRAM: {resp.text}")
    except Exception as e: print(f"❌ ОШИБКА СЕТИ: {e}")

def fetch(t, i, dfrom, dtill, b="TQBR"):
    url = f"{ISS_BASE}/engines/stock/markets/index/boards/SNDX/securities/{t}/candles.json" if b == "SNDX" else f"{ISS_BASE}/engines/currency/markets/selt/boards/CETS/securities/{t}/candles.json" if b == "CETS" else f"{ISS_BASE}/engines/stock/markets/shares/boards/{b}/securities/{t}/candles.json"
    rows, start = [], 0
    while True:
        p = {"from": dfrom, "till": dtill, "interval": i, "start": start, "iss.reverse": "false"}
        try: r = requests.get(url, params=p, timeout=30).json()
        except: break
        b = r.get("candles", {})
        data, cols = b.get("data", []), b.get("columns", [])
        if not data: break
        idx = {c: j for j, c in enumerate(cols)}
        for row in data: rows.append([row[idx.get(c, 0)] for c in ["open", "high", "low", "close", "volume", "begin"]])
        if len(data) < 500: break
        start += len(data)
        time.sleep(PAUSE)
    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume", "begin"])
    for c in ["open", "high", "low", "close", "volume"]: df[c] = pd.to_numeric(df[c], errors='coerce')
    df["begin"] = pd.to_datetime(df["begin"])
    return df.dropna().sort_values("begin").reset_index(drop=True)

def calc(df, ref=None):
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
    
    # ===== ADX / DI+ / DI- =====
    up = df['high'] - df['high'].shift()
    down = df['low'].shift() - df['low']
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    atr_s = pd.Series(tr).rolling(14).mean()
    df['di_plus'] = 100 * pd.Series(plus_dm).rolling(14).mean() / atr_s
    df['di_minus'] = 100 * pd.Series(minus_dm).rolling(14).mean() / atr_s
    dx = 100 * (df['di_plus'] - df['di_minus']).abs() / (df['di_plus'] + df['di_minus'])
    df['adx14'] = dx.rolling(14).mean()
    # ===========================
    
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
    df['z_score'] = (df['close'] - df['sma200']) / df['std200']
    df['inside_bar'] = (df['high'] < df['high'].shift(1)) & (df['low'] > df['low'].shift(1))
    df['gap'] = (df['open'] - df['close'].shift(1)) / df['close'].shift(1)
    df['pivot'] = (df['high'].shift(1) + df['low'].shift(1) + df['close'].shift(1)) / 3
    df['r1'] = 2 * df['pivot'] - df['low'].shift(1)
    df['s1'] = 2 * df['pivot'] - df['high'].shift(1)
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
    df['prev_low'] = df['low'].shift(1)
    df['prev_high'] = df['high'].shift(1)
    df['sweep_up'] = (df['low'] < df['prev_low']) & (df['close'] > df['prev_low'])
    df['sweep_dn'] = (df['high'] > df['prev_high']) & (df['close'] < df['prev_high'])
    df['fvg_up'] = (df['low'] > df['high'].shift(2))
    df['fvg_dn'] = (df['high'] < df['low'].shift(2))
    if ref:
        for rn, rdf in ref.items():
            if not rdf.empty and rn in ['IMOEX', 'BR', 'Si']:
                rdf = rdf[['begin', 'close']].rename(columns={'close': f'{rn}_close'})
                df = df.merge(rdf, on='begin', how='left').ffill()
                df[f'{rn}_ema20'] = df[f'{rn}_close'].ewm(span=20, adjust=False).mean()
    return df

def sigs(df):
    df['cross_ema_up'] = (df['ema20'] > df['ema50']) & (df['ema20'].shift() <= df['ema50'].shift())
    df['cross_ema_dn'] = (df['ema20'] < df['ema50']) & (df['ema20'].shift() >= df['ema50'].shift())
    df['cross_macd_up'] = (df['macd'] > df['macd_sig']) & (df['macd'].shift() <= df['macd_sig'].shift())
    df['cross_macd_dn'] = (df['macd'] < df['macd_sig']) & (df['macd'].shift() >= df['macd_sig'].shift())
    df['vwap_up'] = (df['close'] > df['vwap']) & (df['close'].shift() <= df['vwap'].shift())
    df['vwap_dn'] = (df['close'] < df['vwap']) & (df['close'].shift() >= df['vwap'].shift())
    df['obv_up'] = (df['obv'] > df['obv_ema']) & (df['obv'].shift() <= df['obv_ema'].shift())
    df['obv_dn'] = (df['obv'] < df['obv_ema']) & (df['obv'].shift() >= df['obv_ema'].shift())
    df['sq'] = (df['bb_up'] < df['kc_up']) & (df['bb_dn'] > df['kc_dn'])
    df['sqf'] = (df['sq'].shift() == True) & (df['sq'] == False)
    if 'IMOEX_close' in df.columns:
        df['rs'] = df['close'] / df['IMOEX_close']
        df['rs_ema'] = df['rs'].ewm(span=20, adjust=False).mean()
    df['is_bull'] = df['close'] > df['sma200']
    df['is_bear'] = df['close'] < df['sma200']
    i = len(df) - 1
    t = df.iloc[i]['begin']
    c = df.iloc[i]
    p = df.iloc[i-1] if i > 0 else c
    out = []
    if c['is_bull']:
        lc = [(c['cross_ema_up'], 'EMA20/50'), (c['cross_macd_up'], 'MACD'), (c['close'] > c['don20_high'], 'Donchian20'), (c['close'] > c['don55_high'], 'Donchian55'), (c['close'] > c['kc_up'] and p['close'] <= p['kc_up'], 'Keltner'), (c['close'] > (c['don20_high'] + 0.25 * c['atr14']), 'ATR'), (c['vwap_up'], 'VWAP'), (c['obv_up'], 'OBV'), (c['bull_engulf'], 'Bull_Engulf'), (c['hammer'], 'Hammer'), (c['morning_star'], 'Morning_Star'), (c['bull_harami'], 'Bull_Harami'), (c['rsi14'] > 30 and p['rsi14'] <= 30, 'RSI14'), (c['close'] > c['bb_dn'] and p['close'] <= p['bb_dn'], 'Bollinger'), (c['close'] < c['vwap'] * 0.98 and c['close'] > c['open'], 'VWAP_Reversion'), (c['sqf'] and c['close'] > c['open'], 'Squeeze'), (c['z_score'] < -2.0, 'ZScore'), ('rs' in c and c['rs'] > c['rs_ema'] and p['rs'] <= p['rs_ema'], 'RelativeStrength'), (c['inside_bar'] and c['close'] > p['high'], 'InsideBar'), (c['low'] <= c['s1'] and c['close'] > c['s1'], 'Pivot'), ('BR_close' in c and 'Si_close' in c and c['BR_close'] > c['BR_ema20'] and c['Si_close'] < c['Si_ema20'], 'Intermarket'), (c['gap'] > 0.01 and c['close'] > c['open'], 'GapAndGo'), (c['begin'].weekday() == 0 and c['close'] > c['open'], 'Seasonality'), (c['close'] > c['sma200'] and c['low'] <= c['ema20'] and c['close'] > c['ema20'], 'Chandelier'), (c['sweep_up'], 'SMC_Sweep'), (c['fvg_up'], 'SMC_FVG')]
        out.extend([(t, 1, n) for cond, n in lc if cond])
    if c['is_bear']:
        sc = [(c['cross_ema_dn'], 'EMA20/50'), (c['cross_macd_dn'], 'MACD'), (c['close'] < c['don20_low'], 'Donchian20'), (c['close'] < c['don55_low'], 'Donchian55'), (c['close'] < c['kc_dn'] and p['close'] >= p['kc_dn'], 'Keltner'), (c['close'] < (c['don20_low'] - 0.25 * c['atr14']), 'ATR'), (c['vwap_dn'], 'VWAP'), (c['obv_dn'], 'OBV'), (c['bear_engulf'], 'Bear_Engulf'), (c['shooting_star'], 'Shooting_Star'), (c['evening_star'], 'Evening_Star'), (c['bear_harami'], 'Bear_Harami'), (c['three_black'], 'Three_Black'), (c['rsi14'] < 70 and p['rsi14'] >= 70, 'RSI14'), (c['close'] < c['bb_up'] and p['close'] >= p['bb_up'], 'Bollinger'), (c['close'] > c['vwap'] * 1.02 and c['close'] < c['open'], 'VWAP_Reversion'), (c['sqf'] and c['close'] < c['open'], 'Squeeze'), (c['z_score'] > 2.0, 'ZScore'), ('rs' in c and c['rs'] < c['rs_ema'] and p['rs'] >= p['rs_ema'], 'RelativeStrength'), (c['inside_bar'] and c['close'] < p['low'], 'InsideBar'), (c['high'] >= c['r1'] and c['close'] < c['r1'], 'Pivot'), ('BR_close' in c and 'Si_close' in c and c['BR_close'] < c['BR_ema20'] and c['Si_close'] > c['Si_ema20'], 'Intermarket'), (c['gap'] < -0.01 and c['close'] < c['open'], 'GapAndGo'), (c['begin'].weekday() == 4 and c['close'] < c['open'], 'Seasonality'), (c['close'] < c['sma200'] and c['high'] >= c['ema20'] and c['close'] < c['ema20'], 'Chandelier'), (c['sweep_dn'], 'SMC_Sweep'), (c['fvg_dn'], 'SMC_FVG')]
        out.extend([(t, -1, n) for cond, n in sc if cond])
    return out

def get_kelly_pct(pf, strat):
    trades = [t for t in pf.get("closed_trades", []) if t.get("strategy") == strat]
    if len(trades) < 10: return 0.10
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    W = len(wins) / len(trades)
    avg_win = sum([t["pnl"] for t in wins]) / len(wins) if wins else 1
    avg_loss = abs(sum([t["pnl"] for t in losses]) / len(losses)) if losses else 1
    R = avg_win / avg_loss if avg_loss != 0 else 1.66
    K = W - ((1 - W) / R)
    return max(0.02, min(0.20, K * 0.5))

def check_p(pf):
    still = []
    for p in pf["positions"]:
        h1 = fetch(p["ticker"], 60, p["entry_time"][:10], datetime.now().strftime('%Y-%m-%d'))
        if h1.empty: still.append(p); continue
        h1 = h1[h1["begin"] >= pd.to_datetime(p["entry_time"])]
        if h1.empty: still.append(p); continue
        if p.get("is_option"):
            if h1.iloc[-1]['begin'] >= pd.to_datetime(p["expiry_time"]):
                S, K = h1.iloc[-1]['close'], p["strike"]
                intr = max(0, K - S) if p["direction"] == "PUT" else max(0, S - K)
                nr = (intr - p["premium"]) / p["premium"]
                pnl = p["premium"] * p["qty"] * nr
                pf["cash"] += p["premium"] * p["qty"] + pnl
                pf["closed_trades"].append({**p, "exit_price": intr, "exit_reason": "EXP", "net_ret": nr, "pnl": pnl, "exit_time": str(h1.iloc[-1]['begin'])})
                tg(f"⏰ <b>АГЕНТ ЗАКРЫЛ ОПЦИОН</b>\n{p['ticker']} {p['direction']}\nРезультат: {nr*100:+.2f}% ({pnl:+.0f} ₽)")
            else: still.append(p)
            continue
        d, sl, tp, be, act = (1 if p["direction"] == "LONG" else -1), p["sl_price"], p["tp_price"], p["be_price"], p.get("activated", False)
        ex_p, rs = None, None
        for i in range(len(h1)):
            op, hi, lo = h1.iloc[i]['open'], h1.iloc[i]['high'], h1.iloc[i]['low']
            if d == 1:
                if op >= tp or hi >= tp: ex_p, rs = tp, "TP"; break
                if not act:
                    if op <= sl: ex_p, rs = op, "SL"; break
                    if lo <= sl: ex_p, rs = sl, "SL"; break
                    if hi >= be: act = True
                else:
                    if op <= be: ex_p, rs = op, "BE"; break
                    if lo <= be: ex_p, rs = be, "BE"; break
            else:
                if op <= tp or lo <= tp: ex_p, rs = tp, "TP"; break
                if not act:
                    if op >= sl: ex_p, rs = op, "SL"; break
                    if hi >= sl: ex_p, rs = sl, "SL"; break
                    if lo <= be: act = True
                else:
                    if op >= be: ex_p, rs = op, "BE"; break
                    if hi >= be: ex_p, rs = be, "BE"; break
        if ex_p:
            nr = d * (ex_p - p["entry_price"]) / p["entry_price"] - COMMISSION
            pnl = p["entry_price"] * p["qty"] * nr
            pf["cash"] += p["entry_price"] * p["qty"] + pnl
            pf["closed_trades"].append({**p, "exit_price": ex_p, "exit_reason": rs, "net_ret": nr, "pnl": pnl, "exit_time": str(h1.iloc[i]["begin"])})
            tg(f"{'✅' if pnl>0 else '❌'} <b>АГЕНТ ЗАКРЫЛ СДЕЛКУ</b>\n{p['ticker']} {p['direction']}\nВход: {p['entry_price']:.2f} -> Выход: {ex_p:.2f}\nПричина: {rs}\nРезультат: {nr*100:+.2f}% ({pnl:+.0f} ₽)")
        else: p["activated"] = act; still.append(p)
    pf["positions"] = still

def main():
    print("=== AI VIRTUAL AGENT (Kelly + Regime) ===")
    w = load(WEIGHTS_FILE, DEFAULT_WEIGHTS)
    pf = load(PORTFOLIO_FILE, {"cash": INITIAL_DEPOSIT, "positions": [], "closed_trades": []})
    d1, d2 = (datetime.now() - timedelta(days=300)).strftime('%Y-%m-%d'), datetime.now().strftime('%Y-%m-%d')
    ref = {rn: fetch(rn, 24, d1, d2, b) for rn, (b, _) in REF_TICKERS.items()}
    
    imoex_adx = 0
    if not ref.get('IMOEX', pd.DataFrame()).empty:
        imoex_calc = calc(ref['IMOEX'])
        if len(imoex_calc) > 0:
            imoex_adx = imoex_calc['adx14'].iloc[-1]
            print(f"ADX IMOEX: {imoex_adx:.1f}")
    
    if imoex_adx > 25:
        print("📈 Режим: Тренд (усиливаем трендовые)")
        for s in ['Keltner', 'ATR', 'Donchian55', 'Donchian20', 'SMC_Sweep', 'Chandelier']:
            w[s] = w.get(s, 5) * 1.5
    elif imoex_adx < 20:
        print("📉 Режим: Флэт (усиливаем контртрендовые)")
        for s in ['RSI14', 'Bollinger', 'ZScore', 'VWAP_Reversion']:
            w[s] = w.get(s, 5) * 1.5
            
    check_p(pf)
    open_t = {p["ticker"] for p in pf["positions"]}
    slots = MAX_POSITIONS - len(pf["positions"])
    
    for t in TICKERS:
        if slots <= 0 or t in open_t: continue
        d = fetch(t, 24, d1, d2)
        if len(d) < 200: continue
        s = sigs(calc(d, ref))
        if not s: continue
        best = max(s, key=lambda x: w.get(x[2], 0))
        if w.get(best[2], 0) < 5: continue
        h1 = fetch(t, 60, (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'), datetime.now().strftime('%Y-%m-%d'))
        if h1.empty: continue
        h1['ema20'] = h1['close'].ewm(span=20, adjust=False).mean()
        ep = h1.iloc[-1]['close']
        if best[1] == 1 and ep < h1.iloc[-1]['ema20']: continue
        if best[1] == -1 and ep > h1.iloc[-1]['ema20']: continue
        
        kelly_pct = get_kelly_pct(pf, best[2])
        
        if OPTIONS_MODE and best[1] == -1:
            K = ep * 0.97; T = DAYS_TO_EXPIRY / 365.0
            prem = bs(ep, K, T, 0.15, SIGMA, 'put')
            if prem > pf["cash"]: continue
            pf["positions"].append({"ticker": t, "direction": "PUT", "entry_price": ep, "entry_time": str(best[0]), "qty": 1, "activated": False, "strategy": best[2], "strike": K, "premium": prem, "is_option": True, "expiry_time": (datetime.now() + timedelta(days=DAYS_TO_EXPIRY)).strftime('%Y-%m-%d')})
            pf["cash"] -= prem; slots -= 1; open_t.add(t)
            tg(f"🛡️ <b>АГЕНТ КУПИЛ PUT-ОПЦИОН</b>\n{t} (Страйк: {K:.2f})\nПремия: {prem:.2f} руб.\nСтратегия: {best[2]}")
        else:
            qty = max(1, int((pf["cash"] * kelly_pct) / ep))
            if ep * qty > pf["cash"]: continue
            sl, tp, be = (ep * 0.97, ep * 1.05, ep * 1.02) if best[1] == 1 else (ep * 1.03, ep * 0.95, ep * 0.98)
            pf["positions"].append({"ticker": t, "direction": "LONG" if best[1] == 1 else "SHORT", "entry_price": ep, "entry_time": str(best[0]), "qty": qty, "activated": False, "strategy": best[2], "sl_price": round(sl, 2), "tp_price": round(tp, 2), "be_price": round(be, 2)})
            pf["cash"] -= ep * qty; slots -= 1; open_t.add(t)
            tg(f"{'🟢' if best[1]==1 else '🔴'} <b>АГЕНТ ОТКРЫЛ СДЕЛКУ</b>\n{t} {pf['positions'][-1]['direction']} ({best[2]})\nЦена: {ep:.2f}\nОбъем: {qty} шт. (Келли: {kelly_pct*100:.1f}%)\nСтоп: {sl:.2f}\nТейк: {tp:.2f}")
            
    save(PORTFOLIO_FILE, pf)
    print(f"\nКэш: {pf['cash']:.2f} ₽ | Открытых: {len(pf['positions'])}")
    if pf["closed_trades"]:
        df 
