import unittest
import numpy as np
import pandas as pd
from optimizer import validate_candles, parameter_grid, candidate_signals, simulate_signals, metrics, walk_forward_metrics

# Regression suite for no-lookahead boundaries and next-bar execution. Direct-route and CA-bundle regression smoke requested.
class OptimizerTests(unittest.TestCase):
    def bars(self, n=400):
        x=np.arange(n,dtype=float)
        close=100+0.03*x+2*np.sin(x/8)
        return pd.DataFrame({"begin":pd.date_range("2025-01-02 09:00",periods=n,freq="10min"),
          "open":close-0.1,"high":close+0.5,"low":close-0.5,"close":close,"volume":np.full(n,1000.0)})

    def test_grid_contains_baselines(self):
        g=parameter_grid()
        self.assertIn({"fast":20,"slow":50},g["EMA"])
        self.assertIn({"period":14,"lower":30,"upper":70},g["RSI"])
        self.assertIn({"fast":12,"slow":26,"signal":9},g["MACD"])
        self.assertIn({"period":20,"stdev":2.0},g["BOLLINGER"])

    def test_validation_removes_bad_and_duplicate_rows(self):
        df=self.bars(10)
        df=pd.concat([df,df.iloc[[0]]],ignore_index=True)
        df.loc[1,"high"]=1
        clean,stats=validate_candles(df,10,now=pd.Timestamp("2025-01-03 00:00",tz="Europe/Moscow").to_pydatetime())
        self.assertEqual(stats["duplicates"],1)
        self.assertEqual(stats["invalid_ohlc"],1)
        self.assertEqual(len(clean),9)


    def test_weekend_bars_are_counted_and_excluded(self):
        friday=self.bars(10)
        saturday=friday.copy()
        saturday["begin"]=saturday["begin"]+pd.Timedelta(days=2)
        raw=pd.concat([friday,saturday],ignore_index=True)
        clean,stats=validate_candles(raw,10,now=pd.Timestamp("2025-01-06 00:00",tz="Europe/Moscow").to_pydatetime())
        self.assertEqual(stats["weekend_rows"],10)
        self.assertEqual(len(clean),10)

    def test_signal_arrays_match_input(self):
        df=self.bars()
        for family,params in ((k,v[0]) for k,v in parameter_grid().items()):
            long_sig,short_sig=candidate_signals(df,family,params)
            self.assertEqual(len(long_sig),len(df))
            self.assertEqual(len(short_sig),len(df))

    def test_entry_is_next_bar_open_and_costs_are_subtracted(self):
        df=pd.DataFrame({"begin":pd.date_range("2025-01-02 09:00",periods=6,freq="10min"),
          "open":[100,101,102,103,104,105],"high":[101]*6,"low":[99]*6,"close":[100,101,102,103,104,105]})
        sig=pd.Series([True,False,False,False,False,False])
        trades=simulate_signals(df,sig,~sig,1,2,0.01,0.02)
        self.assertEqual(len(trades),1)
        self.assertEqual(trades[0]["entry_time"],str(df.begin.iloc[1]))
        self.assertAlmostEqual(trades[0]["gross_return"],(102-101)/101)
        self.assertAlmostEqual(trades[0]["net_return"],(102-101)/101-0.03)


    def test_walk_forward_does_not_touch_validation_or_test(self):
        df=self.bars(100)
        trades=[
          {"signal_time":str(df.begin.iloc[25]),"exit_time":str(df.begin.iloc[26]),"net_return":0.02,"gross_return":0.03},
          {"signal_time":str(df.begin.iloc[65]),"exit_time":str(df.begin.iloc[66]),"net_return":0.02,"gross_return":0.03},
          {"signal_time":str(df.begin.iloc[85]),"exit_time":str(df.begin.iloc[86]),"net_return":0.02,"gross_return":0.03},
        ]
        folds=walk_forward_metrics(df,trades)
        self.assertEqual(len(folds),4)
        self.assertEqual(sum(x["trades"] for x in folds),1)

    def test_metrics_empty_and_positive(self):
        self.assertEqual(metrics([])["trades"],0)
        m=metrics([{"net_return":0.1},{"net_return":-0.05}])
        self.assertEqual(m["trades"],2)
        self.assertAlmostEqual(m["profit_factor"],2.0)

if __name__=="__main__":
    unittest.main()
