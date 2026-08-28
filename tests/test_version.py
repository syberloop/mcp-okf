"""Test de coherencia de versión entre el paquete y el código.

La versión vive en dos lugares que tienen que decir lo mismo:

- ``pyproject.toml`` → metadatos del paquete instalado (lo que reporta
  ``pip show okf-mcp``).
- ``cli/__init__.py`` → ``__version__``, que es de donde ``health`` lee la
  versión que muestra al usuario.

Si divergen, el CLI reporta una versión y el paquete instalado otra. Pasó en
v0.4.0: ``cli/__init__.py`` se bumpeó a 0.4.0 y ``pyproject.toml`` se quedó en
0.3.1, así que ``pip show`` decía 0.3.1 sobre código 0.4.0.
"""

import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli import __version__


class VersionCoherenceTests(unittest.TestCase):
    def test_pyproject_matches_cli_version(self):
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        with pyproject.open("rb") as fh:
            declared = tomllib.load(fh)["project"]["version"]

        self.assertEqual(
            declared,
            __version__,
            "pyproject.toml declara %s y cli/__init__.py declara %s: "
            "el bump de versión quedó a medias." % (declared, __version__),
        )


if __name__ == "__main__":
    unittest.main()
