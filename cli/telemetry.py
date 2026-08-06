"""Cognitive Trace telemetry for the OKF vault CLI.

Records every CLI command invocation in the Cognitive Trace SQLite database
and in the Obsidian plugin JSONL, just like the MCP server does.

Telemetry is best-effort: if it fails, it doesn't interrupt the command.
Enabled/disabled via config: features.cognitive_trace (default: True).
"""

import json
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Global state ──

_db_path: Path | None = None
_jsonl_path: Path | None = None
_jsonl_dir: Path | None = None
_jsonl_lock = threading.Lock()
_session_id: str | None = None
_enabled: bool = True

# Máximo de result_nodes por evento
RESULT_NODES_CAP = 150
RESULT_EDGES_CAP = 500  # las aristas de un traverse pueden exceder los nodos (multi-arista por par)


def init(vault: Path, config=None) -> None:
    """Initializes telemetry from configuration.

    Args:
        vault: Path to OKF vault.
        config: Loaded Config object (optional).
    """
    global _db_path, _jsonl_path, _jsonl_dir, _enabled

    if config is not None:
        _enabled = config.features_cognitive_trace if hasattr(config, 'features_cognitive_trace') else True
        if not _enabled:
            return
        trace_db = config._data.get("features", {}).get("trace_db_path")
        trace_jsonl = config._data.get("features", {}).get("trace_jsonl_path")
    else:
        _enabled = True
        trace_db = None
        trace_jsonl = None

    if trace_db:
        _db_path = Path(trace_db).expanduser()
    else:
        _db_path = Path.home() / ".hermes" / "cognitive-trace.db"

    if trace_jsonl:
        _jsonl_path = Path(trace_jsonl).expanduser()
        _jsonl_dir = _jsonl_path.parent
    else:
        _jsonl_dir = vault / ".obsidian" / "plugins" / "cognitive-trace"
        _jsonl_path = _jsonl_dir / "event_log.jsonl"

    _ensure_db()


def _get_session_id() -> str:
    """Returns the session_id from the environment or generates a local one."""
    global _session_id
    if _session_id:
        return _session_id
    sid = os.environ.get("OKF_SESSION_ID", "")
    if not sid:
        sid = os.environ.get("HERMES_SESSION_ID", "")
    if not sid:
        sid = os.environ.get("CLAUDE_SESSION_ID", "")
    if not sid:
        sid = "cli"
    _session_id = sid
    return sid


def _ensure_db() -> None:
    """Creates tables and indexes if they don't exist."""
    if _db_path is None or _jsonl_dir is None or not _enabled:
        return
    _jsonl_dir.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(str(_db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    params TEXT NOT NULL DEFAULT '{}',
                    result_edges TEXT,
                    nodes_count INTEGER,
                    exit_code INTEGER,
                    error TEXT,
                    duration_ms INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_events_tool ON events(tool);
                CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
                CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

                DROP VIEW IF EXISTS v_node_events;
                CREATE VIEW v_node_events AS
                SELECT
                    session_id,
                    ts,
                    CASE WHEN tool IN ('okf_traverse', 'traverse') THEN 'traverse'
                         WHEN tool IN ('okf_read', 'read') THEN 'read'
                         WHEN tool IN ('okf_search', 'search') THEN 'search'
                         ELSE replace(tool, '-', '_') END AS tool_norm,
                    json_extract(params, '$.slug') AS raw_node,
                    CASE WHEN instr(json_extract(params, '$.slug'), '/') > 0
                         THEN substr(json_extract(params, '$.slug'),
                                     instr(json_extract(params, '$.slug'), '/') + 1)
                         ELSE json_extract(params, '$.slug') END AS node,
                    json_extract(params, '$.depth') AS depth,
                    exit_code
                FROM events
                WHERE json_extract(params, '$.slug') IS NOT NULL;

                DROP VIEW IF EXISTS v_node_visits;
                CREATE VIEW v_node_visits AS
                SELECT
                    node,
                    COUNT(*) as visits,
                    MAX(ts) as last_visit
                FROM v_node_events
                WHERE tool_norm = 'traverse'
                GROUP BY node
                ORDER BY visits DESC;
            """)
        # Migración idempotente: tablas creadas antes de result_edges
        try:
            conn.execute("ALTER TABLE events ADD COLUMN result_edges TEXT")
        except Exception as e:
            # "duplicate column" es el caso esperado (ya migrada); el resto se reporta
            # sin romper el CLI (el telemetry nunca debe interrumpir una tool call)
            if "duplicate column" not in str(e).lower():
                print(f"[telemetry] ALTER TABLE result_edges failed: {e}", file=sys.stderr)
    except Exception:
        pass


def _persist_sqlite(tool_name: str, params: dict, exit_code: int,
                    duration_ms: int, nodes_count: int | None = None,
                    error: str | None = None, result_edges: list[dict] | None = None) -> None:
    """Writes the event to SQLite."""
    if _db_path is None or not _enabled:
        return
    try:
        with sqlite3.connect(str(_db_path)) as conn:
            conn.execute(
                """INSERT INTO events
                   (session_id, ts, tool, params, result_edges, nodes_count, exit_code, error, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    _get_session_id(),
                    datetime.now(timezone.utc).isoformat(),
                    tool_name,
                    json.dumps(params, ensure_ascii=False),
                    json.dumps(result_edges, ensure_ascii=False) if result_edges else None,
                    nodes_count,
                    exit_code,
                    error,
                    duration_ms,
                ),
            )
    except Exception:
        pass


def _append_jsonl(event: dict) -> None:
    """Writes a JSON line to event_log.jsonl."""
    if _jsonl_path is None or not _enabled:
        return
    try:
        _jsonl_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with _jsonl_lock:
            with open(_jsonl_path, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass


def _extract_nodes(tool_name: str, params: dict, stdout: str) -> list[str] | None:
    """Extracts node paths from command output.

    Supports --json output and text (Markdown) output from each tool.
    """
    if not stdout:
        return None
    try:
        nodes: list[str] = []
        if tool_name == "okf_traverse":
            if params.get("json"):
                data = json.loads(stdout)
                nodes = [n.get("path", "") for n in data.get("nodes", [])]
            else:
                # Output textual:
                #   📍 frameworks/grafo-cibernetico-marco-teorico.md [MarcoTeorico] ...
                #   → frameworks/tp3-cibernetico.md [MarcoTeorico] ...
                #   ← agentes/dreaming-vault-analista-creativo.md [Agente] ...
                for line in stdout.splitlines():
                    # Match lines starting with arrow + space + path.md
                    m = re.match(r"\s*(?:📍|→|←)\s+(\S+)", line)
                    if m:
                        path = m.group(1)
                        if path.endswith(".md"):
                            nodes.append(path)
        elif tool_name == "okf_read":
            # El slug del concepto leído está en params
            slug = params.get("slug") or params.get("target")
            if slug:
                if not slug.endswith(".md"):
                    slug += ".md"
                nodes = [slug]
        elif tool_name == "okf_search":
            # --todos / --all producen listas de tareas, no conceptos navegables
            if params.get("todos") or params.get("all"):
                return None
            if params.get("json"):
                data = json.loads(stdout)
                nodes = [item.get("file", "") for item in data]
            else:
                # Output textual: tabla con columna ARCHIVO (paths .md)
                for line in stdout.splitlines():
                    for tok in line.split():
                        if tok.endswith(".md"):
                            nodes.append(tok)
                            break
        elif tool_name == "okf_stale":
            if params.get("json"):
                data = json.loads(stdout)
                nodes = [item.get("file", "") for item in data]
            else:
                # 📄 [Type] path/file.md
                for line in stdout.splitlines():
                    m = re.match(r"\s*📄\s+\[\w+\]\s+(\S+)", line)
                    if m:
                        nodes.append(m.group(1))
        elif tool_name == "okf_graph":
            cmd = params.get("subcommand", "")
            if cmd in ("stats", "tags", "bridges", "dirs", "types"):
                return None
            for line in stdout.splitlines():
                m = re.search(r"(\S+\.md)", line)
                if m:
                    nodes.append(m.group(1))
        elif tool_name == "okf_analytics":
            # "  slug — N visitas (...)"
            for line in stdout.splitlines():
                m = re.match(r"\s+(\S+)\s+—", line)
                if m:
                    nodes.append(m.group(1))
        elif tool_name == "okf_health":
            # No extrae nodos (es agregación)
            return None
        elif tool_name == "okf_new":
            # El path creado está en params o se puede inferir
            slug = params.get("created_path")
            if slug:
                if not slug.endswith(".md"):
                    slug += ".md"
                nodes = [slug]
        else:
            return None
        nodes = [n for n in nodes if n]
        return nodes[:RESULT_NODES_CAP] or None
    except Exception:
        return None


def _extract_edges(tool_name: str, params: dict, stdout: str) -> list[dict] | None:
    """Extracts result edges (result_edges) from traverse output.

    Source: JSON output (result_edges field) or text output ("via <type> ← <from>").
    Feeds the ontological annotation effectiveness metric (matched/declared).
    """
    if tool_name != "okf_traverse" or not stdout:
        return None
    try:
        edges: list[dict] = []
        if params.get("json"):
            data = json.loads(stdout)
            edges = data.get("result_edges", []) or []
        else:
            # Textual: cada nodo imprime "via <edge_type>[ (score)] ← <from>"
            # El nodo actual (to) está en la línea previa (📍/→/← + path.md)
            last_path = None
            for line in stdout.splitlines():
                nm = re.match(r"\s*(?:📍|→|←)\s+(\S+\.md)", line)
                if nm:
                    last_path = nm.group(1)
                    continue
                em = re.search(r"via (\S+)(?: \([\d.]+\))?\s*←\s*(\S+\.md)", line)
                if em and last_path:
                    edges.append({"from": em.group(2), "to": last_path, "type": em.group(1)})
        edges = [e for e in edges if e.get("from") and e.get("to") and e.get("type")]
        return edges[:RESULT_EDGES_CAP] or None
    except Exception:
        return None


def record(tool_name: str, params: dict, exit_code: int,
           duration_ms: int, stdout: str = "", stderr: str = "") -> None:
    """Records a tool event in Cognitive Trace (SQLite + JSONL).

    Args:
        tool_name: Command name (e.g.: 'traverse', 'read', 'search').
        params: Dictionary with the parameters used.
        exit_code: Exit code (0 = success).
        duration_ms: Duration in milliseconds.
        stdout: Standard output of the command (to extract result_nodes).
        stderr: Standard error of the command.
    """
    if not _enabled:
        return

    # Si viene del MCP server, el server ya escribe su propio evento.
    # Saltamos para no duplicar cada tool call en el timeline.
    if os.environ.get("OKF_MCP_CALLER") == "1":
        return

    error = None
    if exit_code != 0 and stderr:
        error = stderr[:500]

    nodes = _extract_nodes(tool_name, params, stdout)
    edges = _extract_edges(tool_name, params, stdout)

    _persist_sqlite(
        tool_name=tool_name,
        params=params,
        exit_code=exit_code,
        duration_ms=duration_ms,
        nodes_count=len(nodes) if nodes else None,
        error=error,
        result_edges=edges,
    )

    event = {
        "type": "tool",
        "session": _get_session_id(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool_name,
        "params": params,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
    }
    if nodes:
        event["result_nodes"] = nodes
    if edges:
        event["result_edges"] = edges

    _append_jsonl(event)


def wrap_command(tool_name: str, params: dict, func, *args, **kwargs):
    """Wrapper that runs a CLI command and records telemetry.

    Args:
        tool_name: Command name.
        params: Parameters as dict (from argparse namespace).
        func: Command's run() function.
        *args, **kwargs: Arguments for func.

    Returns:
        The exit_code returned by func.
    """
    start = time.monotonic()
    exit_code = 1
    stdout = ""
    stderr = ""
    try:
        # Capturamos stdout/stderr para telemetría
        import io
        import sys
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            exit_code = func(*args, **kwargs) or 0
        finally:
            stdout = sys.stdout.getvalue()
            stderr = sys.stderr.getvalue()
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            # Re-emitir lo capturado al output real
            if stdout:
                old_stdout.write(stdout)
            if stderr:
                old_stderr.write(stderr)
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
    except Exception:
        exit_code = 1

    duration_ms = int((time.monotonic() - start) * 1000)
    record(tool_name, params, exit_code, duration_ms, stdout, stderr)

    return exit_code
