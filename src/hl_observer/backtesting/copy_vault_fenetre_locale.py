"""Quelle partie du coffre LOCAL le labo doit lire — et que faire quand la mémoire se tend.

LE DÉFAUT, MESURÉ LE 17/11/2026 SUR LE REJEU RÉEL DU LABO.
Le labo principal appelait le pont LOCAL sans fenêtre. Le pont lit alors l'index dans l'ordre de
scellement — le plus ancien d'abord — et s'arrête à 8 millions de lignes. Mesure : il s'arrête au
shard 122 sur 6 409 et **ne dépasse jamais le 10/11**. Or la chaîne causale complète (un carnet
reçu AVANT le signal, lié par son identité de connexion) n'existe dans le coffre qu'à partir du
13/11. Le labo ne pouvait donc lire AUCUN des jours qu'il sait juger, et concluait
`INSUFFICIENT_EVALUABLE_SIGNAL_DAYS` : « trop peu de jours ». Ce verdict décrivait sa lecture,
pas le coffre.

Pire ce jour-là : à la première alerte du gouverneur mémoire, le pont abandonnait tout le reste
— 60 shards lus, 6 349 non lus — alors que la machine retrouvait 9,5 Go libres trente secondes
plus tard. Et le verdict final ne disait rien de cette interruption.

CE QUE FAIT CE MODULE.
* `premier_jour_liable` : le premier jour où les carnets scellés portent de quoi lier une
  référence pré-signal. (Déplacé ici depuis `tools/matrice_coffre.py`, qui le réexporte : une
  seule définition pour la matrice et pour le labo.)
* `choisir_la_fenetre` : le labo lit à partir de ce jour-là. Sans jour liable, il lit comme avant.
* `patienter_sous_pression` : quand la mémoire est critique, on ATTEND si la pression vient
  d'ailleurs (navigateur, WSL…), on s'arrête tout de suite si c'est notre propre charge. « On
  rétrécit la puissance, jamais les données » — et on ne touche à aucun processus tiers.
* `mention_de_lecture` : la phrase que le verdict doit porter quand la lecture a été interrompue.
"""
from __future__ import annotations

import gzip
import json
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hl_observer.ops import budget_ram as _BR
from hl_observer.ops.echec_silencieux import noter as _noter_echec

INDEX_LOCAL = Path("runtime") / "coffre_certifie" / "LOCAL_INDEX.json"

MOTIF_PREMIER_JOUR_LIABLE = "A_PARTIR_DU_PREMIER_JOUR_LIABLE"
MOTIF_AUCUN_JOUR_LIABLE = "AUCUN_JOUR_LIABLE_LECTURE_COMPLETE"
MOTIF_INDEX_ILLISIBLE = "INDEX_LOCAL_ILLISIBLE_LECTURE_COMPLETE"

#: Attentes successives, en secondes, quand la pression vient d'ailleurs. 7,5 minutes au plus :
#: le 17/11 la mémoire revenait au vert en moins d'une minute.
PATIENCE_S = (30.0, 60.0, 120.0, 240.0)

ARRET_MEMOIRE = "MEMOIRE_CRITIQUE"
DETAIL_NOTRE_CHARGE = "NOTRE_CHARGE"
DETAIL_EXTERNE_PERSISTANTE = "PRESSION_EXTERNE_PERSISTANTE"


def premier_jour_liable(root: Path, shards: Sequence[Mapping[str, Any]], *,
                        lignes_par_shard: int = 200) -> dict[str, Any]:
    """Le premier jour où les carnets scellés portent de quoi lier une référence pré-signal.

    La liaison exige ``connection_id`` et ``l2_gap_epoch`` sur le carnet. Mesure du 17/11 : 0,0 %
    des lignes avant le 13/11, ~100 % ensuite. Avant ce jour, aucune chaîne causale complète ne
    peut être rejouée depuis le coffre, quelle que soit la couverture de ``book_l2``.

    Coût borné : UN shard par jour, ``lignes_par_shard`` lignes au plus.
    """
    par_jour: dict[str, dict[str, Any]] = {}
    for entree in sorted((x for x in shards if isinstance(x, Mapping) and x.get("famille") == "book_l2"
                          and type(x.get("ts_max_ms")) is int),
                         key=lambda x: x["ts_max_ms"]):
        jour = time.strftime("%Y-%m-%d", time.gmtime(entree["ts_max_ms"] / 1000.0))
        if jour in par_jour:
            continue
        chemin = Path(root) / str(entree.get("shard") or "")
        lues = liables = 0
        try:
            with gzip.open(chemin, "rt", encoding="utf-8") as fh:
                for brut in fh:
                    if lues >= lignes_par_shard:
                        break
                    if not brut.strip():
                        continue
                    try:
                        ligne = json.loads(brut)
                    except ValueError:
                        continue
                    lues += 1
                    if ligne.get("connection_id") and ligne.get("l2_gap_epoch") is not None:
                        liables += 1
        except (OSError, EOFError):
            par_jour[jour] = {"lues": 0, "liables": 0, "illisible": True}
            continue
        par_jour[jour] = {"lues": lues, "liables": liables}
    premier = next((j for j in sorted(par_jour)
                    if par_jour[j]["lues"] and par_jour[j]["liables"] * 2 > par_jour[j]["lues"]),
                   None)
    return {"premier_jour_liable": premier, "jours_sondes": len(par_jour),
            "par_jour": dict(sorted(par_jour.items())),
            "methode": f"1 shard par jour, {lignes_par_shard} lignes au plus ; liable = majorite "
                       "de lignes portant connection_id ET l2_gap_epoch"}


def choisir_la_fenetre(root: Path, shards: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """La fenêtre que le labo doit demander au pont LOCAL. NE LÈVE JAMAIS.

    ``depuis_ms`` vaut le début (UTC) du premier jour liable, ou ``None`` — auquel cas le pont lit
    comme avant, et le motif dit pourquoi.
    """
    if shards is None:
        try:
            index = json.loads((Path(root) / INDEX_LOCAL).read_text(encoding="utf-8"))
            shards = index.get("shards") if isinstance(index, Mapping) else None
        except (OSError, ValueError) as exc:
            _noter_echec("backtesting/copy_vault_fenetre_locale.py:index_local", exc)
            shards = None
        if not isinstance(shards, list):
            return {"depuis_ms": None, "motif": MOTIF_INDEX_ILLISIBLE, "premier_jour_liable": None,
                    "jours_sondes": 0}
    liaison = premier_jour_liable(Path(root), shards)
    jour = liaison["premier_jour_liable"]
    if jour is None:
        return {"depuis_ms": None, "motif": MOTIF_AUCUN_JOUR_LIABLE, "premier_jour_liable": None,
                "jours_sondes": liaison["jours_sondes"]}
    depuis = int(datetime.strptime(jour, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)
    return {"depuis_ms": depuis, "motif": MOTIF_PREMIER_JOUR_LIABLE, "premier_jour_liable": jour,
            "jours_sondes": liaison["jours_sondes"]}


def patienter_sous_pression(*, patience_s: Sequence[float] = PATIENCE_S,
                            progress: Callable[[str], None] | None = None,
                            br: Any = None) -> dict[str, Any]:
    """Faut-il continuer à charger ? Attend si la pression vient d'ailleurs. NE LÈVE JAMAIS.

    Rend ``continuer`` (bool), ``attendu_s``, ``incident`` (la mémoire était-elle critique),
    ``coupable`` (``NOUS`` / ``EXTERIEUR`` / ``None``) et ``detail`` quand on s'arrête.
    """
    br = br or _BR
    calme = {"continuer": True, "attendu_s": 0.0, "incident": False, "coupable": None, "detail": None}
    try:
        premiere = br.decision()
        if premiere.get("action") != br.PAUSER:
            return calme
        etat = premiere.get("etat") or br.etat_memoire()
        faute = br.coupable_de_la_pression(arbre_octets=br.memoire_de_l_arbre_octets(),
                                           dispo_octets=etat["dispo_octets"],
                                           total_octets=etat["total_octets"])
        if faute.get("coupable") == "NOUS":
            # Attendre ne libérera rien : c'est notre charge. On rétrécit, tout de suite.
            return {"continuer": False, "attendu_s": 0.0, "incident": True, "coupable": "NOUS",
                    "detail": DETAIL_NOTRE_CHARGE}
        attendu = 0.0
        for limite in patience_s:
            if progress is not None:
                progress(f"memoire critique, charge exterieure : attente jusqu'a {limite:.0f} s "
                         "(aucun processus tiers n'est touche)")
            attendu += float(br.attendre_que_ca_respire(limite_s=float(limite)).get("attendu_s") or 0.0)
            if br.decision().get("action") != br.PAUSER:
                return {"continuer": True, "attendu_s": round(attendu, 1), "incident": True,
                        "coupable": "EXTERIEUR", "detail": None}
        return {"continuer": False, "attendu_s": round(attendu, 1), "incident": True,
                "coupable": "EXTERIEUR", "detail": DETAIL_EXTERNE_PERSISTANTE}
    except Exception as exc:  # noqa: BLE001 — un gouverneur en panne ne doit pas bloquer le labo
        _noter_echec("backtesting/copy_vault_fenetre_locale.py:patience_memoire", exc)
        return calme


def mention_de_lecture(coffre_local: Mapping[str, Any] | None) -> str:
    """La précision que le verdict du labo doit porter sur ce qu'il a réellement LU du coffre LOCAL.

    Vide si la lecture est allée au bout. Sinon : pourquoi elle s'est arrêtée, et combien de shards
    n'ont pas été lus. Un verdict « trop peu de jours » sans cette phrase ferait prendre une
    lecture interrompue pour une propriété des données.
    """
    if not isinstance(coffre_local, Mapping):
        return ""
    arret = coffre_local.get("chargement_arrete")
    if not arret:
        return ""
    lus = coffre_local.get("shards_injectes")
    non_lus = coffre_local.get("shards_non_lus")
    return (f" ATTENTION — lecture du coffre LOCAL interrompue ({arret}) : {lus} shards lus, "
            f"{non_lus} non lus. Ce verdict décrit ce qui a été lu, pas le coffre.")


__all__ = [
    "INDEX_LOCAL", "MOTIF_PREMIER_JOUR_LIABLE", "MOTIF_AUCUN_JOUR_LIABLE", "MOTIF_INDEX_ILLISIBLE",
    "PATIENCE_S", "ARRET_MEMOIRE", "DETAIL_NOTRE_CHARGE", "DETAIL_EXTERNE_PERSISTANTE",
    "premier_jour_liable", "choisir_la_fenetre", "patienter_sous_pression", "mention_de_lecture",
]
