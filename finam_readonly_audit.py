import os
import sys
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import requests

BASE_URL = "https://api.finam.ru"
ACCOUNT_ID = os.getenv("FINAM_ACCOUNT_ID")
API_SECRET = os.getenv("FINAM_API_SECRET")
MIC = "MISX"
PAUSE = 1.0

TICKERS = [
    "AFKS", "AFLT", "ALRS", "BSPB", "CBOM", "CHMF", "CNRU", "DOMRF",
    "ENPG", "FLOT", "GAZP", "GMKN", "HEAD", "IRAO", "LKOH", "MAGN",
    "MDMG", "MOEX", "MTSS", "NLMK", "NVTK", "OZON", "PHOR", "PLZL",
    "POSI", "RAGR", "RENI", "ROSN", "RTKM", "RUAL", "SBER", "SBERP",
    "SNGS", "SNGSP", "SVCB", "T", "TATN", "TATNP", "TRNFP", "UGLD",
    "VKCO", "VTBR", "X5", "YDEX"
]

session = requests.Session()


class AuditError(RuntimeError):
    pass


def request_json(method, path, token=None, params=None, payload=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = None
    for attempt in range(3):
        try:
            response = session.request(
                method,
                f"{BASE_URL}{path}",
                headers=headers,
                params=params,
                json=payload,
                timeout=20
            )
        except requests.RequestException as exc:
            # Never print URLs, tokens, account identifiers or response bodies.
            raise AuditError(f"network error ({type(exc).__name__})") from None

        if response.status_code == 429 and attempt < 2:
            retry_after = response.headers.get("Retry-After", "")
            try:
                delay = max(float(retry_after), PAUSE)
            except (TypeError, ValueError):
                delay = 5.0 * (attempt + 1)
            time.sleep(delay)
            continue
        if response.status_code >= 500 and attempt < 2:
            time.sleep(2 ** attempt)
            continue
        break

    if response is None or response.status_code != 200:
        code = response.status_code if response is not None else "no response"
        raise AuditError(f"HTTP {code}")
    try:
        data = response.json()
    except ValueError:
        raise AuditError("invalid JSON response") from None
    if not isinstance(data, dict):
        raise AuditError("unexpected response type")
    # Stay below Finam's shared request-rate limit.
    time.sleep(PAUSE)
    return data


def enum_value(obj):
    return obj.get("value") if isinstance(obj, dict) else obj


def positive_decimal(value):
    if isinstance(value, dict):
        value = value.get("value")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return number.is_finite() and number > 0


def valid_tick_metadata(asset):
    try:
        decimals = int(asset.get("decimals"))
        min_step = Decimal(str(asset.get("min_step", "0")))
    except (TypeError, ValueError, InvalidOperation):
        return False
    if decimals < 0 or not min_step.is_finite() or min_step < 0:
        return False
    if min_step > 0:
        return True
    price_step = asset.get("price_step")
    if not isinstance(price_step, dict):
        return False
    return all(positive_decimal(price_step.get(k)) for k in (
        "step", "threshold_price", "step_from_threshold"
    ))


def parse_position_quantity(account, target_symbol):
    positions = account.get("positions")
    if not isinstance(positions, list):
        raise AuditError("account positions field is missing or malformed")
    total = Decimal("0")
    for position in positions:
        if not isinstance(position, dict):
            raise AuditError("malformed position entry")
        symbol = position.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise AuditError("position entry has no valid symbol")
        if symbol == target_symbol:
            quantity = position.get("quantity")
            if isinstance(quantity, dict):
                quantity = quantity.get("value")
            try:
                parsed = Decimal(str(quantity))
            except (InvalidOperation, TypeError, ValueError):
                raise AuditError("T position quantity is malformed") from None
            if not parsed.is_finite():
                raise AuditError("T position quantity is not finite")
            total += parsed
    return total


def matching_active_orders_for_symbol(response, target_symbol):
    orders = response.get("orders")
    if not isinstance(orders, list):
        raise AuditError("active orders response has no valid orders array")
    matching = []
    for order in orders:
        if not isinstance(order, dict):
            raise AuditError("malformed active order entry")
        nested_order = order.get("order") or {}
        nested_sltp = order.get("sltp_order") or {}
        if not isinstance(nested_order, dict) or not isinstance(nested_sltp, dict):
            raise AuditError("malformed nested active order payload")
        symbol = (
            nested_order.get("symbol")
            or nested_sltp.get("symbol")
            or order.get("symbol")
        )
        if not isinstance(symbol, str) or not symbol:
            raise AuditError("active order entry has no valid symbol")
        status = str(order.get("status", "")).removeprefix("ORDER_STATUS_")
        terminal = {
            "FILLED", "EXECUTED", "CANCELED", "CANCELLED",
            "REJECTED", "REJECTED_BY_EXCHANGE", "DENIED_BY_BROKER",
            "EXPIRED", "FAILED", "DONE_FOR_DAY", "REPLACED"
        }
        if status in terminal and not order.get("triggered_order_id"):
            continue
        if symbol == target_symbol:
            matching.append(order)
    return matching


def safe_order_summary(order):
    # Print only whitelisted order-identification and trading fields.
    allowed = {
        "id", "order_id", "client_order_id", "order_num", "symbol",
        "status", "side", "quantity", "price", "type", "order_type",
        "stop_loss", "take_profit", "trigger_price", "stop_price",
        "quantity_sl", "quantity_tp", "time_in_force", "expiration",
        "created_at", "updated_at", "direction", "operation",
        "instrument", "stop", "take_profit_price", "stop_loss_price"
    }
    summary = {}
    for key in allowed:
        if key in order:
            value = order[key]
            if isinstance(value, (str, int, float, bool)) or value is None:
                summary[key] = value
            elif isinstance(value, dict):
                summary[key] = {
                    k: v for k, v in value.items()
                    if k in allowed and (
                        isinstance(v, (str, int, float, bool)) or v is None
                    )
                }
    for container in ("order", "sltp_order"):
        nested = order.get(container)
        if isinstance(nested, dict):
            summary[container] = {
                key: value for key, value in nested.items()
                if key in allowed and (
                    isinstance(value, (str, int, float, bool)) or value is None
                )
            }
    return summary


def main():
    if not API_SECRET or not ACCOUNT_ID:
        raise AuditError("required Finam credentials are missing")

    # Authentication only. This POST creates a session token; it is not an order.
    auth = request_json("POST", "/v1/sessions", payload={"secret": API_SECRET})
    token = auth.get("token")
    if not token:
        raise AuditError("Finam did not return a session token")

    # Read-only account request. No balance, position, or account id is printed.
    account = request_json(
        "GET", f"/v1/accounts/{quote(ACCOUNT_ID, safe='')}", token=token
    )
    if account.get("account_id") and str(account["account_id"]) != str(ACCOUNT_ID):
        raise AuditError("account identity mismatch")
    print("Finam authentication: OK")
    print("Finam account read: OK")

    # Reconcile the previously traded instrument using GET-only endpoints.
    target_symbol = "T@MISX"
    t_quantity = parse_position_quantity(account, target_symbol)
    active_orders = request_json(
        "GET",
        f"/v1/accounts/{quote(ACCOUNT_ID, safe='')}/orders",
        token=token
    )
    t_orders = matching_active_orders_for_symbol(active_orders, target_symbol)
    t_order_count = len(t_orders)
    print(f"T position quantity ({target_symbol}): {t_quantity}")
    print(f"Active T orders ({target_symbol}, including stop orders): {t_order_count}")
    for index, order in enumerate(t_orders, start=1):
        print(f"T active order {index} (sanitized): {safe_order_summary(order)}")
    if t_quantity != 0 or t_order_count != 0:
        raise AuditError("T position or active orders remain; stop before any trading")

    params_ok = 0
    tick_ok = 0
    long_allowed = 0
    short_allowed = 0
    long_blocked = []
    short_blocked = []
    not_tradable = 0
    failures = []

    for ticker in TICKERS:
        symbol = f"{ticker}@{MIC}"
        try:
            params = request_json(
                "GET",
                f"/v1/assets/{quote(symbol, safe='')}/params",
                token=token,
                params={"account_id": ACCOUNT_ID}
            )
            asset = request_json(
                "GET",
                f"/v1/assets/{quote(symbol, safe='')}",
                token=token,
                params={"account_id": ACCOUNT_ID}
            )
            if params.get("is_tradable") is True:
                lot = params.get("trade_lot_size")
                try:
                    lot_ok = int(lot) > 0
                except (TypeError, ValueError):
                    lot_ok = False
                if lot_ok:
                    params_ok += 1
                else:
                    failures.append(f"{ticker}: invalid trade_lot_size")
            else:
                not_tradable += 1

            if enum_value(params.get("longable")) in ("AVAILABLE", "1", 1):
                long_allowed += 1
            else:
                long_blocked.append(ticker)
            if enum_value(params.get("shortable")) in (
                "AVAILABLE", "AVAILABLE_STRATEGY", "1", "4", 1, 4
            ):
                short_allowed += 1
            else:
                short_blocked.append(ticker)
            if valid_tick_metadata(asset):
                tick_ok += 1
            else:
                failures.append(f"{ticker}: invalid tick metadata")
        except AuditError as exc:
            failures.append(f"{ticker}: {exc}")

    print(f"Instrument parameters with valid trade lot: {params_ok}/{len(TICKERS)}")
    print(f"Instrument tick metadata valid: {tick_ok}/{len(TICKERS)}")
    print(f"LONG permission available: {long_allowed}/{len(TICKERS)}")
    print(f"SHORT permission available: {short_allowed}/{len(TICKERS)}")
    print(f"LONG blocked tickers: {', '.join(long_blocked) if long_blocked else 'none'}")
    print(f"SHORT blocked tickers: {', '.join(short_blocked) if short_blocked else 'none'}")
    print(f"Not tradable for this account: {not_tradable}/{len(TICKERS)}")
    print(f"Instrument audit errors: {len(failures)}")
    for failure in failures:
        print(failure)

    if failures or params_ok + not_tradable != len(TICKERS):
        raise AuditError("one or more instruments could not be fully audited")
    print("READ-ONLY FINAM AUDIT: SUCCESS")
    print("Account positions and active orders were checked using GET only; no broker orders were submitted.")


if __name__ == "__main__":
    try:
        main()
    except AuditError as exc:
        print(f"READ-ONLY FINAM AUDIT: FAILED ({exc})")
        sys.exit(1)
