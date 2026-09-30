HYPERSMART - COPIE COMPLETE VERS UN AUTRE PC WINDOWS
====================================================

Le dossier HyperSmart est directement portable sur Windows 10/11 x64 une fois
extrait. Pour creer une copie de transfert fiable, utiliser exclusivement :

  CREER_ARCHIVE_PORTABLE.cmd

Le constructeur officiel arrete fail-closed si un writer reste vivant, copie les
bases SQLite par l'API Backup, neutralise les metadonnees propres a la machine,
verifie les chemins Windows puis revalide l'archive extraite.

AVANT DE COPIER OU D'ARCHIVER
1. Executer : LANCER_HYPERSMART.cmd stop
2. Attendre la confirmation d'arret.
3. Executer : CREER_ARCHIVE_PORTABLE.cmd
4. Utiliser uniquement l'archive finale declaree RELEASE_READY.

SUR LE NOUVEAU PC
1. Extraire le dossier dans un emplacement local de votre choix, avec un chemin court.
2. Executer : LANCER_HYPERSMART.cmd portable-check
3. Executer : ANALYSER_BACKTESTS_REPLAYS.cmd portable-smoke
4. Verifier PORTABLE_LAUNCHER_CHECK_OK et le smoke d'analyse.
5. Double-cliquer sur LANCER_HYPERSMART.cmd.

Le premier lancement apres changement de PC ou de chemin regenere seulement
l'identite et les verrous propres a l'ancienne machine. Les donnees, bases,
logs et historiques inclus par la politique de release sont conserves.

IMPORTANT
- Ne jamais copier directement une base SQLite pendant que le bot fonctionne.
- Ne jamais fabriquer la release avec WinRAR ou une copie brute du dossier vivant.
- Le PC cible doit etre Windows x64 et disposer de suffisamment d'espace.
- Internet est necessaire pour les donnees publiques Hyperliquid.
- Le runtime Python et Git utilises par HyperSmart sont embarques et relatifs au projet.
- Si Git embarque manque dans un clone source, lancer PREPARER_GIT_PORTABLE.cmd.

Securite : simulation locale/read-only, aucun ordre reel, aucune cle privee.
