"""Comando file-info — Metadatos de fecha de un concepto del vault.

Devuelve:
    - created: fecha del primer commit en git (creación real)
    - updated: fecha del último commit en git (última edición)
    - timestamp: valor del campo 'timestamp' en frontmatter (last meaningful change)
    - created_fm: valor del campo 'created' en frontmatter (fecha de creación OKF)
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from cli.frontmatter import parse_frontmatter


def _get_git_dates(vault, relpath):
    """Obtiene created (primer commit) y updated (último commit) desde git."""
    created = None
    updated = None

    try:
        # Último commit
        result = subprocess.run(
            ["git", "-C", str(vault), "log", "-1", "--format=%ai", "--", relpath],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            updated = result.stdout.strip()

        # Primer commit
        result = subprocess.run(
            ["git", "-C", str(vault), "log", "--diff-filter=A", "--follow",
             "--format=%ai", "--", relpath],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            created = result.stdout.strip().split("\n")[-1]
    except Exception:
        pass

    return created, updated


def run(args, vault, config=None):
    slug = getattr(args, "slug", None)
    json_out = getattr(args, "json", False)

    if not slug:
        print("Error: --slug es requerido", file=sys.stderr)
        return 1

    # Resolver el archivo
    md_file = vault / slug
    if not md_file.exists():
        # Intentar con .md
        md_file = vault / f"{slug}.md"
    if not md_file.exists():
        print(f"Error: archivo no encontrado: {slug}", file=sys.stderr)
        return 1

    relpath = str(md_file.relative_to(vault))

    # Leer frontmatter
    try:
        text = md_file.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error: no se pudo leer {relpath}: {e}", file=sys.stderr)
        return 1

    fm, _ = parse_frontmatter(text)
    fm = fm or {}

    timestamp = str(fm.get("timestamp", ""))
    created_fm = str(fm.get("created", ""))

    # Fechas de git
    git_created, git_updated = _get_git_dates(vault, relpath)

    result = {
        "file": relpath,
        "type": str(fm.get("type", "")),
        "title": str(fm.get("title", "")),
        "created": git_created,
        "updated": git_updated,
        "timestamp": timestamp or None,
        "created_fm": created_fm or None,
    }

    if json_out:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"📄 {result['title'] or relpath}")
    print(f"   type: {result['type']}")
    print(f"   created (git):  {git_created or 'N/A'}")
    print(f"   updated (git):  {git_updated or 'N/A'}")
    print(f"   timestamp (fm): {timestamp or 'N/A'}")
    print(f"   created (fm):   {created_fm or 'N/A'}")

    return 0
