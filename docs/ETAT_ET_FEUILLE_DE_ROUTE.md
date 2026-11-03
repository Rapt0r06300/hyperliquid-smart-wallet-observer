# Alina SmartFlow — État & feuille de route

> **Source de vérité actuelle : [`docs/CURRENT_STATE.md`](CURRENT_STATE.md).**
>
> L'ancien contenu de ce fichier, daté de juillet 2026, était devenu contradictoire avec le code, les 775 optimisations scellées, le scope V2 et les campagnes économiques ajoutées depuis. Il reste intégralement disponible dans l'historique Git antérieur à cette mise à jour, mais ne doit plus être utilisé comme état courant.

## Feuille de route d'exécution mise à jour (3 novembre 2026)

La feuille de route d'audit et de correction la plus récente est :
[`docs/superpowers/plans/2026-11-02-alina-audit-roadmap-190.md`](superpowers/plans/2026-11-02-alina-audit-roadmap-190.md).
La feuille de route compte désormais **722 tâches distinctes** : 150 ASF-001..ASF-150, 72 constats AUD-001..AUD-072, 200 actions économiques ECO-001..ECO-200 et **300 nouvelles tâches LCH-001..LCH-300** consacrées à l'audit intégral du lanceur officiel `LANCER_HYPERSMART.cmd`, à son orchestration PowerShell/Python, aux branchements des collecteurs, Copy-Vault, à la sécurité PAPER, au ledger, aux replays, à la recherche et à la validation Windows GitHub-hosted. Les 300 tâches LCH restent à tester/implémenter; elles ne sont pas 300 bugs prouvés. Le triage P0/P1 et ses références de code sont dans la feuille de route. **Mandat Codex intégré au début du document : exécuter les 722 ID de bout en bout, avec modifications du code réel, branchements, corrections, tests déterministes et CI Windows GitHub-hosted, puis vérifier chaque résultat ; un audit ou une proposition ne clôture aucune tâche.** **Fiches Codex enrichies** : chaque ID dispose d'une case GitHub, d'un nom, d'une priorité, de points d'entrée vérifiés dans le dépôt, d'un correctif attendu et d'un reçu de clôture. Le calculateur `python tools/roadmap_722_progress.py` fournit les % déterministes, les compteurs par préfixe et un contrôle fail-closed des cases. Le mode objectif `docs/CODEX_GOAL_OBJECTIVE_V31.txt` et `AGENTS.md` ordonnent la reprise du plan, sans ouvrir de nouvelle feuille de route. Le nom historique du fichier `190.md` reste inchangé afin de préserver les liens. Aucun tag n'est présumé terminé. Le moteur économique doit geler chaque amélioration nette mesurée et continuer les recherches, sans cible fixe en dollars par jour. La spec canonique reste l'unique autorité normative.

## Autorités actuelles

1. **État lisible courant** : `docs/CURRENT_STATE.md`.
2. **Règles agent et sécurité** : `CLAUDE.md`, `AGENTS.md`, `SECURITY.md`.
3. **Scope économique exécutable** : `src/hl_observer/strategies/active_scope.py`.
4. **Preuves** : tests, registres machine et GitHub Actions du HEAD exact.
5. **Historique** : tasklists, rapports et anciens audits datés ; utiles pour la traçabilité, jamais pour surclasser le code ou les gates actuels.

## Règle

Aucun ancien chiffre de PnL, ancien verdict, ancien nombre de tests ou ancienne priorité ne doit être présenté comme actuel sans nouvelle preuve liée au HEAD courant.
