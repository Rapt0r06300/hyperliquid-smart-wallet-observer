"""QUOI RATTRAPER D'ABORD, ET POURQUOI CE N'EST PAS CE QUI MANQUE LE PLUS.

LE PIEGE QUE CE MODULE EVITE
----------------------------
Le 15/11, deux passes de rattrapage ont tourne en parallele : le funding profond et les bougies
journalieres. Les deux ont ete tuees par le systeme pour manque de memoire, et le bilan des 41
minutes servies tenait en deux coins sur 261. Trois erreurs se cumulaient :

1. **l'ordre** : le funding (94 h de requetes pour 889 jours par coin) est parti AVANT les bougies
   journalieres (1,8 h pour 2 279 jours par coin), alors que le funding profond ne sert a RIEN sans
   un prix en face. On payait 50 fois plus cher la moitie de la paire ;
2. **le parallelisme** : deux passes, deux processus, deux fois la memoire — et le systeme coupe ;
3. **le grain** : chaque passe vidait un coin avant de passer au suivant, alors que la fenetre
   qu'une strategie transversale peut mesurer est l'INTERSECTION des historiques de son livre.

LA REGLE QUI EN SORT, ET ELLE EST QUANTITATIVE
----------------------------------------------
On classe par **jours-coins gagnes par seconde de requete**, pas par manque absolu. C'est le seul
critere qui fait passer le pas journalier (une requete rend jusqu'a 5 000 bougies, donc toute
l'histoire d'un coin d'un coup) devant le funding (une requete rend 500 points, soit 20,8 jours).

    rendement = jours-coins manquants / cout estime en secondes

Et une contrainte de PRECEDENCE s'ajoute au rendement : un prix sans funding reste mesurable (le
funding est un cout, pas le signal), mais un funding sans prix ne mesure RIEN — la carry se mesure
`sens x variation_de_prix + funding`. Les prix passent donc toujours avant.

CE QUE CE MODULE REFUSE
-----------------------
* **plus d'une tache a la fois** : `concurrence()` rend 1, toujours. C'est ce qui a fait tuer les
  passes du 15/11, et un rattrapage deux fois plus rapide qui se fait tuer rend zero ;
* **un budget sans fin** : chaque tache recoit une part BORNEE du budget total, et une tache qui
  n'a rien a faire ne consomme pas sa part ;
* **estimer un cout sans debit** : un budget de debit nul ou negatif n'est pas « instantane », il
  est invalide.

Pur : aucune horloge, aucun reseau, aucun fichier. Lecture seule / PAPER.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

JOUR_MS = 86_400_000
HEURE_MS = 3_600_000

#: Poids d'une reponse dans le budget de debit de la venue (base 20, plus 1 par 60 bougies).
POIDS_BASE = 20.0
#: `candleSnapshot` ne rend que les 5 000 dernieres bougies d'un pas.
CAP_CANDLES = 5000
#: `fundingHistory` est pagine par 500 points horaires, soit 20,83 jours par requete.
PAGE_FUNDING = 500

FAMILLE_PRIX = "PRIX"
FAMILLE_PORTAGE = "PORTAGE"
FAMILLE_FILLS = "FILLS"


@dataclass(frozen=True, slots=True)
class Tache:
    """Une tache de rattrapage, avec de quoi estimer son cout AVANT de la lancer."""

    nom: str
    famille: str
    serie: str                     #: la cle d'etat ("1h", "1d", "funding"...)
    profondeur_cible_j: float      #: ce que la venue peut rendre sur ce pas
    jours_par_requete: float       #: combien de jours une seule requete rapporte
    poids_par_requete: float       #: ce que cette requete coute au budget de debit
    #: Les taches dont celle-ci depend. Un funding sans prix en face ne mesure RIEN.
    depend_de: tuple[str, ...] = ()
    pourquoi: str = ""

    def requetes_pour(self, jours_coins_manquants: float) -> int:
        """Pages SEQUENTIELLES pour combler ce manque **sur UN coin**. Au moins 1 s'il manque qqch.

        Ne vaut que pour une serie paginee, ou un coin exige page apres page (le funding : 500
        points par reponse, soit 20,8 jours). **Ne JAMAIS l'appliquer a un total multi-coins** :
        voir `cout_s`, qui prend un nombre de requetes et refuse de le deviner.
        """
        manque = max(0.0, float(jours_coins_manquants))
        if manque <= 0.0:
            return 0
        return max(1, math.ceil(manque / max(1e-9, float(self.jours_par_requete))))

    def cout_s(self, requetes: int, *, budget_par_minute: float) -> float:
        """Secondes de requetes pour `requetes` appels, au debit donne.

        15/11/2026 — CETTE FONCTION PRENAIT DES JOURS-COINS, ET L'ESTIMATION ETAIT FAUSSE DE x87.
        Elle divisait le manque total par le rendement d'une requete : 10 491 jours-coins manquants
        / 5 000 jours par requete = **3 requetes** annoncees pour le pas journalier. La realite
        mesuree : **261 coins sur 261 avaient au moins un jour de retard, donc 261 requetes**. Le
        rapport est juste pour une serie paginee sur UN coin, et faux des qu'on agrege des coins :
        un coin auquel il ne manque qu'un seul jour coute une requete ENTIERE, pas 1/5 000e.
        Le nombre de requetes se COMPTE donc coin par coin (`manque_*`), il ne se deduit pas.
        """
        debit = float(budget_par_minute)
        if not (debit > 0.0):
            raise ValueError("budget_par_minute doit etre > 0 : un debit nul n'est pas instantane")
        return max(0, int(requetes)) * float(self.poids_par_requete) / debit * 60.0


def _profondeur_pas(pas_ms: int) -> float:
    return CAP_CANDLES * float(pas_ms) / JOUR_MS


#: Les taches de rattrapage, dans l'ordre ou elles ont ete etablies — PAS l'ordre d'execution,
#: qui est calcule par `ordonner()` a partir du manque reellement mesure.
TACHES: tuple[Tache, ...] = (
    Tache("bougies-1d", FAMILLE_PRIX, "1d", _profondeur_pas(JOUR_MS), _profondeur_pas(JOUR_MS),
          POIDS_BASE + CAP_CANDLES / 60.0,
          pourquoi="le pas le PLUS PROFOND (1 101 j sondes, jusqu'a 2 280 j selon la cotation) et "
                   "le moins cher : une requete rend toute l'histoire d'un coin"),
    Tache("bougies-4h", FAMILLE_PRIX, "4h", _profondeur_pas(4 * HEURE_MS), _profondeur_pas(4 * HEURE_MS),
          POIDS_BASE + CAP_CANDLES / 60.0,
          pourquoi="833 j a 6 points par jour : le pas qui garde l'HEURE d'entree sur ~2,3 ans, "
                   "la ou le journalier l'efface"),
    Tache("bougies-1h", FAMILLE_PRIX, "1h", _profondeur_pas(HEURE_MS), _profondeur_pas(HEURE_MS),
          POIDS_BASE + CAP_CANDLES / 60.0,
          pourquoi="208 j au pas exact de la decision horaire"),
    Tache("funding-profond", FAMILLE_PORTAGE, "funding", 1100.0, PAGE_FUNDING * HEURE_MS / JOUR_MS,
          POIDS_BASE + PAGE_FUNDING / 20.0, depend_de=("bougies-1d",),
          pourquoi="le cout de portage, et la PRIME (`premium`) qui vient dans la meme reponse ; "
                   "inutile sans un prix en face, d'ou la dependance"),
    Tache("bougies-5m", FAMILLE_PRIX, "5m", _profondeur_pas(300_000), _profondeur_pas(300_000),
          POIDS_BASE + CAP_CANDLES / 60.0,
          pourquoi="17 j seulement : utile pour l'execution fine, inutile pour l'histoire longue"),
)

TACHES_PAR_NOM = {t.nom: t for t in TACHES}


def concurrence(*, niveau_ram: str = "VERT") -> int:
    """Combien de taches en parallele. **Toujours 1**, quel que soit le niveau.

    Ce n'est pas une precaution timide : les deux passes du 15/11 ont ete TUEES par le systeme pour
    manque de memoire, et une passe tuee rend zero. Un rattrapage sequentiel deux fois plus lent
    qu'un parallele qui meurt reste infiniment plus rapide. La valeur est rendue par une fonction,
    et non codee en dur chez l'appelant, pour que ce raisonnement ait un seul endroit.
    """
    return 1


def manque_bougies(*, coins: Sequence[str], etat_serie: Mapping[str, Any], profondeur_j: float,
                   now_ms: int, pas_ms: int) -> dict[str, Any]:
    """``{"jours_coins", "requetes"}`` pour un pas de bougies.

    Un coin ABSENT de l'etat n'a jamais ete tire : il lui manque toute la profondeur. Un coin
    present a deja recu sa profondeur complete au premier tirage (une requete rend 5 000 bougies) ;
    il ne lui manque donc que son RETARD depuis le dernier point.

    **Les requetes se COMPTENT, coin par coin.** Un coin en retard d'un seul jour coute une requete
    entiere : le collecteur demande `[dernier + un pas, maintenant]` et rend une bougie. Deduire le
    nombre de requetes du total de jours manquants annoncait **3 requetes** la ou il en fallait
    **261** (mesure du 15/11, pas journalier) — et le budget alloue a la tache etait donc 87 fois
    trop court. Un coin a jour a moins d'un pas de retard : lui, ne coute rien.
    """
    jours = 0.0
    requetes = 0
    for coin in coins:
        dernier = etat_serie.get(str(coin))
        try:
            dernier_ms = int(dernier) if dernier else 0
        except (TypeError, ValueError):
            dernier_ms = 0
        if not dernier_ms:
            jours += max(0.0, float(profondeur_j))
            requetes += 1
            continue
        retard_ms = max(0, int(now_ms) - dernier_ms)
        jours += retard_ms / JOUR_MS
        if retard_ms >= max(1, int(pas_ms)):
            requetes += 1                 # une bougie close de retard = une requete
    return {"jours_coins": jours, "requetes": requetes}


def manque_funding(*, coins: Sequence[str], etat_ancien: Mapping[str, Any],
                   etat_recent: Mapping[str, Any], profondeur_j: float, now_ms: int,
                   jours_par_page: float = PAGE_FUNDING * HEURE_MS / JOUR_MS) -> dict[str, Any]:
    """``{"jours_coins", "requetes"}`` pour le funding — **les DEUX fronts comptent**.

    Le manque d'un coin est ce qu'il reste a creuser (sous son point le plus ancien) PLUS son
    retard (au-dessus de son point le plus recent). Ne compter que le retard est exactement
    l'erreur qui a fait croire 115 coins « a jour » alors qu'ils plafonnaient a 211 jours.

    Ici, et contrairement aux bougies, les pages sont SEQUENTIELLES par coin : creuser 889 jours
    demande 43 requetes pour ce seul coin. On les compte donc coin par coin, puis on somme.
    """
    jours = 0.0
    requetes = 0
    page = max(1e-9, float(jours_par_page))
    for coin in coins:
        nom = str(coin)
        try:
            ancien = int(etat_ancien.get(nom) or 0)
        except (TypeError, ValueError):
            ancien = 0
        try:
            recent = int(etat_recent.get(nom) or 0)
        except (TypeError, ValueError):
            recent = 0
        if not ancien and not recent:
            jours += max(0.0, float(profondeur_j))        # jamais vu : toute la profondeur
            requetes += max(1, math.ceil(float(profondeur_j) / page))
            continue
        profondeur_detenue = (int(now_ms) - ancien) / JOUR_MS if ancien else 0.0
        a_creuser = max(0.0, float(profondeur_j) - profondeur_detenue)
        jours += a_creuser
        if a_creuser > 0:
            requetes += max(1, math.ceil(a_creuser / page))
        if recent:
            retard_j = max(0.0, (int(now_ms) - recent) / JOUR_MS)
            jours += retard_j
            if (int(now_ms) - recent) >= HEURE_MS:
                requetes += max(1, math.ceil(retard_j / page))            # a prolonger
    return {"jours_coins": jours, "requetes": requetes}


#: Le pas, en millisecondes, de chaque serie de bougies. Il decide a partir de quand un coin est
#: « en retard » : moins d'une bougie close de retard ne coute aucune requete.
PAS_PAR_SERIE = {"5m": 300_000, "1h": HEURE_MS, "4h": 4 * HEURE_MS, "1d": JOUR_MS}


def manques(*, coins: Sequence[str], etat: Mapping[str, Mapping[str, Any]], now_ms: int,
            profondeur_funding_j: float = 1100.0) -> dict[str, dict[str, Any]]:
    """Le besoin de CHAQUE tache — jours-coins (la VALEUR) **et** requetes (le COUT)."""
    out: dict[str, dict[str, Any]] = {}
    for tache in TACHES:
        if tache.famille == FAMILLE_PORTAGE:
            out[tache.nom] = manque_funding(
                coins=coins, etat_ancien=etat.get("funding_ancien") or {},
                etat_recent=etat.get("funding") or {},
                profondeur_j=profondeur_funding_j, now_ms=now_ms,
                jours_par_page=tache.jours_par_requete)
        else:
            out[tache.nom] = manque_bougies(
                coins=coins, etat_serie=etat.get(tache.serie) or {},
                profondeur_j=tache.profondeur_cible_j, now_ms=now_ms,
                pas_ms=PAS_PAR_SERIE.get(tache.serie, JOUR_MS))
    return out


def besoin(jours_coins: float, requetes: int) -> dict[str, Any]:
    """Un besoin explicite : la VALEUR (jours-coins) et le COUT (requetes), jamais l'un deduit de
    l'autre. C'est la lecon de l'estimation fausse de x87 du 15/11."""
    return {"jours_coins": float(jours_coins), "requetes": int(requetes)}


def ordonner(manques_par_tache: Mapping[str, Mapping[str, Any]], *,
             budget_par_minute: float = 100.0) -> list[dict[str, Any]]:
    """Les taches a faire, **du meilleur rendement au pire**, precedences respectees.

    `rendement` = jours-coins gagnes par seconde de requete. C'est ce rapport, et non le manque
    absolu, qui fait passer le journalier (une requete = toute l'histoire d'un coin) devant le
    funding (une requete = 20,8 jours). Une tache sans manque est ECARTEE : on ne depense pas une
    requete pour verifier ce que l'etat dit deja.

    Les precedences passent AVANT le rendement : une tache ne peut pas devancer celle dont elle
    depend, meme si son rendement est meilleur. Un funding sans prix en face ne mesure rien.

    Chaque entree de `manques_par_tache` porte `jours_coins` ET `requetes` (cf. `besoin()`) : le
    cout ne se deduit PAS de la valeur.
    """
    lignes: list[dict[str, Any]] = []
    for tache in TACHES:
        brut = manques_par_tache.get(tache.nom) or {}
        manque = float(brut.get("jours_coins", 0.0) or 0.0)
        requetes = int(brut.get("requetes", 0) or 0)
        if manque <= 0.0 or requetes <= 0:
            continue
        cout = tache.cout_s(requetes, budget_par_minute=budget_par_minute)
        lignes.append({"nom": tache.nom, "famille": tache.famille, "serie": tache.serie,
                       "manque_jours_coins": manque,
                       "requetes": requetes, "cout_s": cout,
                       "rendement": (manque / cout) if cout > 0 else 0.0,
                       "depend_de": tache.depend_de, "pourquoi": tache.pourquoi})
    lignes.sort(key=lambda x: -x["rendement"])

    # Tri topologique STABLE : on remonte une dependance juste devant son dependant plutot que de
    # re-trier tout, pour que l'ordre de rendement soit conserve partout ailleurs.
    final: list[dict[str, Any]] = []
    restants = list(lignes)
    garde = 0
    while restants and garde <= len(lignes) * len(lignes) + len(lignes):
        garde += 1
        ligne = restants.pop(0)
        attendues = [d for d in ligne["depend_de"]
                     if any(r["nom"] == d for r in restants)]
        if attendues:
            # une dependance est encore a faire : elle doit passer d'abord
            devant = next(r for r in restants if r["nom"] == attendues[0])
            restants.remove(devant)
            restants.insert(0, ligne)
            restants.insert(0, devant)
            continue
        final.append(ligne)
    final.extend(restants)                 # garde-fou : un cycle ne doit pas perdre de taches
    return final


def repartir_budget(plan: Sequence[Mapping[str, Any]], *, total_s: float,
                    minimum_s: float = 60.0) -> list[dict[str, Any]]:
    """Donne a chaque tache sa part du budget total, **dans l'ordre du plan**.

    On sert les premieres taches a leur cout COMPLET tant que le budget suit : fractionner
    uniformement donnerait a chacune un bout trop court pour finir quoi que ce soit, et une
    profondeur a moitie prise ne se mesure pas mieux qu'une profondeur absente. La derniere tache
    servie recoit le reste, meme partiel : elle reprendra au passage suivant.
    """
    reste = max(0.0, float(total_s))
    out: list[dict[str, Any]] = []
    for ligne in plan:
        if reste <= 0.0:
            out.append({**ligne, "budget_s": 0.0, "sert": False,
                        "note": "budget epuise : cette tache attend le passage suivant"})
            continue
        part = min(float(ligne["cout_s"]), reste)
        if part < float(minimum_s) and float(ligne["cout_s"]) > part:
            # Moins que le minimum utile : on ne la commence pas pour rien.
            out.append({**ligne, "budget_s": 0.0, "sert": False,
                        "note": f"reste {part:.0f} s < minimum utile {minimum_s:.0f} s"})
            continue
        out.append({**ligne, "budget_s": part, "sert": True,
                    "note": ("budget complet" if part >= float(ligne["cout_s"])
                             else "budget partiel : reprise au passage suivant")})
        reste -= part
    return out


def eta_heures(plan: Sequence[Mapping[str, Any]]) -> float:
    """Combien d'heures de requetes pour tout combler, au debit utilise pour le plan."""
    return sum(float(x.get("cout_s") or 0.0) for x in plan) / 3600.0


__all__ = ["JOUR_MS", "HEURE_MS", "POIDS_BASE", "CAP_CANDLES", "PAGE_FUNDING",
           "FAMILLE_PRIX", "FAMILLE_PORTAGE", "FAMILLE_FILLS", "Tache", "TACHES",
           "TACHES_PAR_NOM", "concurrence", "manque_bougies", "manque_funding", "manques",
           "ordonner", "repartir_budget", "eta_heures", "besoin", "PAS_PAR_SERIE"]
