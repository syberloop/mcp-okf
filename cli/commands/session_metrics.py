"""Command session-metrics — Aggregated session metrics of the vault."""

import re
import json
from pathlib import Path
from datetime import datetime


def _parse_metrics_section(body):
    """Extracts metrics from the ## Metrics section in the body."""
    metrics = {}
    m = re.search(r"## Métricas\n(.+)", body, re.DOTALL)
    if not m:
        return metrics
    
    section = m.group(1)
    
    # Tools usadas
    tm = re.search(r"Tools usadas:\s*(.+)", section)
    if tm:
        tools_str = tm.group(1)
        tools = {}
        for t in re.finditer(r"(\w+)\s*\((\d+)\)", tools_str):
            tools[t.group(1)] = int(t.group(2))
        metrics["tools"] = tools
    
    # Conceptos creados
    cm = re.search(r"Conceptos creados:\s*(\d+)", section)
    if cm:
        metrics["conceptos_creados"] = int(cm.group(1))
    
    # Commits
    gm = re.search(r"Commits:\s*(\d+)", section)
    if gm:
        metrics["commits"] = int(gm.group(1))
    
    # Infracciones
    im = re.search(r"Infracciones MCP:\s*(\d+)", section)
    if im:
        metrics["infracciones"] = int(im.group(1))
        # Extraer detalles
        details = []
        for line in section.split("\n"):
            if line.strip().startswith("- write_file") or line.strip().startswith("- read_file") or line.strip().startswith("- patch") or line.strip().startswith("- terminal"):
                details.append(line.strip())
        if details:
            metrics["infracciones_detalle"] = details
    
    return metrics


def _sessions_dir(vault, config):
    """Resuelve el directorio de sesiones del vault.

    El nombre lo define el vault (types.directory.Session), no un literal: el
    hardcode "sesiones" hacía que el comando reportara "(no sessions)" en
    cualquier vault con el esquema en inglés (decisions/plans/insights/...),
    que es el del config de ejemplo. Se conserva "sesiones" como último
    recurso para vaults antiguos.
    """
    if config is not None:
        try:
            nombre = dict(config.types_directory).get("Session")
        except Exception:
            nombre = None
        if nombre:
            return vault / nombre
    for nombre in ("sessions", "sesiones"):
        candidato = vault / nombre
        if candidato.exists():
            return candidato
    return vault / "sessions"


def run(args, vault, config=None):
    """Generates aggregated metrics of all sessions."""
    sesiones_dir = _sessions_dir(vault, config)
    if not sesiones_dir.exists():
        print("(no sessions)")
        return 0
    
    sessions = []
    for f in sorted(sesiones_dir.glob("sesion-*.md")):
        content = f.read_text()
        
        # Extraer description
        desc_m = re.search(r'description:\s*"([^"]+)"', content)
        desc = desc_m.group(1) if desc_m else ""
        
        # Extraer session_id
        sid_m = re.search(r'session_id:\s*"([^"]+)"', content)
        sid = sid_m.group(1) if sid_m else f.stem
        
        # Extraer fecha del filename o timestamp
        ts_m = re.search(r'timestamp:\s*(.+)', content)
        date_str = ts_m.group(1)[:10] if ts_m else f.stem.replace("sesion-", "")[:8]
        
        # Métricas
        metrics = _parse_metrics_section(content)
        
        sessions.append({
            "file": f.name,
            "session_id": sid,
            "date": date_str,
            "desc_len": len(desc),
            "metrics": metrics,
        })
    
    if getattr(args, "json", False):
        print(json.dumps(sessions, indent=2, ensure_ascii=False))
        return 0
    
    # Agregados
    total = len(sessions)
    con_metricas = sum(1 for s in sessions if s["metrics"])
    con_infracciones = sum(1 for s in sessions if s["metrics"].get("infracciones", 0) > 0)
    total_infracciones = sum(s["metrics"].get("infracciones", 0) for s in sessions)
    
    # Tools más usadas
    all_tools = {}
    for s in sessions:
        for tool, count in s["metrics"].get("tools", {}).items():
            all_tools[tool] = all_tools.get(tool, 0) + count
    top_tools = sorted(all_tools.items(), key=lambda x: -x[1])[:5]
    
    # Total conceptos
    total_conceptos = sum(s["metrics"].get("conceptos_creados", 0) for s in sessions)
    
    print(f"📊 Session metrics — {total} sessions, {con_metricas} with metrics")
    print()
    print(f"Total MCP violations: {total_infracciones} (in {con_infracciones} sessions)")
    print(f"Concepts created: {total_conceptos}")
    print()
    
    if top_tools:
        print("Most used tools:")
        for tool, count in top_tools:
            print(f"  {tool}: {count}")
    
    if con_infracciones > 0:
        print()
        print("🪞 Sessions with violations:")
        for s in sessions:
            inf = s["metrics"].get("infracciones", 0)
            if inf > 0:
                detalles = s["metrics"].get("infracciones_detalle", [])
                det_str = " — " + ", ".join(detalles[:3]) if detalles else ""
                print(f"  {s['date']} | {s['session_id'][:20]} | {inf} violation(s){det_str}")
    
    return 0
