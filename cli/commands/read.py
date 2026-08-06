"""Command read — Read a concept from the vault + auto-increment reads counter."""

import sys
from pathlib import Path
from cli.frontmatter import increment_reads


def _find_file(target, vault):
    """Searches for a file by name or relative path in the vault."""
    # Coincidencia exacta por ruta relativa
    candidate = vault / target
    if candidate.exists():
        return candidate

    # Por nombre de archivo
    for f in vault.rglob("*.md"):
        if f.name == target:
            return f

    # Por nombre parcial
    candidates = [f for f in vault.rglob("*.md") if target in str(f.relative_to(vault))]
    if len(candidates) == 1:
        return candidates[0]
    elif candidates:
        print(f"⚠ Ambiguo: {target}", file=sys.stderr)
        for c in candidates[:10]:
            print(f"  {c.relative_to(vault)}", file=sys.stderr)
        return None

    return None


def run(args, vault, config=None):
    """Reads a concept from the vault."""
    target = getattr(args, "target", None)
    if not target:
        print("Usage: python3 -m cli read <concept> [--offset N] [--limit N]",
              file=sys.stderr)
        return 1

    offset = getattr(args, "offset", 1)
    limit = getattr(args, "limit", 500)
    no_touch = getattr(args, "no_touch", False)

    filepath = _find_file(target, vault)
    if filepath is None:
        print(f"✗ Not found: {target}", file=sys.stderr)
        return 1

    rel = filepath.relative_to(vault)

    # Touch (incrementar reads)
    if not no_touch:
        new_val = increment_reads(filepath)
        if new_val:
            print(f"📖 {rel}  (reads: {new_val})", file=sys.stderr)
    else:
        print(f"📖 {rel}  (no touch)", file=sys.stderr)

    # Imprimir contenido
    print(f"─── {rel} ({filepath.stat().st_size} bytes) ───", file=sys.stderr)
    lines = filepath.read_text(encoding="utf-8").split("\n")
    total = len(lines)
    start = max(0, offset - 1)
    end = min(total, start + limit)

    for i in range(start, end):
        print(f"{i + 1}|{lines[i]}")

    if end < total:
        next_offset = end + 1
        print(f"\n─── truncated ({end}/{total} lines) — continue with --offset {next_offset} ───")

    return 0
