"""#365 / H-137 — Funding cross-venue, sur le MÊME coin. **ET LE PIÈGE D'UNITÉ QUI M'A EU.**

═══════════════════════════════════════════════════════════════════════════════════════════════
🔴 LIRE CECI AVANT DE TOUCHER A CE FICHIER
═══════════════════════════════════════════════════════════════════════════════════════════════

La 1re version de ce module annonçait **38 % APR** sur l'exemple de la doc Hyperliquid.
C'était **FAUX**. Voici pourquoi, parce que ça se reproduira ailleurs :

    ["AVAX", [["BinPerp",   {"fundingRate": "0.0001"}],      <- taux sur **8 HEURES**
              ["HlPerp",    {"fundingRate": "0.0000125"}],   <- taux sur **1 HEURE**
              ["BybitPerp", {"fundingRate": "0.0001"}]]]     <- taux sur **8 HEURES**

    0.0001 / 8 = 0.0000125.

    ***LES TROIS VENUES SONT EXACTEMENT D'ACCORD.***

Doc officielle (hyperliquid-docs/trading/funding) :
  « the interest rate component is predetermined at **0.01% every 8 hours, which is 0.00125%
    every hour** »
  « **The funding rate on Hyperliquid is paid every hour.** »
  « funding is paid every hour at **one eighth** of the computed rate »

Mon « écart de 8x » n'était pas un écart : **c'était l'intervalle de funding.**

    ***C'EST LE BID-ASK BOUNCE DE T1b, EN COSTUME NEUF :***
    ***comparer deux nombres qui ne sont pas dans la MÊME UNITÉ, et récolter un edge fantôme.***

Le module aurait crié « EXPLOITABLE, 38 % APR » sur **presque chaque coin**.
Ce n'est ni un test ni un invariant qui l'a attrapé : c'est la règle de T1b --
***quand un résultat est beau, regarde QUI survit avant de l'annoncer.***

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE LE MODULE FAIT MAINTENANT
═══════════════════════════════════════════════════════════════════════════════════════════════

  1. **NORMALISE** chaque taux en bps/heure, via un intervalle **SOURCÉ** par venue.
  2. **DENY-BY-DEFAULT sur l'unité** : une venue dont l'intervalle n'est pas dans la table est
     **ÉCARTÉE**, jamais devinée. *Une unité inconnue est pire qu'une donnée absente : elle
     produit un chiffre qui a l'air juste.*
  3. **GARDE ANTI-ERREUR-D'UNITÉ** : si deux taux bruts sont dans un rapport suspect (~8, ~4,
     ~3, ~1/8...), c'est la signature d'un décalage de période, PAS d'un écart économique.
     -> `MOTIF_RAPPORT_SUSPECT`. **Ce garde détecte ma propre classe de bug.**
  4. Le rendement est jugé sur **DEUX** venues de capital (leçon T2b : le carry HYPE rendait
     2 %, pas 4 %, parce qu'on avait oublié la marge de la 2e jambe).

POURQUOI CETTE PISTE MÉRITE QUAND MÊME D'EXISTER : X-04 (perp<->perp, coins DIFFÉRENTS) est mort
(0/120) et en a tiré la loi ***une couverture ne vaut que si c'est le MÊME actif***. HL perp <->
Binance perp sur le **même coin**, c'est le même actif. C'est la seule forme de H-137 qui obéit
à notre propre loi. Reste à savoir s'il reste un écart **une fois les unités remises d'équerre**.

🚨 ET SURTOUT : **NOUS NE POUVONS PAS TRADER SUR BINANCE NI BYBIT.** Aucune intégration, système
paper-only. Ce module MESURE. *Mesurer un edge n'est pas le capturer.*

PUR : aucun appel réseau ici. Aucun ordre réel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# L'INTERVALLE DE FUNDING PAR VENUE — **SOURCÉ**, jamais deviné.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
# Hyperliquid : doc officielle trading/funding -> « paid every hour », « one eighth of the
#               computed [8h] rate ». Donc le `fundingRate` de HlPerp est **HORAIRE**.
# Binance / Bybit : funding standard **8 heures**. C'est la convention des CEX, et c'est ce que
#               l'exemple de la doc HL confirme numériquement (0.0001 = 8 x 0.0000125).
#
# ⚠️ CE QUE JE NE SAIS PAS, ET QUE JE NE DEVINE PAS :
#    Binance et Bybit passent CERTAINES paires en funding 4 h (voire 1 h) en cas de forte
#    déviation. La table ci-dessous est donc une **hypothèse de convention**, pas une vérité
#    par coin. C'est exactement pour ça que le garde `MOTIF_RAPPORT_SUSPECT` existe : il
#    attrape le cas où la période réelle n'est pas celle qu'on croit.
INTERVALLE_FUNDING_HEURES: dict[str, float] = {
    "HlPerp": 1.0,
    "BinPerp": 8.0,
    "BybitPerp": 8.0,
}

# Nos coûts : 4 exécutions (2 venues x aller-retour). Aucun rebate supposé (on n'en a pas).
COUT_4_EXECUTIONS_BPS = 12.0

# Le capital est immobilisé sur DEUX venues. Juger sur une seule jambe = doubler le chiffre.
CAPITAL_SUR_DEUX_VENUES = 2.0

# Au-delà, l'écart d'aujourd'hui ne dit plus rien de demain.
HEURES_MAX = 24.0

# ── LE GARDE ANTI-ERREUR-D'UNITÉ ───────────────────────────────────────────────────────────────
# Si deux taux BRUTS sont dans un rapport très proche d'un rapport de PÉRIODES usuel
# (8, 4, 3, 2 — et leurs inverses), c'est la signature d'un décalage d'intervalle, pas d'un
# écart économique. Un vrai écart de funding ne tombe pas pile sur 8,000.
RAPPORTS_DE_PERIODE_SUSPECTS = (2.0, 3.0, 4.0, 6.0, 8.0)
TOLERANCE_RAPPORT = 0.02          # +/- 2 %

MOTIF_UNE_SEULE_VENUE = "UNE_SEULE_VENUE_NORMALISABLE_AUCUN_ECART_A_MESURER"
MOTIF_ECART_TROP_FAIBLE = "ECART_DE_FUNDING_TROP_FAIBLE_POUR_AMORTIR_4_EXECUTIONS"
MOTIF_ECART_MESURE = "ECART_DE_FUNDING_MESURE_ENTRE_VENUES"
MOTIF_INTERVALLE_INCONNU = "INTERVALLE_DE_FUNDING_INCONNU_VENUE_ECARTEE"
MOTIF_RAPPORT_SUSPECT = "RAPPORT_DE_TAUX_SUSPECT_PROBABLE_ERREUR_D_UNITE_PAS_UN_EDGE"


@dataclass(frozen=True, slots=True)
class TauxVenue:
    """Un taux de funding **avec sa période**. Un taux sans période n'a aucun sens."""
    venue: str
    taux_brut: float                    # tel que l'API le donne, sur SA période
    intervalle_h: float | None          # None = INCONNU -> non comparable

    @property
    def normalisable(self) -> bool:
        return self.intervalle_h is not None and self.intervalle_h > 0

    @property
    def bps_h(self) -> float:
        """Le taux ramené en bps **par heure**. C'est la SEULE unité comparable."""
        if not self.normalisable:
            raise ValueError("taux non normalisable : intervalle inconnu pour %r" % self.venue)
        return (self.taux_brut / float(self.intervalle_h)) * 1e4  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class EcartCrossVenue:
    coin: str
    venue_qui_paie: str          # on est LONG ici (funding le plus bas)
    venue_qui_encaisse: str      # on est SHORT ici (funding le plus haut : elle nous paie)
    taux_paie_bps_h: float
    taux_encaisse_bps_h: float
    ecart_bps_h: float
    heures_pour_amortir: float | None
    ecart_sur_capital_bps_h: float
    exploitable: bool
    motif: str
    venues_ecartees: tuple[str, ...] = ()
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin,
            "venue_qui_paie": self.venue_qui_paie,
            "venue_qui_encaisse": self.venue_qui_encaisse,
            "taux_paie_bps_h": round(self.taux_paie_bps_h, 5),
            "taux_encaisse_bps_h": round(self.taux_encaisse_bps_h, 5),
            "ecart_bps_h": round(self.ecart_bps_h, 5),
            "ecart_sur_capital_bps_h": round(self.ecart_sur_capital_bps_h, 5),
            "heures_pour_amortir": (round(self.heures_pour_amortir, 1)
                                    if self.heures_pour_amortir is not None else None),
            "exploitable": self.exploitable,
            "motif": self.motif,
            "venues_ecartees": list(self.venues_ecartees),
            "note": self.note,
            "unite": "bps par HEURE (normalise : HL=1h, Binance/Bybit=8h)",
            "avertissement": (
                "NOUS NE POUVONS PAS TRADER SUR BINANCE/BYBIT. Ce chiffre MESURE un ecart ; "
                "il ne le CAPTURE pas. Paper-only, read-only."
            ),
            "real_execution": False,
        }


def parser_predicted_fundings(
    payload: Any,
    *,
    intervalles: Mapping[str, float] | None = None,
) -> dict[str, list[TauxVenue]]:
    """Reponse de `predictedFundings` -> {coin: [TauxVenue avec sa PERIODE]}.

    DENY-BY-DEFAULT, deux fois :
      * un taux illisible -> venue ECARTEE (un 0 invente fabriquerait un ecart inexistant) ;
      * une venue dont l'INTERVALLE est inconnu -> `intervalle_h=None`, donc **non comparable**.
        *Une unite inconnue est pire qu'une donnee absente : elle produit un chiffre credible.*
    """
    table = dict(INTERVALLE_FUNDING_HEURES if intervalles is None else intervalles)
    out: dict[str, list[TauxVenue]] = {}
    if not isinstance(payload, list):
        return out
    for ligne in payload:
        if not isinstance(ligne, (list, tuple)) or len(ligne) < 2:
            continue
        coin = str(ligne[0] or "").strip()
        venues = ligne[1]
        if not coin or not isinstance(venues, (list, tuple)):
            continue
        taux: list[TauxVenue] = []
        for v in venues:
            if not isinstance(v, (list, tuple)) or len(v) < 2:
                continue
            nom = str(v[0] or "").strip()
            d = v[1]
            if not nom or not isinstance(d, Mapping):
                continue
            brut = d.get("fundingRate")
            if brut in (None, "", "null"):
                continue                       # on n'invente PAS un 0
            try:
                valeur = float(brut)
            except (TypeError, ValueError):
                continue
            taux.append(TauxVenue(venue=nom, taux_brut=valeur, intervalle_h=table.get(nom)))
        if taux:
            out[coin] = taux
    return out


def rapport_suspect(a: TauxVenue, b: TauxVenue) -> float | None:
    """Le rapport des deux taux BRUTS trahit-il une PERIODE qui n'est pas celle qu'on a declaree ?

    ***Ce garde attrape exactement le bug qui m'a eu*** : comparer du 8h avec du 1h.

    Il ne tire PAS quand le rapport brut est celui qu'on a **deja declare** (HL 1h vs Binance 8h
    -> rapport 8 attendu : la normalisation le regle, l'ecart tombe a zero tout seul).
    Il tire quand le rapport brut vaut une AUTRE periode usuelle -- signe que la vraie periode
    n'est pas celle de notre table (ex. une paire Binance passee en funding 4 h).

    Un vrai ecart economique ne tombe pas pile sur 8,000.
    """
    if not (a.normalisable and b.normalisable):
        return None
    if a.taux_brut == 0.0 or b.taux_brut == 0.0:
        return None
    brut = abs(a.taux_brut / b.taux_brut)
    if brut < 1.0:
        brut = 1.0 / brut

    declare = float(a.intervalle_h) / float(b.intervalle_h)  # type: ignore[arg-type]
    if declare < 1.0:
        declare = 1.0 / declare

    for cible in RAPPORTS_DE_PERIODE_SUSPECTS:
        if abs(brut - cible) > cible * TOLERANCE_RAPPORT:
            continue
        # Ce rapport EST celui qu'on a declare -> normal, la normalisation s'en charge.
        if abs(declare - cible) <= cible * TOLERANCE_RAPPORT:
            return None
        return cible
    return None


def evaluer_coin(
    coin: str,
    taux: Sequence[TauxVenue],
    *,
    cout_bps: float = COUT_4_EXECUTIONS_BPS,
    heures_max: float = HEURES_MAX,
) -> EcartCrossVenue:
    """L'ecart de funding entre venues, **en bps/HEURE**, sur le MEME coin."""
    ecartees = tuple(t.venue for t in taux if not t.normalisable)
    utiles = [t for t in taux if t.normalisable]

    def _refus(motif: str, note: str) -> EcartCrossVenue:
        return EcartCrossVenue(
            coin=coin, venue_qui_paie="-", venue_qui_encaisse="-",
            taux_paie_bps_h=0.0, taux_encaisse_bps_h=0.0, ecart_bps_h=0.0,
            heures_pour_amortir=None, ecart_sur_capital_bps_h=0.0,
            exploitable=False, motif=motif, venues_ecartees=ecartees, note=note,
        )

    if len(utiles) < 2:
        if ecartees:
            return _refus(
                MOTIF_INTERVALLE_INCONNU,
                "venue(s) sans intervalle de funding connu : %s. **Non devinees** -- une unite "
                "inconnue produit un chiffre credible et FAUX." % ", ".join(ecartees),
            )
        return _refus(MOTIF_UNE_SEULE_VENUE, "une seule venue cotee : rien a arbitrer.")

    haut = max(utiles, key=lambda t: t.bps_h)      # SHORT ici : elle nous paie
    bas = min(utiles, key=lambda t: t.bps_h)       # LONG ici  : on paie peu
    ecart = haut.bps_h - bas.bps_h

    # ── LE GARDE ANTI-ERREUR-D'UNITE (sur les taux BRUTS, avant normalisation) ─────────────────
    cible = rapport_suspect(haut, bas)
    if cible is not None and ecart > 0:
        return EcartCrossVenue(
            coin=coin, venue_qui_paie=bas.venue, venue_qui_encaisse=haut.venue,
            taux_paie_bps_h=bas.bps_h, taux_encaisse_bps_h=haut.bps_h,
            ecart_bps_h=ecart, heures_pour_amortir=None,
            ecart_sur_capital_bps_h=0.0, exploitable=False,
            motif=MOTIF_RAPPORT_SUSPECT, venues_ecartees=ecartees,
            note="les taux BRUTS de %s et %s sont dans un rapport de **%.0f** (a %.0f %% pres). "
                 "C'est la signature d'un decalage de PERIODE de funding, pas d'un ecart "
                 "economique : un vrai ecart ne tombe pas pile sur %.0f. La periode reelle "
                 "n'est probablement PAS celle de notre table. REFUSE."
                 % (haut.venue, bas.venue, cible, TOLERANCE_RAPPORT * 100, cible),
        )

    sur_capital = ecart / CAPITAL_SUR_DEUX_VENUES
    heures = (float(cout_bps) / ecart) if ecart > 0 else None

    if heures is None or heures > heures_max:
        return EcartCrossVenue(
            coin=coin, venue_qui_paie=bas.venue, venue_qui_encaisse=haut.venue,
            taux_paie_bps_h=bas.bps_h, taux_encaisse_bps_h=haut.bps_h,
            ecart_bps_h=ecart, heures_pour_amortir=heures,
            ecart_sur_capital_bps_h=sur_capital, exploitable=False,
            motif=MOTIF_ECART_TROP_FAIBLE, venues_ecartees=ecartees,
            note="ecart %.4f bps/h -> il faudrait tenir %s pour amortir %.0f bps (4 executions)."
                 % (ecart, ("%.0f h" % heures) if heures else "l'infini", cout_bps),
        )

    return EcartCrossVenue(
        coin=coin, venue_qui_paie=bas.venue, venue_qui_encaisse=haut.venue,
        taux_paie_bps_h=bas.bps_h, taux_encaisse_bps_h=haut.bps_h,
        ecart_bps_h=ecart, heures_pour_amortir=heures,
        ecart_sur_capital_bps_h=sur_capital, exploitable=True,
        motif=MOTIF_ECART_MESURE, venues_ecartees=ecartees,
        note="SHORT %s (%.4f bps/h) / LONG %s (%.4f bps/h) -> **%.4f bps/h** notionnel, "
             "**%.4f bps/h sur le CAPITAL** (deux venues). Amorti en %.0f h. "
             "⚠️ NON MODELISE : base inter-venue, stress -- et **on ne peut PAS trader sur "
             "Binance**." % (haut.venue, haut.bps_h, bas.venue, bas.bps_h, ecart,
                             sur_capital, heures),
    )


def resume(ecarts: Iterable[EcartCrossVenue]) -> dict[str, Any]:
    es = list(ecarts)
    ex = [e for e in es if e.exploitable]
    return {
        "n_coins": len(es),
        "n_exploitables": len(ex),
        "n_rapport_suspect": sum(1 for e in es if e.motif == MOTIF_RAPPORT_SUSPECT),
        "n_intervalle_inconnu": sum(1 for e in es if e.motif == MOTIF_INTERVALLE_INCONNU),
        "meilleur": ex[0].as_dict() if ex else None,
        "unite": "bps par HEURE (normalise : HL=1h, Binance/Bybit=8h)",
        "piege_documente": (
            "La 1re version comparait des taux 8h avec des taux 1h et annoncait 38 % APR sur "
            "l'exemple de la doc. Les 3 venues y sont en fait EXACTEMENT d'accord."
        ),
        "avertissement": (
            "⚠️ Trade CONNU des professionnels. Et **nous ne pouvons pas trader sur Binance** : "
            "ce module mesure, il ne capture rien."
        ),
        "real_execution": False,
    }


__all__ = [
    "CAPITAL_SUR_DEUX_VENUES", "COUT_4_EXECUTIONS_BPS", "HEURES_MAX",
    "INTERVALLE_FUNDING_HEURES", "RAPPORTS_DE_PERIODE_SUSPECTS", "TOLERANCE_RAPPORT",
    "MOTIF_ECART_MESURE", "MOTIF_ECART_TROP_FAIBLE", "MOTIF_INTERVALLE_INCONNU",
    "MOTIF_RAPPORT_SUSPECT", "MOTIF_UNE_SEULE_VENUE",
    "EcartCrossVenue", "TauxVenue",
    "evaluer_coin", "parser_predicted_fundings", "rapport_suspect", "resume",
]
