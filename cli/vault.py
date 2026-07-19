"""Resolución de ruta del vault y descubrimiento de archivos.

Responsabilidades:
- Determinar la ubicación del vault (CLI arg > $OKF_VAULT > ~/OKF-Vault)
- Encontrar archivos .md del vault con exclusiones consistentes
- Construir índice nombre→ruta para resolución de wikilinks
"""

import os
from pathlib import Path

# Constantes unificadas — la unión de todas las exclusiones de los 10 scripts
EXCLUDE_FILES = {"index.md", "log.md", "dashboard.md", "CLAUDE.md"}
EXCLUDE_DIRS = {".git", ".obsidian", "Templates", "scripts", "references", "assets"}


def resolve_vault_path(cli_arg=None):
    """Determina la ruta del vault.

    Prioridad:
        1. Argumento explícito pasado por CLI (Path o str)
        2. Variable de entorno OKF_VAULT
        3. ~/OKF-Vault (default)

    Returns:
        Path absoluto al vault.
    """
    if cli_arg is not None:
        path = Path(cli_arg)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()

    env = os.environ.get("OKF_VAULT")
    if env:
        return Path(env).expanduser().resolve()

    return (Path.home() / "OKF-Vault").resolve()


def find_md_files(vault, exclude_files=None, exclude_dirs=None):
    """Encuentra todos los archivos .md del vault que son conceptos.

    Args:
        vault: Path al vault.
        exclude_files: Set de nombres de archivo a excluir.
        exclude_dirs: Set de nombres de directorio a excluir.

    Returns:
        Lista de Paths absolutos, ordenada.
    """
    if exclude_files is None:
        exclude_files = EXCLUDE_FILES
    if exclude_dirs is None:
        exclude_dirs = EXCLUDE_DIRS

    files = []
    for md_file in sorted(vault.rglob("*.md")):
        if md_file.name in exclude_files:
            continue
        parts = md_file.relative_to(vault).parts
        if any(p in exclude_dirs for p in parts):
            continue
        files.append(md_file)
    return files


def build_name_index(vault):
    """Construye índice filename → relpath para búsqueda global de wikilinks.

    Args:
        vault: Path al vault.

    Returns:
        dict[str, str] — {filename: relpath}
    """
    all_files = find_md_files(vault)
    return {f.name: str(f.relative_to(vault)) for f in all_files}
