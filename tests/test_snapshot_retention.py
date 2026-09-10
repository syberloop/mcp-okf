"""El histórico de dashboard-snapshot guarda 30 días, no para siempre.

Cada corrida escribe sistema/dashboard-snapshots/YYYY-MM-DD.json con el
snapshot completo (~14 líneas por concepto). El panel lee los últimos 30 y las
tendencias, el de hace 7 días; nada borraba los anteriores, así que la carpeta
sumaba un snapshot completo por día sin techo.
"""

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli.commands import dashboard_snapshot as ds  # noqa: E402

HOY = date(2026, 9, 10)


def _nombre(dias_atras: int) -> str:
    return f"{(HOY - timedelta(days=dias_atras)).isoformat()}.json"


class RetencionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        self.dir = self.vault / ds.SNAPSHOTS_DIR
        self.dir.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _crear(self, *dias_atras):
        for d in dias_atras:
            (self.dir / _nombre(d)).write_text("{}")

    def _nombres(self):
        return sorted(p.name for p in self.dir.iterdir())

    def test_conserva_los_ultimos_30_dias(self):
        self._crear(*range(40))
        borrados = ds._prune_snapshots(self.dir, HOY)
        self.assertEqual(len(borrados), 10)
        self.assertEqual(self._nombres(), sorted(_nombre(d) for d in range(30)))

    def test_conserva_el_baseline_de_las_tendencias(self):
        self._crear(7, 45)
        ds._prune_snapshots(self.dir, HOY)
        self.assertEqual(self._nombres(), [_nombre(7)])

    def test_no_toca_archivos_con_otro_nombre(self):
        otros = ["2026-1-1.json", "2026-13-45.json", "README.md", "notas.json"]
        for n in otros:
            (self.dir / n).write_text("x")
        self._crear(90)
        ds._prune_snapshots(self.dir, HOY)
        self.assertEqual(self._nombres(), sorted(otros))

    def test_write_snapshot_aplica_la_retencion(self):
        self._crear(31, 1)
        ds._write_snapshot(self.vault, {"generated_at": "x"}, HOY)
        self.assertEqual(self._nombres(), [_nombre(1), _nombre(0)])
        self.assertTrue((self.vault / "dashboard.json").exists())


if __name__ == "__main__":
    unittest.main()
