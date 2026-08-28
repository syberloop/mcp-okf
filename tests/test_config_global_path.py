"""Tests de la ruta del config global de usuario (paso 4 de la cadena).

El docstring de cli/config.py documenta `~/.config/okf/config.yaml`, pero el
código buscaba `~/.config/cli/config.yaml`. Quien seguía la documentación
creaba el archivo en una ruta que nunca se leía, sin ningún error visible: el
resolver simplemente caía a los defaults embebidos.

Se aceptan ambas, con la documentada primero; `cli/` queda como legacy para no
romper instalaciones que hayan seguido el código.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli.config import Config


class GlobalConfigPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        # Un vault sin .okf.config.yaml, para que la cadena llegue al paso 4.
        self.vault = Path(self.tmp.name) / "vault"
        self.vault.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_global(self, parent: str) -> Path:
        d = self.home / ".config" / parent
        d.mkdir(parents=True)
        cfg = d / "config.yaml"
        cfg.write_text("cyber:\n  review_days: 99\n", encoding="utf-8")
        return cfg

    def test_documented_okf_path_is_resolved(self):
        expected = self._write_global("okf")
        with patch.object(Path, "home", return_value=self.home):
            resolved = Config(self.vault)._resolve_path(None)
        self.assertEqual(resolved, expected)

    def test_legacy_cli_path_still_works(self):
        expected = self._write_global("cli")
        with patch.object(Path, "home", return_value=self.home):
            resolved = Config(self.vault)._resolve_path(None)
        self.assertEqual(resolved, expected)

    def test_documented_path_wins_over_legacy(self):
        expected = self._write_global("okf")
        self._write_global("cli")
        with patch.object(Path, "home", return_value=self.home):
            resolved = Config(self.vault)._resolve_path(None)
        self.assertEqual(resolved, expected)

    def test_no_global_config_returns_none(self):
        self.home.mkdir(parents=True, exist_ok=True)
        with patch.object(Path, "home", return_value=self.home):
            resolved = Config(self.vault)._resolve_path(None)
        self.assertIsNone(resolved)


if __name__ == "__main__":
    unittest.main()
