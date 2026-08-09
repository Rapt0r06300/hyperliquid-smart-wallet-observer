HYPERSMART - COPIE COMPLETE VERS UN AUTRE PC WINDOWS
====================================================

Le dossier Projet invest est directement portable sur Windows 10/11 x64.
Aucun ZIP special n'est necessaire.

AVANT DE COPIER OU D'ARCHIVER
1. Executer : LANCER_HYPERSMART.cmd stop
2. Attendre la confirmation d'arret.
3. Copier ensuite l'integralite du dossier, fichiers caches compris.

SUR LE NOUVEAU PC
1. Coller ou extraire le dossier dans C:\HyperSmart (recommande).
2. Executer : LANCER_HYPERSMART.cmd portable-check
3. Executer : ANALYSER_BACKTESTS_REPLAYS.cmd portable-smoke
4. Verifier PORTABLE_LAUNCHER_CHECK_OK et le smoke d'analyse.
5. Double-cliquer sur LANCER_HYPERSMART.cmd.

Le premier lancement apres changement de PC ou de chemin regenere seulement
l'identite et les verrous propres a l'ancienne machine. Les donnees, bases,
logs et historiques sont conserves.

IMPORTANT
- Ne jamais copier une base SQLite pendant que le bot fonctionne.
- Inclure tools\python, tools\git, runtime, data, logs et .git dans la sauvegarde complete.
- Le PC cible doit etre Windows x64 et disposer de suffisamment d'espace.
- Internet est necessaire pour les donnees publiques Hyperliquid.
- POUSSER-GITHUB-FORCE.cmd utilise Git embarque et peut etre verifie avec --dry-run.
- Si tools\git manque dans un clone source, lancer PREPARER_GIT_PORTABLE.cmd.

Securite : simulation locale/read-only, aucun ordre reel, aucune cle privee.
