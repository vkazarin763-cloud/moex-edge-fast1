"""Causal, next-open research execution simulator for OHLCV hypotheses.

Signals are observed at a completed bar close and filled at the next bar open.
The simulator is single-position, long/short, and deliberately excludes sizing,
portfolio allocation, broker integration, and strategy approval.
"""
from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Mapping, Sequence
from statistics import median


class ExecutionInputError(ValueError):
    """Raised when execution inputs violate the simulator contract."""


def _validate_inputs(
    bars: Sequence[Mapping[str, Any]],
    feature_panel: Mapping[str, Sequence[float | None]],
    entry_hypothesis: Mapping[str, Any],
    exit_hypothesis: Mapping[str, Any],
    commission_rate: float,
    slippage_rate: float,
) -> int:
    if isinstance(bars, (str, bytes)) or not isinstance(bars, Sequence) or not bars:
        raise ExecutionInputError("bars must be a non-empty sequence")
    previous: datetime | None = None
    for i, bar in enumerate(bars):
        if not isinstance(bar, Mapping):
            raise ExecutionInputError(f"bar {i} must be a mapping")
        timestamp = bar.get("timestamp")
        if not isinstance(timestamp, str):
            raise ExecutionInputError(f"bar {i} timestamp must be ISO-8601")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ExecutionInputError(f"bar {i} has invalid timestamp") from exc
        if previous is not None:
            try:
                if parsed <= previous:
                    raise ExecutionInputError("timestamps must be strictly increasing and unique")
            except TypeError as exc:
                raise ExecutionInputError("timestamps must use a consistent timezone convention") from exc
        previous = parsed
        values = {}
        for field in ("open", "high", "low", "close", "volume"):
            value = bar.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ExecutionInputError(f"bar {i} {field} must be numeric")
            value = float(value)
            if not math.isfinite(value):
                raise ExecutionInputError(f"bar {i} {field} must be finite")
            values[field] = value
        o, h, low, c, volume = (values[k] for k in ("open", "high", "low", "close", "volume"))
        if min(o, h, low, c) <= 0 or volume < 0:
            raise ExecutionInputError(f"bar {i} has non-positive OHLC or negative volume")
        if h < max(o, c, low) or low > min(o, c) or h < low:
            raise ExecutionInputError(f"bar {i} has invalid OHLC relationships")

    if not isinstance(feature_panel, Mapping) or not feature_panel:
        raise ExecutionInputError("feature_panel must be a non-empty mapping")
    for name, values in feature_panel.items():
        if not isinstance(name, str) or not name.strip() or isinstance(values, (str, bytes)):
            raise ExecutionInputError("feature panel must map names to numeric sequences")
        if not isinstance(values, Sequence) or len(values) != len(bars):
            raise ExecutionInputError("each feature series must align one-to-one with bars")
        for value in values:
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ExecutionInputError("feature values must be finite numbers or None")

    for label, hypothesis in (("entry", entry_hypothesis), ("exit", exit_hypothesis)):
        if not isinstance(hypothesis, Mapping) or not isinstance(hypothesis.get("conditions"), list):
            raise ExecutionInputError(f"{label}_hypothesis must contain a conditions list")
        if not hypothesis["conditions"]:
            raise ExecutionInputError(f"{label}_hypothesis conditions must not be empty")
        if hypothesis.get("combination", "ALL") not in ("ALL", "ANY"):
            raise ExecutionInputError(f"{label}_hypothesis combination must be ALL or ANY")
        for condition in hypothesis["conditions"]:
            if not isinstance(condition, Mapping):
                raise ExecutionInputError("hypothesis conditions must be mappings")
            feature, operator, threshold = (
                condition.get("feature"), condition.get("operator"), condition.get("threshold")
            )
            if feature not in feature_panel or operator not in (">=", "<="):
                raise ExecutionInputError("hypothesis references unknown feature or operator")
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(float(threshold)):
                raise ExecutionInputError("hypothesis threshold must be finite numeric")
    direction = entry_hypothesis.get("direction")
    if direction not in ("LONG", "SHORT"):
        raise ExecutionInputError("entry hypothesis direction must be LONG or SHORT")
    for label, value in (("commission_rate", commission_rate), ("slippage_rate", slippage_rate)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
            raise ExecutionInputError(f"{label} must be a finite non-negative decimal rate")
    if slippage_rate >= 1:
        raise ExecutionInputError("slippage_rate must be below 1")
    return len(bars)


def _matches(rule: Mapping[str, Any], panel: Mapping[str, Sequence[float | None]], index: int) -> bool:
    outcomes = []
    for condition in rule["conditions"]:
        value = panel[condition["feature"]][index]
        if value is None:
            outcomes.append(False)
            continue
        threshold = float(condition["threshold"])
        if condition["operator"] == ">=":
            outcomes.append(float(value) >= threshold)
        else:
            outcomes.append(float(value) <= threshold)
    if rule.get("combination", "ALL") == "ANY":
        return any(outcomes)
    return all(outcomes)


def evaluate_hypothesis(
    bars: Sequence[Mapping[str, Any]],
    feature_panel: Mapping[str, Sequence[float | None]],
    entry_hypothesis: Mapping[str, Any],
    exit_hypothesis: Mapping[str, Any],
    *,
    commission_rate: float = 0.0008,
    slippage_rate: float = 0.0005,
) -> dict[str, Any]:
    """Evaluate one entry rule and an independent exit rule.

    A signal on bar t is filled at bar t+1 open. Slippage is applied adversely
    to each fill. Commission is charged on entry and exit notionals. No forced
    end-of-data liquidation occurs: an unfinished position is reported
    separately and excluded from closed-trade performance statistics.
    """
    n = _validate_inputs(
        bars, feature_panel, entry_hypothesis, exit_hypothesis,
        commission_rate, slippage_rate,
    )
    direction = entry_hypothesis["direction"]
    side = 1.0 if direction == "LONG" else -1.0
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None

    for signal_index in range(n - 1):
        if position is None:
            if _matches(entry_hypothesis, feature_panel, signal_index):
                raw_open = float(bars[signal_index + 1]["open"])
                fill = raw_open * (1.0 + slippage_rate * side)
                position = {
                    "direction": direction,
                    "signal_timestamp": bars[signal_index]["timestamp"],
                    "entry_timestamp": bars[signal_index + 1]["timestamp"],
                    "entry_signal_index": signal_index,
                    "entry_price": fill,
                    "raw_entry_open": raw_open,
                }
            continue

        if _matches(exit_hypothesis, feature_panel, signal_index):
            raw_open = float(bars[signal_index + 1]["open"])
            exit_fill = raw_open * (1.0 - slippage_rate * side)
            entry_price = position["entry_price"]
            gross_return = side * (exit_fill / entry_price - 1.0)
            commission = commission_rate * (1.0 + exit_fill / entry_price)
            net_return = gross_return - commission
            trades.append({
                **position,
                "exit_signal_timestamp": bars[signal_index]["timestamp"],
                "exit_timestamp": bars[signal_index + 1]["timestamp"],
                "exit_price": exit_fill,
                "raw_exit_open": raw_open,
                "gross_return": gross_return,
                "commission_return": commission,
                "net_return": net_return,
                "bars_held": signal_index + 1 - position["entry_signal_index"],
            })
            position = None

    returns = [trade["net_return"] for trade in trades]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    result = {
        "status": "EVALUATED",
        "direction": direction,
        "execution": {
            "signal_timing": "completed_bar_close",
            "fill_timing": "next_bar_open",
            "slippage_rate_per_side": float(slippage_rate),
            "commission_rate_per_side": float(commission_rate),
            "end_of_data_policy": "leave_open_and_exclude_from_closed_trade_metrics",
            "position_policy": "one_position_at_a_time_no_pyramiding",
        },
        "counts": {
            "entry_signals_filled": len(trades) + (1 if position is not None else 0),
            "exit_signals_filled": len(trades),
            "closed_trades": len(trades),
            "unfilled_final_bar_signals": int(_matches(entry_hypothesis, feature_panel, n - 1) and position is None),
        },
        "metrics": {
            "win_rate": len(wins) / len(trades) if trades else None,
            "mean_net_return": sum(returns) / len(returns) if returns else None,
            "median_net_return": median(returns) if returns else None,
            "profit_factor": profit_factor,
            "total_net_return_sum": sum(returns) if returns else None,
            "gross_profit_sum": gross_profit if trades else None,
            "gross_loss_sum": gross_loss if trades else None,
        },
        "trades": trades,
        "open_position": position,
        "safety": {
            "lookahead_used": False,
            "future_returns_used_for_rule_selection": False,
            "unclosed_trade_included_in_metrics": False,
            "portfolio_or_capital_sizing_used": False,
            "approval_status": "NOT_APPROVED",
            "requires_multiple_testing_correction_and_unseen_validation": True,
        },
    }
    return result
