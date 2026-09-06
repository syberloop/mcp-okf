"""Tests para dashboard-snapshot: dashboard.json, snapshots diarios y tendencias.

Cubre:
1. Schema top-level del plan DashboardView en un vault fixture.
2. Tolerancia a db de eventos inexistente (campos null/vacíos, sin crash).
3. Snapshot diario en sistema/dashboard-snapshots/ con el mismo contenido.
4. Tendencias 7d comparando con un snapshot artificial de hace 7 días.
5. Extracción real de métricas desde un SQLite de eventos sintético.
6. Flag --canvas (mapa de calor alrededor del nodo más visitado).
"""

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from cli.commands.dashboard_snapshot import (
    _baseline_path,
    _build_snapshot,
    _domain_today,
    _trend,
    run,
)


def _concepto(vault, rel, tipo="Decision", body="", cyber=None, timestamp=None):
    """Escribe un concepto con frontmatter válido en el vault fixture."""
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = [
        "---",
        f"type: {tipo}",
        'title: "Concepto de prueba"',
        'description: "Concepto de prueba con descripcion larga"',
        f"timestamp: {timestamp or '2026-08-01T12:00:00-05:00'}",
    ]
    if cyber:
        fm.append("cyber:")
        fm.append(f"  sensor: {cyber.get('sensor', 'demo')}")
        fm.append(f"  outcome: {cyber.get('outcome', 'pending')}")
        if cyber.get("review_on"):
            fm.append(f"  review_on: {cyber['review_on']}")
        fm.append("  target_metric:")
        fm.append("    name: demometro")
    fm.append("---")
    path.write_text("\n".join(fm) + "\n" + body, encoding="utf-8")
    return path


def _db_events_schema(conn):
    """Crea el esquema mínimo de Cognitive Trace en un SQLite sintético."""
    conn.executescript("""
    CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        ts TEXT NOT NULL,
        tool TEXT NOT NULL,
        params TEXT NOT NULL DEFAULT '{}',
        nodes_count INTEGER, exit_code INTEGER, error TEXT, duration_ms INTEGER,
        created_at TEXT DEFAULT (datetime('now')),
        result_edges TEXT, prompt_id TEXT
    );
    CREATE VIEW v_node_events AS
        SELECT session_id, ts,
               CASE WHEN tool IN ('okf_traverse', 'traverse') THEN 'traverse'
                    WHEN tool IN ('okf_read', 'read') THEN 'read'
                    WHEN tool IN ('okf_search', 'search') THEN 'search'
                    ELSE replace(tool, '-', '_') END AS tool_norm,
               json_extract(params, '$.slug') AS raw_node,
               CASE WHEN instr(json_extract(params, '$.slug'), '/') > 0
                    THEN substr(json_extract(params, '$.slug'),
                                instr(json_extract(params, '$.slug'), '/') + 1)
                    ELSE json_extract(params, '$.slug') END AS node,
               json_extract(params, '$.depth') AS depth,
               exit_code
        FROM events
        WHERE json_extract(params, '$.slug') IS NOT NULL;
    """)
    conn.commit()


def _db_con_actividad(path):
    """SQLite sintético con traverses/reads recientes y uno antiguo."""
    conn = sqlite3.connect(str(path))
    _db_events_schema(conn)
    now = datetime.now(timezone.utc)
    eventos = [
        # 2 traverses + 1 read recientes sobre conceptos/a → read_ratio 0.5
        ("traverse", "conceptos/a", now),
        ("traverse", "conceptos/a", now - timedelta(hours=5)),
        ("read", "conceptos/a", now - timedelta(hours=6)),
        ("traverse", "conceptos/b", now - timedelta(hours=8)),
        ("okf_search", "conceptos/b", now - timedelta(hours=9)),
        # Nodo descuidado: última visita hace 30 días
        ("traverse", "conceptos/antiguo", now - timedelta(days=30)),
    ]
    for i, (tool, slug, ts) in enumerate(eventos):
        conn.execute(
            "INSERT INTO events (session_id, ts, tool, params, exit_code) "
            "VALUES (?, ?, ?, ?, 0)",
            (f"s{i % 2}", ts.isoformat(), tool, json.dumps({"slug": slug})),
        )
    conn.commit()
    conn.close()
    return path


class SnapshotFixture(unittest.TestCase):
    """Fixture común: vault temporal con conceptos, minuta de sesión y cyber."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        _concepto(self.vault, "conceptos/a.md", body="Ver [[conceptos/b.md]]\n")
        _concepto(self.vault, "conceptos/b.md", body="Ver [[conceptos/a.md]]\n")
        _concepto(self.vault, "conceptos/cyber.md",
                  cyber={"outcome": "pending",
                         "review_on": (_domain_today() + timedelta(days=3)).isoformat()})
        _concepto(self.vault, "conceptos/cyber-vencido.md",
                  cyber={"outcome": "pending", "review_on": "2020-01-01"})
        # Minuta de sesión reciente con infracciones MCP
        sesiones = self.vault / "sesiones"
        sesiones.mkdir()
        ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        (sesiones / "sesion-test.md").write_text(
            "---\n"
            "type: Session\n"
            'title: "Sesion de prueba"\n'
            'description: "Minuta de prueba del fixture"\n'
            f"timestamp: {ts}\n"
            "---\n\n"
            "## Métricas\n\n"
            "Tools usadas: traverse (4), read (2)\n"
            "Conceptos creados: 1\n"
            "Commits: 3\n"
            "Infracciones MCP: 2\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _args(self, **kwargs):
        return SimpleNamespace(db=kwargs.get("db", "/nonexistent/events.db"),
                               source=kwargs.get("source", "manual"),
                               canvas=kwargs.get("canvas", False))

    def _run(self, **kwargs):
        run(self._args(**kwargs), self.vault, None)
        return json.loads((self.vault / "dashboard.json").read_text(encoding="utf-8"))


class TestSchema(SnapshotFixture):
    def test_campos_top_level(self):
        snap = self._run()
        esperados = {"generated_at", "generated_by", "source", "health", "graph",
                     "cibernetica", "actividad", "calor_estructural",
                     "conceptos", "negocio", "tendencias"}
        self.assertEqual(set(snap.keys()), esperados)
        self.assertIsNone(snap["negocio"])  # fase 2 del plan
        self.assertTrue(snap["generated_at"].endswith(("-05:00", "+00:00")))

    def test_secciones_del_plan(self):
        snap = self._run()
        health = snap["health"]
        for k in ("score", "max_score", "errors", "warnings",
                  "warnings_detail", "trend_7d"):
            self.assertIn(k, health)
        graph = snap["graph"]
        for k in ("total_nodes", "total_edges", "orphans", "hubs_top5",
                  "density", "trend_7d"):
            self.assertIn(k, graph)
        self.assertGreaterEqual(graph["total_nodes"], 4)
        ciber = snap["cibernetica"]
        for k in ("total_blocks", "loops_cerrados", "loops_abiertos",
                  "review_on_vencidos", "review_on_proximos_7d",
                  "outcome_pending", "outcome_success", "outcome_failure",
                  "trend_7d"):
            self.assertIn(k, ciber)
        actividad = snap["actividad"]
        for k in ("sesiones_7d", "eventos_7d", "eventos_24h", "tools_usadas",
                  "read_ratio_promedio", "infracciones_mcp_7d",
                  "entry_points_top3", "trend_7d"):
            self.assertIn(k, actividad)
        calor = snap["calor_estructural"]
        for k in ("top_visited", "top_neglected", "stale_distribution"):
            self.assertIn(k, calor)
        self.assertEqual(set(calor["stale_distribution"].keys()),
                         {"FRESCO", "ATENCION", "STALE"})
        tendencias = snap["tendencias"]
        for k in ("health_score_trend", "eventos_semana_trend",
                  "stale_count_trend", "cyber_loops_abiertos_trend",
                  "read_ratio_trend"):
            self.assertIn(k, tendencias)

    def test_cibernetica_real_del_vault(self):
        snap = self._run()
        ciber = snap["cibernetica"]
        self.assertEqual(ciber["total_blocks"], 2)
        self.assertEqual(ciber["outcome_pending"], 2)
        self.assertEqual(ciber["loops_abiertos"], 2)
        self.assertEqual(ciber["loops_cerrados"], 0)
        self.assertEqual(ciber["review_on_vencidos"], 1)      # cyber-vencido
        self.assertEqual(ciber["review_on_proximos_7d"], 1)   # cyber +3d

    def test_infracciones_desde_minutas(self):
        snap = self._run()
        self.assertEqual(snap["actividad"]["infracciones_mcp_7d"], 2)


class TestSinDB(SnapshotFixture):
    def test_db_inexistente_no_crashea(self):
        snap = self._run(db="/nonexistent/events.db")
        act = snap["actividad"]
        self.assertIsNone(act["eventos_7d"])
        self.assertIsNone(act["eventos_24h"])
        self.assertIsNone(act["sesiones_7d"])
        self.assertIsNone(act["read_ratio_promedio"])
        self.assertEqual(act["tools_usadas"], {})
        self.assertEqual(act["entry_points_top3"], [])
        self.assertEqual(snap["calor_estructural"]["top_visited"], [])
        self.assertEqual(snap["calor_estructural"]["top_neglected"], [])

    def test_tendencias_null_sin_baseline(self):
        snap = self._run()
        self.assertEqual(snap["health"]["trend_7d"], None)
        self.assertEqual(snap["actividad"]["trend_7d"], None)
        self.assertEqual(snap["cibernetica"]["trend_7d"], None)
        self.assertEqual(snap["graph"]["trend_7d"], None)
        for v in snap["tendencias"].values():
            self.assertIsNone(v)


class TestSnapshotsDiarios(SnapshotFixture):
    def test_escribe_snapshot_diario(self):
        self._run()
        today = _domain_today()
        diario = self.vault / "sistema" / "dashboard-snapshots" / f"{today.isoformat()}.json"
        self.assertTrue(diario.exists())
        # Mismo contenido que dashboard.json
        self.assertEqual(diario.read_text(encoding="utf-8"),
                         (self.vault / "dashboard.json").read_text(encoding="utf-8"))

    def test_snapshot_precio_7dias_se_usa_como_baseline(self):
        today = _domain_today()
        base = _baseline_path(self.vault, today)
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_text(json.dumps({
            "health": {"score": 99},
            "graph": {"density": 99},
            "cibernetica": {"loops_abiertos": 9999},
            "actividad": {"eventos_7d": 999999, "read_ratio_promedio": 99},
            "calor_estructural": {"stale_distribution": {"STALE": 9999}},
        }), encoding="utf-8")
        # Valores baseline absurdamente altos → todas las tendencias "down"
        snap = self._run(db=str(self._crear_db_pequeña()))
        tendencias = snap["tendencias"]
        self.assertEqual(tendencias["health_score_trend"], "down")
        self.assertEqual(tendencias["eventos_semana_trend"], "down")
        self.assertEqual(tendencias["stale_count_trend"], "down")
        self.assertEqual(tendencias["cyber_loops_abiertos_trend"], "down")
        self.assertEqual(tendencias["read_ratio_trend"], "down")
        self.assertEqual(snap["health"]["trend_7d"], "down")
        self.assertEqual(snap["actividad"]["trend_7d"], "down")
        self.assertEqual(snap["cibernetica"]["trend_7d"], "down")
        self.assertEqual(snap["graph"]["trend_7d"], "down")

    def _crear_db_pequeña(self):
        db = self.vault / "events-test.db"
        return _db_con_actividad(db)


class TestDBPresente(SnapshotFixture):
    def setUp(self):
        super().setUp()
        self.db = _db_con_actividad(self.vault / "events-test.db")

    def test_actividad_desde_sqlite(self):
        snap = self._run(db=str(self.db))
        act = snap["actividad"]
        self.assertEqual(act["eventos_24h"], 5)   # todos menos el de 30d
        self.assertEqual(act["eventos_7d"], 5)
        self.assertEqual(act["sesiones_7d"], 2)   # s0 y s1
        self.assertEqual(act["tools_usadas"],
                         {"traverse": 3, "read": 1, "search": 1})
        # ratios por nodo: a=0.5, b=0.0 → promedio 0.25
        self.assertAlmostEqual(act["read_ratio_promedio"], 0.25)
        self.assertEqual(act["entry_points_top3"][0], "conceptos/a")

    def test_calor_estructural_desde_sqlite(self):
        snap = self._run(db=str(self.db))
        calor = snap["calor_estructural"]
        top = calor["top_visited"]
        self.assertGreaterEqual(len(top), 2)
        a = next(t for t in top if t["slug"] == "conceptos/a")
        self.assertEqual(a["traverses"], 2)
        self.assertEqual(a["reads"], 1)
        self.assertEqual(a["read_ratio"], 0.5)
        b = next(t for t in top if t["slug"] == "conceptos/b")
        self.assertEqual(b["read_ratio"], 0.0)
        descuidados = calor["top_neglected"]
        self.assertEqual(len(descuidados), 1)
        self.assertEqual(descuidados[0]["slug"], "conceptos/antiguo")
        self.assertGreaterEqual(descuidados[0]["days_since_last_visit"], 14)

    def test_canvas_flag(self):
        snap = self._run(db=str(self.db), canvas=True)
        today = _domain_today()
        canvas = self.vault / "sistema" / "mapas" / f"calor-{today.isoformat()}.canvas"
        self.assertTrue(canvas.exists())
        data = json.loads(canvas.read_text(encoding="utf-8"))
        ids = {n["id"] for n in data["nodes"]}
        self.assertIn("conceptos/a", ids)  # top visited = raíz del mapa


class TestTrendHelper(unittest.TestCase):
    def test_direcciones(self):
        self.assertEqual(_trend(5, 4), "up")
        self.assertEqual(_trend(4, 5), "down")
        self.assertEqual(_trend(4, 4), "flat")

    def test_null_sin_baseline(self):
        self.assertIsNone(_trend(5, None))
        self.assertIsNone(_trend(None, 5))


if __name__ == "__main__":
    unittest.main()
