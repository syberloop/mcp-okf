"""El smoke test de `health` debe correr con el MISMO intérprete que el CLI.

Regresión: `_check_scripts` lanzaba los subprocesos con `["python3", ...]`, el
primer python3 del PATH. Cuando el CLI corre desde un venv que no está primero
en el PATH —la instalación recomendada, `~/.local/okf-venv`— ese `python3` es
otro intérprete, sin el paquete `cli` instalado, y los 8 comandos del smoke test
fallan con ModuleNotFoundError. `health` reporta entonces 🔴 7/8 con 6 errores
sobre un vault que está sano.
"""
import sys
import unittest
from unittest import mock

from cli.commands import health


class TestSmokeUsaElMismoInterprete(unittest.TestCase):
    def test_subprocesos_usan_sys_executable(self):
        llamadas = []

        def fake_run(cmd, *args, **kwargs):
            llamadas.append(cmd)
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(health.subprocess, "run", side_effect=fake_run):
            health._check_scripts("/tmp/vault-inexistente")

        self.assertTrue(llamadas, "el smoke test no lanzó ningún subproceso")
        for cmd in llamadas:
            self.assertEqual(
                cmd[0], sys.executable,
                f"el smoke test usó {cmd[0]!r} en vez del intérprete actual "
                f"({sys.executable!r}): con el CLI en un venv que no está primero "
                f"en el PATH, health falla sobre un vault sano",
            )
            self.assertEqual(cmd[1:3], ["-m", "cli"])


if __name__ == "__main__":
    unittest.main()
