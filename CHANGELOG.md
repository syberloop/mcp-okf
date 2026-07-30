# Changelog

All notable changes to the MCP OKF server. Uses [Keep a Changelog](https://keepachangelog.com/) format.

## [Unreleased]

### Added
- **Scoring semántico para aristas tipadas** (`score_edge`): puntaje numérico 0.0–1.0 basado en 4 señales — structural fit (0.40), tag Jaccard overlap (0.25), description similarity (0.20), graph precedent (0.15).
- `build_graph()` incluye campo `score` en `typed_out`/`typed_in`.
- `graph impact` usa score para granularidad fina (≥0.7→🔴, 0.4–0.69→🟡, <0.4→🔵) en vez de buckets fijos por tipo.
- `traverse` ordena vecindario por score descendente y muestra score en salida (`via extiende (0.61) ←`).
- `graph backlinks`, `deps` y `dump` muestran scores (`[extiende:0.57]`).

## [2026-07-29]

### Added
- `search --with-graph`: detecta aristas tipadas entre resultados y las incluye en la salida (Nivel 2 de mejoras al motor de búsqueda semántica).
- Sugerencia ontológica en `traverse`: cuando no se usa `--edge-type`, sugiere filtrar si hay aristas tipadas en la travesía.
- Vocabulario `edge_types` expandido en AGENTS.md.

### Fixed
- `graph backlinks` y `deps` con `--edge-type` ahora filtran correctamente.

### Changed
- README traducido a inglés + `okf.config.example.yaml` documentado.

## [2026-07-24]

### Fixed
- `search --todos` ya no genera `result_nodes` vacíos (rompía Cognitive Trace).
- `OKF_MCP_CALLER` se aplica también en reruns de `_extract_result_nodes`.
- Eventos duplicados CLI+MCP eliminados en JSONL.
- Prefijo `okf_` restaurado en `tool_name` para eventos JSONL.

## [2026-07-23]

### Added
- Nuevo type `Mapa` → directorio `mapas/`.
- `okf.config.example.yaml` con quick start para publicación open-source.

### Changed
- Revert renaming: código vuelve a `OKF`. Syberloop es solo la marca.

### Removed
- Prefijo `okf_` redundante eliminado de nombres de herramienta (revertido 2026-07-24).

## [2026-07-22]

### Added
- **`okf_trace`**: rastrea referencias a un término en 5 capas — vault (wikilinks), code (Python MCP server), hooks (git), cron (jobs), agents (AGENTS.md).

### Fixed
- Paths de skills y headings corregidos para post-commit hook.

## [2026-07-21]

### Added
- Instalable como paquete pip (`pip install .`).

### Fixed
- `CLAUDE.md` → `AGENTS.md` en `DEFAULT_EXCLUDE_FILES`.

## [2026-07-20]

### Added
- **`okf_session_metrics`**: métricas agregadas de todas las sesiones (tools, conceptos, commits, infracciones MCP).
- **`okf_file_info`**: metadatos de fecha de un concepto (created git, updated git, timestamp FM, created FM).
- Campo `created` en frontmatter (fecha de creación OKF).
- `search --since` / `search --until`: filtrar conceptos por rango de timestamp.
- `okf_new --body`: crear concepto con body completo en una sola llamada.
- Health check #9: timestamp coherence vs git creation date.
- Nuevo type `Criterio` → directorio `criterios/`.
- Externalización de configuración (Fases 1–4): `.okf.config.yaml` con taxonomía, umbrales y feature flags.

### Fixed
- `validate`: timestamp ahora es obligatorio.
- `validate`: limpia inline code en check de wikilinks malformados.
- Health check #9: timestamp coherence usa tolerancia ±1 día, no exact match (77→3 warnings).
- Comillas en timestamp se limpian antes de `fromisoformat`.
- `CLAUDE.md` defaults eliminados, `problem_patterns` parametrizable, paths de trace configurables.
