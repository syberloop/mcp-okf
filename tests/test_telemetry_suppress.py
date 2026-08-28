"""El smoke test de health no debe dejar telemetría.

`_check_scripts` lanza 8 subprocesos del CLI para comprobar que los comandos
responden. Son verificación, no uso: registrarlos hace que las agregaciones
describan al health check en lugar del trabajo real. Sobre un vault real, 414
de 426 eventos (97 %) eran health y su smoke.

`OKF_SUPPRESS_TELEMETRY=1` cierra esa puerta, con la misma forma que la que ya
existía para `OKF_MCP_CALLER`.
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli import telemetry


class TelemetrySuppressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "trace.db"
        self.jsonl = root / "event_log.jsonl"
        cfg = SimpleNamespace(
            features_cognitive_trace=True,
            _data={"features": {"trace_db_path": str(self.db),
                                "trace_jsonl_path": str(self.jsonl)}},
        )
        telemetry.init(root, cfg)

    def tearDown(self):
        self.tmp.cleanup()

    def _eventos(self):
        if not self.db.exists():
            return 0
        with sqlite3.connect(self.db) as conn:
            return conn.execute("select count(*) from events").fetchone()[0]

    def _record(self):
        telemetry.record("okf_search", {"query": "x"}, 0, 5, "", "")

    def test_sin_la_env_var_si_registra(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("OKF_SUPPRESS_TELEMETRY", "OKF_MCP_CALLER")}
        with patch.dict(os.environ, env, clear=True):
            self._record()
        self.assertEqual(self._eventos(), 1)

    def test_con_la_env_var_no_registra(self):
        env = {k: v for k, v in os.environ.items() if k != "OKF_MCP_CALLER"}
        env["OKF_SUPPRESS_TELEMETRY"] = "1"
        with patch.dict(os.environ, env, clear=True):
            self._record()
        self.assertEqual(
            self._eventos(), 0,
            "el smoke test seguiria registrando: las metricas miden al verificador",
        )

    def test_solo_el_valor_1_suprime(self):
        """Una variable presente pero en '0' no debe apagar la telemetría."""
        env = {k: v for k, v in os.environ.items() if k != "OKF_MCP_CALLER"}
        env["OKF_SUPPRESS_TELEMETRY"] = "0"
        with patch.dict(os.environ, env, clear=True):
            self._record()
        self.assertEqual(self._eventos(), 1)


class SmokeTestEnvTests(unittest.TestCase):
    def test_health_marca_sus_subprocesos(self):
        """_check_scripts debe pasar la variable a los subprocesos del smoke."""
        import inspect
        from cli.commands import health
        src = inspect.getsource(health._check_scripts)
        self.assertIn(
            "OKF_SUPPRESS_TELEMETRY", src,
            "el smoke test no marca sus subprocesos: cada health dejaria 8 eventos",
        )


if __name__ == "__main__":
    unittest.main()
