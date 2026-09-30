"""[AUD-277/278/292/293/294/295/296/297] Data Mesh : registre CENTRAL des sources (statut
REQUIRED/OPTIONAL/DEGRADED, licence, cout API, score de qualite), lineage source->dataset, ablation
de sources (valeur marginale nette) et controle de FREQUENCE (une source lente ne doit pas etre
sur-echantillonnee en douce = fuite). stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

from typing import Callable, Mapping, Sequence

REQUIRED = "REQUIRED"
OPTIONAL = "OPTIONAL"
DEGRADED = "DEGRADED"
_STATUTS = (REQUIRED, OPTIONAL, DEGRADED)


class DataMesh:
    """Registre CENTRAL des sources de donnees. Chaque source porte statut, licence, cout API et
    score de qualite ; le lineage relie chaque dataset a ses sources. Un seul endroit fait autorite."""

    def __init__(self) -> None:
        self._sources: dict[str, dict] = {}
        self._lineage: dict[str, list] = {}

    def enregistrer(self, nom: str, *, statut: str = OPTIONAL, licence: str = "inconnue",
                    cout_api_usd: float = 0.0, qualite: float = 0.0) -> None:
        if statut not in _STATUTS:
            raise ValueError("statut invalide: %s" % statut)
        self._sources[nom] = {"nom": nom, "statut": statut, "licence": licence,
                              "cout_api_usd": float(cout_api_usd), "qualite": float(qualite)}

    def declarer_lineage(self, dataset: str, sources: Sequence[str]) -> None:
        self._lineage[dataset] = list(sources)

    def sources_par_statut(self, statut: str) -> list[str]:
        return sorted(n for n, s in self._sources.items() if s["statut"] == statut)

    def requises_presentes(self, disponibles: Sequence[str]) -> dict:
        manquantes = sorted(set(self.sources_par_statut(REQUIRED)) - set(disponibles))
        return {"ok": len(manquantes) == 0, "manquantes": manquantes}

    def cout_total_api(self) -> float:
        return round(sum(s["cout_api_usd"] for s in self._sources.values()), 6)

    def registre(self) -> dict:
        return {n: dict(s) for n, s in self._sources.items()}

    def lineage(self, dataset: str) -> list:
        return list(self._lineage.get(dataset, []))


def ablation_sources(sources: Sequence[str], evaluer_sans: Callable[[frozenset], float]) -> list[dict]:
    """Ablation de SOURCES : perf de reference vs perf en RETIRANT chaque source -> valeur marginale
    NETTE. Une source dont le retrait ne change rien ne justifie ni son cout ni sa licence."""
    ref = float(evaluer_sans(frozenset()))
    out = [{"source": s, "perf_sans": float(evaluer_sans(frozenset([s])))} for s in sources]
    for d in out:
        d["valeur_marginale"] = ref - d["perf_sans"]
    out.sort(key=lambda d: d["valeur_marginale"], reverse=True)
    return out


def verifier_frequence(timestamps: Sequence[float], *, periode_attendue_s: float, tolerance: float = 0.5) -> dict:
    """Une source LENTE (macro) ne doit pas apparaitre plus vite que sa frequence declaree : sinon
    c'est un carry-forward/sur-echantillonnage qui injecte de la fausse information (look-ahead)."""
    if len(timestamps) < 2:
        return {"ok": True, "n_trop_rapide": 0, "periode_attendue_s": periode_attendue_s}
    seuil = periode_attendue_s * (1.0 - tolerance)
    deltas = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
    trop_rapide = [d for d in deltas if d < seuil]
    return {"ok": len(trop_rapide) == 0, "n_trop_rapide": len(trop_rapide),
            "periode_attendue_s": periode_attendue_s}
