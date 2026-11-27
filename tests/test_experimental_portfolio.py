import os
import unittest
from datetime import date,datetime,timedelta,timezone
from unittest.mock import patch

from experimental_portfolio.engine import UNIVERSE,build_report,MIN_COMMON_BARS,parse_yahoo_payload
from experimental_portfolio.agents import run_reviewers
from experimental_portfolio.paper import update_paper_ledger
from experimental_portfolio.eligibility import load_finam_allowlist

class ExperimentalPortfolioTests(unittest.TestCase):
    def make_history(self,count=260):
        history={}
        base=date(2024,1,1)
        for n,item in enumerate(UNIVERSE[:8]):
            rows=[]
            for i in range(count):
                close=50.0+i*(0.12+n*0.005)
                rows.append({"date":(base+timedelta(days=i)).isoformat(),"open":close,
                  "high":close*1.01,"low":close*0.99,"close":close,"volume":1000,
                  "raw_close":close,"adjusted_close":close,"source":"synthetic"})
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

    def test_yahoo_adjusted_close_is_used_for_return_series(self):
        stamp=int(datetime(2025,1,2,tzinfo=timezone.utc).timestamp())
        payload={"chart":{"result":[{"timestamp":[stamp],"indicators":{
          "quote":[{"open":[100],"high":[102],"low":[99],"close":[101],"volume":[1234]}],
          "adjclose":[{"adjclose":[98.5]}]}}],"error":None}}
        rows=parse_yahoo_payload(payload,"SPY.US",date(2025,1,1),date(2025,1,3))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["raw_close"],101.0)
        self.assertEqual(rows[0]["close"],98.5)
        self.assertTrue(rows[0]["dividend_adjusted"])

    def test_local_reviewer_fallback_runs_without_api_keys(self):
        with patch.dict(os.environ,{},clear=True):
            result=run_reviewers({"status":"INSUFFICIENT_DATA","data_errors":{"SPY.US":"unavailable"}})
        self.assertEqual(result["status"],"LOCAL_DETERMINISTIC_ONLY")
        self.assertEqual(result["agents_completed"],3)
        self.assertEqual(result["llm_agents_completed"],0)
        self.assertTrue(all(x["engine"]=="local_deterministic" for x in result["reviews"].values()))

    def test_local_reviewer_handles_insufficient_historical_report(self):
        with patch.dict(os.environ,{},clear=True):
            result=run_reviewers({"status":"INSUFFICIENT_DATA","historical_backtest":{"period":None,"performance":None},"paper_portfolio":{"status":"WAITING_FOR_FINAM_ACCOUNT_ALLOWLIST","nav_index":100.0},"holdings":[]})
        self.assertEqual(result["agents_completed"],3)
        self.assertEqual(result["local_agents_completed"],3)
        self.assertTrue(all(x["engine"]=="local_deterministic" for x in result["reviews"].values()))

    def test_forward_ledger_initializes_without_historical_trades(self):
        ledger=update_paper_ledger(self.make_history(),None,datetime(2026,11,27,tzinfo=timezone.utc))
        self.assertEqual(ledger["status"],"INITIALIZED_WAITING_FOR_NEXT_SESSION")
        self.assertEqual(ledger["nav_index"],100.0)
        self.assertEqual(ledger["holdings"],[])
        self.assertEqual(ledger["cash_weight"],1.0)
        self.assertFalse(ledger["orders_placed"])

    def test_forward_ledger_enters_only_on_a_new_session(self):
        history=self.make_history()
        first=update_paper_ledger(history,None,datetime(2026,11,27,tzinfo=timezone.utc))
        # Add one new session with a modest positive open-to-close move.
        new_day=(date.fromisoformat(first["last_processed_date"])+timedelta(days=1)).isoformat()
        for rows in history.values():
            old=rows[-1]["close"]
            new=old*1.01
            rows.append({"date":new_day,"open":old,"high":new*1.01,"low":old*0.99,
              "close":new,"raw_close":new,"adjusted_close":new,"volume":1000,"source":"synthetic"})
        updated=update_paper_ledger(history,first,datetime(2026,11,28,tzinfo=timezone.utc))
        self.assertEqual(updated["status"],"UPDATED")
        self.assertEqual(updated["last_processed_date"],new_day)
        self.assertGreater(updated["rebalance_count"],0)
        self.assertEqual(len(updated["holdings"]),4)
        self.assertFalse(updated["orders_placed"])
        self.assertGreater(updated["nav_index"],0)

    def test_forward_ledger_does_not_replay_same_session(self):
        history=self.make_history()
        first=update_paper_ledger(history,None)
        second=update_paper_ledger(history,first)
        self.assertEqual(second["status"],"WAITING_FOR_NEW_SESSION")
        self.assertEqual(second["nav_index"],first["nav_index"])
        self.assertEqual(second["last_processed_date"],first["last_processed_date"])

    def test_cost_assumption_is_explicit(self):
        report=build_report(self.make_history())
        self.assertGreater(report["portfolio_model"]["estimated_one_way_transaction_cost"],0)
        self.assertGreaterEqual(MIN_COMMON_BARS,200)

if __name__=="__main__": unittest.main()
