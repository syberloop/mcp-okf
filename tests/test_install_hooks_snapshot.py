"""Regresión: `install.sh --with-hooks` también genera el snapshot del DashboardView.

`--with-cognitive-trace` instala un plugin cuyo DashboardView lee dashboard.json
y, si falta, dice «Snapshot no generado aún — se regenera en cada commit». Pero
el único que llamaba a `dashboard-snapshot` era hooks/pre-commit, el hook del
vault del sistema: la config que `--with-hooks` escribe para cualquier otro
vault corría validate → index → health y nada más. Medido el 2026-09-11 en
nuestro vault: 18 commits desde que llegó el DashboardView y 0 snapshots; el
generador corrido a mano tarda 1 s.

Los tests corren el bloque real de install.sh (sección 9), no una copia.
"""
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _bloque_with_hooks():
    texto = (REPO / "install.sh").read_text(encoding="utf-8")
    marca = texto.index("# 9. [OPTIONAL] --with-hooks")
    inicio = texto.index("\n", texto.index("# ═", marca)) + 1
    fin = texto.index("# ── Done ──", inicio)
    return texto[inicio:fin]


def _concepto():
    return (
        "---\n"
        "type: Insight\n"
        'title: "Prueba"\n'
        'description: "Concepto de prueba"\n'
        "timestamp: 2026-09-11T11:00:00-05:00\n"
        "---\n\nCuerpo.\n"
    )


class InstallHooksSnapshotTest(unittest.TestCase):

    def _instalar(self, vault):
        script = ("set -euo pipefail\n"
                  "RED=''; GREEN=''; YELLOW=''; BLUE=''; BOLD=''; NC=''\n"
                  "WITH_HOOKS=true; MODE_UPDATE=false\n"
                  f"VAULT={shlex.quote(str(vault))}\n" + _bloque_with_hooks())
        subprocess.run(["bash", "-c", script], check=True,
                       capture_output=True, text=True)

    def test_la_config_generada_produce_el_snapshot(self):
        import yaml
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d) / "mi vault"
            (vault / "insights").mkdir(parents=True)
            (vault / "insights" / "prueba.md").write_text(_concepto(), encoding="utf-8")
            self._instalar(vault)
            config = yaml.safe_load(
                (vault / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
            hooks = config["repos"][0]["hooks"]
            snap = [h for h in hooks if "dashboard-snapshot" in h["entry"]]
            self.assertEqual(len(snap), 1, "ningún hook de la config genera el snapshot")
            env = dict(os.environ, OKF_SUPPRESS_TELEMETRY="1", PYTHONPATH=str(REPO),
                       PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""))
            r = subprocess.run(shlex.split(snap[0]["entry"]), cwd=vault, env=env,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((vault / "dashboard.json").is_file())
            diarios = list((vault / "sistema" / "dashboard-snapshots").glob("*.json"))
            self.assertEqual(len(diarios), 1)

    def test_lo_que_escribe_el_snapshot_no_ensucia_el_repo(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            subprocess.run(["git", "init", "-q", str(vault)], check=True)
            # Sin salto de línea final y con una de las reglas ya presente.
            (vault / ".gitignore").write_text(".obsidian/\n/dashboard.json", encoding="utf-8")
            self._instalar(vault)
            lineas = (vault / ".gitignore").read_text(encoding="utf-8").splitlines()
            self.assertEqual(lineas.count(".obsidian/"), 1)
            self.assertEqual(lineas.count("/dashboard.json"), 1)
            self.assertEqual(lineas.count("/sistema/dashboard-snapshots/"), 1)
            (vault / "dashboard.json").write_text("{}", encoding="utf-8")
            (vault / "sistema" / "dashboard-snapshots").mkdir(parents=True)
            (vault / "sistema" / "dashboard-snapshots" / "2026-09-11.json").write_text(
                "{}", encoding="utf-8")
            estado = subprocess.run(
                ["git", "-C", str(vault), "status", "--porcelain", "--untracked-files=all"],
                capture_output=True, text=True, check=True).stdout
            self.assertNotIn("dashboard", estado)


if __name__ == "__main__":
    unittest.main()
