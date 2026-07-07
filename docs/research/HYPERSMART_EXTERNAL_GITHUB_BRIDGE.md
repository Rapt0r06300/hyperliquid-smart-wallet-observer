# HyperSmart external GitHub bridge

## Objectif

Les depots externes demandes sont installes tels quels sous :

`runtime/research/github_repos_v24/`

HyperSmart ne modifie pas leur logique ni leurs reglages amont. Le bridge ajoute
une couche locale qui lit le manifeste d'installation et expose les familles de
strategies comme profils prioritaires pour la simulation Hyperliquid.

Etat verifie le 2026-06-29 :

- depots demandes dans `tools/install_external_github_repos.ps1` : 37 ;
- depots installes/presents : 34 ;
- profils paper actifs dans la simulation : 34 ;
- URLs GitHub indisponibles : 3 (`06_composio...`, `18_neron888...`, `19_terauss...`).

## Regle de priorite

Les profils issus des depots externes passent avant les profils internes dans :

`src/hl_observer/strategies/strategy_catalog.py`

Les modules internes restent disponibles comme fallback. Le but est de donner la
priorite aux idees des depots installes sans lancer leur code tel quel.

## Securite runtime

- execution externe directe : false
- ordre reel : false
- cle privee : false
- signature : false
- wallet connect : false
- mode : paper local Hyperliquid
- donnees : reelles ou etat vide honnete

Le bridge n'importe pas les packages externes et ne lance pas leurs scripts. Il
preserve les sources amont et declare uniquement des profils paper adaptes au
moteur HyperSmart.

## Repos installes et branches

| Repo local | Statut attendu | Role bridge |
|---|---|---|
| 01_cloddsbot | installe | agentic research loop, decision logging |
| 02_harrier_prediction_markets_toolkits | installe | toolkit de decision et features |
| 03_mrfadiai_polymarket_bot | installe | copy rules legeres |
| 04_polymarket_lp_tool | installe | garde-fou liquidite/quote |
| 05_polyweather | installe | contexte externe recherche |
| 06_composio_polymarket_kalshi_arbitrage_bot | indisponible | profil pending desactive |
| 07_awesome_prediction_market_tools | installe | index recherche |
| 08_polyterm | installe | terminal/operations |
| 09_mlmodelpoly | installe | shadow model local |
| 10_polyrec | installe | recommender shadow wallet/coin |
| 11_prediction_market_backtesting | installe | backtest/no-lookahead |
| 12_polybot | installe | regles bot legeres |
| 13_polymarket_agents | installe | agent framework recherche |
| 14_tradingview_lightweight_charts | installe | charting/metagraph |
| 15_chaininsighter_solana_copy_trading_bot | installe | copy session, latence, session UX |
| 16_immutal0_solana_copytrading_bot | installe | filtres wallets, caps risque |
| 17_rezzecup_whale_wallet_mirror_copy_trader | installe | whale mirror prioritaire |
| 18_neron888_polymarket_copy_trading_bot | indisponible | profil pending desactive |
| 19_terauss_polymarket_copy_trading_bot | indisponible | profil pending desactive |
| 20_warp_id_solana_trading_bot | installe | risk process |
| 21_tony_42069_trader_tony_v4 | installe | SL/TP, trailing, scan autonome |
| 22_freqtrade | installe | backtest discipline |
| 23_octobot | installe | framework strategie |
| 24_jlowo_gengar_polymarket_bot | installe | decisions structurees |
| 25_djienne_polymarket_bot | installe | logging, resilience |
| 26_jonmaa_btc_polymarket_bot | installe | regles mono-marche |
| 27_carlosibcu_polymarket_kalshi_btc_arbitrage_bot | installe | reconciliation multi-source |
| 28_jackhuang166_hyberliquid_arbitrage_bot | installe | arbitrage Hyperliquid paper |
| 29_jackhuang166_hyberliquid_arbitrage | installe | arbitrage Hyperliquid alternatif |
| 30_rustjesty_hyperliquid_drift_arbitrage_bot | installe | funding/spread Hyperliquid-Drift |
| 31_notlelouch_arbibot | installe | spread cross-exchange |
| 32_gajesh2007_funding_arb_bot | installe | funding basis |
| 33_hummingbot | installe | market-making framework paper |
| 34_drakkar_triangular_arbitrage | installe | triangular arbitrage graph |
| 35_enarjord_passivbot | installe | grid/risk sizing paper |
| 36_pydevtop_interexchange_arbitrage_bot | installe | interexchange arbitrage |
| 37_ramilexe_crypto_arbitrage_bot | installe | crypto spread arbitrage |

## Fichiers branchement

- `src/hl_observer/strategies/external_github_bridge.py`
- `src/hl_observer/strategies/strategy_catalog.py`
- `src/hl_observer/strategies/__init__.py`
- `src/hl_observer/ui/status_routes.py`
- `src/hl_observer/ui/static/simulation_v2.html`

## Verification

Le statut live expose maintenant :

`/api/simulation/status -> external_github_bridge`

Ce bloc affiche le nombre de repos installes, les profils actives, les profils
desactives et les chemins locaux des depots amont.
