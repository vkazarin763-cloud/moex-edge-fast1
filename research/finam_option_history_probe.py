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
    if isinstance(item, datetime):
        return item.astimezone(timezone.utc) if item.tzinfo else item.replace(tzinfo=timezone.utc)
    if isinstance(item, str):
        try:
            parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if isinstance(item, (int, float)):
        try:
            return datetime.fromtimestamp(float(item), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(item, dict):
        try:
            seconds = int(item.get("seconds"))
            nanos = int(item.get("nanos", 0))
            return datetime.fromtimestamp(seconds + nanos / 1_000_000_000, tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            return None
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
    series = [
        {
            "timestamp": stamp.isoformat(),
            "price": str(price),
            "size": str(size),
            "side": trade.get("side"),
            "open_interest": value_of(trade.get("open_interest")),
            "is_data_snapshot": bool(trade.get("is_data_snapshot")),
        }
        for stamp, trade, price, size in parsed
        if price is not None and size is not None and price > 0 and size > 0
    ]
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
        "series": series,
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


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1.0 - alpha) * result[-1])
    return result


def trend_direction(bars: list[dict]) -> str | None:
    if len(bars) < 50:
        return None
    closes = [float(Decimal(str(bar["close"]))) for bar in bars]
    ema20 = ema(closes, 20)[-1]
    ema50 = ema(closes, 50)[-1]
    last = closes[-1]
    if last > ema20 > ema50:
        return "LONG"
    if last < ema20 < ema50:
        return "SHORT"
    return None


def direction_set(d1: str | None, h1: str | None) -> dict[str, str | None]:
    return {
        "D1_ONLY": d1,
        "H1_ONLY": h1,
        "D1_H1_CONFIRMED": d1 if d1 is not None and d1 == h1 else None,
    }


def _parsed_series(series: list[dict], price_key: str) -> list[dict]:
    result = []
    for item in series:
        try:
            stamp = datetime.fromisoformat(str(item["timestamp"]).replace("Z", "+00:00"))
            price = Decimal(str(item[price_key]))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        else:
            stamp = stamp.astimezone(timezone.utc)
        if price.is_finite() and price > 0:
            result.append({**item, "_timestamp": stamp, "_price": price})
    return sorted(result, key=lambda item: item["_timestamp"])


def option_trade_price_replay(underlyings: dict, now: datetime, signal_days: int = 20) -> dict:
    """Gross trade-print proxy only; not executable bid/ask backtest."""
    methods = ("D1_ONLY", "H1_ONLY", "D1_H1_CONFIRMED")
    horizons = (1, 3, 5)
    observations = {method: {h: [] for h in horizons} for method in methods}
    per_asset = {}
    today = now.date()

    for underlying, item in underlyings.items():
        history = item.get("underlying_history", {})
        h1_data = history.get("h1", {})
        d1_data = history.get("d1", {})
        h1 = _parsed_series(h1_data.get("series", []), "close")
        d1 = _parsed_series(d1_data.get("series", []), "close")
        # Exclude today's unfinished daily bar and any unfinished hourly bar.
        d1 = [bar for bar in d1 if bar["_timestamp"].date() < today]
        h1 = [bar for bar in h1 if bar["_timestamp"] + timedelta(hours=1) <= now]
        asset_result = {
            "underlying_d1_bars": len(d1),
            "underlying_h1_bars": len(h1),
            "signals": {method: [] for method in methods},
            "status": "ok",
        }
        if len(d1) < 50 or len(h1) < 50:
            asset_result["status"] = "insufficient_underlying_history"
            per_asset[underlying] = asset_result
            continue

        expiry_probe = next(
            (probe for probe in item.get("targeted_expiry_probes", [])
             if probe.get("requested_expiry") == "2026-12-16"),
            None,
        )
        contracts = expiry_probe.get("selected_contracts", []) if expiry_probe else []
        option_by_type = {
            contract.get("type"): _parsed_series(
                contract.get("latest_trades", {}).get("series", []), "price"
            )
            for contract in contracts
        }
        call_trades = option_by_type.get("TYPE_CALL", [])
        put_trades = option_by_type.get("TYPE_PUT", [])
        asset_result["option_trade_counts"] = {
            "CALL": len(call_trades), "PUT": len(put_trades)
        }

        signal_indices = list(range(max(50, len(d1) - signal_days), len(d1)))
        for index in signal_indices:
            day = d1[index]["_timestamp"].date()
            h1_today = [bar for bar in h1 if bar["_timestamp"].date() <= day]
            h1_previous = [bar for bar in h1 if bar["_timestamp"].date() < day]
            d1_now = trend_direction(d1[:index + 1])
            h1_now = trend_direction(h1_today)
            current = direction_set(d1_now, h1_now)
            previous = direction_set(
                trend_direction(d1[:index]) if index else None,
                trend_direction(h1_previous),
            )
            # Signal time is the end of the last completed H1 bar available that day.
            day_h1 = [bar for bar in h1 if bar["_timestamp"].date() == day]
            if not day_h1:
                continue
            signal_time = max(bar["_timestamp"] for bar in day_h1) + timedelta(hours=1)
            events = {
                method: direction if direction is not None and direction != previous[method] else None
                for method, direction in current.items()
            }
            for method, direction in events.items():
                if direction is None:
                    continue
                option_trades = call_trades if direction == "LONG" else put_trades
                if len(option_trades) < 2:
                    continue
                entry_candidates = [trade for trade in option_trades if trade["_timestamp"] >= signal_time]
                if not entry_candidates:
                    continue
                entry = entry_candidates[0]
                for horizon in horizons:
                    target_index = index + horizon
                    if target_index >= len(d1):
                        continue
                    target_day = d1[target_index]["_timestamp"].date()
                    target_h1 = [bar for bar in h1 if bar["_timestamp"].date() == target_day]
                    if not target_h1:
                        continue
                    target_time = max(bar["_timestamp"] for bar in target_h1) + timedelta(hours=1)
                    exits = [trade for trade in option_trades if trade["_timestamp"] >= target_time]
                    if not exits:
                        continue
                    exit_trade = exits[0]
                    if exit_trade["_timestamp"] <= entry["_timestamp"]:
                        continue
                    result_pct = float((exit_trade["_price"] / entry["_price"] - 1) * 100)
                    observation = {
                        "underlying": underlying,
                        "method": method,
                        "direction": direction,
                        "option_type": "CALL" if direction == "LONG" else "PUT",
                        "entry_timestamp": entry["_timestamp"].isoformat(),
                        "entry_trade_price": str(entry["_price"]),
                        "entry_trade_size": entry.get("size"),
                        "entry_trade_side": entry.get("side"),
                        "exit_timestamp": exit_trade["_timestamp"].isoformat(),
                        "exit_trade_price": str(exit_trade["_price"]),
                        "exit_trade_size": exit_trade.get("size"),
                        "exit_trade_side": exit_trade.get("side"),
                        "trade_price_return_pct": round(result_pct, 4),
                        "entry_delay_hours": round((entry["_timestamp"] - signal_time).total_seconds() / 3600, 2),
                        "actual_holding_hours": round((exit_trade["_timestamp"] - entry["_timestamp"]).total_seconds() / 3600, 2),
                    }
                    observations[method][horizon].append(observation)
                    asset_result["signals"][method].append(observation)
        per_asset[underlying] = asset_result

    aggregate = {}
    for method in methods:
        aggregate[method] = {}
        for horizon in horizons:
            values = [o["trade_price_return_pct"] for o in observations[method][horizon]]
            aggregate[method][str(horizon)] = {
                "completed": len(values),
                "positive": sum(v > 0 for v in values),
                "win_rate_pct": round(sum(v > 0 for v in values) / len(values) * 100, 2) if values else None,
                "mean_trade_price_return_pct": round(sum(values) / len(values), 4) if values else None,
                "median_trade_price_return_pct": round(sorted(values)[len(values)//2], 4) if values else None,
                "worst_trade_price_return_pct": round(min(values), 4) if values else None,
                "best_trade_price_return_pct": round(max(values), 4) if values else None,
            }
    return {
        "mode": "underlying_ema_signal_vs_actual_option_trade_prints",
        "signal_window_sessions": signal_days,
        "entry": "First actual option trade print after the end of the signal day's last completed underlying H1 bar.",
        "exit": "First actual option trade print after the end of the 1/3/5-session target day's last completed underlying H1 bar.",
        "option_selection": "Nearest-to-ATM CALL for LONG or PUT for SHORT, expiry 2026-12-16.",
        "results": aggregate,
        "per_asset": per_asset,
        "critical_limitations": [
            "Entry and exit are actual trade prints, not historical executable ask/bid quotes.",
            "No historical spread, queue position, fill probability, fees, or slippage is included.",
            "This is a sparse trade-print proxy, not a validated options backtest or profitability proof.",
        ],
    }


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
            underlying_h1 = bar_summary(api, underlying, "TIME_FRAME_H1", h1_start, end)
            underlying_d1 = bar_summary(api, underlying, "TIME_FRAME_D", d1_start, end)
            item.update({
                "spot_quote": spot_quote,
                "underlying_history": {
                    "h1": underlying_h1,
                    "d1": underlying_d1,
                },
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

    report["trade_price_replay"] = option_trade_price_replay(
        report["underlyings"], datetime.now(timezone.utc), signal_days=20
    )

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
