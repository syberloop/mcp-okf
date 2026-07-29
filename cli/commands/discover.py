"""Comando discover — Búsqueda híbrida search + traverse.

search → top-3 resultados → traverse(depth=1) desde cada uno → grafo consolidado.
Una llamada, respuesta completa con relaciones.

Uso:
    python3 -m cli discover <query> [--limit N] [--json]
"""

import json
import sys
from cli.commands.search import find_concepts, matches_query
from cli.commands.graph import build_graph, _resolve_name
from cli.commands.traverse import _get_frontmatter_summary


def _discover(vault, query, limit=3, depth=1):
    """Ejecuta discover: search → top-N → traverse → grafo unificado."""
    # Fase 1: search
    concepts = find_concepts(vault)
    if query and query.strip():
        concepts = [c for c in concepts if matches_query(c, query)]

    if not concepts:
        return {"query": query, "total_hits": 0, "nodes": []}

    # Tomar top-N (mejorar: ordenar por relevancia en futuro)
    top = concepts[:limit]

    # Fase 2: traverse desde cada top hit
    graph = build_graph(vault)
    visited = set()
    nodes = []

    for hit in top:
        seed_path = hit["file"]
        resolved = _resolve_name(seed_path, graph)
        if resolved is None:
            continue

        filepath = vault / resolved
        fm = _get_frontmatter_summary(filepath)
        if fm is None:
            continue

        # Nodo semilla
        if resolved not in visited:
            visited.add(resolved)
            nodes.append({
                "path": resolved,
                "depth": 0,
                "seed": True,
                "frontmatter": fm,
            })

        # BFS depth=1
        if depth < 1:
            continue

        # Outgoing wikilinks
        out_links = graph.get(resolved, {}).get("out", [])
        for target in out_links:
            if target in visited:
                continue
            visited.add(target)
            tgt_filepath = vault / target
            tgt_fm = _get_frontmatter_summary(tgt_filepath)
            if tgt_fm:
                nodes.append({
                    "path": target,
                    "depth": 1,
                    "seed": False,
                    "frontmatter": tgt_fm,
                    "from": resolved,
                    "edge_type": "wikilink",
                })

        # Incoming backlinks
        in_links = graph.get(resolved, {}).get("in", [])
        for source in in_links:
            if source in visited:
                continue
            visited.add(source)
            src_filepath = vault / source
            src_fm = _get_frontmatter_summary(src_filepath)
            if src_fm:
                nodes.append({
                    "path": source,
                    "depth": 1,
                    "seed": False,
                    "frontmatter": src_fm,
                    "from": resolved,
                    "edge_type": "backlink",
                })

    return {
        "query": query,
        "total_hits": len(concepts),
        "seeds_used": min(limit, len(concepts)),
        "nodes": nodes,
    }


def run(args, vault, config=None):
    """Entry point del comando discover."""
    query = getattr(args, "query", None)
    limit = getattr(args, "limit", 3)
    depth = getattr(args, "depth", 1)
    json_out = getattr(args, "json", False)

    if not query:
        print("Error: --query es requerido", file=sys.stderr)
        return 1

    result = _discover(vault, query, limit=limit, depth=depth)

    if json_out:
        # Sanitizar para JSON
        clean_nodes = []
        for n in result["nodes"]:
            clean_nodes.append({
                k: v for k, v in n.items()
                if k != "frontmatter" or v is not None
            })
        result["nodes"] = clean_nodes
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    # Output legible
    print(f"🔍 discover: \"{query}\"")
    print(f"   {result['total_hits']} resultados, top {result['seeds_used']} expandidos")
    print(f"   {len(result['nodes'])} nodos en el grafo consolidado")
    print()

    seeds = [n for n in result["nodes"] if n.get("seed")]
    others = [n for n in result["nodes"] if not n.get("seed")]

    for node in seeds:
        fm = node.get("frontmatter") or {}
        ctype = fm.get("type", "?")
        status = fm.get("status", "")
        status_str = f" ({status})" if status else ""
        title = fm.get("title", "") or node["path"]
        desc = fm.get("description", "")[:100]
        print(f"📍 {node['path']} [{ctype}]{status_str} {title}")
        if desc:
            print(f"   {desc}")
        print()

    if others:
        print("─── Vecindario ───")
        print()
        for node in others:
            fm = node.get("frontmatter") or {}
            ctype = fm.get("type", "?")
            status = fm.get("status", "")
            status_str = f" ({status})" if status else ""
            title = fm.get("title", "") or node["path"]
            arrow = "→" if node.get("edge_type") == "wikilink" else "←"
            print(f"{arrow} {node['path']} [{ctype}]{status_str} {title}")
            if node.get("from"):
                print(f"   via {node['edge_type']} ← {node['from']}")
            print()

    return 0
