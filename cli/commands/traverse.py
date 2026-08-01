"""Comando traverse — Travesía semántica del grafo del vault OKF.

Recorre el grafo desde un concepto origen, siguiendo wikilinks (out + in),
aristas tipadas (links: en frontmatter) y aristas causales
(cyber.corrects / cyber.corrected_by), hasta la profundidad indicada. En cada nodo visitado, devuelve solo el frontmatter — no el body.

Esto permite navegación semántica eficiente: en una sola llamada se obtiene
el vecindario de un concepto sin leer N archivos completos.

Uso:
    python3 -m cli traverse <concepto> [--depth N] [--json]
                                    [--direction both|out|in] [--no-cyber]
                                    [--edge-type <tipo>] [--filter]

Semántica (Decisión "Cada traverse es una búsqueda ontológica", 2026-08-01):
    --edge-type declara la intención ontológica (anotación). Por defecto NO
    filtra: devuelve el vecindario completo etiquetado, ordenando primero las
    aristas del tipo declarado. El superset nunca se pierde.
    --filter convierte el edge_type en exclusión: solo aristas de ese tipo
    (comportamiento previo, para consultas que piden un solo tipo).
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


def run(args, vault, config=None):
    """Ejecuta travesía semántica del grafo desde uno o varios orígenes."""
    target = getattr(args, "target", None)
    seeds_raw = getattr(args, "seeds", None)

    # Al menos uno de target o --seeds debe estar presente
    if not target and not seeds_raw:
        print("Uso: python3 -m cli traverse <concepto> [--depth N] [--json] "
              "[--direction both|out|in] [--no-cyber]\n"
              "      python3 -m cli traverse --seeds <c1> <c2> [...] [--depth N] [...]",
              file=sys.stderr)
        return 1

    # Normalizar: si solo hay target, tratarlo como seed única
    if seeds_raw:
        seeds_candidates = seeds_raw
    else:
        seeds_candidates = [target]

    depth = getattr(args, "depth", 1)
    direction = getattr(args, "direction", "both")
    json_out = getattr(args, "json", False)
    no_cyber = getattr(args, "no_cyber", False)
    edge_type_filter = getattr(args, "edge_type", None)
    filter_mode = getattr(args, "filter", False)  # --filter: edge_type excluye (default: anotación)

    # Construir grafo de wikilinks (ya resuelve todos los links)
    graph = build_graph(vault)
    name_index = build_name_index(vault)

    # Resolver seeds. Las que no resuelven se ignoran con warning.
    resolved_seeds = []
    warnings = []
    for seed_candidate in seeds_candidates:
        resolved = _resolve_name(seed_candidate, graph)
        if resolved is None:
            warnings.append(f"No encontrado: {seed_candidate}")
        elif resolved in resolved_seeds:
            warnings.append(
                f"Semilla duplicada ignorada: {seed_candidate} -> {resolved}"
            )
        else:
            resolved_seeds.append(resolved)

    # Si TODAS las seeds fallaron, error
    if not resolved_seeds:
        for w in warnings:
            print(f"✗ {w}", file=sys.stderr)
        print("Error: ninguna semilla pudo resolverse.", file=sys.stderr)
        return 1

    # BFS con detección de ciclos y visited set compartido entre seeds
    visited = set()
    nodes = []
    # Queue entries: (path, depth, edge_type, from_path, seed_path, score)
    queue = []

    for seed_path in resolved_seeds:
        queue.append((seed_path, 0, "origin", None, seed_path, 0.0))

    while queue:
        current_path, current_depth, edge_type, from_path, seed_path, current_score = queue.pop(0)

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
        # Incluir score si la arista es tipada
        if current_score > 0:
            node["score"] = current_score
        # Incluir seed en multi-seed mode para trazabilidad
        if len(resolved_seeds) > 1:
            node["seed"] = seed_path

        nodes.append(node)

        if current_depth >= depth:
            continue

        # Recolectar vecinos según dirección
        neighbors = []

        if direction in ("out", "both"):
            for tgt in graph.get(current_path, {}).get("out", []):
                neighbors.append((tgt, "wikilink", 0.0))

            # Aristas tipadas salientes con score
            for entry in graph.get(current_path, {}).get("typed_out", []):
                neighbors.append((entry["target"], entry["type"], entry.get("score", 0.0)))

            if not no_cyber:
                corrects, _ = _get_cyber_edges(filepath)
                for ref in corrects:
                    resolved_ref = _resolve_cyber_ref(ref, vault, name_index)
                    if resolved_ref and resolved_ref != current_path:
                        neighbors.append((resolved_ref, "cyber.corrects", 0.0))

        if direction in ("in", "both"):
            for src in graph.get(current_path, {}).get("in", []):
                neighbors.append((src, "backlink", 0.0))

            # Aristas tipadas entrantes con score
            for entry in graph.get(current_path, {}).get("typed_in", []):
                neighbors.append((entry["target"], entry["type"], entry.get("score", 0.0)))

            if not no_cyber:
                _, corrected_by = _get_cyber_edges(filepath)
                for ref in corrected_by:
                    resolved_ref = _resolve_cyber_ref(ref, vault, name_index)
                    if resolved_ref and resolved_ref != current_path:
                        neighbors.append((resolved_ref, "cyber.corrected_by", 0.0))

        # Ordenar vecinos: en modo anotación, aristas del tipo declarado primero
        # (score desc dentro de cada grupo). En modo filtro, orden por score.
        if edge_type_filter and not filter_mode:
            neighbors.sort(key=lambda x: (x[1] != edge_type_filter, -x[2]))
        else:
            neighbors.sort(key=lambda x: x[2], reverse=True)

        for neighbor_path, n_edge_type, n_score in neighbors:
            if neighbor_path not in visited:
                # Modo filtro (explícito): excluir aristas que no matchean el tipo
                # Modo anotación (default): el superset completo siempre entra
                if filter_mode and edge_type_filter:
                    if n_edge_type != edge_type_filter and n_edge_type not in ("origin",):
                        continue
                queue.append(
                    (neighbor_path, current_depth + 1, n_edge_type,
                     current_path, seed_path, n_score)
                )

    # ── Output JSON ──
    if json_out:
        result = {
            "depth": depth,
            "direction": direction,
            "total": len(nodes),
            "nodes": nodes,
        }
        if len(resolved_seeds) == 1:
            result["origin"] = resolved_seeds[0]
        else:
            result["seeds"] = resolved_seeds
        if edge_type_filter:
            result["edge_type"] = edge_type_filter
            result["filter"] = filter_mode
            if not filter_mode:
                result["matched"] = len([
                    n for n in nodes
                    if n["from"] is not None and n["edge_type"] == edge_type_filter
                ])
        # Aristas resultantes para Cognitive Trace
        result["result_edges"] = [
            {"from": n["from"], "to": n["path"], "type": n["edge_type"]}
            for n in nodes if n["from"] is not None
        ]
        if warnings:
            result["warnings"] = warnings
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    # ── Output legible ──
    if len(resolved_seeds) == 1:
        print(f"🔗 Travesía desde: {resolved_seeds[0]}")
    else:
        print(f"🔗 Travesía desde {len(resolved_seeds)} semillas:")
        for s in resolved_seeds:
            print(f"   📌 {s}")
    print(f"   Profundidad: {depth} | Dirección: {direction} | "
          f"Nodos: {len(nodes)}")

    if warnings:
        print()
        for w in warnings:
            print(f"   ⚠️  {w}")

    # ── Resumen ontológico (modo anotación) ──
    if edge_type_filter and not filter_mode:
        matched = [n for n in nodes
                   if n["from"] is not None and n["edge_type"] == edge_type_filter]
        edges_total = len([n for n in nodes if n["from"] is not None])
        print()
        print(f"   🎯 Anotación: {edge_type_filter} — {len(matched)}/{edges_total} "
              f"aristas del tipo declarado (superset completo conservado)")
    elif not edge_type_filter:
        # ── Sugerencia ontológica (Nivel 2): si no se usó edge_type, sugerir ──
        typed_edge_types = {n["edge_type"] for n in nodes
                            if n["edge_type"] not in ("origin", "wikilink", "backlink",
                                                       "cyber.corrects", "cyber.corrected_by")}
        if typed_edge_types:
            et_list = ", ".join(sorted(typed_edge_types))
            typed_count = len([n for n in nodes if n["edge_type"] in typed_edge_types])
            print()
            print(f"   💡 Tip: esta travesía incluye {typed_count} "
                  f"aristas tipadas ({et_list}).")
            print(f"   Para anotar el tipo explorado: --edge-type <tipo>")
            print(f"   Para filtrar (exclusión): --edge-type <tipo> --filter")
            print(f"   Ejemplo: traverse <slug> --edge-type extiende")

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
            score_str = f" ({node.get('score', 0):.2f})" if node.get("score", 0) > 0 else ""
            print(f"{indent}   via {node['edge_type']}{score_str} ← {node['from']}")
        if len(resolved_seeds) > 1 and node.get("seed"):
            print(f"{indent}   🌰 semilla: {node['seed']}")
        print()

    return 0
