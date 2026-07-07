# HyperSmart - integration categorie 2 arbitrage / price difference

Date: 2026-06-29

## Objectif

Brancher les repos "Arbitrage Cross-Exchange / Hyperliquid / Price Difference" dans HyperSmart sans lancer leur execution native. Les repos restent installes localement sous `runtime/research/github_repos_v24`; HyperSmart utilise des adaptateurs paper-only compatibles avec la simulation locale.

## Repos verifies dans le manifest local

| Repo | Id local | Statut runtime |
|---|---|---|
| Jackhuang166/hyberliquid-arbitrage-bot | `28_jackhuang166_hyberliquid_arbitrage_bot` | installe, profil `ext_jack_hl_arbitrage_spread` |
| Jackhuang166/hyberliquid-arbitrage | `29_jackhuang166_hyberliquid_arbitrage` | installe, profil `ext_jack_hl_arbitrage_alt` |
| rustjesty/hyperliquid-drift-arbitrage-bot | `30_rustjesty_hyperliquid_drift_arbitrage_bot` | installe, profil `ext_hl_drift_funding_spread` |
| notlelouch/ArbiBot | `31_notlelouch_arbibot` | installe, profil `ext_arbibot_cross_exchange_spread` |
| gajesh2007/funding-arb-bot | `32_gajesh2007_funding_arb_bot` | installe, profil `ext_funding_arb_basis` |
| hummingbot/hummingbot | `33_hummingbot` | installe, profil `ext_hummingbot_market_making_framework` |
| Drakkar-Software/Triangular-Arbitrage | `34_drakkar_triangular_arbitrage` | installe, profil `ext_drakkar_triangular_arbitrage` |
| enarjord/passivbot | `35_enarjord_passivbot` | installe, profil `ext_passivbot_grid_risk` |
| pydevtop/interexchange-arbitrage-bot | `36_pydevtop_interexchange_arbitrage_bot` | installe, profil `ext_interexchange_arbitrage` |
| ramilexe/crypto-arbitrage-bot | `37_ramilexe_crypto_arbitrage_bot` | installe, profil `ext_crypto_arbitrage_spread` |

## Cablage effectue

- `src/hl_observer/connectors/standard.py` transporte maintenant `strategy_id`, `coin`, `side`, `notional_usdt`, `reference_price` et `metadata` dans les ordres paper.
- `src/hl_observer/connectors/paper_execution_connector.py` renvoie ces champs dans `PaperOrderResult`; les decisions ne sont plus anonymes.
- `src/hl_observer/strategies/controller.py` injecte automatiquement le `strategy_id` dans la requete paper si le module appelant l'a oublie.
- `src/hl_observer/strategies/fusion_runtime.py` priorise les profils categorie 2:
  - price discrepancy: Jack Hyperliquid -> ArbiBot -> interexchange -> crypto spread;
  - funding: Hyperliquid/Drift -> funding arb;
  - triangular: Drakkar -> interexchange -> crypto spread.
- `src/hl_observer/ui/fusion_persistent_adapter.py` peut maintenant materialiser en position de simulation les ordres paper arbitrage `LONG/SHORT` avec prix de reference reel.

## Garde-fous

- Les repos externes ne sont pas executes/importes directement dans le hot path.
- Aucune cle, signature, wallet-connect, endpoint de trading ou `/exchange`.
- Les signaux `HEDGE`, `ARBITRAGE` multi-leg et chemins triangulaires restent en diagnostic si HyperSmart ne peut pas les marquer comme une position simple et honnete.
- Les positions materialisees sont taguees `EXTERNAL_GITHUB_ARBITRAGE_PAPER`, `paper_only=True`, `read_only=True`, `external_action=False`.

## Tests

- `tests/test_connector_standard.py`
- `tests/test_external_github_strategy_bridge.py`
- `tests/test_fusion_strategy_runtime.py`
- `tests/test_ui_simulation_status_fast.py`

Resultat du lot cible: `31 passed`.

Safety:

- `python -m hyper_smart_observer.app.main --safety-check` -> OK
- `python -m hyper_smart_observer.app.main --audit-safety` -> OK

## Limites restantes

- Le PnL positif n'est jamais garanti: la simulation reflete les positions paper et les prix disponibles.
- Les strategies multi-leg complètes doivent rester diagnostiques tant que le moteur ne sait pas representer chaque jambe proprement dans le portefeuille paper.
- Pour voir le nouveau cablage dans l'UI deja ouverte, il faut redemarrer `LANCER_HYPERSMART.cmd` afin de recharger le code Python.
