"""Telemetría Cognitive Trace para la CLI del vault OKF.

Registra cada invocación de comando CLI en la base SQLite de Cognitive Trace
y en el JSONL del plugin Obsidian, igual que hace el MCP server.

La telemetría es best-effort: si falla, no interrumpe el comando.
Se activa/desactiva vía config: features.cognitive_trace (default: True).
"""

import json
import os
import re
import sqlite3
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


def init(vault: Path, config=None) -> None:
    """Inicializa la telemetría desde la configuración.

    Args:
        vault: Path al vault OKF.
        config: Objeto Config cargado (opcional).
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
    """Devuelve el session_id del entorno o genera uno local."""
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
    """Crea tablas e índices si no existen."""
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
                    nodes_count INTEGER,
                    exit_code INTEGER,
                    error TEXT,
                    duration_ms INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_events_tool ON events(tool);
                CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
                CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

                CREATE VIEW IF NOT EXISTS v_node_visits AS
                SELECT
                    json_extract(params, '$.slug') as node,
                    COUNT(*) as visits,
                    MAX(ts) as last_visit
                FROM events
                WHERE tool = 'traverse'
                  AND json_extract(params, '$.slug') IS NOT NULL
                GROUP BY node
                ORDER BY visits DESC;
            """)
    except Exception:
        pass


def _persist_sqlite(tool_name: str, params: dict, exit_code: int,
                    duration_ms: int, nodes_count: int | None = None,
                    error: str | None = None) -> None:
    """Escribe el evento a SQLite."""
    if _db_path is None or not _enabled:
        return
    try:
        with sqlite3.connect(str(_db_path)) as conn:
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
        pass


def _append_jsonl(event: dict) -> None:
    """Escribe una línea JSON al event_log.jsonl."""
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
    """Extrae paths de nodos del output de un comando.

    Soporta output --json y output textual (Markdown) de cada tool.
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


def record(tool_name: str, params: dict, exit_code: int,
           duration_ms: int, stdout: str = "", stderr: str = "") -> None:
    """Registra un evento de tool en Cognitive Trace (SQLite + JSONL).

    Args:
        tool_name: Nombre del comando (ej: 'traverse', 'read', 'search').
        params: Diccionario con los parámetros usados.
        exit_code: Código de salida (0 = éxito).
        duration_ms: Duración en milisegundos.
        stdout: Output estándar del comando (para extraer result_nodes).
        stderr: Error estándar del comando.
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

    _persist_sqlite(
        tool_name=tool_name,
        params=params,
        exit_code=exit_code,
        duration_ms=duration_ms,
        nodes_count=len(nodes) if nodes else None,
        error=error,
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

    _append_jsonl(event)


def wrap_command(tool_name: str, params: dict, func, *args, **kwargs):
    """Wrapper que ejecuta un comando CLI y registra telemetría.

    Args:
        tool_name: Nombre del comando.
        params: Parámetros como dict (del argparse namespace).
        func: Función run() del comando.
        *args, **kwargs: Argumentos para func.

    Returns:
        El exit_code retornado por func.
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
