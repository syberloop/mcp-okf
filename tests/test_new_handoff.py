"""Tests de integración para new.py con type:Handoff (spec de handoff + ritmo multisession)."""

import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

from cli.commands.new import _build_frontmatter, run


class TestHandoffFrontmatter(unittest.TestCase):
    def _campo(self, fm, nombre):
        for linea in fm.splitlines():
            if linea.startswith(f"{nombre}:"):
                return linea.split(":", 1)[1].strip()
        self.fail(f"frontmatter sin campo {nombre}")

    def test_status_pending_por_defecto(self):
        fm = _build_frontmatter("Handoff", "T", "d", None, None, None, False)
        self.assertEqual(self._campo(fm, "status"), "pending")

    def test_status_custom_se_respeta(self):
        fm = _build_frontmatter("Handoff", "T", "d", "completed", None, None, False)
        self.assertEqual(self._campo(fm, "status"), "completed")

    def test_campos_handoff_presentes(self):
        fm = _build_frontmatter("Handoff", "T", "d", None, None, None, False)
        for campo in [
            "session_id", "priority", "project", "state",
            "last_activity_at", "next_session_at", "interval",
            "checkpoint_at", "repo_state", "graph_state",
        ]:
            self.assertIn(f"{campo}:", fm, f"falta campo {campo}")
        self.assertIn("commit:", fm)
        self.assertIn("files_modified: []", fm)
        self.assertIn("vecindarios: []", fm)

    def test_state_activo_por_defecto(self):
        fm = _build_frontmatter("Handoff", "T", "d", None, None, None, False)
        self.assertEqual(self._campo(fm, "state"), "activo")

    def test_otros_tipos_no_reciben_campos_handoff(self):
        fm = _build_frontmatter("Insight", "T", "d", None, None, None, False)
        self.assertNotIn("repo_state:", fm)
        self.assertNotIn("next_session_at:", fm)


class TestHandoffRun(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name)
        (self.vault / "handoffs").mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _make_args(self, **kwargs):
        defaults = {
            "concept_type": "Handoff",
            "title": "Handoff de prueba",
            "description": "Un handoff de prueba",
            "tags": None,
            "status": None,
            "resource": None,
            "cyber": False,
            "dry_run": True,
            "body": None,
            "body_file": None,
            "links": None,
            "entity": None,
            "force": False,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_crea_en_handoffs(self):
        args = self._make_args(dry_run=False)
        exit_code = run(args, self.vault)
        self.assertEqual(exit_code, 0)
        archivo = self.vault / "handoffs" / "handoff-de-prueba.md"
        self.assertTrue(archivo.exists())
        contenido = archivo.read_text(encoding="utf-8")
        self.assertIn("type: Handoff", contenido)
        self.assertIn("status: pending", contenido)
        self.assertIn("repo_state:", contenido)
        self.assertIn("next_session_at:", contenido)

    def test_dry_run_no_escribe(self):
        args = self._make_args(dry_run=True)
        exit_code = run(args, self.vault)
        self.assertEqual(exit_code, 0)
        archivo = self.vault / "handoffs" / "handoff-de-prueba.md"
        self.assertFalse(archivo.exists())

    def test_body_template_default(self):
        args = self._make_args(dry_run=True)
        exit_code = run(args, self.vault)
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
