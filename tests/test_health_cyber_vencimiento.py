"""Regresión: health no marca como loop roto un review que vence hoy.

dashboard_snapshot define «vencido» como review_on < hoy, pero health usaba
review_on <= hoy: un concepto con outcome pending y review_on igual a hoy salía
como «expired — broken loop». Con el hook del vault corriendo health --strict,
eso rechazaba todos los commits desde las 00:00 del mismo día del review.
"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _fecha_colombia(delta_dias=0):
    # Misma referencia que health: Colombia, UTC-5.
    return (datetime.now(timezone.utc) - timedelta(hours=5)
            + timedelta(days=delta_dias)).strftime("%Y-%m-%d")


def _concepto(review_on, outcome="pending"):
    return (
        "---\n"
        "type: Insight\n"
        'title: "Prueba"\n'
        'description: "Concepto de prueba"\n'
        "cyber:\n"
        '  sensor: "prueba"\n'
        f"  outcome: {outcome}\n"
        f"  review_on: {review_on}\n"
        "---\n\nCuerpo.\n"
    )


class HealthCyberVencimientoTest(unittest.TestCase):

    def _errores(self, review_on, outcome="pending"):
        from cli.commands.health import _check_cyber
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / "insights").mkdir()
            (vault / "insights" / "prueba.md").write_text(
                _concepto(review_on, outcome), encoding="utf-8")
            _ok, _warnings, errores = _check_cyber(vault)
            return errores

    def test_review_que_vence_hoy_no_es_loop_roto(self):
        self.assertEqual(self._errores(_fecha_colombia(0)), [])

    def test_review_de_ayer_es_loop_roto(self):
        errores = self._errores(_fecha_colombia(-1))
        self.assertEqual(len(errores), 1)
        self.assertIn("broken loop", errores[0])

    def test_review_de_manana_no_es_loop_roto(self):
        self.assertEqual(self._errores(_fecha_colombia(1)), [])

    def test_loop_cerrado_con_fecha_pasada_no_es_error(self):
        self.assertEqual(self._errores(_fecha_colombia(-3), outcome="success"), [])


if __name__ == "__main__":
    unittest.main()
