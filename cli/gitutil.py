"""Git date utilities for the OKF CLI.

Replaces the per-file ``git log -1`` subprocess pattern (which spawned
~2 subprocesses per concept — ~10s in ``health``) with a single batched
``git log`` pass that builds a {relpath: {first, last}} date index.
"""

import re
import subprocess
from datetime import datetime, timezone

_ISO_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:?\d{2}$"
)

# Caché por proceso: el CLI ejecuta un comando por proceso, y el índice
# git no cambia durante la ejecución de un comando.
_DATES_CACHE = {}


def _parse_iso(value):
    """Parses an ISO 8601 date string to an aware datetime, or None."""
    try:
        dt = datetime.fromisoformat(value.strip())
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt
    except (ValueError, TypeError):
        return None


def build_git_dates_index(vault):
    """Builds {relpath: {"first": iso, "last": iso}} from a single git log.

    One subprocess: ``git log --format=%aI --name-only`` (newest first).
    For each file, ``last`` is the date of the most recent commit that
    touched it and ``first`` the oldest.

    Args:
        vault: Path to the git repository root.

    Returns:
        dict[str, dict[str, str]] — relpath → {"first": ..., "last": ...}.
        Empty dict if the vault is not a git repo or git is unavailable.
    """
    cache_key = str(vault)
    cached = _DATES_CACHE.get(cache_key)
    if cached is not None:
        return cached

    index = {}
    try:
        result = subprocess.run(
            ["git", "-C", str(vault), "log", "--format=%aI", "--name-only"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {}
    except Exception:
        return {}

    current_date = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if _ISO_DATE_RE.match(line):
            current_date = line
            continue
        if current_date is None:
            continue
        # Línea de archivo (puede venir con prefijo de rename "old => new")
        if " => " in line and line.endswith(".md"):
            line = line.split(" => ")[-1].strip()
        if not line.endswith(".md"):
            continue
        entry = index.setdefault(line, {"first": current_date, "last": current_date})
        # git log va de más nuevo a más viejo: la primera fecha vista es la
        # última edición ("last"); las fechas siguientes son más antiguas y
        # van reescribiendo "first" hasta quedar con la creación.
        entry["first"] = current_date

    _DATES_CACHE[cache_key] = index
    return index


def first_last_for(relpath, index):
    """Returns (first_date, last_date) datetimes for a relpath, or (None, None)."""
    entry = index.get(relpath)
    if not entry:
        return None, None
    return _parse_iso(entry.get("first")), _parse_iso(entry.get("last"))
