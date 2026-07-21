"""BOUCLE /GOAL DU REPLAY (S1, article Roan) — itérer la recherche JUSQU'À une condition
EXTERNE vérifiable. Jamais « l'agent dit que c'est fini ».

CE QUE C'EST
------------
L'orchestrateur qui manquait au-dessus des briques existantes : `ab_flag_replay` évalue UNE
configuration ; cette boucle en enchaîne PLUSIEURS et ne s'arrête que sur l'un des trois
arrêts VÉRIFIABLES DE L'EXTÉRIEUR :

  * PROMU          — la PORTE (fonction de jugement indépendante de l'évaluateur) dit oui ;
  * ESPACE_EPUISE  — toutes les configurations ont été essayées, aucune promue (verdict
                     honnête : la recherche n'a rien trouvé, on ne force pas) ;
  * BUDGET_EPUISE  — plafond d'itérations/temps atteint (reprise possible : l'état survit).

L'AVERTISSEMENT DE L'ARTICLE, PRIS AU SÉRIEUX
---------------------------------------------
« A loop without a real stopping condition fails quietly. » Ici :
  * la porte est une FONCTION SÉPARÉE de l'évaluateur — un rapport qui se déclare lui-même
    gagnant ne promeut RIEN si la porte dit non (testé) ;
  * l'état (`runtime/replay/boucle_objectif_etat.json`) est écrit APRÈS CHAQUE essai —
    un Ctrl-C ne perd rien, la reprise saute les configs déjà jugées ;
  * une évaluation qui explose est notée ERREUR et la boucle continue — pas de faux arrêt.

REPLAY-only : on rejoue des données enregistrées. Aucun ordre, aucun réseau requis ici.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Iterable

STATUT_PROMU = "PROMU"
STATUT_ESPACE_EPUISE = "ESPACE_EPUISE"
STATUT_BUDGET_EPUISE = "BUDGET_EPUISE"

ETAT_RELPATH = Path("runtime") / "replay" / "boucle_objectif_etat.json"


def cle_config(config: dict[str, Any]) -> str:
    """Clé STABLE d'une configuration (l'état de reprise en dépend)."""
    brut = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:16]


def _lire_etat(chemin: Path) -> dict[str, Any]:
    try:
        d = json.loads(chemin.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"essais": []}
    except (OSError, ValueError):
        return {"essais": []}


def _ecrire_etat(chemin: Path, etat: dict[str, Any]) -> None:
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass  # l'etat est un confort de reprise ; son echec d'ecriture ne stoppe pas la recherche


def boucle_objectif(
    configs: Iterable[dict[str, Any]],
    evaluer: Callable[[dict[str, Any]], dict[str, Any]],
    porte: Callable[[dict[str, Any]], bool],
    *,
    etat_path: str | Path | None = None,
    max_essais: int | None = None,
    budget_s: float | None = None,
    s_arreter_au_premier: bool = True,
) -> dict[str, Any]:
    """La boucle. `evaluer(config) -> rapport` ; `porte(rapport) -> bool` (SÉPARÉE, externe).

    Retourne {statut, gagnant, essais:[{cle, config, verdict, ...}]}. Ne lève jamais pour une
    évaluation qui échoue (notée ERREUR) ; lève seulement si `configs` est invalide.
    """
    debut = time.monotonic()
    chemin = Path(etat_path) if etat_path is not None else None
    etat = _lire_etat(chemin) if chemin else {"essais": []}
    deja = {e.get("cle") for e in etat.get("essais", []) if isinstance(e, dict)}
    essais: list[dict[str, Any]] = list(etat.get("essais", []))
    n_ce_run = 0

    for config in configs:
        cle = cle_config(config)
        if cle in deja:
            continue                                   # reprise : deja juge, on ne repaye pas
        if max_essais is not None and n_ce_run >= int(max_essais):
            statut = STATUT_BUDGET_EPUISE
            break
        if budget_s is not None and (time.monotonic() - debut) > float(budget_s):
            statut = STATUT_BUDGET_EPUISE
            break
        try:
            rapport = evaluer(config)
            promu = bool(porte(rapport))               # LA porte, jamais le rapport lui-meme
            essai = {"cle": cle, "config": config, "verdict": "PROMU" if promu else "REJETE",
                     "rapport_resume": {k: rapport.get(k) for k in ("verdict", "gates")
                                        if isinstance(rapport, dict) and k in rapport}}
            # nets par etage (si l'evaluateur les fournit) : diagnostic + classement des pepites
            if isinstance(rapport, dict):
                for etage in ("moitie_1", "moitie_2", "stress"):
                    m = rapport.get(etage)
                    if isinstance(m, dict) and "net_total_usd" in m:
                        essai.setdefault("nets", {})[etage] = round(
                            float(m.get("net_total_usd") or 0.0), 4)
                if rapport.get("instabilite"):
                    essai["instabilite"] = rapport["instabilite"]
        except Exception as exc:  # noqa: BLE001 — une eval qui explose n'arrete pas la recherche
            promu, essai = False, {"cle": cle, "config": config, "verdict": "ERREUR",
                                   "erreur": str(exc)[:200]}
        essais.append(essai)
        deja.add(cle)
        n_ce_run += 1
        # 21/07 (« le replay ne fonctionne pas ») : la recherche moulinait des MINUTES par
        # config en silence total -> ca ressemble a un gel. Une ligne par essai, AVEC le
        # diagnostic (quels nets, quelle porte a tue) : on apprend a chaque ligne.
        print("  essai %d : %s -> %s%s" % (
            len(essais), config, essai.get("verdict"),
            (" %s" % essai["nets"]) if essai.get("nets") else ""), flush=True)
        if chemin:
            _ecrire_etat(chemin, {"essais": essais})   # APRES CHAQUE essai : un Ctrl-C ne perd rien
        if promu and s_arreter_au_premier:
            resultat = {"statut": STATUT_PROMU, "gagnant": config, "essais": essais,
                        "n_essais_total": len(essais)}
            if chemin:
                _ecrire_etat(chemin, {"essais": essais, "resultat": resultat["statut"],
                                      "gagnant": config})
            return resultat
    else:
        statut = STATUT_ESPACE_EPUISE

    # 21/07 (« PLUSIEURS pepites ») : en mode collection, on balaie TOUT l'espace puis on
    # classe les promus par leur net SOUS STRESS (la barre la plus dure) — le gagnant est le
    # plus robuste, et toute la liste part au rapport.
    promus = [e for e in essais if e.get("verdict") == "PROMU"]
    gagnant = None
    if promus:
        statut = STATUT_PROMU
        gagnant = max(promus, key=lambda e: (e.get("nets") or {}).get("stress", 0.0))["config"]
    resultat = {"statut": statut, "gagnant": gagnant, "essais": essais,
                "n_essais_total": len(essais),
                "promus": [{"config": e["config"], "nets": e.get("nets")} for e in promus]}
    if chemin:
        _ecrire_etat(chemin, {"essais": essais, "resultat": statut, "gagnant": gagnant})
    return resultat


__all__ = ["STATUT_PROMU", "STATUT_ESPACE_EPUISE", "STATUT_BUDGET_EPUISE", "ETAT_RELPATH",
           "cle_config", "boucle_objectif"]
