import unittest
from datetime import date,datetime,timedelta,timezone
from experimental_portfolio.engine import UNIVERSE,build_report,MIN_COMMON_BARS

class ExperimentalPortfolioTests(unittest.TestCase):
    def make_history(self,count=260):
        history={}
        base=date(2024,1,1)
        for n,item in enumerate(UNIVERSE[:8]):
            rows=[]
            for i in range(count):
                close=50.0+i*(0.12+n*0.005)
                rows.append({"date":(base+timedelta(days=i)).isoformat(),"open":close,
                  "high":close*1.01,"low":close*0.99,"close":close,"volume":1000})
            history[item["symbol"]]=rows
        return history
    def test_paper_portfolio_report(self):
        report=build_report(self.make_history(),generated_at=datetime(2026,11,27,tzinfo=timezone.utc))
        self.assertIn(report["status"],("READY","DATA_STALE"))
        self.assertEqual(report["portfolio_model"]["initial_nav_index"],100.0)
        self.assertEqual(report["portfolio_model"]["currency"],"NOT_APPLICABLE_INDEX_UNITS")
        self.assertTrue(report["safety"]["paper_only"])
        self.assertFalse(report["safety"]["broker_access"])
        self.assertFalse(report["safety"]["orders_placed"])
        self.assertLessEqual(len(report["holdings"]),4)
        self.assertLessEqual(sum(x["weight"] for x in report["holdings"]),1.000001)
        self.assertIsNotNone(report["performance"]["ending_nav_index"])
    def test_insufficient_data_is_not_fabricated(self):
        report=build_report({},{"SPY.US":"provider_failed"})
        self.assertEqual(report["status"],"INSUFFICIENT_DATA")
        self.assertIsNone(report.get("performance"))
        self.assertFalse(report["safety"]["orders_placed"])
    def test_cost_assumption_is_explicit(self):
        report=build_report(self.make_history())
        self.assertGreater(report["portfolio_model"]["estimated_one_way_transaction_cost"],0)
        self.assertGreaterEqual(MIN_COMMON_BARS,200)

if __name__=="__main__": unittest.main()
