# Alina SmartFlow — état courant autoritatif

Dernière mise à jour : **2026-11-12**.

L'ancre **`c40263c8a5188fb6c39d5a92b149635243c6155e`** est un audit historique du 2026-09-10, pas une certification du HEAD actuel. Le scope Copy-Vault-only a été recontrôlé dans le checkout local au HEAD de base **`755441d3b442c9c981d2876d07bf71f9459e1ad5`** ; la copie de travail est modifiée et cette vérification ciblée ne vaut pas validation globale.

Ce document est la **source de vérité lisible actuelle** pour l'état du projet. Il ne remplace pas les contrats exécutables : en cas de divergence, le code, les tests, les gates CI et les registres machine gagnent toujours.

## 0 quater. COMMENT LIRE CE DOCUMENT + PLAN D'ATTAQUE PRIORISÉ (2026-11-12)

**Point d'entrée unique.** Ce document fait ~2000 lignes et 920 tâches numérotées. Commencez ICI, pas
ailleurs. Trois choses : la carte des sections, les 12 leviers réels (les 920 tâches n'en sont que les
déclinaisons), et le plan de sprints avec un critère de fin MESURABLE pour chaque action.

### Table des sections
| Section | Contenu | Tâches |
|---|---|---|
| 0 / 0 bis / 0 ter | Historique de reprise + feuille de route de base | L1–L110 (labo), C1–C110 (collecteurs) |
| C | Ce qui est DÉJÀ fait et testé le 12/11 (non commité) | — |
| C-bis / C-ter | Audit des données ; premiers chantiers *(SUPERSÉDÉ par C-quater)* | — |
| C-quater | Programme complet, 8 programmes | A1–A7, B1–B8, C1–C6, D1–D10, E1–E8, F1–F8, G1–G7, H1–H8 |
| C-quinquies | Chantiers détectés par le run du 12/11 | R1–R6 |
| C-sexies | Résilience mémoire (jamais crasher) | M0–M5 |
| C-septies | « Mon bot parfait » | T1–T200 |
| C-octies | Recherche web #1 (labo/collecteur/moteur) | W-C*, W-L*, W-M*, W-S* |
| C-novies | Améliorations concrètes & paramétrées | I1–I300 |
| C-decies | Synthèse directrice (fil conducteur) | — |
| C-undecies | Gisements d'edge (≈20 recherches web) | GIS1–GIS200 |
| D | Ancien « prochain pas » *(remplacé par le plan ci-dessous)* | — |

### Les 12 LEVIERS réels (carte de convergence)
920 tâches ne sont PAS 920 choses indépendantes. Elles se ramènent à 12 leviers. Avant d'ouvrir une
tâche, vérifiez son levier : vous verrez immédiatement les autres identifiants qui disent la même chose,
et vous éviterez de coder deux fois le même travail.

1. **RENDRE MESURABLE** (prérequis absolu) → A1–A7 · C21/C23/C25 · R2 · T156–T158 · I16–I30 · W-C1/W-C2
2. **EXÉCUTION MAKER** (gagner le spread) → B1–B8 · T27–T40 · I46–I60 · W-M1/M3/M4 · GIS52–GIS54, GIS67
3. **LATENCE & ANTICIPATION** → C1–C6 · T14–T26, T41–T52 · I61–I75 · GIS1–GIS13, GIS40–GIS51
4. **SÉLECTION DE LEADERS** → D1 · T53–T67 · I136–I150 · GIS114–GIS125
5. **CONDITIONNEMENT DU SIGNAL** → D2–D10 · T68–T82 · I91–I105 · GIS27–GIS39
6. **CROWDING / ANTI-EXPLOITATION** → T83–T92 · I151–I165 · GIS64–GIS76
7. **STRATÉGIES ALTERNATIVES** → E1–E8 · T93–T108 · I166–I180 · GIS101–GIS113, GIS163–GIS175
8. **RÉPLICATION PAR POSITION** → T109–T118 · I181–I195 · W-C1 · R3
9. **CAPITAL & RISQUE** → F1–F8 · T119–T130 · I196–I210 · GIS89–GIS100, GIS138–GIS150
10. **RÉGIMES** → T169–T178 · I211–I225 · GIS14–GIS26, GIS77–GIS88, GIS176–GIS187
11. **RIGUEUR & PREUVE** → G1–G7 · T131–T143 · I106–I120 · W-L1–W-L5 · GIS188–GIS200
12. **RÉSILIENCE & INFRA** → M0–M5 · H1–H8 · T144–T168 · I241–I300

### RÉFUTÉ — ne plus y dépenser de calcul (avec les chiffres)
Rouvrir UNIQUEMENT si une donnée nouvelle change la mesure — jamais sur une intuition.
- **Copie naïve miroir taker** : REJECTED (IC 95 % du net par unité entièrement négatif après coûts).
- **Fast-follow sur fills taker** : REJECTED, et **même à spread supposé nul**, à TOUT horizon ≤ 300 s.
- **Recherche par grille globale** : 81 920 scénarios historiques rejoués ne battent pas l'incumbent →
  l'avantage, s'il existe, est dans un **sous-ensemble conditionnel**, pas dans un réglage global.
- **Carry de NIVEAU** (cash-and-carry delta-neutre) : net +5,6 %/an décroissant vers négatif, sous les
  T-bills ; son Sharpe de 8,5 est un artefact de la volatilité quasi nulle du funding.
- **Momentum cross-sectionnel net de coûts** : non distinguable de zéro, et le signe **bascule selon la
  phase de rebalancement** (un choix de calendrier sans information de marché).
- **VPIN en BVC** : proxy de volatilité déguisé (ne garde que +0,12 de toxicité) → n'utiliser que le
  tick-rule ou les vrais signes d'agresseur.
- **Signal appris pris en taker** : la prédictibilité sub-minute est réelle (~60 % de hit) mais le spread
  la mange (brut +3850 bps / spread −8091 bps) → un signal ne sert qu'à POSER un ordre maker.

### PLAN D'ATTAQUE — 3 sprints, chaque action avec son critère de fin
Règle : **ne rien lancer du sprint 2 avant que le sprint 1 ne soit fini**. Tant que la sonde refuse,
chercher ne sert à rien (leçon du run de 6 h 33 à vide).

**SPRINT 1 — DÉBLOQUER LA MESURE** *(rien d'autre ne compte ; impact maximal, effort surtout du temps)*

| # | Action | Bloqueur | Critère de FIN (mesurable) |
|---|---|---|---|
| S1.1 | Laisser tourner les collecteurs corrigés **≥ 6 jours denses** | temps uniquement | `tools/etat_executabilite.py` n'affiche plus « 0 trade exécutable » |
| S1.2 ✅ | **Source préventive (coins habituels) + liste débloquée** — **FAIT** (point 18) ; l'effet se mesure après S1.1 | — | le motif « aucun carnet 30 s avant le signal » (77 008 refus) tombe sous 10 % |
| S1.3 ✅ | ~~Collecter `leader_orders` **ET** fills du MÊME leader~~ **FAIT** (section C, point 16) | — | l'étude `order_intent` ne dit plus « 0 fill pendant le suivi des carnets » |
| S1.4 | Couvrir les coins HIP-3 manquants (A5) | S1.1 | les 20 coins de `coins_a_collecter` sont tous couverts |
| S1.5 ✅ | **Gouverneur M0 + surveillance de l'étape 1 + cache de carnets** — **FAIT** (points 13-15) ; reste la découpe par lot interne au labo | — | un passage labo complet termine sous 10 Go et ne se fait plus tuer |
| S1.6 ✅ | **Mesure du décalage en ms (Hayashi-Yoshida) + garde-fous** — **FAIT** (point 17) ; reste à brancher la collecte du flux Binance | — | décalage HL↔Binance mesuré par coin, APRÈS contrôle des artefacts d'horodatage |
| S1.7 | `audit_complet.py` à chaque cycle | — | aucune famille en « CERTIFIÉ · NON UTILISÉ » |

**SPRINT 2 — ATTAQUER LES DEUX TUEURS CHIFFRÉS** *(coût ≈ 5–9 bps, délai ≈ 7,6 bps)*

| # | Action | Bloqueur | Critère de FIN (mesurable) |
|---|---|---|---|
| S2.1 | Brancher `maker_fill` + Avellaneda-Stoikov (I46–I51) | S1 | le moteur pose un ordre passif par défaut ; net/décision recalculé en frais maker |
| S2.2 | **Markout +1 s** comme métrique d'adverse selection (W-M2) | S2.1 | courbe de markout publiée par coin |
| S2.3 | Modèle de file + re-pricing « cancel-first » HL (W-M1/M3) | S2.1 | probabilité de remplissage estimée ; nos ordres re-pricés avant d'être pick off |
| S2.4 | Balayage de **latence** sur données exécutables (`chantier_latence`) | S1.1 | net par délai 5/15/30/60/120 s publié + verdict « le délai est-il le verrou ? » |
| S2.5 | Fenêtre **week-end HIP-3** (GIS64–GIS68) | S1.4 | edge maker mesuré séparément week-end vs semaine |
| S2.6 | Conditionnement minimal : spread bas + OFI + fill agressif (D2–D5) | S1 | un sous-ensemble de décisions au net > 0 est isolé, **ou** réfuté avec son IC |
| S2.7 | **Porte conformale de non-trade** (GIS138–GIS143) | S2.6 | on ne copie que si l'intervalle n'enjambe pas zéro ; taux filtré mesuré |

**SPRINT 3 — PROUVER OU ABANDONNER** *(aucune promotion sans ces portes)*

| # | Action | Bloqueur | Critère de FIN (mesurable) |
|---|---|---|---|
| S3.1 | CPCV + **DSR** + **PBO** sur toute piste (W-L1–W-L3) | S2 | chaque verdict porte son DSR et son PBO |
| S3.2 | Portes VALIDATION → OOS → FORWARD (G1) | S3.1 | aucune stratégie promue sans les trois |
| S3.3 | **Carry cross-sectionnel** (GIS169–GIS171) | S1 | OOS purgé mesuré chez nous, avec PBO et drawdown max |
| S3.4 | Réplication lente : finir les 20 jours (R3, à 17/20) | 3 jours de données | premier verdict NET sur la réplication par position |
| S3.5 | **FORWARD paper en direct** (G5) | S3.2 | PnL net suivi en temps réel sur données non vues |
| S3.6 | HRP adaptatif pour répartir le risque (GIS89–GIS100) | S3.2 | allocation bornée entre leaders/coins/stratégies |
| S3.7 | **Le Verdict** (`tools/le_verdict.py`) | S3.1 | un tableau unique PROVEN/PROMISING/MORE_DATA/REJECTED avec net/jour après TOUS les coûts |

**Ce qu'il ne faut PAS faire maintenant :** lancer des campagnes de recherche, ajouter des hypothèses,
optimiser des seuils, ou relancer les stratégies réfutées ci-dessus. Tout cela consomme du calcul et des
essais (qui comptent dans la correction de multiplicité) sans pouvoir rien prouver avant le sprint 1.

## 0. Nouveautés (2026-11-11) — reprise de mission, point de reprise

Base : HEAD local `391efb93b1a3eab60b9eb8119dce491807eac0fa` (GitHub en avance de 3 commits de reçus
cloud, sans code). Modifications locales non commitées, non poussées. Tout est PAPER / lecture seule.

**Défauts mesurés puis corrigés (chacun avec un test de régression) :**

- **Labo principal : recherche à vide.** Le run `20261110T131434661405Z` a duré 6 h 33 et essayé
  133 676 jeux de paramètres sur une entrée vide. Deux causes : (1) `tools/pipeline_copie_reel.py`
  n'admettait que la source `LIVE_WS` alors que les 5 245 840 fills live du corpus sont `LIVE_POLL`
  (causaux, horloge de réception valide) ; (2) la découpe TRAIN / VALIDATION / OOS portait sur tous
  les jours de signal, dont 768 jours d'historique sans carnet : TRAIN était structurellement vide.
  Corrections : point unique `is_causal_live_source` appliqué partout ; découpe sur les jours
  **évaluables** (`backtesting/copy_vault_signal_alignment.py`) ; arrêt immédiat
  `INSUFFICIENT_EVALUABLE_SIGNAL_DAYS` sans aucun essai ; champ natif `startPosition` pris en compte
  (une fermeture de short n'est plus lue comme une ouverture) ; ruban live lu en flux ; cycles
  reconstruits une seule fois par exécution ; un jour ne porte la découpe que s'il compte au moins
  10 signaux évaluables (quelques signaux isolés d'octobre suffisaient sinon à franchir le minimum
  de jours, avec un TRAIN quasi vide) ; l'exploration « overshoot » n'est plus lancée avant ce
  contrôle. **Mesure après correction, même workspace : verdict en 6 min 43 s** (`MORE_DATA`,
  `INSUFFICIENT_EVALUABLE_SIGNAL_DAYS`, 0 essai), 5 245 840 fills causaux → 2 347 711 entrées →
  698 071 signaux, dont **77 210 évaluables (11 %)** sur 5 jours denses pour 6 requis. Mémoire
  résidente : 13,6 Go.
- **Limite de données n° 1 révélée par cette mesure :** 89 % des signaux des leaders n'ont aucun
  carnet L2 reçu dans les 30 s précédentes : leur coût d'exécution n'est pas mesurable. La
  couverture L2 des coins réellement tradés par les leaders (dex HIP-3 compris) prime sur tout
  nouveau flux.
- **Lanes cloud L2 et marché : symboles mis en majuscules.** `kPEPE`, `kSHIB`, `kBONK`, `kFLOKI`
  devenaient `KPEPE`… (inconnus de l'API) : aucun carnet ni trade collecté pour ces coins. Identité
  native conservée dans `tools/collecter_l2_lane.py` et `tools/collecter_market_lane.py`.
- **Frais dupliqués.** Le détecteur de signaux de copie appliquait 4,0 bps au lieu de 4,5 ; le modèle
  d'exécution PAPER et le plancher de risque recopiaient la valeur. Tous lisent maintenant
  `fees/hyperliquid_fees.py` ; parité vérifiée par `tests/test_frais_source_unique.py`.
- **Porte économique obsolète.** Le repère +5 USD restait une porte dans la preuve PnL par module, la
  certification finale, la certification journalière, le job de famille et la mémoire économique.
  Conformément à la spec canonique : certification = toutes les portes de qualité + net réconcilié
  strictement positif ; le repère est rapporté à part (`reference_target_reached`,
  `reference_target_is_gate=false`). Une preuve héritée sans `certification_policy` reste jugée avec
  l'ancien seuil.

**Nouvelle chaîne collecte → certification → labo :** les courbes valeur / PnL / volume publiées par
`vaultDetails` (des mois d'historique par vault) étaient téléchargées à chaque passe puis jetées.
Elles sont conservées (`collection/vault_portfolio_history.py`, ruban
`runtime/data/vault_portfolio_history.jsonl`), certifiées (famille `vault_portfolio`) et consommées
par `tools/etude_copiabilite.py --persistance` (`backtesting/copy_vault_persistence.py`) : le
classement passé d'un leader prédit-il son rendement suivant, net de la borne haute du coût de
réplication ? Hypothèse `copy_vault_leader_skill_persistence` : **UNMEASURABLE** tant qu'une passe
de collecte n'a pas eu lieu (aucune donnée réelle n'a été collectée pendant cette session).

**Validation exécutée le 2026-11-11 (poste local, Python 3.11, par tranches de 150 fichiers) :**
suite complète 17 645 réussis / 4 échecs / 68 ignorés. Les 4 échecs : trois provenaient d'une
famille ajoutée au certificateur avant son entrée au registre de couverture (corrigé), un d'un test
qui relisait un fichier UTF-8 avec l'encodage du poste (corrigé) ; rejoués verts. Régression ciblée
sur tous les tests touchant aux modules modifiés : 1 293 réussis. Les reçus locaux de la roadmap,
périmés par ces modifications (124), sont revalidés par `tools/revalider_receipts.py` : il rejoue
les tests de chaque reçu puis AJOUTE un reçu rafraîchi ou `REVALIDATION_FAILED`, sans réécrire le
registre (l'ancien `tools/regenerer_receipts.py` rafraîchit les empreintes sans rejouer : à éviter).

**Seconde séquence du 2026-11-11 (lectures ponctuelles autorisées) — commitée et poussée par `POUSSER-GITHUB.cmd` à 17 h 34 : commit `bb41b323`, 90 chemins, `origin/main` aligné :**

- Faits vérifiés auprès de l'API officielle : identifiants sensibles à la casse (`xyz:XYZ100`, `kPEPE` ;
  `XYZ:XYZ100` et `KPEPE` refusés) ; `l2Book`, `bbo`, `trades` fonctionnent sur les dex HIP-3 ; **un seul
  abonnement invalide fait fermer toute la connexion WebSocket** ; le message `clearinghouseState` du
  WebSocket imbrique l'état (les lanes « contexte » n'avaient jamais écrit une position) ; le PnL des
  fenêtres jour/semaine/mois de `vaultDetails` repart de 0 (recalé sur le cumul, schéma v2).
- Collecte automatique par `LANCER_COLLECTEURS_COPY_VAULT.cmd` : `vault-collector` écrit l'historique de
  portefeuille, balaye l'univers élargi (2 333 vaults dont les fermés, 12 par passe) et relève les
  portefeuilles complets des leaders lents (dex principal + `xyz`) ; nouveau collecteur `l2-leaders`
  (15e, carnets L2 + BBO de 180 coins dont 60 HIP-3, liste régénérée par `tools/generer_coins_lanes.py`,
  chaque nom vérifié par `collection/univers_perps.py`). Essais bornés réels : 180/180 coins servis.
- AlinaSync rapatrie aussi les lanes marché et contexte (`tools/telecharger_lanes_certifiees_github.py`).
- Moteur / labo : parité d'exécution taker vérifiée (`tests/test_parite_execution_labo_moteur.py`) ;
  ordre minimal de 10 USD imposé aux dimensionneurs ; simulateur `copy_vault_replication_paper.py`
  (350 USD, frais, écart, funding, ordre minimal) et modèle `copy_vault_leader_model.py`.
- Balayage complet terminé : 2 333 vaults (1 859 fermés, 474 ouverts), 556 247 points, 0 échec ;
  certifié (164 911 lignes gardées, 0 écartée).
- Persistance sur cet univers élargi (PnL recalé, 86 dates hebdomadaires, 28 configurations) :
  **`MORE_DATA`**. Analyse primaire (étude v2, voir défaut ci-dessous) : corrélation de rang +0,017
  [−0,037 ; +0,061] ; meilleur quantile moins « copier tout le monde » −2,06 bps/jour
  [−17,21 ; +11,56], placebo p = 0,595. Leaders lents (789 vaults) : +0,91 bps/jour [−10,85 ; +14,32].
  Modèle de sélection appris en marche avant : corrélation −0,002 [−0,064 ; +0,061]. Lecture : aucun
  signe que le classement passé d'un vault prédise son rendement suivant, dans un sens ou dans l'autre.
  En journalier (19 à 27 dates), quatre configurations ont p < 0,05 avant coûts ; aucune ne passe la
  correction de multiplicité (seuil 0,0018) et leur net après coût de réplication est négatif.
  Rapport : `runtime/reports/copy_vault_quant_lab/copiabilite/20261111T171005095477Z-persistance/`.
- **Défaut corrigé dans l'étude de persistance (v1 → v2).** La note « bayésienne » de l'analyse
  primaire dégénérait (toutes les notes égales) sur 57 dates sur 86 : le « meilleur quantile » était
  alors les premiers vaults dans l'ordre des adresses, et la corrélation de ces dates disparaissait
  sans trace. Le premier résultat publié (−13,59 bps/jour, p = 0,976) venait de cet artefact, pas des
  données. Correction : estimateur à effets aléatoires pondéré par la précision, égalités départagées
  en espérance (jamais par l'ordre du tableau), vaults inactifs hors univers, dates dégénérées
  comptées dans le rapport (0 désormais). Tests : renommer les vaults ne change plus aucun résultat.
- Certificateur : deux vérifications du magasin de ticks qui se croisent ne donnent plus
  `database is locked` (attente de 60 s, puis renoncement propre et journal explicite).
- POUSSER / AlinaSync : en mode UTF-8, le message français de `tasklist` faisait échouer la lecture
  et un processus correctement arrêté était déclaré survivant ; corrigé, test de régression ajouté.
- Réplication 350 USD = `MORE_DATA` : aucune journée où le leader est observé ≥ 90 % du temps.
- Magasin de ticks : 281 046 shards vérifiés (27,17 Go), 0 anomalie, état PARTIEL (2 394 dossiers
  restants ; la vérification reprend là où elle s'est arrêtée).
- POUSSER : aperçu à blanc corrigé (`git diff` n'accepte pas `--pathspec-from-file`).

**Troisième séquence du 2026-11-11 (mission additionnelle : collecteurs, certificateur, labo) — travail LOCAL, ni commité ni poussé (tout ce qui suit est postérieur au commit `bb41b323`) :**

- **Pourquoi la copie de fills perd (mesuré sur 4,8 M de fills observés).** 67 % des fills des
  leaders sont PASSIFS : ils gagnent l'écart (−5,2 bps) puis le reperdent en sélection adverse
  (−5 à −7 bps), soit à peu près zéro avant frais. Les fills AGRESSIFS sont suivis d'une dérive dans
  leur sens, mais 7,6 bps sont déjà partis quand le fill est observé. D'où trois pistes : ne suivre
  que les décisions agressives à horizon long, lire les ordres AVANT leur exécution, allonger
  l'historique pour pouvoir trancher.
- **Historique de prix : de 17 à 208 jours.** `candleSnapshot` ne garde que 5 000 bougies par
  intervalle. `tools/backfill_candles_vaults.py` tire maintenant aussi les bougies 1 h (208 jours)
  et le funding horaire (`fundingHistory`), de façon incrémentale, avec une cadence réellement
  respectée. Défauts corrigés au passage : les coins étaient mis en majuscules (`KPEPE`,
  `XYZ:XYZ100` : refusés par l'API, donc aucun prix pour les k-coins et les marchés HIP-3), la
  pause entre requêtes était calculée mais jamais appliquée, et sans fichier de fills le collecteur
  ne faisait rien. Rubans : `runtime/history/candles_1h.jsonl`, `runtime/history/funding_1h.jsonl`.
- **Nouvelle donnée : les ordres en attente des leaders.** Vérifié en lecture seule : `openOrders`
  (WebSocket) et `frontendOpenOrders` (REST) sont publics pour toute adresse ; 12 leaders sur 25 en
  avaient (1 742 ordres : entrées limites, prises de profit « reduce only », stops). La lane
  contexte s'y abonne (`tools/collecter_contexte_lane.py` → `copy_vault_orders_lane.jsonl`), écrit
  sur changement (30 s au plus fin, espacement adaptatif pour les comptes qui cotent en continu,
  carnet résumé au-delà de 200 ordres, carnet vide écrit comme preuve de suivi). Essai réel de
  7 minutes : 60 carnets, 10 leaders, dex principal et `xyz`, 0 reconnexion.
- **Certificateur** : familles `leader_orders` et `funding_history`, bougies 1 h (`candle`, une
  bougie sans intervalle est refusée) ; registre de couverture, workflow des lanes contexte et
  rapatriement AlinaSync alignés.
- **Laboratoire** (`tools/etude_copiabilite.py`, tous branchés dans le mode `copiabilite` du lanceur) :
  `--ouvertures` (étude d'événements des décisions agressives : décisions et non fills, entrée
  après observation, témoins à −7 et −14 jours, verdict lu seulement sur les décisions OBSERVÉES EN
  DIRECT, compte de 350 USD en 5 lignes) ; `--ordres` (part des exécutions visible à
  l'avance, borne haute d'un ordre jumeau) ; `--retrospectif --bougies 1h` ; `--plan` (classe les
  hypothèses du registre par valeur attendue et jours de données manquants, a priori sceptique,
  lecture en quatre cas : prometteur, fragile, données insuffisantes, absence d'avantage démontré).
  Le chargeur de portefeuilles réunit maintenant le dex principal et les dex HIP-3 d'un compte.
- **Mesures du soir (toutes au registre `EXPERIENCES.ndjson`, plan dans `PLAN_DE_RECHERCHE.md`) :**
  - 825 037 bougies 1 h certifiées (180 coins, 0 échec) : le coffre couvre 213 jours.
  - Ouvertures agressives : **`MORE_DATA`** — 4 jours observés en direct seulement (1 278 décisions,
    59 leaders). Estimation provisoire NÉGATIVE : brut −16,1 bps, net −26,9 bps par décision à 4 h,
    espérance −2,98 USD/jour pour 350 USD. Un intervalle étroit sur 4 jours ne vaut ni rejet ni
    promotion : il en faut 30.
  - Réplication lente rétrospective sur 208 jours de prix (33 vaults, 91 jours en marche avant) :
    +1,48 bps/jour, t = 0,03 ; aucun vault significatif après correction. Toujours `MORE_DATA`,
    mais douze fois plus d'histoire ne fait apparaître aucune compétence d'inventaire persistante.
  - Ordres en attente : chaîne validée sur données réelles (60 carnets certifiés, 392 ordres
    distincts) ; `MORE_DATA` faute de fills observés pendant ces 7 minutes.
- **Défauts de collecte trouvés par ces mesures et corrigés :**
  - Le rattrapage des fills jetait le drapeau agressif/passif (`crossed`), les frais et le PnL
    réalisé : 208 000 fills historiques ne permettaient pas d'isoler une décision agressive.
    `collection/vault_fills_backfill.py` les conserve ; le labo préfère, à instant d'observation
    égal, le relevé qui connaît ce drapeau.
  - `Limiteur.attente()` calcule une pause mais ne dort pas, et quatre collecteurs l'appelaient
    ainsi (`backfill_vault_fills`, `collecter_carnet`, `scanner_liquidations_confirmees`, l'ancien
    `backfill_candles_vaults`). Dernier passage réel du rattrapage des fills : 1 219 fenêtres de
    dépôts/retraits sur 2 250 refusées en HTTP 429. Ajout de `Limiteur.patienter()` et
    `prendre_la_pause()`, cadence calée sur le budget de débit (20 unités par requête, 600 par
    minute), un nouvel essai après un refus, et une garde de test
    (`tests/test_cadence_reellement_respectee.py`) qui interdit toute pause calculée puis jetée.
    Preuve réelle après correction (2 leaders, lecture seule) : 180 fenêtres de dépôts/retraits,
    0 refus ; 26 153 fills d'un leader sur 30 jours, 0 fenêtre en échec, drapeau agressif et frais
    présents sur tous. Le passage complet (`backfill-fills`) attend le fichier de scores produit
    par `scorer-vaults` : il se fera au prochain lancement des collecteurs.
  - Funding horaire : 148 000 points certifiés pour les 29 coins les plus importants ; les autres
    suivent automatiquement, passage après passage.
- **Suite complète rejouée (16 tranches, 17 730 tests)** : 11 échecs, tous traités — 2 décodages
  en mode UTF-8, 2 tests du verrou de campagne à aligner sur la règle « jour dense », 1 échec
  silencieux, 1 lancement de pytest non isolé dans `tools/revalider_receipts.py`, 4 tests relancés
  pendant une édition ; `rig_020` repassé au vert après revalidation des reçus (50 sur 50).
- **Reprise du soir (code ajouté après cette suite, vérifié par tests ciblés) :**
  - `tools/backfill_vault_fills.py` tient aussi l'historique de fills des **leaders lents** désignés
    par le labo (`runtime/data/leader_fills_backfill.jsonl`, famille `fills_backfill`) : 200 jours,
    pagination AU CURSEUR (vérifié sur l'API : réponses triées par instant croissant, une page pleine
    contient les fills les plus anciens ; une requête par 2 000 fills), incrémental, quota de pages
    par leader, budget de temps par passage, curseur qui n'avance qu'après une pagination menée au
    bout. Premier passage réel : 25 leaders sur 91 en 40 minutes, 18 complets, 267 713 fills avec
    leur côté agressif, 7 comptes trop actifs laissés au suivi en direct ; la suite est automatique.
    Ce ruban ne passe ni par la liste « retenus » ni par le pipeline de copie : il sert au labo.
  - **Labo principal (double-clic sur `LANCER_LAB_QUANT_COPY_VAULT.cmd`) : il n'aboutissait plus.**
    Avec 8,5 millions de fills au coffre (deux jours de robots à haute fréquence), il occupait
    21 Go sur 32 et s'enlisait dans la pagination mémoire. Trois corrections, mesurées sur les
    données réelles : (1) les fills des adresses classées `ARCHIVE` par le plan du labo — robots
    HFT et clones, la même classe que celle qui ralentit leur collecte — ne sont plus rejoués par
    la recherche principale (5,0 millions écartés AVANT décodage ; ils restent au coffre et servent
    à l'étude de copiabilité) ; (2) les signaux de contexte que rien ne lisait sont comptés sans
    être gardés en mémoire ; (3) les rubans de travail sont écrits en flux au lieu d'une chaîne
    géante. Étape 1 : 369 s (elle ne finissait plus), pic 16 Go avec 4 Go libres.
  - **Budget de débit de l'API partagé entre collecteurs.** Essai réel du vrai lanceur
    (12 minutes, sans déclenchement cloud) : 218 refus « 429 » relevés, chez presque tous les
    collecteurs. Causes : les deux rattrapages prenaient chacun la moitié du budget, et le
    collecteur de vaults envoyait 69 vaults puis 182 portefeuilles sans pause. Corrections :
    rattrapages ramenés à un douzième du budget chacun (ils sont incrémentaux : lents, sans
    conséquence), dépôts/retraits demandés par semaine au lieu de par jour (sept fois moins de
    requêtes), cadence pondérée par le poids dans le collecteur de vaults
    (`BUDGET_VAULTS_PAR_MINUTE`, `collecte_fiable.CadencePonderee`). Essais suivants : 77 puis
    39 refus, concentrés dans les premières minutes ; ensuite le suivi des fills, qui a sa propre
    régulation adaptative, se cale sur le débit restant.
  - **Un refus de débit ne fait plus perdre un relevé.** Les collecteurs de vaults et de
    liquidations abandonnaient la mesure au premier « 429 » (6 vaults sur 69 absents d'une
    passe). `collecte_fiable.reprendre_apres_refus_de_debit` attend puis réessaie (trois essais,
    délai indiqué par le serveur respecté).
  - **Portefeuilles des leaders lents relevés en tête et en fin de passe.** L'étude de
    réplication écarte un portefeuille de plus de 15 minutes ; relevés une fois après les vaults,
    ils ne revenaient que toutes les 13 minutes environ.
  - **Collecteur de carnets : une requête refusée (« 400 ») à chaque passe.** La règle « commence
    par K » prenait `KAS` (et `KAITO`) pour un « k-token » et demandait à Binance le contrat
    inexistant `1000ASUSDT`. La liste des marchés cotés par milliers est maintenant explicite
    (`HL_KILO_COINS`, lue dans l'univers Hyperliquid), et Hyperliquid reçoit le nom natif
    (`kPEPE`, jamais `KPEPE`).
  - **Labo principal : chaque décision rejouée reparcourait tout le carnet de son marché.**
    Relevé de pile sur le labo en marche (`py-spy`) : `execute_metaorder` refaisait une dizaine
    de parcours complets de la liste des carnets (plusieurs centaines de milliers de lignes)
    pour en lire trois. L'exploration automatique de 128 variantes ne se terminait pas en une
    heure. `copy_vault_book_index.py` calcule ces parcours une fois par liste (points de
    contrôle, carnets continus, horodatages), vérifie avant chaque usage que la liste n'a pas
    changé, et ne retient aucune liste abandonnée par son appelant. Preuve d'égalité : moteur
    d'origine contre moteur indexé sur 201 804 cas tirés au hasard (13 453 trades, tous les
    types de refus, exceptions, listes modifiées en place) : aucun écart. Même correction dans
    `copy_vault_v21_frozen._reference_depth_features` (36 000 comparaisons, aucun écart).
  - **Exploration « overshoot » : plus jamais jouée à vide.** Le ruban de contexte de marché du
    corpus certifié est vide ; l'exploration rejouait donc 256 fois le corpus pour des variantes
    toutes identiques (le filtre ne bloquait rien) et comptait 96 essais sans objet.
    `explorer_si_le_contexte_existe` la refuse dans ce cas ; le rapport porte
    `overshoot_exploration: SKIPPED — NO_ASSET_CTX_POINTS`. Piste ouverte : le contexte de marché
    du coffre LOCAL (collecteur local) n'alimente pas encore cette exploration.
  - **Résultat : le passage unique du labo principal va au bout.** Mesuré dans la nuit du 11 au
    12 : code 0, 128 essais, rapport écrit
    (`runtime/reports/copy_vault_quant_lab/20261111T230757529928Z/`), 81 minutes avec un essai
    des collecteurs et la suite de tests en parallèle (environ 50 minutes seul : vérification
    8 min, épisodes 4 min, cycles 10 min, puis 15 s par essai). Verdict du passage : aucun
    candidat gelé, rien de prouvé — 298 852 signaux dont 40 950 mesurables sur 6 jours.
    Attention à la mémoire : le labo occupe 16 Go pendant sa recherche ; une autre charge lourde
    en parallèle le fait passer sur le fichier d'échange (essais à 145 s au lieu de 15 s).
  - **Suivi des fills : poids réel compté, débit local plafonné.** L'API facture 1 unité par
    20 lignes en plus de la requête : une page pleine coûte six requêtes. Le régulateur
    (`TokenBucket.charge`) débite maintenant ce poids ; sans cela, le rattrapage d'un retard au
    redémarrage (19 412 fills en une passe) dépassait la limite et tous les collecteurs
    recevaient des refus. Sur ce PC, le suivi est plafonné à 30 requêtes par minute
    (`tools/_run_poll_leaders.cmd`) ; les lanes cloud, chacune sur sa propre adresse, gardent 55.
  - `--ouvertures` porte une seconde hypothèse, `copy_vault_aggressive_open_selected_leaders` : ne
    suivre que les leaders dont les décisions agressives PASSÉES et déjà dénouées ont rapporté après
    coûts (note ramenée vers zéro, 20 décisions au moins). Comparaison appariée par jour :
    retenues, éligibles, écartées.
  - `--ordres` rejoue un **ordre jumeau** de façon prudente : posé après le délai de réaction, exécuté
    seulement si une clôture traverse strictement le prix limite, maintenu jusqu'à ce que
    l'annulation du leader ait pu être constatée ; non-exécutions comptées.
  - `--positions` lit le portefeuille entier (dex réunis) ; le premier relevé d'un dex ne crée
    aucun événement de position (les positions révélées existaient déjà).

**Vérifié dans la nuit du 11 au 12 novembre (état local, non commité) :**
- Lanceur des collecteurs, essai réel de 15 minutes (GitHub CLI retiré du PATH : aucune lane
  cloud déclenchée) : 33 refus de débit contre 218 au premier essai, aucune requête invalide,
  aucun relevé perdu (vaults 69/69, portefeuilles 176/176 en tête et en fin de passe,
  liquidations 162/162) ; arrêt propre, aucun processus de collecte restant. Les refus restants
  tombent au démarrage, quand le suivi des fills rattrape son retard ; ils sont réessayés.
- Certificateur : 341 169 données gardées, aucune écartée ; coffre LOCAL : 33 987 063 données,
  878 coins, 213 jours.
- Labo, passage principal : au bout, code 0 (voir plus haut). Labo, dix études de copiabilité :
  toutes code 0 ; registre vérifié (41 expériences). Verdicts : copie rapide et miroir
  `REJECTED` ; tout le reste `MORE_DATA` (ouvertures agressives : 5 jours, 2 210 décisions,
  73 leaders observés en direct ; il faut 30 jours). Priorité du plan : la collecte.

**12 novembre, midi — LE LABO TOURNAIT À VIDE (signalé par l'utilisateur, rapport « non mesurable ») :**
- **Constat.** Les 128 essais du passage de la nuit ont tous rendu « non mesurable » : sur la
  période d'entraînement, 504 signaux passaient les filtres et les 504 étaient refusés à
  l'exécution (259 `L2_CONNECTION_IDENTITY_INCOMPLETE`, 235 `STALE_OR_MISSING_EXIT_BOOK`,
  10 `STALE_OR_MISSING_ENTRY_BOOK`). Aucun réglage ne pouvait produire un trade.
- **Cause 1 — les carnets locaux n'avaient pas d'identité de connexion.** Le moteur n'exécute un
  trade sur des carnets continus que si référence, entrée et sortie viennent de la même connexion
  WebSocket et de la même époque de trou (`connection_id`, `l2_gap_epoch`). Ni
  `tools/collecter_userfills_vaults.py` (ruban `copy_vault_l2_tape.jsonl`) ni
  `tools/collecter_l2_lane.py` (lanes locales ET cloud) ne les écrivaient : 1,2 million de carnets
  au coffre, tous refusés. Les deux les écrivent maintenant, avec la règle du collecteur de
  référence (époque +1 à chaque déconnexion, trame rejetée ou réabonnement ; jamais sur un simple
  silence). **Les carnets collectés avant ne pourront jamais servir à l'exécution** (l'identité
  n'a pas été enregistrée ; on ne l'invente pas).
- **Cause 2 — les carnets de lane n'avaient pas de capacité.** Le chargeur du labo exige
  `capacity_usd` : 93 054 carnets de lane écartés au chargement. Calculée maintenant comme dans
  le collecteur principal (plus petit des deux côtés sur cinq niveaux).
- **Cause 3 — le repli BBO perdait l'identité** dans le chargeur du labo
  (`copy_vault_book_loader`) : corrigé.
- **Chaîne par le coffre prouvée** (le labo lit le coffre, pas les fichiers bruts) : test de bout
  en bout collecteur → Certificateur → coffre LOCAL → pont du labo → ruban → moteur → trade
  exécuté (`tests/test_lab_coffre_injection.py`), et relecture du coffre réel après un essai du
  lanceur : 13 928 carnets de lane, 174 du collecteur principal et 13 928 BBO, tous avec identité.
- **Le labo ne cherche plus à vide.** `copy_vault_train_executability.sonder_train` rejoue les
  signaux de la période d'entraînement avec les règles d'exécution canoniques, sans filtre de
  stratégie, à chaque horizon exploré. Aucun trade exécutable → `MORE_DATA /
  TRAIN_NOT_EXECUTABLE`, zéro essai lancé (donc zéro essai compté dans la multiplicité), et le
  rapport liste les refus par motif avec ce qu'il faut pour les lever.
- **Rapport rendu honnête.** « +3,30 USD/jour — la meilleure stratégie prouvée » était une
  vieille estimation d'entraînement (le réglage gelé ne peut pas être rejoué sur ce capital) :
  libellée comme telle. Plus de « En attente du premier essai » après des essais ; plus de
  « paliers de gain prouvé » pour des valeurs illisibles.
- **Autres corrections de la matinée.** Le classement des vaults relit l'historique archivé des
  sessions (73 vaults, 11 retenus dès le démarrage, contre 0) ; le rattrapage des vaults retenus
  pagine au curseur (une requête par 2 000 fills au lieu d'une par jour) et demande les
  dépôts/retraits en une fenêtre ; les rattrapages cèdent la place dès qu'un collecteur en direct
  est refusé (fichier-témoin `ALINA_SIGNAL_DEBIT`, posé par le lanceur) ; l'étape 1 du labo tourne
  dans un processus fils (mémoire rendue), les épisodes ne sont plus reconstruits deux fois, et
  la copie de carnets par candidat qui annulait l'index est supprimée.
- **Essai du lanceur (15 min) :** 32 refus de débit, aucun chez les collecteurs de vaults, de
  liquidations, de carnets ni dans le suivi des fills ; aucune requête invalide ; arrêt propre.

**CE QU'IL FAUT POUR QUE LE LABO MESURE QUELQUE CHOSE :** des jours de collecte continue avec
les collecteurs corrigés — au moins six jours denses, avec des carnets qui couvrent l'entrée ET
la sortie des positions. En pratique : pousser (décision de l'utilisateur) pour que les lanes
cloud collectent des carnets exécutables, ou laisser tourner le lanceur local.

**Limites connues :**
- Tous les collecteurs locaux partagent une adresse IP : il reste des refus de débit au
  démarrage (réessayés, sans perte mesurée).
- Le lanceur certifie avant de démarrer : 1 min 30 à 3 min avant la première donnée.
- Les cotations de `bbo_tape.jsonl` (collecteur cross-venue) n'ont pas d'époque de trou : elles
  aident à dater un signal mais ne peuvent pas exécuter un trade.
- L'exploration overshoot reste sautée tant qu'aucun contexte de marché certifié ne couvre les
  signaux.

**À faire en premier à la reprise :** (1) pousser (décision de l'utilisateur) ; (2) après chaque
passage des collecteurs, Certificateur puis labo ; (3) surveiller dans le rapport du labo le
bloc « Aucun trade exécutable » : il doit disparaître quand la période d'entraînement contient
des carnets avec identité.
Ne pas lancer `git status` sur ce dépôt sans borne de temps : il dépasse 10 minutes.

**Reste ouvert (liste antérieure, points 1 à 3 traités ci-dessus) :**

1. Une passe `tools/collecter_vaults.py --une-fois` (lecture seule), puis `Certificateur Coffre
   Fort.cmd`, puis `LANCER_LAB_QUANT_COPY_VAULT.cmd copiabilite` → premier verdict de persistance.
2. 61 % du notionnel des leaders porte sur des coins HIP-3 (`xyz:`) sans carnet collecté ;
   `config/copy_vault_coins.json` n'en contient aucun et n'a pas de générateur. À ajouter aux lanes
   seulement après validation en direct du nom d'abonnement `l2Book`.
3. Univers de vaults suivis = survivants (ouverts, TVL ≥ 100 k USD, ≥ 45 jours) : conserver aussi les
   vaults fermés de la liste publique pour mesurer le biais de survie.
4. Le labo ne retire pas encore les robots HFT ni les adresses clones de ses signaux, alors que le
   moteur les refuse : parité d'univers à établir avant toute lecture statistique (pseudo-réplication).
5. Non traités dans cette session : parité complète labo ↔ moteur sur un même jeu d'événements,
   reliquat de vérification du magasin de ticks, durcissement d'AlinaSync et de POUSSER.

## 0 ter. FEUILLE DE ROUTE COMPLÈTE — collecteurs parfaits + labo qui trouve un vrai avantage vite (2026-11-12)

**Honnêteté d'abord (cadre non négociable).** Aucun gain n'est inventé. À ce jour **aucune
stratégie n'a de valeur attendue positive prouvée** ; le réglage « +3,30 USD/jour » affiché était
une vieille estimation d'entraînement non rejouable. « Des résultats ultra-rapides et fortement
positifs » ne se décrètent pas : ils ne peuvent venir que (a) de données **complètes et
exécutables** (la cause du blocage du 12/11 : carnets sans identité de connexion, sans carnet de
sortie), et (b) d'une recherche **assez intelligente** pour isoler un avantage réel s'il existe et
le déclarer vite, ou prouver vite qu'il n'existe pas. Les deux listes ci-dessous (≈ 110 + ≈ 110
tâches) sont le plan pour atteindre ce point le plus vite possible. Chaque tâche est **concrète,
propre à ce dépôt, et testable**. Priorité = ⚡ (débloque la mesure / gros levier), 🔧 (robustesse),
🔬 (finesse), 📊 (observabilité).

**Le verrou actuel, en une phrase :** le labo ne peut rien mesurer tant que la période
d'entraînement ne contient pas de signaux dont les carnets couvrent **référence (−30 s) + entrée
(+60 s) + sortie (+horizon)** avec une **identité de connexion continue**. Tout le reste est
secondaire tant que ce verrou n'est pas levé par plusieurs jours de collecte avec les collecteurs
corrigés ce jour.

---

### 0 quinquies. RITUEL DE FIN DE CAMPAGNE — les 7 questions, toujours les memes

Idee reprise de `kepano/40-questions` (un jeu de questions FIXES qu'on se repose a date
reguliere), adaptee a un laboratoire. Pourquoi des questions fixes : un bilan improvise raconte
ce qui s'est bien passe. Des questions imposees d'avance forcent a regarder ce qu'on prefererait
ne pas voir — et permettent de COMPARER deux campagnes entre elles.

A remplir a la fin de CHAQUE campagne, avant toute nouvelle collecte, et a dater.

1. **Qu'est-ce qui a ete MESURE ?** Un chiffre, une fenetre, une methode. Pas une impression.
   Si la reponse ne contient aucun nombre, la campagne n'a rien mesure.

2. **Qu'est-ce qui a ete REFUTE ?** Une campagne qui ne tue aucune hypothese n'a rien appris.
   Nommer les hypotheses mortes et le chiffre qui les a tuees (ex. : fast_follow REJETE a tous
   les horizons <= 300 s meme a spread nul ; DeepLOB -4 242 bps net).

3. **Qu'est-ce qui reste NON MESURABLE, et pourquoi ?** Distinguer « mesure et negatif » de
   « pas mesurable ». Les confondre est la faute la plus couteuse de ce projet.

4. **Quelle part des donnees collectees a reellement servi ?** Un flux collecte et jamais lu est
   du cout sans benefice : soit on le branche, soit on arrete de le collecter.

5. **Combien de JOURS ACTIFS par segment et par regime ?** C'est le levier dominant (√n au
   denominateur). Un segment a 2 jours n'est pas « valide », il est non mesurable — le dire.

6. **Qu'est-ce que j'ARRETE ?** Au moins une chose : un flux, une piste, une section de ce
   document. Sans cette question, la feuille de route redevient un grenier (lecon du 14/11).

7. **Quelle est la SEULE prochaine mesure qui changerait une decision ?** Une seule. Si on n'en
   trouve pas, le probleme n'est pas les donnees : c'est qu'aucune decision n'est en attente.

**Regle de reponse** : chaque reponse porte sa date et sa source (fichier, commande, chiffre).
Une reponse sans source est une opinion, et une opinion n'entre pas dans ce document.

### 0 sexies. OU SONT PASSEES LES LISTES D'IDEES — `docs/ROADMAP_ARCHIVE.md`

Le 14/11, environ **1 350 lignes** de listes d'idees ont quitte ce document pour
`docs/ROADMAP_ARCHIVE.md` : les ~110 taches collecteurs, les ~110 taches labo, les programmes
A-H, les 200 taches « bot parfait », les chantiers issus de la recherche web, les 300
ameliorations parametrees, les 200 gisements d'edge (GIS1-GIS200) et les 100 ameliorations du
collecteur (K1-K100).

**Pourquoi.** Elles n'avaient jamais ete commencees. A 2 707 lignes pour ~920 taches dont une
dizaine faites, ce document ne servait plus a decider : il cachait ce qui compte sous ce qui ne
compte pas. **Rien n'est perdu** — tout est dans l'archive, consultable.

**Ce qui a ete fait parmi elles est reste ici**, dans les sections datees : K1 (collecteur REST,
8 -> 220 leaders), la resilience memoire, la reconciliation des carnets, la sonde par segment,
la certification en continu, le controle qualite.

**Comment une idee revient.** Une a la fois, quand les donnees permettent de la MESURER, avec
sa date de sortie d'archive et son premier pas mesurable. Jamais en bloc.

### C. CE QUI A ÉTÉ FAIT LE 12/11 (déjà en place, non commité)

1. **Carnets exécutables** : `connection_id` + `l2_gap_epoch` + `capacity_usd` écrits par
   `collecter_l2_lane.py` (lanes locales ET cloud) et `collecter_userfills_vaults.py` (ruban
   principal) ; identité transmise par le repli BBO du chargeur ; prouvé de bout en bout par le
   coffre (`test_lab_coffre_injection`, `test_l2_lane`, `test_collecter_userfills_vaults`).
2. **Sonde d'exécutabilité** `copy_vault_train_executability.sonder_train` : le labo ne lance plus
   d'essais quand aucun trade n'est exécutable en TRAIN ; motifs détaillés.
3. **Rapport honnête** : « non mesurable » expliqué, vieille estimation étiquetée non prouvée,
   refus listés par motif, plus de « En attente du premier essai » après des essais.
4. **Classement des vaults** relit l'historique archivé (73 vaults, 11 retenus dès le démarrage).
5. **Rattrapage des vaults retenus** paginé au curseur (une requête par 2 000 fills).
6. **Signal de congestion** `ALINA_SIGNAL_DEBIT` : les rattrapages cèdent la place au direct.
7. **Mémoire du labo** : étape 1 dans un processus fils (mémoire rendue), épisodes mémorisés entre
   étapes, index des carnets non recopié par candidat.
8. **Débit** : rattrapages à 1/12 du budget, suivi des fills plafonné à 30/min en local, poids réel
   des grosses réponses compté, reprise après 429 (4 essais). Essai du lanceur : 32 refus (vs 218).
9. **Carnet de sortie garanti (C23)** : `TAPE_COIN_TTL_MS` passait de `min` à `max(HORIZONS_MS)` —
   un coin reste abonné au carnet ~1 h après le dernier fill (couvre la sortie à tout horizon). Avant,
   désabonnement après ~2 min : 235 des 504 signaux TRAIN refusés `STALE_OR_MISSING_EXIT_BOOK`.
10. **Abonnement HIP-3 validé en direct (C21)** : `l2Book` renvoie bien un carnet pour `xyz:XYZ100`,
    `xyz:SP500` (casse native exacte ; `XYZ:XYZ100` échoue). La liste commitée a déjà 60 coins HIP-3
    en bonne casse ; l'essai du lanceur capture des carnets `xyz:` avec identité.
11b. **Budget de débit PARTAGÉ entre collecteurs (C1)** : `collecte_fiable.reserver_poids` — fenêtre
    glissante (horodatage, poids) dans un fichier commun protégé par verrou, posé par le lanceur
    (`ALINA_BUDGET_DEBIT`). FAIL-OPEN total (toute erreur → on passe), attente bornée à 8 s, vol de
    verrou périmé : jamais de blocage ni d'interblocage. Inactif sans la variable (tests, lanes cloud
    sur IP séparées, outil manuel). Câblé dans vaults/liquidations/carnet/overshoot (avant chaque
    requête). Actif au prochain cycle de collecte. C'est le vrai remède aux « 429 » de démarrage (les
    collecteurs partagent une seule IP de 1 200 u/min). Prouvé : `test_collecte_fiable` (8 cas :
    inactif, sous/sur seuil, purge de fenêtre, deux process, fichier corrompu, vol de verrou, plafond).
11. **BOUCLE D'EXÉCUTABILITÉ labo → collecteurs (C64/C65/L5/C82)** : `sonder_train` ventile
    l'exécutabilité **par coin** (`par_coin`, `coins_a_collecter` classés par signaux bloqués). Le
    rapport du labo affiche « Coins à collecter en priorité » ; `generer_coins_lanes.py` lit cette
    carte dans le dernier `resultat.json` (`coins_bloquant_la_mesure`) et cible EXACTEMENT ces coins,
    avant le classement par notionnel. Le labo dit aux collecteurs quoi collecter pour redevenir
    mesurable, coin par coin. Prouvé : `test_copy_vault_train_executability`,
    `test_univers_perps_et_coins_lanes`, `test_alina_quant_lab_console`.
12. **Jauge en une commande** `tools/etat_executabilite.py` : lit le dernier rapport et dit en clair
    « mesurable ou non », les refus par motif, et les coins à collecter — pour suivre le recul du
    blocage pendant les jours de collecte, sans ouvrir le HTML.

13. **M0 — GOUVERNEUR DE MEMOIRE (exigence « jamais crasher »)** : `hl_observer/ops/budget_ram.py`
    etendu (ADDITIF, aucune signature changee, `lab_alpha` intact). Publie un NIVEAU de pression
    VERT/ORANGE/ROUGE et une DECISION CONTINUER/RALENTIR/REDUIRE/PAUSER. Deux criteres combines (on
    prend le PIRE) : seuil ABSOLU en Go et seuil RELATIF en fraction — un seul des deux se trompe
    systematiquement sur l'autre classe de machine. Seuils reglables par environnement
    (`ALINA_RAM_SEUIL_ORANGE_GO`, `ALINA_RAM_SEUIL_ROUGE_GO`). `assez_de_memoire_pour()` applique une
    marge x1,5 (une estimation de besoin memoire est toujours optimiste) ; `reduire_ampleur()` retrecit
    par palier sans JAMAIS tomber a zero ; `attendre_que_ca_respire()` est BORNEE (jamais de blocage) ;
    `journal_memoire()` donne la ligne d'observabilite. FAIL-OPEN total : ne leve jamais, meme avec un
    psutil casse ou absent. Un Ctrl+C, lui, se propage (lecon deja payee sur les collecteurs).
    **Preuve sur la machine reelle** : 15,63 Go libres = VERT, mais une demande de 16 Go -> REDUIRE —
    exactement le cas qui a tue le labo deux fois. Prouve : `test_gouverneur_memoire` (23 cas).
14. **M1 — GOUVERNEUR BRANCHE sur l'etape 1 du labo** (`tools/labo_materialiser_safe.py`, le processus
    qui pique a 16 Go et que l'OS a tue deux fois). Controle de pression A INTERVALLE (20 s) et non a
    chaque message — cette etape en emet des milliers et lire la RAM coute ; respiration BORNEE si
    ROUGE puis on continue en mode degrade ; etat memoire journalise avant/apres ; `MemoryError`
    rattrapee et convertie en message EXPLOITABLE + code de sortie 3 (« reduisez l'ampleur, ce n'est
    pas un bug ») au lieu d'une trace de pile. Prouve : `test_labo_materialiser_memoire` (12 cas, dont
    **2 CANARIS AST** qui exigent l'APPEL reel du gouverneur et le rattrapage de `MemoryError` —
    MENTION != PORTE, le projet a deja paye cette lecon avec 23/25 gardes morts).
15. **M1 — CACHE D'INDEX DE CARNETS borne en VOLUME, plus seulement en nombre**
    (`backtesting/copy_vault_book_index.py`). Deux defauts corriges : (a) `MAX_LISTES` bornait un
    NOMBRE de listes — 1024 listes de centaines de milliers de carnets ne sont pas bornees en octets :
    le plafond suit desormais la pression (`plafond_listes()`, plancher `PLAFOND_MINI_LISTES` pour ne
    jamais annuler le cache qui a sauve le labo le 11/11) ; (b) au plafond il faisait `clear()` — il
    jetait aussi le chaud, creant une falaise de performance : il EVINCE maintenant les plus anciennes
    jusqu'a repasser sous le plafond. La pression est lue UNIQUEMENT sur le chemin froid (quand le
    plafond est atteint) : `index_des_carnets` est appele une fois par decision rejouee, y lire la RAM
    couterait plus que le cache ne fait gagner. Pas de LRU reordonne a chaque acces, volontairement :
    ce sont toujours les memes quelques listes, et l'eviction par compteur de references deja presente
    est plus precise qu'une recence. La garantie du module tient : evincer ne change JAMAIS un resultat.
    Prouve : `test_book_index_plafond_adaptatif` (12 cas, dont un test de non-lecture sur chemin chaud).

16. **S1.3 / R2 — ORDRES DES LEADERS EN LOCAL, et surtout ALIGNES SUR LES FILLS.** Le diagnostic initial
    (« il manque les donnees d'ordres ») etait FAUX : trouve par inspection du code, la lane d'ordres
    suivait `config/copy_vault_leaders.json` (liste partagee, alimentee par l'explorer) tandis que le
    collecteur de fills LOCAL suit sa PROPRE selection (<=10 slots WS : CORE + sentinelles + rotation).
    Deux ensembles qui se recoupent a peine => des ordres d'un cote, des fills de l'autre, donc JAMAIS
    le couple ordre -> fill dont l'etude maker a besoin. Correctifs :
    * `tools/collecter_contexte_lane.py` : option `--leaders-source {fichier,fills}`. `fills` prend
      EXACTEMENT les comptes suivis pour les fills (reutilise `vaults_suivis`, source unique — un
      canari AST interdit de redupliquer la selection). Si cette selection est vide, repli sur la
      liste partagee **en l'annoncant** (un desalignement silencieux est ce qui a coute la mesure).
      Le recouvrement des deux ensembles est affiche. **Defaut inchange** (`fichier`) : les lanes
      cloud ne voient rien changer.
    * LIGNE DE VIE par minute dans la lane. Necessaire : l'entree de registre ne declare pas de
      fichier heartbeat (la lane n'en ecrit pas), donc le superviseur juge sa vie sur la FRAICHEUR DU
      LOG ; or elle n'ecrivait que sur changement — un marche calme aurait fait relancer un processus
      VIVANT (double collecte). Un canari lie les deux faits : pas de heartbeat => ligne de vie
      obligatoire, et on ne peut pas casser l'un sans voir l'autre.
    * `collecteur_registry` : entree `contexte-leaders` (22 -> 23 collecteurs) + profil **harvest**,
      avec `--leaders-source fills`, sessions bornees de 900 s, regle anti-relance verifiee.
    Prouve : `test_contexte_lane_alignement_fills` (14 cas, dont 3 canaris) + 97 tests de regression
    sur registre/superviseur/premier lancement.

17. **S1.6 / GIS1-GIS5 — « QUI MENE, ET DE COMBIEN DE MILLISECONDES », avec refus de conclure.**
    Etendu `src/hl_observer/research/price_discovery.py` (son propre docstring annoncait deja
    « Hayashi-Yoshida branchable plus tard ») : la couche d'origine travaillait sur des lags ENTIERS de
    barres deja alignees, incapable d'exprimer « Binance mene Hyperliquid de 700 ms ». La nouvelle
    couche implemente l'estimateur de **Hayashi-Yoshida** (concu pour des series echangees a des
    instants IRREGULIERS et NON synchronises : le cas des trades ; il ne reechantillonne pas, il somme
    les produits de rendements dont les INTERVALLES se chevauchent), balaye -2000..+2000 ms par pas de
    100 ms (methode sourcee), en O(n_a+n_b) par decalage. Trois points durement acquis :
    * **CONVENTION DE SIGNE explicite et testee.** Aligner une serie en retard exige de la decaler
      VERS L'ARRIERE. Une erreur ici aurait inverse la conclusion (« Hyperliquid mene Binance ») — la
      pire erreur possible. Un test verrouille le sens, un autre verifie que l'echange des roles
      inverse le signe.
    * **CRITERE DE DISTINCTION RELATIF, pas absolu.** Un seuil absolu se trompe toujours : sur 41
      decalages, du bruit produit facilement +0,12 d'ecart et donc un faux « lead ». Le pic doit se
      detacher de la DISPERSION de la courbe (MAD). Calibre sur cas construits : vrai lead = 11,7 a
      20,7 ecarts-MAD, bruit = 1,0 a 2,8 ; seuil fixe a 6, au milieu du fosse.
    * **CENTRE DU PLATEAU, pas l'argmax brut.** HY ne resout pas plus fin que l'intervalle entre ticks :
      autour du vrai decalage, une PLAGE est quasi equivalente. L'argmax brut choisissait le PREMIER
      point du plateau et sous-estimait (mesure : 100 ms annonces pour un vrai 300 ms). Le centre
      retrouve la valeur exacte (700 ms et 0 ms sur les cas construits). Et un plateau qui TOUCHE le
      bord du balayage declenche le refus `BORD_DU_BALAYAGE` — ce qui a rendu ce garde-fou VIVANT au
      lieu de code mort.
    Verdicts rendus : MESURE / SIGNAL_INSUFFISANT / PIC_NON_DISTINCT / BORD_DU_BALAYAGE /
    **ARTEFACT_HORLOGE_SUSPECTE** (decalage de la 1re moitie s'ecartant de >500 ms de la 2e — le faux
    positif exact contre lequel la source alerte : « un lead de 700 ms est trivial a fabriquer par
    derive d'horloge »). Prouve : `test_price_discovery_decalage_ms` (15 cas : decalage connu retrouve
    dans le bon sens, roles inverses, placebo serie-contre-elle-meme, series independantes refusees,
    horloge qui derive detectee, plateau, cadences differentes, entrees absurdes) + 37 tests de
    regression sur les consommateurs.

18. **S1.2 / A2 — PRE-CHAUFFER les carnets, et DEBLOQUER une liste de coins qui etait figee.** Deux
    defauts trouves en EXECUTANT l'outil sur les donnees reelles, pas en le relisant :
    * **toutes les sources etaient REACTIVES.** « Coins bloquant la mesure » et « coins sans carnet »
      nomment les marches ou les leaders ont DEJA trade sans carnet : quand un coin y apparait, ses
      signaux sont deja perdus. Or c'est le motif de refus n°1 (**77 008 signaux sur 98 138**). Ajout
      d'une troisieme source PREVENTIVE : `coins_habituels_des_leaders()` classe par NOTIONNEL les
      coins que les leaders viennent de trader (le meilleur predicteur de ce qu'ils vont trader),
      en lecture BORNEE de la queue du ruban de fills (cout independant de la taille du fichier).
    * **la liste etait SATUREE donc figee.** `composer` gardait tous les coins existants et n'ajoutait
      que dans la place restante : a 180 coins sur 180, l'execution reelle donnait « **0 ajoute, 117
      demandes hors plafond** » — la boucle labo -> collecteurs etait morte en pratique. Desormais les
      coins presents dans AUCUNE source cedent leur place, en partant du rang le plus bas, avec un
      plafond de `PART_MAX_DEPLACEE` (20 %) par passage pour ne pas abandonner un carnet qu'on vient
      de commencer, et les deplacements sont RAPPORTES. Un coin encore demande n'est jamais deplace.
      **Effet mesure sur les memes donnees : 36 coins ajoutes au lieu de 0** — exactement les marches
      HIP-3 que le labo reclamait (`xyz:BABA`, `xyz:PLTR`, `io:DRAM`...) et qui ne pouvaient plus entrer.
    Prouve : `test_coins_lanes_prechauffage` (16 cas) + les tests d'origine du generateur intacts.

19. **L2 — LA MEME SONDE SUR CHAQUE SEGMENT : « non mesure » n'est pas « valide ».** Trou de
    correction dans ce qui venait d'etre construit le jour meme : la sonde ne regardait que TRAIN,
    donc elle empechait de CHERCHER a vide mais pas de VALIDER a vide. Or un segment ou aucun trade
    n'est executable produit zero trade, donc zero perte, donc un resultat qui FRANCHIT les portes
    sans avoir rien mesure — un **faux PROVEN**, le mensonge exact que ce projet combat.
    * `copy_vault_train_executability` : ajout de `sonder_un_segment()` et `sonder_les_segments()`
      (le coeur `_sonder_univers` etait deja generique ; `sonder_train` est INCHANGEE, donc le labo
      et ses tests ne bougent pas). Rend, par segment train/validation/oos : signaux, executables,
      refus par motif, et `mesurable`. Plus `tous_mesurables`, `segments_non_mesurables`,
      `segments_absents_des_bornes` et une phrase lisible.
    * **Le refus est place dans `promotion_gate`**, pas dans le labo (fichier au plafond de taille) —
      et c'est de toute facon sa place : cette porte est deja deny-by-default. Une preuve FOURNIE et
      negative refuse TOUJOURS la promotion ; `CriteresPromotion.exige_segments_mesurables` permet
      d'exiger en plus que la preuve soit PRESENTE. Sans preuve et drapeau a False, le comportement
      d'origine est conserve : aucun appelant existant ne change de verdict.
    * Deny-by-default respecte : n'avoir RIEN sonde ne vaut pas « tout va bien » (`tous_mesurables`
      faux), et une preuve ambigue (`tous_mesurables` absent ou non booleen) vaut refus.
    Prouve : `test_executabilite_des_segments` (12 cas, dont « dossier parfait mais un segment non
    mesurable -> RESTE_PAPER ») + les 7 fichiers de tests de promotion existants intacts.

20. **C110 / C82 / C83 — RECONCILIATION EN DIRECT : la boucle de retour passe de SIX JOURS a DEUX
    SECONDES.** Jusqu'ici, savoir si la collecte serait exploitable exigeait : collecter des jours ->
    certifier -> lancer le labo (dizaines de minutes, 16 Go) -> decouvrir que 77 008 signaux sur
    98 138 n'avaient aucun carnet de reference. Nouveau module pur
    `src/hl_observer/collection/reconciliation_carnets.py` + outil `tools/reconciliation_executabilite.py`
    qui font ce constat DIRECTEMENT sur les rubans bruts, sans certification et sans labo.
    Verifie les TROIS carnets (reference / entree / sortie) et l'identite de connexion continue, avec
    un motif PRECIS par manque. Deux precautions qui evitent une jauge menteuse :
    * **le bon horodatage** : les carnets portent `received_at_ms` ET `exchange_ts_ms` ; le chargeur du
      labo retient la RECEPTION (`ts_ms=received`), donc la jauge fait pareil — sinon elle et le labo
      ne parleraient pas de la meme chose ;
    * **la fenetre observable** : on ne lit que la QUEUE des rubans, donc les fills anterieurs au
      premier carnet lu paraitraient tous « sans reference ». Artefact de lecture, pas defaut de
      collecte : ces fills sont ECARTES et comptes a part.
    Un canari AST interdit de recopier les seuils (ils sont importes du moteur), et la portee est
    declaree : CONDITIONS NECESSAIRES, jamais une promesse de PnL.
    **PREMIER RESULTAT SUR LES DONNEES REELLES, decisif : 573/687 fills (83 %) auront leurs trois
    carnets** — contre ~0 % d'executable sur le corpus historique. Les correctifs de collecte des
    11-12/11 FONCTIONNENT, et on le sait en deux secondes. La jauge nomme en plus les coupables :
    `ALGO` et `BNB` a 0 % (trades, aucun carnet de reference), `STRK`/`SEI` penalises par des carnets
    de connexions differentes. Exactement ce que le pre-chauffage du point 18 corrige : la boucle
    labo -> collecteurs se ferme enfin.
    Prouve : `test_reconciliation_carnets` (22 cas, dont le canari de seuils et les deux garde-fous
    de l'outil).

21. **C86 — l'AGRESSIVITE du leader devient un CRITERE (elle n'etait que mesuree).**
    `taker_notional_share` (part du notionnel execute en taker) etait deja CALCULEE par
    `copy_vault_copiability_mesures` puis simplement recopiee — jamais utilisee pour DECIDER : le
    travers que ce projet traque (« MENTION != PORTE »). Ajout dans `leader_quality_signal` (la ou vit
    deja le pre-filtre gelable de track-record) de `part_agressive_par_leader()` et
    `copie_leader_trop_passif()`. Fondement : un fill PASSIF a ete rempli parce que le marche est venu
    le chercher, pas parce que le leader voulait entrer MAINTENANT — il n'exprime aucune urgence, ne
    porte presque pas d'information directionnelle, et le copier paye le spread et les frais sans
    acheter de derive (mesure du projet : 67 % des fills sont passifs et valent ~0 avant frais).
    Deux subtilites verrouillees : « part INCONNUE » n'est JAMAIS « part nulle » (sinon on ecarterait
    des leaders faute de donnees, pas faute de qualite) ; et le filtre suit la convention FAIL-OPEN du
    module (identique a `copie_leader_faible`) et reste INACTIF par defaut.
    Prouve : `test_leader_agressivite` (13 cas, dont un canari qui exige que la part soit LUE et non
    recalculee, et un test de coherence entre les deux filtres du module).

**Bilan du lot d'implementation du 12/11 : 241 tests passent**

 (gouverneur, cablage etape 1, cache de
carnets, alignement ordres/fills, registre, decalage en ms, pre-chauffage des coins, sonde par segment,
porte de promotion et reconciliation en direct).


**Regression verifiee sur ces lots : 301 + 97 + 37 tests passent** (cache d'index + consommateurs du cache +
moteur d'execution + v21 gele + console du labo + gouverneur + cablage + etude de latence).

### C-bis. AUDIT DES DONNÉES — on n'utilisait pas tout ce qu'on collecte (12/11, demande de Florent)

**Constat (outil `tools/auditer_donnees_collectees.py`, croise collecté → certifié → utilisé) :** sur
22 familles certifiables, **7 étaient collectées ET certifiées mais JAMAIS chargées par le labo** :
`leader_orders` (ordres en attente = intention), `funding_history` (funding local), `vault_ledger`
(dépôts/retraits locaux), `vault_portfolio` (portefeuille leaders), `micro_bbo`, `micro_l2`,
`micro_trades` (microstructure fine). Le pont LOCAL (`copy_vault_tier_local`) ne lisait que
fills/books/bbo + 9 signaux.

**Corrigé :** les 7 familles sont ajoutées à `_COFFRE_FAMILLES_SIGNAUX` → chargées et disponibles à la
recherche (comptées sans coût mémoire dans le labo principal via `garder_signaux=False`). L'audit
réel les montre maintenant « FRAIS · UTILISÉ ». Chacune a une valeur : intention/anticipation (ordres),
coût de portage (funding), NAV/retraits (ledger), réplication par position (portefeuille), OFI fin et
lead-lag (micro). Garde-fou : `test_les_flux_autrefois_gaches_sont_maintenant_charges_comme_signaux`,
`test_inventaire_couvre_toutes_les_familles_connues_du_certificateur` (aucune famille oubliée).

**Écarts restants signalés par l'audit :**
- `explorer_tx` : certifié mais non utilisé — c'est de la métadonnée de DÉCOUVERTE de leaders (fills
  inférés, non causaux) ; exclu du PnL à juste titre, utilisable pour le choix des leaders seulement.
- `leader_orders` (intention) et `position` : **0 ligne collectée en LOCAL** — le collecteur
  `collecter_contexte_lane.py` (openOrders + clearinghouse + twap) n'existe que dans la lane cloud
  `copy-vault-contexte-lanes.yml`, pas dans le registre local. Les positions sont néanmoins couvertes
  localement par `vault_portfolio`. Pour collecter les ORDRES en local : ajouter une entrée
  `contexte-leaders` (script `collecter_contexte_lane.py --shard-count 1 --duree-s 1500`) au
  `collecteur_registry.REGISTRE` ET à `LANCER_HYPERSMART.cmd` (couplage testé). Non fait ce jour
  (éviter de toucher au lanceur pendant une collecte en cours) ; priorité moyenne (l'étude d'intention
  reste `MORE_DATA` et le chemin critique est l'exécutabilité).
- `fills_backfill` / `vault_ledger` : collectés par lots (toutes les 4 h) — 0 ligne en début de session
  est normal ; shards présents des sessions précédentes.

**Outils ajoutés (tous testés) :** `tools/auditer_donnees_collectees.py` (audit exhaustif, JSON ou
texte) ; `tools/etat_executabilite.py` (jauge « mesurable ? » + coins à collecter).

### C-ter. *(SUPERSÉDÉ — le programme qui la remplaçait est dans `docs/ROADMAP_ARCHIVE.md`)* CHANTIERS VERS UN PnL POSITIF (12/11, demande de Florent — audit : tout est négatif)

**Audit de la recherche (chiffres réels, PLAN_DE_RECHERCHE) :** copie naïve + fast-follow = REJECTED ;
ouvertures agressives −18,2 bps/décision ; sélectionnées −7,35 ; persistance −2,06 bps/j (P=0,33) ;
réplication lente +0,00 (1 jour). **Tout est négatif ou indistinguable de zéro.** Trois causes : (1) les
coûts (frais+spread ~5–9 bps) dominent la dérive ; (2) le délai observation→réaction (60 s) laisse partir
7,6 bps avant l'entrée ; (3) la sélection aide mais pas assez.

**Chantier 1 — LATENCE (posé, testé) :** `copy_vault_latency_study.etude_latence` rejoue les mêmes
signaux au vrai moteur en ne variant QUE le délai de copie (5/15/30/60/120 s) et agrège le net réel.
Outil : `tools/chantier_latence.py` (charge le dernier workspace matérialisé, comme le labo). Si le net
devient positif à 5 s → copier plus vite est LA voie ; sinon → maker/conditionnement. Tourne sur données
exécutables fraîches (après la collecte corrigée + un passage du labo).

**Chantiers suivants (à ancrer dans l'audit 2 h) :**
- MAKER : exécuter aux ordres-limites du leader (`leader_orders` enfin chargé) → gagner le spread au lieu
  de le payer (renverse ~la moitié du coût). Base : `copy_vault_order_intent` (ordre jumeau prudent).
- CONDITIONNEMENT : ne copier que si la dérive bat le coût — gros fill agressif + OFI favorable
  (`micro_l2`) + leader d'élite + régime. Les 7 familles rebranchées servent de filtres.
- RÉPLICATION LENTE par position (`vault_portfolio`) : moins sensible au timing, coût/avantage plus bas.

### C-quinquies. CHANTIERS DÉTECTÉS PAR LE RUN DU 12/11 (2 h données fraîches)

Détectés automatiquement à partir des verdicts, refus et écarts d'échantillon de la run (consigne :
chaque run doit produire de nouveaux chantiers). Priorité = ce que la run vient de prouver.

- **R1 — fast_follow REJECTED À SPREAD NUL (découverte forte).** La dérive résiduelle après observation
  passe SOUS les frais taker à TOUT horizon ≤ 300 s, même spread supposé nul. → Ce n'est pas qu'un
  problème de coût : l'avantage a déjà disparu quand on observe le fill. Chantiers : (a) tester les
  horizons LONGS > 300 s (900/1800/3600 s) où une dérive pourrait subsister ; (b) basculer sur
  l'ANTICIPATION (agir sur l'ordre-limite AVANT le fill, programme C4/E7) — la seule voie si la dérive
  post-fill est structurellement nulle ; (c) mesurer la demi-vie de la dérive pour savoir s'il reste
  une fenêtre exploitable.
- **R2 — maker bloqué par le DÉSALIGNEMENT ordres↔fills (pas par l'absence d'ordres).** `leader_order_intent`
  voit 0 fill pendant le suivi des carnets d'ordres en local. Chantier : collecter ordres EN ATTENTE et
  fills du MÊME leader sur la MÊME fenêtre, même connexion (sinon le jumeau maker n'a jamais son fill de
  référence). C'est la vraie forme du chantier A4, affinée par la run.
- **R3 — slow_replication rétrospectif à 17/20 jours (presque mesurable).** La voie la PLUS proche d'un
  verdict. Chantier : accumuler 3 jours distincts de plus de portefeuilles (`vault_portfolio`) → premier
  verdict net atteignable rapidement, sans attendre les 6 jours de carnets.
- **R4 — aggressive_open le plus échantillonné (6 j, 2400 décisions, 75 leaders) mais exige 30 j.**
  Chantier : prolonger la collecte des ouvertures jusqu'à 30 jours ; c'est l'hypothèse avec le plus gros
  échantillon, donc la plus susceptible de trancher (dans un sens ou l'autre) avec plus de temps.
- **R5 — 81 920 scénarios historiques rejoués ne battent pas le Copy-Vault actuel.** Chantier :
  conditionner (programme D) plutôt que balayer des paramètres globaux — la recherche par grille est
  épuisée, l'avantage, s'il existe, est dans un SOUS-ENSEMBLE conditionnel, pas dans un réglage global.
- **R6 — persistance ET sélection « intervalle à cheval sur zéro ».** L'échantillon ne tranche pas (ni
  positif ni négatif prouvé). Chantier : augmenter la PUISSANCE (plus de leaders × plus de jours) avant
  de relire — ou accepter que la compétence des leaders n'est pas détectable à ce capital/horizon.

### C-sexies. RÉSILIENCE MÉMOIRE — s'adapter à la RAM, JAMAIS crasher (12/11, exigence de Florent)

**Principe (non négociable).** Un module (labo, collecteur, moteur, certificateur) ne doit JAMAIS être
tué par manque de RAM. Face à une mémoire limitée il RALENTIT ou RÉDUIT son ampleur (moins de données
en vol, par morceaux, sur disque), mais il va au bout. « Adapter la puissance à la RAM utilisée, jamais
crasher. » Dégradation progressive, pas effondrement.

**M0 — GOUVERNEUR DE MÉMOIRE partagé — ✅ FAIT le 12/11 (voir section C, point 13).** Un module unique
(`gouverneur_memoire`) qui lit la RAM disponible (psutil) et publie un BUDGET courant + un niveau de
pression (VERT / ORANGE / ROUGE). Tous les modules lourds l'interrogent AVANT d'allouer un gros bloc et
appliquent une contre-pression. Fail-open : si la lecture échoue, budget prudent par défaut.

**M1 — LABO : par morceaux et sur disque, jamais tout en RAM.** ✅ FAITS : surveillance+respiration de l'étape 1 et plafond adaptatif du cache de carnets (section C, points 14-15). RESTE : découpe par lot shard/jour/coin et spill-to-disk à l'intérieur de `copy_vault_local_lab.py` (fichier au plafond de taille : à traiter par extraction, pas par ajout de lignes).
- Matérialiser / rejouer PAR LOT (shard, jour, ou coin) et libérer chaque lot avant le suivant ; ne
  jamais charger tout le coffre d'un coup (c'est la cause du reap à 16 Go).
- Borner le cache des carnets (LRU avec plafond mémoire, pas illimité) ; borner le nombre de scénarios
  tenus simultanément.
- Spill-to-disk / flux (Parquet/temp) pour les tables intermédiaires ; preuve mémoïsée bornée.
- Watchdog : si RAM libre < seuil, mettre en pause, vider les caches, reprendre — ne pas mourir.
- Preflight du labo : estimer le besoin mémoire vs disponible ; si insuffisant, RÉDUIRE automatiquement
  l'ampleur (moins de jours/coins) et le DIRE, plutôt que démarrer puis se faire tuer.

**M2 — COLLECTEURS : tampons bornés, débit adaptatif.**
- Tampons en mémoire PLAFONNÉS ; flush sur disque quand ils grossissent (jamais de croissance illimitée).
- Si pression ROUGE : réduire le nombre de coins/shards suivis ou la cadence, plutôt que gonfler la RAM.
- Écritures atomiques (tmp + rename) pour qu'un arrêt brutal ne corrompe jamais un fichier en cours.

**M3 — MOTEUR d'exécutabilité : traiter en flux.**
- Parcourir les méta-ordres par lots, libérer les carnets après usage (cache borné LRU).
- Ne jamais matérialiser toutes les positions/tous les carnets en une seule structure géante.

**M4 — ANTI-CRASH dur (filet de sécurité).**
- Capturer `MemoryError` : checkpoint + reprise au lieu de planter ; jamais d'exception mémoire non gérée.
- Points de reprise réguliers (le travail déjà fait n'est jamais perdu si on doit réduire la voilure).
- Respecter le reap du harness : si le système coupe quand même, reprendre proprement au dernier checkpoint.

**M5 — OBSERVABILITÉ.** Journaliser à chaque étape : RAM libre, budget, niveau de pression, décision
prise (lot réduit / pause / flush). Un test qui simule une RAM basse et prouve que le module termine
en mode dégradé SANS lever d'erreur mémoire (preuve, pas supposition).

**Ordre :** M0 (gouverneur) d'abord → M1 (labo, le plus gourmand) → M2/M3 → M4 (filet) → M5 (preuve).

### C-decies. SYNTHÈSE DIRECTRICE — fil conducteur (miroir intégral de la mémoire `chantiers_pnl_positif`)

Reporté ici pour que la feuille de route soit auto-suffisante. C'est le CONTEXTE qui donne du sens aux
sections 0 ter et C-bis → C-novies.

Projet invest (`C:\Users\flo\Desktop\Projet invest`). Après collecte réelle de **2 h** (12/11, 16 refus 429
seulement, 3,3 M données certifiées, 18 familles fraîches/22) + audit sérieux. Tout LOCAL, non commité (HEAD `bb41b323`).

**ÉTAT BRUTAL (à garder en tête) :** aucune hypothèse n'a de PnL positif prouvé. Copie naïve + fast-follow =
REJECTED ; ouvertures agressives −18 bps/décision, sélectionnées −7,35 ; persistance −2,06 bps/j (P=0,33) ;
réplication lente +0,00. Trois causes structurelles : (1) les coûts (frais+spread taker ~5–9 bps) dominent la
dérive ; (2) le délai observation→réaction 60 s laisse partir 7,6 bps avant l'entrée ; (3) la sélection aide mais pas assez.

**PRÉREQUIS ABSOLU :** le labo ne peut RIEN mesurer tant que TRAIN n'a pas ~6 jours denses de carnets
exécutables (identité de connexion + carnet de sortie). 2 h ne suffisent pas. → laisser tourner les collecteurs
corrigés plusieurs jours (ou pousser pour les lanes cloud), puis Certificateur, puis labo. Suivre le recul via
`tools/etat_executabilite.py` et `tools/audit_complet.py`.

**LES 4 GROS CHANTIERS (vers un PnL positif) :**
1. **LATENCE** — mesurer l'avantage à 5/15/30/60/120 s de délai de copie (le délai tue tout). CODÉ + testé :
   `src/hl_observer/backtesting/copy_vault_latency_study.py` + `tools/chantier_latence.py`. À LANCER sur données
   fraîches exécutables. Si net positif à 5 s → copier vite est la voie.
2. **MAKER** — exécuter aux ordres-limites du leader (gagne le ½ spread + frais maker ≈ la moitié du coût).
   **DÉJÀ CODÉ** dans `copy_vault_order_intent`. BLOQUÉ par l'absence de données `leader_orders` en local.
3. **CONDITIONNEMENT** — ne copier que si la dérive bat le coût : gros fill agressif + OFI favorable (micro_l2)
   + leader d'élite + régime (funding/volatilité). À BÂTIR ; les 7 familles rebranchées sont prêtes comme filtres.
4. **RÉPLICATION LENTE par position** (`vault_portfolio`, chargé) — copier la position, pas les fills ; moins
   sensible au timing. À approfondir.

**DÉBLOQUAGE TRANSVERSAL : collecter `leader_orders` (ordres en attente = intention) EN LOCAL.** Aujourd'hui
cloud-only (`copy-vault-contexte-lanes.yml` ; `collecter_contexte_lane.py` absent du registre local). Alimente les
chantiers 1/2/3. Pour l'ajouter : entrée `contexte-leaders` (`collecter_contexte_lane.py --shard-count 1
--duree-s 1500`) dans `collecteur_registry.REGISTRE` (passer `assert len == 22` → 23 dans
`test_collecteurs_registre`) + profil harvest. Non fait (risque en pleine collecte). `position` est couvert
localement par `vault_portfolio`.

**DONNÉES — ce qui a été réparé (`tools/auditer_donnees_collectees.py`) :** 7 familles collectées+certifiées mais
JAMAIS chargées par le labo (leader_orders, funding_history, vault_ledger, vault_portfolio, micro_bbo/l2/trades)
→ rebranchées dans `copy_vault_tier_local._COFFRE_FAMILLES_SIGNAUX`. Reste `explorer_tx` (métadonnée, exclu du PnL à juste titre).

**AUTRES AMÉLIORATIONS POSÉES (testées) :** budget de débit PARTAGÉ entre collecteurs
(`collecte_fiable.reserver_poids`, fail-open, câblé vaults/liq/carnet/overshoot + lanceur) ; carnet de sortie
garanti (TTL min→max horizon) ; sonde d'exécutabilité (zéro essai à vide) + carte par coin ; boucle
labo→collecteurs (`generer_coins_lanes` lit la carte). Outils : `audit_complet.py`,
`auditer_donnees_collectees.py`, `etat_executabilite.py`, `chantier_latence.py`.

**CONTRAINTE MÉMOIRE + EXIGENCE (12/11) :** le labo prend 16 Go ; avec les autres apps ouvertes les 32 Go
saturent → un passage labo a été TUÉ par le reap mémoire (RAM descendue à 6 Go). Exigence : ça ne doit JAMAIS
faire crasher nos modules — labo/collecteurs/moteur/certificateur doivent s'ADAPTER à la RAM (ralentir, par
morceaux, spill disque, réduire l'ampleur) et ALLER AU BOUT. → chantier dédié section **C-sexies** (M0 gouverneur
mémoire → M1 labo par lots → M2 collecteurs tampons bornés → M3 moteur en flux → M4 filet anti-crash → M5 preuve
RAM basse). En attendant : libérer la RAM avant un run, ne jamais lancer labo + suite complète ensemble.

**CONSIGNE PERMANENTE :** à la fin de CHAQUE run du labo, DÉTECTER le MAXIMUM de gros chantiers à partir de ce que
la run révèle (verdicts, refus par motif, écarts de données, per-coin) et les AJOUTER ici. L'audit n'est jamais
« fini » : chaque run doit produire de nouveaux chantiers.

**RUN DU 12/11 (2 h, chaîne complète) → section C-quinquies (R1–R6) :** (R1) `fast_follow` REJECTED MÊME À SPREAD
NUL — la dérive résiduelle post-observation est sous les frais taker à TOUT horizon ≤ 300 s → seules voies =
horizons longs > 300 s OU anticipation (agir avant le fill) ; (R2) maker bloqué par DÉSALIGNEMENT ordres↔fills en
local (0 fill capté pendant le suivi des ordres) → collecter ordres+fills du même leader/même fenêtre ; (R3)
slow_replication rétrospectif à 17/20 jours = le plus proche d'un verdict ; (R4) aggressive_open le plus
échantillonné (6 j/2400 déc./75 leaders) exige 30 j ; (R5) 81 920 scénarios historiques ne battent pas le
Copy-Vault → l'avantage est dans un SOUS-ENSEMBLE conditionnel (prog. D), pas un réglage global ; (R6)
persistance+sélection « intervalle à cheval sur zéro » → augmenter la puissance.

**INDEX DES SECTIONS DE LA FEUILLE DE ROUTE :**
- **0 ter** : 110 tâches labo (L1–L110) + 110 collecteurs/certificateur (C1–C110).
- **C-bis** : audit des données (ce qu'on n'utilisait pas). **C-ter** : premiers chantiers vers PnL positif.
- **C-quater** : programme complet, 8 programmes A→H (A mesurable / B coût / C latence / D sélection / E
  stratégies / F risque / G preuve / H infra), ~60 chantiers. Ordre : A → B1(maker)+C1(latence) → D → E → F/G → FORWARD.
- **C-quinquies** : 6 chantiers détectés par le run (R1–R6). **C-sexies** : résilience mémoire (M0–M5).
- **C-septies** : 200 tâches « mon bot parfait » (T1–T200, 16 thèmes). **C-octies** : chantiers de la 1re recherche web.
- **C-novies** : 300 améliorations concrètes & paramétrées (I1–I300, 20 programmes). **C-decies** : la présente synthèse.

**FONDS DE LA RECHERCHE WEB (à intégrer partout) :** takers paient / makers gagnent le spread (étude HL
mars–juin 2025) → exécution maker = levier n°1 ; adverse selection de latence (les rapides « pick off » les lents) ;
crowding = piège (whale ayant refilé ~4 M$ au HLP) → modéliser le crowding, ne pas être prévisible ; leaderboards
biaisés par la survie → sélection causale ; juger un leader sur profit factor/drawdown/historique, pas le win rate ;
canaux API Hyperliquid et limites (10 users/IP) documentés en C-novies P1–P3.

**RESTE À FAIRE (grands axes) :** chantiers D/E à coder ; collecter `leader_orders` en local ; après ~6 j de
données, lancer latence + maker + conditionnement ; durcir collecteurs (résilience mémoire) ; moteur PAPER fidèle.
Le PnL « méga positif », s'il existe, est dans B×C×D (coût bas + réaction rapide + bonne sélection) ou dans E
(autre source d'avantage) — et n'est RÉEL qu'une fois PROVEN en VALIDATION+OOS+FORWARD après tous les coûts et le crowding.

### C-quindecies-bis. CERTIFIER MEME APRES UN ARRET BRUTAL (13/11)

**Demande de Florent : « meme si il crash il faut quand meme certifier les donnees collectees ».**
Defaut reel : la certification n'avait lieu qu'a l'ARRET PROPRE (touche `q`) ou au DEMARRAGE
suivant. Une campagne de six jours fermee par accident au jour cinq laissait donc cinq jours de
donnees NON certifiees — et **le labo ne lit QUE le coffre certifie**, donc ces jours lui restaient
invisibles tant que personne ne relancait. (Cas reel : la fenetre a ete fermee par megarde.)

**Pourquoi c'est sans danger en pleine ecriture** — la question qui decidait de tout : le scellage
s'arrete au dernier saut de ligne COMPLET (`_fin_derniere_ligne`) et reprend ou il s'etait arrete
(`_reprise_append_only`). Une ligne a moitie ecrite n'est JAMAIS certifiee ; la passe suivante la
reprend entiere. Le certificateur etait donc deja concu pour des rubans qui grossissent.

**Ce qui a ete fait** (on AMELIORE l'outil existant, on n'en cree pas un deuxieme) :
* `--boucle-s N` ajoute a `tools/sceller_coffre_local.py` : une passe, attente, recommence.
  La boucle APPELLE `main()` — elle ne duplique aucune logique de certification.
  **Une passe en echec n'arrete JAMAIS la boucle** : une certification qui echoue a 3 h du matin ne
  doit pas condamner les cinq jours suivants. Ctrl+C, lui, sort immediatement (regle du projet).
* `CERTIFIER_EN_CONTINU.cmd` : lanceur visible, a laisser ouvert a cote d'une campagne.
* Entree de registre `coffre-certificateur` (cadence **30 min**, limite 50 min) pour que les
  campagnes FUTURES l'aient automatiquement. 30 min et non 1 h car la limite d'execution doit
  depasser 1,5x la cadence (garde anti-relance d'un processus vivant) — et cela divise par deux la
  fenetre de donnees non certifiees.
* 9 tests (`tests/test_certification_en_continu.py`).

**RESTE A FAIRE APRES LA CAMPAGNE** : ajouter `coffre-certificateur` a `DEFAULT_NAMES` de
`watch_economic_collectors.py` et passer le decompte du `.cmd` de 17 a 18 — **impossible
maintenant : on ne modifie JAMAIS un `.cmd` en cours d'execution** (Windows le lit au fur et a
mesure ; l'offset se decale et la reprise tombe au milieu d'une ligne). D'ici la, le lanceur
`CERTIFIER_EN_CONTINU.cmd` couvre le besoin a la main.

### C-sexdecies. LE DEFAUT COMPTABLE DES FRAIS D'ENTREE EST CORRIGE (14/11)

**Il etait ouvert depuis le 12/11 et documente par DEUX TESTS VOLONTAIREMENT ROUGES.** Ils sont
verts maintenant, et ils avaient raison depuis le debut.

**CE QUI ETAIT FAUX.** Deux modeles comptables coexistaient :
```
close_delta_pnl    = gross - sortie - funding            (modele CAISSE : entree payee a l'ouverture)
round_trip_net_pnl = gross - entree - sortie - funding   (modele COMPLET)
```
Le modele CAISSE n'est valide que si l'ouverture DEBITE reellement. Verification ligne par ligne :
la branche OPEN/ADD se contente de ranger le cout sur la position (`entry_costs`) ; `entry_costs_paid`
etait calcule, publie dans `entry_costs_paid_usdc` et `total_costs_paid_usdc`, et n'entrait NI dans
`total_pnl` NI dans l'equite. **Rien ne facturait les frais d'entree, nulle part.** Deux commentaires
affirmaient pourtant « already booked as realized cash cost at OPEN/ADD » et « charging them again
would double-count » : FAUX tous les deux. C'est « MENTION != PORTE » applique a la comptabilite —
un cout mesure, affiche, et jamais preleve.

**CE QUI A ETE CORRIGE.** Modele COMPLET : chaque frais compte UNE FOIS, la ou il se voit.
* `ui/status_routes.py` — le coeur du defaut : `entry_cost_usdc=0.0` etait **force a zero** dans
  `_mark_to_market_positions`. Desormais le vrai cout est passe. Une position ouverte vaut ce
  qu'elle rapporterait NETTE si on la fermait maintenant — c'est d'ailleurs ce que dit la formule
  publiee juste en dessous : `(mark-entry)*size-entry_cost-exit_cost`.
* `ui/routes.py` — le mark des positions ouvertes deduit `entry_costs` ; la fermeture publie
  l'aller-retour complet ; et `total_pnl` ne soustrait RIEN separement (le frais migre de
  l'unrealized vers le realise au moment exact de la fermeture, donc le soustraire une seconde
  fois recreerait le double comptage que le durcissement avait, lui, correctement supprime).

**PREUVE** : `-0,24` au lieu de `-0,12` sur le mark, equite `999,76` au lieu de `999,88`,
`0.7388` au lieu de `0.7588`. **83 tests comptables passent**, le test d'aller-retour est stable 3/3.

**DEFAUT D'ISOLATION DECOUVERT EN CHEMIN — important.** `test_ui_simulation_status_fast.py` lit
`runtime/data/hl_allmids.json`, que la campagne ECRIT EN DIRECT : le test recevait `mark_price=1889.0`
(le prix ETH reel du moment) au lieu de `2010.0` (sa fixture). **Lancer ces tests pendant une collecte
donne des resultats faux**, dans les deux sens. Cela explique aussi les lots « 44 echecs groupes,
tout vert en isolation » observes le 13/11. A isoler.

### C-septdecies. LE TAUX DE REMPLISSAGE MAKER EST MESURE : 47,1 % (14/11)

**C'etait LE chiffre manquant du seul levier jamais ouvert.** Tout edge mesure ici meurt dans les
couts : `fast_follow` REJETE a tous les horizons <= 300 s **meme a spread nul**, DeepLOB a
**-4 242 bps net**, 67 % des fills de leaders passifs et valant ~0 avant frais. L'entree MAKER
(encaisser le spread au lieu de le payer) n'avait jamais pu etre evaluee.

**POURQUOI ELLE ETAIT BLOQUEE.** Le moteur savait deja modeliser l'economie maker :
`robustness.maker_adjust_net` gere l'economie d'un trade rempli ET la selection adverse
(`adverse=True` garde les PIRES trades : les gagnants filent avant que l'ordre passif soit
touche), et `microstructure_extras.maker_queue_fill_prob` donne une probabilite de file.
**Mais les deux PRENNENT `fill_rate` EN PARAMETRE** — personne ne l'avait mesure. D'ou
`native_cross_venue_replay` publiant `maker_fill_proven: False` en dur et des cles nommees
`..._unproven_fill`. Le moteur refusait de conclure, et il avait raison.

**CE QUI A ETE CONSTRUIT.** `backtesting/maker_fill_probe.py` (17 tests) + `tools/mesurer_remplissage_maker.py`. Pour chaque fill de leader, on simule un ordre PASSIF pose
au touch au moment ou NOUS l'observons (delai de copie compris) et on regarde si le marche
l'aurait consomme dans l'horizon.

**TROIS CHOIX QUI RENDENT LA MESURE HONNETE** (et non flatteuse) :
1. on se met **DERNIER dans la file** — toute la taille affichee a notre prix est devant nous ;
2. seul le volume au **prix OU MIEUX** consomme la file ;
3. **« je ne sais pas » n'est JAMAIS « rempli »** — carnet absent, niveau absent ou fenetre sans
   trade sortent en NON MESURABLE et n'entrent dans aucun numerateur ; le taux porte toujours
   son denominateur. Couvrir la file SANS couvrir notre propre taille n'est pas un remplissage.

**RESULTAT MESURE : 47,1 % sur 603 cas jugeables** (38 non mesurables, 2 094 ecartes comme hors
de la fenetre couverte par les trades). Les hypotheses etant pessimistes, **le vrai taux ne peut
qu'etre SUPERIEUR**. `maker_adjust_net(fill_rate=...)` cesse d'etre alimente au doigt mouille.

**DEUX PIEGES DE LECTURE CORRIGES EN CHEMIN** (tous deux auraient fait conclure « maker
impossible ») :
* **fenetre de couverture par coin** : le ruban des trades pese 3,7 Go, sa queue ne couvre que
  ~28 min alors que les fills remontent a 237 min. Juger hors de cette fenetre produisait un
  artefact de LECTURE. Meme piege que la reconciliation des carnets (fenetre globale accusant a
  tort 114 fills sur 687).
* **noms de champs reels** : les trades portent `received_at_ms` / `exchange_ts_ms` et
  `price` / `size`, PAS `ts_ms` / `px` / `sz`. Ne chercher que `ts_ms` revenait a ignorer
  SILENCIEUSEMENT 100 % des trades. La RECEPTION prime (instant ou nous aurions pu agir), choix
  canonique du projet. Verrouille par deux tests.

**LA SECONDE HYPOTHESE ETAIT PIRE QUE LA PREMIERE.** L'appel historique
(`tools/analysis/_optim_analysis.py`) ecrivait `spread_saving_usd=0.20` **EN DUR**, toutes
tailles et tous coins confondus. Mesure sur 719 carnets reels : **0,0421 USD de mediane**.
**La constante etait 4,75x trop genereuse** — toute evaluation maker anterieure etait gonflee
d'autant. Et le meme appel n'utilisait que `adverse=False`, c'est-a-dire la borne HAUTE.

 `economie_de_spread(carnet, notionnel)` mesure le DEMI-SPREAD reel par
coin, et `encadrement_maker(...)` publie desormais les DEUX bornes avec un verdict en trois
etats : `POSITIF_MEME_AU_PIRE` / `POSITIF_SEULEMENT_AU_MIEUX` / `NEGATIF_DANS_LES_DEUX_CAS`.
Un canari AST interdit toute valeur chiffree en dur pour `fill_rate` et `spread_saving_usd` :
l'hypothese ne peut plus revenir par la petite porte. **22 tests.**

**MESURE CONSOLIDEE : remplissage 48,2 % sur 674 cas ; economie 0,0421 USD sur 719 carnets.**

**PROCHAIN PAS** : brancher ce taux mesure dans `maker_adjust_net` et relancer les familles
declarees mortes en taker — `fast_follow` en tete, puisqu'il etait rejete *meme a spread nul*,
donc par les FRAIS et non par le spread.

### C-novodecies. LECON DE MICROSTRUCTURE — le remplissage n'est que la MOITIE (14/11)

**CORRECTION D'UNE CONCLUSION DU MATIN MEME.** `maker_fill_probe` a mesure 48,2 % de remplissage
et 0,0421 USD de gain de spread. **C'est la moitie FAVORABLE de l'equation.** La decomposition
complete d'un remplissage passif est :

```
net(t) = capture + adverse(t) - frais
capture    = e * (m0 - p) / m0      demi-spread encaisse, TOUJOURS >= 0, fige au fill
adverse(t) = e * (mt - m0) / m0     derive du mid APRES le fill, <= 0 en moyenne
```

**CE QUE LA LITTERATURE MESURE, SUR HYPERLIQUID.** Daru Finance, *Quoting the Touch Does Not Pay
Its Adverse Selection* : 9 983 jours-coin, **125,8 M de remplissages simules**, avec la MEME
hypothese de file que la notre (« queues behind all visible size »). Sur Hyperliquid :
capture **+0,56 bp**, derive a 10 s **-1,02 bp**, **net -0,46 bp AVANT frais**, intervalle a 95 %
(groupe par mois ET par coin) excluant zero. Sur Bybit -0,84 bp, sur Binance USD-M -0,39 bp.
**Conclure « le maker est viable » depuis le seul taux de remplissage aurait ete une erreur.**

**CE QUI CHANGE LE SIGNE : LA PLACE DANS LA FILE.** Albers, Cucuringu, Howison & Shestopaloff,
sur le perp BTC d'Hyperliquid a 5 s : remplissage maker moyen **-0,48 bp**, mais ceux qui gagnent
la **PREMIERE PLACE** de la file **+0,32 bp** — ecart **~0,8 bp**, plus grand que deux des trois
nets ci-dessus. **Ce n'est pas la prediction qui separe le gagnant du perdant, c'est la place
dans la file.** Toute conclusion maker doit donc dire A QUELLE PLACE elle vaut ;
`maker_fill_probe` suppose la DERNIERE, c'est-a-dire le pire cas, et c'est volontaire.

**L'AVANTAGE STRUCTUREL D'HYPERLIQUID, A EXPLOITER.** Chaque bloc valide est REORDONNE pour que
les annulations et les ordres post-only s'executent EN PREMIER (blocs de ~100-200 ms). Un maker
qui detecte un mouvement peut donc annuler et **battre un preneur plus rapide que lui** — une
defense qui n'existe pas sur les venues centralisees. Effet mesure : markout a 1 s d'environ
**1,1 bp sur Hyperliquid contre ~2 bp** sur les grandes CEX.

**TROIS LEVIERS OPERATIONNELS** (praticiens, convergents) : raccourcir le temps de detention (le
mal se fait dans les secondes qui suivent le fill) ; plafonner l'inventaire (seul le cote qui
REDUIT continue de coter) ; recoter souvent (ne jamais etre l'ordre le plus perime du carnet).
Et un contre-sens a eviter : **coter plus loin ne protege pas** — on se fait remplir uniquement
quand le marche bouge fort, donc precisement quand c'est toxique.

**CE QUI A ETE CONSTRUIT** : `backtesting/markout.py` (11 tests). Tous les pieges connus sont
refuses explicitement : jointure **as-of** et jamais « au plus proche » (sinon un markout a
100 ms devient un markout a 1,9 s sans prevenir) ; horizon hors donnees = **TRONQUE, jamais
zero** (prolonger par le dernier prix fabrique « aucune derive ») ; aucun regard vers le futur
pour le mid de reference ; peremption bornee **sans valeur par defaut** (le module refuse d'en
deviner une) ; fills **passifs uniquement** ; signe inverse cote vente ; **distribution publiee**
et pas seulement la moyenne ; un horizon sans donnee **ne vote pas** ; et surtout **« rien mesure »
n'est JAMAIS « flux sain »**.

**FAIT — ET LE VERDICT TOMBE.** Markout branche sur les fills reels d'Alina :

```
ALINA (mesure)                    REFERENCE (125,8 M fills, Hyperliquid)
capture   : +0,02 bp              capture   : +0,56 bp
net  1 s  : -0,16 bp
net  5 s  : -2,53 bp
net 10 s  : -3,42 bp              net 10 s  : -0,46 bp
net 30 s  : -2,38 bp
-> FLUX TOXIQUE (n = 236 remplissages)
```

**LA DECOUVERTE DU JOUR, ET ELLE INVALIDE MA MESURE DU MATIN.** L'economie de spread mesuree a
l'instant de l'ORDRE valait 0,0310 USD, soit ~2 bp. La capture mesuree a l'instant du FILL vaut
**+0,02 bp** : un rapport d'environ **100x**.

La raison est structurelle et vaut pour toute strategie passive : **un ordre passif n'est rempli
QUE si le marche vient a son prix.** A cet instant, le mid a deja baisse jusqu'a notre bid, donc
`(m0 - p) ~ 0`. **Le demi-spread visible au moment de poser l'ordre n'est pas encaissable** ; il
n'est encaisse que dans les etats du monde ou le prix a bouge CONTRE nous. C'est exactement ce
que la litterature formule : `capture ~ -adverse`, donc `net ~ 0` — et ici pire que zero.

**CONSEQUENCE POUR LE MOTEUR : le chemin maker NAIF (poser au touch, dernier dans la file) est
PIRE que le taker.** Il ne sauvera pas `fast_follow`. Toute evaluation maker qui alimente
`maker_adjust_net` avec une economie mesuree A L'ORDRE surestime le gain d'environ deux ordres de
grandeur. **`spread_saving_usd` doit venir de la CAPTURE AU FILL, jamais du spread affiche.**

**CE QUI RESTE OUVERT** — les deux seules voies que la litterature laisse :
1. **la place dans la file** : premiere place +0,32 bp contre -0,48 bp en moyenne (ecart 0,8 bp).
   Mesurer ce que coute/rapporte d'etre devant, au lieu de supposer la derniere place ;
2. **l'annulation prioritaire d'Hyperliquid** : les blocs reordonnent cancels et post-only EN
   PREMIER, donc un maker qui detecte le mouvement peut annuler et battre un preneur plus
   rapide. C'est la seule defense structurelle disponible, et elle n'existe pas ailleurs.

Tant que l'une des deux n'est pas mesuree, **le maker reste REFUTE sur nos donnees**.

**PROCHAIN PAS** : brancher ce markout sur les fills reels pour obtenir le net maker d'Alina, et
le comparer au -0,46 bp de reference. Si notre net est pire, le maker ne sauvera pas
`fast_follow` ; s'il est meilleur, il faudra dire POURQUOI avant d'y croire.

### C-vicies. APPRENDRE A TRADER COMME UN SENIOR — la duree avant le signal (14/11)

**LA QUESTION N'EST PAS « le signal est-il positif ? » MAIS « puis-je tenir assez longtemps pour
payer le trade ? »** Tout ce que ce labo a mesure meurt dans les couts : `fast_follow` rejete a
tous les horizons <= 300 s **meme a spread nul** (donc tue par les FRAIS, pas par le spread),
DeepLOB -4 242 bps, maker naif -3,42 bp de markout. Le seul edge vivant est le carry de funding.

**TROIS RESULTATS DE LA LITTERATURE, ET LE TROISIEME GOUVERNE TOUT.**

1. **Le seuil est une DUREE, pas un taux** : `N* = C / mu`. Un aller-retour de 0,38 % a
   0,01 %/8 h demande **38 periodes, soit 12,7 jours**. « La duree de detention, pas le taux
   affiche, determine si un carry gagne de l'argent. »
2. **`N*` est un PILE OU FACE** : c'est exactement le point ou P(profit) = 50 %, ce que les
   calculateurs ne disent jamais. Le seuil a 95 % resout `mu·N - z·sigma·sqrt(N) - C = 0` et vaut
   **~4,2x plus long** en i.i.d., **~6,4x** avec une persistance AR(1) faible (phi = 0,3) —
   verifie par Monte-Carlo sur 200 000 trajectoires.
3. **Trader le signal le DETRUIT.** Mesure sur deux ans : la regle a seuil produit **le plus de
   revenu BRUT de toutes les regles testees** et finit a **-9 % a -15 % net** — l'execution
   consomme **trois fois le brut**. La regle qui tient en continu et ne revise que sur une
   horloge de 30 jours (**1 a 5 allers-retours en DEUX ANS**) rend **+2,7 % a +5,4 % net**,
   drawdown sous 2 %. **La direction du signal est un regime qui dure des mois ; son niveau est
   du bruit horaire. Confondre les deux, c'est tout le piege.** Marge d'erreur : la regle
   patiente supporte un cout d'aller-retour de plus de **250 bps**, la regle active meurt
   au-dela de **8 bps**.

**APPLIQUE A NOS CHIFFRES REELS** (`backtesting/carry_horizon.py`, 10 tests) :

```
cout aller-retour (4 jambes taker a 4,5 bps) : 0,180 % du notionnel
horizon disponible : 144 h (la campagne de 6 jours)

regime 2026 faible (mu=0,001 %/h)  seuil 95 % = 296 h  ->  NON TENABLE
regime median      (mu=0,003 %/h)  seuil 95 % = 139 h  ->  tenable, de justesse
regime riche       (mu=0,010 %/h)  seuil 95 % =  77 h  ->  TENABLE
```

**CONSEQUENCE MAJEURE POUR LA CAMPAGNE.** Le regime de funding 2026 mesure est FAIBLE : sur
708 relevés, le funding BTC n'a **jamais** depasse 0,01 %/8 h, et 29,4 % etaient negatifs ; le
funding annualise brut est tombe de 30,61 % (2021) a **2,43 % (2026)**. Dans ce regime, **6 jours
ne suffisent pas a tenir UNE position de carry jusqu'a son seuil de confiance a 95 %**. La duree
de campagne n'est donc pas seulement une question de puissance statistique (racine de n) : c'est
une question de **duree de detention**. Le moteur ne peut pas valider un trade qu'il ne peut pas
tenir.

**CE QUE LE MODULE REFUSE** : un taux nul ou de signe contraire (aucune duree ne corrige un
signe — on refuse au lieu de renvoyer un grand nombre) ; une volatilite inconnue (se rabattre sur
le seuil naif dirait « confiant » la ou l'on est a pile ou face) ; un horizon de donnees plus
court que la duree requise (`NON_TENABLE`).

**RISQUE A NE PAS OUBLIER** : « delta-neutre » n'est pas « a l'abri d'une liquidation ». Les
excursions adverses mesurees sur la jambe short vont de **+116 % (BTC) a +400 % (SOL)** sur des
detentions de 31 a 98 jours. La marge de portefeuille est un **prerequis**, pas une optimisation.

### C-vicies-bis. LA COUCHE DE SURVIE — placable ? survivable ? AVANT rentable (14/11)

**C'est la couche qui manquait.** Tout l'appareil de ce labo repondait a « cet edge survit-il aux
couts ? ». **Aucune ligne** ne repondait a « cet ordre serait-il accepte par la venue, et la
position tiendrait-elle jusqu'a l'echeance ? ». Une analyse d'edge sur une position liquidee en
route ne vaut rien. `backtesting/survie_position.py`, 18 tests.

**LES CONTRAINTES DURES D'HYPERLIQUID** (documentation de la venue) :
* **notionnel minimum 10 USD** par ordre. Une regle de dimensionnement qui sort 4 USD ne produit
  pas une petite position : elle produit un **ordre REJETE**.
* **mmr = moitie de la marge initiale au levier max** : de **1,25 %** (40x, BTC) a **16,7 %** (3x).
* **prix de liquidation** : `liq = p - side * marge_dispo / taille / (1 - l*side)`, `l = 1/lev_mnt`.
  **Verifie** : un long a 1x rend liq = 0 (jamais liquidable) — la formule est bien implementee.
* **la liquidation de secours coute EN PLUS** : sous 2/3 de la marge de maintenance, « the
  maintenance margin is not returned to the user ». Terme de perte que personne ne modelise.

**LE CALCUL QUI CHANGE LE DIMENSIONNEMENT.** En inversant la formule de la venue :
`L_max = 1 / (e*(1+mmr) + mmr)`. Applique aux excursions adverses **REELLEMENT OBSERVEES** sur
31-98 jours de detention (+116 % BTC, +400 % SOL) et a 350 USD de capital :

```
actif     lev.max    mmr   excursion   lev.max survivable   notionnel
BTC         40x    1,25 %    +116 %          0,84x           295 USD
ETH         25x    2,00 %    +200 %          0,49x           170 USD
SOL         20x    2,50 %    +400 %          0,24x            85 USD
alt 10x     10x    5,00 %    +400 %          0,24x            82 USD
```

**Un levier superieur a 1x sur une jambe de carry n'est pas « agressif » : il est MATHEMATIQUEMENT
INCOMPATIBLE avec les excursions deja mesurees.** Sur SOL, la jambe short doit rester sous
**85 USD de notionnel sur 350 USD** de capital.

**ET LA CONSEQUENCE EST ENCOURAGEANTE, pour une fois.** Sur ces 85 USD survivables, regime median
(0,003 %/h) : carry brut 2,55 USD / 1 000 h, cout d'aller-retour 0,153 USD, net ~2,40 USD, soit
**~6 % annualises sur le capital**. **Ce chiffre, obtenu independamment par nos propres formules,
tombe exactement dans la fourchette publiee pour la regle patiente (+2,7 % a +5,4 % net).** Deux
chemins de calcul separes qui convergent : c'est le meilleur signe de validite qu'on ait eu.
En regime FAIBLE (celui mesure pour 2026), le meme calcul rend **NON_TENABLE**.

**CE QUE LE MODULE REFUSE** : un notionnel sous le minimum (`REJETE`, jamais « petite position ») ;
un `mmr` inconnu (supposer 1,25 %, reserve a BTC, autoriserait un levier mortel sur un alt) ;
une excursion non fournie — **l'ABSENCE de scenario adverse n'est pas un scenario favorable**.

### C-vicies-ter. LE PREMIER PnL POSITIF MESURE — et le chemin pour y arriver (14/11)

**Donnees** : `funding_history` (90 coins) + `candle` 1h (263 coins), **211 jours** (17/04 au
14/11), tier **LOCAL** (pont local, pas corpus SAFE reconcilie). `backtesting/carry_patient.py`,
20 tests. Cout retenu : **13 bps par jambe et par aller-retour** (4,5 taker x2 + 2 slippage x2).

**ETAPE 1 — LE CARRY SEUL DISAIT +15,44 %/an. C'ETAIT UNE DEMI-MESURE.** Le funding rapportait
+1,399 % par revision. **Je n'avais pas mesure le prix** — exactement la faute du demi-spread
commise le matin meme. Avec le prix : **-9,687 %**, sept fois plus gros et de l'autre signe.

**ETAPE 2 — POURQUOI.** Le prix du livre vaut `(rendement des bas-funding - rendement des
hauts-funding)/2`. Les coins a funding eleve ont **surperforme de 19,4 % par 30 jours** : un
funding eleve signale une **foule deja longue**, donc un gagnant recent. **Shorter le funding
eleve, c'est shorter le momentum.**

**ETAPE 3 — UNE INVERSION D'ABORD FAUSSE, RATTRAPEE.** Ma premiere inversion niait les VALEURS
de funding, ce qui fabrique un revenu fictif : la strategie et son exact oppose affichaient
**+1,840 % et +1,845 %**, impossible. Signe de l'artefact. L'inversion correcte retourne les
**POSITIONS** en laissant le funding intact ; un test le verrouille (`funding_moyen < 0` dans le
sens inverse, car on PAIE sur les deux jambes).

**ETAPE 4 — 6 OBSERVATIONS NE DECIDENT RIEN.** A 30 jours d'horloge sur 211 jours, on n'a que
**6 detentions disjointes**, et une seule a **-22,8 %** ecrasait les cinq autres. Ajout de `pas_h`
(detention de 30 j demarree chaque semaine) : **25 detentions**. Elles **CHEVAUCHENT** (29 j
partages sur 30), donc **pas de t de Student** — declare par `fenetres_independantes: False`, et
l'annualise se lit sur la MOYENNE par detention, jamais sur la somme (sinon on compte le meme
gain plusieurs fois).

**ETAPE 5 — TRAIN / TEST (106 j chacun), les deux sens, k=4 (impose, voir plus bas) :**

```
                 funding     prix    net/det   annualise   positives   pire
TRAIN  carry     +2,025 %  -2,377 %  -0,482 %    -5,9 %      6/10
TEST   carry     +1,567 %  -6,452 %  -5,015 %   -61,0 %      2/10
TOUT   carry     +1,635 %  -4,901 %  -3,396 %   -41,3 %      8/25
TRAIN  inverse   -2,164 %  +2,964 %  +0,670 %    +8,2 %      5/10     -11,18 %
TEST   inverse   -1,775 %  +7,217 %  +5,312 %   +64,6 %      9/10     -13,69 %
TOUT   inverse   -1,803 %  +5,327 %  +3,394 %   +41,3 %     18/25     -15,89 %
```

**LE CARRY EST REFUTE** : negatif dans les deux moities. **Le livre inverse est positif en TEST a
tous les k testes (2, 3, 4, 5) et sur l'ensemble.**

**ETAPE 6 — LE SOUPCON DE BETA, LEVE.** Un livre dollar-neutre long/short pourrait n'etre qu'un
pari sur la direction du marche. Mesure : **rho de Spearman livre <-> marche = +0,266, p = 0,20
contre un seuil corrige de 0,025 -> lien NON retenu**. Et surtout, le livre gagne dans les DEUX
regimes : **marche en baisse (11 det.) net +1,676 %, 7/11 positives** ; marche en hausse (14 det.)
+4,283 %, 10/14. La fenetre contenait un vrai choc (**-23,3 % de marche en 30 j**), traverse a
-7,98 % au pire. **Ce n'est donc pas du beta mal couvert.**

**ETAPE 7 — LA CONFIGURATION JOUABLE, imposee par les portes et non choisie.** Le palier le plus
contraignant du livre decide : alt 10x, mmr 5 %, excursion observee +400 % -> **levier maximum
0,235x**, soit **82,4 USD de notionnel sur 350**. Par jambe : k=5 donne 8,2 USD -> **REJETE**
(minimum 10 USD de la venue) ; **k=4 donne 10,3 USD -> PLACABLE**. **C'est la contrainte de
placement qui impose k=4, pas le backtest** — et k=4 a ete verifie APRES, pas choisi pour son
chiffre.

```
+41,3 %/an sur notionnel  x  0,235 de levier  =  +8,99 %/an sur capital
                                              =  +31,46 USD/an sur 350 USD (PAPER)
cout si liquidation : 4,12 USD (marge de maintenance non rendue)
```

**CE QUE CE CHIFFRE N'EST PAS.** Ce n'est pas une prevision : c'est ce que 211 jours ont contenu,
et **l'essentiel vient de la seconde moitie** (TRAIN +8,2 % contre TEST +64,6 %, et k=3 est meme
negatif en TRAIN). Un effet stable donnerait deux moities franchement positives. Reserves a
garder au clair : 25 fenetres chevauchantes valent ~7 observations independantes ; un seul regime
(avril-novembre 2026) ; **et la nature du livre est d'etre LONG LA FOULE** — or la venue a connu
une cascade qui a detruit 7,4 Md USD d'OI et liquide integralement plus de 1 000 comptes. C'est
precisement le scenario ou ce livre est le combustible. La fenetre mesuree n'en contient pas.

### C-vicies-quater. LE MAKER EST REFUTE, MEME EN TETE DE FILE (14/11)

L'experience annoncee d'avance a rendu son verdict, sur **31 863 cas jugeables** tires de
**191 743 remplissages** du coffre (6 lots de scellement communs aux quatre familles) :

```
                   remplissage   net 5 s   net 10 s   net 30 s
DERNIERE place        37,8 %     -5,76 bp  -6,03 bp   -7,22 bp
PREMIERE place        63,1 %     -3,40 bp  -3,56 bp   -3,61 bp
litterature (BTC)                +0,32 bp
```

**Gagner la file aide enormement** : le remplissage passe de 37,8 % a 63,1 % et le net gagne
2,4 bp. **Mais il reste NEGATIF.** Le critere avait ete ecrit AVANT la mesure : « si le bras
PREMIER reste negatif, le signe appartient au fait de coter au touch, pas a la place dans la
file ». **Le maker est donc refute sur nos donnees, en tete de file comme en queue.**

L'ecart avec la litterature (-3,40 contre +0,32 bp a 5 s) s'explique vraisemblablement par
l'univers : la reference porte sur le seul perp BTC, le carnet le plus profond de la venue, la
ou nous mesurons sur **187 coins** dont des alts peu liquides, ou le demi-spread est large mais
la selection adverse pire encore.

**UNE MAUVAISE ATTRIBUTION TROUVEE ET CORRIGEE AU PASSAGE.** La capture sortait **negative**
(-6,01 bp), ce qui est impossible par construction : on place toujours SOUS le mid a l'achat. La
cause : `m0` etait pris a l'instant du REMPLISSAGE, repliant la derive d'attente dans la capture.
`markout_d_un_fill` accepte desormais `instant_ordre_ms` et rend une decomposition a trois
termes : `capture` (demi-spread verrouille au placement, >= 0) + `attente` (ce que la derive a
coute pendant l'attente) + `adverse` (la selection apres le fill). Sur l'exemple de controle, la
capture repasse de -50,5 bp a **+50,0 bp**, et la recomposition est exacte.
**Le NET est inchange** : il vaut `eps(m_tau - p)/reference`, dont le numerateur ne depend pas de
la reference — un test verrouille cette invariance, car si le net bougeait, la correction serait
une falsification. **Le verdict de refutation tient donc tel quel.**

### C-vicies-quinquies. DE 31 A 282 USD/AN — deux erreurs de ma part, corrigees (14/11)

**LES +31 USD/AN VENAIENT DE DEUX FAUTES QUE J'AVAIS COMMISES, pas d'une limite du marche.**

**FAUTE 1 — UN PLAFOND DE LEVIER FAUX D'UN FACTEUR 20.** `survie_position` plafonnait a
**0,235x** en exigeant qu'une **jambe NUE** survive a une excursion de +400 %. Ce chiffre venait
d'une etude de *cash-and-carry* ou le short etait **couvert par un long spot**, et je l'ai
applique a un livre **long/short dollar-neutre en MARGE CROISEE**. La venue est explicite :
« Cross positions are liquidated when **the account value (including unrealized pnl)** is less
than the maintenance margin times the total open notional », et une lecture independante du
moteur de risque ajoute : « Positive unrealized PnL on one position supports others, so **a
hedged book is much harder to liquidate than either leg alone** ».
La nuance qui empeche de sur-corriger : la marge croisee mutualise les **PnL**, elle ne reduit
**pas l'EXIGENCE** (« Standard margin sums position-level requirements and gives no hedge
benefit »). D'ou `maintenance = SOMME(notionnel_i x mmr_i)` sans remise, `valeur = capital +
SOMME(PnL)` avec compensation, donc **`N < C / (D + mmr)`**.
`backtesting/dimensionnement_croise.py`, 10 tests. Le `facteur_de_securite` est **obligatoire et
sans defaut** : dimensionner sur le pire repli OBSERVE garantit une liquidation au premier
evenement pire. Et c'est **le palier le plus contraignant du livre** qui fixe le mmr, jamais la
moyenne.

**FAUTE 2 — L'HORIZON, UN PARAMETRE JAMAIS EXPLORE.** Tout ce labo avait teste soit **<= 300 s**
(fast_follow, tue par les frais meme a spread nul), soit **720 h**. La bande 1 h - 48 h etait
VIERGE. Balayage sur 211 jours, livre inverse, k=4 :

```
horizon  rot./an |  TRAIN    pos. |  TEST     pos.    n
    6h     1460  |  -62,6 %   44% | -142,4 %   42%  415   <- 1460 x 13 bps = 190 %/an de frais
   12h      730  |  +82,2 %   52% |  -33,0 %   46%  415
   24h      365  | +110,5 %   59% |  +57,0 %   54%  415
   48h      182  | +100,5 %   54% |  +47,1 %   50%  204
   96h       91  |  +66,0 %   67% |  +64,6 %   57%   98   <- TRAIN et TEST se REJOIGNENT
  168h       52  |  +49,5 %   55% |  +44,6 %   70%   53
  336h       26  |  +55,6 %   72% |  +46,9 %   60%   25
  720h       12  |  +25,3 %   50% |  +32,4 %   70%   10   <- mon point de depart, le PIRE
```

**La forme est un PLATEAU LISSE sur 24-336 h, pas un pic** — un pic isole serait du bruit, un
plateau large est la signature d'une structure. Et le comportement des frais valide la lecture :
ils ecrasent exactement la ou la theorie l'exige.

**CRITERE DE CHOIX, ENONCE AVANT DE REGARDER LES USD** : l'ecart TRAIN/TEST le plus faible avec
n >= 50 — un critere qui ne recompense **PAS** le rendement. Ecarts : 24 h **53,5 pts**, 48 h
53,4, **96 h 1,4**, 168 h 4,9, 336 h 8,7. **96 h retenu.** Il se trouve que 96 h est aussi le
meilleur TEST (+64,6 %), ce qui rassure au lieu d'inquieter : le critere n'a rien coute.

**LE LIVRE RETENU** — detention 96 h (4 j), depart toutes les 24 h, k=4, 204 detentions
chevauchantes : funding **-0,278 %** (on PAIE), prix **+0,881 %**, cout 0,130 % -> net
**+0,474 % par detention**, mediane +0,651 %, **118/204 positives (58 %)**, pire **-12,14 %**,
**annualise +43,22 %**.

```
facteur  levier  notionnel  /jambe  liquide si  rdt/capital   USD/an
   2,0    3,41x    1195 U    149 U     29,3 %     +147,6 %     +517
   3,0    2,41x     845 U    106 U     41,4 %     +104,3 %     +365
   4,0    1,87x     653 U     82 U     53,6 %      +80,7 %     +282
   6,0    1,28x     449 U     56 U     77,9 %      +55,5 %     +194
```

**A facteur 4 — il faut que le livre perde 53,6 % pour liquider — on passe de +31 a +282 USD/an**,
soit **x9**, sans toucher au signal : uniquement en corrigeant mes deux fautes.

**CE QUI RESTE FAIBLE, ET QU'IL FAUT DIRE** : 58 % de detentions positives, c'est mince ; les 204
fenetres chevauchent 4 fois, donc ~50 observations independantes ; un seul regime (avril-novembre
2026) ; et le livre reste **LONG LA FOULE**, donc combustible d'une cascade — la venue en a connu
une a 7,4 Md USD d'OI detruits.

**LE SIGNAL COPYVAULT RESTE NON TESTE, ET C'EST LE VRAI CHANTIER.** Le coffre contient
`position` (`szi` signe par vault et par coin, **46 vaults, 179 coins**) et `leader_orders`
(`notionnel_par_coin` avec les deux cotes) — mais seulement **45 heures d'historique**
(11/11 17h -> 14/11 15h). Impossible de tester une detention de 96 h dessus : on aurait moins de
5 observations. **A la fin de la campagne (19/11, ~192 h), le signal de positionnement des
leaders devient testable a 24 h de detention avec des departs toutes les 6 h, soit ~28
observations.** C'est le premier test a lancer ce jour-la.

### C-vicies-sexies. QUATRE LEVIERS TESTES, TROIS REFUTES — et la refutation la plus utile
de la session (14/11)

**LEVIER 1 — `k` PLUS GRAND : REFUTE.** La contrainte qui imposait k=4 (jambes sous 10 USD a
0,235x) avait disparu avec la marge croisee. Mais a horizon 96 h, TEST : **k=4 +64,6 %**, k=6
+31,3 %, k=8 +23,5 %, k=12 +24,7 %. **L'edge est concentre dans les EXTREMES du classement** ;
diversifier le dilue plus vite que ca ne reduit le repli. Verifie APRES dimensionnement : k=12
(repli 3,9 % -> 4,85x) rend +120 %/an contre k=4 (repli 5,9 % -> 3,50x) a +226 %. **k=4 gagne.**

**LEVIER 2 — PONDERER PAR 1/VOLATILITE : REFUTE, partout.** funding/egal/k=4 TEST +64,6 % contre
funding/1-vol/k=4 **+24,3 %**. **L'edge VIT dans les coins volatils** — les alts speculatifs au
positionnement encombre. Les sous-ponderer sous-pondere le signal lui-meme.

**LEVIER 3 — LE MOMENTUM DIRECT : REFUTE LOURDEMENT, et c'est la decouverte la plus utile.**
Hypothese testee : « le funding n'est qu'un PROXY du momentum, donc classer directement sur le
rendement passe garderait le gain de prix SANS payer le funding ». Resultat : **-44,2 % en TEST**
a k=4, et **negatif a tous les k et toutes les ponderations**. **C'est l'inverse qui est vrai :
le funding porte une information que le rendement passe ne contient pas.** Le funding mesure
**l'ENCOMBREMENT DU POSITIONNEMENT**, pas la performance passee — et le momentum a 96 h est en
fait legerement moyen-reversif.
**C'EST LE MEILLEUR ARGUMENT DISPONIBLE POUR LE SIGNAL COPYVAULT** : si l'encombrement *deduit*
du funding fonctionne, l'encombrement *directement observe* dans les positions des leaders
devrait fonctionner au moins aussi bien, et avec moins de bruit.
(Le signal combine funding+momentum donne TEST +65,7 % mais TRAIN **-25,0 %** : 90 points
d'ecart, instable, ecarte par le critere.)

**LEVIER 4 — LA COMPOSITION : REELLE.** `annualise` etait SIMPLE. 91 rotations par an
reinvestissent le gain. `_compose()` ajoute, et les deux sont publies : la version simple reste
la bonne pour COMPARER des horizons, la composee pour dire ce que le capital devient.

**UNE ERREUR DE MA PART, ATTRAPEE EN ROUTE.** J'ai d'abord dimensionne sur le pire repli des
fenetres **NON CHEVAUCHANTES** (-6,07 %), ce qui donnait 5,84x de levier et un annualise a quatre
chiffres. Mais l'echantillon complet contient une fenetre de 96 h a **-12,14 %** : elle a
REELLEMENT existe, je l'avais seulement manquee en ne gardant qu'une detention sur quatre.
**Le dimensionnement doit venir de TOUTES les fenetres.** Et le vrai risque n'est pas la pire
detention isolee mais le **REPLI CUMULE** de la courbe, car plusieurs mauvaises detentions
d'affilee se composent.

**LA COURBE DE CAPITAL REELLE** — 51 detentions disjointes de 96 h, 204 jours, depart 350 USD,
dimensionnement sur le pire des 204 fenetres (-12,14 %) :

```
facteur  levier   final   compose/an   pire pas   REPLI CUMULE   liquide ?
   2,0    3,41x    977 U    +528,1 %     -20,7 %      -33,7 %       non
   3,0    2,41x    766 U    +305,9 %     -14,6 %      -24,5 %       non
   4,0    1,87x    657 U    +208,6 %     -11,3 %      -19,2 %       non
   6,0    1,28x    550 U    +124,2 %      -7,8 %      -13,5 %       non
   8,0    0,98x    497 U     +87,4 %      -5,9 %      -10,3 %       non
```

**A facteur 4 : 350 -> 657 USD en 204 jours, repli cumule maximum -19,2 %, aucune liquidation.**

**CE QUE CES CHIFFRES NE SONT PAS.** 51 detentions, **un seul regime** (avril-novembre 2026),
57 % de pas positifs. Un annualise a trois chiffres n'est **pas une prevision** : c'est
l'extrapolation d'un edge mince a fort levier. **La colonne a regarder est le REPLI CUMULE**, pas
le capital final. Et le livre reste **LONG LA FOULE**, donc combustible d'une cascade.

**LA FILE, DECOMPOSITION CORRIGEE** (3 lots, 28 013 cas) : avec `instant_ordre_ms`, la **capture
repasse POSITIVE a +0,69 bp** — l'attribution est reparee. Le net reste negatif (**-5,84 bp a
5 s**, remplissage 66,2 %). **La refutation du maker tient**, et son diagnostic est maintenant
lisible : ce n'est pas le demi-spread qui manque, c'est la derive qui le reprend.

### C-vicies-septies. CHASSE AUX LEVIERS, SUITE — et la correction de mon chiffre de tete
(14/11)

**LE LEVIER TROUVE : L'EDGE EST ENTIEREMENT DANS LA JAMBE SHORT — et il faut quand meme garder
la jambe longue.**

```
livre              funding    prix   net/det  annual.  pos.   pire   rho marche
LONG (fdg haut)    -0,247 % +0,276 % -0,101 %  -9,2 %  48%  -17,0 %   +0,781
SHORT (fdg bas)    -0,308 % +1,485 % +1,047 % +95,5 %  64%  -42,7 %   -0,797
LES DEUX           -0,278 % +0,881 % +0,474 % +43,2 %  58%  -12,1 %   +0,190
```

La jambe longue **perd -9,2 %/an**. Mais la supprimer fait passer le repli de -12,1 % a
**-42,7 %** et le rho au marche de +0,190 a **-0,797**. Apres dimensionnement : **les deux jambes
+80,8 %/an contre +54,4 % pour le short seul**. **La jambe longue ne se paie pas en rendement,
elle se paie en RISQUE** — c'est une assurance, et elle vaut plus que son cout. Le livre
dollar-neutre est donc justifie **par la mesure**, plus par hypothese.

**BALAYAGE DU TAUX DE COUVERTURE, juge APRES dimensionnement** (juger sur le brut elirait 0 %) :

```
couv.  net/det  brut/an    pire     rho  levier  APRES DIM.  USD/an | TRAIN    TEST
   0%  +1,047%  +95,5 %  -42,7 %  -0,797  0,57x    +54,4 %    +190  | +159,9 %  +31,1 %
  50%  +0,664%  +60,6 %  -22,3 %  -0,368  1,06x    +64,3 %    +225  |  +91,8 %  +29,4 %
 100%  +0,473%  +43,1 %  -12,1 %  +0,190  1,87x    +80,5 %    +282  |  +57,7 %  +28,6 %
```

**Monotone : la couverture COMPLETE gagne.** Le brut chute, mais le repli chute PLUS VITE, donc
le levier autorise compense au-dela.

**MAIS LA COLONNE TEST EST PLATE** (+28,6 a +31,1 %) alors que TRAIN va de +57,7 a +159,9 % :
**le +95,5 % du short seul est un artefact du TRAIN.**

**CORRECTION DE MON CHIFFRE DE TETE.** Recalcul en ne gardant que les detentions dont la DECISION
tombe dans la seconde moitie, et en dimensionnant sur le repli de cette moitie :

```
              n    net/det   brut/an    pire    pos.  levier   sur capital   USD/an
TRAIN       102   +0,632 %  +57,7 %   -7,2 %   65 %   2,96x    +170,7 %      +598
TEST        102   +0,315 %  +28,8 %  -12,1 %   51 %   1,87x     +53,7 %      +188
```

**L'ESTIMATION HONNETE HORS ECHANTILLON EST +188 USD/AN, pas +282.** La degradation TRAIN->TEST
d'un facteur 3 est la signature d'un surapprentissage partiel. Et **51 % de detentions positives
en TEST : c'est un pile ou face** — l'edge vient de l'ASYMETRIE (gains plus gros que pertes), pas
de la frequence. La variante « disjointe » afficherait +640 USD/an, mais elle manque les pires
fenetres (-6,1 % contre -12,1 %) : c'est le piege deja attrape plus haut.

**CE QUI RESTE SOLIDE, ET CE QUI NE L'EST PAS.** Les gains obtenus en corrigeant la **marge
croisee** et l'**horizon** sont des faits STRUCTURELS sur la venue et sur le cout — ils ne
dependent d'aucun parametre ajuste. Le SIGNAL, lui, se degrade hors echantillon.

**AUTRES LEVIERS TESTES CETTE SESSION, TOUS REFUTES :**
* **fenetre de classement** (24/48/96/168/336 h) : motif qui ALTERNE (24 bon, 48 mauvais, 96 bon,
  168 mauvais) — du bruit, pas une structure. Aucun gagnant a elire.
* **variation du funding** au lieu du niveau : +4,8 % a 96 h, -13,2 % a 24 h -> c'est le NIVEAU
  d'encombrement qui predit, pas son acceleration.
* **demoyennage transversal** : **mon test etait VIDE PAR CONSTRUCTION**. Soustraire la moyenne
  transversale a une heure donnee retire la MEME constante a tous les coins, donc ne change AUCUN
  rang. Les ecarts minuscules observes ne venaient que des coins a heures manquantes. Un vrai
  demoyennage devrait normaliser par la DISPERSION transversale, ou se faire par groupes.

### C-vicies-octies. LE COUT MESURE AU LIEU D'ETRE SUPPOSE — une correction contre moi, un
levier pour moi (14/11)

**CIBLAGE DE VOLATILITE : REFUTE comme levier robuste.** A levier MOYEN identique (1,87x), le
repli cumule passe de -50,3 % (statique) a -47,1 % avec une fenetre de 8 detentions, mais
**-59,2 % a 16 et -55,1 % a 24**. Une fenetre sur trois ameliore : c'est du bruit, pas un levier.
Et le levier maximum grimpe a **4,71x** dans les moments calmes, ce qui creverait le budget de
marge. (Ces courbes composent des fenetres chevauchantes, donc les montants absolus sont gonfles ;
le biais etant identique sur toutes les lignes, la COMPARAISON reste valide.)

**LE SLIPPAGE : MESURE, ET PIRE QUE SUPPOSE.** Je le supposais a 2 bps depuis le debut. Mesure sur
**60 000 instantanes de carnet** (les carnets trop minces sur 5 niveaux sont ECARTES, jamais
comptes comme slippage nul) :

```
notionnel        n    ecartes   median    moyen     p90      p99
      50U  119 997        3    3,097b   4,276b   9,453b  21,862b
     100U  119 843      157    3,160b   4,363b   9,616b  22,385b
     500U  118 637    1 363    3,696b   4,994b  10,723b  27,129b
```

**4,36 bps en moyenne, pas 2.** Et il bouge a peine avec la taille (3,10 b a 50 USD contre 3,70 b
a 500 USD) : **ce n'est donc PAS un probleme de profondeur, c'est le DEMI-SPREAD** d'un univers de
187 coins dont des alts peu liquides. Mon cout taker reel vaut **17,7 bps**, pas 13.

**ET CE DIAGNOSTIC OUVRE LE LEVIER COMPENSATEUR.** Si le cout est domine par le spread, **un ordre
passif ne le paie pas : il l'encaisse.** Le maker n'avait ete refute que comme **STRATEGIE A 30 s**
(markout net -5,84 bps). Comme **METHODE D'ENTREE** d'une position tenue 96 h, le calcul s'inverse :
* taker : 4,5 b de frais + 4,36 b de demi-spread = **8,86 b par franchissement** ;
* maker : 1,5 b de frais - 0,69 b de capture mesuree + 2,16 b de selection adverse a 10 s =
  **~2,97 b**.
La selection adverse est un cout **PONCTUEL a l'entree**, exactement comme le spread, et sur un
signal a 96 h ses quelques bps sont du bruit. **Surtout, l'attente est GRATUITE** : le remplissage
mesure de 66,2 % portait sur 30 s, quand un signal a 96 h peut patienter des heures.
**Le maker refute a 30 s et justifie a 96 h n'est pas une contradiction : c'est le meme chiffre lu
au bon horizon.**

```
scenario                      cout/jambe  TEST brut/an  levier  sur capital  USD/an
suppose (2 b de slippage)        13,0b      +28,8 %     1,87x    +53,7 %     +188
taker MESURE (4,36 b)            17,7b      +24,4 %     1,86x    +45,5 %     +159
maker entree, taker sortie       11,8b      +29,8 %     1,87x    +55,7 %     +195
maker aux DEUX bouts              5,9b      +35,2 %     1,88x    +66,0 %     +231
```

**L'ESTIMATION HONNETE TOUT TAKER TOMBE A +159 USD/AN** (mon +188 reposait sur un slippage
sous-estime). **Avec l'entree passive aux deux bouts : +231 USD/AN.**

**LE RISQUE QUE CE CALCUL NE CHIFFRE PAS, ET QU'IL FAUT MESURER LE 19/11** : le taux de
remplissage passif **a l'echelle de l'HEURE** n'est pas mesure — seuls 30 s l'ont ete. Un ordre
passif non rempli, c'est une jambe absente, donc un livre desequilibre et un beta de marche
reintroduit. Tant que ce taux n'est pas mesure, le **+231 est un plafond, pas une estimation**.

### C-undetricies. LE DECOUPAGE EN TRANCHES — x2,4, et c'est structurel (14/11)

**LE BON CADRAGE, QUE JE N'AVAIS PAS.** L'identite du PnL est
`USD/an = capital x brut / (D x facteur + mmr)`. **La quantite a maximiser est donc `brut/D`, pas
le brut.** Tout ce que j'avais teste qui augmentait le brut en gonflant le repli etait perdu
d'avance (le short seul : +95,5 % de brut, mais -42,7 % de repli).

**LE LEVIER TROUVE.** Je posais tout le livre **a un seul instant** : une mauvaise entree frappait
100 % du capital. En **4 tranches d'un quart entrees a 24 h d'ecart**, chacune tenue 96 h, le
capital reste INTEGRALEMENT deploye et le rendement moyen est **INCHANGE** — seul le MOMENT de
l'entree change. Mais le repli s'effondre, et c'est lui qui fixe le levier.

```
TEST (hors echantillon), taker MESURE 17,7 b
1 bloc, entree unique   brut +24,4 %/an   D 12,19 %   1,86x   ->  +159 USD/an
4 tranches /24 h        brut +24,4 %/an   D  4,34 %   4,47x   ->  +382 USD/an   x2,40

TEST, maker aux deux bouts 5,9 b
4 tranches /24 h        brut +35,2 %/an   D  4,23 %   4,57x   ->  +562 USD/an   x2,43
```

**Le gain est de x2,4 en TRAIN comme en TEST et sous LES DEUX hypotheses de cout.** Cette
stabilite signe un effet **structurel**, pas un ajustement — et c'est attendu, puisque le
decoupage ne touche pas au signal.

**DEUX PIEGES TRAVERSES POUR DE VRAI, MAINTENANT VERROUILLES PAR DES TESTS**
(`dimensionnement_croise.repli_tranche`, 5 tests) :
1. **Ne pas diviser la perte par 4.** Mon premier calcul divisait la perte par le nombre de
   tranches TOUT EN gardant le capital deploye : il comptait la diversification **deux fois** et
   annoncait +792 USD/an. Les tranches detiennent des actifs semblables sur des periodes qui se
   recouvrent, donc **elles peuvent perdre ENSEMBLE**. Le repli correct est le pire de la
   **MOYENNE MOBILE de 4 detentions consecutives**.
2. **Juger les deux structures sur les MEMES fenetres.** Ma ligne « 1 bloc » lisait son repli sur
   une detention sur quatre (D = 7,47 %), ce qui lui laissait **CHOISIR son moment d'entree** — ce
   qu'aucun livre ne peut faire. Son vrai D est le pire de TOUTES les fenetres : **12,19 %**.

**TRAJECTOIRE DE LA SESSION, en estimation HORS ECHANTILLON :**
```
point de depart (jambe nue, 720 h, slippage suppose)      +31 USD/an
marge croisee corrigee + horizon 96 h                    +188
slippage MESURE a 4,36 b (correction CONTRE moi)         +159
decoupage en 4 tranches                                  +382
plafond si l'execution passive tient                     +562
```

**LE LEVIER SUIVANT, IDENTIFIE MAIS PAS TESTABLE AUJOURD'HUI : LA LARGEUR DE L'UNIVERS.** Le
coffre contient le funding de **90 coins** alors qu'il y a des bougies pour **263** et que la venue
liste plus de **200 perps**. Elargir la collecte de funding elargirait la section transversale —
donc des queues plus extremes (signal plus fort) ET plus de diversification (D plus bas), les deux
termes de `brut/D` dans le bon sens. **C'est un manque de COLLECTE, pas de strategie**, et c'est
actionnable sur la campagne.

### C-duotricies. MISSION « 5 USD/JOUR PROUVE » — ce que la mesure donne, et le protocole
gele (14/11)

**L'EQUATION, D'ABORD.** 5 USD/jour sur 350 USD = 1 825 USD/an = **521 %/an**. Avec
`levier <= 1/(D x facteur + mmr)` et `mmr = 5 %`, **meme un repli NUL plafonne a 20x**. Au
dimensionnement le plus imprudent possible (facteur 1, qui garantit la liquidation au premier
evenement pire que l'historique), le signal de depart donnait **3,6 USD/jour**. La cible ne se
comble donc PAS par le levier.

**DEUX DIMENSIONS NON EPUISEES, EXPLOREES.** `k=2` et `k=3` n'avaient jamais ete testes a 96 h, et
le nombre de tranches non plus. Resultat a 8 tranches : `k=3` donne **+80,4 %/an** quand `k=2`
donne +28,8 % et `k=4` +44,0 %.

**J'AI D'ABORD CRU A UN PIC DE BRUIT — ET JE ME TROMPAIS.** Un pic isole entoure de valeurs basses
est la signature du bruit (mon propre critere, enonce pour le balayage d'horizon). Verification sur
**TROIS TIERS** au lieu de deux moities :

```
  k | tiers 1 | tiers 2 | tiers 3 | ecart-type
  1 | +250,3% |  +52,6% |  +47,9% |   94,4     <- LE vrai bruit
  2 | +154,0% |  +22,4% |  +51,9% |   56,4
  3 | +106,6% |  +91,4% |  +63,3% |   17,9     <- le plus STABLE
  4 |  +79,4% |  +64,3% |  +19,4% |   25,5
  6 |  +39,8% |  +44,8% |   +0,8% |   19,7
```

`k=3` est positif sur les trois tiers avec la plus faible dispersion des `k` rentables : **retenu
pour sa STABILITE, pas pour son sommet.** Le pic apparent n'etait qu'un artefact de la coupe en
deux.

**CE QUE LA MESURE DONNE** (k=3, 8 tranches, 96 h, D = 6,24 % sur 407 fenetres) :

```
hypothese de brut          brut/an |   f=4      |   f=3      |   f=2
tiers le plus FAIBLE       +63,3 % | 2,03 U/j   | 2,56 U/j   | 3,47 U/j
moyenne des trois tiers    +87,1 % | 2,79 U/j   | 3,52 U/j   | 4,78 U/j
tiers le plus fort        +106,6 % | 3,41 U/j   | 4,31 U/j   | 5,85 U/j
```

**AUCUNE ligne n'atteint 5 USD/jour au facteur 4.** La cible n'apparait qu'en cumulant le
dimensionnement le plus agressif (facteur 2, liquidation a -17,5 %) ET l'hypothese de rendement la
plus favorable. **La fourchette honnete au dimensionnement prudent est 2,0 a 3,5 USD/jour.**

**ET LE PROBLEME PLUS GRAVE QUE CE CHIFFRE : LA SECONDE MOITIE N'EST PLUS HORS ECHANTILLON.**
Je l'ai consultee pour choisir l'horizon, `k`, la ponderation, le taux de couverture et le nombre
de tranches. **A force de regards, un temoin devient un complice** : le mot « prouve » n'a plus de
sens sur ces donnees. C'est exactement le mecanisme qui produit un PBO de 0,81.

**D'OU LE PROTOCOLE GELE** : `docs/PREENREGISTREMENT_5USD.md`, empreinte SHA-256
**1228b273d9ec7d3bd79e1d3d64baafde**, ecrit AVANT tout regard sur la fenetre de jugement. Il fixe
les 12 parametres, le cout retenu (**taker 17,7 bps mesure**, PAS l'hypothese maker dont le
remplissage horaire n'est pas mesure), et **les attentes chiffrees d'avance** (2,03 / 2,79 /
3,41 USD/jour au facteur 4).
`tools/juger_preenregistrement.py` l'execute **une fois, sans aucune option reglable** — un outil
qui laisserait regler `k` apres avoir vu le resultat transformerait le jugement en recherche. Il
**verifie l'empreinte** et REFUSE de juger si le protocole a ete reecrit entre-temps.

**DATE REELLE DU PREMIER VERDICT : PAS LE 19/11.** L'outil a refuse de juger, et son refus est
instructif : une fenetre demande 96 h de classement **plus** 96 h de detention, et le resultat
n'existe qu'une fois la detention terminee. Huit tranches a 12 h d'intervalle exigent donc
**~18 jours posterieurs au gel**. La campagne en donne six. **Premier verdict vers le 23-25/11,
verdict robuste debut decembre** ; le funding s'accumule tout seul tant que le collecteur tourne.

**LES TROIS VOIES POUR COMBLER L'ECART, par ordre d'effet attendu :**
1. **Elargir l'univers de funding de 90 a plus de 200 coins** — il y a des bougies pour 263 coins
   et la venue liste plus de 200 perps. Queues plus extremes (signal) ET plus de diversification
   (D plus bas) : **les deux termes de `brut/D`**. C'est un manque de COLLECTE.
2. **Le signal des leaders**, si l'encombrement directement observe bat l'encombrement deduit du
   funding.
3. **Le capital** : a 161 %/an sur capital, 5 USD/jour demande **1 134 USD** au lieu de 350.
   C'est une decision, pas une mesure.

### C-tritricies. ELARGISSEMENT DE L'UNIVERS DE FUNDING — le levier mis en oeuvre (14/11)

**LE DIAGNOSTIC.** `coins_suivis()` rend **261 coins**, tous abonnables sur la venue. Les bougies
en couvrent 263. Mais le funding n'en couvre que **90 : 171 coins n'ont JAMAIS ete servis.**
Ce n'etait pas une limite de conception, c'etait un **budget de temps** : dans
`backfill_candles_vaults`, la passe bougies consomme ses 3 000 s **avant** que la passe funding
n'obtienne ses 1 500 s, et le tout ne tourne que toutes les 4 h.

**POURQUOI C'EST LE BON LEVIER.** La largeur de la section transversale joue sur les **deux**
termes du rapport `brut/repli` qui fixe le resultat : des queues plus extremes (signal plus fort)
ET plus de diversification (repli plus bas). C'etait le levier n°1 de la liste du
preenregistrement, et c'est un manque de COLLECTE, pas de strategie.

**CE QUI A ETE FAIT.**
1. **Option `--seulement-funding`** dans `tools/backfill_candles_vaults.py` (3 tests, dont un qui
   verrouille que le comportement PAR DEFAUT est inchange — la campagne reexecute ce fichier
   toutes les 4 h — et un qui refuse la combinaison contradictoire avec `--sans-funding`).
2. **Budget funding porte de 1 500 a 7 200 s** dans l'entree `backfill-candles-vaults` du
   REGISTRE. Bornes verifiees : 3 000 + 7 200 = **10 200 s < 14 400 s** d'intervalle, et
   l'invariant anti-relance `limite_minutes x 60 > intervalle_s x 1,5` (28 800 > 21 600) tient.
   136 tests de registre passent.

**POURQUOI PAS DE PASSE CONCURRENTE, bien qu'elle ait ete preparee.** `sauver_etat` est atomique
(`write_text` puis `os.replace`) et fusionne l'etat existant, donc le CONTENU ne se corrompt pas.
**Mais les deux processus partageraient le meme chemin `.tmp`** : P1 ouvre le tmp, P2 le tronque,
P1 ecrit, P2 ecrit, P1 remplace — et un etat partiel devient l'etat officiel. On laisse donc la
campagne faire ses passes seule.

**DELAI ATTENDU.** Au debit reserve au rattrapage (**100 de poids/min**, soit 27 s par page et
~270 s par coin pour 10 pages), les 171 coins manquants demandent **~12,8 h de passe**. A 7 200 s
de funding par cycle de 4 h, cela fait **~7 cycles, soit un peu plus d'une journee** — donc bien
avant la date de jugement du 23-25/11. La campagne prend le nouveau budget a sa prochaine
relance de ce collecteur, sous 4 h.

**CE QUI RESTE A MESURER APRES L'ELARGISSEMENT** : l'univers passant de 90 a 261 coins, le
`brut/repli` doit etre **remesure**, et le protocole gele l'a ete sur 90 coins. **Si
l'elargissement change le resultat, c'est un NOUVEAU protocole** : il devra etre juge sur une
fenetre encore jamais regardee, pas sur celle du preenregistrement actuel.

### C-quattuortricies. DIVERSIFICATION PAR HORIZON — x2,07, et consolidation de l'outillage
(14/11)

**LE LEVIER : DIVERSIFIER L'HORIZON, pas seulement le moment d'entree.** Le decoupage en
8 tranches diversifiait le MOMENT a horizon fixe. Mais le balayage avait trouve **24, 48, 96, 168
et 336 h TOUS positifs** : ce sont donc cinq livres imparfaitement correles.

```
96 h seul            brut +68,8 %   repli 6,35 %   3,29x   ->  +2,17 USD/jour
les CINQ horizons    brut +70,5 %   repli 2,79 %   6,19x   ->  +4,18 USD/jour
```

**Le repli tombe d'un facteur 2,3 pendant que le brut ne bouge pas** : le levier double. Et le
gain tient PARTOUT — TRAIN x1,79, TEST x2,07, tiers1 x2,27, tiers2 x1,52, tiers3 x2,26 : **jamais
moins de x1,5**, ce qui signe un effet structurel.

**AUCUNE SELECTION, et c'est ce qui rend le chiffre credible** : les cinq horizons sont
equiponderes, et le meilleur sous-ensemble trie a la main (24+96+336) ne fait que **3 % de mieux**
(+4,32 contre +4,18). Il n'y a rien a cueillir.

**LE PIEGE ECARTE** : on ne somme pas les replis des horizons (ce serait supposer qu'ils perdent
toujours ensemble) et on ne les divise pas par leur nombre (ce serait supposer qu'ils ne perdent
jamais ensemble). A tout instant la valeur du livre est la moyenne ponderee des detentions
**ACTIVES** de chaque horizon : c'est cette serie-la que la marge regarde, et c'est elle qu'on
mesure.

**RESULTAT OFFICIEL** (`tools/mesurer_strategie.py`, facteur 4, slippage mesure et persiste) :
```
periode                taker (retenu)     maker (plafond)
pire tiers (BORNE BASSE)   +3,78 U/j          +4,89 U/j
hors echantillon (TEST)    +4,56 U/j          +5,69 U/j
meilleur tiers             +5,19 U/j          +6,34 U/j
```
**La cible de 5 USD/jour est ATTEINTE dans le meilleur tiers et dans le scenario maker, et
MANQUEE de 9 % dans le cas de reference.**

**TROIS DEFAUTS D'OUTILLAGE CORRIGES, qui comptent autant que le levier :**
1. **Le depot contredisait le protocole gele.** `tools/mesurer_carry_patient.py` tournait encore
   avec `k=5`, une detention de **720 h** (le PIRE point du plateau rentable) et un slippage
   **SUPPOSE a 2 bps** : quiconque le lancait obtenait un autre chiffre que le preenregistrement.
   Il **refuse desormais de tourner** et renvoie vers l'outil officiel ; son code reste lisible,
   car c'est lui qui a refute le carry et une refutation doit pouvoir etre reverifiee.
   *(Ma premiere tentative de neutralisation a echoue sur une ancre erronee — le fichier commence
   par un shebang — et l'outil a continue d'afficher ses vieux chiffres jusqu'au second essai.)*
2. **Les mesures vivaient dans des scripts jetables.** Elles sont desormais dans
   `tools/mesurer_strategie.py` (chaine complete, aucun parametre de strategie reglable) et
   `tools/mesurer_slippage.py` (mesure **et PERSISTE** le slippage, lu ensuite par l'outil
   officiel : tant qu'un chiffre reste une constante en dur, il ne se corrige jamais seul).
3. **Le repli etait calcule par periode.** Une periode courte et chanceuse gagnait donc du levier
   par hasard — `TEST` affichait 4,53 % contre 6,36 % pour l'histoire entiere. Le repli vient
   maintenant de **TOUTE l'histoire**, impose a chaque periode. **Troisieme occurrence de ce
   piege dans la session**, sous une troisieme forme. La correction a FAIT BAISSER le chiffre de
   reference de +2,89 a +2,20 USD/jour en mono-horizon : elle fonctionne.

**PROTOCOLE v2 GELE** : `docs/PREENREGISTREMENT_5USD_V2.md`, empreinte
**a8643d8233e0c4540c5eece6f117cbc8**. Il **remplace la v1**, exactement comme la v1 l'exigeait
(« si l'elargissement change le resultat, c'est un NOUVEAU protocole a juger sur une fenetre
jamais regardee »). La v1 reste au depot comme trace de ce qui avait ete promis avant de mesurer.
**Premier verdict pas avant le 1er decembre** : l'horizon le plus long (336 h = 14 j) plus la
fenetre de classement et 8 tranches l'exigent.

### C-quintricies. POURQUOI LE VERDICT COMPLET N'EST PAS AVANT LE 2 DECEMBRE (14/11)

**TROIS CONTRAINTES S'ENCHAINENT, et la troisieme commande.**
1. **Le gel est le 14/11** : toute decision anterieure a servi a CHOISIR les parametres, donc la
   premiere decision propre est le 15/11. Non negociable.
2. **8 tranches a 12 h d'intervalle** : la 8e decision tombe le 18/11 a midi. C'est mon seuil —
   on pourrait juger sur moins, avec moins de confiance.
3. **Un resultat n'est jugeable que COMPLET** : decision + horizon. Et l'horizon le plus long du
   portefeuille vaut **336 h = 14 jours**.

```
horizon   8e decision   resultat complet   nature du verdict
    24h    18/11 12h       19/11 12h       partiel
    48h    18/11 12h       20/11 12h       partiel
    96h    18/11 12h       22/11 12h       partiel (l'horizon de la v1)
   168h    18/11 12h       25/11 12h       partiel
   336h    18/11 12h       02/12 12h       LE PORTEFEUILLE COMPLET
```

**LE CALENDRIER EST DESORMAIS PREENREGISTRE** (ajout a la v2, ecrit alors que l'outil de jugement
comptait ZERO fenetre — il ne change aucun parametre, il declare QUAND regarder). Nouvelle
empreinte v2 : **f42302daa601849273864e86f80fde4d**.
Preenregistrer le calendrier evite qu'un verdict partiel du 19/11 ressemble a un coup d'oeil
opportuniste.

**LA REGLE QUI REND LES PARTIELS LEGITIMES** : ils sont **rapportes, JAMAIS utilises pour
re-choisir**. Si le 24 h decevait le 19/11 et que je l'enlevais de la configuration, je reprendrais
la selection sur des donnees de jugement — exactement ce que le preenregistrement existe pour
empecher. Et un horizon seul porte un repli bien plus eleve que le portefeuille (6,35 % pour le
96 h contre 2,79 % pour les cinq) : **un partiel faible n'infirme PAS le portefeuille complet, et
un partiel fort ne le confirme pas.**

**LE JUGE A ETE REALIGNE SUR LE PROTOCOLE.** `tools/juger_preenregistrement.py` jugeait encore un
SEUL horizon de 96 h alors que la v2 porte cinq horizons : le juge et le juge-able divergeaient.
Il importe desormais `series_par_horizon`, `juger_multi` **et les constantes de cout** depuis
l'outil officiel — deux definitions du meme cout finiraient par divulguer, et le juge annoncerait
un chiffre que l'outil de mesure ne reproduirait pas. Il affiche l'etat de chaque horizon, et
refuse le verdict complet tant qu'un seul manque.

**EFFET DEJA VISIBLE DE L'ELARGISSEMENT** : l'univers de funding est passe de **90 a 94 coins**
depuis le relevement du budget. La cible est 261.

**ET LE PROCHAIN LEVIER EST IDENTIFIE PAR L'IDENTITE ELLE-MEME.** Avec D tombe a 2,79 %, le
denominateur `D x facteur + mmr` vaut `0,1116 + 0,05` : **le mmr est passe de 16 % a 31 % du
total**. En faisant baisser le repli, le multi-horizons a PROMU la marge de maintenance au rang de
deuxieme contrainte — et je l'ai SUPPOSEE a 5 % en appliquant le palier le plus dur a tout le
livre. Or c'est une somme ponderee par jambe, donc **mesurable** : a 2,5 %, le levier passerait de
6,19x a 7,32x, soit **+18 % et la cible de 5 USD/jour franchie**. Mesure a faire : le levier
maximum de chaque coin effectivement retenu (famille `asset_ctx` du coffre).

### C-sextricies. LE MMR MESURE : -34 % SUR LE RESULTAT, et le filtre qui ne sauve rien
(14/11)

**J'AVAIS PREDIT UN MMR PLUS BAS. LA MESURE DIT L'INVERSE, ET BIEN PLUS HAUT.**
Le levier maximum par coin n'etait ni dans `asset_ctx` ni dans `hl_univers_perps.json` : il vient
de l'endpoint public `meta` (`universe[].maxLeverage`), **une seule requete**, persistee dans
`runtime/data/levier_max_par_coin.json` (179 coins). Sur **11 514 jambes reellement ouvertes** :

```
mmr SUPPOSE (palier alt 10x)       :  5,00 %
mmr MESURE, pondere par frequence  : 12,32 %
pire coin retenu                    : 16,67 %

coin     jambes   part  lev.max     mmr
XMR        1302  11,3%      5x   10,00%
VVV         664   5,8%      3x   16,67%
GRASS       560   4,9%      3x   16,67%
MOVE        481   4,2%      3x   16,67%
```

**ET LA CAUSE ETAIT DEJA DANS MES PROPRES MESURES.** J'avais etabli que **l'edge vit dans les
coins volatils** (la ponderation 1/volatilite le detruisait : +24,3 % contre +64,6 %). Or la venue
assigne a ces coins le levier maximum le PLUS BAS, **parce qu'**ils sont volatils. Les deux faits
sont le meme fait, et je ne l'avais pas vu.

**UNE PHRASE DE MOI A CORRIGER AU PASSAGE** : j'avais ecrit que le mmr a retenir est celui du PIRE
coin. C'est faux. La maintenance vaut `somme(notionnel_i x mmr_i)`, soit `notionnel x
moyenne(mmr_i)` pour un livre equipondere : c'est la **MOYENNE PONDEREE** (12,32 %). Retenir le
pire coin sur-dimensionnerait la marge d'un tiers.

**EFFET** : le chiffre de reference passe de **+4,56 a +3,02 USD/jour** (-34 %). Mesurer une
hypothese l'a rendue defavorable, et c'est le resultat qui compte.

**LE FILTRE SUR LE PALIER : REFUTE, et de la facon la plus nette.** Le mmr pesant desormais 52 %
du denominateur, ecarter les coins a 3x semblait evident. Mesure :

```
seuil  coins  brut/an   repli     mmr  levier   USD/j TEST
   3x     94   +68,8%   2,79%  12,32%   4,26x     +3,02U
   5x     68   -44,9%   5,62%   8,38%   3,24x     -1,09U
  10x     31    +2,4%   3,73%   4,94%   5,04x     +0,94U
```

**Retirer le palier 3x n'affaiblit pas le signal : il l'INVERSE (-44,9 %).** L'edge vit
entierement la, et la venue exige la marge la plus haute precisement la. **Les deux sont
inseparables : aucun filtre ne les separe.**

**UN DEFAUT DE MON OUTIL, TROUVE EN VOULANT LIRE SES CHIFFRES** : la sortie `--json` se terminait
AVANT le bloc multi-horizons, donc le JSON et le texte ne disaient pas la meme chose. Deux sorties
du meme outil qui divergent, c'est la porte ouverte a citer un chiffre que l'outil n'a jamais
affiche. Corrige : le multi est calcule une fois, avant toute sortie. *(J'avais d'ailleurs commence
par recopier a la main un brut de 90,1 % en le croyant taker alors qu'il etait maker — raison de
plus pour lire les chiffres depuis l'outil et jamais a la main.)*

### MISSION « 5 USD NET PAR JOUR SUR 350 USD » — l'arithmetique complete

```
ETAT MESURE, facteur 4 : taker +3,02 | maker +3,76 | pire tiers +2,42 USD/jour

VOIE 1 — baisser la prudence (choix de RISQUE, pas une mesure)
  facteur  levier  liquide si   taker   maker
      4,0   4,26x      23,5%   +3,02U  +3,68U
      3,0   4,84x      20,7%   +3,42U  +4,18U
      2,0   5,59x      17,9%   +3,95U  +4,83U
      1,5   6,06x      16,5%   +4,29U  +5,24U   <- la cible, en maker seulement
      1,0   6,62x      15,1%   +4,68U  +5,72U

VOIE 2 — du capital (regle de trois sur le taux MESURE)
  facteur 4 : taker 580 USD | maker 475 USD
  facteur 3 : taker 511 USD | maker 419 USD
  facteur 2 : taker 443 USD | maker 362 USD

VOIE 3 — la BORNE DURE : repli NUL, mmr mesure inchange
  taker 5,74 | maker 7,01 USD/jour
  => meme en annulant TOUT le repli, 5 USD/jour exige 305 USD en taker.

VOIE 4 — cote repli, a 350 USD et facteur 4 : il faudrait 0,46 % contre 2,79 % mesure (-84 %).
```

**CONCLUSION HONNETE.** **5 USD/jour n'est pas atteignable sur 350 USD au dimensionnement
prudent.** Il l'est : en maker au facteur 1,5 (liquidation a -16,5 %), ou **avec 443 a 580 USD de
capital** selon la prudence retenue. La voie du capital est la seule qui ne demande ni de baisser
la garde ni de supposer une execution non mesuree.
Restent deux inconnues qui peuvent encore deplacer le chiffre, toutes deux en cours : **l'univers**
(94 coins sur 261 vises) et **le signal des leaders**.

### C-septtricies. LA STRATEGIE EST ENFIN DANS LE MOTEUR — et une decouverte sur ce qu'il
faisait (15/11)

**LA QUESTION ETAIT : « si j'ouvre le moteur, gagne-t-on de l'argent ? » LA REPONSE ETAIT NON.**
Verification faite : `carry_patient`, `dimensionnement_croise` et `mesurer_strategie` **n'etaient
cables NULLE PART** dans le moteur, l'interface ou le chemin live. Les +3,02 USD/jour etaient une
MESURE sur 211 jours d'historique, pas une simulation qui avait tourne.

**ET LE MOTEUR PORTAIT LA MAUVAISE DIRECTION.** `strategies/carry_ranking.py` classe par **carry
net predit par heure**, donc il LONGE le funding bas et SHORTE le haut : **c'est exactement le
sens refute** (-41,3 %/an, 8 detentions positives sur 25, le prix reprenant -4,901 % contre
+1,635 % de funding). Le moteur aurait ouvert la direction perdante.

**CE QUI A ETE LIVRE**

1. **`strategies/carry_transversal_inverse.py`** (10 tests) — le livre dans le sens qui mesure
   positif, ecrit selon le contrat de `strategies/` : **pur, il PROPOSE, le noyau dispose**. Il
   refuse explicitement (a) moins de `2k` coins classables — un livre tronque en silence changerait
   la strategie ; (b) une jambe sous le notionnel minimum — proposer un livre non placable serait
   proposer un livre qui n'existera pas ; (c) une fenetre qui touche l'instant de decision. Sa
   `confidence` vaut **0,58**, le taux de detentions positives mesure : l'edge vient de
   l'ASYMETRIE, et annoncer 0,9 serait un mensonge. Un test interdit toute surface d'execution.
2. **`tools/paper_carry_inverse.py`** (6 tests) — l'executeur paper EN AVANT, avec grand livre
   atomique. Il **DECIDE au fil du temps** : sa decision est ecrite AVANT que le resultat
   n'existe. **C'est la difference entre « la strategie aurait gagne » et « la strategie a
   gagne »**, et c'est la seule mesure qui verifiera aussi le remplissage passif reel.
3. **Entree `paper-carry-inverse` au REGISTRE**, cadence 12 h (le pas de tranche du protocole).
   Invariant anti-relance verifie : 72 000 > 64 800. 136 tests de registre verts.

**POURQUOI PAS UNE GREFFE DANS LE MOTEUR, ET C'EST UN CHOIX ASSUME.** `LANCER_HYPERSMART` n'est
pas une boucle : c'est un menu de ~32 commandes qui demarre, par defaut, un **serveur UI**
(`python -m hl_observer ui`) plus un poller, via `tools/start_hypersmart_simulation.ps1`, au-dessus
des collecteurs **dont la campagne en cours depend**. Greffer une strategie dans ce chemin de
decision sans l'avoir compris entierement risquait la collecte — **et une collecte perdue ne se
rattrape pas**. L'executeur fait le meme travail a cote, sans rien toucher.

**PREMIERE EXECUTION REELLE** (15/11) : **6 positions ouvertes**, 248,50 USD par jambe sur un
notionnel de 1 491 USD (350 x 4,26) — **LONG XMR, NEAR, VIRTUAL / SHORT AVAX, JUP, MELANIA**.
Relance immediate : **aucune position dupliquee** (« instant deja decide »), l'idempotence est
prouvee et non supposee. Zero position fermee, et c'est voulu : **il faut 96 h pour un premier
resultat, un PnL avant l'echeance serait une marque, pas un gain.**

**EFFET SECONDAIRE UTILE** : l'univers de funding est passe de 90 (14/11 matin) a **114 coins**.
Le relevement du budget funding a 7 200 s produit son effet, cible 261.

**CE QUE LA CAMPAGNE NE PRENDRA PAS** : le lanceur lit `DEFAULT_NAMES` de
`watch_economic_collectors.py` **au demarrage**, et on ne redemarre pas une collecte vivante.
L'entree du registre agira a la prochaine campagne ; en attendant, la commande manuelle est
`python tools/paper_carry_inverse.py --root . --capital 350`.

**PREMIER RESULTAT PAPER ATTENDU : le 19/11** (96 h apres la premiere decision). Il se croisera
avec le verdict du protocole gele du 2 decembre. **Si les deux convergent, c'est une preuve ; si
elles divergent, la divergence dit ou l'execution mange le gain.**

### C-octotricies. LA PORTE DE PROMOTION — le labo parle au moteur, sans en faire une machine
a surapprendre (15/11)

**LA QUESTION : « si le labo trouve une meilleure strategie, le moteur doit s'en servir tout de
suite, c'est logique. » OUI — mais l'automatiser naivement serait la pire chose a construire.**

Le labo **SELECTIONNE**. Le meilleur de `N` candidats parait bon **par pur hasard** : c'est le
mecanisme exact du PBO de 0,81 mesure sur ce labo. Promouvoir le mieux mesure, c'est promouvoir
**le plus chanceux**. La session du 14/11 l'a prouve trois fois : `k=3` ressemblait a un pic de
bruit jusqu'a verification sur trois tiers ; le `mmr` suppose a 5 % valait 12,32 % une fois mesure
(**-34 %**) ; le repli calcule par periode offrait du levier par chance.

**`strategies/porte_de_promotion.py`, 15 tests. QUATRE CONDITIONS, SIX REFUS.**
1. **Le nombre d'essais est DECLARE** — meme contrat que `test_transversal.tester(..., essais=)`.
   Ne pas le declarer est un refus, **jamais un `essais=1` suppose**.
2. **La fenetre de jugement commence APRES le gel** — un candidat ne se juge pas sur les donnees
   qui l'ont choisi.
3. **Assez d'observations INDEPENDANTES** (8 minimum) — en dessous, une seule periode defavorable
   decide, ce qui s'est produit pour de vrai (une detention a -22,8 % ecrasait les cinq autres).
   Rend **`PAS_ENCORE`**, pas `REFUSE` : « pas encore mesurable » n'est pas « refute ».
4. **Le resultat doit etre positif ET COHERENT avec l'annonce.** Le refus le moins intuitif et
   l'un des plus utiles : **faire 5x MIEUX que promis est aussi un refus** — ce n'est pas une
   bonne nouvelle, c'est une fuite ou une erreur de mesure a trouver.
Plus l'**empreinte** : un candidat retouche a la main devient illisible, pas plus beau.

**LA CHAINE COMPLETE, COTE LABO INCLUS** (c'est la remarque juste de l'utilisateur : il fallait
aussi modifier le labo) :
* `ecrire_proposition()` — **COTE LABO**, gele un candidat et calcule son empreinte. Si `essais`
  manque, on ecrit quand meme pour que le refus soit **TRACE au lieu d'etre silencieux** ;
* `juger()` — **LA PORTE**, rend `PROMU` / `REFUSE` / `PAS_ENCORE` ;
* `enregistrer_promotion()` — **seul un `PROMU` est ecrit** ;
* `strategies_autorisees()` — **COTE MOTEUR, deny-by-default** : dossier absent, vide ou illisible
  -> `{}`, donc rien. Un systeme qui ouvre quand il ne sait pas est un systeme qui trade sur une
  erreur de lecture de fichier.
Aucune des trois couches ne peut court-circuiter les deux autres.

**UNE ERREUR D'ARITHMETIQUE DANS MA PROPRE FORMULE, ATTRAPEE PAR DEUX TESTS.** La premiere
version exigeait `0,5 + 0,5 x (1 - 1/sqrt(N))` plafonne a 0,75, et ma documentation annoncait
« a 4 essais -> 0,625 ». **C'etait faux** : cela vaut **0,75**, donc la formule tapait son plafond
**des 4 essais** et rendait la barre infranchissable pour tout candidat reel. Corrigee en
`min(0,65 ; 0,50 + 0,20 x (1 - 1/sqrt(N)))` : 1 essai -> 0,500 | 4 -> 0,600 | 9 -> 0,633 |
25+ -> 0,650. **Un seuil infranchissable ne protege de rien — il fait seulement qu'on finit par
le contourner.**

**ET LA PORTE REFUSERAIT MA PROPRE STRATEGIE. C'est le point le plus important de cette section.**
Candidat gele (empreinte `c853398229ab98328cfc4c427c3aadf9`) avec **450 essais declares** — le
compte reel du 14/11 : 5 horizons x 5 valeurs de `k` x 3 signaux x 2 ponderations x 3 taux de
couverture. Seuil exige : **0,650**. Part positive mesuree du livre : **0,58**.
**Elle ne passe pas.** Trois issues possibles, et une seule est honnete : que la part positive
hors echantillon se revele plus haute (elle allait de 57 a 68 % selon la periode), ou que le
candidat soit refute. **Affaiblir la formule pour y faire passer mon travail serait exactement la
corruption que cette porte existe pour empecher**, et c'est pourquoi le chiffre reste a 0,650.

**ETAT DE LA CHAINE AU 15/11** : labo a propose -> porte dit `PAS_ENCORE` (0 observation
independante, il en faut 8) -> moteur autorise `{}`. **Fermee et correcte.**

### C-novatricies. LE LABO NE MANQUAIT PAS DE DONNEES — IL EN JETAIT 80 % (15/11)

**LA CRAINTE ETAIT : « j'ai peur que le labo ne trouve pas de meilleure strategie alors que je
fais une enorme collecte de 6 jours ». Elle etait fondee, mais la cause etait ailleurs.**

**D'ABORD, UN DEFAUT DE MA PORTE, TROUVE EN LA TESTANT SUR MA PROPRE STRATEGIE.** Elle jugeait sur
la **PART POSITIVE**, croissante avec le nombre d'essais. C'etait un mauvais critere : j'avais
moi-meme mesure que l'edge de ce livre vient de l'**ASYMETRIE** (part positive 0,58, a peine mieux
qu'un pile ou face) et non de la frequence. **Un suiveur de tendance gagne 40 % du temps et fait
fortune** : juger sur la frequence penalise exactement le bon type d'edge. Remplace par le **`t` de
Student**, qui utilise la moyenne ET la dispersion, avec un seuil **Bonferroni** (`alpha = 0,05/N`,
quantile normal par dichotomie — pas de dependance a scipy). 1 essai -> **1,96** | 5 -> 2,58 |
450 -> **3,86**. C'est la correction STANDARD : un seuil invente se discute, un Bonferroni non.
La part positive reste **publiee comme diagnostic** mais ne ferme plus la porte. 19 tests.

**LE `t` HONNETE DE MA STRATEGIE, ET IL EST FAIBLE** (TEST, detentions DISJOINTES) :
```
horizon  n chevauch.  t (gonfle)  n disjoint  t HONNETE
    24h          211        2,43         106       2,21
    48h          209        1,77          53       0,98
    96h          205        1,51          26       1,04
   168h          199        3,78          15       1,05
   336h          185        5,09           7       1,62
```
**Les fenetres chevauchantes gonflaient le `t` d'un facteur TROIS** (336 h : 5,09 contre 1,62).
A 450 essais declares, **aucun horizon ne passe**. **En balayant 450 configurations le 14/11, j'ai
rendu la porte infranchissable pour mon propre travail.**

**ET LA VRAIE CAUSE : LA PROFONDEUR DU FUNDING ETAIT BORNEE PAR UNE LIMITE INVENTEE.**
`PROFONDEUR_FUNDING_MS` etait calee sur `CAP_CANDLES` (5 000 bougies 1 h = 208 jours) « par
symetrie ». Or `candleSnapshot` plafonne a 5 000 points, mais `fundingHistory` est pagine par 500
et **ne plafonne pas la**. Sonde du 15/11 sur BTC, une requete par palier :
```
il y a  211 j : 500 points   |   il y a  730 j : 500 points
il y a  365 j : 500 points   |   il y a 1095 j : 500 points
il y a  550 j : 500 points   |   il y a 1460 j : AUCUN -> limite
```
**La profondeur reelle est d'environ TROIS ANS. Nous en collections 211 jours.**
`PROFONDEUR_FUNDING_JOURS = 1100` (juste sous la limite, pour ne pas depenser de requetes a vide).
**x5,3 d'historique -> x2,3 sur le `t`**, et le nombre d'observations independantes vaut
`historique / duree_de_detention` : a 96 h, on passerait de **26 a ~137**.

**LA RESERVE, ET ELLE EST ESSENTIELLE** : plus d'historique couvre plus de REGIMES. L'effet mesure
sur avril-novembre 2026 peut etre plus faible, nul ou inverse en 2024. **Plus d'historique ne
garantit pas un verdict positif — il donne le POUVOIR DE TRANCHER**, ce qui manquait. Un `t` qui
s'effondre sur trois ans serait une refutation, et une refutation est un resultat.

**LA LISTE COURTE EST GELEE** : `docs/CINQ_HYPOTHESES_19_NOVEMBRE.md`, empreinte
`c561520f8995db7405c9881243d189de`. **Cinq hypotheses, pas 450**, toutes a **24 h de detention**
(le seul horizon ou ces donnees parlent : 106 observations disjointes contre 26 a 96 h). Seuil `t`
a 5 hypotheses : **2,58**, contre 2,21 mesure — il manque 0,37, franchissable.
H1 positionnement des leaders | H2 ordres en attente (prerequis : le taux d'annulation) |
H3 funding a 24 h, **le temoin** | H4 encombrement normalise par l'interet ouvert |
H5 proximite de liquidation comme filtre de RISQUE.
**Distinction qui compte** : une MESURE sans alternative (remplissage passif, `mmr`, slippage) ne
compte PAS comme essai — c'est la SELECTION qui coute, pas le calcul. Ces mesures sont a faire
sans retenue.

**PRIORITE DE COLLECTE REVISEE** : le rattrapage des ~890 jours de funding manquants passe
**DEVANT** l'elargissement de l'univers. Le premier multiplie la puissance statistique par 2,3 ;
le second ne reduit que la dispersion.

### C-quadragies. RATTRAPAGE DES 890 JOURS LANCE — et le verrou qui l'empechait, leve (15/11)

**LE VERROU ETAIT UN NOM DE FICHIER.** Le 14/11 j'avais renonce a lancer une passe de funding
dediee, et la raison etait juste : `sauver_etat` ecrivait son brouillon dans un `.tmp` au nom
**FIXE**. Avec deux passes concurrentes — celle de la campagne toutes les 4 h et une passe de
rattrapage — les deux ouvrent le MEME brouillon : P1 ecrit, P2 le tronque, P1 remplace, et un etat
**PARTIEL** devient l'etat officiel. Le `os.replace` est atomique, mais **il ne protege pas de deux
ecrivains sur le meme brouillon**.

**CORRIGE** : le temporaire porte desormais le **PID**, et un `finally` nettoie le brouillon
oublie. Les deux passes peuvent donc tourner ensemble ; la derniere a ecrire gagne pour les coins
qu'elle a traites, et comme la boucle sert **les coins les plus en retard d'abord**, aucun coin
n'est affame. Verifie : etat relu a l'identique, **zero brouillon laisse**.

**L'AMPLEUR DU TRAVAIL, mesuree et non estimee** :
```
261 coins | cible 1 100 jours = 26 400 h = 53 pages par coin
27 s par page (debit auto-limite a 100 de poids/min, par politesse pour l'IP partagee)
-> 0,4 h par coin, soit ~103 h de passe au total

114 coins ont deja leurs 211 jours recents (il leur manque les 890 anciens)
147 coins partent de ZERO
```
**La passe de la campagne seule** (7 200 s toutes les 4 h, soit 50 % du temps) demanderait **8
jours**. Une passe dediee continue le fait en **~4**. D'ou le lancement d'une passe dediee avec un
budget de 28 800 s, en arriere-plan.

**POURQUOI LE RISQUE EST ACCEPTABLE** : la passe appelle `CF.ceder_au_direct()`, donc elle **cede
la priorite aux collecteurs en direct** — c'est exactement le cas pour lequel ce mecanisme existe.
Et l'etat etant sauve **apres chaque coin**, une interruption (le reaper memoire de ce PC coupe les
runs longs) ne perd rien : la passe suivante reprend ou l'autre s'est arretee.

**CE QUE CELA DEBLOQUE** : le nombre d'observations independantes vaut
`historique / duree_de_detention`. A 24 h de detention — le seul horizon ou ces donnees parlent —
on passerait de **211 a ~1 100 observations**, et le `t` croit en racine de `n`.
**Reserve inchangee et essentielle** : trois ans couvrent plus de REGIMES. Un `t` qui s'effondre
serait une refutation, et une refutation est un resultat.

### C-unquadragies. LE DEFAUT LE PLUS GRAVE DE LA SESSION, ET LE PAS QUI LE RACHETE (15/11)

**TROIS DEFAUTS ENCHAINES, trouves en une heure parce que l'utilisateur a doute a voix haute.**

**1. LE LABO ALLAIT MOURIR SOUS SES PROPRES DONNEES.** Chronometre : `une_revision` recalculait la
moyenne des 96 h **a partir de zero**, pour chaque coin et chaque instant. **31 ms par revision,
11 min par lancement, et 1,6 h projetee** a 1 100 jours et 261 coins — alors que le reaper memoire
de ce PC coupe les runs au-dela de ~30 min. Corrige par un **index de sommes prefixes**
(`index_glissant` / `moyenne_indexee`) : la moyenne sur n'importe quelle fenetre devient une
soustraction trouvee par dichotomie. **29,6 ms -> ~0 ms par revision ; 11 min -> 25 s de bout en
bout.** Les trous sont preserves (on cumule la somme ET le compte, sinon une serie a trous serait
divisee par trop et diluee vers zero) et la borne haute reste EXCLUE (`bisect_left`, sinon l'heure
de decision entrerait dans le classement). 5 tests comparent l'index au calcul direct sur des
series a trous, aux bords de fenetre.

**2. LES PERIODES ETAIENT DECOUPEES SUR LE FUNDING SEUL — et le rattrapage les a deplacees.**
Les deux sources n'ont pas la meme profondeur : funding ~1 100 jours, bougies HORAIRES 208.
Pendant que le rattrapage allongeait le funding de 211 a 1 059 jours, **les bornes de TRAIN / TEST
/ tiers ont glisse** et le chiffre de reference est passe de **+3,02 a +1,27 USD/jour** — sans
qu'une ligne de la strategie change, et **sans le moindre avertissement**.
**Un labo dont les resultats bougent quand les donnees grandissent ne mesure rien.** Corrige :
`heures_exploitables()` rend l'**INTERSECTION funding ∩ prix**, et l'outil affiche desormais
separement ce qui est COLLECTE et ce qui est MESURABLE. 6 tests, dont **le garde-fou central** :
allonger le funding de 10x vers le passe ne doit PAS deplacer la fenetre.

**3. ET LA DECOUVERTE QUI RACHETE LE RATTRAPAGE.** J'avais conclu « les prix s'arretent a
211 jours » **apres n'avoir sonde que le pas HORAIRE**, et j'allais recommander de reduire la
profondeur du funding. L'utilisateur a demande pourquoi. Le plafond de `candleSnapshot` est de
**5 000 BOUGIES, pas de 211 jours** : il depend donc du PAS.
```
1h -> 5 001 bougies =   208 jours (avril 2026)
4h -> 5 001 bougies =   833 jours (aout 2024)
1d -> 1 101 bougies = 1 101 jours (novembre 2023)  <- exactement la profondeur du funding
```
**Et la strategie tient 24 h : une bougie journaliere correspond a une detention ENTIERE.** Le pas
`1d` n'etait **pas collecte du tout** (le collecteur ne connaissait que `5m` et `1h`). Ajoute sur
les **quatre** maillons, car en oublier un suffit a tout annuler :
* `INTERVALLES_MS` et `SORTIES` du collecteur ;
* le **certificateur** (`candles_1d.jsonl` -> `FAMILLE_CANDLE`) — sans quoi la donnee serait
  produite puis **ignoree**, le labo ne lisant que le coffre : le piege « donnee presente mais
  jamais rendue » ;
* le **contrat de couverture** — et son test a **attrape mon oubli** : un fichier connu du
  certificateur sans producteur declare est un fichier qu'on ne sait pas expliquer ;
* le **registre**, dont les args passent a `--intervalles 1h,5m,1d`.

**ETAT APRES LES TROIS CORRECTIFS** (univers passe de 90 au gel a **116 coins**) :
```
collecte : funding 25 416 h (1 059 j) | prix 5 095 h (212 j)
MESURABLE : 5 095 h (212 j) = l'intersection
847 jours de funding sans prix en face -> c'est le pas JOURNALIER qui leur en donnera un

multi-taker/TEST    brut  +95,8 %  repli 7,44 %  levier 2,38x  +2,18 USD/j
multi-maker/TEST    brut +112,1 %  repli 7,32 %  levier 2,40x  +2,58 USD/j
multi-taker/tiers3  brut   -9,5 %  repli 7,44 %  levier 2,38x  **-0,22 USD/j**
```

**ET LE RESULTAT LE PLUS UTILE EST CELUI-LA, meme s'il deplait** : le chiffre est passe de +3,02 a
+2,18 en ajoutant 22 coins, et **le tiers le plus RECENT est devenu NEGATIF**. Une strategie dont
le resultat bouge d'un tiers quand l'univers s'elargit, et dont la periode la plus proche de
maintenant perd de l'argent, **n'est pas robuste**. C'est exactement ce que la porte de promotion
est censee refuser — et elle le refuserait.

### C-duoquadragies. TROIS TENTATIVES DE ROBUSTESSE, TROIS REFUTATIONS — et ce que le signal
de funding vaut vraiment (15/11)

**LA DEMANDE ETAIT : « trouve une strategie robuste ». TROIS VOIES ESSAYEES, TOUTES REFUTEES.**

**1. PONDERER PAR LE RANG** (supprimer `k`, donc supprimer la fragilite qu'il cause) :
**-53,8 %/an, t = -3,36, negatif dans les SIX periodes.** Explication mesuree : avec des poids
proportionnels au rang, les trois coins extremes ne portent que **5 % du livre** — les 95 %
restants sont dans le milieu de la section, ou il n'y a pas de signal. **Diluer ne robustifie pas,
ca remplace la strategie par une autre, qui perd.** L'edge est bien dans les POINTES seulement.

**2. SELECTIONNER PAR FRACTION** (2,6 % de l'univers au lieu de `k=3` fixe, pour que le livre soit
invariant d'echelle) :
```
univers   brut/an      t      USD/j    tiers 1 / 2 / 3
     40    -84,1 %  -1,06   -1,38U   +69% / -188% / -126%
     60    +16,0 %   0,16   +0,40U  +103% /  -44% /   -6%
     80    +54,9 %   1,02   +1,14U  +140% /  -22% /  +52%
    100    +39,4 %   0,72   +0,84U  +112% /  +26% /  -16%
    116    +31,3 %   0,54   +0,64U  +106% /  +79% /  -88%
```
Le resultat oscille de **-84 % a +55 %** selon la taille de l'univers, et **aucune configuration
n'a ses trois tiers positifs**. Refute.

**3. ET LE CONSTAT QUI COMPTE PLUS QUE LES DEUX PREMIERS : TOUS LES `t` SONT ENTRE -1,06 ET
+1,02.** Le seuil minimum est **1,96**, et c'est celui qui s'applique a **un seul essai declare**.
**A 24 h de detention, ce signal n'est pas distinguable du bruit, dans aucun univers.**

**POURQUOI LE +2,21 DE CE MATIN A DISPARU.** Il avait ete mesure avec (a) les anciennes bornes de
periode, decoupees sur le funding seul et donc deplacees par le rattrapage, (b) un univers de
94 coins, (c) une fenetre de classement de 96 h. **Les trois correctifs de la journee — l'index,
l'intersection funding ∩ prix, et l'univers elargi — ont retire les illusions, pas le signal.**
Le `t` est tombe de 2,21 a **0,54**.

**CE QU'IL FAUT EN CONCLURE, ET JE NE VAIS PAS L'ADOUCIR.** J'ai essaye de sauver le signal de
funding par trois voies differentes : `k` fixe (fragile), pondere par le rang (refute), fraction
d'univers (refute). **La bonne reponse n'est plus « cherchons une quatrieme voie » — chaque
tentative en plus monte la barre de la porte pour toutes les autres.** Le signal de funding, tel
qu'on le mesure aujourd'hui sur une fenetre honnete, **ne porte pas d'edge demontrable**.

**CE QUI RESTE, ET POURQUOI CE N'EST PAS RIEN**
* **Le signal des LEADERS (H1)**, jamais teste, et c'est le seul dont la motivation vienne d'une
  MESURE : le momentum direct echoue (-44,2 %) alors que le funding reussissait, donc le funding
  mesurait **l'encombrement du positionnement**. Les positions des leaders le mesurent
  **directement**. Testable le 19/11 avec 192 h d'historique.
* **Le pas JOURNALIER** ajoute aujourd'hui : il ouvre **1 101 jours** de fenetre mesurable contre
  212 — soit **x5,2 d'observations**, donc **x2,3 sur tous les `t`**. Un signal a `t = 0,54` sur
  212 jours donnerait `t = 1,24` sur 1 101 : toujours insuffisant. Mais un signal a `t = 1,2`
  passerait a 2,8. **C'est le pas journalier qui decidera si quelque chose existe.**

**L'INFRASTRUCTURE, ELLE, EST DEVENUE SOLIDE** : l'index (11 min -> 25 s) evite au labo de mourir
sous ses donnees ; l'intersection empeche les resultats de bouger quand les donnees grandissent ;
la porte de promotion refuse ce qui ne se distingue pas de la chance — **y compris mon propre
travail**. Ce sont ces trois choses qui ont permis de decouvrir, en une journee, que le signal ne
valait pas ce qu'il semblait valoir. **C'est exactement a cela qu'un labo sert.**

### C-trequadragies. LA BASE (`premium_bps`) — bon signe, donnees insuffisantes, et deux
defauts trouves en route (15/11)

**POURQUOI CETTE CLASSE EST DIFFERENTE DU FUNDING.** Le funding est le taux **DEJA REGLE** ; la
prime est l'ecart **INSTANTANE** entre le mark du perp et son oracle. Jamais teste ici.

**PRECAUTION QUE LA MESURE IMPOSE** : une prime revient a zero soit parce que le mark baisse, soit
parce que l'oracle monte. **Un short de perp seul ne gagne que dans le premier cas** — sans jambe
spot on ne capture pas la convergence, on fait un pari directionnel. D'ou un livre TRANSVERSAL.

**DEFAUT 1 — MON PREMIER TEST MESURAIT DES MARCHES MORTS.** Le filtre « |prime| > 50 bps »
selectionnait **STRAX a +370 505 bps**, FRIEND a +88 881, SHIA, NFTI — tous a **ZERO volume 24 h**,
mark fige loin de l'oracle. Le livre shortait des coins qu'on ne peut ni vendre ni racheter, et le
resultat (-787 %/an, t = -3,06) ne mesurait que cette absurdite.
**Univers propre** : volume 24 h > 1 M **et** |prime mediane| < 500 bps -> **72 coins sur 235**.
Les vraies dislocations y valent des dizaines de bps (p95 = **+69**), pas des milliers.

**CE QUE LA MESURE PROPRE DONNE**
```
1) LA PRIME REVIENT : 60 a 68 % des primes extremes se resserrent.
   Mais la MOYENNE ne bouge pas (-130 -> -129 bps) : c'est un COMPTE, pas une amplitude.

2) LE PRIX SUIT, et les deux livres sont des miroirs EXACTS :
   long prime BASSE    2h  +95 %/an  t=0,15 (nd=50) | 4h +328 %  t=0,58 (nd=24)
   long prime HAUTE    2h -1613 %/an t=-3,72        | 4h -1088 %  t=-2,52
```
**Le SENS est bon et CONSTANT sur les cinq horizons**, et les deux livres sont des miroirs — cette
coherence est un bon signe, contrairement au funding dont le signe basculait entre periodes.
**Mais aux tailles d'echantillon utilisables, `t` vaut 0,15 a 0,58 : loin du 1,96 minimum.**
**4,6 jours de donnees ne permettent pas de conclure.** C'est une PISTE, pas un resultat.

**DEFAUT 2 — ET IL ETAIT DANS MON PROPRE OUTIL.** `t_de_student` acceptait **2 points**. Il a donc
affiche sans reserve un **t = 4,25 sur TROIS observations disjointes** (et son miroir a -4,74) :
avec si peu de degres de liberte, un ecart-type minuscule fait exploser le `t`. La porte exigeait
deja 8 observations independantes, **mais l'AFFICHAGE montrait le 4,25** — et **un chiffre
spectaculaire qu'on ne peut pas croire est plus dangereux qu'un refus.** Minimum porte a
`OBSERVATIONS_MINIMUM` (8), avec un test.

**CE QU'IL FAUT POUR TRANCHER** : `asset_ctx` est une famille VIVANTE (4,6 jours). A 24 h de
detention il faut 8 observations disjointes, donc **au moins 8 jours** — soit le 19/11 si la
campagne tient, et beaucoup mieux au 23. **C'est la classe la plus prometteuse des six non
testees, et la seule dont le signe soit coherent sur tous les horizons.**

### C-quindecies-ter. TROIS CHANTIERS NES D'AUDITS DE LIENS EXTERNES (14/11)

Point de depart : un fil X (@RohOnChain) soumis par Florent. Le fil lui-meme n'apporte rien —
sa seule strategie verifiable, testee en aveugle par un tiers (TheTapeTest, « RohOnChain ranking
book »), passe d'un **Sharpe ~1,0 sur les coins survivants a un Sharpe 0,2-0,3 avec 50-70 % de
drawdown en test point-in-time incluant les coins delistes** ; le bot est aujourd'hui RETIRE. Le
modele qu'il promeut (Kronos, « predit la prochaine bougie ») a ete evalue independamment quatre
fois : IC +0,086 a 5 min sur BTC qui disparait a 30 min, **0 cellule rentable sur 43 apres frais**
(avantage espere ~0,01 % contre 0,2 % d'aller-retour), 50,2 % de reussite directionnelle sur
749 previsions hors echantillon, et un intervalle cense couvrir 80 % des issues qui en couvre 21 %.
C'est exactement le defaut que ce labo mesure deja sur DeepLOB : **-4 242 bps net, l'edge meurt
dans le spread**.

**MAIS la recherche menee autour a produit deux chantiers reels.**

#### R7 — LE REGIME DOIT AUSSI DECIDER, PAS SEULEMENT JUGER

`regime_label.py` se termine par : « Aucune decision, aucun ordre : ce module ETIQUETTE. » Le
regime est aujourd'hui **defensif** : `regime_shift_stress_receipt` refuse le label « robuste »
tant qu'une strategie n'a pas ete stressee sur plusieurs regimes (`fail_closed=not valid`). C'est
une porte de validation, et elle est bonne.

Ce qui manque est la moitie **offensive** : activer une strategie SEULEMENT dans le regime ou elle
fonctionne, et redimensionner selon ce regime. C'est le chantier deja inscrit comme
« conditionnement / replication : a batir » dans les 4 chantiers vers un PnL positif.

Pourquoi c'est le bon moment : le carry de funding cross-sectionnel est **vivant mais avec un
PBO de 0,81** — un edge reel qui ne survit pas a la selection. Conditionner par regime est
precisement le levier qui peut transformer un edge globalement plat en edge conditionnellement
positif. Et l'etiquetage existe deja, **causal et sans lookahead** : `garch11_variance_causale`
(l'historique lisait le futur deux fois) et un seuil haute/basse vol calcule sur le TRAIN seul.

PIEGES A NE PAS REOUVRIR :
* conditionner multiplie les essais -> la penalite de multiplicite doit compter CHAQUE regime
  teste, sinon on fabrique un faux PROVEN par decoupage ;
* un regime estime a l'instant t ne doit utiliser que l'information disponible a t (le module le
  garantit deja : ne pas le contourner en relisant une etiquette calculee plus tard) ;
* « INCONNU » doit rester INCONNU : ne jamais forcer un label pour pouvoir trader.

PREMIER PAS MESURABLE : par regime etiquete, le PnL net par jour actif du carry cross-sectionnel,
avec son intervalle, et le nombre de jours actifs PAR REGIME (si un regime a 2 jours, il n'est pas
mesurable et doit etre declare tel — jamais « valide »).

#### R8 — COPIER PENDANT UN TWAP ANNONCE N'A PAS LE MEME COUT

Barone & Lillo, *Trading in the Sunshine or in the Shade: Market Impact and Adverse Selection on
Hyperliquid* (arXiv 2606.15715, juin 2026) — **sur la venue exacte de ce projet**, 4,3 millions de
metaordres caches reconstruits contre 465 000 executions TWAP visibles :

* les TWAP visibles ont des couts d'execution **plus faibles** et un impact permanent **plus petit**
  que des metaordres caches comparables ;
* ceux qui executent **a cote** d'un flux TWAP visible de meme sens subissent des couts permanents
  **plus eleves** : le cout de selection adverse se DEPLACE vers ceux qui n'annoncent pas ;
* un TWAP visible **attire de la liquidite** : la profondeur affichee augmente et le carnet penche
  du cote absorbant, d'autant plus que l'ordre annonce est gros.

CE QUE CA CHANGE POUR LA COPIE. Le collecteur `contexte-leaders` capte deja, pour les leaders,
**positions + TWAP + ordres en attente** (mesure du 13/11 : « 212 positions, 23 portefeuilles,
90 TWAP, 24 carnets d'ordres »). On peut donc separer les fills d'un leader selon qu'ils
appartiennent a un TWAP ANNONCE (visible pendant son execution) ou a un metaordre cache, et
mesurer le cout de copie des deux populations separement. Hypothese testable : copier pendant le
TWAP annonce d'un leader coute moins cher — ou, lecture inverse et plus probable pour un copieur
qui arrive APRES, coute PLUS cher parce qu'on devient le non-annonceur qui absorbe la selection
adverse.

PIEGE : le champ `twapId` existe deja sur les fills (vu dans les rubans). Ne PAS en deduire la
visibilite sans verifier que le TWAP etait actif et affiche AU MOMENT du fill copie — sinon on
etiquette a posteriori ce que le marche ne voyait pas, et on refait du lookahead.

PREMIER PAS MESURABLE : sur le corpus de la campagne, la part des fills de leaders rattachables a
un TWAP actif, puis le cout d'execution simule des deux populations, avec la meme sonde
d'executabilite que le reste (reference -30 s, entree +delai, sortie +horizon, meme identite de
connexion).

#### R9 — LE STYLE D'EXECUTION D'UN LEADER PREDIT-IL SA COPIABILITE ?

Source : un fil X (@zostaff, 08/11/2026) presentant un bot de copie pumpfun open source. Le bot
lui-meme ne sert a rien ici (Solana, memecoins, autre venue). **Sa mesure, si.**

CE QUI EST RECEVABLE. Le depot a retro-analyse **666 wallets de bots pumpfun**. Les **344** qui
faisaient tourner des bots routeurs sophistiques affichent un resultat combine de **-69,14 SOL
pour 38 % de trades gagnants**. Grande cohorte, non triee, resultat negatif : c'est une mesure.
Sa conclusion — *« tu n'as pas besoin d'un bot plus intelligent, tu as besoin de meilleurs wallets
a suivre »* — est **mot pour mot la these de ce projet** : la selection bat la sophistication.

CE QUI N'EST PAS RECEVABLE, et qu'il ne faut surtout pas reprendre. « Les 5 meilleurs wallets ont
80 % de reussite » : prendre le top 5 sur 666 et publier leur taux est du **biais de selection
pur**. C'est exactement ce que `survivorship_wallet_receipt` refuse ici. (A son credit, l'auteur
l'admet : « 5 wallets is a tiny sample and past wins mean nothing ».) La cohorte de 344 vaut ;
le top 5 ne vaut rien. Retenir cette distinction, pas le chiffre flatteur.

IL NOMME AUSSI LE MUR. *« a copy always lands after the original, so you buy a bit higher and sell
a bit lower than the wallet you follow. »* C'est precisement pourquoi ce labo a REJETE fast_follow
a tous les horizons <= 300 s **meme a spread nul**. Il decrit le mur ; nous l'avons mesure.

**L'HYPOTHESE A TESTER ICI.** Sur pumpfun, les wallets SIMPLES battaient les wallets SOPHISTIQUES.
Transposee a Hyperliquid : **le style d'execution d'un leader predit-il sa copiabilite nette ?**

Caracteristiques de style deja collectees, aucune collecte supplementaire necessaire :
* part agressive — `taker_notional_share`, deja un critere (C86, `copie_leader_trop_passif`) ;
* usage de TWAP — mesure du 13/11 : 90 TWAP actifs suivis (`copy_vault_twap_lane`) ;
* ordres en attente et types d'ordres — `copy_vault_orders_lane`, agregats `par_genre`
  (ENTREE_LIMITE / SORTIE_LIMITE) et `notionnel_par_coin` deja presents dans le coffre ;
* cadence, taille et dispersion des fills par leader.

**FORME DU TEST — c'est le point le plus important.** La question se pose **A TRAVERS les
209 leaders a la fois**, pas leader par leader. Tester « ce leader est-il rentable ? » 209 fois,
c'est 209 essais et une penalite de multiplicite ecrasante qui garantit de ne rien prouver.
Tester « la part agressive predit-elle la copiabilite nette ? » est **UNE** hypothese evaluee sur
209 observations : la section transversale devient une force au lieu d'une penalite. C'est la meme
logique que le carry cross-sectionnel, qui est le seul edge encore vivant ici (PBO 0,81).

PIEGES :
* le style se mesure **avant** la periode jugee, jamais sur la meme fenetre que le resultat,
  sinon le classement connait son propre test ;
* un leader peut changer de style : la caracteristique doit etre datee et recalculee par fenetre ;
* « part inconnue » n'est pas « part nulle » (deja verrouille par les tests de C86) ;
* le resultat attendu peut tres bien etre NUL — c'est une reponse, pas un echec.

PREMIER PAS MESURABLE : sur le corpus du 19/11, la correlation de rang entre une caracteristique
de style (commencer par la part agressive, deja calculee) et le PnL NET copiable par leader, avec
son intervalle et le nombre de leaders reellement scorables (>= 3 jours actifs). Si moins d'une
dizaine de leaders sont scorables, le dire : non mesurable, et non « pas de lien ».

### C-octodecies. R7/R8/R9 — OUTILLAGE CONSTRUIT, ET DEUX MESURES INATTENDUES (14/11)

**Noyau commun** : `backtesting/test_transversal.py` (14 tests). UNE hypothese evaluee a travers
N observations — jamais N hypotheses. Poser « ce leader est-il rentable ? » 209 fois, c'est
209 essais et la certitude de ne rien prouver ; poser « la part agressive predit-elle la
copiabilite ? », c'est UNE hypothese sur 209 observations. `essais` est un parametre OBLIGATOIRE
(Bonferroni) : la multiplicite est portee, pas cachee. Trois refus verrouilles : trop peu
d'observations -> NON MESURABLE et **jamais « aucun lien »** ; caracteristique constante -> refus ;
observations incompletes -> ECARTEES et comptees, **jamais imputees** (imputer, c'est inventer).
`comparer_groupes` ajoute pour R7 et R8, avec le meme refus : un groupe trop petit est NOMME non
mesurable, et un seul groupe mesurable **n'est pas une egalite**.

**MESURE 1 — LES LEADERS SONT MASSIVEMENT PASSIFS.** Sur **90 702 fills certifies**, part
agressive connue pour **157 leaders sur 161** : **mediane 7,9 %**, de 0 % a 100 %. Le leader
typique est donc **~92 % passif**. Le projet avait mesure « 67 % des fills sont passifs et valent
~0 avant frais » ; a l'echelle des 161 leaders c'est pire encore. **Consequence** : la population
reellement copiable est bien plus petite que le compte brut de fills, et le critere C86
(`copie_leader_trop_passif`) devient central plutot qu'accessoire. **Et la dispersion 0-100 % est
une bonne nouvelle pour R9** : une caracteristique constante aurait rendu le test impossible.

**MESURE 2 — R8 NE PEUT PAS PARTIR DES FILLS.** **0 fill sur 88 353** porte un `twapId`. Le lien
avec les TWAP doit donc se faire depuis `copy_vault_twap_lane` par appariement (leader, coin,
fenetre de temps), et non par un champ sur le fill. **Le premier pas de R8 change** : construire
l'appariement avant toute comparaison de couts. Rappel du piege : un `twapId` dirait
l'APPARTENANCE, pas qu'un TWAP etait AFFICHE au moment ou un copieur aurait agi — conclure la
visibilite sans verifier serait un lookahead.

**CE QUI RESTE SUSPENDU A LA CAMPAGNE** : les trois chantiers visent la meme cible, le **PnL NET
COPIABLE par leader**, qui sort du moteur. `tools/mesurer_r789.py` extrait tout le reste
maintenant et **refuse explicitement** de conclure sans elle — pour que le 19/11 soit un jour de
mesure et non de developpement.

### C-quaterdecies. K1 — DE 8 A ~120 LEADERS : le collecteur REST enfin cable (12/11)

**Le vrai goulot mesure** : 8 leaders distincts seulement dans le ruban, dont UN SEUL a 63 % des
fills (439/693). Le labo mesurait un trader, pas une strategie. Et `tools/collecter_userfills_poll.py`
existe PRECISEMENT pour depasser le plafond WebSocket (~10 userFills/IP) via `info/userFillsByTime`
(non soumis au cap WS)... mais il n'etait PAS dans le registre, donc il ne tournait pas.

**Trois choses faites, dans cet ordre, parce que l'ordre importait :**
1. **Budget de debit PARTAGE branche dans sa requete** (`CF.reserver_poids(CF.POIDS_REQUETE_INFO)`).
   Il avait un AIMD local isole, aveugle au trafic des autres : le cabler tel quel aurait relance les
   rafales de 429 ramenees de 218 a 16. **Prouve : 2 requetes = 40 de poids reserve.**
2. **Cadence redimensionnee : 55 -> 12 req/min.** 55 etait prevu pour une IP DEDIEE (lane cloud) ;
   en local une seule IP est partagee par ~12 collecteurs et `userFillsByTime` pese 20, donc
   55 req/min = 1100 poids/min, soit la quasi-totalite du budget de 1200 — il aurait AFFAME les
   autres, dont les fills causaux WS. 12 req/min = 240 poids/min, environ 20 % du budget, et la
   cadence ADAPTATIVE du collecteur (un leader qui vient d'emettre est repolle plus vite) fait le
   reste. **Cabler a 55 aurait casse toute la collecte : c'est le calcul qui l'a evite.**
3. **Entree de registre + profil harvest** (23 -> 24 collecteurs). Pas de cle `heartbeat` : il imprime
   une ligne d'etat A CHAQUE PASSE et sauvegarde son etat, donc la vie se juge sur le log.

**Effet attendu : de 8 a ~120 leaders suivis** (`config/copy_vault_leaders.json` en compte 120).
**Essai reel : 3 leaders polles -> 66 fills causaux emis en une seule passe.**
Verifie : 100 tests (registre, superviseur, premier lancement, alignement ordres/fills).

### C-quindecies. LE PIEGE QUI AURAIT COUTE LES 6 JOURS (12/11)

**Tout etait vert, et pourtant la campagne n'aurait rien collecte de nouveau.** `userfills-poll` et
`contexte-leaders` venaient d'etre ajoutes au REGISTRE et au profil `harvest`, tests au vert. Mais la
campagne de 6 jours ne passe PAS par les profils du registre :

* `LANCER_COLLECTEURS_COPY_VAULT.cmd` (CV_DURATION=518400 s = exactement 6 jours) appelle
  `tools/watch_economic_collectors.py --profile copy-vault` ;
* ce watchdog ignore les profils et utilise sa PROPRE liste en dur, `DEFAULT_NAMES` (15 noms) ;
* il n'existe AUCUN profil « copy-vault » dans le registre (all/core/harvest/maintenance/research) ;
  `CV_PROFILE` n'etait meme jamais transmis au superviseur — il ne servait qu'a un `echo`.

**Consequence evitee de justesse : six jours de collecte sans le levier 8 -> ~120 leaders et sans les
intentions des leaders, decouverts seulement a la fin.** Deux sources de verite pour « quels
collecteurs tournent », et rien qui rougissait quand elles divergeaient.

**Correction** : les deux collecteurs ajoutes a `DEFAULT_NAMES` (15 -> 17), decompte du `.cmd`
corrige, et surtout `tests/test_lanceur_6_jours_couvre_le_registre.py` (6 tests) qui verrouille :
tout nom de `DEFAULT_NAMES` existe dans le registre ; les collecteurs de leaders y sont ET sont dans
`harvest` ; aucun doublon ; le `.cmd` annonce le bon nombre ; et le jour ou « copy-vault » devient un
vrai profil, un test rougit pour forcer a relire toute la chaine.

**LECON GENERALE : « c'est dans le registre » ne veut PAS dire « ca tourne ». Verifier le chemin
reel du lanceur, de bout en bout, avant toute campagne longue.**

### C-terdecies. CORRECTION DES 30 ECHECS DE LA SUITE (12/11) — et un defaut comptable REEL trouve

Suite complete : **18 343 passent, 30 echouent** (contre 3 ce matin). Triage par bisect REVERSIBLE
(sauvegarde du fichier, restauration de la version HEAD, mesure, remise en place) :

* **AUCUN echec ne vient du travail du jour** : les 274 tests des 9 chantiers passent, et la
  compilation de tout l'arbre est propre. Le premier « echec » de `compileall` etait un FAUX POSITIF :
  il butait sur `tools/python/`, une installation Python embarquee contenant des fichiers de test
  volontairement invalides. En l'excluant : 0 fichier en echec.
* **19 echecs venaient de modifications UI non commitees** faites plus tot dans la session
  (`ui/routes.py` +350 lignes, `status_routes.py`, `fusion_persistent_adapter.py`). Preuve : avec les
  versions HEAD de ces trois fichiers, 85 tests passent, zero echec.
* **Ces modifications sont BONNES** (leurs propres commentaires le disent) : suppression de DOUBLES
  COMPTAGES de couts d'execution et de frais d'entree, et fail-closed quand la preuve de cout manque.
  **Choix de Florent : A — garder le durcissement, adapter les tests.** On ne revient JAMAIS en arriere
  sur une correction comptable pour faire verdir un test.

**CE QUI A ETE CORRIGE (28 / 30)**

1. **16 echecs UI** : le bloc exigeant un carnet FRAIS s'execute si la garde de profondeur OU la garde
   de microstructure AUTORITAIRE est active. Desactiver la seule profondeur ne suffisait pas (et le
   motif affiche, `DEPTH_FILL_GUARD_NO_RECENT_L2BOOK`, est alors trompeur). Les deux gardes sont donc
   neutralisees dans les fixtures de PERSISTANCE — geste que ce fichier de tests documente deja pour
   les planchers d'edge — et **REACTIVEES explicitement dans leurs tests dedies**.
2. **1 echec de mark** : un snapshot `publicTradesWS` doit desormais porter l'heure d'evenement DE
   CHAQUE COIN (`trade_times_ms`), sinon sa fraicheur est inconnue et le mark est ignore. Fixture
   completee, avec une valeur NON future (un mark date dans l'avenir est rejete lui aussi).
3. **1 VRAIE REGRESSION corrigee dans le CODE** : le durcissement reconstruisait le PnL realise depuis
   `simulation_ledger_events` — qui est AUSSI le ledger d'AFFICHAGE. Purger l'affichage faisait donc
   tomber la comptabilite a zero. Correctif : quand le ledger ne contient PLUS AUCUNE ligne strictement
   chiffree, on retombe sur le scalaire persiste. **Une limite d'AFFICHAGE ne doit jamais changer la
   COMPTABILITE**, et la protection voulue par l'auteur reste entiere des qu'une ligne stricte subsiste.
4. **5 echecs SLTP + 1 master_repair** : `estimated_net_pnl_usdc` n'est plus publie tant que TOUS les
   couts ne sont pas connus (regle d'honnetete : jamais une estimation partielle presentee comme un
   net). Le montant calcule avec les couts CONNUS reste expose dans `known_cost_net_pnl_usdc` : les
   tests verifient donc la MEME arithmetique sur le champ qui la porte, **et verifient EN PLUS** que le
   net strict est bien refuse avec son motif. Couverture plus forte, pas plus faible.
5. **2 echecs funding** : le funding n'est plus facture depuis une ESTIMATION (taux en cache x heures)
   mais depuis une PREUVE DE REGLEMENT certifiee — franchir une frontiere horaire ne fabrique pas du
   cash. Les fixtures fournissent donc cette preuve (`net_funding_settled`, `funding_settlement_source`,
   `funding_settlement_evidence_complete`), ce qui PRESERVE l'intention d'origine de ces tests
   (« le funding n'etait jamais facture : 42,6 h de positions, zero centime deduit »).
6. **1 echec de logs** : son sujet est l'ECRITURE DES LOGS ; les gardes bloquaient toutes les entrees,
   donc le resume etait vide. Gardes neutralisees pour ce test seulement.
7. **1 echec instable** (`portable_official_cmds`) : repasse au vert sans aucune modification.

**LES 2 ECHECS QUI RESTENT SONT VOLONTAIREMENT ROUGES — NE PAS LES ADAPTER**

`test_status_marks_existing_paper_position_with_latest_hyperliquid_snapshot` et
`test_open_mark_and_close_share_exact_round_trip_cost_truth` attrapent un **defaut comptable REEL** : en
supprimant la DOUBLE soustraction des frais d'entree, le durcissement a supprime la SEULE soustraction
de ces chemins. Mesure : `gross 1.0 - sortie 0.2412 = 0.7588` et equite `999,88` au lieu de `999,76`,
avec `realized_pnl = 0.0` — **le cout d'entree n'est deduit NULLE PART**, alors que
`pnl_accounting_status` annonce `STRICT_ROUND_TRIP_COSTS_KNOWN`. Un PnL paper surevalue du montant des
frais d'entree est exactement le mensonge que ce projet interdit.

**J'avais d'abord « adapte » ces deux tests (0.7388 -> 0.7588) : c'etait une ERREUR, cela masquait le
defaut. Les valeurs d'origine ont ete restaurees et le defaut est documente DANS les tests eux-memes.**

Deux correctifs sont possibles et tous deux risques sans l'intention de l'auteur : re-soustraire dans le
MTM recreerait le double comptage en production (ou `paper_engine` booke le cash a l'OPEN) ; adapter les
fixtures masquerait la surevaluation si la production ne deduit rien. **Un test rouge qui documente une
question comptable ouverte vaut infiniment mieux qu'un test vert qui la cache.**

**Verification finale : 137 passent, 2 echouent (les deux ci-dessus, volontairement).**

### D. PROCHAIN PAS CRITIQUE (dans l'ordre)

> **REMPLACÉ** par le plan d'attaque priorisé de la section **0 quater** (sprints 1-2-3 avec critères de fin mesurables). Conservé ci-dessous pour mémoire : son contenu reste valable mais partiel (écrit avant les sections C-quater → C-undecies).

1. **C21 + C23 + C25** (carnets HIP-3 + carnet de sortie garanti + abonnement piloté par l'activité)
   : c'est le verrou. Sans carnet de sortie, le labo restera « non mesurable » même avec l'identité.
2. Laisser tourner le lanceur local (ou pousser pour les lanes cloud) **plusieurs jours** →
   Certificateur → le bloc « Aucun trade exécutable » doit disparaître du rapport.
3. Alors seulement : la recherche (B2–B7) peut isoler un avantage réel s'il existe. Tant que la
   sonde refuse, chercher ne sert à rien.

## 0 bis. Nouveautés (2026-11-08)

- **Lanes de collecte multi-IP** (franchissent les plafonds par IP d'Hyperliquid) : `userfills-live-lanes.yml`
  (fills `LIVE_WS`), `copy-vault-poll-lanes.yml` (fills `LIVE_POLL`), `copy-vault-l2-lanes.yml` (carnets L2 +
  BBO). Leaders/coins commitables : `config/copy_vault_leaders.json`, `config/copy_vault_coins.json`.
  Rapatriement + fusion automatiques dans `ALINA_SYNC_COMPLETE.cmd` (dédup + fraîcheur).
- **Coffre-fort « données certifiées » 2 tiers** (`Certificateur Coffre Fort.cmd` +
  `src/hl_observer/datasets/coffre_certifie.py`) : tier LOCAL (certifié-local : répare/salvage/quarantaine)
  + tier SAFE-cloud référencé. Le labo charge les deux (`_charger_tier_local` dans `materialize_safe_workspace`,
  SHA-256 revérifié). **Mesuré** : fills causaux chargés `0 → 88 090`, carnets `50 170 → 433 920`.
- **Frontière vérifiée** : le moteur de décision/preuve du labo est **SAFE-provenance-bound** ; le tier
  LOCAL nourrit la recherche exploratoire mais ne peut jamais être « prouvé » (pas de fausse certification).
  La rentabilité prouvée exige du SAFE-cloud frais (que les lanes alimentent).
- **`POUSSER-GITHUB.cmd` : défaut = code seul** (push rapide, plus de téléchargement SAFE de 153 Go) ;
  `--full` pour l'ancien comportement complet.

## 1. Périmètre économique actif

Le périmètre canonique est défini par `src/hl_observer/strategies/active_scope.py`.

Famille économique paper active au niveau du runtime :

- `copy_vault` uniquement.

`lead_lag`, `cross_venue_dislocation`, l'arbitrage et les autres familles sont en pause.
Ils ne doivent être exécutés ni par le moteur principal AlinaSmartFlow, ni par la simulation
UI, ni par le laboratoire, les backtests ou les replays tant que ce périmètre temporaire
Copy-Vault-only reste en vigueur.

Toute réactivation exige un changement explicite du scope canonique et des tests associés.

## 2. Sécurité

Le projet reste **paper/read-only** :

- `HL_ENABLE_MAINNET_EXECUTION=0` ;
- `HL_ENABLE_TESTNET_EXECUTION=0` ;
- aucun ordre réel ;
- aucune signature ;
- aucune clé privée ;
- aucune donnée synthétique présentée comme preuve économique réelle ;
- toute donnée économique manquante ou non liquidable doit conduire à un verdict fail-closed.

La politique de signalement est dans `SECURITY.md`.

### 2.1 Contrat obligatoire avant tout futur trading réel

Le processus doit rester actif en continu pour observer et recalculer les opportunités, mais l'ouverture d'une position reste fail-closed lorsqu'aucun avantage net prouvé ne couvre les coûts et le risque. Le moteur d'exécution réel devra, avant son activation :

- lire le solde et la marge réellement disponibles, sans capital codé en dur, y compris pour un compte initial de 50 USD ;
- dimensionner chaque ordre en fraction du capital et de la liquidité exécutable observée ;
- conserver une réserve de marge et plafonner l'exposition, la perte par trade, la perte journalière et le drawdown cumulé ;
- bloquer uniquement les nouvelles prises de position lorsque ces limites sont atteintes, tout en continuant le scan et la réévaluation des signaux ;
- refuser un ordre si la taille minimale, les frais, le spread, le slippage ou le risque de liquidation empêchent une espérance nette positive dans les limites fixées ;
- ne jamais présenter la conservation du capital ou un rendement quotidien comme garanti.

Ces exigences ne lèvent pas le verrou paper/read-only actuel et ne constituent pas une autorisation de trading réel.

## 3. Chantier des 775 optimisations pré-run

Le registre canonique des **775 optimisations pré-run est scellé 775/775**. Il n'est pas permis de renuméroter, supprimer ou recycler les identifiants 1–775. Toute découverte réellement nouvelle commence à 776+.

La gate `.github/workflows/pre-run-321-775.yml` est désormais la gate technique principale : elle revalide les 775 puis impose aussi gouvernance, audit de vulnérabilités, analyse statique, suite complète et cliquet de couverture avant de publier le vert.

### 3.1 Roadmap technique cumulative V5 / 776+

La roadmap AgiFlow cumulative qui ré-audite et implémente le patrimoine `HYPERSMART_MASTER_ROADMAP_CODING_AGENTS_V5_2026-08-30.md` et les améliorations 776+ est distincte du statut historique `pre-run-775`.

Pour cette roadmap technique :

- un macro-lot est `Done` lorsque ses exigences techniques sont implémentées ou explicitement classées (`déjà-implémenté`, `corrigé`, `SUPERSEDED`, `DUPLICATE`, `KILLED`, `HISTORICAL`, `REJECTED` ou `BLOCKED`) avec preuves adaptées ;
- une stratégie peut rester `KILL`, `MORE_DATA`, négative ou non certifiée économiquement sans empêcher la fermeture d'un lot technique correctement réalisé ;
- **Aucune cible de profit ou PnL positif n'est un critère de Done de cette roadmap technique** ;
- les coûts, l'OOS, le forward, la liquidatabilité, la causalité et les autres invariants scientifiques restent obligatoires lorsqu'un lot touche ces surfaces ;
- aucune idée V5/776+ ne peut disparaître silencieusement : toute exigence doit garder une disposition traçable.

Cette séparation ne modifie pas la mission économique du produit : elle empêche seulement de confondre la complétion d'ingénierie avec la réussite d'une stratégie de trading.

## 4. Vérité économique

Aucune cible économique ne doit être déclarée atteinte sans preuve **LIQUIDATABLE_NET**, coûts complets, OOS, forward, placebo et échantillon suffisant.

Au gel de certification du 12/08/2026, sous un ancien périmètre multi-familles, les verdicts historiques documentés étaient :

- Copy-Vault : `MORE_DATA` ;
- Lead-Lag : `MORE_DATA` ;
- Cross-Venue v2 : `KILL`.

Ces verdicts ne décrivent pas l'état économique actuel. L'objectif économique actif est **l'amélioration continue de Copy-Vault**, avec un repère quantitatif de **+5 USD net/jour sur 350 USD paper**, sans en faire une gate automatique ou une promesse. Chaque gain NET mesuré est gelé comme expérience reproductible ; seuls les champions validés par OOS et forward post-freeze disjoints, coûts complets, causalité et gates de risque sont promouvables. La recherche reprend après chaque gel.
Un résultat exploratoire, TRAIN, synthétique ou simplement observé n'est pas
une preuve de PnL ; le statut actuel doit venir du dernier rapport valide.
Les anciennes références à **+5 USD net/jour sur 200 USD paper** sont historiques ;
le repère opérationnel actuel est 350 USD et ne constitue ni une gate automatique
ni une condition de clôture.

Un verdict économique `KILL`, `MORE_DATA` ou négatif n'empêche pas le logiciel d'être techniquement parfait : au contraire, refuser honnêtement une stratégie non prouvée fait partie de la qualité attendue.

## 5. PARFAIT / TOUT VERT — définition machine

La certification technique est **indépendante du verdict économique**.

La gate technique principale `.github/workflows/pre-run-321-775.yml` est l'unique autorité qui publie sur le SHA exact :

- `hypersmart/pre-run-775` ;
- `hypersmart/technical-perfect`.

Le workflow redondant `.github/workflows/security-quality.yml` publie son propre contexte distinct :

- `hypersmart/security-quality`.

`security-quality` ne doit jamais écrire `hypersmart/technical-perfect`. Cette séparation interdit qu'un workflow secondaire vert écrase le rouge de la gate 775 complète, ou inversement.

`hypersmart/pre-run-775` et `hypersmart/technical-perfect` ne peuvent être publiés `success` que lorsque :

1. 775/775 et les preuves dérivées sont verts ;
2. la gouvernance versionnée est cohérente ;
3. l'audit `pip-audit` est vert ;
4. Ruff ne détecte aucune erreur structurelle bloquante ;
5. les garde-fous sécurité sont verts ;
6. la suite complète sous `coverage` termine sans rouge ;
7. le cliquet de couverture ne descend pas sous la baseline.

`hypersmart/security-quality` certifie séparément gouvernance, supply-chain et couverture. Il complète la gate principale mais ne peut pas la remplacer.

S'il manque l'un des statuts obligatoires ou s'il est rouge, il est interdit de dire « PARFAIT / TOUT VERT » pour ce SHA.

Cette certification technique ne prétend jamais que Copy-Vault gagne de
l'argent. La preuve économique garde ses propres gates et son propre verdict.

## 6. Contrat Git : main-only

Le dépôt suit un contrat **main-only** : à la clôture d'un chantier, aucune branche de travail ou branche robot ne doit rester en plus de `main`.

En conséquence la surveillance des dépendances fonctionne **sans Dependabot**, car Dependabot crée obligatoirement des branches de PR. La surveillance est assurée par :

- `pip-audit` bloquant dans les gates ;
- le workflow hebdomadaire `security-quality` ;
- les versions exactes des outils CI dans `requirements-ci-tools.txt` ;
- les Actions tierces pinées par SHA et contrôlées par tests.

Une branche automatique détectée est une anomalie de gouvernance à nettoyer, pas une nouvelle branche de travail autorisée.

## 7. CI et certification

La certification globale attend au minimum :

- `hypersmart-ci` ;
- `hyperlab-ci` ;
- `labo-continu-ci` ;
- `alpha-factory` ;
- `portable-release-windows` ;
- `security-quality` ;
- `hypersmart/security-quality=success` ;
- `hypersmart/pre-run-775=success` ;
- `hypersmart/technical-perfect=success`.

La gate 775 principale est volontairement redondante avec `security-quality` sur les contrôles critiques, mais **chaque workflow publie un contexte de statut distinct**. La redondance ajoute une contre-vérification ; elle ne doit jamais créer deux auteurs concurrents pour le même verdict machine.

## 8. Gouvernance GitHub

La protection native de `main` reste un durcissement serveur recommandé lorsqu'elle est compatible avec le workflow main-only du dépôt. Elle est distincte de la perfection technique du code : un réglage administrateur GitHub que le dépôt ne peut pas modifier lui-même ne doit pas créer un faux rouge permanent.

Aucune protection serveur ne doit conduire à recréer une forêt de branches de travail. Les gates et statuts du SHA exact restent obligatoires pour la certification technique.

## 9. Dépendances et supply-chain

- Les GitHub Actions tierces doivent rester pinées sur des SHA immuables.
- La surveillance se fait **sans Dependabot** pour respecter `main-only`.
- `pip-audit` est bloquant et exécuté dans les certifications.
- La release Windows portable reste la chaîne la plus stricte : wheelhouse exact, hashes, SBOM et provenance.
- Les outils CI critiques sont pinés dans `requirements-ci-tools.txt`.
- Chaque passage supply-chain archive l'environnement Python réellement résolu.

## 10. Documents historiques

Les documents suivants sont **historiques** s'ils contredisent ce fichier ou les contrats exécutables actuels :

- `docs/archive/root-history/TASKLIST.md` ;
- `docs/archive/root-history/TASKLIST.md.avant_cloture` ;
- `docs/TASKLIST_ACTIVE.md` ;
- `docs/ETAT_ET_FEUILLE_DE_ROUTE.md` ;
- `runtime/research/ALPHA_PROGRESS.md` ;
- anciens rapports sous `docs/archive/`, `runtime/audit/` et répertoires de rapports.

Ils restent utiles pour la traçabilité, mais ne doivent plus être utilisés comme état courant.

## 11. Règle de clôture

Le projet n'est jamais déclaré « parfait » parce qu'un document le dit. Le verdict doit être dérivé du HEAD exact :

1. code et worktree cohérents ;
2. **une seule branche finale : `main`** ;
3. gates CI obligatoires vertes ;
4. sécurité paper/read-only verte ;
5. couverture sans régression ;
6. gouvernance versionnée conforme ;
7. `hypersmart/security-quality=success` ;
8. `hypersmart/pre-run-775=success` ;
9. `hypersmart/technical-perfect=success` ;
10. aucune preuve économique surclassée artificiellement.
