"""Comando health — Verificación completa de integridad del vault OKF.

8 chequeos:
    1. Frontmatter válido (type + description)
    2. Índices sincronizados
    3. Grafo conectado (huérfanos, densidad, tags)
    4. Links rotos (wikilinks + markdown)
    5. Scripts funcionales (smoke test via subprocess)
    6. Git hook presente
    7. Bloque cyber: válido
    8. Sincronización plugin↔spec (plugin_hash vs HEAD del repo)
"""

import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from cli.vault import find_md_files, build_name_index
from cli.frontmatter import parse_frontmatter, extract_tags

EXCLUDED_CYBER_TYPES = {"MarcoTeorico", "LeccionAprendida", "Tool", "Spec"}


# ── Check 1: Frontmatter ──

def _check_frontmatter(vault):
    all_files = find_md_files(vault)
    ok, bad, warnings = 0, [], []

    for f in all_files:
        rel = str(f.relative_to(vault))
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            bad.append(f"{rel}: no se pudo leer")
            continue

        fm, _ = parse_frontmatter(text)
        if fm is None:
            bad.append(f"{rel}: sin frontmatter o YAML inválido")
            continue

        if not fm.get("type"):
            bad.append(f"{rel}: falta 'type' (OKF requerido)")
            continue

        desc = fm.get("description")
        if not desc or not str(desc).strip():
            bad.append(f"{rel}: falta 'description' (política del vault)")
            continue

        desc_str = str(desc).strip()
        if len(desc_str) < 15:
            warnings.append(f"{rel}: description muy corta ({len(desc_str)} chars)")

        ok += 1

    return ok, bad, warnings


# ── Check 2: Índices ──

def _check_indices(vault):
    ok, stale = 0, []

    for idx_file in sorted(vault.rglob("index.md")):
        parent = idx_file.parent
        rel_dir = str(parent.relative_to(vault)) if parent != vault else "raíz"

        from cli.vault import EXCLUDE_FILES as _EXCL
        real_files = {f.name for f in parent.glob("*.md")
                      if f.name not in _EXCL}
        real_dirs = {d.name for d in parent.iterdir()
                     if d.is_dir() and (d / "index.md").exists()
                     and d.name not in (".git", ".obsidian", "Templates", "scripts",
                                        "references", "assets")}

        try:
            text = idx_file.read_text(encoding="utf-8")
        except Exception:
            stale.append(f"{rel_dir}/index.md: no se pudo leer")
            continue

        if not real_files and not real_dirs:
            body = text
            if body.startswith("---"):
                end = body.find("\n---\n", 3)
                if end != -1:
                    body = body[end + 5:]
            body = body.strip()
            if len(body) > 150:
                stale.append(f"{rel_dir}/index.md: sin archivos pero contenido sustancial "
                             f"({len(body)} chars) — ¿debería ser un concepto?")
            continue

        listed_files = set(re.findall(r'\[([^\]]+)\]\(([^)]+\.md)\)', text))
        listed_files = {m[1] for m in listed_files if not m[1].endswith("/index.md")}
        listed_dirs = {m[1].rstrip("/") for m in re.findall(r'\[([^\]]+)\]\(([^)]+/)\)', text)}
        for m in re.finditer(r'\[([^\]]+)\]\(([^)]+/index\.md)\)', text):
            listed_dirs.add(m.group(2).replace("/index.md", ""))

        phantom = listed_files - real_files
        missing_files = real_files - listed_files
        missing_dirs = real_dirs - listed_dirs

        issues = []
        if phantom:
            issues.append(f"lista archivos inexistentes: {', '.join(sorted(phantom))}")
        if missing_files:
            issues.append(f"no lista archivos: {', '.join(sorted(missing_files))}")
        if missing_dirs:
            issues.append(f"no lista subdirectorios: {', '.join(sorted(missing_dirs))}")

        if issues:
            stale.append(f"{rel_dir}/index.md: {'; '.join(issues)}")
        else:
            ok += 1

    return ok, stale


# ── Check 3: Grafo ──

def _check_graph(vault):
    """Salud del grafo via cli.commands.graph (import directo, no subprocess)."""
    try:
        from cli.commands.graph import build_graph, build_tag_index
        graph = build_graph(vault)
        tag_index = build_tag_index(vault)

        # Construir set de nodos leaf — se excluyen del conteo de huérfanos
        leaf_nodes = set()
        for f in find_md_files(vault):
            try:
                text = f.read_text(encoding="utf-8")
                fm, _ = parse_frontmatter(text)
                if fm and fm.get("leaf") is True:
                    leaf_nodes.add(str(f.relative_to(vault)))
            except Exception:
                pass

        nodes = len(graph)
        edges = sum(len(d["out"]) for d in graph.values())
        orphans = sum(1 for n, d in graph.items()
                      if not d["in"] and not d["out"]
                      and n not in leaf_nodes)
        density = edges / max(nodes * (nodes - 1), 1)

        total_tags = len(tag_index)
        shared_tags = sum(1 for files in tag_index.values() if len(files) >= 2)

        warnings = []
        if orphans > 0:
            warnings.append(f"{orphans} concepto(s) huérfano(s)")
        if density < 0.05:
            warnings.append(f"densidad baja ({density:.3f})")

        return {
            "nodes": nodes, "edges": edges, "orphans": orphans, "density": density,
            "tags": {"total": total_tags, "shared": shared_tags},
        }, warnings
    except Exception as e:
        return None, [f"análisis de grafo falló: {e}"]


# ── Check 4: Links rotos ──

def _resolve_simple(target, vault, current_dir, name_index):
    """Resolución de links (misma lógica que wikilinks.resolve_link)."""
    if "#" in target:
        target = target.split("#")[0]
    if target.startswith("/"):
        target = target.lstrip("/")
        if not target.endswith(".md"):
            target += ".md"
        return target
    if target.startswith("."):
        try:
            resolved = (current_dir / target).resolve()
            result = str(resolved.relative_to(vault.resolve()))
            if not result.endswith(".md"):
                result += ".md"
            return result
        except ValueError:
            return None
    if "/" in target:
        if not target.endswith(".md"):
            target += ".md"
        return target
    name = target if target.endswith(".md") else target + ".md"
    if name in name_index:
        return name_index[name]
    candidate = current_dir / name
    if candidate.exists():
        return str(candidate.relative_to(vault))
    return None


def _check_broken_links(vault):
    all_files = find_md_files(vault)
    all_relpaths = {str(f.relative_to(vault)) for f in all_files}
    name_index = {f.name: str(f.relative_to(vault)) for f in all_files}
    broken = []

    for f in all_files:
        rel = str(f.relative_to(vault))
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue

        clean = text
        if clean.startswith("---"):
            end = clean.find("\n---\n", 3)
            if end != -1:
                clean = clean[end + 5:]
        clean = re.sub(r'```[\s\S]*?```', '', clean)
        clean = re.sub(r'`[^`]+`', '', clean)

        for m in re.finditer(r'\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]', clean):
            target = m.group(1).strip().rstrip('\\')
            resolved = _resolve_simple(target, vault, f.parent, name_index)
            if resolved and resolved not in all_relpaths:
                candidate = vault / resolved
                if not candidate.exists():
                    broken.append(f"{rel} → [[{target}]]")

        for m in re.finditer(r'\[([^\]]*)\]\(([^)]+\.md)\)', clean):
            target = m.group(2).strip()
            resolved = _resolve_simple(target, vault, f.parent, name_index)
            if resolved and resolved not in all_relpaths:
                candidate = vault / resolved
                if not candidate.exists():
                    broken.append(f"{rel} → [{m.group(1)}]({target})")

    return broken


# ── Check 5: Scripts funcionales ──

def _check_scripts(vault):
    """Smoke test: los comandos del CLI funcionan (vía subprocess, autocontenido)."""
    cli_module = str((Path(__file__).resolve().parent.parent.parent))

    tests = [
        (["graph", "stats"], 15),
        (["search"], 10),
        (["traverse", "tp3-cibernetico", "--depth", "1"], 15),
        (["validate", "--all"], 15),
        (["touch", "--all"], 10),
        (["audit"], 10),
        (["review", "--count"], 10),
        (["new", "--type", "Decision", "--title", "Health Check Smoke Test",
          "--description", "Test automático del health check.", "--dry-run"], 10),
    ]

    ok, failed = 0, []

    for cmd_args, timeout in tests:
        name = f"cli {' '.join(cmd_args)}"
        try:
            result = subprocess.run(
                ["python3", "-m", "cli"] + cmd_args,
                capture_output=True, text=True, timeout=timeout,
                cwd=str(vault),
                env={**os.environ, "PYTHONPATH": cli_module},
            )
            if result.returncode != 0:
                # review --count usa exit code 1 para indicar "hay items pendientes" (no es error)
                if cmd_args == ["review", "--count"] and result.returncode == 1:
                    ok += 1
                else:
                    # Capturar el output completo del error (stdout o stderr)
                    err_output = (result.stderr or result.stdout).strip()
                    err_lines = err_output.split("\n")
                    # Tomar las primeras 5 líneas del error para diagnóstico
                    err = "; ".join(line.strip() for line in err_lines[:5] if line.strip())
                    if not err:
                        err = f"exit {result.returncode}"
                    failed.append(f"{name}: {err}")
            else:
                ok += 1
        except subprocess.TimeoutExpired:
            failed.append(f"{name}: timeout ({timeout}s)")
        except Exception as e:
            failed.append(f"{name}: {str(e)[:80]}")

    return ok, failed


# ── Check 6: Git hook ──

def _check_git_hook(vault):
    hook = vault / ".git" / "hooks" / "post-commit"
    if not hook.exists():
        return False, "hook post-commit no existe"
    if not os.access(hook, os.X_OK):
        return False, "hook post-commit no es ejecutable"
    return True, None


# ── Check 7: Bloque cyber ──

def _check_cyber(vault):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ok, warnings, errors = 0, [], []

    for f in find_md_files(vault):
        rel = str(f.relative_to(vault))
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue

        fm, _ = parse_frontmatter(text)
        if fm is None:
            continue

        cyber = fm.get("cyber")
        if not isinstance(cyber, dict):
            ok += 1
            continue

        concept_type = str(fm.get("type", ""))
        outcome = str(cyber.get("outcome", ""))
        review_on = str(cyber.get("review_on", "")) if cyber.get("review_on") else ""

        if concept_type in EXCLUDED_CYBER_TYPES:
            errors.append(f"{rel}: bloque cyber: en type '{concept_type}' "
                          f"(excluido — solo Decision/Plan/Project/Insight)")
            continue

        if not outcome or outcome in ("", "None"):
            warnings.append(f"{rel}: bloque cyber: sin 'outcome'")

        if outcome == "pending" and review_on and review_on <= today:
            errors.append(f"{rel}: cyber.outcome=pending con review_on={review_on} "
                          f"vencido — loop roto")

        ok += 1

    return ok, warnings, errors


# ── Check 8: Sincronización plugin↔spec ──

def _check_plugin_hash_sync(vault):
    """Verifica que plugin_hash en specs coincida con HEAD del repo del plugin.

    Busca specs con plugin_hash en el frontmatter. Para cada una, intenta
    encontrar el repo local en ~/.hermes/plugins/<nombre>/ y comparar hashes.
    """
    specs_dir = vault / "specs"
    plugins_dir = Path.home() / ".hermes" / "plugins"
    ok, stale = 0, []

    if not specs_dir.is_dir():
        return 0, ["specs/ no existe"]

    for spec_file in sorted(specs_dir.glob("*.md")):
        try:
            text = spec_file.read_text(encoding="utf-8")
        except Exception:
            continue

        fm, _ = parse_frontmatter(text)
        if fm is None:
            continue

        plugin_hash = fm.get("plugin_hash")
        if not plugin_hash:
            continue

        spec_name = spec_file.stem
        desc = str(fm.get("description", ""))

        # Intentar encontrar el plugin local por nombre
        # Patrones: "plugin-session-summarizer-..." → "session-summarizer"
        plugin_name = spec_name
        for prefix in ("plugin-", "hermes-"):
            if plugin_name.startswith(prefix):
                plugin_name = plugin_name[len(prefix):]
                break

        plugin_dir = plugins_dir / plugin_name
        if not (plugin_dir / ".git").exists():
            # Buscar por nombre aproximado: el nombre base del plugin
            # como substring del nombre del directorio
            found = False
            if plugins_dir.is_dir():
                for d in plugins_dir.iterdir():
                    if not d.is_dir() or not (d / ".git").exists():
                        continue
                    # El nombre del directorio debe ser substring del nombre extraido
                    # Ej: "session-summarizer" ⊂ "session-summarizer-resumidor-de-..."
                    if d.name in plugin_name or plugin_name in d.name:
                        plugin_dir = d
                        found = True
                        break
                    # También probar con la primera parte del nombre
                    base = plugin_name.split("-")[0]
                    if base and d.name.startswith(base):
                        plugin_dir = d
                        found = True
                        break
            if not found:
                stale.append(f"{spec_file.relative_to(vault)}: plugin_hash={plugin_hash[:7]} "
                             f"pero no se encontró repo local en ~/.hermes/plugins/")
                continue

        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=str(plugin_dir),
            )
            if result.returncode != 0:
                stale.append(f"{spec_file.relative_to(vault)}: no se pudo leer HEAD "
                             f"de {plugin_dir}")
                continue

            head = result.stdout.strip()
            if head.startswith(plugin_hash):
                ok += 1
            else:
                stale.append(f"{spec_file.relative_to(vault)}: plugin_hash={plugin_hash[:7]} "
                             f"≠ HEAD={head[:7]} en {plugin_dir.name} — spec desincronizada")
        except Exception as e:
            stale.append(f"{spec_file.relative_to(vault)}: error leyendo git: {e}")

    return ok, stale

def run(args, vault):
    strict = getattr(args, "strict", False)
    json_out = getattr(args, "json", False)

    if not vault.exists():
        msg = f"Error: vault no encontrado en {vault}"
        if json_out:
            print(json.dumps({"error": msg}))
        else:
            print(msg)
        return 1

    results = {}
    all_warnings = []
    all_errors = []

    # 1. Frontmatter
    fm_ok, fm_bad, fm_warn = _check_frontmatter(vault)
    results["frontmatter"] = {"ok": fm_ok, "bad": len(fm_bad), "details": fm_bad[:20]}
    all_errors.extend(fm_bad)
    all_warnings.extend(fm_warn)

    # 2. Índices
    idx_ok, idx_stale = _check_indices(vault)
    results["indices"] = {"ok": idx_ok, "stale": len(idx_stale), "details": idx_stale[:10]}
    all_warnings.extend(idx_stale)

    # 3. Grafo
    graph_data, graph_warn = _check_graph(vault)
    results["graph"] = graph_data
    if graph_data is None:
        all_errors.append("grafo: no se pudo analizar")
    all_warnings.extend(graph_warn)

    # 4. Links rotos
    broken = _check_broken_links(vault)
    results["broken_links"] = {"count": len(broken), "details": broken[:15]}
    all_warnings.extend(broken[:15])

    # 5. Scripts
    scripts_ok, scripts_failed = _check_scripts(vault)
    results["scripts"] = {"ok": scripts_ok, "failed": len(scripts_failed), "details": scripts_failed}
    all_errors.extend(scripts_failed)

    # 6. Git hook
    hook_ok, hook_err = _check_git_hook(vault)
    results["git_hook"] = hook_ok
    if hook_err:
        all_errors.append(hook_err)

    # 7. Bloque cyber
    cyber_ok, cyber_warn, cyber_err = _check_cyber(vault)
    results["cyber"] = {"ok": cyber_ok, "warnings": len(cyber_warn),
                        "errors": len(cyber_err),
                        "details": cyber_err[:10] + cyber_warn[:10]}
    all_warnings.extend(cyber_warn)
    all_errors.extend(cyber_err)

    # 8. Sincronización plugin↔spec
    plugin_ok, plugin_stale = _check_plugin_hash_sync(vault)
    results["plugin_hash_sync"] = {"ok": plugin_ok, "stale": len(plugin_stale),
                                   "details": plugin_stale}
    all_warnings.extend(plugin_stale)

    # Score
    checks_total = 8
    checks_ok = sum([
        1 if len(fm_bad) == 0 else 0,
        1 if len(idx_stale) == 0 else 0,
        1 if graph_data and graph_data.get("orphans", 99) == 0 else 0,
        1 if len(broken) == 0 else 0,
        1 if len(scripts_failed) == 0 else 0,
        1 if hook_ok else 0,
        1 if len(cyber_err) == 0 else 0,
        1 if len(plugin_stale) == 0 else 0,
    ])

    if json_out:
        print(json.dumps({
            "score": f"{checks_ok}/{checks_total}",
            "errors": len(all_errors),
            "warnings": len(all_warnings),
            "error_details": all_errors[:20],
            "warning_details": all_warnings[:20],
            "results": results,
        }, indent=2, ensure_ascii=False))
        return 0 if not strict or (not all_errors and not all_warnings) else 1

    # Reporte legible
    print("🔍 OKF Vault Health Check")
    print("─" * 54)

    if fm_bad:
        print(f"❌ Frontmatter: {fm_ok} ok, {len(fm_bad)} errores")
        for e in fm_bad[:5]:
            print(f"   - {e}")
    else:
        print(f"✅ Frontmatter: {fm_ok}/{fm_ok} archivos conformes")

    total_idx = idx_ok + len(idx_stale)
    if idx_stale:
        print(f"⚠️  Índices: {idx_ok}/{total_idx} sincronizados, {len(idx_stale)} desactualizados")
        for e in idx_stale[:3]:
            print(f"   - {e}")
    else:
        print(f"✅ Índices: {total_idx}/{total_idx} sincronizados")

    if graph_data:
        g = graph_data
        gt = g.get("tags", {})
        tag_str = f", {gt.get('total', 0)} tags ({gt.get('shared', 0)} compartidas)"
        if g["orphans"] == 0:
            print(f"✅ Grafo: {g['nodes']} nodos, {g['edges']} aristas, 0 huérfanos{tag_str}")
        else:
            print(f"⚠️  Grafo: {g['nodes']} nodos, {g['edges']} aristas, {g['orphans']} huérfanos{tag_str}")
    else:
        print("❌ Grafo: no se pudo analizar")

    if broken:
        print(f"⚠️  Links rotos: {len(broken)}")
        for b in broken[:3]:
            print(f"   - {b}")
    else:
        print("✅ Links: sin links rotos detectados")

    total_scr = scripts_ok + len(scripts_failed)
    if scripts_failed:
        print(f"❌ Scripts: {scripts_ok}/{total_scr} funcionales")
        for f in scripts_failed:
            print(f"   - {f}")
    else:
        print(f"✅ Scripts: {total_scr}/{total_scr} funcionales")

    if hook_ok:
        print("✅ Git hook: post-commit presente y ejecutable")
    else:
        print(f"❌ Git hook: {hook_err}")

    if cyber_err:
        print(f"❌ Bloque cyber: {cyber_ok} ok, {len(cyber_err)} errores")
        for e in cyber_err[:3]:
            print(f"   - {e}")
    elif cyber_warn:
        print(f"⚠️  Bloque cyber: {cyber_ok} ok, {len(cyber_warn)} warnings")
    else:
        print(f"✅ Bloque cyber: {cyber_ok}/{cyber_ok} conformes")

    total_plugins = plugin_ok + len(plugin_stale)
    if plugin_stale:
        print(f"⚠️  Plugin↔spec: {plugin_ok}/{total_plugins} sincronizados")
        for e in plugin_stale[:3]:
            print(f"   - {e}")
    elif total_plugins > 0:
        print(f"✅ Plugin↔spec: {total_plugins}/{total_plugins} sincronizados")

    print("─" * 54)
    if all_errors:
        print(f"🔴 Salud: {checks_ok}/{checks_total} — {len(all_errors)} errores, "
              f"{len(all_warnings)} warnings")
    elif all_warnings:
        print(f"🟡 Salud: {checks_ok}/{checks_total} — {len(all_warnings)} warnings")
    else:
        print(f"🟢 Salud: {checks_ok}/{checks_total} — todo limpio")

    if strict and (all_errors or all_warnings):
        return 1
    return 0
# test hook
