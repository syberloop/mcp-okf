"""Entry point del CLI OKF Vault.

Uso:
    python3 -m cli <comando> [opciones]

Comandos:
    search      Buscar conceptos y tareas pendientes
    read        Leer un concepto (+ auto-incrementar reads)
    traverse    Travesía semántica: frontmatter del concepto + vecindario
    graph       Analizar el grafo de wikilinks
    health      Verificación completa de integridad
    index       Regenerar index.md y log.md
    new         Crear un concepto nuevo
    touch       Estadísticas de lecturas
    dashboard   Generar dashboard.md
    stale       Detector de obsolescencia semántica
    review      Revisión cibernética (review_on vencido)
    audit       Auditar frontmatter de todos los conceptos
    validate    Validación estricta YAML pre-commit (sin fallback de regex)
"""

import argparse
import sys
import os
import time
from pathlib import Path


def build_parser():
    """Construye el parser principal con todos los subcomandos."""
    parser = argparse.ArgumentParser(
        prog="okf",
        description="CLI unificado para el vault OKF.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ejemplos:\n"
               "  python3 -m cli search --todos\n"
               "  python3 -m cli read specs/okf-v01\n"
               "  python3 -m cli graph stats\n"
               "  python3 -m cli health --json\n"
               "  python3 -m cli new --type Decision --title \"...\" --description \"...\"",
    )
    parser.add_argument("--vault", type=str, default=None,
                        help="Ruta al vault (default: $OKF_VAULT o ~/OKF-Vault)")
    parser.add_argument("--config", type=str, default=None,
                        help="Ruta a .okf.config.yaml (default: <vault>/.okf.config.yaml)")

    subparsers = parser.add_subparsers(dest="command", help="Comando a ejecutar")

    # ── search ──
    sp_search = subparsers.add_parser("search", help="Buscar conceptos y tareas")
    sp_search.add_argument("--query", type=str, default=None,
                           help="Filtrar por texto en title, description y tags")
    sp_search.add_argument("--type", dest="filter_type", type=str, default=None,
                           help="Filtrar por tipo (Decision, Project, Spec, etc.)")
    sp_search.add_argument("--status", dest="filter_status", type=str, default=None,
                           help="Filtrar por status (propuesta, aplicada, etc.)")
    sp_search.add_argument("--todos", action="store_true", default=False,
                           help="Buscar tareas - [ ] pendientes")
    sp_search.add_argument("--all", action="store_true", default=False,
                           help="Con --todos: incluir completadas - [x]")
    sp_search.add_argument("--aging", action="store_true", default=False,
                           help="Con --todos: mostrar antigüedad de tareas")
    sp_search.add_argument("--include-specs", action="store_true", default=False,
                           help="Con --todos: incluir checkboxes de type=Spec (criterios de aceptación, no tareas)")
    sp_search.add_argument("--with-graph", action="store_true", default=False,
                           help="Mostrar aristas tipadas entre los resultados al final")
    sp_search.add_argument("--json", action="store_true", default=False,
                           help="Salida JSON")
    sp_search.add_argument("--cyber-field", type=str, default=None,
                           help="Filtrar por campo cyber: (sensor, outcome, etc.)")
    sp_search.add_argument("--cyber-value", type=str, default=None,
                           help="Valor del campo --cyber-field")
    sp_search.add_argument("--review-due", action="store_true", default=False,
                           help="Solo conceptos con cyber.review_on <= hoy")
    sp_search.add_argument("--since", type=str, default=None,
                           help="Filtrar por timestamp >= fecha (ISO 8601, inclusivo)")
    sp_search.add_argument("--until", type=str, default=None,
                           help="Filtrar por timestamp <= fecha (ISO 8601, inclusivo)")

    # ── read ──
    sp_read = subparsers.add_parser("read", help="Leer un concepto")
    sp_read.add_argument("target", type=str, nargs="?", help="Concepto a leer")
    sp_read.add_argument("--offset", type=int, default=1, help="Línea de inicio")
    sp_read.add_argument("--limit", type=int, default=500, help="Máx líneas")
    sp_read.add_argument("--no-touch", action="store_true", default=False,
                         help="No incrementar contador reads")

    # ── traverse ──
    sp_traverse = subparsers.add_parser("traverse",
                                        help="Travesía semántica del grafo")
    sp_traverse.add_argument("target", type=str, nargs="?",
                             help="Concepto origen (opcional si se usa --seeds)")
    sp_traverse.add_argument("--seeds", type=str, nargs="+", default=None,
                             help="Múltiples conceptos origen (unión + deduplicación)")
    sp_traverse.add_argument("--depth", type=int, default=1,
                             help="Profundidad de travesía (default: 1)")
    sp_traverse.add_argument("--direction", type=str, default="both",
                             choices=["both", "out", "in"],
                             help="Dirección: both, out, in (default: both)")
    sp_traverse.add_argument("--no-cyber", action="store_true", default=False,
                             help="No seguir aristas cyber.corrects/corrected_by")
    sp_traverse.add_argument("--json", action="store_true", default=False,
                             help="Salida JSON")
    sp_traverse.add_argument("--edge-type", dest="edge_type", type=str, default=None,
                             choices=["extiende", "refina", "fundamenta",
                                      "aplica", "depende", "corrige"],
                             help="Declarar el tipo ontológico explorado (anotación; no filtra)")
    sp_traverse.add_argument("--filter", action="store_true", default=False,
                             help="Con --edge-type: excluir aristas que no son de ese tipo")

    # ── graph ──
    sp_graph = subparsers.add_parser("graph", help="Analizar el grafo de wikilinks")
    sp_graph.add_argument("subcommand", nargs="?", type=str,
                          help="stats|orphans|hubs|backlinks|deps|tags|bridges|cluster|path|dump|dirs|types|impact|suggest-edge-types")
    sp_graph.add_argument("args", nargs="*", type=str,
                          help="Argumentos adicionales para el subcomando")
    sp_graph.add_argument("--edge-type", dest="edge_type", type=str, default=None,
                          help="Filtrar backlinks/deps por tipo de arista "
                               "(extiende, refina, fundamenta, aplica, depende, corrige)")
    sp_graph.add_argument("--apply", action="store_true", default=False,
                          help="Con suggest-edge-types: aplicar sugerencias ALTA")
    sp_graph.add_argument("--dry-run", action="store_true", default=False,
                          help="Con suggest-edge-types --apply: previsualizar sin escribir")
    sp_graph.add_argument("--min-score", dest="min_score", type=float, default=None,
                          help="Con suggest-edge-types: score mínimo para aplicar "
                               "(scoring semántico 0.0-1.0; default: config graph.suggest_min_score)")

    # ── health ──
    sp_health = subparsers.add_parser("health", help="Chequeo completo de salud")
    sp_health.add_argument("--strict", action="store_true", default=False,
                           help="Warnings causan exit 1")
    sp_health.add_argument("--json", action="store_true", default=False,
                           help="Salida JSON")

    # ── index ──
    sp_index = subparsers.add_parser("index", help="Regenerar index.md y log.md")

    # ── new ──
    sp_new = subparsers.add_parser("new", help="Crear un concepto nuevo")
    sp_new.add_argument("--type", dest="concept_type", required=True,
                        help="Tipo: Decision, Plan, Project, Insight, MarcoTeorico, "
                             "LeccionAprendida, Tool, Spec")
    sp_new.add_argument("--title", required=True, help="Título descriptivo")
    sp_new.add_argument("--description", required=True, help="Resumen de una línea")
    sp_new.add_argument("--tags", default=None, help="Tags separadas por coma")
    sp_new.add_argument("--status", default=None,
                        help="Estado: propuesta, aplicada, activo, etc.")
    sp_new.add_argument("--resource", default=None, help="URI canónica externa")
    sp_new.add_argument("--cyber", action="store_true", default=False,
                        help="Agregar bloque cyber:")
    sp_new.add_argument("--dry-run", action="store_true", default=False,
                        help="Mostrar sin escribir")
    sp_new.add_argument("--body", default=None,
                        help="Contenido del body (reemplaza el template por defecto)")
    sp_new.add_argument("--body-file", default=None,
                        help="Archivo con el contenido del body")
    sp_new.add_argument("--link", dest="links", action="append", default=None,
                        help="Link tipado: 'target:type' (repetible). "
                             "Ej: --link frameworks/tp3:extiende")

    # ── touch ──
    sp_touch = subparsers.add_parser("touch", help="Estadísticas de lecturas")
    sp_touch.add_argument("target", nargs="?", type=str, help="Concepto a incrementar")
    sp_touch.add_argument("--all", action="store_true", default=False,
                          help="Mostrar stats de todos los conceptos")

    # ── trace ──
    sp_trace = subparsers.add_parser("trace", help="Rastrear referencias en el ecosistema OKF")
    sp_trace.add_argument("query", type=str, help="Término a buscar")
    sp_trace.add_argument("--layers", type=str, default="vault,code,hooks,cron,agents",
                          help="Capas a rastrear (default: todas)")

    # ── analytics ──
    sp_analytics = subparsers.add_parser("analytics", help="Consultas analíticas sobre Cognitive Trace")
    sp_analytics.add_argument("--query", type=str, default="most_visited",
                              help="Tipo de consulta (most_visited, session_heatmap, tool_usage, edge_type_usage, "
                                   "daily_activity, node_timeline, error_summary, co_visited, "
                                   "read_ratio, session_diff, depth_stats, entry_points, prompts)")
    sp_analytics.add_argument("--limit", type=int, default=10,
                              help="Límite de resultados (default 10)")
    sp_analytics.add_argument("--arg", type=str, default="",
                              help="Argumento adicional (slug para node_timeline/co_visited, "
                                   "'sessionA,sessionB' para session_diff)")
    sp_analytics.add_argument("--session-id", type=str, default="",
                              help="Filtrar por sesión (vacío = actual vía $OKF_SESSION_ID)")

    # ── dashboard ──
    sp_dash = subparsers.add_parser("dashboard", help="Generar dashboard.md")

    # ── stale ──
    sp_stale = subparsers.add_parser("stale", help="Detector de obsolescencia semántica")
    sp_stale.add_argument("--json", action="store_true", default=False,
                          help="Salida JSON")

    # ── session-metrics ──
    sp_sm = subparsers.add_parser("session-metrics", help="Métricas agregadas de sesiones")
    sp_sm.add_argument("--json", action="store_true", default=False,
                       help="Salida JSON")

    # ── review ──
    sp_review = subparsers.add_parser("review", help="Revisión cibernética")
    sp_review.add_argument("--json", action="store_true", default=False,
                           help="Salida JSON")
    sp_review.add_argument("--count", action="store_true", default=False,
                           help="Solo conteo")

    # ── audit ──
    sp_audit = subparsers.add_parser("audit", help="Auditar frontmatter")

    # ── validate ──
    sp_validate = subparsers.add_parser("validate",
                                        help="Validación estricta YAML pre-commit")
    sp_validate.add_argument("target", type=str, nargs="?", default=None,
                             help="Archivo específico a validar (default: staged)")
    sp_validate.add_argument("--all", action="store_true", default=False,
                             help="Validar todos los conceptos del vault")

    # ── file-info ──
    sp_file_info = subparsers.add_parser("file-info", help="Metadatos de fecha de un concepto")
    sp_file_info.add_argument("--slug", type=str, required=True,
                              help="Slug del concepto (ej: 'frameworks/tp3-cibernetico')")
    sp_file_info.add_argument("--json", action="store_true", default=False,
                              help="Salida JSON")

    return parser


def main(argv=None):
    """Punto de entrada principal.

    Args:
        argv: Lista de argumentos (default: sys.argv[1:]).
              Útil para invocar programáticamente: main(["search", "--todos"])
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Resolver vault path
    from cli.vault import resolve_vault_path
    vault = resolve_vault_path(getattr(args, "vault", None))

    if not vault.exists():
        print(f"Error: vault no encontrado en {vault}", file=sys.stderr)
        print("Usa --vault o settea $OKF_VAULT para especificar otra ruta.", file=sys.stderr)
        sys.exit(1)

    # Cargar configuración externalizada
    from cli.config import Config
    config = Config(vault, cli_config_arg=getattr(args, "config", None))

    # Propagar exclusiones a las variables globales de vault.py (backward compat)
    from cli.vault import apply_config
    apply_config(config)

    # Asegurar que el directorio del CLI esté en path para imports
    cli_dir = Path(__file__).resolve().parent
    if str(cli_dir.parent) not in sys.path:
        sys.path.insert(0, str(cli_dir.parent))

    # Inicializar telemetría Cognitive Trace
    from cli.telemetry import init as telemetry_init, record as telemetry_record
    telemetry_init(vault, config)

    # Extraer params del namespace para telemetría (sin campos internos)
    _params = {k: v for k, v in vars(args).items()
               if k not in ("vault", "config", "command", "func") and v is not None
               and v != False and v != ""}

    # Despachar al comando con captura de stdout/stderr para telemetría
    import io as _io
    command = args.command
    _t0 = time.monotonic()
    _exit = 1
    _stdout_buf = _io.StringIO()
    _stderr_buf = _io.StringIO()
    _old_stdout, _old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = _stdout_buf, _stderr_buf

    try:
        if command == "search":
            from cli.commands.search import run
            _exit = run(args, vault, config) or 0

        elif command == "read":
            from cli.commands.read import run
            _exit = run(args, vault, config) or 0

        elif command == "traverse":
            from cli.commands.traverse import run
            _exit = run(args, vault, config) or 0

        elif command == "graph":
            from cli.commands.graph import run
            _exit = run(args, vault, config) or 0

        elif command == "health":
            from cli.commands.health import run
            _exit = run(args, vault, config) or 0

        elif command == "index":
            from cli.commands.index import run
            _exit = run(args, vault, config) or 0

        elif command == "new":
            from cli.commands.new import run
            _exit = run(args, vault, config) or 0

        elif command == "touch":
            from cli.commands.touch import run
            _exit = run(args, vault, config) or 0
        elif command == "trace":
            from cli.commands.trace import run
            _exit = run(args, vault, config) or 0

        elif command == "analytics":
            from cli.commands.analytics import run
            _exit = run(args, vault, config) or 0

        elif command == "dashboard":
            from cli.commands.dashboard import run
            _exit = run(args, vault, config) or 0

        elif command == "stale":
            from cli.commands.stale import run
            _exit = run(args, vault, config) or 0

        elif command == "session-metrics":
            from cli.commands.session_metrics import run
            _exit = run(args, vault, config) or 0

        elif command == "review":
            from cli.commands.review import run
            _exit = run(args, vault, config) or 0

        elif command == "audit":
            from cli.commands.audit import run
            _exit = run(args, vault, config) or 0

        elif command == "validate":
            from cli.commands.validate import run
            _exit = run(args, vault, config) or 0

        elif command == "file-info":
            from cli.commands.file_info import run
            _exit = run(args, vault, config) or 0

        else:
            print(f"Comando desconocido: {command}", file=sys.stderr)
            parser.print_help()
            sys.exit(1)
    finally:
        sys.stdout, sys.stderr = _old_stdout, _old_stderr
        _captured_out = _stdout_buf.getvalue()
        _captured_err = _stderr_buf.getvalue()
        # Re-emitir output a stdout/stderr real
        if _captured_out:
            _old_stdout.write(_captured_out)
        if _captured_err:
            _old_stderr.write(_captured_err)
        _duration_ms = int((time.monotonic() - _t0) * 1000)
        telemetry_record(f"okf_{command}", _params, _exit, _duration_ms, _captured_out, _captured_err)

    sys.exit(_exit)


if __name__ == "__main__":
    main()
