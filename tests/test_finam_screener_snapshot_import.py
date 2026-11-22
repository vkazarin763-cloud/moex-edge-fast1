import json
import tempfile
import unittest
from pathlib import Path

from scripts.import_finam_screener_snapshot import load_export, write_snapshot
from research_agent.finam_screener_adapter import FinamScreenerDataError


class FinamSnapshotImportTests(unittest.TestCase):
    def test_requires_five_responses_and_explicit_retrieval_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            path.write_text(json.dumps({"responses": [], "retrieved_at": "2026-11-22T12:00:00Z"}))
            with self.assertRaisesRegex(FinamScreenerDataError, "exactly five"):
                load_export(path)

    def test_rejects_missing_retrieval_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            path.write_text(json.dumps({"responses": [{}, {}, {}, {}, {}]}))
            with self.assertRaisesRegex(FinamScreenerDataError, "retrieved_at"):
                load_export(path)

    def test_does_not_overwrite_existing_snapshot_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            path.write_text("existing")
            with self.assertRaisesRegex(FinamScreenerDataError, "already exists"):
                write_snapshot({"ok": True}, path)

    def test_writes_valid_json_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "snapshot.json"
            write_snapshot({"ok": True}, path)
            self.assertEqual(json.loads(path.read_text()), {"ok": True})


if __name__ == "__main__":
    unittest.main()
