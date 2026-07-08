# AGENTS.md — consignes pour tout agent/IA travaillant sur HyperSmart Observer

**Règle n°1 (absolue, non négociable) : mainnet lecture seule, testnet verrouillé.**
Aucun ordre mainnet, aucun argent réel, aucune clé privée exposée, aucun seed/mnemonic,
aucun dépôt/retrait, aucun wallet-connect mainnet, aucun appel d'API privée mainnet.
READ-ONLY-MAINNET, LOCAL-DECISION, TESTNET-ONLY, DENY-BY-DEFAULT. Un signal n'est jamais
un ordre mainnet ; un paper-trade n'est jamais un ordre. Si une donnée est incertaine/trop
vieille/incomplète : NO_TRADE.

## Mise à jour testnet contrôlé (2026-07-04)
- La simulation paper complète reste disponible seulement comme garde-fou/legacy minimal.
- La cible produit devient : observer Hyperliquid mainnet en lecture seule, décider localement,
  puis exécuter uniquement sur un environnement testnet à fausse monnaie via une couche
  `testnet_executor` verrouillée.
- Toute exécution externe doit refuser si l'environnement n'est pas explicitement testnet, si
  `REAL_MAINNET_TRADING=false`, `TESTNET_ONLY=true` et `CONFIRM_TESTNET_EXECUTION=true` ne sont
  pas satisfaits, ou si les plafonds `MAX_TESTNET_NOTIONAL` / `MAX_OPEN_TESTNET_POSITIONS` sont
  dépassés.
- Les adaptateurs testnet doivent passer par une interface `TestnetExchangeAdapter`, être
  testables avec un fake adapter, journaliser chaque décision, et ne jamais contourner
  DecisionEngine/RiskEngine.
- Les clés/signatures testnet ne doivent jamais être écrites dans le repo, les logs, le
  dashboard ou la documentation. Toute vraie signature testnet est une phase future explicite,
  isolée et auditée ; le code par défaut reste fake-adapter/refusant.

## Périmètre
- Runtime par défaut : Hyperliquid mainnet en lecture seule (`/info` + WebSocket public). dYdX v4
  reste dormant/comparatif. Les décisions viennent de prix réels du marché ; le PnL complet est
  lu côté testnet quand l'exécuteur testnet est explicitement activé, sinon la simulation locale
  reste minimale et honnête.
- Pas de faux PnL, pas de faux wallet, pas de fausse simulation. Honnêteté avant tout :
  ne jamais maquiller les chiffres, ne jamais promettre un PnL positif.

## Surface IA (lecture seule)
- Le modèle local (`ml/`) NOTE les trades (P(rentable)) et peut FILTRER, jamais ouvrir.
- L'explainer (`research/local_llm_explainer.py`, Ollama optionnel) explique offline ; jamais
  dans le chemin de décision. Aucune API LLM payante.

## Avant toute modif
1. inspecter Git ; 2. comprendre l'archi ; 3. protéger le local ; 4. documenter ; 5. coder
proprement ; 6. tester ; 7. vérifier que mainnet reste 100 % lecture seule et que testnet reste
verrouillé par configuration, fake adapter et tests de refus.

## Flags clés (tous OFF/sûrs par défaut)
- `HYPERSMART_V12_GATE_AUTHORITATIVE`, `HYPERSMART_V13_MODEL_AUTHORITATIVE` : gates contraignants
  (ne peuvent que RÉDUIRE/filtrer les trades, jamais en créer).
- `HYPERSMART_V13_OLLAMA_ENABLED` : explainer local (repli règles si absent).

## Où trouver le reste (2026-07-08)
- **État actuel, méthode de travail, architecture, config, commandes, feuille de route :**
  **`docs/ETAT_ET_FEUILLE_DE_ROUTE.md`** (document maître, à jour).
- **Objectif condensé :** `OBJECTIF.md` (racine).
- **Règles complètes de l'agent :** `CLAUDE.md` (racine, source de vérité).
- **Replay / recherche de scénarios (après les 48h) :** `docs/REPLAY_SCENARIO_SEARCH.md`.
- **Config détaillée :** `docs/CONFIG_FLAGS.md`.
