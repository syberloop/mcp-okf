"""Command new — Create a new concept in the OKF vault with consistent formatting."""

import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Types MECE permitidos — defaults (pisan por Config si existe .okf.config.yaml)
VALID_TYPES = {
    "Sistema", "Agente", "Decision", "Plan", "Project", "Insight",
    "MarcoTeorico", "LeccionAprendida", "Tool", "Spec", "Skill", "Workflow", "Criterio",
    "Sesion", "Research", "Mapa", "Harness",
}

# Types que califican para bloque cyber: — defaults
CYBER_TYPES = {"Sistema", "Agente", "Decision", "Plan", "Project", "Insight", "Harness"}

# Mapeo type → directorio — defaults
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
    "Skill": "skills",
    "Workflow": "workflows",
    "Criterio": "criterios",
    "Sesion": "sesiones",
    "Research": "research",
    "Mapa": "mapas",
    "Harness": "harnesses",
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
    "Harness": """## Tool objetivo

(¿Qué tool envuelve este harness? bash, playwright, git, mcp-okf...)

## Script

(¿Ruta al script que implementa el harness? Ej: ~/.hermes/scripts/terminal_harness.py)

## Uso

```bash
python3 <script> "<comando>" [timeout]
```

## Protocolo de respuesta

| Campo | Tipo | Valores |
|-------|------|---------|
| status | enum | success \\| retry \\| needs_reasoning \\| fatal |
| category | string | ok, timeout, permission_denied, ... |
| exit_code | int | Código de salida real |
| suggestion | string | Acción recomendada para el LLM |

## Categorías de error

### RETRY

| Categoría | Patrón | Sugerencia |
|-----------|--------|------------|

### NEEDS_REASONING

| Categoría | Patrón | Sugerencia |
|-----------|--------|------------|

### FATAL

| Categoría | Patrón | Sugerencia |
|-----------|--------|------------|

## Relacionado

- [[agentes/]] — agentes que consumen este harness
- [[specs/harnesses-como-nodos-del-grafo]] — spec del type Harness
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
    "Workflow": """## Qué problema resuelve

(¿Qué problema resuelve este workflow? ¿Cuándo debería un agente sugerirlo?)

## Arquitectura

(Componentes abstractos: sensor → criterio → clasificación → acción)

## Procedimiento

1. 
2. 
3. 

## Criterios de calidad

(¿Cómo saber si el workflow está funcionando?)

## Instanciación en OKF

(Referencia a la instancia concreta en nuestro ecosistema)
""",
}


def _slugify(text):
    """Converts title to slug for filename."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text


def _parse_links(links):
    """Parse --link 'target:type' flags into a list of dicts.

    Args:
        links: list[str] | None — each element is "target:type".

    Returns:
        list[dict]: [{"target": "path.md", "type": "edge_type"}, ...]

    Raises:
        ValueError: If the format is invalid.
    """
    if not links:
        return []
    result = []
    for raw in links:
        if ":" not in raw:
            raise ValueError(
                f"Invalid format: '{raw}'. Use 'target:type' "
                f"(e.g.: frameworks/tp3-cibernetico:extiende)"
            )
        target, edge_type = raw.rsplit(":", 1)
        target = target.strip()
        edge_type = edge_type.strip()
        if not target:
            raise ValueError(f"Empty target in: '{raw}'")
        if not edge_type:
            raise ValueError(f"Empty type in: '{raw}'")
        result.append({"target": target, "type": edge_type})
    return result


def _build_frontmatter(concept_type, title, description, status, resource, tags,
                       cyber, links=None, config=None):
    """Generate the frontmatter YAML block.

    Args:
        links: list[dict] | None — list of {"target": str, "type": str}.
    """
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
    lines.append(f"created: {now}")

    # --- links: field (NUEVO) ---
    if links:
        lines.append("links:")
        for link in links:
            lines.append(f"  - target: {link['target']}")
            lines.append(f"    type: {link['type']}")

    # Resolver cyber_types desde config o fallback
    cyber_types = set(config.types_cyber) if config else CYBER_TYPES

    if cyber and concept_type in cyber_types:
        review_days = config.cyber_review_days if config else 14
        review_date = (date.today() + timedelta(days=review_days)).isoformat()
        lines.append("cyber:")
        lines.append("  sensor: (completar)")
        lines.append('  perception: ""')
        lines.append('  target_metric: {name: "", target: 0}')
        lines.append("  actuator: []")
        lines.append("  corrects: []")
        lines.append("  outcome: pending")
        lines.append(f"  review_on: {review_date}")
    elif cyber:
        print(f"⚠️  --cyber ignored: type '{concept_type}' does not qualify "
              f"(only {', '.join(sorted(cyber_types))})", file=sys.stderr)

    lines.append("---")
    return "\n".join(lines) + "\n"


def run(args, vault, config=None):
    """Create a new concept in the vault."""
    concept_type = getattr(args, "concept_type", None)
    title = getattr(args, "title", None)
    description = getattr(args, "description", None)
    tags = getattr(args, "tags", None)
    status = getattr(args, "status", None)
    resource = getattr(args, "resource", None)
    cyber = getattr(args, "cyber", False)
    dry_run = getattr(args, "dry_run", False)
    body_text = getattr(args, "body", None)
    body_file = getattr(args, "body_file", None)
    links_raw = getattr(args, "links", None)

    # Resolver desde config o fallback a defaults
    valid_types = set(config.types_valid) if config else VALID_TYPES
    type_dir = dict(config.types_directory) if config else TYPE_DIR

    if concept_type not in valid_types:
        print(f"❌ Invalid type: '{concept_type}'", file=sys.stderr)
        print(f"   Valid: {', '.join(sorted(valid_types))}", file=sys.stderr)
        return 1

    # Determinar directorio y nombre de archivo
    subdir = type_dir[concept_type]
    slug = _slugify(title)
    # Skill usa subdirectorio propio con SKILL.md (convención post-refactor)
    if concept_type == "Skill":
        filename = "SKILL.md"
        filepath = vault / subdir / slug / filename
    else:
        filename = f"{slug}.md"
        filepath = vault / subdir / filename

    if filepath.exists():
        print(f"❌ Already exists: {filepath}", file=sys.stderr)
        return 1

    # --- Parsear y validar links (NUEVO) ---
    parsed_links = []
    if links_raw:
        try:
            parsed_links = _parse_links(links_raw)
        except ValueError as e:
            print(f"❌ {e}", file=sys.stderr)
            return 1

        # Validación bloqueante: targets, edge_types, duplicados
        from cli.edge_types import VALID_EDGE_TYPES
        from cli.commands.graph import build_graph
        from cli.frontmatter import validate_cross_type

        graph = build_graph(vault)

        for link in parsed_links:
            target = link["target"]
            edge_type = link["type"]

            if edge_type not in VALID_EDGE_TYPES:
                print(
                    f"❌ Invalid edge type: '{edge_type}'. "
                    f"Use: {', '.join(sorted(VALID_EDGE_TYPES))}",
                    file=sys.stderr,
                )
                return 1

            target_file = vault / target
            resolved = None
            if target_file.exists():
                resolved = str(target_file.relative_to(vault))
            else:
                try_target = target if target.endswith(".md") else target + ".md"
                for node in graph:
                    if try_target in node or try_target == node:
                        resolved = node
                        break

            if resolved is None or resolved not in graph:
                print(
                    f"❌ Invalid link: '{target}' does not exist in the graph. "
                    f"The target must be an existing node.",
                    file=sys.stderr,
                )
                return 1

            link["target"] = resolved

        seen = set()
        for link in parsed_links:
            key = (link["target"], link["type"])
            if key in seen:
                print(
                    f"❌ Duplicate link: target='{link['target']}' "
                    f"type='{link['type']}'",
                    file=sys.stderr,
                )
                return 1
            seen.add(key)

        source_path = f"{subdir}/{filename}"
        cross_warnings = validate_cross_type(
            concept_type, source_path, parsed_links, vault, graph
        )
        for w in cross_warnings:
            print(f"⚠️  {w}", file=sys.stderr)

    frontmatter = _build_frontmatter(concept_type, title, description,
                                     status, resource, tags, cyber,
                                     links=parsed_links, config=config)
    if body_file:
        try:
            body_text = Path(body_file).read_text(encoding="utf-8")
        except Exception as e:
            print(f"❌ Error reading body-file: {e}", file=sys.stderr)
            return 1
    if body_text:
        body = f"\n{body_text.strip()}\n"
    else:
        template = config.get_template(concept_type) if config else BODY_TEMPLATES.get(concept_type, "## Contexto\n\n(Contenido)\n")
        body = f"\n{template}"
    content = frontmatter + body

    if dry_run:
        print(f"🔍 DRY-RUN — {filepath}")
        print("─" * 60)
        print(content)
        print("─" * 60)
        return 0

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")

    print(f"✅ Created: {filepath}")
    print(f"   Type: {concept_type} | Status: {status or '(no status)'}")
    if cyber and concept_type in (set(config.types_cyber) if config else CYBER_TYPES):
        print(f"   🧠 Cyber block: included (outcome: pending, review_on: +{config.cyber_review_days if config else 14}d)")
    print(f"\n   Next step: edit body and commit.")
    return 0
