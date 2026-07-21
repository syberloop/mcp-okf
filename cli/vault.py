"""Resolución de ruta del vault y descubrimiento de archivos.

Responsabilidades:
- Determinar la ubicación del vault (CLI arg > $OKF_VAULT > ~/OKF-Vault)
- Encontrar archivos .md del vault con exclusiones configuradas
- Construir índice nombre→ruta para resolución de wikilinks
"""

import os
from pathlib import Path

# Constantes unificadas — defaults embebidos (pisan por Config si existe .okf.config.yaml)
DEFAULT_EXCLUDE_FILES = {"index.md", "log.md", "dashboard.md", "AGENTS.md"}
DEFAULT_EXCLUDE_DIRS = {".git", ".obsidian", "Templates", "scripts", "references", "assets"}

# Referencia mutable: los comandos que instancian Config las pisan.
# Se mantienen para backward compat con código que no recibe Config aún.
EXCLUDE_FILES = DEFAULT_EXCLUDE_FILES.copy()
EXCLUDE_DIRS = DEFAULT_EXCLUDE_DIRS.copy()


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


def _get_excludes(config=None):
    """Obtiene exclusiones desde Config o usa las variables globales de módulo."""
    if config is not None:
        return config.exclude_files, config.exclude_dirs
    return EXCLUDE_FILES, EXCLUDE_DIRS


def apply_config(config):
    """Aplica exclusiones desde un objeto Config a las variables globales del módulo.

    Llamar una vez al inicio, después de instanciar Config.
    Mantiene backward compat con código que importa EXCLUDE_FILES/EXCLUDE_DIRS directamente.
    """
    global EXCLUDE_FILES, EXCLUDE_DIRS
    EXCLUDE_FILES = config.exclude_files
    EXCLUDE_DIRS = config.exclude_dirs


def find_md_files(vault, exclude_files=None, exclude_dirs=None, config=None):
    """Encuentra todos los archivos .md del vault que son conceptos.

    Args:
        vault: Path al vault.
        exclude_files: Set de nombres de archivo a excluir (deprecado: usar config).
        exclude_dirs: Set de nombres de directorio a excluir (deprecado: usar config).
        config: Objeto Config (preferido sobre exclude_files/dirs explícitos).

    Returns:
        Lista de Paths absolutos, ordenada.
    """
    if exclude_files is None and exclude_dirs is None:
        exclude_files, exclude_dirs = _get_excludes(config)
    elif exclude_files is None:
        exclude_files = EXCLUDE_FILES
    elif exclude_dirs is None:
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


def build_name_index(vault, config=None):
    """Construye índice filename → relpath para búsqueda global de wikilinks.

    Args:
        vault: Path al vault.
        config: Objeto Config (opcional).

    Returns:
        dict[str, str] — {filename: relpath}
    """
    all_files = find_md_files(vault, config=config)
    return {f.name: str(f.relative_to(vault)) for f in all_files}
