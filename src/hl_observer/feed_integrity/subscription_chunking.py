"""[DATA lot2 #28] SUBSCRIPTION CHUNKING AUTOMATIQUE : découper automatiquement les subscriptions selon la limite
RÉELLE de chaque WS (une venue accepte X symboles par connexion). Envoyer plus que la limite fait rejeter ou couper
la connexion. On chunke en lots ≤ limite. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def decouper(symboles: Sequence[Any], *, max_par_chunk: int) -> dict[str, Any]:
    """Découpe la liste de symboles en chunks de taille ≤ max_par_chunk. max invalide → UNMEASURABLE."""
    if not isinstance(max_par_chunk, int) or max_par_chunk <= 0:
        return {"chunks": "UNMEASURABLE", "raison": "LIMITE_INVALIDE"}
    xs = list(symboles)
    chunks = [xs[i:i + max_par_chunk] for i in range(0, len(xs), max_par_chunk)]
    return {"chunks": chunks, "n_chunks": len(chunks), "max_par_chunk": max_par_chunk,
            "tous_sous_limite": all(len(c) <= max_par_chunk for c in chunks)}


__all__ = ["decouper"]
