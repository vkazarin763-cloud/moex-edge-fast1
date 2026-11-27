#!/usr/bin/env python3
"""Simple read-only MOEX futures H1 breakout scanner.

LONG: last completed H1 close > highest high of the previous 20 H1 candles.
SHORT: last completed H1 close < lowest low of the previous 20 H1 candles.
This scanner only reads public MOEX ISS data. It never contacts Finam accounts
or places, modifies, or cancels orders.
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASE = "https://iss.moex.com/iss"
MARKET = "engines/futures/markets/forts"
ASSETS = [
    "MIX", "RTS", "MOEXCNY", "Si", "CNY", "Eu",
    "BR", "GOLD", "SILV", "PLT", "NG", "WTI",
    "SBRF", "GAZR", "LKOH", "ROSN", "VTBR", "T",
    "MGNT", "NVTK", "PLZL", "SNGR", "ALRS", "MTSS",
    "GMKN", "CHMF", "NLMK", "MOEX", "AFLT",
]
MOSCOW = ZoneInfo("Europe/Moscow")
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "moex-futures-simple-signals/1.0"


def iss_json(path, params=None):
    response = SESSION.get(f"{BASE}/{path}.json", params=params, timeout=25)
    response.raise_for_status()
    return response.json()


def table_rows(payload, name):
    table = payload.get(name, {})
    cols, rows = table.get("columns", []), table.get("data", [])
    return [dict(zip(cols, row)) for row in rows]


def active_contracts(now):
    payload = iss_json(f"{MARKET}/securities", {"iss.meta": "off"})
    result = []
    for row in table_rows(payload, "securities"):
        asset, secid = row.get("ASSETCODE"), row.get("SECID")
        last_trade = row.get("LASTTRADEDATE")
        if asset not in ASSETS or not secid or not last_trade:
            continue
        try:
            expiry = datetime.fromisoformat(str(last_trade)).date()
        except ValueError:
            continue
        if expiry < now.date():
            continue
        result.append({"asset": asset, "secid": secid, "last_trade_date": str(last_trade)})
    # Keep the nearest-expiring active contract per asset.
    result.sort(key=lambda x: (x["asset"], x["last_trade_date"]))
    chosen = {}
    for item in result:
        chosen.setdefault(item["asset"], item)
    return list(chosen.values())


def fetch_h1(secid, now):
    start_date = (now - timedelta(days=30)).date().isoformat()
    end_date = now.date().isoformat()
    path = f"{MARKET}/securities/{secid}/candles"
    all_rows, offset = [], 0
    while True:
        payload = iss_json(path, {
            "from": start_date, "till": end_date, "interval": 60,
            "start": offset, "iss.reverse": "false", "iss.meta": "off",
        })
        rows = table_rows(payload, "candles")
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < 500:
            break
        offset += len(rows)
        time.sleep(0.1)
    bars = {}
    for row in all_rows:
        try:
            stamp = datetime.fromisoformat(str(row["begin"]))
            stamp = stamp.replace(tzinfo=MOSCOW) if stamp.tzinfo is None else stamp.astimezone(MOSCOW)
            o, h, low, close = (float(row[k]) for k in ("open", "high", "low", "close"))
            if min(o, h, low, close) <= 0 or h < max(o, low, close) or low > min(o, h, close):
                continue
            # MOEX candle begin time; skip the still-forming hourly candle.
            if stamp + timedelta(hours=1) > now:
                continue
            bars[stamp] = {"time": stamp.isoformat(), "open": o, "high": h, "low": low, "close": close}
        except (KeyError, TypeError, ValueError):
            continue
    return [bars[k] for k in sorted(bars)]


def signal_for(bars):
    if len(bars) < 21:
        return None, {"valid_h1_bars": len(bars), "reason": "need_at_least_21_completed_h1_bars"}
    previous = bars[-21:-1]
    last = bars[-1]
    high20 = max(x["high"] for x in previous)
    low20 = min(x["low"] for x in previous)
    closes = [x["close"] for x in bars]
    def ema(period):
        alpha = 2 / (period + 1)
        value = closes[0]
        for close in closes[1:]:
            value = alpha * close + (1 - alpha) * value
        return value
    context = {
        "signal_candle_msk": last["time"],
        "last_h1_close": last["close"],
        "previous_20_h1_high": high20,
        "previous_20_h1_low": low20,
        "ema20": round(ema(20), 6),
        "ema50": round(ema(50), 6) if len(closes) >= 50 else None,
        "valid_h1_bars": len(bars),
    }
    context["ema_trend"] = (
        "UP" if context["ema50"] is not None and context["ema20"] > context["ema50"]
        else "DOWN" if context["ema50"] is not None and context["ema20"] < context["ema50"]
        else "FLAT" if context["ema50"] is not None else "NOT_ENOUGH_HISTORY"
    )
    if last["close"] > high20:
        return {"direction": "LONG", "strategy": "H1_DONCHIAN20_BREAKOUT", **context}, context
    if last["close"] < low20:
        return {"direction": "SHORT", "strategy": "H1_DONCHIAN20_BREAKOUT", **context}, context
    return None, context


def main():
    now = datetime.now(MOSCOW)
    report = {
        "as_of_msk": now.isoformat(),
        "mode": "simple_read_only_moex_futures_signals",
        "rule": "LONG above previous 20 completed H1 highs; SHORT below previous 20 completed H1 lows",
        "universe": ASSETS,
        "contracts_processed": 0,
        "contracts": {},
        "signals": [],
        "safety": {"read_only": True, "orders_placed": False, "finam_account_endpoints_called": False},
    }
    for contract in active_contracts(now):
        secid = contract["secid"]
        item = {**contract, "status": "ok"}
        try:
            bars = fetch_h1(secid, now)
            signal, context = signal_for(bars)
            item["market"] = context
            item["signal"] = signal
            if signal:
                report["signals"].append({"asset": contract["asset"], "secid": secid, **signal})
        except Exception as exc:
            item["status"] = "error"
            item["error"] = str(exc)[:240]
        report["contracts"][secid] = item
        report["contracts_processed"] += 1
    Path("moex-futures-signals.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({
        "contracts_processed": report["contracts_processed"],
        "signals": len(report["signals"]),
        "errors": sum(1 for x in report["contracts"].values() if x["status"] == "error"),
        "output": "moex-futures-signals.json",
    }, ensure_ascii=False))
    print(json.dumps(report["signals"], ensure_ascii=False))


if __name__ == "__main__":
    main()
