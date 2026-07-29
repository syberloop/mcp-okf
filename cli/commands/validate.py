"""Comando validate — Validación estricta pre-commit.

Valida que:
1. yaml.safe_load() parsea el frontmatter sin errores
2. Campos obligatorios (type, description, timestamp) presentes y no vacíos
3. Wikilinks no están envueltos en backticks (Obsidian los rompe)
4. Wikilinks están sintácticamente completos ([[ debe tener su cierre ]])
5. Wikilinks con alias (|) dentro de tablas escapan la pipe con \|
6. Wikilinks apuntan a archivos que existen (no links rotos)

A diferencia de parse_frontmatter, NO tiene fallback de regex.
Si el YAML está roto, falla.

Uso:
    python3 -m cli validate              # valida archivos staged en git
    python3 -m cli validate <archivo>    # valida un archivo específico
    python3 -m cli validate --all         # valida todos los conceptos
"""

import re
import sys
from pathlib import Path
from cli.vault import find_md_files, EXCLUDE_FILES


def _extract_body(text, fm_end):
    """Extrae el body del archivo, excluyendo el frontmatter.

    Args:
        text: Contenido completo del archivo.
        fm_end: Índice donde termina el frontmatter (---).

    Returns:
        str: Body del archivo.
    """
    body = text[fm_end:]
    if body.startswith("\n---"):
        body = body[4:]
    return body


def _check_wikilinks_in_backticks(body, rel):
    """Detecta wikilinks envueltos en backticks en el body.

    Patrones detectados:
    - `[[concepto]]` — wikilink dentro de código inline (NO es un enlace en Obsidian)
    - ```[[concepto]]``` dentro de bloque de código (ignorado)

    Returns:
        list[str]: Lista de líneas con backtick-wikilinks encontrados.
    """
    errors = []

    # Eliminar bloques de código fenced (```...```) para evitar falsos positivos
    clean = re.sub(r'```[\s\S]*?```', '', body)

    for i, line in enumerate(clean.split("\n"), 1):
        # Solo detectar patrón exacto: `[[...]]` o `[[...|alias]]`
        # Backtick inmediatamente ANTES de [[ y después de ]]
        if re.search(r'`\[\[[^]]+\]\](?:\[[^]]+\]\])?`', line):
            # Mostrar fragmento
            match = re.search(r'(`\[\[[^`]+\]\]`)', line)
            fragment = match.group(1) if match else "?"
            errors.append(f"  línea {i}: {fragment} → debe ser [[...]] sin backticks")

    return errors


def _check_malformed_wikilinks(body, rel):
    """Detecta wikilinks sintácticamente incompletos en el body.

    Patrones detectados:
    - [[concepto — sin cierre ]] en la misma línea
    - [[concepto|alias — sin cierre ]] en la misma línea

    Returns:
        list[str]: Lista de líneas con wikilinks malformados.
    """
    errors = []

    # Eliminar bloques de código fenced (```...```) e inline code (`...`) para evitar falsos positivos
    clean = re.sub(r'```[\s\S]*?```', '', body)
    clean = re.sub(r'`[^`]+`', '', clean)

    for i, line in enumerate(clean.split("\n"), 1):
        # Buscar [[ que no tenga ]] después en la misma línea
        # Excluir líneas que son parte normal de markdown (ej: [[ en texto)
        opens = [m.start() for m in re.finditer(r'\[\[', line)]
        closes = [m.start() for m in re.finditer(r'\]\]', line)]

        if len(opens) > len(closes):
            # Hay más aperturas que cierres — falta al menos un ]]
            errors.append(f"  línea {i}: wikilink sin cerrar: {line.strip()[:80]}")

    return errors


def _check_wikilinks_in_tables(body, rel):
    """Detecta wikilinks con alias (|) dentro de filas de tabla markdown.

    En tablas, el | del wikilink [[target|alias]] colisiona con el separador
    de celda, partiendo el wikilink en dos celdas separadas. La pipe debe
    escaparse: [[target\\|alias]].

    Returns:
        list[str]: Lista de líneas con wikilinks conflictivos.
    """
    errors = []

    # Eliminar bloques de código fenced
    clean = re.sub(r'```[\s\S]*?```', '', body)

    for i, line in enumerate(clean.split("\n"), 1):
        stripped = line.strip()
        # Solo aplicar a filas de tabla (empiezan por |)
        if not stripped.startswith('|'):
            continue
        # Buscar [[...|...]] donde | no está escapado con \
        matches = re.finditer(r'\[\[([^]]*?[^\\])\|([^]]+)\]\]', stripped)
        for m in matches:
            fragment = m.group(0)
            errors.append(
                f"  línea {i}: {fragment} → dentro de tabla, "
                f"escapar pipe con \\| para que Obsidian no rompa la celda"
            )

    return errors


def _check_broken_wikilinks(body, rel, vault, fm=None):
    """Detecta wikilinks que apuntan a archivos inexistentes.

    También verifica targets en el campo 'links:' del frontmatter si fm
    está presente.

    Args:
        body: Contenido del body.
        rel: Ruta relativa del archivo siendo validado.
        vault: Path al vault root.
        fm: Frontmatter parseado (dict o None). Si está presente y tiene
            campo 'links:', se verifican sus targets.

    Returns:
        list[str]: Lista de wikilinks rotos encontrados.
    """
    from cli.wikilinks import extract_links, resolve_link

    errors = []
    links = extract_links(body)

    if links:
        for target in links:
            if target.startswith(('http://', 'https://', '#')):
                continue
            resolved = resolve_link(target, rel, vault)
            if resolved is None:
                errors.append(f"  [[{target}]] → archivo no encontrado")

    # Verificar targets en links: del frontmatter
    if fm and isinstance(fm.get("links"), list):
        name_index = {}
        try:
            from cli.vault import find_md_files
            all_files = find_md_files(vault)
            name_index = {f.name: str(f.relative_to(vault)) for f in all_files}
        except Exception:
            pass

        for link in fm["links"]:
            if not isinstance(link, dict):
                continue
            target = str(link.get("target", ""))
            if not target:
                continue
            if target.startswith(('http://', 'https://', '#')):
                continue

            # Try to resolve
            target_file = vault / target
            resolved = None
            if target_file.exists():
                resolved = str(target_file.relative_to(vault))
            elif name_index:
                try_target = target if target.endswith(".md") else target + ".md"
                if try_target in name_index:
                    resolved = name_index[try_target]
                else:
                    for name, rp in name_index.items():
                        if try_target in rp:
                            resolved = rp
                            break

            if resolved is None:
                edge_type = link.get("type", "?")
                errors.append(
                    f"  links: target='{target}' type='{edge_type}' "
                    f"→ archivo no encontrado"
                )

    return errors


def _check_edge_type_consistency(filepath, vault):
    """Detecta inconsistencias en aristas tipadas del campo links:.

    Verifica:
    - Edge types no reconocidos
    - Exclusión mutua: mismo target con extiende Y refina
    - corrige sin target deprecado ni cyber.corrected_by

    Returns:
        list[str]: Lista de errores encontrados.
    """
    from cli.edge_types import VALID_EDGE_TYPES
    from cli.frontmatter import parse_frontmatter

    errors = []
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return errors

    fm, _ = parse_frontmatter(text)
    if fm is None:
        return errors

    links = fm.get("links")
    if not isinstance(links, list):
        return errors

    rel = str(filepath.relative_to(vault))

    types_per_target = {}
    for link in links:
        if not isinstance(link, dict):
            continue
        target = str(link.get("target", ""))
        edge_type = str(link.get("type", ""))

        if edge_type not in VALID_EDGE_TYPES:
            errors.append(
                f"  links: tipo desconocido '{edge_type}' en {rel} → {target}"
            )
            continue

        if target not in types_per_target:
            types_per_target[target] = set()
        types_per_target[target].add(edge_type)

        if edge_type == "corrige":
            target_file = vault / target
            if target_file.exists():
                try:
                    t_text = target_file.read_text(encoding="utf-8")
                    t_fm, _ = parse_frontmatter(t_text)
                    if t_fm:
                        status = str(t_fm.get("status", ""))
                        cyber = t_fm.get("cyber")
                        has_cb = (
                            isinstance(cyber, dict)
                            and bool(cyber.get("corrected_by"))
                        )
                        if "deprec" not in status.lower() and not has_cb:
                            errors.append(
                                f"  links: {rel} corrige a '{target}' pero el "
                                f"target no está deprecado (status='{status}')"
                            )
                except Exception:
                    pass

    for target, types in types_per_target.items():
        if "extiende" in types and "refina" in types:
            errors.append(
                f"  links: exclusión mutua en {rel} → {target}: "
                f"'extiende' y 'refina' simultáneos"
            )

    return errors


def _validate_file(filepath, vault):
    """Valida el frontmatter y wikilinks de un archivo .md.

    Returns:
        tuple[bool, str]: (ok, mensaje_error). ok=True si válido.
    """
    rel = str(filepath.relative_to(vault))

    # Excluir archivos que no son conceptos
    if filepath.name in EXCLUDE_FILES or filepath.name == "Untitled.md":
        return True, ""

    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"{rel}: no se pudo leer: {e}"

    # Si no empieza con ---, no es un concepto (nota suelta del usuario)
    if not text.startswith("---"):
        return True, ""

    # Extraer bloque YAML y body
    end = text.find("\n---\n", 3)
    if end == -1:
        end = text.find("\n---", 3)
    if end == -1:
        return False, f"{rel}: frontmatter sin cerrar (falta '---' final)"

    fm_text = text[3:end]
    body = _extract_body(text, end)

    all_errors = []

    # ── Validación 1: YAML estricto ──
    try:
        import yaml
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError as e:
        line = ""
        if hasattr(e, 'problem_mark') and e.problem_mark:
            line = f" (línea {e.problem_mark.line + 1})"
        return False, f"{rel}: YAML inválido{line}: {e}"

    if fm is None:
        return False, f"{rel}: frontmatter vacío"

    if not isinstance(fm, dict):
        return False, f"{rel}: frontmatter no es un dict YAML válido"

    # ── Validación 2: Campos obligatorios ──
    if not fm.get("type"):
        all_errors.append("falta 'type'")
    desc = fm.get("description")
    if not desc or not str(desc).strip():
        all_errors.append("falta 'description'")
    # timestamp: obligatorio excepto en sesiones/ (auto-generadas)
    # y skills/ (skills de Hermes, no conceptos OKF)
    if not rel.startswith("sesiones/") and not rel.startswith("skills/"):
        ts = fm.get("timestamp")
        if not ts or not str(ts).strip():
            all_errors.append("falta 'timestamp'")

    # ── Validación 3: Wikilinks en backticks ──
    wl_errors = _check_wikilinks_in_backticks(body, rel)
    if wl_errors:
        all_errors.append(f"wikilinks en backticks (Obsidian no los muestra como enlaces):\n" + "\n".join(wl_errors))

    # ── Validación 4: Wikilinks malformados ──
    malformed = _check_malformed_wikilinks(body, rel)
    if malformed:
        all_errors.append(f"wikilinks sintácticamente incompletos (falta ]] de cierre):\n" + "\n".join(malformed))

    # ── Validación 5: Wikilinks con alias en tablas ──
    table_wl = _check_wikilinks_in_tables(body, rel)
    if table_wl:
        all_errors.append(f"wikilinks con pipe sin escapar dentro de tabla:\n" + "\n".join(table_wl))

    # ── Validación 6: Links rotos ──
    broken = _check_broken_wikilinks(body, rel, vault, fm=fm)
    if broken:
        all_errors.append(f"wikilinks apuntan a archivos inexistentes:\n" + "\n".join(broken))

    # ── Validación 7: Consistencia de aristas tipadas ──
    edge_errors = _check_edge_type_consistency(filepath, vault)
    if edge_errors:
        all_errors.append(f"inconsistencias en links tipados:\n" + "\n".join(edge_errors))

    if all_errors:
        return False, f"{rel}: " + "; ".join(all_errors)

    return True, ""


def run(args, vault, config=None):
    """Ejecuta validación de frontmatter."""
    target = getattr(args, "target", None)
    validate_all = getattr(args, "all", False)

    if not vault.exists():
        print(f"Error: vault no encontrado en {vault}", file=sys.stderr)
        return 1

    # Determinar qué archivos validar
    if target:
        # Archivo específico
        filepath = vault / target
        if not filepath.exists():
            # Buscar por nombre
            for f in vault.rglob("*.md"):
                if f.name == target or target in str(f.relative_to(vault)):
                    filepath = f
                    break
        if not filepath.exists():
            print(f"✗ No encontrado: {target}", file=sys.stderr)
            return 1
        files = [filepath]
    elif validate_all:
        files = find_md_files(vault)
    else:
        # Por defecto: archivos .md staged en git
        import subprocess
        result = subprocess.run(
            ["git", "-C", str(vault), "diff", "--cached", "--name-only",
             "--diff-filter=ACMR", "*.md"],
            capture_output=True, text=True, timeout=10,
        )
        staged = [f.strip() for f in result.stdout.split("\n") if f.strip()]
        files = [vault / f for f in staged
                 if not f.endswith(("index.md", "log.md", "dashboard.md"))]
        if not files:
            print("✓ No hay archivos .md staged para validar.")
            return 0

    # Validar
    ok_count = 0
    errors = []

    for f in files:
        if not f.exists():
            continue
        is_ok, msg = _validate_file(f, vault)
        if is_ok:
            ok_count += 1
        else:
            errors.append(msg)

    # Reporte
    if errors:
        print(f"❌ {len(errors)} archivo(s) con errores:", file=sys.stderr)
        for e in errors:
            print(f"   {e}", file=sys.stderr)
        print(f"\n✅ {ok_count} válido(s), ❌ {len(errors)} inválido(s)",
              file=sys.stderr)
        print("\nCommit abortado. Corrige los errores e intenta de nuevo.",
              file=sys.stderr)
        return 1

    print(f"✅ {ok_count} archivo(s) válido(s).")
    return 0
