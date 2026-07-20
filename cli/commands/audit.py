"""Comando audit — Auditar frontmatter de todos los conceptos.

Verifica que cada archivo .md del vault tenga frontmatter YAML válido
con los campos requeridos (type, description) y recomendados (title).
Además verifica conectividad: conceptos sin wikilinks generan warning,
excepto si tienen leaf: true (intencionalmente aislados).
"""

import sys
from cli.vault import resolve_vault_path, find_md_files
from cli.frontmatter import parse_frontmatter, validate_frontmatter
from cli.wikilinks import extract_links


def run(args, vault, config=None):
    """Audita frontmatter de todos los conceptos del vault."""
    all_files = find_md_files(vault)
    ok = 0
    bad = []

    for f in all_files:
        rel = str(f.relative_to(vault))
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            bad.append(f"{rel}: no se pudo leer")
            continue

        fm, _ = parse_frontmatter(text)
        errors = validate_frontmatter(fm or {})
        if errors:
            for e in errors:
                bad.append(f"{rel}: {e}")
            continue

        # Check recomendado: title
        if not (fm or {}).get("title"):
            print(f"⚠️  {rel}: Falta recomendado: title")

        # Check de conectividad: wikilinks
        is_leaf = (fm or {}).get("leaf") is True
        links = extract_links(f)
        if not links and not is_leaf:
            print(f"⚠️  {rel}: Sin wikilinks (considera agregar leaf: true si es intencional)")

        print(f"✅ {rel}")
        ok += 1

    if not bad:
        print("\n✓ Todas las notas conformes con OKF v0.1")
        return 0
    else:
        for b in bad:
            print(f"❌ {b}")
        print(f"\n✗ {len(bad)} nota(s) no conforme(s)")
        return 1
