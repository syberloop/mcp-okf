"""Comando graph — Analizar el grafo de wikilinks del vault OKF.

Subcomandos:
    stats, orphans, hubs, backlinks, deps, tags, bridges, cluster, path, dump, dirs, types
"""

import sys
from collections import defaultdict, deque
from pathlib import Path
from cli.vault import find_md_files, EXCLUDE_FILES
from cli.wikilinks import extract_links, resolve_link
from cli.frontmatter import extract_tags


def build_graph(vault):
    """Construye grafo dirigido: {archivo: {out: [...], in: [...]}}."""
    all_files = find_md_files(vault)
    name_index = {f.name: str(f.relative_to(vault)) for f in all_files}
    graph = {}

    for f in all_files:
        relpath = str(f.relative_to(vault))
        graph[relpath] = {"out": [], "in": []}

    for f in all_files:
        relpath = str(f.relative_to(vault))
        links = extract_links(f)
        for target in links:
            resolved = resolve_link(target, vault, f.parent, name_index)
            if resolved and resolved in graph and resolved != relpath:
                graph[relpath]["out"].append(resolved)
                graph[resolved]["in"].append(relpath)

    for node in graph:
        graph[node]["out"] = sorted(set(graph[node]["out"]))
        graph[node]["in"] = sorted(set(graph[node]["in"]))

    return graph


def build_tag_index(vault):
    """Construye índice tag → archivos."""
    all_files = find_md_files(vault)
    tag_index = defaultdict(list)
    for f in all_files:
        relpath = str(f.relative_to(vault))
        for tag in extract_tags(f):
            tag_index[tag].append(relpath)
    return dict(tag_index)


def _resolve_name(filename, graph):
    """Resuelve nombre parcial a nombre completo en el grafo."""
    if filename in graph:
        return filename
    matches = [n for n in graph if filename in n]
    if len(matches) == 1:
        return matches[0]
    if matches:
        print(f"Coincidencias para '{filename}':", file=sys.stderr)
        for m in matches[:10]:
            print(f"  {m}", file=sys.stderr)
    return None


def _cmd_stats(graph, tag_index):
    lines = [
        f"Nodos: {len(graph)}",
        f"Aristas: {sum(len(d['out']) for d in graph.values())}",
        f"Huérfanos: {sum(1 for n, d in graph.items() if not d['in'] and not d['out'])}",
    ]
    nodes = len(graph)
    edges = sum(len(d["out"]) for d in graph.values())
    density = edges / max(nodes * (nodes - 1), 1)
    lines.append(f"Densidad: {density:.3f}")

    max_out = max(graph.items(), key=lambda x: len(x[1]["out"]))
    max_in = max(graph.items(), key=lambda x: len(x[1]["in"]))
    lines.append(f"Mayor out-degree: {max_out[0]} ({len(max_out[1]['out'])})")
    lines.append(f"Mayor in-degree:  {max_in[0]} ({len(max_in[1]['in'])})")

    if tag_index is not None:
        total_tags = len(tag_index)
        shared_tags = sum(1 for t, files in tag_index.items() if len(files) >= 2)
        lines.append(f"Tags totales: {total_tags}")
        lines.append(f"Tags compartidas (≥2 archivos): {shared_tags}")
    return "\n".join(lines)


def _cmd_orphans(graph):
    orphans = [n for n, d in graph.items() if not d["in"] and not d["out"]]
    if not orphans:
        return "No hay conceptos huérfanos."
    lines = [f"{len(orphans)} concepto(s) sin links:"]
    for o in orphans:
        lines.append(f"  {o}")
    return "\n".join(lines)


def _cmd_hubs(graph):
    ranked = sorted(graph.items(), key=lambda x: len(x[1]["in"]), reverse=True)
    lines = ["Top conceptos más referenciados:"]
    for node, data in ranked[:10]:
        count = len(data["in"])
        if count == 0:
            break
        lines.append(f"  [{count}] {node}")
    return "\n".join(lines)


def _cmd_backlinks(graph, filename):
    resolved = _resolve_name(filename, graph)
    if resolved is None:
        return f"No encontrado: {filename}"
    incoming = graph[resolved]["in"]
    if not incoming:
        return f"Nadie referencia a {resolved}"
    lines = [f"← Referencian a {resolved}:"]
    for src in incoming:
        lines.append(f"  {src}")
    return "\n".join(lines)


def _cmd_deps(graph, filename):
    resolved = _resolve_name(filename, graph)
    if resolved is None:
        return f"No encontrado: {filename}"
    outgoing = graph[resolved]["out"]
    if not outgoing:
        return f"{resolved} no referencia a nadie"
    lines = [f"{resolved} → referencia a:"]
    for tgt in outgoing:
        lines.append(f"  {tgt}")
    return "\n".join(lines)


def _cmd_path(graph, origin, dest):
    for name, target in [(origin, "origin"), (dest, "dest")]:
        resolved = _resolve_name(name, graph)
        if resolved is None:
            return f"No encontrado: {name}"
        if target == "origin":
            origin = resolved
        else:
            dest = resolved

    if origin not in graph or dest not in graph:
        return "Origen o destino no encontrados."

    queue = deque([(origin, [origin])])
    visited = {origin}

    while queue:
        current, path = queue.popleft()
        if current == dest:
            return " → ".join(path)
        for neighbor in graph[current]["out"]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))

    return f"No hay camino de {origin} a {dest}"


def _cmd_cluster(graph):
    undirected = defaultdict(set)
    for node, data in graph.items():
        for tgt in data["out"]:
            undirected[node].add(tgt)
            undirected[tgt].add(node)

    visited = set()
    clusters = []

    for node in graph:
        if node in visited:
            continue
        component = []
        queue = deque([node])
        visited.add(node)
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in undirected.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        clusters.append(sorted(component))

    clusters.sort(key=len, reverse=True)
    lines = [f"{len(clusters)} componente(s) conexo(s):"]
    for i, cluster in enumerate(clusters, 1):
        lines.append(f"\n  Grupo {i} ({len(cluster)} conceptos):")
        for node in cluster:
            out_deg = len(graph[node]["out"])
            in_deg = len(graph[node]["in"])
            lines.append(f"    {node}  (→{out_deg} ←{in_deg})")
    return "\n".join(lines)


def _cmd_tags(graph, tag_index, tag_name):
    if tag_name:
        if tag_name not in tag_index:
            return f"Tag no encontrada: {tag_name}"
        files = tag_index[tag_name]
        lines = [f"🏷️  {tag_name} ({len(files)} archivo(s)):"]
        for f in files:
            other_tags = [t for t, fl in tag_index.items() if f in fl and t != tag_name]
            extra = f"  [+ {', '.join(other_tags)}]" if other_tags else ""
            lines.append(f"   - {f}{extra}")
        return "\n".join(lines)

    sorted_tags = sorted(tag_index.items(), key=lambda x: (-len(x[1]), x[0]))
    lines = [f"Tags en el vault ({len(tag_index)} total):\n"]
    for tag, files in sorted_tags:
        count = len(files)
        if count >= 2:
            lines.append(f"🏷️  {tag} ({count} archivos):")
            for f in files:
                lines.append(f"   - {f}")
        else:
            lines.append(f"   {tag} → {files[0]}")
    return "\n".join(lines)


def _cmd_bridges(graph, tag_index):
    undirected = defaultdict(set)
    for node, data in graph.items():
        for tgt in data["out"]:
            undirected[node].add(tgt)
            undirected[tgt].add(node)

    visited = set()
    clusters = []
    cluster_map = {}

    for node in graph:
        if node in visited:
            continue
        component = set()
        queue = deque([node])
        visited.add(node)
        while queue:
            current = queue.popleft()
            component.add(current)
            for neighbor in undirected.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        cid = len(clusters)
        clusters.append(component)
        for n in component:
            cluster_map[n] = cid

    lines = []
    for tag, files in sorted(tag_index.items(), key=lambda x: -len(x[1])):
        if len(files) < 2:
            continue
        cluster_ids = {cluster_map[f] for f in files if f in cluster_map}
        if len(cluster_ids) >= 2:
            lines.append(f"\n🌉  {tag} ({len(files)} archivos) — cruza {len(cluster_ids)} clusters:")
            for f in files:
                cid = cluster_map.get(f, "?")
                lines.append(f"   [{cid}] {f}")

    if not lines:
        return "No hay tags que crucen clusters."
    return "Tags puente entre clusters de wikilinks:\n" + "\n".join(lines)


def _cmd_dirs(vault):
    """Árbol de directorios con conteo de archivos de concepto.

    Agrupa por filesystem — útil para detectar sobrecarga de carpetas,
    a diferencia de cluster que agrupa por conectividad de wikilinks.
    """
    from collections import defaultdict

    all_files = find_md_files(vault)
    # Agrupar por directorio: {rel_dir: count}
    dir_counts: dict[str, int] = defaultdict(int)
    for f in all_files:
        rel = f.relative_to(vault)
        parent = str(rel.parent) if str(rel.parent) != "." else "(raíz)"
        dir_counts[parent] += 1

    # Construir árbol de prefijos para renderizado jerárquico
    prefix_tree: dict[str, dict] = {}
    for d in sorted(dir_counts):
        parts = d.split("/")
        node = prefix_tree
        for part in parts:
            if part not in node:
                node[part] = {}
            node = node[part]

    lines = [f"Directorios del vault ({len(dir_counts)} carpetas con conceptos):\n"]

    def _render(node, path_parts=(), depth=0):
        items = sorted(node.items())
        for i, (name, children) in enumerate(items):
            is_last = (i == len(items) - 1)
            connector = "└── " if is_last else "├── "
            full_path = "/".join(path_parts + (name,))

            # Buscar count: match exacto del path completo
            count = dir_counts.get(full_path, 0)
            # También intentar con "(raíz)" si es el nivel 0
            if count == 0 and depth == 0:
                count = dir_counts.get(f"(raíz)", 0)

            indent = "    " * depth
            lines.append(f"{indent}{connector}{name}/ ({count})")
            if children:
                _render(children, path_parts + (name,), depth + 1)

    _render(prefix_tree)
    return "\n".join(lines)


def _cmd_types(vault):
    """Distribución de conceptos por type (frontmatter).

    Responde: ¿cuántos Decision, Plan, Insight, etc. hay en el vault?
    Detecta desbalances estructurales — ej: muchos Insights sin Decisiones.
    """
    from collections import Counter
    from cli.frontmatter import parse_frontmatter

    all_files = find_md_files(vault)
    type_counts: Counter[str] = Counter()
    missing: list[str] = []

    for f in all_files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            missing.append(str(f.relative_to(vault)))
            continue
        fields, _ = parse_frontmatter(text)
        if fields and fields.get("type"):
            type_counts[str(fields["type"])] += 1
        else:
            missing.append(str(f.relative_to(vault)))

    if not type_counts and not missing:
        return "No se encontraron conceptos con frontmatter."

    lines = [f"Distribución por type ({sum(type_counts.values())} conceptos con type, {len(missing)} sin type):\n"]

    max_count = max(type_counts.values()) if type_counts else 1
    for t, count in type_counts.most_common():
        bar = "█" * max(1, int(20 * count / max_count))
        lines.append(f"  {t:<20} {count:>4}  {bar}")

    if missing:
        lines.append(f"\nSin type ({len(missing)}):")
        for m in missing[:15]:
            lines.append(f"  - {m}")
        if len(missing) > 15:
            lines.append(f"  ... y {len(missing) - 15} más")

    return "\n".join(lines)


def _cmd_dump(graph):
    lines = []
    for node in sorted(graph.keys()):
        data = graph[node]
        out = ", ".join(data["out"]) or "—"
        incoming = ", ".join(data["in"]) or "—"
        lines.append(f"{node}")
        lines.append(f"  → {out}")
        lines.append(f"  ← {incoming}")
        lines.append("")
    return "\n".join(lines)


def run(args, vault):
    """Ejecuta análisis de grafo."""
    subcommand = getattr(args, "subcommand", None)
    sub_args = getattr(args, "args", [])

    if not subcommand:
        # Default: dump
        graph = build_graph(vault)
        print(_cmd_dump(graph))
        return 0

    graph = build_graph(vault)
    tag_index = build_tag_index(vault)

    if subcommand == "stats":
        print(_cmd_stats(graph, tag_index))
    elif subcommand == "orphans":
        print(_cmd_orphans(graph))
    elif subcommand == "hubs":
        print(_cmd_hubs(graph))
    elif subcommand == "backlinks":
        if not sub_args:
            print("Uso: python3 -m cli graph backlinks <archivo.md>", file=sys.stderr)
            return 1
        print(_cmd_backlinks(graph, sub_args[0]))
    elif subcommand == "deps":
        if not sub_args:
            print("Uso: python3 -m cli graph deps <archivo.md>", file=sys.stderr)
            return 1
        print(_cmd_deps(graph, sub_args[0]))
    elif subcommand == "path":
        if len(sub_args) < 2:
            print("Uso: python3 -m cli graph path <origen> <destino>", file=sys.stderr)
            return 1
        print(_cmd_path(graph, sub_args[0], sub_args[1]))
    elif subcommand == "cluster":
        print(_cmd_cluster(graph))
    elif subcommand == "tags":
        print(_cmd_tags(graph, tag_index, sub_args[0] if sub_args else None))
    elif subcommand == "bridges":
        print(_cmd_bridges(graph, tag_index))
    elif subcommand == "dirs":
        print(_cmd_dirs(vault))
    elif subcommand == "types":
        print(_cmd_types(vault))
    elif subcommand == "dump":
        print(_cmd_dump(graph))
    else:
        print(f"Subcomando desconocido: {subcommand}", file=sys.stderr)
        print("Comandos: stats, orphans, hubs, backlinks, deps, tags, bridges, "
              "dirs, types, cluster, path, dump", file=sys.stderr)
        return 1

    return 0
