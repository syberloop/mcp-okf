"""Tests de campos custom en edit.py (--field key=value).

Necesarios para el type Handoff: los checkpoints incrementales actualizan
repo_state.commit, next_session_at, state, session_id, etc.
"""

import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

from cli.commands.edit import _parse_field_value, _set_dotted, run, _split


class TestParseFieldValue(unittest.TestCase):
    def test_string_plano(self):
        self.assertEqual(_parse_field_value("abc123"), "abc123")

    def test_bool(self):
        self.assertEqual(_parse_field_value("true"), True)
        self.assertEqual(_parse_field_value("false"), False)

    def test_int(self):
        self.assertEqual(_parse_field_value("42"), 42)

    def test_json_list(self):
        self.assertEqual(_parse_field_value('["a.py", "b.py"]'), ["a.py", "b.py"])

    def test_vacio_es_none(self):
        self.assertIsNone(_parse_field_value(""))


class TestSetDotted(unittest.TestCase):
    def test_crea_dict_anidado(self):
        fields = {}
        _set_dotted(fields, "repo_state.commit", "abc", [])
        self.assertEqual(fields["repo_state"]["commit"], "abc")

    def test_actualiza_existente(self):
        fields = {"repo_state": {"commit": "old"}}
        changed = []
        _set_dotted(fields, "repo_state.commit", "new", changed)
        self.assertEqual(fields["repo_state"]["commit"], "new")
        self.assertIn("repo_state.commit", changed)

    def test_vacio_borra(self):
        fields = {"next_session_at": "2026-09-01"}
        changed = []
        _set_dotted(fields, "next_session_at", None, changed)
        self.assertNotIn("next_session_at", fields)
        self.assertIn("next_session_at", changed)


class TestEditRunFields(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name)
        (self.vault / "handoffs").mkdir()
        self.handoff = self.vault / "handoffs" / "test-handoff.md"
        self.handoff.write_text("""---
type: Handoff
title: "Test Handoff"
description: "Un handoff"
status: pending
timestamp: 2026-08-31T10:00:00-05:00
created: 2026-08-31T10:00:00-05:00
session_id: ""
repo_state:
  commit: ""
---

## Contexto

Test
""")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _args(self, **kwargs):
        defaults = {
            "slug": "handoffs/test-handoff",
            "title": None, "description": None, "tags": None,
            "status": None, "resource": None, "body": None,
            "body_file": None, "links": None, "clear_links": False,
            "fields": None, "dry_run": False,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_set_anidado_y_serializa(self):
        args = self._args(fields=[
            "repo_state.commit=abc123",
            "next_session_at=2026-09-01T09:00:00-05:00",
            "session_id=default/2026-08-31",
        ])
        exit_code = run(args, self.vault)
        self.assertEqual(exit_code, 0)
        text = self.handoff.read_text(encoding="utf-8")
        self.assertIn("commit: abc123", text)
        self.assertIn("next_session_at: 2026-09-01T09:00:00-05:00", text)
        # re-parseable y campos no tocados preservados
        fields, _ = _split(text)
        self.assertEqual(fields["repo_state"]["commit"], "abc123")
        self.assertEqual(fields["status"], "pending")

    def test_lista_json(self):
        args = self._args(fields=['files_modified=["a.py", "b.py"]'])
        exit_code = run(args, self.vault)
        self.assertEqual(exit_code, 0)
        fields, _ = _split(self.handoff.read_text(encoding="utf-8"))
        self.assertEqual(fields["files_modified"], ["a.py", "b.py"])

    def test_vacio_borra_campo(self):
        args = self._args(fields=["session_id="])
        exit_code = run(args, self.vault)
        self.assertEqual(exit_code, 0)
        fields, _ = _split(self.handoff.read_text(encoding="utf-8"))
        self.assertNotIn("session_id", fields)

    def test_field_invalido_error(self):
        args = self._args(fields=["sinigual"])
        exit_code = run(args, self.vault)
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
