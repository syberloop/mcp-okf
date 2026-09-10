"""Tests de las listas por nodo de la sección cibernetica del snapshot.

El plugin cognitive-trace (dashboard_view.buildCyberNodes) colorea cuatro capas
del grafo con listas opcionales que el CLI nunca emitía, así que la capa Cyber
quedaba vacía en silencio:

  review_on_vencidos_nodes, outcome_pending_nodes,
  outcome_success_nodes, outcome_failure_nodes

Estos tests fijan el contrato: una entrada por nodo con bloque cyber, en el
formato de identificador de conceptos[].file (ruta relativa sin ``.md``), y
cada lista consistente con su contador.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from cli.commands.dashboard_snapshot import _cibernetica_section, run
from cli.commands.review import get_today_str


def _fecha(delta_dias=0):
    hoy = datetime.strptime(get_today_str(), "%Y-%m-%d")
    return (hoy + timedelta(days=delta_dias)).strftime("%Y-%m-%d")


def _concepto(vault, rel, outcome=None, review_on=None):
    """Concepto con bloque cyber; sin outcome no escribe el bloque."""
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = [
        "---",
        "type: Insight",
        'title: "Concepto de prueba"',
        'description: "Concepto de prueba para listas cyber del snapshot"',
    ]
    if outcome or review_on:
        fm.append("cyber:")
        fm.append('  sensor: "prueba"')
        if outcome:
            fm.append(f"  outcome: {outcome}")
        if review_on:
            fm.append(f"  review_on: {review_on}")
    fm.append("---")
    path.write_text("\n".join(fm) + "\n\nCuerpo.\n", encoding="utf-8")
    return path


class CyberNodesTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_las_cuatro_listas_se_emiten_vacias_sin_cyber(self):
        _concepto(self.vault, "conceptos/sin-cyber.md")
        ciber = _cibernetica_section(self.vault)
        for clave in ("review_on_vencidos_nodes", "outcome_pending_nodes",
                      "outcome_success_nodes", "outcome_failure_nodes"):
            self.assertEqual(ciber[clave], [], clave)

    def test_outcomes_por_nodo_coinciden_con_sus_contadores(self):
        _concepto(self.vault, "conceptos/pend.md", outcome="pending")
        _concepto(self.vault, "conceptos/ok.md", outcome="success")
        _concepto(self.vault, "conceptos/mal.md", outcome="failure")
        _concepto(self.vault, "decisiones/tambien-ok.md", outcome="success")
        ciber = _cibernetica_section(self.vault)
        self.assertEqual(ciber["outcome_pending"], 1)
        self.assertEqual(ciber["outcome_success"], 2)
        self.assertEqual(ciber["outcome_failure"], 1)
        self.assertEqual(ciber["outcome_pending_nodes"], ["conceptos/pend"])
        self.assertEqual(ciber["outcome_success_nodes"],
                         ["conceptos/ok", "decisiones/tambien-ok"])
        self.assertEqual(ciber["outcome_failure_nodes"], ["conceptos/mal"])

    def test_vencidos_nodes_solo_los_ya_vencidos(self):
        _concepto(self.vault, "conceptos/ayer.md", outcome="pending",
                  review_on=_fecha(-1))
        _concepto(self.vault, "conceptos/hoy.md", outcome="pending",
                  review_on=_fecha(0))
        _concepto(self.vault, "conceptos/manana.md", outcome="pending",
                  review_on=_fecha(1))
        ciber = _cibernetica_section(self.vault)
        self.assertEqual(ciber["review_on_vencidos_nodes"], ["conceptos/ayer"])
        self.assertEqual(ciber["review_on_vencidos"], 1)

    def test_un_loop_cerrado_con_fecha_pasada_tambien_vencio(self):
        _concepto(self.vault, "conceptos/medido.md", outcome="success",
                  review_on=_fecha(-5))
        ciber = _cibernetica_section(self.vault)
        self.assertEqual(ciber["review_on_vencidos_nodes"], ["conceptos/medido"])
        self.assertEqual(ciber["outcome_success_nodes"], ["conceptos/medido"])

    def test_identificador_sin_extension_igual_que_conceptos_file(self):
        _concepto(self.vault, "decisiones/con-extension.md", outcome="pending")
        ciber = _cibernetica_section(self.vault)
        self.assertEqual(ciber["outcome_pending_nodes"],
                         ["decisiones/con-extension"])
        self.assertNotIn(".md", "".join(ciber["outcome_pending_nodes"]))

    def test_el_snapshot_escrito_trae_las_listas(self):
        _concepto(self.vault, "conceptos/pend.md", outcome="pending")
        _concepto(self.vault, "conceptos/ayer.md", outcome="pending",
                  review_on=_fecha(-1))
        args = SimpleNamespace(db="/nonexistent/events.db", source="test",
                               canvas=False)
        run(args, self.vault, None)
        snap = json.loads((self.vault / "dashboard.json").read_text(
            encoding="utf-8"))
        ciber = snap["cibernetica"]
        self.assertEqual(ciber["outcome_pending_nodes"],
                         ["conceptos/ayer", "conceptos/pend"])
        self.assertEqual(ciber["review_on_vencidos_nodes"], ["conceptos/ayer"])
        self.assertEqual(len(ciber["outcome_success_nodes"]), 0)


if __name__ == "__main__":
    unittest.main()
