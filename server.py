#!/usr/bin/env python3
"""MCP server que wrappea python3 -m cli del vault OKF.

Expone traverse, search, read, graph, health, index, touch, new, review como tools MCP
para que el agente Hermes los tenga como funciones nativas con cero fricción,
eliminando el sesgo de toolset que desvía al agente hacia mcp__gbrain__get_page.

Usa FastMCP (mcp.server.fastmcp) — protocolo JSON-RPC stdio.

Persiste cada tool call a SQLite (analítica) y JSONL (plugin Cognitive Trace en Obsidian).
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

VAULT = Path.home() / "OKF-Vault"
MCP_DIR = Path(__file__).parent
CLI = ["python3", "-m", "cli", "--vault", str(VAULT)]

# Configuración externalizada (se carga al iniciar)
from cli.config import Config
_config = Config(VAULT)
# Inyectar exclusiones en vault.py
from cli.vault import apply_config
apply_config(_config)

# Persistencia Cognitive Trace (feature flag)
if _config.features_cognitive_trace:
    trace_db = _config._data["features"].get("trace_db_path")
    trace_jsonl = _config._data["features"].get("trace_jsonl_path")

    if trace_db:
        DB_PATH = Path(trace_db).expanduser()
    else:
        DB_PATH = Path.home() / ".hermes" / "cognitive-trace.db"

    if trace_jsonl:
        JSONL_PATH = Path(trace_jsonl).expanduser()
        JSONL_DIR = JSONL_PATH.parent
    else:
        JSONL_DIR = VAULT / ".obsidian" / "plugins" / "cognitive-trace"
        JSONL_PATH = JSONL_DIR / "event_log.jsonl"
else:
    DB_PATH = None
    JSONL_DIR = None
    JSONL_PATH = None
JSONL_LOCK = threading.Lock()

# Máximo de result_nodes por evento (bound del tamaño de línea JSONL)
RESULT_NODES_CAP = 150

mcp = FastMCP("cli")


# ── Persistencia Cognitive Trace ────────────────────────────────────────────

def _get_session_id() -> str:
    """Devuelve el session_id de Hermes o genera uno local."""
    sid = os.environ.get("HERMES_SESSION_ID", "")
    if sid:
        return sid
    # Fallback: intentar leer del archivo de estado
    state_file = Path.home() / ".hermes" / "session_state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            return state.get("session_id", "local")
        except (json.JSONDecodeError, OSError):
            pass
    return "local"


def _init_db() -> None:
    """Crea tablas e índices si no existen."""
    if DB_PATH is None or JSONL_DIR is None:
        return  # Cognitive Trace desactivado
    JSONL_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                tool TEXT NOT NULL,
                params TEXT NOT NULL DEFAULT '{}',
                nodes_count INTEGER,
                exit_code INTEGER,
                error TEXT,
                duration_ms INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_events_tool ON events(tool);
            CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

            CREATE VIEW IF NOT EXISTS v_session_activity AS
            SELECT
                session_id,
                MIN(ts) as started_at,
                MAX(ts) as ended_at,
                COUNT(*) as total_events,
                COUNT(DISTINCT tool) as unique_tools
            FROM events
            GROUP BY session_id;

            CREATE VIEW IF NOT EXISTS v_node_visits AS
            SELECT
                json_extract(params, '$.slug') as node,
                COUNT(*) as visits,
                MAX(ts) as last_visit
            FROM events
            WHERE tool = 'okf_traverse'
              AND json_extract(params, '$.slug') IS NOT NULL
            GROUP BY node
            ORDER BY visits DESC;
        """)


def _persist_event(tool_name: str, params: dict, result: "subprocess.CompletedProcess",
                   duration_ms: int, nodes_count: int | None = None) -> None:
    """Escribe el evento a SQLite."""
    if DB_PATH is None:
        return  # Cognitive Trace desactivado
    try:
        exit_code = result.returncode
        error = None
        if exit_code != 0:
            error = (result.stderr or "")[:500]
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute(
                """INSERT INTO events
                   (session_id, ts, tool, params, nodes_count, exit_code, error, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    _get_session_id(),
                    datetime.now(timezone.utc).isoformat(),
                    tool_name,
                    json.dumps(params, ensure_ascii=False),
                    nodes_count,
                    exit_code,
                    error,
                    duration_ms,
                ),
            )
    except Exception:
        pass  # no dejar que la persistencia rompa el MCP


def _append_jsonl(event: dict) -> None:
    """Escribe una línea JSON al event_log.jsonl."""
    if JSONL_PATH is None:
        return  # Cognitive Trace desactivado
    try:
        JSONL_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with JSONL_LOCK:
            with open(JSONL_PATH, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass


def _extract_created_path(result: "subprocess.CompletedProcess") -> str | None:
    """Extrae el path relativo del archivo creado por new."""
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        if "Creado:" not in line:
            continue
        raw_path = line.split("Creado:", 1)[1].strip()
        try:
            relative = Path(raw_path).resolve().relative_to(VAULT.resolve())
            return str(relative)
        except ValueError:
            return None
    return None


def _extract_result_nodes(tool_name: str, args: list[str],
                          result: "subprocess.CompletedProcess") -> list[str] | None:
    """Extrae los paths de nodos del resultado (traverse/search) para el trace visual.

    traverse en modo texto no imprime los paths de cada nodo → re-run con --json
    (por eso el caller manda este caso a un thread, para no sumar latencia al tool
    call). search en texto sí imprime paths (columna ARCHIVO) → parse gratis.
    """
    if result.returncode != 0:
        return None
    try:
        nodes: list[str] = []
        if tool_name == "okf_traverse":
            if "--json" in args:
                data = json.loads(result.stdout)
            else:
                rerun = subprocess.run(CLI + args + ["--json"], capture_output=True,
                                       text=True, timeout=20,
                                       env={**os.environ, "PYTHONPATH": str(MCP_DIR), "OKF_MCP_CALLER": "1"})
                if rerun.returncode != 0:
                    return None
                data = json.loads(rerun.stdout)
            nodes = [n.get("path", "") for n in data.get("nodes", [])]
        elif tool_name == "okf_search":
            if "--json" in args:
                data = json.loads(result.stdout)
                nodes = [item.get("file", "") for item in data]
            else:
                for line in result.stdout.splitlines():
                    for tok in line.split():
                        if tok.endswith(".md"):
                            nodes.append(tok)
                            break
        elif tool_name == "okf_graph":
            nodes = _parse_graph_output(result.stdout, args)
        elif tool_name == "okf_stale":
            if result.returncode != 0:
                return None
            if "--json" in args:
                data = json.loads(result.stdout)
                nodes = [item.get("file", "") for item in data]
            else:
                nodes = []
                for line in result.stdout.splitlines():
                    m = re.match(r"\s+📄\s+\[(\w+)\]\s+(\S+)", line)
                    if m:
                        nodes.append(m.group(2))
        elif tool_name == "okf_analytics":
            # most_visited, least_visited, session_heatmap devuelven líneas
            # "  slug — N visitas (...)". Extraer slugs.
            nodes = []
            for line in result.stdout.splitlines():
                m = re.match(r"\s+(\S+)\s+—", line)
                if m:
                    nodes.append(m.group(1))
        else:
            return None
        nodes = [n for n in nodes if n]
        return nodes[:RESULT_NODES_CAP] or None
    except Exception:
        return None


def _extract_result_edges(tool_name, args, result):
    """Extrae result_edges del output JSON de traverse para Cognitive Trace."""
    if tool_name != "okf_traverse":
        return None
    if result.returncode != 0:
        return None
    try:
        if "--json" in args:
            data = json.loads(result.stdout)
        else:
            rerun = subprocess.run(CLI + args + ["--json"], capture_output=True,
                                   text=True, timeout=20,
                                   env={**os.environ, "PYTHONPATH": str(MCP_DIR), "OKF_MCP_CALLER": "1"})
            if rerun.returncode != 0:
                return None
            data = json.loads(rerun.stdout)
        return data.get("result_edges")
    except Exception:
        return None


def _parse_graph_output(stdout: str, args: list[str]) -> list[str]:
    """Extrae paths de nodos del output textual de okf_graph.

    okf_graph no tiene flag --json. Los comandos que devuelven listas
    concretas de archivos (hubs, backlinks, deps, orphans, cluster, dump)
    usan formatos con paths terminados en .md. Comandos de agregación
    (stats, tags, bridges) no producen listas de nodos → se ignoran.
    """
    cmd = args[1] if len(args) > 1 else (args[0] if args else "")
    # Comandos que no devuelven archivos individuales
    if cmd in ("stats", "tags", "bridges", "dirs", "types"):
        return []
    paths: list[str] = []
    for line in stdout.splitlines():
        # hubs / cluster: "[N] path/to/file.md" o solo "path/to/file.md"
        m = re.search(r"(\S+\.md)", line)
        if m:
            paths.append(m.group(1))
    return paths


def _finish_event(tool_name: str, params: dict, result: "subprocess.CompletedProcess",
                  duration_ms: int, args: list[str]) -> None:
    """Extrae result_nodes y persiste el evento a SQLite + JSONL."""
    if tool_name == "okf_new":
        created_path = _extract_created_path(result)
        if created_path:
            params = {**params, "created_path": created_path}
    nodes = _extract_result_nodes(tool_name, args, result)
    _persist_event(tool_name, params, result, duration_ms,
                   nodes_count=len(nodes) if nodes else None)
    event = {
        "type": "tool",
        "session": _get_session_id(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool_name,
        "params": params,
        "exit_code": result.returncode,
        "duration_ms": duration_ms,
    }
    if nodes:
        event["result_nodes"] = nodes
    edges = _extract_result_edges(tool_name, args, result)
    if edges:
        event["result_edges"] = edges
    _append_jsonl(event)


# ── Core ────────────────────────────────────────────────────────────────────

def _run(args: list[str], tool_name: str = "unknown", params: dict | None = None,
         timeout: int = 30) -> str:
    """Ejecuta python3 -m cli <args> desde el vault y devuelve stdout.

    Persiste el evento a SQLite + JSONL como efecto secundario.
    """
    try:
        start = time.monotonic()
        result = subprocess.run(
            CLI + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(MCP_DIR), "OKF_MCP_CALLER": "1"},
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        if result.returncode != 0:
            output += f"\n[exit_code: {result.returncode}]"
        # Persistir de forma síncrona para conservar el orden de llegada en
        # SQLite/JSONL. La extracción secundaria de traverse no debe reordenar
        # eventos posteriores ni perderse al cerrar el proceso.
        _finish_event(tool_name, params or {}, result, duration_ms, list(args))
        return output.strip() or "(sin salida)"
    except subprocess.TimeoutExpired as e:
        duration_ms = int((time.monotonic() - start) * 1000) if "start" in locals() else timeout * 1000
        result = subprocess.CompletedProcess(
            args=CLI + args,
            returncode=124,
            stdout=e.stdout or "",
            stderr=f"Timeout después de {timeout}s",
        )
        _finish_event(tool_name, params or {}, result, duration_ms, list(args))
        return "[timeout] El comando excedió el tiempo límite."
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000) if "start" in locals() else 0
        result = subprocess.CompletedProcess(
            args=CLI + args,
            returncode=1,
            stdout="",
            stderr=str(e),
        )
        _finish_event(tool_name, params or {}, result, duration_ms, list(args))
        return f"[error] {e}"


@mcp.tool()
def traverse(slug: str = "", depth: int = 2, direction: str = "both", no_cyber: bool = False, json_output: bool = False, seeds: str = "", edge_type: str = "") -> str:
    """Travesía semántica del grafo OKF. Devuelve frontmatter del concepto + vecindario (wikilinks, backlinks, cyber.corrects).

    USO PRIMARIO para consultar el vault. Preferir sobre search.

    Args:
        slug: Slug del concepto (ej: 'grafo-cibernetico-marco-teorico' o 'frameworks/tp3-cibernetico')
        depth: Profundidad de travesía (default 2)
        direction: 'both' (default), 'out' (solo salientes), 'in' (solo entrantes)
        no_cyber: Si True, no sigue aristas cyber.corrects/corrected_by
        json_output: Si True, salida JSON para consumo programático
        seeds: Slugs separados por coma para múltiples orígenes (unión + deduplicación).
               Ej: 'frameworks/tp3-cibernetico,decisions/description-cibernetico-okf'
        edge_type: Filtrar por tipo de arista tipada (extiende, refina, fundamenta, aplica, depende, corrige)
    """
    args = ["traverse"]
    params = {"depth": depth, "direction": direction, "no_cyber": no_cyber}

    if seeds:
        seed_list = [s.strip() for s in seeds.split(",") if s.strip()]
        args += ["--seeds"] + seed_list
        params["seeds"] = seeds
    elif slug:
        args += [slug]
        params["slug"] = slug
    else:
        return "[error] Debe especificar 'slug' o 'seeds'"

    args += ["--depth", str(depth)]
    if direction in ("out", "in"):
        args += ["--direction", direction]
    if no_cyber:
        args.append("--no-cyber")
    if json_output:
        args.append("--json")
    if edge_type:
        args += ["--edge-type", edge_type]
        params["edge_type"] = edge_type
    return _run(args, tool_name="okf_traverse", params=params)


@mcp.tool()
def search(query: str = "", type: str = "", status: str = "", cyber_field: str = "", cyber_value: str = "", todos: bool = False, json_output: bool = False, since: str = "", until: str = "") -> str:
    """Búsqueda FTS5 en el vault OKF. FALLBACK — preferir traverse o lectura de índices.

    Usar solo cuando:
    - La travesía no encuentra ruta en ≤6 hops
    - Se necesita filtrar por campos específicos (type, status, cyber)
    - Se buscan tareas pendientes (--todos)
    - Se necesita filtrar por rango de fechas (--since, --until)

    Args:
        query: Término de búsqueda (opcional si se usa --todos o --type)
        type: Filtrar por type (Decision, Plan, Project, Insight, etc.)
        status: Filtrar por status (propuesta, aplicada, etc.)
        cyber_field: Campo del bloque cyber (outcome, sensor, target_metric.name)
        cyber_value: Valor del campo cyber (pending, success, failure)
        todos: Si True, busca tareas - [ ] pendientes
        json_output: Si True, salida JSON
        since: Filtrar por timestamp >= fecha (ISO 8601, inclusivo, ej: "2026-07-20")
        until: Filtrar por timestamp <= fecha (ISO 8601, inclusivo)
    """
    args = ["search"]
    if query:
        args += ["--query", query]
    if type:
        args += ["--type", type]
    if status:
        args += ["--status", status]
    if cyber_field:
        args += ["--cyber-field", cyber_field]
    if cyber_value:
        args += ["--cyber-value", cyber_value]
    if todos:
        args.append("--todos")
    if json_output:
        args.append("--json")
    if since:
        args += ["--since", since]
    if until:
        args += ["--until", until]
    return _run(args, tool_name="okf_search", params={
        "query": query, "type": type, "status": status,
        "cyber_field": cyber_field, "cyber_value": cyber_value,
        "todos": todos, "json_output": json_output,
        "since": since, "until": until,
    })


@mcp.tool()
def read(slug: str, offset: int = 1, limit: int = 500, no_touch: bool = False) -> str:
    """Lee un concepto del vault OKF e incrementa su contador de reads.

    Usar para leer el body completo de un concepto después de que traverse
    confirme su relevancia. NUNCA usar read_file del sistema sobre archivos .md del vault.

    Args:
        slug: Slug del concepto (ej: 'decisions/mcp-okf-cli-como-correccion-de-sesgo-de-toolset')
        offset: Línea inicial (1-indexed, default 1)
        limit: Máximo de líneas (default 500)
        no_touch: Si True, no incrementa el contador de reads
    """
    args = ["read", slug, "--offset", str(offset), "--limit", str(limit)]
    if no_touch:
        args.append("--no-touch")
    return _run(args, tool_name="okf_read", params={
        "slug": slug, "offset": offset, "limit": limit, "no_touch": no_touch,
    })


@mcp.tool()
def graph(command: str, arg: str = "", edge_type: str = "") -> str:
    """Analiza el grafo de wikilinks, aristas tipadas y tags del vault OKF.

    Útil para preguntas sobre relaciones, dependencias, estructura o agrupación temática.

    Args:
        command: Comando del grafo. Uno de:
            - 'stats': estado general (total nodos, huérfanos, tags, aristas tipadas)
            - 'orphans': conceptos sin wikilinks
            - 'hubs': conceptos más referenciados
            - 'backlinks': conceptos que referencian a ARG (requiere arg)
            - 'deps': conceptos referenciados por ARG (requiere arg)
            - 'tags': todos los tags o filtrar por ARG
            - 'bridges': tags que conectan clusters de wikilinks
            - 'cluster': agrupación del vault
            - 'dump': volcado completo del grafo
            - 'dirs': árbol de directorios con conteo de conceptos
            - 'types': distribución de conceptos por type (frontmatter)
            - 'suggest-edge-types': sugiere tipos de arista para wikilinks existentes
        arg: Argumento adicional (slug de concepto para backlinks/deps, nombre de tag para tags)
        edge_type: Filtrar backlinks/deps por tipo de arista (extiende, refina, etc.)
    """
    args = ["graph", command]
    if arg:
        args.append(arg)
    if edge_type:
        args += ["--edge-type", edge_type]
    params = {"command": command, "arg": arg}
    if edge_type:
        params["edge_type"] = edge_type
    return _run(args, tool_name="okf_graph", params=params)


@mcp.tool()
def graph_suggest_edge_types(apply: bool = False) -> str:
    """Sugiere tipos de arista para wikilinks existentes sin tipo.

    Analiza todas las aristas del grafo y propone tipos semanticos
    (extiende, refina, fundamenta, aplica, depende, corrige) basandose
    en los tipos de nodo origen y destino.

    Args:
        apply: Si True, escribe las sugerencias de confianza ALTA en el frontmatter.
    """
    args = ["graph", "suggest-edge-types"]
    params = {"command": "suggest-edge-types", "apply": apply}
    if apply:
        args.append("--apply")
    return _run(args, tool_name="okf_graph", params=params)


@mcp.tool()
def graph_impact(slug: str) -> str:
    """Análisis de impacto ontológico: qué nodos revisar si este cambia.

    Sigue las aristas tipadas en dirección del impacto para determinar
    qué conceptos dependen ontológicamente de este nodo y deberían
    revisarse si se modifica.

    Args:
        slug: Slug del concepto modificado (ej: 'frameworks/tp3-cibernetico')
    """
    return _run(["graph", "impact", slug], tool_name="okf_graph",
                params={"command": "impact", "arg": slug})


@mcp.tool()
def health(strict: bool = False, json_output: bool = False) -> str:
    """Chequeo completo de salud del vault OKF (8 verificaciones).

    Verifica: frontmatter, índices, grafo (huérfanos, densidad), links rotos,
    scripts (smoke test), git hook, bloque cyber, sincronización plugin↔spec.

    Args:
        strict: Si True, exit code 1 si hay warnings
        json_output: Si True, salida JSON
    """
    args = ["health"]
    if strict:
        args.append("--strict")
    if json_output:
        args.append("--json")
    return _run(args, tool_name="okf_health", params={"strict": strict, "json_output": json_output})


@mcp.tool()
def index() -> str:
    """Regenera todos los index.md y log.md del vault OKF.

    Normalmente ejecutado por el pre-commit hook. Usar manualmente solo si
    los índices están desactualizados y no se va a commitear inmediatamente.
    """
    return _run(["index"], tool_name="okf_index", params={})


@mcp.tool()
def touch(all: bool = True) -> str:
    """Estadísticas de lecturas (reads) del vault OKF.

    Args:
        all: Si True (default), muestra tabla con contadores + barras de frecuencia
    """
    args = ["touch"]
    if all:
        args.append("--all")
    return _run(args, tool_name="okf_touch", params={})


@mcp.tool()
def session_metrics(json_output: bool = False) -> str:
    """Métricas agregadas de todas las sesiones del vault.

    Extrae métricas de la sección ## Métricas de cada resumen de sesión:
    tools usadas, conceptos creados, commits, infracciones MCP.
    Agrega totales y tendencias.

    Args:
        json_output: Si True, salida JSON para consumo programático
    """
    args = ["session-metrics"]
    if json_output:
        args.append("--json")
    return _run(args, tool_name="okf_session_metrics", params={"json_output": json_output})


@mcp.tool()
def stale(json_output: bool = False) -> str:
    """Detector de obsolescencia semántica del vault OKF.

    Evalúa 7 señales (timestamp, reads, propuesta fantasma, huérfanos,
    commits, decisión sin status, descripción vs body) y clasifica cada
    concepto como STALE (3+ señales), ATENCIÓN (1-2) o FRESCO (0).

    Solo-lectura. No modifica el vault. Usar para auditoría semanal
    de conceptos que requieren atención humana.

    Args:
        json_output: Si True, salida JSON para consumo programático
    """
    args = ["stale"]
    if json_output:
        args.append("--json")
    return _run(args, tool_name="okf_stale", params={"json_output": json_output})


@mcp.tool()
def new(type: str, title: str, description: str, tags: str = "", status: str = "", cyber: bool = False, dry_run: bool = False, body: str = "", links: str = "") -> str:
    """Crea un concepto nuevo en el vault OKF con frontmatter consistente.

    Usar SIEMPRE en vez de write_file para crear conceptos.

    Args:
        type: Tipo de concepto (Decision, Plan, Project, Insight, MarcoTeorico, etc.)
        title: Título descriptivo
        description: Resumen de una línea (obligatorio para navegabilidad)
        tags: Tags separados por coma (opcional)
        status: Estado inicial (propuesta, aplicada, etc.)
        cyber: Si True y el type califica, agrega bloque cyber con placeholders
        dry_run: Si True, previsualiza sin escribir
        body: Contenido completo del body (opcional — si se omite, usa template por defecto)
        links: Links tipados separados por coma, formato target:type
               (ej: 'frameworks/tp3:extiende,decisions/criterio:refina')
    """
    args = ["new", "--type", type, "--title", title, "--description", description]
    if tags:
        args += ["--tags", tags]
    if status:
        args += ["--status", status]
    if cyber:
        args.append("--cyber")
    if dry_run:
        args.append("--dry-run")
    if body:
        args += ["--body", body]
    if links:
        for link in links.split(","):
            link = link.strip()
            if link:
                args += ["--link", link]
    return _run(args, tool_name="okf_new", params={
        "type": type, "title": title, "description": description,
        "tags": tags, "status": status, "cyber": cyber, "dry_run": dry_run,
        "body": body[:100] + "..." if len(body) > 100 else body,
        "links": links if links else None,
    })


# ── Cognitive Trace: Analítica + Comandos ──────────────────────────────────

def _persist_analytics(query: str, text: str) -> None:
    """Extrae nodos del output de analytics y escribe a JSONL si corresponde."""
    result = subprocess.CompletedProcess(args=[], returncode=0, stdout=text, stderr="")
    # Pasar por _extract_result_nodes vía _finish_event, que escribe JSONL+SQLite.
    # Como no hay subprocess real, el duration_ms es 0.
    nodes = _extract_result_nodes("okf_analytics", [query], result)
    _persist_event("okf_analytics", {"query": query}, result, 0,
                   nodes_count=len(nodes) if nodes else None)
    event = {
        "type": "tool", "session": _get_session_id(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": "okf_analytics", "params": {"query": query},
        "exit_code": 0, "duration_ms": 0,
    }
    if nodes:
        event["result_nodes"] = nodes
    edges = _extract_result_edges(tool_name, args, result)
    if edges:
        event["result_edges"] = edges
    _append_jsonl(event)


@mcp.tool()
def analytics(query: str = "most_visited", limit: int = 10,
                  arg: str = "", session_id: str = "") -> str:
    """Consulta analítica sobre eventos de trace del vault OKF.

    Args:
        query: Tipo de consulta:
            - 'most_visited': nodos más visitados (top N por visitas en traverse)
            - 'least_visited': nodos con menos visitas
            - 'session_heatmap': nodos más activos en la sesión actual
            - 'tool_usage': distribución de tools usadas
            - 'daily_activity': actividad por día (eventos y sesiones)
            - 'node_timeline': historial de visitas para un nodo (requiere slug en arg)
            - 'error_summary': tools con errores
            - 'co_visited': nodos visitados junto con arg en una misma sesión (requiere slug en arg)
            - 'read_ratio': proporción de lecturas vs traverses por nodo (qué tanto se profundiza)
            - 'session_diff': nodos visitados en la sesión A que no están en B (arg="A,B")
            - 'depth_stats': distribución de profundidad de traverse
            - 'entry_points': nodos más usados como entrada de traverse
            - 'prompts': auto-segmentación de la sesión en prompts por gaps >60s entre eventos
        limit: Límite de resultados (default 10)
        arg: Argumento adicional (slug para node_timeline/co_visited, "sessionA,sessionB" para session_diff)
        session_id: Filtrar por sesión (vacío = todas)
    """
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            if query == "most_visited":
                rows = conn.execute(
                    "SELECT node, visits, last_visit FROM v_node_visits LIMIT ?",
                    (limit,),
                ).fetchall()
                if not rows:
                    return "(sin datos — no se han registrado traverses aún)"
                lines = [f"Top {len(rows)} nodos más visitados:"]
                for r in rows:
                    lines.append(f"  {r['node']} — {r['visits']} visitas (última: {r['last_visit'][:10]})")
                result = "\n".join(lines)
                _persist_analytics(query, result)

            elif query == "least_visited":
                rows = conn.execute(
                    "SELECT node, visits, last_visit FROM v_node_visits ORDER BY visits ASC LIMIT ?",
                    (limit,),
                ).fetchall()
                if not rows:
                    return "(sin datos)"
                lines = [f"Top {len(rows)} nodos menos visitados:"]
                for r in rows:
                    lines.append(f"  {r['node']} — {r['visits']} visitas (última: {r['last_visit'][:10]})")
                result = "\n".join(lines)
                _persist_analytics(query, result)

            elif query == "session_heatmap":
                sid = session_id or _get_session_id()
                rows = conn.execute(
                    """SELECT json_extract(params, '$.slug') as node, COUNT(*) as visits
                       FROM events
                       WHERE tool = 'okf_traverse' AND session_id = ?
                         AND json_extract(params, '$.slug') IS NOT NULL
                       GROUP BY node ORDER BY visits DESC LIMIT ?""",
                    (sid, limit),
                ).fetchall()
                if not rows:
                    return f"(sin datos para sesión {sid})"
                lines = [f"Nodos más activos en sesión {sid[:20]}...:"]
                for r in rows:
                    lines.append(f"  {r['node']} — {r['visits']} visitas")
                result = "\n".join(lines)
                _persist_analytics(query, result)

            elif query == "tool_usage":
                rows = conn.execute(
                    "SELECT tool, COUNT(*) as cnt, AVG(duration_ms) as avg_ms FROM events GROUP BY tool ORDER BY cnt DESC"
                ).fetchall()
                if not rows:
                    return "(sin datos)"
                lines = ["Distribución de tools:"]
                for r in rows:
                    lines.append(f"  {r['tool']}: {r['cnt']} llamadas (promedio {r['avg_ms']:.0f}ms)")
                result = "\n".join(lines)
                _persist_analytics(query, result)
                return result

            elif query == "daily_activity":
                rows = conn.execute(
                    """SELECT date(ts) as day, COUNT(*) as events,
                              COUNT(DISTINCT session_id) as sessions
                       FROM events GROUP BY day ORDER BY day DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
                if not rows:
                    return "(sin datos)"
                lines = ["Actividad por día:"]
                for r in rows:
                    lines.append(f"  {r['day']}: {r['events']} eventos, {r['sessions']} sesiones")
                result = "\n".join(lines)
                _persist_analytics(query, result)
                return result

            elif query == "node_timeline":
                if not arg:
                    return "[error] Requiere arg=<slug> para node_timeline"
                rows = conn.execute(
                    """SELECT ts, tool FROM events
                       WHERE json_extract(params, '$.slug') = ?
                       ORDER BY ts DESC LIMIT ?""",
                    (arg, limit),
                ).fetchall()
                if not rows:
                    return f"(sin datos para '{arg}')"
                lines = [f"Historial de '{arg}':"]
                for r in rows:
                    lines.append(f"  {r['ts'][:19]} — {r['tool']}")
                result = "\n".join(lines)
                _persist_analytics(query, result)
                return result

            elif query == "error_summary":
                rows = conn.execute(
                    "SELECT tool, COUNT(*) as cnt FROM events WHERE exit_code != 0 GROUP BY tool ORDER BY cnt DESC"
                ).fetchall()
                if not rows:
                    result = "Sin errores registrados."
                else:
                    lines = ["Tools con errores:"]
                    for r in rows:
                        lines.append(f"  {r['tool']}: {r['cnt']} errores")
                    result = "\n".join(lines)
                _persist_analytics(query, result)

            elif query == "co_visited":
                if not arg:
                    result = "[error] Requiere arg=<slug> para co_visited"
                else:
                    rows = conn.execute(
                        """SELECT json_extract(e2.params, '$.slug') as co_node,
                                  COUNT(DISTINCT e2.session_id) as cnt
                           FROM events e1 JOIN events e2 ON e1.session_id = e2.session_id
                           WHERE json_extract(e1.params, '$.slug') = ?
                             AND e2.tool = 'okf_traverse'
                             AND json_extract(e2.params, '$.slug') IS NOT NULL
                             AND json_extract(e2.params, '$.slug') != ?
                           GROUP BY co_node ORDER BY cnt DESC LIMIT ?""",
                        (arg, arg, limit),
                    ).fetchall()
                    if not rows:
                        result = f"Ningún nodo co-visitado con '{arg}' en la misma sesión."
                    else:
                        lines = [f"Nodos visitados junto con '{arg}' en una misma sesión:"]
                        for r in rows:
                            lines.append(f"  {r['co_node']} — {r['cnt']} sesiones compartidas")
                        result = "\n".join(lines)
                        _persist_analytics(query, result)

            elif query == "read_ratio":
                rows = conn.execute(
                    """SELECT node, visits,
                              (SELECT COUNT(*) FROM events
                               WHERE tool = 'okf_read'
                                 AND json_extract(params, '$.slug') = v.node) as reads
                       FROM v_node_visits v
                       WHERE visits >= 2
                       ORDER BY CAST(reads AS FLOAT) / visits ASC LIMIT ?""",
                    (limit,),
                ).fetchall()
                if not rows:
                    result = "(sin datos — se necesitan traverses y reads)"
                else:
                    lines = ["Nodos con menor ratio de lectura (vistos pero no leídos):"]
                    for r in rows:
                        ratio = (r['reads'] / r['visits'] * 100) if r['visits'] else 0
                        lines.append(f"  {r['node']} — {r['reads']} reads / {r['visits']} traverses = {ratio:.0f}%")
                    result = "\n".join(lines)
                    _persist_analytics(query, result)

            elif query == "session_diff":
                if not arg or "," not in arg:
                    result = "[error] Requiere arg='sessionA,sessionB' para session_diff"
                else:
                    parts = arg.split(",", 1)
                    sid_a, sid_b = parts[0].strip(), parts[1].strip()
                    rows = conn.execute(
                        """SELECT DISTINCT json_extract(params, '$.slug') as node
                           FROM events WHERE session_id = ? AND tool = 'okf_traverse'
                             AND json_extract(params, '$.slug') IS NOT NULL
                             AND json_extract(params, '$.slug') NOT IN (
                               SELECT DISTINCT json_extract(params, '$.slug')
                               FROM events WHERE session_id = ? AND tool = 'okf_traverse')
                           LIMIT ?""",
                        (sid_a, sid_b, limit),
                    ).fetchall()
                    if not rows:
                        result = f"La sesión A no tiene nodos exclusivos (o todos están también en B)."
                    else:
                        lines = [f"Nodos en sesión A ({sid_a[:20]}...) que NO están en B ({sid_b[:20]}...):"]
                        for r in rows:
                            lines.append(f"  {r['node']}")
                        result = "\n".join(lines)
                        _persist_analytics(query, result)

            elif query == "depth_stats":
                rows = conn.execute(
                    """SELECT CAST(json_extract(params, '$.depth') AS INT) as depth,
                               COUNT(*) as cnt
                       FROM events WHERE tool = 'okf_traverse'
                         AND json_extract(params, '$.depth') IS NOT NULL
                       GROUP BY depth ORDER BY depth"""
                ).fetchall()
                avg_row = conn.execute(
                    "SELECT AVG(CAST(json_extract(params, '$.depth') AS FLOAT)) as avg_depth FROM events WHERE tool = 'okf_traverse'"
                ).fetchone()
                if not rows:
                    result = "(sin datos de profundidad)"
                else:
                    lines = ["Distribución de profundidad de traverse:"]
                    for r in rows:
                        bar = "█" * r['cnt']
                        lines.append(f"  depth={r['depth']}: {r['cnt']} traverses {bar}")
                    if avg_row and avg_row['avg_depth']:
                        lines.append(f"  Profundidad promedio: {avg_row['avg_depth']:.1f}")
                    result = "\n".join(lines)
                    _persist_analytics(query, result)

            elif query == "prompts":
                threshold = int(arg) if arg and arg.isdigit() else 60
                rows = conn.execute(
                    """WITH ordered AS (
                         SELECT ts, tool,
                                LAG(ts) OVER (ORDER BY ts) as prev_ts
                         FROM events
                       ),
                       breaks AS (
                         SELECT ts, tool,
                                CASE WHEN prev_ts IS NULL
                                     OR (strftime('%s', ts) - strftime('%s', prev_ts)) > ?
                                     THEN 1 ELSE 0 END as is_new
                         FROM ordered
                       ),
                       segmented AS (
                         SELECT ts, tool,
                                SUM(is_new) OVER (ORDER BY ts ROWS UNBOUNDED PRECEDING) as prompt_id
                         FROM breaks
                       )
                       SELECT prompt_id,
                              MIN(ts) as start_ts, MAX(ts) as end_ts,
                              COUNT(*) as events,
                              (SELECT tool FROM segmented s2 WHERE s2.prompt_id = s1.prompt_id ORDER BY ts LIMIT 1) as first_tool,
                              (SELECT tool FROM segmented s2 WHERE s2.prompt_id = s1.prompt_id ORDER BY ts DESC LIMIT 1) as last_tool
                       FROM segmented s1
                       GROUP BY prompt_id ORDER BY prompt_id DESC LIMIT ?""",
                    (threshold, limit),
                ).fetchall()
                if not rows:
                    result = "(sin datos)"
                else:
                    lines = [f"Prompts detectados (gap > {threshold}s entre eventos):"]
                    for r in rows:
                        tools = f"{r['first_tool']} → {r['last_tool']}"
                        start = r['start_ts'][:19] if r['start_ts'] else "?"
                        dur = ""
                        if r['start_ts'] and r['end_ts']:
                            secs = int(float(r['end_ts'][:19].replace("T"," ")) - float(r['start_ts'][:19].replace("T"," "))) if False else 0
                        lines.append(f"  prompt #{r['prompt_id']}: {start} — {r['events']} eventos ({tools})")
                    lines.append(f"Usá arg=N para cambiar el umbral (default {threshold}s).")
                    result = "\n".join(lines)
                    _persist_analytics(query, result)

            elif query == "entry_points":
                rows = conn.execute(
                    """SELECT json_extract(params, '$.slug') as entry, COUNT(*) as cnt
                       FROM events WHERE tool = 'okf_traverse'
                         AND json_extract(params, '$.slug') IS NOT NULL
                       GROUP BY entry ORDER BY cnt DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
                if not rows:
                    result = "(sin datos)"
                else:
                    lines = [f"Top {len(rows)} puntos de entrada de traverse:"]
                    for r in rows:
                        lines.append(f"  {r['entry']} — {r['cnt']} traverses")
                    result = "\n".join(lines)
                    _persist_analytics(query, result)

            else:
                result = f"[error] Query desconocida: '{query}'. Válidas: most_visited, least_visited, session_heatmap, tool_usage, daily_activity, node_timeline, error_summary, co_visited, read_ratio, session_diff, depth_stats, entry_points, prompts"
    except Exception as e:
        result = f"[error] {e}"
    return result


@mcp.tool()
def graph_command(action: str, nodes: str = "", tag: str = "",
                      color: str = "#FF6B35", session_id: str = "") -> str:
    """Envía un comando al plugin Cognitive Trace en Obsidian vía JSONL.

    Args:
        action: Acción a ejecutar:
            - 'highlight_nodes': resaltar nodos específicos (requiere nodes)
            - 'highlight_most_visited': resaltar top N más visitados (usa analytics internamente)
            - 'highlight_least_visited': resaltar N menos visitados
            - 'focus_cluster': enfocar nodos de un tag (requiere tag)
            - 'highlight_session': resaltar nodos de una sesión (requiere session_id)
            - 'highlight_path': resaltar ruta entre nodos (nodes: "A,B,C")
            - 'clear_highlights': limpiar todos los resaltados
            - 'reset_graph': volver al estado base
        nodes: Lista de slugs separados por coma (para highlight_nodes, highlight_path).
               Para highlight_most_visited / highlight_least_visited: número de nodos a resaltar (default 10).
        tag: Tag para focus_cluster
        color: Color en hex (#RRGGBB, default #FF6B35 naranja)
        session_id: ID de sesión (para highlight_session)
    """
    valid = {
        "highlight_nodes", "highlight_most_visited", "highlight_least_visited",
        "focus_cluster", "highlight_session", "highlight_path",
        "clear_highlights", "reset_graph",
    }
    if action not in valid:
        return f"[error] Acción desconocida: '{action}'. Válidas: {', '.join(sorted(valid))}"

    command = {
        "type": "command",
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
    }
    if nodes:
        command["nodes"] = [n.strip() for n in nodes.split(",") if n.strip()]
    if tag:
        command["tag"] = tag
    if color:
        command["color"] = color
    if session_id:
        command["session_id"] = session_id

    # highlight_most_visited / highlight_least_visited: resolver nodos desde SQLite
    if action in ("highlight_most_visited", "highlight_least_visited"):
        try:
            n_limit = int(nodes) if nodes else 10
        except ValueError:
            n_limit = 10
        order = "DESC" if action == "highlight_most_visited" else "ASC"
        try:
            with sqlite3.connect(str(DB_PATH)) as conn:
                rows = conn.execute(
                    f"SELECT node FROM v_node_visits ORDER BY visits {order} LIMIT ?",
                    (n_limit,),
                ).fetchall()
            resolved = [row[0] for row in rows if row[0]]
            if resolved:
                command["nodes"] = resolved
            else:
                return "(sin datos — no se han registrado traverses aún)"
        except Exception as e:
            return f"[error] No se pudieron resolver los nodos: {e}"

    # highlight_session: auto-resolver los nodos de la sesión desde SQLite
    if action == "highlight_session":
        sid = session_id or _get_session_id()
        try:
            with sqlite3.connect(str(DB_PATH)) as conn:
                rows = conn.execute(
                    """SELECT DISTINCT json_extract(params, '$.slug') as node
                       FROM events WHERE session_id = ? AND tool = 'okf_traverse'
                         AND json_extract(params, '$.slug') IS NOT NULL""",
                    (sid,),
                ).fetchall()
            resolved = [row[0] for row in rows if row[0]]
            if resolved:
                command["nodes"] = resolved
            else:
                return f"Sin nodos encontrados para la sesión {sid[:20]}..."
        except Exception as e:
            return f"[error] No se pudieron resolver los nodos de la sesión: {e}"

    _append_jsonl(command)
    info = f"Comando '{action}'"
    if command.get("nodes"):
        info += f" ({len(command['nodes'])} nodos)"
    info += " enviado al grafo."
    return info


@mcp.tool()
def file_info(slug: str, json_output: bool = False) -> str:
    """Metadatos de fecha de un concepto del vault OKF.

    Devuelve:
        - created: fecha del primer commit en git (creación real)
        - updated: fecha del último commit en git (última edición)
        - timestamp: valor del campo 'timestamp' en frontmatter (last meaningful change)
        - created_fm: valor del campo 'created' en frontmatter (fecha de creación OKF)

    Args:
        slug: Slug del concepto (ej: 'frameworks/tp3-cibernetico')
        json_output: Si True, salida JSON
    """
    args = ["file-info", "--slug", slug]
    if json_output:
        args.append("--json")
    return _run(args, tool_name="okf_file_info", params={"slug": slug, "json_output": json_output})


@mcp.tool()
def trace(query: str, layers: str = "vault,code,hooks,cron,agents") -> str:
    """Rastrea referencias a una query en todas las capas del ecosistema OKF.

    Útil antes de eliminar, renomvar o modificar componentes del sistema
    (hooks, scripts, tools, configs, paths). Responde: ¿dónde se menciona X?

    Args:
        query: Término a buscar (ej: 'post-commit', 'sistema/skills')
        layers: Capas a rastrear separadas por coma (default: todas).
                vault — wikilinks + contenido .md del vault
                code  — Python del MCP server (~/.hermes/mcp-servers/okf/)
                hooks — .git/hooks/*
                cron  — sistema/cron/ + sistema/hermes-cron-jobs/
                agents — AGENTS.md, CLAUDE.md, ~/.claude/CLAUDE.md
    """
    return _run(["trace", query, "--layers", layers], tool_name="okf_trace",
                params={"query": query, "layers": layers})


@mcp.tool()
def review() -> str:
    """Busca conceptos con cyber.review_on vencido y los reporta.

    Ejecuta 'python3 -m cli review' que escanea TODAS las fechas review_on
    del vault, sin filtrar por outcome. Más exhaustivo que search
    porque detecta vencidos con cualquier outcome (pending, success, failure).
    """
    return _run(["review"], tool_name="okf_review")


# Inicializar DB al cargar el módulo
_init_db()

if __name__ == "__main__":
    mcp.run()
