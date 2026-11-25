#!/usr/bin/env python3
"""Apply direction-aware probabilities to live and historical paper pipelines."""
from pathlib import Path

# Live pipeline: class 1 is a positive future return; SHORT uses its complement.
engine_path = Path("vendor/moex-agent/moex_agent/engine.py")
engine = engine_path.read_text(encoding="utf-8")
old_engine = '''            # Find best horizon
            best_h, best_p = self.models.best_horizon(X)
            if best_h is None:
                continue
'''
new_engine = '''            # Models estimate P(future return > 0). Invert it for SHORT.
            predictions = self.models.predict_all(X)
            if not predictions:
                continue
            if anomaly.direction == Direction.LONG:
                best_h = max(predictions, key=predictions.get)
                best_p = predictions[best_h]
            else:
                best_h = min(predictions, key=predictions.get)
                best_p = 1.0 - predictions[best_h]
'''
if old_engine not in engine:
    raise SystemExit("Expected live prediction block not found; refusing patch")
engine_path.write_text(engine.replace(old_engine, new_engine, 1), encoding="utf-8")

# Historical backtest must use the same directional probability calculation.
backtest_path = Path("vendor/moex-agent/moex_agent/backtest.py")
backtest = backtest_path.read_text(encoding="utf-8")
old_backtest = '''                # Find best horizon
                best_h, best_p = self.models.best_horizon(X)
                if best_h is None:
                    continue
'''
new_backtest = '''                # Match live logic: P(up) for LONG, 1-P(up) for SHORT.
                predictions = self.models.predict_all(X)
                if not predictions:
                    continue
                if anomaly.direction == Direction.LONG:
                    best_h = max(predictions, key=predictions.get)
                    best_p = predictions[best_h]
                else:
                    best_h = min(predictions, key=predictions.get)
                    best_p = 1.0 - predictions[best_h]
'''
if old_backtest not in backtest:
    raise SystemExit("Expected backtest prediction block not found; refusing patch")

# If one OHLC candle touches both take and stop, conservatively assume stop first.
old_exits = '''        # Check take profit
        if pos.take is not None:
            if pos.direction == Direction.LONG and high >= pos.take:
                self._close_position(ticker, pos.take, timestamp, "take")
                return
            elif pos.direction == Direction.SHORT and low <= pos.take:
                self._close_position(ticker, pos.take, timestamp, "take")
                return

        # Check stop loss
        if pos.stop is not None:
            if pos.direction == Direction.LONG and low <= pos.stop:
                self._close_position(ticker, pos.stop, timestamp, "stop")
                return
            elif pos.direction == Direction.SHORT and high >= pos.stop:
                self._close_position(ticker, pos.stop, timestamp, "stop")
                return
'''
new_exits = '''        # Check stop first: if both levels are touched in one candle, avoid
        # optimistic assumptions and record the stop-loss outcome.
        if pos.stop is not None:
            if pos.direction == Direction.LONG and low <= pos.stop:
                self._close_position(ticker, pos.stop, timestamp, "stop")
                return
            elif pos.direction == Direction.SHORT and high >= pos.stop:
                self._close_position(ticker, pos.stop, timestamp, "stop")
                return

        # Check take profit only when the stop was not touched.
        if pos.take is not None:
            if pos.direction == Direction.LONG and high >= pos.take:
                self._close_position(ticker, pos.take, timestamp, "take")
                return
            elif pos.direction == Direction.SHORT and low <= pos.take:
                self._close_position(ticker, pos.take, timestamp, "take")
                return
'''
if old_exits not in backtest:
    raise SystemExit("Expected backtest exit block not found; refusing patch")
backtest = backtest.replace(old_backtest, new_backtest, 1)
backtest = backtest.replace(old_exits, new_exits, 1)
backtest_path.write_text(backtest, encoding="utf-8")
print("Direction-aware LONG/SHORT patch applied to live and backtest pipelines.")
print("Conservative same-candle stop/target handling applied to backtest.")
