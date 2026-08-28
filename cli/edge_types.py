"""Formal definitions of semantic edge types for the OKF graph.

Each edge type has formal properties that the validator and suggester
use to detect category errors and infer missing types.

Properties:
    description  — what the edge means
    transitive   — whether A→B and B→C imply A→C (virtual edge, not written)
    symmetric    — whether A→B implies B→A (none currently is)
    inverse      — name of the inverse edge (e.g.: extiende ↔ es_extendido_por)
    valid_pairs  — valid (source_type, target_type) tuples.
                   Empty list = no restriction (applies to "corrige").
"""

import re
from typing import Optional

EDGE_TYPE_DEFINITIONS = {
    "extiende": {
        "description": "A agrega una dimensión nueva a B sin modificar su núcleo",
        "transitive": True,
        "symmetric": False,
        "inverse": "es_extendido_por",
        "valid_pairs": [
            ("Insight", "MarcoTeorico"),
            ("Research", "MarcoTeorico"),
            ("Plan", "Plan"),
            ("Plan", "MarcoTeorico"),
            ("Spec", "Spec"),
            ("Spec", "MarcoTeorico"),
            ("Decision", "Insight"),
            ("Decision", "Spec"),
        ],
    },
    "refina": {
        "description": "A precisa, acota o corrige el alcance de B sin invalidarlo",
        "transitive": False,
        "symmetric": False,
        "inverse": "es_refinado_por",
        "valid_pairs": [
            ("Decision", "Criterio"),
            ("Decision", "Spec"),
            ("Insight", "Insight"),
            ("Criterio", "Criterio"),
            ("Criterio", "Decision"),  # un criterio precisa la regla de la decisión que lo originó
            ("Spec", "Spec"),
            ("LeccionAprendida", "Insight"),  # una lección precisa el diagnóstico que la origina
        ],
    },
    "fundamenta": {
        "description": "A es base teórica o empírica de B — sin A, B pierde sustento",
        "transitive": True,
        "symmetric": False,
        "inverse": "es_fundamentado_por",
        "valid_pairs": [
            ("MarcoTeorico", "Decision"),
            ("MarcoTeorico", "Spec"),
            ("Research", "Plan"),
            ("Research", "Decision"),
            ("Insight", "Plan"),  # un diagnóstico fundamenta el plan que lo atiende (P3-2)
            ("LeccionAprendida", "Plan"),  # una lección fundamenta el plan que la instrumenta
        ],
    },
    "aplica": {
        "description": "A implementa, ejecuta o materializa B en un contexto concreto",
        "transitive": False,
        "symmetric": False,
        "inverse": "es_aplicado_por",
        "valid_pairs": [
            ("Plan", "Decision"),
            ("Plan", "Spec"),
            ("Plan", "MarcoTeorico"),
            ("Decision", "Criterio"),
            ("Spec", "MarcoTeorico"),
            ("Project", "Plan"),
            ("Workflow", "Spec"),
        ],
    },
    "depende": {
        "description": "A requiere B para existir o funcionar — si B desaparece, A se rompe",
        "transitive": True,
        "symmetric": False,
        "inverse": "es_prerequisito_de",
        "valid_pairs": [
            ("Agente", "Skill"),
            ("Skill", "Skill"),
            ("Spec", "Spec"),
            ("Plan", "Research"),
        ],
    },
    "corrige": {
        "description": "A reemplaza o invalida parte de B (alias formal de cyber.corrects)",
        "transitive": False,
        "symmetric": False,
        "inverse": "es_corregido_por",
        "valid_pairs": [],  # sin restricción — cualquier type puede corregir a cualquier type
    },
}

VALID_EDGE_TYPES = frozenset(EDGE_TYPE_DEFINITIONS.keys())


def resolve_definitions(definitions=None) -> dict:
    """Returns the effective edge-type definitions (config override or defaults).

    Args:
        definitions: Optional dict from config.edge_types. If None, uses the
                     embedded defaults (EDGE_TYPE_DEFINITIONS) — behavior
                     identical to vaults without configuration.

    Returns:
        dict: Effective EDGE_TYPE_DEFINITIONS-compatible dict.
    """
    if definitions is None:
        return EDGE_TYPE_DEFINITIONS
    return definitions


# Alias de nombres de tipo → nombre canónico usado en valid_pairs.
#
# El config de ejemplo se tradujo al inglés (commit 5e26f5d, 29-jul-2026) pero
# esta tabla quedó en el vocabulario anterior, y los pares agregados después
# siguieron usándolo. Un vault creado desde okf.config.example.yaml declara
# Agent / Framework / Criterion / Lesson, que no aparecen en ningún valid_pair:
# 15 de los 32 pares definidos quedaban inalcanzables.
#
# Se normaliza en la entrada en vez de duplicar los pares, para que agregar un
# par nuevo no exija acordarse de escribirlo dos veces.
TYPE_ALIASES = {
    "Agent": "Agente",
    "Framework": "MarcoTeorico",
    "Criterion": "Criterio",
    "Lesson": "LeccionAprendida",
}


def canonical_type(type_name: str) -> str:
    """Nombre canónico de un tipo, resolviendo alias de vocabulario."""
    return TYPE_ALIASES.get(type_name, type_name)


def suggest_edge_type(type_origen: str, type_destino: str,
                      definitions=None) -> tuple:
    """Suggests the most likely edge_type for a pair of types.

    Args:
        type_origen: Type of source node (e.g.: 'Insight').
        type_destino: Type of target node (e.g.: 'MarcoTeorico').
        definitions: Optional config-provided edge type definitions. If None,
                     uses the embedded defaults.

    Returns:
        tuple[str, str]: (edge_type, confidence) where confidence ∈ {"ALTA", "MEDIA", "BAJA"}.
        If no useful suggestion, returns ("extiende", "BAJA").
    """
    defs = resolve_definitions(definitions)
    par = (canonical_type(type_origen), canonical_type(type_destino))
    matches = []
    for etype, defn in defs.items():
        pairs = defn.get("valid_pairs", [])
        if par in pairs:
            matches.append(etype)

    if len(matches) == 1:
        return (matches[0], "ALTA")
    elif len(matches) > 1:
        return (matches[0], "MEDIA")
    else:
        return ("extiende", "BAJA")


def validate_cross_type_pair(type_origen: str, type_destino: str,
                              edge_type: str, definitions=None) -> list:
    """Validates a (source, target, edge_type) pair against EDGE_TYPE_DEFINITIONS.

    Returns list of warnings (empty if all OK). Validation is only
    for warnings — non-blocking.

    Args:
        type_origen: Type of source node (e.g.: 'Insight').
        type_destino: Type of target node (e.g.: 'MarcoTeorico').
        edge_type: Edge type (e.g.: 'extiende').
        definitions: Optional config-provided edge type definitions. If None,
                     uses the embedded defaults.

    Warnings include:
    - Unknown edge type.
    - Atypical pair: the (source_type, target_type) pair is not in valid_pairs.
    - Alternative type suggestion if one exists.
    """
    defs = resolve_definitions(definitions)
    warnings = []

    if edge_type not in defs:
        return [f"Tipo de arista desconocido: '{edge_type}'"]

    defn = defs[edge_type]
    valid_pairs = defn.get("valid_pairs", [])

    # corrige no tiene restricción de pares
    if not valid_pairs:
        return []

    if (canonical_type(type_origen), canonical_type(type_destino)) not in valid_pairs:
        # Buscar sugerencia de tipo alternativo
        alt_type, confidence = suggest_edge_type(
            type_origen, type_destino, definitions=definitions)
        if confidence in ("ALTA", "MEDIA") and alt_type != edge_type:
            warnings.append(
                f"Par atípico: '{type_origen}' {edge_type} '{type_destino}'. "
                f"¿Quisiste decir '{alt_type}'?"
            )
        else:
            warnings.append(
                f"Par atípico: '{type_origen}' {edge_type} '{type_destino}' "
                f"— no está en los pares válidos para '{edge_type}'."
            )

    return warnings


def _jaccard(set_a: set, set_b: set) -> float:
    """Jaccard coefficient between two sets. 0.0 if both empty."""
    union = len(set_a | set_b)
    if union == 0:
        return 0.0
    return len(set_a & set_b) / union


def _desc_overlap(desc_a: str, desc_b: str) -> float:
    """Overlap of significant terms (≥4 chars, no stopwords) between two descriptions.

    Uses word bigrams to capture short phrases in addition to individual terms.
    Returns 0.0-1.0.
    """
    if not desc_a or not desc_b:
        return 0.0

    stopwords = {
        "para", "como", "una", "los", "las", "del", "que", "por", "con",
        "sin", "mas", "sus", "entre", "sobre", "desde", "hasta", "cada",
        "este", "esta", "esto", "pero", "tambien", "tiene", "hace",
        "the", "and", "for", "that", "with", "from", "this", "are",
        "not", "but", "its", "can", "has", "have", "will",
    }

    def _terms(text: str) -> set:
        words = re.findall(r"[a-záéíóúñ]{4,}", text.lower())
        filtered = [w for w in words if w not in stopwords]
        # Unigrams + bigrams
        unigrams = set(filtered)
        bigrams = {
            f"{filtered[i]}_{filtered[i+1]}"
            for i in range(len(filtered) - 1)
        }
        return unigrams | bigrams

    terms_a = _terms(desc_a)
    terms_b = _terms(desc_b)
    return _jaccard(terms_a, terms_b)


def score_edge(
    source_type: str,
    target_type: str,
    edge_type: str,
    source_tags: list,
    target_tags: list,
    source_desc: str,
    target_desc: str,
    precedent_ratio: float = 0.0,
    definitions=None,
) -> float:
    """Numeric score 0.0-1.0 for a typed edge based on 4 semantic signals.

    Args:
        source_type: Type of source node (e.g.: 'Insight').
        target_type: Type of target node (e.g.: 'MarcoTeorico').
        edge_type: Edge type (e.g.: 'extiende').
        source_tags: List of tags of source node.
        target_tags: List of tags of target node.
        source_desc: Description of source node.
        target_desc: Description of target node.
        precedent_ratio: Ratio 0.0-1.0 of precedents in the graph
                        (how many other nodes with the same type-pair use this edge_type).
        definitions: Optional config-provided edge type definitions. If None,
                     uses the embedded defaults.

    Returns:
        float: Score 0.0-1.0 where >0.7 is strong, <0.4 is weak.

    Signals:
        1. Structural fit (0.40): is the pair in the edge_type's valid_pairs?
        2. Tag overlap (0.25): Jaccard between source and target tags.
        3. Description similarity (0.20): Overlap of significant terms.
        4. Graph precedent (0.15): Precedents in the graph.
    """
    defs = resolve_definitions(definitions)
    score = 0.0

    # 1. Structural fit (0.40)
    if edge_type in defs:
        defn = defs[edge_type]
        valid_pairs = defn.get("valid_pairs", [])
        if not valid_pairs:  # 'corrige' — sin restricción
            score += 0.40
        elif (source_type, target_type) in valid_pairs:
            score += 0.40
        # Par no válido → 0.0 en esta señal

    # 2. Tag overlap (0.25)
    src_tags = {str(t).strip().lower() for t in (source_tags or []) if t}
    tgt_tags = {str(t).strip().lower() for t in (target_tags or []) if t}
    tag_jaccard = _jaccard(src_tags, tgt_tags)
    score += 0.25 * tag_jaccard

    # 3. Description similarity (0.20)
    desc_sim = _desc_overlap(source_desc or "", target_desc or "")
    score += 0.20 * desc_sim

    # 4. Graph precedent (0.15)
    score += 0.15 * min(precedent_ratio, 1.0)

    return round(score, 2)
