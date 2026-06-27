# AGENTS.md — consignes pour tout agent/IA travaillant sur HyperSmart Observer

**Règle n°1 (absolue, non négociable) : simulation paper uniquement.**
Aucun ordre réel, aucun argent réel, aucune clé privée, aucun seed/mnemonic, aucune
signature, aucun dépôt/retrait, aucun wallet-connect, aucun appel d'API privée de trading.
READ-ONLY, PAPER-ONLY, TESTNET-FIRST, DENY-BY-DEFAULT. Un signal n'est jamais un ordre ;
un paper-trade n'est jamais un ordre. Si une donnée est incertaine/trop vieille/incomplète : NO_TRADE.

## Périmètre
- Runtime par défaut : Hyperliquid (lecture seule `/info` + WebSocket public). dYdX v4 reste
  dormant/comparatif. Tout vient de prix réels du marché ; PnL paper en USDC fictif.
- Pas de faux PnL, pas de faux wallet, pas de fausse simulation. Honnêteté avant tout :
  ne jamais maquiller les chiffres, ne jamais promettre un PnL positif.

## Surface IA (lecture seule)
- Le modèle local (`ml/`) NOTE les trades (P(rentable)) et peut FILTRER, jamais ouvrir.
- L'explainer (`research/local_llm_explainer.py`, Ollama optionnel) explique offline ; jamais
  dans le chemin de décision. Aucune API LLM payante.

## Avant toute modif
1. inspecter Git ; 2. comprendre l'archi ; 3. protéger le local ; 4. documenter ; 5. coder
proprement ; 6. tester ; 7. vérifier que tout reste 100 % simulation (scan sécurité).

## Flags clés (tous OFF/sûrs par défaut)
- `HYPERSMART_V12_GATE_AUTHORITATIVE`, `HYPERSMART_V13_MODEL_AUTHORITATIVE` : gates contraignants
  (ne peuvent que RÉDUIRE/filtrer les trades, jamais en créer).
- `HYPERSMART_V13_OLLAMA_ENABLED` : explainer local (repli règles si absent).
