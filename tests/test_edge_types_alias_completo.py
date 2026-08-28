"""La normalización de alias tiene que alcanzar los dos lados de la comparación.

El PR #7 introdujo `TYPE_ALIASES` y normalizó la consulta en `suggest_edge_type`
y `validate_cross_type_pair`, pero dejó dos huecos:

1. `score_edge` compara contra los mismos `valid_pairs` y no normalizaba. La
   señal "structural fit" pesa 0.40, así que la misma arista con idéntico
   contenido puntuaba 0.45 escrita en inglés y 0.85 en español. Como
   `--min-score` filtra por ese número, un vault en inglés quedaba
   sistemáticamente por debajo del umbral.

2. Solo se normalizaba la consulta, no los pares. Un vault que declarara sus
   propios `valid_pairs` con el vocabulario del config de ejemplo se quedaba sin
   matchearlos nunca: la consulta se convertía a canónico y el par declarado
   seguía en inglés.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli.edge_types import resolve_definitions, score_edge, suggest_edge_type

# Mismo contenido en ambos lados: la única variable es el nombre del tipo.
TAGS = ["x"]
DESC = "misma cosa"

EQUIVALENCIAS = [
    (("Lesson", "Insight", "refina"), ("LeccionAprendida", "Insight", "refina")),
    (("Framework", "Decision", "fundamenta"), ("MarcoTeorico", "Decision", "fundamenta")),
    (("Criterion", "Decision", "refina"), ("Criterio", "Decision", "refina")),
    (("Agent", "Skill", "depende"), ("Agente", "Skill", "depende")),
]


def _score(source, target, edge):
    return score_edge(source, target, edge, TAGS, TAGS, DESC, DESC, 0.0)


class ScoreEdgeAliasTests(unittest.TestCase):
    def test_el_score_no_depende_del_idioma_del_nombre(self):
        for en, es in EQUIVALENCIAS:
            with self.subTest(par=en):
                self.assertAlmostEqual(_score(*en), _score(*es), places=6)

    def test_el_alias_conserva_el_structural_fit(self):
        """La señal vale 0.40; sin normalizar, el alias la perdía entera."""
        for en, _ in EQUIVALENCIAS:
            with self.subTest(par=en):
                self.assertGreaterEqual(
                    _score(*en), 0.40,
                    f"{en} perdio el structural fit por el nombre del tipo",
                )


class OverridesDelVaultTests(unittest.TestCase):
    def test_un_par_declarado_por_el_vault_en_ingles_resuelve(self):
        overrides = {"refina": {"valid_pairs": [["Lesson", "Workflow"]]}}
        _, confianza = suggest_edge_type("Lesson", "Workflow", definitions=overrides)
        self.assertNotEqual(
            confianza, "BAJA",
            "el par declarado por el vault no matchea: se normalizo la consulta "
            "pero no los pares",
        )

    def test_un_par_declarado_en_canonico_sigue_resolviendo(self):
        overrides = {"refina": {"valid_pairs": [["LeccionAprendida", "Workflow"]]}}
        _, confianza = suggest_edge_type("Lesson", "Workflow", definitions=overrides)
        self.assertNotEqual(confianza, "BAJA")

    def test_resolve_definitions_no_muta_el_dict_recibido(self):
        overrides = {"refina": {"valid_pairs": [["Lesson", "Workflow"]]}}
        antes = [list(p) for p in overrides["refina"]["valid_pairs"]]
        resolve_definitions(overrides)
        self.assertEqual(
            [list(p) for p in overrides["refina"]["valid_pairs"]], antes,
            "resolve_definitions modifico la config que le pasaron",
        )

    def test_sin_overrides_devuelve_los_defaults_intactos(self):
        from cli.edge_types import EDGE_TYPE_DEFINITIONS
        self.assertIs(resolve_definitions(None), EDGE_TYPE_DEFINITIONS)


if __name__ == "__main__":
    unittest.main()
