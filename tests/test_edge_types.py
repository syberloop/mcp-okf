"""Tests para cli.edge_types — definiciones formales y validación de aristas."""

import unittest
from cli.edge_types import (
    VALID_EDGE_TYPES,
    suggest_edge_type,
    validate_cross_type_pair,
)


class TestValidEdgeTypes(unittest.TestCase):
    def test_six_types_defined(self):
        self.assertEqual(len(VALID_EDGE_TYPES), 6)
        expected = {"extiende", "refina", "fundamenta", "aplica", "depende", "corrige"}
        self.assertEqual(VALID_EDGE_TYPES, expected)

    def test_frozenset_is_immutable(self):
        # frozenset no tiene add — intentar usar add lanza AttributeError
        with self.assertRaises(AttributeError):
            VALID_EDGE_TYPES.add("inventado")  # type: ignore


class TestSuggestEdgeType(unittest.TestCase):
    def test_known_pair_returns_alta(self):
        etype, conf = suggest_edge_type("Insight", "MarcoTeorico")
        self.assertEqual(etype, "extiende")
        self.assertEqual(conf, "ALTA")

    def test_unknown_pair_returns_baja(self):
        etype, conf = suggest_edge_type("Sesion", "Mapa")
        self.assertEqual(etype, "extiende")
        self.assertEqual(conf, "BAJA")

    def test_decision_criterio_returns_refina_or_aplica(self):
        # (Decision, Criterio) coincide con refina y aplica → MEDIA
        etype, conf = suggest_edge_type("Decision", "Criterio")
        self.assertIn(etype, ["refina", "aplica"])
        self.assertEqual(conf, "MEDIA")

    def test_plan_decision_returns_aplica(self):
        etype, conf = suggest_edge_type("Plan", "Decision")
        self.assertEqual(etype, "aplica")
        self.assertEqual(conf, "ALTA")

    def test_marcoteorico_decision_returns_fundamenta(self):
        etype, conf = suggest_edge_type("MarcoTeorico", "Decision")
        self.assertEqual(etype, "fundamenta")
        self.assertEqual(conf, "ALTA")

    def test_agente_skill_returns_depende(self):
        etype, conf = suggest_edge_type("Agente", "Skill")
        self.assertEqual(etype, "depende")
        self.assertEqual(conf, "ALTA")


class TestValidateCrossTypePair(unittest.TestCase):
    def test_valid_pair_no_warnings(self):
        warnings = validate_cross_type_pair("Insight", "MarcoTeorico", "extiende")
        self.assertEqual(warnings, [])

    def test_atipico_returns_warning(self):
        warnings = validate_cross_type_pair("Sesion", "Mapa", "extiende")
        self.assertTrue(len(warnings) > 0)
        self.assertIn("atípico", warnings[0].lower())

    def test_corrige_any_pair_no_warnings(self):
        warnings = validate_cross_type_pair("Sesion", "Mapa", "corrige")
        self.assertEqual(warnings, [])

    def test_corrige_any_pair_2(self):
        warnings = validate_cross_type_pair("Insight", "Sesion", "corrige")
        self.assertEqual(warnings, [])

    def test_unknown_edge_type_warns(self):
        warnings = validate_cross_type_pair("A", "B", "nonexistent")
        self.assertTrue(len(warnings) > 0)
        self.assertIn("desconocido", warnings[0].lower())

    def test_refina_insight_insight_valid(self):
        warnings = validate_cross_type_pair("Insight", "Insight", "refina")
        self.assertEqual(warnings, [])

    def test_extiende_spec_spec_valid(self):
        warnings = validate_cross_type_pair("Spec", "Spec", "extiende")
        self.assertEqual(warnings, [])

    def test_sugiere_alternativa_cuando_existe(self):
        # Decision → MarcoTeorico con 'extiende' es atípico
        # pero MarcoTeorico → Decision es 'fundamenta'
        warnings = validate_cross_type_pair("Decision", "MarcoTeorico", "extiende")
        self.assertTrue(len(warnings) > 0)


if __name__ == "__main__":
    unittest.main()
