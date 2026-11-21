import unittest
from datetime import datetime, timedelta, timezone

from research_agent.core import Candle, generate_signals
from research_agent.mtf_scanner import (
    _d1_signals_at_last_bar, _h1_alignment, _parse_candles,
    scan_multi_timeframe_report,
)


class MTFScannerTests(unittest.TestCase):
    def _trend(self, count, start, step, aware=True):
        rows = []
        for i in range(count):
            close = start + step * i
            stamp = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
            rows.append(Candle(stamp, close, close + 1, close - 1, close, 1000))
        return rows

    def test_h1_alignment_long_and_short(self):
        rising = self._trend(80, 100, 1)
        falling = self._trend(80, 180, -1)
        self.assertEqual(_h1_alignment(rising, 1)["status"], "CONFIRMED")
        self.assertEqual(_h1_alignment(falling, -1)["status"], "CONFIRMED")
        self.assertEqual(_h1_alignment(rising, -1)["status"], "NOT_CONFIRMED")

    def test_h1_insufficient_history_is_explicit(self):
        result = _h1_alignment(self._trend(49, 100, 1), 1)
        self.assertEqual(result["status"], "INSUFFICIENT_HISTORY")

    def test_latest_d1_signal_uses_last_bar_and_fixed_donchian_formula(self):
        rows = self._trend(60, 100, 1)
        # Force the final close above the preceding 20-bar high.
        last = rows[-1]
        rows[-1] = Candle(last.timestamp, 180, 190, 179, 189, 1000)
        found = _d1_signals_at_last_bar(rows)
        donchian = next(x for x in found if x["strategy"] == "Donchian20" and x["direction"] == "LONG")
        self.assertGreater(donchian["parameters"]["close"], donchian["parameters"]["donchian20_prior_high"])
        self.assertIn("ema20", donchian["parameters"])
        self.assertIn("rsi14", donchian["parameters"])
        self.assertIn("macd12_26", donchian["parameters"])
        self.assertIn("atr14", donchian["parameters"])
        self.assertIn("keltner20_upper_2atr", donchian["parameters"])

    def test_latest_bar_formulas_match_frozen_core_generator(self):
        rows = self._trend(62, 100, 1)
        last = rows[60]
        rows[60] = Candle(last.timestamp, 180, 190, 179, 189, 1000)
        expected = [
            (signal.strategy, "LONG" if signal.direction > 0 else "SHORT")
            for signal in generate_signals(rows)
            if signal.index == 60
        ]
        actual = [
            (signal["strategy"], signal["direction"])
            for signal in _d1_signals_at_last_bar(rows[:61])
        ]
        self.assertEqual(actual, expected)

    def test_h1_confirmation_never_uses_bar_after_d1_close(self):
        from research_agent.mtf_scanner import scan_multi_timeframe_report

        d1 = []
        for i in range(60):
            close = 100 + i
            d1.append({
                "timestamp": (datetime(2026, 1, 1) + timedelta(days=i)).isoformat(),
                "open": close, "high": close + 1, "low": close - 1,
                "close": close, "volume": 1000,
            })
        # Force a latest-bar Donchian breakout.
        d1[-1].update({"open": 200, "high": 205, "low": 199, "close": 204})

        h1 = []
        start = datetime(2026, 2, 27, 18, 0, tzinfo=timezone.utc)
        for i in range(51):
            close = 100 + i
            stamp = start + timedelta(hours=i)
            h1.append({
                "timestamp": stamp.isoformat(), "open": close,
                "high": close + 1, "low": close - 1, "close": close,
                "volume": 1000, "is_data_snapshot": False,
            })
        # This later H1 bar is after the D1 bar's close and must be ignored.
        later = start + timedelta(hours=51)
        h1.append({
            "timestamp": later.isoformat(), "open": 999, "high": 1000,
            "low": 998, "close": 999, "volume": 1000,
            "is_data_snapshot": False,
        })
        snapshot = "2026-03-02T00:00:00+00:00"
        candles_report = {
            "generated_at_utc": snapshot,
            "universe": ["TEST"],
            "results": {"TEST": {
                "D1": {"source": "MOEX ISS TQBR history", "status": "OK", "candles": d1},
                "H1": {"source": "Finam", "status": "OK", "candles": h1},
            }},
        }
        validation = {
            "generated_at_utc": snapshot, "as_of_utc": snapshot,
            "status": "PASS", "issue_count": 0,
        }
        result = scan_multi_timeframe_report(candles_report, validation)
        self.assertTrue(result["signals"])
        registry = {
            "registry_version": "test-v1",
            "generated_at_utc": snapshot,
            "stage": "DEVELOPMENT_ONLY_NOT_PRODUCTION_APPROVAL",
            "holdout_used_for_selection": False,
            "scanner_contract": {
                "consume_only_status": "PASS",
                "live_trading_authorized": False,
            },
            "strategies": [],
        }
        gated = scan_multi_timeframe_report(candles_report, validation, registry)
        self.assertEqual(gated["signals_count"], 0)
        self.assertGreater(gated["registry_filtered_candidates"], 0)
        self.assertEqual(gated["strategy_registry_version"], "test-v1")
        self.assertIn("parameters", result["signals"][0])
        self.assertGreater(
            result["signals"][0]["parameters"]["close"],
            result["signals"][0]["parameters"]["donchian20_prior_high"],
        )
        self.assertIn("ema20", result["signals"][0]["parameters"])
        self.assertIn("rsi14", result["signals"][0]["parameters"])
        self.assertIn("macd12_26", result["signals"][0]["parameters"])
        self.assertIn("atr14", result["signals"][0]["parameters"])
        self.assertIn("keltner20_upper_2atr", result["signals"][0]["parameters"])
        self.assertEqual(result["signals"][0]["h1"]["h1_timestamp"], "2026-03-01T20:00:00+00:00")
        self.assertEqual(result["signals"][0]["h1"]["h1_age_minutes_at_d1_close"], 0)
        forbidden_fields = {
            "qty", "quantity", "entry_price", "position_size",
            "capital", "allocation", "portfolio_weight",
        }
        for signal in result["signals"]:
            self.assertFalse(forbidden_fields.intersection(signal))

    def test_scanner_rejects_failed_validation(self):
        with self.assertRaises(ValueError):
            scan_multi_timeframe_report({}, {"status": "FAIL", "issue_count": 1})

    def test_scanner_rejects_mismatched_snapshot(self):
        with self.assertRaises(ValueError):
            scan_multi_timeframe_report(
                {"generated_at_utc": "2026-01-01T00:00:00+00:00", "universe": [], "results": {}},
                {"status": "PASS", "issue_count": 0, "generated_at_utc": "2026-01-02T00:00:00+00:00",
                 "as_of_utc": "2026-01-02T00:00:00+00:00"},
            )

    def test_d1_naive_timestamp_is_interpreted_as_moscow(self):
        parsed = _parse_candles(
            [{"timestamp": "2026-01-01T00:00:00", "open": 10, "high": 11, "low": 9,
              "close": 10, "volume": 100}],
            source="MOEX ISS TQBR history",
        )
        self.assertEqual(parsed[0].timestamp.utcoffset(), timedelta(hours=3))

    def test_h1_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            _parse_candles(
                [{"timestamp": "2026-01-01T00:00:00", "open": 10, "high": 11, "low": 9,
                  "close": 10, "volume": 100}],
                source="Finam",
            )


if __name__ == "__main__":
    unittest.main()
