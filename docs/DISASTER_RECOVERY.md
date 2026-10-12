# Alina Smart Flow — Disaster Recovery

## Politique en vigueur : zéro LFS, dépôt et branche uniques

Dépôt principal : `Rapt0r06300/hyperliquid-smart-wallet-observer`, branche
`main`. Git contient le bot, les modules, catalogues, manifests, receipts et
workflows suivis. Les actifs lourds sont des GitHub Releases du **même dépôt**.
Git ne copie pas les Releases lors d'un simple `git clone`. Aucun hook
implicite, réglage LFS ou dépôt supplémentaire ne résout cette limite.

La reconstruction complète est réalisée en **une commande composée de deux
étapes**, détaillée au début de `README.md` : clone Git, puis
`ALINA_SYNC_COMPLETE.cmd` (Windows)
ou `bash ALINA_SYNC_COMPLETE.sh` (Unix), pour un clone neuf comme pour
une synchronisation ultérieure. `GIT_LFS_SKIP_SMUDGE=1` exclut tout téléchargement LFS.
Python 3.10+, Git, assez d'espace disque et l'accès API GitHub sont requis.
Utiliser `gh auth login` ou un jeton avec lecture GitHub si l'API anonyme
est limitée, sans consigner ce secret dans les rapports.

## Synchronisation simple — dossier neuf ou dossier existant

**Dossier neuf, Windows CMD (une seule ligne) :**

```cmd
set "GIT_LFS_SKIP_SMUDGE=1" && git clone --branch main --single-branch https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer.git && cd hyperliquid-smart-wallet-observer && ALINA_SYNC_COMPLETE.cmd
```

**Dossier neuf, Linux/macOS (une seule ligne) :**

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone --branch main --single-branch https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer.git && cd hyperliquid-smart-wallet-observer && bash ALINA_SYNC_COMPLETE.sh
```

**Dossier existant déjà cloné du dépôt canonique :** lancer
`ALINA_SYNC_COMPLETE.cmd` (Windows CMD) ou `bash ALINA_SYNC_COMPLETE.sh`
(Linux/macOS) depuis la racine. Cela synchronise **les deux** couches dans
la même opération : les fichiers Git depuis `main`, puis le corpus
`replay-ready` du même dépôt. Celui-ci contient exactement les assets requis
par toutes les lignes `SAFE` + `replay_compatible` du catalogue courant.
Les données déjà vérifiées sont réutilisées et les téléchargements partiels
sont repris.

Sur un dossier ancien, le profil normal supprime du cache uniquement les
assets hors profil encore publiés dont la copie locale passe de nouveau les
contrôles taille + SHA-256. Les fichiers inconnus, partiels, corrompus ou
symboliques sont laissés intacts. Cette purge libère les anciennes capsules
locales sans effacer leur source distante récupérable par `--everything`.

Le synchroniseur existant `tools/sync_complete_clone.py` contrôle :
- racine Git, `origin` exact, branche `main` et arbre suivi propre ;
- `fetch` + `merge --ff-only`, sans reset/rebase/écrasement des changements ;
- restauration via le **seul** `tools/restore_alina.py`, sans Git LFS ;
- source vérifiée par taille/SHA-256, manifests et catalogue SAFE ;
- exclusion du corpus actif des capsules historiques et lignes PARTIAL/REJECT ;
- vrai code de sortie en échec si inventaire/source/catalogue non certifiables.

Options : `--preflight-only` inventorie sans télécharger ;
`--skip-update` évite le fetch après un clone déjà à jour ;
`--no-snapshot-materialization` est conservé pour compatibilité. Les snapshots
locaux appartiennent au profil d'archive explicite, pas au corpus replay.

Rapports locaux : `runtime/recovery/full/SYNC_REPORT.json` (HEAD du
code + résultat du restaurateur) et `RESTORE_REPORT.json` (preuves des
assets, volumes, manquants et quarantaines), ou
`RESTORE_PREFLIGHT.json` en préflight. `REPLAY_READY_COMPLETE` et exit 0
certifient 100 % du catalogue SAFE/replayable ; `RESTORE_COMPLETE` reste
réservé au mode d'archive intégrale `tools/restore_alina.py --everything`.
Une nouvelle exécution récupère les nouveaux
assets publiés pendant ou après la précédente synchronisation.
Le checkpoint de synchronisation ne déduit jamais ce statut du seul code
de sortie : il relit le rapport, vérifie le dépôt et le SHA-256 de
l'inventaire, puis reste `RESTORE_INCOMPLETE` si le certificat est absent,
invalide ou seulement `ASSETS_VERIFIED_ONLY`.

Aucun processus GitHub ne peut démarrer cette commande sur le PC ;
elle n'est exécutée que lorsque l'opérateur la lance. Aucun collecteur
cloud n'est arrêté, aucune donnée privée Dataset V2 n'est réimportée et
aucun ordre n'est exécuté.

## Inventaire exact et preuve d'identité des données

Le restaurateur énumère la fenêtre live via les pages `list releases` et leurs
inventaires d'assets documentés. Comme GitHub refuse les résultats au-delà des
1 000 Releases les plus récentes, le workflow GitHub-hosted
`publish-restore-inventory` publie toutes les six heures un
`RESTORE_INVENTORY.json.gz` couvrant l'historique complet. Cet inventaire est
lui-même contrôlé par taille et SHA-256 avant d'être fusionné avec la fenêtre
live ; son absence, sa corruption ou un conflit d'identité fait échouer la
restauration. Le fichier de contrôle vérifié est conservé dans le cache de
restauration et n'est pas retéléchargé lors d'une synchronisation identique.
Il vérifie ID, nom, tag, taille, état `uploaded`, SHA-256 puis la totalité
des octets téléchargés. Le profil normal conserve dans
`runtime/recovery/full/releases/` uniquement les conteneurs nécessaires au
catalogue SAFE courant. Le profil `--everything` conserve toutes les
collectes, capsules et preuves publiées.
Chaque ligne d'asset du rapport conserve aussi le dépôt source, l'identité
Release, les tailles annoncée/restaurée, les SHA-256 attendu/calculé, le
statut de vérification et la destination. Les totaux distinguent octets
publiés, restaurés/vérifiés, manquants, non vérifiables et matérialisés en
quarantaine, ainsi que les snapshots et fichiers reconstruits.

Chaque reprise est liée au SHA-256 déterministe de son inventaire initial ;
les collecteurs continuent et peuvent publier de nouveaux actifs pendant
l'opération, qui ne font pas partie de cette première preuve. Une nouvelle
synchronisation les récupère ensuite. Les fichiers Git suivis sont liés au
commit `main` cloné ; l'identité physique des packfiles `.git` n'est pas
l'identité des octets applicatifs.

Les shards ne deviennent `usable/` qu'après accord du catalogue SAFE courant
lié à son SHA-256, du SHA/taille du conteneur Release et du SHA/taille du
membre extrait. L'inventaire incomplet,
les erreurs de téléchargement, un ZIP ambigu, les pertes de données, une
qualification révoquée ou des SHA contradictoires échouent de façon fermée.

`--recover-verifiable` permet de sauver toutes les pièces de source
vérifiables même lorsqu'une ancienne archive est `starter`, sans empreinte
ou définitivement inaccessible ; ces défauts restent dans
`RESTORE_REPORT.json` et forcent `RESTORE_INCOMPLETE` / exit non nul.
Ne jamais interpréter un grand nombre de fichiers téléchargés comme un
succès à 100 %.

`--preflight-only --recover-verifiable` dresse l'inventaire des manques
et estime la capacité disque sans télécharger d'assets.
Les téléchargements utilisent un cache et reprennent les transferts partiels
lorsque les en-têtes HTTP sont cohérents ; un fichier n'est complet qu'après
contrôle SHA-256. Un `REPLAY_READY_COMPLETE` de code 0 prouve uniquement la
disponibilité du corpus de replay courant ; un `RESTORE_COMPLETE` prouve
l'archive intégrale publiée. Aucun des deux ne prouve la profitabilité.

## Fichiers locaux ignorés et preuve de disponibilité

Les fichiers de travail ignorés par Git ne sont pas dans un simple clone.
Leur récupération nécessite un snapshot `alina-local-snapshot-*` qui a été
réellement publié sur GitHub, avec index/chunks et SHA-256. Le drapeau
`--materialize-local-snapshot` fait échouer la restauration intégrale
si aucun snapshot vérifié n'est disponible. Un fichier jamais publié,
un artifact Actions expiré ou une donnée uniquement présente sur un PC
perdu est irrécupérable rétrospectivement : il faut le signaler.

Pour préparer une sauvegarde locale depuis un poste **sur demande explicite**,
utiliser `BACKUP_LOCAL_ALINA.cmd`. Cela ne déclenche aucune utilisation du PC
depuis GitHub et exclut les credentials, clés privées, `.env`, seeds et
artefacts dangereux.

La collecte GitHub-hosted publie d'abord les capsules
`alina-recovery-*` contenant le bundle et ses SHA-256. Les processus de
récupération peuvent reprendre les publications inachevées depuis cette
capsule exacte sans recollecter une autre fenêtre temporelle.

## Critères stricts de réussite

- clone des fichiers Git du HEAD canonique sur `main` ;
- 100 % des shards `SAFE` + `replay_compatible` du catalogue courant
  matérialisés et vérifiés pour le profil normal ;
- 100 % des assets publiés seulement pour le profil explicite `--everything` ;
- chaque asset a sa taille attendue et un SHA-256 source égal au SHA-256 local ;
- aucune archive `starter`, absente ou non vérifiable déguisée en succès ;
- preuves SAFE, manifests et catalogues concordants ;
- `RESTORE_REPORT.json` durable, statut correspondant au profil et code 0.

Si un point manque : récupérer au maximum mais **ne pas certifier 100 %**.
La collecte reste `COLLECT`, GitHub-hosted, paper/read-only, sans clés privées,
signatures, ordres réels, self-hosted runner ou dépendance au PC utilisateur.

## Git LFS : abandonné

Aucune duplication de données lourdes en LFS, aucun quota/achat LFS,
aucun lancement de migration LFS ni exigence `CLONE_COMPLETE` fondée sur
ses pointeurs. Les anciens manifests/scripts sont conservés uniquement si
nécessaires à la compatibilité et ne sont pas un chemin de récupération actif.
Un simple `git clone` sans étape d'hydratation des Releases n'est **pas**
une copie intégrale.
