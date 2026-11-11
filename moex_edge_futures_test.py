#!/usr/bin/env python3
# MOEX EDGE FUTURES — Finam API data availability and quality test
# Reads FINAM_API_SECRET from the environment. Never prints the secret.
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests
import pandas as pd

BASE = "https://api.finam.ru"
TIMEOUT = 30
SECRET = os.environ.get("FINAM_API_SECRET", "").strip()
if not SECRET:
    raise SystemExit("ERROR: FINAM_API_SECRET environment variable is not set.")

auth = requests.post(
    BASE + "/v1/sessions",
    json={"secret": SECRET},
    timeout=TIMEOUT,
)
print("Finam auth HTTP:", auth.status_code)
auth.raise_for_status()
token = auth.json().get("token")
if not token:
    raise SystemExit("ERROR: Finam did not return a session token.")
session = requests.Session()
session.headers.update({"Authorization": f"Bearer {token}"})

def get_all_active_assets():
    assets, cursor = [], "0"
    seen = set()
    for _ in range(100):
        params = {"cursor": cursor, "only_active": "true"}
        r = session.get(BASE + "/v1/assets/all", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        obj = r.json()
        batch = obj.get("assets", [])
        assets.extend(batch)
        next_cursor = str(obj.get("next_cursor") or "")
        if not next_cursor or next_cursor == cursor or next_cursor in seen:
            break
        seen.add(next_cursor)
        cursor = next_cursor
        if not batch:
            break
        time.sleep(0.05)
    return assets

def classify(a):
    s = " ".join(str(a.get(k) or "") for k in ("ticker", "name", "type", "symbol")).lower()
    # Restrict to futures-like records, then classify the five requested underlyings.
    typ = str(a.get("type") or "").lower()
    future_like = any(x in typ for x in ("future", "fut", "фьюч", "derivative", "сроч"))
    if not future_like and not any(x in s for x in (
        "фьючер", "imoex", "mem", "mix", "cny", "юан", "brent", "нефт",
        "gold", "золот", "доллар"
    )):
        return None
    groups = [
        ("Индекс Мосбиржи", ("индекс мос", "imoex", "mem", "mix")),
        ("Юань", ("юан", "cny")),
        ("Доллар", ("доллар", "usd", " si ")),
        ("Brent", ("brent", "нефт", " br ")),
        ("Золото", ("золот", "gold")),
    ]
    padded = " " + s + " "
    for label, keys in groups:
        if any(k in s for k in keys if len(k) > 2) or any(k in padded for k in keys if len(k) <= 2):
            return label
    return "Другие фьючерсы" if future_like else None

def bars(symbol, timeframe, days):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    url_symbol = quote(symbol, safe="@")
    r = session.get(
        f"{BASE}/v1/instruments/{url_symbol}/bars",
        params={
            "timeframe": timeframe,
            "interval.start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "interval.end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    raw = r.json().get("bars", [])
    rows = []
    for b in raw:
        def val(v):
            if isinstance(v, dict):
                v = v.get("value")
            try:
                return float(v)
            except (TypeError, ValueError):
                return float("nan")
        rows.append({
            "timestamp": pd.to_datetime(b.get("timestamp"), utc=True, errors="coerce"),
            "open": val(b.get("open")),
            "high": val(b.get("high")),
            "low": val(b.get("low")),
            "close": val(b.get("close")),
            "volume": val(b.get("volume")),
        })
    return pd.DataFrame(rows)

def quality(d):
    if d.empty:
        return {"bars": 0, "duplicates": 0, "bad_ohlc": 0, "last": ""}
    dup = int(d["timestamp"].duplicated(keep=False).sum())
    bad = (
        d[["timestamp", "open", "high", "low", "close"]].isna().any(axis=1)
        | (d["high"] < d["low"])
        | (d["high"] < d[["open", "close"]].max(axis=1))
        | (d["low"] > d[["open", "close"]].min(axis=1))
        | (d[["open", "high", "low", "close"]] <= 0).any(axis=1)
    )
    return {
        "bars": len(d),
        "duplicates": dup,
        "bad_ohlc": int(bad.sum()),
        "last": str(d["timestamp"].max()),
    }

print("Loading active Finam instrument catalogue...")
assets = get_all_active_assets()
print("Active assets received:", len(assets))

candidates = []
for a in assets:
    group = classify(a)
    if group and group != "Другие фьючерсы":
        symbol = a.get("symbol")
        if not symbol and a.get("ticker") and a.get("mic"):
            symbol = f'{a["ticker"]}@{a["mic"]}'
        if symbol:
            candidates.append({
                "category": group,
                "name": a.get("name", ""),
                "ticker": a.get("ticker", ""),
                "mic": a.get("mic", ""),
                "symbol": symbol,
                "type": a.get("type", ""),
            })

# Remove duplicate symbols; keep the first catalogue record.
unique = {}
for a in candidates:
    unique.setdefault(a["symbol"], a)
candidates = list(unique.values())

if not candidates:
    print("No target futures found by catalogue-name matching.")
    print("Asset types:", sorted({str(a.get("type")) for a in assets}))
    raise SystemExit(2)

print("Target futures candidates:", len(candidates))
for a in candidates:
    print(f'{a["category"]}: {a["name"]} | {a["symbol"]} | type={a["type"]}')

rows = []
for i, a in enumerate(candidates, 1):
    row = {
        "Категория": a["category"], "Название": a["name"],
        "Тикер": a["ticker"], "MIC": a["mic"],
        "Символ Finam": a["symbol"], "Тип": a["type"],
        "D1 свечей": 0, "D1 дубликаты": 0, "D1 плохие OHLC": 0, "Последняя D1": "",
        "H1 свечей": 0, "H1 дубликаты": 0, "H1 плохие OHLC": 0, "Последняя H1": "",
        "Статус": "OK", "Ошибка": "",
    }
    try:
        d1 = bars(a["symbol"], "TIME_FRAME_D", 365)
        q1 = quality(d1)
        row.update({
            "D1 свечей": q1["bars"], "D1 дубликаты": q1["duplicates"],
            "D1 плохие OHLC": q1["bad_ohlc"], "Последняя D1": q1["last"],
        })
        h1 = bars(a["symbol"], "TIME_FRAME_H1", 30)
        qh = quality(h1)
        row.update({
            "H1 свечей": qh["bars"], "H1 дубликаты": qh["duplicates"],
            "H1 плохие OHLC": qh["bad_ohlc"], "Последняя H1": qh["last"],
        })
        if q1["bars"] == 0 or qh["bars"] == 0:
            row["Статус"] = "НЕТ D1/H1 ДАННЫХ"
        elif any((q1["duplicates"], q1["bad_ohlc"], qh["duplicates"], qh["bad_ohlc"])):
            row["Статус"] = "ПРОВЕРИТЬ КАЧЕСТВО"
    except Exception as e:
        row["Статус"] = "ОШИБКА API"
        row["Ошибка"] = str(e)[:500]
    rows.append(row)
    print(f'[{i}/{len(candidates)}] {a["symbol"]}: {row["Статус"]}')
    time.sleep(0.08)

out = pd.DataFrame(rows)
out.to_csv("MOEX_EDGE_FUTURES_data_test.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(candidates).to_csv(
    "MOEX_EDGE_FUTURES_catalog.csv", index=False, encoding="utf-8-sig"
)
print("\n=== FUTURES DATA TEST ===")
print(out.to_string(index=False))
print("\nSaved: MOEX_EDGE_FUTURES_data_test.csv")
print("Saved: MOEX_EDGE_FUTURES_catalog.csv")
