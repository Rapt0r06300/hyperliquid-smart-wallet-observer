r"""LE PLAN DE SCAN — *comment franchir le plafond de 1 000, et où le scan était AVEUGLE.*

═══════════════════════════════════════════════════════════════════════════════════════════════
🔴 LES 4 DÉFAUTS DU SCAN — mesurés, pas supposés
═══════════════════════════════════════════════════════════════════════════════════════════════

**DÉFAUT 1 — IL EXCLUAIT LES REPOS SOUS 5 ÉTOILES.** *Le pire, et le plus ironique.*

    `TRANCHES_ETOILES = ["5..20", ...]`  # commentaire : « On ignore < 5 etoiles »

    Or la moisson de 5 617 repos a **MESURÉ** que les **4 repos les plus exactement sur cible**
    avaient **1, 2, 3 et 3 étoiles** :

        `Giri-Aayush/hyperliquid-data-pipeline`  — position FIFO **depuis le nœud**
        `horn111/hip4-mm-simulator`              — file par volume cumulé, latence 50 ms
        `zer0cache/hyperliquid-market-maker-bot` — MarkoutTracker
        `mackinac/dex-exec`                      — la jambe de couverture de T2

    ***Le scan écartait À L'ENTRÉE exactement le profil qu'on a mesuré comme le meilleur.***

    C'est **le même préjugé** que celui qu'on vient de tuer dans le tri (« étoiles = qualité »).
    Il vivait aussi dans le **scan** — *une capacité présente, un chaînon manquant, personne qui
    se plaint.* **19ᵉ fois.**

**DÉFAUT 2 — LE PLAFOND DE 1 000 N'ÉTAIT FRANCHI QUE ×5.** Les tranches d'étoiles donnent
    5 × 1 000. La partition par **DATE DE CRÉATION** en donne **autant qu'on veut** :
    `created:2024-01-01..2024-03-31` est une requête *différente* pour GitHub.
    → 6 ans × 4 trimestres = **24 tranches**, soit **24 000 résultats accessibles** par sujet.

**DÉFAUT 3 — IL NE CHERCHAIT JAMAIS DANS LE CODE.** 🔑 *La vraie réponse à « chercher partout ».*

    `/search/code` cherche **À L'INTÉRIEUR des fichiers**. Un repo dont le code contient
    `qty_ahead` ou `exp(-kappa` est pertinent **même s'il n'a ni topic, ni étoile, ni README**.

    ***Et on a déjà établi que le README est du marketing. Chercher dans le code, c'est
    chercher dans la vérité.***

**DÉFAUT 4 — `sort=stars` BIAISAIT CHAQUE PAGE.** Avec un plafond à 1 000, trier par étoiles
    revient à ne voir **que les gros** — c'est-à-dire à re-commettre le défaut 1 à chaque requête.
    → on partitionne (et alors le tri n'a plus d'importance) et on alterne `updated` / pertinence.

PUR : aucun réseau. Ce module **fabrique un plan**. Aucun ordre réel.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Sequence

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔴 LES TRANCHES D'ÉTOILES — **on descend jusqu'à ZÉRO.**
#
# *Les 4 repos les plus exactement sur cible avaient 1, 2, 3 et 3 étoiles.*
# Un repo à 0 étoile n'est pas « mauvais » : c'est un repo **que personne n'a encore lu**.
# Et notre tri, lui, ne récompense plus les étoiles (0,35·√⭐) — il récompense la **substance**.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
TRANCHES_ETOILES: tuple[str, ...] = (
    "0..1",        # 🔑 LA TRANCHE QU'ON S'INTERDISAIT. Elle contient nos meilleures cibles.
    "2..4",        # 🔑 idem : 3 des 4 meilleurs sont ici.
    "5..20",
    "21..60",
    "61..200",
    "201..800",
    ">800",
)

# Hyperliquid a lancé son mainnet fin 2023. Avant 2020, rien de pertinent pour un perp DEX.
PREMIERE_ANNEE = 2020


def tranches_de_dates(annee_debut: int = PREMIERE_ANNEE,
                      annee_fin: int | None = None,
                      *, mois_par_tranche: int = 3) -> list[str]:
    """La partition **par date de création**. *Le seul moyen de vraiment franchir les 1 000.*

    `created:2024-01-01..2024-03-31` est une requête **différente** pour GitHub : elle a son
    **propre quota de 1 000**. Avec 24 tranches, on accède à **24 000 résultats** là où les
    tranches d'étoiles n'en donnaient que 5 000.
    """
    fin = annee_fin or date.today().year
    out: list[str] = []
    for an in range(annee_debut, fin + 1):
        m = 1
        while m <= 12:
            m2 = min(m + mois_par_tranche - 1, 12)
            # dernier jour du mois m2, sans dépendre d'une lib de calendrier
            if m2 == 12:
                fin_j = date(an, 12, 31)
            else:
                fin_j = date(an, m2 + 1, 1).toordinal() - 1
                fin_j = date.fromordinal(fin_j)
            out.append("created:%s..%s" % (date(an, m, 1).isoformat(), fin_j.isoformat()))
            m = m2 + 1
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔑 LA RECHERCHE DANS LE **CODE** — la vraie réponse à « chercher partout ».
#
# `/search/code` regarde **À L'INTÉRIEUR des fichiers**. Elle trouve un repo :
#   * sans topic,
#   * sans étoile,
#   * dont le README ne dit rien,
#   * mais dont le **code** contient la formule qu'on cherche.
#
# ***Le README est la page de vente. Le code est la vérité. On cherche enfin dans la vérité.***
#
# ⚠️ `/search/code` **EXIGE un token** (et 10 req/min). Sans token : impossible, et on le DIT.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
REQUETES_CODE: tuple[tuple[str, str], ...] = (
    # (la requête code, le trou de NOTRE bot qu'elle vise)
    ('"qty_ahead" language:python',
     "la position dans la file — notre fill maker est un chiffre INVENTÉ (« 10 % du flux »)"),
    ('"queue_position" language:python',
     "idem — et un repo peut l'implémenter sans jamais l'écrire dans son README"),
    ('"cum_trade_qty"',
     "le **double comptage** des fills (trade ET baisse du carnet) — bug trouvé chez hftbacktest"),
    ('"exp(-kappa" language:python',
     "κ, l'intensité de fill : λ(δ) = A·e^(−κδ). **Jamais mesuré chez nous.**"),
    ('"A * np.exp(-kappa"',
     "la meme intensite de fill, ecrite en numpy — *un filtre trop etroit rate en silence*"),
    ('"reservation_price" language:python',
     "Avellaneda-Stoikov : coter autour du prix de réservation, pas du mid"),
    ('"inventory_skew"',
     "le terme d'inventaire — *c'est précisément ce qui manquait au grinder*"),
    ('"markout" language:python',
     "la sélection adverse : le maker est rempli **quand il a tort**"),
    ('"fundingRate" "hyperliquid"',
     "le carry — **notre seule stratégie mesurée positive** (PURR +7,09 %)"),
    ('"predictedFundings"',
     "l'endpoint HL qu'on vient de brancher — qui d'autre l'utilise, et comment ?"),
    ('"liquidationPx"',
     "🎯 les liquidations — **la dernière piste non mesurée**"),
    ('"purged" "embargo" language:python',
     "la coupe train/test — **la nôtre FUYAIT** (68 % de fuite, ni purge ni embargo)"),
    ('"deflated_sharpe"',
     "les 7 garde-fous anti-overfit qui avaient **zéro appelant** chez nous"),
    ('"probability_of_backtest_overfitting"',
     "la PBO — combien de nos 1 425 000 scenarios etaient de l'overfit ? **On ne l'a jamais su.**"),
    ('"square_root_impact" OR "sqrt_impact"',
     "l'impact de marché — l'hypothèse qui expliquerait nos **−7,97 bps**"),
    ('"MinTradeNtl" OR "BadAloPx"',
     "les contraintes d'exchange HL qu'on vient de brancher — validation externe"),
)


@dataclass(frozen=True, slots=True)
class Requete:
    """Une requête du plan. Elle porte **sa provenance** — *une requête sans motif est du bruit.*"""
    q: str
    genre: str                # "repo" | "code"
    pourquoi: str
    tri: str = "stars"

    def as_dict(self) -> dict[str, Any]:
        return {"q": self.q, "genre": self.genre, "pourquoi": self.pourquoi, "tri": self.tri}


# On alterne le tri : avec un plafond à 1 000, **`sort=stars` ne montre QUE les gros** —
# c'est-à-dire qu'il re-commet le défaut n°1 à chaque requête.
TRIS = ("stars", "updated", "")        # "" = pertinence (best match)


def plan_de_scan(
    sujets: Sequence[str],
    requetes_texte: Sequence[str],
    *,
    avec_code: bool = True,
    avec_dates: bool = True,
    tranches_etoiles: Sequence[str] = TRANCHES_ETOILES,
    annee_debut: int = PREMIERE_ANNEE,
) -> list[Requete]:
    """Le plan complet, **du plus rentable au plus profond**.

    L'ordre n'est pas décoratif : un scan peut être **interrompu à tout moment** (Ctrl-C, quota).
    ***Ce qu'on met en premier est ce qu'on est sûr d'avoir.***
    """
    plan: list[Requete] = []

    # 1) 🔑 LE CODE D'ABORD. *C'est la seule source qui ne peut pas mentir.*
    #    Et si le quota casse le scan, on aura au moins CELA.
    if avec_code:
        for q, pourquoi in REQUETES_CODE:
            plan.append(Requete(q, "code", pourquoi))

    # 2) le texte libre : attrape les repos **sans aucun topic** (la majorité des petits projets)
    for t in requetes_texte:
        plan.append(Requete(t, "repo", "texte libre — les repos sans topic", "stars"))

    # 3) une passe simple par sujet, dans les 3 tris (le tri par étoiles ne montre QUE les gros)
    for s in sujets:
        for tri in TRIS:
            plan.append(Requete("topic:%s" % s, "repo",
                                "sujet, tri=%s" % (tri or "pertinence"), tri))

    # 4) 🔴 LES PETITES ÉTOILES EN PREMIER — *là où sont nos meilleures cibles.*
    for s in sujets:
        for tr in tranches_etoiles:
            plan.append(Requete("topic:%s stars:%s" % (s, tr), "repo",
                                "tranche d'étoiles %s%s" % (
                                    tr,
                                    "  🔑 **la tranche qu'on s'interdisait**"
                                    if tr in ("0..1", "2..4") else ""),
                                "updated"))

    # 5) la partition par DATE : le seul vrai moyen de dépasser les 1 000.
    if avec_dates:
        dates = tranches_de_dates(annee_debut)
        for s in sujets:
            for d in dates:
                plan.append(Requete("topic:%s %s" % (s, d), "repo",
                                    "partition par date — **le plafond de 1 000 tombe**",
                                    "stars"))

    return plan


def deduplique(plan: Iterable[Requete]) -> list[Requete]:
    """Deux requêtes identiques = un appel réseau gaspillé. *Et le quota est notre limite.*"""
    vus: set[tuple[str, str, str]] = set()
    out: list[Requete] = []
    for r in plan:
        cle = (r.q, r.genre, r.tri)
        if cle not in vus:
            vus.add(cle)
            out.append(r)
    return out


def resume(plan: Sequence[Requete]) -> dict[str, Any]:
    """*Un plan qu'on ne peut pas chiffrer est un plan qu'on ne peut pas budgéter.*"""
    n_code = sum(1 for r in plan if r.genre == "code")
    n_repo = len(plan) - n_code
    return {
        "n_requetes": len(plan),
        "n_code": n_code,
        "n_repo": n_repo,
        # 10 req/min sur /search/code (avec token), 30 req/min sur /search/repositories
        "minutes_estimees": round(n_code / 10.0 + n_repo / 30.0, 1),
        "plafond_contourne": ("les tranches d'étoiles donnent 5x1000 ; **la partition par DATE "
                              "en donne autant qu'on veut** (24 tranches = 24 000 résultats)"),
        "note": ("🔑 La recherche **dans le CODE** trouve un repo **sans topic, sans étoile et "
                 "dont le README ne dit rien**. *Le README est la page de vente ; le code est "
                 "la vérité.*"),
        "avertissement_token": ("⚠️ `/search/code` **EXIGE un token** GitHub (lecture seule). "
                                "Sans lui, les %d requêtes code sont **impossibles** — et on le "
                                "DIT, on ne fait pas semblant." % n_code),
    }


__all__ = [
    "PREMIERE_ANNEE", "REQUETES_CODE", "TRANCHES_ETOILES", "TRIS",
    "Requete", "deduplique", "plan_de_scan", "resume", "tranches_de_dates",
]
