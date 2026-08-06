"""Command review — Cybernetic loop sensor.

Scans concepts with cyber.review_on <= today and classifies by severity.
"""

import json
import sys
from datetime import datetime, timezone
from cli.frontmatter import parse_frontmatter
from cli.vault import find_md_files


def get_today_str():
    """'Today' in the domain timezone (Colombia, UTC-5), not UTC.

    Fix 2026-08-02: comparing review_on against UTC advanced
    expirations between 19:00 and 24:00 local time (UTC was already on
    the next day) — a tomorrow review_on appeared expired today.
    """
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%d")


def collect_due(vault):
    """Finds concepts with cyber.review_on <= today."""
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
                "outcome": outcome if outcome not in ("", "None") else "(unmeasured)",
                "review_on": review_str,
                "sensor": sensor,
                "metric": metric_name,
            })

    return due


def run(args, vault, config=None):
    """Runs the cybernetic review."""
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
            print("✅ nothing pending")
    else:
        if not due:
            print("✅ Nothing pending review.")
        else:
            required = [d for d in due if d["severity"] == "required"]
            verify = [d for d in due if d["severity"] == "verify"]

            print(f"📡 Cyber review — {get_today_str()}")
            print("─" * 55)

            if required:
                print(f"\n🔴 Review required ({len(required)}):")
                for d in required:
                    print(f"   [{d['type']}] {d['file']}")
                    print(f"   Sensor: {d['sensor']} | Metric: {d['metric']}")
                    print(f"   Outcome: {d['outcome']} | Review era: {d['review_on']}")
                    print("")

            if verify:
                print(f"🟡 Re-verify validity ({len(verify)}):")
                for d in verify:
                    print(f"   [{d['type']}] {d['file']}")
                    print(f"   Outcome actual: {d['outcome']} | Review era: {d['review_on']}")
                    print(f"   Is this decision still valid?")
                    print("")

            print(f"─\n{len(due)} concept(s) need attention.")

    return 1 if due else 0
