"""Los nombres de tipo del config de ejemplo deben resolver contra valid_pairs.

`okf.config.example.yaml` se tradujo al inglés (commit 5e26f5d, 29-jul-2026) y
`cli/edge_types.py` quedó en el vocabulario anterior; los pares agregados
después siguieron usándolo. Un vault creado desde el ejemplo declara
Agent / Framework / Criterion / Lesson, que no figuran en ningún valid_pair, así
que todo par que los tocara caía al centinela ("extiende", "BAJA") — que
significa "no tengo sugerencia", no "sugiero extiende".

`TYPE_ALIASES` normaliza el nombre en la entrada. Los nombres canónicos siguen
funcionando: los vaults que ya usan el vocabulario viejo no se rompen.
"""

import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli.edge_types import (resolve_definitions, suggest_edge_type,
                            validate_cross_type_pair)

# TYPE_ALIASES y canonical_type se importan dentro de cada test que los usa: así
# los tests de COMPORTAMIENTO fallan por aserción cuando el fix no está, en vez
# de que el módulo entero reviente con ImportError y no se pruebe nada.

REPO = Path(__file__).resolve().parents[1]

# Tipos del ejemplo que no participan de ningún valid_pair por diseño, no por
# desalineación: System y Tool no tienen vocabulario ontológico definido, y una
# Session referencia los conceptos que se tocaron sin extenderlos, refinarlos,
# fundamentarlos ni aplicarlos.
SIN_VOCABULARIO = {"System", "Tool", "Session"}


def _tipos_del_ejemplo():
    cfg = yaml.safe_load((REPO / "okf.config.example.yaml").read_text(encoding="utf-8"))
    return cfg["types"]["valid"]


class TypeAliasTests(unittest.TestCase):
    def test_cada_alias_infiere_igual_que_su_canonico(self):
        from cli.edge_types import TYPE_ALIASES
        for alias, canonico in TYPE_ALIASES.items():
            for otro in ("Decision", "Plan", "Insight", "Spec"):
                for par_a, par_c in (((alias, otro), (canonico, otro)),
                                     ((otro, alias), (otro, canonico))):
                    with self.subTest(alias=alias, par=par_a):
                        self.assertEqual(suggest_edge_type(*par_a),
                                         suggest_edge_type(*par_c))

    def test_canonical_type_deja_pasar_lo_que_no_es_alias(self):
        from cli.edge_types import canonical_type
        self.assertEqual(canonical_type("Decision"), "Decision")
        self.assertEqual(canonical_type("Framework"), "MarcoTeorico")

    def test_los_nombres_canonicos_siguen_funcionando(self):
        # No romper vaults que usen el vocabulario anterior.
        for par in [("LeccionAprendida", "Insight"), ("Criterio", "Decision"),
                    ("MarcoTeorico", "Decision"), ("Agente", "Skill")]:
            with self.subTest(par=par):
                self.assertNotEqual(suggest_edge_type(*par)[1], "BAJA")

    def test_ningun_tipo_del_ejemplo_queda_huerfano_por_nombre(self):
        """Todo tipo del ejemplo resuelve, salvo los que no tienen vocabulario."""
        from cli.edge_types import canonical_type
        defs = resolve_definitions(None)
        en_tabla = {t for d in defs.values() for p in d.get("valid_pairs", []) for t in p}
        huerfanos = {t for t in _tipos_del_ejemplo()
                     if canonical_type(t) not in en_tabla} - SIN_VOCABULARIO
        self.assertEqual(huerfanos, set())

    def test_validate_no_marca_atipico_un_par_valido_escrito_en_ingles(self):
        # Antes: "Par atípico: 'Lesson' refina 'Insight'" — falso, es un par válido.
        self.assertEqual(validate_cross_type_pair("Lesson", "Insight", "refina"), [])
        self.assertEqual(validate_cross_type_pair("Framework", "Decision", "fundamenta"), [])

    def test_el_recall_del_ejemplo_no_retrocede(self):
        """Cota inferior medida: con los alias, 26 de los 225 pares infieren."""
        tipos = _tipos_del_ejemplo()
        con_sugerencia = sum(1 for a in tipos for b in tipos
                             if suggest_edge_type(a, b)[1] != "BAJA")
        self.assertGreaterEqual(con_sugerencia, 26)


if __name__ == "__main__":
    unittest.main()
