"""Comando stale — Detector de obsolescencia semántica.

Escanea conceptos del vault en busca de señales de obsolescencia:
conceptos con formato válido pero desconectados de la realidad actual.

Señales:
  1. timestamp > 90 días        → contenido estancado
  2. reads = 0                  → nadie lo consulta
  3. status: propuesta > 30 días → decisión fantasma
  4. sin backlinks              → huérfano en el grafo
  5. sin commits > 6 meses      → sin mantenimiento
  6. type: Decision sin status  → decisión sin cierre
  7. description vs body        → la description describe problemas
     que el body ya resolvió (checkboxes [x] > 70%)

Clasificación:
  🔴 STALE     — 3+ señales
  🟡 ATENCIÓN  — 1-2 señales
  🟢 FRESCO    — 0 señales
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from cli.frontmatter import parse_frontmatter
from cli.vault import find_md_files


def get_today():
    return datetime.now(timezone.utc)


def days_ago(date_str, today=None):
    """Calcula días transcurridos desde una fecha ISO."""
    if today is None:
        today = get_today()
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (today - dt).days
    except (ValueError, TypeError):
        return None


def git_last_commit_date(filepath, vault):
    """Fecha del último commit que tocó este archivo. None si no hay commits."""
    try:
        result = subprocess.run(
            ["git", "-C", str(vault), "log", "-1", "--format=%aI", "--", str(filepath.relative_to(vault))],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None
    except Exception:
        return None


def count_checkboxes(text):
    """Cuenta checkboxes [x] y [ ] en el body (post-frontmatter)."""
    if text.startswith("---"):
        end = text.find("\n---\n", 3)
        if end == -1:
            end = text.find("\n---", 3)
        if end != -1:
            body = text[end:]
        else:
            body = text
    else:
        body = text

    completed = len(re.findall(r'^\s*- \[x\]', body, re.MULTILINE | re.IGNORECASE))
    pending = len(re.findall(r'^\s*- \[ \]', body, re.MULTILINE))
    total = completed + pending
    return completed, pending, total


def has_problem_language(description):
    """Detecta si la description habla de problemas en tiempo presente."""
    problem_patterns = [
        r'\bno\s+(existe|funciona|hay|tiene|está)\b',
        r'\broto[s]?\b',
        r'\bfalso[s]?\b',
        r'\bfalta[n]?\b',
        r'\bsin\s+(implementar|resolver|definir|conectar|backend)\b',
        r'\bpendiente[s]?\b',
        r'\bincompleto\b',
        r'\bplaceholder\b',
        r'\bno\s+implementado\b',
        r'\bno\s+conectado\b',
        r'\bclaims?\s+fals[oa]s?\b',
        r'\b404\b',
        r'\bCTAs?\s+rot[oa]s?\b',
        r'\bcero\s+métricas\b',
        r'\bno\s+almacena\b',
        r'\bno\s+notifica\b',
        r'\bse\s+pierden\b',
        r'\bno\s+está\b',
    ]
    desc_lower = description.lower()
    for pat in problem_patterns:
        if re.search(pat, desc_lower):
            return True
    return False


def build_backlinks_index(vault):
    """Construye índice de backlinks: {target_filename: [source_relpaths]}."""
    index = {}
    name_index = {}  # filename → relpath
    for f in find_md_files(vault):
        name_index[f.name] = str(f.relative_to(vault))

    for f in find_md_files(vault):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue

        wikilinks = re.findall(r'\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]', text)
        source_rel = str(f.relative_to(vault))

        for target in wikilinks:
            target = target.strip()
            # Intentar resolver: nombre exacto, con .md, path relativo
            resolved = None
            if target in name_index:
                resolved = name_index[target]
            elif target + ".md" in name_index:
                resolved = name_index[target + ".md"]
            else:
                # Buscar por nombre de archivo (sin path)
                target_name = Path(target).name
                if not target_name.endswith(".md"):
                    target_name += ".md"
                if target_name in name_index:
                    resolved = name_index[target_name]

            if resolved:
                if resolved not in index:
                    index[resolved] = []
                if source_rel not in index[resolved]:
                    index[resolved].append(source_rel)

    return index


def collect_stale(vault, timestamp_days=90, propuesta_days=30,
                  no_commits_days=180, checkbox_ratio=0.7):
    """Escanea todos los conceptos y evalúa señales de obsolescencia."""
    today = get_today()
    backlinks = build_backlinks_index(vault)
    results = []

    for f in find_md_files(vault):
        rel = str(f.relative_to(vault))
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue

        fm, _ = parse_frontmatter(text)
        if not fm:
            continue

        signals = []
        details = {}

        # ── Señal 1: timestamp antiguo ──
        ts = fm.get("timestamp")
        if ts:
            age = days_ago(str(ts), today)
            if age is not None and age > timestamp_days:
                signals.append(f"timestamp {age}d")
                details["age_days"] = age

        # ── Señal 2: reads = 0 ──
        reads = fm.get("reads")
        if reads is not None and int(reads) == 0:
            signals.append("reads=0")

        # ── Señal 3: status: propuesta sin resolver ──
        status = fm.get("status", "")
        if str(status).lower() == "propuesta":
            if ts:
                age = days_ago(str(ts), today)
                if age is not None and age > propuesta_days:
                    signals.append(f"propuesta sin resolver ({age}d)")
            else:
                signals.append("propuesta sin timestamp")

        # ── Señal 4: sin backlinks ──
        if rel not in backlinks or len(backlinks[rel]) == 0:
            # Excluir conceptos raíz que son naturalmente huérfanos
            concept_type = str(fm.get("type", ""))
            if concept_type not in ("MarcoTeorico", "Spec", "Tool"):
                signals.append("sin backlinks")

        # ── Señal 5: sin commits ──
        last_commit = git_last_commit_date(f, vault)
        if last_commit:
            commit_age = days_ago(last_commit, today)
            if commit_age is not None and commit_age > no_commits_days:
                signals.append(f"sin commits ({commit_age}d)")
                details["commit_age_days"] = commit_age
        else:
            signals.append("sin commits (nuevo?)")

        # ── Señal 6: type Decision sin status ──
        if str(fm.get("type", "")) == "Decision" and not fm.get("status"):
            signals.append("decisión sin status")

        # ── Señal 7: description vs body inconsistency ──
        description = str(fm.get("description", ""))
        if has_problem_language(description):
            completed, pending, total = count_checkboxes(text)
            if total >= 3 and completed / total >= checkbox_ratio:
                signals.append(f"desc desactualizada ({completed}/{total} tasks ✓)")
                details["tasks_completed"] = f"{completed}/{total}"

        # ── Clasificar ──
        count = len(signals)
        if count >= 3:
            level = "STALE"
            icon = "🔴"
        elif count >= 1:
            level = "ATENCIÓN"
            icon = "🟡"
        else:
            level = "FRESCO"
            icon = "🟢"

        results.append({
            "file": rel,
            "type": str(fm.get("type", "")),
            "title": str(fm.get("title", rel)),
            "level": level,
            "icon": icon,
            "signal_count": count,
            "signals": signals,
            "details": details,
        })

    # Ordenar: STALE primero, luego ATENCIÓN, luego FRESCO
    priority = {"STALE": 0, "ATENCIÓN": 1, "FRESCO": 2}
    results.sort(key=lambda r: (priority.get(r["level"], 9), r["file"]))

    return results


def run(args, vault, config=None):
    """Ejecuta el detector de obsolescencia."""
    json_out = getattr(args, "json", False)

    # Umbrales desde config o defaults
    timestamp_days = config.stale_timestamp_days if config else 90
    propuesta_days = config.stale_propuesta_days if config else 30
    no_commits_days = config.stale_no_commits_days if config else 180
    checkbox_ratio = config.stale_checkbox_ratio if config else 0.7

    results = collect_stale(vault, timestamp_days, propuesta_days,
                            no_commits_days, checkbox_ratio)

    if json_out:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    stale = [r for r in results if r["level"] == "STALE"]
    atencion = [r for r in results if r["level"] == "ATENCIÓN"]
    fresco = [r for r in results if r["level"] == "FRESCO"]

    total = len(results)

    print(f"🕵️ Detector de Obsolescencia — {get_today().strftime('%Y-%m-%d')}")
    print("═" * 60)

    if not stale and not atencion:
        print(f"\n✅ Todo FRESCO — {total} concepto(s) sin señales de obsolescencia.")
        print("\n── FRESCO ──")
        for r in fresco:
            print(f"   🟢 [{r['type']}] {r['file']}")
        return 0

    # ── STALE ──
    if stale:
        print(f"\n🔴 STALE — {len(stale)} concepto(s) con 3+ señales")
        print("─" * 60)
        for r in stale:
            print(f"\n   📄 [{r['type']}] {r['file']}")
            print(f"   {r['title']}")
            for s in r["signals"]:
                print(f"   ⚡ {s}")

    # ── ATENCIÓN ──
    if atencion:
        print(f"\n🟡 ATENCIÓN — {len(atencion)} concepto(s) con 1-2 señales")
        print("─" * 60)
        for r in atencion:
            print(f"\n   📄 [{r['type']}] {r['file']}")
            print(f"   {r['title']}")
            for s in r["signals"]:
                print(f"   ⚡ {s}")

    # ── FRESCO ──
    if fresco:
        print(f"\n🟢 FRESCO — {len(fresco)} concepto(s) sin señales")
        for r in fresco:
            print(f"   🟢 [{r['type']}] {r['file']}")

    # ── Resumen ──
    print(f"\n{'═' * 60}")
    print(f"🔴{len(stale)} 🟡{len(atencion)} 🟢{len(fresco)}  — {total} concepto(s) analizado(s)")

    return 1 if stale else 0
