# OBJECTIF CODEX — Réparer les problèmes des logs + continuer la V9 (Hyperliquid, paper-only)

> Colle ce fichier entier dans le champ *Objectif / Goal* de Codex.
> Traite les tâches **dans l'ordre, une par une**. Après CHAQUE tâche : tests verts + mini-preuve, sinon corrige avant de continuer.
> **Maître du projet : `docs/HYPERSMART_FUSION_ROADMAP_V9.md`.** Ce prompt sert les problèmes des logs réels + la suite V9.

---

## 0. RÈGLES ABSOLUES (sécurité — jamais contourner)

```
PAPER-ONLY · READ-ONLY · DENY-BY-DEFAULT · TESTNET-FIRST
0 ordre réel · 0 argent réel · 0 clé privée · 0 seed/mnemonic · 0 signature · 0 dépôt/retrait · 0 wallet connect · 0 API privée de trading
execution="forbidden" PARTOUT. Conserver tout assert_paper_only / garde-fou existant.
AUCUNE démo, AUCUNE donnée synthétique/fabriquée. Pas de données -> état vide honnête. Donnée douteuse/vieille/incomplète -> NO_TRADE.
Un signal n'est jamais un ordre. Un paper-trade n'est jamais un ordre. Jamais de promesse de PnL, jamais de chiffres maquillés.
Scraping public + proxy/rotation = AUTORISÉS (cf. AGENTS.md et V9 §8). Aucune catégorie "interdit" sur les outils de collecte.
Ne pas supprimer le legacy. Ne pas pousser/committer/reset sans demande explicite.
```

Sur ta machine Windows tu peux éditer les gros fichiers (`routes.py` ~3700 l., `cli.py` ~3000 l.). Fais des **edits chirurgicaux + tests** ; relance `python -m hl_observer --help` après pour prouver que l'import ne casse pas.

---

## 1. CONTEXTE — diagnostic chiffré du ledger réel

Analyse de `logs/logs à envoyer/simulation_decisions_append_only.jsonl` (session 2026-06-19, ~3 h) :
**9154 décisions, 0 acceptée.** Tokens de refus : `NO_MATCHING_PAPER_POSITION_FOR_CLOSE` 4599 · `COPY_DEGRADATION_TOO_HIGH` 4481 · `EDGE_REMAINING_TOO_LOW` 4356 · `SINGLE_WALLET_EDGE_TOO_LOW` 3317 · `STALE_SIGNAL` 3172 · `LIQUIDITY_TOO_LOW` 2921 · `PRICE_DEVIATION_TOO_HIGH` 1167 · `UNKNOWN_DELTA` 74.

### Liste EXHAUSTIVE de ce qui ne va pas dans les logs
1. **0 acceptation** sur 9154 décisions (le bot n'entre jamais).
2. **Leaders surtout ADD/REDUCE** : 4472 ADD + 4587 REDUCE, **9 OPEN seulement**. Avec `ALLOW_ADD_AS_ENTRY=0`, presque rien sur quoi entrer.
3. **50 % de bruit** : 4599 `NO_MATCHING_PAPER_POSITION_FOR_CLOSE` = on logge les REDUCE/CLOSE du leader alors qu'on n'a aucune position correspondante.
4. **Backfill rejoué comme "live"** : `signal_age_ms` médian 11 s, p90 **8,6 h**, max **15,5 h** ; 13 % > 1 h. Ces vieux fills déclenchent `STALE_SIGNAL` + une dégradation aberrante.
5. **Dégradation aberrante** : `copy_degradation_bps` max **1456 bps (14,6 %)** (mouvement de prix adverse car le fill a des heures).
6. **edge non calculable** : `edge_remaining_bps` = sentinelle **-9999** pour ~50 % des lignes (les REDUCE/CLOSE) ; edge>0 seulement 10 % ; edge≥35 bps seulement 125 fois.
7. **Re-scoring de doublons** : 744 redites ; un même fill (`XYZ:TSLA REDUCE`) scoré jusqu'à **51×** (dédup inter-poll défaillante).
8. **Mauvais marchés** : **56 coins sur 229** sont des perps HIP-3/RWA/builder/spot (`XYZ:TSLA`, `CASH:WTI`, `HYNA:BTC`, `@107`, `#2160`, `CASH:GOOGL`…) — pas des perps crypto liquides.
9. **`consensus_wallets`** souvent = 1 (7455/9080) → `SINGLE_WALLET_EDGE_TOO_LOW` avec un seuil trop haut.

### Déjà corrigé par Claude (NE PAS refaire, vérifier seulement)
- `LANCER_HYPERSMART.cmd` recalibré : `ALLOW_ADD_AS_ENTRY=1`, `MAX_SIGNAL_AGE_MS=30000`, `MIN_EDGE_BPS=10`, `SINGLE_WALLET_MIN_EDGE_BPS=15`, `MIN_LIQUIDITY_SCORE=0.3`, `MAX_COPY_DEGRADATION_BPS=22`. (Replay sur le log : ~198 signaux propres passeraient vs 0.)
- `src/hl_observer/markets/universe.py::is_exotic_market(coin)` + `build_market_universe` l'applique ; `MarketUniverseSettings.include_builder_and_rwa_perps=False` par défaut. Test : `tests/test_market_universe_exotic_filter.py` (vert).
- Dashboard `simulation_v2.html` : anti-saut (#decisions/#scan écrits seulement si changé), badge online/offline piloté uniquement par `/api/simulation/status`, timeout status 8 s.

---

## 2. TÂCHES DE RÉPARATION (ordre strict, 1 par 1, chacune avec test + preuve)

### T1 — Supprimer le code DÉMO / wallets synthétiques (viole la règle no-demo)
Commits fautifs : `332c055` (demo seed shortlist), `ba6266e` (per-cluster demo detection / bypass gates synthétiques), `6502fab` (demo PnL), `04a6d27` (LEADER_EXIT désactivé pour positions démo).
- Dans `hyper_smart_observer/dydx_v4/engine.py` : retirer l'injection `_build_demo_wallets()` au démarrage et `self._observer._demo_mode=True`.
- Dans `hyper_smart_observer/dydx_v4/live_observer.py` et `wallet_discovery.py` : retirer `_demo_mode`, `demo_synthetic`, le bypass de gates pour wallets synthétiques.
- Garder `dydx_v4/` **dormant et honnête** (aucune donnée inventée). Si la découverte échoue → shortlist vide + log honnête, jamais de wallet démo.
- **Test** : `tests/test_no_demo_wallets.py` — asserter qu'aucune fonction runtime ne fabrique de wallet/position/PnL synthétique ; grep `demo_synthetic` = 0 hors tests.
- **DoD** : `grep -rni "demo_synthetic\|_build_demo_wallets\|_demo_mode" hyper_smart_observer src | grep -v test` → vide ou inerte.

### T2 — Appliquer `is_exotic_market` DANS la boucle de copie (pas seulement la découverte)
Problème #8 : un wallet suivi qui trade `XYZ:TSLA` fait quand même scorer le fill.
- Dans `src/hl_observer/ui/routes.py`, boucle de copie (~ligne 737, là où on teste déjà `row.coin.upper() in excluded_coins`) : ajouter `from hl_observer.markets.universe import is_exotic_market` et **skip** (continue, sans logguer de décision) si `is_exotic_market(row.coin)` et non `settings.market_universe.include_builder_and_rwa_perps`.
- Idem dans le chemin `cli.py copy-run` s'il score des fills.
- **Test** : un fill `XYZ:TSLA` / `@107` ne produit aucune décision ; un fill `BTC` est traité.
- **DoD** : rejouer le log → 0 décision sur coins exotiques.

### T3 — Fraîcheur à la SOURCE : ne pas scorer les fills trop vieux (anti backfill rejoué)
Problème #4 : on score des fills vieux de plusieurs heures.
- Avant le scoring, calculer l'âge réel du fill (timestamp du fill vs maintenant). Si âge > `2 × MAX_SIGNAL_AGE_MS` (cap dur, ex. 60 s) → **skip sans logguer** (ce n'est pas un signal live, c'est de l'historique).
- Ne JAMAIS traiter un backfill REST comme un signal d'entrée : le backfill sert à reconstruire l'état des positions, pas à générer des signaux.
- **Test** : un delta d'âge 5 h → ignoré (aucune décision) ; un delta d'âge 3 s → scoré.
- **DoD** : plus aucune ligne de décision avec `signal_age_ms` > 60000.

### T4 — Déduplication persistante par identité de fill (anti re-scoring 51×)
Problème #7 : `simulation_delta_identity(row)` + `processed_keys` est par appel (reset à chaque poll) → les mêmes fills re-poll sont re-scorés.
- Persister les identités de fills déjà traitées (table SQLite `processed_fills` OU un curseur `last_processed_fill_ts` par wallet) pour ne scorer chaque fill **qu'une seule fois**, même entre deux polls.
- **Test** : rejouer 2× le même fill → 1 seule décision.
- **DoD** : sur un run, 0 doublon (1 décision par identité de fill distincte).

### T5 — Supprimer le bruit REDUCE/CLOSE sans position
Problème #3 : 50 % des lignes = `NO_MATCHING_PAPER_POSITION_FOR_CLOSE`.
- Dans la boucle : si action ∈ {REDUCE, CLOSE_*, UNKNOWN} ET aucune position paper ouverte ne matche `(wallet, coin, side)` → **skip sans écrire de décision NO_TRADE**.
- Ne traiter REDUCE/CLOSE que lorsqu'on détient la position correspondante (pour simuler la sortie paper).
- **Test** : REDUCE sans position → aucune décision ; REDUCE avec position paper ouverte → sortie paper simulée + 1 décision.
- **DoD** : `NO_MATCHING_PAPER_POSITION_FOR_CLOSE` n'apparaît plus dans le ledger.

### T6 — Aligner les défauts de code sur la calibration (robustesse)
- Dans `src/hl_observer/ui/routes.py` (et `cli.py`), les défauts lus si l'env est absent valent encore 25 / 30000 / 0.35 / 18 / 30. Les aligner sur la calibration validée (10 / 30000 / 0.3 / 22 / 15) tout en gardant l'override par variable d'environnement.
- **Test** : sans variables d'env, `RealtimeCopyRiskConfig` runtime reflète les valeurs calibrées.
- **DoD** : comportement identique que l'env soit posé ou non.

### T7 — Preuve de bout en bout (obligatoire)
- Après T1→T6 : lancer le moteur quelques minutes en read-only paper (vraies données Hyperliquid) OU rejouer le dernier ledger via l'outil de backtest/replay.
- Produire des chiffres AVANT/APRÈS : nb décisions, **nb acceptées (>0 attendu)**, répartition des refus (le bruit doit s'effondrer), 0 coin exotique, 0 âge > 60 s, 0 doublon.
- **Interdit** : forcer des entrées ou inventer des données pour faire monter le compteur. Si 0 signal propre sur la fenêtre, l'afficher honnêtement.

---

## 3. CONTINUER LA V9 (après les réparations)

Suivre `docs/HYPERSMART_FUSION_ROADMAP_V9.md`, slices dans l'ordre §6, chacune = modules neufs + tests + porte de sécurité + DoD :
- **S2bis déjà amorcé** (`collection/proxy_pool.py`, `weight_budgeter.py`, `scanner/throughput_planner.py`) : compléter le client REST `/info` paginé+dédupliqué, le superviseur WS (reconnect/gap-recovery/heartbeat/cap-10) et le rate-limiter par egress.
- **S4** features (OBI, CVD, RVOL, anchored-VWAP, fair-value, scan_features, quality-mode), **S5** scoring smart-money + copy_fidelity, **S6** signaux whale-fill + edge net + no-trade, **S7** risque (VaR/CVaR, loss-halts, calibration Brier), **S8** PaperEngine mark-to-market + lifecycle, **S9** backtest/replay + parité, **S10** dashboard/evidence, **S11** CLI/docs/audit.
- Respecter les 16 tests obligatoires (V9 §4) : REST mock, WS mock, reconnect, gap recovery, dedupe, pagination, lifecycle OPEN/ADD/REDUCE/CLOSE, stale refusé, edge faible refusé, liquidité faible refusée, PnL long/short, fees non doublés, séparation LIVE/BACKTEST/REPLAY/TEST_FIXTURE, dashboard read-only, config safe, 0 ordre réel.

---

## 4. VÉRIFICATION FINALE + RAPPORT (français, obligatoire)

À la fin, fournir :
1. **Fichiers modifiés/créés** (liste).
2. **Problèmes des logs corrigés** (T1→T6) avec, pour chacun, la preuve chiffrée AVANT/APRÈS.
3. **Tests lancés** : `python -m pytest -q` (et le sous-ensemble ciblé) — coller le résumé (X passed).
4. **Limites restantes** + prochaines slices V9.
5. **Confirmation sécurité** : `0 ordre réel, 0 argent réel, 0 clé privée, 0 signature, 0 dépôt/retrait, 0 démo`.

**Definition of Done globale** : sur une vraie session courte, le ledger montre **au moins quelques acceptations paper sur des perps crypto liquides**, le bruit (close-sans-position, backfill, doublons, coins exotiques) a disparu, tous les tests passent, et la simulation reste 100 % paper/read-only.

---

## 2bis. POURQUOI LE MOTEUR N'OUVRE TOUJOURS AUCUNE POSITION — PRIORITÉ (preuve écran 2026-06-19 18:29)

Run APRÈS calibration (moteur **actif**, tick réel, dashboard OK) mais **0 entrée paper** :
- **967895 candidats vus · 2 deltas frais/récents · 0 entrée paper · 1000 refus.**
- Décisions : *fermeture sans position* **226×**, *copie trop dégradée* 14×, *gain trop faible vs frais* 28×, *signal trop vieux* 13×, *marché pas assez liquide* 10×, *max exposure reached* 8×, *prix trop éloigné* 8×.
- Flux marché : des trades vus mais **0 signal**.

**Diagnostic** : le moteur est SAIN — il est **affamé de signaux d'ENTRÉE frais**. Sur ~968k candidats, seulement **2** sont frais ; le reste est du backfill (surtout des REDUCE/CLOSE sans position). Il n'ouvre rien car il n'y a quasi aucun OPEN/ADD **frais + liquide + edge net positif** sur les ~30 wallets suivis. Ce n'est PAS un seuil isolé : c'est l'OFFRE de signaux d'entrée qui est quasi nulle (+ le bruit backfill qui noie le pipeline).

### T8 — Augmenter l'OFFRE de signaux d'ENTRÉE frais (sans fake, sans forcer)
1. **Tarir le backfill dans le flux de candidats** (lié à T3/T4) : « candidats vus » doit compter des deltas FRAIS, pas 968k d'historique. N'injecter comme candidats que les fills frais (≤ fenêtre) ET nouveaux (dédupliqués). Le backfill sert à reconstruire l'état des positions, jamais à générer des signaux.
2. **Élargir les wallets suivis** : faire tourner découverte/leaderboard/`collect-all` dans le temps pour passer de ~30 à plusieurs centaines de leaders scorés. Plus de leaders = plus d'OPEN/ADD frais. Lever le plafond de shortlist s'il est bridé par un artefact de process (cf. mémoire « 30 wallets »).
3. **WS userFills sur les leaders chauds** (cap 10 users) : capter les fills frais en temps réel, pas seulement les diffs de snapshots REST entre deux polls — sinon on rate les entrées intra-poll.
4. **Vérifier le chemin ADD-as-entry** : un ADD frais d'un leader, quand on est flat, DOIT pouvoir ouvrir une position paper (env `ALLOW_ADD_AS_ENTRY=1` déjà posé ; vérifier que le code l'honore réellement).
5. **(Option, flag désactivable) Mode copie d'état « miroir »** : à la 1re observation FRAÎCHE d'un leader déjà en position, autoriser l'ouverture paper miroir **uniquement si** prix courant proche du prix moyen du leader (déviation faible), liquidité OK, edge net positif — toutes les gates s'appliquent. On copie une position réelle existante : ce n'est pas de la donnée inventée.
6. **Diagnostic par cycle (obligatoire)** : logguer combien de deltas d'ENTRÉE FRAIS (OPEN/ADD) ont été vus, combien acceptés/refusés et pourquoi. Objectif : distinguer « peu d'entrées fraîches » (offre) de « gates trop strictes » (filtre).

**DoD T8** : sur une session courte, `deltas frais` >> 2 ET au moins quelques entrées paper sur perps crypto liquides. Si l'offre reste insuffisante, l'AFFICHER honnêtement et recommander d'élargir les wallets — **JAMAIS forcer une entrée ni inventer un signal**.

> Ordre conseillé révisé : **T1 → T5 (nettoyage du bruit/backfill) → T8 (offre de signaux frais) → T6 → T7 (preuve) → §3 (suite V9)**. T8 est le verrou qui fait réellement ouvrir des positions.

---

## MISE À JOUR (module fourni — à BRANCHER, ne pas réécrire)

`src/hl_observer/signals/fill_admission.py` implémente déjà, en module PUR et testé
(`tests/test_v9_fill_admission.py`, 11 verts), la "porte d'entrée" qui consolide T2+T3+T4+T5+T8 :

```python
from hl_observer.signals.fill_admission import admit_live_fill, fill_identity, FillAdmissionConfig

adm = admit_live_fill(
    action_type=row.action_type, coin=row.coin,
    fill_ts_ms=fill_ts, now_ms=now_ms,
    already_seen=(fid in seen),            # seen = set persistant d'identités (T4)
    has_matching_paper_position=has_pos,   # état des positions paper (T5)
    leader_price=row.leader_price,
    config=FillAdmissionConfig(max_signal_age_ms=..., allow_add_as_entry=..., allow_exotic_markets=...),
)
if not adm.admit:
    if adm.log_decision: ledger.write(...)   # rare (ex: PRICE_INVALID)
    continue                                  # skip silencieux: backfill/doublon/exotique/close-sans-position
# adm.kind == "ENTRY" -> scorer l'entrée ; "EXIT" -> simuler la sortie paper
```

**À faire pour Codex** : dans la boucle de copie de `src/hl_observer/ui/routes.py`, remplacer la logique
ad hoc par un appel à `admit_live_fill(...)`, maintenir le set `seen` en base (table `processed_fills`
via `fill_identity(...)`) pour la dédup persistante (T4), et n'écrire au ledger que si `adm.log_decision`.
Cela supprime d'un coup le bruit (backfill, doublons, exotiques, close-sans-position) et ne garde que les
ENTRÉES/SORTIES fraîches — exactement ce qui fait passer le moteur de "1000 refus / 0 entrée" à des entrées propres.
