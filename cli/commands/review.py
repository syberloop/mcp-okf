"""Comando review — Sensor del loop cibernético.

Escanea conceptos con cyber.review_on <= hoy y clasifica por severidad.
"""

import json
import sys
from datetime import datetime, timezone
from cli.frontmatter import parse_frontmatter
from cli.vault import find_md_files


def get_today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def collect_due(vault):
    """Busca conceptos con cyber.review_on <= hoy."""
    today = get_today_str()
    due = []

    for f in find_md_files(vault):
        rel = str(f.relative_to(vault))
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue

        fm, _ = parse_frontmatter(text)
        if not fm:
            continue

        cyber = fm.get("cyber")
        if not isinstance(cyber, dict):
            continue

        review_on = cyber.get("review_on")
        if not review_on:
            continue

        review_str = str(review_on)
        if review_str <= today:
            outcome = str(cyber.get("outcome", ""))
            sensor = str(cyber.get("sensor", "?"))
            metric = cyber.get("target_metric", {})
            metric_name = metric.get("name", "?") if isinstance(metric, dict) else "?"

            if outcome in ("pending", "", "None"):
                severity = "required"
            else:
                severity = "verify"

            due.append({
                "file": rel,
                "type": str(fm.get("type", "")),
                "title": str(fm.get("title", rel)),
                "severity": severity,
                "outcome": outcome if outcome not in ("", "None") else "(sin medir)",
                "review_on": review_str,
                "sensor": sensor,
                "metric": metric_name,
            })

    return due


def run(args, vault, config=None):
    """Ejecuta la revisión cibernética."""
    json_out = getattr(args, "json", False)
    count_only = getattr(args, "count", False)

    due = collect_due(vault)

    if json_out:
        print(json.dumps(due, ensure_ascii=False, indent=2))
    elif count_only:
        required = sum(1 for d in due if d["severity"] == "required")
        verify = sum(1 for d in due if d["severity"] == "verify")
        if due:
            print(f"🔴{required} 🟡{verify}")
        else:
            print("✅ nada pendiente")
    else:
        if not due:
            print("✅ Nada pendiente de revisión.")
        else:
            required = [d for d in due if d["severity"] == "required"]
            verify = [d for d in due if d["severity"] == "verify"]

            print(f"📡 Revisión cibernética — {get_today_str()}")
            print("─" * 55)

            if required:
                print(f"\n🔴 Revisión requerida ({len(required)}):")
                for d in required:
                    print(f"   [{d['type']}] {d['file']}")
                    print(f"   Sensor: {d['sensor']} | Métrica: {d['metric']}")
                    print(f"   Outcome: {d['outcome']} | Review era: {d['review_on']}")
                    print("")

            if verify:
                print(f"🟡 Re-verificar vigencia ({len(verify)}):")
                for d in verify:
                    print(f"   [{d['type']}] {d['file']}")
                    print(f"   Outcome actual: {d['outcome']} | Review era: {d['review_on']}")
                    print(f"   ¿Sigue siendo válida esta decisión?")
                    print("")

            print(f"─\n{len(due)} concepto(s) requieren atención.")

    return 1 if due else 0
