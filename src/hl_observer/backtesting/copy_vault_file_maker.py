"""Le `queue_ratio` d'un ordre PASSIF, mesuré — jamais supposé.

POURQUOI CE MODULE EXISTE. `copy_vault_v21_frozen` paie `frais_taker_bps("HYPERLIQUID")` sur LES
DEUX jambes : **4,5 bps à l'aller, 9 bps l'aller-retour**. En maker, c'est 1,5 bps par jambe, donc
3 bps : **6 bps d'écart par aller-retour**. Sur les 100 USD du contrat paper, à 20 allers-retours
par jour, cela fait **+1,20 USD/jour** — face à un résultat mesuré de −0,19 USD/jour. Aucun autre
levier du projet n'a cet ordre de grandeur.

MAIS UN ORDRE PASSIF NE SE REMPLIT PAS PARCE QU'ON LE SOUHAITE. Le supposer rempli aux mêmes
instants et aux mêmes prix qu'un ordre agressif FABRIQUERAIT le PnL qu'on cherche à mesurer, et
l'erreur serait invisible puisqu'elle embellit le résultat. `paper_trading.fill_outcomes` pose
déjà la bonne règle — sans `queue_ratio`, un remplissage passif est compté `MISSED` — mais rien
ne calculait ce ratio. C'est ce que fait ce module, à partir de deux familles OBSERVÉES du
coffre : ``book_l2`` (ce qui dort devant moi) et ``trades_marche`` (ce qui est réellement passé).

LES DEUX HYPOTHÈSES, TOUTES DEUX CONSERVATRICES :

1. **J'arrive dernier dans la file.** Le carnet ne porte pas la priorité temporelle, donc tout ce
   qui repose à mon prix est compté DEVANT moi. Cela sous-estime les remplissages, jamais
   l'inverse.
2. **Seul le flux agressif du bon côté me remplit.** Un achat passif n'est rempli que par un
   vendeur agressif à mon prix ou en dessous. Le reste du volume ne me concerne pas.

Ce que ce module ne fait PAS : il ne décide d'aucun trade et ne touche pas au moteur gelé. Il
rend un ratio, ou ``None`` quand une des deux mesures manque — et ``None`` veut dire « on ne sait
pas », ce que l'appelant doit traiter comme un refus, jamais comme un remplissage.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

#: Familles du coffre dont ce module a besoin, et leur rôle.
FAMILLE_CARNET = "book_l2"
FAMILLE_TRANSACTIONS = "trades_marche"

#: Côtés d'un ordre passif.
ACHAT = "BUY"
VENTE = "SELL"


def _nombre(valeur: Any) -> float | None:
    """La valeur si c'est un nombre réel. Un booléen n'en est pas un."""
    if isinstance(valeur, bool) or valeur is None:
        return None
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def _niveaux(carnet: Mapping[str, Any], *, cote: str) -> list[tuple[float, float]] | None:
    """Les (prix, taille) du côté demandé, ou None si le carnet ne les porte pas."""
    brut = carnet.get("bids5" if cote == ACHAT else "asks5")
    if not isinstance(brut, (list, tuple)) or not brut:
        return None
    niveaux: list[tuple[float, float]] = []
    for niveau in brut:
        if isinstance(niveau, (list, tuple)) and len(niveau) >= 2:
            prix, taille = _nombre(niveau[0]), _nombre(niveau[1])
        elif isinstance(niveau, Mapping):
            prix, taille = _nombre(niveau.get("px")), _nombre(niveau.get("sz"))
        else:
            return None
        if prix is None or taille is None or prix <= 0 or taille < 0:
            return None
        niveaux.append((prix, taille))
    return niveaux or None


def taille_devant(
    carnet: Mapping[str, Any], *, prix: float, cote: str
) -> float | None:
    """Taille qui me précède dans la file si je me pose à `prix`, ou None si on ne sait pas.

    J'ARRIVE DERNIER : tout ce qui repose à mon prix est compté devant moi, faute de connaître la
    priorité temporelle. Sous-estimer mes remplissages est le seul sens d'erreur acceptable ici.
    """
    p = _nombre(prix)
    if p is None or p <= 0 or cote not in (ACHAT, VENTE):
        return None
    niveaux = _niveaux(carnet, cote=cote)
    if niveaux is None:
        return None
    # Côté achat, un prix PLUS HAUT est servi avant moi ; côté vente, un prix plus bas.
    devant = 0.0
    for niveau_prix, niveau_taille in niveaux:
        meilleur = niveau_prix > p if cote == ACHAT else niveau_prix < p
        if meilleur or niveau_prix == p:
            devant += niveau_taille
    return devant


def volume_traverse(
    transactions: Iterable[Mapping[str, Any]], *, prix: float, cote: str,
) -> float | None:
    """Volume AGRESSIF qui a traversé mon prix, du seul côté qui peut me remplir.

    Un achat passif à `prix` n'est rempli que par un VENDEUR agressif à ce prix ou en dessous.
    Une transaction sans prix, sans taille ou sans agresseur lisible est IGNORÉE — et si aucune
    n'est lisible, on rend None plutôt que zéro : « pas de volume » et « je n'ai pas su lire »
    ne doivent jamais se confondre.
    """
    p = _nombre(prix)
    if p is None or p <= 0 or cote not in (ACHAT, VENTE):
        return None
    total = 0.0
    lisibles = 0
    for transaction in transactions:
        if not isinstance(transaction, Mapping):
            continue
        prix_t = _nombre(transaction.get("price") or transaction.get("px"))
        taille_t = _nombre(transaction.get("size") or transaction.get("sz"))
        agresseur = str(transaction.get("aggressor_side") or "").strip().upper()
        if prix_t is None or taille_t is None or taille_t <= 0 or agresseur not in (ACHAT, VENTE):
            continue
        lisibles += 1
        if cote == ACHAT and agresseur == VENTE and prix_t <= p:
            total += taille_t
        elif cote == VENTE and agresseur == ACHAT and prix_t >= p:
            total += taille_t
    return total if lisibles else None


def ratio_de_file(
    carnet: Mapping[str, Any],
    transactions: Iterable[Mapping[str, Any]],
    *,
    prix: float,
    cote: str,
) -> float | None:
    """`queue_ratio` attendu par `fill_outcomes.resolve_fill`, ou None si une mesure manque.

    Ratio = ce qui me précède / ce qui est réellement passé. Petit quand le marché a largement
    consommé la file (je suis servi), >= 1 quand il ne l'a pas atteinte (je ne le suis pas).

    None N'EST PAS ZÉRO. `resolve_fill` traite None comme `MISSED` : ne pas savoir, c'est ne pas
    être rempli. Rendre 0.0 par défaut déclarerait un remplissage certain sur une ignorance.
    """
    devant = taille_devant(carnet, prix=prix, cote=cote)
    passe = volume_traverse(transactions, prix=prix, cote=cote)
    if devant is None or passe is None:
        return None
    if passe <= 0.0:
        return float("inf")      # rien n'est passé : la file n'a pas bougé, donc MISSED
    return devant / passe


def transactions_du_coffre(
    racine, *, debut_ms: int, fin_ms: int, coins: Sequence[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Les transactions observées du coffre, dans la fenêtre demandée.

    `coffre_tranches` connaît déjà l'horloge de cette famille (`exchange_ts_ms`, avec repli sur
    `received_at_ms` pour les shards scellés avant le correctif du 16/11/2026) : on ne la
    redevine pas ici.
    """
    import json
    from pathlib import Path

    from hl_observer.backtesting import coffre_tranches

    racine = Path(racine)
    index = racine / "runtime/coffre_certifie/LOCAL_INDEX.json"
    if not index.exists():
        return [], {"status": "COFFRE_ABSENT", "chemin": str(index)}
    brut = json.loads(index.read_text(encoding="utf-8"))
    tous = brut.get("shards") or brut.get("entrees") or []
    if isinstance(tous, dict):
        tous = list(tous.values())
    choix = coffre_tranches.selectionner(
        tous, famille=FAMILLE_TRANSACTIONS, coins=list(coins) if coins else None,
        debut_ms=int(debut_ms), fin_ms=int(fin_ms))
    shards = choix.get("shards") or choix.get("retenus") or []
    if not shards:
        return [], {"status": "AUCUN_SHARD", "shards": 0}
    lignes = [
        ligne for ligne in coffre_tranches.flux(
            racine, shards, famille=FAMILLE_TRANSACTIONS,
            coins=list(coins) if coins else None,
            debut_ms=int(debut_ms), fin_ms=int(fin_ms), verifier_sha=False)
    ]
    return lignes, {
        "status": "LU_DEPUIS_LE_COFFRE", "shards": len(shards), "lignes_lues": len(lignes),
    }
