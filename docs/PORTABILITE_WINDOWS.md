# Portabilite Windows de HyperSmart

## Principe

Le dossier `Projet invest` complet est l'unite de sauvegarde et de transport.
Il peut etre copie-colle tel quel, place sur un disque externe, ou archive avec
l'outil choisi par l'utilisateur. Aucun ZIP special n'est necessaire.

La cible supportee est **Windows 10/11 x64**. Le dossier contient son propre
CPython dans `tools/python`, MinGit dans `tools/git`, les dependances, le code,
les donnees, les journaux et l'historique. Les lanceurs ne dependent ni d'un
Python ni d'un Git installes sur le PC.

## Procedure sure

1. Dans une invite de commandes ouverte dans le projet, executer :

   ```bat
   LANCER_HYPERSMART.cmd stop
   ```

2. Verifier qu'HyperSmart, ses collecteurs et son dashboard sont arretes.
3. Copier **tout** le dossier, y compris les fichiers caches et les sous-dossiers
   `tools/python`, `tools/git`, `runtime`, `data`, `logs` et `.git`.
4. Sur le PC cible Windows x64, placer le dossier dans un chemin court et
   inscriptible, par exemple `C:\HyperSmart` ou `D:\HyperSmart`.
5. Executer `LANCER_HYPERSMART.cmd portable-check`.
6. Double-cliquer sur `LANCER_HYPERSMART.cmd`.

Une connexion Internet reste necessaire pour lire les flux publics Hyperliquid.

## Pourquoi l'arret est obligatoire

SQLite et certains JSONL peuvent etre en cours d'ecriture. Une copie ou une
archive prise pendant le fonctionnement peut contenir des fichiers de moments
differents. Le dossier serait complet mais son etat runtime pourrait etre
incoherent. L'arret propre ferme les ecritures avant le copier-coller.

Ce point vaut aussi pour le clic droit `Ajouter a l'archive` : cette operation
est compatible, mais elle doit etre lancee apres l'arret du bot.

## Relocalisation automatique

Au premier lancement sur un autre PC ou depuis un autre chemin, le preflight :

- detecte le changement sans enregistrer le nom du PC ni le chemin en clair ;
- regenere une identite machine locale ;
- retire seulement les PID, marqueurs de session et verrous lies a l'ancien PC ;
- preserve le code, les donnees, les bases, les logs et les sessions terminees.

Sur le meme PC et au meme chemin, le preflight est non destructif. Il ne purge
plus les caches Python ni les fichiers d'etat a chaque lancement.

## Verification

```bat
LANCER_HYPERSMART.cmd portable-check
```

Cette commande verifie :

- le Python embarque et ses imports ;
- le Git embarque, le lanceur d'analyse et le bouton de synchronisation GitHub ;
- l'absence de dependance a un chemin utilisateur absolu ;
- les chemins Python relatifs ;
- la presence des fichiers necessaires au lancement ;
- l'ecriture dans le dossier cible ;
- le mecanisme de premiere relocalisation.

Le resultat attendu se termine par `PORTABLE_LAUNCHER_CHECK_OK`.

Verifier aussi l'analyse locale sans lancer un calcul long :

```bat
ANALYSER_BACKTESTS_REPLAYS.cmd portable-smoke
```

Verifier la synchronisation Git sans pousser :

```bat
POUSSER-GITHUB-FORCE.cmd --dry-run
```

Le bouton Git utilise `tools\git\cmd\git.exe`, travaille seulement sur `main`,
recupere la reference nommee `origin/main` et n'utilise ni `--force`, ni reset,
ni `FETCH_HEAD` comme branche. Les changements vivants sous `runtime`, `logs`
et `data` restent sur le PC ; tout changement de code non committe bloque le
push pour eviter un oubli. Si `tools/git` manque dans un clone GitHub minimal,
executer `PREPARER_GIT_PORTABLE.cmd` une fois.

## Runtime principal

Le launcher principal utilise le profil HARVEST Hyperliquid. dYdX reste un
connecteur legacy/research disponible pour des tests explicites, mais il est
dormant par defaut et n'est pas lance par `LANCER_HYPERSMART.cmd`.

## Outils optionnels

Les commandes `portable-install` et `portable-build` restent disponibles pour
la maintenance ou une distribution applicative sans historique. Elles ne sont
pas requises pour la sauvegarde complete du dossier.

## Limites honnetes

- cible actuelle : Windows 10/11 x64 ;
- la copie complete peut depasser 160 Go ;
- l'espace libre du PC cible doit etre suffisant ;
- une copie effectuee pendant des ecritures actives n'est pas garantie ;
- les pare-feu et antivirus du PC cible peuvent demander une autorisation pour
  Python, Git et les connexions sortantes publiques ;
- l'historique Git n'est portable que si le dossier cache `.git` est inclus.

**Securite : 0 ordre reel · 0 argent reel · 0 cle privee · 0 signature · 0 depot/retrait.**
