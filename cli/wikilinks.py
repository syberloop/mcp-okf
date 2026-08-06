"""Extraction and resolution of wikilinks and markdown links.

Responsibilities:
- Extract targets from [[wikilinks]] and [text](path.md)
- Resolve targets to vault-relative paths
"""

import re
from pathlib import Path

# Regex para wikilinks [[concepto]] y [[concepto|alias]]
WIKILINK_RE = re.compile(r'\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]')
# Regex para markdown links [text](path.md)
MDLINK_RE = re.compile(r'\[([^\]]*)\]\(([^)]+\.md)\)')


def extract_links(md_path, exclude_files=None):
    """Extracts all link targets (wikilinks + markdown) from a file.

    Args:
        md_path: Path to .md file.
        exclude_files: Set of filenames to exclude.

    Returns:
        list[str]: List of unique targets.
    """
    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception:
        return []

    # Quitar frontmatter y code blocks para evitar falsos positivos
    clean = text
    if clean.startswith("---"):
        end = clean.find("\n---\n", 3)
        if end != -1:
            clean = clean[end + 5:]
    clean = re.sub(r'```[\s\S]*?```', '', clean)
    clean = re.sub(r'`[^`]+`', '', clean)

    targets = set()

    # Wikilinks [[target]]
    for match in WIKILINK_RE.finditer(clean):
        target = match.group(1).strip()
        targets.add(target)

    # Markdown links [text](target.md)
    for match in MDLINK_RE.finditer(clean):
        target = match.group(2).strip()
        targets.add(target)

    return list(targets)


def resolve_link(target, vault, current_dir, name_index=None):
    """Resolves a link target to a path relative to the vault.

    Args:
        target: Link text (e.g. "[[okf-v01]]" → "okf-v01").
        vault: Path to the vault.
        current_dir: Path to the directory of the file containing the link.
        name_index: dict {filename: relpath} for global lookup (optional,
                    avoids redundant rglob).

    Returns:
        str|None: Path relative to the vault, or None if not found.
    """
    from cli.vault import EXCLUDE_FILES

    # Quitar anchor (#section)
    if "#" in target:
        target = target.split("#")[0]

    # Ruta absoluta dentro del vault (/frameworks/algo.md)
    if target.startswith("/"):
        target = target.lstrip("/")
        if not target.endswith(".md"):
            target += ".md"
        candidate = vault / target
        if candidate.exists():
            return target
        return None

    # Ruta relativa con ../ o ./
    if target.startswith("."):
        candidate = (current_dir / target).resolve()
        try:
            result = str(candidate.relative_to(vault.resolve()))
            if not result.endswith(".md"):
                result += ".md"
            return result
        except ValueError:
            return None

    # Ruta con path pero sin ./ (ej: frameworks/algo.md)
    if "/" in target:
        if not target.endswith(".md"):
            target += ".md"
        candidate = vault / target
        if candidate.exists():
            return target
        return None

    # Wikilink sin path — buscar nombre de archivo
    name = target if target.endswith(".md") else target + ".md"

    # Buscar en el mismo directorio primero
    candidate = current_dir / name
    if candidate.exists() and candidate.name not in EXCLUDE_FILES:
        return str(candidate.relative_to(vault))

    # Buscar por índice global
    if name_index and name in name_index:
        return name_index[name]

    # Fallback: búsqueda global con rglob
    for f in vault.rglob(name):
        if f.name not in EXCLUDE_FILES:
            return str(f.relative_to(vault))

    return None
