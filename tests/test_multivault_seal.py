"""Tests del sello de identidad de vault (patrón multi-vault).

Un server MCP por vault con el MISMO server.py: la única falla silenciosa
posible es invocar la tool del vault equivocado (`mcp__okf__new` en vez de
`mcp__okf_<cliente>__new`). Estos tests fijan las dos defensas:

1. El docstring de cada tool (que el agente lee como schema ANTES de llamar)
   declara el vault servido por esa instancia.
2. La salida de toda tool de ESCRITURA lleva `[vault: <nombre> (<ruta>)]`, y
   si el CLI cita un archivo fuera de este vault o uno que no existe, se añade
   `[ERROR: ...]` en vez de devolver un éxito silencioso.

NOTA: el caso del docstring se prueba en SUBPROCESO. Borrar `cli.*` de
sys.modules para reimportar `server` contamina los monkeypatches de otros
tests de la suite (verificado: rompía test_scope_readonly y
test_stale_reads_store). Un subproceso es además el escenario real: un
proceso MCP por vault.
"""

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

MCP_DIR = Path(__file__).resolve().parent.parent
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

import server as srv  # noqa: E402  (import único, sin recarga)


def _make_vault(root: Path, name: str = "skynet-vault") -> Path:
    vault = root / name
    (vault / "insights").mkdir(parents=True)
    (vault / ".okf.config.yaml").write_text(
        "types:\n  valid: [Insight]\n  directory:\n    Insight: insights\n"
    )
    return vault


class TestSelloSalida(unittest.TestCase):
    """_seal_output no depende del import: se monkeypatchea VAULT."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = _make_vault(Path(self.tmp.name))
        self._orig = srv.VAULT
        srv.VAULT = self.vault

    def tearDown(self):
        srv.VAULT = self._orig
        self.tmp.cleanup()

    def test_label_incluye_nombre_y_ruta(self):
        self.assertEqual(srv._vault_label(), f"skynet-vault ({self.vault})")

    def test_escritura_lleva_sello(self):
        out = srv._seal_output("✅ Created: insights/x.md\n   Type: Insight", "okf_new", 0)
        self.assertEqual(out.splitlines()[-1], f"[vault: skynet-vault ({self.vault})]")

    def test_lectura_no_lleva_sello(self):
        out = srv._seal_output("Graph: 3 nodes, 2 edges", "okf_graph", 0)
        self.assertEqual(out, "Graph: 3 nodes, 2 edges")

    def test_detecta_archivo_fuera_del_vault(self):
        ajeno = "/home/jota/OKF-Vault/research/otro.md"
        out = srv._seal_output(f"✅ Created: {ajeno}", "okf_new", 0)
        self.assertIn("[ERROR: la salida cita archivos fuera de este vault", out)
        self.assertIn(ajeno, out)

    def test_detecta_exito_fantasma(self):
        fantasma = str(self.vault / "insights" / "no-existe.md")
        out = srv._seal_output(f"✅ Created: {fantasma}", "okf_new", 0)
        self.assertIn("[ERROR: el CLI reporta éxito pero no existe", out)

    def test_exito_real_no_dispara_error(self):
        real = self.vault / "insights" / "si-existe.md"
        real.write_text("---\ntype: Insight\n---\n")
        out = srv._seal_output(f"✅ Created: {real}", "okf_new", 0)
        self.assertIn("[vault: ", out)
        self.assertNotIn("[ERROR", out)

    def test_ruta_relativa_no_se_confunde_con_absoluta(self):
        """`insights/x.md` no es `/x.md`: no debe disparar falso positivo."""
        out = srv._seal_output("✅ Created: insights/x.md", "okf_new", 0)
        self.assertNotIn("[ERROR", out)

    def test_fallo_se_sella_sin_verificar_exito(self):
        out = srv._seal_output("❌ 'Insight' exige el campo 'iniciativa'", "okf_new", 1)
        self.assertIn("[vault: ", out)
        self.assertNotIn("[ERROR: el CLI reporta éxito", out)

    def test_edit_tambien_se_sella(self):
        out = srv._seal_output("✅ Updated: decisions/x.md", "okf_edit", 0)
        self.assertIn("[vault: ", out)

    def test_dry_run_no_verifica_existencia(self):
        """dry_run no escribe: marcar 'éxito fantasma' ahí sería falso positivo.

        Detectado con el mini-cliente stdio real: los 3 servers daban
        `[ERROR: el CLI reporta éxito pero no existe]` en un dry_run válido.
        """
        fantasma = str(self.vault / "decisions" / "probe-sello.md")
        out = srv._seal_output(
            f"🔍 DRY-RUN — {fantasma}", "okf_new", 0, ["new", "--dry-run"]
        )
        self.assertIn("[vault: ", out)
        self.assertNotIn("[ERROR", out)


class TestDocstringDeclaraVault(unittest.TestCase):
    """Subproceso: el schema que ve el agente nombra el vault servido."""

    PROBE = textwrap.dedent(
        """
        import importlib.util, json, sys
        from pathlib import Path
        spec = importlib.util.spec_from_file_location("server_probe", {server!r})
        mod = importlib.util.module_from_spec(spec)
        sys.modules["server_probe"] = mod
        spec.loader.exec_module(mod)
        print(json.dumps({{
            "label": mod._vault_label(),
            "new_doc": mod.new.__doc__,
            "graph_doc": mod.graph.__doc__,
            "vault": str(mod.VAULT),
        }}))
        """
    )

    def _run_probe(self, vault: Path) -> dict:
        import json
        import os
        env = dict(os.environ, OKF_VAULT=str(vault))
        env.pop("OKF_READONLY", None)
        code = self.PROBE.format(server=str(MCP_DIR / "server.py"))
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, env=env, cwd=str(MCP_DIR), timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_schema_nombra_su_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp), "controlresearch-vault")
            data = self._run_probe(vault)
        self.assertEqual(data["vault"], str(vault))
        sello = f"Vault de esta instancia: controlresearch-vault ({vault})."
        self.assertIn(sello, data["new_doc"])
        self.assertIn(sello, data["graph_doc"])
        # el docstring original sobrevive
        self.assertIn("Creates a new concept", data["new_doc"])

    def test_dos_vaults_producen_dos_schemas_distintos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = _make_vault(root, "vault-a")
            b = _make_vault(root, "vault-b")
            da, db = self._run_probe(a), self._run_probe(b)
        self.assertIn("vault-a", da["new_doc"])
        self.assertIn("vault-b", db["new_doc"])
        self.assertNotEqual(da["new_doc"], db["new_doc"])


if __name__ == "__main__":
    unittest.main()
