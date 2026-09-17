"""Regresión: la densidad del grafo no puede vetar los commits.

`_check_graph` metía «low density» en el mismo bucket de warnings que los
huérfanos. Con el pre-commit del vault corriendo `health --strict`, ese único
aviso rechazaba TODOS los commits — incluidos los del agente de sync.

La densidad es `aristas / (n * (n-1))`: el denominador crece con n² y las
aristas con n, así que decae sola a medida que el vault crece. Sostener 0.05
exige ~5 enlaces por concepto a los 100 nodos y ~10 a los 200: cualquier vault
que crezca termina bajo el umbral haga lo que haga. Es un KPI de forma del
portafolio, no un defecto.

Lo que este test fija:
  1. densidad por debajo del umbral NO genera warning;
  2. el número se sigue reportando (no se pierde la señal);
  3. los huérfanos SIGUEN siendo warning — la corrección no los arrastra.

Caso real: vault de 84 nodos y 321 aristas (densidad 0.046) sin poder commitear
del 2026-09-15 al 17. Mismo patrón que test_health_cyber_vencimiento.
"""
import tempfile
import unittest
from pathlib import Path


def _concepto(titulo, enlace=None):
    cuerpo = f"Cuerpo de {titulo}.\n"
    if enlace:
        cuerpo += f"\nVer [[insights/{enlace}]].\n"
    return (
        "---\n"
        "type: Insight\n"
        f'title: "{titulo}"\n'
        f'description: "Concepto {titulo} para la prueba de densidad"\n'
        "---\n\n" + cuerpo
    )


def _vault_en_cadena(directorio, n):
    """n conceptos encadenados: 0 huérfanos y densidad = 1/n."""
    vault = Path(directorio)
    (vault / "insights").mkdir(parents=True, exist_ok=True)
    for i in range(n):
        siguiente = f"nota-{i + 1:02d}" if i + 1 < n else None
        (vault / "insights" / f"nota-{i:02d}.md").write_text(
            _concepto(f"nota-{i:02d}", siguiente), encoding="utf-8")
    return vault


class HealthDensidadTest(unittest.TestCase):

    def _check(self, n, con_huerfano=False):
        from cli.commands.health import _check_graph
        with tempfile.TemporaryDirectory() as d:
            vault = _vault_en_cadena(d, n)
            if con_huerfano:
                (vault / "insights" / "suelta.md").write_text(
                    _concepto("suelta"), encoding="utf-8")
            return _check_graph(vault)

    def test_densidad_baja_no_genera_warning(self):
        datos, warnings = self._check(25)
        self.assertIsNotNone(datos, "el grafo no pudo analizarse")
        self.assertLess(datos["density"], 0.05,
                        "la fixture debe quedar bajo el umbral histórico")
        self.assertEqual(datos["orphans"], 0, "la cadena no debe dejar huérfanos")
        self.assertEqual(
            [w for w in warnings if "density" in w], [],
            f"la densidad no debe generar warning; llegaron: {warnings}")

    def test_la_densidad_se_sigue_reportando(self):
        datos, _ = self._check(25)
        self.assertIn("density", datos)
        self.assertGreater(datos["density"], 0.0)

    def test_huerfano_sigue_siendo_warning(self):
        datos, warnings = self._check(25, con_huerfano=True)
        self.assertEqual(datos["orphans"], 1)
        self.assertTrue(
            any("orphan" in w for w in warnings),
            f"un huérfano debe seguir bloqueando; warnings: {warnings}")


if __name__ == "__main__":
    unittest.main()
