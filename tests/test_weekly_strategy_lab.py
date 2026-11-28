import unittest
from experimental_portfolio.weekly_strategy_lab import validate_bars, signal_series, backtest, compare

def make_bars(closes):
    return [{"date":f"2020-{i+1:02d}-01","open":v,"high":v*1.01,"low":v*.99,"close":v} for i,v in enumerate(closes)]

class WeeklyStrategyLabTests(unittest.TestCase):
    def test_bad_duplicate_rows_filtered(self):
        rows=make_bars([10,11,12]); rows.append(rows[1]); rows.append({"date":"x","open":1,"high":0,"low":1,"close":1})
        self.assertEqual(len(validate_bars(rows)),3)
    def test_momentum_signal(self):
        bars=make_bars(list(range(10,40))); sig=signal_series(bars,"momentum_13w")
        self.assertEqual(sig[12],0); self.assertEqual(sig[13],1)
        self.assertEqual(backtest(bars,"momentum_13w")["status"],"OK")
    def test_costs_penalize(self):
        bars=make_bars([10,11,12,11,10,12,13,12,14,13,15,14,16,15,17,18,19,20,21,22,23])
        self.assertLessEqual(backtest(bars,"sma_trend",0.01)["total_return"],backtest(bars,"sma_trend",0)["total_return"])
    def test_unknown_strategy(self):
        with self.assertRaises(ValueError): backtest(make_bars([1,2]),"magic")
    def test_matrix_size(self): self.assertEqual(len(compare(make_bars(list(range(10,40))))),15)
if __name__=="__main__": unittest.main()
