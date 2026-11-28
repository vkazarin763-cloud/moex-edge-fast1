import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from experimental_portfolio import refresh_finam_allowlist as refresh

class AllowlistRefreshTests(unittest.TestCase):
    def run_refresh(self, params, mics=("ARCX",)):
        temp=tempfile.TemporaryDirectory()
        path=Path(temp.name)/"allowlist.json"
        def fake_api(method, endpoint, token=None, params=None, payload=None):
            if method=="POST": return {"token":"test"}
            return params_response
        params_response=params
        with patch.dict(os.environ,{"FINAM_API_SECRET":"dummy","FINAM_ACCOUNT_ID":"dummy"}), \
             patch.object(refresh,"OUT",path), patch.object(refresh,"TARGETS",{"SPY"}), \
             patch.object(refresh,"MIC_CANDIDATES",mics), patch.object(refresh,"api",fake_api), \
             patch.object(refresh.time,"sleep"):
            code=refresh.refresh()
        return code,json.loads(path.read_text()),temp

    def test_allowed_only_when_account_params_confirm_buy(self):
        code,data,temp=self.run_refresh({"is_tradable":True,"longable":{"value":"AVAILABLE"},"trade_lot_size":"1"})
        self.assertEqual(code,0)
        self.assertEqual(data["instruments"][0]["account_buy_permission"],"BUY_ALLOWED")
        self.assertTrue(data["instruments"][0]["verified_account_access"])
        temp.cleanup()

    def test_not_tradable_is_excluded(self):
        code,data,temp=self.run_refresh({"is_tradable":False,"longable":{"value":"AVAILABLE"}})
        self.assertEqual(code,0)
        self.assertEqual(data["instruments"],[])
        temp.cleanup()

    def test_ambiguous_multiple_available_listings_fail_closed(self):
        code,data,temp=self.run_refresh({"is_tradable":True,"longable":{"value":"AVAILABLE"}},mics=("ARCX","XNAS"))
        self.assertEqual(code,0)
        self.assertEqual(data["instruments"],[])
        temp.cleanup()

if __name__=="__main__": unittest.main()
