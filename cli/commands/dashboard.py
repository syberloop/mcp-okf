"""Comando dashboard — Genera dashboard.md en la raíz del vault.

Agrega tareas pendientes con aging, score de salud y huérfanos.
Usa imports directos (no subprocess) para mejor performance.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _build_dashboard(vault):
    """Construye el contenido de dashboard.md usando imports directos."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Tareas ──
    from cli.commands.search import find_todos, find_agent_bus_signals
    todos = find_todos(vault, include_done=False, with_aging=True)
    todos.extend(find_agent_bus_signals())

    # ── Health ──
    from cli.commands.health import (
        _check_frontmatter, _check_indices, _check_graph,
        _check_broken_links, _check_scripts, _check_git_hook, _check_cyber,
    )

    fm_ok, fm_bad, fm_warn = _check_frontmatter(vault)
    idx_ok, idx_stale = _check_indices(vault)
    graph_data, graph_warn = _check_graph(vault)
    broken = _check_broken_links(vault)
    scripts_ok, scripts_failed = _check_scripts(vault)
    hook_ok, hook_err = _check_git_hook(vault)
    cyber_ok, cyber_warn, cyber_err = _check_cyber(vault)

    checks_ok = sum([
        1 if len(fm_bad) == 0 else 0,
        1 if len(idx_stale) == 0 else 0,
        1 if graph_data and graph_data.get("orphans", 99) == 0 else 0,
        1 if len(broken) == 0 else 0,
        1 if len(scripts_failed) == 0 else 0,
        1 if hook_ok else 0,
        1 if len(cyber_err) == 0 else 0,
    ])
    score = f"{checks_ok}/7"
    errors = len(fm_bad) + len(scripts_failed) + len(cyber_err) + (0 if hook_ok else 1)
    if graph_data is None:
        errors += 1
    warnings = len(fm_warn) + len(idx_stale) + len(graph_warn) + len(broken) + len(cyber_warn)

    # ── Huérfanos ──
    from cli.commands.graph import build_graph
    g = build_graph(vault)
    orphans = [n for n, d in g.items() if not d["in"] and not d["out"]]

    # ── Construir dashboard.md ──
    lines = [
        "# Dashboard OKF", "",
        f"> Regenerado: {now}", "",
    ]

    # Score
    if score == "7/7":
        icon = "🟢"
    elif int(score.split("/")[0]) >= 4:
        icon = "🟡"
    else:
        icon = "🔴"

    lines.append(f"## Salud: {icon} {score}")
    lines.append("")
    if errors:
        lines.append(f"- {errors} errores")
    if warnings:
        lines.append(f"- {warnings} warnings")
    if not errors and not warnings:
        lines.append("- Todo limpio ✅")
    lines.append("")

    # Tareas pendientes
    active_todos = [t for t in todos if not t.get("done", False)]
    lines.append(f"## Tareas pendientes ({len(active_todos)})")
    lines.append("")

    if not active_todos:
        lines.append("- Nada pendiente 🎉")
        lines.append("")
    else:
        by_project = {}
        for t in active_todos:
            proj = t.get("project", "otros")
            by_project.setdefault(proj, []).append(t)

        for proj, items in sorted(by_project.items()):
            lines.append(f"### {proj}")
            lines.append("")
            for item in items:
                age = ""
                if item.get("age_days") is not None:
                    days = item["age_days"]
                    if days <= 3:
                        age = "🟢 "
                    elif days <= 7:
                        age = "🟡 "
                    else:
                        age = "🔴 "
                    age += f"({days}d)" if days > 0 else "(hoy)"
                lines.append(f"- [ ] {item['text']} — *[{item['file']}]({item['file']})* {age}")
            lines.append("")

    # Huérfanos
    if orphans:
        lines.append("## Huérfanos")
        lines.append("")
        lines.append(f"_{len(orphans)} concepto(s) sin links:_")
        for o in orphans:
            lines.append(f"- `{o}`")
        lines.append("")

    # Footer
    lines.extend([
        "---", "",
        "> Auto-generado por `cli dashboard`. No editar manualmente.",
        f"> Última actualización: {now}",
    ])

    return "\n".join(lines) + "\n"


def run(args, vault, config=None):
    """Genera dashboard.md."""
    dashboard_content = _build_dashboard(vault)
    dashboard_path = vault / "dashboard.md"
    dashboard_path.write_text(dashboard_content, encoding="utf-8")
    print(f"  ✓ dashboard.md ({len(dashboard_content)} bytes)")
    return 0
