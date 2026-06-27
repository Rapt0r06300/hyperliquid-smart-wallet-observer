# Reprise Codex HyperSmart V9 - 2026-06-21

## Etat du run

Roadmap relue et appliquee partiellement dans ce run :

- `AGENTS.md`
- `docs/HYPERSMART_FUSION_ROADMAP_V9.md`
- `docs/CODEX_HYPERSMART_MASTER_PLAN_V7_ACTION_BOUNDARY.md`

Ligne de conduite conservee :

- runtime officiel : Hyperliquid uniquement ;
- simulation locale paper uniquement ;
- donnees marche reelles uniquement ;
- aucune donnee fake, aucun fake PnL, aucun fake chart ;
- aucune action externe reelle ;
- aucun `/exchange`, aucun ordre reel, aucune cle privee, aucune signature, aucun wallet connect.

## Corrections livrees

### Pipeline paper V9

Fichier principal :

- `src/hl_observer/copying/v9_paper_pipeline.py`

Corrections :

- `ADD` / `INCREASE` n'ecrasent plus une position existante.
- Les ajouts augmentent le notional et recalculent un prix d'entree moyen.
- `REDUCE` ne ferme plus toute la position.
- `REDUCE` applique une reduction partielle via `reduce_fraction`, `close_fraction` ou `leader_reduce_fraction`.
- Si aucune fraction n'est fournie, le pipeline applique `default_reduce_fraction=0.5`.
- `CLOSE_LONG` / `CLOSE_SHORT` restent des fermetures completes.
- Le resultat expose maintenant `reduces_applied`.
- Les decisions paper contiennent maintenant :
  - `simulation_only=true`
  - `read_only=true`
  - `external_action=false`
  - `execution=forbidden`
  - `venue_endpoint=null`
  - `secret_material_used=false`
  - `raw_event_hash`
  - `paper_ref`
  - `evidence_hash`

Objectif : rendre le PnL et la position paper plus fideles a un suivi leader : ajouter quand le leader ajoute, reduire quand le leader reduit, fermer quand le leader ferme.

### Tests pipeline V9

Fichier :

- `tests/test_v9_paper_pipeline.py`

Tests ajoutes :

- `test_add_increases_position_without_resetting_entry`
- `test_reduce_partially_closes_and_keeps_remaining_position`
- `test_decisions_are_readonly_evidence_chained`

### Launcher et calibration

Fichiers :

- `LANCER_HYPERSMART.cmd`
- `tools/start_hypersmart_simulation.ps1`
- `src/hl_observer/copying/realtime_magic_score.py`

Corrections :

- Le launcher revient au contrat teste : `-MaxLeaders 50`.
- `HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS=22`.
- Le script affiche explicitement `Nouvelle session simulation`.
- La boucle public trade revient a `PublicTradeMaxCoins=60` et `PublicTradeMaxWallets=10000`.
- La configuration par defaut de `RealtimeCopyRiskConfig` est alignee avec les constantes V9 :
  - min edge : `10 bps`
  - max age : `30000 ms`
  - min liquidity : `0.30`
  - single wallet min edge : `15 bps`
  - max copy degradation : `22 bps`
  - max price deviation : `18 bps`

## Tests et audits executes

Resultats :

- `python -m pytest -q tests/test_v9_paper_pipeline.py`
  - `10 passed`
- bloc V9/paper/safety cible :
  - `235 passed`
- suite complete :
  - `1431 passed, 15450 warnings`
- `python -m hyper_smart_observer.app.main --safety-check`
  - `Safety check: OK`
- `python -m hyper_smart_observer.app.main --audit-safety`
  - OK sur no `/exchange`, no signature, no ordre operationnel, no private key config, dashboard read-only, mainnet forbidden, testnet disabled.
- `python -m hyper_smart_observer.app.main --runtime-check`
  - OK avec warning connu : legacy `logs/hl_observer.sqlite3` detecte et exclu des archives.
- `python -m hyper_smart_observer.app.main --archive-audit`
  - rapport genere : `docs/release/HYPERSMART_ARCHIVE_AUDIT.md`

## Ce qui reste a faire

La roadmap V9 n'est pas terminee. Prochaine priorite exacte :

1. Brancher les nouvelles decisions `PAPER_INCREASE` / `PAPER_REDUCE` enrichies jusqu'au dashboard de simulation officiel.
2. Verifier que `/api/simulation/status` et `/api/simulation/overview` exposent clairement :
   - position notional restante ;
   - average entry ;
   - reduce fraction ;
   - realized/unrealized PnL par position ;
   - evidence hash ;
   - raison de refus dominante.
3. Ajouter une QA navigateur longue duree sur `simulation_v2.html` :
   - pas de saut visuel ;
   - metagraphe fluide ;
   - statut de scan stable ;
   - PnL/equity coherent avec les positions ouvertes.
4. Relier les reductions proportionnelles du pipeline V9 au PaperEngine runtime si le runtime principal utilise encore un chemin different de `v9_paper_pipeline`.
5. Continuer la roadmap V9 sur :
   - collecte read-only plus robuste ;
   - source health ;
   - lifecycle complet ;
   - evidence_chain unifiee ;
   - backtest/replay parity vs runtime ;
   - dashboard no-fake-data.

## Commande de reprise conseillee

Coller a Codex :

```text
Travaille dans C:\Users\flo\Desktop\Projet invest.
Relis AGENTS.md, docs/HYPERSMART_FUSION_ROADMAP_V9.md,
docs/CODEX_HYPERSMART_MASTER_PLAN_V7_ACTION_BOUNDARY.md et
docs/release/CODEX_REPRISE_HYPERSMART_V9_20260621.md.
Continue la roadmap V9 a partir de la prochaine priorite exacte :
brancher PAPER_INCREASE/PAPER_REDUCE/evidence_hash jusqu'au dashboard officiel,
verifier /api/simulation/status et /api/simulation/overview, puis faire une QA navigateur
longue duree de simulation_v2.html sans creer de deuxieme simulation.
Garde Hyperliquid read-only + paper local uniquement, donnees reelles seulement,
aucun ordre reel, aucune cle, aucune signature, aucun /exchange.
```

