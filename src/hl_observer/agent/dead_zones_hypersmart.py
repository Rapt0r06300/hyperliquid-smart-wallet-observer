"""LES ZONES MORTES DEJA PAYEES : le cimetiere de HyperSmart (2026-07-12).

    « The scoring rule is the strategy. Everything downstream is just search. »
    « Sans memoire, l'agent re-propose des variantes qu'il a deja rejetees. »

Chaque entree ici a coute des jours. Elles ne sont PAS des opinions : chacune porte sa mesure,
son echantillon, et la condition exacte qui la rouvrirait.

TOUTE recherche future consulte ce fichier AVANT de proposer.

Aucun ordre reel.
"""
from __future__ import annotations

from hl_observer.agent.dead_zones import RegistreZonesMortes, creer_zone_morte

# ---------------------------------------------------------------------------------------------
# LE CIMETIERE. Chaque ligne = des jours de travail, et un chiffre qui a tue une esperance.
# ---------------------------------------------------------------------------------------------

ZONES = [
    creer_zone_morte(
        id="COPY_TRADING_NO_EDGE",
        hypothese="Copier les fills des whales rapporte, si on filtre/regle assez bien.",
        verdict="Le copy-trading n'a AUCUN edge, a AUCUN horizon.",
        mesure="edge net median apres un fill de leader, hors echantillon",
        valeur=-7.97, unite="bps",
        echantillon=24133,
        entree_mesuree="fill_public_leader",
        date="2026-07-11",
        lecon=(
            "Un score de wallet n'est pas un edge en bps. Un consensus n'est pas une preuve de "
            "rentabilite. MEME A COUT ZERO l'esperance reste negative : aucun reglage de seuil, "
            "de SL/TP, de filtre ou de hedge ne peut sauver un signal qui ne predit rien."
        ),
        condition_de_reouverture=(
            "un mecanisme STRUCTURELLEMENT different (ex. acces au flux d'ordres AVANT execution, "
            "pas apres), ou une source de signal qui n'est pas le fill public d'un leader"
        ),
        # FAUX NEGATIF CORRIGE (2026-07-12) : la proposition « scanner plus de wallets, les
        # classer, suivre les meilleurs POUR COPIER LEURS FILLS » passait SANS alerte.
        # Or c'est le copy-trading, deguise en probleme d'infrastructure. Ameliorer le scanner
        # ne cree pas un edge : ca alimente plus vite un signal mesure a -7,97 bps.
        # Une zone morte doit attraper l'IDEE, pas seulement son vocabulaire.
        mots_cles=("copy", "copytrading", "leader", "whale", "consensus", "sniper", "min_edge",
                   "dominance", "wallet_score",
                   # NOTE : la correspondance se fait sur des MOTS isoles (regex [a-z_]{3,}).
                   # Un mot-cle a plusieurs mots ("suivi temps reel") ne peut JAMAIS matcher :
                   # ce serait un mot-cle MORT, qui donne une fausse impression de couverture.
                   "scanner", "scan", "wallets", "classement", "ranking", "shortlist",
                   "decouverte", "copiable", "copyability", "fill", "fills", "copier",
                   # 🚩 2e FAUX NEGATIF CORRIGE (2026-07-13, lot IDEA #204/#207) :
                   # « suivre les market makers connus » et « graphe de transactions / clustering
                   # de wallets » passaient SANS alerte. Or ce sont ENCORE des signaux derives du
                   # COMPORTEMENT D'UN WALLET -- exactement ce qui a ete mesure a -7,97 bps.
                   # Changer la facon de CHOISIR le wallet ne change pas ce que son fill predit.
                   "market_makers", "mm_connus", "graphe", "clustering", "cluster",
                   "adresses", "onchain_wallet", "suivi"),
        source="docs/audit/PREUVE_ABSENCE_EDGE_COPYTRADING.md",
    ),
    creer_zone_morte(
        id="LATENCE_NEST_PAS_LE_PROBLEME",
        hypothese="Si on decidait plus vite (sub-seconde), l'edge de copie apparaitrait.",
        verdict="La courbe edge/horizon est PLATE. Le probleme n'a jamais ete la latence.",
        mesure="edge median a 500 ms apres le fill du leader",
        valeur=-3.74, unite="bps",
        echantillon=15571,
        entree_mesuree="fill_public_leader",
        date="2026-07-11",
        lecon=(
            "Aller plus vite vers un signal qui ne dit rien fait perdre de l'argent plus vite. "
            "Un gain de fraicheur est un gain TECHNIQUE ; il ne devient economique que si la "
            "courbe edge/horizon montre un edge a ces horizons. Ici elle n'en montre a AUCUN."
        ),
        condition_de_reouverture=(
            "des donnees a resolution < 100 ms sur un signal DIFFERENT du fill public"
        ),
        # 🚩 FAUX NEGATIF CORRIGE (2026-07-13, lot IDEA #188) : la proposition « mettre un BUS DE
        # MESSAGES (Redis/Kafka) » passait SANS alerte. Or un bus de messages n'achete qu'UNE
        # chose : de la LATENCE. Et la latence est deja mesuree morte ici meme (courbe PLATE).
        # C'est la meme lecon que pour le copy-trading deguise en probleme de scanner :
        # *une zone morte doit attraper l'IDEE, pas seulement son vocabulaire.*
        mots_cles=("latence", "latency", "hot_path", "fraicheur", "freshness", "horizon",
                   "subseconde", "rust", "colocation",
                   # l'infra qui ne vend QUE de la vitesse -> meme zone morte.
                   # 🚩 ET UNE LECON, PAYEE PAR UN TEST ROUGE : ma 1re version ajoutait le mot
                   # « bus ». Il a immediatement VOLE les propositions destinees a la zone
                   # BUS_GITHUB_EXTERNE, qui ne protegeait plus rien. *Un mot-cle trop generique
                   # n'elargit pas une protection : il en CANNIBALISE une autre.* On nomme donc
                   # les TECHNOS, pas les concepts vagues.
                   "redis", "kafka", "zeromq", "rabbitmq", "nats", "pubsub", "amqp"),
        source="docs/research/EDGE_HORIZON_ET_CARRY_FUNDING.md",
    ),
    creer_zone_morte(
        id="ML_SEQUENTIEL_SUR_SIGNAL_SANS_INFORMATION",
        hypothese=(
            "Un modele SEQUENTIEL (LSTM/GRU, Transformer, RL) extrairait de nos features un edge "
            "que le gradient boosting n'a pas trouve."
        ),
        verdict=(
            "Plus de CAPACITE ne cree pas d'INFORMATION. Le signal sous-jacent a un edge mesure "
            "NEGATIF hors echantillon, meme a cout ZERO."
        ),
        mesure="edge net du signal, hors echantillon, a cout zero (la borne haute absolue)",
        valeur=-7.97, unite="bps",
        echantillon=24133,
        # 🔴 CE CHAMP EST LE CORRECTIF DE MA FAUTE DU 2026-07-13.
        # La mesure porte sur le FILL PUBLIC D'UN LEADER. Elle tue donc LSTM/Transformer sur CE
        # signal (meme entree, autre fonction). Elle ne dit RIEN d'un RL de politique de SORTIE,
        # dont l'entree est l'etat APRES l'entree en position. J'avais quand meme enterre IDEA-04.
        # C'etait un prejuge deguise en deduction -- Flo l'a vu, et il avait raison.
        entree_mesuree="fill_public_leader",
        date="2026-07-13",
        lecon=(
            "IDEA-02/03/04 (LSTM, Transformers, RL). Un modele n'invente pas d'information : il "
            "en extrait. Nos features decrivent le fill public d'un leader -- et ce fill est "
            "CONTRARIEN (le prix court CONTRE lui de -7,75 bps AVANT l'execution, puis plus rien). "
            "Le gradient boosting (IDEA-01, fait) PERD deja contre la baseline (P13 : sa promotion "
            "est bloquee pour cette raison). Empiler des LSTM sur des features sans information, "
            "c'est apprendre le bruit avec plus de parametres -- et sur-ajuster mieux. "
            "*On ne repare pas un signal vide en achetant un plus gros modele.*"
        ),
        condition_de_reouverture=(
            "un JEU DE FEATURES dont l'edge mesure hors echantillon est POSITIF apres couts. "
            "A ce moment-la, et seulement la, la question « quel modele l'extrait le mieux ? » "
            "devient legitime. Tant que l'edge des features est negatif, aucun modele ne peut le "
            "rendre positif"
        ),
        # 🔴 MOT-CLE MORT CORRIGE (2026-07-13) : "rl" faisait DEUX caracteres. La regex de
        # `consulter()` est [a-z_]{3,} -> il ne pouvait matcher JAMAIS. Il ne protegeait RIEN.
        # C'est un TEST ROUGE qui l'a trouve, pas moi : mon propre test attendait un refus, et
        # le registre a repondu LIBRE. *Un garde-fou qui ne peut pas mordre ne garde rien.*
        mots_cles=("lstm", "gru", "transformer", "rnn", "reinforcement", "deep",
                   "neural", "reseau", "sequentiel", "attention", "policy", "agent_rl",
                   "ppo", "dqn", "q_learning", "actor_critic"),
        mots_cles_reouverture=("features", "edge_positif", "nouveau_signal", "oos_positif"),
        source="docs/audit/PREUVE_ABSENCE_EDGE_COPYTRADING.md + P13 (#300)",
    ),
    creer_zone_morte(
        id="FUNDING_JAMBE_NUE",
        hypothese="Encaisser un funding eleve rapporte, meme sans jambe de couverture.",
        verdict="Le prix noie le funding d'un facteur ~281. Une jambe nue est un pari, pas un carry.",
        mesure="ratio median funding / bruit de prix, sur 232 marches",
        valeur=0.0036, unite="ratio",
        echantillon=9512,
        entree_mesuree="funding_seul",
        date="2026-07-11",
        lecon=(
            "PIEGE CONTRE-INTUITIF : monter le seuil de funding ne filtre PAS le risque, il le "
            "CONCENTRE. Le funding est eleve PRECISEMENT la ou le marche est dangereux. Le gate "
            "a 2,5 bps/h ne laissait passer que CASHCAT... qui bouge de 219 bps/h."
        ),
        condition_de_reouverture=(
            "une VRAIE jambe de couverture (spot ou perp oppose) qui annule le risque de prix -- "
            "un frais forfaitaire n'est PAS une couverture"
        ),
        mots_cles=("funding", "carry", "grinder", "arb", "delta_neutre", "cashcat"),
        # LA VOIE DE SORTIE, designee par la mesure elle-meme : une VRAIE couverture.
        mots_cles_reouverture=("spot", "hedge", "couverture", "couvert", "hedged",
                               "jambe_opposee", "basis"),
        source="src/hl_observer/funding/funding_carry_economics.py",
    ),
    creer_zone_morte(
        id="EDGE_FABRIQUE",
        hypothese="On peut deriver un edge en bps d'un score de consensus.",
        verdict="`dominance x 45 + bonus` n'a JAMAIS touche un prix. C'etait une fiction.",
        mesure="constantes inventees dans la formule d'edge (45, 9, 0.55, 10, 25000)",
        valeur=45.0, unite="constante sans source",
        echantillon=24133,
        entree_mesuree="score_consensus",
        date="2026-07-11",
        lecon=(
            "UN EDGE EST UN MOUVEMENT DE PRIX ATTENDU, MESURE. Pas un score de vote converti en "
            "bps par une constante. J'ai optimise un seuil, recalibre des SL/TP et lance un "
            "replay de 150 millions de scenarios SUR CE CHIFFRE -- sans jamais ouvrir la fonction "
            "qui le produisait. On optimise une fiction avec une grande rigueur."
        ),
        condition_de_reouverture=(
            "jamais pour une formule inventee ; un edge doit venir d'une table MESUREE "
            "(runtime/calibration/empirical_edge.json)"
        ),
        mots_cles=("edge", "consensus", "vote", "score", "dominance", "bonus", "proxy"),
        source="src/hl_observer/edge/empirical_edge.py",
    ),
    creer_zone_morte(
        id="BUS_GITHUB_EXTERNE",
        hypothese="Lancer des profils de strategies GitHub comme moteurs donne un edge.",
        verdict="PF net 0,61. Ecarte -- mais reste ALLUME dans le code pendant des semaines.",
        mesure="profit factor net des 38 profils externes",
        valeur=0.61, unite="PF",
        echantillon=810,
        entree_mesuree="profils_github",
        date="2026-07-12",
        lecon=(
            "Un moteur abandonne doit etre eteint DANS LE CODE, pas dans les tetes. Son defaut "
            "etait `priority` : personne ne l'avait rallume, il n'avait jamais ete eteint. "
            "810 evaluations pour 21 entrees reelles, dans le hot path."
        ),
        condition_de_reouverture=(
            "une idee distillee A LA MAIN dans un module HyperSmart teste -- jamais du code "
            "upstream lance comme moteur autonome"
        ),
        mots_cles=("github", "bus", "external", "profil", "repo", "upstream", "distillation"),
        source="src/hl_observer/strategies/external_simulation_bus.py",
    ),
    creer_zone_morte(
        id="MM_SUR_LES_MAJORS",
        hypothese="On peut faire du market making sur BTC/ETH/SOL.",
        verdict="Les frais maker sont 10 a 20x le spread. Arithmetiquement mort.",
        mesure="spread median BTC contre cout aller-retour maker/maker (3,0 bps)",
        valeur=0.16, unite="bps de spread",
        echantillon=1363,
        entree_mesuree="carnet_l2_majors",
        date="2026-07-12",
        lecon=(
            "Chez Hyperliquid le maker PAIE 1,5 bps (pas de rebate avant les tiers "
            "institutionnels). Sur un carnet parfait, l'espace est nul : c'est le metier de gens "
            "avec des rebates et de la colocation. Le spread ne se capture pas la ou tout le "
            "monde le voit."
        ),
        condition_de_reouverture=(
            "un tier de frais avec rebate maker negatif (>500 M$ de volume / 14 j) -- hors de "
            "portee ; ou un marche FIN avec du flux reel (mesure en cours)"
        ),
        # 🔴 2e MOT-CLE MORT (2026-07-13) : "mm" faisait DEUX caracteres -> jamais matche.
        # Remplace par des mots qui existent vraiment dans une proposition.
        mots_cles=("market_making", "market_maker", "cotation", "quoting",
                   "spread", "maker", "majors", "btc", "eth", "sol"),
        mots_cles_reouverture=("rebate", "fins", "illiquide", "flux"),
        source="tools/mesurer_spread_carnet.py",
    ),
    creer_zone_morte(
        id="CALIBRAGE_SLTP_OOS",
        hypothese="Un meilleur reglage SL/TP peut rendre le PnL positif.",
        verdict="Aucun calibrage n'est positif hors echantillon. Le meilleur choix = NE PAS TRADER.",
        # 🔴 CORRIGE LE 2026-07-13 (#578 / H-173) — « JE ME SUIS TROMPE ».
        # J'ai ecrit **150 000 000** ici, et dans 10 autres endroits du code, et dans toute ma
        # memoire. **Le seul rapport sur disque dit `scenarios_evaluated: 1 425 000`.**
        # (runtime/scenarios/replay_4h_report.json)
        #
        # Facteur **105**. Le 150 M etait la taille THEORIQUE de la grille, pas le nombre
        # REELLEMENT evalue -- la recherche s'arrete tot (limite de temps / fichier STOP).
        #
        # ✅ LE CODE, LUI, ETAIT JUSTE : `scenario_search` passe `n_essais=int(evaluated)`,
        #    le VRAI compteur. Le gate anti-overfit n'a jamais ete faux.
        # ✅ ET LA CONCLUSION TIENT : **0 configuration robuste sur 1 425 000 essais reste 0.**
        #    *C'est le chiffre qui etait faux, pas le verdict.*
        #
        # ⚠️ Un chiffre qu'on ne peut pas tracer jusqu'a un rapport est un chiffre qui ment.
        mesure="configurations robustes sur holdout (rapport: runtime/scenarios/replay_4h_report.json)",
        valeur=0.0, unite="configurations robustes",
        echantillon=1_425_000,
        entree_mesuree="reglage_sltp",
        date="2026-07-09",
        lecon=(
            "La boucle generer/tester/selectionner a PARFAITEMENT fonctionne : elle a correctement "
            "rapporte que rien ne survit hors echantillon. Une boucle de recherche ne PEUT PAS "
            "creer un edge qui n'existe pas. Il ne manquait pas la recherche, il manquait quelque "
            "chose qui vaille la peine d'etre cherche."
        ),
        condition_de_reouverture=(
            "un SIGNAL d'entree different (pas un reglage de sortie) dont l'edge est mesure positif"
        ),
        mots_cles=("sltp", "calibrage", "calibration", "stop", "takeprofit", "trailing",
                   "replay", "grid", "seuil", "threshold", "tuning"),
        source="docs/ANALYSE_REPLAY_LEVIER_REEL.md",
    ),
    # ═════════════════════════════════════════════════════════════════════════════════════════
    # 2026-07-13 — L'ARGUMENT DE DOMINATION. Il enterre 15 taches d'un coup (H-46..H-89).
    # ═════════════════════════════════════════════════════════════════════════════════════════
    creer_zone_morte(
        id="MODELE_DE_FILE_ET_DE_FILL",
        hypothese=(
            "Un meilleur modele de file / de remplissage (ProbQueueModel, L3FIFO, position par "
            "ordre depuis le noeud, hftbacktest...) rendrait le market making viable."
        ),
        verdict=(
            "IMPOSSIBLE PAR ARITHMETIQUE. T1b a mesure le MM a **100 % de remplissage** -- la "
            "borne la PLUS GENEREUSE possible -- et a trouve 0/29 coins viables. Tout modele de "
            "file plus realiste ne peut qu'ABAISSER le fill, donc qu'AGGRAVER le verdict."
        ),
        mesure="coins viables en cotant DANS le spread, a 100 % de remplissage",
        valeur=0.0, unite="coins viables sur 29",
        echantillon=9_543,
        entree_mesuree="modele_de_file",
        date="2026-07-13",
        lecon=(
            "Ce n'est pas un prejuge, c'est une DOMINATION. Quand une mesure est faite a la borne "
            "la plus favorable et qu'elle est NEGATIVE, toute amelioration du realisme ne peut que "
            "l'empirer. **Il n'y a rien a esperer d'un meilleur modele de file.** "
            "Le spread n'est jamais un cadeau : c'est le PRIX DU RISQUE -- le prix bouge 5 a 30x "
            "plus que le spread capture pendant qu'on porte l'inventaire."
        ),
        condition_de_reouverture=(
            "une mesure montrant que le RISQUE D'INVENTAIRE (mouvement du prix pendant la "
            "detention) est INFERIEUR au spread capture sur au moins un marche -- ce qui "
            "n'a RIEN a voir avec le modele de file"
        ),
        # 🚩 UN SEUL MOT, sans espace ni tiret : la regex est `[a-z_]{3,}`. Un mot-cle avec un
        # espace ("market making") ne pourrait JAMAIS matcher -- c'est le bug des mots-cles MORTS
        # ("rl", "mm") documente ce matin meme, et je viens de le refaire ce soir. Mon propre
        # invariant m'a rattrape.
        # ⚠️ "l3fifo" serait MORT aussi : le tokeniseur est [a-z_]{3,}, le CHIFFRE le coupe
        # ("l3fifo" -> "fifo"). 3e forme du meme piege, et mes tests ne la voyaient pas.
        mots_cles=("file", "queue", "fill", "remplissage", "probqueue", "fifo", "hftbacktest",
                   "making", "quoting", "coter", "xemm", "glft", "grinder"),
        mots_cles_reouverture=("inventaire", "inventory", "detention"),
        source="src/hl_observer/backtesting/quoting_inside_spread.py",
    ),
    creer_zone_morte(
        id="LATENCE_COMME_CAUSE",
        hypothese=(
            "Reduire la latence (ou mieux la modeliser : latence de flux vs latence d'ordre) "
            "ameliorerait l'edge."
        ),
        verdict=(
            "NON. La courbe edge/horizon est PLATE : a 500 ms l'edge est de -3,74 bps ; a 8 h il "
            "est du meme ordre. **L'edge est negatif AVANT toute latence.** On ne repare pas avec "
            "de la vitesse un signal qui n'a aucune information."
        ),
        mesure="edge net a 500 ms d'horizon",
        valeur=-3.74, unite="bps",
        echantillon=24_133,
        entree_mesuree="latence",
        date="2026-07-11",
        lecon=(
            "La latence est le premier reflexe de tout le monde, et c'etait le notre. La courbe "
            "plate l'a tue : **la latence n'a JAMAIS ete le probleme.** Le probleme est le "
            "CONTENU du signal (le leader est contrarien), pas sa VITESSE."
        ),
        condition_de_reouverture=(
            "un signal dont l'edge est mesure POSITIF a horizon court -- alors, et seulement "
            "alors, la vitesse devient un enjeu"
        ),
        # Idem : un seul mot, sans espace. ("hft rapide" / "edge positif" seraient MORTS.)
        mots_cles=("latence", "latency", "vitesse", "speed", "colocation", "hft"),
        mots_cles_reouverture=("positif", "informatif"),
        source="src/hl_observer/backtesting/horizon_curve.py",
    ),
]


def registre_officiel() -> RegistreZonesMortes:
    """Le cimetiere de HyperSmart. A consulter AVANT toute nouvelle piste."""
    r = RegistreZonesMortes()
    for z in ZONES:
        r.enterrer(z)
    return r


__all__ = ["ZONES", "registre_officiel"]
