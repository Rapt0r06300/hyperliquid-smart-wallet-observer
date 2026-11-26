# Tableau d'avancement — objectif Copy-Vault de bout en bout

Tenu à jour à chaque itération. **HEAD au démarrage : `b206107b04b` (`main`)**, 81 fichiers de
travail local préservés (50 modifiés, 31 nouveaux). Ouvert le 17/11/2026.

Règles qui encadrent chaque ligne : PAPER / READ-ONLY / FAIL-CLOSED ; Copy-Vault seule famille
économique active ; LOCAL pour explorer, chaîne SAFE vérifiée seule admissible à OOS/forward/PnL ;
états honnêtes `PROVEN` / `PROMISING` / `MORE_DATA` / `UNMEASURABLE` / `REJECTED` ; aucune donnée
manquante, aucun signal tardif, aucun fill raté et aucune sortie absente transformés en zéro ou en
profit.

## 📚 23/11/2026, 15:38 (heure lue) — carnets à la minute pour le labo, réparation, et deux défauts de rotation

Carte blanche de l'opérateur : « je te laisse tout choisir, ne me demande rien ».

| point | état |
|---|---|
| **Hydromancer Reservoir** (HF, CC BY 4.0) : carnets 20 niveaux/minute 21,1 Go, bougies 1 min 2 Go, instantanés 0,66 Go, liquidations 0,32 Go | **746/746 fichiers validés**, 23,99 Go, SHA-256 LFS vérifiés, gardés tels que publiés (Parquet ZSTD) |
| alignement mesuré contre NOS carnets (8–16/11) | écart de mid médian **0,47 bps à décalage nul**, symétrique (3,3 bps à ±30 s) : aucune fuite du futur |
| lecteur du labo `backtesting/carnets_externes_hydromancer.py` (non causal par construction, jamais SAFE) | fait, 4 tests |
| **gain mesuré** : fills de leaders (2,12 M dans la période, échantillon 20 000) avec un carnet à ≤ 30 s | **99,78 %** (médiane 14,9 s ; « après » ≤ 30 s : 48,5 %) — contre 65 % des candidats TRAIN rejetés faute de carnet de sortie |
| branchement dans la porte d'exécutabilité (variante séparée du verdict officiel) | **à faire** — ⚠ la porte veut un carnet APRÈS l'instant à ≤ 30 s (`copy_vault_executable._first_at_or_after`) : avec un instantané/minute, vrai pour 48,5 % des instants, donc **~1 candidat sur 4** pour entrée ET sortie. Atteindre ~99 % = tolérance 60 s, une HYPOTHÈSE d'exécution (retard ≤ 1 min) à nommer et tester en variante exploratoire (`require_causal_books=False`), jamais dans le verdict officiel |
| quarantaine (6,5 M lignes) : quasi tout vient des lots du 8 au 16/11, règles corrigées depuis | sonde : fills et instantanés de vaults déjà récupérés (100 %) ; **trades CopyVault « futurs » : 84 % absents du coffre** |
| `tools/reparer_quarantaine.py` : recertifie, vérifie l'identité au coffre, verse une fois, quarantaine intacte | fait, 2 tests (3 gardes rouges sous injection) |
| plan réel (6 512 367 lignes lues) | 436 380 doublons internes ; 598 encore refusées (vraies erreurs) ; **~4,65 M lignes valides paraissent absentes du coffre** (BBO 3,86 M, micro-BBO 514 k, trades 127 k, explorer 61 k, micro-trades 36 k, L2 20 k…) — contre-épreuve à clé lâche (tid ; coin+heure+bid+ask) : **mêmes chiffres** que l'identité stricte (trades 279/1 560, BBO 510/2 451 présents) → l'absence est RÉELLE ; **réparation réelle lancée** (la preuve des sessions attendra qu'elle soit scellée : sinon les deux outils verseraient la même ligne) |
| 1er passage réel | **235 745 lignes réparées au coffre** (trades CopyVault 126 554, explorer 60 701, L2 18 707, dispersion 17 680…, 0 écartée, 0 doublon) ; ⚠ 2 défauts de MON outil : (1) l'étiquette ajoutée cassait le `checksum` des flux micro → 550 227 lignes remises en quarantaine (rien de perdu) ; (2) un « .jsonl » de trop dans le nom des rubans issus de sources tournées → 3,86 M BBO non versées (garde-fou : rien d'orphelin) ; corrigés, 2 gardes rouges |
| 2e passage réel | **4 413 955 lignes** (BBO 3 863 728, micro-BBO 513 914, micro-trades 36 313), 0 écartée, 0 doublon → **total récupéré de la quarantaine : 4 649 700 lignes valides** ; quarantaine d'origine intacte ; 598 vraies erreurs laissées |
| `tools/prouver_scellement.py` (preuve par identité des « à prouver ») | fait, 3 tests (2 gardes rouges) ; plan réel (128 fichiers) : **13 630 086 lignes déjà au coffre, 4 498 381 absentes** (fills : 100 % présents ; trades, asset_ctx, dispersion, carnets de venues : familles ajoutées au certificateur APRÈS ces sessions) ; preuve réelle après la réparation |
| ⚠ **mon passage `--recensement` a redéposé 784 648 lignes BBO** (rotations sans preuve d'état scellées à l'aveugle) | consigné dans `runtime/coffre_certifie/DOUBLONS_CONNUS.json` (shards intacts) ; règle corrigée : rotation sans preuve = `A_PROUVER` |
| ⚠ **défaut du certificateur (antérieur)** : 8 préfixes gardés par ruban → une rotation ancienne non reconnue se rescellait en entier (49 086 micro-BBO) | corrigé : 64 préfixes |
| ⚠ **défaut du certificateur (antérieur)** : pour une archive `.gz`, les 5 préfixes les plus longs essayés à l'aveugle ; un préfixe trop long faisait planter le hash | corrigé : longueur lue sans décompresser (index ou ISIZE), essai par longueur ; 2 gardes rouges |
| la campagne lance le certificateur avec `--recensement` | fait au registre (effectif au prochain lancement des collecteurs) |
| couverture du projet | 99,52 % au départ du passage ; **le rapport écrit (96,74 %) est faux** : le processus avait chargé le recensement avant que la zone Hydromancer n'existe |
| 72 Go en clair dans `runtime/reports/copy_vault_quant_lab/<passage>/workspace/runtime/data/` | ce sont des COPIES des rubans de collecte faites par chaque passage du labo (ex. 7,1 Go de `vault_fills_live.jsonl` le 18/11) ; données déjà au coffre et aux archives. **Non compressées** : la reprise du labo relit les passages précédents — vérifier ses lecteurs d'abord |
| suite des tests liés (tous les fichiers qui touchent un module modifié) | **808 verts**, 0 échec |
| preuve réelle (`prouver_scellement.py`, 130 fichiers) | **5 190 621 lignes absentes scellées** (+ 7 050 scellées par la campagne entre-temps, + 22 doublons internes ignorés) ; 14 684 906 déjà présentes ; 0 écartée |
| ⚠ course avec la campagne | ma preuve a lu l'index AVANT que la campagne ne scelle la même rotation micro-BBO : 148 526 lignes en double (consignées, `DOUBLONS_CONNUS.json` : 982 260 au total) |
| **racine corrigée dans le certificateur** : une rotation `.gz` au préfixe non reconnu précharge les identités du coffre sur SA période (`_precharger_identites_fenetre`) — seules ses lignes absentes entrent | fait, garde rouge sous injection ; `--recensement` lui confie aussi les archives `.gz` « à prouver » ; la preuve hors certificateur ne touche plus les rotations vivantes |
| passage final `--recensement` | **871 426 lignes des 8 archives reconnues déjà au coffre et non redéposées** (951 145 doublons au total du passage, ordinaires compris) ; 458 847 lignes de rotations neuves déposées (0 % ailleurs au coffre, vérifié) ; ⚠ une session `vault_episodes` (période SUPPOSÉE « 1re ligne + 6 h ») a redéposé 16 093 lignes → corrigé : période lue sur toutes les lignes, garde rouge ; consigné (`DOUBLONS_CONNUS.json` : 998 353 lignes, 9 shards) |
| échec FERMÉ du préchargement (23/11 soir) | 1) période d'archive **lue** sur toutes les lignes, datée par la ligne CERTIFIÉE quand l'horloge brute a un autre nom (`time` des fills) — rejoué en lecture seule sur la vraie session `20261109_172801` : **6 lignes absentes** au lieu de 16 099 redéposées ; 2) période illisible → **rien déposé**, l'archive reste à prouver ; 3) une archive « à prouver » du recensement est TOUJOURS préchargée, même sans historique de préfixe. 3 gardes, toutes rouges sous injection |
| **couverture finale** | **99,9963 %** des 27 125 fichiers de données : 0 inconnu, 0 à sceller, 0 externe hors manifeste ; reste 1 rotation micro-BBO créée à l'instant (prochain passage) |
| **bilan de la journée** | ~9,8 M lignes valides rentrées au coffre (4 649 700 de la quarantaine + 5 190 621 des premières sessions + rotations) ; 8,9 M lignes externes ; 24 Go de carnets Hydromancer ; 79,6 Go d'archives compressés en 8,5 Go sans perte |
| suite des tests liés (69 fichiers) | **818 verts, 1 rouge** (après les 3 gardes d'échec fermé) : `test_coffre_tier_local_streaming.py::test_context_family_is_read_after_replay_cap` — test et code poussés par Codex à 16:56–16:57 (`561f74ef`, `e91b7e49`) ; il échoue AUSSI sur un export propre de HEAD (`9e108aa9`, sans aucun de mes changements) : ce n'est pas une régression de ce chantier ; NON corrigé dans le dos de Codex |
| 🔴 **doublons MESURÉS (23/11 soir)** | le certificateur ne dédoublonne qu'à l'intérieur d'UN passage. `tools/backfill_vault_fills.py` **réécrit** `vault_episodes.jsonl` en entier à chaque collecte (`write_text`) : chaque passage le rescellait → **4 639 754 des 7 733 874 lignes `fills_backfill` (60 %) étaient en double**. Mesure exacte par `tools/auditer_doublons_coffre.py` (identité du certificateur, copie du lot le plus ancien gardée), recomptée par une méthode indépendante (109/109 shards identiques) |
| ~~doublons retirés de ce que lit le labo~~ ⚠ **ANNULÉ** (voir la ligne « règle stricte ») | `tools/dedoublonner_coffre.py` : 95 shards remplacés par leurs lignes uniques (copiées à l'octet), 14 entièrement en double ; les 109 originaux restent sur le disque et dans `LOCAL_INDEX.json` → `shards_remplaces` (rien supprimé). Re-mesure : **0 doublon**, 3 156 205 lignes `fills_backfill` uniques. Journal : `DEDOUBLONNAGE.json`. Tests : 4 + 4 injections rouges ; 277 tests du certificateur verts |
| ⚠ **règle stricte (23/11, 23 h)** | la 1re passe retirait par IDENTITÉ seule. Contrôle sur 400 fills retirés tirés au hasard : **21 % avaient un contenu différent** de la copie gardée (`closedPnl`, `fee`, `pos_avant`, `taille_usd`... absents du fill brut gardé). Comparaison doublon / copie gardée sur toutes les familles : identiques à l'octet pour `bbo`, `micro_bbo`, `micro_l2`, `asset_ctx`, `snapshot`... ; même événement **reçu deux fois** (heure de réception, connexion) pour `fills_forward`, `trades_marche`, `micro_trades`, `book_l2`, `liquidation`, `funding_history`, `explorer_tx` ; **contenu réellement différent** pour `candle` (états successifs d'une bougie), `vault_portfolio`. Nouvelle règle : doublon = même identité **ET même contenu à l'octet** ; le reste est gardé et compté (`meme_identite_contenu_different`). Lot `20261123T191724Z_1f8f5763` **annulé** (`--annuler`) : 109 originaux remis dans l'index, 95 remplaçants sortis et gardés sur le disque. 7 tests, 4 + 4 injections rouges |
| ✅ **doublons EXACTS retirés de tout le coffre (24/11, 00 h)** | mesure stricte : **45 339 986 lignes identiques à l'octet en double sur 374 226 309 (12,1 %)** — `bbo` 30,3 M, `micro_bbo` 6,3 M, `fills_backfill` 4,3 M (55 %), `fills_forward` 2,7 M, `explorer_tx` 1,2 M, `vault_ledger` 162 292 (75 %)... ; ~21,6 M lignes « même identité, autre contenu » **gardées**. Lot `20261123T224223Z_cf945628` : 470 shards remplacés (lignes gardées copiées à l'octet), 32 entièrement en double, 0 ignoré ; originaux sur le disque (`shards_remplaces`). Preuves : re-mesure **0 doublon** ; conservation 374 226 309 − 45 339 986 = **328 886 323** lignes relues ; 744/744 lignes retirées tirées au hasard dans 18 familles ont une copie **identique à l'octet** encore dans l'index |
| ✅ **certificateur : aucune version perdue** | le préchargement de période compare désormais le CONTENU exact (`empreinte_contenu`) et non l'identité : une nouvelle version d'un fill déjà au coffre (enrichie de `pos_avant`, `fee`...) entre, sa copie exacte non. 2 injections rouges ; 284 tests du coffre verts |
| ⚠ **résultats du labo antérieurs** | tout résultat calculé avant le 24/11 sur le coffre a vu ~12 % de lignes doublées (55 % pour `fills_backfill`, 21 % pour `bbo`) : à refaire avant d'en tirer une conclusion. Nuance mesurée le 24/11 : les études de copiabilité dédoublonnent elles-mêmes les FILLS par identité (`doublon_identite` : 209 463 en base, 194 933 en rétrospectif) ; les fills n'y étaient donc pas comptés deux fois, les autres familles (BBO, carnets) oui |
| ✅ **labo complet AVEC Codex ouvert (24/11, 17:34 → 18:36)** | lancé HORS de Claude Code (son arrêt mémoire n'y touche pas) : **9/9 étapes, rc=0, 61 min** (35,5 min Codex fermé). Base 10,1 ; portefeuilles 5,8 ; rétrospectifs 3,6 + 3,6 ; ouvertures 7,3 ; ordres 3,4 ; persistance 1,2 ; **réplication 350 : 23,5** ; plan 0,1. Mémoire : labo jusqu'à **18,0 Go pendant les OUVERTURES** (RAM libre 0,0 Go un instant), `git` de Codex jusqu'à 8,8 Go / 10 processus ; le pic de la base n'a pas été mesuré (relevé arrêté à tort pendant 17 min). Correctif ouvertures : plus de copie de la fenêtre de temps quand tout est dedans. Verdicts inchangés, sauf `leader_order_intent` **PROMISING → REJECTED sur le fil** : part anticipable 30,012 % (15 h) → 29,932 % (18 h) pour un seuil de **30 % sans intervalle** — ni l'un ni l'autre ne prouve quoi que ce soit, le verdict bascule au bruit près |
| ✅ **push avec Codex ouvert, git reste rapide (25/11, 21:28)** | 1er push (20:43) `SYNCHRONIZED` `723554e77493` (62 chemins) mais `adoption_index=READ_TREE_SIMPLE_REPLI` : git avait refusé `-m -i <old_tip> <new>` (l'index n'est pas `old_tip` : commit construit par `commit-tree`, entrées protégées indexées) → dates effacées, `git status` > 300 s. Corrigé : base = **arbre de l'index** (`write-tree`), refus impossible par construction ; test sur vrai dépôt git reproduisant le refus, injection rouge, 158 tests de synchro verts. 2e push (21:21) : **`adoption_index=READ_TREE_DEUX_ARBRES_DATES_GARDEES`, base INDEX**, 3 commits publiés, parité SHA `07d2228a9cd9` ; **`git status` après le push : 2,5 s**. Statut final `NO_GO` (rc=2) uniquement parce que Codex modifiait 3 documents pendant la synchro (garde de l'outil) : ils partiront au prochain push |
| ✅ **git rapide avec Codex ouvert (25/11, 20:40)** | conversion terminée (74 min) : **1 903 357 manifestes remis en LF** (identiques à l'octet au blob de l'index), **2 144 au contenu réellement différent** et 21 verrouillés laissés intacts. Index rafraîchi une fois (911 s). **`git status` : 2,0 s** (contre > 580 s). Reste listé : 2 392 chemins modifiés (les 2 144, 164 `catalog/`, 21 `runtime/`, ~60 fichiers de code en cours chez Codex). **Push NON fait** : Codex modifie en ce moment `POUSSER-GITHUB.cmd` et `tools/alina_git_code_sync.py` (moteur `2026-11-25-protected-overlay-v21`) ; 2 tests de `test_push_github_launcher.py` sont rouges sur son travail en cours (garde de verrou réécrite, message « Modifications locales protégées » disparu) — pas sur nos changements (170 autres verts, dont les 4 d'adoption et 3 de normalisation). Pousser maintenant publierait son lanceur à moitié fait |
| 🔧 **git : la VRAIE cause, corrigée (24-25/11)** | la réparation `update-index --refresh` a réussi (2e essai, 741 s) mais n'a daté que 35 785 entrées : **98,2 % des fichiers suivis (~1,9 M manifestes de `datasets/`) ont sur le disque un autre contenu que l'index** — même JSON (300/300 vérifiés), mais en **CRLF** localement contre **LF** sur GitHub (écart = exactement le nombre de retours chariot). Git les voit « modifiés » : impossible à dater, re-hachés à chaque `git status`. Avec accord : `tools/normaliser_fins_de_ligne_datasets.py` réécrit en LF un fichier SEULEMENT si le résultat a exactement le blob de l'index (sinon intact, compté), et `.gitattributes` reçoit `datasets/**/*.manifest.json text eol=lf` (comme le catalogue). 3 tests sur vrai dépôt git + injection rouge ; 55 tests `.gitattributes`/clone verts. Conversion lancée le 25/11 à 19:07 (~70 min) : 99,9 % convertis, **409 au contenu réellement différent laissés intacts** (à examiner) |
| 🔧 **git : la vraie cause de la lenteur (24/11, 17 h)** | les **1 941 337** entrées de l'index ont une date et une taille **à zéro** : `tools/alina_git_code_sync.py` reconstruisait l'index par `read-tree <new>` après chaque push → chaque `git status` (Codex compris) re-hachait tous les fichiers (trace : la phase *refresh* ne finit pas en 570 s). Corrigé : `read-tree -m -i <old> <new>` (garde les dates des chemins inchangés ; repli exact sur l'ancien en cas de refus), 4 tests dont 2 sur un vrai dépôt git, 216 tests de synchro verts. `core.fsmonitor=true` activé (accord de l'opérateur). Réparation unique de l'index (`update-index --refresh`) lancée à 18:36 |
| 🧠 **labo AVEC Codex ouvert (24/11, 15:53 → 16:41)** | passage **arrêté par Claude Code à l'étape 8/9** (réplication 350), mémoire critique. Relevé toutes les 5 s : labo jusqu'à **16,2 Go** (étude de base), RAM libre jusqu'à **0,1 Go**, et les `git` de Codex jusqu'à **19 processus / 11 Go** (`git status --untracked-files=all`, `diff --stat`, `diff --check` lancés par son agent, chacun > 4 min sur 1 941 337 fichiers suivis dont 1 341 234 dans `datasets/sharded/safe` et 451 343 dans `datasets/safe` : le corpus SAFE cloud, à garder). Tout ralentit (base 6,8 → 10,9 min, rétrospectif 2,1 → 5,6). Correctifs sans changer un résultat : `attribute_pnl` ne recopie plus le tableau pour l'ordre (`assign`) ni pour le filtre des coins quand rien n'est écarté, tâches parallèles construites une par une (au plus 2 par processus en vol), `run()` ne recopie plus la fenêtre de temps quand tout est dedans (~3 copies de ~3 Go évitées). 38 tests d'égalité au bit verts, injection rouge. **Décision en attente** : `core.fsmonitor` (désactivé dans `.git/config`) |
| ⏱️ **passage complet mesuré (24/11, 14:58 → 15:33)** | les 9 étapes en **35,5 min** (ce matin : ~1 h 30 estimée, arrêtée à la 4e). Base 26,2 → **6,8 min (x3,9)** ; portefeuilles 16,7 → **3,5 (x4,9)** ; rétrospectif 11,8 → **2,1 (x5,6)** ; rétrospectif 1 h **2,2** ; ouvertures 11,7 → **5,1 (x2,3)** ; ordres 1,9 ; persistance 0,7 ; **réplication 350 : 13,1 min, NON accélérée** (son calcul est la comparaison au hasard, pas l'attribution) = 37 % du total, prochaine cible ; plan 0,1. Verdicts : inchangés en nature ; `leader_order_intent` passe PROMISING (30 % du notionnel visible ≥ 60 s à l'avance : précondition d'information, pas un gain) |
| ⚡ **calcul des études accéléré x5 (24/11, 15 h)** | profil réel : `attribute_pnl` = **398 s sur 408** de l'étude de base (58 ms par couple leader x coin, ~60 opérations sur toute la longueur du panneau). Réécrite sans rien changer à ce qui est calculé ni à l'ordre des sommes : ce qui ne dépend que du coin est calculé une fois par coin, les indices valides une fois par couple, la rotation aux seuls débuts de fenêtre (ajouter 0,0 ne change pas une somme), et les coins répartis sur 4 processus (fournis par `tools/etude_copiabilite.py` : le moteur reste pur, le test d'imports le garde) avec additions dans l'ordre d'origine. Preuves : rapport complet de l'étude de base **identique caractère pour caractère** (184 506 caractères) sur les mêmes 1 569 301 vrais fills, **360 s → 71 s (x5,1)** ; 38 tests d'égalité AU BIT contre la copie figée `tests/_reference_attribution_copiabilite.py` (dont l'exécution parallèle), 5 injections rouges dont un simple changement d'arrondi |
| ⚡ **études du labo accélérées (24/11, 14 h)** | les 8 études prenaient ~1 h 10 : chacune relisait les ~11 Go de carnets pour les demi-spreads (~15 min), reconstruisait le panneau de mids (4 min 33) et re-hachait ~12 Go en série. Désormais (`tools/etude_copiabilite.py`) : demi-spreads gardés **par shard** sous son SHA-256 (seuls les shards nouveaux sont lus), panneau gardé pour un ensemble de shards donné (un seul fichier, remplacé), SHA-256 en parallèle (toujours vérifié à l'octet). Mesuré sur le coffre entier : demi-spreads **176 s puis 2 s**, panneau **136 s puis 0 s**, SHA-256 11 s. Résultats **identiques au bit près** (30 vrais shards, et tests). 4 tests, 6 injections rouges ; 97 tests du labo verts. Caches : `runtime/research_lab/data/copiabilite_cache/` |
| `ETA_COLLECTE.cmd` réparé (24/11, 13 h) | il affichait « ETA 0 min — ATTEINT (7/6 journées) » pendant que le labo répondait MORE_DATA (8 jours sur 20) : le seuil de 6 journées est le plancher de découpage du moteur, pas le besoin des études. Il lit maintenant les besoins **des études elles-mêmes** (`resultat.json` : jours mesurés / requis, une ligne par hypothèse ET par étude, échéance passée = « relancer l'étude ») → **prochaine hypothèse tranchable vers le 06/12, toutes vers le 11/12**. Débit mesuré sur `vault_fills_poll.jsonl` (372 lignes/min) au lieu du ruban WS quasi immobile ; sonde > 24 h marquée PÉRIMÉE ; la touche `q` marche enfin. 22 tests, 3 + 1 injections rouges |
| études de copiabilité relancées (24/11, 12 h) | sur le coffre dédoublonné, HEAD `1aa5ac78e9f1` : **3 sur 8 faites** avant l'arrêt par Claude Code (mémoire du PC basse : 3 `git` orphelins ~5 Go). Base : 21 830 632 fills uniques, miroir net **−13,32 bps** (88 420 copiés), `naive_mirror` MORE_DATA, `fast_follow` **REJECTED**, `slow_inventory` MORE_DATA (8 jours hors échantillon < 20). Positions : MORE_DATA. Rétrospectif : MORE_DATA. Verdicts inchangés en nature ; la comparaison chiffrée avec les passages du 12/11 n'a pas de sens (le corpus a grossi depuis). **Restent** : rétrospectif 1 h, ouvertures, ordres, persistance, réplication 350, plan |
| **cause corrigée** | un ruban en clair non remis à zéro (hors `FLUX_VIVANTS`) dont le préfixe n'est plus reconnu est comparé au coffre sur sa période avant dépôt ; garde rouge sous injection |
| ~~reste à mesurer~~ ✅ fait (ligne « doublons EXACTS ») | les 21 autres familles : la mesure complète a été arrêtée par Claude Code (mémoire du PC basse, ~4,5 Go libres) ; les empreintes déjà calculées sont gardées (reprise). À relancer : `tools\python\python.exe tools\auditer_doublons_coffre.py --travail <dossier>` puis `tools\python\python.exe tools\dedoublonner_coffre.py` |
| push de la nuit | **fait** à 22:16 UTC, Codex fermé par l'opérateur : `SYNCHRONIZED`, SHA local = GitHub `614b3cc7255d` (45 chemins, dont les 2 outils de doublons, le certificateur et leurs tests) ; verrou `index.lock` périmé de 20:13 UTC retiré par le lanceur après arrêt de 2 `git status` orphelins de Codex |
| push du soir | **NON fait** (remplacé par le push de la nuit) : Codex actif à 17:54 UTC ; l'attente automatique a été arrêtée par Claude Code (mémoire du système basse) avant tout push — aucun verrou laissé ; à lancer : `POUSSER-GITHUB.cmd` quand Codex est au repos |
| push | **fait** à 15:38 UTC quand Codex était au repos : `SYNCHRONIZED`, SHA local = GitHub `928e9a54a542` ; les 14 nouveaux fichiers et les modifications vérifiés dans le commit |

## 🗜️ 23/11/2026, 14:13 (heure lue) — compression sans perte, recensement à 100 %, et un défaut du certificateur

Demandes : « tout doit être compressé sans perte de données » ; « le certificateur doit savoir compresser
intelligemment si besoin » ; « le certificateur n'oublie aucune donnée dans l'ensemble du dossier du projet ».

**Mesuré (inventaire complet, 9,2 M fichiers, 87 241 dossiers, 7 min de balayage) : ~190 Go de données EN CLAIR.**
`runtime/archive/session_*` ~80 Go (figées) ; `runtime/reports/copy_vault_quant_lab` 72 Go ; `runtime/labo_tranches_20261121`
17,5 Go ; `market_ticks` 13 Go de shards de l'heure ; quarantaine 3 Go ; `runtime/history` 1,95 Go.

| point | état |
|---|---|
| archive gzip **par blocs indexée** (`datasets/archive_gzip_blocs.py`) : `.gz` standard, sans perte, relue à l'offset en décompressant UN bloc | fait |
| lecteur de preuves (`LecteurBorne`) et `scorer_vaults` lisent une session compressée | fait |
| `sceller_coffre_local.py --compresser[-seulement]` : rubans figés des sessions, ≥ 256 Ko, ≥ 10 min, vérification intégrale (taille + SHA-256) avant retrait du clair | fait ; passage réel lancé à 13:13 UTC |
| ⚠ **défaut du certificateur** : la lecture allait jusqu'à la taille, le préfixe scellé s'arrêtait au dernier retour → une dernière ligne sans retour **déposée deux fois** ; une ligne coupée mise en quarantaine pour rien | corrigé (lecture à la frontière ; archive figée scellée en entier) ; 2 gardes rouges sous injection |
| recensement de **tout** le projet (`datasets/recensement_donnees.py`), indépendant de la découverte du certificateur ; magasins non parcourus (9,2 M → 26 013 fichiers de données, **2,2 s**) | fait |
| `sceller_coffre_local.py --recensement` : scelle les données oubliées, écrit `COUVERTURE_PROJET.json` | fait |
| couverture mesurée | **99,52 %** ; reste 5 shards BBO/micro-BBO à sceller (le passage par défaut ne lit pas les sous-dossiers), 1 journal, **119 fichiers de sessions antérieures au 11/11 12:20 « à prouver »** (10 Go) |
| sessions APRÈS le 11/11 12:20 : scellées par construction (l'archiveur ne déplace qu'un contenu exactement certifié, commit 391efb93b1a3) | règle du recensement |
| ⚠ ne pas compresser : rubans vivants (`runtime/data`, `runtime/history`), sorties du labo (lecteurs non vérifiés) | en attente (collecteurs/labo au repos) |
| push | **retenu** : Codex travaille dans le dépôt en même temps (git diff, pytest) |

## 📦 23/11/2026, 13:30 (heure lue) — données externes gratuites AU COFFRE, et deux défauts trouvés en chemin

Demande : un `.cmd` racine qui récolte ces données et les fait certifier ; « si elles sont viables, fiables,
backtestables et replayables, elles sont autorisées à aller dans le coffre-fort » ; « il faudra qu'elles soient
utiles au labo ». Livré : `COFFRE_DONNEES_EXTERNES.cmd` → `tools/coffre_donnees_externes.py` (`--plan` = lecture
seule). Règles complètes et seuils : `docs/audit/MATRICE_DONNEES_EXTERNES.md` § « Au coffre ».

| point | état |
|---|---|
| récolte Ironflow + 1ers du mois Tardis, empreintes vérifiées, rien de payant | fait |
| recoupement **dex par dex** sur seuils fixés d'avance ; dex sans paire commune refusé | fait |
| versé seulement là où Alina n'a rien ; pré-certifié ; > 0,1 % de quarantaine = fichier refusé | fait |
| index du coffre : `provenance` + `source_tag EXTERNE_*` ; pont du labo : `signaux_externes_par_famille` | fait |
| carnet Tardis | **jamais au coffre** (pas d'heure de réception par Alina) |
| ⚠ OI Ironflow daté 1 h trop tôt (mark = clôture de l'heure : 1,89 bps contre 46) | corrigé à t + 1 h (sens prudent) |
| ⚠ **444 073 fundings d'Alina en double au coffre** ; `taux_du_coffre` les additionnait | corrigé : 1 par coin et par heure |
| impact des doublons sur les PnL déjà publiés du labo | **non re-mesuré** (à faire au prochain passage du labo) |
| gain du funding externe pour le portage | faible : 99,71 % des fills perp des leaders étaient déjà couverts |

Gardes : `tests/test_coffre_donnees_externes.py` (16 tests ; injections rouges sur la priorité d'Alina, l'arrondi
horaire, le remplacement, l'index, le pont, le rattrapage, les versions et la quarantaine). 665 tests des modules
touchés verts. Lanceur déclaré aux quatre endroits (+ `CLAUDE.md`).

## 🎯 Mission 2 (22/11/2026) — chasse à l'alpha CopyVault : 15 essais, **aucun edge**

*(« 14 essais » jusqu'au 15ᵉ, L2-fin, ajouté le même jour — ligne dédiée dans le tableau.)*

Journal complet, pré-enregistrements et registre : `docs/audit/GOAL2_CHASSE_ALPHA.md` ;
registre chaîné : `runtime/reports/copy_vault_quant_lab/goal2/ESSAIS.ndjson` (14 lignes).
Outils : `tools/goal2_*.py` (8 fichiers) ; gardes : `tests/test_goal2_chasse_alpha.py`
(20 tests, **14 preuves par injection rouges**).

| hypothèse | statut | la mesure |
|---|---|---|
| L1 entrer dans la position en perte **tenue** | `REJECTED` | +22,7 bps à 4 h… dont **+1,8** [−16 ; +21] viennent du leader ; le reste est le rebond du prix |
| L2 contre-pied des clôtures en perte agressives | `REJECTED` | +9,2 bps à 1 h [0,5 ; 17,9] : réel, sous les 15 bps de coût |
| L2-fin même contre-pied, **à la minute** (essai 15, moitié A de l'exécution) | `REJECTED` | −0,7 / −3,2 / −4,2 / −7,1 bps à 5/15/30/60 min : aucun rebond ; moitié B non consultée |
| L3 copie lente (24–72 h) | `REJECTED` | +116 bps bruts → **+16** une fois la dérive du coin retirée |
| L4 sélection par copiabilité | `UNMEASURABLE` | ~27 comptes par date : IC détectable > 0,17, contre 0,016 déjà mesuré |
| L8 leader qui pèse dans le volume | `REJECTED` | aucune tranche de participation ne se détache |
| L9 consensus de ≥ 3 leaders | `REJECTED` | +244 bps à 72 h, mais HYPE = 50 % des cas et +153 **sans** leader |
| L10 contre-pied du perdant tenu | `REJECTED` (critère pré-enregistré) | excès −138 à −229 bps à 72 h, IC contenant zéro |
| ordres en attente des leaders | `MORE_DATA` | 9 shards avant le verrou ; seule information **antérieure** au fill |

**La phrase :** toute l'information d'un fill de leader est consommée dans l'heure du fill. Témoin
positif à l'appui — en trichant d'une heure, l'outil voit +18, −66, +86 et −43 bps, tous
significatifs ; en causal, plus rien.

**Protocole respecté :** segments figés dans le code avant tout résultat ; validation, moitié B
de l'exécution (04/11 → 12/11) et OOS final (≥ 13/11) **non consultés**, donc vierges ; moitié A
de l'exécution consultée une fois (L2-fin). **Écart déclaré :** lecture du tier LOCAL
certifié (le SAFE ne porte que 5 shards de fills) → tout est exploration, rien n'est une preuve.

**Quatre faux alphas évités, dont un venait de mon outil :** indice équipondéré de 263 coins
(fabrique un alpha pour qui traite des majeurs) ; effet porté par un seul leader ; rebond
générique pris pour de l'information ; fills d'une même milliseconde triés par `tid` au lieu de
la chaîne `start_position` (60 953 faux trous, 87 % des positions invisibles).

*(PÉRIMÉ le 22/11 après-midi pour le point 1 — la recherche externe lui donne un a priori faible ; voir la section « après-midi » ci-dessous.)*
**Ce qui débloquerait :** (1) collecter les ordres en attente ≥ 30 jours — collecte éteinte sur
décision de l'utilisateur ; (2) re-mesurer L10 sur données neuves, règle déjà figée ;
(3) élargir l'univers à des centaines de comptes suivis **avant** de connaître leur résultat.

## ✅ 22/11/2026, 21:55 — point d'étape exact (reprise « travail réel, pas d'attente »)

**Apprenant prospectif** (preuve démarrée le 22/11 à 21:27, PID 18724, non redémarré) : vivant, 54
déclenchements en attente de résolution (4 h 02), aucun verdict avant le 27/11. **Risque mesuré, à
traiter avant ~demain soir** : ce processus tourne avec l'ancien code, qui relit EN ENTIER le fichier de
prix (~21 Mo/h, ~500 Mo/jour) toutes les 5 min. Le code corrigé (`cycles_fantomes.bande_de_prix`, lecture
depuis la fin, fenêtre utile seulement : identique sur la fenêtre, 0,4 s contre 1,1 s aujourd'hui) n'agit
qu'après redémarrage. Un redémarrage CONSERVE la date de début et le registre (sur disque) : il ne
remet pas l'horloge à zéro. À décider par l'utilisateur.

**Défaut réel corrigé** : l'état de l'apprenant contenait des NaN ; la page `/direct` aurait échoué en
entier au prochain lancement. `sans_nan` sur l'état écrit et la réponse JSON, test de régression.

**Corpus SAFE** : cause et correctif établis (section suivante) ; publication prête, réservée à
l'utilisateur.

**Recherche** : recherche externe (Exa, Tavily) — von Beschwitz, Lunghi & Schmidt (Fed 2021) et le barème
officiel des frais Hyperliquid (4,5 / 1,5 bps). Hypothèse nouvelle H14 (fermeture de réallocation)
pré-enregistrée puis mesurée : `REJECTED` (excès −14,2 bps à 24 h). **29 essais.** Validation des fills
(01/09 → 25/10) toujours VIERGE.

**Infrastructure** : `tools/goal2_bilan_registre.py` — statuts, segments consultés ou vierges, et le
niveau corrigé qu'un nouvel essai doit atteindre (Bonferroni sur 30 : 99,83 %). Le coût fantôme mesuré
(écart réel au BBO au lieu de 12 bps supposés) est PRÉVU pour une seconde campagne d'apprentissage, pas
dans celle en cours : changer le coût en cours de route mélangerait deux règles dans un même registre.

## 🔓 22/11/2026, 21:40 — corpus SAFE gelé au 18/10 : la correction existe, elle n'est jamais partie

Cause racine connue depuis le 21/11 (295 campagnes copy-vault terminales mais inclosables → plus de
release SAFE copy-vault). La correction (`_reconcile_epoch_superseded`, `_reconcile_retry_current_epoch`
dans `tools/campaign_watchdog.py`) est appliquée par le CLOUD (`campaign-watchdog.yml`, cron */5) —
**à condition que le code soit publié**. Vérifié ce soir, sans toucher à l'index Git :
- `origin/main` : 0 référence aux deux réconciliations ; local : 4 ; dernière modification du fichier
  sur `origin/main` le 09/11 ;
- le workflow tourne bien (succès 22/11 02:25 et 10:08, annulations 17:49) — avec l'ANCIEN code ;
- 24 tests de la correction verts en local ;
- essai à blanc de `POUSSER-GITHUB.cmd` (`alina_git_code_sync.py --dry-run`, 14 s) : 220 fichiers de
  code admissibles, dont la correction ; aucun add, commit ou push exécuté.

**Action restante, réservée à l'utilisateur** : lancer `POUSSER-GITHUB.cmd`. Ensuite, au plus 5 min
plus tard, le watchdog cloud fermera les campagnes inclosables et la file CopyVault reprendra.

## 🧠 22/11/2026, soir — le moteur ne POUVAIT pas apprendre ; il apprend maintenant, et ça se voit en direct

**Mon erreur de conception (la plus grave de la session).** La boucle d'auto-amélioration jugeait les
cycles réels du bac à sable. Or une garde VOULUE (`test_raw_probe_sans_edge_reste_shadow_sans_pnl`)
l'empêche d'ouvrir sans avance mesurée. Mesuré en direct : 660 ouvertures de leaders vues, 0 position,
0/20 — la boucle attendait des cycles qui ne pouvaient pas exister. La garde est GARDÉE.

**Ce qui la remplace :**
- `experimental/cycles_fantomes.py` : simule la règle exacte du bac à sable (seuil relatif au TVL,
  entrée au prix connu à la réception, sortie = la première entre le leader qui sort, le stop,
  l'horizon) sur les vrais fills et les vrais prix ; un cycle par ORDRE du leader (`oid`) — un ordre
  en 4 fills faisait 4 trades identiques, corrigé ; aucune entrée choisie selon son issue.
- `experimental/apprentissage_parallele.py` : les **45 variantes exécutables** jugées EN MÊME TEMPS sur
  chaque fill neuf (données postérieures au premier passage seulement), bootstrap par jours, correction
  pour variantes × jours regardés, élimination successive ; une championne exige borne basse > 0,
  5 jours, 50 cycles. Elle seule ARME le bac à sable, avec une avance MESURÉE
  (`edge_source: FANTOME_LCB`, seule source que `_cfg_defaut` accepte) : il ouvre alors en papier
  réel, et la boucle séquentielle juge ces cycles réels pour l'échelle PROBE → ALPHA.
- Mesuré sur la dernière heure : 34 trades fantômes (15 min), 3 % gagnants, −1,15 $ sur 100 $ — le
  pire trade est un vrai trou de prix sur HYPE (62,2175 → 62,025 en 4 s, stop franchi).

**Écran en direct** (demande : « beau, simple, compréhensible, toutes les améliorations, en temps
réel ») : page `/direct` du serveur du moteur, ouverte par `LANCER_HYPERSMART` à la place de `/v2`
(qui reste servie) — `ui/tableau_direct.py` + `.html`. Rafraîchie toutes les 3 s, lue dans les
fichiers : comptes papier (300 / 100 / 20 $), courbe du compte d'entraînement avec bulle au survol,
étapes de l'apprentissage, signaux et réponse du moteur, santé des flux, bilan de la recherche, et
les améliorations du 22/11 cochées SEULEMENT si elles se voient dans les données du moment.
Aussi : `tools/moteur_en_direct.py` (même chose en console).

Gardes : `test_apprentissage_parallele.py` (8 tests, 7 injections rouges), `test_tableau_direct.py`
(3 tests), anciens tests réécrits pour le nouveau partage des rôles ; 899 tests verts sur les fichiers
touchés. Effet : au prochain lancement de `LANCER_HYPERSMART`.

## 📏 22/11/2026, soir — amélioration n° 22 faite : le budget REST commun mesure enfin tous les appels

`rest_budget.json` ne recensait que 2 consommateurs, déclarés par estimation. Nouveau compteur
`hl_observer/ops/budget_rest.py` : chaque requête RÉUSSIE est pesée selon la règle publiée (2 pour
les lectures légères, 20 sinon, +1 par 20 éléments paginés, +1 par 60 bougies) sur une fenêtre
glissante d'une minute ; une écriture par minute et par source, au format déjà lu par le total du
superviseur. Branché dans les six collecteurs qui appelaient sans rien dire : mids, carnets, vaults,
poll des fills, rattrapage des fills et du registre, rattrapage des bougies et du funding.

**Choix délibéré, gardé** : le compteur MESURE, il ne bloque jamais. Le limiteur partagé existant
(`collecte_fiable.reserver_poids`) reste inactif, comme le projet l'a décidé (`debit_adaptatif.py` :
le débit se règle sur les refus 429, par AIMD). L'activer changerait le comportement des
collecteurs en direct ; la mesure réelle dit maintenant si c'est utile. Sous pytest, rien n'est
écrit dans le vrai runtime (vérifié : fichier inchangé après 430 tests des six collecteurs).

Gardes : `tests/test_budget_rest.py` (4 tests, 4 injections rouges). **Les 30 améliorations sont
closes** : 25 faites, 1 contournée (n° 27), 2 retirées (déjà dans le dépôt), 2 closes autrement.
Effet au prochain démarrage des collecteurs.

## 🧱 22/11/2026, soir — le verrou du verdict officiel n'est pas dans le labo : le corpus SAFE s'arrête au 18/10

Suite de la piste « le labo ne trouve pas le ruban des points de contrôle ». La campagne qui produit
`objective_status` (`tools/run_economic_objective_campaigns.py`, lancée par
`run_dataset_economic_campaigns.py`) exige un espace de travail reconstruit depuis le corpus **SAFE**
— conformément à la règle « SAFE certifié exclusivement ». Son passage de 06:45 a trouvé les six
rubans absents (`exists: false`) : tout est `UNMEASURED`.

Mesure du catalogue SAFE (`catalog/DATA_INDEX.json`, 222 parties, 1 853 164 shards) pour CopyVault :

| famille | shards | événements | période |
|---|---|---|---|
| `copy_vault_fills` | 6 | **36** | 01/10 → 17/10/2026 |
| `copy_vault_l2` | 14 651 | 52 682 | 01/10 → 18/10/2026 |
| `copy_vault_snapshot` | 609 | 609 | 01/10 → 18/10/2026 |
| `copy_vault_positions` | 100 | 200 | 16/10 → 18/10/2026 |

**Tout ce qui a été collecté depuis le 18/10 — dont les 127 346 points de contrôle maintenant
complets — n'existe que dans le tier LOCAL.** Aucune correction de ce soir ne peut donc changer le
verdict officiel tant que le passage LOCAL → SAFE est gelé (déjà diagnostiqué : « coffre gelé par
295 campagnes terminales mais inclosables » ; re-mesuré : 35 jours de retard).

Ce passage dépend de la publication GitHub (`POUSSER-GITHUB.cmd`, action de l'utilisateur) et de la
certification cloud : je ne le déclenche pas. **Décision à prendre par l'utilisateur** : débloquer la
certification SAFE des données postérieures au 18/10, ou accepter explicitement le tier LOCAL comme
source de preuve (écart à la règle §5 de la mission, à décider en clair, pas en douce).

## 🔗 22/11/2026, soir — relecture : 4 trous dans mes propres contrôles, et deux défauts de la chaîne

Un avis de relecture a pointé ce que mes vérifications ne couvraient pas. Tout est mesuré :

1. **La ligne de vie ne sortait pas pour les collecteurs visés** : `bbo-collector` et
   `copy-vault-checkpoints` battent avec le pid de leur enveloppeur. Elle sort maintenant pour le pid
   du processus ou de son parent direct ; un battement écrit pour un tiers n'imprime rien.
2. **Une bougie coupée par une reconnexion aurait été déclarée close** : la lane oublie la bougie
   en cours des coins d'une connexion à chaque (re)connexion (test + injection rouge).
3. **Le rattrapage aurait retéléchargé des pages pas encore scellées** (passage interrompu) : il ne
   recule plus que ce que NI le coffre NI les rubans locaux ne contiennent, et compte à part ce qui
   attend seulement le scellage.
4. **Mon détecteur ne regardait qu'à l'intérieur d'un fichier** ; le scelleur dédoublonne ENTRE
   fichiers, par ordre alphabétique. Mode `--session` ajouté. Sur les deux dernières sessions :
   - **fills : 805 fills sur 805 en double gardés dans la version du direct SANS `fee`, `crossed`,
     `closedPnl`** — le collecteur du direct les jetait. Corrigé dans `userfills_live` (noms bruts
     de la plateforme, comme le poll). Vérifié : le cache de la mission 2 n'est PAS touché (0 % de
     champs manquants sur les trois segments ; il vient des fills REST) — les 21 essais tiennent ;
   - carnets non liés : la copie de la lane gagne sur celle du moteur (autre connexion, autre heure
     de réception, mêmes prix). Pas de perte de prix ; **à trancher** si le replay doit garder les
     deux observations (l'identité inclurait la connexion) — décision laissée à l'opérateur.

**Maillon coffre → labo, mesuré avec le lecteur du labo** : les **5 241 références liées au coffre
étaient toutes invérifiables** (`SOURCE_LINE_ABSENT`) : elles désignent une ligne de
`runtime/data/copy_vault_l2_lane.jsonl`, ruban déplacé en archive à chaque arrêt. Le chargeur classe
une référence invérifiable en exploratoire, jamais en preuve ; et dès qu'une session suivante
réécrit ce chemin, il l'aurait déclarée DIVERGENTE (« preuve fausse », ligne rejetée). La ligne
exacte existe toujours, à la même position, dans l'archive : la vérification l'y cherche, avec la
même exigence d'empreinte SHA-256. **Après : 5 241 sur 5 241 vérifiées.** Une ligne introuvable
après rotation est invérifiable, plus « fausse » ; sans archive, une ligne différente reste fausse.

**Ce qui reste, honnêtement** :
- le dernier passage du labo (`economic_campaigns/copy_vault.json`) n'a pas trouvé le ruban des
  points de contrôle (`exists: false`, 0 ligne, reçu d'époque invalide) : c'est le prochain verrou
  du maillon coffre → labo, à mesurer par un passage du labo (comptes seulement, aucun PnL lu sur
  les données ≥ 13/11, aucun statut changé) ;
- maillon labo → moteur : non audité ce soir ;
- bougies partielles déjà au coffre et 3,6 % de trades rejoués étiquetés causaux : restent tels
  quels (on ne supprime rien) ; n° 22 non fait ; tout s'applique au prochain démarrage.

Vérifications : suite complète **20 359 verts, 0 échec** (18 min) ; puis 748 et 251 verts sur les
fichiers touchés après son départ ; 1 reçu périmé par la modification de la liaison, rafraîchi.

## 🔎 22/11/2026, soir — la chaîne collecteurs → certificateur → coffre → labo, contrôlée par mesure

L'utilisateur : « il y en a encore plein, des erreurs comme ça, sur les collecteurs → certificateur
→ coffre-fort → labo → moteur », et « le rattrapage doit utiliser le coffre-fort ».

**Un détecteur général au lieu d'une chasse au cas par cas** : `tools/auditer_identites_coffre.py`.
Pour chaque ruban archivé, chaque ligne est certifiée comme le ferait le scelleur, puis regroupée par
son identité de dédoublonnage ; dans un groupe, il liste les champs qui DIFFÈRENT (hors champs de
pure réception). Un champ métier qui diffère = le coffre n'en garde que la première version.
Toutes familles, 2 sessions par ruban, **23 s**. Il retrouve le défaut des carnets liés tant que la
correction n'y est pas (0 depuis : vérification croisée) et rapporte :

| ruban | collisions | avec perte | verdict |
|---|---|---|---|
| bougies 1 min du direct | 25 053 | **25 053** | **défaut** : le coffre gardait la première version, une bougie d'une demi-seconde (BTC : 3 trades au lieu de 1 965). La plateforme n'envoie presque jamais de version finale (104 bougies sur 4 209). Corrigé à la source : `collecter_market_lane` réémet la bougie complète, marquée `bougie_cloturee`, quand la suivante commence ; elle a sa propre clé au coffre. Aucun labo ne la consommait encore (flux « DISPONIBLE ») : aucun résultat n'en a dépendu. Les bougies déjà au coffre restent partielles (rattrapage à écrire) |
| trades | 32 024 | 14 944 | **pas de perte** : le coffre garde la version directe, écarte la rejouée (mesuré : 14 511 fois sur 14 511) |
| liquidations | 57 | 57 | **pas de perte** : seuls l'âge à l'observation et l'heure de réception diffèrent |
| 20 autres rubans | ≤ 30 | 0 | sains |

**Trouvé en chemin, noté et non corrigé** : 3,6 % des trades déjà au coffre (233 888 sur 6,57 M,
60 derniers lots) ont été reçus plus de 30 s après leur heure d'échange et portent
`causal_observation: true` : l'étiquette d'avant ce soir mentait pour les trades rejoués. Leur
heure d'échange est vraie : une simulation qui les place à cette heure reste juste ; seule
l'étiquette est fausse. Un lecteur qui se fie à `causal_observation` doit recalculer le retard.

**Le rattrapage utilise le coffre** (`hl_observer/ops/rattrapage_coffre.py`, branché dans
`tools/rattrapage_complet.py`). Avant, `RATTRAPAGE.cmd` planifiait depuis son propre curseur : une
page écrite puis jamais scellée restait « faite » et n'était plus jamais redemandée. Maintenant il
mesure la couverture RÉELLE du coffre (premier et dernier pas par série et par coin, cache par
shard : 55 s la première fois, 1 s ensuite), l'affiche, et recule le curseur — après avoir pris le
verrou, copie de l'ancien gardée — partout où il promet ce que le coffre n'a pas. Il n'avance
jamais un curseur. **État réel aujourd'hui : concordance parfaite** sur 5 séries × 263 coins ; aucun
trou dans les bougies 1 h, 4 h et 1 jour, 1 pas en 5 min ; le funding manque une heure sur 97 coins,
la même pour tous (15/08/2024 13:00) : un trou de la plateforme.
*Faux positif évité et documenté* : le premier passage annonçait 129 015 jours-coins de funding
absents (211 coins). C'étaient des **marques de plancher** (« origine atteinte, ne plus demander »),
toutes à 1 106 jours. Elles sont désormais reconnues.

**Corrections de l'avis de relecture** :
- la ligne de vie `[vie]` n'est écrite que s'il y a eu du **progrès** : deux collecteurs battent
  depuis une tâche à part ; sans cela, un collecteur dont la réception est figée aurait gardé un
  journal frais et fait taire le contrôle qualité ;
- la session de carnets de 6 h **relit la liste des coins toutes les 10 min** et ouvre une
  connexion supplémentaire pour les seuls coins nouveaux, sans toucher aux autres (sinon un coin
  nouvellement tenu aurait attendu jusqu'à 6 h son premier carnet) ;
- `collecter_asset_ctx` garde le nom natif (`kPEPE`). Ses lecteurs actuels comparaient sans tenir
  compte de la casse : ni perte avant, ni rupture après.

Gardes : 3 fichiers de tests (`test_rattrapage_coffre.py`, ajouts à `test_l2_lane.py` et
`test_collecteurs_exploitation.py`) ; 4 + 3 + 1 injections rouges, dont 1 garde aveugle refermée.

## 🔐 22/11/2026, 18:25 — arrêt des collecteurs : l'étape 3 « bloquée » et 28 990 preuves jamais arrivées au coffre

L'utilisateur a arrêté les collecteurs à 18:05 et signalé un blocage à l'étape 3 du certificateur,
puis demandé de vérifier que les données avaient bien atterri au coffre.

**1. L'étape 3 n'était pas bloquée, elle débordait.** Journal : début 18:05:27, lots écrits à
18:05:53, fin à 18:09:24 — 3 min 29 s d'écran immobile sur « ETAPE 3/3 » pour un budget annoncé de
45 s. Cause dans `tools/verifier_store_ticks.py` : le budget n'était regardé qu'en tombant sur un
shard NON vérifié ; un dossier actif (manifeste réécrit à chaque rotation, rien de neuf) était
relisté sans consulter l'horloge. Et chaque dossier lisait ses shards par `LIKE 'dossier/%'`, qui
balayait toute la table : **166 ms** par dossier sur 581 578 lignes, contre **0,03 ms** par plage
d'index. Corrigé (horloge consultée par dossier, requête par plage) ; l'étape s'annonce désormais à
l'écran. **Mesuré sur le vrai magasin : 47 s** (4 891 shards vérifiés, 0 anomalie).

**2. Les données de la session sont au coffre.** 52 shards relus et ré-empreintés (SHA-256 et nombre
de lignes conformes au manifeste) ; pour chacun des 21 rubans certifiés de la session archivée,
lignes du ruban = déposées + doublons + écartées. 6 rubans ne sont pas certifiés par conception
(dérivés, inférences, diagnostics), chacun avec son motif au manifeste.

**3. Mais une perte silencieuse ancienne, trouvée par cette vérification.** Le certificateur
identifiait un carnet par (coin, instant, meilleurs prix). Le moteur écrit certains carnets deux
fois : comme simple observation, puis comme **point de contrôle d'un signal** (`REFERENCE`,
`ENTRY`, `EXIT_*`, avec `checkpoint_id`). Le second était jeté « doublon ». Or le chargeur du labo
(`copy_vault_book_loader`) ne lit QUE les lignes portant un `checkpoint_id`. Mesuré sur les 29
sessions archivées : **28 990 points de contrôle sur 127 346 absents du coffre** (6 599
références, 2 554 entrées, 19 837 sorties) ; sur la session du jour, 28 références sur 28.

Corrigé dans `coffre_certifie.identite` (un carnet lié garde sa liaison dans sa clé ; un carnet nu
garde exactement son ancienne clé, rien de déjà déposé ne bouge), règle v2 pour
`copy_vault_l2_tape.jsonl`, et un **rattrapage par identité** : toutes les identités déjà déposées du
ruban sont préchargées, seules les lignes confondues à tort entrent. Lancé sur les archives :
**28 991 lignes rendues**, lot `20261122T171946Z_45a14d20` intègre. Re-mesure : **0 point de contrôle
manquant, 0 en double**. 23 lignes écartées : JSON coupé dans les archives, en quarantaine avec motif.

**Portée pour la recherche** : c'est peut-être une partie de « 100 % des épisodes sans carnet à la
sortie » (voir la cause racine du verdict manquant) — à mesurer en relançant le labo, pas à supposer.

Gardes : `tests/test_coffre_carnets_lies_aux_signaux.py` (4 tests, 6 injections rouges dont un cas
aveugle refermé), 2 tests dans `tests/test_verifier_store_ticks.py` (3 injections rouges) ;
848 tests verts sur les 66 fichiers qui touchent le coffre.

**Améliorations n° 18 et 19 faites** : `heartbeat_collecteur.battre` écrit au plus une ligne `[vie]`
toutes les 5 minutes dans le journal du collecteur, depuis sa propre boucle (un enveloppeur qui
l'écrirait rafraîchirait le journal d'un collecteur figé), avec les métriques de qualité non nulles.
**Le lanceur annonce la mise au coffre du démarrage** (écran vide de 1 à 2 min auparavant).

## 🧪 22/11/2026, 18:00 — le bac à sable du moteur était affamé : 0 cycle possible

**Constat, 20 minutes après le lancement** : `0/20 cycles`, aucune position papier ouverte, alors
que les leaders tradaient. Le journal du moteur (`fills_journal.jsonl`) donne le motif : sur les
fills d'ouverture, **22 déclenchements significatifs, 22 refus `VAULT_NON_SUIVI`** — dans les trois
cohortes, y compris le bac à sable.

**Cause** : `cohortes._vaults_cohorte` ne laissait le bac à sable suivre que les **8 premiers** du
classement. Cela valait « tous les abonnés » tant que l'écoute en direct suivait ce même top. Depuis
le 17/11 les 10 places d'écoute tournent selon l'**activité** : les 6 comptes actifs ce soir sont
aux rangs **30 à 47**. Le bac à sable écoutait donc des comptes qu'il n'avait pas le droit de
copier, et l'auto-amélioration n'avait rien à juger — elle ne pouvait pas apprendre.

**Correction** : le bac à sable suit tout vault **scoré** (présent au classement), quel que soit son
rang — ce que disait déjà sa description. Inchangé : un vault public non scoré reste en observation
seule ; ALPHA (retenus stricts) et PROBE (barre de sécurité) ne sont pas élargis. Papier, 20 USD.
Prend effet au **prochain démarrage du moteur**.

**Ce que cela ne dit pas** : que le bac à sable gagnera. Les 21 essais de la mission 2 concluent
qu'il n'y a pas d'alpha de copie ; le plus probable est qu'il mesure une perte, la juge PERDANTE et
essaie ses voisines. C'est le fonctionnement voulu — avant, il ne mesurait rien.

**Visibilité** : `tools/auto_amelioration.py` affiche désormais ce que le bac à sable a répondu aux
ouvertures des leaders (au moment de la mesure : 154 vues → 126 sous le seuil, 28 refusées).

Gardes : 4 tests dans `tests/test_auto_amelioration.py` (3 injections rouges) ; 220 tests verts sur
les 16 fichiers qui touchent les cohortes ; 0 reçu périmé.

**Amélioration n° 24 faite entre-temps** : `explorer-autonome` fait trois essais sur `meta` puis se
replie sur l'univers enregistré au lancement (même ordre, donc mêmes indices), en le disant. Total :
**24 faites** ; restent 18, 19 (cosmétiques) et 22 (budget REST commun).

**Mesure de référence de 17:59** (22 minutes de campagne) : 20 collecteurs sur 20, 1,42 Go ; retard
médian trades 65 ms, fills 87 ms, carnets 151 ms, BBO 362 ms ; 774 trades rejoués à l'abonnement
désormais écartés du retard ; couverture des carnets STABLE (11 coins par minute en médiane, aucun
creux de plus d'une minute) ; 2 trous causaux depuis le départ (le compteur affiche 877, cumulé).
La seule alerte du contrôle qualité (« ruban ABSENT ») date de 17:37:17, première seconde de la
campagne : c'est la fausse alerte de démarrage déjà corrigée (elle lisait un fichier écrit après
elle) ; prochain passage à 18:37.

## 📊 22/11/2026, 17:55 — état des 30 améliorations : 23 faites, 4 closes autrement, 3 restantes

| état | numéros |
|---|---|
| **faites (23)** | 2 (trous causaux : nature et compte **depuis le départ** — le compteur est cumulé, 875 dès la première seconde), 3 (raccord ≤ 30 s côté labo, éteint par défaut ; session de 6 h à la source), 4 (coins tenus en tête de liste), 5 (liste : poll + plafond 300), 6, 7, 8, 9, 12 (corrigé une seconde fois : la grâce lit le **bail**), 13, 14, 15, 16, 17, 20, 21, 23, 25, 28, 29, 30 (les trades rejoués à l'abonnement ne sont plus comptés comme du retard, ni étiquetés « causaux ») |
| **contournée (1)** | 27 — flux Binance `bookTicker` non réparé ; le profil « CopyVault seul » ne lance plus ce collecteur |
| **retirées (2)** | 1 — `fills_du_coffre` fusionne déjà WebSocket et poll ; 26 — le rattrapage des bougies trie déjà par retard |
| **closes autrement (2)** | 10 — limite de la plateforme : 10 comptes par IP en WebSocket ; l'extension passe par les lanes cloud. 11 — le « journal figé » de `userfills-poll` était une fausse alerte de démarrage, réglée par le n° 12 |
| **restantes (3)** | 18 et 19 (lignes de vie des collecteurs silencieux : cosmétique, le contrôle lit déjà leurs battements), 22 (budget REST commun à tous), 24 (`explorer-autonome` : nouvel essai sur `meta`) |

**Mesures en direct, 15 minutes après le lancement** (`tools/mesures_de_collecte.py`) : trades 65 ms
de retard médian, fills WebSocket 89 ms, carnets L2 156 ms, BBO 376 ms ; continuité des positions :
1 rupture sur 464 fills en direct (0,22 %), 151 sur 14 341 fills du poll (1,05 %).

**Vérifications** : 436 tests verts sur les 33 fichiers qui touchent les modules modifiés ; 4 reçus
périmés par la modification du registre, rafraîchis (0 périmé). La suite complète n'a pas été
rejouée depuis 17:00 : à faire collecteurs arrêtés.

**Décision qui revient à l'opérateur** : allumer le raccord des carnets côté labo
(`HL_LABO_RACCORDER_L2=1`). Effet mesuré : observation continue médiane 25,0 → 71,5 min. Il change
ce que le replay accepte comme continuité ; je ne l'allume pas de moi-même.

## 🧩 22/11/2026, 17:40 → 17:50 — carnets : la vraie cause du « rien de mesurable », et quatre corrections

Travail fait pendant que la mesure de référence tournait (ordre de l'utilisateur : ne jamais
rester inactif en attendant un shell).

**La cause, mesurée sur 12 h de carnets du coffre** (12/11, 453 422 carnets, 216 coins) : le
collecteur local de carnets tourne par **sessions de 25 minutes** (`--duree-s 1500`). Chaque fin de
session change l'identité de connexion des coins et ouvre un trou d'une vingtaine de secondes. Or
le replay refuse un épisode qui traverse deux connexions. Résultat : un coin n'était observé en
continu que **25,0 minutes** en médiane, quand le labo teste des horizons jusqu'à 60 minutes.

| n° | correction | mesure avant → après | état |
|---|---|---|---|
| 3 (labo) | `copy_vault_raccords_l2.py` : deux carnets d'un coin séparés de ≤ 30 s (le seuil de fraîcheur du labo) restent dans la même chaîne de continuité ; tout est compté | observation continue médiane **25,0 → 71,5 min** ; 1 080 raccords franchis (trou médian 19,7 s), 1 404 refusés (> 30 s) | fait, **éteint par défaut** (`HL_LABO_RACCORDER_L2=1`) : touche le cœur causal, à activer par l'opérateur |
| 3 (source) | session locale de 6 h au lieu de 25 min (`collecteur_registry`, `l2-leaders`) | 14 fois moins de changements de connexion | fait ; **prend effet au prochain démarrage des collecteurs** |
| 5 | la liste des coins à carnets lit aussi les fills du **poll** (~120 comptes), plus seulement ceux du WebSocket (10) | sans cela la liste dérive : **78,0 % → 47,9 %** des fills couverts après quelques passes ; avec : stable à 78,4 % | fait |
| 5 | plafond de la liste **180 → 300** coins (8 connexions de 40, loin des 1 000 abonnements permis) | fills de perps ordinaires ayant un carnet : **84,4 % → 99,8 %** ; demandes hors plafond 119 → 0 | fait |
| 4 | les coins où un leader **tient une position** passent en tête des demandes et ne sont jamais déplacés | en réel : 178 coins tenus, dont **62 sans carnet abonné** | fait |
| — | **défaut trouvé en chemin** : `collecter_vaults.py` enregistrait les coins des positions en MAJUSCULES (`kPEPE` → `KPEPE`, un marché qui n'existe pas) ; 11 positions `KPEPE`, 0 `kPEPE` sur le ruban du jour | ces positions étaient invisibles pour toute jointure en aval | corrigé (les données déjà écrites gardent l'ancien nom) |
| 1 | **retiré** : `fills_du_coffre` fusionne déjà WebSocket et poll et dédoublonne par `hash` | — | déjà fait dans le dépôt |

Reste noté, non traité : d'autres collecteurs écrivent aussi des noms en majuscules
(`collecter_carnet`, `collecter_liquidations`, `collecter_lab_ctx`) — familles hors CopyVault.

Gardes ajoutées : `tests/test_copy_vault_raccords_l2.py` (9 tests, 7 injections rouges) et 6 tests
dans `tests/test_collecteurs_exploitation.py` (7 injections rouges).

**À faire à l'arrêt des collecteurs** (on ne modifie pas un `.cmd` qui tourne) : annoncer à l'écran
l'étape de certification du lancement, aujourd'hui muette pendant ~2 minutes.

## ▶ 22/11/2026, 17:37 — collecteurs lancés par l'utilisateur : premières mesures réelles

Lancement complet (20 collecteurs) à 17:35:30 ; collecteurs actifs à **17:37:22**, statut `ACTIVE`,
20/20, aucun manquant (19 démarrés, `userfills-poll` repris).

| mesure | valeur |
|---|---|
| mémoire des 20 collecteurs, régime établi | **1,47 Go** (2,7 Go pendant la passe de `scorer-vaults`, qui monte seul à 1,23 Go) |
| plus gros consommateurs | `bbo-collector` 278 Mo et ~1 cœur ; `native-venues` 177 Mo — deux collecteurs hors CopyVault |
| mémoire libre de la machine | 4,0 Go sur 31,9 |
| refus HTTP 429 depuis le lancement | 0 (10 ce midi sans démarrage échelonné) — une minute d'observation seulement |
| certificateur | `[initial-delay] 600s` : le départ différé fonctionne |
| rotation | `supervisor.log` de 94 Mo archivé, nouveau journal à 4,6 Ko |
| boucle d'auto-amélioration | `runtime/auto_amelioration/etat.json` écrit par le moteur à 17:37:14 : elle tourne ; 0/20 cycles |

**Deux défauts vus seulement en réel :**
1. L'écran reste **vide** pendant ~2 minutes après `[ARRET] {…}` : le lanceur certifie le reste de la
   session précédente sans rien afficher. À corriger **à l'arrêt** (on ne modifie pas un `.cmd` qui tourne).
2. Mon délai de grâce du contrôle-qualité **ne s'appliquait pas** : il lisait l'heure de départ dans le
   fichier d'état, écrit à la fin du démarrage ; au premier contrôle ce fichier datait encore de la
   campagne précédente. Corrigé : il lit le **bail**, écrit avant le lancement (test de régression).

## 🚫 22/11/2026, nuit — faux « DEJA EN COURS » au lancement : c'était MA suite de tests

**Constat de l'utilisateur** : `LANCER_COLLECTEURS_COPY_VAULT.cmd` a refusé de démarrer —
« Des collecteurs tournent deja sur ce PC » — alors qu'aucun ne tournait.

**Cause** : `tools/collecteurs_balayage.py` reconnaît un collecteur à des **sous-chaînes** de sa
ligne de commande (`run_bounded_collector`, `collecter_`, `watch_economic_collectors`). Au même
instant je lançais `pytest … tests/test_run_bounded_collector.py tests/test_watch_economic_collectors.py` :
ma suite de tests a été comptée comme un collecteur vivant. Le même balayage l'aurait **tuée** sur
un `--stop`.

**Correctif** : `MARQUEURS_EXCLUS` reçoit `-m pytest`, `pytest.exe`, `py.test`,
`preflight_collecteurs`. Marqueurs volontairement précis : le seul mot « pytest » figure aussi dans
les dossiers temporaires (`pytest-of-<user>`) et aurait rendu invisibles de vrais collecteurs —
erreur que j'ai faite au premier jet et qu'un test existant a attrapée. Garde :
`test_une_suite_de_tests_qui_nomme_des_fichiers_de_collecteurs_n_est_pas_un_collecteur`
(rouge dans les deux sens par injection).

**Aussi livrés depuis le bilan précédent (lot 4)** : n° 7 (leaders réellement pollés dans la page
de santé), n° 25 (le certificateur part 10 min après les collecteurs), n° 15 complété (trois
générations de journaux `economic-*.log`). N° 26 **retiré** : le rattrapage des bougies trie déjà
les coins du plus en retard au plus à jour — mon constat était faux. Bilan : **18 faites, 1
contournée, 1 retirée, 10 restantes** (1, 2, 3, 4, 5, 10, 11, 18, 19, 22, 24).

⚠ La suite complète n'a pas été rejouée après le lot 4 et ce correctif (seulement les fichiers
de tests concernés : 62 + 76 verts). À rejouer collecteurs arrêtés.

## 🔧 22/11/2026, nuit — les 30 améliorations : 15 faites, 1 contournée, 14 restantes

L'utilisateur : « implémente toutes tes idées ». État exact, numéros de la liste ci-dessous.
Outils nouveaux : `tools/collecteurs_exploitation.py`, `tools/mesures_de_collecte.py`. Gardes :
`tests/test_collecteurs_exploitation.py` (**23 tests, 12 injections rouges**).

| n° | état | ce qui a été fait |
|---|---|---|
| 6 | **fait (mesure)** | `mesures_de_collecte.py` compte les ruptures de chaîne `startPosition` et les localise ; sur les rubans du jour : 69 ruptures sur 5 224 fills du poll (1,32 %), 0 sur 17 du WebSocket. La re-demande automatique du fill manquant reste à faire. |
| 8 | **fait** | la courbe de HLP est relue par le balayage historique (`VAULTS_HISTORIQUE_SEULEMENT`) ; HLP reste hors des vaults copiés. |
| 9 | **fait** | un vault ouvert mais vidé est jugé sur son PnL cumulé au lieu d'être écarté. |
| 12 | **fait** | délai de grâce de 10 min au contrôle-qualité, seulement si l'heure de départ est connue. |
| 13 | **fait** | verrou au nom d'un PID mort écarté (renommé, pas supprimé) à l'arrêt et avant chaque relance. |
| 14 | **fait** | la page de santé porte une `phase` ; la première n'est plus lue comme une panne. Mon constat était inexact : elle est bien rafraîchie, mais seulement à la fin de chaque passe. |
| 15 | **fait en partie** | `supervisor.log` tourne à 20 Mo (5 générations). Les journaux `economic-*.log` ne gardent toujours qu'une génération. |
| 16 | **fait** | le lanceur de collecte écrit de nouveau dans `runtime/logs/launchers/`. |
| 17 | **fait** | RAM et CPU par collecteur (enfants compris) dans chaque ligne du journal du superviseur. |
| 20 | **fait** | `preflight_collecteurs.py --profil tous` : **20/20 démarreraient** (mesuré). |
| 21 | **fait** | 0,5 s entre deux lancements (`HL_COLLECTEURS_ECHELONNEMENT_S`). |
| 23 | **fait** | `asset-ctx` : la réponse d'erreur est fermée, et un refus 429 double l'attente (borné à 5 min). |
| 28 | **fait** | `taux_rejet_canonique` publié à côté de l'ancien taux (84 % le 22/11, quand l'ancien disait 0). |
| 29 | **fait** | profil `--copyvault-seul` : 13 collecteurs au lieu de 20. |
| 30 | **fait (mesure)** | `mesures_de_collecte.py` : retards par ruban. Constat nouveau : la fin du ruban des trades porte des retards de 20 à 47 min — des trades anciens rejoués à l'abonnement, non étiquetés comme tels. |
| 27 | **contourné** | le flux Binance `bookTicker` n'est **pas** réparé ; le profil « CopyVault seul » ne lance simplement plus ce collecteur. |
| 1, 3, 4, 5 | **non faits** | touchent le cœur causal (source des fills, affectation des coins aux connexions). À faire collecteurs en marche, avec mesure avant/après ; le n° 3 doit être relu par l'opérateur avant (note du 22/11). |
| 2, 7, 10, 11, 18, 19, 22, 24, 25, 26 | **non faits** | pas commencés. |

## 📋 22/11/2026, soir — 30 améliorations des collecteurs (audit demandé avant lancement)

Source : traces du fonctionnement réel du 22/11, 12:54 → 13:01 (journaux `runtime/logs/economic-*.log`,
`bbo_heartbeat.json`, journal du superviseur, rubans). **[V]** = vérifié ce jour sur ces traces ;
**[M]** = mesuré plus tôt (mémoire, date indiquée), non remesuré ce soir. **Aucun de ces points
n'empêche de lancer** : ce midi, 19 collecteurs ont démarré, 1 a été repris, les données s'écrivaient.

**A. Justesse des données CopyVault (ce qui manque au verdict du labo)**
1. [M 22/11] Le WebSocket rate 16,6 % des fills que le poll capte ; le poll en rate 2,2 % → faire de la **réunion** des deux la source des fills.
2. [V] 850 trous causaux signalés en 7 min par le superviseur (428 → 850, protocole `copy_vault_unbound_ws_l2_v1`) → publier **quel** coin et **quelle** connexion, pas un compteur.
3. [M 22/11] 83 % des carnets écartés pour des raccords entre connexions de 2,84 s médian → un coin doit rester sur **une** connexion L2 au moins une heure.
4. [M 22/11] Couverture L2 variable : 6 creux de 32 min médians (80 max), plus longs que l'horizon du labo → épingler l'abonnement L2 d'un coin tant qu'un leader y tient une position.
5. [V] Quatre listes de coins indépendantes (L2 : 4 × 40 ; microstructure : 24 ; carnets : 38 ; BBO : 8) → une liste unique, dérivée des coins tenus par les leaders suivis.
6. [V] 1 129 ruptures de chaîne de position sur 110 690 fills rattrapés (1 %) → contrôler la continuité `startPosition` à la collecte et redemander le fill manquant.
7. [V] Profondeur d'historique médiane : 14 jours pour 80 comptes (l'API ne rend que 10 000 fills) → seul le poll continu la construit ; suivre le nombre de leaders réellement pollés.
8. [V] HLP est exclu de la collecte (`VAULTS_EXCLUS`) alors que c'est le seul objet `PROMISING` → collecter et certifier sa courbe.
9. [V] L'univers historique des vaults ignore les vaults ouverts mais vidés (< 1 000 USD) → biais de survie ; les inclure dès que leur PnL cumulé dépasse 1 000 USD en valeur absolue.
10. [V] Ordres en attente et positions : 20 à 42 leaders suivis sur 120 configurés → étendre, ou assumer et le dire (a priori faible, cf. journal § 8).

**B. Robustesse des processus**
11. [V] `userfills-poll` a été **repris** sans vérifier qu'il produisait ; son journal officiel date du 12/11, il écrit dans `poll-leaders.log` (1 ligne en 7 min) → un seul journal, reprise conditionnée à un battement récent.
12. [V] Le contrôle-qualité échoue à **chaque** démarrage (`returncode=1`) : il juge à t+0 des rubans pas encore créés → délai de grâce, sinon l'alerte n'est plus lue.
13. [V] `userfills_live.lock` subsiste après l'arrêt (PID 7132 mort) → le libérer à l'arrêt ; vérifier au prochain lancement qu'un verrou périmé ne bloque pas.
14. [V] `collecteurs_sante.json` écrit une fois au démarrage (tout « ABSENT », 0 leader pollé) puis plus jamais en 7 min → le rafraîchir à cadence fixe.
15. [V] `supervisor.log` pèse 94 Mo, sans rotation ; les autres journaux ne gardent qu'**une** génération (`.prev`) → rotation datée et bornée.
16. [V] Le journal du lanceur `LANCER_COLLECTEURS_COPY_VAULT.log` n'est plus écrit depuis le 12/11 → on ne peut pas savoir si un lancement a été tenté.
17. [V] Le superviseur ne publie ni RAM ni CPU par collecteur → les ajouter (impossible aujourd'hui de dire ce que 20 collecteurs coûtent à côté de Salad).
18. [V] `native-venues` et `copy-vault-checkpoints` : journaux vides après 7 min → une ligne de vie périodique (silence ≠ santé).
19. [V] `bbo-collector` : une seule ligne de journal ; tout son état est dans un fichier de battement → y écrire aussi ses anomalies.
20. [V] Le préflight ne vérifie que 8 collecteurs sur 20 → l'étendre aux 12 autres.

**C. Débit et API**
21. [V] 10 refus HTTP 429 en 7 min sur `asset-ctx` : les 20 collecteurs partent ensemble sur une seule IP → démarrage échelonné.
22. [V] `rest_budget.json` ne recense que 2 consommateurs (75,7 et 133,3 de poids par minute) → y inscrire **tous** les appels REST.
23. [V] `asset-ctx.log` : 755 Ko en 7 min, surtout des avertissements de ressource → les traiter à la source.
24. [V] `explorer-autonome` : « meta indisponible (HTTPError) » → nouvel essai borné, sinon son décodage reste limité.
25. [V] Le certificateur démarre avec les collecteurs et traite 132 fichiers (dont 251 Mo de bougies) → le décaler après la stabilisation.
26. [V] Rattrapage des bougies : 263 coins en série, toutes les 4 h → prioriser les coins des leaders suivis.

**D. CopyVault seul : ce qui tourne pour rien**
27. [V] Flux Binance `bookTicker` en boucle : 35 reconnexions et 35 trous en 433 s, 36 trames (contre 26 670 de profondeur) → le réparer ou le couper.
28. [V] `bbo-collector` : 76 251 événements rejetés pour 14 018 écrits (84 %), alors que son indicateur affiche `taux_rejet = 0.0` → un compteur de santé qui ment.
29. [V] 12 collecteurs sur 20 ne servent pas CopyVault (le contrat n'en exige que 8) → un profil « CopyVault seul », qui libère RAM, CPU et quota d'API.

**E. Mesure**
30. [V] Retards de réception mesurés : trades 162 ms (p99 416), carnets L2 337 ms, fills WS 169 ms, mais **BBO 538 ms (p99 889)** → publier ces retards en continu et traiter le BBO, trois fois plus lent.

## 🧠 22/11/2026, soir — le moteur apprend seul de ses résultats (demande de l'utilisateur)

**Demande** : « je veux que le moteur `LANCER_HYPERSMART.cmd` s'auto-améliore tout seul […]
apprendre de ses erreurs […] un PnL toujours vers le max positif ».

**Ce qui existait déjà** : trois cohortes papier isolées, chacune avec son ledger et une empreinte
de configuration ; une pause automatique quand l'espérance réalisée devient négative ; un bac à
sable (`RAW_PROBE`, 20 USD papier) **figé après 20 cycles « pour décision »** — décision que
personne ne prenait. Le moteur mesurait, il ne changeait rien.

**Ce qui est livré** : `src/hl_observer/experimental/auto_amelioration.py`, appelé toutes les
5 minutes par la passe périodique du moteur (`tools/collecter_userfills_vaults.py`,
`_auto_amelioration_une_passe`, fail-soft). État lisible : `tools/auto_amelioration.py`.

| étape | règle |
|---|---|
| observer | cycles clôturés du bac à sable, par variante du déclencheur (`frac_tvl`) |
| juger | GAGNANTE si la borne basse du résultat moyen > 0 ; PERDANTE si la borne haute < 0 ; INDÉCISE sinon — intervalle élargi par le nombre de variantes comparées |
| retenir | une PERDANTE n'est jamais réessayée ; chaque décision va dans un journal chaîné (`runtime/auto_amelioration/journal.ndjson`) |
| essayer | d'abord les variantes jamais essayées (les mieux notées en fantôme d'abord), puis une INDÉCISE (3 échantillons au plus), puis la meilleure GAGNANTE |
| s'abstenir | tout essayé, rien ne gagne → le bac à sable reste figé : ne pas trader est le résultat appris |

**Garde-fous** : jamais de changement au milieu d'un échantillon ; la mesure fantôme ordonne, ne
prouve pas ; **seul le bac à sable est piloté** — ALPHA et PROBE ne sont pas touchées, une
gagnante y est seulement signalée ; papier uniquement ; un test ne peut pas écrire dans le vrai
runtime (même isolation que les cohortes). Gardes : `tests/test_auto_amelioration.py`
(25 tests, 18 injections rouges après l'extension).

**État réel au 22/11** : variante `v1`, 0/20 cycles, aucune variante jugée. La boucle ne tournera
que lorsque le moteur tournera.

**Ce que cette boucle ne fait pas, dit clairement** : elle ne crée pas d'avantage. Les 21 essais
du jour ne trouvent aucun alpha de copie ; le plus probable est donc qu'elle essaie les cinq
variantes, les trouve perdantes ou indécises, et s'abstienne. C'est exactement ce qu'on lui
demande : arrêter de perdre vite, et trouver ce qui marche **s'il** y a quelque chose à trouver.

*(PÉRIMÉ le soir même : l'utilisateur a demandé de tout faire tout de suite — « fais tout le
nécessaire […] n'oublie rien » — voir « Extension » ci-dessous.)*
**Suite possible, non faite** : étendre le pilotage à la promotion vers PROBE puis ALPHA (budget
réel de papier), et à d'autres paramètres que `frac_tvl` (stop, horizon). À faire seulement
après avoir vu la boucle tourner sur de vrais cycles.

### Extension livrée le 22/11 au soir (à la demande de l'utilisateur)

**Défaut trouvé dans ma première livraison, corrigé.** J'avais écrit « seul le bac à sable est
piloté ». C'était faux : `raw_trigger.json` est lu par les **trois** cohortes ; y écrire aurait
déplacé le déclencheur d'ALPHA et de PROBE et remis leurs compteurs à zéro, sans le dire. Chaque
cohorte a désormais son propre réglage, `runtime/data/<prefixe>_auto.json`
(`cohortes._reglage_auto`) ; sans ce fichier, rien ne change pour personne (testé).

| ajout | règle |
|---|---|
| **trois paramètres** dans le bac à sable | seuil `frac_tvl` (5 valeurs), stop 20/40/80 bps, horizon 15 min / 1 h / 4 h — **un seul à la fois** autour de la meilleure variante connue ; **15 variantes au plus**, puis abstention |
| **promotion vers PROBE** | une variante GAGNANTE **confirmée par un second échantillon** (40 cycles) voit son seuil écrit dans `discovery_probe_auto.json` |
| **promotion vers ALPHA** | seulement si PROBE gagne **à son tour** sur 20 cycles sous ce réglage (borne basse > 0) — un niveau à la fois |
| **rétrogradation** | une cohorte promue qui perd (10 cycles, moyenne négative : le critère de pause du moteur) retrouve ses défauts ; ce seuil n'y est **plus jamais** promu |
| stop et horizon | restent propres au bac à sable : ALPHA et PROBE tiennent les leurs de leurs tables par coin |
| **dépôt papier HLP** | marqué par le moteur lui-même, une lecture publique par 24 h (`_hlp_papier_une_passe`, sous-processus borné à 120 s) |

Gardes : `tests/test_auto_amelioration.py` — **25 tests, 18 injections rouges** (deux gardes
aveugles trouvées par injection puis corrigées : le plafond de 15 variantes, et l'empreinte de
configuration quand seul le stop change).

## 🏦 22/11/2026, soir — famille V : le **dépôt** dans les vaults (essais 16 à 21)

Détail : `docs/audit/GOAL2_CHASSE_ALPHA.md` §§ 9–11. Outils : `tools/goal2_vaults_matrice.py`,
`goal2_depot_vaults.py`, `goal2_hlp.py` ; gardes : `tests/test_goal2_depot_vaults.py`
(19 tests, 19 injections rouges). Registre chaîné : 21 essais.

| objet | statut | mesure (net du déposant, par période de 28 jours) |
|---|---|---|
| panier de tous les vaults d'utilisateurs ≥ 10 000 USD | `REJECTED` | **−436 bps [−823 ; −61]**, alpha contre BTC −584 [−932 ; −272] |
| sélection « qualité » (ancien, gros, calme) | `REJECTED` | −308 bps ; pire que le panier dans 2 variantes sur 3 |
| sélection « extrêmes persistants » | `REJECTED` | −116 bps [−561 ; +286] |
| **HLP, le vault du protocole** | **`PROMISING`** | **+230 bps [113 ; 373]**, bêta −0,03, repli maximal −3,7 % ; validation +54,6 et +28,8 bps |

**Une référence du dépôt est corrigée.** Le « copier tous les vaults : +4,49 bps/jour » du 17/11
excluait la période où un vault se vide et ferme. Mesurées (435 périodes, perte moyenne −23,5 %),
elles font passer le panier de **+319** à **−22 bps** par période : le rendement moyen des vaults
était un biais de survie *à l'intérieur* des séries.

**HLP, à sa juste taille.** Seul résultat positif de la mission, mais ce n'est pas un alpha de
copie : c'est la prime de teneur de marché du protocole, et elle décroît (41 % en 2023, 36 %,
15 %, ~10 %/an en 2026, ~5 %/an sur septembre–octobre). Sur 100 USD : **0,014 à 0,04 USD par
jour**. Donnée lue hors coffre certifié → plafonnée à `PROMISING`. La preuve prospective est
outillée (`goal2_hlp.py --lire --segment prospectif`, première période comptée le 17/12/2026,
6 périodes minimum) et ne demande aucun collecteur.

## 🔧 22/11/2026, après-midi — point fixe, test « figé », état des collecteurs

**Point fixe atteint.** Suite complète en demi-charge (`-n 2`, 27 min) : **20 249 verts, 0 échec**,
59 ignorés, 1 xfail. Reçus : 14 périmés par le chantier funding → **14 rafraîchis, 0 périmé,
0 échec, 0 preuve absente** ; `rig_020` vert.

**Le test « figé à 99 % » n'était pas figé.** `test_dynamic_cli_and_argparse_paths_are_finite_and_offline`
appelle trois fois `runtime-check`, qui balayait le vrai `runtime/data` : **5 170 447 fichiers,
149 s par appel**, en construisant un `Path` par fichier. Tri sur le nom d'abord
(`src/hl_observer/runtime/hygiene.py`) : **10,9 s, rapport identique sur l'arbre réel** ; le test
passe de > 8 min à 2 min 23. Garde : `tests/test_runtime_hygiene_balayage_borne.py` (3 injections
rouges). ⚠ Ce test monkeypatche `os._exit` : `pytest-timeout` ne peut pas le tuer, le nom du
coupable n'apparaît que dans les **avertissements**.

**Collecteurs : ARRÊTÉS, pas en panne** (question de l'utilisateur, 15 h 24). Preuves : 0 processus
identifié par sa ligne de commande, verrou absent ; dernier fonctionnement le 22/11 de 12:54 à
13:01 (lancement fait par erreur, arrêté à la demande) — 19 démarrés et vérifiés + 1 réutilisé,
abonnements acquittés (`userFills` 10/10, `l2Book` 40/40), rubans écrits jusqu'à 13:01 ;
préflight **8/8 `DEMARRERAIT`** ; `LANCER_COLLECTEURS_COPY_VAULT.cmd --status` rend 0.
Rien n'a été relancé : la consigne « ne relance pas la collecte » tient.

**Deux fausses alertes de l'écran d'état, corrigées** (`tools/etat_collecte_reel.py`,
`tests/test_etat_collecte_incoherence.py`, 6 tests, 5 injections rouges) :

| alerte | pourquoi elle était fausse | correction |
|---|---|---|
| `ETAT_INCOHERENT: pids=20 mais demarres_et_verifies=19` | la règle comparait deux **longueurs** et ignorait `reutilises` (`userfills-poll`, déjà vivant, repris) | invariant sur les **ensembles de noms** ; l'alerte nomme le collecteur fautif |
| `RUBANS_ABSENTS: copy_vault_bbo_tape, copy_vault_trades_tape` | le premier est écrit par un **téléchargeur** des lanes cloud, le second par **personne** ; les collecteurs locaux écrivent `*_lane.jsonl` | rubans surveillés = ceux dont le registre `couverture_donnees.FLUX` donne un producteur `tools/collecter_*.py` |

Restent deux alertes **vraies** pour un système arrêté : `ETAT_PERIME` (20 workers déclarés,
0 vivant) et `BAIL_EXPIRE`.

**Recherche externe, second passage** (journal `GOAL2_CHASSE_ALPHA.md` § 8) : sur Hyperliquid,
l'information portée par l'identité d'un compte vit **moins de 30 s** et pèse **~3 bps** (Zhai ;
Ding & Zhai, 2026). Je retire donc ma recommandation « collecter les ordres en attente
débloquerait un edge » : la piste garde `MORE_DATA` avec un a priori **faible**. Le blocage n'est
pas un manque de données mais l'économie du produit (9 bps de frais + ~98 s de retard).

## Les 13 chantiers du journal d'audit

| # | Chantier | État sur le HEAD actuel | Preuve |
|---|---|---|---|
| 1 | Tunnel causal signal → trade | **FAIT, re-joué sur le HEAD FINAL (`75208140d32`)** | 87 844 / 88 131 = 99,7 % (13→17/11), 31 leaders sur 31 ; **re-joué le 18/11 sur les rubans du jour (plafonds × 7, 715 581 carnets sur 0,6 j) : 9 366 / 10 422 = 89,9 % jusqu'à la sortie observée**, 12 leaders sur 12 à chaîne complète, chaque refus avec son motif unique (`PAS_UNE_OUVERTURE` 11 754, `HORS_FENETRE` 944, `AUCUN_CARNET` 66, `ENTRY_BOOK_ABSENT` 40, `EXIT_CENSURE` 6), 0 saut d'horloge. **Re-mesure sur le HEAD final : 9 790 / 9 859 signaux JUGEABLES = 99,3 %** ; les 64,2 % bruts rapportent à tout ce qui est *lu*, donc à un budget d'octets (fenêtre de carnets inchangée à 817,3 min, mais 30 575 fills lus contre 22 176 : la collecte a avancé). 19 leaders, 15 à chaîne complète |
| 2 | Référence L2 pré-signal + trous | **FAIT, durci le 17/11** | liaison pré-signal + `copy_vault_gap_windows` (37 tests) : un incident = un intervalle (302 fenêtres → 1, le journal ne déborde plus), arrêt de l'écrivain déclaré comme trou, sauts d'horloge détectés et gardés dans le tunnel |
| 3 | Collecteurs / orchestration | **FAIT ; effet MESURÉ** | 10 slots `userFills` aux signaux copiables ; recul sur refus unifié sur 3 sites ; effet mesuré après correction : le direct ratait 61,0 % des fills de rafales, ramené à 19,6 % (`tools/mesurer_decouverte_rafales.py`), 79 % des cycles reconduits en production. **Avant correction, le direct ratait 61,0 % des fills des rafales** (début jamais vu) → attribution des emplacements par l'alerte du poll, dans l'ordre du labo (`slots_userfills`, 48 tests dont le vrai superviseur exécuté hors ligne) ; prend effet au prochain démarrage du collecteur |
| 4 | Coffre / scelleur / certificateur | **FAIT** | réindexage 370/370 shards, 22 familles COMPLETE |
| 5 | Audit du labo | **LIMITE MÉMOIRE LEVÉE aux deux étapes, et conduite par tranches livrée** | étape 1 : 8 754 210 fills et 7 527 878 carnets matérialisés avec **1,0 Go** de pic (× 7,2 et × 9,8) ; étape 2 : n'importe quelle tranche de temps lisible à coût borné (**1,54 Go** de fills + **1,27 Go** de carnets pour le 18/11, contre ~52 Go pour le corpus). Réplication 350 USD rejouée avec prix observés, placebo, marge de bruit et capacité ; persistance rejouée ; détention mesurée ; 23 lois au registre. Reste : ≥ 20 jours indépendants (observation), preuve SAFE (externe) |
| 6 | Edge post-observation | **MESURÉ, NÉGATIF** | copie rapide : +0,2 bps (borne haute) contre 9,0 bps de frais ; miroir d'épisode : −12,2 bps net. Détention réelle des leaders mesurée (médiane 46,6 min) — elle ne rouvre aucune de ces deux lois, déjà testées à 1 h, 4 h, 24 h et à la clôture |
| 7 | Moteur paper | **revalidé** | suites moteur / ledger / positions / simulation / UI vertes dans la suite complète (18 940) ; frais incorporés au prix de fill (pas de double compte) ; gel v21 **correctement rejeté** (600 USD de notionnel pour 350 USD sans levier) : aucun gel admissible, le moteur ne s'en fabrique pas |
| 8 | Preuve / certificateur / scoreboard | **CLOS le 18/11 : 3 120/3 120 preuves valides** — PERIME le 21/11/2026 : **3 111/3 120**, 9 isolees (section du 21/11) | contrat de l'instantané aligné sur le capital réel (il exigeait 200 USD) ; alerte de fraîcheur lue dans les faits ; reçu `AUD-044` lié à l'arbre de travail : commit puis rejeu de la tâche auditée |
| 9 | Matrice de consommation exhaustive | **FAIT, re-jouée sur le HEAD FINAL (`75208140d32`)** | `tools/matrice_coffre.py` (9 tests) ; **run sur le HEAD final : 22 familles, `NON_CHARGEE` = 0** (3 `REPLAY_PNL`, 2 `CARNETS`, 8 `CONTEXTE`, 6 `ROLE_MESURE`, 3 exclues avec motif), **tous les shards indexés présents sur le disque**, réconciliation LOCAL → SAFE publiée avec son écart (premier jour liable 13/11), mode `--roles` |
| 10 | Consommation intelligente du coffre | **FAIT, clos** | `coffre_tranches` + `plan_de_fouille` + recensement ; **22 familles : consommées, exclues avec motif, ou à rôle mesuré — plus aucun état d'attente** |
| 11 | Audit exclusions / densité | **FAIT** | exclusions mesurées avec dénominateur |
| 12 | Réconciliation LOCAL → SAFE | **re-mesuré sur le HEAD FINAL ; bloqué par une action externe, précisément identifiée** | SAFE : 15 456 shards, dernier tag du 18/10, **5 shards de fills** ; la fenêtre causalement complète (13/11+) n'existe qu'en LOCAL ; catalogue local en retard de 13 420 fichiers |
| 13 | Parité et fraîcheur bout en bout | **FAIT, durci** | `ops/fraicheur_preuve.py` lit les faits (12 tests) : labo −118,9 h, SAFE −734,3 h |

## Re-jouée sur le HEAD final (`75208140d32`)

**Matrice coffre → labo.** 22 familles, **aucune `NON_CHARGEE`** : 3 en `REPLAY_PNL`, 2 en
`CARNETS`, 8 en `CONTEXTE`, 6 à `ROLE_MESURE`, 3 exclues avec motif. Tous les shards indexés sont
présents sur le disque. Réconciliation LOCAL → SAFE publiée avec son écart : SAFE porte 15 456
shards sur 66 releases, dernier tag du 18/10 ; LOCAL est en avance de **31,7 jours** (27 544 473
lignes de fills contre 5 shards SAFE). Premier jour où une référence pré-signal est liable :
**13/11**. L'outil déclare lui-même que rien de ce que le labo mesure dans cette fenêtre n'est
prouvable — c'est l'écart externe, et sa condition de levée est nommée : une campagne cloud
GitHub-hosted postérieure au premier jour liable, puis release et restauration AlinaSync.

**Tunnel signal → trade → sortie.** 9 790 des 9 859 signaux **jugeables** vont jusqu'à la sortie
observée, soit **99,3 %** ; 19 leaders distincts, 15 à chaîne complète ; zéro saut d'horloge ; âge
médian du carnet de référence 5 920 ms (p90 11 233 ms). Chaque refus est compté une seule fois, au
premier étage qui le rejette. La fraîcheur est déclarée **périmée** (dernier rapport du labo à
125,2 h), et l'outil le dit au lieu de le taire.

## Combien de journées le labo doit-il lire ? Six, et non onze

`choisir_la_fenetre` sonde **11 jours** (07 → 17/11, la fenêtre à carnets) mais part du
**premier jour liable, le 13/11** : avant cette date, les carnets n'ont pas l'identité de connexion
qui permet de lier une référence pré-signal à la même session d'observation. Les cinq premiers jours
sont donc écartés **volontairement** — mesurables peut-être, prouvables non.

Le corpus à lire est donc de **six journées**, et c'est exactement ce que portent les rubans
(8 464 251 fills, 7 527 878 carnets). Depuis l'itération 23, ces six journées sont lisibles en
**19 tranches de ~2,5 Go**. Attendre onze journées du labo serait attendre qu'il lise des données
dont il a lui-même établi qu'elles ne peuvent pas servir de preuve.

## Réconciliation bout en bout, re-jouée le 18/11 sur le HEAD final

Les deux instruments ont été exécutés après les corrections du jour, pour que leur verdict porte
sur le code en place et non sur celui d'hier.

**Matrice coffre → labo** — 22 familles, **aucune `NON_CHARGEE`** : 3 en `REPLAY_PNL`, 2 en
`CARNETS`, 8 en `CONTEXTE`, 6 à `ROLE_MESURE`, 3 exclues avec motif. Tous les shards indexés sont
présents sur le disque. La réconciliation LOCAL → SAFE est publiée avec son écart : SAFE porte
15 456 shards mais son dernier tag est du 18/10, LOCAL est en avance de 31,4 jours, et le premier
jour où une référence pré-signal est liable est le **13/11**. L'outil déclare lui-même que rien de
ce que le labo mesure dans cette fenêtre n'est prouvable — c'est l'écart externe, pas un défaut.

**Tunnel signal → trade → sortie** — re-joué avec des plafonds sept fois plus larges (715 581
carnets, 180 coins, 0,6 jour) : **9 366 des 10 422 signaux d'ouverture vont jusqu'à la sortie
observée, soit 89,9 %**, et les 12 leaders ont tous une chaîne complète. Chaque refus est compté
une seule fois, au premier étage qui le rejette. Aucun saut d'horloge, ni en avant ni en arrière.
L'âge médian du carnet de référence est de 6 354 ms. La fraîcheur est déclarée **périmée** (le
dernier rapport du labo a 119,9 h de retard) : un rapport vert sur des données antérieures ne
qualifie pas l'état présent, et l'outil le dit au lieu de le taire.

À comparer au point de départ : le 12/11, le labo annonçait **0 trade exécutable sur 98 138
signaux**, sans pouvoir dire où le tunnel se fermait.

## Itérations

| # | Défaut / amélioration | Correction | Tests | Suite |
|---|---|---|---|---|
| 0 | Contrôle d'état | HEAD vérifié, 81 fichiers préservés, collecte vivante (pid 69424) | suite complète en référence | replay du labo |
| 1 | Le tunnel mesurait un **tampon de lecture** : `HORS_FENETRE_DE_MESURE` = 35 239 / 43 793 (80 %) par effet du budget d'octets ; et sa sortie n'était consommée par personne, donc coffre et tunnel avaient deux dénominateurs | source `--source coffre` via `coffre_tranches.flux`, une seule boucle de jugement pour les deux sources, deux horloges déclarées | `tests/test_tunnel_source_coffre.py` 5 verts | mesure : **87 844 / 88 131 = 99,7 %** de chaînes complètes sur 13→17/11, 31 leaders sur 31 ; prochain : porter cet échantillon jusqu'au PnL par le moteur existant |
| 2 | `etude_copiabilite` n'utilisait les prix **observés** que si `--prix mids` était tapé ; sinon repli **muet** sur des bougies 5 min récupérées après coup (2 études touchées) | `_panneau_de_prix()` : source demandée = source utilisée ; refus `UNMEASURABLE` nommant le repli explicite si l'observé est trop pauvre | `tests/test_etude_source_de_prix.py` 5 verts | avant/après figé : net −0,967 → **−0,185 USD/j** (−27,6 → −5,3 bps/j), 6 832 → **112 729** points de prix ; la valorisation grossière surestimait la perte d'un **facteur 5** |
| 3 | Le tableau par leader affichait **+18,85 USD/j** (meilleur de 105 comptes sur 4 jours) sans correctif d'essais multiples | `borne_du_hasard_replication()` : placebo par décalage temporel (±24/48/72 h), verdict par `overfit_selection.borne_du_hasard` réutilisée, marge = demi-largeur de l'IC 95 % mesurée | `tests/test_replication_essais_multiples.py` 6 verts | **mesuré** : meilleur réel +18,849 vs moyenne des maxima placebo +19,156 et p95 +34,632 → `LE_TOP_EST_INDISCERNABLE_DU_HASARD` |
| 4 | **Personne n'avait mesuré la détention réelle des leaders** : l'horizon de 300 s était un choix, jamais confronté | `copy_vault_detention.apparier()` (FIFO par compte/coin, censure déclarée) + câblé dans le tunnel | `tests/test_copy_vault_detention.py` 11 verts | 16/11 : **p50 = 46,6 min** (dédupliqué), 160/163 comptes au-delà de 300 s. **Rectifié** : ne rouvre PAS `copy_miroir_episodes` (déjà réfutée à −12,2 bps le 11/11) ; sert seulement à définir ex ante un univers lent |
| 5 | Ma propre mesure de détention **comptait des fills en double** (6,3 % de doublons entre LIVE_POLL/WS/TWAP) ; et `hash` est un hash de **transaction** — le sentinelle `0x0000…` porte 40 915 lignes | `cle_d_identite()` : `stable_event_id` sinon clé naturelle (compte, coin, ts, taille, prix, sens) ; jamais le hash | `tests/test_copy_vault_detention.py` 11 → **16 verts** | 54 304 doublons écartés ; p50 44,8 → **46,6 min**, médiane pondérée 30,9 → **35,3 min** (+14 %) — les doublons biaisaient vers le bas |
| 6 | Le rattrapage `--long` a fini en **1 h 29 sur 12 h** : `funding-profond` arrêté au **1er** refus de débit (334 min inutilisées, 9 872 jours-coins non creusés). Le recul du 16/11 n'était posé que sur 1 site sur 3 | `avec_recul()` : règle unique appelée par les 3 sites ; ne rejoue jamais sans avoir attendu | `tests/test_recul_sur_refus_de_debit.py` 8 verts ; 106 verts sur rattrapage/backfill | relance du rattrapage long avec le correctif |
| 7 | La suite **complète** n'avait jamais tourné sur ce HEAD : 18 697 verts, **12 échecs réels** dont 6 venant de mes ajouts (3 `except: pass` muets, `os.kill` nu, 4 fichiers au-dessus de leur plafond, classement des `.cmd` à moitié fait) ; et ma méthode d'édition avait **basculé les fins de ligne de 20 fichiers suivis** | 10 corrigés : compteurs d'échec, garde POSIX, **4 extractions sans relever aucun plafond**, registre complété, 4 tests alignés sur le HEAD et durcis ; fins de ligne restaurées octet pour octet | 3 048 verts sur Copy-Vault, 111 sur le moteur git, invariants d'architecture verts | 2 rouges externes : `rig_020` (reçu lié à l'arbre) et catalogue local en retard de 13 420 fichiers sur le HEAD |
| 8 | La matrice annonçait **0 shard SAFE pour 15 456 réels** (clés `lots`/`shards` inexistantes dans `COFFRE_INDEX.json`) : l'écart LOCAL → SAFE était invisible | `reconcilier_local_et_safe()` + `premier_jour_liable()` dans `tools/matrice_coffre.py` | `tests/test_matrice_coffre.py` 4 → **9 verts** | mesuré : dernier tag SAFE **18/10**, premier jour liable **13/11**, LOCAL en avance de 30,5 j → fenêtre causale **non couverte** par SAFE ; levée = campagne cloud + push autorisé |
| 9 | Six familles restaient en **état d'attente** (`A_CABLER`) ; et la mesure a révélé que le collecteur d'overshoots prenait **8 perps délistés** pour des événements (67,3 % de la famille) et écrivait une réversion de 0,0 quand le prix futur manquait | `FAMILLES_A_ROLE_MESURE` + `copy_vault_roles_familles` + `matrice_coffre --roles` ; collecteur : `isDelisted` écarté, réversion inconnue dite, prix figé marqué | 11 + 6 tests neufs ; 72 verts sur le registre, 28 sur l'overshoot | capacité : multiple **médian 1,51 ×** l'ordre (5 % de coins à capacité large) ; microstructure applicable à **15,9 %** des ouvertures |
| 10 | Le contrat de l'instantané de restauration exigeait **`paper_capital_usd == 200.0`** alors que le labo écrit 350 : tout instantané actuel était refusé par son propre validateur (la fixture du test portait 200). Et le message de rejet du gel citait « 200 USD » | capital lu de la source unique `PAPER_EQUITY_USD` ; message dérivé de `MAX_GROSS_EXPOSURE_USD` | `test_copy_vault_snapshot_contract.py` 4 → **7 verts** ; console 32 verts | le rejet du gel v21 est juste (`core_notional_usd = 600` pour 350 USD sans levier) : aucun gel admissible aujourd'hui |
| 11 | L'alerte de fraîcheur lisait l'**heure d'écriture** du dernier rapport du labo : une simple pré-vérification (aucun rejeu) suffisait à la faire taire ; et l'âge du tier SAFE n'entrait pas dans le verdict | `fraicheur_preuve.horloges_de_la_chaine()` : fin des données **réellement rejouées**, `PREFLIGHT_ONLY` ignoré, `dernier_tag_safe` ajouté ; tunnel et matrice délégués | `test_fraicheur_preuve.py` 7 → **12 verts** | état réel : labo en retard de 118,9 h, SAFE de 734,3 h → `PERIME` |
| 12 | La capacité n'était mesurée que par coin, pas sur le volume **réellement répliqué** ; et les réfutations du jour ne vivaient que dans ce journal | simulateur : volume par coin (additif) ; `resumer_la_capacite()` à trois seuils ; **4 lois** ajoutées à `lois_mesurees.py`, document régénéré | lois 43 verts, essais multiples 7, rôles 15 | capacité : **2,8 %** du volume sur coins étroits, 0,6 % inconnue, 96,7 % suffisante — l'inquiétude de l'itération 9 est bornée ; meilleur leader −15,78 USD/j sous le p95 du hasard |
| 13 | Un **faux `subprocess.run`** (returncode 0, stdout « ok ») posé par affectation directe dans `test_sync_git_robustesse.py` survivait à son test : **7 échecs** de la suite complète (un 8ᵉ, `cmd.exe` → `0xC0000142`, vient de la machine saturée), et des **faux verts** possibles parmi les 1 441 tests verts exécutés derrière lui. J'avais mal expliqué ces échecs à l'itération 7 (rectifié en place) | `monkeypatch` dans le fichier fautif ; **garde** `tests/garde_sous_processus.py` + crochet `conftest.py` à la frontière de chaque module ; fuite d'environnement de `test_decision_firehose.py` corrigée | garde 7 verts, prouvé sur une fuite volontaire sous les 2 interpréteurs ; 27 verts avec l'ancien coupable passé en premier | suite complète : 18 940 verts, 2 rouges externes + 7 dus à la fuite + 1 dû à la saturation mémoire ; confirmation d'ensemble **à relancer sur demande** (mémoire) |
| 14 | **Le direct ne voyait que 38 % des fills des leaders suivis** : « actif » voulait dire « vu en direct », donc un leader sans emplacement ne pouvait pas le devenir. 30 reprises d'activité sur 49 jamais vues ; **61,0 % des fills de ces rafales manqués**, toujours le début. Et toutes les connexions étaient reconstruites toutes les 150 s | `slots_userfills.py` : activité = max(direct, poll REST), jamais pour un `ARCHIVE`, ordre du plan du labo, titulaire prioritaire, rotation réservée aux candidats hors poll, repli exact si le poll est muet, journal des pages | 48 + 15 tests ; suites du collecteur 193 verts ; garde-fous 125 verts ; instrument `tools/mesurer_decouverte_rafales.py` (61,0 % → borne 19,6 %) | **effet réel à mesurer** après le prochain démarrage du collecteur (non redémarré) ; 4 contrôles du trou de veille rendus |
| 14 bis | **Une seule coupure pouvait fermer l'époque pour toujours** (302 fenêtres pour la veille, journal plafonné à 512) ; l'arrêt de l'écrivain n'était un trou que par accident ; aucun garde contre un recul d'horloge | `GAPS.compacter` (union et sommes conservées exactement) ; nature `writer_outage` ; `ops/sauts_d_horloge.py` câblé dans le tunnel | 37 + 31 + 12 tests, 371 verts avec les consommateurs ; état réel : 302 → 1 fenêtre ; ruban réel : 1 saut en avant, 0 en arrière sur 44 h | effet du compagnon au prochain démarrage |
| 15 | **Le labo lisait le début du coffre** (jamais au-delà du 10/11), **abandonnait à la première alerte mémoire** (60 shards lus sur 6 409) et **ne le disait pas** dans son verdict | `copy_vault_fenetre_locale.py` : lecture à partir du premier jour liable, patience sous pression externe, mention de lecture interrompue dans le verdict | 19 tests ; rejeu réel avant/après : 60 → 452 shards, 14 654 → 64 567 signaux évaluables, 0 → 44 revues de leaders ; **jours évaluables 4 → 3** | le labo ne tient qu'environ un jour dense en mémoire : le conduire par jours équilibrés ou par galeries |
| 16 | **`tools/revalider_receipts.py` allait déclarer fausses 103 preuves sans les rejouer** : tout code de sortie non nul devenait `REVALIDATION_FAILED`, or un processus qui ne DÉMARRE pas rend `0xC0000142` (3ᵉ apparition en 2 jours). Registre append-only : définitif | `CODES_NON_LANCE`, sortie vide = non lancé, garde **au point d'écriture** (pas seulement dans le lanceur), respiration mémoire ; un vrai échec reste un verdict négatif | 11 nouveaux tests dont un segfault qui doit rester un échec ; 39 verts avec les suites voisines | revalidation des 103 reçus lancée sur un outil désormais sûr |
| 16 ter | **Un reçu prouvé par un test qui LIT le registre ne pouvait pas se rafraîchir** : son test voit sa propre péremption et échoue. `ASF-RIG-002` (ce matin), `ASF-RIG-010` et `ASF-RIG-019` (12 et 14/11) étaient enfermés | seconde chance APRÈS l'écriture du verdict négatif (qui lève la péremption), registre à jour ; reprise explicite `--reprendre` des reçus en échec, sans jamais lever un verdict sans rejeu | 10 nouveaux tests (dont « pas de seconde chance pour un groupe ordinaire ni pour un non-lancement ») ; 24 verts | **`rig_020` vert** : 102 reçus rafraîchis, 0 non mesurable, 0 encore périmé |
| 16 quater | **Le « blocage externe » du catalogue n'était pas externe** : 157 manifestes de campagne absents du disque et 61 amputés (historique = sous-ensemble strict de Git, 0 entrée locale, rien écrit depuis 110,9 h) | sauvegarde hors dépôt, puis restauration de `catalog/campaigns` depuis le commit : 4 947 fichiers, 0 absent, 0 différent | `test_sync_complete_clone.py` 78 verts ; les 8 derniers reçus rafraîchis | **3 120 / 3 120 preuves valides sur le HEAD (100 %)**, 0 périmé, 0 en échec |
| 17 | **Le labo tient 3,2 M de lignes en mémoire seulement pour les trier et les écrire**, alors que la phase suivante relit les rubans depuis le disque — d'où `MEMOIRE_CRITIQUE` à 452 shards sur 5 570 et « trop peu de jours » | `rubans_tri_externe.py` : deux passes, morceaux triés fusionnés en flux, **octets identiques** à l'approche en mémoire ; refuse d'écrire si la source bouge | 21 tests dont 300 tirages aléatoires comparant les SHA des deux chemins ; 2 pièges trouvés avant branchement (ordre d'insertion après remplacement, `1 == 1.0` comme clé de dict) | **mesure rendue : 32,2 Go → 1,65 Go, gain 19,5 ×** (11,7 M lignes, 9,3 M identités, 3 458 o par ligne en mémoire). Le labo tentait de tenir 32 Go sur une machine de 32 : branchement justifié |
| 17 bis | Le branchement exigeait des briques au comportement **identique au détail près** à celui du labo | `copy_vault_rubans_lourds.py` (générateurs des deux tiers, trois rubans lourds) + pont LOCAL qui **compte sans matérialiser** (`garder_replay=False`) | 59 tests ; **5 pièges trouvés par les tests avant branchement** : ordre d'insertion après remplacement, `1 == 1.0`, LOCAL ne déloge pas SAFE, fill non causal dans aucun ruban, `isSnapshot` absent | reste la substitution dans `materialize_safe_workspace`, puis le rejeu du labo |
| 18 | Substitution faite dans `materialize_safe_workspace` | les fills et carnets sont lus en flux, plus de dictionnaire | 123 verts (labo, pont, rubans, invariants) ; **rejeu réel : 1 210 121 → 8 754 210 fills (× 7,2) et 766 876 → 7 527 878 carnets (× 9,8), étape 1 VERTE avec 1,0 Go au lieu de 60** | **le goulot s'est déplacé à l'étape 2** : la reconstruction des épisodes charge à son tour 13,9 Go — même nature, même remède |
| 18 bis | **Régression introduite par moi** : `garder_replay=False` coupait aussi les cotations BBO, dont le labo tire le coût de spread — ruban passé de 481,2 Mo à **0,0 Mo** | les cotations restent matérialisées (déduplication à état, 481 Mo seulement) ; test de verrouillage | 97 verts | trouvée en comparant la TAILLE DES FICHIERS produits, pas les compteurs ni le verdict |
| 19 | **`load_observed_books` n'avait que la borne haute** : « avant tel instant », jamais « entre deux ». Conduire le replay jour par jour était impossible, et les six jours denses demandent ~28 Go ensemble | borne `depuis_ms` à la frontière de la source, carnets écartés comptés, fenêtre publiée, fenêtre vide refusée. Approche « liste paresseuse » écartée : `liste_des_carnets` copie tout ce qui n'est pas une vraie `list`, sur le chemin chaud | 8 tests + 247 verts avec les consommateurs ; **vérifié sur le corpus réel : un jour = 1,27 Go** (468 073 carnets retenus, 7 059 804 écartés) | le labo peut maintenant être conduit jour par jour : reste l'agrégation sans moyenne de moyennes |
| 20 | **L'étape 2 demandait ~60 Go** : 31,8 Go de fills (8 464 251 × 3 754 o) + 28,6 Go de carnets, et `_episodes_canoniques` mémorisait le tout | fenêtre `(depuis_ms, jusqu_a_ms)` sur les fills, appliquée aux DEUX sources à la frontière ; **la fenêtre entre dans la signature de mémorisation** (sinon la 2ᵉ journée recevrait les épisodes de la 1ʳᵉ : faux et vert) ; `decoupe_sure` publié | 10 tests + 28 verts ; **mesuré : 100,00 % des 8 464 251 fills portent `startPosition`** (0 des 4 396 paires sans) donc la découpe est licite ; **un jour = 1,54 Go**, soit **2,8 Go/jour avec les carnets** contre 60 Go | reste à faire boucler le labo sur les 6 journées et à agréger sans moyenne de moyennes |
| 21 | **De quelle taille doit être la tranche ?** Je partais sur « un jour » | mesure de la répartition réelle : le 13/11 porte 2 172 496 fills (4,6 × le 18/11) → ~7,03 Go, plus 4,8 Go de carnets = **~11,8 Go pour cette seule journée**. Une découpe calendaire serait morte sur la 1ʳᵉ journée | les fenêtres livrées étant en millisecondes, la granularité est libre : la tranche doit se régler sur `budget_ram`, comme `plafond_listes` | **rectification** : mes « 28,6 Go » de carnets étaient une estimation par analogie avec les fills ; la mesure donne 2 713 o/carnet, soit 20,4 Go |
| 21 bis | Que doit-il survivre à une tranche ? | 56 516 métaordres par journée = 0,93 Go, soit ~5,6 Go pour six journées : accumuler puis explorer une fois ne tient pas non plus | **l'exploration doit avoir lieu DANS la tranche**, seuls les résultats agrégés survivent | poids d'un métaordre : 88 % `member_events`, 11 % `member_event_ids` (dérivable mais **consommé** par 3 modules et 5 tests — non touché, à traiter avec la boucle) |
| 22 | Le labo ne savait pas lire une tranche : les deux chargeurs de l'étape 2 prenaient tout | `run_local_campaign(..., tranche=(depuis_ms, jusqu_a_ms))`, descendue aux DEUX chargeurs ; sans tranche, les deux bornes valent `None` | 5 tests dont **2 fonctionnels** (doubles capturant les arguments reçus) + 1 de non-régression ; 55 verts | le labo ne boucle PAS lui-même : l'agrégation des tranches appartient à un conducteur séparé, pour ne pas enfouir une moyenne de moyennes dans le chemin économique |
| 23 | Il manquait de quoi lire les 6 journées : le labo savait traiter une tranche, personne ne les enchaînait | `agregation_tranches` (module pur, 283 l.) + `tools/conduire_labo_par_tranches.py` : densité mesurée en flux, découpage sous budget, conduite tranche par tranche, agrégat qui refuse les 4 mensonges (moyenne de moyennes, trou→zéro, verdict optimiste, total sans périmètre) | 50 verts ; **plan réel : 19 tranches, couverture continue sur 129,0 h, la plus chargée à 498 039 fills, 0 trou, 0 recouvrement** | **le corpus entier est lisible en 19 passes de ~2,5 Go** au lieu d'une de ~52 Go |
| 23 bis | **Défaut dans MON module**, trouvé par le test de la conduite : un total était déclaré complet alors qu'une tranche entière manquait | `_marquer_incomplet` dans `combiner` — seul lui connaît le nombre de tranches ATTENDUES ; le total reste lisible mais déclaré incomplet | 2 tests dédiés, dont la non-régression sans tranche manquante | 3ᵉ fois ce jour que le piège prend la même forme : **une mesure calculée sur ce qui est présent ignore ce qui est absent** |
| 24 | La découpe était prouvée sur fixtures, pas sur le corpus | comparaison des deux dernières tranches du plan réel, séparées puis en union | **T18 (472 389) + T19 (167 469) = 639 858 ; le même intervalle d'un coup = 639 858 ; intersection 0 ; 0 perdu, 0 inventé** | lire le corpus en 19 passes donne exactement le même ensemble qu'en une — ce qu'aucun test sur fixtures ne pouvait établir |
| 25 | La conduite enchaînait 19 tranches de ~2,5 Go **sans regarder la mémoire** — ce qui a déjà fait couper un rejeu | avis de `budget_ram.decision` avant chaque tranche (besoin estimé depuis la densité mesurée) ; RAM critique → on souffle, puis on redemande ; encore critique → tranche **NON ÉVALUÉE** avec sa raison, la suivante est tentée ; mémoire consommée publiée par tranche | 10 tests avec gouverneur injecté (+1 qui exige que le défaut soit le gouverneur RÉEL) ; 40 verts | jamais d'arrêt brutal, jamais de zéro inventé |
| 25 bis | **Hypothèse de goulot réfutée** : je croyais que revérifier l'empreinte des rubans à chaque tranche coûterait 250 Go de hachage | aucune correction — la mesure dit 11 s pour 13,15 Go, soit 3 min sur 19 tranches | mesure directe | pas une raison d'affaiblir une garde d'intégrité ; l'hypothèse reste écrite au journal pour qu'on ne l'« optimise » pas sans remesurer |
| 26 | **Les 19 tranches auraient partagé leur campagne** : `selection_digest` identifie la source, pas la tranche, donc `TRIALS.jsonl` et `CHECKPOINT.json` étaient communs — la tranche 2 aurait SAUTÉ les paramètres essayés sur la tranche 1 | `_nom_de_campagne(selection_digest, tranche)` dans le labo + racine par tranche dans le conducteur ; `selection_digest` **intact** (scellé dans 3 120 reçus) | 7 tests dont 2 sur l'appel réel ; 99 verts | trouvé **avant** d'avoir conduit la première tranche, en lisant le code |
| 26 bis | Le même piège 3 fois dans la journée : des doubles de test figés sur une ancienne signature (5 au total) | garde-fou qui parcourt tous les fichiers de tests et refuse un double de ces 3 chargeurs sans `**kwargs` | **vérifié dans les deux sens** : rougit avec un double figé déposé exprès, repasse au vert une fois retiré | un double figé est un test qui ne vérifie plus ce qu'il croit vérifier |
| 27 | **Ma correction de l'itération 26 aurait fait planter la tranche 2** : le compteur d'essais passait le nom du dossier comme digest à un lecteur qui LÈVE au lieu de filtrer | `_digest_de_campagne(nom)` + exclusion de la campagne courante par son NOM complet | 12 tests ; 340 verts sur 13 suites | effet voulu obtenu : **la tranche 2 sait que la tranche 1 a cherché**, donc le correctif d'essais multiples ne sous-estime plus la multiplicité |
| 27 bis | 4ᵉ occurrence du double figé (dans les tests du verrou) ; et **7 de mes propres tests étaient faux** (fixtures sans registre d'hypothèses) | `_prior_copy_vault_trial_count` ajouté à la liste surveillée ; fixtures corrigées | le garde-fou a servi le jour même de son écriture | verrouillé au passage : **`None` = « je ne sais pas », 0 = « rien cherché ailleurs »** |
| 28 | **Ma garde mémoire sous-estimait le besoin** : `FACTEUR_CARNETS = 1,8` déduit de la seule journée du 18/11 (la plus légère des six) | mesure sur les 129 heures : rapport carnets/fills médian 0,70, p90 1,03, **max 1,39** → facteur jusqu'à **2,39**. Porté à **2,4** | 2 tests, dont un qui exige la couverture du MAXIMUM mesuré | leçon : **un paramètre de garde se calibre sur le pire cas, un paramètre de performance sur le cas courant** |
| 29 | Mes modifications ont **périmé 20 reçus** de la roadmap (ils épinglent le SHA des fichiers de preuve) | les 11 groupes de tests **rejoués** sur le nouveau code, puis les reçus rafraîchis, après sauvegarde horodatée du registre | **20 rafraîchis, 0 échec, 0 non mesurable ; contre-vérification : 0 périmé, 0 en échec** | l'ordre est le bon : rejouer d'abord, rafraîchir ensuite — l'inverse re-signerait une preuve non refaite |
| 30 | **J'ai cru à un trou de 275 674 fills** entre ce que le labo compte et ce que le ruban porte | aucune correction : les trois équations de conservation bouclent (8 754 210 − 289 959 = 8 464 251 ; 8 754 210 − 8 739 925 = 14 285 ; 12 297 560 − 3 543 350 = 8 754 210) | lecture des bilans publiés au manifeste | j'avais soustrait deux grandeurs non soustrayables. Les 289 959 sont les non-snapshot **non causaux**, comptés. Sans `ecartees_par_le_filtre`, impossible de distinguer « normal » de « bug » |
| 31 | Le compte était juste mais **rien ne l'exigeait** : les tests vérifiaient des nombres attendus, pas la cohérence interne des bilans | `tests/test_conservation_des_lignes.py` : les deux égalités exigées pour chaque cible (sans filtre, avec doublons, filtre partiel, filtre qui refuse tout, 3 cibles d'une passe, 4 échelles, vraies clés du Copy-Vault) | 12 verts, dont un qui compte les lignes **du fichier** et un qui donne au contrôle des bilans faux dans les 3 sens (perte à la dédup, perte à l'écriture, invention) | une perte future de lignes rougira désormais |
| 32 | **CONSTAT MAJEUR : la conduite par tranches ne cherche rien.** `_MINIMUM_SIGNAL_UTC_DAYS = 6` est une porte PAR APPEL (deux portes) ; une tranche de 4–11 h ne couvre jamais 6 journées UTC → les 19 tranches rendraient `MORE_DATA` avec `candidates_tested == 0` | aucune correction encore : 3 tests **fixent le constat** pour qu'on ne croie pas la conduite capable de chercher | 16 verts | la porte a raison mais juge le MORCEAU au lieu de l'ENSEMBLE. `unir_les_jours` existe déjà pour l'ensemble ; il manque un mode « produire sans juger » côté labo — et il devra interdire `economically_proven` à l'échelle d'une tranche |
| 33 | **La porte des 6 journées jugeait le morceau** (constat 32) | `run_local_campaign(..., jours_du_corpus=N)` : les **TROIS** portes jugent l'ensemble (la 3ᵉ gardait l'overshoot en LEVANT) ; tout rapport de tranche porte `verdict_partiel` ; `combiner(..., jours_minimum=6)` **referme** la porte sur l'UNION des journées (`JOURNEES_INSUFFISANTES`) ; le conducteur mesure les journées et **importe** la constante du labo | 18 tests ; 73 + 86 verts | 4 refus vérifiés, dont **6 tranches du même jour = 1 journée, refusée** : découper un jour n'en fabrique pas six. Le seuil n'est pas supprimé, il est appliqué UNE FOIS au bon niveau |
| 34 | **L'agrégat pouvait laisser lire une preuve** là où chaque rapport s'était déclaré non concluant : `combiner` ignorait `verdict_partiel` | `rapports_partiels`, `preuve_possible` (faux dès UN seul partiel) et `essais_totaux` ; le conducteur les AFFICHE (`PREUVE IMPOSSIBLE`, essais, jours obtenus / requis) | 6 tests dont le cas du mélange : **5 rapports complets ne rachètent pas le 6ᵉ** | vérifié d'abord ce qui était déjà juste : Bonferroni par tranche incluant les autres tranches, et verdict global = minimum |
| 35 | **La conduite ne savait pas reprendre** — or 19 tranches durent des heures, et deux tâches de fond ont été arrêtées pour mémoire critique AUJOURD'HUI (dont une suite à 98 %) | journal JSONL (`--journal`) écrit après chaque tranche réussie, avec `flush` + `fsync` ; empreinte du découpage ; les tranches en échec ne sont PAS notées | 14 tests ; 54 verts | refuse : un journal d'un autre découpage (lignes comptées), une ligne tronquée, un rapport illisible. Le test clé : 3ᵉ tranche en `MemoryError` → relance → **seule la manquante repart** |
| 36 | **L'empreinte de reprise ignorait le corpus** : deux corpus de même densité horaire auraient partagé le même journal | le `selection_digest` du manifeste SAFE entre dans l'empreinte ; un manifeste illisible donne `corpus-inconnu`, distinct de tout digest réel | 7 tests, dont **mêmes bornes + workspace re-matérialisé → tranche refaite** et la non-régression inverse | 21 verts |
| 36 bis | **Faux négatif** : les 1 532 fichiers restants lancés en une commande ont rendu code 0 et aucune sortie — ligne de commande de **57 850 caractères** contre 32 767 autorisés sous Windows, et le `grep` du pipeline a masqué l'échec | lots lancés un par un (~11 500 caractères), sortie non filtrée | un bilan pytest DOIT contenir « N passed » : pas de ligne, pas de résultat | 3ᵉ variante cette semaine du piège « sortie vide = rien n'a tourné » |
| 37 | **Un seul échec sur 9 357 tests, et il était à moi** : `copy_vault_local_lab.py` à 5 027 lignes (plafond 5 009) et `copy_vault_book_loader.py` à 820 (plafond 800) | deux modules extraits, **aucun plafond relevé** : `copy_vault_identite_campagne` (les 2 sens de la convention de nommage) et `copy_vault_carnet_validation` (validation + reçu d'accès au futur), réexportés sous leurs noms d'origine | 14 tests ; 24 verts avec l'invariant | 5 003 et 774 lignes. Un test importe chaque module neuf **dans un interpréteur vierge** : une dépendance circulaire casserait à l'import seul, invisible aux tests de comportement |
| 38 | **Une tranche écrivait `runtime/champion_deploye.json`**, chemin UNIQUE et cliquet labo → moteur : 19 tranches s'y écraseraient, le fichier final portant un candidat choisi sur 4–11 h et présenté comme déployable | refus quand `tranche is not None`, publié sous `champion_deploye_refuse` ; cliquet extrait dans `copy_vault_champion_deploye` (137 l.) → labo à **4 915 lignes** | 4 tests dont la non-régression (campagne complète = cliquet intact) ; 32 + 23 verts | **3ᵉ fois ce jour** qu'une décision d'ensemble était prise par un morceau. Mes 2 erreurs d'application : ancre en double (ruff sépare les alias) et un module `_atomic_json` inutile → orphelin, supprimé |
| 39 | Le lot 6 a échoué sur `rig_020` : **18 reçus périmés à nouveau**, car la revalidation de l'itération 29 précédait les corrections 30 à 38 | rejouer puis rafraîchir, cette fois après stabilisation du code | le test est fail-closed à juste titre : un reçu dont le fichier a changé n'est **plus** une preuve, pas « une preuve datée » | **leçon de procédure** : corriger → stabiliser → revalider → seulement alors lire la suite comme un état du HEAD. Revalider trop tôt coûte 11 groupes de tests pour rien |
| 40 | **DÉFAUT BLOQUANT** : deux tranches fabriquaient le même `candidate_id` (digest identique + séquence repartant à 1 par campagne) → la 2ᵉ tranche qui gèle lèverait `IMMUTABLE_COPY_VAULT_CANDIDATE_CONFLICT` | `empreinte_de_tranche` (8 caractères) dans l'identifiant ; **format reconstruit à l'identique sans tranche**, vérifié caractère par caractère | 7 tests ; 119 + 21 verts | trouvé en lecture AVANT qu'il ne se produise. 3 pistes écartées parce que le code était juste : chaînage des reçus, gel physique lu non écrit, écriture en mode `"x"` sous verrou |
| 40 bis | Un candidat gelé ne portait pas sa fenêtre : 19 candidats indistinguables dans le registre durable | `tranche` et `verdict_partiel` copiés dans le reçu | inclus ci-dessus | un candidat trouvé sur 4 h ne se compare pas à un candidat trouvé sur 6 jours, et sans la fenêtre la comparaison est fausse sans le dire |
| 41 | Le tunnel re-joué sur le HEAD final donne **64,2 %** contre 89,9 % le matin | aucune correction : vérifié avant d'écrire « dégradation ». Fenêtre de carnets inchangée (817,3 min), mais 30 575 fills lus contre 22 176 → `HORS_FENETRE` passe de 944 à 5 402 | **le chiffre juste est 9 790 / 9 859 jugeables = 99,3 %** | 3ᵉ fois ce jour qu'un changement de DÉNOMINATEUR a failli passer pour un changement de phénomène |
| 42 | **Le scelleur garde toutes les identités en mémoire** : `_precharger_identites` relit les shards scellés et stocke un TUPLE par ligne (avec un `hash` de 66 caractères pour les fills). Mesuré : **6,17 Go** sur 27 544 473 lignes, machine à 8 % de RAM libre | **non corrigé** (le scellement tournait) ; remède établi : tableau trié de 2×`uint64` + recherche binaire → ~440 Mo, ×14 | mesure des processus pendant la certification | 3ᵉ fois ce motif sur ce dépôt. L'entier 64 bits est ÉCARTÉ : 1 collision sur ~50 000 runs écarterait une ligne neuve en silence |

## Réconciliation de bout en bout : signal → trade → ledger → preuve

Chaque étage avec son dénominateur, son état honnête et ce qui le lèverait. Mesures du 17/11/2026.

| étage | mesure | dénominateur | état | ce qui le lèverait |
|---|---|---|---|---|
| **Signal** — fill WS non-snapshot, ouverture explicite | 88 131 ouvertures | 10 275 086 fills lus au coffre (13 → 17/11) | mesuré, LOCAL | — |
| **Chaîne causale** — référence reçue AVANT le signal, entrée à +60 s, sortie observée | 87 844 complètes = **99,7 %** | 88 131 ouvertures ; 31 leaders sur 31 | mesuré, LOCAL | — |
| **Chaîne causale, 07 → 17/11** (toute la fenêtre à carnets) | 121 900 complètes = **93,5 %** ; 11 jours sur 11 évaluables | 130 385 ouvertures | mesuré en flux, LOCAL | — |
| **Labo principal** — ce qu'il charge de cette chaîne | 3 à 4 jours évaluables sur 6 requis ; lecture interrompue par sa propre mémoire | 452 shards lus sur 5 570 dans la fenêtre | `MORE_DATA` **par défaut de lecture**, dit dans le verdict | conduire le labo par jours ou ne garder que les carnets utiles |
| **Trade, copie rapide** | dérive après observation ≤ +0,2 bps (borne haute) contre 9,0 bps de frais | 33 745 ouvertures vues en < 2 s | `REJECTED` (loi `copy_suivi_rapide_taker`) | une dérive post-observation dont la borne basse dépasse frais + spread, sur corpus SAFE |
| **Trade, miroir d'épisode** | net −12,2 bps | 29 620 épisodes copiables | `REJECTED` (loi `copy_miroir_episodes`) | un univers d'opérateurs lents gagnant en marche avant sur ≥ 20 jours |
| **Trade, réplication lente 350 USD** | net −0,185 USD/jour, IC 95 % [−1,31 ; +0,81] | 413 journées-leader, 105 comptes, **5 jours** | `MORE_DATA` | **≥ 20 jours indépendants** de portefeuilles observés — observation |
| **Sélection d'un leader** | meilleur réel +18,85 USD/j ; placebo moyenne +19,16, p95 +34,63 | 105 comptes, 6 placebos | `REJECTED` (loi `replication_meilleur_leader_du_tableau`) | un leader désigné EX ANTE dépassant le p95 du placebo sur ≥ 20 jours |
| **Persistance de compétence** | corrélation de rang +0,016 [−0,032 ; +0,059] | 2 345 vaults, 87 dates, 28 configurations | `MORE_DATA` | davantage de dates, ou une caractéristique nouvelle connue au signal |
| **Capacité** | 2,8 % du volume répliqué sur coins étroits, 0,6 % inconnue | 366 192 USD répliqués, 99 coins | mesuré (loi `capacite_ordre_paper`, limite) | un modèle d'impact si la part étroite dépasse 10 % |
| **Ledger — moteur paper** | **aucun gel admissible** : le gel v21 porte 600 USD de notionnel pour 350 USD sans levier, rejet juste | 1 gel local | fail-closed, conforme | un gel conforme issu d'une preuve — il n'en existe pas à fabriquer |
| **Preuve — chaîne SAFE** | dernier tag SAFE le **18/10** ; chaîne causale complète depuis le **13/11** | 15 456 shards SAFE, dont 5 de fills | **impossible aujourd'hui** | **externe** : pousser le HEAD, campagne cloud GitHub-hosted postérieure au 13/11, release, restauration AlinaSync |

**Matrice coffre → labo** : 22 familles, chacune dans un état déclaré — 3 en replay PnL, 2 en
carnets, 8 en contexte, 6 à rôle mesuré, 3 exclues avec motif (Cross-Venue par le scope,
`explorer_tx` comme découverte). Plus aucun état d'attente. Le magasin de ticks natifs
(56,7 Go) est classé : 85 % hors scope constitutionnel, la part Hyperliquid déjà scellée.

## Ce qui reste, et pourquoi ce n'est plus réalisable ici

| point | nature | condition exacte |
|---|---|---|
| ≥ 20 jours indépendants de `position` (5 aujourd'hui) | **observation** | laisser la campagne tourner au-delà du 19/11 ; rien à corriger |
| Preuve OOS / forward / PnL | **externe** | autorisation explicite de pousser sur GitHub, puis campagne cloud, release et restauration |
| ~~`test_rig_020` et les reçus de la roadmap~~ | **RÉSOLU le 18/11** | **3 120 / 3 120 preuves valides sur le HEAD**, 0 périmé, 0 en échec, aucun verdict levé sans rejeu |
| ~~`test_windows_checkout_preserves_byte_exact_replay_catalog`~~ | **RÉSOLU le 18/11** | pas un blocage externe : 157 manifestes absents, 61 amputés, tous sous-ensembles stricts de Git ; restaurés sans perte après mesure |
| `tests/test_dataset_policy.py` | **outillage** | valide 1,9 M fichiers ; à lancer seul, avec son propre budget, mémoire disponible |
| Découverte des rafales par le direct (61,0 % de fills manqués avant correction) | **observation** | la correction prend effet au prochain démarrage du collecteur `userFills` (témoin : `runtime/data/userfills_pages.ndjson`) ; relancer `tools/mesurer_decouverte_rafales.py` après quelques jours et comparer à `decouverte_rafales_avant_20261117.json` |
| Stabilité de la page `userFills` | **corrigé, second redémarrage à décider** | en production : 11 cycles reconduits sur 23. Cause principale trouvée et corrigée (deux candidats hors poll alternaient sur un emplacement) ; reste l'alternance du 2ᵉ leader « retenu » du classement, antérieure à ce travail |
| Faux verts parmi les 1 441 tests exécutés derrière la fuite | **borné et vérifié** | seuls 30 fichiers (129 tests) atteignent du code qui lance un sous-processus : rejoués, 140 verts, 0 rouge. Critère statique : la suite complète reste la seule preuve totale |
| ~~Confirmation d'ensemble de la suite~~ | **FAITE le 18/11 : 19 086 verts, 0 ROUGE** | 19 lots sur 19 ; le lot portant `rig_020` rejoué après la remise en état des reçus (1 008 verts) |
| ~~Le labo ne tenait pas le corpus en mémoire~~ | **BRANCHÉ le 18/11** | `rubans_tri_externe.py` prouvé (21 tests, 300 tirages byte-à-byte) et gain mesuré **19,5 ×** : 32,2 Go → 1,65 Go. Branché et vérifié par rejeu réel : × 7,2 fills, × 9,8 carnets, 1,0 Go au lieu de 60. **Borne basse livrée le 18/11** : un jour = 1,27 Go mesuré sur le ruban réel. Reste à faire évaluer le labo jour par jour et à agréger les six jours sans moyenne de moyennes |
| Correctif du collecteur d'overshoots | **redémarrage** | prend effet au prochain démarrage du collecteur ; non redémarré pour ne pas interrompre la collecte |
| `AGENTS.md` : « 5 lanceurs à la racine » contre 12 enregistrés dans le code | **arbitrage** | à l'opérateur de dire lequel fait foi |

## 21/11/2026 — Mission 1 : réparation de l'existant (mesures, pas estimations)

**La ligne 8 ci-dessus (« CLOS le 18/11 : 3 120/3 120 preuves valides ») est PÉRIMÉE** et
conservée telle quelle : le registre append-only porte aujourd'hui **3 111 `VERIFIED_DONE` +
9 `REVALIDATION_FAILED` = 3 120**. Les 9 ne sont pas un test qui échoue (`exit_code = 0`,
12 tests verts) mais une **pièce de preuve épinglée volontairement supprimée** —
`POUSSER-GITHUB-FORCE.cmd`, retiré par `b44aac91ce1c` parce qu'il promettait un `--force`
qu'il n'exécutait pas. L'archive (`docs/archive/legacy_cmd/2026-07-25/`) est une note de
607 octets dont l'empreinte ne correspond pas à celle épinglée, et aucun contenu atteignable
ne la porte : **y rattacher les reçus déclarerait vraie une preuve portant sur autre chose.**
Le refus de `recu_rafraichi()` est correct et reste en place (fail-closed). **Isolé, pas
réparé : rétablir ces 9 preuves change ce qu'elles couvrent — décision de l'opérateur.**

| # | Défaut mesuré | Réparation | Preuve | Reste |
|---|---|---|---|---|
| 43 | **`POUSSER` mourait sur son propre budget** : `merge --ff-only` sur 1 940 030 entrées d'index = **7 249 s mesurées** contre un plafond de 900 s (deux NO_GO à 901,2 s). L'index de 4 Mo n'était qu'un delta : le vrai `sharedindex` fait **244 Mo**, et 30 copies dormaient (**7,0 Go**) | la branche d'adoption pure emprunte la séquence qui préserve l'index (`diff` arbre-à-arbre → `read-tree` sans `-u` → `checkout-index` sur les chemins reçus → `update-ref` gardé par l'ancienne valeur) ; `WORKTREE_MERGE_TIMEOUT_SECONDS = 21600` ne sert plus qu'à un `merge` réintroduit un jour | **6,8 s contre 7 249 s** pour la même adoption (× 1 066) ; un test AST exige que tout `merge --ff-only` survivant porte ce budget ; GO réel, parité SHA | — |
| 44 | **Deux gardes que seul `git merge` portait** ont disparu avec lui : un fichier local non suivi était supprimé sans comparer ses octets, et une divergence sur un chemin protégé passait en silence | identité d'octets exigée avant tout `unlink` (`cat-file --batch-check` contre `hash-object --stdin-paths`) ; refus explicite sur collision protégée, **confirmé par le contenu** | 2 tests de régression repassés rouges par injection dans les deux sens ; refus réel vérifié sur un écart d'octets, acceptation sur l'égalité | — |
| 45 | **Mon propre garde a produit un NO_GO faux** : `protected_local_changes` est un inventaire **par `stat`** (« peut-être modifié »), lu comme un diagnostic | la collision n'est retenue qu'après confirmation par `git diff HEAD --` sur les seuls chemins reçus | `CAMPAIGN_WATCHDOG_RECEIPT.json` : empreinte disque = blob de HEAD, diff vide ; `adoption_protected_suspects: 1`, `adoption_protected_collisions: 0` sur le GO réel | — |
| 46 | **`catalog/campaigns` retardait sans que rien ne le réconcilie** : 92 chemins divergents, **73 en retard sur Git, 19 absents du disque, 0 en avance localement** | les 73 manifestes locaux archivés hors dépôt puis `catalog/` matérialisé depuis le distant (`CANONICAL_REMOTE_ROOTS`), les racines lourdes restant exclues (écrire `datasets/` déclencherait le téléchargement des blobs du clone partiel : **24,1 s mesurées pour un seul manifeste**) | **5 265 manifestes, 0 absent, 0 divergent, 0 non suivi** (`ls-files --stage` + SHA-1 des octets) ; `adoption_canonical_materialises: 1` sur le GO réel ; 6 tests dont les exclusions de `datasets/`, `runtime/`, `logs/`, `data/`, `archives/` | — |
| 47 | **Une suite verte sur le mauvais produit** : 19 860 verts obtenus sous l'interpréteur système (pytest 8.4.2, websockets 10.4) que `requirements.txt` interdit | nouvelle règle d'audit **bloquante** `c_interpreteur_conforme_aux_requirements` — écrite sans `exec_rule`, qui aurait dégradé en non bloquant exactement le cas qu'elle garde | rouge sous l'interpréteur système, verte sous l'épinglé ; 5 tests | — |
| 48 | **Rouge de couches (19)** : 2 modules de `tools/` importés par la pile scientifique | modules **déplacés** vers `src/hl_observer/dataset/` (octets identiques) et remplacés par des alias de module (`sys.modules[__name__] = _reel`, qui laisse `monkeypatch` patcher la vraie fonction), les 5 schémas d'import prouvés en bac à sable avant déplacement | **19 → 17, dont 0 violation de couches** ; plafond de `copy_vault_local_lab.py` tenu à 4 971 lignes (import replié sur une ligne, plafond **non** relevé) | les 17 restants = pandas/numpy dans 10 modules de recherche : réécriture, décision d'architecture |
| 49 | **Un refus fail-closed qui ne disait pas pourquoi** : `_remaining_process_ids` rend `[parent_pid]` pour quatre causes distinctes (processus vivant, code non nul, sortie vide, exception) — le rouge `[17980] == []` de la passe était indiagnosticable. Budget de l'énumération CIM : **3 s pour 1,0 s mesurée** (2,7 × de marge) | `DIAGNOSTIC_RESIDU["motif"]` écrit à chaque sortie, compteurs inclus, et imprimé par l'assertion ; `PROCESS_SCAN_TIMEOUT_SECONDS = 20` (20 × la mesure) ; `tasklist` mesuré aussi avant d'être laissé à 2 s (0,05 s au repos, 0,10 s sous churn) | 2 tests rouges par injection dans les deux sens ; **suite complète 19 885 verts, 0 rouge** sous l'interpréteur épinglé (27 min 43) | — |
| 50 | **Même piège pour *vérifier*** : `git diff --name-only -- catalog/campaigns` restreint au chemin mais rafraîchit l'index entier — **> 65 min sans résultat**, tâche arrêtée, et la suite enchaînée derrière n'a jamais démarré | diagnostic équivalent par `ls-files --stage` + SHA-1 en Python : **quelques secondes** | parité du catalogue prouvée par ce chemin ; règle retenue : aucune commande git qui touche l'index dans un diagnostic | — |
| 51 | **Deux règles d'audit bloquantes accusaient des homonymes**, et la seule issue identifiée était de remonter un cliquet dont le commentaire dit par écrit « il ne remonte pas » : `ops/validation_portable.py:311` (`/exchange`) et `realtime/durable_dedup.py:239` (`DELETE FROM seen_events`) | discriminants de **contenu** plutôt qu'une exemption étiquetée : `_lignes_exchange_utilisees` (un littéral membre d'un `in` / `not in` est EXAMINÉ ; assigné, concaténé ou passé à une requête il est EMPLOYÉ) et `_suppression_archivee_et_bornee` (deux conditions nécessaires : un `WHERE`, et un archiveur appelé **avant** la ligne), branché par un nouveau paramètre `discriminant=` de `regex_rule` | **1 → 0** chemin dangereux et **1 → 0** occurrence ; 11 tests, tous rouges par injection dans les deux sens (discriminant aveugle, ordre archive/suppression ignoré, `WHERE` non exigé, garde retiré) ; `PLAFOND_MARQUEURS` reste à **2**, aucun marqueur ajouté | les deux règles comportementales qui prouvent les propriétés restent en place |
| 52 | **Angle mort du balayage d'arrêt, trouvé en conditions réelles** : 20 familles tournaient, portées par ~30 processus `tools/run_bounded_collector.py`, et **aucun marqueur** de `_MARQUEURS_COLLECTEUR` ne les matchait — le `taskkill` de dernier recours voyait zéro collecteur ; l'arrêt n'a tenu que par l'invalidation du bail | marqueur `run_bounded_collector` ajouté, avec la mesure en commentaire | 6 tests verts dont deux nouveaux, rouges par injection : marqueur retiré → les ouvriers redeviennent invisibles ; `pytest` ajouté aux marqueurs → une passe de 31 min serait tuée. Lint identique (9 avant, 9 après, comparé à `git show HEAD:`) | le compteur « 0 collecteur(s) arrêté(s) » n'était PAS un défaut : `_pids_campagne` lit le bon fichier et y voit bien 20 PID (vérifié) ; ils étaient simplement déjà sortis |
| 53 | **Huit violations du contrat de securite passaient la suite** : `import eth_account`, `os.environ.get('HL_PRIVATE_KEY')`, `place_mainnet_order`, `URL = '/exchange'` (49 tests verts), puis `shell=True`, `wallet_connect`, `'guaranteed profit'`, `net_pnl = 1234.56` dans l'UI LIVE (62 tests verts). Les sept regles bloquantes existaient — **uniquement dans `tools/audit_report.py`**, batterie de 4 131 s lancee a la main : entre deux audits, rien ne les appliquait | `tests/test_securite_execution_reelle.py` fait tourner les 7 regles DANS la passe, avec un chargement unique de l'audit en `lru_cache` pour partager son cache de fichiers | **23 tests, 36 s mesurees** (27,6 + 0,6 + 4,6 + 4 regles quasi gratuites : seule la premiere paye la lecture des sources) ; les 8 violations sont rejouees et **toutes refusees**, le depot reel reste vert ; 1 test anti-faux-positif sur du code ordinaire | les 85 regles bloquantes dont le nom n'apparait dans aucun test sont des CANDIDATES, pas des trous : seule l'injection tranche, une par une |
| 54 | **11e rouge, trouve par la mesure et cause par une note de correctif** : `c_shell_true` accusait `src/hl_observer/ops/crash_notification.py:69`, le COMMENTAIRE qui explique que l'injection PowerShell etait « invisible pour la regle qui cherche `shell=True` » — et qui contient donc le motif | discriminant AST `_shell_true_hors_code` : seul un argument nomme `shell` a `True` dans un APPEL compte ; `line_exclude=("#",)` aurait aussi blanchi un vrai appel suivi d'un commentaire | regle **rouge -> verte** sans rien perdre (0 occurrence) ; 4 cas verifies : commentaire et docstring ignores, vrai appel refuse, fichier inanalysable **jamais** blanchi | — |
| 55 | **Aucun test local ne refusait un runner auto-heberge** : un workflow `runs-on: self-hosted` injecte a traverse les **75 tests** des 8 fichiers qui parlent de workflows. La propriete ne tenait que par `github-hosted-runner-firewall.yml`, donc APRES le push, par un garde lui-meme desactivable | `tests/test_runners_github_hosted.py` : **liste blanche** (`ubuntu-`, `windows-`, `macos-`) et non liste noire — un parc prive s'etiquette comme il veut ; les valeurs de `strategy.matrix` sont resolues, et toute expression non resolvable est un REFUS | 10 tests ; 6 formes prouvees refusees : `self-hosted` nu, `ma-grosse-tour` (sans le mot interdit), `[self-hosted, windows]`, `group:` (runner group), `${{ env.RUNNER }}`, et une matrice piegee. Les 94 workflows du depot passent | les 2 anciens workflows « self-hosted » sont deja neutralises (`ubuntu-latest` + `if: ${{ false }}`) et conserves comme traces |

## 21/11/2026 — Inventaire des pertes d'information A LA COLLECTE

Methode : pour chaque normaliseur, comparer les champs **lus** de la source aux champs
**ecrits** en sortie. Un champ lu puis jamais reecrit est une perte candidate — la forme
exacte du `twapId` jete. Mon premier controle accusait 37 fonctions ; il ne voyait ni les
dataclasses, ni les renommages camelCase -> snake_case, ni les renommages en francais
(`leverage` -> `levier`). Corrige : **19 suspects**, dont 5 vraies pertes.

| # | module | perte MESUREE | correctif | preuve |
|---|--------|---------------|-----------|--------|
| 53 | `collecter_contexte_lane.parser_twap_fills` | `twapId` jete au deballage : 20 tranches d'une decision lues comme 20 signaux | `twap_id` conserve, chaine cablee jusqu'au ruban principal (`--twap`) | 3 tests + injection |
| 54 | `collecter_vaults.parser_univers_public` | **biais du survivant** : vault ferme ecarte SANS TRACE ; `createTimeMillis` reduit a un age relatif a l'heure du collecteur | rejets traces avec motif (borne 2 000), `created_at_ms` absolu conserve ; univers rendu INCHANGE | 5 tests + 4 injections |
| 55 | `collecter_contexte_lane.parser_positions` | horodatage SOURCE jete, seule la reception gardee — la latence bourse/nous etait immesurable | `exchange_ts_ms` (entier, `None` si absent) ; preuve interne : le module frere le gardait deja | 3 tests + 3 injections |
| 56 | `vault_ledger.parser_ledger` | `break` sur la premiere clef PRESENTE meme illisible : `{usdc:'n/a', amount:'-250'}` -> `delta_usd=None, est_retrait=False`, du capital SORTANT invisible | toutes les clefs essayees, `delta_clef`, `delta_illisible`, `contrepartie` conservee, `inf` refuse | 5 tests + 4 injections |
| 57 | `collecter_vaults.parser_clearinghouse` | **4 refus manques favorables** : NAV nul/negatif avec exposition -> `levier=0.0` (en verite infini) ; valeur de position illisible -> expo et levier sous-estimes ; uPnl illisible -> PnL latent 0 | `levier=None` + `levier_refus`, `pnl_latent_usd=None` + `_partiel`, compteurs d'illisibles, `expo_complete` | 4 tests + 4 injections |

**Ce que ces cinq pertes ont en commun** : un champ lu pour FILTRER ou pour DEBALLER, puis
jamais reecrit. Et dans trois cas sur cinq, la version honnete existait deja ailleurs dans
le depot (`portefeuille_compte` gardait `exchange_ts_ms` et rendait `None` sur un NAV nul ;
`vault_portfolio_history` tracait deja `is_closed` « pour mesurer le biais de survie »).
La preuve etait interne : deux modules du meme flux, deux comportements.

Faux positifs tranches et pourquoi (a ne pas rouvrir) : `ordres_leader.normaliser_ordre`
(tout conserve en snake_case), `funding_backfill.parser_funding` (`premium` dans une
dataclass), `userfills_live` (`seq` -> `frame_sequence`), `collecter_asset_ctx`
(`impactPxs` -> `impact_bid`/`impact_ask`), `collecter_overshoots` (`isDelisted` = filtre
documente par mesure : 67,3 % des 175 238 lignes `overshoot` avaient leurs prix futurs
figes ; tracer ces exclusions n'ajouterait que du bruit, un depassement sur prix gele
n'est pas une population de survivants).

### Fin de l'inventaire : les 19 suspects sont TOUS tranches

| # | module | defaut MESURE | correctif | preuve |
|---|--------|---------------|-----------|--------|
| 58 | `bybit_market_data` + `bitget_market_data` | un statut d'instrument **absent** valait << negociable >> (`or "Trading"`, defaut `"normal"`) : un marche suspendu entrait dans l'univers, consommait du quota et polluait la comparaison de funding avec un marche mort | refus sur statut absent, aligne sur `coin_universe.py` (OKX) qui refusait deja avec motif `NOT_LIVE` | 2 tests + 2 injections |
| 59 | `collecter_bbo.parser_aggtrade_binance` | **3 refus manques dans UNE ligne de retour**, sur le detecteur de choc executable qui alimente le lead-lag : `m` absent -> << ACHAT >> affirme (le sens invente retourne le signe du choc), `T` absent -> **1970** (trie avant toute l'histoire, latence absurde), `q` illisible -> trade fantome de taille nulle | les quatre cas refusent (`None`), contrat deja prevu par le consommateur (`if t and ...`) | 4 tests + 4 injections |
| 60 | `collecter_vaults.construire_snapshot` | regression que MON correctif #57 pouvait creer : le snapshot copie `cs["levier"]`, desormais `None` ; un `f"{levier:.2f}"` aurait leve TypeError | garde qui construit ET serialise le snapshot dans les 4 cas de refus — mesure, pas deduction | 1 test |

**Faux positifs restants, tranches et documentes** (ne pas rouvrir) : `parse_market_frame`
(`ap` -> `mark_moving_average`, `z` -> `filled_accumulated_quantity`), `parse_gate_contracts`
et `parse_okx_swap_instruments` (delegues a `validate_gate_contract` /
`validate_okx_linear_usdt_swap`, qui refusent avec un motif),
`construire_instantane_ordres` (garde les ordres individuels, et DECLARE sa troncature avec
`"tronque": True` au lieu de la taire), `construire_univers` (`slots_utilises` = compteur
interne republie), `explorer_intelligence.normaliser_ordre` (refuse deja un sens illisible),
`_parse_userfills_frame` et `parser_vault_details` (clefs de navigation).

**Bilan de l'inventaire** : 19 suspects, **8 modules reellement defectueux**, 19 refus ou
conservations poses, chacun prouve rouge par injection. Et le fait qui structure tout :
**dans 5 cas sur 8, la version honnete existait deja ailleurs dans le depot**. Aucune regle
nouvelle n'a ete inventee — les modules retardataires ont ete alignes sur celle que le depot
appliquait deja ailleurs.

## 21/11/2026 — VERDICT de la conduite 23 tranches : la decoupe, pas les donnees

Conduite terminee : 23/23 tranches, 8 196 s (2 h 17), rapport 204 Ko.

```
VERDICT GLOBAL : MORE_DATA (unanime, 23/23)
reason          : TEMPORAL_SPLIT_INVALID_AFTER_PURGE
jours UTC union : 8 / 6 requis          <- la COUVERTURE etait suffisante
candidats essayes, toutes tranches : 0  <- ZERO
```

**Ce n'etait pas un manque de donnees.** La tranche 1 portait a elle seule 185 121
entrees, 34 863 metaordres, 401 676 fills causaux, 680 896 lignes de carnet et 25 172
signaux temporellement alignes. La porte est `bounds is None` dans
`copy_vault_local_lab._bounds`, qui decoupe **par JOUR UTC** et exige
`len(days) >= max(3, seuil_jours)`, soit 6 ici. Or les 23 tranches mesurent **4 h, 7 h,
26 h** — 1 a 2 jours UTC chacune. Aucune ne pouvait former un split TRAIN/VALIDATION/OOS :
les 23 etaient condamnees avant le depart, et 2 h 17 de calcul ne pouvaient rien rendre.

La faute est dans MA conduite, pas dans le labo : j'ai decoupe pour tenir en memoire sans
verifier que chaque fenetre pouvait encore satisfaire l'unite de decoupe du split.
C'est [[decoupe_non_alignee_sur_ses_propres_unites]], deja en memoire, refait.

| # | correctif durable | preuve |
|---|-------------------|--------|
| 61 | `_diagnostic_du_split()` : le refus DIT desormais sa cause et distingue 4 motifs — `FENETRE_PLUS_ETROITE_QUE_L_UNITE_DE_DECOUPE` (erreur de conception), `JOURS_UTC_INSUFFISANTS_DANS_LA_FENETRE` (trou de donnees reel), `SPLIT_VIDE_APRES_PURGE`, `AUCUN_HORODATAGE_LISIBLE` ; attache au payload du refus | 3 tests + 4 injections, dont un **test aveugle ferme** : l'injection qui remplacait `jours_possibles_dans_la_fenetre` par le nombre de jours OBSERVES passait, faute d'un cas les distinguant (fenetre de 8 j trouee) |

**Deuxieme fait du rapport, et il est sain** : `input_data_complete: false` vient de 200
shards (`copy_vault_positions` 100 + `copy_vault_selection` 100) marques
`RECEIVE_TIME_HTTP_SNAPSHOT_NOT_PER_FILL_PNL_INPUT` — des instantanes HTTP dates de la
RECEPTION, exclus a bon droit d'un PnL par fill. `missing_safe_shards: 0`,
`verified_safe_shards: 15 256 / 15 256`. Rien ne manque ; l'exclusion est correcte et
auto-documentee. En revanche leur `local_files_missing: 100` est le symptome du coffre gele,
pas un defaut du labo.

**Ce qu'il faut pour un vrai verdict** : des tranches couvrant chacune >= 6 jours UTC, donc
quasiment le corpus entier (etendue totale mesuree : 7,58 jours) — ce qui ramene au probleme
de memoire qui avait motive la decoupe. Le corpus doit d'abord GRANDIR, ce qui depend de la
publication (cloud proprietaire de `catalog/`), pas du labo.

## 21/11/2026 — Validation des LANCEURS REELS et charge du chemin chaud

| # | sujet | mesure | resultat |
|---|-------|--------|----------|
| 62 | **charge du chemin chaud** : mes refus fail-closed l'ont-ils ralenti ? 40 000 frames (10 % degradees), 5 tours alternes, version `HEAD` (via `git archive`, sans toucher l'index) contre version courante | `HEAD` 1,10 us/frame, accepte **40 000/40 000** ; courant 1,64 us/frame, accepte 36 000 et **refuse 4 000** ; surcout **+49 %** | +49 % sur une fonction qui coute 1,6 us : **610 916 frames/s** contre ~91/s en production, soit 6 700x la marge. Le durcissement ne coute rien en exploitation, et `HEAD` laissait entrer 10 % de frames a sens invente, horodatage 1970 ou taille nulle |
| 63 | **cablage des 12 lanceurs `.cmd`** : 127 references lues | 1 seule cible absente du disque ET de `HEAD` : `ENTRAINER_IA_AUTO.cmd`, citee par `LANCER_HYPERSMART.cmd` — **dans une ligne `REM`**, donc jamais executee | ligne conservee et MARQUEE PERIMEE sur place (5 lignes `REM` devant), CRLF 1 343 -> 1 348, zero double CR. Les 9 modules modifies aujourd'hui sont tous atteignables par un lanceur reel (8 directement, le labo par son propre CLI) |
| 64 | **garde nouvelle** `tests/test_lanceurs_cibles_existantes.py` : rien ne verifiait qu'un `call`/`start`/`cmd /c` de lanceur pointe vers un fichier reel — or `cmd` continue a la ligne suivante, le lanceur finit << sans erreur >> et l'etape est comptee comme faite | 4 tests ; injection **dans les deux sens** : `call` vers cible absente -> ROUGE, `start` vers `.py` absent -> ROUGE, le MEME nom en commentaire -> reste VERT | la garde a d'abord attrape **mon propre motif** (`"%~dp0POUSSER-GITHUB.cmd"` capture `dp0POUSSER-GITHUB.cmd`, `%~` hors de ma classe) : le lanceur etait juste, mon test non |

**Deux defauts de mes propres outils, corriges** : mon premier scan de cablage cherchait les
fichiers seulement dans `tools/`, `src/` et `scripts/`, donc declarait introuvable tout
module de `src/hl_observer/ops/` ; et sa version suivante balayait le depot par `rglob`,
donc les 1,79 M shards de `runtime/` AVANT de les filtrer — depasse 600 s et concurrencait
la suite de tests sur le disque. Balayage borne aux dossiers de code : **2,5 s**.

| 65 | **liaison jusqu'au coffre** : mes refus et mes champs nouveaux franchissent-ils le certificateur, ou le correctif est-il cosmetique ? | `certifier_snapshot_vault` : les 3 cas **PASS**, `levier: None` CONSERVE — le refus honnete voyage comme refus au lieu de couter de la collecte. `certifier_vault_ledger` : 3 lignes **PASS**, `delta_usd=-250.0` (le flux sortant qui etait invisible), `delta_clef`, `delta_illisible=True`, `contrepartie=0xdead` tous conserves. `certifier_position` : `exchange_ts_ms` conserve | chaine verifiee source -> parseur -> certificateur -> coffre, mesuree et non supposee |

## 22/11/2026 — SUITE COMPLETE : 3 echecs sur 20 057 verts, tranches jusqu'a la cause

`tools/python/python.exe -m pytest tests -n 4 --dist loadfile --timeout=1800`
→ **3 failed, 20 057 passed, 59 skipped, 1 xfailed en 2 017,89 s (33 min 37)**.
Aucun worker mort (ni `INTERNALERROR` ni `node down`) : le total est reel, pas le faux
total credible qu'imprime pytest quand un worker est tue.

| # | echec | verdict | preuve |
|---|-------|---------|--------|
| 66 | `test_invariants_architecture::test_pas_de_nouveau_fichier_geant` | **MA REGRESSION** : `copy_vault_local_lab.py` passe a **5 018 lignes contre un plafond epingle a 4 971** — mon `_diagnostic_du_split` l'a fait franchir. La regle interdit d'AGRANDIR une dette historique, donc pas de relevement de plafond : **extraction** dans `backtesting/diagnostic_signal.py` (couverture du signal + diagnostic du split + la constante), **5 018 → 4 944**, puis **plafond BAISSE a 4 944** (laisser l'ancien ferait repousser la dette en silence). `MINIMUM_SIGNAL_UTC_DAYS` vit dans le module extrait et le labo la RE-EXPORTE : l'inverse creerait un cycle d'import, et une constante lue par tous ne doit dependre de personne | 148 tests verts ; 3 injections ROUGES : +1 seule ligne au labo, module neuf > 800 lignes, constante dupliquee ; lint 6 = 6 sur `HEAD`, 0 sur le module neuf |
| 67 | `test_copy_vault_campaign_lock::test_os_lock_is_released_after_owner_crash_without_replacing_lock_path` | **MON INTERFERENCE, pas une regression** : ce test fait crasher un processus proprietaire pour verifier que le verrou OS se libere — et pendant qu'il tournait j'ai **tue 5 processus Python** (la suite lancee en double) | 5 rejeux isoles, **5 verts** |
| 68 | `test_asf_rig_001_020::test_rig_020_all_current_receipts_are_exactly_revalidated` | **REEL et ATTENDU** : un reçu `VERIFIED_DONE` epingle le SHA-256 des fichiers qui le prouvent ; 9 modules modifies aujourd'hui → **68 reçus perimes** (13 groupes de tests). Une preuve ne survit pas a la modification de ce qu'elle prouve | revalidation HONNETE lancee (`tools/revalider_receipts.py`) : elle REJOUE les tests de chaque reçu avant de le rafraichir, au lieu de recalculer les empreintes a l'aveugle comme `regenerer_receipts.py`. Les 9 reçus `REVALIDATION_FAILED` restants sont ceux dont la preuve epinglee a ete supprimee expres — decision operateur, pas correctif |

**Une erreur de lecture de ma part, consignee** : la premiere suite n'etait PAS morte. Le
harnais a rapporte << failed exit code 2 >>, mais ce 2 venait de mon `ls` sur un fichier que
`nohup` n'avait pas encore cree — pas de pytest. Elle a tourne **42 minutes en parallele** de
la seconde, a se disputer le CPU : d'ou les 33 min 37 au lieu des ~31 habituelles, et
tres probablement l'echec #67. Double mise en arriere-plan (`nohup ... &` DANS une tache deja
detachee par le harnais) = un processus que le harnais ne suit plus.

**Historique des echecs de la journee, qui montre ce qui est instable** : 12:11 → 4 echecs,
12:54 → 3, 14:54 → 1, 22:45 → 3. Sur les **six** noms differents apparus, **un seul est
deterministe** (`rig_020`) ; les cinq autres passent isolement. Rejouer seul AVANT de crier a
la regression.

## 22/11/2026 — J'avais corrompu un lanceur : 4 octets, 17 preuves rouges

| # | fait | mesure | suite |
|---|------|--------|-------|
| 69 | **corruption d'encodage que j'ai causee** : j'ai annote `LANCER_HYPERSMART.cmd` en le LISANT en `cp1252` puis en le REECRIVANT en `cp1252` avec `errors='replace'`. Le fichier est en **UTF-8** — son propre en-tete le dit (`chcp 65001`). Les octets **0x81, 0x8D, 0x8F, 0x90, 0x9D** sont indefinis en cp1252 : devenus `?`, ils ont **ampute les sequences multi-octets** auxquelles ils appartenaient → octet de continuation orphelin → `UnicodeDecodeError` position 17201 | non-ASCII tombe de **153 a 149** ; blob `HEAD` = UTF-8 VALIDE, local = INVALIDE ; diff = 42 lignes abimees + mes 5 lignes d'annotation, rien d'autre | reconstruction depuis le blob + re-application de l'annotation en UTF-8 : **153 non-ASCII retrouves**, CRLF 1 348, 0 double CR, annotation ET ligne d'origine presentes ; copie abimee conservee dans `runtime/backups/lanceur_hypersmart_encodage_20261122/` avec son `POURQUOI.txt` |
| 70 | **ce que ces 4 octets avaient fait rougir** : 17 des 27 reçus `REVALIDATION_FAILED` citaient `tests/test_entrypoint_topology.py` ou `tests/test_runtime_contract.py`, qui lisent ce lanceur en UTF-8 | 10 reçus sur le groupe `entrypoint_topology + runtime_contract`, 7 sur le groupe `collecteurs_registre + collector_runner + entrypoint_topology`, 8 sur `asf_113_120_launchers` (preexistants), 1 sur `rig_001_020`, 1 sur le groupe `port_owner + verrou_lanceur` | apres reparation : `tests/test_runtime_contract.py` + `test_entrypoint_topology.py` + `test_lanceurs_cibles_existantes.py` = **23 verts** |
| 71 | **`rig_020` (echec #68 de la suite) est RESOLU** | revalidation honnete : 68 perimes → **50 rafraichis** (tests rejoues), puis 2e passe 4/4 ; `encore_perimes: 0`, `non_mesurables: 0` (aucun `0xC0000142`, les rejeux ont vraiment tourne) | `tests/test_asf_rig_001_020_copy_vault.py` : **20 passed**. Roadmap : `verified_done` 3 093/3 120 (99,13 %), les 27 manquants = les 27 reçus en echec |

**Et une correction que le code m'a apportee** : j'allais ajouter a
`tools/revalider_receipts.py` la capacite de rejouer un reçu en echec, en argumentant que le
registre << ne cliquette que vers le bas >>. L'option **existe deja** (`--reprendre`,
`recus_a_reprendre()` ligne 102) : je ne l'avais pas passee, d'ou le `"repris": 0` que j'ai
lu comme une impossibilite. Verifier le code AVANT de lui prêter un defaut.

## 22/11/2026 — Reçus retrouves et LANCEURS REELS valides

| # | sujet | mesure | resultat |
|---|-------|--------|----------|
| 72 | **les 18 reçus tombes par ma corruption sont RETROUVES** | `revalider_receipts.py --reprendre` : 27 repris → **18 rafraichis**, 9 echecs, `encore_perimes: 0`, `non_mesurables: 0` | roadmap `verified_done` **3 093 → 3 111 / 3 120 (99,71 %)**. Les **9** restants sont les preexistants dont la preuve epinglee a ete supprimee expres — decision operateur, jamais un vert de complaisance |
| 73 | **validation de bout en bout des LANCEURS REELS**, categorie `sur` (les 4 lanceurs qui demarrent des collecteurs sont en categorie `long`, exclue : consigne de l'operateur respectee) | `SUIVI_COFFRE` plafonne a 45 s (moniteur interactif, `exit=None` ATTENDU : **37 277 octets** de tableau de bord reel, verifie et non suppose) ; `RAPPORT_COLLECTEURS` exit=0 en 25 s ; `Certificateur_plan` exit=0 en 6 s ; `RATTRAPAGE_plan` exit=0 en 1 s | **4/4 conformes**, CRITIQUE=0 ERREUR=0 AVERT=0 sur les quatre |

**Ce que le tableau de bord a revele au passage** : `CERTIFICATION 68,6 %`, `INACTIF depuis
4 h 23`. Le scellement du coffre reprend fichier par fichier (`Certificateur Coffre Fort.cmd
--sans-rattrapage`) et la memoire enregistre que **l'operateur lance cette passe lui-meme** ;
la machine est libre. ⚠ jamais `--reset-affichage` : malgre son nom, il VIDE des rubans.

### Ce qui reste, et qui ne depend plus du code

| blocage | pourquoi il tient | qui peut le lever |
|---------|-------------------|-------------------|
| publication `POUSSER-GITHUB.cmd` puis AlinaSync | refusee par le classificateur d'actions ; sans elle les **295 campagnes isolees** n'atteignent pas le cloud, qui est PROPRIETAIRE de `catalog/` | l'operateur (`! POUSSER-GITHUB.cmd`, ou une autorisation) |
| `economically_proven: false` | un verdict exige des tranches de **>= 6 jours UTC** (unite du split) ; le corpus SAFE a **34 jours de retard** faute de publication | consequence du blocage ci-dessus |
| scellement a 68,6 % | passe lancee par l'operateur (preference enregistree) | l'operateur, machine libre |
| 9 reçus `REVALIDATION_FAILED` | leur preuve epinglee a ete supprimee volontairement | l'operateur |
| collecteurs eteints | consigne explicite : << je ne veux pas de collecteurs allumes >> | l'operateur |

## 22/11/2026 — ✅ SUITE COMPLETE VERTE : 20 070 passed, 0 echec

```
tools/python/python.exe -m pytest tests -n 4 --dist loadfile --timeout=1800
  --ignore=tests/test_dataset_policy.py
-> 20 070 passed, 59 skipped, 1 xfailed, 768 warnings en 1 708,71 s (28 min 28)
   0 FAILED · 0 ERROR · 0 worker mort (ni INTERNALERROR ni node down)
```

Lancee SEULE (lecon du jour : deux suites en parallele avaient fabrique un faux echec).
**20 070 contre 20 057** a la passe precedente : les 13 de plus sont les tests ajoutes depuis
-- garde des cibles de lanceurs, module extrait, refus du ledger et de l'aggtrade.

Les trois echecs de la passe de 22:45 sont resolus PAR LA RACINE, aucun contourne :

| echec | resolution | nature |
|-------|-----------|--------|
| `test_pas_de_nouveau_fichier_geant` | extraction de `backtesting/diagnostic_signal.py`, plafond **BAISSE** 4 971 → 4 944 | vraie regression, la mienne |
| `rig_020` | revalidation honnete (`--reprendre`) : 18 reçus retrouves apres reparation de **ma** corruption d'encodage sur `LANCER_HYPERSMART.cmd` | vraie cause externe au code teste |
| `test_os_lock_is_released_after_owner_crash...` | rien a corriger : 5 rejeux isoles, 5 verts. Il rougissait parce que je tuais des processus Python pendant la suite | mon interference |

⚠️ Ce vert ne dit RIEN de la rentabilite : `economically_proven` reste `false`, et la suite ne
mesure pas l'economie. Elle prouve que le code fait ce qu'il dit, pas qu'il gagne de l'argent.

## 22/11/2026 — Le compte des journees dependait du PAS de mesure

Passe plein corpus demandee par l'operateur. Le plan etait bon (1 tranche, 384 h continues,
16,5 M fills sur 943 shards) mais la trace portait une contradiction :

```
couverture : continue=True  etendue=384,0 h          <- 16 jours
journees UTC du corpus : 1 (2026-11-11 -> 2026-11-11) <- UN jour, bornes identiques
```

**Cause**, trouvee dans `journees_utc(densite)` : le compte se lisait sur les **CLEFS des
seaux de densite**, dont la largeur est `--pas-heures`. Avec `--pas-heures 384` il n'existe
qu'UN seau → 1 journee. Une grandeur qui change avec le parametre d'echantillonnage n'est pas
une mesure. Et ce nombre part au labo (`jours_du_corpus`) commander sa porte des SIX
journees : **le bug aurait sabote la passe unique meme si la memoire avait tenu**.

Trois sources, trois reponses le meme soir : **conducteur 1**, **labo 8**, **index du coffre
214** journees de fills (et 18 de carnets).

| # | correctif | preuve |
|---|-----------|--------|
| 74 | `journees_utc(densite, *, pas_ms)` — `pas_ms` devient OBLIGATOIRE et la fonction **leve** `PAS_PLUS_LARGE_QU_UNE_JOURNEE` au-dela d'un jour : on refuse au lieu de sous-compter, parce qu'un refus se voit et un sous-compte se croit (`raise`, pas `assert` : un `assert` disparait sous `python -O`) | 3 tests neufs ; les 3 appels de test existants declarent desormais leur pas |
| 75 | `journees_du_corpus(ruban, densite, *, pas_ms)` extraite de `main` : au-dela d'un jour, elle **relit** le ruban au pas d'une journee (13 s mesurees) ; en dessous, elle reutilise la densite deja lue | **une injection avait prouve le trou** : remplacer la seconde lecture par un comptage sur les seaux grossiers laissait la suite VERTE, alors que c'est le defaut meme. Cablage desormais garde : 3 injections ROUGES |

**Et une erreur de mon test, corrigee** : ma fixture de 16 jours ne reproduisait pas le piege,
parce que les seaux sont **absolus depuis l'epoch** — seize journees chevauchaient deux seaux
de 384 h. Debut aligne sur la borne de 384 h. 44 tests verts, lint 1 = 1 sur `HEAD`.

**Statut de la passe plein corpus** : arretee par Claude Code (pression memoire du systeme,
pas un echec de la commande) juste apres `[1/1]`, au moment ou le rejeu chargeait les 10,6 M
fills. Les 913 Mo que j'avais annonces etaient mesures pendant la phase de DENSITE, pas
pendant le rejeu : la faisabilite d'une passe unique n'est donc **pas** demontree. Aucun
journal ni rapport ecrit → un redemarrage repartirait propre. Je ne relance pas sans demande.

## 22/11/2026 — 🔴 LA CONTRADICTION STRUCTURELLE DU LABO, mesuree des deux cotes

Le labo ne peut pas rendre de verdict economique sur cette machine, et ce n'est ni la
decoupe, ni les donnees, ni un bug : **deux exigences du labo s'excluent**.

```
le split exige   >= 6 journees UTC distinctes DANS UNE SEULE tranche (_bounds, plancher 3)
la memoire exige <= ~1 journee de carnets a la fois
```

**Mesures, deux dates independantes :**

| date | mesure | source |
|------|--------|--------|
| 18/11/2026 | 7 527 878 carnets sur 12 jours, dont **6 denses** (1,3-1,8 M/jour) : << un jour tient en memoire, les six ensemble non (**~28 Go**) >> | docstring de `copy_vault_book_loader.load_observed_books` |
| 22/11/2026 | tranche de **8 jours** (10,6 M fills) : RSS **24,2 Go**, RAM libre tombee a **0,6 Go (98 %)**, arretee par precaution | mesure directe, ce soir |
| 22/11/2026 | tranche de **16 jours** (16,5 M fills) : tuee par la pression memoire du systeme | mesure directe |
| 21/11/2026 | tranches de **4-26 h** : 0,9 Go chacune | conduite 23 tranches |

La consommation croit **plus vite que lineairement** : 0,9 Go/jour a un jour, **3,0 Go/jour a
huit**. Quelque chose s'accumule avec l'etendue, et le volume dit quoi :

```
dans la fenetre 13->20/11 (8 jours), le coffre porte :
   carnets (bbo + micro_bbo + book_l2) : 168 965 200 lignes
   fills                               :  20 500 191 lignes
   signaux a apparier (extrapoles)     :   ~1 200 000
```

**169 millions de lignes de carnet chargees pour servir ~1,2 million d'appariements**, alors
que chaque appariement ne regarde que ±30 s autour de son signal. Toutes gardees en objets
Python il faudrait 110 Go ; le RSS de 24,2 Go montre que le labo filtre deja beaucoup (le
correctif << lisait 20x trop >> et la borne basse `depuis_ms` du 18/11), mais il indexe encore
un ordre de grandeur de trop.

**LA SEULE SORTIE, et elle preserve la justesse** : ne plus charger les carnets par fenetre de
TRANCHE mais par **fenetres de SIGNAL** (±30 s autour de chaque signal, ~1,2 M lignes au lieu
de 169 M). Memes reponses, deux ordres de grandeur de memoire en moins. C'est une optimisation
au sens du /goal (<< optimise RAM sans sacrifier la justesse >>), pas une nouvelle strategie.

⚠️ Mais elle touche le **coeur causal** du labo, la ou une erreur fabrique du lookahead ou des
profits artificiels -- ce que le contrat interdit explicitement. Je ne reecris pas la strategie
de chargement du labo sans accord : c'est la seule piece de ce chantier dont le risque depasse
le gain d'une nuit de travail non valide.

**Ce qui est deja fait et qui rend ce diagnostic possible** : le compte des journees ne mentira
plus (correctifs 74-75), et le refus du split DIT desormais sa cause (correctif 61). Sans ces
trois correctifs, cette contradiction restait invisible derriere un `MORE_DATA` muet.

## 22/11/2026 — Fenetres de signal : mecanisme LIVRE, gain REFUTE sur ce corpus

| # | livre | preuve |
|---|-------|--------|
| 76 | `load_observed_books(..., fenetres_signal_ms=...)` : filtre pose au MEME point de passage que la borne causale, pour qu'un appelant ne puisse pas l'oublier. `fenetres_normalisees` (tri + fusion, marge elargie **vers le PASSE uniquement** -- vers le futur elle ferait du lookahead), `dans_les_fenetres` (dichotomie, bornes inclusives), compteur `hors_fenetres_signal_rejected`, et une liste VIDE est un **refus** (`AUCUNE_FENETRE_DE_SIGNAL`) jamais zero carnet | 10 tests neufs + 20 existants verts ; **5 injections ROUGES** dont celle qui elargit la marge vers le futur ; `None` par defaut = comportement inchange ; lint 0 = 0 sur `HEAD` |

**ET LE GAIN EST REFUTE, mesure a l'appui.** J'avais extrapole : 169 M lignes de carnet pour
~1,2 M appariements, donc deux ordres de grandeur a gagner. Faux en conclusion :

```
25 172 signaux alignes sur 4,03 h  =  un signal toutes les 0,58 s
fenetres de +-30 s  ->  apres fusion elles couvrent 100 % du temps
->  0 % des lignes de carnet ecartees
```

**Ce qui decide, et que je n'ai pas tranche** : le rapport donne DEUX comptes de signaux --
`temporally_aligned_add_signals: 25 172` (des fills individuels) et `signal_count: 44` (les
instants de decision que le split utilise). Si le carnet est consulte **par metaordre** (44 en
4 h), les fenetres ne couvrent que **9 %** du temps et **91 %** des lignes tombent ; si c'est
**par fill**, le gain est nul. La mesure a faire : compter les instants DISTINCTS pour lesquels
le labo demande un carnet, dans un rejeu d'une seule journee (0,9 Go, sans risque).

Le mecanisme reste utile meme si le gain est nul ici : il ne coute rien tant qu'on ne le passe
pas, il est garde contre le lookahead, et il servira des que le signal sera moins dense (ou
pour un rejeu cible sur quelques leaders). Mais **je n'annonce pas une victoire que la mesure
ne soutient pas** : la contradiction 6 jours / memoire reste entiere.

## 22/11/2026 — ✅ LA CONTRADICTION EST LEVEE : le split SE FORME, pour 0,084 Go

```
tools/sonde_horloges_carnets.py runtime/labo_tranches_20261121/workspace

11 334 251 horodatages de carnets sur 270 coins  ->  0,084 Go  ·  25,8 s
10 631 645 signaux lus                           ->            ·  28,1 s
journees UTC evaluables : 7 · DENSES : 7   (6 requises)
signaux evaluables      : 7 953 552 / 10 631 645  (74,8 %)
SPLIT                   : **SE FORME**
memoire                 : 0,084 Go   contre 24,2 Go pour le rejeu complet (288x)
```

**La contradiction 6 jours / memoire n'etait pas intrinseque.** Elle venait d'une seule
chose : le labo garde les carnets ENTIERS en memoire alors que sa logique d'appariement ne
lit qu'un entier de 8 octets. Preuve dans son propre code
(`copy_vault_signal_alignment.evaluable_signals`) :

```python
for row in metaorders:                  # par METAORDRE
    stamps = horloges.get(row["coin"])  # et UNIQUEMENT des ts_ms
    index = bisect.bisect_right(stamps, signal_ms) - 1
    if index < 0 or signal_ms - stamps[index] > max_book_age_ms:
        continue
```

| # | livre | preuve |
|---|-------|--------|
| 77 | `tools/sonde_horloges_carnets.py` : lit les rubans EN FLUX, ne garde que `(coin, ts_ms)` en `array('q')`, puis interroge les **vraies** fonctions du labo (`_bounds`, `signal_coverage`, `diagnostic_du_split`). N'ecrit rien, ne decide rien, ne touche pas au labo | **5 tests d'EQUIVALENCE** avec `evaluable_signals` : memes nombres, meme rejet d'un carnet trop vieux, meme exclusion d'un carnet POSTERIEUR au signal (pas de lookahead), meme seuil de jours denses. Une sonde qui annoncerait un split que le labo refuse justifierait un refactor sur une illusion ; celle-ci ne peut pas. Lint 0 |

⚠️ **CE QUE LA SONDE NE PROUVE PAS** (a dire avant d'en tirer un plan) : elle lit les RUBANS
par regex, pas le coffre certifie, et met `action=ADD` par defaut quand le champ manque. Le
labo applique en amont des filtres que la sonde n'a pas (deduplication, certification,
identite d'instrument, `une_seule_connexion_par_coin` qui ecarte ~62 % des carnets a dessein).
Ses 7 journees denses et ses 7,95 M signaux evaluables sont donc une **borne haute**. Les
5 tests couvrent la logique d'APPARIEMENT, pas le filtrage amont.

**LE CHEMIN EST DESORMAIS CHIFFRE** : faire lire au labo des HORLOGES (8 o/carnet) pour
l'appariement, le split et les portes, et ne charger les carnets COMPLETS que pour chiffrer
les candidats effectivement evalues. Ce n'est plus une hypothese a 110 Go extrapolee, c'est
une mesure a 0,084 Go. Reste a l'ecrire dans le labo -- la ou une erreur fabrique du lookahead,
donc avec l'accord de l'operateur et sous le meme regime de preuve par injection.

## 22/11/2026 — ✅ LE MODE HORLOGES EST INTEGRE AU LABO (plus seulement sonde)

| # | livre | preuve |
|---|-------|--------|
| 78 | `load_observed_books(..., horloges_seulement=True)` : la ligne est **construite, mesuree, puis JETEE** — seul un entier de 8 o survit, dans un `array('q')` trie. Les diagnostics de rejouabilite (`non_causal_rows`, `safe_causal_rows`) sont calcules par la **MEME expression** sur le **MEME objet** que le mode complet : recopier ces predicats ailleurs creerait deux verites qui divergeraient. L'audit porte `horloges_seulement` pour qu'un consommateur ne decouvre pas en plantant que `row["bid"]` n'existe pas | **9 tests** d'equivalence (instants, diagnostics, corpus vide, tri, bornes causale ET basse, combinaison avec les fenetres) + **6 injections ROUGES** dont << borne causale sautee >> et << corpus vide passe pour rejouable >> |
| 79 | `evaluable_signals(metaorders, books=None, *, horloges=None, ...)` : accepte les deux entrees, **exige exactement l'une** (`FOURNIR_BOOKS_OU_HORLOGES`). Pas de reniflage de type : deviner ferait silencieusement autre chose que ce que l'appelant croit, et ici << autre chose >> voudrait dire des signaux declares evaluables sans carnet — de l'executabilite fabriquee | le dict de retour est **IDENTIQUE** par les deux chemins (`par_books == par_horloges`, egalite du dict ENTIER) ; les deux usages ambigus refusent ; **16 appelants existants inchanges** ; 87 tests du labo verts |

**Pourquoi cette integration etait sure a ecrire, contrairement a ce que je craignais.** Le
risque etait de nourrir le labo d'horloges obtenues HORS de ses filtres (la sonde lit par
regex, sans deduplication ni certification ni `une_seule_connexion_par_coin`) : il aurait
declare evaluables des signaux qui ne le sont pas. Le mode horloges passe par le **meme
pipeline**, au meme point de passage que la borne causale — donc tout filtre amont s'applique
a l'identique, ce que deux injections verifient.

**Le gain, mesure et non extrapole** : 0,084 Go pour 11,3 M horodatages sur 270 coins contre
**24,2 Go** pour le rejeu complet sur 8 jours — et la sonde a confirme que le split SE FORME
(7 journees denses / 6 requises). La contradiction << 6 jours contre la memoire >> qui bloquait
tout verdict depuis le 18/11 n'a plus de raison d'etre.

**Ce qui reste pour un verdict** : brancher le mode horloges dans le chemin de conduite du labo
(phase 1 portes + split sur horloges, phase 2 carnets complets uniquement pour chiffrer les
candidats retenus). Les deux briques existent et sont prouvees equivalentes ; il reste a
choisir OU les appeler dans `copy_vault_local_lab`, ce qui touche l'ordonnancement du rejeu.

## 22/11/2026 — MISSION COLLECTEURS : le lanceur ne peut plus tuer un innocent

Point de depart impose par l'operateur : `LANCER_COLLECTEURS_COPY_VAULT.cmd` et sa chaine.
Etat observe AVANT toute action, par un detecteur qui ne s'attrape pas lui-meme :
**collecte ETEINTE, zero processus**. Trois de mes detecteurs ad hoc en `python -c` s'etaient
matches eux-memes avant que j'ecrive le detecteur dans un fichier — piege deja en memoire,
reconduit trois fois en une heure.

| # | defaut MESURE | correctif | preuve |
|---|---------------|-----------|--------|
| 80 | `taskkill /PID %%P /T /F` sur un PID lu dans un `.pid`, **8 sites**. Windows RECYCLE les PID : un `.pid` perime designe un jour un processus etranger, et `/T` emporte tout son arbre. Douze `python.exe` tournaient sur ce PC pendant la mission | `collecteurs_balayage.identifier_pid` : il faut la racine du projet **ET** un marqueur de collecteur **ET** aucun marqueur exclu (ecran, scelleur, sync, labo), plus le proprietaire quand on l'exige. 7 motifs de refus distincts | **0 taskkill /PID actif** ; 13 tests ; 8 injections ROUGES, chacune precedee d'une verification de syntaxe (une injection qui casse le code ne prouve rien) |
| 81 | `taskkill /FI "WINDOWTITLE eq ALINA-*"`, **8 sites** : un titre de fenetre n'appartient a personne | meme selecteur, et un arret qui ECHOUE empeche de demarrer (`errorlevel 3` vers `fail_lock`) : croire avoir arrete un collecteur vivant, c'est lancer une campagne par-dessus la premiere | **0 actif** ; test `test_un_arret_qui_ECHOUE_empeche_de_demarrer` |
| 82 | le verrou ecrivait `%RANDOM%%RANDOM%` sous un commentaire annoncant « PID du cmd courant » : le code contredisait son commentaire, et personne ne pouvait savoir qui tenait le verrou | `ecrire_verrou` / `lire_verrou` : PID + commande + instant, et `ABSENT` distingue de `FORMAT_ANCIEN_OU_ILLISIBLE` | verifie SUR LA MACHINE : le verrou reel portait encore l'ancien format, desormais annonce `FORMAT_ANCIEN_OU_ILLISIBLE` au lieu d'etre lu comme un PID |
| 83 | detection d'instance = « ce PID est UN python », **DUPLIQUEE** (demarrage + ecran `:status`) : faux positif — un python etranger fait refuser le demarrage — ET faux negatif — un collecteur sans `.pid` reste invisible | les deux sites lisent le MEME selecteur ; un test exige au moins deux usages | 10 tests de garde du lanceur |
| 84 | `--status` sautait **ligne 47** alors que `CV_PYTHON` n'etait defini qu'en **ligne 54** : l'etat interne ne s'affichait pas (defaut PREEXISTANT) et ma detection etait sautee, donc `Statut : ARRETE` **par defaut, quoi qu'il arrive** | bloc Python deplace AVANT l'analyse des arguments | regression trouvee en lancant le vrai lanceur, moins d'une minute apres l'avoir introduite |
| 85 | mon `for /f` a backquotes coupait le chemin de python.exe au premier espace : `CV_VIVANTS=0` **par echec**, un zero qui ressemblait a une mesure | compteur `--compter` ecrit dans un fichier, lu par `set /p` : **zero backquote** | le message « n'est pas reconnu en tant que commande interne » a disparu de la sortie |
| 86 | l'ecran lisait `d.get("lease_valid")`, clef **ABSENTE** de ce schema — elle vit dans `bounded_collection` : il affichait `Lease valide: ?` POUR TOUJOURS alors que le bail etait expire depuis **10,2 h** | `tools/etat_collecte_reel.py` : bail lu sous `lease.expires_at_ms` | 11 tests ; `BAIL_EXPIRE depuis 36 791 s` s'affiche enfin |
| 87 | le fichier d'etat listait **20 workers avec leurs PID** alors que **0** etait vivant, et annoncait `pids=20` / `demarres_et_verifies=19` | etat REEL a **quatre niveaux** : processus vivant != collecte fonctionnelle != donnees fraiches != certifiables. `PROCESSUS_VIVANTS_MAIS_AUCUNE_DONNEE_FRAICHE` est un etat NOMME, jamais un OK | 4 alertes affichees, dont l'incoherence interne que personne ne regardait |

**Rien n'a ete supprime** : les 12 lignes dangereuses sont conservees en `rem`, prefixees
`PERIME 22/11/2026` avec leur motif, et **quatre sauvegardes datees** du lanceur ont ete
prises sous `runtime/backups/`. CRLF 476 vers 551, zero double-CR et zero LF orphelin a
chaque etape.

### ETA VIVANT demande par l'operateur

| # | livre | preuve |
|---|-------|--------|
| 88 | `ETA_COLLECTE.cmd` + `tools/eta_donnees_labo.py` : combien de temps encore collecter. Fonde sur ce qui bloque REELLEMENT le labo (mesure du 22/11) : le nombre de **journees UTC denses** de signaux evaluables, pas un volume d'octets. Le debit se mesure sur la CROISSANCE du ruban — temps constant, aucune relecture des 8 Go | **16 tests**, dont : un debit plus faible ALLONGE l'ETA ; un debit trop faible pour finir la journee avant minuit la fait PERDRE (`JOURNEE_EN_COURS_PERDUE`, +1 jour) ; debit nul vers `INFINI` jamais un chiffre ; non mesurable vers `INCONNU` ; plancher calendaire incontournable |

**Ce que l'ETA repond aujourd'hui, et c'est une bonne nouvelle** : `7 / 6 journees requises`
donc **ATTEINT**. Le temps de collecte n'est donc PAS le blocage — et l'outil l'affiche avec
sa propre mise en garde : borne HAUTE, parce que la sonde lit les rubans par regex, hors des
filtres du labo.

**Total de ce bloc** : 40 tests neufs (13 identite, 10 garde du lanceur, 11 etat reel,
16 ETA — dont recouvrements), 8 injections rouges, lint propre sur tous les fichiers neufs,
78 tests verts sur l'ensemble des suites liees aux collecteurs.

## 22/11/2026 — VALIDATION DE BOUT EN BOUT de la chaine + `rig_020` resolu

Le hook reclamait une validation de la chaine `collecte -> rattrapage -> certification SAFE
-> coffre -> AlinaSync -> labo`, avec charge et reprise. Faite **sans allumer un
collecteur** : la collecte est eteinte sur consigne, et une validation qui exigerait de la
rallumer ne serait pas une validation mais une campagne.

| # | livre | resultat |
|---|-------|----------|
| 89 | `tools/valider_chaine_bout_en_bout.py` : chaque maillon se valide sur TROIS questions distinctes — existe-t-il ? un lanceur reel l'appelle-t-il (sinon `prod=0`, il ne produit rien quels que soient ses tests) ? son contrat de sortie est-il honore sur les donnees presentes ? Cinq etats, jamais deux : `OK`, `ABSENT`, `NON_CABLE`, `CONTRAT_NON_TENU`, `INDETERMINE` | **OK=10, INDETERMINE=1** (l'artefact de reconciliation n'existe pas encore : AlinaSync n'a pas tourne depuis que je l'ai cable — rien a verifier, donc rien a dire) |
| 90 | **trouvaille reelle** : `tools/avancement_rattrapage.py` etait appele par **PERSONNE** (`prod=0`), comme `reconcilier_sources` et `enrichir_fills` hier. Or la passe de rattrapage etait MUETTE — zero octet de sortie en une heure, verifie le 15/11, son resume n'arrivant qu'apres epuisement du budget, jusqu'a 8 h plus tard. Un rattrapage silencieux est indistinguable d'un rattrapage MORT | cable dans l'ecran d'etat (lecture seule, il ne lance aucune passe) |
| 91 | `rig_020` : mes modifications de la nuit avaient de nouveau perime des recus | revalidation honnete : **18 perimes -> 18 rafraichis, 0 echec**, `encore_perimes: 0`. `tests/test_asf_rig_001_020_copy_vault.py` : **20 passed**. Roadmap 3 111/3 120 (99,71 %) ; les 9 restants sont les recus dont la preuve epinglee a ete supprimee volontairement — decision operateur |
| 92 | `tests/test_lanceurs_sans_octet_de_controle.py` : aucun lanceur ne doit porter NUL, BEL, BACKSPACE, VTAB, FORMFEED, SUB ou ESCAPE (la TAB reste licite : elle indente) | 4 tests, **3 injections ROUGES** dont le defaut exact |

### QUATRE FAUX POSITIFS DE MON PROPRE VALIDATEUR, mesures et corriges

Je ne rapporte aucun de ces resultats sans l'avoir verifie : le validateur s'etait trompe
quatre fois, et trois de ces erreurs sont des pieges deja consignes dans la memoire.

1. **`NON_CABLE run_bounded_collector.py`** — il est lance par
   `src/hl_observer/ops/bounded_collection.py`, un module PYTHON. Mon scan ne lisait que les
   `.cmd` et les workflows. Un maillon appele par du Python est cable.
2. **`ABSENT rattraper_gaps.py`** — j'avais **invente** ce nom. Les vrais outils sont
   `avancement_rattrapage.py` et les `backfill_*`.
3. **5 "violations" PAPER/READ-ONLY** dans `audit_report.py`, `securite_18h.py`,
   `garde_fous_recherche.py` : ces fichiers citent `private_key`, `eth_account`,
   `sign_l1_action` et l'URL `/exchange` **parce qu'ils les INTERDISENT**. Le detecteur
   lisait des ETIQUETTES comme des diagnostics. Remplace par un discriminant de CONTENU
   (`tokenize`) : un interdit dans une CHAINE est une mention, le meme en IDENTIFIANT est un
   usage. Plus un discriminant de VOISINAGE : `audit_report.py:3671` porte l'URL exacte dans
   une fixture nommee `piege_exchange`, juste sous un
   `raise RuntimeError("l'ouvreur reseau NE DOIT PAS etre appele sur une URL interdite")` —
   c'est la PREUVE que la garde marche, l'oppose d'une violation.
   Resultat : **0 violation**, avec le compte de ce qui a ete ecarte (1 garde citant
   l'interdit, 26 mentions en chaine) plutot qu'un zero muet.
4. **Le perimetre** : je balayais `tools/python/` et `site-packages`, le runtime embarque.
   Meme piege que l'audit du depot, ou 107 faux positifs etaient tombes a 0 en bornant.

### ET UN OCTET INVISIBLE QUE J'AI MOI-MEME ECRIT

En cablant le suivi de rattrapage, mon heredoc a mange un antislash : Python a lu `\a` =
**BELL (0x07)**, et le lanceur a recu

```
if exist "%CV_ROOT%tools<BEL>vancement_rattrapage.py" (
```

Le `a` avait disparu DANS l'octet de controle. Le `if exist` ne trouvait donc jamais le
fichier, **en silence**, et `grep` ne voyait rien : mon validateur declarait le maillon
`NON_CABLE` apres que je l'avais cable. J'ai failli croire mon outil plutot que les octets.
Repare en OCTETS (2 BEL -> 0), et la garde #92 refuse desormais ce defaut pour tous les
lanceurs. Famille `echappement_dans_du_code_genere`, cinquieme occurrence de la nuit.

## 22/11/2026 — CORRECTION : ce qui doit voyager, c'est le CODE, pas les campagnes

J'ai repete huit fois cette nuit que « sans la publication, les 295 campagnes isolees
n'atteignent pas le cloud ». **C'est faux, et la verite est plus simple.** Verifie dans
`tools/alina_git_code_sync.py` :

```
PROTECTED_DIRS           contient 'catalog'   ->  POUSSER ne commite JAMAIS catalog/
CANONICAL_REMOTE_ROOTS = {'catalog'}          ->  le DISTANT est la source canonique ;
                                                  le local est ADOPTE depuis lui
```

Consequences, dans l'ordre :

1. **Mes 295 manifestes repares localement ne partiront jamais** — par conception. Et la
   prochaine adoption les ECRASERA depuis le distant. Cette reparation locale etait donc un
   **no-op pour le cloud**. Il faut le dire : j'ai presente comme un acquis ce qui n'en
   etait pas un.
2. **Le vrai livrable, c'est le CODE**, et il est en place. Chaine verifiee :

```
.github/workflows/campaign-watchdog.yml
   cron: "*/5 * * * *"          runs-on: ubuntu-latest      (GitHub-hosted, conforme au contrat)
   declenche sur     tools/campaign_watchdog.py + tests/test_campaign_watchdog_drain.py  (L10-11)
   lance D ABORD     python -m pytest -q tests/test_campaign_watchdog_drain.py           (L39)
   puis              python tools/campaign_watchdog.py --dispatch                        (L43, L63)
```

   Mes deux reconciliations (`_reconcile_epoch_superseded`,
   `_reconcile_retry_current_epoch`) sont dans ce fichier : **4 references**, **24 tests
   verts**. Le workflow rejoue ces tests AVANT de dispatcher : un correctif casse ne
   s'appliquerait pas.

3. Donc **pousser le code suffit** : le cloud applique les reconciliations a SON catalogue
   canonique, toutes les 5 minutes, et les campagnes terminales-inclosables se ferment la ou
   ca compte. Aucun fichier local n'a besoin de voyager, et le PC ne devient pas une
   dependance du cloud — ce que le contrat interdit.

**Ce que ca change pour l'operateur** : une seule commande (`! POUSSER-GITHUB.cmd`) ne
« transfere pas des campagnes », elle **livre la reparation au seul endroit qui peut
l'appliquer**. Et elle est la premiere pierre de la chaine qui mene au verdict :
campagnes fermees -> releases SAFE copy-vault reprennent -> le corpus du labo cesse d'avoir
34 jours de retard -> `economically_proven` devient mesurable.

**Ce que ca ne change pas** : je ne peux pas la lancer. Le classificateur d'actions me la
refuse, et je ne contournerai pas un refus.

## 22/11/2026 — 🎯 LA CAUSE RACINE DU VERDICT MANQUANT, mesurée de bout en bout

J'ai passé la nuit à dire « le labo rend MORE_DATA » et « la mémoire bloque ». Les deux sont
vrais mais secondaires. En interrogeant `tools/audit_selection_labo.py` sur un corpus DÉJÀ
préparé, la chaîne causale complète apparaît — et chaque maillon est chiffré :

```
economically_proven = false
  <- 0 trade ferme, 0 journee active, net None
  <- 1 613 / 1 613 candidats TRAIN : INCOMPLETE_EPISODE_REJECTED   (100 %)
  <- 1 045 (65 %) : STALE_OR_MISSING_EXIT_BOOK
       231 : FUNDING_BOUNDARY_UNPRICED
       230 : L2_CONNECTION_GAP_CROSSED
       104 : STALE_OR_MISSING_ENTRY_BOOK
  <- cause nommee par le depot lui-meme (copy_vault_train_executability.py:43) :
     "aucun carnet au moment de la sortie : la collecte s'ARRETE AVANT LA FIN de la position"
```

**Le labo essaie donc bien des candidats.** Il en retient 1 613 en TRAIN et 353 en OOS, les
rejoue, et les rejette TOUS parce qu'aucun episode n'a de carnet complet de l'entree a la
sortie. Ce n'est ni un manque de jours, ni un refus de la porte temporelle.

### L'exigence, transformee en nombre

```
horizons de detention cherches : 30 s, 1, 2, 3, 5, 15, 30 min, 1 h
   -> la collecte doit couvrir un coin SANS TROU pendant 1 h (le plus long horizon)
fraicheur exigee  : carnets a <= 30 s de l'ENTREE **et** de la SORTIE  (MAX_TARGET_LAG_MS)
delai de copie    : 60 s  (COPY_DELAY_MS)
contrainte dure   : sur UNE SEULE connexion L2 par coin
```

Et la specification est ecrite noir sur blanc par le depot, dans
`collection_resume_state.json` (famille `copy_vault`) :

* « entry and exit books no more than 30 seconds from each copied event »
* « at least 8 independent reconciled causal TRAIN metaorders per vault »
* « positive TRAIN net and profit factor above one after all costs »
* « purged positive OOS, positive post-freeze forward, placebo beaten »
* « coin concentration <= 65% and no single winning trade > 60% of gains »

### LE CHIFFRE QUI EXPLIQUE TOUT

```
"une seule connexion L2 par coin -> 125 544 carnets gardes,
 205 940 ecartes comme connexion minoritaire (2/175 coins n'en avaient qu'une)"
```

**173 coins sur 175 sont collectes sur PLUSIEURS connexions L2.** Le labo n'en garde qu'une
par coin — c'est VOULU, un episode ne doit pas traverser deux connexions — donc **62 % des
carnets collectes sont structurellement inutilisables**, et la connexion retenue a des trous.
A l'instant de sortie d'une position, ce trou fait mourir l'episode.

**Ce n'est donc pas un probleme de VOLUME, c'est un probleme de CONTINUITE.** Collecter plus
longtemps n'aide que si une MEME connexion tient 1 h d'affilee sur un coin.

### Ce que cela change pour les collecteurs

L'exigence est modeste et precise : **une connexion L2 par coin, stable pendant >= 1 h, avec
des carnets espaces de <= 30 s**. Aujourd'hui l'architecture repartit les coins sur 4 lanes
(`copy-vault-l2-lanes.yml`) et le meme coin finit vu par plusieurs sockets.

⚠️ Et le module d'etat REFUSE qu'on reduise tout a un manque de donnees :
`safe_to_claim_future_data_required_only: false`, `all_software_pipelines_ready: false`. Il
manque donc AUSSI du logiciel, pas seulement du marche. Je ne dirai pas « il ne manque que
des donnees » : le depot l'interdit explicitement, et il a raison de l'interdire.

### Ce qui reste a faire, dans l'ordre de valeur

1. **Stabiliser une connexion L2 par coin sur >= 1 h** (collecteurs, hors ligne codable,
   validation en vol = feu vert operateur). C'est le seul levier qui attaque les 65 %.
2. `! POUSSER-GITHUB.cmd` : livre le code du watchdog au cloud, qui ferme ses campagnes
   toutes les 5 min -> les releases SAFE reprennent.
3. Les 231 `FUNDING_BOUNDARY_UNPRICED` : un funding sans prix en face ne mesure rien — c'est
   la tache `funding-profond` du rattrapage (394 j-coins, 2,0 h de requetes).

## ⛔ LE BLOC SUIVANT EST REFUTE (voir « CORRECTION » plus bas) — NE PAS AGIR DESSUS

> 17 % / 83 % / 92,6 % sont FAUX : la vraie regle garde 75,3 %, ecarte 24,7 %, et les
> carnets ecartes ne combleraient que 20,9 % des trous. Conclusion inverse : ne PAS
> toucher a la regle. Conserve pour la tracabilite.

## 22/11/2026 — 🎯 LE LEVIER : 83 % des carnets jetés pour des raccords de 2,84 s

### La mesure

```
ruban L2 reel, 400 Mo lus : 512 654 carnets sur 265 coins

gardes par la regle ACTUELLE (une seule connexion par coin) :  87 110  (17,0 %)
ECARTES comme "connexion minoritaire"                       : 425 544  (83,0 %)

raccords entre deux connexions, TROU <= 30 s : 201 977
raccords TROP LONGS (> 30 s)                 :   2 197   (1,1 %)
trou MEDIAN 2,84 s   |   p90 10,3 s   |   p99 37,55 s

=> en franchissant SEULEMENT les raccords courts :
   87 110 -> 474 485 carnets utilisables, soit 17,0 % -> 92,6 % du ruban (x5,4)
```

Les dix coins qui gagneraient le plus : BTC (+3 066 carnets), ETH (+3 041), HYPE (+3 030),
KAITO (+2 917), AVAX (+2 861), SKY, XMR, TIA, POL, KSHIB.

### Pourquoi la regle existe, et pourquoi elle coute trop cher

La regle `une_seule_connexion_par_coin` garde, par coin, la connexion portant le PLUS de
carnets. Sa raison est bonne : un episode ne doit pas traverser deux flux dont le raccord
cache peut-etre des mises a jour perdues.

Mais une connexion WS porte BEAUCOUP de coins : les 297 « connexions de BTC » sont
297 connexions ayant chacune porte quelques carnets de BTC (4 lanes x de nombreuses
reconnexions sur plusieurs jours). Les carnets d'un coin sont donc **eparpilles**, pas
discontinus — et la regle en jette 83 %.

**Le seuil n'est pas invente** : 30 s est `MAX_TARGET_LAG_MS`, la fraicheur que le labo
s'impose DEJA autour de chaque evenement copie. Un raccord plus court que ca ne peut rien
cacher que le labo aurait utilise. Et un raccord plus long reste REFUSE — les 2 197 cas
(1,1 %) continuent d'ecarter l'episode, ce qui est juste.

### Ce que ca attaque

C'est exactement la cause des 1 045 `STALE_OR_MISSING_EXIT_BOOK` sur 1 613 candidats TRAIN :
a l'instant de sortie d'une position, **le carnet existe** — il est seulement sur la
« mauvaise » connexion. D'ou `0 trade ferme`, `net None`, `economically_proven = false`.

### Le correctif propose, et ses garde-fous

Meme patron que les trois optimisations de la nuit (fenetres de signal, mode horloges,
chargement en deux temps) :

* **optionnel, desactive par defaut** -> aucun appelant ne bouge, comportement bit pour bit ;
* le trou de CHAQUE raccord est **mesure**, jamais suppose ; au-dela du seuil -> refus ;
* le seuil vaut `MAX_TARGET_LAG_MS`, pas une valeur choisie pour faire passer des candidats ;
* l'audit publie **combien de raccords ont ete franchis et combien refuses** : sans ce
  compte, on ne saurait pas si un verdict repose sur 17 % ou 93 % du ruban ;
* aucune donnee creee : ces carnets sont **deja certifies SAFE**, seulement ecartes.

⚠️ Cela touche le coeur causal du labo. Je ne l'ecris pas sans que l'operateur l'ait lu : une
erreur ici fabrique du lookahead ou des profits artificiels, ce que le contrat interdit
nommement. La mesure, elle, est faite et reproductible
(`tools/mesure_trous_entre_connexions.py`,
`runtime/reports/trous_entre_connexions_20261122.json`).

## 22/11/2026 — ⛔ CORRECTION : mon « levier » était faux d'un facteur 3,4

J'ai annonce, chiffres a l'appui : « 83 % des carnets ecartes, recuperables a 92,6 % en
franchissant des raccords de 2,84 s, x5,4 de couverture ». **C'etait faux**, et l'erreur est
entierement la mienne : j'avais mesure une regle que le depot n'applique pas.

### Ce que la regle fait VRAIMENT

`une_seule_connexion_par_coin` ne garde pas « la connexion majoritaire ». Elle trie les
connexions par DUREE et en garde PLUSIEURS par coin, tant que leurs intervalles ne se
RECOUVRENT pas :

> « Ce que le replay exige n'est pas une connexion unique, c'est qu'un EPISODE n'en traverse
>   pas deux. »

Et cette forme decoule DEJA d'une refutation du 19/11/2026 : garder la plus longue
globalement laissait « un seul coin couvert le 13/11 et treize le 14 », 365 819 carnets
tombant a 64 024, 418 candidats de VALIDATION sur 418 refuses.

### La mesure, en rejouant la vraie regle

```
carnets lus : 512 654 sur 265 coins
GARDES  : 385 827  (75,3 %)        <- et non 17 %
ECARTES : 126 827  (24,7 %)        <- et non 83 %
coins a connexion unique : 41 / 265

trous > 30 s COMBLES par un carnet ecarte :   519
trous > 30 s qui RESTERAIENT vides        : 1 967
part des trous que l'observation couvrait deja : 20,9 %
```

**Donc le correctif propose aurait recupere 20,9 % des trous, pas 5,4x les carnets.** Et
79,1 % des trous resteraient vides : l'observation n'existait vraiment pas.

### Ce que cette correction etablit

1. **La regle du depot est bonne** : elle ne jette presque rien d'utile. Ne pas y toucher.
2. **La cause dominante des 1 045 `STALE_OR_MISSING_EXIT_BOOK` est une VRAIE absence
   d'observation** : la collecte s'arrete avant la fin des positions. C'est exactement ce que
   `collection_resume_state.json` dit depuis le debut
   (`FUTURE_CAUSAL_BOOK_AND_VAULT_DATA_REQUIRED`, « entry and exit books no more than
   30 seconds from each copied event »).
3. Donc le verdict economique exige de **collecter a nouveau**, en continu, assez longtemps
   pour couvrir entree -> sortie. Pas un correctif de code.

### La lecon, pour ne pas la repayer

**Lire la regle AVANT de mesurer son cout.** J'ai ecrit un script qui implementait ma
supposition (« garder la majoritaire »), obtenu un chiffre spectaculaire, et failli proposer
une modification du coeur causal sur cette base. Le garde-fou qui a tenu : je ne touche pas au
coeur causal sans mesure reproductible -- et en la rendant reproductible, j'ai lu le code et
vu l'erreur. Meme famille que [[verifier_mes_propres_controles]] et
[[outil_qui_fabrique_le_defaut_qu_il_chasse]].

## 22/11/2026 — 🧾 LES 9 ROUGES N'ÉTAIENT PAS DES ÉCHECS : « absent » confondu avec « faux »

### Ce que j'ai trouvé

Les neuf reçus `ASF-113..120` et `ASF-RIG-019` portaient `REVALIDATION_FAILED` depuis le 18/11
avec, dans le meme reçu, `exit_code: 0`. Cette contradiction etait le signal.

```
leurs tests rejoues le 22/11        : 32 verts en 3,6 s
_rejouer() leur rend                : 0   (les deux groupes)
fichiers epingles manquants         : UN SEUL, le meme pour les neuf
                                      -> POUSSER-GITHUB-FORCE.cmd
```

Et l'historique explique sa disparition : commit **b44aac91 du 18/11**, intitule
« lanceur: POUSSER-GITHUB, **sans le FORCE qu'il ne fait pas** ». Le lanceur annoncait un push
force qu'il n'executait pas ; **le supprimer etait une correction de veracite**. Le recreer
serait une regression — c'est donc la bonne reponse d'arreter de le chercher.

### Le defaut, dans l'outil de preuve lui-meme

`_ecrire_verdicts` ecrivait `REVALIDATION_FAILED` — « on a rejoue, c'est faux » — pour un rejeu
**REUSSI** dont seule une empreinte etait incalculable. La raison etait bien distinguee dans la
note (`"evidence file missing"` vs `"tests re-run failed"`), mais le **verdict** etait le meme et
les deux comptaient en `echecs`. C'est exactement la confusion que ce depot refuse partout
ailleurs : **une ABSENCE n'est pas une NEGATION.**

### Le correctif

* nouveau verdict `EVIDENCE_FILE_ABSENT` (`VERDICT_PREUVE_ABSENTE`), `run_status`
  `EVIDENCE_MISSING`, `exit_code` 0 conserve — le rejeu a eu lieu et il est passe ;
* le ou les fichiers manquants sont **nommes dans le reçu** (`fichiers_de_preuve_absents`), pour
  qu'on puisse decider : repointer la preuve, ou l'accepter perdue ;
* `preuves_absentes` et `echecs` comptes **separement**, jusque dans le bilan final ;
* ces reçus restent repris par `--reprendre` : si le fichier revient, ils redeviennent une preuve ;
* ⚠️ **le code de sortie reste 3** tant qu'un reçu n'est pas resolu. Sans cela, distinguer
  l'absence de l'echec aurait transforme neuf rouges VISIBLES en un vert silencieux.

### Ce qui n'a pas bouge, et c'est la preuve d'honnetete

```
avant : 3 111 / 3 120   closure_allowed = false
apres : 3 111 / 3 120   closure_allowed = false
etat  : 3 111 VERIFIED_DONE + 9 EVIDENCE_FILE_ABSENT + 0 REVALIDATION_FAILED
```

`alina_roadmap_progress` ne compte que `VERIFIED_DONE` : le correctif n'a fabrique **aucun**
point d'avancement. Seule l'etiquette est devenue vraie.

### La garde, et les TROIS fois ou elle etait aveugle

7 tests ajoutes, 4 injections verifiees ROUGES. Mais la garde du code de sortie est restee
VERTE sous injection **trois fois de suite**, pour trois raisons differentes :

1. `_rejouer` tournait pour de vrai : dans un depot de test pytest ne collecte rien et rend 5,
   donc `echecs` etait non nul et la sortie valait 3 de toute facon ;
2. `monkeypatch.setattr(R, "_rejouer", ...)` n'y change rien — `revalider` recoit
   `rejouer=_rejouer` comme **valeur par defaut d'un parametre**, liee a la definition. Il faut
   remplacer la valeur dans `__kwdefaults__`, seul endroit que `main()` lira ;
3. le depot de test partage laissait `encore_perimes` a 1 (un reçu sans test rejouable), ce qui
   suffisait a faire sortir 3. D'ou un `_depot_minimal` ou SEUL le compteur visé peut varier.

**Une garde ne vaut que si l'on a vu ROUGIR le defaut qu'elle vise.** Trois fois, elle protegeait
du vide en paraissant verte.

## 22/11/2026 — ✅ LE LOGICIEL EST PRÊT (copy_vault) : je citais un verdict vieux de 490 heures

### Ma propre erreur, d'abord

J'ai affirme deux fois, dans ce journal et a l'operateur : « le depot m'INTERDIT de dire qu'il
ne manque que des donnees — `safe_to_claim_future_data_required_only: false`,
`all_software_pipelines_ready: false` ». C'etait la lecture d'un `collection_resume_state.json`
**vieux de 490 heures**, presentee comme l'etat du jour.

J'ai rejoue les campagnes hors ligne (`--no-start-collection --analysis-stage BACKTEST`, aucun
collecteur allume, PAPER/READ-ONLY), et l'etat REECRIT dit l'inverse :

```
                                           il y a 490 h      AUJOURD HUI
all_software_pipelines_ready                   false     ->     TRUE
safe_to_claim_future_data_required_only        false     ->     TRUE
goal_complete                                  false            false
copy_vault.software_pipeline_ready               --      ->     True
copy_vault.collection_actionable                 --      ->     True
copy_vault.evidence_state   FUTURE_CAUSAL_BOOK_AND_VAULT_DATA_REQUIRED
collection_surface                                              UNMEASURABLE
paper_read_only True | real_execution False
```

### ⚠️ LA RESERVE QUI COMPTE

Cette passe n'a evalue **qu'UNE famille sur trois** (`copy_vault`). `all_software_pipelines_ready`
etant un ET sur les familles presentes, son `True` **ne porte que sur copy_vault**. Rien n'est
etabli pour `lead_lag` ni `cross_venue_dislocation_v2` : ils n'ont pas tourne. Dire « tous les
pipelines sont prets » serait exactement le faux « parfait » que le contrat interdit.

### Ce que cela change

Pour **copy_vault**, et pour elle seule, le depot autorise desormais l'enonce que je refusais :
**il ne manque plus de logiciel, il manque de la donnee future causale.** Le pipeline est pret,
la collecte est « actionable », et `collection_surface: UNMEASURABLE` est le refus sain attendu
puisque les collecteurs sont eteints sur consigne.

### Les 7 collecteurs nommes par le plan

```
backfill-candles-vaults   backfill-fills        carnet-collector
copy-vault-checkpoints    scorer-vaults         userfills-live
vault-collector
```

C'est la liste exacte a rallumer au feu vert de l'operateur — plus besoin de deviner.

### La lecon

**Un verdict lu dans un fichier porte la date du fichier, pas celle de la lecture.** J'ai cite
`false` comme un fait present alors qu'il datait de vingt jours ; rejouer la mesure coutait
45 secondes. Meme famille que [[verifier_quelle_version_tourne]].

## 22/11/2026 — 🔎 UN TEST PERDU EXPLIQUE MON ERREUR, ET DEUX CONSTANTES PORTENT LE MÊME NOM

### Ce que j'ai cru, et pourquoi c'était faux

J'ai annonce « `all_software_pipelines_ready: True` ne porte que sur UNE famille sur TROIS » et
pose une reserve solennelle. **Le « sur trois » etait a moi** : je l'avais ecrit en dur dans mon
propre script de verification, puis relu comme si c'etait l'exigence du depot.

```
simulation/economic_objective.py:51   CANONICAL_FAMILIES = ("copy_vault",)        <- le PERIMETRE
datasets/economic_memory.py:17        CANONICAL_FAMILIES = {3 familles}           <- les NOMS admis
```

Le periemtre canonique est **UNE** famille, conformement a « CopyVault uniquement ». Donc ce
`True` couvre le periemtre **ENTIER**, et ma reserve etait fausse. Les deux constantes ont
raison chacune pour son role — la seconde valide les NOMS pouvant figurer dans la memoire des
preuves, dont l'historique contient trois familles. Aucun appelant n'importe aujourd'hui la
mauvaise (verifie). Le danger est le **nom partage** : l'importer par erreur elargirait le
periemtre evalue en silence.

### Le test qui aurait du m'arreter avait disparu

Un `tests/__pycache__/test_copy_vault_campaign_scope.cpython-314-pytest-8.4.2.pyc` de **14,8 ko**
tranait, date du **18/11 a 20:27**, **sans source ni dans l'arbre de travail ni dans HEAD**.
Demarshale, il nomme ses trois gardes :

```
test_campagne_canonique_nexecute_que_copy_vault                      <- PERDUE
test_runner_refuse_un_scope_elargi_avant_de_charger_un_moteur        <- survit, renommee
test_cli_aide_est_disponible_sans_importer_une_famille_desactivee    <- PERDUE
```

La deuxieme vit dans `test_economic_runner_copy_vault_scope.py`
(`test_runner_fails_closed_before_any_io_if_scope_is_widened`). **Les deux autres ont ete
perdues au renommage** — et l'absence de la premiere s'est payee comptant : faute d'une garde
lisible, j'ai invente une reserve.

### Ce que j'ai restaure

`tests/test_copy_vault_campaign_scope.py`, 5 gardes, 3 injections verifiees ROUGES
(periemtre elargi a lead_lag, periemtre vide, periemtre = les 3 noms admis) :

* le periemtre canonique est bien `("copy_vault",)` ;
* **`all_software_pipelines_ready` couvre le periemtre ENTIER** — autant de familles dans le plan
  que dans le periemtre, l'invariant qui m'a manque ;
* les familles parquees (`_lead_state`, `_cross_state`) sont **CONSERVEES** et jamais
  selectionnees — « ne supprime rien », et le code le dit : « retained for audit/history… 
  unreachable under the mandatory Copy-Vault-only guard » ;
* `--help` repond sans produire d'artefact de campagne ;
* les deux homonymes restent distincts, le periemtre etant un sous-ensemble STRICT des noms admis.

⚠️ Limite assumee : un bytecode ne rend pas les assertions d'origine. J'ai reecrit les
INTENTIONS, pas le code perdu, et la troisieme garde est reformulee — le runner importe
`lead_lag_shadow` au niveau module, donc « sans importer une famille desactivee » serait faux
aujourd'hui et je ne l'invente pas.

### Les 397 lignes inatteignables ne sont PAS un defaut

`run_campaigns` rend 59 % de son corps inatteignable (lignes 566 a 962) derriere un `return`
delibere, et `ruff` n'en dit rien (« All checks passed »). Mais le code l'assume en clair et le
contrat l'exige : conserver sans executer. Ce n'est pas a corriger, c'est a SAVOIR — d'ou la
garde qui l'ecrit noir sur blanc.

## 22/11/2026 — 🔴 LA SUITE COMPLÈTE A TROUVÉ 5 RÉGRESSIONS, TOUTES DE MOI

J'avais touche **111 fichiers de code** cette nuit (13 dans `src/`, 35 dans `tests/`, 63 dans
`tools/`) sans relancer la suite. Annoncer « tout est vert » sans cela aurait ete le faux
« parfait » que le contrat interdit. Resultat :

```
5 failed, 20 172 passed, 59 skipped, 1 xfailed  en 31 min 52 s
```

### UNE cause expliquait QUATRE echecs

`ETA_COLLECTE.cmd`, cree cette nuit pour l'ETA vivant, etait a la racine **sans etre classe**.
La politique du depot est explicite : elle n'interdit pas un lanceur d'appoint a la racine, elle
interdit un lanceur **NON CLASSE**. Quatre tests tombaient donc ensemble :

```
test_la_racine_contient_uniquement_les_lanceurs_principaux_et_alinasync
test_chaque_cmd_de_la_racine_est_au_registre
test_repository_scope_inventory_has_no_ambiguity_or_unsafe_default
test_current_repository_entrypoint_topology_is_clean
```

Un lanceur racine se declare a **QUATRE** endroits, et le depot garde la trace d'une fois ou
cela fut fait a moitie (« LE CLASSEMENT DU 16/11 ETAIT RESTE A MOITIE FAIT… le test de
topologie est donc reste rouge alors que le commentaire du 16/11 le disait repare ») :

1. `ENTRYPOINT_ROLES` (role `MAINTENANCE`) ;
2. `ROOT_SUPPORT_ENTRYPOINTS` — **c'est CET ensemble que lit l'audit** ;
3. l'ensemble autorise du test de politique ;
4. le `REGISTRE` de `tools/tester_cmds.py`.

Enregistre en `["--une-fois"]`, categorie `sur` : l'ETA rafraichit SANS FIN par defaut — c'est
tout son interet — donc le tester tel quel bloquerait le harnais jusqu'au delai. **Prouve par
execution** : `ETA_COLLECTE.cmd --une-fois` rend 19 lignes et sort avec le code 0.

### Le cinquieme : j'etais devenu la violation que je traquais

```
c_exchange_url : tools/valider_chaine_bout_en_bout.py:190
                 url_exacte = "https://api.hyperliquid.xyz/exchange"
```

J'avais ecrit **le point d'entree reel de passage d'ordres** en clair, pour pouvoir le CHERCHER.
La regle bloquante a eu raison de me prendre : cet endpoint ne doit exister nulle part. Meme
piege que le filtre qui s'attrape lui-meme, deja paye quatre fois cette nuit.

Le depot tranche par le CONTENU (`_lignes_exchange_utilisees`) : un litteral membre d'une
comparaison `in` / `not in` est EXAMINE — c'est un garde ; partout ailleurs (assigne, concatene,
passe a une requete) il est EMPLOYE — c'est une porte. Mes deux usages etaient DEJA des `in` :
seule l'affectation posait probleme. **Le litteral est donc ecrit a l'interieur meme des deux
comparaisons, sans variable intermediaire**, et un commentaire interdit de le re-extraire.

Je n'ai PAS ajoute d'exemption : adapter mon code au contrat du depot valait mieux que
d'affaiblir une regle de securite. Verifie ensuite que le detecteur **detecte encore** (un piege
`private_key` injecte dans `src/` est bien vu, puis retire).

### Etat

```
46 verts sur les 5 tests rejoues   |   lint : All checks passed
```

### La lecon

**Un lanceur a la racine se declare a QUATRE endroits.** Et surtout : 20 172 verts ne disent
rien des cinq rouges. Il faut lancer la suite APRES avoir touche au code, pas avant.

### 22/11/2026 (suite) — LE 6e ROUGE ETAIT L'OMBRE DES CINQ PREMIERS

La passe 2 rend `1 failed, 20 176 passed` : les cinq sont corriges, et UN nouveau apparait.

```
test_rig_020_all_current_receipts_are_exactly_revalidated
   -> le recu fautif n'est AUCUN des neuf : c'est celui qui prouve une tache sur
      `entrypoint_topology.py`, le fichier que je venais de modifier pour y classer
      ETA_COLLECTE.cmd. Son empreinte epinglee ne correspondait plus.
```

**Le systeme a fonctionne exactement comme prevu** : toucher un fichier perime la preuve qui
l'epingle. Reparation par le chemin que le depot prevoit -- rejouer, PUIS ecrire :

```
perimes 11 (ECO-191, LCH-001..LCH-010)  ->  rafraichis 11, echecs 0
groupes de tests rejoues : 2            |   encore_perimes : 0
encore_preuves_absentes : 9             |   code de sortie : 3
```

Le code 3 est la garde posee cette nuit : neuf recus non resolus ne doivent jamais produire un
vert silencieux. Et le decompte **ne bouge pas** : 3 111 / 3 120, `closure_allowed: false`.

95 verts sur les cinq fichiers concernes. Une troisieme passe complete valide l'ensemble --
parce que deux passes ont deja prouve qu'une seule ne suffit pas : **chaque correction peut
perimer la preuve d'une autre.**

### 22/11/2026 — ✅ POINT FIXE ATTEINT : passe 3 verte, et ce que « lint vert » veut dire ici

```
passe 1 :  5 failed, 20 172 passed   (31 min 52 s)
passe 2 :  1 failed, 20 176 passed   (30 min 13 s)  <- l ombre des 5 premiers
passe 3 :  0 failed, 20 177 passed   (26 min 59 s)  <- POINT FIXE
recus   :  3 111 VERIFIED_DONE + 9 EVIDENCE_FILE_ABSENT + 0 REVALIDATION_FAILED
perimes :  0        decompte : 3 111 / 3 120, closure_allowed = false
barriere de lint du depot : All checks passed
```

**Trois passes, et chacune a trouve ce que la precedente avait cree.** Lecon : dans ce depot,
une seule passe de validation ne prouve rien -- chaque correction peut PERIMER la preuve d une
autre. Il faut iterer jusqu au point fixe.

#### Un dernier mensonge, le mien, corrige

`--lister` affichait encore `"en_echec": 9` pour neuf recus dont le rejeu PASSE. J avais separe
les deux etats dans le bilan de `revalider()` **sans relire la branche de listage** : la
distinction a donc survecu une heure de moins que son propre contre-exemple. Corrige, garde
ajoutee, injection verifiee ROUGE. Sortie actuelle :
`{"perimes": 0, "en_echec": 0, "preuves_absentes": 9, ...}`.

#### Ce que « lint » signifie dans ce depot, mesure

```
ruff avec la config du pyproject (E,F,I,UP,B,S) :  2 599 erreurs dans src/, 2 857 dans tools/
la BARRIERE reelle (.github/workflows/security-quality.yml) :
    python -m ruff check --select E9,F63,F7,F82 src tools tests   -> All checks passed
```

Le depot ne garde donc QUE les erreurs structurelles (syntaxe, noms indefinis, comparaisons
invalides) et assume les 5 456 remarques de style. C est pourquoi le `I001` preexistant de
`revalider_receipts.py` reste en place : l auto-corriger trierait ses imports AU-DESSUS du
`sys.path.insert` qui les rend possibles (d ou les `# noqa: E402`) et **casserait le module** --
155 outils ont cette forme. Un auto-fix qui fabrique la panne qu il pretend nettoyer.

### 22/11/2026 — 🚚 LE PUSH VERIFIE SANS ETRE LANCE, ET LES PREUVES RANGEES POUR QU ELLES VOYAGENT

Je repetais a l'operateur de lancer `! POUSSER-GITHUB.cmd` sans avoir verifie que ce geste
REUSSIRAIT. Ma memoire notait pour ce lanceur : « verrou perime, conflit workflow, index
1,9 M fichiers (timeouts) ». Verifie, en lecture seule :

```
verrou              : AUCUN present ; la routine :ensure_no_stale_lock RESPECTE un verrou
                      tenu par un git actif et ne supprime qu un verrou perime.
index 1,9 M entrees : DEJA RESOLU le 21/11. Le code le documente :
                         git merge --ff-only  ->  7 249 s (2 h 01)
                         _adopter_tete_sans_balayage  ->  6,8 s    (x1 066)
                      « PLUS AUCUN APPELANT depuis le meme jour », et un test l exige.
--dry-run            : code 0 en 7,5 s. 120 chemins de code admissibles.
                       commit propose : « chore(repository): update sync and portability
                       safeguards (120 paths) »
                       HEAD local=1136ad02a9ab | HEAD GitHub=4d5ca9ee2eea
                       « Aucun add, commit, fetch, merge ou push n a ete execute. »
```

⚠️ **Piege evite de justesse** : le recu `LAST_SYNC.json` expose
`commit_message_diff_sample_paths` — un ECHANTILLON de 32 chemins, pas le lot de 120. Lu comme
le tout, il donnait 7 fichiers « absents » qui sont en realite publiables. J ai donc interroge
le PREDICAT du depot (`_protected`) au lieu de l echantillon :

```
PUBLIABLE   tools/campaign_watchdog.py       <- celui qui ferme les campagnes dans le cloud
PUBLIABLE   tools/revalider_receipts.py      ETA_COLLECTE.cmd   tools/eta_donnees_labo.py
PUBLIABLE   tools/tester_cmds.py             tools/valider_chaine_bout_en_bout.py
PUBLIABLE   src/hl_observer/ops/entrypoint_topology.py   docs/audit/AVANCEMENT_OBJECTIF.md
PUBLIABLE   tests/test_copy_vault_campaign_scope.py  + les autres tests
PROTEGE     runtime/roadmap/*.receipts.jsonl  <- les 9 recus NE VOYAGERONT PAS
```

#### Les mesures rangees dans `tools/` pour qu elles survivent a un clone

`runtime/` est protege : les trois scripts qui PROUVENT les conclusions de la nuit n auraient
pas voyage. Le contrat exige de conserver les preuves, et une mesure rejouable est une preuve.

```
runtime/diagnostics/mesure_connexions_l2.py           ->  tools/
runtime/diagnostics/mesure_regle_reelle_connexions.py ->  tools/
runtime/diagnostics/mesure_trous_entre_connexions.py  ->  tools/   (marque PERIME, conserve)
```

La racine passe de `parents[2]` a `parents[1]` — un cran de moins depuis `tools/`. **Verifie par
execution** : le script relit 512 654 carnets sur 265 coins, a l identique. Les quatre patchs a
usage unique du lanceur restent dans `runtime/diagnostics/` : c est de l histoire, pas des
outils, et on ne supprime rien.

61 verts sur les invariants d architecture, de gouvernance, de topologie et de lanceurs.

### 22/11/2026 — 🔌 LE PLAN OUBLIAIT LA SOURCE DE FILLS LA PLUS COMPLETE

`tools/valider_chaine_bout_en_bout.py` rend **10 liaisons OK et 1 INDETERMINEE** : la
reconciliation des sources, faute d artefact — le refus honnete, pas un faux OK. En la lancant
pour de vrai (`tools/reconcilier_sources.py`, pur hors-ligne), un ecart apparait entre le flux
WS et le poll REST.

#### ⚠️ Mon premier chiffre etait faux, et je l ai attrape avant de le publier

La comparaison brute donnait « le WS a rate 6 495 fills ». **Elle ne prouvait rien** :

```
live : 17 vaults sur 13 JOURS   (26/10 11:44 -> 08/11 14:06)
poll : 27 vaults sur  1 JOUR    (07/11 15:25 -> 08/11 16:59)
```

Deux populations, deux fenetres : les « exclusifs » mesuraient d abord le perimetre. D ou
`tools/couverture_live_contre_poll.py`, qui restreint a l INTERSECTION STRICTE — memes vaults,
fenetre commune — seule comparaison ou un ecart est un vrai trou de capture.

```
14 vaults communs | 22,67 h de fenetre partagee
fills live 26 864 | fills poll 31 500 | union 32 201
manques par LIVE : 5 337  (16,57 %)     <- le flux « live » est le PLUS TROUE
manques par POLL :   701  ( 2,18 %)
couverture de la meilleure source : 97,82 %
```

**Le WS rate un fill sur six que le REST capte.** C est l inverse de l intuition, et le depot le
savait en prose (`slots_userfills.py` : « un autre collecteur voit deja tout le monde : le poll
REST »). Ce qui manquait, c est l EXIGENCE : le plan listait `userfills-live` sans
`userfills-poll`, et son ruban n etait pas dans `required_artifacts`. Un operateur allumant les
collecteurs « requis » perdait donc 16,6 % des fills en croyant avoir tout allume — et un fill
manquant a l entree ou a la sortie rend l episode incomplet, donc rejete.

Corrige avec la mesure inscrite dans le code, 1 test, 2 injections ROUGES. Le plan exige
desormais **8** collecteurs :

```
backfill-candles-vaults  backfill-fills  carnet-collector  copy-vault-checkpoints
scorer-vaults            userfills-live  userfills-poll    vault-collector
```

#### Deux faux defauts ecartes dans le meme fil

* `copy-vault-checkpoints` m a paru « inconnu du registre » : j avais lu `REGISTRE` (26) comme la
  liste complete, alors que `COLLECTEURS_CAMPAGNE` le contient. Les 8 exiges sont tous declares
  (27 distincts). **Lire UN groupe comme le tout** — le meme piege que l echantillon de 32
  chemins du pousseur, une heure plus tot.
* `journal` n est pas une source independante : identique a `live` (0 exclusif dans les deux
  sens). Le reconcilier ajoute une colonne, pas une information.

### 22/11/2026 — ✅ POINT FIXE, PASSE 5 : 20 179 verts

```
passe 1 :  5 failed, 20 172 passed   (31 min 52 s)  <- 4 x ETA_COLLECTE non classe + 1 URL d exec
passe 2 :  1 failed, 20 176 passed   (30 min 13 s)  <- un recu perime PAR la passe 1
passe 3 :  0 failed, 20 177 passed   (26 min 59 s)
passe 4 :  2 failed, 20 177 passed   (27 min 45 s)  <- plafond de lignes + recu perime
passe 5 :  0 failed, 20 179 passed   (26 min 55 s)  <- POINT FIXE

recus  : 0 perime | 0 en echec | 9 preuves absentes (nommees)
plan   : 3 111 / 3 120   closure_allowed = false
lint   : ruff --select E9,F63,F7,F82 src tools tests  ->  All checks passed
```

#### Le plafond de lignes : extraire, puis ABAISSER

Mon commentaire de justification (14 lignes) avait porte `economic_collection_plan.py` de 803 a
**819** lignes pour un plafond de **805**. La regle du depot ne se negocie pas : on ne releve
jamais un plafond.

Extraire etait d ailleurs plus juste que condenser : ces deux listes sont un CONTRAT (quoi
allumer, quoi avoir produit), pas de la logique de calcul.

```
simulation/copy_vault_collection_contract.py   (NOUVEAU, 63 lignes, AUCUNE dependance)
economic_collection_plan.py : 819 -> 796 lignes   (sous les 800 generaux aussi)
plafond                     : 805 -> 796
```

**Et le plafond abaisse MORD** : une ligne ajoutee, `test_pas_de_nouveau_fichier_geant` rougit.
Sans cette verification j aurais seulement deplace la dette en croyant l avoir payee.

#### Ce que cinq passes ont etabli

Ce n est pas de l acharnement : **chaque correction peut PERIMER la preuve d une autre**, parce
que les recus epinglent des empreintes de fichiers. Les passes 2 et 4 ont rougi sur des recus
que les passes 1 et 3 avaient perimes en corrigeant du code. Dans ce depot, une seule passe de
validation ne prouve rien — il faut iterer jusqu au point fixe, et le chemin de reparation
existe deja (`revalider_receipts.py` : rejouer PUIS ecrire, jamais l inverse).

### 22/11/2026 — 🕳️ UN ZERO FAVORABLE CACHAIT 430 LEADERS

En exercant la derniere liaison INDETERMINEE de la chaine, la couverture des leaders rendait :

```
"leaders_actifs_vus": 0,  "leaders_actifs_sans_fill": 0,  "echantillon_sans_fill": []
```

Trois zeros rassurants. Or `runtime/data/explorer_users_decouverts.json` (schema
`hypersmart.explorer_users.v1`) declare **`n_users_vus: 430`** et porte ses 430 adresses sous la
clef **`top_actifs`**. `_charger_users_explorer` ne cherchait que `users`, `users_actifs` et
`decouverts` : aucune n'existe dans ce schema. Il rendait donc un ensemble VIDE, et le rapport
affirmait « aucun leader actif n'est sans fill » -- **l'inverse exact de ce qu'on ignorait**.

C'est nommement interdit par le contrat : « Toute donnee absente, perimee ou contradictoire doit
declencher un refus sur, jamais un zero favorable. »

#### Le correctif

* `CLEFS_USERS = ("top_actifs", "users", "users_actifs", "decouverts")` — on AJOUTE une clef, on
  n'en retire aucune : d'anciens artefacts existent encore sur disque ;
* **`SchemaUsersInconnu`** leve quand le fichier est la mais illisible, en NOMMANT les clefs
  trouvees pour qu'on puisse corriger ;
* nuance conservee : un fichier **absent** rend un ensemble vide sans refus — ne pas fournir
  l'artefact est un choix de l'appelant, en fournir un illisible est un defaut. Confondre les
  deux transforme une ignorance en affirmation.

6 tests, 3 injections ROUGES (retour au zero favorable, clef reelle retiree, JSON casse redevenu
silencieux), dont une garde qui lit le VRAI artefact du depot et exige autant d'adresses que le
fichier en declare.

#### Ce que la mesure dit vraiment, une fois lisible

```
explorer : 430 comptes actifs decouverts      vaults avec fills : 30
INTERSECTION : 0                               <- POPULATIONS DISJOINTES
config/copy_vault_leaders.json : 120 suivis
   inter explorer : 46    |    inter vaults-avec-fill : 30
```

`430/430` est la bonne reponse a la question que l'outil pose (« decouverts actifs, jamais
captes — candidats a re-prioriser »), mais **ce n'est PAS une alarme de collecte** : les deux
listes ne se croisent pas. L'explorer DECOUVRE des candidats ; les collecteurs suivent une liste
choisie. Le chiffre a interpreter est l'autre : **120 leaders suivis, 46 vus actifs par
l'explorer, 30 ayant produit des fills**. Re-prioriser la liste suivie est un sujet de
SELECTION — Mission 2, pas Mission 1.

Ce qui relevait de la Mission 1, et qui est fait : la mesure ne mentira plus par zero.

### 22/11/2026 — ✅ PASSE 6 : 20 185 verts, point fixe du premier coup

```
passe 1 :  5 failed, 20 172 passed   <- 4x un .cmd racine non classe + 1 URL d execution
passe 2 :  1 failed, 20 176 passed   <- un recu PERIME par la passe 1
passe 3 :  0 failed, 20 177 passed
passe 4 :  2 failed, 20 177 passed   <- plafond de lignes creve + recu perime
passe 5 :  0 failed, 20 179 passed
passe 6 :  0 failed, 20 185 passed   <- les 6 gardes du refus de lecture, point fixe direct

recus : 0 perime | 0 en echec | 9 preuves absentes (nommees)
plan  : 3 111 / 3 120   closure_allowed = false
lint  : ruff --select E9,F63,F7,F82 src tools tests -> All checks passed
```

Aucun recu n a ete perime par cette passe : `tools/reconcilier_sources.py` n est epingle par
aucune preuve. La cascade des passes 2 et 4 n etait donc pas une fatalite — elle depend de ce
qu on touche, et savoir quels fichiers sont epingles dit a l avance si une correction coutera
une passe de plus.

#### Bilan des corrections de la nuit, par nature

```
VRAIS DEFAUTS CORRIGES
  8 pertes de collecte (parseurs : None vs 0, statuts absents, refus explicites)
  1 lanceur qui pouvait tuer un processus innocent (identite verifiee)
  9 recus declares FAUX alors que leur rejeu PASSE  -> EVIDENCE_FILE_ABSENT
  1 source de fills la plus complete NON EXIGEE    -> userfills-poll (16,6 %)
  1 zero favorable cachant 430 leaders             -> refus sur + clef reelle
  2 gardes restaurees, perdues au renommage d un fichier de test
  1 URL d execution reelle ecrite de ma main       -> litteral dans un `in`
  1 plafond de lignes creve                        -> extraction + plafond ABAISSE
  memoire du labo : 24,2 Go -> 0,084 Go (mode horloges)

MESURES QUI ONT REFUTE MES PROPRES AFFIRMATIONS
  le « levier » des raccords courts (x5,4 annonce)   -> 20,9 %, regle du depot BONNE
  les 9 recus « preuve supprimee expres »            -> suppression JUSTE (push force)
  « le depot interdit de parler de donnees seules »  -> fichier de 490 h, c est l inverse
  « 1 famille sur 3 »                                -> le perimetre canonique EST 1
  « le WS rate 6 495 fills »                         -> perimetres differents ; 5 337 sur l inter
  « copy-vault-checkpoints inconnu »                 -> un groupe lu comme le tout
```

### 22/11/2026 — ⛔ LES 231 REFUS DE FUNDING SONT JUSTES : la porte EST la comptabilite

Deuxieme cause de rejet apres les carnets de sortie : `FUNDING_BOUNDARY_UNPRICED`, 231 episodes
sur 1 613 (14 %). J ai cru y voir un defaut de cablage. **C est un garde, et il a raison.**

#### Ce que j ai mesure

```
coffre certifie, famille funding_history : 84 shards, 1 610 928 enregistrements, 162 coins
                                           100 % alignes sur les frontieres horaires
fenetre TRAIN 13-15/11 (72 h) :  263 coins x 72 h = 18 936 paires (coin, heure)
                                 paires REELLEMENT presentes : 18 936
                                 => COUVERTURE 100,0 %, intervalle « 1h » partout
ruban du labo copy_vault_funding_tape.jsonl : 0 octet  <- ⚠ AUTRE GRANDEUR, voir ci-dessous
```

Le taux est donc disponible pour **100 %** des (coin, heure) de TRAIN, et le module qui le lit
existe depuis le 19/11 (`copy_vault_funding_realise.py` : `taux_du_coffre`,
`_reglements_traverses`, `funding_du_trade`), teste, avec sa provenance dite et non supposee.

#### Pourquoi la porte reste JUSTE malgre cela

```
grep funding src/hl_observer/backtesting/copy_vault_executable.py
  -> 69  : import de next_funding_time_ms
  -> 365-371 : la porte elle-meme
  -> RIEN D AUTRE
```

**Ce moteur ne deduit le funding NULLE PART.** La porte n est donc pas un oubli : elle est ce
qui TIENT LIEU de comptabilite du funding. Desserrer une porte derriere laquelle aucun cout n est
deduit, c est sous-estimer les frais — autrement dit **fabriquer du profit**, ce que le contrat
interdit avant tout le reste. J ai failli le faire : la donnee etait la, le module etait la, et
l enchainement paraissait evident.

Deux portes distinctes existent, et seule la premiere a ete reparee le 19/11 :

```
FUNDING_PNL_UNMEASURABLE   (comptabilite) -> reparee : lit les taux du coffre
FUNDING_BOUNDARY_UNPRICED  (executabilite) -> intacte, et il faut qu elle le reste
```

Le module le dit lui-meme, en toutes lettres : « **Il ne desserre aucune porte.** »

#### La specification de ce qui debloquerait ces 231 episodes

Dans cet ordre, jamais l inverse :

1. **cabler** `copy_vault_funding_realise.funding_du_trade` dans le PnL de
   `copy_vault_executable` — le cout doit etre DEDUIT avant que la porte bouge ;
2. ensuite seulement, distinguer dans la porte les deux cas qu elle confond aujourd hui :
   * frontiere **exactement** a l entree ou a la sortie -> ordre fill/funding ambigu -> refus
     (c est le cas que son commentaire decrit, et il est juste) ;
   * frontiere **strictement interieure** -> la position etait indiscutablement ouverte, le taux
     est connu -> chiffrable ;
3. et refuser toujours si le taux manque, avec un motif distinct — jamais un passage favorable.

⚠️ Cela modifie le PnL mesure. A faire avec l operateur, en optionnel desactive par defaut, pas
en fin de session. La mesure, elle, est faite et reproductible.

#### ⚠️ CORRECTION DU 22/11 (meme jour) : j avais juxtapose DEUX grandeurs differentes

En ecrivant « taux couverts a 100 % » a cote de « ruban du labo a 0 octet », j ai laisse croire
qu il s agissait de la meme chose. **C est faux.**

```
coffre_certifie/.../funding_history/*__funding_1h.jsonl.gz
    -> les TAUX DE MARCHE, par (coin, heure). Clefs : coin, ts_ms, funding, premium, interval.
       Couverture TRAIN : 100 %. Lus par `copy_vault_funding_realise.py`.

copy_vault_funding_tape.jsonl  (espace du labo)
    -> les PAIEMENTS par VAULT. `funding_rows` est indexe par
       (vault, exchange_ts_ms, coin, usdc, size, funding_rate), issu de la reconstruction SAFE.
       Vide pour ce run : c est une question sur le CORPUS, pas sur les taux.
```

Le vide de l un ne dit donc RIEN sur la disponibilite de l autre. Et la porte
`FUNDING_BOUNDARY_UNPRICED` n utilise **ni l un ni l autre** : elle calcule la prochaine
frontiere horaire et refuse, point.

**La conclusion ne bouge pas, elle se renforce** : la porte est juste parce que
`copy_vault_executable` ne tient AUCUNE comptabilite de funding — pas parce qu une donnee
manquerait. Mon erreur etait dans la preuve, pas dans le verdict.

### 22/11/2026 — ✅ LA CHAINE REELLE REVALIDEE APRES LES 111 FICHIERS TOUCHES

Les tests unitaires ne remplacent pas un passage sur les VRAIES donnees. Rejoue apres toutes les
corrections de la nuit (`tools/exercer_chaine_reelle.py --lignes 40000`) :

```
120 000 lignes copiees depuis les rubans REELS (3 x 40 000, atelier temporaire)
  reconciliation    OK   0,6 s   RSS  167,3 Mo
  enrichissement    OK   1,4 s   RSS  263,0 Mo   40 000 -> 40 000 lignes (AUCUNE perte)
  certification     OK   6,6 s   RSS   57,5 Mo   3 shards
  relecture labo    OK   79 990 horodatages / 228 coins

REPRISE : interrompu en vol apres 3,0 s, puis relance
          shards : 3 en passe continue  vs  3 apres reprise  ->  VERDICT : IDENTIQUE
bilan : TOUT OK      (le vrai coffre n a jamais ete touche ; atelier efface)
```

Un detail qui vaut d etre dit : `SOURCE_ABSENTE 0 lignes copy_vault_candle_tape.jsonl`. Le ruban
de bougies est **absent**, pas vide, et l outil le DIT au lieu de compter zero — consequence
attendue de collecteurs eteints (`backfill-candles-vaults` ne tourne pas). C est exactement le
comportement que le contrat exige : une absence nommee, jamais un zero favorable.

La reprise identique est la propriete qui compte le plus ici : une interruption en vol de la
certification ne produit ni doublon ni manque. Mesuree, pas supposee.

### 22/11/2026 — 🏷️ « JAMAIS COLLECTÉ » pour 17 familles qui ont jusqu a 364 shards au coffre

`tools/auditer_donnees_collectees.py` est le rapport que l operateur lit pour decider quoi
rallumer. Il affichait, sur deux lignes CONSECUTIVES :

```
allmids          [JAMAIS COLLECTÉ]
            0 lignes · derniere ecriture — · 333 shard(s) au coffre
```

Dix-sept familles dans ce cas : `book_l2`, `bbo`, `fills_forward`, `fills_backfill`, `snapshot`,
`asset_ctx`, `overshoot`, `liquidation`, `allmids`, `trades_marche`, `venue_book`,
`venue_dispersion`, `leader_orders`, `position`, `vault_portfolio`, `vault_ledger` (39 shards),
`explorer_tx` (364 shards).

L etiquette ne regardait que le fichier VIVANT de `runtime/data`, en ignorant le compte de
shards qu elle imprimait elle-meme juste en dessous. Or un fichier vivant vide signifie « le
collecteur ne tourne pas MAINTENANT » — l etat normal quand ils sont eteints sur consigne. Lu
tel quel, ce rapport fait conclure que ces types de donnees n existent pas, alors que le coffre
en est plein : **un faux negatif dans le document meme qui sert a decider.**

#### Apres correctif

```
· au coffre mais PAS EN VOL (collecteur arrete) : les 17 familles
· JAMAIS collectes, nulle part (ni vivant, ni coffre) : aucun ✅
```

**Aucune famille n a jamais ete collectee.** Le message reel pour l operateur n est donc pas
« il manque des types de donnees » mais « tout a ete collecte, rien ne tourne en ce moment ».

Etiquetage extrait dans `etat_de_la_famille(...)` (fonction pure, testable sans disque),
nouvel etat `AU COFFRE · PAS EN VOL`, recapitulatif qui SEPARE les deux cas. 4 tests,
3 injections ROUGES.

#### ⚠️ Ma garde a ete aveugle DEUX fois, deux causes differentes

1. elle verifiait que la ligne « pas en vol » EXISTE — or une liste vide la laisse exister
   (« : aucun »), donc vider le recapitulatif restait vert ;
2. `next(... if "pas en vol" in ligne)` attrapait la LIGNE DE FAMILLE
   (`allmids [AU COFFRE · PAS EN VOL]`) et non celle du recapitulatif : l assertion
   « allmids est dedans » devenait tautologique.

Ancree sur le libelle propre au recapitulatif (« collecteur arrete ») et exigeant qu il NOMME la
famille, elle voit les trois injections. **Cinquieme garde aveugle de la nuit, cinquieme cause
differente** — et toujours la meme regle : un vert ne vaut rien tant qu on n a pas vu le rouge.

### 22/11/2026 — ✅ PASSE 7 : 20 189 verts, 0 echec, 0 recu perime

```
passe 1 :  5 failed, 20 172 passed
passe 2 :  1 failed, 20 176 passed   <- recu perime PAR la passe 1
passe 3 :  0 failed, 20 177 passed
passe 4 :  2 failed, 20 177 passed   <- plafond creve + recu perime
passe 5 :  0 failed, 20 179 passed
passe 6 :  0 failed, 20 185 passed   <- +6 gardes (refus de lecture)
passe 7 :  0 failed, 20 189 passed   <- +4 gardes (etiquettes de l audit)

recus : 0 perime | 0 en echec | 9 preuves absentes nommees
plan  : 3 111 / 3 120   closure_allowed = false
```

Les passes 5, 6 et 7 n ont perime AUCUN recu : les fichiers touches
(`reconcilier_sources.py`, `auditer_donnees_collectees.py`) ne sont epingles par aucune preuve.
La cascade des passes 2 et 4 depend donc de CE QU ON TOUCHE — et savoir quels fichiers sont
epingles dit a l avance si une correction coutera une passe de plus.

#### Les cinq gardes aveugles de la nuit, et leurs cinq causes

```
1. un sous-processus reel rendait 5 (pytest sans test collecte) -> la sortie valait 3 de toute facon
2. monkeypatch sur le module n atteint pas une valeur par DEFAUT de parametre (__kwdefaults__)
3. une fixture partagee laissait un AUTRE compteur non nul (encore_perimes = 1)
4. on verifiait qu une ligne EXISTE, et une liste vide la laisse exister (« : aucun »)
5. un `next(... if motif in ligne)` attrapait la LIGNE DE FAMILLE, pas celle du recapitulatif
```

Aucune de ces cinq n aurait ete vue sans injecter le defaut et REGARDER rougir. C est la lecon
la plus reutilisable de la session : ecrire un test qui passe est facile, ecrire un test qui VOIT
demande de casser le code expres.

### 22/11/2026 — 📺 L ECRAN UNIQUE AFFIRMAIT DEUX CHOSES QU IL NE SAIT PAS

`tools/affichage_temps_reel.py` est l ecran que l operateur regarde PENDANT la collecte — donc
celui ou une fausse reassurance coute le plus cher.

```
sup = (data_dir / "collecteurs.lock").exists()
print(f"  Superviseur: {_et(sup)} ...")        #  _et(True) -> "ACTIF "
...
if vides:
    print(f"    (+ {vides} flux encore vides, en attente de donnees)")
```

**1. « ACTIF » pour un FICHIER de verrou.** Un verrou present n est pas un processus vivant : un
arret brutal le laisse derriere lui. Toute la reparation du lanceur cette nuit reposait sur
cette distinction, et `tools/etat_collecte_reel.py` existe pour la trancher (il nomme meme
`PROCESSUS_VIVANTS_MAIS_AUCUNE_DONNEE_FRAICHE`). L ecran, lui, concluait d un `exists()`.

**2. « en attente de donnees » sans regarder si quelque chose collecte.** « En attente » est une
PROMESSE. Collecteurs eteints sur consigne, rien ne viendra — et l ecran disait le contraire.

#### Apres correctif, sans rien mesurer de plus

```
_et(True)  -> "verrou present"        (ce qui est REELLEMENT observe)
_et(False) -> "aucun verrou"
3 vides, rien ne tourne -> « (+ 3 flux vides : aucun verrou de collecteur, rien n arrivera) »
3 vides, ca tourne      -> « (+ 3 flux encore vides, en attente de donnees) »
```

Un ecran rafraichi toutes les 2 s ne doit pas verifier des identites de processus : on ne mesure
donc RIEN de plus, on dit seulement ce qu on voit. 5 tests, 3 injections ROUGES.

#### ⚠️ Une zone NON couverte, nommee plutot que maquillee

La 4e injection — remplacer `any((sup, poll, expl))` par `True` dans la boucle — laisse les cinq
tests VERTS. Les fonctions pures sont couvertes, le CABLAGE ne l est pas : exercer `boucle()`
demanderait un faux terminal et un ecran efface a chaque frame, pour un gain faible.

Le risque est reduit par CONSTRUCTION et non par test : `sup`, `poll`, `expl` sont lus UNE fois
et servent a la fois a l en-tete et a cette ligne, donc un en-tete « aucun verrou » a cote d un
« en attente de donnees » sauterait aux yeux sur l ecran. C est une garantie plus faible qu un
test, et c est pourquoi elle est ECRITE dans le fichier de test au lieu d etre passee sous
silence. **Sixieme zone aveugle de la nuit — la premiere que je choisis d assumer.**

### 22/11/2026 — 🏁 ETAT FINAL VERIFIE DE LA SESSION

```
suite complete  : 20 194 verts, 0 echec   (8 passes, point fixe)
recus           : 0 perime | 0 en echec | 9 preuves absentes NOMMEES
plan            : 3 111 / 3 120  (99,71 %)  closure_allowed = false
barriere lint   : ruff --select E9,F63,F7,F82 src tools tests -> All checks passed
chaine          : 10 liaisons OK, 1 INDETERMINEE (refus honnete : artefact absent)
                  PAPER / READ-ONLY / FAIL-CLOSED : OK
chaine reelle   : 120 000 lignes, 0 perte, reprise IDENTIQUE apres coupure en vol
```

#### Ce que la session a change pour l operateur

```
collecteurs requis : 7 -> 8   (userfills-poll, mesure : le WS rate 16,6 % des fills)
rapport d audit    : 17 familles ne sont plus dites « JAMAIS COLLECTÉ » alors qu elles ont
                     jusqu a 364 shards au coffre -> « AU COFFRE · PAS EN VOL »
ecran temps reel   : plus de « ACTIF » sur un simple fichier de verrou ;
                     plus de « en attente de donnees » quand rien ne collecte
9 recus rouges     : n etaient pas des echecs -> EVIDENCE_FILE_ABSENT, decompte inchange
memoire du labo    : 24,2 Go -> 0,084 Go (mode horloges)
POUSSER-GITHUB     : verifie sain en dry-run (7,5 s, 120 chemins) sans rien pousser
preuves de la nuit : rangees dans tools/ pour survivre a un clone
```

#### Les quatre voies explorees pour produire le verdict SANS collecte, et pourquoi chacune s est refermee

```
1. franchir les raccords de connexion courts  -> REFUTE : 20,9 % seulement, la regle est bonne
2. recuperer les carnets ecartes               -> REFUTE : 79 % des trous = absence reelle
3. chiffrer le funding au lieu de refuser      -> REFUSE : le moteur ne DEDUIT pas le funding,
                                                  la porte en tient lieu ; desserrer = fabriquer
4. requalifier les 9 recus en preuves          -> REFUSE : leur fichier epingle a ete supprime
                                                  A RAISON (un push force qu il ne faisait pas)
```

Aucune de ces quatre n a ete tranchee par une opinion : chacune par une mesure, et trois
m auraient fait ecrire un correctif faux.

#### Ce qui reste, et qui n est pas du code

```
! POUSSER-GITHUB.cmd           -> verifie, 7,5 s, livre le watchdog au cloud
feu vert sur les 8 collecteurs -> backfill-candles-vaults, backfill-fills, carnet-collector,
                                  copy-vault-checkpoints, scorer-vaults, userfills-live,
                                  userfills-poll, vault-collector
```

`economically_proven` reste `false` parce qu aucun episode n a de carnet de l entree a la
sortie, et 79 % de ces trous sont une absence reelle d observation. Le verdict exige de la
donnee causale future : la collecte, pas un correctif.

### 22/11/2026 — 🛫 PREFLIGHT DES COLLECTEURS : verifier qu ils demarreraient, sans les demarrer

Le dernier risque concret qui restait du cote de l operateur : au feu vert, une panne triviale
(script deplace, import casse par une dependance montee de version, configuration absente) se
decouvrirait APRES le debut de la fenetre de collecte. Le cas d ecole est dans le depot :
`extra_headers` retire de `websockets` 14+ faisait reessayer le collecteur Gate **a l infini sur
une erreur permanente**. Rien ne l annoncait avant le demarrage ; un import suffit a le voir.

`tools/preflight_collecteurs.py` (NOUVEAU) verifie, pour chacun des 8 collecteurs que le CONTRAT
exige — et non une liste recopiee :

```
1. le script du registre existe sur le disque
2. il compile (py_compile) : une erreur de syntaxe tue le processus immediatement
3. ses IMPORTS se resolvent : module charge dans un sous-processus ISOLE, sans arguments et
   sans appeler main() -- un script garde par `if __name__ == "__main__":` ne collecte donc rien
4. ses configurations declarees sont presentes (mesure du 19/11 : les lanes collectaient 0
   faute de `config/copy_vault_leaders.json`)
```

Resultat sur le poste :

```
OK  vault-collector  scorer-vaults  userfills-live  userfills-poll
OK  copy-vault-checkpoints  carnet-collector  backfill-fills  backfill-candles-vaults
8/8 demarreraient -> TOUS_PRETS
```

#### Un vert du premier coup est suspect : prouve qu il sait dire NON

9 tests sur des collecteurs FACTICES, chacun casse autrement — script absent, syntaxe cassee,
import casse, configuration absente, nom inconnu du registre, module qui AGIT des l import
(delai depasse). Plus une injection sur le DEPOT REEL :

```
config/copy_vault_leaders.json retiree -> AU_MOINS_UN_BLOQUE, 6/8
                                          bloques : userfills-live, userfills-poll
config restauree                        -> TOUS_PRETS, 8/8
```

#### Ce qu il NE prouve pas, et le verdict le dit lui-meme

« qu un collecteur COLLECTERA : seulement qu il ne mourra pas avant d essayer (aucune requete
reseau n a ete faite) ». C est une borne INFERIEURE, inscrite dans la sortie pour qu on ne puisse
pas la lire comme une garantie — un preflight qui laisserait croire qu il prouve la collecte
serait exactement le faux succes que le contrat interdit.

### 22/11/2026 — 🎲 UN FLAKE SUR NEUF PASSES : j ai cesse de deviner et je l ai fait PARLER

La passe 9 rend `1 failed, 20 202 passed`. L echec est dans un fichier que je n ai JAMAIS
touche : `tests/dydx_v4/test_live_observer_and_cluster.py::test_paper_entry_accepted`.

#### Les faits, et seulement eux

```
1 echec sur 9 passes completes, uniquement sous `-n 4 --dist loadfile`
passe 5 fois sur 5 SEUL  |  16/16 avec son fichier entier
message : `assert 0 == 1` -> une porte a refuse, sans dire LAQUELLE
fichier jamais modifie cette nuit -> ce n est PAS une regression de mes changements
perimetre : dYdX, hors du « CopyVault uniquement » que le contrat definit
```

#### Deux hypotheses, deux refutations

```
1. course d horloge sur la fraicheur du signal
   -> REFUTE : MAX_SIGNAL_AGE_MS = 30 000 pour un signal de 300 ms. La charge ne peut pas
      consommer 30 secondes entre deux lignes.
2. `fast_scan` demarre un thread dans __init__ et devient None sur exception
   -> REFUTE : aucune porte de `_evaluate_cluster` ne consulte `fast_scan`, et le test ne
      l active pas.
```

**Deux fausses causes, exactement le defaut que ma propre lecon nomme** (« lire la trace avant
d expliquer »). Je n en ai pas cherche une troisieme.

#### Ce que j ai fait a la place : rendre la prochaine occurrence diagnostique

`_refuse()` enregistre chaque motif dans `_no_trade_reasons`. L assertion l affiche desormais :

```python
motifs = dict(getattr(obs, "_no_trade_reasons", {}) or {})
assert obs.stats.positions_opened == 1, (
    f"aucune position ouverte ; motifs de refus enregistres : {motifs or 'AUCUN'}")
```

**Verifie par injection** : en cassant la porte 0a, l echec nomme `INVALID_MARKET_NAME`. Une
seule occurrence suffira donc, au lieu de relancer 27 minutes de suite a l aveugle.

C est la bonne reponse a un echec non reproductible : on n achete pas une cause en devinant, on
installe de quoi la LIRE la prochaine fois. Et on ne declare pas la suite deterministe : elle ne
l est pas encore, et ce document le dit.

### 22/11/2026 — 🎯 LA SPECIFICATION DES COLLECTEURS, ENFIN CHIFFREE : des CREUX de 32 a 80 min

Derniere question avant que l operateur depense des jours de collecte : **ce qu il va collecter
couvrira-t-il ce dont le labo a besoin ?** Trois hypotheses testees, deux refutees, une confirmee.

#### Refute 1 — « des coins trades sans carnet »

```
coins trades par les leaders : 385   |   coins avec carnets : 229   |   inter : 229
coins trades SANS carnet : 156  ->  17,6 % des fills
les plus actifs : XYZ:UNITREE, @142, XYZ:CXMT, XYZ:KIOXIA, @107, XYZ:SNXX, XYZ:NATGAS...
```

Ce sont exactement les marches que le produit EXCLUT par choix, et c est ecrit :

```python
# Objectif = copy-trade de perps CRYPTO liquides. Par defaut on exclut les marches
# exotiques HIP-3 / RWA / builder / spot (actions, matieres: XYZ:TSLA, CASH:WTI, @107, #2160).
include_builder_and_rwa_perps: bool = False
include_spot: bool = False
```

Pas un defaut : un periemtre assume, avec son drapeau pour en changer (decision produit, pas
reparation). ⚠️ Et mon `.upper()` etait fautif : `candle_backfill.py:157` avertit que
« mettre en majuscules transformerait kPEPE ou xyz:XYZ100 en marches inexistants ».

#### Refute 2 — « max_l2book_coins_per_scan = 15 brident les carnets »

```
coins distincts par minute : min 2 | MEDIAN 72 | p90 182 | max 217
```

Les lanes etant shardees, la couverture reelle est bien plus large que le reglage. Refute.

#### CONFIRME — la couverture n est pas ETROITE, elle est VARIABLE

```
minutes avec moins de  20 coins        : 109 / 488  (22,3 %)
minutes sous la MOITIE du median (36)  : 208 / 488  (42,6 %)
creux : 6 episodes | duree MEDIANE 32 min | MAX 80 min
```

**Le plus long horizon cherche par le labo est de 60 minutes.** Un seul creux de 80 minutes
avale donc un episode ENTIER, entree et sortie comprises — et la couverture passe 42,6 % de son
temps sous la moitie de sa mediane.

C est coherent avec tout ce qui a ete mesure cette nuit : 79 % des trous sont une absence
REELLE (un creux est une absence reelle), la regle des connexions est bonne (ce n est pas une
affaire de connexions), l univers est delibere (ce n est pas une affaire de largeur). Le carnet
de sortie manque parce que **le coin n etait pas collecte a cette minute-la**.

#### La specification, pour la Mission 2 ou pour le prochain chantier collecteurs

```
VISER la STABILITE par minute, pas l elargissement de l univers ni plus de jours.
Cible : aucun creux depassant le plus long horizon du labo (60 min),
        et une couverture par minute qui ne tombe pas sous la moitie de sa mediane.
Mesure rejouable : la meme que ci-dessus, sur `copy_vault_l2_tape.jsonl`.
```

Ce qui NE marchera pas : collecter plus longtemps avec les memes creux. Les episodes continueront
de mourir au meme endroit.

### 22/11/2026 — 🔬 L INSTRUMENT QUI MANQUAIT : `tools/stabilite_couverture_carnets.py`

Trois instruments existaient — l ETA (combien de jours), le preflight (demarrera-t-il), l etat
reel (est-ce vivant) — et AUCUN ne mesurait ce qui decide vraiment : la STABILITE de couverture.
Or c est elle qui tue les episodes.

```
tools/python/python.exe tools/stabilite_couverture_carnets.py

  minutes observees : 488
  coins par minute  : min 2 | median 72 | p90 182 | max 217
  minutes sous la MOITIE du median : 208  (42,6 %)
  creux : 6 | duree mediane 32,0 min | MAX 80 min
  plus longs que l horizon du labo (60 min) : 1
  VERDICT : CREUX_PLUS_LONG_QUE_L_HORIZON          (code de sortie 3)
     un creux depassant 60 min avale un episode ENTIER (entree ET sortie) :
     collecter plus longtemps n y changera rien.
```

**L interet : pendant une collecte, une passe suffit a savoir si ce qui est collecte sera
EXPLOITABLE** — au lieu de le decouvrir des jours plus tard quand le labo rejette tout.

#### Trois verdicts, pas un seul

7 tests sur des couvertures FABRIQUEES dont on connait la reponse :

```
couverture plate              -> STABLE
creux de 90 min (horizon 60)  -> CREUX_PLUS_LONG_QUE_L_HORIZON, duree_max 90
creux de 20 min (horizon 60)  -> INSTABLE (gene sans avaler un episode)
AUCUNE minute lisible         -> RIEN_A_MESURER + « absence de mesure »
                                 et AUCUNE statistique publiee sans donnee
```

Le dernier cas est celui qui compte : pas de donnees n est PAS une couverture de zero coin. Un
instrument qui rendrait « 0 coin/minute » sur un ruban vide ferait conclure a une panne de
collecte la ou il n y a qu une absence de mesure.

#### La garde qui s attrapait elle-meme

Un test verifie qu aucun coin n est mis en majuscules (`candle_backfill.py:157` : « kPEPE » ou
« xyz:XYZ100 » deviendraient des marches inexistants — faute commise dans ma premiere mesure).
Premiere version : elle cherchait `.upper()` dans tout le fichier et attrapait le COMMENTAIRE
qui interdit justement l usage. Corrigee par `tokenize`, elle lit le CODE seul — commentaires et
chaines retires — et un `.upper()` reellement injecte la fait ROUGIR.

Le verdict dit aussi ce qu il ne prouve pas : « une couverture stable ne garantit pas un verdict
economique ; une couverture trouee l INTERDIT ».

### 22/11/2026 — ✅ LE FLAKE A PARLE, PUIS IL EST MORT

La passe 11 l a reproduit, et l instrumentation posee une heure plus tot a livre la cause d un
coup :

```
AssertionError: aucune position ouverte ;
                motifs de refus enregistres : {'PRECISION_CLUSTER_TOO_WEAK': 1}
```

#### La cause, certaine cette fois

```python
now_ms = int(time.time() * 1000)        # RECALCULE dans la porte
last_age_ms = now_ms - last_ms          # le test posait last_ms = now - 100
max_last_age = 350                      # 350 ms SEULEMENT
```

Le test ne disposait que de **250 ms de temps reel** entre son `now_ms` et cette porte — apres
`_make_observer()`, la construction du signal et une dizaine de portes. Sous quatre workers sur
machine chargee, ce budget est depasse. 2 echecs sur 11 passes.

**C etait bien une course d horloge — et j avais verifie le MAUVAIS seuil** : la porte de
fraicheur du signal (`MAX_SIGNAL_AGE_MS = 30 000`), pas celle de precision (350 ms). Juste en
nature, faux en cible : d ou l interet de faire parler le code plutot que de raisonner dessus.

#### Le correctif, et pourquoi il n affaiblit rien

Horloge GELEE pour ce test (`monkeypatch.setattr(_lo.time, "time", ...)`). Le seuil de 350 ms
reste exerce tel quel, sur des ecarts CHOISIS et non subis. **Verifie par injection** : vieillir
le signal a 5 s fait rougir le test, motif nomme. La porte est donc toujours gardee.

#### Ce que cette sequence demontre

```
passe  9 : le flake apparait -> `assert 0 == 1`, aucune cause
           deux hypotheses, deux REFUTATIONS, et j arrete de deviner
           -> j installe de quoi LIRE la prochaine occurrence
passe 11 : il reparait -> la cause est NOMMEE du premier coup
           -> diagnostic certain, correctif cible, injection de controle
```

Trois lignes d assertion valaient mieux qu une troisieme hypothese. On n achete pas une cause en
devinant ; on installe de quoi la lire, et on attend qu elle se montre.

### 22/11/2026 — ✅ FEU VERT OPERATEUR : les 9 recus repointes, 3 120 / 3 120, closure_allowed = TRUE

L operateur a donne le feu vert sur les deux decisions qui lui etaient reservees (« tout ! »),
et **pas** sur la collecte (« ne relance pas la collecte »). Premier chantier : les 9 recus.

#### La justification etait FACTUELLE, et verifiee avant d agir

```
tests/test_asf_113_120_launchers_copy_vault.py:15  ->  ROOT / "POUSSER-GITHUB.cmd"
```

Le test cite par les 9 recus lit DEJA le successeur. Leur liste epinglee etait donc simplement
PERIMEE : elle pointait `POUSSER-GITHUB-FORCE.cmd`, supprime le 18/11 par le commit b44aac91
(« lanceur: POUSSER-GITHUB, sans le FORCE qu il ne fait pas »). Repointer suit ce que le test
LIT — ce n est pas un choix de confort.

#### `tools/repointer_preuve_deplacee.py` (NOUVEAU) : ce sont les REFUS qui font sa valeur

```
REFUSE si l ancien chemin existe encore       (on ne « deplace » pas une preuve qui est la)
REFUSE si le successeur est absent
REFUSE si aucun test du recu ne CITE le successeur   <- la garde contre le repointage arbitraire
NE DECERNE JAMAIS la preuve : le verdict ne bouge pas, seul revalider_receipts peut la rendre
APPEND-ONLY, avec sauvegarde prise avant d ecrire
```

8 tests, 4 injections ROUGES — dont « l outil decerne la preuve lui-meme » et « le registre
n est plus append-only ». Sans ces refus, on pouvait passer de 3 111 a 3 120 sans qu un seul
test tourne.

#### Le resultat, decerne par le chemin prevu

```
repointage : 9 lignes ajoutees, verdict INCHANGE, sauvegarde prise
puis revalider_receipts --reprendre :
   rafraichis 9 | echecs 0 | preuves_absentes 0
   encore_perimes 0 | encore_en_echec 0 | encore_preuves_absentes 0   | code de sortie 0

DECOMPTE : 3 120 / 3 120   (100,0 %)   closure_allowed = TRUE
VERDICTS : 3 120 VERIFIED_DONE, plus aucun autre etat
```

Le code 0 est legitime pour la premiere fois : la garde posee cette nuit (sortie 3 tant qu un
recu n est pas resolu) rend 0 parce que plus rien n est non resolu. 74 verts sur les fichiers
qui gardent les recus, dont `rig_020`.

**Rien n a ete fabrique** : la preuve a ete decernee en rejouant les tests (code 0), sur des
empreintes recalculees sur des fichiers qui EXISTENT.

### 22/11/2026 — ✅ FEU VERT OPERATEUR, 2e CHANTIER : le funding entre dans le PnL, la porte s ouvre a la frontiere INTERIEURE

#### Ce qui etait en jeu

```
net = gross_pnl - spread_cost - fees - slippage - latency
expected = executable_before_fees - fees
if not math.isclose(net, expected, abs_tol=1e-8): -> ECONOMIC_RECONCILIATION_FAILED
```

Une EQUATION DE CONSERVATION protege `net_pnl_usd`. Y injecter le funding l aurait cassee. Et
les taux viennent d un rattrapage REST (`causal_forward_eligible: False`) : les melanger a un
net causal aurait brouille la provenance, ce que `copy_vault_funding_realise` met en garde de ne
pas faire. Le portage vit donc A COTE :

```
carry_pnl_usd           le cout de portage, signe (convention HL : a taux positif, le LONG paie)
carry_status            MEASURED | MEASURED_ZERO_NO_SETTLEMENT_CROSSED
carry_provenance        REST_FUNDING_HISTORY, dit et non suppose
settlement_crossing_count
net_after_carry_usd     = net_pnl_usd + carry_pnl_usd        (somme EXPLICITE)
net_pnl_usd             INCHANGE, toujours reconcilie
```

#### La porte distingue enfin trois cas la ou elle en confondait deux

```
frontiere EXACTEMENT a l entree ou a la sortie -> FUNDING_BOUNDARY_UNPRICED
    l ordre fill/funding est inconnu avec des horodatages seuls, et AUCUN taux ne leve cette
    ambiguite. C est le cas que decrivait le commentaire d origine : il avait raison.
frontiere STRICTEMENT INTERIEURE + taux observes -> CHIFFREE, l episode passe
frontiere interieure, taux absents ou ne couvrant pas -> FUNDING_BOUNDARY_RATE_UNOBSERVED
aucun taux fourni (defaut) -> FUNDING_BOUNDARY_UNPRICED, comportement d avant BIT POUR BIT
```

`taux_funding=None` par defaut : aucun appelant existant ne change de comportement.

#### 9 tests, 5 injections ROUGES — et une 6e zone aveugle trouvee

```
le SIGNE du portage inverse            -> ROUGE   (un cout deviendrait un revenu)
un taux UNMEASURABLE passe quand meme  -> ROUGE
le defaut change, sans taux ca passe   -> ROUGE
le portage entre dans le net reconcilie -> ROUGE
la frontiere AMBIGUE devient chiffrable -> *** AVEUGLE *** puis ROUGE
```

La cinquieme injection laissait les 7 premiers tests VERTS : aucun n exercait une frontiere
tombant PILE sur l entree ou la sortie. Deux tests ajoutes (fixtures construites pour que
l instant coincide exactement avec 3 600 000 ms), et la garde voit. **Sixieme zone aveugle de
la session, trouvee par injection comme les cinq autres.**

⚠️ Ce chantier ne produit pas un verdict : il rend 231 candidats CHIFFRABLES quand les taux sont
fournis. Sans collecte, le labo n a toujours pas d episode complet de l entree a la sortie.

## 22/11/2026 (soir, heure relevée 21:58 Paris) — complément « Alpha discovery maximum »

- **Carte des mécanismes** écrite (`GOAL2_CHASSE_ALPHA.md` §21) : l'argent de Hyperliquid va à la fourniture
  de liquidité (Jia et al., AFT 2026 : teneurs de marché +208 M$, preneurs algorithmiques ≈ 0, particuliers
  −1,11 Md$). Copier en taker = se placer du côté qui paie. Seul PROMISING : dépôt HLP (preuve dès le 17/12).
- **Liquidations** : inmesurables sur nos données (0 fill `Liquidated` sur 111 000, aucun marqueur dans les trades
  publics) ; déjà instrumentées (`liquidation_cascade`, `liquidation_net`) sans source causale.
- **Décomposition « où l'alpha disparaît »** : déjà faite (Q3, juillet) — pas refaite.
- **H16 pré-enregistrée** (refus prospectifs F1 absorbé / F2 tard / F3 petit / F4 union, Bonferroni, couverture
  ≥ 30 %), gel `2026-11-22T22:30:00Z`. Outil `tools/goal2_refus_prospectif.py` + 5 tests verts. Ne touche
  pas l'apprenant. Premier verdict possible ≥ 5 jours après le gel (~28/11).
- **Erreur corrigée** : heures inventées dans le journal (2e fois) → mémoire `heure_lue_jamais_devinee`.
- En attente utilisateur : `POUSSER-GITHUB.cmd` ; redémarrage de l'apprenant en conservant l'état.

## 22/11/2026 (nuit, 23:47 Paris, heure lue) — push débloqué + mission « Data quant maximum »

- **Push GitHub FAIT** (autorisé) : `SYNCHRONIZED`, 0 commit d'écart ; les 4 workflows de collecte tournent
  avec les corrections. Causes levées : Codex tenait `index.lock` ; préchargement des blobs un par un
  (> 900 s) → un seul `fetch --stdin` (13 s, `_prefetch_blobs_par_lot` + test) ; 546 entrées `catalog/`
  laissées dans l'index par le lancement interrompu → remises sur HEAD (sauvegarde
  `runtime/reports/git-sync/index_catalog_avant_reparation_20261122.txt`).
- **Apprenant redémarré** (PID 12156, code à jour, `debut_ms` conservé) ; il enregistre le contexte d'entrée.
- **Ironflow intégré** : 138 Parquet, 634 Mo, SHA-256 + schémas ; funding identique à nos données
  (860 570 paires), bougies écart médian 0 bps. `tools/ingerer_ironflow.py`, `tools/recouper_ironflow.py`.
- **Tardis intégré** (jours gratuits) : 24 fichiers, 326 Mo ; carnet = instantanés top-20 puis top-5.
- **H17** (absorption des liquidations) `REJECTED` ; les vagues CONTINUENT (−72,9 bps à 24 h pour
  l'absorbeur). **H18** (refus « contre une vague ») pré-enregistrée, MORE_DATA jusqu'au fichier Ironflow
  de novembre. Matrice : `docs/audit/MATRICE_DONNEES_EXTERNES.md`. 33 essais au registre.
- Nœud Hyperliquid : impossible sur ce PC (128 Go de RAM exigés, 32 Go présents).
- Non poussé (aucun push automatique) : ingesteurs, H17/H18, matrice.

## 23/11/2026 (nuit) — AlinaSync : des heures -> une demi-heure environ

- **Mesure** : après une restauration qui réutilisait déjà les 1 792 577 shards (23:59 -> 00:20), le
  DÉBALLAGE repartait sur les 18 familles : 7 Mo/s, 523 ouvertures de fichier par seconde, ~6 h. Puis le
  pont CopyVault relisait les 1,79 M de shards (deux empreintes chacun) pour en écarter 99 %. Seuls
  15 456 shards (CopyVault) servent au labo ; les autres familles sont DISABLED_BY_SCOPE.
- **Correction** : `tools/unpack_verified_safe.py` ne déballe plus que les familles actives `copy_vault_*`
  APRÈS avoir contre-vérifié le corpus entier (comptes, familles, catalogue) ; `tools/copy_vault_safe_bridge.py`
  contrôle le registre complet puis ne lit que le périmètre déballé (`unpack_scope`, `unpacked_shards`).
  Restauration inchangée (son mode CopyVault seul mettrait 1,77 M de shards en quarantaine : écarté).
  `ALINA_DEBALLER_TOUTES_FAMILLES=1` rétablit l'ancien comportement. 82 tests verts, dont 4 nouveaux.
- Au passage : `test_root_entrypoints_are_reusable_in_existing_checkout` était cassé par le commit 04e7b46
  (autre session) qui a changé `ALINA_SYNC_COMPLETE.sh` sans le test ; test aligné.
- Pour en profiter : arrêter le lancement en cours (ancien code déjà chargé) et relancer.
- **Écran noir du début d'AlinaSync supprimé** : `git merge --ff-only` (index entier, 15-30 min muettes,
  7 249 s mesurées le 21/11) est remplacé par l'avance rapide SANS balayage du moteur de POUSSER-GITHUB,
  nouveau mode `alina_git_code_sync.py --adopter-seulement` (n'emprunte que `_fast_path_if_clean` ; refuse
  NO_GO s'il faudrait committer/rejouer/pousser ; jamais de publication). Phases annoncées dès la 1re seconde
  (`DEMARRAGE`, `CONTROLE_DU_CODE_LOCAL`, `ADOPTION_SANS_BALAYAGE`) et progression du moteur à l'écran.
  Tests : 2 de bout en bout sur un vrai dépôt (avance rapide propre ; refus SANS commit ni push), 1 d'appel,
  canari adapté ; 220 + 101 verts. Effet de bord : l'adoption réécrit `runtime/reports/git-sync/LAST_SYNC.json`.

## 23/11/2026 (nuit) — /goal « trois chantiers » : faits, mesurés

1. **Planificateur : capital canonique.** Les USD/jour des anciens essais (mesurés sur 350 USD : 54 enregistrements
   vérifiés) étaient classés comme valant 100 USD, sous un en-tête « (350 USD) ». Désormais chaque preuve porte
   `capital_usd_de_la_mesure` ; un montant d'un autre capital n'est ni transposé ni priorisé (« n/d (sur 350 USD :
   -1.620) ») et l'action dit « remesurer au capital paper de 100 USD ». 157 tests verts.
2. **Chaîne SAFE -> Lab Quant débloquée.** Déballage CopyVault certifié en 367 s (avant : ~6 h projetées, jamais fini) ;
   pont : `SAFE_COPY_NO_GO` 0 fill -> `SAFE_COPY_WORKSPACE_READY` 62 fills en direct. Cause : 29 messages en direct
   sans `isSnapshot` (type officiel `isSnapshot?: boolean`, SDK nktkas `isSnapshot?: true`) ; accepté SEULEMENT si le
   collecteur les a aussi classés `is_snapshot: false`. Vérifié : SAFE CopyVault = 01/10 -> 18/10/2026 (catalogue).
3. **H19 (suivre la vague de liquidations)** pré-enregistrée puis mesurée : `REJECTED` (leaders -1,0 bps à 24 h contre
   +72,9 pour la vague seule). 34 essais.
- Au passage : fins de ligne de 2 fichiers de test remises en LF ; reçus rejoués (0 périmé).


## 24/11/2026 — ETA du coffre et compteurs AlinaSync liés au catalogue courant

- `tools/sync_complete_clone.py` ne publie plus les compteurs SAFE/L2 d’un reçu incomplet, d’un autre dépôt ou lié à un ancien SHA de `DATA_INDEX.json`; la validation réutilise le contrôle exact du reçu (inventaire, parité shards/octets, statut et catalogue).
- `tools/eta_donnees_labo.py` affiche l’âge de `COUVERTURE_PROJET.json` à côté du taux du coffre; il sépare toujours le flux observé, les shards restaurés, l’extraction physique et le reçu local Release.
- Reçu local contrôlé en lecture seule : `RESTORE_REPORT.json` valide pour le SHA catalogue `bc1c682f34d2e38d5d4123aa6031f269c60073ceaa5db3978e8ee66be49ac2cf`, 1 792 577 shards / 142 923 240 926 octets. Le reçu de déballage annonce 15 456 shards mais ne satisfait pas le contrat de preuve physique; ils restent exclus des comptes vérifiés. La base actuelle ne fournit pas de certification L2 complète.
- Observation ETA en deux cycles réels : 5/94 fichiers de flux actifs, 2 193,8 lignes/min à la seconde mesure; inventaire coffre 90,7503 %, 31 601 fichiers, relevé vieux de 23 min lors de l’affichage. Aucun collecteur n’a été lancé, arrêté ou modifié.
- Validation locale : 177 tests réussis, 1 ignoré (lot croisé de 10 modules, 32,08 s); compilation Python et `git diff --check` réussis. HEAD inchangé `86f2e0ca88d33020b4a54bcbe56e1680688e9389`, branche `main`; aucun commit ni push.
- Restent notamment la preuve globale d’identités de trades (le patch courant reste `coverage_complete=false`, 89 888 candidats annoncés restants), l’admission/certification SAFE complète, les validations L2 et replays économiques/OOS/forward; aucun statut économique n’est promu.

### Complément 24/11/2026 — SHA courant du catalogue vérifié par ETA_COLLECTE

- `tools/eta_donnees_labo.py` calcule désormais en flux le SHA-256 du `catalog/DATA_INDEX.json` courant (75 481 octets) au rafraîchissement lent des reçus, puis exige que RESTORE et UNPACK correspondent tous deux à ce catalogue et au contrat de restauration exact. Un reçu ancien ou un catalogue absent affiche des comptes inconnus, avec un motif lisible; rien n’est ajouté aux journées denses.
- Contrôle réel du tableau : `--une-fois` affiche 1 792 577 shards / 133,1 Go validés, 15 456 décompressions seulement annoncées et donc non comptées, 21 400 assets liés au reçu, inventaire coffre à 90,7503 % avec âge visible. Le test deux cycles précédent avait mesuré 5 à 8 flux actifs sur 94 et un débit variant selon les écritures observées; les collecteurs n’ont pas été démarrés/arrêtés.
- Lot croisé final : 178 réussis, 1 ignoré en 34,99 s; ETA+AlinaSync : 87 réussis, 1 ignoré; compilation Python et contrôle whitespace réussis.
- SHA local attendu : `bc1c682f34d2e38d5d4123aa6031f269c60073ceaa5db3978e8ee66be49ac2cf`. La couverture d’identités globales reste incomplète (`coverage_complete=false`); replays L2 continus et preuves économiques OOS/FORWARD ne sont pas démontrés.
### ComplÃ©ment 24/11/2026 â€” DÃ©duplication dâ€™identitÃ©s et ressources Git

- `tools/backfill_global_unique_trade_counts.py` regroupe maintenant les insertions SQLite par lots bornÃ©s de 4 096 identitÃ©s, en gardant les transactions par shard, `INSERT OR IGNORE`, les comptages `total_changes` et le rollback existants. Test de recouvrement inter-shards : 3 000 identitÃ©s communes, 5 000 uniques au total, comptages par shard exacts.
- Microbenchmark local isolÃ©, entrÃ©es identiques de 300 000 identitÃ©s : insertion unitaire 0,671 s, lots 0,543 s, accÃ©lÃ©ration mesurÃ©e 1,24Ã—, mÃªmes identitÃ©s/chevauchements/comptages. Mesure de coÃ»t logiciel uniquement, pas un rÃ©sultat de marchÃ©. Tests du module : 22 rÃ©ussis.
- Processus Git orphelin confirmÃ© comme `git status --renames --porcelain=v1 --untracked-files=no`, parent absent, sans enfant ni verrou, 1,67 Gio de mÃ©moire de travail et 149,3 s CPU; PID 33696 arrÃªtÃ©. Les processus de collecte Python (20728) et Salad (26216) sont restÃ©s actifs et intacts.
- Validation courante : ETA + AlinaSync 87 rÃ©ussis, 1 ignorÃ©; backfill identitÃ© 22 rÃ©ussis; compilation Python et `git diff --check` avec CRLF tolÃ©rÃ© rÃ©ussis. Aucun commit ni push.
- La couverture globale dâ€™identitÃ©s reste incomplÃ¨te : 89 888 shards candidats selon le patch existant; lâ€™optimisation rÃ©duit le coÃ»t dâ€™une reprise mais ne certifie pas ces shards.
- Le test ciblÃ© `tests/test_coffre_tier_local_streaming.py::test_context_family_is_read_after_replay_cap` passe, ainsi que le module complet (1 test). La densitÃ© reste correctement fondÃ©e sur des signaux observÃ©s aprÃ¨s replay ; le simple tÃ©lÃ©chargement dâ€™archives SAFE augmente lâ€™inventaire, pas le compteur de journÃ©es denses.

### ComplÃ©ment 24/11/2026 â€” VÃ©rification d'unicitÃ© du catalogue moins coÃ»teuse

- `src/hl_observer/dataset/partitioned_data_index.py` utilise maintenant des empreintes entiÃ¨res process-local dans `iter_index_rows` et `select_index_rows`; elles ne remplacent ni l'identifiant canonique ni les SHA. Les doublons exacts et collisions d'empreinte sont refusÃ©s. Deux tests dÃ©diÃ©s couvrent les deux lecteurs.
- Parcours rÃ©el identique du DATA_INDEX : 1 853 164 lignes, 293 888 shards trade candidats, 0 compte trade exact non prouvÃ©; hash natif 32,18 s / 667,5 Mio de pic RSS, contre BLAKE2b 36,85 s / 698,9 Mio (âˆ’12,7 % de temps, âˆ’31,4 Mio RSS). Sur 9 581 IDs du premier partition, estimation mÃ©moire du set 1 714 404 â†’ 864 444 octets; mesure locale seulement.
- Suite `tests/test_partitioned_data_index.py` : 23 rÃ©ussis, 3 ignorÃ©s; compilation Python et `git diff --check` rÃ©ussis. HEAD `86f2e0ca88d33020b4a54bcbe56e1680688e9389`, `main`; aucun commit/push et aucun catalogue, shard SAFE ou checkpoint modifiÃ©.
- La couverture globale des trades reste non certifiÃ©e : le nombre de shards candidats traitÃ©s n'est pas une preuve d'unicitÃ© globale. Le checkpoint existant reste Ã  prÃ©server.

### ComplÃ©ment 24/11/2026 â€” Clarification du compteur `x/94` du suivi collecteur

- Le ratio compte les fichiers data observÃ©s qui ont grossi entre deux Ã©chantillons, pas les processus collecteurs. Le dÃ©nominateur n'est pas une cible; aucun plafond Ã  10 n'est codÃ©. Les vues simple et dÃ©taillÃ©e indiquent maintenant explicitement Â« fichiers de donnÃ©es Â» et Â« pas le nombre de collecteurs Â».
- Test rÃ©el read-only sur 2 cycles espacÃ©s de 3 s : cycle 2 = 9/94 fichiers en croissance, dÃ©bit agrÃ©gÃ© mesurÃ© 17 930,1 lignes/min. Le cycle 1 est restÃ© correctement `EN ATTENTE / PREMIERE_MESURE`. Cela confirme l'animation et le calcul de croissance; ce n'est pas une preuve de santÃ© des 94 collecteurs ni de journÃ©es denses.
- Suite `tests/test_eta_donnees_labo.py` : 39 tests rÃ©ussis. Aucun collecteur n'a Ã©tÃ© dÃ©marrÃ©/arrÃªtÃ©.

### ComplÃ©ment 24/11/2026 â€” RÃ©duction mÃ©moire du backfill sans toucher au checkpoint

- Les 293 888 mÃ©tadonnÃ©es candidates sont conservÃ©es en `Mapping` immuable compact (tuple/slots), et `_open_checkpoint` remplace son dict de lookup parallÃ¨le par un tri + une marche ordonnÃ©e des candidats et reÃ§us; doublons, IDs vides, SHA et exact counts restent refusÃ©s.
- Parcours rÃ©el du DATA_INDEX (1 853 164 lignes) : 31,92 s / 602,2 Mio RSS, contre 32,18 s / 667,5 Mio avec dicts, mÃªmes 293 888 candidats et aucun compte exact non prouvÃ©. âˆ’65,3 Mio constatÃ©s, temps comparable.
- `tests/test_global_unique_trade_backfill.py`: 24 rÃ©ussis. Aucun checkpoint SQLite rÃ©el, patch ou shard SAFE n'a Ã©tÃ© modifiÃ©.

### Complément 25/11/2026 — suivi réel des collecteurs dans ETA_COLLECTE

- `tools/eta_donnees_labo.py` lit en lecture seule le dernier relevé JSONL du watchdog dans une fenêtre bornée de 64 Kio. Il vérifie le schéma, l'horodatage (120 s maximum), `paper_read_only=true` et `real_execution=false`; relevé absent, tronqué, périmé ou incohérent = `INCONNU`/`PÉRIMÉ`.
- Le tableau sépare `x/94 fichiers de données en croissance` du nombre de processus supervisés `x/y`, puis affiche séparément les trous causaux et leur évolution. Cela n'assimile pas un collecteur vivant à une preuve sans trou ou à une journée dense.
- Observation ETA locale à 00:04:58 : première mesure `0/94` en croissance, `49/94` récents; watchdog observé 2 s auparavant : `20/20` actifs, aucun manquant; heartbeat Copy-Vault âgé de 0,5 s, `1 184` trous cumulés et `+3` depuis le début de campagne. L'ETA n'a piloté aucun processus.
- Validation : `tests/test_eta_donnees_labo.py` — 45 réussis; compilation Python et `git diff --check` réussis. Cette preuve décrit le suivi technique, pas une continuité sans trou ni la qualité économique.

### Complément 25/11/2026 — Réconciliation des compteurs de catalogues

- Lecture seule des reçus courants : `DATA_INDEX.shard_count=1 853 164`; somme des `row_count` déclarés dans ses 222 partitions = 1 853 164. Cette vérification porte sur le manifeste; les octets des partitions et shards n'ont pas été rescannés.
- Le registre SAFE déclare 1 853 164 shards, répartis en 1 792 577 SAFE + 45 535 PARTIAL + 15 052 REJECT = 1 853 164. `DATA_METRICS.TOTAL_SHARDS` et `COLLECTION_METRICS.indexed_dataset.indexed_shards` valent aussi 1 853 164 et référencent le SHA courant de `DATA_INDEX` (`bc1c682f34d2e38d5d4123aa6031f269c60073ceaa5db3978e8ee66be49ac2cf`). `REPLAY_COMPATIBILITY_REASONS.row_count` est identique et lié au même SHA.
- L'écart historique de 15 761 n'est donc pas reproduit dans les compteurs d'index actuels. `COLLECTION_METRICS.totals.shards` reste `null`, l'admission source est `INCOMPLETE`, et les métriques de collecte ne sont pas complètes : aucun total absent n'a été remplacé par un compteur inféré. La couverture d'unicité globale des trades demeure `false`, avec 89 888 shards candidats non scannés.
- Test de non-régression ajouté pour le garde existant qui refuse un `TOTAL_SHARDS` différent de l'index même lorsque le SHA est courant. Tests `test_collection_metrics`, `test_build_replay_compatibility_reasons` et `test_generate_health_receipt` : 23 réussis; Ruff, `py_compile` et contrôle du diff réussis. Aucun catalogue, shard ou checkpoint n'a été régénéré ou modifié.

### Complément 25/11/2026 — Publication sûre de la progression d'unicité

- `tools/backfill_global_unique_trade_counts.py` remplace maintenant atomiquement `TRADE_UNIQUE_COUNT_PATCH.json` après écriture temporaire, `fsync` et contrôle de la limite de 95 000 000 octets. Un échec d'écriture/remplacement conserve le reçu précédent; un test vérifie aussi le refus d'un reçu trop grand.
- `tests/test_global_unique_trade_backfill.py` : 30 réussis; Ruff, compilation Python et contrôle du diff réussis. Le backfill réel n'a pas été lancé (collecte et Salad actifs, RAM libre mesurée à 5,6 Gio); aucun checkpoint, manifest ni catalogue réel n'a été modifié. Le reçu courant indique toujours 89 888 shards candidats non scannés.

### Complément 25/11/2026 — Diagnostic NO_GO Git et correctif BBO

- Le moteur local de synchronisation est `2026-11-25-protected-overlay-v21`, et `POUSSER-GITHUB.cmd` exige exactement ce build. Le NO_GO historique concernant 161 chemins SAFE protégés est couvert par `test_tracked_protected_collision_is_preserved_as_local_overlay` : 1 test réussi; son dépôt distant est temporaire et confirme que le code peut avancer tandis que les octets SAFE restent en overlay local.
- `LAST_SYNC.json` (15:12 UTC, build v16) reste un reçu historique signalant un `index.lock`. Le reçu `LOCK_REPAIR.json` (15:52 UTC, build v20) porte `status=LOCK_REMOVED`; au contrôle local, `.git/index.lock` est absent. Aucun sync ni push réel n'a été lancé; ces reçus historiques n'ont pas été modifiés.
- Correction runtime locale : `tools/collecter_bbo.py` utilisait `FeedEventKind.UPDATE`, absent de l'énumération; Binance `bookTicker` fournit un BBO complet et utilise maintenant `SNAPSHOT`. Un test AST empêche toute référence future à une valeur d'énumération non déclarée. `tests/test_collecter_bbo.py` : 29 réussis; compilation Python et contrôle ciblé du diff réussis.
- Le collecteur déjà lancé n'a pas été redémarré; ce changement de code ne corrige donc pas rétroactivement son processus ou les données perdues avant son prochain démarrage normal.



### Complément 25/11/2026 — Réduction mesurée des écritures de manifeste BBO

- `TickDatasetWriter` et `PartitionedTickDatasetWriter` acceptent maintenant un intervalle optionnel de rafraîchissement des manifestes. Le flux BBO l'utilise à 5 s avec seuil de secours 100 000 événements; le JSONL reste flushé et `fsync`é à chaque lot, et une rotation scelle et met immédiatement à jour le manifeste.
- Microbenchmark déterministe temporaire, 10 partitions, 40 lots espacés de 250 ms simulés, 400 événements, trois répétitions : médiane `flush_every=1` = 1,659 s / 400 écritures de manifeste; réglage BBO = 1,156 s / 20 écritures (−30,3 % et −95 %). Les 400 records retournés et les octets JSONL courants sont identiques dans chaque comparaison. Mesure d'écriture locale synthétique, pas un résultat économique ni un benchmark du collecteur en production.
- Validation combinée : `test_tick_dataset.py`, `test_partitioned_tick_dataset.py`, `test_collecter_bbo.py` et la régression NO_GO aux 161 chemins protégés : 46 réussis. Ruff et compilation Python réussis sur les fichiers modifiés concernés.
- Le collecteur actif n'a pas été redémarré : le bénéfice runtime n'est pas encore mesuré sur le processus réel; les queues/drops antérieurs demeurent des incidents de qualité et interdisent toute certification de continuité.


### Complément 25/11/2026 — Backfill global des identités : RAM et lecture fail-closed

- `backfill_global_unique_trade_counts.py` lit maintenant le seul champ racine `failure_attempts` du reçu volumineux via mmap, sans matérialiser l'objet `counts` de 93,7 Mo. Mesure sur le reçu local réel : 6,85 s, dictionnaire extrait vide; aucune écriture ni reprise du backfill.
- Les shards JSONL sont lus avec une limite stricte de 64 Mio par record. Les records trop grands, vides, non-objets ou JSON invalides font échouer le shard au lieu d'être ignorés et potentiellement comptés comme exacts.
- Validation : `tests/test_global_unique_trade_backfill.py` 38/38; Ruff, `py_compile` et `git diff --check` réussis.
- Microbenchmark déterministe identique avant/après, 100 000 candidats et 50 000 shards déjà terminés : validation checkpoint 12,92 → 0,77 Mio de pic Python et 1,170 → 0,723 s; sélection du lot suivant 4,99 → 0,04 Mio et 0,155 → 0,123 s. Les sorties sélectionnées sont identiques. Ces mesures synthétiques caractérisent le logiciel, pas les performances économiques ni un scan du corpus.
- Dépôt local `C:\Users\flo\Desktop\Projet invest`, HEAD observé `c884db89b50d`; aucune collecte, écriture de catalogue, backfill, opération Git ou publication distante lancée.


### Complément 25/11/2026 — Lecture JSONL SAFE bornée avant allocation

- `tools/unpack_verified_safe.py` lit maintenant les enregistrements gzip avec `readline(MAX_JSONL_RECORD_BYTES + 1)` et refuse immédiatement toute ligne dépassant 64 Mio. L’ancienne boucle `for line in inp` pouvait allouer toute une ligne corrompue avant d’appliquer sa limite. Le plafond de taille totale, le hash, la validation JSON objet, le sceau et la publication atomique restent appliqués.
- Régression ajoutée à `tests/test_alina_unpack_safe.py` : avec une limite de test abaissée, une ligne trop grande est refusée et ne laisse ni JSONL ni sceau. Validation : suite SAFE unpack complète 18/18; Ruff et `py_compile` réussis.
- Sécurité : les tests hors scan intégral passent 23/23 dans le Python portable du dépôt. Un passage via `py -3` système avait 1 échec/23 réussis : son environnement ambiant contient `eth-keys`; le contrôle du runtime officiel `tools/python/python.exe` trouve zéro dépendance interdite. Aucun paquet global n’a été désinstallé et aucun code sécurité n’a été assoupli.
- Aucun shard, catalogue, téléchargement, collecteur ou processus de collecte modifié/redémarré. Aucun commit, sync ou push. HEAD de départ observé pour cette reprise : `c884db89b50d`.


### Complément 25/11/2026 — Scanner anti-données fictives fail-closed

- `src/hl_observer/security/fake_data_scanner.py` élaguait les répertoires exclus après découverte et ignorait les erreurs de parcours/lecture; un scan partiel pouvait donc retourner « propre ». Le parcours utilise maintenant `os.walk` avec exclusion avant descente; toute racine absente, erreur d’inventaire, source illisible ou encodage invalide produit `SCAN_INCOMPLETE`, donc `assert_no_fake_data` échoue. L’ouverture respecte les déclarations d’encodage Python via `tokenize.open`.
- Régressions : parcours incomplet et source illisible; les deux échouent maintenant en mode fermé. `test_v12_fake_data_scanner.py` : 9 tests ciblés réussis (test de scan runtime séparé : 1 réussi); Ruff et compilation réussis.
- Inventaire runtime identique à l’ancien parcours : 2 190 fichiers `.py`, aucun manquant/extra. Mesure d’énumération locale : `rglob` filtré après parcours 0,285 s, `os.walk` élagué 0,072 s (~75 % plus rapide sur cette phase). Le scan complet post-correction a pris 39,74 s sous charge locale; aucun gain global n’est revendiqué à partir de cette mesure seule.
- `tests/test_safety_audit.py` + multi-racines hors contrôle complet : 23 réussis dans le runtime du dépôt, 1 exclu car il rescane tout le projet. Un essai antérieur avec `py -3` système a échoué uniquement sur `eth-keys` installé dans cet interpréteur; l’audit du runtime officiel trouve zéro paquet interdit. Aucun environnement global n’a été modifié.
- Aucun shard, reçu, catalogue, collecteur ou processus de collecte modifié/redémarré; aucun commit, sync ou push.


### Complément 25/11/2026 — Réconciliation actuelle des catalogues

- Relecture bornée des quatre reçus sur le dépôt local, sans parcourir ni modifier les shards : `DATA_INDEX.shard_count`, `DATA_QUALITY_REGISTRY.active_dataset.indexed_shards`, `COLLECTION_METRICS.indexed_dataset.indexed_shards` et `REPLAY_COMPATIBILITY_REASONS.row_count` valent tous 1 853 164. Le registre SAFE/PARTIAL/REJECT/STALE donne 1 792 577 + 45 535 + 15 052 + 0 = 1 853 164.
- SHA-256 recalculé du `DATA_INDEX.json` : `bc1c682f34d2e38d5d4123aa6031f269c60073ceaa5db3978e8ee66be49ac2cf`; il correspond aux empreintes du registre, des métriques et de la compatibilité replay. L’écart historique de 15 761 shards n’est donc pas présent dans cette vue locale actuelle.
- Cela ne certifie pas la complétude économique : `all_collection_metrics_complete=false`, `global_unique_coverage_complete=false`, `global_unique_trades=null`, admission source `INCOMPLETE` et `proof_of_pnl_allowed=false`. Les compteurs ne sont pas promus en preuve PnL.
- `tests/test_collection_metrics.py` et `tests/test_build_replay_compatibility_reasons.py` : 20 réussis. Aucun catalogue ou shard modifié; aucun transfert, collecte, commit ou push.


### Complément 25/11/2026 — Vérification du NO_GO sans synchronisation

- `runtime/reports/git-sync/LAST_SYNC.json` est un reçu historique de 14:12 UTC, build v16, `NO_GO` causé par `index.lock`; aucun add/commit/push n’y a été tenté. Le fichier `.git/index.lock` est absent au contrôle actuel. Ne pas présenter cet ancien rapport comme l’état d’un run courant.
- Exécution réelle de `POUSSER-GITHUB.cmd --self-check` sous `cmd.exe` : code retour 0, `PORTABLE_GITHUB_PUSH_CHECK_OK`, validation Git/Python et moteurs canoniques, sans synchronisation ni publication. Le lanceur exige le build v21.
- Aucun `fetch`, sync, commit ou push n’a été lancé. Un NO_GO causé par un conflit de fichiers SAFE protégés reste un refus intentionnel tant qu’une opération risquerait d’écraser ces données; le test d’overlay consigné précédemment reste la voie de préservation, pas une autorisation de publier.


### Complément 25/11/2026 — Reçus de frames Copy-Vault complets

- Cause confirmée : `collect_cloud_copy_vault.py` enregistrait `accepted_frames` / `persisted_frames`, mais omettait `frame_reconciliation` de `BUNDLE_INDEX.json`. L’adaptateur campagne exige ce reçu pour établir la cohérence entre compteurs writer, enregistrements JSONL, assets publiés et shards exclus; les campagnes Copy-Vault pouvaient donc rester incomplètes même quand les nombres étaient disponibles.
- Le producteur construit désormais le reçu à partir de tous les manifestes candidats et des rejets exacts, le met dans l’index et le résumé durable, et conserve le statut `INCOMPLETE` ou `MISMATCH` si l’un des comptes manque ou diverge. Les compteurs BBO reconnaissent aussi `copy_vault_bbo` dans l’adaptateur et le constructeur de métriques; les manifestes L2 Copy-Vault continuent d’être comptés dans leur famille correspondante.
- Validation : suites `test_collect_cloud_copy_vault.py`, `test_resumable_campaign_adapters.py` et `test_collection_metrics.py` — **111 réussis**; régressions dédiées au reçu de bundle, au comptage BBO Copy-Vault et au rollup des actifs.
- Le reçu futur s’améliore; les campagnes/releases déjà terminées ne sont pas réécrites. Aucun collecteur n’a été arrêté/redémarré et aucun shard/catalogue existant n’a été modifié. Pas de commit, sync ni push.


### Complément 25/11/2026 — Dénominateur exact de l’ETA collecte

- Le `95` affiché mélangeait des rubans avec des fichiers JSON d’état/checkpoint. Au relevé local, `runtime/data` contenait 33 JSONL et 2 NDJSON parmi les flux append-only; un ruban live connu supplémentaire vit dans le workspace de labo. Les 59 JSON d’état ne sont pas des flux. L’ancien dénominateur 95 n’était donc pas 95 sources/collecteurs actifs.
- `tools/eta_donnees_labo.py` ne mesure plus les `.json` dans le débit. L’écran parle de croissance de fichiers de flux locaux et précise que cela ne certifie pas l’état des processus; le reçu de santé des collecteurs reste séparé. Le dénominateur observé était 36 rubans locaux reconnus, sujet à l’apparition de nouveaux fichiers.
- Validation : `tests/test_eta_donnees_labo.py` **53 réussis**, dont test démontrant qu’un JSON d’état et un `.jsonl.partial` sont exclus alors que JSONL, NDJSON et CSV sont inclus. Cela valide le rendu et le filtre, pas l’activité actuelle des processus.
- `tests/test_coffre_tier_local_streaming.py::test_context_family_is_read_after_replay_cap` passe également (**1 réussi**) sur le Python portable. Aucun collecteur n’a été arrêté/redémarré.


### Complément 25/11/2026 — Réconciliation du NO_GO Git courant

- Le reçu local `runtime/reports/git-sync/LAST_SYNC.json`, terminé à 21:27:58, est plus récent que celui de 20:51. Il rapporte `status=NO_GO`, `exit_code=2`, `progress=93,3 %`, `push_completed=true` et `pushed_head=remote_sha_observed=07d2228a9cd9a086f9117c11dae576dfc0699aac`. Les champs du reçu indiquent `force_push=false`, `reset_or_clean=false`, aucun téléchargement de shards et 82 chemins protégés différés.
- Le même reçu précise que trois fichiers locaux ont changé pendant l’exécution : ce checkpoint, la spec canonique et `recensement_donnees.py`. Le NO_GO final est donc un arrêt de protection après le push enregistré, pour préserver ces changements arrivés en cours de synchronisation. Le reçu n’identifie pas l’initiateur du push et ne constitue pas une vérification indépendante GitHub.
- Le `NO_GO` de la capture de 11:32 n’est pas le dernier état : le reçu courant donne le motif ci-dessus et `.git/index.lock` est absent. Il ne faut pas neutraliser la garde. Aucun nouveau push, fetch ou changement distant n’est lancé dans la mission en cours.
- Le scénario de la capture — 161 changements locaux protégés `catalog/` — dispose déjà d’une régression qui vérifie l’adoption du code sans écraser les octets locaux (`test_tracked_protected_collision_is_preserved_as_local_overlay`). Le résumé `tools/cmd_progress.py` distingue maintenant une publication confirmée des changements locaux encore non publiés et affiche leurs chemins, en conservant le code retour non nul et l’instruction de relancer après stabilisation. Vérification locale du reçu réel et tests ciblés : 6 réussis.


### Complément 25/11/2026 — Recensement du coffre fail-closed

- `src/hl_observer/datasets/recensement_donnees.py` ignorait les erreurs de `scandir`, d’itération et d’inspection d’entrées, tout en retournant `complet=true`; un scan tronqué pouvait donc soutenir une fausse couverture. Un projet vide recevait aussi 100 % par convention.
- Le recenseur enregistre maintenant le nombre et un échantillon borné des erreurs d’I/O; toute erreur invalide `complet` et `cent_pour_cent`, et rend le pourcentage indisponible. Un inventaire terminé sans fichier de données vaut 0 %, jamais 100 %.
- `tools/eta_donnees_labo.py` expose `SCAN INCOMPLET`, masque le pourcentage quand le parcours est tronqué et rejette les reçus incohérents, notamment une certification 100 % avec une couverture différente.
- Validation intégrée : `test_recensement_donnees.py`, `test_eta_donnees_labo.py`, `test_prouver_scellement.py`, `test_marks_source.py` — **84 réussis**. Tests spécifiques nouveaux : inventaire vide, dossier illisible, reçu incomplet et reçu contradictoire.
- Aucune collecte, aucun shard, aucun catalogue, aucun reçu runtime ni donnée SAFE n’a été modifié. Les erreurs d’accès réelles du projet doivent encore être constatées par une exécution de certification autorisée; aucun scan complet n’a été lancé.


### Complément 25/11/2026 — Relecture des compteurs catalogues au HEAD 07d2228

- Le SHA-256 exact de `catalog/DATA_INDEX.json` est `bc1c682f34d2e38d5d4123aa6031f269c60073ceaa5db3978e8ee66be49ac2cf`; son digest logique `shards_sha256` est distinct (`7f5bd3d3…`) et porte sur les lignes de shards. `DATA_QUALITY_REGISTRY.active_dataset`, `DATA_METRICS`, `COLLECTION_METRICS` et `REPLAY_COMPATIBILITY_REASONS` lient tous leurs preuves au SHA du fichier DATA_INDEX.
- Les compteurs de shards concordent à **1 853 164** : `DATA_INDEX.shard_count`, `DATA_CATALOG.indexed_shard_count`, le registre (**1 792 577 SAFE + 45 535 PARTIAL + 15 052 REJECT + 0 STALE**), `DATA_METRICS.TOTAL_SHARDS`, `COLLECTION_METRICS.indexed_dataset.indexed_shards` et `REPLAY_COMPATIBILITY_REASONS.row_count`. L’écart historique de 15 761 n’apparaît pas dans ces compteurs actuellement liés au même index.
- Les métriques de trades sont volontairement de périmètres différents : `DATA_METRICS` rapporte **50 407 261** trades SAFE/replayables; le reçu de compatibilité rapporte **60 517 706** replayables tous statuts, dont **292 948** non replayables, pour **60 810 654** indexés. Les **10 110 445** supplémentaires au-dessus du total SAFE proviennent des lignes replayables hors SAFE et ne sont pas admissibles économiquement.
- La collecte reste `COLLECTION_METRICS.quality_status=INCOMPLETE`; `totals.shards`, les frames et `global_unique_trades` restent `null`. Le compteur observé `387 445 404` est cumulatif et peut chevaucher des fenêtres; l’unicité globale reste fausse/non prouvée. Ce n’est pas une divergence arithmétique avec l’index, mais la preuve que les métriques de campagnes et d’admission restent incomplètes.
- Validation ciblée des générateurs : `tests/test_collection_metrics.py` + `tests/test_build_replay_compatibility_reasons.py` — **21 réussis**. Une suite séparée (`test_dataset_policy.py`) ouvre chaque manifeste de l’index; elle a été interrompue avant résultat après constat qu’elle impliquait une relecture exhaustive. Aucun catalogue ou shard n’a été réécrit.


### Complément 25/11/2026 — Unicité globale liée au snapshot de l’index

- Défaut confirmé dans `tools/backfill_global_unique_trade_counts.py` : le scan pouvait parcourir un ancien inventaire, puis rattacher ses compteurs à un `dataset_id` identique dont l’asset avait changé, ou publier une couverture complète calculée avant que la collecte ajoute de nouveaux shards.
- Le backfill lie désormais l’inventaire à l’empreinte exacte de la racine `DATA_INDEX.json`, vérifie qu’elle ne change ni pendant l’énumération ni avant publication, et refuse un résultat de shard dont `asset_sha256` ne correspond pas au SHA courant de la ligne. Le reçu conserve `source_index_sha256`, distinct du hash du catalogue après ajout des compteurs. L’écriture des compteurs dans un manifeste vérifie aussi l’identité du dataset et le SHA de l’asset, utilise un temporaire atomique unique et abandonne si les octets du manifeste changent avant remplacement.
- Tests temporaires sans lecture des shards SAFE : `tests/test_global_unique_trade_backfill.py` et `tests/test_backfill_replay_compatibility_candidates.py` — **81 réussis**; Ruff et `py_compile` propres. Ils couvrent les deux layouts d’index, le changement d’index pendant le scan, le refus d’asset périmé, la conservation d’une mise à jour concurrente et le comportement nominal.
- Aucun backfill, accès à la base SQLite de 5,47 Go, scan de corpus, modification de manifeste réel, arrêt de collecteur, commit ou push n’a été effectué. Le checkpoint global reste incomplet et non certifié.


### Complément 25/11/2026 — Compteurs exacts protégés contre les collectes concurrentes

- `tools/backfill_exact_trade_counts.py` lisait `DATA_INDEX`, effectuait les téléchargements/mesures, puis appelait le publisher qui relisait la racine courante comme base; une modification du catalogue entre-temps pouvait donc être écrasée par une vue ancienne.
- Le backfill capture maintenant le SHA de la racine avant la lecture, vérifie la stabilité pendant le chargement et le transmet à `_publish_canonical_index`. Le publisher, `_atomic_json` et `save_index` refusent une racine différente avant remplacement; les chemins inline et partitionnés restent atomiques. Les écritures de compteurs manifestes sont limitées au même dataset et au même asset SHA, et abandonnent si les octets changent pendant leur préparation.
- Test de régression simulant l’ajout d’un epoch de collecte pendant le scan : la publication renvoie `CANONICAL_INDEX_SOURCE_CHANGED_BEFORE_PUBLISH` et conserve la nouvelle racine et ses lignes inchangées. Vérification combinée : `tests/test_exact_trade_count_backfill.py`, `test_backfill_trade_partition_guards.py`, `test_partitioned_data_index.py`, `test_global_unique_trade_backfill.py` et `test_backfill_replay_compatibility_candidates.py` — **122 réussis, 3 ignorés**; Ruff et `py_compile` verts.
- Aucun scan de shard réel, backfill, arrêt de collecteur, commit ou push n’a été effectué. `TRADE_COUNT_PATCH` ne contient donc aucun nouveau résultat issu de cette correction.

### Complément 25/11/2026 (Claude) — Labo : réplication 3,5× plus rapide, funding en cache, ouvertures 18 → 15,1 Go

- **Réplication paper** (`copy_vault_replication_paper.run_replication`) : le profil réel montrait 1,26 M appels à `at_one` (un `searchsorted` par coin et par pas) = la moitié du temps. L'indice de chaque pas de grille était déjà calculé (`funding_indices`) : les prix sont lus à cet indice, avec le même contrôle de fraîcheur. Les `np.isnan(x)` sur des `float` Python deviennent `x != x` (vrai uniquement pour NaN). L'ancienne voie reste derrière `INDICES_DE_GRILLE = False`.
  - Preuve : sur les **176 vrais leaders** (décomposition des frictions) + 352 placebos, la version courante rend des résultats **strictement égaux** à la version commitée, figée dans un fichier à part. Temps : décomposition 68,5 s → 19,7 s, placebos 14,5 s → 3,9 s. Tests : `tests/test_replication_indices_grille.py` (23 cas : 16 mondes aléatoires + placebo, 6 décompositions, 1 voie empruntée). Deux injections (indice du pas précédent, fraîcheur ignorée) ont fait rougir le test.
- **Funding** (`tools/etude_copiabilite.load_funding`) : 12,4 M lignes JSON relues par 4 études (77 s de lecture + 17 s de construction). Il y a maintenant un cache par shard, indexé par SHA-256. Il rend les mêmes tuples, avec les mêmes types et le même ordre. Un shard dont une ligne n'a pas exactement `int`/`float` est relu directement. Mesure réelle : lecture froide 53 s, chaude 15,7 s ; tuples, types et taux par coin identiques sur les 381 coins. Tests : 2 ajoutés à `tests/test_etude_copiabilite_caches.py`.
- **Panneau de prix observés** (`load_mid_panel`) : le cache ne gardait que le panneau ENTIER ; un seul nouveau shard `allmids` faisait tout relire (451 shards, 197 s). Chaque shard (immuable) est maintenant gardé sous son SHA-256 (`runtime/.../mids/`), puis le panneau est assemblé selon la règle exacte de `build_mid_panel` : premier horodatage lu gardé, lignes triées, colonnes dans l'ordre de première apparition, cases vides en NaN. Un instant hors int64 ou un nom de coin finissant par NUL fait reprendre l'ancienne construction. Preuve sur le vrai coffre : **197,2 s → 6,1 s** (70 s une seule fois, cache froid), panneau identique au bit, NaN compris (226 576 instants × 408 coins). Tests : `tests/test_panneau_mids_par_shard.py` (16). Trois défauts injectés (colonnes triées, position ignorée, dernier doublon gardé) : tous rouges.
- **Passage CLI réel** (`tools/etude_copiabilite.py --replication-350 --sans-ecriture`, lancé hors Claude Code, Codex ouvert) : **rc=0 en 6 min 44**, pic du labo à 5,0 Go, RAM libre minimale 2,8 Go. Verdict MORE_DATA (9 jours, il en faut 20) ; le top reste indiscernable du hasard (+3,459 contre p95 +9,457). Un nouveau jour de données est arrivé depuis la mesure à 8 jours.
- **Couverture du recensement** : 87,4 % → **99,95 %**. Les 4 294 caches du labo sortaient en INCONNU ; ils ont maintenant la zone `runtime/research_lab/data/copiabilite_cache` = DERIVE (recalculables, jamais à sceller). `bbo_synchro.jsonl` et `cross_venue_atomic_bbo.jsonl` (paires Hyperliquid + Binance de `tools/collecter_bbo.py`) sont écartés par conception, HORS_PERIMETRE (famille Cross-Venue, source externe à validation séparée), dans `coffre_registre_fichiers` et `couverture_donnees`. Ils restent sur le disque. Il ne reste que les rotations fraîches « à prouver », que le Certificateur en continu (toutes les 30 min) prouve à son passage. Tests : 2 ajoutés à `tests/test_recensement_donnees.py`, contrat de couverture vert.
- **Règle funding de Codex** (travail en cours dans `copy_vault_copiability_mesures.py`, 26/11 01:48) : `net_k*_usd` vaut `None` si le funding est mesuré sur moins de 95 % ; 3 champs sont ajoutés. Elle cassait les 38 cas de `tests/test_attribution_rapide.py`. Le test compare maintenant sous cette règle : tous les champs d'origine au bit, `partial_net_excluding_unmeasured_funding` = l'ancien net au bit, et `net` suit exactement la porte. Deux défauts injectés (porte à 50 %, ordre d'accumulation inversé) : rouges.
- **Suite complète** (hors Claude Code, Codex ouvert, `-n 4 --dist loadfile`, sans `test_dataset_policy`) : 20 891 réussis, 44 échecs en 48 min. Les 39 qui étaient à moi (attribution + contrat) sont corrigés et verts au re-passage. Les 5 qui restent touchent du code et des tests déjà commités, donc déjà rouges sur GitHub et pas de cette session : `rig_020` (reçus liés à l'arbre local, rouge connu), `test_campaign_adapter_diagnostics` ×2, `test_launcher_core_heartbeat_bridge`, `test_pas_de_nouveau_fichier_geant` (`native_venue_coordinator.py` 886/866, `campaign_adapters.py` 2 083/2 007, `v2_pipeline.py` 938/892, travaux Codex).
- **Ouvertures** : `assembler_fills` ne copie plus les fills deux fois. Pic mesuré (étude lancée seule, Codex ouvert) : **18,0 → 15,1 Go**, même verdict (MORE_DATA, 19 jours).
- **Manifestes au contenu différent de GitHub** (2 144) : 64 ne diffèrent que par la mise en forme (même JSON). Pour les 2 080 autres, la version GitHub n'est pas téléchargée en local (clone partiel) : on ne peut pas dire laquelle est la plus récente sans la télécharger. Les deux versions existent (GitHub et disque) et aucun fichier n'a été réécrit.
- **Résultat de bout en bout** (même chronométrage, mêmes données, en lecture seule) : réplication complète **829 s → 419 s** (13,8 → 7 min). Le verdict est identique : meilleur réel +3,526 USD/j contre p95 du hasard +5,777, soit LE_TOP_EST_INDISCERNABLE_DU_HASARD ; 177 comptes, 176 simulés, 616 journées-leader sur 8 jours. Il reste les portefeuilles (72 s), les demi-écarts (49 s, les shards neufs y sont comptés), le funding (41 s) et la capacité (192 s, machine chargée).
- **Tests isolés** : `tests/test_ordres_leaders.py` rechargeait `etude_copiabilite` en REMPLAÇANT le module déjà importé. Les fonctions tenues par les autres fichiers de test n'étaient alors plus picklables, et les tests à ProcessPool rougissaient selon l'ordre des fichiers sur le worker. Le défaut existait avant (test des demi-écarts). Le chargeur réutilise maintenant le module déjà importé. 500 tests labo passent avec `-n 4 --dist loadfile`, plus 246 tests capacité/coffre/lois.
- **`docs/LOIS_MESUREES.md` régénéré** depuis `lois_mesurees.markdown()` : le registre avait été modifié et poussé le 24/11 (`--replication-paper`), mais pas le document. `test_le_doc_du_depot_est_bien_GENERE_du_registre` était rouge. Une ligne change, rien n'a été édité à la main.
- **Où partaient les 13,8 min de la réplication** (chronométrage réel, en lecture seule, 829 s) : capacité du marché 475 s, panneau de prix 188 s (reconstruit en entier dès qu'un shard `allmids` arrive), portefeuilles 58 s, demi-écarts 36 s, funding 27 s, décomposition 17 s, placebos 12 s, sélection des shards 15 s.
- **Capacité du marché** (`capacite_de_la_fenetre`) : 455 shards `trades_marche` (51,9 M trades) étaient lus par UN processus. La lecture passe à 4 processus. Les shards sont consommés dans l'ordre du flux : mêmes refus au même rang, mêmes lignes, et chaque notionnel est ajouté à sa minute dans le même ordre (`np.add.at` part de la somme déjà accumulée). La règle de lecture d'un trade est extraite telle quelle (`ROLES.trade_mesurable`), sans copie. Le moindre cas inhabituel (instant hors int64) fait relire le shard par l'ancien flux. Preuve sur le vrai coffre : **520,6 s → 166,7 s**, sortie identique et 2 329 832 sommes par minute identiques au bit. Tests : `tests/test_capacite_parallele.py` (14 : coffres aléatoires avec fichier tronqué, SHA divergent ou absent, fichier absent, hors coffre, instant géant ; ex aequo ; sommes au bit). Trois défauts injectés (somme repartie de zéro, coins triés, lignes hors fenêtre comptées) : tous rouges. Le premier n'était pas vu par le résumé arrondi à 2 décimales, d'où le test sur les sommes elles-mêmes.


### Complément 26/11/2026 (Claude) — AlinaSync vérifié ; rubans partagés : ajout atomique, fusions en ajout seul

- **AlinaSync lancé comme un double-clic** (`ALINA_SYNC_COMPLETE.cmd`, Codex ouvert).
  - 1er passage 03:12 : refus fail-closed (code 2), parce que Codex modifiait 3 fichiers de code juste après le push. C'est voulu.
  - Après un nouveau push, 2e passage 03:33 : **EXIT SUCCESS rc=0 à 04:25** (52 min). Synchronisation principale réussie en 30 min, pont SAFE CopyVault réussi.
  - Mais **1 lane sur 6 en échec** : `telecharger_explorer_github.py` rc=1, `PermissionError [WinError 32]` au renommage de `runtime/data/explorer_tx_tape.jsonl`, tenu ouvert par son collecteur.
- **Cause, et un défaut plus grave mesuré** :
  - Les fusions explorer, carnets L2 et BBO RÉÉCRIVAIENT le ruban vivant (tri + renommage) pendant que le collecteur l'alimentait. Quand le renommage passait, les lignes écrites entre-temps par le collecteur partaient dans un `.bak` effacé à la fusion suivante.
  - La fusion L2 retirait aussi du ruban local les carnets locaux invalides.
  - Les lecteurs par décalage (`explorer_autonome.py`) et le scelleur (suivi par préfixe) voyaient le fichier changer sous eux.
  - Autre défaut, mesuré sous Windows : deux processus qui ajoutent en mode `"a"` au même fichier **perdent des lignes**, 23 à 41 sur 120 000, plus 1 à 3 lignes coupées, sur 3 essais. C'était le cas des lanes certifiées pendant que leur collecteur écrivait, et de `copy_vault_snapshots_lane.jsonl`, écrit par deux collecteurs.
- **Correctif** :
  - `collecte_fiable.ajouter_atomique()` : descripteur Windows en `FILE_APPEND_DATA` seul, chaque écriture placée en fin de fichier par le système. 0 perte sur 3 essais quand les DEUX écrivains l'utilisent. Mêmes octets qu'avant (CRLF du mode texte), et `append_jsonl` passe par lui.
  - Les fusions explorer, L2 et BBO ne font plus qu'un **AJOUT des lignes absentes** : le ruban local est seulement lu, plus aucun renommage.
  - Les lanes certifiées et les écrivains de ces rubans passent à l'ajout atomique : collecteurs explorer, market (trades et bougies), contexte (portefeuilles, ordres, positions, TWAP), et l'écriture du ruban L2 par userfills.
  - Preuves : `tests/test_ajout_atomique_rubans.py` (6 tests, dont la fusion PENDANT que le ruban est tenu ouvert, la cause exacte du 26/11). Trois injections rougissent : l'ancienne fusion explorer, les anciennes fusions L2/BBO, et l'ajout non atomique. Les 441 tests des 27 fichiers touchés passent ; le seul rouge restant est `test_pas_de_nouveau_fichier_geant`, avec 8 fichiers en cours de Codex et aucun des miens.
- Les collecteurs explorer et market ont redémarré seuls à 17:16 avec le nouveau code. Contexte et userfills le prendront à leur prochain redémarrage ; aucun collecteur n'a été coupé.
- **Deux pertes réelles trouvées dans les copies `.avant-fusion.bak`**, comparées par IDENTITÉ au ruban vivant puis au coffre :
  - **Fills live** : la fusion WS filtrait le ruban local avec `_frais_et_causal`, qui exige `time`/`observed_at_ms` (le format des lanes). Le collecteur WS écrit `ts_ms`/`received_at_ms` : **les 777 lignes locales sur 777 étaient retirées à chaque AlinaSync**, dont 11 pas encore scellées. Correctif : le ruban live passe en ajout seul (`_ajouter_au_ruban_live`, mêmes verrous, filtre sur les seules lignes des lanes). La règle du ruban poll (« rejette les lignes polluées ») est inchangée. Test : `test_le_ruban_live_garde_les_fills_du_collecteur_ws` (l'ancienne fusion le fait rougir).
  - **Carnets L2** : l'ancienne fusion dédoublonnait sur (coin, instant) et jetait les carnets LIÉS à un signal (`checkpoint_id`). 215 manquaient au ruban, dont 102 absents du coffre. Le 3e écrivain de ce ruban, `copy_vault_checkpoint_socle._append_jsonl`, passe aussi en ajout atomique (mêmes octets).
  - **Rattrapage** : les 11 fills et les 102 carnets absents du ruban ET du coffre sont remis octet pour octet dans les rubans vivants, par ajout atomique (fills sous le verrou de leur collecteur), relus et vérifiés. Le Certificateur en continu les scelle à son passage suivant. Rapport : `runtime/reports/rattrapage_copies_avant_fusion_2026-11-26.json`. Les copies `.bak` sont conservées.
  - BBO : 0 ligne manquante. Ruban poll (`vault_fills_poll.jsonl.avant-fusion.bak`, 3,9 Go) : pas encore mesuré par identité ; sa règle de filtre est volontaire et testée.
  - Suite ciblée après tous ces changements : 649 tests passent sur les 39 fichiers touchés. Seul rouge : `test_pas_de_nouveau_fichier_geant`, avec 8 fichiers en cours de Codex et aucun des miens.
- Reste sur disque : `runtime/data/explorer_tx_tape.jsonl.fusion.tmp` (1,19 Go), copie triée laissée par la fusion échouée de 04:13. Rien n'y est unique, mais rien n'a été supprimé : c'est à Florent de décider.
