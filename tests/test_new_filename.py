"""`new` no permitía fijar el nombre del archivo ni omitir title/timestamp.

Caso real (pipeline de resúmenes de sesión, t_d661f16d): el formato de
`sesiones/` exige filename `sesion-<session_id>.md` (guiones bajos, que
`_slugify` convierte a guiones) y frontmatter SIN title/timestamp/created.
Sin `--filename`/`--no-timestamps`/`--field`, el resumidor no podía crear el
archivo solo con MCP (`new` escribía `sesiones/.md` con title="").
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli.commands.new import _build_frontmatter, run  # noqa: E402
from cli.frontmatter import parse_frontmatter, validate_frontmatter  # noqa: E402

SESSION_ID = "20260908_172301_5ef849fd"
RESUMEN = ("Telegram (Jaime): 'analiza esto' -> video de AI LABS sobre Graft "
           "(trailhq/NanoNets, MIT): context layer de codigo determinista.")


def _parse_fm(text: str) -> dict:
    fields, _ = parse_frontmatter(text)
    assert fields is not None, "el archivo generado no tiene frontmatter válido"
    return fields


class TestFilenameOverride(unittest.TestCase):
    """`--filename` fija el nombre exacto, sin pasar por el slug del título."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "sesiones").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _args(self, **kwargs):
        defaults = {
            "concept_type": "Sesion",
            "title": None,
            "description": RESUMEN,
            "tags": "sesion,resumen",
            "status": "aplicada",
            "resource": None,
            "cyber": False,
            "dry_run": False,
            "body": None,
            "body_file": None,
            "links": None,
            "entity": None,
            "force": False,
            "filename": None,
            "fields": None,
            "omit_timestamps": False,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_filename_exacto_conserva_guiones_bajos(self):
        args = self._args(filename=f"sesion-{SESSION_ID}.md")
        self.assertEqual(run(args, self.vault), 0)
        creado = self.vault / "sesiones" / f"sesion-{SESSION_ID}.md"
        self.assertTrue(creado.exists(), f"no existe {creado}")

    def test_filename_sin_extension_recibe_md(self):
        args = self._args(filename=f"sesion-{SESSION_ID}")
        self.assertEqual(run(args, self.vault), 0)
        self.assertTrue((self.vault / "sesiones" / f"sesion-{SESSION_ID}.md").exists())

    def test_contrato_del_resumen_sin_title_ni_timestamps(self):
        """Frontmatter exacto de la serie: type, description, tags, status, session_id."""
        args = self._args(
            filename=f"sesion-{SESSION_ID}.md",
            fields=[f"session_id={SESSION_ID}"],
            omit_timestamps=True,
            body="[[insights/x]]\n\n## Métricas\n\n- Tools usadas: read (2)\n",
        )
        self.assertEqual(run(args, self.vault), 0)
        text = (self.vault / "sesiones" / f"sesion-{SESSION_ID}.md").read_text(encoding="utf-8")
        fields = _parse_fm(text)

        self.assertEqual(set(fields), {"type", "description", "tags", "status", "session_id"})
        self.assertEqual(fields["type"], "Sesion")
        self.assertEqual(fields["description"], RESUMEN)
        self.assertEqual(fields["tags"], ["sesion", "resumen"])
        self.assertEqual(fields["status"], "aplicada")
        self.assertEqual(fields["session_id"], SESSION_ID)
        self.assertEqual(validate_frontmatter(fields), [])
        self.assertIn("## Métricas", text)

    def test_sin_title_ni_filename_falla_y_no_crea_basura(self):
        """Antes: `new --title ''` creaba literalmente sesiones/.md."""
        args = self._args(title="")
        self.assertEqual(run(args, self.vault), 1)
        self.assertEqual(list((self.vault / "sesiones").iterdir()), [])

    def test_filename_con_separador_de_ruta_falla(self):
        for malo in ("../fuera.md", "sub/archivo.md", "sub\\archivo.md", ".."):
            with self.subTest(filename=malo):
                self.assertEqual(run(self._args(filename=malo), self.vault), 1)
        self.assertEqual(list((self.vault / "sesiones").iterdir()), [])

    def test_title_sigue_derivando_el_slug_sin_filename(self):
        args = self._args(title="Sesion 20260908_172301_5ef849fd")
        self.assertEqual(run(args, self.vault), 0)
        self.assertTrue((self.vault / "sesiones" / "sesion-20260908-172301-5ef849fd.md").exists())

    def test_skill_filename_nombra_el_directorio(self):
        (self.vault / "skills").mkdir()
        args = self._args(concept_type="Skill", filename="mi-skill")
        self.assertEqual(run(args, self.vault), 0)
        self.assertTrue((self.vault / "skills" / "mi-skill" / "SKILL.md").exists())

    def test_force_sigue_funcionando_con_filename(self):
        args = self._args(filename=f"sesion-{SESSION_ID}.md", force=True)
        self.assertEqual(run(args, self.vault), 0)
        self.assertEqual(run(args, self.vault), 0)


class TestExtraFields(unittest.TestCase):
    """`--field key=value` (top-level) — dialecto compartido con `edit --field`."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "sesiones").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _args(self, **kwargs):
        defaults = {
            "concept_type": "Sesion",
            "title": None,
            "description": RESUMEN,
            "tags": None,
            "status": "aplicada",
            "resource": None,
            "cyber": False,
            "dry_run": False,
            "body": None,
            "body_file": None,
            "links": None,
            "entity": None,
            "force": False,
            "filename": "prueba.md",
            "fields": None,
            "omit_timestamps": True,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_field_escalar_se_escribe_en_frontmatter(self):
        args = self._args(fields=[f"session_id={SESSION_ID}"])
        self.assertEqual(run(args, self.vault), 0)
        fields = _parse_fm((self.vault / "sesiones" / "prueba.md").read_text(encoding="utf-8"))
        self.assertEqual(fields["session_id"], SESSION_ID)

    def test_field_json_produce_yaml_valido(self):
        args = self._args(fields=['vecindarios=[{"slug": "insights/x", "depth": 1}]'])
        self.assertEqual(run(args, self.vault), 0)
        fields = _parse_fm((self.vault / "sesiones" / "prueba.md").read_text(encoding="utf-8"))
        self.assertEqual(fields["vecindarios"], [{"slug": "insights/x", "depth": 1}])

    def test_field_reservado_falla(self):
        for spec in ("description=otra", "type=Insight", "timestamp=2020-01-01T00:00:00-05:00"):
            with self.subTest(spec=spec):
                self.assertEqual(run(self._args(fields=[spec]), self.vault), 1)

    def test_field_sin_igual_y_valor_vacio_fallan(self):
        for spec in ("session_id", "session_id="):
            with self.subTest(spec=spec):
                self.assertEqual(run(self._args(fields=[spec]), self.vault), 1)

    def test_field_duplicado_falla(self):
        self.assertEqual(run(self._args(fields=["a=1", "a=2"]), self.vault), 1)


class TestFrontmatterOpcionales(unittest.TestCase):
    """Unidad: `_build_frontmatter` con title/timestamps opcionales."""

    def _fm(self, **kwargs):
        return _build_frontmatter(
            kwargs.pop("concept_type", "Sesion"),
            kwargs.pop("title", None),
            kwargs.pop("description", "descripcion de prueba"),
            kwargs.pop("status", "aplicada"),
            kwargs.pop("resource", None),
            kwargs.pop("tags", "sesion,resumen"),
            kwargs.pop("cyber", False),
            **kwargs,
        )

    def _yaml(self, fm_text):
        lines = fm_text.splitlines()
        end = lines.index("---", 1)
        return yaml.safe_load("\n".join(lines[1:end]))

    def test_sin_title_no_escribe_la_clave(self):
        fm = self._yaml(self._fm())
        self.assertNotIn("title", fm)

    def test_title_vacio_no_escribe_la_clave(self):
        self.assertNotIn("title", self._yaml(self._fm(title="   ")))

    def test_title_presente_si_se_pasa(self):
        self.assertEqual(self._yaml(self._fm(title="Un titulo"))["title"], "Un titulo")

    def test_timestamps_presentes_por_defecto(self):
        fm = self._yaml(self._fm())
        self.assertIn("timestamp", fm)
        self.assertIn("created", fm)

    def test_omit_timestamps_los_quita(self):
        fm = self._yaml(self._fm(omit_timestamps=True))
        self.assertNotIn("timestamp", fm)
        self.assertNotIn("created", fm)

    def test_extra_lines_antes_de_timestamps(self):
        fm_text = self._fm(extra_lines=["session_id: abc123"])
        lineas = fm_text.splitlines()
        idx_extra = lineas.index("session_id: abc123")
        idx_ts = next(i for i, l in enumerate(lineas) if l.startswith("timestamp:"))
        self.assertLess(idx_extra, idx_ts)
        self.assertEqual(self._yaml(fm_text)["session_id"], "abc123")

    def test_handoff_igual_usa_now_sin_timestamps(self):
        """El bloque Handoff depende de `now`; omitir timestamps no lo rompe."""
        fm = self._yaml(self._fm(concept_type="Handoff", omit_timestamps=True))
        self.assertIn("last_activity_at", fm)
        self.assertIn("checkpoint_at", fm)
        self.assertNotIn("timestamp", fm)


if __name__ == "__main__":
    unittest.main()
