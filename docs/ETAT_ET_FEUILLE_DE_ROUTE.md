# Alina SmartFlow — État & feuille de route

> **Source de vérité actuelle : [`docs/CURRENT_STATE.md`](CURRENT_STATE.md).**
>
> L'ancien contenu de ce fichier, daté de juillet 2026, était devenu contradictoire avec le code, les 775 optimisations scellées, le scope V2 et les campagnes économiques ajoutées depuis. Il reste intégralement disponible dans l'historique Git antérieur à cette mise à jour, mais ne doit plus être utilisé comme état courant.

## Nouvelle feuille de route d'exécution (2 novembre 2026)

La feuille de route d'audit et de correction la plus récente est :
[`docs/superpowers/plans/2026-11-02-alina-audit-roadmap-190.md`](superpowers/plans/2026-11-02-alina-audit-roadmap-190.md).
Elle recense désormais **390 tâches distinctes** : 150 tâches ASF-001 à ASF-150, 40 tâches AUD-001 à AUD-040, et 200 tâches Copy-Vault ECO-001 à ECO-200 issues d'un audit économique et de recherches. Chaque tag a un objectif, un ancrage et une preuve attendue; aucune nouvelle tâche n'est présumée terminée. Le nom historique du fichier en `190.md` est conservé pour maintenir le lien, mais sa feuille de route active couvre bien 390 tâches. Le moteur économique doit geler chaque amélioration nette mesurée et continuer les recherches, sans cible fixe en dollars par jour. La spec canonique reste l'unique autorité normative.

## Autorités actuelles

1. **État lisible courant** : `docs/CURRENT_STATE.md`.
2. **Règles agent et sécurité** : `CLAUDE.md`, `AGENTS.md`, `SECURITY.md`.
3. **Scope économique exécutable** : `src/hl_observer/strategies/active_scope.py`.
4. **Preuves** : tests, registres machine et GitHub Actions du HEAD exact.
5. **Historique** : tasklists, rapports et anciens audits datés ; utiles pour la traçabilité, jamais pour surclasser le code ou les gates actuels.

## Règle

Aucun ancien chiffre de PnL, ancien verdict, ancien nombre de tests ou ancienne priorité ne doit être présenté comme actuel sans nouvelle preuve liée au HEAD courant.
