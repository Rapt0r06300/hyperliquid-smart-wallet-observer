"""TRIAGE des tâches #495-#585 (H-90 -> H-180) — 91 tâches, une par une.

Trois couperets, dans cet ordre :

  1. 🚨 **SECURITE** — `dex-exec` execute de vrais ordres. Refus absolu.
  2. ⚖️ **DOMINATION** — T1b a mesure le MM a **100 % de remplissage** (borne haute) : 0/29.
     Tout meilleur modele de file/fill ne peut qu'ABAISSER le fill. **Arithmetique, pas prejuge.**
  3. 🔑 **ENTREE MESUREE** — une zone morte ne refuse que si l'idee consomme LA MEME ENTREE.

Et **une reouverture honoree** : ma zone morte MODELE_DE_FILE prevoit sa reouverture *« si une
mesure montre que le risque d'inventaire est INFERIEUR au spread capture sur au moins un
marche »*. **#517 l'affirme pour les marches HIP-3. Je dois donc MESURER, pas refuser.**

Aucun ordre reel.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

DOM = "DOMINE_T1b_100PCT_FILL"
FAIT = "FAIT_AUJOURDHUI"
BUG = "BUG_REEL_TROUVE"
EXAM = "A_EXAMINER"
REF = "REFUS"
SEC = "REFUS_SECURITE"
CONF = "CONFIRME_NOTRE_MESURE"
META = "ACTE"

# (id, titre, verdict, note)
T: list[tuple[str, str, str, str]] = [
    # ═══ 🚨 SECURITE ═══
    ("#539/H-134", "dex-exec EXECUTE DE VRAIS ORDRES", SEC,
     "Ne JAMAIS importer, installer, cloner. Aucune exception. Deja acte."),

    # ═══ 🔴 LES VRAIS BUGS — DANS NOTRE CODE. C'est LA l'or. ═══
    ("#543/H-138", "nos frais maker sont-ils VRAIMENT 1,5 bps ?", FAIT,
     "🎯 **LA MEILLEURE TACHE DU LOT.** Reponse : 1,5 bps est JUSTE (perp tier 0, doc officielle). "
     "MAIS le code utilisait **6 valeurs eparpillees** (2.5 / 4.0 / 4.5 / 6.0), dont un **2,5 bps "
     "qui ne figure NULLE PART** dans la grille HL. -> `fees/hyperliquid_fees.py` = source unique, "
     "+ cliquet anti-regression."),
    ("#543b", "🔴 LE SPOT NE COUTE PAS LE PRIX DU PERP", BUG,
     "**Trouve en ecrivant la grille.** Spot maker = **4,0 bps** (perp : 1,5). Spot taker = **7,0** "
     "(perp : 4,5). Or **T2b -- le SEUL resultat positif du projet -- a une jambe SPOT** et etait "
     "chiffre aux frais perp. Aller-retour : **18 -> 23 bps** (taker), **6 -> 11 bps** (maker). "
     "**Le carry HYPE etait sous-estime de 5 bps.** Corrige. Il survit, il maigrit encore."),
    ("#519/H-114", "le BUILDER FEE, un cout HL non modelise", REF,
     "Verifie sur la doc : le builder fee n'existe QUE si on trade via un frontend « builder ». "
     "**On n'en utilise aucun.** Ce n'est PAS un cout manquant. Refute par la doc."),
    ("#540/H-135", "`alo` = ADD LIQUIDITY ONLY (post-only)", DOM,
     "Le post-only sert a garantir d'etre MAKER. **Etre maker = etre dans le carnet = MM.** T1b."),
    ("#514/H-109", "Decimal vs float : arrondis dans le ledger ?", EXAM,
     "Vraie question sur NOTRE code. A mesurer : reconcilier le ledger en Decimal vs float sur "
     "l'historique et comparer. Cheap."),
    ("#563/H-158", "GREP `.mean()`/`.std()` SANS `rolling()` = LOOKAHEAD", BUG,
     "🎯 **La generalisation de GARCH-lit-le-futur.** MAIS : **grep, non -- AST.** Un grep lit les "
     "docstrings (lecon G2). A construire : detecteur AST des agregats non fenetres."),
    ("#562/H-157", "methode ANTI-LOOKAHEAD : test DIFFERENTIEL", CONF,
     "✅ **Deja fait pour GARCH** : on tronque l'entree et on verifie que la sortie passee ne bouge "
     "pas. *Un test qui ne lit pas le code ne peut pas etre trompe par un commentaire.* A generaliser."),
    ("#583/H-178", "`position_stacking` : le backtest empile-t-il ?", EXAM,
     "Vraie divergence backtest/live possible. A verifier sur notre moteur."),
    ("#571/H-166", "on ne compare JAMAIS notre PnL au BUY-AND-HOLD", BUG,
     "🎯 **Vrai, et accablant.** Une strategie a -7,97 bps face a « ne rien faire » : le "
     "buy-and-hold est le benchmark honnete qu'on n'a jamais affiche."),
    ("#572/H-167", "le probleme INTRA-BOUGIE explique nos stops qui derapent", BUG,
     "🔴 **Et il vient de grossir** : on a maintenant 208 j de bougies **1 h**. Un stop DANS une "
     "bougie d'une heure est **indeterminable** (high avant low ? on ne sait pas). Toute mesure de "
     "SL/TP sur bougies 1h est SUSPECTE."),
    ("#567/H-162", "drawdown sur les RATIOS ou sur l'EQUITY ?", EXAM),
    ("#573/H-168", "deux drawdowns, deux Sharpe (trades clotures vs wallet)", EXAM),
    ("#574/H-169", "les 12 metriques du rapport qu'on n'a pas, dont l'ESPERANCE", EXAM),
    ("#575/H-170", "tableau EXIT REASON : quelle SORTIE nous tue ?", CONF,
     "✅ Deja fait : l'autopsie du -64 $ a montre que **30 % = structure de sortie** (breakeven 87 %)."),
    ("#576/H-171", "contraintes exchange : notionnel min, precision prix/taille", BUG,
     "🔴 **Reel.** On size a 500 $ de notionnel. Si le tick/lot et le notionnel minimum ne sont pas "
     "modelises, notre PnL est faux **par construction**. Recuperable via `meta`."),
    ("#578/H-173", "combien des 150 M a-t-on VRAIMENT evalue ?", BUG,
     "🔴 **CRITIQUE.** M-19 deflate le Sharpe par `n_essais=evaluated`. **Si `evaluated` != 150 M, "
     "la correction anti-overfit est FAUSSE** -- dans un sens ou dans l'autre. A verifier."),
    ("#569/H-164", "8 « completed » probablement FAUX", CONF,
     "✅ **La maladie du projet, nommee.** Deja 16 deguisements documentes. L'invariant de cablage "
     "(T3b) et le cliquet sont la reponse structurelle."),
    ("#508/H-103", "l'horloge : corriger le decalage local par SNTP", CONF,
     "✅ **Deja corrige, en pire** : `signal_age` etait une TAUTOLOGIE (le « maintenant » venait des "
     "donnees -> age 0 par construction, et GELE quand le flux calait). Voir `freshness/horloges.py`."),
    ("#496/H-91", "le REJET D'ORDRE par l'exchange : non modelise", EXAM,
     "Realisme paper. Mais un rejet ne cree pas d'edge : il en DETRUIT. Priorite basse."),
    ("#498/H-93", "le flag `order.maker` : le frais depend de COMMENT ca s'execute", BUG,
     "🔴 **Lie a #543.** Si on suppose maker sur une execution qui aurait ete taker, on se trompe "
     "d'un **facteur 3** (4,5 vs 1,5). La grille est maintenant unique ; reste a verifier QUI est "
     "maker dans chaque simulation."),
    ("#505/H-100", "« l'archive S3 est PAYANTE, et sans les trades »", BUG,
     "🔴 **MA PROPRE AFFIRMATION, ET ELLE EST A MOITIE FAUSSE.** Payante : VRAI (requester-pays). "
     "**« Sans les trades » : FAUX** -- `s3://hl-mainnet-node-data/node_trades` et "
     "`node_fills_by_block` existent. **Corrige aujourd'hui.** Flo : rien de payant -> on n'y va pas."),
    ("#509/H-104", "3e bug de triage : un repo MIT classe INTOUCHABLE", META),
    ("#510/H-105", "`VERIFY-ON-REAL-DATA` : marquer ses hypotheses NON VERIFIEES", CONF,
     "✅ **C'est exactement ce que je fais** : `NON_MESURE`, `INSUFFICIENT_DATA`, `None` plutot "
     "qu'un chiffre invente. A systematiser."),
    ("#512/H-107", "ce repo DEMOLIT notre bascule vers le testnet", EXAM,
     "A lire : la liquidite testnet diverge du mainnet. Deja dit dans CLAUDE.md, jamais mesure."),

    # ═══ ⚖️ LE CLUSTER MARKET MAKING — DOMINE ═══
    ("#495/H-90", "lire les 6 modules restants de hftbacktest", DOM),
    ("#497/H-92", "le TRIPLET de latence (req/exch/resp)", REF,
     "Zone morte LATENCE : courbe edge/horizon **PLATE** (-3,74 bps a 500 ms). "
     "**La latence n'a jamais ete le probleme.**"),
    ("#499/H-94", "5 hypotheses optimistes en 3 fichiers", DOM),
    ("#500/H-95", "les 3 bornes d'annulation", DOM),
    ("#501/H-96", "le RAW SPOOL : ecrire la trame brute avant de parser", EXAM,
     "❗ Ingenierie SAINE, independante du MM : si on parse mal, on perd la donnee pour toujours. "
     "**Et c'est GRATUIT.** A retenir pour la collecte forward (seul chemin gratuit L2/trades)."),
    ("#502/H-97", "un consommateur lent ne doit jamais bloquer la socket", EXAM,
     "❗ Idem : c'est peut-etre la cause des **stalls a 02:32 et 04:08**. Vraie piste d'ingenierie."),
    ("#503/H-98", "decomposition du PnL maker en 5 termes", DOM),
    ("#506/H-101", "la position dans la file est accessible (node/gRPC)", DOM,
     "Meme si elle l'est : T1b a mesure a **100 %** de fill. Connaitre sa place ne peut qu'ABAISSER."),
    ("#511/H-106", "modele de fill a 3 regles, calculable avec nos trades", DOM),
    ("#513/H-108", "hip4-mm dit « simulee », sa roadmap dit le contraire", META,
     "✅ X-06 applique : verifier les AFFIRMATIONS d'un repo avant son code. Bien vu."),
    ("#516/H-111", "toxicite PAR COTE (bid != ask)", EXAM,
     "Entree differente (trades avec agresseur). Lie a VPIN (#463/#521)."),
    ("#517/H-112", "le MM SURVIT sur HIP-3 : 20 bps de DEMI-spread", EXAM,
     "🔑 **LA REOUVERTURE. Je l'honore.** Ma zone morte prevoit explicitement : *« si une mesure "
     "montre que le risque d'inventaire est INFERIEUR au spread capture sur au moins un marche »*. "
     "#517 l'AFFIRME pour HIP-3. **Et le growth mode HIP-3 divise les frais par 10** (0,15 bps "
     "maker !). ⚠️ MAIS : T1b est mort sur la porte C (inventaire), pas la porte B (couts). "
     "Diviser les frais par 10 ne touche PAS la porte C. **A MESURER avec l'outil T1b sur les "
     "marches HIP-3. Pas a supposer.**"),
    ("#518/H-113", "controleur d'inventaire a demi-vie", DOM),
    ("#520/H-115", "les 6 garde-fous de cotation qu'on n'a pas", DOM,
     "+ on a deja **25 garde-fous de risque, dont 23 ENTERRES faute d'appelant** (T3b)."),
    ("#523/H-118", "optimiseur a rollback contrefactuel + superviseur", DOM),
    ("#524/H-119", "LADDER + VWAP-ancrage + WALL-FRONTING", DOM),
    ("#525/H-120", "le BUDGET D'API alloue par ROI", EXAM,
     "❗ Ingenierie utile et gratuite : on a des rate limits, on ne les alloue pas."),
    ("#527/H-122", "sur HL (L2 seul), la file s'estime PROBABILISTIQUEMENT", DOM,
     "✅ Et c'est justement pour ca que T1b a mesure a **100 %** : la borne haute rend le "
     "probabilisme inutile. On a deja la reponse la plus favorable."),
    ("#528/H-123", "detection d'ICEBERG par regarnissage", DOM),
    ("#529/H-124", "les 4 mesures canoniques de la selection adverse", CONF,
     "✅ On a le markout (T1b, Q1->Q3) -- **sur le MID**, apres avoir corrige le bid-ask bounce."),
    ("#530/H-125", "front-run deterministic liq engines", EXAM,
     "🔴 Entree DIFFERENTE : les liquidations. **`liquidationPx` est branche** (X-11). Le flux force "
     "est NON informe -> markout positif attendu. **La piste la plus prometteuse qui reste.**"),
    ("#531/H-126", "PRE-PRINT FUNDING CAPTURE", FAIT,
     "🎯 **MECANISME REEL, confirme par la doc** : *« the funding payment AT THE END of the "
     "interval »* -> qui detient a l'instant du prelevement encaisse **l'heure ENTIERE**, non "
     "proratisee. **MAIS** : aller-retour taker = **9,0 bps** contre un funding median de **0,125 "
     "bps/h** -> il faut **72x la mediane**. Module `funding/snapshot_capture.py` + seuil HONNETE "
     "qui inclut le **bruit de prix** (le terme oublie de T1b). **A mesurer sur 120 j.**"),
    ("#532/H-127", "le risk manager en 4 couches", DOM),
    ("#533/H-128", "contre-spoofing : FADE l'illusion", DOM),
    ("#534/H-129", "latence log-normale", REF, "Zone morte LATENCE."),
    ("#535/H-130", "les DEUX echelles de markout (500ms-5s vs 5s-300s)", CONF,
     "✅ La courbe edge/horizon couvre deja 500 ms -> 8 h. **Elle est PLATE.**"),
    ("#536/H-131", "STOP CASCADES : join or fade + RL qui regle A-S", DOM),
    ("#545/H-140", "lazychartguy/hl-market-maker : frais de builder", DOM),
    ("#549/H-144", "LEAD-LAG BTC->ALTS : la niche VIDE", EXAM,
     "🔑 **Entree : nos 208 j de bougies.** Niche vide sur 5 617 repos. **A MESURER** -- c'est "
     "cheap, on a la donnee, et l'anti-overfit est maintenant branche."),
    ("#550/H-145", "nkaz001/algotrading-example", DOM),
    ("#552/H-147", "alpacahq/example-hftish : order book imbalance", DOM),
    ("#554/H-149", "phonegapX/alphahunter : systeme de MM evenementiel", DOM),

    # ═══ FUNDING / CARRY / BASIS ═══
    ("#538/H-133", "le carry COUVERT : les vrais chiffres", CONF,
     "✅ T2b l'a fait : **~2 % APR, pas 4 %**. Et **#543b vient de lui retirer 5 bps de plus.**"),
    ("#542/H-137", "funding arb perp<->perp", CONF,
     "🔒 **MORT** : X-04, 0/120. Couvrir ne change RIEN (ratio 0,0035 couvert vs 0,0036 nu). "
     "La forme cross-venue (HL<->Binance, MEME coin) a ete codee -- **et un piege d'unite 8h/1h "
     "m'a fait annoncer 38 % APR sur un ecart NUL.** Corrige."),
    ("#546/H-141", "crypto-carry-trade : analyse quantitative", EXAM),
    ("#547/H-142", "Nova_funding_hub : collecteur multi-DEX", EXAM,
     "⚠️ Mais on ne peut trader NULLE PART ailleurs. Collecter n'est pas capturer."),
    ("#553/H-148", "HypurrStable + c3p : le basis trade SUR Hyperliquid", EXAM,
     "🔑 **MEME actif** -> obeit a notre loi. C'est la forme de T2b. A confronter."),
    ("#556/H-151", "l'ORACLE HL : les CEX menent, l'oracle SUIT", EXAM,
     "🔑 **CONFIRME PAR LA DOC** : *« oracle prices are computed as the weighted median of CEX "
     "spot prices »*. **Le lag est mecanique et documente.** Entree differente du fill du leader. "
     "**Piste serieuse.**"),
    ("#560/H-155", "SAISONNALITE du funding : le prelevement horaire", FAIT,
     "Couvert par `snapshot_capture.py` (#531). Le flux mecanique existe ; reste a le chiffrer."),
    ("#544/H-139", "le VAULT HLP : le rendement de « l'autre cote »", EXAM,
     "🎯 **Malin** : HLP EST le market maker de HL. Son rendement est un **test direct** de T1b. "
     "⚠️ Mais HLP recoit les rebates ET fait les liquidations : ce n'est pas notre jeu."),
    ("#558/H-153", "OPEN INTEREST + long/short ratio : le trade ENCOMBRE", EXAM,
     "Entree nouvelle (OI, via `activeAssetCtx` / #504)."),
    ("#504/H-99", "`activeAssetCtx` : mark, oracle, funding, premium, basis, OI", CONF,
     "✅ **Deja dans notre allowlist et notre client.** A exploiter (OI, premium)."),

    # ═══ OVERFIT / METRIQUES / BACKTEST ═══
    ("#564/H-159", "l'hypothese qui expliquerait « 0 config robuste sur 150 M »", CONF,
     "✅ **On a la reponse** : il n'y avait rien a trouver. -7,97 bps **a cout ZERO**. Une boucle de "
     "recherche ne peut pas creer un edge qui n'existe pas."),
    ("#565/H-160", "recursive-analysis", CONF, "✅ **DEJA FAIT** : refute, ecart 26 M x sous le seuil."),
    ("#566/H-161", "`only_per_side` : verrouiller UN SEUL cote", EXAM,
     "19/21 ouvertures SHORT -- un desequilibre reel. A creuser."),
    ("#568/H-163", "les 4 protections + le VERROU REVERSIBLE", EXAM),
    ("#570/H-165", "la liste des 6 actions a faire ce soir", META),
    ("#577/H-172", "bilan des 12 repos lus", META),
    ("#579/H-174", "OPTIMISER LE PIRE MARCHE, PAS LA MOYENNE", CONF,
     "✅ **C'est exactement ce que T2b a fait** : le carry HYPE juge sur son **PIRE mois**."),
    ("#580/H-175", "le SIGNAL COLLANT : on entre peu avant qu'il disparaisse", EXAM,
     "🔑 Lie a Q1->Q3 : le prix court CONTRE le leader **avant** son fill. A creuser."),
    ("#581/H-176", "les 12 fonctions de perte : celle qu'on choisit EST la strategie", EXAM),
    ("#582/H-177", "pourquoi mon backtest != mon hyperopt ?", CONF,
     "✅ **On connait la reponse** : la coupe train/test **FUYAIT** (68 % du train), et les 7 "
     "garde-fous anti-overfit avaient **zero appelant**. Corrige (H-05, M-19)."),
    ("#584/H-179", "table ROI par paliers : sortir plus TOT", REF,
     "Zone morte CALIBRAGE_SLTP : **0 configuration robuste hors echantillon sur 150 M.** "
     "**Meme entree** (reglage de sortie)."),

    # ═══ SYNTHESES ═══
    ("#515/H-110", "bilan : 4 repos lus, 13 bugs trouves", META),
    ("#521/H-116", "VPIN sur HORLOGE DE VOLUME", EXAM,
     "🔑 Entree differente. Le VPIN mesure la TOXICITE du flux. ⚠️ Mais il ne ressuscite pas un "
     "signal sans information."),
    ("#522/H-117", "le dashboard qui NE PEUT PAS trader, par construction", CONF,
     "✅ **C'est notre architecture** : read-only, deny-by-default, 8/8 a l'audit securite."),
    ("#526/H-121", "bilan : 5 repos -> 24 trouvailles", META),
    ("#537/H-132", "bilan : 6 repos -> 34 trouvailles", META),
    ("#541/H-136", "les 5 pistes PnL reelles", META),
    ("#548/H-143", "la SYNTHESE PnL honnete", META),
    ("#551/H-146", "GAMMA SCALPING : Deribit + couverture perp HL", REF,
     "**On ne peut pas trader Deribit.** Meme mur que Binance. *Mesurer n'est pas capturer.*"),
    ("#555/H-150", "la CARTE PnL : 8 pistes par esperance x probabilite", META),
    ("#557/H-152", "les NICHES VIDES de 5 617 repos", EXAM),
    ("#559/H-154", "la THESE UNIFIEE : 4 pistes = 1 strategie", META),
    ("#561/H-156", "la CARTE PnL FINALE : 11 pistes", META),
    ("#585/H-180", "les 4 pistes PnL « GRATUITES »", EXAM,
     "🔑 **La bonne question.** Sans nouveau signal : (1) **payer moins de frais** -- #543 vient de "
     "montrer qu'on en payait de FAUX ; (2) **sortir mieux** -- 30 % du -64 $ etait structurel ; "
     "(3) **ne pas trader** -- deja le meilleur choix mesure ; (4) **le funding** -- T2b."),
]


def main() -> int:
    print("=" * 98)
    print("  TRIAGE #495-#585 (H-90 -> H-180) -- %d taches, une par une" % len(T))
    print("=" * 98)
    par: dict[str, list[str]] = {}
    for t in T:
        tid, titre, v = t[0], t[1], t[2]
        note = t[3] if len(t) > 3 else ""
        par.setdefault(v, []).append(tid)
        print("\n  %-12s %-58s [%s]" % (tid, titre[:58], v))
        if note:
            for p in note.split(". "):
                if p.strip():
                    print("      %s" % p.strip())
    print("\n" + "=" * 98)
    print("  RECAPITULATIF")
    print("=" * 98)
    for v in sorted(par, key=lambda k: -len(par[k])):
        print("  %-26s %2d" % (v, len(par[v])))
    print("\n  🎯 L'OR EST ICI -- et ce n'est PAS un repo GitHub, c'est NOTRE code :")
    print("     #543  : 6 valeurs de frais eparpillees, dont un 2,5 bps INVENTE.")
    print("     #543b : **le SPOT coute 2,7x le perp en maker** -> T2b sous-estime de 5 bps.")
    print("     #517  : la SEULE reouverture legitime (HIP-3) -- **a MESURER**, pas a supposer.")
    print("     #531  : le pre-print funding est REEL... mais il faut 72x le funding median.")
    print("     #530  : les liquidations -- flux FORCE, donc NON informe. La meilleure piste restante.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
