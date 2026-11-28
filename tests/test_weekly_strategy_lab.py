import unittest
from datetime import date, timedelta
from experimental_portfolio.weekly_strategy_lab import (
    STRATEGIES, validate_bars, signal_series, backtest, compare, walk_forward_compare,
)

def make_bars(closes):
    return [{"date":(date(2020,1,1)+timedelta(days=7*i)).isoformat(),"open":v,"high":v*1.01,"low":v*.99,"close":v} for i,v in enumerate(closes)]

class WeeklyStrategyLabTests(unittest.TestCase):
    def test_bad_duplicate_rows_filtered(self):
        rows=make_bars([10,11,12]); rows.append(rows[1]); rows.append({"date":"x","open":1,"high":0,"low":1,"close":1})
        self.assertEqual(len(validate_bars(rows)),3)
    def test_momentum_signal(self):
        bars=make_bars(list(range(10,40))); sig=signal_series(bars,"momentum_13w")
        self.assertEqual(sig[12],0); self.assertEqual(sig[13],1)
        self.assertEqual(backtest(bars,"momentum_13w")["status"],"OK")
    def test_parameter_grid_families(self):
        self.assertIn("sma_trend_10w",STRATEGIES)
        self.assertIn("momentum_52w",STRATEGIES)
        self.assertIn("breakout_26w",STRATEGIES)
        self.assertEqual(len(STRATEGIES),13)
    def test_costs_penalize(self):
        bars=make_bars([10,11,12,11,10,12,13,12,14,13,15,14,16,15,17,18,19,20,21,22,23])
        self.assertLessEqual(backtest(bars,"sma_trend",0.01)["total_return"],backtest(bars,"sma_trend",0)["total_return"])
    def test_unknown_strategy(self):
        with self.assertRaises(ValueError): backtest(make_bars([1,2]),"magic")
    def test_matrix_size(self): self.assertEqual(len(compare(make_bars(list(range(10,80)))),39)
    def test_evaluation_window_keeps_indicator_warmup(self):
        bars=make_bars(list(range(10,100)))
        result=backtest(bars,"momentum_13w",evaluation_start=bars[-30]["date"])
        self.assertEqual(result["status"],"OK")
        self.assertEqual(result["period"]["from"],bars[-30]["date"])
        self.assertGreater(result["bars"],result["evaluation_bars"])
    def test_evaluation_end_is_exclusive(self):
        bars=make_bars(list(range(10,100)))
        result=backtest(bars,"buy_hold",evaluation_start=bars[40]["date"],evaluation_end=bars[50]["date"])
        self.assertEqual(result["period"]["to"],bars[49]["date"])
    def test_walk_forward_uses_sequential_holdouts(self):
        bars=make_bars(list(range(10,10+260)))
        results=walk_forward_compare(bars,costs=(0.001,),warmup_bars=104,fold_bars=52)
        self.assertEqual({r["fold"] for r in results},{1,2,3})
        self.assertTrue(all(r["validation"]=="sequential_fixed_rule_holdout" for r in results))
        self.assertTrue(all(r["evaluation_bars"]<=52 for r in results if r["status"]=="OK"))
    def test_sharpe_suppressed_for_low_volatility(self):
        bars=make_bars([100+i*0.01 for i in range(100)])
        result=backtest(bars,"buy_hold")
        self.assertIsNone(result["sharpe_rf0"])
        self.assertEqual(result["sharpe_status"],"LOW_VOLATILITY_UNRELIABLE")
if __name__=="__main__": unittest.main()
