"""El hook versionado (`hooks/pre-commit`) debe ser coherente con el CLI.

Caso real (2026-09-29): al retirar `cli dashboard` en v0.4.17 quedó sin
actualizar `hooks/pre-commit` — la capa que el CHANGELOG declara como fuente de
verdad del hook del vault. El template seguía llamando al comando retirado
(silenciado con `2>/dev/null`, o sea invisible) y stageaba `dashboard.md`
(`git add` fallaba con `fatal: pathspec ... did not match any files` en cada
commit de quien lo tuviera instalado).

El retiro se hizo con un grep truncado por `| head`, que ocultó este archivo.
Estos tests atan el template a la realidad del CLI: si mañana se retira otro
subcomando, el test falla en vez de dejarlo apuntando al vacío.
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "hooks" / "pre-commit"

# Flags del CLI que consumen el token siguiente.
_FLAGS_CON_VALOR = {"--vault", "--config", "--scope"}


def _cli_commands():
    """Subcomandos que el CLI reconoce hoy."""
    out = subprocess.run(
        [sys.executable, "-m", "cli", "--help"],
        capture_output=True, text=True, cwd=REPO, timeout=60,
    )
    texto = (out.stdout or "") + (out.stderr or "")
    m = re.search(r"\{([a-z0-9,\-]+)\}", texto)
    if not m:
        raise AssertionError(f"no pude leer los subcomandos del CLI:\n{texto[:400]}")
    return set(m.group(1).split(","))


def _invocaciones(texto):
    """[(linea, subcomando)] de cada `python3 -m cli ... <cmd>` del texto."""
    invocaciones = []
    for n, linea in enumerate(texto.split("\n"), 1):
        if "-m cli" not in linea:
            continue
        resto = linea.split("-m cli", 1)[1]
        tokens = resto.split()
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok in _FLAGS_CON_VALOR:
                i += 2
                continue
            if tok.startswith("-"):
                i += 1
                continue
            cmd = tok.strip("'\"|;&)")
            invocaciones.append((n, cmd))
            break
    return invocaciones


class HooksTemplateCoherencia(unittest.TestCase):
    def setUp(self):
        self.texto = TEMPLATE.read_text(encoding="utf-8")

    def test_template_existe_y_es_ejecutable(self):
        self.assertTrue(TEMPLATE.exists(), f"falta {TEMPLATE}")
        self.assertTrue(TEMPLATE.stat().st_mode & 0o111,
                        "hooks/pre-commit no es ejecutable")

    def test_extrae_invocaciones(self):
        # Guard del propio parser del test: si no ve nada, el resto es vacuo.
        cmds = {c for _, c in _invocaciones(self.texto)}
        self.assertIn("validate", cmds)
        self.assertIn("index", cmds)
        self.assertGreaterEqual(len(cmds), 4)

    def test_todos_los_subcomandos_invocados_existen(self):
        validos = _cli_commands()
        invalidos = [(n, c) for n, c in _invocaciones(self.texto) if c not in validos]
        self.assertEqual(
            invalidos, [],
            f"hooks/pre-commit invoca subcomandos que el CLI no reconoce: {invalidos}. "
            f"Válidos: {sorted(validos)}",
        )

    def test_no_stagea_archivos_generados_retirados(self):
        # El `git add` del paso 5 no debe listar archivos que ya no existen.
        lineas = [l for l in self.texto.split("\n") if l.strip().startswith("git add")]
        self.assertTrue(lineas, "no encontré el `git add` del paso 5")
        for l in lineas:
            self.assertNotIn("dashboard.md", l,
                             f"el `git add` stagea dashboard.md (retirado): {l.strip()}")

    def test_no_invoca_el_dashboard_estatico(self):
        self.assertNotRegex(
            self.texto, r"-m cli[^\n]*\bdashboard\b(?!-)",
            "hooks/pre-commit invoca `cli dashboard` (retirado en v0.4.17)",
        )


class HooksTemplateInterprete(unittest.TestCase):
    """El template no debe depender del `python3` del PATH.

    Caso real (2026-10-01, hallado en el boot sequence del handoff DSH): el
    toolchain de Hermes se instaló el 2026-09-30 en ~/.hermes/tools/python-*/, y
    desde entonces `python3` en una sesión de Hermes apunta a un intérprete SIN
    PyYAML. El hook ejecutaba `python3 -m cli validate` y moría con
    `ModuleNotFoundError: No module named 'yaml'` — bloqueando el commit sin
    explicar la causa real (el mensaje hablaba de validación fallida).
    """

    def setUp(self):
        self.texto = TEMPLATE.read_text(encoding="utf-8")
        self.lineas_cli = [l for l in self.texto.split("\n") if "-m cli" in l]

    def test_toda_invocacion_usa_el_interprete_resuelto(self):
        sin_resolver = [l.strip() for l in self.lineas_cli if "$OKF_PY" not in l]
        self.assertEqual(
            sin_resolver, [],
            "estas invocaciones no usan el intérprete resuelto ($OKF_PY) y "
            f"dependen del PATH: {sin_resolver}",
        )

    def test_resuelve_un_interprete_con_pyyaml(self):
        self.assertRegex(
            self.texto, r"import yaml",
            "el hook debe comprobar que el intérprete puede importar yaml",
        )
        self.assertIn("OKF_PY=", self.texto)
        # El orden de candidatos debe empezar por el python del sistema, que sí
        # trae PyYAML, y no por el `python3` del PATH.
        self.assertRegex(
            self.texto, r"for _cand in /usr/bin/python3 python3",
            "los candidatos deben empezar por /usr/bin/python3",
        )

    def test_override_documentado(self):
        self.assertIn("OKF_PYTHON", self.texto,
                      "debe poder forzarse el intérprete con OKF_PYTHON")

    def test_falla_ruidoso_si_no_hay_yaml(self):
        # Sin intérprete válido el hook NO debe seguir: un hook que no puede
        # validar no puede aprobar el commit en silencio.
        self.assertRegex(
            self.texto, r"ningún intérprete con PyYAML[\s\S]{0,200}exit 1",
            "el hook debe abortar (exit 1) con mensaje si ningún intérprete tiene yaml",
        )


if __name__ == "__main__":
    unittest.main()