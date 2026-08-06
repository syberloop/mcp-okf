"""Tests de integración para graph.py con aristas tipadas."""

import unittest
import tempfile
from pathlib import Path
from cli.commands.graph import build_graph, _cmd_stats, _cmd_backlinks, _cmd_deps


class TestBuildGraphWithTypedEdges(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name)
        (self.vault / "frameworks").mkdir()
        (self.vault / "insights").mkdir()

        # Nodo A: MarcoTeorico
        a = self.vault / "frameworks" / "tp3.md"
        a.write_text("""---
type: MarcoTeorico
title: "TP3"
description: "Marco teorico"
timestamp: 2026-01-01T00:00:00-05:00
created: 2026-01-01T00:00:00-05:00
links:
  - target: insights/sistema.md
    type: fundamenta
---
Texto con [[insights/sistema.md]]
""")

        # Nodo B: Insight con wikilink y typed link
        b = self.vault / "insights" / "sistema.md"
        b.write_text("""---
type: Insight
title: "Sistema Nervioso"
description: "Un insight"
timestamp: 2026-01-01T00:00:00-05:00
created: 2026-01-01T00:00:00-05:00
links:
  - target: frameworks/tp3.md
    type: extiende
---
Texto con [[frameworks/tp3.md]]
""")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_graph_has_typed_out(self):
        graph = build_graph(self.vault)
        self.assertIn("typed_out", graph["insights/sistema.md"])
        self.assertIn("typed_in", graph["frameworks/tp3.md"])

    def test_typed_out_contains_correct_edge(self):
        graph = build_graph(self.vault)
        typed_out = graph["insights/sistema.md"]["typed_out"]
        self.assertEqual(len(typed_out), 1)
        self.assertEqual(typed_out[0]["target"], "frameworks/tp3.md")
        self.assertEqual(typed_out[0]["type"], "extiende")

    def test_typed_in_contains_correct_edge(self):
        graph = build_graph(self.vault)
        typed_in = graph["frameworks/tp3.md"]["typed_in"]
        self.assertEqual(len(typed_in), 1)
        self.assertEqual(typed_in[0]["target"], "insights/sistema.md")
        self.assertEqual(typed_in[0]["type"], "extiende")

    def test_fundamenta_edge_appears(self):
        graph = build_graph(self.vault)
        typed_out = graph["frameworks/tp3.md"]["typed_out"]
        self.assertEqual(len(typed_out), 1)
        self.assertEqual(typed_out[0]["target"], "insights/sistema.md")
        self.assertEqual(typed_out[0]["type"], "fundamenta")

    def test_wikilinks_still_work(self):
        graph = build_graph(self.vault)
        self.assertIn("insights/sistema.md", graph["frameworks/tp3.md"]["out"])
        self.assertIn("frameworks/tp3.md", graph["insights/sistema.md"]["out"])

    def test_no_links_field_returns_empty_typed(self):
        # Nodo without links:
        c = self.vault / "insights" / "simple.md"
        c.write_text("""---
type: Insight
title: "Simple"
description: "No links"
timestamp: 2026-01-01T00:00:00-05:00
created: 2026-01-01T00:00:00-05:00
---
""")
        graph = build_graph(self.vault)
        self.assertEqual(graph["insights/simple.md"]["typed_out"], [])
        self.assertEqual(graph["insights/simple.md"]["typed_in"], [])


class TestBacklinksDepsWithEdgeType(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name)
        (self.vault / "frameworks").mkdir()
        (self.vault / "insights").mkdir()

        a = self.vault / "frameworks" / "tp3.md"
        a.write_text("""---
type: MarcoTeorico
title: "TP3"
description: "Marco teorico"
timestamp: 2026-01-01T00:00:00-05:00
created: 2026-01-01T00:00:00-05:00
---
Texto con [[insights/sistema.md]]
""")

        b = self.vault / "insights" / "sistema.md"
        b.write_text("""---
type: Insight
title: "Sistema"
description: "Un insight"
timestamp: 2026-01-01T00:00:00-05:00
created: 2026-01-01T00:00:00-05:00
links:
  - target: frameworks/tp3.md
    type: extiende
---
Texto con [[frameworks/tp3.md]]
""")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_backlinks_includes_typed(self):
        graph = build_graph(self.vault)
        output = _cmd_backlinks(graph, "frameworks/tp3.md")
        self.assertIn("insights/sistema.md", output)
        self.assertIn("extiende:", output)  # score incluido: [extiende:0.4]

    def test_deps_includes_typed(self):
        graph = build_graph(self.vault)
        output = _cmd_deps(graph, "insights/sistema.md")
        self.assertIn("frameworks/tp3.md", output)
        self.assertIn("extiende:", output)  # score incluido: [extiende:0.4]

    def test_backlinks_filtered_by_edge_type(self):
        graph = build_graph(self.vault)
        output = _cmd_backlinks(graph, "frameworks/tp3.md", edge_type="extiende")
        self.assertIn("insights/sistema.md", output)

    def test_backlinks_filtered_excludes_non_matching(self):
        graph = build_graph(self.vault)
        output = _cmd_backlinks(graph, "frameworks/tp3.md", edge_type="refina")
        # Only the wikilink (untyped) might still appear, but typed refina should not
        self.assertNotIn("[refina]", output)


class TestStatsWithTypedEdges(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name)
        (self.vault / "frameworks").mkdir()
        (self.vault / "insights").mkdir()

        a = self.vault / "frameworks" / "tp3.md"
        a.write_text("""---
type: MarcoTeorico
title: "TP3"
description: "Marco"
timestamp: 2026-01-01T00:00:00-05:00
created: 2026-01-01T00:00:00-05:00
---
[[insights/sistema.md]]
""")

        b = self.vault / "insights" / "sistema.md"
        b.write_text("""---
type: Insight
title: "Sistema"
description: "Insight"
timestamp: 2026-01-01T00:00:00-05:00
created: 2026-01-01T00:00:00-05:00
links:
  - target: frameworks/tp3.md
    type: extiende
---
[[frameworks/tp3.md]]
""")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_stats_shows_typed_edges_count(self):
        graph = build_graph(self.vault)
        tag_index = {}
        output = _cmd_stats(graph, tag_index)
        self.assertIn("Edges (typed): 1", output)
        self.assertIn("Edges (wikilinks): 2", output)
        self.assertIn("Total edges: 3", output)


if __name__ == "__main__":
    unittest.main()
