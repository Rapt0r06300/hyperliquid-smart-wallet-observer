r"""LA FICHE D'IDÉE — *quoi · **pourquoi** · **comment l'implémenter** · ce qui la RÉFUTERAIT.*

═══════════════════════════════════════════════════════════════════════════════════════════════
🔒 CE QUE J'AI DÉJÀ ACCEPTÉ — ET CE QUE JE N'AI **PAS** ACCEPTÉ
═══════════════════════════════════════════════════════════════════════════════════════════════

Flo demande d'écrire dans le `.md` : *« Claude a déjà accepté ces idées, c'est son script. »*

    ✅ **CE QUI EST VRAI, ET QUE J'ASSUME :**
       **LE FILTRE EST DE MOI.** Les critères de sélection — formule posée · **aveu de limite** ·
       chiffre vérifiable · pénalité de promesse creuse · score **différentiel** (ce qu'ils ont
       QUE NOUS N'AVONS PAS) — **sont exactement ceux que j'appliquerais en lisant moi-même**.
       ***Ce qui est dans ce fichier a passé MON jugement de tri. On ne re-débat pas du tri.***

    🔴 **CE QUI SERAIT FAUX, ET QUE JE REFUSE D'ÉCRIRE :**
       « **l'idée** est acceptée ». Elle ne l'est pas. **Le filtre dit : « ça vaut vingt minutes
       de lecture ».** Il ne dit **pas** : « ça marche ».

       ***Une idée n'est ACCEPTÉE que quand elle est MESURÉE CHEZ NOUS — après frais, spread,
       slippage, impact — et qu'elle bat un dépôt passif dans HLP.***

       Le taux de base est écrasant : **~600 idées mesurées, UNE survivante** (le carry).

    *Si ce fichier disait « Claude a validé ces idées », un agent futur les implémenterait sans
    les mesurer. **C'est exactement comme ça que ce projet s'est fait mal** — et c'est pourquoi
    je ne l'écrirai pas.*

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE CHAQUE FICHE CONTIENT
═══════════════════════════════════════════════════════════════════════════════════════════════

  **QUOI**            en une phrase, sans jargon
  **POURQUOI NOUS**   le trou **MESURÉ** de notre bot qu'elle comble
  **COMMENT**         le module cible · la fonction · **le test obligatoire** · le branchement
  **CE QUE ÇA COÛTE** en temps, et en risque
  🔑 **CE QUI LA RÉFUTERAIT** — *une idée qu'aucun résultat ne pourrait tuer n'est pas une idée :
                                 c'est une croyance.*

PUR : aucun réseau. Aucun ordre réel.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LE CATALOGUE DES IDÉES ACTIONNABLES.
#
# Chaque entrée relie **un concept du corpus** à **un trou mesuré chez nous**, avec le plan
# complet. *Une idée sans point d'ancrage n'est pas une idée : c'est une distraction.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class Modele:
    cle: str
    motifs: tuple[str, ...]
    quoi: str
    pourquoi: str
    ou: str
    comment: str
    test: str
    branchement: str
    cout: str
    refutation: str


CATALOGUE: tuple[Modele, ...] = (
    Modele(
        "kappa_fill",
        (r"\bkappa\b", r"exp\s*\(\s*-\s*k", r"fill\s*(probab|intensit)", r"arrival\s*intensit",
         r"lambda\s*\(\s*delta"),
        "Estimer **κ**, l'intensité d'exécution : λ(δ) = A·e^(−κδ). *Plus on s'éloigne du mid, "
        "moins on est rempli — et **de combien**, exactement.*",
        "🔴 **Notre simulateur suppose un fill maker à « 10 % du flux » — UN CHIFFRE INVENTÉ**, "
        "jamais mesuré. **Toute** conclusion sur le market making en dépend.",
        "nouveau `src/hl_observer/market/fill_intensity.py`, à côté de `flow_toxicity.py`",
        "Ajuster A et κ **par coin**, depuis nos propres L2 + trades (aucun L3 requis). "
        "Exposer `intensite(coin, distance_bps) -> proba | None`.",
        "`tests/test_fill_intensity.py` — 🔒 **un κ non mesurable doit faire REFUSER**, pas "
        "passer. *Ne pas savoir n'est pas une permission.*",
        "`noyau_unique.Contexte.kappa` + une **porte** calquée sur celle du VPIN (porte 6).",
        "~1 jour. **Risque faible** : c'est de la mesure, pas un pari.",
        "🔑 Si κ ajusté donne un fill **supérieur** à 100 %, le modèle est faux. Et **T1b a "
        "mesuré le MM à 100 % de fill : 0/29.** *Un vrai κ ne peut qu'**abaisser** ce fill — "
        "donc **confirmer** la mort du MM.* **Si ça le ressuscite, c'est le modèle qui ment.**",
    ),
    Modele(
        "queue_position",
        (r"qty[_\s]?ahead", r"queue\s*(posit|model)", r"cum[_\s]?trade[_\s]?qty",
         r"time\s*priority", r"\bfifo\b"),
        "Reconstruire **notre position dans la file** depuis les deltas L2 (`qty_ahead`).",
        "🔴 On ne modélise **aucune** file. Et hftbacktest nous a montré le bug jumeau : "
        "**le double comptage** (trade **ET** baisse du carnet) → des fills **2× trop tôt**.",
        "nouveau `src/hl_observer/backtesting/queue_model.py`",
        "`qty_ahead` par ordre, corrigé du double comptage : `chg -= cum_trade_qty`.",
        "`tests/test_queue_model.py` — 🔒 **verrouiller `fill_modélisé ≤ fill_100 %`.**",
        "**Il ne se branche PAS sur le chemin live** : il sert à **re-mesurer T1b**.",
        "~2 jours. **Risque : celui de se mentir** (voir réfutation).",
        "🔑 ***L'argument de domination :*** T1b a mesuré le MM à la **borne haute** (100 % de "
        "fill) → **0/29**. Un modèle de file ne peut qu'**abaisser** le fill. **Si le tien rend "
        "le MM rentable, il est FAUX** — et il faut le jeter, pas le croire.",
    ),
    Modele(
        "impact",
        (r"market\s*impact", r"price\s*impact", r"square[\s-]*root\s*law", r"almgren",
         r"propagator", r"temporary\s*impact"),
        "Modéliser **l'impact de marché** : notre propre ordre bouge le prix contre nous.",
        "🔴 **L'hypothèse qui expliquerait nos −7,97 bps de copy-trading** : on paie l'impact du "
        "leader **après** lui. On ne l'a **jamais** chiffré.",
        "`src/hl_observer/edge/edge_calculator.py` → `compute_net_edge()`",
        "L'impact est **un COÛT**. Il se **soustrait** de l'edge brut, **exactement comme** les "
        "frais (9 bps) et le slippage qu'on vient de brancher.",
        "`tests/test_impact.py` — 🔒 ***un coût qu'on mesure mais qu'on ne soustrait pas est un "
        "coût qu'on CACHE.*** **C'est arrivé 17 fois.** Le test doit prouver la soustraction.",
        "il entre dans le **plancher de 30 bps** de `noyau_unique`.",
        "~1 jour. **Risque faible.**",
        "🔑 Si l'impact chiffré **n'explique pas** les −7,97 bps, alors la cause est ailleurs — "
        "et c'est **aussi** une information. *Une mesure qui réfute mon hypothèse est une bonne "
        "mesure.*",
    ),
    Modele(
        "adverse",
        (r"adverse\s*select", r"markout", r"toxic", r"\bvpin\b", r"informed\s*trad",
         r"pick(ed)?\s*off"),
        "**Markout** : mesurer où va le prix **après** notre fill. *Le maker est rempli **quand "
        "il a tort**.*",
        "🔴 Jamais modélisé. Notre VPIN vient d'être branché **hier** — **aucune validation "
        "externe**.",
        "`src/hl_observer/market/flow_toxicity.py` (l'étendre, **ne pas le doubler**)",
        "Markout à +1 s / +10 s / +60 s **sur le mid**, par côté.",
        "`tests/test_flow_toxicity.py` — l'étendre. *Suspecter son propre outil avant le code "
        "d'autrui.*",
        "déjà branché : **porte 6** (`faut_il_s_abstenir`).",
        "~1 jour.",
        "Si le markout est **positif** après nos fills, on n'est pas sélectionné adversement — "
        "et **T1b a un trou**. *Il faut le savoir.*",
    ),
    Modele(
        "lookahead",
        (r"look[\s-]*ahead", r"data\s*leak", r"purged", r"\bembargo\b", r"walk[\s-]*forward",
         r"deflated\s*sharpe", r"backtest\s*overfit", r"probability\s*of\s*backtest"),
        "**Purge + embargo** dans la coupe train/test, et la **PBO** (probabilité de surajustement).",
        "🔴🔴 **Notre coupe train/test FUYAIT : 68 % de fuite** (ni purge ni embargo). "
        "*Le test était déjà dans le train.* Et **7 garde-fous anti-overfit avaient ZÉRO appelant**.",
        "`src/hl_observer/backtesting/` + `testing/lookahead_detector.py`",
        "Purge + embargo autour de chaque coupe. Calculer la **PBO** sur nos 1 425 000 scénarios.",
        "🔒 Le test doit **retrouver un lookahead CONNU** (`garch11_variance`) — sinon il **se "
        "tait**. *C'est le mécanisme de #562, et il a payé dès sa 2ᵉ exécution.*",
        "il **invalide ou valide** tout le reste. **À faire en premier.**",
        "~2 jours. 🔑 **Le meilleur rapport qualité/prix de la liste.**",
        "🔑 Si la PBO est élevée, **nos 1,4 M de scénarios ne valent rien** — et il vaut mille "
        "fois mieux l'apprendre maintenant. ***Une idée qu'aucun résultat ne pourrait tuer n'est "
        "pas une idée : c'est une croyance.***",
    ),
    Modele(
        "parite",
        (r"backtest.{0,25}live", r"live.{0,25}backtest", r"parity", r"reconcil",
         r"replay.{0,20}reproduce"),
        "🔑 **Le replay d'une période doit REPRODUIRE le live de cette période.**",
        "***Le critère de validation de hftbacktest — qu'on n'a JAMAIS appliqué.*** Si le replay "
        "et le live divergent, **l'un des deux ment** — et tout ce qu'on a mesuré repose dessus.",
        "`src/hl_observer/backtesting/backtest_live_parity.py` (**écrit, jamais appliqué**)",
        "Rejouer une fenêtre live enregistrée et comparer **fill par fill**.",
        "`tests/test_parity.py` — l'écart doit être **borné et expliqué**.",
        "🔒 **C'est un MÉTA-test** : il juge tous nos autres chiffres.",
        "~1 jour (le module existe).",
        "🔑 Si ça diverge, **tous nos backtests sont suspects** — y compris **le carry**. "
        "*C'est le test le plus dangereux de la liste. C'est pour ça qu'il faut le faire.*",
    ),
    Modele(
        "liquidation",
        (r"liquidat", r"cascade", r"forced\s*(selling|liquidat)", r"auto[\s-]*deleverag",
         r"\badl\b"),
        "🎯 Détecter les **cascades de liquidation** et se placer **du bon côté du flux forcé**.",
        "🎯 **LA DERNIÈRE PISTE NON MESURÉE.** ***Le liquidé ne CHOISIT pas de vendre : il est "
        "VENDU.*** C'est le seul flux du marché dont **le sens est connu d'avance** et **non "
        "discrétionnaire**.",
        "`src/hl_observer/backtesting/liquidation_cascade.py` (recorder **déjà branché**)",
        "Depuis l'état public : `liquidationPx` par position + la profondeur du carnet → "
        "estimer le **notionnel forcé** à chaque niveau de prix.",
        "`tests/test_liquidation_cascade.py` — 🔒 un signal **trop vieux** doit être refusé.",
        "`noyau_unique` — nouvelle famille de signal (**pas** une zone morte).",
        "~3 jours. **Il faut du temps de COLLECTE, pas du code.**",
        "🔑 **Elle peut très bien finir à ZÉRO, comme les six autres familles.** *Attends-toi à "
        "un échec — ce ne sera pas une défaite, ce sera une mesure.*",
    ),
    Modele(
        "carry",
        (r"funding\s*(rate|arb)", r"basis\s*trade", r"cash[\s-]*and[\s-]*carry",
         r"delta[\s-]*neutral", r"contango", r"backwardation"),
        "Le **carry delta-neutre** : long spot + short perp, on encaisse le funding.",
        "✅ **NOTRE SEULE PISTE MESURÉE POSITIVE** : PURR **+7,09 %** · HYPE **+4,47 %** APR, "
        "après frais **et** slippage 4 jambes. *Tout ce qui l'améliore vaut de l'or.*",
        "`src/hl_observer/strategies/carry_runtime.py` + `carry_scanner.py`",
        "Chercher : un meilleur **timing d'entrée** · la **prédiction** du funding · les **coûts** "
        "d'un autre venue · la **couverture** du risque de liquidation de la jambe perp.",
        "`tests/test_carry_*.py` — 🔒 *l'APR publié doit être le **NET**.* **Il a déjà été le "
        "BRUT une fois** (les coûts vérifiés à la porte, jamais soustraits du chiffre).",
        "**déjà branché** (porte 2 + porte 8, la jambe spot).",
        "variable.",
        "🔑 **Le funding peut s'inverser** — BERA (−0,83) et STABLE (−0,99) l'ont fait. Et le "
        "carry doit **battre un dépôt passif dans HLP**.",
    ),
    Modele(
        "execution",
        (r"optimal\s*execution", r"execution\s*cost", r"transaction\s*cost",
         r"\btwap\b", r"\bvwap\b", r"implementation\s*shortfall"),
        "**Découper** un ordre pour minimiser le coût total (impact + risque de dérive).",
        "On entre en **une fois**, à 500 $. *À cette taille c'est peut-être sans objet — "
        "**mais on ne l'a jamais vérifié**.* Et le carnet spot de **PUMP ne porte que 473 $**.",
        "`src/hl_observer/market/spot_depth.py` (l'étendre)",
        "Comparer : ordre unique **vs** découpé, sur le **carnet réel**.",
        "`tests/test_spot_depth.py` — l'étendre.",
        "porte 8 (la jambe spot).",
        "~1 jour.",
        "À 500 $ de notionnel, **le gain sera probablement nul** — *et alors on l'écrit et on "
        "passe à autre chose.* **Un « non » mesuré vaut mieux qu'un « peut-être ».**",
    ),
    Modele(
        "inventaire",
        (r"inventory\s*(risk|skew|penalt|control)", r"avellaneda", r"stoikov",
         r"reservation\s*price", r"\bglft\b", r"gueant|guéant"),
        "Le **terme d'inventaire** : coter **autour d'un prix de réservation**, pas du mid.",
        "***L'intuition « grinder » de Flo A un cadre mathématique (GLFT).*** Et ce qui la tue, "
        "c'est **précisément l'absence de terme d'inventaire**.",
        "**nulle part** — 🔴 `INSPIRE_ONLY`.",
        "**Ne PAS l'implémenter.** *Le MM est fermé* : T1b **0/29** à 100 % de fill, et **HLP — "
        "le MM *payé* par le protocole, et liquidateur — rend −0,01 % APR.**",
        "aucun. ***On ne branche pas une stratégie morte.***",
        "aucun.",
        "0.",
        "🔑 **Ça sert à COMPRENDRE pourquoi le grinder est mort**, pas à le ressusciter. "
        "*Si quelqu'un publie un MM retail rentable **après coûts** et **OOS**, alors on a raté "
        "quelque chose d'énorme — et **il faut le lire**.*",
    ),
)


@dataclass(slots=True)
class Idee:
    """Une idée **actionnable**, avec son plan complet."""
    cle: str
    quoi: str
    pourquoi: str
    ou: str
    comment: str
    test: str
    branchement: str
    cout: str
    refutation: str
    preuves: list[str] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cle": self.cle, "quoi": self.quoi, "pourquoi": self.pourquoi,
            "ou": self.ou, "comment": self.comment, "test": self.test,
            "branchement": self.branchement, "cout": self.cout,
            "ce_qui_la_refuterait": self.refutation,
            "preuves": self.preuves, "sources": self.sources,
        }

    def md(self) -> list[str]:
        m = [
            "### 💡 `%s`" % self.cle,
            "",
            "**Quoi.** %s" % self.quoi,
            "",
            "**Pourquoi NOUS.** %s" % self.pourquoi,
            "",
            "| | |",
            "|---|---|",
            "| 📍 **Où** | %s |" % self.ou,
            "| 🔧 **Comment** | %s |" % self.comment,
            "| 🧪 **Test (obligatoire)** | %s |" % self.test,
            "| 🔌 **Branchement** | %s |" % self.branchement,
            "| ⏱️ **Coût** | %s |" % self.cout,
            "",
            "> 🔑 **Ce qui la RÉFUTERAIT.** %s" % self.refutation,
            ">",
            "> *Une idée qu'aucun résultat ne pourrait tuer n'est pas une idée : c'est une "
            "croyance.*",
            "",
        ]
        if self.sources:
            m += ["**Les sources qui l'ont apportée :**", ""]
            for s in self.sources[:8]:
                m.append("- [%s](%s)  *(%s)*" % (s.get("titre", "")[:110], s.get("lien", ""),
                                                 s.get("source", "")))
            m.append("")
        if self.preuves:
            m += ["<details><summary>Les extraits qui l'ont déclenchée</summary>", ""]
            m += ["- « …%s… »" % p[:170] for p in self.preuves[:5]]
            m += ["", "</details>", ""]
        return m


def reconnaitre(texte: str) -> list[str]:
    """Quelles idées **actionnables** ce texte touche-t-il ?"""
    t = texte or ""
    return [m.cle for m in CATALOGUE
            if any(re.search(x, t, re.IGNORECASE) for x in m.motifs)]


def extraire_idees(trouvailles: Sequence[Mapping[str, Any]]) -> list[Idee]:
    """Regroupe **tout le corpus** en fiches d'idées **actionnables**.

    *Cent papiers sur le même sujet ne font pas cent idées : ils font **une** idée, **bien
    étayée**.*
    """
    par_cle: dict[str, Idee] = {}
    modeles = {m.cle: m for m in CATALOGUE}

    for t in trouvailles:
        blob = "%s %s" % (t.get("titre") or "", t.get("resume") or t.get("texte") or "")
        for cle in reconnaitre(blob):
            m = modeles[cle]
            if cle not in par_cle:
                par_cle[cle] = Idee(cle, m.quoi, m.pourquoi, m.ou, m.comment, m.test,
                                    m.branchement, m.cout, m.refutation)
            i = par_cle[cle]
            if t.get("lien"):
                i.sources.append({"titre": str(t.get("titre") or "")[:120],
                                  "lien": str(t.get("lien")),
                                  "source": str(t.get("source") or "")})
            for h in (t.get("honnetete") or [])[:1]:
                if h not in i.preuves:
                    i.preuves.append(str(h))

    # les idées les mieux étayées d'abord. *Une idée avec 20 sources n'est pas 20 idées.*
    return sorted(par_cle.values(), key=lambda x: -len(x.sources))


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔒 LE BLOC DE PRÉ-APPROBATION — *ce que j'ai accepté, et ce que je n'ai PAS accepté.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
PRE_APPROBATION = """
> ## 🔒 Ce que Claude a **déjà accepté** — et ce qu'il n'a **pas** accepté
>
> **Ce fichier a été produit par un script que j'ai écrit.** Donc :
>
> ### ✅ CE QUE J'AI DÉJÀ ACCEPTÉ — *n'y reviens pas*
>
> **LE FILTRE EST DE MOI.** Les critères de sélection sont **exactement** ceux que j'appliquerais
> en lisant moi-même : **formule posée** (*citer un nom est gratuit ; poser une formule veut dire
> qu'on a calculé*) · 🔑 **aveu de limite** (*dans un corpus où tout le monde promet de l'alpha,
> avouer une limite est la seule signature possible de l'honnêteté*) · **chiffre vérifiable** ·
> **pénalité** pour promesse creuse · **score différentiel** (*ce qu'ils ont **que nous n'avons
> pas***).
>
> Et le **canari** l'a validé avant le run : le trieur a **prouvé** qu'il retrouve les repos
> qu'on **sait** bons — sinon **le run se serait arrêté sans rendre aucun verdict**.
>
> 👉 **Le tri n'est pas à re-débattre. Ce qui est ici mérite d'être lu.**
>
> ### 🔴 CE QUE JE N'AI **PAS** ACCEPTÉ — *et je refuse de faire semblant*
>
> **Que ces idées MARCHENT.**
>
> Le filtre dit : *« ça vaut vingt minutes de lecture »*.
> Il ne dit **pas** : *« ça gagne de l'argent »*.
>
> ***Une idée n'est ACCEPTÉE que quand elle est MESURÉE CHEZ NOUS*** — après frais, spread,
> slippage, impact — ***et qu'elle bat un dépôt passif dans HLP*** (mesuré : **−0,01 % APR**).
>
> **Le taux de base est écrasant : ~600 idées mesurées, UNE survivante** (le carry).
>
> *Si ce fichier disait « Claude a validé ces idées », un agent futur les implémenterait **sans
> les mesurer**. **C'est exactement comme ça que ce projet s'est fait mal** — et c'est pourquoi
> je ne l'écrirai pas.*
>
> ---
"""


__all__ = ["CATALOGUE", "PRE_APPROBATION", "Idee", "Modele", "extraire_idees", "reconnaitre"]
