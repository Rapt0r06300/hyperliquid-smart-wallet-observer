r"""#1 — LE CANARI : *le moissonneur doit PROUVER qu'il retrouve ce qu'on sait déjà bon.*

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI C'EST LA PREMIÈRE IDÉE, ET POURQUOI LES 14 AUTRES EN DÉPENDENT
═══════════════════════════════════════════════════════════════════════════════════════════════

Un trieur qu'on n'a **jamais testé contre une vérité connue** est un trieur auquel on fait
confiance **sans raison**. Et ce projet a déjà payé ça très cher :

  * le **balayage de lookahead (#563)** : un grep `pandas` sur du code Python pur → **0 trouvaille**,
    et j'ai failli conclure « aucun lookahead ». *La version qui a marché (#562) était celle qui
    **REFUSAIT de rendre un verdict** si elle ne retrouvait pas le bug **connu** (`garch11_variance`).*
    **Ce garde-fou a payé dès sa deuxième exécution.**
  * l'ancien tri du moissonneur : il classait **les bavards en tête**, et personne ne s'en est
    plaint pendant deux jours.

    ***Un outil de mesure qu'on ne calibre pas mesure ce qu'il veut.***

═══════════════════════════════════════════════════════════════════════════════════════════════
LE MÉCANISME
═══════════════════════════════════════════════════════════════════════════════════════════════

On donne au trieur un **jeu témoin** :

    ✅ des repos qu'on **SAIT** excellents — parce qu'on les a **LUS**, et qu'ils nous ont
       **donné des bugs réels** (hftbacktest → 5 bugs dans notre simu).
    🔴 des repos qu'on **SAIT** creux — bourrage de mots-clés, promesses sans preuve.

**S'il ne sépare pas les deux, il REFUSE de rendre un verdict sur le corpus.**

    ***Il ne dit pas « je n'ai rien trouvé ». Il dit « JE NE SAIS PAS TROUVER ».***
    C'est toute la différence — et c'est exactement la confusion qui a perdu 235 README.

PUR : aucun réseau. Aucun ordre réel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LE JEU TÉMOIN — **des textes RÉELS, pas inventés.**
#
# Chaque « bon » est un repo qu'on a **vraiment lu** et qui nous a **vraiment servi**.
# Chaque « creux » reproduit une signature qu'on a **vraiment rencontrée** dans le corpus.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

BONS: tuple[tuple[str, str, str], ...] = (
    (
        "nkaz001/hftbacktest",
        # ce repo nous a donné **5 bugs réels**. C'est notre étalon.
        "High-frequency trading backtesting with full order book reconstruction. "
        "Queue position modeling: ProbQueueModel estimates qty_ahead from L2 deltas. "
        "We correct double counting: chg -= cum_trade_qty, otherwise fills happen too early. "
        "Order rejection is modeled: the exchange rejects when overloaded. "
        "Latency is a triplet (req_ts, exch_ts, resp_ts), not a single number. "
        "Limitations: an overly pessimistic approach hides small edges. "
        "Round-trip cost 3 bps in our example; results are not investment advice.",
        "il nous a donné **5 bugs réels** dans notre simu — c'est notre ÉTALON",
    ),
    (
        "Giri-Aayush/hyperliquid-data-pipeline",
        "Reconstructs FIFO queue position per order directly from the Hyperliquid node feed. "
        "PnL decomposed into spread capture and adverse selection markout. "
        "Caveat: node data is only available for the last N blocks; the S3 archive is "
        "requester-pays. Measured maker fill ratio: 12% of posted volume.",
        "**3 étoiles** — et il fait exactement ce qui nous manque (position FIFO réelle)",
    ),
    (
        "tfrmma/cross-venue-arbitrage",
        "Cross-venue funding arbitrage. We compute a toxicity proxy from trade imbalance. "
        "Note: this is not a substitute for real VPIN, which requires volume-clock bucketing. "
        "Net of 9 bps round trip our edge was -2 bps over 4000 samples. It didn't work at size.",
        "🔑 **« not a substitute for real VPIN »** — *dans un corpus qui promet tous de l'alpha, "
        "l'aveu d'une limite est la seule signature de l'honnêteté*",
    ),
    (
        "horn111/hip4-mm-simulator",
        "Market making simulator with cumulative-volume queue model and 50ms latency. "
        "lambda(delta) = A * exp(-kappa * delta), kappa fitted per market. "
        "Known limitation: assumes no partial fills. Realized spread was 1.8 bps, "
        "below the 4.5 bps taker cost.",
        "**2 étoiles** — pose la formule ET avoue sa limite ET donne le chiffre",
    ),
)

CREUX: tuple[tuple[str, str, str], ...] = (
    (
        "fake/quant-finance-library",
        # le VRAI champion de l'ancien tri : 12 concepts sur 13, **5 étoiles**, zéro substance.
        "A comprehensive library covering market making, Avellaneda-Stoikov, queue position, "
        "adverse selection, market impact, funding rates, liquidation, mempool, latency, "
        "walk-forward validation, lookahead bias, order book reconstruction, kappa estimation. "
        "The ultimate toolkit for profitable algorithmic trading.",
        "🔴 **LE CHAMPION DE L'ANCIEN TRI** — il récite le catalogue du métier et ne prouve RIEN",
    ),
    (
        "fake/moon-bot-9000",
        "🚀 Turn $500 into $50,000! Guaranteed profit, risk-free money. "  # audit:fixture — APPÂT d'arnaque que le canari doit REJETER : échantillon négatif, pas une promesse
        "300% monthly returns. Never lose a trade. DM me for the secret strategy. "
        "Join our Discord signals group! Passive income money printer.",
        "🔴 la signature d'arnaque relevée sur du VRAI (2 repos HL en bourrage de mots-clés)",
    ),
    (
        "fake/awesome-trading-bot",
        "An awesome trading bot. Very fast. Written in Rust. Star this repo!",
        "🔴 **20 000 étoiles ne sauveraient pas ça** — aucune formule, aucun aveu, aucun chiffre",
    ),
)

# Marge exigée : le pire des BONS doit dépasser le meilleur des CREUX **d'au moins ça**.
# *Un classement correct « de justesse » n'est pas un classement fiable.*
MARGE_MIN = 10.0


@dataclass(slots=True)
class Resultat:
    """Le verdict du canari. **`fiable=False` bloque le corpus entier.**"""
    fiable: bool
    pire_bon: tuple[str, float]
    meilleur_creux: tuple[str, float]
    marge: float
    inversions: list[str] = field(default_factory=list)
    detail: list[tuple[str, float, bool]] = field(default_factory=list)
    raison: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "fiable": self.fiable,
            "pire_bon": {"repo": self.pire_bon[0], "score": round(self.pire_bon[1], 1)},
            "meilleur_creux": {"repo": self.meilleur_creux[0],
                               "score": round(self.meilleur_creux[1], 1)},
            "marge": round(self.marge, 1),
            "marge_exigee": MARGE_MIN,
            "inversions": self.inversions,
            "detail": [{"repo": r, "score": round(s, 1), "attendu_bon": b}
                       for r, s, b in self.detail],
            "raison": self.raison,
        }

    def rapport(self) -> str:
        if self.fiable:
            return (
                "✅ **CANARI VIVANT.** Le pire des bons (`%s`, %.1f) dépasse le meilleur des creux "
                "(`%s`, %.1f) de **%.1f points** (marge exigée : %.1f).\n"
                "   *Le trieur retrouve ce qu'on sait déjà bon. On peut lui faire confiance sur "
                "le reste.*"
                % (self.pire_bon[0], self.pire_bon[1], self.meilleur_creux[0],
                   self.meilleur_creux[1], self.marge, MARGE_MIN)
            )
        return (
            "🔴🔴🔴 **CANARI MORT — LE TRIEUR NE SAIT PAS TROUVER.**\n"
            "   %s\n"
            "   ***Je ne dis PAS « je n'ai rien trouvé ». Je dis « JE NE SAIS PAS TROUVER ».***\n"
            "   *C'est exactement la confusion qui a perdu 235 README — dont hftbacktest, notre "
            "cible n°1.*\n"
            "   🔒 **Aucun verdict ne sera rendu sur le corpus tant que ceci n'est pas réparé.**"
            % self.raison
        )


def verifier(noteur: Callable[[str], float],
             *, bons: Sequence[tuple[str, str, str]] = BONS,
             creux: Sequence[tuple[str, str, str]] = CREUX,
             marge_min: float = MARGE_MIN) -> Resultat:
    """`noteur(texte) -> score`. **Le trieur passe-t-il l'épreuve du connu ?**

    🔒 **Si non : `fiable=False`, et l'appelant DOIT s'abstenir de juger le corpus.**
    *Un outil qui échoue sur ce qu'il connaît n'a rien à dire sur ce qu'il ne connaît pas.*
    """
    detail: list[tuple[str, float, bool]] = []
    sb: list[tuple[str, float]] = []
    sc: list[tuple[str, float]] = []

    for nom, txt, _ in bons:
        s = float(noteur(txt))
        sb.append((nom, s))
        detail.append((nom, s, True))
    for nom, txt, _ in creux:
        s = float(noteur(txt))
        sc.append((nom, s))
        detail.append((nom, s, False))

    if not sb or not sc:
        return Resultat(False, ("", 0.0), ("", 0.0), 0.0, [], detail,
                        "jeu témoin vide — **on ne peut rien calibrer**")

    pire_bon = min(sb, key=lambda x: x[1])
    meilleur_creux = max(sc, key=lambda x: x[1])
    marge = pire_bon[1] - meilleur_creux[1]

    # les inversions, **nommément** : *un échec global ne dit pas QUOI réparer.*
    inversions = [
        "`%s` (creux, %.1f) **dépasse** `%s` (bon, %.1f)" % (nc, vc, nb, vb)
        for nb, vb in sb for nc, vc in sc if vc >= vb
    ]

    if marge < marge_min:
        return Resultat(
            False, pire_bon, meilleur_creux, marge, inversions, detail,
            "le pire des bons (`%s`, %.1f) ne dépasse le meilleur des creux (`%s`, %.1f) que de "
            "**%.1f** — il en faut **%.1f**. %s"
            % (pire_bon[0], pire_bon[1], meilleur_creux[0], meilleur_creux[1], marge, marge_min,
               ("Inversions : " + " · ".join(inversions[:3])) if inversions
               else "*Correct, mais de trop peu : un classement « de justesse » n'est pas fiable.*"),
        )

    return Resultat(True, pire_bon, meilleur_creux, marge, [], detail,
                    "le trieur sépare le connu. **On peut lui faire confiance sur l'inconnu.**")


def pourquoi_temoin() -> list[dict[str, str]]:
    """*Un jeu témoin sans justification est un jeu témoin arbitraire.*"""
    return (
        [{"repo": n, "attendu": "BON", "pourquoi": p} for n, _, p in BONS]
        + [{"repo": n, "attendu": "CREUX", "pourquoi": p} for n, _, p in CREUX]
    )


__all__ = ["BONS", "CREUX", "MARGE_MIN", "Resultat", "pourquoi_temoin", "verifier"]
