# Stratégie — Copy Follow (paper-only)

- **Hypothèse** : un leader smart-money RÉCEMMENT ACTIF qui ouvre/ajoute une position porte un edge court terme copiable si on entre frais.
- **Signal** : delta lifecycle OPEN/ADD d'un wallet de la shortlist (consensus 2+ wallets = voie facile ; 1 wallet fort = edge net ≥ 22 bps).
- **Filtres (deny-by-default)** : source utilisable (SourceRegistry) ; signal frais (≤ 45 s) ; mid disponible ; liquidité ≥ 0.22 ; spread borné ; edge net ≥ 10 bps après frais+spread+slippage+latence+dégradation de copie ; lifecycle non-UNKNOWN, pas de flip ambigu, pas de close orphelin.
- **Edge attendu** : faible mais POSITIF après coûts ; volume d'entrées via diversification (60 slots, 40 USDT).
- **Invalidations** : signal trop vieux (SIGNAL_TOO_OLD), edge net ≤ seuil (EDGE_REMAINING_TOO_LOW), liquidité/spread (MARKET), conflit REST/WS (SOURCE_CONFLICT). Sortie : SL/TP disciplinés (TP +30 bps / SL −40 bps / trailing 25) + suivi close leader.
- **Sécurité** : 100 % paper, read-only, aucun ordre réel. PnL réalisé au VRAI prix marché, jamais fabriqué.
