# Fusion #05 : yangyuan-zhen/PolyWeather (Python/TS, AGPL-3.0) — stack quant temps-réel production
Source: https://github.com/yangyuan-zhen/PolyWeather. ⚠️ **AGPL-3.0 = copyleft : NE PAS copier le code, extraire seulement les idées/architecture.**

## ⭐ OR oublié / haute valeur (patterns temps-réel & ops — pile dans nos points faibles)
- **A1. Dashboard temps-réel par SSE + révisions + replay de gaps** : `/api/events?since_revision=...`, patches `city_observation_patch.v1`, replay des courts gaps via event log (Redis Stream en prod / **SQLite en fallback local**). → ADAPT: passer le dashboard de polling lourd → **SSE patch + numéro de révision + replay de gap** depuis un event log SQLite local. Corrige "tick ancien"/empilement /overview lent à la racine. Module: `dashboard/event_stream.py` + `dashboard/revision_log.py`.
- **A2. ⭐ Politique de fraîcheur (LE correctif "écran qui saute")** : refresh **piloté par l'observation** (les patches fusionnent sans overlay de chargement) ; **détail périmé BLOQUÉ pendant le refresh** (l'utilisateur ne lit jamais une vieille donnée) ; **catch-up au retour d'onglet** (foreground refresh) ; fallback 60s **uniquement pour les charts visibles**. → ADAPT direct dans `dashboard/stale_state_policy.py` : ne jamais afficher de détail stale, fusionner les patches sans flicker, refresh foreground au retour.
- **A3. ⭐ Probabilité calibrée + "model-market difference"** : `mu` + distribution de buckets, calibration EMOS/CRPS, et **différence modèle−marché** (prob modèle − prob implicite marché ; positif = edge au-dessus du prix). → ADAPT: framer notre EDGE comme "prob de notre modèle vs prob implicite du marché" + **probabilité calibrée**. Module: `scoring/calibrated_probability.py`.
- **A4. ⭐ Calibration shadow→primary** : EMOS entraîné **hors-ligne** sur une copie de la DB prod ; promotion seulement si `ready_for_promotion=true` ; **`emos_shadow` avant `emos_primary`**. → ADAPT: notre calibration de confiance s'entraîne hors-ligne, mode **shadow** d'abord, promotion gardée (jamais d'entraînement lourd dans le hot path).
- **A5. ⭐ Explication de décision = "evidence chain + invalidation rules + confirmation rules"** : headline, confiance, chemins base/upside/downside, prochain point d'observation, **chaîne de preuve, modes d'échec, règles de confirmation/invalidation**. → ADAPT: enrichir nos NoTrade/Signal avec **failure modes + règles d'invalidation + règles de confirmation** (au-delà du simple reason code). Renforce DecisionLedger.
- **A6. Observabilité légère** : `/healthz`, `/api/system/status`, `/metrics`. → KEEP: endpoints santé/metrics read-only.
- **A7. SQLite runtime primaire** ; JSON/JSONL legacy seulement pour migration/fallback ; runtime data hors git (`RUNTIME_DATA_DIR`). → KEEP (déjà notre doctrine d'hygiène).
- **A8. Multi-cache snappy** : page memory cache + localStorage + backend short-TTL + SSE replay + foreground refresh. → ADAPT (dashboard réactif).

## BAN / DEFER
- BAN: paiements onchain (USDC checkout, subscription, points, multi-chain), pricing commercial, ops payantes.
- DEFER (domaine météo): DEB, TAF/METAR, EMOS météo spécifiques — garder le **pattern** (agrégation multi-sources + calibration + bucket distribution), pas le contenu météo.
- Licence AGPL: idées seulement, aucun code copié.

## Verdict
Très riche. C'est le repo qui répond le mieux à "on a oublié plein de choses" : **SSE+révisions+replay**, **politique de fraîcheur anti-stale**, **probabilité calibrée + edge modèle-marché**, **calibration shadow→primary**, **explication décision avec invalidation/confirmation**, **/healthz//metrics**.
