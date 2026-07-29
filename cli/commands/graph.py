"""Comando graph — Analizar el grafo de wikilinks del vault OKF.

Subcomandos:
    stats, orphans, hubs, backlinks, deps, tags, bridges, cluster, path,
    dump, dirs, types, suggest-edge-types
"""

import sys
from collections import defaultdict, deque
from pathlib import Path
from cli.vault import find_md_files, EXCLUDE_FILES
from cli.wikilinks import extract_links, resolve_link
from cli.frontmatter import extract_tags, extract_typed_links, parse_frontmatter


def build_graph(vault):
    """Construye grafo dirigido con aristas tipadas y no tipadas.

    Returns:
        {"relpath.md": {
            "out": [...], "in": [...],
            "typed_out": [{"target": "...", "type": "extiende"}, ...],
            "typed_in": [{"target": "...", "type": "extiende"}, ...],
        }}
    """
    all_files = find_md_files(vault)
    name_index = {f.name: str(f.relative_to(vault)) for f in all_files}
    graph = {}

    for f in all_files:
        relpath = str(f.relative_to(vault))
        graph[relpath] = {"out": [], "in": [], "typed_out": [], "typed_in": []}

    for f in all_files:
        relpath = str(f.relative_to(vault))

        # --- Wikilinks (existente) ---
        links = extract_links(f)
        for target in links:
            resolved = resolve_link(target, vault, f.parent, name_index)
            if resolved and resolved in graph and resolved != relpath:
                graph[relpath]["out"].append(resolved)
                graph[resolved]["in"].append(relpath)

        # --- Aristas tipadas desde frontmatter (NUEVO) ---
        typed_links = extract_typed_links(f)
        for tl in typed_links:
            target_raw = tl["target"]
            edge_type = tl["type"]
            resolved = resolve_link(target_raw, vault, f.parent, name_index)
            if resolved and resolved in graph and resolved != relpath:
                graph[relpath]["typed_out"].append({
                    "target": resolved,
                    "type": edge_type,
                })
                graph[resolved]["typed_in"].append({
                    "target": relpath,
                    "type": edge_type,
                })

    # Deduplicar
    for node in graph:
        graph[node]["out"] = sorted(set(graph[node]["out"]))
        graph[node]["in"] = sorted(set(graph[node]["in"]))

        seen_out = set()
        unique_out = []
        for entry in graph[node]["typed_out"]:
            key = (entry["target"], entry["type"])
            if key not in seen_out:
                seen_out.add(key)
                unique_out.append(entry)
        graph[node]["typed_out"] = sorted(
            unique_out, key=lambda x: (x["target"], x["type"])
        )

        seen_in = set()
        unique_in = []
        for entry in graph[node]["typed_in"]:
            key = (entry["target"], entry["type"])
            if key not in seen_in:
                seen_in.add(key)
                unique_in.append(entry)
        graph[node]["typed_in"] = sorted(
            unique_in, key=lambda x: (x["target"], x["type"])
        )

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
    nodes = len(graph)
    wikilinks = sum(len(d["out"]) for d in graph.values())
    typed = sum(len(d["typed_out"]) for d in graph.values())

    lines = [
        f"Nodos: {nodes}",
        f"Aristas (wikilinks): {wikilinks}",
        f"Aristas (tipadas): {typed}",
        f"Aristas totales: {wikilinks + typed}",
    ]
    edges = wikilinks + typed
    density = edges / max(nodes * (nodes - 1), 1)
    lines.append(f"Densidad: {density:.3f}")

    max_out = max(graph.items(), key=lambda x: len(x[1]["out"]))
    max_in = max(graph.items(), key=lambda x: len(x[1]["in"]))
    max_typed_out = max(graph.items(), key=lambda x: len(x[1]["typed_out"]))
    max_typed_in = max(graph.items(), key=lambda x: len(x[1]["typed_in"]))

    lines.append(f"Mayor out-degree (wikilinks): {max_out[0]} ({len(max_out[1]['out'])})")
    lines.append(f"Mayor in-degree (wikilinks):  {max_in[0]} ({len(max_in[1]['in'])})")
    if typed > 0:
        lines.append(f"Mayor typed-out: {max_typed_out[0]} ({len(max_typed_out[1]['typed_out'])})")
        lines.append(f"Mayor typed-in:  {max_typed_in[0]} ({len(max_typed_in[1]['typed_in'])})")

    huérfanos = sum(1 for n, d in graph.items()
                    if not d["in"] and not d["out"]
                    and not d["typed_in"] and not d["typed_out"])
    lines.append(f"Huérfanos: {huérfanos}")

    if tag_index is not None:
        total_tags = len(tag_index)
        shared_tags = sum(1 for t, files in tag_index.items() if len(files) >= 2)
        lines.append(f"Tags totales: {total_tags}")
        lines.append(f"Tags compartidas (≥2 archivos): {shared_tags}")
    return "\n".join(lines)


def _cmd_orphans(graph):
    orphans = [n for n, d in graph.items()
               if not d["in"] and not d["out"]
               and not d["typed_in"] and not d["typed_out"]]
    if not orphans:
        return "No hay conceptos huérfanos."
    lines = [f"{len(orphans)} concepto(s) sin links:"]
    for o in orphans:
        lines.append(f"  {o}")
    return "\n".join(lines)


def _cmd_hubs(graph):
    # Rank by total incoming (wikilinks + typed)
    ranked = sorted(
        graph.items(),
        key=lambda x: len(x[1]["in"]) + len(x[1]["typed_in"]),
        reverse=True,
    )
    lines = ["Top conceptos más referenciados:"]
    for node, data in ranked[:10]:
        count = len(data["in"]) + len(data["typed_in"])
        if count == 0:
            break
        lines.append(f"  [{count}] {node}")
    return "\n".join(lines)


def _cmd_backlinks(graph, filename, edge_type=None):
    resolved = _resolve_name(filename, graph)
    if resolved is None:
        return f"No encontrado: {filename}"

    incoming = graph[resolved]["in"]
    typed_incoming = [
        e["target"] for e in graph[resolved]["typed_in"]
        if edge_type is None or e["type"] == edge_type
    ]

    all_incoming = sorted(set(incoming + typed_incoming))

    if not all_incoming:
        filter_msg = f" (filtrado por tipo: {edge_type})" if edge_type else ""
        return f"Nadie referencia a {resolved}{filter_msg}"

    filter_msg = f" [edge_type={edge_type}]" if edge_type else ""
    lines = [f"← Referencian a {resolved}{filter_msg}:"]
    for src in all_incoming:
        # Anotar tipos de arista tipada
        typed_types = [
            e["type"] for e in graph[resolved]["typed_in"]
            if e["target"] == src
        ]
        type_str = f" [{', '.join(typed_types)}]" if typed_types else ""
        lines.append(f"  {src}{type_str}")
    return "\n".join(lines)


def _cmd_deps(graph, filename, edge_type=None):
    resolved = _resolve_name(filename, graph)
    if resolved is None:
        return f"No encontrado: {filename}"

    outgoing = graph[resolved]["out"]
    typed_outgoing = [
        e["target"] for e in graph[resolved]["typed_out"]
        if edge_type is None or e["type"] == edge_type
    ]

    all_outgoing = sorted(set(outgoing + typed_outgoing))

    if not all_outgoing:
        filter_msg = f" (filtrado por tipo: {edge_type})" if edge_type else ""
        return f"{resolved} no referencia a nadie{filter_msg}"

    filter_msg = f" [edge_type={edge_type}]" if edge_type else ""
    lines = [f"{resolved} → referencia a{filter_msg}:"]
    for tgt in all_outgoing:
        typed_types = [
            e["type"] for e in graph[resolved]["typed_out"]
            if e["target"] == tgt
        ]
        type_str = f" [{', '.join(typed_types)}]" if typed_types else ""
        lines.append(f"  {tgt}{type_str}")
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
        # Consider both wikilinks and typed edges
        neighbors = list(graph[current]["out"])
        neighbors += [e["target"] for e in graph[current]["typed_out"]]
        for neighbor in neighbors:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))

    return f"No hay camino de {origin} a {dest}"


def _cmd_cluster(graph):
    # Include both wikilinks and typed edges in undirected graph
    undirected = defaultdict(set)
    for node, data in graph.items():
        for tgt in data["out"]:
            undirected[node].add(tgt)
            undirected[tgt].add(node)
        for entry in data["typed_out"]:
            undirected[node].add(entry["target"])
            undirected[entry["target"]].add(node)

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
            out_deg = len(graph[node]["out"]) + len(graph[node]["typed_out"])
            in_deg = len(graph[node]["in"]) + len(graph[node]["typed_in"])
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
        for entry in data["typed_out"]:
            undirected[node].add(entry["target"])
            undirected[entry["target"]].add(node)

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
    """Árbol de directorios con conteo de archivos de concepto."""
    from collections import defaultdict

    all_files = find_md_files(vault)
    dir_counts: dict[str, int] = defaultdict(int)
    for f in all_files:
        rel = f.relative_to(vault)
        parent = str(rel.parent) if str(rel.parent) != "." else "(raíz)"
        dir_counts[parent] += 1

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

            count = dir_counts.get(full_path, 0)
            if count == 0 and depth == 0:
                count = dir_counts.get("(raíz)", 0)

            indent = "    " * depth
            lines.append(f"{indent}{connector}{name}/ ({count})")
            if children:
                _render(children, path_parts + (name,), depth + 1)

    _render(prefix_tree)
    return "\n".join(lines)


def _cmd_types(vault):
    """Distribución de conceptos por type (frontmatter)."""
    from collections import Counter

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
        typed_out_str = ", ".join(
            f"{e['target']}[{e['type']}]" for e in data["typed_out"]
        ) or "—"
        typed_in_str = ", ".join(
            f"{e['target']}[{e['type']}]" for e in data["typed_in"]
        ) or "—"
        lines.append(f"{node}")
        lines.append(f"  → {out}")
        lines.append(f"  ← {incoming}")
        lines.append(f"  ⇒ {typed_out_str}")
        lines.append(f"  ⇐ {typed_in_str}")
        lines.append("")
    return "\n".join(lines)


def _cmd_impact(graph, filename, vault=None):
    """Análisis de impacto ontológico: dado un nodo modificado, qué otros
    nodos deberían revisarse según las aristas tipadas.

    La dirección del impacto depende del tipo de arista:
    - X 'depende' B → B cambió → X impactado (typed_in depende)
    - B 'fundamenta' X → B cambió → X impactado (typed_out fundamenta)
    - X 'aplica' B → B cambió → X impactado (typed_in aplica)
    - X 'extiende' B → B cambió → X considerar revisión (typed_in extiende)
    - X 'refina' B → B cambió → posible impacto menor (typed_in refina)
    - X 'corrige' B → B cambió → verificar si la corrección sigue vigente
    """
    resolved = _resolve_name(filename, graph)
    if resolved is None:
        return f"No encontrado: {filename}"

    data = graph[resolved]

    # Categorizar impactos
    blocking = []   # 🔴 revisión obligatoria
    warning = []    # 🟡 considerar revisión
    info = []       # 🔵 revisar si aplica

    # X depende B → typed_in con type=depende
    for entry in data.get("typed_in", []):
        source = entry["target"]
        etype = entry["type"]
        if etype == "depende":
            blocking.append((source, f"{source} depende de este nodo"))
        elif etype == "aplica":
            blocking.append((source, f"{source} aplica este nodo"))
        elif etype == "extiende":
            warning.append((source, f"{source} extiende este nodo"))
        elif etype == "refina":
            info.append((source, f"{source} refina este nodo"))
        elif etype == "corrige":
            info.append((source, f"{source} corrige este nodo — ¿la corrección sigue vigente?"))

    # B fundamenta X → typed_out con type=fundamenta
    for entry in data.get("typed_out", []):
        target = entry["target"]
        etype = entry["type"]
        if etype == "fundamenta":
            blocking.append((target, f"este nodo fundamenta a {target}"))

    # Dependencias inversas: si B fundamenta X y B cambia, X pierde sustento
    # → ya cubierto en typed_out fundamenta arriba

    if not blocking and not warning and not info:
        return f"📋 {resolved}: sin aristas tipadas que indiquen impacto. Nadie depende ontológicamente de este nodo."

    lines = [f"📋 Si modificás '{resolved}', revisá también:\n"]

    if blocking:
        lines.append(f"🔴 REVISIÓN OBLIGATORIA ({len(blocking)}):")
        for path, reason in sorted(set(blocking)):
            lines.append(f"  {path}")
            lines.append(f"     {reason}")
        lines.append("")

    if warning:
        lines.append(f"🟡 CONSIDERAR REVISIÓN ({len(warning)}):")
        for path, reason in sorted(set(warning)):
            lines.append(f"  {path}")
            lines.append(f"     {reason}")
        lines.append("")

    if info:
        lines.append(f"🔵 INFORMATIVO ({len(info)}):")
        for path, reason in sorted(set(info)):
            lines.append(f"  {path}")
            lines.append(f"     {reason}")
        lines.append("")

    total = len(blocking) + len(warning) + len(info)
    lines.append(f"Total: {total} nodos potencialmente impactados.")

    return "\n".join(lines)


def _cmd_suggest_edge_types(vault, graph, apply=False, dry_run=False):
    """Sugiere tipos de arista para wikilinks existentes sin tipo.

    Algoritmo:
    1. Itera todas las aristas out (wikilinks) del grafo.
    2. Para cada arista A→B sin cobertura tipada, obtiene type_A y type_B
       del frontmatter y llama suggest_edge_type().
    3. Clasifica por confianza (ALTA, MEDIA, BAJA).
    4. Con --apply, escribe solo las de confianza ALTA en el frontmatter.
    """
    from cli.edge_types import suggest_edge_type
    from cli.frontmatter import parse_frontmatter

    suggestions = {"ALTA": [], "MEDIA": [], "BAJA": []}

    for source_path, data in graph.items():
        if not data["out"]:
            continue

        source_file = vault / source_path
        source_type = "?"
        source_fm = None
        try:
            text = source_file.read_text(encoding="utf-8")
            source_fm, _ = parse_frontmatter(text)
            if source_fm and source_fm.get("type"):
                source_type = str(source_fm["type"])
        except Exception:
            continue

        # Aristas ya cubiertas por links: existentes
        existing_typed = {
            tl["target"] for tl in extract_typed_links(source_file)
        }

        for target_path in data["out"]:
            if target_path in existing_typed:
                continue

            target_file = vault / target_path
            target_type = "?"
            try:
                t_text = target_file.read_text(encoding="utf-8")
                t_fm, _ = parse_frontmatter(t_text)
                if t_fm and t_fm.get("type"):
                    target_type = str(t_fm["type"])
            except Exception:
                pass

            suggested_type, confidence = suggest_edge_type(
                source_type, target_type
            )

            # Cyber override: si source tiene cyber.corrects → target,
            # sugiere 'refina' (corrige/mejora sin reemplazar).
            # 'corrige' se reserva para cuando el target está explícitamente deprecado.
            if source_fm and isinstance(source_fm.get("cyber"), dict):
                corrects = source_fm["cyber"].get("corrects", [])
                if isinstance(corrects, str):
                    corrects = [corrects]
                for ref in (corrects or []):
                    resolved_c = resolve_link(
                        ref.strip("[]"), vault, source_file.parent
                    )
                    if resolved_c == target_path:
                        # Verificar si el target está deprecado → corrige
                        target_f = vault / target_path
                        is_deprecated = False
                        try:
                            t_text = target_f.read_text(encoding="utf-8")
                            t_fm, _ = parse_frontmatter(t_text)
                            if t_fm:
                                t_status = str(t_fm.get("status", ""))
                                t_cyber = t_fm.get("cyber")
                                if "deprec" in t_status.lower():
                                    is_deprecated = True
                                if isinstance(t_cyber, dict) and t_cyber.get("corrected_by"):
                                    is_deprecated = True
                        except Exception:
                            pass
                        if is_deprecated:
                            suggested_type = "corrige"
                        else:
                            suggested_type = "refina"
                        confidence = "ALTA"
                        break

            suggestions[confidence].append({
                "source": source_path,
                "target": target_path,
                "suggested_type": suggested_type,
            })

    # --- Output ---
    lines = []
    total = sum(len(v) for v in suggestions.values())
    total_wikilinks = sum(len(d["out"]) for d in graph.values())
    lines.append(f"Aristas analizadas: {total} sin tipo (de {total_wikilinks} wikilinks totales)\n")

    for conf in ("ALTA", "MEDIA", "BAJA"):
        items = suggestions[conf]
        if not items:
            continue
        lines.append(f"=== {conf} ({len(items)} aristas) ===")
        for item in items:
            lines.append(
                f"  {item['source']} → {item['target']}: {item['suggested_type']}"
            )
        lines.append("")

    if apply:
        apply_count = 0
        for item in suggestions["ALTA"]:
            source_file = vault / item["source"]
            try:
                content = source_file.read_text(encoding="utf-8")
            except Exception:
                continue

            if not content.startswith("---"):
                continue

            end_fm = content.find("\n---\n", 3)
            if end_fm == -1:
                end_fm = content.find("\n---", 3)
            if end_fm == -1:
                continue

            fm_text = content[3:end_fm]
            after_fm = content[end_fm:]

            link_entry = f"\n  - target: {item['target']}\n    type: {item['suggested_type']}"

            if "links:" in fm_text:
                new_fm = fm_text.rstrip() + link_entry
            else:
                new_fm = fm_text.rstrip() + "\nlinks:" + link_entry

            new_content = f"---\n{new_fm}{after_fm}"

            if not dry_run:
                source_file.write_text(new_content, encoding="utf-8")
            apply_count += 1

        lines.append(f"\n{'DRY-RUN: ' if dry_run else ''}Aplicadas {apply_count} sugerencias ALTA.")
        if not dry_run:
            lines.append("⚠️  Revisa los cambios con git diff antes de commitear.")

    return "\n".join(lines)


def run(args, vault, config=None):
    """Ejecuta análisis de grafo."""
    subcommand = getattr(args, "subcommand", None)
    sub_args = getattr(args, "args", [])
    edge_type = getattr(args, "edge_type", None)
    apply_flag = getattr(args, "apply", False)
    dry_run_flag = getattr(args, "dry_run", False)

    if not subcommand:
        # Default: dump
        graph = build_graph(vault)
        print(_cmd_dump(graph))
        return 0

    # suggest-edge-types solo necesita build_graph, no tag_index
    if subcommand == "suggest-edge-types":
        graph = build_graph(vault)
        print(_cmd_suggest_edge_types(
            vault, graph, apply=apply_flag, dry_run=dry_run_flag
        ))
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
        print(_cmd_backlinks(graph, sub_args[0], edge_type=edge_type))
    elif subcommand == "deps":
        if not sub_args:
            print("Uso: python3 -m cli graph deps <archivo.md>", file=sys.stderr)
            return 1
        print(_cmd_deps(graph, sub_args[0], edge_type=edge_type))
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
    elif subcommand == "impact-batch":
        if not sub_args:
            print("Uso: python3 -m cli graph impact-batch <archivo1> <archivo2> ...", file=sys.stderr)
            return 1
        for slug in sub_args:
            print(_cmd_impact(graph, slug, vault=vault))
            print("---")
    elif subcommand == "impact":
        if not sub_args:
            print("Uso: python3 -m cli graph impact <archivo.md>", file=sys.stderr)
            return 1
        print(_cmd_impact(graph, sub_args[0], vault=vault))
    else:
        print(f"Subcomando desconocido: {subcommand}", file=sys.stderr)
        print("Comandos: stats, orphans, hubs, backlinks, deps, tags, bridges, "
              "dirs, types, cluster, path, dump, impact, suggest-edge-types", file=sys.stderr)
        return 1

    return 0
