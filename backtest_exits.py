"""
MOEX EDGE — backtest_exits.py
Шаг 1: загрузка H1-данных через MOEX ISS с контролем качества.
Не затрагивает moex_edge_fast_33.py и workflow.
"""
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

ISS_BASE = "https://iss.moex.com/iss"
BOARD = "TQBR"
INTERVAL_H1 = 60
PAGE_SIZE = 500          # безопасный размер страницы ISS
REQ_PAUSE = 0.25         # пауза между запросами, сек
CONTROL_TOL_DAYS = 10    # допуск при проверке контрольной точки

TICKERS = [
    "AFKS","AFLT","ALRS","BSPB","CBOM","CHMF","CNRU","DOMRF","ENPG","FLOT",
    "GAZP","GMKN","HEAD","IRAO","LKOH","MAGN","MDMG","MOEX","MTSS","NLMK",
    "NVTK","OZON","PHOR","PLZL","POSI","RAGR","RENI","ROSN","RTKM","RUAL",
    "SBER","SBERP","SNGS","SNGSP","SVCB","T","TATN","TATNP","TRNFP","UGLD",
    "VKCO","VTBR","X5","YDEX",
]

CANDLE_COLS = ["open","close","high","low","value","volume","begin","end"]


def _iss_get(url, params=None, retries=3):
    """GET с ретраями на 5xx/сетевые ошибки."""
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if 500 <= r.status_code < 600:
                time.sleep(1 + attempt)
                continue
            r.raise_for_status()
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(1 + attempt)
    raise RuntimeError(f"ISS request failed: {url}")


def get_candle_borders(ticker: str) -> dict:
    """Возвращает {interval: (begin, end)} для тикера."""
    url = f"{ISS_BASE}/engines/stock/markets/shares/boards/{BOARD}/securities/{ticker}/candleborders.json"
    payload = _iss_get(url)
    block = payload.get("borders", {})
    cols = block.get("columns", [])
    rows = block.get("data", [])
    result = {}
    for row in rows:
        rec = dict(zip(cols, row))
        result[rec["interval"]] = (rec["begin"], rec["end"])
    return result


def fetch_h1_candles(ticker: str, date_from: str, date_till: str) -> pd.DataFrame:
    """
    Пагинированная выгрузка H1-свечей.
    date_from / date_till — строки 'YYYY-MM-DD'.
    Возвращает DataFrame с колонками CANDLE_COLS.
    """
    url = f"{ISS_BASE}/engines/stock/markets/shares/boards/{BOARD}/securities/{ticker}/candles.json"
    all_rows = []
    start = 0
    while True:
        params = {
            "from": date_from,
            "till": date_till,
            "interval": INTERVAL_H1,
            "start": start,
            "iss.reverse": "false",
        }
        payload = _iss_get(url, params=params)
        block = payload.get("candles", {})
        cols = block.get("columns", CANDLE_COLS)
        rows = block.get("data", [])
        if not rows:
            break
        # Приводим к единому порядку колонок
        idx = {c: i for i, c in enumerate(cols)}
        for r in rows:
            all_rows.append([r[idx[c]] for c in CANDLE_COLS])
        if len(rows) < PAGE_SIZE:
            break
        start += len(rows)
        time.sleep(REQ_PAUSE)

    if not all_rows:
        return pd.DataFrame(columns=CANDLE_COLS)

    df = pd.DataFrame(all_rows, columns=CANDLE_COLS)
    df["begin"] = pd.to_datetime(df["begin"])
    df["end"] = pd.to_datetime(df["end"])
    df.insert(0, "ticker", ticker)
    _check_control_point(df, ticker, date_from, date_till)
    return df


def _check_control_point(df: pd.DataFrame, ticker: str, date_from: str, date_till: str):
    """
    Защита от 'тихой ошибки' ISS: проверяем, что данные действительно
    в запрошенном окне (с допуском на выходные/праздники).
    """
    lo = pd.to_datetime(date_from) - timedelta(days=CONTROL_TOL_DAYS)
    hi = pd.to_datetime(date_till) + timedelta(days=CONTROL_TOL_DAYS + 1)
    first = df["begin"].min()
    last = df["end"].max()
    if first < lo or last > hi:
        raise ValueError(
            f"[{ticker}] контрольная точка нарушена: "
            f"запрошено {date_from}..{date_till}, "
            f"получено {first}..{last}"
        )


def validate_h1(df: pd.DataFrame, ticker: str) -> list[str]:
    """Контроль качества. Возвращает список проблем (пусто = OK)."""
    issues = []
    if df.empty:
        return [f"{ticker}: пустой DataFrame"]

    # Дубликаты по begin
    dup = df["begin"].duplicated().sum()
    if dup:
        issues.append(f"{ticker}: дубликатов begin = {dup}")

    # Пропуски обязательных полей
    req = ["open","high","low","close","volume","begin","end"]
    miss = df[req].isna().sum().sum()
    if miss:
        issues.append(f"{ticker}: пропусков обязательных полей = {miss}")

    # OHLC-консистентность
    bad = df[
        (df["low"] > df["high"]) |
        (df["low"] > df["open"]) | (df["low"] > df["close"]) |
        (df["high"] < df["open"]) | (df["high"] < df["close"])
    ]
    if len(bad):
        issues.append(f"{ticker}: некорректных OHLC = {len(bad)}")

    # Свечи в выходные (по московскому времени)
    wk = df[df["begin"].dt.weekday >= 5]
    if len(wk):
        issues.append(f"{ticker}: свечей в выходные = {len(wk)}")

    # Монотонность времени
    if not df["begin"].is_monotonic_increasing:
        issues.append(f"{ticker}: begin не монотонен")

    # end - begin == 1 час
    diff = (df["end"] - df["begin"]).dt.total_seconds()
    bad_len = (diff != 3600).sum()
    if bad_len:
        issues.append(f"{ticker}: свечей с длиной != 1 час = {bad_len}")

    return issues


def load_all(tickers, date_from, date_till, out_csv="h1_moex_iss.csv"):
    all_parts, report = [], []
    for i, t in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {t}: borders...")
        borders = get_candle_borders(t)
        if INTERVAL_H1 not in borders:
            report.append({"ticker": t, "status": "no_h1_interval"})
            continue
        print(f"          H1 доступен: {borders[INTERVAL_H1]}")
        print(f"          выгрузка {date_from}..{date_till}...")
        try:
            df = fetch_h1_candles(t, date_from, date_till)
        except Exception as e:
            report.append({"ticker": t, "status": f"fetch_error: {e}"})
            continue
        issues = validate_h1(df, t)
        if issues:
            report.append({"ticker": t, "status": "qc_issues", "issues": issues})
        else:
            report.append({"ticker": t, "status": "ok", "rows": len(df)})
        all_parts.append(df)
        time.sleep(REQ_PAUSE)

    if all_parts:
        full = pd.concat(all_parts, ignore_index=True)
        full.to_csv(out_csv, index=False)
        print(f"\nСохранено {len(full)} строк в {out_csv}")

    rep = pd.DataFrame(report)
    print("\n=== Отчёт по тикерам ===")
    print(rep.to_string(index=False))
    return rep


if __name__ == "__main__":
    # Тестовый прогон на 3 тикерах за узкий период
    test_tickers = ["SBER", "GAZP", "LKOH"]
    load_all(test_tickers, "2026-01-03", "2026-02-01",
             out_csv="h1_test_moex_iss.csv")
