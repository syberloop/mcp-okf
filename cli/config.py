"""Configuración externalizada del MCP OKF.

Resolución en cadena:
    1. --config <path>           → argumento explícito del CLI
    2. $OKF_CONFIG               → variable de entorno
    3. <vault>/.okf.config.yaml  → junto al vault (95% de los casos)
    4. ~/.config/okf/config.yaml → global del usuario
    5. defaults embebidos        → réplica exacta de la configuración actual de Jaime

Principio: hardcodear reglas fundamentales del dominio, configurar lo que cambia.
El contrato core (type + description + wikilinks) ES regla fundamental → hardcodeado.
Taxonomía, umbrales, feature flags → configurables.
"""

import os
from pathlib import Path
from typing import Any


# ── Defaults embebidos ──────────────────────────────────────────────────────
# Réplica exacta de los hardcodeos actuales. Si no existe .okf.config.yaml,
# el comportamiento es idéntico al actual para Jaime.

DEFAULTS: dict[str, Any] = {
    "types": {
        "valid": [
            "Sistema", "Agente", "Decision", "Plan", "Project", "Insight",
            "MarcoTeorico", "LeccionAprendida", "Tool", "Spec", "Skill", "Workflow",
        ],
        "cyber": ["Sistema", "Agente", "Decision", "Plan", "Project", "Insight"],
        "excluded_cyber": ["MarcoTeorico", "LeccionAprendida", "Tool", "Spec"],
        "directory": {
            "Sistema": "sistema",
            "Agente": "agentes",
            "Decision": "decisions",
            "Plan": "plans",
            "Project": "projects",
            "Insight": "insights",
            "MarcoTeorico": "frameworks",
            "LeccionAprendida": "historias",
            "Tool": "specs",
            "Spec": "specs",
            "Skill": "sistema/skills",
            "Workflow": "workflows",
        },
    },
    "stale": {
        "timestamp_days": 90,
        "propuesta_days": 30,
        "no_commits_days": 180,
        "checkbox_ratio": 0.7,
        # Patrones de lenguaje de problema en description (regex, case-insensitive)
        # Señal 7 del detector: si la description habla de problemas y los
        # checkboxes del body están ≥70% completos, la description está obsoleta.
        "problem_patterns": [
            r"\bno\s+(existe|funciona|hay|tiene|está|implementado|conectado|almacena|notifica)\b",
            r"\broto[s]?\b",
            r"\bfalso[s]?\b",
            r"\bfalta[n]?\b",
            r"\bsin\s+(implementar|resolver|definir|conectar|backend)\b",
            r"\bpendiente[s]?\b",
            r"\bincompleto\b",
            r"\bplaceholder\b",
            r"\bclaims?\s+fals[oa]s?\b",
            r"\b404\b",
            r"\bCTAs?\s+rot[oa]s?\b",
            r"\bcero\s+métricas\b",
            r"\bno\s+está\b",
            r"\bse\s+pierden\b",
        ],
    },
    "cyber": {
        "review_days": 14,
    },
    "health": {
        "smoke_entry_point": "tp3-cibernetico",
    },
    "exclude": {
        "files": ["index.md", "log.md", "dashboard.md"],
        "dirs": [".git", ".obsidian", "Templates", "scripts", "references", "assets"],
    },
    "features": {
        "cognitive_trace": True,
        "plugin_hash_sync": True,
        # Paths para Cognitive Trace (solo relevantes si cognitive_trace: true)
        # - db_path: ruta al SQLite de eventos (default: ~/.hermes/cognitive-trace.db)
        # - jsonl_path: ruta al JSONL para el plugin de Obsidian
        #   (default: <vault>/.obsidian/plugins/cognitive-trace/event_log.jsonl)
        # Usar null para aceptar el default.
        "trace_db_path": None,
        "trace_jsonl_path": None,
    },
    "templates": {
        "Decision": (
            "## Contexto\n\n"
            "(¿Qué disparó esta decisión? ¿Qué problema resuelve?)\n\n"
            "## Decisión\n\n"
            "(¿Qué se decidió? ¿Qué alternativas se descartaron?)\n\n"
            "## Impacto\n\n"
            "(¿Qué cambia a partir de ahora?)\n"
        ),
        "Plan": (
            "## Objetivo\n\n"
            "(¿Qué se quiere lograr?)\n\n"
            "## Fases\n\n"
            "1.\n2.\n3.\n\n"
            "## Métricas\n\n"
            "(¿Cómo se mide el éxito?)\n"
        ),
        "Project": (
            "## Visión\n\n"
            "(¿Qué es este proyecto? ¿Por qué existe?)\n\n"
            "## Estado\n\n"
            "**Fase actual:** (planificación / desarrollo / producción / abandonado)\n\n"
            "## Componentes\n\n"
            "-\n-\n"
        ),
        "Insight": (
            "## Observación\n\n"
            "(¿Qué patrón o conexión se detectó?)\n\n"
            "## Implicación\n\n"
            "(¿Qué significa esto? ¿Qué acción sugiere?)\n\n"
            "## Verificación\n\n"
            "(¿Cómo se confirma o descarta este insight?)\n"
        ),
        "Sistema": (
            "## Qué hace\n\n"
            "(¿Qué configuración o comportamiento controla en el sistema agéntico?)\n\n"
            "## Dónde está\n\n"
            "(¿Archivo de config, variable de entorno, skill?)\n\n"
            "## Por qué\n\n"
            "(¿Qué problema resuelve? ¿Qué pasaría si se quitara?)\n\n"
            "## Relaciones\n\n"
            "- \n"
        ),
        "Agente": (
            "## Rol\n\n"
            "(¿Qué rol cumple este agente en el ecosistema?)\n\n"
            "## Capacidades\n\n"
            "- \n- \n\n"
            "## Configuración\n\n"
            "(¿Modelo, tools, skills asignados?)\n\n"
            "## AGENT.md / SOUL.md\n\n"
            "(¿Dónde está su archivo de definición?)\n"
        ),
        "Skill": (
            "## Identidad\n\n"
            "| Campo | Valor |\n"
            "|---|---|\n"
            "| **Nombre** | (nombre de la skill) |\n"
            "| **Repo** | (URL) |\n"
            "| **Ruta Hermes** | `~/.hermes/skills/<categoria>/<nombre>/` |\n\n"
            "## Qué hace\n\n"
            "(¿Qué problema resuelve esta skill? ¿Cuándo debe cargarla el agente?)\n\n"
            "## Dependencias\n\n"
            "- \n- \n\n"
            "## Archivos\n\n"
            "(¿SKILL.md, references/, scripts/?)\n"
        ),
        "Workflow": (
            "## Qué problema resuelve\n\n"
            "(¿Qué problema resuelve este workflow? ¿Cuándo debería un agente sugerirlo?)\n\n"
            "## Arquitectura\n\n"
            "(Componentes abstractos: sensor → criterio → clasificación → acción)\n\n"
            "## Procedimiento\n\n"
            "1. \n2. \n3. \n\n"
            "## Criterios de calidad\n\n"
            "(¿Cómo saber si el workflow está funcionando?)\n\n"
            "## Instanciación en OKF\n\n"
            "(Referencia a la instancia concreta en nuestro ecosistema)\n"
        ),
    },
}


class Config:
    """Configuración del MCP OKF, resuelta desde archivo o defaults."""

    def __init__(self, vault: Path, cli_config_arg: str | None = None):
        self._vault = vault
        self._data: dict[str, Any] = {}
        self._load(cli_config_arg)

    def _load(self, cli_config_arg: str | None) -> None:
        """Resuelve la cadena de configuración y mergea sobre defaults."""
        import yaml

        config_path = self._resolve_path(cli_config_arg)
        if config_path:
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    user_config = yaml.safe_load(f) or {}
                self._data = self._deep_merge(DEFAULTS, user_config)
            except Exception:
                # YAML roto o archivo ilegible → usar defaults
                self._data = DEFAULTS
        else:
            self._data = DEFAULTS

    def _resolve_path(self, cli_config_arg: str | None) -> Path | None:
        """Resuelve la ruta del archivo de configuración en cadena."""
        # 1. Argumento explícito del CLI
        if cli_config_arg:
            path = Path(cli_config_arg)
            if not path.is_absolute():
                path = Path.cwd() / path
            if path.exists():
                return path.resolve()

        # 2. Variable de entorno
        env_config = os.environ.get("OKF_CONFIG")
        if env_config:
            path = Path(env_config).expanduser()
            if path.exists():
                return path.resolve()

        # 3. Raíz del vault (.okf.config.yaml, oculto)
        vault_config = self._vault / ".okf.config.yaml"
        if vault_config.exists():
            return vault_config

        # 4. Global del usuario
        global_config = Path.home() / ".config" / "okf" / "config.yaml"
        if global_config.exists():
            return global_config

        # 5. Sin archivo → defaults
        return None

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """Merge recursivo: override pisa solo las claves que define."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    # ── Acceso tipado ───────────────────────────────────────────────────────

    @property
    def types_valid(self) -> list[str]:
        return list(self._data["types"]["valid"])

    @property
    def types_cyber(self) -> list[str]:
        return list(self._data["types"]["cyber"])

    @property
    def types_excluded_cyber(self) -> set[str]:
        return set(self._data["types"]["excluded_cyber"])

    @property
    def types_directory(self) -> dict[str, str]:
        return dict(self._data["types"]["directory"])

    @property
    def stale_timestamp_days(self) -> int:
        return int(self._data["stale"]["timestamp_days"])

    @property
    def stale_propuesta_days(self) -> int:
        return int(self._data["stale"]["propuesta_days"])

    @property
    def stale_no_commits_days(self) -> int:
        return int(self._data["stale"]["no_commits_days"])

    @property
    def stale_checkbox_ratio(self) -> float:
        return float(self._data["stale"]["checkbox_ratio"])

    @property
    def stale_problem_patterns(self) -> list[str]:
        return list(self._data["stale"].get("problem_patterns", []))

    @property
    def cyber_review_days(self) -> int:
        return int(self._data["cyber"]["review_days"])

    @property
    def health_smoke_entry_point(self) -> str:
        return str(self._data["health"]["smoke_entry_point"])

    @property
    def exclude_files(self) -> set[str]:
        return set(self._data["exclude"]["files"])

    @property
    def exclude_dirs(self) -> set[str]:
        return set(self._data["exclude"]["dirs"])

    @property
    def features_cognitive_trace(self) -> bool:
        return bool(self._data["features"]["cognitive_trace"])

    @property
    def features_plugin_hash_sync(self) -> bool:
        new_flag = self._data["features"].get("plugin_hash_sync")
        if new_flag is not None:
            return bool(new_flag)
        # backward compat: fallback al flag viejo si existe
        old_flag = self._data["features"].get("cognitive_trace")
        return bool(old_flag) if old_flag is not None else True

    def get_template(self, concept_type: str) -> str:
        """Devuelve el template de body para un type, o uno genérico si no hay."""
        templates = self._data.get("templates", {})
        if isinstance(templates, dict):
            tmpl = templates.get(concept_type, "")
            if tmpl:
                return str(tmpl)
        return "## Contexto\n\n(Contenido)\n"
