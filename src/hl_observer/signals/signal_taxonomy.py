"""Q3 -- LA TAXONOMIE DES SIGNAUX. D'ou vient l'information, et peut-elle encore payer ?

Trois preuves independantes disaient que le copy-trading ne paie pas. Aucune ne disait POURQUOI.
Q3 l'a mesure (38 388 signaux, panel strict, les MEMES aux 12 horizons) :

    T-300s   -7.75 bps   <- le prix court CONTRE le trade
    T-120s   -3.54 bps
    T- 60s   -1.12 bps
    T-  5s   +0.00 bps
    ---------------------  le fill devient public
    T+ 60s   +0.08 bps
    T+300s   +0.62 bps   <- reel (borne basse +0.45), mais 20x sous les 12 bps de cout

**Le fill du leader ne porte aucune information.** Le prix ne bouge pas apres. Et AVANT, il
bouge CONTRE lui : ces wallets achetent la baisse et vendent la hausse.

Ce n'est donc PAS un probleme de vitesse. Ce n'est pas « on arrive trop tard ». C'est
« il n'y a rien a attraper ». Suivre plus vite un signal vide, c'est copier plus vite du vide.

LA DISTINCTION QUI COMPTE
-------------------------
Un signal ne vaut que par son ORIGINE. Il y a quatre familles, et une seule est morte :

  DISCRETIONNAIRE_PUBLIC  -- le fill deja execute d'un humain. MESURE : mort. Zone morte.
  PRE_EXECUTION           -- l'ordre AVANT qu'il touche le carnet (mempool, depots entrants).
                             Structurellement different : l'info n'est pas encore dans le prix.
  FLUX_FORCE              -- un flux qui n'a PAS le choix : liquidation, ADL, prelevement de
                             funding, oracle qui suit les CEX. Le contrepartie ne cherche pas
                             a nous battre -- elle SUBIT. Pas besoin de deviner quoi que ce soit.
  CARRY_STRUCTUREL        -- pas une prediction du tout : un PAIEMENT pour detenir une position
                             (funding, basis). Le seul deja valide chez nous (T2, HYPE, +33 bps).

La difference n'est pas de degre, elle est de NATURE :
  * suivre un discretionnaire = parier qu'il sait quelque chose. Mesure : il ne sait rien.
  * suivre un flux force      = savoir ce qui VA se passer parce que la MECANIQUE l'impose.

Ce module ne trade pas. Il NOMME, et il REFUSE ce qui est prouve mort -- pour qu'on ne
reconstruise pas, dans six mois, une enieme variante du meme signal vide.

Aucun ordre reel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ------------------------------------------------------------------ familles

DISCRETIONNAIRE_PUBLIC = "DISCRETIONNAIRE_PUBLIC"
PRE_EXECUTION = "PRE_EXECUTION"
FLUX_FORCE = "FLUX_FORCE"
CARRY_STRUCTUREL = "CARRY_STRUCTUREL"

FAMILLES = (DISCRETIONNAIRE_PUBLIC, PRE_EXECUTION, FLUX_FORCE, CARRY_STRUCTUREL)

# ------------------------------------------------------------------ verdicts

MORT_PROUVE = "MORT_PROUVE"          # mesure, OOS, plusieurs fois. Ne pas y revenir.
NON_MESURE = "NON_MESURE"            # plausible, jamais teste. Le seul terrain a explorer.
VALIDE_PARTIEL = "VALIDE_PARTIEL"    # survit a une falsification, sur un perimetre etroit.

REFUS_ZONE_MORTE = "SIGNAL_DANS_UNE_ZONE_MORTE_PROUVEE"
REFUS_FAMILLE_INCONNUE = "SIGNAL_FAMILLE_INCONNUE"


@dataclass(frozen=True, slots=True)
class Famille:
    nom: str
    verdict: str
    mecanisme: str
    preuve: str
    exemples: tuple[str, ...] = field(default_factory=tuple)


# ------------------------------------------------------------------ le registre

REGISTRE: dict[str, Famille] = {
    DISCRETIONNAIRE_PUBLIC: Famille(
        nom=DISCRETIONNAIRE_PUBLIC,
        verdict=MORT_PROUVE,
        mecanisme=(
            "On observe le fill DEJA EXECUTE d'un humain, via un canal public. Par construction, "
            "le prix a deja absorbe l'ordre quand on le voit."
        ),
        preuve=(
            "TROIS mesures independantes : (1) OOS 2026-07-11, 24 133 signaux, -7,97 bps meme a "
            "cout ZERO ; (2) courbe edge/horizon PLATE de 500 ms a 5 min -- la latence n'a jamais "
            "ete le probleme ; (3) table d'edge mesuree Q1 (2026-07-13), 23 358 markouts : 0 "
            "cellule survit hors echantillon avec un edge net positif. "
            "Et la CAUSE, mesuree par Q3 (38 388 signaux, panel strict) : le prix bouge CONTRE le "
            "trade de -7,75 bps dans les 300 s AVANT le fill, puis PLUS RIEN apres (+0,08 bps a "
            "60 s ; +0,62 bps a 300 s, soit 20x sous les 12 bps de cout). Ces wallets achetent la "
            "baisse et vendent la hausse : ils ne sont pas informes, ils prennent le contre-pied."
        ),
        exemples=("copy-trading", "smart-money follow", "leaderboard mirror", "whale alert"),
    ),
    PRE_EXECUTION: Famille(
        nom=PRE_EXECUTION,
        verdict=NON_MESURE,
        mecanisme=(
            "On voit l'intention AVANT qu'elle touche le carnet : mempool, depot entrant vers "
            "l'exchange, transaction en attente. L'information n'est pas encore dans le prix -- "
            "c'est la SEULE facon de ne pas arriver apres la bataille."
        ),
        preuve="AUCUNE. Jamais teste chez nous. Faisabilite technique non etablie (X-01, X-09, X-10).",
        exemples=("depots Arbitrum -> Hyperliquid", "mempool", "noeud local L1"),
    ),
    FLUX_FORCE: Famille(
        nom=FLUX_FORCE,
        verdict=NON_MESURE,
        mecanisme=(
            "Un flux qui n'a PAS le choix : liquidation, auto-deleveraging, prelevement horaire "
            "de funding, oracle qui suit mecaniquement les CEX. La contrepartie ne cherche pas a "
            "nous battre -- elle SUBIT. On n'a rien a deviner : la mecanique est publique et "
            "l'etat qui la declenche aussi."
        ),
        preuve="AUCUNE. Le flux existe et est documente ; son edge net apres couts n'est pas mesure.",
        exemples=("cascades de liquidation", "ADL", "saisonnalite du funding", "lead-lag oracle/CEX"),
    ),
    CARRY_STRUCTUREL: Famille(
        nom=CARRY_STRUCTUREL,
        verdict=VALIDE_PARTIEL,
        mecanisme=(
            "Ce n'est pas une prediction. C'est un PAIEMENT pour detenir une position (funding, "
            "basis). On n'a besoin de savoir ou va le prix : on se couvre, et on encaisse le flux."
        ),
        preuve=(
            "T2 (2026-07-12) : LONG spot + SHORT perp sur HYPE = +33,6 bps nets dans son PIRE "
            "mois sur 90 j de funding REEL. 7 des 8 candidats meurent (collisions de ticker, "
            "spread > carry, marche mort). ⚠️ Risque NON modelise : le spot ne sert pas de marge "
            "au perp -- la jambe short peut etre liquidee (T2b)."
        ),
        exemples=("carry delta-neutre spot/perp", "funding arb perp<->perp", "basis"),
    ),
}


def famille_de(signal: str | None) -> str:
    """Classe un signal. Deny-by-default : un nom inconnu n'est PAS suppose vivant."""
    s = (signal or "").strip().upper()
    return s if s in REGISTRE else ""


def est_une_zone_morte(famille: str | None) -> bool:
    f = REGISTRE.get((famille or "").strip().upper())
    return bool(f and f.verdict == MORT_PROUVE)


def verdict_du_signal(famille: str | None) -> tuple[bool, str]:
    """(autorise_a_chercher, raison). NE decide PAS d'un trade -- decide d'une RECHERCHE.

    Un signal dans une zone morte prouvee ne doit pas etre re-explore : ce n'est pas de la
    prudence, c'est du temps rendu. Les preuves sont dans `REGISTRE[...].preuve`.
    """
    cle = (famille or "").strip().upper()
    f = REGISTRE.get(cle)
    if f is None:
        return False, REFUS_FAMILLE_INCONNUE
    if f.verdict == MORT_PROUVE:
        return False, REFUS_ZONE_MORTE
    return True, f.verdict


def zones_mortes() -> tuple[str, ...]:
    return tuple(sorted(n for n, f in REGISTRE.items() if f.verdict == MORT_PROUVE))


def pistes_ouvertes() -> tuple[str, ...]:
    return tuple(sorted(n for n, f in REGISTRE.items() if f.verdict != MORT_PROUVE))


__all__ = [
    "DISCRETIONNAIRE_PUBLIC", "PRE_EXECUTION", "FLUX_FORCE", "CARRY_STRUCTUREL", "FAMILLES",
    "MORT_PROUVE", "NON_MESURE", "VALIDE_PARTIEL",
    "REFUS_ZONE_MORTE", "REFUS_FAMILLE_INCONNUE",
    "Famille", "REGISTRE",
    "famille_de", "est_une_zone_morte", "verdict_du_signal", "zones_mortes", "pistes_ouvertes",
]
