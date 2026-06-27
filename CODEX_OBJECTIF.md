# OBJECTIF CODEX — HyperSmart Observer (dYdX v4, paper-only)

> **Mode d'emploi.** Colle ce fichier entier dans le champ *Goal / Objectif* de Codex.
> Il sert à la fois de prompt de départ ET de critère de fin : Codex doit traiter les
> phases **dans l'ordre, une par une**, et ne s'arrête que quand la VÉRIFICATION FINALE
> (Phase 6) passe. Tu peux aussi lui dire « fais la Phase 1 », valider, puis « fais la Phase 2 ».

---

## RÈGLES GLOBALES (non négociables — valent pour TOUTES les phases)

1. **SÉCURITÉ ABSOLUE (verbatim, ne jamais contourner) :** READ-ONLY, PAPER-ONLY,
   TESTNET-FIRST, DENY-BY-DEFAULT. **0 ordre réel, 0 argent réel, 0 clé privée, 0 seed,
   0 mnemonic, 0 signature, 0 dépôt/retrait, 0 wallet connect, 0 appel d'API privée de
   trading.** Tu n'ajoutes JAMAIS de code qui signe, envoie une transaction, ou détient
   une clé. Un signal n'est jamais un ordre ; un paper-trade n'est jamais un ordre.
   `run()` doit conserver son `assert_paper_only(self.config)` au début.
2. **Une phase à la fois, dans l'ordre.** À la fin de CHAQUE phase :
   `python -m pytest tests/dydx_v4/ -q`. Si c'est rouge, tu corriges AVANT de passer à
   la phase suivante. Tu ne déclares jamais une phase « faite » avec des tests rouges.
3. **Additif et gardé.** Toute nouveauté est derrière un flag de config (défaut sûr) et
   un `try/except` : si une dépendance manque ou si le réseau échoue, le moteur continue
   normalement. Tu ne casses jamais les chemins existants (REST, stream, flux de marché).
4. **Lis avant d'écrire.** Avant de modifier un fichier, tu le lis. Tu **imites les
   patrons déjà présents** (style, dataclasses, `from __future__ import annotations`,
   docstrings FR). Tu ne réécris pas ce qui marche.
5. **Les numéros de ligne ci-dessous sont indicatifs (état au 2026-06-13).** Ils bougent
   quand tu édites : repère toujours par **nom de symbole** (grep), pas par numéro.
6. **Ne touche pas** au code legacy Hyperliquid (`src/hl_observer/...` côté moteur HL).
   Tu peux éditer l'UI `src/hl_observer/ui/static/simulation_v2.html` (c'est l'écran dYdX).
7. **Si une précondition est fausse** (symbole introuvable, signature différente de ce qui
   est décrit), tu **t'arrêtes et tu le signales** dans le rapport — tu ne devines pas.
8. **Périmètre fermé.** N'élargis pas au-delà de ces 6 phases sans demander. Pas de
   nouvelle stratégie « créative » : tu câbles, tu fiabilises, tu testes.

### Carte du code (vérifiée)
- Moteur : `hyper_smart_observer/dydx_v4/live_observer.py`
  - `class DydxLiveObserver`, `__init__` (~256), bloc init full-node-stream (~373‑402),
    `run()` (~408) avec démarrage thread stream (~437‑444) et boucle principale (~447‑507 ;
    appel `_process_stream_consensus()` ~480), `_refresh_market_prices` (~620),
    `get_status()` (~812 ; bloc stats `status["stream"]` ~853‑862),
    `_poll_shortlist_live()` (~869 ; **cap `self._shortlist[:50]` ~877**),
    `_process_stream_consensus()` (~1014), `_evaluate_cluster()` (~1126, gates 0→8),
    `stop()` (~1539). Constante `FOCUS_MARKETS` (~86). Dict `self._mark_prices` (~301).
    Gate 1 : `self.focus_markets` vide ⇒ tous marchés autorisés. origin=="stream" saute
    la gate « proven » (3b) et la gate « edge » (7).
- Config : `hyper_smart_observer/dydx_v4/config.py` — dataclass `DydxV4Config`
  (flags ~130‑193) + `load_config_from_env()` (~246) qui reconstruit via `_bool/_int/_float`.
  Déjà présents : `consensus_min_wallets=2`, `fast_scanner_enabled=False`,
  `fast_scanner_hot_capacity=500`, `max_decision_wallets=250`,
  `stream_consensus_min_wallets=1`, `stream_window_ms=8000`, `require_proven_leaders=False`.
- WS : `hyper_smart_observer/dydx_v4/ws_client.py` — `DydxIndexerWsClient(ws_url, on_message=cb, …)`,
  `subscribe_trades(market_id)`, `start()`, `stop()`. Le callback `on_message` **est bien
  appelé** sur chaque message (l.290). `WsMessage` a `.channel`, `.type`, `.id`, `.data`
  (= `contents`). Pour `v4_trades`, `.data == {"trades":[...]}`.
- Signal : `hyper_smart_observer/dydx_v4/cluster_detector.py` — `class ClusterSignal`
  (champs : market_id, side, wallet_count, participating_wallets, total_notional_usdc,
  first_wallet_opened_ms, last_wallet_opened_ms, signal_age_ms, avg_entry_price,
  signal_strength, market_priority, is_fresh, cluster_id, detected_at_ms=…, origin="rest").
- Flux de marché (déjà créé, **vérifié correct**, à câbler) :
  `hyper_smart_observer/dydx_v4/market_flow.py` — `MarketFlowMonitor(ws_url, markets, window_ms)`,
  `.start()/.stop()`, `.drain_and_detect(min_volume_usdc, min_imbalance) -> list[FlowSignal]`,
  `.stats` (`trades_seen`/`signals`), `build_cluster_from_flow(signal, mark_price, now_ms)`
  (renvoie un `ClusterSignal(origin="stream")` — signature déjà conforme).
- Scan wallets : `fast_scanner.py`, `fast_scan_integration.py`, `wallet_harvester.py`,
  `cosmos_client.py`. Risque : `risk_policy.py` (anti-churn, coupe-circuit, anti-scalper).
  Exits/fills : `paper_fill.py`, `_build_position_exit_plan`/`_check_exits` dans l'observer.
- UI : `src/hl_observer/ui/static/simulation_v2.html` (lit `/api/dydx/status|positions|wallets`).
- Tests : `tests/dydx_v4/` (imite `test_stream_consensus.py` pour le style des tests WS/fenêtre).

---

## PHASE 1 — Câbler le flux de marché `market_flow.py` (priorité n°1)

**Pourquoi.** `v4_trades` diffuse TOUS les trades publics en temps réel, sans node et sans
abonnement par wallet. C'est le flux le plus massif et le plus fiable pour générer des
signaux momentum et faire **enfin bouger** la simulation, tout en restant READ-ONLY.

**Le module `market_flow.py` est déjà écrit et vérifié conforme aux vraies API.** Il ne
reste qu'à le brancher, en miroir exact du câblage de `_process_stream_consensus`.

**Étapes précises :**
1. **`config.py`** — ajoute 3 champs dans `DydxV4Config` (juste après `stream_window_ms`) :
   ```python
   market_flow_enabled: bool = True            # DYDX_MARKET_FLOW
   market_flow_min_volume_usdc: float = 25000  # DYDX_MARKET_FLOW_MIN_VOLUME
   market_flow_min_imbalance: float = 0.60     # DYDX_MARKET_FLOW_MIN_IMBALANCE
   ```
   et 3 lignes correspondantes dans `load_config_from_env()` (après celle de
   `stream_window_ms`), en respectant `_bool/_int/_float`.
2. **`live_observer.py` `__init__`** — juste après le bloc d'init full-node-stream
   (après `self._stream_client = …`, ~l.402), ajoute :
   ```python
   self._flow_monitor = None
   if getattr(config, "market_flow_enabled", False):
       try:
           from hyper_smart_observer.dydx_v4.market_flow import MarketFlowMonitor
           self._flow_monitor = MarketFlowMonitor(
               config.indexer_ws_url, list(FOCUS_MARKETS),
               window_ms=getattr(config, "stream_window_ms", 8000),
           )
           logger.info("market_flow ARMÉ (v4_trades, READ-ONLY) %d marchés", len(FOCUS_MARKETS))
       except Exception as e:
           logger.warning("market_flow init échec (ignoré): %s", e)
           self._flow_monitor = None
   ```
3. **`run()` démarrage** — après le démarrage du thread stream (~l.444), ajoute :
   ```python
   if self._flow_monitor is not None:
       self._flow_monitor.start()
   ```
4. **`run()` boucle** — juste après le bloc `if self.fast_scan is not None or self._stream_client is not None: … _process_stream_consensus()` (~l.482), AVANT « # 5. Détecter clusters », ajoute :
   ```python
   # 4c. Flux de marché (v4_trades) → momentum (READ-ONLY, sans node)
   if self._flow_monitor is not None:
       try:
           sigs = self._flow_monitor.drain_and_detect(
               getattr(self.config, "market_flow_min_volume_usdc", 25000.0),
               getattr(self.config, "market_flow_min_imbalance", 0.60),
           )
           from hyper_smart_observer.dydx_v4.market_flow import build_cluster_from_flow
           for sig in sigs:
               mark = self._mark_prices.get(sig.market)
               if mark and mark > 0:
                   self._evaluate_cluster(build_cluster_from_flow(sig, mark, now_ms))
       except Exception as e:
           logger.debug("market_flow: %s", e)
   ```
5. **`get_status()`** — juste après le bloc `status["stream"] = {…}` (~l.862), ajoute :
   ```python
   if self._flow_monitor is not None:
       try:
           status["market_flow"] = dict(self._flow_monitor.stats)
       except Exception:
           pass
   ```
6. **`stop()`** (~l.1539) — ajoute `if self._flow_monitor is not None: self._flow_monitor.stop()`.
7. **UI** `simulation_v2.html` — dans le rendu du panneau « État du scan » (cherche le bloc
   qui écrit déjà `status.stream` / fills), ajoute une ligne :
   `Flux marché : {market_flow.trades_seen} trades · {market_flow.signals} signaux`.
8. **Tests** `tests/dydx_v4/test_market_flow.py` (imite `test_stream_consensus.py`) :
   - `parse_trades` extrait `(side,size,price)` et **ignore** les entrées invalides ;
   - `MarketFlowWindow.add/prune` retire bien les trades plus vieux que `window_ms` ;
   - `detect_flow_signals` : sous le seuil de volume OU de déséquilibre ⇒ rien ; au-dessus
     ⇒ 1 `FlowSignal`, direction `LONG` si achat≥vente sinon `SHORT` ;
   - `build_cluster_from_flow` : `origin=="stream"`, `market_id`/`side` corrects, `is_fresh`.

**VÉRIFICATION Phase 1 :**
- `python -m pytest tests/dydx_v4/test_market_flow.py -q` passe, et `tests/dydx_v4/ -q` reste vert.
- Lecture : avec `market_flow_enabled=True`, l'observer s'abonne `v4_trades` sur `FOCUS_MARKETS`,
  agrège, et passe des `ClusterSignal(origin="stream")` à `_evaluate_cluster` ⇒ des positions
  paper peuvent s'ouvrir.
- `get_status()["market_flow"]` existe ; l'UI affiche la ligne « Flux marché ».
- `DYDX_MARKET_FLOW=0` (ou `market_flow_enabled=False`) ⇒ comportement **identique** à avant.

---

## PHASE 2 — Scanner PLUS de wallets, PLUS vite (sans saturer la boucle)

**Pourquoi.** L'utilisateur veut « scanner à mort de wallets ». Aujourd'hui le poll REST est
volontairement plafonné à `self._shortlist[:50]` (l.877) pour ne pas saturer la boucle ; le
volume doit venir des chemins **WS** (fast_scanner abonne jusqu'à `fast_scanner_hot_capacity`
wallets ; le flux de marché couvre déjà 100 % des trades). Objectif : augmenter la couverture
**de façon configurable et mesurable**, sans dégrader la latence.

**D'abord : lis et rapporte (ne modifie rien tant que tu n'as pas compris).**
Lis `fast_scanner.py`, `fast_scan_integration.py`, `wallet_harvester.py`. Dans le rapport,
note : comment `hot_capacity` est appliqué (combien de wallets sont réellement abonnés en WS),
comment `track_shortlist()` et `refresh_discovery()` alimentent le set suivi, et comment
`_merge_harvester_into_shortlist()` (observer) élargit `self._shortlist`.

**Étapes précises (toutes gardées + configurables) :**
1. **Rendre le cap REST configurable** (sans le baisser) : `config.py` ajoute
   `rest_poll_cap: int = 50` (env `DYDX_REST_POLL_CAP`) ; dans `_poll_shortlist_live`
   remplace `self._shortlist[:50]` par `self._shortlist[: getattr(self.config,"rest_poll_cap",50)]`.
2. **Augmenter le plafond WS** : laisse `fast_scanner_hot_capacity` configurable (déjà le cas)
   mais vérifie que fast_scanner abonne **réellement** jusqu'à cette capacité (corrige si un
   sous-plafond codé en dur l'empêche). Ne mets pas de valeur géante par défaut : garde 500,
   l'utilisateur pourra monter via `DYDX_FAST_SCANNER_HOT_CAPACITY`.
3. **Mesure de couverture** : ajoute dans `get_status()` un bloc `status["scan"]` qui expose
   des compteurs déjà disponibles : `discovery_wallets=len(self._shortlist)`,
   `ws_tracked` (depuis `fast_scan.stats()` si dispo), `rest_polled=rest_poll_cap`,
   et reprend `flow.trades_seen`/`stream.fills_seen`. (Lecture seule.)
4. **Harvester → décision** : confirme/branche que `_merge_harvester_into_shortlist` ajoute
   bien les wallets découverts (Cosmos) jusqu'à `max_decision_wallets` sans doublons (dedupe
   par adresse). Si un doublon ou un plafond bloque l'élargissement, corrige (gardé).

**VÉRIFICATION Phase 2 :**
- Tests existants verts + un test ajouté : `rest_poll_cap` est respecté ; le merge harvester
  déduplique par adresse et respecte `max_decision_wallets`.
- `get_status()["scan"]` expose les compteurs de couverture (vérifiable en lecture).
- `DYDX_FAST_SCANNER=0` ⇒ comportement REST inchangé ; aucune régression de latence par défaut.

---

## PHASE 3 — Moteur de décision : MOINS de trades, mais PLUS PROPRES

**Pourquoi (objectif quant).** Le but n'est pas de forcer des entrées : c'est de **filtrer**
les mauvais signaux et ne garder que les frais, cohérents, **liquides**, avec **edge net
positif après coûts** (frais + spread + slippage + latence + dégradation de copie). Ne promets
jamais un PnL positif ; optimise la probabilité d'un PnL paper réaliste.

**Contrainte forte :** tu **n'inventes pas** de nouvelle logique de scoring. Tu ajoutes
seulement les gates listées ci-dessous, **toutes configurables, toutes défaut-sûr**, en miroir
du style des gates existantes de `_evaluate_cluster` (mêmes `self._refuse("RAISON")`).

**Étapes précises :**
1. **Gate liquidité/spread pour le flux** : aujourd'hui la gate 8 (« honest fill ») fait déjà
   un fill depuis le carnet. Ajoute, AVANT l'ouverture, un refus explicite si le spread du
   carnet dépasse `max_spread_bps` (config `max_spread_bps: float = 8.0`, env `DYDX_MAX_SPREAD_BPS`)
   ou si la profondeur au prix est insuffisante pour `PAPER_NOTIONAL_USDT`. Réutilise la
   fonction de carnet déjà utilisée par `_honest_entry_price` (ne crée pas de nouvel appel
   réseau). Raison de refus : `SPREAD_TOO_WIDE` / `BOOK_TOO_THIN`.
2. **Qualité du signal flux** : `config.py` ajoute `flow_min_trades: int = 12`
   (env `DYDX_FLOW_MIN_TRADES`). Dans la branche flux (origin=="stream" issue du flow),
   refuse si `cluster.total_notional_usdc` < `market_flow_min_volume_usdc` (déjà filtré amont,
   mais re-checké) **et** si le nombre de trades agrégés < `flow_min_trades`. Pour transmettre
   le nombre de trades, mets-le dans `signal_strength`/un champ déjà présent, ou ajoute un
   attribut optionnel sur `ClusterSignal` (défaut None) — sans casser les autres constructeurs.
3. **Marché mal mappé** : conserve le refus `NO_ORACLE_PRICE` (déjà présent) ; vérifie qu'un
   ticker inconnu de `_mark_prices` est bien refusé et compté dans `no_trade_reasons`.
4. **Fraîcheur** : conserve la gate 2 (`STALE_SIGNAL`). Pour le flux, `signal_age_ms=0` par
   construction — c'est correct (le flux est temps réel) ; ne l'assouplis pas ailleurs.

**VÉRIFICATION Phase 3 :**
- Un test par gate ajoutée : `test_spread_gate_refuses_wide`, `test_book_too_thin_refused`,
  `test_flow_min_trades_refused`. Tous verts.
- Lecture : un marché trop spreadé / trop fin / un flux trop faible est **refusé** et apparaît
  dans `no_trade_reasons`. Les seuils sont configurables ; défaut-sûr (gates OFF si non armées
  via valeurs neutres) ⇒ pas de régression des tests existants.

---

## PHASE 4 — Ouvertures/fermetures réalistes & PnL honnête (verrouiller par tests)

**Pourquoi.** « Si on perd en sim, on perdrait sur le mainnet. » Donc le PnL paper doit être
calculé honnêtement : fill jamais au mid (déjà le cas), frais comptés **une seule fois** à
l'entrée et à la sortie, PnL long/short correct, exits ATR + time-stop + coupe-circuit actifs
aussi pour les positions issues du flux.

**Contrainte :** tu ne changes PAS la formule d'exits/PnL qui marche. Tu **ajoutes des tests
qui verrouillent** le comportement correct, et tu ne corriges QUE si un test révèle un bug.

**Étapes précises :**
1. **Tests de non-régression PnL** dans `tests/dydx_v4/` :
   - `test_pnl_long_short` : LONG gagne si prix monte / perd si baisse ; SHORT l'inverse
     (utilise `PaperPositionState.calculate_pnl`).
   - `test_fees_not_doubled` : frais entrée + sortie comptés chacun une fois (pas deux), via
     `TAKER_FEE_BPS` ; total cohérent.
   - `test_modes_isolated` : les PnL TEST/REPLAY/BACKTEST ne se mélangent jamais avec le LIVE
     (vérifie la séparation déjà prévue par `mode`).
2. **Exits pour le flux** : vérifie que `_check_exits`, `_check_stale_positions` et le
   coupe-circuit (`risk_policy`, si armé) s'appliquent aussi aux positions ouvertes via le
   flux (origin=="stream"). Corrige seulement si un test montre qu'une position flux échappe
   aux exits.
3. **Cooldown/anti-churn** : si `risk_policy_enabled`, vérifie que `reopen_cooldown_seconds`
   et l'anti-scalper s'appliquent aussi aux entrées flux (la gate 0 est en tête de
   `_evaluate_cluster`, donc déjà couverte — confirme par un test).

**VÉRIFICATION Phase 4 :**
- `test_pnl_long_short`, `test_fees_not_doubled`, `test_modes_isolated` verts.
- Lecture : une position flux peut être fermée par SL/TP/trailing/time-stop ; le coupe-circuit
  bloque de nouvelles entrées après pertes consécutives / drawdown.

---

## PHASE 5 — UI « État du scan » complète et lisible (read-only)

**Pourquoi.** L'utilisateur veut voir, en noms simples, que ça scanne et que ça décide.

**Étapes précises (`src/hl_observer/ui/static/simulation_v2.html`) :**
1. Dans le panneau « État du scan », affiche, à partir de `/api/dydx/status` :
   wallets découverts (`scan.discovery_wallets`), suivis temps réel (`scan.ws_tracked`),
   pollés REST (`scan.rest_polled`), **Flux marché** (`market_flow.trades_seen` / `.signals`),
   fills stream (`stream.fills_seen`), et le top des raisons de NO_TRADE (`no_trade_reasons`).
2. Garde les positions ouvertes avec **PnL latent live** (déjà fourni par
   `get_open_positions()` : `mark_price` + `unrealized_pnl_usdc`).
3. Aucune nouvelle dépendance ; aucun appel autre que `/api/dydx/status|positions|wallets` ;
   strictement lecture seule (aucun bouton qui poste un ordre).

**VÉRIFICATION Phase 5 :** le panneau rend toutes les sources sans erreur console ; rien
dans l'UI ne peut déclencher un ordre (lecture seule confirmée).

---

## PHASE 6 — VÉRIFICATION FINALE + RAPPORT (critère de fin global)

1. **Tous les tests verts :** `python -m pytest tests/dydx_v4/ -q`.
2. **Audit sécurité** (doit ne rien renvoyer d'exécutable) :
   `grep -rniE "place_order|sign\(|private_key|mnemonic|seed|withdraw|deposit|wallet[_ ]?connect" hyper_smart_observer/dydx_v4/`
   → seules des occurrences en commentaires/docstrings/noms de refus sont tolérées ; aucun
   code qui signe/envoie/détient une clé.
3. **Garde paper :** `run()` commence toujours par `assert_paper_only(self.config)`.
4. **Flags défaut-sûr :** mettre tous les nouveaux flags à OFF/neutre reproduit le
   comportement d'avant (tests le prouvent).
5. **Rapport** `docs/audit/CODEX_CHANGES_REPORT.md` (en **français**) avec :
   fichiers modifiés ; bugs/problèmes trouvés ; corrections appliquées ; tests lancés
   (+ résultat) ; limites restantes ; prochaines étapes ; et la **confirmation sécurité** :
   « 0 ordre réel, 0 argent réel, 0 clé privée, 0 signature, 0 dépôt/retrait ».
6. Mets à jour `docs/migration/DYDX_V4_ARCHITECTURE.md` (ajout du flux de marché) et
   `docs/migration/DYDX_V4_SAFETY.md` si nécessaire.

**FAIT =** Phases 1→6 terminées, `tests/dydx_v4/` 100 % vert, audit sécurité propre, rapport écrit.

---

### NOTE OPÉRATIONNELLE
La sandbox de l'agent précédent ne pouvait pas exécuter pytest (disque saturé) ; **lance les
tests toi-même** à chaque phase et corrige tout rouge avant de continuer. Travaille par petits
commits (un par phase) pour pouvoir revenir en arrière sans rien perdre.
