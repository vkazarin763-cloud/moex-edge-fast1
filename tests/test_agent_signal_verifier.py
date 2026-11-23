import unittest

from research_agent.agent_signal_verifier import (
    AgentContractError, verify_agent_proposals,
)


class AgentSignalVerifierTests(unittest.TestCase):
    def setUp(self):
        self.scan = {
            "status": "READ_ONLY_LATEST_SIGNAL_SCAN",
            "as_of_utc": "2026-11-23T12:00:00+00:00",
            "universe": ["SBER", "LKOH"],
            "signals": [{
                "symbol": "SBER", "direction": "LONG", "strategy": "Donchian20",
                "d1_bar_end_utc": "2026-11-20T21:00:00+00:00",
                "d1_close": 250.0, "h1_confirmation": "CONFIRMED",
                "h1": {"status": "CONFIRMED"},
            }],
        }
        self.registry = {
            "registry_version": "test-registry",
            "stage": "DEVELOPMENT_ONLY_NOT_PRODUCTION_APPROVAL",
            "holdout_used_for_selection": False,
            "scanner_contract": {"live_trading_authorized": False},
            "strategies": [{
                "ticker": "SBER", "direction": "LONG", "strategy": "Donchian20",
                "status": "PASS", "eligible_for_shadow_scanner": True,
            }],
        }
        self.agent = {
            "status": "AGENT_SIGNAL_PROPOSALS",
            "generated_at_utc": "2026-11-23T12:01:00+00:00",
            "agent_run_id": "test-run-1",
            "proposals": [{
                "symbol": "SBER", "direction": "LONG", "strategy": "Donchian20",
                "d1_bar_end_utc": "2026-11-20T21:00:00+00:00",
                "timeframes": ["D1", "H1"], "rationale": "Breakout candidate.",
            }],
        }

    def test_exact_reproduced_and_approved_signal_is_confirmed(self):
        result = verify_agent_proposals(self.agent, self.scan, self.registry)
        self.assertEqual(result["confirmed_signals_count"], 1)
        self.assertEqual(result["results"][0]["status"], "CONFIRMED")

    def test_unapproved_strategy_is_experimental_even_when_reproduced(self):
        registry = {**self.registry, "strategies": []}
        result = verify_agent_proposals(self.agent, self.scan, registry)
        self.assertEqual(result["results"][0]["status"], "EXPERIMENTAL_STRATEGY_UNAPPROVED")
        self.assertEqual(result["confirmed_signals_count"], 0)

    def test_h1_must_be_confirmed(self):
        scan = {**self.scan, "signals": [{**self.scan["signals"][0], "h1_confirmation": "NOT_CONFIRMED"}]}
        result = verify_agent_proposals(self.agent, scan, self.registry)
        self.assertEqual(result["results"][0]["status"], "VERIFIED_SIGNAL_H1_NOT_CONFIRMED")

    def test_non_reproduced_agent_signal_is_rejected(self):
        agent = {**self.agent, "proposals": [{
            **self.agent["proposals"][0], "d1_bar_end_utc": "2026-11-19T21:00:00+00:00"
        }]}
        result = verify_agent_proposals(agent, self.scan, self.registry)
        self.assertEqual(result["results"][0]["status"], "REJECTED_NOT_REPRODUCED")

    def test_out_of_universe_symbol_is_rejected(self):
        agent = {**self.agent, "proposals": [{**self.agent["proposals"][0], "symbol": "GAZP"}]}
        with self.assertRaises(AgentContractError):
            verify_agent_proposals(agent, self.scan, self.registry)

    def test_duplicate_proposals_are_rejected(self):
        agent = {**self.agent, "proposals": self.agent["proposals"] * 2}
        with self.assertRaisesRegex(AgentContractError, "Duplicate"):
            verify_agent_proposals(agent, self.scan, self.registry)

    def test_agent_cannot_inject_unsupported_strategy(self):
        agent = {**self.agent, "proposals": [{
            **self.agent["proposals"][0], "strategy": "magic-profit-model"
        }]}
        with self.assertRaises(AgentContractError):
            verify_agent_proposals(agent, self.scan, self.registry)

    def test_registry_cannot_authorize_live_trading(self):
        registry = {**self.registry, "scanner_contract": {"live_trading_authorized": True}}
        with self.assertRaises(AgentContractError):
            verify_agent_proposals(self.agent, self.scan, registry)


if __name__ == "__main__":
    unittest.main()
