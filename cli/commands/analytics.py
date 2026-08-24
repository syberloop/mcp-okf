"""Command analytics — Analytical queries on Cognitive Trace events.

Queries the SQLite events database of the OKF vault to extract patterns
of usage, navigation and tools.

Available queries:
  most_visited       — most visited nodes (top N by traverses)
  least_visited      — least visited nodes
  session_heatmap    — most active nodes in current session (or --session-id)
  tool_usage         — distribution of tools used
  daily_activity     — activity per day (events and sessions)
  node_timeline      — visit history for a node (requires --arg)
  error_summary      — tools with errors
  co_visited         — nodes visited together with --arg in the same session
  read_ratio         — reads vs traverses ratio per node
  session_diff       — nodes in session A not in B (--arg "A,B")
  depth_stats        — traverse depth distribution
  entry_points       — most used traverse entry nodes
  prompts            — auto-segmentation of session into prompts by gaps
  edge_type_usage    — ontological usage: traverses with edge_type vs without (decision criterion ≥50%)
"""

import sqlite3
import sys
from pathlib import Path

from cli.edge_types import VALID_EDGE_TYPES


def _edge_types_sql(definitions=None) -> str:
    """Vocabulario de aristas tipadas para SQL (drift-free).

    Se genera del vocabulario efectivo: defaults embebidos o config
    edge_types (decisión 2026-08-10 — vocabulario configurable).

    Args:
        definitions: Optional config-provided edge type definitions. If None,
                     uses the embedded defaults.

    Returns:
        str: SQL fragment "( 'aplica', 'corrige', ... )".
    """
    if definitions:
        types = sorted(definitions.keys())
    else:
        types = sorted(VALID_EDGE_TYPES)
    return "(" + ",".join(f"'{t}'" for t in types) + ")"


# ── Helpers ──

def _resolve_db_path(config) -> Path:
    """Resolves the path to the Cognitive Trace DB from config or default."""
    if config:
        db_path = config._data.get("features", {}).get("trace_db_path")
        if db_path:
            return Path(db_path).expanduser()
    return Path.home() / ".hermes" / "cognitive-trace.db"


def _get_session_id() -> str:
    """Attempts to infer the current session_id from the environment."""
    import os
    for _var in ("OKF_SESSION_ID", "DSH_SESSION_ID", "CLAUDE_SESSION_ID"):
        sid = os.environ.get(_var, "")
        if sid:
            return sid
    return ""


# ── Query handlers ──

def _query_most_visited(conn, limit):
    rows = conn.execute(
        "SELECT node, visits, last_visit FROM v_node_visits ORDER BY visits DESC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        return "(no data — no traverses recorded yet)"
    lines = [f"Top {len(rows)} most visited nodes:"]
    for r in rows:
        lines.append(f"  {r['node']} — {r['visits']} visits (last: {r['last_visit'][:10]})")
    return "\n".join(lines)


def _query_least_visited(conn, limit):
    rows = conn.execute(
        "SELECT node, visits, last_visit FROM v_node_visits ORDER BY visits ASC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        return "(no data)"
    lines = [f"Top {len(rows)} least visited nodes:"]
    for r in rows:
        lines.append(f"  {r['node']} — {r['visits']} visits (last: {r['last_visit'][:10]})")
    return "\n".join(lines)


def _query_session_heatmap(conn, limit, session_id):
    sid = session_id or _get_session_id()
    if not sid:
        return "[error] No session_id. Use --session-id or set OKF_SESSION_ID."
    rows = conn.execute(
        """SELECT node, COUNT(*) as visits
           FROM v_node_events
           WHERE tool_norm = 'traverse' AND session_id = ?
           GROUP BY node ORDER BY visits DESC LIMIT ?""",
        (sid, limit),
    ).fetchall()
    if not rows:
        return f"(no data for session {sid})"
    lines = [f"Most active nodes in session {sid[:20]}...:"]
    for r in rows:
        lines.append(f"  {r['node']} — {r['visits']} visits")
    return "\n".join(lines)


def _query_tool_usage(conn, limit):
    rows = conn.execute(
        """SELECT replace(CASE WHEN tool LIKE 'okf_%' THEN substr(tool, 5)
                              ELSE tool END, '-', '_') as tool_norm,
                  COUNT(*) as cnt, AVG(duration_ms) as avg_ms
           FROM events GROUP BY tool_norm ORDER BY cnt DESC"""
    ).fetchall()
    if not rows:
        return "(no data)"
    lines = ["Tool distribution:"]
    for r in rows:
        lines.append(f"  {r['tool_norm']}: {r['cnt']} calls (avg {r['avg_ms']:.0f}ms)")
    return "\n".join(lines)


def _query_daily_activity(conn, limit):
    rows = conn.execute(
        """SELECT date(ts) as day, COUNT(*) as events,
                  COUNT(DISTINCT session_id) as sessions
           FROM events GROUP BY day ORDER BY day DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    if not rows:
        return "(no data)"
    lines = ["Activity per day:"]
    for r in rows:
        lines.append(f"  {r['day']}: {r['events']} events, {r['sessions']} sessions")
    return "\n".join(lines)


def _query_node_timeline(conn, limit, arg):
    if not arg:
        return "[error] Requires --arg <slug> for node_timeline"
    node = arg.split("/")[-1]
    rows = conn.execute(
        """SELECT ts, tool FROM v_node_events
           WHERE node = ?
           ORDER BY ts DESC LIMIT ?""",
        (node, limit),
    ).fetchall()
    if not rows:
        return f"(no data for '{arg}')"
    lines = [f"History of '{arg}':"]
    for r in rows:
        lines.append(f"  {r['ts'][:19]} — {r['tool']}")
    return "\n".join(lines)


def _query_error_summary(conn, limit):
    rows = conn.execute(
        "SELECT tool, COUNT(*) as cnt FROM events WHERE exit_code != 0 "
        "GROUP BY tool ORDER BY cnt DESC"
    ).fetchall()
    if not rows:
        return "No errors recorded."
    lines = ["Tools with errors:"]
    for r in rows:
        lines.append(f"  {r['tool']}: {r['cnt']} errors")
    return "\n".join(lines)


def _query_co_visited(conn, limit, arg):
    if not arg:
        return "[error] Requires --arg <slug> for co_visited"
    node = arg.split("/")[-1]
    rows = conn.execute(
        """SELECT e2.node as co_node,
                  COUNT(DISTINCT e2.session_id) as cnt
           FROM v_node_events e1 JOIN v_node_events e2 ON e1.session_id = e2.session_id
           WHERE e1.node = ?
             AND e2.tool_norm = 'traverse'
             AND e2.node != ?
           GROUP BY co_node ORDER BY cnt DESC LIMIT ?""",
        (node, node, limit),
    ).fetchall()
    if not rows:
        return f"No node co-visited with '{arg}' in the same session."
    lines = [f"Nodes visited together with '{arg}' in the same session:"]
    for r in rows:
        lines.append(f"  {r['co_node']} — {r['cnt']} shared sessions")
    return "\n".join(lines)


def _query_read_ratio(conn, limit):
    rows = conn.execute(
        """SELECT node, visits,
                  (SELECT COUNT(*) FROM v_node_events
                   WHERE tool_norm = 'read'
                     AND node = v.node) as reads
           FROM v_node_visits v
           WHERE visits >= 2
           ORDER BY CAST(reads AS FLOAT) / visits ASC LIMIT ?""",
        (limit,),
    ).fetchall()
    if not rows:
        return "(no data — traverses and reads required)"
    lines = ["Nodes with lowest read ratio (seen but not read):"]
    for r in rows:
        ratio = (r['reads'] / r['visits'] * 100) if r['visits'] else 0
        lines.append(f"  {r['node']} — {r['reads']} reads / {r['visits']} traverses = {ratio:.0f}%")
    return "\n".join(lines)


def _query_session_diff(conn, limit, arg):
    if not arg or "," not in arg:
        return "[error] Requires --arg 'sessionA,sessionB' for session_diff"
    parts = arg.split(",", 1)
    sid_a, sid_b = parts[0].strip(), parts[1].strip()
    rows = conn.execute(
        """SELECT DISTINCT node
           FROM v_node_events WHERE session_id = ? AND tool_norm = 'traverse'
             AND node NOT IN (
               SELECT DISTINCT node
               FROM v_node_events WHERE session_id = ? AND tool_norm = 'traverse')
           LIMIT ?""",
        (sid_a, sid_b, limit),
    ).fetchall()
    if not rows:
        return "Session A has no exclusive nodes (or all are also in B)."
    lines = [f"Nodes in session A ({sid_a[:20]}...) NOT in B ({sid_b[:20]}...):"]
    for r in rows:
        lines.append(f"  {r['node']}")
    return "\n".join(lines)


def _query_depth_stats(conn, limit):
    rows = conn.execute(
        """SELECT depth, COUNT(*) as cnt
           FROM v_node_events WHERE tool_norm = 'traverse'
             AND depth IS NOT NULL
           GROUP BY depth ORDER BY depth"""
    ).fetchall()
    avg_row = conn.execute(
        "SELECT AVG(depth) as avg_depth "
        "FROM v_node_events WHERE tool_norm = 'traverse' AND depth IS NOT NULL"
    ).fetchone()
    if not rows:
        return "(no depth data)"
    lines = ["Traverse depth distribution:"]
    for r in rows:
        bar = "█" * min(r['cnt'], 50)  # cap bar width
        lines.append(f"  depth={r['depth']}: {r['cnt']} traverses {bar}")
    if avg_row and avg_row['avg_depth']:
        lines.append(f"  Average depth: {avg_row['avg_depth']:.1f}")
    return "\n".join(lines)


def _query_entry_points(conn, limit):
    rows = conn.execute(
        """SELECT node as entry, COUNT(*) as cnt
           FROM v_node_events WHERE tool_norm = 'traverse'
           GROUP BY entry ORDER BY cnt DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    if not rows:
        return "(no data)"
    lines = [f"Top {len(rows)} traverse entry points:"]
    for r in rows:
        lines.append(f"  {r['entry']} — {r['cnt']} traverses")
    return "\n".join(lines)


def _query_prompts(conn, limit, arg):
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
        return "(no data)"
    lines = [f"Prompts detected (gap > {threshold}s between events):"]
    for r in rows:
        tools = f"{r['first_tool']} → {r['last_tool']}"
        start = r['start_ts'][:19] if r['start_ts'] else "?"
        lines.append(f"  prompt #{r['prompt_id']}: {start} — {r['events']} events ({tools})")
    lines.append(f"Use --arg=N to change the threshold (default {threshold}s).")
    return "\n".join(lines)


def _query_edge_type_usage(conn, limit, definitions=None):
    """Ontological capability usage: % of traverses with edge_type.

    Measures the success criterion of Decision "Mandatory ontological reasoning"
    (2026-07-29): ≥50% of traverses with ontological ambiguity must include
    edge_type. Automatic proxy: traverses whose params contain non-empty edge_type.
    """
    total = conn.execute(
        "SELECT COUNT(*) FROM events WHERE tool IN ('okf_traverse', 'traverse')"
    ).fetchone()[0]
    typed = conn.execute(
        """SELECT COUNT(*) FROM events
           WHERE tool IN ('okf_traverse', 'traverse')
             AND COALESCE(json_extract(params, '$.edge_type'), '') != ''"""
    ).fetchone()[0]
    if not total:
        return "(no data — no traverses recorded yet)"
    pct = typed / total * 100
    lines = [
        f"Ontological traverse usage: {typed}/{total} with edge_type ({pct:.0f}%)",
        f"  Decision criterion (>=50%): {'MET' if pct >= 50 else 'NOT MET'}",
    ]
    rows = conn.execute(
        """SELECT date(ts) as day, COUNT(*) as total,
                  SUM(CASE WHEN COALESCE(json_extract(params, '$.edge_type'), '') != ''
                           THEN 1 ELSE 0 END) as typed
           FROM events WHERE tool IN ('okf_traverse', 'traverse')
           GROUP BY day ORDER BY day DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    if rows:
        lines.append("Per day:")
        for r in rows:
            p = (r['typed'] / r['total'] * 100) if r['total'] else 0
            lines.append(f"  {r['day']}: {r['typed']}/{r['total']} ({p:.0f}%)")
    ets = conn.execute(
        """SELECT json_extract(params, '$.edge_type') as et, COUNT(*) as cnt
           FROM events
           WHERE tool IN ('okf_traverse', 'traverse')
             AND COALESCE(json_extract(params, '$.edge_type'), '') != ''
           GROUP BY et ORDER BY cnt DESC"""
    ).fetchall()
    if ets:
        lines.append("Types used:")
        for r in ets:
            lines.append(f"  {r['et']}: {r['cnt']}")

    # ── Annotation effectiveness (result_edges in telemetry, 2026-08-01+) ──
    # Average per traversal: each traverse weighs equally (a dense neighborhood
    # cannot mask failures of others). Separates agent discipline (does it
    # annotate?) from graph quality (is the type correct?).
    eff = conn.execute(
        f"""SELECT declared,
                   AVG(1.0 * matched / NULLIF(total, 0)) * 100 AS eff_pct,
                   SUM(total) AS total, SUM(matched) AS matched,
                   COUNT(*) AS traverses
           FROM (
               SELECT e.id,
                      json_extract(e.params, '$.edge_type') AS declared,
                      COUNT(*) AS total,
                      SUM(CASE WHEN json_extract(je.value, '$.type') =
                                    json_extract(e.params, '$.edge_type')
                               THEN 1 ELSE 0 END) AS matched
               FROM events e, json_each(e.result_edges) je
               WHERE e.tool IN ('okf_traverse', 'traverse', 'mcp__okf__traverse')
                 AND e.result_edges IS NOT NULL
                 AND COALESCE(json_extract(e.params, '$.edge_type'), '') != ''
                 AND json_extract(je.value, '$.type') IN {_edge_types_sql(definitions)}
               GROUP BY e.id
           )
           GROUP BY declared ORDER BY traverses DESC"""
    ).fetchall()
    if eff:
        t_trav = sum(r['traverses'] for r in eff)
        t_edges = sum(r['total'] for r in eff)
        t_match = sum(r['matched'] or 0 for r in eff)
        t_pct = sum((r['eff_pct'] or 0) * r['traverses'] for r in eff) / t_trav if t_trav else 0
        lines.append(
            f"Annotation effectiveness ({t_pct:.0f}% avg over {t_trav} traverses, "
            f"{t_match}/{t_edges} edges):"
        )
        for r in eff:
            p = r['eff_pct'] or 0
            flag = "OK" if p >= 70 else "LOW"
            lines.append(f"  {r['declared']}: {p:.0f}% ({r['traverses']} trav, "
                         f"{r['matched']}/{r['total']} edges) {flag}")
        zones = conn.execute(
            f"""SELECT zone,
                       AVG(1.0 * matched / NULLIF(total, 0)) * 100 AS eff_pct,
                       COUNT(*) AS traverses
               FROM (
                   SELECT e.id,
                          CASE WHEN instr(json_extract(je.value, '$.from'), '/') > 0
                               THEN substr(json_extract(je.value, '$.from'), 1,
                                           instr(json_extract(je.value, '$.from'), '/') - 1)
                               ELSE json_extract(je.value, '$.from') END AS zone,
                          COUNT(*) AS total,
                          SUM(CASE WHEN json_extract(je.value, '$.type') =
                                        json_extract(e.params, '$.edge_type')
                                   THEN 1 ELSE 0 END) AS matched
                   FROM events e, json_each(e.result_edges) je
                   WHERE e.tool IN ('okf_traverse', 'traverse', 'mcp__okf__traverse')
                     AND e.result_edges IS NOT NULL
                     AND COALESCE(json_extract(e.params, '$.edge_type'), '') != ''
                     AND json_extract(je.value, '$.type') IN {_edge_types_sql(definitions)}
                   GROUP BY e.id, zone
               )
               GROUP BY zone HAVING COUNT(*) >= 3
               ORDER BY COUNT(*) DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        if zones:
            lines.append("By zone (source directory, >=3 traverses):")
            for r in zones:
                lines.append(f"  {r['zone']}: {r['eff_pct'] or 0:.0f}% ({r['traverses']} trav)")
    else:
        lines.append("(no effectiveness data — requires result_edges in telemetry, 2026-08-01+)")
    return "\n".join(lines)


# ── Dispatch ──

QUERIES = {
    "most_visited": _query_most_visited,
    "least_visited": _query_least_visited,
    "session_heatmap": _query_session_heatmap,
    "tool_usage": _query_tool_usage,
    "daily_activity": _query_daily_activity,
    "node_timeline": _query_node_timeline,
    "error_summary": _query_error_summary,
    "co_visited": _query_co_visited,
    "read_ratio": _query_read_ratio,
    "session_diff": _query_session_diff,
    "depth_stats": _query_depth_stats,
    "entry_points": _query_entry_points,
    "prompts": _query_prompts,
    "edge_type_usage": _query_edge_type_usage,
}

VALID_QUERIES = ", ".join(sorted(QUERIES.keys()))


def run(args, vault, config=None):
    """Runs an analytical query over Cognitive Trace events.

    Args:
        args: argparse.Namespace with query, limit, arg, session_id
        vault: Path to the vault
        config: Loaded config (optional)
    """
    db_path = _resolve_db_path(config)

    if not db_path.exists():
        print(f"[error] Database not found: {db_path}", file=sys.stderr)
        print("Make sure Cognitive Trace is active and has recorded events.", file=sys.stderr)
        return 1

    query = args.query
    if query not in QUERIES:
        print(f"[error] Unknown query: '{query}'. Valid: {VALID_QUERIES}", file=sys.stderr)
        return 1

    limit = args.limit
    arg = args.arg
    session_id = args.session_id

    try:
        definitions = config.edge_type_definitions() if config else None
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            handler = QUERIES[query]
            # Pasar solo los kwargs que el handler necesita
            import inspect
            sig = inspect.signature(handler)
            kwargs = {"conn": conn, "limit": limit}
            if "arg" in sig.parameters:
                kwargs["arg"] = arg
            if "session_id" in sig.parameters:
                kwargs["session_id"] = session_id
            if "definitions" in sig.parameters:
                kwargs["definitions"] = definitions
            result = handler(**kwargs)
            print(result)
            return 0
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
