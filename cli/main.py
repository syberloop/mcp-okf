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
                           help="Con --todos: mostrar antigüedad vía git blame")
    sp_search.add_argument("--json", action="store_true", default=False,
                           help="Salida JSON")
    sp_search.add_argument("--cyber-field", type=str, default=None,
                           help="Filtrar por campo cyber: (sensor, outcome, etc.)")
    sp_search.add_argument("--cyber-value", type=str, default=None,
                           help="Valor del campo --cyber-field")
    sp_search.add_argument("--review-due", action="store_true", default=False,
                           help="Solo conceptos con cyber.review_on <= hoy")

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
    sp_traverse.add_argument("target", type=str, help="Concepto origen")
    sp_traverse.add_argument("--depth", type=int, default=1,
                             help="Profundidad de travesía (default: 1)")
    sp_traverse.add_argument("--direction", type=str, default="both",
                             choices=["both", "out", "in"],
                             help="Dirección: both, out, in (default: both)")
    sp_traverse.add_argument("--no-cyber", action="store_true", default=False,
                             help="No seguir aristas cyber.corrects/corrected_by")
    sp_traverse.add_argument("--json", action="store_true", default=False,
                             help="Salida JSON")

    # ── graph ──
    sp_graph = subparsers.add_parser("graph", help="Analizar el grafo de wikilinks")
    sp_graph.add_argument("subcommand", nargs="?", type=str,
                          help="stats|orphans|hubs|backlinks|deps|tags|bridges|cluster|path|dump|dirs|types")
    sp_graph.add_argument("args", nargs="*", type=str,
                          help="Argumentos adicionales para el subcomando")

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

    # ── touch ──
    sp_touch = subparsers.add_parser("touch", help="Estadísticas de lecturas")
    sp_touch.add_argument("target", nargs="?", type=str, help="Concepto a incrementar")
    sp_touch.add_argument("--all", action="store_true", default=False,
                          help="Mostrar stats de todos los conceptos")

    # ── dashboard ──
    sp_dash = subparsers.add_parser("dashboard", help="Generar dashboard.md")

    # ── stale ──
    sp_stale = subparsers.add_parser("stale", help="Detector de obsolescencia semántica")
    sp_stale.add_argument("--json", action="store_true", default=False,
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

    # Asegurar que el directorio del CLI esté en path para imports
    cli_dir = Path(__file__).resolve().parent
    if str(cli_dir.parent) not in sys.path:
        sys.path.insert(0, str(cli_dir.parent))

    # Despachar al comando
    command = args.command

    if command == "search":
        from cli.commands.search import run
        sys.exit(run(args, vault))

    elif command == "read":
        from cli.commands.read import run
        sys.exit(run(args, vault))

    elif command == "traverse":
        from cli.commands.traverse import run
        sys.exit(run(args, vault))

    elif command == "graph":
        from cli.commands.graph import run
        sys.exit(run(args, vault))

    elif command == "health":
        from cli.commands.health import run
        sys.exit(run(args, vault))

    elif command == "index":
        from cli.commands.index import run
        sys.exit(run(args, vault))

    elif command == "new":
        from cli.commands.new import run
        sys.exit(run(args, vault))

    elif command == "touch":
        from cli.commands.touch import run
        sys.exit(run(args, vault))

    elif command == "dashboard":
        from cli.commands.dashboard import run
        sys.exit(run(args, vault))

    elif command == "stale":
        from cli.commands.stale import run
        sys.exit(run(args, vault))

    elif command == "review":
        from cli.commands.review import run
        sys.exit(run(args, vault))

    elif command == "audit":
        from cli.commands.audit import run
        sys.exit(run(args, vault))

    elif command == "validate":
        from cli.commands.validate import run
        sys.exit(run(args, vault))

    else:
        print(f"Comando desconocido: {command}", file=sys.stderr)
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
