# Alina Smart Flow

**Research engine quantitatif strictement paper/read-only.**

Alina Smart Flow collecte des données réelles, reconstruit des conditions d'exécution réalistes, exécute replays/backtests/OOS/forward paper et mesure l'edge **net après coûts**. Aucun ordre réel ou testnet, aucune clé privée, aucune signature, aucun dépôt/retrait/transfert.

## Source de vérité

Spec canonique unique :

`docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`

Elle est mise à jour **en place**. Les anciens labels V6.x sont historiques et ne constituent pas des specs concurrentes.

Pour un agent de code, lire en priorité :

1. `SECURITY.md`
2. `AGENTS.md`
3. `CLAUDE.md`
4. la spec canonique
5. seulement les fichiers nécessaires au bloc courant

## Périmètre économique actif

Trois familles uniquement :

- **Copy-Vault**
- **Lead-Lag**
- **Cross-Venue Dislocation**

`Carry / Funding Carry = DISABLED_BY_SCOPE`.

Cible finale : **>= +4.00 USD NET/jour prouvés par famille séparément**, sans compensation. États honnêtes : `PROVEN`, `MORE_DATA`, `UNMEASURABLE`, `KILL`.

## Repositories

### Repo principal

`Rapt0r06300/hyperliquid-smart-wallet-observer` · `main`

Il possède :

- runtime actif `src/hl_observer/`
- logique économique/paper
- orchestration et contrats de campagne
- surface opérateur
- replay/backtest/OOS/forward/PnL proof/scoreboard

`hyper_smart_observer/` reste legacy/compatibilité : ne pas y créer une architecture concurrente.

### Dataset V2

`Rapt0r06300/alina-smartflow-datasets-v2` · `main`

Il possède :

- actifs Dataset V2 durables
- manifests/checkpoints/leases de campagnes cloud lourdes
- publication de données et receipts
- heavy data plane GitHub-hosted

Un même campaign ne doit jamais avoir deux vérités mutables concurrentes.

## Phase Orchestrator

Le contrat canonique utilise :

- `IDLE` — aucun nouveau travail lourd
- `COLLECT` — collecte uniquement
- `ANALYZE` — gel de la collecte puis analyse

Pipeline cible :

`DRAIN -> QUALITY -> REPLAY -> BACKTEST -> OOS -> FORWARD_PAPER -> PNL_PROOF -> SCOREBOARD -> DONE`

Le HEAD du 27 septembre 2026 contient la fondation `src/hl_observer/control_plane/`, notamment :

- `phase_state.py`
- `phase_controller.py`
- `phase_cli.py`
- `resumable_campaign.py`
- `dispatch_receipt.py`
- `campaign_adapters.py`
- `module_pnl_proof.py`

La présence de ces fichiers ne ferme pas automatiquement les `OPEN-*`/`WKR-*`. La spec reste l'autorité du travail restant.

## Cloud et PC utilisateur

Toute automatisation cloud Alina doit être **GitHub-hosted uniquement**.

Interdit depuis ChatGPT Work/GitHub :

- `runs-on: self-hosted`
- réveiller ou utiliser le PC utilisateur
- SSH/tunnel/agent local vers le PC
- dépendre d'un fichier/service/processus disponible uniquement sur le PC

Un chemin local n'est valable que si l'utilisateur le lance explicitement. Une mission Work Cloud ne doit jamais en dépendre.

## Données et preuve économique

Un workflow vert n'est pas une preuve de qualité.

Selon le chemin économique, Alina doit préserver ce qui est nécessaire : timestamps exchange/receive/monotonic, clock offset/RTT/uncertainty, BBO/L2/trades, snapshot/delta, séquences/gaps/duplicates, fee provenance, tick/lot/min-notional/multiplier, depth/VWAP/capacity/quote age, manifests et checksums.

La preuve économique doit prendre en compte les coûts et contraintes pertinents : fees, spread, slippage, latency, partial/missed fills, liquidity, capacity, funding pertinent, exits, drawdown, causality, no-lookahead, OOS, forward et effective-N.

**Missing != 0. Unknown != healthy. Backtest positif != preuve économique.**

## Sources prioritaires

- Hyperliquid
- Binance
- Bybit
- OKX
- Gate
- Bitget

CCXT reste discovery-only lorsqu'aucun chemin natif d'exécution/replay n'est explicitement prévu.

## Agents et quota minimal

- un seul agent principal par défaut
- pas de swarm/subagents/multi-agent sauf demande explicite
- lire la spec une fois puis travailler par sections ciblées
- préférer grep/parsers/scripts/calculs/tests déterministes aux appels modèle
- éviter les rapports intermédiaires
- réutiliser l'existant avant de créer du nouveau
- après deux échecs identiques, changer de méthode

Si la mission demande explicitement **implémentation totale d'abord, validation globale ensuite**, les tests peuvent être écrits/modifiés pendant l'implémentation mais exécutés en phase finale. Les exigences de preuve et de sécurité restent obligatoires avant fermeture globale.

## Sécurité

Voir `SECURITY.md`.

Résumé non négociable :

- 0 ordre réel
- 0 ordre testnet
- 0 `/exchange` opérationnel
- 0 clé privée/seed
- 0 signature
- 0 dépôt/retrait/transfert
- paper/read-only + fail-closed

## Documents clés

| Document | Rôle |
|---|---|
| `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md` | Spec canonique et backlog normatif |
| `AGENTS.md` | Instructions compactes pour agents |
| `CLAUDE.md` | Compatibilité pour agents lisant CLAUDE.md |
| `SECURITY.md` | Invariants no-real-trade |
| `src/hl_observer/` | Runtime actif |
| `src/hl_observer/control_plane/` | Phase/campaign control plane |

## Principe directeur

**Mesurer l'edge réel sans se mentir.**

Le but n'est pas seulement de faire tourner du code, mais d'obtenir des résultats économiquement reproductibles avec données fiables, coûts réalistes, replays/backtests rigoureux, OOS/forward et validation fail-closed.
