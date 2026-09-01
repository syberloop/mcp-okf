"""Tests de _check_timestamp_git — exención de archivos sin commitear.

El check compara el timestamp del frontmatter contra la fecha del ÚLTIMO
COMMIT del archivo. Como `edit` refresca el timestamp en cada cambio real,
editar un concepto commiteado hace más de un día producía un warning que
`health --strict` convertía en un pre-commit abortado: el commit contra el
que se compara todavía no existe.
"""

import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


CONCEPTO = """---
type: Insight
title: "{titulo}"
description: "test"
timestamp: {ts}
---

cuerpo
"""


class TimestampGitTestBase(unittest.TestCase):
    def setUp(self):
        # Cada test usa un tempdir unico, asi que las caches por-proceso de
        # gitutil no colisionan; limpiamos la de fechas por prolijidad. No se
        # toca la de sin-commitear a proposito: asi este archivo tambien corre
        # contra el arbol sin el fix y falla por asercion, no por AttributeError.
        from cli import gitutil
        gitutil._DATES_CACHE.clear()

        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name)
        (self.vault / "insights").mkdir()

        # Offset fijo -05:00 a proposito: con fechas en UTC git emite el
        # sufijo 'Z' y gitutil._ISO_DATE_RE no lo acepta, asi que el indice
        # sale vacio y el check no evalua nada. Es un defecto aparte, ajeno
        # a este fix (ver cuerpo del PR); el fixture lo esquiva para probar
        # exactamente lo que este PR cambia.
        tz = timezone(timedelta(hours=-5))
        self.hoy = datetime.now(tz)
        self.hace_10 = self.hoy - timedelta(days=10)
        self._git("init", "-q")
        self._git("config", "user.email", "test@test")
        self._git("config", "user.name", "Test")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _git(self, *args, fecha=None):
        env = None
        if fecha is not None:
            iso = fecha.isoformat()
            import os
            env = dict(os.environ, GIT_AUTHOR_DATE=iso, GIT_COMMITTER_DATE=iso)
        subprocess.run(["git", "-C", str(self.vault), *args],
                       check=True, capture_output=True, env=env)

    def _escribir(self, nombre, ts):
        p = self.vault / "insights" / f"{nombre}.md"
        p.write_text(CONCEPTO.format(titulo=nombre, ts=ts.isoformat()), encoding="utf-8")
        return p

    def _warnings(self):
        # Import dentro del test: sin el fix, un import a nivel de módulo
        # rompería el archivo entero en vez de fallar por aserción.
        from cli.commands.health import _check_timestamp_git
        _ok, warnings, _errors = _check_timestamp_git(self.vault)
        return warnings


class TestTimestampGitSinCommitear(TimestampGitTestBase):
    def test_archivo_editado_sin_commitear_no_avisa(self):
        """El caso que rompía: concepto viejo, editado hoy, todavía sin commitear."""
        self._escribir("viejo", self.hace_10)
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "inicial", fecha=self.hace_10)

        # `edit` refresca el timestamp; el archivo queda sucio.
        self._escribir("viejo", self.hoy)

        warnings = self._warnings()
        self.assertEqual(
            [w for w in warnings if "viejo.md" in w], [],
            f"un archivo sin commitear no debe avisar de timestamp futuro: {warnings}",
        )

    def test_archivo_limpio_con_timestamp_futuro_sigue_avisando(self):
        """Control: el check no queda desactivado para archivos ya commiteados."""
        self._escribir("limpio", self.hoy)
        self._git("add", "-A")
        # Commit fechado 10 días atrás con timestamp de hoy: desfase real.
        self._git("commit", "-q", "-m", "inicial", fecha=self.hace_10)

        warnings = self._warnings()
        propios = [w for w in warnings if "limpio.md" in w]
        self.assertEqual(len(propios), 1, f"esperaba 1 warning, hay: {warnings}")
        self.assertIn("es futuro", propios[0])


if __name__ == "__main__":
    unittest.main()
