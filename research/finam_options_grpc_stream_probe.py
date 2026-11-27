"""Bounded, read-only Finam gRPC stream and permission diagnostics."""
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
from finam_trade_api.auth_messages import TokenDetailsRequest
from finam_trade_api.market_data import (
    QuoteRequest,
    SubscribeLatestTradesRequest,
    SubscribeOrderBookRequest,
    SubscribeQuoteRequest,
)

DEFAULT_SYMBOLS = (
    "GZ100CL6@RTSX",
    "GZ100CX6@RTSX",
    "SR290CL6@RTSX",
    "SR290CX6@RTSX",
)
DEFAULT_CONTROL_SYMBOL = "SBER@MISX"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def age_seconds(received_at: str, provider_timestamp: str | None) -> float | None:
    received = parse_timestamp(received_at)
    provider = parse_timestamp(provider_timestamp)
    if received is None or provider is None:
        return None
    return round((received - provider).total_seconds(), 3)


async def main() -> None:
    secret = os.environ.get("FINAM_API_SECRET", "")
    if not secret:
        raise RuntimeError("FINAM_API_SECRET_missing")
    duration = int(os.environ.get("CAPTURE_SECONDS", "180"))
    if not 30 <= duration <= 300:
        raise ValueError("CAPTURE_SECONDS_must_be_30_to_300")
    symbols = tuple(
        item.strip()
        for item in os.environ.get("OPTION_SYMBOLS", ",".join(DEFAULT_SYMBOLS)).split(",")
        if item.strip()
    )
    if not symbols or len(symbols) > 4 or len(set(symbols)) != len(symbols):
        raise ValueError("OPTION_SYMBOLS_must_contain_1_to_4_unique_symbols")
    control_symbol = os.environ.get("CONTROL_SYMBOL", DEFAULT_CONTROL_SYMBOL).strip()
    if not control_symbol or control_symbol in symbols:
        raise ValueError("CONTROL_SYMBOL_must_be_nonempty_and_distinct")

    output = Path("finam-options-grpc-streams.jsonl")
    counts: Counter[str] = Counter()
    errors: list[dict] = []
    tracked_symbols = (*symbols, control_symbol)
    stats = {
        item: {
            "quote": {"messages": 0, "snapshots": 0, "updates": 0, "unique_provider_timestamps": 0,
                      "duplicate_timestamps": 0, "fresh_unique_updates": 0, "stale_unique_updates": 0,
                      "last_provider_timestamp": None, "last_age_seconds": None},
            "order_book": {"messages": 0, "snapshots": 0, "delta_messages": 0, "delta_rows": 0,
                           "unique_delta_signatures": 0, "duplicate_delta_signatures": 0,
                           "actions": {}, "newest_row_age_seconds": None},
            "trades": {"messages": 0},
            "_quote_timestamps": set(),
            "_book_signatures": set(),
        }
        for item in tracked_symbols
    }
    started = utc_now()

    def write_record(handle, record: dict) -> None:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()

    with output.open("w", encoding="utf-8") as handle:
        write_record(handle, {
            "record_type": "metadata",
            "started_at_utc": started,
            "duration_seconds": duration,
            "option_symbols": symbols,
            "control_symbol": control_symbol,
            "transport": "Finam official Python SDK / gRPC server streams",
            "subscriptions": ["SubscribeQuote", "SubscribeOrderBook", "SubscribeLatestTrades"],
            "safety": {
                "market_data_streams_only": True,
                "token_details_metadata_only": True,
                "account_ids_or_balances_written": False,
                "orders_or_cancellations_called": False,
                "secret_or_token_written": False,
            },
        })

        async with AsyncFinamClient(secret=secret) as client:
            # Check the token's market-data entitlements without recording the JWT
            # or account identifiers. The SDK keeps AuthService on a channel
            # without Authorization metadata, as required by Finam.
            try:
                token = client.get_token()
                if not token:
                    raise RuntimeError("SDK_did_not_return_a_session_token")
                details = await client.auth.TokenDetails(TokenDetailsRequest(token=token))
                write_record(handle, {
                    "record_type": "token_diagnostics",
                    "at_utc": utc_now(),
                    "readonly": bool(details.readonly),
                    "account_count": len(details.account_ids),
                    "md_permissions": [
                        MessageToDict(item, preserving_proto_field_name=True)
                        for item in details.md_permissions
                    ],
                })
            except Exception as exc:
                item = {
                    "diagnostic": "TokenDetails",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                    "at_utc": utc_now(),
                }
                errors.append(item)
                write_record(handle, {"record_type": "diagnostic_error", **item})

            # Unary snapshots distinguish symbol/access problems from a stream
            # that remains open but emits no updates.
            diagnostic_symbols = tuple(dict.fromkeys((*symbols, control_symbol)))
            for symbol in diagnostic_symbols:
                try:
                    snapshot = await client.market_data.LastQuote(QuoteRequest(symbol=symbol))
                    write_record(handle, {
                        "record_type": "last_quote_snapshot",
                        "at_utc": utc_now(),
                        "symbol": symbol,
                        "payload": MessageToDict(snapshot, preserving_proto_field_name=True),
                    })
                except Exception as exc:
                    item = {
                        "diagnostic": "LastQuote",
                        "symbol": symbol,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                        "at_utc": utc_now(),
                    }
                    errors.append(item)
                    write_record(handle, {"record_type": "diagnostic_error", **item})

            async def consume(name: str, symbol: str, request, method) -> None:
                try:
                    stream = method(request)
                    async for message in stream:
                        received = utc_now()
                        payload = MessageToDict(message, preserving_proto_field_name=True)
                        write_record(handle, {
                            "record_type": "market_event",
                            "received_at_utc": received,
                            "subscription": name,
                            "symbol": symbol,
                            "payload": payload,
                        })
                        counts[f"{name}:{symbol}"] += 1

                        # Normalize repeated fields: one gRPC envelope may contain
                        # several instruments, and repeated snapshots are not fresh updates.
                        if name == "SubscribeQuote":
                            quote_items = payload.get("quote", [])
                            if isinstance(quote_items, dict):
                                quote_items = [quote_items]
                            for quote in quote_items if isinstance(quote_items, list) else []:
                                item_symbol = quote.get("symbol") or symbol
                                if item_symbol not in stats:
                                    continue
                                q = stats[item_symbol]["quote"]
                                q["messages"] += 1
                                provider_ts = quote.get("timestamp")
                                q["last_provider_timestamp"] = provider_ts
                                age = age_seconds(received, provider_ts)
                                q["last_age_seconds"] = age
                                is_snapshot = bool(quote.get("is_data_snapshot", False))
                                q["snapshots" if is_snapshot else "updates"] += 1
                                unique = bool(provider_ts) and provider_ts not in stats[item_symbol]["_quote_timestamps"]
                                if unique:
                                    stats[item_symbol]["_quote_timestamps"].add(provider_ts)
                                    q["unique_provider_timestamps"] += 1
                                    if not is_snapshot and age is not None:
                                        q["fresh_unique_updates" if age <= 60 else "stale_unique_updates"] += 1
                                elif provider_ts:
                                    q["duplicate_timestamps"] += 1
                                write_record(handle, {
                                    "record_type": "normalized_market_item",
                                    "received_at_utc": received,
                                    "subscription": name,
                                    "symbol": item_symbol,
                                    "provider_timestamp": provider_ts,
                                    "age_seconds": age,
                                    "is_snapshot": is_snapshot,
                                    "unique_provider_timestamp": unique,
                                })

                        elif name == "SubscribeOrderBook":
                            book_items = payload.get("order_book", [])
                            if isinstance(book_items, dict):
                                book_items = [book_items]
                            for book in book_items if isinstance(book_items, list) else []:
                                item_symbol = book.get("symbol") or symbol
                                if item_symbol not in stats:
                                    continue
                                b = stats[item_symbol]["order_book"]
                                b["messages"] += 1
                                is_snapshot = bool(book.get("is_data_snapshot", False))
                                rows = book.get("rows", []) or []
                                if is_snapshot:
                                    b["snapshots"] += 1
                                else:
                                    b["delta_messages"] += 1
                                    b["delta_rows"] += len(rows)
                                actions = Counter(str(row.get("action", "UNKNOWN")) for row in rows)
                                for action, count in actions.items():
                                    b["actions"][action] = b["actions"].get(action, 0) + count
                                signature = tuple(sorted(
                                    (str(row.get("timestamp")), str(row.get("price")), str(row.get("action")))
                                    for row in rows
                                ))
                                unique = signature not in stats[item_symbol]["_book_signatures"]
                                if unique:
                                    stats[item_symbol]["_book_signatures"].add(signature)
                                    if not is_snapshot:
                                        b["unique_delta_signatures"] += 1
                                elif not is_snapshot:
                                    b["duplicate_delta_signatures"] += 1
                                row_ages = [age_seconds(received, row.get("timestamp")) for row in rows]
                                row_ages = [age for age in row_ages if age is not None]
                                if row_ages:
                                    b["newest_row_age_seconds"] = min(row_ages)
                                write_record(handle, {
                                    "record_type": "normalized_market_item",
                                    "received_at_utc": received,
                                    "subscription": name,
                                    "symbol": item_symbol,
                                    "row_count": len(rows),
                                    "row_actions": dict(actions),
                                    "is_snapshot": is_snapshot,
                                    "unique_delta_signature": unique,
                                    "newest_row_age_seconds": min(row_ages) if row_ages else None,
                                })

                        elif name == "SubscribeLatestTrades":
                            trade_items = payload.get("trade", [])
                            if isinstance(trade_items, dict):
                                trade_items = [trade_items]
                            for trade in trade_items if isinstance(trade_items, list) else []:
                                item_symbol = trade.get("symbol") or symbol
                                if item_symbol in stats:
                                    stats[item_symbol]["trades"]["messages"] += 1

                        # Finam can report a stream-level error inside the
                        # protobuf response instead of terminating the RPC.
                        stream_error = payload.get("error")
                        if stream_error:
                            item = {
                                "subscription": name,
                                "symbol": symbol,
                                "server_stream_error": stream_error,
                                "at_utc": utc_now(),
                            }
                            errors.append(item)
                            write_record(handle, {"record_type": "stream_server_error", **item})
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

            # Include a known liquid share as a control in the quote stream.
            quote_symbols = list(diagnostic_symbols)
            tasks = [asyncio.create_task(consume(
                "SubscribeQuote",
                ",".join(quote_symbols),
                SubscribeQuoteRequest(symbols=quote_symbols),
                client.market_data.SubscribeQuote,
            ))]
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
        clean_stats = {
            item: {key: value for key, value in data.items() if not key.startswith("_")}
            for item, data in stats.items()
        }
        fresh_updates = sum(stats[item]["quote"]["fresh_unique_updates"] for item in symbols)
        fresh_control_updates = stats[control_symbol]["quote"]["fresh_unique_updates"]
        book_deltas = sum(stats[item]["order_book"]["unique_delta_signatures"] for item in symbols)
        trade_items = sum(stats[item]["trades"]["messages"] for item in symbols)
        write_record(handle, {
            "record_type": "summary",
            "finished_at_utc": utc_now(),
            "duration_seconds": duration,
            "stream_envelopes_total": total,
            "stream_envelopes_by_subscription_symbol": dict(counts),
            "fresh_unique_option_quote_updates": fresh_updates,
            "fresh_unique_control_quote_updates": fresh_control_updates,
            "unique_option_order_book_delta_messages": book_deltas,
            "trade_items_total": trade_items,
            "instrument_quality": clean_stats,
            "diagnostic_errors": errors,
            "result": "fresh_option_updates" if fresh_updates or book_deltas or trade_items else "no_fresh_option_updates",
            "note": (
                "Counts are normalized per instrument item, not per gRPC envelope. Repeated provider timestamps are deduplicated. "
                "Fresh means provider timestamp age <= 60 seconds at receipt. Snapshots are not counted as quote updates. "
                "SBER@MISX is a control symbol."
            ),
        })

    print(json.dumps({
        "status": "completed",
        "stream_envelopes_total": sum(counts.values()),
        "fresh_unique_option_quote_updates": fresh_updates,
        "fresh_unique_control_quote_updates": fresh_control_updates,
        "unique_option_order_book_delta_messages": book_deltas,
        "trade_items_total": trade_items,
        "instrument_quality": clean_stats,
        "diagnostic_errors": len(errors),
        "artifact": str(output),
    }, ensure_ascii=False))
    if not fresh_updates and not book_deltas and not trade_items:
        raise SystemExit("No fresh market-data updates received")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (RuntimeError, ValueError) as exc:
        print(f"FINAM GRPC STREAM PROBE: FAILED ({exc})")
        sys.exit(1)
