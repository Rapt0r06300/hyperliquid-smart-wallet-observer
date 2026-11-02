# Alina SmartFlow — État & feuille de route

> **Source de vérité actuelle : [`docs/CURRENT_STATE.md`](CURRENT_STATE.md).**
>
> L'ancien contenu de ce fichier, daté de juillet 2026, était devenu contradictoire avec le code, les 775 optimisations scellées, le scope V2 et les campagnes économiques ajoutées depuis. Il reste intégralement disponible dans l'historique Git antérieur à cette mise à jour, mais ne doit plus être utilisé comme état courant.

## Nouvelle feuille de route d'exécution (2 novembre 2026)

La feuille de route d'audit et de correction la plus récente est :
[`docs/superpowers/plans/2026-11-02-alina-audit-roadmap-190.md`](superpowers/plans/2026-11-02-alina-audit-roadmap-190.md).
La feuille de route contient désormais **422 tâches distinctes** : 150 tâches ASF-001 à ASF-150, 72 constats d'audit AUD-001 à AUD-072, et 200 tâches économiques Copy-Vault ECO-001 à ECO-200. Le dernier audit (3 novembre 2026) a ajouté 32 constats, classés en bugs confirmés dans le code, blocages de preuve ou risques à reproduire. Chaque tâche conserve son tag et sa preuve exigée. Aucun nouveau tag n'est présumé réalisé. Le nom historique du fichier en `190.md` est conservé pour assurer la stabilité du lien, mais le document actif couvre 422 tâches. Le moteur économique doit geler chaque amélioration nette mesurée et continuer les recherches, sans cible fixe en dollars par jour. La spec canonique reste l'unique autorité normative.

## Autorités actuelles

1. **État lisible courant** : `docs/CURRENT_STATE.md`.
2. **Règles agent et sécurité** : `CLAUDE.md`, `AGENTS.md`, `SECURITY.md`.
3. **Scope économique exécutable** : `src/hl_observer/strategies/active_scope.py`.
4. **Preuves** : tests, registres machine et GitHub Actions du HEAD exact.
5. **Historique** : tasklists, rapports et anciens audits datés ; utiles pour la traçabilité, jamais pour surclasser le code ou les gates actuels.

## Règle

Aucun ancien chiffre de PnL, ancien verdict, ancien nombre de tests ou ancienne priorité ne doit être présenté comme actuel sans nouvelle preuve liée au HEAD courant.
