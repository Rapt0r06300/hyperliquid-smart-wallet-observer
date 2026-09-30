"""TRIAGE des tâches #451-#494 (H-46 -> H-89) par le REGISTRE DES ZONES MORTES.

Règle de Flo (2026-07-13) : *une zone morte ne peut refuser une idée que si cette idée consomme
**LA MÊME ENTRÉE** que la mesure qui l'a tuée.* Chaque tâche déclare donc son entrée.

Et un second couperet, arithmétique celui-là :

    ⚖️ **L'ARGUMENT DE DOMINATION.**
    T1b a mesuré le market making à **100 % de remplissage** -- la borne la PLUS GÉNÉREUSE
    possible. Verdict : 0/29 coins viables. Tout meilleur modèle de file / de fill
    (ProbQueueModel, L3FIFO, hftbacktest, position dans la file par ordre...) ne peut
    qu'ABAISSER le taux de remplissage. **Il ne peut donc qu'aggraver un verdict déjà négatif.**
    Ce n'est pas un préjugé : c'est de l'arithmétique.

Aucun ordre réel. Lecture seule.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.agent.dead_zones_hypersmart import registre_officiel  # noqa: E402

DOMINE = "DOMINE_PAR_T1b_MESURE_A_100_POURCENT_DE_FILL"

# (id, titre court, entrée consommée, verdict proposé, raison)
TACHES: list[tuple[str, str, str, str, str]] = [
    # ── 🚨 SÉCURITÉ — refus absolu, sans discussion ──────────────────────────────────────────
    ("#456/H-51", "mackinac/dex-exec (HL perp + Uniswap V3)", "execution_reelle", "REFUS_SECURITE",
     "🚨 CE REPO EXECUTE DE VRAIS ORDRES. Ne JAMAIS l'installer, l'importer, le cloner. "
     "La seule ligne dure du projet. Deja acte en #539."),

    # ── ⚖️ DOMINÉS PAR T1b (100 % de fill = borne haute) ─────────────────────────────────────
    ("#452/H-47", "hyperliquid-data-pipeline : file PAR ORDRE", "modele_de_file", DOMINE,
     "Un meilleur modele de file ne peut que BAISSER le fill. T1b a mesure a 100 %. "
     "⚠️ MAIS le repo est aussi une SOURCE DE DONNEES L3 -> voir la section DONNEES."),
    ("#487/H-82", "ProbQueueModel + 4 fonctions", "modele_de_file", DOMINE, ""),
    ("#490/H-85", "anti-double-comptage de la file", "modele_de_file", DOMINE,
     "Notre file n'est plus dans le chemin d'un edge : il n'y a plus d'edge de MM a proteger."),
    ("#493/H-88", "aveu de hftbacktest : perte d'info de file", "modele_de_file", DOMINE, ""),
    ("#494/H-89", "L3FIFOQueueModel exact + 2 tests", "modele_de_file", DOMINE, ""),
    ("#488/H-83", "hftbacktest CONTREDIT notre pessimisme", "modele_de_file", DOMINE,
     "🎯 L'argument le plus interessant du lot -- et il tombe quand meme. hftbacktest dit qu'on "
     "est TROP pessimiste sur le fill. Or T1b a mesure a **100 %** : on ne peut pas etre plus "
     "optimiste. Etre 'moins pessimiste' ne peut RIEN ajouter."),
    ("#454/H-49", "hip4-mm-simulator", "market_making", DOMINE, ""),
    ("#469/H-64", "atomic-mesh / MicroExchange / submicro", "market_making", DOMINE, ""),
    ("#491/H-86", "hftbacktest : 4 sources d'alpha MM", "market_making", DOMINE, ""),
    ("#473/H-68", "ctc-executioner : ou placer l'ordre limite", "market_making", DOMINE,
     "Placer l'ordre AILLEURS ne cree pas un edge : T1b a mesure DANS le spread, 0/29."),
    ("#474/H-69", "SGX full order book tick HFT", "market_making", DOMINE,
     "+ on n'a AUCUN historique de carnet L3."),
    ("#489/H-84", "GLFT : unifie MM et GRID trading", "market_making", DOMINE,
     "Et il unifie deux choses MORTES : le MM (T1b) et le grinder (P8)."),
    ("#484/H-79", "le 'grinder mode' de Flo EST du grid trading", "market_making", DOMINE,
     "🔴 Confirme l'autopsie : le grinder est mort avec T1b."),
    ("#458/H-53", "cross-venue-arbitrage + XEMM", "market_making", DOMINE,
     "XEMM = market making cross-exchange. MM mort + **on ne peut pas trader Binance**."),
    ("#492/H-87", "latence de flux vs latence d'ordre", "latence", "REFUS",
     "🔴 La courbe edge/horizon est PLATE : a 500 ms l'edge est -3,74 bps, a 8 h il est -3,7. "
     "**La latence n'a JAMAIS ete le probleme.** Modeliser une 2e latence ne change pas un "
     "edge qui est negatif AVANT toute latence."),
    ("#466/H-61", "Statistical-Arbitrage haute frequence", "prix_bougies", "REFUS",
     "#242 (cointegration) REFUTE sur 208 JOURS : 14/66 cointegrees, 0 viable. Le beta du "
     "train ne tient pas sur le test. **Meme entree (prix), meme mur.**"),
    ("#467/H-62", "stochastic-rs : Hawkes, Ornstein-Uhlenbeck", "prix_bougies", "REFUS_PARTIEL",
     "Ornstein-Uhlenbeck = retour a la moyenne = #242, REFUTE sur 208 j. "
     "⚠️ Hawkes (clustering du flux d'ordres) consomme les TRADES, pas les prix -> A_EXAMINER."),
    ("#477/H-72", "Momentum Transformer / TradeMaster / lob-deep-learning", "prix_bougies", "REFUS",
     "🚩 M-19 : on a deja cherche dans **150 MILLIONS** de scenarios SANS correction de "
     "multiplicite. Du ML sur LOB, c'est la meme machine a p-hacking, en plus opaque. "
     "Et on n'a AUCUN historique de LOB."),
    ("#472/H-67", "alpha mining automatique = machine a p-hacking", "meta", "CONFIRME",
     "✅ **C'est exactement ce qu'on a fait** (150 M de scenarios, garde-fous anti-overfit MORTS). "
     "Cette tache n'est pas une piste : c'est un DIAGNOSTIC, et il est juste. Deja corrige (M-19)."),
    ("#475/H-70", "verdict copy-trading HL : la niche est du spam SEO", "meta", "CONFIRME",
     "✅ Corrobore notre PROPRE mesure : 24 133 signaux OOS, -7,97 bps **meme a cout ZERO**. "
     "Personne n'a de preuve parce qu'il n'y a rien a prouver."),

    # ── 🔴 DONNÉES : la seule chose qui peut REOUVRIR quelque chose ──────────────────────────
    ("#462/H-57", "0xArchive : 5 repos de donnees HL GRANULAIRES", "donnees_historiques", "PRIORITE_1",
     "🔴🔴 **J'AI AFFIRME SANS VERIFIER que le carnet L2 et les trades n'ont aucune source "
     "historique gratuite.** C'est exactement l'erreur que j'ai faite avec candleSnapshot "
     "(« data-limited » etait AUTO-INFLIGE). **A VERIFIER, pas a croire.**"),
    ("#452b/H-47", "hyperliquid-data-pipeline COMME SOURCE (pas comme file)", "donnees_historiques",
     "PRIORITE_1", "Meme raison : si ce pipeline expose des donnees L3 historiques, il debloque "
     "la selection adverse et le PIN/VPIN -- pas le MM (domine)."),
    ("#485/H-80", "ohlcv-validator", "donnees_historiques", "A_EXAMINER",
     "On vient de backfiller 208 j de bougies + du funding. Un VALIDATEUR de ces donnees est "
     "de l'ingenierie utile : nos mesures valent ce que valent nos entrees."),
    ("#463/H-58", "PIN / VPIN : probabilite de flux INFORME", "trades_avec_agresseur", "A_EXAMINER",
     "🎯 Entree DIFFERENTE (trades avec cote agresseur). Q1->Q3 a montre que le leader est "
     "CONTRARIEN. Le VPIN mesure la TOXICITE du flux -- c'est un angle qu'on n'a pas mesure. "
     "⚠️ Mais il ne peut pas ressusciter un signal qui n'a AUCUNE information (-7,97 bps)."),
    ("#455/H-50", "zer0cache : le MARKOUT", "trades_avec_agresseur", "DEJA_FAIT",
     "✅ On a construit le markout dans T1b ET dans Q1->Q3. C'est lui qui a revele que le "
     "leader est contrarien (-7,75 bps AVANT le fill). **Deja notre metrique centrale.**"),

    # ── 📋 META : corrections de MA propre moisson (pas des pistes) ──────────────────────────
    ("#451/H-46", "le bug qui a jete hftbacktest (235 README perdus)", "meta", "ACTE"),
    ("#453/H-48", "les etoiles ne mesurent pas la credibilite", "meta", "ACTE"),
    ("#459/H-54", "297 repos HL : le gisement etait sous 20 etoiles", "meta", "ACTE"),
    ("#460/H-55", "verdict sur les 1 326 repos a zero concept", "meta", "ACTE"),
    ("#461/H-56", "nouvelle hierarchie (remplace H-40)", "meta", "ACTE"),
    ("#468/H-63", "limite du score : 200 car. autour d'un mot-cle", "meta", "ACTE"),
    ("#480/H-75", "bug de tri : CC0 est le DOMAINE PUBLIC", "meta", "ACTE"),
    ("#481/H-76", "2 repos sur 5 617 testent serieusement", "meta", "ACTE"),
    ("#478/H-73", "2 repos sur 5 617 parlent de gap recovery", "meta", "ACTE"),
    ("#464/H-59", "tfrmma : 4 repos dont une MM suite pour HL", "market_making", DOMINE),
    ("#465/H-60", "IMC Prosperity + Optiver : les seuls post-mortems honnetes", "meta", "A_EXAMINER"),
    ("#470/H-65", "chirindaopensource : implementations de PAPIERS", "meta", "A_EXAMINER"),
    ("#476/H-71", "OpenSourceRisk/Engine + tfrmma/oms", "ingenierie", "REFUS",
     "On a **25 garde-fous de risque**, dont **23 ENTERRES faute d'appelant** (T3b). "
     "Le probleme n'a JAMAIS ete le manque de moteur de risque."),
    ("#482/H-77", "gitbitex : un vrai exchange open-source", "ingenierie", "REFUS",
     "Un carnet de reference ne cree pas d'edge. Et notre simulateur d'execution existe."),
    ("#483/H-78", "Financial-Models-Numerical-Methods", "meta", "A_EXAMINER"),
    ("#457/H-52", "freqtrade-ultimate : fork freqtrade POUR HL", "ingenierie", "REFUS",
     "Une 3e architecture. Regle du projet : *ne pas introduire de 3e architecture*."),
    ("#471/H-66", "CE QUE LA MOISSON N'A PAS TROUVE", "meta", "CONFIRME",
     "🎯 **Le resultat le plus important de la moisson** : 5 617 repos, et pas UN seul ne "
     "montre un edge de copy-trading prouve. L'absence est la preuve."),
    ("#479/H-74", "plan de bataille post-moisson + critere d'arret", "meta", "A_EXAMINER"),
    ("#486/H-81", "rendement decroissant : la moisson est epuisee", "meta", "CONFIRME",
     "✅ **NE PAS RE-MOISSONNER.** Deja en memoire."),
]


def main() -> int:
    reg = registre_officiel()
    print("=" * 96)
    print("  TRIAGE #451-#494 (H-46 -> H-89) -- 44 taches")
    print("  Regle : une zone morte ne refuse que si l'idee consomme LA MEME ENTREE.")
    print("  + ARGUMENT DE DOMINATION : T1b a mesure le MM a **100 %% de fill** (borne haute).")
    print("=" * 96)

    par_verdict: dict[str, list[str]] = {}
    for t in TACHES:
        tid, titre, entree, verdict = t[0], t[1], t[2], t[3]
        raison = t[4] if len(t) > 4 else ""
        par_verdict.setdefault(verdict, []).append(tid)
        ex = reg.examiner(titre, entree=entree)
        marque = {"REFUS": "🛑", "LIBRE": "  ", "A_EXAMINER": "❓"}.get(ex.statut, "  ")
        print("\n  %-12s %s" % (tid, titre))
        print("    entree=%-22s registre=%s %s" % (entree, marque, ex.statut))
        print("    VERDICT : %s" % verdict)
        if raison:
            for ligne in raison.split(". "):
                if ligne.strip():
                    print("        %s" % ligne.strip())

    print("\n" + "=" * 96)
    print("  RECAPITULATIF")
    print("=" * 96)
    for v in sorted(par_verdict, key=lambda k: -len(par_verdict[k])):
        print("  %-38s %2d  %s" % (v, len(par_verdict[v]), " ".join(par_verdict[v])[:44]))
    print("\n  -> 1 seule chose peut REOUVRIR quelque chose : **les DONNEES** (#462, #452b).")
    print("     Et c'est precisement la ou j'ai AFFIRME SANS VERIFIER.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
