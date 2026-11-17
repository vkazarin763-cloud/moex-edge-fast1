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
PAUSE = 0.12

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
    if response.status_code != 200:
        raise AuditError(f"HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        raise AuditError("invalid JSON response") from None
    if not isinstance(data, dict):
        raise AuditError("unexpected response type")
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
    time.sleep(PAUSE)

    params_ok = 0
    tick_ok = 0
    long_allowed = 0
    short_allowed = 0
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
                not_tradable += 1

            if enum_value(params.get("longable")) in ("AVAILABLE", "1", 1):
                long_allowed += 1
            if enum_value(params.get("shortable")) in (
                "AVAILABLE", "AVAILABLE_STRATEGY", "1", "4", 1, 4
            ):
                short_allowed += 1
            if valid_tick_metadata(asset):
                tick_ok += 1
            else:
                failures.append(f"{ticker}: invalid tick metadata")
        except AuditError as exc:
            failures.append(f"{ticker}: {exc}")
        time.sleep(PAUSE)

    print(f"Instrument parameters with valid trade lot: {params_ok}/{len(TICKERS)}")
    print(f"Instrument tick metadata valid: {tick_ok}/{len(TICKERS)}")
    print(f"LONG permission available: {long_allowed}/{len(TICKERS)}")
    print(f"SHORT permission available: {short_allowed}/{len(TICKERS)}")
    print(f"Not tradable for this account: {not_tradable}/{len(TICKERS)}")
    print(f"Instrument audit errors: {len(failures)}")
    for failure in failures:
        print(failure)

    if failures or params_ok + not_tradable != len(TICKERS):
        raise AuditError("one or more instruments could not be fully audited")
    print("READ-ONLY FINAM AUDIT: SUCCESS")
    print("No order endpoints were called; no broker orders were submitted.")


if __name__ == "__main__":
    try:
        main()
    except AuditError as exc:
        print(f"READ-ONLY FINAM AUDIT: FAILED ({exc})")
        sys.exit(1)
