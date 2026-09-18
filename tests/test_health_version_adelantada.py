"""Regresión: la línea de versión no afirma «actualizada» sin haber verificado.

`_check_version` consulta la última *release publicada* en GitHub y resolvía
`up_to_date = local >= latest`. Cuando el equipo deja de publicar releases pero
sigue subiendo versiones, `local > latest` y la línea dice «actualizada» para
CUALQUIER versión desde la última release — incluida una congelada meses atrás.

Caso real (2026-09-17): última release publicada v0.4.3 (28-ago), última versión
del código 0.4.12 — nueve versiones sin release ni tag. Un CLI parado en 0.4.3
recibía exactamente la misma etiqueta verde que uno en master.

`local > latest` no significa «al día»: significa que el feed de releases quedó
atrás y no puede verificar nada. Este test fija los tres estados distinguidos.
"""
import unittest
from unittest.mock import patch


class _Resp:
    def __init__(self, tag):
        self._tag = tag

    def read(self):
        import json
        return json.dumps({"tag_name": self._tag}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class HealthVersionAdelantadaTest(unittest.TestCase):

    def _check(self, local, tag_publicado):
        import cli
        from cli.commands.health import _check_version
        with patch.object(cli, "__version__", local), \
             patch("urllib.request.urlopen", lambda *a, **k: _Resp(tag_publicado)):
            return _check_version(None)

    def test_local_adelantada_no_se_reporta_como_actualizada(self):
        v = self._check("0.4.12", "v0.4.3")
        # El defecto de fondo va primero: sin el fix esto falla por semántica
        # (True is not False), no por una clave que falta.
        self.assertFalse(
            v["up_to_date"],
            "estar por delante del feed no es haber verificado que está al día")
        self.assertTrue(v.get("ahead"), "0.4.12 está por delante de la release v0.4.3")

    def test_local_igual_a_la_release_si_es_actualizada(self):
        v = self._check("0.4.3", "v0.4.3")
        self.assertTrue(v["up_to_date"])
        self.assertFalse(v["ahead"])

    def test_local_atrasada_sigue_siendo_desactualizada(self):
        v = self._check("0.4.1", "v0.4.3")
        self.assertFalse(v["up_to_date"])
        self.assertFalse(v["ahead"])
        self.assertEqual(v["latest"], "0.4.3")

    def test_sin_red_no_inventa_estado(self):
        import cli
        from cli.commands.health import _check_version

        def _boom(*a, **k):
            raise OSError("sin red")

        with patch.object(cli, "__version__", "0.4.12"), \
             patch("urllib.request.urlopen", _boom):
            v = _check_version(None)
        self.assertIsNone(v["latest"])
        self.assertIsNone(v["up_to_date"])
        self.assertIsNone(v["ahead"])


if __name__ == "__main__":
    unittest.main()
