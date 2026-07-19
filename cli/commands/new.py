"""Comando new — Crear un concepto nuevo en el vault OKF con formato consistente."""

import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Types MECE permitidos
VALID_TYPES = {
    "Sistema", "Agente", "Decision", "Plan", "Project", "Insight",
    "MarcoTeorico", "LeccionAprendida", "Tool", "Spec", "Skill",
}

# Types que califican para bloque cyber:
CYBER_TYPES = {"Sistema", "Agente", "Decision", "Plan", "Project", "Insight"}

# Mapeo type → directorio
TYPE_DIR = {
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
}

BODY_TEMPLATES = {
    "Decision": """## Contexto

(¿Qué disparó esta decisión? ¿Qué problema resuelve?)

## Decisión

(¿Qué se decidió? ¿Qué alternativas se descartaron?)

## Impacto

(¿Qué cambia a partir de ahora?)
""",
    "Plan": """## Objetivo

(¿Qué se quiere lograr?)

## Fases

1.
2.
3.

## Métricas

(¿Cómo se mide el éxito?)
""",
    "Project": """## Visión

(¿Qué es este proyecto? ¿Por qué existe?)

## Estado

**Fase actual:** (planificación / desarrollo / producción / abandonado)

## Componentes

-
-
""",
    "Insight": """## Observación

(¿Qué patrón o conexión se detectó?)

## Implicación

(¿Qué significa esto? ¿Qué acción sugiere?)

## Verificación

(¿Cómo se confirma o descarta este insight?)
""",
    "Sistema": """## Qué hace

(¿Qué configuración o comportamiento controla en el sistema agéntico?)

## Dónde está

(¿Archivo de config, variable de entorno, skill?)

## Por qué

(¿Qué problema resuelve? ¿Qué pasaría si se quitara?)

## Relaciones

- 
""",
    "Agente": """## Rol

(¿Qué rol cumple este agente en el ecosistema?)

## Capacidades

- 
- 

## Configuración

(¿Modelo, tools, skills asignados?)

## AGENT.md / SOUL.md

(¿Dónde está su archivo de definición?)
""",
    "Skill": """## Identidad

| Campo | Valor |
|---|---|
| **Nombre** | (nombre de la skill) |
| **Repo** | (URL) |
| **Ruta Hermes** | `~/.hermes/skills/<categoria>/<nombre>/` |

## Qué hace

(¿Qué problema resuelve esta skill? ¿Cuándo debe cargarla el agente?)

## Dependencias

- 
- 

## Archivos

(¿SKILL.md, references/, scripts/?)
""",
}


def _slugify(text):
    """Convierte título a slug para nombre de archivo."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text


def _build_frontmatter(concept_type, title, description, status, resource, tags, cyber):
    """Genera el bloque YAML del frontmatter."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S-05:00")

    lines = ["---", f"type: {concept_type}"]
    lines.append(f'title: "{title.strip()}"')
    lines.append(f'description: "{description.strip()}"')

    if status:
        lines.append(f"status: {status}")

    if resource:
        lines.append(f'resource: "{resource}"')

    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        lines.append(f"tags: [{', '.join(tag_list)}]")

    lines.append(f"timestamp: {now}")

    if cyber and concept_type in CYBER_TYPES:
        review_date = (date.today() + timedelta(days=14)).isoformat()
        lines.append("cyber:")
        lines.append("  sensor: (completar)")
        lines.append('  perception: ""')
        lines.append('  target_metric: {name: "", target: 0}')
        lines.append("  actuator: []")
        lines.append("  corrects: []")
        lines.append("  outcome: pending")
        lines.append(f"  review_on: {review_date}")
    elif cyber:
        print(f"⚠️  --cyber ignorado: type '{concept_type}' no califica "
              f"(solo {', '.join(sorted(CYBER_TYPES))})", file=sys.stderr)

    lines.append("---")
    return "\n".join(lines) + "\n"


def run(args, vault):
    """Crea un concepto nuevo en el vault."""
    concept_type = getattr(args, "concept_type", None)
    title = getattr(args, "title", None)
    description = getattr(args, "description", None)
    tags = getattr(args, "tags", None)
    status = getattr(args, "status", None)
    resource = getattr(args, "resource", None)
    cyber = getattr(args, "cyber", False)
    dry_run = getattr(args, "dry_run", False)

    if concept_type not in VALID_TYPES:
        print(f"❌ Type inválido: '{concept_type}'", file=sys.stderr)
        print(f"   Válidos: {', '.join(sorted(VALID_TYPES))}", file=sys.stderr)
        return 1

    # Determinar directorio y nombre de archivo
    subdir = TYPE_DIR[concept_type]
    slug = _slugify(title)
    filename = f"{slug}.md"
    filepath = vault / subdir / filename

    if filepath.exists():
        print(f"❌ Ya existe: {filepath}", file=sys.stderr)
        return 1

    frontmatter = _build_frontmatter(concept_type, title, description,
                                     status, resource, tags, cyber)
    template = BODY_TEMPLATES.get(concept_type, "## Contexto\n\n(Contenido)\n")
    body = f"\n# {title.strip()}\n\n{template}"
    content = frontmatter + body

    if dry_run:
        print(f"🔍 DRY-RUN — {filepath}")
        print("─" * 60)
        print(content)
        print("─" * 60)
        return 0

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")

    print(f"✅ Creado: {filepath}")
    print(f"   Type: {concept_type} | Status: {status or '(sin status)'}")
    if cyber and concept_type in CYBER_TYPES:
        print(f"   🧠 Bloque cyber: incluido (outcome: pending, review_on: +14d)")
    print(f"\n   Siguiente paso: editar body y hacer commit.")
    return 0
