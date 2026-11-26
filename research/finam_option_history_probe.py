"""Read-only probe: test whether Finam exposes historical bars for MOEX options.

Uses only session authentication and GET market-data endpoints. It never calls account,
orders, cancellation, SL/TP, or portfolio endpoints. Secret values and raw API errors
are never written to logs or artifacts.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

import requests

BASE = "https://api.finam.ru"
UNDERLYINGS = ["SBER@MISX", "GAZP@MISX", "ROSN@MISX", "MOEX@MISX"]
TIMEOUT = 20
TARGET_EXPIRIES = ["2026-12-16", "2027-01-20"]


class ProbeError(RuntimeError):
    pass


def value_of(item):
    if isinstance(item, dict):
        return item.get("value")
    return item


def decimal_value(item):
    try:
        value = Decimal(str(value_of(item)))
        return value if value.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def iso_date(item):
    if not isinstance(item, dict):
        return None
    try:
        return f"{int(item['year']):04d}-{int(item['month']):02d}-{int(item['day']):02d}"
    except (KeyError, TypeError, ValueError):
        return None


class FinamReadOnly:
    def __init__(self, secret: str):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "moex-options-history-probe/1.0"})
        response = self.session.post(
            f"{BASE}/v1/sessions",
            json={"secret": secret},
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            raise ProbeError(f"authentication_http_{response.status_code}")
        try:
            token = response.json().get("token")
        except ValueError:
            token = None
        if not isinstance(token, str) or not token:
            raise ProbeError("authentication_token_missing")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def get(self, path: str, params: dict | None = None):
        try:
            response = self.session.get(f"{BASE}{path}", params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise ProbeError(f"network_{type(exc).__name__}") from None
        if response.status_code != 200:
            return response.status_code, None
        try:
            data = response.json()
        except ValueError:
            return response.status_code, None
        return response.status_code, data if isinstance(data, dict) else None


def quote_summary(api: FinamReadOnly, symbol: str) -> dict:
    status, data = api.get(f"/v1/instruments/{quote(symbol, safe='')}/quotes/latest")
    if status != 200 or not data:
        return {"http_status": status, "available": False}
    q = data.get("quote") if isinstance(data.get("quote"), dict) else {}
    return {
        "http_status": status,
        "available": True,
        "timestamp": q.get("timestamp"),
        "bid": value_of(q.get("bid")),
        "ask": value_of(q.get("ask")),
        "last": value_of(q.get("last")),
        "bid_size": value_of(q.get("bid_size")),
        "ask_size": value_of(q.get("ask_size")),
        "open_interest": value_of(q.get("open_interest")),
        "implied_volatility": value_of((q.get("option") or {}).get("implied_volatility"))
        if isinstance(q.get("option"), dict) else None,
    }


def timestamp_value(item):
    if not isinstance(item, dict):
        return None
    try:
        seconds = int(item.get("seconds"))
        nanos = int(item.get("nanos", 0))
        return datetime.fromtimestamp(seconds + nanos / 1_000_000_000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def orderbook_summary(api: FinamReadOnly, symbol: str) -> dict:
    status, data = api.get(f"/v1/instruments/{quote(symbol, safe='')}/orderbook")
    if status != 200 or not data:
        return {"http_status": status, "available": False}
    book = data.get("orderbook") if isinstance(data.get("orderbook"), dict) else {}
    rows = book.get("rows") if isinstance(book.get("rows"), list) else []
    levels = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        price = decimal_value(row.get("price"))
        buy_size = decimal_value(row.get("buy_size")) or Decimal("0")
        sell_size = decimal_value(row.get("sell_size")) or Decimal("0")
        stamp = timestamp_value(row.get("timestamp"))
        if price is None or price <= 0:
            continue
        levels.append((price, buy_size, sell_size, stamp))
    bids = [row for row in levels if row[1] > 0]
    asks = [row for row in levels if row[2] > 0]
    best_bid = max((row[0] for row in bids), default=None)
    best_ask = min((row[0] for row in asks), default=None)
    best_bid_size = sum((row[1] for row in bids if row[0] == best_bid), Decimal("0")) if best_bid is not None else Decimal("0")
    best_ask_size = sum((row[2] for row in asks if row[0] == best_ask), Decimal("0")) if best_ask is not None else Decimal("0")
    stamps = [row[3] for row in levels if row[3] is not None]
    spread_pct = None
    if best_bid is not None and best_ask is not None and (best_bid + best_ask) > 0:
        spread_pct = float((best_ask - best_bid) / ((best_bid + best_ask) / 2) * 100)
    return {
        "http_status": status,
        "available": True,
        "rows_received": len(rows),
        "valid_levels": len(levels),
        "bid_levels": len(bids),
        "ask_levels": len(asks),
        "best_bid": str(best_bid) if best_bid is not None else None,
        "best_bid_size": str(best_bid_size),
        "best_ask": str(best_ask) if best_ask is not None else None,
        "best_ask_size": str(best_ask_size),
        "spread_pct": round(spread_pct, 4) if spread_pct is not None else None,
        "latest_level_timestamp": max(stamps).isoformat() if stamps else None,
    }


def latest_trades_summary(api: FinamReadOnly, symbol: str, now: datetime) -> dict:
    status, data = api.get(f"/v1/instruments/{quote(symbol, safe='')}/trades/latest")
    if status != 200 or not data:
        return {"http_status": status, "available": False}
    trades = data.get("trades") if isinstance(data.get("trades"), list) else []
    parsed = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        stamp = timestamp_value(trade.get("timestamp"))
        price = decimal_value(trade.get("price"))
        size = decimal_value(trade.get("size"))
        if stamp is None:
            continue
        parsed.append((stamp, trade, price, size))
    parsed.sort(key=lambda item: item[0])
    latest = parsed[-1] if parsed else None
    return {
        "http_status": status,
        "available": True,
        "trades_received": len(trades),
        "valid_timestamped_trades": len(parsed),
        "oldest_trade_timestamp": parsed[0][0].isoformat() if parsed else None,
        "latest_trade_timestamp": latest[0].isoformat() if latest else None,
        "latest_trade_age_minutes": round((now - latest[0]).total_seconds() / 60, 2) if latest else None,
        "latest_trade_price": str(latest[2]) if latest and latest[2] is not None else None,
        "latest_trade_size": str(latest[3]) if latest and latest[3] is not None else None,
        "latest_trade_side": latest[1].get("side") if latest else None,
        "latest_trade_open_interest": value_of(latest[1].get("open_interest")) if latest else None,
        "snapshot_trade_count": sum(bool(item[1].get("is_data_snapshot")) for item in parsed),
    }


def bar_summary(api: FinamReadOnly, symbol: str, timeframe: str, start: str, end: str) -> dict:
    status, data = api.get(
        f"/v1/instruments/{quote(symbol, safe='')}/bars",
        params={
            "timeframe": timeframe,
            "interval.start_time": start,
            "interval.end_time": end,
        },
    )
    if status != 200 or not data:
        return {"http_status": status, "bars_count": 0, "available": False}
    bars = data.get("bars")
    if not isinstance(bars, list):
        return {"http_status": status, "bars_count": 0, "available": False, "schema_ok": False}
    valid = []
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        opening, high, low, close = (decimal_value(bar.get(k)) for k in ("open", "high", "low", "close"))
        volume = decimal_value(bar.get("volume"))
        if None in (opening, high, low, close, volume):
            continue
        if min(opening, high, low, close) <= 0 or volume < 0:
            continue
        valid.append((bar, opening, high, low, close, volume))
    timestamps = [str(item[0].get("timestamp")) for item in valid if item[0].get("timestamp")]
    series = [
        {
            "timestamp": str(bar.get("timestamp")),
            "open": str(opening),
            "high": str(high),
            "low": str(low),
            "close": str(close),
            "volume": str(volume),
            "is_data_snapshot": bool(bar.get("is_data_snapshot")),
        }
        for bar, opening, high, low, close, volume in valid
    ]
    return {
        "http_status": status,
        "available": True,
        "bars_count": len(bars),
        "valid_ohlc_bars": len(valid),
        "positive_volume_bars": sum(item[5] > 0 for item in valid),
        "first_timestamp": min(timestamps) if timestamps else None,
        "last_timestamp": max(timestamps) if timestamps else None,
        "first_close": str(valid[0][4]) if valid else None,
        "last_close": str(valid[-1][4]) if valid else None,
        "max_volume": str(max((item[5] for item in valid), default=Decimal("0"))),
        "snapshot_bars": sum(bool(item[0].get("is_data_snapshot")) for item in valid),
        "series": series,
    }


def select_contracts(options: list, spot: Decimal | None, as_of: str) -> tuple[list[dict], dict, str | None]:
    clean = []
    expiry_counts: dict[str, int] = {}
    for option in options:
        if not isinstance(option, dict) or not isinstance(option.get("symbol"), str):
            continue
        strike = decimal_value(option.get("strike"))
        if strike is None:
            continue
        expiry = iso_date(option.get("expiration_last_day")) or iso_date(option.get("expiration_first_day"))
        expiry_counts[expiry or "UNKNOWN"] = expiry_counts.get(expiry or "UNKNOWN", 0) + 1
        clean.append({
            "symbol": option["symbol"],
            "type": str(option.get("type", "UNKNOWN")),
            "strike": str(strike),
            "expiry_start": iso_date(option.get("expiration_first_day")),
            "expiry_end": expiry,
            "trade_first_day": iso_date(option.get("trade_first_day")),
            "trade_last_day": iso_date(option.get("trade_last_day")),
            "contract_size": value_of(option.get("contract_size")),
            "multiplier": value_of(option.get("multiplier")),
            "_distance": abs(strike - spot) if spot is not None else strike,
        })
    future = [item for item in clean if item["expiry_end"] is None or item["expiry_end"] >= as_of]
    nearest_expiry = min(
        (item["expiry_end"] for item in future if item["expiry_end"]),
        default=None,
    )
    nearest = [
        item for item in future
        if nearest_expiry is None or item["expiry_end"] == nearest_expiry
    ]
    selected = []
    for kind in ("CALL", "PUT"):
        candidates = [
            item for item in nearest
            if kind in item["type"].upper()
        ]
        if candidates:
            selected.append(min(candidates, key=lambda item: item["_distance"]))
    if not selected:
        selected = sorted(nearest, key=lambda item: item["_distance"])[:2]
    for item in selected:
        item.pop("_distance", None)
    return selected, expiry_counts, nearest_expiry


def probe_contracts(
    api: FinamReadOnly, contracts: list[dict], h1_start: str, d1_start: str, end: str
) -> list[dict]:
    results = []
    for contract in contracts:
        symbol = contract["symbol"]
        results.append({
            **contract,
            "latest_quote": quote_summary(api, symbol),
            "current_orderbook": orderbook_summary(api, symbol),
            "latest_trades": latest_trades_summary(api, symbol, datetime.now(timezone.utc)),
            "historical_m5": bar_summary(api, symbol, "TIME_FRAME_M5", h1_start, end),
            "historical_h1": bar_summary(api, symbol, "TIME_FRAME_H1", h1_start, end),
            "historical_d1": bar_summary(api, symbol, "TIME_FRAME_D", d1_start, end),
        })
    return results


def main():
    secret = os.environ.get("FINAM_API_SECRET", "")
    if not secret:
        raise ProbeError("FINAM_API_SECRET_missing")
    api = FinamReadOnly(secret)
    now = datetime.now(timezone.utc)
    h1_start = (now - timedelta(days=30)).isoformat(timespec="seconds").replace("+00:00", "Z")
    d1_start = (now - timedelta(days=365)).isoformat(timespec="seconds").replace("+00:00", "Z")
    end = (now + timedelta(minutes=1)).isoformat(timespec="seconds").replace("+00:00", "Z")

    report = {
        "mode": "read_only_finam_options_history_probe",
        "as_of_utc": now.isoformat(),
        "underlyings": {},
        "safety": {
            "session_auth_post_only": True,
            "market_data_get_only": True,
            "account_endpoints_called": False,
            "order_endpoints_called": False,
            "cancel_or_sltp_endpoints_called": False,
            "secret_or_jwt_logged": False,
        },
        "data_limitations": [
            "Bars are aggregated OHLCV trade bars, not historical bid/ask order-book quotes.",
            "A successful bars response does not prove that the historical bars represent executable entry/exit prices.",
        ],
    }

    for underlying in UNDERLYINGS:
        item = {"status": "ok"}
        try:
            spot_quote = quote_summary(api, underlying)
            spot = decimal_value(spot_quote.get("last"))
            chain_status, chain = api.get(
                f"/v1/assets/{quote(underlying, safe='')}/options"
            )
            if chain_status != 200 or not chain:
                item.update({"status": "chain_unavailable", "chain_http_status": chain_status})
                report["underlyings"][underlying] = item
                continue
            options = chain.get("options")
            if not isinstance(options, list):
                item.update({"status": "chain_schema_unexpected", "chain_http_status": chain_status})
                report["underlyings"][underlying] = item
                continue
            contracts, expiry_counts, nearest_expiry = select_contracts(
                options, spot, now.date().isoformat()
            )
            item.update({
                "spot_quote": spot_quote,
                "chain_http_status": chain_status,
                "chain_contract_count": len(options),
                "expiry_distribution": expiry_counts,
                "nearest_expiry": nearest_expiry,
                "option_type_values": sorted({
                    str(o.get("type", "UNKNOWN")) for o in options if isinstance(o, dict)
                }),
                "default_chain_nearest_expiry_contracts": contracts,
                "targeted_expiry_probes": [],
            })
            for expiry in TARGET_EXPIRIES:
                year, month, day = expiry.split("-")
                targeted_status, targeted_chain = api.get(
                    f"/v1/assets/{quote(underlying, safe='')}/options",
                    params={
                        "expiration_date.year": year,
                        "expiration_date.month": month,
                        "expiration_date.day": day,
                    },
                )
                targeted = {
                    "requested_expiry": expiry,
                    "http_status": targeted_status,
                    "chain_contract_count": 0,
                    "selected_contracts": [],
                }
                targeted_options = targeted_chain.get("options") if isinstance(targeted_chain, dict) else None
                if targeted_status == 200 and isinstance(targeted_options, list):
                    targeted_contracts, targeted_expiries, targeted_nearest = select_contracts(
                        targeted_options, spot, now.date().isoformat()
                    )
                    targeted["chain_contract_count"] = len(targeted_options)
                    targeted["expiry_distribution"] = targeted_expiries
                    targeted["nearest_expiry"] = targeted_nearest
                    targeted["selected_contracts"] = probe_contracts(
                        api, targeted_contracts, h1_start, d1_start, end
                    )
                item["targeted_expiry_probes"].append(targeted)
        except ProbeError as exc:
            item.update({"status": "error", "error": str(exc)})
        report["underlyings"][underlying] = item

    output = Path(os.environ.get("FINAM_OPTIONS_PROBE_OUTPUT", "finam-options-history-probe.json"))
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "underlyings": {
            name: {
                "status": value.get("status"),
                "chain_count": value.get("chain_contract_count"),
                "targeted_expiries": [
                    {
                        "expiry": probe.get("requested_expiry"),
                        "chain_count": probe.get("chain_contract_count"),
                        "selected": [
                            {
                                "symbol": c.get("symbol"),
                                "type": c.get("type"),
                                "m5_bars": c.get("historical_m5", {}).get("valid_ohlc_bars"),
                                "h1_bars": c.get("historical_h1", {}).get("valid_ohlc_bars"),
                                "d1_bars": c.get("historical_d1", {}).get("valid_ohlc_bars"),
                            }
                            for c in probe.get("selected_contracts", [])
                        ],
                    }
                    for probe in value.get("targeted_expiry_probes", [])
                ],
                "error": value.get("error"),
            }
            for name, value in report["underlyings"].items()
        },
        "safety": report["safety"],
    }, ensure_ascii=False, indent=2))
    if all(value.get("status") != "ok" for value in report["underlyings"].values()):
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except ProbeError as exc:
        # Never print secret values, tokens, response bodies, or request URLs.
        print(f"FINAM OPTIONS HISTORY PROBE: FAILED ({exc})")
        sys.exit(1)
