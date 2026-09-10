"""El event_log.jsonl no puede crecer sin límite.

El JSONL es el canal en vivo del plugin Cognitive Trace, que solo usa los
últimos eventos; el historial completo queda en SQLite. Sin tope, el archivo
crece con cada evento (~420 bytes de promedio) y el plugin lo lee entero cada
vez que se abre Obsidian. Al llegar a JSONL_MAX_BYTES se renombra a
<nombre>.1 y el siguiente evento abre un archivo nuevo. Lo hacen los dos
escritores: el CLI (cli/telemetry.py) y el server.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from cli import telemetry  # noqa: E402


class RotateJsonlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "event_log.jsonl"
        self.respaldo = self.dir / "event_log.jsonl.1"

    def tearDown(self):
        self.tmp.cleanup()

    def test_por_debajo_del_tope_no_toca_nada(self):
        self.path.write_text("x" * 99)
        self.assertFalse(telemetry.rotate_jsonl(self.path, 100))
        self.assertEqual(self.path.read_text(), "x" * 99)
        self.assertFalse(self.respaldo.exists())

    def test_al_llegar_al_tope_lo_renombra_a_punto_1(self):
        self.path.write_text("x" * 100)
        self.assertTrue(telemetry.rotate_jsonl(self.path, 100))
        self.assertFalse(self.path.exists())
        self.assertEqual(self.respaldo.read_text(), "x" * 100)

    def test_guarda_un_solo_respaldo(self):
        self.respaldo.write_text("viejo")
        self.path.write_text("x" * 100)
        telemetry.rotate_jsonl(self.path, 100)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["event_log.jsonl.1"])
        self.assertEqual(self.respaldo.read_text(), "x" * 100)

    def test_sin_archivo_no_falla(self):
        self.assertFalse(telemetry.rotate_jsonl(self.path, 100))

    def test_sin_tope_explicito_usa_jsonl_max_bytes(self):
        self.path.write_text("x" * 10)
        with patch.object(telemetry, "JSONL_MAX_BYTES", 10):
            self.assertTrue(telemetry.rotate_jsonl(self.path))


class EscritoresRotanTests(unittest.TestCase):
    """Los dos escritores rotan antes de escribir y no dejan huecos."""

    TOPE = 300

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "event_log.jsonl"
        self._server = (server.JSONL_DIR, server.JSONL_PATH)
        self._telemetry = (telemetry._jsonl_path, telemetry._jsonl_dir, telemetry._enabled)

    def tearDown(self):
        server.JSONL_DIR, server.JSONL_PATH = self._server
        telemetry._jsonl_path, telemetry._jsonl_dir, telemetry._enabled = self._telemetry
        self.tmp.cleanup()

    def _indices(self, path):
        return [json.loads(l)["i"] for l in path.read_text(encoding="utf-8").splitlines()]

    def _escribir(self, append, n=20):
        with patch.object(telemetry, "JSONL_MAX_BYTES", self.TOPE):
            for i in range(n):
                append({"i": i, "relleno": "x" * 50})

    def _verificar(self):
        respaldo = self.path.with_name("event_log.jsonl.1")
        self.assertTrue(respaldo.exists(), "con 20 eventos de ~70 bytes y tope 300 tiene que haber rotado")
        vivos, viejos = self._indices(self.path), self._indices(respaldo)
        # el archivo vivo nunca pasa del tope más una línea
        self.assertLess(self.path.stat().st_size, self.TOPE + 100)
        # el último evento está en el vivo y no hay hueco entre .1 y el vivo
        self.assertEqual(vivos[-1], 19)
        self.assertEqual(viejos + vivos, list(range(viejos[0], 20)))

    def test_el_cli_rota(self):
        telemetry._jsonl_path, telemetry._jsonl_dir, telemetry._enabled = self.path, self.dir, True
        self._escribir(telemetry._append_jsonl)
        self._verificar()

    def test_el_server_rota(self):
        server.JSONL_DIR, server.JSONL_PATH = self.dir, self.path
        self._escribir(server._append_jsonl)
        self._verificar()


if __name__ == "__main__":
    unittest.main()
