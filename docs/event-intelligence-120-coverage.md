# Event Intelligence — registre de couverture des 120 idées

Ce fichier est la source de vérité de couverture. **Implémenté** signifie que le contrat/code/garde-fou existe. Cela ne signifie jamais qu'un edge est rentable. La rentabilité exige ensuite des données, OOS et forward post-freeze.

| # | Idée gardée | Couverture technique | Implémentation | Preuve PnL |
|---:|---|---|---|---|
| 1 | Créer Event Intelligence / Global Regime Detector | foundation + worldmonitor + module_bridges | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 2 | Contrat ExternalEvent séparé | external_event.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 3 | Horloge causale retrieval/ingest | external_event.py + replay guards | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 4 | Archivage Data Vault | archive.py + source_discovery integration | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 5 | Conserver R1/R2 structurés | archive.py + WorldMonitorEvent.to_archive_record | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 6 | World Monitor comme méta-source | worldmonitor.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 7 | Sources primaires directes | direct_sources.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 8 | Pas de scraping UI principal | GET-only adapters/documentation | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 9 | News Leads Markets | candidates.py + module_bridges.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 10 | Prediction Leading | PredictionShiftTracker + candidates.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 11 | Polymarket read-only uniquement | worldmonitor prediction + no CLOB/private key | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 12 | Silent Divergence | regimes.py MICROSTRUCTURE_LED/UNEXPLAINED | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 13 | Taxonomie de régimes | regimes.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 14 | Velocity Spike | features.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 15 | Keyword/abnormal spike via baselines | features.py + validation numeric strata | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 16 | Convergence multi-source | corroboration/source_count features | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 17 | Triangulation | source diversity + corroboration metadata | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 18 | Corroboration latency | sequences.py/propagation timing | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 19 | OSINT rapide comme lead | World Monitor structured source; quality gates | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 20 | Inventaire sources non hardcodé | adapter reads payload metadata; no source-count constants | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 21 | Score de provenance | SourceTier + source metadata | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 22 | Diversité des sources | features.py source_diversity_ratio | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 23 | Déduplication événementielle | ExternalEvent keys + archive dedupe | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 24 | Révisions/corrections préservées | revision/supersedes_revision + archive | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 25 | Méthodologie versionnée | methodology_version | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 26 | CII non utilisé comme BUY/SELL | no directional World Monitor score path | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 27 | Scores IA = features seulement | classification metadata only | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 28 | Événements militaires/géopolitiques | ExternalEventType + World Monitor cross-source | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 29 | GPS jamming/spoofing | cross-source normalization maps to MILITARY | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 30 | Aviation/NOTAM comme contexte | cross-source/context architecture | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 31 | Maritime/AIS/chokepoints | SUPPLY_CHAIN event type/context | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 32 | Features supply-chain | event family/context + relevance mapping | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 33 | Infrastructure critique | INFRASTRUCTURE event type + relevance/context routing | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 34 | Infrastructure Cascade | INFRASTRUCTURE context/filter only; no direct order | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 35 | Internet outages/BGP/cyber | CYBER/OUTAGE types + context | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 36 | Cyber seulement si économiquement pertinent | asset relevance + module filters | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 37 | Catastrophes naturelles | USGS/EONET/GDACS direct adapters | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 38 | Mapping événement→actifs | regimes.map_event_to_assets | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 39 | Pas de causalité hardcodée | mapping routes attention only | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 40 | Macro/banques centrales | FRED adapter + MACRO type | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 41 | Macro Event Clock | macro.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 42 | Événements attendus vs surprises | MacroWindow phases + surprise score | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 43 | Prediction markets comme attentes | PredictionShiftTracker | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 44 | surprise_score | macro.py/regimes SurpriseContext | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 45 | Brancher d'abord Lead-Lag | module_bridges LeadLagEventContext | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 46 | External Event → Venue Price Discovery | price_discovery.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 47 | Mesurer first_venue | EventMarketReaction | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 48 | Mesurer reaction_latency_ms | EventMarketReaction | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 49 | Mesurer peak dispersion | price_discovery.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 50 | Mesurer edge half-life | price_discovery.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 51 | Mesurer edge restant sur HL | candidates.py executable room | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 52 | Profondeur avant/après événement | NativeMarketSnapshot depth/capacity in outcomes | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 53 | spread_expansion | executable spread components in outcomes | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 54 | depth_withdrawal | capacity/fill metrics support | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 55 | order-flow imbalance | existing microstructure remains composable via module bridge | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 56 | Volume/trades agressifs | existing native market data composable with event windows | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 57 | OI avant/après | event-window context feeds existing OI data | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 58 | Funding | event-window context feeds existing funding data | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 59 | Liquidations/cascades | LIQUIDATION_LED regime + existing liquidation modules | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 60 | Capacité exécutable | outcomes.py capacity_usd | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 61 | Event Intelligence comme filtre Cross-Venue | CrossVenueEventContext | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 62 | Event-conditioned Cross-Venue | module bridge + validation stratification | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 63 | Ne jamais relâcher coûts Cross-Venue | may_bypass_costs=False/capacity=False | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 64 | Brancher Copy-Vault | module_bridges.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 65 | leader_event_reaction_latency | measure_copy_vault_event_reactions | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 66 | leader_event_specialization | stats per event_family | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 67 | Comparer leaders hors événement | NO_EVENT controls available in validation | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 68 | Ne pas inférer information privilégiée | leader stats measure timing only | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 69 | Dataset événements négatifs | NO_EVENT/control observations | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 70 | Placebos timestamps | placebo_timestamps | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 71 | Randomiser labels/timestamps | permute_event_labels + shifted placebos | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 72 | Groupe NO_EVENT | select_no_event_controls | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 73 | Backtest par famille | stratify event_family | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 74 | Backtest par actif | stratify asset | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 75 | Backtest par venue | stratify venue | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 76 | Backtest par session | market_session_utc + stratify session | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 77 | Backtest par corroboration | stratify corroboration_count | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 78 | Backtest par source tier | stratify source_tier | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 79 | Backtest par surprise | stratify_numeric surprise_score | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 80 | Backtest par velocity | stratify_numeric velocity_zscore | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 81 | Backtest par prediction shift | stratify_numeric prediction_delta_pp | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 82 | Train/validation/OOS chronologiques | chronological_split | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 83 | Purged/embargo | purged_chronological_split | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 84 | Freeze paramètres | protocol.freeze_event_research | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 85 | Forward post-freeze | assert_forward_after_freeze + scoreboard forward | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 86 | N minimal + incertitude | independent_event_count + bootstrap_mean_ci | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 87 | PnL toujours NET | outcomes + canonical scoreboard | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 88 | Comparer à baseline Lead-Lag | incremental_effect | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 89 | PnL incrémental | incremental_vs_control/placebo | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 90 | Sharpe/PF/DD/ES/hit/capacité | canonical scoreboard + event bundle | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 91 | Rejeter edge mono-événement fragile | N indépendant + controls/placebos | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 92 | Scoreboard Event Edge | scoreboard.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 93 | UNMEASURABLE si coût manque | outcomes + canonical scoreboard | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 94 | Health/freshness World Monitor | health.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 95 | Événement stale non signalable | WorldMonitorEvent.usable_for_signal | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 96 | Source down ≠ aucun événement | health gaps/source_active separation | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 97 | Intelligence gaps | detect_intelligence_gap | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 98 | Couverture par famille | coverage_by_family | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 99 | Versionner mapping source/event | methodology_version + revision | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 100 | Architecture simple adaptateurs→normalisation→features | event_intelligence package boundaries | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 101 | Étudier/self-host World Monitor | documented adapter base/self-host-compatible architecture | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 102 | Ne pas intégrer AGPL aveuglément | integration uses API/contracts, no copied WM code | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 103 | Vérifier licence upstream | DirectSourceSpec attribution + docs policy | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 104 | World Monitor comme catalogue | direct_sources.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 105 | Mesurer valeur ajoutée World Monitor | compare_source_latency | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 106 | Garder primaire + WM selon rôle | primary adapters + aggregator bridge | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 107 | Événements positifs et négatifs | neutral event taxonomy | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 108 | Bibliothèque event→market response | archive + price_discovery + scoreboard | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 109 | Chercher séquences récurrentes | sequences.py | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 110 | Extraire séquences tradables seulement si répétées | summarize_patterns + validation | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 111 | Explicatif ≠ prédictif | causal regime classification | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 112 | Disponibilité avant entrée obligatoire | ingest_ts/decision gates | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 113 | LLM ne peut inventer preuve | no LLM-generated evidence path | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 114 | IA peut classifier, jamais preuve primaire | classification_confidence + raw_evidence_ref | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 115 | Versionner tout classifieur | methodology_version | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 116 | market relevance, pas BUY/SELL | map_event_to_assets | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 117 | Rares + fréquents séparables | stratification by family/sample | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 118 | World Monitor rend les edges plus sélectifs | module bridges only | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 119 | Ordre P0→P5 implémenté par couches | foundation→sources→validation→bridges | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |
| 120 | Succès = dollars nets prouvés | canonical scoreboard + incremental OOS/forward | ✅ Implémenté | ⏳ À prouver par données/OOS/forward |

## Règles de clôture

- Aucun item ne peut être supprimé silencieusement : on déduplique/classifie, on ne perd pas une idée retenue.
- Une brique non mesurable reste UNMEASURABLE ; jamais 0 par défaut.
- Les scores World Monitor et classifications ne sont jamais des ordres BUY/SELL.
- Les contrôles NO_EVENT, placebos, N indépendant, purge/embargo, OOS et forward restent obligatoires avant promotion.
- Le critère final n'est pas le nombre de features mais l'amélioration du **PnL net incrémental** après tous coûts, capacité, fill et latence.

## Câblage canonique modules ↔ Dataset V2

`event_intelligence.integration_registry` associe les 120 idées, sans trou, aux
familles `copy_vault`, `lead_lag`, `cross_venue_dislocation` et `arbitrage`, ainsi
qu'aux familles de données V2 nécessaires. Son digest est embarqué dans chaque
manifeste `external_events` produit par `collect_event_intelligence_v2.py`.

La collecte est publique, GET-only, paper/read-only et exécutée sur GitHub Hosted.
En l'absence de référence indépendante exacte, ces shards restent honnêtement
`PARTIAL`, `validation_allowed=false` et `proof_of_pnl_allowed=false`. Le câblage
structurel des 120 idées n'est donc jamais présenté comme une preuve de rentabilité.
