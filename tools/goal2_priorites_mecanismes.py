r"""Priorisation DÉTERMINISTE des mécanismes économiques CopyVault, à partir des résultats MESURÉS du registre.

Pour chaque mécanisme (qui paie -> qui gagne) : dernier effet net mesuré et son IC95 (bps), ou un statut quand aucun
effet n'est mesurable. Trois critères, tous chiffrés :

* net plausible      p = Phi(moyenne / erreur_type), erreur_type = largeur de l'IC95 / (2 x 1,96) ;
* valeur d'info      V = 4 p (1 - p)  (maximale quand l'issue est la plus incertaine) ;
* faisabilité        F = 1 (données VIERGES en main), 0,6 (flux prospectif automatique ou publication à date connue),
                     0,3 (collecte ou infrastructure neuve), 0 (aucune source). 23/11 : AUCUN segment historique
                     vierge ne reste (validation consommée par H15b) : re-tester un mécanisme sur des données déjà
                     consultées ne vaut pas F = 1 -- la première version de cet outil le faisait, corrigé ;
* priorité           F x (p + V) / 2.

Un effet non mesuré n'est jamais favorable : p = 0,5 SEULEMENT si le statut est MORE_DATA (issue réellement
ouverte), et le mécanisme ne monte que par sa valeur d'information. Lecture seule.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm


@dataclass(frozen=True)
class Mecanisme:
    code: str
    transfert: str            # qui paie -> qui gagne
    preuve: str
    moyenne: float | None     # effet net (ou excès) mesuré, bps
    ic: tuple[float, float] | None
    faisabilite: float
    statut: str
    p_impose: float | None = None   # seulement quand AUCUN effet n'est mesurable (statut explicite)


#: Champs complets par mécanisme : capacité à 100 USD, fill utile, test de réfutation (déjà pré-enregistré).
#: Capacité MESURÉE le 23/11 (`tools/goal2_rejeu_capital.py`, même réplication, mêmes données, 127 leaders) :
#: une copie en lignes de 20 USD passe l'ordre minimal (10 USD), mais une RÉPLICATION de portefeuille à 100 USD voit
#: 96,5 % de ses ordres refusés par l'ordre minimal (68,5 % à 350 USD) : elle ne trade presque pas.
COPIE = "lignes de 20 USD >= ordre min. 10 USD : OK"
REPLICATION = "MESURÉ : 96,5 % des ordres refusés par l'ordre min. à 100 USD (68,5 % à 350)"
TAKER = "taker au meilleur prix + écart, après 120 s"
FICHE: dict[str, tuple[str, str, str]] = {
    "M1": (COPIE, TAKER, "excès top-tiers <= 0 sur segment vierge (H15b : -28,7)"),
    "M2": (COPIE, "taker à 120 s ; maker < 60 s exigerait un modèle de remplissage", "markout à 120 s <= coût (H20 : +0,07 vs 12)"),
    "M3": (COPIE, TAKER, "rebond 1 h - coût <= 0 (L2 : -5,8)"),
    "M4": (COPIE, TAKER, "excès sur jumeau <= 0 (H17 : -59,4)"),
    "M5": (COPIE, TAKER, "leader <= vague seule (H19 : -1,0 vs +72,9)"),
    "M6": (COPIE, "aucun (refus)", "gain du refus <= 0 sur novembre (H18)"),
    "M7": (COPIE, "aucun (refus)", "gain du refus <= 0 après le gel (H16)"),
    "M8": (COPIE, TAKER + " ; funding réglé horaire", "receveur - payeur <= 0 (H21 : -52,3)"),
    "M9": (COPIE, TAKER + " ; tenue 24 h", "net <= 0 (L11 : -53,1)"),
    "M10": (COPIE, "entrée taker, sortie miroir taker", "net <= 0 en prospectif (apprenant, 27/11)"),
    "M11": (COPIE, TAKER, "excès sur témoin <= 0 (H14 : -14,2)"),
    "M12": (COPIE, TAKER, "excès <= 0 (L9 : -12,6) ; kappa ~ 0 (pas de course commune)"),
    "M13": ("dépôt <= capital ; verrou 4 j de HLP", "aucun fill : dépôt en vault", "rendement 28 j <= 0 en prospectif (17/12)"),
    "M14": (COPIE, "—", "trop rare pour un test (0,19 % des fills)"),
    "M15": ("dépôt <= capital ; frais de performance du gérant", "aucun fill : dépôt en vault", "rendement < HLP après correction de survie (V : -436 bps/28 j)"),
    "M16": (COPIE, TAKER, "excès des gros fills <= 0 (L8 >= 40 % : -9,12 brut à 4 h)"),
    "M17": (REPLICATION, "taker au mid + demi-écart, réalignement périodique", "net <= 0 ou quasi-inactivité à 100 USD (rejeu 23/11)"),
}


MECANISMES = (
    Mecanisme("M1 wallets informés", "non-informés -> informés", "H15b validation, excès 24 h", -28.7, (-77.4, 16.4), 0.3, "REJECTED"),
    Mecanisme("M2 décroissance / latence", "copieur lent -> preneur rapide", "H20 Tardis, copie à 120 s", -9.43, (-28.59, 20.64), 0.3, "REJECTED"),
    Mecanisme("M3 pression temporaire", "impatients -> patients", "L2 rebond 1 h, brut 9,2 - coût 15", -5.8, (-14.49, 2.92), 0.6, "REJECTED"),
    Mecanisme("M4 absorber les ventes forcées", "liquidés -> absorbeurs", "H17, excès 24 h", -59.4, (-137.0, 5.8), 0.6, "REJECTED"),
    Mecanisme("M5 suivre la cascade", "retardataires -> suiveurs", "H19, net 24 h", -16.0, (-99.1, 59.6), 0.6, "REJECTED"),
    Mecanisme("M6 éviter la vague (NO-TRADE)", "copieur naïf -> copieur filtré", "H18 figée", None, None, 0.6, "MORE_DATA", 0.5),
    Mecanisme("M7 refus absorbé/tard/petit", "copieur naïf -> copieur filtré", "H16 figée", None, None, 0.6, "MORE_DATA", 0.5),
    Mecanisme("M8 prime de funding (receveur)", "côté surpeuplé -> receveur", "H21, net 24 h", -98.9, (-202.2, -0.1), 0.6, "REJECTED"),
    Mecanisme("M9 portage du leader", "payeur de funding -> porteur", "L11, net 24 h", -53.07, (-115.8, 4.04), 0.6, "REJECTED"),
    Mecanisme("M10 sortie / gestion", "sortie tardive -> sortie miroir", "L12c, brut 11,8 - coût 9,5", 2.3, (-9.6, 10.7), 0.6, "REJECTED"),
    Mecanisme("M11 réallocation", "gérant -> suiveur", "H14, net 24 h", -10.66, (-69.78, 49.91), 0.6, "REJECTED"),
    Mecanisme("M12 consensus indépendant", "foule -> consensus", "L9, excès 24 h", -12.62, (-76.71, 50.78), 0.6, "REJECTED"),
    Mecanisme("M13 fourniture de liquidité (HLP)", "preneurs -> teneurs de marché", "V5 validé, +230 bps/28 j", 230.0, None, 0.6, "PROMISING", 0.8),
    Mecanisme("M14 flux résiduel des métaordres", "métaordre visible -> anticipateur", "0,19 % des fills", None, None, 0.0, "UNMEASURABLE", 0.5),
    Mecanisme("M15 sélection de vaults gagnants", "déposant tardif -> gérant (frais, survie)", "V-allocation bornés, 28 j (journal l. 443)", -436.0, (-823.0, -61.0), 0.6, "REJECTED"),
    Mecanisme("M17 réplication lente du portefeuille", "suiveur -> porteur de risque observé",
              "rejeu 23/11 à 100 USD, 127 leaders", -1.05, (-17.4, 11.4), 0.6, "REJECTED"),
    # 23/11 : corrigé -- la 1re version prenait la tranche des PLUS PETITS ordres (0-1 % du volume, +4,65) ;
    # l'hypothèse « gros ordre informé » se lit sur la tranche >= 40 % : brut 4 h -9,12 [-36,46 ; 21,64] - coût 15.
    Mecanisme("M16 taille du fill du leader", "contrepartie d'un gros ordre -> son auteur", "L8 tranche >= 40 %, excès 4 h - coût 15", -24.12, (-51.46, 6.64), 0.6, "REJECTED"),
)


#: Chiffres MESURÉS par mécanisme (registre ESSAIS.ndjson et journal) : brut, seuil de rentabilité (bps), témoin.
MESURES: dict[str, tuple[str, str, str]] = {
    "M1": ("tiers sup. +23,7 (excès 24 h)", "écart > 0 et net > 15", "tous les leaders +20,2 ; 200 tirages : rang 57 %"),
    "M2": ("+5,16 à 60 s ; +0,07 à 120 s", "12 (taker aller-retour + écart)", "tous fills : copie -26,4 [-43,2 ; -3,3]"),
    "M3": ("+9,2 [0,5 ; 17,9] à 1 h", "15", "clôture en perte PASSIVE : -7,7 [-23,6 ; 7,9]"),
    "M4": ("-41,9 [-115,3 ; 20,7] à 24 h", "15", "jumeau : excès -59,4 ; hors vague : -23,3"),
    "M5": ("-1,0 [-84,1 ; 74,6] à 24 h", "15 et >= vague seule", "vague seule : +72,9 [0,6 ; 149,0]"),
    "M6": ("non encore mesuré (gel 22/11)", "gain du refus > 0", "copies non filtrées, mêmes jours"),
    "M7": ("non encore mesuré (gel 22/11)", "gain du refus > 0", "copies non filtrées, mêmes jours"),
    "M8": ("prix -88,4 + funding +4,5", "15", "côté payeur : net +19,1 [-67,9 ; 112,2]"),
    "M9": ("prix -41,2 + funding +3,1", "15", "jumeau : excès -20,7 [-89,8 ; 43,6]"),
    "M10": ("+11,8 [-0,1 ; 20,2]", "~9,5 (sortie miroir)", "jumeau : excès +14,5 [6,3 ; 20,4]"),
    "M11": ("+4,3 [-54,8 ; 64,9] à 24 h", "15", "jumeau : excès -14,2 [-64,0 ; 38,2]"),
    "M12": ("+13,3 [-46,3 ; 74,6] à 24 h", "15", "jumeau +26,0 : excès -12,6 [-76,7 ; 50,8]"),
    "M13": ("+230 bps / 28 j", "0 (dépôt, pas de frais de transaction)", "vaults d'utilisateurs : -436 [-823 ; -61]"),
    "M14": ("0,19 % des fills", "—", "—"),
    "M15": ("-436 [-823 ; -61] bps / 28 j", "> HLP", "HLP : +230"),
    "M16": ("-9,12 [-36,5 ; 21,6] à 4 h (>= 40 %)", "15", "tranche 0-1 % : +4,65 [-4,8 ; 14,3]"),
    "M17": ("-1,05 bps/j du capital [-17,4 ; 11,4]", "0 (vs NO-TRADE)", "même rejeu à 350 USD : -2,58 bps/j"),
}


def score(m: Mecanisme) -> dict:
    if m.moyenne is not None and m.ic is not None:
        erreur = (m.ic[1] - m.ic[0]) / (2 * 1.96)
        p = float(norm.cdf(m.moyenne / erreur)) if erreur > 0 else (1.0 if m.moyenne > 0 else 0.0)
    elif m.p_impose is not None:
        p = m.p_impose
    else:
        raise ValueError(f"{m.code} : ni effet mesuré ni statut explicite")
    v = 4 * p * (1 - p)
    capacite, fill, refutation = FICHE.get(m.code.split()[0], ("NON_RENSEIGNE",) * 3)
    brut, seuil, temoin = MESURES.get(m.code.split()[0], ("NON_RENSEIGNE",) * 3)
    return {"brut_mesure": brut, "seuil_bps": seuil, "temoin_mesure": temoin, "capacite_100_usd": capacite, "fill_utile": fill, "test_de_refutation": refutation, "code": m.code, "transfert": m.transfert, "preuve": m.preuve, "statut": m.statut,
            "p_net_positif": round(p, 3), "valeur_info": round(v, 3), "faisabilite": m.faisabilite,
            "priorite": round(m.faisabilite * (p + v) / 2, 3)}


def classement() -> list[dict]:
    return sorted((score(m) for m in MECANISMES), key=lambda s: (-s["priorite"], s["code"]))


def main() -> int:
    import sys
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    print(f"  {'rang':<4} {'mécanisme':<36} {'qui paie -> qui gagne':<34} {'p(net>0)':>8} {'V':>6} {'F':>4} {'priorité':>8}  statut")
    for rang, s in enumerate(classement(), 1):
        print(f"  {rang:<4} {s['code']:<36} {s['transfert']:<34} {s['p_net_positif']:>8.3f} {s['valeur_info']:>6.3f}"
              f" {s['faisabilite']:>4.1f} {s['priorite']:>8.3f}  {s['statut']}")
    print()
    for s in classement():
        print(f"  {s['code'].split()[0]:<4} brut : {s['brut_mesure']} | seuil : {s['seuil_bps']} | témoin : {s['temoin_mesure']}")
        print(f"       capacité : {s['capacite_100_usd']} | fill : {s['fill_utile']} | réfutation : {s['test_de_refutation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
