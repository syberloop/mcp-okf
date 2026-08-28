"""Test de coherencia de versión: sin hardcodeo doble.

La versión vive en UN solo lugar: ``cli/__init__.py`` (``__version__``).
``pyproject.toml`` la declara como ``dynamic`` y setuptools la lee vía
``attr = "cli.__version__"`` — el paquete instalado y el CLI reportan
siempre la misma versión por construcción.

Antes (v0.4.0) la versión estaba hardcodeada en dos lugares y divergieron:
``cli/__init__.py`` subió a 0.4.0 y ``pyproject.toml`` quedó en 0.3.1
(pip show decía 0.3.1 sobre código 0.4.0). Estos tests protegen el contrato:
- que no reaparezca un literal ``version = "x.y.z"`` en [project]
- que ``dynamic = ["version"]`` apunte a ``cli.__version__``
- que ``cli.__version__`` siga siendo un semver no vacío
"""

import re
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli import __version__

SEMVER = re.compile(r"^\d+\.\d+\.\d+(\.[0-9A-Za-z-]+|\+[0-9A-Za-z-]+)?$")

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


class VersionCoherenceTests(unittest.TestCase):
    def _load_pyproject(self):
        with PYPROJECT.open("rb") as fh:
            return tomllib.load(fh)

    def test_version_not_hardcoded_in_pyproject(self):
        project = self._load_pyproject()["project"]
        self.assertNotIn(
            "version", project,
            "version literal en pyproject.toml: la version se lee de "
            "cli/__init__.py via dynamic (single source of truth).",
        )

    def test_version_is_dynamic(self):
        project = self._load_pyproject()["project"]
        self.assertIn("version", project.get("dynamic", []))

    def test_dynamic_version_points_to_cli(self):
        config = self._load_pyproject()
        attr = config["tool"]["setuptools"]["dynamic"]["version"]["attr"]
        self.assertEqual(attr, "cli.__version__")

    def test_cli_version_is_valid_semver(self):
        self.assertIsInstance(__version__, str)
        self.assertRegex(__version__, SEMVER, f"__version__ = {__version__!r}")


if __name__ == "__main__":
    unittest.main()
