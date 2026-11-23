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
)


def score(m: Mecanisme) -> dict:
    if m.moyenne is not None and m.ic is not None:
        erreur = (m.ic[1] - m.ic[0]) / (2 * 1.96)
        p = float(norm.cdf(m.moyenne / erreur)) if erreur > 0 else (1.0 if m.moyenne > 0 else 0.0)
    elif m.p_impose is not None:
        p = m.p_impose
    else:
        raise ValueError(f"{m.code} : ni effet mesuré ni statut explicite")
    v = 4 * p * (1 - p)
    return {"code": m.code, "transfert": m.transfert, "preuve": m.preuve, "statut": m.statut,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
