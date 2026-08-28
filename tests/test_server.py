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
        # El path tiene que colgar del VAULT que ve el server, no de uno fijo:
        # sin el patch, este test solo pasa en la maquina cuyo VAULT resuelve a
        # /home/jota/OKF-Vault, y en cualquier otra _extract_created_path
        # devuelve None (correctamente: el path no cae dentro del vault).
        vault = Path("/home/jota/OKF-Vault")
        result = SimpleNamespace(
            returncode=0,
            stdout=f"✅ Created: {vault / 'insights' / 'new.md'}\n",
        )
        with patch.object(server, "VAULT", vault):
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


class TestServerTodosTool(unittest.TestCase):
    def test_todos_tool_registered(self):
        import server
        self.assertTrue(hasattr(server, "todos"))

    def test_todos_wraps_search_with_todos_flag(self):
        import server
        from unittest.mock import patch
        with patch.object(server, "_run", return_value="📋 Pending tasks") as mock_run:
            result = server.todos()
        self.assertEqual(result, "📋 Pending tasks")
        args = mock_run.call_args[0][0]
        self.assertEqual(args, ["search", "--todos"])
        self.assertEqual(mock_run.call_args[1]["tool_name"], "okf_todos")

    def test_todos_aging_and_all_flags(self):
        import server
        from unittest.mock import patch
        with patch.object(server, "_run", return_value="ok") as mock_run:
            server.todos(all=True, aging=True, json_output=True)
        args = mock_run.call_args[0][0]
        self.assertEqual(args, ["search", "--todos", "--all", "--aging", "--json"])


if __name__ == "__main__":
    unittest.main()
