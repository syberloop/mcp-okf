"""Tests de integración para edit.py (update de conceptos, merge semantics)."""

import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cli.commands.edit import run


TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-05:00$")

FIXTURE = """---
type: Decision
title: "Decision Base"
description: "Descripcion original"
status: propuesta
tags: [vault, agentes]
created: 2026-01-01T00:00:00-05:00
timestamp: 2026-01-01T00:00:00-05:00
links:
  - target: frameworks/tp3-cibernetico.md
    type: extiende
cyber:
  sensor: "prueba"
  perception: ""
  target_metric:
    name: ""
    target: 0
  actuator: []
  corrects: []
  outcome: pending
  review_on: 2026-01-15
---
## Contexto

Contenido original del body.
"""


class EditTestBase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name)
        (self.vault / "decisions").mkdir()
        (self.vault / "frameworks").mkdir()
        self.target = self.vault / "frameworks" / "tp3-cibernetico.md"
        self.target.write_text("""---
type: MarcoTeorico
title: "TP3 Cibernetico"
description: "Marco teorico de referencia"
timestamp: 2026-01-01T00:00:00-05:00
created: 2026-01-01T00:00:00-05:00
---

Contenido.
""", encoding="utf-8")
        self.concept = self.vault / "decisions" / "decision-base.md"
        self.concept.write_text(FIXTURE, encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _args(self, **kwargs):
        defaults = {
            "slug": "decisions/decision-base",
            "title": None,
            "description": None,
            "tags": None,
            "status": None,
            "resource": None,
            "body": None,
            "body_file": None,
            "links": None,
            "clear_links": False,
            "dry_run": False,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def _read(self):
        return self.concept.read_text(encoding="utf-8")


class TestEditBasic(EditTestBase):
    def test_update_description(self):
        exit_code = run(self._args(description="Nueva descripcion"), self.vault)
        self.assertEqual(exit_code, 0)
        text = self._read()
        self.assertIn('description: "Nueva descripcion"', text)
        self.assertIn('title: "Decision Base"', text)
        self.assertIn("## Contexto", text)

    def test_timestamp_refreshed_created_preserved(self):
        run(self._args(description="Nueva descripcion"), self.vault)
        text = self._read()
        m = re.search(r"^timestamp: (.*)$", text, re.M)
        self.assertIsNotNone(m)
        self.assertRegex(m.group(1), TIMESTAMP_RE)
        self.assertNotEqual(m.group(1), "2026-01-01T00:00:00-05:00")
        self.assertIn("created: 2026-01-01T00:00:00-05:00", text)

    def test_update_status_and_tags(self):
        exit_code = run(self._args(status="aplicada", tags="okf,cibernetico"), self.vault)
        self.assertEqual(exit_code, 0)
        text = self._read()
        self.assertIn("status: aplicada", text)
        self.assertIn("tags: [okf, cibernetico]", text)

    def test_clear_status_with_empty_string(self):
        exit_code = run(self._args(status=""), self.vault)
        self.assertEqual(exit_code, 0)
        self.assertNotIn("status:", self._read())

    def test_clear_tags_with_empty_string(self):
        exit_code = run(self._args(tags=""), self.vault)
        self.assertEqual(exit_code, 0)
        self.assertNotIn("tags:", self._read())

    def test_update_body(self):
        exit_code = run(self._args(body="## Nuevo contexto\n\nCuerpo nuevo."), self.vault)
        self.assertEqual(exit_code, 0)
        text = self._read()
        self.assertIn("## Nuevo contexto", text)
        self.assertNotIn("Contenido original del body", text)

    def test_update_title_does_not_rename_file(self):
        exit_code = run(self._args(title="Decision Renombrada"), self.vault)
        self.assertEqual(exit_code, 0)
        self.assertTrue(self.concept.exists())
        text = self._read()
        self.assertIn('title: "Decision Renombrada"', text)

    def test_no_changes_does_not_write(self):
        before = self._read()
        exit_code = run(self._args(), self.vault)
        self.assertEqual(exit_code, 0)
        self.assertEqual(before, self._read())


class TestEditLinks(EditTestBase):
    def test_replace_links(self):
        exit_code = run(self._args(links=["decisions/decision-base:corrige"]), self.vault)
        self.assertEqual(exit_code, 0)
        text = self._read()
        self.assertNotIn("target: frameworks/tp3-cibernetico.md", text)
        self.assertIn("target: decisions/decision-base.md", text)

    def test_clear_links(self):
        exit_code = run(self._args(clear_links=True), self.vault)
        self.assertEqual(exit_code, 0)
        self.assertNotIn("links:", self._read())

    def test_invalid_link_target_rejected(self):
        exit_code = run(self._args(links=["nonexistent:extiende"]), self.vault)
        self.assertEqual(exit_code, 1)
        text = self._read()
        self.assertIn("target: frameworks/tp3-cibernetico.md", text)

    def test_invalid_edge_type_rejected(self):
        exit_code = run(self._args(links=["frameworks/tp3-cibernetico:bad_type"]), self.vault)
        self.assertEqual(exit_code, 1)


class TestEditPreservation(EditTestBase):
    def test_cyber_block_preserved(self):
        run(self._args(status="aplicada"), self.vault)
        text = self._read()
        self.assertIn("cyber:", text)
        self.assertIn("outcome: pending", text)
        self.assertIn("review_on: 2026-01-15", text)

    def test_custom_fields_preserved(self):
        custom = FIXTURE.replace("cyber:", "custom_field: valor_extra\ncyber:")
        self.concept.write_text(custom, encoding="utf-8")
        run(self._args(status="aplicada"), self.vault)
        self.assertIn("custom_field: valor_extra", self._read())


class TestEditErrors(EditTestBase):
    def test_not_found(self):
        exit_code = run(self._args(slug="decisions/inexistente"), self.vault)
        self.assertEqual(exit_code, 1)

    def test_empty_description_rejected(self):
        exit_code = run(self._args(description=""), self.vault)
        self.assertEqual(exit_code, 1)

    def test_invalid_frontmatter(self):
        (self.vault / "decisions" / "roto.md").write_text("sin frontmatter\n", encoding="utf-8")
        exit_code = run(self._args(slug="decisions/roto"), self.vault)
        self.assertEqual(exit_code, 1)

    def test_dry_run_does_not_write(self):
        before = self._read()
        exit_code = run(self._args(description="Nueva desc", dry_run=True), self.vault)
        self.assertEqual(exit_code, 0)
        self.assertEqual(before, self._read())

    def test_bare_basename_resolution(self):
        exit_code = run(self._args(slug="decision-base", description="Por basename"), self.vault)
        self.assertEqual(exit_code, 0)
        self.assertIn('description: "Por basename"', self._read())


class TestNewForce(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name)
        (self.vault / "insights").mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _new_args(self, **kwargs):
        defaults = {
            "concept_type": "Insight",
            "title": "Test Insight",
            "description": "A test insight",
            "tags": None,
            "status": None,
            "resource": None,
            "cyber": False,
            "dry_run": False,
            "body": None,
            "body_file": None,
            "links": None,
            "force": False,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_without_force_rejected(self):
        from cli.commands.new import run
        self.assertEqual(run(self._new_args(), self.vault), 0)
        self.assertEqual(run(self._new_args(), self.vault), 1)

    def test_with_force_overwrites(self):
        from cli.commands.new import run
        self.assertEqual(run(self._new_args(), self.vault), 0)
        exit_code = run(self._new_args(description="Overwritten", force=True), self.vault)
        self.assertEqual(exit_code, 0)
        content = (self.vault / "insights" / "test-insight.md").read_text(encoding="utf-8")
        self.assertIn('description: "Overwritten"', content)


if __name__ == "__main__":
    unittest.main()
