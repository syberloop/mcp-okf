# OKF MCP Server

Servidor MCP (Model Context Protocol) para vaults OKF. Expone 14 tools que permiten a agentes de IA (Claude Code, Hermes, Cursor, etc.) consultar, crear y analizar conceptos en un vault de conocimiento sin acceso directo al filesystem.

## ¿Qué es OKF?

OKF (Open Knowledge Format) es una convención para representar conocimiento como archivos markdown con frontmatter YAML. El contrato mínimo es:

```markdown
---
type: Decision
title: "Mi primera decisión"
description: "Resumen de una línea explicando qué es este concepto"
---

Contenido libre en markdown. Podés usar [[wikilinks]] para
conectar conceptos entre sí.
```

Cada archivo `.md` es un **concepto**. Los conceptos se vinculan con wikilinks `[[slug]]` formando un grafo de conocimiento navegable. El MCP OKF expone ese grafo como tools semánticas para agentes de IA.

## Quick Start

### 1. Requisitos

- Python 3.12+
- `mcp` (FastMCP)

```bash
pip install mcp
```

### 2. Instalación

```bash
git clone <repo-url> okf-mcp
cd okf-mcp
pip install .
```

Esto instala el comando `okf-mcp` en el PATH.

### 3. Configurá tu vault

Copiá el archivo de ejemplo a la raíz de tu vault y editalo:

```bash
cp okf.config.example.yaml ~/mi-vault/.okf.config.yaml
```

Editá las secciones que necesites — como mínimo, cambiá `health.smoke_entry_point` por un concepto que exista en tu vault. Todas las claves son opcionales; si falta algo, se usa el default.

El MCP encuentra la configuración en este orden:
1. `--config <path>` en el CLI
2. Variable de entorno `$OKF_CONFIG`
3. `<vault>/.okf.config.yaml` (al lado de tus archivos `.md`)
4. `~/.config/okf/config.yaml` (global)
5. Defaults embebidos

Y el vault en este orden:
1. `--vault <path>` en el CLI
2. Variable de entorno `$OKF_VAULT`
3. `~/OKF-Vault` (default)

### 4. Probá el health check

```bash
python3 -m cli health --vault ~/mi-vault
```

Si ves `✅ Salud: 9/9`, tu vault está listo.

### 5. Registrá el MCP en tu agente

**Claude Code** (`~/.claude/.mcp.json`):

```json
{
  "mcpServers": {
    "okf": {
      "command": "okf-mcp",
      "args": []
    }
  }
}
```

**Hermes Agent** (`~/.hermes/config.yaml`):

```yaml
mcp_servers:
  okf:
    command: okf-mcp
    args: []
```

**Cursor** (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "okf": {
      "command": "okf-mcp",
      "args": []
    }
  }
}
```

> ⚠️ Si usás `python3 server.py` en vez de `okf-mcp`, la ruta en `args` DEBE ser absoluta. El cliente MCP no resuelve rutas relativas en `args` aunque tenga el campo `cwd`.

## Tools disponibles

| Tool | Descripción |
|---|---|
| `okf_traverse` | Travesía semántica del grafo — **uso primario para consultar** |
| `okf_read` | Leer body completo de un concepto |
| `okf_search` | Búsqueda FTS5 — **fallback**, preferir traverse |
| `okf_graph` | Análisis del grafo: huérfanos, hubs, backlinks, clusters |
| `okf_new` | Crear concepto nuevo con frontmatter OKF |
| `okf_health` | Chequeo de salud del vault (9 verificaciones) |
| `okf_index` | Regenerar índices y log |
| `okf_touch` | Estadísticas de lecturas |
| `okf_review` | Conceptos con review_on vencido (loop cibernético) |
| `okf_stale` | Detector de obsolescencia semántica |
| `okf_session_metrics` | Métricas agregadas de sesiones |
| `okf_analytics` | Consultas analíticas sobre eventos de trace |
| `okf_graph_command` | Comandos al plugin Cognitive Trace en Obsidian |
| `okf_file_info` | Metadatos de fecha de un concepto |

## El grafo semántico

La herramienta principal es `okf_traverse`. A diferencia de una búsqueda por keyword, la travesía sigue los wikilinks del grafo:

```
okf_traverse("mi-concepto", depth=2)
→ frontmatter del concepto
→ conceptos que enlaza (wikilinks salientes)
→ conceptos que lo enlazan (backlinks)
→ conceptos que corrige (cyber.corrects)
```

Esto permite que el agente **razone sobre la estructura del conocimiento**, no solo matchee texto.

## Tipos de conceptos

Los tipos vienen predefinidos en el archivo de configuración:

| Tipo | Propósito | Lleva cyber |
|---|---|---|
| `Decision` | Decisión arquitectónica o de política | ✅ |
| `Plan` | Plan de ejecución o roadmap | ✅ |
| `Project` | Proyecto con visión, estado y componentes | ✅ |
| `Insight` | Observación, patrón detectado, implicación | ✅ |
| `MarcoTeorico` | Marco teórico o framework conceptual | ❌ |
| `LeccionAprendida` | Lección de una experiencia | ❌ |
| `Tool` | Herramienta o script | ❌ |
| `Spec` | Especificación técnica | ❌ |
| `Sistema` | Configuración de runtime del ecosistema | ✅ |
| `Agente` | Definición de un agente IA | ✅ |
| `Skill` | Catálogo de una skill de Hermes | ❌ |
| `Workflow` | Procedimiento o flujo de trabajo | ❌ |
| `Criterio` | Regla de decisión o criterio | ❌ |
| `Sesion` | Resumen de sesión | ❌ |
| `Research` | Investigación o paper | ❌ |

El bloque `cyber` (sensor → target_metric → review_on) es opcional y solo aplica para los tipos marcados con ✅.

## Configuración avanzada

### Loop cibernético

Si usás el bloque `cyber` en tus conceptos, el MCP puede cerrar el loop automáticamente:

1. `okf_new --cyber` asigna `review_on: +14d`
2. `okf_review` lista conceptos con review vencido
3. Un agente autónomo evalúa el outcome (success/failure) y actualiza

Activá este flujo definiendo `cyber.review_days` en tu `.okf.config.yaml`.

### Detector de obsolescencia

`okf_stale` evalúa 7 señales de obsolescencia semántica:
1. Timestamp viejo (>90 días sin cambios significativos)
2. Pocas lecturas (<2 en 90 días)
3. Propuesta fantasma (>30 días en status "propuesta")
4. Huérfano (sin wikilinks entrantes ni salientes)
5. Sin commits (>180 días sin commits que toquen el archivo)
6. Decisión sin status
7. Description desactualizada (checkboxes completos pero description habla de problemas)

Ajustá los umbrales en `stale.*` de tu `.okf.config.yaml`.

## Desarrollo

```bash
# Ejecutar tests
cd tests && python3 test_server.py

# Probar el servidor manualmente (JSON-RPC stdio)
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | python3 server.py
```

## Licencia

MIT
