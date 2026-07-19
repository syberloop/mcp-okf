#!/usr/bin/env python3
"""Mide el semantic_query_ratio desde agent.log.

Calcula la proporción de consultas al vault que usan herramientas semánticas
(mcp__okf__*) vs get_page crudo (mcp__gbrain__get_page), por sesión y global.

Uso:
    python3 measure.py [--since YYYY-MM-DD] [--json]
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

LOG = Path.home() / ".hermes" / "logs" / "agent.log"

# Herramientas semánticas
SEMANTIC = {"mcp__okf__traverse", "mcp__okf__search"}

# Herramienta cruda (bypass del grafo)
RAW = {"mcp__gbrain__get_page"}


def parse_log(since: str = ""):
    """Parsea agent.log y agrupa tool calls por session_id."""
    sessions = defaultdict(lambda: {"semantic": 0, "raw": 0, "other_okf": 0})

    tool_re = re.compile(r"session=(\S+).*?(?:mcp__okf__\w+|mcp__gbrain__get_page)")
    session_re = re.compile(r"session=(\S+)")
    tool_name_re = re.compile(r"mcp__(okf__\w+|gbrain__get_page)")

    with open(LOG) as f:
        current_session = None
        for line in f:
            # Skip if before --since
            if since:
                # Extract timestamp if present
                ts_match = re.search(r"(\d{4}-\d{2}-\d{2})", line)
                if ts_match and ts_match.group(1) < since:
                    continue

            sess_match = session_re.search(line)
            if sess_match:
                current_session = sess_match.group(1)

            tool_match = re.search(
                r"function.*?name.*?(mcp__(okf__\w+|gbrain__get_page))", line
            )
            if tool_match and current_session:
                tool = tool_match.group(1)
                if tool.startswith("mcp__okf__"):
                    okf_tool = tool.replace("mcp__", "")
                    if okf_tool in ("okf__traverse", "okf__search"):
                        sessions[current_session]["semantic"] += 1
                    else:
                        sessions[current_session]["other_okf"] += 1
                elif tool == "mcp__gbrain__get_page":
                    sessions[current_session]["raw"] += 1

    return sessions


def main():
    parser = argparse.ArgumentParser(description="Medir semantic_query_ratio")
    parser.add_argument("--since", help="Fecha inicio YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="Salida JSON")
    args = parser.parse_args()

    if not LOG.exists():
        print(f"ERROR: {LOG} no existe")
        sys.exit(1)

    sessions = parse_log(args.since)

    total_semantic = sum(s["semantic"] for s in sessions.values())
    total_raw = sum(s["raw"] for s in sessions.values())
    total = total_semantic + total_raw

    if args.json:
        output = {
            "since": args.since or "all",
            "sessions": {
                sid: {
                    "semantic": v["semantic"],
                    "raw": v["raw"],
                    "other_okf": v["other_okf"],
                    "ratio": (
                        round(v["semantic"] / (v["semantic"] + v["raw"]), 2)
                        if (v["semantic"] + v["raw"]) > 0
                        else None
                    ),
                }
                for sid, v in sessions.items()
            },
            "total": {
                "semantic": total_semantic,
                "raw": total_raw,
                "ratio": round(total_semantic / total, 2) if total > 0 else None,
            },
            "target": 0.90,
            "target_met": (total_semantic / total >= 0.90) if total > 0 else None,
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"{'Session':<40} {'Sem':>4} {'Raw':>4} {'Ratio':>7}  Status")
        print("-" * 70)
        for sid, v in sorted(sessions.items()):
            denom = v["semantic"] + v["raw"]
            if denom == 0:
                continue
            ratio = v["semantic"] / denom
            status = "✓" if ratio >= 0.90 else "✗"
            print(
                f"{sid:<40} {v['semantic']:>4} {v['raw']:>4} {ratio:>6.2f}  {status}"
            )
        print("-" * 70)
        if total > 0:
            ratio = total_semantic / total
            status = "✓ TARGET MET" if ratio >= 0.90 else "✗ BELOW TARGET (0.90)"
            print(f"{'TOTAL':<40} {total_semantic:>4} {total_raw:>4} {ratio:>6.2f}  {status}")
        else:
            print("No hay consultas al vault registradas aún.")


if __name__ == "__main__":
    main()
