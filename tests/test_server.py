import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import server


class ServerPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        server.JSONL_DIR = root / "trace"
        server.JSONL_PATH = server.JSONL_DIR / "event_log.jsonl"
        server.DB_PATH = root / "trace.db"
        server._init_db()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_timeout_is_persisted(self):
        timeout = subprocess.TimeoutExpired(["fake"], 30)
        with patch.object(server.subprocess, "run", side_effect=timeout):
            output = server._run(["health"], tool_name="okf_health", params={})

        self.assertIn("[timeout]", output)
        with sqlite3.connect(server.DB_PATH) as conn:
            row = conn.execute("SELECT tool, exit_code, error FROM events").fetchone()
        self.assertEqual(row, ("okf_health", 124, "Timeout after 30s"))

        event = json.loads(server.JSONL_PATH.read_text(encoding="utf-8"))
        self.assertEqual(event["exit_code"], 124)

    def test_created_path_is_relative_to_vault(self):
        result = SimpleNamespace(
            returncode=0,
            stdout="✅ Created: /home/jota/OKF-Vault/insights/new.md\n",
        )
        self.assertEqual(server._extract_created_path(result), "insights/new.md")

    def test_search_persists_all_filter_parameters(self):
        with patch.object(server, "_run", return_value="ok") as run:
            server.search(
                query="agent", type="Insight", status="propuesta",
                cyber_field="outcome", cyber_value="pending",
                todos=True, json_output=True,
            )

        params = run.call_args.kwargs["params"]
        self.assertEqual(params["cyber_field"], "outcome")
        self.assertEqual(params["cyber_value"], "pending")
        self.assertTrue(params["json_output"])


if __name__ == "__main__":
    unittest.main()
