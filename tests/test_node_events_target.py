"""v_node_events tiene que ver los traverse y read que registra el CLI.

El server guarda el nodo en params.slug, pero el CLI lo guarda en
params.target: es el nombre del argumento posicional de `traverse` y de
`read` (el harness dsh hacía lo mismo). La vista filtraba por slug, así que
esos eventos nunca llegaban a v_node_visits. Sobre un vault real había 17
traverses grabados y `analytics most_visited` respondía "no traverses
recorded yet"; lo mismo pasaba con session_heatmap, co_visited, read_ratio,
session_diff, depth_stats y entry_points, que leen de la misma vista.

La vista está definida dos veces (cli/telemetry.py y server.py) y las dos
tienen que dar el mismo resultado.
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from cli import telemetry  # noqa: E402
from cli.commands import analytics  # noqa: E402

# (tool, params) tal como los escriben el CLI y el server
EVENTOS = [
    ("okf_traverse", '{"target": "decisions/implantacion-okf", "depth": 1, "direction": "both"}'),
    ("okf_traverse", '{"slug": "frameworks/tp3-cibernetico", "depth": 2}'),
    ("okf_read", '{"target": "decisions/implantacion-okf", "offset": 1, "limit": 500}'),
    ("okf_read", '{"slug": "frameworks/tp3-cibernetico"}'),
    # validate también usa target, pero ahí es una ruta de archivo, no una visita
    ("okf_validate", '{"target": "decisions/implantacion-okf.md"}'),
]


def _insertar(db: Path) -> None:
    with sqlite3.connect(db) as conn:
        for i, (tool, params) in enumerate(EVENTOS):
            conn.execute(
                "INSERT INTO events (session_id, ts, tool, params, exit_code) "
                "VALUES (?, ?, ?, ?, 0)",
                ("s1", f"2026-09-10T15:00:{i:02d}+00:00", tool, params),
            )


class NodeEventsTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Estado global de los dos módulos: se restaura para no contaminar
        # el resto de la suite.
        self._server = (server.DB_PATH, server.JSONL_DIR, server.JSONL_PATH)
        self._telemetry = (telemetry._db_path, telemetry._jsonl_path,
                           telemetry._jsonl_dir, telemetry._enabled)

    def tearDown(self):
        server.DB_PATH, server.JSONL_DIR, server.JSONL_PATH = self._server
        (telemetry._db_path, telemetry._jsonl_path,
         telemetry._jsonl_dir, telemetry._enabled) = self._telemetry
        self.tmp.cleanup()

    def _db_telemetry(self) -> Path:
        db = self.root / "telemetry.db"
        cfg = SimpleNamespace(
            features_cognitive_trace=True,
            _data={"features": {
                "trace_db_path": str(db),
                "trace_jsonl_path": str(self.root / "t" / "event_log.jsonl"),
            }},
        )
        telemetry.init(self.root, cfg)
        _insertar(db)
        return db

    def _db_server(self) -> Path:
        db = self.root / "server.db"
        server.JSONL_DIR = self.root / "s"
        server.JSONL_PATH = server.JSONL_DIR / "event_log.jsonl"
        server.DB_PATH = db
        server._init_db()
        _insertar(db)
        return db

    @staticmethod
    def _visitas(db: Path) -> dict:
        with sqlite3.connect(db) as conn:
            return dict(conn.execute("SELECT node, visits FROM v_node_visits"))

    def test_telemetry_cuenta_el_traverse_con_target(self):
        self.assertEqual(self._visitas(self._db_telemetry()),
                         {"implantacion-okf": 1, "tp3-cibernetico": 1})

    def test_server_cuenta_el_traverse_con_target(self):
        self.assertEqual(self._visitas(self._db_server()),
                         {"implantacion-okf": 1, "tp3-cibernetico": 1})

    def test_el_read_con_target_tambien_es_nodo(self):
        with sqlite3.connect(self._db_telemetry()) as conn:
            nodos = sorted(r[0] for r in conn.execute(
                "SELECT node FROM v_node_events WHERE tool_norm = 'read'"))
        self.assertEqual(nodos, ["implantacion-okf", "tp3-cibernetico"])

    def test_la_profundidad_del_traverse_del_cli_se_conserva(self):
        with sqlite3.connect(self._db_telemetry()) as conn:
            depths = sorted(r[0] for r in conn.execute(
                "SELECT depth FROM v_node_events WHERE tool_norm = 'traverse'"))
        self.assertEqual(depths, [1, 2])

    def test_el_target_de_otras_tools_no_es_nodo(self):
        """En validate, target es una ruta: no debe contar como visita."""
        with sqlite3.connect(self._db_telemetry()) as conn:
            tools = {r[0] for r in conn.execute("SELECT tool_norm FROM v_node_events")}
        self.assertEqual(tools, {"traverse", "read"})

    def test_las_dos_definiciones_de_la_vista_coinciden(self):
        consulta = "SELECT * FROM v_node_events ORDER BY ts"
        with sqlite3.connect(self._db_telemetry()) as a, \
                sqlite3.connect(self._db_server()) as b:
            self.assertEqual(a.execute(consulta).fetchall(),
                             b.execute(consulta).fetchall())

    def test_most_visited_deja_de_responder_sin_datos(self):
        conn = sqlite3.connect(self._db_telemetry())
        conn.row_factory = sqlite3.Row
        try:
            salida = analytics._query_most_visited(conn, 10)
        finally:
            conn.close()
        self.assertNotIn("no data", salida)
        self.assertIn("implantacion-okf — 1 visits", salida)


if __name__ == "__main__":
    unittest.main()
