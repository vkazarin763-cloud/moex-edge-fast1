# MOEX EDGE FAST 3.3 — Finam API scanner
# Run in Google Colab: %run -i /content/moex_edge_fast_33.py
# Secret is read from the current Colab session if available; otherwise requested securely.

import sys
import subprocess
import importlib.util
import warnings
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from getpass import getpass

warnings.filterwarnings("ignore")

if importlib.util.find_spec("requests") is None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "requests"])

import requests
import pandas as pd
import numpy as np
from IPython.display import display

TICKERS = [
    "AFKS", "AFLT", "ALRS", "BSPB", "CBOM", "CHMF", "CNRU", "DOMRF", "ENPG", "FLOT",
    "GAZP", "GMKN", "HEAD", "IRAO", "LKOH", "MAGN", "MDMG", "MOEX", "MTSS", "NLMK",
    "NVTK", "OZON", "PHOR", "PLZL", "POSI", "RAGR", "RENI", "ROSN", "RTKM", "RUAL",
    "SBER", "SBERP", "SNGS", "SNGSP", "SVCB", "T", "TATN", "TATNP", "TRNFP", "UGLD",
    "VKCO", "VTBR", "X5", "YDEX"
]
BASE = "https://api.finam.ru"
TIMEOUT = 25
NOW_UTC = datetime.now(timezone.utc)
START_D1 = (NOW_UTC - timedelta(days=350)).strftime("%Y-%m-%dT00:00:00Z")
START_H1 = (NOW_UTC - timedelta(days=25)).strftime("%Y-%m-%dT00:00:00Z")
END_TIME = NOW_UTC.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_secret():
    """Reuse a Secret already present in the live Colab kernel, otherwise ask securely."""
    for name in ("secret", "API_SECRET"):
        value = globals().get(name)
        if isinstance(value, str) and value.strip().startswith("tapi_sk_"):
            return value.strip()
    box = globals().get("token_box")
    if isinstance(box, dict):
        value = box.get("value")
        if isinstance(value, str) and value.strip().startswith("tapi_sk_"):
            return value.strip()
    return getpass("Finam API Secret (ввод скрыт): ").strip()


SECRET = get_secret()
if not SECRET:
    raise RuntimeError("Finam Secret не найден и не введён.")

auth = requests.post(
    BASE + "/v1/sessions",
    json={"secret": SECRET},
    timeout=TIMEOUT,
)
print("Авторизация HTTP:", auth.status_code)
auth.raise_for_status()
payload = auth.json()
JWT = payload.get("token")
if not JWT:
    raise RuntimeError("Finam не вернул token. Ответ: " + str(payload)[:500])
HEADERS = {"Authorization": "Bearer " + JWT}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def number(x):
    if isinstance(x, dict):
        x = x.get("value")
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def fetch_bars(ticker, timeframe, start_time):
    """Fetch bars without silently sorting or removing duplicates.

    Sorting and duplicate removal are performed after source-quality counters are
    collected, so the D1 quality report can show what came from the API.
    """
    url = f"{BASE}/v1/instruments/{ticker}@MISX/bars"
    params = {
        "timeframe": timeframe,
        "interval.start_time": start_time,
        "interval.end_time": END_TIME,
    }
    response = SESSION.get(url, params=params, timeout=TIMEOUT)
    if not response.ok:
        raise RuntimeError(
            f"Finam HTTP {response.status_code}: {response.text[:1000]} | URL: {response.url}"
        )
    obj = response.json()
    if not isinstance(obj, dict) or not isinstance(obj.get("bars", []), list):
        raise RuntimeError("Finam вернул неожиданный формат bars: " + str(obj)[:500])

    rows = []
    for bar in obj.get("bars", []):
        rows.append({
            "timestamp": pd.to_datetime(bar.get("timestamp"), utc=True, errors="coerce"),
            "open": number(bar.get("open")),
            "high": number(bar.get("high")),
            "low": number(bar.get("low")),
            "close": number(bar.get("close")),
            "volume": number(bar.get("volume")),
        })
    return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])


def prepare_bars(raw):
    """Return cleaned bars and source-quality counters.

    The returned frame is chronological and unique by timestamp. Counters are
    calculated before cleaning and are therefore suitable for the report.
    """
    if raw is None or raw.empty:
        return raw.copy() if isinstance(raw, pd.DataFrame) else pd.DataFrame(), {
            "Дубликаты timestamp": 0,
            "Порядок timestamp": "Н/Д",
            "Некорректные timestamp": 0,
        }

    d = raw.copy()
    invalid_timestamp = int(d["timestamp"].isna().sum())
    d = d.loc[d["timestamp"].notna()].copy()
    duplicate_count = int(d["timestamp"].duplicated(keep=False).sum())
    source_sorted = bool(d["timestamp"].is_monotonic_increasing)

    d = d.sort_values("timestamp", kind="stable")
    d = d.drop_duplicates(subset=["timestamp"], keep="last")
    d = d.reset_index(drop=True)
    return d, {
        "Дубликаты timestamp": duplicate_count,
        "Порядок timestamp": "ДА" if source_sorted else "НЕТ",
        "Некорректные timestamp": invalid_timestamp,
    }


def validate_ohlc(d):
    """Count missing and invalid OHLC rows, then return a valid OHLC frame."""
    if d.empty:
        return d.copy(), {"Пропуски OHLC": 0, "Некорректные OHLC": 0}
    missing_mask = d[["open", "high", "low", "close"]].isna().any(axis=1)
    invalid_mask = (
        (d["high"] < d["low"])
        | (d["high"] < d[["open", "close"]].max(axis=1))
        | (d["low"] > d[["open", "close"]].min(axis=1))
        | (d[["open", "high", "low", "close"]] <= 0).any(axis=1)
    )
    clean = d.loc[~missing_mask & ~invalid_mask].copy().reset_index(drop=True)
    return clean, {
        "Пропуски OHLC": int(missing_mask.sum()),
        "Некорректные OHLC": int(invalid_mask.sum()),
    }


def wilder(s, n):
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def indicators(df):
    d = df.copy()
    c, h, l = d.close, d.high, d.low
    d["EMA20"] = c.ewm(span=20, adjust=False).mean()
    d["EMA50"] = c.ewm(span=50, adjust=False).mean()
    d["EMA200"] = c.ewm(span=200, adjust=False).mean()
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = wilder(gain, 14) / wilder(loss, 14).replace(0, np.nan)
    d["RSI14"] = 100 - 100 / (1 + rs)
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    d["ATR14"] = wilder(tr, 14)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    d["MACD"] = ema12 - ema26
    d["MACD_SIGNAL"] = d["MACD"].ewm(span=9, adjust=False).mean()
    up, down = h.diff(), -l.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    d["PDI"] = 100 * wilder(plus_dm, 14) / d["ATR14"].replace(0, np.nan)
    d["MDI"] = 100 * wilder(minus_dm, 14) / d["ATR14"].replace(0, np.nan)
    dx = 100 * (d["PDI"] - d["MDI"]).abs() / (d["PDI"] + d["MDI"]).replace(0, np.nan)
    d["ADX"] = wilder(dx, 14)
    d["DC20H"] = h.shift(1).rolling(20).max()
    d["DC20L"] = l.shift(1).rolling(20).min()
    d["DC55H"] = h.shift(1).rolling(55).max()
    d["DC55L"] = l.shift(1).rolling(55).min()
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    d["BBU"], d["BBL"] = mid + 2 * sd, mid - 2 * sd
    low14, high14 = l.rolling(14).min(), h.rolling(14).max()
    d["STO_K"] = 100 * (c - low14) / (high14 - low14).replace(0, np.nan)
    d["STO_D"] = d["STO_K"].rolling(3).mean()
    d["RANGE10H"] = h.shift(1).rolling(10).max()
    d["RANGE10L"] = l.shift(1).rolling(10).min()
    return d


def latest_closed_d1(df):
    """Exclude the current Moscow calendar date from daily bars."""
    if df.empty:
        return df.copy()
    today_msk = datetime.now(ZoneInfo("Europe/Moscow")).date()
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    msk_dates = ts.dt.tz_convert("Europe/Moscow").dt.date
    return df.loc[msk_dates < today_msk].copy().reset_index(drop=True)


def latest_closed_h1(df, now_utc=None):
    """Keep H1 bars whose start timestamp plus one hour is not in the future.

    This uses the FAST 3.3 assumption that Finam's H1 timestamp is the start
    of the one-hour interval. The assumption should be checked against Finam
    documentation or observed timestamps before relying on it operationally.
    """
    if df.empty:
        return df.copy()
    cutoff = pd.Timestamp(now_utc or datetime.now(timezone.utc))
    cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    closed = (ts + pd.Timedelta(hours=1)) <= cutoff
    return df.loc[closed].copy().reset_index(drop=True)


def candle_signals(d):
    p = d.iloc[-2]
    x = d.iloc[-1]
    po, pc, ph, pl = p.open, p.close, p.high, p.low
    o, c, h, l = x.open, x.close, x.high, x.low
    body = abs(c - o)
    rng = max(h - l, 1e-12)
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    bullish_engulf = pc < po and c > o and o <= pc and c >= po
    bearish_engulf = pc > po and c < o and o >= pc and c <= po
    hammer = lower_wick >= 2 * max(body, 1e-12) and upper_wick <= max(body, 1e-12) and c >= l + 0.6 * rng
    shooting = upper_wick >= 2 * max(body, 1e-12) and lower_wick <= max(body, 1e-12) and c <= l + 0.4 * rng
    return bullish_engulf or hammer, bearish_engulf or shooting


def signals(d):
    if len(d) < 210:
        return []
    x, p = d.iloc[-1], d.iloc[-2]
    required = [
        "EMA20", "EMA50", "EMA200", "RSI14", "ATR14", "MACD", "MACD_SIGNAL",
        "ADX", "PDI", "MDI", "DC20H", "DC20L", "DC55H", "DC55L", "BBU", "BBL",
        "STO_K", "STO_D", "RANGE10H", "RANGE10L",
    ]
    if any(pd.isna(x[k]) for k in required):
        return []
    long_candle, short_candle = candle_signals(d)
    out = []

    def add(name, side, condition):
        if condition:
            out.append({"Стратегия": name, "Сигнал": side})

    # Crosses and reversals are evaluated on the latest completed daily bar.
    add("EMA20/50", "LONG", p.EMA20 <= p.EMA50 and x.EMA20 > x.EMA50)
    add("EMA20/50", "SHORT", p.EMA20 >= p.EMA50 and x.EMA20 < x.EMA50)
    add("MACD", "LONG", p.MACD <= p.MACD_SIGNAL and x.MACD > x.MACD_SIGNAL)
    add("MACD", "SHORT", p.MACD >= p.MACD_SIGNAL and x.MACD < x.MACD_SIGNAL)
    add("ADX+DI", "LONG", x.ADX > 20 and x.PDI > x.MDI and p.PDI <= p.MDI)
    add("ADX+DI", "SHORT", x.ADX > 20 and x.MDI > x.PDI and p.MDI <= p.PDI)
    add("Donchian20", "LONG", x.close > x.DC20H)
    add("Donchian20", "SHORT", x.close < x.DC20L)
    add("Donchian55", "LONG", x.close > x.DC55H)
    add("Donchian55", "SHORT", x.close < x.DC55L)
    add("RSI14 reversal", "LONG", p.RSI14 < 30 and x.RSI14 >= 30)
    add("RSI14 reversal", "SHORT", p.RSI14 > 70 and x.RSI14 <= 70)
    add("Bollinger reversal", "LONG", p.close < p.BBL and x.close >= x.BBL)
    add("Bollinger reversal", "SHORT", p.close > p.BBU and x.close <= x.BBU)
    add("Stochastic", "LONG", p.STO_K <= p.STO_D and x.STO_K > x.STO_D and x.STO_K < 30)
    add("Stochastic", "SHORT", p.STO_K >= p.STO_D and x.STO_K < x.STO_D and x.STO_K > 70)
    add("ATR breakout", "LONG", x.close > x.RANGE10H + 0.25 * x.ATR14)
    add("ATR breakout", "SHORT", x.close < x.RANGE10L - 0.25 * x.ATR14)
    add("Candlestick", "LONG", long_candle)
    add("Candlestick", "SHORT", short_candle)
    return out


QUALITY_COLUMNS = [
    "Тикер", "D1 свечей закрытых", "Последняя D1 в API", "Последняя закрытая D1",
    "Пропуски OHLC", "Некорректные OHLC", "Дубликаты timestamp", "Порядок timestamp",
    "Некорректные timestamp", "Качество",
]
ERROR_COLUMNS = ["Тикер", "Этап", "Ошибка"]

quality = []
errors = []
signal_rows = []
h1_cache = {}

print("Загружаю D1 по 44 инструментам...")
for i, ticker in enumerate(TICKERS, 1):
    try:
        raw = fetch_bars(ticker, "TIME_FRAME_D", START_D1)
        if raw.empty:
            quality.append({
                "Тикер": ticker,
                "D1 свечей закрытых": 0,
                "Последняя D1 в API": None,
                "Последняя закрытая D1": None,
                "Пропуски OHLC": 0,
                "Некорректные OHLC": 0,
                "Дубликаты timestamp": 0,
                "Порядок timestamp": "Н/Д",
                "Некорректные timestamp": 0,
                "Качество": "НЕТ ДАННЫХ",
            })
            continue

        prepared, source_quality = prepare_bars(raw)
        valid, ohlc_quality = validate_ohlc(prepared)
        raw_latest_d1 = str(prepared.timestamp.iloc[-1]) if not prepared.empty else None
        completed_raw = latest_closed_d1(valid)
        d = indicators(completed_raw)
        quality_ok = (
            len(d) >= 210
            and source_quality["Некорректные timestamp"] == 0
            and ohlc_quality["Пропуски OHLC"] == 0
            and ohlc_quality["Некорректные OHLC"] == 0
        )
        quality.append({
            "Тикер": ticker,
            "D1 свечей закрытых": len(d),
            "Последняя D1 в API": raw_latest_d1,
            "Последняя закрытая D1": str(d.timestamp.iloc[-1]) if not d.empty else None,
            **ohlc_quality,
            **source_quality,
            "Качество": "OK" if quality_ok else "ПРОВЕРИТЬ",
        })

        found = signals(d)
        for signal in found:
            x = d.iloc[-1]
            side = signal["Сигнал"]
            signal_rows.append({
                "Тикер": ticker,
                "Стратегия": signal["Стратегия"],
                "Сигнал": side,
                "Дата D1": str(x.timestamp),
                "Close D1": round(float(x.close), 6),
                "RSI14": round(float(x.RSI14), 2),
                "ATR14": round(float(x.ATR14), 6),
                "Стоп-ориентир 2ATR": round(
                    float(x.close - 2 * x.ATR14 if side == "LONG" else x.close + 2 * x.ATR14), 6
                ),
            })
    except Exception as exc:
        errors.append({"Тикер": ticker, "Этап": "D1", "Ошибка": str(exc)[:300]})
    print(f"D1: {i}/{len(TICKERS)}", end="\r")

signals_df = pd.DataFrame(signal_rows)
quality_df = pd.DataFrame(quality, columns=QUALITY_COLUMNS)
errors_df = pd.DataFrame(errors, columns=ERROR_COLUMNS)

# H1 is requested only for instruments that generated at least one D1 signal.
if not signals_df.empty:
    candidates = sorted(signals_df["Тикер"].unique())
    print("\nПроверяю H1 только по кандидатам:", len(candidates))
    for i, ticker in enumerate(candidates, 1):
        try:
            h_raw = fetch_bars(ticker, "TIME_FRAME_H1", START_H1)
            h_prepared, _ = prepare_bars(h_raw)
            h_valid, _ = validate_ohlc(h_prepared)
            h = latest_closed_h1(h_valid)
            if len(h) >= 25:
                h = h.copy()
                h["EMA20_H1"] = h.close.ewm(span=20, adjust=False).mean()
                z = h.iloc[-1]
                h1_cache[ticker] = {
                    "H1 свечей закрытых": len(h),
                    "H1 время": str(z.timestamp),
                    "H1 close": round(float(z.close), 6),
                    "EMA20 H1": round(float(z.EMA20_H1), 6),
                }
            else:
                h1_cache[ticker] = {
                    "H1 свечей закрытых": len(h),
                    "H1 время": None,
                    "H1 close": np.nan,
                    "EMA20 H1": np.nan,
                }
        except Exception as exc:
            h1_cache[ticker] = {
                "H1 свечей закрытых": 0,
                "H1 время": None,
                "H1 close": np.nan,
                "EMA20 H1": np.nan,
            }
            errors.append({"Тикер": ticker, "Этап": "H1", "Ошибка": str(exc)[:300]})
        print(f"H1: {i}/{len(candidates)}", end="\r")

    for column in ("H1 свечей закрытых", "H1 время", "H1 close", "EMA20 H1"):
        signals_df[column] = signals_df["Тикер"].map(
            {key: value.get(column) for key, value in h1_cache.items()}
        )
    signals_df["H1 направление"] = np.where(
        signals_df["H1 close"] > signals_df["EMA20 H1"],
        "LONG",
        np.where(signals_df["H1 close"] < signals_df["EMA20 H1"], "SHORT", "НЕЙТРАЛЬНО"),
    )
    h1_available = signals_df["H1 close"].notna() & signals_df["EMA20 H1"].notna()
    signals_df["H1 согласие"] = np.where(
        ~h1_available,
        "НЕТ ДАННЫХ",
        np.where(signals_df["Сигнал"] == signals_df["H1 направление"], "ДА", "НЕТ"),
    )
    signals_df["H1 подтверждение"] = np.where(
        ~h1_available,
        "НЕТ ДАННЫХ",
        np.where(signals_df["H1 согласие"] == "ДА", "ПОДТВЕРЖДЁН", "НЕ ПОДТВЕРЖДЁН"),
    )

# Add the side counts, conflict marker, and stable sorting to the signal report.
conflicts_df = pd.DataFrame(
    columns=[
        "Тикер", "LONG стратегий", "LONG стратегии",
        "SHORT стратегий", "SHORT стратегии",
    ]
)
if not signals_df.empty:
    counts = (
        signals_df.groupby(["Тикер", "Сигнал"])
        .size()
        .rename("Совпадений стратегий")
        .reset_index()
    )
    signals_df = signals_df.merge(counts, on=["Тикер", "Сигнал"], how="left")

    conflict_rows = []
    for ticker, group in signals_df.groupby("Тикер", sort=True):
        long_names = group.loc[group["Сигнал"] == "LONG", "Стратегия"].tolist()
        short_names = group.loc[group["Сигнал"] == "SHORT", "Стратегия"].tolist()
        if long_names and short_names:
            conflict_rows.append({
                "Тикер": ticker,
                "LONG стратегий": len(long_names),
                "LONG стратегии": "; ".join(long_names),
                "SHORT стратегий": len(short_names),
                "SHORT стратегии": "; ".join(short_names),
            })
    conflicts_df = pd.DataFrame(conflict_rows, columns=conflicts_df.columns)
    conflict_tickers = set(conflicts_df["Тикер"]) if not conflicts_df.empty else set()
    signals_df["Конфликт LONG/SHORT"] = np.where(
        signals_df["Тикер"].isin(conflict_tickers), "ДА", "НЕТ"
    )
    signals_df = signals_df.sort_values(
        ["Совпадений стратегий", "Тикер", "Сигнал"],
        ascending=[False, True, True],
    ).reset_index(drop=True)

# Errors can include H1 failures appended after the first DataFrame was created.
errors_df = pd.DataFrame(errors, columns=ERROR_COLUMNS)

print("\n\n=== MOEX EDGE FAST 3.3: СИГНАЛЫ D1 ===")
if signals_df.empty:
    print("Сигналов по правилам сканера нет.")
else:
    display(signals_df)

print("\n=== КОНФЛИКТЫ LONG/SHORT ===")
if conflicts_df.empty:
    print("Конфликтов LONG/SHORT нет.")
else:
    display(conflicts_df)

print("\n=== КАЧЕСТВО D1 ===")
display(quality_df)

print("\n=== ОШИБКИ ЗАГРУЗКИ ===")
display(errors_df if not errors_df.empty else pd.DataFrame([{"Статус": "Ошибок API нет"}]))

signals_df.to_csv("MOEX_EDGE_FAST_3_3_signals.csv", index=False, encoding="utf-8-sig")
conflicts_df.to_csv("MOEX_EDGE_FAST_3_3_conflicts.csv", index=False, encoding="utf-8-sig")
quality_df.to_csv("MOEX_EDGE_FAST_3_3_quality.csv", index=False, encoding="utf-8-sig")
errors_df.to_csv("MOEX_EDGE_FAST_3_3_errors.csv", index=False, encoding="utf-8-sig")

print("\nПримечание: сигналы рассчитаны только по последней закрытой D1-свече.")
print("H1: последняя свеча считается закрытой, если её timestamp + 1 час не превышает текущее UTC-время.")
print("Это основано на предположении о timestamp Finam как времени начала часового интервала.")
print("\nФайлы CSV сохранены в Colab: сигналы, конфликты, качество данных, ошибки.")
