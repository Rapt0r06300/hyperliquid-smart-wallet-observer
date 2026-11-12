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

**Seconde séquence du 2026-11-11 (lectures ponctuelles autorisées) — commitée et poussée par `POUSSER-GITHUB-FORCE.cmd` à 17 h 34 : commit `bb41b323`, 90 chemins, `origin/main` aligné :**

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

### A. COLLECTEURS & CERTIFICATEUR — ≈ 110 tâches

**A1. Débit API & partage de l'unique adresse IP locale (⚡ cause des 429)**
- C1 ⚡ Budget de débit **partagé entre tous les processus** via un compteur + verrou fichier
  (token-bucket inter-process) : chaque collecteur réserve le poids réel d'une requête avant de
  l'émettre. Supprime les 429 de démarrage sans brider personne. (Aujourd'hui : seul un signal de
  congestion existe ; il faut un vrai budget commun.)
- C2 ⚡ Fenêtre glissante 60 s du **poids réellement consommé** (somme des `weight` observés), pas
  d'estimations par collecteur.
- C3 🔧 Respecter `Retry-After` **partout** (seuls vaults/liquidations/carnet le font).
- C4 🔬 Sonde légère (allMids) qui estime le quota IP restant et redistribue le budget en direct.
- C5 ⚡ Priorité de budget déclarée : fills causaux leaders > carnets des coins actifs > ordres en
  attente > vaults > rattrapages.
- C6 🔧 Mode dégradé automatique sous pression 429 : ralentir les collecteurs non critiques au lieu
  de les laisser échouer.
- C7 🔧 Jitter aléatoire au démarrage de chaque collecteur (évite la rafale synchronisée du lancement).
- C8 🔬 Poids EXACT par type de requête (`candleSnapshot` 20+1/60, `userFillsByTime` 20+1/20,
  `clearinghouseState` 2, `l2Book` WS 0) au lieu d'un forfait.
- C9 📊 Journal du budget : poids demandé/accordé/429 par collecteur et par minute → lisible par le labo.
- C10 🔬 Un « chef d'orchestre » de débit (process) qui alloue des jetons et arbitre les priorités.

**A2. Fiabilité & résilience (🔧)**
- C11 🔧 Reconnexion WS avec reprise au **watermark exact** (ni trou ni doublon) sur TOUS les flux.
- C12 🔧 Heartbeat applicatif ping/pong par socket + détection de pong manquant → ouverture d'époque
  de trou (déjà dans le collecteur de référence ; généraliser aux lanes et au collecteur principal).
- C13 🔧 Détection de « marché silencieux » (aucun message > seuil) : marquer trou, pas seulement compter.
- C14 🔧 Watchdog qui relance un collecteur mort en < 5 s **avec reprise d'état**.
- C15 🔧 Écriture d'état atomique (watermark, curseur) **partout** : écrire-puis-renommer.
- C16 📊 Journal structuré JSONL des incidents par collecteur (déconnexion, 429, rejet), exploitable par le labo.
- C17 🔧 Nettoyage des `.pid` orphelins au démarrage + détection de double instance.
- C18 🔧 Test de mort brutale (kill -9) : l'état reprend sans perte ni double-comptage.
- C19 🔬 Timeout de requête adaptatif à la latence observée (p95 glissant).
- C20 🔧 Déduplication inter-sources (REST/WS/poll) par identité de fill stable sur **tous** les flux.

**A3. Complétude de la couverture — ce qui rend les signaux EXÉCUTABLES (⚡ gros levier)**
- C21 ⚡ **Carnets L2 des coins HIP-3 (`xyz:`)** tradés par les leaders : 61 % du notionnel sans
  aucun carnet aujourd'hui. Vérifier le nom d'abonnement `l2Book` contre l'univers officiel d'abord.
- C22 ⚡ Générateur automatique de `config/copy_vault_coins.json` depuis les coins réellement tradés
  par les leaders des 7 derniers jours (fréquence pondérée par notionnel).
- C23 ⚡ **Carnet de SORTIE garanti** : pour chaque position ouverte d'un leader suivi, s'assurer
  qu'un carnet existe à +60 s, +300 s, +900 s, +1 h, +4 h (les horizons du labo). Sans ça : refus
  `STALE_OR_MISSING_EXIT_BOOK` (235 des 504 signaux TRAIN du 12/11).
- C24 ⚡ Carnet de RÉFÉRENCE garanti : un carnet dans les 30 s **avant** chaque signal leader.
- C25 ⚡ Abonnement L2 **déclenché par l'activité du leader** : dès le premier fill sur un coin,
  garder le carnet abonné jusqu'à la fermeture + horizon max (couvre entrée ET sortie).
- C26 🔬 Garder les vaults FERMÉS de la liste publique (mesure du biais de survie).
- C27 ⚡ Ordres en attente (`openOrders`) des leaders en continu, câblés aux lanes cloud.
- C28 🔧 Funding horaire de TOUS les coins tradés (pas seulement 29).
- C29 🔧 Bougies 1 h sur 208 j pour tous les coins actifs (incrémental).
- C30 🔧 Historique complet des fills des leaders lents (pagination curseur, déjà posé) — étendre à
  tous les leaders non-HFT.
- C31 🔬 Collecter les trades publics (`trades` WS) des coins actifs : mesure de l'impact de marché réel.
- C32 🔬 Collecter les variations d'`openInterest` et le premium mark/oracle par coin (déjà partiel).
- C33 🔬 Collecter les liquidations confirmées en continu (déjà posé) et les relier aux carnets.
- C34 🔬 Snapshots de portefeuille complet des leaders (dex réunis) en tête ET fin de passe (déjà posé).
- C35 ⚡ Couvrir les marchés des leaders **avant** qu'ils tradent (pré-abonnement sur leurs coins
  habituels) : capture la référence sans attendre le premier fill.

**A4. Intégrité causale & provenance (⚡ la cause du blocage)**
- C36 ⚡ `connection_id` + `l2_gap_epoch` sur CHAQUE carnet (fait ce jour pour lane + collecteur
  principal ; vérifier qu'aucun autre écrivain de carnet n'en manque).
- C37 ⚡ `capacity_usd` sur chaque carnet de lane (fait ce jour) + vérifier les carnets micro.
- C38 🔧 Époque de trou cohérente : +1 à chaque déconnexion / trame rejetée / réabonnement, jamais
  sur un simple silence (fait ce jour ; ajouter un test de non-régression sur données réelles).
- C39 🔬 Horodatage de réception à l'instant EXACT de lecture du socket (pas après traitement).
- C40 🔧 Refuser tout carnet `received < exchange` ou lag > 30 s (déjà fait ; auditer les rejets).
- C41 🔬 `writer_run_id` + `clean_epoch_ms` sur les checkpoints exacts (déjà dans le protocole).
- C42 🔬 Marquer `data_origin=REAL_OBSERVED` vs reconstruit partout ; interdire toute confusion.
- C43 ⚡ Checkpoints exacts par métaordre (référence/entrée/sortie liés cryptographiquement) : le
  collecteur principal sait les écrire pour les coins à métaordre actif — étendre la couverture.
- C44 🔬 Vérifier que l'horloge de réception est monotone par socket (détecte un décalage d'horloge).
- C45 🔧 Provenance tier (LOCAL vs SAFE) jamais perdue dans le pont du labo.

**A5. Certificateur — reconnaître et sceller tout flux (🔧)**
- C46 🔧 Chaque nouveau flux a une règle de certification OU un motif explicite (jamais ignoré en silence).
- C47 ⚡ Certifier les familles `book_l2`, `bbo`, `leader_orders`, `funding_history`, `candle` avec
  leurs champs d'identité préservés (fait en partie ; auditer que `connection_id`/`l2_gap_epoch`
  survivent au scellage ET au rechargement — prouvé ce jour, ajouter garde permanente).
- C48 🔧 Rattrapage des archives sans dupliquer ce qui est déjà au coffre (déjà posé).
- C49 🔧 Détecter l'altération d'un shard déjà scellé (SHA-256) et refuser l'écrasement.
- C50 📊 Rapport de couverture : par famille, combien scellé / réparé / écarté / inconnu.
- C51 🔬 Certifier les ordres en attente (snapshot = un tout ; rejeter compte incohérent, doublon,
  ordre postérieur à l'observation).
- C52 🔬 Certifier les bougies avec intervalle inféré de la source ; quarantaine si absent.
- C53 🔧 `EQUIVALENT_SAFE` pour chaque famille locale (le labo sait ce qu'il peut « prouver »).
- C54 🔧 Verrou de certification (évite deux scellages concurrents) + attente bornée.
- C55 📊 Inventaire par famille des shards SAFE non utilisés pour le PnL (contexte vs preuve).
- C56 🔬 Certifier les trades publics, l'OI, le premium, les liquidations (nouvelles familles).
- C57 🔧 `LOCAL_INDEX.json` + `SOURCES_TRAITEES.json` toujours cohérents (test d'intégrité).
- C58 🔧 Quarantaine horodatée avec motif lisible pour chaque ligne écartée.
- C59 🔬 Revérifier le magasin de ticks natifs par rotation (immuable à la rotation).
- C60 🔧 Ne jamais baisser les exigences de qualité pour gonfler le nombre de shards.

**A6. Cadence intelligente pilotée par le labo (🔬)**
- C61 🔬 Classes de cadence PRIORITAIRE / STANDARD / DÉCOUVERTE / ARCHIVE depuis le plan du labo
  (`copy_vault_besoins_collecte.json`) — déjà posé ; raffiner par valeur-d'information.
- C62 🔬 Un leader qui vient d'émettre est poll plus souvent ; un leader calme, espacé (budget libéré).
- C63 🔬 ARCHIVE = HFT non copiable ou clone : échantillon borné, pas flux complet.
- C64 🔬 Le labo publie « ce qu'il manque pour mesurer » (quels coins, quels horizons) → le collecteur
  cible exactement ça. Boucle fermée labo → collecteurs.
- C65 ⚡ Priorité de collecte des carnets sur les coins/horizons où le labo a des signaux SANS sortie.
- C66 🔬 Sélection des leaders par valeur : notionnel copiable × fraîcheur × part exécutable.
- C67 🔬 Retirer de l'univers les clones (mêmes fills, décalés) détectés par corrélation.
- C68 🔬 Découvreur autonome de nouveaux leaders actifs (déjà posé) → filtrer sur copiabilité.
- C69 🔬 Cadence adaptative des bougies : coins volatils plus souvent.
- C70 🔬 Budget de rattrapage qui cède toujours la place au direct (fait ce jour, `ALINA_SIGNAL_DEBIT`).

**A7. Lanes cloud multi-IP (🔧)**
- C71 ⚡ Les lanes prennent l'identité de connexion des carnets après push (le fix de ce jour est
  local ; le cloud l'héritera du code poussé).
- C72 🔧 Une IP par lane (runner GitHub) : vérifier que chaque lane a bien son budget propre (55/min).
- C73 🔧 Tranches de coins disjointes par lane (shard-index) sans chevauchement.
- C74 🔧 Rapatriement + fusion automatiques (dédup + fraîcheur) dans AlinaSync.
- C75 🔬 Lanes dédiées HIP-3 (coins `xyz:`) séparées des lanes principales.
- C76 🔧 Leaders/coins commitables (`config/copy_vault_leaders.json`, `copy_vault_coins.json`) +
  garde-fou (zéro leader = refus).
- C77 📊 Chaque lane publie un reçu de couverture (coins, fenêtre, reconnexions, trous).
- C78 🔧 Détecter une lane morte et redistribuer ses coins.
- C79 🔬 Lanes « sortie » dédiées : ne gardent abonnés que les coins à position ouverte, longtemps.
- C80 🔧 Fréquence des lanes réglable sans redéploiement (variable de workflow).

**A8. Qualité, mesure & observabilité (📊)**
- C81 📊 Tableau de bord temps réel : par flux, lignes/s, fraîcheur, trous, 429, reconnexions.
- C82 📊 Mesure « exécutabilité » en direct : % de fills leaders qui auront référence+entrée+sortie.
- C83 📊 Alerte si un coin actif n'a aucun carnet depuis N minutes.
- C84 📊 Rapport quotidien de complétude (déjà posé) enrichi de l'exécutabilité par coin.
- C85 🔬 Mesurer la latence réelle réception − bourse par flux (distribution, pas moyenne).
- C86 ✅ Fills passifs vs agressifs par leader : **FAIT** (section C, point 21) — devenu un filtre decisionnel.
- C87 📊 Score de « santé du carburant » : combien de signaux deviendront scoreables.
- C88 🔧 Tester chaque `.cmd` en tâche de fond régulièrement (`tools/tester_cmds.py`) — déjà posé.
- C89 📊 Historiser le nombre de refus 429 par essai du lanceur (218 → 32 mesuré ; viser ~0).
- C90 🔬 Détecter les fills de même instant (tie) et les ordonner de façon déterministe.

**A9. Stockage, archivage, rejouabilité (🔧)**
- C91 🔧 Archivage sans perte (déplacer, jamais supprimer) + certification avant archivage.
- C92 🔧 Rotation des rubans volumineux à la taille, pas à la session.
- C93 🔧 Compression gz des shards certifiés (déjà fait) + vérification d'intégrité.
- C94 🔧 `vault_snapshots.jsonl` : le scoreur relit l'historique archivé (fait ce jour) — étendre à
  tous les flux qui repartent de zéro après certification.
- C95 🔬 Index temporel des carnets par coin pour un chargement O(log n) côté labo (fait côté moteur).
- C96 🔧 Interning des chaînes répétées dans les gros rubans (fait côté labo ; étendre).
- C97 🔧 Ne jamais garder deux copies d'un carnet en mémoire pendant le scellage.
- C98 📊 Taille du coffre par famille et par jour (tendance).
- C99 🔧 Purge sûre des rubans de travail du labo après usage.
- C100 🔧 Sauvegarde du registre de coffre avant toute réécriture (déjà posé pour les reçus).

**A10. Nouveaux flux à forte valeur (🔬)**
- C101 🔬 Carnet L2 **profond** (plus de 5 niveaux) sur les coins où l'on veut mesurer l'impact.
- C102 🔬 Flux des annulations d'ordres des leaders (anticipation : un ordre annulé n'est pas copiable).
- C103 🔬 Flux des modifications d'ordres (prix/taille) pour reconstruire l'intention.
- C104 🔬 Taux de financement prévisionnel (predicted funding) pour anticiper le coût de portage.
- C105 🔬 Profondeur cross-venue (Binance/Bybit) alignée pour mesurer la dislocation réelle.
- C106 🔬 Carnet au moment EXACT de chaque annonce de funding (coût de portage chiffré).
- C107 🔬 Flux des positions agrégées du marché (skew long/short) par coin.
- C108 🔬 Détection des « méta-ordres » leaders (tranches d'un même ordre) à la collecte, pas au labo.
- C109 🔬 Flux des vaults entrants/sortants (dépôts/retraits) pour le NAV as-of (déjà posé, étendre).
- C110 ✅ **FAIT** le 12/11 (section C, point 20) — réconciliation en direct : chaque fill leader a-t-il ses trois
  carnets ; sinon, demander la collecte manquante immédiatement (boucle d'auto-réparation).

---

### B. LABORATOIRE — ≈ 110 tâches

**B1. Exécutabilité & préparation des données (⚡ débloque la mesure)**
- L1 ⚡ Sonde d'exécutabilité TRAIN avant la recherche (fait ce jour) : aucun trade exécutable →
  `TRAIN_NOT_EXECUTABLE`, zéro essai compté, refus détaillés par motif.
- L2 ✅ Même sonde sur VALIDATION / OOS : **FAIT** le 12/11 (section C, point 19) — refus porté par `promotion_gate`.
- L3 ⚡ Parité d'univers labo ↔ moteur : le labo retire les HFT/clones de ses signaux (le moteur les
  refuse déjà) — sinon pseudo-réplication.
- L4 🔬 Diagnostic « pourquoi ce signal n'est pas exécutable » par motif, agrégé par coin/jour.
- L5 ⚡ Carte de chaleur « signaux avec/sans carnet de sortie » par coin → pilote la collecte (C65).
- L6 🔬 Distinguer OBSERVÉ EN DIRECT (délai ≤ 5 min) de RECONSTRUIT (délai supposé) — déjà posé.
- L7 🔧 Jamais transformer une info récupérée après coup en info « disponible au moment de la décision ».
- L8 🔬 Mesurer la fraction de signaux évaluables par jour (règle des jours denses, déjà posée).
- L9 🔬 Compter précisément les signaux perdus à chaque filtre (déjà : `candidate_audit`).
- L10 ⚡ Afficher dans le rapport le chemin complet d'un signal : collecté → certifié → aligné → exécuté.

**B2. Découverte d'avantage — nouvelles hypothèses (🔬 le cœur)**
- L11 🔬 Réplication lente d'inventaire (déjà posée) : copier la POSITION du leader, pas ses fills.
- L12 🔬 Ouvertures agressives sélectionnées (déjà posée) : suivre les leaders dont les ouvertures
  passées et dénouées ont rapporté après coûts.
- L13 🔬 Intention d'ordre (déjà posée) : ordre jumeau prudent exécuté seulement si une clôture
  traverse strictement le prix limite.
- L14 🔬 Persistance de compétence des leaders (déjà posée) : IC de rang, effets aléatoires bayésiens.
- L15 🔬 Modèle de sélection de leaders (déjà posé) : walk-forward sur résultats dénoués.
- L16 🔬 Momentum du carnet (OFI, order-flow imbalance) comme signal d'entrée.
- L17 🔬 Déséquilibre de profondeur signé (déjà dans v21) comme filtre.
- L18 🔬 Fade de liquidation : entrer contre un débordement mark/oracle (overshoot, déjà posé).
- L19 🔬 Copie conditionnée à la taille du fill leader (gros fill = plus d'information).
- L20 🔬 Copie conditionnée au type de leader (DIRECTIONAL_SLOW vs SWING vs HFT).
- L21 🔬 Copie conditionnée à la fraîcheur du carnet (plus frais = moins de dérapage).
- L22 🔬 Copie conditionnée à la volatilité réalisée récente (régime calme vs agité).
- L23 🔬 Copie conditionnée au funding (éviter de porter contre un funding coûteux).
- L24 🔬 Signal « cluster de leaders » : plusieurs leaders ouvrent le même coin dans la même minute.
- L25 🔬 Signal « divergence cross-venue » : HL vs Binance/Bybit (dislocation réelle, déjà des briques).
- L26 🔬 Signal « premium mark/oracle extrême » comme déclencheur de fade.
- L27 🔬 Signal « OI qui monte vite » (positionnement du marché).
- L28 🔬 Anti-signal : ne pas copier quand le leader est en train de se faire liquider.
- L29 🔬 Signal « ordre en attente anticipé » : le leader a posé un ordre limite → se préparer.
- L30 🔬 Signal « réduction du leader » : copier aussi les sorties (REDUCE/CLOSE), pas que les entrées.
- L31 🔬 Horizon dynamique : tenir jusqu'à ce que le leader réduise, pas un horizon fixe (déjà en v5).
- L32 🔬 Stop/take-profit en bps nets exécutables (déjà en v21) — chercher les seuils.
- L33 🔬 Sizing ciblé-volatilité (déjà un domaine de recherche) : homogénéiser le PnL quotidien.
- L34 🔬 Plafond de perte journalière + verrou de profit journalier (déjà des domaines).
- L35 🔬 Limites par coin / par vault / positions ouvertes (déjà des domaines) — chercher.

**B3. Réalisme d'exécution & coûts (⚡ sinon faux positifs)**
- L36 ⚡ Frais taker canoniques Hyperliquid (autorité de frais, jamais locaux en mode certifiable).
- L37 ⚡ Spread payé = demi-spread observé au carnet d'entrée (pas mid).
- L38 ⚡ Coût de financement sur toute position chevauchant une frontière de funding horaire.
- L39 🔬 Impact de marché : taille vs capacité du carnet (capacity_usd) — pénaliser les gros ordres.
- L40 🔬 Délai de copie réaliste (60 s, déjà) : l'entrée se fait au premier carnet après signal+délai.
- L41 🔬 Slippage = écart entre prix visé et prix exécutable au carnet réel.
- L42 🔬 Latence de réaction (déjà modélisée) : 60 s entre observation et ordre.
- L43 🔬 Non-exécution comptée : si aucune clôture ne traverse le prix limite, l'ordre jumeau n'est pas rempli.
- L44 🔬 Capital paper fixe 350 USD, levier ≤ 1, exposition brute ≤ 350 (déjà).
- L45 🔬 Décomposer le PnL : brut, frais, funding, spread, slippage, net (déjà une brique).
- L46 🔬 Liquidabilité nette : prouver que la position est fermable au carnet réel (déjà `LIQUIDATABLE_NET`).
- L47 🔬 Coût d'opportunité du capital bloqué (plusieurs positions simultanées).
- L48 🔬 Modéliser le refus d'ordre (reduce-only, post-only) selon le type.
- L49 🔬 Frontière de funding exactement égale à l'entrée = position non chiffrable (déjà refusée).
- L50 🔬 Comparer systématiquement à une baseline « ne rien faire » et à « acheter-tenir ».

**B4. Rigueur statistique & anti-surapprentissage (⚡ crédibilité)**
- L51 ⚡ Verdict « prouvé » seulement si VALIDATION + OOS + FORWARD passent tous après coûts.
- L52 ⚡ Borne basse de confiance (LCB) > 0 exigée, avec correction de multiplicité (Bonferroni).
- L53 ⚡ Compter TOUS les essais dans la multiplicité (la sonde évite d'en compter à vide — gros gain).
- L54 🔬 Bootstrap par blocs sur les jours (dépendance sérielle).
- L55 🔬 Test placebo par permutation (inverser le sens ne doit pas gagner).
- L56 🔬 Contrôles appariés (−7 / −14 jours) pour isoler l'effet du régime de marché.
- L57 🔬 Effets aléatoires bayésiens (DerSimonian–Laird) pour la persistance.
- L58 🔬 Poids de quantile sûrs aux égalités (une égalité ne fabrique pas un faux signal).
- L59 ⚡ Échantillon minimum AVANT de lire l'intervalle (4 jours = un seul régime).
- L60 🔬 Prior sceptique dans le planificateur (ne pas croire un effet sur peu de données).
- L61 🔬 Walk-forward : sélectionner sur le passé dénoué, mesurer sur le futur.
- L62 🔬 Purge temporelle entre segments (pas de fuite par l'horizon de détention).
- L63 🔬 Profit factor > 1 ET net > 0 ET concentration faible (pas un seul trade qui porte tout).
- L64 🔬 Détecter la concentration par coin / par vault / par trade (déjà des gardes).
- L65 🔬 Nombre de jours actifs = levier dominant du LCB (√n) : le rapport l'explique déjà.

**B5. Recherche intelligente — valeur d'information (🔬 vitesse)**
- L66 🔬 Planificateur par valeur-d'information : tester d'abord l'hypothèse au plus fort gain espéré
  par unité de calcul (déjà une brique `copy_vault_research_planner`).
- L67 🔬 A priori par hypothèse (certaines sont plus prometteuses) + mise à jour bayésienne.
- L68 🔬 Lectures : SIGNAL PROMETTEUR / SIGNAL FRAGILE / DONNÉES INSUFFISANTES / ABSENCE D'AVANTAGE.
- L69 🔬 Arrêt précoce d'une hypothèse réfutée (ne plus y consacrer de calcul) — déjà dans le plan.
- L70 🔬 Comparer chaque hypothèse à une approche plus simple (parcimonie).
- L71 🔬 Échantillonnage de Halton / quasi-aléatoire de l'espace de paramètres (couverture).
- L72 🔬 Cache de la partie invariante de l'appariement (features de profondeur) — déjà fait.
- L73 🔬 Mémoïser les épisodes reconstruits entre étapes (fait ce jour) — zéro recalcul.
- L74 🔬 Index des carnets calculé une fois par liste (fait ce jour) — zéro re-parcours.
- L75 🔬 Reprise de campagne réconciliée (ne pas réutiliser un id de candidat).
- L76 🔬 Détecter les variantes dégénérées (toutes identiques faute de données) et les sauter.
- L77 🔬 Explorer la variante overshoot seulement si le contexte existe (fait ce jour).
- L78 🔬 Quota de temps/mémoire par passage ; borne dure (le PC coupe à 30 min).
- L79 🔬 Journal du nombre de configurations uniques testées (multiplicité honnête).
- L80 🔬 Détecter un plateau (plus d'amélioration) et élargir l'espace de recherche automatiquement.

**B6. Leaders — qualité & sélection (🔬)**
- L81 🔬 Revue de qualité des leaders V9 en ligne (déjà une brique) : note consultative, jamais preuve.
- L82 🔬 Biais de sélection : ne juger que les décisions POSTÉRIEURES au début du suivi.
- L83 🔬 Détecter les clones (corrélation des fills) et les fusionner en un seul signal.
- L84 🔬 Archétype par leader (DIRECTIONAL_SLOW / SWING / HFT / INSUFFICIENT) — déjà posé.
- L85 🔬 Copiabilité par leader = part de son expo qu'on peut réellement pricer/exécuter.
- L86 🔬 Persistance : un bon leader reste-t-il bon le mois suivant ?
- L87 🔬 Pondérer un leader par la fraîcheur de ses fills (récents = plus informatifs).
- L88 🔬 Retirer les leaders dont tous les fills sont passifs (gain ≈ 0 avant frais).
- L89 🔬 Mesurer la latence observée par leader (certains sont observables, d'autres non).
- L90 🔬 Portefeuille de leaders diversifié (corrélation faible entre eux).

**B7. Capital, risque, portefeuille (🔬)**
- L91 🔬 Allocation du capital 350 USD entre positions simultanées (Kelly fractionné prudent).
- L92 🔬 Drawdown maximum mesuré et borné.
- L93 🔬 Corrélation entre positions ouvertes (ne pas tout miser sur un régime).
- L94 🔬 Verrou de profit / plafond de perte journaliers (déjà des domaines).
- L95 🔬 Sizing ciblé-volatilité pour homogénéiser le PnL quotidien.
- L96 🔬 Réserve de marge pour ne jamais être liquidé en paper.
- L97 🔬 Mesurer le ratio de Sharpe / Sortino quotidien, pas juste le PnL moyen.
- L98 🔬 Espérance par jour = débit du compte × net moyen de TOUTES les décisions (pas un chemin de capital chanceux).
- L99 🔬 Stress-test : rejouer sur les pires jours (choc de volatilité).
- L100 🔬 Capacité de la stratégie : à quel capital le PnL s'effondre (impact de marché).

**B8. Reproductibilité, audit, rapport (📊)**
- L101 📊 Registre d'expériences `EXPERIENCES.ndjson` vérifié (chaîne de hachage) — déjà posé.
- L102 📊 SHA-256 du moteur et de la config dans chaque reçu (empreinte).
- L103 📊 Rapport honnête : « non mesurable » expliqué par motif (fait ce jour).
- L104 📊 Rapport : ne jamais présenter une estimation d'entraînement comme « prouvée » (fait ce jour).
- L105 📊 Rapport : lister les refus d'exécution avec ce qu'il faut pour les lever (fait ce jour).
- L106 📊 Plan de recherche `PLAN_DE_RECHERCHE.md` avec priorité par valeur-d'information.
- L107 📊 Historique des améliorations gelées (paliers prouvés) — honnête sur les valeurs illisibles.
- L108 🔧 Chaque outil qui lance pytest passe par `run_isole` (Ctrl+C propre).
- L109 📊 `donnees_consommees` dans chaque run (quelles familles, combien de lignes).
- L110 📊 Verdict final clair : PROVEN / PROMISING / MORE_DATA / UNMEASURABLE / REJECTED.

---

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

### C-ter. *(SUPERSÉDÉ par C-quater)* CHANTIERS VERS UN PnL POSITIF (12/11, demande de Florent — audit : tout est négatif)

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

### C-quater. PROGRAMME COMPLET VERS UN PnL ULTRA-POSITIF (12/11 — « tous les chantiers »)

**Cadre.** L'audit est sans appel : **toutes les hypothèses mesurées sont négatives** (copie naïve
REJECTED, ouvertures −18 bps, sélectionnées −7, persistance ≈ 0). Un PnL positif ne viendra que si on
attaque simultanément les trois causes — **coût**, **latence**, **sélection** — et qu'on explore des
stratégies au-delà de la copie de fills. Ci-dessous, 8 PROGRAMMES, chacun avec ses chantiers concrets,
priorité ⚡ (débloque la mesure) / 💰 (attaque le coût) / ⏱️ (attaque la latence) / 🎯 (sélection) /
🧪 (nouvelle stratégie) / 🛡️ (risque) / 🔬 (rigueur) / 🏗️ (infra). Aucun gain promis : chaque chantier
est une HYPOTHÈSE à mesurer puis prouver (VALIDATION → OOS → FORWARD).

**PROGRAMME A — RENDRE LE LABO MESURABLE (prérequis absolu, rien ne compte avant) ⚡**
- A1. Collecte continue corrigée pendant **≥ 6 jours denses** (identité + carnet de sortie + HIP-3).
- A2. Garantir référence (−30 s) : pré-chauffer les coins habituels des leaders AVANT leurs fills.
- A3. Garantir entrée (+60 s) et sortie (+horizon) : abonnement tenu jusqu'à fermeture + horizon max (fait).
- A4. Collecter `leader_orders` EN LOCAL (aujourd'hui cloud-only) — débloque les programmes B/C/D.
- A5. Collecter TOUS les coins HIP-3 tradés (61 % du notionnel) + régénérer la liste par exécutabilité (fait).
- A6. Suivre le déblocage coin par coin (`tools/etat_executabilite.py`, `audit_complet.py`) jusqu'à « mesurable ».
- A7. Parité d'univers labo ↔ moteur : retirer HFT/clones des signaux (le moteur les refuse déjà).

**PROGRAMME B — ATTAQUER LE COÛT (frais + spread ≈ 5–9 bps aller-retour = tueur n°1) 💰**
- B1. **MAKER** : exécuter aux ordres-limites du leader → gagner le ½ spread + frais maker (déjà codé,
  `copy_vault_order_intent` ; bloqué par A4). Chantier phare.
- B2. Entrée post-only / passive : modéliser la probabilité de remplissage (le marché traverse-t-il ?).
- B3. Optimiser le rebate maker (Hyperliquid) ; mesurer net AVEC rebate.
- B4. Moins d'allers-retours : copier moins souvent mais plus gros (amortir le coût fixe).
- B5. Palier de frais par volume : estimer le frais taker effectif au volume paper visé.
- B6. Meilleure exécution cross-venue : router vers la venue au spread le plus serré (carnet_venues).
- B7. Timing du spread : n'entrer que quand le demi-spread observé est faible (filtre de coût).
- B8. Sortie maker aussi quand possible (ordre-limite de sortie au lieu de taker).

**PROGRAMME C — ATTAQUER LA LATENCE (7,6 bps partent AVANT l'observation) ⏱️**
- C1. **Balayage de latence** 5/15/30/60/120 s sur carnets réels (codé, `chantier_latence.py`). À lancer
  sur données fraîches. Si net positif à 5 s → copier vite est LA voie.
- C2. Réaction sous la seconde via WS (supprimer le délai de 60 s modélisé quand l'observation est directe).
- C3. Modéliser le flux le plus rapide (fills WS vs poll) ; prioriser les leaders observables en direct.
- C4. **ANTICIPER** via `leader_orders` : agir sur l'ordre-limite AVANT le fill (intention, pas réaction).
- C5. Signal « première tranche » : agir dès le 1er fill d'un méta-ordre sans attendre les suivants.
- C6. Mesurer la latence réelle réception−bourse par leader et par flux (distribution, pas moyenne).

**PROGRAMME D — SÉLECTION & CONDITIONNEMENT (transformer −7 bps en sous-ensemble positif) 🎯**
- D1. Modèle de sélection de leaders : walk-forward, décisions DÉNOUÉES et POSTÉRIEURES au suivi, net>0.
- D2. Conditionnement OFI (micro_l2) : ne copier que si le déséquilibre de flux va dans le sens du leader.
- D3. Conditionnement overshoot/fade (asset_ctx mark vs oracle) : éviter / exploiter le débordement.
- D4. Conditionnement de régime : volatilité réalisée (bougies), funding, heure/session.
- D5. Conditionnement par taille de fill : un gros fill agressif porte plus d'information.
- D6. Conditionnement par coin : certains marchés sont plus copiables (mesurer, pas supposer).
- D7. Conditionnement dislocation cross-venue (dispersion_venues) : copier quand HL décroche.
- D8. Consensus multi-leaders : plusieurs leaders ouvrent le même coin dans la minute → signal renforcé.
- D9. Anti-signaux : ne pas copier un leader en liquidation, ni un clone, ni un fill passif (gain ≈ 0).
- D10. Recherche automatique du MEILLEUR sous-ensemble de conditions (valeur d'information, anti-overfit).

**PROGRAMME E — STRATÉGIES AU-DELÀ DE LA COPIE DE FILLS (diversifier les sources d'avantage) 🧪**
- E1. **Réplication lente par position** (`vault_portfolio`, chargé) : copier la position, moins sensible au timing.
- E2. Market-making autour des positions des leaders (poser des deux côtés, capter le spread).
- E3. Arbitrage de funding (carry) : porter quand le funding paie, en couvrant la direction.
- E4. Fade de liquidation (overshoot) : entrer CONTRE un débordement mark/oracle extrême.
- E5. Arbitrage cross-venue : exploiter la dislocation HL vs Binance/Bybit (briques déjà présentes).
- E6. Retour à la moyenne sur overshoot ; momentum sur OFI soutenu.
- E7. Copie d'INTENTION (ordres en attente) plutôt que de fills (anticipation pure).
- E8. Suivi des ouvertures agressives SÉLECTIONNÉES uniquement (la moins négative — l'approfondir).

**PROGRAMME F — CAPITAL & RISQUE (maximiser le Sharpe, pas seulement le PnL) 🛡️**
- F1. Dimensionnement Kelly fractionné prudent sur les 350 USD.
- F2. Sizing ciblé-volatilité (homogénéiser le PnL quotidien, réduire σ).
- F3. Diversification de portefeuille : leaders/coins à faible corrélation.
- F4. Contrôle du drawdown ; verrou de profit / plafond de perte journaliers.
- F5. Levier dynamique sous le plafond paper (≤ 1).
- F6. Analyse de CAPACITÉ : à quel capital l'avantage s'effondre (impact de marché).
- F7. Réserve de marge : ne jamais être liquidé en paper.
- F8. Mesurer Sharpe/Sortino quotidiens, espérance = débit × net moyen de TOUTES les décisions.

**PROGRAMME G — RIGUEUR & PREUVE (ne jamais se mentir) 🔬**
- G1. Portes VALIDATION → OOS → FORWARD après coûts et liquidité (une stratégie n'est prouvée qu'ainsi).
- G2. Correction de multiplicité (Bonferroni) : TOUS les essais comptent (la sonde évite les essais à vide).
- G3. Bootstrap par blocs sur les jours + placebo par permutation (inverser le sens ne doit pas gagner).
- G4. Walk-forward strict ; purge temporelle entre segments (pas de fuite par l'horizon).
- G5. **FORWARD paper en direct** : le juge ultime — rejouer en temps réel sur données non vues.
- G6. Robustesse de régime : prouver sur plusieurs conditions de marché, pas une fenêtre chanceuse.
- G7. Minimum d'échantillon AVANT de lire l'intervalle ; prior sceptique dans le planificateur.

**PROGRAMME H — INFRASTRUCTURE & DONNÉES (tout ce qui alimente) 🏗️**
- H1. Toutes les familles de données utilisées (fait : 7 rebranchées ; reste `leader_orders` en local).
- H2. Budget de débit partagé inter-process (fait) — éprouver en vrai sur un cycle complet.
- H3. Collecte complète garantie (référence + entrée + sortie) — le vrai débloquage de la mesure.
- H4. Mémoire : labo par morceaux, étape 1 isolée (fait) — ne jamais lancer labo + suite ensemble (OOM).
- H5. Vitesse du labo : perf par essai, index des carnets (fait), épisodes mémoïsés (fait).
- H6. Reproductibilité : reçus, SHA du moteur/config, registre d'expériences vérifié.
- H7. Audit permanent : `audit_complet.py` à chaque cycle ; aucune donnée gâchée ne doit réapparaître.
- H8. PAPER engine : simulation fidèle (frais canoniques, funding, spread, slippage, latence, drawdown).

**ORDRE D'EXÉCUTION RECOMMANDÉ :** A (mesurable) → en parallèle B1(maker)+C1(latence) dès que des
signaux sont exécutables → D (conditionnement) pour isoler un sous-ensemble positif → E (stratégies
alternatives) si la copie reste négative → F/G (risque+preuve) sur toute piste prometteuse → FORWARD.
**Sans A, rien ne se mesure. Le PnL positif, s'il existe, se trouve dans B×C×D (coût bas + réaction
rapide + bonne sélection), ou dans E (autre source d'avantage).**

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

### C-septies. 200 TÂCHES « MON BOT COPY-VAULT PARFAIT » vers un MÉGA PnL positif (12/11)

**Posture.** Écrit comme si ce bot était le mien et que je dispose de TOUS nos outils à la racine. La plupart
de ces modules EXISTENT déjà (`src/hl_observer/backtesting/*`, `tools/*`) mais ne sont ni branchés dans la
décision, ni mesurés honnêtement : la plus grosse avancée est souvent de CÂBLER + MESURER l'existant, pas de
réécrire. Chaque tâche référence un module/outil réel.

**État de l'art (recherche web, à intégrer) :** (1) sur Hyperliquid, les takers paient un coût d'exécution,
les makers gagnent le spread → l'exécution MAKER est le levier n°1 ; (2) adverse selection de latence : les
rapides « pick off » les lents → la vitesse et l'anticipation comptent ; (3) crowding = piège : un gros acteur
peut appâter les copieurs puis les liquider (≈ 4 M$ refilés au HLP) → modéliser le crowding, ne pas être
prévisible ; (4) leaderboards de vaults biaisés par la survie → sélection causale, pas sur le PnL passé ;
(5) juger un leader sur profit factor / drawdown / longueur d'historique, pas le win rate.

**THÈME 1 — SIGNAL : lire l'intention du leader plus tôt et mieux**
- T1. Détecteur d'ordre iceberg : plusieurs fills même niveau ⇒ gros méta-ordre (`copy_vault_order_intent`+`collecter_contexte_lane`).
- T2. Détecteur de TWAP leader : cadence régulière des fills ⇒ prédire les tranches suivantes et se placer avant.
- T3. Signal « premier fill du cluster » : agir dès la 1re tranche (`cluster_metaorders`) sans attendre le méta-ordre complet.
- T4. Pression des ordres en attente du leader (`leader_orders`) comme signal directionnel AVANT l'exécution.
- T5. Détection d'annulation massive ⇒ retrait d'intention ⇒ ne pas copier / sortir.
- T6. Taille du fill vs historique du leader : fill anormalement gros = conviction ⇒ pondérer plus.
- T7. Vitesse d'accumulation : dérivée de la position (`vault_portfolio`) comme signal d'urgence.
- T8. Signal multi-compte : même acteur sur plusieurs vaults ⇒ dédupliquer et renforcer.
- T9. Distinguer Open / Add / Close (`copy_vault_v7_exit_flow_train`) et traiter chacun différemment.
- T10. Détecteur de retournement : leader qui passe long→short sur un coin = signal fort.
- T11. Filtre d'agressivité : fill qui traverse le spread (taker) = info ; fill passif = bruit.
- T12. Écarter spoof / wash / self-trades de l'univers (`copy_vault_universe_integrity`).
- T13. Score de nouveauté : coin jamais tradé par le leader = alpha potentiel (moins crowdé).

**THÈME 2 — ANTICIPATION & LEAD-LAG (brancher la famille `lead_lag_*`)**
- T14. Câbler `lead_lag_multiasset_train` dans la décision : coins menants ⇒ anticiper les suiveurs.
- T15. Lead-lag leader→marché : les fills d'un leader précèdent-ils le prix ? (`lead_lag_causal_diagnostic`).
- T16. Résidu lead-lag (`lead_lag_reference_residual`) : isoler le mouvement propre du bêta marché.
- T17. Confirmation par carnet (`lead_lag_book_confirmation`) : ne copier que si le carnet confirme.
- T18. Timing file maker (`lead_lag_maker_queue_train`) : se placer dans la file au bon instant.
- T19. Courbe du sniper (`sniper_horizon_curve`) : avantage par horizon ⇒ horizon optimal par coin.
- T20. Lead-lag BBO repricing (`lead_lag_bbo_repricing_train`) : anticiper le repricing après un fill.
- T21. Lead-lag cross-venue : HL suit-il Binance/Bybit ? anticiper via la venue menante.
- T22. Demi-vie de la dérive (R1) par coin : fenêtre exploitable ou dérive déjà partie.
- T23. Lead-lag multi-tape (`lead_lag_multitape`) : fusionner plusieurs flux pour un signal robuste.
- T24. Scoring multiasset (`lead_lag_multiasset_scoring`) : classer les paires menant/suivant par force.
- T25. Lead-lag conditionné au régime (`regime_wiring`) : la relation tient-elle selon la volatilité ?
- T26. Autopsie causale (`lead_lag_causal_autopsy`) : purger toute fuite look-ahead du signal.

**THÈME 3 — EXÉCUTION MAKER & COÛT (levier n°1 : makers gagnent le spread)**
- T27. Brancher `maker_fill`+`maker_rebate_decision` : entrée passive par défaut, taker en repli seulement.
- T28. Quoting inside spread (`quoting_inside_spread`) : ordre-limite à l'intérieur du spread du leader.
- T29. Modèle post-only : proba de remplissage vs marché qui traverse (`missed_fill_model`,`partial_fill_model`).
- T30. Décision maker/taker dynamique : coût taker vs risque de non-remplissage par coin/volatilité.
- T31. Fractionnement d'ordre (`order_split_benefit`) pour réduire l'impact (`execution_sim`).
- T32. Capturer le rebate maker et le mesurer NET (`fee_model`,`couts_verite`).
- T33. Sortie maker : ordre-limite de sortie au lieu de taker quand l'horizon le permet.
- T34. Modèle de file d'attente (`queue_model`,`lead_lag_queue_costs`) : position et coût d'attente.
- T35. Passif-agressif (`execution_passive_agressive`) : passif d'abord, bascule agressive si non rempli après délai.
- T36. Peg dynamique : ordre-limite re-pricé sur le mid (`quoting`) plutôt qu'un prix fixe.
- T37. Impact réel (`audit_liquidity_consumption`) : combien notre taille mange le carnet.
- T38. Moins d'allers-retours : regrouper les signaux d'un même coin en une position (amortir le coût fixe).
- T39. Router vers la venue au spread le plus serré (`native_venues`,`routing`).
- T40. Table de coûts calibrée (`construire_table_edge`,`construire_calibration_edge`) par coin/heure/taille.

**THÈME 4 — LATENCE & VITESSE (adverse selection : ne pas se faire pick off)**
- T41. Lancer le chantier latence (`chantier_latence`) dès données exécutables : net par délai 5/15/30/60/120 s.
- T42. Mesurer la latence réception−bourse par leader et par flux (distribution, pas moyenne).
- T43. Prioriser les leaders observables en WS direct (`collecter_userfills_ws_lane`) vs poll.
- T44. Réaction sous la seconde : supprimer le délai 60 s modélisé quand l'observation est directe.
- T45. Gain d'un flux plus rapide / RTT (`execution_delay_model`).
- T46. Budget de latence par coin : les coins à dérive lente tolèrent plus de délai ⇒ prioriser.
- T47. Pré-calcul : pré-charger carnet+features du coin AVANT le fill pour agir instantanément.
- T48. Mesurer si on est « pick off » par des plus rapides (adverse selection de latence).
- T49. Exécution asynchrone : ne jamais bloquer la décision d'un coin sur un autre.
- T50. Horloge certifiée (`lead_lag_certified_clock`) pour mesurer la latence sans biais.
- T51. Backpressure latence : si le flux retarde, dégrader proprement (lien résilience M).
- T52. Coût marginal de chaque 100 ms en bps (`execution_delay_model`) ⇒ ROI de la vitesse.

**THÈME 5 — SÉLECTION DE LEADERS (anti-survivorship)**
- T53. Sélection causale (`copy_vault_causal_selection`) : décisions dénouées ET postérieures au suivi.
- T54. Corriger la malédiction du vainqueur (`h181_malediction_du_vainqueur`) : pas de sélection sur le passé chanceux.
- T55. Persistance de compétence (`copy_vault_persistence`) : la surperformance se maintient-elle ?
- T56. Walk-forward de sélection (`copy_vault_leader_selection_comparison`) : re-sélectionner par segment.
- T57. Signal de qualité leader (`leader_quality_signal`) : features prédictives de la compétence future.
- T58. Décote de crowding : un leader très copié (grosse TVL) a un alpha dilué ⇒ pénaliser.
- T59. Détecter les leaders toxiques (whale-slap) qui piègent les copieurs ⇒ liste noire.
- T60. Diversité de leaders faiblement corrélés (`portfolio_risk`) : pas 10 leaders au même trade.
- T61. Filtrer sur profit factor / drawdown / longueur d'historique, pas le win rate.
- T62. Stabilité de style : un leader qui change radicalement ⇒ prudence.
- T63. Capacité : notre petite taille (350 USD) copie ce qu'un gros ne peut pas ⇒ exploiter cet avantage.
- T64. Sélection conditionnelle au coin : un leader bon seulement sur certains coins.
- T65. Détecter les leaders informés : ouvertures qui précèdent systématiquement le mouvement (`lead_lag_causal`).
- T66. Fenêtre de confiance : activer un leader après N décisions dénouées mesurées (G7).
- T67. Rotation auto : retirer un leader dont l'edge OOS s'effondre (`survival_gate`,`promotion_gate`).

**THÈME 6 — CONDITIONNEMENT & FEATURES**
- T68. OFI (`microstructure`) : ne copier que si le flux va dans le sens du leader.
- T69. Spread au signal (`mesurer_spread_carnet`) : n'entrer que si le coût est bas.
- T70. Overshoot mark/oracle (`overshoot_signal`) : éviter un débordement qui va se corriger.
- T71. Régime de volatilité (`regime_detection`) : adapter/couper en haute vol.
- T72. Funding comme filtre (`measure_funding_gate`) : éviter un funding qui mange l'edge.
- T73. Heure / session : créneaux plus copiables (features temporelles).
- T74. Profondeur du carnet (`profondeur_spot`) : liquidité suffisante pour entrer+sortir.
- T75. Dispersion cross-venue (`mesurer_dispersion_venues`) : copier quand HL décroche.
- T76. Taille du fill leader comme feature de conviction.
- T77. Consensus multi-leaders : même coin/sens dans la minute ⇒ signal renforcé.
- T78. Momentum récent du coin (`market_signals`) : aligner la copie avec le momentum.
- T79. Valeur d'information de chaque condition (`edge_predictor`) : quantifier l'apport de chaque filtre.
- T80. Recherche du meilleur sous-ensemble de conditions (`scenario_search`, anti-overfit).
- T81. Alpha résiduel (`residual_alpha`) après neutralisation du bêta marché.
- T82. Interactions non linéaires (`ml_extras`) : fill agressif × OFI × régime.

**THÈME 7 — CROWDING & ANTI-EXPLOITATION (leçon du whale-slap)**
- T83. Modèle de crowding : estimer le nombre de copieurs (TVL, réaction du marché au leader).
- T84. Détecter les trades piège : gros fill suivi d'un retournement rapide ⇒ fade, pas copie.
- T85. Ne pas être prévisible : randomiser légèrement timing/taille pour ne pas se faire chasser.
- T86. Mesurer notre propre impact de copie : à quelle taille devient-on détectable/exploitable.
- T87. Éviter les niveaux de liquidation évidents (`liquidation_cascade`).
- T88. Signal inverse en cascade (`fade_liquidation_backtest`) : profiter du débordement, pas le subir.
- T89. Détecter le stop-hunt (mèches qui ramassent les stops) ⇒ pas de stop évident.
- T90. Décote d'alpha post-publication : un vault qui monte en leaderboard attire les copieurs ⇒ edge ↓.
- T91. Contrarian sur crowding extrême : quand tout le monde copie long, prudence.
- T92. Mesurer la dégradation de l'edge avec la popularité du leader (TVL vs edge dans le temps).

**THÈME 8 — STRATÉGIES ALTERNATIVES (diversifier l'avantage)**
- T93. Fade de liquidation (`liquidation_edge_measure`) : entrer contre le débordement.
- T94. Direction post-liquidation (`post_liquidation_direction`) : prédire le rebond après cascade.
- T95. Carry funding (`recherche_carry`,`carry_backtest`) : porter quand le funding paie, direction couverte.
- T96. Carry perp-perp cross-venue (`mesurer_funding_perp_perp`).
- T97. Arbitrage de dislocation 2 jambes (`backtest_dislocation_2jambes`).
- T98. MM autour des positions leaders (`grid_market_maker`,`market_making_flow`) : capter le spread.
- T99. Mean reversion sur overshoot (`mean_reversion`).
- T100. Cointégration de paires (`mesurer_cointegration`) : stat-arb relatif.
- T101. Grid MM adaptatif à la volatilité (`grid_market_maker`).
- T102. Quoting inside spread en continu là où le leader est actif.
- T103. Spot-perp carry (`hl_spot_perp_carry_v1`) : base spot/perp.
- T104. Falsifier carry/cash-and-carry (`falsifier_carry`,`falsifier_cashcat`) avant d'allouer.
- T105. Sniper d'horizon (`sniper_horizon_curve`) : entrer/sortir à l'horizon optimal mesuré.
- T106. Copie + MM combinés : copier la direction ET fournir de la liquidité autour.
- T107. Rotation de stratégies par régime (`regime_models`).
- T108. Portefeuille multi-stratégies sur le front de Pareto (`pareto_front`).

**THÈME 9 — RÉPLICATION PAR POSITION & PORTEFEUILLE**
- T109. Réplication par position (`vault_replication`,`copy_vault_replication_paper`) : copier la cible, pas les fills.
- T110. Réplication 350 USD à l'échelle fidèle du notionnel.
- T111. Portefeuille agrégé (`portefeuille_global`) : répliquer le mix de plusieurs leaders.
- T112. Rééquilibrage paresseux : ne bouger que si l'écart dépasse un seuil (coûts ↓).
- T113. Netting multi-leaders : long d'un + short d'un autre même coin ⇒ nettoyer.
- T114. Taille pondérée par conviction dans le leader (T57).
- T115. Réplication à risque égal entre coins (risk parity), pas notionnel égal.
- T116. Comparer suivi retardé vs immédiat (retard ↓ bruit mais rate la dérive).
- T117. Gérer les positions orphelines : fermer proprement si le leader disparaît.
- T118. Répliquer la trajectoire d'entrée (DCA du leader), pas un point unique.

**THÈME 10 — CAPITAL & RISQUE (350 USD)**
- T119. Kelly fractionné (`risk_sizing`) selon l'edge mesuré et sa variance.
- T120. Ciblage de volatilité (`portfolio_risk`) : risque quotidien homogène.
- T121. Plafond de perte journalier + verrou de profit (`exits_risque`).
- T122. Contrôle de drawdown (`stress_testing`) : réduire la taille en drawdown.
- T123. Levier dynamique ≤ 1 sous le plafond paper.
- T124. Diversification coins/leaders faiblement corrélés (`portfolio_risk`).
- T125. Réserve de marge : jamais liquidé en paper (`liquidation_sizing`).
- T126. Analyse de capacité : à quel capital l'edge s'effondre.
- T127. Sizing conditionnel à la force du signal (dans la limite de risque).
- T128. Sortie sur invalidation du signal, pas sur prix fixe (stop non évident, T89).
- T129. Espérance = débit de décisions × net moyen de TOUTES les décisions (pas que les gagnantes).
- T130. Objectif Sharpe/Sortino quotidiens (`perf_metrics`,`honest_metrics`), pas le PnL brut.

**THÈME 11 — RIGUEUR & VALIDATION (ne jamais se mentir)**
- T131. Portes VALIDATION → OOS → FORWARD (`validation_gates`,`promotion_gate`).
- T132. CV purgée/embargo (`purged_split`,`cross_validation`) : pas de fuite via l'horizon.
- T133. Correction de multiplicité (`anti_overfit_gate`) : tous les essais comptent.
- T134. Bootstrap par blocs + placebo (`monte_carlo`,`copy_vault_scientific_controls`) : inverser le sens ne doit pas gagner.
- T135. Walk-forward strict (`robustesse_selection`).
- T136. Forward paper en direct (`forward_causal`,`forward_portefeuille`) : le juge ultime.
- T137. Robustesse de régime (`robustness_protocol`).
- T138. Minimum d'échantillon avant lecture d'intervalle (`garde_fous_recherche`).
- T139. Anti-look-ahead systématique (`anti_lookahead_pipeline`,`lookahead_guard`).
- T140. Détection du biais récursif (`recursive_bias_probe`,`mesurer_biais_recursif`).
- T141. Contrôle de sélection par overfit (`overfit_selection`) : pénaliser le nombre d'hypothèses.
- T142. Deflated Sharpe : corriger le Sharpe du nombre d'essais.
- T143. Registre d'hypothèses horodaté (`copy_vault_hypothesis_registry`,`codex_hypothesis_ledger`) : figer avant de tester.

**THÈME 12 — COÛTS & FILLS FINS (PnL net = après TOUT)**
- T144. Slippage calibré (`slippage_model`) sur carnet réel par coin/taille.
- T145. Missed fill (`missed_fill_model`) : proba qu'un ordre maker ne remplisse pas.
- T146. Partial fill (`partial_fill_model`) : remplissage partiel et coût résiduel.
- T147. File d'attente (`queue_model`) : position et temps d'attente maker.
- T148. Intrabar (`intrabar`) : reconstruire le chemin de prix pour un fill réaliste.
- T149. Frais exacts (`fee_model`,`couts_verite`) : maker/taker/rebate/paliers de volume.
- T150. Impact non linéaire (`copy_vault_execution_math`) au-delà du spread.
- T151. Vérité du PnL (`pnl_verite`) : net après frais+spread+slippage+funding+impact.
- T152. PnL des refus (`pnl_des_refus`) : valeur de NE PAS copier (le filtre a un rendement).
- T153. Marche dans le carnet exécutable (`audit_executable_book_walk`).
- T154. Risque cross-venue non atomique (`audit_cross_venue_non_atomic`) sur les 2 jambes.
- T155. Parité backtest/live (`backtest_live_parity`) : le backtest colle-t-il au paper réel ?

**THÈME 13 — DONNÉES & COLLECTE (tout alimenter, rien gâcher)**
- T156. Collecter `leader_orders` EN LOCAL aligné avec les fills (R2, A4) — débloque maker + anticipation.
- T157. Garantir référence(−30 s)+entrée(+60 s)+sortie(+horizon) par coin (A2/A3).
- T158. Collecter TOUS les coins HIP-3 tradés (A5 ; 61 % du notionnel).
- T159. Brancher `explorer_tx` : dépôts/retraits = signal de flux de capital.
- T160. Enrichir les fills (`enrichir_fills`) : contexte carnet/régime à chaque fill.
- T161. Microstructure fine (`collecter_lab_microstructure`,`flux_microstructure`).
- T162. Dispersion venues en continu (`collecter_dispersion_venues`).
- T163. Snapshots de carnet plus profonds (plus de niveaux que bids5/asks5) pour l'impact.
- T164. Qualité replay (`qualite_donnees_replay`,`check_dataset_quality`) : aucune donnée trouée.
- T165. Déduplication durable (`dedup_durable`) : pas de double comptage.
- T166. Backfill funding horaire + bougies 1 h (`backfill_funding`,`backfill_candles`) sur long historique.
- T167. Collecte résiliente mémoire (M2) : tampons bornés, écritures atomiques.
- T168. Index partitionné (`partitioned_data_index`) pour un labo rapide et par morceaux.

**THÈME 14 — RÉGIMES & ADAPTATION**
- T169. Détection de régime en ligne (`regime_detection`,`regime_label`) : vol/trend/range/funding.
- T170. Câblage régime→décision (`regime_wiring`) : la bonne stratégie par régime.
- T171. Edge par régime : mesurer la copie séparément par régime.
- T172. Couper la copie en régime hostile (haute vol, cascade).
- T173. Détection de cascade en temps réel (`liquidation_cascade`) ⇒ mode défensif.
- T174. Délai de copie adapté au régime (rapide en range, prudent en vol).
- T175. Taille adaptée au régime (réduire en incertitude).
- T176. Rupture de régime ⇒ re-valider les leaders.
- T177. Vote de modèles de régime (`regime_models`).
- T178. Mémoire de régime : quel régime favorise quelle stratégie.

**THÈME 15 — ML & PRÉDICTION D'EDGE**
- T179. Prédicteur d'edge (`edge_predictor`) : prédire le net AVANT de copier, n'agir que si > seuil.
- T180. Calibration des probabilités (`calibration`) : le prédicteur est-il fiable ?
- T181. Diagnostics ML (`ml_diagnostics`) : importance des features, fuites, stabilité.
- T182. Hyperopt local (`hyperopt_local`) sans surajuster (garde `anti_overfit_gate`).
- T183. Modèle par coin vs global quand il y a assez de données.
- T184. Feature store (`features/`) : features versionnées, sans fuite.
- T185. Labeling triple-barrière (`labeling`) : TP/SL/horizon.
- T186. Sélection robuste de features (`robust_selection`) stables en OOS.
- T187. Drift du modèle (`mlops_tools`) : re-calibrer quand les données dérivent.
- T188. Ensembles de modèles faibles plutôt qu'un seul surajusté.
- T189. Incertitude de la prédiction (intervalle) ⇒ taille proportionnelle à la confiance.
- T190. Backtest du prédicteur en walk-forward (pas d'illusion d'edge ML).

**THÈME 16 — MOTEUR PAPER · AUTONOMIE · PREUVE**
- T191. Moteur paper fidèle (`moteur_execution_prod`,`execution_realiste`) : frais+funding+spread+slippage+latence+drawdown.
- T192. Comptabilité du capital (`audit_capital_accounting`,`ledger_verite`) : chaque USD tracé depuis 350.
- T193. Reconciliation prod (`reconciliation_prod`) : le paper colle-t-il au réel potentiel ?
- T194. Boucle de recherche autonome (`alina_autonomous_lab`,`copy_vault_research_planner`) : proposer→tester→trancher.
- T195. Planificateur priorisé (`copy_vault_research_planner`) : attaquer d'abord ce qui débloque le plus d'edge.
- T196. Auto-advance des hypothèses (`auto_advance_analysis`).
- T197. Tableau de bord économique honnête (`export_economic_family_scoreboards`,`dashboard_truth`) : net par famille.
- T198. Certification économique quotidienne (`run_daily_economic_certification`) : verdict daté, reproductible.
- T199. Audit complet à chaque cycle (`audit_complet`) : données+mesure+économie+chantiers, rien gâché.
- T200. LE VERDICT (`le_verdict`) : « méga PnL positif » = PROVEN en VALIDATION+OOS+FORWARD, après TOUS les coûts
  ET le crowding — sinon ce n'est qu'une hypothèse. Aucun gain inventé, jamais.

### C-octies. CHANTIERS ISSUS DE LA RECHERCHE WEB (12/11) — labo · collecteur · moteur en priorité

Faits sourcés sur le web, traduits en chantiers concrets. Priorité aux trois piliers. Chaque fait reste à
re-vérifier sur la source primaire avant d'y engager du capital (les poids d'API notamment).

**COLLECTEUR — faits d'API Hyperliquid (budget partagé = 1200 poids/min/IP) :**
- `clearinghouseState` (positions, marge, PnL latent d'un compte) = **poids 2** (TRÈS léger) ; `l2Book`=2 ; `allMids`=2.
- `frontendOpenOrders` / `openOrders` (ordres en attente = INTENTION) = **poids 20** ; `userFills` = 20 + 1 par 20 fills ; `userRole`=60.
- `userRateLimit` existe pour surveiller notre propre budget.
- **W-C1 (majeur).** Collecter `clearinghouseState` pour TOUS les leaders en continu : à poids 2, les POSITIONS sont quasi gratuites → débloque la réplication par position (T109) à grande échelle sans saturer le budget.
- **W-C2.** Collecter `frontendOpenOrders` (poids 20) = ordres en attente en local (T156, R2) : budgéter ~60 appels poids-20/min sous 1200 → prioriser les top leaders, cadence adaptative.
- **W-C3.** Brancher `userRateLimit` dans le budget partagé (`collecte_fiable`) pour piloter la cadence en vrai, pas à l'estime.
- **W-C4.** Multi-IP pour dépasser 1200/min (archi WS déjà notée) : répartir positions (léger) et ordres (lourd) sur des IP distinctes.

**LABO — rigueur (Bailey & López de Prado) :**
- **W-L1.** Implémenter la **CPCV** (combinatorial purged cross-validation) : prouvée supérieure au walk-forward pour éviter les fausses découvertes (`purged_split`,`cross_validation` à étendre).
- **W-L2.** **Deflated Sharpe Ratio** : corriger le Sharpe du NOMBRE d'essais + non-normalité ; seuil indicatif DSR < 0,95 = probablement surajusté. Brancher dans `honest_metrics`/`anti_overfit_gate`.
- **W-L3.** **PBO** (probability of backtest overfitting) via CSCV : fraction des chemins où l'optimal in-sample sous-performe la médiane OOS. Exige le registre essai-par-essai (`copy_vault_hypothesis_registry`).
- **W-L4.** Fenêtre glissante **~90 jours** (les régimes crypto changent vite) plutôt que 252 ; **embargo ≥ 2× l'horizon de label** (anti-fuite par l'horizon) dans `purged_split`.
- **W-L5.** Compter TOUS les essais pour la correction de multiplicité — la sonde d'exécutabilité (zéro essai à vide) + le registre horodaté rendent ce compte honnête.

**MOTEUR — exécution (makers gagnent, mais adverse selection) :**
- **W-M1 (majeur).** Modèle de fill **conscient de la file** (« Market Maker's Dilemma ») : l'adverse selection EMPIRE quand la file adverse grossit ET quand notre position dans la file est petite → brancher `queue_model`+`lead_lag_maker_queue_train` dans la décision maker.
- **W-M2.** Mesurer l'adverse selection par le **markout à +1 s** post-fill (hors rebate) comme métrique standard (`honest_metrics`,`microstructure`).
- **W-M3.** Exploiter le privilège Hyperliquid « **les market makers annulent en premier** » : re-pricer/annuler nos ordres maker AVANT d'être pick off (logique de cancel-first dans `quoting`/`execution_passive_agressive`).
- **W-M4.** Post-only avec **repricing+resoumission** : un ordre qui croiserait est annulé/repricé → gérer ce cycle (`quoting_inside_spread`,`missed_fill_model`).
- **W-M5.** Base théorique **Avellaneda–Stoikov** (quoting inventory-aware) pour `grid_market_maker`/`quoting` : écart optimal fonction de l'inventaire et de la volatilité.

**SIGNAL & HORIZON — insight stratégique majeur :**
- **W-S1 (décisif).** **ZONE MORTE D'HORIZON.** L'OFI prédit surtout à l'échelle **sub-seconde→secondes** (décroît très vite) ; notre copie à 30–300 s est TROP LENTE pour la microstructure et trop rapide pour l'effet long. Deux sorties, à tester explicitement : (a) descendre **sub-seconde** par l'anticipation des ordres en attente (T4/T14, W-C2) ; (b) viser l'**horizon 4–12 h** où l'OFI des perps a un impact réel QUAND les déviations initiales sont grandes (capacité d'arbitrage saturée) — rejoint R1 (tester les horizons longs > 300 s).
- **W-S2.** **« Quarter-hour effect »** : prédictibilité périodique des rendements liée au trading algo aux ouvertures de quart d'heure → feature temporelle (T73) à tester.
- **W-S3.** Impact des perps **accru quand la déviation initiale est grande** (arbitrage qui bind) → conditionner la copie sur l'AMPLEUR de la déviation prix/oracle (lien T70/T75).

**PRIORISATION issue de ces faits :** W-C1 (positions quasi gratuites) + W-C2 (ordres = intention) d'abord — ils alimentent tout le reste pour un coût d'API minime. Puis W-S1 (choisir le bon horizon : sub-seconde OU 4–12 h, sortir de la zone morte 30–300 s). Puis W-M1/W-M2 (exécution maker mesurée au markout). Puis W-L1–L5 (ne valider qu'avec CPCV+DSR+PBO, sinon on se ment).

### C-novies. 300 AMÉLIORATIONS CONCRÈTES & PARAMÉTRÉES (12/11) — ancrées sur la recherche web

Complète les 200 tâches (C-septies) et les chantiers web (C-octies). Ici, du détail OPÉRATIONNEL : canaux
WebSocket exacts, limites d'API, formules (Avellaneda-Stoikov), méthodes (triple-barrier, CPCV/DSR/PBO, RL).
20 programmes × 15. À re-vérifier sur source primaire avant capital. Priorité labo · collecteur · moteur.

**P1 — COLLECTEUR : canaux WebSocket Hyperliquid (wss://api.hyperliquid.xyz/ws)**
- I1. `orderUpdates` (user) : cycle de vie AUTORITAIRE des ordres (placed→filled→canceled) = l'INTENTION du leader.
- I2. `userFills` (user) : fills AUTORITAIRES (snapshot puis flux) ; gérer `isSnapshot:true` pour ne pas doubler.
- I3. `activeAssetData` (user, coin) : **levier, maxTradeSzs, availableToTrade** du leader = conviction + capacité.
- I4. `webData2`/`webData3` (user) : état agrégé frontend (vue d'ensemble d'un compte).
- I5. `clearinghouseState`/`allDexsClearinghouseState` (user) : positions + marge (tous les dex).
- I6. `userFundings` (user) : paiements de funding (snapshot + horaire).
- I7. `userNonFundingLedgerUpdates` (user) : dépôts/retraits/transferts/liquidations = flux de capital.
- I8. `userEvents` (channel « user ») : fills/funding/liquidation/nonUserCancel — MAIS non garanti complet → ne PAS s'en servir pour l'état.
- I9. `bbo` (coin) : meilleur bid/ask, émis seulement si le BBO change sur un bloc (léger, précis).
- I10. `l2Book` (coin) : carnet par niveaux ; augmenter la profondeur capturée au-delà de 5 niveaux.
- I11. `trades` (coin) : flux des trades du marché (pour l'OFI).
- I12. `activeAssetCtx` (coin) : mark, oracle, prix veille, volume 24 h, OI, funding.
- I13. `candle` (coin, interval) : OHLCV multi-intervalle.
- I14. `userTwapSliceFills` + `userTwapHistory` : détecter les TWAP des leaders (tranches régulières).
- I15. `notification` + `spotState` + `twapStates` : compléter la vue (spot, TWAP en cours).

**P2 — COLLECTEUR : limites d'API & montée en charge**
- I16. Cap dur : **10 adresses user uniques par IP** (orderUpdates/userFills/clearinghouseState/spotState/activeAssetData) → c'est LE verrou.
- I17. Multi-IP : répartir les leaders par shards d'IP (déjà noté archi WS) pour dépasser 10 leaders.
- I18. 1000 abonnements par connexion, 10 connexions, 30 nouvelles connexions/min → planifier l'ouverture.
- I19. 2000 messages/min et 100 posts en vol → borner le débit entrant et les requêtes.
- I20. REST : budget partagé 1200 poids/min/IP (`clearinghouseState`=2, `l2Book`=2, `allMids`=2, `frontendOpenOrders`=20, `userFills`=20+1/20fills, `userRole`=60).
- I21. Brancher `userRateLimit` pour piloter la cadence au réel (pas à l'estime) dans `collecte_fiable`.
- I22. Positions quasi gratuites (poids 2) : poller `clearinghouseState` pour BEAUCOUP de leaders → réplication par position.
- I23. Reconnexion + ré-abonnement automatique avec reprise au dernier snapshot (gap-free).
- I24. Détection de trou : si un `oid` saute, resynchroniser via REST.
- I25. Écritures atomiques (tmp+rename) pour chaque tape ; jamais de fichier corrompu (lien M2).
- I26. Déduplication par `oid`/`tid` + horodatage canonique (pas de double comptage).
- I27. Heartbeat par connexion + superviseur qui relance une connexion morte.
- I28. Compression des tapes à froid, index partitionné à chaud.
- I29. Horloge certifiée (`lead_lag_certified_clock`) pour dater réception vs bloc.
- I30. Backpressure : sous pression mémoire/débit, réduire le nombre de coins/leaders suivis, jamais crasher.

**P3 — COLLECTEUR : nouvelles données à exploiter**
- I31. Levier du leader (activeAssetData) comme feature de conviction par trade.
- I32. Capacité disponible (availableToTrade) : le leader peut-il encore ajouter → prédire la suite du méta-ordre.
- I33. Flux de capital (ledger) : un gros dépôt avant une série de trades = signal d'intention.
- I34. Détection TWAP (userTwapSliceFills) : anticiper les tranches suivantes.
- I35. Liquidations (WsLiquidation) en direct → mode défensif + signal de fade.
- I36. nonUserCancel : annulations forcées → retrait de liquidité.
- I37. OI/mark/oracle (activeAssetCtx) en continu : overshoot et pression directionnelle.
- I38. Positions cross-dex (allDexs) : vue complète d'un leader multi-marchés.
- I39. Profondeur de carnet accrue (plus de niveaux) pour l'impact et la file.
- I40. Trades du marché (trades) pour calculer l'OFI en temps réel.
- I41. Dépôts Arbitrum on-chain (`collecter_depots_arbitrum`) : smart money entrante.
- I42. Explorer tx (`collecter_explorer_lane`) : mouvements de capital on-chain.
- I43. Dispersion venues (`collecter_dispersion_venues`) pour le signal cross-venue.
- I44. Funding cross-venue (`comparer_funding_venues`) pour le carry.
- I45. Snapshots de file d'attente (position dans la queue) pour l'adverse selection.

**P4 — MOTEUR : exécution maker Avellaneda-Stoikov**
- I46. Prix de réservation r = s − q·γ·σ²·(T−t) : décaler le quote selon l'inventaire.
- I47. Demi-spread optimal δ = (1/γ)·ln(1+γ/κ) + ½·γ·σ²·(T−t).
- I48. Calibrer γ (aversion au risque) sur notre capital 350 USD et le risque toléré.
- I49. Calibrer κ sur l'intensité d'arrivée des ordres (fenêtre glissante du carnet).
- I50. σ = volatilité réalisée récente par coin (bougies/microstructure).
- I51. Skew d'inventaire : quoter plus bas si long, plus haut si short, pour revenir à plat.
- I52. Exploiter « les MM annulent en premier » sur HL : re-pricer avant d'être pick off.
- I53. Suivi de la position dans la file (queue_model) : adverse selection ↑ si file adverse grosse et notre rang petit.
- I54. Markout +1 s post-fill (hors rebate) comme mesure d'adverse selection.
- I55. Boucle post-only : si l'ordre croiserait → annulé/repricé → gérer la resoumission.
- I56. Modèle de probabilité de remplissage (missed_fill_model) selon la distance au mid.
- I57. Extensions crypto d'A-S (Hummingbot) : η de décroissance d'inventaire, spread max.
- I58. Cible d'inventaire q* (pas forcément 0 si on veut suivre la direction du leader).
- I59. Horizon T = horizon de la position copiée.
- I60. Backtester A-S sur nos carnets réels (`grid_market_maker`,`quoting_inside_spread`).

**P5 — MOTEUR : exécution RL & avancée**
- I61. Agent DQN d'exécution (état = carnet+inventaire+temps restant).
- I62. Double-dueling DQN pour stabilité (réf. Nagy et al.).
- I63. Politique à action continue (taille/prix) plutôt que discrète.
- I64. Simulateur de carnet rapide type JAX-LOB pour entraîner à grande échelle.
- I65. Récompense = implementation shortfall négatif (minimiser le coût vs prix d'arrivée).
- I66. Pénalité d'adverse selection dans la récompense (markout défavorable).
- I67. Baselines TWAP/VWAP à battre absolument avant d'adopter le RL.
- I68. Ordonnancement d'ordres enfants (child orders) sur la durée.
- I69. Plafond de taux de participation (ne pas être > X % du volume).
- I70. Impact-aware : pénaliser la consommation du carnet.
- I71. Validation walk-forward du RL (pas d'illusion d'edge).
- I72. Robustesse à la latence (le papier Guo et al. le teste explicitement).
- I73. Politique multi-actifs partagée + spécialisation par coin.
- I74. Comparaison RL vs A-S vs taker simple sur net réel.
- I75. Garde-fou : le RL ne décide QUE l'exécution, pas la direction (séparer alpha et exécution).

**P6 — MOTEUR : modélisation fine fills & coûts**
- I76. Intensité d'arrivée des ordres dans queue_model (processus de Poisson).
- I77. Remplissage partiel (partial_fill_model) et coût du résiduel.
- I78. Probabilité de non-remplissage maker (missed_fill_model) par régime.
- I79. Chemin intra-barre (intrabar) pour un fill réaliste.
- I80. Slippage par taille (slippage_model) calibré sur carnet réel.
- I81. Impact non linéaire (loi en racine carrée) au-delà du spread.
- I82. Paliers de frais par volume (fee_model) : frais taker effectif au volume paper.
- I83. Rebate maker capturé et mesuré net.
- I84. Coût de funding par durée de détention (intégré au PnL).
- I85. Risque cross-venue non atomique (audit_cross_venue_non_atomic) sur 2 jambes.
- I86. TCA : implementation shortfall vs prix d'arrivée du leader.
- I87. Courbes de markout (−5 s … +60 s) pour diagnostiquer entrée/sortie.
- I88. Parité backtest/live (backtest_live_parity) à chaque cycle.
- I89. Table de coûts calibrée par coin/heure/taille (construire_table_edge).
- I90. Vérité du PnL (pnl_verite) : net après frais+spread+slippage+funding+impact.

**P7 — LABO : labeling & features (López de Prado)**
- I91. Triple-barrier : TP / SL / horizon max au lieu d'un rendement à horizon fixe.
- I92. Meta-labeling : modèle primaire = sens, modèle secondaire = agir ou non.
- I93. Poids d'échantillon par concurrence de labels (chevauchement des durées).
- I94. Attribution de rendement par unicité (overlap → poids réduit).
- I95. Décroissance temporelle des poids (récent > ancien).
- I96. Équilibrage de classes dans l'apprentissage.
- I97. Différenciation fractionnaire pour la stationnarité sans tuer la mémoire.
- I98. Importance des features MDI/MDA/SHAP (ml_diagnostics).
- I99. Feature store versionné, sans fuite (`features/`).
- I100. OFI comme feature (microstructure) — prédictif à très court horizon.
- I101. Microprice (pondéré par la taille) plutôt que le mid.
- I102. Pente du carnet (book slope) et déséquilibre de profondeur.
- I103. Déviation VWAP-mid (dominante dans la recherche SHAP).
- I104. Pipeline anti-fuite (anti_lookahead_pipeline) sur toutes les features.
- I105. Interactions non linéaires : fill agressif × OFI × régime.

**P8 — LABO : validation rigoureuse (anti-overfit)**
- I106. CPCV (combinatorial purged CV) : prouvée > walk-forward pour les fausses découvertes.
- I107. Purged K-fold + embargo ≥ 2× l'horizon de label (anti-fuite par l'horizon).
- I108. Deflated Sharpe Ratio : corriger du nombre d'essais + non-normalité (seuil ~0,95).
- I109. PBO via CSCV : fraction des chemins où l'optimal IS sous-performe la médiane OOS.
- I110. Fenêtre glissante ~90 jours (régimes crypto rapides) plutôt que 252.
- I111. Bootstrap par blocs sur les jours (dépendance temporelle).
- I112. Placebo par permutation : inverser le sens ne doit PAS gagner.
- I113. Correction de multiplicité : compter TOUS les essais (registre horodaté).
- I114. Minimum d'échantillon AVANT de lire l'intervalle (garde_fous_recherche).
- I115. Porte FORWARD paper en direct (forward_causal) : juge ultime.
- I116. Robustesse de régime (robustness_protocol) : plusieurs conditions.
- I117. Métriques ajustées à la capacité (l'edge survit-il à la taille ?).
- I118. Deflated metrics dans honest_metrics (pas de Sharpe brut).
- I119. Reçus reproductibles (SHA moteur+config+données).
- I120. Détection du biais récursif (recursive_bias_probe).

**P9 — LABO : signal & horizon (sortir de la zone morte)**
- I121. Tester explicitement sub-seconde (anticipation ordres) ET 4–12 h (OFI perp quand déviation grande).
- I122. Mesurer la demi-vie de la dérive post-fill par coin.
- I123. Conditionner sur l'AMPLEUR de la déviation prix/oracle (impact perp ↑ quand arbitrage bind).
- I124. « Quarter-hour effect » : feature temporelle de prédictibilité périodique.
- I125. Timing du cycle de funding (horaire) comme feature.
- I126. Edge mesuré séparément par régime.
- I127. Consensus multi-leaders (même coin/sens/minute).
- I128. Score de nouveauté (coin peu tradé = moins crowdé).
- I129. Valeur d'information par condition (edge_predictor).
- I130. Recherche du meilleur sous-ensemble de conditions (scenario_search, anti-overfit).
- I131. Alpha résiduel après neutralisation du bêta marché (residual_alpha).
- I132. Lead-lag par coin (quels coins mènent) (lead_lag_multiasset).
- I133. Signal « première tranche » d'un cluster (cluster_metaorders).
- I134. Détection iceberg/TWAP comme signal d'un gros méta-ordre.
- I135. Filtre d'agressivité (taker leader = info ; passif = bruit).

**P10 — SÉLECTION DE LEADERS (anti-survivorship)**
- I136. Sélection causale (copy_vault_causal_selection) : décisions dénouées ET postérieures.
- I137. Correction de la malédiction du vainqueur (h181).
- I138. Persistance de compétence (copy_vault_persistence).
- I139. Re-sélection walk-forward par segment.
- I140. Modèle de qualité leader (leader_quality_signal).
- I141. Décote de crowding par TVL.
- I142. Liste noire des leaders toxiques (whale-slap).
- I143. Conviction via levier (activeAssetData) comme feature de qualité.
- I144. Filtres profit factor / drawdown / longueur d'historique (pas le win rate).
- I145. Stabilité de style (détecter un changement brusque).
- I146. Sélection conditionnelle au coin (bon seulement sur certains coins).
- I147. Détection des leaders informés (ouvertures précédant le mouvement).
- I148. Fenêtre de confiance : activer après N décisions dénouées.
- I149. Rotation automatique (survival_gate/promotion_gate) si edge OOS s'effondre.
- I150. Diversification : leaders faiblement corrélés (portfolio_risk).

**P11 — CROWDING & ANTI-EXPLOITATION**
- I151. Modèle de crowding (nombre de copieurs estimé via TVL + réaction marché).
- I152. Détection des trades piège (gros fill suivi d'un retournement).
- I153. Non-prévisibilité : randomiser légèrement timing/taille.
- I154. Mesure de notre propre impact de copie (seuil de détectabilité).
- I155. Éviter les niveaux de liquidation évidents.
- I156. Fade des cascades (fade_liquidation_backtest).
- I157. Détection du stop-hunt (mèches qui ramassent les stops).
- I158. Décote d'alpha post-publication (vault qui monte en leaderboard).
- I159. Contrarian sur crowding extrême.
- I160. Monitoring TVL-vs-edge dans le temps.
- I161. Estimer et exploiter le délai des copieurs (front-run des copieurs lents).
- I162. Détecter si NOUS sommes front-run (adverse selection sur nos ordres).
- I163. Conscience des ordres cachés (RPI : affichés UI, cachés API).
- I164. Plafond de capacité (taille au-delà de laquelle l'edge s'effondre).
- I165. Éviter de suivre un leader en cours de liquidation.

**P12 — STRATÉGIES ALTERNATIVES**
- I166. Fade de liquidation (liquidation_edge_measure).
- I167. Direction post-liquidation (post_liquidation_direction).
- I168. Carry de funding (recherche_carry).
- I169. Carry perp-perp cross-venue (mesurer_funding_perp_perp).
- I170. Base spot-perp (hl_spot_perp_carry_v1).
- I171. Dislocation 2 jambes (backtest_dislocation_2jambes).
- I172. Grid MM adaptatif à la volatilité (grid_market_maker).
- I173. Mean reversion sur overshoot (mean_reversion).
- I174. Cointégration de paires (mesurer_cointegration).
- I175. Market-making A-S inventory-aware.
- I176. Copie + MM combinés (direction + liquidité).
- I177. Rotation de stratégies par régime (regime_models).
- I178. Allocation multi-stratégies sur le front de Pareto (pareto_front).
- I179. Provision de liquidité type HLP (capter les liquidations).
- I180. Falsifier chaque stratégie (falsifier_carry/cashcat) avant capital.

**P13 — RÉPLICATION & PORTEFEUILLE**
- I181. Réplication par position (vault_replication) plutôt que par fills.
- I182. Mise à l'échelle fidèle à 350 USD (copy_vault_replication_paper).
- I183. Portefeuille agrégé multi-leaders (portefeuille_global).
- I184. Rééquilibrage paresseux (seuil d'écart) pour réduire les coûts.
- I185. Netting multi-leaders (long+short même coin).
- I186. Taille pondérée par conviction (levier du leader).
- I187. Risk parity entre coins (pas notionnel égal).
- I188. Suivi retardé vs immédiat (comparer bruit vs dérive).
- I189. Gestion des positions orphelines (leader disparu).
- I190. Réplication de la trajectoire d'entrée (DCA du leader).
- I191. Miroir de levier (dans la limite paper ≤ 1).
- I192. Plafonds d'exposition brute/nette.
- I193. Réplication consciente de la corrélation (éviter la concentration).
- I194. Minimisation du turnover (coûts).
- I195. Agrégation cross-dex des positions.

**P14 — CAPITAL & RISQUE (350 USD)**
- I196. Kelly fractionné (risk_sizing) selon edge+variance.
- I197. Ciblage de volatilité (portfolio_risk).
- I198. Plafond de perte journalier + verrou de profit (exits_risque).
- I199. Contrôle de drawdown (stress_testing).
- I200. Levier dynamique ≤ 1.
- I201. Diversification corrélation.
- I202. Réserve de marge : jamais liquidé (liquidation_sizing).
- I203. Analyse de capacité (impact à la taille).
- I204. Sizing conditionné à la force du signal.
- I205. Sorties sur invalidation du signal (stop non évident).
- I206. Espérance = débit × net moyen de TOUTES les décisions.
- I207. Objectif Sharpe/Sortino quotidiens (perf_metrics).
- I208. Risque de queue (CVaR) borné.
- I209. Limites de position par coin.
- I210. Tests de stress par scénario (stress_testing).

**P15 — RÉGIMES & ADAPTATION**
- I211. Détection de régime en ligne (regime_detection).
- I212. Régimes HMM (regime_models) + vote.
- I213. États vol/trend/range/funding (regime_label).
- I214. Câblage régime→stratégie (regime_wiring).
- I215. Edge par régime.
- I216. Couper la copie en régime hostile.
- I217. Détection de cascade en temps réel (liquidation_cascade).
- I218. Délai de copie adapté au régime.
- I219. Taille adaptée au régime.
- I220. Rupture de régime → re-valider les leaders.
- I221. Régime de funding (carry on/off).
- I222. Régime de liquidité (profondeur du carnet).
- I223. Régime de dislocation cross-venue.
- I224. Mémoire de régime (quelle stratégie a marché quand).
- I225. Transition de régime comme signal (sortie/entrée).

**P16 — ML & PRÉDICTION D'EDGE**
- I226. Prédicteur d'edge (edge_predictor) : n'agir que si net prédit > seuil.
- I227. Calibration des probabilités (fiabilité) (calibration).
- I228. Diagnostics ML (fuites, stabilité, importance).
- I229. Hyperopt local sans surajuster (anti_overfit_gate).
- I230. Modèle par coin vs global.
- I231. Feature store sans fuite.
- I232. Labeling triple-barrière pour l'apprentissage.
- I233. Sélection robuste de features (stables OOS).
- I234. Détection de drift du modèle (mlops_tools).
- I235. Ensembles de modèles faibles.
- I236. Incertitude de prédiction → taille proportionnelle.
- I237. Backtest walk-forward du prédicteur.
- I238. Apprentissage en ligne (adaptation continue).
- I239. Meta-labeling act/no-act au-dessus du signal de copie.
- I240. Baseline gradient-boosting avant tout modèle complexe.

**P17 — MOTEUR PAPER & FIDÉLITÉ DE SIMULATION**
- I241. Moteur paper fidèle (moteur_execution_prod) : frais+funding+spread+slippage+latence+drawdown.
- I242. Comptabilité du capital depuis 350 (audit_capital_accounting, ledger_verite).
- I243. Reconciliation prod (reconciliation_prod).
- I244. Parité backtest/live (backtest_live_parity).
- I245. Modèle de frais canonique (fee_model).
- I246. Accrual de funding horaire.
- I247. PnL au mark-price.
- I248. Simulation de liquidation (ne jamais être liquidé).
- I249. Simulation de remplissage partiel.
- I250. Simulation du cycle de vie des ordres.
- I251. Injection de latence réaliste.
- I252. Injection de slippage réaliste.
- I253. Replay déterministe (même entrée → même sortie).
- I254. Reçus horodatés par run.
- I255. Pin SHA (moteur/config) pour reproductibilité.

**P18 — AUTONOMIE & BOUCLE DE RECHERCHE**
- I256. Boucle autonome (alina_autonomous_lab) : proposer→tester→trancher.
- I257. Planificateur priorisé (copy_vault_research_planner) : d'abord ce qui débloque le plus d'edge.
- I258. Auto-advance des hypothèses (auto_advance_analysis).
- I259. Registre d'hypothèses horodaté (copy_vault_hypothesis_registry).
- I260. Scoreboards économiques (export_economic_family_scoreboards).
- I261. Certification économique quotidienne (run_daily_economic_certification).
- I262. Audit complet à chaque cycle (audit_complet).
- I263. Jauge d'exécutabilité (etat_executabilite).
- I264. Feedback coins-à-collecter (generer_coins_lanes).
- I265. Auto-pacing (ne pas tourner à vide).
- I266. Ordonnancement conscient des ressources (resource_policy).
- I267. Watchdog de campagne (campaign_watchdog).
- I268. Campagnes reprenables (resumable_campaign).
- I269. Gouverneur de mémoire (M0) qui pilote l'ampleur.
- I270. Dégradation progressive (jamais de crash).

**P19 — OBSERVABILITÉ & PREUVE ÉCONOMIQUE**
- I271. Dashboard économique honnête (dashboard_truth).
- I272. Net par famille de stratégie.
- I273. pnl_verite (après tous les coûts).
- I274. pnl_des_refus (valeur de NE PAS copier).
- I275. Dashboards de markout.
- I276. Carte d'exécutabilité par coin.
- I277. Audit des données (rien de gâché).
- I278. Motifs de refus (pourquoi un trade n'est pas exécutable).
- I279. Décomposition des coûts.
- I280. Sharpe/Sortino quotidiens.
- I281. Courbes de capacité.
- I282. Moniteur de crowding.
- I283. Chronologie des régimes.
- I284. Le Verdict (le_verdict) : PROVEN seulement après VALIDATION+OOS+FORWARD, tous coûts + crowding.
- I285. Reproductibilité totale (reçus + SHA).

**P20 — RÉSILIENCE, INFRA & PERFORMANCE**
- I286. Gouverneur de mémoire VERT/ORANGE/ROUGE (psutil).
- I287. Labo par morceaux (shard/jour/coin), libérer chaque lot.
- I288. Cache de carnets LRU borné (pas illimité).
- I289. Spill-to-disk pour les tables intermédiaires.
- I290. Écritures atomiques partout.
- I291. Checkpoint + reprise (travail jamais perdu).
- I292. Capture de MemoryError (jamais d'exception mémoire non gérée).
- I293. Preflight d'estimation mémoire (réduire l'ampleur si insuffisant).
- I294. Index partitionné (partitioned_data_index) pour un labo rapide.
- I295. Replay rapide (replay_profiler) et vectorisation (vectorized).
- I296. Sûreté en parallèle (pas de corruption inter-process).
- I297. Hygiène CRLF/encodage/PYTHONUTF8 (pièges Windows).
- I298. Test sous RAM basse (preuve que ça termine en mode dégradé).
- I299. Conscience du reaper (reprendre proprement si le système coupe).
- I300. Tampons bornés côté collecteurs (jamais de croissance illimitée).

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

### C-undecies. 200 NOUVEAUX GISEMENTS D'EDGE (GIS1–GIS200) — issus de ~20 recherches web approfondies (12/11)

Chaque idée est ancrée sur un FAIT sourcé (à re-vérifier en source primaire avant capital) et un module réel.
Angles entièrement nouveaux par rapport aux sections C-septies (200 T) et C-novies (300 I).

**TA — CROSS-VENUE : Binance mène Hyperliquid (fait : ~700 ms, 29/29 actifs, Hayashi-Yoshida ; = 2 blocs HyperBFT)**
- GIS1. Collecter le flux Binance (perp BTC/ETH/SOL/HYPE…) comme SIGNAL AVANCÉ de HL : 700 ms d'avance, soit >> notre horizon.
- GIS2. Estimer notre propre décalage par coin avec l'estimateur Hayashi-Yoshida (séries asynchrones), pas une corrélation naïve.
- GIS3. Balayer le décalage de −2000 ms à +2000 ms par pas de 100 ms et prendre l'argmax de corrélation (méthode sourcée).
- GIS4. Séparer trades acheteur-initié / vendeur-initié dans l'estimation (filtre le bruit de bid-ask).
- GIS5. Éliminer d'abord TOUT artefact d'horodatage (dérive d'horloge, données périmées, alignement de barres) — un faux lead de 700 ms est trivial à fabriquer.
- GIS6. Tester Lighter comme second meneur (fait : mène HL sur 27/29 ; Binance mène Lighter de ~100 ms).
- GIS7. Exploiter l'asymétrie : HL contient AUSSI de l'information propre (corr 0,22 HL→Binance) via flux à levier, liquidations, sentiment crypto-natif → ne pas traiter HL comme pur suiveur.
- GIS8. Signal « HL décroche » : base perp-spot HL (fait : escompte ~3,8 bps) comme mesure de pression locale.
- GIS9. Prédire le FUNDING de HL depuis Binance (fait : causalité Granger CEX→DEX, 7/9 symboles, ZÉRO causalité inverse).
- GIS10. Intégration CEX 61 % plus forte que DEX → les écarts CEX-DEX persistent : les cartographier par coin.
- GIS11. Conditionner la copie : ne copier un leader que si le meneur (Binance) confirme la direction dans la fenêtre.
- GIS12. Détecter les fills de leader qui ne sont QUE de la réaction au meneur (zéro information propre) → ne pas les copier.
- GIS13. Mesurer le décalage par RÉGIME (calme vs stress) : les 700 ms ne sont pas constants.

**TB — OPTIONS DERIBIT : GEX / skew comme détecteur de régime (BTC/ETH, nos plus gros coins)**
- GIS14. Calculer le GEX agrégé (gamma de tout l'open interest) : combien les dealers doivent acheter/vendre par mouvement de 1 $.
- GIS15. Régime GEX POSITIF : dealers longs gamma → achètent les baisses, vendent les hausses → MEAN-REVERSION + pin sur les strikes à gros OI.
- GIS16. Régime GEX NÉGATIF : dealers courts gamma → vendent les baisses, achètent les hausses → TENDANCE + expansion de volatilité.
- GIS17. Niveau de « gamma flip » (GEX = 0) : au-dessus = régime de retour à la moyenne, en dessous = régime de tendance.
- GIS18. « Murs de gamma » (strikes à gamma max) : aimants/résistances en GEX positif, zones d'expansion une fois franchis.
- GIS19. Pente du gamma autour du spot : pente raide = flux de couverture très sensible aux petits mouvements.
- GIS20. Skew RR25 (IV 25Δ calls − 25Δ puts) : négatif = puts chers (couverture baissière), positif = calls chers (FOMO).
- GIS21. Combinaison GEX+ & RR25+ = configuration de squeeze haussier ; GEX− & RR25− = configuration de chute rapide.
- GIS22. Flux de « charm » : à l'approche de l'expiry (vendredi 08:00 UTC Deribit), les dealers dénouent → pin sur le strike à plus gros OI.
- GIS23. Effet « vanna » : quand l'IV s'effondre post-événement, les dealers achètent du spot → dérive haussière mécanique.
- GIS24. Renversement de rendement autour des expirations quotidiennes (fait : concentré quand l'OI ATM est élevé ET le GEX négatif).
- GIS25. Utiliser DVOL (IV 30 jours constante) comme indicateur de régime de volatilité, et la prime de risque de variance (VRP).
- GIS26. GARDE-FOU : le GEX est un détecteur de RÉGIME et un prédicteur de FLUX de couverture, jamais une cible de prix ; recalibrer pour Deribit (CLOB, pas de dealer unique).

**TC — TOXICITÉ DU FLUX & IMPACT (faits : « le classifieur EST la métrique » ; loi en racine carrée)**
- GIS27. VPIN en TICK-RULE ou vrais signes d'agresseur (HL les publie), JAMAIS en BVC (fait : BVC garde +0,12 de signal de toxicité, corrèle +0,73 à la volatilité = proxy de vol déguisé).
- GIS28. VPIN vrais signes = +0,99 de corrélation à la toxicité réelle ; tick-rule +0,83 → notre flux HL signé nous donne le quasi-plafond.
- GIS29. Bucketing à volume égal (pas temporel), trades coupés aux frontières de bucket, fenêtre glissante de 50 buckets.
- GIS30. Kyle's λ (impact prix par unité de flux, fenêtre 30 min) : +0,67 de signal avec presque zéro charge de volatilité = mesure VRAIMENT différente de la variance.
- GIS31. Corriger le biais à la hausse du λ trade-par-trade (rebond bid-ask) : préférer les régressions par intervalle agrégé.
- GIS32. Exiger la significativité de λ (≥30 fenêtres, |t|≥2) + intervalle par bootstrap par blocs, sinon ne pas l'utiliser.
- GIS33. Ratio d'illiquidité d'Amihud (réponse du prix au volume) comme troisième mesure de liquidité.
- GIS34. Spread réalisé : ce que le fournisseur de liquidité garde après que l'information a atteint le prix ; NÉGATIF = flux informé (même constat que VPIN, mesuré autrement).
- GIS35. Détecteur de toxicité façon « TailScore » : gradient boosting sur signaux carnet+flux à la seconde, SANS volatilité contemporaine (fait : perte évitée statistiquement ≠ 0, répliqué BTC/ETH).
- GIS36. Protocole strict : prédicteurs construits uniquement avec l'information de la seconde PRÉCÉDENTE, walk-forward.
- GIS37. Loi en RACINE CARRÉE de l'impact des méta-ordres : I(Q) ∝ √Q → modéliser NOTRE impact ainsi (pas linéaire).
- GIS38. Impact permanent ≈ 2/3 de l'impact de pointe (fait sourcé) → la relaxation n'est que partielle.
- GIS39. Mémoire longue des signes de trades (Lillo-Mike-Farmer) : le fractionnement d'ordres crée une autocorrélation en loi de puissance → DÉTECTER les méta-ordres des leaders par persistance de signe.

**TD — HAWKES & PROCESSUS PONCTUELS (auto/cross-excitation du carnet)**
- GIS40. Intensité λ(t) = μ + Σ α·e^(−β(t−tk)) : ajuster μ, α, β par maximum de vraisemblance sur fenêtre glissante.
- GIS41. Prédire le TIMING du prochain événement de carnet (tirage exponentiel de moyenne 1/λ) → savoir QUAND agir.
- GIS42. Hawkes MULTIVARIÉ (MHP) : self + cross-excitation entre types d'événements (market orders, limites, annulations, jumps de prix).
- GIS43. Pipeline MHP + COE (continuous output error) : prédit timing ET signe du prochain rendement (fait : surpasse le Hawkes pur en précision et en profit simulé).
- GIS44. Les 4 noyaux du modèle de prix : auto-excitation des trades, retour à la moyenne des prix, impact des trades sur le prix, rétroaction du prix sur l'activité.
- GIS45. L'auto-excitation capture naturellement le FRACTIONNEMENT d'ordres → détecteur d'iceberg/TWAP de leader.
- GIS46. La cross-excitation capture la RÉSILIENCE (reconstitution de liquidité après un gros trade) → savoir quand le carnet se referme.
- GIS47. Noyaux en loi de puissance (plutôt qu'exponentiels) reproduisent mieux l'intensité des jumps (mémoire longue).
- GIS48. Estimer le profil d'impact ENTIER d'un méta-ordre depuis des données anonymes via les intensités conditionnelles empiriques.
- GIS49. Réentraîner le Hawkes chaque seconde en fenêtre glissante (coût de calcul à mesurer — viabilité HF à vérifier).
- GIS50. Utiliser l'intensité de Hawkes sur les JUMPS détectés comme régresseur de volatilité (gain mesuré faible : −1,16 % log MSE — honnête).
- GIS51. GARDE-FOU : la variance récente toutes-observations (dernière heure, EWMA) capture −12/−13 % de MSE, soit ~10× le gain de l'intensité → mettre la variance récente dans le benchmark AVANT d'ajouter Hawkes.

**TE — APPRENTISSAGE PROFOND SUR CARNET (et sa leçon économique décisive)**
- GIS52. LA LEÇON (fait mesuré) : un DeepLOB atteint ~60 % de hit rate, brut +3850 bps, MAIS spread −8091 bps → NET −4242 bps. La prédictibilité sub-minute est RÉELLE mais meurt au spread.
- GIS53. Conclusion directe : profiter exige d'être FOURNISSEUR DE LIQUIDITÉ (gagner le spread) ou d'avoir un vrai avantage de latence/file — pas « un bon classifieur ». → confirme notre chantier maker comme seul débouché.
- GIS54. N'utiliser un signal appris QUE pour décider où POSER un ordre maker, jamais pour traverser le spread.
- GIS55. Architecture DeepLOB (CNN multi-échelle + LSTM) sur fenêtres de 100 événements × 40 features de carnet.
- GIS56. Tester aussi un transformer compact (fait : meilleur à l'horizon le plus court ; fenêtres courtes favorisent l'attention).
- GIS57. Métrique = MACRO-F1, jamais l'accuracy (fait : la classe « stationnaire » domine ; 70 % d'accuracy avec F1 up/down ≈ 0 est un piège).
- GIS58. Horizon « sweet spot » mesuré autour de h=5 événements (h=1 dominé par le stationnaire, h=10 brouillé par la reconstitution et le retour à la moyenne).
- GIS59. Extraire des features UNIVERSELLES qui transfèrent à des instruments non vus (propriété démontrée) → entraîner multi-coins.
- GIS60. Étiquetage à 3 classes (hausse/stationnaire/baisse) avec seuil, + poids de classe dans la perte.
- GIS61. Stride ≥ taille de fenêtre pour réduire la dépendance sérielle entre échantillons.
- GIS62. Split respectant les jours (train j1-7 / val j8 / test j9-10), jamais de split i.i.d.
- GIS63. Les embeddings gelés de l'encodeur portent aussi de l'information de RISQUE (fait : RMSE de volatilité réalisée réduite ~19 %) → réutiliser l'encodeur pour prévoir la volatilité.

**TF — HIP-3 : LE GISEMENT LE PLUS SOUS-EXPLOITÉ (perps déployés par des builders)**
- GIS64. Fait massif : HIP-3 = ~30 % de l'open interest de Hyperliquid, 119 marchés, actions/commodités/pré-IPO (CL pétrole, TSLA, SpaceX, XYZ100).
- GIS65. **EFFET WEEK-END (le plus exploitable)** : quand le CME ferme (vendredi 22:00 UTC), HIP-3 devient le SEUL lieu de découverte de prix.
- GIS66. Conséquence mesurée : part du retail 12 % → 28 %, les bots stat-arb DISPARAISSENT (plus de référence cross-venue), part des MM 12 % → 18 %.
- GIS67. Donc : adverse selection RÉDUITE le week-end → conditions idéales pour faire du maker / fournir de la liquidité.
- GIS68. Fenêtre exacte à exploiter : 1-2 h après la fermeture CME le vendredi ; retour à la normale dimanche 23:00 UTC.
- GIS69. Funding EXTRÊME sur HIP-3 (fait : jusqu'à ~8700 % APY annualisé sur certains contrats actions) → gisement de carry, direction couverte.
- GIS70. Crowding des shorts sur certaines commodités → funding très négatif → carry inverse.
- GIS71. Illiquidité localisée → slippage élevé à l'entrée/sortie : dimensionner petit (notre 350 USD est un AVANTAGE ici).
- GIS72. Oracle fixé par le DÉPLOYEUR via `setOracle` → surveiller les mises à jour d'oracle comme source de dislocation mark/oracle.
- GIS73. Le déployeur peut `haltTrading` (annule tous les ordres, règle au mark) → risque opérationnel à modéliser, ne jamais être surexposé.
- GIS74. Concentration : TradeXYZ = >95 % du volume/OI HIP-3 → un seul point de défaillance à surveiller.
- GIS75. Les MM HIP-3 placent ~19 ordres par fill (requotation intense) → mesurer si on peut tenir ce rythme, sinon viser des coins moins requotés.
- GIS76. Convergence retardée avec le sous-jacent traditionnel (roll CME → perp on-chain) → inefficience structurelle à mesurer.

**TG — PRÉVISION DE VOLATILITÉ (HAR-RV, semivariance, jumps)**
- GIS77. Modèle HAR-RV : régresser la volatilité réalisée future sur ses composantes journalière/hebdomadaire/mensuelle (mémoire longue).
- GIS78. HAR-J (composante de jumps) : meilleur à l'horizon 1 jour (fait).
- GIS79. HAR-RS (semivariance de baisse) : meilleur aux horizons hebdo/mensuel (risque de baisse persistant).
- GIS80. Le workhorse : variance réalisée de la DERNIÈRE HEURE + EWMA (fait : −12/−13 % de MSE, l'essentiel du gain) → l'implémenter en premier.
- GIS81. RV calculée sur rendements 5 minutes (standard sourcé) depuis nos bougies/trades.
- GIS82. Tests de jumps : BNS (Barndorff-Nielsen–Shephard) pour les jours de jump, Lee-Mykland pour l'intraday.
- GIS83. Décomposer RV en continu vs discontinu (jumps) et en semivariances positive/négative signées.
- GIS84. Fait exploitable : effet de RALLYE POST-KRACH — après de fortes baisses, la probabilité de jumps POSITIFS dépasse celle des négatifs.
- GIS85. Intensité de jumps qui monte fortement AVANT les épisodes de stress majeurs → signal défensif précoce.
- GIS86. HAR surpasse GARCH(1,1) aux horizons courts ; GARCH reprend l'avantage aux horizons longs → utiliser chacun à sa place.
- GIS87. Alimenter σ du modèle Avellaneda-Stoikov avec la prévision HAR (et non la vol historique brute).
- GIS88. Alimenter le dimensionnement ciblé-volatilité et les portes de régime avec la même prévision (cohérence σ unique).

**TH — ALLOCATION HRP (robustesse hors échantillon)**
- GIS89. HRP (López de Prado) : clustering hiérarchique de la corrélation → quasi-diagonalisation → bisection récursive.
- GIS90. Avantage décisif : pas besoin d'inverser la matrice de covariance (fonctionne même singulière) → évite la « malédiction de Markowitz ».
- GIS91. Variance hors échantillon plus faible que la min-variance ET que la parité de risque classique (Monte Carlo sourcé).
- GIS92. Sur crypto : HRP navigue mieux la volatilité et le risque de queue que inverse-vol / min-variance / max-diversification.
- GIS93. HRP évite les deux travers : min-variance trop concentrée, inverse-vol trop statique.
- GIS94. HRP ADAPTATIF (basé matrice de distance) : surpasse les autres variantes car les ruptures structurelles de corrélation crypto sont FRÉQUENTES.
- GIS95. Appliquer HRP aux LEADERS (traités comme actifs) pour répartir le risque entre clusters de leaders corrélés.
- GIS96. Appliquer HRP aux COINS et aux STRATÉGIES (copie/carry/liquidation/MM) à trois niveaux emboîtés.
- GIS97. Suivre visuellement le dendrogramme dans le temps : un changement de clustering = signal de rupture de régime.
- GIS98. Métrique de distance alternative (pas seulement √(0,5(1−ρ))) : tester son effet sur la stabilité.
- GIS99. GARDE-FOU HONNÊTE : HRP et min-variance restent sensibles à l'instabilité de la covariance (tendance à surpondérer les actifs les plus instables) → borner les poids.
- GIS100. GARDE-FOU 2 : sur certaines fenêtres, TOUTES les techniques d'allocation ont sous-performé le simple buy-and-hold BTC (0/25 combinaisons de paramètres au-dessus du benchmark) → HRP améliore le RISQUE, pas forcément le rendement. Ne pas vendre HRP comme une source d'alpha.

**TI — LIQUIDATIONS & OPEN INTEREST (aimants de prix)**
- GIS101. Construire NOTRE carte de liquidations : OI par coin + niveau de prix où l'OI a bondi + paliers de levier usuels (5x/10x/20x) + signe du funding.
- GIS102. Formule du prix de liquidation : entrée × (1 − 1/levier + marge de maintenance) pour les longs ; (1 + 1/levier − mm) pour les shorts.
- GIS103. Contrainte de cohérence : l'OI ne peut pas varier de plus que le volume échangé sur la période → écrêter les variations aberrantes.
- GIS104. Zone « aimant » = plage de ~1 % avec l'exposition de liquidation estimée la plus forte.
- GIS105. Mécanique de cascade : le prix atteint un cluster → fermetures forcées (ordres marché opposés) → consomment la liquidité → poussent plus loin → cluster suivant.
- GIS106. Après épuisement du cluster, le prix se RETOURNE souvent → fenêtre de fade (lien avec `fade_liquidation_backtest`).
- GIS107. Clusters des deux côtés = environnement volatil (cascade possible dans les deux sens) → réduire la taille.
- GIS108. Zones VIDES de liquidations : le prix les traverse vite (pas de flux forcé) → ne pas y placer d'ordres d'attente.
- GIS109. Divergence OI/prix (le signal le plus actionnable) : prix en nouveaux sommets + OI en baisse = rallye sans conviction à levier → pullback probable.
- GIS110. Prix en baisse + OI en forte baisse = capitulation des longs → souvent la FIN de la vente.
- GIS111. Hausse de l'OI avec hausse du prix = argent neuf côté long ; hausse de l'OI avec baisse du prix = argent neuf côté short.
- GIS112. Nos liquidations RÉELLES (flux WS `WsLiquidation`) servent à CALIBRER le modèle de clusters estimés (on a la vérité terrain, pas seulement l'estimation).
- GIS113. GARDE-FOU : les heatmaps sont des ESTIMATIONS (les bourses ne publient pas les prix de liquidation individuels) → lire « cette zone a probablement plus d'exposition que ses voisines », jamais « ce prix exact liquide ce montant exact ».

**TJ — SMART MONEY & SÉLECTION DE LEADERS (critères sourcés)**
- GIS114. Critères de « smart money » : win rate élevé + profits réalisés substantiels + performance À TRAVERS LES CYCLES (pas une fenêtre).
- GIS115. Indicateurs de compétence : diversité des actifs tradés, timing stratégique, gestion du risque.
- GIS116. Indicateurs avancés : prise de position précoce, anticipation de tendance.
- GIS117. Méthode rigoureuse (backtest de performance) : calculer le PnL de chaque wallet, filtrer win rate + gains, puis VÉRIFIER que ce n'est pas de la chance (nombre minimum de trades + consistance dans le temps).
- GIS118. Seuils indicatifs sourcés pour le copytrading : ROI réalisé > 50 %, win rate > 0,6, nombre de trades suffisant.
- GIS119. Multi-fenêtres (30 j / 90 j / 180 j / 2 ans) : exiger la présence dans PLUSIEURS fenêtres, pas seulement 30 jours (anti-chance).
- GIS120. Netflow de capital des leaders (entrées/sorties nettes) comme signal d'accumulation/distribution.
- GIS121. Piège SYBIL : une entité peut contrôler des milliers de wallets → dédupliquer les entités avant de compter les « leaders indépendants ».
- GIS122. Piège WASH TRADING : le volume peut être fabriqué entre wallets contrôlés → exiger des motifs d'échange organiques.
- GIS123. Piège « early buyer » : certains sont des initiés ou des farmeurs d'airdrop, pas des traders compétents.
- GIS124. Détecter les wallets liés (plusieurs adresses du même acteur achetant le même actif) → renforcer le signal au lieu de le compter 5 fois.
- GIS125. Il existe des labels publics de traders perp Hyperliquid profitables → à utiliser comme RÉFÉRENCE EXTERNE pour valider notre propre sélection (jamais comme vérité).

**TK — ORDONNANCEMENT D'EXÉCUTION (Almgren-Chriss)**
- GIS126. Séparer impact PERMANENT (reste, γX², INDÉPENDANT du découpage) et impact TEMPORAIRE (décroît, η̃Σnk², SENSIBLE au découpage).
- GIS127. Conséquence capitale : on ne peut PAS ordonnancer l'impact permanent ; on ne peut réduire QUE le temporaire, en étalant.
- GIS128. Erreur à ne pas commettre : confondre temporaire et permanent → soit on croit à tort que trader lentement est inutile, soit on attend un retour du prix qui ne viendra jamais.
- GIS129. Trajectoire optimale en forme close : interpole entre taux constant (neutre au risque) et FRONT-LOADED (averse au risque).
- GIS130. Plus on est averse au risque, plus on liquide tôt (réduire la variance du coût réalisé) → calibrer κ sur notre aversion.
- GIS131. Frontière efficiente coût espéré vs risque de timing : choisir le point, ne pas le subir.
- GIS132. L-VaR (VaR ajustée de la liquidité) : intégrer le coût de liquidation dans la mesure de risque.
- GIS133. Extension « changement de paramètres » : l'exécution optimale = stratégie statique PONCTUÉE de bascules quand le régime change → brancher sur notre détection de régime (BOCPD, GIS176).
- GIS134. Pré-calculer une trajectoire par régime possible et basculer dès que le régime est identifié.
- GIS135. Face à l'incertitude imprévisible, approximer en relevant artificiellement σ (approche sourcée).
- GIS136. Le coût réalisé (impact VWAP) se situe entre l'impact permanent et le pic instantané : c'est EXACTEMENT ce que notre algorithme contrôle → en faire la métrique de l'exécution.
- GIS137. Résilience du carnet (vitesse de reconstitution) détermine la part temporaire récupérable → la mesurer par coin (lien Hawkes GIS46).

**TL — CONFORMAL PREDICTION : DIMENSIONNEMENT ET PORTE DE NON-TRADE**
- GIS138. Intervalles de prédiction SANS hypothèse de distribution, avec garantie de couverture en échantillon fini (90 % demandé → ≥90 % obtenu).
- GIS139. Dimensionnement inverse-largeur : taille ∝ 1/largeur de l'intervalle → on réduit l'exposition automatiquement quand le modèle est incertain.
- GIS140. Différence clé vs ciblage-volatilité : la largeur conformale est une mesure d'incertitude PRÉDICTIVE sans hypothèse, pas une variance paramétrique.
- GIS141. Ratio d'edge e = |μ̂| / largeur = analogue conformal du rapport signal/bruit → l'utiliser pour la taille ET pour filtrer.
- GIS142. PORTE DE NON-TRADE principielle : si l'intervalle enjambe zéro, le rendement réalisé peut plausiblement avoir le SIGNE OPPOSÉ → ne pas copier.
- GIS143. Géométrie exacte : l'intervalle quitte zéro quand e > 1/2 ; calibrer le seuil θ par backtest (sur données journalières e est souvent bien < 1/2).
- GIS144. ATTENTION : les séries financières ne sont PAS échangeables (clustering de volatilité, régimes) → un split conformal aléatoire casse la garantie.
- GIS145. Utiliser ACI (adaptive conformal inference) ou EnbPI : garantie de couverture à long terme sur données non stationnaires.
- GIS146. CQR (conformalized quantile regression) : intervalles à largeur ADAPTATIVE (mieux que largeur fixe).
- GIS147. Fait mesuré : CQR+ACI réduit l'écart de couverture conditionnelle en haute volatilité (82,3 % → 88,1 % pour une cible de 90 %).
- GIS148. « Conformal Kelly » : lire la demi-largeur comme l'échelle d'une règle Kelly fractionnée plafonnée.
- GIS149. Limite à respecter : la couverture est MARGINALE, pas conditionnelle → localement elle peut être sous/sur-couvrante.
- GIS150. Limite 2 : la largeur n'est pas une densité ; dériver un p et un b de Kelly exige une hypothèse EXPLICITE supplémentaire — l'écrire, ne pas la cacher.

**TM — FACTEURS CROSS-SECTION (et leur honnêteté brutale)**
- GIS151. Fait fort : la BASE est le signal cross-sectionnel le PLUS puissant sur les futures crypto (bien plus que le momentum).
- GIS152. Paramètres sourcés qui marchent : lookback 5 jours / détention 1 jour ; la prime DISPARAÎT à 1 semaine et 1 mois.
- GIS153. Interprétation : régimes crypto changeant vite → l'information passée se périme en jours, pas en mois (contraire aux commodités).
- GIS154. Rendements de facteurs journaliers >> hebdomadaires ; mensuels non significatifs → travailler en journalier.
- GIS155. Basis-momentum : significatif seul, mais DISPARAÎT une fois la base prise en compte → ne pas double-compter.
- GIS156. Momentum cross-sectionnel pur : prime non robuste, très sensible au choix lookback/détention.
- GIS157. GARDE-FOU MAJEUR (réplication nette de coûts) : spread brut +0,573 %/semaine ≈ coûts 0,40 pp → NET non distinguable de zéro, et le signe CHANGE selon le lundi de départ du rebalancement (choix arbitraire sans information de marché).
- GIS158. Donc : tout facteur doit être testé NET, avec plusieurs phases de rebalancement — un résultat qui change de signe selon la phase n'est pas un edge.
- GIS159. Sur 864 configurations testées par un tiers, 1 SEULE était robuste (Sharpe > 0,5 sur deux périodes, 70 % des univers en profit, t ≥ 2) → attendre un taux de réussite très faible.
- GIS160. Primes faibles mais persistantes sur 3 périodes (t < 2) à explorer : distance à l'EMA 200, proximité du plus haut 90 jours, carry de funding hors jeunes listings, illiquidité.
- GIS161. Piège de survivorship : un momentum cross-sectionnel « à 72 %/an » reposait sur le SHORT de listings récents ; sans les tokens de moins d'un an → ~6 %/an.
- GIS162. Fait utile : il n'y a PAS de momentum cross-sectionnel parmi les 11 majors → chercher ailleurs que sur BTC/ETH pour ce facteur.

**TN — FUNDING & CARRY (ce qui est mort, ce qui vit)**
- GIS163. Le funding est un PROXY DE POSITIONNEMENT en temps réel, plus difficile à manipuler que le prix (capital réellement engagé).
- GIS164. Seuil sourcé : funding > 0,10 % par 8 h = longs payant > 100 % annualisé → position encombrée à levier.
- GIS165. Les lectures EXTRÊMES précèdent historiquement des retours à la moyenne — non parce que le taux cause le retournement, mais parce qu'il marque une foule à levier.
- GIS166. Funding NÉGATIF en marché HAUSSIER = conviction baissière qui combat la tendance → short covering potentiellement violent.
- GIS167. Combiner funding extrême + open interest + action du prix (le signal seul est peu fiable).
- GIS168. Fait brutal : le carry de NIVEAU (cash-and-carry delta-neutre) est MORT — Sharpe affiché 8,5 = artefact de la quasi-absence de volatilité du funding ; rendement net +5,6 %/an décroissant vers négatif, sous les T-bills, et son vrai risque (base/liquidation/de-peg) n'est même pas capté par un modèle funding-only.
- GIS169. Ce qui VIT : le facteur de carry CROSS-SECTIONNEL (dollar-neutre, long bas-funding / short haut-funding) → Sharpe IS 0,71, OOS purgé 0,39, deflated 0,63, positif sur 36/36 configurations.
- GIS170. Mais PBO = 0,81 sur ce facteur : les configurations sont statistiquement indiscernables → impossible de choisir « la meilleure » ; espérer ~0,4, pas 1,5. Drawdown max −35 %.
- GIS171. Son edge vient de la DISPERSION relative et du retour à la moyenne des longs encombrés, pas du niveau de funding (qui a décru).
- GIS172. Le funding extrême prédit TRÈS faiblement le prix : rank-IC −0,005 (t = −0,89) — correctement signé (longs encombrés sous-performent) mais NON significatif → l'utiliser comme filtre, jamais comme signal principal.
- GIS173. Prévisibilité du funding : à cadence 15 min il est proche d'une MARCHE ALÉATOIRE ; la marche naïve bat ou égale OU/ARIMA/SETAR presque partout. Demi-vies OU de 0,5-4 h réelles mais faibles.
- GIS174. Parcimonie : la sélection d'ordre choisit p=1 sur 10/12 actifs ; ajouter des lags n'apporte rien ; le régime-switching (SETAR) est significativement PIRE plus souvent que meilleur.
- GIS175. Structure par terme : un spread de termes (yield implicite long − court) est un signal plus fort que le niveau de yield pour anticiper le régime de funding.

**TO — DÉTECTION DE RUPTURE DE RÉGIME EN LIGNE (BOCPD)**
- GIS176. BOCPD (Adams-MacKay) : filtrage sur un HMM à états infinis ; la postérieure de longueur de run donne la probabilité de rupture en TEMPS RÉEL.
- GIS177. Paramètre de hasard λ : petit λ = ruptures fréquentes supposées (plus sensible), grand λ = ruptures rares (plus lisse).
- GIS178. Fait sourcé : la règle maxCPs avec λ = 100 a donné la meilleure performance ; BOCPD surpasse nettement GLR et Kolmogorov-Smirnov.
- GIS179. Trois règles d'extraction à tester : maximum local (colmax), seuil sur P(rt=0), maximum global (maxCPs).
- GIS180. Brancher la sortie BOCPD sur : re-validation des leaders, bascule de stratégie, bascule de trajectoire d'exécution (GIS133).
- GIS181. Extension autorégressive avec paramètres variant dans le temps : capte les dépendances temporelles (mieux que i.i.d. par régime).
- GIS182. Version MULTIVARIÉE : détecter les ruptures dans les CORRÉLATIONS entre actifs (risque systémique, lien HRP GIS97).
- GIS183. Limite 1 : latence de détection intrinsèque — BOCPD a besoin d'accumuler l'évidence, il RETARDE légèrement la vraie rupture. Ne pas promettre l'instantané.
- GIS184. Limite 2 : prior gaussien-NIG suppose la normalité intra-régime ; les rendements crypto sont leptokurtiques → tester un modèle d'observation à queues lourdes (Student-t).
- GIS185. Limite 3 : l'hypothèse i.i.d. intra-régime est violée par le clustering de volatilité → en être conscient dans la lecture de la postérieure.
- GIS186. Appliquer BOCPD au FLUX D'ORDRES (pas seulement aux prix) — fait : testé sur l'order flow d'actions liquides.
- GIS187. Historiser les ruptures détectées et ce qui a marché après chacune (mémoire de régime, lien I178/I224).

**TP — HONNÊTETÉ & GARDE-FOUS NOUVEAUX (ce que ces recherches imposent)**
- GIS188. Toute métrique de classification se lit en MACRO-F1 (ou par classe), jamais en accuracy brute — la classe stationnaire domine.
- GIS189. Tout résultat brut se double obligatoirement du NET : la leçon DeepLOB (brut +3850 / spread −8091) est la règle, pas l'exception.
- GIS190. Tout facteur se teste sur PLUSIEURS phases de rebalancement : un signe qui bascule selon la phase = pas d'edge (GIS157).
- GIS191. Tout Sharpe se DÉFLATE du nombre d'essais, et on rapporte le PBO à côté (fait : PBO 0,81 rend le « meilleur » inchoisissable).
- GIS192. Un Sharpe spectaculaire sur un actif à très faible volatilité (funding) est un ARTEFACT : lire le rendement net, pas le ratio.
- GIS193. Toujours rapporter le drawdown max à côté du Sharpe (le carry cross-sectionnel vit avec −35 %).
- GIS194. Les risques non capturés par le modèle (base, liquidation, de-peg, halt du déployeur HIP-3) doivent être NOMMÉS, même non quantifiés.
- GIS195. Les estimations (heatmap de liquidations, GEX, positionnement des dealers) sont des MODÈLES, pas des données — les étiqueter comme telles dans les rapports.
- GIS196. Avant d'ajouter un modèle sophistiqué, mettre le benchmark simple dans la course (variance récente avant Hawkes, marche aléatoire avant OU/ARIMA, 1/N avant HRP).
- GIS197. La parcimonie gagne souvent (p=1 bat p>1 ; HRP améliore le risque pas le rendement ; le no-attention FFN reste compétitif) → préférer simple et prouvé.
- GIS198. Vérifier les artefacts d'horodatage AVANT de croire tout signal de lead-lag (un lead de 700 ms est trivial à fabriquer par dérive d'horloge).
- GIS199. Séparer ce qui est MÉCANIQUE de ce qui est INFORMATIONNEL (fait : l'impact en racine carrée semble essentiellement mécanique) — ça change l'interprétation et la durabilité de l'edge.
- GIS200. Conclusion transversale de ces 20 recherches : la prédictibilité court terme EXISTE et est mesurable, mais presque tout l'edge brut est mangé par le spread et les frais. Les seules voies crédibles restantes pour nous : (1) devenir MAKER (gagner le spread au lieu de le payer), (2) exploiter des RÉGIMES où l'adverse selection chute (week-end HIP-3), (3) capter des primes STRUCTURELLES (carry cross-sectionnel, base), (4) anticiper via un MENEUR (Binance → HL, ordres en attente). Tout le reste est du bruit coûteux.

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

### C-duodecies. 100 AMÉLIORATIONS DU COLLECTEUR AU SERVICE DU LABO (K1–K100, 12/11)

**Ancrées sur les mesures du jour, pas sur des intuitions.** Chiffres de référence obtenus en
réconciliant les rubans réels : **97 % des fills ont déjà leurs trois carnets** (560/576) ; cadence
médiane des carnets **10,3 s** (p90 ≈ 11 s) avec **UN seul trou > 30 s sur 30 coins** ; mais seulement
**8 leaders distincts, dont un à 63 % des fills** ; **14 refus** pour carnets de connexions différentes
(STRK, SEI) ; **27 coins sur 30** portent plusieurs époques de trou ; le ruban local **n'a pas** de
champ `crossed`. Conclusion qui ordonne tout ce qui suit : **la couverture des carnets n'est plus le
goulot — le VOLUME et la DIVERSITÉ des signaux le sont.**

**A — VOLUME ET DIVERSITÉ DES SIGNAUX (le vrai goulot : 8 leaders, un seul à 63 %)**
- K1 ⚡ Câbler `collecter_userfills_poll.py` au registre + profil harvest : il existe pour « casser le plafond WS (~10 userFills/IP) » via REST et il ne tournait pas. C'est LA raison des 8 leaders.
- K2 ⚡ Réserver son poids dans le budget PARTAGÉ avant chaque requête (fait ce jour) : sans cela il recrée les 429.
- K3 ⚡ Mesurer, après câblage, le nombre de leaders distincts par jour — c'est l'indicateur de progrès n°1.
- K4 ⚡ Plafonner la part d'un seul leader dans les signaux retenus : à 63 %, le labo mesure un trader, pas une stratégie.
- K5 🔬 Cadence de poll proportionnelle à l'activité récente du leader (celui qui vient d'émettre est repollé plus vite).
- K6 🔬 Dégrader la cadence des leaders inactifs plutôt que les retirer (ils peuvent revenir).
- K7 ⚡ Répartir les 10 slots WS sur les leaders les plus ACTIFS, laisser le reste au REST.
- K8 🔬 Rotation équitable des slots WS pour que chaque leader ait des fenêtres d'observation directe.
- K9 🔬 Découverte continue de nouveaux leaders actifs, filtrée sur copiabilité (pas sur PnL affiché).
- K10 🔬 Détecter et fusionner les clones (mêmes fills décalés) pour ne pas compter un acteur plusieurs fois.
- K11 🔬 Dédupliquer les ENTITÉS (plusieurs adresses d'un même acteur) avant de compter « n leaders ».
- K12 🔬 Garder les leaders devenus inactifs dans l'univers historique (mesure du biais de survie).
- K13 📊 Journal « couverture leaders » : vus actifs vs effectivement collectés (l'écart est le manque à gagner).
- K14 🔬 Prioriser les leaders dont les fills sont majoritairement AGRESSIFS (le filtre C86 existe désormais).
- K15 ⚡ Objectif chiffré : passer de 8 à ≥ 40 leaders distincts par jour avant de juger un résultat statistiquement.

**B — EXÉCUTABILITÉ : LES TROIS CARNETS (déjà à 97 %, protéger l'acquis)**
- K16 ⚡ Garder la cadence de 10,3 s par coin : c'est elle qui donne les 97 % — toute régression ici détruit la mesure.
- K17 ⚡ Carnet de SORTIE garanti jusqu'à l'horizon MAX (TTL corrigé le 12/11) : ne jamais revenir au min.
- K18 ⚡ Abonnement déclenché par l'activité : dès le premier fill sur un coin, s'abonner sans attendre la régénération de liste.
- K19 ⚡ Pré-chauffage par coins habituels (fait) : vérifier à chaque passe qu'aucun coin tradé n'est hors liste.
- K20 📊 Alerte si un coin tradé n'a aucun carnet depuis N minutes (`coins_sans_aucun_carnet` existe).
- K21 🔬 Mesurer la couverture PAR COIN et non globalement (correctif du 12/11 : la fenêtre globale accusait 114 fills à tort).
- K22 🔬 Prolonger l'abonnement d'un coin tant qu'un leader y a une position OUVERTE (lanes « sortie »).
- K23 🔧 Ne jamais désabonner un coin pendant qu'un métaordre est en cours dessus.
- K24 📊 Publier le % de fills à trois carnets à chaque passe (la jauge existe : `reconciliation_executabilite`).
- K25 🔬 Suivre FARTCOIN/ZEC et les coins à 1-2 fills : ils échouent faute de couverture au bon moment.
- K26 🔧 Vérifier que la liste de coins n'est jamais saturée au point de bloquer les ajouts (bug corrigé le 12/11 : 0 ajout sur 117 demandes).
- K27 🔬 Mesurer le délai entre premier fill sur un coin nouveau et premier carnet de ce coin (temps d'amorçage).

**C — CONTINUITÉ D'IDENTITÉ DE CONNEXION (14 refus mesurés, STRK et SEI)**
- K28 ⚡ Comprendre pourquoi 27 coins sur 30 portent plusieurs époques de trou : c'est le dernier défaut mesurable.
- K29 ⚡ Réduire la fréquence des réabonnements (chaque réabonnement incrémente l'époque et casse la continuité).
- K30 🔧 Grouper les coins par socket de façon STABLE : un coin ne doit pas changer de connexion en cours de session.
- K31 🔧 Ne pas incrémenter l'époque quand la reconnexion n'a causé AUCUNE perte (trou nul = continuité réelle).
- K32 🔬 Mesurer la durée de vie moyenne d'une connexion : plus elle est longue, plus de fills deviennent mesurables.
- K33 🔧 Reprise au watermark exact après reconnexion (ni trou ni doublon).
- K34 📊 Journaliser chaque incrément d'époque avec sa cause (déconnexion, trame rejetée, réabonnement).
- K35 🔬 Préférer N sockets stables à 1 socket qui se réabonne souvent.
- K36 🔧 Heartbeat ping/pong par socket : détecter un pong manquant avant de perdre des trames.
- K37 📊 Mesurer, par coin, le nombre d'époques traversées par heure (STRK et SEI en tête aujourd'hui).

**D — DÉBIT ET BUDGET PARTAGÉ (218 → 16 refus ; viser 0)**
- K38 ⚡ Tous les collecteurs REST passent par `reserver_poids` : un seul cloisonné recrée les rafales.
- K39 🔬 Poids EXACT par type de requête (`clearinghouseState` 2, `l2Book` 2, `frontendOpenOrders` 20, `userFills` 20+1/20).
- K40 ⚡ Exploiter `clearinghouseState` à poids 2 : les POSITIONS de nombreux leaders sont quasi gratuites.
- K41 🔬 Brancher `userRateLimit` pour piloter la cadence au réel, pas à l'estime.
- K42 🔧 Respecter `Retry-After` partout (le module `backoff` le gère déjà : l'utiliser uniformément).
- K43 🔧 Jitter au démarrage de chaque collecteur (supprime la rafale synchronisée du lancement).
- K44 🔬 Priorité de budget déclarée : fills causaux > carnets des coins actifs > ordres > rattrapages.
- K45 🔧 Mode dégradé sous pression : ralentir les non critiques, jamais les fills causaux.
- K46 📊 Historiser le nombre de 429 par lancement (218 → 16 ; objectif ~0).
- K47 🔬 Multi-IP pour dépasser les 10 users WS et les 1200 poids/min (lanes cloud sur IP séparées).

**E — FIABILITÉ, REPRISE, ZÉRO PERTE**
- K48 ⚡ Écriture atomique (tmp + rename) de TOUS les rubans et curseurs : un arrêt brutal ne corrompt rien.
- K49 ⚡ Tampons en mémoire PLAFONNÉS avec flush disque (jamais de croissance illimitée).
- K50 🔧 Reprise après kill -9 sans perte ni double comptage (test de mort brutale).
- K51 🔧 Nettoyage des `.pid` orphelins + détection de double instance au démarrage.
- K52 🔧 Watchdog qui relance un collecteur mort en < 5 s AVEC reprise d'état.
- K53 ⚡ Ligne de vie périodique pour tout collecteur sans heartbeat (sinon le superviseur relance un vivant = double collecte).
- K54 🔧 Détecter le « marché silencieux » et marquer un TROU, pas « aucune activité » (le labo doit savoir).
- K55 🔧 Déduplication inter-sources par identité stable de fill (WS, REST, nœud) sur TOUS les flux.
- K56 🔬 Ordonnancement déterministe des fills de même instant (sinon deux runs donnent deux résultats).
- K57 🔧 Archivage sans perte (déplacer, jamais supprimer) et certifier avant d'archiver.
- K58 🔧 Rotation des rubans à la TAILLE, pas à la session.
- K59 🛡️ Adapter l'ampleur à la RAM via le gouverneur (fait) : ralentir, jamais crasher.

**F — QUALITÉ ET HONNÊTETÉ DES DONNÉES**
- K60 ⚡ `data_origin` = OBSERVÉ_RÉEL vs RECONSTRUIT partout ; interdire la confusion.
- K61 ⚡ Horodatage de RÉCEPTION à l'instant exact de lecture du socket (le labo s'en sert comme horloge causale).
- K62 ⚡ Refuser tout carnet `received < exchange` ou lag > 30 s, et AUDITER les rejets (pas seulement les compter).
- K63 🔧 Vérifier la monotonie de l'horloge de réception par socket (détecte une dérive d'horloge).
- K64 🔬 Ne jamais transformer une donnée obtenue après coup en donnée « disponible à la décision ».
- K65 🔧 Provenance de tier (LOCAL vs SAFE) jamais perdue dans le pont vers le labo.
- K66 🔧 Chaque nouveau flux a une règle de certification OU un motif explicite d'exclusion (jamais ignoré en silence).
- K67 ⚡ Empreinte SHA-256 des shards scellés et refus d'écrasement (le tier LOCAL n'en a aucune aujourd'hui).
- K68 🔧 Quarantaine horodatée avec motif LISIBLE pour chaque ligne écartée.
- K69 🔧 Ne jamais baisser les exigences de qualité pour gonfler le nombre de shards.
- K70 📊 Rapport de couverture par famille : scellé / réparé / écarté / inconnu.
- K71 🔬 Revérifier par rotation que le magasin de ticks natifs est bien immuable.

**G — NOUVELLES DONNÉES DIRECTEMENT UTILES AU LABO**
- K72 ⚡ `crossed` (agressif/passif) dans le ruban LOCAL : absent aujourd'hui, alors que le filtre C86 en dépend.
- K73 ⚡ Ordres en attente des leaders ALIGNÉS sur les fills (fait le 12/11) : sans alignement, l'étude maker reste vide.
- K74 ⚡ `activeAssetData` : levier et capacité disponible du leader = mesure de CONVICTION par trade.
- K75 🔬 Ledger non-funding : dépôts/retraits = flux de capital, signal d'intention avant une série de trades.
- K76 🔬 `userTwapSliceFills` : détecter les TWAP et anticiper les tranches suivantes.
- K77 🔬 Trades publics par coin : indispensables à l'OFI et à l'impact de marché réel.
- K78 🔬 Open interest et premium mark/oracle par coin (overshoot, positionnement).
- K79 🔬 Liquidations confirmées reliées aux carnets (fade de liquidation).
- K80 🔬 Funding horaire de TOUS les coins tradés, pas d'un sous-ensemble.
- K81 🔬 Bougies 1 h sur long historique, incrémental, pour la volatilité réalisée (HAR).
- K82 🔬 Profondeur de carnet au-delà de 5 niveaux (impact des tailles réelles).
- K83 🔬 Flux d'une venue MENEUSE (Binance) : le module de mesure du décalage existe et attend ses données.

**H — OBSERVABILITÉ ET BOUCLE DE RETOUR (de 6 jours à 2 secondes)**
- K84 ⚡ Lancer `reconciliation_executabilite` à chaque passe : savoir en 2 s si la collecte sera mesurable.
- K85 ⚡ Toujours mesurer la couverture PAR COIN : une fenêtre globale mentait de 114 fills.
- K86 📊 Tableau de bord par flux : lignes/s, fraîcheur, trous, 429, reconnexions.
- K87 📊 Reçu de couverture par lane (coins, fenêtre, reconnexions, trous).
- K88 📊 Score « carburant » : combien de signaux deviendront scoreables au rythme actuel.
- K89 📊 Suivre le nombre de JOURS DENSES accumulés (le seuil des 6 jours est le vrai compte à rebours).
- K90 📊 Publier l'écart entre ce que le labo demande et ce que la collecte fournit (la boucle est déjà câblée).
- K91 🔬 Mesurer la latence réception − bourse par flux (distribution, pas moyenne).
- K92 📊 Alerter dès qu'un indicateur régresse (cadence, leaders, part à trois carnets).

**I — PERFORMANCE ET COÛT**
- K93 🔧 Index temporel des carnets par coin pour un chargement O(log n) côté labo.
- K94 🔧 Interning des chaînes répétées dans les gros rubans (mémoire).
- K95 🔧 Ne jamais garder deux copies d'un carnet en mémoire pendant le scellage.
- K96 🔧 Compression des shards certifiés + vérification d'intégrité.
- K97 🔧 Purge sûre des rubans de travail du labo après usage.
- K98 🔬 Lecture BORNÉE de la queue des rubans pour toute jauge (coût indépendant de la taille du fichier).
- K99 🔧 Timeout de requête adaptatif à la latence observée (p95 glissant).
- K100 ⚡ **Règle d'or** : une amélioration de collecteur ne compte que si elle augmente le nombre de signaux MESURABLES par le labo. Toute autre optimisation attend. C'est la mesure du jour qui tranche, pas l'intuition : la couverture des carnets était déjà à 97 %, donc tout effort supplémentaire y aurait été gaspillé — le gain est dans les LEADERS.

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
- **`POUSSER-GITHUB-FORCE.cmd` : défaut = code seul** (push rapide, plus de téléchargement SAFE de 153 Go) ;
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
