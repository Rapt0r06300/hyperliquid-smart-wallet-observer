"""LA SEULE POLITIQUE DONT LES PREUVES DISENT QU'ELLE A UNE ESPÉRANCE POSITIVE.

Tout le reste a été réfuté sur ces données : `fast_follow` rejeté à tous les horizons ≤ 300 s
**même à spread nul** (tué par les frais), DeepLOB à −4 242 bps, maker naïf à −3,42 bp de markout.
Reste le carry de funding cross-sectionnel — et la littérature dit précisément COMMENT le prendre,
parce que la façon évidente perd :

> La règle qui entre dès que le signal dépasse un seuil produit **le plus de revenu BRUT de toutes
> les règles testées** et finit à **−9 % à −15 % net** : l'exécution consomme trois fois le brut.
> La règle qui tient en continu et ne révise que sur une horloge de 30 jours — **1 à 5
> allers-retours en DEUX ANS** — rend **+2,7 % à +5,4 % net**, drawdown sous 2 %.
>
> **La direction du signal est un régime qui dure des mois ; son niveau est du bruit horaire.**

D'où les quatre règles de cette politique, et aucune n'est négociable :

1. **HORLOGE, PAS SEUIL.** On révise à date fixe. Un seuil déclenche sur le bruit horaire, dont
   la demi-vie mesurée est de 1,5 à 3,5 h, quand un aller-retour demande 100 à 135 h pour se
   rembourser. Confondre les deux, c'est tout le piège.
2. **AUCUNE SÉLECTION, AUCUN PARAMÈTRE AJUSTÉ.** Le PBO de 0,81 de ce labo vient de la
   **sélection**. Ici `k` et la fenêtre sont des CONVENTIONS fixées d'avance, jamais optimisées.
   Ce module expose volontairement TOUTES les valeurs de `k` pour que la dispersion soit visible :
   lire la meilleure et la présenter comme le résultat serait reproduire exactement l'erreur.
3. **CAUSALITÉ STRICTE.** Le classement à l'instant `t` n'utilise que du funding ANTÉRIEUR à `t`.
   Le funding de la période détenue est encaissé, jamais consulté pour décider.
4. **LES PORTES DE SURVIE D'ABORD.** Levier plafonné par `survie_position` (les excursions
   adverses mesurées imposent ≤ 0,24x sur un alt), notionnel ≥ 10 USD, horizon ≥ seuil à 95 %.

CONVENTION DE SIGNE. Sur Hyperliquid, un funding positif signifie que **les longs paient les
shorts**. Le rendement de carry d'un short vaut donc `+funding`, celui d'un long `−funding`. On
shorte le haut du classement et on longe le bas : les deux jambes encaissent.

PAPER / lecture seule.
"""
from __future__ import annotations

import bisect
import math
import statistics
from typing import Any, Mapping, Sequence

SHORT, LONG = -1, 1

MESURE = "MESURE"
NON_MESURABLE = "NON_MESURABLE"

PAS_ASSEZ_DE_COINS = "PAS_ASSEZ_DE_COINS"
PRIX_ABSENT = "PRIX_ABSENT_A_L_ENTREE_OU_A_LA_SORTIE"
PAS_ASSEZ_D_HISTOIRE = "PAS_ASSEZ_D_HISTOIRE"
AUCUNE_REVISION = "AUCUNE_REVISION_POSSIBLE"

#: Conventions fixees D'AVANCE, jamais ajustees sur le resultat.
HORLOGE_H = 720          # 30 jours — l'horloge publiee pour la regle patiente
FENETRE_H = 168          # 7 jours de funding anterieur pour classer
K_PAR_JAMBE = 5          # 5 shorts + 5 longs, dollar-neutre


def _fini(valeur: Any) -> float | None:
    try:
        sortie = float(valeur)
    except (TypeError, ValueError):
        return None
    return sortie if math.isfinite(sortie) else None


def index_glissant(serie: Mapping[int, float]) -> tuple[list[int], list[float], list[int]]:
    """Index de sommes prefixes pour une serie : `(heures triees, sommes, comptes)`.

    POURQUOI. `moyenne_anterieure` recalculait la moyenne des 96 heures **a partir de zero**, pour
    chaque coin, a chacun des milliers d'instants. Mesure du 15/11 : 31 ms par revision sur
    115 coins, soit **11 min** par lancement de l'outil — et **1,6 h** projetee a 1 100 jours et
    261 coins, alors que le reaper memoire de ce PC coupe les runs au-dela de ~30 min. **Le labo
    allait etre tue par ses propres donnees.**

    Or la fenetre GLISSE : de `t` a `t+12h` elle n'ajoute que 12 heures et n'en retire que 12.
    Avec des sommes prefixes, la moyenne sur n'importe quelle fenetre devient **une soustraction et
    une division**, trouvees par dichotomie — O(log n) au lieu de O(fenetre).

    **LES TROUS SONT PRESERVES** : on cumule la somme ET le compte, donc la moyenne porte sur les
    heures REELLEMENT presentes, pas sur la largeur de la fenetre. Sans le compte, une serie a
    trous serait divisee par trop et la moyenne diluee vers zero.
    """
    heures = sorted(h for h, v in serie.items() if _fini(v) is not None)
    sommes: list[float] = [0.0]
    comptes: list[int] = [0]
    for h in heures:
        sommes.append(sommes[-1] + float(serie[h]))
        comptes.append(comptes[-1] + 1)
    return heures, sommes, comptes


def moyenne_indexee(index: tuple[list[int], list[float], list[int]], *, fin_exclue: int,
                    fenetre_h: int) -> float | None:
    """Meme resultat que `moyenne_anterieure`, en O(log n). Borne haute toujours EXCLUE."""
    heures, sommes, comptes = index
    if not heures:
        return None
    debut = int(fin_exclue) - int(fenetre_h)
    gauche = bisect.bisect_left(heures, debut)
    droite = bisect.bisect_left(heures, int(fin_exclue))     # EXCLUE : pas bisect_right
    n = comptes[droite] - comptes[gauche]
    if n <= 0:
        return None
    return (sommes[droite] - sommes[gauche]) / n


def moyenne_anterieure(serie: Mapping[int, float], *, fin_exclue: int,
                       fenetre_h: int) -> float | None:
    """Moyenne du funding sur `[fin_exclue − fenetre, fin_exclue)` — **borne haute EXCLUE**.

    L'exclusion n'est pas un detail de style : inclure l'heure de decision ferait entrer dans le
    classement une information que l'on n'aurait pas eue au moment de decider. C'est la frontiere
    exacte entre une mesure et un lookahead.
    """
    debut = int(fin_exclue) - int(fenetre_h)
    valeurs = [v for h, v in serie.items() if debut <= h < int(fin_exclue)
               and _fini(v) is not None]
    if not valeurs:
        return None
    return sum(float(v) for v in valeurs) / len(valeurs)


def carry_encaisse(serie: Mapping[int, float], *, debut: int, fin_exclue: int,
                   sens: int) -> tuple[float, int]:
    """Funding effectivement encaissé sur la période DÉTENUE, et le nombre d'heures comptées.

    Un short encaisse `+funding`, un long `−funding`. On rend aussi le compte d'heures : une
    période à trous ne doit pas être présentée comme une période pleine.
    """
    total = 0.0
    heures = 0
    for h in range(int(debut), int(fin_exclue)):
        valeur = _fini(serie.get(h))
        if valeur is None:
            continue
        total += (valeur if sens == SHORT else -valeur)
        heures += 1
    return total, heures


def pnl_de_prix(prix: Mapping[int, float], *, debut: int, fin_exclue: int,
                sens: int) -> float | None:
    """Variation de prix sur la periode detenue. **None si un prix manque — jamais 0,0.**

    Zero signifierait « le prix n'a pas bouge », ce qui est une affirmation. Un prix manquant est
    une absence de mesure. Les confondre transformerait un trou de donnees en bonne nouvelle :
    exactement l'erreur que `markout` refuse deja pour les mids.
    """
    entree = _fini(prix.get(int(debut)))
    sortie = _fini(prix.get(int(fin_exclue) - 1))
    if entree is None or sortie is None or entree <= 0:
        return None
    variation = (sortie - entree) / entree
    return variation if sens == LONG else -variation


def une_revision(funding: Mapping[str, Mapping[int, float]], *, instant: int,
                 duree_h: int, fenetre_h: int, k: int,
                 prix: Mapping[str, Mapping[int, float]] | None = None,
                 inverser: bool = False,
                 signal: Mapping[str, Mapping[int, float]] | None = None,
                 poids: Mapping[str, float] | None = None,
                 index: Mapping[str, tuple[list[int], list[float], list[int]]] | None = None
                 ) -> dict[str, Any]:
    """Une révision : classer sur le PASSÉ, tenir, encaisser. Rien d'autre.

    Renvoie `NON_MESURABLE` quand le classement n'a pas assez de coins — et surtout pas un
    portefeuille plus petit construit en silence, qui changerait la stratégie sans le dire.
    """
    # `signal` separe CE QUI CLASSE de CE QUI EST ENCAISSE. Sans cette separation, on ne peut pas
    # repondre a la question « le funding n'est-il qu'un PROXY du momentum ? » — car classer sur le
    # funding force a le payer, alors que classer sur le momentum garde le gain de prix SANS le
    # cout de funding. Par defaut le signal EST le funding, donc le comportement ne change pas.
    source = signal if signal is not None else funding
    classables: list[tuple[float, str]] = []
    for coin, serie in source.items():
        if coin not in funding:
            continue          # on n'ouvre pas une jambe dont on ne saurait pas compter le funding
        # L'index pre-calcule donne le MEME resultat en O(log n) au lieu de O(fenetre) : on
        # l'utilise quand il existe, et on retombe sur le calcul direct sinon. Aucune API ne
        # change, donc aucun appelant existant n'est casse.
        if index is not None and coin in index:
            moyenne = moyenne_indexee(index[coin], fin_exclue=instant, fenetre_h=fenetre_h)
        else:
            moyenne = moyenne_anterieure(serie, fin_exclue=instant, fenetre_h=fenetre_h)
        if moyenne is not None:
            classables.append((moyenne, coin))
    if len(classables) < 2 * int(k):
        return {"verdict": NON_MESURABLE, "motif": PAS_ASSEZ_DE_COINS,
                "coins_classables": len(classables), "requis": 2 * int(k)}
    classables.sort(reverse=True)
    haut = [c for _, c in classables[:int(k)]]            # funding le PLUS HAUT
    bas = [c for _, c in classables[-int(k):]]            # le plus BAS
    if inverser:
        # LE LIVRE INVERSE : on LONGE le funding haut et on SHORTE le bas. On PAIE donc le
        # funding sur les deux jambes, et le pari devient purement un pari de PRIX (momentum).
        # ATTENTION : la seule facon correcte d'inverser est de retourner les POSITIONS.
        # Nier les valeurs de funding fabriquerait un revenu fictif — une strategie et son exact
        # oppose afficheraient alors le MEME gain, ce qui est impossible et signe l'artefact.
        shorts, longs = bas, haut
    else:
        shorts, longs = haut, bas

    jambes: list[dict[str, Any]] = []
    for coin, sens in [(c, SHORT) for c in shorts] + [(c, LONG) for c in longs]:
        rendement, heures = carry_encaisse(funding[coin], debut=instant,
                                           fin_exclue=instant + int(duree_h), sens=sens)
        jambe = {"coin": coin, "sens": sens, "rendement": rendement, "heures": heures,
                 "prix_pnl": None}
        if prix is not None:
            jambe["prix_pnl"] = pnl_de_prix(prix.get(coin, {}), debut=instant,
                                            fin_exclue=instant + int(duree_h), sens=sens)
        jambes.append(jambe)

    pleines = [j for j in jambes if j["heures"] > 0]
    if not pleines:
        return {"verdict": NON_MESURABLE, "motif": PAS_ASSEZ_D_HISTOIRE, "jambes": jambes}
    # Ponderation : equipondere en dollars par defaut. Un poids fait qu'une jambe volatile pese
    # moins en notionnel, ce qui reduit le repli du livre SANS changer le signal. Les poids sont
    # renormalises a somme 1 pour que le notionnel total reste le meme — sinon on comparerait
    # deux livres de tailles differentes et le gain serait un artefact d'echelle.
    def _poids(j):
        if poids is None:
            return 1.0
        valeur = _fini(poids.get(j["coin"]))
        return valeur if valeur is not None and valeur > 0 else 0.0
    somme_poids = sum(_poids(j) for j in pleines)
    if somme_poids <= 0:
        somme_poids = float(len(pleines))
        for j in pleines:
            j["poids"] = 1.0 / somme_poids
    else:
        for j in pleines:
            j["poids"] = _poids(j) / somme_poids
    brut = sum(j["rendement"] * j["poids"] for j in pleines)

    resultat = {"verdict": MESURE, "instant": int(instant), "jambes": jambes,
                "jambes_pleines": len(pleines), "rendement_brut": brut,
                "shorts": shorts, "longs": longs, "prix_pnl": None,
                "jambes_sans_prix": 0, "total_brut": brut}
    if prix is not None:
        avec_prix = [j for j in pleines if j["prix_pnl"] is not None]
        resultat["jambes_sans_prix"] = len(pleines) - len(avec_prix)
        if not avec_prix:
            # Aucune jambe chiffrable en prix : on ne rend PAS « prix neutre ».
            resultat["motif_prix"] = PRIX_ABSENT
        else:
            # Le livre est dollar-neutre : le PnL de prix du livre est la MOYENNE des jambes.
            total_poids = sum(j["poids"] for j in avec_prix)
            resultat["prix_pnl"] = (sum(j["prix_pnl"] * j["poids"] for j in avec_prix)
                                    / total_poids) if total_poids > 0 else None
            resultat["total_brut"] = brut + resultat["prix_pnl"]
    return resultat


def _compose(net_par_detention: float, horloge_h: int) -> float | None:
    """`(1+r)^(8760/H) - 1`. Refuse un net <= -100 % : un capital detruit ne se compose pas."""
    r = _fini(net_par_detention)
    if r is None or horloge_h <= 0 or r <= -1.0:
        return None
    rotations = 8760.0 / float(horloge_h)
    try:
        return math.exp(rotations * math.log1p(r)) - 1.0
    except (ValueError, OverflowError):
        return None


def mesurer(funding: Mapping[str, Mapping[int, float]], *,
            cout_aller_retour: float, horloge_h: int = HORLOGE_H,
            fenetre_h: int = FENETRE_H, k: int = K_PAR_JAMBE,
            prix: Mapping[str, Mapping[int, float]] | None = None,
            inverser: bool = False, pas_h: int | None = None,
            signal: Mapping[str, Mapping[int, float]] | None = None,
            poids: Mapping[str, float] | None = None) -> dict[str, Any]:
    """La règle patiente, de bout en bout, sur toute l'histoire disponible.

    Le coût est prélevé **une fois par révision** — c'est tout l'intérêt de l'horloge : une règle
    à seuil le paierait des dizaines de fois sur la même période.

    `pas_h` sépare la DÉTENTION (`horloge_h`) de la CADENCE DE MESURE. À 211 jours d'histoire et
    une horloge de 30 jours, on n'obtient que **6 observations disjointes** — et une seule période
    défavorable y pèse alors pour un sixième du verdict, ce qui s'est produit ici (une révision à
    −22,8 % écrasait les cinq autres). Démarrer une détention chaque semaine (`pas_h=168`) donne
    environ quatre fois plus d'observations sur la même histoire et une estimation de la moyenne
    bien plus stable.

    **MAIS CES FENÊTRES SE CHEVAUCHENT, donc elles ne sont PAS indépendantes** : elles partagent
    jusqu'à 29 jours sur 30. Le nombre d'observations gonfle sans que l'information suive. On ne
    peut donc PAS en tirer un intervalle de confiance ou un t de Student comme s'il s'agissait de
    tirages distincts. Le résultat le dit en clair (`fenetres_independantes`), et la part de
    périodes positives reste la lecture honnête.
    """
    heures = sorted({h for serie in funding.values() for h in serie})
    if not heures:
        return {"verdict": NON_MESURABLE, "motif": PAS_ASSEZ_D_HISTOIRE}
    premiere = heures[0] + int(fenetre_h)
    derniere = heures[-1] - int(horloge_h)
    if derniere < premiere:
        return {"verdict": NON_MESURABLE, "motif": AUCUNE_REVISION,
                "heures_disponibles": len(heures),
                "lecture": (f"{len(heures)} heures d'histoire : il en faut au moins "
                            f"{int(fenetre_h) + int(horloge_h)} pour une seule revision "
                            "(fenetre de classement + duree de detention).")}

    cadence = int(pas_h) if pas_h else int(horloge_h)
    if cadence <= 0:
        return {"verdict": NON_MESURABLE, "motif": "CADENCE_INVALIDE"}
    revisions: list[dict[str, Any]] = []
    instant = premiere
    while instant <= derniere:
        revisions.append(une_revision(funding, instant=instant, duree_h=int(horloge_h),
                                      fenetre_h=int(fenetre_h), k=int(k), prix=prix,
                                      inverser=bool(inverser), signal=signal, poids=poids))
        instant += cadence

    mesurees = [r for r in revisions if r.get("verdict") == MESURE]
    if not mesurees:
        return {"verdict": NON_MESURABLE, "motif": PAS_ASSEZ_DE_COINS,
                "revisions_tentees": len(revisions)}

    bruts = [float(r["rendement_brut"]) for r in mesurees]
    cout = _fini(cout_aller_retour) or 0.0
    # Le TOTAL comprend le prix quand il est mesurable. Mesurer le seul funding d'un livre
    # long/short serait la meme faute que mesurer le seul demi-spread d'un remplissage passif.
    totaux = [float(r.get("total_brut", r["rendement_brut"])) for r in mesurees]
    nets = [t - cout for t in totaux]
    prix_pnls = [float(r["prix_pnl"]) for r in mesurees if r.get("prix_pnl") is not None]
    positives = sum(1 for n in nets if n > 0)
    total = sum(nets)
    chevauchent = cadence < int(horloge_h)
    # Avec des fenetres qui se chevauchent, la duree REELLEMENT couverte est l'etendue du
    # calendrier, pas la somme des detentions : sommer donnerait un annualise gonfle d'autant.
    duree_totale_h = (len(mesurees) * int(horloge_h) if not chevauchent
                      else (mesurees[-1]["instant"] - mesurees[0]["instant"] + int(horloge_h)))
    # L'annualise d'un chevauchement se lit sur la MOYENNE par detention, jamais sur la somme :
    # additionner des periodes qui se recouvrent compterait le meme gain plusieurs fois.
    annualise = ((statistics.fmean(nets) / int(horloge_h)) * 8760.0 if chevauchent
                 else (total / duree_totale_h) * 8760.0 if duree_totale_h else None)

    return {
        "verdict": MESURE,
        "revisions": len(mesurees),
        "cadence_h": cadence,
        "fenetres_independantes": not chevauchent,
        "revisions_ecartees": len(revisions) - len(mesurees),
        "cout_par_revision": cout,
        "brut_moyen": statistics.fmean(bruts),
        "funding_moyen": statistics.fmean(bruts),
        "prix_pnl_moyen": statistics.fmean(prix_pnls) if prix_pnls else None,
        "revisions_avec_prix": len(prix_pnls),
        "net_moyen": statistics.fmean(nets),
        "net_median": statistics.median(nets),
        "net_min": min(nets),
        "net_max": max(nets),
        "net_total": total,
        "part_positive": positives / len(nets),
        "annualise": annualise,
        # L'annualise ci-dessus est SIMPLE. Un livre qui tourne 91 fois par an reinvestit son
        # gain : ignorer la composition sous-estime le resultat d'environ un quart. On publie les
        # deux, car la version simple reste la bonne pour comparer des horizons entre eux.
        "annualise_compose": _compose(statistics.fmean(nets), int(horloge_h)),
        "duree_couverte_h": duree_totale_h,
        "nets": nets,
        "lecture": (
            f"{len(mesurees)} detention(s)"
            + ("" if not chevauchent else " CHEVAUCHANTES (non independantes)")
            + f" sur {duree_totale_h} h | "
            f"funding {statistics.fmean(bruts)*100:+.3f} % | "
            + (f"prix {statistics.fmean(prix_pnls)*100:+.3f} % | " if prix_pnls
               else "prix NON MESURE | ")
            + f"cout {cout*100:.3f} % | net {statistics.fmean(nets)*100:+.3f} % par revision | "
            f"{positives}/{len(nets)} positives | "
            + (f"annualise {annualise*100:+.2f} %" if annualise is not None else "")),
    }


def balayage_sans_selection(funding: Mapping[str, Mapping[int, float]], *,
                            cout_aller_retour: float, ks: Sequence[int],
                            horloge_h: int = HORLOGE_H, fenetre_h: int = FENETRE_H,
                            prix: Mapping[str, Mapping[int, float]] | None = None
                            ) -> dict[str, Any]:
    """Toutes les valeurs de `k`, **sans en élire aucune**.

    Ce n'est pas une optimisation : c'est son contraire. Publier la dispersion complète empêche de
    lire le meilleur `k` et de le présenter comme le résultat — l'erreur exacte qui a produit le
    PBO de 0,81. La convention `K_PAR_JAMBE` reste la seule valeur de référence, et elle a été
    fixée AVANT de voir ces chiffres.
    """
    resultats = {int(k): mesurer(funding, cout_aller_retour=cout_aller_retour,
                                 horloge_h=horloge_h, fenetre_h=fenetre_h, k=int(k),
                                 prix=prix)
                 for k in ks}
    mesures = {k: r for k, r in resultats.items() if r.get("verdict") == MESURE}
    annualises = {k: r["annualise"] for k, r in mesures.items() if r.get("annualise") is not None}
    return {
        "par_k": resultats,
        "convention": int(K_PAR_JAMBE),
        "annualises": annualises,
        "part_des_k_positifs": (sum(1 for v in annualises.values() if v > 0) / len(annualises))
        if annualises else None,
        "avertissement": ("Dispersion publiee EXPRES. Elire le meilleur k reproduirait le PBO de "
                          "0,81. Seule la convention fixee d'avance compte comme resultat."),
    }


__all__ = ["SHORT", "LONG", "_compose", "index_glissant", "moyenne_indexee", "MESURE", "NON_MESURABLE", "PAS_ASSEZ_DE_COINS",
           "PAS_ASSEZ_D_HISTOIRE", "AUCUNE_REVISION", "HORLOGE_H", "FENETRE_H", "K_PAR_JAMBE",
           "PRIX_ABSENT", "moyenne_anterieure", "carry_encaisse", "pnl_de_prix",
           "une_revision", "mesurer",
           "balayage_sans_selection"]
