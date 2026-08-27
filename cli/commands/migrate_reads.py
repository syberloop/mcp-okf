"""migrate-reads command — mueve los read counters del frontmatter al store.

Decisión 2026-08-27: los read counters ya no viven en el frontmatter
(versionaban ruido en cada lectura y generaban conflictos constantes en
vaults multi-actor con sync automático). Este comando migra un vault:
siembra los counters actuales en .okf/state/reads.jsonl (no versionado) y
limpia el campo 'reads:' de los frontmatters.

El resultado es UN commit único de limpieza por vault (no fricción continua):
los archivos cambian una vez, y de ahí en más las lecturas no tocan git.
"""

import sys


def run(args, vault, config=None):
    from cli.reads_store import migrate_frontmatter_reads

    seeded, cleaned = migrate_frontmatter_reads(vault)
    print(f"  ✓ Contadores sembrados en el store: {seeded}")
    print(f"  ✓ Frontmatters limpiados: {cleaned}")
    if seeded:
        print("  → El store vive en .okf/state/reads.jsonl (no versionado).")
        print("  → Commiteá los cambios: git add -A && git commit")
    return 0
