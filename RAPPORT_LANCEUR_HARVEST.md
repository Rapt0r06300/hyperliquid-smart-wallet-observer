# Rapport — Audit & réparation profonde de `LANCER_HYPERSMART.cmd`

**Objectif :** après correction, tu ne fais qu'une chose — double-cliquer sur `LANCER_HYPERSMART.cmd`.
Le lanceur prépare l'environnement, démarre toute la récolte utile, **prouve** que chaque flux reçoit
réellement des données, surveille les pannes, et reste **strictement paper / lecture seule**
(0 ordre réel, 0 clé, 0 signature, aucun `/exchange`).

`ANALYSER_BACKTESTS_REPLAYS.cmd` **n'a pas été touché** (comme demandé).

---

## 1. Ce qui a été livré — 9 blocs, 9 commits, 24 fichiers, tout testé

| SHA | Bloc | Item(s) | Contenu |
|-----|------|---------|---------|
| `13c49a1` | 1 | 1, 8 | Profil officiel **HARVEST** (distinct de `research`) + sortie non-zero si une source obligatoire manque |
| `027c205` | 2 | 6 | **Preflight BLOQUANT** avant le moteur (10 contrôles) |
| `acc6fdd` | 3 | 7 | **Preuve de vie** par source → READY / DEGRADED / DATA_NOT_READY |
| `60603df` | 4 | 10 | **Registre PID réel** + arrêt ciblé zéro orphelin |
| `0a128a2` | 5 | 11 | **Stockage borné** — quota + alarme pré-saturation + rétention explicite |
| `b0f37f5` | 6 | 12 | **Tableau de santé** live des collecteurs |
| `514a771` | 7 | 5 | **Persistance dYdX** + branchement WS → stockage |
| `d06499b` | 8 | 2,7,8,9,10 | Câblage chirurgical du `.cmd` / `.ps1` |
| `6768310` | 9 | 13 | **Recette E2E** + barrière CI |

Fichiers **créés** : `preflight_lanceur.py`, `preuve_de_vie.py`, `registre_pids.py`, `quota_stockage.py`,
`tableau_sante_collecteurs.py`, `recette_lanceur.py` (sous `src/hl_observer/ops/`),
`hyper_smart_observer/dydx_v4/flux_live.py`, `RECETTE-LANCEUR.cmd`, + 8 fichiers de tests.

Fichiers **modifiés** : `LANCER_HYPERSMART.cmd`, `tools/start_hypersmart_simulation.ps1`,
`superviseur_collecteurs.py`, `dydx_v4/storage.py`, `dydx_v4/indexer.py`, `.github/workflows/ci.yml`,
+ 2 canaris de test mis à jour.

---

## 2. Tests exécutés (sandbox Linux, `PYTHONPATH=src`)

- **Barrière CI « Lanceur HARVEST »** (les 8 nouveaux fichiers) : **53 verts**.
- **Canaris lanceur + sécurité** (superviseur, config, single-launcher, no-real-trade, safety-audit,
  runtime-protections…) : **83 verts**.
- **Suite dYdX v4 complète** (régression après la persistance) : **358 verts**.
- `python -m hl_observer safety-audit` et `audit-safety` : **ok** (aucun endpoint d'exécution réelle).
- Ces 8 fichiers sont aussi **auto-shardés** par la CI (`ci_shard` : partition valide, 1426 fichiers)
  et branchés sur les jobs **Linux** *et* **Windows**.

**Recette Windows :** `RECETTE-LANCEUR.cmd` est prête à être **double-cliquée sur ta machine** après le
lanceur. Elle appelle `python -m hl_observer.ops.recette_lanceur` (verdict composé : preflight + preuve
de vie + registre PID + zéro orphelin + paper strict) puis décrit la vérification manuelle de la relance
après panne. La partie **live Windows** (vrais heartbeats, vraie DB) ne peut pas tourner dans mon bac à
sable Linux (pas de Windows, pas de réseau d'échange, dépendances absentes) — elle s'exécute chez toi.
Le **flux E2E complet** (preflight → HARVEST → READY → panne d'un collecteur tué → relance → arrêt propre
→ zéro orphelin → paper strict) est prouvé de façon **déterministe** par `test_e2e_lanceur_harvest.py`.

---

## 3. Flux RÉELLEMENT collectés au double-clic (profil HARVEST)

Chaque collecteur ci-dessous a un **vrai runner** présent sur le disque, dédupliqué par le superviseur
(source canonique unique par canal — item 3) :

| Collecteur | Canal / venue | Runner |
|-----------|---------------|--------|
| `allmids-collector` | allMids (Hyperliquid) | `tools/collecter_allmids.py` |
| `bbo-collector` | BBO **Hyperliquid + Binance** | `tools/collecter_bbo.py` |
| `userfills-live` | userFills leaders (rotation, **≤ 10 wallets** simultanés) | `tools/collecter_userfills_vaults.py` |
| `carnet-collector` | L2 book (HL) + depth Binance | `tools/collecter_carnet.py` |
| `marks-collector` | marks tous coins | `tools/ecrire_marks_tous_coins.py` |
| `liq-collector` | liquidations | `tools/collecter_liquidations.py` |
| `venues-collector` | dispersion multi-venues | `tools/collecter_dispersion_venues.py` |
| `overshoot-collector` | overshoots | `tools/collecter_overshoots.py` |
| `vault-collector` | découverte de vaults | `tools/collecter_vaults.py` |
| `scorer-vaults` | scoring de vaults | `tools/scorer_vaults.py` |
| `backfill-fills` | backfill fills de vaults | `tools/backfill_vault_fills.py` |
| `backfill-candles-vaults` | backfill candles | `tools/backfill_candles_vaults.py` |

Plus, démarrés par le `.ps1` : le **moteur/UI paper** (port 8794), le **poller** simulation, le **stream
userFills HF**. Les **3 sources CORE** (allMids, BBO, userFills) sont **obligatoires** : si l'une ne
démarre pas, le superviseur sort en code 3 et **le moteur ne se lance pas** (item 8).

**Respect des quotas WS (item 4) :** WS réservé aux leaders prioritaires (`userfills_live`, MAX_SLOTS=10) ;
l'univers massif passe par REST/backfill. Le preflight **vérifie** le budget (10 connexions / 10 users /
1000 souscriptions) avant de lancer.

---

## 4. Flux encore BLOQUÉS (honnêtement hors profil — aucune donnée fabriquée)

- **dYdX (live)** : la **persistance est désormais réparée et testée** (bloc 7) — trades, positions,
  subaccounts et **carnets** sont vraiment écrits en SQLite (avant : normalisés puis **jetés**) ; le
  branchement WS→stockage (`flux_live.PiloteFluxDydx`), la dédup, le **gap recovery** REST, le heartbeat
  et la **reprise après crash** existent et sont couverts par 358 tests verts. **MAIS** le profil HARVEST
  **ne démarre pas encore** de processus collecteur dYdX (il n'y a pas d'entrée dYdX dans le `REGISTRE`
  du superviseur). Autrement dit : **dYdX est prêt à persister, mais pas encore auto-démarré** par le
  double-clic. Prochaine étape : un runner `tools/` qui relie `DydxIndexerWsClient` à `PiloteFluxDydx`
  + une entrée `REGISTRE`.
- **Bybit** : exclu tant que son **vrai collecteur public** n'est pas implémenté et testé (ta condition).
- **node fills global**, **HF recorder standalone**, **TWAP slice standalone**, **L4 capture** : restent
  `BLOCKED_EXTERNAL` — pas de runner réseau réel, donc **hors profil** (on ne prétend pas les collecter).

---

## 5. Deux points « prêts mais pas encore activés » — dits franchement

Ces deux modules sont **codés et testés**, mais leur **activation live** demande un branchement
supplémentaire que je n'ai **pas** fait, pour ne pas casser une protection existante :

1. **Stockage brut borné (item 11).** Le module `quota_stockage` (quota, alarme, rétention sans
   suppression silencieuse) est complet. Mais le lanceur garde encore `HYPERSMART_DISABLE_RAW_STORAGE=1`
   — le drapeau qui avait évité le crash de la DB à 29 Go. **Le rebrancher sans câbler la garde dans les
   writers ré-ouvrirait le risque de saturation.** Activer = plomber `GardeStockage` dans les writers
   bruts, puis passer le drapeau à 0.
2. **Tableau de santé (item 12).** Le module produit la zone dynamique + le journal horodaté, et le
   lanceur affiche déjà un **instantané** de preuve de vie. La **boucle d'affichage continue** dans la
   fenêtre principale (rafraîchie chaque seconde) reste à câbler dans le `.ps1`/l'UI.

Je préfère te le dire clairement plutôt que cocher une case en vert.

---

## 6. Sécurité — inchangée et vérifiée

Paper strict de bout en bout : `HL_ENV=paper`, `HL_ENABLE_MAINNET_EXECUTION=0`,
`HL_ENABLE_TESTNET_EXECUTION=0`, `HYPERSMART_MODE=SIMULATION_ONLY_UNTIL_MANUAL_REVIEW`. Le preflight
**bloque** si un flag d'exécution réelle est actif. La recette E2E **scanne** le lanceur : aucun
`/exchange`, aucune clé, aucune signature. `safety-audit` / `audit-safety` : **ok**.

---

## 7. Réserve honnête

Deux tests étaient **déjà rouges avant cette tâche** (commit `9fce6a3`, session précédente) et sont
**sans rapport** avec le lanceur : `test_runtime_no_limbo` (module `runtime/protections` que personne
n'importe) et `test_risk_guards_no_limbo` (`paper_trading`). Mes modules sont dans `ops/` ; je n'ai
**rien ajouté** à ces échecs et, suivant la règle « pas de suppression/modification brutale », je ne les
ai pas touchés.

---

## 8. Miroir vérifié

Les 24 fichiers ont été copiés dans ton repo `C:\Users\flo\Desktop\Projet invest` et vérifiés
**identiques octet par octet** (hash combiné `193ca3a5…` identique des deux côtés). L'archive de
transport a été déposée dans `_to_delete\_mirror_launcher.tgz` — tu peux supprimer ce dossier.
**Je n'ai pas fait `git push`** (c'est toi qui pousses).
