"""Regresión: el index raíz no enlaza carpetas que no tienen index.md.

_generate_root_index lista toda carpeta de primer nivel y le escribía un enlace
a <carpeta>/index.md, existiera o no. Pero `index` sólo genera índices para las
carpetas con conceptos (_find_concept_dirs), así que una carpeta sin conceptos
quedaba enlazada a un archivo que nunca va a existir. Medido en nuestro vault el
2026-09-11: 2 de 11 enlaces del index raíz eran muertos — hooks/ (el
pre-commit) y Claude outputs/ (una captura que guardó la app de escritorio).
"""
import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path


def _concepto():
    return (
        "---\n"
        "type: Insight\n"
        'title: "Prueba"\n'
        'description: "Concepto de prueba"\n'
        "timestamp: 2026-09-11T11:00:00-05:00\n"
        "---\n\nCuerpo.\n"
    )


class IndexRaizSinEnlacesMuertosTest(unittest.TestCase):

    def _regenerar(self, vault):
        from cli.commands.index import run
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            run(None, vault)
        return (vault / "index.md").read_text(encoding="utf-8")

    def _vault_con_carpetas_sin_conceptos(self, d):
        vault = Path(d)
        (vault / "insights").mkdir()
        (vault / "insights" / "prueba.md").write_text(_concepto(), encoding="utf-8")
        (vault / "hooks").mkdir()
        (vault / "hooks" / "pre-commit.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (vault / "Claude outputs").mkdir()
        (vault / "Claude outputs" / "captura.jpg").write_bytes(b"\xff\xd8\xff")
        return vault

    def test_todo_enlace_del_index_raiz_apunta_a_un_archivo_que_existe(self):
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault_con_carpetas_sin_conceptos(d)
            index = self._regenerar(vault)
            destinos = re.findall(r"\]\(([^)]+)\)", index)
            self.assertIn("insights/index.md", destinos)
            muertos = [p for p in destinos if not (vault / p).exists()]
            self.assertEqual(muertos, [])

    def test_carpeta_sin_conceptos_no_aparece_en_el_index_raiz(self):
        with tempfile.TemporaryDirectory() as d:
            vault = self._vault_con_carpetas_sin_conceptos(d)
            index = self._regenerar(vault)
            self.assertNotIn("[hooks/]", index)
            self.assertNotIn("[Claude outputs/]", index)

    def test_carpeta_con_index_escrito_a_mano_se_sigue_listando(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / "insights").mkdir()
            (vault / "insights" / "prueba.md").write_text(_concepto(), encoding="utf-8")
            (vault / "referencias").mkdir()
            (vault / "referencias" / "index.md").write_text(
                '---\ndescription: "Material de consulta"\n---\n\n# referencias\n',
                encoding="utf-8")
            index = self._regenerar(vault)
            self.assertIn(
                "* [referencias/](referencias/index.md) - Material de consulta", index)


if __name__ == "__main__":
    unittest.main()
