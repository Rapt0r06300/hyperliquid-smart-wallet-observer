# HyperSmart V14 — Méga-roadmap SCAN / SCRAPING / FRAÎCHEUR / TIMING D'ENTRÉE

> Recherche profonde dans le **code** des 14 GitHub (pas seulement READMEs), centrée sur
> « entrer dans de bonnes positions, au bon moment ». Tout reste **gratuit, paper-only,
> read-only, 0 ordre réel**. Objectif : moins de trades mais frais, liquides, edge net positif.

## Ce que le code des repos nous apprend (pépites scan/scrape/timing)

### mlmodelpoly (collector + ws_client lus en entier)
- **Souscription WS combinée** : un seul socket `/stream?streams=a/b/c` ; flux par symbole :
  aggTrade, bookTicker, markPrice, **forceOrder (LIQUIDATIONS)**, depth@100/500ms ; **Futures+Spot**.
- **Reconnect backoff** [1,2,5,10,30], ping 20s/timeout 10s, max msg 10 Mo, **anti-backpressure**
  (queue avec timeout → warn), **horodatage recv_ts_ms** (note NTP pour latence exacte).
- **Bootstrap contexte HTF** au démarrage (1m/5m/15m/1h, 500 bars) + **garde warmup**
  `CONTEXT_MIN_READY_BARS=200` (ne pas décider avant que le contexte soit prêt).
- **Exécutabilité réelle** : `MIN_TOP1_USD=20`, `MIN_TOP3_USD=60`, `MIN_DEPTH=200`, tiers de
  spread `DEGRADED=400 / BAD=800 bps`, `EDGE_BUFFER_BPS=25`.
- **Cadence** : slow-loop 1 s, **cooldown 2 s**, **budget par fenêtre** 30 slices / 300 USD.
- **forceOrder** = signal de liquidation → cascades = points d'entrée frais. **`record` events** pour rejeu.

### Harrier
- **On-Chain Whale Signal 3–30 s d'avance** (sub blocs + décode calldata) → chez nous : le
  **firehose de fills WS** doit être la SOURCE D'ENTRÉE PRIMAIRE (détecter l'OPEN avant l'API lente).
- **OBI rafraîchi ~500 ms**, **polling position ~200 ms/wallet**, **sémaphore 25 req/10 s**.

### Polymarket/agents
- **Découverte marchés triée par VOLUME** (`get-all-markets --sort-by volume`) → prioriser les
  marchés liquides. Connecteurs qui **normalisent** + Pydantic strict (refus à la frontière).

### polybot
- **ingestor-service** = ingestion continue market/user-trade ; **replication & similarity scoring**.

### Composio / PolyWeather / polyrec
- **Fenêtre de démarrage** (n'évaluer qu'après N s) + late-resolution (Composio).
- **SSE patches + replay**, couches de sources officielles, ancres de règlement (PolyWeather).
- **Fusion multi-sources** oracle+exchange+book + 70 colonnes + **eat-flow** (polyrec).

## Gap vs notre stack (on a déjà : scanner/, collection/proxy+rate_limiter, explorer/, freshness/, wallets/, realtime/, signals/whale_fill_signal)
Manque ou non câblé : flux liquidations, whale-fill en source PRIMAIRE, correction d'horloge,
garde warmup, souscription combinée+anti-backpressure auditée, découverte par volume, fusion
multi-sources wallets dédupliquée, fenêtre consensus chaude, sémaphore+proxy santé câblés,
seuils top1/top3 + tiers spread, OBI/eat-flow dans le scoring, cadence+cooldown+budget fenêtre,
enregistrement d'événements, et la **promotion live** des briques V13 (exec-cost/smart-money/
depth-guard/maker/deb/emos/features).

## Méga-roadmap = étapes #166→#185 (voir progression)
Axes : A) signaux frais & timing ; B) découverte marchés/wallets (scan/scrape) ; C) anti-ban/
débit/proxy ; D) microstructure fraîche ; E) cadence & budget ; F) promotion des briques V13.
Chaque étape : shadow d'abord, gardée, testée, 0 ordre réel.

## Avancement 2026-06-25 — #166→#170 FAITS (purs, testés, shadow-first)

Tout **gratuit, paper-only, read-only, 0 ordre / 0 clé / 0 signature**. Modules purs,
branchés en SHADOW (flags OFF par défaut), 15 tests verts (`tests/test_v14_freshness_timing.py`).

- **#166 `realtime/freshness_audit.py`** — audit de fraîcheur bout-en-bout : latence par
  étage (capture exchange→recv, compute recv→décision, total) + **histogramme d'âge**
  (buckets ≤1s/2s/4s/8s/15s/30s/>30s) avec ratio frais / ratio périmé + statut OK/SOME_STALE/
  MOSTLY_STALE. `build_freshness_audit_from_events/_from_logs` lisent les décisions locales.
- **#167 `signals/liquidation_signal.py`** — cascade de LIQUIDATIONS comme déclencheur frais :
  agrège les forced-orders récents d'un coin, déduit le côté dominant liquidé, expose
  `momentum_side`/`reversion_side`/`trigger_side` (mode reversion|momentum), `is_fresh_trigger`
  + force 0..1. SHADOW (le flux live de liquidations sera câblé avec la souscription WS combinée #171).
- **#168 `signals/whale_primary_gate.py`** — promotion du signal whale-fill en SOURCE D'ENTRÉE
  PRIMAIRE. Câblé dans `routes.opportunity_metrics`, flag `HYPERSMART_V14_WHALE_PRIMARY_AUTHORITATIVE`
  (défaut 0). Intersection plus stricte : refuse une entrée acceptée si pas de whale primaire ;
  ne peut QUE réduire les trades ; `None` (inconnu) ne bloque jamais.
- **#169 `realtime/clock_offset.py`** — correction d'horloge pour un `signal_age` exact :
  estimateur NTP (offset = médiane des θ sur les échantillons à plus faible délai) + repli
  one-way **borné et marqué non fiable** (jamais utilisé pour rajeunir un signal). 
  `corrected_signal_age_ms` n'applique que l'estimation NTP de confiance.
- **#170 `signals/warmup_guard.py`** — garde de warmup : `warmup_status` (prêt si chaque TF a
  ≥ `min_ready_bars`=200 et features prêtes) + promotion `HYPERSMART_V14_WARMUP_AUTHORITATIVE`
  (défaut 0). Câblée dans `routes` en no-op tant que les bars HTF ne sont pas plumbés (sans danger).

**Reset des logs (demande 2026-06-25)** : `runtime/session_logs.py::purge_stale_top_level_logs`
vide les gros `*.log` (tronqués à 0), supprime les archives lourdes `*.zip/.7z/.rar` et le dossier
mojibake, **préserve les DB SQLite** et surtout **n'effleure jamais `runtime/`** (modèle IA +
`training_samples.jsonl` = l'intelligence). Appelé à chaque lancement via
`prepare-simulation-logs --purge-top-level`. La boucle IA (`tools/ia_train_loop.ps1`) repart aussi
d'une trace vierge à chaque ouverture, sans toucher au modèle entraîné.
