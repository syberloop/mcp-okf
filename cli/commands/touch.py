"""touch command — Increment reads counter or show statistics."""

import re
import sys
from pathlib import Path
from cli.frontmatter import increment_reads


def _show_stats(vault):
    """Show read stats for the entire vault."""
    from cli.vault import find_md_files

    results = []
    for md_file in find_md_files(vault):
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        if not content.startswith("---"):
            continue
        match = re.search(r'^reads:\s*(\d+)', content, re.MULTILINE)
        reads = int(match.group(1)) if match else 0
        results.append((str(md_file.relative_to(vault)), reads))

    if not results:
        print("(no concepts)")
        return 0

    results.sort(key=lambda x: x[1], reverse=True)
    total = sum(r[1] for r in results)

    print(f"{'FILE':<55} READS")
    print("-" * 65)
    for path, reads in results:
        bar = "█" * min(reads, 40) if reads > 0 else ""
        print(f"{path:<55} {reads:>3}  {bar}")
    print("-" * 65)
    print(f"{'TOTAL':<55} {total:>3}")
    return 0


def run(args, vault, config=None):
    """Increment reads counter or show statistics."""
    if getattr(args, "all", False):
        return _show_stats(vault)

    target = getattr(args, "target", None)
    if not target:
        print("Usage: python3 -m cli touch <concept> [--all]", file=sys.stderr)
        return 1

    # Buscar el archivo
    import fnmatch
    filepath = None
    for f in vault.rglob("*.md"):
        if f.name == target or str(f.relative_to(vault)) == target:
            filepath = f
            break

    if filepath is None:
        candidates = [f for f in vault.rglob("*.md") if target in str(f.relative_to(vault))]
        if len(candidates) == 1:
            filepath = candidates[0]
        else:
            print(f"Not found: {target}", file=sys.stderr)
            if candidates:
                print("Matches:", file=sys.stderr)
                for c in candidates[:10]:
                    print(f"  {c.relative_to(vault)}", file=sys.stderr)
            return 1

    new_val = increment_reads(filepath)
    rel = filepath.relative_to(vault)
    print(f"  ✓ {rel} → reads: {new_val}")
    return 0
