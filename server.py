#!/usr/bin/env python3
"""MCP server that wraps python3 -m cli for the OKF vault.

Exposes traverse, search, read, graph, health, index, touch, new, review as MCP tools
so the Hermes agent has them as native zero-friction functions,
eliminating the toolset bias that diverts the agent toward mcp__gbrain__get_page.

Uses FastMCP (mcp.server.fastmcp) — JSON-RPC stdio protocol.

Persists every tool call to SQLite (analytics) and JSONL (Cognitive Trace plugin in Obsidian).
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

# Docker persistence pattern (skill multi-tenant-profile): deps installed with
# pip --target live in a volume dir that must take precedence over both the
# script dir (sys.path[0]) and the image venv. If OKF_PYLIBS is set, prepend it
# BEFORE importing mcp/fastmcp, and propagate it to subprocesses via PYTHONPATH
# (the CLI subprocess is a fresh interpreter that does not inherit sys.path).
_pylibs = os.environ.get("OKF_PYLIBS")
if _pylibs:
    sys.path.insert(0, _pylibs)
    _pp = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = _pylibs + ((":" + _pp) if _pp else "")

from mcp.server.fastmcp import FastMCP

# Vault path configurable per instance: --vault <path> CLI arg (wins) or
# OKF_VAULT env var (multi-vault pattern: one MCP server instance per vault,
# same server.py). Default: ~/OKF-Vault.
_default_vault = os.environ.get("OKF_VAULT", str(Path.home() / "OKF-Vault"))
_vault_arg = None
if "--vault" in sys.argv:
    try:
        _vault_arg = sys.argv[sys.argv.index("--vault") + 1]
    except IndexError:
        pass
VAULT = Path(_vault_arg or _default_vault).expanduser()
MCP_DIR = Path(__file__).parent
CLI = ["python3", "-m", "cli", "--vault", str(VAULT)]

# Subprocess PYTHONPATH: MCP_DIR (donde vive el paquete cli) + lo que el entorno
# traiga (en Docker: /opt/data/pylibs con mcp 1.28.1 + yaml). Sin esta unión,
# el subprocess pierde pylibs y falla con ModuleNotFoundError (yaml, etc.).
_SUBPROCESS_PYTHONPATH = str(MCP_DIR) + (
    (":" + os.environ["PYTHONPATH"]) if os.environ.get("PYTHONPATH") else ""
)

# Externalized configuration (loaded on startup)
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

# Max result_nodes per event (bound on JSONL line size)
RESULT_NODES_CAP = 150

mcp = FastMCP("cli")


# ── Persistencia Cognitive Trace ────────────────────────────────────────────

def _get_session_id() -> str:
    """Returns the harness session_id (OKF/DSH/Hermes) or generates a local one."""
    for _var in ("OKF_SESSION_ID", "DSH_SESSION_ID", "HERMES_SESSION_ID"):
        _sid = os.environ.get(_var, "")
        if _sid:
            return _sid
    # Fallback: try reading from state file
    state_file = Path.home() / ".hermes" / "session_state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            return state.get("session_id", "local")
        except (json.JSONDecodeError, OSError):
            pass
    return "local"


def _init_db() -> None:
    """Creates tables and indexes if they don't exist."""
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

            CREATE VIEW IF NOT EXISTS v_session_activity AS
            SELECT
                session_id,
                MIN(ts) as started_at,
                MAX(ts) as ended_at,
                COUNT(*) as total_events,
                COUNT(DISTINCT tool) as unique_tools
            FROM events
            GROUP BY session_id;

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
            if "duplicate column" not in str(e).lower():
                print(f"[server] ALTER TABLE result_edges failed: {e}", file=sys.stderr)


def _persist_event(tool_name: str, params: dict, result: "subprocess.CompletedProcess",
                   duration_ms: int, nodes_count: int | None = None,
                   result_edges: list | None = None) -> None:
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
        pass  # no dejar que la persistencia rompa el MCP


def _append_jsonl(event: dict) -> None:
    """Writes a JSON line to event_log.jsonl."""
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
    """Extracts the relative path of the file created by new."""
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        if "Created:" not in line:
            continue
        raw_path = line.split("Created:", 1)[1].strip()
        try:
            relative = Path(raw_path).resolve().relative_to(VAULT.resolve())
            return str(relative)
        except ValueError:
            return None
    return None


def _extract_result_nodes(tool_name: str, args: list[str],
                          result: "subprocess.CompletedProcess") -> list[str] | None:
    """Extracts result nodes from command output (traverse/search) for visual trace.

    traverse in text mode does not print each node's path → re-run with --json
    (so the caller sends this case to a thread, to not add latency to the tool
    call). search in text mode does print paths (ARCHIVO column) → free parse.
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
                                       env={**os.environ, "PYTHONPATH": _SUBPROCESS_PYTHONPATH, "OKF_MCP_CALLER": "1",
                 "OKF_SESSION_ID": _get_session_id()})
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
            # most_visited, least_visited, session_heatmap return lines
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
    """Extracts result_edges from traverse JSON output for Cognitive Trace."""
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
                                   env={**os.environ, "PYTHONPATH": _SUBPROCESS_PYTHONPATH, "OKF_MCP_CALLER": "1",
                 "OKF_SESSION_ID": _get_session_id()})
            if rerun.returncode != 0:
                return None
            data = json.loads(rerun.stdout)
        return data.get("result_edges")
    except Exception:
        return None


def _parse_graph_output(stdout: str, args: list[str]) -> list[str]:
    """Extracts node paths from okf_graph text output.

    okf_graph has no --json flag. Commands that return concrete lists
    of files (hubs, backlinks, deps, orphans, cluster, dump)
    use formats with .md paths. Aggregation commands
    (stats, tags, bridges) produce no node lists → ignored.
    """
    cmd = args[1] if len(args) > 1 else (args[0] if args else "")
    # Commands that don't return individual files
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
    """Extracts result_nodes and persists the event to SQLite + JSONL."""
    if tool_name == "okf_new":
        created_path = _extract_created_path(result)
        if created_path:
            params = {**params, "created_path": created_path}
    nodes = _extract_result_nodes(tool_name, args, result)
    edges = _extract_result_edges(tool_name, args, result)
    _persist_event(tool_name, params, result, duration_ms,
                   nodes_count=len(nodes) if nodes else None,
                   result_edges=edges)
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
    if edges:
        event["result_edges"] = edges
    _append_jsonl(event)


# ── Core ────────────────────────────────────────────────────────────────────

def _run(args: list[str], tool_name: str = "unknown", params: dict | None = None,
         timeout: int = 30) -> str:
    """Runs python3 -m cli <args> from the vault and returns stdout.

    Persists event to SQLite + JSONL as a side effect.
    """
    try:
        start = time.monotonic()
        result = subprocess.run(
            CLI + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": _SUBPROCESS_PYTHONPATH, "OKF_MCP_CALLER": "1",
                 "OKF_SESSION_ID": _get_session_id()},
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        if result.returncode != 0:
            output += f"\n[exit_code: {result.returncode}]"
        # Persist synchronously to preserve arrival order in
        # SQLite/JSONL. Secondary traverse extraction must not reorder
        # subsequent events nor be lost on process exit.
        _finish_event(tool_name, params or {}, result, duration_ms, list(args))
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired as e:
        duration_ms = int((time.monotonic() - start) * 1000) if "start" in locals() else timeout * 1000
        result = subprocess.CompletedProcess(
            args=CLI + args,
            returncode=124,
            stdout=e.stdout or "",
            stderr=f"Timeout after {timeout}s",
        )
        _finish_event(tool_name, params or {}, result, duration_ms, list(args))
        return "[timeout] The command exceeded the time limit."
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
def traverse(slug: str = "", depth: int = 2, direction: str = "both", no_cyber: bool = False, json_output: bool = False, seeds: str = "", edge_type: str = "", filter: bool = False) -> str:
    """Semantic traversal of the OKF graph. Returns concept frontmatter + neighborhood (wikilinks, backlinks, cyber.corrects).

    PRIMARY USE for querying the vault. Prefer over search.

    ONTOLOGICAL SEMANTICS (Decision "Every traverse is an ontological search", 2026-08-01):
    edge_type is MANDATORY — declares the relationship explored (annotation). By default does NOT
    filter: returns the full neighborhood labeled, and sorts edges of the declared
    type first. Pass filter=True only for explicit exclusion (a single type).

    Args:
        slug: Concept slug (e.g.: 'grafo-cibernetico-marco-teorico' or 'frameworks/tp3-cibernetico')
        depth: Traversal depth (default 2)
        direction: 'both' (default), 'out' (outgoing only), 'in' (incoming only)
        no_cyber: If True, does not follow cyber.corrects/corrected_by edges
        json_output: If True, JSON output for programmatic consumption
        seeds: Comma-separated slugs for multiple origins (union + deduplication).
               e.g.: 'frameworks/tp3-cibernetico,decisions/description-cibernetico-okf'
        edge_type: MANDATORY — ontological type explored (extiende, refina, fundamenta,
                   aplica, depende, corrige). Annotates without filtering.
        filter: If True, edge_type excludes edges not of that type (explicit exclusion).
    """
    if not edge_type or not edge_type.strip():
        return "[error] traverse requires edge_type: every traverse is an ontological search — declare the explored type (extiende|refina|fundamenta|aplica|depende|corrige). See Decision 2026-08-01."
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
        return "[error] Must specify 'slug' or 'seeds'"

    args += ["--depth", str(depth)]
    if direction in ("out", "in"):
        args += ["--direction", direction]
    if no_cyber:
        args.append("--no-cyber")
    if json_output:
        args.append("--json")
    args += ["--edge-type", edge_type]
    params["edge_type"] = edge_type
    if filter:
        args.append("--filter")
        params["filter"] = True
    return _run(args, tool_name="okf_traverse", params=params)


@mcp.tool()
def search(query: str = "", type: str = "", status: str = "", cyber_field: str = "", cyber_value: str = "", todos: bool = False, json_output: bool = False, since: str = "", until: str = "", with_graph: bool = False) -> str:
    """FTS5 search in the OKF vault. FALLBACK — prefer traverse or index reads.

    Use only when:
    - Traversal doesn't find a path in ≤6 hops
    - You need to filter by specific fields (type, status, cyber)
    - You're looking for pending tasks (--todos)
    - You need to filter by date range (--since, --until)

    Args:
        query: Search term (optional if using --todos or --type)
        type: Filter by type (Decision, Plan, Project, Insight, etc.)
        status: Filter by status (propuesta, aplicada, etc.)
        cyber_field: cyber block field (outcome, sensor, target_metric.name)
        cyber_value: cyber field value (pending, success, failure)
        todos: If True, searches for pending - [ ] tasks
        json_output: If True, JSON output
        since: Filter by timestamp >= date (ISO 8601, inclusive, e.g. "2026-07-20")
        until: Filter by timestamp <= date (ISO 8601, inclusive)
        with_graph: If True, includes ## Detected relationships section with typed edges between results
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
    if with_graph:
        args.append("--with-graph")
    return _run(args, tool_name="okf_search", params={
        "query": query, "type": type, "status": status,
        "cyber_field": cyber_field, "cyber_value": cyber_value,
        "todos": todos, "json_output": json_output,
        "since": since, "until": until,
    })


@mcp.tool()
def read(slug: str, offset: int = 1, limit: int = 500, no_touch: bool = False) -> str:
    """Reads a concept from the OKF vault and increments its read counter.

    Use to read the full body of a concept after traverse
    confirms its relevance. NEVER use system read_file on vault .md files.

    Args:
        slug: Concept slug (e.g.: 'decisions/mcp-okf-cli-como-correccion-de-sesgo-de-toolset')
        offset: Starting line (1-indexed, default 1)
        limit: Max lines (default 500)
        no_touch: If True, does not increment the read counter
    """
    args = ["read", slug, "--offset", str(offset), "--limit", str(limit)]
    if no_touch:
        args.append("--no-touch")
    return _run(args, tool_name="okf_read", params={
        "slug": slug, "offset": offset, "limit": limit, "no_touch": no_touch,
    })


@mcp.tool()
def graph(command: str, arg: str = "", edge_type: str = "") -> str:
    """Analyzes the wikilink graph, typed edges, and tags of the OKF vault.

    Useful for questions about relationships, dependencies, structure, or thematic grouping.

    Args:
        command: Graph command. One of:
            - 'stats': overall status (total nodes, orphans, tags, typed edges)
            - 'orphans': concepts without wikilinks
            - 'hubs': most referenced concepts
            - 'backlinks': concepts that reference ARG (requires arg)
            - 'deps': concepts referenced by ARG (requires arg)
            - 'tags': all tags or filter by ARG
            - 'bridges': tags that connect wikilink clusters
            - 'cluster': vault clustering
            - 'dump': full graph dump
            - 'dirs': directory tree with concept counts
            - 'types': concept distribution by type (frontmatter)
            - 'suggest-edge-types': suggests edge types for existing wikilinks
        arg: Additional argument (concept slug for backlinks/deps, tag name for tags)
        edge_type: Filter backlinks/deps by edge type (extiende, refina, etc.)
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
def graph_suggest_edge_types(apply: bool = False, min_score: float = 0.0) -> str:
    """Suggests edge types for existing untyped wikilinks.

    Analyzes all graph edges and proposes semantic types
    (extiende, refina, fundamenta, aplica, depende, corrige) based
    on source and target node types, with semantic scoring 0.0-1.0
    (structural fit, tag overlap, description similarity, graph precedent).

    Args:
        apply: If True, writes HIGH confidence suggestions to the frontmatter.
        min_score: Minimum semantic score (0.0-1.0) to apply. With apply=True,
                   discards suggestions with score < min_score. Default 0.0 = no filter.
    """
    args = ["graph", "suggest-edge-types"]
    params = {"command": "suggest-edge-types", "apply": apply, "min_score": min_score}
    if apply:
        args.append("--apply")
    if min_score > 0:
        args += ["--min-score", str(min_score)]
    return _run(args, tool_name="okf_graph", params=params)


@mcp.tool()
def graph_impact(slug: str) -> str:
    """Ontological impact analysis: which nodes to review if this one changes.

    Follows typed edges in the direction of impact to determine
    which concepts ontologically depend on this node and should
    be reviewed if it is modified.

    Args:
        slug: Slug of the modified concept (e.g.: 'frameworks/tp3-cibernetico')
    """
    return _run(["graph", "impact", slug], tool_name="okf_graph",
                params={"command": "impact", "arg": slug})


@mcp.tool()
def health(strict: bool = False, json_output: bool = False) -> str:
    """Complete health check of the OKF vault (8 checks).

    Verifies: frontmatter, indexes, graph (orphans, density), broken links,
    scripts (smoke test), git hook, cyber block, plugin↔spec sync.

    Args:
        strict: If True, exit code 1 if there are warnings
        json_output: If True, JSON output
    """
    args = ["health"]
    if strict:
        args.append("--strict")
    if json_output:
        args.append("--json")
    return _run(args, tool_name="okf_health", params={"strict": strict, "json_output": json_output})


@mcp.tool()
def index() -> str:
    """Regenerates all index.md and log.md in the OKF vault.

    Normally run by the pre-commit hook. Use manually only if
    indexes are out of date and you won't commit immediately.
    """
    return _run(["index"], tool_name="okf_index", params={})


@mcp.tool()
def touch(all: bool = True) -> str:
    """Read statistics of the OKF vault.

    Args:
        all: If True (default), shows table with counters + frequency bars
    """
    args = ["touch"]
    if all:
        args.append("--all")
    return _run(args, tool_name="okf_touch", params={})


@mcp.tool()
def session_metrics(json_output: bool = False) -> str:
    """Aggregated metrics of all vault sessions.

    Extracts metrics from the ## Metrics section of each session summary:
    tools used, concepts created, commits, MCP violations.
    Aggregates totals and trends.

    Args:
        json_output: If True, JSON output for programmatic consumption
    """
    args = ["session-metrics"]
    if json_output:
        args.append("--json")
    return _run(args, tool_name="okf_session_metrics", params={"json_output": json_output})


@mcp.tool()
def stale(json_output: bool = False) -> str:
    """Semantic staleness detector of the OKF vault.

    Evaluates 7 signals (timestamp, reads, phantom proposal, orphans,
    commits, decision without status, description vs body) and classifies each
    concept as STALE (3+ signals), ATTENTION (1-2) or FRESH (0).

    Read-only. Does not modify the vault. Use for weekly audit
    of concepts requiring human attention.

    Args:
        json_output: If True, JSON output for programmatic consumption
    """
    args = ["stale"]
    if json_output:
        args.append("--json")
    return _run(args, tool_name="okf_stale", params={"json_output": json_output})


@mcp.tool()
def new(type: str, title: str, description: str, tags: str = "", status: str = "", cyber: bool = False, dry_run: bool = False, body: str = "", links: str = "", entity: str = "") -> str:
    """Creates a new concept in the OKF vault with consistent frontmatter.

    ALWAYS use this instead of write_file to create concepts.

    Args:
        type: Concept type (Decision, Plan, Project, Insight, MarcoTeorico, etc.)
        title: Descriptive title
        description: One-line summary (required for navigability)
        tags: Comma-separated tags (optional)
        status: Initial status (propuesta, aplicada, etc.)
        cyber: If True and the type qualifies, adds cyber block with placeholders
        dry_run: If True, previews without writing
        body: Full body content (optional — if omitted, uses default template)
        links: Comma-separated typed links, format target:type
               (e.g.: 'frameworks/tp3:extiende,decisions/criterio:refina')
        entity: Entity slug for by_entity types (e.g.: type=Cliente entity=Lopcort
                → clientes/Lopcort/<slug>.md). Required when the type groups
                by entity (types.by_entity in config).
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
    if entity:
        args += ["--entity", entity]
    return _run(args, tool_name="okf_new", params={
        "type": type, "title": title, "description": description,
        "tags": tags, "status": status, "cyber": cyber, "dry_run": dry_run,
        "body": body[:100] + "..." if len(body) > 100 else body,
        "links": links if links else None,
    })


# ── Cognitive Trace: Analytics + Commands ───────────────────────────────────

@mcp.tool()
def analytics(query: str = "most_visited", limit: int = 10,
                  arg: str = "", session_id: str = "") -> str:
    """Analytical query over trace events of the OKF vault.

    Args:
        query: Query type:
            - 'most_visited': most visited nodes (top N by traverse visits)
            - 'least_visited': least visited nodes
            - 'session_heatmap': most active nodes in the current session
            - 'tool_usage': distribution of tools used
            - 'daily_activity': daily activity (events and sessions)
            - 'node_timeline': visit history for a node (requires slug in arg)
            - 'error_summary': tools with errors
            - 'co_visited': nodes visited together with arg in the same session (requires slug in arg)
            - 'read_ratio': read vs traverse ratio per node (how deeply nodes are explored)
            - 'session_diff': nodes visited in session A not in B (arg="A,B")
            - 'depth_stats': traverse depth distribution
            - 'entry_points': most used traverse entry nodes
            - 'prompts': auto-segmentation of session into prompts by >60s gaps between events
            - 'edge_type_usage': ontological graph usage — traverses with edge_type vs without (measures ≥50% criteria from Decision razonamiento-ontologico-obligatorio)
        limit: Result limit (default 10)
        arg: Additional argument (slug for node_timeline/co_visited, "sessionA,sessionB" for session_diff)
        session_id: Filter by session (empty = all)

    Delegated to CLI (analytics.py) — single source of truth. Previous inline
    duplication caused divergence (NameError tool_name, tool names and slugs
    without normalization). See decision in the vault.
    """
    return _run(
        ["analytics", "--query", query, "--limit", str(limit),
         "--arg", arg, "--session-id", session_id],
        tool_name="okf_analytics",
        params={"query": query, "limit": limit, "arg": arg, "session_id": session_id},
    )


@mcp.tool()
def graph_command(action: str, nodes: str = "", tag: str = "",
                      color: str = "#FF6B35", session_id: str = "") -> str:
    """Sends a command to the Cognitive Trace plugin in Obsidian via JSONL.

    Args:
        action: Action to execute:
            - 'highlight_nodes': highlight specific nodes (requires nodes)
            - 'highlight_most_visited': highlight top N most visited (uses analytics internally)
            - 'highlight_least_visited': highlight N least visited
            - 'focus_cluster': focus nodes of a tag (requires tag)
            - 'highlight_session': highlight nodes of a session (requires session_id)
            - 'highlight_path': highlight path between nodes (nodes: "A,B,C")
            - 'clear_highlights': clear all highlights
            - 'reset_graph': return to base state
        nodes: Comma-separated slug list (for highlight_nodes, highlight_path).
               For highlight_most_visited / highlight_least_visited: number of nodes to highlight (default 10).
        tag: Tag for focus_cluster
        color: Color in hex (#RRGGBB, default #FF6B35 orange)
        session_id: Session ID (for highlight_session)
    """
    valid = {
        "highlight_nodes", "highlight_most_visited", "highlight_least_visited",
        "focus_cluster", "highlight_session", "highlight_path",
        "clear_highlights", "reset_graph",
    }
    if action not in valid:
        return f"[error] Unknown action: '{action}'. Valid: {', '.join(sorted(valid))}"

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
                return "(no data — no traverses recorded yet)"
        except Exception as e:
            return f"[error] Could not resolve nodes: {e}"

    # highlight_session: auto-resolve session nodes from SQLite
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
                return f"No nodes found for session {sid[:20]}..."
        except Exception as e:
            return f"[error] Could not resolve session nodes: {e}"

    _append_jsonl(command)
    info = f"Command '{action}'"
    if command.get("nodes"):
        info += f" ({len(command['nodes'])} nodes)"
    info += " sent to graph."
    return info


@mcp.tool()
def file_info(slug: str, json_output: bool = False) -> str:
    """Date metadata for a concept in the OKF vault.

    Returns:
        - created: date of the first commit in git (real creation)
        - updated: date of the last commit in git (last edit)
        - timestamp: value of the 'timestamp' field in frontmatter (last meaningful change)
        - created_fm: value of the 'created' field in frontmatter (OKF creation date)

    Args:
        slug: Concept slug (e.g.: 'frameworks/tp3-cibernetico')
        json_output: If True, JSON output
    """
    args = ["file-info", "--slug", slug]
    if json_output:
        args.append("--json")
    return _run(args, tool_name="okf_file_info", params={"slug": slug, "json_output": json_output})


@mcp.tool()
def canvas(action: str, path: str = "", slug: str = "", algorithm: str = "auto",
           depth: int = 1, fix: bool = False, dry_run: bool = False,
           output: str = "") -> str:
    """Generates, layouts and validates Obsidian .canvas maps of the vault graph.

    The .canvas format is the same graph drawn in 2D — the system drawing
    itself (corteza visual layer). Three actions:
      - validate: sensor. Checks JSON, IDs, grid alignment, overlaps,
        z-index, placeholders. Returns valid/warnings/errors. --fix auto-aligns.
      - layout:   actuador. Re-layouts a canvas with an algorithm
        (grid, dagre, radial, force, linear, auto).
      - generate: materializes the vault graph around a concept as a canvas.
        BFS from slug at depth, typed edges become edge labels (extiende,
        refina...). Output defaults to mapas/<slug>.canvas.

    Args:
        action: One of 'validate', 'layout', 'generate'
        path: Path to .canvas file (validate/layout)
        slug: Root concept slug, e.g. 'insights/canvas-como-corteza-visual' (generate)
        algorithm: Layout algorithm: grid, dagre, radial, force, linear, auto (layout/generate)
        depth: BFS depth from root concept (generate, default 1)
        fix: Auto-fix grid alignment and color types (validate)
        dry_run: Compute layout without writing (layout)
        output: Output path (generate; default mapas/<slug>.canvas)
    """
    if action == "validate":
        args = ["canvas", "validate", path]
        if fix:
            args.append("--fix")
    elif action == "layout":
        args = ["canvas", "layout", path, algorithm]
        if dry_run:
            args.append("--dry-run")
    elif action == "generate":
        args = ["canvas", "generate", slug, "--depth", str(depth), "--layout", algorithm]
        if output:
            args += ["--output", output]
    else:
        raise ValueError(f"Unknown canvas action: {action}")
    return _run(args, tool_name="okf_canvas",
                params={"action": action, "path": path, "slug": slug,
                        "algorithm": algorithm, "depth": depth,
                        "fix": fix, "dry_run": dry_run, "output": output})


@mcp.tool()
def trace(query: str, layers: str = "vault,code,hooks,cron,agents") -> str:
    """Traces references to a query across all layers of the OKF ecosystem.

    Useful before deleting, renaming or modifying system components
    (hooks, scripts, tools, configs, paths). Answers: where is X mentioned?

    Args:
        query: Search term (e.g.: 'post-commit', 'sistema/skills')
        layers: Layers to trace, comma-separated (default: all).
                vault — wikilinks + .md content of the vault
                code  — Python of the MCP server (~/.hermes/mcp-servers/okf/)
                hooks — .git/hooks/*
                cron  — sistema/cron/ + sistema/hermes-cron-jobs/
                agents — AGENTS.md, CLAUDE.md, ~/.claude/CLAUDE.md
    """
    return _run(["trace", query, "--layers", layers], tool_name="okf_trace",
                params={"query": query, "layers": layers})


@mcp.tool()
def review() -> str:
    """Finds concepts with expired cyber.review_on and reports them.

    Runs 'python3 -m cli review' which scans ALL review_on dates
    in the vault, without filtering by outcome. More exhaustive than search
    because it detects expired items with any outcome (pending, success, failure).
    """
    return _run(["review"], tool_name="okf_review")


# Initialize DB on module load
_init_db()

if __name__ == "__main__":
    mcp.run()
