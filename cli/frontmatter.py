"""Parseo de frontmatter YAML.

Responsabilidades:
- Extraer y parsear el bloque YAML del frontmatter de un archivo .md
- Validar campos requeridos (type, description)
- Extraer tags normalizadas
- Incrementar contador reads
- Normalizar tags string↔lista

Campos reconocidos (OKF v0.1):
  type (requerido), description (requerido), title, tags, timestamp,
  resource, status, reads, leaf, cyber, okf_version
"""

import re
from pathlib import Path


def parse_frontmatter(text):
    """Extrae y parsea frontmatter YAML. Intenta PyYAML, fallback a regex.

    Args:
        text: Contenido completo del archivo .md.

    Returns:
        tuple[dict|None, str|None]: (fields_dict, raw_fm_text)
        - fields_dict: dict con los campos parseados, o None si no hay frontmatter.
        - raw_fm_text: texto crudo del frontmatter (sin delimitadores), o None.
    """
    if not text.startswith("---"):
        return None, None

    end = text.find("\n---\n", 3)
    if end == -1:
        end = text.find("\n---", 3)
    if end == -1:
        return None, None

    fm_text = text[3:end]

    # Intentar PyYAML primero (más preciso)
    try:
        import yaml
        fm = yaml.safe_load(fm_text)
        if isinstance(fm, dict):
            # Filtrar claves espurias
            fm = {
                k: v for k, v in fm.items()
                if k and not str(k).startswith("#") and not str(k).startswith("- ")
            }
            return fm, fm_text
    except Exception:
        pass

    # Fallback: parser manual con regex
    fm = {}
    for line in fm_text.split("\n"):
        m = re.match(r'^(\w[\w-]*):\s*(.*)', line)
        if m:
            key = m.group(1)
            val = m.group(2).strip().strip('"').strip("'")
            fm[key] = val

    return fm if fm else None, fm_text


def validate_frontmatter(fields):
    """Valida que el frontmatter tenga los campos requeridos.

    Args:
        fields: dict del frontmatter parseado.

    Returns:
        list[str]: Lista de errores (vacía = todo ok).
    """
    errors = []
    if not fields:
        return ["sin frontmatter o YAML inválido"]

    if not fields.get("type"):
        errors.append("falta 'type' (OKF requerido)")

    desc = fields.get("description")
    if not desc or not str(desc).strip():
        errors.append("falta 'description' (política del vault)")
    elif isinstance(desc, str) and len(desc) > 2000:
        errors.append(f"description excede 2000 chars ({len(desc)}) — probable corrupción")

    return errors


def extract_tags(md_path):
    """Extrae tags del frontmatter de un archivo. Sin dependencia de PyYAML.

    Args:
        md_path: Path al archivo .md.

    Returns:
        list[str]: Lista de tags normalizada.
    """
    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception:
        return []

    if not text.startswith("---"):
        return []

    end = text.find("\n---\n", 3)
    if end == -1:
        return []
    fm_text = text[3:end]

    tags = []
    # Formato inline: tags: [tag1, tag2]
    m = re.search(r'^tags:\s*\[([^\]]+)\]', fm_text, re.MULTILINE)
    if m:
        tags = [t.strip().strip('"').strip("'") for t in m.group(1).split(",")]
    else:
        # Formato multilínea: tags:\n  - tag1\n  - tag2
        in_tags = False
        for line in fm_text.split("\n"):
            if re.match(r'^tags:', line):
                in_tags = True
                continue
            if in_tags:
                m2 = re.match(r'\s*-\s+(.+)', line)
                if m2:
                    tags.append(m2.group(1).strip().strip('"').strip("'"))
                elif line.strip() and not line.startswith(" "):
                    break
    return [t for t in tags if t]


def normalize_tags(tags_value):
    """Convierte cualquier representación de tags a lista de strings.

    Args:
        tags_value: Puede ser str ("tag1, tag2"), list, o None.

    Returns:
        list[str]
    """
    if tags_value is None:
        return []
    if isinstance(tags_value, list):
        return [str(t).strip() for t in tags_value if t]
    if isinstance(tags_value, str):
        # Puede ser formato "[a, b]" o "a, b"
        s = tags_value.strip()
        if s.startswith("[") and s.endswith("]"):
            s = s[1:-1]
        return [t.strip() for t in s.split(",") if t.strip()]
    return []


def increment_reads(filepath):
    """Incrementa o crea el campo reads en el frontmatter de un archivo.

    Args:
        filepath: Path al archivo .md.

    Returns:
        int: Nuevo valor del contador (0 si falló).
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return 0

    if not content.startswith("---"):
        return 0

    end = content.find("\n---\n", 3)
    if end == -1:
        end = content.find("\n---", 3)
    if end == -1:
        return 0

    fm = content[3:end]
    after_fm = content[end:]

    reads_match = re.search(r'^reads:\s*(\d+)', fm, re.MULTILINE)
    if reads_match:
        current = int(reads_match.group(1))
        new_val = current + 1
        fm = re.sub(r'^reads:\s*\d+', f'reads: {new_val}', fm, flags=re.MULTILINE)
    else:
        new_val = 1
        # Insertar después de description si existe
        if 'description:' in fm:
            fm = re.sub(r'(description:.*\n)', r'\1reads: 1\n', fm, count=1)
        else:
            fm = fm.rstrip() + "\nreads: 1"

    new_content = f"---\n{fm}{after_fm}"
    filepath.write_text(new_content, encoding="utf-8")
    return new_val


def extract_typed_links(md_path):
    """Extrae aristas tipadas del campo 'links:' en el frontmatter.

    Args:
        md_path: Path al archivo .md.

    Returns:
        list[dict]: Lista de {"target": str, "type": str}.
        Lista vacía si no hay campo 'links:' o el frontmatter está mal formado.
    """
    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception:
        return []

    fm, _ = parse_frontmatter(text)
    if fm is None:
        return []

    links = fm.get("links")
    if not isinstance(links, list):
        return []

    result = []
    for item in links:
        if isinstance(item, dict) and "target" in item and "type" in item:
            result.append({
                "target": str(item["target"]),
                "type": str(item["type"]),
            })
    return result


def validate_cross_type(source_type, source_path, links, vault, graph):
    """Validación cross-type no bloqueante para aristas tipadas.

    Verifica que los pares (type_origen, type_destino, edge_type) sean
    semánticamente válidos según EDGE_TYPE_DEFINITIONS. También detecta
    exclusión mutua (extiende + refina mismo target) y corrige sin target
    deprecado.

    Args:
        source_type: Type del nodo origen (str).
        source_path: Path relativo del nodo origen (str).
        links: Lista de dicts {"target": str, "type": str}.
        vault: Path al vault root.
        graph: Grafo construido con build_graph().

    Returns:
        list[str]: Lista de warnings (vacía = todo OK).
    """
    from cli.edge_types import validate_cross_type_pair, EDGE_TYPE_DEFINITIONS

    warnings = []

    for link in links:
        target_path = link["target"]
        edge_type = link["type"]

        # Obtener type del destino desde el frontmatter
        target_file = vault / target_path
        target_type = "?"
        if target_file.exists():
            try:
                text = target_file.read_text(encoding="utf-8")
                fm, _ = parse_frontmatter(text)
                if fm and fm.get("type"):
                    target_type = str(fm["type"])
            except Exception:
                pass

        # Validar par cross-type
        pair_warnings = validate_cross_type_pair(
            source_type, target_type, edge_type
        )
        for w in pair_warnings:
            warnings.append(
                f"links: {source_path} → {target_path}: {w}"
            )

        # Exclusión mutua: mismo target con extiende Y refina
        other_types = {
            l["type"] for l in links
            if l["target"] == target_path and l["type"] != edge_type
        }
        if edge_type == "extiende" and "refina" in other_types:
            warnings.append(
                f"links: {source_path} → {target_path}: exclusión mutua — "
                f"'extiende' y 'refina' en el mismo par"
            )
        if edge_type == "refina" and "extiende" in other_types:
            warnings.append(
                f"links: {source_path} → {target_path}: exclusión mutua — "
                f"'extiende' y 'refina' en el mismo par"
            )

        # corrige sin target deprecado ni corrected_by
        if edge_type == "corrige" and target_file.exists():
            try:
                text = target_file.read_text(encoding="utf-8")
                fm, _ = parse_frontmatter(text)
                if fm:
                    status = str(fm.get("status", ""))
                    cyber = fm.get("cyber")
                    has_corrected_by = (
                        isinstance(cyber, dict)
                        and bool(cyber.get("corrected_by"))
                    )
                    if "deprec" not in status.lower() and not has_corrected_by:
                        warnings.append(
                            f"links: {source_path} corrige a '{target_path}' "
                            f"pero el target no está marcado como deprecado "
                            f"ni tiene cyber.corrected_by."
                        )
            except Exception:
                pass

    return warnings
