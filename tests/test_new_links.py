"""Tests de integración para new.py con aristas tipadas."""

import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from cli.commands.new import _parse_links, _build_frontmatter, run


class TestParseLinks(unittest.TestCase):
    def test_valid_single_link(self):
        result = _parse_links(["frameworks/tp3-cibernetico:extiende"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["target"], "frameworks/tp3-cibernetico")
        self.assertEqual(result[0]["type"], "extiende")

    def test_valid_multiple_links(self):
        result = _parse_links([
            "frameworks/tp3:extiende",
            "decisions/criterio:refina",
        ])
        self.assertEqual(len(result), 2)

    def test_no_colon_raises(self):
        with self.assertRaises(ValueError):
            _parse_links(["invalid_format"])

    def test_empty_target_raises(self):
        with self.assertRaises(ValueError):
            _parse_links([":extiende"])

    def test_empty_type_raises(self):
        with self.assertRaises(ValueError):
            _parse_links(["target:"])

    def test_empty_list_returns_empty(self):
        result = _parse_links([])
        self.assertEqual(result, [])

    def test_none_returns_empty(self):
        result = _parse_links(None)
        self.assertEqual(result, [])


class TestBuildFrontmatterWithLinks(unittest.TestCase):
    def test_includes_links_block(self):
        links = [{"target": "frameworks/tp3.md", "type": "extiende"}]
        fm = _build_frontmatter("Insight", "Test", "desc", "", "", "", False, links=links)
        self.assertIn("links:", fm)
        self.assertIn("target: frameworks/tp3.md", fm)
        self.assertIn("type: extiende", fm)

    def test_no_links_param_excluded(self):
        fm = _build_frontmatter("Insight", "Test", "desc", "", "", "", False)
        self.assertNotIn("links:", fm)

    def test_empty_links_excluded(self):
        fm = _build_frontmatter("Insight", "Test", "desc", "", "", "", False, links=[])
        self.assertNotIn("links:", fm)


class TestNewRunWithLinks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name)
        # Create minimal vault structure
        (self.vault / "frameworks").mkdir()
        (self.vault / "decisions").mkdir()
        (self.vault / "insights").mkdir()
        # Create a target node
        target = self.vault / "frameworks" / "tp3-cibernetico.md"
        target.write_text("""---
type: MarcoTeorico
title: "TP3 Cibernetico"
description: "Marco teorico de referencia"
timestamp: 2026-01-01T00:00:00-05:00
created: 2026-01-01T00:00:00-05:00
---
""")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _make_args(self, **kwargs):
        defaults = {
            "concept_type": "Insight",
            "title": "Test Insight",
            "description": "A test insight",
            "tags": None,
            "status": None,
            "resource": None,
            "cyber": False,
            "dry_run": True,
            "body": None,
            "body_file": None,
            "links": None,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_valid_link_creates_node(self):
        args = self._make_args(
            links=["frameworks/tp3-cibernetico:extiende"],
        )
        exit_code = run(args, self.vault)
        self.assertEqual(exit_code, 0)

    def test_invalid_target_rejected(self):
        args = self._make_args(
            links=["nonexistent:extiende"],
        )
        exit_code = run(args, self.vault)
        self.assertEqual(exit_code, 1)

    def test_invalid_edge_type_rejected(self):
        args = self._make_args(
            links=["frameworks/tp3-cibernetico:nonexistent_type"],
        )
        exit_code = run(args, self.vault)
        self.assertEqual(exit_code, 1)

    def test_malformed_link_rejected(self):
        args = self._make_args(
            links=["invalid_format_without_colon"],
        )
        exit_code = run(args, self.vault)
        self.assertEqual(exit_code, 1)

    def test_duplicate_link_rejected(self):
        args = self._make_args(
            links=[
                "frameworks/tp3-cibernetico:extiende",
                "frameworks/tp3-cibernetico:extiende",
            ],
        )
        exit_code = run(args, self.vault)
        self.assertEqual(exit_code, 1)

    def test_different_types_same_target_allowed(self):
        # Crear un nodo Decision para que refina funcione
        (self.vault / "decisions" / "criterio.md").write_text("""---
type: Criterio
title: "Criterio Test"
description: "Un criterio"
timestamp: 2026-01-01T00:00:00-05:00
created: 2026-01-01T00:00:00-05:00
---
""")
        args = self._make_args(
            concept_type="Decision",
            links=[
                "frameworks/tp3-cibernetico:extiende",
                "decisions/criterio:refina",
            ],
        )
        exit_code = run(args, self.vault)
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
