# HYPERSMART — REGISTRE COMPLET DES TÂCHES (MASTER V6)

> Source : `HYPERSMART_CHERCHEUR_D_OR_MASTER_V6_TACHES_CLAUDE_BUGS_EXECUTION.md`
> (17 699 lignes, HEAD de référence `8e899a20cd05d7b0c689a447f086b0bdae9d18ca`).
> Ce registre liste **chaque chose à faire** du document, dédupliquée par identifiant :
> **390 défauts AUD-001→AUD-390 + 120 tâches DATA-001→DATA-120 + 80 tâches BUG-001→BUG-080 = 590 tâches.**
> Aucune n'est oubliée. Chaque tâche = une entrée dans la barre de progression.

---

## 🔒 Garde-fous non négociables (valables pour TOUTES les tâches)

- **PAPER / READ-ONLY UNIQUEMENT** : 0 ordre réel, 0 `/exchange`, 0 clé privée, 0 seed/mnemonic, 0 signature, 0 dépôt/retrait, 0 wallet-connect pour agir, aucune exécution mainnet/testnet.
- **Capital fictif consolidé = exactement 1 000 USD** (jamais additionné entre lanes/cohortes).
- **Vérité des données** : donnée absente = `DATA_MISSING`/`UNMEASURABLE`/`TECHNICAL_FAILURE`, jamais zéro. Aucune donnée fabriquée présentée comme réelle. Aucun PnL maquillé.
- **Familles actives** : Copy-Vault, Lead-Lag, Cross-Venue. **Carry = DISABLED_BY_SCOPE** (historique/audit seulement).
- **Discipline** : défaut prouvé → test rouge → correction minimale → tests ciblés + régression → commit sur `main` (1 bloc = 1 commit) → SHA publié. `DONE` interdit sans commit + tests + preuve runtime.
- **Verdict économique autorisé** : `VALIDATED_POSITIVE_PAPER` (positif robuste prouvé) **ou** `NO_VALIDATED_EDGE_FOUND` / `MORE_DATA` / `TECHNICAL_BLOCKER` / `DATA_BLOCKER`. Jamais de gain garanti.
- **État d'esprit gagnant** : ambition maximale pour TROUVER l'edge + honnêteté totale pour ne GARDER que ce qui survit (fees+spread+slippage+latence+partial fills+capacité+OOS+forward post-gel).

Sévérités : **S0** sécurité/exécution réelle · **S1** faux PnL/corruption économique · **S2** perte d'alpha/câblage/données · **S3** robustesse/dette · **S4** secondaire.

---

## 🌊 Ordre d'exécution imposé (section 318 du master)

- **Vague 1 — empêcher les mensonges techniques** : BUG-001→016, DATA-001→006, DATA-108→120.
- **Vague 2 — dYdX & Binance complets** : DATA-007→035, BUG-017→040.
- **Vague 3 — Bybit, OKX, Coinbase** : DATA-036→071, BUG-041→060.
- **Vague 4 — Deribit, Kraken, Drift, GMX** : DATA-072→093, BUG-061→080.
- **Vague 5 — enrichissements optionnels** : DATA-094→107.
- **Transverse (chantiers laboratoire/validation)** : AUD-001→260 (unification orchestrateur, freeze/forward, Lead-Lag causal, Cross-Venue round-trip, Copy-Vault lifecycle, taxonomie de preuve, capital unique, zéro-position, apprentissage, rapport PnL, stats anti-overfit, CI Windows).

---

# 1) DÉFAUTS AUD-001 → AUD-390

## AUD-001 → AUD-011 — Registre conservatoire (fondations, MASTER V3)

- **AUD-001** — S1 — Vérité de données/provenance insuffisamment autoritative.
- **AUD-002** — S1 — Épisodes ou observations non indépendants.
- **AUD-003** — S1 — Partitions ou frontières contaminables.
- **AUD-004** — S1 — Coûts/exécution incomplets ou synthétiques.
- **AUD-005** — S2 — Cache/adressage de contenu insuffisant.
- **AUD-006** — S1 — Plusieurs pipelines économiques concurrents.
- **AUD-007** — S1 — Ledger/equity/report non unifiés.
- **AUD-008** — S2 — Module présenté actif sans preuve de câblage.
- **AUD-009** — S2 — Tests verts non équivalents à preuve économique.
- **AUD-010** — S2 — CI/release/package ne testant pas forcément le même logiciel.
- **AUD-011** — S2 — Données locales massives non reproductibles indépendamment.

## AUD-012 → AUD-021 — Registre conservatoire (laboratoire)

- **AUD-012** — S2 — Seulement 24 configurations par défaut.
- **AUD-013** — S2 — Chemin principal encore mono-session.
- **AUD-014** — S1 — Classement utilisant OOS + Forward.
- **AUD-015** — S1 — Réconciliation échouée classée comme perte.
- **AUD-016** — S2 — README opposé au scope officiel.
- **AUD-017** — S2 — Carry/legacy pouvant contaminer docs, tests ou rapports.
- **AUD-018** — S2 — Sources de vérité contradictoires.
- **AUD-019** — S2 — Chemins runtime/legacy concurrents.
- **AUD-020** — S2 — Scope annoncé non uniformément appliqué.
- **AUD-021** — S1 — Résultats historiques contaminés non invalidés.

## AUD-022 → AUD-032 — Release / CI / packaging

- **AUD-022** — S2 — Archive portable non prouvée.
- **AUD-023** — S2 — Environnement distribué différent de l'environnement testé.
- **AUD-024** — S1 — CI non rattachée au SHA ou jobs critiques non bloquants.
- **AUD-025** — S2 — Scripts Windows non couverts E2E.
- **AUD-026** — S2 — Chemins/encodage/CRLF/locks/WAL non prouvés.
- **AUD-027** — S2 — Package installé pouvant différer du checkout.
- **AUD-028** — S2 — Runtime canonique et package legacy confondus.
- **AUD-029** — S2 — Validations visant le mauvais package.
- **AUD-030** — S2 — Artefacts officiels non issus du chemin strict.
- **AUD-031** — S2 — Dépendances/sources non hermétiques.
- **AUD-032** — S1 — Release déclarée prête sans preuve d'installation/exécution.

## AUD-033 → AUD-040 — Hérités du MASTER V3

- **AUD-033 → AUD-040** — Conservés du MASTER V3 (référencés §141 mais **titres non cités dans V6**). À retrouver dans l'historique du master ; restent OUVERTS, jamais fermés implicitement. (8 tâches.)

## AUD-041 → AUD-060 — Collecteurs, câblage & preuve de vie (Addendum V4)

- **AUD-041** — S1 — Aucun commit public après le SHA de reprise (registre GIT_HEAD_AUDIT_TRAIL).
- **AUD-042** — S1 — CI publique du HEAD non prouvée.
- **AUD-043** — S1 — READY_CORE ne prouve pas READY_STRATEGIES (barrière par famille).
- **AUD-044** — S1 — Profil HARVEST inclut dYdX contrairement aux docs/tests → politique unique.
- **AUD-045** — S1 — Flag EXPERIMENTAL_PAPER actif mais worker potentiellement non schedulé.
- **AUD-046** — S2 — Lignes legacy exécutables présentes dans le lanceur (après exit /b).
- **AUD-047** — S1 — Succès de spawn confondu avec collecteur démarré (PID ≠ handshake).
- **AUD-048** — S1 — Collecteurs batch échouant en boucle avec log toujours frais.
- **AUD-049** — S1 — Collecteurs secondaires ne bloquent pas les familles qu'ils alimentent.
- **AUD-050** — S2 — Couverture incohérente REGISTRE/HARVEST/SOURCES_HARVEST (overshoot-collector).
- **AUD-051** — S2 — Registre mélange producteurs/dériveurs/consommateurs/reporters (rôles canoniques).
- **AUD-052** — S1 — Absence de preuve systématique producteur → consommateur.
- **AUD-053** — S2 — Launcher affiche une liste HARVEST sans prouver chaque élément.
- **AUD-054** — S2 — Politique de restart insuffisante pour les échecs sémantiques.
- **AUD-055** — S1 — Preuve de vie ne distingue pas marché calme et collecteur cassé.
- **AUD-056** — S2 — Environnement Python enfant non attesté (HYPERSMART_PYTHON).
- **AUD-057** — S1 — Registres PID/états à rendre atomiques et anti-PID-reuse.
- **AUD-058** — S1 — Tests trop mockés pour prouver le double-clic Windows réel (E2E faux collecteurs).
- **AUD-059** — S1 — Dépendances collecteurs des familles actives non autoritatives (strategy_data_dependencies).
- **AUD-060** — S1 — Une collecte valide est condition préalable à LIQUIDATABLE_NET.

## AUD-061 → AUD-086 — Méga-audit continu (P0 économiques)

- **AUD-061** — S1 — Le segment FORWARD participe à la sélection et à la promotion (fuite de validation).
- **AUD-062** — S1 — Empreinte de cache économique insuffisante (64 premiers triplets seulement).
- **AUD-063** — S2 — Lanceur d'analyse mono-session, pas cumulatif.
- **AUD-064** — S1 — Audit de câblage du labo produit des faux « CÂBLÉ ET UTILISÉ ».
- **AUD-065** — S1 — Lead-Lag ne modélise pas une relation inter-venues (groupe par coin + next tick).
- **AUD-066** — S1 — Lead-Lag utilise mid, liquidité par défaut et réconciliation déclarative.
- **AUD-067** — S1 — Cross-Venue reconstruit artificiellement timestamps, latence et provenance.
- **AUD-068** — S1 — Paire Cross-Venue appariée jamais liquidée dans MegaCablage (round-trip incomplet).
- **AUD-069** — S1 — Positions COIN@VENUE ne reçoivent pas les marks simples du pipeline.
- **AUD-070** — S1 — Runtime Fusion transforme Cross-Venue en position directionnelle à une jambe.
- **AUD-071** — S1 — Plusieurs pipelines économiques concurrents (EconomicAuthorityRegistry).
- **AUD-072** — S1 — Fills ordinaires de MegaCablage utilisent une latence nulle (ExecutionContext).
- **AUD-073** — S1 — data_origin=REEL est un défaut et un fallback (deny-by-default).
- **AUD-074** — S1 — Rapport POSITIF ne signifie pas LIQUIDATABLE_NET (taxonomie 1→6).
- **AUD-075** — S1 — Actions Copy-Vault perdues entre reconstruction et exécution (LeaderPositionTarget).
- **AUD-076** — S2 — Feed adapter accepte des événements passe-plat insuffisamment validés.
- **AUD-077** — S1 — Test E2E raw-to-PnL prouve une réconciliation, pas un PnL liquidable.
- **AUD-078** — S2 — P95/P99 Lead-Lag ne sont pas des stress exécutions indépendantes.
- **AUD-079** — S2 — Verrou du laboratoire non garanti par finally (Ctrl+C/exception).
- **AUD-080** — S2 — Grille de recherche restreinte et adaptativité non contrôlée.
- **AUD-081** — S2 — Carry reste présent dans runtime/imports/tests (isoler LEGACY_RESEARCH_ONLY).
- **AUD-082** — S2 — Sécurité configurée mais résultat au HEAD non prouvé (job bloquant + manifeste).
- **AUD-083** — S3 — Tests sécurité fondations ne scannent qu'un sous-ensemble.
- **AUD-084** — S1 — Mode strict et expérimental possèdent chacun 1000 USD (anti-somme).
- **AUD-085** — S2 — MegaCablage non prouvé comme moteur du lanceur principal.
- **AUD-086** — S2 — Connecteur paper Fusion accepte sans exécuter (INTENT ≠ ORDER ≠ FILL).

## AUD-087 → AUD-102 — Améliorations ANALYSER_BACKTESTS_REPLAYS.cmd

- **AUD-087** — S2 — Analyse mono-session par défaut (double-clic cumulatif).
- **AUD-088** — S2 — Espace par défaut limité à 24 configurations.
- **AUD-089** — S1 — Forward consulté pendant l'évaluation des configurations.
- **AUD-090** — S1 — Absence de registre global anti-data-mining.
- **AUD-091** — S2 — Absence de sampler et pruner adaptatifs (Random/Sobol/TPE/Halving).
- **AUD-092** — S2 — Espace de recherche commun trop pauvre (espaces par famille).
- **AUD-093** — S1 — Cache non invalidé par toute l'économie du replay (fingerprint complet).
- **AUD-094** — S1 — Absence de portefeuille global dans le lanceur (1000 USD unique).
- **AUD-095** — S2 — Pas de commande d'arrêt propre du laboratoire (stop/drain/checkpoint/reconcile).
- **AUD-096** — S2 — Pas de reprise exacte inter-session.
- **AUD-097** — S3 — Absence de mode status complet (PID/phase/compteurs/ETA/incidents).
- **AUD-098** — S1 — Stress synthétique confondu avec mesure (MEASURED/ESTIMATED/STRESS_ONLY).
- **AUD-099** — S1 — Horizon Lead-Lag implicite ou insuffisant (paire intervenue + horizons explicites).
- **AUD-100** — S1 — Round-trip Cross-Venue non garanti par le lanceur.
- **AUD-101** — S1 — Rapport non hiérarchisé par niveau de preuve (taxonomie GROSS→RECONCILED_FORWARD).
- **AUD-102** — S2 — Tests Windows E2E du CMD insuffisants (dispatch/stop/reprise/rapport/portable).

## AUD-103 → AUD-126 — Zéro position en simulation

- **AUD-103** — S1 — Zéro position sans diagnostic causal.
- **AUD-104** — S2 — Absence de READY_STRATEGIES.
- **AUD-105** — S2 — Strict sizing peut expliquer zéro sans message explicite.
- **AUD-106** — S2 — experimental_paper_v2 désactivé mais potentiellement encore visible en UI.
- **AUD-107** — S1 — Aucun producteur vivant confondu avec marché calme (panne silencieuse).
- **AUD-108** — S1 — Funnel événements→positions absent.
- **AUD-109** — S2 — Drops producteur/consumer insuffisamment exposés à l'utilisateur.
- **AUD-110** — S1 — Absence de preuve live que chaque famille émet un PaperIntent.
- **AUD-111** — S1 — Absence de preuve live que chaque PaperIntent atteint l'exécuteur.
- **AUD-112** — S1 — Absence de preuve live que chaque fill atteint le ledger.
- **AUD-113** — S1 — Réconciliation moteur/ledger/store/API/UI non continue.
- **AUD-114** — S1 — Tous les signaux peuvent être sized à zéro sans alerte globale.
- **AUD-115** — S2 — Causes NO_TRADE non hiérarchisées.
- **AUD-116** — S2 — Adresse agent/master/subaccount non diagnostiquée.
- **AUD-117** — S1 — Pagination fills incomplète pouvant supprimer les signaux.
- **AUD-118** — S1 — Déduplication snapshot/reconnect pouvant sur-supprimer.
- **AUD-119** — S2 — Rate limit/staleness pouvant refuser 100% des entrées.
- **AUD-120** — S2 — Absence de voie exploratoire canonique active.
- **AUD-121** — S1 — Risque de ressusciter un moteur experimental parallèle.
- **AUD-122** — S1 — Budget exploratoire potentiellement additionné au capital officiel.
- **AUD-123** — S2 — « positions ouvertes = 0 » sans distinction jamais essayé/refusé/missed.
- **AUD-124** — S2 — Test E2E Windows de la première position absent.
- **AUD-125** — S1 — Dashboard peut lire une cohorte ou un ledger différent.
- **AUD-126** — S3 — Aucun SLA « première position ou diagnostic définitif ».

## AUD-127 → AUD-138 — Apprendre des erreurs (cohortes exploratoires)

- **AUD-127** — S2 — La voie stricte seule peut affamer le laboratoire en outcomes.
- **AUD-128** — S2 — Absence de cohorte exploratoire canonique active.
- **AUD-129** — S3 — Absence de probes contrôlés pour calibrer les inconnues.
- **AUD-130** — S2 — Les pertes paper ne sont pas systématiquement attribuées.
- **AUD-131** — S2 — Absence de replay contrefactuel automatique par trade.
- **AUD-132** — S2 — Mémoire d'apprentissage inter-run insuffisante.
- **AUD-133** — S1 — Risque de supprimer ou ignorer les configurations perdantes.
- **AUD-134** — S1 — Risque de confondre PnL exploratoire et PnL validé.
- **AUD-135** — S1 — Risque de multiplier le capital entre cohortes.
- **AUD-136** — S2 — Absence de priorité du capital STRICT sur EXPLORATORY.
- **AUD-137** — S3 — Absence de rapport « erreurs apprises ».
- **AUD-138** — S2 — Admission exploratoire non formalisée.

## AUD-139 → AUD-146 — Rapport « comment améliorer le PnL »

- **AUD-139** — S2 — Le rapport ne dit pas encore comment améliorer le PnL.
- **AUD-140** — S2 — Absence de classement des actions par gain attendu.
- **AUD-141** — S2 — Absence d'attribution complète des pertes.
- **AUD-142** — S2 — Absence de rapport des opportunités manquées.
- **AUD-143** — S2 — Absence de suivi avant/après des recommandations.
- **AUD-144** — S3 — Absence de rapport simple destiné à Flo.
- **AUD-145** — S2 — Absence de file d'expériences PnL priorisée.
- **AUD-146** — S2 — Absence de verdict conserver/annuler chaque amélioration.

## AUD-147 → AUD-180 — Laboratoire multi-moteurs maximal

- **AUD-147** — S2 — Absence d'orchestrateur DAG.
- **AUD-148** — S2 — Absence de moteur vectorisé de fast screen.
- **AUD-149** — S1 — Absence de comparaison fast/exact.
- **AUD-150** — S2 — Catalogue de scénarios insuffisant.
- **AUD-151** — S2 — Espace de recherche non versionné complètement.
- **AUD-152** — S2 — Absence d'optimisation multi-objectifs complète.
- **AUD-153** — S2 — Pareto front non conservé.
- **AUD-154** — S1 — Queue model non calibré.
- **AUD-155** — S1 — Feed/order/inter-leg latency non séparées.
- **AUD-156** — S1 — Analyse lookahead dédiée absente du CMD.
- **AUD-157** — S2 — Analyse récursive dédiée absente.
- **AUD-158** — S2 — Property-based testing insuffisant.
- **AUD-159** — S2 — Mutation testing insuffisant.
- **AUD-160** — S1 — Differential testing insuffisant.
- **AUD-161** — S2 — Fault injection insuffisant.
- **AUD-162** — S2 — Registre SQLite des expériences absent.
- **AUD-163** — S1 — Data lineage trial/artifact incomplet.
- **AUD-164** — S3 — Recalcul descendant non ciblé.
- **AUD-165** — S1 — Parallélisme non prouvé déterministe.
- **AUD-166** — S2 — Moteur larger-than-RAM non formalisé.
- **AUD-167** — S2 — Scenario coverage non mesurée.
- **AUD-168** — S2 — Génération automatique d'hypothèses insuffisante.
- **AUD-169** — S2 — Ablations non systématiques.
- **AUD-170** — S2 — Contrefactuels non systématiques.
- **AUD-171** — S3 — Clustering des erreurs absent.
- **AUD-172** — S3 — Transfert coin/venue/régime non testé.
- **AUD-173** — S2 — Bibliothèque de 100 scénarios non automatisée.
- **AUD-174** — S1 — Simulations agent-based non isolées SYNTHETIC.
- **AUD-175** — S3 — Plan factoriel et Sobol insuffisants.
- **AUD-176** — S2 — Plateau search insuffisant.
- **AUD-177** — S2 — Budget adaptatif inter-fidélités absent.
- **AUD-178** — S2 — Cache par nœud DAG insuffisant.
- **AUD-179** — S2 — Rapport maximum de pistes absent.
- **AUD-180** — S2 — Double-clic maximum non prouvé E2E Windows.

## AUD-181 → AUD-220 — CMD hermétique, tests combinatoires, recherche automatisée

- **AUD-181** — S2 — CMD trop intelligent (bootstrap uniquement).
- **AUD-182** — S2 — Expansion différée dangereuse pour les chemins.
- **AUD-183** — S2 — Couverture caractères spéciaux Windows insuffisante.
- **AUD-184** — S2 — Codes de sortie non exhaustivement testés.
- **AUD-185** — S1 — Process group et arrêt enfant insuffisants.
- **AUD-186** — S1 — Environnement non totalement hermétique.
- **AUD-187** — S2 — Dépendances non hashées intégralement.
- **AUD-188** — S3 — SBOM absent.
- **AUD-189** — S2 — Installation possible pendant un run.
- **AUD-190** — S1 — Flaky test pouvant être masqué par rerun.
- **AUD-191** — S2 — Timeouts incomplets.
- **AUD-192** — S2 — Test order dependency non recherchée.
- **AUD-193** — S2 — Pairwise/t-way absent.
- **AUD-194** — S2 — Couverture des interactions non mesurée.
- **AUD-195** — S1 — Expectations de données non centralisées.
- **AUD-196** — S1 — Schema drift insuffisamment détecté.
- **AUD-197** — S1 — Stationary/block bootstrap incomplet.
- **AUD-198** — S1 — SPA/Reality Check absent.
- **AUD-199** — S2 — Model Confidence Set absent.
- **AUD-200** — S1 — Optional stopping non contrôlé.
- **AUD-201** — S2 — Minimum track record non calculé.
- **AUD-202** — S1 — Drift de coûts/fills/latence non surveillé.
- **AUD-203** — S2 — Change-point segmentation absente.
- **AUD-204** — S3 — Incertitude conforme non explorée.
- **AUD-205** — S3 — Génération automatique de features insuffisante.
- **AUD-206** — S1 — Régression symbolique non encadrée.
- **AUD-207** — S1 — Recherche génétique non comptée comme multiple testing.
- **AUD-208** — S2 — Complexité des formules non pénalisée.
- **AUD-209** — S3 — Qualité-diversité absente.
- **AUD-210** — S3 — Archive de niches absente.
- **AUD-211** — S1 — Agent générateur non quarantainé.
- **AUD-212** — S3 — Ordonnanceur non fondé sur information gain.
- **AUD-213** — S2 — Réserve de tests rares absente.
- **AUD-214** — S2 — Budgets de performance absents.
- **AUD-215** — S2 — Régression mémoire non détectée.
- **AUD-216** — S2 — Soak tests absents.
- **AUD-217** — S2 — Test double-clic simultané absent.
- **AUD-218** — S3 — Test antivirus/file-lock absent.
- **AUD-219** — S2 — Test locale/timezone insuffisant.
- **AUD-220** — S2 — Rapport ne publie pas encore la couverture combinatoire.

## AUD-221 → AUD-260 — Unification orchestrateurs & statistique correcte

- **AUD-221** — S1 — Orchestrateurs fragmentés.
- **AUD-222** — S1 — CMD officiel ne lance pas historical_analysis_suite.
- **AUD-223** — S1 — Espace officiel limité à 24 configurations.
- **AUD-224** — S1 — Paramètres non spécifiques aux familles.
- **AUD-225** — S1 — Fast screen et moteur canonique non unifiés.
- **AUD-226** — S2 — Recherche massive optionnelle et séparée.
- **AUD-227** — S1 — Mode multi-session absent du CMD officiel.
- **AUD-228** — S1 — Hash limité aux 64 premiers événements.
- **AUD-229** — S1 — CPCV actuelle incomplète.
- **AUD-230** — S1 — Purge des intervalles de labels absente.
- **AUD-231** — S1 — Reconstruction des chemins CPCV absente.
- **AUD-232** — S1 — PBO complète absente du chemin officiel.
- **AUD-233** — S1 — White Reality Check simplifié.
- **AUD-234** — S1 — Bootstrap IID inadapté aux dépendances temporelles.
- **AUD-235** — S1 — SPA/StepM/MCS absents du chemin officiel.
- **AUD-236** — S1 — Anti-overfit non visible dans lab_alpha.
- **AUD-237** — S2 — Placebo limité au signe IS.
- **AUD-238** — S1 — Stress de coûts partiellement heuristique.
- **AUD-239** — S1 — Calibration point-in-time des coûts absente.
- **AUD-240** — S1 — Equity réelle leader/vault potentiellement manquante.
- **AUD-241** — S1 — Pagination fills non prouvée E2E.
- **AUD-242** — S1 — Détection adresse agent/master non prouvée.
- **AUD-243** — S1 — Réconciliation reconnect WebSocket non prouvée.
- **AUD-244** — S1 — Preuve CI absente du HEAD audité.
- **AUD-245** — S1 — Installation editable CI non bloquante.
- **AUD-246** — S1 — Dépendances research CI non bloquantes.
- **AUD-247** — S1 — Suite Windows complète absente.
- **AUD-248** — S2 — Pas de WINDOWS_FULL_NIGHTLY.
- **AUD-249** — S1 — Pas de verdict POSITIVE_OR_NO_PROMOTION.
- **AUD-250** — S1 — Pas de borne basse nette obligatoire.
- **AUD-251** — S2 — Leave-one-session-out absent.
- **AUD-252** — S2 — Leave-one-wallet-out non généralisé.
- **AUD-253** — S2 — Leave-one-venue-out non généralisé.
- **AUD-254** — S1 — Drift coûts/fills pas intégré au verdict.
- **AUD-255** — S1 — Multiplicité des idées générées sous-comptée.
- **AUD-256** — S2 — Clones de stratégies non dédupliqués économiquement.
- **AUD-257** — S2 — Rapport ne compare pas tous les orchestrateurs.
- **AUD-258** — S1 — Mode maximum peut ignorer les optimiseurs absents.
- **AUD-259** — S1 — Résultat non prouvé identique après unification.
- **AUD-260** — S1 — Aucun protocole explicite pour le cas sans edge positif.

## AUD-261 → AUD-310 — Data Mesh multi-venue & multi-wallet

- **AUD-261** — S1 — dYdX limité à cinq marchés.
- **AUD-262** — S1 — Aucun subaccount dYdX par défaut.
- **AUD-263** — S1 — dYdX retourne succès sur indisponibilité.
- **AUD-264** — S1 — dYdX dépend du package legacy.
- **AUD-265** — S1 — Discovery dYdX absent.
- **AUD-266** — S2 — Scoring dYdX non raccordé.
- **AUD-267** — S1 — multi_venue flux externe bloqué (BLOCKED_EXTERNAL).
- **AUD-268** — S1 — Bybit non branché.
- **AUD-269** — S1 — OKX non branché.
- **AUD-270** — S2 — Coinbase non branché.
- **AUD-271** — S2 — Deribit non branché.
- **AUD-272** — S2 — Kraken Futures non branché.
- **AUD-273** — S1 — Binance WS E2E non prouvé.
- **AUD-274** — S1 — Cross-Venue deuxième jambe conceptuelle.
- **AUD-275** — S1 — Cadence Cross-Venue 60 s insuffisante.
- **AUD-276** — S1 — READY_MULTI_VENUE absent.
- **AUD-277** — S2 — Sources externes non REQUIRED.
- **AUD-278** — S1 — Data Mesh absent.
- **AUD-279** — S1 — Symbol master incomplet.
- **AUD-280** — S1 — Horloge multi-venue insuffisante.
- **AUD-281** — S2 — Drift absent.
- **AUD-282** — S2 — GMX absent.
- **AUD-283** — S3 — Nansen non intégré.
- **AUD-284** — S3 — Dune discovery absent.
- **AUD-285** — S1 — Entity resolution absent.
- **AUD-286** — S2 — Provenance labels absente.
- **AUD-287** — S1 — Wallet scoring multi-protocole absent.
- **AUD-288** — S2 — Cohortes wallets dynamiques absentes.
- **AUD-289** — S2 — Détection crowding multi-protocole absente.
- **AUD-290** — S3 — Glassnode PiT absent.
- **AUD-291** — S3 — DefiLlama régime absent.
- **AUD-292** — S2 — Source licensing registry absent.
- **AUD-293** — S3 — API cost registry absent.
- **AUD-294** — S1 — Source quality score absent.
- **AUD-295** — S1 — Source ablation absente.
- **AUD-296** — S2 — Source marginal value non mesurée.
- **AUD-297** — S1 — Données macro potentiellement utilisées à mauvaise fréquence.
- **AUD-298** — S1 — Données CEX privées potentiellement confondues avec publiques.
- **AUD-299** — S1 — Wallet CEX non observable potentiellement présenté comme copiable.
- **AUD-300** — S1 — Raw immutable multi-source absent.
- **AUD-301** — S2 — Partitionnement Parquet multi-source absent.
- **AUD-302** — S1 — Lineage multi-source incomplet.
- **AUD-303** — S1 — Replay multi-source absent.
- **AUD-304** — S1 — Point-in-time labels absent.
- **AUD-305** — S1 — Open interest unités non normalisées.
- **AUD-306** — S1 — Funding intervals non normalisés.
- **AUD-307** — S1 — Liquidation sides non normalisés.
- **AUD-308** — S2 — Options regime absent.
- **AUD-309** — S2 — Multi-protocol wallet consensus absent.
- **AUD-310** — S1 — Aucune preuve que plus de données améliore l'OOS.

## AUD-311 → AUD-390 — Bugs & durcissement (jumeaux de BUG-001→080)

- **AUD-311** — S1 — Recenser tous les BLOCKED_EXTERNAL dans un registre unique.
- **AUD-312** — S1 — Détecter les modules codés mais sans appelant.
- **AUD-313** — S1 — Éliminer les faux codes succès des collecteurs.
- **AUD-314** — S1 — Réduire les except Exception trop larges.
- **AUD-315** — S1 — Unifier les packages legacy et canonique.
- **AUD-316** — S2 — Détecter la dérive des fichiers de tâches statiques.
- **AUD-317** — S1 — Unifier tous les registres de collecteurs.
- **AUD-318** — S1 — Séparer liveness et progression des données.
- **AUD-319** — S1 — Ajouter last_useful_event_ts à chaque source.
- **AUD-320** — S1 — Créer READY_MULTI_VENUE et READY_WALLETS.
- **AUD-321** — S1 — Formaliser OPTIONAL/REQUIRED/DEGRADED par source.
- **AUD-322** — S2 — Définir des seuils stale par stream.
- **AUD-323** — S1 — Créer une Dead Letter Queue.
- **AUD-324** — S1 — Créer un registre de migrations de schéma.
- **AUD-325** — S1 — Garantir l'idempotence REST + WS.
- **AUD-326** — S1 — Corriger les collisions de snapshots dYdX à la milliseconde.
- **AUD-327** — S1 — Remplacer les floats critiques par Decimal/entiers quantifiés.
- **AUD-328** — S2 — Batcher les insertions SQLite.
- **AUD-329** — S2 — Réutiliser les connexions SQLite de façon sûre.
- **AUD-330** — S2 — Gérer les checkpoints WAL SQLite.
- **AUD-331** — S1 — Borner les tables raw JSON (rotation/rétention).
- **AUD-332** — S1 — Ajouter la backpressure.
- **AUD-333** — S1 — Ajouter le load shedding priorisé.
- **AUD-334** — S1 — Créer un quota disque par source.
- **AUD-335** — S1 — Créer un coordinateur global de rate limits.
- **AUD-336** — S1 — Ajouter un circuit breaker par endpoint.
- **AUD-337** — S2 — Empêcher les tempêtes de reconnexion.
- **AUD-338** — S2 — Distinguer reconnect réseau et resync carnet.
- **AUD-339** — S1 — Surveiller l'horloge système et NTP.
- **AUD-340** — S1 — Créer un registre de sémantique des timestamps.
- **AUD-341** — S1 — Créer un symbol master point-in-time.
- **AUD-342** — S1 — Normaliser contrats linéaires, inverses et multiplicateurs.
- **AUD-343** — S1 — Gérer USD/USDT/USDC avec risque de depeg.
- **AUD-344** — S1 — Normaliser tous les intervalles de funding.
- **AUD-345** — S1 — Normaliser les unités d'open interest.
- **AUD-346** — S1 — Normaliser le sens des liquidations.
- **AUD-347** — S1 — Normaliser le sens agressor/taker des trades.
- **AUD-348** — S1 — Créer un modèle de frais par niveau et compte paper.
- **AUD-349** — S1 — Versionner les méthodologies mark/index.
- **AUD-350** — S1 — Interdire les données révisées non point-in-time dans les backtests.
- **AUD-351** — S2 — Gérer l'expiration des caches payants.
- **AUD-352** — S1 — Interdire l'usage basse latence de Dune/Nansen.
- **AUD-353** — S1 — Réduire les faux merges d'entités.
- **AUD-354** — S2 — Détecter sybils et wallets miroirs.
- **AUD-355** — S1 — Séparer transferts et PnL sur tous les protocoles.
- **AUD-356** — S1 — Corriger le survivorship bias des wallets.
- **AUD-357** — S1 — Inclure les wallets liquidés dans les cohortes historiques.
- **AUD-358** — S1 — Mesurer la copyability cross-protocole.
- **AUD-359** — S2 — Mesurer le crowding multi-source.
- **AUD-360** — S1 — Filtrer spoofing, wash trades et quote flicker.
- **AUD-361** — S2 — Tester les pannes corrélées de sources.
- **AUD-362** — S1 — Pondérer le consensus par indépendance.
- **AUD-363** — S1 — Rendre la source ablation obligatoire.
- **AUD-364** — S1 — Calculer la valeur marginale nette des sources.
- **AUD-365** — S1 — Ajouter le lineage au niveau ligne/événement.
- **AUD-366** — S1 — Prouver l'immutabilité Bronze.
- **AUD-367** — S1 — Hasher les shards et partitions.
- **AUD-368** — S1 — Créer la parité live/replay par source.
- **AUD-369** — S1 — Éviter les doubles adaptateurs live/replay.
- **AUD-370** — S2 — Sortir les tests réseau du CI déterministe principal.
- **AUD-371** — S1 — Créer des golden packets officiels.
- **AUD-372** — S1 — Détecter les changements silencieux d'API.
- **AUD-373** — S1 — Pinner les versions et endpoints.
- **AUD-374** — S2 — Créer un registre licences, quotas et coûts.
- **AUD-375** — S1 — Limiter les secrets aux clés read-only de données.
- **AUD-376** — S2 — Ajouter une revue conformité/conditions d'utilisation.
- **AUD-377** — S1 — Créer un dashboard santé Data Mesh.
- **AUD-378** — S2 — Définir un SLA par source.
- **AUD-379** — S2 — Créer une checklist d'onboarding source.
- **AUD-380** — S2 — Créer une politique de retrait de source.
- **AUD-381** — S1 — Détecter les collecteurs doublons.
- **AUD-382** — S1 — Tester la correspondance registre ↔ lanceur ↔ superviseur.
- **AUD-383** — S2 — Empêcher le watchdog de masquer une panne récurrente.
- **AUD-384** — S1 — Interdire SUCCESS quand zéro donnée est produite.
- **AUD-385** — S1 — Ajouter un compteur d'événements utiles par consommateur.
- **AUD-386** — S1 — Quarantainer les champs inconnus au lieu de les ignorer.
- **AUD-387** — S1 — Interdire les zéros inventés pour champs manquants.
- **AUD-388** — S1 — Interdire le carry-forward silencieux des dernières valeurs.
- **AUD-389** — S2 — Rendre toutes les sélections aléatoires seedées.
- **AUD-390** — S2 — Attribuer CPU/RAM/disque/réseau par source.

---

# 2) TÂCHES DATA-001 → DATA-120 (Data Mesh — une par amélioration de la §297)

> Chaque tâche : implémenter réellement l'item + le raccorder au chemin officiel
> `source → Bronze → Silver → Gold → replay → stratégie → rapport`, avec heartbeat,
> qualité, couverture, erreurs, quotas, lineage. DONE seulement si appelable, testé,
> observable, read-only/paper, sans capacité fictive.

## dYdX (DATA-001 → DATA-020)

- **DATA-001** — Migrer le package legacy vers `src/hl_observer`.
- **DATA-002** — Supprimer le faux succès sur exception.
- **DATA-003** — Rendre l'échec non-zero.
- **DATA-004** — Distinguer OPTIONAL et REQUIRED.
- **DATA-005** — Augmenter l'univers au-delà de 5 marchés.
- **DATA-006** — Sélectionner les marchés dynamiquement.
- **DATA-007** — Suivre tous les marchés liquides compatibles.
- **DATA-008** — Ajouter candles.
- **DATA-009** — Ajouter positions REST.
- **DATA-010** — Ajouter fills REST.
- **DATA-011** — Ajouter transfers REST.
- **DATA-012** — Ajouter pagination.
- **DATA-013** — Ajouter discovery d'adresses.
- **DATA-014** — Ajouter subaccount registry.
- **DATA-015** — Ajouter parent subaccounts.
- **DATA-016** — Ajouter scoring.
- **DATA-017** — Ajouter shortlist.
- **DATA-018** — Ajouter replay.
- **DATA-019** — Ajouter E2E réseau contrôlé.
- **DATA-020** — Intégrer au Data Mesh.

## Binance (DATA-021 → DATA-035)

- **DATA-021** — Prouver WS depth réel.
- **DATA-022** — Prouver snapshot REST.
- **DATA-023** — Prouver resync.
- **DATA-024** — Ajouter bookTicker.
- **DATA-025** — Ajouter aggTrade.
- **DATA-026** — Ajouter mark price.
- **DATA-027** — Ajouter funding.
- **DATA-028** — Ajouter OI.
- **DATA-029** — Ajouter liquidations.
- **DATA-030** — Ajouter exchangeInfo.
- **DATA-031** — Ajouter symbol mapping.
- **DATA-032** — Mesurer clock skew.
- **DATA-033** — Heartbeat.
- **DATA-034** — Stockage brut.
- **DATA-035** — Replay exact.

## Bybit (DATA-036 → DATA-048)

- **DATA-036** — Créer connecteur public.
- **DATA-037** — Orderbook L1.
- **DATA-038** — Orderbook L50.
- **DATA-039** — Orderbook L200.
- **DATA-040** — Orderbook L1000 optionnel.
- **DATA-041** — Public trades.
- **DATA-042** — Ticker.
- **DATA-043** — Funding.
- **DATA-044** — OI.
- **DATA-045** — Liquidations.
- **DATA-046** — Utiliser `cts`.
- **DATA-047** — Gérer snapshot/delta.
- **DATA-048** — Intégrer au NBBO.

## OKX (DATA-049 → DATA-061)

- **DATA-049** — Créer connecteur.
- **DATA-050** — bbo-tbt.
- **DATA-051** — books5.
- **DATA-052** — books.
- **DATA-053** — seqId/prevSeqId.
- **DATA-054** — Trades.
- **DATA-055** — Funding.
- **DATA-056** — OI.
- **DATA-057** — Mark/index.
- **DATA-058** — Liquidations.
- **DATA-059** — Instruments updates.
- **DATA-060** — Service-upgrade reconnect.
- **DATA-061** — Replay.

## Coinbase (DATA-062 → DATA-071)

- **DATA-062** — Créer connecteur.
- **DATA-063** — level2.
- **DATA-064** — Market trades.
- **DATA-065** — Ticker.
- **DATA-066** — Candles.
- **DATA-067** — Status.
- **DATA-068** — Heartbeat.
- **DATA-069** — Sequence gap.
- **DATA-070** — USD/USDC mapping.
- **DATA-071** — Spot-perp lead-lag.

## Deribit / Kraken (DATA-072 → DATA-084)

- **DATA-072** — Deribit books.
- **DATA-073** — Deribit trades.
- **DATA-074** — Deribit ticker.
- **DATA-075** — Deribit OI.
- **DATA-076** — Deribit funding.
- **DATA-077** — Deribit IV.
- **DATA-078** — Deribit skew.
- **DATA-079** — Kraken book.
- **DATA-080** — Kraken trades.
- **DATA-081** — Kraken OI.
- **DATA-082** — Kraken liquidation volume.
- **DATA-083** — Kraken CVD.
- **DATA-084** — Kraken funding/basis.

## Protocoles wallets (DATA-085 → DATA-100)

- **DATA-085** — Drift Data API.
- **DATA-086** — Drift wallet discovery.
- **DATA-087** — Drift lifecycle.
- **DATA-088** — Drift funding payments.
- **DATA-089** — Drift liquidation history.
- **DATA-090** — GMX positions.
- **DATA-091** — GMX trades.
- **DATA-092** — GMX performance snapshots.
- **DATA-093** — GMX entity registry.
- **DATA-094** — Nansen labels.
- **DATA-095** — Nansen Smart Money.
- **DATA-096** — Nansen perp trades.
- **DATA-097** — Dune discovery queries.
- **DATA-098** — Dune cached results.
- **DATA-099** — Cross-protocol wallet identity.
- **DATA-100** — Multi-protocol scoring.

## Régime & gouvernance Data Mesh (DATA-101 → DATA-120)

- **DATA-101** — Glassnode PiT.
- **DATA-102** — Exchange netflows.
- **DATA-103** — Whale flows.
- **DATA-104** — Derivatives OI.
- **DATA-105** — DefiLlama stablecoins.
- **DATA-106** — DefiLlama perps volume.
- **DATA-107** — DefiLlama DEX volume.
- **DATA-108** — Source licensing registry.
- **DATA-109** — API cost registry.
- **DATA-110** — Quota registry.
- **DATA-111** — Quality registry.
- **DATA-112** — Time sync.
- **DATA-113** — Symbol master.
- **DATA-114** — Source lineage.
- **DATA-115** — Immutable bronze.
- **DATA-116** — Canonical silver.
- **DATA-117** — Feature gold.
- **DATA-118** — Multi-source replay.
- **DATA-119** — Source ablation.
- **DATA-120** — Positive-or-no-promotion verdict.

---

# 3) TÂCHES BUG-001 → BUG-080 (Bugs & durcissement — section 316)

> Chaque tâche : preuve du défaut → test rouge reproductible → correction du chemin
> canonique (pas de 2ᵉ moteur) → métriques + reason codes + fail-closed → tests ciblés
> + régression. DONE seulement si le test reproduisant le défaut passe et le comportement
> trompeur est devenu impossible.

- **BUG-001** — P0 — Recenser tous les BLOCKED_EXTERNAL dans un registre unique.
- **BUG-002** — P0 — Détecter les modules codés mais sans appelant.
- **BUG-003** — P0 — Éliminer les faux codes succès des collecteurs.
- **BUG-004** — P0 — Réduire les `except Exception` trop larges.
- **BUG-005** — P0 — Unifier les packages legacy et canonique.
- **BUG-006** — P1 — Détecter la dérive des fichiers de tâches statiques.
- **BUG-007** — P0 — Unifier tous les registres de collecteurs.
- **BUG-008** — P0 — Séparer liveness et progression des données.
- **BUG-009** — P0 — Ajouter `last_useful_event_ts` à chaque source.
- **BUG-010** — P0 — Créer READY_MULTI_VENUE et READY_WALLETS.
- **BUG-011** — P0 — Formaliser OPTIONAL/REQUIRED/DEGRADED par source.
- **BUG-012** — P1 — Définir des seuils stale par stream.
- **BUG-013** — P0 — Créer une Dead Letter Queue.
- **BUG-014** — P0 — Créer un registre de migrations de schéma.
- **BUG-015** — P0 — Garantir l'idempotence REST + WS.
- **BUG-016** — P0 — Corriger les collisions de snapshots dYdX à la milliseconde.
- **BUG-017** — P0 — Remplacer les floats critiques par Decimal ou entiers quantifiés.
- **BUG-018** — P1 — Batcher les insertions SQLite.
- **BUG-019** — P1 — Réutiliser les connexions SQLite de façon sûre.
- **BUG-020** — P1 — Gérer les checkpoints WAL SQLite.
- **BUG-021** — P0 — Borner les tables raw JSON.
- **BUG-022** — P0 — Ajouter la backpressure.
- **BUG-023** — P0 — Ajouter le load shedding priorisé.
- **BUG-024** — P0 — Créer un quota disque par source.
- **BUG-025** — P0 — Créer un coordinateur global de rate limits.
- **BUG-026** — P0 — Ajouter un circuit breaker par endpoint.
- **BUG-027** — P1 — Empêcher les tempêtes de reconnexion.
- **BUG-028** — P1 — Distinguer reconnect réseau et resync carnet.
- **BUG-029** — P0 — Surveiller l'horloge système et NTP.
- **BUG-030** — P0 — Créer un registre de sémantique des timestamps.
- **BUG-031** — P0 — Créer un symbol master point-in-time.
- **BUG-032** — P0 — Normaliser contrats linéaires, inverses et multiplicateurs.
- **BUG-033** — P0 — Gérer USD, USDT et USDC avec risque de depeg.
- **BUG-034** — P0 — Normaliser tous les intervalles de funding.
- **BUG-035** — P0 — Normaliser les unités d'open interest.
- **BUG-036** — P0 — Normaliser le sens des liquidations.
- **BUG-037** — P0 — Normaliser le sens agressor/taker des trades.
- **BUG-038** — P0 — Créer un modèle de frais par niveau et compte paper.
- **BUG-039** — P0 — Versionner les méthodologies mark/index.
- **BUG-040** — P0 — Interdire les données révisées non point-in-time dans les backtests.
- **BUG-041** — P1 — Gérer l'expiration des caches payants.
- **BUG-042** — P0 — Interdire l'usage basse latence de Dune/Nansen.
- **BUG-043** — P0 — Réduire les faux merges d'entités.
- **BUG-044** — P1 — Détecter sybils et wallets miroirs.
- **BUG-045** — P0 — Séparer transferts et PnL sur tous les protocoles.
- **BUG-046** — P0 — Corriger le survivorship bias des wallets.
- **BUG-047** — P0 — Inclure les wallets liquidés dans les cohortes historiques.
- **BUG-048** — P0 — Mesurer la copyability cross-protocole.
- **BUG-049** — P1 — Mesurer le crowding multi-source.
- **BUG-050** — P0 — Filtrer spoofing, wash trades et quote flicker.
- **BUG-051** — P1 — Tester les pannes corrélées de sources.
- **BUG-052** — P0 — Pondérer le consensus par indépendance.
- **BUG-053** — P0 — Rendre la source ablation obligatoire.
- **BUG-054** — P0 — Calculer la valeur marginale nette des sources.
- **BUG-055** — P0 — Ajouter le lineage au niveau ligne/événement.
- **BUG-056** — P0 — Prouver l'immutabilité Bronze.
- **BUG-057** — P0 — Hasher les shards et partitions.
- **BUG-058** — P0 — Créer la parité live/replay par source.
- **BUG-059** — P0 — Éviter les doubles adaptateurs live/replay.
- **BUG-060** — P1 — Sortir les tests réseau du CI déterministe principal.
- **BUG-061** — P0 — Créer des golden packets officiels.
- **BUG-062** — P0 — Détecter les changements silencieux d'API.
- **BUG-063** — P0 — Pinner les versions et endpoints.
- **BUG-064** — P1 — Créer un registre licences, quotas et coûts.
- **BUG-065** — P0 — Limiter les secrets aux clés read-only de données.
- **BUG-066** — P1 — Ajouter une revue conformité/conditions d'utilisation.
- **BUG-067** — P0 — Créer un dashboard santé Data Mesh.
- **BUG-068** — P1 — Définir un SLA par source.
- **BUG-069** — P1 — Créer une checklist d'onboarding source.
- **BUG-070** — P1 — Créer une politique de retrait de source.
- **BUG-071** — P0 — Détecter les collecteurs doublons.
- **BUG-072** — P0 — Tester la correspondance registre ↔ lanceur ↔ superviseur.
- **BUG-073** — P1 — Empêcher le watchdog de masquer une panne récurrente.
- **BUG-074** — P0 — Interdire SUCCESS quand zéro donnée est produite.
- **BUG-075** — P0 — Ajouter un compteur d'événements utiles par consommateur.
- **BUG-076** — P0 — Quarantainer les champs inconnus au lieu de les ignorer.
- **BUG-077** — P0 — Interdire les zéros inventés pour champs manquants.
- **BUG-078** — P0 — Interdire le carry-forward silencieux des dernières valeurs.
- **BUG-079** — P1 — Rendre toutes les sélections aléatoires seedées.
- **BUG-080** — P1 — Attribuer CPU/RAM/disque/réseau par source.

---

# 4) GATES FINAUX (à ne pas oublier — sections 321-323)

- Test `test_master_every_data_item_has_task.py` : 120 items §297 + DATA-001→120 + BUG-001→080, IDs uniques, présents dans le JSONL, pas de DONE sans preuve, correspondance AUD.
- Test `test_every_done_task_is_wired.py` : toute tâche DONE a un appelant CLI/orchestrateur/scheduler/superviseur/consommateur/artefact (un fichier isolé ne suffit pas).
- Registre machine : `runtime/research/claude_tasks/CLAUDE_TASKS.jsonl` + `CLAUDE_TASKS_LATEST.md` + `EVIDENCE/`.
- **Gate PnL** : même après TOUT, plus de données/tests/wallets ≠ PnL garanti. Verdict `VALIDATED_POSITIVE_PAPER` ou `NO_VALIDATED_EDGE_FOUND`.

*Fin du registre — 590 tâches (390 AUD + 120 DATA + 80 BUG). Aucune oubliée.*
