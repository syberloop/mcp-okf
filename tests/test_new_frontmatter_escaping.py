"""`new` escribía title/description sin escapar comillas dobles → YAML inválido.

Una description del estilo `el flag "para cuando toque" no sincroniza nada`
producía `description: "... "para cuando toque" ..."`: el bloque no parsea, el
archivo queda ilegible para `edit` (Invalid or missing frontmatter) y el health
check lo marca. El mismo bug ya estaba resuelto en `cli/commands/index.py`, que
sí escapaba.
"""

import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli.commands.new import _build_frontmatter  # noqa: E402


def _parse(fm_text: str) -> dict:
    """Parsea el bloque de frontmatter generado por _build_frontmatter."""
    lines = fm_text.splitlines()
    assert lines[0] == "---", f"sin apertura de frontmatter: {lines[0]!r}"
    end = lines.index("---", 1)
    return yaml.safe_load("\n".join(lines[1:end]))


class NewFrontmatterEscapingTests(unittest.TestCase):
    def _fm(self, title, description, status="", resource="", tags="", cyber=False):
        return _build_frontmatter("Decision", title, description, status, resource,
                                  tags, cyber, links=None, config=None)

    def test_description_con_comillas_dobles_produce_yaml_valido(self):
        desc = 'El flag "para cuando toque" no sincroniza nada.'
        fm = _parse(self._fm("Titulo sin comillas", desc))
        self.assertEqual(fm["description"], desc)

    def test_title_con_comillas_dobles_produce_yaml_valido(self):
        title = 'La decisión "opción B" del demo'
        fm = _parse(self._fm(title, "descripcion corta sin comillas"))
        self.assertEqual(fm["title"], title)

    def test_backslash_y_comilla_suelta_no_rompen(self):
        desc = 'ruta C:\\temp y comilla " suelta'
        fm = _parse(self._fm("t", desc))
        self.assertEqual(fm["description"], desc)

    def test_resource_con_comillas_produce_yaml_valido(self):
        resource = 'https://example.com/a"b'
        fm = _parse(self._fm("t", "d", resource=resource))
        self.assertEqual(fm["resource"], resource)

    def test_descripcion_plana_sigue_sin_comillas_rotas(self):
        fm = _parse(self._fm("titulo", "sin comillas internas"))
        self.assertEqual(fm["description"], "sin comillas internas")
        self.assertEqual(fm["title"], "titulo")

    def test_cyber_block_sigue_siendo_yaml_valido(self):
        fm = _parse(self._fm("t", "d", cyber=True))
        self.assertEqual(fm["cyber"]["outcome"], "pending")


if __name__ == "__main__":
    unittest.main()
