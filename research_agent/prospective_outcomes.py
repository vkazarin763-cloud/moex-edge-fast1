"""Append-only outcomes for signals first observed in the prospective holdout."""
from __future__ import annotations
import argparse, hashlib, json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any
from .core import BacktestConfig, Candle, Signal, backtest, validate_candles

HOLDOUT_START = date(2026, 11, 20)
COHORT_VERSION = "v1-frozen-2026-11-19"

class OutcomeLedgerError(ValueError):
    """Malformed source data or conflicting append-only outcome history."""

def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def _parse_stamp(value: str) -> datetime:
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is not None and stamp.utcoffset() is not None:
        raise OutcomeLedgerError("MOEX D1 timestamps must be exchange-local naive values")
    return stamp

def _load_d1(candle_report: dict, symbol: str) -> list[Candle]:
    item = candle_report.get("results", {}).get(symbol, {}).get("D1", {})
    if item.get("status") != "OK" or item.get("source") != "MOEX ISS TQBR history":
        raise OutcomeLedgerError(f"{symbol}: native MOEX D1 data unavailable or invalid")
    rows = []
    for index, row in enumerate(item.get("candles", [])):
        try:
            stamp = _parse_stamp(row["timestamp"])
            values = [float(row[key]) for key in ("open", "high", "low", "close", "volume")]
            rows.append(Candle(stamp, *values))
        except (KeyError, TypeError, ValueError) as exc:
            raise OutcomeLedgerError(f"{symbol}: invalid D1 candle at row {index}: {exc}") from exc
    if not rows:
        raise OutcomeLedgerError(f"{symbol}: empty D1 history")
    return validate_candles(rows)

def _load_signal_events(path: str | Path, holdout_start: date) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    source = Path(path)
    if not source.exists():
        raise OutcomeLedgerError(f"Signal ledger does not exist: {source}")
    with source.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                event_id, cohort, signal = record["event_id"], record["cohort_version"], record["signal"]
                signal_time = _parse_stamp(signal["d1_signal_timestamp"])
                direction, strategy = signal["direction"], signal["strategy"]
                symbol = str(signal["symbol"]).upper()
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise OutcomeLedgerError(f"Invalid signal ledger row {line_no}: {exc}") from exc
            if cohort != COHORT_VERSION or signal_time.date() < holdout_start:
                continue
            if direction not in ("LONG", "SHORT") or not event_id or not strategy or not symbol:
                raise OutcomeLedgerError(f"Invalid prospective signal identity at row {line_no}")
            grouped[symbol].append({
                "event_id": event_id, "signal_time": signal_time,
                "direction": 1 if direction == "LONG" else -1,
                "strategy": strategy, "signal": signal,
            })
    for symbol, events in grouped.items():
        events.sort(key=lambda item: (item["signal_time"], item["strategy"], -item["direction"]))
        seen = set()
        for item in events:
            key = (item["event_id"], item["strategy"])
            if key in seen:
                raise OutcomeLedgerError(f"Duplicate prospective signal event: {item['event_id']}")
            seen.add(key)
    return grouped

def _outcome_id(event_id: str) -> str:
    return hashlib.sha256(("PROSPECTIVE|" + event_id).encode("utf-8")).hexdigest()

def _read_existing(path: Path) -> dict[str, dict]:
    existing = {}
    if not path.exists():
        return existing
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                outcome_id = record["outcome_id"]
                if record["data_origin"] != "PROSPECTIVE" or record["status"] != "CLOSED":
                    raise ValueError("unexpected origin/status")
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise OutcomeLedgerError(f"Invalid outcome ledger row {line_no}") from exc
            if outcome_id in existing and _canonical(existing[outcome_id]) != _canonical(record):
                raise OutcomeLedgerError(f"Conflicting duplicate outcome already stored: {outcome_id}")
            existing[outcome_id] = record
    return existing

def _summary(records: list[dict]) -> dict:
    values = [float(row["net_return"]) for row in records]
    wins, losses = [x for x in values if x > 0], [x for x in values if x <= 0]
    loss_abs = abs(sum(losses))
    return {
        "closed_trades": len(values),
        "win_rate": len(wins) / len(values) if values else None,
        "mean_net_return": mean(values) if values else None,
        "median_net_return": median(values) if values else None,
        "profit_factor": sum(wins) / loss_abs if loss_abs else None,
        "sum_trade_returns_not_portfolio_return": sum(values),
    }

def update_prospective_outcomes(signal_ledger_path: str | Path, candle_report: dict,
                                outcome_ledger_path: str | Path, *,
                                holdout_start: date = HOLDOUT_START,
                                config: BacktestConfig = BacktestConfig()) -> dict:
    """Append newly closed prospective outcomes; leave all open signals pending."""
    grouped = _load_signal_events(signal_ledger_path, holdout_start)
    path = Path(outcome_ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_existing(path)
    candidates = []
    pending_waiting_entry = pending_open = skipped_overlap = 0

    for symbol, events in sorted(grouped.items()):
        rows = _load_d1(candle_report, symbol)
        index_by_time = {row.timestamp: index for index, row in enumerate(rows)}
        signals, event_by_key = [], {}
        for event in events:
            index = index_by_time.get(event["signal_time"])
            if index is None:
                raise OutcomeLedgerError(
                    f"{symbol}: signal candle {event['signal_time'].isoformat()} is absent from current D1 history"
                )
            key = (event["strategy"], event["direction"], event["signal_time"])
            if key in event_by_key:
                raise OutcomeLedgerError(f"{symbol}: ambiguous duplicate signal mapping")
            event_by_key[key] = event
            signals.append(Signal(index, event["direction"], event["strategy"]))
            if index + 1 >= len(rows):
                pending_waiting_entry += 1

        simulated = backtest(rows, signals, config)
        returned_keys = set()
        for trade in simulated:
            key = (trade.strategy, trade.direction, trade.signal_time)
            event = event_by_key.get(key)
            if event is None:
                raise OutcomeLedgerError(f"{symbol}: simulator returned an unmapped trade")
            returned_keys.add(key)
            if trade.status == "OPEN":
                pending_open += 1
                continue
            outcome_id = _outcome_id(event["event_id"])
            record = {
                "schema_version": 1, "outcome_id": outcome_id,
                "event_id": event["event_id"], "data_origin": "PROSPECTIVE",
                "cohort_version": COHORT_VERSION, "symbol": symbol,
                "strategy": trade.strategy,
                "direction": "LONG" if trade.direction > 0 else "SHORT",
                "signal_time": trade.signal_time.isoformat(),
                "entry_time": trade.entry_time.isoformat(),
                "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
                "entry_price": trade.entry_price, "exit_price": trade.exit_price,
                "net_return": trade.net_return, "status": "CLOSED",
                "exit_reason": trade.exit_reason,
                "source_candle_snapshot_utc": candle_report.get("generated_at_utc"),
                "execution_config": {
                    "fee_per_side": config.fee_per_side,
                    "slippage_per_side": config.slippage_per_side,
                    "stop_pct": config.stop_pct, "target_pct": config.target_pct,
                    "max_bars": config.max_bars,
                },
            }
            previous = existing.get(outcome_id)
            if previous is not None:
                if _canonical(previous) != _canonical(record):
                    raise OutcomeLedgerError(f"Previously closed outcome changed; refusing rewrite: {outcome_id}")
            else:
                candidates.append(record)

        for key, event in event_by_key.items():
            if key not in returned_keys and index_by_time[event["signal_time"]] + 1 < len(rows):
                skipped_overlap += 1

    if candidates:
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            for record in candidates:
                stream.write(_canonical(record) + "\n")
            stream.flush()

    combined = list(existing.values()) + candidates
    by_direction = {
        direction: _summary([r for r in combined if r["direction"] == direction])
        for direction in ("LONG", "SHORT")
    }
    by_strategy = {
        strategy: _summary([r for r in combined if r["strategy"] == strategy])
        for strategy in sorted({r["strategy"] for r in combined})
    }
    return {
        "status": "PROSPECTIVE_OUTCOME_TRACKING_READ_ONLY",
        "holdout_start": holdout_start.isoformat(), "cohort_version": COHORT_VERSION,
        "symbols_with_prospective_signals": len(grouped),
        "prospective_signal_events": sum(len(items) for items in grouped.values()),
        "newly_closed": len(candidates), "total_closed": len(combined),
        "pending_waiting_for_entry": pending_waiting_entry,
        "pending_open": pending_open, "skipped_overlap": skipped_overlap,
        "summary": _summary(combined), "by_direction": by_direction,
        "by_strategy": by_strategy,
        "methodology": "Only prospective cohort signals dated on/after holdout start are processed. Native completed MOEX D1 candles are replayed through research_agent.core.backtest with frozen costs/exits. Only CLOSED outcomes are appended; open and not-yet-entered events remain pending. No capital or portfolio return is calculated.",
        "safety": "Read-only research; no broker/account/order/position/sizing/live-trading access.",
    }

def main() -> int:
    parser = argparse.ArgumentParser(description="Update append-only prospective signal outcomes")
    parser.add_argument("--signals-ledger", required=True)
    parser.add_argument("--candles", required=True)
    parser.add_argument("--outcomes-ledger", required=True)
    parser.add_argument("--report", default="moex_edge_prospective_outcomes.json")
    args = parser.parse_args()
    candle_report = json.loads(Path(args.candles).read_text(encoding="utf-8"))
    result = update_prospective_outcomes(args.signals_ledger, candle_report, args.outcomes_ledger)
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Prospective outcomes: new_closed={result['newly_closed']}, total_closed={result['total_closed']}, pending_open={result['pending_open']}, waiting_entry={result['pending_waiting_for_entry']}, overlap_skipped={result['skipped_overlap']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
