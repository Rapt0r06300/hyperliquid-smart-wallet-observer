#!/usr/bin/env python3
"""Suivi ADAPTATIF des leaders : curés (vettés) + traders ACTIFS découverts par l'explorer.

Problème observé : on suit 71 leaders mais la plupart sont inactifs à l'instant t, donc
les fills viennent d'un seul trader. L'explorer, lui, découvre en continu les traders
réellement actifs. Cet outil fusionne, à chaque lancement, la liste suivie :

    suivis = base curée (toujours gardée) + top traders ACTIFS (classement explorer), plafonné

Le débit REST est capé par l'AIMD anti-429 du poll (suivre plus de leaders ne crée pas plus
de 429 : chaque leader est simplement interrogé un peu moins souvent). Résultat : des fills
de BEAUCOUP plus de traders, donc plus de diversité et de jours scoreables pour le labo.
Non destructif : la base curée est sauvegardée une fois, l'ancienne liste est sauvegardée.
PAPER / lecture seule vis-à-vis du réseau.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.forward_poll_fills import cadence_plan  # noqa: E402

LEADERS = Path("config") / "copy_vault_leaders.json"
CURES = Path("config") / "copy_vault_leaders_cures.json"     # base vettée permanente
CLASSEMENT = Path("config") / "leaders_actifs_classement.json"  # écrit par l'explorer
CAP_DEFAUT = 120


def _valide(v) -> str | None:
    s = str(v or "").strip().lower()
    return s if s.startswith("0x") and len(s) >= 10 else None


BESOINS = Path("runtime") / "data" / "copy_vault_besoins_collecte.json"   # plan publié par le labo
CAP_ARCHIVE = 150      # adresses gardées en cadence d'archive, hors plafond principal
STRATES = 4            # tranches du classement d'activité parcourues à tour de rôle
CLASSES_LENTES = ("PRIORITAIRE", "STANDARD")
RESERVE_EXPLORATION = 20   # places gardées pour des leaders jamais classés (au plus 1/4 de la capacité libre)


def ordre_exploration(candidats: list[str], *, jour: int, strates: int = STRATES) -> list[str]:
    """Parcours STRATIFIÉ du classement d'activité, déterministe, avec rotation journalière.

    Le classement de l'explorer trie par activité : ne prendre que la tête revient à ne
    découvrir que des robots à haute fréquence (non copiables, mesuré par le labo). On
    alterne donc entre tranches d'activité, et le point de départ de chaque tranche avance
    d'un cran par jour : toute la population finit explorée, sans choix lié à un résultat.
    """
    n = len(candidats)
    if n == 0:
        return []
    k = max(1, min(strates, n))
    bornes = [round(i * n / k) for i in range(k + 1)]
    tranches = [candidats[bornes[i]:bornes[i + 1]] for i in range(k)]
    tranches = [t[jour % len(t):] + t[:jour % len(t)] for t in tranches if t]
    out: list[str] = []
    while any(tranches):
        for tranche in tranches:
            if tranche:
                out.append(tranche.pop(0))
    return out


def construire_suivis(
    cures: list[str], actifs: list[str], *, cap: int = CAP_DEFAUT,
    plan: dict[str, str] | None = None, jour: int = 0,
) -> list[str]:
    """Liste suivie = base curée, puis (si le labo a publié un plan) opérateurs lents mesurés,
    puis exploration stratifiée, plafonné à `cap` ; enfin les adresses en cadence d'archive.

    Sans plan : comportement historique exact (curés puis actifs par activité).
    Avec plan : une adresse classée ``ARCHIVE`` (robot HFT ou clone d'opérateur) ne consomme
    plus de place d'exploration, mais reste suivie à faible cadence (jusqu'à ``CAP_ARCHIVE``) :
    l'univers historique est conservé, seul le budget change.
    """
    out: list[str] = []
    vus: set[str] = set()

    def ajouter(source: list[str], limite: int) -> None:
        for v in source:
            if len(out) >= limite:
                return
            vv = _valide(v)
            if vv and vv not in vus:
                vus.add(vv)
                out.append(vv)

    if not plan:
        ajouter(cures, cap)
        ajouter(actifs, cap)
        return out
    archives = {a for a, classe in plan.items() if classe == "ARCHIVE"}
    ajouter(cures, cap)                                                   # vettés : toujours gardés
    # Sans réserve, les leaders déjà classés remplissent tout le plafond et la découverte tombe à
    # zéro (constaté en réel) : on ne mesurerait plus jamais que les mêmes adresses.
    reserve = min(RESERVE_EXPLORATION, max(0, cap - len(out)) // 4)
    for classe in CLASSES_LENTES:                                         # mesurés lents par le labo
        ajouter([a for a, c in plan.items() if c == classe], cap - reserve)
    candidats = [a for a in (_valide(v) for v in actifs) if a and a not in archives and a not in vus]
    ajouter(ordre_exploration(candidats, jour=jour), cap)                 # découverte sans biais d'activité
    ajouter([a for a in plan if a in archives], len(out) + CAP_ARCHIVE)   # conservés, faible cadence
    return out


def _charger_vaults(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    v = data.get("vaults") if isinstance(data, dict) else data
    return [x for x in (v or []) if _valide(x)]


def _charger_actifs(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    actifs = data.get("actifs") if isinstance(data, dict) else data
    out = []
    for item in actifs or []:
        v = item.get("vault") if isinstance(item, dict) else item
        if _valide(v):
            out.append(str(v).strip().lower())
    return out


def _charger_plan(root: Path) -> tuple[dict[str, str], str | None]:
    """Plan de cadence du labo (adresse -> classe) ; vide si absent ou illisible (jamais bloquant)."""
    try:
        besoins = json.loads((root / BESOINS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, None
    if not isinstance(besoins, dict):
        return {}, None
    return cadence_plan(besoins), besoins.get("experiment_id")


def fusionner(root: Path, *, cap: int = CAP_DEFAUT) -> dict:
    leaders_path = root / LEADERS
    cures_path = root / CURES
    # 1) snapshot de la base curée (une seule fois) depuis la liste actuelle.
    if not cures_path.exists() and leaders_path.exists():
        cures_path.parent.mkdir(parents=True, exist_ok=True)
        cures_path.write_text(json.dumps(
            {"vaults": _charger_vaults(leaders_path), "note": "base curee vettee (figee)"},
            ensure_ascii=False, indent=2), encoding="utf-8")
    cures = _charger_vaults(cures_path) or _charger_vaults(leaders_path)
    actifs = _charger_actifs(root / CLASSEMENT)
    if not actifs:
        return {"statut": "pas_de_classement", "cures": len(cures), "actifs_ajoutes": 0,
                "total": len(cures)}
    plan, experience = _charger_plan(root)
    jour = int(time.time() // 86_400)
    suivis = construire_suivis(cures, actifs, cap=cap, plan=plan, jour=jour)
    # Les adresses en cadence d'archive (robots HFT, clones) ne servent qu'à un collecteur qui
    # APPLIQUE le plan du labo. ``vaults`` est lue par toutes les lanes cloud, qui n'ont pas ce
    # plan et les interrogeraient à pleine cadence au détriment des leaders utiles : elles vont
    # donc dans ``vaults_archive``. Un leader vetté reste dans ``vaults`` quelle que soit sa classe.
    base = set(cures)
    archives = [v for v in suivis if plan.get(v) == "ARCHIVE" and v not in base]
    pleine_cadence = [v for v in suivis if v not in set(archives)]
    ajoutes = [v for v in pleine_cadence if v not in base]
    # 2) sauvegarde de l'ancienne liste puis écriture.
    if leaders_path.exists():
        bak = leaders_path.with_suffix(".json.avant-fusion.bak")
        bak.write_text(leaders_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    leaders_path.parent.mkdir(parents=True, exist_ok=True)
    leaders_path.write_text(json.dumps(
        {"vaults": pleine_cadence, "vaults_archive": archives,
         "source": "fusion curés+actifs (fusionner_leaders_actifs)",
         "n_cures": len(cures), "n_actifs_ajoutes": len(ajoutes), "cap": cap,
         # traçabilité de la sélection : quel plan du labo, quel jour de rotation, quelles classes
         "plan_labo": {
             "applique": bool(plan), "experiment_id": experience, "jour_rotation": jour,
             "n_lents": sum(1 for v in pleine_cadence if plan.get(v) in CLASSES_LENTES),
             "n_archive": sum(1 for v in suivis if plan.get(v) == "ARCHIVE"),
             "n_exploration": sum(1 for v in ajoutes if v not in plan),
         }},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return {"statut": "OK", "cures": len(cures), "actifs_ajoutes": len(ajoutes),
            "archives": len(archives), "total": len(suivis)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fusionne leaders curés + actifs découverts (suivi adaptatif).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--cap", type=int, default=CAP_DEFAUT)
    args = p.parse_args(argv)
    rap = fusionner(Path(args.root), cap=max(1, args.cap))
    if rap["statut"] == "OK":
        print(f"[leaders] suivi adaptatif : {rap['cures']} cures + {rap['actifs_ajoutes']} actifs "
              f"+ {rap.get('archives', 0)} en cadence d'archive (hors lanes cloud) "
              f"= {rap['total']} leaders suivis.", flush=True)
    else:
        print(f"[leaders] {rap['statut']} : {rap['cures']} cures conserves (pas d'ajout). "
              f"L'explorer doit tourner un cycle pour produire le classement.", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
