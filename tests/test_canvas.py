"""Tests para canvas.py — validación, layout y generación de .canvas.

Cubre:
1. validate: detecta JSON inválido, IDs duplicados, placeholders, overlap, grid.
2. layout: grid/radial/force mueven nodos y alinean a grid de 20px.
3. generate: materializa el grafo del vault con aristas tipadas como labels.
"""

import json
import tempfile
import unittest
from pathlib import Path

from cli.commands.canvas import (
    generate_canvas,
    layout_canvas,
    layout_force,
    layout_grid,
    layout_radial,
    snap,
    validate_canvas,
)

GRID = 20


def _make_canvas(path, nodes, edges=None):
    """Escribe un canvas minimalista válido."""
    data = {"nodes": nodes, "edges": edges or []}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _text_node(nid, x=0, y=0, w=200, h=100, text="Hola", color="1"):
    return {"id": nid, "type": "text", "text": text,
            "x": x, "y": y, "width": w, "height": h, "color": color}


class TestValidate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def test_valid_canvas(self):
        p = _make_canvas(self.root / "ok.canvas", [_text_node("a"), _text_node("b", x=400)])
        report = validate_canvas(p)
        self.assertTrue(report["valid"])
        self.assertEqual(report["nodes"], 2)

    def test_invalid_json(self):
        p = self.root / "bad.canvas"
        p.write_text("{not json", encoding="utf-8")
        report = validate_canvas(p)
        self.assertFalse(report["valid"])
        self.assertTrue(any("Invalid JSON" in e for e in report["errors"]))

    def test_duplicate_ids(self):
        p = _make_canvas(self.root / "dup.canvas",
                         [_text_node("a"), _text_node("a", x=400)])
        report = validate_canvas(p)
        self.assertFalse(report["valid"])
        self.assertTrue(any("Duplicate node ID" in e for e in report["errors"]))

    def test_placeholder_detection(self):
        p = _make_canvas(self.root / "ph.canvas",
                         [_text_node("a", text="Describe this thing")])
        report = validate_canvas(p)
        self.assertTrue(report["valid"])  # placeholder es warning, no error
        self.assertTrue(any("placeholder" in w.lower() for w in report["warnings"]))

    def test_overlap_detection(self):
        p = _make_canvas(self.root / "ov.canvas",
                         [_text_node("a", x=0, y=0, w=200, h=100),
                          _text_node("b", x=100, y=0, w=200, h=100)])
        report = validate_canvas(p)
        self.assertTrue(any("overlap" in w.lower() for w in report["warnings"]))

    def test_grid_alignment_warning(self):
        p = _make_canvas(self.root / "grid.canvas", [_text_node("a", x=33)])
        report = validate_canvas(p)
        self.assertTrue(any("not aligned" in w for w in report["warnings"]))
        # Con --fix alinea
        report2 = validate_canvas(p, fix=True)
        self.assertFalse(any("not aligned" in w for w in report2["warnings"]))
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(data["nodes"][0]["x"] % GRID, 0)

    def test_unknown_node_in_edge(self):
        p = _make_canvas(self.root / "edge.canvas",
                         [_text_node("a")],
                         edges=[{"id": "e1", "fromNode": "a", "toNode": "ghost"}])
        report = validate_canvas(p)
        self.assertFalse(report["valid"])
        self.assertTrue(any("unknown node" in e for e in report["errors"]))


class TestLayout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def test_snap_multiplo_20(self):
        for v in (0, 1, 19, 20, 33, 47):
            self.assertEqual(snap(v) % GRID, 0)

    def test_grid_layout_alinea(self):
        nodes = [_text_node(f"n{i}", x=0, y=0) for i in range(4)]
        nodes = layout_grid(nodes)
        for n in nodes:
            self.assertEqual(n["x"] % GRID, 0)
            self.assertEqual(n["y"] % GRID, 0)
        # 4 nodos → 2 columnas (sqrt(4)), posiciones distintas
        posiciones = {(n["x"], n["y"]) for n in nodes}
        self.assertEqual(len(posiciones), 4)

    def test_radial_center_es_origen(self):
        nodes = [_text_node("a"), _text_node("b"), _text_node("c")]
        edges = [{"fromNode": "a", "toNode": "b"}, {"fromNode": "a", "toNode": "c"}]
        nodes = layout_radial(nodes, edges, center_id="a")
        center = next(n for n in nodes if n["id"] == "a")
        self.assertEqual(center["x"] % GRID, 0)
        self.assertEqual(center["y"] % GRID, 0)

    def test_force_mueve_nodos_sin_overlap(self):
        nodes = [_text_node(f"n{i}") for i in range(6)]
        edges = [{"fromNode": "n0", "toNode": f"n{i}"} for i in range(1, 6)]
        originales = {(n["id"], n["x"], n["y"]) for n in nodes}
        nodes = layout_force(nodes, edges, iterations=50)
        movidos = sum(1 for n in nodes
                      if (n["id"], n["x"], n["y"]) not in originales)
        self.assertGreater(movidos, 0)
        # Sin overlaps entre nodos
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                overlap = (a["x"] < b["x"] + b["width"] and a["x"] + a["width"] > b["x"]
                           and a["y"] < b["y"] + b["height"] and a["y"] + a["height"] > b["y"])
                self.assertFalse(overlap, f"overlap entre {a['id']} y {b['id']}")

    def test_layout_canvas_escribe_y_dry_run_no(self):
        p = _make_canvas(self.root / "lay.canvas",
                         [_text_node(f"n{i}", x=i * 5, y=i * 5) for i in range(5)])
        report = layout_canvas(str(p), "grid", dry_run=True)
        self.assertTrue(report["success"])
        # dry-run no escribe: coordenadas originales intactas
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(data["nodes"][0]["x"], 0)
        # real sí escribe y alinea
        report2 = layout_canvas(str(p), "grid", dry_run=False)
        self.assertTrue(report2["success"])
        data = json.loads(p.read_text(encoding="utf-8"))
        for n in data["nodes"]:
            self.assertEqual(n["x"] % GRID, 0)
            self.assertEqual(n["y"] % GRID, 0)


class TestGenerate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        (self.vault / "insights").mkdir()
        (self.vault / "specs").mkdir()
        (self.vault / "mapas").mkdir()

        root = self.vault / "insights" / "raiz.md"
        root.write_text("""---
type: Insight
title: "Raiz"
description: "Concepto raiz del test"
timestamp: 2026-01-01T00:00:00-05:00
created: 2026-01-01T00:00:00-05:00
links:
  - target: specs/hijo.md
    type: refina
---
Texto con [[specs/hijo.md]]
""")
        hijo = self.vault / "specs" / "hijo.md"
        hijo.write_text("""---
type: Spec
title: "Hijo"
description: "Spec que refina la raiz"
timestamp: 2026-01-01T00:00:00-05:00
created: 2026-01-01T00:00:00-05:00
---
Texto del hijo
""")

    def test_generate_crea_canvas_con_aristas_tipadas(self):
        report = generate_canvas(self.vault, "insights/raiz", depth=1, output=str(self.vault / "mapas" / "test.canvas"))
        self.assertTrue(report["success"])
        data = json.loads((self.vault / "mapas" / "test.canvas").read_text(encoding="utf-8"))
        ids = {n["id"] for n in data["nodes"]}
        self.assertIn("insights/raiz", ids)
        self.assertIn("specs/hijo", ids)
        # La arista lleva el label ontológico
        labels = {e.get("label") for e in data["edges"] if e.get("label")}
        self.assertIn("refina", labels)
        # El canvas generado pasa validación
        report_val = validate_canvas(self.vault / "mapas" / "test.canvas")
        self.assertTrue(report_val["valid"], report_val["errors"])
        self.assertEqual(report_val["warnings"], [])

    def test_generate_slug_inexistente(self):
        report = generate_canvas(self.vault, "insights/no-existe", depth=1)
        self.assertFalse(report["success"])


if __name__ == "__main__":
    unittest.main()
