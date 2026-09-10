"""`analytics node_timeline` consultaba una columna inexistente y fallaba siempre.

`v_node_events` expone `tool_norm`, no `tool`: la query tiraba
`sqlite3.OperationalError: no such column: tool` con cualquier argumento, y el
render leía la misma clave inexistente (`r['tool']`). Issue #14.
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli import telemetry  # noqa: E402
from cli.commands import analytics  # noqa: E402

# (tool, params) tal como los escriben el server y el CLI
EVENTOS = [
    ("okf_traverse", '{"slug": "frameworks/tp3-cibernetico", "depth": 2}'),
    ("okf_read", '{"target": "frameworks/tp3-cibernetico", "offset": 1}'),
    ("okf_traverse", '{"slug": "decisions/implantacion-okf", "depth": 1}'),
]


class NodeTimelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._telemetry = (telemetry._db_path, telemetry._jsonl_path,
                           telemetry._jsonl_dir, telemetry._enabled)

    def tearDown(self):
        (telemetry._db_path, telemetry._jsonl_path,
         telemetry._jsonl_dir, telemetry._enabled) = self._telemetry
        self.tmp.cleanup()

    def _conn(self):
        db = self.root / "telemetry.db"
        cfg = SimpleNamespace(
            features_cognitive_trace=True,
            _data={"features": {
                "trace_db_path": str(db),
                "trace_jsonl_path": str(self.root / "t" / "event_log.jsonl"),
            }},
        )
        telemetry.init(self.root, cfg)
        with sqlite3.connect(db) as c:
            for i, (tool, params) in enumerate(EVENTOS):
                c.execute(
                    "INSERT INTO events (session_id, ts, tool, params, exit_code) "
                    "VALUES (?, ?, ?, ?, 0)",
                    ("s1", f"2026-09-10T15:00:{i:02d}+00:00", tool, params),
                )
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    def test_devuelve_el_historial_sin_explotar(self):
        conn = self._conn()
        try:
            salida = analytics._query_node_timeline(conn, 10, "tp3-cibernetico")
        finally:
            conn.close()
        self.assertNotIn("OperationalError", salida)
        self.assertIn("History of 'tp3-cibernetico':", salida)
        self.assertEqual(len(salida.strip().splitlines()), 3)  # titulo + 2 visitas

    def test_la_tool_se_renderiza_normalizada(self):
        """El evento del server (slug) y el del CLI (target) tienen que verse."""
        conn = self._conn()
        try:
            salida = analytics._query_node_timeline(conn, 10, "frameworks/tp3-cibernetico")
        finally:
            conn.close()
        self.assertIn("— traverse", salida)
        self.assertIn("— read", salida)

    def test_nodo_sin_eventos_sigue_diciendo_no_data(self):
        conn = self._conn()
        try:
            salida = analytics._query_node_timeline(conn, 10, "frameworks/no-existe")
        finally:
            conn.close()
        self.assertEqual(salida, "(no data for 'frameworks/no-existe')")


if __name__ == "__main__":
    unittest.main()
