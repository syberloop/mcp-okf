"""Command audit — Audit frontmatter of all concepts.

Verifies that each .md file in the vault has valid YAML frontmatter
with required (type, description) and recommended (title) fields.
Also checks connectivity: concepts without wikilinks generate a warning,
unless they have leaf: true (intentionally isolated).
"""

import sys
from cli.vault import resolve_vault_path, find_md_files
from cli.frontmatter import parse_frontmatter, validate_frontmatter
from cli.wikilinks import extract_links


def run(args, vault, config=None):
    """Audits frontmatter of all concepts in the vault."""
    all_files = find_md_files(vault)
    ok = 0
    bad = []

    for f in all_files:
        rel = str(f.relative_to(vault))
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            bad.append(f"{rel}: could not read")
            continue

        fm, _ = parse_frontmatter(text)
        errors = validate_frontmatter(fm or {})
        if errors:
            for e in errors:
                bad.append(f"{rel}: {e}")
            continue

        # Check recomendado: title
        if not (fm or {}).get("title"):
            print(f"⚠️  {rel}: Missing recommended: title")

        # Check de conectividad: wikilinks
        is_leaf = (fm or {}).get("leaf") is True
        links = extract_links(f)
        if not links and not is_leaf:
            print(f"⚠️  {rel}: No wikilinks (consider adding leaf: true if intentional)")

        print(f"✅ {rel}")
        ok += 1

    if not bad:
        print("\n✓ All notes compliant with OKF v0.1")
        return 0
    else:
        for b in bad:
            print(f"❌ {b}")
        print(f"\n✗ {len(bad)} note(s) non-compliant")
        return 1
