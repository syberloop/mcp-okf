# OKF MCP Server

Servidor MCP (Model Context Protocol) para el vault OKF. Expone 14 tools que wrappean `python3 -m cli` para que agentes como Claude Code consulten, creen y analicen conceptos del vault sin acceso directo al filesystem.

## Requisitos

- Python 3.12+
- `mcp[cli]` (FastMCP)
- Un vault OKF (default: `~/OKF-Vault`)

```bash
pip install mcp
```

## Configuración en Claude Code

Agregar a `~/.claude/.mcp.json` o a `<proyecto>/.mcp.json`:

```json
{
  "mcpServers": {
    "okf": {
      "command": "python3",
      "args": ["/home/jota/.hermes/mcp-servers/okf/server.py"],
      "cwd": "/home/jota/.hermes/mcp-servers/okf"
    }
  }
}
```

### ⚠️ La ruta en `args` DEBE ser absoluta

Claude Code **no resuelve rutas relativas en `args`** aunque tenga el campo `cwd`. Si usás `"args": ["server.py"]`, el proceso nunca se spawneará y el servidor no cargará (sin error visible, simplemente no aparece).

Siempre usá la ruta absoluta al script:

```json
// ✅ CORRECTO
"args": ["/ruta/absoluta/al/server.py"]

// ❌ INCORRECTO — no carga
"args": ["server.py"]
```

## Tools disponibles

| Tool | Descripción |
|---|---|
| `okf_traverse` | Travesía semántica del grafo (uso primario para consultar) |
| `okf_search` | Búsqueda FTS5 (fallback, preferir traverse) |
| `okf_read` | Leer body completo de un concepto |
| `okf_graph` | Análisis del grafo de wikilinks y tags |
| `okf_health` | Chequeo de salud del vault (8+ verificaciones) |
| `okf_index` | Regenerar índices y log |
| `okf_touch` | Estadísticas de lecturas |
| `okf_new` | Crear concepto nuevo con frontmatter |
| `okf_review` | Conceptos con review_on vencido |
| `okf_stale` | Detector de obsolescencia semántica |
| `okf_session_metrics` | Métricas agregadas de sesiones |
| `okf_analytics` | Consultas analíticas sobre eventos de trace |
| `okf_graph_command` | Comandos al plugin Cognitive Trace en Obsidian |
| `okf_file_info` | Metadatos de fecha de un concepto |

## Configuración del vault

Copiá `.okf.config.example.yaml` a `<vault>/.okf.config.yaml` y editalo según tu taxonomía. Todas las secciones son opcionales — si una clave no está presente, se usa el default.

## Desarrollo

```bash
# Ejecutar tests
cd tests && python3 test_server.py

# Probar el servidor manualmente (JSON-RPC stdio)
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | python3 server.py
```
