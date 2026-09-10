"""Regresión: «vence hoy» no es «vencido» — una sola semántica de fechas.

El off-by-one que arregló #21 en health (``review_on <= hoy`` → ``<``) dejaba
el dashboard contradiciéndose consigo mismo: el agregado
``cibernetica.review_on_vencidos`` contaba los reviews que vencen hoy (vía
``severity == 'required'``) mientras el campo por nodo
``conceptos[].cyber.vencido`` los daba por no vencidos.

Semántica única (fijada 2026-09-10):

- ``review.collect_due()[].vencido``   → ``review_on < hoy``
- ``cibernetica.review_on_vencidos``   → cuántos ya vencieron (loops rotos)
- ``cibernetica.review_on_hoy``        → cuántos vencen hoy (siguen en la lista)
- ``conceptos[].cyber.vencido``        → ``review_on < hoy``
- ``health``                           → loop roto solo si ``review_on < hoy``

La lista de ``review`` sigue devolviendo los que vencen hoy: son tareas de hoy.
``severity`` (required/verify) es ortogonal a ``vencido``: un concepto con
outcome medido y fecha pasada aparece en la lista para re-verificación, pero
sigue contando como vencido.
"""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from cli.commands.dashboard_snapshot import _cibernetica_section, _cyber_por_nodo
from cli.commands.review import collect_due, get_today_str, run


def _fecha(delta_dias=0):
    """Fecha ISO relativa a «hoy» en la zona del dominio (Colombia, UTC-5)."""
    hoy = datetime.strptime(get_today_str(), "%Y-%m-%d")
    return (hoy + timedelta(days=delta_dias)).strftime("%Y-%m-%d")


def _concepto(vault, rel, review_on, outcome="pending"):
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "type: Insight\n"
        'title: "Concepto de prueba"\n'
        'description: "Concepto de prueba para vencimiento de review"\n'
        "cyber:\n"
        '  sensor: "prueba"\n'
        f"  outcome: {outcome}\n"
        f"  review_on: {review_on}\n"
        "---\n\nCuerpo.\n",
        encoding="utf-8",
    )
    return path


class ReviewVencimientoTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _uno(self, review_on, outcome="pending"):
        _concepto(self.vault, "conceptos/prueba.md", review_on, outcome)
        return collect_due(self.vault)[0]

    # ── collect_due ──────────────────────────────────────────────────────

    def test_review_que_vence_hoy_no_esta_vencido(self):
        item = self._uno(_fecha(0))
        self.assertFalse(item["vencido"])
        self.assertEqual(item["review_on"], _fecha(0))

    def test_review_de_ayer_esta_vencido(self):
        self.assertTrue(self._uno(_fecha(-1))["vencido"])

    def test_review_futuro_no_entra_en_la_lista(self):
        _concepto(self.vault, "conceptos/prueba.md", _fecha(1))
        self.assertEqual(collect_due(self.vault), [])

    def test_hoy_sigue_en_la_lista_con_severity_required(self):
        item = self._uno(_fecha(0))
        self.assertEqual(item["severity"], "required")

    def test_severity_y_vencido_son_independientes(self):
        # Outcome ya medido y fecha pasada: se re-verifica, pero está vencido.
        item = self._uno(_fecha(-2), outcome="success")
        self.assertEqual(item["severity"], "verify")
        self.assertTrue(item["vencido"])

    # ── dashboard: agregado vs campo por nodo ────────────────────────────

    def test_cibernetica_no_cuenta_hoy_como_vencido(self):
        _concepto(self.vault, "conceptos/hoy.md", _fecha(0))
        _concepto(self.vault, "conceptos/ayer.md", _fecha(-1))
        ciber = _cibernetica_section(self.vault)
        self.assertEqual(ciber["review_on_vencidos"], 1)
        self.assertEqual(ciber["review_on_hoy"], 1)
        self.assertEqual(ciber["review_on_proximos_7d"], 0)

    def test_agregado_y_flag_por_nodo_coinciden(self):
        for dias in (0, -1, -30):
            _concepto(self.vault, f"conceptos/c{dias}.md", _fecha(dias))
        ciber = _cibernetica_section(self.vault)
        por_nodo = 0
        for path in sorted(self.vault.rglob("conceptos/*.md")):
            fm = _frontmatter(path.read_text(encoding="utf-8"))
            if _cyber_por_nodo(fm, get_today_str())["vencido"]:
                por_nodo += 1
        self.assertEqual(ciber["review_on_vencidos"], por_nodo)
        self.assertEqual(ciber["review_on_vencidos"], 2)

    def test_cyber_por_nodo_no_marca_hoy(self):
        path = _concepto(self.vault, "conceptos/hoy.md", _fecha(0))
        fm = _frontmatter(path.read_text(encoding="utf-8"))
        self.assertFalse(_cyber_por_nodo(fm, get_today_str())["vencido"])

    # ── salida humana ────────────────────────────────────────────────────

    def test_la_lista_marca_los_que_vencen_hoy(self):
        _concepto(self.vault, "conceptos/hoy.md", _fecha(0))
        _concepto(self.vault, "conceptos/ayer.md", _fecha(-1))
        salida = self._run_review()
        self.assertIn("conceptos/hoy.md", salida)
        self.assertIn("vence hoy", salida)
        lineas = [l for l in salida.splitlines() if "Review era:" in l]
        self.assertEqual(len(lineas), 2)
        self.assertEqual(sum("vence hoy" in l for l in lineas), 1)

    def test_json_de_la_lista_expone_vencido(self):
        import json
        _concepto(self.vault, "conceptos/ayer.md", _fecha(-1))
        salida = self._run_review(json_out=True)
        self.assertTrue(json.loads(salida)[0]["vencido"])

    def _run_review(self, json_out=False):
        args = SimpleNamespace(json=json_out, count=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            run(args, self.vault, None)
        return buf.getvalue()


def _frontmatter(text):
    from cli.frontmatter import parse_frontmatter
    fm, _ = parse_frontmatter(text)
    return fm


if __name__ == "__main__":
    unittest.main()
