"""LES LOIS MESURÉES — ce que NOS chiffres ont déjà tranché (21/07).

POURQUOI CE FICHIER EXISTE
--------------------------
Depuis le 11 juillet, une dizaine d'idées ont été tuées non par une opinion mais par une
MESURE : le copy-trading global (−7,97 bps sur 24 133 signaux hors échantillon), le
market-making dans le spread (0 gagnant sur 29, à 100 % de fill), le lead-lag BTC→alts
(0/66), le funding perp↔perp (0/120)…

**Ces verdicts ne vivaient nulle part dans le dépôt.** Ils existaient dans la mémoire d'une
session de travail. Conséquence concrète : une autre session, un autre outil, ou moi-même
après un redémarrage, pouvait rouvrir une piste déjà réfutée — au mieux perdre des jours,
au pire *l'implémenter* et remettre dans le bot une stratégie qu'on avait prouvée perdante.

Ce module est le registre. Il suit exactement le motif déjà en place pour les garde-fous
enterrés (`risk/tombstones.py`) : une décision écrite, datée, avec le nombre qui l'a tuée et
l'endroit où le vérifier. Pas de prose vague — un chiffre ou rien.

CE QU'UNE LOI N'EST PAS
-----------------------
Ce n'est **pas** un interdit de penser. Une loi dit : « sur les données qu'on avait, à cette
date, ce mécanisme n'a pas payé, voici le chiffre ». Elle se rouvre — mais alors il faut une
DONNÉE nouvelle, pas un argument neuf. `condition_de_reouverture` dit laquelle.

C'est la différence entre un projet qui apprend et un projet qui tourne en rond.
"""
from __future__ import annotations

from dataclasses import dataclass, field

VERDICT_REFUTE = "REFUTE"          # mesuré perdant / sans edge
VERDICT_CONFIRME = "CONFIRME"      # mesuré positif, en production
VERDICT_LIMITE = "LIMITE"          # marche, mais moins que ses coûts / trop mince pour agir
VERDICTS = (VERDICT_REFUTE, VERDICT_CONFIRME, VERDICT_LIMITE)


@dataclass(frozen=True, slots=True)
class Loi:
    cle: str                        # identifiant court, stable
    titre: str
    verdict: str                    # REFUTE | CONFIRME | LIMITE
    chiffre: str                    # LE nombre qui tranche — jamais une impression
    date: str                       # AAAA-MM-JJ de la mesure
    condition_de_reouverture: str   # quelle DONNÉE nouvelle justifierait d'y revenir
    mots_cles: tuple[str, ...] = field(default_factory=tuple)
    ou_verifier: str = ""

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError("verdict inconnu: %r (attendu %s)" % (self.verdict, list(VERDICTS)))


LOIS: tuple[Loi, ...] = (
    Loi(cle="arb_dislocation_cout_all_in",
        titre="L'arbitrage de dislocation HL↔Binance paie après coûts",
        verdict=VERDICT_REFUTE,
        chiffre="le forfait `COUT_AR_BPS = 8` ne comptait que 2 exécutions sur 4 et oubliait "
                "les frais de la 2ᵉ venue. Coût all-in réel : 16,0 bps (13 de frais + 2 de "
                "spread + 1 d'adverse selection). Les 4 trades réels passent de +0,0929 $ "
                "à **−0,0671 $**. Convergence mesurée : le meilleur seau (10-20 bps, n=245) "
                "ne se referme que de **3,98 bps en 30 min** — contre 16 bps de coûts",
        date="2026-07-21",
        condition_de_reouverture="une MESURE du taux de fill passif sur les 4 exécutions : à "
                                 "9 bps (tout maker) les mêmes trades survivent (+0,0729 $). "
                                 "Sans cette mesure, l'hypothèse tout-maker est un espoir",
        mots_cles=("arbitrage", "dislocation", "cross-venue", "spread", "convergence", "binance"),
        ou_verifier="funding/arb_cout_all_in.py + backtesting/arb_backtest.py"),

    Loi(cle="arb_ecart_fige",
        titre="Un gros écart entre venues est une grosse opportunité",
        verdict=VERDICT_REFUTE,
        chiffre="MKR affichait 71,44 bps sur **208 observations avec un écart-type de 0,0000** "
                "(min = max). Le seau 40+ bps convergeait à **0 %** sur 176 observations, "
                "quand le seau 10-20 bps convergeait à 86 %. Le plus gros écart de l'univers "
                "était le seul à franchir le seuil — et le seul à ne jamais bouger",
        date="2026-07-21",
        condition_de_reouverture="aucune pour un écart figé : sigma nul = prix périmé, contrat "
                                 "différent ou mauvais appariement. Un écart CAPTURABLE fluctue",
        mots_cles=("arbitrage", "ecart fige", "prix mort", "adverse selection", "mapping"),
        ou_verifier="funding/arb_cout_all_in.ecart_vivant + arb_dislocation_paper.tick"),

    Loi(cle="carry_plancher_domine",
        titre="Un carry au plancher protocolaire vaut la peine d'être ouvert",
        verdict=VERDICT_REFUTE,
        chiffre="12/12 positions ouvertes et 580/580 lectures de scan au plancher "
                "(0,125 bps/h) → **APR net 2,65 %** contre **15-30 %** pour le vault HLP. "
                "Il faut **0,2660 bps/h, soit 2,13 × le plancher**, juste pour égaler la "
                "borne basse. 1 343,61 $ de marge dormaient sous l'alternative",
        date="2026-07-21",
        condition_de_reouverture="un funding durablement au-dessus de 0,266 bps/h — le journal "
                                 "de scans le dira. Positif ne suffit pas : il faut battre "
                                 "l'alternative disponible",
        # ⚠️ PAS de mot-clé « carry » nu : cette loi porte sur le PLANCHER, pas sur le carry en
        # général. L'y mettre déclenchait un avertissement décourageant sur toute idée
        # d'améliorer le carry — alors que l'améliorer est précisément ce qu'il faut faire
        # pour sortir du plancher. Une loi n'est pas un interdit de penser.
        mots_cles=("plancher", "hlp", "cout d'opportunite", "benchmark", "domine",
                   "carry au plancher"),
        ou_verifier="funding/carry_benchmark_gate.py (branché sur porte_risque_ouverture)"),

    Loi(cle="copy_global",
        titre="Suivre les wallets « smart money » en moyenne",
        verdict=VERDICT_REFUTE,
        chiffre="−7,97 bps sur 24 133 signaux hors échantillon, MÊME à coût zéro",
        date="2026-07-11",
        condition_de_reouverture="un sous-ensemble de leaders au markout forward POSITIF, "
                                 "prouvé sur ≥ 30 fills chacun (c'est ce que fait la whitelist)",
        mots_cles=("copy", "copytrading", "smart money", "leader", "suivre", "wallet"),
        ou_verifier="tools/ecrire_copy_whitelist.py + copy_wallet/leader_markout.py"),

    Loi(cle="copy_leader_contrarien",
        titre="La CAUSE du précédent : le leader moyen est contrarien",
        verdict=VERDICT_REFUTE,
        chiffre="le prix court CONTRE le leader de −7,75 bps AVANT même son fill",
        date="2026-07-14",
        condition_de_reouverture="mesurer un leader dont le markout AVANT fill est positif — "
                                 "sinon la vitesse ne sert à rien, le problème est le CONTENU",
        mots_cles=("contrarien", "markout", "avant fill", "latence copy", "mempool"),
        ou_verifier="docs/audit/ — Q1→Q3 edge mesuré"),

    Loi(cle="latence",
        titre="Être plus rapide améliorerait le copy",
        verdict=VERDICT_REFUTE,
        chiffre="sur les 24 133 signaux, la courbe edge/horizon est PLATE : raccourcir "
                "l'horizon ne fait pas remonter l'edge au-dessus de 0",
        date="2026-07-11",
        condition_de_reouverture="une courbe edge/horizon en PENTE sur des données neuves",
        mots_cles=("latence", "vitesse", "rapide", "horizon", "mempool", "colocation"),
        ou_verifier="mémoire projet : courbe edge/horizon"),

    Loi(cle="market_making_spread",
        titre="Faire le marché à l'intérieur du spread (T1/T1b)",
        verdict=VERDICT_REFUTE,
        chiffre="0 gagnant sur 29 coins, mesuré à 100 % de fill (borne HAUTE, impossible en vrai) ; "
                "le prix bouge 5 à 30× le spread",
        date="2026-07-13",
        condition_de_reouverture="un marché où le prix bouge MOINS que le spread — "
                                 "aucun de nos 29 coins n'était dans ce cas",
        mots_cles=("market making", "mm", "spread", "inside spread", "grid", "carnet"),
        ou_verifier="mémoire projet : T1b fermé, 0/29"),

    Loi(cle="spread_prix_du_risque",
        titre="Le spread est un revenu à capter",
        verdict=VERDICT_REFUTE,
        chiffre="corollaire du 0/29 de T1b : le spread n'est jamais un cadeau, c'est le PRIX "
                "du risque d'inventaire — le prix bouge 5 à 30× le spread encaissé",
        date="2026-07-13",
        condition_de_reouverture="un modèle qui montre l'inventaire couvert à coût nul",
        mots_cles=("spread", "revenu", "capter", "maker rebate"),
        ou_verifier="mémoire projet : T1b"),

    Loi(cle="funding_perp_perp",
        titre="Arbitrer le funding entre deux perps (X-04)",
        verdict=VERDICT_REFUTE,
        chiffre="0 opportunité nette sur 120 mesurées",
        date="2026-07-13",
        condition_de_reouverture="deux perps du MÊME actif (une couverture ne vaut que si "
                                 "c'est le même sous-jacent — loi `couverture_meme_actif`)",
        mots_cles=("perp perp", "funding spread", "x-04", "inter-perp"),
        ou_verifier="funding/funding_spread_perp_perp.py"),

    Loi(cle="couverture_meme_actif",
        titre="Couvrir un actif par un actif corrélé",
        verdict=VERDICT_REFUTE,
        chiffre="corollaire du 0/120 de X-04 : une couverture ne vaut QUE si c'est le même "
                "actif — sinon la base résiduelle dépasse l'edge visé",
        date="2026-07-13",
        condition_de_reouverture="jamais sur corrélation seule ; seulement sur identité d'actif",
        mots_cles=("couverture", "hedge", "correle", "proxy", "beta"),
        ou_verifier="X-04 / #242"),

    Loi(cle="lead_lag",
        titre="BTC mène, les alts suivent (tradeable)",
        verdict=VERDICT_REFUTE,
        chiffre="0 sur 66 paires ; BNB : corrélation instantanée +0,83 vs corrélation à 2 h −0,03. "
                "Les alts bougent AVEC BTC, ils ne le SUIVENT pas",
        date="2026-07-14",
        condition_de_reouverture="une corrélation DÉCALÉE significative, mesurée hors échantillon",
        mots_cles=("lead lag", "lead-lag", "btc mene", "alt suit", "cascade"),
        ou_verifier="mémoire projet : #549"),

    Loi(cle="rendement_negatif_domine",
        titre="Une stratégie à rendement négatif peut être sauvée par le sizing",
        verdict=VERDICT_REFUTE,
        chiffre="arithmétique : −1 bps × n'importe quelle taille reste sous les 0 bps du "
                "cash — le sizing multiplie, il ne change pas le signe",
        date="2026-07-13",
        condition_de_reouverture="aucune — c'est de l'arithmétique",
        mots_cles=("sizing", "levier", "kelly", "multiplier", "rendement negatif"),
        ou_verifier="mémoire projet : benchmark CASH"),

    Loi(cle="hlp_benchmark",
        titre="Le vault HLP comme référence à battre",
        verdict=VERDICT_REFUTE,
        chiffre="🔴 CORRIGÉ le 21/07 : notre mesure interne disait −0,01 % APR — elle portait "
                "sur une fenêtre trop courte. La donnée PUBLIQUE 2026 dit **15 à 30 % APR** "
                "sur la plupart des fenêtres trimestrielles (drawdowns 5-12 %). Notre carry "
                "vaut ~12,9 %/an : **un dépôt passif dans HLP nous bat**. La stratégie est "
                "DOMINÉE par une alternative sans code, sans surveillance et sans risque "
                "d'exécution",
        date="2026-07-21",
        condition_de_reouverture="que le carry dépasse durablement 30 % APR net, OU que HLP "
                                 "s'effondre. Attention : HLP n'est PAS delta-neutre (il porte "
                                 "du risque directionnel et de liquidation) — la comparaison "
                                 "est brutale mais pas parfaitement égale à risque",
        mots_cles=("hlp", "vault", "benchmark", "depot passif", "rendement passif"),
        ou_verifier="defillama.com/protocol/hyperliquid-hlp (public) + carry_backtest"),

    Loi(cle="carry_delta_neutre",
        titre="Carry delta-neutre (long spot + short perp) sur Hyperliquid",
        verdict=VERDICT_CONFIRME,
        chiffre="le SEUL chiffre positif du projet : ~2 % APR mesuré sur HYPE (13/07) ; "
                "+0,35 $/j sur 11 positions au 21/07, coûts payés",
        date="2026-07-13",
        condition_de_reouverture="—  c'est la stratégie en production ; à re-mesurer si le "
                                 "funding quitte le plancher protocolaire",
        mots_cles=("carry", "delta neutre", "funding", "basis", "spot perp"),
        ou_verifier="funding/delta_neutral_carry.py + backtesting/carry_backtest.py"),

    Loi(cle="arbitrage_cross_venue",
        titre="Arbitrer une dislocation de prix Hyperliquid ↔ Binance",
        verdict=VERDICT_LIMITE,
        chiffre="l'écart CONVERGE (−2,26 bps à 30 min, 64,9 % des cas) mais MOINS que les "
                "8 bps d'aller-retour : edge net négatif en moyenne. Seuls les écarts extrêmes "
                "paient — à 8 bps d'ouverture : 19 entrées, capture moyenne 8,53 bps",
        date="2026-07-21",
        condition_de_reouverture="la même mesure sur ≥ 5 000 écarts (la cadence est passée à "
                                 "60 s le 21/07 pour ça) — si la capture tient au-dessus de "
                                 "8 bps, le seuil descend de 15 à ~8",
        mots_cles=("arbitrage", "dislocation", "cross venue", "binance", "ecart de prix"),
        ou_verifier="backtesting/arb_backtest.py + runtime/replay/BACKTEST_ARBITRAGE.md"),

    Loi(cle="zscore_au_plancher",
        titre="Le z-score du funding comme signal de taille",
        verdict=VERDICT_REFUTE,
        chiffre="corrélation −0,596 entre le facteur de taille et le rendement net : on "
                "finançait le PLUS les coins les MOINS rentables. Au plancher protocolaire, "
                "tous les coins sont au même taux par construction — le z-score y mesure du bruit",
        date="2026-07-21",
        condition_de_reouverture="un funding franchement AU-DESSUS du plancher (le garde du "
                                 "plancher réactive alors le z-score automatiquement)",
        mots_cles=("z-score", "zscore", "facteur taille", "sizing funding", "spike funding"),
        ou_verifier="funding/carry_optimizer.py:facteur_zscore + carry_allocation_nette.py"),
)

_PAR_CLE = {l.cle: l for l in LOIS}


def loi(cle: str) -> Loi | None:
    return _PAR_CLE.get(str(cle))


def par_verdict(verdict: str) -> tuple[Loi, ...]:
    return tuple(l for l in LOIS if l.verdict == verdict)


def chercher(texte: str) -> tuple[Loi, ...]:
    """Les lois qui concernent `texte` (idée, titre de piste, nom de module).

    Sert au moment le plus utile : quand une idée est PROPOSÉE. Retourne les lois par
    verdict le plus contraignant d'abord — on veut voir « déjà réfuté » avant « confirmé ».
    """
    t = " " + str(texte or "").lower() + " "
    touchees = [l for l in LOIS if any(m in t for m in l.mots_cles)]
    ordre = {VERDICT_REFUTE: 0, VERDICT_LIMITE: 1, VERDICT_CONFIRME: 2}
    return tuple(sorted(touchees, key=lambda l: (ordre[l.verdict], l.date)))


def avertissement(texte: str) -> str | None:
    """Une phrase à afficher quand une idée retombe sur une loi déjà mesurée. None sinon.
    Ce n'est PAS un interdit : c'est le chiffre à battre, et la donnée qui rouvrirait le dossier."""
    touchees = [l for l in chercher(texte) if l.verdict != VERDICT_CONFIRME]
    if not touchees:
        return None
    l = touchees[0]
    return ("déjà mesuré le %s — %s : %s. Pour rouvrir : %s (voir %s)"
            % (l.date, l.titre, l.chiffre, l.condition_de_reouverture, l.ou_verifier or "le dépôt"))


def markdown() -> str:
    """Le registre en Markdown — SOURCE UNIQUE. `docs/LOIS_MESUREES.md` est généré d'ici :
    une loi recopiée à la main finirait par diverger de celle qui est testée."""
    icones = {VERDICT_REFUTE: "🔴", VERDICT_LIMITE: "🟠", VERDICT_CONFIRME: "🟢"}
    l = ["# Les lois mesurées — ce que NOS chiffres ont déjà tranché", "",
         "> Généré depuis `src/hl_observer/research/lois_mesurees.py` (source unique).",
         "> Une loi n'est pas un interdit de penser : c'est un **chiffre à battre**, avec la",
         "> **donnée** qui justifierait de rouvrir le dossier. Un argument neuf ne suffit pas.", ""]
    for v, titre in ((VERDICT_REFUTE, "Réfuté par la mesure"),
                     (VERDICT_LIMITE, "Réel mais insuffisant en l'état"),
                     (VERDICT_CONFIRME, "Confirmé — en production")):
        lois = par_verdict(v)
        if not lois:
            continue
        l += ["## %s %s (%d)" % (icones[v], titre, len(lois)), ""]
        for x in lois:
            l += ["### %s — `%s`" % (x.titre, x.cle), "",
                  "- **le chiffre** : %s" % x.chiffre,
                  "- **mesuré le** : %s" % x.date,
                  "- **pour rouvrir** : %s" % x.condition_de_reouverture,
                  "- **où vérifier** : `%s`" % (x.ou_verifier or "—"), ""]
    l += ["---", "",
          "**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · "
          "0 dépôt/retrait.**", ""]
    return "\n".join(l)


__all__ = ["Loi", "LOIS", "VERDICTS", "VERDICT_REFUTE", "VERDICT_CONFIRME", "VERDICT_LIMITE",
           "loi", "par_verdict", "chercher", "avertissement", "markdown"]
