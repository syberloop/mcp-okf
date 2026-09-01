"""Tests de find_todos — los handoffs no son backlog.

Los checkboxes de un `type: Handoff` son el estado congelado de una sesión
(tareas que el handoff transmite al próximo agente), no una lista viva:
vuelven a inyectar los mismos ítems en cada sesión hasta que el handoff
se actualiza. Mismo criterio que ya aplican Spec (2026-08-02), Skill
(2026-08-06) y Session (2026-09-01).
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


class TodosHandoffsTestBase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name)
        for carpeta in ("plans", "handoffs"):
            (self.vault / carpeta).mkdir()
        (self.vault / "plans" / "plan.md").write_text(
            CONCEPTO.format(tipo="Plan", titulo="Plan", tarea="tarea viva"),
            encoding="utf-8")
        (self.vault / "handoffs" / "handoff.md").write_text(
            CONCEPTO.format(tipo="Handoff", titulo="Handoff", tarea="estado congelado"),
            encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _textos(self, **kwargs):
        from cli.commands.search import find_todos
        return [t["text"] for t in find_todos(self.vault, **kwargs)]


class TestTodosExcluyeHandoffs(TodosHandoffsTestBase):
    def test_por_defecto_no_lista_los_handoffs(self):
        textos = self._textos()
        self.assertIn("tarea viva", textos)
        self.assertNotIn("estado congelado", textos,
                         f"un handoff no es backlog: {textos}")

    def test_include_handoffs_los_trae_de_vuelta(self):
        """El opt-in existe, igual que --include-sessions."""
        textos = self._textos(include_handoffs=True)
        self.assertIn("tarea viva", textos)
        self.assertIn("estado congelado", textos)


if __name__ == "__main__":
    unittest.main()
