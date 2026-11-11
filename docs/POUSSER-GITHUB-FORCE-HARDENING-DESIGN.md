# Design — Durcissement de `POUSSER-GITHUB-FORCE.cmd`

Date de mise à jour : 2026-11-11
Statut : implémenté et vérifié dans le checkout local ; aucune décision d'implémentation restante

## Intention

Faire de `POUSSER-GITHUB-FORCE.cmd` un lanceur de synchronisation de code
fiable, mesurable et récupérable sur le poste local, tout en conservant son
usage par double-clic. Le lanceur doit publier uniquement le code admissible
vers `main`, ne jamais forcer l’historique et ne jamais télécharger, supprimer
ou écraser les shards/data.

## État mesuré avant durcissement

- Le dépôt local contient environ 1 905 522 chemins suivis sous `datasets`.
- Le `git status` complet dépassait le budget de lecture de 30 secondes.
- L’inventaire borné actuellement corrigé prend environ 3 secondes sur ce
  checkout.
- Le contrôle portable du lanceur prend environ 1,5 seconde.
- La suite dédiée compte maintenant 102 tests ; la dernière exécution complète
  est verte (`102 passed`).

## Objectifs

1. Maintenir un inventaire borné sans perdre les garde-fous sur le code, les
   fichiers protégés ordinaires et les fichiers racine supprimés.
2. Rendre chaque étape mesurable : durée, budget, commande, SHA et résultat.
3. Empêcher les fuites de secrets dans les rapports et les erreurs Git.
4. Garantir qu’un timeout ne laisse pas de processus Git descendant actif.
5. Distinguer les erreurs transitoires retryables des erreurs d’authentification,
   de protection ou de configuration qui doivent arrêter immédiatement.
6. Vérifier le résultat réel du push par sortie structurée et SHA distant exact.
7. Fournir un mode de plan/préflight explicitement sans mutation.
8. Conserver un historique de receipts par exécution avec un dernier pointeur
   facilement lisible.
9. Garder le moteur hash-pinné et vérifier les capacités minimales de Git,
   Python et du dépôt avant mutation.
10. Ajouter une matrice de tests de panne couvrant les courses, verrous,
    timeouts, conflits, données protégées et remote avancé.
11. Réduire la latence sans sacrifier les preuves : mesurer séparément le
    temps local, réseau et mutation, puis supprimer les scans et appels Git
    redondants.

## Non-objectifs

- Aucun force-push, reset, clean, stash, suppression de données ou transfert de
  shards.
- Aucun changement du runtime PAPER / READ-ONLY / FAIL-CLOSED.
- Aucun nouveau service permanent, dépendance externe ou worktree.
- Aucun remplacement du moteur Python par une seconde architecture PowerShell.
- Aucun activation automatique de FSMonitor sans benchmark local démontrant un
  gain et sans stratégie de démarrage/arrêt vérifiable.

## Approches considérées

### A — Durcissement chirurgical, retenu

Conserver le CMD comme façade, renforcer le moteur Python existant, compléter
les receipts et étendre les tests. Cette voie minimise le changement de surface
et préserve le double-clic, le hash pinning et les protections existantes.

### B — Préflight puis push explicite

Séparer obligatoirement la préparation et la publication en deux commandes.
Cette voie augmente le contrôle humain mais dégrade l’usage quotidien demandé.

### C — Remplacement par un orchestrateur PowerShell/Python

Permettrait un reporting plus riche, mais introduirait une migration large et
une nouvelle surface de panne sans bénéfice nécessaire pour ce correctif.

## Conception retenue

### Lanceur CMD

- conserver la résolution portable de Git/Python et le hash SHA-256 du moteur ;
- propager explicitement chaque code de sortie ;
- afficher un identifiant d’exécution et les chemins des receipts ;
- refuser les options inconnues et les environnements incomplets ;
- ne jamais présenter un échec comme une synchronisation réussie.

### Moteur Python

- conserver l’inventaire borné des racines massives et les comparaisons ciblées
  de chemins protégés entrants ;
- mettre en cache les pathspecs et les invariants locaux pendant une exécution ;
- utiliser `--no-renames` pour les inventaires où la détection de renommage ne
  change pas la décision de sécurité, tout en conservant les contrôles ciblés
  nécessaires aux déplacements historiques ;
- éviter les appels Git redondants et réutiliser les SHA déjà prouvés dans le
  même run ;
- séparer les budgets de latence locale, réseau et mutation afin de ne pas
  ralentir un contrôle local à cause d’un timeout réseau ;
- benchmarker `core.untrackedCache`/FSMonitor en opt-in, sans modifier la
  configuration utilisateur si le gain n’est pas démontré ;
- ajouter des budgets par étape et un résumé de latence dans le receipt ;
- nettoyer et vérifier les arbres de processus Git après timeout ;
- redacter URL credentials, tokens et secrets avant affichage/écriture ;
- classer les push/fetch failures avant retry ;
- analyser `git push --porcelain` pour confirmer exactement la ref `main`, puis
  relire `ls-remote` et exiger l’égalité SHA ;
- rendre le mode dry-run/plan explicite et prouver l’absence de mutation ;
- écrire un receipt horodaté atomique en plus de `LAST_SYNC.json`, avec une
  rétention bornée et sans supprimer de données utilisateur ;
- vérifier les capacités minimales avant toute mutation ;
- enrichir les diagnostics sans faire fuiter le contenu des shards.
- isoler les hooks Git par processus pour que Git LFS ne transforme pas un
  checkpoint de code en transfert de données ou en attente cachée ;
- créer le checkpoint avec `write-tree`, `commit-tree` puis `update-ref` gardé
  par l'ancien SHA, afin d'éviter le rafraîchissement complet de l'index massif
  exécuté par `git commit` ;
- refuser explicitement un `index.lock` déjà présent et le signaler dans le
  receipt, sans le supprimer automatiquement ;
- autoriser les octets protégés locaux dans un checkpoint code-only/WIP tout en
  refusant un raccourci silencieux lorsque seuls des octets protégés sont
  modifiés et que GitHub est déjà aligné.

### Tests

Ajouter des tests déterministes pour :

- budget d’inventaire et racine `datasets` massive ;
- propagation d’options et de codes de sortie CMD ;
- timeout avec descendants résiduels ;
- redaction de credentials et tokens ;
- retry réseau contre arrêt immédiat auth/protection ;
- sortie push structurée et SHA final ;
- plan sans add/commit/fetch/merge/push ;
- receipt atomique, run id et rétention ;
- capabilities mismatch ;
- remote avancé, éditeur concurrent, conflit et données protégées.

## Critères d’acceptation quantitatifs

- inventaire standard de ce checkout : inférieur à 10 secondes ;
- objectif cible après optimisation : inférieur à 5 secondes à froid et
  inférieur à 2 secondes à chaud pour l’inventaire local hors réseau, mesuré
  sur au moins 5 répétitions après une répétition d’échauffement ;
- aucune étape locale ne doit attendre un budget réseau ; les budgets et les
  p50/p95 de chaque classe doivent apparaître dans le receipt ;
- au moins 20 % de réduction du nombre d’appels Git sur le chemin propre,
  mesurée avant/après sur le même checkout ;
- aucun timeout sur l’inventaire borné à cause de `datasets` ;
- `--portable-self-check` : inférieur à 5 secondes ;
- aucun processus Git descendant après un timeout dans le test Windows dédié ;
- zéro credential détectable dans les receipts de tests négatifs ;
- zéro retry pour une erreur d’authentification ou de protection ;
- un push déclaré réussi seulement si le SHA GitHub final égale le SHA local ;
- aucun appel `push --force`, `reset`, `clean`, `stash` ou téléchargement de
  shard dans le journal de commandes ;
- suite dédiée et nouveaux tests tous verts ;
- aucun fichier utilisateur non lié à cette note ou au moteur touché.

## Risques et réponses

- Un cache Git ou FSMonitor peut être indisponible ou froid : il reste
  optionnel ; l’inventaire borné reste le chemin déterministe.
- GitHub peut avancer pendant le push : la boucle de race reste bornée et
  repose sur le rejet non-fast-forward puis une nouvelle preuve distante.
- Un fichier protégé massif peut changer localement sans être rescanné : il ne
  devient jamais candidat au commit, et tout chemin protégé nommé par le diff
  distant est vérifié ciblément avant merge.
- Un rapport peut échouer à s’écrire : l’échec du reporting ne doit jamais
  transformer une opération Git échouée en succès.

## Décision clôturée

L’approche A a été retenue et implémentée. Les critères restent des contrôles
de non-régression : une mesure non atteinte reste explicitement documentée et
ne peut pas être transformée en succès.

## Extension opérateur validée le 2026-11-04

La livraison doit aller jusqu’à **20 correctifs robustes et vérifiés**, en
regroupant les améliorations par performance, sécurité, processus, receipts,
push, diagnostic et tests. La validation finale doit exécuter plusieurs fois
le CMD dans ses modes de contrôle, simulation et synchronisation contrôlée,
avec comparaison des SHA et inspection des receipts après chaque run.

## Résultats mesurés de l'implémentation

- Inventaire réel via `python tools/benchmark_git_sync.py --root . --runs 5`,
  en lecture seule : `mutations=[]` et résultats JSON conservant p50/p95 et le
  nombre d'appels Git. Le CMD ne prétend pas exposer une option `--benchmark`.
- Comparaison avec le baseline de la même session : p50 `3,03 s`, p95
  `3,19 s`, trois appels Git ; la fusion de l'inventaire staged/worktree
  apporte donc environ `33 %` de réduction d'appels et `11–12 %` de latence
  mesurée. Le seuil standard `<10 s` et le p95 cible `<5 s` sont atteints ;
  l'objectif ambitieux `<2 s` à chaud reste explicitement non atteint sur ce
  checkout et n'est pas présenté comme une réussite.
- Trois exécutions réelles de `--portable-self-check` ont renvoyé `0` avec
  `PORTABLE_GITHUB_PUSH_CHECK_OK`.
- Le dry-run du moteur et le benchmark restent sans mutation ; les tests de
  synchronisation refusent les modifications protégées ou concurrentes avec
  `NO_GO`, `mutations=0` et receipt horodaté.
- Une synchronisation normale a créé le checkpoint local par la voie plomberie
  en environ `3,1 s` pour 218 chemins admissibles, puis a renvoyé `NO_GO` code
  `2` sans push : `docs/CODEX_GOAL_OBJECTIVE_V31.txt` diverge entre le local et
  GitHub et n'est pas résolvable automatiquement sans choix de contenu. Les
  changements `catalog/...` sont restés hors du commit.
- Dernière exécution contrôlée : `NO_GO` code `2` après l'arrivée de deux
  modifications de code pendant le run (`src/hl_observer/simulation/economic_proof_controls.py`
  et `tests/test_hvr_0861_0880_copy_vault.py`). Le moteur a conservé ces octets,
  n'a effectué aucun push et a écrit le reçu `LAST_SYNC.json` ; cet état externe
  reste à réconcilier avant toute publication.
- Le précédent `git commit` a été reproduit jusqu'au timeout de `301,5 s` avec
  un `index.lock`; après isolation des hooks, le rafraîchissement d'index
  restait le goulot. `write-tree` a été mesuré à environ `2,8 s`, puis le
  checkpoint plomberie complet a terminé en quelques secondes sans hook LFS.
- Le dernier benchmark réel du CMD : 5 runs, p50 `2,672 s`, p95 `3,029 s`,
  exactement 2 commandes Git par run et `mutations=[]`. Le dernier
  `--portable-self-check` a renvoyé `0`.
- Les receipts sont écrits atomiquement dans `LAST_SYNC.json` et
  `history/RUN-<run_id>.json`, avec rétention bornée à 20 fichiers générés.
- La suite complète finale vérifiée est verte : `102 passed in 167.50s`.
