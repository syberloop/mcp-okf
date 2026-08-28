"""touch command — Read statistics (--all). Increment mode deprecated since v0.4.1."""

import sys
from pathlib import Path


def _show_stats(vault):
    """Show read stats for the entire vault (from the telemetry store)."""
    from cli.vault import find_md_files
    from cli.reads_store import get_reads

    counts = get_reads(vault)
    results = []
    for md_file in find_md_files(vault):
        rel = str(md_file.relative_to(vault))
        results.append((rel, counts.get(rel, 0)))

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
    """Show read statistics (--all) — the ONLY supported mode since v0.4.1.

    The manual increment mode (touch <target>) is DEPRECATED: since the read
    counters moved to the local store (.okf/state/reads.jsonl, decision
    2026-08-27), `read` increments automatically. Calling touch <target>
    would double-count. It is now a documented no-op with a warning.
    """
    if getattr(args, "all", False):
        return _show_stats(vault)

    target = getattr(args, "target", None)
    if not target:
        print("Usage: python3 -m cli touch --all", file=sys.stderr)
        return 1

    print(
        f"⚠️  touch <target> está deprecado (v0.4.1): el contador de lectura "
        f"se incrementa automáticamente con `read`. Este llamado no "
        f"incrementó nada — usá `touch --all` para estadísticas de lectura.",
        file=sys.stderr,
    )
    return 0
