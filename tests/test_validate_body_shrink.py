"""Validación 11: el body no puede perder la mayor parte de su contenido.

Caso real (2026-09-29, 12:29): una corrida del cron Cyber Review resolvió dos
conceptos. En uno actualizó bien el frontmatter pero reescribió el BODY COMPLETO
en vez de anexar su reporte: borró 111 líneas (Contexto/Decisión/Impacto de una
decisión) y dejó solo su sección. El commit pasó sin objeción y la pérdida se
detectó a mano minutos después.

Nada comparaba el body nuevo con el anterior, así que el guard de runtime vive
en el commit: si un body con >= 20 líneas con contenido conserva menos del 60%,
se rechaza.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli.commands.validate import (
    _body_line_count,
    _check_body_shrink,
    _strip_frontmatter,
    _validate_file,
)

FM = (
    "---\n"
    "type: Decision\n"
    'title: "Test"\n'
    'description: "Descripcion de prueba suficientemente larga"\n'
    'timestamp: "2026-09-27T10:00:00-05:00"\n'
    "---\n"
)

BODY_LONG = "\n".join(f"Línea de contenido {i}" for i in range(1, 41)) + "\n"
BODY_TINY = "Solo el reporte\nSegunda línea\n"


class GitVaultFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        (self.vault / "decisions").mkdir()
        self.rel = "decisions/test.md"
        self.file = self.vault / self.rel
        self.file.write_text(FM + "\n" + BODY_LONG, encoding="utf-8")
        self._git("init", "-q")
        self._git("config", "user.email", "t@t.t")
        self._git("config", "user.name", "t")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def _git(self, *args):
        return subprocess.run(["git", "-C", str(self.vault), *args],
                              capture_output=True, text=True)

    def _rewrite_body(self, body):
        self.file.write_text(FM + "\n" + body, encoding="utf-8")


class BodyShrinkUnitTests(GitVaultFixture):
    def test_line_count_ignores_blanks(self):
        self.assertEqual(_body_line_count("a\n\n  \nb\n"), 2)

    def test_strip_frontmatter(self):
        self.assertEqual(_body_line_count(_strip_frontmatter(FM + "\n" + BODY_LONG)), 40)

    def test_truncated_body_is_rejected(self):
        err = _check_body_shrink(self.file, self.vault, "\n" + BODY_TINY, self.rel)
        self.assertIsNotNone(err)
        self.assertIn("body shrink", err)
        self.assertIn("40 → 2", err)

    def test_append_is_allowed(self):
        body = "\n" + BODY_LONG + "\n## Revisión cibernética 2026-09-29\ncontenido\n"
        self.assertIsNone(_check_body_shrink(self.file, self.vault, body, self.rel))

    def test_small_trim_is_allowed(self):
        trimmed = "\n" + "\n".join(BODY_LONG.split("\n")[:30]) + "\n"
        self.assertIsNone(_check_body_shrink(self.file, self.vault, trimmed, self.rel))

    def test_short_bodies_are_exempt(self):
        # Un body de 10 líneas no tiene "contenido que perder" según el umbral.
        self.file.write_text(FM + "\n" + "a\nb\nc\nd\ne\nf\ng\nh\ni\nj\n",
                             encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "corto")
        self.assertIsNone(_check_body_shrink(self.file, self.vault, "\nz\n", self.rel))

    def test_new_file_is_exempt(self):
        nuevo = self.vault / "decisions/nuevo.md"
        nuevo.write_text(FM + "\n" + BODY_TINY, encoding="utf-8")
        self.assertIsNone(
            _check_body_shrink(nuevo, self.vault, "\n" + BODY_TINY, "decisions/nuevo.md"))

    def test_non_git_vault_is_exempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp)
            f = plain / "x.md"
            f.write_text(FM + "\n" + BODY_LONG, encoding="utf-8")
            self.assertIsNone(_check_body_shrink(f, plain, "\n" + BODY_TINY, "x.md"))


class BodyShrinkIntegrationTests(GitVaultFixture):
    def test_validate_file_rejects_truncated_body(self):
        self._rewrite_body("\n" + BODY_TINY)
        ok, msg = _validate_file(self.file, self.vault)
        self.assertFalse(ok)
        self.assertIn("body shrink", msg)

    def test_validate_file_accepts_append(self):
        self._rewrite_body(
            "\n" + BODY_LONG + "\n## Revisión cibernética 2026-09-29\nEvidencia: ok\n")
        ok, msg = _validate_file(self.file, self.vault)
        self.assertTrue(ok, msg)

    def test_real_incident_shape_is_caught(self):
        """La forma exacta del incidente: frontmatter nuevo + body = reporte."""
        report_only = (
            "\n## Revisión cibernética 2026-09-29\n"
            "| Campo | Valor |\n|---|---|\n| **Outcome** | failure |\n"
            "**Evidencia**: grep → 0 hits\n**Conclusión**: quinto ciclo.\n"
        )
        self._rewrite_body(report_only)
        ok, msg = _validate_file(self.file, self.vault)
        self.assertFalse(ok)
        self.assertIn("body shrink", msg)


if __name__ == "__main__":
    unittest.main()