"""Command validate — Strict pre-commit validation.

Validates that:
1. yaml.safe_load() parses the frontmatter without errors
2. Required fields (type, description, timestamp) are present and non-empty
3. Wikilinks are not wrapped in backticks (Obsidian breaks them)
4. Wikilinks are syntactically complete ([[ must have its closing ]])
5. Wikilinks with alias (|) inside tables escape the pipe with \\|
6. Wikilinks point to existing files (no broken links)

Unlike parse_frontmatter, it has NO regex fallback.
If the YAML is broken, it fails.

Usage:
    python3 -m cli validate              # validates git staged files
    python3 -m cli validate <file>       # validates a specific file
    python3 -m cli validate --all         # validates all concepts
"""

import re
import sys
from pathlib import Path
from cli.vault import find_md_files, EXCLUDE_FILES


def _extract_body(text, fm_end):
    """Extracts the file body, excluding the frontmatter.

    Args:
        text: Full file content.
        fm_end: Index where the frontmatter ends (---).

    Returns:
        str: File body.
    """
    body = text[fm_end:]
    if body.startswith("\n---"):
        body = body[4:]
    return body


def _check_wikilinks_in_backticks(body, rel):
    """Detects wikilinks wrapped in backticks in the body.

    Detected patterns:
    - `[[concept]]` — wikilink inside inline code (NOT a link in Obsidian)
    - ```[[concept]]``` inside a code block (ignored)

    Returns:
        list[str]: List of lines with backtick-wikilinks found.
    """
    errors = []

    # Remove fenced code blocks (```...```) to avoid false positives
    clean = re.sub(r'```[\s\S]*?```', '', body)

    for i, line in enumerate(clean.split("\n"), 1):
        # Only detect exact pattern: `[[...]]` or `[[...|alias]]`
        # Backtick immediately BEFORE [[ and after ]]
        if re.search(r'`\[\[[^]]+\]\](?:\[[^]]+\]\])?`', line):
            # Show fragment
            match = re.search(r'(`\[\[[^`]+\]\]`)', line)
            fragment = match.group(1) if match else "?"
            errors.append(f"  line {i}: {fragment} → must be [[...]] without backticks")

    return errors


def _check_malformed_wikilinks(body, rel):
    """Detects syntactically incomplete wikilinks in the body.

    Detected patterns:
    - [[concept — missing closing ]] on the same line
    - [[concept|alias — missing closing ]] on the same line

    Returns:
        list[str]: List of lines with malformed wikilinks.
    """
    errors = []

    # Remove fenced code blocks (```...```) and inline code (`...`) to avoid false positives
    clean = re.sub(r'```[\s\S]*?```', '', body)
    clean = re.sub(r'`[^`]+`', '', clean)

    for i, line in enumerate(clean.split("\n"), 1):
        # Find [[ that doesn't have ]] after it on the same line
        # Exclude lines that are normal markdown parts (e.g.: [[ in text)
        opens = [m.start() for m in re.finditer(r'\[\[', line)]
        closes = [m.start() for m in re.finditer(r'\]\]', line)]

        if len(opens) > len(closes):
            # More opens than closes — at least one ]] is missing
            errors.append(f"  line {i}: unclosed wikilink: {line.strip()[:80]}")

    return errors


def _check_wikilinks_in_tables(body, rel):
    """Detects wikilinks with alias (|) inside markdown table rows.

    In tables, the | of the wikilink [[target|alias]] collides with the cell
    separator, splitting the wikilink into two separate cells. The pipe must
    be escaped: [[target\\|alias]].

    Returns:
        list[str]: List of lines with conflicting wikilinks.
    """
    errors = []

    # Remove fenced code blocks
    clean = re.sub(r'```[\s\S]*?```', '', body)

    for i, line in enumerate(clean.split("\n"), 1):
        stripped = line.strip()
        # Only apply to table rows (starting with |)
        if not stripped.startswith('|'):
            continue
        # Find [[...|...]] where | is not escaped with \
        matches = re.finditer(r'\[\[([^]]*?[^\\])\|([^]]+)\]\]', stripped)
        for m in matches:
            fragment = m.group(0)
            errors.append(
                f"  line {i}: {fragment} → inside table, "
                f"escape pipe with \\| so Obsidian doesn't break the cell"
            )

    return errors


def _check_broken_wikilinks(body, rel, vault, fm=None, name_index=None):
    """Detects wikilinks pointing to nonexistent files.

    Also verifies targets in the frontmatter 'links:' field if fm
    is present.

    Args:
        body: Body content.
        rel: Relative path of the file being validated.
        vault: Path to vault root.
        fm: Parsed frontmatter (dict or None). If present and has
            'links:' field, its targets are verified.
        name_index: Shared {filename: relpath} index (built once per run).
            Avoids rebuilding it per file (O(n²) over the vault).

    Returns:
        list[str]: List of broken wikilinks found.
    """
    from cli.wikilinks import extract_links_from_text, resolve_link
    from pathlib import Path

    # Logs in sesiones/ are auto-generated records, not navigable
    # documents: their wikilinks are not validated (same policy as the
    # orphan count in the graph).
    if rel.startswith("sesiones/"):
        return []

    if name_index is None:
        from cli.vault import find_md_files
        try:
            all_files = find_md_files(vault)
            name_index = {f.name: str(f.relative_to(vault)) for f in all_files}
        except Exception:
            name_index = {}

    errors = []
    links = extract_links_from_text(body)

    if links:
        # ABSOLUTE directory of the file (resolve_link expects absolute paths
        # to resolve relative ./ ../ targets against the vault).
        current_dir = (vault / rel).parent if rel else vault
        for target in links:
            if target.startswith(('http://', 'https://', '#')):
                continue
            # Note: resolve_link(target, vault, current_dir, name_index).
            # It used to be called with (target, rel, vault) — swapped args —
            # and extract_links received the body as if it were a Path, so
            # this check never ran (always returned []).
            resolved = resolve_link(target, vault, current_dir, name_index)
            if resolved is None:
                errors.append(f"  [[{target}]] → file not found")

    # Verify targets in links: from frontmatter
    if fm and isinstance(fm.get("links"), list):
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
                    f"→ file not found"
                )

    return errors


def _check_edge_type_consistency(filepath, vault, definitions=None):
    """Detects inconsistencies in typed edges of the links: field.

    Verifies:
    - Unrecognized edge types (ERROR — blocking)
    - Mutual exclusion: same target with extiende AND refina (ERROR)
    - corrige without deprecated target nor cyber.corrected_by (ERROR)
    - Atypical pair (via validate_cross_type_pair) with semantic score
      (WARNING — informational, scoring-semantico plan: prioritized by score)

    Args:
        filepath: Path of the file to validate.
        vault: Path to vault root.
        definitions: Optional config-provided edge type definitions. If None,
                     uses the embedded defaults.

    Returns:
        tuple[list[str], list[str]]: (errors, warnings).
    """
    from cli.edge_types import VALID_EDGE_TYPES, validate_cross_type_pair, score_edge
    from cli.frontmatter import parse_frontmatter

    errors = []
    warnings = []
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return errors, warnings

    fm, _ = parse_frontmatter(text)
    if fm is None:
        return errors, warnings

    links = fm.get("links")
    if not isinstance(links, list):
        return errors, warnings

    valid_edge_types = set(definitions) if definitions else VALID_EDGE_TYPES
    rel = str(filepath.relative_to(vault))
    src_type = str(fm.get("type", ""))

    types_per_target = {}
    for link in links:
        if not isinstance(link, dict):
            continue
        target = str(link.get("target", ""))
        edge_type = str(link.get("type", ""))

        if edge_type not in valid_edge_types:
            errors.append(
                f"  links: unknown type '{edge_type}' in {rel} → {target}"
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
                        if "deprec" not in status.lower() and "superced" not in status.lower() and not has_cb:
                            errors.append(
                                f"  links: {rel} corrects '{target}' but the "
                                f"target is not deprecated (status='{status}')"
                            )
                except Exception:
                    pass

        # Atypical pair with semantic score: non-blocking WARNING.
        # Historical edges may have pairs outside valid_pairs without
        # breaking the commit; the score (0.0-1.0) prioritizes review.
        target_file = vault / target
        tgt_type = "?"
        tgt_fm = None
        try:
            t_text = target_file.read_text(encoding="utf-8")
            tgt_fm, _ = parse_frontmatter(t_text)
            if tgt_fm and tgt_fm.get("type"):
                tgt_type = str(tgt_fm["type"])
        except Exception:
            pass

        pair_warnings = validate_cross_type_pair(
            src_type, tgt_type, edge_type, definitions=definitions)
        if pair_warnings:
            src_tags = fm.get("tags", [])
            tgt_tags = tgt_fm.get("tags", []) if tgt_fm else []
            if isinstance(src_tags, str):
                src_tags = [t.strip() for t in src_tags.strip("[]").split(",") if t.strip()]
            if isinstance(tgt_tags, str):
                tgt_tags = [t.strip() for t in tgt_tags.strip("[]").split(",") if t.strip()]
            if not isinstance(src_tags, list):
                src_tags = []
            if not isinstance(tgt_tags, list):
                tgt_tags = []
            s = score_edge(
                source_type=src_type,
                target_type=tgt_type,
                edge_type=edge_type,
                source_tags=src_tags,
                target_tags=tgt_tags,
                source_desc=str(fm.get("description", "")),
                target_desc=str(tgt_fm.get("description", "")) if tgt_fm else "",
                precedent_ratio=0.0,
                definitions=definitions,
            )
            for w in pair_warnings:
                warnings.append(f"  {w} [score: {s:.2f}]")

    for target, types in types_per_target.items():
        if "extiende" in types and "refina" in types:
            errors.append(
                f"  links: mutual exclusion in {rel} → {target}: "
                f"'extiende' and 'refina' simultaneously"
            )

    return errors, warnings


def _validate_file(filepath, vault, definitions=None, name_index=None):
    """Validates the frontmatter and wikilinks of a .md file.

    Args:
        filepath: Path of the file to validate.
        vault: Path to vault root.
        definitions: Optional config-provided edge type definitions. If None,
                     uses the embedded defaults.
        name_index: Shared {filename: relpath} index (built once per run).

    Returns:
        tuple[bool, str]: (ok, error_message). ok=True if valid.
    """
    rel = str(filepath.relative_to(vault))

    # Exclude files that are not concepts
    if filepath.name in EXCLUDE_FILES or filepath.name == "Untitled.md":
        return True, ""

    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"{rel}: could not read: {e}"

    # If it doesn't start with ---, it's not a concept (loose user note)
    if not text.startswith("---"):
        return True, ""

    # Extract YAML block and body
    end = text.find("\n---\n", 3)
    if end == -1:
        end = text.find("\n---", 3)
    if end == -1:
        return False, f"{rel}: unclosed frontmatter (missing final '---')"

    fm_text = text[3:end]
    body = _extract_body(text, end)

    all_errors = []

    # ── Validation 1: strict YAML ──
    try:
        import yaml
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError as e:
        line = ""
        if hasattr(e, 'problem_mark') and e.problem_mark:
            line = f" (line {e.problem_mark.line + 1})"
        return False, f"{rel}: invalid YAML{line}: {e}"

    if fm is None:
        return False, f"{rel}: empty frontmatter"

    if not isinstance(fm, dict):
        return False, f"{rel}: frontmatter is not a valid YAML dict"

    # ── Validation 2: required fields ──
    if not fm.get("type"):
        all_errors.append("missing 'type'")
    desc = fm.get("description")
    if not desc or not str(desc).strip():
        all_errors.append("missing 'description'")
    # timestamp: obligatorio excepto en sesiones/ (auto-generadas)
    # y skills/ (skills de Hermes, no conceptos OKF)
    if not rel.startswith("sesiones/") and not rel.startswith("skills/"):
        ts = fm.get("timestamp")
        if not ts or not str(ts).strip():
            all_errors.append("missing 'timestamp'")

    # ── Validation 3: wikilinks in backticks ──
    wl_errors = _check_wikilinks_in_backticks(body, rel)
    if wl_errors:
        all_errors.append(f"wikilinks in backticks (Obsidian doesn't render them as links):\n" + "\n".join(wl_errors))

    # ── Validation 4: malformed wikilinks ──
    malformed = _check_malformed_wikilinks(body, rel)
    if malformed:
        all_errors.append(f"syntactically incomplete wikilinks (missing closing ]]):\n" + "\n".join(malformed))

    # ── Validation 5: wikilinks with alias in tables ──
    table_wl = _check_wikilinks_in_tables(body, rel)
    if table_wl:
        all_errors.append(f"wikilinks with unescaped pipe inside table:\n" + "\n".join(table_wl))

    # ── Validation 6: broken links ──
    broken = _check_broken_wikilinks(body, rel, vault, fm=fm,
                                     name_index=name_index)
    if broken:
        all_errors.append(f"wikilinks pointing to nonexistent files:\n" + "\n".join(broken))

    # ── Validation 8: apoptosis — supercedida exige replaced_by ──
    if str(fm.get("status", "")).strip().lower() == "supercedida":
        rb = fm.get("replaced_by")
        if not rb or not str(rb).strip():
            all_errors.append(
                "status: supercedida sin 'replaced_by' (protocolo de apoptosis: "
                "criterios/protocolo-de-apoptosis-muerte-de-conceptos-en-el-vault-okf)")

    # ── Validation 7: typed edge consistency ──
    edge_errors, edge_warnings = _check_edge_type_consistency(
        filepath, vault, definitions=definitions)
    if edge_errors:
        all_errors.append(f"inconsistencies in typed links:\n" + "\n".join(edge_errors))
    if edge_warnings:
        # Non-blocking warnings (semantic-scoring plan: atypical pair
        # prioritized by score) — reported to stderr without aborting.
        print(f"⚠️  {rel}:", file=sys.stderr)
        for w in edge_warnings:
            print(w, file=sys.stderr)

    if all_errors:
        return False, f"{rel}: " + "; ".join(all_errors)

    return True, ""


def _check_superseded_corrige(vault):
    """Validation 9 (grafo): toda entidad con status: supercedida debe tener
    una arista tipada 'corrige' entrante declarada por su reemplazo.

    Implementa la memoria de errores tipada del grafo (P1-2 del backlog de
    instrumentación ontológica): el protocolo de apoptosis marca la muerte con
    replaced_by (wikilink), y la arista corrige la hace machine-readable para
    graph_impact/analytics. El reemplazo declara:
        links:
          - target: <predecesor.md>
            type: corrige
    """
    import yaml
    errors = []
    superseded: list[str] = []
    corrige_targets: set[str] = set()
    for f in find_md_files(vault):
        if f.name in EXCLUDE_FILES or f.name == "Untitled.md":
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if not text.startswith("---"):
            continue
        end = text.find("\n---\n", 3)
        if end == -1:
            end = text.find("\n---", 3)
        if end == -1:
            continue
        rel = str(f.relative_to(vault))
        try:
            fm = yaml.safe_load(text[3:end])
        except Exception:
            continue
        if not isinstance(fm, dict):
            continue
        if str(fm.get("status", "")).strip().lower() == "supercedida":
            superseded.append(rel)
        links = fm.get("links") or []
        if not isinstance(links, list):
            continue
        for link in links:
            if isinstance(link, dict) and link.get("type") == "corrige":
                t = str(link.get("target", "")).strip()
                if t and not t.endswith(".md"):
                    t += ".md"
                corrige_targets.add(t)
    for rel in superseded:
        if rel not in corrige_targets:
            errors.append(
                f"{rel}: status supercedida sin arista 'corrige' entrante "
                "(el reemplazo debe declarar links: [{target: <este>, type: corrige}])")
    return errors


def run(args, vault, config=None):
    """Runs frontmatter validation."""
    target = getattr(args, "target", None)
    validate_all = getattr(args, "all", False)

    if not vault.exists():
        print(f"Error: vault not found at {vault}", file=sys.stderr)
        return 1

    # Determine which files to validate
    if target:
        # Specific file
        filepath = vault / target
        if not filepath.exists():
            # Search by name
            for f in vault.rglob("*.md"):
                if f.name == target or target in str(f.relative_to(vault)):
                    filepath = f
                    break
        if not filepath.exists():
            print(f"✗ Not found: {target}", file=sys.stderr)
            return 1
        files = [filepath]
    elif validate_all:
        files = find_md_files(vault)
    else:
        # Default: .md files staged in git
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
            print("✓ No .md files staged for validation.")
            return 0

    # Validate
    definitions = config.edge_type_definitions() if config else None
    # Shared index: built ONCE (previously _check_broken_wikilinks rebuilt
    # it per file with links: → O(n²) over the vault).
    name_index = {f.name: str(f.relative_to(vault)) for f in find_md_files(vault)}
    ok_count = 0
    errors = []

    for f in files:
        if not f.exists():
            continue
        is_ok, msg = _validate_file(f, vault, definitions=definitions,
                                    name_index=name_index)
        if is_ok:
            ok_count += 1
        else:
            errors.append(msg)

    # ── Validation 9 (grafo): supercedidas exigen arista corrige entrante ──
    errors.extend(_check_superseded_corrige(vault))

    # Reporte
    if errors:
        print(f"❌ {len(errors)} file(s) with errors:", file=sys.stderr)
        for e in errors:
            print(f"   {e}", file=sys.stderr)
        print(f"\n✅ {ok_count} valid, ❌ {len(errors)} invalid",
              file=sys.stderr)
        print("\nCommit aborted. Fix the errors and try again.",
              file=sys.stderr)
        return 1

    print(f"✅ {ok_count} file(s) valid.")
    return 0
