"""Comando analytics — Consultas analíticas sobre eventos de Cognitive Trace.

Consulta la base SQLite de eventos del vault OKF para extraer patrones
de uso, navegación y herramientas.

Queries disponibles:
  most_visited       — nodos más visitados (top N por traverses)
  least_visited      — nodos con menos visitas
  session_heatmap    — nodos más activos en la sesión actual (o --session-id)
  tool_usage         — distribución de tools usadas
  daily_activity     — actividad por día (eventos y sesiones)
  node_timeline      — historial de visitas para un nodo (requiere --arg)
  error_summary      — tools con errores
  co_visited         — nodos visitados junto con --arg en una misma sesión
  read_ratio         — proporción de reads vs traverses por nodo
  session_diff       — nodos en sesión A que no están en B (--arg "A,B")
  depth_stats        — distribución de profundidad de traverse
  entry_points       — nodos más usados como entrada de traverse
  prompts            — auto-segmentación de la sesión en prompts por gaps
  edge_type_usage    — uso ontológico: traverses con edge_type vs sin (criterio decisión ≥50%)
"""

import sqlite3
import sys
from pathlib import Path

from cli.edge_types import VALID_EDGE_TYPES

# Vocabulario de aristas tipadas para SQL (drift-free: se genera de edge_types.py)
_EDGE_TYPES_SQL = "(" + ",".join(f"'{t}'" for t in sorted(VALID_EDGE_TYPES)) + ")"


# ── Helpers ──

def _resolve_db_path(config) -> Path:
    """Resuelve la ruta a la DB de Cognitive Trace desde config o default."""
    if config:
        db_path = config._data.get("features", {}).get("trace_db_path")
        if db_path:
            return Path(db_path).expanduser()
    return Path.home() / ".hermes" / "cognitive-trace.db"


def _get_session_id() -> str:
    """Intenta inferir el session_id actual desde el entorno."""
    import os
    sid = os.environ.get("OKF_SESSION_ID", "")
    if not sid:
        sid = os.environ.get("CLAUDE_SESSION_ID", "")
    return sid


# ── Query handlers ──

def _query_most_visited(conn, limit):
    rows = conn.execute(
        "SELECT node, visits, last_visit FROM v_node_visits ORDER BY visits DESC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        return "(sin datos — no se han registrado traverses aún)"
    lines = [f"Top {len(rows)} nodos más visitados:"]
    for r in rows:
        lines.append(f"  {r['node']} — {r['visits']} visitas (última: {r['last_visit'][:10]})")
    return "\n".join(lines)


def _query_least_visited(conn, limit):
    rows = conn.execute(
        "SELECT node, visits, last_visit FROM v_node_visits ORDER BY visits ASC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        return "(sin datos)"
    lines = [f"Top {len(rows)} nodos menos visitados:"]
    for r in rows:
        lines.append(f"  {r['node']} — {r['visits']} visitas (última: {r['last_visit'][:10]})")
    return "\n".join(lines)


def _query_session_heatmap(conn, limit, session_id):
    sid = session_id or _get_session_id()
    if not sid:
        return "[error] Sin session_id. Usá --session-id o seteá OKF_SESSION_ID."
    rows = conn.execute(
        """SELECT node, COUNT(*) as visits
           FROM v_node_events
           WHERE tool_norm = 'traverse' AND session_id = ?
           GROUP BY node ORDER BY visits DESC LIMIT ?""",
        (sid, limit),
    ).fetchall()
    if not rows:
        return f"(sin datos para sesión {sid})"
    lines = [f"Nodos más activos en sesión {sid[:20]}...:"]
    for r in rows:
        lines.append(f"  {r['node']} — {r['visits']} visitas")
    return "\n".join(lines)


def _query_tool_usage(conn, limit):
    rows = conn.execute(
        """SELECT replace(CASE WHEN tool LIKE 'okf_%' THEN substr(tool, 5)
                              ELSE tool END, '-', '_') as tool_norm,
                  COUNT(*) as cnt, AVG(duration_ms) as avg_ms
           FROM events GROUP BY tool_norm ORDER BY cnt DESC"""
    ).fetchall()
    if not rows:
        return "(sin datos)"
    lines = ["Distribución de tools:"]
    for r in rows:
        lines.append(f"  {r['tool_norm']}: {r['cnt']} llamadas (promedio {r['avg_ms']:.0f}ms)")
    return "\n".join(lines)


def _query_daily_activity(conn, limit):
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
    return "\n".join(lines)


def _query_node_timeline(conn, limit, arg):
    if not arg:
        return "[error] Requiere --arg <slug> para node_timeline"
    node = arg.split("/")[-1]
    rows = conn.execute(
        """SELECT ts, tool FROM v_node_events
           WHERE node = ?
           ORDER BY ts DESC LIMIT ?""",
        (node, limit),
    ).fetchall()
    if not rows:
        return f"(sin datos para '{arg}')"
    lines = [f"Historial de '{arg}':"]
    for r in rows:
        lines.append(f"  {r['ts'][:19]} — {r['tool']}")
    return "\n".join(lines)


def _query_error_summary(conn, limit):
    rows = conn.execute(
        "SELECT tool, COUNT(*) as cnt FROM events WHERE exit_code != 0 "
        "GROUP BY tool ORDER BY cnt DESC"
    ).fetchall()
    if not rows:
        return "Sin errores registrados."
    lines = ["Tools con errores:"]
    for r in rows:
        lines.append(f"  {r['tool']}: {r['cnt']} errores")
    return "\n".join(lines)


def _query_co_visited(conn, limit, arg):
    if not arg:
        return "[error] Requiere --arg <slug> para co_visited"
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
        return f"Ningún nodo co-visitado con '{arg}' en la misma sesión."
    lines = [f"Nodos visitados junto con '{arg}' en una misma sesión:"]
    for r in rows:
        lines.append(f"  {r['co_node']} — {r['cnt']} sesiones compartidas")
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
        return "(sin datos — se necesitan traverses y reads)"
    lines = ["Nodos con menor ratio de lectura (vistos pero no leídos):"]
    for r in rows:
        ratio = (r['reads'] / r['visits'] * 100) if r['visits'] else 0
        lines.append(f"  {r['node']} — {r['reads']} reads / {r['visits']} traverses = {ratio:.0f}%")
    return "\n".join(lines)


def _query_session_diff(conn, limit, arg):
    if not arg or "," not in arg:
        return "[error] Requiere --arg 'sessionA,sessionB' para session_diff"
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
        return "La sesión A no tiene nodos exclusivos (o todos están también en B)."
    lines = [f"Nodos en sesión A ({sid_a[:20]}...) que NO están en B ({sid_b[:20]}...):"]
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
        return "(sin datos de profundidad)"
    lines = ["Distribución de profundidad de traverse:"]
    for r in rows:
        bar = "█" * min(r['cnt'], 50)  # cap bar width
        lines.append(f"  depth={r['depth']}: {r['cnt']} traverses {bar}")
    if avg_row and avg_row['avg_depth']:
        lines.append(f"  Profundidad promedio: {avg_row['avg_depth']:.1f}")
    return "\n".join(lines)


def _query_entry_points(conn, limit):
    rows = conn.execute(
        """SELECT node as entry, COUNT(*) as cnt
           FROM v_node_events WHERE tool_norm = 'traverse'
           GROUP BY entry ORDER BY cnt DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    if not rows:
        return "(sin datos)"
    lines = [f"Top {len(rows)} puntos de entrada de traverse:"]
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
        return "(sin datos)"
    lines = [f"Prompts detectados (gap > {threshold}s entre eventos):"]
    for r in rows:
        tools = f"{r['first_tool']} → {r['last_tool']}"
        start = r['start_ts'][:19] if r['start_ts'] else "?"
        lines.append(f"  prompt #{r['prompt_id']}: {start} — {r['events']} eventos ({tools})")
    lines.append(f"Usá --arg=N para cambiar el umbral (default {threshold}s).")
    return "\n".join(lines)


def _query_edge_type_usage(conn, limit):
    """Uso de capacidades ontológicas: % de traverses con edge_type.

    Mide el criterio de éxito de la Decision "Razonamiento ontológico obligatorio"
    (2026-07-29): ≥50% de traverses con ambigüedad ontológica deben incluir
    edge_type. Proxy automático: traverses cuyo params contiene edge_type no vacío.
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
        return "(sin datos — no se han registrado traverses aún)"
    pct = typed / total * 100
    lines = [
        f"Uso ontológico de traverse: {typed}/{total} con edge_type ({pct:.0f}%)",
        f"  Criterio decisión (>=50%): {'CUMPLE' if pct >= 50 else 'NO CUMPLE'}",
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
        lines.append("Por día:")
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
        lines.append("Tipos usados:")
        for r in ets:
            lines.append(f"  {r['et']}: {r['cnt']}")

    # ── Efectividad del anotado (result_edges en telemetry, 2026-08-01+) ──
    # matched/declared: aristas tipadas del tipo declarado / aristas tipadas totales.
    # Separa disciplina del agente (¿anota?) de calidad del grafo (¿el tipo es correcto?).
    eff = conn.execute(
        f"""WITH edges AS (
               SELECT json_extract(e.params, '$.edge_type') AS declared,
                      je.value AS edge
               FROM events e, json_each(e.result_edges) je
               WHERE e.tool IN ('okf_traverse', 'traverse')
                 AND e.result_edges IS NOT NULL
                 AND COALESCE(json_extract(e.params, '$.edge_type'), '') != ''
           ),
           typed AS (
               SELECT declared, edge FROM edges
               WHERE json_extract(edge, '$.type') IN {_EDGE_TYPES_SQL}
           )
           SELECT declared, COUNT(*) AS total,
                  SUM(CASE WHEN json_extract(edge, '$.type') = declared
                           THEN 1 ELSE 0 END) AS matched
           FROM typed GROUP BY declared ORDER BY total DESC"""
    ).fetchall()
    if eff:
        t_edges = sum(r['total'] for r in eff)
        t_match = sum(r['matched'] or 0 for r in eff)
        t_pct = t_match / t_edges * 100 if t_edges else 0
        lines.append(f"Efectividad del anotado ({t_match}/{t_edges} = {t_pct:.0f}%):")
        for r in eff:
            p = r['matched'] / r['total'] * 100 if r['total'] else 0
            flag = "OK" if p >= 70 else "BAJA"
            lines.append(f"  {r['declared']}: {r['matched']}/{r['total']} ({p:.0f}%) {flag}")
        zones = conn.execute(
            f"""WITH edges AS (
                   SELECT json_extract(e.params, '$.edge_type') AS declared,
                          json_extract(je.value, '$.type') AS etype,
                          json_extract(je.value, '$.from') AS from_node
                   FROM events e, json_each(e.result_edges) je
                   WHERE e.tool IN ('okf_traverse', 'traverse')
                     AND e.result_edges IS NOT NULL
                     AND COALESCE(json_extract(e.params, '$.edge_type'), '') != ''
               ),
               typed AS (
                   SELECT declared, etype, from_node FROM edges
                   WHERE etype IN {_EDGE_TYPES_SQL}
               )
               SELECT CASE WHEN instr(from_node, '/') > 0
                           THEN substr(from_node, 1, instr(from_node, '/') - 1)
                           ELSE from_node END AS zone,
                      COUNT(*) AS total,
                      SUM(CASE WHEN etype = declared THEN 1 ELSE 0 END) AS matched
               FROM typed GROUP BY zone HAVING total >= 3
               ORDER BY total DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        if zones:
            lines.append("Por zona (directorio origen, >=3 aristas):")
            for r in zones:
                p = r['matched'] / r['total'] * 100 if r['total'] else 0
                lines.append(f"  {r['zone']}: {r['matched']}/{r['total']} ({p:.0f}%)")
    else:
        lines.append("(sin datos de efectividad — requiere result_edges en telemetry, 2026-08-01+)")
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
    """Ejecuta una consulta analítica sobre los eventos de Cognitive Trace.

    Args:
        args: argparse.Namespace con query, limit, arg, session_id
        vault: Path al vault
        config: Config cargada (opcional)
    """
    db_path = _resolve_db_path(config)

    if not db_path.exists():
        print(f"[error] Base de datos no encontrada: {db_path}", file=sys.stderr)
        print("Asegurate de que Cognitive Trace esté activo y haya registrado eventos.", file=sys.stderr)
        return 1

    query = args.query
    if query not in QUERIES:
        print(f"[error] Query desconocida: '{query}'. Válidas: {VALID_QUERIES}", file=sys.stderr)
        return 1

    limit = args.limit
    arg = args.arg
    session_id = args.session_id

    try:
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
            result = handler(**kwargs)
            print(result)
            return 0
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
