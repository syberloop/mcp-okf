"""Comando traverse — Travesía semántica del grafo del vault OKF.

Recorre el grafo desde un concepto origen, siguiendo wikilinks (out + in) y
aristas causales (cyber.corrects / cyber.corrected_by), hasta la profundidad
indicada. En cada nodo visitado, devuelve solo el frontmatter — no el body.

Esto permite navegación semántica eficiente: en una sola llamada se obtiene
el vecindario de un concepto sin leer N archivos completos.

Uso:
    python3 -m cli traverse <concepto> [--depth N] [--json]
                                    [--direction both|out|in] [--no-cyber]
"""

import json
import sys
from pathlib import Path
from cli.vault import build_name_index
from cli.frontmatter import parse_frontmatter, normalize_tags
from cli.commands.graph import build_graph, _resolve_name


def _get_frontmatter_summary(filepath):
    """Extrae solo el frontmatter de un archivo .md (sin el body).

    Returns:
        dict|None: Campos clave para scaneo semántico, o None si no hay frontmatter.
    """
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return None
    fm, _ = parse_frontmatter(text)
    if fm is None:
        return None
    return {
        "type": str(fm.get("type", "")),
        "title": str(fm.get("title", "")),
        "description": str(fm.get("description", "")),
        "tags": normalize_tags(fm.get("tags")),
        "status": str(fm.get("status", "")),
        "timestamp": str(fm.get("timestamp", "")),
    }


def _get_cyber_edges(filepath):
    """Extrae aristas causales del bloque cyber: de un concepto.

    Returns:
        tuple[list[str], list[str]]: (corrects, corrected_by)
    """
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return [], []
    fm, _ = parse_frontmatter(text)
    if fm is None:
        return [], []
    cyber = fm.get("cyber")
    if not isinstance(cyber, dict):
        return [], []

    corrects = cyber.get("corrects", [])
    corrected_by = cyber.get("corrected_by", [])

    if isinstance(corrects, str):
        corrects = [corrects]
    if isinstance(corrected_by, str):
        corrected_by = [corrected_by]

    return corrects or [], corrected_by or []


def _resolve_cyber_ref(ref, vault, name_index):
    """Resuelve una referencia cyber (nombre de archivo o wikilink) a ruta relativa.

    cyber.corrects puede contener:
    - Nombres de archivo sin extensión: "decision-0042"
    - Nombres con extensión: "decision-0042.md"
    - Wikilinks: "[[decision-0042]]"
    - Rutas relativas: "decisions/decision-0042.md"
    """
    ref = ref.strip()
    if not ref:
        return None

    # Quitar [[...]] si viene como wikilink
    if ref.startswith("[["):
        ref = ref.strip("[]").split("|")[0].strip()

    # Quitar #anchor
    if "#" in ref:
        ref = ref.split("#")[0]

    # Ruta con directorio
    if "/" in ref:
        if not ref.endswith(".md"):
            ref += ".md"
        candidate = vault / ref
        if candidate.exists():
            return ref
        return None

    # Nombre de archivo
    if not ref.endswith(".md"):
        ref += ".md"

    if ref in name_index:
        return name_index[ref]

    # Fallback: rglob
    for f in vault.rglob(ref):
        if f.name == ref:
            return str(f.relative_to(vault))
    return None


def run(args, vault):
    """Ejecuta travesía semántica del grafo desde un concepto origen."""
    target = getattr(args, "target", None)
    if not target:
        print("Uso: python3 -m cli traverse <concepto> [--depth N] [--json] "
              "[--direction both|out|in] [--no-cyber]",
              file=sys.stderr)
        return 1

    depth = getattr(args, "depth", 1)
    direction = getattr(args, "direction", "both")
    json_out = getattr(args, "json", False)
    no_cyber = getattr(args, "no_cyber", False)

    # Construir grafo de wikilinks (ya resuelve todos los links)
    graph = build_graph(vault)
    name_index = build_name_index(vault)

    # Resolver concepto origen
    resolved = _resolve_name(target, graph)
    if resolved is None:
        print(f"✗ No encontrado: {target}", file=sys.stderr)
        return 1

    # BFS con detección de ciclos
    visited = set()
    nodes = []
    queue = [(resolved, 0, "origin", None)]

    while queue:
        current_path, current_depth, edge_type, from_path = queue.pop(0)

        if current_path in visited:
            continue
        if current_depth > depth:
            continue

        visited.add(current_path)

        # Leer solo frontmatter (no body)
        filepath = vault / current_path
        fm_summary = _get_frontmatter_summary(filepath)

        node = {
            "path": current_path,
            "depth": current_depth,
            "edge_type": edge_type,
            "from": from_path,
            "frontmatter": fm_summary,
        }
        nodes.append(node)

        if current_depth >= depth:
            continue

        # Recolectar vecinos según dirección
        neighbors = []

        if direction in ("out", "both"):
            for tgt in graph.get(current_path, {}).get("out", []):
                neighbors.append((tgt, "wikilink"))

            if not no_cyber:
                corrects, _ = _get_cyber_edges(filepath)
                for ref in corrects:
                    resolved_ref = _resolve_cyber_ref(ref, vault, name_index)
                    if resolved_ref and resolved_ref != current_path:
                        neighbors.append((resolved_ref, "cyber.corrects"))

        if direction in ("in", "both"):
            for src in graph.get(current_path, {}).get("in", []):
                neighbors.append((src, "backlink"))

            if not no_cyber:
                _, corrected_by = _get_cyber_edges(filepath)
                for ref in corrected_by:
                    resolved_ref = _resolve_cyber_ref(ref, vault, name_index)
                    if resolved_ref and resolved_ref != current_path:
                        neighbors.append((resolved_ref, "cyber.corrected_by"))

        for neighbor_path, n_edge_type in neighbors:
            if neighbor_path not in visited:
                queue.append(
                    (neighbor_path, current_depth + 1, n_edge_type, current_path)
                )

    # ── Output JSON ──
    if json_out:
        print(json.dumps({
            "origin": resolved,
            "depth": depth,
            "direction": direction,
            "total": len(nodes),
            "nodes": nodes,
        }, indent=2, ensure_ascii=False))
        return 0

    # ── Output legible ──
    print(f"🔗 Travesía desde: {resolved}")
    print(f"   Profundidad: {depth} | Dirección: {direction} | "
          f"Nodos: {len(nodes)}")
    print()

    for node in nodes:
        indent = "  " * node["depth"]
        fm = node["frontmatter"] or {}

        if node["depth"] == 0:
            prefix = f"{indent}📍"
        else:
            arrow = "→" if node["edge_type"] in ("wikilink", "cyber.corrects") else "←"
            prefix = f"{indent}{arrow}"

        title = fm.get("title", "") or node["path"]
        desc = fm.get("description", "")
        tags = fm.get("tags", [])
        ctype = fm.get("type", "?")
        status = fm.get("status", "")

        # Truncar descripción
        desc_short = desc[:120] + "..." if len(desc) > 120 else desc
        tag_str = (
            f"[{', '.join(tags[:6])}{'...' if len(tags) > 6 else ''}]"
            if tags else ""
        )

        status_str = f" ({status})" if status else ""

        print(f"{prefix} {node['path']} [{ctype}]{status_str} {title}")
        if desc_short:
            print(f"{indent}   {desc_short}")
        if tag_str:
            print(f"{indent}   🏷️  {tag_str}")
        if node["from"]:
            print(f"{indent}   via {node['edge_type']} ← {node['from']}")
        print()

    return 0
