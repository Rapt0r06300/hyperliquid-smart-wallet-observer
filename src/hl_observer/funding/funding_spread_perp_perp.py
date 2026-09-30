"""#365 / X-04 / H-137 — LE FUNDING ARB **PERP ↔ PERP** : la voie de réouverture DÉSIGNÉE.

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI CETTE PISTE EST LEGITIME (et pas un contournement de zone morte)
═══════════════════════════════════════════════════════════════════════════════════════════════

La zone morte `FUNDING_JAMBE_NUE` (mesuree : ratio funding/bruit = **0,0036** sur 9 512 relevés)
dit que toucher le funding sur une **jambe nue** est un pari directionnel avec un coupon.

Mais elle DESIGNE ELLE-MEME sa sortie :

    condition_de_reouverture = "une VRAIE jambe de couverture (spot ou **perp oppose**) qui
                                annule le risque de prix"

C'est exactement ce module. **Ce n'est pas un contournement : c'est la porte que la mesure a
laissee ouverte.** (Et T2 a deja prouve que le carry couvert EXISTE -- sur HYPE, via le spot.
Ici on essaie sans spot du tout : perp contre perp.)

═══════════════════════════════════════════════════════════════════════════════════════════════
L'IDEE, ET LES TROIS FACONS DONT ELLE PEUT MOURIR
═══════════════════════════════════════════════════════════════════════════════════════════════

Deux perps dont les sous-jacents bougent ensemble. L'un paie +5 bps/h de funding, l'autre -2.
On short le premier, on long le second, **dimensionnes par beta** -> delta ~ 0. On encaisse
l'ECART de funding (7 bps/h) sans (en principe) porter de risque de prix.

Les trois morts possibles -- et on les teste **dans cet ordre**, du plus dur au plus doux :

  🔴 1. **LE RESIDU.** Beta n'est pas parfait. Ce qui reste apres couverture (`r_A - beta*r_B`)
        BOUGE. Si ce residu bouge plus que le funding qu'on encaisse, **c'est le meme piege que
        la jambe nue, en plus cher** (deux jambes, quatre executions).
        *C'est LA question. Tout le reste est du detail.*

  🔴 2. **LES COUTS.** 4 executions. A ~3 bps l'aller-retour par jambe -> ~12 bps. Combien
        d'heures faut-il tenir pour les amortir ? Et l'ecart de funding existe-t-il encore
        a ce moment-la ?

  🔴 3. **LA PERSISTANCE.** Un ecart de funding qui s'inverse en 20 min ne paie rien.

DENY-BY-DEFAULT : donnee insuffisante -> `INSUFFICIENT_DATA`. Jamais un chiffre invente.

⚠️ CE QU'ON NE MESURE **PAS** ICI, ET QU'IL FAUT DIRE :
  * le risque de **liquidation** de l'une des deux jambes (T2b : il a divise le rendement du
    carry HYPE par DEUX) ;
  * l'**ADL** (Hyperliquid peut fermer une position sans nous demander) ;
  * la **rupture de correlation** (le beta d'hier n'est pas celui de demain).
Ces trois-la ne peuvent que DEGRADER le resultat. On l'assume, et on l'ecrit.

Aucun ordre reel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

# Couts REELS Hyperliquid : le maker PAIE 1,5 bps. Deux jambes, aller-retour = 4 executions.
COUT_4_EXECUTIONS_BPS = 12.0

MIN_POINTS = 100                 # sous 100 points appariés, un beta est du bruit
MIN_R2 = 0.30                    # sous 30 % de variance expliquee, ce n'est pas une couverture
HEURES_DETENTION_MAX = 24.0      # au-dela, la correlation d'hier ne dit plus rien

MOTIF_INSUFFISANT = "INSUFFICIENT_DATA"
MOTIF_PAS_UNE_COUVERTURE = "CORRELATION_TROP_FAIBLE_CE_N_EST_PAS_UNE_COUVERTURE"
MOTIF_RESIDU_DOMINE = "LE_RESIDU_BOUGE_PLUS_QUE_LE_FUNDING_ENCAISSE_PARI_DEGUISE"
MOTIF_COUTS_JAMAIS_AMORTIS = "COUTS_NON_AMORTIS_DANS_LA_FENETRE_DE_DETENTION"
MOTIF_VIABLE = "ECART_DE_FUNDING_DOMINE_LE_RESIDU_ET_AMORTIT_LES_COUTS"


def _rendements(prix: Sequence[float]) -> list[float]:
    return [
        (prix[i] - prix[i - 1]) / prix[i - 1]
        for i in range(1, len(prix))
        if prix[i - 1] > 0
    ]


def beta_et_r2(ra: Sequence[float], rb: Sequence[float]) -> tuple[float, float]:
    """OLS de `ra` sur `rb`. Rend (beta, R²).

    Le R² est **le juge de la couverture** : un beta calcule sur deux series independantes
    existe toujours -- il ne veut simplement rien dire. *Un beta sans R² est un nombre qui ment.*
    """
    n = min(len(ra), len(rb))
    if n < 2:
        return 0.0, 0.0
    ra, rb = list(ra[:n]), list(rb[:n])
    ma, mb = sum(ra) / n, sum(rb) / n
    sbb = sum((x - mb) ** 2 for x in rb)
    if sbb <= 0:
        return 0.0, 0.0
    sab = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    beta = sab / sbb
    saa = sum((x - ma) ** 2 for x in ra)
    if saa <= 0:
        return beta, 0.0
    r2 = (sab * sab) / (saa * sbb)
    return beta, max(0.0, min(1.0, r2))


def residu_bps(ra: Sequence[float], rb: Sequence[float], beta: float) -> float:
    """L'ecart-type de ce qui RESTE apres couverture, en bps par pas de temps.

    🔴 C'EST LA VARIABLE QUI DECIDE. Si ce residu bouge plus que le funding qu'on encaisse, la
    « couverture » n'en est pas une, et on refait exactement l'erreur de la jambe nue -- en payant
    deux fois plus de frais.
    """
    n = min(len(ra), len(rb))
    if n < 2:
        return 0.0
    res = [ra[i] - beta * rb[i] for i in range(n)]
    m = sum(res) / n
    var = sum((x - m) ** 2 for x in res) / (n - 1)
    return 1e4 * math.sqrt(max(0.0, var))


@dataclass(frozen=True, slots=True)
class VerdictPaire:
    a: str
    b: str
    n_points: int
    beta: float
    r2: float
    funding_a_bps_h: float
    funding_b_bps_h: float
    ecart_funding_bps_h: float        # ce qu'on encaisse par heure, delta-ajuste
    residu_bps_h: float               # ce que le residu bouge par heure
    ratio: float                      # encaisse / subi. LA metrique.
    heures_pour_amortir: float | None
    viable: bool
    motif: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "a": self.a, "b": self.b, "n_points": self.n_points,
            "beta": round(self.beta, 4), "r2": round(self.r2, 4),
            "funding_a_bps_h": round(self.funding_a_bps_h, 4),
            "funding_b_bps_h": round(self.funding_b_bps_h, 4),
            "ecart_funding_bps_h": round(self.ecart_funding_bps_h, 4),
            "residu_bps_h": round(self.residu_bps_h, 4),
            "ratio_encaisse_sur_subi": round(self.ratio, 6),
            "heures_pour_amortir": (round(self.heures_pour_amortir, 2)
                                    if self.heures_pour_amortir is not None else None),
            "viable": self.viable, "motif": self.motif, "note": self.note,
            "real_execution": False,
        }


def evaluer_paire(
    nom_a: str,
    nom_b: str,
    serie_a: Sequence[float],
    serie_b: Sequence[float],
    funding_a_bps_h: float,
    funding_b_bps_h: float,
    *,
    pas_par_heure: float = 60.0,          # les relevés sont ~ a la minute
    cout_bps: float = COUT_4_EXECUTIONS_BPS,
    heures_max: float = HEURES_DETENTION_MAX,
) -> VerdictPaire:
    """Le verdict d'UNE paire perp↔perp. Les trois portes, du plus dur au plus doux."""
    ra, rb = _rendements(serie_a), _rendements(serie_b)
    n = min(len(ra), len(rb))

    def _refus(motif: str, note: str, **kw) -> VerdictPaire:
        base = dict(a=nom_a, b=nom_b, n_points=n, beta=0.0, r2=0.0,
                    funding_a_bps_h=funding_a_bps_h, funding_b_bps_h=funding_b_bps_h,
                    ecart_funding_bps_h=0.0, residu_bps_h=0.0, ratio=0.0,
                    heures_pour_amortir=None, viable=False, motif=motif, note=note)
        base.update(kw)
        return VerdictPaire(**base)

    if n < MIN_POINTS:
        return _refus(MOTIF_INSUFFISANT, "%d points < %d" % (n, MIN_POINTS))

    beta, r2 = beta_et_r2(ra, rb)

    # --- PORTE 1 : est-ce seulement une COUVERTURE ?
    if r2 < MIN_R2:
        return _refus(
            MOTIF_PAS_UNE_COUVERTURE,
            "R² = %.3f < %.2f : les deux perps ne bougent pas ensemble. Shorter l'un et longer "
            "l'autre n'est pas une couverture -- c'est **deux paris**, et on paie 4 executions "
            "pour ca." % (r2, MIN_R2),
            beta=beta, r2=r2,
        )

    # ce qu'on encaisse : le funding de A moins beta fois celui de B (on short A, long beta*B)
    ecart = float(funding_a_bps_h) - beta * float(funding_b_bps_h)
    # ce qu'on subit : le residu, ramene a l'heure (sqrt du temps)
    res_pas = residu_bps(ra, rb, beta)
    res_h = res_pas * math.sqrt(max(1.0, pas_par_heure))
    ratio = (abs(ecart) / res_h) if res_h > 0 else float("inf")

    # --- PORTE 2 : 🔴 LE RESIDU DOMINE-T-IL LE FUNDING ? (la question qui a tue la jambe nue)
    if abs(ecart) <= res_h:
        return _refus(
            MOTIF_RESIDU_DOMINE,
            "on encaisse %.3f bps/h et le residu bouge de **%.1f bps/h** (ratio %.4f). "
            "*C'est le meme piege que la jambe nue -- en payant deux fois plus de frais.*"
            % (abs(ecart), res_h, ratio),
            beta=beta, r2=r2, ecart_funding_bps_h=ecart, residu_bps_h=res_h, ratio=ratio,
        )

    # --- PORTE 3 : les COUTS s'amortissent-ils dans la fenetre ?
    heures = (float(cout_bps) / abs(ecart)) if abs(ecart) > 0 else None
    if heures is None or heures > heures_max:
        return _refus(
            MOTIF_COUTS_JAMAIS_AMORTIS,
            "il faudrait tenir **%.1f h** pour amortir %.0f bps de couts, au-dela de la fenetre "
            "de %.0f h ou la correlation reste credible."
            % (heures or float("inf"), cout_bps, heures_max),
            beta=beta, r2=r2, ecart_funding_bps_h=ecart, residu_bps_h=res_h, ratio=ratio,
            heures_pour_amortir=heures,
        )

    return VerdictPaire(
        a=nom_a, b=nom_b, n_points=n, beta=beta, r2=r2,
        funding_a_bps_h=funding_a_bps_h, funding_b_bps_h=funding_b_bps_h,
        ecart_funding_bps_h=ecart, residu_bps_h=res_h, ratio=ratio,
        heures_pour_amortir=heures, viable=True, motif=MOTIF_VIABLE,
        note="R²=%.2f, beta=%.2f ; on encaisse %.3f bps/h contre %.1f bps/h de residu "
             "(ratio %.3f) ; couts amortis en %.1f h. ⚠️ NON MODELISE : liquidation d'une jambe, "
             "ADL, rupture de correlation -- **tous DEGRADENT** ce chiffre."
             % (r2, beta, abs(ecart), res_h, ratio, heures),
    )


def funding_median(relevés: Sequence[Mapping[str, Any]]) -> float:
    """Le funding MEDIAN (pas la moyenne : un pic ne doit pas decider)."""
    vals = sorted(float(r.get("funding_bps_hourly") or 0.0) for r in relevés)
    return vals[len(vals) // 2] if vals else 0.0


__all__ = [
    "COUT_4_EXECUTIONS_BPS", "HEURES_DETENTION_MAX", "MIN_POINTS", "MIN_R2",
    "MOTIF_COUTS_JAMAIS_AMORTIS", "MOTIF_INSUFFISANT", "MOTIF_PAS_UNE_COUVERTURE",
    "MOTIF_RESIDU_DOMINE", "MOTIF_VIABLE",
    "VerdictPaire", "beta_et_r2", "evaluer_paire", "funding_median", "residu_bps",
]
