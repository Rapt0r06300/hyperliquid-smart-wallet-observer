# Fusion #03 : MrFadiAi/Polymarket-bot (TS, MIT) — risk management v3.1
Source: https://github.com/MrFadiAi/Polymarket-bot — 4 stratégies, gestion de risque pro.

## ⭐ OR oublié / haute valeur (paper-only)
- **A1. Protection multi-couches de perte (mock halts)** : Daily 5% (pause 60min), Monthly 15% (pause 30j), Drawdown 25% depuis le pic (pause 7j), **Total 40% = HALT permanent (restart manuel)**. → ADAPT: `risk_engine/loss_halts.py` (mock USDC) — état RiskHalt visible au dashboard.
- **A2. Smart Money Filtering — seuils exacts** : win rate ≥ **60%**, PnL total ≥ **$500**, **profit factor ≥ 1.5x**, **consistency score ≥ 70%** (perf récente), **no whale trade = max 30% du PnL sur un seul trade** (one-big-win guard). → KEEP/CORE pour `scoring/wallet_score_v2` (vérifier/ajuster ces seuils + consistency + one_big_win_ratio).
- **A3. Dynamic Position Sizing par série** : base 2% du capital, **−20% par perte consécutive**, **+10% par gain consécutif** (cap 5%). → ADAPT: `paper_trading/sizing_policy.py` (sizing adaptatif selon streak), mock USDC.
- **A4. Trade floor / min trade** ($1.50, sortie garantie) + **comptabilité des frais de gas** (seuil de profit relevé pour couvrir les coûts). → KEEP (edge après coûts + notional min).
- **A5. Dashboard risk panel** : indicateur LIVE/DRY-RUN, panneau de risque (daily/monthly/drawdown/streak, BREACHED/OK), toggles de stratégie. → ADAPT (read-only): panneau d'état de risque + toggles de scan (sans bouton réel).

## BAN
Clé privée, USDC réel, **panic sell**, **live toggle vers réel**, auto-copy réel, MATIC/gas réel.

## Note
Confirme notre doctrine "moins de trades mais plus propres" : ne suivre QUE des leaders prouvés (60%/PF1.5/consistency/anti-one-big-win), sizing prudent, halts. Tout en **paper** chez nous.
