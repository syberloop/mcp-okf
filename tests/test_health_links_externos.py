"""Regresión: health Check 2 y Check 4 contra directorios/URLs fuera del vault.

Check 2 (_check_indices): un index.md bajo un directorio excluido del régimen
de índices (p.ej. .dsh-build, que vive dentro del vault como repo git anidado)
no debe validarse — el indexer nunca lo regenera, así que marcarlo stale es un
falso positivo. Antes el check hardcodeaba 6 exclusiones y omitía .dsh-build.

Check 4 (_check_broken_links): un enlace markdown a una URL externa que
termina en ".md" (p.ej. https://github.com/google-labs-code/design.md) era
resuelto como ruta local y reportado broken aunque la URL responda 200.
"""

import tempfile
import unittest
from pathlib import Path


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class HealthExternalLinksTest(unittest.TestCase):
    def setUp(self):
        from cli.commands.health import _check_broken_links, _check_indices
        self._check_broken_links = _check_broken_links
        self._check_indices = _check_indices
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_url_externa_terminada_en_md_no_es_link_roto(self):
        vault = self.vault
        _write(vault / "research" / "nota.md",
               "# Nota\n\nVer [design.md](https://github.com/google-labs-code/design.md)\n"
               "y [SPEC.md](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)\n")
        _write(vault / "insights" / "real.md",
               "---\ntype: Insight\ntitle: \"real\"\ndescription: \"un concepto real\"\n---\n\ncuerpo\n")

        broken = self._check_broken_links(vault)
        self.assertEqual(broken, [], f"URLs externas .md marcadas como rotas: {broken}")

    def test_wikilink_local_roto_sigue_reportandose(self):
        vault = self.vault
        _write(vault / "insights" / "a.md",
               "---\ntype: Insight\ntitle: \"a\"\ndescription: \"concepto a\"\n---\n\n"
               "ref [[insights/inexistente]]\n")
        broken = self._check_broken_links(vault)
        self.assertEqual(len(broken), 1, broken)
        self.assertIn("inexistente", broken[0])

    def test_index_bajo_dir_excluido_no_se_valida(self):
        vault = self.vault
        # .dsh-build está en DEFAULT_EXCLUDE_DIRS: el indexer nunca lo toca.
        # Un index.md stale ahí no debe reportarse.
        _write(vault / ".dsh-build" / "anidado" / "index.md",
               "---\ndescription: \"proyecto anidado no conceptos\"\n---\n\n# Anidado\n\n"
               "* [fantasma.md](fantasma.md)\n")
        _write(vault / ".dsh-build" / "anidado" / "real.md", "sin frontmatter\n")

        ok, stale = self._check_indices(vault)
        self.assertEqual(stale, [], f"index de dir excluido marcado stale: {stale}")

    def test_index_de_carpeta_concepto_sin_sync_sigue_reportandose(self):
        vault = self.vault
        _write(vault / "insights" / "index.md",
               "---\ndescription: \"índice\"\n---\n\n# Insights\n\n")
        _write(vault / "insights" / "nuevo.md",
               "---\ntype: Insight\ntitle: \"nuevo\"\ndescription: \"concepto sin indexar\"\n---\n\ncuerpo\n")

        ok, stale = self._check_indices(vault)
        self.assertTrue(any("insights/index.md" in s and "missing from index" in s for s in stale),
                        stale)


if __name__ == "__main__":
    unittest.main()
