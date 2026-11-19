"""La position du leader DERIVEE de `start_position`, pour les fills qui n'en portent pas.

LE DEFAUT QUE CE MODULE REPARE (19/11/2026). La politique gelee ne copie QUE les RENFORCEMENTS
(``ACTIONS_COPIEES_PAR_LA_POLITIQUE = ('ADD',)``), et distinguer un renforcement d'une ouverture
demande la position du leader AVANT le fill : ``dir`` dit « Open Long » dans les deux cas. Cette
position se lit dans ``start_position``, que la plateforme ne renseigne pas toujours, ou dans la
famille ``position`` du coffre. Mesure du 19/11 sur la fenetre dense (13 au 19 novembre) :

    13 926 102 lignes lues  ->  4 122 261 retenues  ->  118 742 COPIABLES, soit 0,85 %
     6 194 061 fills JETES faute de position connue

Et ce n'est pas qu'une perte de volume : la famille ``position`` ne couvre que **179 coins sur
les 1 648** qui portent des fills. Les 89 % ecartes sont donc la QUEUE de distribution, toujours
les memes. Un signal dont l'univers est defini par ce qu'on a deja instantane ne peut rien
decouvrir de nouveau -- c'est un biais de selection, pas seulement un trou.

CE QUE CE MODULE AJOUTE, ET POURQUOI C'EST HONNETE. La famille ``fills_backfill`` porte
``start_position`` sur **81,3 %** de ses lignes (mesure du 19/11 : 17 404 sur 21 404), contre
37,9 % pour ``fills_forward`` -- 7,2 M de lignes sur 208 journees et 522 coins. Chacune de ces
valeurs est une OBSERVATION publiee par la plateforme, jamais une supposition.

LA DISTINCTION QUI DECIDE DE TOUT : SIGNAL contre ETAT.

* Comme **signal a copier**, un fill de backfill est INTERDIT : on ne l'a connu qu'apres coup,
  donc aucun copieur n'aurait pu y reagir. Le corpus le dit lui-meme, chaque ligne de backfill
  portant ``causal_forward_eligible: False``. Ce module ne rend donc JAMAIS d'evenement a copier,
  et ``FAMILLES_DE_FILLS`` reste inchangee.
* Comme **etat de position**, la meme ligne est legitime : la position d'un leader a l'instant T
  est un fait, et un copieur en direct peut l'interroger (``clearinghouseState``). On s'en sert
  uniquement pour repondre « que detenait le leader avant SON fill », question dont la reponse
  ne depend pas du moment ou nous, nous l'avons apprise.

La causalite reste imposee en aval : ``position_avant`` ne regarde que les observations situees
au plus tard a l'instant du fill, et au plus ``MAX_AGE_POSITION_MS`` avant lui.

CE QUI EST REFUSE PLUTOT QUE DEVINE. On n'enregistre une observation que si la position APRES le
fill est entierement calculable : ``start_position`` numerique, ``sz`` numerique et ``signe``
dans {+1, -1}. Enregistrer la position d'AVANT serait enregistrer une valeur qu'on sait deja
perimee -- le fill vient de la changer. Toute ligne incomplete est COMPTEE dans l'audit et
laissee de cote.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

#: Familles lues par defaut. ``fills_backfill`` est la nouvelle source (81,3 % de couverture) ;
#: ``fills_forward`` peut etre ajoutee par l'appelant, au prix d'une seconde lecture de ses
#: 13,9 M de lignes.
FAMILLES_DERIVEES: tuple[str, ...] = ("fills_backfill",)

#: On lit avant la fenetre : une position observee juste avant son debut renseigne les premiers
#: fills. La marge reprend celle de ``positions_du_coffre`` (age maximal + une heure).
MARGE_LECTURE_MS = 300_000 + 3_600_000


def _nombre(valeur: Any) -> float | None:
    """La valeur si c'est un nombre REEL, sinon None. Un booleen n'est pas un nombre ici."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None
    return float(valeur)


def positions_depuis_les_fills(
    racine: str | Path,
    *,
    debut_ms: int,
    fin_ms: int,
    familles: Sequence[str] = FAMILLES_DERIVEES,
) -> tuple[dict[tuple[str, str], list[tuple[int, float]]], dict[str, Any]]:
    """Series ``(vault, coin) -> [(instant_ms, position_signee)]`` derivees des fills.

    Meme forme que ``positions_du_coffre`` pour que ``position_avant`` les lise sans changement.

    L'instant retenu est ``ts_ms``, l'horodatage du fill du LEADER -- c'est-a-dire le moment ou
    sa position a reellement change. Prendre ``received_at_ms`` (le moment ou NOUS avons recu la
    ligne) rendrait toute observation de backfill perimee de plusieurs jours, donc inutilisable.
    """
    from hl_observer.backtesting import coffre_tranches

    racine = Path(racine)
    index = racine / "runtime/coffre_certifie/LOCAL_INDEX.json"
    audit: dict[str, Any] = {
        "status": "LU_DEPUIS_LE_COFFRE",
        "familles": list(familles),
        "lignes_lues": 0,
        "sans_start_position": 0,
        "sans_taille_ou_signe": 0,
        "sans_identite": 0,
        "observations_gardees": 0,
        "couples_vault_coin": 0,
        "shards": 0,
    }
    if not index.exists():
        return {}, {"status": "COFFRE_ABSENT", "chemin": str(index)}

    brut = json.loads(index.read_text(encoding="utf-8"))
    tous = brut.get("shards") or brut.get("entrees") or []
    if isinstance(tous, dict):
        tous = list(tous.values())

    debut_lecture = int(debut_ms) - MARGE_LECTURE_MS
    series: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for famille in familles:
        choix = coffre_tranches.selectionner(
            tous, famille=famille, coins=None, debut_ms=debut_lecture, fin_ms=int(fin_ms))
        shards = choix.get("shards") or choix.get("retenus") or []
        if not shards:
            continue
        audit["shards"] += len(shards)
        for ligne in coffre_tranches.flux(
            racine, shards, famille=famille, coins=None,
            debut_ms=debut_lecture, fin_ms=int(fin_ms), verifier_sha=False,
        ):
            audit["lignes_lues"] += 1
            avant = _nombre(ligne.get("start_position"))
            if avant is None:
                audit["sans_start_position"] += 1
                continue
            taille = _nombre(ligne.get("sz"))
            signe = _nombre(ligne.get("signe"))
            if taille is None or signe is None or signe not in (1.0, -1.0) or taille < 0.0:
                # Sans de quoi calculer la position APRES, on ne garde rien : la position
                # d'avant est deja perimee a l'instant qu'on lui donnerait.
                audit["sans_taille_ou_signe"] += 1
                continue
            instant = _nombre(ligne.get("ts_ms"))
            cle = (str(ligne.get("vault") or ligne.get("user") or ""), str(ligne.get("coin") or ""))
            if instant is None or not cle[0] or not cle[1]:
                audit["sans_identite"] += 1
                continue
            series.setdefault(cle, []).append((int(instant), avant + signe * taille))
            audit["observations_gardees"] += 1

    for serie in series.values():
        serie.sort(key=lambda couple: couple[0])
    audit["couples_vault_coin"] = len(series)
    return series, audit


def fusionner_positions(
    *sources: Mapping[tuple[str, str], Sequence[tuple[int, float]]],
) -> dict[tuple[str, str], list[tuple[int, float]]]:
    """Fusionne plusieurs series de positions, triees et sans doublon d'instant.

    QUI GAGNE EN CAS D'EGALITE. A instant identique, la source donnee EN PREMIER l'emporte :
    l'appelant passe d'abord la famille ``position`` (``szi``, observation directe de la chambre
    de compensation) et ensuite les positions derivees, qui ne comblent donc que les trous.
    """
    fusion: dict[tuple[str, str], dict[int, float]] = {}
    for source in sources:
        for cle, serie in (source or {}).items():
            cible = fusion.setdefault(cle, {})
            for instant, valeur in serie:
                cible.setdefault(int(instant), float(valeur))
    return {cle: sorted(valeurs.items()) for cle, valeurs in fusion.items()}
