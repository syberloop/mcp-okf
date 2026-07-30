"""Definiciones formales de tipos de arista semántica para el grafo OKF.

Cada tipo de arista tiene propiedades formales que el validador y el suggester
usan para detectar errores de categoría e inferir tipos faltantes.

Propiedades:
    description  — qué significa la arista
    transitive   — si A→B y B→C implican A→C (arista virtual, no escrita)
    symmetric    — si A→B implica B→A (ninguna lo es actualmente)
    inverse      — nombre de la arista inversa (ej: extiende ↔ es_extendido_por)
    valid_pairs  — tuplas (type_origen, type_destino) válidas.
                   Lista vacía = sin restricción (aplica para "corrige").
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
            ("Spec", "Spec"),
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


def suggest_edge_type(type_origen: str, type_destino: str) -> tuple:
    """Sugiere el edge_type más probable para un par de types.

    Args:
        type_origen: Type del nodo origen (ej: 'Insight').
        type_destino: Type del nodo destino (ej: 'MarcoTeorico').

    Returns:
        tuple[str, str]: (edge_type, confianza) donde confianza ∈ {"ALTA", "MEDIA", "BAJA"}.
        Si no hay sugerencia útil, retorna ("extiende", "BAJA").
    """
    matches = []
    for etype, defn in EDGE_TYPE_DEFINITIONS.items():
        pairs = defn.get("valid_pairs", [])
        if (type_origen, type_destino) in pairs:
            matches.append(etype)

    if len(matches) == 1:
        return (matches[0], "ALTA")
    elif len(matches) > 1:
        return (matches[0], "MEDIA")
    else:
        return ("extiende", "BAJA")


def validate_cross_type_pair(type_origen: str, type_destino: str,
                              edge_type: str) -> list:
    """Valida un par (origen, destino, edge_type) contra EDGE_TYPE_DEFINITIONS.

    Retorna lista de warnings (vacía si todo OK). La validación es solo
    para warnings — no bloqueante.

    Los warnings incluyen:
    - Tipo de arista desconocido.
    - Par atípico: el par (origen_type, destino_type) no está en valid_pairs.
    - Sugerencia de tipo alternativo si existe.
    """
    warnings = []

    if edge_type not in EDGE_TYPE_DEFINITIONS:
        return [f"Tipo de arista desconocido: '{edge_type}'"]

    defn = EDGE_TYPE_DEFINITIONS[edge_type]
    valid_pairs = defn.get("valid_pairs", [])

    # corrige no tiene restricción de pares
    if not valid_pairs:
        return []

    if (type_origen, type_destino) not in valid_pairs:
        # Buscar sugerencia de tipo alternativo
        alt_type, confidence = suggest_edge_type(type_origen, type_destino)
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
    """Coeficiente de Jaccard entre dos sets. 0.0 si ambos vacíos."""
    union = len(set_a | set_b)
    if union == 0:
        return 0.0
    return len(set_a & set_b) / union


def _desc_overlap(desc_a: str, desc_b: str) -> float:
    """Overlap de términos significativos (≥4 chars, sin stopwords) entre dos descripciones.

    Usa bigramas de palabras para capturar frases cortas además de términos individuales.
    Retorna 0.0-1.0.
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
) -> float:
    """Score numérico 0.0-1.0 para una arista tipada basado en 4 señales semánticas.

    Args:
        source_type: Type del nodo origen (ej: 'Insight').
        target_type: Type del nodo destino (ej: 'MarcoTeorico').
        edge_type: Tipo de arista (ej: 'extiende').
        source_tags: Lista de tags del nodo origen.
        target_tags: Lista de tags del nodo destino.
        source_desc: Description del nodo origen.
        target_desc: Description del nodo destino.
        precedent_ratio: Ratio 0.0-1.0 de precedentes en el grafo
                        (cuántos otros nodos con el mismo type-pair usan este edge_type).

    Returns:
        float: Score 0.0-1.0 donde >0.7 es fuerte, <0.4 es débil.

    Señales:
        1. Structural fit (0.40): ¿el par está en valid_pairs del edge_type?
        2. Tag overlap (0.25): Jaccard entre tags de source y target.
        3. Description similarity (0.20): Overlap de términos significativos.
        4. Graph precedent (0.15): Precedentes en el grafo.
    """
    score = 0.0

    # 1. Structural fit (0.40)
    if edge_type in EDGE_TYPE_DEFINITIONS:
        defn = EDGE_TYPE_DEFINITIONS[edge_type]
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
