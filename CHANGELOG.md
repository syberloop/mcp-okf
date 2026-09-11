# Changelog

Todas las modificaciones notables al servidor MCP OKF. Formato basado en [Keep a Changelog](https://keepachangelog.com/).

---

## [2026-09-11] — v0.4.11

### Fixed
- **El index raíz ya no enlaza carpetas que no tienen `index.md`** (#22). `_generate_root_index` recorría toda carpeta de primer nivel (`_find_all_content_dirs`) y le escribía un enlace a `<carpeta>/index.md`, existiera o no; pero `index` sólo genera índices para las carpetas con conceptos (`_find_concept_dirs`). Una carpeta sin conceptos —un export, una captura, un respaldo— quedaba anunciada en el índice raíz con un enlace muerto, y en silencio: el aviso `MISSING DESCRIPTION` sólo se imprime cuando el `index.md` existe, y `health` no mira los enlaces markdown de los índices, sólo los wikilinks. Ahora una carpeta se lista únicamente si tiene `index.md` — a esa altura del `run` (paso 2) ese es exactamente el conjunto que `index` maneja. Una carpeta con `index.md` escrito a mano y sin conceptos se sigue listando igual que antes.
- `tests/test_index_raiz_sin_enlaces_muertos.py` (3 tests): todo enlace del index raíz apunta a un archivo que existe; una carpeta sin conceptos no aparece; una carpeta con `index.md` a mano se sigue listando. RED sobre master: 2 de los 3 fallan.

Tests: 290.

---

## [2026-09-10] — v0.4.10

### Added
- **La capa Cyber del plugin deja de estar muerta.** `cibernetica` ahora emite las cuatro listas por nodo que `dashboard_view.buildCyberNodes` esperaba desde el plan DashboardView y que el CLI nunca produjo: `review_on_vencidos_nodes`, `outcome_pending_nodes`, `outcome_success_nodes`, `outcome_failure_nodes`. El plugin las leía con `?? []`, así que la capa se renderizaba vacía sin error visible — el comentario del propio plugin decía «si el CLI las produce, la capa las colorea». Identificador: ruta relativa sin `.md`, igual que `conceptos[].file`. `review_on_vencidos_nodes` usa el mismo criterio que el agregado (`review_on < hoy`, sin mirar el outcome: un loop cerrado con fecha pasada también venció).
- `tests/test_dashboard_cyber_nodes.py` (6 tests): cada lista consistente con su contador, formato del identificador, y presencia de las claves en el `dashboard.json` escrito.

Tests: 287.

---

## [2026-09-10] — v0.4.9

### Fixed
- **Un review que vence HOY ya no cuenta como vencido en ningún sensor** (#21 + complemento). Tres componentes usaban dos semánticas distintas para la misma fecha: `health` marcaba «expired — broken loop» con `review_on <= hoy` (el mismo día del vencimiento, desde las 00:00), el agregado `cibernetica.review_on_vencidos` contaba `severity == 'required'` (o sea también los de hoy) y en cambio `conceptos[].cyber.vencido` usaba `review_on < hoy`. Un concepto con `outcome: pending` y `review_on` igual a hoy producía un snapshot con 1 vencido en el agregado y 0 en el nodo.
  - `health._check_cyber`: `review_on <= today` → `review_on < today` (#21). Loop roto pasa a significar vencido de verdad.
  - `review.collect_due`: cada ítem expone `vencido` (`review_on < hoy`). La lista de `review` sigue devolviendo los que vencen hoy — son tareas de hoy — y `severity` (required/verify) queda ortogonal a `vencido`.
  - `dashboard_snapshot`: `review_on_vencidos` cuenta `vencido`. Los que vencen hoy se cuentan aparte en la clave nueva `review_on_hoy` (aditiva; el plugin `cognitive-trace` ignora claves desconocidas, todavía no la renderiza).
  - `review` en modo humano marca los ítems que vencen hoy (`⏰ vence hoy`).
- Docstrings que afirmaban una semántica que el código no cumplía: `_cibernetica_section` («severity required = loop pendiente con fecha vencida») y `_cyber_por_nodo` («misma semántica que review.collect_due», falso para el caso «hoy»).

### Added
- `tests/test_review_vencimiento.py` (10 tests): fija la semántica única de fechas entre `collect_due`, el agregado del dashboard, el flag por nodo y la salida humana. Comprobado en las dos direcciones — con el agregado viejo fallan.

Tests: 281.

---

## [2026-09-10] — v0.4.8

### Added
- **`new` puede fijar el nombre del archivo y omitir `title`/timestamps** (tarjeta t_d661f16d). El pipeline de resúmenes de sesión era imposible de ejecutar solo con MCP y terminaba escribiendo el `.md` a mano, violando la regla "EXCLUSIVAMENTE `mcp__okf__*`" del propio agente resumidor.
  - `--filename <nombre>` (CLI) / `filename=` (MCP `okf_new`): usa el nombre exacto en vez de derivarlo del slug del título. Conserva mayúsculas, acentos y guiones bajos — antes `_slugify()` convertía `sesion-20260908_172301_5ef849fd` en `sesion-20260908-172301-5ef849fd`, así que la convención de `sesiones/` era inalcanzable. Acepta con o sin `.md`, exige un nombre simple (sin separadores de ruta: la carpeta la decide el type) y para `type=Skill` nombra el directorio de la skill.
  - `--field key=value` en `new` (repetible, solo claves top-level): campos extra de frontmatter con el mismo dialecto que `edit --field` (JSON para listas/dicts) — es lo que permite escribir `session_id` en el alta.
  - `--no-timestamps` (CLI) / `omit_timestamps=` (MCP): no escribe `timestamp:`/`created:`, para los formatos del vault que no los llevan. El health check 9 ya exime a `sesiones/` del warning de timestamp ausente.
  - El alta completa (nombre exacto + frontmatter del contrato + body) sale en UNA llamada `okf_new`: `type='Sesion'`, `filename='sesion-<session_id>.md'`, `fields=['session_id=<session_id>']`, `omit_timestamps=True`, `description=`, `body=`.

### Fixed
- **`title` es opcional en `new`** (antes obligatorio en CLI y en el schema MCP) y, si se omite, ya no se escribe la clave `title:` (antes `--title ''` dejaba `title: ""`). Sin `--filename` ni título, `new` falla con un error explícito: antes creaba literalmente `<tipo>/.md`.
- **`okf_new` valida `description`** con un mensaje claro en vez de delegar en el argparse del CLI.

### Deuda anotada
- `--field` en `new` solo acepta claves top-level y no admite claves repetidas; los bloques anidados siguen siendo territorio de `edit --field`.
- `edit` no puede eliminar el `title` (no hay `--clear-title`), así que un concepto creado con título no puede migrar al formato sin title sin reescribirlo.

Tests: 267.

---

## [2026-09-10] — v0.4.7

### Added
- **Límites de crecimiento de la telemetría** (PR #19, contribución de @nefast325-tech): el `event_log.jsonl` crecía sin techo (28,2 MB en el vault) y `sistema/dashboard-snapshots/` sumaba un snapshot completo por día para siempre.
  - `rotate_jsonl()` en `cli/telemetry.py`: al llegar a `JSONL_MAX_BYTES` (5 MB) el archivo se renombra a `<nombre>.1` (pisando el respaldo anterior) y el siguiente evento abre uno nuevo — en disco nunca hay más de ~2x el tope. Lo aplican los **dos** escritores (CLI y `server.py`).
  - `_prune_snapshots()` en `dashboard_snapshot.py`: conserva 30 días de snapshots diarios (solo `YYYY-MM-DD.json` con fecha válida; cualquier otro archivo de la carpeta queda intacto) y se aplica en cada `_write_snapshot`.
  - El plugin ya toleraba la rotación (detecta el achique y resetea el offset; el polling de 500 ms cubre el `fs.watch` sobre el inodo viejo) y el consumidor de snapshots lee exactamente los últimos 30 (`dashboard_view.ts` → `slice(-30)`), así que el 30 es coherente con quien lo consume. Verificado con el reader real del plugin antes del merge.
  - Tests: 11 nuevos (rotación, respaldo único, los dos escritores sin huecos, retención y archivos ajenos).
- **`readAll` por cola en el plugin** (PR #4 del repo `cognitive-trace`, misma tanda): la carga inicial pasó de leer el archivo entero (245 ms) a leer la cola (6 ms, 2,7% del archivo) con resultados idénticos. Acá no cambia código: el tope de 5 MB y la lectura por cola se complementan.

### Deuda anotada
- Los dos umbrales quedan hardcodeados: pasarlos a `.okf.config.yaml` es el issue **#20**.
- Los snapshots diarios no están versionados (`.gitignore`), así que la poda es irreversible: 30 días es la única copia.

## [2026-09-10] — v0.4.6

### Fixed
- **`new` generaba frontmatter inválido si el `title` o la `description` traían comillas dobles** (PR #18): interpolaba los valores entre comillas sin escapar, así que un concepto nuevo nacía ilegible — `edit` fallaba con `Invalid or missing frontmatter` sobre el archivo que el propio `new` acababa de crear, el health lo marcaba y el pre-commit bloqueaba el commit. Fix: `quote_yaml_scalar()` en `cli/frontmatter.py` (`json.dumps`, mismo criterio que `edit.py::_quote`), usada para `title`, `description` y `resource`. Se detectó creando un concepto cuya descripción citaba textualmente una decisión. Tests: 233.

### Deuda anotada
- La primitiva de quoting queda duplicada en `edit.py::_quote`, el escaping inline de `index.py` y el nuevo `quote_yaml_scalar`: `index.py` podría consumir el helper compartido.

## [2026-09-10] — v0.4.5

### Fixed
- **`v_node_events` no veía los `traverse` y `read` del CLI** (PR #13, contribución de @nefast325-tech): el server guarda el nodo en `params.slug` y el CLI (`traverse`/`read` con argumento posicional) y el harness dsh lo guardan en `params.target`; la vista solo leía `slug`, así que esos eventos nunca llegaban a `v_node_visits`. Ahora `COALESCE(slug, target)` con `target` aceptado solo en `traverse`/`read` (en `validate` es una ruta de archivo), en las **dos** definiciones de la vista (`cli/telemetry.py` y `server.py`). Medido sobre el `trace.db` del vault (17.587 eventos): +787 eventos visibles y `most_visited` deja de estar en blanco. Sin migración (`DROP VIEW IF EXISTS` al iniciar) y sin cambio de columnas.
- **`analytics node_timeline` fallaba siempre** (PR #16, issue #14): `SELECT ts, tool FROM v_node_events` sobre una vista que expone `tool_norm` → `sqlite3.OperationalError: no such column: tool` con cualquier argumento, y el render leía la misma clave inexistente.
- **`server.py` no era importable en una máquina sin `~/.hermes`** (PR #17): `_init_db()` corre en el import y el DB default es `~/.hermes/cognitive-trace.db` → `unable to open database file`, con el import de `server` cayéndose entero (2 módulos de tests no cargaban en CI). Se crea el directorio padre, igual que ya se hacía con el JSONL. Mismo arreglo en `cli/telemetry.py`, donde el `except` tapaba el fallo y **los eventos no se grababan** en una instalación limpia.
- **Test no hermético** `test_index_bajo_dir_excluido_no_se_valida` (PR #17): dependía del config ambiente (el vault real excluye `.dsh-build`). Ahora escribe su propio `.okf.config.yaml` y restaura los globales de `cli.vault`.

### Added
- **CI** (PR #17): GitHub Action en cada push a `master` y en cada PR, matriz 3.11/3.12 — `pip install -e .`, sanity check del CLI y `unittest discover` (227 tests). Antes los PRs se mergeaban sin ningún check automático, incluido el #13 de un contribuidor externo. El propio PR del workflow expuso los dos bugs de arriba.

### Version
- Se alinea el bump olvidado de **0.4.4**: el CHANGELOG lo documentaba (2026-08-29) pero `__version__` seguía en 0.4.3, así que `pip show`/`cli --version` reportaban una versión que no era la publicada.

Tests: 227.

## [2026-08-29] — v0.4.4

### Fixed
- **Pre-commit hook: falso positivo bloqueaba todos los commits por `LONG DESCRIPTION`**: el hook matcheaba `🚨` genérico en el stderr del indexer, confundiendo el warning informativo `🚨 LONG DESCRIPTION` (description >600 chars — el indexer trunca y sigue) con el error real `🚨 MISSING DESCRIPTION` (directorio sin description en index.md). Cualquier concept con description larga bloqueaba el commit de cualquiera. Fix: el hook ahora bloquea solo con `grep -q "MISSING DESCRIPTION"`. Además el hook se versiona en `hooks/pre-commit` (antes solo existía instalado en `.git/hooks/` del vault, sin fuente de verdad — por eso el bug pasó desapercibido).

## [2026-08-28] — v0.4.3

### Fixed
- **`edge_types`: normalización incompleta del #7** (PR #8): (1) `score_edge` no normalizaba — la señal estructural (0.40 de 0..1) se perdía para vaults con el vocabulario inglés del config de ejemplo (una arista caía de "fuerte" a "mediocre" solo por el idioma del nombre); (2) regresión del #7: se normalizaba la consulta pero no los `valid_pairs` declarados por el vault en su `.okf.config.yaml` — un par escrito en inglés nunca matcheaba. Fix: `_canonicalize_pairs` normaliza ambos lados de la comparación al resolver definiciones (sobre copias, sin mutar el config; `resolve_definitions(None)` sigue devolviendo la tabla embebida por identidad) y `score_edge` normaliza su consulta. Tests: `tests/test_edge_types_alias_completo.py`.

Tests: 153 + 44 subtests.

## [2026-08-28] — v0.4.2

### Fixed
- **`graph impact` contaba aristas como nodos y etiquetaba toda arista entrante como `depende`** (PR #6): el bloque de `depende` en `_cmd_impact` no tenía el guard `if etype != "depende": continue` que tienen los demás bloques — la salida mentía sobre la naturaleza de la relación y el total inflaba (2 aristas al mismo vecino = 4 "nodos impactados"). Fix: guard restaurado, `continue` suelto eliminado, agrupación por nodo (`_by_node`, conserva todas las razones) y `total` = nodos únicos. Tests: `tests/test_graph_impact.py`.
- **`edge_types` desalineado con el config de ejemplo traducido** (PR #7): `okf.config.example.yaml` usa el vocabulario inglés (Agent, Framework, Criterion, Lesson) pero `valid_pairs` quedó en español — 15 de 32 pares (47%) inalcanzables para un vault del ejemplo, con warnings de validación falsos y `suggest-edge-types` cayendo al centinela ("extiende", "BAJA"). Fix: `TYPE_ALIASES` + `canonical_type()` normalizando en la entrada de `suggest_edge_type` y `validate_cross_type_pair` (sin duplicar pares). Tests: `tests/test_edge_types_nombres.py`.

Tests: 147 + 36 subtests.

## [2026-08-28] — v0.4.1

### Changed
- **`touch` deprecado en modo incremento** (`touch <target>`): desde la migración de los read counters al store local (v0.3.0, `.okf/state/reads.jsonl`), `read` incrementa el contador automáticamente — `touch <target>` generaba doble conteo. Ahora es un no-op con warning explícito; el único modo soportado es `touch --all` (estadísticas de lectura). Tests: `tests/test_touch.py` (no-op con warning, store intacto, tabla, usage).
- **Versión dinámica en `pyproject.toml`**: `dynamic = ["version"]` con `attr = "cli.__version__"` — la versión ya no se hardcodea en dos lugares. Un único bump en `cli/__init__.py` y el paquete instalado (`pip show`) reporta lo mismo. Causa de fondo del fix del PR #3 (v0.4.0 quedó con pyproject en 0.3.1). `tests/test_version.py` protege el contrato: sin literal `version` en `[project]`, `dynamic` presente, `attr` apuntando a `cli.__version__`, y semver válido.

Tests: 135 verdes.

## [2026-08-28] — v0.4.0

### Added
- **Tool `mcp__okf__edit`** (comando CLI `edit`): update de conceptos con merge semantics — la vía canónica para actualizar (new es create-only y aborta con "Already exists"). Solo cambia los campos pasados (title, description, tags, status, resource, body, links), preserva type/created/cyber/campos custom y refresca `timestamp` (último cambio significativo, OKF v0.1). `--link` reemplaza la lista completa; `--clear-links` la vacía; `--dry-run` previsualiza. Validación de links idéntica a new (edge types, targets, duplicados, cross-type).
- **Tool `mcp__okf__todos`** (wrapper de `search --todos`): lista de tareas pendientes `- [ ]` agrupadas por proyecto. Nombre auto-descriptivo para el catálogo diferido — resuelve el caso real donde el agente respondía con health/review/stale ante "¿qué tareas hay pendientes?" (lección 2026-08-28, vaults OKF y skynet).
- **`new --force`**: sobrescribe si el slug ya existe (reemplazo total intencional).

### Changed
- Descripción de la tool `search`: la primera línea ahora incluye "pending tasks list (todos=true)" y remite a la tool dedicada `todos`.

### Fixed
- Serializador de frontmatter en `edit`: YAML 1.1 parsea timestamps ISO como `datetime`; `isoformat` preserva la "T" (con `str()` se perdía: "2026-01-01 00:00:00").

Tests: 123 verdes.

## [2026-08-27] — v0.3.1 (fix crítico)

### Fixed
- **`migrate-reads` truncaba el body de los conceptos**: `_fm_reads` reconstruía solo el frontmatter sin concatenar el contenido posterior. Ahora preserva el archivo completo (frontmatter editado + body). Tests de regresión: `test_migrate_preserves_body`, `test_increment_auto_migrate_preserves_body`.

## [2026-08-27] — v0.3.0

### Added
- **Read counters fuera del frontmatter** (decisión 2026-08-27): los counters viven en `<vault>/.okf/state/reads.jsonl` — append-only, NO versionado, con lock por archivo (`fcntl.flock`). El frontmatter queda 100% contenido; se elimina la fricción de merge en vaults multi-actor con sync automático.
- **`cli/reads_store.py`**: `get_reads`, `increment_reads`, `migrate_frontmatter_reads`, `find_vault`.
- **Comando `migrate-reads`**: migración en masa (siembra counters del frontmatter al store + limpia el campo) — un commit único por vault.

### Changed
- `frontmatter.increment_reads` delega al store; auto-migra el campo legacy `reads: N` al primer read (baseline + limpieza).
- `touch --all` lee del store (no del frontmatter).
- `no_touch` / `OKF_SESSION_PURPOSE=test` siguen evitando el incremento.

## [2026-08-27] — v0.2.0

### Added
- **Versionado del paquete**: `okf --version` (flag CLI); comparación con la última release en la tool `health` (informativa, no bloqueante).

### Fixed
- **Timestamp del frontmatter en `new`**: se generaba en UTC etiquetado como -05:00 (PR #1, 5h de desfase).
- **Directorio de sesiones en `session-metrics`**: salía de un literal `"sesiones"`; ahora lee `types.directory.Session` del config con fallback (PR #2).

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
