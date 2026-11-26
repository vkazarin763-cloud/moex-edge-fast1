#!/usr/bin/env python3
"""Read-only Finam options-chain and quote availability probe.

This module deliberately has no account, order, cancel, or SL/TP calls.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://api.finam.ru"
UNDERLYINGS = ("GAZP@MISX", "SBER@MISX", "ROSN@MISX", "MOEX@MISX")
MAX_OPTION_QUOTES_PER_UNDERLYING = 12
TIMEOUT = 25


def decimal_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def option_type(value: Any) -> str:
    return str(value or "").upper()


def quote_quality(quote: dict[str, Any]) -> dict[str, Any]:
    bid = decimal_value(quote.get("bid"))
    ask = decimal_value(quote.get("ask"))
    last = decimal_value(quote.get("last"))
    bid_size = decimal_value(quote.get("bid_size"))
    ask_size = decimal_value(quote.get("ask_size"))
    mid = (bid + ask) / 2 if bid is not None and ask is not None and bid > 0 and ask >= bid else None
    spread_pct = ((ask - bid) / mid * 100) if mid and ask is not None and bid is not None else None
    timestamp = quote.get("timestamp")
    return {
        "bid": bid,
        "ask": ask,
        "last": last,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "timestamp": timestamp,
        "spread_pct_of_mid": round(spread_pct, 3) if spread_pct is not None else None,
        "quote_valid": bool(bid is not None and ask is not None and bid > 0 and ask >= bid),
    }


def request_json(session: requests.Session, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    response = session.request(method, f"{BASE_URL}{path}", timeout=TIMEOUT, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected response type for {path}")
    return payload


def authenticate(secret: str) -> str:
    response = requests.post(
        f"{BASE_URL}/v1/sessions",
        json={"secret": secret},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    token = response.json().get("token")
    if not token:
        raise RuntimeError("Finam auth response did not contain an access token")
    return str(token)


def strike_distance(option: dict[str, Any], spot: float | None) -> float:
    strike = decimal_value(option.get("strike"))
    if spot is None or strike is None:
        return float("inf")
    return abs(strike - spot)


def compact_option(option: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "symbol", "type", "strike", "multiplier", "contract_size",
        "trade_first_day", "trade_last_day",
        "expiration_first_day", "expiration_last_day",
    )
    return {key: option.get(key) for key in keys if key in option}


def probe_underlying(session: requests.Session, underlying: str) -> dict[str, Any]:
    item: dict[str, Any] = {"underlying": underlying}
    try:
        underlying_quote = request_json(
            session, "GET", f"/v1/instruments/{underlying}/quotes/latest"
        ).get("quote", {})
        spot = decimal_value(underlying_quote.get("last"))
        item["underlying_quote"] = {
            "last": spot,
            "bid": decimal_value(underlying_quote.get("bid")),
            "ask": decimal_value(underlying_quote.get("ask")),
            "timestamp": underlying_quote.get("timestamp"),
        }
    except Exception as exc:  # noqa: BLE001 - record per-underlying API failures
        spot = None
        item["underlying_quote_error"] = f"{type(exc).__name__}: {exc}"

    try:
        chain = request_json(session, "GET", f"/v1/assets/{underlying}/options")
        options = chain.get("options", [])
        if not isinstance(options, list):
            raise ValueError("OptionsChain response has no options array")
        item["chain_count"] = len(options)
        item["chain_expiry_scope"] = "Finam default chain response; verify returned expiry dates"
        ordered = sorted(
            options,
            key=lambda opt: strike_distance(opt, spot),
        )
        selected = ordered[:MAX_OPTION_QUOTES_PER_UNDERLYING]
        samples = []
        for option in selected:
            symbol = option.get("symbol")
            row: dict[str, Any] = {"contract": compact_option(option)}
            if not symbol:
                row["quote_error"] = "Option chain row has no symbol"
            else:
                try:
                    quote_payload = request_json(
                        session, "GET",
                        f"/v1/instruments/{requests.utils.quote(str(symbol), safe='@')}/quotes/latest",
                    )
                    quote = quote_payload.get("quote", {})
                    row["quote"] = quote_quality(quote)
                    option_metrics = quote.get("option")
                    if isinstance(option_metrics, dict):
                        row["option_metrics"] = {
                            key: decimal_value(option_metrics.get(key))
                            for key in ("implied_volatility", "theoretical_price", "delta",
                                        "gamma", "theta", "vega", "rho", "open_interest")
                            if key in option_metrics
                        }
                except Exception as exc:  # noqa: BLE001
                    row["quote_error"] = f"{type(exc).__name__}: {exc}"
            samples.append(row)
        item["sampled_contracts"] = samples
    except Exception as exc:  # noqa: BLE001
        item["chain_error"] = f"{type(exc).__name__}: {exc}"
    return item


def main() -> int:
    secret = os.environ.get("FINAM_API_SECRET", "").strip()
    if not secret:
        print("FINAM_API_SECRET is missing", file=sys.stderr)
        return 2

    token = authenticate(secret)
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "Finam Trade API",
        "mode": "READ_ONLY_MARKET_DATA_ONLY",
        "order_endpoints_called": False,
        "underlyings": [probe_underlying(session, symbol) for symbol in UNDERLYINGS],
    }

    output = Path("artifacts/moex_options_probe.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    total_chains = sum("chain_count" in row for row in report["underlyings"])
    total_contracts = sum(row.get("chain_count", 0) for row in report["underlyings"])
    total_quotes = sum(
        1 for row in report["underlyings"]
        for contract in row.get("sampled_contracts", [])
        if contract.get("quote", {}).get("quote_valid")
    )
    print(f"Underlying chains returned: {total_chains}/{len(UNDERLYINGS)}")
    print(f"Contracts listed in returned chains: {total_contracts}")
    print(f"Valid sampled bid/ask quotes: {total_quotes}")
    print(f"Report written: {output}")
    print("READ-ONLY: no account, order, cancel, or SL/TP endpoints were called.")

    # API access is considered successful if at least one chain was returned.
    # Quote coverage is reported independently; it is not silently treated as success.
    return 0 if total_chains else 1


if __name__ == "__main__":
    raise SystemExit(main())
