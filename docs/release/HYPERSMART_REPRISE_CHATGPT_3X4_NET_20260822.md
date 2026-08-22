# HyperSmart - reprise ChatGPT pour la preuve economique 3 x 4 USD net

Date de cloture locale : 2026-08-22  
Branche : `main` uniquement  
Mode : PAPER / READ-ONLY uniquement  
Push effectue par Codex : non  

## 1. Mission qui reste ouverte

Le chantier prioritaire n'est pas une refonte d'architecture. Il faut continuer les
iterations economiques existantes jusqu'a produire, separement et sans compensation
entre familles :

- Copy-Vault : au moins `+4,00 USD NET PROUVE` ;
- Lead-Lag : au moins `+4,00 USD NET PROUVE` ;
- Cross-Venue Dislocation : au moins `+4,00 USD NET PROUVE`.

Une preuve n'est admissible que si elle est reproductible, nette de frais, spread,
slippage, latence et capacite, entierement liquidable, sans position residuelle, avec
identites de trades uniques, separation temporelle sans lookahead, OOS, forward
post-freeze, placebo et provenance des donnees. Un verdict `KILL` ou `MORE_DATA` est
preferable a un faux PnL positif.

## 2. Etat Git exact au moment de la reprise

`main` local contient sept commits non pousses au-dessus de `origin/main` :

| SHA local | Objet |
|---|---|
| `a0796237` | Aligne le replay Lead-Lag sur sa fenetre causale |
| `98d1773d` | Fiabilise les preuves causales Copy-Vault et Lead-Lag |
| `aa2164ef` | Certifie les preuves economiques Cross-Venue |
| `e439afff` | Deduplique les preuves forward Copy-Vault |
| `fc32c8d2` | Aligne causalement les sources Lead-Lag |
| `fee8f59f` | Refuse les faux decoupages Cross-Venue |
| `767ae6c5` | Durcit la preuve economique Copy-Vault |

Avant le present document, le worktree etait propre et `origin/main` etait
`fda15f500942b0f8f178455c324d74aae9ee4814`.

## 3. Resultats economiques actuellement mesures

Les fichiers autoritatifs sont sous
`runtime/reports/economic_campaigns/`. Ils sont des preuves locales runtime et ne
doivent pas etre confondus avec une certification positive.

| Famille | Net mesure | Profit factor | Verdict honnete |
|---|---:|---:|---|
| Copy-Vault | `-9.84788766 USD` | `0.36868408` | `KILL` en l'etat |
| Lead-Lag | `-4.97316818 USD` | `0.03315975` | `KILL` en l'etat |
| Cross-Venue Dislocation v2 | `0.00 USD` | `0.0` | `MORE_DATA`, aucune preuve liquidable |

Ces chiffres ne satisfont aucun objectif `+4 USD`. Ils ne doivent jamais etre
arrondis, compenses entre familles ou presentes comme une promesse de profit.

### Copy-Vault

- 49 positions fermees.
- PnL brut : `+2.63498484 USD`.
- Frais : `6.61572389 USD`.
- Spread : `2.68786032 USD`.
- Cout de latence : `3.17928828 USD`.
- PnL net : `-9.84788766 USD`.
- OOS observe : `-1.8541894 USD`.
- Forward post-freeze admissible : absent.
- Taux de gain : `28.57 %`.
- Drawdown maximal : `10.68267398 USD`.
- Le cout total depasse largement l'edge brut.
- Une selection simple donnait un wallet apparemment positif, mais l'evaluation
  robuste l'a correctement tue : LCB negatif, concentration excessive, seulement
  cinq jours et aucun regime independant valide.
- La whitelist robuste contient donc zero leader promouvable. C'est une correction
  de faux positif, pas une regression.

### Lead-Lag

- Les sources BBO sont maintenant selectionnees par recouvrement temporel exact
  avec les fenetres de ticks marche.
- 36 fenetres marche ont ete identifiees.
- 194 shards BBO alignes sur 615 candidats, environ 1.21 Gio.
- 1 669 936 trades Binance ETH ont ete charges depuis 47 876 942 lignes.
- Le seuil fige a 20 bps donne zero choc.
- A 8 bps, deux chocs existent mais aucun candidat executable : le prochain carnet
  causal Hyperliquid arrive 2.295 s et 4.715 s apres le choc, au-dela de la limite
  executable de 750 ms.
- L'ancien OOS ne contient que quatre observations et son edge brut est voisin du
  cout reel de 9 bps : il n'est pas promouvable.
- La prochaine recherche doit expliquer la rarete du carnet causal, pas relacher
  retroactivement le seuil sur l'OOS.

### Cross-Venue Dislocation

- 208 timestamps atomiques certifies sont disponibles.
- Duree observee : environ 4 057 148 ms, soit 67.6 minutes.
- Duree encore necessaire pour un decoupage purge valide : environ
  13 944 682 ms, soit 3 h 52 min.
- Le replay refuse maintenant explicitement un split impossible avec
  `INSUFFICIENT_DURATION_FOR_PURGED_SPLITS`.
- Aucune position deux jambes entierement ouverte et fermee n'est prouvee.
- Le mecanisme v2 courant est `KILL`; une nouvelle hypothese materiellement
  differente doit etre formulee sur train uniquement apres collecte suffisante.

## 4. Corrections deja integrees

- Alignement causal des sources Lead-Lag.
- Fenetres de marche deduites des noms modernes et des ticks courants.
- Selection des shards BBO par intersection temporelle.
- Chargement borne du tape Binance dans les fenetres exactes.
- Refus des splits Cross-Venue impossibles au lieu de fabriquer des sous-ensembles.
- Conservation des details de positions residuelles Cross-Venue.
- Dedupe des identites forward Copy-Vault.
- Fusion filtree du tape `allMids` frais dans les marks Copy-Vault.
- Normalisation correcte des sens `B/S/BUY/SELL`.
- Conservation des regimes, metaorders, TWAP, bursts et entites.
- Evaluation robuste de la whitelist Copy-Vault via LCB, concentration, jours,
  regimes et votes independants.
- Tests de regression ciblant ces corrections.

## 5. Tests deja passes

- Bloc alignement Lead-Lag : 23 tests passes.
- Bloc Cross-Venue : 21 tests cibles et 48 tests elargis passes.
- Bloc Copy-Vault : 37 tests cibles et 85 tests elargis passes.
- `compileall` et controles de diff ont passe sur les blocs modifies.
- Un `PermissionError` Windows de nettoyage de `pytest-current` peut apparaitre en
  `atexit`; il n'a pas invalide les assertions, mais doit etre traite separement si
  recurrent.

## 6. Etat du runner Windows self-hosted

Verification locale realisee le 2026-08-22 :

- installation : `C:\actions-runner` presente ;
- service : `Running` ;
- demarrage : `Automatic` ;
- nom : `HyperSmart-FinalV1-DESKTOP-BMVQHGM` ;
- label dedie : `hypersmart-final-v1` ;
- labels complementaires : `self-hosted`, `Windows`, `X64`, `alina` ;
- workspace Actions : `C:\actions-runner\_work` ;
- donnees persistantes : `C:\HyperSmart-Runner-Data` ;
- depot de developpement separe : `C:\Users\flo\Desktop\Projet invest` ;
- Python persistant : version 3.14.2, chemin valide ;
- service et stockage ne sont pas dans le depot de developpement ;
- garde-fous mainnet/testnet/ordres reels : tous desactives ;
- workflow final reserve au depot exact, push sur `main`, acteur
  `Rapt0r06300`, hors fork, SHA courant et ajout d'un seul contrat JSON ;
- checkout sans credentials persistants ;
- aucune commande shell arbitraire dans le contrat ;
- artifacts publics limites aux preuves compactes allowlistees.

Le dernier smoke GitHub -> PC -> GitHub reussi est le run GitHub
`32412297593`, sur le SHA `aa6e9a02fd3a675ff6ea66c8ca0ba49ea292d688`.

Le runner n'est pas certifie pour le HEAD local non pousse. Le diagnostic local
signale exactement deux ecarts attendus :

1. `HEAD != origin/main`, parce que sept commits locaux doivent encore etre pousses
   par l'utilisateur ;
2. le manifeste prepare pointe sur l'ancien SHA `aa6e9a02...`.

Apres le push utilisateur, il faut rafraichir le manifeste/controle sur le nouveau
SHA, attendre les gates techniques vertes, puis lancer le smoke minimal avec ce SHA.
Ne jamais dire que le runner est parfait pour le nouveau HEAD avant ce smoke.

### Circuit autonome cible

Une fois les commits locaux pousses et le smoke du nouveau SHA valide, Codex n'est
pas requis pour la boucle d'execution normale :

1. ChatGPT ajoute sur `main` un unique contrat JSON conforme et sans commande libre ;
2. GitHub verifie depot, acteur, branche, commit de controle et SHA exact ;
3. GitHub route le job vers le label `hypersmart-final-v1` ;
4. le runner execute localement replays, backtests et audits avec les gros datasets
   conserves sur le PC ;
5. le runner publie heartbeat, progression, verdicts et preuves compactes ;
6. GitHub conserve l'artifact allowliste et le statut du SHA ;
7. ChatGPT lit ces preuves et prepare l'hypothese ou le contrat suivant.

Les datasets bruts ne quittent pas le PC. Le workflow refuse les PR, forks, acteurs
non autorises, SHA stale et champs de shell arbitraire. `workflow_dispatch` reste un
smoke manuel de secours; le chemin normal est l'ajout controle d'un fichier JSON sur
`main`. Cette autonomie porte sur l'execution et le reporting, pas sur la capacite a
garantir un PnL : la gate economique reste fail-closed.

## 7. Regles de travail obligatoires pour ChatGPT

- Travailler dans `C:\Users\flo\Desktop\Projet invest`.
- Utiliser `main` uniquement.
- Lire `AGENTS.md` et `docs/CURRENT_STATE.md` avant toute modification.
- Ne jamais reset, clean, checkout destructeur ou supprimer les donnees runtime.
- Ne jamais pousser sans demande explicite.
- Ne jamais executer d'ordre reel, de signature ou `/exchange`.
- Ne jamais modifier un seuil apres avoir observe validation/OOS pour embellir le
  resultat.
- Ne jamais reutiliser un trade entre train, validation, OOS et forward.
- Ne jamais compenser une famille perdante par une autre gagnante.
- Conserver les verdicts `KILL` et `MORE_DATA` lorsqu'ils sont justifies.
- Toute nouvelle hypothese doit avoir un identifiant, une formulation causale, un
  univers, une fenetre train et des couts figes avant validation.
- La boucle correcte est : mesure -> hypothese -> test train -> freeze -> validation
  -> OOS -> forward -> placebo -> reconciliation -> verdict.

## 8. Feuille de route executable en 120 etapes

### Phase A - Reprise sure et verite du HEAD

1. Lire integralement `AGENTS.md`.
2. Lire integralement `docs/CURRENT_STATE.md`.
3. Lire le present document de reprise.
4. Verifier `git status --short --branch`.
5. Verifier que la branche est `main`.
6. Comparer `HEAD` et `origin/main` sans reset.
7. Confirmer que les sept commits economiques sont presents apres le push.
8. Lister les fichiers modifies par ces sept commits.
9. Rejouer uniquement les tests cibles de ces fichiers.
10. Enregistrer le SHA exact utilise pour chaque nouvelle preuve.

### Phase B - Reconciliation des preuves existantes

11. Charger les trois scoreboards canoniques.
12. Verifier les empreintes des datasets de chaque scoreboard.
13. Recalculer les identites de trades et rechercher les doublons.
14. Verifier que chaque position ouverte a une fermeture explicite.
15. Verifier que chaque cout est exprime en USD et signe correctement.
16. Recalculer `gross - fees - spread - slippage - latency`.
17. Recalculer equity et drawdown depuis le ledger, pas depuis le dashboard.
18. Comparer les resultats bruts, les scoreboards et l'audit canonique.
19. Invalider toute preuve dont le dataset a change depuis son freeze.
20. Produire un tableau unique des raisons `KILL/MORE_DATA` actuelles.

### Phase C - Copy-Vault, diagnostic causal

21. Recharger les fills Copy-Vault valides sans adresse tronquee.
22. Recharger les marks seulement pour les coins et fenetres utiles.
23. Mesurer la couverture mark/fill par coin, wallet et jour.
24. Rejeter les episodes sans prix causal executable.
25. Regrouper correctement les fills en metaorders independants.
26. Mesurer la correlation intra-wallet pour eviter un faux grand `n`.
27. Mesurer la concentration PnL par trade, coin, jour et regime.
28. Recalculer le LCB net par wallet.
29. Exiger un nombre minimal de jours independants.
30. Exiger plusieurs regimes de marche observes.

### Phase D - Copy-Vault, nouvelle hypothese train-only

31. Formuler une nouvelle hypothese materiellement differente de la moyenne simple.
32. Limiter la recherche au train avant tout freeze.
33. Tester la copyabilite selon la taille du leader.
34. Tester la copyabilite selon la profondeur executable disponible.
35. Tester l'age du fill leader au moment observable.
36. Tester la deviation entre prix leader et prix copiable.
37. Tester la persistance du mouvement apres fill leader.
38. Tester consensus multi-wallet sans double compter les entites liees.
39. Tester filtrage par coin liquide sans regarder l'OOS.
40. Tester filtrage par regime causal connu a l'entree.

### Phase E - Copy-Vault, certification

41. Choisir la regle uniquement sur train.
42. Figer tous les parametres et couts.
43. Hasher le freeze et le dataset.
44. Executer validation une seule fois.
45. Tuer l'hypothese si validation nette est negative ou concentree.
46. Si validation passe, executer OOS une seule fois.
47. Exiger liquidabilite et identites de trades completes en OOS.
48. Executer placebo direction, temps et wallet.
49. Collecter un forward strictement posterieur au freeze.
50. Certifier Copy-Vault seulement si toutes les gates donnent au moins +4 USD net.

### Phase F - Lead-Lag, qualite des sources

51. Inspecter les deux chocs 8 bps deja observes timestamp par timestamp.
52. Determiner si le carnet manquant vient d'un gap collecte ou d'une vraie absence.
53. Comparer timestamps exchange, reception et ecriture.
54. Mesurer latence, jitter, gaps, doublons et reconnexions par source.
55. Verifier snapshot puis incrementaux avant d'utiliser un carnet.
56. Refuser carnet croise, stale ou non monotone.
57. Mesurer la cadence reelle du BBO Hyperliquid autour des chocs.
58. Verifier que les shards selectionnes couvrent les memes fenetres que le tape.
59. Ne pas remplacer un BBO executable par `allMids`.
60. Produire un rapport de couverture causale par milliseconde.

### Phase G - Lead-Lag, hypotheses train-only

61. Definir un train temporel pur avant toute grille.
62. Rechercher les chocs sur plusieurs actifs sources liquides, pas ETH seulement.
63. Associer chaque actif source au marche Hyperliquid correspondant.
64. Tester taker uniquement avec ask/bid reel et cout complet.
65. Tester maker uniquement avec queue et consommation publique mesurables.
66. Tester horizons causaux dans train sans toucher validation/OOS.
67. Tester seuils de choc dans train et corriger le multiple testing.
68. Tester direction continuation et controle inverse comme hypotheses separees.
69. Mesurer la capacite par profondeur disponible.
70. Exiger un minimum de chocs independants et plusieurs jours.

### Phase H - Lead-Lag, freeze et preuve

71. Selectionner au plus une hypothese principale depuis train.
72. Figer source, coin, seuil, fenetre, latence, execution et sortie.
73. Hasher le freeze et la provenance.
74. Executer validation sans recalibrage.
75. Tuer si le brut ne depasse pas clairement tous les couts.
76. Executer OOS une seule fois si validation passe.
77. Executer placebo temporel, symbole et direction.
78. Mesurer un forward post-freeze sur flux frais.
79. Reconciler chaque fill et chaque cout au ledger.
80. Certifier Lead-Lag seulement si le net eligible separe atteint +4 USD.

### Phase I - Cross-Venue, collecte necessaire

81. Mesurer la nouvelle duree de `runtime/data/carnet_venues.jsonl`.
82. Verifier que les deux venues sont synchronisees sur chaque ligne candidate.
83. Verifier provenance, timestamp exchange et timestamp reception.
84. Continuer la collecte jusqu'a depasser le minimum purge avec marge.
85. Refuser tout split dont la duree effective reste insuffisante.
86. Mesurer gaps et staleness par venue.
87. Construire des BBO executables et non des mids decoratifs.
88. Verifier les tailles disponibles sur les deux jambes.
89. Verifier la compatibilite des symboles, multiplicateurs et devises.
90. Verifier que dYdX reste dormant si le scope actif est Hyperliquid-only.

### Phase J - Cross-Venue, nouvelle hypothese

91. Ne pas ressusciter le mecanisme v2 tue.
92. Formuler une hypothese v3 materiellement differente sur train.
93. Distinguer dislocation de prix, basis, funding et lead-lag cross-venue.
94. Choisir une seule mecanique economique testable.
95. Simuler l'ouverture atomique des deux jambes.
96. Refuser si une seule jambe est remplissable.
97. Modeliser latence et mouvement entre les deux jambes.
98. Modeliser fees, spread, slippage et funding des deux venues.
99. Dimensionner par la jambe la moins liquide.
100. Fermer explicitement les deux jambes et verifier position nette zero.

### Phase K - Cross-Venue, walk-forward et preuve

101. Definir train, purge, embargo, validation et OOS par temps.
102. Figer les parametres avant validation.
103. Executer validation sans changer seuil ni sens.
104. Tuer l'hypothese si validation ne couvre pas les couts.
105. Executer OOS une seule fois si validation passe.
106. Executer controle inverse et placebo de timestamps.
107. Verifier aucune position residuelle cachee.
108. Collecter forward post-freeze.
109. Reconciler le ledger deux jambes.
110. Certifier Cross-Venue seulement si le net eligible separe atteint +4 USD.

### Phase L - Cloture 3 sur 3 et runner

111. Relancer les trois campagnes canoniques au meme SHA.
112. Regenerer les trois scoreboards depuis leurs ledgers.
113. Lancer l'audit de preuve economique canonique.
114. Confirmer qu'aucun trade n'apparait dans deux segments ou familles.
115. Confirmer que les trois positions finales sont toutes plates.
116. Lancer les tests cibles, puis la suite complete si les ressources le permettent.
117. Lancer les audits safety/read-only et prouver zero execution reelle.
118. Apres push, rafraichir le runner sur le SHA exact et reexecuter le smoke minimal.
119. Ajouter ensuite un unique contrat JSON de certification dans un commit separe.
120. Ne publier `3/3` que si la gate machine certifie separement les trois +4 USD net.

## 9. Commandes de reprise utiles

Ces commandes doivent etre relues dans le code avant execution si leur interface a
change :

```powershell
cd 'C:\Users\flo\Desktop\Projet invest'
git status --short --branch
git log -10 --oneline --decorate
python -m pytest -q tests/test_lead_lag_source_alignment.py tests/test_dataset_economic_source_wiring.py
python -m pytest -q tests/test_ecrire_copy_whitelist.py tests/test_wallet_copy_edge.py tests/test_marks_source.py
python -m pytest -q tests/test_cross_venue_economic_provenance.py tests/test_economic_campaigns.py
python tools/run_economic_objective_campaigns.py
python tools/export_economic_family_scoreboards.py
python tools/audit_economic_objectives.py
python -m hl_observer.cli --safety-check
```

Pour le runner, apres que tous les commits locaux ont ete pousses par l'utilisateur :

```powershell
cd 'C:\Users\flo\Desktop\Projet invest'
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\tools\VERIFIER_ALINA_RUNNER_WINDOWS.ps1
```

Si le diagnostic indique seulement un manifeste SHA obsolete, utiliser le mode de
rafraichissement documente dans `docs/ALINA_SELF_HOSTED_RUNNER.md`; ne jamais
reinstaller ou deregistrer le runner a l'aveugle.

## 10. Prochaine action exacte

La prochaine action technique est Lead-Lag : autopsier les deux chocs 8 bps et
prouver si l'absence de carnet executable sous 750 ms vient d'un gap de collecte ou
du marche reel. Ensuite seulement, construire une exploration train-only multi-actif
avec couts complets. En parallele, laisser Cross-Venue collecter au moins 3 h 52 min
supplementaires avant tout nouveau split. Copy-Vault ne doit pas etre relance avec la
whitelist simple : aucune selection robuste n'est actuellement promouvable.

## 11. Definition de fin

Le travail est termine uniquement lorsque les trois familles ont chacune une preuve
canonique distincte `LIQUIDATABLE_NET >= 4.00 USD`, avec OOS et forward post-freeze,
et que le runner execute cette certification sur le SHA exact de `main`. Tant que ce
n'est pas vrai, le verdict reste `NON ATTEINT`, meme si un sous-ensemble, un train ou
un graphique affiche ponctuellement un PnL positif.
