"""#566 / H-161 — `only_per_side` : **19 de nos 21 ouvertures étaient des SHORT.**

═══════════════════════════════════════════════════════════════════════════════════════════════
LE FAIT, ET CE QU'IL SIGNIFIE
═══════════════════════════════════════════════════════════════════════════════════════════════

Sur nos 21 ouvertures observées : **19 SHORT, 2 LONG**. Ce n'est pas un détail cosmétique.

Deux lectures possibles, et **elles n'ont pas la même conséquence** :

  **(A) Le bot a un BIAIS DE CONSTRUCTION.** Un gate asymétrique, un signe inversé quelque part,
      un seuil qui n'est pas symétrique. -> **C'est un BUG, et il faut le trouver.**
      *(On a déjà eu un bug de SIGNE : la fraîcheur rendait le VIEUX signal meilleur que le frais.)*

  **(B) Le marché était baissier sur la période.** -> Alors ce n'est pas un biais, c'est une
      **exposition directionnelle non voulue** : on croit copier un signal, on fait en réalité un
      pari macro. **Et un pari macro n'a rien à faire dans un bot de copy-trading.**

🔴 **Dans les DEUX cas, c'est grave.** Et on ne peut pas trancher sans mesurer.

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QU'ON MESURE — un test binomial, pas une impression
═══════════════════════════════════════════════════════════════════════════════════════════════

Si le bot était neutre, chaque ouverture serait SHORT avec p = 0,5.
**Quelle est la probabilité d'observer 19 SHORT (ou pire) sur 21, par pur hasard ?**

    P(X >= 19 | n=21, p=0,5)

Si cette probabilité est **minuscule**, le déséquilibre **n'est pas du hasard** : il y a une cause.

Et un second test, qui distingue (A) de (B) :
    **le déséquilibre des SIGNAUX correspond-il au déséquilibre des OUVERTURES ?**
      * signaux équilibrés + ouvertures déséquilibrées -> **(A) le BOT biaise.** 🔴
      * signaux déséquilibrés -> **(B) le MARCHÉ**, ou le leader qu'on copie.

═══════════════════════════════════════════════════════════════════════════════════════════════
`only_per_side` — LE VERROU
═══════════════════════════════════════════════════════════════════════════════════════════════

Une fois la cause connue, on peut **verrouiller un seul côté** : n'autoriser que les LONG, ou que
les SHORT, ou imposer un **équilibre maximal**. ⚠️ **Mais verrouiller sans comprendre serait
maquiller le symptôme.** Le verrou est un OUTIL, pas une explication.

PUR : aucun appel réseau. Aucun ordre réel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

LONG = "LONG"
SHORT = "SHORT"

# Au-delà de ce déséquilibre, on refuse d'ouvrir de ce côté-là (garde-fou, pas explication).
DESEQUILIBRE_MAX = 0.70          # 70 % d'un côté au maximum

MOTIF_BIAIS_DU_BOT = "DESEQUILIBRE_DES_OUVERTURES_SANS_DESEQUILIBRE_DES_SIGNAUX_BIAIS_DU_BOT"
MOTIF_BIAIS_DU_MARCHE = "LE_DESEQUILIBRE_VIENT_DES_SIGNAUX_PARI_DIRECTIONNEL_NON_VOULU"
MOTIF_EQUILIBRE = "PAS_DE_DESEQUILIBRE_SIGNIFICATIF"
MOTIF_TROP_PEU = "TROP_PEU_D_OUVERTURES_POUR_CONCLURE"
MOTIF_VERROU = "COTE_VERROUILLE_PAR_only_per_side"

MIN_OUVERTURES = 10


def _binom_cdf_sup(k: int, n: int, p: float = 0.5) -> float:
    """P(X >= k) pour X ~ Binomiale(n, p). Exact, sans dépendance."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return sum(math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(k, n + 1))


@dataclass(frozen=True, slots=True)
class Diagnostic:
    n_ouvertures: int
    n_short: int
    n_long: int
    p_hasard: float                  # P(observer ce déséquilibre, ou pire, par pur hasard)
    part_short_signaux: float | None  # le déséquilibre des SIGNAUX (None = non fourni)
    motif: str
    note: str = ""

    @property
    def part_short(self) -> float:
        return self.n_short / self.n_ouvertures if self.n_ouvertures else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"n_ouvertures": self.n_ouvertures, "n_short": self.n_short,
                "n_long": self.n_long,
                "part_short": round(self.part_short, 4),
                "part_short_signaux": (round(self.part_short_signaux, 4)
                                       if self.part_short_signaux is not None else None),
                "p_hasard": round(self.p_hasard, 8),
                "motif": self.motif, "note": self.note, "real_execution": False}


def diagnostiquer(
    cotes_ouvertures: Sequence[str],
    *,
    cotes_signaux: Sequence[str] | None = None,
    min_ouvertures: int = MIN_OUVERTURES,
    seuil_p: float = 0.05,
) -> Diagnostic:
    """**Est-ce le BOT qui biaise, ou le MARCHÉ ?** On tranche par un test, pas par une impression."""
    o = [c.upper() for c in cotes_ouvertures if c]
    n = len(o)
    ns = sum(1 for c in o if c == SHORT)
    nl = n - ns

    if n < min_ouvertures:
        return Diagnostic(n, ns, nl, 1.0, None,
                          "%s : %d < %d" % (MOTIF_TROP_PEU, n, min_ouvertures),
                          "*Un déséquilibre sur 5 trades n'est pas un déséquilibre.*")

    # P(observer AU MOINS ce déséquilibre, du côté majoritaire, par pur hasard)
    majoritaire = max(ns, nl)
    p = 2.0 * _binom_cdf_sup(majoritaire, n, 0.5)          # bilatéral
    p = min(1.0, p)

    part_sig: float | None = None
    if cotes_signaux:
        s = [c.upper() for c in cotes_signaux if c]
        part_sig = (sum(1 for c in s if c == SHORT) / len(s)) if s else None

    if p >= seuil_p:
        return Diagnostic(n, ns, nl, p, part_sig, MOTIF_EQUILIBRE,
                          "p = %.3f : le déséquilibre est compatible avec le hasard." % p)

    # 🔴 Le déséquilibre est RÉEL. Vient-il du bot ou des signaux ?
    if part_sig is None:
        return Diagnostic(
            n, ns, nl, p, None, MOTIF_BIAIS_DU_BOT,
            "**%d/%d %s** — p = %.2e. Ce n'est PAS le hasard. ⚠️ Les signaux n'ont pas été "
            "fournis : **on ne peut pas encore dire si c'est le BOT ou le MARCHÉ.** "
            "*Ne pas verrouiller avant de savoir : ce serait maquiller le symptôme.*"
            % (majoritaire, n, SHORT if ns > nl else LONG, p),
        )

    ecart = abs(part_sig - (ns / n))
    if ecart > 0.20:
        return Diagnostic(
            n, ns, nl, p, part_sig, MOTIF_BIAIS_DU_BOT,
            "🔴 **LE BOT BIAISE.** Les signaux sont à %.0f %% SHORT, mais les ouvertures à "
            "%.0f %%. **Le filtre n'est pas symétrique** — il y a un bug, comme le bug de SIGNE "
            "de la fraîcheur. *Chercher le gate asymétrique.*"
            % (part_sig * 100, ns / n * 100),
        )
    return Diagnostic(
        n, ns, nl, p, part_sig, MOTIF_BIAIS_DU_MARCHE,
        "🔴 **PARI DIRECTIONNEL NON VOULU.** Les ouvertures suivent les signaux (%.0f %% vs "
        "%.0f %% SHORT) : le bot ne biaise pas, **mais on fait un pari MACRO sans l'avoir "
        "décidé.** Un pari macro n'a rien à faire dans un bot de copy-trading."
        % (ns / n * 100, part_sig * 100),
    )


def only_per_side(
    cote_demandee: str,
    *,
    ouvertures_en_cours: Sequence[str],
    cote_autorise: str | None = None,
    desequilibre_max: float = DESEQUILIBRE_MAX,
) -> tuple[bool, str]:
    """LE VERROU. ⚠️ **Un outil, pas une explication.**

    * `cote_autorise` : ne laisser passer QUE ce côté (`None` = les deux).
    * `desequilibre_max` : refuser d'aggraver un déséquilibre déjà trop fort.
    """
    c = str(cote_demandee).upper()
    if c not in (LONG, SHORT):
        return False, "cote inconnue : %r" % cote_demandee

    if cote_autorise and c != str(cote_autorise).upper():
        return False, "%s : seul %s est autorisé" % (MOTIF_VERROU, cote_autorise.upper())

    o = [x.upper() for x in ouvertures_en_cours if x]
    if o:
        futur = o + [c]
        part = sum(1 for x in futur if x == c) / len(futur)
        if part > desequilibre_max:
            return False, ("%s : ouvrir un %s de plus porterait ce côté à %.0f %% "
                           "(max %.0f %%)" % (MOTIF_VERROU, c, part * 100, desequilibre_max * 100))
    return True, "OK"


__all__ = [
    "DESEQUILIBRE_MAX", "LONG", "MIN_OUVERTURES", "MOTIF_BIAIS_DU_BOT",
    "MOTIF_BIAIS_DU_MARCHE", "MOTIF_EQUILIBRE", "MOTIF_TROP_PEU", "MOTIF_VERROU", "SHORT",
    "Diagnostic", "diagnostiquer", "only_per_side",
]
