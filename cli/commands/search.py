"""Comando search — Buscar conceptos y tareas pendientes en el vault."""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from cli.vault import find_md_files
from cli.frontmatter import parse_frontmatter, normalize_tags


def _is_valid_frontmatter_key(key):
    return bool(key) and not str(key).startswith("#") and not str(key).startswith("- ")


def _extract_project(relative_parts):
    """Extrae el proyecto/área de la ruta relativa del archivo."""
    if len(relative_parts) <= 1:
        return "raíz"
    if relative_parts[0] == "clientes" and len(relative_parts) >= 3:
        return f"{relative_parts[0]}/{relative_parts[1]}"
    return relative_parts[0]


def _get_git_blame_cache(vault, relpath):
    """Ejecuta git blame por archivo y devuelve {line_num: (age_days, date_iso)}."""
    try:
        result = subprocess.run(
            ["git", "-C", str(vault), "blame", "--line-porcelain", "--", relpath],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None

        cache = {}
        current_start = 0
        current_count = 0
        current_ts = None

        for line in result.stdout.split("\n"):
            m = re.match(r'^[0-9a-f]{40} (\d+) (\d+) (\d+)$', line)
            if m:
                if current_ts is not None and current_start > 0:
                    commit_dt = datetime.fromtimestamp(current_ts, tz=timezone.utc)
                    age_days = (datetime.now(timezone.utc) - commit_dt).days
                    date_str = commit_dt.strftime("%Y-%m-%d")
                    for ln in range(current_start, current_start + current_count):
                        cache[ln] = (age_days, date_str)
                current_start = int(m.group(2))
                current_count = int(m.group(3))
                current_ts = None
                continue
            if line.startswith("committer-time "):
                current_ts = int(line.split()[1])

        if current_ts is not None and current_start > 0:
            commit_dt = datetime.fromtimestamp(current_ts, tz=timezone.utc)
            age_days = (datetime.now(timezone.utc) - commit_dt).days
            date_str = commit_dt.strftime("%Y-%m-%d")
            for ln in range(current_start, current_start + current_count):
                cache[ln] = (age_days, date_str)

        return cache if cache else None
    except Exception:
        return None


def find_todos(vault, include_done=False, with_aging=False):
    """Encuentra todos los - [ ] y - [x] en archivos del vault."""
    todos = []
    blame_cache = {}

    for md_file in find_md_files(vault):
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        relpath = str(md_file.relative_to(vault))
        parts = md_file.relative_to(vault).parts
        fm, _ = parse_frontmatter(text)
        fm = fm or {}
        project = _extract_project(parts)

        if with_aging and relpath not in blame_cache:
            blame_cache[relpath] = _get_git_blame_cache(vault, relpath)

        for i, line in enumerate(text.split("\n"), 1):
            m = re.match(r'^\s*- \[([ xX])\]\s+(.+)', line)
            if m:
                done = m.group(1) in ("x", "X")
                if done and not include_done:
                    continue
                entry = {
                    "file": relpath,
                    "project": project,
                    "line": i,
                    "done": done,
                    "text": m.group(2).strip(),
                    "context": fm.get("title", fm.get("description", relpath)),
                }
                if with_aging:
                    file_cache = blame_cache.get(relpath)
                    if file_cache and i in file_cache:
                        age_days, age_date = file_cache[i]
                        entry["age_days"] = age_days
                        entry["age_date"] = age_date
                        entry["age_status"] = "fresh" if age_days <= 3 else (
                            "aging" if age_days <= 7 else "stale")
                    else:
                        entry["age_days"] = None
                        entry["age_date"] = None
                        entry["age_status"] = "unknown"
                todos.append(entry)

    return todos


def find_agent_bus_signals():
    """Escanea signals/→default/ en perfiles Hermes (si existen)."""
    agent_bus_base = Path.home() / ".hermes" / "profiles"
    signals_dir_suffix = Path("agent-bus") / "signals" / "→default"
    signals = []

    if not agent_bus_base.exists():
        return signals

    for profile_dir in sorted(agent_bus_base.iterdir()):
        if not profile_dir.is_dir():
            continue
        sd = profile_dir / signals_dir_suffix
        if not sd.exists():
            continue

        profile_name = profile_dir.name
        for signal_file in sorted(sd.glob("*.md")):
            if signal_file.name == ".gitkeep":
                continue
            try:
                text = signal_file.read_text(encoding="utf-8")
            except Exception:
                continue

            fm, _ = parse_frontmatter(text)
            fm = fm or {}
            from_profile = fm.get("from", profile_name)
            ticket_ref = fm.get("ticket_ref", "")
            urgency = fm.get("urgency", "normal")
            signal_type = fm.get("type", "notification")

            ref_str = f" — {ticket_ref}" if ticket_ref else ""
            urgency_icon = "🔴" if urgency == "escalated" else "📬"

            signals.append({
                "file": f"profiles/{profile_name}/agent-bus/signals/→default/{signal_file.name}",
                "project": f"agent-bus/{profile_name}",
                "line": 0,
                "done": False,
                "text": f"{urgency_icon} [{from_profile}] {signal_type}{ref_str}",
                "context": f"[{profile_name}] {signal_file.name}",
            })

    return signals


def _sanitize_cyber(cyber):
    """Convierte objetos date/datetime a strings para JSON."""
    if cyber is None or not isinstance(cyber, dict):
        return None
    result = {}
    for k, v in cyber.items():
        if isinstance(v, (datetime,)):
            result[k] = v.isoformat() if hasattr(v, 'isoformat') else str(v)
        elif hasattr(v, 'isoformat'):
            result[k] = v.isoformat()
        elif isinstance(v, dict):
            result[k] = {
                sk: sv.isoformat() if hasattr(sv, 'isoformat') else sv
                for sk, sv in v.items()
            }
        elif isinstance(v, list):
            result[k] = [x.isoformat() if hasattr(x, 'isoformat') else x for x in v]
        else:
            result[k] = v
    return result


def find_concepts(vault):
    """Encuentra todos los conceptos con frontmatter en el vault."""
    concepts = []
    for md_file in find_md_files(vault):
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        fm, _ = parse_frontmatter(text)
        if not fm:
            continue

        relpath = str(md_file.relative_to(vault))
        parts = md_file.relative_to(vault).parts
        folder = _extract_project(parts)

        tags = normalize_tags(fm.get("tags", []))

        concepts.append({
            "file": relpath,
            "folder": folder,
            "type": str(fm.get("type", "")),
            "title": str(fm.get("title", "")),
            "status": str(fm.get("status", "")),
            "description": str(fm.get("description", "")),
            "tags": tags,
            "resource": str(fm.get("resource", "")),
            "timestamp": str(fm.get("timestamp", "")),
            "cyber": _sanitize_cyber(fm.get("cyber")),
        })

    return concepts


def matches_query(concept, query):
    """Verifica si un concepto coincide con la query (AND, case-insensitive)."""
    tokens = query.lower().split()
    if not tokens:
        return True

    searchable = " ".join([
        concept["title"],
        concept["description"],
        " ".join(concept["tags"]) if isinstance(concept["tags"], list) else "",
    ]).lower()

    for token in tokens:
        if ":" in token and not token.startswith("http"):
            field, value = token.split(":", 1)
            field = field.strip()
            value = value.strip()

            if "." in field:
                parent, child = field.split(".", 1)
                if parent == "cyber":
                    cyber = concept.get("cyber")
                    if not isinstance(cyber, dict):
                        return False
                    child_parts = child.split(".")
                    val = cyber
                    for part in child_parts:
                        if isinstance(val, dict):
                            val = val.get(part)
                        else:
                            val = None
                            break
                    if val is None:
                        return False
                    if str(val).lower() != value:
                        return False
                    continue
                return False

            if field in ("type", "status", "title"):
                if concept.get(field, "").lower() != value:
                    return False
                continue

        if token not in searchable:
            return False

    return True


def _print_todos(todos, with_aging=False):
    """Imprime tareas pendientes agrupadas por proyecto."""
    if not todos:
        print("(sin tareas pendientes)")
        return

    by_project = {}
    for t in todos:
        by_project.setdefault(t.get("project", t["file"]), []).append(t)

    total = len(todos)
    stale_count = sum(1 for t in todos if t.get("age_status") == "stale")
    aging_count = sum(1 for t in todos if t.get("age_status") == "aging")

    status_line = f"📋 Tareas pendientes ({total} encontradas)"
    if with_aging:
        parts = []
        if stale_count:
            parts.append(f"🔴 {stale_count} >7d")
        if aging_count:
            parts.append(f"🟡 {aging_count} 3-7d")
        if parts:
            status_line += " — " + ", ".join(parts)
    print(status_line)
    print("─" * 60)

    for project, items in sorted(by_project.items()):
        context = items[0]["context"]
        if context and context != items[0]["file"]:
            print(f"\n📁 {project}  — {context}")
        else:
            print(f"\n📁 {project}")

        for item in items:
            prefix = ""
            if with_aging and item.get("age_days") is not None:
                days = item["age_days"]
                if days <= 3:
                    prefix = "🟢 "
                elif days <= 7:
                    prefix = "🟡 "
                else:
                    prefix = "🔴 "
                age_info = f" ({days}d)" if days > 0 else " (hoy)"
            elif with_aging:
                prefix = "⚪ "
                age_info = " (?)"
            else:
                age_info = ""

            marker = "☑" if item.get("done") else "☐"
            print(f"  {prefix}{marker} {item['text']}{age_info}")

    print(f"\n─ {total} tarea(s) en {len(by_project)} proyecto(s)")


def _print_table(concepts):
    """Imprime tabla formateada en texto."""
    if not concepts:
        print("(sin resultados)")
        return

    cols = {
        "file": max(len(c["file"]) for c in concepts),
        "type": max(max(len(c["type"]) for c in concepts), 4),
        "status": max(max(len(c["status"]) for c in concepts), 6),
    }

    header = (
        f"{'ARCHIVO':<{cols['file']}}  "
        f"{'TIPO':<{cols['type']}}  "
        f"{'STATUS':<{cols['status']}}  "
        f"DESCRIPCIÓN"
    )
    sep = "─" * len(header)
    print(sep)
    print(header)
    print(sep)

    for c in concepts:
        desc = c["description"][:80]
        prefix = "⚠ " if c["status"] == "propuesta" else "  "
        print(
            f"{prefix}{c['file']:<{cols['file']}}  "
            f"{c['type']:<{cols['type']}}  "
            f"{c['status']:<{cols['status']}}  "
            f"{desc}"
        )

    print(sep)
    print(f"{len(concepts)} concepto(s)")


def run(args, vault, config=None):
    """Ejecuta búsqueda de conceptos o tareas."""
    json_out = getattr(args, "json", False)
    todos_mode = getattr(args, "todos", False)
    include_all = getattr(args, "all", False)
    with_aging = getattr(args, "aging", False)
    query = getattr(args, "query", None)
    filter_type = getattr(args, "filter_type", None)
    filter_status = getattr(args, "filter_status", None)
    cyber_field = getattr(args, "cyber_field", None)
    cyber_value = getattr(args, "cyber_value", None)
    review_due = getattr(args, "review_due", False)

    if with_aging and not todos_mode:
        print("Error: --aging solo funciona con --todos", file=sys.stderr)
        return 1
    if include_all and not todos_mode:
        print("Error: --all solo funciona con --todos", file=sys.stderr)
        return 1
    if cyber_value and not cyber_field:
        print("Error: --cyber-value requiere --cyber-field", file=sys.stderr)
        return 1

    if todos_mode:
        todos = find_todos(vault, include_done=include_all, with_aging=with_aging)
        agent_bus_signals = find_agent_bus_signals()
        todos.extend(agent_bus_signals)
        if json_out:
            print(json.dumps(todos, ensure_ascii=False, indent=2))
        else:
            _print_todos(todos, with_aging=with_aging)
        return 0

    concepts = find_concepts(vault)

    if query and query.strip():
        concepts = [c for c in concepts if matches_query(c, query)]
    if filter_type:
        concepts = [c for c in concepts if c["type"].lower() == filter_type.lower()]
    if filter_status:
        concepts = [c for c in concepts if c["status"].lower() == filter_status.lower()]

    if cyber_field:
        field_path = cyber_field.split(".")
        value = (cyber_value or "").lower()
        filtered = []
        for c in concepts:
            cyber = c.get("cyber")
            if not isinstance(cyber, dict):
                continue
            val = cyber
            for part in field_path:
                if isinstance(val, dict):
                    val = val.get(part)
                else:
                    val = None
                    break
            if val is not None and str(val).lower() == value:
                filtered.append(c)
        concepts = filtered

    if review_due:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filtered = []
        for c in concepts:
            cyber = c.get("cyber")
            if not isinstance(cyber, dict):
                continue
            review_on = cyber.get("review_on")
            if review_on and str(review_on) <= today_str:
                filtered.append(c)
        concepts = filtered

    if json_out:
        print(json.dumps(concepts, ensure_ascii=False, indent=2))
    else:
        _print_table(concepts)

    return 0
