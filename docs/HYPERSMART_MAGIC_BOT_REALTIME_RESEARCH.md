# HyperSmart Magic Bot Realtime Research

Date: 2026-05-27

Ce document transforme la recherche publique sur les copy bots Hyperliquid en exigences safe pour HyperSmart Observer.

## Sources consultees

- LearnWithMeAI, "I Built a Claude Trading Bot That Copies Hyperliquid Millionaires": architecture en 3 jobs, top 5 wallets, polling 5 minutes, paper portfolio et reports.
- MaxIsOntoSomething/Hyperliquid_Copy_Trader: monitoring temps reel, sizing proportionnel, caps notionnels, deviation de prix, copie des positions existantes.
- zkOSAI/hyperliquid-copy-trading-bot: watchMyTrades, ignore les fills anterieurs au demarrage, taille fixe USDC, leverage cap, logs.
- oasisprotocol/template-rofl-hl-copy-trader: marque les snapshots initiaux comme deja vus, ignore `isSnapshot`, traite seulement les nouveaux fills/orders, polling positions, memoire bornee.
- Discussions publiques Hyperliquid/AI trading: le point faible recurrent est le gap signal -> execution: timing, funding, slippage, profondeur, fills partiels.

## Ce qui est reproductible en mode safe

HyperSmart peut reproduire la logique observable, pas l'execution:

1. Job A: decouverte et shortlist de leaders.
2. Job B: boucle realtime read-only, snapshots, deltas, SignalCandidate.
3. Job C: dashboard, no-trade report, portefeuille local simule.

Les idees reprises:

- polling 300 secondes par defaut, plus UI refresh 1 seconde;
- public trade stream pour decouvrir des wallets actifs;
- shortlist de leaders, pas surveillance user-specific massive;
- deltas OPEN_LONG, OPEN_SHORT, ADD, INCREASE, REDUCE, CLOSE_LONG, CLOSE_SHORT, UNKNOWN;
- ignore tout evenement anterieur au lancement de la simulation;
- edge_remaining_bps obligatoire;
- sizing plafonne sur capital local 1000 USDT;
- refus si signal trop vieux, edge non mesurable, prix deja parti, liquidite faible, exposition max atteinte;
- no_trade_report pour chaque refus.

## Notation realtime ajoutee

Le module `src/hl_observer/copying/realtime_magic_score.py` calcule:

- `signal_freshness_score`: 1.0 quand le delta est tres frais, 0.0 au-dela de la fenetre realtime.
- `leader_expected_edge_bps`: estimation prudente derivee du leader, du consensus et de la confiance.
- `leader_consistency_factor`: facteur de qualite du leader.
- `consensus_factor`: bonus borne quand plusieurs wallets ouvrent meme coin/meme direction dans la fenetre.
- `copy_degradation_bps`: delai + spread + slippage + frais + liquidite + adverse selection + crowding + funding.
- `edge_remaining_bps`: edge attendu apres tous les couts.
- `risk_score`: penalise degradation, deviation de prix et faible liquidite.
- `simulated_notional_usdt`: taille locale plafonnee.

Decision:

- `ACCEPT_LOCAL_SIMULATION`: uniquement simulation locale, jamais ordre.
- `REJECT_NO_TRADE`: refus documente.

## Formule minimale

```text
edge_remaining_bps =
  leader_expected_edge_bps
  * leader_consistency_factor
  * signal_freshness_score
  * consensus_factor
  - delay_cost_bps
  - spread_bps
  - slippage_bps
  - fee_bps
  - liquidity_penalty_bps
  - adverse_price_move_bps
  - adverse_selection_penalty_bps
  - crowding_penalty_bps
  - funding_penalty_bps
```

## Refus obligatoires

- `EDGE_UNMEASURABLE`
- `STALE_SIGNAL`
- `EDGE_REMAINING_TOO_LOW`
- `PRICE_DEVIATION_TOO_HIGH`
- `LIQUIDITY_TOO_LOW`
- `COPY_DEGRADATION_TOO_HIGH`
- `MAX_OPEN_PAPER_TRADES_REACHED`
- `MAX_EXPOSURE_REACHED`
- `REDUCE_OR_CLOSE_NOT_ENTRY`
- `UNKNOWN_DELTA`

## Gestion du risque

Capital local: 1000 USDT simules.

Sizing:

- fenetre realtime dure: 10 minutes maximum, avec penalite de delai continue;
- position de base: environ 3% du capital;
- cap par position: 50 USDT;
- cap exposition totale: 200 USDT;
- min position: 5 USDT;
- consensus peut augmenter legerement la taille, mais reste borne;
- leader notional peut reduire la taille;
- aucun leverage executable n'est produit.

Persistance:

- la session simulation est conservee dans `data/runtime/ui_simulation_state.json`;
- une reconnexion ou un redemarrage du serveur UI ne remet plus automatiquement le PnL a 0;
- la remise a zero doit etre volontaire via action locale `reset_simulation_session`.

Important: le consensus n'est pas une garantie. Trop de wallets sur le meme trade augmente aussi le risque de crowding.

## Ce qui reste interdit

- aucune route `/exchange` operationnelle;
- aucune signature;
- aucune cle privee;
- aucun ordre reel;
- aucun testnet executor actif;
- aucun mainnet;
- aucun LLM dans le hot path execution;
- aucune promesse de profit.

## Limites connues

- Les trades publics ne prouvent pas toujours une ouverture/fermeture complete.
- Un openOrder seul est seulement du contexte, pas une execution.
- La simulation depend de la fraicheur des deltas locaux.
- Un PnL positif local ne garantit rien pour le futur.
- Les effets reels de latence, partial fill, funding et slippage peuvent etre pires que la simulation.
