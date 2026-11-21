"""Deterministic tests for independent frozen entry-formula replay."""
import math
import unittest
from datetime import datetime, timedelta

from research_agent.core import Candle, generate_signals
from research_agent.reference_signals import audit_signal_generation, reference_generate_signals


def _fixture(count=360):
    rows = []
    start = datetime(2024, 1, 1)
    for i in range(count):
        # Deterministic trend + two frequencies produces crossings and breakouts.
        close = 100.0 + 0.035 * i + 2.8 * math.sin(i / 8.0) + 1.1 * math.sin(i / 2.7)
        spread = 0.35 + 0.08 * (i % 5)
        rows.append(Candle(
            start + timedelta(days=i), close, close + spread,
            close - spread, close, 1000.0 + (i % 17) * 13.0,
        ))
    return rows


class IndependentSignalReplayTests(unittest.TestCase):
    def test_reference_events_match_primary_generator(self):
        candles = _fixture()
        primary = generate_signals(candles)
        audit = audit_signal_generation(candles, primary)
        self.assertEqual(audit["status"], "REFERENCE_SIGNAL_MATCH", audit["mismatches"])
        self.assertEqual(audit["mismatch_count"], 0)
        self.assertEqual(audit["primary_signal_count"], len(reference_generate_signals(candles)))

    def test_deliberately_altered_signal_is_detected(self):
        candles = _fixture()
        signals = generate_signals(candles)
        self.assertTrue(signals)
        signals[0] = type(signals[0])(
            signals[0].index, -signals[0].direction, signals[0].strategy
        )
        audit = audit_signal_generation(candles, signals)
        self.assertEqual(audit["status"], "REFERENCE_SIGNAL_MISMATCH")
        self.assertGreater(audit["mismatch_count"], 0)

    def test_future_bar_mutation_does_not_change_prior_reference_events(self):
        original = _fixture()
        cutoff = 240
        changed = list(original)
        last = changed[-1]
        changed[-1] = Candle(
            last.timestamp, last.open * 1.7, last.high * 1.7,
            last.low * 1.7, last.close * 1.7, last.volume,
        )
        left = [e for e in reference_generate_signals(original) if e["index"] < cutoff]
        right = [e for e in reference_generate_signals(changed) if e["index"] < cutoff]
        self.assertEqual(left, right)

    def test_warmup_and_last_bar_entry_guard(self):
        short = _fixture(56)
        self.assertEqual(reference_generate_signals(short), [])
        longer = _fixture(57)
        events = reference_generate_signals(longer)
        self.assertTrue(all(55 <= e["index"] < len(longer) - 1 for e in events))


if __name__ == "__main__":
    unittest.main()
