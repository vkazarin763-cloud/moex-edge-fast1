"""Two-minute, read-only Finam gRPC market-data stream probe."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from google.protobuf.json_format import MessageToDict
from finam_trade_api import AsyncFinamClient
from finam_trade_api.market_data import (
    SubscribeLatestTradesRequest,
    SubscribeOrderBookRequest,
    SubscribeQuoteRequest,
)

DEFAULT_SYMBOLS = ("GZ100CX6@RTSX", "SR290CX6@RTSX")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main() -> None:
    secret = os.environ.get("FINAM_API_SECRET", "")
    if not secret:
        raise RuntimeError("FINAM_API_SECRET_missing")
    duration = int(os.environ.get("CAPTURE_SECONDS", "120"))
    if not 30 <= duration <= 300:
        raise ValueError("CAPTURE_SECONDS_must_be_30_to_300")
    symbols = tuple(
        item.strip()
        for item in os.environ.get("OPTION_SYMBOLS", ",".join(DEFAULT_SYMBOLS)).split(",")
        if item.strip()
    )
    if not symbols or len(symbols) > 4:
        raise ValueError("OPTION_SYMBOLS_must_contain_1_to_4_symbols")

    output = Path("finam-options-grpc-streams.jsonl")
    counts: Counter[str] = Counter()
    errors: list[dict] = []
    started = utc_now()

    def write_record(handle, record: dict) -> None:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()

    with output.open("w", encoding="utf-8") as handle:
        write_record(handle, {
            "record_type": "metadata",
            "started_at_utc": started,
            "duration_seconds": duration,
            "symbols": symbols,
            "transport": "Finam official Python SDK / gRPC server streams",
            "subscriptions": ["SubscribeQuote", "SubscribeOrderBook", "SubscribeLatestTrades"],
            "safety": {
                "market_data_streams_only": True,
                "account_endpoints_called": False,
                "orders_or_cancellations_called": False,
                "secret_or_token_written": False,
            },
        })

        async with AsyncFinamClient(secret=secret) as client:
            async def consume(name: str, symbol: str, request, method) -> None:
                try:
                    stream = method(request)
                    async for message in stream:
                        payload = MessageToDict(message, preserving_proto_field_name=True)
                        write_record(handle, {
                            "record_type": "market_event",
                            "received_at_utc": utc_now(),
                            "subscription": name,
                            "symbol": symbol,
                            "payload": payload,
                        })
                        counts[f"{name}:{symbol}"] += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    item = {
                        "subscription": name,
                        "symbol": symbol,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                        "at_utc": utc_now(),
                    }
                    errors.append(item)
                    write_record(handle, {"record_type": "stream_error", **item})

            tasks = [
                asyncio.create_task(
                    consume(
                        "SubscribeQuote",
                        ",".join(symbols),
                        SubscribeQuoteRequest(symbols=list(symbols)),
                        client.market_data.SubscribeQuote,
                    )
                )
            ]
            for symbol in symbols:
                tasks.append(asyncio.create_task(consume(
                    "SubscribeOrderBook", symbol,
                    SubscribeOrderBookRequest(symbol=symbol),
                    client.market_data.SubscribeOrderBook,
                )))
                tasks.append(asyncio.create_task(consume(
                    "SubscribeLatestTrades", symbol,
                    SubscribeLatestTradesRequest(symbol=symbol),
                    client.market_data.SubscribeLatestTrades,
                )))

            try:
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=duration)
            except asyncio.TimeoutError:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        total = sum(counts.values())
        write_record(handle, {
            "record_type": "summary",
            "finished_at_utc": utc_now(),
            "duration_seconds": duration,
            "events_total": total,
            "events_by_subscription_symbol": dict(counts),
            "stream_errors": errors,
            "result": "events_received" if total else "no_stream_events",
            "note": (
                "received_at_utc is client receipt time; payload timestamps are provider event times. "
                "Order-book stream messages may be deltas; inspect is_data_snapshot before rebuilding a book."
            ),
        })

    print(json.dumps({
        "status": "completed",
        "events_total": sum(counts.values()),
        "events_by_subscription_symbol": dict(counts),
        "stream_errors": len(errors),
        "artifact": str(output),
    }, ensure_ascii=False))
    if not counts:
        raise SystemExit("No market-data stream events received")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (RuntimeError, ValueError) as exc:
        print(f"FINAM GRPC STREAM PROBE: FAILED ({exc})")
        sys.exit(1)
