#!/usr/bin/env python3
"""Simple read-only MOEX options signal generator.

Signals are based on the underlying's last completed H1 candle:
  LONG CALL: close breaks the previous 20-bar high.
  LONG PUT:  close breaks the previous 20-bar low.
EMA20/EMA50 are reported for later filtering, but do not suppress signals.

No liquidity, spread, volatility, OI or AI filters suppress a signal. Those
fields are displayed as context only. This script never places orders.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

import requests

BASE = "https://api.finam.ru"
DEFAULT_UNDERLYINGS = ["SBER@MISX", "GAZP@MISX", "LKOH@MISX", "ROSN@MISX", "MOEX@MISX"]
TIMEOUT = 20


def value(x):
    return x.get("value") if isinstance(x, dict) and "value" in x else x


def number(x):
    try:
        n = Decimal(str(value(x)))
        return n if n.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def parse_time(x):
    if isinstance(x, dict):
        if "seconds" in x:
            return datetime.fromtimestamp(float(x["seconds"]), timezone.utc)
        try:
            parts = {k: int(x[k]) for k in ("year", "month", "day")}
            return datetime(**parts, hour=int(x.get("hour", 0)),
                            minute=int(x.get("minute", 0)),
                            second=int(x.get("second", 0)), tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(x, (int, float)):
        return datetime.fromtimestamp(float(x), timezone.utc)
    if isinstance(x, str):
        try:
            t = datetime.fromisoformat(x.replace("Z", "+00:00"))
            return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


class Finam:
    def __init__(self, secret):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "moex-options-simple-signals/1.0"
        response = self.session.post(BASE + "/v1/sessions", json={"secret": secret}, timeout=TIMEOUT)
        if response.status_code != 200:
            raise RuntimeError(f"auth_http_{response.status_code}")
        token = response.json().get("token")
        if not token:
            raise RuntimeError("auth_token_missing")
        self.session.headers["Authorization"] = "Bearer " + token

    def get(self, path, params=None):
        response = self.session.get(BASE + path, params=params, timeout=TIMEOUT)
        if response.status_code != 200:
            raise RuntimeError(f"api_http_{response.status_code}")
        return response.json()


def ema(values, period):
    alpha = 2.0 / (period + 1)
    result = []
    for item in values:
        result.append(float(item) if not result else alpha * float(item) + (1 - alpha) * result[-1])
    return result


def get_h1_bars(api, symbol, now):
    start = (now - timedelta(days=60)).isoformat(timespec="seconds").replace("+00:00", "Z")
    end = (now + timedelta(minutes=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload = api.get(f"/v1/instruments/{quote(symbol, safe='')}/bars", {
        "timeframe": "TIME_FRAME_H1",
        "interval.start_time": start,
        "interval.end_time": end,
    })
    raw = payload.get("bars", [])
    bars = []
    for item in raw if isinstance(raw, list) else []:
        stamp = parse_time(item.get("timestamp"))
        o, h, low, c = [number(item.get(k)) for k in ("open", "high", "low", "close")]
        if not stamp or None in (o, h, low, c):
            continue
        if min(o, h, low, c) <= 0 or h < max(o, c, low) or low > min(o, c, h):
            continue
        # Finam timestamps mark candle opening time. Ignore the still-forming H1 candle.
        if stamp + timedelta(hours=1) > now:
            continue
        bars.append({"time": stamp, "open": float(o), "high": float(h),
                     "low": float(low), "close": float(c)})
    bars.sort(key=lambda x: x["time"])
    # Deduplicate timestamps, keeping the last returned candle.
    unique = {b["time"]: b for b in bars}
    return [unique[k] for k in sorted(unique)]


def find_signal(bars):
    if len(bars) < 21:
        return None, {"valid_h1_bars": len(bars), "reason": "need_at_least_21_completed_h1_bars"}
    closes = [b["close"] for b in bars]
    e20 = ema(closes, 20)
    e50 = ema(closes, 50) if len(bars) >= 50 else None
    i = len(bars) - 1
    previous = bars[i-20:i]
    high20 = max(b["high"] for b in previous)
    low20 = min(b["low"] for b in previous)
    last = bars[i]
    common = {
        "signal_candle_utc": last["time"].isoformat(),
        "underlying_close": last["close"],
        "ema20": round(e20[i], 6),
        "ema50": round(e50[i], 6) if e50 else None,
        "previous_20_h1_high": high20,
        "previous_20_h1_low": low20,
        "valid_h1_bars": len(bars),
    }
    common["ema_trend"] = ("UP" if e20[i] > e50[i] else "DOWN" if e20[i] < e50[i] else "FLAT") if e50 else "NOT_ENOUGH_HISTORY"
    if last["close"] > high20:
        return {"direction": "LONG_CALL", "reason": "H1 close above previous 20-bar high", **common}, common
    if last["close"] < low20:
        return {"direction": "LONG_PUT", "reason": "H1 close below previous 20-bar low", **common}, common
    return None, common


def expiry_date(contract):
    for key in ("expiration_last_day", "expiration_first_day"):
        raw = value(contract.get(key))
        if isinstance(raw, dict):
            try:
                return f"{int(raw['year']):04d}-{int(raw['month']):02d}-{int(raw['day']):02d}"
            except (KeyError, TypeError, ValueError):
                pass
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw[:10]).date().isoformat()
            except ValueError:
                pass
    return None


def choose_option(api, underlying, direction, spot, today, now):
    payload = api.get(f"/v1/assets/{quote(underlying, safe='')}/options")
    options = payload.get("options", [])
    wanted = "TYPE_CALL" if direction == "LONG_CALL" else "TYPE_PUT"
    candidates = []
    for item in options if isinstance(options, list) else []:
        symbol = value(item.get("symbol"))
        strike = number(item.get("strike"))
        kind = str(value(item.get("type", ""))).upper()
        expiry = expiry_date(item)
        if not symbol or strike is None or kind != wanted or not expiry:
            continue
        try:
            dte = (datetime.fromisoformat(expiry).date() - today).days
        except ValueError:
            continue
        if 1 <= dte <= 120:
            candidates.append((dte, abs(float(strike) - float(spot)), item, expiry, strike))
    if not candidates:
        return {"status": "no_matching_contract_in_chain"}
    # Prefer the nearest expiry, then the closest strike. No liquidity filters.
    _, _, contract, expiry, strike = min(candidates, key=lambda x: (x[0], x[1]))
    symbol = str(value(contract["symbol"]))
    result = {
        "symbol": symbol,
        "type": wanted,
        "strike": float(strike),
        "expiry": expiry,
        "dte": (datetime.fromisoformat(expiry).date() - today).days,
        "status": "selected_nearest_expiry_near_atm",
    }
    try:
        q = api.get(f"/v1/instruments/{quote(symbol, safe='')}/quotes/latest").get("quote", {})
        bid, ask = number(q.get("bid")), number(q.get("ask"))
        stamp = parse_time(q.get("timestamp"))
        age = round((now - stamp).total_seconds() / 60, 1) if stamp else None
        spread = None
        if bid is not None and ask is not None and bid > 0 and ask >= bid:
            mid = (bid + ask) / 2
            spread = round(float((ask - bid) / mid * 100), 2) if mid else None
        result["quote"] = {
            "bid": float(bid) if bid is not None else None,
            "ask": float(ask) if ask is not None else None,
            "last": float(number(q.get("last"))) if number(q.get("last")) is not None else None,
            "timestamp_utc": stamp.isoformat() if stamp else None,
            "age_minutes": age,
            "spread_pct": spread,
        }
        result["quote_warning"] = "quote may be stale or wide; shown for information only"
    except Exception as exc:
        result["quote_error"] = str(exc)
    return result


def main():
    secret = os.environ.get("FINAM_API_SECRET")
    if not secret:
        raise RuntimeError("FINAM_API_SECRET_missing")
    symbols = [s.strip() for s in os.environ.get("OPTION_UNDERLYINGS", ",".join(DEFAULT_UNDERLYINGS)).split(",") if s.strip()]
    now = datetime.now(timezone.utc)
    today = now.date()
    api = Finam(secret)
    report = {
        "as_of_utc": now.isoformat(),
        "mode": "simple_read_only_options_signals",
        "rules": {
            "long_call": "last completed H1 close > highest high of previous 20 completed H1 candles",
            "long_put": "last completed H1 close < lowest low of previous 20 completed H1 candles",
            "filters": "none; EMA trend, option spread, quote age, volatility, OI and liquidity do not suppress signals",
        },
        "underlyings": {},
        "signals": [],
        "safety": {"read_only": True, "orders_placed": False, "account_endpoints_called": False},
    }
    for underlying in symbols:
        item = {"status": "ok"}
        try:
            bars = get_h1_bars(api, underlying, now)
            signal, context = find_signal(bars)
            item["market"] = context
            item["signal"] = signal
            if signal:
                spot = number(signal["underlying_close"])
                try:
                    item["option"] = choose_option(api, underlying, signal["direction"], spot, today, now)
                except Exception as exc:
                    item["option"] = {"status": "lookup_failed", "error": str(exc)}
                report["signals"].append({"underlying": underlying, **signal, "option": item["option"]})
            else:
                item["status"] = context.get("reason", "no_signal")
        except Exception as exc:
            item.update({"status": "error", "error": str(exc)})
        report["underlyings"][underlying] = item
    out = Path(os.environ.get("OUTPUT_JSON", "moex-options-signals.json"))
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"underlyings": len(symbols), "signals": len(report["signals"]), "output": str(out)}))
    print(json.dumps(report["signals"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("OPTIONS SIGNAL SCAN FAILED: " + str(exc), file=sys.stderr)
        sys.exit(1)
