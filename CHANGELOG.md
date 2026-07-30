# Changelog

Todas las modificaciones notables al servidor MCP OKF. Formato basado en [Keep a Changelog](https://keepachangelog.com/).

---

## [2026-07-30]

### Added
- **Scoring semántico para aristas tipadas** (`score_edge`): cada arista declarada en `links:` recibe un puntaje numérico 0.0–1.0 basado en 4 señales ponderadas:
  - *Structural fit* (0.40): qué tan típico es el par `(tipo_origen, tipo_destino)` para el `edge_type` declarado, según una matriz de frecuencia construida desde el grafo real.
  - *Tag Jaccard overlap* (0.25): solapamiento de tags entre origen y destino — aristas entre nodos con tags compartidos reciben score más alto.
  - *Description similarity* (0.20): similitud coseno entre vectores TF-IDF de las descripciones.
  - *Graph precedent* (0.15): bonus si ya existen aristas del mismo tipo entre nodos del mismo par de tipos.
- `build_graph()` incluye campo `score` en `typed_out` y `typed_in` de cada nodo.
- `graph impact` clasifica impacto por score en vez de buckets fijos por tipo de arista: ≥0.7 → 🔴 crítico, 0.4–0.69 → 🟡 moderado, <0.4 → 🔵 bajo.
- `traverse` ordena vecindario por score descendente y muestra score inline: `via extiende (0.61) ←`.
- `graph backlinks`, `deps` y `dump` muestran scores en formato `[extiende:0.57]`.

### Docs
- CHANGELOG.md: registro histórico completo del proyecto desde el commit inicial.

---

## [2026-07-29]

### Added
- **Búsqueda semántica Nivel 2**: `search --with-graph` detecta aristas tipadas entre los resultados de búsqueda y las incluye en una sección `## Relaciones detectadas`. Esto le da al LLM conciencia inmediata de cómo se conectan los resultados entre sí, sin necesidad de traverses adicionales.
- **Sugerencia ontológica en `traverse`**: cuando una travesía retorna aristas tipadas pero no se usó `--edge-type`, el output sugiere explícitamente filtrar por tipo con el comando exacto a ejecutar. Elimina la fricción de descubrir edge types manualmente.
- Vocabulario `edge_types` expandido en AGENTS.md: tabla de verbos de consulta → edge_type con ejemplos concretos, heurística de clasificación obligatoria antes de traverse.

### Fixed
- `graph backlinks` y `deps` con `--edge-type` ahora filtran correctamente. Antes el filtro no se aplicaba en absoluto por un bug en la construcción del grafo invertido.

### Changed
- README traducido a inglés + `okf.config.example.yaml` documentado como quick start.

### Removed
- `discover` command (búsqueda híbrida search + traverse, Nivel 3): revertido por complejidad innecesaria. El patrón search → with-graph cubre el mismo caso de uso con menos superficie de API.

---

## [2026-07-24]

### Fixed
- `search --todos` ya no genera `result_nodes` vacíos que rompían el plugin Cognitive Trace en Obsidian. El bug ocurría porque las tareas pendientes no tienen slug de archivo asociado.
- `OKF_MCP_CALLER` se aplica también en reruns de `_extract_result_nodes`, garantizando trazabilidad correcta incluso cuando el parser se ejecuta múltiples veces por request.
- Eventos duplicados CLI+MCP eliminados del trace JSONL. El wrapper MCP llamaba al CLI y ambos escribían eventos independientes, duplicando cada operación en el log.
- Prefijo `okf_` restaurado en `tool_name` para eventos JSONL (revertido el remove del 2026-07-23). El Cognitive Trace esperaba este prefijo para filtrar eventos del plugin.

---

## [2026-07-23]

### Added
- Nuevo type `Mapa` → directorio `mapas/`. Para documentos que representan mapas conceptuales, diagramas de arquitectura, o vistas panorámicas del grafo de conocimiento.
- `okf.config.example.yaml`: template de configuración con quick start para nuevos vaults que adopten OKF. Documenta taxonomía, umbrales, y feature flags disponibles.

### Changed
- **Revert renaming**: código vuelve a `OKF`. Syberloop queda como marca exclusivamente. La decisión de renombrar fue prematura — OKF ya tenía tracción como estándar en el ecosistema.

### Removed
- Prefijo `okf_` redundante eliminado de nombres de herramienta MCP (revertido al día siguiente, ver 2026-07-24).

---

## [2026-07-22]

### Added
- **`okf_trace`**: rastrea referencias a un término en 5 capas del ecosistema — vault (wikilinks + contenido), code (Python del MCP server), hooks (git), cron (jobs), agents (AGENTS.md). Herramienta de infraestructura: antes de renombrar, eliminar o mover cualquier componente, responde "¿dónde se menciona X?" en todas las capas donde el sistema tiene memoria.

### Fixed
- Paths de skills y headings corregidos en el post-commit hook. Tras la migración de `sistema/skills/` a `skills/`, el hook seguía apuntando a rutas viejas y fallaba silenciosamente.
- `CLAUDE.md` → `AGENTS.md` en `DEFAULT_EXCLUDE_FILES` de `vault.py` para evitar que el archivo de instrucciones del agente se indexe como concepto del vault.

---

## [2026-07-21]

### Added
- **Instalable como paquete pip**: `pip install .` funciona. Permite usar `python3 -m cli` desde cualquier directorio sin depender de la ubicación física del repo. El `setup.py` / `pyproject.toml` expone el CLI como entry point.

### Docs
- README con setup completo: instalación, dependencia de `$OKF_VAULT_PATH`, y advertencia explícita de que los argumentos de path deben ser absolutos (no relativos al CWD del proceso).

---

## [2026-07-20]

### Added
- **Externalización de configuración Fases 1-4** (`cli/config.py`): clase `Config` con cadena de resolución `--config > $OKF_CONFIG > .okf.config.yaml > defaults`. 14 comandos migrados a firma `run(args, vault, config=None)`. Lo que se externalizó:
  - Taxonomía: `VALID_TYPES`, `TYPE_DIR`, `BODY_TEMPLATES` (permite a cada vault definir sus propios tipos de concepto sin modificar el código).
  - Umbrales: timestamps, propuestas fantasma, antigüedad de commits, checkboxes abiertos (parametrizables por vault).
  - Feature flags: `cognitive_trace` (ON/OFF), `plugin_hash_sync` (condicional).
  - Exclusiones: `DEFAULT_EXCLUDE_FILES`, `problem_patterns`, paths de trace.
  - Backward compatible: sin `.okf.config.yaml`, comportamiento idéntico al anterior.
- **`okf_session_metrics`**: métricas agregadas de todas las sesiones del vault — tools usadas, conceptos creados, commits, infracciones MCP. Extrae datos de la sección `## Métricas` de cada resumen de sesión.
- **`okf_new --body`**: crea concepto con body completo en una sola llamada MCP. Antes requería crear el archivo y luego editarlo con `write_file` o `patch`.
- **`okf_file_info`**: metadatos de fecha de un concepto — `created` (primer commit git), `updated` (último commit git), `timestamp` (frontmatter), `created_fm` (fecha de creación OKF). Útil para auditoría de frescura sin leer el body completo.
- **`okf_stale`**: expone el detector de obsolescencia semántica como tool MCP nativa. Antes solo accesible vía CLI. Evalúa 7 señales (timestamp, reads, propuesta fantasma, huérfanos, commits, decisión sin status, descripción vs body) y clasifica cada concepto como STALE (3+), ATENCIÓN (1-2) o FRESCO (0). El cron job de staleness migró de `terminal` a esta tool.
- Campo `created` en frontmatter: fecha de creación del concepto en el vault OKF, independiente del git creation date.
- `search --since` / `search --until`: filtrar conceptos por rango de timestamp en frontmatter.
- Health check #9: timestamp coherence — verifica que el `timestamp` en frontmatter sea coherente con la fecha de creación en git (tolerancia ±1 día).
- Health check #10: `plugin_hash_sync` — compara hash de la spec del plugin Cognitive Trace con el plugin instalado en Obsidian.
- Nuevo type `Criterio` → directorio `criterios/`. Para decisiones que establecen reglas, heurísticas o estándares que otras decisiones deben satisfacer.
- Nuevo type `Workflow` → directorio `workflows/`. Plantillas de automatización portables entre vaults: secuencias de pasos, tools requeridas, y criterios de éxito.

### Fixed
- `validate`: timestamp ahora es obligatorio (antes opcional, causaba health check #9 irrelevante).
- `validate`: limpia inline code (backticks) en check de wikilinks malformados para evitar falsos positivos.
- Health check #9 usa tolerancia ±1 día, no exact match — redujo falsos warnings de 77 a 3 en el vault de Jaime.
- Comillas en timestamp se limpian antes de `fromisoformat()` para evitar crashes por valores como `"2026-07-20"`.
- `CLAUDE.md` defaults eliminados del código; `problem_patterns` y paths de trace ahora son configurables.
- Warnings de `index.py`: mensajes en mayúsculas con instrucción concreta (`AGREGAR description`, `¡TRUNCAR!`) y conteo de chars/máx para descriptions largas.

---

## [2026-07-19]

### Added
- **Commit inicial**: servidor MCP + CLI para gestión de vaults OKF. 11 tools MCP nativas:
  - `okf_traverse`: travesía semántica del grafo de wikilinks con profundidad configurable y dirección `in`/`out`/`both`.
  - `okf_search`: búsqueda FTS5 con filtros por type, status, campos cyber, y tareas pendientes.
  - `okf_read`: lectura de conceptos con contador de reads auto-incremental.
  - `okf_new`: creación de conceptos con frontmatter consistente (type, title, description, tags, status, cyber).
  - `okf_health`: diagnóstico de 8 verificaciones (frontmatter, índices, grafo, links rotos, scripts, git hook, bloque cyber, plugin sync).
  - `okf_graph`: análisis del grafo — stats, orphans, hubs, backlinks, deps, tags, bridges, cluster, dump.
  - `okf_touch`: estadísticas de lecturas con contadores y barras de frecuencia.
  - `okf_index`: regeneración de `index.md` y `log.md` para todos los directorios del vault.
  - `okf_review`: escaneo de conceptos con `cyber.review_on` vencido.
  - `okf_analytics`: consultas sobre eventos de trace — most_visited, session_heatmap, tool_usage, etc.
  - `okf_graph_command`: comandos al plugin Cognitive Trace en Obsidian vía JSONL (highlight, focus, reset).
- **Arquitectura**: separación CLI/MCP. El CLI (`cli/`) es Python puro stdlib, cero dependencias externas. El server MCP (`server.py`) wrappea el CLI como tools nativas del protocolo MCP. Mismos resultados, cero fricción de shell.
- **Persistencia de paths**: `okf_new` y `okf_index` retornan el path absoluto del archivo creado, permitiendo al agente verificarlo con `read_file` sin inferir la ruta.
- **Fortalecimiento MCP**: manejo de errores robusto en el server — excepciones del CLI se capturan y retornan como texto estructurado en lugar de crashes silenciosos. Tests iniciales (`tests/test_server.py`).
- **Graph `dirs` + `types`**: `graph dirs` muestra árbol de directorios con conteo de conceptos por carpeta. `graph types` muestra distribución por type con barras de frecuencia. `traverse` output incluye ruta completa (`carpeta/nombre.md`) en cada nodo del vecindario.
