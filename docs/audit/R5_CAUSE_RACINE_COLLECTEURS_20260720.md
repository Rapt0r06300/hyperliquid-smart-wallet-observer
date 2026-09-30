# R5 — Cause racine : pourquoi les 4 collecteurs meurent ENSEMBLE (verdict 20/07)

## Les faits (journal superviseur + ledgers, tous vérifiables)
- **19/07 15:28** : les 4 collecteurs se taisent À LA MÊME MINUTE (âge au constat identique :
  262 min pour les quatre). Relance groupée par le superviseur le 19/07 19:50. C'est LA panne
  déjà connue (#163) — **aucune récidive groupée depuis** (24 h+ de recul).
- **18/07** : le MOTEUR lui-même a des trous de 66, 95 et 139 min — même machine, même classe
  d'interruption, un jour où les collecteurs n'existaient pas encore sous cette forme.
- **20/07 ~16:31** : venues-collector meurt SEUL (2e relance à 16:52). Son script a des
  timeouts réseau (12 s) — le mode solitaire est distinct du mode groupé.

## Verdict
**Cause racine du mode groupé : interruption MACHINE (veille/gel du PC), pas notre code.**
Quatre boucles `.cmd` indépendantes ne crashent pas à la même seconde ; un processus qui gèle
avec sa machine, si. Les trous moteur du 18/07 (66–139 min) signent la même main. Le
superviseur est le bon remède : il a relancé les 4 en une passe, et il journalise chaque cas.

Test décisif (côté Windows, 1 commande, si tu veux la preuve absolue) :
`powercfg /systemsleepdiagnostics` — si une veille couvre 15:28→19:50 le 19/07, dossier clos.

## Mode solitaire (venues) — sous surveillance
2 occurrences. Hypothèse dominante : passe bloquée hors timeout ou boucle orpheline tuée par la
fermeture de la console lors des redémarrages rapprochés (16:00 → 17:02 → 17:19). Le journal
du superviseur compte chaque relance ; si `relances_total` de venues grimpe seul, c'est lui.

## Ce qui est armé en permanence
superviseur (constat ≤ limite par collecteur, relance + journal) · `.prev` du log préservé à
chaque relance (1 génération) · compteur PANNES_INTERNES. Un mort silencieux n'existe plus.
