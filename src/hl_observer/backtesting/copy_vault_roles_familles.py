"""RÔLE MESURÉ des familles du coffre restées « à câbler » — ou leur exclusion motivée.

POURQUOI CE MODULE (17/11/2026). La matrice du coffre classait six familles dans un troisième
état, ``A_CABLER`` : ni consommées, ni exclues, seulement « déclarées, en attente d'une
hypothèse ». C'était mieux que le silence d'avant, mais l'objectif exige pour chaque famille un
rôle **consommé et mesuré** OU une **exclusion motivée**. Un état d'attente sans mesure laisse
ouverte la question qui compte : cette famille PEUT-elle seulement changer quelque chose ?

Ce module répond par une mesure descriptive, famille par famille, sans brancher aucune d'elles
dans un modèle — brancher sans hypothèse préenregistrée ajouterait des essais multiples, et les
lois mesurées n'ont pas besoin d'un degré de liberté de plus :

* ``trades_marche``  -> CAPACITÉ : le volume qu'échange le marché en une minute, rapporté à un
  ordre paper de 350 USD. Dit si la capacité est une contrainte, coin par coin.
* ``liquidation``    -> RISQUE : fréquence des liquidations / ADL touchant les comptes suivis.
* ``vault_ledger``   -> FLUX DE CAPITAL : part des jours-compte avec dépôt ou retrait, c'est-à-dire
  les jours où un PnL lu naïvement sur la valeur du compte serait faussé.
* ``overshoot``      -> RÉSULTAT SEULEMENT. La famille porte ``mid_fwd_15s … mid_fwd_120s`` et
  ``reversion_bps`` : ce sont des valeurs du FUTUR de l'événement. S'en servir comme
  caractéristique serait un look-ahead par construction. Elle est donc EXCLUE comme entrée de
  décision, et gardée comme étiquette de résultat, mesurée ici.
* ``micro_l2`` / ``micro_trades`` -> APPLICABILITÉ : ces flux ne couvrent que quelques coins. On
  mesure la part des ouvertures copiables qui tombent sur ces coins — si elle est faible, aucun
  conditionnement de microstructure ne peut peser, quelle que soit sa qualité.

Chaque fonction est pure, lit ses lignes en flux, et COMPTE ce qu'elle ignore.
PAPER / LECTURE SEULE : statistiques descriptives sur des observations publiques.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from hl_observer.backtesting.copy_vault_protocol import PAPER_EQUITY_USD

SCHEMA = "hypersmart.copy_vault_roles_familles.v1"
MINUTE_MS = 60_000
JOUR_MS = 86_400_000

#: Au-delà de ce multiple, une minute de marché absorbe l'ordre paper sans que la capacité soit
#: une contrainte. Volontairement large : 100 fois l'ordre en UNE minute.
MULTIPLE_CAPACITE_LARGE = 100.0

ROLE_CAPACITE = "CAPACITE_MESUREE"
ROLE_RISQUE = "RISQUE_MESURE"
ROLE_FLUX = "FLUX_DE_CAPITAL_MESURE"
ROLE_RESULTAT = "RESULTAT_SEULEMENT_EXCLUE_COMME_ENTREE"
ROLE_APPLICABILITE = "APPLICABILITE_MESUREE"


def _nombre(valeur: Any) -> float | None:
    if isinstance(valeur, bool) or valeur is None:
        return None
    try:
        x = float(valeur)
    except (TypeError, ValueError, OverflowError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _entier(valeur: Any) -> int | None:
    return valeur if type(valeur) is int else None


def _mediane(valeurs: list[float]) -> float | None:
    if not valeurs:
        return None
    ordonnees = sorted(valeurs)
    return float(ordonnees[len(ordonnees) // 2])


def capacite_par_coin(trades: Iterable[Mapping[str, Any]], *,
                      ordre_usd: float = float(PAPER_EQUITY_USD)) -> dict[str, Any]:
    """Volume de marché par minute et par coin, rapporté à l'ordre paper.

    Pour chaque coin : la MÉDIANE du notionnel échangé par minute, sur les seules minutes où il y
    a eu au moins un trade (une minute sans trade n'est pas un volume nul observé : c'est une
    minute où l'on ne sait rien de la capacité, et elle est comptée à part).
    """
    par_coin: dict[str, dict[int, float]] = {}
    lues = ignorees = 0
    debut = fin = None
    for trade in trades or ():
        lues += 1
        coin = trade.get("coin")
        # Pas de `a or b` ici : un horodatage 0 est FAUX au sens de Python et serait pris pour
        # une absence. On teste None explicitement, comme le scelleur.
        instant = _entier(trade.get("exchange_ts_ms"))
        if instant is None:
            instant = _entier(trade.get("received_at_ms"))
        prix = _nombre(trade.get("price", trade.get("px")))
        taille = _nombre(trade.get("size", trade.get("sz")))
        if (not isinstance(coin, str) or not coin or instant is None
                or prix is None or taille is None or prix <= 0 or taille <= 0):
            ignorees += 1
            continue
        minutes = par_coin.setdefault(coin, {})
        cle = instant // MINUTE_MS
        minutes[cle] = minutes.get(cle, 0.0) + prix * taille
        debut = instant if debut is None else min(debut, instant)
        fin = instant if fin is None else max(fin, instant)
    minutes_fenetre = 0 if debut is None else (fin - debut) // MINUTE_MS + 1
    coins: dict[str, dict[str, Any]] = {}
    for coin, minutes in par_coin.items():
        mediane = _mediane(list(minutes.values()))
        coins[coin] = {
            "minutes_avec_trades": len(minutes),
            "part_minutes_avec_trades": (round(len(minutes) / minutes_fenetre, 4)
                                         if minutes_fenetre else None),
            "notionnel_median_par_minute_usd": None if mediane is None else round(mediane, 2),
            "multiple_de_l_ordre": (None if mediane is None or ordre_usd <= 0
                                    else round(mediane / ordre_usd, 2)),
        }
    multiples = [c["multiple_de_l_ordre"] for c in coins.values()
                 if c["multiple_de_l_ordre"] is not None]
    larges = sum(1 for m in multiples if m >= MULTIPLE_CAPACITE_LARGE)
    etroits = sorted(((c, v["multiple_de_l_ordre"]) for c, v in coins.items()
                      if v["multiple_de_l_ordre"] is not None and v["multiple_de_l_ordre"] < 1.0),
                     key=lambda kv: kv[1])
    return {
        "schema": SCHEMA, "famille": "trades_marche", "role": ROLE_CAPACITE,
        "ordre_usd": float(ordre_usd),
        "lignes_lues": lues, "lignes_ignorees": ignorees,
        "coins": len(coins), "minutes_dans_la_fenetre": int(minutes_fenetre),
        "multiple_median": _mediane([float(m) for m in multiples]),
        "coins_a_capacite_large": larges,
        "part_coins_a_capacite_large": round(larges / len(multiples), 4) if multiples else None,
        "coins_ou_une_minute_mediane_absorbe_moins_que_l_ordre": etroits[:25],
        "par_coin": dict(sorted(coins.items())),
        "lecture": ("multiple = notionnel median d'UNE minute de marche / ordre paper ; sous 1, "
                    "l'ordre depasse ce que le marche echange en une minute mediane"),
    }


def risque_de_liquidation(lignes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Fréquence des liquidations et ADL observées sur les comptes suivis."""
    par_type: dict[str, int] = {}
    comptes: dict[str, int] = {}
    coins: dict[str, int] = {}
    jours: set[int] = set()
    lues = ignorees = 0
    notionnel = 0.0
    for ligne in lignes or ():
        lues += 1
        instant = _entier(ligne.get("ts_ms"))
        compte = str(ligne.get("vault") or "").lower()
        coin = ligne.get("coin")
        if instant is None or not compte or not isinstance(coin, str) or not coin:
            ignorees += 1
            continue
        libelle = str(ligne.get("dir") or "(sans libelle)")
        par_type[libelle] = par_type.get(libelle, 0) + 1
        comptes[compte] = comptes.get(compte, 0) + 1
        coins[coin] = coins.get(coin, 0) + 1
        jours.add(instant // JOUR_MS)
        prix, taille = _nombre(ligne.get("px")), _nombre(ligne.get("sz"))
        if prix is not None and taille is not None:
            notionnel += abs(prix * taille)
    retenues = lues - ignorees
    return {
        "schema": SCHEMA, "famille": "liquidation", "role": ROLE_RISQUE,
        "lignes_lues": lues, "lignes_ignorees": ignorees,
        "evenements": retenues,
        "comptes_touches": len(comptes), "coins_touches": len(coins),
        "jours_avec_evenement": len(jours),
        "evenements_par_jour_actif": round(retenues / len(jours), 2) if jours else None,
        "notionnel_total_usd": round(notionnel, 2),
        "par_type": dict(sorted(par_type.items(), key=lambda kv: -kv[1])),
        "comptes_les_plus_touches": sorted(comptes.items(), key=lambda kv: -kv[1])[:10],
        "lecture": ("un evenement = une ligne de liquidation ou d'ADL impliquant un compte suivi ; "
                    "une frequence faible borne ce qu'un filtre de risque pourrait eviter"),
    }


def flux_de_capital(lignes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Dépôts et retraits : combien de jours-compte un PnL naïf serait-il faussé ?"""
    jours_compte: set[tuple[str, int]] = set()
    comptes: set[str] = set()
    depots = retraits = 0
    lues = ignorees = montants_inconnus = 0
    total_depots = total_retraits = 0.0
    for ligne in lignes or ():
        lues += 1
        instant = _entier(ligne.get("ts_ms"))
        compte = str(ligne.get("vault") or "").lower()
        if instant is None or not compte:
            ignorees += 1
            continue
        comptes.add(compte)
        jours_compte.add((compte, instant // JOUR_MS))
        delta = _nombre(ligne.get("delta_usd"))
        est_retrait = bool(ligne.get("est_retrait")) or (delta is not None and delta < 0)
        if ligne.get("montant_connu") is False or delta is None:
            montants_inconnus += 1          # le flux a eu lieu ; son montant, lui, n'est pas connu
        if est_retrait:
            retraits += 1
            total_retraits += abs(delta or 0.0)
        else:
            depots += 1
            total_depots += abs(delta or 0.0)
    return {
        "schema": SCHEMA, "famille": "vault_ledger", "role": ROLE_FLUX,
        "lignes_lues": lues, "lignes_ignorees": ignorees,
        "comptes_avec_flux": len(comptes),
        "jours_compte_avec_flux": len(jours_compte),
        "depots": depots, "retraits": retraits,
        "part_retraits": round(retraits / (depots + retraits), 4) if (depots + retraits) else None,
        "montants_inconnus": montants_inconnus,
        "total_depots_usd": round(total_depots, 2),
        "total_retraits_usd": round(total_retraits, 2),
        "lecture": ("chaque jour-compte liste ici est un jour ou la variation de valeur du compte "
                    "contient un flux : un PnL lu sans correction y est faux"),
    }


def resultat_overshoot(lignes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Distribution des dépassements — RÉSULTAT seulement, jamais une entrée de décision.

    Vérifie au passage ce qui motive l'exclusion : la présence de champs du futur dans la ligne.
    """
    champs_futurs = ("mid_fwd_15s", "mid_fwd_30s", "mid_fwd_60s", "mid_fwd_120s", "reversion_bps")
    amplitudes: list[float] = []
    reversions: list[float] = []
    par_sens: dict[str, int] = {}
    lues = ignorees = avec_futur = chemins_figes = 0
    for ligne in lignes or ():
        lues += 1
        amplitude = _nombre(ligne.get("overshoot_bps"))
        if amplitude is None:
            ignorees += 1
            continue
        if any(champ in ligne for champ in champs_futurs):
            avec_futur += 1
        # Chemin FIGE : les quatre prix futurs sont exactement le prix de l'evenement. Mesure du
        # 17/11 : 67,3 % des lignes, toutes sur des perps delistes que le collecteur n'ecartait pas.
        m0 = ligne.get("mid_at_event")
        futurs = [ligne.get(c) for c in champs_futurs[:4]]
        if m0 is not None and all(v is not None and v == m0 for v in futurs):
            chemins_figes += 1
        amplitudes.append(abs(amplitude))
        reversion = _nombre(ligne.get("reversion_bps"))
        if reversion is not None:
            reversions.append(reversion)
        sens = str(ligne.get("sens") or "(inconnu)")
        par_sens[sens] = par_sens.get(sens, 0) + 1
    amplitudes.sort()

    def _quantile(valeurs: list[float], q: float) -> float | None:
        return None if not valeurs else float(valeurs[min(len(valeurs) - 1,
                                                          int(round(q * (len(valeurs) - 1))))])

    return {
        "schema": SCHEMA, "famille": "overshoot", "role": ROLE_RESULTAT,
        "lignes_lues": lues, "lignes_ignorees": ignorees,
        "evenements": len(amplitudes),
        "lignes_portant_des_champs_du_futur": avec_futur,
        "part_avec_champs_du_futur": round(avec_futur / len(amplitudes), 4) if amplitudes else None,
        "champs_du_futur": list(champs_futurs),
        "amplitude_abs_bps": {"p50": _quantile(amplitudes, 0.5), "p90": _quantile(amplitudes, 0.9),
                              "p99": _quantile(amplitudes, 0.99)},
        "reversion_bps_mediane": _mediane(reversions),
        "part_reversion_nulle": (round(sum(1 for r in reversions if r == 0.0) / len(reversions), 4)
                                 if reversions else None),
        "chemins_figes": chemins_figes,
        "part_chemins_figes": round(chemins_figes / len(amplitudes), 4) if amplitudes else None,
        "par_sens": dict(sorted(par_sens.items(), key=lambda kv: -kv[1])),
        "motif_d_exclusion_comme_entree": (
            "LOOK_AHEAD_PAR_CONSTRUCTION : la ligne porte des prix posterieurs a l'evenement "
            "(mid_fwd_*) et leur consequence (reversion_bps)"),
    }


def applicabilite_microstructure(ouvertures_par_coin: Mapping[str, int],
                                 coins_micro: Iterable[str]) -> dict[str, Any]:
    """Part des ouvertures copiables qui tombent sur un coin couvert par la microstructure."""
    couverts = {str(c) for c in coins_micro or ()}
    total = sum(int(n) for n in ouvertures_par_coin.values())
    sur_micro = sum(int(n) for c, n in ouvertures_par_coin.items() if str(c) in couverts)
    hors = sorted(((c, int(n)) for c, n in ouvertures_par_coin.items() if str(c) not in couverts),
                  key=lambda kv: -kv[1])
    return {
        "schema": SCHEMA, "famille": "micro_l2+micro_trades", "role": ROLE_APPLICABILITE,
        "coins_micro": len(couverts),
        "coins_avec_ouvertures": len(ouvertures_par_coin),
        "ouvertures": total,
        "ouvertures_sur_coins_micro": sur_micro,
        "part_des_ouvertures_couvertes": round(sur_micro / total, 4) if total else None,
        "principaux_coins_NON_couverts": hors[:15],
        "lecture": ("un conditionnement de microstructure ne peut agir que sur cette part des "
                    "ouvertures ; le reste lui est structurellement invisible"),
    }


def exposition_a_la_capacite(volume_usd_par_coin: Mapping[str, float],
                             capacite: Mapping[str, Any], *,
                             seuil_etroit: float = 1.0) -> dict[str, Any]:
    """Quelle part du volume d'une stratégie tombe sur des coins où le marché est ÉTROIT ?

    ``capacite`` est la sortie de ``capacite_par_coin``. Trois classes, jamais deux :

    * ``etroit``  : une minute médiane de marché échange moins de ``seuil_etroit`` fois l'ordre ;
    * ``mesure``  : capacité connue et au-dessus du seuil ;
    * ``inconnu`` : aucun trade de marché observé pour ce coin sur la fenêtre. Une capacité non
      mesurée n'est PAS une capacité suffisante : elle est comptée à part.

    Le coût du simulateur (frais taker + demi-écart) ne contient pas d'impact. Sur la part
    ``etroit`` + ``inconnu`` du volume, son net est donc optimiste d'un montant que cette mesure
    ne chiffre pas — elle dit seulement sur quelle part du volume la question se pose.
    """
    par_coin = capacite.get("par_coin") if isinstance(capacite, Mapping) else None
    par_coin = par_coin if isinstance(par_coin, Mapping) else {}
    total = etroit = inconnu = 0.0
    coins_etroits: dict[str, float] = {}
    coins_inconnus: dict[str, float] = {}
    for coin, volume in (volume_usd_par_coin or {}).items():
        v = _nombre(volume)
        if v is None or v <= 0:
            continue
        total += v
        fiche = par_coin.get(str(coin))
        multiple = None if not isinstance(fiche, Mapping) else fiche.get("multiple_de_l_ordre")
        if multiple is None:
            inconnu += v
            coins_inconnus[str(coin)] = coins_inconnus.get(str(coin), 0.0) + v
        elif float(multiple) < float(seuil_etroit):
            etroit += v
            coins_etroits[str(coin)] = coins_etroits.get(str(coin), 0.0) + v
    def _part(x: float) -> float | None:
        return round(x / total, 4) if total > 0 else None
    return {
        "schema": SCHEMA,
        "volume_total_usd": round(total, 2),
        "part_volume_coins_etroits": _part(etroit),
        "part_volume_capacite_inconnue": _part(inconnu),
        "part_volume_capacite_mesuree_suffisante": _part(total - etroit - inconnu),
        "seuil_etroit": float(seuil_etroit),
        "principaux_coins_etroits": sorted(((c, round(v, 2)) for c, v in coins_etroits.items()),
                                           key=lambda kv: -kv[1])[:10],
        "principaux_coins_inconnus": sorted(((c, round(v, 2)) for c, v in coins_inconnus.items()),
                                            key=lambda kv: -kv[1])[:10],
    }


__all__ = [
    "exposition_a_la_capacite",
    "SCHEMA", "ROLE_CAPACITE", "ROLE_RISQUE", "ROLE_FLUX", "ROLE_RESULTAT", "ROLE_APPLICABILITE",
    "MULTIPLE_CAPACITE_LARGE", "capacite_par_coin", "risque_de_liquidation", "flux_de_capital",
    "resultat_overshoot", "applicabilite_microstructure",
]
