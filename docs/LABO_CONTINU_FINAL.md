# LABO-CONTINU-FINAL — laboratoire de recherche continu (paper-only)

**But.** Un laboratoire qui démarre au CMD, travaille **sans limite de durée** en cycles, et produit le
**rapport final** uniquement au **Ctrl+C** (ou `stop <run_id>`). **ADDITIF** : ne touche ni au mode 14 h ni
au mode 18 h. Sortie exclusivement sous `runtime/research_lab/continuous/<run_id>/`. **0 ordre réel, 0
argent, 0 clé, 0 signature, 0 dépôt/retrait.**

## Lancer
```
LANCER-RECHERCHE-CONTINUE.cmd dry-run     # sécurité + disque + ressources
LANCER-RECHERCHE-CONTINUE.cmd start       # travaille jusqu'au Ctrl+C -> rapport final
LANCER-RECHERCHE-CONTINUE.cmd status
LANCER-RECHERCHE-CONTINUE.cmd snapshot    # rapport intermédiaire SANS arrêter
LANCER-RECHERCHE-CONTINUE.cmd stop <run_id>
```

## Chaîne (10 briques, toutes câblées)
1. **Ingestion incrémentale précise** — `tools/curseurs_continue.py` : un curseur par source (offset octet +
   SHA de la région déjà consommée pour détecter rotation/troncature/remplacement). On ne relit **jamais**
   tout l'historique ; chaque cycle distingue `new_events` / `historical_context` / `affected_windows`.
2. **Scheduler adaptatif** — `tools/scheduler_continue.py` : 7 files prioritaires, **signature canonique** de
   trial (dédup fiable, code_sha estampillé), filtre de nouveauté, recherche **multi-étages** (grille indexée
   par cycle → jamais les mêmes 64, random, recherche locale autour des meilleurs). Objectif de sélection
   **multi-critères** : un net ≤ 0 n'est **jamais** promu (pas de gros PnL brut instable/mono-coin).
3. **Familles élargies honnêtes + horizons subseconde** — `tools/familles_continue.py` : une famille ne
   compte que si la donnée porte son **prédicat réel** (OFI, sweep, liquidation, funding, momentum, z-score…) ;
   sinon 0 épisode → **DATA_MISSING honnête** (alimente l'analyse permanente des refus). Horizons dès 100 ms.
4. **Deux vitesses** — FAST_SCREEN (approx, non éligible) puis EXACT_REPLAY causal, **interruptible** (le
   `stop_event` est vérifié à chaque variante → Ctrl+C traité en secondes même en plein replay).
5. **Validation** — walk-forward purgé/embargo, CPCV, DSR, PBO, placebos, stress (via `validation_18h`).
6. **Champions / challengers** — `tools/champions_continue.py` : statuts (EXPLORATOIRE…CHAMPION/KILL),
   **registre append-only** (une amélioration = nouveau `candidate_id` + version + `parent_id`, **jamais** de
   réécriture d'un candidat figé), mesure de **dérive** (edge/fill/coût/vol, dormant/réveillé).
7. **Dashboard threadé** — un thread rafraîchit l'affichage toutes ~1,5 s (horloge recalculée en direct),
   **même pendant un long calcul** ; compteurs réels depuis les campagnes.
8. **Superviseur de collecteurs** — `tools/superviseur_continue.py` : PID + create_time enregistrés,
   **anti-doublon** au resume, **restart individuel** des morts, **arrêt explicite** à la fin. Ne lance que
   des collecteurs **read-only** ; garde-fou : ne tue jamais son propre PID.
9. **Ctrl+C strict + IPC** — 1er Ctrl+C = arrêt propre (checkpoint, curseurs, réconciliation, CSV/JSON,
   rapport MD, **manifeste SHA-256 en dernier**) ; 2e Ctrl+C = `FINALIZATION_PARTIAL` (rien de perdu en
   silence). `stop <run_id>` écrit **`STOP_REQUEST.json`** que la **boucle principale** détecte et finalise
   elle-même (jamais un process concurrent). `snapshot` ne bloque pas la boucle (process séparé).
10. **Rapport final** — dans `Rapports en continu/<run_id>/`, plus un **`INDEX-RAPPORTS.md`** racine (une
    ligne par rapport). Sections : résumé, durée/identité, sécurité, sources/couverture, totaux,
    **réconciliation PnL/ROI/equity/DD**, **champions**, pistes (exploratoire ≠ validé), KILL/DATA_MISSING,
    refus & effet des gates, matrices, lignée, limites, reproduction, manifeste.

## Vérité des données (règle dure)
Le rapport sépare toujours **exploratoire / prometteur (holdout>0, à valider) / confirmé (forward paper) /
rejeté**. Une piste positive sur données **synthétiques** (fallback quand aucune archive BBO exploitable)
n'est **jamais** présentée comme un edge réel. La loi mesurée reste : après coûts A/R complets, les
mécanismes natifs testés sont **KILL** — on ne garde que ce qui survit, sans jamais maquiller un chiffre.

## Tests
`tests/test_labo_continu_final.py` (23 tests d'acceptation) + `tests/test_recherche_continue.py` (12).
Accélérés (`max_cycles`, tmp) : curseurs offset/rotation, new_events/affected_windows, jamais de cycle vide,
scheduler nouveauté/multi-étages/7 files, objectif multi-critères, familles honnêtes, EXACT_REPLAY
interruptible, champions/dérive/gel, dashboard threadé, superviseur, Ctrl+C strict, STOP_REQUEST IPC,
dossier `<run_id>` + INDEX, réconciliation, 14h/18h intacts, paper-only.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
