import unittest
from datetime import datetime, timezone
from research_agent.core import Candle
from research_agent.finam_market_data import FinamBar
from research_agent.finam_h1_crosscheck import compare_h1_series

class FinamH1CrosscheckTests(unittest.TestCase):
    def test_aligns_moex_local_and_finam_utc_timestamps(self):
        now=datetime(2026,11,18,13,30,tzinfo=timezone.utc)
        moex=[Candle(datetime(2026,11,18,14),100,105,99,104,1000)]
        finam=[FinamBar(datetime(2026,11,18,11,tzinfo=timezone.utc),100,105,99,104,1000,False)]
        result=compare_h1_series(moex,finam,now=now)
        self.assertEqual(result["matched_bars"],1)
        self.assertEqual(result["status"],"DATE_COVERAGE_MATCHES")

    def test_excludes_open_and_snapshot_bars(self):
        now=datetime(2026,11,18,13,30,tzinfo=timezone.utc)
        moex=[Candle(datetime(2026,11,18,14),100,105,99,104,1000),
              Candle(datetime(2026,11,18,15),100,105,99,104,1000)]
        finam=[FinamBar(datetime(2026,11,18,11,tzinfo=timezone.utc),100,105,99,104,1000,True),
               FinamBar(datetime(2026,11,18,12,tzinfo=timezone.utc),100,105,99,104,1000,False)]
        result=compare_h1_series(moex,finam,now=now)
        self.assertEqual(result["moex_closed_bars"],1)
        self.assertEqual(result["finam_closed_bars"],0)
        self.assertEqual(result["matched_bars"],0)

    def test_unknown_snapshot_flag_is_retained(self):
        now=datetime(2026,11,18,13,30,tzinfo=timezone.utc)
        moex=[Candle(datetime(2026,11,18,14),100,105,99,104,1000)]
        finam=[FinamBar(datetime(2026,11,18,11,tzinfo=timezone.utc),100,105,99,104,1000,None)]
        result=compare_h1_series(moex,finam,now=now)
        self.assertIsNone(result["comparisons"][0]["finam_is_data_snapshot"])

if __name__=="__main__": unittest.main()
