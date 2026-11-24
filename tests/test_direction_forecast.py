import unittest
from datetime import date, datetime, timedelta

from research_agent.core import Candle
from research_agent.direction_forecast import (
    CLASS_NAMES, FEATURE_NAMES, HOLDOUT_START, _fit_gaussian_nb,
    _predict_proba, build_samples, evaluate_horizon,
)


def _candles(count=100, start=date(2026, 8, 1)):
    rows = []
    price = 100.0
    for index in range(count):
        price *= 1.0 + (0.003 if index % 5 in (0, 1, 2) else -0.002)
        stamp = datetime.combine(start + timedelta(days=index), datetime.min.time())
        open_price = price * (0.999 if index % 2 else 1.001)
        rows.append(Candle(
            stamp, open_price, max(open_price, price) * 1.01,
            min(open_price, price) * 0.99, price, 1000.0 + (index % 11) * 50,
        ))
    return rows


class DirectionForecastTests(unittest.TestCase):
    def test_sample_labels_never_use_holdout_target_dates(self):
        samples = build_samples("SBER", _candles(120), 5)
        self.assertTrue(samples)
        self.assertTrue(all(sample["target_date"] < HOLDOUT_START for sample in samples))
        self.assertTrue(all(sample["date"] < HOLDOUT_START for sample in samples))
        self.assertTrue(all(len(sample["features"]) == len(FEATURE_NAMES) for sample in samples))

    def test_gaussian_nb_returns_normalized_three_class_probabilities(self):
        samples = []
        for index in range(180):
            features = [
                ((index * (feature + 3)) % 17 - 8) / 10.0
                for feature in range(len(FEATURE_NAMES))
            ]
            samples.append({
                "features": features,
                "label": index % 3,
            })
        model = _fit_gaussian_nb(samples)
        probabilities = _predict_proba(model, samples[-1]["features"])
        self.assertEqual(len(probabilities), len(CLASS_NAMES))
        self.assertAlmostEqual(sum(probabilities), 1.0, places=10)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in probabilities))

    def test_walk_forward_uses_label_maturity_embargo(self):
        samples = []
        start = date(2024, 1, 1)
        for day in range(120):
            for ticker_index in range(2):
                features = [
                    ((day + ticker_index * 3 + feature) % 13 - 6) / 10.0
                    for feature in range(len(FEATURE_NAMES))
                ]
                samples.append({
                    "ticker": f"T{ticker_index}",
                    "date": start + timedelta(days=day),
                    "target_date": start + timedelta(days=day + 5),
                    "features": features,
                    "label": (day + ticker_index) % 3,
                    "neutral_threshold": 0.003,
                })
        report = evaluate_horizon(samples, folds=4, initial_train_fraction=0.5)
        self.assertEqual(report["status"], "OUT_OF_SAMPLE_EVALUATED")
        self.assertEqual(report["folds_evaluated"], 4)
        for fold in report["fold_reports"]:
            self.assertLess(
                date.fromisoformat(fold["train_max_label_maturity_date"]),
                date.fromisoformat(fold["test_start"]),
            )
            self.assertEqual(fold["status"], "EVALUATED")
            self.assertGreaterEqual(fold["metrics"]["test_samples"], 20)
        self.assertGreater(report["oos_samples"], 0)
        self.assertIn("log_loss", report["pooled_oos_metrics"])
        self.assertIn("historical_momentum_baseline_accuracy", report["pooled_oos_metrics"])


if __name__ == "__main__":
    unittest.main()
