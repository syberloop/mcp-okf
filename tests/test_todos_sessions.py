"""Tests de find_todos — las minutas de sesión no son backlog.

Los checkboxes de un `type: Session` son la foto de lo que estaba pendiente
ese día. Al escanearlos, cada sesión pasada vuelve a inyectar su lista
congelada en la lista viva, y lo que inyecta suele estar ya hecho.

Mismo criterio que ya aplican Spec (2026-08-02) y Skill (2026-08-06).
"""

import tempfile
import unittest
from pathlib import Path


CONCEPTO = """---
type: {tipo}
title: "{titulo}"
description: "test"
---

- [ ] {tarea}
"""


class TodosSessionsTestBase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name)
        for carpeta in ("plans", "sessions"):
            (self.vault / carpeta).mkdir()
        (self.vault / "plans" / "plan.md").write_text(
            CONCEPTO.format(tipo="Plan", titulo="Plan", tarea="tarea viva"),
            encoding="utf-8")
        (self.vault / "sessions" / "sesion.md").write_text(
            CONCEPTO.format(tipo="Session", titulo="Sesion", tarea="foto de ese dia"),
            encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _textos(self, **kwargs):
        from cli.commands.search import find_todos
        return [t["text"] for t in find_todos(self.vault, **kwargs)]


class TestTodosExcluyeSessions(TodosSessionsTestBase):
    def test_por_defecto_no_lista_las_minutas(self):
        textos = self._textos()
        self.assertIn("tarea viva", textos)
        self.assertNotIn("foto de ese dia", textos,
                         f"una minuta no es backlog: {textos}")

    def test_include_sessions_las_trae_de_vuelta(self):
        """El opt-in existe, igual que --include-specs e --include-skills."""
        textos = self._textos(include_sessions=True)
        self.assertIn("tarea viva", textos)
        self.assertIn("foto de ese dia", textos)


if __name__ == "__main__":
    unittest.main()
