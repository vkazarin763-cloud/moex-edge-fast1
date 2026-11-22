import unittest
from research_agent.v2.multiple_testing import MultipleTestingInputError, holm_bonferroni

class HolmCorrectionTests(unittest.TestCase):
    def test_step_down_values_and_decisions(self):
        result = holm_bonferroni({"h3": 0.04, "h1": 0.01, "h2": 0.03}, alpha=0.05, family_id="f1")
        rows = {r["hypothesis_id"]: r for r in result["results"]}
        self.assertAlmostEqual(rows["h1"]["holm_adjusted_p_value"], 0.03)
        self.assertAlmostEqual(rows["h2"]["holm_adjusted_p_value"], 0.06)
        self.assertAlmostEqual(rows["h3"]["holm_adjusted_p_value"], 0.06)
        self.assertTrue(rows["h1"]["reject_null"])
        self.assertFalse(rows["h2"]["reject_null"])
        self.assertFalse(rows["h3"]["reject_null"])

    def test_adjusted_values_monotone_by_rank(self):
        result = holm_bonferroni({"a": 0.001, "b": 0.002, "c": 0.2, "d": 0.8}, family_id="f2")
        ranked = sorted(result["results"], key=lambda r: r["raw_p_value"])
        values = [r["holm_adjusted_p_value"] for r in ranked]
        self.assertEqual(values, sorted(values))

    def test_preserves_input_order_and_single_test(self):
        result = holm_bonferroni({"z": 0.2, "a": 0.04}, family_id="f3")
        self.assertEqual([r["hypothesis_id"] for r in result["results"]], ["z", "a"])
        one = holm_bonferroni({"only": 0.04}, family_id="f4")
        self.assertAlmostEqual(one["results"][0]["holm_adjusted_p_value"], 0.04)

    def test_invalid_values_rejected(self):
        for values in ({}, {"x": float("nan")}, {"x": float("inf")}, {"x": -0.1}, {"x": 1.1}, {"x": True}):
            with self.subTest(values=values):
                with self.assertRaises(MultipleTestingInputError):
                    holm_bonferroni(values, family_id="bad")
        with self.assertRaises(MultipleTestingInputError):
            holm_bonferroni({"x": 0.1}, alpha=1.0, family_id="bad")

    def test_family_id_required(self):
        with self.assertRaises(MultipleTestingInputError):
            holm_bonferroni({"x": 0.1}, family_id=" ")

if __name__ == "__main__":
    unittest.main()
