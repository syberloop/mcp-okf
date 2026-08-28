"""Tests de touch.py — deprecación del modo incremento (v0.4.1)."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cli.commands.touch import run
from cli.reads_store import get_reads


class TouchTestBase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name)
        (self.vault / "insights").mkdir()
        self.concept = self.vault / "insights" / "test.md"
        self.concept.write_text("""---
type: Insight
title: "Test"
description: "test"
---
""", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _args(self, all_=False, target=None):
        return SimpleNamespace(all=all_, target=target)

    def _capture(self, fn):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            exit_code = fn()
        return exit_code, out.getvalue(), err.getvalue()


class TestTouchIncrementDeprecated(TouchTestBase):
    def test_target_mode_is_noop_with_warning(self):
        exit_code, out, err = self._capture(lambda: run(self._args(target="test"), self.vault))
        self.assertEqual(exit_code, 0)
        self.assertIn("deprecado", err)
        self.assertIn("no incrementó nada", err)
        # El store NO cambió: el contador sigue en 0
        self.assertEqual(get_reads(self.vault).get("insights/test.md", 0), 0)

    def test_target_mode_does_not_require_existing_file(self):
        # No-op: ni siquiera valida que el target exista
        exit_code, _, err = self._capture(lambda: run(self._args(target="no-existe"), self.vault))
        self.assertEqual(exit_code, 0)
        self.assertIn("deprecado", err)


class TestTouchAllStats(TouchTestBase):
    def test_all_mode_shows_table(self):
        exit_code, out, _ = self._capture(lambda: run(self._args(all_=True), self.vault))
        self.assertEqual(exit_code, 0)
        self.assertIn("READS", out)
        self.assertIn("TOTAL", out)

    def test_no_target_without_all_usage_error(self):
        exit_code, _, err = self._capture(lambda: run(self._args(), self.vault))
        self.assertEqual(exit_code, 1)
        self.assertIn("Usage", err)


if __name__ == "__main__":
    unittest.main()
