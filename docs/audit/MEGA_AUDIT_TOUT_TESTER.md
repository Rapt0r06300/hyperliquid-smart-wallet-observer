# MÉGA-AUDIT — chaîne TOUT-TESTER (2026-07-22)

Revue de code + QA de toute la chaîne `TOUT-TESTER.cmd → lanceur_tout_tester.py → tout_tester.py
→ étapes`, déclenchée par un **blocage réel** : la recherche a tourné **114 min sur un budget de
90**, à **0 % CPU** (deadlock), `Ctrl-C` sans effet. Objectif : plus AUCUN blocage possible, sans
jamais plafonner ce qu'on teste.

## 🔴 Cause racine du blocage (trouvée et corrigée)

`chercher_toutes(parallele=True)` utilisait un **`ProcessPoolExecutor`**. Sur Windows, avec une
grosse population (candidates.jsonl = **556 443 lignes / 258 Mo**), le pool **deadlocke** :
workers bloqués, **0 % CPU**, et — pire — les workers **survivent au `kill` du parent**, donc :
1. le tube `stdout` reste ouvert → l'orchestrateur `_courir` ne rend jamais la main ;
2. le minuteur dur (`proc.kill()`) ne tuait que le parent → **budget jamais respecté** ;
3. `Ctrl-C` (console) n'atteint pas les workers → sans effet.

**Correctif :** le pool est **retiré**. `chercher_toutes` est désormais **séquentiel** : il streame
sa progression en direct, **ne peut pas deadlocker**, et **teste TOUT (aucun plafond de
population)**. Chaque module reste blindé (une exception → verdict ERREUR, les autres continuent).

## ✅ Correctifs appliqués (avec tests)

| # | Risque | Correctif | Test |
|---|---|---|---|
| 1 | Deadlock du pool parallèle | `chercher_toutes` **séquentiel**, `ProcessPoolExecutor` et `_chercher_un_module` supprimés | `test_chercher_toutes_est_SEQUENTIELLE_et_ne_peut_pas_deadlock` |
| 2 | Budget non respecté (workers survivent au kill) | `_courir` tue **tout l'arbre** (`_tuer_arbre` : psutil / `taskkill /T` / `killpg`) + `start_new_session` | `test_courir_TUE_TOUT_L_ARBRE_pas_seulement_le_parent` |
| 3 | Timeout/Ctrl-C du **lanceur** laissait des orphelins | lanceur en **Popen** + `_tuer_arbre` au timeout ET au Ctrl-C | `test_le_lanceur_tue_TOUT_L_ARBRE_pas_seulement_l_enfant` |
| 4 | « Temps restant » faux/figé | **ETA MESURÉE** : la recherche émet `… avancement i/n configs`, le HUD calcule le reste sur la **vitesse réelle** | `test_hud_ETA_MESUREE_depuis_l_avancement_reel`, `test_0_avancement_emis_avec_total_hint...` |
| 5 | « reste run » trompeur en dépassement | plafonné par le **budget** (signe `≤`, jamais un faux « presque fini ») | `test_hud_ne_se_fige_pas_a_zero_quand_l_etape_deborde` |
| 6 | Progression invisible pendant une étape longue | **HUD collant** rafraîchi chaque seconde (spinner + barre + écoulé + reste + dernière ligne) | 8 tests `test_hud_*` |

## 🟢 QA — chaque étape pointe sur une cible réelle

`securite` (`hl_observer safety-audit`), `consolidation` (`hl_observer.runtime.replay_recorder`),
`tests` (`pytest`), `invariants` (`test_invariants_economiques.py`), `cablage`
(`tools/audit_cablage_cli.py`), `donnees` (`tools/qualite_donnees_replay.py`), `backtests`
(`tools/backtest_carry_cli.py`), `recherche` (`chercher_toutes`), `rapport_jour`
(`tools/rapport_quotidien.py`) — **toutes présentes**, CLI importable, tout compile.

## 🟢 Points déjà solides (confirmés à la revue)

- **`TOUT-TESTER.cmd`** : minimal, ASCII, CRLF, zéro `goto`/`label`/`chcp`/`endlocal`, pause
  toujours atteinte, message explicite si `python` absent (errorlevel 9009). Toute la logique est
  en Python testé. **RAS.**
- **Pré-vol** (version Python, arborescence, disque, OneDrive, UNC), **contrôle sécurité**
  (interrupteurs d'exécution réelle + secrets refusés au démarrage), **verrou** anti-double-run
  avec péremption, **archive** du RECAP précédent, **filet** `point_d_entree` qui affiche toute
  exception (même à l'import) et garde la fenêtre ouverte. **RAS.**
- Chaque étape a son **budget**, écrit son verdict, et le RECAP est écrit **atomiquement, à la fin,
  quoi qu'il arrive**.

## ⚠️ Limites restantes (honnêtes)

- Sur **Ctrl-C**, l'arbre est coupé → l'orchestrateur ne finit pas d'écrire un RECAP frais (le run
  était de toute façon interrompu volontairement). C'est le bon compromis : **pouvoir arrêter** >
  « avoir un RECAP d'un run avorté ». Relancer donne un RECAP complet.
- La recherche séquentielle **teste tout** : sur données massives, elle est plus lente que l'ancien
  parallèle (qui, lui, deadlockait). Le filet de budget la coupe proprement si besoin (RECAP quand
  même écrit). Le budget est réglable (`TOUT_TESTER_BUDGET_S`).
- La preuve exhaustive des **5 849 tests** reste le run Windows (le sandbox tronque les très gros
  fichiers). Compilation de tout l'arbre + imports + sous-ensembles ciblés : **verts**.

## 🔒 Sécurité

Rien de tout ceci ne touche au no-real-trade : ce sont des mécanismes d'orchestration en lecture
seule. **0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
