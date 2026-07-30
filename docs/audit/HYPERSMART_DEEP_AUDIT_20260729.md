# HYPERSMART — AUDIT PROFOND (2026-07-29)

Réponses directes aux questions posées par la roadmap V2 §7, sur le HEAD réel, pas sur la documentation.

---

## 1. Qu'est-ce qui tournait réellement au démarrage officiel ?

`LANCER_HYPERSMART.cmd` (double-clic, sans argument) exécute :

1. un **préflight** : verrou d'instance unique (port 8794), registre PID/run_id, archivage du replay ;
2. `python -m hl_observer.ops.superviseur_collecteurs demarrer-tous core` → **profil CORE = `allMids` + `BBO`
   uniquement** ;
3. `tools/start_hypersmart_simulation.ps1` → `python -m hl_observer ui` (moteur + dashboard).

Tout le reste des collecteurs (vaults, liquidations, overshoots, microstructure, userfills…) est écrit dans
le `.cmd` **après une instruction `exit /b 0`** : ces lignes sont donc **inatteignables** depuis l'autopilot
et ne démarrent que via les sous-commandes `collectors-research` / `collectors-all`.

## 2. Qu'est-ce qui était ON seulement sur le papier ?

- `HYPERSMART_EXPERIMENTAL_PAPER=1`, `HYPERSMART_EXPLORATORY_PAPER=1`, `HYPERSMART_FUNDING_ARB_PAPER`,
  `HYPERSMART_V26_FUNDING_POLLER` : posés par le lanceur, mais leurs producteurs (`experimental-paper`,
  collecteurs de recherche) appartiennent au profil `research`, **pas à CORE**. Un flag sans producteur est
  **OFF de fait**.
- Mesure : **1 interrupteur mort** et **62 vivants** au HEAD (`tools/auditer_cablage.py`).

## 3. Qu'est-ce qui tournait alors qu'il était hors scope ?

Le bloc 1 (`0ffa5e5`) a rendu la **liste d'autorisation autoritative au point de décision** :
`cross_venue_dislocation`, `lead_lag`, `copy_vault` et les cohortes SHADOW. Preuve runtime enregistrée au
ledger : `CLI refactor-fusion-run → 1 ordre cross-venue, 0 funding, 0 bus externe`. Le carry historique est
`HYPERSMART_CARRY_DISABLED=1` et n'ouvre plus.

## 4. Quel est désormais l'unique moteur de fill/comptabilité paper ?

`hl_observer.market_truth` : `canonicalize_tick_record` → `FeedQualityGate` → `replay_executable_fill` →
`TruthChain` (PaperLedger + réconciliation), orchestré par `MarketTruthPipeline`. Le bloc 4 (`8cfcb62`) a
prouvé que le cœur direct, `PaperEngine` et `PaperSimConnector` rendent **le même fill** sur le même snapshot
(`parity=true`).

## 5. Les chemins paper donnent-ils le même résultat sur une fixture commune ?

Oui pour la parité d'exécution (bloc 4, `parity=true`) et pour la parité causale replay↔forward
(bloc 17 : troncature du futur, warm-up 5/20/27, reconnexion, doublons, reorder, rejeu idempotent).
**Réserve honnête** : la parité est prouvée sur le cœur d'exécution, pas sur les trois pipelines applicatifs
complets de bout en bout dans un même run live.

## 6. Quelle part du PnL historique change après correction ?

Non chiffrable, et le dire est plus utile qu'un pourcentage inventé : les ledgers historiques
(`carry_paper`) n'ont **pas** les prix exécutables nécessaires (100 ouvertures sans prix ni notionnel).
On ne peut donc pas comparer « avant/après » sur ces données. Ce qui est mesurable au HEAD :
`raw_probe` = 19 épisodes, **-5,88 bps/trade**, PF 0,66.

## 7. Différence `mid equity` vs `liquidatable equity` ?

Structurellement : le mid n'est jamais autoritatif. `unrealized_mid_pnl_usd` est **informatif**,
`liquidatable_pnl_usd` est **autoritatif** quand exécutable (bloc 7, `74de4c3`). Le chiffrer sur les données
actuelles supposerait des carnets joints aux épisodes historiques — ils ne le sont pas : `BLOCKED_DATA`, avec
producteur en place (`collecter_carnet`).

## 8. Quelle stratégie a la meilleure espérance nette ?

**Aucune n'est positive.** La seule mesurable (`raw_probe`) est négative dans les trois enveloppes
(BASE -0,168 · P95 -0,276 · P99 -0,384). Publier un classement entre une stratégie mesurée et deux
non mesurables serait un faux classement.

## 9. Idées externes rejetées, et pourquoi

Voir `HYPERSMART_EXTERNAL_IDEAS_20260729.md` : Hummingbot (pas de MM réel), Nautilus (pas de réécriture),
hftbacktest (latence reste `ASSUMED`), Freqtrade (méthode oui, stratégies non), Cryptofeed (concept oui,
dépendance non), petits repos « AI bot » (aucun mécanisme testable), posts X (question, pas preuve).

## 10. Idées qui restent SHADOW faute de données

ALPHA-5 (tape L2 par condition), ALPHA-7 (densité de TWAP simultanés), ALPHA-8 (NAV point-in-time des
wallets), capacité par épisode. **Le producteur existe dans les quatre cas** — il manque l'exécution d'une
campagne, pas du code.

---

## 11. Bugs trouvés dans CE run, avec cause racine

| Bug | Cause racine | Correction |
|---|---|---|
| `manifeste_campagne` déclarait un arbre **propre** quand `git` ne répondait pas | `subprocess` en échec rendait `""`, indistinguable de la sortie vide d'un arbre propre | Tri-état `True/False/None` + `reproductible=False` si inconnu (`1ca1a34`) |
| `market_truth` (1 145 l.) sans aucun appelant de production | Module écrit et testé, jamais branché — maladie « testé-seulement » | Étape `market_truth_replay` dans le lanceur d'analyse (`1ca1a34`) |
| Diagnostic erroné de ma part : `pnl_improvement_lab` classé orphelin | Recherche des appelants par `import` seulement, alors qu'il est lancé en **sous-processus** | Méthode corrigée : chercher aussi le nom comme chaîne de commande |

## 12. Limite majeure de ce run

**Rien n'a été exécuté sous Windows.** Le sandbox est Linux (Python 3.10 — d'où l'unique `FAIL` de
`doctor` : `python_3_11_plus`). La recette Windows, `LANCER_HYPERSMART.cmd self-test` et
`ANALYSER_BACKTESTS_REPLAYS.cmd full` **n'ont pas été lancés par moi**. La vérité du projet reste Windows.

---

`Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.`
