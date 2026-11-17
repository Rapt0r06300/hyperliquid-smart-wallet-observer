"""Ce que le coffre permet de lire EN TRANCHES, et la part qu'une seule charge en voit.

POURQUOI CE MODULE EST À PART (17/11/2026). Ce code vivait dans ``copy_vault_local_lab.py``, qui
est un fichier de plus de 5 000 lignes sous plafond historique : l'invariant
``test_pas_de_nouveau_fichier_geant`` interdit de l'agrandir, et il avait raison de rougir. Plutôt
que de relever le plafond, le catalogue est extrait ici — il n'a d'ailleurs besoin de rien d'autre
que de l'index du coffre.

16/11/2026 — CHANTIER 10 : « comptées puis jetées » devient « comptées, ET utilisables ». Garder
les 154 millions de lignes de contexte en mémoire ferait sauter la machine : le
``garder_signaux=False`` du pont reste donc juste. Ce qui manquait, c'était un moyen
INTERMÉDIAIRE : prendre une TRANCHE bornée (famille × coins × fenêtre) au lieu de tout ou rien.
``coffre_tranches`` le fournit, en s'appuyant sur les ``coins`` / ``ts_min_ms`` / ``ts_max_ms``
que l'index du coffre porte déjà pour chaque shard.

Mesure du 16/11 sur le coffre réel : ``funding_history`` pèse 3 285 943 lignes ; la tranche
BTC+ETH sur 30 jours en rend 1 440 — 2 282 fois moins, pour la même réponse.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def catalogue_tranchable(repository_root: Path) -> dict[str, Any]:
    """Ce que le coffre permet de PRENDRE EN TRANCHE, sans rien charger ici.

    Une famille n'est découpable par le temps que si ses shards portent `ts_min_ms`/`ts_max_ms`.
    Les 171 shards `position` et 192 `trades_marche` scellés avant le correctif d'horloge du
    16/11 ne les portent pas : ils apparaissent en `shards_sans_bornes`, et c'est une information,
    pas un silence. Aucune lecture de shard ici — seulement l'index.
    """
    import json as _json

    from hl_observer.backtesting import coffre_tranches as _TR

    index = Path(repository_root) / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    try:
        shards = _json.loads(index.read_text(encoding="utf-8")).get("shards") or []
    except (OSError, ValueError, TypeError):
        return {"disponible": False, "raison": "LOCAL_INDEX_ILLISIBLE"}
    par_famille: dict[str, dict[str, Any]] = {}
    for shard in shards:
        if not isinstance(shard, dict):
            continue
        famille = str(shard.get("famille") or "?")
        bloc = par_famille.setdefault(famille, {
            "shards": 0, "shards_sans_bornes": 0, "lignes": 0, "octets": 0,
            "horloge": _TR.horloge_de(famille),
        })
        bloc["shards"] += 1
        bloc["lignes"] += int(shard.get("deposes") or 0)
        bloc["octets"] += int(shard.get("octets") or 0)
        if not (type(shard.get("ts_min_ms")) is int and type(shard.get("ts_max_ms")) is int):
            bloc["shards_sans_bornes"] += 1
    for bloc in par_famille.values():
        avec = bloc["shards"] - bloc["shards_sans_bornes"]
        bloc["shards_tranchables"] = avec
        bloc["part_tranchable"] = round(avec / bloc["shards"], 4) if bloc["shards"] else 0.0
        bloc["tranchable"] = (
            "COMPLETE" if bloc["shards_sans_bornes"] == 0 and avec
            else "PARTIELLE" if avec
            else "AUCUNE")
    # 16/11 (3e passe) — CE QU'IL FAUDRAIT POUR TOUT VOIR. Un run qui lit une seule charge
    # tronquee a 8 M lignes ne doit pas pouvoir ecrire un verdict sans dire combien de galeries
    # le corpus exige. Le plan ne lit AUCUN shard : seulement l'index, en moins de 3 secondes.
    fouille: dict[str, Any] = {"disponible": False}
    try:
        from hl_observer.backtesting import plan_de_fouille as _PF

        budget = _PF.budget_lignes()
        familles_connues = sorted(par_famille)
        plan = _PF.galeries(shards, familles=familles_connues, budget=budget["lignes"])
        controle = _PF.couverture(plan)
        lignes_totales = int(plan.get("lignes_indexees") or 0)
        fouille = {
            "disponible": True,
            "budget_lignes": budget["lignes"],
            "niveau_ram": budget["niveau_ram"],
            "galeries_pour_tout_voir": len(plan.get("galeries") or ()),
            "lignes_indexees": lignes_totales,
            "couverture_complete": bool(controle.get("complete")),
            "part_vue_en_une_charge": (
                round(min(1.0, budget["lignes"] / lignes_totales), 4) if lignes_totales else None),
            "appel": ("python tools/fouille_coffre.py --recenser  "
                      "(ou plan_de_fouille.galeries + parcourir)"),
        }
    except Exception as exc:  # noqa: BLE001 — un plan indisponible ne doit pas casser un run
        fouille = {"disponible": False, "raison": type(exc).__name__}
    return {
        "disponible": True,
        "schema": _TR.SCHEMA,
        "appel": ("hl_observer.backtesting.coffre_tranches.contexte_as_of("
                  "root, shards, evenements, famille=...)"),
        "familles": dict(sorted(par_famille.items())),
        "note": ("une famille tranchable se lit par (coins x fenetre) ; la jointure as-of est "
                 "STRICTEMENT anterieure, une egalite a la milliseconde est refusee"),
        # Combien de galeries il faudrait parcourir pour voir TOUT le corpus, et quelle part une
        # seule charge en voit. Sans ce chiffre, « tronque » reste une abstraction.
        "fouille": fouille,
    }


def publier_le_contexte_tranchable(resume: dict[str, Any], repository_root: Path) -> None:
    """Retire les lignes de signaux du résumé du coffre LOCAL et publie ce qui reste lisible.

    Les lignes elles-mêmes ne doivent pas gonfler le résultat du labo : seule la LISTE des
    familles comptées est gardée, avec le catalogue de ce qu'on peut relire en tranches.
    """
    signaux_locaux = resume.pop("_signaux", {})
    resume["signaux_familles_comptees"] = sorted(signaux_locaux.keys())
    resume["contexte_tranchable"] = catalogue_tranchable(repository_root)


__all__ = ["catalogue_tranchable", "publier_le_contexte_tranchable"]
