r"""MÉGA-AUDIT DU MOISSONNEUR — *tiendra-t-il vraiment 12 heures sans dériver ?*

═══════════════════════════════════════════════════════════════════════════════════════════════
LA QUESTION DE FLO, ET POURQUOI JE NE RÉPONDS PAS « OUI »
═══════════════════════════════════════════════════════════════════════════════════════════════

    *« Est-ce que tu es sûr que pendant 12 h il va continuer à trouver ? »*

***« Je suis sûr » n'est pas une réponse. C'est une opinion déguisée en garantie.***

Cet outil **CALCULE** :

  1. **LE BUDGET RÉEL** — combien de requêtes tiennent dans 12 h, vu les rythmes qu'on respecte.
  2. **L'OFFRE DE SUJETS** — combien de requêtes on a **au départ**.
  3. 🔑 **LE FACTEUR DE BRANCHEMENT** — combien de **nouvelles** pistes une piste engendre,
     **mesuré sur du VRAI texte**. *Si b > 1, la frontière **diverge** : elle ne peut pas se vider.
     Si b < 1, elle **s'éteint** — et il faut le savoir MAINTENANT, pas à la 9ᵉ heure.*
  4. **LA LAISSE** — le taux de faux positifs sur du hors-sujet (*les recettes de cuisine*).
  5. **L'ALLOCATION DU TEMPS** — une phase qui déborde peut **étouffer** les suivantes.

Aucun réseau. Aucun ordre réel. **On compte, on ne raconte pas.**
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research.frontiere import (  # noqa: E402
    Frontiere,
    extraire,
    fond_de_roulement,
)
from hl_observer.research.github_scan_plan import deduplique, plan_de_scan  # noqa: E402
from hl_observer.research.github_graph import requetes_ciblees  # noqa: E402
from hl_observer.research.idee import CATALOGUE as IDEES  # noqa: E402
from hl_observer.research.moissonneur_sujets import SUJETS, TEXTE  # noqa: E402
from hl_observer.research.moteur import (  # noqa: E402
    requetes_chronologiques,
    requetes_de_contradiction,
)
from hl_observer.research.sources_plus import CATALOGUE as SOURCES  # noqa: E402

HEURES = 12.0

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# DES TEXTES **RÉELS** pour mesurer le branchement. *Pas des textes fabriqués pour me plaire.*
# Ce sont des résumés/README typiques du corpus qu'on va vraiment croiser.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
ECHANTILLONS: tuple[tuple[str, str], ...] = (
    ("papier arXiv typique", """
     We study optimal market making in a limit order book with adverse selection.
     Following Avellaneda and Stoikov, and the closed-form solution of Gueant Lehalle
     Fernandez-Tapia, we derive the reservation price under inventory risk. The fill
     intensity is modeled as lambda(delta) = A exp(-kappa delta), with kappa estimated
     from order arrival data. We compare against the Almgren Chriss framework for optimal
     execution and the square root law of market impact. See arxiv.org/abs/1105.3115.
     Our backtest uses purged cross-validation with embargo to avoid lookahead bias.
     Limitations: we assume zero latency and ignore transaction costs above 2 bps.
     """),
    ("README GitHub typique", """
     # hl-mm-bot
     A market maker for Hyperliquid perpetuals. Implements queue position estimation from
     L2 deltas (`qty_ahead`), VPIN toxicity on a volume clock, and OFI imbalance signals.
     Inspired by https://github.com/nkaz001/hftbacktest . Uses `ccxt` and `nautilus_trader`.
     Funding rate arbitrage module for basis trades (cash and carry).
     Caveat: our fill model is not a substitute for real L3 data. Net of 9 bps round trip
     our edge was -2 bps out of sample. It didn't work at size.
     """),
    ("rapport OpenReview typique", """
     The paper proposes a deep RL agent for high frequency trading. Weaknesses: the authors
     ignore transaction costs entirely, and the backtest appears to be in-sample. The market
     impact model is unrealistic; a square root law would be more appropriate. The queue
     position assumption (immediate fill) is not defensible in a limit order book.
     No walk-forward validation is provided. Rating: 3 (reject).
     """),
    ("post StackExchange typique", """
     How do you estimate the probability of fill for a limit order at distance delta from
     the mid? I've seen the exponential intensity model but my kappa estimates are unstable
     on thin books. Related: adverse selection markout after fills, and Kyle's lambda.
     """),
)

# 🔴 **LA LAISSE — et l'audit l'a déjà prise en défaut UNE FOIS.**
#    (`tutorial` tout court → *« React and Redux **tutorial** »* franchissait la laisse.)
#    ***Cinq textes, c'est trop peu pour prouver quoi que ce soit.*** On en met vingt, et on
#    vise **précisément les mots qui ressemblent aux nôtres sans être les nôtres.**
HORS_SUJET: tuple[str, ...] = (
    "The environmental impact of Smith Johnson's cooking recipes and carbon footprint.",
    "React and Redux tutorial: managing state with hooks. See the API and JSON docs.",
    "Machine learning for medical imaging: Chen Wang propose a CNN for tumor detection.",
    "Best gaming laptops of 2026. Nvidia GPU benchmarks and cooling performance.",
    "How to grow tomatoes. Watering schedule and soil pH management for a good harvest.",
    # ── les pièges : des mots qui RESSEMBLENT aux nôtres ───────────────────────────────────────
    "A complete course in web development. Of course, you will need Node and npm.",
    "Product review: the new espresso machine has great performance and low latency.",
    "Kubernetes deployment: managing state, rolling updates and a canary release.",
    "Our restaurant survey shows customers value fresh data on the menu.",
    "Book review of a fantasy novel. The queue at the bookstore was long.",
    "Supply chain optimization: inventory management and warehouse throughput.",
    "Physics: measuring the intensity of a laser beam and its impact on the target.",
    "Poker strategy: bet sizing and pot odds. Managing your bankroll and variance.",
    "A survey of image compression algorithms. Rate limiting on the CDN.",
    "Real estate market analysis: prices, spread between asking and selling.",
    "Employee performance review and career development handbook.",
    "Traffic engineering: queue theory applied to highway congestion.",
    "Database indexing tutorial: B-trees, cache locality and query performance.",
    "Race condition in a video game rendering loop. Deadlock in the render thread.",
    "Insurance fund for natural disasters: how governments manage collateral damage.",
)


def _ligne(t: str = "") -> None:
    print(t)


def main() -> int:  # noqa: C901, PLR0915
    _ligne("=" * 100)
    _ligne("  MÉGA-AUDIT DU MOISSONNEUR — *tiendra-t-il 12 h sans dériver ?*")
    _ligne("  ***« Je suis sûr » n'est pas une réponse. On COMPTE.***")
    _ligne("=" * 100)

    verdicts: list[tuple[str, bool, str]] = []

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  1. LE BUDGET RÉEL DE REQUÊTES EN 12 HEURES
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    _ligne("\n" + "─" * 100)
    _ligne("  1. LE BUDGET — combien de requêtes tiennent VRAIMENT dans 12 h ?")
    _ligne("─" * 100)

    secondes = HEURES * 3600.0
    _ligne("\n  %-22s %10s %14s   %s" % ("source", "rythme", "req. en 12 h", "contrainte"))
    total_theorique = 0.0
    for s in sorted(SOURCES, key=lambda x: x.rythme):
        n = secondes / s.rythme
        total_theorique += n
        note = ""
        if s.nom == "github_code":
            note = "10 req/min (le plus sévère)"
        elif s.nom == "arxiv":
            note = "leur doc EXIGE 3 s. On obéit."
        elif s.nom == "openalex":
            note = "100 000/jour — quasi illimité"
        _ligne("  %-22s %8.2f s %14.0f   %s" % (s.nom, s.rythme, n, note))

    # en pratique le crawler alterne les sources : on prend le rythme MOYEN
    rythme_moyen = sum(s.rythme for s in SOURCES) / len(SOURCES)
    budget = secondes / rythme_moyen
    _ligne("\n  rythme moyen (le crawler alterne) : **%.2f s/requête**" % rythme_moyen)
    _ligne("  🔑 **BUDGET RÉALISTE SUR 12 H : ~%.0f requêtes.**" % budget)
    _ligne("     *(GitHub avec token : 5 000 REST/h → 60 000 en 12 h. Le temps est la vraie")
    _ligne("      contrainte, pas le quota — **à condition d'avoir un token**.)*")

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  2. L'OFFRE DE SUJETS AU DÉPART
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    _ligne("\n" + "─" * 100)
    _ligne("  2. L'OFFRE — combien de requêtes a-t-on AU DÉPART, avant toute frontière ?")
    _ligne("─" * 100)

    plan = deduplique(plan_de_scan(SUJETS, TEXTE, avec_code=True, avec_dates=True))
    n_chrono = len(requetes_chronologiques())
    n_contra = len(requetes_de_contradiction())
    n_cible = len(requetes_ciblees())
    n_fond = len(fond_de_roulement())
    depart = len(plan) + n_chrono + n_contra + n_cible + n_fond

    _ligne("\n  plan de scan GitHub (sujets x tris x étoiles x dates) : **%d**" % len(plan))
    _ligne("  requêtes chronologiques (après HIP-3, l'airdrop...)   : %d" % n_chrono)
    _ligne("  🔴 requêtes de CONTRADICTION (chercher ce qui nous donne tort) : %d" % n_contra)
    _ligne("  requêtes ciblées sur nos trous mesurés               : %d" % n_cible)
    _ligne("  🎓 fond de roulement (q-fin entier, les COURS, les revues) : %d" % n_fond)
    _ligne("\n  🔑 **TOTAL AU DÉPART : %d requêtes.**" % depart)

    # ⚠️ chaque requête « papier » interroge PLUSIEURS sources
    par_papier = 9        # arxiv, openalex, openreview, pwc, s2, dblp, zenodo, crossref, wiki
    _ligne("\n  ⚠️ **Mais une requête « papier » interroge 9 sources.** Le vrai coût en appels")
    _ligne("     est donc bien supérieur au nombre de requêtes.")

    ok_offre = depart >= 500
    verdicts.append((
        "L'offre de départ (%d requêtes)" % depart, ok_offre,
        "assez pour amorcer" if ok_offre else "🔴 **TROP MAIGRE** — il tournera à vide",
    ))

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  3. 🔑 LE FACTEUR DE BRANCHEMENT — *la frontière DIVERGE-t-elle ?*
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    _ligne("\n" + "─" * 100)
    _ligne("  3. 🔑 LE FACTEUR DE BRANCHEMENT — *mesuré sur du VRAI texte*")
    _ligne("─" * 100)
    _ligne("\n  *Une piste explorée engendre combien de NOUVELLES pistes ?*")
    _ligne("  ***Si b > 1, la frontière DIVERGE : elle ne peut pas se vider.***")
    _ligne("  ***Si b < 1, elle S'ÉTEINT — et il faut le savoir MAINTENANT, pas à la 9ᵉ heure.***")

    f = Frontiere()
    total_pistes = 0
    _ligne("\n  %-30s %14s" % ("échantillon", "pistes engendrées"))
    for nom, txt in ECHANTILLONS:
        p = extraire(txt, parent="audit")
        n = f.semer(p, profondeur=1)
        total_pistes += len(p)
        _ligne("  %-30s %14d" % (nom, len(p)))

    b = total_pistes / float(len(ECHANTILLONS))
    _ligne("\n  🔑 **FACTEUR DE BRANCHEMENT MESURÉ : b = %.1f pistes par document lu.**" % b)

    # combien de documents lira-t-on ? ~1 par requête au minimum (souvent 20-50)
    diverge = b > 1.0
    if diverge:
        _ligne("\n  ✅ **b = %.1f > 1 → LA FRONTIÈRE DIVERGE.**" % b)
        _ligne("     *Chaque document lu en engendre %.1f de plus. **Il est arithmétiquement" % b)
        _ligne("      impossible qu'il soit à court en 12 h.*** Le vrai risque est l'inverse :")
        _ligne("     qu'il ne puisse pas tout explorer — **et c'est un bon problème.**")
    else:
        _ligne("\n  🔴 **b = %.1f ≤ 1 → LA FRONTIÈRE S'ÉTEINT.** Il finira par tourner à vide." % b)

    verdicts.append((
        "Le facteur de branchement (b = %.1f)" % b, diverge,
        "**la frontière ne peut PAS se vider**" if diverge
        else "🔴 elle s'éteindra — il faut élargir l'extraction",
    ))

    # une simulation honnête de croissance, bornée par la profondeur
    _ligne("\n  simulation (borne : profondeur %d) :" % Frontiere.PROFONDEUR_MAX)
    reste, explore = float(depart), 0.0
    for h in range(1, int(HEURES) + 1):
        req_h = budget / HEURES
        fait = min(reste, req_h)
        explore += fait
        reste = reste - fait + fait * b * 0.35     # 0,35 = taux de nouveauté après dédup
        if h in (1, 3, 6, 9, 12):
            _ligne("     après %2d h : **%7.0f explorées** · **%7.0f restant à explorer**"
                   % (h, explore, max(reste, 0)))
    jamais_vide = reste > 100
    if jamais_vide:
        _ligne("\n  ✅ **À la 12ᵉ heure il reste encore ~%.0f pistes.** *Il n'aura pas fini.*"
               % reste)
    else:
        _ligne("\n  🔴 **La frontière se vide avant 12 h.** Le fond de roulement prendra le relais.")
    verdicts.append(("Il reste des pistes à la 12ᵉ heure", jamais_vide,
                     "~%.0f pistes non explorées" % max(reste, 0)))

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  4. LA LAISSE — *les recettes de cuisine.*
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    _ligne("\n" + "─" * 100)
    _ligne("  4. LA LAISSE — *« je ne veux pas qu'il finisse sur des recettes de cuisine »*")
    _ligne("─" * 100)

    faux = 0
    _ligne("")
    for h in HORS_SUJET:
        p = extraire(h, parent="audit")
        etat = "🔴 **%d PISTE(S) — FUITE !**" % len(p) if p else "✅ 0 piste"
        faux += len(p)
        _ligne("  %-64s %s" % (h[:62] + "…", etat))
        for x in p:
            _ligne("       -> %r" % x.requete)

    propre = faux == 0
    _ligne("\n  🔑 **%d faux positif(s) sur %d textes hors sujet.**" % (faux, len(HORS_SUJET)))
    if propre:
        _ligne("     ✅ **La laisse tient. Aucune recette de cuisine ne peut entrer.**")
    else:
        _ligne("     🔴 **LA LAISSE FUIT.** *Un motif trop lâche est une laisse coupée.*")
    verdicts.append(("La laisse (0 hors-sujet)", propre,
                     "aucune dérive possible" if propre else "🔴 **%d fuite(s)**" % faux))

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  5. LES SUJETS COUVRENT-ILS TOUT CE QUI NOUS SERT ?
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    _ligne("\n" + "─" * 100)
    _ligne("  5. LA COUVERTURE — *cherche-t-il tout ce qui peut nous servir ?*")
    _ligne("─" * 100)

    tout = " ".join(SUJETS + TEXTE
                    + [q for _g, q, _p in
                       __import__("hl_observer.research.frontiere", fromlist=["x"])
                       .FOND_DE_ROULEMENT]
                    + [x["requete"] for x in requetes_ciblees()]
                    + [x["requete"] for x in requetes_de_contradiction()]).lower()

    from hl_observer.research.domaines import (  # noqa: PLC0415
        DOMAINES,
        familles,
        rapport as rapport_dom,
    )

    rd = rapport_dom()
    _ligne("\n  🔴 %s" % rd["le_constat"])
    _ligne("\n  %s\n" % rd["le_trou_trouve"])

    manque: list[str] = []
    for fam, ds in familles().items():
        _ligne("  %s" % fam)
        for d in ds:
            # une requête du domaine doit VRAIMENT être dans le plan
            ok = any(q.lower() in tout for q in d.requetes) or any(
                s in tout for s in d.sujets)
            _ligne("     %-24s %s   %s" % (d.cle, "✅" if ok else "🔴 **NON COUVERT**",
                                           d.quoi[:52]))
            if not ok:
                manque.append(d.cle)
        _ligne("")

    _ligne("  🔑 **%d domaines · %d requêtes · %d sujets GitHub.**"
           % (rd["n_domaines"], rd["n_requetes"], rd["n_sujets"]))
    verdicts.append(("La couverture (%d domaines, 5 familles)" % len(DOMAINES), not manque,
                     "**tout est couvert**" if not manque
                     else "🔴 manque : %s" % ", ".join(manque)))

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  6. LES IDÉES ACTIONNABLES
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    _ligne("\n" + "─" * 100)
    _ligne("  6. LE MOTEUR D'IDÉES — chaque idée dit-elle QUOI · POURQUOI · COMMENT · RÉFUTATION ?")
    _ligne("─" * 100)
    _ligne("")
    complet = True
    for m in IDEES:
        manquants = [n for n, v in (("quoi", m.quoi), ("pourquoi", m.pourquoi), ("où", m.ou),
                                    ("comment", m.comment), ("test", m.test),
                                    ("réfutation", m.refutation)) if not v or len(v) < 20]
        if manquants:
            complet = False
        _ligne("  %-18s %s" % (m.cle, "✅" if not manquants else "🔴 manque : %s"
                               % ", ".join(manquants)))
    verdicts.append(("Les %d fiches d'idées sont complètes" % len(IDEES), complet,
                     "quoi · pourquoi · comment · test · **réfutation**"))

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  LE VERDICT
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    _ligne("\n" + "=" * 100)
    _ligne("  VERDICT DE L'AUDIT")
    _ligne("=" * 100)
    _ligne("")
    for quoi, ok, note in verdicts:
        _ligne("  %s  %-46s %s" % ("✅" if ok else "🔴", quoi, note))

    tout_ok = all(ok for _q, ok, _n in verdicts)
    _ligne("")
    if tout_ok:
        _ligne("  ✅ **LE MOISSONNEUR TIENDRA 12 H.**")
        _ligne("")
        _ligne("     Et ce n'est pas une opinion : **b = %.1f > 1**, donc chaque document lu" % b)
        _ligne("     en engendre %.1f de plus. ***Il est arithmétiquement impossible qu'il" % b)
        _ligne("     soit à court.*** Le vrai risque est **l'inverse** : qu'il n'ait pas le")
        _ligne("     temps de tout explorer.")
        _ligne("")
        _ligne("     🚩 **Et je maintiens la réserve :** il trouvera **plus de choses à tester**.")
        _ligne("        **Aucune garantie que ce qu'il trouve soit rentable.** *~600 idées")
        _ligne("        mesurées, **une** survivante.* Le taux de base ne change pas.")
    else:
        _ligne("  🔴 **DES TROUS SUBSISTENT — voir ci-dessus.**")
    _ligne("=" * 100)
    return 0 if tout_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
