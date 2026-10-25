# Alina Smart Flow — synchronisation Git bidirectionnelle du code

## Contrat de sécurité

`POUSSER-GITHUB-FORCE.cmd` conserve son nom historique pour les raccourcis
Windows, mais **n'utilise jamais `git push --force`**. C'est un bouton de
synchronisation de **code uniquement**, sans téléchargement de shards.
**AlinaSync** reste seul responsable des shards SAFE et de leur décompression.

Le point unique de vérité reste
`Rapt0r06300/hyperliquid-smart-wallet-observer`, branche `main`.
Le point d'entrée principal appelle `tools/alina_git_code_sync.py`.
`tools/push_github_safe.ps1` est un simple relais de compatibilité vers
**le même moteur** (aucune seconde logique de fusion).

## Un double-clic standard

1. Vérifie le dépôt, la branche `main`, l'URL exacte du remote `origin`,
   l'absence de merge/rebase déjà en cours et la disponibilité de Git/Python.
2. Inventorie le code modifié, créé et supprimé, y compris les fichiers
   non suivis. Exclut par principe `runtime/`, `data/`, `datasets/`,
   `logs/`, les archives et les secrets. Ne parcourt pas le corpus SAFE.
3. Vérifie les chemins publiables, les tailles et les clés privées.
   **Seuls les chemins publiables** sont ajoutés à l'index.
4. Crée un commit réel si le contenu de l'index a changé, même si le
   travail local n'a pas encore été terminé. Aucun commit vide.
   Le dernier commit local est conservé dans
   `refs/alina-sync/last-local-checkpoint` pour retrouver facilement
   son SHA sans créer de branche parallèle.
5. Avant de publier, refuse tout Python local syntaxiquement incomplet.
   Le commit WIP reste **local**. Ce contrôle n'est **pas** une preuve
   qu'un code compilable passe les tests fonctionnels.
6. Récupère `origin/main` via `git fetch` (Git seulement), puis
   intègre ses commits par fast-forward ou fusion Git standard.
   Les conflits non résolus automatiquement sont annulés par
   `git merge --abort`. Les deux historiques restent accessibles.
7. Pousse **sans force** uniquement `HEAD:refs/heads/main`. Si GitHub
   avance pendant le push, réessaie la réconciliation au maximum
   cinq fois. Un refus d'authentification ou de branche protégée
   est traité comme un échec, jamais contourné.
8. Confirme le SHA distant par `git ls-remote` et le SHA local.
   Écrit un rapport `runtime/reports/git-sync/LAST_SYNC.json`.

Le script n'exécute **jamais** `reset --hard`, `git clean`,
`git stash`, `--force`, ni de suppression des verrous internes
`.git/index.lock`. Son verrou d'exclusion mutuelle est libéré par
le système d'exploitation à la fin de son processus.

## Modes

```cmd
POUSSER-GITHUB-FORCE.cmd
POUSSER-GITHUB-FORCE.cmd --dry-run
POUSSER-GITHUB-FORCE.cmd --wip-only
POUSSER-GITHUB-FORCE.cmd --portable-self-check
```

- **Normal** : checkpoint local, réception de GitHub, fusion prudente et
  publication avec vérification SHA.
- **Dry-run** : vérifie l'inventaire et la référence distante. Ne lance
  aucun add, commit, fetch, merge ou push. Le rapport local reste créé.
- **WIP-only** : sauvegarde le travail local en commit sans fetch,
  merge ou push. Adapté aux modifications inachevées.
- **Self-check** : vérifie que le lanceur, Git et Python sont disponibles
  sans modifier le dépôt ni contacter GitHub.

## Situations bloquantes et reprise

- **Fichiers exclus déjà indexés ou modifications locales de données Git
  suivies** : aucun merge ni push ; conserver les fichiers et régler
  leur traitement séparément. Le programme n'efface pas l'index.
- **Conflit entre Codex/Claude et GitHub** : pas de choix arbitraire
  « local gagne » / « distant gagne ». Les commits locaux sont
  préservés et le merge annulé ; résoudre les différences
  puis relancer le bouton.
- **Code Python local incomplet** : le commit WIP existe localement ;
  le push est refusé pour ne pas publier une erreur syntaxique.
- **Authentification GitHub ou hooks** : message d'échec explicite ;
  aucune réécriture des refs distante.
- **Deux synchronisations simultanées** : mutex du processus,
  deuxième synchronisation refusée proprement.
- **Shards SAFE ignorés** : laissés en place. Si GitHub voudrait écrire
  sur un chemin exclu non suivi présent localement, la fusion est
  bloquée avant toute écriture.

L'exécution peut toujours échouer à cause d'un conflit sémantique, d'un
processus externe qui édite les fichiers pendant la synchronisation, de
restrictions GitHub ou du réseau. « Aucun octet perdu » ne peut pas être
promis face à une panne disque ou à des changements externes, mais ce
lanceur ne supprime volontairement ni les données locales ni des commits
distants. Le rapport et les SHA permettent de reprendre après un échec.

Les tests de sécurité utilisent uniquement des dépôts Git **temporaires**
sous GitHub-hosted Linux et Windows, jamais les shards ou ton PC.
