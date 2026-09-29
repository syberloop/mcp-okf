"""Validación 10: un bloque `cyber:` en el cuerpo es un error.

Contexto (2026-09-25): el cron Cyber Review tiene la instrucción «Actualizar
cyber block con patch». El agente la interpretó literal: escribió el reporte
en el cuerpo y pegó el YAML `cyber:` al final del cuerpo, dejando el
frontmatter intacto con `outcome: pending` y el `review_on` viejo. El loop
seguía contando como roto en `health` mientras el reporte decía success/failure,
y el vault acumulaba YAML mal formado. En un caso (criterios-falsifiables...)
el bloque estaba SOLO en el cuerpo: invisible para health, review y dashboard.

El bloque cyber vive en el frontmatter (OKF v0.1). Estos tests fijan el guard
que lo hace cumplir en el pre-commit.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli.commands.validate import _check_cyber_block_in_body, _validate_file

FM = (
    "---\n"
    "type: Decision\n"
    'title: "Test"\n'
    'description: "Descripcion de prueba suficientemente larga"\n'
    'timestamp: "2026-09-27T10:00:00-05:00"\n'
    "---\n"
)

REAL_SHAPE = """
## Revisión cibernética 2026-09-25
| Campo | Valor |
|---|---|
| **Outcome** | success |
**Conclusión**: Target cumplido.

---

cyber:
  outcome: success
  measured_at: 2026-09-25
  review_on: 2026-10-25
"""


class CyberBlockInBodyUnitTests(unittest.TestCase):
    def test_column_zero_block_is_detected(self):
        errs = _check_cyber_block_in_body(REAL_SHAPE, "x.md")
        self.assertEqual(len(errs), 1)
        self.assertIn("cyber:", errs[0])
        self.assertIn("FRONTMATTER", errs[0])

    def test_trailing_spaces_still_detected(self):
        errs = _check_cyber_block_in_body("\ntext\n\ncyber:   \n  outcome: x\n", "x.md")
        self.assertEqual(len(errs), 1)

    def test_fenced_code_block_is_ignored(self):
        body = "Ejemplo del formato:\n\n```\ncyber:\n  outcome: pending\n```\n"
        self.assertEqual(_check_cyber_block_in_body(body, "x.md"), [])

    def test_indented_example_is_ignored(self):
        body = "En el frontmatter va así:\n\n    cyber:\n      outcome: pending\n"
        self.assertEqual(_check_cyber_block_in_body(body, "x.md"), [])

    def test_inline_mention_is_ignored(self):
        body = "El campo `cyber.review_on` decide el vencimiento.\ncyber.review_on: 2026-10-01\n"
        self.assertEqual(_check_cyber_block_in_body(body, "x.md"), [])

    def test_clean_body_passes(self):
        self.assertEqual(_check_cyber_block_in_body("## Sección\n\ntexto normal\n", "x.md"), [])

    def test_detects_multiple_blocks(self):
        errs = _check_cyber_block_in_body("cyber:\n  outcome: a\n\ntexto\n\ncyber:\n  outcome: b\n", "x.md")
        self.assertEqual(len(errs), 2)


class ValidateFileIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, body, rel="decisions/test.md"):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(FM + body, encoding="utf-8")
        return p

    def test_file_with_stray_block_fails(self):
        p = self._write(REAL_SHAPE)
        ok, msg = _validate_file(p, self.vault)
        self.assertFalse(ok)
        self.assertIn("cyber:", msg)
        self.assertIn("belongs in frontmatter", msg)

    def test_file_without_stray_block_passes(self):
        p = self._write("## Sección\n\ncontenido\n")
        ok, msg = _validate_file(p, self.vault)
        self.assertTrue(ok, msg)

    def test_block_in_code_fence_passes(self):
        p = self._write("Formato:\n\n```yaml\ncyber:\n  outcome: pending\n```\n")
        ok, msg = _validate_file(p, self.vault)
        self.assertTrue(ok, msg)


if __name__ == "__main__":
    unittest.main()