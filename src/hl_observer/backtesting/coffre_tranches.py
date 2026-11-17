"""TRANCHES BORNÉES du coffre : lire ce dont une étude a besoin, pas les 154 millions de lignes.

POURQUOI (chantier 10 de l'audit du 15/11). Le chemin principal du labo appelle
``_charger_tier_local(..., garder_signaux=False)`` : les 16 familles de contexte — dont
``funding_history`` et ``candle`` — sont **comptées puis jetées**. Le run du 12/11 comptait ainsi
13 354 078 lignes de signaux LOCAL qu'il n'utilisait pas.

Ce ``False`` n'est PAS une erreur : garder 154 millions de lignes en mémoire ferait sauter la
machine, et la règle de l'opérateur est « on ralentit ou on rétrécit, on ne crashe JAMAIS ». Le
vrai défaut est qu'il n'existait **aucun moyen intermédiaire** : tout ou rien.

Ce module est ce moyen. L'index du coffre porte déjà, pour chaque shard, ses ``coins``, ses bornes
``ts_min_ms``/``ts_max_ms`` et son ``sha256`` : on peut donc choisir les **seuls** shards qui
croisent une fenêtre et une liste de coins, puis n'en lire que les lignes utiles.

CE QU'IL GARANTIT, ET CE QU'IL REFUSE :

* **jointure as-of STRICTEMENT antérieure** : la valeur de contexte doit avoir été connue AVANT
  l'instant de la décision. Une égalité exacte à la milliseconde est refusée — dans la même
  milliseconde l'ordre n'est pas observable, et le supposer fabriquerait la causalité qu'on mesure.
  (Même règle que ``copy_vault_reference_binding``, pour que la chaîne soit cohérente.)
* **SHA-256 obligatoire** : un shard dont l'empreinte ne correspond pas est refusé entier. Jamais
  de données à moitié vérifiées.
* **borne de mémoire explicite** : au-delà de ``max_lignes`` on s'arrête et on le DIT
  (``tronque=True``). Une troncature silencieuse ferait mesurer sur un échantillon inconnu.
* **un shard sans bornes de temps n'est pas jeté en silence** : il est listé à part
  (``sans_bornes``), parce qu'on ne peut pas prouver qu'il est hors fenêtre. C'est le cas des 171
  shards ``position`` et 192 ``trades_marche`` scellés avant le correctif d'horloge du 16/11 :
  l'appelant décide de payer leur lecture ou de déclarer le trou — mais il le sait.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA = "hypersmart.coffre_tranches.v1"

#: Horloge qui DATE une ligne, par famille — **exactement la table du scelleur**
#: (``tools/sceller_coffre_local.py::_ts_primaire``). Les bornes ``ts_min_ms``/``ts_max_ms`` de
#: chaque shard de l'index ont été écrites avec CETTE horloge : trancher avec une autre ferait
#: sortir de la fenêtre des lignes que l'index croit ailleurs dans le temps.
#:
#: 16/11/2026 — DÉFAUT MESURÉ, ET SILENCIEUX. La table ne couvrait que 9 familles sur 23 et
#: ``horloge_de`` repliait sur ``ts_ms``. Or trois familles n'ont PAS ce champ : ``bbo``
#: (30 392 168 lignes, horloge ``recv_wall_ts_ms``), ``book_l2`` (6 956 689 lignes,
#: ``exchange_ts_ms``) et ``venue_book`` (``snapshot_ts_ms``). Dans ``charger()``, un instant
#: absent vaut ``continue`` : le trancheur ignorait donc CHAQUE ligne de carnet et de cotation et
#: renvoyait ``n=0`` **sans aucun motif**. Les deux familles les plus lourdes du replay étaient
#: invisibles à l'outil même censé les rendre exploitables.
#:
#: Depuis : la table couvre les 23 familles du coffre, les lignes sans horloge sont COMPTÉES
#: (``lignes_sans_horloge``) au lieu d'être jetées en silence, et un test refuse qu'une famille
#: indexée n'ait pas d'horloge déclarée ici.
HORLOGE_PAR_FAMILLE: dict[str, str] = {
    # fills et épisodes de vault : horloge d'événement Hyperliquid
    "fills_forward": "ts_ms",
    "fills_backfill": "ts_ms",
    "snapshot": "ts_ms",
    "vault_ledger": "ts_ms",
    "vault_portfolio": "ts_ms",
    "leader_orders": "ts_ms",
    # carnets et cotations : horloges propres, SANS ts_ms (le défaut du 16/11)
    "book_l2": "exchange_ts_ms",
    "bbo": "recv_wall_ts_ms",
    "venue_book": "snapshot_ts_ms",
    # marché et contexte
    "trades_marche": "exchange_ts_ms",
    "candle": "open_ts_ms",
    "funding_history": "ts_ms",
    "asset_ctx": "ts_ms",
    "allmids": "ts_ms",
    "position": "received_at_ms",
    "liquidation": "ts_ms",
    "overshoot": "ts_ms",
    "venue_dispersion": "ts_ms",
    "explorer_tx": "ts_ms",
    # microstructure : le scelleur les date par ts_ms, le trancheur DOIT en faire autant pour
    # rester cohérent avec les bornes de l'index (la chaîne causale, elle, utilise l'horloge de
    # réception en passant explicitement ``horloge_serie`` à ``jointure_as_of``).
    "micro_bbo": "ts_ms",
    "micro_l2": "ts_ms",
    "micro_trades": "ts_ms",
}

#: Replis AUTORISÉS, dans l'ordre, quand l'horloge primaire manque sur une ligne. Le scelleur
#: écrit ``exchange_ts_ms or received_at_ms`` pour ``trades_marche`` : le trancheur accepte le même
#: repli, et lui seul. Ailleurs, une horloge absente reste une ligne non datée, comptée comme telle.
HORLOGES_DE_REPLI: dict[str, tuple[str, ...]] = {
    "trades_marche": ("received_at_ms",),
}

#: Plafond par défaut : ~200 Mo de lignes JSON décodées. Au-delà, une étude doit resserrer sa
#: fenêtre ou ses coins plutôt que d'avaler le corpus.
MAX_LIGNES_DEFAUT = 2_000_000


def _entier(valeur: Any) -> int | None:
    if type(valeur) is not int or isinstance(valeur, bool):
        return None
    return valeur


def horloge_de(famille: str) -> str:
    """Le champ qui date une ligne de cette famille (même choix que le scelleur)."""
    return HORLOGE_PAR_FAMILLE.get(str(famille), "ts_ms")


def instant_de(ligne: Mapping[str, Any], famille: str) -> int | None:
    """L'instant d'une ligne : horloge primaire, puis les replis DÉCLARÉS de cette famille.

    Rend ``None`` quand la ligne n'est datée par aucune horloge autorisée — l'appelant doit alors
    la compter, jamais la confondre avec une ligne hors fenêtre.
    """
    instant = _entier(ligne.get(horloge_de(famille)))
    if instant is not None:
        return instant
    for repli in HORLOGES_DE_REPLI.get(str(famille), ()):
        instant = _entier(ligne.get(repli))
        if instant is not None:
            return instant
    return None


def selectionner(shards: Iterable[Mapping[str, Any]], *, famille: str,
                 coins: Sequence[str] | None = None,
                 debut_ms: int | None = None, fin_ms: int | None = None) -> dict[str, Any]:
    """Les shards qui CROISENT cette fenêtre et ces coins — et ceux dont on ne peut rien dire.

    Pur : ne touche aucun fichier. ``shards`` vient de ``LOCAL_INDEX.json``.
    """
    voulus = {str(c) for c in coins} if coins else None
    retenus: list[dict[str, Any]] = []
    sans_bornes: list[dict[str, Any]] = []
    ecartes_temps = ecartes_coin = 0
    for s in shards or ():
        if not isinstance(s, Mapping) or str(s.get("famille") or "") != str(famille):
            continue
        ses_coins = s.get("coins")
        if voulus is not None and isinstance(ses_coins, list) and ses_coins:
            if not (voulus & {str(c) for c in ses_coins}):
                ecartes_coin += 1
                continue
        tmin, tmax = _entier(s.get("ts_min_ms")), _entier(s.get("ts_max_ms"))
        if tmin is None or tmax is None:
            # On ne peut PAS prouver qu'il est hors fenetre : il sort a part, jamais en silence.
            sans_bornes.append(dict(s))
            continue
        if fin_ms is not None and tmin > int(fin_ms):
            ecartes_temps += 1
            continue
        if debut_ms is not None and tmax < int(debut_ms):
            ecartes_temps += 1
            continue
        retenus.append(dict(s))
    retenus.sort(key=lambda s: (_entier(s.get("ts_min_ms")) or 0, str(s.get("shard"))))
    return {
        "schema": SCHEMA, "famille": str(famille),
        "retenus": retenus, "sans_bornes": sans_bornes,
        "octets_retenus": sum(int(s.get("octets") or 0) for s in retenus),
        "octets_sans_bornes": sum(int(s.get("octets") or 0) for s in sans_bornes),
        "ecartes_temps": ecartes_temps, "ecartes_coin": ecartes_coin,
    }


#: Empreintes déjà calculées dans CE processus, clé ``(chemin, mtime_ns, taille)``. Une fouille
#: parcourt le corpus en dizaines de galeries et un shard dense est traversé par plusieurs d'entre
#: elles : sans ce cache, les 9,55 Go du coffre seraient re-hashés à chaque passage. La clé inclut
#: la date et la taille du fichier : si le shard change d'un octet, la clé change et l'empreinte est
#: recalculée. On ne fait donc PAS confiance à une vérification passée sur un fichier modifié.
_CACHE_SHA: dict[tuple[str, int, int], str] = {}

#: Au-delà, le cache est vidé : une fouille très longue ne doit pas fuir en mémoire.
MAX_CACHE_SHA = 20_000


def _sha256(chemin: Path) -> str:
    try:
        st = chemin.stat()
        cle: tuple[str, int, int] | None = (str(chemin), st.st_mtime_ns, st.st_size)
    except OSError:
        cle = None
    if cle is not None:
        vu = _CACHE_SHA.get(cle)
        if vu is not None:
            return vu
    h = hashlib.sha256()
    with chemin.open("rb") as fh:
        for bloc in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(bloc)
    empreinte = h.hexdigest()
    if cle is not None:
        if len(_CACHE_SHA) >= MAX_CACHE_SHA:
            _CACHE_SHA.clear()
        _CACHE_SHA[cle] = empreinte
    return empreinte


def flux(root: str | Path, shards: Iterable[Mapping[str, Any]], *, famille: str,
         coins: Sequence[str] | None = None,
         debut_ms: int | None = None, fin_ms: int | None = None,
         verifier_sha: bool = True,
         compteurs: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
    """Les lignes de cette tranche, UNE PAR UNE, sans jamais les accumuler.

    C'est la primitive qui permet d'exploiter un corpus plus grand que la RAM : l'appelant agrège
    au vol (compter, sommer, ajuster) et la mémoire reste plate quel que soit le nombre de shards.
    ``charger()`` n'est que ce flux matérialisé sous un plafond.

    Bornes INCLUSIVES ``[debut_ms, fin_ms]``. ``compteurs``, si fourni, reçoit le coût payé :
    ``shards_lus``, ``shards_refuses`` (avec motif), ``lignes_sans_horloge``, ``lignes_hors_coin``,
    ``lignes_hors_fenetre``. Un shard dont le SHA-256 diverge est refusé ENTIER, jamais à moitié lu.
    """
    racine = Path(root).resolve()
    voulus = {str(c) for c in coins} if coins else None
    c = compteurs if compteurs is not None else {}
    c.setdefault("shards_lus", 0)
    c.setdefault("shards_refuses", [])
    c.setdefault("lignes_sans_horloge", 0)
    c.setdefault("lignes_hors_coin", 0)
    c.setdefault("lignes_hors_fenetre", 0)
    for entree in shards or ():
        rel = str(entree.get("shard") or "")
        chemin = (racine / rel).resolve()
        try:
            chemin.relative_to(racine)
        except ValueError:
            c["shards_refuses"].append({"shard": rel, "motif": "HORS_COFFRE"})
            continue
        if not chemin.is_file():
            c["shards_refuses"].append({"shard": rel, "motif": "ABSENT_DU_DISQUE"})
            continue
        attendu = entree.get("sha256")
        if verifier_sha:
            if not isinstance(attendu, str) or len(attendu) != 64:
                c["shards_refuses"].append({"shard": rel, "motif": "SHA_ABSENT"})
                continue
            if _sha256(chemin) != attendu:
                c["shards_refuses"].append({"shard": rel, "motif": "SHA_DIVERGENT"})
                continue
        c["shards_lus"] += 1
        ouvrir = gzip.open if chemin.suffix == ".gz" else open
        try:
            with ouvrir(chemin, "rt", encoding="utf-8") as fh:
                for brut in fh:
                    if not brut.strip():
                        continue
                    try:
                        ligne = json.loads(brut)
                    except ValueError:
                        continue
                    if not isinstance(ligne, dict):
                        continue
                    if voulus is not None and str(ligne.get("coin") or "") not in voulus:
                        c["lignes_hors_coin"] += 1
                        continue
                    instant = instant_de(ligne, famille)
                    if instant is None:
                        # Jamais confondue avec une ligne hors fenetre : elle n'est pas datable.
                        c["lignes_sans_horloge"] += 1
                        continue
                    if debut_ms is not None and instant < int(debut_ms):
                        c["lignes_hors_fenetre"] += 1
                        continue
                    if fin_ms is not None and instant > int(fin_ms):
                        c["lignes_hors_fenetre"] += 1
                        continue
                    yield ligne
        except (OSError, EOFError, gzip.BadGzipFile):
            c["shards_refuses"].append({"shard": rel, "motif": "LECTURE_INTERROMPUE"})
            continue


def charger(root: str | Path, shards: Iterable[Mapping[str, Any]], *, famille: str,
            coins: Sequence[str] | None = None,
            debut_ms: int | None = None, fin_ms: int | None = None,
            max_lignes: int = MAX_LIGNES_DEFAUT,
            verifier_sha: bool = True) -> dict[str, Any]:
    """Lit la tranche. SHA vérifié, chemin borné au coffre, mémoire plafonnée et DITE."""
    champ = horloge_de(famille)
    compteurs: dict[str, Any] = {}
    lignes: list[dict[str, Any]] = []
    tronque = False
    plafond = max(1, int(max_lignes))
    for ligne in flux(root, shards, famille=famille, coins=coins, debut_ms=debut_ms,
                      fin_ms=fin_ms, verifier_sha=verifier_sha, compteurs=compteurs):
        lignes.append(ligne)
        if len(lignes) >= plafond:
            tronque = True
            break
    lignes.sort(key=lambda r: instant_de(r, famille) or 0)
    return {
        "schema": SCHEMA, "famille": str(famille), "horloge": champ,
        "lignes": lignes, "n": len(lignes), "shards_lus": compteurs["shards_lus"],
        "shards_refuses": compteurs["shards_refuses"], "tronque": tronque,
        "max_lignes": int(max_lignes),
        # 16/11 : une ligne non datable est COMPTEE. Avant, les 37 M lignes de carnets et de
        # cotations disparaissaient ici sans laisser de trace.
        "lignes_sans_horloge": compteurs["lignes_sans_horloge"],
    }


def jointure_as_of(evenements: Sequence[Mapping[str, Any]], serie: Sequence[Mapping[str, Any]],
                   *, horloge_evenement: str, horloge_serie: str,
                   par_coin: bool = True) -> list[dict[str, Any]]:
    """Pour chaque événement, la DERNIÈRE valeur de contexte connue **strictement avant** lui.

    Aucune valeur postérieure ne peut entrer : c'est toute la différence entre une mesure et une
    fuite temporelle. Un événement sans valeur antérieure reçoit ``None`` — jamais une valeur
    « proche », jamais un zéro.
    """
    import bisect

    par_cle: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
    for ligne in serie or ():
        instant = _entier(ligne.get(horloge_serie))
        if instant is None:
            continue
        cle = str(ligne.get("coin") or "") if par_coin else ""
        par_cle.setdefault(cle, []).append((instant, ligne))
    for v in par_cle.values():
        v.sort(key=lambda t: t[0])
    index = {k: [t[0] for t in v] for k, v in par_cle.items()}

    sortie: list[dict[str, Any]] = []
    for ev in evenements or ():
        instant = _entier(ev.get(horloge_evenement))
        cle = str(ev.get("coin") or "") if par_coin else ""
        contexte = None
        age = None
        if instant is not None and cle in index:
            i = bisect.bisect_left(index[cle], instant) - 1   # STRICTEMENT avant
            if i >= 0:
                vu, contexte = par_cle[cle][i]
                age = instant - vu
        sortie.append({"evenement": ev, "contexte": contexte, "age_ms": age})
    return sortie


def contexte_as_of(root: str | Path, index_shards: Iterable[Mapping[str, Any]],
                   evenements: Sequence[Mapping[str, Any]], *, famille: str,
                   horloge_evenement: str = "signal_ms",
                   marge_avant_ms: int = 7 * 86_400_000,
                   max_lignes: int = MAX_LIGNES_DEFAUT) -> dict[str, Any]:
    """Le point d'entrée en UN appel : sélectionne, charge la tranche, joint en as-of.

    C'est la fonction que les études doivent utiliser au lieu de charger un corpus entier. La
    fenêtre est déduite des événements eux-mêmes, élargie de ``marge_avant_ms`` vers le PASSÉ
    seulement — jamais vers le futur, pour qu'aucune valeur postérieure ne puisse entrer.

    Rend aussi le coût payé (shards lus, octets, troncature, refus) : une étude doit pouvoir dire
    sur quoi elle a mesuré, et ce qu'elle n'a pas pu lire.
    """
    instants = [_entier(e.get(horloge_evenement)) for e in evenements or ()]
    instants = [t for t in instants if t is not None]
    if not instants:
        return {"schema": SCHEMA, "famille": str(famille), "resultats": [],
                "couverture": {"evenements": 0, "avec_contexte": 0},
                "tranche": {"n": 0, "shards_lus": 0, "tronque": False, "shards_refuses": []},
                "selection": {"retenus": 0, "sans_bornes": 0},
                "raison": "AUCUN_EVENEMENT_HORODATE"}
    coins = sorted({str(e.get("coin")) for e in evenements if e.get("coin")}) or None
    debut = min(instants) - max(0, int(marge_avant_ms))
    fin = max(instants)
    sel = selectionner(index_shards, famille=famille, coins=coins, debut_ms=debut, fin_ms=fin)
    tranche = charger(root, sel["retenus"], famille=famille, coins=coins,
                      debut_ms=debut, fin_ms=fin, max_lignes=max_lignes)
    resultats = jointure_as_of(evenements, tranche["lignes"],
                               horloge_evenement=horloge_evenement,
                               horloge_serie=tranche["horloge"])
    avec = sum(1 for r in resultats if r["contexte"] is not None)
    return {
        "schema": SCHEMA, "famille": str(famille), "resultats": resultats,
        "couverture": {"evenements": len(resultats), "avec_contexte": avec,
                       "sans_contexte": len(resultats) - avec},
        "tranche": {k: tranche[k] for k in ("n", "shards_lus", "tronque", "shards_refuses")},
        "selection": {"retenus": len(sel["retenus"]), "sans_bornes": len(sel["sans_bornes"]),
                      "octets_retenus": sel["octets_retenus"],
                      "octets_sans_bornes": sel["octets_sans_bornes"]},
        "fenetre_ms": [debut, fin],
        "raison": "OK",
    }


__all__ = [
    "SCHEMA", "HORLOGE_PAR_FAMILLE", "HORLOGES_DE_REPLI", "MAX_LIGNES_DEFAUT",
    "horloge_de", "instant_de", "selectionner", "flux", "charger",
    "jointure_as_of", "contexte_as_of",
]
