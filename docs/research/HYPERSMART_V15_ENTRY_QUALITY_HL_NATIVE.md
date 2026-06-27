# HyperSmart V15 — Qualité d'entrée (edge-engine) + leviers NATIFS Hyperliquid

> Lecture du **code** edge_engine.py + features.py de mlmodelpoly + leviers spécifiques
> Hyperliquid (funding, OI, oracle, frais, TWAP). But : maximiser ROI/PnL en simulation
> RÉELLE sur HL. Tout **gratuit, paper-only, read-only, 0 ordre réel** ; shadow d'abord.

## Pépites du code edge_engine.py (scoreur d'entrée 0-100, transposable)
- **Veto-first** : quality_mode≠OK, warmup pas prêt, gap détecté, données stale, profondeur
  faible, spread trop large, pas de prix → NONE. (pipeline de veto unifié AVANT le score).
- **Biais global** multi-TF (1h+15m + alignment + micro-stage ACCEL) ; **triggers UP/DOWN**
  = biais OK + **déviation AVWAP** au-delà d'un seuil + **≥1 confirmation**.
- **Edge-score 0-100** pondéré : biais +25, régime TREND +15, alignement +10, mispricing vs
  AVWAP (≤+25), RVOL spike +10, impulse +10, **absorption +10**, basis +5 ; **pénalités** :
  RSI suracheté/survendu −15, **depth dégradée −10**, basis contraire −10. Seuil d'action 60.
- **Confiance** = score/100, **réduite en régime RANGE (×0.8)** et faible alignement (×0.7).
- **Pénalité de spread** par 100 bps + veto liquidité/spread.

## Features confirmées (features.py)
absorption_score (panique+stabilisation), **spike-detector 5s (z-seuil 2.0)**, **OBI + change
10s/30s**, **liquidations 30s/60s (qty/count)**, CVD futures+spot, microprice, AVWAP 15m,
**gap-detection** entre horodatages aggTrade.

## Leviers NATIFS Hyperliquid (pas encore minés — gros potentiel ROI)
- **Funding** : sens/ampleur → filtre (éviter de payer un funding très défavorable, préférer le
  recevoir) + **funding intégré au PnL paper** (carry).
- **Open interest (OI)** : delta d'OI + prix = vrai mouvement (confirmation d'entrée).
- **Oracle vs mark** : premium/écart HL comme signal.
- **Fenêtre de funding** (countdown) : ne pas entrer juste avant un flip de funding.
- **Paliers de frais HL** (maker/taker selon volume 14 j) → coûts exacts dans l'edge net.
- **Ordres TWAP HL** : détecter les gros TWAP (flux informé) comme signal.

## Manques EXIT / SIZING / DATA (vers un logiciel "parfait")
Trailing ATR, prises de profit partielles + breakeven, pyramiding sur confirmation, **plafonds
d'exposition corrélée** (ne pas empiler des longs corrélés) + bêta net, slippage par coin,
filtre de session/heure, détection gaps de séquence, largeur de scan multi-coins bornée.

## Méga-roadmap = étapes #186→#207 (voir progression)
Axe Q (qualité d'entrée), Axe HL (natif Hyperliquid), Axe EXIT/SIZING, Axe DATA/BREADTH.
Chaque étape : module pur testé → shadow → autoritatif via flag. Aucune promesse de PnL.

## Avancement 2026-06-25 — #171→#209 FAITS (purs, testés, shadow-first)

Tout **gratuit, paper-only, read-only, 0 ordre / 0 clé / 0 signature**. 44 modules purs,
86 tests verts (test_v14_freshness_timing 15 + test_v14_scan_microstructure 11 +
test_v15_entry_quality 20 + test_v15_exit_sizing 9 = 55 nouveaux ce lot, +31 des lots V14 précédents).

### V14 scan/scrape/microstructure (#171-185)
ws_subscription_audit (#171 backoff borné + anti-backpressure + détection de gaps de séquence),
market_discovery_ranking (#172 tri par volume/liquidité), leaderboard_robustness (#173 validation +
seuils smart-money + dédup), multi_source_merge (#174 fusion explorer/WS/leaderboard + provenance +
confiance), consensus_window (#175 fenêtre chaude 4 s — **câblé live** dans routes via l'âge du
signal, flag `HYPERSMART_V14_CONSENSUS_WINDOW_AUTHORITATIVE`), rate_limit_semaphore (#176 25 req/10 s
+ budget de poids REST), proxy_health (#177 santé/rotation/repli), depth_spread_gate (#178 top1/top3 +
tiers de spread), entry_microstructure_shadow (#179 OBI + eat-flow, contexte seul), decision_cadence
(#180 slow-loop + cooldown + budget fenêtre), entry_event_recorder (#181 buffer/flush + rejeu fenêtres),
exec_cost_promotion (#182), entry_quality_gate (#183 smart-money + depth), scoring_calibration_promotion
(#184 maker/DEB/EMOS), feature_vector_promotion (#185 eat_flow/basis/accumulate/sigma).

### V15 qualité d'entrée / natif HL / sortie & sizing (#186-209)
edge_score (#186 0-100 veto-first + points + pénalités), avwap (#187), multi_confirmation (#188),
absorption (#189), spike_detector (#190 z-score 5 s), obi_delta (#191), rsi_overheat (#192),
regime_confidence (#193 RANGE→réduite), funding (#194 filtre + carry PnL), oi_delta (#195),
oracle_mark_premium (#196), funding_window (#197 countdown), fee_tiers (#198 paliers HL configurables),
twap_detector (#199), atr_trailing_stop (#200), scale_out (#201), pyramiding (#202),
correlated_exposure (#203 caps corrélés + bêta net), slippage_model (#204 par coin), session_filter
(#205), data_quality_gap (#206 veto gaps), scan_breadth (#207 bornée), metrics_endpoint (#208 /metrics
read-only), leader_hotness (#209 forme récente).

### Câblage live vs prêt-à-câbler (honnête)
- **Câblés live (flag OFF par défaut)** dans `routes.opportunity_metrics` : #168 whale primaire,
  #170 warmup (no-op tant que bars HTF non plumbés), #175 fenêtre de consensus (fonctionnel via l'âge).
- **Gates testés prêts à promouvoir** (#178/#182/#183/#188/#197/#205/#206) : la fonction
  `apply_*_promotion` existe et est prouvée par tests ; câblage live au fur et à mesure que la donnée
  (profondeur/spread, exec-cost, OI, oracle, funding, session) est plumbée dans le hot-path — chaque
  promotion ne peut QUE réduire des trades, jamais en créer.
- Tous les `apply_*_promotion` : intersection plus stricte ; `None` (inconnu) ne bloque jamais ;
  shadow (flag=0) = no-op exact → le moteur ne peut pas être cassé en activant un flag.

## Câblage LIVE 2026-06-25 (#210-216) — données réelles dans le hot-path

Investigation (#210): dans `routes.opportunity_metrics`, données RÉELLES dispo = `liquidity_score`,
`score.edge_remaining_bps`, `score.simulated_notional_usdt`, `confidence` (→ leader_score),
`cluster_notional`, `age_ms`. La profondeur L2 par coin n'est PAS dans cette closure (seulement
`mid_prices`) ; `liquidity_score` est le proxy de liquidité réel déjà utilisé comme gate.

**Câblés LIVE (flags OFF par défaut = shadow ; ne peuvent QUE réduire les trades) :**
- **#182 exec-cost net-edge** (le plus gros levier) : `net = edge_remaining − [frais HL 4.5 + demi-spread 1.5
  + slippage(taille RÉELLE, liquidité RÉELLE via slippage_model)]`. Refuse si `net < HYPERSMART_V14_EXEC_MIN_NET_EDGE_BPS`
  quand `HYPERSMART_V14_EXEC_COST_AUTHORITATIVE=1`. Champs shadow exposés : `shadow_exec_cost_bps`,
  `shadow_net_edge_after_exec_bps`.
- **#183 qualité d'entrée** : `depth_ok = liquidity_score ≥ min_liquidity` (réel), `smart_money_ok =
  leader_score ≥ HYPERSMART_V14_SMART_MONEY_MIN_SCORE` (réel). Flag `HYPERSMART_V14_ENTRY_QUALITY_AUTHORITATIVE`.
- **#175 fenêtre de consensus** : déjà câblé (via l'âge du signal).
- **#167 liquidations (shadow)** : `shadow_liquidation_present` dérivé du marqueur `raw_json.liquidation`
  s'il existe, sinon `None` (pas de flux forceOrder public HL dans cette closure → honnête).
- **#168 whale primaire / #170 warmup** : câblés ; warmup reste no-op tant que les bars HTF ne sont pas
  threadés dans la closure (honnête, sans danger).

**Dashboard :**
- **#166 panneau fraîcheur** ajouté à `/api/v12/panels` (clé `freshness` : statut + histogramme d'âge +
  latence par étage, depuis les logs locaux).
- **#208 endpoint `/metrics`** read-only (texte Prometheus : positions ouvertes réelles + compteurs,
  `execution_forbidden=1`, `paper_local_only=1`).

**Limites honnêtes restantes :** #178 (top1/top3 + tiers de spread) et le warmup #170 attendent que la
profondeur L2 réelle et le contexte de bars HTF soient threadés dans `opportunity_metrics` (changement
d'infra plus large) ; en attendant, #183 couvre la profondeur via le proxy de liquidité réel. Aucun
chiffre fabriqué : demi-spread 1.5 bps et frais 4.5 bps sont des constantes conservatrices documentées.
