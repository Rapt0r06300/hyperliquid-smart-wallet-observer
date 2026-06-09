# AUDIT PRODUCTION : HYPERLIQUID PNL NÉGATIF
**Auteur : Jules (Mode Audit Production + Python Senior + Quant)**
**Date : 2026-06-08**

## 1. RÉSUMÉ EXÉCUTIF
La simulation paper actuelle présente un PnL net négatif de **-61.50 USDC** pour un volume d'événements massif (1.4M). Le problème majeur n'est pas une absence d'edge brut, mais une **hémorragie de frais (73.69 USDC)** qui dépasse l'avantage théorique. Le moteur souffre de signaux périmés (stale), d'une mauvaise réconciliation des positions (lifecycle), et d'une contamination par des actifs illiquides ou mal mappés.

## 2. ANALYSE DES CHIFFRES (POST-MORTEM)
*   **Événements totaux :** 1,406,901
*   **Refus :** 1,355,550 (96.3%)
*   **Acceptés/Replay :** 51,351
    *   *Négatifs :* 28,453
    *   *Positifs :* 14,277
*   **PnL Net Global :** -61.495485 USDC
*   **Frais Totaux :** 73.687279 USDC (Plus de 100% du PnL brut perdu en frais).

### Top Pertes par Coin
1.  **HYPE :** -15.14 USDC (Cooldown nécessaire)
2.  **BTC :** -8.67 USDC
3.  **ZEC :** -7.98 USDC
4.  **SOL :** -6.94 USDC
5.  **CASH:WTI / XYZ:CL :** Pertes sur actifs exotiques mal gérés.

## 3. CAUSES RACINES IDENTIFIÉES

### A. Fraîcheur des Signaux (Critical)
Un bug majeur permet à des `PAPER_CONSENSUS_ADD_REPLAYED` d'être acceptés avec un `signal_age_ms` de **55,155 ms** (exemple sur HYPE). Dans un marché comme Hyperliquid, 55 secondes d'âge signifie que l'edge a disparu et que le bot "chasse" le prix à son désavantage.

### B. Cycle de Vie et Réconciliation (High)
La cause `NO_MATCHING_PAPER_POSITION_FOR_CLOSE` est massive. Cela indique que le moteur perd la trace des positions (mauvaises clés, mauvaise persistance) ou qu'il rate l'OPEN original mais tente de suivre le CLOSE du leader.

### C. Drag des Frais et Edge Insuffisant (High)
Le bot accepte des trades où l'edge restant est trop faible par rapport aux coûts fixes (fees + spread + slippage). Les micro-ajustements (ADD/REDUCE) génèrent des frais sans ajouter de valeur statistique.

### D. Contamination des Données (Medium)
Les wallets de test (`0x111`, `0xaaaa`, etc.) polluent les statistiques "Live". De plus, le moteur ne distingue pas assez strictement les modes LIVE, REPLAY et TEST_FIXTURE dans ses calculs de performance.

## 4. PLAN DE REMÉDIATION

### Phase 1 : Isolation et Pureté
*   Séparation stricte `run_mode` et `source_quality`.
*   Blacklistage immédiat des wallets factices.
*   Blacklistage des actifs `CASH:*`, `XYZ:*`, `@*`.

### Phase 2 : Barrière de Fraîcheur
*   `MAX_LIVE_SIGNAL_AGE_MS = 4000` (4 secondes).
*   `HARD_MAX_LIVE_SIGNAL_AGE_MS = 8000`.
*   Aucune exception, même pour le consensus.

### Phase 3 : Filtre de Rentabilité Stricte
*   Edge minimum = `max(30 bps, 3x total_cost_bps)`.
*   Prise en compte réelle du carnet L2 pour le slippage.
*   Cooldown automatique sur coin/wallet après perte.

### Phase 4 : Fiabilité du Lifecycle
*   Refonte de la clé de position : `mode|wallet|coin|side`.
*   Gestion propre des `orphan_close_events`.
*   Interdiction des ADD orphelins (sans OPEN préalable).

## 5. RÉALISATIONS TECHNIQUES
*   **Indexer Persistant** : Création de `HyperliquidIndexerService` pour une collecte temps-réel via WebSocket et récupération REST pour combler les manques.
*   **Unification de la Logique** : Centralisation des calculs de PnL et de prix dans `src/hl_observer/utils/simulation_utils.py` pour garantir une cohérence parfaite entre le moteur, l'UI et les replays.
*   **Comptabilité Stricte** : Révision des formules pour inclure systématiquement les coûts d'entrée alloués et les frais de sortie réels, éliminant les biais de "profit virtuel".

## 6. ENGAGEMENT SÉCURITÉ
*   **0 ORDRE RÉEL.**
*   **0 SIGNATURE / CLÉ PRIVÉE.**
*   **SIMULATION PAPER UNIQUEMENT.**
*   **READ-ONLY STRICT.**
