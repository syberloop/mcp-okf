"""Tests de la semántica configurable del vocabulario de aristas (decisión 2026-08-10).

Cubre:
- Config.edge_type_definitions(): valid_pairs del config se UNEN a los defaults
  (no reemplazan), un edge_type nuevo entra completo.
- suggest_edge_type / validate_cross_type_pair con definitions del config.
- Fallback sin config: comportamiento idéntico a los defaults embebidos.
- types_by_entity: con y sin config.
"""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from cli.config import Config
from cli.edge_types import (
    EDGE_TYPE_DEFINITIONS,
    suggest_edge_type,
    validate_cross_type_pair,
)
from cli.commands.new import run as new_run


def _write_yaml(data: dict) -> str:
    """Escribe un config YAML temporal y devuelve su ruta."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)
    return path


# Replica del config real del vault (visto en OKF-Vault/.okf.config.yaml)
VAULT_CONFIG_EDGE_TYPES = {
    "types": {
        "valid": ["Cliente", "Insight", "Plan", "Decision", "Workflow"],
        "by_entity": ["Cliente"],
        "directory": {
            "Cliente": "clientes",
            "Insight": "insights",
            "Plan": "plans",
            "Decision": "decisions",
            "Workflow": "workflows",
        },
    },
    "edge_types": {
        "aplica": {
            "valid_pairs": [["Cliente", "Plan"], ["Decision", "Workflow"]],
        },
        "refina": {
            "valid_pairs": [["Decision", "Decision"]],
        },
    },
}


class TestEdgeTypeDefinitionsFromConfig(unittest.TestCase):
    """Unión de valid_pairs: el config agrega, no reemplaza."""

    def setUp(self):
        self.config_path = _write_yaml(VAULT_CONFIG_EDGE_TYPES)
        self.vault = Path(tempfile.mkdtemp())
        self.config = Config(self.vault, cli_config_arg=self.config_path)

    def tearDown(self):
        os.unlink(self.config_path)

    def test_union_adds_pairs_not_replaces(self):
        defs = self.config.edge_type_definitions()
        pairs = [tuple(p) for p in defs["aplica"]["valid_pairs"]]
        # Defaults siguen presentes
        self.assertIn(("Plan", "Decision"), pairs)
        self.assertIn(("Workflow", "Spec"), pairs)
        # Pares del config agregados
        self.assertIn(("Cliente", "Plan"), pairs)
        self.assertIn(("Decision", "Workflow"), pairs)

    def test_union_preserves_all_default_types(self):
        defs = self.config.edge_type_definitions()
        self.assertEqual(set(defs.keys()), set(EDGE_TYPE_DEFINITIONS.keys()))

    def test_config_pair_validates_without_warnings(self):
        defs = self.config.edge_type_definitions()
        warnings = validate_cross_type_pair(
            "Cliente", "Plan", "aplica", definitions=defs)
        self.assertEqual(warnings, [])

    def test_suggest_edge_type_honors_config_pair(self):
        defs = self.config.edge_type_definitions()
        etype, conf = suggest_edge_type("Cliente", "Plan", definitions=defs)
        self.assertEqual(etype, "aplica")
        self.assertEqual(conf, "ALTA")

    def test_default_pair_still_suggested_high(self):
        defs = self.config.edge_type_definitions()
        etype, conf = suggest_edge_type("Plan", "Decision", definitions=defs)
        self.assertEqual(etype, "aplica")
        self.assertEqual(conf, "ALTA")

    def test_refina_decision_decision_from_config(self):
        defs = self.config.edge_type_definitions()
        warnings = validate_cross_type_pair(
            "Decision", "Decision", "refina", definitions=defs)
        self.assertEqual(warnings, [])


class TestNewEdgeTypeFromConfig(unittest.TestCase):
    """Un edge_type nuevo declarado en config entra completo."""

    def setUp(self):
        self.config_path = _write_yaml({
            "edge_types": {
                "conecta": {
                    "description": "A conecta B en la red de conocimiento",
                    "transitive": False,
                    "valid_pairs": [["Sesion", "Insight"]],
                },
            },
        })
        self.vault = Path(tempfile.mkdtemp())
        self.config = Config(self.vault, cli_config_arg=self.config_path)

    def tearDown(self):
        os.unlink(self.config_path)

    def test_new_edge_type_present_in_definitions(self):
        defs = self.config.edge_type_definitions()
        self.assertIn("conecta", defs)
        self.assertEqual(defs["conecta"]["description"],
                         "A conecta B en la red de conocimiento")
        self.assertEqual(defs["conecta"]["valid_pairs"], [("Sesion", "Insight")])

    def test_new_edge_type_validates(self):
        defs = self.config.edge_type_definitions()
        warnings = validate_cross_type_pair(
            "Sesion", "Insight", "conecta", definitions=defs)
        self.assertEqual(warnings, [])

    def test_new_edge_type_suggested(self):
        defs = self.config.edge_type_definitions()
        etype, conf = suggest_edge_type("Sesion", "Insight", definitions=defs)
        self.assertEqual(etype, "conecta")
        self.assertEqual(conf, "ALTA")


class TestFallbackWithoutConfig(unittest.TestCase):
    """Sin config: los defaults embebidos son idénticos al comportamiento previo."""

    def test_edge_type_definitions_returns_defaults(self):
        vault = Path(tempfile.mkdtemp())
        config = Config(vault)
        defs = config.edge_type_definitions()
        self.assertEqual(defs, EDGE_TYPE_DEFINITIONS)

    def test_types_by_entity_empty_without_config(self):
        vault = Path(tempfile.mkdtemp())
        config = Config(vault)
        self.assertEqual(config.types_by_entity, set())

    def test_validate_default_pair_unchanged(self):
        defs = Config(Path(tempfile.mkdtemp())).edge_type_definitions()
        warnings = validate_cross_type_pair(
            "Insight", "MarcoTeorico", "extiende", definitions=defs)
        self.assertEqual(warnings, [])

    def test_resolve_definitions_none_returns_defaults(self):
        from cli.edge_types import resolve_definitions
        self.assertIs(resolve_definitions(None), EDGE_TYPE_DEFINITIONS)


class TestTypesByEntity(unittest.TestCase):
    """types.by_entity controla el subdirectorio por entidad."""

    def test_by_entity_read_from_config(self):
        config_path = _write_yaml({"types": {"by_entity": ["Cliente"]}})
        try:
            config = Config(Path(tempfile.mkdtemp()), cli_config_arg=config_path)
            self.assertEqual(config.types_by_entity, {"Cliente"})
        finally:
            os.unlink(config_path)

    def test_by_entity_default_empty(self):
        config_path = _write_yaml({"types": {}})
        try:
            config = Config(Path(tempfile.mkdtemp()), cli_config_arg=config_path)
            self.assertEqual(config.types_by_entity, set())
        finally:
            os.unlink(config_path)


class TestNewRunByEntity(unittest.TestCase):
    """Integración: new --type Cliente --entity <x> → clientes/<x>/<slug>.md."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        for sub in ("clientes", "insights", "plans", "decisions", "workflows"):
            (self.vault / sub).mkdir()
        # Nodo target para los links
        (self.vault / "plans" / "plan-base.md").write_text(
            "---\ntype: Plan\ntitle: \"Plan Base\"\ndescription: \"Plan de referencia\"\n"
            "timestamp: 2026-01-01T00:00:00-05:00\n---\n",
            encoding="utf-8",
        )
        self.config_path = _write_yaml(VAULT_CONFIG_EDGE_TYPES)
        self.config = Config(self.vault, cli_config_arg=self.config_path)

    def tearDown(self):
        os.unlink(self.config_path)
        self.tmp.cleanup()

    def _args(self, **kwargs):
        defaults = {
            "concept_type": "Cliente",
            "title": "Lopcort SAS",
            "description": "Cliente de prueba",
            "tags": None,
            "status": None,
            "resource": None,
            "cyber": False,
            "dry_run": False,
            "body": None,
            "body_file": None,
            "links": None,
            "entity": "Lopcort",
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_by_entity_with_entity_creates_subdir(self):
        exit_code = new_run(self._args(), self.vault, config=self.config)
        self.assertEqual(exit_code, 0)
        expected = self.vault / "clientes" / "lopcort" / "lopcort-sas.md"
        self.assertTrue(expected.exists(), f"Falta {expected}")
        content = expected.read_text(encoding="utf-8")
        self.assertIn("type: Cliente", content)
        self.assertIn("title: \"Lopcort SAS\"", content)

    def test_by_entity_without_entity_errors(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = new_run(
                self._args(entity=None), self.vault, config=self.config)
        self.assertEqual(exit_code, 1)
        self.assertIn("entity", stderr.getvalue().lower())
        # No se creó ningún archivo
        self.assertEqual(list((self.vault / "clientes").iterdir()), [])

    def test_by_entity_with_link_to_plan(self):
        exit_code = new_run(
            self._args(links=["plans/plan-base:aplica"]),
            self.vault,
            config=self.config,
        )
        self.assertEqual(exit_code, 0)
        expected = self.vault / "clientes" / "lopcort" / "lopcort-sas.md"
        content = expected.read_text(encoding="utf-8")
        self.assertIn("links:", content)
        self.assertIn("type: aplica", content)

    def test_regular_type_ignores_entity(self):
        # Insight no está en by_entity → entity se ignora, va a insights/
        exit_code = new_run(
            self._args(concept_type="Insight", entity="Lopcort"),
            self.vault,
            config=self.config,
        )
        self.assertEqual(exit_code, 0)
        expected = self.vault / "insights" / "lopcort-sas.md"
        self.assertTrue(expected.exists(), f"Falta {expected}")


if __name__ == "__main__":
    unittest.main()
