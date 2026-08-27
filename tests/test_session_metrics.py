"""Tests de session_metrics: resolucion del directorio y parseo de metricas.

Regresion: run() buscaba un literal "sesiones", asi que en un vault con el
esquema en ingles (types.directory.Session = "sessions") reportaba siempre
"(no sessions)" aunque las minutas existieran.
"""

import io
import unittest
import tempfile
import contextlib
from pathlib import Path
from types import SimpleNamespace

from cli.commands.session_metrics import _sessions_dir, _parse_metrics_section, run


MINUTA = '''---
type: Session
title: "Sesion de prueba"
description: "Minuta de prueba"
timestamp: 2026-08-27T15:00:00-05:00
---

## Métricas

Tools usadas: traverse (4), read (2)
Conceptos creados: 1
Commits: 3
Infracciones MCP: 0
'''


class TestSessionsDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_toma_el_nombre_del_config(self):
        (self.vault / "sessions").mkdir()
        cfg = SimpleNamespace(types_directory={"Session": "sessions"})
        self.assertEqual(_sessions_dir(self.vault, cfg), self.vault / "sessions")

    def test_sin_config_encuentra_sessions(self):
        (self.vault / "sessions").mkdir()
        self.assertEqual(_sessions_dir(self.vault, None), self.vault / "sessions")

    def test_sin_config_respeta_el_legado_sesiones(self):
        (self.vault / "sesiones").mkdir()
        self.assertEqual(_sessions_dir(self.vault, None), self.vault / "sesiones")

    def test_config_roto_no_revienta(self):
        (self.vault / "sessions").mkdir()
        cfg = SimpleNamespace()  # sin types_directory
        self.assertEqual(_sessions_dir(self.vault, cfg), self.vault / "sessions")


class TestRunEncuentraLasMinutas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        (self.vault / "sessions").mkdir()
        (self.vault / "sessions" / "sesion-2026-08-27-prueba.md").write_text(
            MINUTA, encoding="utf-8"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _salida(self, config):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run(SimpleNamespace(json=False), self.vault, config)
        return buf.getvalue()

    def test_no_reporta_vacio_con_config(self):
        cfg = SimpleNamespace(types_directory={"Session": "sessions"})
        salida = self._salida(cfg)
        self.assertNotIn("(no sessions)", salida)

    def test_no_reporta_vacio_sin_config(self):
        self.assertNotIn("(no sessions)", self._salida(None))


class TestParseMetricas(unittest.TestCase):
    def test_lee_la_seccion_en_espanol(self):
        m = _parse_metrics_section(MINUTA)
        self.assertEqual(m.get("commits"), 3)
        self.assertEqual(m.get("conceptos_creados"), 1)
        self.assertEqual(m.get("infracciones"), 0)
        self.assertEqual(m.get("tools", {}).get("traverse"), 4)


if __name__ == "__main__":
    unittest.main()
