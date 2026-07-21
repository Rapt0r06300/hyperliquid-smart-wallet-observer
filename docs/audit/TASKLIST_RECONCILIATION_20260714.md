# Réconciliation TASKLIST — audit exhaustif du 2026-07-14

**Demande de Flo : « vérifie que tout ce que contient ce fichier soit entièrement terminé ».**
Méthode : chaque affirmation vérifiée sur pièces (fichiers, dates, rapports, tests), pas sur
mémoire. Ce document est le verdict item par item, catégorie par catégorie.

## 0. La découverte qui prime sur tout : 5 jours de travail NON COMMITÉS

Le dernier commit datait du **08/07 23:17** (`79a626c`). TOUT le travail du 09→13/07 (edge
empirique, mutation testing, horloges de fraîcheur, safety gates truth, triage H-46→H-89,
la suite de 3 520 tests, les 7 passes du 13/07) vivait uniquement sur le disque.
→ **Protégé le 14/07 : commit `246cef4` — 666 fichiers, 80 982 insertions.**
`runtime/scenarios/` (12 Go), `runtime/replay/`, `runtime/history/`, `coverage.json` ajoutés
au `.gitignore` (données régénérables, pas du code).

## 1. Les compteurs du fichier, recomptés

| ce que dit TASKLIST.md | mesuré (grep) | verdict |
|---|---|---|
| « TOTAL 544, terminées 260, en attente 284 » | 251 cochées `[x]`, 264 non cochées `[ ]` | compteurs périmés |
| « EN ATTENTE — 293 taches » | 264 | périmé |
| « EN COURS (1) : #586 » | #586 est RÉSOLUE+RÉFUTÉE (§7 du même fichier) | **contradiction interne** |
| §5 « #597 toujours ouvert » | 4e passe : ✅ #597 fermée (plafond BAISSÉ 304→273) | strate périmée |
| §6 « quoi faire : #597, #588, #599 » | les 3 sont FAITES (4e, 8e→#588 le 13/07, 6e passes) | strate périmée |
| §3 « #588 liquidation non modélisée » | `funding/carry_liquidation_risk.py` + `docs/audit/T2b_CARRY_LIQUIDATION.md` + `MESURER-588.cmd`, datés 13/07 | FAIT — verdict 2,0 % APR |

Corrections appliquées le 14/07 dans TASKLIST.md (strates mises à jour, doublons cochés).

## 2. Pourquoi « non coché » ≠ « à faire » — la structure du fichier

Le fichier garde l'archive brute (« aucune tâche supprimée ») ET des blocs de réconciliation
par lot. Beaucoup d'entrées `[ ]` individuelles ont DÉJÀ leur verdict dans un bloc `[x]` :

- **Dominés par T1b** (loi de DOMINATION, mesure à 100 % de fill, 0/29 coins) : #375 (M-01),
  #378 (M-02), #379 (M-03), #399 (M-23), #402 (M-26), #403 (M-27), #389 (M-13 volet MM),
  #357 (GH-04), #360 (GH-07), #295/#321/#322 (P8 grinder), #417 (H-12), #427 (H-22),
  #432 (H-27), #408 (H-03 carnet local pour nos fills). *Un meilleur modèle de file ne peut
  que BAISSER le fill : inégalité, pas préjugé.*
- **Fermés par mesure directe** : copy-trading (−7,97 bps à coût zéro, 24 133 obs OOS),
  latence (courbe PLATE), SL/TP (0/150 M configs OOS), funding jambe nue (281:1),
  X-04 funding perp↔perp (0/120), #373 (X-12 HIP-3 : porte INVENTAIRE fermée, ratio 0,20),
  biais récursif #355/GH-02 (écart 26 M× sous le seuil). Chaque zone morte porte sa condition
  de réouverture : c'est une facture payée, pas un dogme.
- **Moisson épuisée, mesurée** (H-81, rendement décroissant) : #368 (X-07), #376 (X-15),
  #377 (X-16), #383 (M-07), #415 (H-10), #419 (H-14), #425 (H-20). Ne pas re-moissonner.
- **Doublons d'une tâche faite** : #369 (X-09) = #588 ✅ ; #591 et #594 (entrées DIVERS)
  faites en 6e/4e passes ; #310 = #594.
- **Notes de lecture** (M-*/H-* restants, ~150) : des idées à évaluer, pas du travail engagé.
  Règle de tri en vigueur : *on ne refuse une idée que si elle consomme LA MÊME ENTRÉE
  qu'une mesure morte.*

## 3. CE QUI EST RÉELLEMENT OUVERT (14/07) — la liste que « tout finir » veut dire

### A. Pistes PnL vivantes (dans l'ordre de valeur)
1. **#372/X-11 + #412 (H-07) — LIQUIDATIONS** : la meilleure piste (flux FORCÉ, non informé —
   le liquidé ne choisit pas de vendre). Bloquée par : on ne COLLECTE pas le flux. Étape 1 :
   trancher #374 (X-13 : est-ce possible sur HL ?) sur pièces (H-07 a des preuves) ;
   étape 2 : brancher la collecte read-only. 4 pièges déjà documentés.
2. **Carry HYPE (T2/T2b ✅)** : mesuré ~2,0 % APR sur capital total, verrou liquidation câblé.
   Décision d'EXPLOITATION à prendre par Flo : activer en paper ou garder en réserve.
   (⚠️ frais spot 4,0 bps ≠ perp 1,5 : déjà corrigé le 13/07 soir, −15 % sur l'edge.)
3. **#556 / #413 (H-08) — funding PRÉVISIBLE** (l'angle survivant du lead-lag oracle : une
   heure pour agir, pas une course de vitesse).
4. **#370 (X-09) mempool / flux pré-exécution** : la seule réouverture structurelle du
   copy-trading (T3). Exploratoire, aucune promesse.

### B. Ingénierie de vérité (aucun edge promis, valeur réelle)
5. **#286 (P1)** — identifiant de session commun aux 3 processus (« la plus importante des
   restantes » ; 20 lignes + un LECTEUR).
6. **#292b** — les 11 gates de `risk_engine_v3` : brancher au chemin d'entrée live ou enterrer.
7. **#325 → #304 (P17)** — baseline PnL IMMUABLE, sans elle toute « amélioration » est
   invérifiable.
8. **#302 (P15)** — replay déterministe + shadow mode (l'outil anti-mensonge ancien vs nouveau).
9. **#303/#348 (R2)** — tests de panne/charge (~35 cas) — le run 48 h a crashé 2 fois.
10. **#320 (P5-2)** — buffers bornés anti-bloat SQLite (cause d'un crash de run).
11. **#314 (P4-3)** — fiabilité WS (heartbeat/gap/dedupe) — partiellement fait (V27).
12. **#347 (R1)** — finir matrice de preuves/archive ; **#287 (P2)** à réconcilier (largement
    répondu par Q1/G2/#594/#318) ; **#363 (X-02)** sceller 2 zones mortes avec la doc officielle.
13. **#352 (G3) / #361 (GH-08) / #366 (X-05) / #423 (H-18)** — matrice de distillation +
    question juridique des repos, UNE fois.
14. **H-30 volet enterrement** — registre `backtesting/` pour `lookahead_analysis` (façade
    redondante) — décidé, pas encore fait.
15. **#326** — règle rollout (un changement à la fois, tout derrière flags) — process.
16. **#306 (P19)** — rapport final : le dernier, par construction.

### C. Bloqués par données/temps (pas par du code)
- **#115** (run de collecte long — prérequis bornes disque = #320) ; **#143** (cascades de
  liquidations — dépend de X-11/X-13) ; **#145** (basis CEX — aucune donnée CEX ; bonne
  formulation = H-151) ; #407/#418/#437 (sources tick historiques : « data-limited » —
  ⚠️ en partie levé par candleSnapshot 208 jours, mais PAS pour le carnet L2).

## 4. Vérité des tests au 13/07 (dernières preuves)

`check_601.txt` : **3 520 passed / 0 failed** (244 s), safety 8/8, doctor 10/10, le `.cmd`
atteint FIN. Couverture de LIGNES : 83,83 % (la seule mesure honnête), 3 cliquets posés.
Mutation testing : score 62,5 % → trous connus et nommés (le `+` entre deux coûts d'edge_calculator,
la borne MIN_ECHANTILLON, le garde division-par-zéro) — travail de fond légitime restant.

## 5. Sécurité

Rien dans cette réconciliation ne touche l'exécution : lecture, docs, git. Les 8 contrôles
safety + le contrôle runtime transport restent en place. **0 ordre réel, 0 argent réel,
0 clé privée, 0 signature, 0 dépôt/retrait.**
